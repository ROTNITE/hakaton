"""Read back v3 geometry, window variants, grounding metadata and real fault."""
from pathlib import Path
import json
import math
from datetime import datetime, timezone
import unreal

root=Path(unreal.Paths.project_dir()).resolve().parents[1]
level=unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
actors=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
assert level.load_level('/Game/Maps/RescueQuarter')
cls=unreal.load_class(None,'/Script/MetaRescue.MRWorld')
worlds=[a for a in actors.get_all_level_actors() if a.get_class()==cls]
assert len(worlds)==1
world=worlds[0]
components=world.get_components_by_class(unreal.StaticMeshComponent)
library=json.loads((root/'unreal/MetaRescue/Content/Scenario/library-v3.json').read_text(encoding='utf-8-sig'))
glazing=next(a for a in library['assets'] if a['id']=='GlazingKit')
glazing_parts={part['mesh']:part for part in glazing['parts']}
sub=unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
if sub is None:
    # Commandlets do not always initialize editor subsystems. This is the same
    # stateless fallback already used by the import and lighting tools.
    sub=unreal.new_object(unreal.StaticMeshEditorSubsystem)
matlib=unreal.MaterialEditingLibrary
window_styles=set();glass_readback={}

def verify_glass(mat):
    while isinstance(mat,unreal.MaterialInstance):mat=mat.get_editor_property('parent')
    path=mat.get_path_name()
    if path in glass_readback:return
    assert mat.get_editor_property('blend_mode')==unreal.BlendMode.BLEND_TRANSLUCENT,path
    assert mat.get_editor_property('shading_model')==unreal.MaterialShadingModel.MSM_THIN_TRANSLUCENT,path
    assert mat.get_editor_property('translucency_lighting_mode')==unreal.TranslucencyLightingMode.TLM_SURFACE_PER_PIXEL_LIGHTING,path
    assert mat.get_editor_property('two_sided'),path
    opacity=matlib.get_material_property_input_node(mat,unreal.MaterialProperty.MP_OPACITY)
    assert isinstance(opacity,unreal.MaterialExpressionConstant),('unexpected glass surface-layer graph',path)
    value=opacity.get_editor_property('r')
    assert 0<=value<.20,('glass surface layer blocks transmission',path,value)
    roughness=matlib.get_material_property_input_node(mat,unreal.MaterialProperty.MP_ROUGHNESS)
    assert roughness is not None,('no glass roughness input',path)
    expressions=matlib.get_material_expressions(mat)
    outputs=[n for n in expressions if isinstance(n,unreal.MaterialExpressionThinTranslucentMaterialOutput)]
    assert len(outputs)==1,('wrong ThinTranslucent output count',path,len(outputs))
    inputs=[n for n in matlib.get_inputs_for_material_expression(mat,outputs[0]) if n is not None]
    assert inputs,('missing actual transmission connection',path)
    transmissions=[n for n in inputs if isinstance(n,unreal.MaterialExpressionConstant3Vector)]
    assert transmissions,('unexpected transmission graph; inspect actual graph',path)
    color=transmissions[0].get_editor_property('constant')
    rgb=[color.r,color.g,color.b]
    assert all(math.isfinite(c) and .5<c<=1 for c in rgb),('unexpected pane transmission',path,rgb)
    glass_readback[path]={'opacity':value,'transmission_rgb':rgb,'roughness_node':roughness.get_class().get_name(),'thin_output_count':len(outputs)}
instances=0;variants=set();windows=set();meshes={};lighting_surfaces=0
for c in components:
    mesh=c.get_editor_property('static_mesh');assert mesh is not None,c.get_name()
    count=c.get_instance_count() if isinstance(c,unreal.InstancedStaticMeshComponent) else 1
    instances+=count;path=mesh.get_path_name();meshes[path]=meshes.get(path,0)+count
    for tag in c.get_editor_property('component_tags'):
        text=str(tag)
        if text.startswith('BuildingVariant:'):variants.add(int(text.split(':')[1]))
    if c.component_has_tag('InteriorLightingSurface'):
        assert path.startswith('/Game/RescueAssets/LibraryV3/Lighting/'),('unbaked interior mesh',path)
        scale=c.get_world_scale()
        assert all(abs(v-1)<.00001 for v in (scale.x,scale.y,scale.z)),('unbaked interior scale',c.get_name())
        settings=sub.get_lod_build_settings(mesh,0)
        assert settings.get_editor_property('distance_field_resolution_scale')==3
        assert settings.get_editor_property('max_lumen_mesh_cards')==24
        lighting_surfaces+=1
    if path in glazing_parts:
        windows.add(path);part=glazing_parts[path]
        style=part['object'].rsplit('_',1)[-1];window_styles.add(style)
        actual=mesh.get_num_triangles(0)
        assert abs(actual-part['triangles'])<=max(3,part['triangles']*.03),('window geometry changed',path,actual,part['triangles'])
        assert sub.get_num_uv_channels(mesh,0)>0,('window UV missing',path)
        if style!='empty':
            matched=[c.get_material(i) for i in range(c.get_num_materials()) if c.get_material(i) and ('M_GlassV3_'+style) in c.get_material(i).get_name()]
            assert matched,('actual window has no material for its style',path,style)
            for mat in matched:verify_glass(mat)
    for i in range(c.get_num_materials()):assert c.get_material(i) is not None
    if isinstance(c,unreal.InstancedStaticMeshComponent):
        for i in range(c.get_num_materials()):
            mat=c.get_material(i)
            while isinstance(mat,unreal.MaterialInstance):mat=mat.get_editor_property('parent')
            assert mat.get_editor_property('used_with_instanced_static_meshes'),mat.get_path_name()
assert variants==set(range(6)),variants
assert len(windows)>=12,windows
assert window_styles=={'clean','dirty','cracked','broken','empty'},window_styles
assert any(isinstance(c,unreal.HierarchicalInstancedStaticMeshComponent) for c in components),'No repeated geometry batching'
for style in ['clean','dirty','cracked','broken']:
    mat=unreal.load_asset('/Game/RescueAssets/LibraryV3/GlazingKit/Materials/M_GlassV3_'+style)
    assert mat.get_editor_property('shading_model')==unreal.MaterialShadingModel.MSM_THIN_TRANSLUCENT
assert lighting_surfaces>0,'No verified lighting surfaces'
result={'passed':True,'scope':'asset geometry, materials and lighting settings; runtime visual quality remains separate','lighting_surfaces':lighting_surfaces,'components':len(components),'instances':instances,'building_variants':sorted(variants),'window_modules':sorted(windows),'window_styles':sorted(window_styles),'actual_map_glass_materials':glass_readback,'meshes':meshes}
folder=Path('D:/MetaRescue-output/readbacks');folder.mkdir(parents=True,exist_ok=True)
target=folder/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-quarter-v3.json')
target.write_text(json.dumps(result,indent=2),encoding='utf-8')
unreal.log('MR_V3_READBACK_REPORT '+str(target))
unreal.log('MR_V3_SCENE_VERIFIED '+str(instances)+' instances')
