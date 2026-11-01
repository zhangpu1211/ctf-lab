"""通用场景 v2 的离线校验与确定性计划；不执行进程、路由或磁盘写入。"""
from __future__ import annotations

import argparse
import copy
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sys
import uuid

MAX_BYTES = 1024 * 1024


class ScenarioError(ValueError):
    pass


def require(value, message):
    if not value:
        raise ScenarioError(message)


def fields(value, names):
    require(type(value) is dict and set(value) == set(names.split()), '字段缺失或存在未知字段')


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[a-z][a-z0-9-]{0,47}', value), '无效逻辑标识')


def integer(value, low, high):
    require(type(value) is int and low <= value <= high, '整数范围错误')


def text(value):
    require(isinstance(value, str) and 0 < len(value) <= 512 and not any(ord(c) < 32 for c in value), '说明文字无效')


def validate_manifest(value):
    """严格白名单；只允许隔离网络和静态地址，路由服务留待 S04。"""
    try:
        return _validate(value)
    except (TypeError, KeyError, AttributeError, ValueError, RecursionError) as exc:
        if isinstance(exc, ScenarioError):
            raise
        raise ScenarioError('场景字段类型或值无效') from None


def _validate(value):
    fields(value, 'schema scenario_id assets networks nodes policy')
    require(type(value['schema']) is int and value['schema'] == 2, '只接受场景 schema 2')
    identifier(value['scenario_id'])
    fields(value['policy'], 'internet host_forwards failure')
    require(value['policy']['internet'] is False and value['policy']['host_forwards'] == []
            and value['policy']['failure'] == 'preserve', '必须无默认出口并保留失败现场')
    assets, networks, nodes = (value[k] for k in ('assets', 'networks', 'nodes'))
    for collection, maximum in ((assets, 64), (networks, 16), (nodes, 32)):
        require(type(collection) is dict and 1 <= len(collection) <= maximum, '资源数量无效')
        for key in collection: identifier(key)
    for asset in assets.values():
        fields(asset, 'sha256 architecture source license verification')
        require(isinstance(asset['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', asset['sha256']), '资产哈希无效')
        require(asset['architecture'] in ('x86_64', 'aarch64'), '资产架构不支持')
        text(asset['source']); text(asset['license'])
        require(asset['verification'] in ('unverified', 'boot', 'service', 'course'), '验证等级无效')
    subnets = {}
    private = [ipaddress.IPv4Network(block) for block in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
    for key, network in networks.items():
        require(type(network) is dict and set(network) in ({'cidr', 'uplink'},
                                                           {'cidr', 'uplink', 'external'}), '字段缺失或存在未知字段')
        require(network['uplink'] == 'none', '网络必须无宿主出口')
        require(isinstance(network['cidr'], str), 'CIDR 必须为文字')
        subnet = ipaddress.IPv4Network(network['cidr'], strict=True)
        require(16 <= subnet.prefixlen <= 30 and any(subnet.subnet_of(p) for p in private), '仅支持 RFC1918 /16—/30')
        require(not any(subnet.overlaps(n) for n in subnets.values()), '网段重叠')
        subnets[key] = subnet
        from ctflab_external_attach import validate_network_external
        validate_network_external({'cidr': network['cidr'], **({'external': network['external']} if 'external' in network else {})})
    macs, addresses = set(), set()
    for key, node in nodes.items():
        required_node = set('asset cpus memory_mb firmware disk_bus interfaces depends_on'.split())
        require(type(node) is dict and required_node <= set(node) <= required_node | {'vmgenid'}, '字段缺失或存在未知字段')
        if 'vmgenid' in node:
            require(type(node['vmgenid']) is str and node['vmgenid'] == 'managed-generation-v1', '无效VMGenID声明')
        require(isinstance(node['asset'], str) and node['asset'] in assets, '未知资产')
        integer(node['cpus'], 1, 64); integer(node['memory_mb'], 256, 262144)
        require(node['firmware'] in ('bios', 'uefi') and node['disk_bus'] in ('ide', 'virtio', 'sata'), '硬件组合不支持')
        if 'vmgenid' in node:
            require(assets[node['asset']]['architecture'] == 'x86_64' and node['firmware'] == 'bios', 'VMGenID首版仅支持x86_64 BIOS/pc')
        if assets[node['asset']]['architecture'] == 'aarch64':
            require(node['firmware'] == 'uefi' and node['disk_bus'] == 'virtio', 'ARM 要求 UEFI/VirtIO')
        depends = node['depends_on']
        require(type(depends) is list and all(isinstance(d, str) and d in nodes and d != key for d in depends), '依赖引用错误')
        require(len(depends) == len(set(depends)), '重复依赖')
        interfaces = node['interfaces']
        require(type(interfaces) is list and 1 <= len(interfaces) <= 8, '网卡数量无效')
        names, attached = set(), set()
        for nic in interfaces:
            fields(nic, 'id network address mac model')
            identifier(nic['id']); require(nic['id'] not in names, '重复网卡标识'); names.add(nic['id'])
            require(isinstance(nic['network'], str) and nic['network'] in networks, '未知网段')
            require(nic['network'] not in attached, '同一节点重复接入网段'); attached.add(nic['network'])
            require(nic['model'] in ('e1000', 'virtio-net-pci'), '网卡模型不支持')
            if assets[node['asset']]['architecture'] == 'aarch64':
                require(nic['model'] == 'virtio-net-pci', 'ARM 要求 VirtIO 网卡')
            require(isinstance(nic['address'], str), '地址必须为文字')
            address = ipaddress.IPv4Address(nic['address']); subnet = subnets[nic['network']]
            require(address in subnet and address not in (subnet.network_address, subnet.broadcast_address), '地址不在可用网段')
            require(address not in addresses, '重复地址'); addresses.add(address)
            mac = nic['mac']
            require(mac == 'derived' or isinstance(mac, str) and re.fullmatch(r'02(?::[0-9a-f]{2}){5}', mac), 'MAC 必须为 derived 或本地单播地址')
            if mac != 'derived':
                require(mac not in macs, '重复 MAC'); macs.add(mac)
    # 外部槽位与节点地址/MAC全局查重；预留属于计划的一部分。
    for key, network in networks.items():
        slot = network.get('external')
        if not slot:
            continue
        require(ipaddress.IPv4Address(slot['address']) not in addresses, '外部预约地址与节点冲突')
        require(slot['mac'].lower() not in macs, '外部预约MAC与节点冲突')
    # 排序使用标识，避免对象插入顺序影响计划哈希和恢复顺序。
    order = []
    remaining = set(nodes)
    while remaining:
        ready = sorted(k for k in remaining if set(nodes[k]['depends_on']) <= set(order))
        require(ready, '节点依赖存在环')
        order.extend(ready); remaining.difference_update(ready)
    return copy.deepcopy(value)


def parse_manifest(raw):
    require(isinstance(raw, str), '场景必须为 JSON 文字')
    try:
        require(len(raw.encode('utf-8')) <= MAX_BYTES, '场景超过大小限制')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                require(key not in result, '重复 JSON 字段'); result[key] = value
            return result
        def invalid(_): raise ScenarioError('禁止非 JSON 常量')
        return validate_manifest(json.loads(raw, object_pairs_hook=unique, parse_constant=invalid))
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ScenarioError): raise
        raise ScenarioError('场景 JSON 无效') from None


def instance_plan(manifest, instance_uuid, *, generation=1):
    manifest = validate_manifest(manifest)
    integer(generation, 1, 2**31-1)
    try:
        require(str(uuid.UUID(instance_uuid)) == instance_uuid, '实例 UUID 非规范形式')
    except (ValueError, AttributeError, TypeError):
        raise ScenarioError('实例 UUID 无效') from None
    order = []
    nodes = manifest['nodes']
    while len(order) < len(nodes):
        order.extend(sorted(k for k in nodes if k not in order and set(nodes[k]['depends_on']) <= set(order)))
    macs = set()
    for key, node in nodes.items():
        for nic in node['interfaces']:
            if nic['mac'] == 'derived':
                digest = hashlib.sha256(f'{instance_uuid}/{key}/{nic["id"]}'.encode()).digest()
                nic['mac'] = ':'.join(f'{b:02x}' for b in b'\x02'+digest[:5])
            require(nic['mac'] not in macs, '实例 MAC 碰撞'); macs.add(nic['mac'])
    namespace = f'scenarios/{instance_uuid}/generations/{generation}'
    resources = {key: {'overlay': f'{namespace}/nodes/{key}/disk.qcow2',
                       'nvram': f'{namespace}/nodes/{key}/nvram.fd' if node['firmware'] == 'uefi' else None,
                       'asset_sha256': manifest['assets'][node['asset']]['sha256']}
                 for key, node in nodes.items()}
    result = {'schema': 2, 'instance_uuid': instance_uuid, 'generation': generation,
              'manifest': manifest, 'start_order': order, 'stop_order': list(reversed(order)),
              'resources': resources, 'runtime_verified': False, 'isolation_verified': False,
              'address_configuration': 'static-guest-configuration-required',
              'total_cpus': sum(n['cpus'] for n in nodes.values()),
              'total_memory_mb': sum(n['memory_mb'] for n in nodes.values())}
    result['plan_sha256'] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='通用场景 v2 离线计划，不启动 VM')
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--instance', required=True)
    parser.add_argument('--generation', type=int, default=1)
    args = parser.parse_args(argv)
    try:
        with args.manifest.open('rb') as source:
            raw = source.read(MAX_BYTES+1)
        require(len(raw) <= MAX_BYTES, '场景超过大小限制')
        plan = instance_plan(parse_manifest(raw.decode('utf-8')), args.instance, generation=args.generation)
        print(json.dumps(plan, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, UnicodeError, ScenarioError):
        print(json.dumps({'result':'failed', 'error':'场景读取或校验失败'}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
