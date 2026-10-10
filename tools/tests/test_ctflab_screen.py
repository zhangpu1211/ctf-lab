#!/usr/bin/env python3
"""CTFLab 截图 OCR 与启动画面分类测试。"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from ctflab import (  # noqa: E402
    SCREEN_FAILURE_CLASSES,
    classify_screen_text,
    classify_screenshot,
    probe_recommendations,
    probe_verdict,
)
import ctflab  # noqa: E402


class ScreenTextClassificationTests(unittest.TestCase):
    def test_uefi_shell_is_distinguished(self) -> None:
        result = classify_screen_text(
            "UEFI Interactive Shell v2.2\nMapping table\nPress ESC to skip startup.nsh\nShell>"
        )
        self.assertEqual(result["classification"], "uefi_shell")
        self.assertEqual(result["confidence"], "high")

    def test_no_boot_device_is_distinguished(self) -> None:
        result = classify_screen_text("Boot failed: not a bootable disk. No bootable device.")
        self.assertEqual(result["classification"], "no_boot_device")
        self.assertEqual(result["confidence"], "high")

    def test_kernel_error_is_distinguished(self) -> None:
        result = classify_screen_text(
            "Kernel panic - not syncing: VFS: Unable to mount root fs on unknown-block(0,0)"
        )
        self.assertEqual(result["classification"], "kernel_error")
        self.assertEqual(result["confidence"], "high")

    def test_login_ready_wins_over_generic_boot_progress(self) -> None:
        result = classify_screen_text(
            "[ OK ] Started Login Service.\n"
            "[ OK ] Reached target Login Prompts.\n"
            "[ OK ] Reached target Graphical Interface.\n"
            "[FAILED] Failed to start Tomcat9."
        )
        self.assertEqual(result["classification"], "login_ready")
        self.assertEqual(result["confidence"], "high")
        self.assertIn("检测到服务启动失败文字", result["warnings"])

    def test_boot_progress_and_unknown(self) -> None:
        booting = classify_screen_text("Starting networking...\nMounting local filesystems...")
        self.assertEqual(booting["classification"], "boot_progress")
        self.assertEqual(booting["confidence"], "medium")
        self.assertEqual(classify_screen_text("")["classification"], "unknown")

    def test_pxe_boot_screen_is_recognized(self) -> None:
        """PXE 网络引导横幅必须被识别为独立失败类，而不是 unknown。"""
        result = classify_screen_text(">>Start PXE over IPv4")
        self.assertEqual(result["classification"], "pxe_network_boot")
        self.assertEqual(result["confidence"], "high")
        self.assertIn("Start PXE", result["matched_signals"])
        self.assertIn("pxe_network_boot", SCREEN_FAILURE_CLASSES)

    def test_pxe_ocr_degraded_sample_from_webserver_regression(self) -> None:
        """回归样本：2026-09-25 WebServer.ova 探测截图的真实退化 OCR 文本。

        Tesseract 把 "IPv4" 误读成 "[Pu4"；分类必须锚定 "start pxe over" 而非
        完整句子，否则该样本会落回 unknown 并被误判为磁盘启动候选。
        """
        degraded = classify_screen_text(">>Start PXE over [Pu4.\nge_liano")
        self.assertEqual(degraded["classification"], "pxe_network_boot")
        self.assertIn("Start PXE", degraded["matched_signals"])
        # 命中单个信号时置信度按失败类规则取 medium，但分类不依赖置信度
        self.assertEqual(degraded["confidence"], "medium")

    def test_pxe_exiting_rom_signal(self) -> None:
        result = classify_screen_text("PXE-M0F: Exiting PXE ROM.")
        self.assertEqual(result["classification"], "pxe_network_boot")


class ProbeVerdictTests(unittest.TestCase):
    """probe 结论判定：非磁盘引导画面不得成为启动矩阵可接受的候选。"""

    def test_pxe_must_not_be_disk_boot_candidate(self) -> None:
        """QEMU 在运行、画面非黑、DHCP 正常（宿主侧服务），也不得返回
        network_and_display_candidate。"""
        verdict = probe_verdict(
            protocol_ready=False,
            network_ready=True,
            display_active=True,
            process_running=True,
            screen_classification="pxe_network_boot",
        )
        self.assertEqual(verdict, "pxe_network_boot")
        self.assertNotIn(verdict, {"service_ready", "network_and_display_candidate",
                                   "display_activity_only"})

    def test_failure_screens_override_readiness_except_protocol(self) -> None:
        for classification in ("uefi_shell", "no_boot_device", "kernel_error",
                               "pxe_network_boot"):
            self.assertEqual(
                probe_verdict(protocol_ready=False, network_ready=True,
                              display_active=True, process_running=True,
                              screen_classification=classification),
                classification,
            )
        # 协议级就绪优先：真实服务应答时不被早先截图上的失败文字覆盖
        self.assertEqual(
            probe_verdict(protocol_ready=True, network_ready=True,
                          display_active=True, process_running=True,
                          screen_classification="pxe_network_boot"),
            "service_ready",
        )

    def test_pxe_recommendation_mentions_firmware_bus_boot_order(self) -> None:
        hints = probe_recommendations("pxe_network_boot")
        self.assertEqual(len(hints), 1)
        for keyword in ("固件", "磁盘总线", "启动顺序"):
            self.assertIn(keyword, hints[0])
        # 其他分类不产生建议；人工确认边界由 requires_human_review 保持
        self.assertEqual(probe_recommendations("uefi_shell"), [])
        self.assertEqual(probe_recommendations("login_ready"), [])
        self.assertEqual(probe_recommendations(None), [])

    def test_readiness_ordering_without_failure_screen(self) -> None:
        cases = [
            ((True, True, True, True), "service_ready"),
            ((False, True, True, True), "network_and_display_candidate"),
            ((False, False, True, True), "display_activity_only"),
            ((False, False, False, True), "process_running_no_readiness"),
            ((False, False, False, False), "qemu_exited"),
        ]
        for (protocol, network, display, process), expected in cases:
            self.assertEqual(
                probe_verdict(protocol_ready=protocol, network_ready=network,
                              display_active=display, process_running=process),
                expected,
            )


class ScreenshotOcrTests(unittest.TestCase):
    @mock.patch("ctflab.shutil.which", return_value=None)
    def test_missing_tesseract_degrades_safely(self, _which: mock.Mock) -> None:
        result = classify_screenshot(Path("missing.png"))
        self.assertFalse(result["available"])
        self.assertEqual(result["classification"], "unknown")
        self.assertIn("未安装 Tesseract", result["warnings"][0])

    @mock.patch("ctflab.subprocess.run")
    @mock.patch("ctflab.shutil.which", return_value="/usr/bin/tesseract")
    def test_tesseract_text_is_classified(
        self,
        _which: mock.Mock,
        run: mock.Mock,
    ) -> None:
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="UEFI Interactive Shell\nShell>",
            stderr="",
        )
        result = classify_screenshot(Path("screen.png"))
        self.assertTrue(result["available"])
        self.assertEqual(result["engine"], "tesseract")
        self.assertEqual(result["classification"], "uefi_shell")


class ProbeFlowTests(unittest.TestCase):
    def test_pxe_with_dhcp_exits_before_candidate_and_stops_own_instance(self):
        """实际 probe 调用链：识别 PXE 后立即回退，不只测试分类辅助函数。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = ctflab.LabManager(root)
            qmp = root / "qmp"
            qmp.touch()
            profile = {"readiness": {"checks": ["dhcp"]},
                       "detection": {"status": "candidate"}}
            state = {"pid": 9999, "qmp_path": str(qmp), "started_at": "test"}
            def qmp_call(_path, command, arguments=None):
                if command == "screendump":
                    Path(arguments["filename"]).touch()
                return {"status": "running"}
            pxe = ctflab.classify_screen_text(">>Start PXE over [Pu4.")
            with mock.patch("ctflab.load_profile", return_value=profile), \
                 mock.patch("ctflab.bool_pid_alive", return_value=True), \
                 mock.patch.object(manager, "runtime_state", side_effect=[None, state, state, state]), \
                 mock.patch.object(manager, "run") as run, \
                 mock.patch.object(manager, "stop") as stop, \
                 mock.patch.object(manager, "health", return_value=[{"name": "dhcp", "ok": True}]), \
                 mock.patch("ctflab.qmp_execute", side_effect=qmp_call), \
                 mock.patch("ctflab.ppm_display_activity", return_value={"active": True}), \
                 mock.patch("ctflab.classify_screenshot", return_value=pxe), \
                 mock.patch("ctflab.shutil.which", return_value=None), \
                 mock.patch("ctflab.time.sleep") as sleep:
                result = manager.probe("kali-arm64", abort_on_failure_screen=True)
            self.assertEqual(result["early_failure"], "pxe_network_boot")
            self.assertEqual(result["verdict"], "pxe_network_boot")
            self.assertTrue(result["requires_human_review"])
            self.assertTrue(result["recommendations"])
            run.assert_called_once()
            stop.assert_called_once_with(["kali-arm64"])
            sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
