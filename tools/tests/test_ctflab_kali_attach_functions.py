"""生成助手真实函数测试：执行材料内脚本本体，覆盖描述符交接/序号链/租约清理。

不创建真实TAP（需Linux内核）；fork路径在macOS上走失败分支验证清理与回收。
"""
import io
import json
import os
import socket
import struct
import sys
import time
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ctflab_kali_attach import render_assistant


def load_assistant():
    namespace = {'__name__': 'assistant-under-test'}
    exec(compile(render_assistant(), 'ctflab-kali-attach', 'exec'), namespace)
    return namespace


class DescriptorHandoffTests(unittest.TestCase):
    def test_send_receive_descriptor_roundtrip(self):
        """核验复现处：recvmsg第二参数必须为整数；收发边界与所有权。"""
        namespace = load_assistant()
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(parent.close)
        self.addCleanup(child.close)
        original = os.open('/dev/null', os.O_RDONLY)
        self.addCleanup(os.close, original)
        namespace['send_descriptor'](child, original)
        received = namespace['receive_descriptor'](parent)
        self.assertIsInstance(received, int)
        self.assertGreaterEqual(received, 0)
        os.close(received)  # 副本所有权归接收方
        os.fstat(original)  # 原fd仍有效

    def test_create_tap_failure_returns_none_and_reaps_child(self):
        """setns不可用（非Linux/缺netns）时走失败分支：返回None、回收子进程。"""
        namespace = load_assistant()
        started = time.monotonic()
        result = namespace['create_tap_in_ns']('ctflab-absent-ns', 'ctftap-absent')
        self.assertIsNone(result)
        self.assertLess(time.monotonic() - started, 10, '失败路径不得挂起')

    def test_receive_rejects_incomplete_rights(self):
        namespace = load_assistant()
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(parent.close)
        self.addCleanup(child.close)
        child.sendall(b'truncated')
        child.close()
        with self.assertRaises(OSError):
            namespace['receive_descriptor'](parent)


class SequenceEnforcementTests(unittest.TestCase):
    def test_duplicate_regressed_and_skipped_sequences_rejected(self):
        namespace = load_assistant()
        check = namespace['read_record_checked']
        stream = io.BytesIO(b'\x01\x00\x00\x00\x07\x00\x02' + b'a' * 2
                            + b'\x01\x00\x00\x00\x07\x00\x02' + b'b' * 2
                            + b'\x01\x00\x00\x00\x09\x00\x02' + b'c' * 2)
        first = check(stream, 7)
        self.assertEqual(first, (0x01, 7, b'a' * 2))
        self.assertIsNone(check(stream, 8), '重复序号必须拒绝')
        self.assertIsNone(check(stream, 7), '回退后跳号必须拒绝')

    def test_heartbeat_and_close_kinds_have_bounded_payloads(self):
        namespace = load_assistant()
        self.assertEqual(namespace['PAYLOAD_LIMITS'][0x03], 0)
        self.assertEqual(namespace['PAYLOAD_LIMITS'][0x04], 256)


class LeaseLifecycleTests(unittest.TestCase):
    def test_grant_expiry_and_sweep_close_lifecycle_fd(self):
        namespace = load_assistant()
        session = '11111111-2222-3333-4444-555555555555'
        expired = {'session': session, 'netns': namespace['netns_name'](session),
                   'tap': namespace['tap_name'](session),
                   'mac': '02:aa:bb:cc:dd:ee', 'address': '192.168.242.66',
                   'prefix': 24, 'mtu': 1400, 'expires': '2000-01-01T00:00:00Z'}
        fd = os.open('/dev/null', os.O_RDONLY)
        sessions = {session: {'grant': expired, 'tap_fd': fd}}
        with tempfile.TemporaryDirectory() as root:
            namespace['STATE_ROOT'] = root
            namespace['namespace_present'] = lambda _: False
            namespace['sweep_expired'](sessions)
        self.assertNotIn(session, sessions)
        with self.assertRaises(OSError):
            os.fstat(fd)  # daemon生命周期FD已关闭，TAP随之释放

    def test_live_session_not_swept(self):
        namespace = load_assistant()
        session = '22222222-2222-3333-4444-555555555555'
        live = {'session': session, 'netns': 'ctflab-live', 'tap': 'ctf2222',
                'mac': '02:aa:bb:cc:dd:ee', 'address': '192.168.242.66',
                'prefix': 24, 'mtu': 1400,
                'expires': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() + 3600))}
        fd = os.open('/dev/null', os.O_RDONLY)
        self.addCleanup(os.close, fd)
        sessions = {session: {'grant': live, 'tap_fd': fd}}
        namespace['sweep_expired'](sessions)
        self.assertIn(session, sessions)
        os.fstat(fd)  # 未到期不回收


