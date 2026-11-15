"""Read every supplied model and render diagnostic views without saving originals.

Blender --background --factory-startup --python-exit-code 1 --python this.py -- --render
"""
from pathlib import Path
import hashlib
import json
import math
import sys

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/3d-world/asset-library'
ARGS = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []


def asset_id(path):
    name = path.stem.removeprefix('Meshy_AI_').split('_20261109')[0]
    return name.removesuffix('_4k')


def open_source(path):
    if path.suffix == '.blend':
        bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    elif path.suffix == '.glb':
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(path))
    else:
        raise ValueError('Unsupported source: ' + str(path))


def bounds(objects):
    points = [obj.matrix_world @ Vector(p) for obj in objects if obj.type == 'MESH' for p in obj.bound_box]
    return Vector(tuple(min(v[i] for v in points) for i in range(3))), Vector(tuple(max(v[i] for v in points) for i in range(3)))


def inspect(path):
    open_source(path)
    objects = []
    for obj in bpy.data.objects:
        row = {'name': obj.name, 'type': obj.type, 'parent': obj.parent.name if obj.parent else None,
               'location': list(obj.location), 'rotation': list(obj.rotation_euler), 'scale': list(obj.scale),
               'hidden_render': obj.hide_render}
        if obj.type == 'MESH':
            obj.data.calc_loop_triangles()
            lo, hi = bounds([obj])
            row.update(vertices=len(obj.data.vertices), triangles=len(obj.data.loop_triangles),
                       uv_layers=list(obj.data.uv_layers.keys()), bounds_min=list(lo), bounds_max=list(hi),
                       materials=[s.material.name if s.material else None for s in obj.material_slots],
                       modifiers=[{'name': m.name, 'type': m.type} for m in obj.modifiers])
        if obj.type == 'ARMATURE':
            row.update(bones=[{'name': b.name, 'parent': b.parent.name if b.parent else None} for b in obj.data.bones])
        anim = obj.animation_data
        if anim:
            row['animation'] = {'action': anim.action.name if anim.action else None,
                                'nla_tracks': [{'name': t.name, 'strips': [{'name': s.name, 'action': s.action.name if s.action else None,
                                  'start': s.frame_start, 'end': s.frame_end} for s in t.strips]} for t in anim.nla_tracks]}
        objects.append(row)
    materials = []
    for mat in bpy.data.materials:
        nodes = []
        if mat.use_nodes:
            for node in mat.node_tree.nodes:
                entry = {'name': node.name, 'type': node.type}
                if node.type == 'TEX_IMAGE' and node.image:
                    entry['image'] = node.image.name
                if node.type == 'BSDF_PRINCIPLED':
                    entry['inputs'] = {pin.name: {'linked': pin.is_linked,
                        'value': list(pin.default_value) if hasattr(pin.default_value, '__len__') else pin.default_value}
                        for pin in node.inputs if pin.name in {'Base Color', 'Roughness', 'Metallic', 'Alpha', 'Transmission Weight', 'IOR'}}
                if node.type == 'GROUP' and node.node_tree:
                    entry['group'] = node.node_tree.name
                nodes.append(entry)
        materials.append({'name': mat.name, 'nodes': nodes})
    images = [{'name': img.name, 'size': list(img.size), 'packed': bool(img.packed_file),
               'filepath': img.filepath, 'colorspace': img.colorspace_settings.name,
               'exists': bool(img.packed_file) or Path(bpy.path.abspath(img.filepath)).is_file()}
              for img in bpy.data.images if img.type not in {'RENDER_RESULT', 'COMPOSITING'}]
    lo, hi = bounds(bpy.data.objects)
    with path.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    report = {'id': asset_id(path), 'source': path.relative_to(ROOT).as_posix(), 'sha256': sha,
              'units': {'system': bpy.context.scene.unit_settings.system, 'scale_length': bpy.context.scene.unit_settings.scale_length},
              'bounds_min': list(lo), 'bounds_max': list(hi), 'dimensions': list(hi - lo),
              'objects': objects, 'materials': materials, 'images': images,
              'actions': [{'name': a.name, 'frames': list(a.frame_range),
                           'slots': [s.identifier for s in a.slots]} for a in bpy.data.actions]}
    (OUT / 'reports').mkdir(exist_ok=True)
    (OUT / 'reports' / (report['id'] + '.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('MR_LIBRARY_AUDIT', report['id'], sum(o.get('triangles', 0) for o in objects),
          len(report['actions']), 'actions', sum(not i['exists'] for i in images), 'missing images', flush=True)
    return report


def preview(report):
    scene = bpy.context.scene
    meshes = [o for o in scene.objects if o.type == 'MESH' and not o.hide_render]
    lo, hi = bounds(meshes)
    span = max(hi - lo)
    root = bpy.data.objects.new('Audit_Normalization', None)
    scene.collection.objects.link(root)
    for obj in list(scene.objects):
        if obj != root and obj.parent is None and obj.type not in {'CAMERA', 'LIGHT'}:
            world = obj.matrix_world.copy()
            obj.parent = root
            obj.matrix_world = world
    root.scale = (3 / span,) * 3
    root.location = Vector((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z)) * (3 / span)
    for obj in list(scene.objects):
        if obj.type in {'CAMERA', 'LIGHT'}:
            bpy.data.objects.remove(obj, do_unlink=True)
    for arm in [o for o in scene.objects if o.type == 'ARMATURE']:
        arm.data.pose_position = 'REST'
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 8
    scene.cycles.use_denoising = True
    scene.cycles.device = 'CPU'
    scene.render.resolution_x = 640
    scene.render.resolution_y = 560
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = 'PNG'
    scene.use_nodes = False
    scene.world = bpy.data.worlds.new('Audit_World')
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get('Background')
    bg.inputs['Color'].default_value = (.14, .17, .20, 1)
    bg.inputs['Strength'].default_value = .65
    scene.view_settings.view_transform = 'AgX'
    for p, energy, size in [((1, -3, 5), 600, 5), ((-3, 1, 3), 500, 4), ((2, 4, 4), 700, 4)]:
        bpy.ops.object.light_add(type='AREA', location=p)
        lamp = bpy.context.object
        lamp.data.energy = energy
        lamp.data.shape = 'DISK'
        lamp.data.size = size
        lamp.rotation_euler = (Vector((0, 0, 1)) - lamp.location).to_track_quat('-Z', 'Y').to_euler()
    height = (hi.z - lo.z) * 3 / span
    center = Vector((0, 0, height * .48))
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = 4.1
    scene.camera = camera
    folder = OUT / 'previews' / report['id']
    folder.mkdir(parents=True, exist_ok=True)
    views = [('a', (4, -5, 3)), ('b', (-4, 5, 3)), ('front', (5, 0, .45)),
             ('side', (0, -5, .45)), ('top', (.01, 0, 7)), ('rear', (-5, 0, .45))]
    for name, direction in views:
        camera.location = center + Vector(direction)
        camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = str(folder / (name + '.png'))
        bpy.ops.render.render(write_still=True)
    print('MR_LIBRARY_PREVIEW', report['id'], flush=True)


def main():
    manifest = json.loads((OUT / 'inventory.json').read_text(encoding='utf-8'))
    wanted = [a for a in ARGS if not a.startswith('--')]
    reports = []
    for source in manifest['sources']:
        for relative in source['assets']:
            path = ROOT / relative
            if wanted and asset_id(path) not in wanted:
                continue
            report = inspect(path)
            reports.append({'id': report['id'], 'source': relative,
                            'triangles': sum(o.get('triangles', 0) for o in report['objects']),
                            'mesh_objects': sum(o['type'] == 'MESH' for o in report['objects']),
                            'dimensions': report['dimensions'], 'actions': len(report['actions']),
                            'missing_images': sum(not i['exists'] for i in report['images'])})
            if '--render' in ARGS:
                preview(report)
    (OUT / 'audit-summary.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
