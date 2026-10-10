#!/usr/bin/env python3
"""版本锁定的屏保离线构建包；只构建到私有 staging，绝不替换系统认证程序。"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import subprocess
import sys
import tarfile

import screen_wake_patch as wake

ARCHIVE_URL = "https://archive.xfce.org/src/apps/xfce4-screensaver/4.20/xfce4-screensaver-4.20.2.tar.xz"
ARCHIVE_SHA256 = "5032f60a31df5e50a80512e301b595be5ea6a6bd762cdd95cacc24cbd29a01d7"
TOP = "xfce4-screensaver-4.20.2"
MAX_ARCHIVE = 2 * 1024 * 1024
MAX_EXPANDED = 20 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def archive_files(data):
    """哈希门禁之后仍拒绝链接、设备、路径穿越和重复项；不调用 extractall。"""
    if len(data) > MAX_ARCHIVE or digest(data) != ARCHIVE_SHA256:
        raise ValueError("不是登记的官方 4.20.2 源码归档。")
    files, seen, total = {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as archive:
        for index, member in enumerate(archive):
            path = PurePosixPath(member.name)
            if (index >= 512 or path.is_absolute() or ".." in path.parts
                    or "\\" in member.name or not path.parts or path.parts[0] != TOP
                    or str(path) in seen or not (member.isfile() or member.isdir())):
                raise ValueError("归档含非法或重复条目。")
            seen.add(str(path))
            if member.isdir():
                continue
            total += member.size
            if member.size < 0 or total > MAX_EXPANDED:
                raise ValueError("归档展开尺寸超限。")
            with archive.extractfile(member) as source:
                files[str(path)] = source.read(member.size + 1)
            if len(files[str(path)]) != member.size:
                raise ValueError("归档文件长度不一致。")
    original = files[TOP + "/src/gs-window.c"]
    files[TOP + "/src/gs-window.c"] = wake.patched_source(original).encode()
    return files, wake.make_patch(original)


def prepare(data, output):
    files, patch = archive_files(data)
    output = Path(output).absolute()
    if output.parent.resolve(strict=True) != output.parent:
        raise ValueError("输出父目录含符号链接。")
    # 独占私有目录；构建包直到完整清单写入才有效。拒绝任何既有路径。
    output.mkdir(mode=0o700)
    try:
        files["wake.patch"] = patch
        for name, content in files.items():
            target = output / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        (output / "official-source.tar.xz").write_bytes(data)
        manifest = {
            "schema": 1, "version": wake.VERSION, "source_url": ARCHIVE_URL,
            "archive_sha256": ARCHIVE_SHA256, "source_sha256": wake.SOURCE_SHA256,
            "files": {name: digest(content) for name, content in sorted(files.items())},
            "status": "prepared-not-built-not-installed", "authentication": "pam",
            "runtime_verified": False,
        }
        (output / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    except BaseException:
        shutil.rmtree(output)
        raise
    return manifest


def verify_bundle(bundle):
    bundle = Path(bundle).absolute()
    if bundle.resolve(strict=True) != bundle:
        raise ValueError("构建目录含符号链接。")
    manifest = json.loads(wake.read_source(bundle / "MANIFEST.json"))
    if (manifest.get("schema") != 1 or manifest.get("version") != wake.VERSION
            or manifest.get("archive_sha256") != ARCHIVE_SHA256
            or manifest.get("authentication") != "pam"):
        raise ValueError("构建清单版本或认证方案不匹配。")
    # 重新由登记归档生成的文件哈希是内容门禁；清单本身不是可信签名。
    archive = wake.read_source(bundle / "official-source.tar.xz")
    files, patch = archive_files(archive)
    files["wake.patch"] = patch
    expected = {name: digest(content) for name, content in files.items()}
    if manifest.get("files") != expected:
        raise ValueError("清单与登记源码不一致。")
    actual = set()
    for target in (bundle / TOP).rglob("*"):
        if target.is_symlink() or not (target.is_file() or target.is_dir()):
            raise ValueError("源码树含链接或特殊文件。")
        if target.is_file():
            actual.add(target.relative_to(bundle).as_posix())
    if actual != {name for name in expected if name.startswith(TOP + "/")}:
        raise ValueError("源码树含未登记文件或缺失文件。")
    for name, expected_hash in expected.items():
        target = bundle / name
        if target.resolve(strict=True) != target or digest(wake.read_source(target)) != expected_hash:
            raise ValueError("源码被修改或含符号链接：" + name)
    return manifest


def build(bundle):
    if sys.platform != "linux" or platform.machine() != "aarch64" or os.geteuid() == 0:
        raise ValueError("请在 Kali ARM64 中以普通用户构建；禁止宿主或 root 执行。")
    bundle = Path(bundle).absolute()
    verify_bundle(bundle)
    if any(os.path.lexists(bundle / name) for name in ("build", "stage", "BUILD.json")):
        raise ValueError("已有构建产物，请使用全新构建包；不覆盖。")
    for name in ("meson", "ninja", "cc", "pkg-config"):
        if not shutil.which(name):
            raise ValueError("缺少构建工具：" + name + "；未安装或改写系统。")
    # 不关闭认证、不修改 PAM、不启动候选屏保、不写 /usr；缺依赖时由 Meson 停止。
    commands = [
        ["meson", "setup", str(bundle / "build"), str(bundle / TOP), "--prefix=/usr",
         "--sysconfdir=/etc", "-Dauthentication-scheme=pam", "-Dsession-manager=systemd",
         "-Dx11=enabled", "-Dwayland=disabled", "-Ddocs=disabled", "--wrap-mode=nodownload"],
        ["meson", "compile", "-C", str(bundle / "build")],
        ["meson", "install", "-C", str(bundle / "build"), "--destdir", str(bundle / "stage")],
    ]
    for command in commands:
        subprocess.run(command, check=True, cwd=bundle)
    result = {"status": "staged-not-installed", "runtime_verified": False,
              "authentication": "pam", "system_modified": False}
    (bundle / "BUILD.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    command = subs.add_parser("prepare")
    command.add_argument("archive", type=Path)
    command.add_argument("--out", type=Path, required=True)
    command = subs.add_parser("build")
    command.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            data = wake.read_source(args.archive)
            result = prepare(data, args.out)
        else:
            result = build(args.bundle)
        summary = {key: value for key, value in result.items() if key != "files"}
        if "files" in result:
            summary["file_count"] = len(result["files"])
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as error:
        print("错误：" + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
