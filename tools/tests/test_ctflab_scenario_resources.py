"""合成准备/就绪故障；不执行网络服务或 VM。"""
import copy
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

from test_ctflab_scenario import candidate, CAPS, INSTANCE
import ctflab_scenario_resources as resources
from ctflab_scenario import ScenarioError


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'state'

    def prepare(self, **kwargs):
        return resources.prepare_network_resources(candidate(), INSTANCE, generation=1,
            state_root=self.root, host_routes=kwargs.pop('host_routes', []),
            available_capabilities=CAPS, **kwargs)

    def records(self, prepared):
        records = {}
        for key, spec in prepared.specs.items():
            config = spec['config']
            records[key] = dict(schema=1, instance_uuid=INSTANCE, network_id=key, generation=1,
                port=prepared.ports[key], endpoint=f'tcp://127.0.0.1:{prepared.ports[key]}',
                cidr=config.cidr, server_ip=config.server_ip, server_mac=config.server_mac,
                subnet_mask=str(config.subnet.netmask), broadcast=str(config.subnet.broadcast_address),
                pool=[config.pool_start, config.pool_end], registered_only=True,
                static_leases=spec['static_leases'], pid=123)
        return records

    def test_private_paths_ports_and_close(self):
        with self.prepare() as prepared:
            self.assertEqual(len(set(prepared.ports.values())), 2)
            for listener in prepared.listeners.values():
                self.assertFalse(listener.get_inheritable())
                with socket.socket() as competitor, self.assertRaises(OSError):
                    competitor.bind(listener.getsockname())
            for spec in prepared.specs.values():
                self.assertEqual(spec['state_path'].parent.stat().st_mode & 0o777, 0o700)
            records = self.records(prepared)
            self.assertEqual(resources.wait_network_ready(prepared, observe=records.get,
                owned_process=lambda *_: True, timeout=1), prepared.ports)
        prepared.close()
        self.assertTrue(all(sock.fileno() == -1 for sock in prepared.listeners.values()))
        self.assertTrue(self.root.exists())

    def test_routes_fail_before_writes(self):
        for routes in (None, ['invalid'], ['192.168.243.0/24'], ['192.168.0.0/16']):
            with self.subTest(routes=routes), self.assertRaises(ScenarioError):
                self.prepare(host_routes=routes)
        self.assertFalse(self.root.exists())
        with self.prepare(host_routes=['0.0.0.0/0', '10.0.0.0/8']):
            pass

    def test_lock_contention_and_second_listener_failure(self):
        with self.prepare(), self.assertRaises(BlockingIOError):
            self.prepare()
        real_socket = socket.socket
        first = real_socket()
        with mock.patch.object(resources.socket, 'socket', side_effect=[first, OSError('synthetic bind failure')]):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertEqual(first.fileno(), -1)
        with self.prepare():
            pass

    def test_permissions_symlink_and_existing_record(self):
        self.root.mkdir(mode=0o755)
        with self.assertRaises(ScenarioError):
            self.prepare()
        self.root.chmod(0o700)
        with self.prepare() as prepared:
            path = prepared.specs['outer']['state_path']
        path.write_text('preserved')
        with self.assertRaises(ScenarioError):
            self.prepare()
        self.assertEqual(path.read_text(), 'preserved')
        linked = Path(self.temp.name).resolve() / 'linked'
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ScenarioError):
            resources.prepare_network_resources(candidate(), INSTANCE, generation=2,
                state_root=linked, host_routes=[], available_capabilities=CAPS)

    def test_wrong_identity_configuration_and_process(self):
        with self.prepare() as prepared:
            original = self.records(prepared)
            changes = {'generation': 2, 'network_id': 'inner', 'instance_uuid': 'other',
                'port': 1000, 'endpoint': 'tcp://0.0.0.0:1000', 'registered_only': 1,
                'static_leases': {}, 'server_mac': '02:00:00:00:00:00',
                'pool': ['192.168.243.2', '192.168.243.3'], 'pid': True}
            for key, value in changes.items():
                records = copy.deepcopy(original)
                records['outer'][key] = value
                with self.subTest(key=key), self.assertRaises(ScenarioError):
                    resources.wait_network_ready(prepared, observe=records.get,
                        owned_process=lambda *_: True, timeout=1)
            with self.assertRaises(ScenarioError):
                resources.wait_network_ready(prepared, observe=original.get,
                    owned_process=lambda *_: False, timeout=1)
            self.assertFalse(prepared.closed)

    def test_partial_ready_timeout_preserves_resources(self):
        with self.prepare() as prepared:
            records = self.records(prepared)
            records['inner'] = None
            tick = [0.0]
            def pause(seconds):
                tick[0] += seconds
            with self.assertRaisesRegex(ScenarioError, '超时'):
                resources.wait_network_ready(prepared, observe=records.get,
                    owned_process=lambda *_: True, timeout=0.1,
                    clock=lambda: tick[0], pause=pause)
            self.assertFalse(prepared.closed)
            self.assertTrue(all(sock.fileno() >= 0 for sock in prepared.listeners.values()))
            records['inner'] = self.records(prepared)['inner']
            resources.wait_network_ready(prepared, observe=records.get,
                owned_process=lambda *_: True, timeout=1)

    def test_real_state_writer_without_service(self):
        from ctflab_network import DHCPServer
        with self.prepare() as prepared:
            records = {}
            for key, spec in prepared.specs.items():
                server = DHCPServer(port=prepared.ports[key], **spec)
                server.write_state()
                records[key] = json.loads(spec['state_path'].read_text())
            self.assertEqual(resources.wait_network_ready(prepared, observe=records.get,
                owned_process=lambda _key, pid: pid == os.getpid(), timeout=1), prepared.ports)
            for timeout in (float('nan'), float('inf'), True, 0):
                with self.subTest(timeout=timeout), self.assertRaises(ScenarioError):
                    resources.wait_network_ready(prepared, observe=records.get,
                        owned_process=lambda *_: True, timeout=timeout)


