"""Dedicated v3 effects, configured through verified installed Niagara inputs."""
from pathlib import Path
import json
import os
import re
import sys
import unreal

tools=unreal.AssetToolsHelpers.get_asset_tools()
assets=unreal.EditorAssetLibrary
lib=unreal.MaterialEditingLibrary
command_line = unreal.SystemLibrary.get_command_line()
selection = re.search(r'-MRQuarterEffects=([A-Za-z0-9_,]+)', command_line)
report_arg = re.search(r'-MRQuarterEffectsReport=(?:"([^"]+)"|([^ ]+))', command_line)
generate_surfaces = '-MRQuarterEventSurfaces' in command_line.split()
surfaces_only = '-MRQuarterSurfacesOnly' in command_line.split()
fab_manifest = os.environ.get('MR_FAB_EFFECTS_MANIFEST')
readable = '-MRQuarterReadableEffects' in command_line.split()
veils = '-MRQuarterVeils' in command_line.split()
if veils and (fab_manifest or readable or generate_surfaces or surfaces_only or selection):
    raise RuntimeError('Revision4 veils run separately from other effects')
if (fab_manifest or readable) and (generate_surfaces or surfaces_only or selection):
    raise RuntimeError('Revision3 effects run separately from the base event generator')
asset_dir = '/Game/EffectsV3/Revision2' if generate_surfaces or surfaces_only else '/Game/EffectsV3'
if readable or fab_manifest:
    asset_dir = '/Game/EffectsV3/Revision3'
if veils:
    asset_dir = '/Game/EffectsV3/Revision4'
fab_dir = asset_dir + '/Fab'
if readable or not fab_manifest:
    assets.make_directory(asset_dir)

# name, colour, opacity, rate, lifetime range, sprite cm range, launch cm/s range,
# acceleration, source radius. The renderer never owns the hazard state.
specs=[
 ('BuildingFire',(22000,2700,90),.75,40,1,1.8,35,90,30,100,(0,0,65),45),
 ('HeavySmoke',(.033,.031,.028),.31,15,7,11,100,210,25,65,(0,0,8),68),
 ('CollapseDust',(.28,.23,.17),.23,21,5,8,90,185,20,80,(0,0,-4),90),
 ('LowVisibility',(.36,.38,.37),.13,7,10,14,240,410,5,15,(0,0,0),130),
 ('Sparks',(42000,10000,700),.9,24,.45,.9,2.5,5.5,100,260,(0,0,-350),15),
 ('IgnitionFlash',(31000,10200,1250),.85,20,.11,.16,50,125,10,20,(0,0,0),12),
 ('PipeLeak',(.35,.51,.49),.5,95,.55,1.1,6,14,180,380,(0,0,-980),12),
 ('WheelSplash',(.095,.065,.038),.5,35,.3,.65,3,8,40,100,(0,0,-500),25),
]
selected = set(selection.group(1).split(',')) if selection else {spec[0] for spec in specs}
if unknown := selected - {spec[0] for spec in specs}:
    raise RuntimeError('Unknown Quarter effects: ' + ', '.join(sorted(unknown)))
if readable:
    specs = [
        ('BuildingFire',(22000,2700,90),.78,40,1,1.8,40,100,30,100,(0,0,65),50),
        ('HeavySmoke',(.030,.031,.032),.40,15,7,11,120,235,25,65,(0,0,8),78),
        ('LowVisibility',(.47,.51,.53),.20,7,10,14,230,410,5,15,(0,0,0),140),
    ]
else:
    specs = [] if surfaces_only or fab_manifest or veils else [spec for spec in specs if spec[0] in selected]

