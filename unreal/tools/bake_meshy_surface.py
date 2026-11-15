"""Rebake a dense supplied surface onto a reduced mesh with fresh game UVs."""
from pathlib import Path

import bpy


def bake_surface(high, low, folder, name, resolution=2048):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 8
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = 8
    bpy.ops.object.select_all(action='DESELECT')
    low.select_set(True)
    bpy.context.view_layer.objects.active = low
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=1.1519, island_margin=.006, area_weight=.3,
                             correct_aspect=True, scale_to_bounds=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    source = high.data.materials[0]
    bsdf = next(n for n in source.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    output = next(n for n in source.node_tree.nodes if n.type == 'OUTPUT_MATERIAL')
    original = [(l.from_socket, l.to_socket) for l in output.inputs['Surface'].links]
    target = bpy.data.materials.new('M_' + name + '_Baked')
    target.use_nodes = True
    shader = target.node_tree.nodes.get('Principled BSDF')
    low.data.materials.clear()
    low.data.materials.append(target)
    for face in low.data.polygons:face.material_index = 0
    emission = source.node_tree.nodes.new('ShaderNodeEmission')
    emission.inputs['Strength'].default_value = 1
    combine = source.node_tree.nodes.new('ShaderNodeCombineXYZ')
    source.node_tree.links.new(bsdf.inputs['Roughness'].links[0].from_socket, combine.inputs['Y']) if bsdf.inputs['Roughness'].is_linked else None
    source.node_tree.links.new(bsdf.inputs['Metallic'].links[0].from_socket, combine.inputs['Z']) if bsdf.inputs['Metallic'].is_linked else None
    combine.inputs['X'].default_value = 1
    if not bsdf.inputs['Roughness'].is_linked:combine.inputs['Y'].default_value = bsdf.inputs['Roughness'].default_value
    if not bsdf.inputs['Metallic'].is_linked:combine.inputs['Z'].default_value = bsdf.inputs['Metallic'].default_value
    scene.render.bake.use_selected_to_active = True
    scene.render.bake.use_clear = True
    scene.render.bake.margin = 12
    scene.render.bake.cage_extrusion = .025
    scene.render.bake.max_ray_distance = .10
    images = {}
    high.hide_render = False
    high.hide_set(False)
    for kind in ['BaseColor', 'ORM', 'Normal']:
        img = bpy.data.images.new('T_' + name + '_' + kind, width=resolution, height=resolution, alpha=False)
        img.colorspace_settings.name = 'sRGB' if kind == 'BaseColor' else 'Non-Color'
        node = target.node_tree.nodes.new('ShaderNodeTexImage')
        node.image = img
        target.node_tree.nodes.active = node
        if kind == 'BaseColor':
            color = bsdf.inputs['Base Color']
            if color.is_linked:
                source.node_tree.links.new(color.links[0].from_socket, emission.inputs['Color'])
            else:
                emission.inputs['Color'].default_value = color.default_value
            source.node_tree.links.new(emission.outputs[0], output.inputs['Surface'])
        elif kind == 'ORM':
            source.node_tree.links.new(combine.outputs[0], emission.inputs['Color'])
            source.node_tree.links.new(emission.outputs[0], output.inputs['Surface'])
        else:
            for origin, destination in original:source.node_tree.links.new(origin, destination)
        bpy.ops.object.select_all(action='DESELECT')
        high.select_set(True);low.select_set(True)
        bpy.context.view_layer.objects.active = low
        bpy.ops.object.bake(type='NORMAL' if kind == 'Normal' else 'EMIT')
        img.file_format = 'PNG'
        img.filepath_raw = str(folder / (img.name + '.png'))
        img.save()
        images[kind] = (img, node)
        print('MR_SURFACE_BAKED', name, kind, resolution, flush=True)
    source.node_tree.nodes.remove(emission);source.node_tree.nodes.remove(combine)
    for origin, destination in original:source.node_tree.links.new(origin, destination)
    target.node_tree.links.new(images['BaseColor'][1].outputs['Color'], shader.inputs['Base Color'])
    split = target.node_tree.nodes.new('ShaderNodeSeparateColor')
    target.node_tree.links.new(images['ORM'][1].outputs['Color'], split.inputs['Color'])
    target.node_tree.links.new(split.outputs['Green'], shader.inputs['Roughness'])
    target.node_tree.links.new(split.outputs['Blue'], shader.inputs['Metallic'])
    normal = target.node_tree.nodes.new('ShaderNodeNormalMap')
    target.node_tree.links.new(images['Normal'][1].outputs['Color'], normal.inputs['Color'])
    target.node_tree.links.new(normal.outputs['Normal'], shader.inputs['Normal'])
    bpy.data.objects.remove(high, do_unlink=True)
    scene.render.bake.use_selected_to_active = False
    return images
