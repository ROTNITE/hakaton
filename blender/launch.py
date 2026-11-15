"""Open a model in the project-local portable Blender installation."""
import argparse
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('file', type=Path, nargs='?')
args = parser.parse_args()
installation = ROOT / '.tools/blender/installation.json'
if not installation.is_file():
    parser.error('Project-local Blender installation not found; see blender/README.md')
executable = Path(json.loads(installation.read_text(encoding='utf-8'))['executable'])
if not executable.is_file():
    parser.error('Portable Blender executable is missing')
command = [str(executable)]
if args.file:
    file = args.file.resolve()
    if not file.is_file():
        parser.error('Model file not found: ' + str(file))
    command.append(str(file))
subprocess.Popen(command, cwd=ROOT)
