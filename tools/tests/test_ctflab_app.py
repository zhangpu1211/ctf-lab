#!/usr/bin/env python3
"""Task 6.2 单元测试：`CTFLab.app` 结构、运行时闭包、清单、SBOM 与签名分级。

测试用一个**用 clang 现场编译的最小 QEMU 替身**（3 个可执行 + 两级 dylib 依赖 + 假 firmware），
因此不依赖本机 Homebrew QEMU，也不需要网络；真实 QEMU 的 E2E 由
`tools/ctflab_app_e2e.py` 覆盖（见 `docs/verification-task6-2-2026-09-15.md`）。
"""

from __future__ import annotations

import json
import os
import pathlib
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

import ctflab  # noqa: E402
import ctflab_app  # noqa: E402
import ctflab_app_kali_e2e  # noqa: E402
import ctflab_package  # noqa: E402

CLANG = shutil.which("clang")
FAKE_SHARE_FILES = ("firmware-a.fd", "firmware-b.fd", "bios-test.bin", "rom-test.rom",
                    "edk2-licenses.txt")

MAIN_C = """#include <stdio.h>
#include <string.h>
int stub_answer(void);
int main(int argc, char **argv) {
  if (argc > 1 && strcmp(argv[1], "--version") == 0) {
    printf("QEMU emulator version 11.1.0\\n");
    return 0;
  }
  printf("%d\\n", stub_answer());
  return 0;
}
"""
PYTHON_MAIN_C = """#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
  if (argc > 1 && strcmp(argv[1], "--version") == 0) {
    printf("Python 3.12.14\\n");
    return 0;
  }
  printf("stub python\\n");
  return 0;
}
"""
BUNDLE_C = "int stub_bundle(void) { return 7; }\n"
LIB_C = "int stub_answer(void) { return 42; }\n"
LIB2_C = "int stub_answer(void); int layer2(void) { return stub_answer() + 1; }\n"


class FakePythonRuntime:
    """用 clang 构造最小 Python 发行版替身：symlink、可裁剪项与一个 Mach-O 扩展模块。"""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root

    @staticmethod
    def _clang(args: list[str]) -> None:
        result = subprocess.run([CLANG, "-mmacosx-version-min=26.0", *args],
                                capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr)

    def build(self) -> pathlib.Path:
        root = self.root
        (root / "bin").mkdir(parents=True, exist_ok=True)
        (root / "lib" / "python3.12" / "lib-dynload").mkdir(parents=True, exist_ok=True)
        (root / "lib" / "python3.12" / "site-packages").mkdir(parents=True, exist_ok=True)
        (root / "lib" / "python3.12" / "encodings").mkdir(parents=True, exist_ok=True)
        (root / "lib" / "python3.12" / "tkinter").mkdir(parents=True, exist_ok=True)
        (root / "include" / "python3.12").mkdir(parents=True, exist_ok=True)
        (root / "share" / "man" / "man1").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as temp:
            temp_path = pathlib.Path(temp)
            (temp_path / "main.c").write_text(PYTHON_MAIN_C, encoding="utf-8")
            (temp_path / "bundle.c").write_text(BUNDLE_C, encoding="utf-8")
            (temp_path / "lib.c").write_text(LIB_C, encoding="utf-8")
            self._clang(["-o", str(root / "bin" / "python3.12"), str(temp_path / "main.c")])
            self._clang(["-dynamiclib", "-o", str(root / "lib" / "libpython3.12.dylib"),
                         str(temp_path / "lib.c")])
            self._clang(["-bundle", "-undefined", "dynamic_lookup", "-o",
                         str(root / "lib" / "python3.12" / "lib-dynload"
                             / "_example.cpython-312-darwin.so"),
                         str(temp_path / "bundle.c")])
        (root / "bin" / "python3").symlink_to("python3.12")
        (root / "bin" / "pip3").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (root / "lib" / "python3.12" / "LICENSE.txt").write_text("PSF LICENSE stub\n", encoding="utf-8")
        (root / "lib" / "python3.12" / "encodings" / "__init__.py").write_text("", encoding="utf-8")
        (root / "lib" / "python3.12" / "site-packages" / "README.txt").write_text(
            "stub\n", encoding="utf-8")
        (root / "lib" / "python3.12" / "tkinter" / "__init__.py").write_text("", encoding="utf-8")
        (root / "include" / "python3.12" / "Python.h").write_text("/* stub */\n", encoding="utf-8")
        (root / "share" / "man" / "man1" / "python3.1").write_text("stub\n", encoding="utf-8")
        return root


def make_fake_pyyaml(path: pathlib.Path) -> pathlib.Path:
    """构造最小 PyYAML wheel（zip）：yaml/ 包（含真实 Mach-O 扩展）、_yaml/、dist-info 许可证。"""
    import zipfile

    extension_bytes = b"\0" * 16
    if CLANG:
        with tempfile.TemporaryDirectory() as temp:
            source = pathlib.Path(temp) / "bundle.c"
            target = pathlib.Path(temp) / "bundle.so"
            source.write_text(BUNDLE_C, encoding="utf-8")
            FakePythonRuntime._clang(["-bundle", "-undefined", "dynamic_lookup",
                                     "-o", str(target), str(source)])
            extension_bytes = target.read_bytes()

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("yaml/__init__.py", "def safe_load(text):\n    return {}\n")
        archive.writestr("yaml/_yaml.cpython-312-darwin.so", extension_bytes)
        archive.writestr("_yaml/__init__.py", "import yaml\n")
        archive.writestr("pyyaml-6.0.3.dist-info/METADATA",
                         "Metadata-Version: 2.1\nName: PyYAML\nVersion: 6.0.3\n")
        archive.writestr("pyyaml-6.0.3.dist-info/licenses/LICENSE", "MIT License stub\n")
    return path


