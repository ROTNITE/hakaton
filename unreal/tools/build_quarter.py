"""Create the separate authored RescueQuarter map; never rebuild the legacy map."""
from pathlib import Path
import json

import unreal


ASSETS = unreal.EditorAssetLibrary
TOOLS = unreal.AssetToolsHelpers.get_asset_tools()
LIB = unreal.MaterialEditingLibrary


def surface(name, code, roughness):
    material = unreal.load_asset('/Game/Materials/' + name)
    if material is None:
        material = TOOLS.create_asset(name, '/Game/Materials', unreal.Material, unreal.MaterialFactoryNew())
    LIB.delete_all_material_expressions(material)
    position = LIB.create_material_expression(material, unreal.MaterialExpressionWorldPosition, -600, 0)
    custom = LIB.create_material_expression(material, unreal.MaterialExpressionCustom, -350, 0)
    custom.set_editor_property('code', code)
    custom.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    input_pin = unreal.CustomInput()
    input_pin.set_editor_property('input_name', 'WorldPos')
    custom.set_editor_property('inputs', [input_pin])
    LIB.connect_material_expressions(position, '', custom, 'WorldPos')
    LIB.connect_material_property(custom, '', unreal.MaterialProperty.MP_BASE_COLOR)
    scalar = LIB.create_material_expression(material, unreal.MaterialExpressionConstant, -350, 220)
    scalar.set_editor_property('r', roughness)
    LIB.connect_material_property(scalar, '', unreal.MaterialProperty.MP_ROUGHNESS)
    LIB.recompile_material(material)
    ASSETS.save_loaded_asset(material)
    return material


surface('M_QuarterPaving', '''
float2 p=WorldPos.xy/50.0;
p.x+=fmod(floor(p.y*2.0),2.0)*0.5;
float2 q=float2(p.x,p.y*2.0), f=frac(q), cell=floor(q);
float h=frac(sin(dot(cell,float2(127.1,311.7)))*43758.5453);
float edge=min(min(f.x,1.0-f.x),min(f.y,1.0-f.y));
float grout=1.0-smoothstep(0.014,0.032,edge);
float grain=frac(sin(dot(floor(WorldPos.xy*1.2),float2(12.8,78.2)))*17652.23);
return float3(0.37,0.355,0.32)*(0.85+0.18*h+0.07*grain)*(1.0-0.38*grout);
''', .91)
surface('M_QuarterAsphalt', '''
float2 p=WorldPos.xy, b=floor(p/250.0), f=frac(p/250.0), w=f*f*(3.0-2.0*f);
float a=frac(sin(dot(b,float2(127.1,311.7)))*43758.5453);
float c=frac(sin(dot(b+float2(1,0),float2(127.1,311.7)))*43758.5453);
float d=frac(sin(dot(b+float2(0,1),float2(127.1,311.7)))*43758.5453);
float e=frac(sin(dot(b+float2(1,1),float2(127.1,311.7)))*43758.5453);
float macro=lerp(lerp(a,c,w.x),lerp(d,e,w.x),w.y);
float grain=frac(sin(dot(floor(p*1.5),float2(12.8,78.2)))*17652.23);
float cracks=(1.0-smoothstep(0.015,0.045,abs(sin(p.x*0.006+sin(p.y*0.004)*0.5))))*step(0.67,macro);
return float3(0.055,0.062,0.060)*(0.80+0.25*macro+0.14*grain)*(1.0-0.52*cracks);
''', .94)
mud=surface('M_QuarterMud', '''
float2 p=WorldPos.xy;
float n=frac(sin(dot(floor(p*.09),float2(12.8,78.2)))*43758.5453);
float rut=pow(abs(sin(p.x*.027+sin(p.y*.004)*.18)),18.0);
return lerp(float3(.055,.043,.029),float3(.12,.095,.055),n*.4+rut*.2);
''', .46)
mud_pos=LIB.create_material_expression(mud,unreal.MaterialExpressionWorldPosition,-900,600)
for output,code in [('roughness','''
float2 p=P.xy;
float pool=sin(p.x*.018+sin(p.y*.01))*cos(p.y*.013);
return lerp(.16,.87,smoothstep(-.3,.45,pool));
'''),('normal','''
float2 p=P.xy;
float rut=sin(p.x*.027+sin(p.y*.004)*.18);
float gravel=sin(p.x*.41)*cos(p.y*.37);
return normalize(float3(rut*.09+gravel*.035,cos(p.y*.027)*.04,1));
''')]:
    node=LIB.create_material_expression(mud,unreal.MaterialExpressionCustom,-550,600 if output=='roughness' else 820)
    node.set_editor_property('code',code)
    node.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT1 if output=='roughness' else unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    pin=unreal.CustomInput();pin.set_editor_property('input_name','P');node.set_editor_property('inputs',[pin])
    LIB.connect_material_expressions(mud_pos,'',node,'P')
    LIB.connect_material_property(node,'',unreal.MaterialProperty.MP_ROUGHNESS if output=='roughness' else unreal.MaterialProperty.MP_NORMAL)
