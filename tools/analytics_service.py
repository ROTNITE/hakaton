"""Reuse the matching local archive viewer or start one hidden Python service."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError,URLError
from urllib.request import urlopen

from contracts.protocol import strict_json
from analytics.metrics import VERSION
from analytics.store import SCHEMA


ROOT=Path(__file__).resolve().parents[1]


def analytics_health(root,*,port=8140):
    try:
        with urlopen(f'http://127.0.0.1:{port}/api/health',timeout=.8) as response:
            data=strict_json(response.read(65537),maximum_bytes=65536)
    except HTTPError as error:
        raise RuntimeError('Port '+str(port)+' is occupied by a service without the matching MetaRescue analytics health') from error
    except (URLError,TimeoutError):return None
    if (data.get('format')!='metarescue.analytics-health.v1' or data.get('component')!='metarescue_analytics' or
        data.get('metrics_version')!=VERSION or data.get('index_schema')!=SCHEMA or
        Path(data.get('output_root','')).resolve()!=Path(root).resolve()):
        raise RuntimeError('Local analytics on port '+str(port)+' uses another version or output directory')
    return data


def available_port(root,*,exclude=(),candidates=range(8140,8150)):
    for port in candidates:
        if port in exclude:continue
        try:analytics_health(root,port=port)
        except RuntimeError:continue
        return port
    raise RuntimeError('No compatible local analytics port is available in 8140..8149')


def ensure_analytics(workspace,root,*,port=8140):
    if analytics_health(root,port=port):return {'url':f'http://127.0.0.1:{port}/','reused':True,'pid':None}
    workspace=Path(workspace)
    startup=None;flags=0
    if os.name=='nt':
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
        flags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP
    with (workspace/'analytics-stdout.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen([sys.executable,'-B','-X','utf8','-m','analytics.server','--root',str(Path(root).resolve()),'--port',str(port)],
            cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,startupinfo=startup,creationflags=flags)
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        if process.poll() is not None:raise RuntimeError('Archive viewer failed to start; see analytics-stdout.log')
        if analytics_health(root,port=port):return {'url':f'http://127.0.0.1:{port}/','reused':False,'pid':process.pid}
        time.sleep(.1)
    # This process was created here; its failed startup is not a user's service.
    process.terminate();process.wait(timeout=10)
    raise TimeoutError('Archive viewer startup timed out')
