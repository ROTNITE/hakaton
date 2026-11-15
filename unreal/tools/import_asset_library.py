"""Import the reviewed v2 library with explicit PBR, glass and module manifests."""
from pathlib import Path
import json
import re
import sys

import unreal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_rescue_assets import import_one, configure_lods, ASSETS, LIB, ROOT, TOOLS

BASE = ROOT / 'blender/prepared/v2'
DEST = '/Game/RescueAssets/Library'
V3 = '-MRLibraryVersion=3' in unreal.SystemLibrary.get_command_line()
if V3:
    BASE = ROOT / 'blender/prepared/v3'
    DEST = '/Game/RescueAssets/LibraryV3'


def safe(name):
    return re.sub('[^A-Za-z0-9_]', '_', name)


def scalar(mat, value, prop, y=0):
    node = LIB.create_material_expression(mat, unreal.MaterialExpressionConstant, -250, y)
    node.set_editor_property('r', value)
    LIB.connect_material_property(node, '', prop)


def color(mat, value, prop, y=0):
    node = LIB.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -250, y)
    node.set_editor_property('constant', unreal.LinearColor(*value[:3], 1))
    LIB.connect_material_property(node, '', prop)


def material(record, asset, folder, source):
    name = safe(record['name'])
    target = folder + '/Materials'
    mat = unreal.load_asset(target + '/' + name)
    if mat is None:
        mat = TOOLS.create_asset(name, target, unreal.Material, unreal.MaterialFactoryNew())
    LIB.delete_all_material_expressions(mat)
    values = record['inputs']
    glass = record['glass']
    wire = 'wire' in name.lower()
    mat.set_editor_property('two_sided', glass or wire or asset['id'] in {'UrbanKit', 'FenceKit'})
    if glass:
        mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_TRANSLUCENT)
        mat.set_editor_property('shading_model', unreal.MaterialShadingModel.MSM_THIN_TRANSLUCENT)
        mat.set_editor_property('translucency_lighting_mode', unreal.TranslucencyLightingMode.TLM_SURFACE_PER_PIXEL_LIGHTING)
        color(mat, [.05, .065, .06], unreal.MaterialProperty.MP_BASE_COLOR)
        scalar(mat, values.get('Roughness',.08), unreal.MaterialProperty.MP_ROUGHNESS, 120)
        # ThinTranslucentCommon.ush multiplies transmission by (1-opacity).
        # Opacity describes the dusty surface layer, not the pane coverage.
        scalar(mat, .07 if 'dirty' in name or 'cracked' in name or 'broken' in name else .018,
               unreal.MaterialProperty.MP_OPACITY, 240)
        scalar(mat, .5, unreal.MaterialProperty.MP_SPECULAR, 360)
        output=LIB.create_material_expression(mat,unreal.MaterialExpressionThinTranslucentMaterialOutput,100,-250)
        transmission=LIB.create_material_expression(mat,unreal.MaterialExpressionConstant3Vector,-250,-250)
        transmission.set_editor_property('constant',unreal.LinearColor(.86,.91,.88,1))
        if not LIB.connect_material_expressions(transmission,'',output,'TransmittanceColor'):
            raise RuntimeError('Thin translucent transmission output missing')
    else:
        mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_MASKED if wire else unreal.BlendMode.BLEND_OPAQUE)
        color(mat, values.get('Base Color', [.5, .5, .5]), unreal.MaterialProperty.MP_BASE_COLOR)
        scalar(mat, values.get('Roughness', .65), unreal.MaterialProperty.MP_ROUGHNESS, 120)
        scalar(mat, values.get('Metallic', 0), unreal.MaterialProperty.MP_METALLIC, 240)
    links = record.get('links', [])
    imported = {}
    for i, image in enumerate(record.get('images', [])):
        filename = image['file']
        texture_name = safe(Path(filename).stem)
        texpath = target + '/' + texture_name
        texture = import_one(source / filename, target, texture_name)
        outgoing = [l for l in links if l['from'] == image['node']]
        low = (image['image'] + ' ' + filename).lower()
        normal = any('normal' in l['to'].lower() for l in outgoing) or '_nor_' in low or 'normal' in low
        base = any(l['input'] == 'Base Color' for l in outgoing) or '_diff' in low or 'basecolor' in low
        texture.set_editor_property('srgb', base)
        texture.set_editor_property('compression_settings', unreal.TextureCompressionSettings.TC_NORMALMAP if normal else
            unreal.TextureCompressionSettings.TC_DEFAULT if base else unreal.TextureCompressionSettings.TC_MASKS)
        if normal:
            texture.set_editor_property('flip_green_channel', True)
        ASSETS.save_loaded_asset(texture)
        imported[texture_name] = texture.get_path_name()
        if glass:
            if 'CrackDirt' in image['image']:
                sample=LIB.create_material_expression(mat,unreal.MaterialExpressionTextureSample,-750,250)
                sample.set_editor_property('texture',texture)
                sample.set_editor_property('sampler_type',unreal.MaterialSamplerType.SAMPLERTYPE_MASKS)
                variation=LIB.create_material_expression(mat,unreal.MaterialExpressionCustom,-450,200)
                variation.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT1)
                cracked='cracked' in name or 'broken' in name
                dirty='dirty' in name or cracked
                variation.set_editor_property('code',f'return saturate({values.get("Roughness",.08)}+Mask.g*{.65 if dirty else .12}+Mask.r*{.8 if cracked else 0});')
                pin=unreal.CustomInput();pin.set_editor_property('input_name','Mask');variation.set_editor_property('inputs',[pin])
                LIB.connect_material_expressions(sample,'RGB',variation,'Mask')
                LIB.connect_material_property(variation,'',unreal.MaterialProperty.MP_ROUGHNESS)
                if cracked:
                    # Height derivatives supply a real normal perturbation at each crack.
                    bump=LIB.create_material_expression(mat,unreal.MaterialExpressionCustom,-400,420)
                    bump.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT3)
                    bump.set_editor_property('code','return normalize(float3(-ddx(H)*8,-ddy(H)*8,1));')
                    inp=unreal.CustomInput();inp.set_editor_property('input_name','H');bump.set_editor_property('inputs',[inp])
                    LIB.connect_material_expressions(sample,'R',bump,'H');LIB.connect_material_property(bump,'',unreal.MaterialProperty.MP_NORMAL)
            continue
        node = LIB.create_material_expression(mat, unreal.MaterialExpressionTextureSample, -650, i * 260)
        node.set_editor_property('texture', texture)
        node.set_editor_property('sampler_type', unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL if normal else
            unreal.MaterialSamplerType.SAMPLERTYPE_COLOR if base else unreal.MaterialSamplerType.SAMPLERTYPE_MASKS)
        if normal:
            LIB.connect_material_property(node, 'RGB', unreal.MaterialProperty.MP_NORMAL)
        elif base:
            LIB.connect_material_property(node, 'RGB', unreal.MaterialProperty.MP_BASE_COLOR)
        elif '_rough' in low:
            LIB.connect_material_property(node, 'R', unreal.MaterialProperty.MP_ROUGHNESS)
        elif '_metal' in low:
            LIB.connect_material_property(node, 'R', unreal.MaterialProperty.MP_METALLIC)
        elif '_alpha' in low and wire:
            LIB.connect_material_property(node, 'R', unreal.MaterialProperty.MP_OPACITY_MASK)
        else:
            separate = [l['to'] for l in outgoing]
            destination = [l for l in links if l['from'] in separate]
            for link in destination:
                prop = {'Roughness': unreal.MaterialProperty.MP_ROUGHNESS,
                        'Metallic': unreal.MaterialProperty.MP_METALLIC}.get(link['input'])
                if prop:
                    channel = {'Green': 'G', 'Blue': 'B', 'Red': 'R'}.get(link['output'], link['output'])
                    LIB.connect_material_property(node, channel, prop)
    if name == 'M_Rig_Track':
        # Exposed travel parameter is updated independently for left/right tracks.
        coord = LIB.create_material_expression(mat, unreal.MaterialExpressionTextureCoordinate, -900, -400)
        travel = LIB.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -900, -200)
        travel.set_editor_property('parameter_name', 'Travel')
        custom = LIB.create_material_expression(mat, unreal.MaterialExpressionCustom, -500, -300)
        custom.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT3)
        custom.set_editor_property('code', 'float t=frac((UV.x+Travel)*60); float ridge=smoothstep(0.02,0.06,t)*(1-smoothstep(0.72,0.83,t)); return lerp(float3(.012,.017,.014),float3(.06,.068,.057),ridge);')
        pins=[]
        for pin_name in ['UV','Travel']:
            pin=unreal.CustomInput();pin.set_editor_property('input_name',pin_name);pins.append(pin)
        custom.set_editor_property('inputs',pins)
        LIB.connect_material_expressions(coord,'',custom,'UV');LIB.connect_material_expressions(travel,'',custom,'Travel')
        LIB.connect_material_property(custom,'',unreal.MaterialProperty.MP_BASE_COLOR)
    if values.get('Emission Strength', 0) > 0:
        color(mat, [v * values['Emission Strength'] for v in values['Emission Color'][:3]], unreal.MaterialProperty.MP_EMISSIVE_COLOR, -200)
    LIB.recompile_material(mat)
    ASSETS.save_loaded_asset(mat)
    return mat


