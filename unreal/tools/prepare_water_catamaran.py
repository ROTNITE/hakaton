"""Create a separate, measured UE derivative of the user-supplied catamaran.

Run Blender --background --factory-startup --disable-autoexec --python-exit-code 1
--python this_script -- --source SOURCE.blend --output NEW_DIR --workspace ROOT.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def bounds(obj):
    corners=[obj.matrix_world@Vector(c) for c in obj.bound_box]
    return ([min(c[a] for c in corners) for a in range(3)],
            [max(c[a] for c in corners) for a in range(3)])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--length',type=float,default=4.6)
    parser.add_argument('--triangles',type=int,default=140000)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    source=args.source.resolve(strict=True);output=args.output.resolve()
    if output==source.parent or not 3.8<=args.length<=6 or not 80000<=args.triangles<=200000:
        raise ValueError('Invalid derivative directory, length or triangle budget')
    output.mkdir(parents=True,exist_ok=False)
    original_sha=digest(source)
    bpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False,use_scripts=False)
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    if len(meshes)!=1:raise ValueError('The audited source must contain exactly one visual shell')
    obj=meshes[0]
    for other in list(bpy.data.objects):
        if other!=obj:bpy.data.objects.remove(other,do_unlink=True)
    bpy.context.view_layer.objects.active=obj;obj.select_set(True)
    # Source inspection: the twin jet housings face +X; the bow faces -X.
    obj.rotation_euler.z+=math.pi
    bpy.ops.object.transform_apply(location=False,rotation=True,scale=True)
    low,high=bounds(obj);scale=args.length/(high[0]-low[0])
    obj.scale=(scale,)*3
    bpy.ops.object.transform_apply(location=False,rotation=True,scale=True)
    low,high=bounds(obj)
    offset=Vector(((low[0]+high[0])*.5,(low[1]+high[1])*.5,low[2]))
    obj.location-=offset
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    obj.data.calc_loop_triangles();before=len(obj.data.loop_triangles)
    reference_data=obj.data
    reference_points=[obj.data.vertices[i].co.copy() for i in range(0,len(obj.data.vertices),max(1,len(obj.data.vertices)//2500))]
    modifier=obj.modifiers.new('GameVisualBudget','DECIMATE')
    modifier.ratio=min(1,args.triangles/before);modifier.use_collapse_triangulate=True
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.data.calc_loop_triangles();after=len(obj.data.loop_triangles)
    if after>args.triangles*1.05 or after<args.triangles*.85:
        raise ValueError('Unexpected decimation result: '+str(after))
    tree=BVHTree.FromObject(obj,bpy.context.evaluated_depsgraph_get())
    distances=[]
    for point in reference_points:
        result=tree.find_nearest(point)
        if result[0] is None:raise ValueError('Could not compare the reduced surface')
        distances.append(result[3])
    distances.sort()
    errors={'sample_count':len(distances),'p95_m':distances[int(.95*(len(distances)-1))],
            'max_m':distances[-1]}
    if errors['p95_m']>.025 or errors['max_m']>.12:
        raise ValueError('Reduced hull loses too much of its audited geometry: '+json.dumps(errors))
    if reference_data!=obj.data and reference_data.users==0:bpy.data.meshes.remove(reference_data)
    obj.name='SM_RescueWaterCatamaran';obj.data.name=obj.name+'_Geometry'
    bpy.context.scene.unit_settings.system='METRIC';bpy.context.scene.unit_settings.scale_length=1
    material=obj.data.materials[0]
    bsdf=next(n for n in material.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    links=[{'from_node':l.from_node.name,'from_socket':l.from_socket.name,
            'to_node':l.to_node.name,'to_socket':l.to_socket.name} for l in material.node_tree.links]
    textures={};used=[]
    for node in material.node_tree.nodes:
        if node.type!='TEX_IMAGE' or node.image is None:continue
        outgoing=[l for l in material.node_tree.links if l.from_node==node]
        if any(l.to_node==bsdf and l.to_socket.name=='Base Color' for l in outgoing):kind='BaseColor'
        elif any(l.to_node.type=='NORMAL_MAP' for l in outgoing):kind='Normal'
        elif any(l.to_node.type in ('SEPRGB','SEPARATE_COLOR') for l in outgoing):kind='ORM'
        else:raise ValueError('Unsupported source texture routing: '+node.name)
        if kind in textures:raise ValueError('Ambiguous source map: '+kind)
        image=node.image.copy()
        if max(image.size)>2048:image.scale(2048,2048)
        path=output/f'T_RescueWaterCatamaran_{kind}.png'
        image.file_format='PNG';image.filepath_raw=str(path);image.save()
        derivative=bpy.data.images.load(str(path),check_existing=False)
        derivative.name=path.stem;derivative.colorspace_settings.name='sRGB' if kind=='BaseColor' else 'Non-Color'
        derivative.pack();node.image=derivative
        textures[kind]={'path':path.name,'bytes':path.stat().st_size,'sha256':digest(path),'size':list(derivative.size)}
        used.append(derivative)
        bpy.data.images.remove(image)
    if set(textures)!={'BaseColor','Normal','ORM'}:raise ValueError('Audited PBR map set differs')
    for image in list(bpy.data.images):
        if image not in used and image.users==0:bpy.data.images.remove(image)
    material.name='M_RescueWaterCatamaran'
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
    blend=output/'RescueWaterCatamaran.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend),relative_remap=False)
    fbx=output/'RescueWaterCatamaran.fbx'
    bpy.ops.export_scene.fbx(filepath=str(fbx),use_selection=True,object_types={'MESH'},add_leaf_bones=False,
        apply_unit_scale=True,apply_scale_options='FBX_SCALE_UNITS',axis_forward='-Y',axis_up='Z',
        path_mode='RELATIVE',use_mesh_modifiers=True,bake_anim=False)
    low,high=bounds(obj)
    assert digest(source)==original_sha,'Original source changed during preparation'
    report={'format':'metarescue.water-catamaran.r1','source_name':source.name,'source_sha256':original_sha,
        'original_preserved':True,'license':'user-supplied; no public redistribution claim',
        'source_forward_axis':'-X','prepared_forward_axis':'+X','source_triangles':before,'triangles':after,
        'bounds_m':{'min':low,'max':high},'dimensions_m':list(obj.dimensions),'surface_deviation':errors,
        'textures':textures,'original_material_links':links,
        'mesh':{'path':fbx.name,'bytes':fbx.stat().st_size,'sha256':digest(fbx)},
        'blend':{'path':blend.name,'bytes':blend.stat().st_size,'sha256':digest(blend)},
        'collision':'visual shell only; independent hull/jet/cargo physics still to implement',
        'status':'prepared; native import and loaded water evacuation not yet accepted'}
    (output/'manifest.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    sys.path.insert(0,str(args.workspace.resolve()/'unreal/tools'))
    from prepare_blender_assets import render_preview
    render_preview(obj,'RescueWaterCatamaran-prepared-front',-.7,args.length)
    render_preview(obj,'RescueWaterCatamaran-prepared-rear',2.4,args.length)
    print('MR_CATAMARAN_PREPARED '+json.dumps(report),flush=True)

if __name__=='__main__':main()
