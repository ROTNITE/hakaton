"""Save the generated v3 scene; effect assets are prepared separately."""
from pathlib import Path
import hashlib
import json
import runpy
import unreal

folder=Path(__file__).resolve().parent
root=Path(unreal.Paths.project_dir()).resolve().parents[1]
# Build the surface graphs first, then duplicate materials into v3. Existing v2
# material assets and their master-instance relationships remain untouched.
source=(folder/'build_quarter.py').read_text(encoding='utf-8')
exec(compile(source.split('level = unreal.get_editor_subsystem')[0],str(folder/'build_quarter.py'),'exec'))
lib=unreal.EditorAssetLibrary
manifest=root/'unreal/MetaRescue/Content/Scenario/library-v3.json'
record=json.loads(manifest.read_text(encoding='utf-8'))
mapping={}

def copy_material(material):
    key=material.get_path_name()
    if key in mapping:return unreal.load_asset(mapping[key])
    if 'glass' in material.get_name().lower() and '/LibraryV3/' not in key:
        clean=unreal.load_asset('/Game/RescueAssets/LibraryV3/GlazingKit/Materials/M_GlassV3_clean')
        result=copy_material(clean);mapping[key]=result.get_path_name();return result
    # The source contents are part of the cache key. A path-only cache silently
    # kept obsolete glass/surface graphs after the source material was rebuilt.
    fingerprint=key.encode()+b'v3-surface-detail-1'
    if key.startswith('/Game/'):
        file=root/'unreal/MetaRescue/Content'/(key.split('.')[0][6:]+'.uasset')
        fingerprint+=file.read_bytes()
    digest=hashlib.sha256(fingerprint).hexdigest()[:12]
    path='/Game/MaterialsV3/Instances/'+material.get_name()+'_'+digest
    existing=unreal.load_asset(path)
    copy=existing or lib.duplicate_asset(key,path)
    if copy is None:raise RuntimeError('Material copy failed: '+key)
    mapping[key]=copy.get_path_name()
    if isinstance(copy,unreal.MaterialInstanceConstant):
        parent=material.get_editor_property('parent')
        unreal.MaterialEditingLibrary.set_material_instance_parent(copy,copy_material(parent))
    elif isinstance(copy,unreal.Material):
        if existing is None and material.get_name() in {'MI_Concrete','M_V3_Concrete','MI_Ground'}:
            # V3-only detail, preserving the original library material graphs.
            edit=unreal.MaterialEditingLibrary
            earth=material.get_name()=='MI_Ground'
            world=edit.create_material_expression(copy,unreal.MaterialExpressionWorldPosition,-950,900)
            for prop,code in [
                (unreal.MaterialProperty.MP_BASE_COLOR,'''float3 base=BASE;
float grain=frac(sin(dot(floor(P*1.8),float3(12.8,78.2,31.7)))*17652.23);
float coarse=sin(P.x*.045+sin(P.y*.027))*cos(P.z*.061+P.y*.018);
return base*(.82+grain*.21+coarse*.10);'''.replace('BASE','float3(.20,.15,.105)' if earth else 'float3(.31,.30,.275)')),
                (unreal.MaterialProperty.MP_NORMAL,'''float a=sin(P.x*.24)*cos(P.y*.31+P.z*.17);
float b=cos(P.y*.29)*sin(P.z*.23+P.x*.19);
return normalize(float3(a*.055,b*.055,1));''')]:
                expr=edit.create_material_expression(copy,unreal.MaterialExpressionCustom,-650,900 if prop==unreal.MaterialProperty.MP_BASE_COLOR else 1150)
                expr.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT3)
                expr.set_editor_property('code',code)
                pin=unreal.CustomInput();pin.set_editor_property('input_name','P');expr.set_editor_property('inputs',[pin])
                edit.connect_material_expressions(world,'',expr,'P');edit.connect_material_property(expr,'',prop)
        copy.set_editor_property('used_with_instanced_static_meshes',True)
        unreal.MaterialEditingLibrary.recompile_material(copy)
    lib.save_loaded_asset(copy)
    return copy

for asset in record['assets']:
    for part in asset['parts']:
        mesh=unreal.load_asset(part['mesh'])
        for slot in mesh.get_editor_property('static_materials'):
            material=slot.get_editor_property('material_interface')
            if material:copy_material(material)
for path in lib.list_assets('/Game/Materials',recursive=False,include_folder=False):
    material=unreal.load_asset(path)
    if isinstance(material,(unreal.Material,unreal.MaterialInstanceConstant)):copy_material(material)
record['material_overrides']=mapping
manifest.write_text(json.dumps(record,indent=2),encoding='utf-8')
runpy.run_path(str(folder/'build_quarter.py'),run_name='__main__')
