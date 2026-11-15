"""Import the verified supplied skin and its actual FBX animation clips."""
from pathlib import Path
import json
import sys
import unreal
sys.path.insert(0,str(Path(__file__).resolve().parent))
from import_rescue_assets import import_one, ROOT, ASSETS, LIB
from import_asset_library import material


def import_typed(filename, destination, name, options, expected):
    task=unreal.AssetImportTask()
    for key,value in [('filename',str(filename)),('destination_path',destination),('destination_name',name),
                      ('automated',True),('replace_existing',True),('save',True),('options',options)]:
        task.set_editor_property(key,value)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    created=[unreal.load_asset(p) for p in task.get_editor_property('imported_object_paths')]
    matches=[a for a in created if isinstance(a,expected)]
    if len(matches)!=1:raise RuntimeError('Unexpected typed FBX import: '+str([(str(a),a.get_class().get_name()) for a in created]))
    return matches[0]

folder = ROOT / 'blender/prepared/v2/MannequinRig'
record = json.loads((folder/'rig.json').read_text(encoding='utf-8'))
dest = '/Game/RescueAssets/Library/MannequinRig'
mats = {m['name']:material(m,{'id':'MannequinRig'},dest,folder) for m in record['materials']}
options = unreal.FbxImportUI()
for key,value in [('automated_import_should_detect_type',False),('import_mesh',True),('import_as_skeletal',True),
                  ('import_materials',False),('import_textures',False),('import_animations',False),
                  ('mesh_type_to_import',unreal.FBXImportType.FBXIT_SKELETAL_MESH)]:
    options.set_editor_property(key,value)
data = options.get_editor_property('skeletal_mesh_import_data')
for key,value in [('convert_scene',True),('convert_scene_unit',True),('force_front_x_axis',True)]:data.set_editor_property(key,value)
skin = import_typed(folder / 'MannequinRig.fbx',dest,'SK_RescueMannequin',options,unreal.SkeletalMesh)
slots = skin.get_editor_property('materials')
for slot in slots:
    name = str(slot.get_editor_property('imported_material_slot_name'))
    if name not in mats:raise RuntimeError('Unexpected rig material: ' + name)
    slot.set_editor_property('material_interface',mats[name])
skin.set_editor_property('materials',slots);ASSETS.save_loaded_asset(skin)
skeleton = skin.get_editor_property('skeleton')
clips=[]
for clip in record['clips']:
    opts=unreal.FbxImportUI()
    for key,value in [('automated_import_should_detect_type',False),('import_mesh',False),('import_animations',True),
                      ('mesh_type_to_import',unreal.FBXImportType.FBXIT_ANIMATION),('skeleton',skeleton)]:opts.set_editor_property(key,value)
    animation=import_typed(folder/clip['fbx'],dest,'A_'+clip['name'],opts,unreal.AnimSequence)
    clips.append({'name':clip['name'],'path':animation.get_path_name(),'length_s':animation.get_editor_property('sequence_length')})
    ASSETS.save_loaded_asset(animation)
result={'skin':skin.get_path_name(),'skeleton':skeleton.get_path_name(),'clips':clips}
(ROOT/'artifacts/3d-world/ue-mannequin-import.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
unreal.log('MR_MANNEQUIN_ANIMATIONS_IMPORTED '+str(len(clips)))
