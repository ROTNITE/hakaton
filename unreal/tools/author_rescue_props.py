"""Author complementary rescue-world models in Blender, with editable sources."""
from pathlib import Path
import json
import math
import random

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'blender' / 'authored' / 'v1'
PALETTE = {
    'Teal': ((.08, .24, .21, 1), .55, .25),
    'White': ((.72, .74, .70, 1), .65, .05),
    'Dark': ((.025, .035, .035, 1), .6, .3),
    'Metal': ((.25, .29, .30, 1), .42, .75),
    'Rubber': ((.018, .023, .025, 1), .93, 0),
    'Orange': ((.85, .23, .045, 1), .5, .25),
    'Red': ((.55, .065, .035, 1), .7, 0),
    'Glass': ((.045, .12, .15, 1), .19, .6),
    'Concrete': ((.40, .38, .34, 1), .92, 0),
    'Rust': ((.24, .10, .045, 1), .82, .45),
    'Paint': ((.65, .62, .45, 1), .9, 0),
    'Leaf': ((.14, .20, .12, 1), .95, 0),
    'Brick': ((.27, .13, .08, 1), .92, 0),
    'Ground': ((.29, .32, .25, 1), .95, 0),
}
MATERIALS = {}
PARTS = []


def material(key):
    if key not in MATERIALS:
        rgb, roughness, metallic = PALETTE[key]
        m = bpy.data.materials.new('M_A_' + key)
        m.diffuse_color = rgb
        m.use_nodes = True
        bsdf = m.node_tree.nodes.get('Principled BSDF')
        bsdf.inputs['Base Color'].default_value = rgb
        bsdf.inputs['Roughness'].default_value = roughness
        bsdf.inputs['Metallic'].default_value = metallic
        MATERIALS[key] = m
    return MATERIALS[key]


def finish(obj, name, color, bevel=0):
    obj.name = name
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.clear()
    obj.data.materials.append(material(color))
    if bevel:
        mod = obj.modifiers.new('ManufacturedEdges', 'BEVEL')
        mod.width = bevel
        mod.segments = 2
        bpy.ops.object.modifier_apply(modifier=mod.name)
    PARTS.append(obj)
    return obj


def box(name, location, dimensions, color, bevel=.01, rotation=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location, rotation=rotation)
    obj = bpy.context.object
    obj.dimensions = dimensions
    return finish(obj, name, color, bevel)


def cylinder(name, location, radius, depth, color, vertices=16, rotation=(0, 0, 0)):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth,
                                    location=location, rotation=rotation)
    return finish(bpy.context.object, name, color, .005 if radius > .02 else 0)


def rod(name, first, last, radius, color):
    first, last = Vector(first), Vector(last)
    direction = last - first
    obj = cylinder(name, (first + last) * .5, radius, direction.length, color, 10)
    obj.rotation_euler = direction.to_track_quat('Z', 'Y').to_euler()
    return obj


def sphere(name, position, dimensions, color):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=10, location=position)
    obj = bpy.context.object
    obj.dimensions = dimensions
    finish(obj, name, color)
    for face in obj.data.polygons:
        face.use_smooth = True
    return obj