# Procedural sprite opacity. The plume edges move at different speeds so the
# overhead view separates turbulent smoke, ground dust and a broad fog veil.
shapes = {
    'BuildingFire': """
float y=1-UV.y;
float x=(UV.x-.5)*2 + sin(y*9-Clock*7)*.14;
float width=lerp(.83,.12,y);
float lobe=abs(x+.22*sin(y*12+Clock*8)) / max(.04,width);
float tongue=saturate(1-lobe);
float side=saturate(1-abs(x-.32*sin(y*7-Clock*6))/(width*.65));
return max(tongue,side*.63)*smoothstep(0,.16,y)*(1-smoothstep(.65,1,y))*ALPHA;
""",
    'HeavySmoke': """
float2 p=(UV-.5)*2;
float broad=sin(p.x*6+p.y*9+Clock*.83)*sin(p.y*8-p.x*6-Clock*.68);
float small=sin(p.x*18-p.y*12+Clock*1.2)*cos(p.y*16+p.x*11-Clock);
return pow(saturate(1-dot(p,p)+.28*broad+.07*small),1.7)*ALPHA;
""",
    'CollapseDust': """
float2 p=(UV-.5)*2;
float billows=cos(p.x*10+Clock*.52)*sin(p.y*7-p.x*4-Clock*.6);
float grit=sin(p.x*25+p.y*21)*cos(p.y*19-p.x*17);
return pow(saturate(1-dot(p,p)+.23*billows+.09*grit),1.4)*ALPHA;
""",
    'LowVisibility': """
float2 p=(UV-.5)*2;
float band=sin(p.y*6+p.x*3-Clock*.38);
return pow(saturate(1-dot(p,p)),1.35)*(.75+.25*band)*ALPHA;
""",
    'Sparks': """
float2 p=(UV-.5)*2;
return pow(saturate(1-dot(p,p*float2(5,.85))),2.1)*ALPHA;
""",
}
soft_droplet = """
float2 p=(UV-.5)*2;
float ripples=sin(p.x*13+p.y*9+Clock*2)*sin(p.y*15-p.x*7-Clock*1.7);
return pow(saturate(1-dot(p,p)-ripples*.12),2)*ALPHA;
"""
niagara_readback = {}
for name,tint,alpha,rate,lo,hi,slo,shi,vlo,vhi,gravity,radius in specs:
    mat=unreal.load_asset(asset_dir+'/M_'+name) or tools.create_asset('M_'+name,asset_dir,unreal.Material,unreal.MaterialFactoryNew())
    lib.delete_all_material_expressions(mat)
    mat.set_editor_property('blend_mode',unreal.BlendMode.BLEND_TRANSLUCENT)
    luminous=name in {'BuildingFire','Sparks','IgnitionFlash'}
    mat.set_editor_property('shading_model',unreal.MaterialShadingModel.MSM_UNLIT if luminous else unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
    mat.set_editor_property('two_sided',True);mat.set_editor_property('used_with_niagara_sprites',True)
    if not luminous:mat.set_editor_property('translucency_lighting_mode',unreal.TranslucencyLightingMode.TLM_VOLUMETRIC_NON_DIRECTIONAL)
    uv=lib.create_material_expression(mat,unreal.MaterialExpressionTextureCoordinate,-850,100)
    clock=lib.create_material_expression(mat,unreal.MaterialExpressionTime,-850,280)
    shape=lib.create_material_expression(mat,unreal.MaterialExpressionCustom,-550,130)
    shape.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT1)
    code=shapes.get(name,soft_droplet).replace('ALPHA',str(alpha))
    shape.set_editor_property('code',code)
    pins=[]
    for pin_name in ['UV','Clock']:
        pin=unreal.CustomInput();pin.set_editor_property('input_name',pin_name);pins.append(pin)
    shape.set_editor_property('inputs',pins)
    lib.connect_material_expressions(uv,'',shape,'UV');lib.connect_material_expressions(clock,'',shape,'Clock')
    particle=lib.create_material_expression(mat,unreal.MaterialExpressionParticleColor,-850,450)
    opacity=lib.create_material_expression(mat,unreal.MaterialExpressionMultiply,-220,180)
    lib.connect_material_expressions(shape,'',opacity,'A');lib.connect_material_expressions(particle,'A',opacity,'B')
    fade=lib.create_material_expression(mat,unreal.MaterialExpressionScalarParameter,-250,400)
    fade.set_editor_property('parameter_name','Fade');fade.set_editor_property('default_value',1)
    faded=lib.create_material_expression(mat,unreal.MaterialExpressionMultiply,20,180)
    lib.connect_material_expressions(opacity,'',faded,'A');lib.connect_material_expressions(fade,'',faded,'B')
    lib.connect_material_property(faded,'',unreal.MaterialProperty.MP_OPACITY)
    if name=='BuildingFire':
        color=lib.create_material_expression(mat,unreal.MaterialExpressionCustom,-300,-100)
        color.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT3)
        color.set_editor_property('inputs',pins)
        color.set_editor_property('code',"""
float y=1-UV.y;
float x=(UV.x-.5)*2;
float hot=saturate((1-abs(x)*1.8)*(1-y*.85));
hot *= .8+.2*sin(Clock*10+y*14);
return lerp(float3(9000,580,14),float3(22000,7200,370),hot);
""")
        lib.connect_material_expressions(uv,'',color,'UV')
        lib.connect_material_expressions(clock,'',color,'Clock')
    else:
        color=lib.create_material_expression(mat,unreal.MaterialExpressionConstant3Vector,-300,-100)
        color.set_editor_property('constant',unreal.LinearColor(*tint,1))
    lib.connect_material_property(color,'',unreal.MaterialProperty.MP_EMISSIVE_COLOR if luminous else unreal.MaterialProperty.MP_BASE_COLOR)
    lib.recompile_material(mat)
    if not assets.save_loaded_asset(mat):
        raise RuntimeError('Could not save Quarter effect material: ' + name)
    system=unreal.MRAssetTools.create_effect('/Niagara/DefaultAssets/Templates/Emitters/Fountain.Fountain',asset_dir+'/NS_'+name,mat)
    if system is None:raise RuntimeError('Niagara creation failed: '+name)
    unreal.MRAssetTools.configure_effect(system,rate,lo,hi,slo,shi,vlo,vhi,unreal.Vector(*gravity),radius)
    if not assets.save_loaded_asset(system):
        raise RuntimeError('Could not save Quarter effect system: ' + name)
    if generate_surfaces or readable:
        niagara_readback[name] = unreal.MRAssetTools.describe_effect(system)
    unreal.log('MR_V3_EFFECT '+name)
