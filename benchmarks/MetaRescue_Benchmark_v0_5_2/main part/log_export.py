"""Streaming, human-readable exhaustive TXT audit of one complete comparison.
Every model second has a complete top-down ASCII map for EACH variant.
No future truth or secret is ever sent to a planner. The exporter is privileged.
"""
from __future__ import annotations
import bisect, json, math
from collections import defaultdict

def as_json(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),default=str)
LEGEND={0:'.',1:'#',2:':',3:'~'}
HAZARD={'collapse':'C','fire':'F','flood':'W','mud':'M','road_damage':'X'}

def index_segments(segments, count):
    grouped=[[] for _ in range(count)]
    for s in segments:
        if s['r']<count:grouped[s['r']].append(s)
    for arr in grouped:arr.sort(key=lambda x:x['t0'])
    return [(arr,[q['t0'] for q in arr]) for arr in grouped]

def pose(index,t):
    segments,starts=index
    j=bisect.bisect_right(starts,t+1e-9)-1
    if j<0:return (segments[0]['a'] if segments else [1,1]),'idle'
    seg=segments[j]
    if t>=seg['t1']:return seg['b'],'idle'
    p=min(1.,max(0.,(t-seg['t0'])/max(1e-8,seg['t1']-seg['t0'])))
    return [seg['a'][k]+(seg['b'][k]-seg['a'][k])*p for k in range(2)],seg.get('action','move')

