"""Import changed geometry and then rebuild project effects and quarter map."""
from pathlib import Path
import runpy
import unreal
folder=Path(__file__).resolve().parent
scripts=['import_mannequin_rig.py','build_rescue_effects.py','build_quarter.py']
if '-MRSkipStatic' not in unreal.SystemLibrary.get_command_line():scripts.insert(0,'import_asset_library.py')
for script in scripts:
    runpy.run_path(str(folder/script),run_name='__main__')
