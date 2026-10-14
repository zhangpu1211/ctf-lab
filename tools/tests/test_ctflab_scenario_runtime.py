"""生产采集与恢复接管合成验证：ps 注入、QMP 假 socket、接管停止故障。

只使用自身临时状态根、注入的 ps 采集器、合成 FD/进程身份；没有真实 VM、
真实 QMP、网络服务子进程或用户实例/资产操作。
"""
import hashlib
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
import ctflab_scenario_runtime as runtime
from ctflab_scenario import ScenarioError
from ctflab_scenario_services import _digest

LSTART = 'Tue Oct 14 10:00:00 2026'


def identity_for(command, *, start=LSTART):
    """与 process_start_identity 相同的摘要公式，供合成身份对齐。"""
    return hashlib.sha256((start + '\n' + ' '.join(command)).encode()).hexdigest()


def ps_output(stdout, *, fail=False):
    def run(_args, **_kwargs):
        if fail:
            import subprocess
            raise subprocess.SubprocessError('synthetic ps failure')
        return mock.Mock(stdout=stdout, returncode=0)
    return run


def ps_single(command, *, start=LSTART):
    """模拟 `ps -o command=` 的单行输出。"""
    return ps_output(f'{command}\n')


class IdentityTests(unittest.TestCase):
    def test_identity_binds_lstart_and_command(self):
        live = f'{LSTART}\n/synthetic/qemu -name demo\n'
        first = runtime.process_start_identity(4242, run=ps_output(live))
        second = runtime.process_start_identity(4242, run=ps_output(live))
        self.assertEqual(first, second)
        self.assertEqual(first, identity_for(['/synthetic/qemu', '-name', 'demo']))
        self.assertEqual(runtime.process_command(4242, run=ps_single('/synthetic/qemu -name demo')),
                         '/synthetic/qemu -name demo')
        reused = f'{LSTART}\n/synthetic/other\n'
        self.assertNotEqual(first, runtime.process_start_identity(4242, run=ps_output(reused)))
        for broken in (ps_output('', fail=True), ps_output('one-line\n'), ps_output('a\nb\nc\n')):
            with self.subTest(broken=broken):
                self.assertIsNone(runtime.process_start_identity(4242, run=broken))
        for broken_command in (ps_output('', fail=True), ps_output('a\nb\n')):
            with self.subTest(broken_command=broken_command):
                self.assertIsNone(runtime.process_command(4242, run=broken_command))
        with self.assertRaises(ScenarioError):
            runtime.process_start_identity('4242', run=ps_output(live))

    def test_build_inspect_reports_live_absent_unknown(self):
        argv = ['/synthetic/qemu', '-name', 'demo']
        expected = {'pid': 4242, 'argv': argv, 'start_identity': identity_for(argv)}
        live = ps_output(f'{LSTART}\n{" ".join(argv)}\n')
        inspect = runtime.build_inspect(run=live)
        self.assertEqual(inspect('kali', dict(expected)), dict(expected, status='live'))
        absent = runtime.build_inspect(run=ps_output('', fail=True))
        self.assertEqual(absent('kali', dict(expected)), {'status': 'absent'})
        reused = runtime.build_inspect(
            run=ps_output(f'{LSTART} +1s\n{" ".join(argv)}\n'))
        self.assertEqual(reused('kali', dict(expected)), {'status': 'unknown'})
        mutated = runtime.build_inspect(
            run=ps_output(f'{LSTART}\n/synthetic/qemu -name evil\n'))
        self.assertEqual(mutated('kali', dict(expected)), {'status': 'unknown'})

    def test_child_identity_requires_capture(self):
        class Process:
            pid = 4242

            def poll(self):
                return None
        live = ps_output(f'{LSTART}\ncmd\n')
        self.assertEqual(runtime.child_identity(Process(), run=live),
                         runtime.process_start_identity(4242, run=live))

    def test_child_identity_fails_closed_on_exit_or_instability(self):
        class Exited:
            pid = 4242

            def poll(self):
                return 0
        with self.assertRaisesRegex(ScenarioError, '已退出'):
            runtime.child_identity(Exited(), run=ps_output('', fail=True))

        class Alive:
            pid = 4242
            generation = [0]

            def poll(self):
                return None
        flips = [runtime.process_start_identity(4242, run=ps_output(f'{LSTART}\nfirst\n')),
                 runtime.process_start_identity(4242, run=ps_output(f'{LSTART}\nsecond\n'))]
        def unstable(_pid, *, run=None, hasher=hashlib.sha256):
            value = flips[Alive.generation[0] % 2]
            Alive.generation[0] += 1
            return value
        with mock.patch.object(runtime, 'process_start_identity', unstable), \
                mock.patch.object(runtime.time, 'sleep', lambda _s: None):
            with self.assertRaisesRegex(ScenarioError, '未稳定'):
                runtime.child_identity(Alive())


