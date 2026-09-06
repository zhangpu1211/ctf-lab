#!/usr/bin/env python3
"""CTFLab 第一阶段本地运行器。

这是一个面向 macOS Apple Silicon 的轻量 MVP：基础镜像只读导入，启动时
创建 qcow2 overlay，并用 QEMU 管理 ARM64 Kali 与 x86_64 靶机的生命周期。
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
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

try:
    import yaml
except ImportError:  # pragma: no cover - 在不含 PyYAML 的分发环境中给出清晰提示
    yaml = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = PROJECT_ROOT / "tools" / "ctflab_profiles"
DEFAULT_STATE_DIR = Path.home() / "Library" / "Application Support" / "CTFLab"
QEMU_X86_NAMES = ("qemu-system-x86_64",)
QEMU_ARM_NAMES = ("qemu-system-aarch64",)
PROFILE_ALIASES = {"kali": "kali-arm64"}
NETWORK_SCRIPT = PROJECT_ROOT / "tools" / "ctflab_network.py"


class CTFLabError(RuntimeError):
    """用户可理解的运行错误。"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def which_any(names: Iterable[str]) -> str | None:
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


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
    path = shutil.which("qemu-img")
    if not path:
        raise CTFLabError("未找到 qemu-img，请先安装 QEMU（brew install qemu）。")
    return path


def qemu_info(path: Path) -> dict[str, Any]:
    result = run_command([qemu_img_path(), "info", "--output=json", str(path)])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CTFLabError(f"qemu-img info 返回了无法解析的内容：{path}") from exc


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