LIB.recompile_material(mud);ASSETS.save_loaded_asset(mud)
surface('M_QuarterInterior','return float3(.19,.18,.155);',.94)
soot=surface('M_V3Soot','return float3(.008,.006,.004);',.98)
soot.set_editor_property('blend_mode',unreal.BlendMode.BLEND_MASKED)
uv=LIB.create_material_expression(soot,unreal.MaterialExpressionTextureCoordinate,-650,400)
edge=LIB.create_material_expression(soot,unreal.MaterialExpressionCustom,-350,400)
edge.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT1)
edge.set_editor_property('code','float2 p=(UV-.5)*2;return .8-dot(p,p)+sin(p.x*29)*sin(p.y*23)*.12;')
pin=unreal.CustomInput();pin.set_editor_property('input_name','UV');edge.set_editor_property('inputs',[pin])
LIB.connect_material_expressions(uv,'',edge,'UV');LIB.connect_material_property(edge,'',unreal.MaterialProperty.MP_OPACITY_MASK)
LIB.recompile_material(soot);ASSETS.save_loaded_asset(soot)
surface('M_V3WetEdge','return float3(.034,.039,.030);',.18)
foam=surface('M_V3Foam','''
float n=frac(sin(dot(floor(WorldPos.xy*.25),float2(127.1,311.7)))*43758.5453);
return float3(.56,.59,.51)*(0.5+n*.5);
''',.64)
foam.set_editor_property('blend_mode',unreal.BlendMode.BLEND_MASKED)
mask=LIB.create_material_expression(foam,unreal.MaterialExpressionCustom,-300,330)
mask.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT1)
mask.set_editor_property('code','return frac(sin(dot(floor(P.xy*.17+T*.8),float2(12.8,78.2)))*17652.23);')
pins=[]
for name in ['P','T']:
    pin=unreal.CustomInput();pin.set_editor_property('input_name',name);pins.append(pin)
mask.set_editor_property('inputs',pins)
wp=LIB.create_material_expression(foam,unreal.MaterialExpressionWorldPosition,-600,330)
tm=LIB.create_material_expression(foam,unreal.MaterialExpressionTime,-600,480)
LIB.connect_material_expressions(wp,'',mask,'P');LIB.connect_material_expressions(tm,'',mask,'T')
LIB.connect_material_property(mask,'',unreal.MaterialProperty.MP_OPACITY_MASK)
LIB.recompile_material(foam);ASSETS.save_loaded_asset(foam)
surface('M_V3RoadDamage','''
float2 p=WorldPos.xy;
float noise=frac(sin(dot(floor(p*.1),float2(12.8,78.2)))*43758.5453);
float crack=pow(saturate(1-abs(sin(p.x*.013+sin(p.y*.008)*1.3))),28);
return lerp(float3(.055,.059,.055)*(0.8+noise*.3),float3(.014,.01,.008),crack);
''',.97)
water = surface('M_QuarterWater', 'return float3(0.018,0.085,0.095);', .16)
water.set_editor_property('shading_model', unreal.MaterialShadingModel.MSM_SINGLE_LAYER_WATER)
opacity = LIB.create_material_expression(water, unreal.MaterialExpressionConstant, -180, -550)
opacity.set_editor_property('r', .18)
LIB.connect_material_property(opacity, '', unreal.MaterialProperty.MP_OPACITY)
# Changing the shading model can insert this output automatically. A second
# output silently falls back to the default grey material at runtime.
outputs = [node for node in LIB.get_material_expressions(water)
           if isinstance(node, unreal.MaterialExpressionSingleLayerWaterMaterialOutput)]
volume = outputs[0] if outputs else LIB.create_material_expression(water, unreal.MaterialExpressionSingleLayerWaterMaterialOutput, 100, -250)
for extra in outputs[1:]:LIB.delete_material_expression(water, extra)
for value, pin in [([.0015,.004,.0045], 'ScatteringCoefficients'),
                   ([.012,.004,.002], 'AbsorptionCoefficients')]:
    coefficient = LIB.create_material_expression(water, unreal.MaterialExpressionConstant3Vector, -180, -700)
    coefficient.set_editor_property('constant', unreal.LinearColor(*value, 1))
    if not LIB.connect_material_expressions(coefficient, '', volume, pin):
        raise RuntimeError('Water coefficient pin not found: ' + pin)
waves = LIB.create_material_expression(water, unreal.MaterialExpressionCustom, -300, -250)
waves.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT3)
waves.set_editor_property('code', '''
float2 p=WorldPos.xy;
float a=0.055*sin(p.x*0.015+Clock*0.9)+0.025*sin((p.x+p.y)*0.021-Clock*0.7);
float b=0.045*cos(p.y*0.013+Clock*1.1)+0.025*cos((p.x-p.y)*0.019+Clock*0.6);
return normalize(float3(a,b,1));
''')
inputs = []
for name in ['WorldPos','Clock']:
    pin = unreal.CustomInput();pin.set_editor_property('input_name',name);inputs.append(pin)
