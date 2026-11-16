"""Blender: derive sealed twin-hull displacement and the actual deck anchor.

Run in the prepared boat .blend, without auto-exec. Writes a new runtime JSON;
the supplied model is never saved or modified. The profile is a game model,
not a manufacturer stability or payload certificate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if args.output.exists():raise ValueError('Preserve previous hydrostatic profiles')
    manifest=json.loads(args.manifest.read_bytes())
    if manifest.get('format')!='metarescue.water-catamaran.r1':raise ValueError('Unsupported prepared boat')
    obj=bpy.data.objects.get('SM_RescueWaterCatamaran')
    if obj is None or obj.type!='MESH':raise ValueError('Prepared catamaran mesh missing')
    mesh=obj.data;points=[obj.matrix_world@v.co for v in mesh.vertices]
    if any(len(p.vertices)!=3 for p in mesh.polygons):raise ValueError('Expected the prepared triangulated mesh')
    tree=BVHTree.FromPolygons(points,[tuple(p.vertices) for p in mesh.polygons],all_triangles=True)
    dx=.05;dz=.01;curves=[[0.] for _ in range(8)];missing=0
    for zi in range(55):
        z=(zi+.5)*dz;increment=[0.]*8
        for xi in range(92):
            x=-2.3+(xi+.5)*dx;y=-1.25;hits=[]
            for _ in range(32):
                hit,normal,index,distance=tree.ray_cast(Vector((x,y,z)),Vector((0,1,0)),2.5)
                if hit is None or hit.y>1.25:break
                if not hits or hit.y-hits[-1]>.0001:hits.append(float(hit.y))
                y=float(hit.y)+.00002
            for side in (0,1):
                values=[h for h in hits if (h<0)==(side==0)]
                if len(values)<2:missing+=1;continue
                increment[side*4+min(3,xi//23)]+=(max(values)-min(values))*dx*dz
        for i,volume in enumerate(increment):curves[i].append(curves[i][-1]+volume)
    deck=[]
    for x in (-.8,0,.8):
        for y in (-.15,0,.15):
            hit,normal,index,distance=tree.ray_cast(Vector((x,y,1.2)),Vector((0,0,-1)),2.)
            if hit is None or normal.z<.98:raise ValueError('Cargo rectangle is not a level supported deck')
            deck.append(float(hit.z))
    if max(deck)-min(deck)>.01:raise ValueError('Cargo anchor needs a different support rectangle')
    result={'format':'metarescue.watercraft-hydrostatics.v1','asset_id':'RescueWaterCatamaran-r1',
        'model_source_sha256':manifest['source_sha256'],
        'preparation_manifest_sha256':hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        'height_step_m':dz,'sealed_top_m':.55,'section_x_m':[-1.725,-.575,.575,1.725]*2,
        'section_y_m':[-.6]*4+[.6]*4,'section_volume_m3':curves,
        'body_origin_above_keel_m':.45,'cargo_deck_above_keel_m':max(deck)+.005,
        'dry_mass_kg':475.,'person_and_stretcher_mass_kg':98.,'payload_limit_kg':130.,
        'battery_wh':3000.,'maximum_jet_thrust_n':900.,'maximum_speed_m_s':2.8,
        'model_assumptions':'Sealed exterior envelope below .55m; 8 hydrostatic sections. Mass, power and payload limits are chosen game parameters.',
        'quadrature':{'x_step_m':dx,'z_step_m':dz,'missing_side_samples':missing,
            'limitation':'Exterior envelope estimate; no manifold, pressure or strength certification.'}}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'profile':str(args.output),'deck_m':result['cargo_deck_above_keel_m'],
                      'sealed_volume_m3':sum(c[-1] for c in curves),'sections':len(curves)}))


if __name__=='__main__':main()
