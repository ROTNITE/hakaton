"""Author ground-cover materials for CityV2 from world-scale textures in code."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import unreal


REVISION = 4 if '-MRCitySurfacesR4' in unreal.SystemLibrary.get_command_line() else 3 if '-MRCitySurfacesR3' in unreal.SystemLibrary.get_command_line() else 2
R3 = REVISION>=3
FOLDER = '/Game/RescueAssets/CityV2/SurfacesR'+str(REVISION)
OUTPUT = Path('D:/MetaRescue-output/city-assets')
ASSETS = unreal.EditorAssetLibrary
TOOLS = unreal.AssetToolsHelpers.get_asset_tools()
EDIT = unreal.MaterialEditingLibrary

# Colour varies on two scales. Grout uses a separate physically sized grid.
# The tiling pattern is procedural and introduces no external texture files.
GRAIN = '''
float2 p = Position.xy * 0.01;
float2 cell = floor(p * 0.55);
float2 f = frac(p * 0.55);
float2 w = f*f*(3.0-2.0*f);
float seed = dot(cell,float2(127.1,311.7));
float4 seeds = float4(seed,seed+127.1,seed+311.7,seed+438.8);
float4 samples = frac(sin(seeds)*43758.5453);
float patch = lerp(lerp(samples.x,samples.y,w.x),lerp(samples.z,samples.w,w.x),w.y);
float grains = frac(sin(dot(floor(p*65),float2(91.3,17.9)))*15731.7541);
'''
SURFACES = {
    'M_Yard': (.91, '''
float2 fTile = frac(p*1.2);
float edge = min(min(fTile.x,1-fTile.x),min(fTile.y,1-fTile.y));
float seam = 1.0 - smoothstep(.014,.038,edge);
return lerp(float3(.19,.185,.158),float3(.29,.28,.24),patch)*(.92+.12*grains)*(1-.37*seam);
'''),
    'M_Lawn': (.94, '''
return lerp(float3(.041,.063,.027),float3(.112,.143,.057),patch)*(.85+.30*grains);
'''),
    'M_Service': (.96, '''
return lerp(float3(.109,.103,.084),float3(.238,.224,.191),patch)*(.81+.38*grains);
'''),
    'M_Verge': (.99, '''
float mask = smoothstep(.31,.65,patch);
return lerp(float3(.115,.100,.076),float3(.074,.102,.043),mask)*(.9+.18*grains);
'''),
}

if R3:
    GRAIN = '''
float2 p = Position.xy * 0.01;
float2 q = p * .13;
float2 cell = floor(q), f = frac(q), w = f*f*(3.0-2.0*f);
float seed = dot(cell,float2(127.1,311.7));
float4 samples = frac(sin(float4(seed,seed+127.1,seed+311.7,seed+438.8))*43758.5453);
float coarse = lerp(lerp(samples.x,samples.y,w.x),lerp(samples.z,samples.w,w.x),w.y);
q = (p+float2(14.3,31.7))*.71;
cell = floor(q); f = frac(q); w = f*f*(3.0-2.0*f);
seed = dot(cell,float2(127.1,311.7));
samples = frac(sin(float4(seed,seed+127.1,seed+311.7,seed+438.8))*43758.5453);
float detail = lerp(lerp(samples.x,samples.y,w.x),lerp(samples.z,samples.w,w.x),w.y);
float patch = saturate(.76*coarse+.24*detail);
float grains = frac(sin(dot(floor(p*65),float2(91.3,17.9)))*15731.7541);
float footprint = max(length(ddx(p)),length(ddy(p)));
grains = lerp(.5,grains,1-smoothstep(.025,.12,footprint));
'''
    SURFACES['M_Verge']=(.99, '''
float mask = smoothstep(.28,.74,patch);
return lerp(float3(.108,.095,.074),float3(.069,.092,.044),mask)*(.94+.10*grains);
''')

if REVISION==4:
    # Hash the same integer corner through the same expression on both sides
    # of a cell. Adding a decimal offset to an already rounded dot product
    # changes its low bits and causes visible jumps after the sine hash.
    first='''float seed = dot(cell,float2(127.1,311.7));
float4 samples = frac(sin(float4(seed,seed+127.1,seed+311.7,seed+438.8))*43758.5453);'''
    second='''seed = dot(cell,float2(127.1,311.7));
samples = frac(sin(float4(seed,seed+127.1,seed+311.7,seed+438.8))*43758.5453);'''
    corners='''float4 keys = float4(dot(cell,float2(127.1,311.7)),
    dot(cell+float2(1,0),float2(127.1,311.7)),
    dot(cell+float2(0,1),float2(127.1,311.7)),
    dot(cell+float2(1,1),float2(127.1,311.7)));'''
    assert first in GRAIN and second in GRAIN
    GRAIN=GRAIN.replace(first,corners+'\nfloat4 samples = frac(sin(keys)*43758.5453);')
    GRAIN=GRAIN.replace(second,corners.replace('float4 keys','keys')+'\nsamples = frac(sin(keys)*43758.5453);')


def material(name, roughness, body):
    asset = unreal.load_asset(FOLDER+'/'+name)
    if asset is not None:
        if R3:
            node=EDIT.get_material_property_input_node(asset,unreal.MaterialProperty.MP_BASE_COLOR)
            assert (isinstance(node,unreal.MaterialExpressionCustom) and node.get_editor_property('code')==GRAIN+body), \
                'Existing derivative graph differs; use a new revision'
        return asset
    asset = TOOLS.create_asset(name, FOLDER, unreal.Material, unreal.MaterialFactoryNew())
    asset.set_editor_property('used_with_instanced_static_meshes', True)
    asset.set_editor_property('used_with_nanite', True)
    world = EDIT.create_material_expression(asset, unreal.MaterialExpressionWorldPosition, -660, 0)
    custom = EDIT.create_material_expression(asset, unreal.MaterialExpressionCustom, -330, 0)
    custom.set_editor_property('code', GRAIN + body)
    custom.set_editor_property('output_type', unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    pin = unreal.CustomInput()
    pin.set_editor_property('input_name', 'Position')
    custom.set_editor_property('inputs', [pin])
    assert EDIT.connect_material_expressions(world, '', custom, 'Position')
    assert EDIT.connect_material_property(custom, '', unreal.MaterialProperty.MP_BASE_COLOR)
    scalar = EDIT.create_material_expression(asset, unreal.MaterialExpressionConstant, -330, 220)
    scalar.set_editor_property('r', roughness)
    assert EDIT.connect_material_property(scalar, '', unreal.MaterialProperty.MP_ROUGHNESS)
    EDIT.recompile_material(asset)
    assert ASSETS.save_loaded_asset(asset)
    return asset


prior_graphs={}
if R3:
    for name in SURFACES:
        old=unreal.load_asset('/Game/RescueAssets/CityV2/SurfacesR2/'+name)
        node=EDIT.get_material_property_input_node(old,unreal.MaterialProperty.MP_BASE_COLOR)
        prior_graphs[name]=node.get_editor_property('code') if isinstance(node,unreal.MaterialExpressionCustom) else str(type(node))
surfaces = {name:material(name,*values) for name,values in SURFACES.items()}
unreal.MRAssetTools.finish_asset_compilation()
report = {}
for name, asset in surfaces.items():
    assert asset.get_editor_property('used_with_nanite')
    assert asset.get_editor_property('used_with_instanced_static_meshes')
    file = Path(unreal.Paths.project_content_dir()) / (FOLDER.removeprefix('/Game/')+'/'+name+'.uasset')
    report[name] = {'asset':asset.get_path_name(),'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
if R3:report={'revision':REVISION,'materials':report,'previous_graphs':prior_graphs,
              'new_graphs':{name:GRAIN+body for name,(_,body) in SURFACES.items()},'visual_acceptance':False}
OUTPUT.mkdir(parents=True,exist_ok=True)
target = OUTPUT / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-city-v2-surfaces.json')
with target.open('x',encoding='utf-8') as stream:
    json.dump(report,stream,indent=2)
unreal.log('MR_CITY_V2_SURFACES_READY '+str(target))
