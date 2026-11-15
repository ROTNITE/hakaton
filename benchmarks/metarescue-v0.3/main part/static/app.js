'use strict';
const $=id=>document.getElementById(id);
const COLORS=['#56beff','#3ddaa7','#ecbd78','#ad8cf0','#f381a2'];
const TYPES=['collapse','fire','flood','mud','road_damage','smoke','low_visibility','new_target'];
const TERRAIN=['#263b4b','#586579','#6f6256','#22546b','#94744f','#a9805c','#dd5a4b','#2881a0','#af4e56'];
const EVENT_COLORS={collapse:'#d96867',fire:'#fb9655',flood:'#53bce7',mud:'#bca16a',road_damage:'#d5ad74',smoke:'#bcc7cf',low_visibility:'#86b1b3',new_target:'#55efbc',agent_failure:'#f9738a'};
const UI={mode:location.pathname==='/scout'?'scout':location.pathname==='/rescue'?'rescue':'mission',
 data:null,t:0,horizon:480,playing:false,lastAnim:0,cards:[],chartMarkers:[],winner:null,loadToken:0};
function node(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=String(text);return e;}
function svg(tag,props={}){const x=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(props))x.setAttribute(k,v);return x;}
function fixed(n,d=1){return Number.isFinite(n)?n.toFixed(d):'—';}
function fmt(t){t=Math.max(0,Math.floor(t));return String(Math.floor(t/60)).padStart(2,'0')+':'+String(t%60).padStart(2,'0');}
function color(run,index){return COLORS[index%COLORS.length];}
function eventsAt(arr,t){return arr.filter(e=>e.t<=t+1e-8);}
function targetsNow(t){const d=UI.data.scenario;return d.initial_people+d.events.filter(e=>e.t<=t && e.type==='new_target').length;}
function energyAt(run,t){let used=0;for(const s of run.segments){if(s.t0>t)continue;used+=s.e*Math.max(0,Math.min(1,(t-s.t0)/Math.max(.001,s.t1-s.t0)));}return used;}
function metrics(run,t){
 const discoveries=eventsAt(run.discoveries,t),rescues=eventsAt(run.rescues,t);
 const events=eventsAt(UI.data.scenario.events,t),total=targetsNow(t),
  primary=UI.mode==='scout'?discoveries.length:rescues.length;
 const last=rescues.length?rescues[rescues.length-1].t:null;
 const rate=last==null?0:rescues.length*60/Math.max(1,last);
 const trip=rescues.length?rescues.reduce((a,r)=>a+(r.t-r.start),0)/rescues.length:null;
 const replans=eventsAt(run.replans,t).length;
 const found=discoveries.length;
 const energy=energyAt(run,t);
 const ratio=primary/Math.max(1,total), early=(UI.mode==='scout'?discoveries:rescues)
    .reduce((a,r)=>a+(1-r.t/UI.horizon),0)/Math.max(1,total);
 const budget=UI.mode==='scout'?UI.data.scenario.scouts*UI.data.scenario.scout_battery_Wh:
     UI.mode==='rescue'?UI.data.scenario.rescuers*UI.data.scenario.ground_battery_Wh:
     UI.data.scenario.scouts*UI.data.scenario.scout_battery_Wh+UI.data.scenario.rescuers*UI.data.scenario.ground_battery_Wh;
 const economy=ratio*Math.max(0,1-energy/Math.max(1,budget*.90));
 
 let score=0;
 if(UI.mode==='scout')score=65*ratio+25*early+10*economy;
 else if(UI.mode==='rescue')score=70*ratio+20*early+10*economy;
 else score=60*ratio+15*(found/Math.max(1,total))+15*early+10*economy;
 return {found,rescued:rescues.length,primary,total,energy,rate,trip,last,
         replans,events:events.length,score:Math.max(0,Math.min(100,score)),
         covered:eventsAt(run.visits,t).reduce((a,v)=>(a.add(v.sector),a),new Set()).size};
}
function canvasMap(card){
 const d=UI.data.scenario,sz=d.width,el=card.canvas;
 el.width=sz*11;el.height=sz*11;
 const paint=el.getContext('2d');paint.setTransform(11,0,0,11,0,0);paint.imageSmoothingEnabled=false;
 const base=document.createElement('canvas');base.width=sz*11;base.height=sz*11;
 const ctx=base.getContext('2d');ctx.setTransform(11,0,0,11,0,0);
 for(let y=0;y<sz;y++)for(let x=0;x<sz;x++){
   ctx.fillStyle=TERRAIN[d.grid[y][x]];ctx.fillRect(x,y,1,1);
   ctx.strokeStyle='#0b1a2b55';ctx.lineWidth=.035;ctx.strokeRect(x,y,1,1);
 }
 card.baseCanvas=base;
 card.actorSegments={};
 for(const s of card.run.segments){const key=s.kind+':'+s.r;if(!card.actorSegments[key])card.actorSegments[key]=[];card.actorSegments[key].push(s);}
}
function trailPoint(path,f){
 if(!path.length)return [1,1];if(path.length===1)return path[0];
 const d=path.slice(1).map((p,i)=>Math.hypot(p[0]-path[i][0],p[1]-path[i][1]));
 let len=d.reduce((a,b)=>a+b,0)*Math.max(0,Math.min(1,f));
 for(let i=0;i<d.length;i++){
   if(len<=d[i]||i===d.length-1){const w=d[i]===0?0:len/d[i];return [path[i][0]*(1-w)+path[i+1][0]*w,path[i][1]*(1-w)+path[i+1][1]*w];}
   len-=d[i];
 }
 return path.at(-1);
}
function moveTrack(ctx,segments,t,stroke){
 ctx.beginPath();let drew=false;
 for(const s of segments){
   if(s.t0>t || s.t1<t-115 || !['scout_move','return_scout','to_person','to_base'].includes(s.action))continue;
   const path=s.path;if(path.length<2)continue;
   const frac=Math.min(1,(t-s.t0)/Math.max(.001,s.t1-s.t0));
   const end=trailPoint(path,frac);
   ctx.moveTo(path[0][0]+.5,path[0][1]+.5);
   for(let i=1;i<path.length;i++){
     // Approximation of traversed polyline for view only.
        if(i/(path.length-1)>frac)break;
     ctx.lineTo(path[i][0]+.5,path[i][1]+.5);
   }
   ctx.lineTo(end[0]+.5,end[1]+.5);drew=true;
 }
 if(drew){ctx.strokeStyle=stroke;ctx.lineWidth=.17;ctx.globalAlpha=.65;ctx.stroke();ctx.globalAlpha=1;}
}
function currentPos(segs,t){let loc=[1,1];for(const s of segs){if(s.t0>t)break;
 const progress=Math.max(0,Math.min(1,(t-s.t0)/Math.max(.001,s.t1-s.t0)));
 loc=trailPoint(s.path,progress);if(s.t1>=t)break;
 }return loc;
}
function paintMap(card,t){
 const ctx=card.canvas.getContext('2d'),d=UI.data.scenario,run=card.run,sz=d.width;
 ctx.clearRect(0,0,sz,sz);ctx.drawImage(card.baseCanvas,0,0,sz,sz);
 const nowEvents=eventsAt(d.events,t);
 const effects=new Map();const weather=[];
 for(const ev of nowEvents){
   if(['collapse','fire','flood','mud','road_damage'].includes(ev.type)){
     for(const [x,y] of ev.cells){if(d.grid[y][x]===1||d.grid[y][x]===3)continue;
       const key=y*sz+x;
       if((ev.type==='mud'||ev.type==='road_damage') && ['collapse','fire','flood'].includes(effects.get(key)))continue;
       effects.set(key,ev.type);
     }
   }else if(['smoke','low_visibility'].includes(ev.type)){
     if(t<ev.t+(ev.type==='smoke'?90:100))weather.push(ev);
   }
 }
 for(const [id,type] of effects){const x=id%sz,y=Math.floor(id/sz);
   ctx.fillStyle={collapse:'#c95050',fire:'#ed713b',flood:'#297b9b',mud:'#917551',road_damage:'#ac8553'}[type];ctx.fillRect(x,y,1,1);
 }
 for(const ev of weather){ctx.fillStyle=ev.type==='smoke'?'#c1c7ce90':'#8aaeb06b';
   for(const [x,y] of ev.cells)ctx.fillRect(x,y,1,1);
 }
 // Individual coverage is not falsely shared between algorithms.
 const covered=new Set(eventsAt(run.visits,t).map(v=>v.sector));
 ctx.lineWidth=.09;ctx.strokeStyle='#47c6ae75';
 for(const sec of covered){const x=(sec%d.sector_count)*5,y=Math.floor(sec/d.sector_count)*5;
   ctx.strokeRect(x+.10,y+.10,4.8,4.8);
 }
 // Environmental signal gives only a coarse sector, not the exact person coordinates.
 const discovered=new Set(eventsAt(run.discoveries,t).map(v=>v.id));
 for(const ev of nowEvents){if(ev.type!=='new_target'||discovered.has(ev.person_id)||UI.mode==='rescue')continue;
   const x=(ev.sector%d.sector_count)*5+2.5,y=Math.floor(ev.sector/d.sector_count)*5+2.5;
   ctx.strokeStyle='#35efb6';ctx.lineWidth=.26;ctx.beginPath();ctx.arc(x,y,1.7,0,Math.PI*2);ctx.stroke();
   ctx.fillStyle='#b5ffde';ctx.font='bold 2.4px Arial';ctx.textAlign='center';ctx.fillText('?',x,y+.82);
 }
 for(const p of eventsAt(run.discoveries,t)){
   if(eventsAt(run.rescues,t).some(r=>r.id===p.id))continue;
   ctx.beginPath();ctx.fillStyle='#46f7ad';ctx.strokeStyle='#113d30';ctx.lineWidth=.18;
   ctx.arc(p.x+.5,p.y+.5,.53,0,Math.PI*2);ctx.fill();ctx.stroke();
 }
 for(const kind of ['scout','rescue']){
   const n=kind==='scout'?d.scouts:d.rescuers;if(kind==='scout'&&UI.mode==='rescue')continue;
   if(kind==='rescue'&&UI.mode==='scout')continue;
   const tint=kind==='scout'?'#52c7fa':'#ffb95f';
   for(let r=0;r<n;r++){
     const events=card.actorSegments[kind+':'+r]||[];
     moveTrack(ctx,events,t,kind==='scout'?'#4ba5ca':'#db9861');
     const p=currentPos(events,t);ctx.fillStyle=tint;
     ctx.strokeStyle='#102237';ctx.lineWidth=.2;
     ctx.beginPath();ctx.arc(p[0]+.5,p[1]+.5,.63,0,Math.PI*2);ctx.fill();ctx.stroke();
     if(sz<=35){ctx.fillStyle='#092033';ctx.font='bold 1.05px Arial';ctx.textAlign='center';ctx.fillText(kind==='scout'?'D':'R',p[0]+.5,p[1]+.86);}
   }
 }
 // Rescue checkpoint is always fixed and safe.
 ctx.fillStyle='#e1f0fa';ctx.strokeStyle='#2b88b0';ctx.lineWidth=.18;
 ctx.fillRect(.25,.25,2,2);ctx.strokeRect(.25,.25,2,2);
 ctx.textAlign='center';ctx.fillStyle='#105275';ctx.font='bold 1.1px Arial';ctx.fillText('HQ',1.25,1.66);
 card.timeText.textContent=fmt(t);
}
function createCards(){
 const panels=$('panels');panels.replaceChildren();UI.cards=[];
 UI.data.runs.forEach((run,i)=>{
   const card=node('article','method-card');
   const head=node('div','method-header');const name=node('div','method-name');
   const dot=node('span','dot');dot.style.background=color(run,i);
   name.append(dot,node('span','',run.label));
   const score=node('span','score','0.0 / 100');head.append(name,score);
   const map=node('div','map');const canvas=node('canvas');canvas.className='map-canvas';
   const flag=node('span','map-flag',UI.data.scenario.width+' × '+UI.data.scenario.height+' · 2D');
   const tm=node('span','map-clock','00:00');map.append(canvas,flag,tm);
   const info=node('div','method-metrics');const labels=UI.mode==='scout'?['Найдено','Охват','Энергия, Wh','Перепланы']:
             ['Спасено','Найдено','Энергия, Wh','Перепланы'];
   const fields=labels.map(l=>{const col=node('div'),title=node('span','',l),val=node('strong','','0');col.append(title,val);info.append(col);return val;});
   const bar=node('div','mini-progress');const fill=node('div');bar.append(fill);
   card.append(head,map,info,bar);panels.append(card);
   const entry={run,i,card,canvas,timeText:tm,scoreText:score,fields,fill};
   canvasMap(entry);UI.cards.push(entry);
 });
}
function applyCard(card,t,m){
 card.scoreText.textContent=fixed(m.score,1)+' / 100';
 const vals=UI.mode==='scout'?[m.found+' / '+m.total,m.covered+' / '+(UI.data.scenario.sector_count**2),fixed(m.energy),m.replans]:
    [m.rescued+' / '+m.total,m.found+' / '+m.total,fixed(m.energy),m.replans];
 vals.forEach((v,i)=>card.fields[i].textContent=String(v));
 card.fill.style.width=fixed(m.primary/Math.max(1,m.total)*100,2)+'%';
 paintMap(card,t);
}
function update(t,heavy=true){
 if(!UI.data)return;UI.t=Math.max(0,Math.min(UI.horizon,t));
 $('time-slider').value=String(UI.t);$('clock').textContent=fmt(UI.t);
 $('stat-time').textContent=fixed(UI.t,1)+' с';
 $('stat-events').textContent=eventsAt(UI.data.scenario.events,UI.t).length+' / '+UI.data.scenario.events.length;
 $('stat-targets').textContent=String(targetsNow(UI.t));
 const all=UI.cards.map(c=>({c,m:metrics(c.run,UI.t)}));
 const leader=all.slice().sort((a,b)=>b.m.score-a.m.score||b.m.primary-a.m.primary||a.m.energy-b.m.energy)[0];
 $('stat-leader').textContent=leader&&leader.m.score>0?leader.c.run.label+' · '+fixed(leader.m.score):'—';
 for(const {c,m} of all){c.card.classList.toggle('leader',leader===all.find(e=>e.c===c)&&m.score>0);applyCard(c,UI.t,m);}
 for(const marker of UI.chartMarkers){const x=marker.x(UI.t);marker.line.setAttribute('x1',x);marker.line.setAttribute('x2',x);
   marker.value.textContent=eventsAt(marker.run[marker.field],UI.t).length+' / '+targetsNow(UI.t);}
 if(heavy||Math.floor(UI.t)%4===0){fillTable(all);updateEvents();updateDecisions();}
}
function scoreFormula(){
 const message=UI.mode==='scout'?
  'Баллы = 65% доля найденных + 25% раннее обнаружение + 10% экономия энергии с учётом результата.':
  UI.mode==='rescue'?
  'Баллы = 70% доля спасённых + 20% ранние доставки + 10% экономия энергии.':
  'Баллы = 60% доля спасённых + 15% доля найденных + 15% ранние доставки + 10% экономия энергии.';
 $('score-method').textContent=message+' Оценка вычисляется по одному правилу для всех методов, нормируется от 0 до 100. Это исследовательский индекс, не официальная оценка хакатона.';
}
function fillTable(all){
 const m=UI.mode,table=$('results-table');table.replaceChildren();
 const headers=m==='scout'?['Место','Алгоритм','Баллы','Найдено','Секторы','Энергия, Wh','Время окончания, с','План, мс']:
 ['Место','Алгоритм','Баллы','Спасено','Найдено','Темп, чел/мин','Рейс, с/чел','Энергия, Wh','Последняя доставка, с','Окончание работы, с','Перепланы','Заблокировано','План, мс'];
 const thead=node('thead');const tr=node('tr');for(const h of headers)tr.append(node('th','',h));thead.append(tr);table.append(thead);
 const body=node('tbody');all=all.slice().sort((a,b)=>b.m.score-a.m.score||b.m.primary-a.m.primary||a.m.energy-b.m.energy);
 all.forEach(({c,m},i)=>{
   const row=node('tr',i===0&&m.score>0?'winner':'');
   const values=UI.mode==='scout'?[i+1,c.run.label,fixed(m.score),m.found+'/'+m.total,m.covered+'/'+UI.data.scenario.sector_count**2,
     fixed(m.energy),fixed(c.run.final.finished_at),fixed(c.run.final.compute_ms)]:
     [i+1,c.run.label,fixed(m.score),m.rescued+'/'+m.total,m.found+'/'+m.total,
       fixed(m.rate,2),m.trip==null?'—':fixed(m.trip),fixed(m.energy),m.last==null?'—':fixed(m.last),
       fixed(c.run.final.finished_at),m.replans,eventsAt(c.run.decisions,UI.t).filter(e=>e.type==='route_blocked').length,fixed(c.run.final.compute_ms)];
   values.forEach((v,k)=>row.append(node('td',k===0?'rank':'',v)));body.append(row);
 });table.append(body);$('table-time').textContent='Текущее время: '+fmt(UI.t)+' · окончание — итог';
}
function buildProgress(){
 const holder=$('progress-chart');holder.replaceChildren();UI.chartMarkers=[];
 const max=UI.data.scenario.n_people,H=UI.horizon,L=29,R=10,T=8,B=19,W=550,D=68;
 const X=x=>L+(W-L-R)*Math.min(1,Math.max(0,x/H));
 const Y=y=>T+(D-T-B)*(1-y/Math.max(1,max));
 const field=UI.mode==='scout'?'discoveries':'rescues';
 UI.data.runs.forEach((run,index)=>{
   const lane=node('div','progress-lane');const head=node('div','lane-top');
   head.append(node('strong','',run.label));const value=node('small','','0 / '+UI.data.scenario.initial_people);
   head.append(value);lane.append(head);
   const g=svg('svg',{viewBox:'0 0 550 68',preserveAspectRatio:'none',role:'img','aria-label':run.label+' по времени'});
   for(const f of [0,.5,1]){
     const y=Y(max*f);g.append(svg('line',{x1:L,y1:y,x2:W-R,y2:y,stroke:'#345068','stroke-width':.6}));
     const txt=svg('text',{x:L-5,y:y+3,fill:'#819eb5','font-size':9,'text-anchor':'end'});txt.textContent=Math.round(max*f);g.append(txt);
   }
   for(const f of [0,.5,1]){
     const x=X(H*f);g.append(svg('line',{x1:x,y1:T,x2:x,y2:Y(0),stroke:'#28465b','stroke-width':.7}));
     const tx=svg('text',{x,y:64,fill:'#839fb4','font-size':9,'text-anchor':'middle'});tx.textContent=Math.round(H*f);g.append(tx);
   }
   let count=0,d=`M${X(0)},${Y(0)}`;
   for(const e of run[field]){
     d+=`L${X(e.t)},${Y(count)}`;count++;d+=`L${X(e.t)},${Y(count)}`;
   }d+=`L${X(H)},${Y(count)}`;
   g.append(svg('path',{d,fill:'none',stroke:color(run,index),'stroke-width':2.6}));
   const mark=svg('line',{x1:X(UI.t),x2:X(UI.t),y1:T,y2:Y(0),stroke:'#d1f0ff','stroke-width':1.3,'stroke-dasharray':'3 3'});
   g.append(mark);lane.append(g);holder.append(lane);UI.chartMarkers.push({line:mark,x:X,value,run,field});
 });
}
function buildEventList(){
 const list=$('event-list');list.replaceChildren();
 const arr=UI.data.scenario.events;
 if(!arr.length){list.append(node('p','empty','Событий нет: установлены нулевые вероятности.'));return;}
 for(const e of arr){
   const item=node('div','event-item');item.dataset.time=e.t;
   const time=node('span','event-time',fmt(e.t));const mark=node('i','event-mark');mark.style.background=EVENT_COLORS[e.type]||'#a1b4c7';
   const txt=node('span');txt.append(node('b','',e.label));
   const info=e.type==='new_target'?' · сигнал, сектор '+(e.sector+1):e.type==='agent_failure'?' · эвакуатор '+(e.robot+1):
    ' · '+e.cells.length+' клеток · сектор '+(e.sector+1);
   txt.append(document.createTextNode(info));item.append(time,mark,txt);list.append(item);
 }
}
function updateEvents(){
 const items=Array.from($('event-list').children);
 items.forEach(el=>{if(el.dataset.time)el.classList.toggle('future',Number(el.dataset.time)>UI.t);});
}
function decisionLabel(d){
 switch(d.type){
  case 'route_replanned':return 'Перестроен маршрут R'+(d.robot+1)+' ('+d.reason+')';
  case 'route_blocked':return 'Нет безопасного пути для R'+(d.robot+1);
  case 'target_detected':return 'Обнаружен человек №'+d.person;
  case 'target_rescued':return 'Доставлен человек №'+d.person+' роботом R'+(d.robot+1);
  case 'coarse_signal':return 'Получен сигнал: сектор '+(d.sector+1);
  case 'environment_event':return 'Событие: '+d.event_type;
  case 'agent_failed':return 'Отказ эвакуатора R'+(d.robot+1);
  case 'rescue_assigned':return 'R'+(d.robot+1)+' назначен человеку №'+d.person;
  default:return d.type;
 }
}
function updateDecisions(){
 const holder=$('decision-log'),selected=$('log-method').value;
 const run=UI.data.runs.find(r=>r.method===selected)||UI.data.runs[0];
 const logs=run.decisions.filter(e=>e.t<=UI.t && !['scout_assigned'].includes(e.type)).slice(-16).reverse();
 holder.replaceChildren();
 if(!logs.length){holder.append(node('p','empty','До этого момента решений нет.'));return;}
 for(const d of logs){const row=node('div','event-item');row.append(node('span','event-time',fmt(d.t)),
   node('span','',decisionLabel(d)));holder.append(row);}
}
function buildPareto(){
 const el=$('pareto-chart');el.replaceChildren();const runs=UI.data.runs.filter(r=>r.pareto?.length);
 if(!runs.length){el.append(node('p','empty','В этом режиме NSGA-II не выполнялся.'));return;}
 const last=runs.at(-1),data=last.pareto;const maxT=Math.max(1,...data.map(v=>v.time)),maxE=Math.max(1,...data.map(v=>v.energy));
 const chart=svg('svg',{viewBox:'0 0 550 240',role:'img','aria-label':'Приближённый фронт Парето'});
 for(let f=0;f<=4;f++){
  const x=44+(490*f/4),y=204-(170*f/4);
  chart.append(svg('line',{x1:x,y1:30,x2:x,y2:204,stroke:'#2a455a','stroke-width':.8}));
  chart.append(svg('line',{x1:44,y1:y,x2:534,y2:y,stroke:'#2a455a','stroke-width':.8}));
  const tx=svg('text',{x,y:220,fill:'#96afc2','font-size':10,'text-anchor':'middle'});tx.textContent=Math.round(maxT*f/4);chart.append(tx);
  const ty=svg('text',{x:38,y:y+4,fill:'#96afc2','font-size':10,'text-anchor':'end'});ty.textContent=Math.round(maxE*f/4);chart.append(ty);
 }
 for(const p of data){const x=44+490*p.time/maxT,y=204-170*p.energy/maxE;
  chart.append(svg('circle',{cx:x,cy:y,r:4.6,fill:'#57baf6',stroke:'#b5e6ff','stroke-width':.9}));}
 el.append(chart,node('p','hint','Локальный фронт: '+last.label+' · '+data.length+' недоминируемых кандидатов. X — прогноз времени, Y — прогноз энергии.'));
}
function stop(){UI.playing=false;$('play-btn').textContent='▶ Запустить';}
function frame(now){
 if(UI.playing && UI.data){
   const delta=Math.min(.15,(now-UI.lastAnim)/1000);
   const v=UI.t+Math.max(0,delta)*Number($('speed').value);
   if(v>=UI.horizon){stop();update(UI.horizon,true);}else update(v,false);
 }
 UI.lastAnim=now;requestAnimationFrame(frame);
}
async function load(){
 const token=++UI.loadToken;stop();$('new-run').disabled=true;$('status').classList.remove('error');$('status').textContent='Рассчитываются одинаковые испытания…';
 $('panels').replaceChildren(node('p','spinner','Запуск пяти независимых симуляций…'));
 const q=new URLSearchParams(new FormData($('settings')));q.set('mode',UI.mode);
 try{
  const response=await fetch('/api/simulation?'+q.toString());
  const data=await response.json();
  if(token!==UI.loadToken)return;
  if(!response.ok)throw new Error(data.error||'Ошибка сервера');
  UI.data=data;UI.horizon=data.scenario.horizon;UI.t=0;
  $('time-slider').max=String(UI.horizon);$('time-slider').value='0';$('end-clock').textContent=fmt(UI.horizon);
  $('stat-horizon').textContent='Лимит: '+UI.horizon+' с';
  $('scene-details').textContent=`${data.scenario.width} × ${data.scenario.height} · ${data.scenario.scouts} дрона / ${data.scenario.rescuers} эвакуаторов`;
  $('method-title').textContent=UI.mode==='mission'?'Пять стратегий общей миссии':UI.mode==='scout'?'Пять стратегий разведки':'Четыре стратегии эвакуации';
  $('chart-title').textContent=UI.mode==='scout'?'Обнаруженные по времени':'Спасённые по времени';
  $('subtitle').textContent=UI.mode==='mission'?'Параллельная разведка и эвакуация при одинаковых динамических возмущениях.':
    UI.mode==='scout'?'Как разные стратегии дронов обследуют изменяющийся ландшафт.':
    'Пострадавшие известны с начала теста; новые сигналы сразу добавляют задачи эвакуации.';
  createCards();buildProgress();buildEventList();scoreFormula();
  const sel=$('log-method');sel.replaceChildren();for(const r of data.runs){const opt=node('option','',r.label);opt.value=r.method;sel.append(opt);}sel.value=data.runs[0].method;
  buildPareto();update(0,true);
  $('status').textContent=`Готово: ${data.runs.length} алгоритмов; ${data.scenario.events.length} событий; ${data.scenario.n_people} целей за эпизод.`;
  const u=new URL(window.location.href);u.searchParams.set('mode',UI.mode);for(const [key,val] of q)if(key!=='mode')u.searchParams.set(key,val);
  if(location.protocol!=='about:')history.replaceState(null,'',u.pathname+u.search);
 }catch(err){if(token!==UI.loadToken)return;$('panels').replaceChildren(node('p','empty','Не удалось построить симуляцию.'));
  $('status').textContent='Ошибка: '+err.message;$('status').classList.add('error');console.error(err);
 }finally{if(token===UI.loadToken)$('new-run').disabled=false;}
}
function init(){
 document.querySelectorAll('.mode-nav a').forEach(a=>a.classList.toggle('active',a.dataset.page===UI.mode));
 const q=new URLSearchParams(location.search);
 for(const [key,value] of q){const el=$(key);if(el && el.name===key && (el.type!=='range'||Number.isFinite(Number(value))))el.value=value;}
 for(const input of document.querySelectorAll('#prob-controls input')){
  const out=document.querySelector(`output[for="${input.id}"]`);
  const update=()=>out.textContent=input.value+'%';input.addEventListener('input',update);update();
 }
 $('settings').addEventListener('submit',ev=>{ev.preventDefault();if($('settings').reportValidity())load();});
 $('play-btn').addEventListener('click',()=>{
  if(!UI.data)return;
  if(UI.playing)stop();else{if(UI.t>=UI.horizon)update(0,true);UI.playing=true;UI.lastAnim=performance.now();$('play-btn').textContent='❚❚ Пауза';}
 });
 $('step-btn').addEventListener('click',()=>{if(!UI.data)return;stop();update(UI.t+10,true);});
 $('time-slider').addEventListener('input',()=>{stop();update(Number($('time-slider').value),true);});
 $('log-method').addEventListener('change',updateDecisions);
 requestAnimationFrame(frame);load();
}
window.addEventListener('DOMContentLoaded',init);
