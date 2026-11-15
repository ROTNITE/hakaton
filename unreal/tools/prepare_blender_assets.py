"""Prepare non-destructive UE exports from supplied Meshy .blend sources.

Run in Blender: --background --factory-startup --python <script>.
The source files remain untouched; outputs live under blender/prepared/v1.
"""
from pathlib import Path
import hashlib
import json
import math

import bpy
from mathutils import Vector, Matrix


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'blender' / 'prepared' / 'v1'
PREVIEW = ROOT / 'artifacts' / '3d-world' / 'asset-previews'
SPECS = [
    ('Rover', 'Rescue_Tracked_Transporter', 2.5, 0, 60000),
    ('Drone', 'Rescue_Scout_Drone', 1.3, 0, 30000),
    ('Stretcher', 'Rescue_Stretcher', 2.05, 0, 16000),
    ('Building', 'Damaged_Building', 9.6, 2, 90000),
    ('WindowWall', 'Wall_Module_with_Window', 3.2, 2, 18000),
]


def render_preview(obj, label, angle, size):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 12
    scene.cycles.use_denoising = True
    scene.cycles.device = 'CPU'
    scene.render.resolution_x = 800
    scene.render.resolution_y = 650
    scene.render.resolution_percentage = 100
    scene.world.color = (0.25, 0.25, 0.25)
    if scene.world.use_nodes:
        background = scene.world.node_tree.nodes.get('Background')
        if background:
            background.inputs['Color'].default_value = (.32, .35, .38, 1)
            background.inputs['Strength'].default_value = .6
    center = Vector((0, 0, obj.dimensions.z * .45))
    bpy.ops.object.camera_add(location=center + Vector((math.cos(angle), math.sin(angle), .65)) * size * 1.8)
    camera = bpy.context.object
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = size * 1.3
    scene.camera = camera
    for position, energy, scale in [((1, -2, 3), 350, 2.5), ((-2, 1, 2), 250, 2)]:
        bpy.ops.object.light_add(type='AREA', location=Vector(position) * size)
        light = bpy.context.object
        light.data.energy = energy * size * size
        light.data.shape = 'DISK'
        light.data.size = scale * size
        light.rotation_euler = (center - light.location).to_track_quat('-Z', 'Y').to_euler()
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = str(PREVIEW / (label + '.png'))
    bpy.ops.render.render(write_still=True)
    for item in list(scene.objects):
        if item.type in {'CAMERA', 'LIGHT'}:
            bpy.data.objects.remove(item, do_unlink=True)


def prepare(name, needle, length, axis, budget):
    source = next((ROOT / 'blender').glob('*' + needle + '_*.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if len(meshes) != 1:
        raise RuntimeError('Expected one audited Meshy mesh: ' + source.name)
    obj = meshes[0]
    for other in list(bpy.data.objects):
        if other != obj:
            bpy.data.objects.remove(other, do_unlink=True)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    bounds = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    low = Vector([min(v[i] for v in bounds) for i in range(3)])
    high = Vector([max(v[i] for v in bounds) for i in range(3)])
    center = Vector(((low.x + high.x) * .5, (low.y + high.y) * .5, low.z))
    factor = length / (high[axis] - low[axis])
    matrix = obj.matrix_world.copy()
    for vertex in obj.data.vertices:
        vertex.co = (matrix @ vertex.co - center) * factor
    obj.matrix_world = Matrix.Identity(4)
    bpy.context.view_layer.update()
    obj.data.calc_loop_triangles()
    before = len(obj.data.loop_triangles)
    decimate = obj.modifiers.new('GameMeshReduction', 'DECIMATE')
    decimate.ratio = min(1, budget / before)
    decimate.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=decimate.name)
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40), keep_sharp_edges=True)
    obj.data.calc_loop_triangles()
    after = len(obj.data.loop_triangles)
    obj.name = 'SM_' + name
    obj.data.name = obj.name + '_Geometry'
    bpy.context.scene.unit_settings.system = 'METRIC'
    bpy.context.scene.unit_settings.scale_length = 1
    folder = OUT / name
    textures = folder / 'textures'
    textures.mkdir(parents=True, exist_ok=True)
    material = obj.data.materials[0]
    material.name = 'M_' + name
    bsdf = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    links = [{'from_node': link.from_node.name, 'from_socket': link.from_socket.name,
              'to_node': link.to_node.name, 'to_socket': link.to_socket.name}
             for link in material.node_tree.links]
    image_nodes = [n for n in material.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image]
    texture_map = {}
    for node in image_nodes:
        outputs = [link for link in material.node_tree.links if link.from_node == node]
        if any(link.to_node == bsdf and link.to_socket.name == 'Base Color' for link in outputs):
            kind = 'BaseColor'
        elif any(link.to_node.type == 'NORMAL_MAP' for link in outputs):
            kind = 'Normal'
        else:
            kind = 'ORM'
        image = node.image
        image.name = 'T_' + name + '_' + kind
        image.file_format = 'PNG'
        image.filepath_raw = str(textures / (image.name + '.png'))
        image.save()
        image.filepath = '//textures/' + image.name + '.png'
        texture_map[kind] = 'textures/' + image.name + '.png'
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / (name + '.blend')), relative_remap=False)
    bpy.ops.export_scene.fbx(filepath=str(folder / (name + '.fbx')), use_selection=True,
        object_types={'MESH'}, add_leaf_bones=False, apply_unit_scale=True,
        apply_scale_options='FBX_SCALE_UNITS', axis_forward='-Y', axis_up='Z',
        path_mode='RELATIVE', use_mesh_modifiers=True, bake_anim=False)
    record = {'id': name, 'mesh': obj.name, 'source': source.relative_to(ROOT).as_posix(),
              'source_sha256': hashlib.file_digest(source.open('rb'), 'sha256').hexdigest(),
              'source_triangles': before, 'triangles': after, 'dimensions_m': list(obj.dimensions),
              'fbx': name + '/' + name + '.fbx', 'blend': name + '/' + name + '.blend',
              'textures': {k: name + '/' + v for k, v in texture_map.items()},
              'original_material_links': links, 'parts': 'single visual shell; functional geometry prepared separately',
              'collision': 'not included; runtime collision proxies are separate'}
    (folder / 'asset.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    size = max(obj.dimensions)
    render_preview(obj, name + '-front', -.7, size)
    render_preview(obj, name + '-rear', 2.4, size)
    print('MR_PREPARED:', json.dumps(record), flush=True)
    return record


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    PREVIEW.mkdir(parents=True, exist_ok=True)
    records = [prepare(*spec) for spec in SPECS]
    (OUT / 'manifest.json').write_text(json.dumps({'version': 1, 'assets': records}, indent=2), encoding='utf-8')
