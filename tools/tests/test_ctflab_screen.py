#!/usr/bin/env python3
"""CTFLab 截图 OCR 与启动画面分类测试。"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from ctflab import classify_screen_text, classify_screenshot  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
