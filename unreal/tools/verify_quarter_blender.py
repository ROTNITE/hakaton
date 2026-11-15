"""Inspect saved v3 source geometry and preserve source-library hash evidence."""
from pathlib import Path
import hashlib
import json
import math
import bpy

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'artifacts/quarter-v3'
inventory=json.loads((ROOT/'artifacts/3d-world/asset-library/inventory.json').read_text(encoding='utf-8'))
for source in inventory['sources']:
    with (ROOT/source['source']).open('rb') as stream:
        assert hashlib.file_digest(stream,'sha256').hexdigest()==source['sha256'],source['source']
rows=[];glass_areas={}
for path in sorted((ROOT/'blender/prepared/v3').glob('*/asset.json')):
    record=json.loads(path.read_text(encoding='utf-8'))
    bpy.ops.wm.open_mainfile(filepath=str(path.parent/record['blend']),load_ui=False)
    assert bpy.context.scene.unit_settings.system=='METRIC'
    assert bpy.context.scene.unit_settings.scale_length==1
    for part in record['parts']:
        o=bpy.data.objects[part['object']]
        assert all(abs(s-1)<1e-5 for s in o.scale),o.name
        assert o.data.uv_layers,o.name
        assert all(math.isfinite(x) for v in o.data.vertices for x in v.co),o.name
        assert (path.parent/part['fbx']).stat().st_size>1000
        if record['id']=='GlazingKit':
            area=sum(f.area for f in o.data.polygons if o.data.materials[f.material_index] and
                     'GlassV3' in o.data.materials[f.material_index].name)
            glass_areas[o.name]=area
        rows.append({'asset':record['id'],'object':o.name,'vertices':len(o.data.vertices),
                     'height_m':o.dimensions.z,'bottom_m':min((o.matrix_world@v.co).z for v in o.data.vertices)})
    for im in bpy.data.images:
        if im.type=='IMAGE':
            assert not im.packed_file and Path(bpy.path.abspath(im.filepath)).is_file(),im.name
for i in range(1,4):
    prefix=f'window_0{i}_'
    clean=glass_areas[prefix+'clean']
    assert clean>.3
    assert .05<glass_areas[prefix+'broken']/clean<.8
    assert glass_areas[prefix+'empty']==0
report={'passed':True,'original_files_verified':len(inventory['sources']),'objects':rows,'glass_surface_areas_m2':glass_areas}
(OUT/'blender-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('MR_V3_BLENDER_VERIFIED',len(rows),'objects;',len(inventory['sources']),'source hashes')