class LabManager:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir.expanduser().resolve()
        self.images_dir = self.state_dir / "images"
        self.runtime_dir = self.state_dir / "runtime"
        self.logs_dir = self.state_dir / "logs"
        self.pcap_dir = self.state_dir / "pcap"
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

    def image_state(self, profile_id: str) -> dict[str, Any] | None:
        return read_json(self.image_state_path(profile_id))

    def runtime_state(self, profile_id: str) -> dict[str, Any] | None:
        return read_json(self.runtime_state_path(profile_id))

    def network_state(self, lab_port: int) -> dict[str, Any] | None:
        return read_json(self.network_state_path(lab_port))

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

    def import_image(self, profile_id: str, source_arg: str) -> dict[str, Any]:
        with self.operation_lock(f"导入 {profile_id}"):
            return self._import_image_unlocked(profile_id, source_arg)

    def _import_image_unlocked(self, profile_id: str, source_arg: str) -> dict[str, Any]:
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        profile = load_profile(profile_id)
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
            existing = self.image_state(profile_id)
            if (
                existing
                and existing.get("source_sha256") == source_hash
                and Path(str(existing.get("base_path", ""))).exists()
            ):
                # 同一来源的重复导入必须是幂等的，尤其不能把已验证的来宾修复基盘
                # 悄悄切回最初转换出的未修复基盘。
                return existing
            info = qemu_info(source_for_convert)
            source_format = str(info.get("format") or "")
            if not source_format:
                raise CTFLabError(f"无法识别镜像格式：{source_for_convert}")
            image_dir = self.images_dir / profile_id
            image_dir.mkdir(parents=True, exist_ok=True)
            base_path = image_dir / f"base-{source_hash[:12]}.qcow2"
            if not base_path.exists():
                run_command([qemu_img_path(), "convert", "-f", source_format, "-O", "qcow2", str(source_for_convert), str(base_path)], capture=False)
            destination_info = qemu_info(base_path)
            state = {
                "schema": 1,
                "profile_id": profile_id,
                "profile_path": str(profile_path(profile_id)),
                "source_path": str(source),
                "source_sha256": source_hash,
                "source_format": source_format,
                "base_path": str(base_path),
                "virtual_size": destination_info.get("virtual-size"),
                "imported_at": now_iso(),
                "guest": profile.get("guest", {}),
            }
            write_json(self.image_state_path(profile_id), state)
            return state
        finally:
            if temporary_dir is not None:
                temporary_dir.cleanup()

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

    def qemu_command(self, profile_id: str, profile: dict[str, Any], overlay: Path, lab_port: int, headless: bool) -> tuple[list[str], dict[str, int]]:
        guest = profile.get("guest", {})
        disk = profile.get("disk", {})
        network = profile.get("network", {})
        architecture = guest.get("architecture", "x86_64")
        if architecture == "aarch64":
            qemu = which_any(QEMU_ARM_NAMES)
            if not qemu:
                raise CTFLabError("未找到 qemu-system-aarch64，请先安装 QEMU。")
            command = [
                qemu,
                "-name", f"CTFLab-{profile_id}",
                "-machine", str(guest.get("machine", "virt")),
                "-accel", "hvf",
                "-cpu", "host",
                "-smp", str(guest.get("cpus", 2)),
                "-m", str(guest.get("memory_mb", 4096)),
                "-drive", f"file={overlay},if=none,format=qcow2,id=disk0",
                "-device", "virtio-blk-pci,drive=disk0",
                "-device", "virtio-gpu-pci",
            ]
            firmware = find_firmware("edk2-aarch64-code.fd")
            if guest.get("firmware") == "uefi" and firmware:
                command += ["-bios", str(firmware)]
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
        mgmt_netdev = "user,id=mgmt,restrict=on"
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
        if headless:
            command += ["-display", "none", "-serial", "mon:stdio"]
        else:
            command += ["-display", "cocoa"]
        qmp_path = self.runtime_dir / profile_id / "qmp.sock"
        if qmp_path.exists():
            qmp_path.unlink()
        command += ["-qmp", f"unix:{qmp_path},server=on,wait=off"]
        return command, host_forwards

    def run(self, profile_ids: list[str], headless: bool = False, pcap: bool = False) -> list[dict[str, Any]]:
        with self.operation_lock("启动 " + ",".join(profile_ids)):
            return self._run_unlocked(profile_ids, headless=headless, pcap=pcap)

    def _run_unlocked(self, profile_ids: list[str], headless: bool = False, pcap: bool = False) -> list[dict[str, Any]]:
        profile_ids = list(dict.fromkeys(PROFILE_ALIASES.get(profile_id, profile_id) for profile_id in profile_ids))
        for profile_id in profile_ids:
            load_profile(profile_id)
        running = self.running_states()
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
            profile = load_profile(profile_id)
            overlay = self.ensure_overlay(profile_id)
            command, host_forwards = self.qemu_command(profile_id, profile, overlay, lab_port, headless)
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
                "headless": headless,
            }
            write_json(self.runtime_state_path(profile_id), state)
            started.append(state)
        return started

    def stop(self, profile_ids: list[str], stop_all: bool = False) -> list[str]:
        description = "停止全部实例" if stop_all else "停止 " + ",".join(profile_ids)
        with self.operation_lock(description):
            return self._stop_unlocked(profile_ids, stop_all=stop_all)

    def _stop_unlocked(self, profile_ids: list[str], stop_all: bool = False) -> list[str]:
        targets = available_profiles() if stop_all else [PROFILE_ALIASES.get(profile_id, profile_id) for profile_id in profile_ids]
        stopped: list[str] = []
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
                deadline = time.monotonic() + 3
                while bool_pid_alive(pid) and time.monotonic() < deadline:
                    time.sleep(0.25)
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
            if qmp_path.exists():
                qmp_path.unlink()
            state_path = self.runtime_state_path(profile_id)
            if state_path.exists():
                state_path.unlink()
            stopped.append(profile_id)
        remaining = self.running_states()
        if not remaining:
            for port in stopped_ports:
                self.stop_network(port)
        return stopped

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

    def probe(self, profile_id: str, *, timeout_seconds: int | None = None, keep_running: bool = False) -> dict[str, Any]:
        """启动候选配置并收集 QMP、显示、DHCP 与协议证据。

        显示活动只说明画面不是全黑，不能自动区分登录界面、内核报错和 UEFI Shell。
        因此候选配置始终保留人工复核标记。
        """
        profile_id = PROFILE_ALIASES.get(profile_id, profile_id)
        profile = load_profile(profile_id)
        existing = self.runtime_state(profile_id)
        already_running = bool(existing and bool_pid_alive(int(existing.get("pid", 0))))
        started_by_probe = not already_running
        if started_by_probe:
            self.run([profile_id], headless=True)
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
                "screenshot_path": screenshot_path,
                "health": health,
                "verdict": verdict,
                "requires_human_review": candidate_profile or verdict != "service_ready",
                "errors": list(dict.fromkeys(errors))[-20:],
                "verification": {
                    "boot_process": process_running,
                    "display_activity": bool(display.get("active")),
                    "network": network_ready,
                    "service": protocol_ready,
                },
                "note": "非全黑截图可能是 UEFI Shell 或错误画面；候选配置需人工查看截图后才能标记已验证。",
            }
            write_json(report_path, report)
            report["report_path"] = str(report_path)
            return report
        finally:
            if started_by_probe and not keep_running:
                self.stop([profile_id])


def cmd_doctor(manager: LabManager, _args: argparse.Namespace) -> int:
    checks = [
        ("宿主系统", f"{platform.system()} {platform.machine()}" if platform.system() == "Darwin" and platform.machine() in {"arm64", "aarch64"} else None),
        ("python", sys.executable),
        ("qemu-img", shutil.which("qemu-img")),
        ("qemu-system-x86_64", which_any(QEMU_X86_NAMES)),
        ("qemu-system-aarch64", which_any(QEMU_ARM_NAMES)),
        ("utmctl", shutil.which("utmctl")),
        ("PyYAML", "available" if yaml is not None else None),
        ("ARM64 UEFI", str(find_firmware("edk2-aarch64-code.fd")) if find_firmware("edk2-aarch64-code.fd") else None),
    ]
    failed = False
    for name, value in checks:
        ok = bool(value)
        print(f"{'OK  ' if ok else 'MISS'} {name}: {value or '未找到'}")
        failed |= not ok
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
    state = manager.import_image(args.profile, args.source)
    print(f"导入完成：{args.profile}")
    print(f"基础镜像：{state['base_path']}")
    print(f"SHA-256：{state['source_sha256']}")
    return 0


