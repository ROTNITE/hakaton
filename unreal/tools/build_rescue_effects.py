"""Author project Niagara systems from installed Epic emitter templates."""
import unreal

tools = unreal.AssetToolsHelpers.get_asset_tools()
assets = unreal.EditorAssetLibrary
lib = unreal.MaterialEditingLibrary
assets.make_directory('/Game/Effects')

# A translucent swept disc replaces aliased individual blades at high RPM.
rotor = unreal.load_asset('/Game/Materials/M_RotorBlur') or tools.create_asset('M_RotorBlur','/Game/Materials',unreal.Material,unreal.MaterialFactoryNew())
lib.delete_all_material_expressions(rotor)
rotor.set_editor_property('blend_mode',unreal.BlendMode.BLEND_TRANSLUCENT)
rotor.set_editor_property('two_sided',True)
uv=lib.create_material_expression(rotor,unreal.MaterialExpressionTextureCoordinate,-600,0)
disc=lib.create_material_expression(rotor,unreal.MaterialExpressionCustom,-300,0)
disc.set_editor_property('output_type',unreal.CustomMaterialOutputType.CMOT_FLOAT1)
disc.set_editor_property('code','float2 p=(UV-.5)*2; float r=length(p); return smoothstep(.1,.22,r)*(1-smoothstep(.85,1,r))*.14;')
pin=unreal.CustomInput();pin.set_editor_property('input_name','UV');disc.set_editor_property('inputs',[pin])
lib.connect_material_expressions(uv,'',disc,'UV');lib.connect_material_property(disc,'',unreal.MaterialProperty.MP_OPACITY)
color=lib.create_material_expression(rotor,unreal.MaterialExpressionConstant3Vector,-300,160)
color.set_editor_property('constant',unreal.LinearColor(.065,.08,.075,1))
lib.connect_material_property(color,'',unreal.MaterialProperty.MP_BASE_COLOR)
lib.recompile_material(rotor);assets.save_loaded_asset(rotor)

beacon=unreal.load_asset('/Game/Effects/M_VanBeacon') or tools.create_asset('M_VanBeacon','/Game/Effects',unreal.Material,unreal.MaterialFactoryNew())
lib.delete_all_material_expressions(beacon)
tint=lib.create_material_expression(beacon,unreal.MaterialExpressionConstant3Vector,-500,0)
tint.set_editor_property('constant',unreal.LinearColor(.012,.08,.8,1))
power=lib.create_material_expression(beacon,unreal.MaterialExpressionScalarParameter,-500,170)
power.set_editor_property('parameter_name','Intensity');power.set_editor_property('default_value',1)
mult=lib.create_material_expression(beacon,unreal.MaterialExpressionMultiply,-200,0)
lib.connect_material_expressions(tint,'',mult,'A');lib.connect_material_expressions(power,'',mult,'B')
lib.connect_material_property(mult,'',unreal.MaterialProperty.MP_EMISSIVE_COLOR)
lib.connect_material_property(tint,'',unreal.MaterialProperty.MP_BASE_COLOR)
lib.recompile_material(beacon);assets.save_loaded_asset(beacon)

for name, tint, opacity, emitter in [
    ('ElectricalFire', (18000, 2400, 105), .65, 'Fountain'),
    ('CollapseDust', (.23, .19, .14), .18, 'HangingParticulates'),
    ('PipeLeak', (.18, .55, .65), .45, 'Fountain'),
]:
    path = '/Game/Effects/M_' + name
    mat = unreal.load_asset(path) or tools.create_asset('M_' + name, '/Game/Effects', unreal.Material, unreal.MaterialFactoryNew())
    lib.delete_all_material_expressions(mat)
    mat.set_editor_property('blend_mode', unreal.BlendMode.BLEND_TRANSLUCENT)
    mat.set_editor_property('shading_model', unreal.MaterialShadingModel.MSM_UNLIT if name=='ElectricalFire'
                            else unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
    if name!='ElectricalFire':mat.set_editor_property('translucency_lighting_mode',unreal.TranslucencyLightingMode.TLM_VOLUMETRIC_NON_DIRECTIONAL)
    mat.set_editor_property('two_sided', True)
    mat.set_editor_property('used_with_niagara_sprites', True)
    color = lib.create_material_expression(mat, unreal.MaterialExpressionConstant3Vector, -300, 0)
    color.set_editor_property('constant', unreal.LinearColor(*tint, 1))
    lib.connect_material_property(color, '', unreal.MaterialProperty.MP_EMISSIVE_COLOR if name=='ElectricalFire'
                                  else unreal.MaterialProperty.MP_BASE_COLOR)
    uv = lib.create_material_expression(mat, unreal.MaterialExpressionTextureCoordinate, -700, 200)
    shape = lib.create_material_expression(mat, unreal.MaterialExpressionCustom, -400, 200)
    shape.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT1)
    shape.set_editor_property('code', 'float2 d=(UV-float2(.5,.5))*2; return pow(saturate(1-dot(d,d)),2)*' + str(opacity) + ';')
    pin = unreal.CustomInput();pin.set_editor_property('input_name','UV');shape.set_editor_property('inputs',[pin])
    lib.connect_material_expressions(uv,'',shape,'UV')
    particle = lib.create_material_expression(mat, unreal.MaterialExpressionParticleColor, -700, 400)
    multiply = lib.create_material_expression(mat, unreal.MaterialExpressionMultiply, -100, 200)
    lib.connect_material_expressions(shape,'',multiply,'A');lib.connect_material_expressions(particle,'A',multiply,'B')
    lib.connect_material_property(multiply,'',unreal.MaterialProperty.MP_OPACITY)
    lib.recompile_material(mat);assets.save_loaded_asset(mat)
    system = unreal.MRAssetTools.create_effect('/Niagara/DefaultAssets/Templates/Emitters/' + emitter + '.' + emitter,
        '/Game/Effects/NS_' + name, mat)
    if system is None:raise RuntimeError('Could not create actual Niagara system: ' + name)
    assets.save_loaded_asset(system)
    unreal.log('MR_NIAGARA_EFFECT_CREATED ' + name)
