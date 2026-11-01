"""真实临时文件/数据库验证；磁盘内容为合成字节，不启动来宾。"""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
import uuid
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError
from ctflab_generation_store import GenerationStore, digest
from ctflab_scenario_coordinator import ScenarioCoordinator, NodeObservation
from ctflab_local_service import LocalService, OperationContext
from test_ctflab_scenario_v2 import sample


class Driver:
    def __init__(self):
        self.states = {}
        self.calls = []
        self.fail = None
        self.identity = 'verified'
        self.timeout = False

    def observe(self, plan, node, paths):
        key = (plan['instance_uuid'], plan['generation'], node)
        return NodeObservation(*key, self.identity, self.states.get(key, 'stopped'))

    def start(self, plan, node, paths, params):
        self.calls.append(('start', node))
        if self.fail == node:
            raise OSError('合成启动失败')
        self.states[(plan['instance_uuid'], plan['generation'], node)] = 'process-running'

    def stop(self, plan, node, paths):
        self.calls.append(('stop', node))
        if not self.timeout:
            self.states[(plan['instance_uuid'], plan['generation'], node)] = 'stopped'


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.base = self.root / '基盘 source.bin'
        self.base.write_bytes(b'base-fixture' * 100)
        self.manifest = sample()
        self.manifest['assets']['linux']['sha256'] = digest(self.base)
        self.instance = str(uuid.uuid4())
        self.store = GenerationStore.create(self.root / '私有实例', self.manifest, self.instance, {'linux': self.base})
        self.driver = Driver()
        self.backend = ScenarioCoordinator(self.store, course_id='c01', baseline_id='base', driver=self.driver)

    def context(self, generation=1, cancelled=lambda: False):
        return OperationContext(self.instance, str(uuid.uuid4()), generation, cancelled)

    def run_action(self, action, generation=1, context=None):
        params = {'prepare': {'course_id': 'c01', 'baseline_id': 'base'}, 'reset': {'baseline_id': 'base'},
                  'start': {'display': 'headless', 'allow_emulation': False}, 'stop': {}, 'recover': {}}[action]
        return self.backend.execute({'operation': action, 'parameters': params}, context or self.context(generation))

    def test_prepare_reset_preserves_old_and_original(self):
        original = digest(self.base)
        self.assertEqual(self.run_action('prepare').state, 'prepared')
        disk = self.store.node_paths(1, 'server')['disk']
        disk.write_bytes(b'progress')
        self.assertEqual(self.run_action('reset').state, 'prepared')
        self.assertEqual(self.store.snapshot()['active_generation'], 2)
        self.assertEqual(disk.read_bytes(), b'progress')
        self.assertEqual(digest(self.store.node_paths(2, 'server')['disk']), original)
        self.assertEqual(digest(self.base), original)

    def test_start_stop_dag_and_repeated_operation(self):
        self.run_action('prepare')
        self.run_action('start')
        self.assertEqual(self.driver.calls, [('start', 'server'), ('start', 'middle'), ('start', 'client')])
        self.run_action('stop')
        self.assertEqual(self.driver.calls[-3:], [('stop', 'client'), ('stop', 'middle'), ('stop', 'server')])

    def test_partial_start_preserves_and_never_replays(self):
        self.run_action('prepare')
        self.driver.fail = 'middle'
        context = self.context()
        with self.assertRaises(OSError):
            self.run_action('start', context=context)
        self.assertEqual(self.backend.observe(context).state, 'recovery-required')
        before = list(self.driver.calls)
        with self.assertRaises(ContractError):
            self.run_action('start', context=context)
        self.assertEqual(self.driver.calls, before)
        self.assertEqual(self.run_action('recover').state, 'recovery-required')
        self.assertTrue(self.store.node_paths(1, 'server')['disk'].exists())
        self.assertEqual(self.run_action('stop').state, 'stopped')
        self.assertEqual(self.driver.calls[-1], ('stop', 'server'))

    def test_disk_space_failure_creates_no_generation(self):
        with mock.patch('ctflab_generation_store.shutil.disk_usage', return_value=type('Usage', (), {'free': 0})()):
            with self.assertRaises(ContractError):
                self.run_action('prepare')
        self.assertEqual(self.store.snapshot()['generations'], [])
        self.assertTrue(self.store.snapshot()['unresolved'])

    def test_two_instances_do_not_share_writable_disks(self):
        self.run_action('prepare')
        other = GenerationStore.create(self.root / 'other', self.manifest, str(uuid.uuid4()), {'linux': self.base})
        backend = ScenarioCoordinator(other, course_id='c01', baseline_id='base', driver=self.driver)
        context = OperationContext(other.config['instance_uuid'], str(uuid.uuid4()), 1, lambda: False)
        backend.execute({'operation': 'prepare', 'parameters': {'course_id': 'c01', 'baseline_id': 'base'}}, context)
        other.node_paths(1, 'server')['disk'].write_bytes(b'other-progress')
        self.assertEqual(digest(self.store.node_paths(1, 'server')['disk']), digest(self.base))

    def test_cancel_after_reset_commit_cannot_claim_cancelled(self):
        self.run_action('prepare')
        operation = str(uuid.uuid4())
        cancel = [False]
        with self.store.locked():
            self.store.begin(operation, 'reset', 1)
            result = self.store.prepare_generation(operation, 1, cancelled=lambda: cancel[0],
                checkpoint=lambda stage: cancel.__setitem__(0, True) if stage == 'after-commit' else None)
        self.assertEqual(result['state'], 'prepared')
        self.assertEqual(self.store.snapshot()['active_generation'], 2)

    def test_unknown_identity_and_running_reset_rejected(self):
        self.run_action('prepare')
        self.driver.identity = 'unknown'
        with self.assertRaises(ContractError):
            self.run_action('reset')
        self.driver.identity = 'verified'
        self.run_action('start')
        with self.assertRaises(ContractError):
            self.run_action('reset')
        self.assertEqual(self.store.snapshot()['active_generation'], 1)

    def test_stop_timeout_does_not_report_stopped(self):
        self.run_action('prepare')
        self.run_action('start')
        self.driver.timeout = True
        with self.assertRaises(ContractError):
            self.run_action('stop')
        self.assertTrue(self.store.snapshot()['unresolved'])

    def test_before_commit_failure_recovers_old_generation(self):
        self.run_action('prepare')
        operation = str(uuid.uuid4())
        def crash(stage):
            if stage == 'before-commit':
                raise RuntimeError('合成提交前中断')
        with self.store.locked():
            self.store.begin(operation, 'reset', 1)
            with self.assertRaises(RuntimeError):
                self.store.prepare_generation(operation, 1, checkpoint=crash)
        self.assertEqual(self.store.snapshot()['active_generation'], 1)
        self.assertEqual(self.run_action('recover').state, 'stopped')
        self.assertFalse(self.store.snapshot()['unresolved'])
        self.run_action('reset')
        self.assertEqual(self.store.snapshot()['active_generation'], 2)
        self.assertEqual(len(self.store.snapshot()['generations']), 3)

    def test_after_commit_failure_recovers_new_generation(self):
        self.run_action('prepare')
        operation = str(uuid.uuid4())
        def crash(stage):
            if stage == 'after-commit':
                raise RuntimeError('合成提交后中断')
        with self.store.locked():
            self.store.begin(operation, 'reset', 1)
            with self.assertRaises(RuntimeError):
                self.store.prepare_generation(operation, 1, checkpoint=crash)
        reopened = GenerationStore(self.store.root)
        self.assertEqual(reopened.snapshot()['active_generation'], 2)
        self.assertFalse(reopened.snapshot()['unresolved'])

    def test_abrupt_process_exit_releases_gate_but_keeps_intent(self):
        self.run_action('prepare')
        script = '''import os,sys,uuid
sys.path.insert(0,sys.argv[1])
from ctflab_generation_store import GenerationStore
store=GenerationStore(sys.argv[2])
with store.locked():
    operation=str(uuid.uuid4())
    store.begin(operation,'reset',1)
    store.prepare_generation(operation,1,checkpoint=lambda stage: os._exit(31) if stage=='before-commit' else None)
'''
        result = subprocess.run([sys.executable, '-B', '-c', script,
                                 str(Path(__file__).resolve().parents[1]), str(self.store.root)],
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 31, result.stderr.decode())
        reopened = GenerationStore(self.store.root)
        self.assertEqual(reopened.snapshot()['active_generation'], 1)
        self.assertTrue(reopened.snapshot()['unresolved'])
        with reopened.locked():
            pass
        self.assertEqual(self.run_action('recover').state, 'stopped')

    def test_contract_partial_start_can_explicitly_stop_verified_nodes(self):
        service = LocalService.create(self.root / 'partial-contract')
        generation, revision = None, None
        for action, params in [('prepare', {'course_id': 'c01', 'baseline_id': 'base'}),
                               ('start', {'display': 'headless', 'allow_emulation': False}), ('stop', {})]:
            if action == 'start':
                self.driver.fail = 'middle'
            req = {'protocol': 'ctflab-local', 'version': 1, 'request_id': str(uuid.uuid4()),
                   'instance_uuid': self.instance, 'operation': action, 'idempotency_key': action,
                   'expected_generation': generation, 'expected_state_revision': revision, 'parameters': params}
            accepted = service.submit(req, 'tester')
            result = service.execute(accepted['operation_id'], 'tester', self.backend)
            self.assertEqual(result['result'], 'failed' if action == 'start' else 'completed', result)
            generation, revision = result['generation'], result['state_revision']
        self.assertEqual(result['state'], 'stopped')
        self.assertEqual(self.driver.calls, [('start', 'server'), ('start', 'middle'), ('stop', 'server')])

    def test_cancel_preserves_and_retry_allocates_new_attempt(self):
        self.run_action('prepare')
        result = self.run_action('reset', context=self.context(cancelled=lambda: True))
        self.assertTrue(result.cancelled)
        self.assertEqual(self.store.snapshot()['active_generation'], 1)
        self.run_action('reset')
        self.assertEqual(self.store.snapshot()['active_generation'], 2)

    def test_source_mutation_and_private_path(self):
        self.base.write_bytes(b'changed')
        with self.assertRaises(ContractError):
            self.run_action('prepare')
        self.assertEqual(self.store.snapshot()['active_generation'], 0)
        with self.assertRaises(ContractError):
            self.store.guard(self.base)

    def test_concurrent_lock_rejects_and_releases(self):
        with self.store.locked():
            with self.assertRaises(ContractError):
                with GenerationStore(self.store.root).locked():
                    pass
        with self.store.locked():
            pass

    def test_uefi_disk_and_nvram_together(self):
        firmware = self.root / 'vars.fd'
        firmware.write_bytes(b'firmware-fixture')
        self.manifest['nodes']['server']['firmware'] = 'uefi'
        store = GenerationStore.create(self.root / 'uefi', self.manifest, str(uuid.uuid4()),
                                       {'linux': self.base}, {'server': firmware})
        operation = str(uuid.uuid4())
        with store.locked():
            store.begin(operation, 'prepare', 0)
            store.prepare_generation(operation, 0)
        self.assertEqual(store.node_paths(1, 'server')['nvram'].read_bytes(), firmware.read_bytes())
        self.assertFalse(store.snapshot()['deletion_available'])

    def test_missing_driver_fails_closed(self):
        self.run_action('prepare')
        self.backend.driver = None
        with self.assertRaises(ContractError):
            self.run_action('start')

    def test_local_service_end_to_end_and_idempotence(self):
        service = LocalService.create(self.root / 'contract')
        generation, revision = None, None
        for action, params in [('prepare', {'course_id': 'c01', 'baseline_id': 'base'}),
                               ('start', {'display': 'headless', 'allow_emulation': False}),
                               ('stop', {}), ('reset', {'baseline_id': 'base'})]:
            req = {'protocol': 'ctflab-local', 'version': 1, 'request_id': str(uuid.uuid4()),
                   'instance_uuid': self.instance, 'operation': action, 'idempotency_key': action,
                   'expected_generation': generation, 'expected_state_revision': revision, 'parameters': params}
            accepted = service.submit(req, 'tester')
            result = service.execute(accepted['operation_id'], 'tester', self.backend)
            self.assertEqual(result['result'], 'completed', result)
            calls = list(self.driver.calls)
            self.assertEqual(service.submit(req, 'tester'), result)
            self.assertEqual(self.driver.calls, calls)
            generation, revision = result['generation'], result['state_revision']
        self.assertEqual(generation, 2)


if __name__ == '__main__':
    unittest.main()
