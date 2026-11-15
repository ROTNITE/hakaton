"""Read actual built section bindings for source and split city windows."""
from datetime import datetime,timezone
import json
from pathlib import Path
import unreal


root=Path(unreal.Paths.project_dir()).resolve().parents[1]
catalog=json.loads((root/'unreal/MetaRescue/Content/Scenario/city-assets.json').read_bytes())
records=[]
for path,record in catalog['replacements'].items():
    if not path.rsplit('/',1)[-1].startswith('SM_window_01_'):
        continue
    for kind,target in [('source',path)]+[(part['kind'],part['mesh']) for part in record['parts']]:
        mesh=unreal.load_asset(target)
        if not isinstance(mesh,unreal.StaticMesh):raise RuntimeError('Missing window mesh: '+target)
        unreal.MRAssetTools.finish_asset_compilation()
        slots=[]
        for slot in mesh.get_editor_property('static_materials'):
            material=slot.get_editor_property('material_interface')
            slots.append({'name':str(slot.get_editor_property('imported_material_slot_name')),
                'material':material.get_path_name() if material else None,
                'blend':str(material.get_blend_mode()) if material else None})
        geometry=json.loads(unreal.MRAssetTools.describe_mesh_geometry(mesh))
        sections=geometry.get('render_sections',[])
        records.append({'source':path,'mesh':target,'kind':kind,'slots':slots,'sections':sections,
                        'geometry':geometry})
if len({row['source'] for row in records})!=5 or any(not row['sections'] for row in records):
    raise RuntimeError('Expected built sections for all five window states')
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
file=Path('D:/MetaRescue-output/checks')/(stamp+'-window-sections.json')
file.write_text(json.dumps(records,indent=2),encoding='utf-8')
unreal.log('MR_WINDOW_SECTIONS '+str(file))
