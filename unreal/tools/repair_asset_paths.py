"""Repair early export relative paths using actual exported texture files."""
from pathlib import Path
import json
import math
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_blender_assets import render_preview, ROOT, OUT, PREVIEW


PREVIEW.mkdir(parents=True, exist_ok=True)
requested = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
for folder in sorted(OUT.iterdir()):
    record_path = folder / 'asset.json'
    if not record_path.is_file() or (requested and folder.name not in requested):
        continue
    record = json.loads(record_path.read_text(encoding='utf-8'))
    bpy.ops.wm.open_mainfile(filepath=str(OUT / record['blend']), load_ui=False)
    obj = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40), keep_sharp_edges=True)
    for image in bpy.data.images:
        if image.type == 'RENDER_RESULT':
            continue
        texture = folder / 'textures' / (image.name + '.png')
        if not texture.is_file():
            raise RuntimeError('Missing texture: ' + str(texture))
        image.filepath = str(texture)
        image.reload()
        image.filepath = '//textures/' + texture.name
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT / record['blend']), relative_remap=False)
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.fbx(filepath=str(OUT / record['fbx']), use_selection=True,
        object_types={'MESH'}, add_leaf_bones=False, apply_unit_scale=True,
        apply_scale_options='FBX_SCALE_UNITS', axis_forward='-Y', axis_up='Z',
        path_mode='RELATIVE', use_mesh_modifiers=True, bake_anim=False)
    size = max(obj.dimensions)
    render_preview(obj, folder.name + '-front', -.7, size)
    render_preview(obj, folder.name + '-rear', 2.4, size)
    print('MR_REPAIRED:', folder.name, flush=True)
