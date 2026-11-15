"""Author three branching street trees on D:. No vendor assets are changed."""
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import random
import bpy
from mathutils import Vector

VERSION='city-foliage-1'
OUT=Path('D:/MetaRescue-output/city-foliage')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
OUT.mkdir(parents=True,exist_ok=False)
rows=[]
for variant,height in enumerate((5.5,6.5,7.5)):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.unit_settings.system='METRIC';bpy.context.scene.unit_settings.scale_length=1
    rng=random.Random(6251+variant)
    bark=bpy.data.materials.new('City_Bark');bark.diffuse_color=(.13,.08,.04,1)
    leaves=bpy.data.materials.new('City_Leaves');leaves.diffuse_color=(.075,.14,.035,1)
    objects=[]

    def branch(a,b,r1,r2):
        direction=Vector(b)-Vector(a)
        bpy.ops.mesh.primitive_cone_add(vertices=10,radius1=r1,radius2=r2,depth=direction.length,location=(Vector(a)+Vector(b))/2)
        obj=bpy.context.object;obj.rotation_euler=direction.to_track_quat('Z','Y').to_euler()
        obj.data.materials.append(bark);objects.append(obj)

    branch((0,0,0),(.06,-.03,4.2),.22,.08)
    for i in range(10):
        angle=i*math.tau/10+rng.uniform(-.15,.15);z=2.35+(i%3)*.52
        endpoint=(math.cos(angle)*1.18,math.sin(angle)*1.18,z+.9)
        branch((0,0,z),endpoint,.09,.025)
    for i in range(21):
        angle=i*2.399963
        radius=.95 if i<14 else .42
        z=3.7+(i%4)*(height-4.65)/3
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=1,
            location=(math.cos(angle)*radius,math.sin(angle)*radius,z))
        obj=bpy.context.object;obj.scale=(rng.uniform(.75,1.05),rng.uniform(.75,1.05),rng.uniform(.65,.9))
        obj.data.materials.append(leaves);objects.append(obj)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=1,location=(0,0,height-.6))
    obj=bpy.context.object;obj.scale=(.75,.8,.6);obj.data.materials.append(leaves);objects.append(obj)
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:obj.select_set(True)
    bpy.context.view_layer.objects.active=objects[0]
    bpy.ops.object.join();obj=bpy.context.object;obj.name=f'SM_StreetTree_{variant}'
    bpy.ops.object.transform_apply(location=False,rotation=True,scale=True)
    bpy.context.scene.cursor.location=(0,0,0);bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
    for face in obj.data.polygons:face.use_smooth=True
    bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66),island_margin=.02)
    bpy.ops.object.mode_set(mode='OBJECT')
    points=[obj.matrix_world@v.co for v in obj.data.vertices]
    low=[min(p[a] for p in points) for a in range(3)];high=[max(p[a] for p in points) for a in range(3)]
    # A tapered leaning trunk has a slightly tilted bottom ring. Author a flat
    # zero datum and the exact declared height before exporting the new mesh.
    for vertex in obj.data.vertices:vertex.co.z=(vertex.co.z-low[2])*height/(high[2]-low[2])
    points=[obj.matrix_world@v.co for v in obj.data.vertices]
    low=[min(p[a] for p in points) for a in range(3)];high=[max(p[a] for p in points) for a in range(3)]
    assert abs(low[2])<1e-5 and abs(high[2]-height)<1e-4,(low,high,height)
    assert max(abs(low[0]),abs(low[1]),abs(high[0]),abs(high[1]))<2.2,(low,high)
    fbx=OUT/(obj.name+'.fbx')
    bpy.ops.export_scene.fbx(filepath=str(fbx),use_selection=True,object_types={'MESH'},add_leaf_bones=False,
        apply_unit_scale=True,apply_scale_options='FBX_SCALE_UNITS',axis_forward='-Y',axis_up='Z',use_mesh_modifiers=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/(obj.name+'.blend')))
    rows.append({'variant':variant,'height_m':height,'fbx':str(fbx),'sha256':hashlib.sha256(fbx.read_bytes()).hexdigest(),
                 'bounds_m':{'min':low,'max':high},'vertices':len(obj.data.vertices),'faces':len(obj.data.polygons)})
report={'format':VERSION,'origin':'procedural project-authored branching trees; no third-party source',
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'blender':bpy.app.version_string,'models':rows}
(OUT/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('MR_CITY_FOLIAGE_AUTHORED',OUT)
