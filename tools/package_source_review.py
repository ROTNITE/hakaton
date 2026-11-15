"""Freeze a code-only review supplement without building or launching Unreal.

This is not the complete Windows/asset/experiment submission required by §15.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ('controller', 'environment', 'analytics', 'web', 'contracts', 'tests',
           'tools', 'docs', 'benchmarks', 'benchmark', 'blender', 'unreal/tools',
           'unreal/MetaRescue/Source', 'unreal/MetaRescue/Config',
           'unreal/MetaRescue/Content/Scenario')
SINGLE_FILES = ('README.md', 'AGENTS.md', 'requirements.txt', 'unreal/README.md',
                'unreal/QA.md', 'unreal/launch.py', 'unreal/MetaRescue/MetaRescue.uproject')
EXTENSIONS = {'.py', '.md', '.txt', '.json', '.html', '.css', '.js', '.ts', '.cpp',
              '.h', '.cs', '.ini', '.uproject', '.ps1', '.cmd', '.bat', '.sh', '.toml'}
SKIP = {'__pycache__', '.git', '.venv', 'venv', 'node_modules', 'Saved',
        'Intermediate', 'Binaries', 'DerivedDataCache'}
REQUIRED = ('environment/main.py', 'controller/main.py', 'controller/baselines.py',
            'analytics/server.py', 'contracts/protocol.py', 'requirements.txt',
            'controller/vendor/nsga2-origin.json', 'tests/test_protocol.py',
            'unreal/MetaRescue/MetaRescue.uproject',
            'unreal/MetaRescue/Content/Scenario/core-scenarios-v1.json')
DEPENDENCIES = ('jsonschema', 'jsonschema-specifications', 'attrs', 'referencing', 'rpds-py')
EMPTY_KEY_TEMPLATE = 'benchmarks/MetaRescue_Benchmark_v0_5_2/secret.env'
NOTICE = '''# Supplement: source review snapshot

This immutable supplement contains environment and controller code, both required
controls (fixed_workflow/local_reactive), tests, scenario declarations, preparation
scripts and the supplied task PDFs. SOURCE-MANIFEST.json records source hashes.
It excludes geometry, textures, cooked assets, Unreal/Python binaries, credentials,
mission archives and final presentation materials. It is not a complete §15 release
and cannot build the native world without the separately licensed asset inputs.

Python: use the version recorded in DEPENDENCIES.json; install requirements.txt.
The imported benchmark itself needs Python 3.10+ and the standard library.
From an extracted copy, run:

    python -B -X utf8 -m unittest discover -s tests -v
    python -B -X utf8 -m unittest discover -s "benchmarks/MetaRescue_Benchmark_v0_5_2/main part/tests" -v
    python -B -X utf8 -m unittest discover -s "benchmarks/metarescue-v0.3/main part/tests" -v
    python -B -X utf8 -m unittest discover -s unreal/tools/tests -v

These checks do not start Unreal or make LIVE AI requests. Refer to
docs/windows-runtime.md for the separate Windows runtime, unreal/README.md for
native build instructions, and docs/stage-1-interaction.md for the public contract.
DEPENDENCIES.json describes the packaging host, not a tested minimum machine or
an offline installer. Optional OR-Tools is not required by the contest controller.
Retain upstream provenance and asset licences when assembling the full release.
The upstream secret.env template is included only if its complete stripped value
is API= (empty key). A populated template causes packaging to fail.
As in tools/package_windows.py, the snapshot disables AndroidFileServer and removes
its editor configuration section. Original inputs remain unchanged; their hashes
and the two documented transformations are recorded in SOURCE-MANIFEST.json.
'''


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def distribution_source(name, data):
    """Mirror the existing Windows packager's AndroidFileServer sanitization."""
    if name == 'unreal/MetaRescue/MetaRescue.uproject':
        descriptor = json.loads(data.decode('utf-8-sig'))
        plugins = [plugin for plugin in descriptor.get('Plugins', ()) if plugin['Name'] != 'AndroidFileServer']
        descriptor['Plugins'] = [*plugins, {'Name': 'AndroidFileServer', 'Enabled': False}]
        return json_bytes(descriptor).replace(b'\n', os.linesep.encode()), 'disable AndroidFileServer, matching Windows packaging'
    if name == 'unreal/MetaRescue/Config/DefaultEngine.ini':
        lines = []
        include = True
        for line in data.decode('utf-8-sig').splitlines():
            if line.startswith('['):
                include = not line.startswith('[/Script/AndroidFileServer')
            if include:
                lines.append(line)
        return (os.linesep.join(lines) + os.linesep).encode('utf-8'), 'remove AndroidFileServer editor settings, matching Windows packaging'
    return data, None


