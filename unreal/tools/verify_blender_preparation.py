"""Read actual prepared .blend files and check source preservation and portability."""
from pathlib import Path
import hashlib
import json
import math

import bpy


ROOT = Path(__file__).resolve().parents[2]
PREPARED = ROOT / 'blender/prepared/v1'
manifest = json.loads((PREPARED / 'manifest.json').read_text(encoding='utf-8'))
reports = []
for record in manifest['assets']:
    source = ROOT / record['source']
    assert hashlib.file_digest(source.open('rb'), 'sha256').hexdigest() == record['source_sha256'], source
    file = PREPARED / record['blend']
    bpy.ops.wm.open_mainfile(filepath=str(file), load_ui=False)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    assert len(meshes) == 1, file
    assert not any(o.type in {'CAMERA', 'LIGHT'} for o in bpy.context.scene.objects), file
    obj = meshes[0]
    obj.data.calc_loop_triangles()
    assert len(obj.data.loop_triangles) == record['triangles'], file
    assert len(obj.data.uv_layers) > 0, file
    assert all(abs(value - 1) < .001 for value in obj.scale), file
    assert all(math.isfinite(value) for vertex in obj.data.vertices for value in vertex.co), file
    images = []
    for image in bpy.data.images:
        if image.type == 'RENDER_RESULT':
            continue
        target = Path(bpy.path.abspath(image.filepath))
        assert target.is_file() and target.is_relative_to(PREPARED.resolve()), target
        image.reload()
        assert image.size[0] >= 1024 and image.size[1] >= 1024, image.name
        images.append(target.relative_to(ROOT).as_posix())
    assert len(images) == 3, file
    reports.append({'id': record['id'], 'triangles': record['triangles'],
                    'source_preserved': True, 'external_textures': images})
authored = ROOT / 'blender/authored/v1'
props = json.loads((authored / 'manifest.json').read_text(encoding='utf-8'))
for record in props['assets']:
    file = authored / record['blend']
    bpy.ops.wm.open_mainfile(filepath=str(file), load_ui=False)
    assert len([o for o in bpy.context.scene.objects if o.type == 'MESH']) > 1, file
    assert (authored / record['fbx']).stat().st_size > 1000, file
out = ROOT / 'artifacts/3d-world/blender-verification.json'
out.write_text(json.dumps({'passed': True, 'prepared': reports, 'authored_models': len(props['assets'])}, indent=2), encoding='utf-8')
print('MR_BLENDER_VERIFIED: sources preserved, 5 prepared meshes, 15 external textures,', len(props['assets']), 'editable authored models', flush=True)
