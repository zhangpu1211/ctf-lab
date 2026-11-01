"""跨实例资源登记；追加历史，不自动释放不明占用或删除资产。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import uuid

from ctflab_scenario import ScenarioError, _require
from ctflab_scenario_resources import _private_directory, _private_tree, _resource_lock


def read_events(path):
    """只读取私有普通单链接记录；半行/损坏记录要求恢复，不跳过。"""
    path = Path(path)
    for component in [*path.parents, path]:
        _require(not component.is_symlink(), '登记路径禁止符号链接')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return []
    with os.fdopen(fd, 'r', encoding='utf-8') as source:
        info = os.fstat(source.fileno())
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                 and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
                 and info.st_size <= 8 * 1024 * 1024, '登记文件归属、权限或大小错误')
        events = []
        try:
            for line in source:
                _require(line.endswith('\n'), '登记尾部不完整；需要恢复')
                def unique(pairs):
                    result = {}
                    for key, value in pairs:
                        _require(key not in result, '登记 JSON 重复字段')
                        result[key] = value
                    return result
                event = json.loads(line, object_pairs_hook=unique,
                    parse_constant=lambda _value: (_ for _ in ()).throw(ScenarioError('登记常量非法')))
                _require(isinstance(event, dict) and type(event.get('sequence')) is int
                         and event['sequence'] == len(events) + 1, '登记事件序号错误')
                events.append(event)
        except ScenarioError:
            raise
        except (ValueError, UnicodeError) as exc:
            raise ScenarioError('登记记录损坏；需要恢复') from exc
        return events


def append_event(path, event):
    """调用方须持所属锁；写盘异常由上层闭锁，不抹除已写现场。"""
    path = Path(path)
    prior = read_events(path)
    event = dict(event, sequence=len(prior) + 1)
    data = (json.dumps(event, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n').encode()
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                 and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1,
                 '登记文件归属或权限错误')
        while data:
            written = os.write(fd, data)
            _require(written > 0, '登记写入失败')
            data = data[written:]
        os.fsync(fd)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.close(fd)
    return event


def active_reservations(root):
    active, seen = {}, set()
    for event in read_events(Path(root) / 'scenario-reservations.jsonl'):
        _require(type(event.get('schema')) is int and event['schema'] == 1 and event.get('action') in ('reserve', 'release'), '未知资源登记事件')
        token = event.get('token')
        _require(isinstance(token, str) and str(uuid.UUID(token)) == token, '资源登记 token 错误')
        if event['action'] == 'reserve':
            _require(token not in seen and set(event) == {'schema', 'action', 'token', 'reservation', 'sequence'},
                     '重复或非法资源预约')
            reservation = event['reservation']
            _require(isinstance(reservation, dict) and set(reservation) ==
                     {'instance_uuid', 'generation', 'macs', 'ports', 'paths'}, '资源预约字段错误')
            _require(str(uuid.UUID(reservation['instance_uuid'])) == reservation['instance_uuid']
                     and type(reservation['generation']) is int and reservation['generation'] > 0,
                     '资源预约实例或代次错误')
            for field in ('macs', 'ports', 'paths'):
                values = reservation[field]
                _require(isinstance(values, list) and values and len(values) == len(set(values)), '资源预约列表错误')
            _require(all(isinstance(mac, str) and len(mac.split(':')) == 6
                         and all(len(part) == 2 and all(c in '0123456789abcdef' for c in part)
                                 for part in mac.split(':')) and int(mac[:2], 16) & 3 == 2
                         for mac in reservation['macs']), '资源预约 MAC 错误')
            _require(all(type(port) is int and 1024 <= port <= 65535 for port in reservation['ports'])
                     and all(isinstance(path, str) and Path(path).is_absolute() and '..' not in Path(path).parts
                             for path in reservation['paths']), '资源预约端点错误')
            for current in active.values():
                _require(current['instance_uuid'] != reservation['instance_uuid']
                         and all(not set(current[field]) & set(reservation[field]) for field in ('macs', 'ports', 'paths')),
                         '登记存在重复占用；需要恢复')
            active[token] = reservation
            seen.add(token)
        else:
            _require(set(event) == {'schema', 'action', 'token', 'sequence'} and token in active,
                     '未知或重复资源释放')
            del active[token]
    return active


def _reject_unregistered_state(root, active):
    """固定层级检查旧代次现场；不能把旧资产/服务当成没有占用。"""
    scenarios = root / 'scenarios'
    registered = {(item['instance_uuid'], str(item['generation'])) for item in active.values()}
    # 已明确释放的历史代次也保留资产，不应重新占用；仅识别登记过的历史。
    for event in read_events(root / 'scenario-reservations.jsonl'):
        if event.get('action') == 'reserve':
            item = event['reservation']
            registered.add((item['instance_uuid'], str(item['generation'])))
    if not scenarios.exists():
        return
    def directory(path):
        info = path.lstat()
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                 and stat.S_IMODE(info.st_mode) == 0o700, '场景历史目录类型或权限错误')
    directory(scenarios)
    for scene in scenarios.iterdir():
        directory(scene)
        # 重置仅创建停止态资产；已提交/明确放弃的代次可识别为历史，
        # 不为其虚构网络端口或新的活跃预约。
        for event in read_events(scene / 'reset-lifecycle.jsonl'):
            _require(type(event.get('schema')) is int and event['schema'] == 1
                     and event.get('instance_uuid') == scene.name
                     and type(event.get('new_generation')) is int and event['new_generation'] > 0
                     and event.get('state') in ('reset-preparing', 'reset-ready', 'committed', 'aborted'),
                     '历史重置记录非法')
            if event['state'] in ('committed', 'aborted'):
                registered.add((scene.name, str(event['new_generation'])))
        generations = scene / 'generations'
        if not generations.exists():
            _require(not generations.is_symlink(), '场景历史路径禁止链接')
            continue
        directory(generations)
        for generation in generations.iterdir():
            directory(generation)
            if (scene.name, generation.name) in registered:
                continue
            prepared = generation / 'prepared.json'
            nodes = generation / 'nodes'
            networks = generation / 'networks'
            occupied = prepared.exists() or prepared.is_symlink() or nodes.exists() or nodes.is_symlink()
            if networks.exists():
                directory(networks)
                for network in networks.iterdir():
                    directory(network)
                    occupied |= any(network.iterdir())
            else:
                occupied |= networks.is_symlink()
            _require(not occupied, '存在未登记的历史场景现场；需要恢复，禁止自动迁移')


def reserve_prepared(prepared, manifest, nodes, *, state_root):
    """仅由完整准备入口在全局锁及场景锁均持有时调用。"""
    root = Path(state_root)
    info = os.fstat(prepared.lock.fileno())
    lock_info = (root / 'scenario-resources.lock').stat()
    _require((info.st_dev, info.st_ino) == (lock_info.st_dev, lock_info.st_ino), '预约必须持全局资源锁')
    spec = next(iter(prepared.specs.values()))
    macs = {nic['mac'] for node in manifest['nodes'].values() for nic in node['interfaces']}
    macs.update(network['config'].server_mac for network in prepared.specs.values())
    reservation = {'instance_uuid': spec['instance_uuid'], 'generation': spec['generation'],
        'macs': sorted(macs), 'ports': sorted(prepared.ports.values()),
        'paths': sorted([str(path) for pair in nodes.values() for path in pair]
                        + [str(network['state_path']) for network in prepared.specs.values()])}
    active = active_reservations(root)
    _reject_unregistered_state(root, active)
    for current in active.values():
        _require(current['instance_uuid'] != reservation['instance_uuid'], '实例已有未释放预约；需要恢复')
        for field in ('macs', 'ports', 'paths'):
            _require(not set(current[field]) & set(reservation[field]), f'跨实例 {field} 资源冲突')
    token = str(uuid.uuid4())
    append_event(root / 'scenario-reservations.jsonl',
                 {'schema': 1, 'action': 'reserve', 'token': token, 'reservation': reservation})
    prepared.reservation_token = token
    return token


def _release_locked(root, token, *, observe_stopped):
    """释放内核：调用方必须已持有全局→场景锁。

    observe_stopped 接收 {instance_uuid, generation}，返回不含 token 的停止证据；
    本函数核对后注入 token 再追加释放事件，不删除记录或资产。
    """
    active = active_reservations(root)
    _require(token in active, '预约不存在或已经释放')
    reservation = active[token]
    scenario = root / 'scenarios' / reservation['instance_uuid']
    _private_tree(root, scenario)
    evidence = observe_stopped({'instance_uuid': reservation['instance_uuid'],
                                'generation': reservation['generation']})
    expected = {'instance_uuid': reservation['instance_uuid'], 'generation': reservation['generation'],
                'nodes': {key: 'stopped' for key in ('kali', 'straylight', 'neuromancer')},
                'networks': {key: 'stopped' for key in ('outer', 'inner')}}
    _require(isinstance(evidence, dict) and {key: value for key, value in evidence.items()
             if key != 'token'} == expected, '所属资源未证明全部停止；保留预约')
    append_event(root / 'scenario-reservations.jsonl', {'schema': 1, 'action': 'release', 'token': token})
    return reservation


def release_reservation(state_root, token, *, observe_stopped):
    """可信调用方证明所有节点及网络停止后释放；锁顺序为全局→场景。

    调用前须结束持场景锁的会话。观察器必须重新核对资产/进程身份；
    本接口不探查 PID、不停止服务，不能以持久化 stopped 字样代替观察。
    """
    root = _private_directory(state_root)
    with _resource_lock(root / 'scenario-resources.lock'):
        active = active_reservations(root)
        _require(token in active, '预约不存在或已经释放')
        scenario = root / 'scenarios' / active[token]['instance_uuid']
        with _resource_lock(scenario / 'scenario.lock'):
            return _release_locked(root, token, observe_stopped=observe_stopped)
