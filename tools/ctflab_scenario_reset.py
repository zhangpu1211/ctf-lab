"""停止状态下的整场景派生资产重置事务与接续链；不启动、不删旧代次。"""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import uuid

from ctflab_scenario import ScenarioError, _path, _require, network_server_specs, validate_manifest
from ctflab_scenario_registry import (_release_locked, active_reservations, append_event, read_events,
                                      reserve_prepared)
from ctflab_scenario_resources import (PreparedNetworks, _private_directory, _private_tree,
                                       _resource_lock, _verified_file, fresh_routes)
from ctflab_scenario_services import _digest, _read_binding


def _scene(root, instance_uuid):
    _require(str(uuid.UUID(instance_uuid)) == instance_uuid, '实例 UUID 非规范形式')
    root = Path(_path(root))
    return root, _private_tree(root, root / 'scenarios' / instance_uuid)


def _stopped(binding, observe):
    evidence = observe(copy.deepcopy(binding))
    expected = {'instance_uuid': binding['instance_uuid'], 'generation': binding['generation'],
        'nodes': {key: 'stopped' for key in ('kali', 'straylight', 'neuromancer')},
        'networks': {key: 'stopped' for key in ('outer', 'inner')}}
    _require(evidence == expected and type(evidence.get('generation')) is int,
             '三节点/双网未证明停止或归属不明；禁止重置')


def _write_json(path, data):
    with path.open('x', encoding='utf-8') as target:
        os.chmod(target.name, 0o600)
        json.dump(data, target, sort_keys=True, ensure_ascii=False, allow_nan=False)
        target.flush()
        os.fsync(target.fileno())
    _sync_directory(path.parent)


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _pointer(binding, descriptor):
    return {'schema': 1, 'instance_uuid': binding['instance_uuid'], 'generation': binding['generation'],
            'descriptor': descriptor, 'binding_digest': _digest(binding)}


def _source(scene, pointer, capabilities):
    _require(set(pointer) == {'schema', 'instance_uuid', 'generation', 'descriptor', 'binding_digest'}
             and type(pointer['schema']) is int and pointer['schema'] == 1
             and pointer['instance_uuid'] == scene.name and type(pointer['generation']) is int
             and 0 < pointer['generation'] < 2**31
             and pointer['descriptor'] in ('prepared.json', 'reset-ready.json'), '活动代次指针非法')
    descriptor = scene / 'generations' / str(pointer['generation']) / pointer['descriptor']
    binding = _read_binding(descriptor)
    _require(binding.get('instance_uuid') == scene.name and binding.get('generation') == pointer['generation']
             and _digest(binding) == pointer['binding_digest'], '活动代次完整性不匹配')
    validate_manifest(binding['manifest'], available_capabilities=capabilities)
    _require(type(binding.get('generation')) is int and set(binding['assets']) == set(binding['manifest']['assets'])
             and set(binding['nodes']) == set(binding['manifest']['nodes']), '活动代次资产集合不完整')
    for key, item in binding['nodes'].items():
        _require(Path(item['runtime']) == scene / 'generations' / str(pointer['generation']) / 'nodes' / key,
                 '活动代次节点路径越界')
    uefi = {key for key, node in binding['manifest']['nodes'].items() if node['firmware'] == 'uefi'}
    _require(set(binding['firmware']) == uefi, '活动代次固件集合不完整')
    if pointer['descriptor'] == 'reset-ready.json':
        _require(binding.get('status') == 'reset-assets-ready' and isinstance(binding.get('inventory'), dict),
                 '重置完整性清单缺失')
        expected = {str(Path(item['runtime']) / 'overlay.qcow2') for item in binding['nodes'].values()}
        expected.update(str(Path(binding['nodes'][key]['runtime']) / 'nvram.fd') for key in binding['firmware'])
        _require(set(binding['inventory']) == expected, '重置资产完整性集合不匹配')
        generation_root = scene / 'generations' / str(pointer['generation'])
        for name, digest in binding['inventory'].items():
            path = Path(name)
            _require(path.is_relative_to(generation_root), '重置完整性路径越界')
            _verified_file(path, digest)
    return binding


