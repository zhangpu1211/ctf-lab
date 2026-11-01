"""合成资源登记、服务生命周期及恢复；没有 VM/网络服务子进程。"""
import copy
import json
from pathlib import Path
import unittest
from unittest import mock

from test_ctflab_scenario import CAPS, INSTANCE
import test_ctflab_scenario_resources as fixtures
from ctflab_scenario import ScenarioError
import ctflab_scenario_resources as resources
import ctflab_scenario_registry as registry
import ctflab_scenario_services as services

OTHER = '12345678-1234-4234-8234-123456789abd'


class SyntheticProcess:
    def __init__(self, args, pid):
        self.args, self.pid = args, pid
        self.alive, self.exit_on_terminate = True, True
        self.start_identity = f'synthetic-start-{pid}'
        self.terminate_count = 0

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.terminate_count += 1
        if self.exit_on_terminate:
            self.alive = False


class ScenarioServiceTests(unittest.TestCase):
    setUp = fixtures.ResourceTests.setUp
    setup_assets = fixtures.ScenarioPreparationTests.setup_assets
    image_run = fixtures.ScenarioPreparationTests.image_run
    collect = fixtures.ScenarioPreparationTests.collect
    scenario_prepare = fixtures.ScenarioPreparationTests.scenario_prepare
    records = fixtures.ResourceTests.records

    def prepare(self):
        self.setup_assets()
        prepared = self.scenario_prepare()
        self.addCleanup(prepared.close)
        return prepared

    def session(self, prepared, *, missing=(), fail=None):
        self.spawned = {}
        def spawn(args, *, pass_fds, close_fds):
            from ctflab_network import parse_args
            parsed = parse_args(args[2:])
            self.assertEqual(pass_fds, (prepared.listeners[parsed.network_id].fileno(),))
            self.assertTrue(close_fds)
            self.assertFalse(prepared.listeners[parsed.network_id].get_inheritable())
            if parsed.network_id == fail:
                raise OSError('synthetic spawn failure')
            process = SyntheticProcess(args, 101 + len(self.spawned))
            self.spawned[parsed.network_id] = process
            if parsed.network_id not in missing:
                record = self.records(prepared)[parsed.network_id]
                record['pid'] = process.pid
                parsed.state.write_text(json.dumps(record))
            return process
        return services.NetworkServiceSession(prepared, spawn=spawn,
            identity=lambda process: process.start_identity,
            python_binary='/synthetic/python', service_script='/synthetic/ctflab_network.py')

    def recover(self, prepared, inspect):
        return services.recover_network_services(self.root, INSTANCE, generation=1,
            available_capabilities=CAPS, inspect=inspect)

    def evidence(self, prepared):
        return {'instance_uuid': INSTANCE, 'generation': 1, 'token': prepared.reservation_token,
                'nodes': {key: 'stopped' for key in ('kali', 'straylight', 'neuromancer')},
                'networks': {key: 'stopped' for key in ('outer', 'inner')}}

    def test_registry_all_macs_persist_and_explicit_release(self):
        prepared = self.prepare()
        active = registry.active_reservations(self.root)
        reservation = active[prepared.reservation_token]
        self.assertEqual(len(reservation['macs']), 6)  # 四个 NIC + 两个 DHCP server。
        self.assertEqual(reservation['ports'], sorted(prepared.ports.values()))
        prepared.close()
        self.assertIn(prepared.reservation_token, registry.active_reservations(self.root))
        with self.assertRaisesRegex(ScenarioError, '未释放'):
            self.scenario_prepare(generation=2)
        wrong = self.evidence(prepared)
        wrong['networks']['inner'] = 'unknown'
        with self.assertRaisesRegex(ScenarioError, '全部停止'):
            registry.release_reservation(self.root, prepared.reservation_token, observe_stopped=lambda _: wrong)
        registry.release_reservation(self.root, prepared.reservation_token,
                                     observe_stopped=lambda _: self.evidence(prepared))
        self.assertFalse(registry.active_reservations(self.root))
        with self.assertRaisesRegex(ScenarioError, '已经释放'):
            registry.release_reservation(self.root, prepared.reservation_token, observe_stopped=lambda _: {})
        self.assertEqual([event['action'] for event in registry.read_events(self.root / 'scenario-reservations.jsonl')],
                         ['reserve', 'release'])

    def test_cross_instance_collision_and_independent_preparation(self):
        self.setup_assets()
        # 显式 MAC 可跨 UUID 重复，必须由全局登记阻止。
        self.manifest['nodes']['kali']['interfaces'][0]['mac'] = '02:11:22:33:44:55'
        with self.scenario_prepare() as prepared:
            def other(manifest):
                return resources.prepare_scenario_resources(manifest, OTHER, generation=1,
                    state_root=self.root, socket_root=self.sockets, assets=self.assets,
                    firmware=self.firmware, qemu_img='/synthetic/qemu-img', collect_routes=self.collect,
                    available_capabilities=CAPS, run=self.image_run)
            with self.assertRaisesRegex(ScenarioError, 'macs.*冲突'):
                other(self.manifest)
            changed = copy.deepcopy(self.manifest)
            changed['nodes']['kali']['interfaces'][0]['mac'] = 'derived'
            with other(changed):
                self.assertEqual(len(registry.active_reservations(self.root)), 2)
            with self.assertRaises(BlockingIOError):
                registry.release_reservation(self.root, prepared.reservation_token,
                                             observe_stopped=lambda _: self.evidence(prepared))

    def test_registry_corrupt_tail_and_symlink_fail_closed(self):
        prepared = self.prepare()
        prepared.close()
        path = self.root / 'scenario-reservations.jsonl'
        with path.open('a') as target:
            target.write('{partial')
        before = path.read_bytes()
        with self.assertRaisesRegex(ScenarioError, '不完整'):
            self.scenario_prepare(generation=2)
        self.assertEqual(path.read_bytes(), before)
        linked = self.root / 'linked.jsonl'
        linked.symlink_to(path)
        with self.assertRaises(ScenarioError):
            registry.read_events(linked)

    def test_service_ready_stop_and_read_only_recovery(self):
        prepared = self.prepare()
        session = self.session(prepared)
        self.assertEqual(session.start(timeout=1), prepared.ports)
        self.assertEqual(session.state, 'networks-ready')
        report = self.recover(prepared, lambda _key, expected: dict(expected, status='live'))
        self.assertEqual(report['state'], 'networks-observed')
        with self.assertRaises(ScenarioError):
            session.start(timeout=1)
        with self.assertRaisesRegex(ScenarioError, '节点'):
            session.stop(nodes_stopped=lambda: False, timeout=1)
        self.assertTrue(session.stop(nodes_stopped=lambda: True, timeout=1))
        self.assertEqual(session.state, 'stopped')
        self.assertEqual(self.recover(prepared, lambda *_: {'status': 'absent'})['state'], 'stopped-observed')
        self.assertTrue(all(process.terminate_count == 1 for process in self.spawned.values()))
        self.assertIn(prepared.reservation_token, registry.active_reservations(self.root))

    def test_second_spawn_failure_preserves_first_and_unknown_window(self):
        prepared = self.prepare()
        session = self.session(prepared, fail='inner')
        with self.assertRaises(OSError):
            session.start(timeout=1)
        self.assertEqual(session.state, 'degraded')
        self.assertTrue(self.spawned['outer'].alive)
        self.assertFalse(prepared.closed)
        with self.assertRaisesRegex(ScenarioError, '启动窗口'):
            session.stop(nodes_stopped=lambda: True, timeout=1)
        report = self.recover(prepared, lambda _key, expected: dict(expected, status='live'))
        self.assertEqual(report['state'], 'recovery-required')
        self.assertEqual(report['unknown'], ['inner'])
        self.assertEqual(self.spawned['outer'].terminate_count, 0)

    def test_partial_ready_timeout_and_stop_timeout_retry(self):
        prepared = self.prepare()
        session = self.session(prepared, missing=('inner',))
        tick = [0.0]
        def pause(seconds):
            tick[0] += seconds
        with self.assertRaisesRegex(ScenarioError, '超时'):
            session.start(timeout=0.1, clock=lambda: tick[0], pause=pause)
        self.assertEqual(session.state, 'degraded')
        self.spawned['inner'].exit_on_terminate = False
        self.assertFalse(session.stop(nodes_stopped=lambda: True, timeout=0.1,
                                      clock=lambda: tick[0], pause=pause))
        self.assertEqual(session.state, 'stop-pending')
        self.assertFalse(prepared.closed)
        self.assertTrue(self.spawned['inner'].alive)
        self.spawned['inner'].alive = False
        self.assertTrue(session.stop(nodes_stopped=lambda: True, timeout=0.1,
                                     clock=lambda: tick[0], pause=pause))
        self.assertEqual(self.spawned['inner'].terminate_count, 1)

    def test_recovery_pid_reuse_and_mutated_binding(self):
        prepared = self.prepare()
        session = self.session(prepared)
        session.start(timeout=1)
        def reused(key, expected):
            return dict(expected, status='live', start_identity='other-start') if key == 'inner' else dict(expected, status='live')
        before = session.journal.read_bytes()
        self.assertEqual(self.recover(prepared, reused)['state'], 'recovery-required')
        self.assertEqual(session.journal.read_bytes(), before)
        binding = json.loads(prepared.binding_path.read_text())
        binding['assets']['kali']['sha256'] = '0' * 64
        prepared.binding_path.write_text(json.dumps(binding))
        with self.assertRaisesRegex(ScenarioError, '资产绑定|日志绑定'):
            self.recover(prepared, lambda *_: {'status': 'absent'})

    def test_identity_change_and_journal_failure_never_signal(self):
        prepared = self.prepare()
        session = self.session(prepared)
        session.start(timeout=1)
        self.spawned['inner'].start_identity = 'changed'
        with self.assertRaisesRegex(ScenarioError, '归属变化'):
            session.stop(nodes_stopped=lambda: True, timeout=1)
        self.assertTrue(all(process.terminate_count == 0 for process in self.spawned.values()))
        self.spawned['inner'].start_identity = 'synthetic-start-102'
        with mock.patch.object(services, 'append_event', side_effect=OSError('synthetic fsync failure')):
            with self.assertRaises(OSError):
                session.stop(nodes_stopped=lambda: True, timeout=1)
        self.assertTrue(all(process.terminate_count == 0 for process in self.spawned.values()))

    def test_network_exit_degrades_without_restart(self):
        prepared = self.prepare()
        session = self.session(prepared)
        session.start(timeout=1)
        self.assertTrue(session.check_health())
        self.spawned['inner'].alive = False
        self.assertFalse(session.check_health())
        self.assertEqual(session.state, 'degraded')
        self.assertEqual(len(self.spawned), 2)
        self.assertTrue(all(process.terminate_count == 0 for process in self.spawned.values()))
        with self.assertRaises(ScenarioError):
            session.start(timeout=1)

    def test_spawn_journal_window_failure_and_total_deadline(self):
        prepared = self.prepare()
        session = self.session(prepared)
        real_append = services.append_event
        def fail_spawn_result(path, event):
            if event['processes']:
                raise OSError('synthetic result journal failure')
            return real_append(path, event)
        with mock.patch.object(services, 'append_event', side_effect=fail_spawn_result):
            with self.assertRaises(OSError):
                session.start(timeout=1)
        self.assertEqual(session.state, 'recovery-required')
        self.assertTrue(self.spawned['outer'].alive)
        report = self.recover(prepared, lambda *_: {'status': 'absent'})
        self.assertEqual(report['state'], 'recovery-required')
        self.assertEqual(report['unknown'], ['outer'])
        self.assertEqual(self.spawned['outer'].terminate_count, 0)

    def test_recovery_observation_changed_and_incomplete_journal(self):
        prepared = self.prepare()
        session = self.session(prepared)
        session.start(timeout=1)
        def changing(_key, expected):
            last = registry.read_events(session.journal)[-1]
            last.pop('sequence')
            registry.append_event(session.journal, last)
            return dict(expected, status='live')
        with self.assertRaisesRegex(ScenarioError, '观察期间'):
            self.recover(prepared, changing)
        with session.journal.open('a') as target:
            target.write('{half-written')
        with self.assertRaisesRegex(ScenarioError, '不完整'):
            self.recover(prepared, lambda *_: {'status': 'absent'})
        self.assertTrue(all(process.terminate_count == 0 for process in self.spawned.values()))

    def test_registry_write_failure_before_overlay_and_preserved_reservation(self):
        self.setup_assets()
        with mock.patch.object(registry.os, 'fsync', side_effect=OSError('synthetic registry fsync failure')):
            with self.assertRaises(OSError):
                self.scenario_prepare()
        self.assertFalse(any(args[1] == 'create' for args in self.calls))
        # 完整行可能已经写入但 fsync 未确认：保留且阻止同实例再次准备。
        self.assertEqual(len(registry.active_reservations(self.root)), 1)
        with self.assertRaisesRegex(ScenarioError, '未释放'):
            self.scenario_prepare()

    def test_release_observer_failure_preserves_history_and_locks(self):
        prepared = self.prepare()
        prepared.close()
        path = self.root / 'scenario-reservations.jsonl'
        before = path.read_bytes()
        def failed(_reservation):
            raise OSError('synthetic stopped inspection failure')
        with self.assertRaises(OSError):
            registry.release_reservation(self.root, prepared.reservation_token, observe_stopped=failed)
        self.assertEqual(before, path.read_bytes())
        for lock in (self.root / 'scenario-resources.lock', self.root / 'scenarios' / INSTANCE / 'scenario.lock'):
            with resources._resource_lock(lock):
                pass

    def test_recovery_wrong_resource_path_and_generation(self):
        prepared = self.prepare()
        session = self.session(prepared)
        session.start(timeout=1)
        binding = copy.deepcopy(prepared.bindings)
        binding['nodes']['kali']['runtime'] = '/other/runtime'
        prepared.binding_path.write_text(json.dumps(binding))
        with self.assertRaisesRegex(ScenarioError, '路径绑定'):
            self.recover(prepared, lambda *_: {'status': 'absent'})
        with self.assertRaises(ScenarioError):
            services.recover_network_services(self.root, INSTANCE, generation=True,
                available_capabilities=CAPS, inspect=lambda *_: {'status': 'absent'})

    def test_total_start_deadline_does_not_spawn_second_service(self):
        prepared = self.prepare()
        session = self.session(prepared)
        tick = [0.0]
        original = session.spawn
        def slow_spawn(*args, **kwargs):
            result = original(*args, **kwargs)
            tick[0] = 2
            return result
        session.spawn = slow_spawn
        with self.assertRaisesRegex(ScenarioError, '截止时间'):
            session.start(timeout=1, clock=lambda: tick[0], pause=lambda _: None)
        self.assertEqual(set(self.spawned), {'outer'})
        self.assertTrue(self.spawned['outer'].alive)
        self.assertEqual(session.state, 'degraded')

    def test_legacy_unregistered_scene_requires_recovery(self):
        self.setup_assets()
        legacy = self.root / 'scenarios' / OTHER / 'generations/1'
        resources._private_tree(self.root, legacy)
        (legacy / 'prepared.json').write_text('{}')
        before = (legacy / 'prepared.json').read_bytes()
        with self.assertRaisesRegex(ScenarioError, '未登记的历史'):
            self.scenario_prepare()
        self.assertEqual((legacy / 'prepared.json').read_bytes(), before)
        self.assertFalse((self.root / 'scenario-reservations.jsonl').exists())
        self.assertFalse(any(args[1] == 'create' for args in self.calls))
