"""Local analytics server. The simulation clock is never called."""
from __future__ import annotations

import argparse
import csv
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
import mimetypes
from pathlib import Path
import tempfile
from urllib.parse import parse_qs,urlsplit
import zipfile

from analytics.store import SCHEMA,RunStore,safe_path
from analytics.metrics import VERSION
from environment.main import DEFAULT_OUTPUT


ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'web'
MAX_COMPARE=20


class Handler(BaseHTTPRequestHandler):
    server_version='MetaRescueAnalytics/1.0'

    def log_message(self,*args):
        pass

    def send(self,data,status=200,content_type='application/json; charset=utf-8',filename=None):
        raw=json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8') if isinstance(data,(dict,list)) else data
        self.send_response(status)
        self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        if filename:self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
        self.end_headers();self.wfile.write(raw)

    def do_GET(self):
        host=self.headers.get('Host','')
        if host not in (f'localhost:{self.server.server_port}',f'127.0.0.1:{self.server.server_port}'):
            self.send({'error':'Loopback host required'},403);return
        parsed=urlsplit(self.path);query=parse_qs(parsed.query,keep_blank_values=True)
        one=lambda key,default='':query.get(key,[default])[0]
        try:
            if parsed.path=='/api/health':
                self.send({'format':'metarescue.analytics-health.v1','component':'metarescue_analytics',
                           'metrics_version':VERSION,'index_schema':SCHEMA,'output_root':str(self.server.store.root)});return
            if parsed.path=='/api/runs':self.send({'runs':self.server.store.runs()});return
            if parsed.path=='/api/compare':
                identifiers=[item for item in one('runs').split(',') if item]
                if not 2<=len(identifiers)<=MAX_COMPARE:raise ValueError('Choose 2..20 saved runs')
                reports=[self.server.store.ensure(identifier) for identifier in identifiers]
                if any('visual' in row for row in reports):raise ValueError('Choose runs with native mission journals')
                if any(row['state']=='error' for row in reports):
                    raise ValueError('; '.join(row['error'] for row in reports if row['state']=='error'))
                if any(row['state']!='ready' for row in reports):self.send({'state':'indexing','runs':reports},202);return
                summaries=[row['summary'] for row in reports]
                self.send({'state':'ready','runs':summaries,'pairwise':comparison(summaries)});return
            if parsed.path.startswith('/api/runs/'):
                parts=parsed.path.split('/');identifier=parts[3];action=parts[4] if len(parts)>4 else 'summary'
                if action=='summary':
                    report=self.server.store.ensure(identifier)
                    self.send(report,202 if report['state']=='indexing' else 500 if report['state']=='error' else 200);return
                if action=='records':
                    self.send(self.server.store.records(identifier,cursor=int(one('cursor','0')),limit=int(one('limit','100')),
                        stream=one('stream'),kind=one('kind'),query=one('q'),after=float(one('after','0'))));return
                if action=='timeline':
                    self.send(self.server.store.timeline(identifier,truth=one('basis')=='truth'));return
                if action=='heatmap':
                    basis=one('basis','public')
                    if basis not in ('public','truth'):raise ValueError('Choose public or truth heatmap basis')
                    self.send(self.server.store.heatmap(identifier,truth=basis=='truth'));return
                if action=='map':self.send(self.server.store.map(identifier));return
                if action=='fronts':self.send({'fronts':self.server.store.fronts(identifier)});return
                if action=='usage':
                    self.send(self.server.store.usage(identifier));return
                if action=='export':
                    self.export(identifier,one('format','json'));return
                raise FileNotFoundError('Unknown report')
            file=WEB/('index.html' if parsed.path=='/' else parsed.path.lstrip('/'))
            file=safe_path(WEB,file)
            if not file.is_file():raise FileNotFoundError('Unknown resource')
            self.send(file.read_bytes(),content_type=mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        except (ValueError,KeyError,TypeError) as error:self.send({'error':str(error)},400)
        except FileNotFoundError as error:self.send({'error':str(error)},404)
        except BrokenPipeError:pass
        except Exception as error:self.send({'error':type(error).__name__+': '+str(error)},500)

    def export(self,identifier,format):
        ready=self.server.store.ensure(identifier)
        if ready['state']!='ready' or 'summary' not in ready:raise ValueError('Wait until the saved run is indexed')
        report=ready['summary']
        if format=='json':
            self.send(report,filename=identifier+'.json');return
        if format in ('csv','txt'):
            metrics=report['metrics'];flat={key:value for key,value in metrics.items() if not isinstance(value,(list,dict))}
            flat.update(run_id=identifier,status=report['status'],M1=metrics['M1']['value'],M5=None)
            if format=='txt':
                text='\n'.join(f'{key} = {value if value is not None else "unverified"}' for key,value in flat.items())+'\n'
                self.send(text.encode('utf-8-sig'),content_type='text/plain; charset=utf-8',filename=identifier+'.txt');return
            output=io.StringIO(newline='');writer=csv.DictWriter(output,fieldnames=list(flat));writer.writeheader();writer.writerow(flat)
            self.send(output.getvalue().encode('utf-8-sig'),content_type='text/csv; charset=utf-8',filename=identifier+'.csv');return
        if format!='zip':raise ValueError('Choose json, csv, txt or zip')
        run=self.server.store.locate(identifier)
        directory=self.server.store.cache/identifier
        # A temporary file bounds memory while retaining all raw evidence.
        with tempfile.TemporaryFile(dir=directory) as stream:
            with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
                archive.writestr('audit-summary.json',json.dumps(report,ensure_ascii=False,indent=2))
                for prefix,source in (('run',run['path']),('native',run['native'])):
                    if not source:continue
                    for file in source.rglob('*'):
                        if file.is_file():
                            resolved=safe_path(self.server.store.root,file)
                            archive.write(resolved,prefix+'/'+file.relative_to(source).as_posix())
            size=stream.tell();stream.seek(0)
            self.send_response(200);self.send_header('Content-Type','application/zip')
            self.send_header('Content-Disposition','attachment; filename="'+identifier+'.zip"')
            self.send_header('Content-Length',str(size));self.end_headers()
            for block in iter(lambda:stream.read(1024*1024),b''):self.wfile.write(block)


def comparison(reports):
    output=[]
    for i,left in enumerate(reports):
        for right in reports[i+1:]:
            comparable=bool(left.get('layout_sha256')) and left['layout_sha256']==right.get('layout_sha256')
            row={'left':left['run_id'],'right':right['run_id'],'same_layout':comparable,'differences':None}
            if comparable:
                keys=('rescued','energy_wh','cutoff_s','found')
                row['differences']={key:left['metrics'][key]-right['metrics'][key] for key in keys}
            output.append(row)
    return output


def serve(root,port):
    store=RunStore(root)
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.store=store
    print('http://127.0.0.1:'+str(server.server_port),flush=True)
    try:server.serve_forever(poll_interval=.3)
    finally:server.server_close();store.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument('--port',type=int,default=8140)
    args=parser.parse_args(argv)
    if not 1024<=args.port<=65535:parser.error('Invalid loopback port')
    serve(args.root,args.port)


if __name__=='__main__':main()
