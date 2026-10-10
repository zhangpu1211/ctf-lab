#!/usr/bin/env python3
"""TCP 回退模式（路径 B）正向 E2E——环境门控，默认跳过。

运行条件（全部满足才执行）：
- 环境变量 ``CTFLAB_SPICE_TCP_E2E=1``；
- ``CTFLAB_SPICE_TCP_E2E_APP`` 指向含受控 QEMU/固件的 CTFLab.app（提供 QEMU 与
  PATH 注入）；
- 来源状态目录中已导入 ``kali-arm64`` 基盘（可用 ``CTFLAB_SPICE_TCP_E2E_STATE_DIR``
  覆盖）；只读取资产登记，运行在新建独立目录，清理只停止本测试节点；
- 本机 clang + pkg-config + spice-client-gtk-3.0 可用（按验证记录中的可复现
  构建命令现场编译受控客户端）；
- 认证探针需要 ``cryptography``（缺失时整项 E2E 跳过，不省略认证验收）。

每轮（``CTFLAB_SPICE_TCP_E2E_ROUNDS`` 轮，默认 3）断言：
1. runner 全流程 ``run --display spice --spice-listen tcp --clipboard`` 后，受控
   客户端在 127.0.0.1 受控端口建立通道（端口存在 ESTABLISHED 连接）；
2. 无新增 ``Invalid password``（正向认证通过）；
3. ticket 明文不出现在 QEMU 命令行、运行状态 JSON、QEMU 日志与客户端日志；
4. QEMU 命令只绑 127.0.0.1（无 0.0.0.0）；
5. 第 1 轮执行负向探针：错误 ticket 得到 PERMISSION_DENIED(7)。

范围：本用例验证认证、显示通道和停止清理，不等待来宾图形登录；display-ready
不能证明完整引导、桌面剪贴板传输、动态分辨率或输入坐标已通过。

用法：
    CTFLAB_SPICE_TCP_E2E=1 \
    CTFLAB_SPICE_TCP_E2E_APP=/path/to/CTFLab.app \
    /opt/miniconda3/bin/python3 -m unittest tools.tests.test_ctflab_spice_tcp_e2e -v
"""

from __future__ import annotations

import json
import hashlib
import os
import pathlib
import shutil
import secrets
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

APP = os.environ.get("CTFLAB_SPICE_TCP_E2E_APP", "")
STATE_DIR = os.environ.get("CTFLAB_SPICE_TCP_E2E_STATE_DIR",
                           str(pathlib.Path.home() / "Library" / "Application Support" / "CTFLab"))
ROUNDS = max(1, int(os.environ.get("CTFLAB_SPICE_TCP_E2E_ROUNDS", "3")))

try:
    from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
    from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402
    HAVE_CRYPTO = True
except ImportError:  # pragma: no cover - 环境相关
    HAVE_CRYPTO = False


def _skip_reason() -> str:
    if os.environ.get("CTFLAB_SPICE_TCP_E2E") != "1":
        return "需要 CTFLAB_SPICE_TCP_E2E=1"
    if not APP or not pathlib.Path(APP).is_dir():
        return "需要 CTFLAB_SPICE_TCP_E2E_APP 指向 CTFLab.app"
    if not (pathlib.Path(STATE_DIR) / "images" / "kali-arm64").is_dir():
        return "状态目录未导入 kali-arm64 基盘"
    if shutil.which("clang") is None or shutil.which("pkg-config") is None:
        return "需要 clang 与 pkg-config 现场编译受控客户端"
    if not HAVE_CRYPTO:
        return "需要 cryptography 验证正/负向认证"
    return ""


SKIP_REASON = _skip_reason()


def qemu_log_invalids(log_path: pathlib.Path) -> int:
    try:
        return log_path.read_text(errors="replace").count("Invalid password")
    except OSError:
        return 0


