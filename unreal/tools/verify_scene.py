"""Read-only Unreal commandlet check for an extracted project package."""
import json
from pathlib import Path
import unreal

levels=unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
assert levels.load_level('/Game/Maps/RescueDistrict'),'Map load failed'
actors=unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
world_class=unreal.load_class(None,'/Script/MetaRescue.MRWorld')
districts=[a for a in actors if a.get_class()==world_class]
assert len(districts)==1,'Expected one native district actor'
components=districts[0].get_components_by_class(unreal.StaticMeshComponent)
assert len(components)>500,'Generated geometry missing'
assert all(c.get_editor_property('static_mesh') is not None and c.get_material(0) is not None for c in components),'Missing mesh/material'
content=Path(unreal.Paths.project_content_dir())
scenario=json.loads((content/'Scenario/scenario.json').read_text(encoding='utf-8'))
assert scenario['source_version']=='0.3'
assert scenario['centimetres_per_cell']==1000
out={'passed':True,'native_actor':'MRWorld','static_mesh_components':len(components),
     'scenario_source':scenario['source_version'],'map':'/Game/Maps/RescueDistrict'}
folder=Path(unreal.Paths.project_saved_dir())/'Automation';folder.mkdir(parents=True,exist_ok=True)
(folder/'package-scene-check.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
unreal.log('MR_PACKAGE_VERIFIED '+json.dumps(out))
