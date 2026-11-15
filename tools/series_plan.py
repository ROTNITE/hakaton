"""Freeze the 30-map, 450-run native comparison before any scoring."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from environment.config import EVENT_DEFAULTS,Settings
from environment.disturbances import FORMAT as DISTURBANCE_FORMAT,validate_tape as validate_disturbances
from environment.events import validate_tape as validate_events
from environment.layout import generate,public_map


FORMAT='metarescue.native-series.v1'
FAMILIES=('open','urban','clusters','scarce','uncertain','dynamic')
OPTIMIZER_SEEDS=(1129,2039,3253)
POLICIES=(
    ('dual-off','nsga2_nsga2','OFF','global_local'),
    ('dual-global','nsga2_nsga2','MOCK','global'),
    ('dual-global-local','nsga2_nsga2','MOCK','global_local'),
    ('fixed','fixed_workflow','OFF','global_local'),
    ('reactive','local_reactive','OFF','global_local'),
)


def json_bytes(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,
                       separators=(',',':'))+'\n').encode('utf-8')


def digest(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def tape_digest(world):
    return digest({name:world.get(name) for name in ('event_model','disturbances')})


def world_for(family,index):
    settings={'map_size':25,'city_revision':'2.2','preset':FAMILIES[family-1],'horizon':480,
              'scouts':3,'rescuers':3,'people':12,'seed':5000+100*family+index,
              'event_profile':'v052','probabilities':dict.fromkeys(EVENT_DEFAULTS['v052'],0)}
    if family==4:
        settings.update(rescuers=1,resource_profile='contest',ground_battery_wh=35,aerial_battery_wh=120)
        settings['probabilities']['mud']=100
    if family==5:
        settings.update(sensor_reliability=.74,communication_loss=.12,communication_latency_s=.35)
    if family==6:
        settings['probabilities']=dict(EVENT_DEFAULTS['v052'])
    world=generate(Settings.parse(settings),include_events=True)
    if family==6:
        # The subject is chosen before dispatch, independent of route/score.
        ground=[agent for agent in world['spawns'] if agent['kind']=='ground']
        failed=ground[(index-1)%len(ground)]['id']
        world['disturbances']={'format':DISTURBANCE_FORMAT,'events':[
            {'id':'s6-carrier-loss','type':'agent_failure','time':132,'until':None,
             'source':'scenario-supervisor','targets':[failed],'parameters':{'reason':'traction_failure'}},
            {'id':'s6-radio-gap','type':'connectivity_loss','time':208,'until':249,
             'source':'scenario-supervisor','targets':[world['spawns'][-1]['id']],
             'parameters':{'reason':'transient_radio_partition'}}]}
        validate_disturbances(world['disturbances'],world)
    validate_events(world['event_model'],world)
    return world


def design(output):
    output.mkdir(parents=True,exist_ok=False)
    maps=output/'maps';maps.mkdir()
    plan={'format':FORMAT,'simulation':'Unreal Core Protocol 1.0',
          'renderer':'null_rhi','comparison_horizon_s':480,'worlds':[],'runs':[]}
    for family in range(1,7):
        for index in range(1,6):
            identifier=f'S{family}-{index:02d}'
            world=world_for(family,index)
            private=maps/(identifier+'.private.json')
            public=maps/(identifier+'.public.json')
            private.write_bytes(json_bytes(world));public.write_bytes(json_bytes(public_map(world)))
            entry={'id':identifier,'family':f'S{family}','seed':world['settings']['seed'],
                   'private_layout':private.relative_to(output).as_posix(),
                   'public_layout':public.relative_to(output).as_posix(),
                   'layout_sha256':digest(world),'external_tape_sha256':tape_digest(world)}
            plan['worlds'].append(entry)
            for repeat,optimizer in enumerate(OPTIMIZER_SEEDS,1):
                offset=(family+index+repeat)%len(POLICIES)
                for tag,policy,mode,scope in POLICIES[offset:]+POLICIES[:offset]:
                    plan['runs'].append({'id':f'{identifier}-O{repeat}-{tag}',
                        'world':identifier,'optimizer_seed':optimizer,'policy_id':tag,
                        'policy':policy,'ai_mode':mode,'ai_scope':scope})
    assert len(plan['worlds'])==30 and len(plan['runs'])==450
    manifest=output/'plan.json'
    manifest.write_bytes(json_bytes(plan))
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    manifest=design(args.output)
    print(json.dumps({'plan':str(manifest.resolve()),'sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
                      'worlds':30,'planned_runs':450,'completed_native_runs':0}))
