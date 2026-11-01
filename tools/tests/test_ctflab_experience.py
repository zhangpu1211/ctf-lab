"""显示诊断与启动检查不重启、不写镜像，也不把黑屏当作死机。"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.manager = ctflab.LabManager(Path(self.temporary.name))
        self.state = {"pid": 123, "qmp_path": "/test/qmp", "display_backend": "spice", "spice_client_pid": 456}

    def diagnosis(self, running=True, client=True, black=True):
        def qmp(path, command, arguments=None):
            if command == "query-status": return {"running": running, "status": "running" if running else "paused"}
            self.assertEqual(command, "screendump")
            Path(arguments["filename"]).write_bytes(b"P6\n2 2\n255\n" + (b"\0\0\0" if black else b"\x80\x90\xa0") * 4)
            return {}
        with mock.patch.object(self.manager, "runtime_state", return_value=self.state), mock.patch.object(ctflab, "bool_pid_alive", return_value=True), mock.patch.object(ctflab, "spice_client_summary", return_value={"alive": client}), mock.patch.object(ctflab, "qmp_execute", side_effect=qmp):
            return ctflab.display_diagnosis(self.manager, "kali-arm64")

    def test_black_is_not_guest_dead(self):
        report = self.diagnosis()
        self.assertEqual(report["state"], "black-frame")
        self.assertIn("不能据此判定死机", report["hint"])
        self.assertNotIn("screenshot_path", report)

    def test_uniform_colored_frame_is_present(self):
        self.assertEqual(self.diagnosis(black=False)["state"], "frame-present")

    def test_disconnected_is_distinct_from_pause(self):
        self.assertEqual(self.diagnosis(client=False)["state"], "disconnected")
        self.assertEqual(self.diagnosis(running=False)["state"], "paused")

    def test_stopped_does_not_query_guest(self):
        with mock.patch.object(self.manager, "runtime_state", return_value=self.state), mock.patch.object(ctflab, "bool_pid_alive", return_value=False), mock.patch.object(ctflab, "qmp_execute") as query:
            self.assertEqual(ctflab.display_diagnosis(self.manager, "kali-arm64")["state"], "stopped")
            query.assert_not_called()

    def test_qmp_failure_remains_unknown(self):
        with mock.patch.object(self.manager, "runtime_state", return_value=self.state), mock.patch.object(ctflab, "bool_pid_alive", return_value=True), mock.patch.object(ctflab, "qmp_execute", side_effect=ctflab.CTFLabError("超时")):
            self.assertEqual(ctflab.display_diagnosis(self.manager, "kali-arm64")["state"], "unknown")

    def preflight(self, image, info=None):
        with mock.patch.object(self.manager, "image_state", return_value=image), mock.patch.object(self.manager, "running_states", return_value=[]), mock.patch.object(ctflab, "check_host_resources", return_value=[]), mock.patch.object(ctflab, "which_any", return_value="qemu"), mock.patch.object(ctflab, "qemu_img_path", return_value="qemu-img"), mock.patch.object(ctflab, "qemu_info", return_value=info or {}):
            return ctflab.startup_preflight(self.manager, "smoke")

    def test_missing_base_does_not_create_overlay(self):
        report = self.preflight({})
        self.assertFalse(report["ok"])
        self.assertFalse((self.manager.runtime_dir / "smoke" / "overlay.qcow2").exists())
        self.assertFalse(any(self.manager.runtime_dir.glob("network-*.json")))

    def test_stale_overlay_rejected_without_modification(self):
        base = Path(self.temporary.name) / "base.qcow2"; base.write_bytes(b"base")
        overlay = self.manager.runtime_dir / "smoke" / "overlay.qcow2"
        overlay.parent.mkdir(parents=True); overlay.write_bytes(b"overlay")
        report = self.preflight({"base_path": str(base)}, {"full-backing-filename": "/old/base"})
        self.assertFalse(report["checks"][0]["ok"])
        self.assertEqual(overlay.read_bytes(), b"overlay")
        self.assertEqual(base.read_bytes(), b"base")

    def test_cli_new_commands_parse_without_hidden_permissions(self):
        parser = ctflab.build_parser()
        self.assertEqual(parser.parse_args(["display-diagnose", "kali-arm64"]).command, "display-diagnose")
        self.assertEqual(parser.parse_args(["preflight", "kali-arm64", "--resource-preset", "light"]).resource_preset, "light")
        self.assertFalse(parser.parse_args(["update", "stage", "CTFLab.app", "--sha256", "0" * 64]).allow_local_candidate)

    def test_update_uses_explicit_state_scope(self):
        args = ctflab.build_parser().parse_args(["--state-dir", self.temporary.name, "update", "status"])
        with mock.patch("ctflab_update.status", return_value={}) as status:
            ctflab.cmd_update(None, args)
        status.assert_called_once_with(Path(self.temporary.name) / "updates")

    def test_latest_transition_event_not_historical_timeout(self):
        log = Path(self.temporary.name) / "display.log"
        log.write_text("CTFLAB_SPICE_STATE display-ready=1\nCTFLAB_SPICE_STATE display-transition end reason=timeout\nCTFLAB_SPICE_STATE display-transition end reason=frame-matched\n")
        state = {**self.state, "spice_client_log_path": str(log)}
        with mock.patch.object(ctflab, "bool_pid_alive", return_value=True):
            report = ctflab.spice_client_summary(state)
        self.assertEqual(report["last_transition_reason"], "frame-matched")
        self.assertTrue(report["display_ready"])


if __name__ == "__main__": unittest.main()
