"""适配入口测试，仅合成后端与临时契约库。"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab_local_adapter as adapter
from ctflab_contract import canonical, ContractError, MAX_MESSAGE_BYTES
from ctflab_local_service import LocalService
from ctflab_windows_probe import FixtureBackend, request


@unittest.skipUnless(os.name == 'posix' and os.geteuid() != 0, '需要普通 POSIX 本机身份')
class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'state'
        LocalService.create(self.root)
        self.instance = str(uuid.uuid4())
        self.prepare = request(self.instance, 'prepare', parameters={'course_id':'course', 'baseline_id':'base'})

    def test_no_backend_rejects_before_intent(self):
        a = adapter.LocalAdapter(self.root)
        before = (self.root/'contract.sqlite3').read_bytes()
        result = a.dispatch(canonical(self.prepare))
        self.assertEqual(result['error']['code'], 'capability-unverified')
        self.assertEqual(before, (self.root/'contract.sqlite3').read_bytes())

    def test_injected_backend_and_retry(self):
        a = adapter.LocalAdapter(self.root, backend=FixtureBackend())
        first = a.dispatch(canonical(self.prepare))
        self.assertEqual(first['result'], 'completed')
        second = a.dispatch(canonical(self.prepare))
        self.assertEqual(first['operation_id'], second['operation_id'])
        self.assertEqual(first, second)
        self.assertIsNotNone(a.events(self.instance))

    def test_actor_cannot_be_supplied_by_message(self):
        a = adapter.LocalAdapter(self.root, backend=FixtureBackend())
        value = dict(self.prepare, actor='admin')
        self.assertEqual(a.dispatch(canonical(value))['error']['code'], 'invalid-request')

    def test_changed_identity_rejected(self):
        a = adapter.LocalAdapter(self.root)
        with mock.patch.object(adapter, 'process_actor', return_value='other'):
            self.assertEqual(a.dispatch(canonical(self.prepare))['error']['code'], 'permission-denied')
            self.assertEqual(a.events(self.instance)['error']['code'], 'permission-denied')

    def test_privileged_identity_rejected(self):
        with mock.patch.object(adapter.os, 'geteuid', return_value=0):
            with self.assertRaises(ContractError): adapter.process_actor()

    def test_unsupported_host_fails_closed(self):
        with mock.patch.object(adapter.os, 'name', 'unsupported'):
            with self.assertRaises(ContractError): adapter.process_actor()

    def test_framing_and_utf8(self):
        a = adapter.LocalAdapter(self.root)
        out = io.BytesIO()
        code = adapter.serve(a, io.BytesIO(b'\xff\n{}\n'), out)
        self.assertEqual(code, 0)
        self.assertEqual(len(out.getvalue().splitlines()), 2)
        self.assertNotIn(b'Traceback', out.getvalue())

    def test_overlong_frame_does_not_dispatch_tail(self):
        fake = mock.Mock()
        out = io.BytesIO()
        self.assertEqual(adapter.serve(fake, io.BytesIO(b'x'*(MAX_MESSAGE_BYTES+1)+b'\n{}\n'), out), 2)
        fake.dispatch.assert_not_called()
        self.assertEqual(len(out.getvalue().splitlines()), 1)

    def test_truncated_frame_rejected(self):
        fake = mock.Mock()
        self.assertEqual(adapter.serve(fake, io.BytesIO(b'{}'), io.BytesIO()), 2)
        fake.dispatch.assert_not_called()

    def test_real_isolated_cli_readonly_and_no_path_leak(self):
        a = adapter.LocalAdapter(self.root, backend=FixtureBackend())
        a.dispatch(canonical(self.prepare))
        req = request(self.instance, 'status')
        before = hashlib.sha256((self.root/'contract.sqlite3').read_bytes()).hexdigest()
        proc = subprocess.run([sys.executable, '-I', str(Path(adapter.__file__)), '--root', str(self.root)],
                              input=canonical(req)+'\n', text=True, capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['state'], 'prepared')
        self.assertEqual(before, hashlib.sha256((self.root/'contract.sqlite3').read_bytes()).hexdigest())
        self.assertNotIn(str(self.root), proc.stdout)

    def test_missing_root_does_not_initialize(self):
        missing = self.root/'missing'
        proc = subprocess.run([sys.executable, '-I', str(Path(adapter.__file__)), '--root', str(missing)],
                              input='', text=True, capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(missing.exists())
        self.assertNotIn(str(missing), proc.stdout+proc.stderr)

    def test_main_cli_routes_without_old_state_creation(self):
        import ctflab
        legacy = self.root/'legacy'
        with mock.patch.object(adapter, 'main', return_value=0) as entry:
            self.assertEqual(ctflab.main(['--state-dir', str(legacy), 'local-contract', '--root', str(self.root)]), 0)
            entry.assert_called_once_with(['--root', str(self.root)])
        self.assertFalse(legacy.exists())

    def test_plan_and_catalog_cli_do_not_create_legacy_state(self):
        import ctflab
        import ctflab_catalog
        import ctflab_scenario_v2
        legacy = self.root/'legacy'
        with mock.patch.object(ctflab_scenario_v2, 'main', return_value=0) as entry:
            self.assertEqual(ctflab.main(['--state-dir',str(legacy),'scenario-plan-v2','manifest.json',
                                         '--instance',self.instance]),0)
            entry.assert_called_once_with(['manifest.json','--instance',self.instance,'--generation','1'])
        with mock.patch.object(ctflab_catalog, 'main', return_value=0) as entry:
            self.assertEqual(ctflab.main(['--state-dir',str(legacy),'course-catalog','catalog.json',
                                         '--course','course','--host-architecture','x86_64']),0)
            entry.assert_called_once()
        self.assertFalse(legacy.exists())
