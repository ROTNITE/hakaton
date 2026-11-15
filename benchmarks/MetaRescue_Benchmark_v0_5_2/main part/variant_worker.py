"""Isolated subprocess for one benchmark variant (avoids shared mutable planner state).
Parameters contain no secrets; DeepSeek API key is read from inherited environment.
"""
from __future__ import annotations
import json,sys
from pathlib import Path
from world import World
from mission_v05 import run_mission_v05
from ai_v05 import AIOrchestrator

LABELS={'base':'NSGA-II + NSGA-II','global_ai':'NSGA-II ×2 + Global AI',
        'global_local_ai':'NSGA-II ×2 + Global + Local AI'}

def execute(settings):
    name=settings['variant']
    if name not in LABELS:raise ValueError('Unrecognized variant')
    world=World(settings['seed'],settings['people'],settings['preset'],
                settings['grid_size'],settings['scouts'],settings['rescuers'],
                settings['probabilities'])
    ai=None if name=='base' else AIOrchestrator(name,settings['ai_mode'],
         settings['max_calls'],settings['local_timeout'],settings['global_timeout'])
    result=run_mission_v05(world,name,ai=ai)
    result['method']=name;result['label']=LABELS[name]
    result['ai_stats']=ai.summary() if ai else {'mode':'off','connected':False,
      'calls':0,'input_tokens':0,'output_tokens':0,'api_wall_s':0,'api_errors':0,
      'local_actions':0,'global_actions':0,'fallbacks':0,'messages':0}
    return result

if __name__=='__main__':
    settings=json.loads(sys.argv[1]);target=Path(sys.argv[2])
    data=execute(settings)
    target.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf-8')
