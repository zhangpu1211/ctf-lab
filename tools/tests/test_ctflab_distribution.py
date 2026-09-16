#!/usr/bin/env python3
"""分发准备与"可校验导入"回归（路线 A：网盘/资料区）。

覆盖：

- `ctflab dist prepare`：压缩/复制基盘、登记哈希与大小、合并清单、生成 SHA256SUMS 与 README；
- `ctflab dist verify`：文件缺失、大小或哈希不一致必须报告；
- `ctflab import --expect-sha256/--manifest/--nvram`：期望哈希必须强制核对；清单冲突
  （显式哈希或 NVRAM 与清单不一致）一律拒绝；校验结果写入 image.json 证据。
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import ctflab  # noqa: E402
import ctflab_dist  # noqa: E402

PROFILE_ID = "smoke"


def fake_run(command, *, capture=True):
    """替身 qemu-img：convert 产出目标文件，其余命令返回 0。"""
    if len(command) > 1 and command[1] == "convert":
        pathlib.Path(command[-1]).write_bytes(b"converted-base")
    return subprocess.CompletedProcess(command, 0, "", "")


class DistPrepareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.out = self.root / "dist"
        self.source = self.root / "base-input.qcow2"
        self.source.write_bytes(b"base-image-bytes" * 64)
        self.source_hash = ctflab_dist.sha256_file(self.source)

    def _prepare(self, *, profile=PROFILE_ID, compress=False, base_sha256=None, **kwargs):
        return ctflab_dist.prepare_image_entry(
            self.out, profile_id=profile, source=self.source, qemu_img="qemu-img",
            compress=compress, base_sha256=base_sha256, **kwargs)

    def test_prepare_copies_records_and_writes_sums(self) -> None:
        entry = self._prepare(base_sha256="a" * 64)
        self.assertEqual(entry["role"], "base")
        self.assertEqual(entry["profile"], PROFILE_ID)
        self.assertEqual(entry["file"], f"{PROFILE_ID}-base.qcow2")
        self.assertEqual(entry["sha256"], self.source_hash)
        self.assertEqual(entry["compression"], ctflab_dist.COMPRESSION_NONE)
        self.assertEqual(entry["source_base_sha256"], "a" * 64)
        self.assertTrue((self.out / entry["file"]).is_file())
        sums = (self.out / ctflab_dist.SUMS_NAME).read_text(encoding="utf-8")
        self.assertIn(f"{self.source_hash}  {entry['file']}", sums)
        readme = (self.out / ctflab_dist.README_NAME).read_text(encoding="utf-8")
        self.assertIn("--manifest DISTRIBUTION.json", readme)
        self.assertIn(entry["file"], readme)
        manifest = ctflab_dist.load_manifest(self.out)
        self.assertEqual(len(manifest["entries"]), 1)

    def test_prepare_compresses_with_zstd_and_checks(self) -> None:
        commands: list[list[str]] = []

        def recording_run(command, *, capture=True, timeout=None, check=True):
            commands.append(list(command))
            if "info" in command:
                return subprocess.CompletedProcess(command, 0, json.dumps({"virtual-size": 4096}), "")
            return fake_run(command)

        with mock.patch.object(ctflab_dist, "_run_tool", side_effect=recording_run):
            entry = self._prepare(compress=True)
        self.assertEqual(entry["compression"], ctflab_dist.COMPRESSION_ZSTD)
        self.assertEqual(entry["content_verified"], "qemu-img-compare-equal")
        convert = [cmd for cmd in commands if "convert" in cmd][0]
        self.assertIn("-c", convert)
        self.assertIn("compression_type=zstd", convert)
        self.assertTrue(any("check" in cmd for cmd in commands), "压缩后必须 qemu-img check")
        compare = [cmd for cmd in commands if "compare" in cmd]
        self.assertTrue(compare, "压缩后必须 qemu-img compare 证明内容一致")
        self.assertNotIn("-s", compare[0], "压缩会重排分配布局，严格模式必然误报")
        self.assertTrue(any("info" in cmd for cmd in commands), "必须显式核对容量")

    def test_compress_content_mismatch_is_refused(self) -> None:
        def mismatching_run(command, *, capture=True, timeout=None, check=True):
            if "compare" in command:
                return subprocess.CompletedProcess(command, 1, "Images differ", "")
            if "info" in command:
                return subprocess.CompletedProcess(command, 0, json.dumps({"virtual-size": 4096}), "")
            return fake_run(command)

        with mock.patch.object(ctflab_dist, "_run_tool", side_effect=mismatching_run):
            with self.assertRaises(ctflab_dist.DistError) as raised:
                self._prepare(compress=True)
        self.assertIn("不一致", str(raised.exception))
        self.assertFalse((self.out / f"{PROFILE_ID}-base.qcow2").exists(),
                         "内容不一致时不得发布压缩产物")

    def test_compress_size_mismatch_is_refused(self) -> None:
        def size_mismatching_run(command, *, capture=True, timeout=None, check=True):
            if "info" in command:
                size = 4096 if str(self.source) in command else 2048
                return subprocess.CompletedProcess(command, 0, json.dumps({"virtual-size": size}), "")
            return fake_run(command)

        with mock.patch.object(ctflab_dist, "_run_tool", side_effect=size_mismatching_run):
            with self.assertRaises(ctflab_dist.DistError) as raised:
                self._prepare(compress=True)
        self.assertIn("容量", str(raised.exception))

    def test_manifest_merges_multiple_profiles(self) -> None:
        self._prepare(profile="smoke")
        other = self.root / "kali-base.qcow2"
        other.write_bytes(b"kali-bytes" * 32)
        ctflab_dist.prepare_image_entry(self.out, profile_id="kali-arm64", source=other,
                                        qemu_img="qemu-img", compress=False)
        manifest = ctflab_dist.load_manifest(self.out)
        profiles = [entry["profile"] for entry in manifest["entries"]]
        self.assertEqual(profiles, ["kali-arm64", "smoke"])
        sums = (self.out / ctflab_dist.SUMS_NAME).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(sums), 2)

    def test_nvram_entry_is_registered_and_looked_up(self) -> None:
        nvram = self.root / "uefi-vars.fd"
        nvram.write_bytes(b"nvram-template" * 8)
        entry = ctflab_dist.prepare_nvram_entry(self.out, profile_id="kali-arm64", source=nvram)
        self.assertEqual(entry["role"], ctflab_dist.NVRAM_ROLE)
        self.assertEqual(entry["sha256"], ctflab_dist.sha256_file(nvram))
        manifest = ctflab_dist.load_manifest(self.out)
        found = ctflab_dist.expected_for_profile(manifest, "kali-arm64", ctflab_dist.NVRAM_ROLE)
        self.assertIsNotNone(found)
        self.assertEqual(found["file"], entry["file"])

    def test_verify_reports_tampering_and_missing_files(self) -> None:
        entry = self._prepare()
        report = ctflab_dist.verify_distribution(self.out)
        self.assertTrue(report["ok"], report["problems"])
        target = self.out / entry["file"]
        target.write_bytes(b"tampered")
        report = ctflab_dist.verify_distribution(self.out)
        self.assertFalse(report["ok"])
        self.assertTrue(any("SHA-256 不一致" in problem for problem in report["problems"]))
        target.unlink()
        report = ctflab_dist.verify_distribution(self.out)
        self.assertFalse(report["ok"])
        self.assertTrue(any("文件缺失" in problem for problem in report["problems"]))

    def test_load_manifest_rejects_foreign_or_missing_files(self) -> None:
        with self.assertRaises(ctflab_dist.DistError):
            ctflab_dist.load_manifest(self.out)
        bogus = self.out
        bogus.mkdir(parents=True, exist_ok=True)
        (bogus / ctflab_dist.MANIFEST_NAME).write_text('{"format": "other"}', encoding="utf-8")
        with self.assertRaises(ctflab_dist.DistError):
            ctflab_dist.load_manifest(self.out)

    def test_prepare_rejects_path_in_file_name(self) -> None:
        with self.assertRaises(ctflab_dist.DistError):
            self._prepare(file_name="sub/dir.qcow2")


class ImportVerificationTests(unittest.TestCase):
    """`ctflab import` 的期望哈希校验：来源不匹配必须拒绝，校验证据必须落盘。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.manager = ctflab.LabManager(self.root / "state")
        self.source = self.root / "smoke-base.qcow2"
        self.source.write_bytes(b"distributed-base-bytes" * 32)
        self.source_hash = ctflab.sha256_file(self.source)
        self.dist_dir = self.root / "dist"
        ctflab_dist.prepare_image_entry(self.dist_dir, profile_id=PROFILE_ID, source=self.source,
                                        qemu_img="qemu-img", compress=False)
        self.manifest = ctflab_dist.manifest_path(self.dist_dir)

    def _import(self, *, source=None, **kwargs):
        with mock.patch.object(ctflab, "qemu_img_path", return_value="/usr/bin/qemu-img"), \
                mock.patch.object(ctflab, "qemu_info",
                                  return_value={"format": "qcow2", "virtual-size": 1024}), \
                mock.patch.object(ctflab, "run_command", side_effect=fake_run):
            return self.manager.import_image(PROFILE_ID, str(source or self.source), **kwargs)

    def test_expect_sha256_match_records_evidence(self) -> None:
        state = self._import(expect_sha256=self.source_hash)
        verification = state["source_verification"]
        self.assertEqual(verification["method"], "expect-sha256")
        self.assertEqual(verification["expected_sha256"], self.source_hash)
        self.assertEqual(state["source_sha256"], self.source_hash)

    def test_expect_sha256_mismatch_refuses_import(self) -> None:
        with self.assertRaises(ctflab.CTFLabError) as raised:
            self._import(expect_sha256="0" * 64)
        message = str(raised.exception)
        self.assertIn("期望", message)
        self.assertIn("实际", message)
        self.assertFalse(self.manager.image_state_path(PROFILE_ID).exists(),
                         "校验失败不得写入任何导入状态")

    def test_bad_expect_sha256_format_is_rejected(self) -> None:
        with self.assertRaises(ctflab.CTFLabError):
            self._import(expect_sha256="not-a-hash")

    def test_manifest_match_and_mismatch(self) -> None:
        state = self._import(manifest=self.manifest)
        self.assertEqual(state["source_verification"]["method"], "manifest")
        self.assertEqual(state["source_verification"]["manifest"], str(self.manifest))
        other = self.root / "other.qcow2"
        other.write_bytes("不同内容".encode("utf-8") * 32)
        with self.assertRaises(ctflab.CTFLabError) as raised:
            self._import(source=other, manifest=self.manifest)
        self.assertIn("不一致", str(raised.exception))

    def test_manifest_without_profile_lists_available(self) -> None:
        with self.assertRaises(ctflab.CTFLabError) as raised:
            ctflab.LabManager(self.root / "state2").distribution_expectations(
                "basic-pentesting-2", None, self.manifest, None)
        self.assertIn(PROFILE_ID, str(raised.exception))

    def test_manifest_conflicts_are_refused(self) -> None:
        expectations = self.manager.distribution_expectations
        with self.assertRaises(ctflab.CTFLabError) as raised:
            expectations(PROFILE_ID, "1" * 64, self.manifest, None)
        self.assertIn("与分发清单登记的期望值不一致", str(raised.exception))

    def test_nvram_from_manifest_is_attached_and_verified(self) -> None:
        nvram = self.root / "uefi-vars.fd"
        nvram.write_bytes(b"nvram-template-bytes" * 16)
        entry = ctflab_dist.prepare_nvram_entry(self.dist_dir, profile_id=PROFILE_ID, source=nvram)
        state = self._import(manifest=self.manifest)
        self.assertEqual(state["uefi_vars_path"], str(self.dist_dir / entry["file"]))
        self.assertEqual(state["uefi_vars_sha256"], ctflab_dist.sha256_file(nvram))
        # NVRAM 被篡改时必须拒绝
        (self.dist_dir / entry["file"]).write_bytes(b"tampered-nvram")
        other_state_dir = self.root / "state3"
        manager = ctflab.LabManager(other_state_dir)
        with mock.patch.object(ctflab, "qemu_img_path", return_value="/usr/bin/qemu-img"), \
                mock.patch.object(ctflab, "qemu_info",
                                  return_value={"format": "qcow2", "virtual-size": 1024}), \
                mock.patch.object(ctflab, "run_command", side_effect=fake_run):
            with self.assertRaises(ctflab.CTFLabError) as raised:
                manager.import_image(PROFILE_ID, str(self.source), manifest=self.manifest)
        self.assertIn("NVRAM 模板 SHA-256", str(raised.exception))

    def test_explicit_nvram_conflicting_with_manifest_is_refused(self) -> None:
        nvram = self.root / "uefi-vars.fd"
        nvram.write_bytes(b"nvram-template-bytes" * 16)
        ctflab_dist.prepare_nvram_entry(self.dist_dir, profile_id=PROFILE_ID, source=nvram)
        other = self.root / "other-vars.fd"
        other.write_bytes(b"other")
        with self.assertRaises(ctflab.CTFLabError) as raised:
            self.manager.distribution_expectations(PROFILE_ID, None, self.manifest, other)
        self.assertIn("NVRAM", str(raised.exception))

    def test_reimport_with_manifest_is_idempotent_and_records_verification(self) -> None:
        first = self._import(manifest=self.manifest)
        base_path = first["base_path"]
        base_hash = ctflab.sha256_file(pathlib.Path(base_path))
        second = self._import(manifest=self.manifest)
        self.assertEqual(second["base_path"], base_path)
        self.assertEqual(ctflab.sha256_file(pathlib.Path(base_path)), base_hash)
        self.assertEqual(second["source_verification"]["method"], "manifest")


if __name__ == "__main__":
    unittest.main()
