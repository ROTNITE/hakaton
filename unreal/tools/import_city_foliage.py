"""Import project-authored street trees and verify real source geometry."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import unreal

CONTENT=Path(unreal.Paths.project_content_dir())
assets=unreal.EditorAssetLibrary
files=sorted(Path('D:/MetaRescue-output/city-foliage').glob('*/manifest.json'))
assert files,'Prepare city foliage with Blender first'
source=json.loads(files[-1].read_text(encoding='utf-8'))
models=[]
for row in source['models']:
    fbx=Path(row['fbx']);assert hashlib.sha256(fbx.read_bytes()).hexdigest()==row['sha256']
    name='SM_StreetTree_'+str(row['variant'])+'_'+row['sha256'][:12]
    folder='/Game/RescueAssets/CityV1/Foliage'
    raw_path=folder+'/Source/'+name
    mesh=unreal.load_asset(raw_path)
    if mesh is None:
        options=unreal.FbxImportUI()
        for key,value in [('import_mesh',True),('import_as_skeletal',False),('import_materials',False),
                          ('import_textures',False),('automated_import_should_detect_type',False),
                          ('mesh_type_to_import',unreal.FBXImportType.FBXIT_STATIC_MESH)]:options.set_editor_property(key,value)
        data=options.get_editor_property('static_mesh_import_data')
        for key,value in [('combine_meshes',True),('auto_generate_collision',False),('build_nanite',False),
                          ('convert_scene',True),('convert_scene_unit',True),('force_front_x_axis',True)]:data.set_editor_property(key,value)
        task=unreal.AssetImportTask()
        for key,value in [('filename',str(fbx)),('destination_path',folder+'/Source'),('destination_name',name),
                          ('automated',True),('save',True),('replace_existing',False),('options',options)]:task.set_editor_property(key,value)
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        mesh=unreal.load_asset(raw_path)
    assert isinstance(mesh,unreal.StaticMesh),raw_path
    for index,slot in enumerate(mesh.get_editor_property('static_materials')):
        label=str(slot.get_editor_property('imported_material_slot_name'))
        assert 'City_Bark' in label or 'City_Leaves' in label,label
        material=unreal.load_asset('/Game/MaterialsCity/'+('City_Bark' if 'City_Bark' in label else 'City_Leaves'))
        mesh.set_material(index,material)
    assert assets.save_loaded_asset(mesh)
    geometry=json.loads(unreal.MRAssetTools.describe_mesh_geometry(mesh))
    assert geometry['available'],geometry
    assert abs(geometry['source_min_cm'][2])<.01,geometry
    assert abs(geometry['source_max_cm'][2]-row['height_m']*100)<.01,geometry
    assert max(abs(v) for key in ('source_min_cm','source_max_cm') for v in geometry[key][:2])<=220,geometry
    result=json.loads(unreal.MRAssetTools.prepare_city_mesh(mesh,folder+'/'+name,unreal.Vector(1,1,1)))
    assert result.get('verified') and len(result['parts'])==1,result
    derived=unreal.load_asset(result['parts'][0]['mesh']);assert assets.save_loaded_asset(derived)
    models.append({'variant':row['variant'],'height_m':row['height_m'],'mesh':derived.get_path_name(),
                   'geometry':geometry,'triangle_preservation':result,'fbx_sha256':row['sha256']})
unreal.MRAssetTools.finish_asset_compilation()
report={'format':'city-foliage-1','source_manifest':str(files[-1]),'models':models,'native_render_verified':False}
target=Path('D:/MetaRescue-output/city-foliage')/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-import.json')
target.write_text(json.dumps(report,indent=2),encoding='utf-8')
(CONTENT/'Scenario/city-foliage.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
unreal.log('MR_CITY_FOLIAGE_IMPORTED '+str(target))
