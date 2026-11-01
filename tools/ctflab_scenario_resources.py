"""场景资源准备与可信绑定；只创建派生资产，不启动网络服务或 VM。"""
from __future__ import annotations

import fcntl
import ipaddress
import math
import os
from pathlib import Path
import socket
import stat
import time

from ctflab_scenario import ScenarioError, _path, _require, network_server_specs


def _private_directory(path):
    """逐级拒绝链接；仅创建缺失目录，不修正已有目录权限。"""
    path = Path(_path(path))
    for component in [*reversed(path.parents), path]:
        _require(not component.is_symlink(), "状态路径禁止符号链接")
        if not component.exists():
            component.mkdir(mode=0o700)
        info = component.lstat()
        _require(stat.S_ISDIR(info.st_mode), "状态路径必须为目录")
    info = path.lstat()
    _require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
             "状态目录必须属于当前用户且权限为 0700")
    return path


class PreparedNetworks:
    """持有监听 FD 和全局/交接后的场景锁；close 仅释放本对象资源。"""

    def __init__(self, specs, listeners, lock):
        self.specs, self.listeners, self.lock = specs, listeners, lock
        self.closed = False

    @property
    def ports(self):
        _require(not self.closed, "准备资源已关闭")
        return {key: value.getsockname()[1] for key, value in self.listeners.items()}

    def close(self):
        if not self.closed:
            for listener in self.listeners.values():
                listener.close()
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_UN)
            self.lock.close()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def prepare_network_resources(manifest, instance_uuid, *, generation, state_root,
                              host_routes, available_capabilities=()):
    """调用方提供当前 IPv4 路由 CIDR 快照；缺失或冲突即拒绝。

    排除默认路由；其他路由（含 VPN/直连网）不得与场景网段重叠。
    不启动服务，监听 FD 必须由后续可信编排器通过 pass_fds 交接。
    """
    specs = network_server_specs(manifest, instance_uuid, generation=generation,
                                 state_root=state_root, available_capabilities=available_capabilities)
    _require(isinstance(host_routes, (list, tuple)), "必须提供宿主路由快照")
    try:
        routes = [ipaddress.IPv4Network(value, strict=False) for value in host_routes]
    except (ValueError, TypeError) as exc:
        raise ScenarioError("无效宿主路由快照") from exc
    for spec in specs.values():
        _require(not any(route.prefixlen and route.overlaps(spec['config'].subnet) for route in routes),
                 "场景网段与宿主路由冲突")
    root = _private_directory(state_root)
    lock_path = root / 'scenario-resources.lock'
    lock = _resource_lock(lock_path)
    listeners = {}
    try:
        pointer_path = root / 'scenarios' / instance_uuid / 'active-generation.json'
        if pointer_path.exists() or pointer_path.is_symlink():
            from ctflab_scenario_services import _read_binding
            pointer = _read_binding(pointer_path)
            _require(type(pointer.get('generation')) is int and pointer['generation'] == generation
                     and pointer.get('descriptor') == 'prepared.json',
                     '活动代次已变化或重置资产待接续；禁止旧代次/未接续资产预约')
        # 网络独立切片保留全局锁；完整准备入口会交接到场景锁。
        for spec in specs.values():
            relative = spec['state_path'].parent.relative_to(root)
            current = root
            for part in relative.parts:
                current = _private_directory(current / part)
            _require(not spec['state_path'].exists() and not spec['state_path'].is_symlink(),
                     "已有网络记录需要恢复核验，禁止覆盖")
        for network_id in specs:
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listeners[network_id] = listener
            listener.bind(('127.0.0.1', 0))
            listener.listen(8)
            listener.set_inheritable(False)
        return PreparedNetworks(specs, listeners, lock)
    except BaseException:
        for listener in listeners.values():
            listener.close()
        lock.close()
        raise


