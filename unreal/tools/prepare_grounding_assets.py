"""Keep CPU vertex positions for the cooked meshes used by ground placement."""

import json
import os
from pathlib import Path

import unreal


def main():
    requested = Path(os.environ['MR_GROUNDING_MESHES'])
    report_path = Path(os.environ['MR_GROUNDING_REPORT'])
    meshes = json.loads(requested.read_bytes())
    if not meshes or any(not path.startswith('/Game/RescueAssets/') for path in meshes):
        raise ValueError('Invalid grounding mesh list')
    saved = []
    for path in meshes:
        mesh = unreal.load_asset(path)
        if not isinstance(mesh, unreal.StaticMesh):
            raise ValueError('Grounding mesh is unavailable: '+path)
        if not mesh.get_editor_property('allow_cpu_access'):
            mesh.set_editor_property('allow_cpu_access', True)
            if not unreal.EditorAssetLibrary.save_loaded_asset(mesh, only_if_is_dirty=False):
                raise RuntimeError('Cannot save the cooked input mesh: '+path)
        if not mesh.get_editor_property('allow_cpu_access'):
            raise RuntimeError('CPU access was not retained: '+path)
        saved.append(mesh.get_path_name())
    with report_path.open('x', encoding='utf-8') as stream:
        json.dump({'passed':True, 'meshes':saved}, stream, indent=2)


if __name__ == '__main__':
    main()
