"""Wintermute 场景 v1 静态契约；不执行进程、网络或文件写入。"""
from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import uuid

REQUIRED_CAPABILITIES = frozenset({"scenario-v1", "multi-nic", "isolated-dhcp-v1", "transactional-reset-v1"})
# 这里只描述可解析的契约，不能作为当前运行器的能力声明。
TOPOLOGY = {"kali": [("outer0", "outer")], "straylight": [("outer0", "outer"), ("inner0", "inner")], "neuromancer": [("inner0", "inner")]}


class ScenarioError(ValueError):
    """清单或运行资源不符合离线场景契约。"""


def _require(condition, message):
    if not condition:
        raise ScenarioError(message)


def _fields(value, keys):
    _require(isinstance(value, dict) and set(value) == set(keys.split()), f"字段必须为：{keys}")


def _integer(value, low, high):
    _require(type(value) is int and low <= value <= high, f"整数必须在 {low}..{high}")


def _identifier(value):
    _require(isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,47}", value), "无效逻辑标识")


def _text(value):
    _require(isinstance(value, str) and 0 < len(value) <= 512 and not any(c in value for c in "\x00\n\r"), "无效说明文字")
    _require(not value.startswith(("/", "~", "file:")) and not re.search(r"(?:password|ticket|token)=", value, re.I), "禁止宿主路径或凭据")


