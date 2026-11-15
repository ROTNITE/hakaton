"""Archive an immutable implementation baseline without touching user files."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path('D:/MetaRescue-output')
SKIP = {'__pycache__', 'venv', '.venv', 'Intermediate', 'Saved', 'Binaries', '.git'}


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def capture(output: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = output.resolve() / 'baselines' / stamp
    destination.mkdir(parents=True, exist_ok=False)
    files = []
    for folder in ('docs', 'contracts', 'controller', 'environment', 'web', 'tests',
                   'tools', 'unreal/MetaRescue/Source', 'unreal/MetaRescue/Config',
                   'unreal/MetaRescue/Content/Scenario', 'unreal/MetaRescue/Content/Maps',
                   'unreal/tools', 'benchmarks/MetaRescue_Benchmark_v0_5_2',
                   'benchmarks/metarescue-v0.3', 'benchmarks/metarescue-v0.2'):
        for path in (ROOT / folder).rglob('*'):
            if (path.is_file() and not SKIP.intersection(path.parts)
                    and path.suffix.lower() not in {'.env', '.zip', '.png', '.jpg', '.mp4'}):
                files.append(path)
    files.extend(p for p in (ROOT / 'AGENTS.md', ROOT / 'README.md', ROOT / 'requirements.txt',
                            ROOT / 'unreal/launch.py', ROOT / 'unreal/MetaRescue/MetaRescue.uproject') if p.is_file())
    records = {}
    for path in sorted(set(files)):
        relative = path.relative_to(ROOT)
        target = destination / 'source' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        records[relative.as_posix()] = {'sha256': digest(path), 'size': path.stat().st_size}
    inventory = ROOT / 'artifacts/3d-world/asset-library/inventory.json'
    original_hashes = []
    if inventory.exists():
        data = json.loads(inventory.read_text(encoding='utf-8-sig'))
        def visit(value):
            if isinstance(value, dict):
                if 'sha256' in value:
                    original_hashes.append(value)
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)
        visit(data)
        shutil.copy2(inventory, destination / 'original-asset-inventory.json')
    status = subprocess.run(['git', 'status', '--porcelain=v1', '-uall'], cwd=ROOT,
                            capture_output=True, text=True, encoding='utf-8', check=True)
    (destination / 'git-status.txt').write_text(status.stdout, encoding='utf-8')
    manifest = {'format': 'metarescue.baseline.v1', 'created_at': stamp,
                'workspace': str(ROOT), 'files': records,
                'original_asset_hash_records': len(original_hashes),
                'secrets_copied': False,
                'notes': 'Existing dirty changes and deletions preserved. Asset originals remain in place.'}
    (destination / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=OUTPUT)
    print(capture(parser.parse_args().output))
