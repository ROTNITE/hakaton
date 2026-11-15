"""Inspect the supplied rig's local axes before authoring stretcher posture."""
from pathlib import Path
import bpy
from mathutils import Vector
root = Path(__file__).resolve().parents[2]
bpy.ops.wm.open_mainfile(filepath=str(root / 'blender/prepared/v2/MannequinRig/MannequinRig.blend'), load_ui=False)
arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
for side in ['Left', 'Right']:
    bone = arm.data.bones['mixamorig:' + side + 'Arm']
    print('MR_BONE_AXES', side, list(bone.head_local), list(bone.tail_local),
          [list(bone.matrix_local.to_3x3() @ Vector(v)) for v in [(1,0,0),(0,1,0),(0,0,1)]])
