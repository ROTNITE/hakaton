#!/usr/bin/env python3
"""Entry point. Double-click main.bat on Windows, or run python main.py.
On first run creates a local portable-by-regeneration virtual environment.
No third-party Python dependencies are required for core operation.
"""
from pathlib import Path
import os, subprocess, sys, venv

ROOT=Path(__file__).resolve().parent
VENV=ROOT/'venv'

def interpreter():
    if os.name=='nt':return VENV/'Scripts'/'python.exe'
    return VENV/'bin'/'python'

def main():
    if sys.version_info<(3,10):
        raise SystemExit('Требуется Python 3.10 или новее. Установите Python с python.org.')
    if '--run-app' not in sys.argv:
        if not (VENV/'pyvenv.cfg').exists() or not interpreter().exists():
            print('Создаю виртуальное окружение в папке venv/ (один раз)...')
            try:venv.EnvBuilder(with_pip=True,clear=False).create(str(VENV))
            except Exception as e:
                print('Не удалось создать venv:',e)
                print('Запускаю приложение через системный Python (зависимости не нужны).')
                return run_app()
        if interpreter().resolve()!=Path(sys.executable).resolve():
            return subprocess.call([str(interpreter()),str(ROOT/'main.py'),'--run-app'])
    return run_app()

def run_app():
    sys.path.insert(0,str(ROOT/'main part'))
    from server import start
    start()
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except KeyboardInterrupt:pass
