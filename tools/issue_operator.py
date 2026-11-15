"""Queue a structured operator request for the controller; never step the world."""
from pathlib import Path
import argparse
import json
import os
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from contracts.protocol import strict_json
from controller.ai import file_lock
from controller.operator_input import INPUT_FORMAT


def enqueue(path, *, episode_id, expires_at, parameters, request_id=None):
    path=Path(path)
    if not episode_id or type(expires_at) not in (int,float) or not isinstance(parameters,dict):
        raise ValueError('Episode, expiry and an instruction object are required')
    ident=request_id or uuid.uuid4().hex
    item={'id':ident,'expires_at':expires_at,'parameters':parameters}
    path.parent.mkdir(parents=True,exist_ok=True)
    with file_lock(path.with_suffix('.lock')):
        if path.exists():
            document=strict_json(path.read_bytes(),maximum_bytes=65536)
            if (document.get('format')!=INPUT_FORMAT or document.get('episode_id')!=episode_id or
                    not isinstance(document.get('requests'),list)):
                raise ValueError('Existing operator input belongs to another episode or is invalid; use its new episode file')
        else:document={'format':INPUT_FORMAT,'episode_id':episode_id,'requests':[]}
        previous=next((row for row in document['requests'] if row['id']==ident),None)
        if previous:
            if previous!=item:raise ValueError('Request ID already contains different input')
            return ident
        if len(document['requests'])>=64:raise ValueError('Operator input file already has 64 requests')
        document['requests'].append(item)
        data=(json.dumps(document,ensure_ascii=False,allow_nan=False,indent=2)+'\n').encode('utf-8')
        if len(data)>65536:raise ValueError('Operator input exceeds 64 KiB')
        partial=path.with_name(path.name+'.'+uuid.uuid4().hex+'.part')
        with partial.open('xb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        partial.replace(path)
    return ident


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('--episode',required=True)
    parser.add_argument('--expires-at',type=float,required=True,help='Latest model time for submitting this request')
    parser.add_argument('--instruction',type=Path,required=True,help='JSON issue_directive parameters')
    parser.add_argument('--request-id')
    args=parser.parse_args()
    item=strict_json(args.instruction.read_bytes(),maximum_bytes=8192)
    ident=enqueue(args.input,episode_id=args.episode,expires_at=args.expires_at,parameters=item,request_id=args.request_id)
    print(json.dumps({'request_id':ident,'state':'queued_locally','input':str(args.input),
                      'note':'Delivery and execution must be confirmed in the controller journal.'},ensure_ascii=False))


if __name__=='__main__':main()
