"""Render actual saved repaired assets, including deployed/open poses."""
from pathlib import Path
import json
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_asset_library import preview


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'blender/prepared/v2'
names = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else ['Drone', 'Rover', 'Medical', 'Sensor', 'Case', 'Van']
for name in names:
    file = BASE / name / (name + '.blend')
    bpy.ops.wm.open_mainfile(filepath=str(file), load_ui=False)
    preview({'id': 'Repaired_' + name})
    bpy.context.scene.frame_set(100)
    scene = bpy.context.scene
    from mathutils import Vector
    camera = scene.camera
    # Return to a three-quarter view so opening/extension are actually visible.
    center = Vector((0, 0, 1))
    camera.location = center + Vector((4, -5, 3))
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    scene.render.filepath = str(ROOT / 'artifacts/3d-world/asset-library/previews' / ('Repaired_' + name) / 'operating.png')
    bpy.ops.render.render(write_still=True)
