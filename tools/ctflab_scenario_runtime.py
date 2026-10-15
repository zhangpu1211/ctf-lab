"""场景生产采集与恢复接管；只控制身份/参数/路径/代次均已核实的所属进程。

本模块把生命周期会话的注入点接到本机观测：进程身份用只读 `ps` 采集，
QMP 通过私有 UNIX socket 握手，停止证明逐一核对已记录进程与端点。
接管停止只在锁内、按日志身份核验后进行；任何不明窗口/身份失配都要求
恢复核验，不以 PID 存活或旧状态文件作为控制授权。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import signal
import socket
import time

from ctflab_scenario import ScenarioError, _require, network_server_specs
from ctflab_scenario_registry import active_reservations, append_event, read_events
from ctflab_scenario_resources import _private_tree, _resource_lock
from ctflab_scenario_services import _digest, _read_binding, _validate_reservation

PS_BINARY = '/bin/ps'


def _ps_environment():
    # lstart 会本地化；身份采集与恢复检查必须使用同一种格式。
    return dict(os.environ, LC_ALL='C', LANG='C')


def popen_spawn(args, *, pass_fds=(), close_fds=True, stdout=None, stderr=None):
    """生产启动器：新会话启动子进程（脱离终端），默认丢弃输出。

    仅由可信 CLI/GUI 编排入口调用；stdout/stderr 可传入已打开的日志文件对象。
    """
    import subprocess
    return subprocess.Popen(args, pass_fds=tuple(pass_fds), close_fds=close_fds,
                            start_new_session=True, stdin=subprocess.DEVNULL,
                            stdout=stdout if stdout is not None else subprocess.DEVNULL,
                            stderr=stderr if stderr is not None else subprocess.DEVNULL)


def _lstart_command(stdout_text):
    """解析 `ps -o lstart=,command=` 输出；兼容单行与两行格式。

    lstart 固定为 5 个词（周 月 日 时 年），其余为命令行。
    """
    lines = [line for line in stdout_text.splitlines() if line.strip()]
    if len(lines) == 1:
        parts = lines[0].split(None, 5)
        if len(parts) != 6:
            return None
        return ' '.join(parts[:5]), parts[5]
    if len(lines) == 2:
        return lines[0].strip(), lines[1]
    return None


def process_start_identity(pid, *, run=None, hasher=hashlib.sha256):
    """只读采集 pid 的启动时间与命令行摘要；进程不存在返回 None。

    摘要绑定 lstart 与命令行：PID 被复用或参数变化都会得到不同身份。
    """
    import subprocess
    _require(type(pid) is int and pid > 0, '无效进程号')
    try:
        result = (run or subprocess.run)([PS_BINARY, '-ww', '-p', str(pid), '-o', 'lstart=,command='],
            capture_output=True, text=True, check=True, timeout=5, env=_ps_environment())
    except subprocess.SubprocessError:
        return None
    fields = _lstart_command(result.stdout)
    if fields is None:
        return None
    return hasher((fields[0] + '\n' + fields[1]).encode()).hexdigest()


def process_command(pid, *, run=None):
    """只读返回 pid 的原始命令行；不存在返回 None。"""
    import subprocess
    try:
        result = (run or subprocess.run)([PS_BINARY, '-ww', '-p', str(pid), '-o', 'command='],
            capture_output=True, text=True, check=True, timeout=5, env=_ps_environment())
    except subprocess.SubprocessError:
        return None
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return lines[0] if len(lines) == 1 else None


def child_identity(process, *, run=None):
    """会话身份提供器：启动后采集子进程身份，直到连续两次一致才采信。

    包装脚本（shebang/env）会经历多次 exec，ps 在此期间看到不同 argv；
    身份未稳定或无法采集时拒绝进入就绪等待，保留启动窗口待恢复。
    """
    import time as time_module
    previous = process_start_identity(process.pid, run=run)
    for _attempt in range(40):
        if previous is None:
            _require(process.poll() is None, '子进程已退出；无法采集启动身份')
            time_module.sleep(0.05)
            previous = process_start_identity(process.pid, run=run)
            continue
        current = process_start_identity(process.pid, run=run)
        if current == previous:
            _require(process.poll() is None, '子进程已退出；无法采集启动身份')
            return current
        previous = current
        time_module.sleep(0.05)
    raise ScenarioError('子进程启动身份未稳定；保留启动窗口待恢复')


def build_inspect(*, run=None):
    """生产恢复审计观察器：单次 ps 采集，PID/命令行/启动身份全匹配才报告 live。

    进程退出窗口期 macOS ps 会退化输出 `(进程名)` 而非完整命令行；
    对这类瞬时读数做有界重读，最终仍不匹配则按 unknown 拒绝。
    """
    import subprocess
    import time as time_module
    def read_once(expected):
        try:
            result = (run or subprocess.run)(
                [PS_BINARY, '-ww', '-p', str(expected['pid']), '-o', 'lstart=,command='],
                capture_output=True, text=True, check=True, timeout=5, env=_ps_environment())
        except subprocess.SubprocessError:
            return {'status': 'absent'}
        fields = _lstart_command(result.stdout)
        if fields is None:
            return {'status': 'absent'}
        # 僵尸进程表示本体已退出（父进程尚未收尸）：按 absent 处理。
        if fields[1] == '<defunct>':
            return {'status': 'absent'}
        identity = hashlib.sha256((fields[0] + '\n' + fields[1]).encode()).hexdigest()
        expected_command = ' '.join(expected['argv'])
        # 包装脚本（shebang/env/解释器）会在命令行前多出解释器前缀；
        # 只要 PID/启动时间一致且记录 argv 是命令行的完整后缀即视为同一进程。
        if identity == expected['start_identity'] and (
                fields[1] == expected_command or fields[1].endswith(' ' + expected_command)):
            return dict(expected, status='live')
        # `(名称)` 形式是 ps 在 argv 不可用时的退化输出，值得瞬时重读；
        # 其它命令行差异属于确定性的身份失配。
        transient = fields[1].startswith('(') and fields[1].endswith(')')
        return {'status': 'unknown', 'transient': transient}
    def inspect(_key, expected):
        verdict = read_once(expected)
        for _attempt in range(4):
            if verdict.get('status') != 'unknown' or not verdict.get('transient'):
                break
            time_module.sleep(0.05)
            verdict = read_once(expected)
        # 恢复审计按 dict(expected, status=...) 精确比对；剔除内部标记。
        return {key: value for key, value in verdict.items() if key != 'transient'}
    return inspect


def _qmp_request(qmp_path, commands, *, connect=None, timeout):
    """QMP 握手并顺序发送命令；返回最后一条命令的 return，失败返回 None。"""
    path = str(qmp_path)
    def default_connect():
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(path)
        return client
    def readline(source):
        buffer = bytearray()
        while True:
            byte = source.recv(1)
            if not byte:
                return None
            buffer.extend(byte)
            if byte == b'\n':
                return json.loads(buffer.decode())
    source = None
    try:
        source = (connect or default_connect)()
        greeting = readline(source)
        if not isinstance(greeting, dict) or 'QMP' not in greeting:
            return None
        for command in ['qmp_capabilities', *commands]:
            source.sendall(json.dumps({'execute': command}).encode() + b'\n')
            response = None
            while response is None:
                response = readline(source)
                if response is None:
                    return None
                if 'return' in response or 'error' in response:
                    break
            if 'error' in response or 'return' not in response:
                return None
            result = response['return']
        return result
    except (OSError, ValueError, TypeError):
        return None
    finally:
        if source is not None:
            try:
                source.close()
            except OSError:
                pass


def qmp_query(qmp_path, *, connect=None, timeout=5.0):
    """连接私有 QMP socket：握手并查询状态；不可达或协议错误返回 None。"""
    result = _qmp_request(qmp_path, ['query-status'], connect=connect, timeout=timeout)
    if isinstance(result, dict) and isinstance(result.get('status'), str):
        return result
    return None


def qmp_powerdown(qmp_path, *, connect=None, timeout=5.0):
    """通过 QMP 请求 ACPI 关机；socket 不可达或协议错误返回 False。"""
    return _qmp_request(qmp_path, ['system_powerdown'], connect=connect, timeout=timeout) is not None


def node_observer(binding, *, run=None, qmp_connect=None, qmp_timeout=5.0):
    """生产节点就绪观察器：启动身份与 QMP 握手同时通过才返回就绪记录。"""
    def observe(key, process, expected):
        if child_identity(process, run=run) != expected['start_identity']:
            return None
        endpoint = Path(binding['nodes'][key]['sockets']) / 'qmp.sock'
        if qmp_query(endpoint, connect=qmp_connect, timeout=qmp_timeout) is None:
            return None
        return dict(expected, instance_uuid=binding['instance_uuid'],
                    generation=binding['generation'], node_id=key, qmp_ready=True,
                    overlay=str(Path(binding['nodes'][key]['runtime']) / 'overlay.qcow2'),
                    qmp=str(endpoint))
    return observe


def node_powerdown(binding, *, connect=None, qmp_timeout=5.0):
    """生产关机请求器：向绑定记录中该节点的 QMP 请求 ACPI powerdown。

    只使用绑定里核验过的 socket 路径与 PID 记录；不接收外部路径或 PID。
    """
    def powerdown(key, _process, expected):
        _require(type(expected.get('pid')) is int and expected['pid'] > 0, '关机请求身份不匹配')
        endpoint = Path(binding['nodes'][key]['sockets']) / 'qmp.sock'
        return qmp_powerdown(endpoint, connect=connect, timeout=qmp_timeout)
    return powerdown


def _journal_last(root, instance_uuid, generation, binding, name):
    """读取并核验单类生命周期日志；缺失返回 None（视为从未通过会话启动）。"""
    path = root / 'scenarios' / instance_uuid / 'generations' / str(generation) / name
    if not path.exists() and not path.is_symlink():
        return None
    events = read_events(path)
    digest = _digest(binding)
    for event in events:
        _require(event.get('instance_uuid') == instance_uuid
                 and event.get('generation') == generation
                 and event.get('binding_digest') == digest, '生命周期日志与准备记录不匹配')
    return events[-1]


def stopped_observer(state_root, instance_uuid, generation, *, run=None, qmp_connect=None):
    """生产停止证明：逐一核对已记录进程身份不存在且 QMP 端点不可达。

    返回与 _stopped 契约同形的证据；发现存活/不明成员时以 'live'/'unknown'
    标注，由调用方的严格比对拒绝。日志与准备记录不匹配按 unknown 处理；
    日志缺失视为该代次从未通过会话启动（该侧成员标 stopped）。
    """
    _require(str(generation).isdigit() and int(generation) > 0, '停止证明代次错误')
    generation = int(generation)
    root = Path(state_root)
    scene = _private_tree(root, root / 'scenarios' / instance_uuid)
    pointer_path = scene / 'active-generation.json'
    binding = None
    pointer = None
    if pointer_path.exists() or pointer_path.is_symlink():
        pointer = _read_binding(pointer_path)
        if pointer.get('generation') == generation:
            descriptor = scene / 'generations' / str(generation) / pointer['descriptor']
            binding = _read_binding(descriptor)
            _require(binding.get('instance_uuid') == instance_uuid
                     and _digest(binding) == pointer.get('binding_digest'), '活动代次完整性不匹配')
    if binding is None and pointer is not None:
        # 旧代次释放时指针可能已切到新代次：直接读取该代次准备记录；
        # 其生命周期日志自带绑定摘要，仍可自洽校验。
        prepared_path = scene / 'generations' / str(generation) / 'prepared.json'
        if prepared_path.exists() and not prepared_path.is_symlink():
            binding = _read_binding(prepared_path)
    inspect = build_inspect(run=run)
    evidence = {'instance_uuid': instance_uuid, 'generation': generation,
                'nodes': {}, 'networks': {}}
    for name, kind, members in (('node-lifecycle.jsonl', 'nodes', ('kali', 'straylight', 'neuromancer')),
                                ('network-lifecycle.jsonl', 'networks', ('outer', 'inner'))):
        recorded = {}
        if binding is not None:
            try:
                last = _journal_last(root, instance_uuid, generation, binding, name)
                recorded = dict(last.get('processes') or {}) if last else {}
            except ScenarioError:
                recorded = None  # 日志损坏或不匹配：不能当作停止证据。
        elif (scene / 'generations' / str(generation) / name).exists():
            recorded = None  # 指针缺失或不匹配但有日志：无法核验归属。
        if recorded is None and binding is None:
            for member in members:
                evidence[kind][member] = 'unknown'
            continue
        def valid_record(item):
            return (isinstance(item, dict) and type(item.get('pid')) is int and item['pid'] > 0
                    and isinstance(item.get('argv'), list)
                    and isinstance(item.get('start_identity'), str) and item['start_identity'])
        if isinstance(recorded, dict) and any(not valid_record(item) for item in recorded.values()):
            # 记录畸形时不能信任成员清单：该侧整体按 unknown 处理。
            for member in members:
                evidence[kind][member] = 'unknown'
            continue
        for member in members:
            expected = recorded.get(member) if isinstance(recorded, dict) else None
            if expected is None:
                evidence[kind][member] = 'stopped' if recorded is not None else 'unknown'
                continue
            observed = inspect(member, dict(expected))
            evidence[kind][member] = {'absent': 'stopped', 'live': 'live'}.get(observed.get('status'), 'unknown')
        if kind == 'nodes' and binding is not None:
            for member in members:
                if evidence[kind][member] != 'stopped':
                    continue
                sockets = binding['nodes'][member].get('sockets')
                if sockets is None:
                    continue  # 未接续的停止态资产没有 socket 绑定，也无从可达。
                endpoint = Path(sockets) / 'qmp.sock'
                if qmp_query(endpoint, connect=qmp_connect) is not None:
                    evidence[kind][member] = 'live'
    return evidence


def _validated_binding(root, instance_uuid, generation):
    """读取指针激活的准备记录并核对指针摘要；返回场景根与绑定。"""
    scene = _private_tree(root, root / 'scenarios' / instance_uuid)
    pointer_path = scene / 'active-generation.json'
    _require(pointer_path.exists() and not pointer_path.is_symlink(), '活动指针缺失或非法')
    pointer = _read_binding(pointer_path)
    _require(pointer.get('descriptor') == 'prepared.json' and pointer.get('generation') == generation,
             '准备记录未激活或代次不匹配')
    binding = _read_binding(scene / 'generations' / str(generation) / 'prepared.json')
    _require(binding.get('instance_uuid') == instance_uuid
             and binding.get('generation') == generation
             and _digest(binding) == pointer.get('binding_digest'), '准备记录完整性不匹配')
    return scene, binding


def _validated_journal(path, instance_uuid, generation, binding, allowed_stop_states):
    """核验接管目标的日志绑定与状态；返回最后事件。"""
    events = read_events(path)
    _require(events, '生命周期日志缺失；不能推断没有进程')
    digest = _digest(binding)
    allowed = {'prepared', 'starting', 'nodes-ready', 'networks-ready', 'degraded',
               'stopping', 'stop-pending', 'stopped'}
    for event in events:
        _require(event.get('instance_uuid') == instance_uuid and event.get('generation') == generation
                 and event.get('binding_digest') == digest and event.get('state') in allowed,
                 '生命周期日志绑定错误')
    last = events[-1]
    _require(last['state'] in allowed_stop_states, f"状态 {last['state']} 禁止接管停止")
    _require(not last.get('pending'), '存在不明启动窗口；必须恢复核验')
    return last


def stop_recovered_nodes(state_root, instance_uuid, *, generation, inspect, powerdown,
                         timeout_per_node, clock=time.monotonic, pause=time.sleep):
    """重开后按日志身份接管三节点正常关机；锁序为全局→场景→排序节点锁。

    只对身份/命令行/启动身份均核验存活的节点请求 ACPI 关机；已退出节点跳过，
    身份失配或不明启动窗口直接拒绝。每节点独立截止时间，超时进入 stop-pending，
    不强杀、不重复发送已记录的关机请求、不触碰网络服务或预约。
    """
    _require(type(generation) is int and generation > 0, '接管代次错误')
    _require(type(timeout_per_node) in (int, float) and math.isfinite(timeout_per_node)
             and 0 < timeout_per_node <= 600, '无效节点关机截止时间')
    root = Path(state_root)
    global_lock = _resource_lock(root / 'scenario-resources.lock')
    try:
        scene, binding = _validated_binding(root, instance_uuid, generation)
        path = scene / 'generations' / str(generation) / 'node-lifecycle.jsonl'
        last = _validated_journal(path, instance_uuid, generation, binding,
                                  {'nodes-ready', 'degraded', 'stop-pending'})
        stop_order = binding['manifest']['lifecycle']['stop_order']
        _require(set(last.get('stop_requested') or []) <= set(binding['nodes']), '节点日志关机记录非法')
        scene_lock = _resource_lock(scene / 'scenario.lock')
        locks = []
        try:
            locks = [_resource_lock(Path(binding['nodes'][key]['runtime']) / 'node.lock')
                     for key in sorted(binding['nodes'])]
            live = {}
            for key, expected in last['processes'].items():
                observed = inspect(key, dict(expected))
                if observed == {'status': 'absent'}:
                    continue
                _require(observed == dict(expected, status='live'), '节点身份失配或不明归属；要求恢复核验')
                live[key] = expected
            stop_requested = list(last.get('stop_requested') or [])

            def record(state):
                append_event(path, {'schema': 1, 'instance_uuid': instance_uuid,
                    'generation': generation, 'binding_digest': _digest(binding), 'state': state,
                    'processes': dict(last['processes']), 'pending': [],
                    'stop_requested': list(stop_requested)})

            record('stopping')
            for key in stop_order:
                if key not in live:
                    continue
                deadline = clock() + timeout_per_node
                expected = live[key]
                if key not in stop_requested:
                    stop_requested.append(key)
                    record('stopping')
                    powerdown(key, None, dict(expected))
                observed = inspect(key, dict(expected))
                while observed != {'status': 'absent'}:
                    _require(observed == dict(expected, status='live'), '等待关机时节点归属变化')
                    if clock() >= deadline:
                        record('stop-pending')
                        return False  # 保留其余节点与双网，不自动强杀。
                    pause(min(0.05, max(0, deadline - clock())))
                    observed = inspect(key, dict(expected))
            record('stopped')
            return True
        finally:
            for lock in reversed(locks):
                lock.close()
            scene_lock.close()
    finally:
        global_lock.close()


def stop_recovered_services(state_root, instance_uuid, *, generation, available_capabilities, inspect,
                            signal_process, nodes_stopped, timeout, clock=time.monotonic,
                            pause=time.sleep):
    """重开后按日志身份接管双网服务正常停止；锁序为全局→场景。

    必须由可信外层先证明三节点已停止；只对身份核验存活的服务发送一次
    终止请求（inner→outer），超时进入 stop-pending，不强杀、不释放预约。
    signal_process 默认 SIGTERM；身份失配或不明窗口直接拒绝。
    """
    _require(type(generation) is int and generation > 0, '接管代次错误')
    _require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 600,
             '无效服务停止截止时间')
    _require(callable(nodes_stopped) and nodes_stopped() is True, '节点未证明全部停止；禁止停网络')
    root = Path(state_root)
    global_lock = _resource_lock(root / 'scenario-resources.lock')
    try:
        active = active_reservations(root)
        scene, binding = _validated_binding(root, instance_uuid, generation)
        specs = network_server_specs(binding['manifest'], instance_uuid, generation=generation,
                                    state_root=root, available_capabilities=available_capabilities)
        _validate_reservation(binding, root, specs, active)
        path = scene / 'generations' / str(generation) / 'network-lifecycle.jsonl'
        last = _validated_journal(path, instance_uuid, generation, binding,
                                  {'networks-ready', 'degraded', 'stop-pending'})
        _require(set(last.get('stop_requested') or []) <= set(specs), '服务日志停止记录非法')
        scene_lock = _resource_lock(scene / 'scenario.lock')
        try:
            _require(active_reservations(root) == active, '接管期间预约变化；重新核验')
            live = {}
            for key, expected in last['processes'].items():
                observed = inspect(key, dict(expected))
                if observed == {'status': 'absent'}:
                    continue
                _require(observed == dict(expected, status='live'), '服务身份失配或不明归属；要求恢复核验')
                live[key] = expected
            stop_requested = list(last.get('stop_requested') or [])

            def record(state):
                append_event(path, {'schema': 1, 'instance_uuid': instance_uuid,
                    'generation': generation, 'token': binding['reservation_token'],
                    'binding_digest': _digest(binding), 'state': state,
                    'processes': dict(last['processes']), 'pending': [],
                    'stop_requested': list(stop_requested)})

            def send_signal(pid):
                if signal_process is None:
                    os.kill(pid, signal.SIGTERM)
                else:
                    signal_process(pid)

            record('stopping')
            for key in ('inner', 'outer'):
                if key not in live:
                    continue
                expected = live[key]
                if key not in stop_requested:
                    stop_requested.append(key)
                    record('stopping')
                    send_signal(expected['pid'])
            deadline = clock() + timeout
            while True:
                states = {key: inspect(key, dict(expected)) for key, expected in live.items()}
                _require(all(value == {'status': 'absent'}
                             or value == dict(expected, status='live')
                             for key, expected in live.items() for value in [states[key]]),
                         '等待服务退出时归属变化')
                if all(value == {'status': 'absent'} for value in states.values()):
                    record('stopped')
                    return True
                if clock() >= deadline:
                    record('stop-pending')
                    return False  # 保留现场，不升级为强杀。
                pause(min(0.05, max(0, deadline - clock())))
        finally:
            scene_lock.close()
    finally:
        global_lock.close()
