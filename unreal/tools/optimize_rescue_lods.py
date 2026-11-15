"""Build actual distance-dependent render LODs without modifying collision LOD0."""
from pathlib import Path
import json
import sys

import unreal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_rescue_assets import configure_lods, ROOT

report = {}
for name in ['Rover', 'Drone', 'Stretcher', 'Building', 'WindowWall']:
    mesh = unreal.load_asset('/Game/RescueAssets/User/' + name + '/SM_' + name)
    if mesh is None:
        raise RuntimeError('Missing mesh: ' + name)
    report[name] = configure_lods(mesh)
(ROOT / 'artifacts/3d-world/render-lods.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
unreal.log('MR_RENDER_LODS_COMPLETE')