class SignalAndGuardTests(unittest.TestCase):
    def test_sigterm_handler_uses_event_not_globals_setattr(self):
        script = render_assistant()
        self.assertIn('stopping.set()', script)
        self.assertNotIn('setattr(globals', script)

    def test_attach_rejects_session_argument_and_uses_handshake(self):
        script = render_assistant()
        self.assertIn('attach不接受会话参数', script)
        self.assertIn("'action': 'attach'", script)
        self.assertIn('challenge_echo', script)

    def test_run_reports_missing_binary_as_failure(self):
        namespace = load_assistant()
        self.assertEqual(namespace['run'](['ctflab-definitely-missing-binary']), 1)



class ProductionControlChainTests(unittest.TestCase):
    """真实Unix socket/描述符+生成的客户端与daemon函数；网络设备以/dev/null替代。"""
    SESSION = '11111111-2222-4333-8444-555555555555'

    def binding(self):
        return {'instance_uuid': self.SESSION, 'generation': 2,
                'network_id': 'outer', 'policy_sha256': 'b' * 64,
                'mac': '02:aa:bb:cc:dd:ee', 'address': '192.168.50.9', 'mtu': 1400}

    def test_client_daemon_descriptor_before_identity_and_continuous_sequence(self):
        import threading
        from types import SimpleNamespace
        ns = load_assistant()
        a, b = socket.socketpair()
        self.addCleanup(a.close); self.addCleanup(b.close)
        a.settimeout(2); b.settimeout(2)
        fd = os.open('/dev/null', os.O_RDONLY)
        self.addCleanup(os.close, fd)
        grant = dict(self.binding(), session=self.SESSION, expires='2099-01-01T00:00:00Z')
        sessions = {self.SESSION: {'grant': grant, 'tap_fd': fd}}
        ns['control_connection'] = lambda: a
        ns['self_digest'] = lambda: 'a' * 64
        ns['read_machine_uuid'] = lambda: self.SESSION
        hello = dict(self.binding(), handshake=ns['HANDSHAKE_HOST'],
                     session_uuid=self.SESSION, challenge='c' * 32)
        payload = json.dumps(hello).encode()
        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, write_fd)
        stdin = os.fdopen(read_fd, 'rb')
        self.addCleanup(stdin.close)
        os.write(write_fd, struct.pack('!BIH', 2, 0, len(payload)) + payload
                 + struct.pack('!BIH', ns['RECORD_HEARTBEAT'], 1, 0)
                 + struct.pack('!BIH', ns['RECORD_HEARTBEAT'], 2, 0))
        stdout = io.BytesIO()
        ns['sys'] = SimpleNamespace(stdin=SimpleNamespace(buffer=stdin),
                                    stdout=SimpleNamespace(buffer=stdout))
        errors = []
        def serve():
            try:
                request = json.loads(b.recv(65536).decode())
                reply = ns['handle_daemon'](request, 123, 123, sessions, b)
                if reply is not None:
                    b.sendall((json.dumps(reply) + '\n').encode())
            except BaseException as error:
                errors.append(error)
            finally:
                b.close()
        def pump(grant_value, received, source):
            os.fstat(received)  # 已取得有效FD之后才能对宿主应答。
            self.assertTrue(stdout.getvalue())
            os.close(received)
            self.assertEqual(grant_value, grant)
            import select
            self.assertTrue(select.select([source], [], [], 0)[0], 'HELLO不得预读并隐藏后续记录')
            self.assertEqual(ns['read_record_checked'](source, 1)[0], ns['RECORD_HEARTBEAT'])
            self.assertTrue(select.select([source], [], [], 0)[0], '读取一条后select仍须观察下一条')
        ns['pump_frames'] = pump
        thread = threading.Thread(target=serve); thread.start()
        try:
            ns['attach_client']()
        finally:
            thread.join(3)
        self.assertFalse(thread.is_alive()); self.assertEqual(errors, [])
        stdout.seek(0)
        self.assertEqual(ns['read_record_checked'](stdout, 0)[0], ns['RECORD_CONTROL'])

    def test_daemon_rejects_every_unapproved_binding_before_fd_transfer(self):
        ns = load_assistant()
        grant = dict(self.binding(), session=self.SESSION, expires='2099-01-01T00:00:00Z')
        for key, changed in [('instance_uuid', '0' * 36), ('generation', 3),
                             ('generation', True), ('network_id', 'other'),
                             ('policy_sha256', 'a' * 64)]:
            hello = dict(self.binding(), **{key: changed})
            result = ns['handle_daemon']({'action': 'attach', 'session': self.SESSION,
                                          'hello': hello}, 123, 123,
                                         {self.SESSION: {'grant': grant}}, None)
            self.assertEqual(result, {'error': 'grant-mismatch'})

    def test_setup_rejects_missing_admin_binding_before_network_commands(self):
        ns = load_assistant()
        ns['load_grant'] = lambda _: None
        ns['run'] = lambda _: self.fail('不应执行网络命令')
        request = {'mac': '02:aa:bb:cc:dd:ee', 'address': '192.168.50.9',
                   'prefix': 24, 'mtu': 1400}
        self.assertEqual(ns['setup_session'](self.SESSION, request, {}),
                         {'error': 'invalid-binding'})

    def test_scm_rights_single_owner_no_hidden_duplicate(self):
        import fcntl
        ns = load_assistant()
        a, b = socket.socketpair()
        self.addCleanup(a.close); self.addCleanup(b.close)
        fd = os.open('/dev/null', os.O_RDONLY)
        self.addCleanup(os.close, fd)
        def open_fds():
            return {i for i in range(256) if self.is_open(i)}
        before = open_fds()
        ns['send_descriptor'](b, fd)
        received = ns['receive_descriptor'](a)
        os.close(received)
        self.assertEqual(open_fds(), before)

    @staticmethod
    def is_open(fd):
        try:
            os.fstat(fd)
            return True
        except OSError:
            return False

    def test_multiple_descriptors_rejected_and_all_received_fds_closed(self):
        ns = load_assistant()
        a, b = socket.socketpair()
        self.addCleanup(a.close); self.addCleanup(b.close)
        fd = os.open('/dev/null', os.O_RDONLY)
        self.addCleanup(os.close, fd)
        before = {i for i in range(256) if self.is_open(i)}
        b.sendmsg([b'fd'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, struct.pack('2i', fd, fd))])
        with self.assertRaises(OSError):
            ns['receive_descriptor'](a)
        self.assertEqual({i for i in range(256) if self.is_open(i)}, before)

    def test_shell_reaper_never_steals_tap_child_or_spins_on_live_child(self):
        from types import SimpleNamespace
        ns = load_assistant()
        ns['SHELL_CHILDREN'].update([111, 222])
        calls = []
        def wait(pid, options):
            calls.append(pid)
            return (0, 0) if pid == 111 else (pid, 0)
        ns['os'] = SimpleNamespace(waitpid=wait, WNOHANG=1)
        ns['reap_shell_children']()
        self.assertEqual(sorted(calls), [111, 222])
        self.assertEqual(ns['SHELL_CHILDREN'], {111})

    def test_linux_peer_credentials_extract_uid_not_pid(self):
        from types import SimpleNamespace
        ns = load_assistant()
        connection = SimpleNamespace(getsockopt=lambda *args: struct.pack('3i', 5678, 1234, 9876))
        self.assertEqual(ns['peer_uid'](connection), 1234)

    def test_pump_heartbeat_replies_continue_after_identity_sequence(self):
        from types import SimpleNamespace
        ns = load_assistant()
        stdin = io.BytesIO(struct.pack('!BIH', ns['RECORD_HEARTBEAT'], 1, 0)
                           + struct.pack('!BIH', ns['RECORD_CLOSE'], 2, 0))
        stdout = io.BytesIO()
        ns['sys'] = SimpleNamespace(stdout=SimpleNamespace(buffer=stdout))
        ns['select'] = SimpleNamespace(select=lambda *args: ([stdin], [], []))
        fd = os.open('/dev/null', os.O_RDONLY)
        ns['pump_frames']({'expires': '2099-01-01T00:00:00Z'}, fd, stdin)
        stdout.seek(0)
        self.assertEqual(ns['read_record_checked'](stdout, 1), (ns['RECORD_HEARTBEAT'], 1, b''))




