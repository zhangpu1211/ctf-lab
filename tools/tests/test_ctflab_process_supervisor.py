from pathlib import Path
import sys,tempfile,unittest,uuid
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_process_supervisor import Supervisor,SupervisorError
from ctflab_windows_native import ProcessIdentity

class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.identity=ProcessIdentity(123,456,'fixture.exe','running')
        self.observe=Mock(return_value=self.identity)
        self.transport=Mock();self.transport.process.pid=123;self.transport.command.return_value={'message':{'return':{}}}
        self.s=Supervisor(self.root,self.transport,self.identity,self.observe,lambda root:None)
        self.s.bind(str(uuid.uuid4()),1)
    def test_intent_before_side_effect_and_no_replay(self):
        op=str(uuid.uuid4())
        def check(cmd):
            self.assertTrue((self.root/(op+'.intent.json')).exists())
            return {'message':{'return':{}}}
        self.transport.command.side_effect=check
        self.assertEqual(self.s.command(op,'system_powerdown')['state'],'acknowledged')
        with self.assertRaises(SupervisorError):self.s.command(op,'system_powerdown')
        self.assertEqual(self.transport.command.call_count,1)
    def test_pid_reuse_denies_control(self):
        self.observe.return_value=ProcessIdentity(123,999,'fixture.exe','running')
        with self.assertRaises(SupervisorError):self.s.command(str(uuid.uuid4()),'query-status')
        self.transport.command.assert_not_called()
    def test_unknown_identity_denies(self):
        self.observe.side_effect=OSError('gone')
        with self.assertRaises(SupervisorError):self.s.command(str(uuid.uuid4()),'query-status')
        self.transport.command.assert_not_called()
    def test_timeout_preserves_unknown(self):
        self.transport.command.side_effect=TimeoutError()
        op=str(uuid.uuid4())
        with self.assertRaises(SupervisorError):self.s.command(op,'system_powerdown')
        self.assertIn('unknown',(self.root/(op+'.result.json')).read_text())
    def test_interrupted_intent_not_replayed(self):
        op=str(uuid.uuid4());(self.root/(op+'.intent.json')).write_text('{}')
        self.assertEqual(len(self.s.recovery_status()['unresolved_operations']),1)
        with self.assertRaises(SupervisorError):self.s.command(op,'system_powerdown')
        self.transport.command.assert_not_called()
    def test_stale_lock_preserved(self):
        (self.root/'operation.lock').write_text('')
        with self.assertRaises(SupervisorError):self.s.command(str(uuid.uuid4()),'query-status')
        self.assertTrue((self.root/'operation.lock').exists())
    def test_exit_not_graceful_claim(self):
        self.transport.observe.return_value={'state':'exited','returncode':0}
        self.s.record_exit()
        self.assertIn('false',(self.root/'exit.json').read_text())
