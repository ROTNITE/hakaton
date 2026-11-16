"""Bake the CC0 JangaFX fire cache to transparent, camera-matched atlases.

Run the installed Blender with --background --factory-startup --disable-autoexec
--python-exit-code 1 --python this_script -- --source VDB_DIRECTORY --output NEW_DIR.
Original VDBs are read-only. Runtime Niagara needs only the small PNG atlases.
"""
from array import array
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import bpy
from mathutils import Vector


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frames', type=int, choices=(16, 64), default=64)
    parser.add_argument('--size', type=int, choices=(128, 256, 512), default=256)
    parser.add_argument('--samples', type=int, choices=(8, 16, 32), default=16)
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--temperature-scale', type=float, default=12000)
    parser.add_argument('--density-scale', type=float, default=.06)
    return parser.parse_args(sys.argv[sys.argv.index('--') + 1:])


def configure_volume(scene, source, temperature_scale, density_scale):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.object.volume_import(filepath=str(source))
    volume = bpy.context.object
    volume.data.grids.load()
    if not {'flames', 'temperature'} <= {grid.name for grid in volume.data.grids}:
        raise ValueError('Expected the inspected JangaFX fire/temperature fields')
    low = Vector(tuple(min(vertex[axis] for vertex in volume.bound_box) for axis in range(3)))
    high = Vector(tuple(max(vertex[axis] for vertex in volume.bound_box) for axis in range(3)))
    scale = 3.0 / max(high - low)
    volume.scale = (scale,) * 3
    volume.location = (-(low.x + high.x) * scale / 2,
                       -(low.y + high.y) * scale / 2, -low.z * scale)
    material = bpy.data.materials.new('M_JangaFX_Fire_Bake')
    material.use_nodes = True
    if hasattr(material.cycles, 'volume_interpolation'):
        material.cycles.volume_interpolation = 'CUBIC'
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    shader = nodes.new('ShaderNodeVolumePrincipled')
    shader.inputs['Density'].default_value = density_scale
    shader.inputs['Density Attribute'].default_value = 'flames'
    shader.inputs['Color'].default_value = (.16, .035, .008, 1)
    # EmberGen exports its blackbody driving field as "flames". The vendor's
    # documented binding retains hot cores and cooler tongues instead of
    # tinting the entire occupied volume one flat orange.
    shader.inputs['Temperature Attribute'].default_value = 'flames'
    shader.inputs['Temperature'].default_value = temperature_scale
    shader.inputs['Blackbody Intensity'].default_value = 1
    links = material.node_tree.links
    # The demonstration cache includes a luminous emitter emblem at its foot.
    # Remove that source geometry in volume space, including the overhead view;
    # the runtime asset must contain flame only, without a visible pedestal.
    position = nodes.new('ShaderNodeNewGeometry')
    xyz = nodes.new('ShaderNodeSeparateXYZ')
    links.new(position.outputs['Position'], xyz.inputs[0])
    mask = nodes.new('ShaderNodeMapRange')
    mask.clamp = True
    mask.interpolation_type = 'SMOOTHERSTEP'
    mask.inputs['From Min'].default_value = .62
    mask.inputs['From Max'].default_value = .88
    links.new(xyz.outputs['Z'], mask.inputs['Value'])
    links.new(mask.outputs[0], shader.inputs['Blackbody Intensity'])
    density = nodes.new('ShaderNodeMath')
    density.operation = 'MULTIPLY'
    density.inputs[1].default_value = density_scale
    links.new(mask.outputs[0], density.inputs[0])
    links.new(density.outputs[0], shader.inputs['Density'])
    links.new(shader.outputs['Volume'], output.inputs['Volume'])
    volume.data.materials.clear()
    volume.data.materials.append(material)
    camera_data = bpy.data.cameras.new('BakeCamera')
    camera = bpy.data.objects.new('BakeCamera', camera_data)
    scene.collection.objects.link(camera)
    camera_data.type = 'ORTHO'
    camera_data.ortho_scale = 3.65
    scene.camera = camera
    return volume, camera, {'min': list(low), 'max': list(high), 'normalization_scale': scale}


