#!/usr/bin/env python3
"""CTFLab 第一阶段本地运行器。

这是一个面向 macOS Apple Silicon 的轻量 MVP：基础镜像只读导入，启动时
创建 qcow2 overlay，并用 QEMU 管理 ARM64 Kali 与 x86_64 靶机的生命周期。
"""

from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
import fcntl
import gzip
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, TextIO
import urllib.error
import urllib.request

from ctflab_inspect import InspectionError, inspect_image, profile_from_report, report_text
from ctflab_utm import PublishError, UTMExportError, exclusive_rename, export_utm_package

try:
    import yaml
except ImportError:  # pragma: no cover - 在不含 PyYAML 的分发环境中给出清晰提示
    yaml = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = PROJECT_ROOT / "tools" / "ctflab_profiles"
DEFAULT_STATE_DIR = Path.home() / "Library" / "Application Support" / "CTFLab"
# 版本是打包（Task 6.1）、内容包版本门禁与 SBOM 的单一来源。
CTFLAB_VERSION = "0.1.0"
# 最低 Python 版本（与 tools/ctflab_package.py 的 MIN_PYTHON 一致；doctor 实际校验）。
MIN_PYTHON = (3, 10)
QEMU_X86_NAMES = ("qemu-system-x86_64",)
QEMU_ARM_NAMES = ("qemu-system-aarch64",)
SPICE_CLIENT_NAMES = ("remote-viewer", "spicy")
PROFILE_ALIASES = {"kali": "kali-arm64"}
NETWORK_SCRIPT = PROJECT_ROOT / "tools" / "ctflab_network.py"
KALI_SETUP_SCRIPT = PROJECT_ROOT / "tools" / "guest_fixes" / "kali-arm64" / "configure.sh"


class CTFLabError(RuntimeError):
    """用户可理解的运行错误。"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def python_version_ok() -> bool:
    """当前解释器是否满足最低版本（doctor 的实际校验，而非只看解释器存在）。"""
    return sys.version_info[:2] >= MIN_PYTHON


def run_command(command: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=capture,
        )
    except FileNotFoundError as exc:
        raise CTFLabError(f"找不到命令：{command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise CTFLabError(f"命令执行失败：{' '.join(command)}\n{detail}") from exc


def runtime_root() -> Path | None:
    """受控 QEMU 运行时根目录。

    优先 `CTFLAB_RUNTIME_ROOT`（.app 启动器导出），其次识别 `.app` 布局
    （`Contents/Resources/ctflab/tools/ctflab.py` → `Contents/Resources/runtime`）。
    两者都不存在时返回 None（开发环境按 PATH 解析；代码里不写死任何安装路径）。
    """
    env = os.environ.get("CTFLAB_RUNTIME_ROOT")
    if env:
        candidate = Path(env).expanduser()
        if (candidate / "bin").is_dir():
            return candidate
    # .app 布局：Contents/Resources/ctflab/tools/ctflab.py → Contents/Resources/runtime
    for ancestor in Path(__file__).resolve().parents:
        if ancestor.name == "Resources" and (ancestor / "runtime" / "bin").is_dir():
            return ancestor / "runtime"
    return None


def resolve_tool(name: str) -> str | None:
    """工具解析顺序：受控运行时，或未激活受控运行时时使用 PATH。

    受控运行时一旦激活就不回退到宿主 PATH。这样 app 缺件会明确失败，不会被开发机
    恰好安装的 Homebrew QEMU 掩盖，也不会把“使用 bundled runtime”误报为成功。
    """
    root = runtime_root()
    if root is not None:
        candidate = root / "bin" / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        return None
    return shutil.which(name)


def which_any(names: Iterable[str]) -> str | None:
    for name in names:
        path = resolve_tool(name)
        if path:
            return path
    return None


def spice_client_path() -> str | None:
    """查找受控 SPICE 客户端；不把任意外部命令或参数透传给 QEMU。

    `CTFLAB_SPICE_CLIENT` 只用于本机开发/验收时指定已审计的客户端路径；分发包应把
    客户端放进自己的 runtime/bin 后再由这里解析。没有客户端时，显式 spice 请求必须
    在启动 QEMU 前失败，不能退回 Cocoa。
    """
    override = os.environ.get("CTFLAB_SPICE_CLIENT")
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    root = runtime_root()
    if root is not None:
        for name in SPICE_CLIENT_NAMES:
            candidate = root / "bin" / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        return None
    return shutil.which(SPICE_CLIENT_NAMES[0]) or shutil.which(SPICE_CLIENT_NAMES[1])


def spice_client_command(client: str, endpoint: Path, clipboard: bool = False) -> list[str]:
    """构造受控客户端命令；只有显式 `--clipboard` 才打开客户端剪贴板。"""
    client_uri = f"spice+unix://{endpoint}"
    if Path(client).name == "spicy":
        command = [client, "--uri", client_uri]
        if clipboard:
            command.append("--clipboard")
        return command
    return [client, client_uri]


def resolve_display_backend(profile_id: str, requested: str, *, headless: bool = False) -> str:
    """解析 ``run --display auto``：Kali 图形模式使用 SPICE，其余节点使用 Cocoa。

    自动模式只对图形启动启用 SPICE；无头运行不拉起客户端，也不要求宿主具备 SPICE
    客户端。显式 ``cocoa``/``spice`` 仍由调用方执行各自的 profile 与能力门禁。
    """
    if requested not in {"auto", "cocoa", "spice"}:
        raise CTFLabError(f"不支持的显示后端：{requested}（可选 auto、cocoa 或 spice）。")
    if headless and requested == "auto":
        return "cocoa"
    if requested == "auto":
        return "spice" if profile_id == "kali-arm64" else "cocoa"
    return requested


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CTFLabError(f"无法读取状态文件：{path}\n{exc}") from exc


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def qemu_img_path() -> str:
    path = resolve_tool("qemu-img")
    if not path:
        raise CTFLabError(
            "未找到 qemu-img：请安装 QEMU（brew install qemu），或使用自带运行时的 CTFLab.app。")
    return path


def qemu_info(path: Path, *, force_share: bool = False) -> dict[str, Any]:
    command = [qemu_img_path(), "info"]
    if force_share:
        command.append("--force-share")
    command += ["--output=json", str(path)]
    result = run_command(command)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CTFLabError(f"qemu-img info 返回了无法解析的内容：{path}") from exc


def compare_disk_images(source: Path, source_format: str, base_path: Path) -> bool:
    """用 qemu-img compare（严格模式）判断来源与现有基盘的来宾可见内容是否一致。

    必须使用 `-s`：默认模式下 qemu-img compare 只警告尺寸不一致并仍返回 0，
    会把截断或不同容量的镜像误判为一致。返回 True 表示一致；False 表示内容或容量不同；
    无法比较（文件损坏等）时抛错，调用方必须按“不可信”处理。
    """
    result = subprocess.run(
        [qemu_img_path(), "compare", "-s", "-f", source_format, "-F", "qcow2", str(source), str(base_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    detail = (result.stderr or result.stdout or "").strip()
    raise CTFLabError(f"qemu-img compare 无法完成（退出码 {result.returncode}）：{detail[:400]}")


def validate_arm64_installer_iso(path: Path) -> dict[str, Any]:
    """验证 ISO9660 签名和 Kali/Debian ARM64 安装器所需成员。"""
    path = path.expanduser().resolve()
    if not path.is_file():
        raise CTFLabError(f"安装 ISO 不存在：{path}")
    try:
        with path.open("rb") as handle:
            handle.seek(0x8001)
            iso_signature = handle.read(5)
    except OSError as exc:
        raise CTFLabError(f"无法读取安装 ISO：{path}\n{exc}") from exc
    if iso_signature != b"CD001":
        raise CTFLabError(f"文件不是有效的 ISO9660 镜像：{path}")
    bsdtar = shutil.which("bsdtar") or shutil.which("tar")
    if not bsdtar:
        raise CTFLabError("未找到 bsdtar，无法读取 ARM64 安装器文件。")
    required_members = ("install.a64/vmlinuz", "install.a64/gtk/initrd.gz")
    result = subprocess.run(
        [bsdtar, "-tf", str(path), *required_members],
        check=False,
        text=True,
        capture_output=True,
    )
    listed = set(result.stdout.splitlines())
    missing = [member for member in required_members if member not in listed]
    if result.returncode != 0 or missing:
        detail = result.stderr.strip() or ", ".join(missing)
        raise CTFLabError(f"ISO 不含完整的 ARM64 图形安装器：{detail}")
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "kernel_member": required_members[0],
        "initrd_member": required_members[1],
    }


def build_unattended_preseed(username: str = "kali", hostname: str = "kali", *, password: str | None = None) -> str:
    """生成仅用于本地隔离实验机的 Kali XFCE 无人值守安装回答。"""
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", username):
        raise CTFLabError(f"安装用户名不合法：{username}")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", hostname):
        raise CTFLabError(f"安装主机名不合法：{hostname}")
    password = password if password is not None else os.environ.get("CTFLAB_INSTALL_PASSWORD", "")
    if not password or any(char.isspace() or ord(char) < 32 for char in password):
        raise CTFLabError("自动安装需要 CTFLAB_INSTALL_PASSWORD，且不能含空白或控制字符；口令仅写入本地安装资产。")
    return f"""# CTFLab 本地隔离靶场无人值守安装配置