def medical():
    box('Floor', (0, 0, .1), (6, 3, .2), 'Metal', .04)
    box('BackWall', (-2.94, 0, 1.5), (.12, 3, 2.8), 'Teal')
    for sign in [-1, 1]:
        box('SideWall', (0, sign * 1.46, 1.5), (6, .08, 2.8), 'Teal')
        box('WindowTrim', (0, sign * 1.515, 1.65), (1.5, .035, 1), 'White', .03)
        box('WindowGlass', (0, sign * 1.54, 1.65), (1.35, .018, .83), 'Glass', .015)
        for rib in range(24):
            box('ContainerRib', (-2.8 + rib * .24, sign * 1.51, 1.5), (.035, .035, 2.65), 'Teal', .004)
    for sign in [-1, 1]:
        box('EntranceJamb', (2.93, sign * 1.23, 1.5), (.14, .53, 2.8), 'Teal')
        box('DoorOpen', (2.99, sign * 1.25, 1.36), (.09, .52, 2.5), 'White', .02)
        for y in [-1.43, 1.43]:
            box('CornerFrame', (sign * 2.96, y, 1.5), (.12, .12, 3), 'White')
    box('EntranceHeader', (2.94, 0, 2.82), (.14, 2, .36), 'Teal')
    box('MedicalMark', (3.02, 0, 2.84), (.02, .12, .33), 'White')
    box('MedicalMark', (3.025, 0, 2.84), (.02, .33, .12), 'White')
    box('Roof', (0, 0, 3.04), (6.15, 3.15, .14), 'White', .025)
    for rib in range(16):
        box('RoofRib', (-2.9 + rib * .38, 0, 3.13), (.04, 3.04, .04), 'Metal', .005)
    box('Vent', (-1.5, 0, 3.33), (1, .8, .45), 'Metal', .03)
    for i in range(7):
        box('VentGrille', (-1.5, -.413, 3.19 + i * .045), (.8, .015, .015), 'Dark', 0)
    box('Ramp', (3.55, 0, .09), (1.2, 1.8, .06), 'Metal', .01, (0, -.1, 0))
    for sign in [-1, 1]:
        rod('RampGuide', (3.0, sign * .92, .2), (4.1, sign * .92, .07), .025, 'White')
    box('TreatmentBench', (-1, 1, .55), (2, .55, .8), 'White', .03)
    box('MedicalCabinet', (-2.6, -.95, 1.0), (.45, .8, 1.6), 'White', .03)


def relay():
    box('Battery', (0, 0, .38), (.65, .6, .76), 'Dark', .035)
    box('EquipmentBand', (.333, 0, .42), (.012, .5, .1), 'Teal', 0)
    cylinder('Mast', (0, 0, 1.8), .045, 3.6, 'Metal')
    for angle in [0, 2.094, 4.189]:
        x, y = math.cos(angle), math.sin(angle)
        rod('Stabilizer', (.8 * x, .8 * y, .05), (.25 * x, .25 * y, .55), .035, 'Metal')
        box('Foot', (.8 * x, .8 * y, .025), (.22, .18, .05), 'Dark')
    for sign in [-1, 1]:
        box('Antenna', (sign * .21, 0, 3.0), (.16, .12, .85), 'White', .025)
        rod('Bracket', (0, 0, 2.65), (sign * .21, 0, 2.65), .02, 'Metal')
    rod('Whip', (0, 0, 3.6), (0, 0, 3.95), .012, 'Dark')


def sensor():
    for angle in [0, 2.094, 4.189]:
        rod('TripodLeg', (.48 * math.cos(angle), .48 * math.sin(angle), .04), (0, 0, 1.2), .035, 'Metal')
    cylinder('PanAxis', (0, 0, 1.26), .09, .13, 'Metal')
    box('CameraBody', (0, 0, 1.48), (.4, .35, .3), 'Teal', .04)
    cylinder('Lens', (.23, 0, 1.48), .09, .08, 'Dark', rotation=(0, math.pi / 2, 0))
    cylinder('Glass', (.275, 0, 1.48), .075, .012, 'Glass', rotation=(0, math.pi / 2, 0))
    box('Battery', (0, 0, .46), (.26, .25, .2), 'Dark', .02)
    cylinder('Antenna', (-.12, .1, 1.84), .01, .45, 'Dark', 8)


def dock():
    box('Deck', (0, 0, .055), (3.1, 1.85, .11), 'Dark', .03)
    for sign in [-1, 1]:
        box('SideGuide', (0, sign * .88, .15), (2.9, .08, .18), 'Metal', .02)
        box('CornerMark', (1.35, sign * .86, .245), (.28, .08, .012), 'Orange', 0)
    box('ServiceHousing', (-1.45, 0, .3), (.32, 1.8, .6), 'Dark', .06)
    for sign in [-1, 1]:
        box('Contacts', (-1.275, sign * .42, .28), (.018, .24, .12), 'Metal')
    box('Status', (-1.27, 0, .51), (.015, .6, .035), 'Teal', 0)


