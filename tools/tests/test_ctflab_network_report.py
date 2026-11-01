#!/usr/bin/env python3
"""实验网只读拓扑报告的回归测试（第 11 项展示切片；全部 mock，无真实网络）。"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import ctflab  # noqa: E402


class NetworkReportTests(unittest.TestCase):
    def _manager(self, directory: str) -> ctflab.LabManager:
        return ctflab.LabManager(Path(directory))

    def _write_running(self, manager: ctflab.LabManager, profile_id: str,
                       internet: bool = False) -> None:
        ctflab.write_json(manager.runtime_state_path(profile_id), {
            "schema": 1, "profile_id": profile_id, "pid": 4242,
            "qmp_path": str(manager.runtime_dir / profile_id / "qmp.sock"),
            "log_path": str(manager.logs_dir / f"{profile_id}.log"),
            "started_at": ctflab.now_iso(),
            "lab_port": 23400,
            "host_forwards": {"ssh": 12210},
            "internet_enabled": internet,
            "display_backend": "spice",
            "spice_endpoint": f"spice+unix://{manager.runtime_dir}/{profile_id}/spice/display.sock",
            "spice_listen": "unix",
        })

    def test_stopped_nodes_show_declared_policy_without_actual(self):
        with tempfile.TemporaryDirectory() as directory:
            report = ctflab.network_report(self._manager(directory))
            kali = next(node for node in report["nodes"] if node["id"] == "kali-arm64")
            self.assertFalse(kali["running"])
            self.assertIsNone(kali["actual"])
            self.assertEqual(kali["declared"]["lab_ip"], "192.168.242.10")
            self.assertEqual(kali["declared"]["host_forwards"], {"ssh": 12210})
            self.assertFalse(kali["declared"]["internet"])
            self.assertTrue(kali["internet_policy"]["consistent"])

    def test_running_kali_marks_default_nat_policy_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            self._write_running(manager, "kali-arm64", internet=True)
            with mock.patch.object(ctflab, "bool_pid_alive", return_value=True), \
                    mock.patch.object(ctflab.LabManager, "dhcp_lease",
                                      return_value="192.168.242.10"), \
                    mock.patch.object(ctflab.LabManager, "network_ports",
                                      return_value=[]):
                report = ctflab.network_report(manager)
            kali = next(node for node in report["nodes"] if node["id"] == "kali-arm64")
            self.assertTrue(kali["running"])
            policy = kali["internet_policy"]
            self.assertTrue(policy["runtime"])
            self.assertIn("user-mode NAT", policy["note"])
            self.assertTrue(policy["consistent"])
            self.assertEqual(kali["actual"]["dhcp_lease"], "192.168.242.10")

    def test_target_internet_mismatch_is_flagged(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            # 靶机声明公网隔离，但构造运行状态错误地开了联网：必须标记不一致。
            self._write_running(manager, "smoke", internet=True)
            with mock.patch.object(ctflab, "bool_pid_alive", return_value=True), \
                    mock.patch.object(ctflab.LabManager, "dhcp_lease",
                                      return_value=None), \
                    mock.patch.object(ctflab.LabManager, "network_ports",
                                      return_value=[]):
                report = ctflab.network_report(manager)
            smoke = next(node for node in report["nodes"] if node["id"] == "smoke")
            self.assertFalse(smoke["internet_policy"]["consistent"])

    def test_switch_state_lists_counters_and_residue(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self._manager(directory)
            self._write_running(manager, "kali-arm64", internet=True)
            network_state = {
                "pid": 7777,
                "client_count": 2,
                "learned_macs": ["52:54:00:24:00:10", "52:54:00:24:00:20"],
                "counters": {"received": 100, "forwarded": 90, "dropped_rate_limit": 1},
                "pcap_path": "/tmp/lab.pcap",
            }
            with mock.patch.object(ctflab, "bool_pid_alive", return_value=True), \
                    mock.patch.object(ctflab.LabManager, "dhcp_lease",
                                      return_value=None), \
                    mock.patch.object(ctflab.LabManager, "network_ports",
                                      return_value=[23400]), \
                    mock.patch.object(ctflab.LabManager, "network_state",
                                      return_value=network_state):
                report = ctflab.network_report(manager)
            switch = report["switches"][0]
            self.assertEqual(switch["lab_port"], 23400)
            self.assertTrue(switch["alive"])
            self.assertEqual(switch["clients"], 2)
            self.assertEqual(switch["learned_macs"], 2)
            self.assertEqual(switch["counters"], {"received": 100, "forwarded": 90,
                                                  "dropped_rate_limit": 1})
            self.assertEqual(switch["pcap_path"], "/tmp/lab.pcap")

    def test_cli_wires_network_json_flag(self):
        parser = ctflab.build_parser()
        self.assertTrue(parser.parse_args(["network", "--json"]).json)
        self.assertFalse(parser.parse_args(["network"]).json)


if __name__ == "__main__":
    unittest.main()
