"""Run one native city at a time, preserving real evidence and input hashes."""
import argparse
from pathlib import Path
from check_city_run import verify
from run_quarter_validation import run

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('layout',type=Path)
    parser.add_argument('--name',required=True)
    parser.add_argument('--seconds',type=int,default=40)
    probes=parser.add_mutually_exclusive_group()
    probes.add_argument('--asset-views',action='store_true')
    probes.add_argument('--building-views',action='store_true')
    probes.add_argument('--lighting-views',action='store_true')
    probes.add_argument('--glazing-views',action='store_true')
    probes.add_argument('--competition-views',action='store_true')
    parser.add_argument('--glass-reflection-test',action='store_true')
    args=parser.parse_args()
    if not 30<=args.seconds<=900:parser.error('--seconds must be 30..900')
    if args.asset_views and args.seconds<52:parser.error('--asset-views needs at least 52 seconds')
    if args.building_views and args.seconds<72:parser.error('--building-views needs at least 72 seconds')
    if args.lighting_views and args.seconds<40:parser.error('--lighting-views needs at least 40 seconds')
    if args.glazing_views and args.seconds<82:parser.error('--glazing-views needs at least 82 seconds')
    if args.competition_views and args.seconds<46:parser.error('--competition-views needs at least 46 seconds')
    extra=['--environment','static','--external-control','--city-layout',str(args.layout)]
    if args.asset_views:extra+=['--visual-probe','city-assets']
    if args.building_views:extra+=['--visual-probe','city-buildings']
    if args.lighting_views:extra+=['--visual-probe','city-lumen']
    if args.glazing_views:extra+=['--visual-probe','city-glazing']
    if args.competition_views:extra+=['--visual-probe','city-competition']
    if args.glass_reflection_test:extra+=['--glass-reflection-test']
    run(args.name,extra,args.seconds,checker=verify)
