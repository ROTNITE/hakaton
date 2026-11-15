"""Drop unused dense-source datablocks from prepared files after texture baking."""
from pathlib import Path
import bpy

root = Path(__file__).resolve().parents[2]
for path in sorted((root / 'blender/prepared/v2').glob('*/*.blend')):
    bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False)
    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=True)
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(path), relative_remap=False)
    print('MR_LIBRARY_CLEANED', path.parent.name, flush=True)
