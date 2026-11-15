"""Preserve supplied walking/running rig and author rescue-appropriate lying breathing."""
from pathlib import Path
import json
import math
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_mechanized_assets as rig


ROOT = rig.ROOT
source = next((ROOT / 'blender').glob('*animated_mixamo*.glb'))
folder = rig.OUT / 'MannequinRig'
folder.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source))
arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
bone_count = len(arm.data.bones)
arm.rotation_mode = 'XYZ'
body = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o.parent == arm)
for obj in list(bpy.data.objects):
    if obj not in {arm, body}:
        bpy.data.objects.remove(obj, do_unlink=True)
actions = list(bpy.data.actions)
for action in actions:action.use_fake_user = True
arm.animation_data_clear()
for bone in arm.pose.bones:
    bone.rotation_mode = 'XYZ'
    bone.rotation_euler = (0, 0, 0)
    bone.location = (0, 0, 0)
arm.data.pose_position = 'REST'
bpy.context.view_layer.update()
height = body.dimensions.z
factor = 1.75 / height
arm.scale *= factor
rig.activate(arm)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
rig.activate(body)
# Decimate bind geometry with the armature disabled, keeping weighted vertices.
modifier = next(m for m in body.modifiers if m.type == 'ARMATURE')
modifier.show_viewport = False
mod = body.modifiers.new('WeightedGameMesh', 'DECIMATE')
body.data.calc_loop_triangles()
mod.ratio = 24000 / len(body.data.loop_triangles)
mod.use_collapse_triangulate = True
bpy.ops.object.modifier_apply(modifier=mod.name)
modifier.show_viewport = True
bpy.ops.object.shade_smooth_by_angle(angle=math.radians(50), keep_sharp_edges=False)
arm.name = 'RescueMannequin_Rig'
body.name = 'RescueMannequin_Skin'
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 1
scene.render.fps = 30
arm.data.pose_position = 'POSE'
clips = []
for action in actions:
    arm.animation_data_create()
    arm.animation_data.action = action
    arm.animation_data.action_slot = action.slots[0]
    # Eliminate root translation from supplied walk/run loops: locomotion comes
    # from the actor path in Unreal. Preserve small pelvis movement vertically.
    for curve in action.fcurves:
        if curve.data_path.endswith('.location') and 'Hips' in curve.data_path and curve.array_index in {0, 2}:
            for key in curve.keyframe_points:key.co.y = 0
    # glTF stores bone rotations as quaternions. Simply changing rotation_mode
    # to XYZ suppresses those channels and exports a rigid body with moving hips.
    # Sample their real poses before converting to editable Euler channels.
    quaternion_bones = {bone.name for bone in arm.pose.bones
                        if any(curve.data_path == bone.path_from_id('rotation_quaternion') for curve in action.fcurves)}
    for bone in arm.pose.bones:
        bone.rotation_mode = 'QUATERNION' if bone.name in quaternion_bones else 'XYZ'
    samples=[];previous={}
    for frame in range(math.floor(action.frame_range.x),math.ceil(action.frame_range.y)+1):
        scene.frame_set(frame)
        angles={}
        for name in quaternion_bones:
            quaternion=arm.pose.bones[name].rotation_quaternion
            angles[name]=quaternion.to_euler('XYZ',previous[name]) if name in previous else quaternion.to_euler('XYZ')
        previous=angles;samples.append((frame,angles))
    for curve in list(action.fcurves):
        if curve.data_path.endswith('.rotation_quaternion'):action.fcurves.remove(curve)
    for bone in arm.pose.bones:bone.rotation_mode='XYZ'
    for frame,angles in samples:
        for name,angle in angles.items():
            bone=arm.pose.bones[name];bone.rotation_euler=angle
            bone.keyframe_insert(data_path='rotation_euler',frame=frame,group=name)
    clips.append({'name': action.name, 'frames': list(action.frame_range), 'source': 'supplied_glb'})
arm.animation_data_clear()
for bone in arm.pose.bones:
    bone.rotation_euler = (0, 0, 0)
    bone.location = (0, 0, 0)
# Breathing is deliberately subtle and local. Posture/root alignment are applied
# when creating the stretcher pose; no walking animation is used for a casualty.
for frame, chest, head in [(1, 0, 0), (31, .012, -.006), (61, 0, 0), (91, -.006, .003), (121, 0, 0)]:
    for name, angle in [('mixamorig:Spine2', chest), ('mixamorig:Neck', head)]:
        bone = arm.pose.bones[name]
        bone.rotation_euler.x = angle
        bone.keyframe_insert(data_path='rotation_euler', frame=frame, group=name)
