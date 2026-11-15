'use strict';
const SVG='http://www.w3.org/2000/svg';
const $=id=>document.getElementById(id);
const MODE_META={
 scout:{name:'Разведка',title:'Алгоритмы разведки местности',subtitle:'Пять стратегий обследуют одну и ту же местность. Позиции людей неизвестны алгоритмам до обнаружения.',heading:'Сравнение маршрутов дронов',progress:'Обнаружено пострадавших по времени',pareto:'Энергия дронов, Wh и время полного покрытия, с',badge:'Найдено'},
 rescue:{name:'Эвакуация',title:'Алгоритмы эвакуации',subtitle:'Четыре стратегии (и опционально OR-Tools) распределяют известные цели между выбранным числом эвакуаторов.',heading:'Сравнение планов эвакуации',progress:'Спасено пострадавших по времени',pareto:'Энергия, Wh и взвешенное время спасения',badge:'Спасено'},
 mission:{name:'Три архитектуры',title:'NSGA-II ×2 · Global AI · Local AI',subtitle:'Три одинаковые спасательные миссии: базовый NSGA-II, + Global AI и + Global/Local AI. Сравнение при тех же катастрофах, ресурсах и правилах.',heading:'Сравнение трёх архитектур',progress:'Спасено пострадавших по времени',pareto:'Фронт Парето одной из используемых оптимизаций',badge:'Спасено'}
};
const COLORS=['#72b9f7','#ad89ff','#54d4a8'];
const SCOUT_COLORS=['#45baff','#ac92ff','#f9c66a'];
const ROBOT_COLORS=['#56e2bd','#ffbb65','#ff83b0','#a8a6ff'];
const TERRAIN=['#1a3044','#405067','#364d4f','#17435b'];
const HAZARD_COLORS={collapse:'#e5685b',fire:'#ff8d3e',flood:'#2998d4',mud:'#906d44',road_damage:'#dec067',smoke:'#b0b9c5'};
const EVENT_LABELS={collapse:'Обрушение',fire:'Пожар',flood:'Затопление',mud:'Грязь',road_damage:'Повреждение дороги',smoke:'Задымление',smoke_clear:'Дым рассеялся',appearance:'Новый сигнал'};
const EVENT_KEYS=['collapse','fire','flood','mud','road_damage','smoke','appearance'];
let state={mode:'mission',lastRunId:null,lastQuery:null,data:null,t:0,playing:false,speed:12,lastFrame:0,uiLast:0,cards:[],progressMarker:null,chartMax:480,loadToken:0,progressMarkers:[]};

