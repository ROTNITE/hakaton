"""Versioned UI-only materials: runtime ribbons and a shadow-free knowledge board."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

import unreal


FOLDER='/Game/RescueAssets/UIV1'
ASSETS=unreal.EditorAssetLibrary
TOOLS=unreal.AssetToolsHelpers.get_asset_tools()
EDIT=unreal.MaterialEditingLibrary
report={}

for name,ribbon in (('M_TelemetryRibbon',True),('M_KnowledgeBoard',False)):
    asset=unreal.load_asset(FOLDER+'/'+name)
    if asset is None:
        asset=TOOLS.create_asset(name,FOLDER,unreal.Material,unreal.MaterialFactoryNew())
        asset.set_editor_property('shading_model',unreal.MaterialShadingModel.MSM_UNLIT)
        asset.set_editor_property('two_sided',True)
        if ribbon:
            asset.set_editor_property('blend_mode',unreal.BlendMode.BLEND_TRANSLUCENT)
            color=EDIT.create_material_expression(asset,unreal.MaterialExpressionVertexColor,-600,0)
        else:
            color=EDIT.create_material_expression(asset,unreal.MaterialExpressionConstant3Vector,-600,0)
            color.set_editor_property('constant',unreal.LinearColor(.026,.038,.031,1))
        # Installed UE5.8 expression provides exposure-independent display colour.
        inverse=EDIT.create_material_expression(asset,unreal.MaterialExpressionEyeAdaptationInverse,-250,0)
        pins=EDIT.get_material_expression_input_names(inverse)
        # VertexColor's RGB output has no name in UE5.8. An empty pin selects
        # input/output zero, as implemented by MaterialEditingLibrary.
        assert pins and EDIT.connect_material_expressions(color,'',inverse,''),pins
        assert EDIT.connect_material_property(inverse,'',unreal.MaterialProperty.MP_EMISSIVE_COLOR)
        if ribbon:assert EDIT.connect_material_property(color,'A',unreal.MaterialProperty.MP_OPACITY)
        EDIT.recompile_material(asset)
        assert ASSETS.save_loaded_asset(asset)
    assert asset.get_editor_property('shading_model')==unreal.MaterialShadingModel.MSM_UNLIT
    node=EDIT.get_material_property_input_node(asset,unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    assert isinstance(node,unreal.MaterialExpressionEyeAdaptationInverse),'Existing derivative graph differs; create a new revision'
    if ribbon:
        assert asset.get_editor_property('blend_mode')==unreal.BlendMode.BLEND_TRANSLUCENT
        assert isinstance(EDIT.get_material_property_input_node(asset,unreal.MaterialProperty.MP_OPACITY),unreal.MaterialExpressionVertexColor)
    else:assert asset.get_editor_property('blend_mode')==unreal.BlendMode.BLEND_OPAQUE
    report[name]={'asset':asset.get_path_name(),'unlit':True,'exposure_compensated':True,
                  'blend_mode':str(asset.get_editor_property('blend_mode'))}

unreal.MRAssetTools.finish_asset_compilation()
for name,item in report.items():
    file=Path(unreal.Paths.project_content_dir())/'RescueAssets/UIV1'/(name+'.uasset')
    item['sha256']=hashlib.sha256(file.read_bytes()).hexdigest()
output=Path('D:/MetaRescue-output/city-assets');output.mkdir(parents=True,exist_ok=True)
path=output/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-mission-ui-v1.json')
path.write_text(json.dumps({'format':'metarescue.ui-materials.v1','materials':report,'visual_acceptance':False},indent=2)+'\n',encoding='utf-8')
unreal.log('MR_MISSION_UI_ASSETS_READY '+str(path))
