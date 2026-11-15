"""Inspect installed UE Python API names used by the authoring tools."""
import unreal
unreal.log('MR_WATER_ENUMS ' + str([n for n in dir(unreal.MaterialShadingModel) if 'WATER' in n]))
water = unreal.MaterialExpressionSingleLayerWaterMaterialOutput()
for i in range(4):
    unreal.log('MR_WATER_PIN ' + str(i) + ' ' + str(water.get_name()))
unreal.log('MR_NIAGARA_SYSTEMS ' + str([str(unreal.load_asset('/Game/Effects/NS_'+n)) for n in ['ElectricalFire','CollapseDust','PipeLeak']]))
