"""Import the prepared visual bodies without replacing native collision."""
from pathlib import Path
import hashlib
import json
import os

import unreal


SOURCE = Path(os.environ['MR_COMPETITION_ASSET_MANIFEST']).resolve(strict=True)
FOLDER = '/Game/RescueAssets/Competition'
MATERIALS = {'SafetyYellow': 'MI_Orange', 'SignalOrange': 'MI_Orange',
             'RescueTeal': 'MI_Teal', 'DarkRubber': 'MI_Rubber'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def import_vehicle(row):
    file = SOURCE.parent/row['fbx']
    assert digest(file) == row['fbx_sha256']
    name = 'SM_'+row['id']
    path = FOLDER+'/'+name
    assert not unreal.EditorAssetLibrary.does_asset_exist(path), 'Existing asset: '+path
    settings = unreal.FbxImportUI()
    settings.set_editor_properties({'import_mesh':True,'import_as_skeletal':False,'import_materials':False,
        'import_textures':False,'automated_import_should_detect_type':False,
        'mesh_type_to_import':unreal.FBXImportType.FBXIT_STATIC_MESH})
    settings.get_editor_property('static_mesh_import_data').set_editor_properties({
        'combine_meshes':True,'auto_generate_collision':False,'build_nanite':False,
        'convert_scene':True,'convert_scene_unit':True,'force_front_x_axis':False})
    task = unreal.AssetImportTask()
    task.set_editor_properties({'filename':str(file),'destination_path':FOLDER,'destination_name':name,
                                'automated':True,'save':False,'replace_existing':False,'options':settings})
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    asset = unreal.load_asset(path)
    assert isinstance(asset,unreal.StaticMesh), path
    readback = []
    for index,slot in enumerate(asset.get_editor_property('static_materials')):
        label = str(slot.get_editor_property('imported_material_slot_name'))
        material_name = MATERIALS[label]
        material = unreal.load_asset('/Game/Materials/'+material_name)
        assert material, material_name
        asset.set_material(index,material)
        readback.append({'source_slot':label,'material':material.get_path_name()})
    assert {m['source_slot'] for m in readback}==set(row['material_slots'])
    native = json.loads(unreal.MRAssetTools.describe_mesh_geometry(asset))
    assert native['available'] and native['triangles']==row['triangles'], native
    measured = [(hi-lo)/100 for lo,hi in zip(native['source_min_cm'],native['source_max_cm'])]
    assert all(abs(got-want)<.01 for got,want in zip(measured,row['dimensions_m'])), (measured,row)
    assert unreal.EditorAssetLibrary.save_loaded_asset(asset), path
    return {'id':row['id'],'mesh':asset.get_path_name(),'dimensions_m':measured,'triangles':native['triangles'],
            'materials':readback,'source_fbx_sha256':row['fbx_sha256']}


data = json.loads(SOURCE.read_bytes())
models = [import_vehicle(row) for row in data['assets']]
unreal.MRAssetTools.finish_asset_compilation()
with (SOURCE.parent/'unreal-import.json').open('x',encoding='utf-8') as stream:
    json.dump({'prepared_sha256':digest(SOURCE),'models':models,'passed':True},stream,ensure_ascii=False,indent=2)
unreal.log('MR_COMPETITION_VEHICLE_IMPORT_OK')