def custom_node(mat, code, output_type, inputs, column, row):
    node = lib.create_material_expression(mat, unreal.MaterialExpressionCustom, column, row)
    node.set_editor_property('code', code)
    node.set_editor_property('output_type', output_type)
    pins = []
    for name, _, _ in inputs:
        pin = unreal.CustomInput()
        pin.set_editor_property('input_name', name)
        pins.append(pin)
    node.set_editor_property('inputs', pins)
    for name, value, output in inputs:
        if not lib.connect_material_expressions(value, output, node, name):
            raise RuntimeError('Could not connect surface input: ' + name)
    return node


def build_surface(name, properties, *, masked=False, water=False, asphalt_texture=None, folder=None):
    # Keep event surfaces independent of the static basin and the authored map.
    folder = folder or asset_dir
    path = folder + '/M_' + name
    mat = unreal.load_asset(path) or tools.create_asset(
        'M_' + name, folder, unreal.Material, unreal.MaterialFactoryNew())
    if mat is None:
        raise RuntimeError('Could not create surface material: ' + name)
    lib.delete_all_material_expressions(mat)
    mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_MASKED if masked else unreal.BlendMode.BLEND_OPAQUE)
    mat.set_editor_property('shading_model', unreal.MaterialShadingModel.MSM_SINGLE_LAYER_WATER if water else unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
    position = lib.create_material_expression(mat, unreal.MaterialExpressionWorldPosition, -850, 20)
    color = lib.create_material_expression(mat, unreal.MaterialExpressionVertexColor, -850, 160)
    clock = lib.create_material_expression(mat, unreal.MaterialExpressionTime, -850, 300)
    available = {'P': (position, ''), 'Surface': (color, ''), 'Clock': (clock, '')}
    if asphalt_texture is not None:
        uv = custom_node(mat, 'return P.xy / 200.0;', unreal.CustomMaterialOutputType.CMOT_FLOAT2,
                         [('P', position, '')], -660, 480)
        sample = lib.create_material_expression(mat, unreal.MaterialExpressionTextureSample, -460, 480)
        sample.set_editor_property('texture', asphalt_texture)
        sample.set_editor_property('sampler_type', unreal.MaterialSamplerType.SAMPLERTYPE_COLOR)
        if not lib.connect_material_expressions(uv, '', sample, 'UVs'):
            raise RuntimeError('Could not bind world coordinates to the asphalt texture')
        available['FabColor'] = (sample, 'RGB')
    for row, (prop, vector, code, inputs) in enumerate(properties):
        value = custom_node(mat, code, unreal.CustomMaterialOutputType.CMOT_FLOAT3 if vector else
                            unreal.CustomMaterialOutputType.CMOT_FLOAT1,
                            [(name, *available[name]) for name in inputs], -460, row * 210)
        if not lib.connect_material_property(value, '', prop):
            raise RuntimeError('Could not connect surface property: ' + str(prop))
    if water:
        outputs = [node for node in lib.get_material_expressions(mat)
                   if isinstance(node, unreal.MaterialExpressionSingleLayerWaterMaterialOutput)]
        volume = outputs[0] if outputs else lib.create_material_expression(
            mat, unreal.MaterialExpressionSingleLayerWaterMaterialOutput, 80, 440)
        for extra in outputs[1:]:
            lib.delete_material_expression(mat, extra)
        scattering = (.0022,.0070,.0083) if veils else (.0022,.0057,.0062) if readable else (.0019,.0045,.0048)
        absorption = (.015,.0042,.0019) if veils else (.012,.0044,.0022) if readable else (.010,.0041,.0023)
        for value, pin in [(scattering, 'ScatteringCoefficients'), (absorption, 'AbsorptionCoefficients')]:
            coefficient = lib.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -460, 860)
            coefficient.set_editor_property('constant', unreal.LinearColor(*value, 1))
            if not lib.connect_material_expressions(coefficient, '', volume, pin):
                raise RuntimeError('Could not connect water volume input: ' + pin)
    lib.recompile_material(mat)
    if not assets.save_loaded_asset(mat):
        raise RuntimeError('Could not save Quarter event surface: ' + name)
    unreal.log('MR_V3_SURFACE ' + name)
    return path


