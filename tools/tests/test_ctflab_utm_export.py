#!/usr/bin/env python3
"""路径 A（UTM 导出）最小切片的单元测试。

覆盖：

- golden fixture：脱敏、哈希固定的 UTM 4.7.5 结构（Display 单元素数组、MemorySize(MiB)、
  Target=virt、Data/data.qcow2、InterfaceVersion、QEMU.UEFIBoot/AdditionalArguments、
  Network=[]、Sharing.ClipboardSharing=false、无 CTFLabMappingStatus）；
- 基盘完整性：新导入登记 base_sha256；旧记录缺少 base_sha256 明确拒绝；导出前修改基盘必须拒绝；
- 原子输出：构建期间最终 .utm 不出现、失败清理临时文件、既有文件与隐藏文件不被覆盖、
  清单发布失败回滚本次发布的包；
- 转换校验：qemu-img info 必须确认 qcow2、qemu-img check 必须通过；
- 隐私：导出清单不含任何绝对路径。

真实 UTM E2E（xrandr 跟随、剪贴板负向、网络三层隔离）不在本文件范围，见设计文档 2.4 第 5 条。
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import pathlib
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout
from unittest import mock

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import ctflab  # noqa: E402
import ctflab_utm  # noqa: E402

PROFILE_ID = "kali-arm64"
BUNDLE_NAME = f"{PROFILE_ID}.utm"
MANIFEST_NAME = f"{PROFILE_ID}.utm.export.json"
DISK_RELATIVE = pathlib.Path("Data") / "data.qcow2"


def fake_convert(source: pathlib.Path, destination: pathlib.Path) -> None:
    destination.write_bytes(b"converted-qcow2:" + source.read_bytes()[:32])


def fake_nvram_convert(source: pathlib.Path, destination: pathlib.Path) -> None:
    destination.write_bytes(b"converted-nvram-qcow2:" + source.read_bytes()[:32])


def fake_info(path: pathlib.Path) -> dict:
    return {"format": "qcow2", "virtual-size": 33554432}


def fake_check(path: pathlib.Path) -> None:
    return None


class ExportTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.out_dir = self.root / "out"
        self.base_path = self.root / "base.qcow2"
        self.base_path.write_bytes(b"base-image-bytes" * 128)
        self.nvram_path = self.root / "uefi-vars.fd"
        self.nvram_path.write_bytes(b"raw-nvram-bytes" * 64)
        self.manager = ctflab.LabManager(self.root / "state")
        self.profile = copy.deepcopy(ctflab.load_profile(PROFILE_ID))
        self.write_image_state()
        # 默认隔离本机 UTM 库与 utmctl，测试不依赖真实环境。
        self.real_known_utm_bundle_names = ctflab_utm.known_utm_bundle_names
        for target, value in (
            ("known_utm_bundle_names", set()),
            ("detect_utm_version", None),
        ):
            patcher = mock.patch.object(ctflab_utm, target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_image_state(self, **overrides) -> dict:
        state = {
            "schema": 1,
            "profile_id": PROFILE_ID,
            "source_path": str(self.root / "missing-source.qcow2"),
            "source_sha256": "a" * 64,
            "base_path": str(self.base_path),
            "base_sha256": ctflab.sha256_file(self.base_path),
            "uefi_vars_path": str(self.nvram_path),
            "uefi_vars_sha256": ctflab.sha256_file(self.nvram_path),
        }
        state.update(overrides)
        ctflab.write_json(self.manager.image_state_path(PROFILE_ID), state)
        return state

    def export(self, **kwargs):
        kwargs.setdefault("convert", fake_convert)
        kwargs.setdefault("nvram_convert", fake_nvram_convert)
        kwargs.setdefault("info", fake_info)
        kwargs.setdefault("check", fake_check)
        kwargs.setdefault("generated_at", "2026-09-14T00:00:00+00:00")
        kwargs.setdefault("profile", self.profile)
        kwargs.setdefault("image_state", self.manager.image_state(PROFILE_ID))
        kwargs.setdefault("out_dir", self.out_dir)
        kwargs.setdefault("profile_id", PROFILE_ID)
        return ctflab_utm.export_utm_package(**kwargs)

    @property
    def bundle(self) -> pathlib.Path:
        return self.out_dir / BUNDLE_NAME

    @property
    def manifest_path(self) -> pathlib.Path:
        return self.out_dir / MANIFEST_NAME

    def temp_leftovers(self) -> list[str]:
        if not self.out_dir.exists():
            return []
        return sorted(entry.name for entry in self.out_dir.iterdir()
                      if entry.name.startswith(f".{PROFILE_ID}-"))


class GoldenStructureTests(ExportTestCase):
    """生成配置必须与本机 UTM 4.7.5 的脱敏结构一致。"""

    def load_plist(self) -> dict:
        return plistlib.loads((self.bundle / "config.plist").read_bytes())

    def test_generated_config_matches_sanitized_structure(self) -> None:
        self.export()
        plist = self.load_plist()
        fixture = ctflab_utm.load_fixture()
        expected = copy.deepcopy(fixture["config_structure"])
        expected["Information"]["Name"] = PROFILE_ID
        expected["System"]["CPUCount"] = self.profile["guest"]["cpus"]
        expected["System"]["MemorySize"] = self.profile["guest"]["memory_mb"]
        self.assertEqual(set(plist), set(expected))
        self.assertEqual(plist["Backend"], "QEMU")
        self.assertEqual(plist["ConfigurationVersion"], 4)
        self.assertEqual(plist["Information"]["Icon"], "linux")
        self.assertIs(plist["Information"]["IconCustom"], False)
        self.assertEqual(plist["Information"]["Name"], PROFILE_ID)
        uuid.UUID(plist["Information"]["UUID"])
        self.assertEqual(plist["System"], expected["System"])
        drive = plist["Drive"][0]
        self.assertEqual(set(drive), set(expected["Drive"][0]))
        uuid.UUID(drive["Identifier"])
        self.assertNotEqual(drive["Identifier"], plist["Information"]["UUID"])
        for key in ("ImageName", "ImageType", "Interface", "InterfaceVersion", "ReadOnly"):
            self.assertEqual(drive[key], expected["Drive"][0][key])
        self.assertEqual(plist["Display"], expected["Display"])
        self.assertEqual(plist["Network"], [])
        self.assertEqual(plist["QEMU"], expected["QEMU"])
        self.assertEqual(plist["Sharing"], expected["Sharing"])

    def test_display_is_single_element_array_with_dynamic_resolution(self) -> None:
        self.export()
        display = self.load_plist()["Display"]
        self.assertIsInstance(display, list)
        self.assertEqual(len(display), 1)
        self.assertIs(display[0]["DynamicResolution"], True)
        self.assertEqual(display[0]["Hardware"], "virtio-gpu-pci")
        self.assertIs(display[0]["NativeResolution"], False)

    def test_system_uses_memory_size_mib_and_target_virt(self) -> None:
        self.export()
        system = self.load_plist()["System"]
        self.assertEqual(system["Architecture"], "aarch64")
        self.assertEqual(system["Target"], "virt")
        self.assertEqual(system["MemorySize"], self.profile["guest"]["memory_mb"])
        self.assertNotIn("Memory", system)
        self.assertEqual(system["CPUCount"], self.profile["guest"]["cpus"])

    def test_disk_uses_data_directory_and_bare_image_name(self) -> None:
        self.export()
        self.assertTrue((self.bundle / DISK_RELATIVE).is_file())
        self.assertFalse((self.bundle / "Images").exists())
        drive = self.load_plist()["Drive"][0]
        self.assertEqual(drive["ImageName"], "data.qcow2")
        self.assertEqual(drive["InterfaceVersion"], 1)
        self.assertEqual(drive["Interface"], "VirtIO")
        self.assertEqual(drive["ImageType"], "Disk")
        self.assertIs(drive["ReadOnly"], False)

    def test_qemu_uefi_and_no_additional_arguments(self) -> None:
        self.export()
        qemu = self.load_plist()["QEMU"]
        self.assertEqual(qemu, {
            "DebugLog": False,
            "UEFIBoot": True,
            "RNGDevice": True,
            "BalloonDevice": False,
            "TPMDevice": False,
            "Hypervisor": True,
            "TSO": False,
            "RTCLocalTime": False,
            "PS2Controller": False,
            "AdditionalArguments": [],
        })

    def test_input_section_matches_source_key_names(self) -> None:
        self.export()
        self.assertEqual(self.load_plist()["Input"],
                         {"UsbBusSupport": "3.0", "UsbSharing": False, "MaximumUsbShare": 3})

    def test_system_cpu_is_default_from_reference_structure(self) -> None:
        self.export()
        self.assertEqual(self.load_plist()["System"]["CPU"], "default")

    def test_network_and_clipboard_are_explicit(self) -> None:
        self.export()
        plist = self.load_plist()
        self.assertEqual(plist["Network"], [], "路径 A 默认必须不带网卡")
        self.assertEqual(plist["Serial"], [], "顶层 Serial 段必须存在且为空（禁止串口）")
        self.assertEqual(plist["Sound"], [], "顶层 Sound 段必须存在且为空（禁止音频设备）")
        self.assertEqual(plist["Sharing"], {
            "DirectoryShareMode": "None",
            "DirectoryShareReadOnly": False,
            "ClipboardSharing": False,
        })
        raw = (self.bundle / "config.plist").read_text(encoding="utf-8")
        for forbidden in ("CTFLabMappingStatus", "PortForward", "SharedFolder", "MacAddress",
                          "WebDAV", "VirtFS"):
            self.assertNotIn(forbidden, raw, f"生成配置不得包含 {forbidden}")

    def test_plist_root_keys_match_fixture_whitelist(self) -> None:
        self.export()
        self.assertEqual(set(self.load_plist()), set(ctflab_utm.ALLOWED_CONFIG_KEYS))


class BaseIntegrityTests(ExportTestCase):
    def test_missing_base_sha256_is_refused_with_hint(self) -> None:
        state = self.write_image_state(base_sha256=None)
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            self.export(image_state=state)
        message = str(raised.exception)
        self.assertIn("base_sha256", message)
        self.assertIn("不会静默信任", message)
        self.assertIn("重新执行 import", message)
        self.assertIn("完整性迁移流程", message)
        self.assertNotIn("image.json", message, "不得再提示删除 image.json")
        self.assertFalse(self.bundle.exists())

    def test_base_image_modified_after_registration_is_rejected(self) -> None:
        self.base_path.write_bytes(b"tampered-after-registration")
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            self.export()
        self.assertIn("与登记值不一致", str(raised.exception))
        self.assertFalse(self.bundle.exists())
        self.assertFalse(self.manifest_path.exists())

    def test_source_matching_registry_is_recorded(self) -> None:
        source = self.root / "source.qcow2"
        source.write_bytes(b"original-source")
        state = self.write_image_state(
            source_path=str(source),
            source_sha256=ctflab.sha256_file(source),
        )
        manifest = self.export(image_state=state)
        self.assertEqual(manifest["source_image"]["source_recheck"], "source-matches-recorded")
        self.assertEqual(manifest["source_image"]["file"], source.name)

    def test_source_registry_mismatch_is_rejected(self) -> None:
        source = self.root / "source.qcow2"
        source.write_bytes(b"changed-source")
        state = self.write_image_state(source_path=str(source), source_sha256="b" * 64)
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            self.export(image_state=state)
        self.assertIn("哈希与导入登记值不一致", str(raised.exception))

    def test_missing_image_state_is_rejected(self) -> None:
        with self.assertRaises(ctflab_utm.UTMExportError):
            self.export(image_state=None)

    def test_missing_base_image_is_rejected(self) -> None:
        state = self.write_image_state(base_path=str(self.root / "gone.qcow2"))
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            self.export(image_state=state)
        self.assertIn("基础镜像不存在", str(raised.exception))

    def test_missing_recorded_sha256_is_rejected(self) -> None:
        state = self.write_image_state(source_sha256="")
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            self.export(image_state=state)
        self.assertIn("缺少来源 SHA-256", str(raised.exception))


class NvramTests(ExportTestCase):
    """UEFI NVRAM：要求、哈希、RAW→QCOW2 转换、info/check 与输入只读。"""

    def test_missing_nvram_is_refused(self) -> None:
        state = self.write_image_state(uefi_vars_path=str(self.root / "gone.fd"))
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            self.export(image_state=state)
        self.assertIn("UEFI NVRAM 不存在", str(raised.exception))

    def test_missing_nvram_sha256_is_refused(self) -> None:
        state = self.write_image_state(uefi_vars_sha256="")
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            self.export(image_state=state)
        self.assertIn("缺少 uefi_vars_sha256", str(raised.exception))

    def test_nvram_hash_mismatch_is_refused(self) -> None:
        state = self.write_image_state(uefi_vars_sha256="c" * 64)
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            self.export(image_state=state)
        self.assertIn("NVRAM SHA-256 与登记值不一致", str(raised.exception))
        self.assertFalse(self.bundle.exists())

    def test_unsupported_variant_combinations_are_refused(self) -> None:
        aarch64_bios = copy.deepcopy(self.profile)
        aarch64_bios["guest"]["firmware"] = "bios"
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            self.export(profile=aarch64_bios)
        self.assertIn("aarch64+bios", str(raised.exception))
        x86_uefi = copy.deepcopy(self.profile)
        x86_uefi["guest"]["architecture"] = "x86_64"
        with self.assertRaises(ctflab_utm.UTMExportError) as raised2:
            self.export(profile=x86_uefi)
        self.assertIn("x86_64+uefi", str(raised2.exception))

    def test_nvram_conversion_failure_cleans_temp(self) -> None:
        def broken(source: pathlib.Path, destination: pathlib.Path) -> None:
            raise ctflab_utm.UTMExportError("模拟 NVRAM 转换失败")

        with self.assertRaises(ctflab_utm.UTMExportError):
            self.export(nvram_convert=broken)
        self.assertEqual(self.temp_leftovers(), [])
        self.assertFalse(self.bundle.exists())
        self.assertFalse(self.manifest_path.exists())

    def test_nvram_format_error_is_refused(self) -> None:
        def wrong_format(path: pathlib.Path) -> dict:
            if path.name == ctflab_utm.NVRAM_OUTPUT_NAME:
                return {"format": "raw"}
            return {"format": "qcow2", "virtual-size": 33554432}

        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            self.export(info=wrong_format)
        self.assertIn("NVRAM 转换结果不是 qcow2", str(raised.exception))
        self.assertEqual(self.temp_leftovers(), [])
        self.assertFalse(self.bundle.exists())

    def test_nvram_check_failure_cleans_temp(self) -> None:
        def failing_check(path: pathlib.Path) -> None:
            if path.name == ctflab_utm.NVRAM_OUTPUT_NAME:
                raise ctflab_utm.UTMExportError("模拟 NVRAM check 失败")

        with self.assertRaises(ctflab_utm.UTMExportError):
            self.export(check=failing_check)
        self.assertEqual(self.temp_leftovers(), [])
        self.assertFalse(self.bundle.exists())
        self.assertFalse(self.manifest_path.exists())

    def test_nvram_success_output_and_input_unchanged(self) -> None:
        nvram_before = self.nvram_path.read_bytes()
        manifest = self.export()
        self.assertEqual(self.nvram_path.read_bytes(), nvram_before, "RAW NVRAM 必须保持只读")
        output = self.bundle / "Data" / "efi_vars.fd"
        self.assertTrue(output.is_file())
        block = manifest["uefi_vars"]
        for key in ("input_file", "input_sha256", "input_sha256_before", "input_sha256_after",
                    "output_file", "output_sha256", "format", "check", "size_bytes", "virtual_size"):
            self.assertIn(key, block)
        self.assertEqual(block["input_file"], self.nvram_path.name)
        self.assertEqual(block["output_file"], "efi_vars.fd")
        self.assertEqual(block["format"], "qcow2")
        self.assertEqual(block["check"], "ok")
        self.assertEqual(block["input_sha256"], ctflab.sha256_file(self.nvram_path))
        self.assertEqual(block["input_sha256_before"], block["input_sha256_after"])
        self.assertEqual(block["output_sha256"], ctflab.sha256_file(output))


class ExclusivePublishTests(unittest.TestCase):
    def test_exclusive_rename_moves_when_target_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "src"
            source.write_text("payload", encoding="utf-8")
            target = root / "dst"
            ctflab_utm.exclusive_rename(source, target)
            self.assertFalse(source.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "payload")

    def test_exclusive_rename_refuses_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "src"
            source.write_text("ours", encoding="utf-8")
            target = root / "dst"
            target.write_text("existing", encoding="utf-8")
            with self.assertRaises(ctflab_utm.PublishError) as raised:
                ctflab_utm.exclusive_rename(source, target)
            self.assertIn("拒绝覆盖", str(raised.exception))
            self.assertEqual(target.read_text(encoding="utf-8"), "existing", "既有文件不得被改写")
            self.assertTrue(source.exists(), "发布失败时源文件保留给调用方清理")

    def test_exclusive_rename_refuses_existing_directory(self) -> None:
        """普通 Path.rename() 会替换空目录；排他发布必须拒绝。"""
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "src.utm"
            source.mkdir()
            (source / "config.plist").write_text("x", encoding="utf-8")
            target = root / "dst.utm"
            target.mkdir()
            with self.assertRaises(ctflab_utm.PublishError):
                ctflab_utm.exclusive_rename(source, target)
            self.assertEqual(list(target.iterdir()), [], "既有目录不得被替换")
            self.assertTrue((source / "config.plist").exists())

    def test_publish_race_with_external_creation_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            manager = ctflab.LabManager(root / "state")
            base = root / "base.qcow2"
            base.write_bytes(b"base" * 64)
            nvram = root / "uefi-vars.fd"
            nvram.write_bytes(b"nvram" * 64)
            state = {
                "schema": 1,
                "profile_id": PROFILE_ID,
                "source_path": str(root / "missing.qcow2"),
                "source_sha256": "a" * 64,
                "base_path": str(base),
                "base_sha256": ctflab.sha256_file(base),
                "uefi_vars_path": str(nvram),
                "uefi_vars_sha256": ctflab.sha256_file(nvram),
            }
            out_dir = root / "out"

            def racing_check(path: pathlib.Path) -> None:
                # 模拟外部进程在构建期间创建最终包目录。
                external = out_dir / BUNDLE_NAME
                if not external.exists():
                    external.mkdir(parents=True)
                    (external / "external-marker.txt").write_text("external", encoding="utf-8")

            with mock.patch.object(ctflab_utm, "known_utm_bundle_names", return_value=set()), \
                    mock.patch.object(ctflab_utm, "detect_utm_version", return_value=None):
                with self.assertRaises(ctflab_utm.UTMExportError) as raised:
                    ctflab_utm.export_utm_package(
                        profile_id=PROFILE_ID,
                        profile=copy.deepcopy(ctflab.load_profile(PROFILE_ID)),
                        image_state=state,
                        out_dir=out_dir,
                        convert=fake_convert,
                        nvram_convert=fake_nvram_convert,
                        info=fake_info,
                        check=racing_check,
                    )
            self.assertIn("构建期间出现", str(raised.exception))
            external = out_dir / BUNDLE_NAME
            self.assertEqual((external / "external-marker.txt").read_text(encoding="utf-8"), "external",
                             "外部并发创建的目录不得被删除或改写")
            leftovers = [entry.name for entry in out_dir.iterdir()
                         if entry.name.startswith(f".{PROFILE_ID}-")]
            self.assertEqual(leftovers, [], "本次临时文件必须清理")


class ImportRegistrationTests(unittest.TestCase):
    def test_import_registers_base_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            manager = ctflab.LabManager(root / "state")
            source = root / "input.qcow2"
            source.write_bytes(b"source-bytes")

            def fake_run(command, *, capture=True):
                pathlib.Path(command[-1]).write_bytes(b"converted-base")
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch.object(ctflab, "qemu_img_path", return_value="/usr/bin/qemu-img"), \
                    mock.patch.object(ctflab, "qemu_info",
                                      return_value={"format": "qcow2", "virtual-size": 1024}), \
                    mock.patch.object(ctflab, "run_command", side_effect=fake_run):
                state = manager.import_image("smoke", str(source))
            base = pathlib.Path(state["base_path"])
            self.assertEqual(state["base_sha256"], ctflab.sha256_file(base))
            self.assertEqual(state["base_sha256"],
                             hashlib.sha256(b"converted-base").hexdigest())


class AtomicOutputTests(ExportTestCase):
    def test_final_bundle_absent_during_build_and_temp_cleaned(self) -> None:
        observed: dict = {}

        def observing_convert(source: pathlib.Path, destination: pathlib.Path) -> None:
            observed["final_bundle_exists"] = self.bundle.exists()
            observed["temp_entries"] = sorted(
                entry.name for entry in self.out_dir.iterdir() if entry.name.endswith(".utm")
            )
            fake_convert(source, destination)

        self.export(convert=observing_convert)
        self.assertIs(observed["final_bundle_exists"], False,
                      "构建期间最终 .utm 路径不得出现")
        self.assertTrue(any(name.startswith(f".{PROFILE_ID}-") for name in observed["temp_entries"]),
                        observed)
        self.assertTrue(self.bundle.is_dir())
        self.assertEqual(self.temp_leftovers(), [])

    def test_conversion_failure_cleans_temp_and_keeps_existing(self) -> None:
        self.out_dir.mkdir(parents=True)
        keep = self.out_dir / "keep.txt"
        keep.write_text("keep", encoding="utf-8")

        def broken(source: pathlib.Path, destination: pathlib.Path) -> None:
            raise ctflab_utm.UTMExportError("模拟转换失败")

        with self.assertRaises(ctflab_utm.UTMExportError):
            self.export(convert=broken)
        self.assertEqual([entry.name for entry in self.out_dir.iterdir()], ["keep.txt"])
        self.assertFalse(self.bundle.exists())
        self.assertFalse(self.manifest_path.exists())

    def test_info_format_validation_failure_cleans_temp(self) -> None:
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            self.export(info=lambda path: {"format": "raw"})
        self.assertIn("不是 qcow2", str(raised.exception))
        self.assertEqual(self.temp_leftovers(), [])
        self.assertFalse(self.bundle.exists())

    def test_qemu_img_check_failure_cleans_temp(self) -> None:
        def failing_check(path: pathlib.Path) -> None:
            raise ctflab_utm.UTMExportError("模拟 check 失败")

        with self.assertRaises(ctflab_utm.UTMExportError):
            self.export(check=failing_check)
        self.assertEqual(self.temp_leftovers(), [])
        self.assertFalse(self.bundle.exists())
        self.assertFalse(self.manifest_path.exists())

    def test_manifest_publish_failure_rolls_back_published_bundle(self) -> None:
        self.out_dir.mkdir(parents=True)
        keep = self.out_dir / "keep.txt"
        keep.write_text("keep", encoding="utf-8")
        real_exclusive_rename = ctflab_utm.exclusive_rename

        def flaky_exclusive_rename(source: pathlib.Path, target: pathlib.Path) -> None:
            if str(target).endswith(MANIFEST_NAME):
                raise ctflab_utm.PublishError("模拟清单发布失败")
            real_exclusive_rename(source, target)

        with mock.patch.object(ctflab_utm, "exclusive_rename", flaky_exclusive_rename):
            with self.assertRaises(ctflab_utm.PublishError):
                self.export()
        self.assertEqual([entry.name for entry in self.out_dir.iterdir()], ["keep.txt"])
        self.assertFalse(self.bundle.exists())
        self.assertFalse(self.manifest_path.exists())

    def test_existing_hidden_export_file_is_not_overwritten(self) -> None:
        self.out_dir.mkdir(parents=True)
        sentinel = self.out_dir / f".{PROFILE_ID}-user.export.json"
        sentinel.write_text("keep", encoding="utf-8")
        self.export()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertTrue(self.manifest_path.is_file())
        self.assertEqual(self.temp_leftovers(), [sentinel.name])

    def test_existing_bundle_directory_is_refused_and_untouched(self) -> None:
        self.bundle.mkdir(parents=True)
        (self.bundle / "keep.txt").write_text("keep", encoding="utf-8")
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            self.export()
        self.assertIn("拒绝覆盖", str(raised.exception))
        self.assertEqual((self.bundle / "keep.txt").read_text(encoding="utf-8"), "keep")
        self.assertFalse(self.manifest_path.exists())

    def test_existing_manifest_file_is_refused_and_untouched(self) -> None:
        self.manifest_path.parent.mkdir(parents=True)
        self.manifest_path.write_text("keep", encoding="utf-8")
        with self.assertRaises(ctflab_utm.UTMExportError):
            self.export()
        self.assertEqual(self.manifest_path.read_text(encoding="utf-8"), "keep")
        self.assertFalse(self.bundle.exists())


class ConversionVerificationTests(ExportTestCase):
    def test_info_and_check_are_invoked_on_converted_disk(self) -> None:
        calls: dict = {"info": [], "check": []}

        def recording_info(path: pathlib.Path) -> dict:
            calls["info"].append(path.name)
            return fake_info(path)

        def recording_check(path: pathlib.Path) -> None:
            calls["check"].append(path.name)

        manifest = self.export(info=recording_info, check=recording_check)
        self.assertEqual(calls["info"], ["data.qcow2", "efi_vars.fd"])
        self.assertEqual(calls["check"], ["data.qcow2", "efi_vars.fd"])
        self.assertEqual(manifest["utm_disk"]["format"], "qcow2")
        self.assertEqual(manifest["utm_disk"]["check"], "ok")
        self.assertEqual(manifest["uefi_vars"]["format"], "qcow2")
        self.assertEqual(manifest["uefi_vars"]["check"], "ok")


class PrivacyTests(ExportTestCase):
    def test_manifest_contains_no_absolute_paths(self) -> None:
        manifest = self.export()
        text = self.manifest_path.read_text(encoding="utf-8")
        for absolute in ("/Users/", "/var/folders/", "/private/", "/tmp/", str(self.root), str(self.out_dir)):
            self.assertNotIn(absolute, text, f"清单不得包含绝对路径：{absolute}")
        self.assertNotIn(str(self.base_path), text)
        self.assertFalse(manifest["bundle"]["name"].startswith("/"))
        self.assertFalse(manifest["manifest"]["name"].startswith("/"))
        self.assertEqual(manifest["base_image"]["file"], self.base_path.name)
        self.assertEqual(manifest["utm_disk"]["file"], "data.qcow2")
        self.assertEqual(manifest["uefi_vars"]["input_file"], self.nvram_path.name)
        self.assertEqual(manifest["uefi_vars"]["output_file"], "efi_vars.fd")
        self.assertNotIn("path", {key for key in manifest["bundle"]})
        self.assertNotIn("source_path", manifest["source_image"])
        self.assertNotIn("input_path", manifest["uefi_vars"])
        parsed = json.loads(text)
        self.assertEqual(parsed, manifest)

    def test_manifest_records_e2e_pending_and_structure_status(self) -> None:
        manifest = self.export()
        self.assertNotIn("e2e_verified", manifest, "含糊的 E2E 布尔字段应被 runtime_status 取代")
        self.assertEqual(manifest["runtime_status"]["e2e_scope"], ctflab_utm.E2E_SCOPE_NOT_RUN)
        self.assertEqual(manifest["runtime_status"]["e2e_status"], ctflab_utm.E2E_STATUS_NOT_RUN)
        self.assertEqual(manifest["runtime_status"]["verification_records"], [])
        self.assertEqual(manifest["guest_agent_prerequisite"]["status"], "not-verified-offline")
        self.assertTrue(manifest["utm_e2e_required"])
        self.assertEqual(manifest["fixture"]["structure_status"], ctflab_utm.STRUCTURE_STATUS)
        self.assertEqual(manifest["fixture"]["sha256"], ctflab_utm.FIXTURE_SHA256)
        self.assertEqual(manifest["fixture"]["utm_version_reference"], "4.7.5")
        self.assertEqual(manifest["network"], {"mode": "none", "nics": 0})
        self.assertEqual(manifest["shared_directories"], [])
        self.assertEqual(manifest["additional_qemu_arguments"], [])
        self.assertIs(manifest["clipboard_sharing"], False)
        self.assertIn("不得据此宣称可导入、可启动或动态分辨率就绪", manifest["note"])

    def test_structure_status_is_separate_from_runtime_status(self) -> None:
        """结构状态只描述必需段/键；运行验收状态独立记录，不得用结构状态暗示 E2E 结论。"""
        manifest = self.export()
        self.assertEqual(manifest["fixture"]["structure_status"], "complete-required-keys")
        self.assertNotIn("pending", manifest["fixture"]["structure_status"])
        self.assertIn("独立", manifest["fixture"]["structure_status_detail"])
        self.assertEqual(manifest["schema"], 3)

    def test_disk_hashes_at_export_and_after_e2e_are_distinct_fields(self) -> None:
        """导出时哈希与 E2E 后哈希必须是两个字段，导出时不得出现含糊的单一 sha256。"""
        manifest = self.export()
        disk = manifest["utm_disk"]
        self.assertNotIn("sha256", disk, "不得保留含糊的 utm_disk.sha256 字段")
        self.assertRegex(disk["sha256_at_export"], r"^[0-9a-f]{64}$")
        self.assertIsNone(disk["sha256_after_e2e"], "导出时 E2E 后哈希必须为空")
        self.assertIs(disk["writable"], True)
        self.assertIn("启动/关机", disk["writable_note"])

    def test_no_ctflab_mapping_status_in_manifest_json(self) -> None:
        self.export()
        text = self.manifest_path.read_text(encoding="utf-8")
        self.assertNotIn("CTFLabMappingStatus", text)


class NamingTests(ExportTestCase):
    def test_duplicate_utm_library_name_is_case_insensitive(self) -> None:
        with mock.patch.object(ctflab_utm, "known_utm_bundle_names", return_value={"KALI-ARM64"}):
            with self.assertRaises(ctflab_utm.UTMExportError) as raised:
                self.export()
        self.assertIn("同名虚拟机", str(raised.exception))
        self.assertFalse(self.out_dir.exists(), "拒绝时必须不创建输出目录")

    def test_known_utm_bundle_names_is_read_only_enumeration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root / "Foo.utm").mkdir()
            (root / "not-a-bundle").mkdir()
            (root / "loose.txt").write_text("x", encoding="utf-8")
            with mock.patch.object(ctflab_utm, "UTM_LIBRARY_HINTS", (root,)):
                names = self.real_known_utm_bundle_names()
            self.assertEqual(names, {"Foo"})
            self.assertEqual(sorted(entry.name for entry in root.iterdir()),
                             ["Foo.utm", "loose.txt", "not-a-bundle"])

    def test_unsafe_names_are_rejected(self) -> None:
        for bad in ("../evil", "a/b", ".hidden", "x.utm", "", "a" * 80, "with space"):
            with self.subTest(name=bad):
                with self.assertRaises(ctflab_utm.UTMExportError):
                    self.export(name=bad)

    def test_safe_custom_name_is_used(self) -> None:
        manifest = self.export(name="Lab-Kali_1")
        self.assertEqual(manifest["display_name"], "Lab-Kali_1")
        self.assertTrue((self.out_dir / "Lab-Kali_1.utm").is_dir())


class ProfileGuardTests(ExportTestCase):
    def test_non_aarch64_profile_is_rejected(self) -> None:
        profile = copy.deepcopy(self.profile)
        profile["guest"]["architecture"] = "x86_64"
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            self.export(profile=profile)
        self.assertIn("只支持 aarch64", str(raised.exception))

    def test_non_virtio_disk_is_rejected(self) -> None:
        profile = copy.deepcopy(self.profile)
        profile["disk"]["bus"] = "ide"
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            self.export(profile=profile)
        self.assertIn("只支持 virtio 磁盘", str(raised.exception))

    def test_non_virtio_gpu_display_is_rejected(self) -> None:
        profile = copy.deepcopy(self.profile)
        profile["display"] = {"adapter": "VGA"}
        with self.assertRaises(ctflab_utm.UTMExportError):
            self.export(profile=profile)


class FixtureGuardTests(unittest.TestCase):
    def fixture_data(self) -> dict:
        return json.loads(ctflab_utm.fixture_bytes().decode("utf-8"))

    def test_builtin_fixture_matches_registered_hash_and_structure(self) -> None:
        fixture = ctflab_utm.load_fixture()
        self.assertEqual(fixture["fixture_version"], ctflab_utm.FIXTURE_VERSION)
        self.assertEqual(fixture["utm_version_reference"], "4.7.5")
        self.assertEqual(fixture["structure_status"], ctflab_utm.STRUCTURE_STATUS)
        self.assertEqual(fixture["disk_relative_path"], "Data/data.qcow2")
        self.assertEqual(ctflab_utm.fixture_sha256(), ctflab_utm.FIXTURE_SHA256)
        structure = fixture["config_structure"]
        self.assertEqual(set(structure), set(ctflab_utm.ALLOWED_CONFIG_KEYS))
        self.assertIsInstance(structure["Display"], list)
        self.assertEqual(structure["Network"], [])
        self.assertEqual(structure["Serial"], [])
        self.assertEqual(structure["Sound"], [])
        self.assertEqual(structure["System"]["CPU"], "default")
        self.assertIs(structure["QEMU"]["Hypervisor"], True)
        self.assertEqual(set(structure["Input"]), set(ctflab_utm.SECTION_KEYS["Input"]))
        self.assertEqual(structure["Sharing"]["DirectoryShareMode"], "None")

    def test_tampered_fixture_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tampered = pathlib.Path(directory) / "fixture.json"
            data = self.fixture_data()
            data["config_structure"]["Sharing"]["ClipboardSharing"] = True
            tampered.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ctflab_utm.UTMExportError) as raised:
                ctflab_utm.load_fixture(tampered)
        self.assertIn("哈希与登记值不一致", str(raised.exception))

    def test_fixture_whitelist_rejects_unknown_keys(self) -> None:
        data = self.fixture_data()
        data["template_hint"] = "/Users/someone/example.utm"
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            ctflab_utm.validate_fixture(data)
        self.assertIn("白名单之外的键", str(raised.exception))

    def test_fixture_rejects_forbidden_structures(self) -> None:
        cases = {
            "network": lambda d: d["config_structure"].update({"Network": [{"Mode": "Shared"}]}),
            "sharing": lambda d: d["config_structure"]["Sharing"].update({"DirectoryShareMode": "VirtFS"}),
            "additional_args": lambda d: d["config_structure"]["QEMU"].update({"AdditionalArguments": ["-netdev"]}),
            "clipboard": lambda d: d["config_structure"]["Sharing"].update({"ClipboardSharing": True}),
            "memory_key": lambda d: d["config_structure"]["System"].update({"Memory": 4096}),
            "cpu_removed": lambda d: d["config_structure"]["System"].pop("CPU"),
            "cpu_changed": lambda d: d["config_structure"]["System"].update({"CPU": "host"}),
            "hypervisor_false": lambda d: d["config_structure"]["QEMU"].update({"Hypervisor": False}),
            "display_not_array": lambda d: d["config_structure"].update({"Display": {"Hardware": "virtio-gpu-pci"}}),
            "uefi_false": lambda d: d["config_structure"]["QEMU"].update({"UEFIBoot": False}),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                data = self.fixture_data()
                mutate(data)
                with self.assertRaises(ctflab_utm.UTMExportError):
                    ctflab_utm.validate_fixture(data)

    def test_fixture_rejects_placeholders_outside_approved_slots(self) -> None:
        data = self.fixture_data()
        data["config_structure"]["Information"]["Icon"] = "<icon>"
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            ctflab_utm.validate_fixture(data)
        self.assertIn("图标", str(raised.exception))

    def test_fixture_rejects_missing_required_sections(self) -> None:
        """UTM 4.7.5 顶层强制 decode 的任一段缺失都必须被校验器拒绝。"""
        required = sorted(ctflab_utm.ALLOWED_CONFIG_KEYS - {"Backend", "ConfigurationVersion"})
        self.assertEqual(required, sorted([
            "Information", "System", "QEMU", "Input", "Sharing", "Display", "Drive",
            "Network", "Serial", "Sound",
        ]))
        for section in required:
            with self.subTest(section=section):
                data = self.fixture_data()
                data["config_structure"].pop(section)
                with self.assertRaises(ctflab_utm.UTMExportError):
                    ctflab_utm.validate_fixture(data)

    def test_fixture_rejects_missing_required_fields(self) -> None:
        """各段源码必需字段（含 QEMU/System/Input/Sharing）逐个删除都必须被拒绝。"""
        required_fields = [
            ("Information", "Name"), ("Information", "UUID"), ("Information", "Icon"),
            ("Information", "IconCustom"),
            ("System", "Architecture"), ("System", "Target"), ("System", "CPU"),
            ("System", "CPUFlagsAdd"), ("System", "CPUFlagsRemove"), ("System", "CPUCount"),
            ("System", "ForceMulticore"), ("System", "MemorySize"), ("System", "JITCacheSize"),
            ("QEMU", "DebugLog"), ("QEMU", "UEFIBoot"), ("QEMU", "RNGDevice"),
            ("QEMU", "BalloonDevice"), ("QEMU", "TPMDevice"), ("QEMU", "Hypervisor"),
            ("QEMU", "RTCLocalTime"), ("QEMU", "PS2Controller"), ("QEMU", "AdditionalArguments"),
            ("Input", "UsbBusSupport"), ("Input", "UsbSharing"), ("Input", "MaximumUsbShare"),
            ("Sharing", "DirectoryShareMode"), ("Sharing", "DirectoryShareReadOnly"),
            ("Sharing", "ClipboardSharing"),
        ]
        for section, key in required_fields:
            with self.subTest(section=section, key=key):
                data = self.fixture_data()
                data["config_structure"][section].pop(key)
                with self.assertRaises(ctflab_utm.UTMExportError):
                    ctflab_utm.validate_fixture(data)

    def test_fixture_rejects_wrong_key_case(self) -> None:
        """源码 CodingKeys 大小写敏感：改错大小写等同于缺键，必须被拒绝。"""
        cases = [
            ("Input", "UsbBusSupport", "USBBusSupport"),
            ("Input", "UsbSharing", "USBSharing"),
            ("Input", "MaximumUsbShare", "MaximumUSBShare"),
            ("Sharing", "DirectoryShareMode", "DirectorySharemode"),
            ("Sharing", "DirectoryShareReadOnly", "DirectoryShareReadonly"),
            ("System", "CPUFlagsAdd", "CpuFlagsAdd"),
            ("System", "MemorySize", "Memorysize"),
            ("QEMU", "UEFIBoot", "UefiBoot"),
            ("QEMU", "PS2Controller", "Ps2Controller"),
        ]
        for section, key, wrong in cases:
            with self.subTest(section=section, key=key):
                data = self.fixture_data()
                section_data = data["config_structure"][section]
                section_data[wrong] = section_data.pop(key)
                with self.assertRaises(ctflab_utm.UTMExportError):
                    ctflab_utm.validate_fixture(data)


class X86_64BiosVariantTests(ExportTestCase):
    """x86_64 + BIOS（Smoke/Basic 靶机）变体：结构取值来自本机 UTM 4.7.5 参考包。"""

    def x86_profile(self, bus: str = "scsi", cpus: int = 2) -> dict:
        profile = copy.deepcopy(self.profile)
        profile["guest"] = {"architecture": "x86_64", "firmware": "bios", "machine": "pc",
                            "memory_mb": 1024, "cpus": cpus}
        profile["disk"] = {"format": "qcow2", "bus": bus}
        return profile

    def export_x86(self, **kwargs):
        kwargs.setdefault("profile", self.x86_profile())
        # BIOS 记录没有 NVRAM：显式移除
        state = kwargs.pop("image_state", None) or dict(self.manager.image_state(PROFILE_ID))
        state.pop("uefi_vars_path", None)
        state.pop("uefi_vars_sha256", None)
        kwargs["image_state"] = state
        return self.export(**kwargs)

    def test_x86_bios_structure_matches_reference(self) -> None:
        self.export_x86()
        plist = plistlib.loads((self.bundle / "config.plist").read_bytes())
        self.assertEqual(set(plist), set(ctflab_utm.ALLOWED_CONFIG_KEYS))
        system = plist["System"]
        self.assertEqual(system["Architecture"], "x86_64")
        self.assertEqual(system["Target"], "pc")
        self.assertEqual(system["CPU"], "qemu64")
        self.assertEqual(system["CPUCount"], 2)
        self.assertEqual(system["MemorySize"], 1024)
        self.assertIs(system["ForceMulticore"], True)  # 多核参考包为 true
        self.assertEqual(system["CPUFlagsAdd"], [])
        self.assertEqual(system["JITCacheSize"], 0)
        qemu = plist["QEMU"]
        self.assertIs(qemu["UEFIBoot"], False)
        self.assertIs(qemu["Hypervisor"], False)
        self.assertIs(qemu["PS2Controller"], True)
        self.assertEqual(qemu["AdditionalArguments"], [])
        screen = plist["Display"][0]
        self.assertEqual(screen["Hardware"], "VGA")
        self.assertIs(screen["DynamicResolution"], False)
        self.assertEqual(plist["Network"], [])
        self.assertEqual(plist["Sharing"],
                         {"DirectoryShareMode": "None", "DirectoryShareReadOnly": False, "ClipboardSharing": False})
        self.assertFalse((self.bundle / "Data" / "efi_vars.fd").exists(), "BIOS 包不得包含 NVRAM")

    def test_bus_mapping_ide_and_scsi(self) -> None:
        for bus, expected in (("scsi", "SCSI"), ("ide", "IDE")):
            with self.subTest(bus=bus):
                out = self.root / f"out-{bus}"
                manifest = self.export_x86(out_dir=out, profile=self.x86_profile(bus=bus))
                bundle = out / f"{ctflab_utm.sanitize_name(manifest['display_name'])}{ctflab_utm.BUNDLE_SUFFIX}"
                plist = plistlib.loads((bundle / "config.plist").read_bytes())
                self.assertEqual(plist["Drive"][0]["Interface"], expected)
                self.assertEqual(plist["Drive"][0]["ImageName"], "data.qcow2")

    def test_single_cpu_force_multicore_false(self) -> None:
        self.export_x86(profile=self.x86_profile(cpus=1))
        plist = plistlib.loads((self.bundle / "config.plist").read_bytes())
        self.assertIs(plist["System"]["ForceMulticore"], False)

    def test_manifest_records_variant_and_fixed_display(self) -> None:
        manifest = self.export_x86()
        self.assertEqual(manifest["variant"], "x86_64-bios")
        self.assertEqual(manifest["display"]["mode"], "fixed")
        self.assertIs(manifest["display"]["dynamic_resolution"], False)
        self.assertEqual(manifest["uefi_vars"]["status"], "not-applicable")
        self.assertEqual(manifest["network"], {"mode": "none", "nics": 0})

    def test_unsupported_x86_bus_is_refused(self) -> None:
        profile = self.x86_profile(bus="sata")
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            self.export_x86(profile=profile)
        self.assertIn("只支持 IDE/SCSI", str(raised.exception))

    def test_aarch64_manifest_carries_unstable_display_note(self) -> None:
        manifest = self.export()
        self.assertEqual(manifest["variant"], "aarch64-uefi")
        self.assertEqual(manifest["display"]["mode"], "dynamic-attempted")
        self.assertIn("重启后复测失败，显示链路不稳定；当前包仅保证固定显示可用。",
                      manifest["display"]["note"])


class X86_64FixtureGuardTests(unittest.TestCase):
    def fixture_data(self) -> dict:
        return json.loads(ctflab_utm.fixture_bytes().decode("utf-8"))

    def test_fixture_contains_both_variants(self) -> None:
        data = self.fixture_data()
        ctflab_utm.validate_fixture(data)
        self.assertEqual(data["x86_64_bios_drive_interfaces"], {"ide": "IDE", "scsi": "SCSI"})
        ctflab_utm.validate_structure(data["x86_64_bios_structure"],
                                      variant=ctflab_utm.VARIANT_X86_64_BIOS, label="x86_64_bios_structure")

    def test_x86_structure_rejects_wrong_values(self) -> None:
        cases = {
            "uefi_boot_true": lambda s: s["QEMU"].update({"UEFIBoot": True}),
            "hypervisor_true": lambda s: s["QEMU"].update({"Hypervisor": True}),
            "dynamic_resolution_true": lambda s: s["Display"][0].update({"DynamicResolution": True}),
            "ps2_false": lambda s: s["QEMU"].update({"PS2Controller": False}),
            "cpu_host": lambda s: s["System"].update({"CPU": "host"}),
            "target_q35": lambda s: s["System"].update({"Target": "q35"}),
            "force_multicore_literal": lambda s: s["System"].update({"ForceMulticore": False}),
            "missing_drive_interface_placeholder": lambda s: s["Drive"][0].update({"Interface": "VirtIO"}),
            "network_nonempty": lambda s: s.update({"Network": [{"Mode": "Shared"}]}),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name):
                data = self.fixture_data()
                mutate(data["x86_64_bios_structure"])
                with self.assertRaises(ctflab_utm.UTMExportError):
                    ctflab_utm.validate_fixture(data)

    def test_fixture_rejects_missing_variant_or_bad_mapping(self) -> None:
        data = self.fixture_data()
        data.pop("x86_64_bios_structure")
        with self.assertRaises(ctflab_utm.UTMExportError):
            ctflab_utm.validate_fixture(data)
        data = self.fixture_data()
        data["x86_64_bios_drive_interfaces"] = {"ide": "IDE"}
        with self.assertRaises(ctflab_utm.UTMExportError):
            ctflab_utm.validate_fixture(data)


class RecordE2EResultTests(unittest.TestCase):
    """运行结论补记：离线字段不动，两个磁盘哈希字段不得互相顶替。"""

    AT_EXPORT = "a" * 64
    AFTER_E2E = "b" * 64

    def legacy_manifest(self) -> dict:
        return {
            "schema": 2,
            "generated_at": "2026-09-14T00:00:00Z",
            "fixture": {
                "version": 5,
                "sha256": "c" * 64,
                "utm_version_reference": "4.7.5",
                "structure_status": ctflab_utm.LEGACY_STRUCTURE_STATUS,
            },
            "utm_disk": {"file": "data.qcow2", "sha256": self.AT_EXPORT, "format": "qcow2", "check": "ok"},
            "network": {"mode": "none", "nics": 0},
            "clipboard_sharing": False,
            "note": "离线导出",
        }

    def record(self, manifest: dict, **overrides) -> dict:
        payload = {
            "e2e_scope": ctflab_utm.E2E_SCOPE_CONSOLE_ISOLATION,
            "e2e_status": ctflab_utm.E2E_STATUS_PASSED_SCOPED,
            "dynamic_resolution": ctflab_utm.DYNAMIC_RESOLUTION_UNTESTED_X86,
            "sha256_after_e2e": self.AFTER_E2E,
            "verification_records": ["docs/verification-utm-smoke-2026-09-14.md"],
        }
        payload.update(overrides)
        return ctflab_utm.record_e2e_result(manifest, **payload)

    def test_migration_renames_disk_hash_without_changing_value(self) -> None:
        updated = self.record(self.legacy_manifest())
        disk = updated["utm_disk"]
        self.assertNotIn("sha256", disk)
        self.assertEqual(disk["sha256_at_export"], self.AT_EXPORT)
        self.assertEqual(disk["sha256_after_e2e"], self.AFTER_E2E)
        self.assertEqual(updated["schema"], 3)
        self.assertEqual(updated["fixture"]["structure_status"], ctflab_utm.STRUCTURE_STATUS)

    def test_offline_export_fields_are_preserved(self) -> None:
        original = self.legacy_manifest()
        updated = self.record(original)
        self.assertEqual(updated["generated_at"], original["generated_at"])
        self.assertEqual(updated["fixture"]["sha256"], original["fixture"]["sha256"])
        self.assertEqual(updated["fixture"]["version"], original["fixture"]["version"])
        self.assertEqual(updated["network"], original["network"])
        self.assertIs(updated["clipboard_sharing"], False)
        self.assertEqual(original["utm_disk"]["sha256"], self.AT_EXPORT, "不得就地修改输入清单")

    def test_disk_writable_note_is_added_without_loss(self) -> None:
        updated = self.record(self.legacy_manifest())
        self.assertIs(updated["utm_disk"]["writable"], True)
        self.assertIn("启动/关机", updated["utm_disk"]["writable_note"])

    def test_record_requires_distinct_valid_hashes(self) -> None:
        for bad in ("", "xyz", "a" * 63, "A" * 64, self.AT_EXPORT.upper()):
            with self.subTest(value=bad):
                with self.assertRaises(ctflab_utm.UTMExportError):
                    self.record(self.legacy_manifest(), sha256_after_e2e=bad)
        with self.assertRaises(ctflab_utm.UTMExportError):
            self.record(self.legacy_manifest(), sha256_after_e2e=None, e2e_scope="")
        blank = self.legacy_manifest()
        blank["utm_disk"].pop("sha256")
        with self.assertRaises(ctflab_utm.UTMExportError):
            self.record(blank)

    def test_record_refuses_ambiguous_disk_hash_fields(self) -> None:
        ambiguous = self.legacy_manifest()
        ambiguous["utm_disk"]["sha256_at_export"] = self.AT_EXPORT
        with self.assertRaises(ctflab_utm.UTMExportError):
            self.record(ambiguous)

    def test_record_note_default_is_the_required_sentence(self) -> None:
        updated = self.record(self.legacy_manifest())
        self.assertEqual(updated["runtime_status"]["note"], ctflab_utm.E2E_SCOPED_NOTE)
        self.assertIn("不构成动态分辨率或联网靶场验收", updated["runtime_status"]["note"])
        self.assertEqual(updated["runtime_status"]["verification_records"],
                         ["docs/verification-utm-smoke-2026-09-14.md"])

    def test_writable_note_names_both_checklists(self) -> None:
        updated = self.record(self.legacy_manifest())
        note = updated["utm_disk"]["writable_note"]
        self.assertIn("SHA256SUMS.at-export", note)
        self.assertIn("不能对 E2E 后可写盘执行校验", note)
        self.assertIn("sha256_after_e2e", note)


class LegacyStructureLabelGuardTests(unittest.TestCase):
    """旧 schema 迁移标签只用于迁移识别，绝不作为当前 fixture 或当前状态输出。"""

    def test_structure_status_is_current_and_not_legacy(self) -> None:
        self.assertEqual(ctflab_utm.STRUCTURE_STATUS, "complete-required-keys")
        self.assertNotIn("pending", ctflab_utm.STRUCTURE_STATUS)
        self.assertNotEqual(ctflab_utm.STRUCTURE_STATUS, ctflab_utm.LEGACY_STRUCTURE_STATUS)
        self.assertIn("旧 schema 迁移标签", ctflab_utm.LEGACY_STRUCTURE_STATUS_LABEL)

    def test_fixture_outputs_current_label_not_legacy(self) -> None:
        fixture = ctflab_utm.load_fixture()
        self.assertEqual(fixture["structure_status"], ctflab_utm.STRUCTURE_STATUS)
        self.assertNotIn(ctflab_utm.LEGACY_STRUCTURE_STATUS,
                         pathlib.Path(ctflab_utm.FIXTURE_PATH).read_text(encoding="utf-8"))

    def test_recorded_manifest_never_outputs_legacy_label(self) -> None:
        legacy = {
            "schema": 2,
            "fixture": {"version": 5, "sha256": "c" * 64,
                        "structure_status": ctflab_utm.LEGACY_STRUCTURE_STATUS},
            "utm_disk": {"file": "data.qcow2", "sha256": "a" * 64},
        }
        recorded = ctflab_utm.record_e2e_result(
            legacy,
            e2e_scope=ctflab_utm.E2E_SCOPE_CONSOLE_ISOLATION,
            e2e_status=ctflab_utm.E2E_STATUS_PASSED_SCOPED,
            dynamic_resolution=ctflab_utm.DYNAMIC_RESOLUTION_UNTESTED_X86,
            sha256_after_e2e="b" * 64,
            verification_records=["docs/verification-utm-smoke-2026-09-14.md"],
        )
        dumped = json.dumps(recorded, ensure_ascii=False)
        self.assertNotIn(ctflab_utm.LEGACY_STRUCTURE_STATUS, dumped)
        self.assertEqual(recorded["fixture"]["structure_status"], ctflab_utm.STRUCTURE_STATUS)

    def test_record_refuses_legacy_label_left_in_notes(self) -> None:
        """迁移注释里若仍带旧标签字面量，补记必须明确拒绝而不是原样带出。"""
        manifest = {
            "schema": 2,
            "fixture": {"version": 5, "sha256": "c" * 64,
                        "structure_status": ctflab_utm.LEGACY_STRUCTURE_STATUS,
                        "fixture_migration_note": (
                            "由 %s 迁移为 complete-required-keys。" % ctflab_utm.LEGACY_STRUCTURE_STATUS)},
            "utm_disk": {"file": "data.qcow2", "sha256": "a" * 64},
        }
        with self.assertRaises(ctflab_utm.UTMExportError) as raised:
            ctflab_utm.record_e2e_result(
                manifest,
                e2e_scope=ctflab_utm.E2E_SCOPE_CONSOLE_ISOLATION,
                e2e_status=ctflab_utm.E2E_STATUS_PASSED_SCOPED,
                dynamic_resolution=ctflab_utm.DYNAMIC_RESOLUTION_UNTESTED_X86,
                sha256_after_e2e="b" * 64,
                verification_records=["docs/verification-utm-smoke-2026-09-14.md"],
            )
        self.assertIn("旧 schema 迁移标签", str(raised.exception))
        self.assertIn("中性表述", str(raised.exception))


@unittest.skipUnless(shutil.which("qemu-img"), "需要 qemu-img")
class RealQemuImgPipelineTests(ExportTestCase):
    def test_real_conversion_passes_info_and_check(self) -> None:
        qemu_img = shutil.which("qemu-img")
        source = self.root / "real-base.qcow2"
        subprocess.run([qemu_img, "create", "-f", "qcow2", str(source), "16M"],
                       check=True, capture_output=True)
        state = self.write_image_state(
            base_path=str(source),
            base_sha256=ctflab.sha256_file(source),
        )
        manifest = self.export(
            image_state=state,
            convert=ctflab_utm.qemu_img_convert,
            nvram_convert=ctflab_utm.qemu_img_convert_nvram,
            info=ctflab_utm.qemu_img_info,
            check=ctflab_utm.qemu_img_check,
        )
        produced = self.bundle / DISK_RELATIVE
        info = json.loads(subprocess.run(
            [qemu_img, "info", "--output=json", str(produced)],
            check=True, capture_output=True, text=True,
        ).stdout)
        self.assertEqual(info["format"], "qcow2")
        self.assertEqual(manifest["utm_disk"]["format"], "qcow2")
        self.assertEqual(manifest["utm_disk"]["check"], "ok")
        self.assertEqual(manifest["utm_disk"]["virtual_size"], info["virtual-size"])
        produced_nvram = self.bundle / "Data" / "efi_vars.fd"
        nvram_info = json.loads(subprocess.run(
            [qemu_img, "info", "--output=json", str(produced_nvram)],
            check=True, capture_output=True, text=True,
        ).stdout)
        self.assertEqual(nvram_info["format"], "qcow2")
        self.assertEqual(manifest["uefi_vars"]["format"], "qcow2")
        self.assertEqual(manifest["uefi_vars"]["check"], "ok")
        self.assertEqual(manifest["uefi_vars"]["output_sha256"],
                         ctflab.sha256_file(produced_nvram))
        plist = plistlib.loads((self.bundle / "config.plist").read_bytes())
        self.assertEqual(plist["Drive"][0]["ImageName"], "data.qcow2")
        self.assertEqual(plist["Network"], [])


class CliSurfaceTests(unittest.TestCase):
    def subcommands(self) -> dict:
        parser = ctflab.build_parser()
        found: dict = {}
        for action in parser._subparsers._group_actions:
            found.update(action.choices)
        return found

    def test_utm_export_has_no_force_or_template_options(self) -> None:
        sub = self.subcommands()["utm-export"]
        options = {option for action in sub._actions for option in action.option_strings}
        self.assertIn("--out", options)
        self.assertIn("--name", options)
        for forbidden in ("--force", "--overwrite", "--template", "--clipboard", "--network"):
            self.assertNotIn(forbidden, options)

    def test_run_exposes_explicit_display_backend(self) -> None:
        sub = self.subcommands()["run"]
        options = {option for action in sub._actions for option in action.option_strings}
        self.assertIn("--display", options)

    def test_cmd_utm_export_reports_bundle_and_pending_e2e(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            manager = ctflab.LabManager(root / "state")
            base = root / "base.qcow2"
            base.write_bytes(b"base" * 64)
            ctflab.write_json(
                manager.image_state_path(PROFILE_ID),
                {
                    "schema": 1,
                    "profile_id": PROFILE_ID,
                    "source_path": str(root / "missing.qcow2"),
                    "source_sha256": "c" * 64,
                    "base_path": str(base),
                    "base_sha256": ctflab.sha256_file(base),
                },
            )
            args = ctflab.build_parser().parse_args(
                ["utm-export", PROFILE_ID, "--out", str(root / "out")]
            )
            nvram = root / "uefi-vars.fd"
            nvram.write_bytes(b"nvram" * 64)
            state_path = manager.image_state_path(PROFILE_ID)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["uefi_vars_path"] = str(nvram)
            state["uefi_vars_sha256"] = ctflab.sha256_file(nvram)
            ctflab.write_json(state_path, state)
            output = io.StringIO()
            with mock.patch.object(ctflab_utm, "known_utm_bundle_names", return_value=set()), \
                    mock.patch.object(ctflab_utm, "detect_utm_version", return_value=None), \
                    mock.patch.object(ctflab_utm, "qemu_img_convert", side_effect=fake_convert), \
                    mock.patch.object(ctflab_utm, "qemu_img_convert_nvram", side_effect=fake_nvram_convert), \
                    mock.patch.object(ctflab_utm, "qemu_img_info", side_effect=fake_info), \
                    mock.patch.object(ctflab_utm, "qemu_img_check", side_effect=fake_check), \
                    redirect_stdout(output):
                code = ctflab.cmd_utm_export(manager, args)
            text = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn(f"{PROFILE_ID}.utm", text)
        self.assertIn("真实 UTM E2E", text)


if __name__ == "__main__":
    unittest.main()
