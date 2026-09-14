#!/usr/bin/env python3
"""修复 Kali 发行包中 Ghidra 帮助窗口的 JavaHelp "view is invalid" 异常。

背景：Kali 的 ghidra 包（12.1.2+ds）只保留了空的 JavaHelp 搜索索引目录
（help/<Module>_JavaHelpSearch/），没有索引文件，但每个 helpset 仍然写入了
Search 视图且不带 <data> 元素。JavaHelp 创建帮助窗口时，
MergingSearchEngine.makeEngine() 对缺少 data 参数的视图返回 null，merge()
随即抛出 IllegalArgumentException: view is invalid；表现是首次 What's New
或打开帮助页时弹出 "Uncaught Exception" 错误对话框，随后
docking.help.HelpViewSearcher 也找不到搜索导航器。

处理：用 Ghidra 自带 javahelp-2.0.05.jar 里的 com.sun.java.help.search.Indexer
为每个模块的 help/topics 生成搜索索引，写入已有的 help/<Module>_JavaHelpSearch/
目录，并给对应的 Search 视图补上 JavaHelpSetBuilder 期望的
<data engine="com.sun.java.help.search.DefaultSearchEngine"> 元素。

写入方式：所有改动先在临时文件里构建成完整 JAR，校验通过后再用 os.replace
原子替换原文件；任何一步失败都只删除临时文件，原 JAR 保持原样，不会留下
半修复的 JAR。原始 helpset 备份到 /var/tmp/ctflab-ghidra-backup/，脚本可重复
执行（已带 data 的 helpset 会跳过）。不依赖外部 zip 命令。

用法：sudo python3 ghidra_help_fix.py [--root /usr/share/ghidra]
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT_DEFAULT = pathlib.Path("/usr/share/ghidra")
BACKUP_DEFAULT = pathlib.Path("/var/tmp/ctflab-ghidra-backup")
JAVAHELP_RELATIVE = pathlib.Path("Ghidra/Framework/Help/lib/javahelp-2.0.05.jar")
INDEX_FILES = ("DOCS", "DOCS.TAB", "OFFSETS", "POSITIONS", "SCHEMA", "TMAP")
SEARCH_VIEW = re.compile(r"<view>\s*<name>Search</name>.*?</view>", re.S)
DATA_ELEMENT = '\t\t<data engine="com.sun.java.help.search.DefaultSearchEngine">%s</data>\n'
JAVA_CANDIDATES = (
    "/usr/lib/jvm/java-21-openjdk-arm64/bin/java",
    "/usr/lib/jvm/default-java/bin/java",
)


class FixError(RuntimeError):
    """可理解的修复失败。"""


def find_java() -> str:
    for candidate in JAVA_CANDIDATES:
        if pathlib.Path(candidate).is_file():
            return candidate
    java = shutil.which("java")
    if not java:
        raise FixError("未找到 java，无法运行 JavaHelp 索引器。")
    return java


def run_indexer(java: str, javahelp_jar: pathlib.Path, database: pathlib.Path,
                relative_files: list[str], cwd: pathlib.Path) -> None:
    """用 Ghidra 自带索引器生成 DOCS/DOCS.TAB/... 六个文件。

    独立成函数便于测试注入；失败时抛 FixError，调用方不会改动 JAR。
    """
    try:
        subprocess.run(
            [java, "-cp", str(javahelp_jar), "com.sun.java.help.search.Indexer",
             "-db", str(database), "-nostopwords", *relative_files],
            cwd=cwd, check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise FixError(f"JavaHelp 索引器失败：{detail.strip()[:400]}") from exc


def helpset_names(archive: zipfile.ZipFile) -> list[str]:
    return [
        name for name in archive.namelist()
        if name.endswith("_HelpSet.hs") and name.startswith("help/")
    ]


def search_view_needs_data(text: str) -> bool:
    match = SEARCH_VIEW.search(text)
    return match is not None and "<data" not in match.group(0)


def patch_helpset_text(text: str, search_dir: str) -> str:
    match = SEARCH_VIEW.search(text)
    if match is None:
        raise FixError("helpset 中没有 Search 视图，拒绝写入。")
    block = match.group(0)
    if "<data" in block:
        raise FixError("Search 视图已带 data，拒绝重复写入。")
    patched_block = block.replace("</view>", DATA_ELEMENT % search_dir + "\t</view>")
    return text[: match.start()] + patched_block + text[match.end():]


def backup_path(backup_dir: pathlib.Path, jar: pathlib.Path, entry: str) -> pathlib.Path:
    return backup_dir / (str(jar).replace("/", "_") + "--" + entry.replace("/", "_") + ".orig")


def build_replacement_jar(jar: pathlib.Path, updated: dict[str, str],
                          added: dict[str, bytes]) -> pathlib.Path:
    """把原 JAR 的全部条目复制到临时文件并替换/新增指定条目。

    临时文件与目标 JAR 同目录，保证 os.replace 是同一文件系统上的原子替换。
    任何失败都会删除临时文件并重新抛出，原 JAR 不受影响。
    """
    temporary = jar.parent / f".{jar.name}.ctflab-{os.getpid()}.tmp"
    temporary.unlink(missing_ok=True)
    replaced = set(updated) | set(added)
    try:
        with zipfile.ZipFile(jar) as source, zipfile.ZipFile(temporary, "w") as target:
            for info in source.infolist():
                if info.filename in replaced:
                    continue
                data = b"" if info.is_dir() else source.read(info.filename)
                target.writestr(info, data)
            for name, text in updated.items():
                _write_entry(target, name, text.encode("iso-8859-1"))
            for name, data in sorted(added.items()):
                _write_entry(target, name, data)
        verify_jar(temporary, updated, added)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _write_entry(target: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    target.writestr(info, data)


def verify_jar(path: pathlib.Path, updated: dict[str, str], added: dict[str, bytes]) -> None:
    """校验临时 JAR 可读、条目完整，失败时抛 FixError。"""
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise FixError(f"临时 JAR 校验失败：{bad}")
        names = set(archive.namelist())
        for name, text in updated.items():
            if name not in names:
                raise FixError(f"临时 JAR 缺少 {name}")
            if archive.read(name).decode("iso-8859-1") != text:
                raise FixError(f"临时 JAR 中 {name} 内容不一致")
        for name in added:
            if name not in names:
                raise FixError(f"临时 JAR 缺少新增条目 {name}")


def install_jar(temporary: pathlib.Path, jar: pathlib.Path) -> None:
    """保留原文件权限后原子替换。"""
    mode = stat.S_IMODE(jar.stat().st_mode)
    os.chmod(temporary, mode)
    os.replace(temporary, jar)


def fix_jar(jar: pathlib.Path, javahelp_jar: pathlib.Path, backup_dir: pathlib.Path,
            *, java: str, indexer=None, log=print) -> tuple[int, int]:
    """处理单个 JAR，返回 (修复的 helpset 数, 跳过的 helpset 数)。

    一个 JAR 里的所有 helpset 先在临时目录里全部生成索引并汇总修改，再构建
    **一个**完整临时 JAR，校验通过后只做一次 os.replace；任一步失败都不会改动
    原 JAR，避免“第一个 helpset 已写入、第二个失败”的半修复状态。
    """
    indexer = indexer or run_indexer
    with zipfile.ZipFile(jar) as archive:
        names = archive.namelist()
        all_helpsets = helpset_names(archive)
        targets = [name for name in all_helpsets if search_view_needs_data(
            archive.read(name).decode("iso-8859-1"))]
    if not targets:
        return 0, len(all_helpsets)

    members = [name for name in names if name.startswith("help/")]
    relative = sorted(
        member[len("help/"):] for member in members
        if member.startswith("help/topics/")
        and member.lower().endswith((".htm", ".html"))
    )
    if not relative:
        raise FixError(f"{jar.name} 没有可索引的 HTML 主题")

    updated: dict[str, str] = {}
    added: dict[str, bytes] = {}
    backups: list[tuple[pathlib.Path, str]] = []
    counts: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="ctflab-ghidra-") as work_text:
        work = pathlib.Path(work_text)
        with zipfile.ZipFile(jar) as archive:
            archive.extractall(work, members=members)
        for entry in targets:
            module = entry[len("help/"):-len("_HelpSet.hs")]
            search_dir = f"{module}_JavaHelpSearch"
            database = work / "help" / search_dir
            database.mkdir(parents=True, exist_ok=True)
            indexer(java, javahelp_jar, database, relative, work / "help")
            missing = [name for name in INDEX_FILES if not (database / name).is_file()]
            if missing:
                raise FixError(f"{jar.name}: {entry} 索引不完整，缺少 {', '.join(missing)}")
            with zipfile.ZipFile(jar) as archive:
                original_text = archive.read(entry).decode("iso-8859-1")
            updated[entry] = patch_helpset_text(original_text, search_dir)
            backups.append((backup_path(backup_dir, jar, entry), original_text))
            counts[entry] = len(relative)
            for name in INDEX_FILES:
                added[f"help/{search_dir}/{name}"] = (database / name).read_bytes()
        temporary = build_replacement_jar(jar, updated, added)
    try:
        for path, text in backups:
            if not path.exists():
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                path.write_text(text, encoding="iso-8859-1")
        install_jar(temporary, jar)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    for entry in updated:
        log(f"已修复：{jar} -> {entry}（索引 {counts[entry]} 个主题）")
    return len(updated), 0


def fix_tree(root: pathlib.Path, javahelp_jar: pathlib.Path, backup_dir: pathlib.Path,
             *, java: str, indexer=None, log=print) -> dict[str, list]:
    """修复 root 下所有需要处理的 JAR，逐个原子替换。

    单个 JAR 失败只会记录在 failed 中并保持该 JAR 原样；已成功处理的 JAR 是
    完整可用的，重跑脚本会跳过它们。
    """
    indexer = indexer or run_indexer
    result: dict[str, list] = {"patched": [], "skipped": [], "failed": []}
    for jar in sorted(pathlib.Path(root).rglob("*.jar")):
        try:
            with zipfile.ZipFile(jar) as archive:
                if not helpset_names(archive):
                    continue
            patched, skipped = fix_jar(jar, javahelp_jar, backup_dir,
                                       java=java, indexer=indexer, log=log)
        except (OSError, zipfile.BadZipFile, FixError) as exc:
            result["failed"].append((jar, str(exc)))
            log(f"失败（保持原样）：{jar}：{exc}")
            continue
        if patched:
            result["patched"].append(jar)
        else:
            result["skipped"].append(jar)
    return result


def remaining_without_data(root: pathlib.Path) -> list[tuple[pathlib.Path, str]]:
    """复核：仍存在不带 data 的 Search 视图。"""
    remaining: list[tuple[pathlib.Path, str]] = []
    for jar in sorted(pathlib.Path(root).rglob("*.jar")):
        try:
            with zipfile.ZipFile(jar) as archive:
                for name in archive.namelist():
                    if name.endswith(".hs") and name.startswith("help/"):
                        text = archive.read(name).decode("iso-8859-1")
                        if search_view_needs_data(text):
                            remaining.append((jar, name))
        except (OSError, zipfile.BadZipFile):
            continue
    return remaining


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="修复 Ghidra JavaHelp view is invalid 异常")
    parser.add_argument("--root", type=pathlib.Path, default=ROOT_DEFAULT,
                        help="Ghidra 安装根目录（默认 /usr/share/ghidra）")
    parser.add_argument("--backup-dir", type=pathlib.Path, default=BACKUP_DEFAULT,
                        help="原始 helpset 备份目录")
    parser.add_argument("--java", help="java 可执行文件；默认自动探测")
    args = parser.parse_args(argv)

    if os.geteuid() != 0:
        print("请以 root 运行。", file=sys.stderr)
        return 1
    javahelp_jar = args.root / JAVAHELP_RELATIVE
    if not javahelp_jar.is_file():
        print(f"未找到 {javahelp_jar}；Ghidra 可能未安装或路径不同。", file=sys.stderr)
        return 1
    java = args.java or find_java()

    result = fix_tree(args.root, javahelp_jar, args.backup_dir, java=java)
    remaining = remaining_without_data(args.root)
    for jar, name in remaining:
        print(f"仍缺少 data：{jar} -> {name}")
    print(f"完成：修复 {len(result['patched'])} 个 JAR，跳过 {len(result['skipped'])} 个，"
          f"失败 {len(result['failed'])} 个，复核剩余 {len(remaining)} 个；"
          f"原始 helpset 备份在 {args.backup_dir}/。")
    return 1 if (result["failed"] or remaining) else 0


if __name__ == "__main__":
    sys.exit(main())
