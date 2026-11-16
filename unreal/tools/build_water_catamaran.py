"""Import the user's prepared catamaran without publishing its binary source.

Run by run_disaster_art.py --kind watercraft under the shared Unreal lock.
The FBX is a render shell. Separate twin hull contacts, water displacement,
jets and cargo belong to the native agent; convex-decomposing the whole deck
would close the gap between the hulls and create an incorrect waterline.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

import unreal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_rescue_assets import configure_lods, import_one

FOLDER = '/Game/RescueAssets/WatercraftV1'
LIB = unreal.MaterialEditingLibrary
ASSETS = unreal.EditorAssetLibrary


def checked_file(root, row):
    path = (root / row['path']).resolve(strict=True)
    if not path.is_relative_to(root) or path.stat().st_size != row['bytes']:
        raise ValueError('Watercraft input is outside its preparation directory or changed size')
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != row['sha256']:
            raise ValueError('Watercraft input SHA-256 differs: ' + path.name)
    return path


def main():
    inputs = Path(os.environ['MR_WATERCRAFT_ART_INPUTS']).resolve(strict=True)
    report = Path(os.environ['MR_WATERCRAFT_ART_REPORT']).resolve()
    preparation = json.loads(inputs.read_bytes())
    if preparation.get('format') != 'metarescue.water-catamaran.r1' or preparation['triangles'] > 150000:
        raise ValueError('Unsupported or unbounded watercraft preparation')
    root = inputs.parent
    mesh_file = checked_file(root, preparation['mesh'])
    files = {kind: checked_file(root, row) for kind, row in preparation['textures'].items()}
    textures = {}
    for kind, path in files.items():
        texture = import_one(path, FOLDER, 'T_RescueWaterCatamaran_' + kind)
        texture.set_editor_property('srgb', kind == 'BaseColor')
        if kind == 'Normal':
            texture.set_editor_property('compression_settings', unreal.TextureCompressionSettings.TC_NORMALMAP)
            # Blender stores OpenGL normals, the project uses DirectX normals.
            texture.set_editor_property('flip_green_channel', True)
        elif kind == 'ORM':
            texture.set_editor_property('compression_settings', unreal.TextureCompressionSettings.TC_MASKS)
        texture.set_editor_property('max_texture_size', 2048)
        if not ASSETS.save_loaded_asset(texture):
            raise RuntimeError('Could not save texture ' + kind)
        textures[kind] = texture
    name = 'M_RescueWaterCatamaran'
    material = unreal.load_asset(FOLDER + '/' + name) or unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, FOLDER, unreal.Material, unreal.MaterialFactoryNew())
    if material is None:
        raise RuntimeError('Could not create the watercraft PBR material')
    LIB.delete_all_material_expressions(material)
    for i, (kind, texture) in enumerate(textures.items()):
        sample = LIB.create_material_expression(material, unreal.MaterialExpressionTextureSample, -500, i * 230)
        sample.set_editor_property('texture', texture)
        sample.set_editor_property('sampler_type', {
            'BaseColor': unreal.MaterialSamplerType.SAMPLERTYPE_COLOR,
            'Normal': unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL,
            'ORM': unreal.MaterialSamplerType.SAMPLERTYPE_MASKS}[kind])
        routes = {
            'BaseColor': [('RGB', unreal.MaterialProperty.MP_BASE_COLOR)],
            'Normal': [('RGB', unreal.MaterialProperty.MP_NORMAL)],
            'ORM': [('R', unreal.MaterialProperty.MP_AMBIENT_OCCLUSION),
                    ('G', unreal.MaterialProperty.MP_ROUGHNESS),
                    ('B', unreal.MaterialProperty.MP_METALLIC)]}[kind]
        for channel, prop in routes:
            if not LIB.connect_material_property(sample, channel, prop):
                raise RuntimeError('Watercraft PBR connection failed: ' + kind + '.' + channel)
    LIB.recompile_material(material)
    if not ASSETS.save_loaded_asset(material):
        raise RuntimeError('Could not save watercraft material')
    options = unreal.FbxImportUI()
    for key, value in {'import_mesh': True, 'import_as_skeletal': False, 'import_materials': False,
                       'import_textures': False, 'automated_import_should_detect_type': False,
                       'mesh_type_to_import': unreal.FBXImportType.FBXIT_STATIC_MESH}.items():
        options.set_editor_property(key, value)
    data = options.get_editor_property('static_mesh_import_data')
    for key, value in {'combine_meshes': True, 'auto_generate_collision': False, 'build_nanite': False,
                       'convert_scene': True, 'convert_scene_unit': True, 'force_front_x_axis': True}.items():
        data.set_editor_property(key, value)
    mesh = import_one(mesh_file, FOLDER, 'SM_RescueWaterCatamaran', options)
    mesh.set_material(0, material)
    lods = configure_lods(mesh)
    unreal.MRAssetTools.finish_asset_compilation()
    bounds = mesh.get_bounds()
    dimensions = [bounds.box_extent.x * 2, bounds.box_extent.y * 2, bounds.box_extent.z * 2]
    expected = [v * 100 for v in preparation['dimensions_m']]
    if any(abs(a - b) > max(2, b * .015) for a, b in zip(dimensions, expected)):
        raise RuntimeError('Watercraft scale/forward axis differs: ' + repr((dimensions, expected)))
    if abs(bounds.origin.z - bounds.box_extent.z) > 1:
        raise RuntimeError('Watercraft origin no longer lies on the keel plane')
    ASSETS.save_loaded_asset(mesh)
    result = {'format': 'metarescue.watercraft-import.v1', 'source_sha256': preparation['source_sha256'],
              'mesh': mesh.get_path_name(), 'material': material.get_path_name(), 'dimensions_cm': dimensions,
              'origin_cm': [bounds.origin.x, bounds.origin.y, bounds.origin.z], 'lods': lods,
              'textures': {k: v.get_path_name() for k, v in textures.items()},
              'physics_status': 'visual shell imported; loaded twin-hull acceptance still required',
              'license': preparation['license']}
    report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    unreal.log('MR_WATERCRAFT_ART_IMPORTED: ' + mesh.get_path_name())


if __name__ == '__main__':
    main()
