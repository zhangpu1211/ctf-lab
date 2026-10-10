"""验收驱动不得把损坏 App 或历史就绪事件当成通过；不启动虚拟机。"""
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab
import ctflab_app
import ctflab_ux_acceptance as acceptance


class AcceptanceGuardTests(unittest.TestCase):
    def test_usage_sampling_is_limited_to_bound_processes(self):
        state = {"pid": 10, "spice_client_pid": 11, "qmp_path": "/test/qmp",
                 "spice_client_log_path": "/missing/log"}
        manager = mock.Mock()
        manager.runtime_state.return_value = state
        with mock.patch.object(ctflab, "bool_pid_alive", return_value=True), \
                mock.patch.object(ctflab, "qmp_execute", return_value={"running": True}), \
                mock.patch.object(ctflab, "ppm_display_activity", return_value={"active": True}), \
                mock.patch.object(ctflab, "sample_process_usage", return_value={10: {"cpu_percent": 1}}) as usage:
            row = acceptance.idle_observation(ctflab, manager, state)
        usage.assert_called_once_with([10, 11])
        self.assertEqual(row["host_process_usage"], {10: {"cpu_percent": 1}})

    def test_guest_load_fixture_is_bounded_and_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            target = acceptance.guest_load_fixture(Path(directory))
            result = subprocess.run(["/bin/sh", str(target)],
                                    env={**os.environ, "CTFLAB_LOAD_SECONDS": "1"},
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("CTFLAB-LOAD-START seconds=1 workers=2", result.stdout)
            self.assertIn("CTFLAB-LOAD-END", result.stdout)
            with self.assertRaises(FileExistsError):
                acceptance.guest_load_fixture(Path(directory))
            result = subprocess.run(["/bin/sh", str(target)],
                                    env={**os.environ, "CTFLAB_LOAD_SECONDS": "301"},
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("CTFLAB-LOAD-START", result.stdout)

    def test_large_clipboard_fixture_is_deterministic_and_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = acceptance.clipboard_fixture(root / "first")
            second = acceptance.clipboard_fixture(root / "second")
            self.assertEqual(first, second)
            self.assertGreaterEqual(first["bytes"], 1024 * 1024)
            self.assertEqual(first["sha256"], acceptance.digest(root / "first" / first["file"]))
            with self.assertRaises(FileExistsError):
                acceptance.clipboard_fixture(root / "first")

    def test_clipboard_fixture_does_not_access_vm(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(sys, "dont_write_bytecode", True), \
                mock.patch.object(sys, "argv", ["acceptance", "clipboard-fixture", "--out", directory]), \
                mock.patch.object(ctflab, "LabManager") as manager:
            acceptance.main()
            manager.assert_not_called()

    def test_clipboard_flag_cannot_mutate_an_existing_session(self):
        with mock.patch.object(sys, "dont_write_bytecode", True), \
                mock.patch.object(sys, "argv", ["acceptance", "capture", "--out", "/unused", "--clipboard"]), \
                mock.patch.object(ctflab, "LabManager") as manager:
            with self.assertRaises(SystemExit) as result:
                acceptance.main()
            self.assertEqual(result.exception.code, 2)
            manager.assert_not_called()

    def test_idle_black_frame_is_not_a_hang_verdict(self):
        state = {"pid": 10, "spice_client_pid": 11, "qmp_path": "/test/qmp",
                 "spice_client_log_path": "/missing/log", "clipboard_enabled": False}
        manager = mock.Mock()
        manager.runtime_state.return_value = state
        with mock.patch.object(ctflab, "bool_pid_alive", return_value=True), \
                mock.patch.object(ctflab, "qmp_execute", return_value={"running": True}) as qmp, \
                mock.patch.object(ctflab, "ppm_display_activity", return_value={"active": False}):
            row = acceptance.idle_observation(ctflab, manager, state)
        self.assertFalse(row["frame"]["active"])
        self.assertNotIn("terminal", row)
        self.assertNotIn("passed", row)
        self.assertEqual([call.args[1] for call in qmp.call_args_list], ["query-status", "screendump"])

    def test_idle_query_timeout_does_not_restart_or_mark_exit(self):
        state = {"pid": 10, "spice_client_pid": 11, "qmp_path": "/test/qmp",
                 "spice_client_log_path": "/missing/log"}
        manager = mock.Mock()
        manager.runtime_state.return_value = state
        with mock.patch.object(ctflab, "bool_pid_alive", return_value=True), \
                mock.patch.object(ctflab, "qmp_execute", side_effect=TimeoutError):
            row = acceptance.idle_observation(ctflab, manager, state)
        self.assertEqual(row["observation_error"], "TimeoutError")
        self.assertNotIn("terminal", row)
        manager.show_display.assert_not_called()
        manager.stop.assert_not_called()

    def test_idle_refuses_changed_client_or_permissions(self):
        state = {"pid": 10, "spice_client_pid": 11, "clipboard_enabled": False}
        for changed in ({**state, "spice_client_pid": 12}, {**state, "clipboard_enabled": True}):
            manager = mock.Mock()
            manager.runtime_state.return_value = changed
            with mock.patch.object(ctflab, "qmp_execute") as qmp:
                with self.assertRaisesRegex(ValueError, "会话已改变"):
                    acceptance.idle_observation(ctflab, manager, state)
                qmp.assert_not_called()

    def test_idle_exited_bound_process_is_terminal_without_qmp(self):
        state = {"pid": 10, "spice_client_pid": 11}
        manager = mock.Mock()
        manager.runtime_state.return_value = state
        with mock.patch.object(ctflab, "bool_pid_alive", return_value=False), \
                mock.patch.object(ctflab, "qmp_execute") as qmp:
            row = acceptance.idle_observation(ctflab, manager, state)
        self.assertEqual(row["terminal"], "bound-process-exited")
        qmp.assert_not_called()

    def test_metrics_empty_has_no_success_claim(self):
        report = acceptance.display_metrics("")
        self.assertEqual(report["resize_send_to_matched_frame_ms"]["count"], 0)
        self.assertIsNone(report["button_press_to_first_gtk_draw_ms"]["p95_ms"])
        self.assertNotIn("passed", report)

    def test_metrics_ignores_focus_but_keeps_slow_real_click(self):
        report = acceptance.display_metrics("""
recovery-cycle=1 phase=input reason=focus-in
recovery-cycle=1 phase=first-gtk-draw input-us=800000000
recovery-cycle=2 phase=input reason=button-press
recovery-cycle=2 phase=first-gtk-draw input-us=6000000
recovery-cycle=2 phase=first-gtk-draw input-us=1000
recovery-cycle=3 phase=input reason=button-press
""")
        self.assertEqual(report["button_press_to_first_gtk_draw_ms"]["max_ms"], 6000)
        self.assertEqual(report["button_press_to_first_gtk_draw_ms"]["count"], 1)
        self.assertEqual(report["excluded_focus_or_motion_cycles"], 1)
        self.assertEqual(report["button_samples_over_5000ms"], 1)
        self.assertEqual(report["button_presses_without_draw_record"], 1)

    def test_metrics_superseded_timeout_and_pending_are_not_passed(self):
        report = acceptance.display_metrics("""
resize-send immediate=1 accepted=1 target=900x700 t=100ms
resize-send immediate=1 accepted=1 target=1000x800 t=200ms
display-transition end reason=frame-matched t=350ms
resize-send immediate=1 accepted=1 target=1200x800 t=400ms
display-transition end reason=timeout t=2400ms
resize-send immediate=1 accepted=1 target=800x600 t=2500ms
""")
        self.assertEqual(report["resize_send_to_matched_frame_ms"]["max_ms"], 150)
        self.assertEqual(report["superseded_resize_requests"], 1)
        self.assertEqual(report["unmatched_transition_ends"], 1)
        self.assertTrue(report["pending_resize_at_log_end"])

    def test_metrics_negative_time_rejected(self):
        report = acceptance.display_metrics("resize-send immediate=1 accepted=1 target=800x600 t=200ms\ndisplay-transition end reason=frame-matched t=100ms")
        self.assertEqual(report["invalid_time_samples"], 1)
        self.assertEqual(report["resize_send_to_matched_frame_ms"]["count"], 0)

    def test_metrics_can_run_without_app_or_vm_access(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "input.log"
            log.write_text("no samples")
            out = Path(directory) / "evidence"
            argv = ["acceptance", "metrics", "--log", str(log), "--out", str(out)]
            with mock.patch.object(sys, "dont_write_bytecode", True), mock.patch.object(sys, "argv", argv), mock.patch.object(ctflab, "LabManager") as manager:
                acceptance.main()
                with self.assertRaises(FileExistsError):
                    acceptance.main()
                manager.assert_not_called()
            self.assertTrue((out / "display-metrics.json").is_file())

    def test_bytecode_guard_runs_before_import_or_setup(self):
        with mock.patch.object(sys, "dont_write_bytecode", False), \
                mock.patch.object(ctflab, "LabManager") as manager:
            with self.assertRaisesRegex(SystemExit, "python3 -B"):
                acceptance.main()
            manager.assert_not_called()

    def test_failed_app_verification_prevents_asset_access_and_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "Candidate.app"
            argv = ["acceptance", "prepare", "--app", str(app), "--out", str(Path(directory) / "evidence")]
            with mock.patch.object(sys, "dont_write_bytecode", True), \
                    mock.patch.object(sys, "argv", argv), \
                    mock.patch.dict(os.environ), \
                    mock.patch.object(ctflab_app, "verify_app", side_effect=ValueError("清单损坏")) as verify, \
                    mock.patch.object(acceptance, "digest") as digest, \
                    mock.patch.object(ctflab, "LabManager") as manager:
                original_path = list(sys.path)
                try:
                    with self.assertRaisesRegex(ValueError, "清单损坏"):
                        acceptance.main()
                finally:
                    sys.path[:] = original_path
                verify.assert_called_once_with(app.resolve())
                digest.assert_not_called()
                manager.assert_not_called()

    def test_cycle_uses_current_runtime_summary_not_historical_substring(self):
        source = Path(acceptance.__file__).read_text()
        self.assertIn('ctflab.spice_client_summary(restored)["display_ready"]', source)
        self.assertNotIn('"display-ready=1" in Path(', source)
