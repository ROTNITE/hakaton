"""Run inside UnrealEditor-Cmd with -run=pythonscript -script=<this file>.

Creates authored material assets and the saved district map through editor APIs.
Does not edit engine files or depend on downloaded art.
"""
import unreal
from pathlib import Path
import json

TOOLS=unreal.AssetToolsHelpers.get_asset_tools()
LIB=unreal.MaterialEditingLibrary
ASSETS=unreal.EditorAssetLibrary
unreal.log('MR_BUILD: creating materials')
ASSETS.make_directory('/Game/Materials')
ASSETS.make_directory('/Game/Maps')
master=unreal.load_asset('/Game/Materials/M_RescueSurface')
if master is None:
    master=TOOLS.create_asset('M_RescueSurface','/Game/Materials',unreal.Material,unreal.MaterialFactoryNew())
    def node(cls,x,y):return LIB.create_material_expression(master,cls,x,y)
    color=node(unreal.MaterialExpressionVectorParameter,-650,0)
    color.set_editor_property('parameter_name','Tint')
    color.set_editor_property('default_value',unreal.LinearColor(.4,.4,.4,1))
    variation=node(unreal.MaterialExpressionScalarParameter,-650,150)
    variation.set_editor_property('parameter_name','Variation');variation.set_editor_property('default_value',.15)
    pos=node(unreal.MaterialExpressionWorldPosition,-850,-350)
    scale=node(unreal.MaterialExpressionScalarParameter,-850,-200)
    scale.set_editor_property('parameter_name','GrainSize');scale.set_editor_property('default_value',40)
    divide=node(unreal.MaterialExpressionDivide,-650,-320)
    LIB.connect_material_expressions(pos,'',divide,'A');LIB.connect_material_expressions(scale,'',divide,'B')
    noise=node(unreal.MaterialExpressionNoise,-450,-320)
    noise.set_editor_property('quality',1);noise.set_editor_property('levels',2)
    noise.set_editor_property('scale',1);noise.set_editor_property('output_min',0);noise.set_editor_property('output_max',1)
    LIB.connect_material_expressions(divide,'',noise,'Position')
    grain=node(unreal.MaterialExpressionMultiply,-230,-180)
    LIB.connect_material_expressions(noise,'',grain,'A');LIB.connect_material_expressions(variation,'',grain,'B')
    multiplier=node(unreal.MaterialExpressionAdd,-30,-160)
    multiplier.set_editor_property('const_b',.84);LIB.connect_material_expressions(grain,'',multiplier,'A')
    tinted=node(unreal.MaterialExpressionMultiply,130,0)
    LIB.connect_material_expressions(color,'',tinted,'A');LIB.connect_material_expressions(multiplier,'',tinted,'B')
    LIB.connect_material_property(tinted,'',unreal.MaterialProperty.MP_BASE_COLOR)
    for name,value,prop,y in [('Roughness',.85,unreal.MaterialProperty.MP_ROUGHNESS,220),('Metallic',0,unreal.MaterialProperty.MP_METALLIC,330)]:
        scalar=node(unreal.MaterialExpressionScalarParameter,130,y)
        scalar.set_editor_property('parameter_name',name);scalar.set_editor_property('default_value',value)
        LIB.connect_material_property(scalar,'',prop)
    glow=node(unreal.MaterialExpressionScalarParameter,-150,440)
    glow.set_editor_property('parameter_name','Glow');glow.set_editor_property('default_value',0)
    emissive=node(unreal.MaterialExpressionMultiply,130,440)
    LIB.connect_material_expressions(color,'',emissive,'A');LIB.connect_material_expressions(glow,'',emissive,'B')
    LIB.connect_material_property(emissive,'',unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    LIB.recompile_material(master)
    ASSETS.save_loaded_asset(master)

# Colors are linear material values. Weathering is world-space and scale-aware.
palette={
 'Concrete':((.40,.38,.33),.89,0,.34,50,0),
 'Plaster':((.57,.55,.48),.9,0,.2,75,0),
 'Asphalt':((.075,.085,.08),.93,0,.55,9,0),
 'Ground':((.29,.32,.25),.93,0,.25,60,0),
 'Mud':((.17,.115,.065),.58,0,.4,30,0),
 'Metal':((.18,.21,.20),.45,.7,.15,14,0),
 'Rust':((.22,.095,.04),.86,.35,.5,10,0),
 'Glass':((.055,.13,.17),.16,.75,.01,20,0),
 'Orange':((.78,.19,.035),.48,.32,.05,30,0),
 'Blue':((.025,.24,.46),.35,.45,.04,30,0),
 'Teal':((.08,.24,.21),.6,.3,.08,35,0),
 'Dark':((.025,.035,.031),.56,.4,.06,12,0),
 'Rubber':((.018,.024,.021),.96,0,.2,7,0),
 'White':((.7,.73,.67),.65,.1,.02,30,0),
 'Red':((.65,.045,.025),.65,0,.05,25,0),
 'Paint':((.59,.52,.28),.92,0,.25,8,0),
 'Equipment':((.14,.18,.11),.83,.15,.15,25,0),
 'Zone':((.07,.22,.16),.83,0,.05,30,0),
 'CyanGlow':((.03,.52,.8),.24,.3,.01,20,2.5),
 'WhiteGlow':((.85,.91,.72),.3,0,.01,20,1.5),
 'Rotor':((.07,.09,.08),.4,.45,.01,15,0),
 'Water':((.025,.11,.14),.14,.3,.07,75,0),
}
for name,(rgb,rough,metal,var,grain,glow) in palette.items():
    instance=unreal.load_asset('/Game/Materials/MI_'+name)
    if instance is None:instance=TOOLS.create_asset('MI_'+name,'/Game/Materials',unreal.MaterialInstanceConstant,unreal.MaterialInstanceConstantFactoryNew())
    LIB.set_material_instance_parent(instance,master)
    LIB.set_material_instance_vector_parameter_value(instance,'Tint',unreal.LinearColor(*rgb,1))
    for param,value in [('Roughness',rough),('Metallic',metal),('Variation',var),('GrainSize',grain),('Glow',glow)]:
        LIB.set_material_instance_scalar_parameter_value(instance,param,value)
    ASSETS.save_loaded_asset(instance)

unreal.log('MR_BUILD: creating district map')
level=unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
actors=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
map_path='/Game/Maps/RescueDistrict'
if ASSETS.does_asset_exist(map_path):
    if not level.load_level(map_path):raise RuntimeError('Cannot load existing map')
else:
    if not level.new_level(map_path):raise RuntimeError('Cannot create map')
district_class=unreal.load_class(None,'/Script/MetaRescue.MRWorld')
district=next((a for a in actors.get_all_level_actors() if a.get_class()==district_class),None)
if district is None:district=actors.spawn_actor_from_class(district_class,unreal.Vector(0,0,0))
district.set_actor_label('Rescue District — imported benchmark scenario')
district.build_scene()
def get_or_spawn(cls,location,rotation=unreal.Rotator(0,0,0)):
    current=next((a for a in actors.get_all_level_actors() if isinstance(a,cls)),None)
    if current is None:current=actors.spawn_actor_from_class(cls,location,rotation)
    return current

sun=get_or_spawn(unreal.DirectionalLight,unreal.Vector(0,0,4000),unreal.Rotator(-36,-28,0))
light=sun.get_component_by_class(unreal.DirectionalLightComponent)
light.set_mobility(unreal.ComponentMobility.MOVABLE);light.set_intensity(45000)
light.set_light_color(unreal.LinearColor(1,.97,.91,1));light.set_atmosphere_sun_light(True)
light.set_editor_property('light_source_angle',1.5)
get_or_spawn(unreal.SkyAtmosphere,unreal.Vector(0,0,0))
sky=get_or_spawn(unreal.SkyLight,unreal.Vector(0,0,2000))
skycomp=sky.get_component_by_class(unreal.SkyLightComponent)
skycomp.set_mobility(unreal.ComponentMobility.MOVABLE);skycomp.set_real_time_capture(True);skycomp.set_intensity(1.1)
fog=get_or_spawn(unreal.ExponentialHeightFog,unreal.Vector(0,0,-100))
fogcomp=fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
fogcomp.set_editor_property('fog_density',.006)
fogcomp.set_editor_property('fog_height_falloff',.25)
fogcomp.set_editor_property('enable_volumetric_fog',True)
post=get_or_spawn(unreal.PostProcessVolume,unreal.Vector(0,0,0))
post.set_editor_property('unbound',True)
settings=post.get_editor_property('settings')
for key,value in [('bloom_intensity',.25),('vignette_intensity',.12),('motion_blur_amount',0),
                  ('auto_exposure_min_brightness',10),('auto_exposure_max_brightness',16),('auto_exposure_bias',0)]:
    settings.set_editor_property('override_'+key,True);settings.set_editor_property(key,value)
post.set_editor_property('settings',settings)
start=get_or_spawn(unreal.PlayerStart,unreal.Vector(-2000,-2000,400))
unreal.EditorLevelLibrary.set_level_viewport_camera_info(unreal.Vector(-4000,-4000,8000),unreal.Rotator(-45,45,0))
if not level.save_current_level():raise RuntimeError('Map save failed')
ASSETS.save_directory('/Game/Materials',only_if_is_dirty=False,recursive=True)
marker=Path(unreal.Paths.project_content_dir())/'Scenario'/'scene-build.json'
marker.parent.mkdir(parents=True,exist_ok=True)
marker.write_text(json.dumps({'ready':True,'map':map_path,'materials':len(palette)}),encoding='utf-8')
unreal.log('MR_BUILD_COMPLETE: materials and /Game/Maps/RescueDistrict saved')