class FakeQMP:
    """脚本化 QMP 响应的假 socket；记录收到的命令。"""

    def __init__(self, stream):
        self.stream = stream.encode()
        self.received = []
        self.closed = False

    def sendall(self, data):
        self.received.append(data.decode().strip())

    def recv(self, _size):
        if not self.stream:
            return b''
        byte, self.stream = self.stream[:1], self.stream[1:]
        return byte

    def close(self):
        self.closed = True


def qmp_stream(final):
    return ('{"QMP": {"version": "synthetic"}}\n'
            '{"return": {}}\n'
            f'{final}\n')


RUNNING = '{"return": {"status": "running"}}\n'


class QMPTests(unittest.TestCase):
    def test_query_status_and_powerdown_success(self):
        client = FakeQMP(qmp_stream(RUNNING))
        status = runtime.qmp_query('/synthetic/qmp.sock', connect=lambda: client)
        self.assertEqual(status, {'status': 'running'})
        self.assertEqual(client.received, ['{"execute": "qmp_capabilities"}',
                                           '{"execute": "query-status"}'])
        client = FakeQMP(qmp_stream('{"return": {}}\n'))
        self.assertTrue(runtime.qmp_powerdown('/synthetic/qmp.sock', connect=lambda: client))
        self.assertEqual(client.received[-1], '{"execute": "system_powerdown"}')
        self.assertTrue(client.closed)

    def test_qmp_failures_return_none_or_false(self):
        def broken():
            raise OSError('synthetic connect refusal')
        self.assertIsNone(runtime.qmp_query('/synthetic/qmp.sock', connect=broken))
        self.assertFalse(runtime.qmp_powerdown('/synthetic/qmp.sock', connect=broken))
        for stream in ('garbage\n', '{"return": {}}\n{"error": {"desc": "x"}}\n',
                       '{"QMP": {}}\n{"return": {}}\n{"return": {}}\n'):
            with self.subTest(stream=stream):
                self.assertIsNone(runtime.qmp_query('/s', connect=lambda: FakeQMP(stream)))
        self.assertFalse(runtime.qmp_powerdown('/s', connect=lambda: FakeQMP(
            '{"QMP": {}}\n{"return": {}}\n{"error": {"desc": "x"}}\n')))

    def test_node_observer_requires_identity_and_qmp(self):
        binding = {'instance_uuid': INSTANCE, 'generation': 2,
                   'nodes': {'kali': {'runtime': '/synthetic/runtime',
                                      'sockets': '/synthetic/sockets'}}}
        argv = ['/synthetic/qemu']
        expected = {'pid': 4242, 'argv': argv, 'start_identity': identity_for(argv)}
        live = ps_output(f'{LSTART}\n/synthetic/qemu\n')
        observer = runtime.node_observer(binding, run=live,
                                         qmp_connect=lambda: FakeQMP(qmp_stream(RUNNING)))
        def alive():
            process = mock.Mock(pid=4242)
            process.poll.return_value = None
            return process
        record = observer('kali', alive(), dict(expected))
        self.assertEqual(record, dict(expected, instance_uuid=INSTANCE, generation=2,
                                      node_id='kali', qmp_ready=True,
                                      overlay='/synthetic/runtime/overlay.qcow2',
                                      qmp='/synthetic/sockets/qmp.sock'))
        no_qmp = runtime.node_observer(binding, run=live, qmp_connect=lambda: FakeQMP(''))
        self.assertIsNone(no_qmp('kali', alive(), dict(expected)))
        reused = runtime.node_observer(
            binding, run=ps_output(f'{LSTART} +1s\n/synthetic/qemu\n'),
            qmp_connect=lambda: FakeQMP(qmp_stream(RUNNING)))
        self.assertIsNone(reused('kali', alive(), dict(expected)))