class TeardownRecoveryTests(unittest.TestCase):
    SESSION = '11111111-2222-4333-8444-555555555555'

    def setUp(self):
        self.ns = load_assistant()
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.ns['STATE_ROOT'] = root.name
        self.grant = {'session': self.SESSION, 'netns': self.ns['netns_name'](self.SESSION),
                      'tap': self.ns['tap_name'](self.SESSION), 'expires': '2099-01-01T00:00:00Z'}
        self.fd = os.open('/dev/null', os.O_RDONLY)
        self.sessions = {self.SESSION: {'grant': self.grant, 'tap_fd': self.fd}}
        self.present = True
        self.names = {'lo'}
        self.pids = []
        self.commands = []
        self.ns['namespace_present'] = lambda _: self.present
        self.ns['namespace_resources'] = lambda _: (self.names, self.pids)
        self.ns['run'] = self.run_command
        self.ns['save_cleanup_grant'](self.grant)
        self.addCleanup(self.close_remaining)

    def close_remaining(self):
        entry = self.sessions.get(self.SESSION)
        if entry and entry.get('tap_fd') is not None:
            os.close(entry['tap_fd'])

    def run_command(self, argv):
        self.commands.append(argv)
        return 1

    def teardown(self):
        return self.ns['teardown_session'](self.SESSION, self.sessions)

    def test_failed_netns_delete_keeps_record_and_retry_closes(self):
        result = self.teardown()
        self.assertEqual(result['state'], 'cleanup-incomplete')
        self.assertFalse(result['netns_removed'])
        self.assertIn('netns', result['leftover'])
        self.assertIn(self.SESSION, self.sessions)
        self.assertTrue(self.ns['load_grant'](self.SESSION)['cleanup_pending'])
        with self.assertRaises(OSError):
            os.fstat(self.fd)
        # 第一轮已关闭FD；后续重试不可误关被操作系统复用的描述符。
        replacement = os.open('/dev/null', os.O_RDONLY)
        self.addCleanup(os.close, replacement)
        def successful(argv):
            if argv[:3] == ['ip', 'netns', 'del']:
                self.present = False
            return 0
        self.ns['run'] = successful
        result = self.teardown()
        os.fstat(replacement)
        self.assertEqual(result['state'], 'session-closed')
        self.assertEqual(result['leftover'], [])
        self.assertNotIn(self.SESSION, self.sessions)
        self.assertIsNone(self.ns['load_grant'](self.SESSION))

    def test_tap_delete_failure_does_not_detach_namespace(self):
        self.names.add(self.grant['tap'])
        result = self.teardown()
        self.assertIn('tap', result['leftover'])
        self.assertFalse(any(cmd[:3] == ['ip', 'netns', 'del'] for cmd in self.commands))

    def test_busy_or_unexpected_namespace_keeps_reference(self):
        for names, pids, reason in [({'lo'}, ['123'], 'namespace-processes'),
                                    ({'lo', 'user-link'}, [], 'unexpected-links')]:
            with self.subTest(reason=reason):
                self.names, self.pids = names, pids
                self.commands.clear()
                self.assertIn(reason, self.teardown()['leftover'])
                self.assertFalse(any(cmd[:3] == ['ip', 'netns', 'del'] for cmd in self.commands))

    def test_query_failure_is_unknown_not_absent(self):
        self.ns['namespace_resources'] = lambda _: None
        self.assertIn('namespace-inspection', self.teardown()['leftover'])
        self.assertFalse(any(cmd[:3] == ['ip', 'netns', 'del'] for cmd in self.commands))

    def test_grant_unlink_failure_cannot_report_complete(self):
        from unittest.mock import patch
        self.present = False
        with patch('os.unlink', side_effect=PermissionError('denied')):
            result = self.teardown()
        self.assertTrue(result['netns_removed'])
        self.assertEqual(result['leftover'], ['grant'])
        self.assertIn(self.SESSION, self.sessions)

    def test_restart_restores_cleanup_only_and_rejects_access(self):
        restored = self.ns['restore_cleanup_sessions']()
        self.assertIsNone(restored[self.SESSION]['tap_fd'])
        for action in ['verify', 'attach', 'shell']:
            reply = self.ns['handle_daemon']({'action': action, 'session': self.SESSION},
                                            123, 123, restored, None)
            self.assertEqual(reply, {'error': 'cleanup-pending'})
        self.present = False
        self.ns['sweep_expired'](restored)
        self.assertEqual(restored, {})

    def test_missing_or_mismatched_ownership_never_deletes_network(self):
        self.assertEqual(self.ns['teardown_session']('00000000-2222-4333-8444-555555555555', {} )['error'],
                         'session-unknown')
        self.grant['netns'] = 'user-network'
        self.assertEqual(self.teardown()['error'], 'session-unknown')
        self.assertEqual(self.commands, [])

    def test_disk_write_failure_preserves_memory_and_blocks_access(self):
        self.ns['save_cleanup_grant'] = lambda _: (_ for _ in ()).throw(OSError('disk-full'))
        result = self.teardown()
        self.assertIn('cleanup-record', result['leftover'])
        self.assertIn(self.SESSION, self.sessions)
        self.assertTrue(self.grant['cleanup_pending'])

    def test_setup_configuration_failure_retains_retry_record(self):
        sessions = {}
        self.present = False
        ns = self.ns
        def run(argv):
            if argv[:3] == ['ip', 'netns', 'add']:
                self.present = True
                return 0
            if 'addr' in argv:
                return 1
            if argv[:3] == ['ip', 'netns', 'del']:
                return 1  # 清理也失败，不能遗失记录。
            return 0
        ns['run'] = run
        fd = os.open('/dev/null', os.O_RDONLY)
        ns['create_tap_in_ns'] = lambda *_: fd
        os.unlink(Path(ns['STATE_ROOT']) / (self.SESSION + '.json'))
        request = dict(ProductionControlChainTests().binding(), prefix=24)
        request['binding'] = {key: request[key] for key in
                              ('instance_uuid', 'generation', 'network_id', 'policy_sha256')}
        result = ns['setup_session'](self.SESSION, request, sessions)
        self.assertEqual(result['error'], 'configure-failed')
        self.assertEqual(result['cleanup']['state'], 'cleanup-incomplete')
        self.assertTrue(ns['load_grant'](self.SESSION)['cleanup_pending'])
        self.assertIsNone(sessions[self.SESSION]['tap_fd'])
        with self.assertRaises(OSError):
            os.fstat(fd)
        self.present = False
        self.assertEqual(ns['teardown_session'](self.SESSION, sessions)['state'], 'session-closed')

    def test_setup_requires_persistent_record_before_network_mutation(self):
        ns = self.ns
        os.unlink(Path(ns['STATE_ROOT']) / (self.SESSION + '.json'))
        ns['save_cleanup_grant'] = lambda _: (_ for _ in ()).throw(OSError('disk-full'))
        ns['run'] = lambda _: self.fail('授权记录未持久化前不改网络')
        request = dict(ProductionControlChainTests().binding(), prefix=24)
        request['binding'] = {key: request[key] for key in
                              ('instance_uuid', 'generation', 'network_id', 'policy_sha256')}
        sessions = {}
        self.assertEqual(ns['setup_session'](self.SESSION, request, sessions),
                         {'error': 'grant-write-failed'})
        self.assertEqual(sessions, {})

    def test_query_command_failure_and_malformed_output_remain_unknown(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        # 使用生成脚本真实查询函数，不把失败的ip查询当空网卡/空进程列表。
        probe_namespace = load_assistant()
        probe_namespace['command_path'] = lambda _: '/usr/sbin/ip'
        probe = probe_namespace['namespace_resources']
        for value in ['{}', '[{}]', 'not-json']:
            with patch('subprocess.run', return_value=SimpleNamespace(stdout=value)):
                self.assertIsNone(probe('ctflab-test'))
        with patch('subprocess.run', side_effect=FileNotFoundError()):
            self.assertIsNone(probe('ctflab-test'))
        with patch('subprocess.run', side_effect=[SimpleNamespace(stdout='[{"ifname":"lo"}]'),
                                                 SimpleNamespace(stdout='123\n456\n')]):
            self.assertEqual(probe('ctflab-test'), ({'lo'}, ['123', '456']))

    def test_status_exposes_pending_without_claiming_fd_alive(self):
        self.teardown()
        result = self.ns['handle_daemon']({'action': 'status'}, 123, 123, self.sessions, None)
        self.assertTrue(result['sessions'][0]['cleanup_pending'])
        self.assertFalse(result['sessions'][0]['tap_fd_alive'])


    def test_setup_never_overwrites_malformed_existing_grant(self):
        path = Path(self.ns['STATE_ROOT']) / (self.SESSION + '.json')
        original = b'{damaged-grant-evidence'
        path.write_bytes(original)
        request = dict(ProductionControlChainTests().binding(), prefix=24)
        self.assertEqual(self.ns['setup_session'](self.SESSION, request, {}),
                         {'error': 'session-exists'})
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.commands, [])

    def test_network_command_permission_failure_is_failure(self):
        from unittest.mock import patch
        with patch('subprocess.run', side_effect=PermissionError('denied')):
            self.assertEqual(load_assistant()['run'](['ip', 'netns', 'del', 'test']), 1)


