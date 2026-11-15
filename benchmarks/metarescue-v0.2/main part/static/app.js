'use strict';
const SVG='http://www.w3.org/2000/svg';
const $=id=>document.getElementById(id);
const MODE_META={
 scout:{name:'Разведка',title:'Алгоритмы разведки местности',subtitle:'Пять стратегий обследуют одну и ту же местность. Позиции людей неизвестны алгоритмам до обнаружения.',heading:'Сравнение маршрутов дронов',progress:'Обнаружено пострадавших по времени',pareto:'Энергия дронов, Wh и время полного покрытия, с',badge:'Найдено'},
 rescue:{name:'Эвакуация',title:'Алгоритмы эвакуации',subtitle:'Четыре стратегии (и опционально OR-Tools) распределяют известные цели между выбранным числом эвакуаторов.',heading:'Сравнение планов эвакуации',progress:'Спасено пострадавших по времени',pareto:'Энергия, Wh и взвешенное время спасения',badge:'Спасено'},
 mission:{name:'Общая миссия',title:'Поиск + эвакуация одновременно',subtitle:'Новые цели обнаруживаются дронами, а эвакуаторы начинают спасение до окончания разведки. Сравнение комбинаций алгоритмов.',heading:'Сравнение полных миссий',progress:'Спасено пострадавших по времени',pareto:'Фронт Парето одной из используемых оптимизаций',badge:'Спасено'}
};
const COLORS=['#8d9dad','#daa26f','#54d4a8','#a796fd','#40baff','#f17f9e','#f6ca4c'];
const SCOUT_COLORS=['#45baff','#ac92ff','#f9c66a'];
const ROBOT_COLORS=['#56e2bd','#ffbb65','#ff83b0','#a8a6ff'];
const TERRAIN=['#1a3044','#405067','#364d4f','#17435b'];
let state={mode:'scout',data:null,t:0,playing:false,speed:12,lastFrame:0,uiLast:0,cards:[],progressMarker:null,chartMax:480,loadToken:0,progressMarkers:[]};

