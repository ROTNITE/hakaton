"""Update only the authored post process, preserving the baked lighting meshes."""
import json
from datetime import datetime, timezone
from pathlib import Path
import unreal

level=unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
assert level.load_level('/Game/Maps/RescueQuarter')
actors=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
post=next(a for a in actors.get_all_level_actors() if isinstance(a,unreal.PostProcessVolume))
settings=post.get_editor_property('settings')
values={'auto_exposure_method':unreal.AutoExposureMethod.AEM_HISTOGRAM,
        'auto_exposure_min_brightness':6.0,'auto_exposure_max_brightness':12.8,
        'auto_exposure_low_percent':50.0,'auto_exposure_high_percent':80.0,
        'auto_exposure_speed_up':4.0,'auto_exposure_speed_down':3.0}
for key,value in values.items():
    settings.set_editor_property('override_'+key,True)
    settings.set_editor_property(key,value)
post.set_editor_property('settings',settings)
assert level.save_current_level()
readback=post.get_editor_property('settings')
for key,value in values.items():
    actual=readback.get_editor_property(key)
    assert readback.get_editor_property('override_'+key)
    assert abs(actual-value)<.001 if isinstance(value,float) else actual==value
folder=Path('D:/MetaRescue-output/lighting');folder.mkdir(parents=True,exist_ok=True)
target=folder/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-exposure.json')
target.write_text(json.dumps({'settings':{key:str(value) for key,value in values.items()},
                              'visual_acceptance':False},indent=2),encoding='utf-8')
unreal.log('MR_EXPOSURE_AUTHORED '+str(target))
