import json
from pathlib import Path
import tempfile
import unittest
import zlib

from tools.native_archive import ArchiveError,ENTRY,IndexedRecords,MAX_RECORD


class NativeArchiveTests(unittest.TestCase):
    def make(self,directory):
        path=Path(directory)/'public';rows=[b'{"type":"small"}\n',json.dumps({'payload':'abcdef'*10000}).encode()]
        data=bytearray();entries=[]
        for codec,raw in enumerate(rows):
            stored=zlib.compress(raw) if codec else raw
            entries.append(ENTRY.pack(len(data),len(stored),len(raw),zlib.crc32(raw),codec));data.extend(stored)
        Path(str(path)+'.records').write_bytes(data);Path(str(path)+'.index').write_bytes(b''.join(entries))
        return path,rows

    def test_raw_compressed_random_page_and_empty_end(self):
        with tempfile.TemporaryDirectory() as directory:
            path,rows=self.make(directory);reader=IndexedRecords(path)
            self.assertEqual(list(reader.records()),rows);self.assertEqual(list(reader.records(start=1,limit=1)),rows[1:])
            self.assertEqual(list(reader.records(start=2)),[]);self.assertEqual(len(list(reader.json_records())),2)
            with self.assertRaises(ArchiveError):list(reader.records(start=-1))

    def test_truncation_crc_and_unindexed_tail_are_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            path,_=self.make(directory);data=Path(str(path)+'.records');original=data.read_bytes()
            for changed in (original[:-2],b'!'+original[1:],original+b'orphan'):
                data.write_bytes(changed)
                with self.assertRaises(ArchiveError):list(IndexedRecords(path).records())
            index=Path(str(path)+'.index');index.write_bytes(index.read_bytes()[:-1])
            with self.assertRaises(ArchiveError):IndexedRecords(path)

    def test_decompression_bomb_and_invalid_codec_are_rejected_before_allocation(self):
        with tempfile.TemporaryDirectory() as directory:
            path,_=self.make(directory);data=Path(str(path)+'.records');index=Path(str(path)+'.index')
            for raw_size,codec in ((MAX_RECORD+1,1),(10,1),(60000,8)):
                stored=zlib.compress(b'x'*60000);data.write_bytes(stored)
                index.write_bytes(ENTRY.pack(0,len(stored),raw_size,0,codec))
                with self.assertRaises(ArchiveError):list(IndexedRecords(path).records())


if __name__=='__main__':unittest.main()
