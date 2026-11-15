"""Read-only acceptance of the local saved-run analytics and four exports."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode,urlsplit
from urllib.request import Request,urlopen
import zipfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8140')
    parser.add_argument('--run',action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    address=urlsplit(args.url)
    if address.scheme!='http' or address.hostname not in ('127.0.0.1','localhost'):
        parser.error('Use the local loopback server')
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'verification.json').write_text(json.dumps({'passed':False,'state':'incomplete','runs':args.run}),encoding='utf-8')
    def fetch(path,*,host=None):
        request=Request(args.url+path,headers={'Host':host} if host else {})
        try:
            with urlopen(request,timeout=120) as response:return response.status,response.read(),dict(response.headers)
        except HTTPError as error:return error.code,error.read(),dict(error.headers)
    def json_get(path):
        status,raw,_=fetch(path)
        assert status in (200,202),(path,status,raw[:500])
        return json.loads(raw)
    def ready(path):
        until=time.monotonic()+600;last=None
        while True:
            report=json_get(path)
            if report.get('state')=='ready':return report
            assert report.get('state')=='indexing',report
            assert time.monotonic()<until,'Indexing deadline exceeded'
            current=report.get('progress',report.get('state'))
            if current!=last:print('indexing '+str(current),flush=True);last=current
            time.sleep(.5)
    reports=[]
    for identifier in args.run:
        report=ready('/api/runs/'+identifier+'/summary')['summary'];reports.append(report)
        assert report['archive_verified'] and report['metrics']['complete']
        usage=json_get('/api/runs/'+identifier+'/usage')
        if usage['available']:assert usage['manifest']['state']=='complete'
    identifier=args.run[0];base='/api/runs/'+identifier+'/'
    public=json_get(base+'timeline');truth=json_get(base+'timeline?basis=truth')
    assert public['basis']=='public' and truth['basis']=='truth'
    assert public['frames'] and truth['frames']
    records=json_get(base+'records?'+urlencode({'kind':'command_result','q':'handover'}))
    assert records['records'],'Expected saved handover records'
    assert all(row['kind']=='command_result' for row in records['records'])
    for path,code in [(base+'records?after=nan',400),(base+'records?limit=99999',400),
                      ('/api/runs/not-available/summary',404),('/../analytics/server.py',400)]:
        actual,_,_=fetch(path);assert actual==code,(path,actual)
    assert fetch('/api/runs',host='external.example')[0]==403
    exported={}
    for format in ('json','csv','txt','zip'):
        status,raw,headers=fetch(base+'export?format='+format)
        assert status==200,(format,status,raw[:200])
        assert 'attachment;' in headers['Content-Disposition']
        path=args.output/(identifier+'.'+format);path.write_bytes(raw)
        if format=='json':assert json.loads(raw)['episode_id']==reports[0]['episode_id']
        elif format=='csv':assert next(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))['run_id']==identifier
        elif format=='txt':assert identifier in raw.decode('utf-8-sig')
        else:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                assert archive.testzip() is None
                assert 'native/truth.records' in archive.namelist()
                assert 'run/controller/controller.jsonl.gz' in archive.namelist()
        exported[format]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        print('export '+format+' '+str(len(raw))+' bytes',flush=True)
    comparison=None
    if len(args.run)>1:
        comparison=ready('/api/compare?'+urlencode({'runs':','.join(args.run)}))
        assert len(comparison['runs'])==len(args.run)
        assert all(pair['same_layout'] for pair in comparison['pairwise'])
    result={'passed':True,'runs':args.run,'exports':exported,'handover_records':len(records['records']),
            'public_frames':len(public['frames']),'truth_frames':len(truth['frames']),
            'comparison':comparison,'simulation_steps':0}
    (args.output/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('analytics acceptance passed',flush=True)


if __name__=='__main__':main()