class FakeRuntime:
    """用 clang 构造最小 Mach-O 运行时：绝对路径依赖 → 必须被改写为 @loader_path。"""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.bin_dir = root / "bin"
        self.lib_dir = root / "lib"
        self.share_dir = root / "share" / "qemu"

    def build(self) -> "FakeRuntime":
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        self.lib_dir.mkdir(parents=True, exist_ok=True)
        self.share_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as temp:
            temp_path = pathlib.Path(temp)
            (temp_path / "main.c").write_text(MAIN_C, encoding="utf-8")
            (temp_path / "lib.c").write_text(LIB_C, encoding="utf-8")
            (temp_path / "lib2.c").write_text(LIB2_C, encoding="utf-8")
            stub = self.lib_dir / "libstub.dylib"
            layer2 = self.lib_dir / "liblayer2.dylib"
            self._clang(["-dynamiclib", "-o", str(stub), "-install_name", str(stub),
                         str(temp_path / "lib.c")])
            self._clang(["-dynamiclib", "-o", str(layer2), "-install_name", str(layer2),
                         str(temp_path / "lib2.c"), str(stub)])
            for name in ctflab_app.QEMU_BINARIES:
                binary = self.bin_dir / name
                self._clang(["-o", str(binary), str(temp_path / "main.c"), str(layer2), str(stub)])
        for name in FAKE_SHARE_FILES + ctflab_app.QEMU_OPTIONAL_SHARE_FILES:
            (self.share_dir / name).write_bytes(f"fake-{name}\n".encode())
        keymaps = self.share_dir / "keymaps"
        keymaps.mkdir(exist_ok=True)
        (keymaps / "en-us").write_text("keymap\n", encoding="utf-8")
        return self

    @staticmethod
    def _clang(args: list[str]) -> None:
        result = subprocess.run([CLANG, "-mmacosx-version-min=26.0", *args],
                                capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr)


def make_source_root(path: pathlib.Path, *, with_decoys: bool = False,
                     with_vendored: bool = False) -> pathlib.Path:
    """最小 CTFLab 源码树（用于 app 内的 tools/ 镜像）。"""
    path.mkdir(parents=True, exist_ok=True)
    (path / "tools" / "ctflab_profiles").mkdir(parents=True, exist_ok=True)
    (path / "tools" / "guest_fixes" / "smoke").mkdir(parents=True, exist_ok=True)
    for rel in ctflab_package.RELEASE_TOOL_FILES:
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# stub {target.name}\n", encoding="utf-8")
    (path / "tools" / "ctflab_profiles" / "smoke.yaml").write_text(
        (PROJECT_ROOT / "tools" / "ctflab_profiles" / "smoke.yaml").read_text(encoding="utf-8"),
        encoding="utf-8")
    (path / "tools" / "guest_fixes" / "smoke" / "interfaces").write_text("auto lo\n", encoding="utf-8")
    (path / "README.md").write_text("# stub\n", encoding="utf-8")
    (path / "LICENSE").write_text("MIT License\n\nstub for tests\n", encoding="utf-8")
    gui_dir = path / ctflab_app.GUI_SOURCE_DIR
    gui_dir.mkdir(parents=True, exist_ok=True)
    for name in ctflab_app.GUI_SOURCES:
        (gui_dir / name).write_text(f"// stub {name}\n", encoding="utf-8")
    if with_vendored:
        # 假 runtime 的 dylib 不在 /opt/homebrew 下，formula 归为 unknown；
        # 在 vendored 目录里放文本即可命中回退路径。
        vendored = path / "tools" / "licenses" / "unknown"
        vendored.mkdir(parents=True, exist_ok=True)
        (vendored / "BSD-2-Clause").write_text("vendored license stub\n", encoding="utf-8")
    if with_decoys:
        (path / "tools" / "guest_fixes" / "smoke" / "evil.qcow2").write_bytes(b"disk")
        (path / "tools" / "guest_fixes" / "smoke" / "guest-credentials.txt").write_bytes(b"secret")
        (path / "tools" / "guest_fixes" / "smoke" / "capture.pcap").write_bytes(b"pcap")
        (path / "tools" / "logs").mkdir(parents=True, exist_ok=True)
        (path / "tools" / "logs" / "run.log").write_text("log\n", encoding="utf-8")
    return path


