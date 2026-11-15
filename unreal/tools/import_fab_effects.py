"""Import only SHA-checked Fab derivatives needed by the optional event art."""
import hashlib
import json
from pathlib import Path

import unreal

from import_rescue_assets import import_one


def checked_file(directory, item):
    path = (directory / item['path']).resolve(strict=True)
    if not path.is_relative_to(directory) or path.stat().st_size != item['bytes']:
        raise RuntimeError('Fab input is outside the preparation directory or has a different size')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != item['sha256']:
        raise RuntimeError('Fab input SHA-256 differs: ' + path.name)
    return path


def import_effect_sources(manifest, folder):
    data = json.loads(manifest.read_bytes())
    if data.get('format') != 'metarescue.fab-effects.v1':
        raise RuntimeError('Unsupported Fab effect preparation manifest')
    directory = manifest.parent
    source_manifest = checked_file(directory, data['source_manifest'])
    debris = data['debris']
    maps = {name: checked_file(directory, row) for name, row in {
        'T_EventFractureAsphalt': data['asphalt_color'],
        'T_EventBurntDebrisBase': debris['base_color'],
        'T_EventBurntDebrisRoughness': debris['roughness'],
    }.items()}
    mesh_file = checked_file(directory, debris['mesh'])
    assets = unreal.EditorAssetLibrary
    edit = unreal.MaterialEditingLibrary
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    assets.make_directory(folder)
    textures = {}
    for name, path in maps.items():
        texture = import_one(path, folder, name)
        if not isinstance(texture, unreal.Texture2D):
            raise RuntimeError('Expected a Fab Texture2D: ' + name)
        is_roughness = name.endswith('Roughness')
        texture.set_editor_property('srgb', not is_roughness)
        if is_roughness:
            texture.set_editor_property('compression_settings', unreal.TextureCompressionSettings.TC_MASKS)
        if not assets.save_loaded_asset(texture):
            raise RuntimeError('Could not save Fab texture: ' + name)
        textures[name] = texture

    material_name = 'M_EventBurntDebris'
    material_path = folder + '/' + material_name
    material = unreal.load_asset(material_path) or tools.create_asset(
        material_name, folder, unreal.Material, unreal.MaterialFactoryNew())
    if material is None:
        raise RuntimeError('Could not create Fab debris material')
    edit.delete_all_material_expressions(material)
    for row, (name, prop, output, sampler) in enumerate((
        ('T_EventBurntDebrisBase', unreal.MaterialProperty.MP_BASE_COLOR, 'RGB', unreal.MaterialSamplerType.SAMPLERTYPE_COLOR),
        ('T_EventBurntDebrisRoughness', unreal.MaterialProperty.MP_ROUGHNESS, 'R', unreal.MaterialSamplerType.SAMPLERTYPE_MASKS),
    )):
        node = edit.create_material_expression(material, unreal.MaterialExpressionTextureSample, -420, row * 230)
        node.set_editor_property('texture', textures[name])
        node.set_editor_property('sampler_type', sampler)
        if not edit.connect_material_property(node, output, prop):
            raise RuntimeError('Could not bind Fab debris texture: ' + name)
    edit.recompile_material(material)
    if not assets.save_loaded_asset(material):
        raise RuntimeError('Could not save Fab debris material')

    options = unreal.FbxImportUI()
    for key, value in [('import_mesh', True), ('import_as_skeletal', False), ('import_materials', False),
                       ('import_textures', False), ('automated_import_should_detect_type', False),
                       ('mesh_type_to_import', unreal.FBXImportType.FBXIT_STATIC_MESH)]:
        options.set_editor_property(key, value)
    import_data = options.get_editor_property('static_mesh_import_data')
    for key, value in [('combine_meshes', True), ('auto_generate_collision', False), ('build_nanite', False),
                       ('convert_scene', True), ('convert_scene_unit', True), ('force_front_x_axis', True)]:
        import_data.set_editor_property(key, value)
    mesh = import_one(mesh_file, folder, 'SM_EventBurntDebris', options)
    if not isinstance(mesh, unreal.StaticMesh) or len(mesh.get_editor_property('static_materials')) != 1:
        raise RuntimeError('Expected a single-slot static mesh from the prepared Fab fragment')
    mesh.set_material(0, material)
    if not assets.save_loaded_asset(mesh):
        raise RuntimeError('Could not save the Fab debris mesh')
    unreal.MRAssetTools.finish_asset_compilation()
    native = json.loads(unreal.MRAssetTools.describe_mesh_geometry(mesh))
    measured = sorted(high - low for low, high in zip(native['source_min_cm'], native['source_max_cm']))
    expected = sorted((high - low) * 100 for low, high in zip(
        debris['geometry']['bounds_m']['min'], debris['geometry']['bounds_m']['max']))
    if not native['available'] or native['nanite_enabled'] or native['triangles'] != debris['geometry']['mesh_triangles'] or \
            abs(native['source_min_cm'][2]) > .03 or any(abs(a-b) > .1 for a,b in zip(measured,expected)):
        raise RuntimeError('Imported Fab debris geometry differs: ' + json.dumps(native))
    return textures['T_EventFractureAsphalt'], {
        'source_manifest': data['source_manifest']['sha256'], 'source_manifest_file': source_manifest.name,
        'textures': {name: asset.get_path_name() for name, asset in textures.items()},
        'debris_material': material.get_path_name(), 'debris_mesh': mesh.get_path_name(), 'geometry': native}
