"""Import SHA-checked CC0 textures and generate the city-2.3 effect revision.

Run only with the common Unreal lock. MR_DISASTER_ART_INPUTS points to the
prepare_disaster_effects.py manifest; MR_DISASTER_ART_REPORT is a new JSON file.
The old, cooked effect revisions and downloaded originals are never edited.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

import unreal
# A Python commandlet does not add the script directory to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_rescue_assets import import_one

FOLDER = '/Game/EffectsV3/Revision5'
ASSETS = unreal.EditorAssetLibrary
EDIT = unreal.MaterialEditingLibrary
TOOLS = unreal.AssetToolsHelpers.get_asset_tools()


def checked_file(root, row):
    path = (root / row['path']).resolve(strict=True)
    if not path.is_relative_to(root) or path.stat().st_size != row['bytes']:
        raise ValueError('Disaster art input is outside its directory or has changed size')
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != row['sha256']:
            raise ValueError('Disaster art input SHA-256 differs: ' + path.name)
    return path


def node(material, kind, x=0, y=0, **properties):
    result = EDIT.create_material_expression(material, kind, x, y)
    if result is None:
        raise RuntimeError('Material expression could not be created: ' + str(kind))
    for name, value in properties.items():
        result.set_editor_property(name, value)
    return result


def connect(source, output, target, name):
    if not EDIT.connect_material_expressions(source, output, target, name):
        raise RuntimeError('Material input connection failed: ' + name)


def property_input(source, output, material, prop):
    if not EDIT.connect_material_property(source, output, prop):
        raise RuntimeError('Material property connection failed: ' + str(prop))


def custom(material, code, kind, inputs, x=0, y=0):
    result = node(material, unreal.MaterialExpressionCustom, x, y, code=code, output_type=kind)
    pins = []
    for name, _, _ in inputs:
        pin = unreal.CustomInput()
        pin.set_editor_property('input_name', name)
        pins.append(pin)
    result.set_editor_property('inputs', pins)
    for name, source, output in inputs:
        connect(source, output, result, name)
    return result


def scalar(material, name, default, y=0):
    return node(material, unreal.MaterialExpressionScalarParameter, -1000, y,
                parameter_name=name, default_value=default)


def vector(material, name, default, y=0):
    return node(material, unreal.MaterialExpressionVectorParameter, -1000, y,
                parameter_name=name, default_value=unreal.LinearColor(*default, 1))


def texture_object(material, texture, name, y=0):
    return node(material, unreal.MaterialExpressionTextureObjectParameter, -1100, y,
                parameter_name=name, texture=texture)


def material(name, translucent=False, luminous=False, particle=False):
    value = unreal.load_asset(FOLDER + '/' + name) or TOOLS.create_asset(
        name, FOLDER, unreal.Material, unreal.MaterialFactoryNew())
    if value is None:
        raise RuntimeError('Could not create material: ' + name)
    EDIT.delete_all_material_expressions(value)
    value.set_editor_property('blend_mode', unreal.BlendMode.BLEND_TRANSLUCENT if translucent else unreal.BlendMode.BLEND_OPAQUE)
    value.set_editor_property('shading_model', unreal.MaterialShadingModel.MSM_UNLIT if luminous else unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
    value.set_editor_property('two_sided', translucent)
    value.set_editor_property('used_with_niagara_sprites', particle)
    if translucent and not luminous:
        value.set_editor_property('translucency_lighting_mode', unreal.TranslucencyLightingMode.TLM_VOLUMETRIC_NON_DIRECTIONAL)
    return value


def save(material):
    EDIT.recompile_material(material)
    if not ASSETS.save_loaded_asset(material):
        raise RuntimeError('Could not save disaster material: ' + material.get_name())


def build_fire(textures):
    value = material('M_BuildingFire', translucent=True, luminous=True, particle=True)
    front = texture_object(value, textures['FireFront'], 'FireFront', 0)
    overhead = texture_object(value, textures['FireOverhead'], 'FireOverhead', 200)
    uv = node(value, unreal.MaterialExpressionTextureCoordinate, -1100, 380)
    life = node(value, unreal.MaterialExpressionParticleRelativeTime, -1100, 500)
    view = node(value, unreal.MaterialExpressionCameraVectorWS, -1100, 620)
    # Each new particle plays a complete, baked flame episode. Model-pause
    # support comes from Niagara's simulation delta, never a wall-time node.
    color = custom(value, '''
float Frame = min(63, floor(saturate(Life) * 64));
float2 Cell = float2(fmod(Frame, 8), floor(Frame / 8));
float2 AtlasUV = (Cell + lerp(.008, .992, saturate(UV))) / 8;
float4 Front = Texture2DSample(FrontTex, FrontTexSampler, AtlasUV);
float4 Above = Texture2DSample(AboveTex, AboveTexSampler, AtlasUV);
return lerp(Front, Above, smoothstep(.45, .8, abs(View.z)));
''', unreal.CustomMaterialOutputType.CMOT_FLOAT4,
        [('FrontTex', front, ''), ('AboveTex', overhead, ''), ('UV', uv, ''),
         ('Life', life, ''), ('View', view, '')], -650, 0)
    rgba = node(value, unreal.MaterialExpressionComponentMask, -350, 0, r=True, g=True, b=True, a=False)
    connect(color, '', rgba, '')
    radiance = custom(value, 'return Color * 2400 * Fade;', unreal.CustomMaterialOutputType.CMOT_FLOAT3,
        [('Color', rgba, ''), ('Fade', scalar(value, 'Fade', 1, 750), '')], -50, 0)
    property_input(radiance, '', value, unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    alpha = node(value, unreal.MaterialExpressionComponentMask, -350, 180, r=False, g=False, b=False, a=True)
    connect(color, '', alpha, '')
    faded = custom(value, 'return saturate(Alpha * Fade);', unreal.CustomMaterialOutputType.CMOT_FLOAT1,
        [('Alpha', alpha, ''), ('Fade', scalar(value, 'Fade', 1, 850), '')], -50, 180)
    property_input(faded, '', value, unreal.MaterialProperty.MP_OPACITY)
    save(value)
    return value


def build_billow(textures):
    value = material('M_HeavySmoke', translucent=True, particle=True)
    tex = node(value, unreal.MaterialExpressionTextureSample, -800, 0,
               texture=textures['SmokeBillow'])
    uv = node(value, unreal.MaterialExpressionTextureCoordinate, -1100, 0)
    connect(uv, '', tex, 'UVs')
    particle = node(value, unreal.MaterialExpressionParticleColor, -800, 260)
    fade = scalar(value, 'Fade', 1, 450)
    opacity = custom(value, 'return saturate(Cloud * Particle * Fade * .42);',
        unreal.CustomMaterialOutputType.CMOT_FLOAT1,
        [('Cloud', tex, 'A'), ('Particle', particle, 'A'), ('Fade', fade, '')], -350, 150)
    property_input(opacity, '', value, unreal.MaterialProperty.MP_OPACITY)
    shade = vector(value, 'SmokeAlbedo', (.045, .048, .05), 620)
    property_input(shade, 'RGB', value, unreal.MaterialProperty.MP_BASE_COLOR)
    save(value)
    return value


def build_volume():
    value = material('M_PhysicalSmoke', translucent=True)
    inputs = [
        ('Source', vector(value, 'SmokeSource', (0, 0, 0)), 'RGB'),
        ('Wind', vector(value, 'SmokeWind', (0, 0, 0), 140), 'RGB'),
        ('Shape', vector(value, 'SmokeShape', (3000, 1800, .12), 280), 'RGB'),
        ('Rise', scalar(value, 'SmokeRise', 150, 420), ''),
        ('Extinction', scalar(value, 'SmokeExtinction', .0035, 560), ''),
        ('Strength', scalar(value, 'SmokeStrength', 1, 700), ''),
        ('Surface', node(value, unreal.MaterialExpressionWorldPosition, -1100, 840), ''),
        ('Camera', node(value, unreal.MaterialExpressionCameraPositionWS, -1100, 980), ''),
        ('SceneZ', node(value, unreal.MaterialExpressionSceneDepth, -1100, 1120), ''),
        ('PixelZ', node(value, unreal.MaterialExpressionPixelDepth, -1100, 1260), ''),
        ('Side', node(value, unreal.MaterialExpressionTwoSidedSign, -1100, 1400), ''),
    ]
    code = (Path(__file__).resolve().parent / 'shaders/disaster_smoke.hlsl').read_text(encoding='utf-8')
    opacity = custom(value, code, unreal.CustomMaterialOutputType.CMOT_FLOAT1, inputs, -350, 0)
    property_input(opacity, '', value, unreal.MaterialProperty.MP_OPACITY)
    property_input(vector(value, 'SmokeAlbedo', (.045, .048, .05), 1550), 'RGB', value,
                   unreal.MaterialProperty.MP_BASE_COLOR)
    save(value)
    return value


def build_soot(textures):
    value = material('M_FireSoot', translucent=True)
    value.set_editor_property('material_domain', unreal.MaterialDomain.MD_DEFERRED_DECAL)
    value.set_editor_property('used_with_nanite', False)
    value.set_editor_property('used_with_instanced_static_meshes', False)
    cloud = node(value, unreal.MaterialExpressionTextureSample, -700, 200,
                 texture=textures['SmokeBillow'])
    opacity = custom(value, 'return saturate(Cloud * Burn * .82);', unreal.CustomMaterialOutputType.CMOT_FLOAT1,
        [('Cloud', cloud, 'A'), ('Burn', scalar(value, 'BurnFraction', 1, 560), '')], -300, 200)
    property_input(opacity, '', value, unreal.MaterialProperty.MP_OPACITY)
    property_input(vector(value, 'SootColor', (.008, .006, .004)), 'RGB', value,
                   unreal.MaterialProperty.MP_BASE_COLOR)
    property_input(scalar(value, 'Roughness', .96, 400), '', value, unreal.MaterialProperty.MP_ROUGHNESS)
    save(value)
    return value


def build_mud(textures):
    value = material('M_EventMud')
    position = node(value, unreal.MaterialExpressionWorldPosition, -1100, 0)
    uv = custom(value, 'return Position.xy / 350;', unreal.CustomMaterialOutputType.CMOT_FLOAT2,
                [('Position', position, '')], -850, 0)
    for index, (name, prop, output) in enumerate((
        ('MudColor', unreal.MaterialProperty.MP_BASE_COLOR, 'RGB'),
        ('MudNormal', unreal.MaterialProperty.MP_NORMAL, 'RGB'),
        ('MudRoughness', unreal.MaterialProperty.MP_ROUGHNESS, 'R'),
    )):
        sampler = unreal.MaterialSamplerType.SAMPLERTYPE_COLOR if name == 'MudColor' else \
            unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL if name == 'MudNormal' else unreal.MaterialSamplerType.SAMPLERTYPE_MASKS
        sample = node(value, unreal.MaterialExpressionTextureSample, -550, index * 230,
                      texture=textures[name], sampler_type=sampler)
        connect(uv, '', sample, 'UVs')
        property_input(sample, output, value, prop)
    save(value)
    return value


def main():
    manifest = Path(os.environ['MR_DISASTER_ART_INPUTS']).resolve(strict=True)
    report = Path(os.environ['MR_DISASTER_ART_REPORT']).resolve()
    if report.exists():
        raise ValueError('Import report already exists; preserve previous evidence')
    data = json.loads(manifest.read_bytes())
    if data.get('format') != 'metarescue.disaster-effects.sources.v1' or data.get('revision') != 5 or \
            any(row.get('license') != 'CC0-1.0' for row in data['sources']):
        raise ValueError('Unsupported disaster effect preparation or license')
    ASSETS.make_directory(FOLDER)
    textures = {}
    for name, row in data['textures'].items():
        texture = import_one(checked_file(manifest.parent, row), FOLDER + '/Textures', 'T_' + name)
        if not isinstance(texture, unreal.Texture2D):
            raise TypeError('Disaster art input did not import as a Texture2D')
        texture.set_editor_property('srgb', row['usage'] in ('color', 'alpha'))
        texture.set_editor_property('address_x', unreal.TextureAddress.TA_CLAMP if name.startswith('Fire') else unreal.TextureAddress.TA_WRAP)
        texture.set_editor_property('address_y', unreal.TextureAddress.TA_CLAMP if name.startswith('Fire') else unreal.TextureAddress.TA_WRAP)
        texture.set_editor_property('compression_settings', unreal.TextureCompressionSettings.TC_NORMALMAP if row['usage'] == 'normal' else \
            unreal.TextureCompressionSettings.TC_MASKS if row['usage'] == 'linear' else unreal.TextureCompressionSettings.TC_DEFAULT)
        if not ASSETS.save_loaded_asset(texture):
            raise RuntimeError('Could not save texture: ' + name)
        textures[name] = texture
    fire = build_fire(textures)
    smoke = build_billow(textures)
    materials = [fire, smoke, build_volume(), build_mud(textures), build_soot(textures)]
    systems = {}
    for name, mat, spec in (
        ('BuildingFire', fire, (7, 1.2, 1.8, 180, 285, 5, 20, (0, 0, 10), 16)),
        ('HeavySmoke', smoke, (6, 5, 8, 320, 650, 100, 200, (0, 0, 8), 95)),
    ):
        rate, low, high, size_low, size_high, speed_low, speed_high, gravity, spread = spec
        system = unreal.MRAssetTools.create_effect('/Niagara/DefaultAssets/Templates/Emitters/Fountain.Fountain',
            FOLDER + '/NS_' + name, mat)
        if system is None:
            raise RuntimeError('Could not create disaster Niagara system: ' + name)
        unreal.MRAssetTools.configure_effect(system, rate, low, high, size_low, size_high,
            speed_low, speed_high, unreal.Vector(*gravity), spread)
        if not ASSETS.save_loaded_asset(system):
            raise RuntimeError('Could not save disaster Niagara system: ' + name)
        systems[name] = {'path': system.get_path_name(), 'readback': unreal.MRAssetTools.describe_effect(system)}
    unreal.MRAssetTools.finish_asset_compilation()
    result = {'format': 'metarescue.disaster-effects.import.v1', 'revision': 5,
              'source_manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
              'textures': {name: asset.get_path_name() for name, asset in textures.items()},
              'materials': [mat.get_path_name() for mat in materials], 'systems': systems}
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    unreal.log('MR_DISASTER_ART_IMPORTED ' + str(report))


if __name__ == '__main__':
    main()
