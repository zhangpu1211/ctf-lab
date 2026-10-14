"""节点与重置事务合成故障验证；无真实 VM、用户实例或用户资产操作。"""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest import mock

from test_ctflab_scenario import CAPS, INSTANCE
import test_ctflab_scenario_services as fixtures
import ctflab_scenario_nodes as nodes
import ctflab_scenario_reset as reset
import ctflab_scenario_registry as registry
import ctflab_scenario_resources as resources
from ctflab_scenario import ScenarioError


class NodeResetTests(unittest.TestCase):
    setUp = fixtures.ScenarioServiceTests.setUp
    setup_assets = fixtures.ScenarioServiceTests.setup_assets
    image_run = fixtures.ScenarioServiceTests.image_run
    collect = fixtures.ScenarioServiceTests.collect
    scenario_prepare = fixtures.ScenarioServiceTests.scenario_prepare
    records = fixtures.ScenarioServiceTests.records
    prepare = fixtures.ScenarioServiceTests.prepare
    session = fixtures.ScenarioServiceTests.session

    def node_session(self, *, fail=None, missing=None, wrong=None):
        prepared = self.prepare()
        networks = self.session(prepared)
        networks.start(timeout=1)
        self.node_processes, self.start_order, self.stop_order = {}, [], []
        def spawn(args, *, close_fds):
            self.assertTrue(close_fds)
            key = next(key for key in prepared.bindings['nodes'] if f'-{key}-g1' in args[args.index('-name') + 1])
            self.start_order.append(key)
            if key == fail:
                raise OSError('synthetic node spawn failure')
            process = fixtures.SyntheticProcess(args, 201 + len(self.node_processes))
            self.node_processes[key] = process
            return process
        def observe(key, process, expected):
            if key == missing:
                return None
            record = dict(expected, instance_uuid=INSTANCE, generation=1, node_id=key,
                qmp_ready=True, overlay=str(Path(prepared.bindings['nodes'][key]['runtime']) / 'overlay.qcow2'),
                qmp=str(Path(prepared.bindings['nodes'][key]['sockets']) / 'qmp.sock'))
            if key == wrong:
                record['overlay'] = '/other/disk.qcow2'
            return record
        def powerdown(key, process, expected):
            self.stop_order.append(key)
            self.assertEqual(expected['pid'], process.pid)
            if process.exit_on_terminate:
                process.alive = False
        result = nodes.ScenarioNodeSession(networks, spawn=spawn, identity=lambda process: process.start_identity,
            observe=observe, powerdown=powerdown,
            qemu_binaries={'aarch64': '/synthetic/qemu-arm', 'x86_64': '/synthetic/qemu-x86'},
            available_capabilities=CAPS)
        self.addCleanup(result.close)
        return prepared, networks, result

    def stopped(self, binding):
        return {'instance_uuid': binding['instance_uuid'], 'generation': binding['generation'],
            'nodes': {key: 'stopped' for key in ('kali', 'straylight', 'neuromancer')},
            'networks': {key: 'stopped' for key in ('outer', 'inner')}}

    def initialize(self):
        prepared = self.prepare()
        prepared.close()
        pointer = reset.initialize_active_generation(self.root, INSTANCE, generation=1,
            available_capabilities=CAPS, observe_stopped=self.stopped)
        self.scene = self.root / 'scenarios' / INSTANCE
        return prepared, pointer

    def do_reset(self, **changes):
        args = dict(new_generation=2, available_capabilities=CAPS, observe_stopped=self.stopped,
                    qemu_img='/synthetic/qemu-img', run=self.image_run)
        args.update(changes)
        return reset.reset_scenario_assets(self.root, INSTANCE, **args)

    def audit(self):
        return reset.audit_reset(self.root, INSTANCE, available_capabilities=CAPS)

    def test_node_order_ready_stop_then_networks(self):
        prepared, networks, session = self.node_session()
        self.assertTrue(session.start(timeout=1))
        self.assertEqual(self.start_order, ['neuromancer', 'straylight', 'kali'])
        self.assertEqual(session.state, 'nodes-ready')
        self.assertTrue(session.check_health())
        self.assertTrue(session.stop(timeout_per_node=1))
        self.assertEqual(self.stop_order, ['kali', 'straylight', 'neuromancer'])
        self.assertTrue(session.nodes_stopped())
        self.assertTrue(networks.stop(nodes_stopped=session.nodes_stopped, timeout=1))
        self.assertTrue(all(process.terminate_count == 0 for process in self.node_processes.values()))
        self.assertIn(prepared.reservation_token, registry.active_reservations(self.root))
        with self.assertRaises(ScenarioError):
            session.start(timeout=1)

    def test_partial_node_spawn_failure_preserves_networks_and_window(self):
        _prepared, networks, session = self.node_session(fail='straylight')
        with self.assertRaises(OSError):
            session.start(timeout=1)
        self.assertEqual(self.start_order, ['neuromancer', 'straylight'])
        self.assertTrue(self.node_processes['neuromancer'].alive)
        self.assertEqual(session.pending, ['straylight'])
        with self.assertRaisesRegex(ScenarioError, '不明节点'):
            session.stop(timeout_per_node=1)
        self.assertEqual(networks.state, 'networks-ready')
        self.assertTrue(all(process.terminate_count == 0 for process in self.spawned.values()))

    def test_qmp_wrong_binding_and_existing_journal_gate(self):
        _prepared, _networks, session = self.node_session(wrong='neuromancer')
        with self.assertRaisesRegex(ScenarioError, 'QMP'):
            session.start(timeout=1)
        self.assertEqual(self.start_order, ['neuromancer'])
        self.assertEqual(session.state, 'degraded')
        # 缺 QMP 就绪证据与错盘绑定分开验证，不启动其它节点。
        with self.assertRaises(ScenarioError):
            nodes.ScenarioNodeSession(session.networks, spawn=session.spawn, identity=session.identity,
                observe=session.observe, powerdown=session.powerdown, qemu_binaries=session.qemu_binaries,
                available_capabilities=CAPS)

    def test_node_shutdown_timeout_preserves_later_nodes_and_retry(self):
        _prepared, networks, session = self.node_session()
        session.start(timeout=1)
        self.node_processes['kali'].exit_on_terminate = False
        tick = [0.0]
        def pause(seconds):
            tick[0] += seconds
        self.assertFalse(session.stop(timeout_per_node=0.1, clock=lambda: tick[0], pause=pause))
        self.assertEqual(session.state, 'stop-pending')
        self.assertEqual(self.stop_order, ['kali'])
        self.assertTrue(self.node_processes['straylight'].alive)
        self.assertFalse(session.nodes_stopped())
        with self.assertRaises(ScenarioError):
            networks.stop(nodes_stopped=session.nodes_stopped, timeout=1)
        self.node_processes['kali'].alive = False
        self.assertTrue(session.stop(timeout_per_node=0.1, clock=lambda: tick[0], pause=pause))
        self.assertEqual(self.stop_order, ['kali', 'straylight', 'neuromancer'])

    def test_node_identity_change_and_journal_failure_no_powerdown(self):
        _prepared, _networks, session = self.node_session()
        session.start(timeout=1)
        self.node_processes['kali'].start_identity = 'reused'
        with self.assertRaisesRegex(ScenarioError, '归属变化'):
            session.stop(timeout_per_node=1)
        self.assertFalse(self.stop_order)
        self.node_processes['kali'].start_identity = 'synthetic-start-203'
        with mock.patch.object(nodes, 'append_event', side_effect=OSError('synthetic journal failure')):
            with self.assertRaises(OSError):
                session.stop(timeout_per_node=1)
        self.assertFalse(self.stop_order)
        self.assertEqual(session.state, 'recovery-required')

    def test_node_exit_degrades_without_restart(self):
        _prepared, _networks, session = self.node_session()
        session.start(timeout=1)
        self.node_processes['straylight'].alive = False
        self.assertFalse(session.check_health())
        self.assertEqual(session.state, 'degraded')
        self.assertEqual(len(self.start_order), 3)

    def test_reset_preserves_old_and_switches_single_pointer(self):
        prepared, old = self.initialize()
        previous = {key: (Path(spec['runtime']) / 'overlay.qcow2').read_bytes()
                    for key, spec in prepared.bindings['nodes'].items()}
        result = self.do_reset()
        self.assertEqual(result['generation'], 2)
        self.assertEqual(self.audit(), {'state': 'committed-observed', 'generation': 2})
        descriptor = json.loads((self.scene / 'generations/2/reset-ready.json').read_text())
        self.assertEqual(descriptor['manifest'], prepared.bindings['manifest'])
        self.assertEqual(descriptor['status'], 'reset-assets-ready')
        self.assertNotIn('network_ports', descriptor)
        for key in descriptor['nodes']:
            new = Path(descriptor['nodes'][key]['runtime'])
            self.assertTrue((new / 'overlay.qcow2').exists())
            self.assertEqual((Path(prepared.bindings['nodes'][key]['runtime']) / 'overlay.qcow2').read_bytes(), previous[key])
        self.assertEqual((self.scene / 'generations/2/nodes/kali/nvram.fd').read_bytes(),
                         self.firmware['kali']['vars'].read_bytes())
        self.assertFalse(list((self.scene / 'generations/2/networks').rglob('network.json')))
        self.assertIn(prepared.reservation_token, registry.active_reservations(self.root))
        with self.assertRaises(ScenarioError):
            self.do_reset()
        self.assertEqual(old['generation'], 1)

    def test_reset_stop_proof_and_scene_lock_gate_before_writes(self):
        prepared, _ = self.initialize()
        bad = self.stopped(prepared.bindings)
        bad['nodes']['kali'] = 'unknown'
        with self.assertRaisesRegex(ScenarioError, '未证明停止'):
            self.do_reset(observe_stopped=lambda _: bad)
        self.assertFalse((self.scene / 'reset-lifecycle.jsonl').exists())
        with resources._resource_lock(self.scene / 'scenario.lock'):
            with self.assertRaises(BlockingIOError):
                self.do_reset()
        self.assertEqual(self.audit()['generation'], 1)

    def test_second_disk_failure_old_active_preserved(self):
        self.initialize()
        creates = [0]
        def failed(args, **kwargs):
            if args[1] == 'create':
                creates[0] += 1
                if creates[0] == 2:
                    raise OSError('synthetic second overlay failure')
            return self.image_run(args, **kwargs)
        with self.assertRaises(OSError):
            self.do_reset(run=failed)
        self.assertEqual(self.audit(), {'state': 'old-active-preserved', 'generation': 1})
        self.assertTrue((self.scene / 'generations/2/nodes/kali/overlay.qcow2').exists())
        with self.assertRaisesRegex(ScenarioError, '未收口'):
            self.do_reset(new_generation=3)

    def test_pointer_replace_failure_preserves_candidate(self):
        self.initialize()
        def failed_replace(*_):
            raise OSError('synthetic atomic replacement failure')
        with self.assertRaises(OSError):
            self.do_reset(replace=failed_replace)
        self.assertEqual(self.audit()['state'], 'old-active-preserved')
        self.assertTrue((self.scene / 'generations/2/reset-ready.json').exists())

    def test_commit_journal_failure_pointer_is_authoritative(self):
        self.initialize()
        real_append = reset.append_event
        def failed(path, event):
            if event['state'] == 'committed':
                raise OSError('synthetic post-commit fsync failure')
            return real_append(path, event)
        with mock.patch.object(reset, 'append_event', side_effect=failed):
            with self.assertRaises(OSError):
                self.do_reset()
        self.assertEqual(self.audit(), {'state': 'committed-observed', 'generation': 2})
        self.assertTrue((self.scene / 'generations/1/prepared.json').exists())

    def test_reset_hash_and_space_gate(self):
        self.initialize()
        self.assets['kali'].write_bytes(b'changed source')
        with self.assertRaisesRegex(ScenarioError, 'SHA-256'):
            self.do_reset()
        self.assertFalse((self.scene / 'generations/2').exists())
        self.assertEqual(self.audit()['state'], 'old-active-preserved')

    def test_reset_source_changes_before_commit_proof(self):
        prepared, _ = self.initialize()
        calls = [0]
        def changed(binding):
            calls[0] += 1
            evidence = self.stopped(binding)
            if calls[0] > 1:
                evidence['networks']['inner'] = 'live'
            return evidence
        with self.assertRaisesRegex(ScenarioError, '未证明停止'):
            self.do_reset(observe_stopped=changed)
        self.assertEqual(self.audit()['state'], 'old-active-preserved')
        self.assertEqual(len(registry.active_reservations(self.root)), 1)

    def test_existing_target_generation_is_preserved(self):
        self.initialize()
        target = resources._private_tree(self.scene, self.scene / 'generations/2')
        (target / 'preserved.txt').write_text('preserved synthetic fixture')
        with self.assertRaisesRegex(ScenarioError, '已有现场'):
            self.do_reset()
        self.assertEqual((target / 'preserved.txt').read_text(), 'preserved synthetic fixture')
        self.assertEqual(self.audit()['generation'], 1)

    def test_missing_qmp_times_out_without_starting_later_nodes(self):
        _prepared, networks, session = self.node_session(missing='neuromancer')
        tick = [0.0]
        def pause(seconds):
            tick[0] += seconds
        with self.assertRaisesRegex(ScenarioError, '超时'):
            session.start(timeout=0.1, clock=lambda: tick[0], pause=pause)
        self.assertEqual(self.start_order, ['neuromancer'])
        self.assertTrue(self.node_processes['neuromancer'].alive)
        self.assertEqual(networks.state, 'networks-ready')

    def test_node_recovery_pid_reuse_and_pending_spawn(self):
        prepared, _networks, session = self.node_session(fail='straylight')
        with self.assertRaises(OSError):
            session.start(timeout=1)
        before = session.journal.read_bytes()
        report = nodes.recover_scenario_nodes(prepared, inspect=lambda _key, expected: dict(expected, status='live'))
        self.assertEqual(report['state'], 'recovery-required')
        self.assertEqual(report['unknown'], ['straylight'])
        self.assertEqual(session.journal.read_bytes(), before)

    def test_node_ready_recovery_requires_same_start_identity(self):
        prepared, _networks, session = self.node_session()
        session.start(timeout=1)
        inspect = lambda _key, expected: dict(expected, status='live')
        self.assertEqual(nodes.recover_scenario_nodes(prepared, inspect=inspect)['state'], 'nodes-observed')
        inspect = lambda _key, expected: dict(expected, status='live', start_identity='other-start')
        self.assertEqual(nodes.recover_scenario_nodes(prepared, inspect=inspect)['state'], 'recovery-required')

    def test_post_commit_recovery_records_commit_without_changing_pointer(self):
        self.initialize()
        real_append = reset.append_event
        def failed(path, event):
            if event['state'] == 'committed':
                raise OSError('synthetic post-commit failure')
            return real_append(path, event)
        with mock.patch.object(reset, 'append_event', side_effect=failed):
            with self.assertRaises(OSError):
                self.do_reset()
        before = (self.scene / 'active-generation.json').read_bytes()
        report = reset.recover_reset_transaction(self.root, INSTANCE, available_capabilities=CAPS,
                                                observe_stopped=self.stopped)
        self.assertEqual(report['transaction'], 'committed')
        self.assertEqual((self.scene / 'active-generation.json').read_bytes(), before)
        self.do_reset(new_generation=3)
        self.assertEqual(self.audit()['generation'], 3)

    def test_failed_reset_explicit_abort_allows_new_target_and_keeps_partial(self):
        self.initialize()
        def failed(args, **kwargs):
            if args[1] == 'create':
                raise OSError('synthetic overlay failure')
            return self.image_run(args, **kwargs)
        with self.assertRaises(OSError):
            self.do_reset(run=failed)
        report = reset.recover_reset_transaction(self.root, INSTANCE, available_capabilities=CAPS,
                                                observe_stopped=self.stopped)
        self.assertEqual(report['transaction'], 'aborted')
        self.assertTrue((self.scene / 'generations/2/nodes/kali').exists())
        self.do_reset(new_generation=3)
        self.assertEqual(self.audit()['generation'], 3)
        self.assertTrue((self.scene / 'generations/2').exists())

    def test_corrupt_reset_disk_inventory_rejects_audit(self):
        self.initialize()
        self.do_reset()
        disk = self.scene / 'generations/2/nodes/straylight/overlay.qcow2'
        disk.write_bytes(b'corrupt synthetic overlay')
        with self.assertRaisesRegex(ScenarioError, 'SHA-256'):
            self.audit()

    def test_reset_low_space_and_wrong_backing_preserve_pointer(self):
        self.initialize()
        with mock.patch('shutil.disk_usage', return_value=mock.Mock(free=0)):
            with self.assertRaisesRegex(ScenarioError, '空间不足'):
                self.do_reset()
        self.assertFalse((self.scene / 'generations/2').exists())
        reset.recover_reset_transaction(self.root, INSTANCE, available_capabilities=CAPS, observe_stopped=self.stopped)
        def wrong(args, **kwargs):
            result = self.image_run(args, **kwargs)
            if args[1] == 'info' and args[-1].endswith('overlay.qcow2'):
                result.stdout = json.dumps({'format': 'qcow2', 'full-backing-filename': '/other/base',
                                           'backing-filename-format': 'qcow2'})
            return result
        with self.assertRaisesRegex(ScenarioError, 'backing'):
            self.do_reset(new_generation=3, run=wrong)
        self.assertEqual(self.audit()['generation'], 1)

    def test_real_qemu_img_reset_without_vm(self):
        import shutil
        import subprocess
        tool = shutil.which('qemu-img')
        if tool is None:
            self.skipTest('没有 qemu-img；真实派生盘重置验证未运行')
        self.setup_assets()
        for key, old in self.assets.items():
            path = old.with_name(key + '-real.qcow2')
            subprocess.run([tool, 'create', '-f', 'qcow2', str(path), '1M'], capture_output=True, check=True, timeout=10)
            path.chmod(0o400)
            self.assets[key] = path
            self.manifest['assets'][key]['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        prepared = self.scenario_prepare(qemu_img=tool, run=None)
        prepared.close()
        self.scene = self.root / 'scenarios' / INSTANCE
        reset.initialize_active_generation(self.root, INSTANCE, generation=1,
            available_capabilities=CAPS, observe_stopped=self.stopped)
        result = self.do_reset(qemu_img=tool, run=None)
        self.assertEqual(result['generation'], 2)
        self.assertEqual(self.audit()['state'], 'committed-observed')
        for key, path in self.assets.items():
            self.assertEqual(path.stat().st_mode & 0o777, 0o400)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), self.manifest['assets'][key]['sha256'])

    def test_reset_active_generation_rejects_stale_network_preparation(self):
        self.initialize()
        self.do_reset()
        with self.assertRaisesRegex(ScenarioError, '活动代次'):
            self.scenario_prepare(generation=1)
        with self.assertRaisesRegex(ScenarioError, '待接续'):
            self.scenario_prepare(generation=2)
        self.assertEqual(self.audit()['generation'], 2)
