#!/usr/bin/env python3
"""受控启动回退矩阵的回归测试。"""

from __future__ import annotations

import copy
import io
from contextlib import redirect_stdout
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import ctflab  # noqa: E402
from ctflab import LabManager, matrix_candidates  # noqa: E402

BASE_PROFILE = {
    "schema": 1,
    "id": "unknown-x86",
    "name": "Unknown x86",
    "guest": {"architecture": "x86_64", "firmware": "bios", "machine": "pc", "memory_mb": 1024, "cpus": 1},
    "disk": {"format": "qcow2", "bus": "ide"},
    "network": {"adapter": "e1000", "mac": "52:54:00:24:00:2a", "lab_ip": "192.168.242.42",
                "segment": "lab", "internet": False},
    "readiness": {"timeout_seconds": 60, "checks": ["dhcp"]},
}


class MatrixDefinitionTests(unittest.TestCase):
    def test_x86_matrix_uses_whitelisted_combinations(self) -> None:
        seen = set()
        for candidate in matrix_candidates("x86_64"):
            self.assertIn(candidate["firmware"], {"bios", "uefi"})
            self.assertIn(candidate["bus"], {"ide", "sata", "scsi", "virtio"})
            self.assertIn(candidate.get("controller"), {None, "lsi53c895a", "ich9-ahci"})
            seen.add((candidate["firmware"], candidate["bus"]))
            # 白名单组合必须能通过 profile 校验
            profile = copy.deepcopy(BASE_PROFILE)
            profile["guest"]["firmware"] = candidate["firmware"]
            profile["disk"]["bus"] = candidate["bus"]
            if candidate.get("controller"):
                profile["disk"]["controller"] = candidate["controller"]
            ctflab.validate_profile(profile, pathlib.Path("matrix.yaml"))
        self.assertEqual(len(seen), 8, "应覆盖 BIOS/UEFI × IDE/SATA/SCSI/VirtIO")

    def test_aarch64_matrix_is_single_uefi_virtio(self) -> None:
        candidates = matrix_candidates("aarch64")
        self.assertEqual(list(candidates), [{"firmware": "uefi", "bus": "virtio"}])

    def test_candidate_label_includes_controller(self) -> None:
        self.assertEqual(ctflab.candidate_label({"firmware": "bios", "bus": "scsi", "controller": "lsi53c895a"}),
                         "bios/scsi/lsi53c895a")
        self.assertEqual(ctflab.candidate_label({"firmware": "uefi", "bus": "virtio"}), "uefi/virtio")


class BootMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.manager = LabManager(pathlib.Path(self._tmp.name))
        self.profile = copy.deepcopy(BASE_PROFILE)
        self.profile["id"] = "kali-arm64"  # 借用已存在的 profile id 以便 REPORT/日志路径可用
        self.overrides_seen: list[dict] = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def fake_probe(self, outcomes):
        """outcomes: 每个候选的 (verdict, screen_classification) 或 Exception。"""
        calls = iter(outcomes)

        def probe(profile_id, *, timeout_seconds=None, keep_running=False,
                  profile_overrides=None, abort_on_failure_screen=False):
            outcome = next(calls)
            if isinstance(outcome, Exception):
                raise outcome
            self.overrides_seen.append(copy.deepcopy(profile_overrides[profile_id]))
            verdict, classification = outcome
            report = {
                "profile_id": profile_id,
                "verdict": verdict,
                "screen": {"classification": classification, "confidence": "high"},
                "early_failure": classification if classification in ctflab.SCREEN_FAILURE_CLASSES else None,
                "screenshot_path": None,
                "report_path": None,
            }
            # probe 会把截图分类结果写进报告；这里直接返回构造结果
            return report

        return probe

    def run_matrix(self, outcomes, **kwargs):
        output = io.StringIO()
        with mock.patch.object(ctflab, "load_profile", return_value=copy.deepcopy(self.profile)), \
                mock.patch.object(self.manager, "probe", side_effect=self.fake_probe(outcomes)), \
                redirect_stdout(output):
            return self.manager.boot_matrix("kali-arm64", **kwargs)

    def test_stops_at_first_bootable_candidate(self) -> None:
        result = self.run_matrix([
            ("uefi_shell", "uefi_shell"),
            ("display_activity_only", "login_ready"),
        ])
        self.assertTrue(result["succeeded"])
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(result["selected"]["label"], "bios/ide")
        # 第一个候选是矩阵第一项（bios/scsi/lsi53c895a），第二个才是 bios/ide
        self.assertEqual(self.overrides_seen[0]["disk"]["bus"], "scsi")
        self.assertEqual(self.overrides_seen[0]["disk"]["controller"], "lsi53c895a")
        self.assertEqual(self.overrides_seen[1]["disk"]["bus"], "ide")
        self.assertNotIn("controller", self.overrides_seen[1]["disk"])
        self.assertTrue(pathlib.Path(result["report_path"]).is_file())

    def test_reports_all_candidates_when_none_boot(self) -> None:
        outcomes = [("no_boot_device", "no_boot_device")] * len(matrix_candidates("x86_64"))
        result = self.run_matrix(outcomes)
        self.assertFalse(result["succeeded"])
        self.assertEqual(len(result["attempts"]), 8)
        self.assertTrue(all(attempt["screen"] == "no_boot_device" for attempt in result["attempts"]))

    def test_launch_error_continues_with_next_candidate(self) -> None:
        result = self.run_matrix([
            ctflab.CTFLabError("缺少 UEFI 固件"),
            ("service_ready", "login_ready"),
        ])
        self.assertTrue(result["succeeded"])
        self.assertIn("缺少 UEFI 固件", result["attempts"][0]["error"])
        self.assertEqual(result["selected"]["label"], "bios/ide")

    def test_profile_on_disk_is_not_modified(self) -> None:
        original = copy.deepcopy(self.profile)
        self.run_matrix([("uefi_shell", "uefi_shell"), ("display_activity_only", "login_ready")])
        self.assertEqual(self.profile, original, "矩阵只能使用覆盖副本，不能改写 profile")

    def test_max_candidates_limits_attempts(self) -> None:
        result = self.run_matrix([("uefi_shell", "uefi_shell")], max_candidates=1)
        self.assertFalse(result["succeeded"])
        self.assertEqual(len(result["attempts"]), 1)


class X86UefiCommandTests(unittest.TestCase):
    def test_x86_uefi_uses_ovmf_pflash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = LabManager(pathlib.Path(directory))
            profile = copy.deepcopy(BASE_PROFILE)
            profile["guest"]["firmware"] = "uefi"
            command, _ = manager.qemu_command("unknown-x86", profile,
                                              pathlib.Path("/tmp/overlay.qcow2"), 23400, headless=True)
        joined = " ".join(command)
        self.assertIn("if=pflash,format=raw,unit=0", joined)
        self.assertIn("edk2-x86_64-code.fd", joined)
        self.assertIn("if=pflash,format=raw,unit=1", joined)
        self.assertIn("uefi-vars-x86_64.fd", joined)

    def test_x86_bios_has_no_pflash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = LabManager(pathlib.Path(directory))
            profile = copy.deepcopy(BASE_PROFILE)
            command, _ = manager.qemu_command("unknown-x86", profile,
                                              pathlib.Path("/tmp/overlay.qcow2"), 23400, headless=True)
        self.assertNotIn("pflash", " ".join(command))


if __name__ == "__main__":
    unittest.main()
