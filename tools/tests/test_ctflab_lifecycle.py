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


if __name__ == "__main__":
    unittest.main()