def barrier():
    # True Jersey cross-section, extruded along the long X axis.
    cross = [(-.3, 0), (.3, 0), (.3, .2), (.13, .58), (.11, .85), (-.11, .85), (-.13, .58), (-.3, .2)]
    vertices = [(x, y, z) for x in [-1, 1] for y, z in cross]
    faces = [tuple(reversed(range(8))), tuple(range(8, 16))]
    faces += [(i, (i + 1) % 8, (i + 1) % 8 + 8, i + 8) for i in range(8)]
    mesh = bpy.data.meshes.new('JerseyGeometry');mesh.from_pydata(vertices, [], faces);mesh.update()
    obj = bpy.data.objects.new('BarrierBody', mesh);bpy.context.collection.objects.link(obj)
    finish(obj, 'BarrierBody', 'Concrete', .018)
    for side in [-1, 1]:
        for x in [-.7, -.25, .2, .65]:
            box('SafetyBand', (x, side * .126, .7), (.18, .014, .25), 'Orange', .003, (0, -.3, 0))


def lamp():
    box('Base', (0, 0, .045), (.3, .3, .09), 'Metal')
    cylinder('Pole', (0, 0, 3), .065, 6, 'Metal')
    rod('Arm', (0, 0, 5.9), (.85, 0, 6.2), .045, 'Metal')
    box('LampHead', (.95, 0, 6.2), (.65, .28, .11), 'Dark', .04)
    box('LampLens', (.95, 0, 6.14), (.52, .2, .02), 'White', .02)


def crate():
    box('Case', (0, 0, .22), (.8, .5, .44), 'Teal', .05)
    box('Lid', (0, 0, .47), (.8, .5, .08), 'Teal', .025)
    for x in [-.33, .33]:
        for y in [-.19, .19]:
            box('Corner', (x, y, .21), (.14, .12, .38), 'Rubber', .03)
    for x in [-.23, .23]:
        box('Latch', (x, -.261, .4), (.07, .025, .15), 'Metal', .008)
    box('Mark', (0, 0, .515), (.24, .07, .008), 'White', 0)
    box('Mark', (0, 0, .516), (.07, .24, .008), 'White', 0)


def fence():
    for x in [-1.5, 1.5]:
        box('Post', (x, 0, .9), (.07, .07, 1.8), 'Metal')
        box('Foot', (x, 0, .02), (.24, .24, .04), 'Dark')
    for z in [.12, 1.72]:
        box('Frame', (0, 0, z), (3, .04, .04), 'Metal', .005)
    for i in range(20):
        rod('Wire', (-1.4 + i * .148, 0, .15), (-1.4 + i * .148, 0, 1.7), .006, 'Metal')
    for i in range(10):
        rod('Wire', (-1.46, 0, .2 + i * .15), (1.46, 0, .2 + i * .15), .006, 'Metal')


def person():
    # Non-graphic training target lying on back, X is the body axis.
    sphere('Torso', (.10, 0, .18), (.55, .40, .26), 'Red')
    sphere('Pelvis', (-.27, 0, .17), (.28, .36, .25), 'Red')
    sphere('Head', (.58, 0, .22), (.25, .22, .27), 'Red')
    rod('Neck', (.39, 0, .2), (.49, 0, .2), .075, 'Red')
    for sign in [-1, 1]:
        sphere('UpperLeg', (-.52, sign * .10, .13), (.42, .17, .19), 'Dark')
        sphere('LowerLeg', (-.83, sign * .10, .1), (.35, .13, .15), 'Dark')
        sphere('Boot', (-1.00, sign * .10, .13), (.19, .14, .21), 'Rubber')
        sphere('UpperArm', (.07, sign * .27, .14), (.35, .12, .15), 'Red')
        sphere('LowerArm', (-.19, sign * .28, .12), (.28, .10, .12), 'Red')
        sphere('Hand', (-.36, sign * .28, .12), (.13, .09, .10), 'Red')