surface_paths = []
fab_result = None
asphalt_texture = None
if fab_manifest:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from import_fab_effects import import_effect_sources
    asphalt_texture, fab_result = import_effect_sources(Path(fab_manifest).resolve(strict=True), fab_dir)
if generate_surfaces or surfaces_only or fab_manifest:
    mp = unreal.MaterialProperty
    fracture = """
float2 xy=P.xy*.01;
float2 p=float2(dot(xy,float2(.92,.39)),dot(xy,float2(-.39,.92)));
float drift=p.y*.23 + .24*sin(p.x*.83) + .12*sin(p.x*2.42);
float mainCrack=abs(frac(drift)-.5)*4.3;
float branch=abs(frac(drift+p.x*.155+.18*sin(p.x*1.73))-.5)*5.5;
float fork=smoothstep(.35,.72,sin(p.x*1.48+p.y*.83)*.5+.5);
float width=.065+.10*(sin(p.x*2.37+p.y*.95)*.5+.5);
float closest=min(mainCrack,branch+lerp(.24,0,fork));
float body=(1-smoothstep(width,width+.12,closest))*smoothstep(.02,.33,Surface.g);
"""
    base_inputs = ('P','Surface')
    shoulder = 'float3(.16,.133,.098)'
    if asphalt_texture is not None:
        base_inputs += ('FabColor',)
        shoulder = 'lerp(float3(.16,.133,.098),FabColor,.55)'
    base_color = fracture+"""
float core=1-smoothstep(width*.38,width*.94,closest);
float chips=.7+.3*sin(p.x*13)*sin(p.y*18);
return lerp(SHOULDER*chips,float3(.007,.005,.004),core);
""".replace('SHOULDER',shoulder)
    surface_paths.append(build_surface('EventFracture', [
        (mp.MP_BASE_COLOR, True, base_color, base_inputs),
        (mp.MP_OPACITY_MASK, False, fracture+"return body;", ('P','Surface')),
        (mp.MP_ROUGHNESS, False, "return .94;", ()),
    ], masked=True, asphalt_texture=asphalt_texture, folder=fab_dir if fab_manifest else asset_dir))

