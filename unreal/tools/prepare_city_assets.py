"""Create city render derivatives. Originals, v2 and Quarter meshes are read-only.

Opaque triangles become Nanite meshes for instanced Lumen coverage. Transparent
triangles remain conventional glass. C++ verifies the full triangle multiset,
including every source position, normal, UV channel and material slot.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import unreal

ROOT=Path(unreal.Paths.project_dir()).resolve().parents[1]
CONTENT=ROOT/'unreal/MetaRescue/Content'
LIB=unreal.EditorAssetLibrary
VERSION='city-assets-v1-split-nanite-3-section-bindings'
library_file=CONTENT/'Scenario/library-v3.json'
library=json.loads(library_file.read_text(encoding='utf-8'))
library_hash=hashlib.sha256(library_file.read_bytes()).hexdigest()
probe='-MRCityAssetProbe' in unreal.SystemLibrary.get_command_line()
repair='-MRCityGlassRepair' in unreal.SystemLibrary.get_command_line()
if probe and repair:raise RuntimeError('Choose a probe or a full glass-binding repair')
previous=json.loads((CONTENT/'Scenario/city-assets.json').read_bytes()) if repair else None


def source_file(path):
    package=path.split('.')[0]
    base=CONTENT if package.startswith('/Game/') else Path(unreal.Paths.engine_content_dir())
    return base/(package.split('/',2)[2]+'.uasset')


def prepare(path,scale=(1.,1.,1.)):
    source=unreal.load_asset(path)
    assert isinstance(source,unreal.StaticMesh),path
    key=hashlib.sha256(source_file(path).read_bytes()+
                       json.dumps([VERSION,library_hash,path,scale]).encode()).hexdigest()[:16]
    package='/Game/RescueAssets/CityV1/'+source.get_name()+'_'+key
    result=json.loads(unreal.MRAssetTools.prepare_city_mesh(source,package,unreal.Vector(*scale)))
    assert result.get('verified'),(path,scale,result)
    assert result.get('render_sections_verified'),(path,scale,result)
    assert result['source_triangles']==sum(p['triangles'] for p in result['parts']),result
    for part in result['parts']:
        mesh=unreal.load_asset(part['mesh'])
        assert mesh is not None,part
        assert LIB.save_loaded_asset(mesh),part
        check=json.loads(unreal.MRAssetTools.describe_mesh_geometry(mesh))
        assert check['nanite_enabled']==(part['kind']=='opaque'),(part,check)
        assert check['fallback_target']=='percent_triangles' and check['fallback_triangle_fraction']==1,check
    return result


paths={f'/Engine/BasicShapes/{name}.{name}' for name in ('Cube','Cylinder','Cone','Plane')}
for asset in library['assets']:
    if asset['id'] not in {'Drone','Rover','Casualty','Stretcher'}:
        paths.update(part['mesh'] for part in asset['parts'])
if probe:
    paths={'/Engine/BasicShapes/Cube.Cube'}
    for asset_id,prefix in [('GlazingKit','window_01_clean'),('UrbanKit','wall_window_centered_large_01')]:
        asset=next(a for a in library['assets'] if a['id']==asset_id)
        paths.add(next(p['mesh'] for p in asset['parts'] if p['object']==prefix))
if repair:
    paths={path for path,record in previous['replacements'].items() if any(part['kind']=='glass' for part in record['parts'])}
source_hashes={path:hashlib.sha256(source_file(path).read_bytes()).hexdigest() for path in paths}
replacements=dict(previous['replacements']) if repair else {}
replacements.update({path:prepare(path) for path in sorted(paths)})
sizes=[(900,900,16),(600,900,16),(300,600,16),(15,720,278),(740,12,278),(900,900,14)]
boxes=previous['baked_boxes_cm'] if repair else {
    ','.join(f'{v:.3f}' for v in size):prepare('/Engine/BasicShapes/Cube.Cube',tuple(v/100 for v in size))
    for size in (sizes[:1] if probe else sizes)}
unreal.MRAssetTools.finish_asset_compilation()
section_checks=[]
changed_meshes={part['mesh'] for path in paths for part in replacements[path]['parts']}
for record in [*replacements.values(),*boxes.values()]:
    for part in record['parts']:
        mesh=unreal.load_asset(part['mesh'])
        check=json.loads(unreal.MRAssetTools.describe_mesh_geometry(mesh))
        expected={group['slot'] for group in check['source_groups'] if group['triangles']}
        actual={section['slot'] for section in check['render_sections'] if section['triangles']}
        assert expected==actual,('Built material slots differ from source polygon groups',part,expected,actual)
        section_checks.append({'mesh':part['mesh'],'active_slots':sorted(actual)})
        # Existing read-only derivatives need no resave during a focused repair.
        if not repair or part['mesh'] in changed_meshes:assert LIB.save_loaded_asset(mesh)
assert source_hashes=={path:hashlib.sha256(source_file(path).read_bytes()).hexdigest() for path in paths},'Source meshes changed'
assert hashlib.sha256(library_file.read_bytes()).hexdigest()==library_hash,'Source library changed'
report={'format':VERSION,'source_library_sha256':library_hash,'replacements':replacements,
        'baked_boxes_cm':boxes,'native_geometry_verified':True,'render_bindings_verified':True,
        'section_checks':section_checks,'source_mesh_hashes':source_hashes,
        'visual_acceptance':False,'repair_sources':len(paths) if repair else None}
folder=Path('D:/MetaRescue-output/city-assets');folder.mkdir(parents=True,exist_ok=True)
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
target=folder/(stamp+('-probe.json' if probe else '-manifest.json'))
target.write_text(json.dumps(report,indent=2),encoding='utf-8')
if not probe:
    (CONTENT/'Scenario/city-assets.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
unreal.log('MR_CITY_ASSETS_READY '+str(len(replacements))+' '+str(target))
