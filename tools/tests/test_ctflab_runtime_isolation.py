"""独立状态的真实交换机竞争及长 UNIX socket 路径验证。"""
import concurrent.futures
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab

class RuntimeIsolationTests(unittest.TestCase):
    def test_two_states_bind_distinct_live_ports_without_check_bind_race(self):
        with tempfile.TemporaryDirectory() as root:
            managers = [ctflab.LabManager(Path(root) / str(i)) for i in range(2)]
            states = []
            try:
                with mock.patch.object(ctflab, 'available_profiles', return_value=[]):
                    with concurrent.futures.ThreadPoolExecutor(2) as pool:
                        states = list(pool.map(lambda m: m.ensure_network([], 23400), managers))
                self.assertNotEqual(states[0]['port'], states[1]['port'])
                for m, state in zip(managers, states):
                    self.assertEqual(m.network_state(state['port'])['pid'], state['pid'])
                    with socket.create_connection(('127.0.0.1', state['port']), timeout=2):
                        pass
                managers[0].stop_network(states[0]['port'])
                self.assertTrue(ctflab.bool_pid_alive(states[1]['pid']))
            finally:
                for m in managers:
                    for port in m.network_ports():
                        m.stop_network(port)
            for state in states:
                self.assertFalse(ctflab.bool_pid_alive(state['pid']))

    def test_occupied_external_listener_is_preserved(self):
        with tempfile.TemporaryDirectory() as root, socket.socket() as external:
            external.bind(('127.0.0.1', 0)); external.listen()
            occupied = external.getsockname()[1]
            m = ctflab.LabManager(Path(root))
            try:
                with mock.patch.object(ctflab, 'available_profiles', return_value=[]):
                    state = m.ensure_network([], occupied)
                self.assertNotEqual(state['port'], occupied)
                with socket.create_connection(('127.0.0.1', occupied), timeout=2):
                    pass
            finally:
                for port in m.network_ports(): m.stop_network(port)

    def test_long_paths_bind_and_are_distinct_for_different_states(self):
        with tempfile.TemporaryDirectory() as root:
            paths = []
            for suffix in ['a', 'b']:
                m = ctflab.LabManager(Path(root) / ('long-' * 30) / suffix)
                p = m._qmp_socket('sample')
                self.assertLess(len(os.fsencode(p)), 100)
                self.assertEqual(p.parent.stat().st_mode & 0o777, 0o700)
                with socket.socket(socket.AF_UNIX) as sock:
                    sock.bind(str(p))
                    self.assertTrue(p.is_socket())
                p.unlink(); paths.append(p)
            self.assertNotEqual(*paths)

    def test_short_paths_preserve_existing_layout(self):
        with tempfile.TemporaryDirectory() as root:
            m = ctflab.LabManager(Path(root))
            self.assertEqual(m._qmp_socket('a'), m.runtime_dir / 'a/qmp.sock')

    def test_long_spice_endpoint_lookup_preserves_live_listener(self):
        with tempfile.TemporaryDirectory() as root:
            m = ctflab.LabManager(Path(root) / ('long-' * 25))
            endpoint = m._spice_socket('kali-arm64')
            self.assertLess(len(os.fsencode(endpoint)), 100)
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(endpoint)); server.listen()
                # 状态登记/等待/重连查找必须复用该路径，并且不删除已监听端点。
                for _ in range(3):
                    self.assertEqual(m._spice_endpoint_path('kali-arm64'), endpoint)
                    with socket.socket(socket.AF_UNIX) as client:
                        client.connect(str(m._spice_endpoint_path('kali-arm64')))
                        connection, _ = server.accept(); connection.close()
            endpoint.unlink()

    def test_reconnect_uses_recorded_long_path_endpoint_without_restarting_vm(self):
        with tempfile.TemporaryDirectory() as root:
            m = ctflab.LabManager(Path(root) / ('long-' * 25))
            endpoint = m._spice_socket('kali-arm64')
            state = {'pid': 123, 'spice_client_pid': 456, 'display_backend': 'spice',
                     'spice_endpoint': str(endpoint), 'clipboard_enabled': False,
                     'file_transfer_enabled': False, 'overlay_path': 'unchanged'}
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(endpoint)); server.listen()
                with mock.patch.object(m, 'runtime_state', return_value=state), mock.patch.object(ctflab, 'bool_pid_alive', side_effect=lambda pid: pid == 123), mock.patch.object(ctflab, 'spice_client_path', return_value='/test/spicy'), mock.patch.object(ctflab.subprocess, 'Popen', return_value=mock.Mock(pid=789)) as spawn, mock.patch.object(ctflab, 'track_background_process'):
                    result = m.show_display('kali-arm64', reconnect=True)
                self.assertEqual(result['pid'], 789)
                self.assertEqual(state['pid'], 123)
                self.assertEqual(state['overlay_path'], 'unchanged')
                self.assertIn('spice+unix://' + str(endpoint), spawn.call_args.args[0])
                self.assertNotIn('--clipboard', spawn.call_args.args[0])
                self.assertNotIn('--file-transfer', spawn.call_args.args[0])
                self.assertTrue(endpoint.is_socket())
            endpoint.unlink()
