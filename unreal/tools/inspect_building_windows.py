"""Probe facade surfaces at the window centers read from orthographic renders."""
from pathlib import Path
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
root=Path(__file__).resolve().parents[2]
bpy.ops.wm.open_mainfile(filepath=str(root/'blender/prepared/v2/Building/Building.blend'),load_ui=False)
obj=next(o for o in bpy.context.scene.objects if o.type=='MESH')
tree=BVHTree.FromObject(obj,bpy.context.evaluated_depsgraph_get())
for sign,ys in [(-1,[.97,-1.25]),(1,[-2.24,.51])]:
    for y in ys:
        for z in [1.65,4.4,7.2]:
            hit=tree.ray_cast(Vector((sign*10,y,z)),Vector((-sign,0,0)),20)
            print('MR_WINDOW_HIT',sign,y,z,list(hit[0]) if hit[0] else None)
