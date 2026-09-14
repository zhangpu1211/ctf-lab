#!/usr/bin/env python3
"""Ghidra 帮助修复脚本的回归测试：模拟 JAR、幂等性、失败回滚。"""

from __future__ import annotations

import hashlib
import io
from contextlib import redirect_stdout
import pathlib
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))
sys.path.insert(0, str(TOOLS_DIR / "guest_fixes" / "kali-arm64"))

import ghidra_help_fix as fix  # noqa: E402

HELPSET_BROKEN = """<?xml version='1.0' encoding='ISO-8859-1' ?>
<helpset version="2.0">
\t<title>Demo HelpSet</title>
\t<maps>
\t\t<mapref location="Demo_map.xml" />
\t</maps>
\t<view mergetype="javax.help.UniteAppendMerge">
\t\t<name>TOC</name>
\t\t<label>Ghidra Table of Contents</label>
\t\t<type>help.CustomTOCView</type>
\t\t<data>Demo_TOC.xml</data>
\t</view>
\t<view>
\t\t<name>Search</name>
\t\t<label>Search for Keywords</label>
\t\t<type>help.CustomSearchView</type>
\t</view>
\t<view>
\t\t<name>Favorites</name>
\t\t<label>Ghidra Favorites</label>
\t\t<type>help.CustomFavoritesView</type>
\t</view>
</helpset>
"""

HELPSET_FIXED = HELPSET_BROKEN.replace(
    "\t\t<type>help.CustomSearchView</type>\n",
    "\t\t<type>help.CustomSearchView</type>\n"
    '\t\t<data engine="com.sun.java.help.search.DefaultSearchEngine">Demo_JavaHelpSearch</data>\n',
)


def fake_indexer(java, javahelp_jar, database, relative_files, cwd):
    """模拟 JavaHelp 索引器：写出六个索引文件。"""
    assert relative_files, "索引器必须收到主题文件"
    for name in fix.INDEX_FILES:
        (database / name).write_bytes(f"{name}:{len(relative_files)}".encode())


class HelpFixTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "ghidra"
        self.backup = pathlib.Path(self._tmp.name) / "backup"
        self.lib = self.root / "Ghidra" / "Features" / "Demo" / "lib"
        self.lib.mkdir(parents=True)
        self.javahelp = self.root / "Ghidra" / "Framework" / "Help" / "lib" / "javahelp-2.0.05.jar"
        self.javahelp.parent.mkdir(parents=True)
        with zipfile.ZipFile(self.javahelp, "w") as archive:
            archive.writestr("placeholder.txt", "javahelp")

        self.jar = self.lib / "Demo.jar"
        with zipfile.ZipFile(self.jar, "w") as archive:
            archive.writestr("help/Demo_HelpSet.hs", HELPSET_BROKEN)
            archive.writestr("help/Demo_TOC.xml", "<toc/>")
            archive.writestr("help/Demo_map.xml", "<map/>")
            archive.writestr("help/topics/Demo/Demo.htm", "<html>demo</html>")
            archive.writestr("help/topics/Demo/Other.html", "<html>other</html>")
            archive.writestr("help/Demo_JavaHelpSearch/", "")
            archive.writestr("demo/Code.class", b"\xca\xfe\xba\xbe")

        # 已带 data 的 helpset：应被跳过
        self.fixed_jar = self.lib / "Fixed.jar"
        with zipfile.ZipFile(self.fixed_jar, "w") as archive:
            archive.writestr("help/Fixed_HelpSet.hs", HELPSET_FIXED.replace("Demo_", "Fixed_"))
            archive.writestr("help/topics/Fixed/Fixed.htm", "<html>fixed</html>")

        # 没有 helpset 的 JAR：应被忽略
        self.other_jar = self.lib / "Other.jar"
        with zipfile.ZipFile(self.other_jar, "w") as archive:
            archive.writestr("other/Thing.class", b"\xca\xfe\xba\xbe")

    def make_multi_jar(self) -> pathlib.Path:
        """同一个 JAR 内两个待修复 helpset，用于验证“一次构建、失败不改动”。"""
        jar = self.lib / "Multi.jar"
        with zipfile.ZipFile(jar, "w") as archive:
            for module in ("Alpha", "Beta"):
                archive.writestr(
                    f"help/{module}_HelpSet.hs",
                    HELPSET_BROKEN.replace("Demo_", f"{module}_"),
                )
                archive.writestr(f"help/topics/{module}/{module}.htm", f"<html>{module}</html>")
                archive.writestr(f"help/{module}_JavaHelpSearch/", "")
        return jar

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def digest(self, path: pathlib.Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def leftovers(self) -> list[str]:
        return [p.name for p in self.lib.iterdir() if ".ctflab-" in p.name]

    def run_fix(self, *, indexer=fake_indexer) -> dict:
        return fix.fix_tree(self.root, self.javahelp, self.backup, java="/usr/bin/java",
                            indexer=indexer, log=lambda *_: None)

    def test_patches_helpset_and_adds_index_files(self) -> None:
        result = self.run_fix()
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["patched"], [self.jar])
        self.assertEqual(result["skipped"], [self.fixed_jar])  # 没有 helpset 的 JAR 直接忽略
        with zipfile.ZipFile(self.jar) as archive:
            self.assertIsNone(archive.testzip())
            text = archive.read("help/Demo_HelpSet.hs").decode("iso-8859-1")
            self.assertIn(
                '<data engine="com.sun.java.help.search.DefaultSearchEngine">Demo_JavaHelpSearch</data>',
                text,
            )
            names = set(archive.namelist())
            for name in fix.INDEX_FILES:
                self.assertIn(f"help/Demo_JavaHelpSearch/{name}", names)
            # 其他条目必须原样保留
            self.assertEqual(archive.read("help/topics/Demo/Demo.htm"), b"<html>demo</html>")
            self.assertEqual(archive.read("demo/Code.class"), b"\xca\xfe\xba\xbe")
            self.assertEqual(archive.read("help/Demo_TOC.xml"), b"<toc/>")
        self.assertEqual(self.leftovers(), [])
        backup = fix.backup_path(self.backup, self.jar, "help/Demo_HelpSet.hs")
        self.assertTrue(backup.is_file())
        self.assertIn("<name>Search</name>", backup.read_text(encoding="iso-8859-1"))
        # 未涉及的 JAR 不应被改写
        self.assertEqual(self.digest(self.fixed_jar), self.digest(self.fixed_jar))

    def test_second_run_is_idempotent(self) -> None:
        self.run_fix()
        first = self.digest(self.jar)
        result = self.run_fix()
        self.assertEqual(result["patched"], [])
        self.assertEqual(self.digest(self.jar), first)
        self.assertEqual(self.leftovers(), [])

    def test_indexer_failure_leaves_jar_untouched(self) -> None:
        before = self.digest(self.jar)
        original = self.jar.read_bytes()

        def broken_indexer(*args, **kwargs):
            raise fix.FixError("模拟索引器失败")

        result = self.run_fix(indexer=broken_indexer)
        self.assertEqual(result["patched"], [])
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(self.digest(self.jar), before)
        self.assertEqual(self.jar.read_bytes(), original)
        with zipfile.ZipFile(self.jar) as archive:
            self.assertIsNone(archive.testzip())
        self.assertEqual(self.leftovers(), [])

    def test_install_failure_keeps_jar_and_cleans_temp_file(self) -> None:
        before = self.digest(self.jar)
        with mock.patch.object(fix.os, "replace", side_effect=OSError("模拟替换失败")):
            result = self.run_fix()
        self.assertEqual(result["patched"], [])
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(self.digest(self.jar), before)
        with zipfile.ZipFile(self.jar) as archive:
            self.assertIsNone(archive.testzip())
        self.assertEqual(self.leftovers(), [])

    def test_missing_index_files_is_a_failure(self) -> None:
        def incomplete_indexer(java, javahelp_jar, database, relative_files, cwd):
            (database / "DOCS").write_bytes(b"only-one-file")

        result = self.run_fix(indexer=incomplete_indexer)
        self.assertEqual(result["patched"], [])
        self.assertEqual(len(result["failed"]), 1)
        self.assertEqual(self.leftovers(), [])
        with zipfile.ZipFile(self.jar) as archive:
            text = archive.read("help/Demo_HelpSet.hs").decode("iso-8859-1")
        self.assertTrue(fix.search_view_needs_data(text))

    def test_two_helpsets_in_one_jar_are_fixed_in_one_replacement(self) -> None:
        multi_jar = self.make_multi_jar()
        result = self.run_fix()
        self.assertEqual(result["failed"], [])
        self.assertIn(multi_jar, result["patched"])
        with zipfile.ZipFile(multi_jar) as archive:
            self.assertIsNone(archive.testzip())
            names = set(archive.namelist())
            for module in ("Alpha", "Beta"):
                text = archive.read(f"help/{module}_HelpSet.hs").decode("iso-8859-1")
                self.assertIn(f">{module}_JavaHelpSearch</data>", text)
                for name in fix.INDEX_FILES:
                    self.assertIn(f"help/{module}_JavaHelpSearch/{name}", names)
        self.assertEqual(self.leftovers(), [])

    def test_second_helpset_failure_leaves_jar_untouched(self) -> None:
        # 只保留 Multi.jar，断言“两个 helpset 都被尝试过”不会被其他 JAR 干扰
        self.jar.unlink()
        multi_jar = self.make_multi_jar()
        before = multi_jar.read_bytes()
        calls: list[str] = []

        def failing_indexer(java, javahelp_jar, database, relative_files, cwd):
            calls.append(database.name)
            if "Beta" in database.name:
                raise fix.FixError("模拟 Beta 索引失败")
            for name in fix.INDEX_FILES:
                (database / name).write_bytes(b"index")

        result = self.run_fix(indexer=failing_indexer)
        self.assertEqual(len(calls), 2, f"应尝试两个 helpset：{calls}")
        self.assertEqual(result["patched"], [])
        failed = {str(jar): message for jar, message in result["failed"]}
        self.assertIn(str(multi_jar), failed)
        # 关键断言：第一个 helpset 不能被部分写入
        self.assertEqual(multi_jar.read_bytes(), before)
        with zipfile.ZipFile(multi_jar) as archive:
            self.assertIsNone(archive.testzip())
            for module in ("Alpha", "Beta"):
                text = archive.read(f"help/{module}_HelpSet.hs").decode("iso-8859-1")
                self.assertTrue(fix.search_view_needs_data(text), module)
                for name in fix.INDEX_FILES:
                    self.assertNotIn(f"help/{module}_JavaHelpSearch/{name}", archive.namelist())
        self.assertEqual(self.leftovers(), [])

    def test_patch_helpset_text_rejects_unexpected_input(self) -> None:
        with self.assertRaises(fix.FixError):
            fix.patch_helpset_text("<helpset><view><name>TOC</name></view></helpset>", "Demo_JavaHelpSearch")
        with self.assertRaises(fix.FixError):
            fix.patch_helpset_text(HELPSET_FIXED, "Demo_JavaHelpSearch")

    def test_main_requires_root_and_reports_remaining(self) -> None:
        with mock.patch.object(fix.os, "geteuid", return_value=1000):
            self.assertEqual(fix.main(["--root", str(self.root), "--backup-dir", str(self.backup)]), 1)
        output = io.StringIO()
        with mock.patch.object(fix.os, "geteuid", return_value=0), \
                mock.patch.object(fix, "run_indexer", fake_indexer), \
                redirect_stdout(output):
            code = fix.main(["--root", str(self.root), "--backup-dir", str(self.backup),
                             "--java", "/usr/bin/java"])
        self.assertEqual(code, 0)
        self.assertIn("修复 1 个 JAR", output.getvalue())
        with zipfile.ZipFile(self.jar) as archive:
            self.assertIn("Demo_JavaHelpSearch", archive.read("help/Demo_HelpSet.hs").decode("iso-8859-1"))


if __name__ == "__main__":
    unittest.main()
