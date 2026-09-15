#!/usr/bin/env python3
"""导入完整性回归：不得静默信任没有可信 base_sha256 登记的既有基盘。

覆盖：

- 目标 `base-*.qcow2` 已存在但没有登记时，必须由 qemu-img compare 证明内容一致才登记；
  内容不一致或无法比较时明确拒绝，且不改写既有文件、不写入状态；
- 已有登记时，重复导入必须核对当前哈希，不一致拒绝静默重新登记；
- 新转换写入临时文件，info/check 通过后发布，登记后基盘为只读；
- 提示信息不再指向删除 image.json。
"""

from __future__ import annotations

import copy
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import ctflab  # noqa: E402

PROFILE_ID = "smoke"


def fake_run(command, *, capture=True):
    if len(command) > 1 and command[1] == "convert":
        pathlib.Path(command[-1]).write_bytes(b"converted-base")
    return subprocess.CompletedProcess(command, 0, "", "")


class ImportIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.manager = ctflab.LabManager(self.root / "state")
        self.source = self.root / "source.qcow2"
        self.source.write_bytes(b"source-image-bytes" * 32)
        self.source_hash = ctflab.sha256_file(self.source)
        self.image_dir = self.manager.images_dir / PROFILE_ID
        self.image_dir.mkdir(parents=True)
        self.base_name = f"base-{self.source_hash[:12]}.qcow2"

    @property
    def base_path(self) -> pathlib.Path:
        return self.image_dir / self.base_name

    @property
    def state_path(self) -> pathlib.Path:
        return self.manager.image_state_path(PROFILE_ID)

    def import_with(self, *, compare_result=None, compare_error=None, qemu_info=None, run_command=None):
        if compare_error is not None:
            compare_patch = mock.patch.object(ctflab, "compare_disk_images", side_effect=compare_error)
        else:
            compare_patch = mock.patch.object(ctflab, "compare_disk_images", return_value=compare_result)
        with mock.patch.object(ctflab, "qemu_img_path", return_value="/usr/bin/qemu-img"), \
                mock.patch.object(ctflab, "qemu_info",
                                  return_value=qemu_info or {"format": "qcow2", "virtual-size": 1024}), \
                compare_patch, \
                mock.patch.object(ctflab, "run_command", side_effect=run_command or fake_run):
            return self.manager.import_image(PROFILE_ID, str(self.source))

    def state(self) -> dict:
        return ctflab.read_json(self.state_path) or {}

    # ---- 已有目标基盘、但没有登记 ----------------------------------------

    def test_existing_unregistered_base_requires_compare(self) -> None:
        self.base_path.write_bytes(b"untrusted-existing-base")
        with self.assertRaises(ctflab.CTFLabError) as raised:
            self.import_with(compare_result=False)
        message = str(raised.exception)
        self.assertIn("拒绝登记该文件", message)
        self.assertIn("完整性迁移流程", message)
        self.assertNotIn("image.json", message, "不得再提示删除 image.json")
        self.assertEqual(self.base_path.read_bytes(), b"untrusted-existing-base",
                         "被拒绝的既有文件不得被改写")
        self.assertFalse(self.state_path.exists(), "拒绝时不得写入登记状态")

    def test_compare_proven_base_is_registered_and_read_only(self) -> None:
        self.base_path.write_bytes(b"compare-proven-base")
        state = self.import_with(compare_result=True)
        self.assertEqual(state["base_sha256"], ctflab.sha256_file(self.base_path))
        self.assertEqual(state["base_sha256_evidence"], "qemu-img-compare")
        self.assertEqual(stat.S_IMODE(self.base_path.stat().st_mode), 0o444)
        self.assertEqual(self.state()["base_sha256"], state["base_sha256"])

    def test_indeterminate_compare_is_refused(self) -> None:
        self.base_path.write_bytes(b"untrusted-existing-base")
        with self.assertRaises(ctflab.CTFLabError) as raised:
            self.import_with(compare_error=ctflab.CTFLabError("qemu-img compare 无法完成"))
        self.assertIn("无法完成", str(raised.exception))
        self.assertFalse(self.state_path.exists())
        self.assertEqual(self.base_path.read_bytes(), b"untrusted-existing-base")

    # ---- 新转换 ----------------------------------------------------------

    def test_new_conversion_uses_temp_then_publishes_read_only(self) -> None:
        state = self.import_with(compare_result=True)
        self.assertTrue(self.base_path.is_file())
        self.assertEqual(self.base_path.read_bytes(), b"converted-base")
        self.assertEqual(state["base_sha256"], ctflab.sha256_file(self.base_path))
        self.assertEqual(state["base_sha256_evidence"], "converted")
        self.assertEqual(stat.S_IMODE(self.base_path.stat().st_mode), 0o444)
        leftovers = [entry.name for entry in self.image_dir.iterdir() if ".partial-" in entry.name]
        self.assertEqual(leftovers, [], "转换临时文件必须清理")

    def test_conversion_failure_leaves_no_base_or_state(self) -> None:
        def failing_run(command, *, capture=True):
            raise ctflab.CTFLabError("模拟转换失败")

        with self.assertRaises(ctflab.CTFLabError):
            self.import_with(compare_result=True, run_command=failing_run)
        self.assertFalse(self.base_path.exists())
        self.assertFalse(self.state_path.exists())
        leftovers = [entry.name for entry in self.image_dir.iterdir() if ".partial-" in entry.name]
        self.assertEqual(leftovers, [])

    # ---- 重复导入 --------------------------------------------------------

    def test_reimport_with_registered_hash_mismatch_is_refused(self) -> None:
        self.base_path.write_bytes(b"registered-base")
        ctflab.write_json(self.state_path, {
            "schema": 1,
            "profile_id": PROFILE_ID,
            "source_path": str(self.source),
            "source_sha256": self.source_hash,
            "base_path": str(self.base_path),
            "base_sha256": "d" * 64,
        })
        with self.assertRaises(ctflab.CTFLabError) as raised:
            self.import_with(compare_result=True)
        message = str(raised.exception)
        self.assertIn("拒绝静默重新登记", message)
        self.assertNotIn("image.json", message)
        self.assertEqual(self.state()["base_sha256"], "d" * 64, "拒绝时不得改写已有登记")

    def test_reimport_without_registration_requires_compare(self) -> None:
        self.base_path.write_bytes(b"legacy-base")
        legacy_state = {
            "schema": 1,
            "profile_id": PROFILE_ID,
            "source_path": str(self.source),
            "source_sha256": self.source_hash,
            "source_format": "qcow2",
            "base_path": str(self.base_path),
            "imported_at": "2026-09-01T00:00:00+00:00",
        }
        ctflab.write_json(self.state_path, legacy_state)
        with self.assertRaises(ctflab.CTFLabError) as raised:
            self.import_with(compare_result=False)
        self.assertIn("缺少 base_sha256", str(raised.exception))
        self.assertNotIn("base_sha256", self.state(), "拒绝时不得补登记")

        state = self.import_with(compare_result=True)
        self.assertEqual(state["base_sha256"], ctflab.sha256_file(self.base_path))
        self.assertEqual(state["base_sha256_evidence"], "qemu-img-compare")
        self.assertEqual(state["imported_at"], "2026-09-01T00:00:00+00:00",
                         "补登记不得丢掉既有字段")
        self.assertEqual(self.state()["base_sha256"], state["base_sha256"])

    def test_reimport_with_matching_registration_is_idempotent(self) -> None:
        self.base_path.write_bytes(b"registered-base")
        state = {
            "schema": 1,
            "profile_id": PROFILE_ID,
            "source_path": str(self.source),
            "source_sha256": self.source_hash,
            "base_path": str(self.base_path),
            "base_sha256": ctflab.sha256_file(self.base_path),
        }
        ctflab.write_json(self.state_path, state)
        with mock.patch.object(ctflab, "compare_disk_images") as compare:
            result = self.import_with(compare_result=True)
        compare.assert_not_called()
        self.assertEqual(result, state)


