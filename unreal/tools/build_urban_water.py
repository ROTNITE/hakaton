"""Build only the new flood material; preserve every prior fire/smoke asset."""
import hashlib
import json
import os
from pathlib import Path
import sys

import unreal
sys.path.insert(0,str(Path(__file__).resolve().parent))
from build_disaster_effects import ASSETS,FOLDER,material,node,vector,scalar,custom,property_input,connect,save


def main():
    manifest=Path(os.environ['MR_URBAN_WATER_ART_INPUTS']).resolve(strict=True)
    report=Path(os.environ['MR_URBAN_WATER_ART_REPORT']).resolve()
    if report.exists():raise ValueError('Preserve earlier water import evidence')
    sources=json.loads(manifest.read_bytes())
    if sources.get('format')!='metarescue.disaster-effects.sources.v1' or sources.get('revision')!=5:
        raise ValueError('Unsupported effect source manifest')
    row=sources['textures']['SmokeBillow']
    source=next(item for item in sources['sources'] if item['id']==row['source'])
    if source['license']!='CC0-1.0':raise ValueError('Foam detail must be open CC0')
    texture=unreal.load_asset(FOLDER+'/Textures/T_SmokeBillow')
    if not isinstance(texture,unreal.Texture2D):raise ValueError('Import the checked Kenney particle texture first')
    value=material('M_UrbanFlood')
    value.set_editor_property('shading_model',unreal.MaterialShadingModel.MSM_SINGLE_LAYER_WATER)
    world=node(value,unreal.MaterialExpressionWorldPosition,-1000,0)
    field=node(value,unreal.MaterialExpressionVertexColor,-1000,180)
    clock=scalar(value,'ModelTime',0,360)
    detail=node(value,unreal.MaterialExpressionTextureObject,-1000,540,texture=texture)
    color=custom(value,'''
float2 flow=(Field.rg*255-128)*(800.0/127);
float2 uv=(World.xy-flow*ModelTime*.45)*.0025;
float noise=Texture2DSample(Detail,DetailSampler,frac(uv)).a;
float depth=Field.b*4;
float shore=saturate((.22-depth)/.22)*smoothstep(.2,.7,noise);
float3 silt=lerp(float3(.055,.040,.022),float3(.095,.073,.040),noise*.35);
return lerp(silt,float3(.35,.32,.25),shore*.4);
''',unreal.CustomMaterialOutputType.CMOT_FLOAT3,
        [('World',world,''),('Field',field,''),('ModelTime',clock,''),('Detail',detail,'')],-300,0)
    property_input(color,'',value,unreal.MaterialProperty.MP_BASE_COLOR)
    normal=custom(value,'''
float2 flow=(Field.rg*255-128)*(800.0/127);
float2 p=World.xy-flow*ModelTime*.35;
float x=.026*sin(p.x*.014+ModelTime*.9)+.012*sin((p.x+p.y)*.023-ModelTime*.7);
float y=.023*cos(p.y*.013+ModelTime*1.1)+.012*cos((p.x-p.y)*.021+ModelTime*.6);
return normalize(float3(x,y,1));
''',unreal.CustomMaterialOutputType.CMOT_FLOAT3,
        [('World',world,''),('Field',field,''),('ModelTime',clock,'')],-300,400)
    property_input(normal,'',value,unreal.MaterialProperty.MP_NORMAL)
    for name,default,prop in (
        ('Roughness',.25,unreal.MaterialProperty.MP_ROUGHNESS),
        ('Specular',.4,unreal.MaterialProperty.MP_SPECULAR),
        ('Opacity',.25,unreal.MaterialProperty.MP_OPACITY)):
        property_input(scalar(value,name,default,700),'',value,prop)
    edit=unreal.MaterialEditingLibrary
    outputs=[item for item in edit.get_material_expressions(value)
             if isinstance(item,unreal.MaterialExpressionSingleLayerWaterMaterialOutput)]
    volume=outputs[0] if outputs else node(value,unreal.MaterialExpressionSingleLayerWaterMaterialOutput,200,300)
    for extra in outputs[1:]:edit.delete_material_expression(value,extra)
    for name,color,pin in (
        ('Scattering',(.008,.0062,.0035),'ScatteringCoefficients'),
        ('Absorption',(.018,.022,.033),'AbsorptionCoefficients')):
        connect(vector(value,name,color,900),'RGB',volume,pin)
    save(value);unreal.MRAssetTools.finish_asset_compilation()
    report.write_text(json.dumps({'format':'metarescue.urban-water.import.v1',
        'source_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
        'material':value.get_path_name(),'detail_texture':texture.get_path_name(),
        'texture_source':source,'world_position_offset':False},indent=2)+'\n',encoding='utf-8')
    unreal.log('MR_URBAN_WATER_IMPORTED '+str(report))


if __name__=='__main__':main()
