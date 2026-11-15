"""Run project effect and district authoring sequentially in the same editor."""
from pathlib import Path
import runpy
folder = Path(__file__).resolve().parent
for script in ['build_rescue_effects.py', 'build_quarter.py']:
    runpy.run_path(str(folder / script), run_name='__main__')
