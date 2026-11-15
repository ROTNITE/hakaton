"""Import the editable Blender-authored companion models into Unreal."""
from pathlib import Path
import json
import sys

import unreal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_rescue_assets import import_one, ASSETS, ROOT, TOOLS, LIB


prepared = ROOT / 'blender' / 'authored' / 'v1'
manifest = json.loads((prepared / 'manifest.json').read_text(encoding='utf-8'))
if not ASSETS.does_asset_exist('/Game/Materials/MI_Brick'):
    brick = TOOLS.create_asset('MI_Brick', '/Game/Materials', unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
    LIB.set_material_instance_parent(brick, unreal.load_asset('/Game/Materials/M_RescueSurface'))
    LIB.set_material_instance_vector_parameter_value(brick, 'Tint', unreal.LinearColor(.27,.13,.08,1))
    for parameter, value in [('Roughness',.92),('Metallic',0),('Variation',.3),('GrainSize',8)]:
        LIB.set_material_instance_scalar_parameter_value(brick, parameter, value)
    ASSETS.save_loaded_asset(brick)
report = []
for record in manifest['assets']:
    name = record['id']
    folder = '/Game/RescueAssets/Authored/' + name
    ASSETS.make_directory(folder)
    options = unreal.FbxImportUI()
    for key, value in [('import_mesh', True), ('import_as_skeletal', False), ('import_materials', False),
                       ('import_textures', False), ('automated_import_should_detect_type', False),
                       ('mesh_type_to_import', unreal.FBXImportType.FBXIT_STATIC_MESH)]:
        options.set_editor_property(key, value)
    data = options.get_editor_property('static_mesh_import_data')
    for key, value in [('combine_meshes', True), ('auto_generate_collision', name not in {'Medical', 'Doorway', 'Fence', 'Dock', 'UtilityTunnel'}),
                       ('build_nanite', False), ('convert_scene', True), ('convert_scene_unit', True),
                       ('force_front_x_axis', True)]:
        data.set_editor_property(key, value)
    mesh = import_one(prepared / record['fbx'], folder, 'SM_' + name, options)
    for i, slot in enumerate(mesh.get_editor_property('static_materials')):
        slot_name = str(slot.get_editor_property('imported_material_slot_name'))
        palette = slot_name.removeprefix('M_A_')
        if palette not in {item['palette'] for item in record['materials']}:
            raise RuntimeError('Unexpected imported material slot: ' + name + ' / ' + slot_name)
        material = unreal.load_asset('/Game/Materials/MI_' + palette)
        if material is None:
            raise RuntimeError('Missing shared material: ' + palette)
        mesh.set_material(i, material)
    if name in {'Medical', 'Doorway', 'Fence', 'Dock', 'UtilityTunnel'}:
        body = mesh.get_editor_property('body_setup')
        body.set_editor_property('collision_trace_flag', unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
    ASSETS.save_loaded_asset(mesh)
    bounds = mesh.get_bounds()
    dimensions = [bounds.box_extent.x * 2, bounds.box_extent.y * 2, bounds.box_extent.z * 2]
    expected = sorted(x * 100 for x in record['dimensions_m'])
    assert all(abs(x - y) < max(3, y * .02) for x, y in zip(sorted(dimensions), expected)), name
    report.append({'id': name, 'mesh': mesh.get_path_name(), 'dimensions_cm': dimensions,
                   'triangles': record['triangles']})
(ROOT / 'artifacts/3d-world/ue-authored-import.json').write_text(json.dumps({'assets': report}, indent=2), encoding='utf-8')
ASSETS.save_directory('/Game/RescueAssets/Authored', only_if_is_dirty=False, recursive=True)
unreal.log('MR_AUTHORED_ASSET_IMPORT_COMPLETE: ' + str(len(report)))
