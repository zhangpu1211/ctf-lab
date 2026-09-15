#!/usr/bin/env python3
"""路径 A：把已导入的只读基础镜像导出为新的 UTM 包（`utm-export` 最小切片）。

约束来自 `docs/ctflab-dynamic-resolution-design.md` 第 2 节：

- 只读来源：要求导入记录登记 `base_sha256`，导出前后复核基盘与来源哈希；
  缺少 `base_sha256` 的旧记录不会被静默信任（明确拒绝并给出处理提示）；
- 配置结构与本机 UTM 4.7.5 的现有包静态对齐（脱敏 fixture、哈希登记、严格白名单重建）；
  不接受用户模板，禁止共享目录、端口转发、网络与剪贴板共享、附加 QEMU 参数；
- 原子输出：在输出目录内用不可预测的临时 `.utm` 目录构建，全部转换与校验通过后才发布
  最终名称；任一步失败只清理本次临时文件；
- 转换后校验：`qemu-img info` 确认 qcow2、`qemu-img check` 通过；
- 清单不含任何绝对路径；离线导出不声称图形会话 agent 已连接；本模块不执行真实 UTM E2E，
  运行结论由导出后的独立验证记录提供。
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import uuid as uuid_module
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

FIXTURE_PATH = Path(__file__).with_name("ctflab_utm_fixture.json")
FIXTURE_VERSION = 6
# 内置 fixture 的登记哈希（随发布更新）；修改 fixture 必须同时更新此值。
FIXTURE_SHA256 = "53b395d00903b275e500fe125c22f2c8ad04bea16048649718eb053ad856d6cc"
# 两个受支持变体：aarch64+UEFI（Kali，动态分辨率试点）与 x86_64+BIOS（Smoke/Basic 靶机，固定显示）。
VARIANT_AARCH64_UEFI = "aarch64-uefi"
VARIANT_X86_64_BIOS = "x86_64-bios"
# 总线 → UTM Drive.Interface（源码 QEMUDriveInterface 枚举原始值；靶机仅需 IDE/SCSI）。
X86_64_BUS_INTERFACES = {"ide": "IDE", "scsi": "SCSI"}
UTM_VERSION_REFERENCE = "4.7.5"
# 结构状态只描述“配置结构”里程碑，与运行/E2E 验收状态分离（运行状态见清单 runtime_status）。
STRUCTURE_STATUS = "complete-required-keys"
STRUCTURE_STATUS_DETAIL = (
    "结构状态只表示 UTM 4.7.5 必需段/必需键已按上游源码补齐；"
    "运行验收（导入/冷启动/交互/关机/隔离）是独立维度，以 runtime_status 与验证记录为准。"
)
# 运行状态取值（清单 runtime_status；导出时为 not-run-at-export，E2E 后由验证记录补记）。
E2E_SCOPE_NOT_RUN = "not-run-at-export"
E2E_STATUS_NOT_RUN = "not-run-at-export"
E2E_SCOPE_CONSOLE_ISOLATION = "static-console-and-isolation"
E2E_STATUS_PASSED_SCOPED = "passed-with-scope-limits"
DYNAMIC_RESOLUTION_UNTESTED_X86 = "not-tested-for-x86-fixed-display"
DYNAMIC_RESOLUTION_UNSTABLE_AARCH64 = "unstable-after-reboot-not-guaranteed"
# 包内磁盘为可写副本：来宾每次启动/关机会改变其内容与 SHA-256，两个哈希字段不得混用。
WRITABLE_DISK_NOTE = (
    "包内磁盘是可写副本：来宾每次启动/关机会改变 Data/data.qcow2 的内容与 SHA-256。"
    "sha256_at_export 是导出时的值；sha256_after_e2e 是 E2E 后复核的值，二者不得混用，"
    "也不得用其中任何一个推断未记录的运行状态。校验当前包用 SHA256SUMS（与 sha256_after_e2e 一致）；"
    "SHA256SUMS.at-export 只是导出时的历史记录，不能对 E2E 后可写盘执行校验。"
)
# 已完成“静态控制台 E2E”的包在清单 runtime_status.note 中使用的说明（逐字固定）。
E2E_SCOPED_NOTE = (
    "本清单记录离线导出结果；静态控制台 E2E 结果以独立验证记录为准。"
    "该包已验证导入、冷启动、控制台交互、正常关机和无网卡隔离，"
    "但不构成动态分辨率或联网靶场验收。"
)
BUNDLE_SUFFIX = ".utm"
MANIFEST_SUFFIX = ".utm.export.json"
DISK_RELATIVE_PATH = "Data/data.qcow2"
DISK_IMAGE_NAME = "data.qcow2"
NVRAM_RELATIVE_PATH = "Data/efi_vars.fd"
NVRAM_OUTPUT_NAME = "efi_vars.fd"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# UTM 只读枚举的常见位置；只读列出，绝不写入。
UTM_LIBRARY_HINTS = (
    Path.home() / "Library" / "Containers" / "com.utmapp.UTM" / "Data" / "Documents",
    Path.home() / "Documents",
)
ALLOWED_FIXTURE_KEYS = frozenset(
    {
        "schema",
        "fixture_version",
        "utm_version_reference",
        "structure_status",
        "disk_relative_path",
        "config_structure",
        "x86_64_bios_structure",
        "x86_64_bios_drive_interfaces",
    }
)
# UTM 4.7.5 顶层 `required init(from:)` 全部使用必需 decode 的段（源码 utmapp/UTM @ v4.7.5，
# Configuration/UTMQemuConfiguration.swift）：缺任一段即“配置无效”。
ALLOWED_CONFIG_KEYS = frozenset(
    {
        "Backend",
        "ConfigurationVersion",
        "Information",
        "System",
        "QEMU",
        "Input",
        "Sharing",
        "Display",
        "Drive",
        "Network",
        "Serial",
        "Sound",
    }
)
# 各段必需键与固定值（键名大小写严格按源码 CodingKeys；取值来自本机 4.7.5 参考包或源码枚举）。
SECTION_KEYS: dict[str, frozenset[str]] = {
    "Information": frozenset({"Icon", "IconCustom", "Name", "UUID"}),
    "System": frozenset(
        {"Architecture", "Target", "CPU", "CPUFlagsAdd", "CPUFlagsRemove", "CPUCount",
         "ForceMulticore", "MemorySize", "JITCacheSize"}
    ),
    "QEMU": frozenset(
        {"DebugLog", "UEFIBoot", "RNGDevice", "BalloonDevice", "TPMDevice", "Hypervisor",
         "TSO", "RTCLocalTime", "PS2Controller", "AdditionalArguments"}
    ),
    "Input": frozenset({"UsbBusSupport", "UsbSharing", "MaximumUsbShare"}),
    "Sharing": frozenset({"DirectoryShareMode", "DirectoryShareReadOnly", "ClipboardSharing"}),
    "Display": frozenset({"Hardware", "DynamicResolution", "UpscalingFilter", "DownscalingFilter",
                          "NativeResolution"}),
    "Drive": frozenset({"Identifier", "ImageName", "ImageType", "Interface", "InterfaceVersion",
                        "ReadOnly"}),
}
ALLOWED_PLACEHOLDERS = frozenset(
    {"<name>", "<uuid>", "<cpu-count>", "<memory-mib>", "<drive-uuid>", "<drive-interface>", "<force-multicore>"}
)


class UTMExportError(RuntimeError):
    """路径 A 导出过程中的用户可理解错误。"""


class PublishError(UTMExportError):
    """排他发布失败（目标已存在或底层调用不可用）。"""


def exclusive_rename(source: Path, destination: Path) -> None:
    """不覆盖既有目标的原子发布。

    macOS 使用 `renameatx_np(RENAME_EXCL)`，目标已存在时返回 EEXIST 而不是替换；
    其他平台退化为“先检查后 rename”（存在并发覆盖窗口，仅作为兼容回退）。
    """
    source = Path(source)
    destination = Path(destination)
    if sys.platform == "darwin":
        import ctypes
        import ctypes.util
        import errno as errno_module

        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.dylib", use_errno=True)
        renameatx_np = getattr(libc, "renameatx_np", None)
        if renameatx_np is not None:
            renameatx_np.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            renameatx_np.restype = ctypes.c_int
            at_fdcwd = -2
            rename_excl = 0x00000004
            result = renameatx_np(
                at_fdcwd, os.fsencode(source), at_fdcwd, os.fsencode(destination), rename_excl
            )
            if result != 0:
                err = ctypes.get_errno()
                if err == errno_module.EEXIST:
                    raise PublishError(f"目标已存在（并发创建），拒绝覆盖：{destination.name}")
                raise PublishError(f"排他发布失败（errno {err}）：{destination.name}")
            return
    if destination.exists():
        raise PublishError(f"目标已存在（并发创建），拒绝覆盖：{destination.name}")
    os.rename(source, destination)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expect(condition: Any, message: str) -> None:
    if not condition:
        raise UTMExportError(message)


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def fixture_bytes(path: Path | None = None) -> bytes:
    path = Path(path) if path is not None else FIXTURE_PATH
    try:
        return path.read_bytes()
    except OSError as exc:
        raise UTMExportError(f"无法读取内置 UTM fixture：{path}\n{exc}") from exc


def fixture_sha256(path: Path | None = None) -> str:
    return hashlib.sha256(fixture_bytes(path)).hexdigest()


def _placeholders_in(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        if value.startswith("<") and value.endswith(">"):
            found.add(value)
    elif isinstance(value, dict):
        for item in value.values():
            found |= _placeholders_in(item)
    elif isinstance(value, list):
        for item in value:
            found |= _placeholders_in(item)
    return found


VARIANT_EXPECTATIONS: dict[str, dict[str, Any]] = {
    VARIANT_AARCH64_UEFI: {
        "Architecture": "aarch64", "Target": "virt", "CPU": "default",
        "ForceMulticore": False, "UEFIBoot": True, "Hypervisor": True, "PS2Controller": False,
        "DisplayHardware": "virtio-gpu-pci", "DynamicResolution": True, "DriveInterface": "VirtIO",
    },
    VARIANT_X86_64_BIOS: {
        "Architecture": "x86_64", "Target": "pc", "CPU": "qemu64",
        "ForceMulticore": "<force-multicore>", "UEFIBoot": False, "Hypervisor": False,
        "PS2Controller": True, "DisplayHardware": "VGA", "DynamicResolution": False,
        "DriveInterface": "<drive-interface>",
    },
}


def validate_structure(structure: dict[str, Any], *, variant: str, label: str) -> None:
    """按变体严格校验一份 UTM 4.7.5 完整必需结构（键集合与源码一致，取值按变体核对）。"""
    exp = VARIANT_EXPECTATIONS[variant]
    _expect(isinstance(structure, dict), f"{label} 必须是 JSON 对象。")
    _expect(set(structure) == ALLOWED_CONFIG_KEYS,
            f"{label} 顶层段必须恰好为（UTM 4.7.5 顶层强制 decode）：{', '.join(sorted(ALLOWED_CONFIG_KEYS))}")
    _expect(structure["Backend"] == "QEMU", f"{label}.Backend 必须是 QEMU。")
    _expect(structure["ConfigurationVersion"] == 4, f"{label}.ConfigurationVersion 必须是 4。")

    def exact_section(name: str) -> dict[str, Any]:
        section = structure[name]
        expected = SECTION_KEYS[name]
        _expect(isinstance(section, dict) and set(section) == set(expected),
                f"{label}.{name} 键集合必须恰好为（源码必需键，大小写敏感）：{sorted(expected)}")
        return section

    info = exact_section("Information")
    _expect(info["Icon"] == "linux" and info["IconCustom"] is False,
            f"{label}.Information 图标必须是脱敏后的 linux 默认值。")
    _expect(info["Name"] == "<name>" and info["UUID"] == "<uuid>",
            f"{label}.Information 只允许 <name>/<uuid> 占位符。")

    system = exact_section("System")
    _expect(system["Architecture"] == exp["Architecture"], f"{label}.System.Architecture 必须是 {exp['Architecture']}。")
    _expect(system["Target"] == exp["Target"], f"{label}.System.Target 必须是 {exp['Target']}。")
    _expect(system["CPU"] == exp["CPU"], f"{label}.System.CPU 必须是 {exp['CPU']}（本机 UTM 4.7.5 参考值）。")
    _expect(system["CPUFlagsAdd"] == [] and system["CPUFlagsRemove"] == [],
            f"{label}.System.CPUFlagsAdd/CPUFlagsRemove 必须为空数组。")
    _expect(system["CPUCount"] == "<cpu-count>" and system["MemorySize"] == "<memory-mib>",
            f"{label}.System 只允许 <cpu-count>/<memory-mib> 占位符。")
    if variant == VARIANT_AARCH64_UEFI:
        _expect(system["ForceMulticore"] is False, f"{label}.System.ForceMulticore 必须是 false（本机参考值）。")
    else:
        _expect(system["ForceMulticore"] == "<force-multicore>", f"{label}.System.ForceMulticore 只允许 <force-multicore> 占位符。")
    _expect(system["JITCacheSize"] == 0, f"{label}.System.JITCacheSize 必须是 0（本机参考值）。")

    qemu = exact_section("QEMU")
    _expect(qemu["DebugLog"] is False, f"{label}.QEMU.DebugLog 必须是 false。")
    _expect(qemu["UEFIBoot"] is exp["UEFIBoot"], f"{label}.QEMU.UEFIBoot 必须是 {exp['UEFIBoot']}。")
    _expect(qemu["RNGDevice"] is True, f"{label}.QEMU.RNGDevice 必须是 true（本机参考值）。")
    _expect(qemu["BalloonDevice"] is False and qemu["TPMDevice"] is False,
            f"{label}.QEMU.BalloonDevice/TPMDevice 必须是 false。")
    _expect(qemu["Hypervisor"] is exp["Hypervisor"], f"{label}.QEMU.Hypervisor 必须是 {exp['Hypervisor']}。")
    _expect(qemu["TSO"] is False, f"{label}.QEMU.TSO 必须是 false（本机参考值）。")
    _expect(qemu["RTCLocalTime"] is False, f"{label}.QEMU.RTCLocalTime 必须是 false。")
    _expect(qemu["PS2Controller"] is exp["PS2Controller"], f"{label}.QEMU.PS2Controller 必须是 {exp['PS2Controller']}。")
    _expect(qemu["AdditionalArguments"] == [], f"{label}.QEMU.AdditionalArguments 必须为空数组。")

    input_section = exact_section("Input")
    _expect(input_section["UsbBusSupport"] == "3.0", f"{label}.Input.UsbBusSupport 必须是 3.0（本机参考值）。")
    _expect(input_section["UsbSharing"] is False, f"{label}.Input.UsbSharing 必须是 false。")
    _expect(input_section["MaximumUsbShare"] == 3, f"{label}.Input.MaximumUsbShare 必须是 3（本机参考值）。")

    sharing = exact_section("Sharing")
    _expect(sharing["DirectoryShareMode"] == "None", f"{label}.Sharing.DirectoryShareMode 必须是枚举值 None。")
    _expect(sharing["DirectoryShareReadOnly"] is False, f"{label}.Sharing.DirectoryShareReadOnly 必须是 false。")
    _expect(sharing["ClipboardSharing"] is False, f"{label}.Sharing.ClipboardSharing 必须显式关闭。")

    display = structure["Display"]
    _expect(isinstance(display, list) and len(display) == 1 and isinstance(display[0], dict),
            f"{label}.Display 必须是单元素数组。")
    screen = display[0]
    _expect(set(screen) == set(SECTION_KEYS["Display"]),
            f"{label}.Display[0] 键集合必须恰好为：{sorted(SECTION_KEYS['Display'])}")
    _expect(screen["Hardware"] == exp["DisplayHardware"],
            f"{label}.Display[0].Hardware 必须是 {exp['DisplayHardware']}（本机参考值）。")
    _expect(screen["DynamicResolution"] is exp["DynamicResolution"],
            f"{label}.Display[0].DynamicResolution 必须是 {exp['DynamicResolution']}。")
    _expect(screen["NativeResolution"] is False, f"{label}.Display[0].NativeResolution 必须是 false。")
    _expect(screen["DownscalingFilter"] == "Linear" and screen["UpscalingFilter"] == "Nearest",
            f"{label}.Display[0] 的缩放过滤值必须来自 QEMUScaler 枚举（Linear/Nearest）。")

    drive = structure["Drive"]
    _expect(isinstance(drive, list) and len(drive) == 1 and isinstance(drive[0], dict),
            f"{label}.Drive 必须是单元素数组。")
    disk = drive[0]
    _expect(set(disk) == set(SECTION_KEYS["Drive"]),
            f"{label}.Drive[0] 键集合必须恰好为：{sorted(SECTION_KEYS['Drive'])}")
    _expect(disk["Identifier"] == "<drive-uuid>", f"{label}.Drive[0].Identifier 只允许 <drive-uuid> 占位符。")
    _expect(disk["ImageName"] == DISK_IMAGE_NAME, f"{label}.Drive[0].ImageName 必须是 {DISK_IMAGE_NAME}。")
    _expect(disk["ImageType"] == "Disk" and disk["ReadOnly"] is False,
            f"{label}.Drive[0] 必须固定 Disk + 非只读副本。")
    _expect(disk["Interface"] == exp["DriveInterface"], f"{label}.Drive[0].Interface 必须是 {exp['DriveInterface']}。")
    _expect(disk["InterfaceVersion"] == 1, f"{label}.Drive[0].InterfaceVersion 必须是 1。")

    _expect(structure["Network"] == [], f"{label}.Network 必须为空数组（默认无网卡）。")
    _expect(structure["Serial"] == [], f"{label}.Serial 必须为空数组（顶层段必需，禁止串口）。")
    _expect(structure["Sound"] == [], f"{label}.Sound 必须为空数组（顶层段必需，禁止音频设备）。")

    unapproved = sorted(_placeholders_in(structure) - ALLOWED_PLACEHOLDERS)
    _expect(not unapproved, f"{label} 含未批准的占位符：{', '.join(unapproved)}")


def validate_fixture(data: dict[str, Any]) -> None:
    """严格校验脱敏后的 UTM 4.7.5 双变体完整结构；越界键或未批准占位符一律拒绝。"""
    _expect(isinstance(data, dict), "UTM fixture 必须是 JSON 对象。")
    unknown = sorted(set(data) - ALLOWED_FIXTURE_KEYS)
    _expect(not unknown, f"UTM fixture 含白名单之外的键：{', '.join(unknown)}")
    missing = sorted(ALLOWED_FIXTURE_KEYS - set(data))
    _expect(not missing, f"UTM fixture 缺少必需键：{', '.join(missing)}")
    _expect(data["schema"] == 2, "UTM fixture schema 必须是 2。")
    _expect(data["fixture_version"] == FIXTURE_VERSION, f"UTM fixture 版本必须是 {FIXTURE_VERSION}。")
    _expect(data["utm_version_reference"] == UTM_VERSION_REFERENCE,
            f"UTM fixture 参考版本必须是 {UTM_VERSION_REFERENCE}。")
    _expect(data["structure_status"] == STRUCTURE_STATUS, f"UTM fixture 结构状态必须是 {STRUCTURE_STATUS}。")
    _expect(data["structure_status"] != LEGACY_STRUCTURE_STATUS,
            f"UTM fixture 不得输出{LEGACY_STRUCTURE_STATUS_LABEL} {LEGACY_STRUCTURE_STATUS} 作为当前结构状态。")
    _expect(data["disk_relative_path"] == DISK_RELATIVE_PATH, f"UTM fixture 磁盘路径必须是 {DISK_RELATIVE_PATH}。")
    validate_structure(data["config_structure"], variant=VARIANT_AARCH64_UEFI, label="config_structure")
    validate_structure(data["x86_64_bios_structure"], variant=VARIANT_X86_64_BIOS, label="x86_64_bios_structure")
    mapping = data["x86_64_bios_drive_interfaces"]
    _expect(isinstance(mapping, dict) and mapping == X86_64_BUS_INTERFACES,
            f"x86_64_bios_drive_interfaces 必须恰好为 {X86_64_BUS_INTERFACES}。")


def load_fixture(path: Path | None = None) -> dict[str, Any]:
    """读取内置 fixture：先比对登记哈希，再做结构校验；不接受用户模板。"""
    raw = fixture_bytes(path)
    digest = hashlib.sha256(raw).hexdigest()
    _expect(digest == FIXTURE_SHA256,
            "内置 UTM fixture 哈希与登记值不一致，拒绝导出："
            f"实际 {digest}，登记 {FIXTURE_SHA256}。")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UTMExportError(f"UTM fixture 不是有效的 JSON：{exc}") from exc
    validate_fixture(data)
    return data


def sanitize_name(name: str) -> str:
    value = str(name or "").strip()
    _expect(NAME_RE.match(value),
            "包名只允许 1-64 位的字母、数字、点、下划线和连字符，且必须以字母或数字开头："
            f"{value!r}")
    _expect(not value.lower().endswith(BUNDLE_SUFFIX),
            f"包名不要包含 {BUNDLE_SUFFIX} 后缀，导出时会自动添加：{value!r}")
    return value


def known_utm_bundle_names() -> set[str]:
    """只读枚举常见 UTM 库位置的包名，用于避免与用户已有虚拟机重名。"""
    names: set[str] = set()
    for root in UTM_LIBRARY_HINTS:
        try:
            if not root.is_dir():
                continue
            for entry in root.iterdir():
                if entry.is_dir() and entry.name.endswith(BUNDLE_SUFFIX):
                    names.add(entry.name[: -len(BUNDLE_SUFFIX)])
        except OSError:
            continue
    return names


def detect_utm_version() -> str | None:
    """尽力记录 UTM 版本；未安装 utmctl 时返回 None（导出不依赖 UTM）。"""
    utmctl = shutil.which("utmctl")
    if not utmctl:
        return None
    try:
        result = subprocess.run([utmctl, "version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or result.stderr).strip() or None


def variant_for_profile(profile: dict[str, Any]) -> str:
    """按 profile 的架构与固件选择 UTM 变体；不受支持的组合明确拒绝。"""
    guest = (profile or {}).get("guest", {}) or {}
    architecture = str(guest.get("architecture", ""))
    firmware = str(guest.get("firmware", ""))
    if architecture == "aarch64" and firmware == "uefi":
        return VARIANT_AARCH64_UEFI
    if architecture == "x86_64" and firmware == "bios":
        return VARIANT_X86_64_BIOS
    raise UTMExportError(
        "路径 A 只支持 aarch64+UEFI 或 x86_64+BIOS 的 profile；"
        f"当前为 {architecture or '未知架构'}+{firmware or '未知固件'}，拒绝导出。"
    )


def build_plist_config(fixture: dict[str, Any], variant: str, profile: dict[str, Any], display_name: str) -> dict[str, Any]:
    """按变体与脱敏结构填充占位符；只输出白名单内的键，不做任何字段透传。"""
    guest = profile.get("guest", {}) or {}
    try:
        cpu_count = int(guest.get("cpus"))
        memory_mb = int(guest.get("memory_mb"))
    except (TypeError, ValueError) as exc:
        raise UTMExportError("profile 缺少有效的 guest.cpus / guest.memory_mb。") from exc
    _expect(cpu_count > 0 and memory_mb > 0, "profile 的 guest.cpus / guest.memory_mb 必须为正整数。")
    if variant == VARIANT_AARCH64_UEFI:
        structure = copy.deepcopy(fixture["config_structure"])
    else:
        structure = copy.deepcopy(fixture["x86_64_bios_structure"])
        bus = str(((profile.get("disk", {}) or {}).get("bus", "")))
        _expect(bus in X86_64_BUS_INTERFACES, f"x86_64 BIOS 变体只支持 IDE/SCSI 磁盘；当前为 {bus or '未知'}。")
        structure["Drive"][0]["Interface"] = X86_64_BUS_INTERFACES[bus]
        # ForceMulticore 与本机两个 x86_64 参考包一致：多核时 true，单核时 false。
        structure["System"]["ForceMulticore"] = cpu_count > 1
    structure["Information"]["Name"] = display_name
    structure["Information"]["UUID"] = str(uuid_module.uuid4())
    structure["System"]["CPUCount"] = cpu_count
    structure["System"]["MemorySize"] = memory_mb
    structure["Drive"][0]["Identifier"] = str(uuid_module.uuid4())
    leftover = sorted(_placeholders_in(structure))
    _expect(not leftover, f"生成配置仍有未填充的占位符：{', '.join(leftover)}")
    return structure


def _qemu_img_tool() -> str | None:
    """qemu-img 解析：受控运行时（.app）优先，其次 PATH（开发环境回退）。"""
    try:
        import ctflab  # noqa: PLC0415  函数内导入，避免循环依赖
    except ImportError:
        return shutil.which("qemu-img")
    # 受控运行时激活但缺少 qemu-img 时必须失败，不能被宿主 PATH 静默补齐。
    return ctflab.resolve_tool("qemu-img")


def qemu_img_convert(source: Path, destination: Path) -> None:
    qemu_img = _qemu_img_tool()
    _expect(qemu_img, "未找到 qemu-img：请安装 QEMU 或使用自带运行时的 CTFLab.app。")
    result = subprocess.run(
        [qemu_img, "convert", "-f", "qcow2", "-O", "qcow2", str(source), str(destination)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise UTMExportError(f"qemu-img convert 失败：{detail or result.returncode}")


def qemu_img_convert_nvram(source: Path, destination: Path) -> None:
    """把 CTFLab 的 RAW UEFI NVRAM 转换为 UTM 使用的 QCOW2 变量盘。"""
    qemu_img = _qemu_img_tool()
    _expect(qemu_img, "未找到 qemu-img：请安装 QEMU 或使用自带运行时的 CTFLab.app。")
    result = subprocess.run(
        [qemu_img, "convert", "-f", "raw", "-O", "qcow2", str(source), str(destination)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise UTMExportError(f"NVRAM 转换失败（qemu-img convert -f raw -O qcow2）：{detail or result.returncode}")


def qemu_img_info(path: Path) -> dict[str, Any]:
    qemu_img = _qemu_img_tool()
    _expect(qemu_img, "未找到 qemu-img：请安装 QEMU 或使用自带运行时的 CTFLab.app。")
    result = subprocess.run([qemu_img, "info", "--output=json", str(path)], capture_output=True, text=True)
    if result.returncode != 0:
        raise UTMExportError(f"qemu-img info 失败：{(result.stderr or result.stdout).strip() or result.returncode}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise UTMExportError(f"qemu-img info 返回了无法解析的内容：{path.name}") from exc


def qemu_img_check(path: Path) -> None:
    qemu_img = _qemu_img_tool()
    _expect(qemu_img, "未找到 qemu-img：请安装 QEMU 或使用自带运行时的 CTFLab.app。")
    result = subprocess.run([qemu_img, "check", str(path)], capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stdout or result.stderr or "").strip()
        raise UTMExportError(f"qemu-img check 未通过：{detail or result.returncode}")


def export_utm_package(
    *,
    profile_id: str,
    profile: dict[str, Any],
    image_state: dict[str, Any] | None,
    out_dir: Path,
    name: str | None = None,
    fixture_path: Path | None = None,
    convert: Callable[[Path, Path], None] | None = None,
    nvram_convert: Callable[[Path, Path], None] | None = None,
    info: Callable[[Path], dict[str, Any]] | None = None,
    check: Callable[[Path], None] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """导出路径 A 的 `<name>.utm` 包与 `<name>.utm.export.json` 清单（原子发布）。"""
    profile_id = str(profile_id)
    guest = (profile or {}).get("guest", {}) or {}
    variant = variant_for_profile(profile)
    disk_profile = (profile or {}).get("disk", {}) or {}
    bus = str(disk_profile.get("bus", ""))
    if variant == VARIANT_AARCH64_UEFI:
        _expect(bus == "virtio", "aarch64+UEFI 变体只支持 virtio 磁盘；请改用 virtio 磁盘的 profile。")
        adapter = str(((profile or {}).get("display", {}) or {}).get("adapter", "") or "")
        _expect(not adapter or adapter == "virtio-gpu",
                f"aarch64+UEFI 变体只支持 virtio-gpu 显示，当前 profile 声明了 {adapter}。")
    else:
        _expect(bus in X86_64_BUS_INTERFACES,
                f"x86_64+BIOS 变体只支持 IDE/SCSI 磁盘；当前为 {bus or '未知'}，拒绝导出。")

    _expect(image_state, f"{profile_id} 尚未导入基础镜像，无法导出 UTM 包（先执行 import）。")
    base_path = Path(str(image_state.get("base_path") or ""))
    _expect(base_path.is_file(), f"导入记录中的基础镜像不存在：{base_path}")
    recorded_source_sha256 = str(image_state.get("source_sha256") or "")
    _expect(recorded_source_sha256, "导入记录缺少来源 SHA-256，无法完成只读校验，拒绝导出。")
    registered_base_sha256 = str(image_state.get("base_sha256") or "")
    _expect(
        registered_base_sha256,
        "导入记录缺少 base_sha256（旧版本登记），不会静默信任。处理提示：在来源镜像仍可得时"
        "重新执行 import，由 qemu-img compare 证明内容一致后登记；否则请等待专门的完整性迁移流程。",
    )
    recorded_source_path = Path(str(image_state.get("source_path") or ""))
    source_recheck = "source-missing"
    source_file = None
    if recorded_source_path.is_file():
        _expect(sha256_file(recorded_source_path) == recorded_source_sha256,
                "来源镜像哈希与导入登记值不一致，拒绝导出。")
        source_recheck = "source-matches-recorded"
        source_file = recorded_source_path.name
    base_sha256_before = sha256_file(base_path)
    _expect(base_sha256_before == registered_base_sha256,
            "基础镜像 SHA-256 与登记值不一致（基盘可能已被修改），拒绝导出。")

    uefi_vars_path: Path | None = None
    registered_nvram_sha256 = ""
    nvram_sha256_before = ""
    if variant == VARIANT_AARCH64_UEFI:
        uefi_vars_path = Path(str(image_state.get("uefi_vars_path") or ""))
        registered_nvram_sha256 = str(image_state.get("uefi_vars_sha256") or "")
        _expect(uefi_vars_path.is_file(), f"导入记录中的 UEFI NVRAM 不存在：{uefi_vars_path}")
        _expect(registered_nvram_sha256, "导入记录缺少 uefi_vars_sha256，拒绝导出。")
        nvram_sha256_before = sha256_file(uefi_vars_path)
        _expect(nvram_sha256_before == registered_nvram_sha256,
                "UEFI NVRAM SHA-256 与登记值不一致（NVRAM 可能已被修改），拒绝导出。")

    display_name = sanitize_name(profile_id if name is None else name)
    existing_names = {item.casefold() for item in known_utm_bundle_names()}
    _expect(display_name.casefold() not in existing_names,
            f"UTM 库中已存在同名虚拟机 {display_name}；请用 --name 指定其他显示名（不触碰已有虚拟机）。")

    out_dir = Path(out_dir).expanduser()
    if out_dir.exists() and not out_dir.is_dir():
        raise UTMExportError(f"输出路径不是目录：{out_dir}")
    bundle_final = out_dir / f"{display_name}{BUNDLE_SUFFIX}"
    manifest_final = out_dir / f"{display_name}{MANIFEST_SUFFIX}"
    _expect(not bundle_final.exists() and not manifest_final.exists(),
            f"目标已存在，拒绝覆盖：{bundle_final.name if bundle_final.exists() else manifest_final.name}")

    fixture = load_fixture(fixture_path)
    plist_config = build_plist_config(fixture, variant, profile, display_name)
    convert_fn = convert or qemu_img_convert
    nvram_convert_fn = nvram_convert or qemu_img_convert_nvram
    info_fn = info or qemu_img_info
    check_fn = check or qemu_img_check
    utm_version = detect_utm_version()
    out_dir.mkdir(parents=True, exist_ok=True)

    temp_dir: Path | None = None
    temp_manifest: Path | None = None
    published_bundle = False
    try:
        # 不可预测、独占创建的临时 .utm 目录；构建期间最终名称不出现。
        temp_dir = Path(tempfile.mkdtemp(prefix=f".{display_name}-", suffix=BUNDLE_SUFFIX, dir=str(out_dir)))
        (temp_dir / "config.plist").write_bytes(plistlib.dumps(plist_config, fmt=plistlib.FMT_XML, sort_keys=True))
        data_dir = temp_dir / "Data"
        data_dir.mkdir()
        disk_path = temp_dir / DISK_RELATIVE_PATH
        convert_fn(base_path, disk_path)
        _expect(disk_path.is_file(), "磁盘转换没有生成目标文件。")
        disk_info = info_fn(disk_path)
        _expect(str(disk_info.get("format")) == "qcow2",
                f"转换结果不是 qcow2（实际 {disk_info.get('format')}），拒绝发布。")
        check_fn(disk_path)
        nvram_path: Path | None = None
        nvram_info: dict[str, Any] = {}
        if variant == VARIANT_AARCH64_UEFI:
            nvram_path = temp_dir / NVRAM_RELATIVE_PATH
            nvram_convert_fn(uefi_vars_path, nvram_path)
            _expect(nvram_path.is_file(), "NVRAM 转换没有生成目标文件。")
            nvram_info = info_fn(nvram_path)
            _expect(str(nvram_info.get("format")) == "qcow2",
                    f"NVRAM 转换结果不是 qcow2（实际 {nvram_info.get('format')}），拒绝发布。")
            check_fn(nvram_path)
        base_sha256_after = sha256_file(base_path)
        _expect(base_sha256_after == base_sha256_before,
                "基础镜像在导出过程中发生变化（应保持只读），已中止导出。")
        nvram_sha256_after = ""
        if variant == VARIANT_AARCH64_UEFI:
            nvram_sha256_after = sha256_file(uefi_vars_path)
            _expect(nvram_sha256_after == nvram_sha256_before,
                    "UEFI NVRAM 在导出过程中发生变化（应保持只读），已中止导出。")
        if variant == VARIANT_AARCH64_UEFI:
            uefi_vars_block: dict[str, Any] = {
                "input_file": uefi_vars_path.name,
                "input_sha256": registered_nvram_sha256,
                "input_sha256_before": nvram_sha256_before,
                "input_sha256_after": nvram_sha256_after,
                "output_file": NVRAM_OUTPUT_NAME,
                "output_sha256": sha256_file(nvram_path),
                "format": "qcow2",
                "check": "ok",
                "size_bytes": nvram_path.stat().st_size,
                "virtual_size": nvram_info.get("virtual-size"),
            }
            display_block: dict[str, Any] = {
                "mode": "dynamic-attempted",
                "dynamic_resolution": True,
                "note": "重启后复测失败，显示链路不稳定；当前包仅保证固定显示可用。",
            }
            agent_block: dict[str, Any] = {
                "status": "not-verified-offline",
                "detail": "离线导出只记录基盘前提，不核验图形会话 agent；spice-vdagent 进程与 xrandr 跟随只能在 UTM E2E 中验收。",
            }
            e2e_required = [
                "来宾图形会话中 spice-vdagent 进程运行且 agent 已连接",
                "至少两种窗口尺寸下实际 xrandr --current 模式跟随",
                "宿主/来宾剪贴板双向负向（英文、中文、多行）",
                "无 WAN、无物理 LAN、无 CTFLab 实验网连通",
            ]
        else:
            uefi_vars_block = {
                "status": "not-applicable",
                "detail": "x86_64 BIOS 包不含 UEFI NVRAM；UTM 使用自身固件配置。",
            }
            display_block = {
                "mode": "fixed",
                "dynamic_resolution": False,
                "note": "固定显示（DynamicResolution=false）；动态分辨率未验收。",
            }
            agent_block = {
                "status": "not-applicable",
                "detail": "x86_64 BIOS 靶机不使用 SPICE agent；登录界面为控制台（或镜像自带界面）。",
            }
            e2e_required = [
                "冷启动到达登录界面（控制台或镜像自带界面）",
                "基本 GUI/控制台交互可用",
                "来宾内正常关机或 ACPI 正常关机",
                "无 WAN、无物理 LAN、无 CTFLab 实验网连通",
            ]
        runtime_status = {
            "e2e_scope": E2E_SCOPE_NOT_RUN,
            "e2e_status": E2E_STATUS_NOT_RUN,
            "dynamic_resolution": (
                DYNAMIC_RESOLUTION_UNSTABLE_AARCH64
                if variant == VARIANT_AARCH64_UEFI else DYNAMIC_RESOLUTION_UNTESTED_X86
            ),
            "verification_records": [],
            "note": (
                "本清单记录离线导出结果；静态控制台 E2E 结果以独立验证记录为准。"
                "导出时尚未执行 E2E：补齐验证记录前不得宣称可导入、可启动或动态分辨率就绪。"
                + ("动态分辨率：重启后复测失败，显示链路不稳定；当前包仅保证固定显示可用。"
                   if variant == VARIANT_AARCH64_UEFI else
                   "本包为 x86_64 BIOS 靶机，固定显示，不含动态分辨率/SPICE agent。")
            ),
        }
        manifest = {
            "schema": 3,
            "generator": "ctflab utm-export",
            "generated_at": generated_at or now_iso(),
            "profile_id": profile_id,
            "display_name": display_name,
            "variant": variant,
            "bundle": {
                "name": bundle_final.name,
                "format": "utm",
                "config": "config.plist",
                "disk": DISK_RELATIVE_PATH,
            },
            "manifest": {"name": manifest_final.name},
            "fixture": {
                "version": int(fixture["fixture_version"]),
                "sha256": fixture_sha256(fixture_path),
                "utm_version_reference": str(fixture["utm_version_reference"]),
                "structure_status": str(fixture["structure_status"]),
                "structure_status_detail": STRUCTURE_STATUS_DETAIL,
            },
            "base_image": {
                "file": base_path.name,
                "sha256": registered_base_sha256,
                "sha256_before": base_sha256_before,
                "sha256_after": base_sha256_after,
            },
            "source_image": {
                "file": source_file,
                "recorded_sha256": recorded_source_sha256,
                "source_recheck": source_recheck,
            },
            "utm_disk": {
                "file": DISK_IMAGE_NAME,
                "sha256_at_export": sha256_file(disk_path),
                "sha256_after_e2e": None,
                "writable": True,
                "writable_note": WRITABLE_DISK_NOTE,
                "size_bytes": disk_path.stat().st_size,
                "format": "qcow2",
                "check": "ok",
                "virtual_size": disk_info.get("virtual-size"),
            },
            "uefi_vars": uefi_vars_block,
            "display": display_block,
            "network": {"mode": "none", "nics": 0},
            "clipboard_sharing": False,
            "shared_directories": [],
            "additional_qemu_arguments": [],
            "utm_version": utm_version,
            "guest_agent_prerequisite": agent_block,
            "utm_e2e_required": e2e_required,
            "runtime_status": runtime_status,
            "note": (
                "路径 A 产物：UTM 4.7.5 必需段与必需键已按上游源码补齐；导入/E2E 验收状态以验证记录为准，"
                "不得据此宣称可导入、可启动或动态分辨率就绪。"
                + ("动态分辨率：重启后复测失败，显示链路不稳定；当前包仅保证固定显示可用。"
                   if variant == VARIANT_AARCH64_UEFI else
                   "本包为 x86_64 BIOS 靶机，固定显示，不含动态分辨率/SPICE agent。")
            ),
        }
        # 临时清单：独占创建，不使用固定 <manifest>.tmp 名称，不覆盖任何既有文件。
        handle_fd, temp_manifest_name = tempfile.mkstemp(
            prefix=f".{display_name}-", suffix=MANIFEST_SUFFIX, dir=str(out_dir)
        )
        temp_manifest = Path(temp_manifest_name)
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        _expect(not bundle_final.exists() and not manifest_final.exists(),
                "目标在构建期间出现，拒绝覆盖。")
        # 发布：先包后清单，使用排他重命名（macOS renameatx_np RENAME_EXCL），
        # 目标在检查与发布之间被外部并发创建时返回 EEXIST 而不是覆盖。
        exclusive_rename(temp_dir, bundle_final)
        temp_dir = None
        published_bundle = True
        exclusive_rename(temp_manifest, manifest_final)
        temp_manifest = None
        return manifest
    except Exception:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
        if temp_manifest is not None:
            temp_manifest.unlink(missing_ok=True)
        if published_bundle:
            # 只回滚本次发布的包；既有文件从未被触碰。
            shutil.rmtree(bundle_final, ignore_errors=True)
        raise


MANIFEST_SCHEMA_CURRENT = 3
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# 旧版（schema 2）清单使用裸 `utm_disk.sha256`；迁移时只重命名，不改数值。
LEGACY_DISK_SHA_FIELD = "sha256"
# 旧 schema 迁移标签：只用于识别 schema 2 清单并迁移，绝不作为当前 fixture 值或当前结构状态输出。
LEGACY_STRUCTURE_STATUS = "complete-required-keys-pending-utm-e2e"
LEGACY_STRUCTURE_STATUS_LABEL = "旧 schema 迁移标签"


def record_e2e_result(
    manifest: dict[str, Any],
    *,
    e2e_scope: str,
    e2e_status: str,
    dynamic_resolution: str,
    sha256_after_e2e: str | None,
    verification_records: list[str],
    note: str = E2E_SCOPED_NOTE,
) -> dict[str, Any]:
    """把 E2E 运行结论补记到离线清单：只写运行状态与磁盘的 E2E 后哈希。

    约束（与“清单保持离线导出语义”一致）：
    - 不改动任何离线导出字段（generated_at、base_image、source_image、network、
      clipboard_sharing、fixture.sha256 等保持导出时原值）；
    - 旧 schema 2 清单的裸 `utm_disk.sha256` 只重命名为 `sha256_at_export`，数值不变；
    - `sha256_after_e2e` 与 `sha256_at_export` 是两个独立字段，任何一方缺失/非法都拒绝写入，
      不得用其中一个字段顶替另一个。
    """
    _expect(isinstance(manifest, dict), "清单必须是 JSON 对象。")
    updated = copy.deepcopy(manifest)
    disk = updated.get("utm_disk")
    _expect(isinstance(disk, dict), "清单缺少 utm_disk 段，无法补记 E2E 结果。")
    if LEGACY_DISK_SHA_FIELD in disk:
        _expect("sha256_at_export" not in disk,
                "清单同时含旧字段 sha256 与新字段 sha256_at_export，无法安全迁移。")
        disk["sha256_at_export"] = disk.pop(LEGACY_DISK_SHA_FIELD)
    _expect("sha256_at_export" in disk, "清单缺少 sha256_at_export，拒绝补记 E2E 结果。")
    _expect(_SHA256_RE.match(str(disk["sha256_at_export"])) is not None,
            "sha256_at_export 不是 64 位小写十六进制，拒绝补记。")
    if sha256_after_e2e is not None:
        _expect(_SHA256_RE.match(str(sha256_after_e2e)) is not None,
                "sha256_after_e2e 不是 64 位小写十六进制；无 E2E 后哈希时应传 None。")
    disk["sha256_after_e2e"] = sha256_after_e2e
    disk.setdefault("writable", True)
    # 说明字段由常量派生：重复补记时刷新，避免残留旧版校验清单语义。
    disk["writable_note"] = WRITABLE_DISK_NOTE
    fixture = updated.get("fixture")
    if isinstance(fixture, dict) and fixture.get("structure_status") == LEGACY_STRUCTURE_STATUS:
        # 旧 schema 迁移标签：只做标签迁移（文档语义），fixture 版本/哈希等离线字段保持导出时原值。
        fixture["structure_status"] = STRUCTURE_STATUS
        fixture["structure_status_detail"] = STRUCTURE_STATUS_DETAIL
    _expect(str(e2e_scope) and str(e2e_status) and str(dynamic_resolution),
            "e2e_scope/e2e_status/dynamic_resolution 都必须为非空字符串。")
    _expect(isinstance(verification_records, list) and all(
        isinstance(item, str) and item for item in verification_records),
        "verification_records 必须是字符串列表。")
    updated["runtime_status"] = {
        "e2e_scope": str(e2e_scope),
        "e2e_status": str(e2e_status),
        "dynamic_resolution": str(dynamic_resolution),
        "verification_records": list(verification_records),
        "note": str(note),
    }
    updated["schema"] = MANIFEST_SCHEMA_CURRENT
    # 补记后的清单不得再输出旧 schema 迁移标签字面量：它只用于识别/迁移输入，
    # 出现在结果里（例如注释字段被原样带出）就拒绝，避免旧标签被当成当前状态。
    remainder = json.dumps(updated, ensure_ascii=False)
    _expect(LEGACY_STRUCTURE_STATUS not in remainder,
            f"补记结果仍含{LEGACY_STRUCTURE_STATUS_LABEL}字面量（{LEGACY_STRUCTURE_STATUS}）；"
            "请把相关说明改为不含该字面量的中性表述（如“旧 schema 迁移标签”）后再补记。")
    return updated