def cmd_run(manager: LabManager, args: argparse.Namespace) -> int:
    states = manager.run(args.profiles, headless=args.headless, pcap=args.pcap)
    for state in states:
        forwards = ", ".join(f"{name}=127.0.0.1:{port}" for name, port in state.get("host_forwards", {}).items()) or "无主机端口映射"
        print(f"已启动 {state['profile_id']}（PID {state['pid']}，实验网 TCP {state['lab_port']}；{forwards}）")
    pcap_paths = {str(state.get("pcap_path")) for state in states if state.get("pcap_path")}
    for pcap_path in sorted(pcap_paths):
        print(f"PCAP：{pcap_path}")
    return 0


def cmd_status(manager: LabManager, _args: argparse.Namespace) -> int:
    running = {state["profile_id"]: state for state in manager.running_states()}
    shown_networks: set[int] = set()
    for profile_id in available_profiles():
        state = running.get(profile_id)
        if not state:
            continue
        print(f"{profile_id}: running PID={state['pid']} lab=tcp://127.0.0.1:{state['lab_port']} log={state['log_path']}")
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
    if not running:
        print("没有正在运行的 CTFLab 实例。")
    return 0


def cmd_stop(manager: LabManager, args: argparse.Namespace) -> int:
    stopped = manager.stop(args.profiles, stop_all=args.all)
    print("已停止：" + (", ".join(stopped) if stopped else "没有运行中的实例"))
    return 0


def cmd_reset(manager: LabManager, args: argparse.Namespace) -> int:
    manager.reset(args.profile, force=args.force)
    print(f"已重置 {args.profile}：下次启动会从基础镜像创建全新 overlay。")
    return 0


def cmd_health(manager: LabManager, args: argparse.Namespace) -> int:
    results = manager.health(args.profile)
    failed = False
    for result in results:
        status = "OK" if result["ok"] is True else "WAIT" if result["ok"] is None else "FAIL"
        print(f"{status:4} {result['name']}: {result['detail']}")
        failed |= result["ok"] is False
    return 1 if failed else 0


def cmd_probe(manager: LabManager, args: argparse.Namespace) -> int:
    report = manager.probe(args.profile, timeout_seconds=args.timeout, keep_running=args.keep_running)
    print(f"探测结论：{report['verdict']}")
    display = report.get("display", {})
    print(f"显示活动：{'是' if display.get('active') else '否'}（{display.get('detail')}）")
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

    run_parser = subparsers.add_parser("run", help="启动一个或多个实验节点")
    run_parser.add_argument("profiles", nargs="+", choices=profile_choices)
    run_parser.add_argument("--headless", action="store_true", help="不打开图形窗口，日志写入 logs/")
    run_parser.add_argument("--pcap", action="store_true", help="记录隔离实验网的 Ethernet PCAP")

    subparsers.add_parser("status", help="查看运行状态")

    stop_parser = subparsers.add_parser("stop", help="优雅停止实例")
    # 这里不在 argparse 层设置 choices，否则 Python 3.10 在“空位置参数 + --all”时
    # 会把空列表本身当成一个候选值；具体配置名在执行阶段校验。
    stop_parser.add_argument("profiles", nargs="*", metavar="PROFILE")
    stop_parser.add_argument("--all", action="store_true", help="停止所有实例")

    reset_parser = subparsers.add_parser("reset", help="删除运行 overlay，恢复到基础镜像")
    reset_parser.add_argument("profile", choices=profile_choices)
    reset_parser.add_argument("--force", action="store_true", help="运行中也先停止再重置")

    health_parser = subparsers.add_parser("health", help="检查进程和已配置的端口")
    health_parser.add_argument("profile", choices=profile_choices)

    probe_parser = subparsers.add_parser("probe", help="启动候选并收集 QMP 截图、DHCP 和服务证据")
    probe_parser.add_argument("profile", choices=profile_choices)
    probe_parser.add_argument("--timeout", type=int, help="探测超时秒数，默认使用配置 readiness 超时")
    probe_parser.add_argument("--keep-running", action="store_true", help="探测结束后保留本次启动的虚拟机")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    manager = LabManager(args.state_dir)
    handlers = {
        "doctor": cmd_doctor,
        "list": cmd_list,
        "inspect": cmd_inspect,
        "onboard": cmd_onboard,
        "import": cmd_import,
        "run": cmd_run,
        "status": cmd_status,
        "stop": cmd_stop,
        "reset": cmd_reset,
        "health": cmd_health,
        "probe": cmd_probe,
    }
    try:
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
        return handlers[args.command](manager, args)
    except CTFLabError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
