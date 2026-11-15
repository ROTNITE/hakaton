"""Prepare render meshes for the three physical competition media."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def material(name, rgb):
    value = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    value.diffuse_color = (*rgb, 1.)
    return value


def import_mesh(path, shade, offset=(0,0,0), *, ned=False):
    before = set(bpy.data.objects)
    if path.suffix == '.dae':
        bpy.ops.wm.collada_import(filepath=str(path))
    else:
        bpy.ops.wm.obj_import(filepath=str(path),forward_axis='NEGATIVE_Y',up_axis='Z')
    objects = [o for o in bpy.data.objects if o not in before and o.type=='MESH']
    if not objects:
        raise ValueError(f'No mesh in {path.name}')
    for obj in objects:
        vertices = len(obj.data.vertices)
        if vertices > 22000:
            bpy.context.view_layer.objects.active = obj
            simplifier = obj.modifiers.new('Realtime mesh reduction','DECIMATE')
            simplifier.ratio = min(1.,12000/vertices)
            bpy.ops.object.modifier_apply(modifier=simplifier.name)
        transform = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = Matrix.Identity(4)
        if ned:
            transform = Matrix.Diagonal((1.,-1.,-1.,1.)) @ transform
        obj.data.transform(Matrix.Translation(Vector(offset)) @ transform)
        obj.data.materials.clear()
        obj.data.materials.append(shade)
        for poly in obj.data.polygons:
            poly.material_index = 0
    return objects


def assembled_mesh(name, objects, limits, out):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    obj = bpy.context.object
    obj.name = 'SM_'+name
    obj.data.calc_loop_triangles()
    if len(obj.data.loop_triangles) > 28000:
        modifier = obj.modifiers.new('Realtime triangle budget','DECIMATE')
        modifier.ratio = 28000/len(obj.data.loop_triangles)
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    minimum = Vector(tuple(min(v.co[i] for v in obj.data.vertices) for i in range(3)))
    maximum = Vector(tuple(max(v.co[i] for v in obj.data.vertices) for i in range(3)))
    dimensions = maximum-minimum
    scale = min(a/b for a,b in zip(limits,dimensions))
    obj.data.transform(Matrix.Scale(scale,4) @ Matrix.Translation(-(maximum+minimum)/2.))
    obj.data.calc_loop_triangles()
    if not 30 <= len(obj.data.loop_triangles) <= 29000:
        raise ValueError(f'Unexpected triangle count for {name}: {len(obj.data.loop_triangles)}')
    fbx = out/(obj.name+'.fbx')
    blend = out/(obj.name+'.blend')
    bpy.ops.export_scene.fbx(filepath=str(fbx),use_selection=True,object_types={'MESH'},axis_forward='-Y',
                            axis_up='Z',apply_unit_scale=True,add_leaf_bones=False,bake_anim=False)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    return {'id':name,'fbx':fbx.name,'fbx_sha256':digest(fbx),'blend':blend.name,'blend_sha256':digest(blend),
            'triangles':len(obj.data.loop_triangles),'dimensions_m':list(dimensions*scale),
            'material_slots':[slot.material.name for slot in obj.material_slots]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('output',type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    source = args.source.resolve(strict=True)
    provenance = json.loads((source/'source-manifest.json').read_bytes())
    if any(digest(source/f['path'])!=f['sha256'] for f in provenance['files']):
        raise ValueError('Original model checksum changed')
    output = args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    models = []

    bpy.ops.wm.read_factory_settings(use_empty=True)
    clearpath = source/'husky/husky_description/meshes'
    yellow = material('SafetyYellow',(.92,.46,.055))
    rubber = material('DarkRubber',(.045,.05,.047))
    chassis = import_mesh(clearpath/'base_link.dae',yellow)
    wheels = [obj for x in (-.256,.256) for y in (-.2775,.2775) for obj in
              import_mesh(clearpath/'wheel.dae',rubber,(x,y,.03282))]
    models.append(assembled_mesh('HuskyTunnel',chassis+wheels,(1.09,.67,.49),output))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    boats = source/'stonefish/data/opti_blueboat'
    orange = material('SignalOrange',(.95,.27,.043))
    trim = material('DarkRubber',(.045,.05,.047))
    hulls = [obj for side in ('left','right') for obj in import_mesh(boats/(side+'_side_or.obj'),orange,ned=True)]
    stern = [obj for side in ('left','right') for obj in import_mesh(boats/(side+'_rear_or.obj'),trim,ned=True)]
    bpy.ops.mesh.primitive_cube_add(size=1.,location=(0,0,.12))
    connector = bpy.context.object
    connector.scale = (.63,.58,.06)
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    connector.data.materials.append(trim)
    models.append(assembled_mesh('BlueBoatSurface',hulls+stern+[connector],(1.41,.79,.43),output))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    rovs = source/'stonefish/data/bluerov2'
    teal = material('RescueTeal',(.045,.59,.57))
    dark = material('DarkRubber',(.045,.05,.047))
    body = import_mesh(rovs/'bluerov2.obj',teal,ned=True)
    wings = import_mesh(rovs/'bluerov2_wings.obj',dark,ned=True)
    models.append(assembled_mesh('BlueROV2Submerged',body+wings,(1.40,.79,.49),output))

    info = {'format':'metarescue.competition-render-assets.v1','blender':bpy.app.version_string,
            'source_manifest_sha256':digest(source/'source-manifest.json'),'assets':models,
            'contact_geometry':'unchanged native AMRAgent box collision'}
    (output/'prepared.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
