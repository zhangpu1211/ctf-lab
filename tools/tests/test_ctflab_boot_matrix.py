#!/usr/bin/env python3
"""受控启动回退矩阵的回归测试。"""

from __future__ import annotations

import copy
import io
import os
from contextlib import redirect_stdout
import pathlib
import platform
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import yaml

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
    def test_unsupported_architecture_is_not_guessed(self):
        with self.assertRaises(ctflab.CTFLabError):
            matrix_candidates("mips")

    def test_source_candidate_is_first_without_extending_whitelist(self):
        profile = copy.deepcopy(BASE_PROFILE)
        profile["detection"] = {"status": "candidate"}
        profile["guest"]["firmware"] = "uefi"
        profile["disk"] = {"bus": "sata", "controller": "ich9-ahci"}
        ordered = ctflab.ordered_matrix_candidates(profile)
        self.assertEqual(ordered[0], {"firmware": "uefi", "bus": "sata", "controller": "ich9-ahci"})
        self.assertTrue(all(item["firmware"] == "uefi" for item in ordered[:4]))
        self.assertEqual({ctflab.candidate_label(x) for x in ordered},
                         {ctflab.candidate_label(x) for x in matrix_candidates("x86_64")})
        profile["disk"]["controller"] = "untrusted-arbitrary-device"
        self.assertNotIn("untrusted-arbitrary-device", str(ctflab.ordered_matrix_candidates(profile)))

    def test_launch_failures_have_conservative_retry_policy(self):
        examples = (
            ("No space left on device", "storage", False),
            ("Failed to get write lock", "storage", False),
            ("cannot allocate memory", "resources", False),
            ("缺少 QEMU", "runtime_dependency", False),
            ("缺少 UEFI 固件", "firmware_dependency", True),
            ("x is not a valid device model", "device_compatibility", True),
            ("unexpected failure", "unclassified", False),
        )
        for text, category, retryable in examples:
            result = ctflab.startup_failure(text)
            self.assertEqual((result["category"], result["retryable"]), (category, retryable))
            self.assertTrue(result["hint"])

    def test_screen_guidance_does_not_claim_automatic_repair(self):
        for screen in ctflab.SCREEN_FAILURE_CLASSES | {"login_ready", "unknown"}:
            self.assertTrue(ctflab.probe_recommendations(screen))
        self.assertIn("不自动改写", " ".join(ctflab.probe_recommendations("kernel_error")))

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
                "process_running_at_verdict": True,
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

    def test_pxe_screen_never_counts_as_bootable(self) -> None:
        """2026-09-25 WebServer 回归：PXE 启动画面不得被矩阵选为磁盘启动成功。

        真实样本里 QEMU 在运行、画面非黑且 DHCP 正常；旧逻辑下该候选曾被
        network_and_display_candidate 语义接受。现在 PXE 属失败类，应立即
        换下一个候选且不产生 selected。
        """
        result = self.run_matrix([("pxe_network_boot", "pxe_network_boot")],
                                 max_candidates=1)
        self.assertFalse(result["succeeded"])
        self.assertIsNone(result["selected"])
        attempt = result["attempts"][0]
        self.assertEqual(attempt["verdict"], "pxe_network_boot")
        self.assertEqual(attempt["screen"], "pxe_network_boot")
        self.assertEqual(attempt["early_failure"], "pxe_network_boot")

    def test_unknown_display_with_dhcp_continues_matrix(self) -> None:
        result = self.run_matrix([
            ("network_and_display_candidate", "unknown"),
            ("display_activity_only", "login_ready"),
        ])
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(result["selected"]["label"], "bios/ide")

    def test_environment_error_stops_without_trying_all_controllers(self):
        result = self.run_matrix([ctflab.CTFLabError("No space left on device")])
        self.assertFalse(result["succeeded"])
        self.assertEqual(len(result["attempts"]), 1)
        self.assertEqual(result["stopped_reason"]["category"], "storage")

    def test_unknown_error_stops_and_keeps_original_error(self):
        result = self.run_matrix([ctflab.CTFLabError("opaque startup failure")])
        self.assertEqual(result["stopped_reason"]["category"], "unclassified")
        self.assertEqual(result["attempts"][0]["error"], "opaque startup failure")

    def test_running_node_is_refused_without_stop_or_probe(self):
        with mock.patch.object(self.manager, "runtime_state", return_value={"pid": 123}), \
                mock.patch.object(ctflab, "bool_pid_alive", return_value=True), \
                mock.patch.object(self.manager, "stop") as stop, \
                mock.patch.object(self.manager, "probe") as probe, \
                self.assertRaisesRegex(ctflab.CTFLabError, "正在运行"):
            self.manager.boot_matrix("kali-arm64")
        stop.assert_not_called()
        probe.assert_not_called()

    def test_existing_overlay_is_preserved_without_reset_or_probe(self):
        instance = self.manager.runtime_dir / "kali-arm64"
        instance.mkdir(parents=True)
        disk = instance / "overlay.qcow2"
        disk.write_bytes(b"user changes")
        with mock.patch.object(self.manager, "reset") as reset, \
                mock.patch.object(self.manager, "probe") as probe, \
                self.assertRaisesRegex(ctflab.CTFLabError, "保护改动"):
            self.manager.boot_matrix("kali-arm64")
        reset.assert_not_called()
        probe.assert_not_called()
        self.assertEqual(disk.read_bytes(), b"user changes")

    def test_owned_overlay_and_nvram_are_fresh_for_each_attempt(self):
        instance = self.manager.runtime_dir / "kali-arm64"
        original_probe = self.fake_probe([("no_boot_device", "no_boot_device"),
                                          ("display_activity_only", "login_ready")])
        def probe(*args, **kwargs):
            self.assertFalse(instance.exists(), "前一候选的运行盘不得进入下一候选")
            instance.mkdir(parents=True)
            (instance / "overlay.qcow2").write_bytes(b"probe-only")
            (instance / "uefi-vars.fd").write_bytes(b"probe-only")
            return original_probe(*args, **kwargs)
        with mock.patch.object(ctflab, "load_profile", return_value=self.profile), \
                mock.patch.object(self.manager, "probe", side_effect=probe):
            result = self.manager.boot_matrix("kali-arm64")
        self.assertTrue(result["succeeded"])
        self.assertFalse(instance.exists())

    def test_live_instance_after_stop_is_preserved_and_matrix_aborts(self):
        instance = self.manager.runtime_dir / "kali-arm64"
        def probe(*args, **kwargs):
            instance.mkdir(parents=True)
            return {"verdict": "display_activity_only", "screen": {"classification": "unknown"}}
        with mock.patch.object(ctflab, "load_profile", return_value=self.profile), \
                mock.patch.object(self.manager, "runtime_state", side_effect=[None, {"pid": 123}]), \
                mock.patch.object(ctflab, "bool_pid_alive", return_value=True), \
                mock.patch.object(self.manager, "probe", side_effect=probe), \
                mock.patch.object(self.manager, "stop"), \
                mock.patch.object(self.manager, "reset") as reset, \
                self.assertRaisesRegex(ctflab.CTFLabError, "未能停止"):
            self.manager.boot_matrix("kali-arm64")
        reset.assert_not_called()
        self.assertTrue(instance.exists())

    def test_stale_login_screenshot_after_exit_is_not_selected(self):
        with mock.patch.object(ctflab, "load_profile", return_value=self.profile), \
                mock.patch.object(self.manager, "probe", return_value={
                    "verdict": "qemu_exited", "screen": {"classification": "login_ready"},
                    "process_running_at_verdict": False}):
            result = self.manager.boot_matrix("kali-arm64", max_candidates=1)
        self.assertFalse(result["succeeded"])
        self.assertIsNone(result["selected"])

    def test_failure_screen_overrides_service_ready(self):
        result = self.run_matrix([("service_ready", "pxe_network_boot")], max_candidates=1)
        self.assertFalse(result["succeeded"])

    def test_profile_changed_during_probe_cannot_bind_report(self):
        with mock.patch.object(ctflab, "sha256_file", side_effect=["a" * 64, "b" * 64]), \
                self.assertRaisesRegex(ctflab.CTFLabError, "矩阵运行期间被修改"):
            self.run_matrix([("display_activity_only", "login_ready")])


class MatrixApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.manager = LabManager(self.root / "state")
        self.profile_dir = self.root / "profiles"
        self.profile_dir.mkdir()
        self.env = mock.patch.dict(os.environ, {"CTFLAB_PROFILE_DIR": str(self.profile_dir)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.profile_id = "matrix-box"
        self.profile = copy.deepcopy(BASE_PROFILE)
        self.profile["id"] = self.profile_id
        self.profile["detection"] = {"status": "candidate", "boot_verified": False,
                                     "service_verified": False}
        self.profile_path = self.profile_dir / f"{self.profile_id}.yaml"
        self.profile_path.write_text(yaml.safe_dump(self.profile, allow_unicode=True, sort_keys=False),
                                     encoding="utf-8")
        self.base = self.root / "base.qcow2"
        self.base.write_bytes(b"registered base")
        self.base_hash = ctflab.sha256_file(self.base)
        self.source_hash = "a" * 64
        ctflab.write_json(self.manager.image_state_path(self.profile_id), {
            "profile_id": self.profile_id, "source_sha256": self.source_hash,
            "base_path": str(self.base), "base_sha256": self.base_hash,
        })
        self.report_dir = self.manager.logs_dir / "probes"
        self.report_dir.mkdir(parents=True)
        self.report_path = self.report_dir / "matrix.json"
        self.candidate = {"firmware": "uefi", "bus": "sata", "controller": "ich9-ahci"}
        self.report = {
            "schema": 1, "profile_id": self.profile_id, "succeeded": True,
            "profile_sha256": ctflab.sha256_file(self.profile_path),
            "source_sha256": self.source_hash, "base_sha256": self.base_hash,
            "selected": {"candidate": self.candidate, "verdict": "display_activity_only",
                         "screen": "login_ready", "process_running_at_verdict": True},
        }
        ctflab.write_json(self.report_path, self.report)

    def test_apply_requires_confirmation(self):
        with self.assertRaisesRegex(ctflab.CTFLabError, "confirm-apply"):
            self.manager.apply_matrix_candidate(self.profile_id, str(self.report_path), confirm=False)
        self.assertEqual(ctflab.load_profile(self.profile_id)["disk"]["bus"], "ide")

    def manual_report(self):
        screenshot = self.report_dir / "sample.png"
        screenshot.write_bytes(b"bound screenshot fixture")
        attempt = {"candidate": self.candidate, "screen": "unknown", "verdict": "network_and_display_candidate",
                   "process_running_at_verdict": True, "display_active": True,
                   "screenshot_path": str(screenshot), "screenshot_sha256": ctflab.sha256_file(screenshot)}
        self.report.update(succeeded=False, selected=None, review_attempt=1, attempts=[attempt])
        ctflab.write_json(self.report_path, self.report)
        return screenshot

    def test_manual_review_requires_explicit_index_and_keeps_candidate(self):
        self.manual_report()
        before = self.profile_path.read_bytes()
        with self.assertRaises(ctflab.CTFLabError):
            self.manager.apply_matrix_candidate(self.profile_id, str(self.report_path), confirm=True)
        result = self.manager.apply_matrix_candidate(self.profile_id, str(self.report_path),
                                                     confirm=True, review_attempt=1)
        self.assertEqual(pathlib.Path(result["backup_path"]).read_bytes(), before)
        profile = ctflab.load_profile(self.profile_id)
        self.assertFalse(profile["detection"]["boot_verified"])
        self.assertFalse(profile["detection"]["service_verified"])
        self.assertEqual(profile["detection"]["status"], "candidate")
        self.assertEqual(profile["detection"]["matrix_applied"]["review_mode"], "screenshot-only")

    def test_manual_review_refuses_tampered_screenshot_and_failure_screen(self):
        screenshot = self.manual_report()
        screenshot.write_bytes(b"changed")
        with self.assertRaisesRegex(ctflab.CTFLabError, "截图"):
            self.manager.apply_matrix_candidate(self.profile_id, str(self.report_path), confirm=True, review_attempt=1)
        self.report["attempts"][0]["screenshot_sha256"] = ctflab.sha256_file(screenshot)
        self.report["attempts"][0]["screen"] = "pxe_network_boot"
        ctflab.write_json(self.report_path, self.report)
        with self.assertRaisesRegex(ctflab.CTFLabError, "画面"):
            self.manager.apply_matrix_candidate(self.profile_id, str(self.report_path), confirm=True, review_attempt=1)

    def test_apply_only_hardware_candidate_and_keeps_unverified(self):
        before = self.profile_path.read_bytes()
        result = self.manager.apply_matrix_candidate(self.profile_id, str(self.report_path), confirm=True)
        updated = ctflab.load_profile(self.profile_id)
        self.assertEqual(updated["guest"]["firmware"], "uefi")
        self.assertEqual(updated["disk"], {"format": "qcow2", "bus": "sata", "controller": "ich9-ahci"})
        self.assertEqual(updated["detection"]["status"], "candidate")
        self.assertFalse(updated["detection"]["boot_verified"])
        self.assertFalse(updated["detection"]["service_verified"])
        self.assertTrue(updated["detection"]["matrix_applied"]["human_confirmed"])
        self.assertEqual(pathlib.Path(result["backup_path"]).read_bytes(), before)
        self.assertEqual(ctflab.read_json(self.report_path), self.report)
        self.assertFalse((self.manager.runtime_dir / self.profile_id).exists())

    def test_apply_rejects_external_or_stale_report_and_tampered_base(self):
        external = self.root / "outside.json"
        ctflab.write_json(external, self.report)
        with self.assertRaisesRegex(ctflab.CTFLabError, "当前状态目录"):
            self.manager.apply_matrix_candidate(self.profile_id, str(external), confirm=True)
        self.profile_path.write_text(self.profile_path.read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ctflab.CTFLabError, "配置.*已变化"):
            self.manager.apply_matrix_candidate(self.profile_id, str(self.report_path), confirm=True)
        self.profile_path.write_text(yaml.safe_dump(self.profile, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.report["profile_sha256"] = ctflab.sha256_file(self.profile_path)
        ctflab.write_json(self.report_path, self.report)
        self.base.write_bytes(b"tampered")
        with self.assertRaisesRegex(ctflab.CTFLabError, "基础镜像"):
            self.manager.apply_matrix_candidate(self.profile_id, str(self.report_path), confirm=True)

    def test_apply_rejects_incomplete_or_non_whitelist_success(self):
        for change in (
            {"succeeded": False},
            {"selected": {"candidate": self.candidate, "verdict": "service_ready",
                          "screen": "pxe_network_boot", "process_running_at_verdict": True}},
            {"selected": {"candidate": {"firmware": "bios", "bus": "floppy"},
                          "verdict": "service_ready", "screen": "login_ready",
                          "process_running_at_verdict": True}},
            {"selected": {"candidate": self.candidate, "verdict": "qemu_exited",
                          "screen": "login_ready", "process_running_at_verdict": False}},
        ):
            bad = copy.deepcopy(self.report)
            bad.update(change)
            ctflab.write_json(self.report_path, bad)
            with self.assertRaisesRegex(ctflab.CTFLabError, "可固化"):
                self.manager.apply_matrix_candidate(self.profile_id, str(self.report_path), confirm=True)

    def test_apply_rejects_existing_runtime_without_deleting_it(self):
        runtime = self.manager.runtime_dir / self.profile_id
        runtime.mkdir(parents=True)
        overlay = runtime / "overlay.qcow2"
        overlay.write_bytes(b"user")
        with self.assertRaisesRegex(ctflab.CTFLabError, "运行盘"):
            self.manager.apply_matrix_candidate(self.profile_id, str(self.report_path), confirm=True)
        self.assertEqual(overlay.read_bytes(), b"user")

    def test_cli_apply_calls_offline_path_and_rejects_matrix_options(self):
        parser = ctflab.build_parser()
        args = parser.parse_args([
            "probe", self.profile_id, "--apply-matrix-report", str(self.report_path),
            "--confirm-apply",
        ])
        manager = mock.Mock()
        manager.apply_matrix_candidate.return_value = {
            "candidate": self.candidate, "backup_path": "/tmp/backup.yaml",
        }
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(ctflab.cmd_probe(manager, args), 0)
        manager.apply_matrix_candidate.assert_called_once_with(
            self.profile_id, str(self.report_path), confirm=True, review_attempt=None)
        self.assertIn("状态仍为 candidate", output.getvalue())

        mixed = parser.parse_args([
            "probe", self.profile_id, "--apply-matrix-report", str(self.report_path),
            "--confirm-apply", "--matrix-timeout", "30",
        ])
        with self.assertRaisesRegex(ctflab.CTFLabError, "不能与启动/矩阵参数混用"):
            ctflab.cmd_probe(mock.Mock(), mixed)

    def test_failed_replace_keeps_original_and_backup(self):
        before = self.profile_path.read_bytes()
        with mock.patch.object(ctflab.os, "replace", side_effect=OSError("replace failed")), \
                self.assertRaisesRegex(ctflab.CTFLabError, "replace failed"):
            self.manager.apply_matrix_candidate(self.profile_id, str(self.report_path), confirm=True)
        self.assertEqual(self.profile_path.read_bytes(), before)
        self.assertFalse(list(self.profile_dir.glob(".*-matrix-*.yaml")))
        backups = list((self.manager.state_dir / "profile-backups" / self.profile_id).glob("*.yaml"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)

    def test_external_profile_change_before_publish_is_preserved(self):
        original_identity = ctflab.source_identity(self.profile_path)
        external_bytes = self.profile_path.read_bytes() + b"\n# external change\n"
        calls = 0
        real_identity = ctflab.source_identity
        def changed_identity(path):
            nonlocal calls
            calls += 1
            if calls == 1:
                return original_identity
            self.profile_path.write_bytes(external_bytes)
            return real_identity(path)
        with mock.patch.object(ctflab, "source_identity", side_effect=changed_identity), \
                self.assertRaisesRegex(ctflab.CTFLabError, "发布前被外部修改"):
            self.manager.apply_matrix_candidate(self.profile_id, str(self.report_path), confirm=True)
        self.assertEqual(self.profile_path.read_bytes(), external_bytes)
        self.assertFalse(list(self.profile_dir.glob(".*-matrix-*.yaml")))


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


@unittest.skipUnless(os.environ.get("CTFLAB_BOOT_MATRIX_E2E") == "1"
                     and platform.system() == "Darwin", "需显式开启独立合成盘 QEMU 验收")
class SyntheticMatrixE2ETests(unittest.TestCase):
    def test_real_empty_disk_probe_preserves_base_and_cleans_owned_runtime(self):
        # QEMU UNIX QMP 路径上限很短；用受控短目录，避免测试环境路径长度冒充启动失败。
        with tempfile.TemporaryDirectory(prefix="cml-", dir="/private/tmp") as directory:
            root = pathlib.Path(directory)
            source = root / "empty.qcow2"
            subprocess.run([ctflab.qemu_img_path(), "create", "-f", "qcow2", str(source), "4M"],
                           check=True, capture_output=True)
            manager = LabManager(root / "state")
            profile = copy.deepcopy(BASE_PROFILE)
            profile["id"] = "smoke"
            pids = []
            run = manager.run
            def recorded_run(*args, **kwargs):
                states = run(*args, **kwargs)
                for state in states:
                    pids.append(state["pid"])
                    network = manager.network_state(state["lab_port"]) or {}
                    if network.get("pid"):
                        pids.append(network["pid"])
                return states
            with mock.patch.object(ctflab, "load_profile", return_value=profile), \
                    mock.patch.object(manager, "run", side_effect=recorded_run):
                image = manager.import_image("smoke", str(source))
                before = ctflab.sha256_file(pathlib.Path(image["base_path"]))
                try:
                    result = manager.boot_matrix("smoke", per_candidate_timeout=5, max_candidates=1)
                    self.assertFalse(result["succeeded"], "空盘和非黑画面不能成为可启动候选")
                    self.assertFalse((manager.runtime_dir / "smoke").exists())
                    self.assertTrue(pids)
                    self.assertTrue(all(not ctflab.bool_pid_alive(pid) for pid in pids))
                    self.assertEqual(ctflab.sha256_file(pathlib.Path(image["base_path"])), before)
                    subprocess.run([ctflab.qemu_img_path(), "check", image["base_path"]],
                                   check=True, capture_output=True)
                finally:
                    manager.stop(["smoke"])


if __name__ == "__main__":
    unittest.main()