def source_files(root):
    root = root.resolve(strict=True)
    candidates = {root / name for name in SINGLE_FILES if (root / name).is_file()}
    for name in FOLDERS:
        candidates.update(p for p in (root / name).rglob('*') if p.is_file())
    candidates.update((root / 'ТЗ').glob('*.pdf'))
    selected = {}
    for path in sorted(candidates):
        relative = path.relative_to(root)
        if SKIP.intersection(relative.parts) or relative.parts[:2] == ('docs', 'assets'):
            continue
        if not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('Source link escapes the workspace: ' + relative.as_posix())
        if relative.as_posix() == EMPTY_KEY_TEMPLATE:
            if path.read_bytes().strip() != b'API=':
                raise ValueError('Upstream API template is not empty; refusing to package it')
            selected[relative.as_posix()] = path
            continue
        if path.suffix.lower() not in EXTENSIONS and not (relative.parts[0] == 'ТЗ' and path.suffix == '.pdf'):
            continue
        if path.name.lower().startswith(('.env', 'secrets', 'credentials')):
            continue
        selected[relative.as_posix()] = path
    missing = sorted(set(REQUIRED) - selected.keys())
    if missing:
        raise ValueError('Required source files missing: ' + ', '.join(missing))
    return selected


def verify_source_zip(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names):
            raise ValueError('Duplicate ZIP members')
        for name in names:
            pure = PurePosixPath(name)
            if pure.is_absolute() or '..' in pure.parts or '\\' in name or ':' in name:
                raise ValueError('Unsafe ZIP member')
        manifest = json.loads(archive.read('SOURCE-MANIFEST.json'))
        if manifest.get('format') != 'metarescue.source-review.v1':
            raise ValueError('Unsupported source manifest')
        if set(names) != set(manifest['files']) | {'SOURCE-MANIFEST.json'}:
            raise ValueError('ZIP inventory differs from manifest')
        for name, expected in manifest['files'].items():
            data = archive.read(name)
            if checksum(data) != expected['sha256'] or len(data) != expected['bytes']:
                raise ValueError('ZIP checksum/size mismatch: ' + name)
        if archive.testzip() is not None:
            raise ValueError('ZIP CRC failed')
    return {'passed': True, 'files_verified': len(manifest['files']),
            'zip_sha256': checksum(Path(path).read_bytes())}


def create_bundle(root, output):
    root = root.resolve(strict=True)
    output = output.resolve()
    if output.is_relative_to(root):
        raise ValueError('Use an output directory outside the active workspace')
    selected = source_files(root)
    before = {name: checksum(path.read_bytes()) for name, path in selected.items()}
    output.mkdir(parents=True, exist_ok=False)
    partial = output / 'MetaRescue-source-review.zip.part'
    manifest = {'format': 'metarescue.source-review.v1',
                'created_at': datetime.now(timezone.utc).isoformat(),
                'scope': 'code-only supplement; not a complete §15 release',
                'source_root': str(root), 'files': {}, 'source_inputs': before,
                'transformations': {}}
    dependencies = {'python': sys.version, 'platform': platform.platform(),
                    'packages': {name: metadata.version(name) for name in DEPENDENCIES},
                    'native_build': 'Unreal 5.8, Visual Studio C++ toolchain, Windows SDK; see unreal/README.md',
                    'assets_included': False, 'offline_installer': False}
    with zipfile.ZipFile(partial, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        def add(name, data):
            archive.writestr(name, data)
            manifest['files'][name] = {'sha256': checksum(data), 'bytes': len(data)}
        for name, path in selected.items():
            data = path.read_bytes()
            if checksum(data) != before[name]:
                raise ValueError('Source changed during snapshot: ' + name)
            data, transformation = distribution_source(name, data)
            if transformation:
                manifest['transformations'][name] = transformation
            add(name, data)
        add('SOURCE-REVIEW.md', NOTICE.encode('utf-8'))
        add('DEPENDENCIES.json', json_bytes(dependencies))
        archive.writestr('SOURCE-MANIFEST.json', json_bytes(manifest))
    # Reject edits and additions while copying; do not freeze the other chat.
    after = {name: checksum(path.read_bytes()) for name, path in source_files(root).items()}
    if before != after:
        raise ValueError('Source tree changed during snapshot; retry into a new output directory')
    report = verify_source_zip(partial)
    destination = partial.with_suffix('')
    partial.rename(destination)
    report.update(source_inputs_unchanged=True, archive=str(destination),
                  source_files=len(selected), native_build_executed=False)
    (output / 'SOURCE-MANIFEST.json').write_bytes(json_bytes(manifest))
    (output / 'verification.json').write_bytes(json_bytes(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(create_bundle(args.root, args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