def slab():
    rng = random.Random(30)
    outline = [(-1.4, -.65), (.65, -.8), (1.4, -.35), (1.15, .7), (-1.05, .78)]
    vertices = [(x, y, z + rng.uniform(-.025, .025)) for z in [0, .24] for x, y in outline]
    faces = [tuple(reversed(range(5))), tuple(range(5, 10))]
    faces += [(i, (i + 1) % 5, (i + 1) % 5 + 5, i + 5) for i in range(5)]
    mesh = bpy.data.meshes.new('BrokenSlab');mesh.from_pydata(vertices, [], faces);mesh.update()
    obj = bpy.data.objects.new('ConcreteBody', mesh);bpy.context.collection.objects.link(obj)
    finish(obj, 'ConcreteBody', 'Concrete', .025)
    for y in [-.4, 0, .35]:
        rod('Rebar', (.95, y, .13), (1.65, y + .05, .10), .012, 'Rust')


def beam():
    box('Web', (0, 0, .18), (3, .035, .36), 'Rust', .006)
    for z in [.02, .35]:
        box('Flange', (0, 0, z), (3, .26, .045), 'Metal', .008)


def doorway():
    for sign in [-1, 1]:
        box('Jamb', (sign * 1.18, 0, 1.6), (.64, .32, 3.2), 'Concrete', .025)
    box('Lintel', (0, 0, 2.82), (1.74, .32, .76), 'Concrete', .025)


def loading_ramp():
    box('RampDeck', (0, 0, .02), (1.3, .8, .04), 'Metal', .012)
    for side in [-1, 1]:
        box('RampGuide', (0, side * .41, .075), (1.3, .025, .11), 'Metal', .005)
    for i in range(12):
        box('GripRib', (-.59 + i * .108, 0, .045), (.018, .75, .01), 'Dark', .003)


def rubble():
    rng = random.Random(231)
    for i in range(45):
        radius = rng.uniform(0, 1.2)
        angle = rng.uniform(0, math.tau)
        x, y = radius * math.cos(angle), radius * math.sin(angle) * .7
        z = max(.07, .45 * (1 - radius / 1.3)) + rng.uniform(0, .1)
        box('BrokenBrick', (x, y, z), (rng.uniform(.16, .28), .12, .09), 'Brick', .012,
            (rng.uniform(-.3, .3), rng.uniform(-.3, .3), rng.uniform(0, math.tau)))
    for i in range(12):
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1,
            location=(rng.uniform(-1, 1), rng.uniform(-.65, .65), rng.uniform(.15, .5)))
        obj = bpy.context.object
        obj.scale = (rng.uniform(.15, .35), rng.uniform(.12, .3), rng.uniform(.1, .22))
        finish(obj, 'ConcreteFragment', 'Concrete')


