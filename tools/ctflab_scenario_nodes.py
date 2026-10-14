"""三节点生命周期合成接口；无默认启动器、QMP 客户端或强制停止。"""
from __future__ import annotations

import copy
from pathlib import Path
import time

from ctflab_scenario import _require, qemu_command
from ctflab_scenario_registry import append_event, read_events
from ctflab_scenario_resources import _resource_lock
from ctflab_scenario_services import _deadline, _digest, _read_binding


class ScenarioNodeSession:
    def __init__(self, networks, *, spawn, identity, observe, powerdown, qemu_binaries,
                 available_capabilities, headless_architectures=frozenset()):
        _require(networks.state == 'networks-ready' and not networks.prepared.closed,
                 '双网未就绪；禁止创建节点')
        self.networks, self.prepared = networks, networks.prepared
        self.spawn, self.identity, self.observe, self.powerdown = spawn, identity, observe, powerdown
        self.binding = copy.deepcopy(self.prepared.bindings)
        self.root = self.prepared.binding_path.parents[4]
        pointer = self.root / 'scenarios' / self.binding['instance_uuid'] / 'active-generation.json'
        if pointer.exists() or pointer.is_symlink():
            active = _read_binding(pointer)
            _require(active.get('generation') == self.binding['generation']
                     and active.get('binding_digest') == _digest(self.binding),
                     '准备代次已非活动代次或绑定变化；禁止旧代次启动')
        self.qemu_binaries, self.capabilities = qemu_binaries, available_capabilities
        # headless 架构的节点省略 -spice（无 SPICE 运行时）；显示证据走 QMP screendump。
        self.headless_architectures = frozenset(headless_architectures)
        self.processes, self.identities, self.pending, self.stop_requested = {}, {}, [], []
        self.locks, self.state = [], 'prepared'
        self.journal = self.prepared.binding_path.parent / 'node-lifecycle.jsonl'
        _require(not self.journal.exists() and not self.journal.is_symlink(), '已有节点日志；必须恢复核验')
        try:
            # 场景锁已由准备对象持有，节点锁按名称排序。
            for key in sorted(self.binding['nodes']):
                self.locks.append(_resource_lock(Path(self.binding['nodes'][key]['runtime']) / 'node.lock'))
            self._record('prepared')
        except BaseException:
            self.close()
            raise

    def close(self):
        """仅释放本会话节点锁；调用方仍须管理场景锁、存活对象及恢复。"""
        for lock in reversed(self.locks):
            lock.close()
        self.locks.clear()

    def _record(self, state):
        try:
            append_event(self.journal, {'schema': 1, 'instance_uuid': self.binding['instance_uuid'],
                'generation': self.binding['generation'], 'binding_digest': _digest(self.binding),
                'state': state, 'processes': copy.deepcopy(self.identities),
                'pending': list(self.pending), 'stop_requested': list(self.stop_requested)})
        except BaseException:
            self.state = 'recovery-required'
            raise
        self.state = state

    def _owned(self, key):
        process = self.processes[key]
        expected = self.identities.get(key)
        return (expected is not None and not self.prepared.closed and bool(self.locks)
                and process.pid == expected['pid'] and process.args == expected['argv']
                and self.identity(process) == expected['start_identity'] and process.poll() is None)

    def _command(self, key):
        node = self.binding['manifest']['nodes'][key]
        sockets = Path(self.binding['nodes'][key]['sockets']).parents[2]
        return qemu_command(self.binding['manifest'], self.binding['instance_uuid'], key,
            generation=self.binding['generation'], state_root=self.root, socket_root=sockets,
            network_ports=self.prepared.ports, qemu_binary=self.qemu_binaries[node['architecture']],
            firmware_code=self.prepared.firmware.get(key, {}).get('code'), available_capabilities=self.capabilities,
            include_spice=node['architecture'] not in self.headless_architectures)

    def _ready(self, key):
        _require(self._owned(key), '节点退出或启动身份不匹配')
        process = self.processes[key]
        observed = self.observe(key, process, copy.deepcopy(self.identities[key]))
        if observed is None:
            return False
        expected = dict(self.identities[key], instance_uuid=self.binding['instance_uuid'],
            generation=self.binding['generation'], node_id=key, qmp_ready=True,
            overlay=str(Path(self.binding['nodes'][key]['runtime']) / 'overlay.qcow2'),
            qmp=str(Path(self.binding['nodes'][key]['sockets']) / 'qmp.sock'))
        _require(isinstance(observed, dict) and observed == expected
                 and observed.get('qmp_ready') is True and type(observed.get('pid')) is int
                 and type(observed.get('generation')) is int, '节点 QMP 或磁盘绑定错误')
        return True

    def _degrade(self):
        self.state = 'degraded'
        try:
            self._record('degraded')
        except (OSError, ValueError):
            pass

    def start(self, *, timeout, clock=time.monotonic, pause=time.sleep):
        _require(self.state == 'prepared' and self.locks and not self.prepared.closed, '禁止重复启动或绕过恢复')
        deadline = _deadline(timeout, clock)
        try:
            self._record('starting')
            for key in self.binding['manifest']['lifecycle']['start_order']:
                _require(clock() < deadline and self.networks.check_health(), '启动截止时间已过或网络降级')
                self.pending = [key]
                self._record('starting')
                args = self._command(key)
                process = self.spawn(args, close_fds=True)
                self.processes[key] = process
                start_identity = self.identity(process)
                _require(type(process.pid) is int and process.pid > 0 and process.args == args
                         and process.poll() is None and isinstance(start_identity, str) and start_identity
                         and len(start_identity) <= 256, '节点启动对象或身份错误')
                self.identities[key] = {'pid': process.pid, 'argv': args, 'start_identity': start_identity}
                self.pending = []
                self._record('starting')
                while not self._ready(key):
                    _require(clock() < deadline and self.networks.check_health(), '节点就绪超时或网络降级')
                    pause(min(0.05, max(0, deadline - clock())))
                _require(clock() < deadline, '节点就绪超过截止时间')
            self._record('nodes-ready')  # 尚未验证地址、服务、隔离或题目。
            return True
        except BaseException:
            self._degrade()
            raise

    def check_health(self):
        _require(self.state == 'nodes-ready' and self.locks, '当前状态禁止健康核验')
        try:
            _require(self.networks.check_health() and all(self._ready(key) for key in self.processes),
                     '场景节点或网络失联')
            return True
        except (OSError, ValueError):
            self._degrade()
            return False

    def stop(self, *, timeout_per_node, clock=time.monotonic, pause=time.sleep):
        _require(self.state in ('nodes-ready', 'degraded', 'stop-pending') and self.locks
                 and not self.prepared.closed, '当前状态禁止关机')
        _deadline(timeout_per_node, clock)
        _require(not self.pending and set(self.processes) == set(self.identities), '不明节点启动窗口；必须恢复')
        for key, process in self.processes.items():
            _require(process.poll() is not None or self._owned(key), '节点归属变化；禁止关机')
        try:
            self._record('stopping')
            for key in self.binding['manifest']['lifecycle']['stop_order']:
                process = self.processes.get(key)
                if process is None or process.poll() is not None:
                    continue
                deadline = _deadline(timeout_per_node, clock)
                _require(self._owned(key), '节点归属变化；禁止关机')
                if key not in self.stop_requested:
                    self.stop_requested.append(key)
                    self._record('stopping')
                    self.powerdown(key, process, copy.deepcopy(self.identities[key]))
                while process.poll() is None:
                    _require(self._owned(key), '等待关机时节点归属变化')
                    if clock() >= deadline:
                        self._record('stop-pending')
                        return False  # 保留其它节点及双网，不自动强杀。
                    pause(min(0.05, max(0, deadline - clock())))
            self._record('stopped')
            return True
        except BaseException:
            self._degrade()
            raise

    def nodes_stopped(self):
        return (self.state == 'stopped' and not self.pending and self.locks
                and all(process.poll() is not None for process in self.processes.values())) is True


