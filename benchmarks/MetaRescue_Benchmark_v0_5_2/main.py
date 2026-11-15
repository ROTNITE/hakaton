#!/usr/bin/env python3
"""MetaRescue v0.5.2: run this Python file; no .bat or external packages required.
Edit the bundled secret.env next to this file: API=your_new_deepseek_key.
The server is idle until the user presses Start in the web interface.
"""
from pathlib import Path
import os,sys
ROOT=Path(__file__).resolve().parent

def load_local_settings():
    file=next((p for p in (ROOT/'secret.env',ROOT/'Secret.env') if p.is_file()),None)
    if file is None:return
    for line in file.read_text(encoding='utf-8-sig').splitlines():
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line:continue
        key,value=(s.strip() for s in line.split('=',1))
        value=value.strip('\"').strip("'")
        if key in ('API','DEEPSEEK_API_KEY') and value:os.environ['DEEPSEEK_API_KEY']=value
        if key=='DEEPSEEK_MODEL' and value:os.environ['DEEPSEEK_MODEL']=value

def main():
    if sys.version_info<(3,10):raise SystemExit('Нужен Python 3.10+')
    load_local_settings()
    sys.path.insert(0,str(ROOT/'main part'))
    from server import start
    start()

if __name__=='__main__':main()
