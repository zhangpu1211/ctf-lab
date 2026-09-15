#!/usr/bin/env python3
"""Task 6.1 打包单元测试：release bundle 与 `.ctflab` 内容包。

覆盖：

- 确定性归档：相同输入 + 相同 `generated_at` 产出逐字节相同的 tar.gz；
- 完整性：MANIFEST/content 逐文件哈希、外层 `.sha256` 旁车、篡改必失败；
- 拒绝清单：磁盘、凭据、日志、缓存不进包；包内出现禁止内容时校验失败；
- 路径安全：绝对路径/`..`/符号链接条目被拒绝；
- 版本门禁：`requires_ctflab` 不满足时 `content verify` 失败；
- 白名单：包内只出现登记文件；启动器不含开发解释器硬编码；install.sh 语法有效且校验 MANIFEST；
- SBOM：许可证标识齐全、当前不内置第三方二进制（bundled=false）、项目许可证如实标为 undeclared。
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

import ctflab_package  # noqa: E402

FIXED_TIME = "2026-09-15T00:00:00Z"
PROFILE_ID = "smoke"


class PackageTestCase(unittest.TestCase):
    """构造一个最小但完整的源码根，避免依赖仓库当前的无关文件。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name) / "src"
        self.out = pathlib.Path(self.temp.name) / "out"
        self.root.mkdir()
        (self.root / "tools" / "ctflab_profiles").mkdir(parents=True)
        (self.root / "tools" / "guest_fixes" / PROFILE_ID).mkdir(parents=True)
        (self.root / "docs").mkdir()

        for rel in ctflab_package.RELEASE_TOOL_FILES:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            if rel.endswith("ctflab_utm_fixture.json"):
                path.write_text('{"fixture": true}\n', encoding="utf-8")
            else:
                path.write_text(f"# stub {path.name}\n", encoding="utf-8")
        for rel in ctflab_package.RELEASE_DOC_FILES:
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {path.name}\n", encoding="utf-8")
        shutil.copy2(PROJECT_ROOT / "tools" / "ctflab_profiles" / f"{PROFILE_ID}.yaml",
                     self.root / "tools" / "ctflab_profiles" / f"{PROFILE_ID}.yaml")
        (self.root / "tools" / "guest_fixes" / PROFILE_ID / "interfaces").write_text(
            "auto lo\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build_release(self, **kwargs) -> dict:
        params = {"version": "0.1.0", "source_root": self.root, "generated_at": FIXED_TIME}
        params.update(kwargs)
        return ctflab_package.build_release_bundle(self.out, **params)

    def build_content(self, **kwargs) -> dict:
        params = {"version": "1.0.0", "source_root": self.root, "generated_at": FIXED_TIME}
        params.update(kwargs)
        return ctflab_package.build_content_package(PROFILE_ID, self.out, **params)

    def repack(self, source: pathlib.Path, destination: pathlib.Path,
               mutate=None, extra: dict[str, bytes] | None = None,
               drop: set[str] | None = None) -> pathlib.Path:
        """重打包以模拟篡改/额外文件；返回新包路径（不带旁车文件）。"""
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(source, "r:gz") as tar:
            members = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
        if drop:
            for name in drop:
                members.pop(name, None)
        if mutate:
            members = {name: mutate(name, data) for name, data in members.items()}
        if extra:
            members.update(extra)
        with tarfile.open(destination, "w:gz") as tar:
            for name, data in sorted(members.items()):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mtime = 0
                tar.addfile(info, __import__("io").BytesIO(data))
        return destination


class DeterminismTests(PackageTestCase):
    def test_same_inputs_produce_identical_bytes(self) -> None:
        first = self.build_release()
        first_digest = first["sha256"]
        shutil.rmtree(self.out)
        second = self.build_release()
        self.assertEqual(first_digest, second["sha256"], "确定性归档必须逐字节一致")

    def test_existing_target_is_never_overwritten(self) -> None:
        self.build_release()
        with self.assertRaises(ctflab_package.PackageError) as raised:
            self.build_release()
        self.assertIn("拒绝覆盖", str(raised.exception))

    def test_published_archives_are_user_readable(self) -> None:
        release = self.build_release()
        self.assertEqual(pathlib.Path(release["bundle"]).stat().st_mode & 0o777, 0o644)
        shutil.rmtree(self.out)
        content = self.build_content()
        self.assertEqual(pathlib.Path(content["package"]).stat().st_mode & 0o777, 0o644)

    def test_generated_at_changes_archive_but_not_manifest_hashes(self) -> None:
        first = self.build_release()
        shutil.rmtree(self.out)
        second = self.build_release(generated_at="2026-09-16T00:00:00Z")
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertEqual([entry["sha256"] for entry in first["manifest"]["files"]],
                         [entry["sha256"] for entry in second["manifest"]["files"]])

    def test_release_version_cannot_drift_from_runtime(self) -> None:
        with self.assertRaises(ctflab_package.PackageError) as raised:
            self.build_release(version="9.9.9")
        self.assertIn("CTFLAB_VERSION", str(raised.exception))

    def test_build_failure_leaves_no_partial_outputs(self) -> None:
        with mock.patch.object(ctflab_package, "write_deterministic_tar_gz",
                               side_effect=OSError("simulated write failure")):
            with self.assertRaises(ctflab_package.PackageError):
                self.build_release()
        self.assertEqual(list(self.out.glob(".ctflab-*.tmp")), [])
        self.assertEqual(list(self.out.glob("*.tar.gz")), [])
        self.assertEqual(list(self.out.glob("*.sha256")), [])

    def test_sidecar_publish_failure_rolls_back_bundle(self) -> None:
        with mock.patch.object(ctflab_package, "_publish_file",
                               side_effect=ctflab_package.PackageError("sidecar failure")):
            with self.assertRaises(ctflab_package.PackageError):
                self.build_release()
        self.assertEqual(list(self.out.glob("*.tar.gz")), [])
        self.assertEqual(list(self.out.glob("*.sha256")), [])


class ReleaseBundleTests(PackageTestCase):
    def test_verify_accepts_fresh_bundle_and_reports_scope(self) -> None:
        result = self.build_release()
        report = ctflab_package.verify_release_bundle(pathlib.Path(result["bundle"]))
        manifest = report["manifest"]
        self.assertEqual(manifest["format"], "ctflab-release")
        self.assertEqual(manifest["license"]["status"], ctflab_package.PROJECT_LICENSE)
        self.assertIn("不包含 CTFLab.app", " ".join(manifest["notes"]))
        names = {entry["path"] for entry in manifest["files"]}
        self.assertIn("tools/ctflab.py", names)
        self.assertIn("tools/ctflab", names)
        self.assertIn("tools/ctflab_profiles/smoke.yaml", names)
        self.assertIn("tools/guest_fixes/smoke/interfaces", names)
        self.assertIn("README.md", names)
        self.assertIn("LICENSE", names, "项目许可证全文必须随包分发")
        self.assertFalse([name for name in names if name.startswith("tools/tests")],
                         "发布包不得包含开发测试目录")

    def test_bundle_excludes_disks_credentials_and_logs(self) -> None:
        decoys = {
            "tools/ctflab_profiles/decoy.qcow2": b"disk",
            "credentials.txt": b"user:pass",
            "tools/guest_fixes/smoke/big.raw": b"raw",
            "logs/run.log": b"log",
            "tools/__pycache__/x.pyc": b"cache",
            ".env": b"SECRET=1",
        }
        for rel, data in decoys.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        result = self.build_release()
        entries = ctflab_package.read_tar_gz(pathlib.Path(result["bundle"]))
        joined = "\n".join(sorted(entries))
        for needle in ("decoy.qcow2", "credentials.txt", "big.raw", "logs/", "__pycache__", ".env"):
            self.assertNotIn(needle, joined, f"包内不得出现 {needle}")

    def test_tampered_payload_is_rejected(self) -> None:
        result = self.build_release()
        bundle = pathlib.Path(result["bundle"])
        tampered = pathlib.Path(self.temp.name) / "tampered.tar.gz"

        def mutate(name: str, data: bytes) -> bytes:
            if name.endswith("tools/ctflab.py"):
                return data + b"\n# tampered\n"
            return data

        self.repack(bundle, tampered, mutate=mutate)
        shutil.copy2(bundle.with_name(bundle.name + ".sha256"),
                     tampered.with_name(tampered.name + ".sha256"))
        with self.assertRaises(ctflab_package.PackageError) as raised:
            ctflab_package.verify_release_bundle(tampered)
        self.assertIn("外层 SHA-256 不一致", str(raised.exception))

    def test_tampered_payload_with_matching_outer_hash_is_rejected(self) -> None:
        """即使外层哈希被同步更新，包内逐文件哈希也必须拦截。"""
        result = self.build_release()
        bundle = pathlib.Path(result["bundle"])
        tampered = pathlib.Path(self.temp.name) / "tampered2.tar.gz"

        def mutate(name: str, data: bytes) -> bytes:
            if name.endswith("tools/ctflab.py"):
                return data + b"\n# tampered\n"
            return data

        self.repack(bundle, tampered, mutate=mutate)
        digest = ctflab_package.sha256_file(tampered)
        tampered.with_name(tampered.name + ".sha256").write_text(
            f"{digest}  {tampered.name}\n", encoding="utf-8")
        with self.assertRaises(ctflab_package.PackageError) as raised:
            ctflab_package.verify_release_bundle(tampered)
        self.assertIn("文件哈希不符", str(raised.exception))

    def test_tampered_sums_file_is_rejected(self) -> None:
        result = self.build_release()
        bundle = pathlib.Path(result["bundle"])
        tampered = pathlib.Path(self.temp.name) / "tampered-sums.tar.gz"

        def mutate(name: str, data: bytes) -> bytes:
            if name.endswith("/SHA256SUMS"):
                return data.replace(b"a", b"b", 1)
            return data

        self.repack(bundle, tampered, mutate=mutate)
        digest = ctflab_package.sha256_file(tampered)
        tampered.with_name(tampered.name + ".sha256").write_text(
            f"{digest}  {tampered.name}\n", encoding="utf-8")
        with self.assertRaises(ctflab_package.PackageError) as raised:
            ctflab_package.verify_release_bundle(tampered)
        self.assertIn("SHA256SUMS", str(raised.exception))

    def test_unlisted_extra_file_is_rejected(self) -> None:
        result = self.build_release()
        bundle = pathlib.Path(result["bundle"])
        tampered = pathlib.Path(self.temp.name) / "extra.tar.gz"
        self.repack(bundle, tampered,
                    extra={"ctflab-0.1.0/tools/evil.sh": b"#!/bin/sh\n"})
        digest = ctflab_package.sha256_file(tampered)
        tampered.with_name(tampered.name + ".sha256").write_text(
            f"{digest}  {tampered.name}\n", encoding="utf-8")
        with self.assertRaises(ctflab_package.PackageError) as raised:
            ctflab_package.verify_release_bundle(tampered)
        self.assertIn("未登记文件", str(raised.exception))

    def test_launcher_is_portable_and_installer_is_valid_shell(self) -> None:
        result = self.build_release()
        entries = ctflab_package.read_tar_gz(pathlib.Path(result["bundle"]))
        launcher = entries["ctflab-0.1.0/tools/ctflab"].decode("utf-8")
        self.assertNotIn("/opt/miniconda3", launcher)
        self.assertIn("command -v python3", launcher)
        installer = entries["ctflab-0.1.0/install.sh"]
        with tempfile.NamedTemporaryFile("wb", suffix=".sh", delete=False) as handle:
            handle.write(installer)
            installer_path = handle.name
        check = subprocess.run(["sh", "-n", installer_path], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertIn("MANIFEST.json", installer.decode("utf-8"))
        self.assertIn("拒绝覆盖", installer.decode("utf-8"))

    def test_installer_creates_portable_installation(self) -> None:
        result = self.build_release()
        extracted = pathlib.Path(self.temp.name) / "extracted"
        with tarfile.open(result["bundle"], "r:gz") as tar:
            tar.extractall(extracted)
        root = extracted / "ctflab-0.1.0"
        install_prefix = pathlib.Path(self.temp.name) / "installed"
        clean_home = pathlib.Path(self.temp.name) / "home"
        clean_home.mkdir()
        env = dict(os.environ)
        env.update({"HOME": str(clean_home), "CTFLAB_PREFIX": str(install_prefix),
                    "LANG": "en_US.UTF-8"})
        env.pop("LC_ALL", None)
        completed = subprocess.run(["sh", str(root / "install.sh")], capture_output=True,
                                   text=True, errors="replace", env=env)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue((install_prefix / "tools" / "ctflab.py").is_file())
        launcher = clean_home / "Library" / "Application Support" / "CTFLab" / "bin" / "ctflab"
        self.assertTrue(launcher.is_file())
        self.assertNotEqual(launcher.stat().st_mode & 0o111, 0)
        self.assertIn(str(install_prefix), launcher.read_text(encoding="utf-8"))

    def test_manifest_contains_no_absolute_paths(self) -> None:
        result = self.build_release()
        text = json.dumps(result["manifest"], ensure_ascii=False)
        for needle in ("/Users/", "/tmp/", "/private/"):
            self.assertNotIn(needle, text)


class ForbiddenPathTests(unittest.TestCase):
    def test_forbidden_reason_table(self) -> None:
        cases = {
            "tools/a.qcow2": "磁盘",
            "images/base.raw": "磁盘",
            "logs/x.txt": "日志" if False else "禁止",
            "runtime/x.json": "禁止",
            "credentials.txt": "凭据",
            ".env": "隐藏",
            ".env.local": "隐藏",
            "/abs/path": "绝对路径",
            "../escape": "绝对路径",
            "tools/ok.py": None,
            "docs/readme.md": None,
        }
        for rel, expected in cases.items():
            with self.subTest(path=rel):
                reason = ctflab_package.forbidden_reason(rel)
                if expected is None:
                    self.assertIsNone(reason)
                else:
                    self.assertIsNotNone(reason)
                    self.assertIn(expected, reason)


class ContentPackageTests(PackageTestCase):
    def test_verify_accepts_fresh_content_package(self) -> None:
        result = self.build_content()
        report = ctflab_package.verify_content_package(pathlib.Path(result["package"]))
        content = report["content"]
        self.assertEqual(content["id"], PROFILE_ID)
        self.assertEqual(content["name"], "Smoke")
        self.assertIs(content["image"]["disk_included"], False)
        self.assertTrue(content["image"]["source_required"])
        self.assertEqual(content["requires_ctflab"], ">=0.1.0")
        names = {entry["path"] for entry in content["files"]}
        self.assertEqual(names, {"profile/smoke.yaml", "guest_fixes/smoke/interfaces"})

    def test_content_entries_are_exactly_manifest_and_readme(self) -> None:
        result = self.build_content()
        entries = set(ctflab_package.read_tar_gz(pathlib.Path(result["package"])))
        self.assertEqual(entries, {"content.json", "README.md", "profile/smoke.yaml",
                                   "guest_fixes/smoke/interfaces"})

    def test_content_package_never_contains_disks(self) -> None:
        (self.root / "tools" / "guest_fixes" / PROFILE_ID / "payload.qcow2").write_bytes(b"disk")
        result = self.build_content()
        entries = ctflab_package.read_tar_gz(pathlib.Path(result["package"]))
        self.assertNotIn("guest_fixes/smoke/payload.qcow2", entries)

    def test_version_gate_refuses_newer_requirement(self) -> None:
        result = self.build_content()
        package = pathlib.Path(result["package"])
        tampered = pathlib.Path(self.temp.name) / f"{PROFILE_ID}-1.0.0.ctflab"

        def mutate(name: str, data: bytes) -> bytes:
            if name == "content.json":
                payload = json.loads(data.decode("utf-8"))
                payload["requires_ctflab"] = ">=99.0.0"
                return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            return data

        self.repack(package, tampered, mutate=mutate)
        with self.assertRaises(ctflab_package.PackageError) as raised:
            ctflab_package.verify_content_package(tampered)
        self.assertIn("不满足", str(raised.exception))
        report = ctflab_package.verify_content_package(tampered, check_version=False)
        self.assertEqual(report["content"]["requires_ctflab"], ">=99.0.0")

    def test_tampered_content_file_is_rejected(self) -> None:
        result = self.build_content()
        package = pathlib.Path(result["package"])
        tampered = pathlib.Path(self.temp.name) / f"{PROFILE_ID}-1.0.0.ctflab"

        def mutate(name: str, data: bytes) -> bytes:
            if name.endswith(".yaml"):
                return data.replace(b"id: smoke", b"id: smoke # x")
            return data

        self.repack(package, tampered, mutate=mutate)
        with self.assertRaises(ctflab_package.PackageError) as raised:
            ctflab_package.verify_content_package(tampered)
        self.assertIn("文件哈希不符", str(raised.exception))

    def test_unlisted_extra_entry_is_rejected(self) -> None:
        result = self.build_content()
        package = pathlib.Path(result["package"])
        tampered = pathlib.Path(self.temp.name) / f"{PROFILE_ID}-1.0.0.ctflab"
        self.repack(package, tampered, extra={"profile/extra.yaml": b"schema: 1\n"})
        with self.assertRaises(ctflab_package.PackageError) as raised:
            ctflab_package.verify_content_package(tampered)
        self.assertIn("未登记文件", str(raised.exception))

    def test_wrong_extension_and_bad_id_are_rejected(self) -> None:
        result = self.build_content()
        renamed = pathlib.Path(self.temp.name) / "smoke-1.0.0.tar.gz"
        shutil.copy2(result["package"], renamed)
        with self.assertRaises(ctflab_package.PackageError):
            ctflab_package.verify_content_package(renamed)

    def test_unpack_writes_files_and_refuses_overwrite(self) -> None:
        result = self.build_content()
        target = pathlib.Path(self.temp.name) / "unpacked"
        written = ctflab_package.unpack_content_package(pathlib.Path(result["package"]), target)
        self.assertEqual(len(written), 2)
        self.assertTrue((target / "profile" / "smoke.yaml").is_file())
        with self.assertRaises(ctflab_package.PackageError) as raised:
            ctflab_package.unpack_content_package(pathlib.Path(result["package"]), target)
        self.assertIn("拒绝覆盖", str(raised.exception))

    def test_unpack_preflights_all_targets_before_writing(self) -> None:
        result = self.build_content()
        target = pathlib.Path(self.temp.name) / "preflight"
        (target / "guest_fixes" / PROFILE_ID).mkdir(parents=True)
        (target / "guest_fixes" / PROFILE_ID / "interfaces").write_text("external\n", encoding="utf-8")
        with self.assertRaises(ctflab_package.PackageError):
            ctflab_package.unpack_content_package(pathlib.Path(result["package"]), target)
        self.assertFalse((target / "profile" / "smoke.yaml").exists(),
                         "冲突预检失败时不得留下已写入的前置文件")

    def test_unpack_preserves_declared_executable_mode(self) -> None:
        fix = self.root / "tools" / "guest_fixes" / PROFILE_ID / "run.sh"
        fix.write_text("#!/bin/sh\n", encoding="utf-8")
        fix.chmod(0o755)
        result = self.build_content()
        target = pathlib.Path(self.temp.name) / "mode"
        ctflab_package.unpack_content_package(pathlib.Path(result["package"]), target)
        self.assertEqual((target / "guest_fixes" / PROFILE_ID / "run.sh").stat().st_mode & 0o777, 0o755)

    def test_invalid_profile_is_refused_at_pack_time(self) -> None:
        profile_path = self.root / "tools" / "ctflab_profiles" / f"{PROFILE_ID}.yaml"
        profile_path.write_text("schema: 1\nid: smoke\nname: Smoke\n", encoding="utf-8")
        with self.assertRaises(Exception) as raised:
            self.build_content()
        self.assertIn("缺少字段", str(raised.exception))


class TarSafetyTests(PackageTestCase):
    def test_absolute_and_traversal_entries_are_refused(self) -> None:
        for name in ("/etc/passwd", "../escape", "ctflab-0.1.0/../../evil"):
            with self.subTest(entry=name):
                path = pathlib.Path(self.temp.name) / "evil.tar.gz"
                with tarfile.open(path, "w:gz") as tar:
                    info = tarfile.TarInfo(name)
                    info.size = 1
                    tar.addfile(info, __import__("io").BytesIO(b"x"))
                with self.assertRaises(ctflab_package.PackageError) as raised:
                    ctflab_package.read_tar_gz(path)
                self.assertIn("路径不合法", str(raised.exception))

    def test_symlink_entry_is_refused(self) -> None:
        path = pathlib.Path(self.temp.name) / "link.tar.gz"
        with tarfile.open(path, "w:gz") as tar:
            info = tarfile.TarInfo("ctflab-0.1.0/tools/ctflab")
            info.type = tarfile.SYMTYPE
            info.linkname = "/usr/bin/python3"
            tar.addfile(info)
        with self.assertRaises(ctflab_package.PackageError) as raised:
            ctflab_package.read_tar_gz(path)
        self.assertIn("非常规条目", str(raised.exception))

    def test_duplicate_file_entry_is_refused(self) -> None:
        path = pathlib.Path(self.temp.name) / "duplicate.tar.gz"
        with tarfile.open(path, "w:gz") as tar:
            for payload in (b"first", b"second"):
                info = tarfile.TarInfo("ctflab-0.1.0/tools/ctflab")
                info.size = len(payload)
                tar.addfile(info, __import__("io").BytesIO(payload))
        with self.assertRaises(ctflab_package.PackageError) as raised:
            ctflab_package.read_tar_gz(path)
        self.assertIn("重复条目", str(raised.exception))

    def test_malformed_json_is_reported_as_package_error(self) -> None:
        path = pathlib.Path(self.temp.name) / "malformed.tar.gz"
        with tarfile.open(path, "w:gz") as tar:
            info = tarfile.TarInfo("ctflab-0.1.0/MANIFEST.json")
            info.size = 3
            tar.addfile(info, __import__("io").BytesIO(b"{x}"))
        digest = ctflab_package.sha256_file(path)
        path.with_name(path.name + ".sha256").write_text(
            f"{digest}  {path.name}\n", encoding="utf-8")
        with self.assertRaises(ctflab_package.PackageError) as raised:
            ctflab_package.verify_release_bundle(path)
        self.assertIn("MANIFEST.json 不是有效 JSON", str(raised.exception))


class SbomTests(PackageTestCase):
    def test_sbom_reports_licenses_and_does_not_claim_bundling(self) -> None:
        result = self.build_release()
        entries = ctflab_package.read_tar_gz(pathlib.Path(result["bundle"]))
        sbom = json.loads(entries["ctflab-0.1.0/SBOM.json"].decode("utf-8"))
        by_name = {component["name"]: component for component in sbom["components"]}
        self.assertEqual(by_name["ctflab"]["license"], ctflab_package.PROJECT_LICENSE)
        self.assertIs(by_name["ctflab"]["bundled"], True)
        self.assertEqual(by_name["PyYAML"]["license"], "MIT")
        self.assertEqual(by_name["QEMU (qemu-system-*, qemu-img)"]["license"], "GPL-2.0-only")
        others = [c for name, c in by_name.items() if name != "ctflab"]
        self.assertTrue(all(c["bundled"] is False for c in others),
                        "当前发布包不内置任何第三方组件")
        licenses = entries["ctflab-0.1.0/THIRD_PARTY_LICENSES.md"].decode("utf-8")
        self.assertIn(ctflab_package.PROJECT_LICENSE, licenses)
        self.assertIn("LICENSE", licenses)
        self.assertIn("MIT", licenses)

    def test_sums_file_lists_every_file(self) -> None:
        result = self.build_release()
        entries = ctflab_package.read_tar_gz(pathlib.Path(result["bundle"]))
        sums = entries["ctflab-0.1.0/SHA256SUMS"].decode("utf-8").splitlines()
        listed = {line.split("  ", 1)[1] for line in sums}
        manifest_paths = {entry["path"] for entry in result["manifest"]["files"]}
        self.assertTrue(manifest_paths <= listed, "SHA256SUMS 必须覆盖全部登记文件")
        self.assertIn("MANIFEST.json", listed)


class VersionGateTests(unittest.TestCase):
    def test_version_parsing_and_constraints(self) -> None:
        self.assertEqual(ctflab_package.parse_version("1.2.3"), (1, 2, 3))
        self.assertTrue(ctflab_package.version_satisfies("0.1.0", ">=0.1.0"))
        self.assertTrue(ctflab_package.version_satisfies("0.2.0", ">0.1.0"))
        self.assertFalse(ctflab_package.version_satisfies("0.1.0", ">0.1.0"))
        self.assertTrue(ctflab_package.version_satisfies("1.0.0", "==1.0.0"))
        for bad in ("1.0", "v1.0.0", "", "1.0.0.0"):
            with self.subTest(value=bad):
                with self.assertRaises(ctflab_package.PackageError):
                    ctflab_package.parse_version(bad)
        with self.assertRaises(ctflab_package.PackageError):
            ctflab_package.version_satisfies("1.0.0", ">=1")


class CliSurfaceTests(unittest.TestCase):
    def test_package_and_content_subcommands_exist(self) -> None:
        import ctflab  # noqa: PLC0415

        parser = ctflab.build_parser()
        subcommands: dict[str, object] = {}
        for action in parser._subparsers._group_actions:
            subcommands.update(action.choices)
        self.assertIn("package", subcommands)
        self.assertIn("content", subcommands)
        package_choices = {}
        for action in subcommands["package"]._subparsers._group_actions:  # type: ignore[attr-defined]
            package_choices.update(action.choices)
        self.assertEqual(set(package_choices), {"build", "verify"})
        content_choices = {}
        for action in subcommands["content"]._subparsers._group_actions:  # type: ignore[attr-defined]
            content_choices.update(action.choices)
        self.assertEqual(set(content_choices), {"pack", "verify", "unpack"})

    def test_version_flag_is_wired(self) -> None:
        import ctflab  # noqa: PLC0415

        output = subprocess.run([sys.executable, str(TOOLS_DIR / "ctflab.py"), "--version"],
                                capture_output=True, text=True)
        self.assertEqual(output.returncode, 0)
        self.assertIn(ctflab.CTFLAB_VERSION, output.stdout)


if __name__ == "__main__":
    unittest.main()