d-i debian-installer/locale string en_US.UTF-8
d-i keyboard-configuration/xkb-keymap select us
d-i netcfg/choose_interface select auto
d-i netcfg/get_hostname string {hostname}
d-i netcfg/get_domain string local
d-i netcfg/get_nameservers string 10.0.2.3
d-i clock-setup/utc boolean true
d-i time/zone string Asia/Shanghai
d-i passwd/root-login boolean false
d-i passwd/user-fullname string Kali User
d-i passwd/username string {username}
d-i passwd/user-password password {password}
d-i passwd/user-password-again password {password}
d-i user-setup/allow-password-weak boolean true
d-i user-setup/encrypt-home boolean false
d-i partman-auto/disk string /dev/vda
d-i partman-auto/method string regular
d-i partman-auto/choose_recipe select atomic
d-i partman-partitioning/confirm_write_new_label boolean true
d-i partman/choose_partition select finish
d-i partman/confirm boolean true
d-i partman/confirm_nooverwrite boolean true
d-i apt-setup/use_mirror boolean false
d-i apt-setup/services-select multiselect
d-i pkgsel/upgrade select none
d-i pkgsel/update-policy select none
tasksel tasksel/first multiselect standard
d-i pkgsel/include string kali-desktop-xfce kali-linux-default openssh-server qemu-guest-agent spice-vdagent
popularity-contest popularity-contest/participate boolean false
wireshark-common wireshark-common/install-setuid boolean false
kismet-capture-common kismet-capture-common/install-setuid boolean false
macchanger macchanger/automatically_run boolean false
d-i grub-installer/only_debian boolean true
d-i cdrom-detect/eject boolean false
d-i preseed/late_command string cp /ctflab-guest-setup.sh /target/tmp/ctflab-guest-setup.sh && in-target /bin/sh /tmp/ctflab-guest-setup.sh && rm -f /target/tmp/ctflab-guest-setup.sh
d-i finish-install/reboot_in_progress note
"""


def extract_iso_member(iso_path: Path, member: str, destination: Path) -> None:
    bsdtar = shutil.which("bsdtar") or shutil.which("tar")
    if not bsdtar:
        raise CTFLabError("未找到 bsdtar，无法提取 ARM64 安装器。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("wb") as output:
        result = subprocess.run(
            [bsdtar, "-xOf", str(iso_path), member],
            check=False,
            stdout=output,
            stderr=subprocess.PIPE,
        )
    if result.returncode != 0 or temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise CTFLabError(f"无法从 ISO 提取 {member}：{detail}")
    temporary.replace(destination)


def prepare_unattended_installer_assets(iso_path: Path, iso_hash: str, destination: Path) -> tuple[Path, Path]:
    """提取内核，并向安装 initrd 追加本地 preseed.cfg。"""
    destination.mkdir(parents=True, exist_ok=True)
    destination.chmod(0o700)
    preseed = build_unattended_preseed()
    setup_script = KALI_SETUP_SCRIPT.read_bytes()
    preseed_hash = hashlib.sha256(preseed.encode("utf-8") + setup_script).hexdigest()[:8]
    suffix = f"{iso_hash[:12]}-{preseed_hash}"
    kernel_path = destination / f"vmlinuz-{suffix}"
    initrd_path = destination / f"initrd-unattended-{suffix}.gz"
    if kernel_path.exists() and initrd_path.exists():
        return kernel_path, initrd_path

    with tempfile.TemporaryDirectory(prefix="ctflab-initrd-", dir=destination) as directory:
        work = Path(directory)
        original_initrd = work / "initrd-original.gz"
        raw_initrd = work / "initrd.raw"
        preseed_path = work / "preseed.cfg"
        staged_kernel = work / "vmlinuz"
        staged_initrd = work / "initrd-unattended.gz"
        extract_iso_member(iso_path, "install.a64/vmlinuz", staged_kernel)
        extract_iso_member(iso_path, "install.a64/gtk/initrd.gz", original_initrd)
        with gzip.open(original_initrd, "rb") as source, raw_initrd.open("wb") as target:
            shutil.copyfileobj(source, target)
        preseed_path.write_text(preseed, encoding="utf-8")
        preseed_path.chmod(0o600)
        (work / "ctflab-guest-setup.sh").write_bytes(setup_script)
        cpio = shutil.which("cpio")
        if not cpio:
            raise CTFLabError("未找到 cpio，无法生成无人值守安装 initrd。")
        # macOS 自带 bsdtar/cpio 不支持 GNU cpio 的原地追加模式。Linux
        # initramfs 本身允许由多个按 4 字节对齐的 newc 归档串联，因此先生成
        # 只含 preseed.cfg 的归档，再拼接到 Debian 安装器 initrd 末尾。
        preseed_archive = work / "preseed.cpio"
        with preseed_archive.open("wb") as output:
            result = subprocess.run(
                [cpio, "-o", "-H", "newc"],
                cwd=work,
                input=b"preseed.cfg\nctflab-guest-setup.sh\n",
                stdout=output,
                stderr=subprocess.PIPE,
                check=False,
            )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise CTFLabError(f"无法生成 preseed initramfs 归档：{detail}")
        with raw_initrd.open("ab") as target, preseed_archive.open("rb") as source:
            padding = (-target.tell()) % 4
            if padding:
                target.write(b"\0" * padding)
            shutil.copyfileobj(source, target)
        with raw_initrd.open("rb") as source, gzip.open(staged_initrd, "wb", compresslevel=6) as target:
            shutil.copyfileobj(source, target)
        staged_kernel.replace(kernel_path)
        staged_initrd.chmod(0o600)
        staged_initrd.replace(initrd_path)
    return kernel_path, initrd_path


def profile_path(profile_id: str) -> Path:
    profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
    candidate = PROFILE_DIR / f"{profile_id}.yaml"
    if not candidate.exists():
        raise CTFLabError(f"未知配置：{profile_id}。可用配置：{', '.join(available_profiles())}")
    return candidate


def available_profiles() -> list[str]:
    if not PROFILE_DIR.exists():
        return []
    return sorted(path.stem for path in PROFILE_DIR.glob("*.yaml"))


def validate_profile(data: dict[str, Any], path: Path) -> None:
    """校验运行器实际会使用的白名单字段，拒绝任意 QEMU 原始参数。"""
    required = ("schema", "id", "name", "guest", "disk", "network")
    missing = [key for key in required if key not in data]
    if missing:
        raise CTFLabError(f"配置缺少字段：{path}：{', '.join(missing)}")
    if data.get("schema") != 1:
        raise CTFLabError(f"不支持的配置 schema：{path}：{data.get('schema')}")
    guest = data["guest"]
    disk = data["disk"]
    network = data["network"]
    if guest.get("architecture") not in {"x86_64", "aarch64"}:
        raise CTFLabError(f"不支持的客体架构：{path}：{guest.get('architecture')}")
    if guest.get("firmware") not in {"bios", "uefi"}:
        raise CTFLabError(f"不支持的固件：{path}：{guest.get('firmware')}")
    if guest.get("machine") not in {"pc", "virt"}:
        raise CTFLabError(f"不支持的机器类型：{path}：{guest.get('machine')}")
    try:
        memory_mb = int(guest.get("memory_mb", 0))
        cpus = int(guest.get("cpus", 0))
    except (TypeError, ValueError) as exc:
        raise CTFLabError(f"内存和 CPU 必须是整数：{path}") from exc
    if not 256 <= memory_mb <= 65536 or not 1 <= cpus <= 16:
        raise CTFLabError(f"资源配置超出允许范围：{path}：memory={memory_mb}MB cpus={cpus}")
    if disk.get("bus") not in {"ide", "sata", "scsi", "virtio", "virtio-blk"}:
        raise CTFLabError(f"不支持的磁盘总线：{path}：{disk.get('bus')}")
    allowed_controllers = {None, "lsi53c895a", "ich9-ahci"}
    if disk.get("controller") not in allowed_controllers:
        raise CTFLabError(f"不支持的磁盘控制器：{path}：{disk.get('controller')}")
    if network.get("adapter") not in {"e1000", "pcnet", "virtio-net-pci"}:
        raise CTFLabError(f"不支持的网卡型号：{path}：{network.get('adapter')}")
    mac_parts = network.get("mac", "").split(":") if isinstance(network.get("mac"), str) else []
    if len(mac_parts) != 6 or any(len(part) != 2 or any(char not in "0123456789abcdefABCDEF" for char in part) for part in mac_parts):
        raise CTFLabError(f"网卡 MAC 地址格式错误：{path}")
    for forward in network.get("host_forwards", []) or []:
        try:
            guest_port = int(forward.get("guest_port", 0))
            host_port = int(forward.get("host_port", 0))
        except (TypeError, ValueError) as exc:
            raise CTFLabError(f"端口映射必须为正整数：{path}") from exc
        if guest_port <= 0 or host_port <= 0 or host_port > 65535 or guest_port > 65535:
            raise CTFLabError(f"端口映射必须为正整数：{path}")


def load_profile(profile_id: str) -> dict[str, Any]:
    profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
    if yaml is None:
        raise CTFLabError("当前 Python 缺少 PyYAML。请使用 /opt/miniconda3/bin/python3，或安装：python3 -m pip install pyyaml")
    path = profile_path(profile_id)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise CTFLabError(f"无法读取配置：{path}\n{exc}") from exc
    if data.get("id") != profile_id:
        raise CTFLabError(f"配置文件 id 与文件名不一致：{path}")
    validate_profile(data, path)
    return data


def bool_pid_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def find_firmware(name: str) -> Path | None:
    """固件查找：受控运行时优先；运行时激活时**不回退**宿主路径，避免掩盖缺件。"""
    root = runtime_root()
    if root is not None:
        candidate = root / "share" / "qemu" / name
        return candidate if candidate.exists() else None
    candidates = [
        Path("/opt/homebrew/share/qemu") / name,
        Path("/usr/local/share/qemu") / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def qmp_execute(qmp_path: Path, execute: str, arguments: dict[str, Any] | None = None) -> Any:
    """执行一条 QMP 命令并返回 ``return`` 字段。"""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2.0)
        connection.connect(str(qmp_path))
        stream = connection.makefile("rwb", buffering=0)
        greeting = stream.readline()
        if not greeting:
            raise OSError("QMP 在握手前关闭了连接")

        def send(payload: dict[str, Any]) -> Any:
            stream.write(json.dumps(payload).encode() + b"\r\n")
            while True:
                line = stream.readline()
                if not line:
                    raise OSError("QMP 在返回结果前关闭了连接")
                message = json.loads(line)
                if "error" in message:
                    detail = message["error"].get("desc", message["error"])
                    raise CTFLabError(f"QMP {payload.get('execute')} 失败：{detail}")
                if "return" in message:
                    return message["return"]

        send({"execute": "qmp_capabilities"})
        payload: dict[str, Any] = {"execute": execute}
        if arguments:
            payload["arguments"] = arguments
        return send(payload)


def qmp_command(qmp_path: Path, execute: str, arguments: dict[str, Any] | None = None) -> None:
    """兼容无需读取结果的生命周期命令。"""
    qmp_execute(qmp_path, execute, arguments)


# stop 等待来宾关机的秒数：--graceful 超时后保留实例，普通 stop 超时后强制结束 QEMU。
GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 30
FORCED_SHUTDOWN_TIMEOUT_SECONDS = 3


def ppm_display_activity(path: Path) -> dict[str, Any]:
    """从 QEMU PPM 截图计算显示活动；只证明画面非全黑，不等价于登录成功。"""
    try:
        data = path.read_bytes()
    except OSError as exc:
        return {"active": False, "detail": str(exc)}
    if not data.startswith(b"P6"):
        return {"active": False, "detail": "不是 P6 PPM 截图"}
    index = 2
    tokens: list[bytes] = []
    while len(tokens) < 3 and index < len(data):
        while index < len(data) and data[index:index + 1].isspace():
            index += 1
        if index < len(data) and data[index:index + 1] == b"#":
            newline = data.find(b"\n", index)
            index = len(data) if newline < 0 else newline + 1
            continue
        end = index
        while end < len(data) and not data[end:end + 1].isspace():
            end += 1
        tokens.append(data[index:end])
        index = end
    if len(tokens) != 3:
        return {"active": False, "detail": "PPM 头不完整"}
    try:
        width, height, maximum = map(int, tokens)
    except ValueError:
        return {"active": False, "detail": "PPM 尺寸无法解析"}
    while index < len(data) and data[index:index + 1].isspace():
        index += 1
    pixels = data[index:]
    if maximum != 255 or len(pixels) < width * height * 3:
        return {"active": False, "detail": "PPM 像素数据不完整"}
    pixel_count = width * height
    stride_pixels = max(1, pixel_count // 30000)
    sample = [tuple(pixels[offset:offset + 3]) for offset in range(0, pixel_count * 3, stride_pixels * 3)]
    nonblack = sum(1 for red, green, blue in sample if max(red, green, blue) > 16)
    ratio = nonblack / max(1, len(sample))
    unique_colors = len(set(sample))
    active = ratio >= 0.002 and unique_colors >= 4
    return {
        "active": active,
        "width": width,
        "height": height,
        "sampled_pixels": len(sample),
        "nonblack_ratio": round(ratio, 6),
        "unique_colors": unique_colors,
        "detail": "检测到非全黑画面" if active else "画面仍接近全黑或无变化",
    }


# 受控启动回退矩阵：只使用白名单里的固件、磁盘总线与控制器组合，按顺序尝试。
# x86 先试传统 BIOS + LSI SCSI（多数老靶机），再依次尝试 IDE/SATA/VirtIO，最后才是 UEFI。
BOOT_MATRIX_SUCCESS_VERDICTS = {"service_ready", "network_and_display_candidate"}
BOOT_MATRIX_SUCCESS_SCREENS = {"login_ready"}
X86_BOOT_MATRIX: tuple[dict[str, str], ...] = (
    {"firmware": "bios", "bus": "scsi", "controller": "lsi53c895a"},
    {"firmware": "bios", "bus": "ide"},
    {"firmware": "bios", "bus": "sata", "controller": "ich9-ahci"},
    {"firmware": "bios", "bus": "virtio"},
    {"firmware": "uefi", "bus": "scsi", "controller": "lsi53c895a"},
    {"firmware": "uefi", "bus": "ide"},
    {"firmware": "uefi", "bus": "sata", "controller": "ich9-ahci"},
    {"firmware": "uefi", "bus": "virtio"},
)
AARCH64_BOOT_MATRIX: tuple[dict[str, str], ...] = (
    {"firmware": "uefi", "bus": "virtio"},
)


def matrix_candidates(architecture: str) -> tuple[dict[str, str], ...]:
    """按客体架构返回白名单候选；aarch64 只支持 UEFI + VirtIO。"""
    return AARCH64_BOOT_MATRIX if architecture == "aarch64" else X86_BOOT_MATRIX


def candidate_label(candidate: dict[str, str]) -> str:
    label = f"{candidate['firmware']}/{candidate['bus']}"
    if candidate.get("controller"):
        label += f"/{candidate['controller']}"
    return label


SCREEN_PATTERNS: dict[str, tuple[tuple[str, str], ...]] = {
    "uefi_shell": (
        ("UEFI Interactive Shell", r"uefi\s+interactive\s+shell"),
        ("Shell 提示符", r"(?:^|\s)shell\s*>"),
        ("startup.nsh", r"startup\.nsh"),
        ("UEFI Mapping Table", r"mapping\s+table"),
    ),
    "no_boot_device": (
        ("No bootable device", r"no\s+bootable\s+device"),
        ("No boot device", r"no\s+boot\s+device"),
        ("Boot failed", r"boot\s+failed"),
        ("Not a bootable disk", r"not\s+a\s+bootable\s+disk"),
        ("Operating system not found", r"operating\s+system\s+not\s+found"),
        ("Select proper boot device", r"select\s+proper\s+boot\s+device"),
    ),
    "kernel_error": (
        ("Kernel panic", r"kernel\s+panic"),
        ("Kernel not syncing", r"not\s+syncing"),
        ("Unable to mount root", r"unable\s+to\s+mount\s+root"),
        ("Cannot open root device", r"cannot\s+open\s+root\s+device"),
        ("Waiting for root device failed", r"gave\s+up\s+waiting\s+for\s+root"),
        ("Emergency mode", r"emergency\s+mode"),
    ),
    "login_ready": (
        ("Login prompt", r"(?:^|\n)[^\n]{0,80}\blogin\s*[:>]"),
        ("Login Prompts target", r"reached\s+target\s+login\s+prompts"),
        ("Graphical Interface target", r"reached\s+target\s+graphical\s+interface"),
        ("Display manager", r"(?:started|starting)\s+[^\n]{0,80}display\s+manager"),
    ),
    "boot_progress": (
        ("Starting services", r"(?:^|\n)\s*(?:\[[^\]]+\]\s*)?starting\s+"),
        ("Started services", r"(?:^|\n)\s*(?:\[[^\]]+\]\s*)?started\s+"),
        ("Mounting filesystems", r"(?:mounting|mounted|remounting)\s+"),
        ("Loading components", r"(?:loading|loaded)\s+"),
        ("Reached target", r"reached\s+target\s+"),
    ),
}

SCREEN_FAILURE_CLASSES = {"uefi_shell", "no_boot_device", "kernel_error"}
SCREEN_CLASS_LABELS = {
    "uefi_shell": "UEFI Shell",
    "no_boot_device": "未找到可启动设备",
    "kernel_error": "内核/根文件系统错误",
    "login_ready": "登录界面已就绪",
    "boot_progress": "系统仍在启动",
    "unknown": "无法确定",
}


def classify_screen_text(text: str) -> dict[str, Any]:
    """将 OCR 文本归类为启动状态，并保留可审计的命中信号。"""
    normalized = text.lower().replace("\r", "\n")
    matched: dict[str, list[str]] = {}
    for classification, patterns in SCREEN_PATTERNS.items():
        signals = [label for label, pattern in patterns if re.search(pattern, normalized, re.MULTILINE)]
        if signals:
            matched[classification] = signals

    warnings: list[str] = []
    if re.search(r"(?:\[\s*failed\s*\]|failed\s+to\s+start|dependency\s+failed)", normalized):
        warnings.append("检测到服务启动失败文字")

    classification = "unknown"
    for candidate in ("uefi_shell", "no_boot_device", "kernel_error", "login_ready", "boot_progress"):
        if candidate in matched:
            classification = candidate
            break
    signal_count = len(matched.get(classification, []))
    if classification in SCREEN_FAILURE_CLASSES:
        confidence = "high" if signal_count >= 2 else "medium"
    elif classification == "login_ready":
        confidence = "high" if signal_count >= 2 else "medium"
    elif classification == "boot_progress":
        confidence = "medium" if signal_count >= 2 else "low"
    else:
        confidence = "low"
    return {
        "classification": classification,
        "confidence": confidence,
        "matched_signals": matched.get(classification, []),
        "all_signals": matched,
        "warnings": warnings,
    }


def classify_screenshot(path: Path) -> dict[str, Any]:
    """使用本机 Tesseract 分析截图；缺少依赖时返回明确的安全降级结果。"""
    tesseract = shutil.which("tesseract")
    if not tesseract:
        return {
            "available": False,
            "engine": None,
            "classification": "unknown",
            "confidence": "low",
            "matched_signals": [],
            "all_signals": {},
            "warnings": ["未安装 Tesseract，未执行截图 OCR"],
            "text": "",
        }
    try:
        result = subprocess.run(
            [tesseract, str(path), "stdout", "-l", "eng", "--psm", "6"],
            check=False,
            text=True,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "available": False,
            "engine": "tesseract",
            "classification": "unknown",
            "confidence": "low",
            "matched_signals": [],
            "all_signals": {},
            "warnings": [f"Tesseract 执行失败：{exc}"],
            "text": "",
        }
    text = result.stdout.strip()
    classified = classify_screen_text(text)
    warnings = list(classified["warnings"])
    if result.returncode != 0:
        warnings.append(f"Tesseract 退出码 {result.returncode}：{result.stderr.strip()[:300]}")
    classified.update(
        {
            "available": result.returncode == 0,
            "engine": "tesseract",
            "warnings": warnings,
            "text": text[:12000],
        }
    )
    return classified


class LabManager:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir.expanduser().resolve()
        self.images_dir = self.state_dir / "images"
        self.runtime_dir = self.state_dir / "runtime"
        self.logs_dir = self.state_dir / "logs"
        self.pcap_dir = self.state_dir / "pcap"
        self.install_dir = self.state_dir / "install"
        self.locks_dir = self.state_dir / "locks"
        self._operation_lock_depth = 0
        self._operation_lock_handle: TextIO | None = None
        self.state_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def operation_lock(self, action: str, timeout_seconds: float = 10.0) -> Iterator[None]:
        """串行化会修改镜像、overlay、状态或实验网络的操作。

        锁文件会保留在状态目录中，但真正的所有权由内核 ``flock`` 维护；
        因此进程崩溃后不会留下需要人工删除的“死锁文件”。同一个管理器中的
        嵌套调用可重入，例如 ``reset --force`` 在持锁时调用 ``stop``。
        """
        if self._operation_lock_depth:
            self._operation_lock_depth += 1
            try:
                yield
            finally:
                self._operation_lock_depth -= 1
            return

        self.locks_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.locks_dir / "operations.lock"
        handle = lock_path.open("a+", encoding="utf-8")
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    handle.seek(0)
                    owner_text = handle.read().strip()
                    handle.close()
                    owner = "另一个 CTFLab 进程"
                    if owner_text:
                        try:
                            metadata = json.loads(owner_text)
                            owner = f"PID {metadata.get('pid', '?')} 的 {metadata.get('action', '操作')}"
                        except json.JSONDecodeError:
                            pass
                    raise CTFLabError(f"等待操作锁超时：{owner}仍在执行；请稍后重试。")
                time.sleep(0.05)

        self._operation_lock_handle = handle
        self._operation_lock_depth = 1
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({"pid": os.getpid(), "action": action, "acquired_at": now_iso()}, ensure_ascii=False))
        handle.flush()
        try:
            yield
        finally:
            self._operation_lock_depth = 0
            self._operation_lock_handle = None
            handle.seek(0)
            handle.truncate()
            handle.flush()
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def image_state_path(self, profile_id: str) -> Path:
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        return self.images_dir / profile_id / "image.json"

    def runtime_state_path(self, profile_id: str) -> Path:
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        return self.runtime_dir / profile_id / "run.json"

    def network_state_path(self, lab_port: int) -> Path:
        return self.runtime_dir / f"network-{lab_port}.json"

    def installer_state_path(self, profile_id: str) -> Path:
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        return self.install_dir / profile_id / "install.json"

    def image_state(self, profile_id: str) -> dict[str, Any] | None:
        return read_json(self.image_state_path(profile_id))

    def runtime_state(self, profile_id: str) -> dict[str, Any] | None:
        return read_json(self.runtime_state_path(profile_id))

    def network_state(self, lab_port: int) -> dict[str, Any] | None:
        return read_json(self.network_state_path(lab_port))

    def installer_state(self, profile_id: str) -> dict[str, Any] | None:
        return read_json(self.installer_state_path(profile_id))

    def imported_profiles(self) -> list[str]:
        return [profile_id for profile_id in available_profiles() if self.image_state(profile_id)]

    def discover_source(self, source: Path) -> Path:
        source = source.expanduser().resolve()
        if not source.exists():
            raise CTFLabError(f"镜像不存在：{source}")
        if source.is_file():
            return source
        known = ["*.qcow2", "*.vmdk", "*.vdi", "*.vhd", "*.vhdx", "*.raw", "*.img", "*.ova"]
        matches: list[Path] = []
        for pattern in known:
            matches.extend(sorted(source.glob(pattern)))
        if not matches:
            raise CTFLabError(f"目录中没有找到支持的磁盘文件：{source}")
        if len(matches) > 1:
            qcow2 = [item for item in matches if item.suffix.lower() == ".qcow2"]
            if len(qcow2) == 1:
                return qcow2[0]
            raise CTFLabError("目录中有多个候选磁盘，请直接传入具体文件路径：\n" + "\n".join(str(item) for item in matches))
        return matches[0]

    def import_image(self, profile_id: str, source_arg: str, *, expect_sha256: str | None = None,
                     manifest: str | Path | None = None,
                     nvram: str | Path | None = None) -> dict[str, Any]:
        with self.operation_lock(f"导入 {profile_id}"):
            return self._import_image_unlocked(profile_id, source_arg, expect_sha256=expect_sha256,
                                               manifest=manifest, nvram=nvram)

    def distribution_expectations(self, profile_id: str, expect_sha256: str | None,
                                  manifest: str | Path | None,
                                  nvram: str | Path | None) -> dict[str, Any]:
        """解析来源校验计划：显式哈希与分发清单必须一致；不一致立即失败，不做取舍。"""
        import ctflab_dist  # noqa: PLC0415

        plan: dict[str, Any] = {"expect_sha256": None, "manifest": None, "nvram": None,
                                "nvram_expected": None, "method": None, "nvram_manifest": None}
        manifest_path = Path(manifest).expanduser() if manifest else None
        if manifest_path is not None:
            try:
                data = ctflab_dist.load_manifest(manifest_path)
            except ctflab_dist.DistError as exc:
                raise CTFLabError(str(exc)) from exc
            entry = ctflab_dist.expected_for_profile(data, profile_id, ctflab_dist.BASE_ROLE)
            if entry is None:
                available = ", ".join(sorted({str(item.get("profile")) for item in data["entries"]}))
                raise CTFLabError(
                    f"分发清单中没有 {profile_id} 的基盘条目：{manifest_path}（清单内 profile：{available or '无'}）")
            plan["expect_sha256"] = str(entry["sha256"]).lower()
            plan["manifest"] = manifest_path
            plan["method"] = "manifest"
            nvram_entry = ctflab_dist.expected_for_profile(data, profile_id, ctflab_dist.NVRAM_ROLE)
            if nvram_entry is not None:
                plan["nvram"] = manifest_path.parent / str(nvram_entry["file"])
                plan["nvram_expected"] = str(nvram_entry["sha256"]).lower()
                plan["nvram_manifest"] = manifest_path
        if expect_sha256:
            value = expect_sha256.strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                raise CTFLabError(f"--expect-sha256 必须是 64 位十六进制摘要：{expect_sha256!r}")
            if plan["expect_sha256"] and plan["expect_sha256"] != value:
                raise CTFLabError(
                    "--expect-sha256 与分发清单登记的期望值不一致，拒绝导入：\n"
                    f"  清单：{plan['expect_sha256']}\n  参数：{value}")
            plan["expect_sha256"] = value
            if plan["method"] is None:
                plan["method"] = "expect-sha256"
        if nvram:
            explicit = Path(nvram).expanduser()
            if plan["nvram"] is not None and explicit != plan["nvram"]:
                raise CTFLabError(
                    "--nvram 与分发清单登记的 NVRAM 模板不一致，拒绝导入：\n"
                    f"  清单：{plan['nvram']}\n  参数：{explicit}")
            plan["nvram"] = explicit
            plan["nvram_expected"] = plan["nvram_expected"] if plan["nvram_manifest"] else None
        return plan

    def _import_image_unlocked(self, profile_id: str, source_arg: str, *,
                               expect_sha256: str | None = None,
                               manifest: str | Path | None = None,
                               nvram: str | Path | None = None) -> dict[str, Any]:
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        profile = load_profile(profile_id)
        plan = self.distribution_expectations(profile_id, expect_sha256, manifest, nvram)
        source = self.discover_source(Path(source_arg))
        source_for_convert = source
        temporary_dir: tempfile.TemporaryDirectory[str] | None = None
        try:
            if source.suffix.lower() == ".ova":
                temporary_dir = tempfile.TemporaryDirectory(prefix="ctflab-ova-")
                with tarfile.open(source, "r:*") as archive:
                    members = [member for member in archive.getmembers() if member.isfile() and member.name.lower().endswith((".vmdk", ".qcow2", ".vdi", ".vhd", ".vhdx"))]
                    if not members:
                        raise CTFLabError(f"OVA 内没有找到可用磁盘：{source}")
                    member = members[0]
                    member_path = Path(member.name)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        raise CTFLabError(f"OVA 内含有不安全的磁盘路径：{member.name}")
                    archive.extract(member, temporary_dir.name)
                    source_for_convert = Path(temporary_dir.name) / member.name
            source_hash = sha256_file(source)
            updates: dict[str, Any] = {}
            if plan["expect_sha256"]:
                if source_hash != plan["expect_sha256"]:
                    raise CTFLabError(
                        "来源镜像 SHA-256 与期望值不一致，拒绝导入（请重新下载，不要跳过校验）：\n"
                        f"  文件：{source}\n"
                        f"  期望：{plan['expect_sha256']}\n"
                        f"  实际：{source_hash}")
                updates["source_verification"] = {
                    "expected_sha256": plan["expect_sha256"],
                    "actual_sha256": source_hash,
                    "method": plan["method"],
                    "manifest": str(plan["manifest"]) if plan["manifest"] else None,
                    "verified_at": now_iso(),
                }
            if plan["nvram"]:
                nvram_path = Path(plan["nvram"]).expanduser()
                if not nvram_path.is_file():
                    raise CTFLabError(f"UEFI NVRAM 模板不存在：{nvram_path}")
                nvram_hash = sha256_file(nvram_path)
                if plan["nvram_expected"] and nvram_hash != plan["nvram_expected"]:
                    raise CTFLabError(
                        "UEFI NVRAM 模板 SHA-256 与分发清单不一致，拒绝导入：\n"
                        f"  文件：{nvram_path}\n"
                        f"  期望：{plan['nvram_expected']}\n"
                        f"  实际：{nvram_hash}")
                updates["uefi_vars_path"] = str(nvram_path)
                updates["uefi_vars_sha256"] = nvram_hash
            existing = self.image_state(profile_id)
            if (
                existing
                and existing.get("source_sha256") == source_hash
                and Path(str(existing.get("base_path", ""))).exists()
            ):
                # 同一来源的重复导入必须是幂等的，尤其不能把已验证的来宾修复基盘
                # 悄悄切回最初转换出的未修复基盘；同时不得静默信任缺少 base_sha256 的旧基盘。
                return self._reuse_existing_base(profile_id, existing, source_for_convert,
                                                 updates=updates)
            info = qemu_info(source_for_convert)
            source_format = str(info.get("format") or "")
            if not source_format:
                raise CTFLabError(f"无法识别镜像格式：{source_for_convert}")
            image_dir = self.images_dir / profile_id
            image_dir.mkdir(parents=True, exist_ok=True)
            base_path = image_dir / f"base-{source_hash[:12]}.qcow2"
            evidence = "converted"
            if base_path.exists():
                # 目标基盘已存在但没有可信登记：不得直接计算当前哈希并登记。
                # 只有 qemu-img compare 证明它与来源镜像的来宾可见内容一致时才登记。
                if not compare_disk_images(source_for_convert, source_format, base_path):
                    raise CTFLabError(
                        f"已存在 {base_path.name}，但没有可信的 base_sha256 登记，"
                        "且 qemu-img compare 未能证明它与来源镜像的来宾可见内容一致；"
                        "拒绝登记该文件。请人工核对该文件，或等待后续专门的完整性迁移流程。"
                    )
                evidence = "qemu-img-compare"
                base_path.chmod(0o444)
            else:
                self._convert_base_image(source_for_convert, source_format, base_path)
            destination_info = qemu_info(base_path)
            state = {
                "schema": 1,
                "profile_id": profile_id,
                "profile_path": str(profile_path(profile_id)),
                "source_path": str(source),
                "source_sha256": source_hash,
                "source_format": source_format,
                "base_path": str(base_path),
                "base_sha256": sha256_file(base_path),
                "base_sha256_evidence": evidence,
                "virtual_size": destination_info.get("virtual-size"),
                "imported_at": now_iso(),
                "guest": profile.get("guest", {}),
                **updates,
            }
            write_json(self.image_state_path(profile_id), state)
            return state
        finally:
            if temporary_dir is not None:
                temporary_dir.cleanup()

    def _apply_state_updates(self, profile_id: str, state: dict[str, Any],
                             updates: dict[str, Any] | None) -> dict[str, Any]:
        """把来源校验/NVRAM 等幂等元数据写回状态；没有变化时不写盘。"""
        if not updates:
            return state
        merged = dict(state)
        merged.update(updates)
        if merged != state:
            write_json(self.image_state_path(profile_id), merged)
        return merged

    def _reuse_existing_base(self, profile_id: str, existing: dict[str, Any], source_for_convert: Path,
                             *, updates: dict[str, Any] | None = None) -> dict[str, Any]:
        """重复导入：已登记则核对；未登记则只在内容比对证明一致时补登记。"""
        base_path = Path(str(existing.get("base_path")))
        registered = str(existing.get("base_sha256") or "")
        if registered:
            if sha256_file(base_path) != registered:
                raise CTFLabError(
                    f"{profile_id} 的基础镜像与登记 base_sha256 不一致；拒绝静默重新登记。"
                    "请人工核对，或等待后续专门的完整性迁移流程。"
                )
            return self._apply_state_updates(profile_id, existing, updates)
        source_format = str(existing.get("source_format") or "")
        if not source_format:
            source_format = str(qemu_info(source_for_convert).get("format") or "")
        if not source_format or not compare_disk_images(source_for_convert, source_format, base_path):
            raise CTFLabError(
                f"{profile_id} 的导入记录缺少 base_sha256，且 qemu-img compare 未能证明现有基盘与"
                "来源镜像的来宾可见内容一致；拒绝登记该文件。请人工核对，或等待后续专门的完整性迁移流程。"
            )
        state = dict(existing)
        state["base_sha256"] = sha256_file(base_path)
        state["base_sha256_evidence"] = "qemu-img-compare"
        state.update(updates or {})
        base_path.chmod(0o444)
        write_json(self.image_state_path(profile_id), state)
        return state

    def _convert_base_image(self, source: Path, source_format: str, base_path: Path) -> None:
        """新转换写入临时文件，info/check 通过后再排他发布，并设为只读。"""
        temporary_base = base_path.parent / f"{base_path.stem}.partial-{os.getpid()}-{int(time.time() * 1000)}.qcow2"
        try:
            run_command(
                [qemu_img_path(), "convert", "-f", source_format, "-O", "qcow2", str(source), str(temporary_base)],
                capture=False,
            )
            if str(qemu_info(temporary_base).get("format") or "") != "qcow2":
                raise CTFLabError("基础镜像转换结果不是 qcow2，拒绝发布。")
            run_command([qemu_img_path(), "check", "-q", str(temporary_base)])
            try:
                exclusive_rename(temporary_base, base_path)
            except PublishError as exc:
                raise CTFLabError(
                    f"发布基础镜像失败：{exc}。目标可能是外部并发创建的文件，请人工核对。"
                ) from exc
            base_path.chmod(0o444)
        finally:
            if temporary_base.exists():
                temporary_base.unlink(missing_ok=True)

    def installer_command(
        self,
        profile_id: str,
        profile: dict[str, Any],
        iso_path: Path,
        target_path: Path,
        vars_path: Path,
        qmp_path: Path,
        *,
        unattended: bool,
        headless: bool,
        kernel_path: Path | None = None,
        initrd_path: Path | None = None,
    ) -> list[str]:
        qemu = which_any(QEMU_ARM_NAMES)
        code_path = find_firmware("edk2-aarch64-code.fd")
        if not qemu or not code_path:
            raise CTFLabError("缺少 qemu-system-aarch64 或 ARM64 UEFI 固件。")
        guest = profile.get("guest", {})
        command = [
            qemu,
            "-name", f"CTFLab-{profile_id}-Installer",
            "-machine", str(guest.get("machine", "virt")),
            "-accel", "hvf",
            "-cpu", "host",
            "-smp", str(guest.get("cpus", 4)),
            "-m", str(guest.get("memory_mb", 5120)),
            "-drive", f"if=pflash,format=raw,unit=0,file={code_path},readonly=on",
            "-drive", f"if=pflash,format=raw,unit=1,file={vars_path}",
            "-drive", f"file={target_path},if=none,format=qcow2,id=disk0,discard=unmap",
            "-device", "virtio-blk-pci,drive=disk0",
            "-device", "virtio-scsi-pci,id=scsi0",
            "-drive", f"file={iso_path},if=none,format=raw,media=cdrom,readonly=on,id=cd0",
            "-device", "scsi-cd,drive=cd0,bus=scsi0.0",
            "-device", "virtio-gpu-pci",
            "-device", "ramfb",
            "-device", "qemu-xhci",
            "-device", "usb-kbd",
            "-device", "usb-tablet",
            "-netdev", "user,id=installnet,restrict=on",
            "-device", "virtio-net-pci,netdev=installnet",
        ]
        if unattended:
            if not kernel_path or not initrd_path:
                raise CTFLabError("无人值守安装缺少内核或 initrd。")
            command += [
                "-kernel", str(kernel_path),
                "-initrd", str(initrd_path),
                "-append",
                (
                    "auto=true priority=critical locale=en_US.UTF-8 keymap=us "
                    "hostname=kali domain=local net.ifnames=0 "
                    "DEBIAN_FRONTEND=noninteractive console=tty0 console=ttyAMA0,115200 "
                    "preseed/file=/preseed.cfg simple-cdd/profiles=kali,offline "
                    "desktop=xfce --- quiet"
                ),
            ]
        else:
            command += ["-boot", "order=d,menu=on"]
        command += [
            "-display", "none" if headless else "cocoa",
            "-serial", "stdio",
            "-qmp", f"unix:{qmp_path},server=on,wait=off",
            "-no-reboot",
        ]
        return command

    def start_install(
        self,
        profile_id: str,
        iso_arg: str,
        *,
        disk_size_gb: int = 64,
        unattended: bool = False,
        headless: bool = False,
        resume: bool = False,
        confirm_reinstall: bool = False,
    ) -> dict[str, Any]:
        with self.operation_lock(f"安装 {profile_id}"):
            profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
            profile = load_profile(profile_id)
            if profile.get("guest", {}).get("architecture") != "aarch64":
                raise CTFLabError("ISO 安装流程当前只允许 ARM64 配置。")
            if self.image_state(profile_id):
                raise CTFLabError(f"{profile_id} 已有基础镜像，无需再次安装。")
            if not 20 <= disk_size_gb <= 256:
                raise CTFLabError("安装磁盘容量必须位于 20～256 GiB。")
            if headless and not unattended:
                raise CTFLabError("后台安装必须同时使用 --unattended，否则无法操作安装界面。")
            running = self.runtime_state(profile_id)
            if running and bool_pid_alive(int(running.get("pid", 0))):
                raise CTFLabError(f"{profile_id} 正在正常运行，请先 stop。")

            old = self.installer_state(profile_id)
            if old and bool_pid_alive(int(old.get("pid", 0))):
                return old
            if old and not resume:
                raise CTFLabError(
                    f"{profile_id} 已有停止的安装目标；使用 install --resume 重新启动安装器，"
                    "确认完成后使用 finalize-install。"
                )
            if old and unattended and not confirm_reinstall:
                raise CTFLabError("自动安装重新启动会重新分区已有安装目标；如确需重装，增加 --confirm-reinstall。")

            if unattended:
                build_unattended_preseed()
            iso_path = Path(iso_arg).expanduser().resolve()
            iso = validate_arm64_installer_iso(iso_path)
            install_root = self.install_dir / profile_id
            install_root.mkdir(parents=True, exist_ok=True)
            if old:
                if old.get("iso_sha256") != iso["sha256"]:
                    raise CTFLabError("--resume 指定的 ISO 与原安装任务 SHA-256 不一致。")
                target_path = Path(str(old["target_path"]))
                vars_path = Path(str(old["uefi_vars_path"]))
                if not target_path.is_file() or not vars_path.is_file():
                    raise CTFLabError("已有安装目标或 UEFI NVRAM 缺失，拒绝重新启动。")
            else:
                target_path = install_root / f"target-{iso['sha256'][:12]}.qcow2"
                vars_path = install_root / f"uefi-vars-{iso['sha256'][:12]}.fd"
                if target_path.exists():
                    raise CTFLabError(f"发现未登记的安装目标，拒绝覆盖：{target_path}")
                vars_template = find_firmware("edk2-arm-vars.fd")
                if not vars_template:
                    raise CTFLabError("未找到 ARM64 UEFI NVRAM 模板 edk2-arm-vars.fd。")
                run_command([qemu_img_path(), "create", "-f", "qcow2", str(target_path), f"{disk_size_gb}G"])
                shutil.copy2(vars_template, vars_path)

            qmp_path = install_root / "installer-qmp.sock"
            qmp_path.unlink(missing_ok=True)
            log_path = self.logs_dir / f"{profile_id}-installer.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_offset = log_path.stat().st_size if log_path.is_file() else 0
            state = {
                "schema": 1,
                "profile_id": profile_id,
                "pid": 0,
                "iso_path": str(iso_path),
                "iso_sha256": iso["sha256"],
                "target_path": str(target_path),
                "uefi_vars_path": str(vars_path),
                "qmp_path": str(qmp_path),
                "log_path": str(log_path),
                "log_offset": log_offset,
                "disk_size_gb": disk_size_gb if not old else old.get("disk_size_gb", disk_size_gb),
                "unattended": unattended,
                "headless": headless,
                "started_at": now_iso(),
                "status": "preparing",
            }
            write_json(self.installer_state_path(profile_id), state)

            kernel_path: Path | None = None
            initrd_path: Path | None = None
            if unattended:
                kernel_path, initrd_path = prepare_unattended_installer_assets(
                    iso_path,
                    str(iso["sha256"]),
                    install_root / "assets",
                )
            command = self.installer_command(
                profile_id,
                profile,
                iso_path,
                target_path,
                vars_path,
                qmp_path,
                unattended=unattended,
                headless=headless,
                kernel_path=kernel_path,
                initrd_path=initrd_path,
            )
            log_handle = log_path.open("a", encoding="utf-8")
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    env={key: value for key, value in os.environ.items() if key != "CTFLAB_INSTALL_PASSWORD"},
                    start_new_session=True,
                    text=True,
                )
            except OSError as exc:
                raise CTFLabError(f"无法启动 {profile_id} 安装器：{exc}") from exc
            finally:
                log_handle.close()
            time.sleep(0.5)
            if process.poll() is not None:
                state["status"] = "failed"
                state["exit_code"] = process.returncode
                write_json(self.installer_state_path(profile_id), state)
                detail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
                raise CTFLabError(f"安装器启动失败（退出码 {process.returncode}）：\n{detail}")
            state.update({
                "pid": process.pid,
                "status": "installing",
            })
            write_json(self.installer_state_path(profile_id), state)
            return state

    def install_status(self, profile_id: str) -> dict[str, Any]:
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        state = self.installer_state(profile_id)
        if not state:
            raise CTFLabError(f"{profile_id} 没有安装任务。")
        result = dict(state)
        running = bool_pid_alive(int(state.get("pid", 0)))
        result["running"] = running
        qmp_value = str(state.get("qmp_path") or "")
        qmp_path = Path(qmp_value) if qmp_value else None
        if running and qmp_path and qmp_path.exists():
            try:
                result["qmp_status"] = qmp_execute(qmp_path, "query-status")
                blocks = qmp_execute(qmp_path, "query-blockstats")
                result["disk_io"] = {
                    item["device"]: {key: item.get("stats", {}).get(key, 0) for key in ("rd_bytes", "wr_bytes", "failed_wr_operations")}
                    for item in blocks if item.get("device") in {"disk0", "cd0"}
                }
            except (OSError, CTFLabError, json.JSONDecodeError) as exc:
                result["qmp_error"] = str(exc)
        target_value = str(state.get("target_path") or "")
        target_path = Path(target_value) if target_value else None
        if target_path and target_path.is_file():
            info = qemu_info(target_path, force_share=running)
            result["target_actual_size"] = info.get("actual-size")
            result["target_virtual_size"] = info.get("virtual-size")
        log_value = str(state.get("log_path") or "")
        log_path = Path(log_value) if log_value else None
        log_tail = ""
        if log_path and log_path.is_file():
            with log_path.open("rb") as handle:
                handle.seek(int(state.get("log_offset") or 0))
                log_tail = handle.read()[-12000:].decode("utf-8", errors="replace")
        result["completion_hint"] = bool(
            re.search(r"installation\s+(?:is\s+)?complete|rebooting\s+the\s+system|restarting\s+system", log_tail, re.IGNORECASE)
        )
        result["status"] = "installing" if running else (
            "finalized" if state.get("status") == "finalized" else
            "completed_candidate" if result["completion_hint"] else state.get("status", "stopped")
        )
        result["log_tail"] = log_tail[-2000:]
        return result

    def stop_install(self, profile_id: str) -> bool:
        with self.operation_lock(f"停止安装 {profile_id}"):
            state = self.installer_state(profile_id)
            if not state:
                return False
            pid = int(state.get("pid", 0))
            qmp_path = Path(str(state.get("qmp_path", "")))
            if bool_pid_alive(pid):
                try:
                    if qmp_path.exists():
                        qmp_command(qmp_path, "quit")
                except (OSError, CTFLabError):
                    pass
                deadline = time.monotonic() + 3
                while bool_pid_alive(pid) and time.monotonic() < deadline:
                    time.sleep(0.1)
                if bool_pid_alive(pid):
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                deadline = time.monotonic() + 3
                while bool_pid_alive(pid) and time.monotonic() < deadline:
                    time.sleep(0.1)
                if bool_pid_alive(pid):
                    raise CTFLabError("安装器仍未退出，保留运行状态；请检查进程后重试。")
            state["status"] = "stopped"
            state["stopped_at"] = now_iso()
            write_json(self.installer_state_path(profile_id), state)
            return True

    def finalize_install(self, profile_id: str, *, confirmed: bool = False, from_runtime: bool = False) -> dict[str, Any]:
        with self.operation_lock(f"完成安装 {profile_id}"):
            profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
            if not confirmed:
                raise CTFLabError("完成登记需要 --confirm，确认安装器已经正常结束。")
            previous = self.image_state(profile_id)
            if previous and not from_runtime:
                raise CTFLabError(f"{profile_id} 已存在基础镜像。")
            install = self.install_status(profile_id)
            if install["running"]:
                raise CTFLabError("安装器仍在运行；请等待自动重启退出，或先执行 stop-install。")
            target_path = Path(str(install["target_path"]))
            vars_source = Path(str(install["uefi_vars_path"]))
            actual_size = int(install.get("target_actual_size") or 0)
            runtime_dir = self.runtime_dir / profile_id
            if from_runtime:
                if not previous or previous.get("source_format") != "iso-installer":
                    raise CTFLabError("--from-runtime 仅用于固化通过 install 创建的 Kali 后续配置。")
                runtime = self.runtime_state(profile_id) or {}
                if bool_pid_alive(int(runtime.get("pid", 0))):
                    raise CTFLabError("固化前请正常关闭 Kali 并执行 stop。")
                target_path = runtime_dir / "overlay.qcow2"
                vars_source = runtime_dir / "uefi-vars.fd"
                if not target_path.is_file() or not vars_source.is_file():
                    raise CTFLabError("未找到可固化的运行磁盘或 UEFI NVRAM。")
                # overlay 的物理尺寸可以很小；验收的是完整 backing 链的容量。
                if qemu_info(target_path).get("full-backing-filename") != previous["base_path"]:
                    raise CTFLabError("运行磁盘与当前基础镜像不匹配，拒绝固化。")
            elif install.get("unattended") and not install.get("completion_hint"):
                raise CTFLabError("没有检测到自动安装正常结束的日志，不能把半成品登记为基盘。")
            if actual_size < 512 * 1024 * 1024:
                raise CTFLabError("安装目标写入量不足 512MiB，拒绝把空盘登记为基础镜像。")
            run_command([qemu_img_path(), "check", "-q", str(target_path)])
            target_hash = sha256_file(target_path)
            image_dir = self.images_dir / profile_id
            image_dir.mkdir(parents=True, exist_ok=True)
            base_path = image_dir / f"base-{target_hash[:12]}-installed.qcow2"
            if not base_path.exists():
                temporary_base = base_path.with_suffix(".partial.qcow2")
                run_command([qemu_img_path(), "convert", "-O", "qcow2", str(target_path), str(temporary_base)])
                run_command([qemu_img_path(), "check", "-q", str(temporary_base)])
                temporary_base.replace(base_path)
            base_path.chmod(0o444)
            vars_path = image_dir / f"uefi-vars-{target_hash[:12]}.fd"
            if not vars_path.exists():
                shutil.copy2(vars_source, vars_path)
            profile = load_profile(profile_id)
            destination_info = qemu_info(base_path)
            state = {
                "schema": 1,
                "profile_id": profile_id,
                "profile_path": str(profile_path(profile_id)),
                "source_path": install["iso_path"],
                "source_sha256": install["iso_sha256"],
                "source_format": "iso-installer",
                "installed_disk_sha256": target_hash,
                "base_path": str(base_path),
                "base_sha256": sha256_file(base_path),
                "uefi_vars_path": str(vars_path),
                "uefi_vars_sha256": sha256_file(vars_path),
                "virtual_size": destination_info.get("virtual-size"),
                "imported_at": now_iso(),
                "verification_status": "candidate",
                "guest": profile.get("guest", {}),
            }
            if from_runtime:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                archive = self.install_dir / profile_id / f"runtime-before-finalize-{stamp}"
                state["previous_base_path"] = previous["base_path"]
                state["archived_runtime_path"] = str(archive)
                runtime_dir.rename(archive)
                try:
                    write_json(archive / "previous-image.json", previous)
                    write_json(self.image_state_path(profile_id), state)
                except Exception:
                    archive.rename(runtime_dir)
                    raise
            else:
                write_json(self.image_state_path(profile_id), state)
            install_state = self.installer_state(profile_id) or {}
            install_state["status"] = "finalized"
            install_state["finalized_at"] = now_iso()
            install_state["base_path"] = str(base_path)
            write_json(self.installer_state_path(profile_id), install_state)
            return state

    def ensure_overlay(self, profile_id: str) -> Path:
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        image = self.image_state(profile_id)
        if not image:
            raise CTFLabError(f"配置 {profile_id} 尚未导入镜像，请先执行：ctflab import {profile_id} <镜像路径>")
        base_path = Path(image["base_path"])
        if not base_path.exists():
            raise CTFLabError(f"基础镜像已丢失：{base_path}")
        instance_dir = self.runtime_dir / profile_id
        instance_dir.mkdir(parents=True, exist_ok=True)
        overlay = instance_dir / "overlay.qcow2"
        if not overlay.exists():
            run_command([qemu_img_path(), "create", "-f", "qcow2", "-F", "qcow2", "-b", str(base_path), str(overlay)])
        else:
            overlay_info = qemu_info(overlay)
            backing = overlay_info.get("full-backing-filename") or overlay_info.get("backing-filename")
            if not backing or Path(str(backing)).resolve() != base_path.resolve():
                raise CTFLabError(
                    f"{profile_id} 的 overlay 指向旧基础镜像，请先执行：ctflab reset {profile_id}"
                )
        return overlay

    # 各架构的 UEFI 固件代码与 NVRAM 模板（受控回退矩阵只使用这里的白名单文件）。
    UEFI_FIRMWARE = {
        "aarch64": ("edk2-aarch64-code.fd", "edk2-arm-vars.fd"),
        "x86_64": ("edk2-x86_64-code.fd", "edk2-i386-vars.fd"),
    }

    def ensure_uefi_vars(self, profile_id: str, architecture: str | None = None) -> tuple[Path, Path]:
        """为实例创建可重置的 UEFI NVRAM 副本；架构决定固件与模板。"""
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        if architecture is None:
            architecture = str(load_profile(profile_id).get("guest", {}).get("architecture", "aarch64"))
        code_name, vars_name = self.UEFI_FIRMWARE.get(architecture, self.UEFI_FIRMWARE["aarch64"])
        code_path = find_firmware(code_name)
        if not code_path:
            raise CTFLabError(f"未找到 UEFI 固件代码 {code_name}。")
        image = self.image_state(profile_id) or {}
        configured_vars = image.get("uefi_vars_path") if architecture == "aarch64" else None
        vars_source = Path(str(configured_vars)) if configured_vars else find_firmware(vars_name)
        if not vars_source or not vars_source.exists():
            raise CTFLabError(f"未找到 UEFI NVRAM 模板 {vars_name}。")
        # aarch64 沿用历史文件名，避免破坏 finalize-install --from-runtime 的既有路径。
        file_name = "uefi-vars.fd" if architecture == "aarch64" else f"uefi-vars-{architecture}.fd"
        runtime_vars = self.runtime_dir / profile_id / file_name
        runtime_vars.parent.mkdir(parents=True, exist_ok=True)
        if not runtime_vars.exists():
            shutil.copy2(vars_source, runtime_vars)
        return code_path, runtime_vars

    def running_states(self) -> list[dict[str, Any]]:
        result = []
        for profile_id in available_profiles():
            state = self.runtime_state(profile_id)
            if state and bool_pid_alive(int(state.get("pid", 0))):
                state = dict(state)
                state["profile_id"] = profile_id
                result.append(state)
        return result

    def allocate_lab_port(self) -> int:
        used = {int(state.get("lab_port")) for state in self.running_states() if state.get("lab_port")}
        for candidate in range(23400, 23500):
            if candidate not in used:
                return candidate
        raise CTFLabError("没有可用的实验网端口，请先停止旧的靶场实例。")

    def management_mac(self, profile_id: str) -> str:
        digest = hashlib.sha256(("mgmt:" + profile_id).encode()).digest()
        return "52:54:00:%02x:%02x:%02x" % (digest[0], digest[1], digest[2])

    def lab_mac(self, profile_id: str) -> str:
        return self.management_mac("lab:" + PROFILE_ALIASES.get(profile_id, profile_id))

    def allocate_lab_ip(self) -> str:
        used: set[str] = set()
        for profile_id in available_profiles():
            try:
                address = load_profile(profile_id).get("network", {}).get("lab_ip")
            except CTFLabError:
                continue
            if address:
                used.add(str(address))
        for host in range(30, 240):
            candidate = f"192.168.242.{host}"
            if candidate not in used:
                return candidate
        raise CTFLabError("192.168.242.0/24 中没有可分配的候选地址。")

    def ensure_network(
        self,
        profile_ids: list[str],
        lab_port: int,
        *,
        pcap_path: Path | None = None,
        max_frames_per_second: int = 10000,
    ) -> dict[str, Any]:
        """启动当前实验网的无 root 二层交换机/DHCP 服务，并返回网络状态。"""
        profile_ids = list(dict.fromkeys(PROFILE_ALIASES.get(profile_id, profile_id) for profile_id in profile_ids))
        state_path = self.network_state_path(lab_port)
        old = self.network_state(lab_port)
        if old and bool_pid_alive(int(old.get("pid", 0))):
            if pcap_path and not old.get("pcap_path"):
                raise CTFLabError("实验网已在未抓包模式下运行；请先 stop --all，再使用 run --pcap 重新启动。")
            return old
        leases: list[str] = []
        # 服务器启动后还会有新节点接入，因此一次注册全部内置配置的固定租约。
        for profile_id in available_profiles():
            profile = load_profile(profile_id)
            lab_ip = profile.get("network", {}).get("lab_ip")
            if lab_ip:
                leases.append(f"{profile['network']['mac']}={lab_ip}")
        command = [sys.executable, str(NETWORK_SCRIPT), "--port", str(lab_port), "--state", str(state_path)]
        command += ["--max-frames-per-second", str(max_frames_per_second)]
        if pcap_path:
            command += ["--pcap", str(pcap_path)]
        for lease in leases:
            command += ["--lease", lease]
        log_path = self.logs_dir / f"network-{lab_port}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("a", encoding="utf-8")
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
            )
        except OSError as exc:
            log_handle.close()
            raise CTFLabError(f"无法启动实验网交换机/DHCP：{exc}") from exc
        finally:
            log_handle.close()
        time.sleep(0.2)
        if process.poll() is not None:
            detail = log_path.read_text(encoding="utf-8", errors="replace").strip()
            raise CTFLabError(f"实验网交换机/DHCP 未能启动（退出码 {process.returncode}）。{detail}")
        # 网络子进程是状态文件的唯一写入者，避免父子进程竞争覆盖 leases 字典。
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            state = self.network_state(lab_port)
            if state and int(state.get("pid", 0)) == process.pid:
                return state
            time.sleep(0.05)
        return {"pid": process.pid, "port": lab_port, "log_path": str(log_path), "leases": {}}

    def stop_network(self, lab_port: int) -> None:
        state_path = self.network_state_path(lab_port)
        state = self.network_state(lab_port)
        if not state:
            return
        pid = int(state.get("pid", 0))
        if bool_pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 2
            while bool_pid_alive(pid) and time.monotonic() < deadline:
                time.sleep(0.1)
            if bool_pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if state_path.exists():
            state_path.unlink()

    def dhcp_lease(self, profile_id: str) -> str | None:
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        runtime = self.runtime_state(profile_id)
        if not runtime:
            return None
        network = self.network_state(int(runtime.get("lab_port", 0)))
        if not network:
            return None
        leases = network.get("leases", {})
        profile = load_profile(profile_id)
        return leases.get(profile.get("network", {}).get("mac"))

    @staticmethod
    def probe_spice(qemu: str) -> dict[str, Any]:
        """探测当前 QEMU 是否具备路径 B 所需的 SPICE 能力。

        `-display help` 负责显示后端；`-device help` 负责 virtio-serialport；最后用
        一个暂停的最小实例验证 `spicevmc` chardev。探测只读取帮助/启动参数，不运行
        来宾，也不创建持久状态。结果故意保留错误文本，供 CLI 给出可操作的失败原因。
        """
        result: dict[str, Any] = {
            "qemu": qemu,
            "spice_display": False,
            "spicevmc": False,
            "virtserialport": False,
            "client": bool(spice_client_path()),
            "errors": [],
        }
        try:
            display = subprocess.run([qemu, "-display", "help"], check=False,
                                     capture_output=True, text=True, timeout=5)
            display_text = f"{display.stdout}\n{display.stderr}"
            # QEMU 11.x 在 Cocoa 构建中把本机 SPICE 图形后端列为
            # `spice-app`；它仍然提供 `-spice unix=...` 服务端，因此不能只匹配
            # 旧版本曾使用的单独 `spice` 行。
            result["spice_display"] = bool(re.search(r"(?mi)^\s*spice(?:-app)?\s*$", display_text))
            if display.returncode != 0 and not result["spice_display"]:
                result["errors"].append(f"-display help 退出码 {display.returncode}")
        except (OSError, subprocess.SubprocessError) as exc:
            result["errors"].append(f"无法执行 -display help：{exc}")

        try:
            devices = subprocess.run([qemu, "-device", "help"], check=False,
                                     capture_output=True, text=True, timeout=5)
            device_text = f"{devices.stdout}\n{devices.stderr}"
            result["virtserialport"] = "virtserialport" in device_text
        except (OSError, subprocess.SubprocessError) as exc:
            result["errors"].append(f"无法执行 -device help：{exc}")

        with tempfile.TemporaryDirectory(prefix="ctflab-spice-probe-") as directory:
            socket_path = Path(directory) / "probe.sock"
            probe_command = [
                qemu, "-machine", "virt", "-nodefaults", "-display", "none", "-S",
                # QEMU 11.x 把 UNIX transport 拆成 `unix=on` + `addr=PATH`；
                # `unix=PATH` 会被解释为布尔值并在真正启动时失败。
                "-spice", f"unix=on,addr={socket_path},disable-ticketing=on",
                "-device", "virtio-serial-pci",
                "-chardev", "spicevmc,id=ctflab_probe,name=vdagent",
                "-device", "virtserialport,chardev=ctflab_probe,name=com.redhat.spice.0",
            ]
            try:
                spice = subprocess.run(probe_command, check=False, capture_output=True,
                                       text=True, timeout=1.5)
                spice_text = f"{spice.stdout}\n{spice.stderr}"
                result["spicevmc"] = (
                    "not a valid char driver" not in spice_text
                    and "invalid option" not in spice_text
                    and "unknown option" not in spice_text
                )
                if not result["spicevmc"]:
                    result["errors"].append("-chardev spicevmc 不可用")
            except subprocess.TimeoutExpired:
                # `-S` 使合法命令保持运行；超时本身就是“参数被接受”的证据。
                result["spicevmc"] = True
            except (OSError, subprocess.SubprocessError) as exc:
                result["errors"].append(f"无法验证 spicevmc：{exc}")
        result["supported"] = all(result[key] for key in
                                   ("spice_display", "spicevmc", "virtserialport", "client"))
        return result

    @staticmethod
    def spice_capability_error(capabilities: dict[str, Any]) -> CTFLabError:
        missing = [label for key, label in (
            ("spice_display", "QEMU spice 显示后端"),
            ("spicevmc", "spicevmc chardev"),
            ("virtserialport", "virtserialport 设备"),
            ("client", "本地 SPICE 客户端（remote-viewer 或 spicy）"),
        ) if not capabilities.get(key)]
        detail = "；".join(capabilities.get("errors", []))
        suffix = f"（{detail}）" if detail else ""
        return CTFLabError(
            "SPICE 动态分辨率未就绪：缺少 " + "、".join(missing) + suffix
            + "。请安装/内置经过验证的 SPICE QEMU 与客户端；不会自动回退 Cocoa。"
        )

    def _spice_socket(self, profile_id: str) -> Path:
        """返回 0700 runtime 目录内的本次 SPICE UNIX socket 路径。"""
        directory = self.runtime_dir / profile_id / "spice"
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        socket_path = directory / "display.sock"
        if socket_path.exists() or socket_path.is_symlink():
            if socket_path.is_dir():
                raise CTFLabError(f"SPICE socket 路径被目录占用：{socket_path}")
            socket_path.unlink()
        return socket_path

    def qemu_command(self, profile_id: str, profile: dict[str, Any], overlay: Path, lab_port: int,
                     headless: bool, allow_internet: bool = False, clipboard: bool = False,
                     display: str = "cocoa") -> tuple[list[str], dict[str, int]]:
        if display not in {"cocoa", "spice"}:
            raise CTFLabError(f"不支持的显示后端：{display}（可选 cocoa 或 spice）。")
        if display == "spice" and (profile_id != "kali-arm64" or headless):
            raise CTFLabError("SPICE 动态分辨率仅支持 Kali 图形模式。")
        if clipboard and (profile_id != "kali-arm64" or headless):
            raise CTFLabError("剪贴板仅支持 Kali 图形模式。")
        guest = profile.get("guest", {})
        disk = profile.get("disk", {})
        network = profile.get("network", {})
        architecture = guest.get("architecture", "x86_64")
        if architecture == "aarch64":
            qemu = which_any(QEMU_ARM_NAMES)
            if not qemu:
                raise CTFLabError("未找到 qemu-system-aarch64，请先安装 QEMU。")
            code_path, vars_path = self.ensure_uefi_vars(profile_id)
            command = [
                qemu,
                "-name", f"CTFLab-{profile_id}",
                "-machine", str(guest.get("machine", "virt")),
                "-accel", "hvf",
                "-cpu", "host",
                "-smp", str(guest.get("cpus", 2)),
                "-m", str(guest.get("memory_mb", 4096)),
                "-drive", f"if=pflash,format=raw,unit=0,file={code_path},readonly=on",
                "-drive", f"if=pflash,format=raw,unit=1,file={vars_path}",
                "-drive", f"file={overlay},if=none,format=qcow2,id=disk0",
                "-device", "virtio-blk-pci,drive=disk0",
                "-device", "virtio-gpu-pci",
                "-device", "qemu-xhci",
                "-device", "usb-kbd",
                "-device", "usb-tablet",
            ]
            primary_adapter = "virtio-net-pci"
        else:
            qemu = which_any(QEMU_X86_NAMES)
            if not qemu:
                raise CTFLabError("未找到 qemu-system-x86_64，请先安装 QEMU。")
            command = [
                qemu,
                "-name", f"CTFLab-{profile_id}",
                "-machine", str(guest.get("machine", "pc")),
                "-accel", "tcg,thread=multi",
                "-cpu", "max",
                "-smp", str(guest.get("cpus", 1)),
                "-m", str(guest.get("memory_mb", 1024)),
            ]
            if str(guest.get("firmware", "bios")) == "uefi":
                # 受控回退矩阵会尝试 x86_64 + UEFI：使用 OVMF 白名单固件与独立 NVRAM。
                code_path, vars_path = self.ensure_uefi_vars(profile_id, "x86_64")
                command += [
                    "-drive", f"if=pflash,format=raw,unit=0,file={code_path},readonly=on",
                    "-drive", f"if=pflash,format=raw,unit=1,file={vars_path}",
                ]
            bus = str(disk.get("bus", "ide"))
            if bus == "scsi":
                command += [
                    "-drive", f"file={overlay},if=none,format=qcow2,id=disk0",
                    "-device", f"{disk.get('controller', 'lsi53c895a')},id=scsi0",
                    "-device", "scsi-hd,drive=disk0,bus=scsi0.0",
                ]
            elif bus == "sata":
                command += [
                    "-drive", f"file={overlay},if=none,format=qcow2,id=disk0",
                    "-device", f"{disk.get('controller', 'ich9-ahci')},id=sata0",
                    "-device", "ide-hd,drive=disk0,bus=sata0.0",
                ]
            elif bus in {"virtio", "virtio-blk"}:
                command += [
                    "-drive", f"file={overlay},if=none,format=qcow2,id=disk0",
                    "-device", "virtio-blk-pci,drive=disk0",
                ]
            else:
                command += ["-drive", f"file={overlay},if={bus},format=qcow2"]
            command += ["-vga", "std"]
            primary_adapter = str(network.get("adapter", "e1000"))

        spice_socket: Path | None = None
        if display == "spice":
            capabilities = self.probe_spice(qemu)
            if not capabilities.get("supported"):
                raise self.spice_capability_error(capabilities)
            spice_socket = self._spice_socket(profile_id)

        command += ["-net", "none"]
        host_forwards: dict[str, int] = {}
        forwards = network.get("host_forwards", []) or []
        forward_parts: list[str] = []
        for item in forwards:
            guest_port = int(item["guest_port"])
            host_port = int(item["host_port"])
            label = str(item.get("name", guest_port))
            host_forwards[label] = host_port
            forward_parts.append(f"hostfwd=tcp:127.0.0.1:{host_port}-:{guest_port}")
        if allow_internet and profile_id != "kali-arm64":
            raise CTFLabError("只有 Kali 可以临时联网。")
        mgmt_netdev = "user,id=mgmt" + ("" if allow_internet else ",restrict=on")
        if forward_parts:
            mgmt_netdev += "," + ",".join(forward_parts)
        # 将实验网卡放在第一块，并使用原始 OVF 的模型/MAC：各 QEMU 实例通过
        # 回环 TCP 二层交换机互通，固定地址由本地 DHCP 服务分配。第二块网卡是
        # 受限 user-net 管理面，只承载宿主机端口映射。
        command += [
            "-netdev", f"socket,id=labnet,connect=127.0.0.1:{lab_port}",
            "-device", f"{primary_adapter},netdev=labnet,mac={network.get('mac')}",
            "-netdev", mgmt_netdev,
            "-device", f"e1000,netdev=mgmt,mac={self.management_mac(profile_id)}",
            "-no-reboot",
        ]
        if display == "spice":
            # UNIX socket + 0700 runtime 目录是本机鉴权边界；不开放 TCP，也不把 ticket
            # 写入命令行或状态文件。SPICE agent transport 始终存在，剪贴板只由显式开关控制。
            copy_paste = "off" if clipboard else "on"
            command += [
                "-display", "none",
                # 与最小能力探测保持同一套 QEMU 11.x 参数格式。
                "-spice", f"unix=on,addr={spice_socket},disable-ticketing=on,disable-copy-paste={copy_paste},disable-agent-file-xfer=on",
                "-device", "virtio-serial-pci",
                "-chardev", "spicevmc,id=ctflab_spice_agent,name=vdagent",
                "-device", "virtserialport,chardev=ctflab_spice_agent,name=com.redhat.spice.0",
            ]
        elif headless:
            command += ["-display", "none", "-serial", "mon:stdio"]
        else:
            command += ["-display", "cocoa,zoom-to-fit=on"]
        if clipboard and display != "spice":
            command += [
                "-device", "virtio-serial-pci",
                "-chardev", "qemu-vdagent,id=ctflab_clipboard,clipboard=on,mouse=off",
                "-device", "virtserialport,chardev=ctflab_clipboard,name=com.redhat.spice.0",
            ]
        qmp_path = self.runtime_dir / profile_id / "qmp.sock"
        if qmp_path.exists():
            qmp_path.unlink()
        command += ["-qmp", f"unix:{qmp_path},server=on,wait=off"]
        return command, host_forwards

    def run(self, profile_ids: list[str], headless: bool = False, pcap: bool = False,
            allow_internet: bool = False, clipboard: bool = False,
            display: str = "auto",
            profile_overrides: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        with self.operation_lock("启动 " + ",".join(profile_ids)):
            return self._run_unlocked(profile_ids, headless=headless, pcap=pcap,
                                      allow_internet=allow_internet, clipboard=clipboard,
                                      display=display, profile_overrides=profile_overrides)

    def _run_unlocked(self, profile_ids: list[str], headless: bool = False, pcap: bool = False,
                      allow_internet: bool = False, clipboard: bool = False,
                      display: str = "auto",
                      profile_overrides: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        profile_overrides = profile_overrides or {}
        profile_ids = list(dict.fromkeys(PROFILE_ALIASES.get(profile_id, profile_id) for profile_id in profile_ids))
        if display not in {"auto", "cocoa", "spice"}:
            raise CTFLabError(f"不支持的显示后端：{display}（可选 auto、cocoa 或 spice）。")
        if display == "spice" and profile_ids != ["kali-arm64"]:
            raise CTFLabError("--display spice 只能单独启动 kali-arm64。")
        if display == "spice" and headless:
            raise CTFLabError("--display spice 不能与 --headless 同时使用。")
        if clipboard and (headless or "kali-arm64" not in profile_ids):
            raise CTFLabError("--clipboard 需要启动 Kali 图形窗口。")
        if allow_internet and "kali-arm64" not in profile_ids:
            raise CTFLabError("只有 Kali 可以联网；Smoke 和 Basic Pentesting 2 始终保持隔离。")
        displays = {
            profile_id: resolve_display_backend(profile_id, display, headless=headless)
            for profile_id in profile_ids
        }
        for profile_id in profile_ids:
            load_profile(profile_id)
        if "spice" in displays.values():
            # 预检必须发生在创建实验网交换机和 overlay 之前；显式 SPICE 缺件不能留下
            # “虚拟机没启动但网络还在”的半完成状态。
            qemu = which_any(QEMU_ARM_NAMES)
            if not qemu:
                raise CTFLabError("未找到 qemu-system-aarch64，无法启动 SPICE 动态分辨率。")
            capabilities = self.probe_spice(qemu)
            if not capabilities.get("supported"):
                raise self.spice_capability_error(capabilities)
        running = self.running_states()
        for state in running:
            if state["profile_id"] == "kali-arm64" and "kali-arm64" in profile_ids and bool(state.get("clipboard_enabled")) != clipboard:
                raise CTFLabError("切换剪贴板模式需要先 stop，再 run。")
            expected_display = displays.get(state["profile_id"])
            if expected_display and state.get("display_backend", "cocoa") != expected_display:
                raise CTFLabError("切换显示后端需要先 stop，再 run。")
        for state in running:
            expected_internet = state["profile_id"] == "kali-arm64"
            if state["profile_id"] in profile_ids and bool(state.get("internet_enabled")) != expected_internet:
                raise CTFLabError("切换联网模式需要先 stop，再 run。")
        lab_port = int(running[0]["lab_port"]) if running else self.allocate_lab_port()
        pcap_path: Path | None = None
        if pcap:
            self.pcap_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            pcap_path = self.pcap_dir / f"lab-{lab_port}-{stamp}.pcap"
        network_state = self.ensure_network(
            [state["profile_id"] for state in running] + profile_ids,
            lab_port,
            pcap_path=pcap_path,
        )
        started: list[dict[str, Any]] = []
        for profile_id in profile_ids:
            old = self.runtime_state(profile_id)
            if old and bool_pid_alive(int(old.get("pid", 0))):
                started.append(old)
                continue
            profile = profile_overrides.get(profile_id) or load_profile(profile_id)
            overlay = self.ensure_overlay(profile_id)
            command, host_forwards = self.qemu_command(
                profile_id, profile, overlay, lab_port, headless,
                # Kali 的管理网默认使用 user-mode NAT；脆弱靶机的管理网仍为
                # restrict=on，实验网只经本地交换机互通。
                allow_internet=profile_id == "kali-arm64",
                clipboard=clipboard and profile_id == "kali-arm64",
                display=displays[profile_id],
            )
            log_path = self.logs_dir / f"{profile_id}.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("a", encoding="utf-8")
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    text=True,
                )
            except OSError as exc:
                log_handle.close()
                raise CTFLabError(f"无法启动 {profile_id}：{exc}") from exc
            finally:
                log_handle.close()
            time.sleep(0.2)
            if process.poll() is not None:
                detail = log_path.read_text(encoding="utf-8", errors="replace").strip()
                raise CTFLabError(f"QEMU 未能启动 {profile_id}（退出码 {process.returncode}）。{detail}")
            state = {
                "schema": 1,
                "profile_id": profile_id,
                "pid": process.pid,
                "command": command,
                "overlay_path": str(overlay),
                "qmp_path": str(self.runtime_dir / profile_id / "qmp.sock"),
                "log_path": str(log_path),
                "lab_port": lab_port,
                "host_forwards": host_forwards,
                "pcap_path": network_state.get("pcap_path"),
                "started_at": now_iso(),
                "boot_override": {k: v for k, v in {
                    "firmware": profile.get("guest", {}).get("firmware"),
                    "bus": profile.get("disk", {}).get("bus"),
                    "controller": profile.get("disk", {}).get("controller"),
                }.items() if v} if profile_id in profile_overrides else None,
                "headless": headless,
                "internet_enabled": profile_id == "kali-arm64",
                "clipboard_enabled": clipboard and profile_id == "kali-arm64",
                "display_backend": displays[profile_id],
                "spice_endpoint": str(self.runtime_dir / profile_id / "spice" / "display.sock") if displays[profile_id] == "spice" else None,
            }
            write_json(self.runtime_state_path(profile_id), state)
            if displays[profile_id] == "spice":
                # QEMU 先创建服务端 socket，再启动受控客户端；客户端只接收固定的
                # spice+unix URI，不接受用户拼接的 QEMU/网络参数。
                endpoint = Path(str(state["spice_endpoint"]))
                deadline = time.monotonic() + 5.0
                while not endpoint.exists() and bool_pid_alive(process.pid) and time.monotonic() < deadline:
                    time.sleep(0.05)
                client = spice_client_path()
                if not endpoint.exists() or not client:
                    self._stop_unlocked([profile_id])
                    reason = "SPICE socket 未建立" if not endpoint.exists() else "本地 SPICE 客户端不可用"
                    raise CTFLabError(f"{reason}；已清理本次 QEMU 启动，不会自动回退 Cocoa。")
                client_command = spice_client_command(client, endpoint, clipboard)
                client_log = self.logs_dir / f"{profile_id}-spice-client.log"
                with client_log.open("a", encoding="utf-8") as client_handle:
                    try:
                        client_process = subprocess.Popen(
                            client_command,
                            stdin=subprocess.DEVNULL,
                            stdout=client_handle,
                            stderr=subprocess.STDOUT,
                            start_new_session=True,
                            text=True,
                        )
                    except OSError as exc:
                        self._stop_unlocked([profile_id])
                        raise CTFLabError(f"无法启动 SPICE 客户端：{exc}") from exc
                state["spice_client_pid"] = client_process.pid
                state["spice_client_log_path"] = str(client_log)
                write_json(self.runtime_state_path(profile_id), state)
            started.append(state)
        return started

    def stop(self, profile_ids: list[str], stop_all: bool = False, graceful: bool = False) -> list[str]:
        description = "停止全部实例" if stop_all else "停止 " + ",".join(profile_ids)
        with self.operation_lock(description):
            return self._stop_unlocked(profile_ids, stop_all=stop_all, graceful=graceful)

    def _stop_unlocked(self, profile_ids: list[str], stop_all: bool = False, graceful: bool = False) -> list[str]:
        targets = available_profiles() if stop_all else [PROFILE_ALIASES.get(profile_id, profile_id) for profile_id in profile_ids]
        stopped: list[str] = []
        preserved: list[str] = []
        stopped_ports: set[int] = set()
        for profile_id in targets:
            state = self.runtime_state(profile_id)
            if not state:
                continue
            if state.get("lab_port"):
                stopped_ports.add(int(state["lab_port"]))
            pid = int(state.get("pid", 0))
            qmp_path = Path(state.get("qmp_path", ""))
            if bool_pid_alive(pid):
                try:
                    if qmp_path.exists():
                        qmp_command(qmp_path, "system_powerdown")
                except (OSError, CTFLabError):
                    pass
                deadline = time.monotonic() + (GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS if graceful else FORCED_SHUTDOWN_TIMEOUT_SECONDS)
                while bool_pid_alive(pid) and time.monotonic() < deadline:
                    time.sleep(0.25)
                if graceful and bool_pid_alive(pid):
                    # 只保留这个实例，继续处理其余 profile；全部处理完后再统一报错。
                    preserved.append(profile_id)
                    continue
                if bool_pid_alive(pid):
                    # 某些旧靶机没有响应 ACPI 关机，优先通过 QMP quit 结束 QEMU，
                    # 再退回 SIGTERM/SIGKILL，避免 stop 命令长时间悬挂。
                    try:
                        if qmp_path.exists():
                            qmp_command(qmp_path, "quit")
                    except (OSError, CTFLabError):
                        pass
                    time.sleep(0.5)
                if bool_pid_alive(pid):
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    time.sleep(1)
                if bool_pid_alive(pid):
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            client_pid = int(state.get("spice_client_pid", 0) or 0)
            if client_pid and bool_pid_alive(client_pid):
                try:
                    os.kill(client_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                client_deadline = time.monotonic() + 1.0
                while bool_pid_alive(client_pid) and time.monotonic() < client_deadline:
                    time.sleep(0.05)
                if bool_pid_alive(client_pid):
                    try:
                        os.kill(client_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            if qmp_path.exists():
                qmp_path.unlink()
            spice_endpoint = Path(str(state.get("spice_endpoint", "")))
            if spice_endpoint.is_file() or spice_endpoint.is_symlink():
                spice_endpoint.unlink()
            state_path = self.runtime_state_path(profile_id)
            if state_path.exists():
                state_path.unlink()
            stopped.append(profile_id)
        remaining = self.running_states()
        if not remaining:
            # 没有实例存活时一并清理所有实验网状态文件，包括实例状态已被删除、
            # 但交换机仍在运行的残留端口。
            for port in sorted(stopped_ports | set(self.network_ports())):
                if port > 0:
                    self.stop_network(port)
        if preserved:
            raise CTFLabError(
                "以下实例未完成正常关机，已保留进程、磁盘和网络："
                + "、".join(preserved)
                + "。若来宾图形会话弹出了关机确认框，请在 QEMU 窗口中确认，或先在来宾里正常关机；"
                "确认来宾已经关机后可用 stop（不带 --graceful）结束进程并清理状态。"
            )
        return stopped

    def network_ports(self) -> list[int]:
        """列出运行目录中登记过的实验网端口（含无实例的残留交换机）。"""
        ports: list[int] = []
        for path in sorted(self.runtime_dir.glob("network-*.json")):
            suffix = path.stem.split("-", 1)[1]
            if suffix.isdigit():
                ports.append(int(suffix))
        return ports

    def stale_runtime_states(self) -> list[tuple[str, int]]:
        """返回状态文件仍在、但 QEMU 进程已经退出的实例。"""
        stale: list[tuple[str, int]] = []
        for profile_id in available_profiles():
            state = self.runtime_state(profile_id)
            if state and not bool_pid_alive(int(state.get("pid", 0))):
                stale.append((profile_id, int(state.get("pid", 0))))
        return stale

    def reset(self, profile_id: str, force: bool = False) -> None:
        with self.operation_lock(f"重置 {profile_id}"):
            profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
            state = self.runtime_state(profile_id)
            if state and bool_pid_alive(int(state.get("pid", 0))):
                if not force:
                    raise CTFLabError(f"{profile_id} 正在运行，请先 stop，或使用 reset --force。")
                self.stop([profile_id])
            instance_dir = self.runtime_dir / profile_id
            if instance_dir.exists():
                shutil.rmtree(instance_dir)

    def health(self, profile_id: str) -> list[dict[str, Any]]:
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        state = self.runtime_state(profile_id)
        if not state or not bool_pid_alive(int(state.get("pid", 0))):
            return [{"name": "process", "ok": False, "detail": "未运行"}]
        results: list[dict[str, Any]] = [{"name": "process", "ok": True, "detail": f"PID {state['pid']}"}]
        profile = load_profile(profile_id)
        try:
            started_at = datetime.fromisoformat(str(state.get("started_at")))
            elapsed = max(0, (datetime.now(timezone.utc) - started_at).total_seconds())
        except (TypeError, ValueError):
            elapsed = 0
        readiness_timeout = int(profile.get("readiness", {}).get("timeout_seconds", 180))

        def pending_or_failed(detail: str) -> tuple[bool | None, str]:
            if elapsed < readiness_timeout:
                return None, f"启动中（{int(elapsed)}s/{readiness_timeout}s）：{detail}"
            return False, detail

        for item in profile.get("readiness", {}).get("checks", []) or []:
            check = {"type": item} if isinstance(item, str) else dict(item)
            if check.get("type") == "dhcp":
                lease = self.dhcp_lease(profile_id)
                if lease:
                    results.append({"name": "dhcp", "ok": True, "detail": lease})
                else:
                    ok, detail = pending_or_failed("尚未获得固定实验地址")
                    results.append({"name": "dhcp", "ok": ok, "detail": detail})
                continue
            if check.get("type") not in {"tcp", "http", "ssh"}:
                results.append({"name": str(check.get("type")), "ok": None, "detail": "由来宾网络内检查"})
                continue
            guest_port = int(check.get("port"))
            host_port = None
            for forward in profile.get("network", {}).get("host_forwards", []) or []:
                if int(forward.get("guest_port")) == guest_port:
                    host_port = int(forward.get("host_port"))
                    break
            if host_port is None:
                results.append({"name": f"{check.get('type')}:{guest_port}", "ok": None, "detail": "没有主机端口映射"})
                continue
            if check.get("type") == "tcp":
                try:
                    with socket.create_connection(("127.0.0.1", host_port), timeout=1.0):
                        # QEMU user-net 的 hostfwd 会先在宿主监听端口，即使来宾服务
                        # 尚未就绪也可能完成 TCP 建连；因此这里只报告“转发层已建立”，
                        # 不把它误判成来宾服务已经响应。
                        results.append({"name": f"tcp:{guest_port}", "ok": None, "detail": f"端口转发已建立：127.0.0.1:{host_port}，需协议级检查"})
                except OSError as exc:
                    ok, detail = pending_or_failed(str(exc))
                    results.append({"name": f"tcp:{guest_port}", "ok": ok, "detail": detail})
            elif check.get("type") == "http":
                url = f"http://127.0.0.1:{host_port}{check.get('path', '/') }"
                try:
                    with urllib.request.urlopen(url, timeout=2.0) as response:
                        expected = int(check.get("expected_status", 200))
                        results.append({"name": f"http:{guest_port}", "ok": response.status == expected, "detail": f"HTTP {response.status}"})
                except (OSError, urllib.error.URLError) as exc:
                    ok, detail = pending_or_failed(str(exc))
                    results.append({"name": f"http:{guest_port}", "ok": ok, "detail": detail})
            else:
                try:
                    with socket.create_connection(("127.0.0.1", host_port), timeout=2.0) as connection:
                        connection.settimeout(2.0)
                        banner = connection.recv(128).decode("ascii", errors="replace").strip()
                    if banner.startswith("SSH-"):
                        results.append({"name": f"ssh:{guest_port}", "ok": True, "detail": banner})
                    else:
                        ok, detail = pending_or_failed(f"未收到 SSH 协议横幅：{banner or '空响应'}")
                        results.append({"name": f"ssh:{guest_port}", "ok": ok, "detail": detail})
                except OSError as exc:
                    ok, detail = pending_or_failed(str(exc))
                    results.append({"name": f"ssh:{guest_port}", "ok": ok, "detail": detail})
        return results

    def probe(self, profile_id: str, *, timeout_seconds: int | None = None, keep_running: bool = False,
              profile_overrides: dict[str, dict[str, Any]] | None = None,
              abort_on_failure_screen: bool = False) -> dict[str, Any]:
        """启动候选配置并收集 QMP、显示、DHCP 与协议证据。

        显示活动只说明画面不是全黑，不能自动区分登录界面、内核报错和 UEFI Shell。
        因此候选配置始终保留人工复核标记。``profile_overrides`` 用于受控回退矩阵：
        不写盘、只影响本次启动的固件/磁盘参数；``abort_on_failure_screen`` 在识别到
        UEFI Shell、无启动盘或内核错误时提前结束本次探测，交给矩阵尝试下一个候选。
        """
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        overrides = profile_overrides or {}
        profile = overrides.get(profile_id) or load_profile(profile_id)
        existing = self.runtime_state(profile_id)
        already_running = bool(existing and bool_pid_alive(int(existing.get("pid", 0))))
        started_by_probe = not already_running
        if started_by_probe:
            self.run([profile_id], headless=True, profile_overrides=overrides)
        state = self.runtime_state(profile_id)
        if not state:
            raise CTFLabError(f"无法获得 {profile_id} 的运行状态。")

        timeout = int(timeout_seconds or profile.get("readiness", {}).get("timeout_seconds", 180))
        timeout = max(5, min(timeout, 1800))
        probe_root = self.logs_dir / "probes"
        probe_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        ppm_path = probe_root / f"{profile_id}-{stamp}.ppm"
        png_path = probe_root / f"{profile_id}-{stamp}.png"
        report_path = probe_root / f"{profile_id}-{stamp}.json"
        qmp_path = Path(str(state.get("qmp_path", "")))
        checks = profile.get("readiness", {}).get("checks", []) or []
        expected_protocols = {
            str((item if isinstance(item, dict) else {"type": item}).get("type"))
            for item in checks
        } & {"http", "ssh"}
        deadline = time.monotonic() + timeout
        display: dict[str, Any] = {"active": False, "detail": "尚未取得截图"}
        health: list[dict[str, Any]] = []
        qmp_status: Any = None
        errors: list[str] = []
        screen: dict[str, Any] = {
            "available": False,
            "engine": None,
            "classification": "unknown",
            "confidence": "low",
            "matched_signals": [],
            "all_signals": {},
            "warnings": ["没有可供 OCR 的截图"],
            "text": "",
        }
        early_failure: str | None = None
        try:
            while time.monotonic() < deadline:
                current = self.runtime_state(profile_id)
                if not current or not bool_pid_alive(int(current.get("pid", 0))):
                    errors.append("QEMU 在探测完成前退出。")
                    break
                if qmp_path.exists():
                    try:
                        qmp_status = qmp_execute(qmp_path, "query-status")
                        qmp_execute(qmp_path, "screendump", {"filename": str(ppm_path)})
                        display = ppm_display_activity(ppm_path)
                    except (OSError, CTFLabError, json.JSONDecodeError) as exc:
                        errors.append(str(exc))
                health = self.health(profile_id)
                network_ready = any(item["name"] == "dhcp" and item["ok"] is True for item in health)
                protocol_ready = any(
                    item["ok"] is True and item["name"].split(":", 1)[0] in expected_protocols
                    for item in health
                )
                if (expected_protocols and protocol_ready) or (not expected_protocols and network_ready and display.get("active")):
                    break
                if abort_on_failure_screen and display.get("active") and ppm_path.exists():
                    # 矩阵探测：识别到 UEFI Shell/无启动盘/内核错误就提前结束，尝试下一个候选。
                    screen = classify_screenshot(ppm_path)
                    if screen.get("classification") in SCREEN_FAILURE_CLASSES:
                        early_failure = str(screen.get("classification"))
                        break
                time.sleep(2)

            process_running = bool_pid_alive(int((self.runtime_state(profile_id) or {}).get("pid", 0)))
            network_ready = any(item["name"] == "dhcp" and item["ok"] is True for item in health)
            protocol_ready = any(
                item["ok"] is True and item["name"].split(":", 1)[0] in expected_protocols
                for item in health
            )
            if protocol_ready:
                verdict = "service_ready"
            elif network_ready and display.get("active"):
                verdict = "network_and_display_candidate"
            elif display.get("active"):
                verdict = "display_activity_only"
            elif process_running:
                verdict = "process_running_no_readiness"
            else:
                verdict = "qemu_exited"

            screenshot_path: str | None = str(ppm_path) if ppm_path.exists() else None
            sips = shutil.which("sips")
            if sips and ppm_path.exists():
                conversion = subprocess.run(
                    [sips, "-s", "format", "png", str(ppm_path), "--out", str(png_path)],
                    check=False,
                    text=True,
                    capture_output=True,
                )
                if conversion.returncode == 0 and png_path.exists():
                    screenshot_path = str(png_path)
                    ppm_path.unlink()

            if screenshot_path:
                screen = classify_screenshot(Path(screenshot_path))
            else:
                screen = {
                    "available": False,
                    "engine": None,
                    "classification": "unknown",
                    "confidence": "low",
                    "matched_signals": [],
                    "all_signals": {},
                    "warnings": ["没有可供 OCR 的截图"],
                    "text": "",
                }
            screen_failure = screen.get("classification") in SCREEN_FAILURE_CLASSES
            if screen_failure and not protocol_ready:
                verdict = str(screen["classification"])

            candidate_profile = profile.get("detection", {}).get("status") == "candidate"
            report = {
                "schema": 1,
                "profile_id": profile_id,
                "started_at": state.get("started_at"),
                "probed_at": now_iso(),
                "timeout_seconds": timeout,
                "started_by_probe": started_by_probe,
                "kept_running": keep_running or already_running,
                "qmp_status": qmp_status,
                "process_running_at_verdict": process_running,
                "display": display,
                "early_failure": early_failure,
                "screenshot_path": screenshot_path,
                "screen": screen,
                "health": health,
                "verdict": verdict,
                "requires_human_review": candidate_profile or verdict != "service_ready" or screen_failure,
                "errors": list(dict.fromkeys(errors))[-20:],
                "verification": {
                    "boot_process": process_running,
                    "display_activity": bool(display.get("active")),
                    "screen_classification": screen.get("classification"),
                    "network": network_ready,
                    "service": protocol_ready,
                },
                "note": "OCR 分类用于快速排障，仍可能受字体、分辨率和语言影响；候选配置需人工查看截图后才能标记已验证。",
            }
            write_json(report_path, report)
            report["report_path"] = str(report_path)
            return report
        finally:
            if started_by_probe and not keep_running:
                self.stop([profile_id])


    def boot_matrix(self, profile_id: str, *, per_candidate_timeout: int = 90,
                    max_candidates: int | None = None, start_at: int = 1) -> dict[str, Any]:
        """受控启动回退矩阵：按白名单顺序尝试固件/磁盘组合，用画面分类决定是否继续。

        候选只作用于本次启动（不写入 profile）；识别到 UEFI Shell、无启动盘或内核错误
        就立即换下一个候选，命中协议级就绪或登录界面即停止。
        """
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        base = load_profile(profile_id)
        architecture = str(base.get("guest", {}).get("architecture", "x86_64"))
        candidates = list(matrix_candidates(architecture))
        if max_candidates is not None:
            candidates = candidates[: max(1, max_candidates)]
        start_at = max(1, int(start_at))
        candidates = candidates[max(0, start_at - 1):]
        timeout = max(5, min(int(per_candidate_timeout), 1800))
        attempts: list[dict[str, Any]] = []
        selected: dict[str, Any] | None = None
        for index, candidate in enumerate(candidates, 1):
            override = copy.deepcopy(base)
            override.setdefault("guest", {})["firmware"] = candidate["firmware"]
            override.setdefault("disk", {})["bus"] = candidate["bus"]
            if candidate.get("controller"):
                override["disk"]["controller"] = candidate["controller"]
            else:
                override["disk"].pop("controller", None)
            print(f"[{index}/{len(candidates)}] 尝试 {candidate_label(candidate)}（超时 {timeout}s）")
            try:
                report = self.probe(
                    profile_id,
                    timeout_seconds=timeout,
                    profile_overrides={profile_id: override},
                    abort_on_failure_screen=True,
                )
            except CTFLabError as exc:
                attempts.append({"candidate": candidate, "label": candidate_label(candidate),
                                 "error": str(exc)})
                print(f"    无法启动：{exc}")
                continue
            screen = report.get("screen", {})
            verdict = str(report.get("verdict"))
            classification = str(screen.get("classification", "unknown"))
            success = verdict in BOOT_MATRIX_SUCCESS_VERDICTS or classification in BOOT_MATRIX_SUCCESS_SCREENS
            attempt = {
                "candidate": candidate,
                "label": candidate_label(candidate),
                "verdict": verdict,
                "screen": classification,
                "confidence": screen.get("confidence"),
                "early_failure": report.get("early_failure"),
                "screenshot_path": report.get("screenshot_path"),
                "report_path": report.get("report_path"),
            }
            attempts.append(attempt)
            print(f"    结论：{verdict}（画面 {classification}/{screen.get('confidence', 'low')}）")
            if success:
                selected = attempt
                break
        result = {
            "schema": 1,
            "profile_id": profile_id,
            "architecture": architecture,
            "timeout_per_candidate": timeout,
            "attempts": attempts,
            "selected": selected,
            "succeeded": selected is not None,
            "note": "候选只作用于本次启动，不会写入 profile；命中结果需要人工复核截图后才能标记为已验证交付。",
        }
        report_root = self.logs_dir / "probes"
        report_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        matrix_path = report_root / f"{profile_id}-matrix-{stamp}.json"
        write_json(matrix_path, result)
        result["report_path"] = str(matrix_path)
        return result


def cmd_doctor(manager: LabManager, _args: argparse.Namespace) -> int:
    """检查运行依赖；每项缺失都给出可操作的安装提示，必选项缺失时返回 1。"""
    checks = [
        (
            "宿主系统",
            f"{platform.system()} {platform.machine()}" if platform.system() == "Darwin" and platform.machine() in {"arm64", "aarch64"} else None,
            True,
            "需要 macOS Apple Silicon（Darwin arm64）",
        ),
        (
            "python",
            f"{sys.executable}（{platform.python_version()}）" if python_version_ok() else None,
            True,
            f"需要 Python {MIN_PYTHON}+；当前 {sys.executable} 是 {platform.python_version()}，"
            "推荐使用自带解释器与 PyYAML 的 CTFLab.app",
        ),
        ("qemu-img", resolve_tool("qemu-img"), True,
         "请安装 QEMU：brew install qemu，或使用自带运行时的 CTFLab.app"),
        ("qemu-system-x86_64", which_any(QEMU_X86_NAMES), True,
         "请安装 QEMU：brew install qemu，或使用自带运行时的 CTFLab.app"),
        ("qemu-system-aarch64", which_any(QEMU_ARM_NAMES), True,
         "请安装 QEMU：brew install qemu，或使用自带运行时的 CTFLab.app"),
        (
            "utmctl",
            shutil.which("utmctl"),
            False,
            "可选：仅 UTM 镜像适配流程使用，运行器本身不依赖 UTM",
        ),
        (
            "PyYAML",
            "available" if yaml is not None else None,
            True,
            "缺少 PyYAML 时无法读写配置：python3 -m pip install pyyaml，或改用自带 PyYAML 的 Python",
        ),
        ("ARM64 UEFI", str(find_firmware("edk2-aarch64-code.fd")) if find_firmware("edk2-aarch64-code.fd") else None, True, "运行时应自带 edk2-aarch64-code.fd（QEMU 或 CTFLab.app）"),
        ("ARM64 UEFI NVRAM", str(find_firmware("edk2-arm-vars.fd")) if find_firmware("edk2-arm-vars.fd") else None, True, "运行时应自带 edk2-arm-vars.fd（QEMU 或 CTFLab.app）"),
        ("bsdtar", shutil.which("bsdtar") or shutil.which("tar"), True, "macOS 自带 bsdtar；缺失时请安装 libarchive"),
        ("cpio", shutil.which("cpio"), True, "macOS 自带 cpio；缺失时请安装"),
        (
            "Tesseract OCR",
            shutil.which("tesseract"),
            False,
            "可选：brew install tesseract；未安装时截图分类降级为人工复核",
        ),
    ]
    failed = False
    for name, value, required, hint in checks:
        ok = bool(value)
        marker = "OK  " if ok else "MISS" if required else "OPT "
        print(f"{marker} {name}: {value if ok else hint}")
        failed |= required and not ok
    root = runtime_root()
    if root is not None:
        print(f"运行时：bundled（{root}）")
        for name in ("qemu-img", "qemu-system-x86_64", "qemu-system-aarch64"):
            path = resolve_tool(name)
            if path:
                print(f"  {name}: {path}（bundled runtime）")
    else:
        print("运行时：PATH（未使用 app 内运行时；开发环境回退，等价于 brew 安装的 QEMU）")
    print(f"状态目录：{manager.state_dir}")
    return 1 if failed else 0


def cmd_list(manager: LabManager, _args: argparse.Namespace) -> int:
    for profile_id in available_profiles():
        profile = load_profile(profile_id)
        image = manager.image_state(profile_id)
        runtime = manager.runtime_state(profile_id)
        running = bool(runtime and bool_pid_alive(int(runtime.get("pid", 0))))
        imported = f"已导入 {image.get('source_format', '?')}" if image else "未导入"
        print(f"{profile_id:20} {profile.get('name', profile_id):24} {imported:12} {'运行中' if running else '已停止'}")
    return 0


def cmd_inspect(_manager: LabManager, args: argparse.Namespace) -> int:
    try:
        report = inspect_image(args.source, calculate_hash=not args.no_hash)
    except InspectionError as exc:
        raise CTFLabError(str(exc)) from exc
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report_text(report))
    return 0


def cmd_onboard(manager: LabManager, args: argparse.Namespace) -> int:
    profile_id = args.id.lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,47}[a-z0-9])?", profile_id):
        raise CTFLabError("配置 id 只能包含小写字母、数字和连字符，长度 1～49，且不能以连字符开头或结尾。")
    if profile_id in PROFILE_ALIASES or (PROFILE_DIR / f"{profile_id}.yaml").exists():
        raise CTFLabError(f"配置 {profile_id} 已存在；为避免覆盖已验证参数，请换一个 id。")
    try:
        report = inspect_image(args.source, calculate_hash=True)
    except InspectionError as exc:
        raise CTFLabError(str(exc)) from exc
    architecture = args.architecture if args.architecture != "auto" else report["candidate"]["architecture"]
    firmware = args.firmware if args.firmware != "auto" else report["candidate"]["firmware"]
    if architecture == "aarch64" and firmware == "bios":
        raise CTFLabError("ARM64 virt 候选不支持 Legacy BIOS，请使用 --firmware uefi。")
    lab_ip = args.lab_ip or manager.allocate_lab_ip()
    try:
        parsed_ip = ipaddress.IPv4Address(lab_ip)
    except ipaddress.AddressValueError as exc:
        raise CTFLabError(f"实验网 IP 无效：{lab_ip}") from exc
    if parsed_ip not in ipaddress.IPv4Network("192.168.242.0/24") or int(str(parsed_ip).rsplit(".", 1)[1]) in {0, 1, 255}:
        raise CTFLabError("实验网 IP 必须位于 192.168.242.2～192.168.242.254，且不能使用 .255。")
    used_ips = {
        str(load_profile(item).get("network", {}).get("lab_ip"))
        for item in available_profiles()
        if load_profile(item).get("network", {}).get("lab_ip")
    }
    if str(parsed_ip) in used_ips:
        raise CTFLabError(f"实验网 IP 已被其它配置使用：{parsed_ip}")
    source_name = Path(args.source).expanduser().name
    default_name = re.sub(r"[-_]+", " ", Path(source_name).stem).strip().title() or profile_id
    overrides = {
        "architecture": architecture,
        "firmware": firmware,
        "disk_bus": args.disk_bus,
        "disk_controller": args.disk_controller,
        "network_adapter": args.network_adapter,
        "memory_mb": args.memory_mb,
        "cpus": args.cpus,
    }
    profile = profile_from_report(
        report,
        profile_id=profile_id,
        name=args.name or default_name,
        lab_ip=str(parsed_ip),
        mac=manager.lab_mac(profile_id),
        overrides=overrides,
    )
    validate_profile(profile, PROFILE_DIR / f"{profile_id}.yaml")
    if yaml is None:
        raise CTFLabError("当前 Python 缺少 PyYAML，无法生成配置。")
    destination = PROFILE_DIR / f"{profile_id}.yaml"
    temporary = destination.with_suffix(".yaml.tmp")
    temporary.write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding="utf-8")
    temporary.replace(destination)
    detection_path = manager.images_dir / profile_id / "detection.json"
    write_json(detection_path, report)
    print(f"候选配置已生成：{destination}")
    print(f"探测报告：{detection_path}")
    for warning in report.get("warnings", []):
        print(f"警告：{warning}")
    if args.no_import:
        print("已按 --no-import 跳过磁盘导入；候选配置尚未启动验证。")
        return 0
    state = manager.import_image(profile_id, args.source)
    print(f"导入完成：{profile_id}")
    print(f"基础镜像：{state['base_path']}")
    print(f"下一步：./tools/ctflab probe {profile_id}")
    return 0


def cmd_import(manager: LabManager, args: argparse.Namespace) -> int:
    state = manager.import_image(args.profile, args.source,
                                 expect_sha256=args.expect_sha256,
                                 manifest=args.manifest,
                                 nvram=args.nvram)
    print(f"导入完成：{args.profile}")
    print(f"基础镜像：{state['base_path']}")
    print(f"SHA-256：{state['source_sha256']}")
    verification = state.get("source_verification")
    if verification:
        print(f"来源校验：通过（{verification['method']}；期望 {verification['expected_sha256'][:12]}…）")
    else:
        print("来源校验：未提供期望哈希（可用 --manifest 或 --expect-sha256 校验下载文件）")
    if state.get("uefi_vars_path"):
        print(f"UEFI NVRAM 模板：{state['uefi_vars_path']}")
    return 0


def cmd_dist_prepare(manager: LabManager, args: argparse.Namespace) -> int:
    """为一个 profile 生成分发文件（压缩基盘 + 可选 NVRAM 模板）并合并分发清单。"""
    import ctflab_dist  # noqa: PLC0415

    profile_id = PROFILE_ALIASES.get(args.profile, args.profile)
    profile = load_profile(profile_id)
    state = manager.image_state(profile_id) or {}
    source = Path(args.source).expanduser() if args.source else Path(str(state.get("base_path") or ""))
    if not source.is_file():
        raise CTFLabError(
            f"{profile_id} 没有已导入的基盘（或 --source 指向的文件不存在）：{source or '（未登记）'}；"
            "先执行 ctflab import，或用 --source 显式指定")
    try:
        base_entry = ctflab_dist.prepare_image_entry(
            args.out, profile_id=profile_id, source=source, qemu_img=qemu_img_path(),
            compress=not args.no_compress, base_sha256=state.get("base_sha256"))
        nvram_entry = None
        architecture = str(profile.get("guest", {}).get("architecture") or "")
        if architecture == "aarch64" and not args.no_nvram:
            nvram_source = Path(args.nvram).expanduser() if args.nvram \
                else Path(str(state.get("uefi_vars_path") or ""))
            if not nvram_source.is_file():
                raise CTFLabError(
                    f"{profile_id} 是 aarch64：需要随包分发 UEFI NVRAM 模板"
                    "（用 --nvram 指定，或先用 ctflab import --nvram 登记；"
                    "确认不需要时用 --no-nvram 明确跳过）")
            nvram_entry = ctflab_dist.prepare_nvram_entry(
                args.out, profile_id=profile_id, source=nvram_source)
    except ctflab_dist.DistError as exc:
        raise CTFLabError(str(exc)) from exc
    print(f"分发文件已写入：{Path(args.out).expanduser()}")
    print(f"  {base_entry['file']}（{base_entry['compression']} 压缩，"
          f"{ctflab_dist.human_size(int(base_entry['size']))}，sha256 {base_entry['sha256'][:12]}…）")
    if nvram_entry:
        print(f"  {nvram_entry['file']}（{ctflab_dist.human_size(int(nvram_entry['size']))}，"
              f"sha256 {nvram_entry['sha256'][:12]}…）")
    if base_entry.get("source_base_sha256"):
        print(f"  source_base_sha256：{base_entry['source_base_sha256'][:12]}…"
              "（该 profile 验证记录中的基盘哈希，供交叉核对）")
    print(f"清单：{ctflab_dist.MANIFEST_NAME} / {ctflab_dist.SUMS_NAME} / {ctflab_dist.README_NAME}")
    return 0


def cmd_dist_verify(_manager: LabManager, args: argparse.Namespace) -> int:
    """复核分发目录：逐文件大小与 SHA-256 与清单一致。"""
    import ctflab_dist  # noqa: PLC0415

    try:
        report = ctflab_dist.verify_distribution(args.dir)
    except ctflab_dist.DistError as exc:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "entries": [], "problems": [str(exc)],
                              "summary": {"total": 0, "ok": 0, "failed": 1},
                              "dir": str(Path(args.dir).expanduser())},
                             ensure_ascii=False, indent=2))
            return 1
        raise CTFLabError(str(exc)) from exc
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    if report["ok"]:
        print(f"分发目录校验通过：{Path(args.dir).expanduser()}"
              f"（{len(report['entries'])} 个文件与清单一致）")
        return 0
    for problem in report["problems"]:
        print(f"不一致：{problem}", file=sys.stderr)
    raise CTFLabError(f"分发目录校验失败：{len(report['problems'])} 项不一致")


def cmd_utm_export(manager: LabManager, args: argparse.Namespace) -> int:
    """路径 A：把一个已导入的基础镜像导出为新的 UTM 包（aarch64+UEFI 或 x86_64+BIOS 变体）。"""
    profile_id = PROFILE_ALIASES.get(args.profile, args.profile)
    with manager.operation_lock(f"导出 {profile_id} 的 UTM 包"):
        try:
            result = export_utm_package(
                profile_id=profile_id,
                profile=load_profile(profile_id),
                image_state=manager.image_state(profile_id),
                out_dir=args.out,
                name=args.name,
            )
        except UTMExportError as exc:
            raise CTFLabError(str(exc)) from exc
    out_dir = Path(args.out).expanduser()
    print(f"UTM 包已导出：{out_dir / result['bundle']['name']}")
    print(f"导出清单：{out_dir / result['manifest']['name']}")
    print("提示：UTM 4.7.5 必需段/键已按上游源码补齐；真实 UTM E2E 结论见设计文档 2.4 与 "
          "docs/verification-utm-*.md：重启后复测失败，显示链路不稳定；当前包仅保证固定显示可用。")
    return 0


def cmd_package_build(_manager: LabManager, args: argparse.Namespace) -> int:
    """Task 6.1：构建源码级可分发安装包（MANIFEST + SBOM + 许可证清单 + install.sh）。"""
    import ctflab_package  # noqa: PLC0415  延迟导入，保持主 CLI 启动路径不变

    try:
        result = ctflab_package.build_release_bundle(args.out, version=args.version)
    except ctflab_package.PackageError as exc:
        raise CTFLabError(str(exc)) from exc
    manifest = result["manifest"]
    print(f"安装包已生成：{result['bundle']}")
    print(f"外层 SHA-256：{result['sha256']}")
    print(f"清单：{len(manifest['files'])} 个文件；版本 {manifest['version']}")
    print("包内包含：MANIFEST.json、SBOM.json、THIRD_PARTY_LICENSES.md、install.sh、SHA256SUMS")
    print(f"许可证状态：{manifest['license']['status']}（对外分发前必须补充项目 LICENSE）")
    print("提示：本包为源码级安装包，不含 CTFLab.app、QEMU 运行时与签名；"
          "干净环境验收脚本：tools/ctflab_acceptance.py")
    return 0


def cmd_package_verify(_manager: LabManager, args: argparse.Namespace) -> int:
    import ctflab_package  # noqa: PLC0415

    try:
        report = ctflab_package.verify_release_bundle(args.bundle)
    except ctflab_package.PackageError as exc:
        raise CTFLabError(str(exc)) from exc
    print(f"安装包校验通过：{report['bundle']}")
    print(f"外层 SHA-256：{report['sha256']}")
    print(f"版本 {report['manifest']['version']}，共 {report['file_count']} 个登记文件")
    print(f"启动器无开发解释器硬编码；SBOM 组件数：{len(report['sbom']['components'])}")
    return 0


def cmd_content_pack(_manager: LabManager, args: argparse.Namespace) -> int:
    import ctflab_package  # noqa: PLC0415

    profile_id = PROFILE_ALIASES.get(args.profile, args.profile)
    try:
        result = ctflab_package.build_content_package(profile_id, args.out, version=args.version)
    except ctflab_package.PackageError as exc:
        raise CTFLabError(str(exc)) from exc
    print(f"内容包已生成：{result['package']}")
    print(f"SHA-256：{result['sha256']}")
    print(f"不含虚拟磁盘；导入镜像：ctflab import {profile_id} <镜像路径>")
    return 0


def cmd_content_verify(_manager: LabManager, args: argparse.Namespace) -> int:
    import ctflab_package  # noqa: PLC0415

    try:
        report = ctflab_package.verify_content_package(
            args.package, check_version=not args.no_version_check)
    except ctflab_package.PackageError as exc:
        raise CTFLabError(str(exc)) from exc
    content = report["content"]
    print(f"内容包校验通过：{report['package']}")
    print(f"id={content['id']} name={content['name']} version={content['version']} "
          f"requires_ctflab={content['requires_ctflab']}")
    print(f"登记文件 {report['file_count']} 个；disk_included=False")
    return 0


def cmd_content_unpack(_manager: LabManager, args: argparse.Namespace) -> int:
    import ctflab_package  # noqa: PLC0415

    try:
        written = ctflab_package.unpack_content_package(args.package, args.out)
    except ctflab_package.PackageError as exc:
        raise CTFLabError(str(exc)) from exc
    print(f"已解包 {len(written)} 个文件到：{Path(args.out).expanduser()}")
    for path in written:
        print(f"  {path.name}")
    return 0


def cmd_app_build(_manager: LabManager, args: argparse.Namespace) -> int:
    """Task 6.2/6.3B：构建包含受控 QEMU + Python 运行时的 CTFLab.app。"""
    import ctflab_app  # noqa: PLC0415

    try:
        result = ctflab_app.build_app(
            args.out,
            version=args.version,
            qemu_root=args.qemu_root,
            spice_client=args.spice_client,
            python_runtime=args.python_runtime,
            python_runtime_sha256=args.python_runtime_sha256,
            pyyaml_source=args.pyyaml,
            pyyaml_sha256=args.pyyaml_sha256,
            sign_identity=args.sign_identity,
            allow_incomplete_license_texts=args.allow_incomplete_license_texts,
            unsigned=args.unsigned,
        )
    except ctflab_app.AppBuildError as exc:
        raise CTFLabError(str(exc)) from exc
    signature = result["signature"]
    runtime = result["manifest"]["runtime"]
    print(f"CTFLab.app 已生成：{result['app']}")
    print(f"版本 {result['manifest']['version']}，{len(result['manifest']['files'])} 个登记文件；"
          f"QEMU：{runtime['qemu_version']}")
    print(f"动态库 {len(runtime['dylibs'])} 个，"
          f"运行时资源 {len(runtime['share_files'])} 个")
    print(f"内置 Python {runtime['python']['version']}（{runtime['python']['source']}），"
          f"PyYAML {runtime['python']['pyyaml']['version']}；"
          f"裁掉 {len(runtime['python']['pruned'])} 项、解引用符号链接 "
          f"{runtime['python']['symlinks_dereferenced']} 个")
    print(f"签名级别：{signature['level']}；公证：{signature['notarization_status']}")
    if result["missing_license_texts"]:
        print("警告：以下组件在 Homebrew keg 与仓库 tools/licenses/ 中都没有许可证文本："
              + ", ".join(result["missing_license_texts"]))
    for blocker in result["manifest"]["license"]["distribution_blockers"]:
        print(f"分发阻塞：{blocker}")
    return 0


def cmd_app_verify(_manager: LabManager, args: argparse.Namespace) -> int:
    import ctflab_app  # noqa: PLC0415

    try:
        report = ctflab_app.verify_app(args.app)
    except ctflab_app.AppBuildError as exc:
        raise CTFLabError(str(exc)) from exc
    runtime = report["runtime"]
    print(f"app 校验通过：{report['app']}")
    print(f"版本 {report['version']}，{report['file_count']} 个登记文件；"
          f"QEMU：{runtime['qemu_version']}")
    python_section = runtime.get("python", {})
    if python_section:
        print(f"内置 Python：{python_section.get('version')}"
              f"（{python_section.get('bin')}），"
              f"PyYAML：{python_section.get('pyyaml', {}).get('version')}")
    print(f"签名级别：{report['signature']['level']}；公证：{report['signature']['notarization_status']}")
    print(f"许可证文本完整性：{report['license_texts_complete']}")
    for blocker in report["distribution_blockers"]:
        print(f"分发阻塞：{blocker}")
    return 0


def cmd_install(manager: LabManager, args: argparse.Namespace) -> int:
    state = manager.start_install(
        args.profile,
        args.iso,
        disk_size_gb=args.disk_size_gb,
        unattended=args.unattended,
        headless=args.headless,
        resume=args.resume,
        confirm_reinstall=args.confirm_reinstall,
    )
    print(f"Kali ARM64 安装器已启动（PID {state['pid']}）。")
    print(f"目标磁盘：{state['target_path']}")
    print(f"ISO SHA-256：{state['iso_sha256']}")
    if state.get("unattended"):
        print("无人值守安装：XFCE + kali-linux-default；用户名 kali，使用本次提供的本地口令。")
        print("安装完成时 QEMU 会因 -no-reboot 自动退出。")
    else:
        print("请在 QEMU 窗口选择 Graphical install 并完成安装。")
    print(f"查看进度：./tools/ctflab install-status {state['profile_id']} --log-tail")
    print(f"完成登记：./tools/ctflab finalize-install {state['profile_id']} --confirm")
    return 0


def cmd_install_status(manager: LabManager, args: argparse.Namespace) -> int:
    state = manager.install_status(args.profile)
    print(f"{state['profile_id']} 安装器：{'运行中' if state['running'] else '已停止'}")
    print(f"目标磁盘：{state['target_path']}")
    actual = int(state.get("target_actual_size") or 0)
    virtual = int(state.get("target_virtual_size") or 0)
    print(f"磁盘写入：{actual / 1024 ** 3:.2f} GiB / 虚拟容量 {virtual / 1024 ** 3:.0f} GiB")
    disk_io = state.get("disk_io", {}).get("disk0", {})
    if disk_io:
        print(f"本轮累计写入：{disk_io.get('wr_bytes', 0) / 1024 ** 3:.2f} GiB；写入错误：{disk_io.get('failed_wr_operations', 0)}")
    print(f"完成提示：{'已在日志中检测到' if state.get('completion_hint') else '尚未检测到'}")
    if args.log_tail and state.get("log_tail"):
        print("日志末尾：")
        print(state["log_tail"])
    return 0


def cmd_stop_install(manager: LabManager, args: argparse.Namespace) -> int:
    stopped = manager.stop_install(args.profile)
    print("安装器已停止。" if stopped else "没有安装任务。")
    return 0


def cmd_finalize_install(manager: LabManager, args: argparse.Namespace) -> int:
    state = manager.finalize_install(args.profile, confirmed=args.confirm, from_runtime=args.from_runtime)
    print(f"安装磁盘已登记为候选基础镜像：{state['base_path']}")
    print(f"基础镜像 SHA-256：{state['base_sha256']}")
    if state.get("archived_runtime_path"):
        print(f"固化前的运行盘已归档：{state['archived_runtime_path']}")
    print(f"下一步：./tools/ctflab probe {state['profile_id']} --timeout 300")
    return 0


def cmd_run(manager: LabManager, args: argparse.Namespace) -> int:
    states = manager.run(args.profiles, headless=args.headless, pcap=args.pcap,
                         allow_internet=args.internet, clipboard=args.clipboard,
                         display=args.display)
    for state in states:
        forwards = ", ".join(f"{name}=127.0.0.1:{port}" for name, port in state.get("host_forwards", {}).items()) or "无主机端口映射"
        print(f"已启动 {state['profile_id']}（PID {state['pid']}，实验网 TCP {state['lab_port']}；{forwards}）")
        if state.get("internet_enabled"):
            print("  Kali 默认通过 user-mode NAT 联网；Smoke/Basic Pentesting 2 仍保持管理网隔离。")
        if state.get("display_backend") == "spice":
            print(f"  SPICE 动态分辨率端点：{state['spice_endpoint']}")
    pcap_paths = {str(state.get("pcap_path")) for state in states if state.get("pcap_path")}
    for pcap_path in sorted(pcap_paths):
        print(f"PCAP：{pcap_path}")
    return 0


def _status_report(manager: LabManager) -> dict[str, Any]:
    """状态快照（GUI 与文本模式共用同一数据源，避免两套判断）。"""
    running = {state["profile_id"]: state for state in manager.running_states()}
    stale = {profile_id: pid for profile_id, pid in manager.stale_runtime_states()}
    profiles: list[dict[str, Any]] = []
    for profile_id in available_profiles():
        profile = load_profile(profile_id)
        image = manager.image_state(profile_id) or {}
        state = running.get(profile_id) or {}
        lab_port = int(state.get("lab_port", 0) or 0)
        network = (manager.network_state(lab_port) or {}) if lab_port else {}
        profiles.append({
            "id": profile_id,
            "name": str(profile.get("name", profile_id)),
            "architecture": str((profile.get("guest") or {}).get("architecture", "")),
            "firmware": str((profile.get("guest") or {}).get("firmware", "")),
            "imported": bool(image),
            "source_format": image.get("source_format"),
            "base_path": image.get("base_path"),
            "base_sha256": image.get("base_sha256"),
            "uefi_vars_path": image.get("uefi_vars_path"),
            "running": bool(state),
            "pid": int(state.get("pid", 0) or 0),
            "log_path": state.get("log_path"),
            "lab_port": lab_port or None,
            "host_forwards": state.get("host_forwards") or {},
            "internet_enabled": bool(state.get("internet_enabled")),
            "display_backend": state.get("display_backend", "cocoa"),
            "stale_pid": stale.get(profile_id),
            "network": {
                "client_count": network.get("client_count"),
                "learned_macs": len(network.get("learned_macs", []) or []),
                "pcap_path": network.get("pcap_path"),
            } if network else None,
        })
    return {"schema": 1, "state_dir": str(manager.state_dir), "profiles": profiles,
            "running_count": len(running)}


def cmd_status(manager: LabManager, args: argparse.Namespace) -> int:
    if getattr(args, "json", False):
        print(json.dumps(_status_report(manager), ensure_ascii=False, indent=2))
        return 0
    running = {state["profile_id"]: state for state in manager.running_states()}
    shown_networks: set[int] = set()
    printed = False
    for profile_id in available_profiles():
        state = running.get(profile_id)
        if not state:
            continue
        printed = True
        print(f"{profile_id}: running PID={state['pid']} lab=tcp://127.0.0.1:{state['lab_port']} log={state['log_path']}")
        if state.get("internet_enabled"):
            print("  网络：Kali 默认 user-mode NAT（实验网仍经回环交换机隔离）")
        if state.get("host_forwards"):
            print("  端口：" + ", ".join(f"{key}=127.0.0.1:{value}" for key, value in state["host_forwards"].items()))
        lab_port = int(state.get("lab_port", 0))
        if lab_port and lab_port not in shown_networks:
            shown_networks.add(lab_port)
            network = manager.network_state(lab_port) or {}
            counters = network.get("counters", {})
            print(
                "  交换机："
                f"clients={network.get('client_count', '?')} "
                f"macs={len(network.get('learned_macs', []))} "
                f"rx={counters.get('received', 0)} "
                f"forwarded={counters.get('forwarded', 0)} "
                f"dropped={counters.get('dropped_rate_limit', 0)}"
            )
            if network.get("pcap_path"):
                print(f"  PCAP：{network['pcap_path']}")
    for profile_id, pid in manager.stale_runtime_states():
        printed = True
        print(f"{profile_id}: 进程已退出（原 PID {pid}），状态文件待清理；可执行 stop --all。")
    for port in manager.network_ports():
        if port in shown_networks:
            continue
        printed = True
        network = manager.network_state(port) or {}
        if bool_pid_alive(int(network.get("pid", 0))):
            print(f"残留实验网：lab=tcp://127.0.0.1:{port}（无运行实例），可执行 stop --all。")
        else:
            print(f"实验网状态文件残留：port {port}（进程已退出），可执行 stop --all。")
    if not printed:
        print("没有正在运行的 CTFLab 实例。")
    return 0


def cmd_stop(manager: LabManager, args: argparse.Namespace) -> int:
    stopped = manager.stop(args.profiles, stop_all=args.all, graceful=args.graceful)
    print("已停止：" + (", ".join(stopped) if stopped else "没有运行中的实例"))
    return 0


def cmd_reset(manager: LabManager, args: argparse.Namespace) -> int:
    manager.reset(args.profile, force=args.force)
    print(f"已重置 {args.profile}：下次启动会从基础镜像创建全新 overlay。")
    return 0


def cmd_health(manager: LabManager, args: argparse.Namespace) -> int:
    results = manager.health(args.profile)
    failed = False
    pending = False
    for result in results:
        status = "OK" if result["ok"] is True else "WAIT" if result["ok"] is None else "FAIL"
        if not getattr(args, "json", False):
            print(f"{status:4} {result['name']}: {result['detail']}")
        failed |= result["ok"] is False
        pending |= result["ok"] is None
    if getattr(args, "json", False):
        print(json.dumps({"schema": 1, "profile": PROFILE_ALIASES.get(args.profile, args.profile),
                          # ok 只表示没有明确失败；pending 单独表达“仍在启动/检查中”，
                          # 防止 GUI 把 WAIT 错显示为健康通过。
                          "ok": not failed, "pending": pending, "checks": results},
                         ensure_ascii=False, indent=2))
    return 1 if failed else 0


def cmd_probe(manager: LabManager, args: argparse.Namespace) -> int:
    if args.matrix:
        result = manager.boot_matrix(
            args.profile,
            per_candidate_timeout=args.matrix_timeout,
            max_candidates=args.matrix_max,
            start_at=args.matrix_start,
        )
        for attempt in result["attempts"]:
            if attempt.get("error"):
                print(f"  {attempt['label']}: 启动失败（{attempt['error']}）")
            else:
                print(f"  {attempt['label']}: {attempt['verdict']}（画面 {attempt['screen']}）")
        if result["succeeded"]:
            selected = result["selected"]
            print(f"矩阵结论：{selected['label']} 可以启动（{selected['verdict']}）；"
                  f"请人工查看截图后再修改 profile。")
            print(f"矩阵报告：{result['report_path']}")
            return 0
        print("矩阵结论：所有白名单候选都没有识别到可用启动画面；请人工检查截图与日志。")
        print(f"矩阵报告：{result['report_path']}")
        return 1
    report = manager.probe(args.profile, timeout_seconds=args.timeout, keep_running=args.keep_running)
    print(f"探测结论：{report['verdict']}")
    display = report.get("display", {})
    print(f"显示活动：{'是' if display.get('active') else '否'}（{display.get('detail')}）")
    screen = report.get("screen", {})
    classification = str(screen.get("classification", "unknown"))
    print(
        "画面分类："
        f"{SCREEN_CLASS_LABELS.get(classification, classification)} "
        f"（置信度 {screen.get('confidence', 'low')}，OCR {'可用' if screen.get('available') else '不可用'}）"
    )
    for warning in screen.get("warnings", []):
        print(f"画面警告：{warning}")
    for result in report.get("health", []):
        status = "OK" if result["ok"] is True else "WAIT" if result["ok"] is None else "FAIL"
        print(f"{status:4} {result['name']}: {result['detail']}")
    if report.get("screenshot_path"):
        print(f"截图：{report['screenshot_path']}")
    print(f"报告：{report['report_path']}")
    if report.get("requires_human_review"):
        print("需要人工查看截图并确认登录/错误画面；当前不会自动标记为已验证交付。")
    return 0 if report["verdict"] in {"service_ready", "network_and_display_candidate", "display_activity_only"} else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ctflab", description="CTFLab Mac M 第一阶段运行器")
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR, help="运行时状态目录")
    parser.add_argument("--version", action="version", version=f"%(prog)s {CTFLAB_VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    profile_choices = available_profiles() + sorted(PROFILE_ALIASES)

    subparsers.add_parser("doctor", help="检查本机 QEMU/UTM/PyYAML 依赖")
    subparsers.add_parser("list", help="列出内置配置及导入状态")

    inspect_parser = subparsers.add_parser("inspect", help="只读探测镜像并生成带置信度的硬件候选")
    inspect_parser.add_argument("source", help="磁盘、OVA 或虚拟机目录")
    inspect_parser.add_argument("--json", action="store_true", help="输出完整 JSON 报告")
    inspect_parser.add_argument("--no-hash", action="store_true", help="跳过耗时的 SHA-256（正式导入仍会计算）")

    onboard_parser = subparsers.add_parser("onboard", help="探测新镜像、生成候选配置并安全导入")
    onboard_parser.add_argument("source", help="磁盘、OVA 或虚拟机目录")
    onboard_parser.add_argument("--id", required=True, help="新配置 id，例如 vulnbox-1")
    onboard_parser.add_argument("--name", help="显示名称；默认由文件名生成")
    onboard_parser.add_argument("--architecture", choices=["auto", "x86_64", "aarch64"], default="auto")
    onboard_parser.add_argument("--firmware", choices=["auto", "bios", "uefi"], default="auto")
    onboard_parser.add_argument("--disk-bus", choices=["auto", "ide", "sata", "scsi", "virtio"], default="auto")
    onboard_parser.add_argument("--disk-controller", help="受控控制器型号，例如 lsi53c895a 或 ich9-ahci")
    onboard_parser.add_argument("--network-adapter", choices=["auto", "e1000", "pcnet", "virtio-net-pci"], default="auto")
    onboard_parser.add_argument("--memory-mb", type=int)
    onboard_parser.add_argument("--cpus", type=int)
    onboard_parser.add_argument("--lab-ip", help="固定实验网地址；默认自动从 192.168.242.30 起分配")
    onboard_parser.add_argument("--no-import", action="store_true", help="只生成候选配置和报告，不转换磁盘")

    import_parser = subparsers.add_parser("import", help="导入 VMDK/QCOW2/OVA 等镜像")
    import_parser.add_argument("profile", choices=profile_choices)
    import_parser.add_argument("source", help="磁盘文件或包含单个磁盘的目录")
    import_parser.add_argument("--expect-sha256",
                               help="期望的来源镜像 SHA-256（下载后校验；不一致拒绝导入）")
    import_parser.add_argument("--manifest", type=Path,
                               help="分发清单 DISTRIBUTION.json：按 profile 核对哈希，并自动套用配套 NVRAM 模板")
    import_parser.add_argument("--nvram", type=Path,
                               help="UEFI NVRAM 模板（aarch64 已安装系统）；使用 --manifest 时自动解析")

    dist_parser = subparsers.add_parser(
        "dist", help="分发准备（路线 A）：压缩基盘并生成 DISTRIBUTION.json/SHA256SUMS/README")
    dist_sub = dist_parser.add_subparsers(dest="dist_command", required=True)
    dist_prepare = dist_sub.add_parser(
        "prepare", help="为一个 profile 生成分发文件；可多次执行合并进同一清单")
    dist_prepare.add_argument("--profile", choices=profile_choices, required=True)
    dist_prepare.add_argument("--out", type=Path, required=True, help="分发目录（写入/合并清单）")
    dist_prepare.add_argument("--source", type=Path, help="基盘来源；缺省用该 profile 当前已导入的基盘")
    dist_prepare.add_argument("--nvram", type=Path, help="UEFI NVRAM 模板；缺省用已导入的登记值")
    dist_prepare.add_argument("--no-nvram", action="store_true",
                              help="明确不登记 NVRAM 模板（aarch64 不推荐：跳过的是已验证的启动路径）")
    dist_prepare.add_argument("--no-compress", action="store_true",
                              help="不压缩（仅小镜像或诊断用）")
    dist_verify = dist_sub.add_parser(
        "verify", help="复核分发目录：逐文件大小与 SHA-256 与清单一致")
    dist_verify.add_argument("--dir", type=Path, required=True)
    dist_verify.add_argument("--json", action="store_true",
                             help="输出机器可读报告（GUI 使用；失败时返回 1 且仍打印 JSON）")

    install_parser = subparsers.add_parser("install", help="从 ARM64 安装 ISO 创建 Kali 基础镜像")
    install_parser.add_argument("profile", choices=profile_choices)
    install_parser.add_argument("iso", help="ARM64 Kali/Debian 安装 ISO")
    install_parser.add_argument("--disk-size-gb", type=int, default=64, help="目标磁盘虚拟容量，默认 64GiB")
    install_parser.add_argument("--unattended", action="store_true", help="自动安装 XFCE；用户名 kali，口令从 CTFLAB_INSTALL_PASSWORD 读取")
    install_parser.add_argument("--headless", action="store_true", help="后台安装，不打开 QEMU 窗口")
    install_parser.add_argument("--resume", action="store_true", help="使用相同 ISO 重新启动已有安装目标")
    install_parser.add_argument("--confirm-reinstall", action="store_true", help="确认自动安装重启会重新分区已有安装目标")

    install_status_parser = subparsers.add_parser("install-status", help="查看 ISO 安装任务状态")
    install_status_parser.add_argument("profile", choices=profile_choices)
    install_status_parser.add_argument("--log-tail", action="store_true", help="显示安装日志末尾")

    stop_install_parser = subparsers.add_parser("stop-install", help="停止 ISO 安装任务但保留目标盘")
    stop_install_parser.add_argument("profile", choices=profile_choices)

    finalize_install_parser = subparsers.add_parser("finalize-install", help="把已完成的安装目标登记为候选基础镜像")
    finalize_install_parser.add_argument("profile", choices=profile_choices)
    finalize_install_parser.add_argument("--confirm", action="store_true", help="确认安装器已正常完成并停止")
    finalize_install_parser.add_argument("--from-runtime", action="store_true", help="正常关机后固化 Kali 运行盘中的配置；保留原基盘和运行盘归档")

    run_parser = subparsers.add_parser("run", help="启动一个或多个实验节点")
    run_parser.add_argument("profiles", nargs="+", choices=profile_choices)
    run_parser.add_argument("--headless", action="store_true", help="不打开图形窗口，日志写入 logs/")
    run_parser.add_argument("--clipboard", action="store_true", help="显式允许 Mac 与 Kali 图形桌面双向共享文本剪贴板")
    run_parser.add_argument("--pcap", action="store_true", help="记录隔离实验网的 Ethernet PCAP")
    run_parser.add_argument("--internet", action="store_true",
                            help="兼容旧命令的显式确认；Kali 图形启动默认联网，其他节点仍隔离")
    run_parser.add_argument("--display", choices=("auto", "cocoa", "spice"), default="auto",
                            help="显示后端；默认 auto：Kali 图形启动使用 SPICE 自动分辨率，其他节点使用 Cocoa")

    status_parser = subparsers.add_parser("status", help="查看运行状态")
    status_parser.add_argument("--json", action="store_true",
                               help="输出机器可读状态（GUI 使用；含导入与运行信息）")

    stop_parser = subparsers.add_parser("stop", help="停止实例，默认超时会强制退出；桌面建议 --graceful")
    stop_parser.add_argument("--graceful", action="store_true", help="只请求正常关机，30 秒超时后保留实例，不强制断电")
    # 这里不在 argparse 层设置 choices，否则 Python 3.10 在“空位置参数 + --all”时
    # 会把空列表本身当成一个候选值；具体配置名在执行阶段校验。
    stop_parser.add_argument("profiles", nargs="*", metavar="PROFILE")
    stop_parser.add_argument("--all", action="store_true", help="停止所有实例")

    reset_parser = subparsers.add_parser("reset", help="删除运行 overlay，恢复到基础镜像")
    reset_parser.add_argument("profile", choices=profile_choices)
    reset_parser.add_argument("--force", action="store_true", help="运行中也先停止再重置")

    health_parser = subparsers.add_parser("health", help="检查进程和已配置的端口")
    health_parser.add_argument("profile", choices=profile_choices)
    health_parser.add_argument("--json", action="store_true",
                               help="输出机器可读健康检查结果（GUI 使用）")

    probe_parser = subparsers.add_parser("probe", help="启动候选并收集 QMP 截图、DHCP 和服务证据")
    probe_parser.add_argument("profile", choices=profile_choices)
    probe_parser.add_argument("--timeout", type=int, help="探测超时秒数，默认使用配置 readiness 超时")
    probe_parser.add_argument("--keep-running", action="store_true", help="探测结束后保留本次启动的虚拟机")
    probe_parser.add_argument("--matrix", action="store_true", help="受控启动回退矩阵：按白名单尝试 BIOS/UEFI × IDE/SATA/SCSI/VirtIO")
    probe_parser.add_argument("--matrix-timeout", type=int, default=90, help="矩阵中每个候选的探测秒数，默认 90")
    probe_parser.add_argument("--matrix-max", type=int, help="只尝试前 N 个候选（用于快速排查）")
    probe_parser.add_argument("--matrix-start", type=int, default=1, help="跳过前 N-1 个候选，从第 N 个开始（用于验证回退路径与定位）")

    utm_export_parser = subparsers.add_parser(
        "utm-export",
        help="把已导入的基础镜像导出为新的 UTM 包（路径 A；支持 aarch64+UEFI 与 x86_64+BIOS 变体）",
    )
    utm_export_parser.add_argument("profile", choices=profile_choices)
    utm_export_parser.add_argument("--out", type=Path, required=True, help="输出目录；目标已存在时一律拒绝覆盖")
    utm_export_parser.add_argument("--name", help="包名（不含 .utm 后缀），默认使用配置 id")
    package_parser = subparsers.add_parser(
        "package",
        help="构建/校验可分发安装包（Task 6.1；源码级，不含 .app/QEMU 运行时/签名）",
    )
    package_sub = package_parser.add_subparsers(dest="package_command", required=True)
    package_build = package_sub.add_parser(
        "build", help="构建 ctflab-<version>-macos-arm64.tar.gz（含 MANIFEST/SBOM/许可证/install.sh）")
    package_build.add_argument("--out", type=Path, required=True, help="输出目录；目标已存在时一律拒绝覆盖")
    package_build.add_argument("--version", help=f"版本号（必须与当前 CTFLAB_VERSION={CTFLAB_VERSION} 一致）")
    package_verify = package_sub.add_parser(
        "verify", help="校验安装包：旁车 SHA-256、包内 MANIFEST、逐文件哈希与禁止项")
    package_verify.add_argument("bundle", type=Path)

    content_parser = subparsers.add_parser("content", help="构建/校验 .ctflab 内容包（不含虚拟磁盘）")
    content_sub = content_parser.add_subparsers(dest="content_command", required=True)
    content_pack = content_sub.add_parser(
        "pack", help="按 profile 构建 <id>-<version>.ctflab（profile + 来宾修复，无磁盘）")
    content_pack.add_argument("profile", choices=profile_choices)
    content_pack.add_argument("--out", type=Path, required=True, help="输出目录；目标已存在时一律拒绝覆盖")
    content_pack.add_argument("--version", default="1.0.0", help="内容包版本，默认 1.0.0")
    content_verify = content_sub.add_parser(
        "verify", help="校验内容包：哈希、清单、禁止内容与 requires_ctflab 版本门禁")
    content_verify.add_argument("package", type=Path)
    content_verify.add_argument("--no-version-check", action="store_true",
                                help="跳过 requires_ctflab 门禁（仅诊断用，不影响其他检查）")
    content_unpack = content_sub.add_parser(
        "unpack", help="校验后解包到目标目录（逐文件复核哈希；不覆盖既有文件）")
    content_unpack.add_argument("package", type=Path)
    content_unpack.add_argument("--out", type=Path, required=True)

    app_parser = subparsers.add_parser(
        "app", help="构建/校验含受控 QEMU + Python 运行时的 CTFLab.app（Task 6.2/6.3B；本地构建，不做公证）")
    app_sub = app_parser.add_subparsers(dest="app_command", required=True)
    app_build = app_sub.add_parser("build", help="构建 CTFLab.app（排他发布；默认 ad-hoc 签名）")
    app_build.add_argument("--out", type=Path, required=True, help="输出目录；目标已存在时一律拒绝覆盖")
    app_build.add_argument("--version", help=f"覆盖版本号，默认 {CTFLAB_VERSION}")
    app_build.add_argument("--qemu-root", type=Path,
                           help="QEMU 安装根目录（含 bin/ 与 share/qemu/）；默认从 PATH 探测")
    app_build.add_argument("--spice-client", type=Path,
                           help="可选 SPICE 客户端（当前支持 spicy）；提供后随 app 打包并做动态库闭包")
    app_build.add_argument("--python-runtime", type=Path, required=True,
                           help="python-build-standalone install_only_stripped 的 .tar.gz 或解包目录"
                                "（必填：app 必须内置解释器，不回退系统 Python）")
    app_build.add_argument("--python-runtime-sha256",
                           help="期望的 Python 运行时归档 SHA-256（可选，强制校验来源）")
    app_build.add_argument("--pyyaml", type=Path, required=True,
                           help="PyYAML wheel（.whl）或解包目录（必填：随包分发，接收者无需 pip）")
    app_build.add_argument("--pyyaml-sha256",
                           help="期望的 PyYAML wheel SHA-256（可选，强制校验来源）")
    app_build.add_argument("--sign-identity",
                           help="codesign 身份；缺省为 ad-hoc（-）。本机不存在的身份会直接失败")
    app_build.add_argument("--unsigned", action="store_true",
                           help="不签名（仅诊断用；Apple Silicon 上可能无法运行）")
    app_build.add_argument("--allow-incomplete-license-texts", action="store_true",
                           help="允许许可证文本缺失（本地测试用；会在 MANIFEST 记录分发阻塞）")
    app_verify = app_sub.add_parser(
        "verify", help="校验 CTFLab.app：结构、清单哈希、运行时引用与签名分级")
    app_verify.add_argument("app", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "doctor": cmd_doctor,
        "list": cmd_list,
        "inspect": cmd_inspect,
        "onboard": cmd_onboard,
        "import": cmd_import,
        "install": cmd_install,
        "install-status": cmd_install_status,
        "stop-install": cmd_stop_install,
        "finalize-install": cmd_finalize_install,
        "run": cmd_run,
        "status": cmd_status,
        "stop": cmd_stop,
        "reset": cmd_reset,
        "health": cmd_health,
        "probe": cmd_probe,
        "utm-export": cmd_utm_export,
    }
    package_handlers = {"build": cmd_package_build, "verify": cmd_package_verify}
    content_handlers = {"pack": cmd_content_pack, "verify": cmd_content_verify,
                        "unpack": cmd_content_unpack}
    app_handlers = {"build": cmd_app_build, "verify": cmd_app_verify}
    dist_handlers = {"prepare": cmd_dist_prepare, "verify": cmd_dist_verify}
    try:
        # 纯打包/校验命令不需要运行状态；避免仅执行 package/content 时在默认
        # 状态目录创建 locks/ 等运行时目录，保持该类操作的只读/构建边界。
        if args.command == "package":
            return package_handlers[args.package_command](None, args)  # type: ignore[arg-type]
        if args.command == "content":
            return content_handlers[args.content_command](None, args)  # type: ignore[arg-type]
        if args.command == "app":
            return app_handlers[args.app_command](None, args)  # type: ignore[arg-type]
        if args.command == "dist" and args.dist_command == "verify":
            # verify 只读分发目录，不需要运行状态；不要在默认状态目录创建 locks/。
            return dist_handlers[args.dist_command](None, args)  # type: ignore[arg-type]
        manager = LabManager(args.state_dir)
        if args.command == "stop" and not args.all and not args.profiles:
            parser.error("stop 需要提供配置名，或使用 --all")
        if args.command == "stop":
            unknown = sorted({profile_id for profile_id in args.profiles if PROFILE_ALIASES.get(profile_id, profile_id) not in available_profiles()})
            if unknown:
                raise CTFLabError(f"未知配置：{', '.join(unknown)}。可用配置：{', '.join(available_profiles())}")
        if args.command == "onboard":
            # onboard 会同时分配 IP、写入 profile、保存探测报告并可能导入镜像，
            # 整体持锁才能避免两个终端生成重复地址或覆盖中间状态。
            with manager.operation_lock(f"接入 {args.id}"):
                return handlers[args.command](manager, args)
        if args.command == "dist":
            return dist_handlers[args.dist_command](manager, args)  # type: ignore[arg-type]
        return handlers[args.command](manager, args)
    except CTFLabError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
