"""Create v3 glazing, room and debris modules without changing any v2 files."""
from pathlib import Path
import math
import random
import sys

import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_mechanized_assets as rig

rig.OUT = rig.ROOT / 'blender/prepared/v3'
SOURCE = rig.ROOT / 'blender/prepared/v2/UrbanKit/UrbanKit.blend'


def join_module(objects, name):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects: obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    obj = bpy.context.object
    obj.name = name
    # Modules are inserted at a caller-specified datum; the assembly loader
    # intentionally drops catalog translations. Bake the active joined object's
    # transform so its FBX remains in the same zero-based module coordinates.
    obj.data.transform(obj.matrix_world)
    obj.matrix_world = Matrix.Identity(4)
    rig.register(obj, 'module')
    return obj


def mask_texture():
    size = 512
    y, x = np.mgrid[0:size, 0:size] / (size - 1)
    crack = np.zeros((size, size), dtype=np.float32)
    rng = random.Random(381)
    for angle in [i * math.tau / 9 + rng.uniform(-.13, .13) for i in range(9)]:
        a = np.array([.42, .58]); direction = np.array([math.cos(angle), math.sin(angle)])
        for step in range(5):
            b = a + direction * rng.uniform(.09, .19) + np.array([rng.uniform(-.03, .03), rng.uniform(-.03, .03)])
            dx, dy = b - a
            t = np.clip(((x-a[0])*dx+(y-a[1])*dy)/max(1e-8,dx*dx+dy*dy),0,1)
            d = np.sqrt((x-a[0]-t*dx)**2+(y-a[1]-t*dy)**2)
            crack = np.maximum(crack,np.clip((.0035-d)*450,0,1))
            a = b
    dirt = np.clip(.17+.12*np.sin(x*23+y*4)*np.sin(y*17)+.08*np.sin(x*89+y*63),0,1)
    rgba = np.dstack([crack,dirt,np.maximum(crack*.7,dirt*.3),np.ones_like(crack)])
    image = bpy.data.images.new('GlassV3_CrackDirt_Mask',width=size,height=size)
    image.colorspace_settings.name='Non-Color'
    image.pixels.foreach_set(rgba.astype(np.float32).ravel())
    image.update()
    return image