@unittest.skipUnless(__import__("shutil").which("qemu-img"), "需要 qemu-img")
class RealCompareSemanticsTests(unittest.TestCase):
    """验证 qemu-img compare -s 的退出码语义：0=一致、1=内容/容量不同。

    默认模式（无 -s）只警告尺寸不一致并仍返回 0，必须使用严格模式。
    """

    def test_compare_detects_identical_different_content_and_size(self) -> None:
        import shutil as shutil_module

        qemu_img = shutil_module.which("qemu-img")
        qemu_io = shutil_module.which("qemu-io")
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "source.qcow2"
            subprocess.run([qemu_img, "create", "-f", "qcow2", str(source), "16M"],
                           check=True, capture_output=True)
            identical = root / "identical.qcow2"
            subprocess.run([qemu_img, "convert", "-f", "qcow2", "-O", "qcow2",
                            str(source), str(identical)], check=True, capture_output=True)
            different_content = root / "different-content.qcow2"
            subprocess.run([qemu_img, "convert", "-f", "qcow2", "-O", "qcow2",
                            str(source), str(different_content)], check=True, capture_output=True)
            if qemu_io:
                subprocess.run([qemu_io, "-f", "qcow2", "-c", "write -P 0x41 0 512",
                                str(different_content)], check=True, capture_output=True)
            different_size = root / "different-size.qcow2"
            subprocess.run([qemu_img, "create", "-f", "qcow2", str(different_size), "32M"],
                           check=True, capture_output=True)
            with mock.patch.object(ctflab, "qemu_img_path", return_value=qemu_img):
                self.assertTrue(ctflab.compare_disk_images(source, "qcow2", identical))
                if qemu_io:
                    self.assertFalse(ctflab.compare_disk_images(source, "qcow2", different_content))
                # 尺寸不同必须判为不可信（默认模式会误判为一致，因此代码必须带 -s）。
                self.assertFalse(ctflab.compare_disk_images(source, "qcow2", different_size))


if __name__ == "__main__":
    unittest.main()
