"""Measure real Blender/FBX part bounds instead of assuming an axis convention."""
from pathlib import Path
import json

root=Path(__file__).resolve().parents[2]
try:
    import bpy
except ImportError:
    import unreal
    manifest=json.loads((root/'unreal/MetaRescue/Content/Scenario/library-v2.json').read_text())
    report={}
    for asset in manifest['assets']:
        if asset['id'] not in {'Drone','Rover','Van'}:continue
        report[asset['id']]={}
        for part in asset['parts']:
            mesh=unreal.load_asset(part['mesh']);bounds=mesh.get_bounds()
            report[asset['id']][part['object']]={'center_cm':list(bounds.origin.to_tuple()),'dimensions_cm':part['dimensions_cm']}
    (root/'artifacts/3d-world/assembly-ue-bounds.json').write_text(json.dumps(report,indent=2))
else:
    from mathutils import Vector
    report={}
    for name in ['Drone','Rover','Van']:
        bpy.ops.wm.open_mainfile(filepath=str(root/'blender/prepared/v2'/name/(name+'.blend')),load_ui=False)
        report[name]={o.name:{'center_m':list(sum((Vector(p) for p in o.bound_box),Vector())/8),'location_m':list(o.location)}
                      for o in bpy.context.scene.objects if o.type=='MESH'}
    (root/'artifacts/3d-world/assembly-blender-bounds.json').write_text(json.dumps(report,indent=2))
