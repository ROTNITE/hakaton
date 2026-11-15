"use strict";
const $ = (id) => document.getElementById(id);
const form = $("configForm");
const palette = {ink:"#1b3d33", green:"#28735a", blue:"#4d8fba", orange:"#e9784d", red:"#d4624f"};
let state = null, world = null, running = false, timer = null, pending = null, changing = false;
let batchJob = null, batchResult = null, batchTimer = null, traceOpen = false;
let mapBackground = null;
const fmt = (v,d=1) => v === null || v === undefined || !Number.isFinite(v) ? "—" : v.toLocaleString("ru-RU",{maximumFractionDigits:d,minimumFractionDigits:d});
const modeName = (mode) => mode === "scout" ? "Разведка" : "Эвакуация";
const reasons = {running:"В работе",all_found:"Все найдены · дроны вернулись",all_rescued:"Все доставлены",time_limit:"Лимит времени",no_tasks_remaining:"Задачи завершены",energy_exhausted:"Энергия исчерпана",no_reachable_sector:"Нет доступных секторов"};
const tags = {sweep:"SWEEP",nearest:"GREEDY",coverage:"COVERAGE",deadline:"EDD",local:"LOCAL SEARCH",nsga2:"EVOLUTION"};

async function api(path, data) {
  const options = data === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json","X-Rescue-Benchmark":"1"},body:JSON.stringify(data)};
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}
function notice(error) { $("notice").textContent = error.message || String(error); $("notice").hidden=false; }
function clearNotice() { $("notice").hidden = true; }
function readConfig() {
  if (!form.reportValidity()) throw new Error("Проверьте диапазоны настроек слева.");
  const result = {};
  for (const [key,value] of new FormData(form)) result[key] = key === "scout_policy" ? value : Number(value);
  result.density /= 100;
  return result;
}
function fillForm(config) {
  for (const [key,value] of Object.entries(config)) if (form.elements.namedItem(key)) form.elements.namedItem(key).value = key === "density" ? Math.round(value*100) : value;
}
function setControls() {
  $("playBtn").textContent = running ? "Ⅱ Пауза" : "▶ Запустить";
  $("playBtn").disabled = changing || !state || state.done;
  $("stepBtn").disabled = changing || running || !!pending || !state || state.done;
  $("resetBtn").disabled = changing;
  $("applyBtn").disabled = changing;
  document.querySelectorAll("[data-mode]").forEach(b => {b.disabled=changing;b.classList.toggle("active",b.dataset.mode===state?.mode);b.setAttribute("aria-current",b.dataset.mode===state?.mode?"page":"false");});
  $("traceBtn").disabled = !state?.runs.find(r=>r.id==="nsga2")?.trace?.length;
  $("runStatus").textContent = changing ? "Подготовка…" : state?.done ? "Миссия завершена" : running ? "Выполняется" : state?.time ? "Приостановлено" : "Готов к запуску";
  $("runStatus").classList.toggle("running",running);
}
function stop() { running=false; clearTimeout(timer); setControls(); }
async function advance(steps) {
  if (pending || changing || !state || state.done) return;
  const request = api("/api/step",{session:state.session,steps});
  pending=request;setControls();
  try { accept(await request); }
  catch(error) {stop();notice(error);}
  finally {pending=null;setControls();}
}
async function tick() {
  if (!running) return;
  const speed=Number($("speed").value), steps=Math.max(1,Math.round(speed/10));
  const started=performance.now();
  await advance(steps);
  if (state?.done) stop();
  if (running) timer=setTimeout(tick,Math.max(10,1000*steps/speed-(performance.now()-started)));
}
async function reset(mode, config) {
  if (changing) return;
  stop();changing=true;setControls();clearNotice();
  try {
    if (pending) await pending.catch(()=>{});
    const result=await api("/api/reset",{mode,config});
    accept(result,true);fillForm(result.config);
  } catch(error) {notice(error);}
  finally {changing=false;setControls();}
}
function accept(result,rebuild=false) {
  const newWorld = !!result.world;
  state=result;
  if (newWorld) {world=result.world;makeBackground();}
  if (rebuild || !$("arenas").children.length || $("arenas").dataset.mode!==state.mode) buildArenas();
  $("modeDescription").textContent=state.mode==="scout" ? "Карта местности известна, координаты людей скрыты. Дроны открывают новые участки по четырём разным стратегиям. Наземные роботы на этой странице не участвуют." : "Разведка продолжается, пока роботы спасают уже найденных людей. Все алгоритмы эвакуации получают одинаковую информацию от одних и тех же дронов.";
  $("sharedPolicyLabel").hidden=state.mode==="scout";
  $("clockTime").textContent=String(state.time).padStart(3,"0");
  $("clockLimit").textContent=state.config.horizon;
  $("timeProgress").style.width=`${100*state.time/state.config.horizon}%`;
  renderMetrics();renderMaps();renderTable();renderVerdict();
  if(traceOpen) renderTrace();
  setControls();
}
function buildArenas() {
  const root=$("arenas");root.replaceChildren();root.dataset.mode=state.mode;
  state.runs.forEach((run,index)=>{
    const card=document.createElement("article");card.className="arena"+(run.id==="nsga2"?" nsga":"");card.dataset.algorithm=run.id;
    card.innerHTML=`<div class="arena-top"><div class="algorithm-title"><span class="algorithm-index">0${index+1}</span><h3>${run.label}</h3></div><span class="algorithm-tag">${tags[run.id]}</span></div><div class="map-frame"><canvas class="map-canvas" aria-label="Карта: ${run.label}"></canvas><span class="map-label">SEED ${state.config.seed} / ${world.width} × ${world.height}</span></div><div class="metrics-row"><div><span class="mini-label">${state.mode==="scout"?"Найдено":"Спасено"}</span><span class="metric-value count-value">0 <small>/ ${state.config.people}</small></span></div><div><span class="mini-label">Энергия</span><span class="metric-value energy-value">0</span></div><div><span class="mini-label">Балл / 100</span><span class="metric-value score-value">0</span></div></div><div class="arena-foot"><span class="finish-value">Ожидание запуска</span><span class="cpu-value">CPU <strong>0.0</strong> мс</span></div><div class="chart-wrap"><canvas class="mini-chart" aria-label="${state.mode==="scout"?"Найденные":"Спасённые"} по времени: ${run.label}"></canvas><div class="chart-caption"><span>${state.mode==="scout"?"Обнаруженные":"Доставленные"} люди / время</span><span>Общая шкала 0–${state.config.horizon} с</span></div></div>`;
    root.append(card);
  });
}
function renderMetrics() {
  state.runs.forEach(run=>{
    const card=document.querySelector(`[data-algorithm="${run.id}"]`),m=run.metrics;
    card.querySelector(".count-value").innerHTML=`${state.mode==="scout"?m.found:m.rescued} <small>/ ${state.config.people}</small>`;
    card.querySelector(".energy-value").textContent=fmt(m.energy,0);
    card.querySelector(".score-value").textContent=fmt(m.score,2);
    card.querySelector(".cpu-value").innerHTML=`CPU <strong>${fmt(m.planning.mean_ms,1)}</strong> мс / план`;
    card.querySelector(".finish-value").textContent=m.finished_at===null ? `Покрытие ${fmt(m.coverage*100,0)}%` : `${fmt(m.finished_at,0)} с · ${reasons[m.status]}`;
    drawHistory(card.querySelector(".mini-chart"),run);
  });
}
function canvasContext(canvas) {
  const rect=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;
  const width=Math.max(1,Math.round(rect.width)),height=Math.max(1,Math.round(rect.height));
  if(canvas.width!==Math.round(width*dpr)||canvas.height!==Math.round(height*dpr)){canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);}
  const ctx=canvas.getContext("2d");ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
  return {ctx,w:width,h:height};
}
function makeBackground() {
  mapBackground=document.createElement("canvas");mapBackground.width=world.width*8;mapBackground.height=world.height*8;
  const c=mapBackground.getContext("2d");
  world.terrain.forEach((row,y)=>row.forEach((value,x)=>{
    c.fillStyle=value===0?"#9baaa0":value>1?"#c8cdb9":"#e3e9db";c.fillRect(x*8,y*8,8,8);
    if(value===0){c.fillStyle="#b4c0b1";c.fillRect(x*8+1,y*8+1,6,2);c.fillStyle="#7f9486";c.fillRect(x*8+6,y*8+2,2,6);}
    if(value>1){c.fillStyle="#aeb89d";c.fillRect(x*8+2,y*8+2,2,2);c.fillRect(x*8+5,y*8+5,1,1);}
  }));
}
function maskArray(hex) {
  const arr=new Uint8Array(world.width*world.height);
  for(let n=0;n<hex.length;n++){const v=parseInt(hex[hex.length-1-n],16);for(let b=0;b<4;b++)if(v&(1<<b))arr[n*4+b]=1;}
  return arr;
}
function renderMaps() {
  if(!state||!world)return;
  state.runs.forEach(run=>{
    const canvas=document.querySelector(`[data-algorithm="${run.id}"] .map-canvas`);
    const {ctx:c,w,h}=canvasContext(canvas);
    c.fillStyle="#e8ede4";c.fillRect(0,0,w,h);
    const s=Math.min((w-18)/world.width,(h-18)/world.height),ox=(w-world.width*s)/2,oy=(h-world.height*s)/2;
    const point=p=>[ox+(p[0]+.5)*s,oy+(p[1]+.5)*s];
    c.imageSmoothingEnabled=false;c.drawImage(mapBackground,ox,oy,world.width*s,world.height*s);
    const seen=maskArray(run.coverage_mask);
    c.fillStyle="#41574b25";
    for(let y=0;y<world.height;y++)for(let x=0;x<world.width;x++)if(!seen[y*world.width+x])c.fillRect(ox+x*s,oy+y*s,s+.1,s+.1);
    if(s>5){c.strokeStyle="#71857512";c.lineWidth=.5;c.beginPath();for(let x=0;x<=world.width;x++){c.moveTo(ox+x*s,oy);c.lineTo(ox+x*s,oy+world.height*s);}for(let y=0;y<=world.height;y++){c.moveTo(ox,oy+y*s);c.lineTo(ox+world.width*s,oy+y*s);}c.stroke();}
    if($("showPaths").checked){
      run.robots.forEach(r=>{if(!r.path?.length)return;c.beginPath();c.strokeStyle="#28735a88";c.lineWidth=1.4;c.setLineDash([3,3]);c.moveTo(...point([r.x,r.y]));r.path.slice(1).forEach(p=>c.lineTo(...point(p)));c.stroke();c.setLineDash([]);});
      run.drones.forEach(d=>{if(!d.goals?.length)return;c.beginPath();c.strokeStyle="#4d8fba80";c.lineWidth=1;c.setLineDash([4,4]);c.moveTo(...point([d.x,d.y]));d.goals.forEach(p=>c.lineTo(...point(p)));c.stroke();c.setLineDash([]);});
    }
    world.people.forEach(p=>{
      const status=run.people[p.id].status;if(status==="rescued"||status==="carried")return;
      if(status==="hidden"&&!$("showHidden").checked)return;
      const [x,y]=point([p.x,p.y]),r=Math.max(2.4,Math.min(4,s*.45));
      if(status==="expired"){if(!run.people[p.id].discovered_at&&!$("showHidden").checked)return;c.strokeStyle="#868577";c.lineWidth=1.5;c.beginPath();c.moveTo(x-r,y-r);c.lineTo(x+r,y+r);c.moveTo(x+r,y-r);c.lineTo(x-r,y+r);c.stroke();}
      else{c.beginPath();c.arc(x,y,r,0,2*Math.PI);c.fillStyle=status==="hidden"?"#a4908b":palette.red;c.fill();c.strokeStyle="#fff9";c.lineWidth=1;c.stroke();}
    });
    const [bx,by]=point(world.base),baseSize=Math.max(9,Math.min(13,s*1.4));
    c.fillStyle=palette.green;c.fillRect(bx-baseSize/2,by-baseSize/2,baseSize,baseSize);c.fillStyle="#ecf7cb";c.fillRect(bx-1,by-baseSize*.3,2,baseSize*.6);c.fillRect(bx-baseSize*.3,by-1,baseSize*.6,2);
    run.robots.forEach(r=>{
      const [x,y]=point([r.x,r.y]),size=Math.max(5,Math.min(8,s*.8));c.fillStyle=r.mode==="stranded"?"#8b7759":palette.green;c.strokeStyle="#fff";c.lineWidth=1;c.fillRect(x-size/2,y-size/2,size,size);c.strokeRect(x-size/2,y-size/2,size,size);
      if(r.person!==null&&["inbound","unloading"].includes(r.mode)){c.fillStyle=palette.orange;c.beginPath();c.arc(x+size/2,y-size/2,2.8,0,Math.PI*2);c.fill();}
    });
    run.drones.forEach(d=>{
      const [x,y]=point([d.x,d.y]);c.strokeStyle="#6096bd13";c.lineWidth=1;c.beginPath();c.arc(x,y,state.config.radius*s,0,2*Math.PI);c.stroke();
      const g=d.goals?.[0],angle=g?Math.atan2(g[1]-d.y,g[0]-d.x)+Math.PI/2:0;
      c.save();c.translate(x,y);c.rotate(angle);c.beginPath();c.moveTo(0,-5);c.lineTo(4,4);c.lineTo(0,2);c.lineTo(-4,4);c.closePath();c.fillStyle=palette.blue;c.fill();c.strokeStyle="#fff";c.lineWidth=.8;c.stroke();c.restore();
    });
    c.strokeStyle="#758f7040";c.lineWidth=1;c.strokeRect(ox-.5,oy-.5,world.width*s+1,world.height*s+1);
  });
}
function drawHistory(canvas,run){
  const {ctx:c,w,h}=canvasContext(canvas),left=24,top=9,right=8,bottom=18,pw=w-left-right,ph=h-top-bottom;
  const x=t=>left+t/state.config.horizon*pw,y=n=>top+(1-n/state.config.people)*ph;
  c.strokeStyle="#e9eee3";c.lineWidth=1;
  [0,.5,1].forEach(f=>{c.beginPath();c.moveTo(left,top+f*ph);c.lineTo(w-right,top+f*ph);c.stroke();});
  c.font="9px Consolas,monospace";c.fillStyle="#8a998d";c.textAlign="right";c.fillText(state.config.people,left-6,top+3);c.fillText("0",left-6,h-bottom+3);c.textAlign="left";c.fillText("0",left,h-3);c.textAlign="right";c.fillText(state.config.horizon+" с",w-right,h-3);
  const points=run.history;if(!points.length)return;
  const color=run.id==="nsga2"?palette.green:"#658f84";
  c.beginPath();c.moveTo(x(0),y(0));let prev=0;points.forEach(p=>{c.lineTo(x(p[0]),y(prev));c.lineTo(x(p[0]),y(p[1]));prev=p[1];});
  const last=points[points.length-1];c.lineTo(x(last[0]),y(0));c.closePath();c.fillStyle=run.id==="nsga2"?"#a9c46926":"#83a79716";c.fill();
  c.beginPath();c.moveTo(x(0),y(0));prev=0;points.forEach(p=>{c.lineTo(x(p[0]),y(prev));c.lineTo(x(p[0]),y(p[1]));prev=p[1];});c.strokeStyle=color;c.lineWidth=1.8;c.stroke();c.beginPath();c.arc(x(last[0]),y(last[1]),2.5,0,2*Math.PI);c.fillStyle=color;c.fill();
}
function renderTable(){
  const scout=state.mode==="scout";
  const headings=["Алгоритм",scout?"Найдено":"Спасено","Баллы ↓","Завершение, с","Все, с",scout?"Сред. обнаружение, с":"Сред. от обнаружения, с","Секунд / человек","Людей / мин","Энергия","Энергия / человек","CPU сред. / макс., мс","Оценок плана"];
  $("resultsTable").tHead.innerHTML="<tr>"+headings.map(h=>`<th scope="col">${h}</th>`).join("")+"</tr>";
  const sorted=[...state.runs].sort((a,b)=>b.metrics.score-a.metrics.score);
  $("resultsTable").tBodies[0].innerHTML=sorted.map(run=>{const m=run.metrics;return `<tr class="${run.id==="nsga2"?"highlight":""}"><td>${run.label}<small>${reasons[m.status]}</small></td><td>${scout?m.found:m.rescued} / ${state.config.people}${scout?"":`<small>истёк срок: ${m.expired}</small>`}</td><td class="score-cell">${fmt(m.score,3)}</td><td>${fmt(m.finished_at,0)}</td><td>${fmt(m.all_completed_at)}</td><td>${fmt(m.mean_response)}</td><td>${fmt(m.seconds_per_person)}</td><td>${fmt(m.people_per_minute,2)}</td><td>${fmt(m.energy)}<small>земля ${fmt(m.energy_ground,0)} · воздух ${fmt(m.energy_drone,0)}</small></td><td>${fmt(m.energy_per_person)}</td><td>${fmt(m.planning.mean_ms,2)} / ${fmt(m.planning.max_ms,2)}</td><td>${m.planning.evaluations}</td></tr>`;}).join("");
}
function renderVerdict(){
  if(state.time===0){$("verdict").textContent="Запустите эксперимент, чтобы сравнить результаты.";return;}
  const sorted=[...state.runs].sort((a,b)=>b.metrics.score-a.metrics.score),best=sorted[0];
  const equal=sorted.filter(r=>Math.abs(r.metrics.score-best.metrics.score)<1e-9);
  const lead=equal.length>1?`Равный результат: ${equal.map(r=>r.label).join(", ")}`:`${state.done?"Лучший результат":"Пока лидирует"}: ${best.label}`;
  const margin=equal.length===1?best.metrics.score-sorted[1].metrics.score:0;
  $("verdict").innerHTML=`<strong>${lead}</strong> · ${fmt(best.metrics.score,3)} балла. ${margin>0?`Отрыв ${fmt(margin,3)}.`:""} ${state.done?"Вывод относится к этой карте. Проверьте серию ниже.":"Рейтинг предварительный, миссия продолжается."}`;
}
function renderTrace(){
  const run=state.runs.find(r=>r.id==="nsga2"),trace=run.trace;
  if(!trace.length){$("traceDescription").textContent="Запустите несколько шагов, чтобы получить запись поиска.";return;}
  const slider=$("generationSlider");slider.max=trace.length-1;if(Number(slider.value)>Number(slider.max))slider.value=slider.max;
  const selected=trace[Number(slider.value)];$("generationValue").textContent=selected.generation;
  const scout=state.mode==="scout";
  $("traceDescription").textContent=`${modeName(state.mode)} · планирование в ${fmt(run.trace_time,0)} с · ${trace.length-1} поколений · ${selected.evaluations} уникальных оценок к выбранному поколению.`;
  const v=selected.best;
  $("traceNumbers").innerHTML=`<div class="trace-number"><strong>${fmt(-v[0],0)}</strong><span>${scout?"новых клеток в плане":"прогноз доставок до срока"}</span></div><div class="trace-number"><strong>${fmt(v[1])} с</strong><span>${scout?"время покрытия плана":"средняя задержка со штрафом"}</span></div><div class="trace-number"><strong>${fmt(v[2])}</strong><span>энергия плана</span></div>`;
  const {ctx:c,w,h}=canvasContext($("frontChart")),all=trace.flatMap(g=>g.front),xs=all.map(v=>-v[0]),ys=all.map(v=>v[1]);
  const xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys),left=43,bottom=34,top=15,right=15;
  const px=x=>left+(x-xmin)/Math.max(1,xmax-xmin)*(w-left-right),py=y=>top+(1-(y-ymin)/Math.max(1,ymax-ymin))*(h-top-bottom);
  c.font="10px Consolas,monospace";c.fillStyle="#7c8f7e";c.strokeStyle="#e0e8d9";
  for(let i=0;i<4;i++){const y=top+(h-top-bottom)*i/3;c.beginPath();c.moveTo(left,y);c.lineTo(w-right,y);c.stroke();c.fillText(fmt(ymax-(ymax-ymin)*i/3,0),2,y+3);}
  all.forEach(v=>{c.beginPath();c.arc(px(-v[0]),py(v[1]),2.5,0,2*Math.PI);c.fillStyle="#9eaf9b44";c.fill();});
  selected.front.forEach(v=>{c.beginPath();c.arc(px(-v[0]),py(v[1]),4,0,2*Math.PI);c.fillStyle="#4b8064";c.fill();});
  c.beginPath();c.arc(px(-v[0]),py(v[1]),6,0,2*Math.PI);c.strokeStyle=palette.orange;c.lineWidth=2;c.stroke();
  c.fillStyle="#768b76";c.textAlign="left";c.fillText(fmt(xmin,0),left,h-bottom+14);c.textAlign="right";c.fillText(fmt(xmax,0),w-right,h-bottom+14);c.textAlign="center";c.fillText(scout?"Прирост покрытия →":"Своевременные доставки →",w/2,h-3);c.textAlign="left";
}
const csvFields=["seed","algorithm","label","found","rescued","expired","score","finished_at","all_completed_at","last_completed_at","mean_response","seconds_per_person","people_per_minute","energy","energy_ground","energy_drone","energy_per_person","coverage","status","planning.calls","planning.evaluations","planning.mean_ms","planning.max_ms","planning.total_ms"];
function csv(rows){const cell=v=>`"${String(v??"").replaceAll('"','""')}"`;return "\ufeff"+[csvFields.join(";"),...rows.map(r=>csvFields.map(key=>cell(key.split(".").reduce((o,k)=>o?.[k],r))).join(";"))].join("\r\n");}
function download(name,content,mime){const url=URL.createObjectURL(new Blob([content],{type:mime})),a=document.createElement("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function currentRows(){return state.runs.map(r=>({seed:state.config.seed,algorithm:r.id,label:r.label,...r.metrics}));}
async function startBatch(){
  clearNotice();
  try {
    const count=Number($("batchCount").value);if(!Number.isInteger(count)||count<1||count>20)throw new Error("Число карт должно быть от 1 до 20.");
    // Use applied settings, never silently mix pending form edits with the live comparison.
    $("batchBtn").disabled=true;batchResult=null;$("batchResults").hidden=true;
    batchJob=await api("/api/batch",{mode:state.mode,config:state.config,count});
    $("cancelBatch").hidden=false;$("cancelBatch").disabled=false;pollBatch();
  }catch(error){$("batchBtn").disabled=false;notice(error);}
}
async function pollBatch(){
  try {
    const job=await api("/api/batch/"+batchJob.id);batchJob=job;
    $("batchStatus").textContent=`${job.completed} / ${job.requested} карт · ${job.status==="running"?"вычисляется…":job.status==="cancelled"?"остановлено":job.status==="error"?"ошибка":"готово"}`;
    if(job.status==="running"){batchTimer=setTimeout(pollBatch,400);return;}
    $("batchBtn").disabled=false;$("cancelBatch").hidden=true;
    if(job.error)throw new Error(job.error);
    batchResult=job.result;if(batchResult?.rows.length)renderBatch();
  }catch(error){$("batchBtn").disabled=false;$("cancelBatch").hidden=true;notice(error);}
}
function renderBatch(){
  const r=batchResult,field=r.mode==="scout"?"found":"rescued";
  $("batchResults").hidden=false;
  $("batchTitle").textContent=`${modeName(r.mode)} · ${r.completed} карт · seed ${r.config.seed}–${r.config.seed+r.completed-1}`;
  const heads=["Алгоритм",r.mode==="scout"?"Найдено, μ ± σ":"Спасено, μ ± σ","Баллы, μ ± σ","Победы¹","Завершение, с","Энергия, μ ± σ","CPU плана, мс"];
  $("batchTable").tHead.innerHTML="<tr>"+heads.map(h=>`<th>${h}</th>`).join("")+"</tr>";
  const stats=(v,d=1)=>`${fmt(v.mean,d)} ± ${fmt(v.sd,d)}`;
  $("batchTable").tBodies[0].innerHTML=r.summary.map(s=>`<tr class="${s.algorithm==="nsga2"?"highlight":""}"><td>${s.label}</td><td>${stats(s[field])}</td><td class="score-cell">${stats(s.score,3)}</td><td>${fmt(s.win_rate*100,0)}%</td><td>${stats(s.finished_at)}</td><td>${stats(s.energy)}</td><td>${stats(s.planning_ms,2)}</td></tr>`).join("");
  const pairs=r.paired_nsga2.map(p=>`${p.against}: Δ ${fmt(p.mean_score_difference,3)}${p.bootstrap_95?` [${fmt(p.bootstrap_95[0],3)}; ${fmt(p.bootstrap_95[1],3)}]`:" (для интервала нужно ≥3 карт)"}`).join(" · ");
  $("pairedNote").textContent=`μ ± σ — среднее и выборочное стандартное отклонение. ¹ При ничьей победа делится. Разница баллов NSGA-II с соперником и парный bootstrap 95%: ${pairs}. Малая серия не доказывает превосходство на других сценариях. Вычисление серии: ${fmt(r.elapsed_seconds,2)} с на этом ПК.`;
}
$("playBtn").addEventListener("click",()=>{clearNotice();if(running)stop();else{running=true;setControls();tick();}});
$("stepBtn").addEventListener("click",()=>{clearNotice();advance(1);});
$("resetBtn").addEventListener("click",()=>reset(state.mode,state.config));
form.addEventListener("submit",event=>{event.preventDefault();try{reset(state.mode,readConfig());}catch(error){notice(error);}});
document.querySelectorAll("[data-mode]").forEach(b=>b.addEventListener("click",()=>{if(state.mode!==b.dataset.mode)reset(b.dataset.mode,state.config);}));
$("showPaths").addEventListener("change",renderMaps);
$("showHidden").addEventListener("change",()=>{$("observerNote").hidden=!$("showHidden").checked;renderMaps();});
$("csvBtn").addEventListener("click",()=>download(`rescue-${state.mode}-seed${state.config.seed}.csv`,csv(currentRows()),"text/csv;charset=utf-8"));
$("jsonBtn").addEventListener("click",async()=>{try{const data=await api("/api/export");download(`rescue-${state.mode}-seed${state.config.seed}.json`,JSON.stringify(data,null,2),"application/json");}catch(error){notice(error);}});
$("traceBtn").addEventListener("click",()=>{traceOpen=!traceOpen;$("traceSection").hidden=!traceOpen;if(traceOpen){$("generationSlider").value=0;renderTrace();$("traceSection").scrollIntoView({behavior:"smooth",block:"center"});}});
$("closeTrace").addEventListener("click",()=>{traceOpen=false;$("traceSection").hidden=true;$("traceBtn").focus();});
$("generationSlider").addEventListener("input",renderTrace);
$("batchBtn").addEventListener("click",startBatch);
$("cancelBatch").addEventListener("click",async()=>{try{$("cancelBatch").disabled=true;await api("/api/batch/cancel",{id:batchJob.id});}catch(error){notice(error);}});
$("batchCsvBtn").addEventListener("click",()=>download(`series-${batchResult.mode}.csv`,csv(batchResult.rows),"text/csv;charset=utf-8"));
$("batchJsonBtn").addEventListener("click",()=>download(`series-${batchResult.mode}.json`,JSON.stringify(batchResult,null,2),"application/json"));
let resizeTimer;window.addEventListener("resize",()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(state){renderMaps();state.runs.forEach(r=>drawHistory(document.querySelector(`[data-algorithm="${r.id}"] .mini-chart`),r));if(traceOpen)renderTrace();}},100);});
window.addEventListener("beforeunload",()=>{stop();clearTimeout(batchTimer);});
api("/api/state").then(result=>{accept(result,true);fillForm(result.config);}).catch(error=>{notice(error);setControls();});
