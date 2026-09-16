#!/usr/bin/env python3
"""CTFLab 图形入口（Task 6.4）测试。

三层：

1. Swift 核心逻辑测试：`gui/GuiCoreTests.swift` 用 swiftc 编译后直接运行（无 XCTest 依赖，
   也不需要图形会话）；缺 swiftc 时跳过并说明。
2. CLI 机器可读输出：GUI 只通过 `--json` 读取 `dist verify` / `status` / `health` 的结果，
   这里覆盖成功与三类失败（缺失、大小不符、哈希不符）。
3. app 构建集成：用真实 `gui/` 源码编译一次，校验 GUI 入口、CLI 启动器、Info.plist 与
   MANIFEST.gui 记录，并跑完整 `verify_app`。
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1]
TESTS_DIR = pathlib.Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))
sys.path.insert(0, str(TESTS_DIR))  # 复用 test_ctflab_app 的假运行时夹具

import ctflab  # noqa: E402
import ctflab_app  # noqa: E402
import ctflab_dist  # noqa: E402

SWIFTC = shutil.which("swiftc")
GUI_DIR = PROJECT_ROOT / "gui"


class CliJsonContractTests(unittest.TestCase):
    """GUI 依赖的 CLI JSON 契约（字段名变化会直接打断图形入口）。"""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.temp.name) / "dist with space"
        self.dir.mkdir(parents=True)
        self.payload = self.dir / "smoke-base.qcow2"
        self.payload.write_bytes(b"payload-bytes")
        manifest = {
            "schema": 1,
            "format": ctflab_dist.DISTRIBUTION_FORMAT,
            "entries": [{
                "file": self.payload.name,
                "profile": "smoke",
                "role": ctflab_dist.BASE_ROLE,
                "size": self.payload.stat().st_size,
                "sha256": ctflab_dist.sha256_file(self.payload),
            }],
        }
        (self.dir / ctflab_dist.MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_verify_reports_ok_with_size_and_status(self) -> None:
        report = ctflab_dist.verify_distribution(self.dir)
        self.assertTrue(report["ok"])
        entry = report["entries"][0]
        self.assertEqual(entry["status"], "ok")
        self.assertEqual(entry["size"], self.payload.stat().st_size)
        self.assertIsNone(entry["problem"])
        self.assertEqual(report["summary"], {"total": 1, "ok": 1, "failed": 0})
        self.assertIn("dir", report)

    def test_verify_reports_missing_file(self) -> None:
        self.payload.unlink()
        report = ctflab_dist.verify_distribution(self.dir)
        self.assertFalse(report["ok"])
        self.assertEqual(report["entries"][0]["status"], "missing")
        self.assertIn("缺失", report["entries"][0]["problem"])

    def test_verify_reports_size_mismatch(self) -> None:
        """改长度会同时触发大小与哈希不一致：两条都要上报，行状态取更严重的一类。"""
        self.payload.write_bytes(b"longer-payload-bytes")
        report = ctflab_dist.verify_distribution(self.dir)
        self.assertFalse(report["ok"])
        problems = "；".join(report["problems"])
        self.assertIn("大小不一致", problems)
        self.assertIn("SHA-256 不一致", problems)
        self.assertEqual(report["entries"][0]["status"], "sha256-mismatch",
                         "行状态取更严重的一类（哈希优先于大小）")
        self.assertEqual(report["summary"]["failed"], len(report["problems"]))

    def test_verify_reports_hash_mismatch(self) -> None:
        original = self.payload.read_bytes()
        self.payload.write_bytes(b"X" * len(original))
        report = ctflab_dist.verify_distribution(self.dir)
        self.assertFalse(report["ok"])
        self.assertEqual(report["entries"][0]["status"], "sha256-mismatch")
        self.assertIn("SHA-256", report["entries"][0]["problem"])

    def test_cli_json_flags_are_wired(self) -> None:
        parser = ctflab.build_parser()
        subcommands: dict[str, object] = {}
        for action in parser._subparsers._group_actions:
            subcommands.update(action.choices)
        status_options = {option for action in subcommands["status"]._actions  # type: ignore[attr-defined]
                          for option in action.option_strings}
        self.assertIn("--json", status_options)
        health_options = {option for action in subcommands["health"]._actions  # type: ignore[attr-defined]
                          for option in action.option_strings}
        self.assertIn("--json", health_options)
        dist_choices = {}
        for action in subcommands["dist"]._subparsers._group_actions:  # type: ignore[attr-defined]
            dist_choices.update(action.choices)
        verify_options = {option for action in dist_choices["verify"]._actions
                          for option in action.option_strings}
        self.assertIn("--json", verify_options)

    def test_import_requires_source_positional_that_gui_supplies(self) -> None:
        """契约：CLI 的 import 需要位置参数 source；GUI 必须从清单解析基盘文件并传入。

        这一条对应实机验证中发现过的缺陷（GUI 曾漏传 source，CLI 直接报用法错误）。
        """
        parser = ctflab.build_parser()
        subcommands: dict[str, object] = {}
        for action in parser._subparsers._group_actions:
            subcommands.update(action.choices)
        with self.assertRaises(SystemExit):
            parser.parse_args(["import", "smoke", "--manifest", "/tmp/DISTRIBUTION.json"])
        parsed = parser.parse_args(["import", "smoke", "smoke-base.qcow2",
                                    "--manifest", "/tmp/DISTRIBUTION.json"])
        self.assertEqual(parsed.source, "smoke-base.qcow2")
        self.assertEqual(str(parsed.manifest), "/tmp/DISTRIBUTION.json")
        source = (GUI_DIR / "GuiCore.swift").read_text(encoding="utf-8")
        self.assertIn('args += ["import", node.rawValue, sourcePath, "--manifest", manifestPath]',
                      source)

    def test_gui_resolves_base_path_from_manifest(self) -> None:
        """GUI 从 DISTRIBUTION.json 的 profile+role=base 条目解析基盘文件。"""
        source = (GUI_DIR / "GuiCore.swift").read_text(encoding="utf-8")
        self.assertIn("func basePath(for node: LabNode)", source)
        self.assertIn('entry["role"] as? String) == "base"', source)
        app = (GUI_DIR / "GuiApp.swift").read_text(encoding="utf-8")
        self.assertIn("layout.basePath(for: node)", app)

    def test_status_json_shape_covers_all_local_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            manager = ctflab.LabManager(pathlib.Path(state_dir))
            report = ctflab._status_report(manager)
        ids = {profile["id"] for profile in report["profiles"]}
        self.assertLessEqual({"kali-arm64", "smoke", "basic-pentesting-2"}, ids)
        for profile in report["profiles"]:
            for key in ("imported", "running", "log_path", "base_sha256"):
                self.assertIn(key, profile)
            self.assertIsInstance(profile["imported"], bool)

    def test_dist_verify_json_failure_still_prints_json(self) -> None:
        """GUI 解析 JSON；失败时也必须打印 JSON 并以退出码 1 表示失败。"""
        self.payload.unlink()
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "ctflab.py"), "dist", "verify",
             "--dir", str(self.dir), "--json"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertFalse(report["ok"])
        self.assertEqual(report["entries"][0]["status"], "missing")


class ResetSemanticsTests(unittest.TestCase):
    """GUI 的重置门禁必须映射到 CLI 的真实能力（逐节点 reset，无批量捷径）。"""

    def test_reset_accepts_single_profile_only(self) -> None:
        parser = ctflab.build_parser()
        subcommands: dict[str, object] = {}
        for action in parser._subparsers._group_actions:
            subcommands.update(action.choices)
        reset = subcommands["reset"]
        positional = [action for action in reset._actions  # type: ignore[attr-defined]
                      if not action.option_strings]
        self.assertEqual(len(positional), 1)
        self.assertIsNone(positional[0].nargs, "reset 每次只接受一个 profile（GUI 逐个执行）")

    def test_gui_cli_path_matches_app_layout_constant(self) -> None:
        """GUI 里的 CLI 相对路径必须与打包常量一致，否则双击后调不到 CLI。"""
        source = (GUI_DIR / "GuiCore.swift").read_text(encoding="utf-8")
        self.assertIn(ctflab_app.LAUNCHER_REL, source,
                      f"GUI 必须引用 {ctflab_app.LAUNCHER_REL}（ctflab_app.LAUNCHER_REL）")

    def test_gui_exposes_selected_node_start_and_default_policy(self) -> None:
        """GUI 把启动节点选择交给用户，Kali 的联网与自动分辨率由 CLI 默认策略负责。"""
        source = (GUI_DIR / "GuiCore.swift").read_text(encoding="utf-8")
        app = (GUI_DIR / "GuiApp.swift").read_text(encoding="utf-8")
        self.assertIn("case run(nodes: [LabNode])", source)
        self.assertIn("canStartSelected", source)
        self.assertIn("启动所选节点", app)
        self.assertIn("selectedNodes", app)
        self.assertNotIn("Kali 联网维护", app)
        self.assertNotIn("动态分辨率…", app)


@unittest.skipUnless(SWIFTC, "需要 swiftc（Xcode 命令行工具）编译 GUI 核心")
class SwiftCoreTests(unittest.TestCase):
    """Swift 核心状态机/命令拼接/解析的单元测试（编译后直接运行）。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        binary = pathlib.Path(cls._temp.name) / "gui-core-tests"
        cls._swift_cache = tempfile.TemporaryDirectory(prefix="ctflab-swift-test-cache-")
        swift_env = dict(os.environ)
        swift_env["CLANG_MODULE_CACHE_PATH"] = cls._swift_cache.name
        result = subprocess.run(
            [SWIFTC, "-O", "-target", ctflab_app.GUI_TARGET,
             "-o", str(binary),
             str(GUI_DIR / "GuiCore.swift"), str(GUI_DIR / "GuiCoreTests.swift")],
            capture_output=True, text=True, env=swift_env)
        cls._compile = result
        cls._binary = binary if result.returncode == 0 else None

    @classmethod
    def tearDownClass(cls) -> None:
        cls._swift_cache.cleanup()
        cls._temp.cleanup()

    def test_swift_core_compiles_and_all_checks_pass(self) -> None:
        self.assertIsNotNone(self._binary,
                             f"GUI 核心编译失败：{self._compile.stderr[:400]}")
        result = subprocess.run([str(self._binary)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0,
                         f"Swift 核心检查失败：\n{result.stdout[-1500:]}")
        self.assertIn("失败 0 项", result.stdout)
        self.assertGreaterEqual(result.stdout.count("ok   "), 40)


class GuiSourceGuardTests(unittest.TestCase):
    def test_gui_uses_existing_cli_entrypoints_only(self) -> None:
        """GUI 只能调用既有 CLI 子命令，不得自带导入/QEMU 参数逻辑。"""
        source = (GUI_DIR / "GuiCore.swift").read_text(encoding="utf-8")
        for needle in ('"dist", "verify"', '"import"', '"--manifest"', '"run"', '"status"',
                       '"health"', '"stop", "--all"', '"reset"'):
            self.assertIn(needle, source, f"缺少 CLI 能力引用：{needle}")
        for forbidden in ("-m ", "qemu-system", "-drive", "overlay.qcow2"):
            self.assertNotIn(forbidden, source, f"GUI 不得直接构造 QEMU 参数：{forbidden}")

    def test_gui_has_no_external_runtime_dependency(self) -> None:
        """只允许系统框架（Foundation/AppKit/SwiftUI）；不得引入 Electron/Node/浏览器内核。"""
        allowed = {"Foundation", "AppKit", "SwiftUI"}
        for name in ("GuiCore.swift", "GuiApp.swift", "GuiCoreTests.swift"):
            source = (GUI_DIR / name).read_text(encoding="utf-8")
            imports = {line.split()[1].split(".")[0]
                       for line in source.splitlines()
                       if line.startswith("import ")}
            self.assertTrue(imports <= allowed,
                            f"{name} 引入了非系统依赖：{sorted(imports - allowed)}")
            for forbidden in ("Electron", "WKWebView", "WebKit", "require("):
                self.assertNotIn(forbidden, source, f"{name} 不得引入 {forbidden}")


@unittest.skipUnless(SWIFTC, "需要 swiftc（Xcode 命令行工具）编译 GUI 入口")
@unittest.skipUnless(shutil.which("clang"), "需要 clang 构造最小 QEMU 替身")
class GuiAppBuildTests(unittest.TestCase):
    """真实 gui/ 源码参与的一次 app 构建：入口、Info.plist、MANIFEST 与 verify_app。"""

    @classmethod
    def setUpClass(cls) -> None:
        from test_ctflab_app import AppTestCase  # noqa: PLC0415 复用既有假运行时夹具

        cls._base = AppTestCase
        AppTestCase.setUpClass()
        cls._harness = AppTestCase("build")  # 借用夹具的 build() 辅助方法与临时目录
        cls._harness.setUp()
        # 真实 GUI 源码：把仓库 gui/ 复制进假源码树，走 swiftc 真实编译路径（每个类只编译一次）。
        target = cls._harness.source_root / ctflab_app.GUI_SOURCE_DIR
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(GUI_DIR, target)
        cls._result = cls._harness.build(gui_binary=None)
        cls._app = pathlib.Path(cls._result["app"])

    @classmethod
    def tearDownClass(cls) -> None:
        cls._harness.tearDown()
        cls._base.tearDownClass()

    def copy_app(self) -> pathlib.Path:
        """需要改动 app 的用例各用一份副本，避免互相影响。"""
        target = pathlib.Path(self._harness.temp.name) / f"copy-{uuid.uuid4().hex[:8]}.app"
        shutil.copytree(self._app, target, symlinks=True)
        return target

    def test_app_builds_with_native_gui_entry(self) -> None:
        result = self._result
        app = self._app
        gui = app / "Contents/MacOS" / ctflab_app.GUI_EXECUTABLE
        self.assertTrue(gui.is_file(), "缺少 GUI 可执行文件")
        self.assertTrue(bool(gui.stat().st_mode & 0o111), "GUI 可执行文件没有执行位")
        # 主可执行文件是原生入口；CLI 启动器保留在 Resources/bin 并可直接调用。
        self.assertTrue((app / ctflab_app.LAUNCHER_REL).is_file())
        self.assertTrue((app / ctflab_app.LAUNCHER_COMPAT_REL).is_file())
        gui_record = result["manifest"]["gui"]
        self.assertEqual(gui_record["executable"], f"Contents/MacOS/{ctflab_app.GUI_EXECUTABLE}")
        self.assertEqual(gui_record["cli"], ctflab_app.LAUNCHER_REL)
        self.assertEqual(gui_record["source"], "swiftc")
        self.assertIn("swift_version", gui_record)
        self.assertIn("gui/GuiApp.swift", gui_record["sources"])
        self.assertNotIn("gui/GuiCoreTests.swift", gui_record["sources"],
                         "测试文件不得编进 app")
        # GUI 源码随包镜像（可审计）
        self.assertTrue((app / "Contents/Resources/ctflab/gui/GuiCore.swift").is_file())
        self.assertTrue((app / "Contents/Resources/ctflab/gui/GuiCoreTests.swift").is_file())
        # 主可执行文件不在清单里（由代码签名覆盖），但其余文件必须一致
        self.assertNotIn(f"Contents/MacOS/{ctflab_app.GUI_EXECUTABLE}",
                         [entry["path"] for entry in result["manifest"]["files"]])
        self.assertEqual(result["manifest"]["signature_covers"],
                         [f"Contents/MacOS/{ctflab_app.GUI_EXECUTABLE}"])
        report = ctflab_app.verify_app(app, check_signature=False)
        self.assertEqual(report["version"], "0.1.0")

    def test_verify_app_rejects_missing_gui_entry(self) -> None:
        app = self.copy_app()
        (app / "Contents/MacOS" / ctflab_app.GUI_EXECUTABLE).unlink()
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            ctflab_app.verify_app(app, check_signature=False)
        self.assertIn(ctflab_app.GUI_EXECUTABLE, str(raised.exception))

    def test_verify_app_rejects_manifest_without_gui_record(self) -> None:
        app = self.copy_app()
        manifest_path = app / ctflab_app.MANIFEST_REL
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.pop("gui")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        # 清单自身哈希不在清单内，改写后仍需保证 MANIFEST.json 被接受：verify 会重新读取。
        with self.assertRaises(ctflab_app.AppBuildError) as raised:
            ctflab_app.verify_app(app, check_signature=False)
        self.assertIn("MANIFEST.gui", str(raised.exception))


class GuiDocsGuardTests(unittest.TestCase):
    """图形入口文档：必须写明学生可双击完成导入启动、CLI 仍保留、以及未验证项。"""

    RECORD = PROJECT_ROOT / "docs" / "verification-gui-2026-09-16.md"
    TUTORIAL = PROJECT_ROOT / "docs" / "ctflab-student-distribution-tutorial.md"
    README = PROJECT_ROOT / "README.md"

    def test_record_distinguishes_clicked_and_unit_only(self) -> None:
        text = self.RECORD.read_text(encoding="utf-8")
        self.assertIn("实际点击验证", text)
        self.assertIn("仅单元测试覆盖", text)
        self.assertIn("未验证", text)
        self.assertIn("开发者 ID", text.replace("Developer ID", "开发者 ID"))
        self.assertIn("公证", text)
        self.assertIn("签名/公证流水线", text)

    def test_tutorial_leads_with_gui_and_keeps_cli(self) -> None:
        text = self.TUTORIAL.read_text(encoding="utf-8")
        gui_section = text.index("## 2. 图形界面流程")
        cli_section = text.index("## 3. 命令行流程")
        self.assertLess(gui_section, cli_section, "图形流程必须排在命令行之前")
        for needle in ("双击", "校验分发目录", "导入实验环境", "启动所选节点", "检查状态", "重置"):
            self.assertIn(needle, text)
        self.assertIn("Contents/Resources/bin/CTFLab", text)

    def test_readme_mentions_gui_entry_and_cli_kept(self) -> None:
        text = self.README.read_text(encoding="utf-8")
        self.assertIn("## 图形入口", text)
        self.assertIn("CTFLab.app/Contents/Resources/bin/ctflab-cli", text)
        self.assertIn("默认联网", text)


if __name__ == "__main__":
    unittest.main()
