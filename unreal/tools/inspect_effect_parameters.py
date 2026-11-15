"""Read installed Niagara rapid-iteration inputs before configuring effects."""
from pathlib import Path
import unreal
root=Path(unreal.Paths.project_dir()).resolve().parents[1]
lines=[]
for name in ['ElectricalFire','CollapseDust','PipeLeak']:
    system=unreal.load_asset('/Game/Effects/NS_'+name)
    lines.extend([name,unreal.MRAssetTools.describe_effect(system)])
(root/'artifacts/quarter-v3/niagara-inputs.txt').write_text('\n'.join(lines),encoding='utf-8')
