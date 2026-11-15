"""Import prepared user meshes and source PBR maps using the installed UE editor."""
import json
from pathlib import Path

import unreal


PROJECT = Path(unreal.Paths.project_dir()).resolve()
ROOT = PROJECT.parents[1]
PREPARED = ROOT / 'blender' / 'prepared' / 'v1'
TOOLS = unreal.AssetToolsHelpers.get_asset_tools()
LIB = unreal.MaterialEditingLibrary
ASSETS = unreal.EditorAssetLibrary


def import_one(filename, folder, name, options=None):
    task = unreal.AssetImportTask()
    task.set_editor_property('filename', str(filename))
    task.set_editor_property('destination_path', folder)
    task.set_editor_property('destination_name', name)
    task.set_editor_property('automated', True)
    task.set_editor_property('replace_existing', True)
    task.set_editor_property('save', True)
    if options is not None:
        task.set_editor_property('options', options)
    TOOLS.import_asset_tasks([task])
    paths = task.get_editor_property('imported_object_paths')
    if not paths:
        raise RuntimeError('Import produced no asset: ' + str(filename))
    result = unreal.load_asset(paths[0])
    if result is None:
        raise RuntimeError('Cannot load imported asset: ' + str(paths[0]))
    return result


def import_asset(record):
    name = record['id']
    folder = '/Game/RescueAssets/User/' + name
    ASSETS.make_directory(folder)
    textures = {}
    for kind, relative in record['textures'].items():
        texture = import_one(PREPARED / relative, folder, 'T_' + name + '_' + kind)
        texture.set_editor_property('srgb', kind == 'BaseColor')
        if kind == 'Normal':
            texture.set_editor_property('compression_settings', unreal.TextureCompressionSettings.TC_NORMALMAP)
            texture.set_editor_property('flip_green_channel', True)
        elif kind == 'ORM':
            texture.set_editor_property('compression_settings', unreal.TextureCompressionSettings.TC_MASKS)
        ASSETS.save_loaded_asset(texture)
        textures[kind] = texture
    material_name = 'M_' + name
    material = unreal.load_asset(folder + '/' + material_name)
    if material is None:
        material = TOOLS.create_asset(material_name, folder, unreal.Material, unreal.MaterialFactoryNew())
    LIB.delete_all_material_expressions(material)
    for index, (kind, texture) in enumerate(textures.items()):
        node = LIB.create_material_expression(material, unreal.MaterialExpressionTextureSample, -500, index * 230)
        node.set_editor_property('texture', texture)
        if kind == 'BaseColor':
            node.set_editor_property('sampler_type', unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
            LIB.connect_material_property(node, 'RGB', unreal.MaterialProperty.MP_BASE_COLOR)
        elif kind == 'Normal':
            node.set_editor_property('sampler_type', unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
            LIB.connect_material_property(node, 'RGB', unreal.MaterialProperty.MP_NORMAL)
        elif kind == 'ORM':
            node.set_editor_property('sampler_type', unreal.MaterialSamplerType.SAMPLERTYPE_MASKS)
            LIB.connect_material_property(node, 'G', unreal.MaterialProperty.MP_ROUGHNESS)
            LIB.connect_material_property(node, 'B', unreal.MaterialProperty.MP_METALLIC)
            LIB.connect_material_property(node, 'R', unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)
    LIB.recompile_material(material)
    ASSETS.save_loaded_asset(material)
    options = unreal.FbxImportUI()
    options.set_editor_property('import_mesh', True)
    options.set_editor_property('import_as_skeletal', False)
    options.set_editor_property('import_materials', False)
    options.set_editor_property('import_textures', False)
    options.set_editor_property('automated_import_should_detect_type', False)
    options.set_editor_property('mesh_type_to_import', unreal.FBXImportType.FBXIT_STATIC_MESH)
    data = options.get_editor_property('static_mesh_import_data')
    data.set_editor_property('combine_meshes', True)
    data.set_editor_property('auto_generate_collision', False)
    data.set_editor_property('build_nanite', False)
    data.set_editor_property('convert_scene', True)
    data.set_editor_property('convert_scene_unit', True)
    data.set_editor_property('force_front_x_axis', True)
    mesh = import_one(PREPARED / record['fbx'], folder, 'SM_' + name, options)
    mesh.set_material(0, material)
    if name in {'Building', 'WindowWall'}:
        body = mesh.get_editor_property('body_setup')
        body.set_editor_property('collision_trace_flag', unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
    ASSETS.save_loaded_asset(mesh)
    lod_report = configure_lods(mesh)
    bounds = mesh.get_bounds()
    dimensions = [bounds.box_extent.x * 2, bounds.box_extent.y * 2, bounds.box_extent.z * 2]
    expected = sorted(v * 100 for v in record['dimensions_m'])
    assert all(abs(a - b) < max(3, b * .02) for a, b in zip(sorted(dimensions), expected)), (name, dimensions, expected)
    return {'id': name, 'mesh': mesh.get_path_name(), 'material': material.get_path_name(),
            'dimensions_cm': dimensions, 'textures': {k: t.get_path_name() for k, t in textures.items()},
            'source': record['source'], 'source_sha256': record['source_sha256'], 'lods': lod_report}


def configure_lods(mesh):
    subsystem = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    if subsystem is None:
        # Commandlets do not register every editor subsystem; these mesh operations are stateless.
        subsystem = unreal.new_object(unreal.StaticMeshEditorSubsystem)
    options = unreal.StaticMeshReductionOptions()
    options.set_editor_property('auto_compute_lod_screen_size', False)
    settings = []
    for ratio, size in [(1,1),(.4,.28),(.1,.08),(.035,.025)]:
        item = unreal.StaticMeshReductionSettings()
        item.set_editor_property('percent_triangles', ratio)
        item.set_editor_property('screen_size', size)
        settings.append(item)
    options.set_editor_property('reduction_settings', settings)
    if subsystem.set_lods(mesh, options) < 0:
        raise RuntimeError('LOD reduction failed: ' + mesh.get_path_name())
    assert subsystem.get_lod_count(mesh) == 4
    ASSETS.save_loaded_asset(mesh)
    return {'vertices': [subsystem.get_number_verts(mesh, i) for i in range(4)],
            'triangles': [mesh.get_num_triangles(i) for i in range(4)],
            'screen_sizes': list(subsystem.get_lod_screen_sizes(mesh))}


if __name__ == '__main__':
    manifest = json.loads((PREPARED / 'manifest.json').read_text(encoding='utf-8'))
    records = [import_asset(record) for record in manifest['assets']]
    out = ROOT / 'artifacts' / '3d-world' / 'ue-asset-import.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'assets': records}, indent=2), encoding='utf-8')
    ASSETS.save_directory('/Game/RescueAssets/User', only_if_is_dirty=False, recursive=True)
    unreal.log('MR_USER_ASSET_IMPORT_COMPLETE: ' + str(len(records)))
