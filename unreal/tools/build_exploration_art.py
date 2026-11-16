"""Command-view matte: a new material, without rewriting the live-scene art."""
import json
import os
from pathlib import Path
import sys
import unreal

sys.path.insert(0,str(Path(__file__).resolve().parent))
from build_disaster_effects import node,custom,property_input,save

def main():
    report=Path(os.environ['MR_EXPLORATION_ART_REPORT']).resolve()
    if report.exists():raise ValueError('Preserve prior exploration-art evidence')
    folder='/Game/EffectsV3/ExplorationR1'
    unreal.EditorAssetLibrary.make_directory(folder)
    material=unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        'M_KnowledgeMatte',folder,unreal.Material,unreal.MaterialFactoryNew())
    if material is None:raise ValueError('Create a new revision instead of replacing a matte material')
    material.set_editor_property('material_domain',unreal.MaterialDomain.MD_POST_PROCESS)
    material.set_editor_property('blendable_location',unreal.BlendableLocation.BL_SCENE_COLOR_AFTER_TONEMAPPING)
    scene=node(material,unreal.MaterialExpressionSceneTexture,-800,0,scene_texture_id=unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0)
    stencil=node(material,unreal.MaterialExpressionSceneTexture,-800,200,scene_texture_id=unreal.SceneTextureId.PPI_CUSTOM_STENCIL)
    output=custom(material,'return lerp(float3(.008,.012,.011), Scene.rgb, step(.5, Stencil.r));',
        unreal.CustomMaterialOutputType.CMOT_FLOAT3,[('Scene',scene,'Color'),('Stencil',stencil,'Color')],-200,0)
    property_input(output,'',material,unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    save(material);unreal.MRAssetTools.finish_asset_compilation()
    report.write_text(json.dumps({'format':'metarescue.exploration-art.v1','material':material.get_path_name(),
        'stage':'after_tonemapping','basis':'only_copied_delivered_geometry_writes_stencil',
        'unknown_rgb':[.008,.012,.011]},indent=2)+'\n',encoding='utf-8')
    unreal.log('MR_EXPLORATION_ART_IMPORTED '+str(report))

if __name__=='__main__':main()