def log_chunks(data):
    scenario=data['scenario'];runs=data['runs'];n=scenario['width'];h=math.ceil(scenario['horizon'])
    yield ('META-RESCUE BENCHMARK v0.5.2 — ПОЛНЫЙ ТЕКСТОВЫЙ ПРОТОКОЛ\n'
           'ПРЕДУПРЕЖДЕНИЕ: блоки TRUTH_MAP являются привилегированными снимками для ПОСЛЕДУЮЩЕГО аудита. '\
           'Ни одна LLM и ни один планировщик не получают эти снимки.\n'
           'Невозможно экспортировать скрытые внутренние рассуждения модели: здесь записаны полные входные запросы, '
           'видимые JSON-ответы, reason_codes, проверки, сообщения, действия и результаты.\n'
           'Легенда: .=дорога, #=препятствие, :=трудная поверхность, ~=вода, C=обрушение, F=огонь, W=затопление, '
           'M=грязь, X=повреждение дороги, S=дым, ?=скрытый человек, P=обнаруженный человек, '
           'r=эвакуатор, d=дрон, B=база.\n'
           f'РАЗМЕР={n}x{n}; МОДЕЛЬНЫЕ СЕКУНДЫ=0..{h}; SEED={scenario["seed"]}; '\
           f'НАЧАЛЬНЫЕ ЛЮДИ={scenario["initial_people"]}; ВСЕГО={scenario["n_people"]}; '\
           f'РЕЖИМ_AI={data.get("ai_mode","off")}\n\n').encode('utf-8')
    yield ('==== ИСХОДНЫЕ УСЛОВИЯ / НАСТРОЙКИ ===='+'\n'+as_json({k:v for k,v in scenario.items() if k!='grid'})+'\n\n').encode('utf-8')
    truth_people=data.get('_truth_people',[])
    # The scenario grid itself is already repeated in every second, no hidden coords in UI JSON.
    for run in runs:
        heading=f'\n{"="*90}\nVARIANT {run["method"]}: {run["label"]}\n{"="*90}\n'
        yield heading.encode('utf-8')
        yield ('FINAL_METRICS '+as_json(run['final'])+'\nOPTIMIZATION '+as_json(run.get('opt',{}))+
               '\nAI_METRICS '+as_json(run.get('ai_stats',{}))+'\n').encode('utf-8')
        if run.get('audit'):
            yield b'\n==== AI REQUESTS / RESPONSES / MESSAGES / VALIDATION / REPLAN LOG (ALL) ====\n'
            for e in run['audit']:
                yield ('AUDIT '+as_json(e)+'\n').encode('utf-8')
        else:yield b'\n==== BASELINE: NO AI CALLS ====\n'
        for field in ('terrain_events','knowledge_events','signals','visits','discoveries','decisions','incidents','stranding','rescues','failures'):
            yield f'\n==== {field.upper()} (ALL) ====\n'.encode('utf-8')
            for e in run.get(field,[]):yield (field.upper()+' '+as_json(e)+'\n').encode('utf-8')
        for field in ('scout_segments','rescue_segments'):
            yield f'\n==== {field.upper()} — EACH PHYSICAL MOVEMENT SEGMENT ====\n'.encode('utf-8')
            for item in run.get(field,[]):
                yield ('MOVE '+field+' '+as_json(item)+'\n').encode('utf-8')
        yield b'\n==== SECOND-BY-SECOND WORLD + ALL ROBOT POSITIONS ====\n'
        scout_idx=index_segments(run.get('scout_segments',[]),scenario['scouts'])
        rescue_idx=index_segments(run.get('rescue_segments',[]),scenario['rescuers'])
        terrain_events=sorted(scenario.get('environment_events',[]),key=lambda e:e['t'])
        knowledge_events=sorted(run.get('knowledge_events',[]),key=lambda e:e['t'])
        known_cursor=0;known_hazards={};known_smoke=set();last_seen={}
        change_cursor=0;hazards={};smoke=set();targets=set();rescued=set()
        discoveries=sorted(run.get('discoveries',[]),key=lambda e:e['t']);rescues=sorted(run.get('rescues',[]),key=lambda e:e['t'])
        di=ri=0
        for second in range(h+1):
            current=[]
            while change_cursor<len(terrain_events) and terrain_events[change_cursor]['t']<=second:
                e=terrain_events[change_cursor];change_cursor+=1
                for pt in e.get('cells',[]):
                    xy=tuple(pt)
                    if e['type']=='smoke':smoke.add(xy)
                    elif e['type']=='smoke_clear':smoke.discard(xy)
                    else:hazards[xy]=HAZARD.get(e['type'],'!')
            while di<len(discoveries) and discoveries[di]['t']<=second:
                targets.add(discoveries[di]['id']);di+=1
            while ri<len(rescues) and rescues[ri]['t']<=second:
                rescued.add(rescues[ri]['id']);ri+=1
            while known_cursor<len(knowledge_events) and knowledge_events[known_cursor]['t']<=second:
                item=knowledge_events[known_cursor];known_cursor+=1
                last_seen[item['sector']]=item['observed_at']
                for x,y,kind,flag in item['cells']:
                    if kind:known_hazards[(x,y)]=HAZARD.get(kind,'!')
                    else:known_hazards.pop((x,y),None)
                    if flag:known_smoke.add((x,y))
                    else:known_smoke.discard((x,y))
            known_grid=[[LEGEND[c] for c in row] for row in scenario['grid']]
            for (x,y),c in known_hazards.items():known_grid[y][x]=c
            for x,y in known_smoke:known_grid[y][x]='S'
            grid=[[LEGEND[c] for c in row] for row in scenario['grid']]
            for (x,y),c in hazards.items():grid[y][x]=c
            for x,y in smoke:grid[y][x]='S'
            for person in truth_people:
                if person['appearance_t']>second or person['id'] in rescued:continue
                x,y=person['x'],person['y']
                grid[y][x]='P' if person['id'] in targets else '?'
            positions=[]
            for kind,group,char in [('drone',scout_idx,'d'),('evacuator',rescue_idx,'r')]:
                for i,index in enumerate(group):
                    xy,action=pose(index,second)
                    x=max(0,min(n-1,round(xy[0])));y=max(0,min(n-1,round(xy[1])))
                    positions.append({'id':f'{kind}_{i+1:02d}','pos':[round(v,3) for v in xy],
                                      'action':action})
                    grid[y][x]=char
            grid[1][1]='B'
            current.append(f'\n===== SECOND {second:05d} | VARIANT {run["method"]} =====')
            current.append('SCENE '+as_json({'model_t':second,'known_targets':sorted(targets),
                'rescued_targets':sorted(rescued),'hazard_cells':len(hazards),
                'smoke_cells':len(smoke),'known_hazard_cells':len(known_hazards),
                'known_sectors':len(last_seen),'agents':positions}))
            current.append(f'TRUTH_MAP_BEGIN {n}x{n}')
            current.extend(''.join(row) for row in grid)
            current.append('TRUTH_MAP_END')
            current.append(f'TEAM_KNOWN_MAP_BEGIN {n}x{n}')
            current.extend(''.join(row) for row in known_grid)
            current.append('TEAM_KNOWN_MAP_END')
            yield ('\n'.join(current)+'\n').encode('utf-8')
    yield b'\n==== END OF COMPLETE AUDIT ====\n'