def tunnel():
    def profile(radius):
        return [(radius, 0)] + [(radius * math.cos(i * math.pi / 24),
            2 + radius * math.sin(i * math.pi / 24)) for i in range(25)] + [(-radius, 0)]

    def band(name, inner, outer, color, length=12):
        n = len(inner)
        vertices = [(x, y, z) for x in [-length/2, length/2] for curve in [inner, outer] for y, z in curve]
        faces = []
        for i in range(n-1):
            faces.extend([(i, 2*n+i, 2*n+i+1, i+1),
                          (n+i, n+i+1, 3*n+i+1, 3*n+i),
                          (i, i+1, n+i+1, n+i),
                          (2*n+i, 3*n+i, 3*n+i+1, 2*n+i+1)])
        faces.extend([(0,n,3*n,2*n),(n-1,3*n-1,4*n-1,2*n-1)])
        mesh = bpy.data.meshes.new(name);mesh.from_pydata(vertices, [], faces);mesh.update()
        obj = bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(obj)
        finish(obj,name,color)
    inner, outer = profile(2.0), profile(2.25)
    band('ConcreteVault',inner,outer,'Concrete')
    earth = []
    corners = [(7,0),(2.5,5.5),(-2.5,5.5),(-7,0)]
    for i in range(len(outer)):
        parameter = i/(len(outer)-1)*3
        section = min(2,int(parameter));blend = parameter-section
        earth.append(tuple(corners[section][j]*(1-blend)+corners[section+1][j]*blend for j in range(2)))
    band('EarthEmbankment',outer,earth,'Ground')
    for x in [-5.9,-3,0,3,5.9]:
        for side in [-1,1]:
            box('WallReinforcement',(x,side*1.97,1),(.08,.06,2),'Metal',.01)
        for i in range(12):
            a=(i+.5)*math.pi/12
            obj=box('VaultRib',(x,1.97*math.cos(a),2+1.97*math.sin(a)),(.08,.52,.045),'Metal',.004)
            obj.rotation_euler.x=a-math.pi/2
    box('Walkway',(0,0,.035),(12,3.9,.07),'Concrete',.005)
    rod('UtilityPipe',(-5.9,-1.84,2.1),(5.9,-1.84,2.1),.055,'Rust')


def export(name, builder):
    global MATERIALS, PARTS
    bpy.ops.wm.read_factory_settings(use_empty=True)
    MATERIALS, PARTS = {}, []
    builder()
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC';scene.unit_settings.scale_length = 1
    collection = bpy.data.collections.new(name + '_EditableParts')
    scene.collection.children.link(collection)
    for part in PARTS:
        for previous in list(part.users_collection):
            previous.objects.unlink(part)
        collection.objects.link(part)
    bpy.ops.object.select_all(action='SELECT')
    bpy.context.view_layer.objects.active = PARTS[0]
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / (name + '.blend')), relative_remap=False)
    # Export a joined static visual; the .blend retains the separately named construction parts.
    bpy.ops.object.join()
    obj = bpy.context.object
    scene.cursor.location = (0, 0, 0)
    bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
    obj.name = 'SM_' + name
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40), keep_sharp_edges=True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(island_margin=.025)
    bpy.ops.object.mode_set(mode='OBJECT')
    obj.data.calc_loop_triangles()
    bpy.ops.export_scene.fbx(filepath=str(folder / (name + '.fbx')), use_selection=True,
        object_types={'MESH'}, add_leaf_bones=False, apply_unit_scale=True,
        apply_scale_options='FBX_SCALE_UNITS', axis_forward='-Y', axis_up='Z',
        path_mode='RELATIVE', bake_anim=False)
    return {'id': name, 'fbx': name + '/' + name + '.fbx', 'blend': name + '/' + name + '.blend',
            'dimensions_m': list(obj.dimensions), 'triangles': len(obj.data.loop_triangles),
            'materials': [{'slot': i, 'name': slot.material.name,
                           'palette': slot.material.name.removeprefix('M_A_')}
                          for i, slot in enumerate(obj.material_slots)]}


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    builders = [('Medical', medical), ('Relay', relay), ('Sensor', sensor), ('Dock', dock),
                ('Barrier', barrier), ('Lamp', lamp), ('Crate', crate), ('Fence', fence),
                ('Person', person), ('Slab', slab), ('Beam', beam), ('Doorway', doorway),
                ('LoadingRamp', loading_ramp), ('Rubble', rubble), ('UtilityTunnel', tunnel)]
    records = [export(name, builder) for name, builder in builders]
    (OUT / 'manifest.json').write_text(json.dumps({'assets': records}, indent=2), encoding='utf-8')
    print('MR_AUTHORED_ASSETS_COMPLETE:', len(records), flush=True)