def wait_for_listener(port: int, deadline_seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def recv_exact(connection: socket.socket, length: int) -> bytes:
    """TCP 分片不能改变协议解析；断开或超时均不代表认证成功。"""
    result = bytearray()
    while len(result) < length:
        chunk = connection.recv(length - len(result))
        if not chunk:
            raise AssertionError("认证完成前连接已关闭")
        result.extend(chunk)
    return bytes(result)


def raw_ticket_auth(port: int, password: bytes) -> int:
    """原始 SPICE ticket 认证探针（对齐 spice-gtk 0.42 流程）。

    返回服务器明确的认证结果：0=接受，7=PERMISSION_DENIED（口令被拒）。
    """
    cap_selection = 1 << 0   # SPICE_COMMON_CAP_PROTOCOL_AUTH_SELECTION
    cap_auth_spice = 1 << 1  # SPICE_COMMON_CAP_AUTH_SPICE
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    try:
        caps = [cap_auth_spice | cap_selection]
        body = struct.pack("<IBBIII", 0, 1, 0, len(caps), 0, 18)
        body += b"".join(struct.pack("<I", c) for c in caps)
        s.sendall(struct.pack("<IIII", int.from_bytes(b"REDQ", "little"), 2, 2, len(body)) + body)
        header = recv_exact(s, 16)
        magic, major, minor, size = struct.unpack("<IIII", header)
        if magic != int.from_bytes(b"REDQ", "little") or major != 2 or minor != 2:
            raise AssertionError("无效 SPICE 链路头")
        if not 178 <= size <= 65536:
            raise AssertionError("无效 SPICE 链路回复长度")
        data = recv_exact(s, size)
        error = struct.unpack("<I", data[:4])[0]
        if error != 0:
            raise AssertionError(f"链路错误 {error}")
        pub_key = data[4:4 + 162]  # SpiceLinkReply: error u32 + pub_key[162]
        public_key = serialization.load_der_public_key(pub_key)
        assert isinstance(public_key, rsa.RSAPublicKey)
        plaintext = password + b"\x00"  # strlen + 1，与 spice-gtk 一致
        encrypted = public_key.encrypt(plaintext, padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA1()), algorithm=hashes.SHA1(), label=None))
        s.sendall(struct.pack("<I", 1))  # SPICE_LINK_AUTH_MECHANISM_SPICE
        s.sendall(encrypted)
        s.settimeout(3)
        return struct.unpack("<I", recv_exact(s, 4))[0]
    finally:
        s.close()


