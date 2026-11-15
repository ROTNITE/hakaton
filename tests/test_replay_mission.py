import base64
import json
from pathlib import Path
import tempfile
import unittest
import zlib

from tools.native_archive import ENTRY
from tools.replay_mission import recorded_steps


class NativeReplayReadTests(unittest.TestCase):
    def store(self, root, rows):
        with (root/'replay.records').open('wb') as data, (root/'replay.index').open('wb') as index:
            for row in rows:
                raw=json.dumps(row).encode()
                index.write(ENTRY.pack(data.tell(),len(raw),len(raw),zlib.crc32(raw),0))
                data.write(raw)

    def test_flat_replay_rows_keep_accepted_decisions_in_order(self):
        accepted=[]
        rows=[]
        for stamp in (1,2):
            decision={'decision_id':f'd-{stamp}','episode_id':'episode','request_id':f'r-{stamp}','time':stamp-1}
            response={'episode_id':'episode','request_id':f'r-{stamp}','time':stamp,'status':'running'}
            rows.append({'decision_id':decision['decision_id'],'http_status':200,
                         'request_body_base64':base64.b64encode(json.dumps(decision).encode()).decode(),
                         'response':json.dumps(response)})
            accepted.append((decision,response))
        rows.insert(1,{'http_status':422,'response':'{"error":{"code":"INVALID_COMMAND"}}'})
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.store(root,rows)
            self.assertEqual(list(recorded_steps(root)),accepted)

    def test_mismatched_record_identity_is_rejected(self):
        decision={'decision_id':'original','episode_id':'episode','request_id':'request'}
        response={'episode_id':'episode','request_id':'unrelated'}
        row={'decision_id':'original','http_status':200,
             'request_body_base64':base64.b64encode(json.dumps(decision).encode()).decode(),
             'response':json.dumps(response)}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.store(root,[row])
            with self.assertRaisesRegex(ValueError,'Native replay request and response identities differ'):
                list(recorded_steps(root))


if __name__=='__main__':
    unittest.main()