class ScenarioPreparationTests(unittest.TestCase):
    setUp = ResourceTests.setUp
    prepare = ResourceTests.prepare
    records = ResourceTests.records

    def setup_assets(self):
        import hashlib
        self.manifest = candidate()
        self.assets = {}
        for key, spec in self.manifest['assets'].items():
            path = Path(self.temp.name).resolve() / (key + '.qcow2')
            path.write_bytes(('synthetic-' + key).encode())
            spec['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assets[key] = path
        self.firmware = {'kali': {}}
        for role in ('code', 'vars'):
            path = Path(self.temp.name).resolve() / (role + '.fd')
            path.write_bytes(('synthetic-' + role).encode())
            self.firmware['kali'][role] = path
            self.firmware['kali'][role + '_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        socket_temp = tempfile.TemporaryDirectory(prefix='cs-', dir='/private/tmp' if Path('/private/tmp').exists() else '/tmp')
        self.addCleanup(socket_temp.cleanup)
        self.sockets = Path(socket_temp.name).resolve() / 's'
        self.calls = []

    def image_run(self, args, **kwargs):
        self.calls.append(args)
        path = Path(args[-1])
        if args[1] == 'create':
            path.write_text(args[-2])
            return mock.Mock(stdout='')
        if path.name == 'overlay.qcow2':
            info = {'format': 'qcow2', 'full-backing-filename': path.read_text(),
                    'backing-filename-format': 'qcow2'}
        else:
            info = {'format': 'qcow2'}
        return mock.Mock(stdout=json.dumps(info))

    def collect(self):
        return {'routes': [], 'observed_at': resources.time.monotonic()}

    def scenario_prepare(self, **changes):
        args = dict(generation=1, state_root=self.root, socket_root=self.sockets,
            assets=self.assets, firmware=self.firmware, qemu_img='/synthetic/qemu-img',
            collect_routes=self.collect, available_capabilities=CAPS, run=self.image_run)
        args.update(changes)
        return resources.prepare_scenario_resources(self.manifest, INSTANCE, **args)

    def test_assets_lock_handoff_and_independent_instance(self):
        self.setup_assets()
        before = {key: path.read_bytes() for key, path in self.assets.items()}
        with self.scenario_prepare() as prepared:
            self.assertEqual(set(prepared.nodes), set(self.manifest['nodes']))
            self.assertEqual(json.loads(prepared.binding_path.read_text()), prepared.bindings)
            self.assertEqual(prepared.binding_path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(BlockingIOError):
                resources._resource_lock(self.root / 'scenarios' / INSTANCE / 'scenario.lock')
            global_lock = resources._resource_lock(self.root / 'scenario-resources.lock')
            global_lock.close()
            with self.assertRaises(BlockingIOError):
                self.scenario_prepare(generation=2)
            self.assertEqual((prepared.nodes['kali'][0] / 'nvram.fd').read_bytes(),
                             self.firmware['kali']['vars'].read_bytes())
            other = '12345678-1234-4234-8234-123456789abd'
            with resources.prepare_network_resources(candidate(), other, generation=1,
                    state_root=self.root, host_routes=[], available_capabilities=CAPS):
                pass
        self.assertEqual(before, {key: path.read_bytes() for key, path in self.assets.items()})
        with self.assertRaisesRegex(ScenarioError, '禁止覆盖'):
            self.scenario_prepare()

    def test_hash_firmware_and_stale_route_before_writes(self):
        self.setup_assets()
        self.assets['kali'].write_bytes(b'wrong')
        with self.assertRaisesRegex(ScenarioError, 'SHA-256'):
            self.scenario_prepare()
        self.assertFalse(self.root.exists())
        self.setup_assets()
        self.firmware['kali']['vars_sha256'] = '0' * 64
        with self.assertRaisesRegex(ScenarioError, 'SHA-256'):
            self.scenario_prepare()
        self.assertFalse(self.root.exists())
        self.setup_assets()
        with self.assertRaisesRegex(ScenarioError, '过期'):
            self.scenario_prepare(collect_routes=lambda: {'routes': [], 'observed_at': 0})
        self.assertFalse(self.root.exists())

    def test_second_overlay_failure_preserves_first_and_releases_locks(self):
        self.setup_assets()
        creates = [0]
        def fail(args, **kwargs):
            if args[1] == 'create':
                creates[0] += 1
                if creates[0] == 2:
                    raise OSError('synthetic disk failure')
            return self.image_run(args, **kwargs)
        with self.assertRaises(OSError):
            self.scenario_prepare(run=fail)
        first = self.root / 'scenarios' / INSTANCE / 'generations/1/nodes/kali/overlay.qcow2'
        self.assertTrue(first.exists())
        for path in (self.root / 'scenario-resources.lock',
                     self.root / 'scenarios' / INSTANCE / 'scenario.lock'):
            with resources._resource_lock(path):
                pass
        with self.assertRaisesRegex(ScenarioError, '禁止覆盖'):
            self.scenario_prepare()

    def test_wrong_backing_low_space_and_route_changed(self):
        self.setup_assets()
        def wrong(args, **kwargs):
            result = self.image_run(args, **kwargs)
            if args[1] == 'info' and args[-1].endswith('overlay.qcow2'):
                result.stdout = json.dumps({'format': 'qcow2', 'full-backing-filename': '/wrong',
                                           'backing-filename-format': 'qcow2'})
            return result
        with self.assertRaisesRegex(ScenarioError, 'backing'):
            self.scenario_prepare(run=wrong)
        with mock.patch('shutil.disk_usage', return_value=mock.Mock(free=0)):
            with self.assertRaisesRegex(ScenarioError, '空间不足'):
                self.scenario_prepare(generation=2)
        # 前一故障的预约保留；路由故障使用另一独立测试状态根。
        self.root = self.root.with_name('route-state')
        calls = [0]
        def changed():
            calls[0] += 1
            return {'routes': [] if calls[0] == 1 else ['192.168.243.0/24'],
                    'observed_at': resources.time.monotonic()}
        with self.assertRaisesRegex(ScenarioError, '路由冲突'):
            self.scenario_prepare(generation=3, collect_routes=changed)

    def test_owned_process_and_fresh_observer(self):
        with self.prepare() as prepared:
            bindings = resources.OwnedNetworkProcesses(prepared)
            records = self.records(prepared)
            for key, spec in prepared.specs.items():
                process = mock.Mock(pid=123, args=['network', key])
                process.poll.return_value = None
                bindings.bind(key, process, expected_args=['network', key])
                spec['state_path'].write_text(json.dumps(records[key]))
            resources.wait_network_ready(prepared, observe=bindings.observe,
                owned_process=bindings.owned, timeout=1)
            process.poll.return_value = 0
            self.assertFalse(bindings.owned(key, 123))
            process.poll.return_value = None
            process.args = ['other']
            self.assertFalse(bindings.owned(key, 123))
            self.assertFalse(bindings.owned('unknown', 123))
            with self.assertRaises(ScenarioError):
                bindings.bind(key, process, expected_args=['network', key])
            spec['state_path'].write_text('{broken')
            with self.assertRaisesRegex(ScenarioError, '损坏'):
                bindings.observe(key)
            spec['state_path'].unlink()  # 仅移除本测试自己创建的夹具。
            spec['state_path'].symlink_to(self.root / 'absent')
            with self.assertRaises(OSError):
                bindings.observe(key)


class RouteCollectorTests(unittest.TestCase):
    def test_macos_short_routes_and_unknown_table(self):
        text = 'Routing tables\n\nInternet:\nDestination Gateway Flags Netif Expire\n'
        text += 'default 1.2.3.4 UG en0\n192.168.0/23 link#1 UCS en0\n128.0/1 1.2.3.4 UG utun4\n127 127.0.0.1 UCS lo0\n127.0.0.1 127.0.0.1 UH lo0\n'
        self.assertEqual(resources.parse_macos_routes(text), ['0.0.0.0/0', '192.168.0.0/23',
            '128.0.0.0/1', '127.0.0.0/8', '127.0.0.1/32'])
        run = mock.Mock(return_value=mock.Mock(stdout=text))
        result = resources.collect_macos_routes(run=run, clock=lambda: 3)
        self.assertEqual(result['observed_at'], 3)
        for bad in ('', 'Internet:\n', text + 'unknown link#1 U en0\n', text + '999/2 link#1 U en0\n'):
            with self.subTest(bad=bad), self.assertRaises(ScenarioError):
                resources.parse_macos_routes(bad)

    def test_route_freshness_future_bool_and_slow_snapshot(self):
        for observed in (False, -1, 2, float('nan')):
            with self.subTest(observed=observed), self.assertRaises(ScenarioError):
                resources.fresh_routes(lambda: {'routes': [], 'observed_at': observed}, clock=lambda: 1)
        times = iter([1, 5])
        with self.assertRaises(ScenarioError):
            resources.fresh_routes(lambda: {'routes': [], 'observed_at': 1}, clock=lambda: next(times))


class RealImagePreparationTests(unittest.TestCase):
    setUp = ResourceTests.setUp
    setup_assets = ScenarioPreparationTests.setup_assets
    image_run = ScenarioPreparationTests.image_run
    collect = ScenarioPreparationTests.collect
    scenario_prepare = ScenarioPreparationTests.scenario_prepare

    def test_real_qemu_img_synthetic_disks_without_vm(self):
        import hashlib
        import shutil
        import subprocess
        tool = shutil.which('qemu-img')
        if tool is None:
            self.skipTest('没有 qemu-img；真实派生格式验证未运行')
        self.setup_assets()
        # 合成 RAW 夹具另建独立 QCOW2；不访问真实镜像库。
        for key, old in self.assets.items():
            path = old.with_name(key + '-real.qcow2')
            subprocess.run([tool, 'create', '-f', 'qcow2', str(path), '1M'],
                           capture_output=True, check=True, timeout=10)
            path.chmod(0o400)
            self.assets[key] = path
            self.manifest['assets'][key]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.scenario_prepare(qemu_img=tool, run=None) as prepared:
            for key, (runtime, _) in prepared.nodes.items():
                result = subprocess.run([tool, 'check', '--output=json', str(runtime / 'overlay.qcow2')],
                                        capture_output=True, text=True, check=True, timeout=10)
                self.assertEqual(json.loads(result.stdout).get('check-errors', 0), 0)
                self.assertEqual(self.assets[key].stat().st_mode & 0o777, 0o400)