def glazing():
    bpy.ops.wm.open_mainfile(filepath=str(SOURCE),load_ui=False)
    originals = [bpy.data.objects['window_centered_large_0'+str(i)] for i in [1,2,3]]
    templates = [(o.data.copy(),o.name) for o in originals]
    for obj in list(bpy.data.objects):bpy.data.objects.remove(obj,do_unlink=True)
    rig.PARTS.clear();rig.REPAIRS.clear()
    mask = mask_texture()
    glasses = {}
    for style, roughness in [('clean',.055),('dirty',.20),('cracked',.15),('broken',.21)]:
        mat = rig.material('M_GlassV3_'+style,(.82,.89,.87),0,roughness,True)
        shader=mat.node_tree.nodes.get('Principled BSDF')
        shader.inputs['IOR'].default_value=1.5
        node=mat.node_tree.nodes.new('ShaderNodeTexImage');node.image=mask
        node.name='CrackDirtMask'
        glasses[style]=mat
    for number,(mesh,original_name) in enumerate(templates,1):
        glass_slots={i for i,m in enumerate(mesh.materials) if m and 'glass' in m.name.lower()}
        glass_points=[mesh.vertices[v].co.copy() for f in mesh.polygons if f.material_index in glass_slots for v in f.vertices]
        low=Vector(tuple(min(v[a] for v in glass_points) for a in range(3)))
        high=Vector(tuple(max(v[a] for v in glass_points) for a in range(3)))
        for style in ['clean','dirty','cracked','broken','empty']:
            frame=bpy.data.objects.new('Frame',mesh.copy());bpy.context.collection.objects.link(frame)
            bm=bmesh.new();bm.from_mesh(frame.data)
            bmesh.ops.delete(bm,geom=[f for f in bm.faces if f.material_index in glass_slots],context='FACES')
            bm.to_mesh(frame.data);bm.free()
            objects=[frame]
            if style!='empty':
                # One thin pane or retained perimeter shards with a real central hole.
                coords=[(0,0),(1,0),(1,1),(0,1)]
                faces=[(0,1,2,3)]
                if style=='broken':
                    coords += [(.23,.18),(.73,.27),(.8,.72),(.26,.86)]
                    faces=[(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
                vertices=[(low.x+u*(high.x-low.x),float((low.y+high.y)/2),low.z+v*(high.z-low.z)) for u,v in coords]
                pane_mesh=bpy.data.meshes.new('Pane');pane_mesh.from_pydata(vertices,[],faces);pane_mesh.update()
                pane=bpy.data.objects.new('Glass',pane_mesh);bpy.context.collection.objects.link(pane)
                pane.data.materials.append(glasses[style]);objects.append(pane)
                uv=pane_mesh.uv_layers.new(name='UVMap')
                for poly in pane_mesh.polygons:
                    for loop in poly.loop_indices:uv.data[loop].uv=coords[pane_mesh.loops[loop].vertex_index]
            join_module(objects,f'window_0{number}_{style}')
    rig.REPAIRS.extend(['15 separate window modules: clean, dirty, cracked, real perimeter shards and empty frame for each source size.',
                        'External deterministic crack/dirt mask; original frame textures and v2 library preserved.'])
    return rig.export_asset('GlazingKit',SOURCE)


def props():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    rig.PARTS.clear();rig.REPAIRS.clear()
    concrete=rig.material('M_V3_Concrete',(.28,.27,.24),0,.95)
    brick=rig.material('M_V3_Brick',(.27,.12,.07),0,.96)
    plaster=rig.material('M_V3_Plaster',(.47,.43,.34),0,.92)
    metal=rig.material('M_V3_Rust',(.16,.075,.035),.55,.76)
    wood=rig.material('M_V3_Wood',(.14,.10,.065),0,.87)
    cloth=rig.material('M_V3_Fabric',(.11,.14,.12),0,.96)
    # Distinct fractured pieces. Manufactured bevel cubes made every break look
    # like a clean masonry display; remove irregular corners and cap the breaks.
    def fracture(obj, seed):
        rng = random.Random(seed)
        bm=bmesh.new();bm.from_mesh(obj.data)
        for face in bm.faces:face.smooth=False
        dims=obj.dimensions.copy()
        for sx,sy,sz in [(-1,1,1),(1,-1,-1),(1,1,1)]:
            normal=Vector((sx*rng.uniform(.7,1.1),sy*rng.uniform(.7,1.1),sz*rng.uniform(.7,1.1))).normalized()
            corner=Vector((sx*dims.x*.5,sy*dims.y*.5,sz*dims.z*.5))
            plane=corner-normal*min(dims)*rng.uniform(.18,.42)
            result=bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),
                dist=.00001,plane_co=plane,plane_no=normal,clear_outer=True,clear_inner=False)
            edges=[e for e in result['geom_cut'] if isinstance(e,bmesh.types.BMEdge) and e.is_boundary]
            bmesh.ops.holes_fill(bm,edges=edges,sides=0)
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(obj.data);bm.free()
        rig.activate(obj);bpy.ops.object.mode_set(mode='EDIT');bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.smart_project(island_margin=.025);bpy.ops.object.mode_set(mode='OBJECT')
        obj.data.update()
    # Distinct, editable individual debris, each grounded at z=0.
    for i,(dims,mat) in enumerate([((.26,.12,.09),brick),((.21,.105,.075),brick),
                                  ((.58,.40,.19),concrete),((.83,.57,.25),concrete),
                                  ((1.8,.22,1.1),plaster)]):
        obj=rig.cube('fragment_'+str(i),(0,0,0),dims,mat,0)
        fracture(obj,192+i)
        obj.location.z=-min(v.co.z for v in obj.data.vertices)
        if i==4:
            pieces=[obj]
            for x in [-.55,.15,.66]:
                pieces.append(rig.cylinder('ExposedRebar',(x,.015,1.13),.008,.42,metal,axis='Z',vertices=8))
            obj=join_module(pieces,'fragment_'+str(i))
            # join_module registers; export only one entry for this piece.
            rig.PARTS.pop()
        rig.origin(obj,Vector((0,0,0)));rig.register(obj,'module')
    # Reusable small room assemblies: floor datum, no catalog offset.
    for style in range(3):
        objects=[]
        def box(name,p,s,mat):
            o=rig.cube(name,p,s,mat,.012);objects.append(o);return o
        if style==0:
            box('CouchSeat',(0,.5,.38),(1.7,.7,.27),cloth)
            box('CouchBack',(0,.85,.73),(1.7,.16,.74),cloth)
            for x in [-.78,.78]:box('CouchArm',(x,.5,.58),(.15,.7,.55),cloth)
            for x in [-.66,.66]:
                for y in [.25,.76]:box('CouchFoot',(x,y,.1225),(.075,.075,.245),wood)
            box('Table',(0,-.7,.49),(.9,.55,.055),wood)
            for x in [-.36,.36]:
                for y in [-.89,-.51]:box('Leg',(x,y,.23),(.045,.045,.46),metal)
        elif style==1:
            box('Desk',(0,.55,.74),(1.45,.6,.07),wood)
            for x in [-.62,.62]:box('DeskPanel',(x,.55,.37),(.06,.55,.74),wood)
            box('Cabinet',(1.2,.7,.85),(.55,.4,1.7),wood)
            for z in [.45,.9,1.35]:box('Shelf',(1.2,.48,z),(.48,.02,.025),metal)
        else:
            box('Mattress',(0,.2,.35),(.9,1.9,.24),cloth)
            box('Bed',(0,.2,.14),(.97,1.98,.20),wood)
            for x in [-.39,.39]:
                for y in [-.65,1.05]:box('BedFoot',(x,y,.02),(.07,.07,.04),wood)
            box('Pillow',(0,.83,.51),(.65,.36,.10),plaster)
            box('Bedside',(1,.6,.4),(.45,.45,.8),wood)
        join_module(objects,'room_'+str(style))
    # A few functional parcels and roofs make the same street modules read as a
    # neighbourhood. These remain separate reusable models rather than one city.
    objects=[rig.cube('Seat',(0,0,.46),(1.65,.38,.07),wood,0),
             rig.cube('Back',(0,.17,.76),(1.65,.065,.48),wood,0)]
    for x in [-.62,.62]:objects.append(rig.cube('BenchLeg',(x,0,.23),(.065,.33,.46),metal,0))
    join_module(objects,'courtyard_bench')
    objects=[]
    for x in [-.42,.42]:
        objects.extend([rig.cube('WasteBin',(x,0,.48),(.58,.65,.92),cloth,.015),
                        rig.cube('BinLid',(x,-.015,.95),(.63,.71,.07),metal,.008)])
        for side in [-1,1]:objects.append(rig.cylinder('BinWheel',(x+side*.23,.25,.06),.06,.045,metal,axis='Y',vertices=12))
    join_module(objects,'service_bins')
    objects=[rig.cube('Housing',(0,0,.3),(1.2,.8,.6),plaster,.015)]
    for z in [.12,.21,.30,.39,.48]:objects.append(rig.cube('Vent',(0,-.408,z),(1.05,.015,.035),metal,0))
    for x in [-.43,.43]:objects.append(rig.cube('Feet',(x,0,.035),(.10,.94,.07),metal,0))
    join_module(objects,'roof_vent')
    rig.REPAIRS.append('Chipped closed debris with UVs, exposed rebar, three room modules, courtyard bench, utility bins and roof vent; original v2 unchanged.')
    return rig.export_asset('SceneryKit',SOURCE)


def ruins():
    source=rig.ROOT/'blender/prepared/v2/Building/Building.blend'
    bpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False)
    template=bpy.data.objects['Building'].data.copy()
    for obj in list(bpy.data.objects):bpy.data.objects.remove(obj,do_unlink=True)
    rig.PARTS.clear();rig.REPAIRS.clear()
    for name,height in [('ruin_full',None),('ruin_low',3.25)]:
        obj=bpy.data.objects.new(name,template.copy());bpy.context.collection.objects.link(obj)
        if height is not None:
            bm=bmesh.new();bm.from_mesh(obj.data)
            bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=.0001,
                plane_co=Vector((0,0,height)),plane_no=Vector((.06,-.04,1)),clear_outer=True,clear_inner=False)
            bm.to_mesh(obj.data);bm.free()
        rig.register(obj,'module')
    rig.REPAIRS.append('Original textured ruin plus a genuinely cut low ruin; empty damaged window apertures, original v2 unchanged.')
    return rig.export_asset('BuildingVariants',source)


if __name__=='__main__':
    names=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else ['glazing','props','ruins']
    for name in names:globals()[name]()
