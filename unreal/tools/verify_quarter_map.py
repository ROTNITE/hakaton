"""Read back the saved quarter and inspect real mesh/material references."""
from pathlib import Path
import json

import unreal


root = Path(unreal.Paths.project_dir()).resolve().parents[1]
level = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
assert level.load_level('/Game/Maps/RescueQuarter')
cls = unreal.load_class(None, '/Script/MetaRescue.MRWorld')
worlds = [a for a in actors.get_all_level_actors() if a.get_class() == cls]
assert len(worlds) == 1 and worlds[0].get_editor_property('rescue_quarter')
components = worlds[0].get_components_by_class(unreal.StaticMeshComponent)
counts = {}
for component in components:
    mesh = component.get_editor_property('static_mesh')
    assert mesh is not None, component.get_name()
    for slot in range(component.get_num_materials()):
        assert component.get_material(slot) is not None, (component.get_name(), slot)
    path = mesh.get_path_name()
    counts[path] = counts.get(path, 0) + 1
library=json.loads((root/'unreal/MetaRescue/Content/Scenario/library-v2.json').read_text())
placed=[]
for record in library['assets']:
    if record['id'] in {'Rover','Drone','Casualty'}:continue  # spawned mission actors
    assert any(path.startswith(record['folder']+'/') for path in counts), 'Missing placed assembly: '+record['id']
    placed.append(record['id'])
for name in ['Beam','UtilityTunnel']:
    assert any(('/SM_'+name+'.') in path for path in counts), 'Missing authored geometry: '+name
spotlights=worlds[0].get_components_by_class(unreal.SpotLightComponent)
assert len(spotlights)==20, 'Missing street lighting'
result = {'passed': True, 'map': '/Game/Maps/RescueQuarter', 'static_mesh_components': len(components),
          'mesh_instances': counts, 'placed_library_assemblies':placed,'street_spotlights':len(spotlights),
          'runtime_assemblies':['Drone','Rover','Casualty']}
(root / 'artifacts/3d-world/quarter-map-verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
unreal.log('MR_QUARTER_MAP_VERIFIED: ' + str(len(components)))