breathing = arm.animation_data.action
breathing.name = 'CasualtyBreathing'
breathing.use_fake_user = True
clips.append({'name': breathing.name, 'frames': list(breathing.frame_range), 'source': 'authored_subtle_rescue_idle'})
scene.frame_start, scene.frame_end = 1, 121
scene.frame_set(1)
materials = rig.export_materials(folder)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'MannequinRig.blend'), relative_remap=False)
def export(file, animated):
    bpy.ops.object.select_all(action='DESELECT')
    body.select_set(True);arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.fbx(filepath=str(folder / file), use_selection=True,
        object_types={'MESH', 'ARMATURE'}, add_leaf_bones=False, use_armature_deform_only=True,
        apply_unit_scale=True, apply_scale_options='FBX_SCALE_UNITS', axis_forward='-Y', axis_up='Z',
        path_mode='RELATIVE', mesh_smooth_type='FACE', bake_anim=animated, bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=False, bake_anim_simplify_factor=0, bake_anim_step=1)
export('MannequinRig.fbx', False)
for clip in clips:
    action = bpy.data.actions[clip['name']]
    arm.animation_data.action = action
    arm.animation_data.action_slot = action.slots[0]
    scene.frame_start = round(action.frame_range.x)
    scene.frame_end = max(scene.frame_start + 1, math.ceil(action.frame_range.y))
    export(clip['name'] + '.fbx', True)
    clip['fbx'] = clip['name'] + '.fbx'
# A static, relaxed supine skin for the stretcher is derived from the same rig.
arm.animation_data.action = breathing
arm.animation_data.action_slot = breathing.slots[0]
scene.frame_set(1)
# Fit the existing weighted arms alongside the torso rather than leave the
# supplied A-pose overhanging the 60 cm stretcher. Solve using the actual hand
# positions; GLB bone local axes are asymmetric and cannot share guessed angles.
for side, sign in [('Left', 1), ('Right', -1)]:
    bone = arm.pose.bones['mixamorig:' + side + 'Arm']
    hand = arm.pose.bones['mixamorig:' + side + 'Hand']
    best = None
    for ix in range(-10, 11):
        for iz in range(-10, 11):
            bone.rotation_euler = (ix * .045, 0, iz * .045)
            bpy.context.view_layer.update()
            p = arm.matrix_world @ hand.head
            score = (p.x - sign * .22) ** 2 + (p.z - .76) ** 2 * .15 + p.y ** 2 * .2
            if best is None or score < best[0]:best = (score, ix * .045, iz * .045)
    bone.rotation_euler = (best[1], 0, best[2])
arm.rotation_euler = (-math.pi / 2, 0, math.pi / 2)
bpy.context.view_layer.update()
deps = bpy.context.evaluated_depsgraph_get()
mesh = bpy.data.meshes.new_from_object(body.evaluated_get(deps), depsgraph=deps)
posed = bpy.data.objects.new('CasualtySupine', mesh)
scene.collection.objects.link(posed)
posed.matrix_world = body.matrix_world.copy()
rig.activate(posed)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
lo = Vector(tuple(min(v.co[i] for v in mesh.vertices) for i in range(3)))
hi = Vector(tuple(max(v.co[i] for v in mesh.vertices) for i in range(3)))
offset = Vector(((lo.x+hi.x)/2, (lo.y+hi.y)/2, lo.z))
for v in mesh.vertices:v.co -= offset
for obj in [body, arm]:bpy.data.objects.remove(obj, do_unlink=True)
rig.PARTS.clear();rig.REPAIRS.clear()
rig.register(posed, 'casualty')
rig.REPAIRS.append('Supine pose derived from weighted supplied rig; extraneous Icosphere removed; UV and source materials preserved.')
rig.export_asset('Casualty', source)
record = {'id':'MannequinRig','kind':'skeletal','source':source.relative_to(ROOT).as_posix(),
          'blend':'MannequinRig.blend','fbx':'MannequinRig.fbx','clips':clips,'bones':bone_count,
          'materials':materials, 'source_triangles':195252,'removed_objects':['Icosphere'],
          'purpose':'Base walking demonstration and weighted rescue poses; no unsupervised walking of casualties.'}
(folder / 'rig.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
print('MR_MANNEQUIN_RIG_PREPARED', json.dumps(record))