def wait_network_ready(prepared, *, observe, owned_process, timeout, clock=time.monotonic,
                       pause=time.sleep):
    """合成可注入就绪门槛。observe 返回新鲜记录；owned_process 核验启动身份。

    None 表示尚未就绪；已出现的错误绑定立即失败。失败不终止任何进程，
    不自动关闭可能已交接的 FD，调用方保留现场并决定释放未使用预约。
    """
    _require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 600, "无效就绪截止时间")
    ports = prepared.ports
    deadline = clock() + timeout
    while True:
        ready = set()
        for network_id, spec in prepared.specs.items():
            record = observe(network_id)
            if record is None:
                continue
            config = spec['config']
            expected = dict(schema=1, instance_uuid=spec['instance_uuid'],
                            network_id=network_id, generation=spec['generation'],
                            port=ports[network_id], endpoint=f"tcp://127.0.0.1:{ports[network_id]}",
                            cidr=config.cidr, server_ip=config.server_ip, server_mac=config.server_mac,
                            subnet_mask=str(config.subnet.netmask), broadcast=str(config.subnet.broadcast_address),
                            pool=[config.pool_start, config.pool_end], registered_only=True,
                            static_leases=spec['static_leases'])
            _require(isinstance(record, dict) and all(type(record.get(key)) is type(value)
                     and record[key] == value for key, value in expected.items()), "网络就绪绑定或 DHCP 配置不匹配")
            _require(type(record.get('pid')) is int and record['pid'] > 0
                     and owned_process(network_id, record['pid']), "网络进程退出或启动身份不匹配")
            ready.add(network_id)
        if ready == set(prepared.specs):
            return {key: ports[key] for key in ready}
        _require(clock() < deadline, "等待双网就绪超时；保留部分就绪现场")
        pause(min(0.05, max(0, deadline - clock())))


def _private_tree(root, target):
    """逐层验证受控根内目录，不能只验证最终叶目录。"""
    current = _private_directory(root)
    for part in Path(target).relative_to(current).parts:
        current = _private_directory(current / part)
    return current


def _resource_lock(path):
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    lock = os.fdopen(descriptor, 'r+')
    try:
        info = os.fstat(descriptor)
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                 and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1,
                 '资源锁归属或权限错误')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock
    except BaseException:
        lock.close()
        raise


def _verified_file(path, digest):
    """只读核验普通文件；拒绝链接、硬链接和核验期间变化。"""
    import hashlib
    path = Path(_path(path))
    for component in [*path.parents, path]:
        _require(not component.is_symlink(), '资产路径禁止符号链接')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as source:
        before = os.fstat(source.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size > 0,
                 '资产必须为非空普通单链接文件')
        actual = hashlib.sha256()
        for block in iter(lambda: source.read(1024 * 1024), b''):
            actual.update(block)
        after = os.fstat(source.fileno())
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    _require(identity(before) == identity(after) == identity(path.stat()), '资产核验期间变化')
    _require(actual.hexdigest() == digest, '资产 SHA-256 不匹配')
    return path


def fresh_routes(collect, *, clock=time.monotonic, max_age=2):
    """采集器返回 routes/observed_at；只接受本次调用窗口内的单调时钟快照。"""
    _require(type(max_age) in (int, float) and math.isfinite(max_age) and 0 < max_age <= 10,
             '无效路由新鲜度门槛')
    start = clock()
    snapshot = collect()
    end = clock()
    _require(isinstance(snapshot, dict) and set(snapshot) == {'routes', 'observed_at'}, '无效路由采集结果')
    observed = snapshot['observed_at']
    _require(type(observed) in (int, float) and math.isfinite(observed)
             and start <= observed <= end and end - observed <= max_age, '宿主路由快照过期或时钟错误')
    _require(isinstance(snapshot['routes'], (list, tuple)), '无效宿主路由快照')
    return snapshot['routes']


class OwnedNetworkProcesses:
    """仅绑定本编排器实际取得的 Popen 对象；不接收状态文件中的 PID 作为授权。"""

    def __init__(self, prepared):
        self.prepared = prepared
        self.bindings = {}

    def bind(self, network_id, process, *, expected_args):
        _require(network_id in self.prepared.specs and network_id not in self.bindings, '未知或重复进程绑定')
        _require(isinstance(expected_args, (list, tuple)) and expected_args
                 and process.args == list(expected_args) and type(process.pid) is int and process.pid > 0
                 and process.poll() is None, '启动对象或参数不匹配')
        self.bindings[network_id] = (process, tuple(expected_args))

    def wait_ready(self, *, timeout):
        return wait_network_ready(self.prepared, observe=self.observe,
                                  owned_process=self.owned, timeout=timeout)

    def owned(self, network_id, pid):
        binding = self.bindings.get(network_id)
        if binding is None:
            return False
        process, args = binding
        return (not self.prepared.closed and type(pid) is int and pid == process.pid
                and process.args == list(args) and process.poll() is None)

    def observe(self, network_id):
        """每次重新读私有记录；不缓存旧代次，不跟随链接。"""
        import json
        path = self.prepared.specs[network_id]['state_path']
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, 'r') as source:
            info = os.fstat(source.fileno())
            _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                     and info.st_nlink == 1 and info.st_size <= 1024 * 1024,
                     '网络记录归属或类型错误')
            try:
                return json.load(source)
            except (ValueError, UnicodeError) as exc:
                raise ScenarioError('网络记录损坏；保留现场') from exc


