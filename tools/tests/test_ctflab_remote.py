"""远程消息身份、角色范围与SSH固定参数；不连接真实SSH主机。"""
from datetime import datetime, timedelta, timezone
import json
import os
import threading
import time
from unittest.mock import patch
from pathlib import Path
import sys
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_ctflab_generation_store as generation_tests
from ctflab_contract import ContractError
from ctflab_generation_store import digest
from ctflab_remote import Runner, ssh_arguments, decode, exchange, SSHSession, PROTOCOL


class RemoteTests(unittest.TestCase):
    setUp = generation_tests.GenerationTests.setUp

    def setup_runner(self, principal='alice'):
        self.server = str(uuid.uuid4()); self.calls = []
        self.policy = {'schema': 1, 'server_uuid': self.server,
                       'principals': {name: {'role': role, 'instances': [self.instance], 'expires': '2099-01-01T00:00:00Z'}
                                      for name, role in [('alice','student'),('bob','student'),('teacher','teacher')]},
                       'instances': {self.instance: {'root': str(self.store.root), 'owner': 'alice'}}}
        def dispatch(root, payload): self.calls.append((root, payload)); return {'state': 'fixture'}
        self.runner = Runner(self.policy, principal, dispatch=dispatch)

    def request(self, action='overview', parameters=None):
        return {'protocol': PROTOCOL, 'version': 1, 'request_id': str(uuid.uuid4()), 'server_uuid': self.server,
                'action': action, 'parameters': parameters if parameters is not None else {'instance_uuid': self.instance}}

    def submit(self, operation='start'):
        request = {'protocol': 'ctflab-local', 'version': 1, 'request_id': str(uuid.uuid4()),
                   'operation': operation, 'instance_uuid': self.instance, 'idempotency_key': str(uuid.uuid4()),
                   'expected_generation': 1, 'expected_state_revision': 1,
                   'parameters': {'display': 'headless', 'allow_emulation': False} if operation == 'start' else {}}
        return self.request('submit', {'instance_uuid': self.instance, 'request': request})

    def test_handshake_has_explicit_capabilities_and_no_implicit_shell_or_upload(self):
        self.setup_runner(); result = self.runner.exchange(self.request('handshake', {}))['result']
        self.assertEqual(result['role'], 'student'); self.assertFalse(result['arbitrary_commands'])
        self.assertFalse(result['asset_upload']); self.assertFalse(result['display_tunnel'])
        self.assertEqual(self.calls, [])

    def test_students_cannot_access_another_owner_even_with_misassigned_scope(self):
        self.setup_runner('bob')
        self.assertEqual(self.runner.exchange(self.request('list', {}))['result']['instances'], [])
        for action in ('overview', 'diagnostics'):
            with self.assertRaises(ContractError): self.runner.exchange(self.request(action))
        self.assertEqual(self.calls, [])

    def test_teacher_still_requires_explicit_instance_scope(self):
        self.setup_runner('teacher'); self.policy['principals']['teacher']['instances'] = []
        with self.assertRaises(ContractError): self.runner.exchange(self.request())
        self.assertEqual(self.calls, [])

    def test_identity_version_principal_and_path_injection_refused(self):
        self.setup_runner()
        for key, value in [('server_uuid',str(uuid.uuid4())), ('version',True), ('principal','teacher')]:
            request = self.request(); request[key] = value
            with self.assertRaises(ContractError): self.runner.exchange(request)
        request = self.request(); request['parameters']['root'] = '/tmp/other'
        with self.assertRaises(ContractError): self.runner.exchange(request)
        request = self.request(); request['action'] = 'shell'
        with self.assertRaises(ContractError): self.runner.exchange(request)
        self.assertEqual(self.calls, [])

    def test_expiry_refuses_start_but_allows_normal_stop_and_overview(self):
        self.setup_runner(); self.policy['principals']['alice']['expires'] = '2000-01-01T00:00:00Z'
        with self.assertRaises(ContractError): self.runner.exchange(self.submit())
        self.runner.exchange(self.submit('stop')); self.runner.exchange(self.request())
        self.assertEqual(len(self.calls), 2)

    def test_payload_instance_cannot_differ_from_authorized_instance(self):
        self.setup_runner(); request = self.submit()
        request['parameters']['request']['instance_uuid'] = str(uuid.uuid4())
        with self.assertRaises(ContractError): self.runner.exchange(request)
        self.assertEqual(self.calls, [])

    def test_duplicate_keys_and_oversize_requests_refused(self):
        with self.assertRaises(ContractError): decode(b'{"action":1,"action":2}')
        with self.assertRaises(ContractError): decode(b' '*65537)
        with self.assertRaises(ContractError): decode(b'{"number":NaN}')

    def test_ssh_host_keys_are_pinned_and_configuration_cannot_inject_commands(self):
        self.setup_runner()
        binary = self.root/'ssh'; binary.write_bytes(b'fixture-not-executed')
        known = self.root/'known_hosts'; known.write_text('fixture-host-key\n'); known.chmod(0o600)
        key = self.root/'identity'; key.write_text('fixture-key\n'); key.chmod(0o600)
        config = {'schema': 1, 'host':'runner.invalid', 'user':'student', 'port':22,
                  'ssh':str(binary), 'identity':str(key), 'known_hosts':str(known),
                  'known_hosts_sha256':digest(known), 'server_uuid': self.server}
        args = ssh_arguments(config)
        self.assertEqual(args[-1], 'ctflab-runner-v1')
        for flag in ('StrictHostKeyChecking=yes','ClearAllForwardings=yes','ProxyCommand=none','IdentityAgent=none'):
            self.assertIn(flag, args)
        known.write_text('changed-host-key')
        with self.assertRaises(ContractError): ssh_arguments(config)
        config['known_hosts_sha256'] = digest(known)
        for host in ('-oProxyCommand=bad', 'host;command', 'host\noption', 'user@host'):
            config['host'] = host
            with self.assertRaises(ContractError): ssh_arguments(config)
        config['host'] = 'runner.invalid'
        for filename in ("foo'bar", 'foo\\bar', 'foo#bar'):
            config['known_hosts'] = str(self.root/filename)
            with self.assertRaises(ContractError): ssh_arguments(config)

    def transport(self, body):
        self.setup_runner()
        executable = self.root/'ssh'
        executable.write_text('#!'+sys.executable+'\n'+body); executable.chmod(0o700)
        known = self.root/'known_hosts'; known.write_text('fixture-host-key'); known.chmod(0o600)
        key = self.root/'identity'; key.write_text('fixture-private-material'); key.chmod(0o600)
        return {'schema':1,'host':'runner.invalid','port':22,'user':'student','ssh':str(executable),
                'identity':str(key),'known_hosts':str(known),'known_hosts_sha256':digest(known),'server_uuid':self.server}

    @unittest.skipIf(os.name == 'nt', 'POSIX脚本替身；不代替Windows OpenSSH实测')
    def test_transport_real_owned_pipe_checks_reply_binding(self):
        config = self.transport('import json,sys\nv=json.load(sys.stdin)\nv.pop("parameters");v.pop("action");v["result"]={"state":"fixture"}\nprint(json.dumps(v))\n')
        request = self.request('handshake', {})
        self.assertEqual(exchange(config, request)['request_id'], request['request_id'])
        (self.root/'ssh').write_text('#!'+sys.executable+'\nimport json,sys\nv=json.load(sys.stdin)\nv.pop("parameters");v.pop("action");v["result"]={};v["request_id"]="wrong"\nprint(json.dumps(v))\n')
        with self.assertRaises(ContractError): exchange(config, request)

    @unittest.skipIf(os.name == 'nt', 'POSIX脚本替身；不代替Windows OpenSSH实测')
    def test_transport_output_limit_ends_only_owned_transport(self):
        config = self.transport('import sys\nsys.stdin.read()\nsys.stdout.buffer.write(b"x"*(5*1024**2))\n')
        with self.assertRaises(ContractError): exchange(config, self.request('handshake', {}))

    @unittest.skipIf(os.name == 'nt', 'POSIX脚本替身；不代替Windows OpenSSH实测')
    def test_transport_disconnect_does_not_replay_mutation(self):
        marker = self.root/'attempts'
        config = self.transport('import sys\nfrom pathlib import Path\nsys.stdin.read()\np=Path('+repr(str(marker))+')\np.write_text((p.read_text() if p.exists() else "")+"once\\n")\nraise SystemExit(2)\n')
        with self.assertRaises(ContractError): exchange(config, self.request('handshake', {}))
        self.assertEqual(marker.read_text(), 'once\n')

    @unittest.skipIf(os.name == 'nt', 'POSIX脚本替身；不代替Windows OpenSSH实测')
    def test_transport_timeout_does_not_leave_a_waiting_owned_process(self):
        import subprocess
        config = self.transport('import sys,time\nsys.stdin.read()\ntime.sleep(10)\n')
        with self.assertRaises(subprocess.TimeoutExpired): exchange(config, self.request('handshake', {}), timeout=.1)

    @unittest.skipIf(os.name == 'nt', 'POSIX脚本替身；不代替Windows OpenSSH实测')
    def test_persistent_session_has_multiple_bound_requests_on_one_owned_process(self):
        config=self.transport('import json,sys\ncount=0\nfor raw in sys.stdin:\n v=json.loads(raw);count+=1\n action=v.pop("action");v.pop("parameters");v["result"]={"sequence":count,"action":action}\n print(json.dumps(v),flush=True)\n')
        with SSHSession(config) as session:
            self.assertEqual(session.request('handshake',{})['sequence'],1)
            self.assertEqual(session.request('list',{})['sequence'],2)
        self.assertEqual(session.process.returncode,0)

    @unittest.skipIf(os.name == 'nt', 'POSIX脚本替身；不代替Windows OpenSSH实测')
    def test_persistent_session_wrong_response_closes_without_replay(self):
        config=self.transport('import json,sys\nv=json.loads(sys.stdin.readline());v.pop("action");v.pop("parameters");v["result"]={};v["request_id"]="wrong"\nprint(json.dumps(v),flush=True)\n')
        session=SSHSession(config)
        with self.assertRaises(ContractError):session.request('handshake',{})
        self.assertTrue(session.closed);self.assertIsNotNone(session.process.poll())

    @unittest.skipIf(os.name == 'nt', 'POSIX脚本替身；不代替Windows OpenSSH实测')
    def test_persistent_session_timeout_closes_only_owned_transport(self):
        config=self.transport('import sys,time\nsys.stdin.readline()\ntime.sleep(10)\n')
        session=SSHSession(config,timeout=.1)
        with self.assertRaises(ContractError):session.request('handshake',{})
        self.assertTrue(session.closed);self.assertIsNotNone(session.process.poll())

    @unittest.skipIf(os.name == 'nt', 'POSIX脚本替身；不代替Windows OpenSSH实测')
    def test_persistent_session_overlarge_line_is_rejected(self):
        config=self.transport('import sys\nsys.stdin.readline()\nsys.stdout.buffer.write(b"x"*(5*1024**2));sys.stdout.buffer.flush()\n')
        session=SSHSession(config)
        with self.assertRaises(ContractError):session.request('handshake',{})
        self.assertTrue(session.closed);self.assertIsNotNone(session.process.poll())


    def test_pre_cancel_does_not_spawn_any_owned_transport(self):
        with patch('ctflab_remote.subprocess.Popen') as spawned:
            with self.assertRaises(ContractError):SSHSession({},cancel_requested=lambda:True)
            spawned.assert_not_called()

    @unittest.skipIf(os.name=='nt','POSIX脚本替身；不代替Windows OpenSSH实测')
    def test_cancel_during_reply_wait_closes_owned_transport_without_new_request(self):
        config=self.transport('import sys,time\nsys.stdin.readline()\ntime.sleep(10)\n')
        cancel=threading.Event();session=SSHSession(config,cancel_requested=cancel.is_set)
        timer=threading.Timer(.1,cancel.set);timer.start();self.addCleanup(timer.cancel)
        started=time.monotonic()
        with self.assertRaises(ContractError):session.request('handshake',{})
        self.assertLess(time.monotonic()-started,3)
        self.assertTrue(session.closed);self.assertIsNotNone(session.process.poll())

    @unittest.skipIf(os.name=='nt','POSIX脚本替身；不代替Windows OpenSSH实测')
    def test_cancel_during_blocked_stdin_does_not_leave_writer_or_transport(self):
        config=self.transport('import time\ntime.sleep(10)\n');cancel=threading.Event()
        session=SSHSession(config,cancel_requested=cancel.is_set);timer=threading.Timer(.1,cancel.set)
        timer.start();self.addCleanup(timer.cancel)
        with self.assertRaises(ContractError):session.request('handshake',{'padding':'x'*60000})
        self.assertTrue(session.closed);self.assertIsNotNone(session.process.poll())


if __name__ == '__main__': unittest.main()