waves.set_editor_property('inputs',inputs)
position = LIB.create_material_expression(water,unreal.MaterialExpressionWorldPosition,-600,-250)
clock = LIB.create_material_expression(water,unreal.MaterialExpressionTime,-600,-400)
LIB.connect_material_expressions(position,'',waves,'WorldPos')
LIB.connect_material_expressions(clock,'',waves,'Clock')
LIB.connect_material_property(waves,'',unreal.MaterialProperty.MP_NORMAL)
assert len([node for node in LIB.get_material_expressions(water)
            if isinstance(node,unreal.MaterialExpressionSingleLayerWaterMaterialOutput)]) == 1
LIB.recompile_material(water);ASSETS.save_loaded_asset(water)

level = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
map_path = '/Game/Maps/RescueQuarter'
for asset in ['/Game/RescueAssets/User/Building/SM_Building',
              '/Game/RescueAssets/User/Rover/SM_Rover',
              '/Game/RescueAssets/Authored/Medical/SM_Medical']:
    if not ASSETS.does_asset_exist(asset):
        raise RuntimeError('Prepare and import rescue assets before building the quarter: ' + asset)
if ASSETS.does_asset_exist(map_path):
    if not level.load_level(map_path):
        raise RuntimeError('Cannot load quarter')
elif not level.new_level(map_path):
    raise RuntimeError('Cannot create quarter')
world_class = unreal.load_class(None, '/Script/MetaRescue.MRWorld')
world = next((a for a in actors.get_all_level_actors() if a.get_class() == world_class), None)
if world is None:
    world = actors.spawn_actor_from_class(world_class, unreal.Vector(0, 0, 0))
world.set_editor_property('rescue_quarter', True)
world.set_actor_label('MetaRescue / Authored Rescue Quarter')
world.build_scene()


def get_or_spawn(cls, location, rotation=unreal.Rotator(0, 0, 0)):
    actor = next((a for a in actors.get_all_level_actors() if isinstance(a, cls)), None)
    return actor if actor else actors.spawn_actor_from_class(cls, location, rotation)


sun = get_or_spawn(unreal.DirectionalLight, unreal.Vector(0, 0, 5000), unreal.Rotator(-38, -35, 0))
light = sun.get_component_by_class(unreal.DirectionalLightComponent)
light.set_mobility(unreal.ComponentMobility.MOVABLE)
light.set_intensity(35000)
light.set_light_color(unreal.LinearColor(1, .91, .80, 1))
light.set_atmosphere_sun_light(True)
light.set_editor_property('light_source_angle', 2.5)
get_or_spawn(unreal.SkyAtmosphere, unreal.Vector(0, 0, 0))
sky = get_or_spawn(unreal.SkyLight, unreal.Vector(0, 0, 3000))
sky_light = sky.get_component_by_class(unreal.SkyLightComponent)
sky_light.set_mobility(unreal.ComponentMobility.MOVABLE)
sky_light.set_real_time_capture(True)
sky_light.set_intensity(2.0)
fog = get_or_spawn(unreal.ExponentialHeightFog, unreal.Vector(0, 0, -200))
fog_component = fog.get_component_by_class(unreal.ExponentialHeightFogComponent)
fog_component.set_editor_property('fog_density', .004)
fog_component.set_editor_property('fog_height_falloff', .3)
fog_component.set_editor_property('enable_volumetric_fog', True)
post = get_or_spawn(unreal.PostProcessVolume, unreal.Vector(0, 0, 0))
post.set_editor_property('unbound', True)
settings = post.get_editor_property('settings')
for key, value in [('bloom_intensity', .15), ('vignette_intensity', .12), ('motion_blur_amount', 0),
                   ('auto_exposure_method', unreal.AutoExposureMethod.AEM_HISTOGRAM),
                   ('auto_exposure_min_brightness', 6.0), ('auto_exposure_max_brightness', 12.8),
                   ('auto_exposure_low_percent', 50.0), ('auto_exposure_high_percent', 80.0),
                   ('auto_exposure_speed_up', 4.0), ('auto_exposure_speed_down', 3.0),
                   ('auto_exposure_bias', 0), ('ambient_occlusion_intensity', .6),
                   ('lumen_front_layer_translucency_reflections',True)]:
    settings.set_editor_property('override_' + key, True)
    settings.set_editor_property(key, value)
post.set_editor_property('settings', settings)
get_or_spawn(unreal.PlayerStart, unreal.Vector(-4000, -4000, 600))
unreal.EditorLevelLibrary.set_level_viewport_camera_info(unreal.Vector(-4300, -4100, 6500), unreal.Rotator(-40, 45, 0))
if not level.save_current_level():
    raise RuntimeError('Cannot save quarter')
marker = Path(unreal.Paths.project_content_dir()) / 'Scenario/quarter-build.json'
marker.write_text(json.dumps({'map': map_path, 'ready': True, 'source': 'authored_3d_environment_v1'}), encoding='utf-8')
unreal.log('MR_RESCUE_QUARTER_SAVED')
