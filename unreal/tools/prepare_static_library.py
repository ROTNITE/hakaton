"""Prepare supplied scenery and modular kits, retaining each usable module separately."""
from pathlib import Path
import json
import math
import sys

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_mechanized_assets as rig


ROOT = rig.ROOT
SPECS = {
    'Relay': ('Emergency_Radio_Relay', 2.8, 2, 16000),
    'Stretcher': ('Rescue_Stretcher', 2.05, 0, 16000),
    'WindowWall': ('Wall_Module_with_Window', 3.2, 2, 18000),
    'Doorway': ('Wall_Module_with_Doorway', 3.2, 2, 18000),
    'Building': ('Damaged_Building', 9.6, 2, 90000),
    'Rubble': ('Static_Rubble_Pile', 3.4, 0, 30000),
    'Slab': ('Concrete_Slab_Fragment', 2.4, 0, 7000),
    'MannequinStatic': ('Rescue_Training_Mannequin', 1.75, 2, 16000),
    'Dock': ('Rescue_Rover_Docking_Station', 3.6, 0, 18000),
}
KITS = {'Barrier': 'concrete_road_barrier_02', 'Hydrant': 'fire_hydrant',
        'FenceKit': 'modular_chainlink_fence', 'CableKit': 'modular_electric_cables',
        'PipeKit': 'modular_industrial_pipes_01', 'UrbanKit': 'modular_urban_apartments_facade',
        'Generator': 'portable_generator', 'Streetlight': 'streetlight',
        'UtilityBox': 'utility_box_02', 'Manhole': 'water_manhole_cover'}


def simple(name):
    token, size, axis, budget = SPECS[name]
    rig.SPECS[name] = (token, size, axis, budget, False)
    rig.PARTS.clear();rig.REPAIRS.clear()
    source, body = rig.load_body(name)
    body.name = name
    rig.register(body, 'static')
    if name == 'Building':
        glass = rig.material('M_Rig_Glass', (.73,.84,.86), 0, .14, True)
        # Facade centers are measured from saved orthographic renders and BVH
        # probes. Ground-floor broken openings remain empty.
        for y in [.97,-1.25]:
            for z in [1.65,4.4,7.2]:
                if y<0 and z<2:continue
                rig.bisect_box(body,(-7,y-.57,z-.55),(-5,y+.57,z+.55))
                _, count = rig.edit_faces(body,lambda p,y=y,z=z:p.x < -5.0 and abs(p.y-y)<.57 and abs(p.z-z)<.55)
                rig.register(rig.cube('RearWindowGlass',(-5.55,y,z),(.018,1.10,1.06),glass,.002),'glass',removed_infill_faces=count)
        for z in [4.4,7.2]:
            rig.bisect_box(body,(2.2,.24,z-.55),(3,.78,z+.55))
            _,count=rig.edit_faces(body,lambda p,z=z:2.2<p.x<3.0 and abs(p.y-.51)<.27 and abs(p.z-z)<.55)
            rig.register(rig.cube('FrontWindowGlass',(2.59,.51,z),(.018,.50,1.06),glass,.002),'glass',removed_infill_faces=count)
        rig.REPAIRS.append('Seven surviving facade panes converted to real glazing after measured aperture cuts; broken ground openings remain open.')
    rig.REPAIRS.append('Meter scale, ground pivot, UV-preserving reduction; source untouched.')
    return rig.export_asset(name, source)


def kit(name):
    rig.PARTS.clear();rig.REPAIRS.clear()
    token = KITS[name]
    inventory = json.loads((rig.AUDIT / 'inventory.json').read_text(encoding='utf-8'))
    source = next(ROOT / p for item in inventory['sources'] for p in item['assets'] if Path(p).stem.removesuffix('_4k') == token)
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False)
    import re
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH' and not re.search(r'_LOD[1-9]', o.name)]
    for obj in list(bpy.data.objects):
        if obj not in meshes:
            bpy.data.objects.remove(obj, do_unlink=True)
    for obj in meshes:
        if obj.animation_data:
            obj.animation_data_clear()
        world = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = world
        rig.activate(obj)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        lo = Vector(tuple(min((obj.matrix_world @ Vector(p))[i] for p in obj.bound_box) for i in range(3)))
        hi = Vector(tuple(max((obj.matrix_world @ Vector(p))[i] for p in obj.bound_box) for i in range(3)))
        center = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
        # The editable catalog retains source arrangement; each exported module
        # has a usable ground origin independent of that arrangement.
        obj.data.transform(Matrix.Translation(-center) @ obj.matrix_world)
        obj.matrix_world = Matrix.Translation(center)
        if name == 'UrbanKit' and obj.name.startswith('wall_') and obj.dimensions.y < .01:
            mod = obj.modifiers.new('PhysicalWallThickness', 'SOLIDIFY')
            mod.thickness = .18
            mod.offset = 0
            bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(38), keep_sharp_edges=True)
        rig.register(obj, 'module', catalog_position_m=list(center))
    if name == 'UrbanKit':
        for mat in bpy.data.materials:
            if 'glass' not in mat.name.lower():
                continue
            shader = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
            for pin in ['Base Color', 'Metallic', 'Roughness', 'Alpha']:
                for link in list(shader.inputs[pin].links):
                    mat.node_tree.links.remove(link)
            shader.inputs['Base Color'].default_value = (.72, .84, .88, 1)
            shader.inputs['Metallic'].default_value = 0
            shader.inputs['Roughness'].default_value = .11
            shader.inputs['Transmission Weight'].default_value = 1
            shader.inputs['Alpha'].default_value = 1
        rig.REPAIRS.append('Real transmission glass replaces opaque window slot; planar walls gain 18 cm thickness; each of 147 modules exported separately.')
    if name == 'Streetlight':
        body = meshes[0]
        # This source was authored 4.47 m below the world origin. Keep its
        # catalog datum in metadata, but place the usable assembly on ground.
        body.location = (0,0,0)
        body.data.materials.clear()
        metal = rig.material('M_Streetlight_Metal', (.16, .18, .17), .72, .4)
        lens = rig.material('M_Streetlight_Lens', (.8, .86, .77), .05, .24)
        shader = lens.node_tree.nodes.get('Principled BSDF')
        shader.inputs['Emission Color'].default_value = (.9, 1, .75, 1)
        shader.inputs['Emission Strength'].default_value = 3
        body.data.materials.append(metal);body.data.materials.append(lens)
        for face in body.data.polygons:
            if face.center.z > 4.5 and face.normal.z < -.45:
                face.material_index = 1
        rig.REPAIRS.append('Removed the source catalog offset so the complete 5.34 m pole stands above ground.')
        rig.REPAIRS.append('Replaced white placeholder with metal pole and a separate emitting lens material.')
    if name == 'Generator':
        # Keep rubber feet stationary; the engine block gets a small local idle vibration.
        engine = max(meshes, key=lambda o: len(o.data.vertices))
        home = engine.location.copy()
        for frame, offset in [(1, 0), (3, .0008), (5, -.0008), (7, 0)]:
            engine.location = home + Vector((0, 0, offset))
            engine.keyframe_insert(data_path='location', index=2, frame=frame)
        engine.animation_data.action.name = 'GeneratorIdle'
        rig.REPAIRS.append('Discarded zero-duration source action; tiny engine idle action, no random movement of the station.')
    result = rig.export_asset(name, source)
    result['kind'] = 'modular_catalog' if name.endswith('Kit') or name == 'Hydrant' else 'static_assembly'
    (rig.OUT / name / 'asset.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    names = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else list(SPECS) + list(KITS)
    for name in names:
        simple(name) if name in SPECS else kit(name)
