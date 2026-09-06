#!/usr/bin/env python3
"""CTFLab 跨进程操作锁的回归测试。"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from ctflab import LabManager  # noqa: E402


class OperationLockTests(unittest.TestCase):
    def test_lock_is_reentrant_in_one_manager(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = LabManager(Path(directory))
            with manager.operation_lock("外层"):
                with manager.operation_lock("内层"):
                    self.assertEqual(manager._operation_lock_depth, 2)
            self.assertEqual(manager._operation_lock_depth, 0)

    def test_competing_process_gets_actionable_error(self) -> None:
        child_code = textwrap.dedent(
            """
            from pathlib import Path
            import sys

            sys.path.insert(0, sys.argv[1])
            from ctflab import CTFLabError, LabManager

            manager = LabManager(Path(sys.argv[2]))
            try:
                with manager.operation_lock("子进程", timeout_seconds=0.15):
                    pass
            except CTFLabError as exc:
                print(exc)
                raise SystemExit(23)
            """
        )
        with tempfile.TemporaryDirectory() as directory:
            manager = LabManager(Path(directory))
            with manager.operation_lock("父进程测试"):
                result = subprocess.run(
                    [sys.executable, "-c", child_code, str(TOOLS_DIR), directory],
                    check=False,
                    text=True,
                    capture_output=True,
                )
        self.assertEqual(result.returncode, 23)
        self.assertIn(f"PID {os.getpid()}", result.stdout)
        self.assertIn("父进程测试", result.stdout)
        self.assertIn("请稍后重试", result.stdout)

    def test_lock_is_released_after_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = LabManager(Path(directory))
            with self.assertRaisesRegex(RuntimeError, "测试异常"):
                with first.operation_lock("异常路径"):
                    raise RuntimeError("测试异常")

            second = LabManager(Path(directory))
            with second.operation_lock("异常后重试", timeout_seconds=0.1):
                self.assertEqual(second._operation_lock_depth, 1)


if __name__ == "__main__":
    unittest.main()
