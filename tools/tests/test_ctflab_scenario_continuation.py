"""重置接续链合成验证：旧预约释放、新代次预约、服务/节点接续与中断恢复。

只使用自身临时状态根、合成基盘/固件、FD 与合成进程对象；没有真实 VM、
网络服务子进程或用户实例/资产操作。
"""
import json
from pathlib import Path
import unittest
from unittest import mock

from test_ctflab_scenario import CAPS, INSTANCE
import test_ctflab_scenario_services as fixtures
import test_ctflab_scenario_nodes_reset as node_fixtures
import ctflab_scenario_registry as registry
import ctflab_scenario_reset as reset
import ctflab_scenario_resources as resources
import ctflab_scenario_services as services
import ctflab_scenario_nodes as nodes
from ctflab_scenario import ScenarioError


class ResetContinuationTests(unittest.TestCase):
    setUp = fixtures.ScenarioServiceTests.setUp
    setup_assets = fixtures.ScenarioServiceTests.setup_assets
    image_run = fixtures.ScenarioServiceTests.image_run
    collect = fixtures.ScenarioServiceTests.collect
    scenario_prepare = fixtures.ScenarioServiceTests.scenario_prepare
    prepare = fixtures.ScenarioServiceTests.prepare
    records = fixtures.ScenarioServiceTests.records
    stopped = node_fixtures.NodeResetTests.stopped

    def records(self, prepared):
        records = fixtures.ScenarioServiceTests.records(self, prepared)
        for key, spec in prepared.specs.items():
            records[key]['generation'] = spec['generation']
        return records

    def initialize_and_reset(self):
        prepared = self.prepare()
        self.old_ports = sorted(prepared.ports.values())
        prepared.close()
        self.scene = self.root / 'scenarios' / INSTANCE
        reset.initialize_active_generation(self.root, INSTANCE, generation=1,
            available_capabilities=CAPS, observe_stopped=self.stopped)
        reset.reset_scenario_assets(self.root, INSTANCE, new_generation=2, available_capabilities=CAPS,
            observe_stopped=self.stopped, qemu_img='/synthetic/qemu-img', run=self.image_run)
        return prepared

    def resume(self, **changes):
        args = dict(available_capabilities=CAPS, observe_stopped=self.stopped,
                    collect_routes=self.collect, socket_root=self.sockets)
        args.update(changes)
        return reset.resume_reset_resources(self.root, INSTANCE, **args)

    def session(self, prepared, *, fail=None):
        self.spawned = {}
        def spawn(args, *, pass_fds, close_fds):
            from ctflab_network import parse_args
            parsed = parse_args(args[2:])
            self.assertEqual(pass_fds, (prepared.listeners[parsed.network_id].fileno(),))
            if parsed.network_id == fail:
                raise OSError('synthetic spawn failure')
            process = fixtures.SyntheticProcess(args, 301 + len(self.spawned))
            self.spawned[parsed.network_id] = process
            record = self.records(prepared)[parsed.network_id]
            record['pid'] = process.pid
            parsed.state.write_text(json.dumps(record))
            return process
        return services.NetworkServiceSession(prepared, spawn=spawn,
            identity=lambda process: process.start_identity,
            python_binary='/synthetic/python', service_script='/synthetic/ctflab_network.py')

    def node_session(self, networks, prepared):
        self.node_processes = {}
        def spawn(args, *, close_fds):
            self.assertTrue(close_fds)
            key = next(key for key in prepared.bindings['nodes'] if f'-{key}-g2' in args[args.index('-name') + 1])
            process = fixtures.SyntheticProcess(args, 401 + len(self.node_processes))
            self.node_processes[key] = process
            return process
        def observe(key, process, expected):
            return dict(expected, instance_uuid=INSTANCE, generation=2, node_id=key,
                qmp_ready=True, overlay=str(Path(prepared.bindings['nodes'][key]['runtime']) / 'overlay.qcow2'),
                qmp=str(Path(prepared.bindings['nodes'][key]['sockets']) / 'qmp.sock'))
        return nodes.ScenarioNodeSession(networks, spawn=spawn,
            identity=lambda process: process.start_identity, observe=observe,
            powerdown=lambda key, process, expected: setattr(process, 'alive', False),
            qemu_binaries={'aarch64': '/synthetic/qemu-arm', 'x86_64': '/synthetic/qemu-x86'},
            available_capabilities=CAPS)

    def active_for(self, generation):
        return [token for token, item in registry.active_reservations(self.root).items()
                if item['instance_uuid'] == INSTANCE and item['generation'] == generation]

    def test_resume_connects_reset_assets_to_full_runtime_chain(self):
        self.initialize_and_reset()
        old_ports = self.old_ports
        resumed = self.resume()
        self.addCleanup(resumed.close)
        bindings = resumed.bindings
        self.assertEqual(bindings['generation'], 2)
        self.assertEqual(bindings['status'], 'assets-prepared')
        self.assertNotEqual(sorted(bindings['network_ports'].values()), old_ports)
        pointer = json.loads((self.scene / 'active-generation.json').read_text())
        self.assertEqual(pointer['descriptor'], 'prepared.json')
        self.assertEqual(pointer['binding_digest'], services._digest(bindings))
        # 重置提交后代次被接续：审计应识别为已提交，而非 recovery-required。
        self.assertEqual(reset.audit_reset(self.root, INSTANCE, available_capabilities=CAPS),
                         {'state': 'committed-observed', 'generation': 2})
        self.assertEqual(self.active_for(1), [])
        self.assertEqual(len(self.active_for(2)), 1)
        reservation = registry.active_reservations(self.root)[bindings['reservation_token']]
        self.assertEqual(len(reservation['macs']), 6)
        # 旧代次资产保留；新代次网络目录仍无运行记录。
        self.assertTrue((self.scene / 'generations/1/prepared.json').exists())
        self.assertFalse(list((self.scene / 'generations/2/networks').rglob('network.json')))
        # 接续对象直接进入既有服务/节点调用链。
        networks = self.session(resumed)
        self.assertEqual(networks.start(timeout=1), resumed.ports)
        session = self.node_session(networks, resumed)
        self.assertTrue(session.start(timeout=1))
        self.assertEqual(session.state, 'nodes-ready')
        self.assertTrue(session.stop(timeout_per_node=1))
        self.assertTrue(networks.stop(nodes_stopped=session.nodes_stopped, timeout=1))
        resumed.close()  # 结束持锁会话后才能释放预约。
        registry.release_reservation(self.root, bindings['reservation_token'],
                                     observe_stopped=lambda _: self.stopped(bindings))
        actions = [event['action'] for event in registry.read_events(self.root / 'scenario-reservations.jsonl')]
        self.assertEqual(actions, ['reserve', 'release', 'reserve', 'release'])
        with self.assertRaisesRegex(ScenarioError, '运行日志'):
            self.resume()

    def test_resume_rejected_when_reset_transaction_unclosed(self):
        prepared = self.prepare()
        prepared.close()
        self.scene = self.root / 'scenarios' / INSTANCE
        reset.initialize_active_generation(self.root, INSTANCE, generation=1,
            available_capabilities=CAPS, observe_stopped=self.stopped)
        real_append = reset.append_event
        def failed(path, event):
            if event['state'] == 'committed':
                raise OSError('synthetic post-commit failure')
            return real_append(path, event)
        with mock.patch.object(reset, 'append_event', side_effect=failed):
            with self.assertRaises(OSError):
                reset.reset_scenario_assets(self.root, INSTANCE, new_generation=2, available_capabilities=CAPS,
                    observe_stopped=self.stopped, qemu_img='/synthetic/qemu-img', run=self.image_run)
        with self.assertRaisesRegex(ScenarioError, '未收口'):
            self.resume()
        reset.recover_reset_transaction(self.root, INSTANCE, available_capabilities=CAPS,
                                        observe_stopped=self.stopped)
        resumed = self.resume()
        self.addCleanup(resumed.close)
        self.assertEqual(resumed.bindings['generation'], 2)

    def test_resume_requires_old_generation_stop_proof(self):
        prepared = self.initialize_and_reset()
        before = (self.scene / 'active-generation.json').read_bytes()
        bad = self.stopped(prepared.bindings)
        bad['nodes']['straylight'] = 'live'
        def observer(_binding):
            if _binding['generation'] == 1:
                return bad
            return self.stopped(_binding)
        with self.assertRaisesRegex(ScenarioError, '未证明停止'):
            self.resume(observe_stopped=observer)
        self.assertEqual((self.scene / 'active-generation.json').read_bytes(), before)
        self.assertEqual(len(self.active_for(1)), 1)
        self.assertEqual(self.active_for(2), [])

    def test_reserve_failure_after_release_recovers_on_retry(self):
        self.initialize_and_reset()
        real_append = registry.append_event
        def failed(path, event):
            if event.get('action') == 'reserve':
                raise OSError('synthetic reserve failure')
            return real_append(path, event)
        with mock.patch.object(registry, 'append_event', side_effect=failed):
            with self.assertRaises(OSError):
                self.resume()
        self.assertEqual(self.active_for(1), [])
        self.assertEqual(self.active_for(2), [])
        resumed = self.resume()
        self.addCleanup(resumed.close)
        self.assertEqual(len(self.active_for(2)), 1)
        self.assertEqual(json.loads((self.scene / 'active-generation.json').read_text())['generation'], 2)

    def test_pointer_switch_failure_leaves_orphan_for_explicit_recovery(self):
        self.initialize_and_reset()
        def failed_replace(*_args):
            raise OSError('synthetic pointer replace failure')
        with self.assertRaises(OSError):
            self.resume(replace=failed_replace)
        self.assertEqual(len(self.active_for(2)), 1)
        self.assertEqual(json.loads((self.scene / 'active-generation.json').read_text())['descriptor'],
                         'reset-ready.json')
        self.assertTrue((self.scene / 'generations/2/prepared.json').exists())
        # 孤儿预约存在时禁止重复接续；显式恢复后重试成功并替换失效准备记录。
        with self.assertRaisesRegex(ScenarioError, '未接续预约'):
            self.resume()
        report = reset.recover_reset_continuation(self.root, INSTANCE, available_capabilities=CAPS,
                                                  observe_stopped=self.stopped)
        self.assertEqual(report['state'], 'orphan-released')
        self.assertEqual(self.active_for(2), [])
        resumed = self.resume()
        self.addCleanup(resumed.close)
        binding = json.loads((self.scene / 'generations/2/prepared.json').read_text())
        self.assertEqual(binding['reservation_token'], resumed.bindings['reservation_token'])
        self.assertEqual(registry.active_reservations(self.root)[binding['reservation_token']]['ports'],
                         sorted(resumed.ports.values()))

    def test_activated_generation_rewires_after_pre_start_crash(self):
        first = self.resume_after_reset()
        stale_token = first.bindings['reservation_token']
        stale_ports = sorted(first.ports.values())
        # 模拟 CLI 在指针切换后、服务启动前退出：关闭对象释放 FD 与锁（进程死亡）。
        first.close()
        second = self.resume()
        self.addCleanup(second.close)
        self.assertNotEqual(second.bindings['reservation_token'], stale_token)
        self.assertNotEqual(sorted(second.ports.values()), stale_ports)
        pointer = json.loads((self.scene / 'active-generation.json').read_text())
        self.assertEqual(pointer['binding_digest'], services._digest(second.bindings))
        self.assertEqual(self.active_for(2), [second.bindings['reservation_token']])
        networks = self.session(second)
        self.assertEqual(networks.start(timeout=1), second.ports)

    def resume_after_reset(self):
        self.initialize_and_reset()
        resumed = self.resume()
        self.scene = self.root / 'scenarios' / INSTANCE
        return resumed

    def test_orphan_reserve_for_activated_pointer_recovers(self):
        first = self.resume_after_reset()
        keep_token = first.bindings['reservation_token']
        first.close()
        real_append = registry.append_event
        def failed(path, event):
            if event.get('action') == 'reserve':
                raise OSError('synthetic reserve failure after new token')
            return real_append(path, event)
        # 指针已指向 prepared 且旧 token 活跃：接续在重接预约前先释放并因故障中止。
        with mock.patch.object(registry, 'append_event', side_effect=failed):
            with self.assertRaises(OSError):
                self.resume()
        self.assertEqual(self.active_for(2), [])
        resumed = self.resume()
        self.addCleanup(resumed.close)
        self.assertNotEqual(resumed.bindings['reservation_token'], keep_token)

    def test_corrupt_inventory_blocks_resume_before_any_change(self):
        prepared = self.initialize_and_reset()
        disk = self.scene / 'generations/2/nodes/kali/overlay.qcow2'
        disk.write_bytes(b'corrupted synthetic overlay')
        before = (self.scene / 'active-generation.json').read_bytes()
        with self.assertRaisesRegex(ScenarioError, 'SHA-256'):
            self.resume()
        self.assertEqual((self.scene / 'active-generation.json').read_bytes(), before)
        self.assertEqual(len(self.active_for(1)), 1)
        self.assertEqual(self.active_for(2), [])

    def test_concurrent_operations_blocked_by_lock_order(self):
        self.initialize_and_reset()
        with resources._resource_lock(self.root / 'scenario-resources.lock'):
            with self.assertRaises(BlockingIOError):
                self.resume()
        with resources._resource_lock(self.scene / 'scenario.lock'):
            with self.assertRaises(BlockingIOError):
                self.resume()
        self.assertEqual(json.loads((self.scene / 'active-generation.json').read_text())['descriptor'],
                         'reset-ready.json')
        resumed = self.resume()
        self.addCleanup(resumed.close)

    def test_service_session_refuses_unactivated_prepared_record(self):
        prepared = self.initialize_and_reset()
        resumed = self.resume()
        self.addCleanup(resumed.close)
        # 模拟接续后指针被回退到 reset-ready：孤儿准备记录不得启动服务。
        pointer = json.loads((self.scene / 'active-generation.json').read_text())
        reset_descriptor = json.loads((self.scene / 'generations/2/reset-ready.json').read_text())
        reverted = {'schema': 1, 'instance_uuid': INSTANCE, 'generation': 2,
                    'descriptor': 'reset-ready.json',
                    'binding_digest': services._digest(reset_descriptor)}
        (self.scene / 'active-generation.json').write_text(json.dumps(reverted))
        with self.assertRaisesRegex(ScenarioError, '未接续激活'):
            self.session(resumed)
        self.assertEqual(pointer['descriptor'], 'prepared.json')

    def test_guest_writes_after_activation_are_not_asset_corruption(self):
        first = self.resume_after_reset()
        networks = self.session(first)
        networks.start(timeout=1)
        session = self.node_session(networks, first)
        session.start(timeout=1)
        self.assertTrue(session.stop(timeout_per_node=1))
        self.assertTrue(networks.stop(nodes_stopped=session.nodes_stopped, timeout=1))
        # 来宾合法写入改变运行盘内容：不得用停止态清单判定为损坏。
        disk = self.scene / 'generations/2/nodes/kali/overlay.qcow2'
        disk.write_bytes(b'guest wrote synthetic data')
        self.assertEqual(reset.audit_reset(self.root, INSTANCE, available_capabilities=CAPS)['generation'], 2)
        first.close()  # 结束持锁会话后才能释放预约。
        registry.release_reservation(self.root, first.bindings['reservation_token'],
                                     observe_stopped=lambda _: self.stopped(first.bindings))
        pointer = reset.reset_scenario_assets(self.root, INSTANCE, new_generation=3,
            available_capabilities=CAPS, observe_stopped=self.stopped,
            qemu_img='/synthetic/qemu-img', run=self.image_run)
        self.assertEqual(pointer['generation'], 3)
        resumed = self.resume()
        self.addCleanup(resumed.close)
        self.assertEqual(resumed.bindings['generation'], 3)

    def test_repeated_resume_after_services_started_requires_recovery(self):
        first = self.resume_after_reset()
        self.addCleanup(first.close)
        networks = self.session(first)
        networks.start(timeout=1)
        with self.assertRaisesRegex(ScenarioError, '运行日志'):
            self.resume()
        report = services.recover_network_services(self.root, INSTANCE, generation=2,
            available_capabilities=CAPS, inspect=lambda _key, expected: dict(expected, status='live'))
        self.assertEqual(report['state'], 'networks-observed')

    def test_recovery_no_orphan_and_not_pending_are_idempotent(self):
        self.initialize_and_reset()
        report = reset.recover_reset_continuation(self.root, INSTANCE, available_capabilities=CAPS,
                                                  observe_stopped=self.stopped)
        self.assertEqual(report, {'state': 'no-orphan', 'generation': 2})
        resumed = self.resume()
        self.addCleanup(resumed.close)
        self.assertEqual(len(self.active_for(2)), 1)
        resumed.close()  # 结束持锁会话后恢复入口才能取得场景锁。
        report = reset.recover_reset_continuation(self.root, INSTANCE, available_capabilities=CAPS,
                                                  observe_stopped=self.stopped)
        # 指针已激活且活跃预约正是当前准备记录：无孤儿可释放，也不属于待接续。
        self.assertEqual(report, {'state': 'no-orphan', 'generation': 2})


if __name__ == '__main__':
    unittest.main()
