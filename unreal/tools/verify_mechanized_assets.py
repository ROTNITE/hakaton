"""Validate saved repaired mechanisms, animation curves, textures and source hashes."""
from pathlib import Path
import hashlib
import json
import math

import bpy


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/3d-world'
reports = []
inventory=json.loads((OUT/'asset-library/inventory.json').read_text(encoding='utf-8'))
for source in inventory['sources']:
    with (ROOT/source['source']).open('rb') as stream:
        assert hashlib.file_digest(stream,'sha256').hexdigest()==source['sha256'], 'Original source changed: '+source['source']
for path in sorted((ROOT / 'blender/prepared/v2').glob('*/asset.json')):
    asset = json.loads(path.read_text(encoding='utf-8'))
    name = asset['id']
    bpy.ops.wm.open_mainfile(filepath=str(path.parent / asset['blend']), load_ui=False)
    source = ROOT / asset['source']
    with source.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == asset['source_sha256'], name + ': original changed'
    assert bpy.context.scene.unit_settings.scale_length == 1
    assert bpy.context.scene.unit_settings.system == 'METRIC'
    objects = {o.name: o for o in bpy.context.scene.objects}
    assert len([o for o in objects.values() if o.type == 'MESH']) == len(asset['parts'])
    for part in asset['parts']:
        obj = objects[part['object']]
        assert obj.type == 'MESH' and len(obj.data.vertices), (name, obj.name)
        assert (path.parent / part['fbx']).is_file(), (name, obj.name)
        assert all(abs(s - 1) < 1e-5 for s in obj.scale), (name, obj.name, 'unapplied scale')
        assert obj.data.uv_layers, (name, obj.name, 'UV missing')
        assert all(math.isfinite(v) for vertex in obj.data.vertices for v in vertex.co)
        assert (obj.parent.name if obj.parent else None) == part['parent']
    for img in bpy.data.images:
        if img.type != 'IMAGE':
            continue
        assert not img.packed_file, (name, img.name, 'still packed')
        assert Path(bpy.path.abspath(img.filepath)).is_file(), (name, img.filepath)
    animated = [o for o in objects.values() if o.animation_data and o.animation_data.action]
    if name in {'Drone', 'Rover', 'Sensor', 'Case', 'Van'}:
        assert animated, name + ': no actual animated parts'
    for obj in animated:
        action = obj.animation_data.action
        curves = list(action.fcurves)
        assert curves and any(len(f.keyframe_points) >= 2 and
            max(k.co.y for k in f.keyframe_points) - min(k.co.y for k in f.keyframe_points) >
            (.00005 if f.data_path == 'location' else .01) for f in curves), (name, obj.name, 'empty action')
    for part in asset['parts']:
        if part['role'] == 'glass':
            mat = objects[part['object']].data.materials[0]
            shader = mat.node_tree.nodes.get('Principled BSDF')
            assert shader.inputs['Transmission Weight'].default_value > .9, (name, 'opaque glass')
    reports.append({'id': name, 'parts': len(asset['parts']), 'triangles': sum(p['triangles'] for p in asset['parts']),
                    'animated_parts': len(animated), 'source_preserved': True,
                    'glass_parts': sum(p['role'] == 'glass' for p in asset['parts'])})
rig_folder=ROOT/'blender/prepared/v2/MannequinRig'
rig_record=json.loads((rig_folder/'rig.json').read_text(encoding='utf-8'))
bpy.ops.wm.open_mainfile(filepath=str(rig_folder/rig_record['blend']),load_ui=False)
armatures=[o for o in bpy.context.scene.objects if o.type=='ARMATURE']
assert len(armatures)==1 and len(armatures[0].data.bones)==24
assert not any(o.name=='Icosphere' for o in bpy.context.scene.objects)
assert not armatures[0].animation_data.nla_tracks, 'Conflicting NLA tracks'
for clip in rig_record['clips']:
    assert (rig_folder/clip['fbx']).is_file()
    curves=bpy.data.actions[clip['name']].fcurves
    animated_bones={curve.data_path.split('].')[0] for curve in curves
                    if curve.data_path.endswith('.rotation_euler') and
                    max(k.co.y for k in curve.keyframe_points)-min(k.co.y for k in curve.keyframe_points)>.001}
    assert len(animated_bones)>=(8 if clip['name'] in {'Walking','Running'} else 2), (clip['name'],animated_bones)
for image in bpy.data.images:
    if image.type=='IMAGE':assert not image.packed_file and Path(bpy.path.abspath(image.filepath)).is_file(),image.name
result = {'passed': True, 'assets': reports,'original_source_files_verified':len(inventory['sources']),
          'rig':{'bones':24,'clips':[clip['name'] for clip in rig_record['clips']],'external_textures_verified':True}}
(OUT / 'mechanized-blender-verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print('MR_MECHANIZED_BLENDER_VERIFIED', json.dumps(reports))
