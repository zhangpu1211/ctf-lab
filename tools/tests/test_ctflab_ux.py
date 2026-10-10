"""体验优化契约：资源、显示恢复与恢复点 JSON（不操作用户虚拟机）。"""
import argparse
import contextlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab


class UXTests(unittest.TestCase):
    def test_display_status_uses_latest_ready_event(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "client.log"
            state = {"display_backend": "spice", "spice_client_pid": 123,
                     "spice_client_log_path": str(log)}
            for events, ready in [("", False), ("1\n0", False),
                                  ("0\n1", True), ("1", True)]:
                log.write_text("\n".join("CTFLAB_SPICE_STATE display-ready=" + value
                                         for value in events.splitlines()))
                with mock.patch.object(ctflab, "bool_pid_alive", return_value=True):
                    self.assertEqual(ctflab.spice_client_summary(state)["display_ready"], ready)

    def test_display_status_does_not_trust_dead_or_unrelated_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "client.log"
            state = {"display_backend": "spice", "spice_client_pid": 123,
                     "spice_client_log_path": str(log)}
            log.write_text("CTFLAB_SPICE_STATE display-ready=1\n")
            with mock.patch.object(ctflab, "bool_pid_alive", return_value=False):
                self.assertFalse(ctflab.spice_client_summary(state)["display_ready"])
            with mock.patch.object(ctflab, "bool_pid_alive", return_value=True):
                log.write_text("说明 display-ready=1\nCTFLAB_SPICE_STATE display-ready=10\n")
                self.assertFalse(ctflab.spice_client_summary(state)["display_ready"])
                log.unlink()
                self.assertFalse(ctflab.spice_client_summary(state)["display_ready"])

    def test_zombie_pid_is_not_running(self):
        with mock.patch.object(ctflab.sys, "platform", "darwin"), \
                mock.patch.object(ctflab.os, "kill"), \
                mock.patch.object(ctflab.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="Z+\n")):
            self.assertFalse(ctflab.bool_pid_alive(123))

    def test_live_or_unavailable_status_preserves_pid(self):
        for result in (mock.Mock(returncode=0, stdout="Ss\n"),
                       mock.Mock(returncode=1, stdout="")):
            with mock.patch.object(ctflab.sys, "platform", "darwin"), \
                    mock.patch.object(ctflab.os, "kill"), \
                    mock.patch.object(ctflab.subprocess, "run", return_value=result):
                self.assertTrue(ctflab.bool_pid_alive(123))

    def test_pid_status_timeout_is_conservative(self):
        with mock.patch.object(ctflab.sys, "platform", "darwin"), \
                mock.patch.object(ctflab.os, "kill"), \
                mock.patch.object(ctflab.subprocess, "run", side_effect=ctflab.subprocess.TimeoutExpired("ps", 1)):
            self.assertTrue(ctflab.bool_pid_alive(123))

    def test_health_checks_actual_runtime_forward_not_default_port(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ctflab.LabManager(Path(directory))
            connection = mock.MagicMock()
            connection.__enter__.return_value.recv.return_value = b"SSH-2.0-TEST\r\n"
            state = {"pid": 123, "host_forwards": {"ssh": 54321}}
            with mock.patch.object(manager, "runtime_state", return_value=state), \
                    mock.patch.object(ctflab, "bool_pid_alive", return_value=True), \
                    mock.patch.object(manager, "dhcp_lease", return_value="192.168.242.10"), \
                    mock.patch.object(ctflab.socket, "create_connection", return_value=connection) as connect:
                result = manager.health("kali-arm64")
            self.assertEqual(connect.call_args.args[0], ("127.0.0.1", 54321))
            self.assertTrue(next(item for item in result if item["name"] == "ssh:22")["ok"])

    def test_health_missing_runtime_forward_does_not_probe_old_port(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ctflab.LabManager(Path(directory))
            with mock.patch.object(manager, "runtime_state", return_value={"pid": 123, "host_forwards": {}}), \
                    mock.patch.object(ctflab, "bool_pid_alive", return_value=True), \
                    mock.patch.object(manager, "dhcp_lease", return_value="192.168.242.10"), \
                    mock.patch.object(ctflab.socket, "create_connection") as connect:
                result = manager.health("kali-arm64")
            connect.assert_not_called()
            self.assertIsNone(next(item for item in result if item["name"] == "ssh:22")["ok"])

    def test_presets_do_not_change_profile(self):
        original = ctflab.load_profile("kali-arm64")
        for preset, (memory, cpus) in ctflab.RESOURCE_PRESETS.items():
            profile = ctflab.resource_preset_overrides(["kali-arm64"], preset)["kali-arm64"]
            self.assertEqual((profile["guest"]["memory_mb"], profile["guest"]["cpus"]), (memory, cpus))
        self.assertEqual(original, ctflab.load_profile("kali-arm64"))

    def test_preset_rejects_target_and_unknown(self):
        for profiles, preset in [(["smoke"], "light"), (["kali-arm64"], "bad")]:
            with self.assertRaises(ctflab.CTFLabError):
                ctflab.resource_preset_overrides(profiles, preset)

    def test_memory_counts_actual_running_and_override_once(self):
        output = mock.Mock(stdout=str(8 * 1024**3))
        with mock.patch.object(ctflab.subprocess, "run", return_value=output), mock.patch.object(ctflab.os, "statvfs", side_effect=OSError):
            # 2GiB 运行实例不能按基线 5GiB 计算，也不能重复计算自身。
            self.assertEqual(ctflab.check_host_resources(["kali-arm64", "smoke"], ["kali-arm64"],
                             running_memory={"kali-arm64": 2048}), [])
            with self.assertRaises(ctflab.CTFLabError):
                ctflab.check_host_resources(["kali-arm64"], [], profile_overrides=
                                            ctflab.resource_preset_overrides(["kali-arm64"], "performance"))

    def test_snapshot_json_empty_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ctflab.LabManager(Path(directory))
            for action, key in [("list", "snapshots"), ("list-backups", "backups")]:
                stream = io.StringIO()
                with contextlib.redirect_stdout(stream):
                    ctflab.cmd_snapshot(manager, argparse.Namespace(snapshot_command=action, profile="smoke", json=True))
                self.assertEqual(json.loads(stream.getvalue()), {key: []})

    def test_show_stopped_and_headless_refuse(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ctflab.LabManager(Path(directory))
            with self.assertRaises(ctflab.CTFLabError): manager.show_display("smoke")
            with mock.patch.object(manager, "runtime_state", return_value={"pid": 123, "headless": True}), mock.patch.object(ctflab, "bool_pid_alive", return_value=True):
                with self.assertRaises(ctflab.CTFLabError): manager.show_display("smoke")

    def test_show_existing_client_does_not_spawn(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ctflab.LabManager(Path(directory))
            state = {"pid": 123, "spice_client_pid": 456, "display_backend": "spice"}
            with mock.patch.object(manager, "runtime_state", return_value=state), mock.patch.object(ctflab, "bool_pid_alive", return_value=True), mock.patch.object(ctflab.subprocess, "Popen") as spawn:
                self.assertEqual(manager.show_display("kali-arm64")["pid"], 456)
                spawn.assert_not_called()

    def test_show_reconnect_preserves_permissions_and_vm(self):
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="ux-") as directory:
            manager = ctflab.LabManager(Path(directory))
            instance = manager.runtime_dir / "kali-arm64"
            (instance / "spice").mkdir(parents=True)
            (instance / "spice").chmod(0o700)
            state = {"pid": 123, "spice_client_pid": 456, "display_backend": "spice",
                     "clipboard_enabled": False, "file_transfer_enabled": False,
                     "display_quality": "smooth", "overlay_path": "unchanged"}
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(instance / "spice" / "display.sock"))
                with mock.patch.object(manager, "runtime_state", return_value=state), mock.patch.object(ctflab, "bool_pid_alive", side_effect=lambda pid: pid == 123), mock.patch.object(ctflab, "spice_client_path", return_value="/test/spicy"), mock.patch.object(ctflab.subprocess, "Popen", return_value=mock.Mock(pid=789)) as spawn:
                    result = manager.show_display("kali-arm64")
                command = spawn.call_args.args[0]
                self.assertNotIn("--clipboard", command)
                self.assertNotIn("--file-transfer", command)
                self.assertEqual(state["pid"], 123)
                self.assertEqual(state["overlay_path"], "unchanged")
                self.assertTrue(result["reconnected"])

    def test_parser_accepts_new_contract(self):
        parser = ctflab.build_parser()
        self.assertEqual(parser.parse_args(["show", "smoke"]).command, "show")
        self.assertTrue(parser.parse_args(["show", "kali-arm64", "--reconnect"]).reconnect)
        self.assertTrue(parser.parse_args(["snapshot", "list", "smoke", "--json"]).json)
        self.assertEqual(parser.parse_args(["run", "kali-arm64", "--resource-preset", "light"]).resource_preset, "light")

    def test_explicit_reconnect_replaces_live_client_only(self):
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="ux-") as directory:
            manager = ctflab.LabManager(Path(directory))
            endpoint = manager.runtime_dir / "kali-arm64" / "spice"
            endpoint.mkdir(parents=True)
            state = {"pid": 123, "spice_client_pid": 456, "display_backend": "spice",
                     "clipboard_enabled": False, "file_transfer_enabled": False,
                     "overlay_path": "unchanged"}
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(endpoint / "display.sock"))
                with mock.patch.object(manager, "runtime_state", return_value=state), mock.patch.object(ctflab, "bool_pid_alive", return_value=True), mock.patch.object(ctflab, "terminate_spice_client") as terminate, mock.patch.object(ctflab, "spice_client_path", return_value="/test/spicy"), mock.patch.object(ctflab.subprocess, "Popen", return_value=mock.Mock(pid=789)) as spawn:
                    result = manager.show_display("kali-arm64", reconnect=True)
                terminate.assert_called_once_with(456)
                self.assertEqual(result["pid"], 789)
                self.assertEqual(state["pid"], 123)
                self.assertEqual(state["overlay_path"], "unchanged")
                self.assertNotIn("--clipboard", spawn.call_args.args[0])
                self.assertNotIn("--file-transfer", spawn.call_args.args[0])

    def test_reconnect_missing_endpoint_keeps_live_client(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ctflab.LabManager(Path(directory))
            state = {"pid": 123, "spice_client_pid": 456, "display_backend": "spice"}
            with mock.patch.object(manager, "runtime_state", return_value=state), mock.patch.object(ctflab, "bool_pid_alive", return_value=True), mock.patch.object(ctflab, "terminate_spice_client") as terminate, mock.patch.object(ctflab, "spice_client_path", return_value="/test/spicy"):
                with self.assertRaises(ctflab.CTFLabError):
                    manager.show_display("kali-arm64", reconnect=True)
                terminate.assert_not_called()

    def test_reconnect_cocoa_refuses_without_stopping_vm(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ctflab.LabManager(Path(directory))
            with mock.patch.object(manager, "runtime_state", return_value={"pid": 123, "display_backend": "cocoa"}), mock.patch.object(ctflab, "bool_pid_alive", return_value=True), mock.patch.object(ctflab, "terminate_spice_client") as terminate:
                with self.assertRaises(ctflab.CTFLabError):
                    manager.show_display("smoke", reconnect=True)
                terminate.assert_not_called()

    def test_client_prefers_native_bundle_with_old_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plain = root / "bin/spicy"
            native = root / "CTFLabDisplay.app/Contents/MacOS/spicy"
            plain.parent.mkdir(parents=True)
            plain.write_bytes(b"test")
            plain.chmod(0o755)
            with mock.patch.object(ctflab, "runtime_root", return_value=root), mock.patch.dict(ctflab.os.environ, {"CTFLAB_SPICE_CLIENT": ""}):
                self.assertEqual(ctflab.spice_client_path(), str(plain))
                native.parent.mkdir(parents=True)
                native.write_bytes(b"test")
                native.chmod(0o755)
                self.assertEqual(ctflab.spice_client_path(), str(native))

    def test_snapshot_size_unit_does_not_pollute_date(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ctflab.LabManager(Path(directory))
            output = mock.Mock(stdout="1 sample 0 B 2026-10-08 12:34:56 00:00:00.000\n")
            with mock.patch.object(ctflab, "run_command", return_value=output), mock.patch.object(ctflab, "qemu_img_path", return_value="qemu-img"):
                item = manager._qemu_snapshots(Path(directory) / "disk")[0]
            self.assertEqual(item["vm_size"], "0 B")
            self.assertEqual(item["date"], "2026-10-08 12:34:56")

    def test_diagnostic_export_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.json"
            target.write_bytes(b"keep")
            with mock.patch.object(ctflab, "diagnostics_report", return_value={}):
                with self.assertRaises(ctflab.CTFLabError):
                    ctflab.write_diagnostics(ctflab.LabManager(Path(directory)), target)
            self.assertEqual(target.read_bytes(), b"keep")
