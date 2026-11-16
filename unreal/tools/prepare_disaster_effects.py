"""Prepare licensed disaster textures without changing downloaded originals.

The three input directories contain the extracted Kenney Particle Pack 1.1,
ambientCG Ground026 2K JPG and the verified bake_disaster_fire.py result.
No Blender/Python code from a downloaded archive is executed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(particles, ground, fire, output):
    output = output.resolve()
    inputs = [p.resolve(strict=True) for p in (particles, ground, fire)]
    if any(output == p or output.is_relative_to(p) for p in inputs):
        raise ValueError('Output must be separate from the originals')
    bake = json.loads((fire / 'manifest.json').read_bytes())
    if not bake.get('passed') or bake.get('preview') or bake['frame_count'] != 64 or \
            bake.get('source_emitter_clip_normalized_z') != [.62, .88]:
        raise ValueError('A complete, emitter-free 64-frame fire bake is required')
    output.mkdir(parents=True, exist_ok=False)
    sources = [
        {'id': 'kenney-particles-1.1', 'author': 'Kenney', 'license': 'CC0-1.0',
         'page': 'https://kenney.nl/assets/particle-pack',
         'archive_sha256': 'b631d4b07f7002549fdcf155f01141ad482f79f3440e4e301eed49ce5f1d8958'},
        {'id': 'ambientcg-ground026', 'author': 'ambientCG', 'license': 'CC0-1.0',
         'page': 'https://ambientcg.com/view?id=Ground026',
         'archive_sha256': 'defbc8d2f777f941457e272b64aaa1e1c9c675a097927e8434d23ade1c7e2451'},
        {'id': 'jangafx-fire01', 'author': 'JangaFX', 'license': 'CC0-1.0',
         'page': 'https://jangafx.com/software/embergen/download/free-vdb-animations',
         'archive_sha256': 'c130c42bf2ffc52254691e2d870c5c54cfda40e73bde4831d1603ccee94fb681'},
    ]
    textures = {}
    selected = {
        'SmokeBillow': (particles / 'PNG (Transparent)' / 'smoke_01.png', sources[0]['id'], 'alpha'),
        'SmokeWisps': (particles / 'PNG (Transparent)' / 'smoke_07.png', sources[0]['id'], 'alpha'),
        'MudColor': (ground / 'Ground026_2K-JPG_Color.jpg', sources[1]['id'], 'color'),
        'MudNormal': (ground / 'Ground026_2K-JPG_NormalDX.jpg', sources[1]['id'], 'normal'),
        'MudRoughness': (ground / 'Ground026_2K-JPG_Roughness.jpg', sources[1]['id'], 'linear'),
        'MudHeight': (ground / 'Ground026_2K-JPG_Displacement.jpg', sources[1]['id'], 'linear'),
        'FireFront': (fire / bake['views']['front']['file'], sources[2]['id'], 'color'),
        'FireOverhead': (fire / bake['views']['overview']['file'], sources[2]['id'], 'color'),
    }
    for name, (path, source, usage) in selected.items():
        path = path.resolve(strict=True)
        sha = digest(path)
        if name.startswith('Fire'):
            view = 'front' if name == 'FireFront' else 'overview'
            if sha != bake['views'][view]['sha256']:
                raise ValueError('Fire atlas differs from the baked manifest')
        target = output / ('T_' + name + path.suffix.lower())
        shutil.copy2(path, target)
        if digest(target) != sha:
            raise OSError('Prepared texture differs from its source')
        textures[name] = {'path': target.name, 'bytes': target.stat().st_size,
                          'sha256': sha, 'source': source, 'usage': usage}
    license_files = [particles / 'License.txt', ground / 'Ground026_2K-JPG_Color.jpg', fire / 'manifest.json']
    # ambientCG distributes the CC0 dedication on the asset page, not as a
    # license file in each ZIP. Preserve its exact origin separately.
    for source, path in zip(sources, license_files):
        if source['id'] == 'kenney-particles-1.1':
            shutil.copy2(path, output / 'Kenney-License.txt')
        if source['id'] == 'jangafx-fire01':
            shutil.copy2(path, output / 'fire-bake.json')
    report = {'format': 'metarescue.disaster-effects.sources.v1', 'sources': sources,
              'textures': textures, 'fire': {'frames': 64, 'grid': 8, 'fps': bake['fps'],
              'manifest_sha256': digest(fire / 'manifest.json')},
              'license': 'CC0-1.0', 'revision': 5}
    (output / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('particles', 'ground', 'fire', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.particles, args.ground, args.fire, args.output)
    print(json.dumps({'textures': len(result['textures']), 'output': str(args.output)}))
