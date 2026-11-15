"""Generate local bounding boxes for static base infrastructure from imported UE meshes."""
from pathlib import Path
import hashlib
import itertools
import json
import math

import unreal


content = Path(unreal.Paths.project_content_dir()).resolve()
library_path = content / 'Scenario/library-v3.json'
library_bytes = library_path.read_bytes()
library = json.loads(library_bytes)
names = {'Medical', 'Generator', 'Sensor', 'UtilityBox'}
result = {'format': 'metarescue.base-assets.r1',
          'library_sha256': hashlib.sha256(library_bytes).hexdigest(), 'assemblies': {}}

for asset in library['assets']:
    if asset['id'] not in names:
        continue
    points = []
    for part in asset['parts']:
        if part['role'] in ('glass', 'beacon'):
            continue
        if part['parent'] is not None:
            raise ValueError('Expected root-level base assembly parts')
        mesh = unreal.load_asset(part['mesh'])
        if not isinstance(mesh, unreal.StaticMesh):
            raise ValueError('Missing base part ' + part['mesh'])
        bounds = mesh.get_bounds()
        center = bounds.origin.to_tuple()
        extent = bounds.box_extent.to_tuple()
        roll, pitch, yaw = part['rotation_deg']
        if abs(roll) > .0001 or abs(pitch) > .0001:
            raise ValueError('Base asset bounds require an upright part')
        sine, cosine = math.sin(math.radians(-yaw)), math.cos(math.radians(-yaw))
        tx, ty, tz = part['location_m']
        for sx, sy, sz in itertools.product((-1, 1), repeat=3):
            x, y, z = [value + sign * half for value, sign, half in
                       zip(center, (sx, sy, sz), extent)]
            points.append(((cosine*x - sine*y)/100 + tx, (sine*x + cosine*y)/100 - ty, z/100 + tz))
    result['assemblies'][asset['id']] = {
        'min': [round(min(p[i] for p in points), 6) for i in range(3)],
        'max': [round(max(p[i] for p in points), 6) for i in range(3)],
    }

if result['assemblies'].keys() != names:
    raise ValueError('Incomplete base asset library')
output = Path('D:/MetaRescue-output/city-assets/base-assets-r1.json')
with output.open('x', encoding='utf-8') as stream:
    json.dump(result, stream, indent=2)
    stream.write('\n')
unreal.log('MR_BASE_ASSETS_MEASURED ' + str(output))
