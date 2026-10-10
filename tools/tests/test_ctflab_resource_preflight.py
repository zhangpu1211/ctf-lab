"""第 7 项资源预检的回归测试（全 mock，不读真实宿主状态）。"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))
import ctflab  # noqa: E402
from ctflab import CTFLabError  # noqa: E402


def fake_sysctl(total_bytes: int):
    return mock.patch.object(
        ctflab.subprocess, "run",
        return_value=subprocess.CompletedProcess([], 0, str(total_bytes), ""))


class ResourcePreflightTests(unittest.TestCase):
    def test_usage_samples_owned_pids_once_and_keeps_units(self):
        output = mock.Mock(stdout=" 12 130.5 2048\n34 0.0 1024\n99 5.0 9999\n", returncode=0)
        with mock.patch.object(ctflab.subprocess, "run", return_value=output) as probe:
            result = ctflab.sample_process_usage([12, 34, 12, -1])
        probe.assert_called_once()
        self.assertEqual(probe.call_args.args[0][2], "12,34")
        self.assertEqual(result, {12: {"cpu_percent": 130.5, "rss_mb": 2.0},
                                  34: {"cpu_percent": 0.0, "rss_mb": 1.0}})

    def test_usage_unavailable_is_unknown_not_zero(self):
        for output in ("12 nan 2048\n", "12 2 inf\n", "bad\n", "12 -1 3\n"):
            with mock.patch.object(ctflab.subprocess, "run", return_value=mock.Mock(stdout=output)):
                self.assertEqual(ctflab.sample_process_usage([12]), {})
        with mock.patch.object(ctflab.subprocess, "run", side_effect=OSError):
            self.assertEqual(ctflab.sample_process_usage([12]), {})
        with mock.patch.object(ctflab.subprocess, "run") as probe:
            self.assertEqual(ctflab.sample_process_usage([]), {})
            probe.assert_not_called()

    def test_resource_summary_uses_runtime_configuration(self):
        profile = {"guest": {"memory_mb": 5120, "cpus": 4}}
        state = {"pid": 12, "memory_mb": 2048, "cpus": 2,
                 "command": ["qemu", "-accel", "hvf"]}
        result = ctflab.node_resource_summary(profile, state, {12: {"cpu_percent": 15, "rss_mb": 600}})
        self.assertEqual((result["memory_mb"], result["cpus"], result["acceleration"]), (2048, 2, "hvf"))
        stopped = ctflab.node_resource_summary(profile, {}, {})
        self.assertEqual(stopped["memory_mb"], 5120)
        self.assertIsNone(stopped["rss_mb"])
        self.assertIsNone(stopped["acceleration"])
        self.assertIsNone(ctflab.node_resource_summary(profile, {"command": ["qemu", "-accel"]}, {})["acceleration"])

    def test_under_commit_passes_and_low_disk_warns(self):
        stat = mock.Mock(f_bavail=100, f_frsize=1024 * 1024)  # 100 MiB < 阈值
        with fake_sysctl(16 * 1024 ** 3), \
                mock.patch.object(ctflab.os, "statvfs", return_value=stat):
            warnings = ctflab.check_host_resources(
                ["smoke"], [], Path("/tmp/state"))
        self.assertEqual(len(warnings), 1)
        self.assertIn("可用", warnings[0])

    def test_overcommit_refuses_with_numbers(self):
        # kali(5G) + smoke(4G) + basic(1G) = 10G，宿主 10GiB ×0.9=9GiB → 超配。
        with fake_sysctl(10 * 1024 ** 3), \
                mock.patch.object(ctflab.os, "statvfs"):
            with self.assertRaisesRegex(CTFLabError, "内存预检未通过.*TCG"):
                ctflab.check_host_resources(
                    ["kali-arm64", "smoke", "basic-pentesting-2"], [], Path("/tmp/s"))

    def test_running_nodes_count_toward_commit(self):
        with fake_sysctl(8 * 1024 ** 3), \
                mock.patch.object(ctflab.os, "statvfs"):
            # 已运行 kali 5G，再启动 smoke 4G → 9G > 7.2G 上限。
            with self.assertRaisesRegex(CTFLabError, "内存预检"):
                ctflab.check_host_resources(["smoke"], ["kali-arm64"], Path("/tmp/s"))

    def test_sysctl_failure_does_not_block(self):
        def boom(*args, **kwargs):
            raise OSError("no sysctl")
        with mock.patch.object(ctflab.subprocess, "run", side_effect=boom):
            self.assertEqual(ctflab.check_host_resources(["smoke"], [], None), [])

    def test_run_wires_preflight_warnings(self):
        stat = mock.Mock(f_bavail=1, f_frsize=1024)
        manager = ctflab.LabManager(Path(tempfile.mkdtemp()))
        with fake_sysctl(16 * 1024 ** 3), \
                mock.patch.object(ctflab.os, "statvfs", return_value=stat), \
                mock.patch.object(ctflab.LabManager, "running_states", return_value=[]):
            warnings = ctflab.check_host_resources(
                ["smoke"], [s["profile_id"] for s in manager.running_states()],
                manager.state_dir)
        self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()