if generate_surfaces or surfaces_only:
    mud = """
float2 p=P.xy*.01;
float s=sin(p.x*.74+cos(p.y*.62)*1.3);
float fine=sin(p.x*5.6+p.y*3.9)*sin(p.y*6.4-p.x*1.5);
float damp=smoothstep(-.18,.65,s*.65+fine*.24+cos(p.y*.81)*.24);
"""
    surface_paths.append(build_surface('EventMud', [
        (mp.MP_BASE_COLOR, True, mud+"""
float grain=sin(p.x*36.1)*cos(p.y*42.8)*.05;
return lerp(float3(.24,.139,.066),float3(.091,.055,.029),damp)*(1+grain);
""", ('P',)),
        (mp.MP_ROUGHNESS, False, mud+"return lerp(.91,.32,damp);", ('P',)),
        (mp.MP_OPACITY_MASK, False, mud+"""
float ragged=sin(p.x*7.7+p.y*2.4)*sin(p.y*6.3-p.x*2.8)*.19;
return smoothstep(.01,.62,Surface.g+ragged);
""", ('P','Surface')),
    ], masked=True))

if generate_surfaces or surfaces_only or readable or veils:
    mp = unreal.MaterialProperty
    surface_paths.append(build_surface('EventFlood', [
        (mp.MP_BASE_COLOR, True, """
float depth=saturate((P.z-(Surface.r*155-100))/42);
float2 p=P.xy*.01;
float silt=sin(p.x*.71+p.y*.34+Clock*.38)*sin(p.y*1.02-p.x*.56-Clock*.3);
float3 shallow=WATER_SHALLOW+silt*float3(.017,.011,.005);
float3 deep=WATER_TINT+silt*WATER_RIPPLE;
return lerp(shallow,deep,smoothstep(.06,.78,depth))*lerp(.8,1,Surface.g);
""".replace('WATER_SHALLOW', 'float3(.095,.15,.158)' if veils else 'float3(.17,.123,.063)'
     ).replace('WATER_TINT', 'float3(.031,.192,.238)' if veils else 'float3(.032,.138,.159)' if readable else 'float3(.029,.093,.096)'
     ).replace('WATER_RIPPLE', 'float3(.011,.025,.031)' if veils else 'float3(.008,.020,.024)' if readable else 'float3(.005,.013,.014)'), ('P','Surface','Clock')),
        (mp.MP_NORMAL, True, """
float2 p=P.xy*.01;
float x=sin(p.x*2.31+p.y*.42+Clock*1.2)*.10+sin(p.x*4.6-p.y*2.1-Clock*.8)*.028;
float y=cos(p.y*1.8+p.x*.33-Clock*.98)*.084+sin(p.x*3.8+p.y*4.1+Clock*.7)*.024;
return normalize(float3(x,y,1));
""", ('P','Clock')),
        (mp.MP_ROUGHNESS, False, "return lerp(.37,.18,Surface.g);", ('Surface',)),
        (mp.MP_OPACITY, False, "return .43;" if veils else "return .31;" if readable else "return .21;", ()),
    ], water=True))

if generate_surfaces or surfaces_only or readable:
    surface_paths.append(build_surface('EventFoam', [
        (mp.MP_BASE_COLOR, True, "return float3(.61,.64,.54);", ()),
        (mp.MP_ROUGHNESS, False, "return .66;", ()),
        (mp.MP_OPACITY_MASK, False, """
float2 p=P.xy*.01;
float waves=sin(p.x*11.7+p.y*9.6+Clock*1.05)*sin(p.y*14.4-p.x*6.3-Clock*.6);
float gaps=sin(p.x*1.31+p.y*1.71+Clock*.33);
return smoothstep(.10,.47,waves*.55+gaps*.35);
""".replace('.10,.47,waves*.55+gaps*.35', '.02,.44,waves*.48+gaps*.45' if readable else '.10,.47,waves*.55+gaps*.35'), ('P','Clock')),
    ], masked=True))

if generate_surfaces or surfaces_only:
    surface_paths.append(build_surface('EventWetEdge', [
        (mp.MP_BASE_COLOR, True, "return float3(.061,.053,.036);", ()),
        (mp.MP_ROUGHNESS, False, "return .26;", ()),
        (mp.MP_OPACITY_MASK, False, """
float2 p=P.xy*.01;
float n=sin(p.x*6.4+p.y*1.8)*sin(p.y*6.6-p.x*2.4);
return smoothstep(-.62,-.19,n);
""", ('P',)),
    ], masked=True))

