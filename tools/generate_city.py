"""Author a private physical layout and a separate announced map on D:."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from contracts.protocol import strict_json
from environment.config import MAP_SIZES,PRESETS,Settings
from environment.layout import generate,public_map,fingerprint


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings',type=Path)
    parser.add_argument('--size',type=int,choices=MAP_SIZES)
    parser.add_argument('--seed',type=int)
    parser.add_argument('--preset',choices=PRESETS)
    parser.add_argument('--city-revision',choices=['1.1','2.0','2.1','2.2','2.3'])
    parser.add_argument('--layout-kind',choices=['generated_city','rescue_quarter'])
    parser.add_argument('--scouts',type=int)
    parser.add_argument('--rescuers',type=int)
    parser.add_argument('--people',type=int)
    parser.add_argument('--static',action='store_true',help='Generate geometry without a scheduled event tape')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    values=strict_json(args.settings.read_bytes()) if args.settings else {}
    for key in ('seed','preset','scouts','rescuers','people','city_revision'):
        if getattr(args,key) is not None:values[key]=getattr(args,key)
    if args.layout_kind is not None:values['layout']=args.layout_kind
    if args.size is not None:values['map_size']=args.size
    world=generate(Settings.parse(values),include_events=not args.static)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target=args.output or Path('D:/MetaRescue-output/worlds')/(stamp+'-layout.private.json')
    target.parent.mkdir(parents=True,exist_ok=True)
    public=target.with_name(target.stem+'.public.json')
    # Both names are reserved before writing either file, so retry cannot
    # silently replace a previous world or its separately distributable map.
    if target.exists() or public.exists():raise FileExistsError('World output already exists')
    target.write_text(json.dumps(world,indent=2,ensure_ascii=False),encoding='utf-8')
    public.write_text(json.dumps(public_map(world),indent=2),encoding='utf-8')
    print(json.dumps({'private_layout':str(target),'public_map':str(public),
                      'sha256':fingerprint(world),'preflight':world['preflight']},ensure_ascii=False))


if __name__=='__main__':main()