def _validate(manifest, available_capabilities):
    _fields(manifest, "schema scenario_id required_capabilities assets networks nodes policy lifecycle checks")
    _require(type(manifest["schema"]) is int and manifest["schema"] == 1, "不支持的场景 schema")
    _require(manifest["scenario_id"] == "wintermute", "v1 仅支持 wintermute")
    caps = manifest["required_capabilities"]
    _require(isinstance(caps, list) and all(isinstance(c, str) for c in caps) and len(caps) == len(set(caps)) and set(caps) == REQUIRED_CAPABILITIES, "能力声明不完整或未知")
    _require(REQUIRED_CAPABILITIES <= set(available_capabilities), "运行器能力不足；禁止降级")
    _fields(manifest["policy"], "internet host_forwards guest_management_nic")
    _require(manifest["policy"] == {"internet": False, "host_forwards": [], "guest_management_nic": False} and manifest["policy"]["internet"] is False and manifest["policy"]["guest_management_nic"] is False, "禁止 NAT、映射或管理网卡")
    assets = manifest["assets"]
    _require(isinstance(assets, dict) and len(assets) == 3, "需要三个基盘引用")
    for asset_id, asset in assets.items():
        _identifier(asset_id)
        _fields(asset, "sha256 source license profile hardware_verified")
        _require(isinstance(asset["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", asset["sha256"]), "无效基盘哈希")
        _text(asset["source"])
        _text(asset["license"])
        _identifier(asset["profile"])
        _require(type(asset["hardware_verified"]) is bool, "硬件验证标记必须是布尔值")
    networks = manifest["networks"]
    _fields(networks, "outer inner")
    subnets = []
    leases = {}
    for network_id, network in networks.items():
        _fields(network, "cidr server pool leases uplink gateway dns")
        _require(network["uplink"] == "none" and network["gateway"] is None and network["dns"] == [], "网络必须无出口、网关和 DNS")
        subnet = ipaddress.IPv4Network(network["cidr"], strict=True)
        _require(subnet.prefixlen == 24 and any(subnet.subnet_of(ipaddress.IPv4Network(block)) for block in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")), "只接受 RFC1918 IPv4 /24")
        _require(not any(subnet.overlaps(other) for other in subnets), "场景内网段重叠")
        subnets.append(subnet)
        server = ipaddress.IPv4Address(network["server"])
        def usable(address):
            return address in subnet and address not in (subnet.network_address, subnet.broadcast_address)
        _require(usable(server), "DHCP server 地址无效")
        _require(isinstance(network["pool"], list) and len(network["pool"]) == 2, "无效 DHCP 池")
        low, high = map(ipaddress.IPv4Address, network["pool"])
        _require(usable(low) and usable(high) and low <= high and not low <= server <= high, "DHCP 池范围无效")
        _require(isinstance(network["leases"], dict), "无效预约表")
        ips = set()
        for key, value in network["leases"].items():
            address = ipaddress.IPv4Address(value)
            _require(usable(address) and address != server and not low <= address <= high and address not in ips, "预约地址无效、重复或与动态池重叠")
            ips.add(address)
            leases[key] = network_id
    nodes = manifest["nodes"]
    _fields(nodes, "kali straylight neuromancer")
    used_assets, expected_leases, macs = set(), set(), set()
    for node_id, node in nodes.items():
        _fields(node, "asset architecture firmware disk_bus cpus memory_mb interfaces depends_on shutdown")
        _require(node["asset"] in assets and node["asset"] not in used_assets, "未知或重复基盘引用")
        used_assets.add(node["asset"])
        _integer(node["cpus"], 1, 8)
        _integer(node["memory_mb"], 256, 8192)
        _require(node["shutdown"] == "acpi", "不支持的关机策略")
        arch = node["architecture"]
        _require(arch in ("aarch64", "x86_64") and node["firmware"] in ("bios", "uefi") and node["disk_bus"] in ("ide", "virtio"), "不支持的硬件组合")
        _require(arch != "aarch64" or (node["firmware"] == "uefi" and node["disk_bus"] == "virtio"), "ARM 必须使用 UEFI/VirtIO")
        interfaces = node["interfaces"]
        _require(isinstance(interfaces, list) and len(interfaces) == len(TOPOLOGY[node_id]), "网卡数量错误")
        slots = set()
        for nic, (nic_id, network_id) in zip(interfaces, TOPOLOGY[node_id]):
            _fields(nic, "id network model pci_slot mac")
            _require((nic["id"], nic["network"]) == (nic_id, network_id), "NIC 顺序或网段错误")
            _require(nic["model"] in ("e1000", "e1000-82544gc", "e1000-82545em", "virtio-net-pci") and (arch != "aarch64" or nic["model"] == "virtio-net-pci"), "不支持的网卡模型")
            _integer(nic["pci_slot"], 5, 30)
            _require(nic["pci_slot"] not in slots and (not slots or nic["pci_slot"] > max(slots)), "PCI 顺序错误或重复")
            slots.add(nic["pci_slot"])
            mac = nic["mac"]
            _require(mac == "derived" or (isinstance(mac, str) and re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", mac) and int(mac[:2], 16) & 3 == 2), "MAC 必须为局部单播或 derived")
            if mac != "derived":
                _require(mac not in macs, "重复 MAC")
                macs.add(mac)
            key = f"{node_id}/{nic_id}"
            _require(leases.get(key) == network_id, "缺少或错误预约")
            expected_leases.add(key)
        deps = node["depends_on"]
        _require(isinstance(deps, list) and all(isinstance(d, str) and d in nodes and d != node_id for d in deps) and len(deps) == len(set(deps)), "无效依赖")
    _require(set(leases) == expected_leases, "存在非本场景租约")
    def visit(node_id, path):
        _require(node_id not in path, "循环依赖")
        for dep in nodes[node_id]["depends_on"]:
            visit(dep, path | {node_id})
    for node_id in nodes:
        visit(node_id, set())
    _require(sum(n["memory_mb"] for n in nodes.values()) <= 16384 and sum(n["cpus"] for n in nodes.values()) <= 16, "场景总资源超限")
    lifecycle = manifest["lifecycle"]
    _fields(lifecycle, "start_order stop_order startup_timeout_seconds shutdown_timeout_seconds failure reset")
    _require(lifecycle["start_order"] == ["neuromancer", "straylight", "kali"] and lifecycle["stop_order"] == ["kali", "straylight", "neuromancer"], "生命周期顺序错误")
    for node_id, node in nodes.items():
        _require(all(lifecycle["start_order"].index(dep) < lifecycle["start_order"].index(node_id) for dep in node["depends_on"]), "依赖与启动顺序冲突")
    _integer(lifecycle["startup_timeout_seconds"], 1, 600)
    _integer(lifecycle["shutdown_timeout_seconds"], 1, 600)
    _require(lifecycle["failure"] == "preserve" and lifecycle["reset"] == "stopped-atomic-preserve", "必须保留失败现场和重置备份")
    _fields(manifest["checks"], "boot address service isolation")
    # 第一个切片不执行探针，也不允许将猜测的服务写成已验证检查。
    _require(all(value == [] for value in manifest["checks"].values()), "v1 静态切片仅接受空检查列表")
    return copy.deepcopy(manifest)


def validate_manifest(manifest, *, available_capabilities=()):
    """严格校验并返回独立副本；能力必须由调用方明确提供。"""
    try:
        return _validate(manifest, available_capabilities)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        if isinstance(exc, ScenarioError):
            raise
        raise ScenarioError(f"无效场景清单：{exc}") from exc


def parse_manifest(text, *, available_capabilities=()):
    """解析 JSON 字符串；拒绝任意层级的重复键和非 JSON 常量。"""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, f"重复 JSON 字段：{key}")
            result[key] = value
        return result
    def invalid_constant(value):
        raise ScenarioError(f"禁止 JSON 常量：{value}")
    try:
        manifest = json.loads(text, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (ValueError, TypeError) as exc:
        raise ScenarioError(f"无效场景 JSON：{exc}") from exc
    return validate_manifest(manifest, available_capabilities=available_capabilities)


def instance_plan(manifest, instance_uuid, *, available_capabilities=()):
    """派生稳定 MAC/逻辑资源名称；不创建目录或交换机。"""
    manifest = validate_manifest(manifest, available_capabilities=available_capabilities)
    try:
        identity = str(uuid.UUID(instance_uuid))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ScenarioError("无效实例 UUID") from exc
    _require(identity == instance_uuid, "UUID 必须为规范形式")
    macs = set()
    for node_id, node in manifest["nodes"].items():
        for nic in node["interfaces"]:
            if nic["mac"] == "derived":
                digest = hashlib.sha256(f"{identity}/{node_id}/{nic['id']}".encode()).digest()
                nic["mac"] = ":".join(f"{byte:02x}" for byte in bytes([2]) + digest[:5])
            _require(nic["mac"] not in macs, "实例 MAC 碰撞")
            macs.add(nic["mac"])
    return {"instance_uuid": identity, "namespace": f"scenarios/{identity}", "manifest": manifest}


def _path(value):
    value = str(value)
    _require(Path(value).is_absolute() and not any(c in value for c in ",\x00\n\r") and ".." not in Path(value).parts, "运行路径必须绝对且不能注入 QEMU 选项")
    return value


def network_server_specs(manifest, instance_uuid, *, generation, state_root, available_capabilities=()):
    """将逻辑租约转为两个独立 DHCPServer 配置；不创建服务或预约端点。"""
    from ctflab_network import DHCPConfig

    plan = instance_plan(manifest, instance_uuid, available_capabilities=available_capabilities)
    _integer(generation, 1, 2**31 - 1)
    root = Path(_path(state_root)) / plan["namespace"] / "generations" / str(generation) / "networks"
    result = {}
    used_macs = {nic["mac"] for node in plan["manifest"]["nodes"].values() for nic in node["interfaces"]}
    for network_id, network in plan["manifest"]["networks"].items():
        digest = hashlib.sha256(f"{instance_uuid}/dhcp/{network_id}".encode()).digest()
        server_mac = ":".join(f"{byte:02x}" for byte in bytes([2]) + digest[:5])
        _require(server_mac not in used_macs, "DHCP server MAC 碰撞")
        used_macs.add(server_mac)
        leases = {}
        for key, address in network["leases"].items():
            node_id, nic_id = key.split("/")
            nic = next(nic for nic in plan["manifest"]["nodes"][node_id]["interfaces"] if nic["id"] == nic_id)
            leases[nic["mac"]] = address
        result[network_id] = {
            "config": DHCPConfig(network["cidr"], network["server"], *network["pool"], server_mac, True),
            "static_leases": leases,
            "state_path": root / network_id / "network.json",
            "instance_uuid": instance_uuid,
            "network_id": network_id,
            "generation": generation,
        }
    return result


def qemu_command(manifest, instance_uuid, node_id, *, generation, state_root, socket_root, network_ports, qemu_binary, firmware_code=None, available_capabilities=(), include_spice=True):
    """生成 argv。路径/端口为调用方的可信绑定；不核验存在、不预约或启动。

    include_spice=False 供无 SPICE 运行时的 headless 节点使用：省略 -spice 参数，
    显示证据由 QMP screendump 承担；QMP 绑定不变。默认行为不变。
    """
    _require(include_spice is True or include_spice is False, "include_spice 必须为布尔")
    plan = instance_plan(manifest, instance_uuid, available_capabilities=available_capabilities)
    _require(node_id in TOPOLOGY, "未知节点")
    _integer(generation, 1, 2**31 - 1)
    _fields(network_ports, "outer inner")
    for port in network_ports.values():
        _integer(port, 1024, 65535)
    _require(len(set(network_ports.values())) == 2, "两个网络不能共用端点")
    root, sockets = Path(_path(state_root)), Path(_path(socket_root))
    node = plan["manifest"]["nodes"][node_id]
    runtime = root / plan["namespace"] / "generations" / str(generation) / "nodes" / node_id
    endpoint = sockets / instance_uuid / str(generation) / node_id
    qmp, spice = str(endpoint / "qmp.sock"), str(endpoint / "spice.sock")
    socket_paths = (qmp,) if include_spice else (qmp, spice)
    _require(max(len(p.encode()) for p in socket_paths) <= 103, "UNIX socket 路径过长")
    command = [_path(qemu_binary), "-name", f"CTFLab-{instance_uuid}-{node_id}-g{generation}", "-nodefaults", "-machine", "virt" if node["architecture"] == "aarch64" else "pc", "-accel", "hvf" if node["architecture"] == "aarch64" else "tcg,thread=multi", "-cpu", "host" if node["architecture"] == "aarch64" else "max", "-smp", str(node["cpus"]), "-m", str(node["memory_mb"])]
    if node["firmware"] == "uefi":
        _require(firmware_code is not None, "UEFI 需要调用方提供只读固件")
        command += ["-drive", f"if=pflash,format=raw,unit=0,file={_path(firmware_code)},readonly=on", "-drive", f"if=pflash,format=raw,unit=1,file={runtime / 'nvram.fd'}"]
    else:
        _require(firmware_code is None, "BIOS 不接受固件路径")
    disk = runtime / "overlay.qcow2"
    if node["disk_bus"] == "virtio":
        command += ["-drive", f"file={disk},if=none,format=qcow2,id=disk0", "-device", "virtio-blk-pci,drive=disk0"]
    else:
        command += ["-drive", f"file={disk},if=ide,format=qcow2"]
    command += ["-net", "none", "-display", "none", "-monitor", "none", "-serial", "none", "-qmp", f"unix:{qmp},server=on,wait=off"]
    if include_spice:
        command += ["-spice", f"unix=on,addr={spice},disable-ticketing=on,disable-copy-paste=on,disable-agent-file-xfer=on"]
    command += ["-device", "virtio-gpu-pci" if node["architecture"] == "aarch64" else "VGA", "-device", "qemu-xhci", "-device", "usb-kbd", "-device", "usb-tablet"]
    for index, nic in enumerate(node["interfaces"]):
        command += ["-netdev", f"socket,id=nic{index},connect=127.0.0.1:{network_ports[nic['network']]}", "-device", f"{nic['model']},netdev=nic{index},mac={nic['mac']},addr=0x{nic['pci_slot']:x}"]
    return command
