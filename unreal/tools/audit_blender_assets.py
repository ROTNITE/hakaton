"""Inspect source .blend assets without saving them; run with Blender --background."""
from pathlib import Path
import hashlib
import json
import sys

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts' / '3d-world' / 'asset-audit'


def inspect(path):
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    rows = []
    for obj in bpy.data.objects:
        row = {'name': obj.name, 'type': obj.type, 'location': list(obj.location),
               'rotation': list(obj.rotation_euler), 'scale': list(obj.scale)}
        if obj.type == 'MESH':
            obj.data.calc_loop_triangles()
            bounds = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
            row.update(vertices=len(obj.data.vertices), polygons=len(obj.data.polygons),
                       triangles=len(obj.data.loop_triangles), uv_layers=list(obj.data.uv_layers.keys()),
                       dimensions=list(obj.dimensions),
                       bounds_min=[min(c[i] for c in bounds) for i in range(3)],
                       bounds_max=[max(c[i] for c in bounds) for i in range(3)],
                       materials=[slot.material.name if slot.material else None for slot in obj.material_slots])
        rows.append(row)
    materials = []
    for material in bpy.data.materials:
        nodes = []
        if material.use_nodes:
            for node in material.node_tree.nodes:
                item = {'name': node.name, 'type': node.type}
                if node.type == 'TEX_IMAGE' and node.image:
                    item.update(image=node.image.name, colorspace=node.image.colorspace_settings.name)
                if node.type == 'BSDF_PRINCIPLED':
                    item['inputs'] = {s.name: {'linked': s.is_linked, 'value': list(s.default_value)
                        if hasattr(s.default_value, '__len__') else s.default_value}
                        for s in node.inputs if s.name in ['Base Color', 'Roughness', 'Metallic', 'Normal']}
                nodes.append(item)
        materials.append({'name': material.name, 'nodes': nodes})
    images = [{'name': img.name, 'size': list(img.size), 'packed': bool(img.packed_file),
               'filepath': img.filepath, 'colorspace': img.colorspace_settings.name}
              for img in bpy.data.images if img.type != 'RENDER_RESULT']
    report = {'source': path.relative_to(ROOT).as_posix(),
              'sha256': hashlib.file_digest(path.open('rb'), 'sha256').hexdigest(),
              'blender_version': bpy.app.version_string, 'unit_system': bpy.context.scene.unit_settings.system,
              'unit_scale': bpy.context.scene.unit_settings.scale_length,
              'objects': rows, 'materials': materials, 'images': images}
    output = OUT / (path.stem + '.json')
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('MR_ASSET_AUDIT:', json.dumps({'source': path.name,
          'meshes': len([r for r in rows if r['type'] == 'MESH']),
          'triangles': sum(r.get('triangles', 0) for r in rows), 'images': len(images)}), flush=True)


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    files = [Path(p) for p in sys.argv[sys.argv.index('--') + 1:]] if '--' in sys.argv else sorted((ROOT / 'blender').glob('*.blend'))
    for file in files:
        inspect(file)
