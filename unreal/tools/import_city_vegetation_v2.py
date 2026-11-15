"""Import verified Poly Haven derivatives into the versioned CityV2 content."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sys

import unreal

sys.path.insert(0,str(Path(__file__).resolve().parent))
from import_rescue_assets import import_one

CONTENT=Path(unreal.Paths.project_content_dir())
source=Path(os.environ['MR_CITY_V2_PREPARED']).resolve(strict=True)
data=json.loads(source.read_text(encoding='utf-8'))
if data['format']=='metarescue.polyhaven-city-prop.v1':
    VERSION='metarescue.city-props.v1'
    FOLDER='/Game/RescueAssets/CityV2/Props'
    CATALOG='city-props-v1.json'
else:
    assert data['format']=='metarescue.polyhaven-foliage.v2'
    VERSION='metarescue.city-vegetation.v2.r3'
    FOLDER='/Game/RescueAssets/CityV2/VegetationR3'
    CATALOG='city-vegetation-v2-r3.json'
tools=unreal.AssetToolsHelpers.get_asset_tools()
library=unreal.EditorAssetLibrary
edit=unreal.MaterialEditingLibrary


def sha256(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def texture(record,usage):
    path=Path(record['path']);assert sha256(path)==record['sha256'],path
    name='T_'+path.stem+'_'+record['sha256'][:10]
    item=unreal.load_asset(FOLDER+'/Maps/'+name) or import_one(path,FOLDER+'/Maps',name)
    assert isinstance(item,unreal.Texture2D),path
    color=usage in ('base_color','base_color_alpha')
    if usage=='normal':
        item.set_editor_property('compression_settings',unreal.TextureCompressionSettings.TC_NORMALMAP)
        item.set_editor_property('flip_green_channel',True)
    elif not color:
        item.set_editor_property('compression_settings',unreal.TextureCompressionSettings.TC_MASKS)
    else:
        item.set_editor_property('compression_settings',unreal.TextureCompressionSettings.TC_DEFAULT)
    if usage in ('opacity','base_color_alpha'):
        threshold=unreal.Vector4(.33,0,0,0) if usage=='opacity' else unreal.Vector4(0,0,0,.33)
        item.set_editor_property('do_scale_mips_for_alpha_coverage',True)
        item.set_editor_property('alpha_coverage_thresholds',threshold)
    item.set_editor_property('srgb',color)
    assert item.get_editor_property('srgb')==color,(path,usage)
    assert library.save_loaded_asset(item)
    return item


def material(slot):
    digest=hashlib.sha256(json.dumps(slot,sort_keys=True).encode()+VERSION.encode()).hexdigest()[:10]
    name='M_'+slot['name']+'_'+digest;folder=FOLDER+'/Materials'
    existing=unreal.load_asset(folder+'/'+name)
    if existing:return existing
    item=tools.create_asset(name,folder,unreal.Material,unreal.MaterialFactoryNew())
    maps=slot['maps'];masked='opacity' in maps
    item.set_editor_property('used_with_instanced_static_meshes',True)
    item.set_editor_property('used_with_nanite',True)
    if masked:
        item.set_editor_property('two_sided',True)
        item.set_editor_property('blend_mode',unreal.BlendMode.BLEND_MASKED)
        item.set_editor_property('shading_model',unreal.MaterialShadingModel.MSM_TWO_SIDED_FOLIAGE)
        item.set_editor_property('opacity_mask_clip_value',.33)
    color_alpha=slot['name']=='tree_small_02_leaves'
    property_by_usage={'base_color':unreal.MaterialProperty.MP_BASE_COLOR,'normal':unreal.MaterialProperty.MP_NORMAL,
        'roughness':unreal.MaterialProperty.MP_ROUGHNESS,'opacity':unreal.MaterialProperty.MP_OPACITY_MASK,
        'metallic':unreal.MaterialProperty.MP_METALLIC}
    for i,(usage,record) in enumerate(maps.items()):
        if color_alpha and usage=='opacity':
            continue
        sample=edit.create_material_expression(item,unreal.MaterialExpressionTextureSample,-560,i*220)
        sample.set_editor_property('texture',texture(record,'base_color_alpha' if color_alpha and usage=='base_color' else usage))
        sampler=(unreal.MaterialSamplerType.SAMPLERTYPE_COLOR if usage=='base_color' else
                 unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL if usage=='normal' else unreal.MaterialSamplerType.SAMPLERTYPE_MASKS)
        sample.set_editor_property('sampler_type',sampler)
        assert edit.connect_material_property(sample,'RGB' if usage in ('base_color','normal') else 'R',property_by_usage[usage])
        if masked and usage=='base_color':
            assert edit.connect_material_property(sample,'RGB',unreal.MaterialProperty.MP_SUBSURFACE_COLOR)
            if color_alpha:
                assert edit.connect_material_property(sample,'A',unreal.MaterialProperty.MP_OPACITY_MASK)
    edit.recompile_material(item);assert library.save_loaded_asset(item)
    return item


def mesh(row):
    filename=Path(row['fbx']);assert sha256(filename)==row['fbx_sha256'],filename
    name='SM_'+row['id']+'_'+row['fbx_sha256'][:12];folder=FOLDER+'/Source'
    path=folder+'/'+name
    item=unreal.load_asset(path)
    if item is None:
        options=unreal.FbxImportUI()
        for key,value in [('import_mesh',True),('import_as_skeletal',False),('import_materials',False),
                          ('import_textures',False),('automated_import_should_detect_type',False),
                          ('mesh_type_to_import',unreal.FBXImportType.FBXIT_STATIC_MESH)]:options.set_editor_property(key,value)
        options_data=options.get_editor_property('static_mesh_import_data')
        for key,value in [('combine_meshes',True),('auto_generate_collision',False),('build_nanite',False),
                          ('convert_scene',True),('convert_scene_unit',True),('force_front_x_axis',True)]:options_data.set_editor_property(key,value)
        task=unreal.AssetImportTask()
        for key,value in [('filename',str(filename)),('destination_path',folder),('destination_name',name),
                          ('automated',True),('save',True),('replace_existing',False),('options',options)]:task.set_editor_property(key,value)
        tools.import_asset_tasks([task]);item=unreal.load_asset(path)
    assert isinstance(item,unreal.StaticMesh),path
    available={slot['name']:slot for slot in row['materials']};readback=[]
    for i,slot in enumerate(item.get_editor_property('static_materials')):
        label=str(slot.get_editor_property('imported_material_slot_name'))
        assert label in available,(path,label,sorted(available))
        mat=material(available[label]);item.set_material(i,mat)
        readback.append({'slot':label,'asset':mat.get_path_name(),'masked':'opacity' in available[label]['maps']})
    assert len(readback)==len(available) and library.save_loaded_asset(item)
    native=json.loads(unreal.MRAssetTools.describe_mesh_geometry(item))
    assert native['available'] and abs(native['source_min_cm'][2])<.03,native
    assert abs(native['source_max_cm'][2]-row['bounds_m']['max'][2]*100)<.1,native
    assert native['triangles']==row['triangles'],native
    if any(slot['masked'] for slot in readback):
        # Source leaf cards retain conventional instanced rasterisation and mip
        # coverage. Opaque deadwood still uses the verified Nanite derivative.
        assert not native['nanite_enabled'],native
        render=item
    else:
        verified=json.loads(unreal.MRAssetTools.prepare_city_mesh(item,FOLDER+'/'+name,unreal.Vector(1,1,1)))
        assert verified['verified'] and len(verified['parts'])==1,verified
        render=unreal.load_asset(verified['parts'][0]['mesh'])
    assert render and library.save_loaded_asset(render)
    return {'id':row['id'],'asset':row['asset'],'kind':row['kind'],'mesh':render.get_path_name(),
            'source_object':row['source_object'],'source_sha256':row['source_sha256'],'fbx_sha256':row['fbx_sha256'],
            'bounds_m':{side:[round(n/100,6) for n in native['source_'+side+'_cm']] for side in ('min','max')},
            'triangles':native['triangles'],'materials':readback,'source_url':row['source_url'],'license':row['license']}


models=[mesh(row) for row in data['models']]
unreal.MRAssetTools.finish_asset_compilation()
report={'format':VERSION,'preparation_manifest_sha256':sha256(source),'models':models}
destination=CONTENT/'Scenario'/CATALOG
if destination.exists():
    assert json.loads(destination.read_text(encoding='utf-8'))==report,'Use a new content manifest for changed imports'
else:
    with destination.open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2)
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
evidence=source.parent/(stamp+'-unreal-import.json')
with evidence.open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2)
unreal.log(('MR_CITY_PROPS_READY ' if VERSION=='metarescue.city-props.v1' else 'MR_CITY_V2_VEGETATION_READY ')+str(evidence))