def import_asset(path):
    asset = json.loads(path.read_text(encoding='utf-8'))
    name = asset['id']
    folder = DEST + '/' + name
    ASSETS.make_directory(folder)
    mats = {m['name']: material(m, asset, folder, path.parent) for m in asset['materials']}
    options = unreal.FbxImportUI()
    for key,value in [('import_mesh',True),('import_as_skeletal',False),('import_materials',False),('import_textures',False),
                      ('automated_import_should_detect_type',False),('mesh_type_to_import',unreal.FBXImportType.FBXIT_STATIC_MESH)]:
        options.set_editor_property(key,value)
    data = options.get_editor_property('static_mesh_import_data')
    for key,value in [('combine_meshes',True),('auto_generate_collision',False),('build_nanite',False),
                      ('convert_scene',True),('convert_scene_unit',True),('force_front_x_axis',True)]:
        data.set_editor_property(key,value)
    for part in asset['parts']:
        part['asset_name'] = 'SM_' + safe(part['object'])
        mesh = import_one(path.parent / part['fbx'], folder, part['asset_name'], options)
        for i, slot in enumerate(mesh.get_editor_property('static_materials')):
            imported = str(slot.get_editor_property('imported_material_slot_name'))
            expected = next((k for k in mats if safe(k)==safe(imported)),None)
            if expected is None:
                raise RuntimeError('Unexpected material slot: ' + name + '/' + imported)
            mesh.set_material(i,mats[expected])
        body = mesh.get_editor_property('body_setup')
        body.set_editor_property('collision_trace_flag',unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
        ASSETS.save_loaded_asset(mesh)
        if mesh.get_num_triangles(0)>7000:
            configure_lods(mesh)
        bounds = mesh.get_bounds()
        dimensions = [bounds.box_extent.x*2,bounds.box_extent.y*2,bounds.box_extent.z*2]
        if 'dimensions_m' in part:
            expected = sorted(v*100 for v in part['dimensions_m'])
            if not all(abs(a-b)<max(2,b*.03) for a,b in zip(sorted(dimensions),expected)):
                raise RuntimeError('Wrong imported dimensions: ' + name + '/' + part['object'] + str((dimensions,expected)))
        part['mesh'] = mesh.get_path_name()
        part['dimensions_cm'] = dimensions
    asset['folder'] = folder
    ASSETS.save_directory(folder,only_if_is_dirty=False,recursive=True)
    unreal.log('MR_LIBRARY_IMPORTED ' + name + ' ' + str(len(asset['parts'])) + ' parts')
    return asset


if __name__ == '__main__':
    destination = Path(unreal.Paths.project_content_dir()) / ('Scenario/library-v3.json' if V3 else 'Scenario/library-v2.json')
    match = re.search(r'-MRLibraryAssets=([A-Za-z0-9_,]+)', unreal.SystemLibrary.get_command_line())
    selected = set(match.group(1).split(',')) if match else None
    initial=destination if destination.exists() else destination.with_name('library-v2.json')
    records = json.loads(initial.read_text(encoding='utf-8'))['assets'] if (selected or V3) and initial.exists() else []
    updated = [import_asset(p) for p in sorted(BASE.glob('*/asset.json')) if selected is None or p.parent.name in selected]
    records = sorted([r for r in records if r['id'] not in {a['id'] for a in updated}] + updated, key=lambda r:r['id'])
    destination.write_text(json.dumps({'version':3 if V3 else 2,'assets':records},indent=2),encoding='utf-8')
    (ROOT / ('artifacts/quarter-v3/ue-library-import.json' if V3 else 'artifacts/3d-world/ue-library-import.json')).write_text(json.dumps({'assets':records},indent=2),encoding='utf-8')
    unreal.log('MR_LIBRARY_IMPORT_COMPLETE ' + str(len(records)))
