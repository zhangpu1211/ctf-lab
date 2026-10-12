#!/usr/bin/env python3
"""OVA/VMDK 导入链路回归：安全解包、显式选盘与占用登记（qemu-img 小夹具）。"""

from __future__ import annotations

from pathlib import Path
import io
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import ctflab  # noqa: E402
from ctflab import CTFLabError, LabManager  # noqa: E402
from ctflab_inspect import InspectionError, inspect_image  # noqa: E402
import ctflab_inspect

PROFILE = "smoke"


def run_qemu_img(*args: str) -> None:
    subprocess.run([ctflab.qemu_img_path(), *args], check=True, capture_output=True)


class OvaImportTests(unittest.TestCase):
    def test_cancel_unpack_cleans_owned_stage_and_preserves_archive(self):
        cancel = self.root / "cancel"
        before = ctflab.sha256_file(self.single)
        locations = []
        copy = ctflab_inspect.copy_tar_member
        def cancel_copy(archive, member, destination):
            locations.append(destination.parent)
            cancel.touch()
            copy(archive, member, destination)
        with ctflab.import_session(cancel), \
                mock.patch.object(ctflab_inspect, "copy_tar_member", side_effect=cancel_copy), \
                self.assertRaisesRegex(InspectionError, "安全取消"):
            with ctflab_inspect.prepare_ova(self.single):
                self.fail("取消不得进入完成暂存")
        self.assertTrue(locations)
        self.assertTrue(all(not location.exists() for location in locations))
        self.assertEqual(ctflab.sha256_file(self.single), before)

    def test_real_failed_onboard_resume_completes_without_rewriting_candidate(self):
        cancel = self.root / "cancel"
        env = {"CTFLAB_PROFILE_DIR": str(self.root / "profiles"),
               "CTFLAB_IMPORT_CANCEL_FILE": str(cancel)}
        args = ["--state-dir", str(self.root / "resume-state"), "onboard", str(self.single), "--id", "resume-box"]
        convert = ctflab.run_import_conversion
        def cancel_convert(command):
            cancel.touch()
            convert(command)
        before = ctflab.sha256_file(self.single)
        with mock.patch.dict(os.environ, env):
            with mock.patch.object(ctflab, "run_import_conversion", side_effect=cancel_convert):
                self.assertEqual(ctflab.main(args), 2)
            profile = self.root / "profiles" / "resume-box.yaml"
            original = profile.read_bytes()
            cancel.unlink()
            self.assertEqual(ctflab.main(args + ["--resume"]), 0)
            self.assertEqual(profile.read_bytes(), original)
            state = ctflab.LabManager(self.root / "resume-state").image_state("resume-box")
            self.assertEqual(state["source_sha256"], before)
            run_qemu_img("check", str(state["base_path"]))
        self.assertEqual(ctflab.sha256_file(self.single), before)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.manager = LabManager(self.root / "state")
        # 真实 VMDK 小盘：qemu-img 原生支持创建与转换，无需虚拟机。
        run_qemu_img("create", "-f", "vmdk", str(self.root / "disk1.vmdk"), "4M")
        run_qemu_img("create", "-f", "vmdk", str(self.root / "disk2.vmdk"), "8M")
        self.ovf = self.root / "machine.ovf"
        self.ovf.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Envelope xmlns="http://schemas.dmtf.org/ovf/envelope/1">'
            "<VirtualSystem/></Envelope>", encoding="utf-8")
        self.single = self._pack_ova("single.ova", ["machine.ovf", "disk1.vmdk"])
        self.multi = self._pack_ova("multi.ova", ["machine.ovf", "disk1.vmdk", "disk2.vmdk"])

    def _pack_ova(self, name: str, members: list[str], unsafe_member: str | None = None) -> Path:
        target = self.root / name
        with tarfile.open(target, "w") as archive:
            for member in members:
                archive.add(self.root / member, arcname=member)
            if unsafe_member is not None:
                payload = b"evil"
                info = tarfile.TarInfo(unsafe_member)
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
        return target

    # ---- 只读识别 ---------------------------------------------------------

    def test_prepared_ova_is_shared_by_inspection_and_real_conversion(self):
        with mock.patch.object(ctflab_inspect, "find_disk_and_ovf",
                               wraps=ctflab_inspect.find_disk_and_ovf) as locate:
            with ctflab_inspect.prepare_ova(self.single) as prepared:
                staged = prepared.located[0]
                report = inspect_image(self.single, calculate_hash=False, _prepared_ova=prepared)
                state = self.manager.import_image(PROFILE, str(self.single), _prepared_ova=prepared)
                self.assertEqual(report["format"], "vmdk")
                self.assertEqual(state["source_sha256"], ctflab.sha256_file(self.single))
                self.assertTrue(staged.exists())
            self.assertEqual(locate.call_count, 1, "整个识别+转换只展开一次 OVA")
            self.assertFalse(staged.exists(), "上下文结束必须清理暂存")

    def test_prepared_ova_rejects_source_change_and_cleans_up(self):
        with ctflab_inspect.prepare_ova(self.single) as prepared:
            staged = prepared.located[0]
            with self.single.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(CTFLabError, "发生变化"):
                self.manager.import_image(PROFILE, str(self.single), _prepared_ova=prepared)
            self.assertEqual(self._image_state(), {})
        self.assertFalse(staged.exists())

    def test_prepared_ova_rejects_different_selection(self):
        with ctflab_inspect.prepare_ova(self.multi, "disk1.vmdk") as prepared:
            with self.assertRaisesRegex(CTFLabError, "选盘"):
                self.manager.import_image(PROFILE, str(self.multi), ova_disk="disk2.vmdk",
                                          _prepared_ova=prepared)
        self.assertEqual(self._image_state(), {})

    def test_low_temporary_space_rejects_before_extract(self):
        with mock.patch.object(ctflab_inspect.shutil, "disk_usage", return_value=SimpleNamespace(free=0)), \
                mock.patch.object(ctflab_inspect, "copy_tar_member") as copy:
            with self.assertRaisesRegex(InspectionError, "OVA 解包空间不足"):
                with ctflab_inspect.prepare_ova(self.single):
                    self.fail("不得进入暂存上下文")
        copy.assert_not_called()

    def test_conversion_space_failure_does_not_publish_base(self):
        with ctflab_inspect.prepare_ova(self.single) as prepared:
            with mock.patch.object(ctflab, "require_free_space", side_effect=InspectionError("转换空间不足")):
                with self.assertRaisesRegex(CTFLabError, "转换空间不足"):
                    self.manager.import_image(PROFILE, str(self.single), _prepared_ova=prepared)
        self.assertEqual(self._image_state(), {})
        self.assertFalse(list((self.manager.images_dir / PROFILE).glob("*.qcow2")))

    def test_real_onboard_uses_single_unpack_and_cleans_on_failure(self):
        args = ctflab.build_parser().parse_args(["onboard", str(self.single), "--id", "perf-box"])
        with mock.patch.dict(os.environ, {"CTFLAB_PROFILE_DIR": str(self.root / "profiles")}), \
                mock.patch.object(ctflab_inspect, "find_disk_and_ovf",
                                  wraps=ctflab_inspect.find_disk_and_ovf) as locate, \
                mock.patch.object(self.manager, "import_image", side_effect=CTFLabError("模拟转换失败")) as importer:
            with self.assertRaisesRegex(CTFLabError, "模拟转换失败"):
                ctflab.cmd_onboard(self.manager, args)
        self.assertEqual(locate.call_count, 1)
        staged = importer.call_args.kwargs["_prepared_ova"].located[0]
        self.assertFalse(staged.exists(), "接入失败也清理暂存")

    def test_inspect_single_ova_reports_disk_selection(self):
        report = inspect_image(self.single, calculate_hash=False)
        self.assertEqual(report["disks"], ["disk1.vmdk"])
        self.assertEqual(report["selected_disk"], "disk1.vmdk")
        self.assertEqual(report["format"], "vmdk")
        self.assertEqual(report["virtual_size"], 4 * 1024 * 1024)

    def test_inspect_multi_ova_defaults_to_first_with_warning(self):
        report = inspect_image(self.multi, calculate_hash=False)
        self.assertEqual(report["disks"], ["disk1.vmdk", "disk2.vmdk"])
        self.assertEqual(report["selected_disk"], "disk1.vmdk")
        self.assertTrue(any("只使用第一个" in item for item in report["warnings"]))

    def test_inspect_multi_ova_preferred_disk_selects_and_verifies(self):
        report = inspect_image(self.multi, calculate_hash=False,
                               preferred_disk="disk2.vmdk")
        self.assertEqual(report["selected_disk"], "disk2.vmdk")
        self.assertEqual(report["virtual_size"], 8 * 1024 * 1024)
        self.assertFalse(any("只使用第一个" in item for item in report["warnings"]))

    def test_inspect_missing_preferred_disk_lists_alternatives(self):
        with self.assertRaisesRegex(InspectionError, "可用磁盘.*disk1"):
            inspect_image(self.multi, calculate_hash=False, preferred_disk="nope.vmdk")

    def test_inspect_rejects_unsafe_member_paths(self):
        unsafe = self._pack_ova("unsafe.ova", ["disk1.vmdk"], unsafe_member="../evil.vmdk")
        with self.assertRaisesRegex(InspectionError, "不安全路径"):
            inspect_image(unsafe, calculate_hash=False)

    # ---- 导入（真实转换） --------------------------------------------------

    def _image_state(self) -> dict:
        return ctflab.read_json(self.manager.image_state_path(PROFILE)) or {}

    def test_import_single_ova_converts_vmdk_and_records_selection(self):
        state = self.manager.import_image(PROFILE, str(self.single))
        self.assertEqual(state["source_format"], "vmdk")
        self.assertEqual(state["ova_disk"], "disk1.vmdk")
        self.assertEqual(state["ova_disk_count"], 1)
        self.assertEqual(state["virtual_size"], 4 * 1024 * 1024)
        base = Path(state["base_path"])
        self.assertTrue(base.is_file())
        self.assertEqual(ctflab.qemu_info(base).get("format"), "qcow2")
        self.assertEqual(self._image_state()["ova_disk"], "disk1.vmdk")

    def test_import_multi_ova_requires_explicit_disk(self):
        with self.assertRaisesRegex(CTFLabError, "2 个磁盘.*disk1.vmdk.*disk2.vmdk"):
            self.manager.import_image(PROFILE, str(self.multi))
        self.assertEqual(self._image_state(), {})

    def test_import_multi_ova_with_explicit_disk_uses_it(self):
        state = self.manager.import_image(PROFILE, str(self.multi), ova_disk="disk2.vmdk")
        self.assertEqual(state["ova_disk"], "disk2.vmdk")
        self.assertEqual(state["ova_disk_count"], 2)
        self.assertEqual(state["virtual_size"], 8 * 1024 * 1024)

    def test_import_multi_ova_unknown_disk_is_rejected(self):
        with self.assertRaisesRegex(CTFLabError, "指定的磁盘不存在"):
            self.manager.import_image(PROFILE, str(self.multi), ova_disk="nope.vmdk")

    # ---- CLI 接线 ----------------------------------------------------------

    def test_cli_wires_disk_flags(self):
        parser = ctflab.build_parser()
        self.assertEqual(parser.parse_args(["import", PROFILE, "/tmp/x.ova",
                                            "--disk", "sys.vmdk"]).disk, "sys.vmdk")
        self.assertEqual(parser.parse_args(["inspect", "/tmp/x.ova",
                                            "--disk", "sys.vmdk"]).disk, "sys.vmdk")
        self.assertEqual(parser.parse_args(["onboard", "/tmp/x.ova", "--id", "box-1",
                                            "--disk", "sys.vmdk"]).disk, "sys.vmdk")


if __name__ == "__main__":
    unittest.main()
