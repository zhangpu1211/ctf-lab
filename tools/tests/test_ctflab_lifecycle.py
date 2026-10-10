#!/usr/bin/env python3
"""CTFLab 停止/状态一致性的回归测试。"""

from __future__ import annotations

from contextlib import redirect_stdout
from pathlib import Path
import io
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import ctflab  # noqa: E402
from ctflab import CTFLabError, LabManager, main, write_json  # noqa: E402


def start_sleeper(seconds: int = 60) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"])


class GracefulStopTests(unittest.TestCase):
    """stop --graceful 超时后必须保留实例，不做强制断电。"""

    def _write_runtime(self, manager: LabManager, pid: int, log_path: Path) -> None:
        write_json(
            manager.runtime_state_path("kali-arm64"),
            {
                "schema": 1,
                "profile_id": "kali-arm64",
                "pid": pid,
                "qmp_path": str(manager.runtime_dir / "kali-arm64" / "qmp.sock"),
                "log_path": str(log_path),
                "started_at": "2026-09-13T00:00:00+00:00",
            },
        )

    def test_graceful_stop_preserves_instance_when_guest_does_not_shutdown(self) -> None:
        alive = {"pid": 4242}

        def fake_alive(pid: int) -> bool:
            return pid == alive["pid"]

        def fake_kill(pid: int, signum: int) -> None:
            if pid == alive["pid"]:
                alive["pid"] = -1

        with tempfile.TemporaryDirectory() as directory:
            manager = LabManager(Path(directory))
            log = manager.logs_dir / "kali-arm64.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("boot\n", encoding="utf-8")
            self._write_runtime(manager, 4242, log)
            with mock.patch.object(ctflab, "bool_pid_alive", side_effect=fake_alive), \
                    mock.patch.object(ctflab.os, "kill", side_effect=fake_kill), \
                    mock.patch.object(ctflab, "qmp_command", side_effect=FileNotFoundError), \
                    mock.patch.object(ctflab, "GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS", 0.5):
                with self.assertRaises(CTFLabError) as raised:
                    manager.stop(["kali-arm64"], graceful=True)
            self.assertIn("未完成正常关机", str(raised.exception))
            self.assertEqual(alive["pid"], 4242)
            self.assertTrue(manager.runtime_state_path("kali-arm64").exists())

    def test_graceful_stop_continues_after_one_instance_is_preserved(self) -> None:
        # kali 不响应 ACPI（保留），smoke 的 QEMU 已经退出（清态）——两种结果要同时汇报
        alive = {"kali": 4242}

        def fake_alive(pid: int) -> bool:
            return pid in alive.values()

        def fake_kill(pid: int, signum: int) -> None:
            for name, value in list(alive.items()):
                if pid == value:
                    alive[name] = -1

        with tempfile.TemporaryDirectory() as directory:
            manager = LabManager(Path(directory))
            for profile_id, pid in (("kali-arm64", 4242), ("smoke", 5252)):
                log = manager.logs_dir / f"{profile_id}.log"
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_text("boot\n", encoding="utf-8")
                write_json(
                    manager.runtime_state_path(profile_id),
                    {
                        "schema": 1,
                        "profile_id": profile_id,
                        "pid": pid,
                        "qmp_path": str(manager.runtime_dir / profile_id / "qmp.sock"),
                        "log_path": str(log),
                        "started_at": "2026-09-14T00:00:00+00:00",
                    },
                )
            with mock.patch.object(ctflab, "bool_pid_alive", side_effect=fake_alive), \
                    mock.patch.object(ctflab.os, "kill", side_effect=fake_kill), \
                    mock.patch.object(ctflab, "qmp_command", side_effect=FileNotFoundError), \
                    mock.patch.object(ctflab, "GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS", 0.2):
                with self.assertRaises(CTFLabError) as raised:
                    manager.stop(["kali-arm64", "smoke"], graceful=True)
            message = str(raised.exception)
            self.assertIn("kali-arm64", message)      # 未完成关机的实例被保留并报告
            self.assertNotIn("smoke", message)        # 已完成关机的实例不应出现在错误里
            self.assertTrue(manager.runtime_state_path("kali-arm64").exists())
            self.assertFalse(manager.runtime_state_path("smoke").exists())

    def test_plain_stop_force_exits_when_guest_ignores_powerdown(self) -> None:
        alive = {"pid": 4242}

        def fake_alive(pid: int) -> bool:
            return pid == alive["pid"]

        def fake_kill(pid: int, signum: int) -> None:
            if pid == alive["pid"]:
                alive["pid"] = -1

        with tempfile.TemporaryDirectory() as directory:
            manager = LabManager(Path(directory))
            log = manager.logs_dir / "kali-arm64.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("boot\n", encoding="utf-8")
            self._write_runtime(manager, 4242, log)
            with mock.patch.object(ctflab, "bool_pid_alive", side_effect=fake_alive), \
                    mock.patch.object(ctflab.os, "kill", side_effect=fake_kill), \
                    mock.patch.object(ctflab, "qmp_command", side_effect=FileNotFoundError), \
                    mock.patch.object(ctflab, "FORCED_SHUTDOWN_TIMEOUT_SECONDS", 0.2):
                stopped = manager.stop(["kali-arm64"])
            self.assertEqual(stopped, ["kali-arm64"])
            self.assertEqual(alive["pid"], -1)
            self.assertFalse(manager.runtime_state_path("kali-arm64").exists())


