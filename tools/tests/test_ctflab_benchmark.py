"""资源档位基准不得用监听层或缺失样本冒充桌面性能。"""
from pathlib import Path
import sys
import unittest
import tempfile
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab_benchmark as benchmark


class BenchmarkTests(unittest.TestCase):
    def test_ready_requires_dhcp_and_guest_ssh(self):
        rows = [{"name": "process", "ok": True}, {"name": "dhcp", "ok": True},
                {"name": "tcp:22", "ok": True}]
        self.assertFalse(benchmark.ready(rows))
        rows.append({"name": "ssh:22", "ok": True})
        self.assertTrue(benchmark.ready(rows))
        rows[-1]["ok"] = None
        self.assertFalse(benchmark.ready(rows))

    def test_summary_missing_is_unknown_not_zero(self):
        report = benchmark.summary([{"preset": "light", "network_ready_seconds": None}])
        self.assertIsNone(report["light"]["median_network_ready_seconds"])
        self.assertEqual(report["light"]["completed_samples"], 0)

    def test_summary_median_and_failures(self):
        report = benchmark.summary([{"preset": "balanced", "network_ready_seconds": value}
                                    for value in (10, 20, None)])
        self.assertEqual(report["balanced"]["median_network_ready_seconds"], 15)
        self.assertEqual(report["balanced"]["completed_samples"], 2)

    def test_bytecode_guard_before_app_access(self):
        with mock.patch.object(sys, "dont_write_bytecode", False):
            with self.assertRaisesRegex(SystemExit, "python3 -B"):
                benchmark.main([])

    def test_only_disposable_manager_is_stopped(self):
        source = Path(benchmark.__file__).read_text()
        self.assertIn('prefix="ctflab-benchmark-"', source)
        self.assertIn('manager.stop(["kali-arm64"])', source)
        self.assertNotIn("stop_all=True", source)
        self.assertIn("headless=True, allow_internet=False", source)
        self.assertIn("clipboard=False, file_transfer=False", source)

    def test_start_failure_stops_only_own_instance(self):
        manager = mock.Mock()
        manager.run.side_effect = ValueError("启动失败")
        manager.running_states.return_value = []
        profile = {"guest": {"memory_mb": 2048, "cpus": 2}}
        api = SimpleNamespace(LabManager=mock.Mock(return_value=manager),
                              write_json=mock.Mock(), CTFLabError=RuntimeError,
                              resource_preset_overrides=lambda *_: {"kali-arm64": profile})
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(benchmark.tempfile, "mkdtemp", return_value=temporary):
            row = benchmark.run_round(api, {}, "light", 30)
        manager.stop.assert_called_once_with(["kali-arm64"])
        self.assertEqual(row["error"], "启动失败")
        self.assertTrue(row["no_running_instances_after_stop"])
        self.assertIsNone(row["network_ready_seconds"])

    def test_cleanup_failure_is_preserved(self):
        manager = mock.Mock()
        manager.run.side_effect = ValueError("启动失败")
        manager.stop.side_effect = RuntimeError("停止失败")
        manager.running_states.return_value = [{"pid": 123}]
        api = SimpleNamespace(LabManager=mock.Mock(return_value=manager),
                              write_json=mock.Mock(), CTFLabError=RuntimeError,
                              resource_preset_overrides=lambda *_: {"kali-arm64": {"guest": {"memory_mb": 2048, "cpus": 2}}})
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(benchmark.tempfile, "mkdtemp", return_value=temporary):
            row = benchmark.run_round(api, {}, "light", 30)
        self.assertEqual(row["cleanup_error"], "停止失败")
        self.assertFalse(row["no_running_instances_after_stop"])


if __name__ == "__main__":
    unittest.main()
