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
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import secrets
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator, TextIO
import urllib.error
import urllib.parse
import urllib.request

from ctflab_inspect import (IMPORT_CONTROL, import_session, InspectionError, PreparedOva, inspect_image, prepare_ova,
                            profile_from_report, report_text, require_free_space, source_identity)
from ctflab_utm import PublishError, UTMExportError, exclusive_rename, export_utm_package

try:
    import yaml
except ImportError:  # pragma: no cover - 在不含 PyYAML 的分发环境中给出清晰提示
    yaml = None


# 长驻 QEMU/交换机由运行状态文件管理。父 CLI 在同一进程内做探测时仍需保留
# Popen 对象并在停止后 wait，否则 Python 会在子进程仍运行时产生 ResourceWarning，
# 也可能延后回收已退出子进程。
_BACKGROUND_PROCESSES: dict[int, subprocess.Popen[Any]] = {}
_BACKGROUND_PROCESSES_LOCK = threading.Lock()


def track_background_process(process: subprocess.Popen[Any]) -> None:
    with _BACKGROUND_PROCESSES_LOCK:
        _BACKGROUND_PROCESSES[process.pid] = process


def reap_background_process(pid: int) -> None:
    with _BACKGROUND_PROCESSES_LOCK:
        process = _BACKGROUND_PROCESSES.pop(pid, None)
    if process is None:
        return
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        # 仍在运行说明停止流程保留了它；继续跟踪，绝不因回收辅助逻辑强杀。
        with _BACKGROUND_PROCESSES_LOCK:
            _BACKGROUND_PROCESSES[pid] = process


PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 内置 profile 跟随源码/App 资源，只读；用户通过 GUI/CLI 接入的新镜像必须写在状态目录外部，
# 这样 App 签名与升级不会被改写，也不会把课堂内置配置交给候选镜像覆盖。
BUILTIN_PROFILE_DIR = PROJECT_ROOT / "tools" / "ctflab_profiles"
# 兼容既有测试和引用；新代码请通过 profile_path()/available_profiles() 访问。
PROFILE_DIR = BUILTIN_PROFILE_DIR
DEFAULT_STATE_DIR = Path.home() / "Library" / "Application Support" / "CTFLab"
# 版本是打包（Task 6.1）、内容包版本门禁与 SBOM 的单一来源。
CTFLAB_VERSION = "0.1.1"
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


def import_hash(path: Path, stage: str) -> str:
    control = IMPORT_CONTROL.get()
    if control is None:
        return sha256_file(path)
    digest = hashlib.sha256()
    total, done = path.stat().st_size, 0
    control.progress(stage, 0, total)
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            control.check()
            digest.update(chunk)
            done += len(chunk)
            control.progress(stage, done, total)
    return digest.hexdigest()


def run_import_conversion(command: list[str]) -> None:
    control = IMPORT_CONTROL.get()
    if control is None:
        run_command(command, capture=False)
        return
    control.progress("转换")
    try:
        process = subprocess.Popen(command)
    except OSError as exc:
        raise CTFLabError(f"无法启动镜像转换：{exc}") from exc
    try:
        last_progress = time.monotonic()
        while process.poll() is None:
            control.check()
            if time.monotonic() - last_progress >= 1:
                control.progress("转换")
                last_progress = time.monotonic()
            try:
                process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                pass
        control.check()
        if process.returncode != 0:
            raise CTFLabError(f"镜像转换失败（退出码 {process.returncode}），候选配置保留，可重试。")
    finally:
        # 必须先回收本次子进程，再由调用者删除其未完成文件；不影响其他 QEMU。
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


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
        candidate = root / "CTFLabDisplay.app/Contents/MacOS/spicy"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        for name in SPICE_CLIENT_NAMES:
            candidate = root / "bin" / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        return None
    return shutil.which(SPICE_CLIENT_NAMES[0]) or shutil.which(SPICE_CLIENT_NAMES[1])


def spice_client_command(client: str, endpoint: Path | str, clipboard: bool = False,
                         qemu_pid: int | None = None,
                         password_file: Path | None = None,
                         geometry: str | None = None,
                         state_file: Path | None = None,
                         display_quality: str | None = None,
                         file_transfer: bool = False) -> list[str]:
    """构造受控客户端命令；只有显式 ``--clipboard`` 才打开剪贴板。

    ``qemu_pid`` 不是用户可控参数。传入后，内置 ``spicy`` 会在 QEMU 异常退出时自行
    结束，覆盖 SPICE 断开事件没有及时送达的孤儿窗口场景。
    ``endpoint`` 可以是 UNIX socket 路径（构造 ``spice+unix://`` URI），或已经以
    ``spice://`` 开头的 TCP URI。``password_file`` 只用于 TCP 回退模式的每次运行
    ticket：路径进入客户端参数，ticket 内容本身不进入任何命令行或状态文件。
    ``geometry``（``WxH``）显式覆盖初始窗口尺寸；``state_file`` 让客户端跨次启动
    记忆窗口尺寸与全屏状态。两者只对受控 spicy 生效，不透传其它参数。
    """
    endpoint_text = str(endpoint)
    if endpoint_text.startswith("spice://"):
        client_uri = endpoint_text
    else:
        client_uri = f"spice+unix://{endpoint}"
    # 正式 App 固定命名为 spicy；本机 E2E 会把同一受控客户端编译成
    # ctflab-spicy-<build-id>，仍使用 --uri 协议。其它客户端保留 remote-viewer 的 URI 参数约定。
    client_name = Path(client).name.lower()
    if client_name == "spicy" or client_name.startswith("ctflab-spicy"):
        command = [client, "--uri", client_uri]
        if clipboard:
            command.append("--clipboard")
        if file_transfer:
            command.append("--file-transfer")
        if password_file is not None:
            command += ["--password-file", str(password_file)]
        if qemu_pid is not None:
            if qemu_pid <= 0:
                raise CTFLabError("SPICE 客户端监控需要有效的 QEMU PID。")
            command += ["--qemu-pid", str(qemu_pid)]
        if geometry is not None:
            geometry_match = re.fullmatch(r"([0-9]{3,5})x([0-9]{3,5})", geometry)
            if (geometry_match is None
                    or not 400 <= int(geometry_match.group(1)) <= 16384
                    or not 300 <= int(geometry_match.group(2)) <= 16384):
                raise CTFLabError(f"非法的客户端窗口几何：{geometry}（应为 WxH，"
                                  "宽 400-16384、高 300-16384）。")
            command += ["--geometry", geometry]
        if state_file is not None:
            command += ["--state-file", str(state_file)]
        if display_quality is not None:
            if display_quality not in {"sharp", "smooth"}:
                raise CTFLabError(f"不支持的显示质量偏好：{display_quality}（可选 sharp、smooth）。")
            command += ["--display-quality", display_quality]
        return command
    if file_transfer:
        raise CTFLabError("文件传输需要受控客户端支持，不能透传到未知客户端。")
    if password_file is not None:
        raise CTFLabError("TCP 回退模式的 ticket 需要受控客户端（spicy/ctflab-spicy）支持。")
    return [client, client_uri]


# 绝对鼠标走 usb-tablet（内核 evdev，按当前屏幕实时映射）而不是 vdagent 的
# uinput 路径（QEMU 选项 agent-mouse=off）。实测 vdagent 路径在客户端驱动的
# 分辨率切换后，指针按旧屏幕比例换算（如 1512x917 下 (400,500)→(472,573)）。

