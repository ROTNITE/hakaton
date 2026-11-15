"""Inventory supplied asset files and safely extract ZIPs into a separate vendor tree."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import zipfile


ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / 'blender'
OUT = ROOT / 'artifacts/3d-world/asset-library'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for source in sorted(LIBRARY.iterdir()):
        if not source.is_file() or source.suffix.lower() not in {'.blend', '.glb', '.zip'}:
            continue
        row = {'source': source.relative_to(ROOT).as_posix(), 'bytes': source.stat().st_size,
               'sha256': digest(source), 'assets': []}
        if source.suffix.lower() == '.zip':
            folder = LIBRARY / 'vendor' / source.name.removesuffix('.zip').removesuffix('.blend')
            with zipfile.ZipFile(source) as archive:
                row['archive_files'] = [item.filename for item in archive.infolist()]
                for item in archive.infolist():
                    part = PurePosixPath(item.filename.replace('\\', '/'))
                    target = folder.joinpath(*part.parts).resolve()
                    if part.is_absolute() or not target.is_relative_to(folder.resolve()):
                        raise ValueError('Unsafe archive member: ' + item.filename)
                    if item.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    data = archive.read(item)
                    if target.exists() and target.read_bytes() != data:
                        raise FileExistsError('Preserve edited extracted asset: ' + str(target))
                    if not target.exists():
                        target.write_bytes(data)
                    if target.suffix.lower() in {'.blend', '.glb', '.gltf', '.fbx', '.obj'}:
                        row['assets'].append(target.relative_to(ROOT).as_posix())
        else:
            row['assets'].append(row['source'])
        records.append(row)
        print(source.name, round(row['bytes'] / 1048576, 1), 'MiB', len(row['assets']), 'model files')
    manifest = {'source_count': len(records), 'models': sum(len(r['assets']) for r in records), 'sources': records}
    (OUT / 'inventory.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('MR_LIBRARY_INVENTORY', manifest['source_count'], manifest['models'])


if __name__ == '__main__':
    main()
