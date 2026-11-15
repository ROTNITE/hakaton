import json
from pathlib import Path
import tempfile
import unittest

from controller.operational import FORMAT,OperationalControl


class OperationalTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/'control.json'
        self.control=OperationalControl(self.path,session_id='session')
        self.revision=0

    def write(self,mode='paused',steps=0,**extra):
        self.revision+=1
        data={'format':FORMAT,'session_id':'session','revision':self.revision,'mode':mode,'step_total':steps}
        data.update(extra)
        self.path.write_text(json.dumps(data))

    def test_pause_does_not_consume_steps_and_retry_commits_once(self):
        self.write()
        self.assertEqual(self.control.take(),'wait')
        self.write(steps=2)
        self.assertEqual(self.control.take(),'advance')
        self.assertEqual(self.control.take(),'advance')
        self.assertEqual(self.control.snapshot()['completed_steps'],0)
        self.control.complete()
        self.assertEqual(self.control.snapshot()['completed_steps'],1)
        self.control.complete()
        self.assertEqual(self.control.snapshot()['completed_steps'],1)
        self.assertEqual(self.control.take(),'advance')
        self.control.complete()
        self.assertEqual(self.control.take(),'wait')
        self.write('running',2)
        self.assertEqual(self.control.take(),'advance')
        self.write('paused',2)
        self.assertEqual(self.control.take(),'wait')

    def test_invalid_missing_and_foreign_documents_fail_closed(self):
        self.assertEqual(self.control.take(),'wait')
        self.write('running')
        self.assertEqual(self.control.take(),'advance')
        self.path.write_text('{')
        self.assertEqual(self.control.take(),'wait')
        self.write('running',session_id='other')
        self.assertEqual(self.control.take(),'wait')
        self.write('running',steps=True)
        self.assertEqual(self.control.take(),'wait')
        self.write('running')
        self.assertEqual(self.control.take(),'advance')

    def test_stop_latches_and_old_or_reused_revisions_cannot_restart(self):
        self.write(steps=1)
        self.control.take();self.control.complete()
        self.write('running',steps=0)
        self.assertEqual(self.control.take(),'wait')
        self.write('stopping',steps=1)
        self.assertEqual(self.control.take(),'stop')
        self.write('running',steps=1)
        self.assertEqual(self.control.take(),'stop')
        self.path.unlink()
        self.assertEqual(self.control.take(),'stop')
        fresh=OperationalControl(self.path,session_id='session')
        self.write()
        self.assertEqual(fresh.take(),'wait')
        self.write('running',revision=self.revision)
        self.assertEqual(fresh.take(),'wait')
        self.assertIn('reused',fresh.snapshot()['error'])