def build_event_veil(name, tint, density, pattern):
    path = asset_dir + '/' + name
    material = unreal.load_asset(path) or tools.create_asset(name, asset_dir, unreal.Material, unreal.MaterialFactoryNew())
    if material is None:
        raise RuntimeError('Could not create event veil: ' + name)
    lib.delete_all_material_expressions(material)
    material.set_editor_property('blend_mode', unreal.BlendMode.BLEND_TRANSLUCENT)
    material.set_editor_property('shading_model', unreal.MaterialShadingModel.MSM_UNLIT)
    position = lib.create_material_expression(material, unreal.MaterialExpressionWorldPosition, -850, 20)
    clock = lib.create_material_expression(material, unreal.MaterialExpressionTime, -850, 160)
    colors = lib.create_material_expression(material, unreal.MaterialExpressionVertexColor, -850, 300)
    view = lib.create_material_expression(material, unreal.MaterialExpressionCameraVectorWS, -850, 440)
    fade = lib.create_material_expression(material, unreal.MaterialExpressionScalarParameter, -850, 570)
    fade.set_editor_property('parameter_name', 'Fade')
    fade.set_editor_property('default_value', 0.0)
    opacity = custom_node(material, VEIL_ALPHA.replace('DENSITY', str(density)).replace('PATTERN', pattern),
        unreal.CustomMaterialOutputType.CMOT_FLOAT1,
        [('P', position, ''), ('Clock', clock, ''), ('Surface', colors, ''),
         ('View', view, ''), ('Fade', fade, '')], -420, 160)
    shade = lib.create_material_expression(material, unreal.MaterialExpressionConstant3Vector, -620, -180)
    shade.set_editor_property('constant', unreal.LinearColor(*tint, 1))
    inverse = lib.create_material_expression(material, unreal.MaterialExpressionEyeAdaptationInverse, -300, -180)
    if not lib.connect_material_expressions(shade, '', inverse, '') or not lib.connect_material_property(
            inverse, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR):
        raise RuntimeError('Could not bind exposure-compensated veil colour: ' + name)
    if not lib.connect_material_property(opacity, '', unreal.MaterialProperty.MP_OPACITY):
        raise RuntimeError('Could not bind veil opacity: ' + name)
    lib.recompile_material(material)
    if not assets.save_loaded_asset(material):
        raise RuntimeError('Could not save event veil: ' + name)
    unreal.log('MR_V3_SURFACE ' + name)
    return path


VEIL_ALPHA = """
float2 p=P.xy*.01;
float overhead=smoothstep(.70,.92,View.z);
float footprint=smoothstep(0,.64,Surface.g);
float density=PATTERN;
return DENSITY*overhead*footprint*saturate(Fade)*density;
"""
if veils:
    surface_paths.append(build_event_veil('M_EventSmokeVeil', (.035,.045,.051), .50, """
        .54+.46*smoothstep(-.55,.66,sin(p.x*.90+p.y*.45-Clock*.58)*cos(p.y*.78-p.x*.31+Clock*.37)
        +.3*sin(p.x*2.3+p.y*1.9-Clock*.74))
    """))
    surface_paths.append(build_event_veil('M_EventFogVeil', (.49,.66,.73), .40, """
        .60+.40*smoothstep(-.65,.85,sin(p.x*.36+p.y*.68+Clock*.29)*cos(p.y*.40-p.x*.31-Clock*.22))
    """))

root=Path(unreal.Paths.project_dir()).resolve().parents[1]
if report_arg:
    report=Path(report_arg.group(1) or report_arg.group(2))
elif not selection and not surface_paths:
    report=root/'artifacts/quarter-v3/effect-specs.json'
else:
    report=None
if report:
    report.parent.mkdir(parents=True,exist_ok=True)
    data = {'asset_dir': asset_dir, 'niagara': specs, 'niagara_readback': niagara_readback,
            'surface_materials': surface_paths} if surface_paths else specs
    if fab_result is not None:
        data['fab'] = fab_result
    report.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
