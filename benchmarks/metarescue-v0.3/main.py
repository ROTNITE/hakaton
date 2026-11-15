"""Launch MetaRescue v0.3. No external Python dependencies are required."""
from pathlib import Path
import argparse
import sys
ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--no-browser',action='store_true',help='Do not open a browser')
    parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    if sys.version_info<(3,10):
        raise SystemExit('Требуется Python 3.10 или новее')
    sys.path.insert(0,str(ROOT/'main part'))
    import importlib
    server=importlib.import_module('server')
    server.start(open_browser=not args.no_browser,port=args.port)

if __name__=='__main__':main()
