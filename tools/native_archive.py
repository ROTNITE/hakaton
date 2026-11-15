"""Read/verify native indexed journals without loading episode history into RAM."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import struct
import zlib


ENTRY=struct.Struct('<QIIII')
MAX_RECORD=32*1024*1024


class ArchiveError(ValueError):
    pass


def file_sha256(path):
    checksum=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):checksum.update(block)
    return checksum.hexdigest()


class IndexedRecords:
    def __init__(self,stem):
        self.stem=Path(stem)
        self.data_path=Path(str(self.stem)+'.records')
        self.index_path=Path(str(self.stem)+'.index')
        size=self.index_path.stat().st_size
        if size%ENTRY.size:raise ArchiveError('Truncated index: '+str(self.index_path))
        self.count=size//ENTRY.size
        self.data_bytes=self.data_path.stat().st_size

    def __len__(self):
        return self.count

    def records(self,start=0,limit=None):
        if type(start) is not int or not 0<=start<=self.count:raise ArchiveError('Invalid record cursor')
        if limit is not None and (type(limit) is not int or limit<0):raise ArchiveError('Invalid record limit')
        stop=self.count if limit is None else min(self.count,start+limit)
        with self.index_path.open('rb') as index,self.data_path.open('rb') as data:
            index.seek(start*ENTRY.size)
            previous_end=None
            for number in range(start,stop):
                encoded=index.read(ENTRY.size)
                if len(encoded)!=ENTRY.size:raise ArchiveError('Index changed or truncated during read')
                offset,size,raw_size,crc,codec=ENTRY.unpack(encoded)
                if not 0<size<=MAX_RECORD or not 0<raw_size<=MAX_RECORD or codec not in (0,1):
                    raise ArchiveError('Invalid record header at '+str(number))
                if codec==0 and size!=raw_size:raise ArchiveError('Invalid raw size at '+str(number))
                if offset>self.data_bytes or size>self.data_bytes-offset:raise ArchiveError('Record extends past EOF')
                if previous_end is not None and offset!=previous_end:raise ArchiveError('Noncontiguous journal records')
                if number==0 and offset!=0:raise ArchiveError('First record offset is not zero')
                data.seek(offset);stored=data.read(size)
                if len(stored)!=size:raise ArchiveError('Truncated record at '+str(number))
                if codec:
                    try:
                        decoder=zlib.decompressobj();raw=decoder.decompress(stored,raw_size+1)
                    except zlib.error as error:raise ArchiveError('Invalid zlib record at '+str(number)) from error
                    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                        raise ArchiveError('Incomplete or oversized zlib record at '+str(number))
                else:raw=stored
                if len(raw)!=raw_size or zlib.crc32(raw)!=crc:raise ArchiveError('Record size/CRC mismatch at '+str(number))
                previous_end=offset+size
                yield raw
            if stop==self.count and previous_end is not None and previous_end!=self.data_bytes:
                raise ArchiveError('Unindexed data tail; archive is incomplete')
            if self.count==0 and self.data_bytes:raise ArchiveError('Unindexed nonempty data file')

    def json_records(self,**kwargs):
        for raw in self.records(**kwargs):
            try:
                value=json.loads(raw.decode('utf-8'),parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
            except (UnicodeError,ValueError) as error:raise ArchiveError('Invalid UTF-8/JSON record') from error
            if not isinstance(value,dict):raise ArchiveError('Journal record is not an object')
            yield value


def verify_archive(directory,*,require_complete=True):
    directory=Path(directory)
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format')!='metarescue.indexed-json.v1':raise ArchiveError('Unknown native journal format')
    if require_complete and manifest.get('state')!='complete':raise ArchiveError('Native archive is '+str(manifest.get('state')))
    result={'format':manifest['format'],'episode_id':manifest['episode_id'],'state':manifest['state'],
            'status':manifest['status'],'time':manifest['time'],'files':{},
            'resident_indices':{k:manifest.get(k) for k in ('replay_index_entries','live_command_states','agent_command_digests')}}
    for name in ('public','truth','replay'):
        reader=IndexedRecords(directory/name);counts=Counter();uncompressed=0
        expected=manifest['files'][name]
        for key,actual in [('records',len(reader)),('stored_bytes',reader.data_bytes),('index_bytes',reader.index_path.stat().st_size)]:
            if expected[key]!=actual:raise ArchiveError('Manifest mismatch: '+name+'.'+key)
        for raw in reader.records():
            uncompressed+=len(raw)
            try:row=json.loads(raw.decode('utf-8'))
            except (UnicodeError,ValueError) as error:raise ArchiveError('Invalid record JSON in '+name) from error
            if not isinstance(row,dict) or (name!='replay' and row.get('episode_id')!=manifest['episode_id']):
                raise ArchiveError('Invalid episode or record in '+name)
            counts[row.get('record_type','replay')]+=1
        if uncompressed!=expected['uncompressed_bytes']:raise ArchiveError('Manifest raw-byte count mismatch: '+name)
        result['files'][name]={'records':len(reader),'stored_bytes':reader.data_bytes,'uncompressed_bytes':uncompressed,
            'record_types':dict(counts),'data_sha256':file_sha256(reader.data_path),'index_sha256':file_sha256(reader.index_path)}
    result['passed']=True
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    parser.add_argument('--export',type=Path,help='New directory for streaming JSONL.gz exports')
    args=parser.parse_args();result=verify_archive(args.directory)
    if args.export:
        args.export.mkdir(parents=True,exist_ok=False)
        for name in ('public','truth','replay'):
            with gzip.open(args.export/(name+'.jsonl.gz'),'xb',compresslevel=3) as output:
                for raw in IndexedRecords(args.directory/name).records():output.write(raw.rstrip(b'\n')+b'\n')
        (args.export/'source-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
