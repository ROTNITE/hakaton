"""City-only material derivatives with persisted Nanite/instance usage.

Originals, v2 and Quarter material assets are never resaved. A copied hierarchy
keeps parameter overrides and shader graphs, adding only the required usages.
"""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import unreal

ROOT=Path(unreal.Paths.project_dir()).resolve().parents[1]
CONTENT=ROOT/'unreal/MetaRescue/Content'
VERSION='city-materials-v1-nanite-hism'
tools=unreal.AssetToolsHelpers.get_asset_tools()
edit=unreal.MaterialEditingLibrary
assets=unreal.EditorAssetLibrary
replacements={};checks=[]


def configure(material):
    material.set_editor_property('used_with_instanced_static_meshes',True)
    if material.get_editor_property('blend_mode') in (unreal.BlendMode.BLEND_OPAQUE,unreal.BlendMode.BLEND_MASKED):
        material.set_editor_property('used_with_nanite',True)
    edit.recompile_material(material)


for name,color,roughness in [('City_Leaves',(.075,.14,.035),.94),
                              ('City_Bark',(.13,.08,.04),.96),
                              ('City_Soil',(.13,.105,.07),1.0)]:
    path='/Game/MaterialsCity/'+name
    material=unreal.load_asset(path)
    if material is None:
        material=tools.create_asset(name,'/Game/MaterialsCity',unreal.Material,unreal.MaterialFactoryNew())
        rgb=edit.create_material_expression(material,unreal.MaterialExpressionConstant3Vector,-250,0)
        rgb.set_editor_property('constant',unreal.LinearColor(*color,1))
        edit.connect_material_property(rgb,'',unreal.MaterialProperty.MP_BASE_COLOR)
        rough=edit.create_material_expression(material,unreal.MaterialExpressionConstant,-250,160)
        rough.set_editor_property('r',roughness)
        edit.connect_material_property(rough,'',unreal.MaterialProperty.MP_ROUGHNESS)
    configure(material)
    assert assets.save_loaded_asset(material)
    replacements[material.get_path_name()]=material.get_path_name()


def package_file(path):
    package=path.split('.')[0]
    base=CONTENT if package.startswith('/Game/') else Path(unreal.Paths.engine_content_dir())
    return base/(package.split('/',2)[2]+'.uasset')


def copy_material(source):
    path=source.get_path_name()
    if path in replacements:return unreal.load_asset(replacements[path])
    digest=hashlib.sha256(package_file(path).read_bytes()+VERSION.encode()).hexdigest()[:16]
    dest='/Game/MaterialsCity/Imported/'+source.get_name()+'_'+digest
    copy=unreal.load_asset(dest) or assets.duplicate_asset(path,dest)
    assert copy is not None,path
    replacements[path]=copy.get_path_name()
    if isinstance(source,unreal.MaterialInstanceConstant):
        edit.set_material_instance_parent(copy,copy_material(source.get_editor_property('parent')))
    elif isinstance(source,unreal.Material):
        configure(copy)
    else:
        raise RuntimeError('Unsupported material hierarchy: '+path)
    assert assets.save_loaded_asset(copy)
    return copy


library=json.loads((CONTENT/'Scenario/library-v3.json').read_text(encoding='utf-8'))
city=json.loads((CONTENT/'Scenario/city-assets.json').read_text(encoding='utf-8'))
source_paths=set(library.get('material_overrides',{}).values())
for path in assets.list_assets('/Game/Materials',recursive=False,include_folder=False):
    item=unreal.load_asset(path)
    if isinstance(item,(unreal.Material,unreal.MaterialInstanceConstant)):
        source_paths.add(library.get('material_overrides',{}).get(item.get_path_name(),item.get_path_name()))
for record in [*city['replacements'].values(),*city['baked_boxes_cm'].values()]:
    for part in record['parts']:
        mesh=unreal.load_asset(part['mesh'])
        for slot in mesh.get_editor_property('static_materials'):
            material=slot.get_editor_property('material_interface')
            if material:source_paths.add(material.get_path_name())
for path in sorted(source_paths):copy_material(unreal.load_asset(path))
unreal.MRAssetTools.finish_asset_compilation()
for source,destination in replacements.items():
    material=unreal.load_asset(destination)
    while isinstance(material,unreal.MaterialInstanceConstant):material=material.get_editor_property('parent')
    assert isinstance(material,unreal.Material),destination
    opaque=material.get_editor_property('blend_mode') in (unreal.BlendMode.BLEND_OPAQUE,unreal.BlendMode.BLEND_MASKED)
    assert material.get_editor_property('used_with_instanced_static_meshes'),destination
    assert not opaque or material.get_editor_property('used_with_nanite'),destination
    checks.append({'source':source,'derived':destination,'base':material.get_path_name(),
                   'opaque':opaque,'instancing':True,'nanite':bool(material.get_editor_property('used_with_nanite'))})
report={'format':VERSION,'replacements':replacements,'checks':checks,'runtime_render_verified':False}
folder=Path('D:/MetaRescue-output/city-assets');folder.mkdir(parents=True,exist_ok=True)
target=folder/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-materials.json')
target.write_text(json.dumps(report,indent=2),encoding='utf-8')
(CONTENT/'Scenario/city-materials.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
unreal.log('MR_CITY_MATERIALS_READY '+str(len(replacements))+' '+str(target))