def main():
    args = arguments()
    if not (math.isfinite(args.temperature_scale) and 1000 <= args.temperature_scale <= 50000 and
            math.isfinite(args.density_scale) and .001 <= args.density_scale <= 3):
        raise ValueError('Invalid VDB shader scaling')
    source = args.source.resolve(strict=True)
    output = args.output.resolve()
    if output == source or output.is_relative_to(source):
        raise ValueError('Bake output must be separate from the original cache')
    output.mkdir(parents=True, exist_ok=False)
    started = time.time()
    reference = source / 'embergen_fire_a_35.vdb'
    if not reference.is_file():
        raise FileNotFoundError(reference)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 4
    scene.cycles.volume_bounces = 0
    scene.cycles.seed = 20261115
    scene.render.resolution_x = scene.render.resolution_y = args.size
    scene.render.resolution_percentage = 100
    # Emitting volumes need additive radiance, rather than unpremultiplied
    # radiance divided by stochastic transparent-film alpha at their edges.
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '8'
    scene.view_settings.view_transform = 'AgX'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0
    device = 'CPU'
    try:
        preferences = bpy.context.preferences.addons['cycles'].preferences
        preferences.compute_device_type = 'OPTIX'
        preferences.get_devices()
        enabled = [item for item in preferences.devices if item.type == 'OPTIX']
        for item in preferences.devices:
            item.use = item in enabled
        if enabled:
            scene.cycles.device = 'GPU'
            device = ', '.join(item.name for item in enabled)
    except (RuntimeError, TypeError):
        scene.cycles.device = 'CPU'
    volume, camera, bounds = configure_volume(scene, reference, args.temperature_scale, args.density_scale)
    frames = [35] if args.preview else [round(12 + 88 * i / (args.frames - 1)) for i in range(args.frames)]
    side = math.ceil(math.sqrt(len(frames)))
    dimension = side * args.size
    report = {'format': 'metarescue.fire-flipbooks.v1', 'passed': False,
              'author': 'JangaFX', 'license': 'CC0-1.0',
              'source_page': 'https://jangafx.com/software/embergen/download/free-vdb-animations',
              'blender': bpy.app.version_string, 'device': device, 'preview': args.preview,
              'size': args.size, 'atlas_grid': side, 'frame_count': len(frames),
              'fps': 16, 'bounds': bounds, 'inputs': [], 'views': {},
              'source_emitter_clip_normalized_z': [.62, .88],
              'compositing': 'additive_radiance_rgb; alpha derived from linear radiance'}
    report.update(temperature_scale=args.temperature_scale, density_scale=args.density_scale)
    try:
        for index in frames:
            path = source / f'embergen_fire_a_{index}.vdb'
            report['inputs'].append({'name': path.name, 'sha256': sha256(path)})
        for name, position in (('front', (0, -12, 1.5)), ('overview', (0, -8, 11))):
            camera.location = position
            camera.rotation_euler = (Vector((0, 0, 1.4)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
            pixels = array('f', [0.0]) * (dimension * dimension * 4)
            coverage = []
            for number, index in enumerate(frames):
                volume.data.filepath = str(source / f'embergen_fire_a_{index}.vdb')
                volume.data.grids.load()
                bpy.context.view_layer.update()
                path = output / f'{name}-{number:03d}.png'
                scene.render.filepath = str(path)
                bpy.ops.render.render(write_still=True)
                frame = bpy.data.images.load(str(path), check_existing=False)
                values = array('f', frame.pixels[:])
                for pixel in range(0, len(values), 4):
                    values[pixel + 3] = min(1.0, max(values[pixel:pixel + 3])) ** .7
                alpha = values[3::4]
                visible = sum(value > .02 for value in alpha) / len(alpha)
                coverage.append(visible)
                if not args.preview and not .0005 < visible < .9:
                    raise ValueError(f'Fire frame {name}/{index} has invalid alpha coverage: {visible}')
                x = (number % side) * args.size
                y = (side - 1 - number // side) * args.size
                for row in range(args.size):
                    start = ((y + row) * dimension + x) * 4
                    offset = row * args.size * 4
                    pixels[start:start + args.size * 4] = values[offset:offset + args.size * 4]
                bpy.data.images.remove(frame)
                print('MR_FIRE_BAKE ' + json.dumps({'view': name, 'frame': number,
                    'source_frame': index, 'alpha_coverage': round(visible, 5)}), flush=True)
            atlas = bpy.data.images.new('FireAtlas_' + name, width=dimension, height=dimension, alpha=True)
            atlas.colorspace_settings.name = 'sRGB'
            atlas.pixels.foreach_set(pixels)
            atlas.file_format = 'PNG'
            atlas.filepath_raw = str(output / f'fire-{name}.png')
            atlas.save()
            report['views'][name] = {'file': Path(atlas.filepath_raw).name,
                'sha256': sha256(Path(atlas.filepath_raw)), 'alpha_coverage': coverage}
            bpy.data.images.remove(atlas)
        report['passed'] = True
    finally:
        report['elapsed_s'] = time.time() - started
        (output / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print('MR_FIRE_BAKE_REPORT ' + json.dumps({'passed': report['passed'], 'output': str(output),
            'elapsed_s': report['elapsed_s']}), flush=True)


if __name__ == '__main__':
    main()
