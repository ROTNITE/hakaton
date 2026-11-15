"""Non-destructive, editable mechanisms and glass repairs for supplied rescue models.

Rigid parts are exported independently with a transform manifest. Blender actions are
preview rigs; Unreal animates these parts from actual actuator state, not a timer loop.
"""
from pathlib import Path
import hashlib
import json
import math
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'blender/prepared/v2'
AUDIT = ROOT / 'artifacts/3d-world/asset-library'
SPECS = {
    'Drone': ('Rescue_Scout_Drone', 1.3, 0, 50000, True),
    'Rover': ('Rescue_Tracked_Transporter', 2.5, 0, 60000, True),
    'Medical': ('Medical_Aid_Container', 6.06, 0, 40000, False),
    'Van': ('Medical_Support_Van', 5.4, 0, 65000, True),
    'Sensor': ('Stationary_Sensor_Node', 1.8, 2, 24000, False),
    'Case': ('Rescue_Equipment_Case', .8, 0, 18000, False),
}
PARTS = []
REPAIRS = []


def activate(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def origin(obj, point):
    point = Vector(point)
    obj.data.transform(Matrix.Translation(-point))
    obj.location += point


def material(name, color, metallic=0, roughness=.5, glass=False):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Metallic'].default_value = metallic
    shader.inputs['Roughness'].default_value = roughness
    if glass:
        shader.inputs['Transmission Weight'].default_value = 1
        shader.inputs['IOR'].default_value = 1.45
    mat.diffuse_color = (*color, .2 if glass else 1)
    return mat


def cube(name, location, size, mat, bevel=.008):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    if bevel:
        mod = obj.modifiers.new('ManufacturedEdges', 'BEVEL')
        mod.width = bevel
        mod.segments = 2
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj


def cylinder(name, location, radius, depth, mat, axis='Y', vertices=32):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.rotation_euler = (math.pi / 2, 0, 0) if axis == 'Y' else (0, 0, 0)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    obj.data.materials.append(mat)
    return obj


def edit_faces(obj, predicate, name=None, pivot=None):
    """Split or remove a spatially reviewed face region while preserving UV layers."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    chosen = [face for face in bm.faces if predicate(face.calc_center_median())]
    if not chosen:
        bm.free()
        raise RuntimeError('Empty geometric edit: ' + (name or obj.name))
    result = None
    if name:
        copy = bm.copy()
        copy.faces.ensure_lookup_table()
        selected = {f.index for f in chosen}
        bmesh.ops.delete(copy, geom=[f for f in copy.faces if f.index not in selected], context='FACES')
        data = bpy.data.meshes.new(name + '_Geometry')
        copy.to_mesh(data)
        copy.free()
        result = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(result)
        for mat in obj.data.materials:
            data.materials.append(mat)
        if pivot is not None:
            origin(result, pivot)
    count = len(chosen)
    bmesh.ops.delete(bm, geom=chosen, context='FACES')
    bm.to_mesh(obj.data)
    bm.free()
    return result, count


def bisect_box(obj, low, high):
    """Split face boundaries before an aperture cut; preserve interpolated UVs."""
    bm = bmesh.new();bm.from_mesh(obj.data)
    for axis in range(3):
        for value in [low[axis],high[axis]]:
            point=Vector((0,0,0));point[axis]=value
            normal=Vector((0,0,0));normal[axis]=1
            bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
                dist=1e-6,plane_co=point,plane_no=normal,clear_inner=False,clear_outer=False)
    bm.to_mesh(obj.data);bm.free();obj.data.update()


def rotation_action(obj, name, axis, keys, linear=False):
    obj.rotation_mode = 'XYZ'
    for frame, degrees in keys:
        obj.rotation_euler[axis] = math.radians(degrees)
        obj.keyframe_insert(data_path='rotation_euler', index=axis, frame=frame)
    obj.animation_data.action.name = name
    for curve in obj.animation_data.action.fcurves:
        for key in curve.keyframe_points:
            key.interpolation = 'LINEAR' if linear else 'BEZIER'
            if not linear:
                key.handle_left_type = key.handle_right_type = 'AUTO_CLAMPED'
    obj.rotation_euler[axis] = math.radians(keys[0][1])


def register(obj, role='static', **extra):
    obj['mr_role'] = role
    PARTS.append({'object': obj.name, 'role': role, **extra})
    return obj


def make_drone(body):
    coords = np.empty(len(body.data.vertices) * 3, dtype=np.float32)
    body.data.vertices.foreach_get('co', coords)
    coords = coords.reshape((-1, 3))
    # Rotor blades are entirely above this reviewed plane; the motor cans stay fixed.
    for i, (sx, sy) in enumerate([(1, 1), (1, -1), (-1, 1), (-1, -1)]):
        # The generated source has different motor heights on the two sides.
        zcut = .398 if sy > 0 else .48
        group = coords[(coords[:, 0] * sx > .14) & (coords[:, 1] * sy > .14) & (coords[:, 2] > zcut)]
        if len(group) < 20:
            raise RuntimeError('Rotor region missing: ' + str(i))
        center = (group[:, :2].min(axis=0) + group[:, :2].max(axis=0)) * .5
        band = coords[(coords[:, 2] > zcut - .05) & (coords[:, 2] < zcut - .012)
                      & (np.linalg.norm(coords[:, :2] - center, axis=1) < .08)]
        if len(band) < 20:
            raise RuntimeError('Cannot fit rotor motor axis: ' + str(i))
        design = np.column_stack((band[:, 0], band[:, 1], np.ones(len(band))))
        fitted = np.linalg.lstsq(design, -(band[:, 0] ** 2 + band[:, 1] ** 2), rcond=None)[0]
        fitted_center = -fitted[:2] / 2
        # Incomplete generated motor rings can give an unstable least-squares
        # circle. Reject an axis outside the symmetric two-blade envelope.
        axis = fitted_center if np.linalg.norm(fitted_center-center)<.025 else center
        pivot = Vector((float(axis[0]), float(axis[1]), zcut))
        part, count = edit_faces(body, lambda p, sx=sx, sy=sy, zcut=zcut: p.x * sx > .14 and p.y * sy > .14 and p.z > zcut,
                                 'Rotor_' + str(i), pivot)
        sign = 1 if sx == sy else -1
        rotation_action(part, 'RotorLoop_' + str(i), 2, [(1, 0), (31, sign * 3600)], True)
        register(part, 'rotor', spin=sign, axis='Z', pivot_m=list(pivot), extracted_faces=count)
    # The camera below the nose is independent from the fixed landing gear.
    camera, count = edit_faces(body, lambda p: p.x > .12 and p.z < .23 and abs(p.y) < .13,
                               'Gimbal', (.26, 0, .205))
    rotation_action(camera, 'CameraSweep', 1, [(1, -12), (61, 22), (121, -12)])
    register(camera, 'gimbal', axis='Y', limits_deg=[-35, 35], extracted_faces=count)
    REPAIRS.append('Separated four textured rotors and camera; opposite diagonal spin; fixed motor/landing gear.')


def belt(name, y, rubber):
    # Closed capsule strip, arc-length UV along travel. There are no individual physics links.
    points = []
    half, radius, z = .91, .225, .24
    for center, start in [(half, -math.pi / 2), (-half, math.pi / 2)]:
        for i in range(25):
            angle = start + math.pi * i / 24
            points.append((center + radius * math.cos(angle), z + radius * math.sin(angle)))
    verts, faces, distances = [], [], [0.]
    for i, (x, height) in enumerate(points):
        if i:
            distances.append(distances[-1] + math.dist(points[i - 1], points[i]))
        for side, inset in [(-1, 0), (1, 0), (-1, .045), (1, .045)]:
            # Inner strip shrinks toward the center of the capsule section.
            toward = Vector((x, height - z)).normalized()
            verts.append((x - toward.x * inset, y + side * .105, height - toward.y * inset))
    count = len(points)
    for i in range(count):
        j = (i + 1) % count
        for a, b in [(0, 1), (1, 3), (3, 2), (2, 0)]:
            faces.append((i * 4 + a, j * 4 + a, j * 4 + b, i * 4 + b))
    mesh = bpy.data.meshes.new(name + '_Geometry')
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    uv = mesh.uv_layers.new(name='TrackTravelUV')
    perimeter = distances[-1] + math.dist(points[-1], points[0])
    for poly in mesh.polygons:
        segment = poly.index // 4
        u0 = distances[segment] / perimeter
        u1 = distances[segment + 1] / perimeter if segment + 1 < count else 1
        for loop, value in zip(poly.loop_indices, [(u0, 0), (u1, 0), (u1, 1), (u0, 1)]):
            uv.data[loop].uv = value
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    mesh.materials.append(rubber)
    register(obj, 'track', side=1 if y > 0 else -1, perimeter_m=perimeter)
    return obj


def track_material():
    mat = material('M_Rig_Track', (.035, .042, .038), .05, .88)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    shader = nodes.get('Principled BSDF')
    uv = nodes.new('ShaderNodeTexCoord')
    split = nodes.new('ShaderNodeSeparateXYZ')
    links.new(uv.outputs['UV'], split.inputs[0])
    offset = nodes.new('ShaderNodeValue')
    offset.name = 'TrackOffset'
    for frame, value in [(1, 0), (121, -2)]:
        offset.outputs[0].default_value = value
        offset.outputs[0].keyframe_insert(data_path='default_value', frame=frame)
    add = nodes.new('ShaderNodeMath');add.operation = 'ADD'
    links.new(split.outputs['X'], add.inputs[0]);links.new(offset.outputs[0], add.inputs[1])
    repeat = nodes.new('ShaderNodeMath');repeat.operation = 'MULTIPLY';repeat.inputs[1].default_value = 60
    links.new(add.outputs[0], repeat.inputs[0])
    fraction = nodes.new('ShaderNodeMath');fraction.operation = 'FRACT';links.new(repeat.outputs[0], fraction.inputs[0])
    ridge = nodes.new('ShaderNodeMath');ridge.operation = 'LESS_THAN';ridge.inputs[1].default_value = .22
    links.new(fraction.outputs[0], ridge.inputs[0])
    bump = nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value = .55;bump.inputs['Distance'].default_value = .009
    links.new(ridge.outputs[0], bump.inputs['Height']);links.new(bump.outputs[0], shader.inputs['Normal'])
    return mat


def make_rover(body):
    _, removed = edit_faces(body, lambda p: p.z < .49 and abs(p.y) > .40)
    _, rear_removed = edit_faces(body, lambda p: p.x < -1.01 and p.z > .57 and abs(p.y) < .50)
    rubber = material('M_Rig_Rubber', (.035, .042, .038), .05, .88)
    tracks = track_material()
    metal = material('M_Rig_Metal', (.27, .30, .29), .75, .35)
    orange = material('M_Rig_Orange', (.76, .16, .035), .18, .5)
    for side in [-1, 1]:
        belt('Track_' + ('L' if side > 0 else 'R'), side * .53, tracks)
        for i in range(6):
            x = -.90 + i * .36
            wheel = cylinder('Wheel_' + str(side) + '_' + str(i), (x, side * .53, .24), .178, .175, rubber)
            # Join manufactured hub and lug pattern into each rigid rotating wheel.
            pieces = [wheel, cylinder('Hub', (x, side * .627, .24), .108, .025, metal)]
            for bolt in range(6):
                angle = bolt * math.tau / 6
                pieces.append(cylinder('Lug', (x + .074 * math.cos(angle), side * .645, .24 + .074 * math.sin(angle)), .012, .012, metal, vertices=8))
            bpy.ops.object.select_all(action='DESELECT')
            for piece in pieces:
                piece.select_set(True)
            bpy.context.view_layer.objects.active = wheel
            bpy.ops.object.join()
            rotation_action(wheel, 'WheelRoll_' + str(side) + '_' + str(i), 1, [(1, 0), (121, -720)], True)
            register(wheel, 'wheel', side=side, radius_m=.178, axis='Y')
    # A short stored ramp plus a sliding extension reaches the ground when deployed.
    ramp = cube('RearRamp', (-1.08, 0, .57), (.64, .76, .035), metal)
    ramp.data.transform(Matrix.Translation(Vector((-.32, 0, 0))))
    rotation_action(ramp, 'RampDeploy', 1, [(1, 80), (31, 80), (66, -27), (151, -27), (186, 80)])
    register(ramp, 'ramp', axis='Y', stowed_deg=80, deployed_deg=-27)
    extension = cube('RampExtension', (0, 0, -.022), (.60, .70, .025), metal)
    extension.data.transform(Matrix.Translation(Vector((-.32, 0, 0))))
    extension.parent = ramp
    for frame, x in [(1, 0), (65, 0), (90, -.52), (135, -.52), (160, 0)]:
        extension.location.x = x
        extension.keyframe_insert(data_path='location', index=0, frame=frame)
    extension.animation_data.action.name = 'RampExtensionDeploy'
    register(extension, 'ramp_extension', travel_m=.52)
    winch = cylinder('WinchDrum', (-.91, 0, .68), .055, .24, metal)
    rotation_action(winch, 'WinchPull', 1, [(1, 0), (91, 1080)], True)
    register(winch, 'winch', axis='Y', radius_m=.055)
    REPAIRS.append('Removed fused track shells (' + str(removed) + ' faces) and rear infill (' + str(rear_removed) + '); rebuilt 12 wheels and two closed UV belts; authored telescopic ramp and winch.')


def make_medical(body):
    # Reviewed on both side elevations. The cut removes both opaque window infills.
    _, count = edit_faces(body, lambda p: -.23 < p.x < 1.13 and 1.20 < p.z < 1.92)
    glass = material('M_Rig_Glass', (.78, .9, .92), 0, .075, True)
    trim = material('M_Rig_WindowFrame', (.62, .65, .63), .55, .35)
    floor = material('M_Rig_MedicalInterior', (.66, .73, .71), .05, .58)
    for side in [-1, 1]:
        y = side * 1.225
        for i, (x, width) in enumerate([(.10, .65), (.79, .65)]):
            register(cube('MedicalGlass_' + str(side) + '_' + str(i), (x, y, 1.56), (width, .012, .68), glass, .002), 'glass')
        for x in [-.25, .45, 1.15]:
            register(cube('WindowMullion', (x, y - side * .012, 1.56), (.035, .06, .76), trim), 'static')
        for z in [1.19, 1.93]:
            register(cube('WindowSill', (.45, y, z), (1.45, .06, .035), trim), 'static')
    register(cube('MedicalInteriorFloor', (.35, 0, .16), (4.7, 2.3, .07), floor), 'static')
    register(cube('MedicalBench', (.6, .82, .55), (2.3, .42, .12), floor), 'static')
    register(cube('MedicalCabinet', (1.8, .82, .68), (.7, .4, 1.0), floor), 'static')
    bpy.context.view_layer.update()
    tree = BVHTree.FromObject(body, bpy.context.evaluated_depsgraph_get())
    hit = tree.ray_cast(Vector((.45, -1.65, 1.56)), Vector((0, 1, 0)), 3.3)
    if hit[0] is not None:
        raise RuntimeError('Medical opaque window cut is still blocked: ' + str(hit[0]))
    REPAIRS.append('Removed ' + str(count) + ' opaque infill faces; two-sided paired glazing, frames and simple interior; clear aperture ray verified.')


def make_sensor(body):
    head, count = edit_faces(body, lambda p: p.z > 1.12, 'SensorHead', (0, 0, 1.16))
    rotation_action(head, 'SensorScan', 2, [(1, -50), (91, 50), (181, -50)])
    register(head, 'sensor_head', axis='Z', limits_deg=[-50, 50], extracted_faces=count)
    REPAIRS.append('Separated camera head above swivel from fixed tripod; bounded eased scan.')


def make_van(body):
    glass = material('M_Rig_Glass', (.73, .86, .89), 0, .09, True)
    interior = material('M_Rig_VanInterior', (.29, .34, .33), .05, .65)
    seat = material('M_Rig_Seat', (.06, .105, .11), 0, .83)
    rubber = material('M_Rig_Rubber', (.028, .033, .03), .03, .88)
    metal = material('M_Rig_Metal', (.37, .40, .39), .8, .3)
    # Spatial masks were drawn from the orthographic source elevations. Splitting
    # the actual curved surfaces retains their fit; the infill becomes glazing.
    for side in [-1, 1]:
        for label, low, high in [('CabGlass', .67, 1.60), ('SideGlass', -1.15, .18)]:
            pane, count = edit_faces(body, lambda p, side=side, low=low, high=high:
                p.y * side > .88 and low < p.x < high and 1.23 < p.z < 1.99,
                label + ('L' if side > 0 else 'R'))
            pane.data.materials.clear();pane.data.materials.append(glass)
            register(pane, 'glass', converted_faces=count)
    windscreen, count = edit_faces(body, lambda p: p.x > 1.45 and abs(p.y) < .82 and 1.34 < p.z < 2.07,
                                   'Windscreen')
    windscreen.data.materials.clear();windscreen.data.materials.append(glass)
    register(windscreen, 'glass', converted_faces=count)
    # The generated rear infill is warped and has no usable panel boundary.
    # Rebuild the doors as rigid framed panels instead of animating torn shards.
    _, count = edit_faces(body, lambda p: p.x < -2.35 and abs(p.y) < .91 and .64 < p.z < 2.44)
    white = material('M_Rig_VanPaint', (.77, .81, .79), .22, .32)
    teal = material('M_Rig_VanStripe', (.025, .28, .28), .12, .42)
    for side in [-1, 1]:
        register(cube('RearApertureJamb', (-2.53, side*.92, 1.52), (.46,.105,1.81), white, .018), 'static')
    register(cube('RearApertureHeader', (-2.53,0,2.42), (.46,1.87,.10), white, .018), 'static')
    register(cube('RearApertureSill', (-2.53,0,.66), (.46,1.87,.08), rubber, .015), 'static')
    for side in [-1, 1]:
        pivot = Vector((-2.74, side * .89, .65))
        elements = []
        for label, p, size, mat in [
            ('LowerPanel', (-2.74, side * .46, .98), (.055, .84, .66), white),
            ('UpperRail', (-2.74, side * .46, 2.17), (.055, .84, .38), white),
            ('OuterRail', (-2.74, side * .86, 1.65), (.06, .055, .72), white),
            ('CenterRail', (-2.74, side * .055, 1.65), (.06, .055, .72), white),
            ('Stripe', (-2.775, side * .46, 1.05), (.012, .84, .085), teal),
            ('Handle', (-2.79, side * .13, 1.22), (.045, .14, .032), rubber),
        ]:
            elements.append(cube(label, p, size, mat, .009))
        bpy.ops.object.select_all(action='DESELECT')
        for element in elements:element.select_set(True)
        door = elements[0];bpy.context.view_layer.objects.active = door;bpy.ops.object.join()
        door.name = 'RearDoor_' + str(side)
        door.data.transform(Matrix.Translation(door.location - pivot));door.location = pivot
        pane = cube('RearGlass_' + str(side), (-2.735, side * .46, 1.65), (.018, .75, .67), glass, .004)
        pane.parent = door;pane.location -= pivot
        rotation_action(door, 'VanRearDoor_' + str(side), 2, [(1, 0), (46, -side * 88), (136, -side * 88), (181, 0)])
        register(door, 'van_door', axis='Z', side=side, open_deg=-side * 88, removed_infill_faces=count)
        register(pane, 'glass')
    wheel_x = [2.06, -1.87]
    _, removed = edit_faces(body, lambda p: abs(p.y) > .81 and p.z < .75 and
        any((p.x - x) ** 2 + (p.z - .36) ** 2 < .44 ** 2 for x in wheel_x))
    for side in [-1, 1]:
        for i, x in enumerate(wheel_x):
            wheel = cylinder('VanWheel_' + str(side) + '_' + str(i), (x, side * .99, .36), .36, .19, rubber, vertices=48)
            hub = cylinder('VanHub', (x, side * 1.095, .36), .22, .025, metal)
            pieces = [wheel, hub]
            for j in range(8):
                a = j * math.tau / 8
                pieces.append(cylinder('HubInset', (x + .16 * math.sin(a), side * 1.115, .36 + .16 * math.cos(a)), .026, .01, rubber, vertices=12))
            bpy.ops.object.select_all(action='DESELECT')
            for part in pieces:part.select_set(True)
            bpy.context.view_layer.objects.active = wheel;bpy.ops.object.join()
            rotation_action(wheel, 'VanWheelRoll_' + str(side) + '_' + str(i), 1, [(1, 0), (181, -1080)], True)
            register(wheel, 'wheel', radius_m=.36, side=side, axle=i, axis='Y')
    register(cube('CabFloor', (.4, 0, .43), (4.7, 1.82, .07), interior), 'static')
    register(cube('Dashboard', (1.63, 0, 1.12), (.42, 1.7, .27), interior, .03), 'static')
    for side in [-1, 1]:
        register(cube('SeatBase', (.90, side * .48, .76), (.58, .48, .15), seat, .035), 'static')
        register(cube('SeatBack', (.64, side * .48, 1.09), (.12, .48, .65), seat, .035), 'static')
    register(cube('MedicalBench', (-1.12, .65, .75), (1.7, .48, .15), seat, .025), 'static')
    register(cube('EquipmentCupboard', (-1.1, -.65, .99), (1.5, .38, 1.1), interior, .02), 'static')
    for sx in [-1, 1]:
        for side in [-1, 1]:
            beacon, count = edit_faces(body, lambda p, sx=sx, side=side:
                p.x*sx>0 and p.y*side>.55 and p.z>2.77, 'EmergencyBeacon_' + str(sx) + '_' + str(side))
            register(beacon, 'beacon', side=side, extracted_faces=count)
    REPAIRS.append('Set van proportions to 5.8 x 2.28 x 2.85 m; seven curved glazing regions, cabin/cargo interior, hinged rear doors, four rebuilt wheels (' + str(removed) + ' old wheel faces removed), emergency lenses.')


def make_case(body):
    lid, count = edit_faces(body, lambda p: p.z > .35, 'CaseLid', (0, .20, .35))
    rotation_action(lid, 'CaseOpen', 0, [(1, 0), (45, -100), (120, -100), (160, 0)])
    register(lid, 'case_lid', axis='X', extracted_faces=count)
    lining = material('M_Rig_CaseInterior', (.065, .085, .08), 0, .9)
    for name, p, s in [('LiningFloor', (0, 0, .05), (.71, .36, .025)),
                        ('LiningRear', (0, .17, .21), (.71, .025, .31)),
                        ('LiningFront', (0, -.17, .21), (.71, .025, .31)),
                        ('LiningEnd1', (-.35, 0, .21), (.025, .35, .31)),
                        ('LiningEnd2', (.35, 0, .21), (.025, .35, .31))]:
        register(cube(name, p, s, lining), 'static')
    REPAIRS.append('Separated hinged lid and added internal lining; rigid preview open/close.')


def export_materials(folder):
    textures = folder / 'textures'
    textures.mkdir(exist_ok=True)
    image_files = {}
    used = {mat for obj in bpy.context.scene.objects if obj.type == 'MESH' for mat in obj.data.materials if mat}
    reports = []
    for mat in sorted(used, key=lambda m: m.name):
        shader = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if mat.use_nodes else None
        entry = {'name': mat.name, 'glass': 'glass' in mat.name.lower(), 'inputs': {}}
        if shader:
            for socket in ['Base Color', 'Metallic', 'Roughness', 'Transmission Weight', 'IOR', 'Alpha', 'Emission Color', 'Emission Strength']:
                pin = shader.inputs[socket]
                value = pin.default_value
                entry['inputs'][socket] = list(value) if hasattr(value, '__len__') else value
            entry['links'] = [{'from': l.from_node.name, 'output': l.from_socket.name,
                               'to': l.to_node.name, 'input': l.to_socket.name} for l in mat.node_tree.links]
            entry['images'] = []
            for node in mat.node_tree.nodes:
                if node.type != 'TEX_IMAGE' or not node.image:
                    continue
                img = node.image
                if img.name not in image_files:
                    filename = 'T_' + str(len(image_files)) + '_' + ''.join(c if c.isalnum() else '_' for c in img.name.rsplit('.', 1)[0]) + '.png'
                    if max(img.size) > 2048:
                        factor = 2048 / max(img.size)
                        img.scale(max(1, round(img.size[0] * factor)), max(1, round(img.size[1] * factor)))
                    img.file_format = 'PNG'
                    img.filepath_raw = str(textures / filename)
                    img.save()
                    if img.packed_file:
                        img.unpack(method='REMOVE')
                    img.filepath = '//textures/' + filename
                    image_files[img.name] = 'textures/' + filename
                entry['images'].append({'node': node.name, 'image': img.name, 'file': image_files[img.name],
                                        'colorspace': img.colorspace_settings.name})
        reports.append(entry)
    return reports


def export_asset(name, source):
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1
    scene.render.fps = 30
    scene.render.engine = 'CYCLES'
    scene.frame_start, scene.frame_end = 1, 186
    scene.frame_set(1)
    # BMesh edits rebuild edge data; restore angle-based shading after those edits.
    for obj in [o for o in scene.objects if o.type == 'MESH']:
        activate(obj)
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40), keep_sharp_edges=False)
    mats = export_materials(folder)
    # High-poly bake source materials/images are not part of the editable game
    # asset. Purge unused datablocks instead of retaining packed source images.
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
    for item in PARTS:
        obj = bpy.data.objects[item['object']]
        obj.data.calc_loop_triangles()
        item.update(triangles=len(obj.data.loop_triangles), location_m=list(obj.matrix_local.translation),
                    rotation_deg=[math.degrees(v) for v in obj.matrix_local.to_euler()],
                    parent=obj.parent.name if obj.parent else None,
                    dimensions_m=list(obj.dimensions),
                    materials=[m.name for m in obj.data.materials], fbx='parts/' + obj.name + '.fbx')
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / (name + '.blend')), relative_remap=False)
    (folder / 'parts').mkdir(exist_ok=True)
    for item in PARTS:
        obj = bpy.data.objects[item['object']]
        parent, local, inverse = obj.parent, obj.matrix_basis.copy(), obj.matrix_parent_inverse.copy()
        animation = obj.animation_data.action if obj.animation_data else None
        if obj.animation_data:
            obj.animation_data.action = None
        obj.parent = None
        obj.matrix_world = Matrix.Identity(4)
        activate(obj)
        bpy.ops.export_scene.fbx(filepath=str(folder / item['fbx']), use_selection=True,
            object_types={'MESH'}, add_leaf_bones=False, apply_unit_scale=True,
            apply_scale_options='FBX_SCALE_UNITS', axis_forward='-Y', axis_up='Z',
            path_mode='RELATIVE', use_mesh_modifiers=True, mesh_smooth_type='FACE', bake_anim=False)
        obj.parent, obj.matrix_basis, obj.matrix_parent_inverse = parent, local, inverse
        if animation:
            obj.animation_data.action = animation
    record = {'id': name, 'source': source.relative_to(ROOT).as_posix(),
              'source_sha256': hashlib.file_digest(source.open('rb'), 'sha256').hexdigest(),
              'blend': name + '.blend', 'parts': PARTS.copy(), 'materials': mats,
              'repairs': REPAIRS.copy(), 'actions': [{'name': a.name, 'frames': list(a.frame_range)} for a in bpy.data.actions],
              'animation_runtime': 'Rigid meshes driven from Unreal actuator state; Blender actions are inspectable demonstrations.'}
    (folder / 'asset.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print('MR_MECHANIZED', name, len(PARTS), 'parts', sum(p['triangles'] for p in PARTS), 'triangles', flush=True)
    return record


def load_body(name):
    token, length, axis, budget, flip = SPECS[name]
    source = next((ROOT / 'blender').glob('Meshy_AI_' + token + '_*.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False)
    body = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
    for other in list(bpy.data.objects):
        if other != body:
            bpy.data.objects.remove(other, do_unlink=True)
    activate(body)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    points = [body.matrix_world @ Vector(v) for v in body.bound_box]
    low = Vector(tuple(min(v[i] for v in points) for i in range(3)))
    high = Vector(tuple(max(v[i] for v in points) for i in range(3)))
    scale = length / (high[axis] - low[axis])
    offset = Vector(((low.x + high.x) / 2, (low.y + high.y) / 2, low.z))
    transform = Matrix.Rotation(math.pi if flip else 0, 4, 'Z') @ Matrix.Scale(scale, 4) @ Matrix.Translation(-offset)
    body.data.transform(transform @ body.matrix_world)
    body.matrix_world = Matrix.Identity(4)
    if name == 'Van':
        size = (high - low) * scale
        body.data.transform(Matrix.Diagonal(Vector((5.8 / size.x, 2.28 / size.y, 2.85 / size.z, 1))))
    body.name = 'Body'
    high = body.copy()
    high.data = body.data.copy()
    high.name = 'BakeSource_High'
    bpy.context.collection.objects.link(high)
    body.data.calc_loop_triangles()
    mod = body.modifiers.new('RuntimeReduction', 'DECIMATE')
    mod.ratio = min(1, budget / len(body.data.loop_triangles))
    mod.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40), keep_sharp_edges=True)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bake_meshy_surface import bake_surface
    bake_surface(high, body, OUT / name / 'baked', name)
    return source, body


def prepare(name):
    PARTS.clear()
    REPAIRS.clear()
    source, body = load_body(name)
    register(body, 'body')
    recipes = {'Drone': make_drone, 'Rover': make_rover, 'Medical': make_medical, 'Sensor': make_sensor, 'Case': make_case, 'Van': make_van}
    if name in recipes:
        recipes[name](body)
    else:
        raise RuntimeError('Repair recipe not yet implemented: ' + name)
    return export_asset(name, source)


if __name__ == '__main__':
    wanted = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else ['Drone', 'Rover', 'Medical', 'Sensor', 'Case']
    OUT.mkdir(parents=True, exist_ok=True)
    for name in wanted:
        prepare(name)