function el(tag,attrs={},text=null){const e=document.createElement(tag);for(const [k,v] of Object.entries(attrs)){if(k==='className')e.className=v;else e.setAttribute(k,v);}if(text!==null)e.textContent=text;return e;}
function svgEl(tag,attrs={}){const e=document.createElementNS(SVG,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,String(v));return e;}
function svgText(x,y,content,more={}){const e=svgEl('text',{x,y,fill:'#9fb5ca','font-size':8,'text-anchor':'middle',...more});e.textContent=content;return e;}
const fixed=(v,d=1)=>Number(v||0).toFixed(d);
const fmtTime=t=>{let s=Math.floor(Math.max(0,t||0));return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0');};
const ENERGY_CACHE=new WeakMap();
function sumEnergy(segments,t){
 if(!segments?.length)return 0;
 if(segments.length<180){let e=0;for(const s of segments){if(t>=s.t1)e+=s.e;else if(t>s.t0&&s.t1>s.t0)e+=s.e*(t-s.t0)/(s.t1-s.t0);}return e;}
 let data=ENERGY_CACHE.get(segments);
 if(!data){const ordered=[...segments].sort((a,b)=>a.t1-b.t1);
  const cum=[0];for(const s of ordered)cum.push(cum.at(-1)+s.e);
  const byRobot=[];for(const s of segments)(byRobot[s.r]??=[]).push(s);
  byRobot.forEach(a=>a?.sort((x,y)=>x.t0-y.t0));
  data={ordered,cum,byRobot};ENERGY_CACHE.set(segments,data);
 }
 let lo=0,hi=data.ordered.length;while(lo<hi){const m=(lo+hi)>>1;if(data.ordered[m].t1<=t)lo=m+1;else hi=m;}
 let value=data.cum[lo];
 for(const arr of data.byRobot){if(!arr?.length)continue;
  let a=0,b=arr.length;while(a<b){const m=(a+b)>>1;if(arr[m].t0<=t)a=m+1;else b=m;}
  const s=arr[a-1];if(s&&s.t0<t&&t<s.t1)value+=s.e*(t-s.t0)/(s.t1-s.t0);
 }
 return value;
}
function upto(events,t){let n=0;for(const e of events){if(e.t<=t+1e-8)n++;else break;}return n;}
function modeSegments(run){return state.mode==='mission'?[...run.scout_segments,...run.rescue_segments]:run.segments;}
function calc(run,t){const sc=state.data.scenario;
 const count=(sc.initial_people??sc.n_people)+
 (sc.environment_events||[]).filter(e=>e.type==='appearance'&&e.t<=t).length;
 if(state.mode==='scout')return {primary:upto(run.discoveries,t),secondary:new Set(run.visits.filter(v=>v.t<=t).map(v=>v.sector)).size,energy:sumEnergy(run.segments,t),compute:run.opt.wall_ms||0,total:count};
 if(state.mode==='rescue')return {primary:upto(run.rescues,t),secondary:run.known_people.filter(p=>(p.t??0)<=t).length,energy:sumEnergy(run.segments,t),compute:run.opt.wall_ms||0,total:count};
 return {primary:upto(run.rescues,t),secondary:upto(run.discoveries,t),energy:sumEnergy(run.scout_segments,t)+sumEnergy(run.rescue_segments,t),compute:run.opt.wall_ms||0,total:count};
}
// Local transparent 0–100 index. It is NOT the Metaroy jury score.
// Success is dominant, timeliness is second, resource efficiency is third.
function scoreDetails(run,t){
 const sc=state.data.scenario, h=sc.horizon;
 const n=Math.max(1,(sc.initial_people??sc.n_people)+
  (sc.environment_events||[]).filter(e=>e.type==='appearance'&&e.t<=t).length);
 const events=(state.mode==='scout'?run.discoveries:run.rescues).filter(e=>e.t<=Math.min(t,h));
 const detected=(run.discoveries||[]).filter(e=>e.t<=Math.min(t,h));
 const progress=events.length/n;
 const early=events.reduce((s,e)=>s+Math.max(0,1-e.t/h),0)/n;
 const detection=detected.length/n;
 const energy=calc(run,t).energy;
 const energyBudget=Math.max(1, (state.data.runs?.[0]?.final?.energy||1)*1.35 * Math.max(.05,t/h));
 const energyEff=progress*Math.max(0,1-energy/Math.max(1,energyBudget));
 let score;
 if(state.mode==='scout')score=65*progress+25*early+10*energyEff;
 else if(state.mode==='rescue')score=70*progress+20*early+10*energyEff;
 else {
  const interrupted=(run.incidents||[]).filter(e=>e.t<=t).length;
  const stranded=(run.stranding||[]).filter(e=>e.t<=t).length;
  score=60*progress+15*detection+15*early+10*energyEff-Math.min(9,interrupted*.6+stranded*2);
 }
 return {score:Math.max(0,Math.min(100,score)),progress,early};
}
function rescueStats(run,t){
 const events=(run.rescues||[]).filter(e=>e.t<=t);
 if(!events.length)return {last:null,avg:null,rate:0};
 const last=Math.max(...events.map(e=>e.t));
 const avg=events.reduce((s,e)=>s+(e.t-(e.start||0)),0)/events.length;
 return {last,avg,rate:events.length*60/Math.max(1,last)};
}
function elapsedText(v){return Number.isFinite(v)?fixed(v,1):'—';}
function setMode(){
 state.mode='mission';
 const m=MODE_META[state.mode];
 document.querySelectorAll('.main-nav a').forEach(a=>a.classList.toggle('active',a.dataset.mode===state.mode));
 $('crumb-page').textContent=m.name;$('page-title').textContent=m.title;$('page-subtitle').textContent=m.subtitle;
 $('panels-heading').textContent=m.heading;$('progress-title').textContent=m.progress;
 $('pareto-description').textContent=m.pareto+'. На графике показаны решения настоящего NSGA-II (не искусственные данные).';
 $('stat-b-label').textContent='Лидер рейтинга';
 $('stat-d').textContent=$('people').value;
 $('stat-b-caption').textContent='Лидер по текущему баллу (0–100)';
 $('stat-c').textContent='—';
}
function toast(message){const t=$('toast');t.textContent=message;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),4300);}
async function load(){const ticket=++state.loadToken;state.playing=false;state.t=0;
 $('new-run').disabled=true;
 $('new-run').textContent='Выполняется расчёт…';
 $('play-btn').textContent='▶';$('overlay').classList.remove('hidden');
 const q=new URLSearchParams({mode:state.mode,seed:$('seed').value,people:$('people').value,scenario:$('scenario').value,
  map_size:$('map-size').value,scouts:$('scouts').value,rescuers:$('rescuers').value,
  ai_mode:$('ai-mode').value,ai_calls:$('ai-calls').value,
  local_timeout:$('local-timeout').value,global_timeout:$('global-timeout').value,run_id:String(Date.now())});
 EVENT_KEYS.forEach(key=>q.set('p_'+key,$('p-'+key).value));state.lastQuery=q.toString();
 try{
  const started=await fetch('/api/runs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(q)),cache:'no-store'});
  const initial=await started.json();if(!started.ok)throw new Error(initial.error||'Не удалось запустить расчёт');
  state.lastRunId=initial.run_id;
  let status='QUEUED';
  while(ticket===state.loadToken&&status!=='COMPLETED'){
   await new Promise(resolve=>setTimeout(resolve,700));
   const progress=await fetch('/api/runs/status?run_id='+encodeURIComponent(state.lastRunId),{cache:'no-store'});
   const job=await progress.json();if(!progress.ok)throw new Error(job.error||'Нет статуса');
   status=job.status;
   if(status==='FAILED'||status==='CANCELLED')throw new Error(job.error||status);
   $('new-run').textContent=status==='RUNNING'?'Расчёт трёх архитектур…':'Постановка в очередь…';
  }
  if(ticket!==state.loadToken)return;
  const res=await fetch('/api/runs/result?run_id='+encodeURIComponent(state.lastRunId),{cache:'no-store'});
  const data=await res.json();if(!res.ok)throw new Error(data.error||'Ошибка сервера');
  if(ticket!==state.loadToken)return;
  state.data=data;state.cards=[];
  const aiStats=data.runs.slice(1).map(r=>r.ai_stats);
  const live=$('ai-mode').value==='live';
  $('ai-connection').textContent=live?(data.ai_connected?'● Ключ есть · запросы отправлены':'○ Нет ключа · AI использует fallback'):
    $('ai-mode').value==='mock'?'● MOCK · DeepSeek не вызывается':'○ OFF · DeepSeek отключён';state.progressMarkers=[];$('stat-c').textContent=data.runs.length;
  $('notes').textContent=data.notes+' Режим: '+data.scenario.scenario_label+'.';
  $('stat-d').textContent=data.scenario.initial_people;
  $('time-slider').max=data.scenario.horizon;$('end-time-label').textContent=data.scenario.horizon+' с · ЗАВЕРШЕНИЕ';
  state.chartMax=data.scenario.horizon;
  createCards();buildProgressChart();buildParetoChart();update(0,true);state.playing=true;$('play-btn').textContent='❚❚';
 }catch(e){console.error(e);toast('Ошибка запуска: '+e.message);$('panels').textContent='Не удалось загрузить результаты: '+e.message;}
 finally{if(ticket===state.loadToken){$('overlay').classList.add('hidden');$('new-run').disabled=false;$('new-run').textContent='▶ СТАРТ · Запустить сравнение';}}
}
function tColor(run,index){return COLORS[index%COLORS.length];}
function initSVG(card,run,index){const d=state.data.scenario,n=d.width,s=n*10;
 const svg=svgEl('svg',{viewBox:`0 0 ${s} ${s}`,class:'map-svg','aria-label':'Карта участка для '+run.label});
 const terrain=svgEl('g');
 for(let y=0;y<n;y++)for(let x=0;x<n;x++){
   const tile=d.grid[y][x];terrain.append(svgEl('rect',{x:x*10,y:y*10,width:10.1,height:10.1,fill:TERRAIN[tile]}));
 }
 svg.append(terrain);
 // Independent dynamic hazard and smoke layers: playback can scrub both ways.
 const changeKeys=new Set();
 for(const event of d.environment_events||[])for(const cell of event.cells||[])changeKeys.add(cell.join(','));
 const changes=svgEl('g');const changeNodes=new Map();
 for(const key of changeKeys){const [x,y]=key.split(',').map(Number);
  const tile=svgEl('rect',{x:x*10,y:y*10,width:10.1,height:10.1,fill:'#000',opacity:0});
  const smoke=svgEl('rect',{x:x*10,y:y*10,width:10.1,height:10.1,fill:HAZARD_COLORS.smoke,opacity:0});
  changes.append(tile,smoke);changeNodes.set(key,{tile,smoke});
 }
 svg.append(changes);
 const prior=svgEl('g');
 const overlays=[];
 for(let sec=0;sec<d.prior.length;sec++){
  const x=sec%d.sector_count*d.sector_size*10,y=Math.floor(sec/d.sector_count)*d.sector_size*10;
  prior.append(svgEl('rect',{x,y,width:d.sector_size*10,height:d.sector_size*10,fill:'#e1a260',opacity:Math.min(.17,d.prior[sec]*.055)}));
  const overlay=svgEl('rect',{x,y,width:d.sector_size*10,height:d.sector_size*10,fill:'#32d4a1',opacity:0});
  overlays.push(overlay);prior.append(overlay);
  prior.append(svgEl('rect',{x,y,width:d.sector_size*10,height:d.sector_size*10,fill:'none',stroke:'#537089','stroke-width':.55,'stroke-dasharray':'2 2',opacity:.65}));
 }
 svg.append(prior);
 const path=svgEl('g');svg.append(path);
 const people=svgEl('g');svg.append(people);
 const base=svgEl('g');
 base.append(svgEl('circle',{cx:15,cy:15,r:7,fill:'#e8f5ff',stroke:'#245d90','stroke-width':2}));
 base.append(svgEl('path',{d:'M11 15H19 M15 11V19',stroke:'#237bbb','strokeWidth':1.5,'stroke-width':1.7}));
 svg.append(base);
 const actors=svgEl('g');svg.append(actors);
 const actorList=[];
 const robots=state.mode==='scout'?0:d.rescuers,scouts=state.mode==='rescue'?0:d.scouts;
 for(let kind of ['scout','robot']){
  const quantity=kind==='scout'?scouts:robots;
  for(let r=0;r<quantity;r++){
   const color=(kind==='scout'?SCOUT_COLORS:ROBOT_COLORS)[r%(kind==='scout'?SCOUT_COLORS.length:ROBOT_COLORS.length)];
   const group=svgEl('g',{transform:'translate(15,15)'});
   if(kind==='scout'){
    group.append(svgEl('polygon',{points:'0,-6 -5.5,5 0,2 5.5,5',fill:color,stroke:'#e3f4ff','stroke-width':.8}));
   }else{
    group.append(svgEl('rect',{x:-5,y:-5,width:10,height:10,rx:2,fill:color,stroke:'#ebf5ff','stroke-width':.8}));
   }
   const txt=svgText(0,1.4,String(r+1),{'font-size':6,fill:kind==='scout'?'#081625':'#101926','font-weight':800});
   group.append(txt);actors.append(group);
   actorList.push({kind,r,group});
  }
 }
 const lines=[];
 const parts=state.mode==='mission'?[{segments:run.scout_segments,kind:'scout'},{segments:run.rescue_segments,kind:'robot'}]:[{segments:run.segments,kind:state.mode==='scout'?'scout':'robot'}];
 for(const part of parts){
  for(let r=0;r<(part.kind==='scout'?d.scouts:d.rescuers);r++){
   const pieces=part.segments.filter(a=>a.r===r);
   const points=[];
   for(const seg of pieces){if(!points.length)points.push(seg.a);points.push(seg.b);}
   if(points.length){const poly=svgEl('polyline',{points:points.map(p=>`${p[0]*10+5},${p[1]*10+5}`).join(' '),fill:'none',stroke:(part.kind==='scout'?SCOUT_COLORS:ROBOT_COLORS)[r%(part.kind==='scout'?SCOUT_COLORS.length:ROBOT_COLORS.length)],'stroke-width':1.25,'stroke-opacity':part.kind==='scout'?.48:.35,'stroke-dasharray':part.kind==='scout'?'3 3':'1.5 3'});path.append(poly);lines.push(poly);}
  }
 }
 const targetList=state.mode==='rescue'?run.known_people:run.discoveries;
 const targetNodes=[];
 for(const target of targetList){
  const group=svgEl('g',{transform:`translate(${target.x*10+5},${target.y*10+5})`});
  group.append(svgEl('circle',{r:4.5,fill:'#ffad76',stroke:'#ffebd0','stroke-width':1.15}));
  group.append(svgText(0,1.7,'+',{'font-size':7,fill:'#53232a','font-weight':900}));
  group.setAttribute('visibility',state.mode==='rescue'?'visible':'hidden');
  people.append(group);targetNodes.push({target,group});
 }
 const signals=[];
 for(const event of d.environment_events||[]){if(event.type!=='appearance')continue;
  const cx=(event.sector%d.sector_count*d.sector_size+d.sector_size/2)*10;
  const cy=(Math.floor(event.sector/d.sector_count)*d.sector_size+d.sector_size/2)*10;
  const g=svgEl('g',{transform:`translate(${cx},${cy})`,visibility:'hidden'});
  g.append(svgEl('rect',{x:-7,y:-7,width:14,height:14,rx:2,fill:'#f7d15d',stroke:'#fff6c3','stroke-width':1.6,transform:'rotate(45)'}));
  g.append(svgText(0,3,'?',{'font-size':11,'font-weight':900,fill:'#2c2412'}));
  svg.append(g);signals.push({event,group:g});
 }
 const failureNodes=[];
 if(state.mode==='mission')for(const failure of (run.failures||[])){
  const g=svgEl('g',{transform:`translate(${failure.x*10+5},${failure.y*10+5})`,visibility:'hidden'});
  g.append(svgEl('circle',{r:7,fill:'#a92342',stroke:'#ffd6df','stroke-width':1.5}));
  g.append(svgText(0,2.4,'!',{'font-size':10,'font-weight':900,fill:'#ffffff'}));
  svg.append(g);failureNodes.push({data:failure,group:g});
 }
 card.map.append(svg);
 card.refs={svg,overlays,actorList,targetNodes,parts,failureNodes,changeNodes,signals};
 card.segmentLookup={scout:[],robot:[]};
 for(const part of parts){for(let r=0;r<(part.kind==='scout'?d.scouts:d.rescuers);r++){
  card.segmentLookup[part.kind][r]=part.segments.filter(seg=>seg.r===r);
 }}
}
// Large-map fast rendering: one Canvas per benchmark, instead of 70k+ SVG tiles.
// Static terrain/routes are cached; each playback tick redraws only overlays/actors.
function initCanvas(card,run,index){
 const d=state.data.scenario,n=d.width,px=6,size=n*px;
 const canvas=el('canvas',{className:'large-map-canvas','aria-label':`Карта ${run.label} ${n}×${n}`});
 canvas.width=size;canvas.height=size;card.map.append(canvas);
 const background=document.createElement('canvas');background.width=size;background.height=size;
 const bg=background.getContext('2d');
 for(let y=0;y<n;y++)for(let x=0;x<n;x++){
  bg.fillStyle=TERRAIN[d.grid[y][x]];bg.fillRect(x*px,y*px,px,px);
 }
 for(let i=0;i<d.prior.length;i++){
  const sx=i%d.sector_count,sy=Math.floor(i/d.sector_count);
  bg.fillStyle=`rgba(225,162,96,${Math.min(.17,d.prior[i]*.055)})`;
  bg.fillRect(sx*d.sector_size*px,sy*d.sector_size*px,d.sector_size*px,d.sector_size*px);
 }
 bg.strokeStyle='rgba(91,123,151,.28)';bg.lineWidth=.6;
 for(let x=0;x<=n;x+=d.sector_size){bg.beginPath();bg.moveTo(x*px,0);bg.lineTo(x*px,size);bg.stroke();}
 for(let y=0;y<=n;y+=d.sector_size){bg.beginPath();bg.moveTo(0,y*px);bg.lineTo(size,y*px);bg.stroke();}
 const segmentLookup={scout:Array.from({length:d.scouts},()=>[]),robot:Array.from({length:d.rescuers},()=>[])};
 for(const seg of run.scout_segments||[])segmentLookup.scout[seg.r]?.push(seg);
 for(const seg of run.rescue_segments||[])segmentLookup.robot[seg.r]?.push(seg);
 for(const kind of ['scout','robot']){
  segmentLookup[kind].forEach((arr,r)=>{
   if(arr.length===0)return;
   arr.sort((a,b)=>a.t0-b.t0);
   bg.lineWidth=kind==='scout'?1.2:1.1;
   bg.strokeStyle=kind==='scout'?'rgba(124,183,255,.30)':
     (run.method==='global_local_ai'?'rgba(83,223,169,.28)':
      run.method==='global_ai'?'rgba(171,130,255,.30)':'rgba(242,187,119,.27)');
   bg.beginPath();let last=null;
   for(const seg of arr){
    const a=seg.a,b=seg.b;
    if(!last||Math.abs(a[0]-last[0])+Math.abs(a[1]-last[1])>0.1)bg.moveTo((a[0]+.5)*px,(a[1]+.5)*px);
    bg.lineTo((b[0]+.5)*px,(b[1]+.5)*px);last=b;
   }
   bg.stroke();
  });
 }
 card.segmentLookup=segmentLookup;
 card.refs={canvas:true,ctx:canvas.getContext('2d'),background,px,n,
             targetList:run.discoveries||[],signals:(d.environment_events||[]).filter(e=>e.type==='appearance')};
}
function renderCanvas(card,t,terrain,smoke,scanned=new Set()){
 const refs=card.refs,ctx=refs.ctx,px=refs.px,n=refs.n,d=state.data.scenario,run=card.run;
 ctx.drawImage(refs.background,0,0);
 ctx.fillStyle='rgba(50,212,161,.18)';
 for(const i of scanned){const x=i%d.sector_count,y=Math.floor(i/d.sector_count);
  ctx.fillRect(x*d.sector_size*px,y*d.sector_size*px,d.sector_size*px,d.sector_size*px);
 }
 for(const [key,kind] of terrain){const [x,y]=key.split(',').map(Number);
  ctx.globalAlpha=.83;ctx.fillStyle=HAZARD_COLORS[kind]||'#888';ctx.fillRect(x*px,y*px,px,px);
 }
 ctx.fillStyle=HAZARD_COLORS.smoke;ctx.globalAlpha=.55;
 for(const key of smoke){const [x,y]=key.split(',').map(Number);ctx.fillRect(x*px,y*px,px,px);}
 ctx.globalAlpha=1;
 const found=new Set(),rescued=new Set();
 for(const e of run.discoveries||[]){if(e.t>t)break;found.add(e.id);}
 for(const e of run.rescues||[]){if(e.t>t)break;rescued.add(e.id);}
 for(const p of refs.targetList){if(p.t>t)break;
  const x=(p.x+.5)*px,y=(p.y+.5)*px;
  ctx.globalAlpha=rescued.has(p.id)?.25:1;ctx.fillStyle='#ffb66f';
  ctx.beginPath();ctx.arc(x,y,px*.58,0,Math.PI*2);ctx.fill();
 }
 ctx.globalAlpha=1;
 for(const ev of refs.signals){if(ev.t>t)break;if(found.has(ev.id))continue;
  const x=((ev.sector%d.sector_count)*d.sector_size+d.sector_size/2)*px;
  const y=(Math.floor(ev.sector/d.sector_count)*d.sector_size+d.sector_size/2)*px;
  ctx.fillStyle='#f6d164';ctx.fillRect(x-3,y-3,6,6);
 }
 ctx.fillStyle='#e7f6ff';ctx.beginPath();ctx.arc(1.5*px,1.5*px,px*.8,0,Math.PI*2);ctx.fill();
 for(const [kind,arr,colors] of [['scout',card.segmentLookup.scout,SCOUT_COLORS],
                                  ['robot',card.segmentLookup.robot,ROBOT_COLORS]]){
  for(let r=0;r<arr.length;r++){
   const {point}=findPose(arr[r],t);const x=(point[0]+.5)*px,y=(point[1]+.5)*px;
   ctx.fillStyle=colors[r%colors.length];ctx.strokeStyle='#eff9ff';ctx.lineWidth=.55;
   if(kind==='scout'){
    ctx.beginPath();ctx.moveTo(x,y-px*.78);ctx.lineTo(x+px*.75,y+px*.70);
    ctx.lineTo(x-px*.75,y+px*.70);ctx.closePath();ctx.fill();ctx.stroke();
   }else{ctx.fillRect(x-2.4,y-2.4,4.8,4.8);ctx.strokeRect(x-2.4,y-2.4,4.8,4.8);}
  }
 }
}

function createCards(){const root=$('panels');root.replaceChildren();
 state.data.runs.forEach((run,index)=>{
  const card=el('article',{className:'method-card'+(run.method.includes('nsga2')?' nsga-card':'')});
  const color=tColor(run,index);
  const head=el('div',{className:'method-top'});
  const mt=el('div',{className:'method-title'});mt.append(el('span',{className:'method-dot',style:`background:${color};color:${color}`}));
  const names=el('div');names.append(el('h3',{},run.label));
  names.append(el('div',{className:'method-subtitle'},run.method==='base'?'Два оптимизатора · без AI':
   run.method==='global_ai'?'DeepSeek: стратегическая координация':'DeepSeek: глобальный + личные агенты')); 
  mt.append(names);head.append(mt);
  const scoreTag=el('span',{className:'score-pill'},'0.0 / 100');head.append(scoreTag);
  card.append(head);
  const frame=el('div',{className:'svg-frame'});frame.append(el('div',{className:'map-corner'},`${state.data.scenario.width} × ${state.data.scenario.height} / 2D`));
  const clock=el('div',{className:'map-clock'},'00:00');frame.append(clock);card.append(frame);
  const incident=el('div',{className:'incident-line'},'Среда: без событий · прерываний: 0');card.append(incident);
  const grid=el('div',{className:'metric-grid'});
  const metricEls=[];
  const labels=state.mode==='scout'?['Найдено','Обследовано','Энергия Wh']:
               state.mode==='rescue'?['Спасено','Известно','Энергия Wh']:
               ['Спасено','Найдено','Энергия Wh'];
  labels.forEach((label,k)=>{const cell=el('div',{className:'metric-box'});
   cell.append(el('span',{},label));const v=el('strong',{className:k===0?'accent':''},'0');cell.append(v);metricEls.push(v);grid.append(cell);
  });
  card.append(grid);
  const foot=el('div',{className:'card-bottom'}),left=el('span',{},'Планирование: ');
  const right=el('span',{},'Фронт: ');
  left.append(el('strong',{},fixed(run.opt.wall_ms,1)+' мс'));
  right.append(el('strong',{},String(run.opt.pareto_size||0)));
  right.textContent='AI: '+(run.ai_stats?.calls||0)+' выз. · стратегий: '+
    (run.ai_stats?.strategic_commits||0)+' · '+(run.ai_stats?.last_strategy||'balanced');
  foot.append(left,right);card.append(foot);
  const bar=el('div',{className:'method-progress'}),fill=el('div',{className:'method-progress-fill'});
  fill.style.background=color;bar.append(fill);card.append(bar);
  root.append(card);
  const info={run,index,clock,map:frame,metrics:metricEls,bar:fill,scoreTag,incident,root:card,refs:null,segmentLookup:{}};
  if(state.data.scenario.width>65)initCanvas(info,run,index);else initSVG(info,run,index);state.cards.push(info);
 });
}
function findPose(segments,t){
 let lo=0,hi=segments.length;while(lo<hi){const mid=(lo+hi)>>1;if(segments[mid].t0<=t)lo=mid+1;else hi=mid;}
 const idx=lo-1;if(idx<0)return {point:[1,1],act:'idle'};const s=segments[idx];
 if(t>=s.t1)return {point:s.b,act:'idle'};
 const frac=s.t1>s.t0?(t-s.t0)/(s.t1-s.t0):1;
 return {point:[s.a[0]+(s.b[0]-s.a[0])*frac,s.a[1]+(s.b[1]-s.a[1])*frac],act:s.action};
}
function knownTerrainAt(card,t){
 const updates=card.run.knowledge_events||[];
 let k=card.knowledgeCache;
 if(!k||t<k.t-1e-6){k={t:-1,index:0,terrain:new Map(),smoke:new Set()};card.knowledgeCache=k;}
 while(k.index<updates.length&&updates[k.index].t<=t+1e-8){
  const obs=updates[k.index++];for(const c of obs.cells||[]){const key=c[0]+','+c[1];
   if(c[2])k.terrain.set(key,c[2]);else k.terrain.delete(key);
   if(c[3])k.smoke.add(key);else k.smoke.delete(key);
  }
 }
 k.t=t;
 return k;
}
function updateCard(card,t){const run=card.run,refs=card.refs,values=calc(run,t);
 card.clock.textContent=fmtTime(t);
 card.metrics[0].textContent=values.primary+' / '+values.total;
 card.metrics[1].textContent=values.secondary+(state.mode==='scout'?' / '+state.data.scenario.prior.length:state.mode==='mission'?' / '+values.total:'');
 card.metrics[2].textContent=fixed(values.energy,1);
 card.bar.style.width=(100*values.primary/Math.max(values.total,1))+'%';
 card.scoreTag.textContent=fixed(scoreDetails(run,t).score,1)+' / 100';
 const changes=state.data.scenario.environment_events||[];
 const activeTerrain=new Map(),activeSmoke=new Set();let changesSoFar=0,lastEvent=null;
 const showKnown=$('knowledge-mode')?.value!=='truth';
 for(const event of changes){if(event.t>t+1e-8)break;
  changesSoFar++;lastEvent=event;
  if(showKnown)continue;
  for(const cell of event.cells||[]){const key=cell.join(',');
   if(event.type==='smoke')activeSmoke.add(key);
   else if(event.type==='smoke_clear')activeSmoke.delete(key);
   else activeTerrain.set(key,event.type);
  }
 }
 if(showKnown){
  const observed=knownTerrainAt(card,t);
  for(const [key,kind] of observed.terrain)activeTerrain.set(key,kind);
  for(const key of observed.smoke)activeSmoke.add(key);
 }
 if(!refs.canvas)for(const [key,obj] of refs.changeNodes){const hazard=activeTerrain.get(key);
  obj.tile.setAttribute('opacity',hazard?'.86':'0');
  if(hazard)obj.tile.setAttribute('fill',HAZARD_COLORS[hazard]||'#888');
  obj.smoke.setAttribute('opacity',activeSmoke.has(key)?'.68':'0');
 }
 const incidents=(run.incidents||[]).filter(e=>e.t<=t);
 card.incident.textContent=`События среды: ${changesSoFar} · прерываний: ${incidents.length}`+
  (lastEvent?' · '+(EVENT_LABELS[lastEvent.type]||lastEvent.type):'');
 const seenPeople=new Set((run.discoveries||[]).filter(e=>e.t<=t).map(e=>e.id));
 if(!refs.canvas)for(const sig of (refs.signals||[])){sig.group.setAttribute('visibility',
    sig.event.t<=t&&!seenPeople.has(sig.event.id)&&state.mode!=='rescue'?'visible':'hidden');}
 const visits=state.mode==='rescue'?[]:run.visits;
 const scanned=new Set(visits.filter(e=>e.t<=t).map(e=>e.sector));
 if(!refs.canvas)refs.overlays.forEach((e,i)=>e.setAttribute('opacity',scanned.has(i)?'.23':'0'));
 if(refs.canvas)renderCanvas(card,t,activeTerrain,activeSmoke,scanned);
 const rescued=new Set((run.rescues||[]).filter(e=>e.t<=t).map(e=>e.id));
 for(const tar of (refs.targetNodes||[])){
   tar.group.setAttribute('visibility',tar.target.t===undefined ? (state.mode==='rescue'?'visible':'hidden') : tar.target.t<=t?'visible':'hidden');
   tar.group.setAttribute('opacity',rescued.has(tar.target.id)?'.35':'1');
 }
 for(const failure of (refs.failureNodes||[])){
   failure.group.setAttribute('visibility',failure.data.t<=t?'visible':'hidden');
 }
 for(const obj of (refs.actorList||[])){
   const items=card.segmentLookup[obj.kind][obj.r]||[];
   const pose=findPose(items,t);
   obj.group.setAttribute('transform',`translate(${pose.point[0]*10+5},${pose.point[1]*10+5})`);
   obj.group.setAttribute('opacity',pose.act==='scan'?'.75':'1');
 }
}
function update(t,force=false){if(!state.data)return;const horizon=state.data.scenario.horizon;
 state.t=Math.max(0,Math.min(horizon,t));
 $('time-slider').value=state.t;$('time-label').innerHTML=fmtTime(state.t)+' <em>/ '+fmtTime(horizon)+'</em>';
 $('stat-a').textContent=fixed(state.t,0)+' с';
 $('stat-d').textContent=calc(state.data.runs[0],state.t).total;
 let lead=null,bestScore=-1;
 state.cards.forEach(card=>{
  updateCard(card,state.t);
  const score=scoreDetails(card.run,state.t).score;
  card.root.classList.remove('leader-card');
  if(score>bestScore+1e-8){lead=card;bestScore=score;}
 });
 if(lead&&bestScore>0)lead.root.classList.add('leader-card');
 $('stat-b').textContent=lead&&bestScore>0?lead.run.label+' · '+fixed(bestScore,1):'—';
 if(state.progressMarkers){for(const marker of state.progressMarkers){
  const x=marker.axisX(Math.min(state.chartMax,state.t));marker.line.setAttribute('x1',x);marker.line.setAttribute('x2',x);
  marker.count.textContent=upto(marker.run[marker.field]||[],state.t)+' / '+calc(marker.run,state.t).total;
 }}
 if(force||performance.now()-state.uiLast>250){fillResultsTable();renderAuditPanel();state.uiLast=performance.now();}
 if(state.t>=horizon&&state.playing){state.playing=false;$('play-btn').textContent='▶';}
}
function fillResultsTable(){
 const mode=state.mode, isScout=mode==='scout';
 const labels=isScout?
  ['Место','Алгоритм','Баллы / 100','Найдено','Секторов','Темп, чел/мин','Энергия, Wh','Окончание работы, с','План, мс']:
  ['Место','Алгоритм','Баллы / 100','Спасено','Найдено','Темп, чел/мин','Рейс, с/чел','Энергия, Wh','Прерывания','Последняя доставка, с','Окончание работы, с','План, мс'];
 const items=state.cards.map(c=>{
  const run=c.run,met=calc(run,state.t),sc=scoreDetails(run,state.t),rescue=rescueStats(run,state.t);
  const count=isScout?met.primary:rescue.last===null?0:met.primary;
  const lastFound=(run.discoveries||[]).filter(e=>e.t<=state.t);
  const rate=isScout?(lastFound.length*60/Math.max(1,lastFound.at(-1)?.t||0)):rescue.rate;
  return {c,run,met,sc,rescue,rate,count};
 }).sort((a,b)=>b.sc.score-a.sc.score||b.met.primary-a.met.primary||a.met.energy-b.met.energy||a.c.index-b.c.index);
 const table=$('results-table');table.replaceChildren();
 const thead=el('thead'),r=el('tr');labels.forEach(l=>r.append(el('th',{},l)));thead.append(r);table.append(thead);
 const body=el('tbody');
 items.forEach((o,i)=>{
  const {c,run,met,sc,rescue,rate}=o;
  const tr=el('tr',{className:i===0&&sc.score>0?'leader-row':''});
  tr.append(el('td',{className:'rank-text'},'#'+(i+1)));
  const td=el('td');const cell=el('div',{className:'method-cell'});
  const dot=el('span',{className:'tiny-dot'});dot.style.background=tColor(run,c.index);
  cell.append(dot,el('span',{},run.label));td.append(cell);tr.append(td);
  const scoreTd=el('td');scoreTd.append(el('span',{className:'score-pill'},fixed(sc.score,1)));tr.append(scoreTd);
  let values;
  if(isScout){
   values=[met.primary+' / '+met.total,met.secondary+' / '+state.data.scenario.prior.length,
    fixed(rate,2),fixed(met.energy,1),elapsedText(run.final.finished_at),fixed(met.compute,1)];
  }else{
   values=[met.primary+' / '+met.total,met.secondary+' / '+met.total,fixed(rate,2),
     rescue.avg===null?'—':fixed(rescue.avg,1),fixed(met.energy,1),
     String((run.incidents||[]).filter(e=>e.t<=state.t).length),rescue.last===null?'—':fixed(rescue.last,1),elapsedText(run.final.finished_at),fixed(met.compute,1)];
  }
  values.forEach(v=>tr.append(el('td',{},String(v))));body.append(tr);
 });table.append(body);
 $('table-status').textContent='Текущий момент: '+fmtTime(state.t)+' · окончание работы — итоговое время';
 $('score-method').textContent=mode==='scout'?
  'Формула баллов: 65% — доля найденных; 25% — насколько рано обнаружены; 10% — экономия энергии с учётом результата. 100 баллов — теоретический максимум.':
  mode==='rescue'?
  'Формула баллов: 70% — доля спасённых; 20% — насколько рано доставлены; 10% — экономия энергии с учётом результата. Сортировка — по баллам.':
  'Формула баллов: 60% — доля спасённых; 15% — доля обнаруженных; 15% — ранняя эвакуация; 10% — энергия. Из результата вычитается до 9 баллов за опасные прерывания и потерю доступности робота.';
}
// Separate aligned sparkline per method: zero overlapping curves.
function buildProgressChart(){
 const holder=$('progress-chart');holder.replaceChildren();state.progressMarkers=[];
 const h=state.data.scenario.horizon,n=state.data.scenario.n_people;
 const field=state.mode==='scout'?'discoveries':'rescues';
 const W=690,LEFT=42,RIGHT=14,TOP=7,BOTTOM=21;
 const X=v=>LEFT+(W-LEFT-RIGHT)*Math.max(0,Math.min(1,v/h));
 const Y=v=>TOP+(95-TOP-BOTTOM)*(1-v/Math.max(1,n));
 state.data.runs.forEach((run,i)=>{
  const lane=el('div',{className:'progress-lane'});
  const head=el('div',{className:'progress-lane-header'});
  const name=el('div',{className:'progress-lane-name'});
  const dot=el('span',{className:'tiny-dot'});dot.style.background=tColor(run,i);
  name.append(dot,el('span',{},run.label));
  const value=el('span',{className:'progress-lane-value'},'0 / '+n);
  head.append(name,value);lane.append(head);
  const svg=svgEl('svg',{viewBox:'0 0 690 97',preserveAspectRatio:'xMidYMid meet','aria-label':run.label+' — '+field+' по времени'});
  [0,.5,1].forEach(frac=>{
   const yy=Y(n*frac);
   svg.append(svgEl('line',{x1:LEFT,y1:yy,x2:W-RIGHT,y2:yy,stroke:'#2a4359','stroke-width':.7}));
   svg.append(svgText(LEFT-15,yy+3,String(Math.round(n*frac)),{'font-size':9}));
  });
  [0,.25,.5,.75,1].forEach(frac=>{
   const xx=X(h*frac);
   svg.append(svgEl('line',{x1:xx,y1:TOP,x2:xx,y2:Y(0),stroke:'#21364b','stroke-width':.7}));
   svg.append(svgText(xx,94,String(Math.round(h*frac)),{'font-size':9}));
  });
  let plotted=0;let curve=`M ${X(0)} ${Y(0)}`;
  for(const e of run[field]||[]){if(e.t>h)break;curve+=` L ${X(e.t)} ${Y(plotted)} L ${X(e.t)} ${Y(++plotted)}`;}
  curve+=` L ${X(h)} ${Y(plotted)}`;
  svg.append(svgEl('path',{d:curve,fill:'none',stroke:tColor(run,i),'stroke-width':2.7,'stroke-linejoin':'round'}));
  const mark=svgEl('line',{x1:X(state.t),y1:TOP,x2:X(state.t),y2:Y(0),stroke:'#dceefc','stroke-width':1.2,'stroke-dasharray':'3 4',opacity:.9});
  svg.append(mark);state.progressMarkers.push({line:mark,axisX:X,count:value,run,field});
  lane.append(svg);holder.append(lane);
 });
 holder.append(el('p',{className:'progress-axis-footer'},'Ось X — модельное время (с). Ось Y — количество людей. Все мини-графики используют одни и те же пределы.'));
}
function buildParetoChart(){const holder=$('pareto-chart');holder.replaceChildren();
 const run=state.data.runs.find(r=>r.method==='base')||state.data.runs[0];
 const points=run?.opt?.pareto||[];
 if(!points.length){holder.append(el('p',{style:'padding:45px 12px;text-align:center;color:#7189a6'},
  state.mode==='mission'?'Онлайн-оптимизация запускается при каждом событии. Отдельные финальные фронты не объединяются: они относятся к разным задачам.':'Недостаточно точек фронта.'));return;}
 const width=440,height=230,L=55,R=18,T=15,B=38;
 const xs=points.map(p=>p[2]),ys=points.map(p=>p[1]);
 let loX=Math.min(...xs),hiX=Math.max(...xs),loY=Math.min(...ys),hiY=Math.max(...ys);
 if(hiX-loX<.01){loX-=1;hiX+=1;}else{const a=(hiX-loX)*.12;loX-=a;hiX+=a;}
 if(hiY-loY<.01){loY-=1;hiY+=1;}else{const a=(hiY-loY)*.12;loY-=a;hiY+=a;}
 const X=v=>L+(v-loX)/(hiX-loX)*(width-L-R);
 const Y=v=>height-B-(v-loY)/(hiY-loY)*(height-T-B);
 const svg=svgEl('svg',{viewBox:`0 0 ${width} ${height}`,'aria-label':'Фронт Парето NSGA-II'});
 for(let k=0;k<=4;k++){
  let x=L+k/4*(width-L-R),y=T+k/4*(height-T-B);
  svg.append(svgEl('line',{x1:L,y1:y,x2:width-R,y2:y,stroke:'#2e4560','stroke-width':.8}));
  svg.append(svgEl('line',{x1:x,y1:T,x2:x,y2:height-B,stroke:'#223b54','stroke-width':.8}));
  svg.append(svgText(x,height-B+16,fixed(loX+(hiX-loX)*k/4,0),{'font-size':9}));
  svg.append(svgText(L-26,y+3,fixed(hiY-(hiY-loY)*k/4,0),{'font-size':9}));
 }
 const unique=new Set();
 for(const p of points){let key=p.map(v=>Number(v).toFixed(3)).join('|');if(unique.has(key))continue;unique.add(key);
  svg.append(svgEl('circle',{cx:X(p[2]),cy:Y(p[1]),r:4.5,fill:'#54d4f9',stroke:'#d3efff','stroke-width':1,opacity:.86}));
 }
 svg.append(svgText(width/2,height-1,'Энергия, Wh',{'font-size':11}));
 holder.append(svg);
 const text=el('div',{style:'font-size:11px;color:#88a3be;margin:2px 5px'},`Уникальных точек: ${unique.size} · популяция: ${run.opt.population||'—'} · поколений: ${run.opt.generations||'—'} · оценок: ${run.opt.evaluations||'—'}`);
 holder.append(text);
}

function renderAuditPanel(){
 const root=$('audit-feed');if(!root||!state.data)return;
 const variant=$('audit-variant').value;
 const run=state.data.runs.find(r=>r.method===variant);if(!run)return;
 let logs=run.audit||[];
 if(variant==='base')logs=[
  ...(run.discoveries||[]).map(e=>({t:e.t,source:'sensor',type:'TARGET_DETECTED',data:e})),
  ...(run.decisions||[]).map(e=>({t:e.t,source:'nsga2',type:'PLAN_EVALUATED',data:e})),
  ...(run.incidents||[]).map(e=>({t:e.t,source:'safety',type:'ROUTE_INTERRUPTED',data:e})),
  ...(run.rescues||[]).map(e=>({t:e.t,source:'executor',type:'TARGET_RESCUED',data:e}))
 ].sort((a,b)=>a.t-b.t);
 const items=logs.filter(e=>e.t<=state.t+1e-8).slice(-25).reverse();root.replaceChildren();
 if(!items.length){root.append(el('p',{className:'audit-empty'},'На текущей секунде ещё нет событий. Передвиньте ползунок времени.'));return;}
 for(const e of items){
  const line=el('details',{className:'audit-entry'});
  const summary=el('summary');summary.append(el('span',{className:'audit-time'},fmtTime(e.t)),
   el('strong',{},e.source||'system'),el('span',{className:'audit-type'},e.type||'EVENT'));
  const body=el('pre',{},JSON.stringify(e,null,2));line.append(summary,body);root.append(line);
 }
}
function bind(){setMode();
 $('audit-variant').addEventListener('change',renderAuditPanel);
 $('scenario-form').addEventListener('submit',e=>{e.preventDefault();const p=new URL(window.location.href);p.searchParams.set('seed',$('seed').value);p.searchParams.set('people',$('people').value);p.searchParams.set('scenario',$('scenario').value);p.searchParams.set('map_size',$('map-size').value);p.searchParams.set('scouts',$('scouts').value);p.searchParams.set('rescuers',$('rescuers').value);EVENT_KEYS.forEach(k=>p.searchParams.set('p_'+k,$('p-'+k).value));history.replaceState({},'',p);load();});
 $('play-btn').addEventListener('click',()=>{if(!state.data)return;if(state.t>=state.data.scenario.horizon)update(0,true);state.playing=!state.playing;$('play-btn').textContent=state.playing?'❚❚':'▶';});
 $('step-btn').addEventListener('click',()=>{state.playing=false;$('play-btn').textContent='▶';update(state.t+5,true);});
 $('reset-btn').addEventListener('click',()=>{state.playing=false;$('play-btn').textContent='▶';update(0,true);});
 $('time-slider').addEventListener('input',e=>{state.playing=false;$('play-btn').textContent='▶';update(+e.target.value,true);});
 $('speed').addEventListener('change',e=>{state.speed=+e.target.value;});
 $('knowledge-mode').addEventListener('change',()=>{if(state.data)update(state.t,true);});
 $('export-logs-btn').addEventListener('click',()=>{if(!state.data||!state.lastQuery){toast('Сначала запустите сравнение');return;}
  toast('Загрузка полного TXT-журнала без новых расчётов и AI-вызовов');
  window.location.href='/api/logs?run_id='+encodeURIComponent(state.lastRunId);});
 $('export-btn').addEventListener('click',()=>{if(!state.data)return;const b=new Blob([JSON.stringify(state.data,null,2)],{type:'application/json;charset=utf-8'});
  const a=el('a');a.href=URL.createObjectURL(b);a.download=`metarescue_${state.mode}_${state.data.scenario.scenario_type}_${state.data.scenario.width}x${state.data.scenario.height}_seed${state.data.scenario.seed}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);toast('Результаты сохранены в JSON');});
 const q=new URLSearchParams(window.location.search);
 if(q.has('seed'))$('seed').value=q.get('seed');if(q.has('people'))$('people').value=q.get('people');if(q.has('scenario'))$('scenario').value=q.get('scenario');
 if(q.has('ai_mode'))$('ai-mode').value=q.get('ai_mode');
 if(q.has('ai_calls'))$('ai-calls').value=q.get('ai_calls');
 if(q.has('local_timeout'))$('local-timeout').value=q.get('local_timeout');
 if(q.has('global_timeout'))$('global-timeout').value=q.get('global_timeout');
 if(q.has('map_size'))$('map-size').value=q.get('map_size');if(q.has('scouts'))$('scouts').value=q.get('scouts');if(q.has('rescuers'))$('rescuers').value=q.get('rescuers');
 EVENT_KEYS.forEach(k=>{
  const input=$('p-'+k),out=$('p-'+k+'-out');
  if(q.has('p_'+k))input.value=q.get('p_'+k);
  out.textContent=input.value+'%';
  input.addEventListener('input',()=>{out.textContent=input.value+'%';});
 });
 $('events-zero').addEventListener('click',()=>EVENT_KEYS.forEach(k=>{
  $('p-'+k).value='0';$('p-'+k+'-out').textContent='0%';
 }));
 state.speed=+$('speed').value;
 // Waiting for explicit START: no world generation, NSGA-II, or DeepSeek call.
 $('panels').textContent='Настройте параметры слева и нажмите «СТАРТ». До этого расчёты не выполняются.';
 fetch('/api/health',{cache:'no-store'}).then(r=>r.json()).then(info=>{
  $('ai-connection').textContent=info.ai_connected?'● Ключ DeepSeek найден · ожидание СТАРТ':'○ Ключ DeepSeek отсутствует · LIVE будет недоступен';
 }).catch(()=>{$('ai-connection').textContent='Статус API недоступен';});
 requestAnimationFrame(tick);
}
function tick(now){if(state.playing&&state.data&&state.lastFrame){const dt=Math.min(.25,(now-state.lastFrame)/1000);update(state.t+dt*state.speed);}
 state.lastFrame=now;requestAnimationFrame(tick);
}
window.addEventListener('DOMContentLoaded',bind);