def initialize_active_generation(state_root, instance_uuid, *, generation, available_capabilities, observe_stopped):
    """显式初始化活动指针；只用于未启用指针的完整准备代次。"""
    _require(type(generation) is int and 0 < generation < 2**31, '无效代次')
    root, scene = _scene(state_root, instance_uuid)
    with _resource_lock(root / 'scenario-resources.lock'), _resource_lock(scene / 'scenario.lock'):
        _require(not (scene / 'active-generation.json').exists()
                 and not (scene / 'active-generation.json').is_symlink(), '活动指针已存在；禁止重新初始化')
        binding = _read_binding(scene / 'generations' / str(generation) / 'prepared.json')
        _require(binding['instance_uuid'] == instance_uuid and binding['generation'] == generation
                 and type(binding['generation']) is int, '初始准备代次不匹配')
        validate_manifest(binding['manifest'], available_capabilities=available_capabilities)
        _require(binding['reservation_token'] in active_reservations(root), '初始预约失效')
        _stopped(binding, observe_stopped)
        pointer = _pointer(binding, 'prepared.json')
        _write_json(scene / 'active-generation.json', pointer)
        return pointer


def _prepare_assets(source, scene, new_generation, *, qemu_img, run, reserve_bytes):
    _require(type(reserve_bytes) is int and reserve_bytes >= 64 * 1024 * 1024, '准备空间余量不足')
    tool = _path(qemu_img)
    def execute(args):
        return (run or subprocess.run)(args, capture_output=True, text=True, check=True, timeout=60).stdout
    bases = {}
    for key, asset in source['assets'].items():
        _require(asset['sha256'] == source['manifest']['assets'][key]['sha256'], '基盘声明不一致')
        base = _verified_file(asset['path'], asset['sha256'])
        info = json.loads(execute([tool, 'info', '--output=json', str(base)]))
        _require(info.get('format') == 'qcow2' and not info.get('backing-filename')
                 and not info.get('full-backing-filename') and not info.get('data-file'), '基盘不是独立 QCOW2')
        bases[key] = base
    firmware = {}
    for key, spec in source['firmware'].items():
        firmware[key] = {role: _verified_file(spec[role], spec[role + '_sha256']) for role in ('code', 'vars')}
    needed = reserve_bytes + sum(item['vars'].stat().st_size for item in firmware.values())
    _require(shutil.disk_usage(scene).free >= needed, '派生资产空间不足')
    generation_root = scene / 'generations' / str(new_generation)
    _require(not generation_root.exists() and not generation_root.is_symlink(), '目标代次已有现场；禁止覆盖')
    _private_tree(scene, generation_root)
    nodes, inventory = {}, {}
    for key, node in source['manifest']['nodes'].items():
        runtime = _private_tree(scene, generation_root / 'nodes' / key)
        base = bases[node['asset']]
        overlay = runtime / 'overlay.qcow2'
        execute([tool, 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', str(base), str(overlay)])
        overlay.chmod(0o600)
        info = json.loads(execute([tool, 'info', '--output=json', str(overlay)]))
        _require(info.get('format') == 'qcow2' and info.get('full-backing-filename') == str(base)
                 and info.get('backing-filename-format') == 'qcow2', '新 overlay backing 不匹配')
        execute([tool, 'check', '--output=json', str(overlay)])
        if key in firmware:
            with firmware[key]['vars'].open('rb') as original, (runtime / 'nvram.fd').open('xb') as target:
                os.chmod(target.name, 0o600)
                shutil.copyfileobj(original, target)
                target.flush()
                os.fsync(target.fileno())
            _verified_file(runtime / 'nvram.fd', source['firmware'][key]['vars_sha256'])
        # 新代次只建立空租约目录，不复制旧 network.json/运行 PID/端口。
        nodes[key] = {'runtime': str(runtime)}
        with overlay.open('rb') as disk:
            os.fsync(disk.fileno())
        _sync_directory(runtime)
        for name in ('overlay.qcow2', 'nvram.fd'):
            artifact = runtime / name
            if artifact.exists():
                digest = hashlib.sha256()
                with artifact.open('rb') as source_file:
                    for block in iter(lambda: source_file.read(1024 * 1024), b''):
                        digest.update(block)
                inventory[str(artifact)] = digest.hexdigest()
    _sync_directory(generation_root / 'nodes')
    for key in ('outer', 'inner'):
        _private_tree(scene, generation_root / 'networks' / key)
        _sync_directory(generation_root / 'networks' / key)
    _sync_directory(generation_root / 'networks')
    for key, base in bases.items():
        _verified_file(base, source['assets'][key]['sha256'])
    for key, paths in firmware.items():
        for role, path in paths.items():
            _verified_file(path, source['firmware'][key][role + '_sha256'])
    candidate = {'schema': 1, 'instance_uuid': source['instance_uuid'], 'generation': new_generation,
        'status': 'reset-assets-ready', 'manifest': copy.deepcopy(source['manifest']),
        'assets': copy.deepcopy(source['assets']), 'firmware': copy.deepcopy(source['firmware']),
        'nodes': nodes, 'inventory': inventory, 'previous_generation': source['generation']}
    _write_json(generation_root / 'reset-ready.json', candidate)
    _sync_directory(generation_root.parent)
    return candidate


def reset_scenario_assets(state_root, instance_uuid, *, new_generation, available_capabilities,
                          observe_stopped, qemu_img, run=None, reserve_bytes=64 * 1024 * 1024,
                          replace=os.replace):
    """新代次完整准备后原子切换单一指针；失败保留全部现场，绝不 stop/启动。"""
    _require(type(new_generation) is int and 0 < new_generation < 2**31, '无效新代次')
    root, scene = _scene(state_root, instance_uuid)
    with _resource_lock(root / 'scenario-resources.lock'), _resource_lock(scene / 'scenario.lock'):
        pointer_path, journal = scene / 'active-generation.json', scene / 'reset-lifecycle.jsonl'
        old_pointer = _read_binding(pointer_path)
        source = _source(scene, old_pointer, available_capabilities)
        _require(new_generation > source['generation'], '新代次必须大于当前代次')
        events = read_events(journal)
        _require(not events or events[-1].get('state') in ('committed', 'aborted'), '已有未收口重置；先恢复核验')
        _stopped(source, observe_stopped)
        operation = str(uuid.uuid4())
        common = {'schema': 1, 'instance_uuid': instance_uuid, 'operation': operation,
                  'old': old_pointer, 'new_generation': new_generation}
        append_event(journal, dict(common, state='reset-preparing'))
        candidate = _prepare_assets(source, scene, new_generation, qemu_img=qemu_img,
                                    run=run, reserve_bytes=reserve_bytes)
        new_pointer = _pointer(candidate, 'reset-ready.json')
        append_event(journal, dict(common, state='reset-ready', new=new_pointer))
        # 变更指针前重新观察；长准备期间不能沿用旧停止证明。
        _stopped(source, observe_stopped)
        _require(_read_binding(pointer_path) == old_pointer, '准备期间活动指针变化；禁止提交')
        temporary = scene / ('active-generation.' + operation + '.pending.json')
        _write_json(temporary, new_pointer)
        replace(temporary, pointer_path)
        _sync_directory(scene)
        append_event(journal, dict(common, state='committed', new=new_pointer))
        return new_pointer


def audit_reset(state_root, instance_uuid, *, available_capabilities):
    """只读判定提交点；不自动写日志、回退指针或清理失败代次。"""
    root = Path(_path(state_root))
    _require(str(uuid.UUID(instance_uuid)) == instance_uuid, '实例 UUID 非规范形式')
    scene = root / 'scenarios' / instance_uuid
    pointer = _read_binding(scene / 'active-generation.json')
    _source(scene, pointer, available_capabilities)
    events = read_events(scene / 'reset-lifecycle.jsonl')
    if not events:
        return {'state': 'active-observed', 'generation': pointer['generation']}
    for event in events:
        _require(type(event.get('schema')) is int and event['schema'] == 1
                 and event.get('instance_uuid') == instance_uuid
                 and event.get('state') in ('reset-preparing', 'reset-ready', 'committed', 'aborted'), '重置日志非法')
    last = events[-1]
    if pointer == last.get('new') and last['state'] in ('reset-ready', 'committed'):
        state = 'committed-observed'  # 指针已切换，可能提交后日志写入中断。
    elif pointer.get('descriptor') == 'prepared.json' and last['state'] == 'committed' \
            and pointer.get('generation') == last.get('new_generation'):
        state = 'committed-observed'  # 提交后已接续运行资源：指针切换为同代次 prepared 描述。
    elif pointer == last.get('old') and last['state'] in ('reset-preparing', 'reset-ready', 'aborted'):
        state = 'old-active-preserved'
    else:
        state = 'recovery-required'
    _require(_read_binding(scene / 'active-generation.json') == pointer
             and read_events(scene / 'reset-lifecycle.jsonl') == events, '审计期间记录变化')
    return {'state': state, 'generation': pointer['generation']}


def recover_reset_transaction(state_root, instance_uuid, *, available_capabilities, observe_stopped):
    """显式收口中断事务：补记已提交或记为放弃；旧/失败代次全部保留。"""
    root, scene = _scene(state_root, instance_uuid)
    with _resource_lock(root / 'scenario-resources.lock'), _resource_lock(scene / 'scenario.lock'):
        report = audit_reset(root, instance_uuid, available_capabilities=available_capabilities)
        events = read_events(scene / 'reset-lifecycle.jsonl')
        _require(events and events[-1]['state'] not in ('committed', 'aborted'), '没有待收口的重置事务')
        _require(report['state'] in ('committed-observed', 'old-active-preserved'), '指针归属不明；禁止收口')
        pointer = _read_binding(scene / 'active-generation.json')
        source = _source(scene, pointer, available_capabilities)
        _stopped(source, observe_stopped)
        last = dict(events[-1])
        last.pop('sequence')
        last['state'] = 'committed' if report['state'] == 'committed-observed' else 'aborted'
        append_event(scene / 'reset-lifecycle.jsonl', last)
        return dict(report, transaction=last['state'])


def _pending_reset(scene, instance_uuid, available_capabilities):
    """读取待接续指针；仅接受 reset-ready 与未运行的 prepared 两种接续现场。"""
    pointer_path = scene / 'active-generation.json'
    pointer = _read_binding(pointer_path)
    if pointer.get('descriptor') not in ('reset-ready.json', 'prepared.json'):
        raise ScenarioError('活动指针非法；禁止接续')
    source = _source(scene, pointer, available_capabilities)
    events = read_events(scene / 'reset-lifecycle.jsonl')
    if pointer['descriptor'] == 'reset-ready.json':
        _require(events and events[-1].get('state') == 'committed'
                 and events[-1].get('new_generation') == pointer['generation'],
                 '重置事务未收口；先运行恢复核验')
    else:
        # 首次准备没有重置日志；已有日志时不得处于未收口事务中间。
        _require(not events or events[-1].get('state') in ('committed', 'aborted'),
                 '已有未收口重置事务；先运行恢复核验')
    generation_root = scene / 'generations' / str(pointer['generation'])
    for name in ('network-lifecycle.jsonl', 'node-lifecycle.jsonl'):
        _require(not (generation_root / name).exists() and not (generation_root / name).is_symlink(),
                 '新代次已有运行日志；请使用状态/恢复入口核验，禁止重新接续')
    return pointer_path, pointer, source


def resume_reset_resources(state_root, instance_uuid, *, available_capabilities, observe_stopped,
                           collect_routes, socket_root, replace=os.replace):
    """把已提交的重置资产接续为新代次运行预约；复用 overlay/NVRAM，不创建磁盘。

    覆盖两类现场：指针仍指向 reset-ready（先证明旧代次停止并释放旧预约），
    以及指针已切换但服务未及启动（证明本代次停止后重接预约并重写准备记录）。
    顺序：核验资产完整性 → 全局→场景锁 → 停止证明与预约处理 → 路由检查与
    监听 FD → 资源登记 → 写准备记录 → 原子切换活动指针。任一失败保留现场；
    成功后返回的 PreparedNetworks 持场景锁，可交给服务/节点会话。
    """
    root, scene = _scene(state_root, instance_uuid)
    pointer_path, pointer, source = _pending_reset(scene, instance_uuid, available_capabilities)
    generation = pointer['generation']
    old = None
    current_token = None
    if pointer['descriptor'] == 'reset-ready.json':
        previous = source['previous_generation']
        _require(type(previous) is int and 0 < previous < generation, '接续代次来源非法')
        old = _read_binding(scene / 'generations' / str(previous) / 'prepared.json')
        _require(old.get('instance_uuid') == instance_uuid and old.get('generation') == previous
                 and isinstance(old.get('reservation_token'), str), '旧代次准备记录缺失或不匹配')
    else:
        current_token = source.get('reservation_token')
        _require(isinstance(current_token, str), '已激活准备记录缺少预约身份')
    specs = network_server_specs(source['manifest'], instance_uuid, generation=generation,
                                state_root=root, available_capabilities=available_capabilities)
    sockets_root = _private_directory(socket_root)
    endpoints = {}
    for key in source['nodes']:
        endpoints[key] = sockets_root / instance_uuid / str(generation) / key
        _require(not endpoints[key].exists() or (endpoints[key].is_dir() and not any(endpoints[key].iterdir())),
                 '新代次 socket 现场已占用')
    listeners = {}
    global_lock = _resource_lock(root / 'scenario-resources.lock')
    try:
        scenario_lock = _resource_lock(scene / 'scenario.lock')
        try:
            active = active_reservations(root)
            known = {item['reservation_token'] for item in (old,) if item is not None}
            if current_token is not None:
                known.add(current_token)
            for token, reservation in active.items():
                if reservation['instance_uuid'] != instance_uuid:
                    continue
                if token == current_token:
                    continue  # 指针已激活但服务未启动的当前预约，由下方重接处理。
                _require(reservation['generation'] != generation,
                         '新代次已有未接续预约；先运行恢复核验')
                _require(token in known, '实例已有未知预约；需要恢复')
            if current_token is not None and current_token in active:
                # 指针已激活但服务未启动：先证明本代次全部停止才释放失效预约。
                _stopped(source, observe_stopped)
                _release_locked(root, current_token, observe_stopped=observe_stopped)
            if old is not None and old['reservation_token'] in active:
                # 接续前重新证明旧节点与双网已停止；失败即中止，不释放、不预约。
                _stopped(old, observe_stopped)
                _release_locked(root, old['reservation_token'], observe_stopped=observe_stopped)
            routes = fresh_routes(collect_routes)
            for spec in specs.values():
                _require(not any(ipaddress.IPv4Network(route, strict=False).prefixlen
                         and ipaddress.IPv4Network(route, strict=False).overlaps(spec['config'].subnet)
                         for route in routes), '场景网段与宿主路由冲突')
            try:
                for spec in specs.values():
                    _private_tree(root, spec['state_path'].parent)
                    _require(not spec['state_path'].exists() and not spec['state_path'].is_symlink(),
                             '新代次已有网络记录；禁止覆盖')
                    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    listeners[spec['network_id']] = listener
                    listener.bind(('127.0.0.1', 0))
                    listener.listen(8)
                    listener.set_inheritable(False)
                for key in source['nodes']:
                    _private_tree(sockets_root, endpoints[key])
                # 指针切换前在锁内复核资产完整性；接续完成后由运行状态接手，
                # 不再用停止态清单判断来宾合法写入。
                if pointer['descriptor'] == 'reset-ready.json':
                    for name, digest in source['inventory'].items():
                        _verified_file(name, digest)
                for key, spec in source['firmware'].items():
                    for role in ('code', 'vars'):
                        _verified_file(spec[role], spec[role + '_sha256'])
                prepared = PreparedNetworks(specs, listeners, global_lock)
                nodes = {key: (Path(source['nodes'][key]['runtime']), endpoints[key])
                         for key in source['nodes']}
                token = reserve_prepared(prepared, source['manifest'], nodes, state_root=root)
                bindings = {'schema': 1, 'instance_uuid': instance_uuid, 'generation': generation,
                    'status': 'assets-prepared', 'manifest': copy.deepcopy(source['manifest']),
                    'reservation_token': token, 'assets': copy.deepcopy(source['assets']),
                    'firmware': copy.deepcopy(source['firmware']),
                    'nodes': {key: {'runtime': str(runtime), 'sockets': str(endpoints[key])}
                              for key, (runtime, _endpoint) in nodes.items()},
                    'network_ports': prepared.ports}
                binding_path = scene / 'generations' / str(generation) / 'prepared.json'
                _commit_binding(binding_path, bindings, generation, instance_uuid, replace)
                _require(_read_binding(pointer_path) == pointer, '接续期间活动指针变化；禁止提交')
                new_pointer = _pointer(bindings, 'prepared.json')
                temporary = scene / ('active-generation.' + str(uuid.uuid4()) + '.pending.json')
                _write_json(temporary, new_pointer)
                replace(temporary, pointer_path)
                _sync_directory(scene)
                prepared.nodes = nodes
                prepared.firmware = {key: {role: Path(spec[role]) for role in ('code', 'vars')}
                                     for key, spec in source['firmware'].items()}
                prepared.bindings, prepared.binding_path = bindings, binding_path
                prepared.lock = scenario_lock
                global_lock.close()
                return prepared
            except BaseException:
                for listener in listeners.values():
                    listener.close()
                raise
        except BaseException:
            scenario_lock.close()
            raise
    except BaseException:
        global_lock.close()
        raise


def _commit_binding(binding_path, bindings, generation, instance_uuid, replace):
    """写接续准备记录；仅当既有记录可证明未激活且预约已消失时才原子替换。"""
    generation_root = binding_path.parent
    for name in ('network-lifecycle.jsonl', 'node-lifecycle.jsonl'):
        _require(not (generation_root / name).exists() and not (generation_root / name).is_symlink(),
                 '新代次已有运行日志；需要恢复核验')
    if binding_path.exists() or binding_path.is_symlink():
        stale = _read_binding(binding_path)
        _require(stale.get('instance_uuid') == instance_uuid and stale.get('generation') == generation
                 and stale.get('manifest') == bindings['manifest']
                 and stale.get('assets') == bindings['assets']
                 and stale.get('firmware') == bindings['firmware'], '既有准备记录与重置资产不匹配')
        _require(stale.get('reservation_token') not in active_reservations(binding_path.parents[4]),
                 '既有准备记录预约仍然活跃；先运行恢复核验')
        temporary = binding_path.parent / (binding_path.name + '.' + str(uuid.uuid4()) + '.pending')
        _write_json(temporary, bindings)
        replace(temporary, binding_path)
        _sync_directory(binding_path.parent)
        return
    _write_json(binding_path, bindings)


def recover_reset_continuation(state_root, instance_uuid, *, available_capabilities, observe_stopped):
    """释放接续中断遗留的新代次孤儿预约；不删除资产、不改变活动指针。

    指针指向 reset-ready 或未运行的 prepared 时，可证明新代次从无会话
    运行日志且可信观察确认全部停止，才释放不属于当前准备记录的孤儿预约；
    否则保留现场要求进一步恢复。
    """
    root, scene = _scene(state_root, instance_uuid)
    pointer = _read_binding(scene / 'active-generation.json')
    if pointer.get('descriptor') not in ('reset-ready.json', 'prepared.json'):
        return {'state': 'not-pending', 'generation': pointer.get('generation')}
    generation = pointer['generation']
    source = _source(scene, pointer, available_capabilities)
    keep = source.get('reservation_token') if pointer['descriptor'] == 'prepared.json' else None
    with _resource_lock(root / 'scenario-resources.lock'), _resource_lock(scene / 'scenario.lock'):
        active = active_reservations(root)
        orphans = [token for token, reservation in active.items()
                   if reservation['instance_uuid'] == instance_uuid
                   and reservation['generation'] == generation and token != keep]
        if not orphans:
            return {'state': 'no-orphan', 'generation': generation}
        _require(len(orphans) == 1, '新代次存在多个孤儿预约；需要人工恢复')
        generation_root = scene / 'generations' / str(generation)
        for name in ('network-lifecycle.jsonl', 'node-lifecycle.jsonl'):
            _require(not (generation_root / name).exists() and not (generation_root / name).is_symlink(),
                     '新代次已有运行日志；需要完整恢复核验')
        _stopped({'instance_uuid': instance_uuid, 'generation': generation}, observe_stopped)
        _release_locked(root, orphans[0], observe_stopped=observe_stopped)
        return {'state': 'orphan-released', 'generation': generation, 'token': orphans[0]}