class TicketProtocolTests(unittest.TestCase):
    def test_fragmented_receive(self):
        connection = mock.Mock()
        connection.recv.side_effect = [b"\x00", b"\x00\x00", b"\x00"]
        self.assertEqual(recv_exact(connection, 4), b"\x00" * 4)

    def test_eof_is_not_auth_success(self):
        connection = mock.Mock()
        connection.recv.side_effect = [b"\x00", b""]
        with self.assertRaisesRegex(AssertionError, "连接已关闭"):
            recv_exact(connection, 4)

    def test_timeout_is_not_auth_success(self):
        connection = mock.Mock()
        connection.recv.side_effect = socket.timeout("no reply")
        with self.assertRaises(socket.timeout):
            recv_exact(connection, 4)

    @unittest.skipUnless(HAVE_CRYPTO, "需要 cryptography 验证 ticket 链路")
    def test_auth_caps_mechanism_and_explicit_result(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        der = key.public_key().public_bytes(serialization.Encoding.DER,
                                           serialization.PublicFormat.SubjectPublicKeyInfo)
        self.assertEqual(len(der), 162)
        reply = struct.pack("<I", 0) + der + struct.pack("<III", 1, 0, 178)
        reply += struct.pack("<I", 3)
        header = struct.pack("<IIII", int.from_bytes(b"REDQ", "little"), 2, 2, len(reply))
        for result in (0, 7):
            with self.subTest(result=result):
                stream = bytearray(header + reply + struct.pack("<I", result))
                sent = []
                connection = mock.Mock()
                def read(length):
                    chunk = bytes(stream[:min(length, 3)])
                    del stream[:len(chunk)]
                    return chunk
                connection.recv.side_effect = read
                connection.sendall.side_effect = sent.append
                with mock.patch("socket.create_connection", return_value=connection):
                    self.assertEqual(raw_ticket_auth(12345, b"sample"), result)
                self.assertEqual(struct.unpack("<I", sent[0][-4:])[0], 3)
                self.assertEqual(struct.unpack("<I", sent[1])[0], 1)
                plaintext = key.decrypt(sent[2], padding.OAEP(
                    mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None))
                self.assertEqual(plaintext, b"sample\x00")
                connection.close.assert_called_once()

    @unittest.skipUnless(HAVE_CRYPTO and os.environ.get("CTFLAB_SPICE_AUTH_QEMU"),
                         "需要 CTFLAB_SPICE_AUTH_QEMU 指向支持 SPICE 的 QEMU")
    def test_real_qemu_ticket_handshake_without_guest_or_desktop(self):
        """真实服务器认证，不启动来宾磁盘、不显示窗口、不访问用户状态目录。"""
        qemu = os.environ["CTFLAB_SPICE_AUTH_QEMU"]
        with tempfile.TemporaryDirectory(prefix="ctflab-spice-auth-") as directory:
            root = pathlib.Path(directory)
            ticket = secrets.token_urlsafe(32).encode()
            ticket_file = root / "ticket"
            with ticket_file.open("xb") as handle:
                os.chmod(ticket_file, 0o600)
                handle.write(ticket)
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            command = [
                qemu, "-machine", "none,accel=tcg", "-S", "-display", "none",
                "-nodefaults", "-monitor", "none", "-serial", "none", "-nic", "none",
                "-object", f"secret,id=ticket,file={ticket_file},format=raw",
                "-spice", f"addr=127.0.0.1,port={port},password-secret=ticket",
            ]
            with (root / "qemu.log").open("wb") as log:
                process = subprocess.Popen(command, stdout=log, stderr=log)
                try:
                    self.assertTrue(wait_for_listener(port, 10), "服务器未就绪")
                    for _ in range(3):
                        self.assertEqual(raw_ticket_auth(port, ticket), 0)
                        self.assertEqual(raw_ticket_auth(port, b"WRONG-TICKET"), 7)
                    self.assertIsNone(process.poll())
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            self.assertNotIn(ticket, (root / "qemu.log").read_bytes())


@unittest.skipIf(SKIP_REASON, SKIP_REASON)
class SpiceTcpPositiveE2E(unittest.TestCase):
    """可重复的正向 TCP E2E：认证、隔离与负向拒绝。"""

    @classmethod
    def setUpClass(cls) -> None:
        # macOS 的 UNIX socket 路径上限为 104 字节，默认 /var/folders 路径过长。
        cls.tmp = tempfile.TemporaryDirectory(prefix="ctflab-tcp-", dir="/private/tmp")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.app = pathlib.Path(APP)
        source_state = pathlib.Path(STATE_DIR)
        cls.state_dir = pathlib.Path(cls.tmp.name) / "state"
        cls.runtime_bin = cls.app / "Contents/Resources/runtime/bin"
        cls.client_bin = pathlib.Path(cls.tmp.name) / "ctflab-spicy-tcp-e2e"
        pkg_result = subprocess.run(
            ["pkg-config", "--cflags", "--libs", "spice-client-gtk-3.0", "gtk+-3.0"],
            capture_output=True, text=True)
        if pkg_result.returncode != 0:
            raise unittest.SkipTest(f"pkg-config 不可用：{pkg_result.stderr.strip()}")
        build = subprocess.run(
            ["clang", "-Wall", "-Wextra", "-Werror", "-mmacosx-version-min=26.0",
             str(TOOLS_DIR / "spice_client" / "ctflab_spicy.c"),
             "-o", str(cls.client_bin), *pkg_result.stdout.split()],
            capture_output=True, text=True)
        if build.returncode != 0:
            raise AssertionError(f"受控客户端构建失败：{build.stderr[-800:]}")
        saved_env = {key: os.environ.get(key) for key in
                     ("PATH", "CTFLAB_SPICE_CLIENT", "CTFLAB_RUNTIME_ROOT")}
        def restore_env():
            for key, value in saved_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        cls.addClassCleanup(restore_env)
        cls._old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{cls.runtime_bin}:{cls._old_path}"
        os.environ["CTFLAB_SPICE_CLIENT"] = str(cls.client_bin)
        os.environ["CTFLAB_RUNTIME_ROOT"] = str(cls.runtime_bin.parent)
        import ctflab  # noqa: E402
        cls.ctflab = ctflab
        cls.manager = ctflab.LabManager(cls.state_dir)
        # 只读取已登记的基础资产；overlay、NVRAM 副本和运行状态全部落在独立目录。
        record = source_state / "images/kali-arm64/image.json"
        destination = cls.manager.image_state_path("kali-arm64")
        destination.parent.mkdir(parents=True, exist_ok=True)
        metadata = json.loads(record.read_text())
        cls.original_hashes = {}
        for key, hash_key in (("base_path", "base_sha256"),
                              ("uefi_vars_path", "uefi_vars_sha256")):
            path = pathlib.Path(metadata[key])
            digest = cls._hash(path)
            if digest != metadata.get(hash_key):
                raise AssertionError(f"{key} 登记哈希不匹配")
            cls.original_hashes[path] = digest
        destination.write_text(json.dumps(metadata))
        # 清理仅针对本测试创建的节点，从不对用户状态执行 stop --all。
        cls.addClassCleanup(cls._verify_original_hashes)
        cls.addClassCleanup(cls.manager.stop, ["kali-arm64"])

    @staticmethod
    def _hash(path):
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @classmethod
    def _verify_original_hashes(cls):
        for path, expected in cls.original_hashes.items():
            if cls._hash(path) != expected:
                raise AssertionError("E2E 原始资产发生变化")

    def test_positive_tcp_repeated_rounds(self) -> None:
        for round_index in range(1, ROUNDS + 1):
            with self.subTest(round=round_index):
                self.manager.stop(["kali-arm64"])
                time.sleep(1)
                qemu_log = self.state_dir / "logs" / "kali-arm64.log"
                before_invalid = qemu_log_invalids(qemu_log)
                prior_client_log = self.manager.logs_dir / "kali-arm64-spice-client.log"
                client_log_start = prior_client_log.stat().st_size if prior_client_log.exists() else 0
                states = self.manager.run(["kali-arm64"], display="spice",
                                          spice_listen="tcp", clipboard=True)
                state = states[0]
                try:
                    self.assertEqual(state["display_backend"], "spice")
                    self.assertEqual(state["spice_listen"], "tcp")
                    endpoint = state["spice_endpoint"]
                    self.assertTrue(endpoint.startswith("spice://127.0.0.1:"))
                    port = int(endpoint.rsplit(":", 1)[1])
                    command_text = " ".join(state["command"])
                    self.assertNotIn("0.0.0.0", command_text)
                    ticket = (self.state_dir / "runtime/kali-arm64/spice/ticket").read_bytes()
                    # 隔离断言：ticket 明文不进命令行与状态 JSON
                    self.assertNotIn(ticket, command_text.encode())
                    self.assertNotIn(ticket.decode(), json.dumps(state))
                    self.assertTrue(wait_for_listener(port, 20), "QEMU 未在受控端口监听")
                    deadline = time.monotonic() + 40
                    established = 0
                    while time.monotonic() < deadline:
                        out = subprocess.run(["lsof", "-iTCP:%d" % port, "-P", "-n"],
                                             capture_output=True, text=True).stdout
                        established = out.count("ESTABLISHED")
                        if established > 0:
                            break
                        time.sleep(0.5)
                    self.assertGreater(established, 0, "客户端未在 TCP 端口建立通道")
                    # ESTABLISHED 只证明传输层；还必须收到显示通道 ready。
                    client_log = pathlib.Path(state.get("spice_client_log_path", ""))
                    deadline = time.monotonic() + 40
                    ready = False
                    while time.monotonic() < deadline:
                        if client_log.is_file():
                            client_text = client_log.read_bytes()[client_log_start:].decode(errors="replace")
                            ready = "CTFLAB_SPICE_STATE display-ready=1" in client_text
                        if ready:
                            break
                        time.sleep(0.2)
                    self.assertTrue(ready, "客户端未建立就绪的显示通道")
                    self.assertTrue(self.ctflab.bool_pid_alive(state["spice_client_pid"]),
                                    "客户端已退出，不能用旧日志认定就绪")
                    self.assertEqual(qemu_log_invalids(qemu_log), before_invalid,
                                     "出现新的 Invalid password")
                    state_now = json.loads(
                        (self.state_dir / "runtime/kali-arm64/run.json").read_text())
                    client_log = pathlib.Path(state_now.get("spice_client_log_path", ""))
                    if client_log.is_file():
                        self.assertNotIn(ticket.decode(),
                                         client_log.read_text(errors="replace"))
                    # 负向（第 1 轮）：错误 ticket 被拒
                    if round_index == 1 and HAVE_CRYPTO:
                        self.assertEqual(raw_ticket_auth(port, ticket), 0,
                                         "正确 ticket 必须收到明确的成功应答")
                        self.assertEqual(raw_ticket_auth(port, b"CTFLAB-WRONG-TICKET"), 7,
                                         "错误 ticket 应得到 PERMISSION_DENIED")
                finally:
                    self.manager.stop(["kali-arm64"])
                    time.sleep(1)


if __name__ == "__main__":
    unittest.main()