class TakeoverTests(unittest.TestCase):
    setUp = fixtures.ScenarioServiceTests.setUp
    setup_assets = fixtures.ScenarioServiceTests.setup_assets
    image_run = fixtures.ScenarioServiceTests.image_run
    collect = fixtures.ScenarioServiceTests.collect
    scenario_prepare = fixtures.ScenarioServiceTests.scenario_prepare
    prepare = fixtures.ScenarioServiceTests.prepare
    stopped = node_fixtures.NodeResetTests.stopped

    def records(self, prepared):
        records = fixtures.ScenarioServiceTests.records(self, prepared)
        for key, spec in prepared.specs.items():
            records[key]['generation'] = spec['generation']
        return records

    def activate(self):
        prepared = self.prepare()
        self.bindings = prepared.bindings
        prepared.close()
        self.scene = self.root / 'scenarios' / INSTANCE
        reset.initialize_active_generation(self.root, INSTANCE, generation=1,
            available_capabilities=CAPS, observe_stopped=self.stopped)
        return prepared

    def node_processes(self, pids):
        processes = {}
        for key in ('kali', 'straylight', 'neuromancer'):
            argv = ['/synthetic/qemu', '-name', key]
            processes[key] = {'pid': pids[key], 'argv': argv,
                              'start_identity': identity_for(argv)}
        return processes

    def write_journal(self, name, state, processes, *, token=None, stop_requested=None):
        path = self.scene / 'generations/1' / name
        event = {'schema': 1, 'instance_uuid': INSTANCE, 'generation': 1,
                 'binding_digest': _digest(self.bindings), 'state': state,
                 'processes': processes, 'pending': [],
                 'stop_requested': stop_requested or []}
        if token is not None:
            event['token'] = token
        registry.append_event(path, event)

    def ps_for(self, live_pids, commands, *, exited=None):
        """exited 传可变集合引用：powerdown/signal 后的退出在采集时生效。"""
        def run(args, **_kwargs):
            pid = int(args[args.index("-p") + 1])
            if pid not in live_pids or (exited is not None and pid in exited):
                import subprocess
                raise subprocess.SubprocessError('synthetic absent')
            command = commands.get(pid, ['/synthetic/qemu'])
            return mock.Mock(stdout=f'{LSTART}\n{" ".join(command)}\n', returncode=0)
        return run

    def test_stopped_observer_marks_recorded_members(self):
        self.activate()
        evidence = runtime.stopped_observer(self.root, INSTANCE, 1,
                                            run=ps_output('', fail=True))
        self.assertEqual(evidence,
                         {'instance_uuid': INSTANCE, 'generation': 1,
                          'nodes': {key: 'stopped' for key in ('kali', 'straylight', 'neuromancer')},
                          'networks': {key: 'stopped' for key in ('outer', 'inner')}})
        pids = {'kali': 704, 'straylight': 709, 'neuromancer': 710}
        self.write_journal('node-lifecycle.jsonl', 'nodes-ready', self.node_processes(pids))
        live = runtime.stopped_observer(self.root, INSTANCE, 1,
                                        run=self.ps_for(set(pids.values()),
                                                        {pid: ['/synthetic/qemu', '-name', key]
                                                         for key, pid in pids.items()}))
        self.assertEqual(live['nodes'], {'kali': 'live', 'straylight': 'live', 'neuromancer': 'live'})
        absent = runtime.stopped_observer(self.root, INSTANCE, 1,
                                          run=ps_output('', fail=True))
        self.assertEqual(absent['nodes'], {key: 'stopped' for key in ('kali', 'straylight', 'neuromancer')})
        # QMP 仍可达时不得报告停止。
        reachable = runtime.stopped_observer(self.root, INSTANCE, 1,
                                             run=ps_output('', fail=True),
                                             qmp_connect=lambda: FakeQMP(qmp_stream(RUNNING)))
        self.assertEqual(reachable['nodes'], {key: 'live' for key in ('kali', 'straylight', 'neuromancer')})
        # 日志与绑定摘要不匹配按 unknown 处理，绝不冒充停止。
        self.write_journal('network-lifecycle.jsonl', 'networks-ready', {'outer': {}}, token='0' * 8)
        mismatch = runtime.stopped_observer(self.root, INSTANCE, 1,
                                            run=ps_output('', fail=True))
        self.assertEqual(mismatch['networks'], {'outer': 'unknown', 'inner': 'unknown'})

    def test_stop_recovered_nodes_takeover_and_timeout(self):
        self.activate()
        pids = {'kali': 711, 'straylight': 712, 'neuromancer': 713}
        commands = {pid: ['/synthetic/qemu', '-name', key] for key, pid in pids.items()}
        self.write_journal('node-lifecycle.jsonl', 'nodes-ready', self.node_processes(pids))
        requested, exited = [], set()
        def powerdown(key, _process, expected):
            requested.append(key)
            self.assertEqual(expected['pid'], pids[key])
            exited.add(expected['pid'])
        inspect = runtime.build_inspect(run=self.ps_for(set(pids.values()), commands, exited=exited))
        self.assertTrue(runtime.stop_recovered_nodes(self.root, INSTANCE, generation=1,
            inspect=inspect, powerdown=powerdown, timeout_per_node=1))
        self.assertEqual(requested, ['kali', 'straylight', 'neuromancer'])
        events = registry.read_events(self.scene / 'generations/1/node-lifecycle.jsonl')
        self.assertEqual([event['state'] for event in events],
                         ['nodes-ready', 'stopping', 'stopping', 'stopping', 'stopping', 'stopped'])
        self.assertEqual(events[-1]['stop_requested'], ['kali', 'straylight', 'neuromancer'])
        for lock in (self.root / 'scenario-resources.lock', self.scene / 'scenario.lock',
                     self.scene / 'generations/1/nodes/kali/node.lock'):
            with resources._resource_lock(lock):
                pass

    def test_node_takeover_timeout_preserves_later_nodes_and_retry(self):
        self.activate()
        pids = {'kali': 721, 'straylight': 722, 'neuromancer': 723}
        commands = {pid: ['/synthetic/qemu', '-name', key] for key, pid in pids.items()}
        self.write_journal('node-lifecycle.jsonl', 'nodes-ready', self.node_processes(pids))
        requested, exited, tick = [], set(), [0.0]
        def powerdown(key, _process, expected):
            requested.append(key)
            if key != 'kali':
                exited.add(expected['pid'])
        def pause(seconds):
            tick[0] += seconds
        inspect = runtime.build_inspect(run=self.ps_for(set(pids.values()), commands, exited=exited))
        self.assertFalse(runtime.stop_recovered_nodes(self.root, INSTANCE, generation=1,
            inspect=inspect, powerdown=powerdown, timeout_per_node=0.1,
            clock=lambda: tick[0], pause=pause))
        self.assertEqual(requested, ['kali'])
        events = registry.read_events(self.scene / 'generations/1/node-lifecycle.jsonl')
        self.assertEqual(events[-1]['state'], 'stop-pending')
        # kali 退出后重试：不重复发送已记录的关机请求，继续处理其余节点。
        exited.add(pids['kali'])
        inspect = runtime.build_inspect(run=self.ps_for(set(pids.values()), commands, exited=exited))
        self.assertTrue(runtime.stop_recovered_nodes(self.root, INSTANCE, generation=1,
            inspect=inspect, powerdown=powerdown, timeout_per_node=1))
        self.assertEqual(requested, ['kali', 'straylight', 'neuromancer'])

    def test_node_takeover_refuses_pending_identity_and_pointer(self):
        self.activate()
        pids = {'kali': 731, 'straylight': 732, 'neuromancer': 733}
        commands = {pid: ['/synthetic/qemu', '-name', key] for key, pid in pids.items()}
        inspect = runtime.build_inspect(run=self.ps_for(set(pids.values()), commands))
        with self.assertRaisesRegex(ScenarioError, '日志缺失'):
            runtime.stop_recovered_nodes(self.root, INSTANCE, generation=1,
                inspect=inspect, powerdown=lambda *_: None, timeout_per_node=1)
        path = self.scene / 'generations/1/node-lifecycle.jsonl'
        registry.append_event(path, {'schema': 1, 'instance_uuid': INSTANCE, 'generation': 1,
            'binding_digest': _digest(self.bindings), 'state': 'nodes-ready',
            'processes': self.node_processes(pids), 'pending': ['kali'], 'stop_requested': []})
        with self.assertRaisesRegex(ScenarioError, '不明启动窗口'):
            runtime.stop_recovered_nodes(self.root, INSTANCE, generation=1,
                inspect=inspect, powerdown=lambda *_: None, timeout_per_node=1)
        events = registry.read_events(path)
        registry.append_event(path, dict(events[-1], state='nodes-ready', pending=[]))
        reused = runtime.build_inspect(
            run=self.ps_for(set(pids.values()), {pid: ['/synthetic/other'] for pid in pids.values()}))
        with self.assertRaisesRegex(ScenarioError, '身份失配'):
            runtime.stop_recovered_nodes(self.root, INSTANCE, generation=1,
                inspect=reused, powerdown=lambda *_: None, timeout_per_node=1)
        pointer = json.loads((self.scene / 'active-generation.json').read_text())
        pointer['descriptor'] = 'reset-ready.json'
        (self.scene / 'active-generation.json').write_text(json.dumps(pointer))
        with self.assertRaisesRegex(ScenarioError, '未激活'):
            runtime.stop_recovered_nodes(self.root, INSTANCE, generation=1,
                inspect=inspect, powerdown=lambda *_: None, timeout_per_node=1)
        self.assertFalse(registry.read_events(path)[-1]['state'] == 'stopping')

    def test_stop_recovered_services_signals_once_and_waits(self):
        self.activate()
        binding_token = self.bindings['reservation_token']
        processes = {name: {'pid': pid, 'argv': ['/synthetic/dhcp', name],
                            'start_identity': identity_for(['/synthetic/dhcp', name])}
                     for name, pid in (('outer', 741), ('inner', 742))}
        self.write_journal('network-lifecycle.jsonl', 'networks-ready', processes, token=binding_token)
        signaled, exited = [], set()
        def signal_process(pid):
            signaled.append(pid)
            exited.add(pid)
        def inspect_factory():
            return runtime.build_inspect(run=self.ps_for({741, 742}, {741: ['/synthetic/dhcp', 'outer'], 742: ['/synthetic/dhcp', 'inner']}, exited=exited))
        with self.assertRaisesRegex(ScenarioError, '节点未证明'):
            runtime.stop_recovered_services(self.root, INSTANCE, generation=1,
                available_capabilities=CAPS, inspect=inspect_factory(), signal_process=signal_process,
                nodes_stopped=lambda: False, timeout=1)
        self.assertTrue(runtime.stop_recovered_services(self.root, INSTANCE, generation=1,
            available_capabilities=CAPS, inspect=inspect_factory(), signal_process=signal_process,
            nodes_stopped=lambda: True, timeout=1))
        self.assertEqual(signaled, [742, 741])
        events = registry.read_events(self.scene / 'generations/1/network-lifecycle.jsonl')
        self.assertEqual([event['state'] for event in events],
                         ['networks-ready', 'stopping', 'stopping', 'stopping', 'stopped'])
        self.assertEqual(events[-1]['stop_requested'], ['inner', 'outer'])
        self.assertIn(binding_token, registry.active_reservations(self.root))

    def test_service_takeover_timeout_keeps_pending_without_resignal(self):
        self.activate()
        binding_token = self.bindings['reservation_token']
        processes = {'outer': {'pid': 751, 'argv': ['/synthetic/dhcp', 'outer'],
                               'start_identity': identity_for(['/synthetic/dhcp', 'outer'])}}
        self.write_journal('network-lifecycle.jsonl', 'networks-ready', processes, token=binding_token)
        signaled, exited, tick = [], set(), [0.0]
        def signal_process(pid):
            signaled.append(pid)
        def pause(seconds):
            tick[0] += seconds
        inspect = runtime.build_inspect(run=self.ps_for({751}, {751: ['/synthetic/dhcp', 'outer']}, exited=exited))
        self.assertFalse(runtime.stop_recovered_services(self.root, INSTANCE, generation=1,
            available_capabilities=CAPS, inspect=inspect, signal_process=signal_process,
            nodes_stopped=lambda: True, timeout=0.1, clock=lambda: tick[0], pause=pause))
        self.assertEqual(signaled, [751])
        events = registry.read_events(self.scene / 'generations/1/network-lifecycle.jsonl')
        self.assertEqual(events[-1]['state'], 'stop-pending')
        exited.add(751)
        inspect = runtime.build_inspect(run=self.ps_for({751}, {751: ['/synthetic/dhcp', 'outer']}, exited=exited))
        self.assertTrue(runtime.stop_recovered_services(self.root, INSTANCE, generation=1,
            available_capabilities=CAPS, inspect=inspect, signal_process=signal_process,
            nodes_stopped=lambda: True, timeout=1))
        self.assertEqual(signaled, [751])  # 重试只等待，不重复发送。

    def test_service_takeover_refuses_released_reservation(self):
        self.activate()
        binding_token = self.bindings['reservation_token']
        processes = {'outer': {'pid': 761, 'argv': ['/synthetic/dhcp', 'outer'],
                               'start_identity': identity_for(['/synthetic/dhcp', 'outer'])}}
        self.write_journal('network-lifecycle.jsonl', 'networks-ready', processes, token=binding_token)
        registry.release_reservation(self.root, binding_token,
                                     observe_stopped=lambda _: self.stopped(self.bindings))
        inspect = runtime.build_inspect(run=self.ps_for({761}, {}))
        with self.assertRaisesRegex(ScenarioError, '预约'):
            runtime.stop_recovered_services(self.root, INSTANCE, generation=1,
                available_capabilities=CAPS, inspect=inspect, signal_process=lambda pid: None,
                nodes_stopped=lambda: True, timeout=1)


if __name__ == '__main__':
    unittest.main()