@unittest.skipUnless(CLANG, "需要 clang 构造最小 Mach-O 运行时")
class AppTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._class_temp = tempfile.TemporaryDirectory()
        base = pathlib.Path(cls._class_temp.name)
        cls.fake_runtime = FakeRuntime(base / "fakeqemu").build().root
        cls.source_root = make_source_root(base / "src")
        cls.fake_python = FakePythonRuntime(base / "fakepython").build()
        cls.fake_pyyaml = make_fake_pyyaml(base / "pyyaml-6.0.3-cp312-cp312-macosx_11_0_arm64.whl")
        # 预编译的 GUI 入口替身：避免每个用例都调用 swiftc（真实编译路径由专门的用例覆盖）。
        cls.fake_gui = base / "CTFLabGUI-stub"
        with tempfile.TemporaryDirectory() as temp:
            stub_c = pathlib.Path(temp) / "gui.c"
            stub_c.write_text("int main(void) { return 0; }\n", encoding="utf-8")
            result = subprocess.run([CLANG, "-mmacosx-version-min=26.0", "-o", str(cls.fake_gui), str(stub_c)],
                                    capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(result.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._class_temp.cleanup()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.out = pathlib.Path(self.temp.name) / "out"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build(self, **kwargs):
        params = {
            "version": "0.1.0",
            "source_root": self.source_root,
            "qemu_root": self.fake_runtime,
            "python_runtime": self.fake_python,
            "pyyaml_source": self.fake_pyyaml,
            "generated_at": "2026-09-15T00:00:00Z",
            "allow_incomplete_license_texts": True,
            "unsigned": True,
            "share_files": FAKE_SHARE_FILES,
            "gui_binary": self.fake_gui,
        }
        params.update(kwargs)
        return ctflab_app.build_app(self.out, **params)


class StructureTests(AppTestCase):
    def test_required_structure_and_info_plist(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        for rel in ("Contents/Info.plist",
                    f"Contents/MacOS/{ctflab_app.GUI_EXECUTABLE}",
                    ctflab_app.LAUNCHER_REL, ctflab_app.LAUNCHER_COMPAT_REL,
                    "Contents/Resources/ctflab/tools/ctflab.py",
                    "Contents/Resources/MANIFEST.json", "Contents/Resources/SBOM.json",
                    "Contents/Resources/THIRD_PARTY_LICENSES.md",
                    "Contents/Resources/licenses",
                    "Contents/Resources/runtime/bin", "Contents/Resources/runtime/lib",
                    "Contents/Resources/runtime/share/qemu"):
            self.assertTrue((app / rel).exists(), f"缺少 {rel}")
        info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
        self.assertEqual(info["CFBundleExecutable"], ctflab_app.GUI_EXECUTABLE)
        self.assertEqual(info["CFBundleIdentifier"], ctflab_app.BUNDLE_IDENTIFIER)
        self.assertEqual(info["CFBundleShortVersionString"], "0.1.0")
        self.assertEqual(info["LSMinimumSystemVersion"], "26.0")
        self.assertEqual(ctflab_app.MIN_BUNDLED_MACOS_VERSION, (26, 0))

    def test_launcher_has_no_developer_paths(self) -> None:
        result = self.build()
        launcher = (pathlib.Path(result["app"]) / ctflab_app.LAUNCHER_REL).read_text(encoding="utf-8")
        self.assertIn("CTFLAB_RUNTIME_ROOT", launcher)
        self.assertIn("runtime/python/bin/python3", launcher)
        self.assertIn("-B -s -E", launcher)
        self.assertNotIn("command -v python3", launcher,
                         "启动器不得探测系统 Python（必须使用内置解释器）")
        for needle in ("/opt/homebrew", "/usr/local", "/Users/", "conda"):
            self.assertNotIn(needle, launcher)

    def test_runtime_binaries_present_and_executable(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        for name in ctflab_app.QEMU_BINARIES:
            binary = app / ctflab_app.RUNTIME_REL / "bin" / name
            self.assertTrue(binary.is_file(), name)
            self.assertTrue(os.access(binary, os.X_OK), name)
        share = app / ctflab_app.RUNTIME_REL / "share" / "qemu"
        for name in FAKE_SHARE_FILES:
            self.assertTrue((share / name).is_file(), name)
        self.assertTrue((share / "keymaps").is_dir())

    def test_optional_qemu_share_file_is_copied_when_present(self) -> None:
        destination = pathlib.Path(self.temp.name) / "share-copy"
        destination.mkdir()
        with mock.patch.object(ctflab_app, "QEMU_SHARE_FILES", ("firmware-a.fd",)), \
             mock.patch.object(ctflab_app, "QEMU_OPTIONAL_SHARE_FILES", ("sgabios.bin",)), \
             mock.patch.object(ctflab_app, "QEMU_SHARE_DIRS", ()):
            copied = ctflab_app.copy_qemu_share(self.fake_runtime, destination)
        self.assertEqual(copied, ["firmware-a.fd", "sgabios.bin"])
        self.assertTrue((destination / "sgabios.bin").is_file())


class RuntimeClosureTests(AppTestCase):
    def test_dylib_closure_copied_inside_app(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        lib_dir = app / ctflab_app.RUNTIME_REL / "lib"
        names = {path.name for path in lib_dir.iterdir()}
        self.assertIn("libstub.dylib", names)
        self.assertIn("liblayer2.dylib", names, "传递依赖（第二级）也必须随包")
        self.assertEqual(result["manifest"]["runtime"]["dylibs"], sorted(names))

    def test_otool_references_have_no_absolute_developer_paths(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        runtime = app / ctflab_app.RUNTIME_REL
        for path in [*(runtime / "bin").iterdir(), *(runtime / "lib").iterdir()]:
            listing = subprocess.run(["otool", "-l", str(path)], capture_output=True, text=True).stdout
            for needle in ("/opt/homebrew", "/usr/local", "/Users/", "conda"):
                self.assertNotIn(needle, listing, f"{path.name} 含 {needle}")
            for dep in ctflab_app.otool_deps(path):
                if ctflab_app.is_system_library(dep):
                    continue
                self.assertTrue(dep.startswith("@loader_path/"),
                                f"{path.name} 的非系统依赖未相对化：{dep}")
                target = (path.parent / dep[len("@loader_path/"):]).resolve()
                self.assertTrue(target.is_file(), f"{path.name} 依赖缺失：{dep}")

    def test_unresolvable_dependency_stops_build(self) -> None:
        """依赖指向不存在的位置时必须失败，不允许猜测或跳过。"""
        broken = FakeRuntime(pathlib.Path(self.temp.name) / "brokenqemu").build().root
        (broken / "lib" / "libstub.dylib").unlink()
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            self.build(qemu_root=broken)
        self.assertIn("依赖不存在", str(raised.exception))

    def test_verify_rejects_forbidden_rpath(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        binary = app / ctflab_app.RUNTIME_REL / "bin" / "qemu-img"
        subprocess.run(
            ["install_name_tool", "-add_rpath", "/opt/homebrew/forbidden", str(binary)],
            check=True, capture_output=True, text=True,
        )
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            ctflab_app.verify_app(app, check_signature=False)
        self.assertIn("rpath", str(raised.exception).lower())


class ManifestAndSbomTests(AppTestCase):
    def test_manifest_hashes_cover_app_and_verify_detects_tamper(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        report = ctflab_app.verify_app(app, check_signature=False)
        self.assertEqual(report["file_count"], len(result["manifest"]["files"]))
        target = app / ctflab_app.RUNTIME_REL / "share" / "qemu" / FAKE_SHARE_FILES[0]
        target.write_bytes(b"tampered\n")
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            ctflab_app.verify_app(app, check_signature=False)
        self.assertIn("哈希不符", str(raised.exception))

    def test_unlisted_extra_file_is_rejected(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        (app / "Contents" / "Resources" / "extra.bin").write_bytes(b"x")
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            ctflab_app.verify_app(app, check_signature=False)
        self.assertIn("未登记文件", str(raised.exception))

    def test_sbom_bundled_entries_match_files(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        sbom = json.loads((app / ctflab_app.SBOM_REL).read_text(encoding="utf-8"))
        bundled_files = []
        for component in sbom["components"]:
            if not component.get("bundled"):
                continue
            if component.get("file"):
                bundled_files.append(component["file"])
            for binary in component.get("binaries", []):
                bundled_files.append(binary["file"])
        self.assertTrue(bundled_files)
        for rel in bundled_files:
            self.assertTrue((app / rel).is_file(), rel)
        qemu = next(c for c in sbom["components"] if c["name"] == "QEMU")
        self.assertTrue(qemu["distribution_obligations"], "QEMU 分发义务必须单独列出")
        self.assertTrue(all(b["bundled"] is True for b in qemu["binaries"]))
        non_qemu = [c for c in sbom["components"] if c.get("file")]
        self.assertTrue(all(c["bundled"] is True for c in non_qemu),
                        "随包动态库必须标为 bundled=true")
        serialized = json.dumps(sbom, ensure_ascii=False)
        for needle in ("/opt/homebrew", "/usr/local/", "/Users/", "conda"):
            self.assertNotIn(needle, serialized, "SBOM 不得泄露构建机绝对路径")

    def test_missing_bundled_file_fails_verification(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        (app / ctflab_app.RUNTIME_REL / "lib" / "libstub.dylib").unlink()
        with self.assertRaises(ctflab_app.AppBuildError):
            ctflab_app.verify_app(app, check_signature=False)

    def test_sidecar_is_required_and_verified(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        sidecar = pathlib.Path(result["sidecar"])
        sidecar.unlink()
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            ctflab_app.verify_app(app, check_signature=False)
        self.assertIn("旁车", str(raised.exception))
        sidecar.write_text("0" * 64 + "  CTFLab.app\n", encoding="utf-8")
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            ctflab_app.verify_app(app, check_signature=False)
        self.assertIn("旁车校验不一致", str(raised.exception))

    def test_malformed_manifest_is_reported_as_app_error(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        (app / ctflab_app.MANIFEST_REL).write_text("{broken", encoding="utf-8")
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            ctflab_app.verify_app(app, check_signature=False)
        self.assertIn("元数据无法解析", str(raised.exception))

    def test_malformed_sbom_shape_is_reported_as_app_error(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        sbom_path = app / ctflab_app.SBOM_REL
        sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
        sbom["components"] = ["not-an-object"]
        sbom_path.write_text(json.dumps(sbom), encoding="utf-8")
        # 同步 MANIFEST 中 SBOM 哈希，让测试抵达结构校验而不是先被普通篡改检查拦截。
        manifest_path = app / ctflab_app.MANIFEST_REL
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            if entry["path"] == ctflab_app.SBOM_REL:
                entry["sha256"] = ctflab_app.sha256_file(sbom_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            ctflab_app.verify_app(app, check_signature=False)
        self.assertIn("SBOM.components", str(raised.exception))

    def test_symlink_app_is_rejected(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        alias = self.out / "Alias.app"
        alias.symlink_to(app, target_is_directory=True)
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            ctflab_app.verify_app(alias, check_signature=False)
        self.assertIn("普通 .app", str(raised.exception))


class ForbiddenContentTests(AppTestCase):
    def test_disks_credentials_logs_never_enter_app(self) -> None:
        decoy_source = make_source_root(pathlib.Path(self.temp.name) / "decoy-src", with_decoys=True)
        result = self.build(source_root=decoy_source, allow_incomplete_license_texts=True)
        app = pathlib.Path(result["app"])
        names = [path.name for path in app.rglob("*")]
        for banned in ("evil.qcow2", "guest-credentials.txt", "capture.pcap", "run.log"):
            self.assertNotIn(banned, names, f"app 内出现禁止文件：{banned}")
        self.assertEqual([p for p in app.rglob("*.qcow2")], [])
        self.assertEqual([p for p in app.rglob("*.pcap")], [])
        self.assertEqual([p for p in app.rglob("credentials*.txt")], [])

    def test_state_directory_stays_outside_app(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"]).resolve()
        default_state = ctflab.DEFAULT_STATE_DIR.expanduser()
        self.assertFalse(str(default_state).startswith(str(app)),
                         "默认状态目录必须在 app 之外")
        launcher = (app / ctflab_app.LAUNCHER_REL).read_text(encoding="utf-8")
        self.assertNotIn("--state-dir", launcher)


class PublishTests(AppTestCase):
    def test_existing_target_is_refused(self) -> None:
        self.build()
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            self.build()
        self.assertIn("拒绝覆盖", str(raised.exception))

    def test_failed_build_leaves_no_partial_output(self) -> None:
        incomplete = pathlib.Path(self.temp.name) / "incompleteqemu"
        shutil.copytree(self.fake_runtime, incomplete)
        (incomplete / "share" / "qemu" / FAKE_SHARE_FILES[0]).unlink()
        with self.assertRaises(ctflab_app.AppBuildError):
            self.build(qemu_root=incomplete)
        self.assertFalse((self.out / "CTFLab.app").exists(), "失败后不得留下最终 app")
        leftovers = [p for p in self.out.iterdir() if p.name.startswith(".CTFLab.app.")]
        self.assertEqual(leftovers, [], "失败后必须清理临时目录")

    def test_tree_hash_is_stable_and_sensitive(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        first = ctflab_app.app_tree_hash(app)
        self.assertEqual(first, ctflab_app.app_tree_hash(app))
        self.assertEqual(first, result["tree_sha256"])
        sidecar = pathlib.Path(result["sidecar"]).read_text(encoding="utf-8")
        self.assertIn(first, sidecar)
        target = app / ctflab_app.RUNTIME_REL / "bin" / "qemu-img"
        target.write_bytes(target.read_bytes() + b"\0")
        self.assertNotEqual(first, ctflab_app.app_tree_hash(app))

    def test_concurrent_app_target_is_preserved(self) -> None:
        original = ctflab_app._exclusive_publish_directory

        def race(source, destination):
            destination.mkdir()
            (destination / "external.txt").write_text("keep", encoding="utf-8")
            return original(source, destination)

        with mock.patch.object(ctflab_app, "_exclusive_publish_directory", side_effect=race):
            with self.assertRaises(ctflab_app.AppBuildError):
                self.build()
        self.assertEqual((self.out / "CTFLab.app" / "external.txt").read_text(), "keep")
        self.assertFalse((self.out / "CTFLab.app.sha256").exists())

    def test_concurrent_sidecar_rolls_back_only_published_app(self) -> None:
        def race(_source, destination):
            destination.write_text("external\n", encoding="utf-8")
            raise ctflab_app.AppBuildError("旁车并发创建")

        with mock.patch.object(ctflab_app, "_exclusive_publish_file", side_effect=race):
            with self.assertRaises(ctflab_app.AppBuildError):
                self.build()
        self.assertFalse((self.out / "CTFLab.app").exists())
        self.assertEqual((self.out / "CTFLab.app.sha256").read_text(), "external\n")

    def test_requested_version_must_match_runtime_version(self) -> None:
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            self.build(version="9.9.9")
        self.assertIn("必须与 CTFLAB_VERSION 一致", str(raised.exception))


class SigningTests(AppTestCase):
    def test_adhoc_signing_reports_adhoc_level(self) -> None:
        result = self.build(unsigned=False)
        self.assertEqual(result["signature"]["level"], "ad-hoc")
        report = ctflab_app.verify_app(pathlib.Path(result["app"]))
        self.assertEqual(report["signature"]["level"], "ad-hoc")
        self.assertFalse(report["signature"]["notarized"])
        self.assertIn("未验证", report["signature"]["notarization_status"])

    def test_unsigned_build_reports_unsigned(self) -> None:
        result = self.build(unsigned=True)
        self.assertEqual(result["signature"]["level"], "unsigned")
        report = ctflab_app.verify_app(pathlib.Path(result["app"]))
        self.assertEqual(report["signature"]["level"], "unsigned")

    def test_unknown_sign_identity_is_refused(self) -> None:
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            self.build(unsigned=False, sign_identity="Developer ID Application: Nobody (0000000000)")
        self.assertIn("未找到签名身份", str(raised.exception))


@unittest.skipUnless(CLANG, "需要 clang 构造最小 Mach-O 运行时")
class EntitlementPreservationTests(AppTestCase):
    """HVF 依赖 com.apple.security.hypervisor：重签名必须保留源二进制 entitlements。"""

    ENTITLEMENTS = {"com.apple.security.hypervisor": True}

    def _runtime_with_entitlements(self) -> pathlib.Path:
        """构造带 entitlements 的假运行时（仅 qemu-system-* 带，模拟宿主 QEMU）。"""
        runtime = FakeRuntime(pathlib.Path(self.temp.name) / "entqemu").build().root
        plist = pathlib.Path(self.temp.name) / "ent.plist"
        plist.write_bytes(plistlib.dumps(self.ENTITLEMENTS))
        for name in ("qemu-system-aarch64", "qemu-system-x86_64"):
            result = subprocess.run(
                ["codesign", "--force", "--sign", "-", "--entitlements", str(plist),
                 str(runtime / "bin" / name)],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        return runtime

    def test_read_entitlements_round_trip(self) -> None:
        runtime = self._runtime_with_entitlements()
        found = ctflab_app.read_entitlements(runtime / "bin" / "qemu-system-aarch64")
        self.assertEqual(found, self.ENTITLEMENTS)
        self.assertIsNone(ctflab_app.read_entitlements(runtime / "bin" / "qemu-img"))

    def test_build_preserves_entitlements_and_records_them(self) -> None:
        runtime = self._runtime_with_entitlements()
        result = self.build(qemu_root=runtime, unsigned=False)
        app = pathlib.Path(result["app"])
        for name in ("qemu-system-aarch64", "qemu-system-x86_64"):
            actual = ctflab_app.read_entitlements(app / ctflab_app.RUNTIME_REL / "bin" / name)
            self.assertEqual(actual, self.ENTITLEMENTS, f"{name} 丢失 entitlements（HVF 会失败）")
        recorded = result["manifest"]["runtime"]["entitlements"]
        self.assertEqual(recorded["qemu-system-aarch64"]["keys"],
                         ["com.apple.security.hypervisor"])
        self.assertRegex(recorded["qemu-system-aarch64"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            recorded["qemu-system-aarch64"],
            ctflab_app.entitlement_record(self.ENTITLEMENTS),
        )

    def test_verify_app_detects_stripped_entitlements(self) -> None:
        runtime = self._runtime_with_entitlements()
        result = self.build(qemu_root=runtime, unsigned=False)
        app = pathlib.Path(result["app"])
        target = app / ctflab_app.RUNTIME_REL / "bin" / "qemu-system-aarch64"
        strip = subprocess.run(["codesign", "--force", "--sign", "-", str(target)],
                               capture_output=True, text=True)
        self.assertEqual(strip.returncode, 0, strip.stderr)
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            ctflab_app.verify_app(app, check_signature=False)
        message = str(raised.exception)
        self.assertTrue("entitlements" in message or "哈希不符" in message, message)

    def test_verify_app_detects_changed_entitlement_value(self) -> None:
        runtime = self._runtime_with_entitlements()
        result = self.build(qemu_root=runtime, unsigned=False)
        app = pathlib.Path(result["app"])
        target = app / ctflab_app.RUNTIME_REL / "bin" / "qemu-system-aarch64"
        false_plist = pathlib.Path(self.temp.name) / "false-entitlement.plist"
        false_plist.write_bytes(plistlib.dumps({"com.apple.security.hypervisor": False}))
        resign = subprocess.run(
            ["codesign", "--force", "--sign", "-", "--entitlements", str(false_plist), str(target)],
            capture_output=True, text=True,
        )
        self.assertEqual(resign.returncode, 0, resign.stderr)
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            ctflab_app.verify_app(app, check_signature=False)
        self.assertIn("entitlements", str(raised.exception))


class LicenseComplianceTests(AppTestCase):
    """项目 LICENSE、vendored 许可证文本回退与 QEMU 源码书面要约（GPL-2.0 §3）。"""

    def test_app_ships_license_and_source_offer(self) -> None:
        source_root = make_source_root(pathlib.Path(self.temp.name) / "license-src",
                                       with_vendored=True)
        result = self.build(source_root=source_root)
        app = pathlib.Path(result["app"])
        manifest = result["manifest"]
        self.assertEqual(manifest["license"]["status"], ctflab_package.PROJECT_LICENSE)
        self.assertEqual(manifest["license"]["project_license_file"], ctflab_app.LICENSE_REL)
        blockers = manifest["license"]["distribution_blockers"]
        for blocker in blockers:
            self.assertNotIn("项目许可证未声明", blocker,
                             "许可证已声明，不得再记录旧的分发阻塞")
            self.assertNotIn("unknown", blocker, "vendored 回退应已覆盖缺失文本")
        offer = manifest["license"]["source_offer"]
        self.assertEqual(offer["qemu_version"], "11.1.0")
        self.assertEqual(offer["sha256"], ctflab_app.QEMU_SOURCE_SHA256["11.1.0"])
        self.assertEqual(offer["url"], "https://download.qemu.org/qemu-11.1.0.tar.xz")
        self.assertEqual(offer["valid_until"], "2029-09-15T00:00:00Z")
        license_text = (app / ctflab_app.LICENSE_REL).read_text(encoding="utf-8")
        self.assertIn("MIT License", license_text)
        offer_text = (app / ctflab_app.SOURCE_OFFER_REL).read_text(encoding="utf-8")
        self.assertIn("GPL", offer_text)
        self.assertIn(offer["sha256"], offer_text)
        third_party = (app / ctflab_app.THIRD_PARTY_REL).read_text(encoding="utf-8")
        self.assertIn(ctflab_package.PROJECT_LICENSE, third_party)
        ctflab_app.verify_app(app, check_signature=False)

    def test_vendored_license_texts_cover_missing_keg(self) -> None:
        source_root = make_source_root(pathlib.Path(self.temp.name) / "vendored-src",
                                       with_vendored=True)
        result = self.build(source_root=source_root)
        app = pathlib.Path(result["app"])
        dylibs = [c for c in result["sbom"]["components"] if c.get("file", "").endswith(".dylib")]
        self.assertTrue(dylibs, "fixture 必须包含 dylib 组件")
        for component in dylibs:
            self.assertEqual(component["license_text_status"], "vendored",
                             "假 runtime 的 dylib 不在 Homebrew keg 中，必须命中 vendored 回退")
        vendored_file = app / ctflab_app.LICENSES_REL / "unknown" / "BSD-2-Clause"
        self.assertTrue(vendored_file.is_file(), "vendored 许可证文本必须随包复制")

    def test_missing_project_license_stops_build(self) -> None:
        source_root = make_source_root(pathlib.Path(self.temp.name) / "no-license-src")
        (source_root / "LICENSE").unlink()
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            self.build(source_root=source_root)
        self.assertIn("LICENSE", str(raised.exception))

    def test_unregistered_qemu_version_stops_build(self) -> None:
        with mock.patch.dict(ctflab_app.QEMU_SOURCE_SHA256, {}, clear=True):
            with self.assertRaises(ctflab_app.AppBuildError) as raised:
                self.build()
        self.assertIn("未登记", str(raised.exception))

    def test_source_offer_tampering_is_rejected(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        offer_path = app / ctflab_app.SOURCE_OFFER_REL
        offer_path.write_text("# 被替换的要约\n", encoding="utf-8")
        # 同步 MANIFEST 中 SOURCE_OFFER.md 的普通文件哈希，让测试抵达要约一致性校验。
        manifest_path = app / ctflab_app.MANIFEST_REL
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            if entry["path"] == ctflab_app.SOURCE_OFFER_REL:
                entry["sha256"] = ctflab_app.sha256_file(offer_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            ctflab_app.verify_app(app, check_signature=False)
        self.assertIn("SOURCE_OFFER.md", str(raised.exception))

    def test_source_offer_registry_mismatch_is_rejected(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        manifest_path = app / ctflab_app.MANIFEST_REL
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["license"]["source_offer"]["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            ctflab_app.verify_app(app, check_signature=False)
        self.assertIn("登记表不一致", str(raised.exception))


class PythonRuntimeTests(AppTestCase):
    """内置 Python 运行时：复制、裁剪、符号链接解引用、PyYAML 与签名覆盖。"""

    def test_python_runtime_bundled_pruned_and_dereferenced(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        python_root = app / ctflab_app.PYTHON_RUNTIME_REL
        python_bin = python_root / "bin" / "python3"
        self.assertTrue(python_bin.is_file(), "内置解释器必须存在")
        self.assertTrue(os.access(python_bin, os.X_OK), "内置解释器必须可执行")
        self.assertEqual([p for p in python_root.rglob("*") if p.is_symlink()], [],
                         "app 内 Python 树不得残留符号链接")
        for pruned in ("bin/pip3", "lib/python3.12/tkinter", "include", "share",
                       "lib/libpython3.12.dylib"):
            self.assertFalse((python_root / pruned).exists(), f"应被裁剪：{pruned}")
        section = result["manifest"]["runtime"]["python"]
        self.assertEqual(section["version"], "3.12.14")
        self.assertEqual(section["symlinks_dereferenced"], 1)
        self.assertIn("bin/pip3", section["pruned"])
        self.assertIn("lib/libpython3.12.dylib", section["pruned"])

    def test_python_runtime_from_tarball(self) -> None:
        import tarfile

        archive = pathlib.Path(self.temp.name) / "cpython-3.12.14+20260901-aarch64-apple-darwin-install_only_stripped.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(self.fake_python, arcname="python")
        result = self.build(python_runtime=archive)
        app = pathlib.Path(result["app"])
        self.assertTrue((app / ctflab_app.PYTHON_RUNTIME_REL / "bin" / "python3").is_file())
        section = result["manifest"]["runtime"]["python"]
        self.assertEqual(section["source"], "python-build-standalone 20260901（cpython-3.12.14）")
        self.assertEqual(section["archive_sha256"], ctflab_app.sha256_file(archive))

    def test_python_runtime_sha256_mismatch_stops_build(self) -> None:
        import tarfile

        archive = pathlib.Path(self.temp.name) / "python-bad.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(self.fake_python, arcname="python")
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            self.build(python_runtime=archive, python_runtime_sha256="0" * 64)
        self.assertIn("SHA-256 不符", str(raised.exception))

    def test_missing_python_or_pyyaml_stops_build(self) -> None:
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            self.build(python_runtime=None)
        self.assertIn("--python-runtime", str(raised.exception))
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            self.build(pyyaml_source=None)
        self.assertIn("--pyyaml", str(raised.exception))

    def test_pyyaml_installed_into_site_packages(self) -> None:
        result = self.build()
        app = pathlib.Path(result["app"])
        site = app / "Contents/Resources/runtime/python/lib/python3.12/site-packages"
        self.assertTrue((site / "yaml" / "__init__.py").is_file())
        self.assertTrue((site / "_yaml" / "__init__.py").is_file())
        self.assertTrue((site / "yaml" / "_yaml.cpython-312-darwin.so").is_file(),
                        "PyYAML 的 C 扩展（系统库依赖）应随包并在签名覆盖内")
        self.assertTrue((app / ctflab_app.LICENSES_REL / "pyyaml" / "LICENSE").is_file())
        self.assertTrue((app / ctflab_app.LICENSES_REL / "python" / "LICENSE.txt").is_file())
        pyyaml = result["manifest"]["runtime"]["python"]["pyyaml"]
        self.assertEqual(pyyaml["version"], "6.0.3")
        self.assertEqual(pyyaml["package"],
                         "Contents/Resources/runtime/python/lib/python3.12/site-packages/yaml")

    def test_pyyaml_wheel_path_escape_is_rejected(self) -> None:
        import zipfile

        evil = pathlib.Path(self.temp.name) / "pyyaml-6.0.3-cp312-cp312-macosx_11_0_arm64.whl"
        with zipfile.ZipFile(evil, "w") as archive:
            archive.writestr("../escape.txt", "no")
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            self.build(pyyaml_source=evil)
        self.assertIn("越界", str(raised.exception))

    def test_python_tree_is_signed_when_signing_enabled(self) -> None:
        result = self.build(unsigned=False)
        app = pathlib.Path(result["app"])
        for rel in ("Contents/Resources/runtime/python/bin/python3.12",
                    "Contents/Resources/runtime/python/lib/python3.12/lib-dynload/"
                    "_example.cpython-312-darwin.so"):
            verify = subprocess.run(["codesign", "--verify", "--strict", str(app / rel)],
                                    capture_output=True, text=True)
            self.assertEqual(verify.returncode, 0, f"{rel}: {verify.stderr}")
        report = ctflab_app.verify_app(app)
        self.assertEqual(report["signature"]["level"], "ad-hoc")


class FormulaVersionTests(unittest.TestCase):
    """SBOM 的来源字段依赖 Cellar 版本解析；解析失败会静默降级成 `?`。"""

    def test_cellar_symlink_resolves_to_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            opt_root = pathlib.Path(temp) / "opt"
            keg = pathlib.Path(temp) / "Cellar" / "qemu" / "11.1.0"
            keg.mkdir(parents=True)
            opt_root.mkdir()
            (opt_root / "qemu").symlink_to(keg, target_is_directory=True)
            self.assertEqual(ctflab_app._formula_version("qemu", opt_root=opt_root), "11.1.0")

    def test_missing_or_unrelated_paths_return_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            opt_root = pathlib.Path(temp) / "opt"
            opt_root.mkdir()
            self.assertIsNone(ctflab_app._formula_version("qemu", opt_root=opt_root))
            outside = pathlib.Path(temp) / "elsewhere" / "qemu"
            outside.mkdir(parents=True)
            (opt_root / "qemu").symlink_to(outside, target_is_directory=True)
            self.assertIsNone(ctflab_app._formula_version("qemu", opt_root=opt_root))


class KaliE2EGuardTests(unittest.TestCase):
    """Task 6.3A 必须避免把 GRUB 当登录界面，也不能绕过来宾侧验收。"""

    def test_grub_menu_is_not_login_ready(self) -> None:
        text = "Kali GNU/Linux\nAdvanced options for Kali\nUEFI Firmware Settings\nBooting in 4 seconds"
        result = ctflab_app_kali_e2e.classify_kali_screen(text)
        self.assertEqual(result["classification"], "boot_progress")
        self.assertNotEqual(result["classification"], "login_ready")

    def test_lightdm_text_is_login_ready(self) -> None:
        result = ctflab_app_kali_e2e.classify_kali_screen(
            "KALI Linux\nUsername\nPassword\nLog In"
        )
        self.assertEqual(result["classification"], "login_ready")

    def test_measured_lightdm_ocr_degradation_is_login_ready(self) -> None:
        result = ctflab_app_kali_e2e.classify_kali_screen("Log!\nKALI")
        self.assertEqual(result["classification"], "login_ready")

    def test_kali_brand_alone_is_not_login_ready(self) -> None:
        result = ctflab_app_kali_e2e.classify_kali_screen("Kali GNU/Linux")
        self.assertNotEqual(result["classification"], "login_ready")

    def test_guest_password_is_stdin_only_for_poweroff(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            ssh = ctflab_app_kali_e2e.GuestSSH(pathlib.Path(temp), "secret")
            with mock.patch.object(ctflab_app_kali_e2e, "run", return_value={}) as mocked:
                ssh.command("sudo -S poweroff", input_text="secret\n")
            command = mocked.call_args.args[0]
            self.assertNotIn("secret", " ".join(command))
            self.assertEqual(mocked.call_args.kwargs["input_text"], "secret\n")
            self.assertEqual(mocked.call_args.kwargs["redact"], ["secret"])

    def test_missing_password_fails_before_app_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            app = root / "CTFLab.app"
            launcher = app / ctflab_app.LAUNCHER_REL
            launcher.parent.mkdir(parents=True)
            launcher.write_text("#!/bin/sh\n", encoding="utf-8")
            workdir = root / "evidence"
            with mock.patch.dict(os.environ, {"CTFLAB_KALI_PASSWORD": ""}, clear=False):
                result = ctflab_app_kali_e2e.main([
                    "--app", str(app), "--workdir", str(workdir),
                ])
            self.assertEqual(result, 1)
            evidence = json.loads((workdir / "kali-e2e-evidence.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["result"], "失败")
            self.assertEqual(evidence["steps"][0]["step"], "guest-password")


class RuntimeSelectionTests(unittest.TestCase):
    """运行时的选择规则：CTFLAB_RUNTIME_ROOT 与 .app 布局优先，PATH 仅作开发回退。"""

    def test_app_layout_derives_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            app = pathlib.Path(temp) / "CTFLab.app"
            (app / "Contents" / "Resources" / "runtime" / "bin").mkdir(parents=True)
            (app / "Contents" / "Resources" / "runtime" / "bin" / "qemu-img").write_text("x")
            os.chmod(app / "Contents" / "Resources" / "runtime" / "bin" / "qemu-img", 0o755)
            # 把真实模块复制进 .app 布局，才能验证 PROJECT_ROOT 推导出的 runtime 路径。
            fake_tools = app / "Contents" / "Resources" / "ctflab" / "tools"
            fake_tools.mkdir(parents=True)
            for name in ("ctflab.py", "ctflab_inspect.py", "ctflab_network.py",
                         "ctflab_utm.py", "ctflab_utm_fixture.json"):
                shutil.copy2(TOOLS_DIR / name, fake_tools / name)
            shutil.copytree(TOOLS_DIR / "ctflab_profiles", fake_tools / "ctflab_profiles")
            fake_module = fake_tools / "ctflab.py"
            code = (
                "import sys, pathlib;"
                f"sys.path.insert(0, {str(fake_module.parent)!r});"
                "import ctflab;"
                "print(ctflab.runtime_root());"
                "print(ctflab.resolve_tool('qemu-img'))"
            )
            result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                    env={**os.environ, "CTFLAB_RUNTIME_ROOT": ""})
            lines = result.stdout.strip().splitlines()
            expected_runtime = (app / "Contents" / "Resources" / "runtime").resolve()
            self.assertEqual(lines[0], str(expected_runtime))
            self.assertEqual(lines[1], str(expected_runtime / "bin" / "qemu-img"))

    def test_env_override_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp) / "runtime"
            (root / "bin").mkdir(parents=True)
            (root / "bin" / "qemu-img").write_text("x")
            os.chmod(root / "bin" / "qemu-img", 0o755)
            result = subprocess.run(
                [sys.executable, "-c",
                 "import sys; sys.path.insert(0, %r); import ctflab; print(ctflab.runtime_root());"
                 "print(ctflab.resolve_tool('qemu-img'))" % str(TOOLS_DIR)],
                capture_output=True, text=True,
                env={**os.environ, "CTFLAB_RUNTIME_ROOT": str(root)})
            lines = result.stdout.strip().splitlines()
            self.assertEqual(lines[0], str(root))
            self.assertEqual(lines[1], str(root / "bin" / "qemu-img"))

    def test_no_runtime_falls_back_to_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bin_dir = pathlib.Path(temp) / "bin"
            bin_dir.mkdir()
            (bin_dir / "qemu-img").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            os.chmod(bin_dir / "qemu-img", 0o755)
            result = subprocess.run(
                [sys.executable, "-c",
                 "import sys; sys.path.insert(0, %r); import ctflab; print(ctflab.runtime_root());"
                 "print(ctflab.resolve_tool('qemu-img'))" % str(TOOLS_DIR)],
                capture_output=True, text=True,
                env={**os.environ, "CTFLAB_RUNTIME_ROOT": "", "PATH": f"{bin_dir}:/usr/bin:/bin"})
            lines = result.stdout.strip().splitlines()
            self.assertEqual(lines[0], "None")
            self.assertEqual(lines[1], str(bin_dir / "qemu-img"))

    def test_active_runtime_missing_tool_does_not_fall_back_to_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = pathlib.Path(temp)
            runtime = base / "runtime"
            host_bin = base / "host-bin"
            (runtime / "bin").mkdir(parents=True)
            host_bin.mkdir()
            host_tool = host_bin / "qemu-img"
            host_tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            host_tool.chmod(0o755)
            result = subprocess.run(
                [sys.executable, "-c",
                 "import sys; sys.path.insert(0, %r); import ctflab; "
                 "print(ctflab.resolve_tool('qemu-img'))" % str(TOOLS_DIR)],
                capture_output=True, text=True,
                env={**os.environ, "CTFLAB_RUNTIME_ROOT": str(runtime),
                     "PATH": f"{host_bin}:/usr/bin:/bin"},
            )
            self.assertEqual(result.stdout.strip(), "None")


class CliSurfaceTests(unittest.TestCase):
    def test_app_subcommands_exist_and_baseline_commands_remain(self) -> None:
        parser = ctflab.build_parser()
        subcommands: dict[str, object] = {}
        for action in parser._subparsers._group_actions:
            subcommands.update(action.choices)
        for name in ("doctor", "import", "run", "stop", "reset", "package", "content", "app"):
            self.assertIn(name, subcommands)
        app_choices = {}
        for action in subcommands["app"]._subparsers._group_actions:  # type: ignore[attr-defined]
            app_choices.update(action.choices)
        self.assertEqual(set(app_choices), {"build", "verify"})

    def test_source_release_contains_app_module_used_by_cli(self) -> None:
        self.assertIn("tools/ctflab_app.py", ctflab_package.RELEASE_TOOL_FILES)
        with tempfile.TemporaryDirectory() as temp:
            result = ctflab_package.build_release_bundle(
                pathlib.Path(temp), source_root=PROJECT_ROOT,
                generated_at="2026-09-15T00:00:00Z",
            )
            paths = {entry["path"] for entry in result["manifest"]["files"]}
            self.assertIn("tools/ctflab_app.py", paths)
            ctflab_package.verify_release_bundle(pathlib.Path(result["bundle"]))


if __name__ == "__main__":
    unittest.main()
