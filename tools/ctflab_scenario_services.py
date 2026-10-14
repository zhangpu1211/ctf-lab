"""双网服务生命周期合成入口；必须注入启动器，不自动启动 VM 或真实服务。"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time

from ctflab_scenario import _path, _require, network_server_specs
from ctflab_scenario_registry import active_reservations, append_event, read_events
from ctflab_scenario_resources import OwnedNetworkProcesses, wait_network_ready


def network_service_command(prepared, network_id, *, python_binary, service_script):
    """仅从已准备的白名单配置构造 argv/继承 FD，不执行。"""
    _require(not prepared.closed and network_id in prepared.specs, '准备对象或网段错误')
    spec = prepared.specs[network_id]
    config = spec['config']
    fd = prepared.listeners[network_id].fileno()
    args = [_path(python_binary), _path(service_script), '--port', str(prepared.ports[network_id]),
        '--listener-fd', str(fd), '--state', str(spec['state_path']), '--cidr', config.cidr,
        '--server-ip', config.server_ip, '--pool-start', config.pool_start, '--pool-end', config.pool_end,
        '--server-mac', config.server_mac, '--registered-only', '--instance-uuid', spec['instance_uuid'],
        '--network-id', network_id, '--generation', str(spec['generation'])]
    for mac, address in sorted(spec['static_leases'].items()):
        args.extend(['--lease', f'{mac}={address}'])
    return args, (fd,)


def _digest(bindings):
    return hashlib.sha256(json.dumps(bindings, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _validate_reservation(binding, root, specs, active):
    """准备记录必须与登记中的完整资源集合一致，不能只核对端口。"""
    _require(set(binding) == {'schema', 'instance_uuid', 'generation', 'status', 'manifest',
             'reservation_token', 'assets', 'firmware', 'nodes', 'network_ports'}
             and type(binding['schema']) is int and binding['schema'] == 1
             and binding['status'] == 'assets-prepared', '准备记录字段错误')
    token = binding['reservation_token']
    _require(token in active, '服务会话预约已失效')
    manifest = binding['manifest']
    _require(set(binding['assets']) == set(manifest['assets'])
             and set(binding['nodes']) == set(manifest['nodes'])
             and set(binding['network_ports']) == set(specs), '准备资源绑定不完整')
    for key, asset in binding['assets'].items():
        _require(set(asset) == {'path', 'sha256'} and asset['sha256'] == manifest['assets'][key]['sha256'],
                 '资产绑定与清单不一致')
        _path(asset['path'])
    paths, socket_roots = [], set()
    generation_root = root / 'scenarios' / binding['instance_uuid'] / 'generations' / str(binding['generation'])
    for key, node in binding['nodes'].items():
        runtime, sockets = Path(_path(node['runtime'])), Path(_path(node['sockets']))
        _require(set(node) == {'runtime', 'sockets'} and runtime == generation_root / 'nodes' / key
                 and sockets.parts[-3:] == (binding['instance_uuid'], str(binding['generation']), key),
                 '节点运行路径绑定错误')
        socket_roots.add(sockets.parents[2])
        paths.extend([str(runtime), str(sockets)])
    _require(len(socket_roots) == 1, 'socket 根绑定不一致')
    macs = {nic['mac'] for node in manifest['nodes'].values() for nic in node['interfaces']}
    macs.update(spec['config'].server_mac for spec in specs.values())
    paths.extend(str(spec['state_path']) for spec in specs.values())
    _require(all(type(port) is int and 1024 <= port <= 65535 for port in binding['network_ports'].values()),
             '准备端口类型或范围错误')
    expected = {'instance_uuid': binding['instance_uuid'], 'generation': binding['generation'],
                'macs': sorted(macs), 'ports': sorted(binding['network_ports'].values()), 'paths': sorted(paths)}
    _require(active[token] == expected, '预约与准备资源绑定不匹配')


def _deadline(timeout, clock):
    _require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 600,
             '无效服务截止时间')
    return clock() + timeout


class NetworkServiceSession:
    """只管理本会话启动的网络服务；VM 的停止证明仍由外层提供。"""

    def __init__(self, prepared, *, spawn, identity, python_binary, service_script):
        _require(not prepared.closed and hasattr(prepared, 'bindings'), '需要完整资产准备对象')
        root = prepared.binding_path.parents[4]
        scene_lock = root / 'scenarios' / prepared.bindings['instance_uuid'] / 'scenario.lock'
        lock_info, expected_lock = os.fstat(prepared.lock.fileno()), scene_lock.stat()
        _require((lock_info.st_dev, lock_info.st_ino) == (expected_lock.st_dev, expected_lock.st_ino),
                 '服务会话必须持场景锁')
        _require(_read_binding(prepared.binding_path) == prepared.bindings, '准备绑定被修改')
        # 指针存在时必须指向本准备记录：防止接续中断的孤儿记录或旧代次绕过激活启动。
        pointer = root / 'scenarios' / prepared.bindings['instance_uuid'] / 'active-generation.json'
        if pointer.exists() or pointer.is_symlink():
            activated = _read_binding(pointer)
            _require(activated.get('generation') == prepared.bindings['generation']
                     and activated.get('binding_digest') == _digest(prepared.bindings),
                     '准备记录未接续激活或绑定变化；禁止启动')
        active = active_reservations(root)
        _validate_reservation(prepared.bindings, root, prepared.specs, active)
        self.prepared = prepared
        self.spawn, self.identity = spawn, identity
        self.python_binary, self.service_script = python_binary, service_script
        self.owned = OwnedNetworkProcesses(prepared)
        self.processes, self.identities, self.pending = {}, {}, []
        self.state = 'prepared'
        self.stop_requested = []
        self.journal = prepared.binding_path.parent / 'network-lifecycle.jsonl'
        _require(not self.journal.exists() and not self.journal.is_symlink(), '已有服务日志；必须先恢复核验')
        self.binding_digest = _digest(prepared.bindings)
        self._record('prepared')

    def _record(self, state):
        try:
            append_event(self.journal, {'schema': 1, 'instance_uuid': self.prepared.bindings['instance_uuid'],
                'generation': self.prepared.bindings['generation'], 'token': self.prepared.reservation_token,
                'binding_digest': self.binding_digest, 'state': state,
                'processes': copy.deepcopy(self.identities), 'pending': list(self.pending),
                'stop_requested': list(self.stop_requested)})
        except BaseException:
            self.state = 'recovery-required'
            raise
        self.state = state

    def start(self, *, timeout, clock=time.monotonic, pause=time.sleep):
        _require(self.state == 'prepared' and not self.prepared.closed, '禁止重复启动或绕过恢复')
        deadline = _deadline(timeout, clock)
        try:
            self._record('starting')
            for key in ('outer', 'inner'):
                _require(clock() < deadline, '服务启动截止时间已过；保留现场')
                args, fds = network_service_command(self.prepared, key,
                    python_binary=self.python_binary, service_script=self.service_script)
                # 先记 spawn 窗口。启动抛错也可能已创建子进程，不能推断没有占用。
                self.pending = [key]
                self._record('starting')
                process = self.spawn(args, pass_fds=fds, close_fds=True)
                self.processes[key] = process
                self.owned.bind(key, process, expected_args=args)
                start_identity = self.identity(process)
                _require(isinstance(start_identity, str) and start_identity and len(start_identity) <= 256,
                         '缺少可信进程启动身份')
                self.identities[key] = {'pid': process.pid, 'argv': args, 'start_identity': start_identity}
                self.pending = []
                self._record('starting')
            remaining = deadline - clock()
            _require(remaining > 0, '服务启动截止时间已过；保留现场')
            result = wait_network_ready(self.prepared, observe=self.owned.observe,
                owned_process=self.owned.owned, timeout=remaining, clock=clock, pause=pause)
            self._record('networks-ready')
            return result
        except BaseException:
            self.state = 'degraded'
            # 写盘失败不能代替原异常；已有 spawn 窗口要求恢复核验。
            try:
                self._record('degraded')
            except (OSError, ValueError):
                pass
            raise

    def check_health(self):
        """当前会话双网身份/配置核验；失联只降级，不补启。"""
        _require(self.state == 'networks-ready' and not self.prepared.closed, '当前状态禁止健康核验')
        try:
            _require(all(self.identity(process) == self.identities[key]['start_identity']
                         for key, process in self.processes.items()), '进程启动身份变化')
            for key in self.prepared.specs:
                _require(self.owned.observe(key) is not None, '网络记录缺失')
            wait_network_ready(self.prepared, observe=self.owned.observe,
                               owned_process=self.owned.owned, timeout=0.01)
            return True
        except (OSError, ValueError):
            self._record('degraded')
            return False

    def stop(self, *, nodes_stopped, timeout, clock=time.monotonic, pause=time.sleep):
        """可信外层证明三节点停止才可停网络；超时不强杀、不释放预约。"""
        _require(not self.prepared.closed and self.state in ('networks-ready', 'degraded', 'stop-pending'),
                 '当前状态禁止停止')
        deadline = _deadline(timeout, clock)
        _require(nodes_stopped() is True, '节点未证明全部停止；禁止停网络')
        _require(not self.pending and set(self.processes) == set(self.identities),
                 '存在不明启动窗口；必须恢复核验')
        for key, process in self.processes.items():
            _require(process.poll() is not None or (self.owned.owned(key, process.pid)
                     and self.identity(process) == self.identities[key]['start_identity']),
                     '进程归属变化；禁止停止')
        _require(clock() < deadline, '停止核验超过截止时间；未发送请求')
        self._record('stopping')
        try:
            for key in ('inner', 'outer'):
                process = self.processes.get(key)
                if process is not None and process.poll() is None:
                    _require(self.owned.owned(key, process.pid), '进程归属变化；禁止停止')
                    # 重试只等待，不重复发送终止请求。没有 kill/按记录 PID 发信号。
                    if key not in self.stop_requested:
                        _require(clock() < deadline, '停止请求超过截止时间')
                        self.stop_requested.append(key)
                        self._record('stopping')
                        process.terminate()
            while any(process.poll() is None for process in self.processes.values()):
                if clock() >= deadline:
                    self._record('stop-pending')
                    return False
                pause(min(0.05, max(0, deadline - clock())))
            self._record('stopped')
            return True
        except BaseException:
            self.state = 'degraded'
            try:
                self._record('degraded')
            except (OSError, ValueError):
                pass
            raise


def _read_binding(path):
    for component in [*path.parents, path]:
        _require(not component.is_symlink(), '准备记录路径禁止符号链接')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'r', encoding='utf-8') as source:
        info = os.fstat(source.fileno())
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                 and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
                 and info.st_size <= 1024 * 1024, '准备记录归属或类型错误')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                _require(key not in result, '准备记录重复字段')
                result[key] = value
            return result
        return json.load(source, object_pairs_hook=unique,
                         parse_constant=lambda _value: (_ for _ in ()).throw(ValueError('非法常量')))


def recover_network_services(state_root, instance_uuid, *, generation, available_capabilities, inspect):
    """只读恢复审计；inspect 是可信现场身份观察器，本函数不接管/启动/发信号。"""
    root = Path(_path(state_root))
    # 先校验用于构造路径的身份，防止从记录中扩大读取范围。
    import uuid
    _require(str(uuid.UUID(instance_uuid)) == instance_uuid and type(generation) is int and generation > 0,
             '恢复实例或代次错误')
    path = root / 'scenarios' / instance_uuid / 'generations' / str(generation) / 'prepared.json'
    binding = _read_binding(path)
    _require(isinstance(binding, dict) and binding.get('instance_uuid') == instance_uuid
             and type(binding.get('generation')) is int and binding['generation'] == generation,
             '准备记录实例或代次不匹配')
    specs = network_server_specs(binding['manifest'], instance_uuid, generation=generation,
                                state_root=root, available_capabilities=available_capabilities)
    active = active_reservations(root)
    token = binding['reservation_token']
    _validate_reservation(binding, root, specs, active)
    events = read_events(path.parent / 'network-lifecycle.jsonl')
    digest = _digest(binding)
    states = {'prepared', 'starting', 'networks-ready', 'degraded', 'stopping', 'stop-pending', 'stopped'}
    for event in events:
        _require(set(event) == {'schema', 'instance_uuid', 'generation', 'token', 'binding_digest',
                               'state', 'processes', 'pending', 'stop_requested', 'sequence'}
                 and type(event.get('schema')) is int and event['schema'] == 1 and event.get('instance_uuid') == instance_uuid
                 and type(event.get('generation')) is int and event['generation'] == generation
                 and event.get('token') == token and event.get('binding_digest') == digest
                 and event.get('state') in states and isinstance(event.get('processes'), dict)
                 and isinstance(event.get('pending'), list)
                 and isinstance(event.get('stop_requested'), list)
                 and set(event['stop_requested']) <= set(specs)
                 and len(event['stop_requested']) == len(set(event['stop_requested']))
                 and set(event['processes']) <= set(specs) and set(event['pending']) <= set(specs),
                 '服务日志绑定错误；需要恢复')
    if not events:
        return {'state': 'prepared-observed', 'live': [], 'absent': [], 'unknown': []}
    last = events[-1]
    live, absent, unknown = [], [], list(last['pending'])
    for key, expected in last['processes'].items():
        _require(isinstance(expected, dict) and set(expected) == {'pid', 'argv', 'start_identity'}
                 and type(expected['pid']) is int and expected['pid'] > 0
                 and isinstance(expected['argv'], list) and all(isinstance(arg, str) for arg in expected['argv'])
                 and isinstance(expected['start_identity'], str) and expected['start_identity'], '日志启动身份非法')
        observed = inspect(key, copy.deepcopy(expected))
        if observed == {'status': 'absent'}:
            absent.append(key)
        elif observed == dict(expected, status='live') and type(observed.get('pid')) is int:
            live.append(key)
        else:
            unknown.append(key)
    _require(read_events(path.parent / 'network-lifecycle.jsonl') == events
             and _read_binding(path) == binding and active_reservations(root) == active,
             '恢复观察期间记录变化；需要重新核验')
    # starting 日志在两次 spawn 之间中断也不能自动补启。
    if unknown or last['state'] in ('starting', 'stopping', 'degraded') or (last['state'] == 'stopped' and live):
        state = 'recovery-required'
    elif len(live) == 2 and last['state'] == 'networks-ready':
        state = 'networks-observed'  # 尚未重新检查 DHCP/QMP/节点与隔离。
    elif len(absent) == len(last['processes']) and last['state'] in ('stopped', 'stop-pending'):
        state = 'stopped-observed'
    elif last['state'] == 'prepared' and not last['processes']:
        state = 'prepared-observed'
    else:
        state = 'recovery-required'
    return {'state': state, 'live': sorted(live), 'absent': sorted(absent), 'unknown': sorted(set(unknown))}
