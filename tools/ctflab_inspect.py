#!/usr/bin/env python3
"""虚拟机镜像的只读探测与 CTFLab 候选配置生成。

这里的结论分为“事实”和“候选”。磁盘格式、容量、分区签名等可以直接观察；
客体架构、控制器和网卡在缺少 OVF 元数据时只能推断，必须保留置信度和警告。
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from typing import Any
import uuid
import xml.etree.ElementTree as ET


SUPPORTED_SUFFIXES = (".qcow2", ".vmdk", ".vdi", ".vhd", ".vhdx", ".raw", ".img")
EFI_SYSTEM_PARTITION = uuid.UUID("c12a7328-f81f-11d2-ba4b-00a0c93ec93b").bytes_le


class InspectionError(RuntimeError):
    """镜像探测失败。"""


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def qemu_info(path: Path) -> dict[str, Any]:
    qemu_img = shutil.which("qemu-img")
    if not qemu_img:
        raise InspectionError("未找到 qemu-img，请先安装 QEMU（brew install qemu）。")
    process = subprocess.run(
        [qemu_img, "info", "--output=json", str(path)],
        check=False,
        text=True,
        capture_output=True,
    )
    if process.returncode != 0:
        raise InspectionError(f"qemu-img 无法读取 {path}：{(process.stderr or process.stdout).strip()}")
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise InspectionError(f"qemu-img 返回了无法解析的 JSON：{path}") from exc


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def safe_tar_member(member: tarfile.TarInfo) -> bool:
    path = Path(member.name)
    return member.isfile() and not path.is_absolute() and ".." not in path.parts


def copy_tar_member(archive: tarfile.TarFile, member: tarfile.TarInfo, destination: Path) -> None:
    source = archive.extractfile(member)
    if source is None:
        raise InspectionError(f"无法读取 OVA 成员：{member.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source, destination.open("wb") as output:
        shutil.copyfileobj(source, output, length=8 * 1024 * 1024)


def find_disk_and_ovf(source: Path, temporary_dir: Path) -> tuple[Path, Path | None, list[str]]:
    warnings: list[str] = []
    if source.is_dir():
        disks = sorted(path for path in source.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES)
        ovfs = sorted(source.glob("*.ovf"))
        if not disks:
            raise InspectionError(f"目录中没有支持的虚拟磁盘：{source}")
        if len(disks) > 1:
            warnings.append(f"目录中发现 {len(disks)} 个磁盘，候选配置当前只使用第一个：{disks[0].name}")
        return disks[0], ovfs[0] if ovfs else None, warnings

    if source.suffix.lower() != ".ova":
        sibling_ovfs = sorted(source.parent.glob("*.ovf"))
        return source, sibling_ovfs[0] if len(sibling_ovfs) == 1 else None, warnings

    with tarfile.open(source, "r:*") as archive:
        unsafe = [member.name for member in archive.getmembers() if member.isfile() and not safe_tar_member(member)]
        if unsafe:
            raise InspectionError(f"OVA 含不安全路径：{unsafe[0]}")
        disks = [member for member in archive.getmembers() if safe_tar_member(member) and Path(member.name).suffix.lower() in SUPPORTED_SUFFIXES]
        ovfs = [member for member in archive.getmembers() if safe_tar_member(member) and Path(member.name).suffix.lower() == ".ovf"]
        if not disks:
            raise InspectionError(f"OVA 内没有支持的虚拟磁盘：{source}")
        if len(disks) > 1:
            warnings.append(f"OVA 内发现 {len(disks)} 个磁盘，候选配置当前只使用第一个：{disks[0].name}")
        disk_path = temporary_dir / Path(disks[0].name).name
        copy_tar_member(archive, disks[0], disk_path)
        ovf_path = None
        if ovfs:
            ovf_path = temporary_dir / Path(ovfs[0].name).name
            copy_tar_member(archive, ovfs[0], ovf_path)
        return disk_path, ovf_path, warnings


def parse_memory_mb(quantity: str | None, units: str | None) -> int | None:
    if not quantity:
        return None
    try:
        value = int(quantity)
    except ValueError:
        return None
    normalized = (units or "").lower().replace(" ", "")
    if "2^30" in normalized or "gigabyte" in normalized:
        return value * 1024
    if "2^10" in normalized or "kilobyte" in normalized:
        return max(1, value // 1024)
    return value


def parse_ovf(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        return {"warnings": [f"OVF 解析失败：{exc}"]}

    result: dict[str, Any] = {"source": str(path), "raw_hints": []}
    controllers: list[dict[str, str]] = []
    network_subtypes: list[str] = []
    disk_parents: list[str] = []
    for element in root.iter():
        name = local_name(element.tag)
        text = (element.text or "").strip()
        if name in {"VirtualSystemType", "Description", "Caption"} and text:
            result["raw_hints"].append(text)
        if name == "OperatingSystemSection":
            for key, value in element.attrib.items():
                if local_name(key) == "id":
                    result["os_id"] = value
        if name == "Config":
            attributes = {local_name(key): value for key, value in element.attrib.items()}
            if attributes.get("key", "").lower() == "firmware":
                result["firmware"] = attributes.get("value", "").lower()
        if name != "Item":
            continue
        fields: dict[str, str] = {}
        for child in element:
            value = (child.text or "").strip()
            if value:
                fields[local_name(child.tag)] = value
        resource_type = fields.get("ResourceType")
        if resource_type == "3" and fields.get("VirtualQuantity", "").isdigit():
            result["cpus"] = int(fields["VirtualQuantity"])
        elif resource_type == "4":
            memory = parse_memory_mb(fields.get("VirtualQuantity"), fields.get("AllocationUnits"))
            if memory:
                result["memory_mb"] = memory
        elif resource_type in {"5", "6", "20"}:
            controllers.append(
                {
                    "id": fields.get("InstanceID", ""),
                    "type": resource_type,
                    "subtype": fields.get("ResourceSubType", ""),
                }
            )
        elif resource_type == "17" and fields.get("Parent"):
            disk_parents.append(fields["Parent"])
        elif resource_type == "10" and fields.get("ResourceSubType"):
            network_subtypes.append(fields["ResourceSubType"])
    if controllers:
        result["controllers"] = controllers
    if disk_parents:
        result["disk_parents"] = disk_parents
    if network_subtypes:
        result["network_subtypes"] = network_subtypes
    return result


def read_descriptor_hints(path: Path) -> dict[str, str]:
    try:
        with path.open("rb") as handle:
            prefix = handle.read(2 * 1024 * 1024).decode("latin1", errors="ignore")
    except OSError:
        return {}
    hints: dict[str, str] = {}
    patterns = {
        "adapter_type": r'ddb\.adapterType\s*=\s*"?([^"\r\n]+)',
        "guest_os": r'ddb\.guestOS\s*=\s*"?([^"\r\n]+)',
        "create_type": r'createType\s*=\s*"?([^"\r\n]+)',
        "virtual_hw": r'ddb\.virtualHWVersion\s*=\s*"?([^"\r\n]+)',
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, prefix, flags=re.IGNORECASE)
        if match:
            hints[key] = match.group(1).strip()
    return hints


def read_partition_hints(path: Path) -> dict[str, Any]:
    qemu_img = shutil.which("qemu-img")
    if not qemu_img:
        return {"scheme": "unknown", "warning": "未找到 qemu-img"}
    with tempfile.NamedTemporaryFile(prefix="ctflab-header-", suffix=".raw") as output:
        process = subprocess.run(
            [qemu_img, "dd", f"if={path}", f"of={output.name}", "bs=512", "count=4096"],
            check=False,
            text=True,
            capture_output=True,
        )
        if process.returncode != 0:
            return {"scheme": "unknown", "warning": (process.stderr or process.stdout).strip()}
        output.seek(0)
        data = output.read()
    if len(data) < 512:
        return {"scheme": "unknown", "warning": "磁盘头不足 512 字节"}
    mbr_signature = data[510:512] == b"\x55\xaa"
    partition_types = [data[446 + index * 16 + 4] for index in range(4)] if mbr_signature else []
    gpt = len(data) >= 1024 and data[512:520] == b"EFI PART"
    efi_partition = EFI_SYSTEM_PARTITION in data[1024:1024 + 128 * 128]
    if gpt:
        scheme = "gpt"
    elif mbr_signature:
        scheme = "mbr"
    else:
        scheme = "unknown"
    return {
        "scheme": scheme,
        "mbr_signature": mbr_signature,
        "mbr_boot_code": any(data[:440]),
        "partition_types": [f"0x{value:02x}" for value in partition_types if value],
        "gpt_signature": gpt,
        "efi_system_partition": efi_partition,
    }


def infer_architecture(text: str) -> tuple[str, str, str]:
    normalized = text.lower()
    if re.search(r"(?:aarch64|arm64|arm[_ -]?64)", normalized):
        return "aarch64", "high", "名称或 OVF 元数据含 ARM64/AArch64 标识"
    if re.search(r"(?:x86_64|x86-64|amd64|x64|i[3-6]86|32-bit|64-bit|_64\b)", normalized):
        return "x86_64", "medium", "名称或 OVF 元数据含 x86/64 位标识"
    return "x86_64", "low", "磁盘本身通常不记录客体 CPU 架构，按传统靶机常见的 x86_64 生成候选"


def infer_firmware(partitions: dict[str, Any], ovf: dict[str, Any]) -> tuple[str, str, str]:
    if ovf.get("firmware") in {"efi", "uefi"}:
        return "uefi", "high", "OVF 明确声明 EFI 固件"
    if partitions.get("efi_system_partition"):
        return "uefi", "high", "GPT 中发现 EFI System Partition"
    if partitions.get("scheme") == "mbr" and partitions.get("mbr_boot_code"):
        return "bios", "high", "发现传统 MBR 引导代码"
    if partitions.get("scheme") == "gpt":
        return "uefi", "medium", "发现 GPT，但未确认 EFI System Partition"
    return "bios", "low", "未发现明确固件证据，旧 x86 镜像优先生成 Legacy BIOS 候选"


def infer_disk(architecture: str, descriptor: dict[str, str], ovf: dict[str, Any]) -> tuple[str, str | None, str, str]:
    if architecture == "aarch64":
        return "virtio", None, "medium", "ARM64 QEMU virt 机器默认使用 VirtIO 块设备"
    adapter = descriptor.get("adapter_type", "").lower()
    if adapter in {"ide", "ata"}:
        return "ide", None, "high", f"VMDK 描述符声明 adapterType={adapter}"
    if adapter in {"lsilogic", "lsilogicsas"}:
        return "scsi", "lsi53c895a", "high", f"VMDK 描述符声明 adapterType={adapter}"
    if adapter in {"pvscsi", "buslogic"}:
        return "scsi", "lsi53c895a", "low", f"来源使用 {adapter}，当前 MVP 以 LSI SCSI 作为候选，必须启动验证"
    controllers = ovf.get("controllers", [])
    parents = set(ovf.get("disk_parents", []))
    attached = [controller for controller in controllers if controller.get("id") in parents]
    if attached:
        controllers = attached
    for controller in controllers:
        if controller.get("type") == "5":
            return "ide", None, "high", "OVF 声明 IDE 控制器"
        if controller.get("type") == "20":
            return "sata", "ich9-ahci", "high", "OVF 声明 SATA 控制器"
        if controller.get("type") == "6":
            return "scsi", "lsi53c895a", "medium", f"OVF 声明 SCSI 控制器 {controller.get('subtype') or ''}".strip()
    return "ide", None, "low", "没有控制器元数据，旧 x86 镜像优先生成 IDE 候选"


def infer_network(architecture: str, ovf: dict[str, Any]) -> tuple[str, str, str]:
    if architecture == "aarch64":
        return "virtio-net-pci", "medium", "ARM64 QEMU virt 机器默认使用 VirtIO 网卡"
    subtypes = " ".join(ovf.get("network_subtypes", [])).lower()
    if "pcnet" in subtypes:
        return "pcnet", "high", "OVF 声明 PCnet 网卡"
    if "e1000" in subtypes:
        return "e1000", "high", "OVF 声明 E1000 网卡"
    if "virtio" in subtypes:
        return "virtio-net-pci", "high", "OVF 声明 VirtIO 网卡"
    return "e1000", "low", "没有网卡元数据，x86 候选使用兼容性较好的 E1000"


def inspect_image(source_arg: str | Path, *, calculate_hash: bool = True) -> dict[str, Any]:
    source = Path(source_arg).expanduser().resolve()
    if not source.exists():
        raise InspectionError(f"镜像不存在：{source}")
    hash_target = source if source.is_file() else None
    temporary = tempfile.TemporaryDirectory(prefix="ctflab-inspect-")
    try:
        disk, ovf_path, warnings = find_disk_and_ovf(source, Path(temporary.name))
        info = qemu_info(disk)
        ovf = parse_ovf(ovf_path)
        descriptor = read_descriptor_hints(disk)
        partitions = read_partition_hints(disk)
        hint_text = " ".join(
            [source.name, disk.name, descriptor.get("guest_os", ""), str(ovf.get("os_id", "")), *ovf.get("raw_hints", [])]
        )
        architecture, arch_confidence, arch_reason = infer_architecture(hint_text)
        firmware, firmware_confidence, firmware_reason = infer_firmware(partitions, ovf)
        if architecture == "aarch64":
            firmware, firmware_confidence, firmware_reason = "uefi", "high", "ARM64 virt 运行配置要求 UEFI"
        disk_bus, controller, disk_confidence, disk_reason = infer_disk(architecture, descriptor, ovf)
        network_adapter, network_confidence, network_reason = infer_network(architecture, ovf)
        if arch_confidence == "low":
            warnings.append("客体架构无法从磁盘可靠判定；启动前应通过来源说明确认，必要时使用 --architecture 覆盖。")
        if disk_confidence == "low":
            warnings.append("磁盘控制器是低置信度候选；进入 UEFI Shell、黑屏或找不到根分区时必须回退控制器。")
        warnings.extend(ovf.get("warnings", []))
        warnings.append("尚未进行冷启动、登录、网络和目标服务验证；该报告不能作为可用性交付结论。")
        report = {
            "schema": 1,
            "source_path": str(source),
            "disk_path": str(disk if source.suffix.lower() != ".ova" else Path(disk.name)),
            "source_sha256": sha256_file(hash_target) if calculate_hash and hash_target else None,
            "format": info.get("format"),
            "virtual_size": info.get("virtual-size"),
            "actual_size": info.get("actual-size"),
            "partition": partitions,
            "descriptor": descriptor,
            "ovf": ovf,
            "candidate": {
                "architecture": architecture,
                "firmware": firmware,
                "machine": "virt" if architecture == "aarch64" else "pc",
                "memory_mb": int(ovf.get("memory_mb") or (4096 if architecture == "aarch64" else 2048)),
                "cpus": int(ovf.get("cpus") or (4 if architecture == "aarch64" else 2)),
                "disk_bus": disk_bus,
                "disk_controller": controller,
                "network_adapter": network_adapter,
            },
            "confidence": {
                "architecture": {"level": arch_confidence, "reason": arch_reason},
                "firmware": {"level": firmware_confidence, "reason": firmware_reason},
                "disk": {"level": disk_confidence, "reason": disk_reason},
                "network": {"level": network_confidence, "reason": network_reason},
            },
            "warnings": list(dict.fromkeys(warnings)),
            "verification": {
                "format_readable": True,
                "boot_tested": False,
                "display_or_login_verified": False,
                "network_verified": False,
                "service_verified": False,
            },
        }
        return report
    finally:
        temporary.cleanup()


def profile_from_report(
    report: dict[str, Any],
    *,
    profile_id: str,
    name: str,
    lab_ip: str,
    mac: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    overrides = {key: value for key, value in (overrides or {}).items() if value not in {None, "auto"}}
    candidate = dict(report["candidate"])
    candidate.update(overrides)
    architecture = candidate["architecture"]
    if architecture == "aarch64":
        if "firmware" not in overrides:
            candidate["firmware"] = "uefi"
        if "disk_bus" not in overrides:
            candidate["disk_bus"] = "virtio"
            candidate["disk_controller"] = None
        if "network_adapter" not in overrides:
            candidate["network_adapter"] = "virtio-net-pci"
    if candidate["disk_bus"] not in {"scsi", "sata"}:
        candidate["disk_controller"] = None
    ipaddress.IPv4Address(lab_ip)
    disk: dict[str, Any] = {"format": "qcow2", "bus": candidate["disk_bus"]}
    if candidate.get("disk_controller"):
        disk["controller"] = candidate["disk_controller"]
    return {
        "schema": 1,
        "id": profile_id,
        "name": name,
        "version": "0.1.0-candidate",
        "guest": {
            "architecture": architecture,
            "firmware": candidate["firmware"],
            "machine": "virt" if architecture == "aarch64" else "pc",
            "memory_mb": int(candidate["memory_mb"]),
            "cpus": int(candidate["cpus"]),
        },
        "disk": disk,
        "network": {
            "adapter": candidate["network_adapter"],
            "mac": mac,
            "lab_ip": lab_ip,
            "segment": "lab",
            "internet": False,
            "host_forwards": [],
        },
        "readiness": {"timeout_seconds": 180, "checks": ["dhcp"]},
        "detection": {
            "status": "candidate",
            "source_sha256": report.get("source_sha256"),
            "confidence": report.get("confidence", {}),
            "warnings": report.get("warnings", []),
            "boot_verified": False,
            "service_verified": False,
        },
    }


def report_text(report: dict[str, Any]) -> str:
    candidate = report["candidate"]
    confidence = report["confidence"]
    lines = [
        f"来源：{report['source_path']}",
        f"格式：{report.get('format')}，虚拟容量：{report.get('virtual_size')} bytes",
        f"SHA-256：{report.get('source_sha256') or '未计算'}",
        f"分区：{report.get('partition', {}).get('scheme', 'unknown')}",
        "候选硬件：",
        f"  架构：{candidate['architecture']}（{confidence['architecture']['level']}：{confidence['architecture']['reason']}）",
        f"  固件：{candidate['firmware']}（{confidence['firmware']['level']}：{confidence['firmware']['reason']}）",
        f"  磁盘：{candidate['disk_bus']}（{confidence['disk']['level']}：{confidence['disk']['reason']}）",
        f"  网卡：{candidate['network_adapter']}（{confidence['network']['level']}：{confidence['network']['reason']}）",
        f"  资源：{candidate['memory_mb']} MB / {candidate['cpus']} vCPU",
        "警告：",
    ]
    lines.extend(f"  - {warning}" for warning in report.get("warnings", []))
    return "\n".join(lines)