def terminate_spice_client(client_pid: int) -> None:
    """有界结束显示客户端：先 SIGTERM 等待 6 秒，仍在才 SIGKILL。

    QEMU 干净退出（ACPI 关机或 QMP quit）时，spice-server 在 RedClient 销毁路径
    存在崩溃缺陷（InputsChannel::release_keys 段错误，见 2026-10-05 验证记录的
    崩溃报告汇总）。停止流程先让客户端断开连接再结束 QEMU，绕开该路径。
    客户端（GtkApplication 外壳）的优雅退出含会话断开、窗口状态保存与应用
    关闭迭代，实测可超过 1 秒；且主循环偶发被过渡轮询阻塞数秒，客户端自带 alarm(4) 兜底，这里给 6 秒。
    """
    if client_pid <= 0 or not bool_pid_alive(client_pid):
        return
    try:
        os.kill(client_pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 6.0
    while bool_pid_alive(client_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if bool_pid_alive(client_pid):
        try:
            os.kill(client_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def resolve_display_backend(profile_id: str, requested: str, *, headless: bool = False,
                            spice_supported: bool = False) -> str:
    """解析显示后端；Kali 的 ``auto`` 在能力完整时默认使用真实动态分辨率。

    ``auto`` 只在 Kali 图形模式且 QEMU、spicevmc、virtserialport 与受控客户端均通过
    能力探测时选择 SPICE；缺件时退化为 Cocoa，使普通启动仍可用。用户显式请求
    ``spice`` 时不允许退化，仍由调用方在创建网络和 overlay 前明确失败。无头与靶机
    始终使用 Cocoa 语义（随后由命令构造器转为 ``-display none`` 或固定显示）。
    """
    if requested not in {"auto", "cocoa", "spice"}:
        raise CTFLabError(f"不支持的显示后端：{requested}（可选 auto、cocoa 或 spice）。")
    if requested == "auto":
        if profile_id == "kali-arm64" and not headless and spice_supported:
            return "spice"
        return "cocoa"
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
    built_in = BUILTIN_PROFILE_DIR / f"{profile_id}.yaml"
    if built_in.is_file() and not built_in.is_symlink():
        return built_in
    candidate = user_profile_dir() / f"{profile_id}.yaml"
    if candidate.is_file() and not candidate.is_symlink():
        return candidate
    raise CTFLabError(f"未知配置：{profile_id}。可用配置：{', '.join(available_profiles())}")


def user_profile_dir() -> Path:
    """返回用户候选 profile 的唯一可写目录。

    `CTFLAB_PROFILE_DIR` 仅供隔离验收或 GUI 的临时状态目录覆盖；正常运行固定在
    `~/Library/Application Support/CTFLab/profiles`。该函数不创建目录，纯读取命令不会产生文件。
    """
    configured = os.environ.get("CTFLAB_PROFILE_DIR")
    return Path(configured).expanduser() if configured else DEFAULT_STATE_DIR / "profiles"


def profile_exists(profile_id: str) -> bool:
    """内置和用户目录任一存在同名常规文件即视为已占用，禁止候选覆盖。"""
    profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
    return any(
        path.is_file() and not path.is_symlink()
        for path in (BUILTIN_PROFILE_DIR / f"{profile_id}.yaml", user_profile_dir() / f"{profile_id}.yaml")
    )


def available_profiles() -> list[str]:
    # 内置 profile 优先，用户同名文件既不覆盖也不显示为第二份；符号链接一律不作为配置载入。
    profile_ids: set[str] = set()
    for directory in (BUILTIN_PROFILE_DIR, user_profile_dir()):
        if not directory.is_dir():
            continue
        for path in directory.glob("*.yaml"):
            if path.is_file() and not path.is_symlink():
                profile_ids.add(path.stem)
    return sorted(profile_ids)


LAB_NETWORK = "192.168.242.0/24"
_READINESS_HTTP_PATH_RE = re.compile(r"^/[^@\s]*$")


def validate_http_check_path(path_value: Any, path: Path) -> str:
    """HTTP 就绪检查只允许站内相对路径；拒绝 userinfo/绝对 URL/控制字符逃逸。

    `http://127.0.0.1:<port>` + path 拼接出的最终 URL 会按 URL 语义解析：
    `@example.invalid/` 这类值会把请求指向外部主机，这里在配置层直接拒绝。
    """
    if not isinstance(path_value, str) or not _READINESS_HTTP_PATH_RE.match(path_value):
        raise CTFLabError(
            f"HTTP 就绪检查 path 必须是以 / 开头的站内相对路径（不允许 @ 或空白）：{path}：{path_value!r}")
    return path_value


def http_probe_url(host_port: int, path_value: Any, *, source: Path | None = None) -> str:
    """构造并复核 HTTP 就绪检查的最终 URL；目标主机必须是 127.0.0.1。"""
    path = validate_http_check_path(path_value, source or Path("<runtime>"))
    url = f"http://127.0.0.1:{int(host_port)}{path}"
    host = urllib.parse.urlsplit(url).hostname
    if host != "127.0.0.1":
        raise CTFLabError(f"HTTP 就绪检查目标主机越界（{host}），拒绝探测：{url}")
    return url


class _LoopbackRedirectBlocker(urllib.request.HTTPRedirectHandler):
    """就绪检查不跟随重定向：重定向可能把探测带离授权的回环目标。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        host = urllib.parse.urlsplit(newurl).hostname
        if host not in {"127.0.0.1", "::1"}:
            raise urllib.error.URLError(f"重定向离开回环目标，已阻止：{newurl}")
        return None


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
    readiness = data.get("readiness")
    if readiness is not None:
        if not isinstance(readiness, dict):
            raise CTFLabError(f"readiness 必须是对象：{path}")
        for item in readiness.get("checks", []) or []:
            check = {"type": item} if isinstance(item, str) else item
            if not isinstance(check, dict):
                raise CTFLabError(f"readiness 检查项必须是字符串或对象：{path}")
            if check.get("type") == "http":
                validate_http_check_path(check.get("path", "/"), path)
                expected = check.get("expected_status")
                if expected is not None and not isinstance(expected, int):
                    raise CTFLabError(f"HTTP 就绪检查 expected_status 必须是整数：{path}")


def validate_pack_profile(data: dict[str, Any], path: Path) -> None:
    """内容包 profile 的额外白名单：在 validate_profile 之上收紧字段与敏感能力。

    内容包是外部输入：除运行器读取的白名单字段外，不允许夹带其他键（防止用
    未实现字段误导接收者）；不得声明互联网访问或非 lab 网段——实际联网本来就
    由运行期的显式开关控制，这里拒绝的是误导性/越界声明。
    """
    import ctflab_dist  # noqa: PLC0415

    validate_profile(data, path)
    for section, allowed in (
            (None, ctflab_dist.PACK_PROFILE_TOP_KEYS),
            ("guest", ctflab_dist.PACK_PROFILE_GUEST_KEYS),
            ("disk", ctflab_dist.PACK_PROFILE_DISK_KEYS),
            ("network", ctflab_dist.PACK_PROFILE_NETWORK_KEYS)):
        source = data if section is None else data.get(section) or {}
        unknown = sorted(set(source) - set(allowed))
        if unknown:
            label = "顶层" if section is None else f"{section} 段"
            raise CTFLabError(f"内容包配置{label}含有白名单之外的字段：{path}：{', '.join(unknown)}")
    network = data["network"]
    if network.get("internet") is True:
        raise CTFLabError(f"内容包配置不得声明互联网访问：{path}")
    segment = network.get("segment")
    if segment is not None and segment != "lab":
        raise CTFLabError(f"内容包配置只能使用 lab 实验网段：{path}：{segment!r}")
    lab_ip = network.get("lab_ip")
    if lab_ip is not None:
        import ipaddress  # noqa: PLC0415

        try:
            address = ipaddress.ip_address(str(lab_ip))
        except ValueError as exc:
            raise CTFLabError(f"内容包 lab_ip 不是合法地址：{path}：{lab_ip!r}") from exc
        if address not in ipaddress.ip_network(LAB_NETWORK):
            raise CTFLabError(
                f"内容包 lab_ip 超出实验网段 {LAB_NETWORK}：{path}：{lab_ip}")
    for forward in network.get("host_forwards", []) or []:
        if not isinstance(forward, dict) or set(forward) - {"name", "guest_port", "host_port"}:
            raise CTFLabError(f"内容包端口映射只允许 name/guest_port/host_port：{path}")
    readiness = data.get("readiness")
    if readiness is not None:
        if not isinstance(readiness, dict) or set(readiness) - {"timeout_seconds", "checks"}:
            raise CTFLabError(f"内容包 readiness 只允许 timeout_seconds/checks：{path}")
        timeout = readiness.get("timeout_seconds")
        try:
            timeout_value = int(timeout)
        except (TypeError, ValueError) as exc:
            raise CTFLabError(f"内容包 readiness.timeout_seconds 必须是整数：{path}") from exc
        if not 1 <= timeout_value <= 3600:
            raise CTFLabError(f"内容包 readiness.timeout_seconds 超出范围：{path}：{timeout}")
        checks = readiness.get("checks", [])
        if not isinstance(checks, list):
            raise CTFLabError(f"内容包 readiness.checks 必须是数组：{path}")
        for item in checks:
            if isinstance(item, str):
                if item not in {"dhcp", "tcp", "http", "ssh"}:
                    raise CTFLabError(f"内容包 readiness 检查类型不支持：{path}：{item!r}")
                continue
            if not isinstance(item, dict) or set(item) - {"type", "port", "path", "expected_status"}:
                raise CTFLabError(f"内容包 readiness 检查项只允许 type/port/path/expected_status：{path}")
            if item.get("type") not in {"dhcp", "tcp", "http", "ssh"}:
                raise CTFLabError(f"内容包 readiness 检查类型不支持：{path}：{item.get('type')!r}")
            if item.get("type") in {"tcp", "http", "ssh"}:
                try:
                    port_value = int(item.get("port"))
                except (TypeError, ValueError) as exc:
                    raise CTFLabError(f"内容包 readiness 检查端口必须是整数：{path}") from exc
                if not 1 <= port_value <= 65535:
                    raise CTFLabError(f"内容包 readiness 检查端口超出范围：{path}：{port_value}")
            if item.get("type") == "http":
                validate_http_check_path(item.get("path", "/"), path)
                expected = item.get("expected_status")
                if expected is not None and not isinstance(expected, int):
                    raise CTFLabError(f"HTTP 就绪检查 expected_status 必须是整数：{path}")
    if not isinstance(data.get("verification"), (dict, type(None))):
        raise CTFLabError(f"内容包 verification 段必须是对象或省略：{path}")
    if not isinstance(data.get("description"), (str, type(None))):
        raise CTFLabError(f"内容包 description 必须是字符串或省略：{path}")


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
    # kill(pid, 0) 对等待父进程回收的僵尸也成功；不能将其当作仍在运行。
    # 只查询状态，不回收他人管理的子进程，也不读取进程参数或凭据。
    if sys.platform == "darwin":
        try:
            status = subprocess.run(
                ["/bin/ps", "-p", str(pid), "-o", "stat="],
                capture_output=True, text=True, timeout=1,
            )
            if status.returncode == 0 and status.stdout.strip().startswith("Z"):
                return False
        except (OSError, subprocess.TimeoutExpired):
            pass  # 无法查询时保守保留存活判断，避免误操作运行中实例。
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
BOOT_MATRIX_SUCCESS_VERDICTS = {"service_ready"}
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
    if architecture not in {"aarch64", "x86_64"}:
        raise CTFLabError(f"不支持的客体架构：{architecture}；拒绝猜测为 x86_64。")
    return AARCH64_BOOT_MATRIX if architecture == "aarch64" else X86_BOOT_MATRIX


def ordered_matrix_candidates(profile: dict[str, Any]) -> list[dict[str, str]]:
    """来源生成的候选优先，仍只使用白名单；旧的非候选配置保持原编号。"""
    guest, disk = profile.get("guest", {}), profile.get("disk", {})
    candidates = list(matrix_candidates(str(guest.get("architecture", "x86_64"))))
    if profile.get("detection", {}).get("status") != "candidate":
        return candidates
    preferred = {"firmware": guest.get("firmware"), "bus": disk.get("bus")}
    if disk.get("controller"):
        preferred["controller"] = disk["controller"]
    # 排序不把任意来源控制器或 QEMU 参数放进白名单。
    return sorted(candidates, key=lambda item: (
        item != preferred, item["firmware"] != guest.get("firmware"),
        item["bus"] != disk.get("bus")))


def startup_failure(error: str) -> dict[str, Any]:
    """保守区分宿主阻塞和设备兼容性；未知错误不盲目重启八次。"""
    text = error.lower()
    rules = (
        ("storage", False, ("no space left", "空间不足", "permission denied", "permission error", "权限", "基础镜像已丢失", "overlay 指向旧基础镜像", "failed to get.*lock"), "先检查存储、权限和磁盘锁；不要通过换固件绕过完整性错误。"),
        ("resources", False, ("cannot allocate memory", "内存", "资源预检", "hv_no_device", "error creating platform vgic"), "先检查内存与运行时授权；换磁盘总线不能修复宿主资源问题。"),
        ("firmware_dependency", True, ("缺少 uefi 固件", "未找到.*固件", "未找到.*nvram", "uefi 固件不存在"), "当前固件依赖缺失，其他白名单候选仍可探测；不要推断镜像需要 BIOS。"),
        ("runtime_dependency", False, ("缺少 qemu", "找不到命令", "未找到 qemu", "spice.*未就绪"), "先补齐受控运行时依赖，再重试；不自动回退显示后端。"),
        ("device_compatibility", True, ("is not a valid device model", "unsupported.*device", "bus .*not found", "no .*bus.*found"), "可尝试下一项白名单固件/控制器组合，命中后仍须人工复核。"),
    )
    for category, retryable, patterns, hint in rules:
        if any(re.search(pattern, text) for pattern in patterns):
            return {"category": category, "retryable": retryable, "hint": hint}
    return {"category": "unclassified", "retryable": False,
            "hint": "启动错误尚未归类，停止自动回退；查看原始日志后再决定下一步。"}


def candidate_label(candidate: dict[str, str]) -> str:
    label = f"{candidate['firmware']}/{candidate['bus']}"
    if candidate.get("controller"):
        label += f"/{candidate['controller']}"
    return label


def probe_recommendations(screen_classification: str | None) -> list[str]:
    """按画面分类生成 probe 报告的人工处置建议。"""
    recommendations: list[str] = []
    hints = {
        "uefi_shell": "当前固件未进入系统：检查 EFI 引导项、固件类型和磁盘控制器；UEFI Shell 不是启动成功。",
        "no_boot_device": "检查系统盘选择、BIOS/UEFI 和磁盘控制器；格式转换成功不证明引导器完整。",
        "kernel_error": "内核或根文件系统启动失败：优先核对原控制器和根盘依赖；多磁盘镜像可能缺数据/根盘，不自动改写来宾。",
        "login_ready": "登录画面是启动候选证据；仍需人工登录、验证网络和目标服务，不自动标记为可用。",
        "unknown": "无法可靠识别画面；保留截图与协议证据，不把非黑画面或 DHCP 当成磁盘启动成功。",
    }
    if screen_classification in hints:
        recommendations.append(hints[str(screen_classification)])
    if screen_classification == "pxe_network_boot":
        recommendations.append(
            "来宾进入 PXE 网络启动，说明当前固件/总线组合没有从磁盘引导；"
            "请检查固件（BIOS/UEFI）、磁盘总线与控制器以及启动顺序，"
            "必要时用 probe --matrix 受控回退。"
        )
    return recommendations


def probe_verdict(*, protocol_ready: bool, network_ready: bool, display_active: bool,
                  process_running: bool, screen_classification: str | None = None) -> str:
    """probe 结论判定。

    画面分类属于失败类（含 PXE 网络启动）且没有协议级就绪时，结论必须是该
    分类本身：即使 QEMU 在运行、画面非黑且 DHCP 正常（那是宿主侧 DHCP 服务
    的健康检查，不代表来宾从磁盘引导），也不得返回可被启动矩阵接受的
    ``network_and_display_candidate`` 磁盘启动候选。
    """
    if protocol_ready:
        return "service_ready"
    if screen_classification in SCREEN_FAILURE_CLASSES:
        return str(screen_classification)
    if network_ready and display_active:
        return "network_and_display_candidate"
    if display_active:
        return "display_activity_only"
    if process_running:
        return "process_running_no_readiness"
    return "qemu_exited"


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
    "pxe_network_boot": (
        # SeaBIOS/UEFI 的 PXE 网络引导横幅；OCR 常把 "IPv4" 误读（如 "[Pu4"），
        # 因此锚定 "start pxe over" 而不是完整句子。
        ("Start PXE", r"start\s+pxe\b"),
        ("PXE over IPv4", r"pxe\s+over\s+ipv4"),
        ("Exiting PXE ROM", r"exiting\s+pxe|pxe-m0f"),
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

# pxe_network_boot：磁盘没有引导、固件落到网络启动，也不得成为可被启动矩阵
# 接受的磁盘启动候选（即使 QEMU 在运行、画面非黑且 DHCP 正常）。
SCREEN_FAILURE_CLASSES = {"uefi_shell", "no_boot_device", "pxe_network_boot", "kernel_error"}
SCREEN_CLASS_LABELS = {
    "uefi_shell": "UEFI Shell",
    "no_boot_device": "未找到可启动设备",
    "pxe_network_boot": "PXE 网络启动（磁盘未引导）",
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
    for candidate in ("uefi_shell", "no_boot_device", "pxe_network_boot", "kernel_error",
                      "login_ready", "boot_progress"):
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
        self.content_packs_dir = self.state_dir / "content-packs"
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
                     nvram: str | Path | None = None,
                     ova_disk: str | None = None,
                     _prepared_ova: PreparedOva | None = None) -> dict[str, Any]:
        with self.operation_lock(f"导入 {profile_id}"):
            return self._import_image_unlocked(profile_id, source_arg, expect_sha256=expect_sha256,
                                               manifest=manifest, nvram=nvram,
                                               ova_disk=ova_disk, _prepared_ova=_prepared_ova)

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
                               nvram: str | Path | None = None,
                               ova_disk: str | None = None,
                               _prepared_ova: PreparedOva | None = None) -> dict[str, Any]:
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        profile = load_profile(profile_id)
        plan = self.distribution_expectations(profile_id, expect_sha256, manifest, nvram)
        source = self.discover_source(Path(source_arg))
        source_for_convert = source
        ova_disk_names: list[str] = []
        temporary_dir: tempfile.TemporaryDirectory[str] | None = None
        try:
            source_hash = import_hash(source, "来源校验")
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
            # 已登记 OVA 的重复导入先核对两份完整哈希，再复用基盘；
            # 不为仅需校验的操作再次展开整个归档。旧记录/多盘未选/换盘不走快路径。
            if (source.suffix.lower() == ".ova" and existing
                    and existing.get("source_sha256") == source_hash
                    and existing.get("base_sha256")
                    and Path(str(existing.get("base_path", ""))).is_file()
                    and existing.get("ova_disk")
                    and ((ova_disk is None and existing.get("ova_disk_count") == 1)
                         or ova_disk == existing.get("ova_disk"))):
                return self._reuse_existing_base(profile_id, existing, source,
                                                 updates=updates)
            if source.suffix.lower() == ".ova":
                from ctflab_inspect import find_disk_and_ovf  # noqa: PLC0415
                try:
                    if _prepared_ova is not None:
                        _prepared_ova.validate(source, ova_disk)
                        source_for_convert, _ovf_path, _warnings, ova_disk_names = _prepared_ova.located
                    else:
                        temporary_dir = tempfile.TemporaryDirectory(prefix="ctflab-ova-")
                        source_for_convert, _ovf_path, _warnings, ova_disk_names = find_disk_and_ovf(
                            source, Path(temporary_dir.name), preferred_disk=ova_disk)
                except (InspectionError, tarfile.TarError) as exc:
                    # 损坏 OVA 常见为 tarfile.ReadError；统一包成运行器错误，
                    # 避免裸 traceback 逸出内容包导入等事务边界。
                    raise CTFLabError(f"OVA 无法解析：{source}（{exc}）") from exc
                if len(ova_disk_names) > 1 and ova_disk is None:
                    raise CTFLabError(
                        f"OVA 内有 {len(ova_disk_names)} 个磁盘：{', '.join(ova_disk_names)}。"
                        f"请先用 inspect 查看后用 --disk 选择系统盘重试；"
                        "数据盘暂不支持（多磁盘场景逐步补齐）。")
                if (existing and existing.get("source_sha256") == source_hash
                        and existing.get("ova_disk")
                        and existing["ova_disk"] != source_for_convert.name):
                    raise CTFLabError("该配置已登记此 OVA 的另一磁盘；请用新配置导入，不能静默复用旧盘。")
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
                "base_sha256": import_hash(base_path, "基盘校验与登记"),
                "base_sha256_evidence": evidence,
                "virtual_size": destination_info.get("virtual-size"),
                "imported_at": now_iso(),
                "guest": profile.get("guest", {}),
                **({"ova_disk": Path(str(source_for_convert)).name,
                    "ova_disk_count": len(ova_disk_names)} if ova_disk_names else {}),
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
            if import_hash(base_path, "已登记基盘校验") != registered:
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
        try:
            require_free_space(base_path.parent, source.stat().st_blocks * 512, "基盘转换最低")
        except InspectionError as exc:
            raise CTFLabError(str(exc)) from exc
        temporary_base = base_path.parent / f"{base_path.stem}.partial-{os.getpid()}-{int(time.time() * 1000)}.qcow2"
        try:
            run_import_conversion(
                [qemu_img_path(), "convert", "-f", source_format, "-O", "qcow2", str(source), str(temporary_base)])
            control = IMPORT_CONTROL.get()
            if control:
                control.progress("转换完整性检查")
            if str(qemu_info(temporary_base).get("format") or "") != "qcow2":
                raise CTFLabError("基础镜像转换结果不是 qcow2，拒绝发布。")
            run_command([qemu_img_path(), "check", "-q", str(temporary_base)])
            if control:
                control.check()
                control.committing = True
                control.progress("发布与登记（取消将在本项完成后生效）")
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

    # ---- 内容包（schema 2 分发目录）安装 ----

    def content_pack_profile_status(self, profile_id: str) -> dict[str, Any]:
        """冲突预览：某个 profile id 目前的占用来源与内容哈希（只读，不建目录）。"""
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        builtin = BUILTIN_PROFILE_DIR / f"{profile_id}.yaml"
        if builtin.is_file() and not builtin.is_symlink():
            return {"kind": "builtin", "sha256": sha256_file(builtin)}
        user = user_profile_dir() / f"{profile_id}.yaml"
        if user.is_file() and not user.is_symlink():
            return {"kind": "user", "sha256": sha256_file(user)}
        return {"kind": "absent", "sha256": None}

    def _plan_pack_profiles(self, pack_dir: Path, parsed: dict[str, Any],
                            ctflab_dist: Any) -> dict[str, dict[str, Any]]:
        """安装前把每个包内 profile 完整校验并分类；全部通过才开始写任何文件。"""
        plan: dict[str, dict[str, Any]] = {}
        for profile_id in sorted(parsed["profiles"]):
            slot = parsed["profiles"][profile_id]
            yaml_entry = slot[ctflab_dist.PROFILE_ROLE]
            yaml_path = ctflab_dist.resolve_pack_file(pack_dir, yaml_entry["file"])
            if yaml_path.is_symlink():
                raise CTFLabError(f"包内配置不允许是符号链接：{yaml_entry['file']}")
            if yaml is None:
                raise CTFLabError("当前 Python 缺少 PyYAML，无法校验内容包配置。")
            try:
                data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                raise CTFLabError(f"无法读取包内配置：{yaml_path}（{exc}）") from exc
            if not isinstance(data, dict):
                raise CTFLabError(f"包内配置不是有效的 YAML 映射：{yaml_path}")
            if str(data.get("id", "")) != profile_id:
                raise CTFLabError(f"包内配置 id 与清单登记不一致：{yaml_path}（id={data.get('id')!r}）")
            validate_pack_profile(data, yaml_path)
            local = self.content_pack_profile_status(profile_id)
            action: str
            if local["kind"] == "builtin":
                raise CTFLabError(
                    f"配置 id {profile_id} 与内置配置同名，内容包不得覆盖内置课程："
                    "请让制作者更换 id 后重新打包。")
            if local["kind"] == "user":
                if local["sha256"] == yaml_entry["sha256"]:
                    action = "skip-identical"
                else:
                    raise CTFLabError(
                        f"配置 id {profile_id} 已有同名的用户候选配置，且内容不同，默认不覆盖：\n"
                        f"  已有：{user_profile_dir() / f'{profile_id}.yaml'}"
                        f"（sha256 {str(local['sha256'])[:12]}…）\n"
                        f"  包内：{yaml_entry['file']}（sha256 {yaml_entry['sha256'][:12]}…）\n"
                        "  请更换包内 id 重打，或人工移除已有候选配置后重试。")
            else:
                action = "install"
            plan[profile_id] = {"data": data, "yaml_path": yaml_path, "action": action,
                                "entry": yaml_entry}
        return plan

    def _publish_pack_profile(self, profile_id: str, source: Path) -> Path:
        """把包内 profile 以排他方式发布到用户候选目录；不覆盖任何既有文件。"""
        destination = user_profile_dir() / f"{profile_id}.yaml"
        destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".pack-{profile_id}-", suffix=".yaml", dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(source.read_bytes())
            os.chmod(temporary, 0o600)
            try:
                os.link(temporary, destination)
            except FileExistsError as exc:
                raise CTFLabError(f"配置 {profile_id} 已存在，拒绝覆盖。") from exc
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def install_content_pack(self, pack_dir: Path) -> dict[str, Any]:
        """校验并安装目录式内容包；失败时回滚本轮写入，已提交节点如实保留。

        顺序：整体校验（哈希/大小/结构/冲突）→ 说明文件冲突预检 → 排他安装
        profile → 复制说明 → 逐节点导入基盘（复用 import 的事务与哈希核对，
        NVRAM 模板复制进状态目录，不保留对原包路径的依赖）→ 最后写包记录。
        回滚只删除“本轮创建且未被已提交节点使用”的文件：某个节点导入成功后，
        它的配置、基盘与登记一律保留，后续节点失败不回溯删除。包内 claims 与
        配置中的 verification 段只作为声明存进登记，不设置任何“已验证”状态。
        """
        import ctflab_dist  # noqa: PLC0415

        pack_dir = Path(pack_dir).expanduser()
        with self.operation_lock("导入内容包"):
            try:
                report = ctflab_dist.verify_distribution(
                    pack_dir, profile_status=self.content_pack_profile_status,
                    runner_version=CTFLAB_VERSION)
                manifest = ctflab_dist.load_manifest(pack_dir)
                parsed = ctflab_dist.parse_pack(manifest, runner_version=CTFLAB_VERSION)
            except ctflab_dist.DistError as exc:
                raise CTFLabError(str(exc)) from exc
            if not report["ok"]:
                raise CTFLabError("内容包校验失败，未做任何导入：\n"
                                  + "\n".join(f"  - {problem}" for problem in report["problems"]))
            plan = self._plan_pack_profiles(pack_dir, parsed, ctflab_dist)

            pack_id = parsed["id"]
            manifest_sha256 = sha256_file(ctflab_dist.manifest_path(pack_dir))
            record_path = self.content_packs_dir / pack_id / "pack.json"
            record_existed = record_path.exists()
            installed_profiles: list[str] = []
            skipped_profiles: list[str] = []
            docs_copied: list[str] = []
            docs_dir = self.content_packs_dir / pack_id / "docs"
            docs_dir_created = False
            # created_files 记录本轮创建、且仍可回滚的文件；节点提交后其 YAML 移出该集合。
            created_files: list[tuple[Path, str | None]] = []
            committed: set[str] = set()
            completed_imports: list[str] = []

            # 说明文件冲突必须在任何写入/登记变化之前拒绝（失败重装不得触碰既有状态）。
            if parsed["docs"]:
                for doc_entry in parsed["docs"]:
                    doc_name = str(doc_entry["file"])
                    target = docs_dir / doc_name
                    if target.exists() and sha256_file(target) != doc_entry["sha256"]:
                        raise CTFLabError(
                            f"状态目录中已有同名但内容不同的说明文件，拒绝覆盖：{doc_name}")

            try:
                for profile_id, item in plan.items():
                    if item["action"] == "skip-identical":
                        skipped_profiles.append(profile_id)
                        continue
                    published = self._publish_pack_profile(profile_id, item["yaml_path"])
                    created_files.append((published, profile_id))
                    installed_profiles.append(profile_id)

                if parsed["docs"]:
                    docs_dir.mkdir(parents=True, exist_ok=True)
                    docs_dir_created = True
                    for doc_entry in parsed["docs"]:
                        doc_name = str(doc_entry["file"])
                        source = ctflab_dist.resolve_pack_file(pack_dir, doc_name)
                        target = docs_dir / doc_name
                        if not target.exists():
                            shutil.copy2(source, target)
                            created_files.append((target, None))
                        docs_copied.append(doc_name)

                claims_manifest = parsed["claims"]
                for profile_id, item in plan.items():
                    slot = parsed["profiles"][profile_id]
                    base_entry = slot[ctflab_dist.BASE_ROLE]
                    if base_entry is None:
                        raise CTFLabError(f"内容包节点 {profile_id} 缺少 base 登记，无法导入")
                    # NVRAM 先校验并复制进状态目录：失败时该节点尚未提交、登记未被
                    # 触碰，原有登记（可能指向旧的模板副本）原样保留。导入本身只做
                    # 基盘哈希核对（expect_sha256），不再携带 manifest——避免导入路径
                    # 把 uefi_vars_path 临时写成包内路径并在后续失败时残留。
                    nvram_target: Path | None = None
                    nvram_entry = slot[ctflab_dist.NVRAM_ROLE]
                    if nvram_entry is not None:
                        vars_source = ctflab_dist.resolve_pack_file(pack_dir, nvram_entry["file"])
                        vars_hash = sha256_file(vars_source)
                        vars_target = self.images_dir / profile_id / f"uefi-vars-{vars_hash[:12]}.fd"
                        if vars_target.exists():
                            if sha256_file(vars_target) != vars_hash:
                                raise CTFLabError(
                                    f"状态目录中的 UEFI NVRAM 模板与包内登记不一致，拒绝覆盖：{vars_target}")
                        else:
                            vars_target.parent.mkdir(parents=True, exist_ok=True)
                            temporary = vars_target.parent / f".{vars_target.name}.partial-{os.getpid()}"
                            try:
                                shutil.copy2(vars_source, temporary)
                                os.replace(temporary, vars_target)
                            except OSError as exc:
                                raise CTFLabError(
                                    f"复制 UEFI NVRAM 模板到状态目录失败：{vars_target}（{exc}）") from exc
                            finally:
                                temporary.unlink(missing_ok=True)
                            vars_target.chmod(0o444)
                            created_files.append((vars_target, profile_id))
                        nvram_target = vars_target

                    base_path = ctflab_dist.resolve_pack_file(pack_dir, base_entry["file"])
                    try:
                        state = self._import_image_unlocked(
                            profile_id, base_path,
                            expect_sha256=str(base_entry["sha256"]))
                    except CTFLabError as exc:
                        raise CTFLabError(f"内容包节点 {profile_id} 导入失败：{exc}") from exc
                    committed.add(profile_id)
                    completed_imports.append(profile_id)
                    # 已提交节点：其配置随后续失败不再回滚。
                    created_files = [(path, owner) for path, owner in created_files
                                     if owner != profile_id]

                    base_sha = str(base_entry["sha256"])
                    updates: dict[str, Any] = {
                        "content_pack": {"id": pack_id, "version": parsed["version"],
                                         "manifest_sha256": manifest_sha256},
                        # 导入按包内清单登记的哈希核对基盘；把 method 记为
                        # content-pack-manifest 以区分普通 --manifest 导入。
                        "source_verification": {
                            "expected_sha256": base_sha,
                            "actual_sha256": str(state.get("source_sha256") or base_sha),
                            "method": "content-pack-manifest",
                            "manifest": str(ctflab_dist.manifest_path(pack_dir)),
                            "verified_at": now_iso(),
                        },
                    }
                    if nvram_target is not None:
                        updates["uefi_vars_path"] = str(nvram_target)
                        updates["uefi_vars_sha256"] = sha256_file(nvram_target)
                    claims: dict[str, Any] = {}
                    if isinstance(claims_manifest.get(profile_id), dict):
                        claims["manifest"] = claims_manifest[profile_id]
                    if isinstance(item["data"].get("verification"), dict):
                        claims["profile"] = item["data"]["verification"]
                    if claims:
                        # 仅声明：来源与范围照抄包内数据，接收方本机验收状态不受影响。
                        updates["claims_from_pack"] = claims
                    self._apply_state_updates(profile_id, state, updates)

                record = {
                    "schema": 1,
                    "pack": {"id": pack_id, "name": parsed["name"], "version": parsed["version"],
                             "requires_runner": parsed["requires_runner"]},
                    "manifest_sha256": manifest_sha256,
                    "installed_at": now_iso(),
                    "installed_profiles": installed_profiles,
                    "skipped_identical_profiles": skipped_profiles,
                    "imported_profiles": completed_imports,
                    "docs": docs_copied,
                    "claims": claims_manifest,
                    "imported_from": str(pack_dir),
                }
                self.content_packs_dir.mkdir(parents=True, exist_ok=True)
                write_json(record_path, record)
            except Exception as exc:
                # 回滚本轮明确创建、且不属于已提交节点的文件；既有包记录永不删除。
                for path, _owner in created_files:
                    path.unlink(missing_ok=True)
                if docs_dir_created and not any(docs_dir.iterdir()):
                    docs_dir.rmdir()
                if not record_existed and record_path.exists():
                    record_path.unlink()
                if isinstance(exc, CTFLabError):
                    detail = str(exc)
                    kept = sorted(committed)
                    summary = f"已完成并保留的节点：{', '.join(kept)}" if kept \
                        else "本轮没有已提交的节点；新装配置已回滚"
                    raise CTFLabError(f"{detail}\n{summary}；原内容包未被修改，可修复后重试。") from exc
                raise
            return {
                "pack": report.get("pack"),
                "installed": installed_profiles,
                "skipped_identical": skipped_profiles,
                "imported": completed_imports,
                "docs": docs_copied,
                "record": str(record_path),
            }

    def pack_records(self) -> list[dict[str, Any]]:
        """状态目录中已安装内容包的登记（按安装时间排序）。"""
        records: list[dict[str, Any]] = []
        if not self.content_packs_dir.is_dir():
            return records
        for path in sorted(self.content_packs_dir.glob("*/pack.json")):
            data = read_json(path)
            if isinstance(data, dict):
                records.append(data)
        return records

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
        # 绑定后把监听 FD 交给子进程；避免“先检查再绑定”的跨状态竞争，
        # 也绝不连接或结束其它状态/程序已经占用的交换机。
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        candidates = [lab_port] + [port for port in range(23400, 23500) if port != lab_port]
        for port in candidates:
            try:
                listener.bind(("127.0.0.1", port))
                listener.listen(8)
                lab_port = port
                break
            except OSError as exc:
                if exc.errno not in {48, 98}:  # macOS/Linux EADDRINUSE
                    listener.close()
                    raise CTFLabError(f"无法绑定实验网回环端口：{exc}") from exc
        else:
            listener.close()
            raise CTFLabError("没有可用的实验网回环端口；未操作其他实例。")
        state_path = self.network_state_path(lab_port)
        command = [sys.executable, str(NETWORK_SCRIPT), "--port", str(lab_port), "--state", str(state_path)]
        command += ["--listener-fd", str(listener.fileno())]
        command += ["--max-frames-per-second", str(max_frames_per_second)]
        if pcap_path:
            command += ["--pcap", str(pcap_path)]
        for lease in leases:
            command += ["--lease", lease]
        log_path = self.logs_dir / f"network-{lab_port}.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("a", encoding="utf-8")
        except OSError:
            listener.close()
            raise
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
                pass_fds=(listener.fileno(),),
            )
        except OSError as exc:
            log_handle.close()
            raise CTFLabError(f"无法启动实验网交换机/DHCP：{exc}") from exc
        finally:
            log_handle.close()
            listener.close()
        time.sleep(0.2)
        if process.poll() is not None:
            detail = log_path.read_text(encoding="utf-8", errors="replace").strip()
            raise CTFLabError(f"实验网交换机/DHCP 未能启动（退出码 {process.returncode}）。{detail}")
        track_background_process(process)
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
        reap_background_process(pid)

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
        socket_path = self._spice_endpoint_path(profile_id)
        if socket_path.exists() or socket_path.is_symlink():
            if socket_path.is_dir():
                raise CTFLabError(f"SPICE socket 路径被目录占用：{socket_path}")
            socket_path.unlink()
        return socket_path

    def _spice_endpoint_path(self, profile_id: str) -> Path:
        """计算实际端点；登记和连接时不能调用会清理 socket 的准备方法。"""
        return self._unix_socket_path(profile_id, "display.sock",
                                      self.runtime_dir / profile_id / "spice" / "display.sock")

    def _unix_socket_path(self, profile_id: str, name: str, preferred: Path) -> Path:
        """长路径只将 socket 放到当前用户的私有短目录，磁盘仍留在原状态目录。"""
        if len(os.fsencode(preferred)) < 100:
            return preferred
        identity = hashlib.sha256((str(self.state_dir.resolve()) + "\0" + profile_id).encode()).hexdigest()[:24]
        root = Path("/tmp") / f"ctflab-sockets-{os.getuid()}"
        directory = root / identity
        for path in (root, directory):
            path.mkdir(mode=0o700, exist_ok=True)
            info = path.lstat()
            if path.is_symlink() or not path.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise CTFLabError(f"短 socket 目录不是当前用户私有目录：{path}")
        return directory / name

    def _qmp_socket(self, profile_id: str) -> Path:
        return self._unix_socket_path(profile_id, "qmp.sock", self.runtime_dir / profile_id / "qmp.sock")

    def _spice_ticket(self, profile_id: str) -> Path:
        """写入本次运行的 SPICE ticket 并返回 0600 ticket 文件路径。

        ticket 只落在 0700 runtime 目录内的文件里，通过 QEMU ``password-secret``
        读取；命令行参数与运行状态中只出现文件路径，不出现 ticket 明文。
        """
        directory = self.runtime_dir / profile_id / "spice"
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        ticket_path = directory / "ticket"
        # QEMU 以 format=raw 整文件读取 ticket；不得带换行，否则与客户端裁剪后的值不一致
        ticket_path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        os.chmod(ticket_path, 0o600)
        return ticket_path

    @staticmethod
    def _reserve_loopback_port() -> int:
        """预留一个 127.0.0.1 回环端口供本次 SPICE TCP 监听使用。"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def qemu_command(self, profile_id: str, profile: dict[str, Any], overlay: Path, lab_port: int,
                     headless: bool, allow_internet: bool = False, clipboard: bool = False,
                     display: str = "cocoa", spice_listen: str = "unix",
                     spice_port: int | None = None,
                     file_transfer: bool = False) -> tuple[list[str], dict[str, int]]:
        if display not in {"cocoa", "spice"}:
            raise CTFLabError(f"不支持的显示后端：{display}（可选 cocoa 或 spice）。")
        if spice_listen not in {"unix", "tcp"}:
            raise CTFLabError(f"不支持的 SPICE 监听方式：{spice_listen}（可选 unix 或 tcp）。")
        if spice_listen == "tcp" and display != "spice":
            raise CTFLabError("--spice-listen tcp 只能与 --display spice 同时使用。")
        if display == "spice" and (profile_id != "kali-arm64" or headless):
            raise CTFLabError("SPICE 动态分辨率仅支持 Kali 图形模式。")
        if file_transfer and (profile_id != "kali-arm64" or headless or display != "spice"):
            raise CTFLabError("文件传输仅支持 Kali 的 SPICE 图形窗口。")
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
        spice_ticket: Path | None = None
        if display == "spice":
            capabilities = self.probe_spice(qemu)
            if not capabilities.get("supported"):
                raise self.spice_capability_error(capabilities)
            if spice_listen == "tcp":
                spice_ticket = self._spice_ticket(profile_id)
            else:
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
            # UNIX socket + 0700 runtime 目录是本机鉴权边界；TCP 回退模式只绑定
            # 127.0.0.1 的受控端口，并用每次运行重新生成的 ticket 文件鉴权
            # （QEMU password-secret 从 0600 文件读取，ticket 不进命令行与状态）。
            # SPICE agent transport 始终存在，剪贴板只由显式开关控制。
            copy_paste = "off" if clipboard else "on"
            # 文件传输独立授权；文本剪贴板不会隐式开启文件写入。
            file_xfer = "off" if file_transfer else "on"
            command += ["-display", "none"]
            if spice_listen == "tcp":
                command += [
                    "-spice", f"addr=127.0.0.1,port={spice_port},disable-ticketing=off,disable-copy-paste={copy_paste},disable-agent-file-xfer={file_xfer},agent-mouse=off,password-secret=ctflab_spice_ticket",
                    "-object", f"secret,id=ctflab_spice_ticket,file={spice_ticket},format=raw",
                ]
            else:
                # 与最小能力探测保持同一套 QEMU 11.x 参数格式。
                command += [
                    "-spice", f"unix=on,addr={spice_socket},disable-ticketing=on,disable-copy-paste={copy_paste},disable-agent-file-xfer={file_xfer},agent-mouse=off",
                ]
            command += [
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
        qmp_path = self._qmp_socket(profile_id)
        if qmp_path.exists():
            qmp_path.unlink()
        command += ["-qmp", f"unix:{qmp_path},server=on,wait=off"]
        return command, host_forwards

    def run(self, profile_ids: list[str], headless: bool = False, pcap: bool = False,
            allow_internet: bool = False, clipboard: bool = False,
            display: str = "auto", spice_listen: str = "unix",
            profile_overrides: dict[str, dict[str, Any]] | None = None,
            display_quality: str | None = None,
            file_transfer: bool = False) -> list[dict[str, Any]]:
        with self.operation_lock("启动 " + ",".join(profile_ids)):
            return self._run_unlocked(profile_ids, headless=headless, pcap=pcap,
                                      allow_internet=allow_internet, clipboard=clipboard,
                                      display=display, spice_listen=spice_listen,
                                      profile_overrides=profile_overrides,
                                      display_quality=display_quality, file_transfer=file_transfer)

    def _run_unlocked(self, profile_ids: list[str], headless: bool = False, pcap: bool = False,
                      allow_internet: bool = False, clipboard: bool = False,
                      display: str = "auto", spice_listen: str = "unix",
                      profile_overrides: dict[str, dict[str, Any]] | None = None,
                      display_quality: str | None = None,
                      file_transfer: bool = False) -> list[dict[str, Any]]:
        # 启动前资源预检（第 7 项）：内存超配拒绝；顺序启动即启动队列。
        running_for_preflight = self.running_states()
        for warning in check_host_resources(
                profile_ids,
                [state["profile_id"] for state in running_for_preflight],
                self.state_dir, profile_overrides=profile_overrides,
                running_memory={state["profile_id"]: state.get("memory_mb")
                                for state in running_for_preflight}):
            print(f"资源预检警告：{warning}")
        profile_overrides = profile_overrides or {}
        profile_ids = list(dict.fromkeys(PROFILE_ALIASES.get(profile_id, profile_id) for profile_id in profile_ids))
        if display not in {"auto", "cocoa", "spice"}:
            raise CTFLabError(f"不支持的显示后端：{display}（可选 auto、cocoa 或 spice）。")
        if spice_listen not in {"unix", "tcp"}:
            raise CTFLabError(f"不支持的 SPICE 监听方式：{spice_listen}（可选 unix 或 tcp）。")
        if spice_listen == "tcp" and display != "spice":
            raise CTFLabError("--spice-listen tcp 只能与 --display spice 同时使用。")
        if display == "spice" and profile_ids != ["kali-arm64"]:
            raise CTFLabError("--display spice 只能单独启动 kali-arm64。")
        if display == "spice" and headless:
            raise CTFLabError("--display spice 不能与 --headless 同时使用。")
        if clipboard and (headless or "kali-arm64" not in profile_ids):
            raise CTFLabError("--clipboard 需要启动 Kali 图形窗口。")
        if file_transfer and (headless or profile_ids != ["kali-arm64"] or display == "cocoa"):
            raise CTFLabError("--file-transfer 仅支持单独启动 Kali 的 SPICE 图形窗口。")
        if allow_internet and "kali-arm64" not in profile_ids:
            raise CTFLabError("只有 Kali 可以联网；Smoke 和 Basic Pentesting 2 始终保持隔离。")
        auto_capabilities: dict[str, Any] | None = None
        if display == "auto" and "kali-arm64" in profile_ids and not headless:
            qemu = which_any(QEMU_ARM_NAMES)
            if qemu:
                auto_capabilities = self.probe_spice(qemu)
        auto_spice_supported = bool(auto_capabilities and auto_capabilities.get("supported"))
        displays = {
            profile_id: resolve_display_backend(
                profile_id, display, headless=headless,
                spice_supported=auto_spice_supported,
            )
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
        if file_transfer and displays.get("kali-arm64") != "spice":
            raise CTFLabError("文件传输需要完整 SPICE 能力；不会在 Cocoa 后端静默忽略。")
        for state in running:
            if state["profile_id"] in profile_ids and bool(state.get("file_transfer_enabled")) != file_transfer:
                raise CTFLabError("切换文件传输模式需要先 stop，再 run。")
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
        lab_port = int(network_state.get("port", lab_port))
        started: list[dict[str, Any]] = []
        for profile_id in profile_ids:
            old = self.runtime_state(profile_id)
            if old and bool_pid_alive(int(old.get("pid", 0))):
                started.append(old)
                continue
            profile = profile_overrides.get(profile_id) or load_profile(profile_id)
            overlay = self.ensure_overlay(profile_id)
            spice_tcp = displays[profile_id] == "spice" and spice_listen == "tcp"
            spice_tcp_port = self._reserve_loopback_port() if spice_tcp else None
            command, host_forwards = self.qemu_command(
                profile_id, profile, overlay, lab_port, headless,
                # Kali 的管理网默认使用 user-mode NAT；脆弱靶机的管理网仍为
                # restrict=on，实验网只经本地交换机互通。
                allow_internet=profile_id == "kali-arm64",
                clipboard=clipboard and profile_id == "kali-arm64",
                display=displays[profile_id],
                spice_listen=spice_listen,
                spice_port=spice_tcp_port,
                file_transfer=file_transfer,
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
            track_background_process(process)
            state = {
                "schema": 1,
                "profile_id": profile_id,
                "pid": process.pid,
                "memory_mb": profile.get("guest", {}).get("memory_mb"),
                "cpus": profile.get("guest", {}).get("cpus"),
                "command": command,
                "overlay_path": str(overlay),
                "qmp_path": str(self._qmp_socket(profile_id)),
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
                "file_transfer_enabled": file_transfer and profile_id == "kali-arm64",
                "display_backend": displays[profile_id],
                "display_requested": display,
                "display_quality": display_quality,
                "display_auto_fallback": (
                    display == "auto" and profile_id == "kali-arm64"
                    and not headless and displays[profile_id] == "cocoa"
                ),
                "spice_endpoint": (
                    f"spice://127.0.0.1:{spice_tcp_port}" if spice_tcp
                    else str(self._spice_endpoint_path(profile_id))
                ) if displays[profile_id] == "spice" else None,
                "spice_listen": spice_listen if displays[profile_id] == "spice" else None,
            }
            write_json(self.runtime_state_path(profile_id), state)
            if displays[profile_id] == "spice":
                # QEMU 先建立监听端点，再启动受控客户端；客户端只接收运行器生成的
                # URI，不接受用户拼接的 QEMU/网络参数。TCP 回退模式轮询 127.0.0.1
                # 受控端口可连接为止，ticket 通过 0600 文件交给客户端。
                endpoint_text = str(state["spice_endpoint"])
                spice_tcp = endpoint_text.startswith("spice://")
                endpoint = Path(endpoint_text) if not spice_tcp else None
                ticket_path = Path(self.runtime_dir / profile_id / "spice" / "ticket") if spice_tcp else None
                deadline = time.monotonic() + 5.0
                if spice_tcp:
                    port = int(endpoint_text.rsplit(":", 1)[1])
                    endpoint_ready = False
                    while time.monotonic() < deadline and bool_pid_alive(process.pid):
                        try:
                            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                                endpoint_ready = True
                                break
                        except OSError:
                            time.sleep(0.05)
                else:
                    while not endpoint.exists() and bool_pid_alive(process.pid) and time.monotonic() < deadline:
                        time.sleep(0.05)
                    endpoint_ready = endpoint.exists()
                client = spice_client_path()
                if not endpoint_ready or not client:
                    self._stop_unlocked([profile_id])
                    reason = "SPICE 端点未建立" if not endpoint_ready else "本地 SPICE 客户端不可用"
                    raise CTFLabError(f"{reason}；已清理本次 QEMU 启动，不会自动回退 Cocoa。")
                # 客户端把窗口尺寸/全屏状态记忆在节点自己的运行目录，下次启动恢复。
                client_window_state = Path(self.runtime_dir / profile_id / "spice" /
                                           "client-window.txt")
                client_window_state.parent.mkdir(parents=True, exist_ok=True)
                client_command = spice_client_command(client, endpoint_text, clipboard,
                                                      qemu_pid=process.pid,
                                                      password_file=ticket_path,
                                                      state_file=client_window_state,
                                                      display_quality=display_quality,
                                                      file_transfer=file_transfer)
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
                track_background_process(client_process)
                state["spice_client_log_path"] = str(client_log)
                write_json(self.runtime_state_path(profile_id), state)
            started.append(state)
        return started

    def show_display(self, profile_id: str, reconnect: bool = False) -> dict[str, Any]:
        """复用运行中节点或重连 SPICE，只恢复显示，不重启 QEMU。"""
        with self.operation_lock(f"恢复显示 {profile_id}"):
            profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
            state = self.runtime_state(profile_id)
            if not state or not bool_pid_alive(int(state.get("pid", 0))):
                raise CTFLabError("该节点已停止，请从面板启动；关闭 Cocoa 窗口可能同时停止虚拟机。")
            if state.get("headless"):
                raise CTFLabError("该节点以无界面模式启动；请停止后以图形模式启动。")
            if state.get("display_backend", "cocoa") != "spice":
                if reconnect:
                    raise CTFLabError("Cocoa 显示不支持独立重连；虚拟机保持运行，不会通过重启代替恢复。")
                return {"profile": profile_id, "pid": state["pid"], "reconnected": False}
            client_pid = int(state.get("spice_client_pid", 0) or 0)
            if bool_pid_alive(client_pid) and not reconnect:
                return {"profile": profile_id, "pid": client_pid, "reconnected": False}
            client = spice_client_path()
            if not client:
                raise CTFLabError("缺少受控 SPICE 客户端，不能恢复显示。")
            directory = self.runtime_dir / profile_id / "spice"
            if state.get("spice_listen") == "tcp":
                ticket = directory / "ticket"
                if not ticket.is_file():
                    raise CTFLabError("缺少本次运行 ticket，不能恢复显示。")
                endpoint = str(state["spice_endpoint"])
            else:
                ticket = None
                endpoint = str(state.get("spice_endpoint") or self._spice_endpoint_path(profile_id))
                if not Path(endpoint).is_socket():
                    raise CTFLabError("运行中节点的 SPICE socket 不存在；请查看诊断，不会重启节点。")
            # 显式恢复用于进程仍存活但窗口不绘制；先核验恢复前提，再只断开客户端。
            # 不自动用黑屏判定卡死，避免把锁屏/息屏误判为故障。
            if reconnect and bool_pid_alive(client_pid):
                terminate_spice_client(client_pid)
            command = spice_client_command(client, endpoint,
                                           clipboard=bool(state.get("clipboard_enabled")),
                                           qemu_pid=int(state["pid"]), password_file=ticket,
                                           state_file=directory / "client-window.txt",
                                           display_quality=state.get("display_quality"),
                                           file_transfer=bool(state.get("file_transfer_enabled")))
            # 重连使用新日志，避免前一会话 display-ready 标记被误读为本次就绪。
            log = self.logs_dir / f"{profile_id}-spice-client-{uuid.uuid4().hex[:12]}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            try:
                with log.open("a", encoding="utf-8") as handle:
                    process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                               stdout=handle, stderr=subprocess.STDOUT,
                                               start_new_session=True, text=True)
            except OSError as exc:
                raise CTFLabError(f"恢复显示失败，虚拟机保持运行：{exc}") from exc
            state["spice_client_pid"] = process.pid
            track_background_process(process)
            state["spice_client_log_path"] = str(log)
            write_json(self.runtime_state_path(profile_id), state)
            return {"profile": profile_id, "pid": process.pid, "reconnected": True}

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
            client_pid = int(state.get("spice_client_pid", 0) or 0)
            if bool_pid_alive(pid):
                if client_pid:
                    # 先断开显示客户端再请求任何关机：来宾响应 ACPI 的干净退出
                    # 与 QMP quit 一样会触发 spice-server 的 RedClient 销毁段错误
                    # （2026-10-05 崩溃报告实证优雅/强制两条路径都命中）。来宾
                    # 关机可快于任何固定等待，不能靠延时规避；窗口随停止关闭。
                    terminate_spice_client(client_pid)
                    reap_background_process(client_pid)
                    client_pid = 0
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
            if client_pid and bool_pid_alive(client_pid):
                # 优雅停止路径：QEMU 退出后客户端通常经 qemu-pid 监控自行退出，
                # 残留时在此有界回收。
                terminate_spice_client(client_pid)
            if client_pid:
                reap_background_process(client_pid)
            if qmp_path.exists():
                qmp_path.unlink()
            spice_endpoint = Path(str(state.get("spice_endpoint", "")))
            if spice_endpoint.is_socket() or spice_endpoint.is_file() or spice_endpoint.is_symlink():
                spice_endpoint.unlink()
            state_path = self.runtime_state_path(profile_id)
            if state_path.exists():
                state_path.unlink()
            reap_background_process(pid)
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

    def reset(self, profile_id: str, force: bool = False, backup_name: str | None = None) -> None:
        with self.operation_lock(f"重置 {profile_id}"):
            profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
            state = self.runtime_state(profile_id)
            if state and bool_pid_alive(int(state.get("pid", 0))):
                if not force:
                    raise CTFLabError(f"{profile_id} 正在运行，请先 stop，或使用 reset --force。")
                self.stop([profile_id])
            instance_dir = self.runtime_dir / profile_id
            if backup_name is not None:
                # 重置前备份：把整个 overlay 与 NVRAM 移入 state 目录下的备份区，
                # 重置的 rmtree 不会触及；恢复用 snapshot restore-backup。
                self._backup_instance(profile_id, instance_dir, backup_name)
            if instance_dir.exists():
                shutil.rmtree(instance_dir)

    def remove_image(self, profile_id: str) -> None:
        """删除已导入的镜像数据：基盘副本、导入登记与 NVRAM 模板一并移除。

        原始来源镜像（用户的下载/分发目录）与整盘备份区不受影响；内置课程
        profile 保留登记（回到“未导入”），用户登记的 yaml 由调用方按需移除。
        """
        with self.operation_lock(f"删除镜像 {profile_id}"):
            profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
            state = self.runtime_state(profile_id)
            if state and bool_pid_alive(int(state.get("pid", 0))):
                raise CTFLabError(f"{profile_id} 正在运行，请先 stop 再删除镜像。")
            image_dir = self.images_dir / profile_id
            if not (image_dir / "image.json").exists():
                raise CTFLabError(f"{profile_id} 没有已导入的镜像数据（images 目录为空）。")
            backup_root = self._backup_root(profile_id)
            if backup_root.exists() and any(backup_root.iterdir()):
                raise CTFLabError(f"{profile_id} 仍有整盘备份依赖基础镜像；请先恢复并处理备份，不能删除基础盘。")
            instance_dir = self.runtime_dir / profile_id
            if instance_dir.exists():
                shutil.rmtree(instance_dir)
            shutil.rmtree(image_dir)

    SNAPSHOT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}$")
    BACKUP_DIR_NAME = "backups"

    def _require_stopped(self, profile_id: str, action: str) -> None:
        state = self.runtime_state(profile_id)
        if state and bool_pid_alive(int(state.get("pid", 0))):
            raise CTFLabError(f"{profile_id} 正在运行；{action} 只作用于已停止的节点，"
                              f"请先执行 stop。")

    def _instance_files(self, profile_id: str) -> tuple[Path, Path | None]:
        overlay = self.runtime_dir / profile_id / "overlay.qcow2"
        if not overlay.exists():
            raise CTFLabError(f"{profile_id} 没有可操作的 overlay（尚未导入或从未运行）。")
        nvram = self.runtime_dir / profile_id / "uefi-vars.fd"
        return overlay, (nvram if nvram.exists() else None)

    def _backup_root(self, profile_id: str) -> Path:
        return self.state_dir / self.BACKUP_DIR_NAME / profile_id

    def _backup_instance(self, profile_id: str, instance_dir: Path, backup_name: str) -> Path:
        """把当前实例盘整份移入备份区（rename，不复制大文件）。"""
        self._validate_snapshot_name(backup_name, "备份名")
        destination = self._backup_root(profile_id) / backup_name
        if destination.exists():
            raise CTFLabError(f"备份 {backup_name} 已存在：{destination}")
        if not instance_dir.exists():
            raise CTFLabError(f"{profile_id} 没有可备份的实例目录。")
        self._instance_files(profile_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # 整个目录一次移动，保留内部快照对应的 NVRAM、overlay 登记和显示偏好。
        # 同卷 rename 失败时原目录不变，不会留下只移动了一半的备份。
        os.rename(instance_dir, destination)
        return destination

    def _validate_snapshot_name(self, name: str, label: str) -> str:
        if not self.SNAPSHOT_NAME_PATTERN.fullmatch(name):
            raise CTFLabError(
                f"{label}不合法：{name!r}（小写字母/数字开头，仅含小写字母、数字、"
                "._-，长度 1-32；空格与中文会破坏 qemu-img 列表解析）。")
        return name

    def snapshot_create(self, profile_id: str, name: str) -> dict[str, Any]:
        """对节点 overlay 建命名内部快照；基础镜像只读不受影响。

        快照成对保存 NVRAM 副本（存在时），revert 一并恢复；两者都存放在
        runtime/<node>/ 内，reset 会连同丢弃（重置前要保留请用 --backup）。
        """
        with self.operation_lock(f"创建快照 {profile_id}:{name}"):
            profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
            name = self._validate_snapshot_name(name, "快照名")
            self._require_stopped(profile_id, "创建快照")
            overlay, nvram = self._instance_files(profile_id)
            existing = {item["tag"] for item in self._qemu_snapshots(overlay)}
            if name in existing:
                raise CTFLabError(f"快照 {name} 已存在。")
            nvram_pair = None
            if nvram:
                nvram_pair = nvram.with_name(f"uefi-vars.fd.snapshot-{name}")
                if nvram_pair.exists():
                    raise CTFLabError(f"快照 {name} 已有固件副本；请先检查残留文件。")
                shutil.copy2(nvram, nvram_pair)
            try:
                run_command([qemu_img_path(), "snapshot", "-c", name, str(overlay)])
            except Exception:
                if nvram_pair is not None:
                    nvram_pair.unlink(missing_ok=True)
                raise
            return {"profile": profile_id, "tag": name,
                    "nvram_paired": nvram_pair is not None}

    def _qemu_snapshots(self, overlay: Path) -> list[dict[str, Any]]:
        result = run_command([qemu_img_path(), "snapshot", "-l", str(overlay)],
                             capture=True)
        snapshots: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            fields = line.split()
            # 固定表头两行与本方命名规则（无空格）下按列解析即足够；无法解析的
            # 行（外来空格名快照）跳过而不是崩溃，list 会如实少列。
            if len(fields) < 3 or not fields[0].isdigit():
                continue
            date_index = next((index for index, field in enumerate(fields[2:], 2)
                               if re.fullmatch(r"\d{4}-\d{2}-\d{2}", field)), None)
            if date_index is None:
                continue
            snapshots.append({"id": fields[0], "tag": fields[1],
                              "vm_size": " ".join(fields[2:date_index]),
                              "date": " ".join(fields[date_index:date_index + 2])})
        return snapshots

    def snapshot_list(self, profile_id: str) -> list[dict[str, Any]]:
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        overlay, _ = self._instance_files(profile_id)
        return self._qemu_snapshots(overlay)

    def snapshot_revert(self, profile_id: str, name: str) -> dict[str, Any]:
        with self.operation_lock(f"恢复快照 {profile_id}:{name}"):
            profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
            name = self._validate_snapshot_name(name, "快照名")
            self._require_stopped(profile_id, "恢复快照")
            overlay, nvram = self._instance_files(profile_id)
            if name not in {item["tag"] for item in self._qemu_snapshots(overlay)}:
                raise CTFLabError(f"快照 {name} 不存在。")
            pair = overlay.parent / f"uefi-vars.fd.snapshot-{name}"
            if nvram is not None and not pair.is_file():
                raise CTFLabError(f"快照 {name} 缺少配对 NVRAM；磁盘未恢复。请使用完整备份。")
            run_command([qemu_img_path(), "snapshot", "-a", name, str(overlay)])
            nvram_restored = False
            if pair.is_file():
                shutil.copy2(pair, overlay.parent / "uefi-vars.fd")
                nvram_restored = True
            return {"profile": profile_id, "reverted": name,
                    "nvram_restored": nvram_restored}

    def snapshot_delete(self, profile_id: str, name: str) -> dict[str, Any]:
        with self.operation_lock(f"删除快照 {profile_id}:{name}"):
            profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
            name = self._validate_snapshot_name(name, "快照名")
            self._require_stopped(profile_id, "删除快照")
            overlay, nvram = self._instance_files(profile_id)
            if name not in {item["tag"] for item in self._qemu_snapshots(overlay)}:
                raise CTFLabError(f"快照 {name} 不存在。")
            run_command([qemu_img_path(), "snapshot", "-d", name, str(overlay)])
            if nvram:
                nvram.with_name(f"uefi-vars.fd.snapshot-{name}").unlink(missing_ok=True)
            return {"profile": profile_id, "deleted": name}

    def backups_list(self, profile_id: str) -> list[dict[str, Any]]:
        root = self._backup_root(PROFILE_ALIASES.get(profile_id, profile_id))
        if not root.is_dir():
            return []
        result = []
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            overlay = entry / "overlay.qcow2"
            size = overlay.stat().st_size if overlay.exists() else None
            result.append({"name": entry.name, "overlay_bytes": size,
                           "complete": overlay.exists()})
        return result

    def backup_restore(self, profile_id: str, name: str) -> dict[str, Any]:
        """把整盘备份恢复为当前实例（当前实例盘被覆盖，操作前应已另有备份）。"""
        with self.operation_lock(f"恢复备份 {profile_id}:{name}"):
            profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
            self._validate_snapshot_name(name, "备份名")
            self._require_stopped(profile_id, "恢复备份")
            source = self._backup_root(profile_id) / name
            overlay_source = source / "overlay.qcow2"
            if not overlay_source.exists():
                raise CTFLabError(f"备份 {name} 不完整：{source}")
            info = qemu_info(overlay_source)
            backing = info.get("full-backing-filename") or info.get("backing-filename")
            if backing and not Path(str(backing)).is_file():
                raise CTFLabError("备份依赖的基础盘不存在；未修改当前实例或备份。")
            instance_dir = self.runtime_dir / profile_id
            previous = None
            if instance_dir.exists():
                previous = self._backup_root(profile_id) / ("before-restore-" + uuid.uuid4().hex[:12])
                os.rename(instance_dir, previous)
            try:
                # 备份不继承历史 PID/socket，避免恢复后误操作其它进程。
                (source / "run.json").unlink(missing_ok=True)
                (source / "qmp.sock").unlink(missing_ok=True)
                os.rename(source, instance_dir)
            except OSError:
                if previous is not None:
                    os.rename(previous, instance_dir)
                raise
            return {"profile": profile_id, "restored_backup": name,
                    "previous_backup": previous.name if previous else None}

    def backup_delete(self, profile_id: str, name: str) -> None:
        """明确删除指定备份，不隐式删除当前实例或基础盘。"""
        with self.operation_lock(f"删除备份 {profile_id}:{name}"):
            profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
            self._validate_snapshot_name(name, "备份名")
            self._require_stopped(profile_id, "删除备份")
            source = self._backup_root(profile_id) / name
            if not source.is_dir() or source.is_symlink():
                raise CTFLabError(f"备份 {name} 不存在或不是受控目录。")
            shutil.rmtree(source)

    def storage_report(self) -> dict[str, Any]:
        """各节点磁盘占用、backing chain 与引用关系；只读，不做任何清理。

        对应路线图第 10 项的“清理前建立磁盘引用关系”：运行中的节点 base
        标记 referenced，缺失 backing 的 overlay 标记 broken，供人工决策。
        """
        running = {state["profile_id"] for state in self.running_states()}
        profiles: list[dict[str, Any]] = []
        for profile_id in available_profiles():
            image = self.image_state(profile_id) or {}
            base_path = Path(str(image.get("base_path") or ""))
            entry: dict[str, Any] = {
                "id": profile_id,
                "imported": bool(image) and base_path.is_file(),
                "running": profile_id in running,
            }
            if image:
                if base_path.is_file():
                    info = qemu_info(base_path, force_share=True)
                    entry["base"] = {
                        "path": str(base_path),
                        "actual_bytes": base_path.stat().st_size,
                        "virtual_bytes": info.get("virtual-size"),
                    }
                    entry["base_referenced"] = profile_id in running
                else:
                    entry["base"] = None
                    entry["base_referenced"] = False
            overlay = self.runtime_dir / profile_id / "overlay.qcow2"
            if overlay.exists():
                info = qemu_info(overlay, force_share=True)
                backing = info.get("full-backing-filename") or info.get("backing-filename")
                backing_ok = bool(backing) and Path(str(backing)).is_file()
                entry["overlay"] = {
                    "path": str(overlay),
                    "actual_bytes": overlay.stat().st_size,
                    "virtual_bytes": info.get("virtual-size"),
                    "backing_path": backing,
                    "backing_ok": backing_ok,
                }
                entry["snapshots"] = self._qemu_snapshots(overlay) \
                    if profile_id not in running else self.snapshot_list(profile_id)
            else:
                entry["overlay"] = None
                entry["snapshots"] = []
            entry["backups"] = self.backups_list(profile_id)
            profiles.append(entry)
        return {"schema": 1, "state_dir": str(self.state_dir), "profiles": profiles}

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
                    # 实例运行时可能使用临时/自选端口，不能检查配置中的旧端口。
                    # 有运行映射但缺少该项时不回退，避免误探测另一台实例。
                    label = str(forward.get("name", guest_port))
                    if "host_forwards" in state:
                        actual = state["host_forwards"].get(label)
                        host_port = int(actual) if actual is not None else None
                    else:
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
                try:
                    url = http_probe_url(host_port, check.get("path", "/"))
                except CTFLabError as exc:
                    results.append({"name": f"http:{guest_port}", "ok": False, "detail": str(exc)})
                    continue
                try:
                    # 不跟随重定向：重定向可能把探测带离授权的回环目标。
                    opener = urllib.request.build_opener(_LoopbackRedirectBlocker())
                    with opener.open(url, timeout=2.0) as response:
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
                if expected_protocols and protocol_ready:
                    break
                if display.get("active") and ppm_path.exists():
                    # 矩阵探测：识别到 UEFI Shell/无启动盘/PXE 网络启动/内核错误就提前结束，
                    # 尝试下一个候选。
                    screen = classify_screenshot(ppm_path)
                    if abort_on_failure_screen and screen.get("classification") in SCREEN_FAILURE_CLASSES:
                        early_failure = str(screen.get("classification"))
                        break
                    # DHCP 可能来自固件 PXE；非黑画面或 unknown OCR 不能让矩阵提前命中。
                    if not expected_protocols and network_ready and screen.get("classification") == "login_ready":
                        break
                time.sleep(2)

            process_running = bool_pid_alive(int((self.runtime_state(profile_id) or {}).get("pid", 0)))
            network_ready = any(item["name"] == "dhcp" and item["ok"] is True for item in health)
            protocol_ready = any(
                item["ok"] is True and item["name"].split(":", 1)[0] in expected_protocols
                for item in health
            )
            verdict = probe_verdict(
                protocol_ready=protocol_ready,
                network_ready=network_ready,
                display_active=bool(display.get("active")),
                process_running=process_running,
            )

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
                verdict = probe_verdict(
                    protocol_ready=protocol_ready,
                    network_ready=network_ready,
                    display_active=bool(display.get("active")),
                    process_running=process_running,
                    screen_classification=str(screen["classification"]),
                )

            candidate_profile = profile.get("detection", {}).get("status") == "candidate"
            recommendations = probe_recommendations(str(screen.get("classification")))
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
                "recommendations": recommendations,
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
        with self.operation_lock(f"启动回退 {profile_id}"):
            return self._boot_matrix_unlocked(profile_id, per_candidate_timeout=per_candidate_timeout,
                                              max_candidates=max_candidates, start_at=start_at)

    def _boot_matrix_unlocked(self, profile_id: str, *, per_candidate_timeout: int = 90,
                              max_candidates: int | None = None, start_at: int = 1) -> dict[str, Any]:
        """受控启动回退矩阵：按白名单顺序尝试固件/磁盘组合，用画面分类决定是否继续。

        候选只作用于本次启动（不写入 profile）；识别到 UEFI Shell、无启动盘、PXE
        网络启动或内核错误就立即换下一个候选，命中协议级就绪或登录界面即停止。
        """
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        running = self.runtime_state(profile_id)
        if running and bool_pid_alive(int(running.get("pid", 0))):
            raise CTFLabError("该节点正在运行；拒绝用当前实例冒充回退候选，也不会自动停止它。")
        instance_dir = self.runtime_dir / profile_id
        if instance_dir.exists():
            raise CTFLabError("该节点已有运行盘或 NVRAM；为保护改动，拒绝用它做启动矩阵。请先人工备份并重置，或以新配置导入。")
        base = load_profile(profile_id)
        initial_profile_hash = sha256_file(profile_path(profile_id))
        architecture = str(base.get("guest", {}).get("architecture", "x86_64"))
        candidates = ordered_matrix_candidates(base)
        if max_candidates is not None:
            candidates = candidates[: max(1, max_candidates)]
        start_at = max(1, int(start_at))
        candidates = candidates[max(0, start_at - 1):]
        timeout = max(5, min(int(per_candidate_timeout), 1800))
        attempts: list[dict[str, Any]] = []
        selected: dict[str, Any] | None = None
        stopped_reason: dict[str, Any] | None = None
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
                failure = startup_failure(str(exc))
                attempts.append({"candidate": candidate, "label": candidate_label(candidate),
                                 "error": str(exc), "failure": failure})
                print(f"    无法启动：{exc}")
                if not failure["retryable"]:
                    stopped_reason = failure
                    break
                continue
            finally:
                # 入口已确认没有用户运行盘；只清理本矩阵创建的运行目录。
                # 必须先结束本次实例，再删派生 overlay/NVRAM，避免不同候选互相污染。
                if instance_dir.exists():
                    self.stop([profile_id])
                    state = self.runtime_state(profile_id)
                    if state and bool_pid_alive(int(state.get("pid", 0))):
                        raise CTFLabError("回退实例未能停止；保留运行盘和状态，停止后续尝试，请人工检查。")
                    self.reset(profile_id)
            screen = report.get("screen", {})
            verdict = str(report.get("verdict"))
            classification = str(screen.get("classification", "unknown"))
            success = (report.get("process_running_at_verdict") is True
                       and classification not in SCREEN_FAILURE_CLASSES
                       and (verdict in BOOT_MATRIX_SUCCESS_VERDICTS
                            or classification in BOOT_MATRIX_SUCCESS_SCREENS))
            attempt = {
                "candidate": candidate,
                "label": candidate_label(candidate),
                "verdict": verdict,
                "screen": classification,
                "confidence": screen.get("confidence"),
                "early_failure": report.get("early_failure"),
                "process_running_at_verdict": report.get("process_running_at_verdict"),
                "screenshot_path": report.get("screenshot_path"),
                "display_active": report.get("display", {}).get("active") is True,
                "report_path": report.get("report_path"),
                "recommendations": report.get("recommendations", probe_recommendations(classification)),
            }
            attempts.append(attempt)
            screenshot = Path(str(attempt.get("screenshot_path") or ""))
            if screenshot.is_file() and not screenshot.is_symlink():
                attempt["screenshot_sha256"] = sha256_file(screenshot)
            print(f"    结论：{verdict}（画面 {classification}/{screen.get('confidence', 'low')}）")
            if success:
                selected = attempt
                break
            if (classification == "unknown" and attempt["display_active"]
                    and attempt["process_running_at_verdict"] is True
                    and verdict in {"display_activity_only", "network_and_display_candidate"}
                    and attempt.get("screenshot_sha256")):
                # 暂停回退等待人工查看；不把 DHCP/非黑画面自动升级为成功。
                break
        if sha256_file(profile_path(profile_id)) != initial_profile_hash:
            raise CTFLabError("候选配置在矩阵运行期间被修改；拒绝生成可固化报告，请重新探测。")
        result = {
            "schema": 1,
            "profile_id": profile_id,
            "architecture": architecture,
            "timeout_per_candidate": timeout,
            "attempts": attempts,
            "selected": selected,
            "review_attempt": (len(attempts) if selected is None and attempts
                               and attempts[-1].get("screenshot_sha256")
                               and attempts[-1].get("screen") == "unknown"
                               and attempts[-1].get("display_active") is True
                               and attempts[-1].get("process_running_at_verdict") is True
                               and attempts[-1].get("verdict") in {"display_activity_only", "network_and_display_candidate"}
                               else None),
            "succeeded": selected is not None,
            "stopped_reason": stopped_reason,
            "ordering": "source-candidate-first" if base.get("detection", {}).get("status") == "candidate" else "legacy-whitelist",
            "runtime_policy": "fresh-overlay-and-nvram-per-attempt; existing-runtime-refused",
            "profile_sha256": initial_profile_hash,
            "source_sha256": (self.image_state(profile_id) or {}).get("source_sha256"),
            "base_sha256": (self.image_state(profile_id) or {}).get("base_sha256"),
            "note": "候选只作用于本次启动；人工复核后可保存候选硬件参数，完整启动、网络和服务验收仍需另行完成。",
        }
        report_root = self.logs_dir / "probes"
        report_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        matrix_path = report_root / f"{profile_id}-matrix-{stamp}.json"
        write_json(matrix_path, result)
        result["report_path"] = str(matrix_path)
        return result

    def apply_matrix_candidate(self, profile_id: str, report_arg: str, *, confirm: bool,
                               review_attempt: int | None = None) -> dict[str, Any]:
        with self.operation_lock(f"保存回退候选 {profile_id}"):
            try:
                return self._apply_matrix_candidate_unlocked(profile_id, report_arg, confirm=confirm,
                                                              review_attempt=review_attempt)
            except OSError as exc:
                raise CTFLabError(f"无法保存回退候选参数：{exc}；请查看 profile-backups 中的原配置备份。") from exc

    def _apply_matrix_candidate_unlocked(self, profile_id: str, report_arg: str, *, confirm: bool,
                                        review_attempt: int | None = None) -> dict[str, Any]:
        """人工确认后仅固化启动参数；保留 candidate 状态和原配置备份。"""
        if not confirm:
            raise CTFLabError("保存回退参数需要 --confirm-apply；这只固化候选参数，不代表镜像已经验收。")
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        destination = user_profile_dir() / f"{profile_id}.yaml"
        if (profile_id in PROFILE_ALIASES or not destination.is_file() or destination.is_symlink()
                or profile_path(profile_id).resolve() != destination.resolve()):
            raise CTFLabError("只允许保存用户接入的候选配置；内置配置、链接或路径异常均拒绝修改。")
        if self.runtime_state(profile_id) or (self.runtime_dir / profile_id).exists():
            raise CTFLabError("该节点存在运行状态或运行盘；请先正常停止并人工备份/重置，再保存候选参数。")
        report_path = Path(report_arg).expanduser()
        probes_root = (self.logs_dir / "probes").resolve()
        if report_path.is_symlink() or not report_path.is_file():
            raise CTFLabError(f"矩阵报告不存在或是链接：{report_path}")
        report_path = report_path.resolve()
        if not report_path.is_relative_to(probes_root):
            raise CTFLabError("矩阵报告必须来自当前状态目录的 probes；拒绝外部或其他实例报告。")
        report = read_json(report_path) or {}
        selected = report.get("selected")
        manual = review_attempt is not None
        if manual:
            attempts = report.get("attempts", [])
            if (not isinstance(review_attempt, int) or review_attempt < 1 or review_attempt > len(attempts)
                    or report.get("review_attempt") != review_attempt):
                raise CTFLabError("人工复核序号不是报告中的待复核候选。")
            selected = attempts[review_attempt - 1]
            if not isinstance(selected, dict):
                raise CTFLabError("人工复核候选格式不正确。")
            screenshot = Path(str(selected.get("screenshot_path") or ""))
            if (selected.get("screen") != "unknown" or selected.get("display_active") is not True
                    or selected.get("verdict") not in {"display_activity_only", "network_and_display_candidate"}
                    or screenshot.is_symlink() or not screenshot.is_file()
                    or not screenshot.resolve().is_relative_to(probes_root)
                    or sha256_file(screenshot) != selected.get("screenshot_sha256")):
                raise CTFLabError("人工复核截图缺失、失配或该画面不允许保存；未改变候选。")
        candidate = selected.get("candidate") if isinstance(selected, dict) else None
        if (report.get("schema") != 1 or report.get("profile_id") != profile_id
                or (not manual and report.get("succeeded") is not True) or not isinstance(candidate, dict)
                or selected.get("process_running_at_verdict") is not True
                or selected.get("screen") in SCREEN_FAILURE_CLASSES
                or not (manual or selected.get("verdict") in BOOT_MATRIX_SUCCESS_VERDICTS
                        or selected.get("screen") in BOOT_MATRIX_SUCCESS_SCREENS)
                or candidate not in matrix_candidates("x86_64")):
            raise CTFLabError("矩阵报告没有可固化的 x86_64 白名单启动候选，或成功证据不完整。")
        current_bytes = destination.read_bytes()
        current_identity = source_identity(destination)
        if hashlib.sha256(current_bytes).hexdigest() != report.get("profile_sha256"):
            raise CTFLabError("候选配置在矩阵之后已变化；拒绝应用过期报告，请重新运行矩阵。")
        image = self.image_state(profile_id) or {}
        base_path = Path(str(image.get("base_path", "")))
        if (not base_path.is_file() or image.get("source_sha256") != report.get("source_sha256")
                or image.get("base_sha256") != report.get("base_sha256")
                or sha256_file(base_path) != report.get("base_sha256")):
            raise CTFLabError("来源或基础镜像与矩阵报告不一致；拒绝应用过期/失配结果。")
        profile = load_profile(profile_id)
        if (profile.get("guest", {}).get("architecture") != "x86_64"
                or profile.get("detection", {}).get("status") != "candidate"):
            raise CTFLabError("该配置不是用户候选；拒绝改写已验证或未知状态配置。")
        updated = copy.deepcopy(profile)
        updated["guest"]["firmware"] = candidate["firmware"]
        updated["disk"]["bus"] = candidate["bus"]
        if candidate.get("controller"):
            updated["disk"]["controller"] = candidate["controller"]
        else:
            updated["disk"].pop("controller", None)
        updated["detection"]["matrix_applied"] = {
            "report": report_path.name,
            "applied_at": now_iso(),
            "candidate": candidate,
            "verdict": selected.get("verdict"),
            "screen": selected.get("screen"),
            "human_confirmed": True,
            "review_mode": "screenshot-only" if manual else "protocol-or-login",
            "review_attempt": review_attempt,
            "note": "仅固化本次启动候选；boot_verified/service_verified 仍为 false。",
        }
        updated["detection"]["boot_verified"] = False
        updated["detection"]["service_verified"] = False
        validate_profile(updated, destination)
        backup_dir = self.state_dir / "profile-backups" / profile_id
        backup_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = backup_dir / f"pre-matrix-{stamp}.yaml"
        descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(current_bytes)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{profile_id}-matrix-", suffix=".yaml",
                                                       dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(yaml.safe_dump(updated, allow_unicode=True, sort_keys=False))
            if source_identity(destination) != current_identity:
                raise CTFLabError("候选配置在发布前被外部修改；已保留备份，拒绝覆盖。")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return {"profile_id": profile_id, "profile_path": str(destination),
                "backup_path": str(backup), "candidate": candidate,
                "status": "candidate", "verified": False}


def cmd_doctor(manager: LabManager, args: argparse.Namespace) -> int:
    """检查运行依赖；每项缺失都给出可操作的安装提示，必选项缺失时返回 1。"""
    diagnostics_path = getattr(args, "diagnostics", None)
    if diagnostics_path:
        exported = write_diagnostics(manager, Path(diagnostics_path))
        print(f"诊断包已导出：{exported}（0600；不含口令/ticket/剪贴板正文）")
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
        report = inspect_image(args.source, calculate_hash=not args.no_hash,
                               preferred_disk=getattr(args, "disk", None))
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
    if getattr(args, "resume", False):
        destination = user_profile_dir() / f"{profile_id}.yaml"
        report_path = manager.images_dir / profile_id / "detection.json"
        report = read_json(report_path) or {}
        if (args.no_import or profile_id in PROFILE_ALIASES
                or not report.get("source_path") or not isinstance(report.get("candidate"), dict)
                or not destination.is_file() or destination.is_symlink()
                or profile_path(profile_id).resolve() != destination.resolve()
                or manager.image_state(profile_id)
                or Path(str(report.get("source_path", ""))).expanduser().resolve()
                != Path(args.source).expanduser().resolve()
                or report.get("import_disk") != getattr(args, "disk", None)):
            raise CTFLabError("只允许重试本来源、同选盘且尚未登记基盘的用户候选配置；不覆盖既有节点。")
        state = manager.import_image(profile_id, args.source, ova_disk=getattr(args, "disk", None))
        report["source_sha256"] = state["source_sha256"]
        write_json(report_path, report)
        print(f"重试导入完成：{profile_id}；候选仍未启动验证。")
        return 0
    if profile_id in PROFILE_ALIASES or profile_exists(profile_id):
        raise CTFLabError(f"配置 {profile_id} 已存在；为避免覆盖已验证参数，请换一个 id。")
    source = Path(args.source).expanduser()
    if source.is_file() and source.suffix.lower() == ".ova" and not args.no_import:
        try:
            with prepare_ova(source, getattr(args, "disk", None)) as prepared:
                if len(prepared.located[3]) > 1 and getattr(args, "disk", None) is None:
                    raise CTFLabError("OVA 含多磁盘，请先显式选择系统盘；未创建候选配置。")
                return _cmd_onboard_ready(manager, args, prepared)
        except InspectionError as exc:
            raise CTFLabError(str(exc)) from exc
    return _cmd_onboard_ready(manager, args)


def _cmd_onboard_ready(manager: LabManager, args: argparse.Namespace,
                       prepared: PreparedOva | None = None) -> int:
    profile_id = args.id.lower()
    try:
        # 正常接入由正式 import 独立核验来源；只生成候选时仍保留来源摘要。
        report = inspect_image(args.source, calculate_hash=args.no_import,
                               preferred_disk=getattr(args, "disk", None),
                               **({"_prepared_ova": prepared} if prepared is not None else {}))
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
    destination = user_profile_dir() / f"{profile_id}.yaml"
    validate_profile(profile, destination)
    if yaml is None:
        raise CTFLabError("当前 Python 缺少 PyYAML，无法生成配置。")
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    # 临时文件与目标处于同一目录；用硬链接排他发布，避免并发或外部进程覆盖另一份候选配置。
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{profile_id}-", suffix=".yaml", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False))
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise CTFLabError(f"配置 {profile_id} 已存在；为避免覆盖已验证参数，请换一个 id。") from exc
    finally:
        temporary.unlink(missing_ok=True)
    detection_path = manager.images_dir / profile_id / "detection.json"
    report["import_disk"] = getattr(args, "disk", None)
    write_json(detection_path, report)
    print(f"候选配置已生成：{destination}")
    print(f"探测报告：{detection_path}")
    for warning in report.get("warnings", []):
        print(f"警告：{warning}")
    if args.no_import:
        print("已按 --no-import 跳过磁盘导入；候选配置尚未启动验证。")
        return 0
    state = manager.import_image(profile_id, args.source,
                                 ova_disk=getattr(args, "disk", None),
                                 **({"_prepared_ova": prepared} if prepared is not None else {}))
    report["source_sha256"] = state.get("source_sha256")
    write_json(detection_path, report)
    print(f"导入完成：{profile_id}")
    print(f"基础镜像：{state['base_path']}")
    print(f"下一步：./tools/ctflab probe {profile_id}")
    return 0


def cmd_import(manager: LabManager, args: argparse.Namespace) -> int:
    state = manager.import_image(args.profile, args.source,
                                 expect_sha256=args.expect_sha256,
                                 manifest=args.manifest,
                                 nvram=args.nvram,
                                 ova_disk=getattr(args, "disk", None))
    print(f"导入完成：{args.profile}")
    print(f"基础镜像：{state['base_path']}")
    virtual = int(state.get("virtual_size") or 0)
    base_file = Path(str(state["base_path"]))
    actual = base_file.stat().st_size if base_file.exists() else 0
    print(f"占用空间：基盘 {actual / (1024 ** 2):.1f} MiB（虚拟 {virtual / (1024 ** 3):.1f} GiB）；来源格式 {state.get('source_format', '?')}")
    if state.get("ova_disk"):
        print(f"OVA 选盘：{state['ova_disk']}（共 {state.get('ova_disk_count', 1)} 块）")
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
    """复核分发目录：逐文件大小与 SHA-256 与清单一致；内容包附带结构校验与包摘要。"""
    import ctflab_dist  # noqa: PLC0415

    profile_status = None
    if getattr(args, "conflicts", False):
        # 冲突预览只读内置/用户 profile 目录（CTFLAB_PROFILE_DIR 环境变量生效），
        # 不创建状态目录；未指定 --conflicts 时保持输出与旧版完全一致。
        def profile_status(profile_id: str) -> dict[str, Any]:
            builtin = BUILTIN_PROFILE_DIR / f"{profile_id}.yaml"
            if builtin.is_file() and not builtin.is_symlink():
                return {"kind": "builtin", "sha256": sha256_file(builtin)}
            user = user_profile_dir() / f"{profile_id}.yaml"
            if user.is_file() and not user.is_symlink():
                return {"kind": "user", "sha256": sha256_file(user)}
            return {"kind": "absent", "sha256": None}

    try:
        report = ctflab_dist.verify_distribution(args.dir, profile_status=profile_status,
                                                 runner_version=CTFLAB_VERSION)
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
        pack = report.get("pack")
        if pack:
            print(f"内容包：{pack['name']}（{pack['id']} v{pack['version']}；"
                  f"要求运行器 {pack['requires_runner']}）")
            for node in pack["nodes"]:
                local = node.get("local") or {}
                conflict = {"builtin": "与内置同名（拒绝导入）",
                            "user": "已有同名候选（内容不同时拒绝覆盖）"}.get(local.get("kind"))
                resources = (f"{node.get('memory_mb', '?')} MiB / {node.get('cpus', '?')} vCPU"
                             if node.get("memory_mb") else "资源未知")
                note = f"；{conflict}" if conflict else ""
                print(f"  节点 {node['profile']}：{resources}{note}")
            if pack["docs"]:
                print(f"  说明文件：{', '.join(pack['docs'])}")
            if pack["claims"]:
                print(f"  包内验收声明：{', '.join(pack['claims'])}（仅供参考，不代表本机已验收）")
        return 0
    for problem in report["problems"]:
        print(f"不一致：{problem}", file=sys.stderr)
    raise CTFLabError(f"分发目录校验失败：{len(report['problems'])} 项不一致")


def cmd_dist_install(manager: LabManager, args: argparse.Namespace) -> int:
    """校验并安装目录式内容包：配置、基盘、固件与说明一并登记到状态目录。"""
    result = manager.install_content_pack(args.dir)
    if getattr(args, "json", False):
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
        return 0
    pack = result.get("pack") or {}
    if pack:
        print(f"内容包：{pack.get('name')}（{pack.get('id')} v{pack.get('version')}）")
    if result["installed"]:
        print(f"已安装配置：{', '.join(result['installed'])}")
    if result["skipped_identical"]:
        print(f"内容一致，跳过：{', '.join(result['skipped_identical'])}")
    for profile_id in result["imported"]:
        state = manager.image_state(profile_id) or {}
        print(f"已导入节点 {profile_id}：基盘 {state.get('base_path')}")
    if result["docs"]:
        print(f"说明文件：{', '.join(result['docs'])}")
    if pack and pack.get("claims"):
        print(f"包内验收声明：{', '.join(pack['claims'])}（仅供参考；导入未把任何节点标记为本机已验证，"
              "实际验收以本机 probe/matrix 证据为准）")
    print("导入不会自动启动虚拟机；使用 ctflab run <profile> 或 GUI 启动。")
    return 0


def cmd_dist_make_pack(_manager: LabManager, args: argparse.Namespace) -> int:
    """制作 schema 2 内容包目录：完整校验 profile 后复制文件并生成清单。"""
    import ctflab_dist  # noqa: PLC0415

    profile_yaml = Path(args.profile).expanduser()
    if yaml is None:
        raise CTFLabError("当前 Python 缺少 PyYAML，无法读取 profile。")
    try:
        data = yaml.safe_load(profile_yaml.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CTFLabError(f"无法读取 profile：{profile_yaml}（{exc}）") from exc
    if not isinstance(data, dict):
        raise CTFLabError(f"profile 不是有效的 YAML 映射：{profile_yaml}")
    profile_id = str(data.get("id", ""))
    validate_pack_profile(data, profile_yaml)
    try:
        result = ctflab_dist.make_pack(
            args.out, pack_id=args.pack_id, profile_yaml=profile_yaml,
            base_image=Path(args.base).expanduser(), name=args.name,
            version=args.version, requires_runner=args.requires_runner,
            nvram=Path(args.nvram).expanduser() if args.nvram else None,
            docs=[Path(item).expanduser() for item in args.doc or []],
            profile_data=data)
    except ctflab_dist.DistError as exc:
        raise CTFLabError(str(exc)) from exc
    print(f"内容包已生成：{result['dir']}")
    for entry in result["entries"]:
        print(f"  {entry['file']}（{entry['role']}，{ctflab_dist.human_size(int(entry['size']))}，"
              f"sha256 {entry['sha256'][:12]}…）")
    print("导入：ctflab dist install --dir <内容包目录>（先整体校验，不自动启动）")
    return 0


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


def cmd_update(_manager: LabManager, args: argparse.Namespace) -> int:
    import ctflab_update
    root = args.root or args.state_dir / "updates"
    try:
        if args.update_command == "stage":
            result = ctflab_update.stage(root, args.source, args.sha256, args.allow_local_candidate)
        elif args.update_command == "select":
            result = ctflab_update.select(root, args.slot)
        elif args.update_command == "rollback":
            result = ctflab_update.select(root, rollback=True)
        elif args.update_command == "launch":
            result = ctflab_update.launch(root, args.state_dir)
        else:
            result = ctflab_update.status(root)
    except (ctflab_update.UpdateError, ctflab_update.AppBuildError, OSError, ValueError, subprocess.CalledProcessError) as error:
        raise CTFLabError(str(error)) from error
    print(json.dumps(result, ensure_ascii=False))
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
    overrides = resource_preset_overrides(args.profiles, getattr(args, "resource_preset", None))
    if overrides and any(state["profile_id"] == "kali-arm64" for state in manager.running_states()):
        raise CTFLabError("调整 Kali 资源档位需要先停止 Kali，再启动；不会修改正在运行的实例。")
    states = manager.run(args.profiles, headless=args.headless, pcap=args.pcap,
                         allow_internet=args.internet, clipboard=args.clipboard,
                         display=args.display,
                         display_quality=getattr(args, "display_quality", None), spice_listen=args.spice_listen,
                         file_transfer=getattr(args, "file_transfer", False),
                         profile_overrides=overrides)
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


def cmd_show_display(manager: LabManager, args: argparse.Namespace) -> int:
    print(json.dumps(manager.show_display(args.profile, reconnect=args.reconnect), ensure_ascii=False))
    return 0


BOOT_STAGE_LABELS = {
    "process": "进程启动",
    "guest-boot": "系统引导",
    "display": "显示连接",
    "network": "网络就绪",
}

DIAGNOSTICS_SECRET_PATTERN = re.compile(r"ticket|password|passwd|secret|token", re.IGNORECASE)
DIAGNOSTICS_LOG_TAIL_LINES = 6


def sanitize_log_line(line: str) -> str:
    """诊断包只保留定位所需内容；疑似凭据行整行替换，不做部分截取。"""
    return "[已脱敏：疑似凭据行]" if DIAGNOSTICS_SECRET_PATTERN.search(line) else line


def diagnostics_report(manager: "LabManager") -> dict[str, Any]:
    """一键脱敏诊断包：版本、能力、各节点启动阶段与日志尾行。

    对应路线图第 12 项：常见故障应能从诊断包定位到具体阶段。不收集口令、
    ticket、剪贴板正文或无关用户数据；日志只保留末尾几行并过滤疑似凭据行，
    状态摘要复用 ``_status_report``（GUI 与 CLI 同源，不引入第二套判断）。
    """
    def qemu_version(binary: str | None) -> str | None:
        if not binary:
            return None
        try:
            output = subprocess.run([binary, "--version"], capture_output=True,
                                    text=True, timeout=5)
            return output.stdout.splitlines()[0].strip() if output.stdout else None
        except (OSError, subprocess.SubprocessError, IndexError):
            return None

    qemu_arm = which_any(QEMU_ARM_NAMES)
    diagnostics: dict[str, Any] = {
        "schema": 1,
        "generated_at": now_iso(),
        "ctflab_version": CTFLAB_VERSION,
        "host": {
            "system": f"{platform.system()} {platform.release()}",
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "capabilities": {
            "qemu_img": resolve_tool("qemu-img"),
            "qemu_system_aarch64": qemu_arm,
            "qemu_system_aarch64_version": qemu_version(qemu_arm),
            "spice_client": spice_client_path(),
            "firmware_edk2_aarch64": str(find_firmware("edk2-aarch64-code.fd") or ""),
        },
        "stale_profiles": [
            {"id": profile_id, "pid": pid}
            for profile_id, pid in manager.stale_runtime_states()
        ],
        "profiles": [],
    }
    for node in _status_report(manager)["profiles"]:
        entry = dict(node)
        state = manager.runtime_state(str(node["id"])) or {}
        log_tail: dict[str, list[str]] = {}
        for label, key in (("qemu", "log_path"), ("spice_client", "spice_client_log_path")):
            path = Path(str(state.get(key) or ""))
            if not path.is_file():
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            log_tail[label] = [sanitize_log_line(item)
                               for item in lines[-DIAGNOSTICS_LOG_TAIL_LINES:]]
        if log_tail:
            entry["log_tail"] = log_tail
        diagnostics["profiles"].append(entry)
    return diagnostics


def write_diagnostics(manager: "LabManager", path: Path) -> Path:
    """写诊断包；0600 权限（含状态目录路径与日志尾行，不做公开分发）。"""
    payload = diagnostics_report(manager)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise CTFLabError("诊断文件已存在，请选择新文件名；不会覆盖已有文件。") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def boot_stage_summary(manager: "LabManager", profile_id: str,
                       state: dict[str, Any]) -> dict[str, Any] | None:
    """把运行中节点的启动进度归纳为固定四阶段；不引入新的重型探测。

    阶段只依据既有信号推导：QEMU 进程存活（进程启动）、任一健康检查通过
    （系统引导出现来宾活动）、SPICE 客户端日志出现 display-ready=1（显示连接）、
    宿主侧健康检查全部通过（网络就绪）。非 SPICE 后端的显示阶段与没有任何
    宿主侧检查的网络阶段标记为不适用（ok=null），不伪造进度。超过就绪超时
    仍未就绪时给出诊断：卡住的检查、日志路径与单节点恢复说明。
    """
    pid = int(state.get("pid", 0) or 0)
    if not bool_pid_alive(pid):
        return None
    profile = load_profile(profile_id)
    try:
        started_at = datetime.fromisoformat(str(state.get("started_at")))
        elapsed = int(max(0, (datetime.now(timezone.utc) - started_at).total_seconds()))
    except (TypeError, ValueError):
        elapsed = 0
    readiness_timeout = int(profile.get("readiness", {}).get("timeout_seconds", 180))
    health = manager.health(profile_id)
    concrete = [item for item in health
                if item["name"] != "process" and item.get("ok") is not None]
    guest_boot_ok = any(item.get("ok") is True for item in health if item["name"] != "process")
    network_ok = bool(concrete) and all(item.get("ok") is True for item in concrete)
    if str(state.get("display_backend") or "cocoa") == "spice":
        client_pid = int(state.get("spice_client_pid", 0) or 0)
        client_log = state.get("spice_client_log_path")
        display_ok = False
        if bool_pid_alive(client_pid) and client_log:
            try:
                display_ok = "display-ready=1" in Path(client_log).read_text(
                    encoding="utf-8", errors="replace")
            except OSError:
                display_ok = False
        display_stage = {"name": "display", "ok": display_ok,
                         "detail": "启动时已建立显示通道；当前状态见显示客户端" if display_ok else "等待显示通道就绪"}
    else:
        display_stage = {"name": "display", "ok": None, "detail": "非 SPICE 显示，不适用"}
    stages = [
        {"name": "process", "ok": True, "detail": f"PID {pid}"},
        {"name": "guest-boot", "ok": guest_boot_ok,
         "detail": "已出现来宾活动信号" if guest_boot_ok else "等待来宾引导信号"},
        display_stage,
        {"name": "network",
         "ok": network_ok if concrete else None,
         "detail": "健康检查全部通过" if network_ok else
                   ("没有宿主侧检查，不适用" if not concrete else "健康检查未全部通过")},
    ]
    phase = "process"
    for stage in stages:
        if stage["ok"] is True:
            phase = str(stage["name"])
    summary: dict[str, Any] = {
        "phase": phase,
        "phase_label": BOOT_STAGE_LABELS[phase],
        "overall": "ready" if network_ok else "booting",
        "elapsed_seconds": elapsed,
        "readiness_timeout_seconds": readiness_timeout,
        "stages": stages,
        "health": health,
    }
    if network_ok is not True and elapsed >= readiness_timeout:
        summary["overall"] = "timeout"
        summary["diagnosis"] = {
            "message": f"启动后 {elapsed}s（就绪超时 {readiness_timeout}s）仍未就绪",
            "failed_checks": [item["name"] for item in concrete if item.get("ok") is False],
            "log_path": state.get("log_path"),
            "client_log_path": state.get("spice_client_log_path"),
            "hint": "查看上述日志定位卡住的阶段；stop 仅作用于该节点，不影响其他节点；"
                    "reset 需显式确认，不会自动重置磁盘。",
        }
    return summary


MEMORY_COMMIT_LIMIT_RATIO = 0.9
DISK_WARNING_BYTES = 5 * 1024 ** 3


RESOURCE_PRESETS = {"light": (2048, 2), "balanced": (4096, 4), "performance": (8192, 4)}


def resource_preset_overrides(profile_ids: list[str], preset: str | None) -> dict[str, dict[str, Any]]:
    """只改变本次 Kali 的内存与 CPU，不写入用户 profile 或镜像。"""
    if preset is None:
        return {}
    if preset not in RESOURCE_PRESETS or [PROFILE_ALIASES.get(p, p) for p in profile_ids] != ["kali-arm64"]:
        raise CTFLabError("资源档位仅用于单独启动 Kali，可选 light、balanced、performance。")
    profile = copy.deepcopy(load_profile("kali-arm64"))
    memory, cpus = RESOURCE_PRESETS[preset]
    profile["guest"].update(memory_mb=memory, cpus=cpus)
    return {"kali-arm64": profile}


def check_host_resources(pending_profile_ids: list[str],
                         running_profile_ids: list[str],
                         state_dir: Path | None = None,
                         profile_overrides: dict[str, dict[str, Any]] | None = None,
                         running_memory: dict[str, int | None] | None = None) -> list[str]:
    """启动前资源预检（第 7 项）：内存超配直接拒绝，磁盘偏低告警。

    保守启发式：宿主物理内存 × 0.9 作为承诺上限，比较运行中与待启动节点的
    配置内存总和；这不是内存压力的精确测量，拒绝信息附带全部数字供人工
    判断。顺序启动（run 按列表逐个启动）本身就是启动队列；本检查防的是把
    宿主一次性压满导致整个实验环境失去响应。磁盘检查按状态目录所在卷的
    可用空间给出告警，不阻止启动。
    """
    warnings: list[str] = []
    try:
        output = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                text=True, timeout=5)
        total_bytes = int(output.stdout.strip())
    except Exception:  # noqa: BLE001 预检探针绝不能阻塞启动；读不到就跳过，
        # 不假装预检通过（返回空警告表，内存项按未检处理）。
        return warnings

    def configured_memory(profile_id: str) -> int:
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        if profile_id in running_profile_ids and (running_memory or {}).get(profile_id):
            return int(running_memory[profile_id]) * 1024 * 1024
        profile = (profile_overrides or {}).get(profile_id) or load_profile(profile_id)
        return int((profile.get("guest") or {}).get("memory_mb") or 0) * 1024 * 1024

    counted = list(dict.fromkeys([*running_profile_ids, *pending_profile_ids]))
    committed = sum(configured_memory(item) for item in counted)
    limit = int(total_bytes * MEMORY_COMMIT_LIMIT_RATIO)
    if committed > limit:
        detail = "、".join(
            f"{item}={configured_memory(item) // (1024 ** 2)}MiB"
            for item in counted)
        raise CTFLabError(
            f"内存预检未通过：本批与运行中节点合计 {committed // (1024 ** 3):.1f} GiB"
            f"（{detail}），超过宿主 {total_bytes // (1024 ** 3)} GiB × "
            f"{int(MEMORY_COMMIT_LIMIT_RATIO * 100)}% 上限。请先 stop 部分节点或减少"
            "本批数量；x86 靶机为 TCG 模拟，超配会使整机失去响应。")
    try:
        usage = os.statvfs(state_dir or DEFAULT_STATE_DIR)
    except OSError:
        usage = None
    if usage is not None:
        free = usage.f_bavail * usage.f_frsize
        if free < DISK_WARNING_BYTES:
            warnings.append(
                f"状态目录所在卷仅剩 {free / (1024 ** 3):.1f} GiB 可用（阈值 "
                f"{DISK_WARNING_BYTES // (1024 ** 3)} GiB）；overlay 增长或导入转换"
                "可能失败，请清理或迁移后重试。")
    return warnings


def spice_client_summary(state: dict[str, Any]) -> dict[str, Any] | None:
    """显示客户端与虚拟机状态分列展示的数据源：仅 SPICE 后端节点有值。

    使用最新 display-ready 事件，不把启动阶段曾经就绪的历史当作当前状态。
    alive 仅表示客户端进程存活；就绪不证明来宾已登录、未锁屏或画面非黑。
    """
    if str(state.get("display_backend") or "cocoa") != "spice":
        return None
    client_pid = int(state.get("spice_client_pid", 0) or 0)
    alive = bool_pid_alive(client_pid)
    display_ready = False
    transition_reason = None
    client_log = state.get("spice_client_log_path")
    if alive and client_log:
        try:
            log_text = Path(client_log).read_text(encoding="utf-8", errors="replace")
            events = re.findall(r"^CTFLAB_SPICE_STATE display-ready=([01])\s*$", log_text, re.MULTILINE)
            display_ready = bool(events and events[-1] == "1")
            transitions = re.findall(r"display-transition end reason=([^\s]+)", log_text)
            transition_reason = transitions[-1] if transitions else None
        except OSError:
            display_ready = False
    result = {"pid": client_pid or None, "alive": alive, "display_ready": display_ready}
    if transition_reason is not None:
        result["last_transition_reason"] = transition_reason
    return result


def network_report(manager: "LabManager") -> dict[str, Any]:
    """实验网只读拓扑（第 11 项展示切片）：profile 声明策略与运行实际并排。

    不做任何变更。联网一致性：非 Kali 节点运行时联网必须与声明一致；Kali 的
    user-mode NAT 是运行器默认策略（实验网仍经回环交换机隔离），单独注明。
    靶机应用级回连与组合间隔离验证仍未完成，不得据此宣称安全边界已验证。
    """
    running = {state["profile_id"]: state for state in manager.running_states()}
    nodes: list[dict[str, Any]] = []
    for profile_id in available_profiles():
        profile = load_profile(profile_id)
        declared = profile.get("network", {}) or {}
        state = running.get(profile_id) or {}
        runtime_internet = bool(state.get("internet_enabled"))
        declared_internet = bool(declared.get("internet"))
        is_kali = profile_id == "kali-arm64"
        entry: dict[str, Any] = {
            "id": profile_id,
            "declared": {
                "segment": declared.get("segment"),
                "lab_ip": declared.get("lab_ip"),
                "internet": declared_internet,
                "adapter": declared.get("adapter"),
                "host_forwards": {str(item.get("name")): int(item.get("host_port", 0))
                                  for item in declared.get("host_forwards", []) or []},
            },
            "running": bool(state),
            "internet_policy": {
                "declared": declared_internet,
                "runtime": runtime_internet,
                "note": ("运行器默认为 Kali 启用 user-mode NAT；实验网仍经回环交换机隔离"
                         if is_kali and runtime_internet else
                         "公网隔离" if not runtime_internet else ""),
                "consistent": True if is_kali else declared_internet == runtime_internet,
            },
            "actual": None,
        }
        if state:
            entry["actual"] = {
                "lab_port": state.get("lab_port"),
                "dhcp_lease": manager.dhcp_lease(profile_id),
                "host_forwards": state.get("host_forwards") or {},
                "spice_endpoint": state.get("spice_endpoint"),
                "spice_listen": state.get("spice_listen"),
            }
        nodes.append(entry)
    switches: list[dict[str, Any]] = []
    for port in manager.network_ports():
        net = manager.network_state(port) or {}
        counters = net.get("counters", {}) or {}
        switches.append({
            "lab_port": port,
            "pid": net.get("pid"),
            "alive": bool_pid_alive(int(net.get("pid", 0) or 0)),
            "clients": net.get("client_count"),
            "learned_macs": len(net.get("learned_macs", []) or []),
            "counters": {key: counters.get(key)
                         for key in ("received", "forwarded", "dropped_rate_limit")},
            "pcap_path": net.get("pcap_path"),
        })
    return {"schema": 1, "state_dir": str(manager.state_dir),
            "nodes": nodes, "switches": switches}


def sample_process_usage(pids: list[int]) -> dict[int, dict[str, float]]:
    """一次只读采样已有 QEMU PID；CPU 为 ps 口径，RSS 为宿主驻留内存，不是来宾内存。"""
    valid = sorted({pid for pid in pids if isinstance(pid, int) and pid > 0})
    if not valid:
        return {}
    try:
        output = subprocess.run(["/bin/ps", "-p", ",".join(map(str, valid)),
                                 "-o", "pid=,%cpu=,rss="], capture_output=True, text=True,
                                timeout=1, env={**os.environ, "LC_ALL": "C"})
        result: dict[int, dict[str, float]] = {}
        for line in output.stdout.splitlines():
            fields = line.split()
            if len(fields) != 3:
                continue
            try:
                pid, cpu, rss_kb = int(fields[0]), float(fields[1]), float(fields[2])
                if pid in valid and math.isfinite(cpu) and math.isfinite(rss_kb) and cpu >= 0 and rss_kb >= 0:
                    result[pid] = {"cpu_percent": cpu, "rss_mb": round(rss_kb / 1024, 1)}
            except ValueError:
                continue
        return result
    except (OSError, subprocess.TimeoutExpired):
        return {}


def node_resource_summary(profile: dict[str, Any], state: dict[str, Any],
                          usage: dict[int, dict[str, float]]) -> dict[str, Any]:
    command = state.get("command")
    acceleration = None
    if isinstance(command, list) and "-accel" in command:
        index = command.index("-accel") + 1
        if index < len(command):
            acceleration = command[index]
    sampled = usage.get(int(state.get("pid", 0) or 0), {})
    configured = state if state else profile.get("guest", {})
    return {"memory_mb": configured.get("memory_mb"), "cpus": configured.get("cpus"),
            "cpu_percent": sampled.get("cpu_percent"), "rss_mb": sampled.get("rss_mb"),
            "acceleration": acceleration}


def _status_report(manager: LabManager) -> dict[str, Any]:
    """状态快照（GUI 与文本模式共用同一数据源，避免两套判断）。"""
    running = {state["profile_id"]: state for state in manager.running_states()}
    usage = sample_process_usage([int(state.get("pid", 0) or 0) for state in running.values()])
    stale = {profile_id: pid for profile_id, pid in manager.stale_runtime_states()}
    profiles: list[dict[str, Any]] = []
    for profile_id in available_profiles():
        profile = load_profile(profile_id)
        image = manager.image_state(profile_id) or {}
        # image.json 只是一次导入的登记记录。基础盘若后来被用户移动或清理，不能继续
        # 在 GUI 中误报“已导入”；状态查询不重算大盘哈希，只做存在性核验并给出失效状态。
        base_path_text = str(image.get("base_path") or "")
        base_exists = bool(base_path_text) and Path(base_path_text).is_file()
        imported = bool(image) and base_exists
        import_state = ("registered" if imported else
                        "missing-base" if image else "not-imported")
        state = running.get(profile_id) or {}
        lab_port = int(state.get("lab_port", 0) or 0)
        network = (manager.network_state(lab_port) or {}) if lab_port else {}
        boot = boot_stage_summary(manager, profile_id, state) if state else None
        profiles.append({
            "id": profile_id,
            "name": str(profile.get("name", profile_id)),
            # 内置课程包（随包分发）不可被 deregister 移除；GUI 据此隐藏“移除登记”。
            "builtin": (BUILTIN_PROFILE_DIR / f"{profile_id}.yaml").is_file(),
            "architecture": str((profile.get("guest") or {}).get("architecture", "")),
            "firmware": str((profile.get("guest") or {}).get("firmware", "")),
            "imported": imported,
            "import_state": import_state,
            "source_format": image.get("source_format"),
            # 内容包导入的节点显示来源包；claims_from_pack 只用于展示声明，不代表本机验收。
            "content_pack": image.get("content_pack"),
            "has_pack_claims": bool(image.get("claims_from_pack")),
            # GUI 的“扫描并导入新增”用它做幂等：同一路径不重复 onboard。
            "source_path": image.get("source_path"),
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
            "boot": boot,
            "spice_client": spice_client_summary(state) if state else None,
            "resources": node_resource_summary(profile, state, usage),
            "network": {
                "client_count": network.get("client_count"),
                "learned_macs": len(network.get("learned_macs", []) or []),
                "pcap_path": network.get("pcap_path"),
            } if network else None,
        })
    return {"schema": 1, "state_dir": str(manager.state_dir), "profiles": profiles,
            "running_count": len(running)}


def startup_preflight(manager: LabManager, profile_id: str, preset: str | None = None) -> dict[str, Any]:
    """只读启动检查；不创建 overlay、交换机或重置磁盘，run 仍保留最终检查。"""
    profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
    profile = resource_preset_overrides([profile_id], preset).get(profile_id) or load_profile(profile_id)
    checks: list[dict[str, Any]] = []
    def check(name: str, operation: Any, hint: str) -> None:
        try:
            operation()
            checks.append({"name": name, "ok": True, "detail": "通过"})
        except (CTFLabError, OSError, ValueError) as error:
            checks.append({"name": name, "ok": False, "detail": str(error), "hint": hint})
    image = manager.image_state(profile_id) or {}
    def disk_check() -> None:
        base = Path(str(image.get("base_path") or ""))
        if not image or not base.is_file():
            raise CTFLabError("基础镜像未导入或已被移动")
        overlay = manager.runtime_dir / profile_id / "overlay.qcow2"
        if overlay.exists():
            backing = qemu_info(overlay).get("full-backing-filename")
            if not backing or Path(str(backing)).resolve() != base.resolve():
                raise CTFLabError("运行盘指向旧基盘；请先备份，再在“快照与备份”中重置")
        if profile["guest"].get("firmware") == "uefi":
            architecture = profile["guest"]["architecture"]
            _, vars_name = manager.UEFI_FIRMWARE[architecture]
            template = (Path(image["uefi_vars_path"]) if architecture == "aarch64" and image.get("uefi_vars_path")
                        else find_firmware(vars_name))
            if not template or not template.is_file():
                raise CTFLabError("UEFI NVRAM 模板缺失，请校验分发目录后重新导入")
    check("disk", disk_check, "使用校验导入；旧运行盘先备份再重置，检查本身不修改磁盘。")
    running = manager.running_states()
    check("resources", lambda: check_host_resources([profile_id], [item["profile_id"] for item in running],
          manager.state_dir, profile_overrides={profile_id: profile},
          running_memory={item["profile_id"]: item.get("memory_mb") for item in running}),
          "在更多菜单选择轻量档，或停止不需要的节点后重试。")
    def runtime_check() -> None:
        qemu = which_any(QEMU_ARM_NAMES if profile["guest"]["architecture"] == "aarch64" else QEMU_X86_NAMES)
        if not qemu:
            raise CTFLabError("缺少对应架构的 QEMU，请使用完整候选 App")
        qemu_img_path()
        if profile["guest"].get("firmware") == "uefi":
            code_name, _ = manager.UEFI_FIRMWARE[profile["guest"]["architecture"]]
            if not find_firmware(code_name):
                raise CTFLabError("UEFI 固件代码缺失，请使用完整 App")
        if profile_id == "kali-arm64":
            capabilities = manager.probe_spice(qemu)
            if not capabilities.get("supported"):
                raise manager.spice_capability_error(capabilities)
    check("runtime", runtime_check, "使用含 SPICE 客户端与运行时的完整 App；不会静默回退。")
    def ports_check() -> None:
        if any(item["profile_id"] == profile_id for item in running):
            raise CTFLabError("节点已经运行，请打开显示窗口，不要重复启动")
        for forward in profile.get("network", {}).get("host_forwards", []):
            with socket.socket() as endpoint:
                endpoint.bind(("127.0.0.1", int(forward["host_port"])))
    check("ports", ports_check, "停止占用端口的已知节点，或调整该配置；不会结束其他程序。")
    return {"profile": profile_id, "ok": all(item["ok"] for item in checks), "checks": checks,
            "scope": "read-only-preflight-run-rechecks"}


def display_diagnosis(manager: LabManager, profile_id: str) -> dict[str, Any]:
    """按需查询 QMP/画面，临时截图即清理；黑色或静止不能证明卡死。"""
    profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
    state = manager.runtime_state(profile_id) or {}
    report: dict[str, Any] = {"profile": profile_id, "state": "stopped", "hint": "节点已停止，请启动节点。"}
    if not bool_pid_alive(int(state.get("pid", 0) or 0)):
        return report
    report.update(state="unknown", client=spice_client_summary(state), hint="状态不明；可以只重连显示，不要重置磁盘。")
    try:
        report["qmp"] = qmp_execute(Path(state["qmp_path"]), "query-status")
        if not report["qmp"].get("running"):
            report.update(state="paused", hint="来宾未在执行；显示重连不能替代恢复来宾执行。")
            return report
        client = report["client"]
        if client and not client["alive"]:
            report.update(state="disconnected", hint="来宾仍运行，显示客户端已退出；点重新打开显示窗口。")
            return report
        with tempfile.TemporaryDirectory(prefix="ctflab-display-diagnosis-") as temporary:
            frame = Path(temporary) / "frame.ppm"
            qmp_execute(Path(state["qmp_path"]), "screendump", {"filename": str(frame)})
            report["frame"] = ppm_display_activity(frame)
        if report["frame"].get("nonblack_ratio", 0) >= .002:
            report.update(state="frame-present", hint="来宾原始画面非黑；不证明可点击。若窗口不更新，可只重连显示。")
        elif "width" in report["frame"]:
            report.update(state="black-frame", hint="来宾原始画面接近全黑，可能息屏或锁屏；先移动鼠标或按普通键，不能据此判定死机。")
    except (CTFLabError, OSError, KeyError) as error:
        report["error"] = str(error)
    return report


def cmd_preflight(manager: LabManager, args: argparse.Namespace) -> int:
    report = startup_preflight(manager, args.profile, args.resource_preset)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["ok"] else 2


def cmd_display_diagnose(manager: LabManager, args: argparse.Namespace) -> int:
    print(json.dumps(display_diagnosis(manager, args.profile), ensure_ascii=False))
    return 0


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
        boot = boot_stage_summary(manager, profile_id, state)
        if boot:
            elapsed = boot["elapsed_seconds"]
            limit = boot["readiness_timeout_seconds"]
            print(f"  阶段：{boot['phase_label']}（{elapsed}s/{limit}s）")
            if boot["overall"] == "timeout":
                diagnosis = boot["diagnosis"]
                print(f"  诊断：{diagnosis['message']}；卡住检查："
                      f"{', '.join(diagnosis['failed_checks']) or '无明确失败项'}")
                print(f"  {diagnosis['hint']}")
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
    backup_name = getattr(args, "backup", None)
    manager.reset(args.profile, force=args.force, backup_name=backup_name)
    if backup_name:
        print(f"已备份为 {backup_name} 并重置 {args.profile}："
              f"可用 snapshot restore-backup {args.profile} {backup_name} 恢复。")
    else:
        print(f"已重置 {args.profile}：下次启动会从基础镜像创建全新 overlay。")
    return 0


def cmd_deregister(manager: LabManager, args: argparse.Namespace) -> int:
    profile_id = PROFILE_ALIASES.get(args.profile, args.profile)
    if (BUILTIN_PROFILE_DIR / f"{profile_id}.yaml").is_file():
        raise CTFLabError(f"{profile_id} 是内置配置，不能移除；内置节点始终可用。")
    user_yaml = user_profile_dir() / f"{profile_id}.yaml"
    if not user_yaml.is_file() or user_yaml.is_symlink():
        raise CTFLabError(f"用户目录中没有 {profile_id} 的登记（可用：{', '.join(available_profiles())}）。")
    if manager.image_state(profile_id):
        raise CTFLabError(f"{profile_id} 已导入镜像数据；先执行 ctflab reset {profile_id} 删除导入数据，再移除登记。")
    runtime = manager.runtime_state(profile_id)
    if runtime and bool_pid_alive(int(runtime.get("pid", 0) or 0)):
        raise CTFLabError(f"{profile_id} 正在运行；先停止再移除登记。")
    user_yaml.unlink()
    print(f"已移除登记：{profile_id}（未导入镜像数据，未删除任何文件之外的内容）。")
    return 0


def cmd_remove_image(manager: LabManager, args: argparse.Namespace) -> int:
    profile_id = PROFILE_ALIASES.get(args.profile, args.profile)
    manager.remove_image(profile_id)
    user_yaml = user_profile_dir() / f"{profile_id}.yaml"
    builtin = (BUILTIN_PROFILE_DIR / f"{profile_id}.yaml").is_file()
    if not builtin and user_yaml.is_file() and not user_yaml.is_symlink():
        user_yaml.unlink()
        print(f"已删除镜像数据并移除登记：{profile_id}（原始来源镜像不受影响）。")
    else:
        print(f"已删除镜像数据：{profile_id}（内置课程配置保留，重新显示为“未导入”）。")
    return 0


def cmd_snapshot(manager: LabManager, args: argparse.Namespace) -> int:
    action = args.snapshot_command
    if action == "create":
        result = manager.snapshot_create(args.profile, args.name)
        suffix = "（含 NVRAM 副本）" if result["nvram_paired"] else "（无 NVRAM，未配对）"
        print(f"已创建快照 {args.profile}:{args.name} {suffix}")
    elif action == "list":
        manager._require_stopped(args.profile, "列出快照")
        snapshots = (manager.snapshot_list(args.profile)
                     if (manager.runtime_dir / args.profile / "overlay.qcow2").is_file() else [])
        if getattr(args, "json", False):
            print(json.dumps({"snapshots": snapshots}, ensure_ascii=False))
            return 0
        if not snapshots:
            print(f"{args.profile} 没有快照。")
        for item in snapshots:
            nvram_mark = "NVRAM✓" if (manager.runtime_dir / args.profile /
                                       f"uefi-vars.fd.snapshot-{item['tag']}").exists() else "—"
            print(f"{item['id']:>3}  {item['tag']:<32} {item['vm_size']:>10}  "
                  f"{item['date']}  {nvram_mark}")
    elif action == "revert":
        result = manager.snapshot_revert(args.profile, args.name)
        suffix = "，NVRAM 已恢复" if result["nvram_restored"] else ""
        print(f"已恢复快照 {args.profile}:{args.name}{suffix}")
    elif action == "delete":
        manager.snapshot_delete(args.profile, args.name)
        print(f"已删除快照 {args.profile}:{args.name}")
    elif action == "restore-backup":
        result = manager.backup_restore(args.profile, args.name)
        print(f"已恢复整盘备份 {result['restored_backup']} 为 {args.profile} 当前实例。")
        if result.get("previous_backup"):
            print(f"恢复前的实例另存为备份：{result['previous_backup']}。")
    elif action == "delete-backup":
        manager.backup_delete(args.profile, args.name)
        print(f"已删除指定整盘备份 {args.profile}:{args.name}（不能恢复；当前实例与基础盘不变）。")
    elif action == "list-backups":
        backups = manager.backups_list(args.profile)
        if getattr(args, "json", False):
            print(json.dumps({"backups": backups}, ensure_ascii=False))
            return 0
        if not backups:
            print(f"{args.profile} 没有整盘备份（reset --backup 产生）。")
        for item in backups:
            size_mb = (item["overlay_bytes"] or 0) / (1024 * 1024)
            mark = "" if item["complete"] else "（不完整）"
            print(f"{item['name']:<32} {size_mb:>10.1f} MB{mark}")
    return 0


def cmd_network(manager: LabManager, args: argparse.Namespace) -> int:
    report = network_report(manager)
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    switch_by_port = {item["lab_port"]: item for item in report["switches"]}
    for node in report["nodes"]:
        state_text = "运行中" if node["running"] else "已停止"
        print(f"{node['id']}（{state_text}）")
        declared = node["declared"]
        policy = node["internet_policy"]
        internet_text = policy["note"] or ("声明联网" if policy["declared"] else "公网隔离")
        if not policy["consistent"]:
            internet_text += "；⚠ 与 profile 声明不一致"
        print(f"  策略：segment={declared['segment']} ip={declared['lab_ip']} "
              f"adapter={declared['adapter']}；联网：{internet_text}")
        forwards = declared["host_forwards"]
        if forwards:
            print("  端口映射：" + ", ".join(f"{name}=127.0.0.1:{port}"
                                            for name, port in forwards.items()))
        if node["actual"]:
            actual = node["actual"]
            switch = switch_by_port.get(int(actual["lab_port"] or 0))
            if switch:
                switch_text = (f"交换机 {'存活' if switch['alive'] else '已退出'}，"
                               f"{switch['clients']} 客户端，{switch['learned_macs']} MAC")
                print(f"  实验网：tcp://127.0.0.1:{actual['lab_port']}（{switch_text}）")
                counters = switch["counters"]
                print(f"  流量：rx={counters['received']} forwarded={counters['forwarded']} "
                      f"dropped={counters['dropped_rate_limit']}")
            if actual["dhcp_lease"]:
                print(f"  DHCP 租约：{actual['dhcp_lease']}")
            if actual["spice_endpoint"]:
                listen = "TCP+ticket" if actual["spice_listen"] == "tcp" else "UNIX socket"
                print(f"  显示：SPICE {listen}（仅本机）")
    for switch in report["switches"]:
        if not any((node["actual"] or {}).get("lab_port") == switch["lab_port"]
                   for node in report["nodes"]):
            alive_text = "存活" if switch["alive"] else "已退出"
            print(f"残留实验网：tcp://127.0.0.1:{switch['lab_port']}（{alive_text}，无运行实例），可执行 stop --all。")
    return 0


def cmd_storage(manager: LabManager, args: argparse.Namespace) -> int:
    report = manager.storage_report()
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    for entry in report["profiles"]:
        state = "运行中" if entry["running"] else ("已导入" if entry["imported"] else "未导入")
        print(f"{entry['id']}: {state}")
        if entry.get("base"):
            base = entry["base"]
            referenced = "；运行中节点引用" if entry["base_referenced"] else ""
            print(f"  基础镜像 {base['actual_bytes'] / (1024 ** 3):.2f} GiB"
                  f"（虚拟 {base['virtual_bytes'] / (1024 ** 3):.1f} GiB）{referenced}")
        if entry.get("overlay"):
            overlay = entry["overlay"]
            chain = "backing 完整" if overlay["backing_ok"] else "backing 缺失！"
            print(f"  overlay {overlay['actual_bytes'] / (1024 ** 2):.1f} MiB（{chain}）")
        for snapshot in entry.get("snapshots", []):
            print(f"    快照 {snapshot['tag']}（{snapshot['vm_size']}，{snapshot['date']}）")
        for backup in entry.get("backups", []):
            print(f"    整盘备份 {backup['name']}"
                  f"（{(backup['overlay_bytes'] or 0) / (1024 ** 2):.1f} MiB）")
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
    if args.apply_matrix_report:
        if (args.matrix or args.keep_running or args.timeout is not None
                or args.matrix_timeout != 90 or args.matrix_max is not None or args.matrix_start != 1):
            raise CTFLabError("--apply-matrix-report 只执行离线保存，不能与启动/矩阵参数混用。")
        result = manager.apply_matrix_candidate(args.profile, args.apply_matrix_report,
                                                confirm=args.confirm_apply,
                                                review_attempt=args.review_attempt)
        print(f"已保存白名单候选参数：{candidate_label(result['candidate'])}")
        print(f"原配置备份：{result['backup_path']}")
        print("状态仍为 candidate；尚未完成登录、网络和目标服务验收。")
        return 0
    if args.confirm_apply or args.review_attempt is not None:
        raise CTFLabError("--confirm-apply 必须与 --apply-matrix-report 同时使用。")
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
        if result.get("review_attempt"):
            index = result["review_attempt"]
            print(f"矩阵待人工复核：{index}（没有自动成功结论）")
            print(f"复核截图：{result['attempts'][index - 1]['screenshot_path']}")
            print(f"矩阵报告：{result['report_path']}")
            return 0
        if result.get("stopped_reason"):
            print(f"矩阵结论：已提前停止（{result['stopped_reason']['category']}）；"
                  f"{result['stopped_reason']['hint']}")
        else:
            print("矩阵结论：本次已尝试的白名单候选没有识别到可用启动画面；请人工检查截图与日志。")
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
    for recommendation in report.get("recommendations", []):
        print(f"建议：{recommendation}")
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

    update_parser = subparsers.add_parser("update", help="本地校验更新槽位与回退；不下载或覆盖现用 App")
    update_sub = update_parser.add_subparsers(dest="update_command", required=True)
    for operation in ("stage", "select", "rollback", "status", "launch"):
        item = update_sub.add_parser(operation)
        item.add_argument("--root", type=Path, help="更新槽位目录；默认当前 state-dir 下的 updates")
        if operation == "stage":
            item.add_argument("source", type=Path)
            item.add_argument("--sha256", required=True)
            item.add_argument("--allow-local-candidate", action="store_true")
        if operation == "select":
            item.add_argument("slot")

    preflight_parser = subparsers.add_parser("preflight", help="只读启动检查，不修改磁盘或网络")
    preflight_parser.add_argument("profile", choices=profile_choices)
    preflight_parser.add_argument("--resource-preset", choices=list(RESOURCE_PRESETS))
    diagnosis_parser = subparsers.add_parser("display-diagnose", help="按需诊断显示；黑屏不等同死机")
    diagnosis_parser.add_argument("profile", choices=profile_choices)

    doctor_parser = subparsers.add_parser("doctor", help="检查本机 QEMU/UTM/PyYAML 依赖")
    doctor_parser.add_argument("--diagnostics", type=Path,
                               help="导出脱敏诊断包 JSON（版本/能力/启动阶段/日志尾行）")
    subparsers.add_parser("list", help="列出内置配置及导入状态")

    inspect_parser = subparsers.add_parser("inspect", help="只读探测镜像并生成带置信度的硬件候选")
    inspect_parser.add_argument("source", help="磁盘、OVA 或虚拟机目录")
    inspect_parser.add_argument("--json", action="store_true", help="输出完整 JSON 报告")
    inspect_parser.add_argument("--no-hash", action="store_true", help="跳过耗时的 SHA-256（正式导入仍会计算）")
    inspect_parser.add_argument("--disk", help="OVA/目录含多磁盘时显式选择成员（按文件名）")

    onboard_parser = subparsers.add_parser("onboard", help="探测新镜像、生成候选配置并安全导入")
    onboard_parser.add_argument("source", help="磁盘、OVA 或虚拟机目录")
    onboard_parser.add_argument("--id", required=True, help="新配置 id，例如 vulnbox-1")
    onboard_parser.add_argument("--name", help="显示名称；默认由文件名生成")
    onboard_parser.add_argument("--disk", help="OVA/目录含多磁盘时显式选择系统盘（按文件名）")
    onboard_parser.add_argument("--architecture", choices=["auto", "x86_64", "aarch64"], default="auto")
    onboard_parser.add_argument("--firmware", choices=["auto", "bios", "uefi"], default="auto")
    onboard_parser.add_argument("--disk-bus", choices=["auto", "ide", "sata", "scsi", "virtio"], default="auto")
    onboard_parser.add_argument("--disk-controller", help="受控控制器型号，例如 lsi53c895a 或 ich9-ahci")
    onboard_parser.add_argument("--network-adapter", choices=["auto", "e1000", "pcnet", "virtio-net-pci"], default="auto")
    onboard_parser.add_argument("--memory-mb", type=int)
    onboard_parser.add_argument("--cpus", type=int)
    onboard_parser.add_argument("--lab-ip", help="固定实验网地址；默认自动从 192.168.242.30 起分配")
    onboard_parser.add_argument("--no-import", action="store_true", help="只生成候选配置和报告，不转换磁盘")
    onboard_parser.add_argument("--resume", action="store_true", help="重试同来源、同选盘的未登记用户候选；不覆盖已有节点")

    import_parser = subparsers.add_parser("import", help="导入 VMDK/QCOW2/OVA 等镜像")
    import_parser.add_argument("profile", choices=profile_choices)
    import_parser.add_argument("source", help="磁盘文件或包含单个磁盘的目录")
    import_parser.add_argument("--disk", help="OVA 含多磁盘时显式选择系统盘（按文件名；多磁盘不指定会拒绝导入）")
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
    dist_verify.add_argument("--conflicts", action="store_true",
                             help="内容包冲突预览：标注与内置/用户同名配置（只读）")
    dist_install = dist_sub.add_parser(
        "install", help="安装目录式内容包（schema 2）：校验→装配置→导基盘→复制说明；不自动启动")
    dist_install.add_argument("--dir", type=Path, required=True,
                              help="内容包目录（含 schema 2 DISTRIBUTION.json）")
    dist_install.add_argument("--json", action="store_true", help="输出机器可读结果")
    dist_make_pack = dist_sub.add_parser(
        "make-pack", help="制作目录式内容包：校验 profile 后复制文件并生成清单（不改动来源）")
    dist_make_pack.add_argument("--out", type=Path, required=True,
                                help="内容包目录；目标已存在且非空时拒绝")
    dist_make_pack.add_argument("--pack-id", required=True,
                                help="内容包 id（小写字母/数字/短横线；区别于节点 profile id）")
    dist_make_pack.add_argument("--name", help="内容包显示名；默认用 pack-id")
    dist_make_pack.add_argument("--version", default="1.0.0", help="内容包版本，默认 1.0.0")
    dist_make_pack.add_argument("--requires-runner", help="最低运行器约束，默认 >=当前版本")
    dist_make_pack.add_argument("--profile", type=Path, required=True,
                                help="节点配置 YAML（按内容包白名单完整校验）")
    dist_make_pack.add_argument("--base", type=Path, required=True, help="基盘镜像（原样复制）")
    dist_make_pack.add_argument("--nvram", type=Path, help="可选 UEFI NVRAM 模板（aarch64 推荐）")
    dist_make_pack.add_argument("--doc", type=Path, action="append",
                                help="说明文件（md/txt/pdf/png/jpg），可多次给出")

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
    run_parser.add_argument("--resource-preset", choices=list(RESOURCE_PRESETS),
                            help="Kali 本次启动资源：light=2GiB/2核、balanced=4GiB/4核、performance=8GiB/4核；不改基础配置")
    show_parser = subparsers.add_parser("show", help="恢复运行中节点的显示；不重启虚拟机")
    show_parser.add_argument("--reconnect", action="store_true", help="只重建显示连接，不重启来宾或改变共享授权")
    show_parser.add_argument("profile", choices=profile_choices)
    run_parser.add_argument("--display-quality", choices=["sharp", "smooth"],
                            help="SPICE 显示偏好：smooth=流畅优先（逻辑分辨率，UI 大小正常，默认），"
                                 "sharp=清晰优先（Retina 设备像素，UI 更小更精细）；均真实跟随分辨率，"
                                 "并记忆到节点状态，下次启动默认沿用")
    run_parser.add_argument("--headless", action="store_true", help="不打开图形窗口，日志写入 logs/")
    run_parser.add_argument("--clipboard", action="store_true", help="显式允许 Mac 与 Kali 图形桌面双向共享文本剪贴板；不启用文件传输")
    run_parser.add_argument("--file-transfer", action="store_true", help="独立允许从 Mac 拖入文件到 Kali（仅 SPICE；不启用文本剪贴板）")
    run_parser.add_argument("--pcap", action="store_true", help="记录隔离实验网的 Ethernet PCAP")
    run_parser.add_argument("--internet", action="store_true",
                            help="兼容旧命令的显式确认；Kali 图形启动默认联网，其他节点仍隔离")
    run_parser.add_argument("--display", choices=("auto", "cocoa", "spice"), default="auto",
                            help="显示后端；默认 auto 在 Kali 的 SPICE 能力完整时使用真实自动分辨率，缺件时退化为 Cocoa；显式 spice 缺件会失败")
    run_parser.add_argument("--spice-listen", choices=("unix", "tcp"), default="unix",
                            help="SPICE 监听方式；默认 unix socket（0700 目录鉴权），tcp 为仅绑定 127.0.0.1 受控端口并使用每次运行 ticket 的回退路径")

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

    reset_parser.add_argument("--backup", metavar="NAME",
                              help="重置前把整个实例盘（overlay+NVRAM）移入备份区保存")

    deregister_parser = subparsers.add_parser(
        "deregister", help="移除用户目录中未导入的 profile 登记（不动内置配置与镜像数据）")
    deregister_parser.add_argument("profile", metavar="PROFILE",
                                   help="要移除登记的 profile ID（仅用户目录登记）")

    remove_parser = subparsers.add_parser(
        "remove", help="删除已导入的镜像数据（基盘副本与登记；原始来源镜像不受影响）")
    remove_parser.add_argument("profile", metavar="PROFILE", help="要删除镜像的 profile ID")

    snapshot_parser = subparsers.add_parser(
        "snapshot", help="节点 overlay 快照与整盘备份（只作用于已停止节点；基础镜像只读）")
    snapshot_sub = snapshot_parser.add_subparsers(dest="snapshot_command", required=True)
    snapshot_create = snapshot_sub.add_parser("create", help="创建命名快照（含 NVRAM 副本）")
    snapshot_create.add_argument("profile", choices=profile_choices)
    snapshot_create.add_argument("name", help="小写字母/数字开头，仅含 a-z0-9._-，长度 1-32")
    snapshot_list = snapshot_sub.add_parser("list", help="列出快照")
    snapshot_list.add_argument("profile", choices=profile_choices)
    snapshot_list.add_argument("--json", action="store_true")
    snapshot_revert = snapshot_sub.add_parser("revert", help="恢复到指定快照（当前实例改动丢弃）")
    snapshot_revert.add_argument("profile", choices=profile_choices)
    snapshot_revert.add_argument("name")
    snapshot_delete = snapshot_sub.add_parser("delete", help="删除快照")
    snapshot_delete.add_argument("profile", choices=profile_choices)
    snapshot_delete.add_argument("name")
    snapshot_backup_list = snapshot_sub.add_parser("list-backups", help="列出 reset --backup 的整盘备份")
    snapshot_backup_list.add_argument("profile", choices=profile_choices)
    snapshot_backup_list.add_argument("--json", action="store_true")
    snapshot_restore = snapshot_sub.add_parser(
        "restore-backup", help="把整盘备份恢复为当前实例（覆盖现有 overlay）")
    snapshot_restore.add_argument("profile", choices=profile_choices)
    snapshot_restore.add_argument("name")
    snapshot_delete_backup = snapshot_sub.add_parser("delete-backup", help="删除指定整盘备份（不可恢复；基础盘与当前实例不变）")
    snapshot_delete_backup.add_argument("profile", choices=profile_choices)
    snapshot_delete_backup.add_argument("name")

    storage_parser = subparsers.add_parser(
        "storage", help="各节点磁盘占用、backing chain、快照与备份清单（只读，不清理）")
    network_parser = subparsers.add_parser(
        "network", help="实验网拓扑、联网策略与端口映射的只读视图（不做变更）")
    network_parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    storage_parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")

    health_parser = subparsers.add_parser("health", help="检查进程和已配置的端口")
    health_parser.add_argument("profile", choices=profile_choices)
    health_parser.add_argument("--json", action="store_true",
                               help="输出机器可读健康检查结果（GUI 使用）")

    probe_parser = subparsers.add_parser("probe", help="启动候选并收集 QMP 截图、DHCP 和服务证据")
    probe_parser.add_argument("profile", choices=profile_choices)
    probe_parser.add_argument("--timeout", type=int, help="探测超时秒数，默认使用配置 readiness 超时")
    probe_parser.add_argument("--keep-running", action="store_true", help="探测结束后保留本次启动的虚拟机")
    probe_parser.add_argument("--matrix", action="store_true", help="新运行盘上的受控回退；已有运行盘拒绝；来源候选优先，仍限 BIOS/UEFI × 白名单总线")
    probe_parser.add_argument("--matrix-timeout", type=int, default=90, help="矩阵中每个候选的探测秒数，默认 90")
    probe_parser.add_argument("--matrix-max", type=int, help="只尝试前 N 个候选（用于快速排查）")
    probe_parser.add_argument("--matrix-start", type=int, default=1, help="跳过前 N-1 个候选，从第 N 个开始（用于验证回退路径与定位）")
    probe_parser.add_argument("--apply-matrix-report", help="人工复核后保存当前状态目录中的矩阵命中参数；不升级验证状态")
    probe_parser.add_argument("--review-attempt", type=int, help="显式确认已查看报告中指定待复核候选的截图；仅保存未验收硬件参数")
    probe_parser.add_argument("--confirm-apply", action="store_true", help="确认只固化报告中的白名单固件/总线参数，并保留原配置备份")

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
        "show": cmd_show_display,
        "status": cmd_status,
        "preflight": cmd_preflight,
        "display-diagnose": cmd_display_diagnose,
        "stop": cmd_stop,
        "reset": cmd_reset,
        "deregister": cmd_deregister,
        "remove": cmd_remove_image,
        "health": cmd_health,
        "snapshot": cmd_snapshot,
        "storage": cmd_storage,
        "network": cmd_network,
        "probe": cmd_probe,
        "utm-export": cmd_utm_export,
    }
    package_handlers = {"build": cmd_package_build, "verify": cmd_package_verify}
    content_handlers = {"pack": cmd_content_pack, "verify": cmd_content_verify,
                        "unpack": cmd_content_unpack}
    app_handlers = {"build": cmd_app_build, "verify": cmd_app_verify}
    dist_handlers = {"prepare": cmd_dist_prepare, "verify": cmd_dist_verify,
                     "install": cmd_dist_install, "make-pack": cmd_dist_make_pack}
    try:
        # 纯打包/校验命令不需要运行状态；避免仅执行 package/content 时在默认
        # 状态目录创建 locks/ 等运行时目录，保持该类操作的只读/构建边界。
        if args.command == "package":
            return package_handlers[args.package_command](None, args)  # type: ignore[arg-type]
        if args.command == "content":
            return content_handlers[args.content_command](None, args)  # type: ignore[arg-type]
        if args.command == "app":
            return app_handlers[args.app_command](None, args)  # type: ignore[arg-type]
        if args.command == "update":
            return cmd_update(None, args)  # type: ignore[arg-type]
        if args.command == "dist" and args.dist_command in {"verify", "make-pack"}:
            # verify/make-pack 不写运行状态；不要在默认状态目录创建 locks/。
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
            with manager.operation_lock(f"接入 {args.id}"), import_session(
                    Path(os.environ["CTFLAB_IMPORT_CANCEL_FILE"]) if os.environ.get("CTFLAB_IMPORT_CANCEL_FILE") else None):
                return handlers[args.command](manager, args)
        if args.command == "import":
            with import_session(Path(os.environ["CTFLAB_IMPORT_CANCEL_FILE"])
                                if os.environ.get("CTFLAB_IMPORT_CANCEL_FILE") else None):
                return handlers[args.command](manager, args)
        if args.command == "dist" and args.dist_command == "install":
            # 内容包安装可能做长时间镜像转换：接入与 import 同一套协作取消机制。
            with import_session(Path(os.environ["CTFLAB_IMPORT_CANCEL_FILE"])
                                if os.environ.get("CTFLAB_IMPORT_CANCEL_FILE") else None):
                return dist_handlers[args.dist_command](manager, args)  # type: ignore[arg-type]
        if args.command == "dist":
            return dist_handlers[args.dist_command](manager, args)  # type: ignore[arg-type]
        return handlers[args.command](manager, args)
    except (CTFLabError, InspectionError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