def prepare_scenario_resources(manifest, instance_uuid, *, generation, state_root,
                               socket_root, assets, firmware, qemu_img, collect_routes,
                               available_capabilities=(), run=None, reserve_bytes=64 * 1024 * 1024):
    """准备派生资产和双网 FD，不启动 VM/服务。失败保留派生现场，拒绝覆盖重试。

    assets 为 asset_id→基盘路径，firmware 为节点→code/vars 路径及各自 sha256。
    采集器和 qemu-img 路径必须由可信宿主调用方给出，不来自在线元数据。
    """
    import json
    import shutil
    import subprocess
    from ctflab_scenario import instance_plan, qemu_command
    plan = instance_plan(manifest, instance_uuid, available_capabilities=available_capabilities)
    manifest = plan['manifest']
    _require(set(assets) == set(manifest['assets']), '基盘绑定不完整')
    uefi = {key for key, node in manifest['nodes'].items() if node['firmware'] == 'uefi'}
    _require(set(firmware) == uefi, '固件绑定不完整')
    bases = {key: _verified_file(assets[key], spec['sha256']) for key, spec in manifest['assets'].items()}
    firm = {}
    for key, spec in firmware.items():
        _require(set(spec) == {'code', 'vars', 'code_sha256', 'vars_sha256'}, '固件绑定字段错误')
        firm[key] = {role: _verified_file(spec[role], spec[role + '_sha256']) for role in ('code', 'vars')}
    _require(type(reserve_bytes) is int and reserve_bytes >= 64 * 1024 * 1024, '空间预约过小')
    image_tool = _path(qemu_img)
    def execute(args):
        result = (run or subprocess.run)(args, capture_output=True, text=True, check=True, timeout=60)
        return result.stdout
    for base in bases.values():
        info = json.loads(execute([image_tool, 'info', '--output=json', str(base)]))
        _require(info.get('format') == 'qcow2' and not info.get('backing-filename')
                 and not info.get('full-backing-filename') and not info.get('data-file'),
                 '基盘必须为独立 QCOW2')
    routes = fresh_routes(collect_routes)
    prepared = prepare_network_resources(manifest, instance_uuid, generation=generation,
        state_root=state_root, host_routes=routes, available_capabilities=available_capabilities)
    try:
        root = Path(state_root)
        scenario_root = root / plan['namespace']
        scenario_lock = _resource_lock(scenario_root / 'scenario.lock')
        try:
            sockets = _private_directory(socket_root)
            needed = reserve_bytes + sum(paths['vars'].stat().st_size for paths in firm.values())
            _require(shutil.disk_usage(root).free >= needed, '派生资产空间不足')
            nodes = {}
            for key in manifest['nodes']:
                runtime = scenario_root / 'generations' / str(generation) / 'nodes' / key
                endpoint = sockets / instance_uuid / str(generation) / key
                # 参数生成同时检查 UNIX socket 路径上限，写磁盘前拒绝。
                qemu_command(manifest, instance_uuid, key, generation=generation,
                    state_root=root, socket_root=sockets, network_ports=prepared.ports,
                    qemu_binary='/usr/bin/true', firmware_code=firm.get(key, {}).get('code'),
                    available_capabilities=available_capabilities)
                _require(not runtime.exists() and not runtime.is_symlink()
                         and not endpoint.exists() and not endpoint.is_symlink(), '已有节点现场禁止覆盖')
                nodes[key] = (runtime, endpoint)
            from ctflab_scenario_registry import reserve_prepared
            reservation_token = reserve_prepared(prepared, manifest, nodes, state_root=root)
            for key, (runtime, endpoint) in nodes.items():
                _private_tree(root, runtime)
                _private_tree(sockets, endpoint)
                base = bases[manifest['nodes'][key]['asset']]
                overlay = runtime / 'overlay.qcow2'
                execute([image_tool, 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', str(base), str(overlay)])
                overlay.chmod(0o600)
                info = json.loads(execute([image_tool, 'info', '--output=json', str(overlay)]))
                _require(info.get('format') == 'qcow2' and info.get('full-backing-filename') == str(base)
                         and info.get('backing-filename-format') == 'qcow2', 'overlay backing 绑定错误')
                if key in firm:
                    with firm[key]['vars'].open('rb') as source, (runtime / 'nvram.fd').open('xb') as target:
                        os.chmod(target.name, 0o600)
                        shutil.copyfileobj(source, target)
                    _verified_file(runtime / 'nvram.fd', firmware[key]['vars_sha256'])
            # 准备期间再次采集，防止耗时资产操作后使用过期或新增冲突路由。
            latest = fresh_routes(collect_routes)
            for spec in prepared.specs.values():
                _require(not any(ipaddress.IPv4Network(route, strict=False).prefixlen
                         and ipaddress.IPv4Network(route, strict=False).overlaps(spec['config'].subnet)
                         for route in latest), '场景网段与宿主路由冲突')
            for key, base in bases.items():
                _verified_file(base, manifest['assets'][key]['sha256'])
            for key, paths in firm.items():
                for role, path in paths.items():
                    _verified_file(path, firmware[key][role + '_sha256'])
            bindings = {'schema': 1, 'instance_uuid': instance_uuid, 'generation': generation,
                'status': 'assets-prepared', 'manifest': manifest, 'reservation_token': reservation_token,
                'assets': {key: {'path': str(base), 'sha256': manifest['assets'][key]['sha256']}
                           for key, base in bases.items()},
                'firmware': {key: {field: str(value) for field, value in spec.items()}
                             for key, spec in firmware.items()},
                'nodes': {key: {'runtime': str(runtime), 'sockets': str(endpoint)}
                          for key, (runtime, endpoint) in nodes.items()}, 'network_ports': prepared.ports}
            binding_path = scenario_root / 'generations' / str(generation) / 'prepared.json'
            with binding_path.open('x', encoding='utf-8') as target:
                os.chmod(target.name, 0o600)
                json.dump(bindings, target, ensure_ascii=False, sort_keys=True)
                target.flush()
                os.fsync(target.fileno())
            prepared.nodes, prepared.firmware = nodes, firm
            prepared.bindings, prepared.binding_path = bindings, binding_path
            global_lock = prepared.lock
            prepared.lock = scenario_lock
            global_lock.close()
            return prepared
        except BaseException:
            scenario_lock.close()
            raise
    except BaseException:
        prepared.close()
        raise


def parse_macos_routes(output):
    """解析 netstat -rn -f inet 的数字路由，未知行拒绝而不是静默漏掉 VPN。"""
    routes, in_table = [], False
    for line in output.splitlines():
        fields = line.split()
        if not fields or line.strip() in ('Routing tables', 'Internet:'):
            continue
        if fields[:3] == ['Destination', 'Gateway', 'Flags']:
            _require(not in_table, '重复 IPv4 路由表头')
            in_table = True
            continue
        _require(in_table and len(fields) >= 4, '无法解析宿主 IPv4 路由表')
        destination = fields[0]
        if destination == 'default':
            routes.append('0.0.0.0/0')
            continue
        try:
            address, separator, prefix = destination.partition('/')
            octets = address.split('.')
            _require(1 <= len(octets) <= 4 and all(part.isdigit() and 0 <= int(part) <= 255 for part in octets),
                     '无法解析宿主路由目的地址')
            mask = int(prefix) if separator else 8 * len(octets)
            expanded = '.'.join(octets + ['0'] * (4 - len(octets)))
            routes.append(str(ipaddress.IPv4Network(f'{expanded}/{mask}', strict=False)))
        except (ValueError, TypeError) as exc:
            raise ScenarioError('无法解析宿主路由目的地址') from exc
    _require(in_table and routes, '宿主 IPv4 路由表缺失或为空')
    return routes


def collect_macos_routes(*, run=None, clock=time.monotonic):
    """只读本机路由，不发探测包；采集失败闭锁。"""
    import subprocess
    result = (run or subprocess.run)(['/usr/sbin/netstat', '-rn', '-f', 'inet'],
        capture_output=True, text=True, check=True, timeout=5)
    return {'routes': parse_macos_routes(result.stdout), 'observed_at': clock()}