class ProductionCombinationTests(unittest.TestCase):
    """生产组合：并发多会话隔离、重启+过期租约、断流后清理的组合行为。

    全部函数级合成：网络设备以/dev/null替代，daemon桩返回0；不冒充真实内核。
    """

    def setUp(self):
        self.ns = load_assistant()
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.ns['STATE_ROOT'] = root.name
        self.open_fds = []
        self.addCleanup(self.close_all_fds)

    def close_all_fds(self):
        for fd in self.open_fds:
            try:
                os.close(fd)
            except OSError:
                pass

    def session_grant(self, session, *, expired=False):
        return {'session': session, 'netns': self.ns['netns_name'](session),
                'tap': self.ns['tap_name'](session), 'mac': '02:aa:bb:cc:dd:ee',
                'address': '192.168.242.66', 'prefix': 24, 'mtu': 1400,
                'expires': '2000-01-01T00:00:00Z' if expired else
                           time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() + 3600))}

    def dynamic_namespace(self, names, *, fail_delete=False):
        """动态桩：ip netns del 同步更新presence；撤网失败注入按需开启。"""
        ns = self.ns
        ns['namespace_present'] = lambda name: name in names
        ns['namespace_resources'] = lambda _: ({'lo'}, [])

        def run(argv):
            if argv[:3] == ['ip', 'netns', 'del']:
                if fail_delete:
                    return 1
                names.discard(argv[3])
            return 0
        ns['run'] = run

    def test_concurrent_sessions_sweep_and_teardown_isolation(self):
        ns = self.ns
        live_a, live_b, stale = ('aaaaaaaa-2222-3333-4444-555555555555',
                                 'bbbbbbbb-2222-3333-4444-555555555555',
                                 'cccccccc-2222-3333-4444-555555555555')
        fds = {}
        for name in (live_a, live_b, stale):
            fd = os.open('/dev/null', os.O_RDONLY)
            self.open_fds.append(fd)
            fds[name] = fd
        sessions = {name: {'grant': self.session_grant(name, expired=(name == stale)),
                           'tap_fd': fd} for name, fd in fds.items()}
        self.dynamic_namespace({ns['netns_name'](name)
                                for name in (live_a, live_b, stale)})
        ns['sweep_expired'](sessions)
        self.assertEqual(sorted(sessions), sorted([live_a, live_b]))
        os.fstat(fds[live_a]); os.fstat(fds[live_b])  # 并发会话不受过期清理波及
        with self.assertRaises(OSError):
            os.fstat(fds[stale])  # 过期会话生命周期FD已关闭
        # 一条会话撤网失败不得影响另一条的门禁与status可见性。
        self.dynamic_namespace({ns['netns_name'](name) for name in (live_a, live_b)},
                               fail_delete=True)
        result = ns['teardown_session'](live_a, sessions)
        self.assertEqual(result['state'], 'cleanup-incomplete')
        self.assertIn(live_a, sessions)
        ns['self_digest'] = lambda: 'a' * 64
        ns['read_machine_uuid'] = lambda: live_b
        verify = ns['handle_daemon']({'action': 'verify', 'session': live_b},
                                     123, 123, sessions, None)
        self.assertTrue(verify['ok'])
        status = ns['handle_daemon']({'action': 'status', 'session': ''},
                                     123, 123, sessions, None)
        reported = {item['session'] for item in status['sessions']}
        self.assertEqual(reported, {live_a, live_b})
        flags = sorted(item['cleanup_pending'] for item in status['sessions'])
        self.assertEqual(flags, [False, True])

    def test_restart_with_expired_lease_sweeps_to_clean_state(self):
        ns = self.ns
        session = 'dddddddd-2222-3333-4444-555555555555'
        grant = self.session_grant(session, expired=True)
        ns['save_cleanup_grant'](grant)
        restored = ns['restore_cleanup_sessions']()
        self.assertIn(session, restored)
        self.assertIsNone(restored[session]['tap_fd'])
        self.assertTrue(restored[session]['grant']['cleanup_pending'])
        self.dynamic_namespace({grant['netns']})
        ns['sweep_expired'](restored)
        self.assertEqual(restored, {})
        self.assertIsNone(ns['load_grant'](session))  # 磁盘授权一并清除
        # 重启后的记录无论租约如何都只能撤网，不能恢复帧连接。
        ns['save_cleanup_grant'](self.session_grant(session))
        restored = ns['restore_cleanup_sessions']()
        reply = ns['handle_daemon']({'action': 'attach', 'session': session},
                                    123, 123, restored, None)
        self.assertEqual(reply, {'error': 'cleanup-pending'})

    def test_mid_frame_stream_loss_then_teardown_completes(self):
        from types import SimpleNamespace
        ns = self.ns
        session = 'eeeeeeee-2222-3333-4444-555555555555'
        grant = self.session_grant(session)
        client_fd = os.open('/dev/null', os.O_RDONLY)
        daemon_fd = os.open('/dev/null', os.O_RDONLY)
        self.open_fds.extend([client_fd, daemon_fd])
        # 声明64字节载荷只到达5字节：断流立即退出且不写半条记录；
        # pump退出关闭client侧FD副本，daemon生命周期FD独立保留。
        stdin = io.BytesIO(struct.pack('!BIH', ns['RECORD_FRAME'], 1, 64) + b'short')
        stdout = io.BytesIO()
        ns['sys'] = SimpleNamespace(stdout=SimpleNamespace(buffer=stdout))
        ns['select'] = SimpleNamespace(select=lambda *args: ([stdin], [], []))
        ns['pump_frames'](grant, client_fd, stdin)
        self.assertEqual(stdout.getvalue(), b'')
        with self.assertRaises(OSError):
            os.fstat(client_fd)
        self.dynamic_namespace({grant['netns']})
        sessions = {session: {'grant': grant, 'tap_fd': daemon_fd}}
        result = ns['teardown_session'](session, sessions)
        self.assertEqual(result['state'], 'session-closed')
        self.assertEqual(result['leftover'], [])
        self.assertNotIn(session, sessions)
        with self.assertRaises(OSError):
            os.fstat(daemon_fd)


if __name__ == '__main__':
    unittest.main()