function el(tag,attrs={},text=null){const e=document.createElement(tag);for(const [k,v] of Object.entries(attrs)){if(k==='className')e.className=v;else e.setAttribute(k,v);}if(text!==null)e.textContent=text;return e;}
function svgEl(tag,attrs={}){const e=document.createElementNS(SVG,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,String(v));return e;}
function svgText(x,y,content,more={}){const e=svgEl('text',{x,y,fill:'#9fb5ca','font-size':8,'text-anchor':'middle',...more});e.textContent=content;return e;}
const fixed=(v,d=1)=>Number(v||0).toFixed(d);
const fmtTime=t=>{let s=Math.floor(Math.max(0,t||0));return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0');};
function sumEnergy(segments,t){let e=0;for(const s of segments){if(t>=s.t1)e+=s.e;else if(t>s.t0 && s.t1>s.t0)e+=s.e*(t-s.t0)/(s.t1-s.t0);}return e;}
function upto(events,t){let n=0;for(const e of events){if(e.t<=t+1e-8)n++;else break;}return n;}
function modeSegments(run){return state.mode==='mission'?[...run.scout_segments,...run.rescue_segments]:run.segments;}
function calc(run,t){const count=state.data.scenario.n_people;
 if(state.mode==='scout')return {primary:upto(run.discoveries,t),secondary:upto(run.visits,t),energy:sumEnergy(run.segments,t),compute:run.opt.wall_ms||0,total:count};
 if(state.mode==='rescue')return {primary:upto(run.rescues,t),secondary:run.known_people.length,energy:sumEnergy(run.segments,t),compute:run.opt.wall_ms||0,total:count};
 return {primary:upto(run.rescues,t),secondary:upto(run.discoveries,t),energy:sumEnergy(run.scout_segments,t)+sumEnergy(run.rescue_segments,t),compute:run.opt.wall_ms||0,total:count};
}
// Local transparent 0–100 index. It is NOT the Metaroy jury score.
// Success is dominant, timeliness is second, resource efficiency is third.
function scoreDetails(run,t){
 const sc=state.data.scenario, h=sc.horizon,n=Math.max(1,sc.n_people);
 const events=(state.mode==='scout'?run.discoveries:run.rescues).filter(e=>e.t<=Math.min(t,h));
 const detected=(run.discoveries||[]).filter(e=>e.t<=Math.min(t,h));
 const progress=events.length/n;
 const early=events.reduce((s,e)=>s+Math.max(0,1-e.t/h),0)/n;
 const detection=detected.length/n;
 const energy=calc(run,t).energy;
 const energyBudget=(state.mode==='scout'?sc.scouts*sc.scout_battery_Wh:
  state.mode==='rescue'?sc.rescuers*sc.ground_battery_Wh:
  sc.scouts*sc.scout_battery_Wh+sc.rescuers*sc.ground_battery_Wh)*.9;
 const energyEff=progress*Math.max(0,1-energy/Math.max(1,energyBudget));
 let score;
 if(state.mode==='scout')score=65*progress+25*early+10*energyEff;
 else if(state.mode==='rescue')score=70*progress+20*early+10*energyEff;
 else score=60*progress+15*detection+15*early+10*energyEff;
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
function setMode(){const p=window.location.pathname, qMode=new URLSearchParams(window.location.search).get('mode');
 state.mode=p==='/rescue'||qMode==='rescue'?'rescue':p==='/mission'||qMode==='mission'?'mission':'scout';
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
 $('play-btn').textContent='▶';$('overlay').classList.remove('hidden');
 const q=new URLSearchParams({mode:state.mode,seed:$('seed').value,people:$('people').value,scenario:$('scenario').value,
  map_size:$('map-size').value,scouts:$('scouts').value,rescuers:$('rescuers').value});
 try{const res=await fetch('/api/simulation?'+q.toString(),{cache:'no-store'});
  const data=await res.json();if(!res.ok)throw new Error(data.error||'Ошибка сервера');
  if(ticket!==state.loadToken)return;
  state.data=data;state.cards=[];state.progressMarkers=[];$('stat-c').textContent=data.runs.length;
  $('notes').textContent=data.notes+' Режим: '+data.scenario.scenario_label+'.';$('stat-d').textContent=data.scenario.n_people;
  $('time-slider').max=data.scenario.horizon;$('end-time-label').textContent=data.scenario.horizon+' с · ЗАВЕРШЕНИЕ';
  state.chartMax=data.scenario.horizon;
  createCards();buildProgressChart();buildParetoChart();update(0,true);state.playing=true;$('play-btn').textContent='❚❚';
 }catch(e){console.error(e);toast('Ошибка запуска: '+e.message);$('panels').textContent='Не удалось загрузить результаты: '+e.message;}
 finally{if(ticket===state.loadToken)$('overlay').classList.add('hidden');}
}
function tColor(run,index){if(run.method==='nsga2'||run.method==='nsga2_nsga2')return '#40baff';return COLORS[index%COLORS.length];}
function initSVG(card,run,index){const d=state.data.scenario,n=d.width,s=n*10;
 const svg=svgEl('svg',{viewBox:`0 0 ${s} ${s}`,class:'map-svg','aria-label':'Карта участка для '+run.label});
 const terrain=svgEl('g');
 for(let y=0;y<n;y++)for(let x=0;x<n;x++){
   const tile=d.grid[y][x];terrain.append(svgEl('rect',{x:x*10,y:y*10,width:10.1,height:10.1,fill:TERRAIN[tile]}));
 }
 svg.append(terrain);
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
 const failureNodes=[];
 if(state.mode==='mission')for(const failure of (run.failures||[])){
  const g=svgEl('g',{transform:`translate(${failure.x*10+5},${failure.y*10+5})`,visibility:'hidden'});
  g.append(svgEl('circle',{r:7,fill:'#a92342',stroke:'#ffd6df','stroke-width':1.5}));
  g.append(svgText(0,2.4,'!',{'font-size':10,'font-weight':900,fill:'#ffffff'}));
  svg.append(g);failureNodes.push({data:failure,group:g});
 }
 card.map.append(svg);
 card.refs={svg,overlays,actorList,targetNodes,parts,failureNodes};
 card.segmentLookup={scout:[],robot:[]};
 for(const part of parts){for(let r=0;r<(part.kind==='scout'?d.scouts:d.rescuers);r++){
  card.segmentLookup[part.kind][r]=part.segments.filter(seg=>seg.r===r);
 }}
}
function createCards(){const root=$('panels');root.replaceChildren();
 state.data.runs.forEach((run,index)=>{
  const card=el('article',{className:'method-card'+(run.method.includes('nsga2')?' nsga-card':'')});
  const color=tColor(run,index);
  const head=el('div',{className:'method-top'});
  const mt=el('div',{className:'method-title'});mt.append(el('span',{className:'method-dot',style:`background:${color};color:${color}`}));
  const names=el('div');names.append(el('h3',{},run.label));
  names.append(el('div',{className:'method-subtitle'},run.method.includes('nsga2')?'Недоминируемая сортировка · Pareto':'Базовая стратегия сравнения'));
  mt.append(names);head.append(mt);
  const scoreTag=el('span',{className:'score-pill'},'0.0 / 100');head.append(scoreTag);
  card.append(head);
  const frame=el('div',{className:'svg-frame'});frame.append(el('div',{className:'map-corner'},`${state.data.scenario.width} × ${state.data.scenario.height} / 2D`));
  const clock=el('div',{className:'map-clock'},'00:00');frame.append(clock);card.append(frame);
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
  if(!run.method.includes('nsga2'))right.textContent='Контрольный метод';
  foot.append(left,right);card.append(foot);
  const bar=el('div',{className:'method-progress'}),fill=el('div',{className:'method-progress-fill'});
  fill.style.background=color;bar.append(fill);card.append(bar);
  root.append(card);
  const info={run,index,clock,map:frame,metrics:metricEls,bar:fill,scoreTag,root:card,refs:null,segmentLookup:{}};
  initSVG(info,run,index);state.cards.push(info);
 });
}
function findPose(segments,t){let point=[1,1],act='idle';
 for(const s of segments){
  if(s.t0>t)break;
  if(t>=s.t1){point=s.b;continue;}
  if(t>=s.t0){const frac=s.t1>s.t0?(t-s.t0)/(s.t1-s.t0):1;
   point=[s.a[0]+(s.b[0]-s.a[0])*frac,s.a[1]+(s.b[1]-s.a[1])*frac];act=s.action;break;
  }
 }
 return {point,act};
}
function updateCard(card,t){const run=card.run,refs=card.refs,values=calc(run,t);
 card.clock.textContent=fmtTime(t);
 card.metrics[0].textContent=values.primary+' / '+values.total;
 card.metrics[1].textContent=values.secondary+(state.mode==='scout'?' / '+state.data.scenario.prior.length:state.mode==='mission'?' / '+values.total:'');
 card.metrics[2].textContent=fixed(values.energy,1);
 card.bar.style.width=(100*values.primary/Math.max(values.total,1))+'%';
 card.scoreTag.textContent=fixed(scoreDetails(run,t).score,1)+' / 100';
 const visits=state.mode==='rescue'?[]:run.visits;
 const scanned=new Set(visits.filter(e=>e.t<=t).map(e=>e.sector));
 refs.overlays.forEach((e,i)=>e.setAttribute('opacity',scanned.has(i)?'.23':'0'));
 const rescued=new Set((run.rescues||[]).filter(e=>e.t<=t).map(e=>e.id));
 for(const tar of refs.targetNodes){
   tar.group.setAttribute('visibility',(state.mode==='rescue'||tar.target.t<=t)?'visible':'hidden');
   tar.group.setAttribute('opacity',rescued.has(tar.target.id)?'.35':'1');
 }
 for(const failure of refs.failureNodes){
   failure.group.setAttribute('visibility',failure.data.t<=t?'visible':'hidden');
 }
 for(const obj of refs.actorList){
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
  marker.count.textContent=upto(marker.run[marker.field]||[],state.t)+' / '+state.data.scenario.n_people;
 }}
 if(force||performance.now()-state.uiLast>250){fillResultsTable();state.uiLast=performance.now();}
 if(state.t>=horizon&&state.playing){state.playing=false;$('play-btn').textContent='▶';}
}
function fillResultsTable(){
 const mode=state.mode, isScout=mode==='scout';
 const labels=isScout?
  ['Место','Алгоритм','Баллы / 100','Найдено','Секторов','Темп, чел/мин','Энергия, Wh','Окончание работы, с','План, мс']:
  ['Место','Алгоритм','Баллы / 100','Спасено','Найдено','Темп, чел/мин','Рейс, с/чел','Энергия, Wh','Последняя доставка, с','Окончание работы, с','План, мс'];
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
     rescue.last===null?'—':fixed(rescue.last,1),elapsedText(run.final.finished_at),fixed(met.compute,1)];
  }
  values.forEach(v=>tr.append(el('td',{},String(v))));body.append(tr);
 });table.append(body);
 $('table-status').textContent='Текущий момент: '+fmtTime(state.t)+' · окончание работы — итоговое время';
 $('score-method').textContent=mode==='scout'?
  'Формула баллов: 65% — доля найденных; 25% — насколько рано обнаружены; 10% — экономия энергии с учётом результата. 100 баллов — теоретический максимум.':
  mode==='rescue'?
  'Формула баллов: 70% — доля спасённых; 20% — насколько рано доставлены; 10% — экономия энергии с учётом результата. Сортировка — по баллам.':
  'Формула баллов: 60% — доля спасённых; 15% — доля обнаруженных; 15% — ранняя эвакуация; 10% — экономия энергии с учётом результата.';
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
 const run=state.data.runs.find(r=>r.method==='nsga2'||r.method==='nsga2_nsga2');
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
function bind(){setMode();
 $('scenario-form').addEventListener('submit',e=>{e.preventDefault();const p=new URL(window.location.href);p.searchParams.set('seed',$('seed').value);p.searchParams.set('people',$('people').value);p.searchParams.set('scenario',$('scenario').value);p.searchParams.set('map_size',$('map-size').value);p.searchParams.set('scouts',$('scouts').value);p.searchParams.set('rescuers',$('rescuers').value);history.replaceState({},'',p);load();});
 $('play-btn').addEventListener('click',()=>{if(!state.data)return;if(state.t>=state.data.scenario.horizon)update(0,true);state.playing=!state.playing;$('play-btn').textContent=state.playing?'❚❚':'▶';});
 $('step-btn').addEventListener('click',()=>{state.playing=false;$('play-btn').textContent='▶';update(state.t+5,true);});
 $('reset-btn').addEventListener('click',()=>{state.playing=false;$('play-btn').textContent='▶';update(0,true);});
 $('time-slider').addEventListener('input',e=>{state.playing=false;$('play-btn').textContent='▶';update(+e.target.value,true);});
 $('speed').addEventListener('change',e=>{state.speed=+e.target.value;});
 $('export-btn').addEventListener('click',()=>{if(!state.data)return;const b=new Blob([JSON.stringify(state.data,null,2)],{type:'application/json;charset=utf-8'});
  const a=el('a');a.href=URL.createObjectURL(b);a.download=`metarescue_${state.mode}_${state.data.scenario.scenario_type}_${state.data.scenario.width}x${state.data.scenario.height}_seed${state.data.scenario.seed}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);toast('Результаты сохранены в JSON');});
 const q=new URLSearchParams(window.location.search);
 if(q.has('seed'))$('seed').value=q.get('seed');if(q.has('people'))$('people').value=q.get('people');if(q.has('scenario'))$('scenario').value=q.get('scenario');
 if(q.has('map_size'))$('map-size').value=q.get('map_size');if(q.has('scouts'))$('scouts').value=q.get('scouts');if(q.has('rescuers'))$('rescuers').value=q.get('rescuers');
 state.speed=+$('speed').value;
 load();requestAnimationFrame(tick);
}
function tick(now){if(state.playing&&state.data&&state.lastFrame){const dt=Math.min(.25,(now-state.lastFrame)/1000);update(state.t+dt*state.speed);}
 state.lastFrame=now;requestAnimationFrame(tick);
}
window.addEventListener('DOMContentLoaded',bind);
