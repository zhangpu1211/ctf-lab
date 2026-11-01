#!/usr/bin/env python3
"""生成版本锁定的 Xfce 小幅移动唤醒补丁；不安装、不修改屏保或认证配置。"""
import argparse
import difflib
import hashlib
import os
from pathlib import Path
import stat
import sys
import tempfile

VERSION = "4.20.2"
SOURCE_URL = ("https://raw.githubusercontent.com/xfce-mirror/xfce4-screensaver/"
              "xfce4-screensaver-4.20.2/src/gs-window.c")
SOURCE_SHA256 = "5fec2129f0217c7ff6e1d9d16a5d3c4878649a7aa6ba2121d41872a114e89c7f"
MAX_SOURCE_BYTES = 1024 * 1024
OLD_RATIO = "    gdouble min_percentage = 0.1;"
NEW_RATIO = "    gdouble min_percentage = 0.005; /* CTFLab: small real pointer motion */"
OLD_DISTANCE = "    min_distance = gdk_screen_get_width (screen) * min_percentage;"
NEW_DISTANCE = "    min_distance = CLAMP (gdk_screen_get_width (screen) * min_percentage, 8.0, 24.0);"


def patched_source(source):
    """只接受逐字匹配的官方版本，不改活动处理、认证或事件转发。"""
    if len(source) > MAX_SOURCE_BYTES or hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("源码不是已登记的 Xfce 4.20.2 文件；拒绝猜测或跨版本补丁。")
    original = source.decode("utf-8")
    for before in (OLD_RATIO, OLD_DISTANCE):
        if original.count(before) != 1:
            raise ValueError("源码锚点不唯一，拒绝生成。")
    return original.replace(OLD_RATIO, NEW_RATIO).replace(OLD_DISTANCE, NEW_DISTANCE)


def make_patch(source):
    updated = patched_source(source)
    header = (f"# CTFLab candidate; xfce4-screensaver {VERSION}\n"
              f"# Original-SHA256: {SOURCE_SHA256}\n"
              f"# Source: {SOURCE_URL}\n"
              "# Scope: real-motion threshold only; authentication unchanged\n"
              "# Runtime acceptance: NOT VERIFIED; do not auto-install\n")
    diff = difflib.unified_diff(source.decode("utf-8").splitlines(keepends=True),
                               updated.splitlines(keepends=True),
                               fromfile="a/src/gs-window.c", tofile="b/src/gs-window.c")
    return (header + "".join(diff)).encode("utf-8")


def read_source(path):
    """拒绝链接、设备和 FIFO，限制读取量；不读取任意安装凭据。"""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("输入必须是普通源码文件。")
        data = handle.read(MAX_SOURCE_BYTES + 1)
    return data


def publish_patch(source, output):
    data = make_patch(source)
    output = Path(output).absolute()
    # 不沿输出目录符号链接写入；现有路径包括损坏链接一律拒绝。
    if output.parent.resolve(strict=True) != output.parent or os.path.lexists(output):
        raise ValueError("输出已存在或父目录含符号链接；不允许覆盖。")
    fd, name = tempfile.mkstemp(prefix=".ctflab-wake-", dir=output.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fchmod(handle.fileno(), 0o644)
            os.fsync(handle.fileno())
        os.link(temporary, output, follow_symlinks=False)
    finally:
        temporary.unlink(missing_ok=True)
    return hashlib.sha256(data).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="官方 4.20.2 的 src/gs-window.c")
    parser.add_argument("--out", type=Path, required=True, help="全新补丁文件，不覆盖")
    args = parser.parse_args(argv)
    try:
        digest = publish_patch(read_source(args.source), args.out)
        print(f"候选补丁已生成，SHA-256：{digest}")
        print("仅降低真实鼠标移动门槛；尚未来宾编译或验收，不自动安装。")
        return 0
    except (ValueError, OSError, UnicodeError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