class SpiceClientStopOrderTests(unittest.TestCase):
    """停止顺序回归：QEMU 干净退出前必须先断开显示客户端。

    依据 2026-10-05 的九份 QEMU 崩溃报告：QEMU 在 SPICE 客户端仍连接时干净退出
    （ACPI 关机或 QMP quit），spice-server 的 RedClient 销毁路径稳定段错误
    （InputsChannel::release_keys）。runner 的责任是保证客户端先断开。
    """

    def _write_runtime(self, manager: LabManager, pid: int, client_pid: int,
                       log_path: Path) -> None:
        qmp_path = manager.runtime_dir / "kali-arm64" / "qmp.sock"
        qmp_path.parent.mkdir(parents=True, exist_ok=True)
        qmp_path.write_text("", encoding="utf-8")
        write_json(
            manager.runtime_state_path("kali-arm64"),
            {
                "schema": 1,
                "profile_id": "kali-arm64",
                "pid": pid,
                "spice_client_pid": client_pid,
                "qmp_path": str(qmp_path),
                "log_path": str(log_path),
                "started_at": "2026-10-05T00:00:00+00:00",
            },
        )

    def _fixture(self):
        events: list[str] = []
        alive = {"qemu": 4242, "client": 5151}

        def fake_alive(pid: int) -> bool:
            return pid in alive.values()

        def fake_kill(pid: int, signum: int) -> None:
            if pid == alive["qemu"]:
                events.append("qemu-killed")
                alive["qemu"] = -1
            elif pid == alive["client"]:
                events.append("client-terminated")
                alive["client"] = -1

        def fake_qmp(path, command, **kwargs):
            events.append(f"qmp:{command}")
            return {}

        return events, alive, fake_alive, fake_kill, fake_qmp

    def test_plain_stop_disconnects_client_before_qemu_shutdown(self) -> None:
        events, alive, fake_alive, fake_kill, fake_qmp = self._fixture()

        def guest_ignores_acpi(path, command, **kwargs):
            fake_qmp(path, command)
            if command == "quit":
                events.append("qemu-killed")
                alive["qemu"] = -1
            return {}

        with tempfile.TemporaryDirectory() as directory:
            manager = LabManager(Path(directory))
            log = manager.logs_dir / "kali-arm64.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("boot\n", encoding="utf-8")
            self._write_runtime(manager, alive["qemu"], alive["client"], log)
            with mock.patch.object(ctflab, "bool_pid_alive", side_effect=fake_alive), \
                    mock.patch.object(ctflab.os, "kill", side_effect=fake_kill), \
                    mock.patch.object(ctflab, "qmp_command", side_effect=guest_ignores_acpi), \
                    mock.patch.object(ctflab, "FORCED_SHUTDOWN_TIMEOUT_SECONDS", 0.2):
                stopped = manager.stop(["kali-arm64"])
            self.assertEqual(stopped, ["kali-arm64"])
            self.assertIn("client-terminated", events)
            self.assertIn("qmp:system_powerdown", events)
            self.assertIn("qmp:quit", events)
            # 客户端断开必须先于任何 QMP 关机命令，规避 spice-server 销毁崩溃。
            self.assertLess(events.index("client-terminated"),
                            events.index("qmp:system_powerdown"))
            self.assertFalse(manager.runtime_state_path("kali-arm64").exists())

    def test_graceful_stop_keeps_client_until_guest_exits(self) -> None:
        events, alive, fake_alive, fake_kill, fake_qmp = self._fixture()

        def guest_shuts_down(path, command, **kwargs):
            fake_qmp(path, command)
            if command == "system_powerdown":
                events.append("qemu-killed")
                alive["qemu"] = -1
            return {}

        with tempfile.TemporaryDirectory() as directory:
            manager = LabManager(Path(directory))
            log = manager.logs_dir / "kali-arm64.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("boot\n", encoding="utf-8")
            self._write_runtime(manager, alive["qemu"], alive["client"], log)
            with mock.patch.object(ctflab, "bool_pid_alive", side_effect=fake_alive), \
                    mock.patch.object(ctflab.os, "kill", side_effect=fake_kill), \
                    mock.patch.object(ctflab, "qmp_command", side_effect=guest_shuts_down), \
                    mock.patch.object(ctflab, "GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS", 0.5):
                stopped = manager.stop(["kali-arm64"], graceful=True)
            self.assertEqual(stopped, ["kali-arm64"])
            # 优雅路径同样先断客户端（来宾 ACPI 关机快于任何固定等待，延时无法
            # 规避 spice-server 销毁崩溃），再请求 ACPI；不落 QMP quit 强制梯级。
            self.assertEqual(events[0], "client-terminated")
            self.assertIn("qmp:system_powerdown", events)
            self.assertNotIn("qmp:quit", events)