def recover_scenario_nodes(prepared, *, inspect):
    """只读节点身份审计；不接管 QMP、不补启、不发送关机请求。"""
    _require(not prepared.closed, '准备对象已关闭')
    binding = _read_binding(prepared.binding_path)
    _require(binding == prepared.bindings, '准备绑定变化')
    path = prepared.binding_path.parent / 'node-lifecycle.jsonl'
    events = read_events(path)
    _require(events, '节点日志缺失；不能推断没有进程')
    allowed = {'prepared', 'starting', 'nodes-ready', 'degraded', 'stopping', 'stop-pending', 'stopped'}
    for event in events:
        _require(type(event.get('schema')) is int and event['schema'] == 1 and event.get('instance_uuid') == binding['instance_uuid']
                 and type(event.get('generation')) is int and event['generation'] == binding['generation']
                 and event.get('binding_digest') == _digest(binding) and event.get('state') in allowed
                 and isinstance(event.get('processes'), dict) and isinstance(event.get('pending'), list)
                 and set(event['processes']) <= set(binding['nodes']) and set(event['pending']) <= set(binding['nodes']),
                 '节点日志绑定错误')
    last = events[-1]
    live, absent, unknown = [], [], list(last['pending'])
    for key, expected in last['processes'].items():
        _require(isinstance(expected, dict) and set(expected) == {'pid', 'argv', 'start_identity'}
                 and type(expected['pid']) is int and expected['pid'] > 0
                 and isinstance(expected['argv'], list) and all(isinstance(arg, str) for arg in expected['argv'])
                 and isinstance(expected['start_identity'], str)
                 and expected['start_identity'], '节点启动身份记录非法')
        observed = inspect(key, copy.deepcopy(expected))
        if observed == {'status': 'absent'}:
            absent.append(key)
        elif observed == dict(expected, status='live') and type(observed.get('pid')) is int:
            live.append(key)
        else:
            unknown.append(key)
    _require(read_events(path) == events and _read_binding(prepared.binding_path) == binding,
             '节点恢复观察期间记录变化')
    if unknown or last['state'] in ('starting', 'stopping', 'degraded'):
        state = 'recovery-required'
    elif last['state'] == 'nodes-ready' and len(live) == 3:
        state = 'nodes-observed'
    elif last['state'] in ('stopped', 'stop-pending') and not live and len(absent) == len(last['processes']):
        state = 'stopped-observed'
    elif last['state'] == 'prepared' and not last['processes']:
        state = 'prepared-observed'
    else:
        state = 'recovery-required'
    return {'state': state, 'live': sorted(live), 'absent': sorted(absent), 'unknown': sorted(set(unknown))}