class ResidualNetworkTests(unittest.TestCase):
    def test_stop_all_cleans_network_without_instances(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = LabManager(Path(directory))
            sleeper = start_sleeper()
            try:
                write_json(
                    manager.network_state_path(23499),
                    {"schema": 1, "pid": sleeper.pid, "port": 23499, "leases": {}},
                )
                stopped = manager.stop([], stop_all=True)
                self.assertEqual(stopped, [])
                self.assertIsNone(manager.network_state(23499))
                deadline = time.monotonic() + 5
                while sleeper.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.1)
                self.assertIsNotNone(sleeper.poll())
            finally:
                sleeper.kill()
                sleeper.wait()

    def test_stale_state_and_residual_network_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = LabManager(Path(directory))
            sleeper = start_sleeper()
            try:
                write_json(
                    manager.runtime_state_path("kali-arm64"),
                    {
                        "schema": 1,
                        "profile_id": "kali-arm64",
                        "pid": 999999,
                        "qmp_path": str(manager.runtime_dir / "kali-arm64" / "qmp.sock"),
                        "log_path": str(manager.logs_dir / "kali-arm64.log"),
                        "lab_port": 23499,
                        "started_at": "2026-09-13T00:00:00+00:00",
                    },
                )
                write_json(
                    manager.network_state_path(23499),
                    {"schema": 1, "pid": sleeper.pid, "port": 23499, "leases": {}},
                )
                self.assertEqual(manager.stale_runtime_states(), [("kali-arm64", 999999)])
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main(["--state-dir", directory, "status"])
                text = output.getvalue()
                self.assertEqual(code, 0)
                self.assertIn("状态文件待清理", text)
                self.assertIn("残留实验网", text)
                self.assertIn("23499", text)
                self.assertIn(manager.network_ports(), [[23499]])
            finally:
                sleeper.kill()
                sleeper.wait()


class DoctorOutputTests(unittest.TestCase):
    def test_required_and_optional_hints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = LabManager(Path(directory))
            real_which = ctflab.shutil.which

            def fake_which(name: str):
                if name in {"utmctl", "tesseract"}:
                    return None
                return real_which(name)

            output = io.StringIO()
            with mock.patch.object(ctflab.shutil, "which", side_effect=fake_which), \
                    mock.patch.object(ctflab, "yaml", None), \
                    redirect_stdout(output):
                code = ctflab.cmd_doctor(manager, None)
            text = output.getvalue()
        self.assertEqual(code, 1, "缺少必选 PyYAML 时 doctor 必须返回失败")
        self.assertIn("MISS PyYAML", text)
        self.assertIn("pip install pyyaml", text)
        self.assertNotIn("PyYAML: 未找到（可选", text)
        self.assertIn("OPT  utmctl", text)
        self.assertIn("OPT  Tesseract OCR", text)
        self.assertIn("未安装时截图分类降级为人工复核", text)


class RemoveImageTests(unittest.TestCase):
    """remove PROFILE：删除导入数据，带运行守卫与幂等拒绝。"""

    def test_remove_deletes_image_and_instance(self) -> None:
        import json
        with tempfile.TemporaryDirectory() as state_dir:
            manager = LabManager(Path(state_dir))
            image_dir = manager.images_dir / "smoke"
            image_dir.mkdir(parents=True)
            (image_dir / "image.json").write_text(json.dumps({"schema": 1}), encoding="utf-8")
            (image_dir / "base-abc.qcow2").write_bytes(b"base")
            instance = manager.runtime_dir / "smoke"
            instance.mkdir(parents=True)
            (instance / "overlay.qcow2").write_bytes(b"overlay")
            manager.remove_image("smoke")
            self.assertFalse(image_dir.exists(), "images 目录应删除")
            self.assertFalse(instance.exists(), "runtime 实例目录应删除")

    def test_remove_refuses_running_and_missing(self) -> None:
        import json
        import os
        with tempfile.TemporaryDirectory() as state_dir:
            manager = LabManager(Path(state_dir))
            with self.assertRaisesRegex(ctflab.CTFLabError, "没有已导入的镜像数据"):
                manager.remove_image("smoke")
            image_dir = manager.images_dir / "smoke"
            image_dir.mkdir(parents=True)
            (image_dir / "image.json").write_text("{}", encoding="utf-8")
            run_path = manager.runtime_state_path("smoke")
            run_path.parent.mkdir(parents=True, exist_ok=True)
            run_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
            with self.assertRaisesRegex(ctflab.CTFLabError, "正在运行"):
                manager.remove_image("smoke")


if __name__ == "__main__":
    unittest.main()
