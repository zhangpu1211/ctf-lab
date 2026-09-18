#!/usr/bin/env python3
"""CTFLab Task 6.2：包含受控 QEMU 运行时的 `CTFLab.app` 本地构建。

设计见 `docs/ctflab-task6-app-runtime-design.md`。核心约束：

- 只随包必要的 QEMU 程序、firmware/ROM/keymaps 与其非系统动态库；macOS 系统库不复制；
- 动态库闭包用 `otool -L` 递归求解，路径改写为 `@loader_path` 相对引用；无法确认的依赖直接失败，
  不猜测、不跳过；
- `.app` 内不出现任何虚拟磁盘、凭据、日志；运行状态仍写在 app 外部；
- 排他发布：同父目录内构建随机临时 `.app`，全部校验通过后才改名为最终目录；失败清理本次临时内容；
- 签名分级如实记录：`unsigned` / `ad-hoc` / `developer-id`；没有真实身份时不冒充 Developer ID；
  公证只记录“未验证/后续任务”，本模块不接触任何密码或凭据；
- 许可证闭环：随包附项目 `LICENSE`（`ctflab_package.PROJECT_LICENSE` 单一来源）；Homebrew keg 缺
  许可证文本的组件回退到仓库 `tools/licenses/` 的 vendored 文本（如 dtc/libfdt）；
  GPL-2.0 组件的源码义务用随包 `SOURCE_OFFER.md` 书面要约履行（GPL-2.0 §3），
  源码哈希按版本登记，未知版本直接失败——不编造、不猜测。
"""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_ROOT = TOOLS_DIR.parent

APP_BUNDLE_NAME = "CTFLab.app"
# 双击打开运行的是原生图形入口；`ctflab-cli` 与兼容名 `CTFLab` 都指向同一 CLI 启动器。
APP_EXECUTABLE = "CTFLab"          # 兼容保留的 CLI 启动器名（既有脚本/验收引用）
GUI_EXECUTABLE = "CTFLabGUI"       # CFBundleExecutable：原生 SwiftUI 入口
CLI_EXECUTABLE = "ctflab-cli"      # GUI 调用的 CLI 启动器
GUI_SOURCE_DIR = "gui"
# 编译进 app 的源码（测试文件只随包镜像、不参与编译，避免重复符号）。
GUI_SOURCES = ("GuiCore.swift", "GuiApp.swift")
GUI_MIRROR_EXTRA = ("GuiCoreTests.swift",)
# 产品与随包运行时统一以 macOS 26.0 为最低目标，避免 GUI 与 Info.plist/运行时出现相互矛盾的门槛。
GUI_TARGET = "arm64-apple-macos26.0"
CTFLAB_VERSION_FALLBACK = "0.1.0"
BUNDLE_IDENTIFIER = "local.ctflab.app"
RUNTIME_REL = "Contents/Resources/runtime"
CTFLAB_REL = "Contents/Resources/ctflab"
LICENSES_REL = "Contents/Resources/licenses"
MANIFEST_REL = "Contents/Resources/MANIFEST.json"
SBOM_REL = "Contents/Resources/SBOM.json"
THIRD_PARTY_REL = "Contents/Resources/THIRD_PARTY_LICENSES.md"
LICENSE_REL = "Contents/Resources/LICENSE"
SOURCE_OFFER_REL = "Contents/Resources/SOURCE_OFFER.md"
# CLI 启动器放在 Resources/bin（MacOS/ 只放原生主入口）：codesign 会把 MacOS/ 内的
# 额外可执行文件当作嵌套代码要求单独签名，而脚本签名依赖扩展属性、不适合分发；
# 放在 Resources/ 里由 bundle 签名按哈希封存，随包复制不会失效。
LAUNCHER_REL = "Contents/Resources/bin/ctflab-cli"
LAUNCHER_COMPAT_REL = f"Contents/Resources/bin/{APP_EXECUTABLE}"
INFO_PLIST_REL = "Contents/Info.plist"
SIGNATURE_DIR_REL = "Contents/_CodeSignature"

# 仓库内 vendored 许可证文本目录（Homebrew keg 缺文本时的回退；见 tools/licenses/PROVENANCE.md）。
VENDORED_LICENSES_REL = "tools/licenses"

# QEMU 对应源码（GPL-2.0 §3 书面要约指向的上游归档）。版本必须与随包二进制一致；
# 未知版本的源码哈希无法编造，构建直接失败并要求先核实登记。
QEMU_SOURCE_URL_TEMPLATE = "https://download.qemu.org/qemu-{version}.tar.xz"
QEMU_SOURCE_SHA256 = {
    "11.1.0": "6ee1d1a61f68212476b27108c26da5f449dc09b626d42f8279ba0dc2e08fa858",
}

# 内置 Python 运行时（python-build-standalone，见 docs/ctflab-task6-app-runtime-design.md §11）。
PYTHON_RUNTIME_REL = f"{RUNTIME_REL}/python"
# 裁剪清单：只保留 CTFLab CLI 运行所需（stdlib + 内置扩展）。每一项在构建时记录，
# 裁剪内容与理由见设计文档；tkinter/Tcl/Tk 不随包（无许可证文本缺口）、pip/ensurepip 不随包
# （学生机不需要安装包）、idle/lib2to3/2to3 等开发工具与 include/config 头文件不随包。
PYTHON_PRUNE_GLOBS = (
    "include",
    "share",
    "bin/2to3*",
    "bin/idle3*",
    "bin/pip*",
    "bin/pydoc3*",
    "bin/python3-config*",
    "bin/python",                # 别名；保留 bin/python3（硬链接到 python3.12）
    "lib/libtcl*",
    "lib/libtk*",
    "lib/tcl*",
    "lib/tk*",
    "lib/itcl*",
    "lib/thread*",
    "lib/libpython3.*.dylib",    # python-build-standalone 的静态可执行文件不加载它（实测）
    "lib/pkgconfig",
    "lib/python*/idlelib",
    "lib/python*/lib2to3",
    "lib/python*/tkinter",
    "lib/python*/ensurepip",
    "lib/python*/config-*",
    "lib/python*/lib-dynload/_tkinter*",
    "lib/python*/site-packages/pip*",
)
PYTHON_VERSION_RE = re.compile(r"^Python\s+([0-9][0-9A-Za-z.]*)$")
PBS_ASSET_RE = re.compile(r"^(cpython-\d+\.\d+\.\d+)\+(\d{8})-aarch64-apple-darwin-")

QEMU_BINARIES = ("qemu-system-aarch64", "qemu-system-x86_64", "qemu-img")
# 课堂分发包最低支持 macOS 26.0。当前受控 QEMU 运行时使用 macOS 26 SDK 构建，
# 并可合法引用 macOS 26 提供的系统符号；不再向旧系统承诺兼容性。
MIN_BUNDLED_MACOS = "26.0"
MIN_BUNDLED_MACOS_VERSION = (26, 0)
# 外置 SPICE 客户端是可选运行时；未提供时保留默认 Cocoa App，显式请求 SPICE 会被 CLI 拒绝。
SPICE_CLIENT_NAME = "spicy"
# 只随包实际需要的固件/ROM/keymaps（aarch64 virt UEFI + x86_64 pc BIOS/UEFI 与三种网卡）。
QEMU_SHARE_FILES = (
    "edk2-aarch64-code.fd",   # aarch64 virt 的 UEFI 固件代码
    "edk2-arm-vars.fd",       # aarch64 UEFI NVRAM 模板（CTFLab 每个实例复制一份）
    "edk2-x86_64-code.fd",    # x86_64 UEFI（启动回退矩阵的 OVMF 路径）
    "edk2-i386-vars.fd",      # x86_64 UEFI NVRAM 模板
    "bios-256k.bin",          # pc 机器默认 SeaBIOS
    "bios.bin",
    "kvmvapic.bin",           # pc + TCG 的 vapic 支持
    "vgabios-stdvga.bin",
    "vgabios-virtio.bin",
    "efi-e1000.rom",          # basic-pentesting-2 的 e1000 UEFI 引导 ROM
    "efi-pcnet.rom",          # smoke 的 pcnet UEFI 引导 ROM
    "efi-virtio.rom",         # kali 的 virtio-net UEFI 引导 ROM
    "pxe-e1000.rom",
    "pxe-pcnet.rom",
    "pxe-virtio.rom",
    "edk2-licenses.txt",      # EDK2 固件许可证文本（随包分发）
)
# 存在才复制：缺失不视为错误（-nographic 的 BIOS 串口 ROM，非必需）。
QEMU_OPTIONAL_SHARE_FILES = ("sgabios.bin",)
QEMU_SHARE_DIRS = ("keymaps",)
SYSTEM_PREFIX_PATTERNS = (
    re.compile(r"^/usr/lib/"),
    re.compile(r"^/System/"),
)
FORBIDDEN_BINARY_PATTERNS = (
    re.compile(r"/opt/homebrew"),
    re.compile(r"/usr/local/"),
    re.compile(r"/Users/"),
    re.compile(r"conda"),
)
FORBIDDEN_APP_SUFFIXES = (".qcow2", ".qcow", ".raw", ".img", ".vmdk", ".vdi", ".vhd", ".vhdx",
                          ".ova", ".pcap", ".pem", ".key")
FORBIDDEN_APP_NAMES = (re.compile(r"^credentials.*\.txt$"), re.compile(r"^guest-credentials.*$"),
                       re.compile(r"^\.env(\.|$)"))

# 许可标识来自 Homebrew formula 声明与随包许可证文本；未做法律审查，未知一律如实标注。
KNOWN_LICENSES = {
    "qemu": "GPL-2.0-only",
    "capstone": "BSD-3-Clause",
    "dtc": "BSD-2-Clause OR GPL-2.0-or-later（libfdt 双许可）",
    "gettext": "LGPL-2.1-or-later",
    "glib": "LGPL-2.1-or-later",
    "gmp": "LGPL-3.0-or-later OR GPL-2.0-or-later",
    "gnutls": "LGPL-2.1-or-later",
    "jpeg-turbo": "BSD-3-Clause AND IJG",
    "libidn2": "LGPL-3.0-or-later OR GPL-2.0-or-later",
    "libpng": "libpng-2.0",
    "libslirp": "BSD-3-Clause",
    "libssh": "LGPL-2.1-or-later",
    "libtasn1": "LGPL-2.1-or-later",
    "libunistring": "LGPL-3.0-or-later OR GPL-2.0-or-later",
    "libusb": "LGPL-2.1-or-later",
    "lzo": "GPL-2.0-or-later",
    "ncurses": "MIT",
    "nettle": "LGPL-3.0-or-later OR GPL-2.0-or-later",
    "openssl@3": "Apache-2.0",
    "p11-kit": "BSD-3-Clause",
    "pcre2": "BSD-3-Clause",
    "pixman": "MIT",
    "python": "PSF-2.0",
    "pyyaml": "MIT",
    "snappy": "BSD-3-Clause",
    "vde": "GPL-2.0-or-later AND LGPL-2.1-or-later（libvdeplug）",
    "zstd": "BSD-3-Clause OR GPL-2.0",
    "spice-gtk": "LGPL-2.1-or-later",
    "sqlite": "blessing",
}
LICENSE_GLOBS = ("COPYING*", "LICENSE*", "NOTICE*", "LGPL-*", "GPL-*", "MIT*", "BSD*")

LAUNCHER_TEMPLATE = """#!/bin/sh
# CTFLab 启动器（.app 内）：使用 app 自带运行时（QEMU + Python），不依赖任何开发机路径。
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# 启动器位于 Contents/Resources/bin：向上找到包含 Resources/ctflab 的 Contents 目录，
# 不假设固定的相对深度（MacOS/ 或 Resources/bin/ 都能工作）。
contents_dir="$script_dir"
while [ "$contents_dir" != "/" ] && [ ! -d "$contents_dir/Resources/ctflab" ]; do
  contents_dir=$(dirname "$contents_dir")
done
resources="$contents_dir/Resources"
runtime="$resources/runtime"
if [ -d "$runtime/bin" ]; then
  CTFLAB_RUNTIME_ROOT="$runtime"
  export CTFLAB_RUNTIME_ROOT
fi

python_bin="$runtime/python/bin/python3"
if [ ! -x "$python_bin" ]; then
  echo "错误：App 内 Python 运行时缺失或不可执行（构建不完整）；不回退系统 Python。" >&2
  exit 1
fi

# 不在已签名 bundle 内写 __pycache__（保护签名与清单）；子进程同样生效。
PYTHONDONTWRITEBYTECODE=1
PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE PYTHONNOUSERSITE

# -B：禁止写字节码缓存；-s：忽略用户 site-packages；-E：忽略 PYTHON* 环境变量。
exec "$python_bin" -B -s -E "$resources/ctflab/tools/ctflab.py" "$@"
"""


class AppBuildError(Exception):
    """app 构建/校验失败的统一异常。"""


def _expect(condition: Any, message: str) -> None:
    if not condition:
        raise AppBuildError(message)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ctflab_version() -> str:
    import ctflab  # noqa: PLC0415  函数内导入，避免循环依赖

    return str(getattr(ctflab, "CTFLAB_VERSION", CTFLAB_VERSION_FALLBACK))


# --------------------------------------------------------------------------- otool 封装

def _run_tool(command: list[str], *, check: bool = True,
              env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, text=True, env=env)
    if check and result.returncode != 0:
        raise AppBuildError(f"命令失败：{' '.join(command)}：{(result.stderr or result.stdout).strip()}")
    return result


def otool_deps(path: Path) -> list[str]:
    _expect(shutil.which("otool"), "需要 macOS otool（Xcode 命令行工具）来解析动态库依赖。")
    output = _run_tool(["otool", "-L", str(path)]).stdout
    deps: list[str] = []
    for line in output.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        deps.append(line.split(" (compatibility")[0].strip())
    return deps


def otool_rpaths(path: Path) -> list[str]:
    output = _run_tool(["otool", "-l", str(path)]).stdout
    return re.findall(r"path (.+?) \(offset \d+\)", output)


def otool_install_id(path: Path) -> str | None:
    result = _run_tool(["otool", "-D", str(path)], check=False)
    lines = [line.strip() for line in result.stdout.splitlines()[1:] if line.strip()]
    return lines[0] if lines else None


def is_system_library(dep: str) -> bool:
    return any(pattern.match(dep) for pattern in SYSTEM_PREFIX_PATTERNS)


def resolve_dep(dep: str, owner: Path) -> Path:
    """把一条依赖解析为真实文件路径；无法确认时直接失败（不猜测）。"""
    if dep.startswith("@rpath/"):
        suffix = dep[len("@rpath/"):]
        for rpath in otool_rpaths(owner):
            expanded = rpath.replace("@loader_path", str(owner.parent)).replace(
                "@executable_path", str(owner.parent))
            candidate = Path(expanded) / suffix
            if candidate.exists():
                return candidate
        raise AppBuildError(f"无法解析 @rpath 依赖：{dep}（来自 {owner}）")
    if dep.startswith("@loader_path/"):
        candidate = owner.parent / dep[len("@loader_path/"):]
        _expect(candidate.exists(), f"@loader_path 依赖不存在：{dep}（来自 {owner}）")
        return candidate
    if dep.startswith("@executable_path/"):
        candidate = owner.parent / dep[len("@executable_path/"):]
        _expect(candidate.exists(), f"@executable_path 依赖不存在：{dep}（来自 {owner}）")
        return candidate
    candidate = Path(dep)
    _expect(candidate.exists(), f"依赖不存在：{dep}（来自 {owner}）")
    return candidate


def collect_dylib_closure(binaries: Iterable[Path]) -> dict[str, Path]:
    """递归收集非系统动态库闭包；同名不同文件视为冲突并失败。"""
    libs: dict[str, Path] = {}
    queue = list(binaries)
    visited: set[Path] = set()
    while queue:
        current = queue.pop()
        if current in visited:
            continue
        visited.add(current)
        for dep in otool_deps(current):
            if is_system_library(dep):
                continue
            # 文件名沿用加载器期望的 soname（Homebrew 的 unversioned 符号链接名），
            # 冲突检测用解析后的真实路径，避免 /opt/homebrew/opt/<f> 与 Cellar 误判。
            resolved = resolve_dep(dep, current)
            name = resolved.name
            canonical = resolved.resolve()
            if name in libs and libs[name].resolve() != canonical:
                raise AppBuildError(f"动态库同名冲突：{name} → {libs[name]} 与 {resolved}")
            if name not in libs:
                libs[name] = resolved
                queue.append(resolved)
    return libs


def forbidden_binary_reference(path: Path) -> list[str]:
    """返回二进制/动态库中残留的禁止依赖、install id 或 LC_RPATH。"""
    hits: list[str] = []
    for dep in otool_deps(path):
        for pattern in FORBIDDEN_BINARY_PATTERNS:
            if pattern.search(dep):
                hits.append(dep)
                break
    install_id = otool_install_id(path)
    if install_id:
        for pattern in FORBIDDEN_BINARY_PATTERNS:
            if pattern.search(install_id):
                hits.append(f"install-id: {install_id}")
                break
    for rpath in otool_rpaths(path):
        for pattern in FORBIDDEN_BINARY_PATTERNS:
            if pattern.search(rpath):
                hits.append(f"rpath: {rpath}")
                break
    return hits


# --------------------------------------------------------------------------- 运行时准备

def detect_qemu_root() -> Path:
    """从 PATH 探测 QEMU 安装根目录（开发机用；app 内不写死任何路径）。"""
    qemu_img = shutil.which("qemu-img")
    _expect(qemu_img, "未找到 qemu-img：请先安装 QEMU（brew install qemu）或指定 --qemu-root。")
    root = Path(qemu_img).resolve().parent.parent
    _expect((root / "share" / "qemu").is_dir(), f"{root} 下缺少 share/qemu，无法作为运行时来源。")
    return root


def copy_qemu_share(source_root: Path, destination: Path,
                    share_files: Iterable[str] | None = None) -> list[str]:
    share_src = source_root / "share" / "qemu"
    copied: list[str] = []
    names = list(
        share_files if share_files is not None
        else (*QEMU_SHARE_FILES, *QEMU_OPTIONAL_SHARE_FILES)
    )
    for name in names:
        candidate = share_src / name
        if not candidate.is_file():
            if name in QEMU_OPTIONAL_SHARE_FILES:
                continue
            raise AppBuildError(f"固件/ROM 缺失：{candidate}（无法确认时停止，不用宿主兜底）")
        shutil.copy2(candidate, destination / name)
        copied.append(name)
    for directory in QEMU_SHARE_DIRS:
        source_dir = share_src / directory
        _expect(source_dir.is_dir(), f"缺少资源目录：{source_dir}")
        shutil.copytree(source_dir, destination / directory)
        copied.extend(
            f"{directory}/{path.relative_to(source_dir).as_posix()}"
            for path in sorted(source_dir.rglob("*")) if path.is_file()
        )
    return copied


def _formula_of(path: Path) -> str | None:
    match = re.search(r"/opt/homebrew/(?:Cellar|opt)/([^/]+)", str(path))
    return match.group(1) if match else None


def _formula_version(formula: str, opt_root: Path = Path("/opt/homebrew/opt")) -> str | None:
    """解析 `<opt_root>/<formula>` 指向的 Cellar 版本目录名（如 `11.1.0`）。"""
    opt = Path(opt_root) / formula
    if opt.exists():
        target = opt.resolve()
        # target 形如 <prefix>/Cellar/<formula>/<version>，因此 Cellar 在两级之上。
        if target.parent.parent.name == "Cellar":
            return target.name
    return None


def qemu_source_description(qemu_root: Path) -> str:
    """给 QEMU 二进制记录真实来源类别，不把上游源码构建误写成 Homebrew bottle。"""
    binary = Path(qemu_root) / "bin" / "qemu-system-aarch64"
    formula = _formula_of(binary)
    if formula == "qemu":
        return f"Homebrew qemu {_formula_version('qemu') or '?'}"
    version = _qemu_semver(_qemu_version(binary)) or "unknown"
    return f"Upstream QEMU {version} source build"


def collect_license_texts(formula: str) -> list[tuple[str, Path]]:
    """收集某个 formula 的许可证文本；找不到时返回空列表（由调用方决定是否失败）。"""
    keg = Path("/opt/homebrew/opt") / formula
    if not keg.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for pattern in LICENSE_GLOBS:
        for path in sorted(keg.glob(pattern)):
            if path.is_file() and path.name not in seen:
                seen.add(path.name)
                found.append((path.name, path))
    return found


def collect_vendored_license_texts(source_root: Path, formula: str) -> list[tuple[str, Path]]:
    """回退：仓库 `tools/licenses/<formula>/` 内原样 vendored 的上游许可证文本。

    Homebrew keg 不随附所有上游文本（例如 dtc/libfdt），回退目录里的每个普通文件都随包分发；
    目录不存在或为空时返回空列表，由调用方决定是否失败。来源与哈希登记见 PROVENANCE.md。
    """
    vendored = Path(source_root) / VENDORED_LICENSES_REL / formula
    if not vendored.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    for path in sorted(vendored.iterdir()):
        _expect(not path.is_symlink(), f"vendored 许可证文本不得是符号链接：{path}")
        if path.is_file() and not path.name.startswith("."):
            found.append((path.name, path))
    return found


MACHO_MAGICS = (
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",   # 32 位
    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",   # 64 位
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",   # fat/universal
)


def _is_mach_o(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) in MACHO_MAGICS
    except OSError:
        return False


def macho_minimum_os(path: Path) -> tuple[int, int] | None:
    """读取 Mach-O 的 LC_BUILD_VERSION.minos；无法读取时返回 None。"""
    result = _run_tool(["otool", "-l", str(path)], check=False)
    versions = re.findall(r"\n\s+minos\s+(\d+)\.(\d+)", result.stdout)
    if not versions:
        return None
    return max((int(major), int(minor)) for major, minor in versions)


def macho_version_text(version: tuple[int, int]) -> str:
    return f"{version[0]}.{version[1]}"


def iter_macho_files(root: Path) -> list[Path]:
    """递归列出 Mach-O 文件（用魔数判断，不依赖 file 命令）。"""
    if not root.is_dir():
        return []
    return [path for path in sorted(root.rglob("*")) if path.is_file() and _is_mach_o(path)]


def _extract_tar_safely(archive: Path, destination: Path) -> None:
    """解包 .tar.gz；拒绝绝对路径、`..` 越界与设备/硬链接成员。"""
    import tarfile  # noqa: PLC0415

    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            name = PurePosixPath(member.name)
            _expect(not name.is_absolute() and ".." not in name.parts,
                    f"归档成员路径越界：{member.name}")
            if member.issym():
                target = PurePosixPath(member.linkname)
                _expect(not target.is_absolute() and ".." not in target.parts,
                        f"归档符号链接越界：{member.name} -> {member.linkname}")
            _expect(member.isfile() or member.isdir() or member.issym(),
                    f"归档含不允许的成员类型：{member.name}")
        tar.extractall(destination)  # noqa: S202  已逐成员校验路径与类型


def _dereference_symlinks(root: Path) -> int:
    """把树内符号链接替换为指向目标的硬链接（app 内禁止符号链接，见 verify_app）。"""
    resolved_root = root.resolve()
    replaced = 0
    for path in sorted(root.rglob("*")):
        if not path.is_symlink():
            continue
        target = path.resolve()
        _expect(target.is_file(), f"符号链接目标不是普通文件：{path} -> {target}")
        _expect(target.is_relative_to(resolved_root),
                f"符号链接指向树外：{path} -> {target}")
        path.unlink()
        os.link(target, path)
        replaced += 1
    return replaced


def _prune_python_tree(root: Path, patterns: tuple[str, ...] = PYTHON_PRUNE_GLOBS) -> list[str]:
    """按白名单外清单裁剪发行版；返回实际删除的相对路径（记录进 MANIFEST）。"""
    removed: list[str] = []
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            removed.append(path.relative_to(root).as_posix())
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
    return sorted(removed)


def _python_version(python_root: Path) -> str | None:
    binary = python_root / "bin" / "python3"
    if not binary.is_file():
        return None
    result = _run_tool([str(binary), "--version"], check=False)
    text = (result.stdout or result.stderr).strip()
    match = PYTHON_VERSION_RE.match(text)
    return match.group(1) if match else None


def copy_python_runtime(source: Path, destination: Path, *,
                        expected_sha256: str | None = None) -> dict[str, Any]:
    """把 python-build-standalone 发行版（.tar.gz 或已解包目录）复制进 app。

    复制后：按 PYTHON_PRUNE_GLOBS 裁剪、符号链接解引用为硬链接、断言无符号链接残留。
    返回 SBOM 元数据；归档只接受 `.tar.gz`，哈希可选用 `expected_sha256` 强制校验。
    """
    source = Path(source).expanduser()
    _expect(source.exists(), f"Python 运行时不不存在：{source}")
    staging: Path | None = None
    if source.is_dir():
        source_root = source
        archive_sha256: str | None = None
    else:
        _expect(source.name.endswith(".tar.gz"),
                f"Python 运行时必须是 .tar.gz 归档或目录：{source}")
        archive_sha256 = sha256_file(source)
        if expected_sha256:
            _expect(archive_sha256 == expected_sha256,
                    f"Python 运行时归档 SHA-256 不符：期望 {expected_sha256}，"
                    f"实际 {archive_sha256}")
        staging = destination.parent / f".{destination.name}.staging"
        _expect(not staging.exists(), f"Python 运行时临时目录已存在：{staging}")
        staging.mkdir()
        try:
            _extract_tar_safely(source, staging)
            candidates = [staging] if (staging / "bin" / "python3").is_file() else [
                child for child in staging.iterdir()
                if child.is_dir() and (child / "bin" / "python3").is_file()]
            _expect(len(candidates) == 1,
                    f"归档内找不到唯一的 Python 发行版根目录（含 bin/python3）：{source.name}")
            source_root = candidates[0]
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    try:
        shutil.copytree(source_root, destination, symlinks=True)
        pruned = _prune_python_tree(destination)
        replaced = _dereference_symlinks(destination)
        leftovers = [path.relative_to(destination).as_posix()
                     for path in sorted(destination.rglob("*")) if path.is_symlink()]
        _expect(not leftovers, f"Python 运行时仍含符号链接：{', '.join(leftovers[:5])}")
        version = _python_version(destination)
        _expect(version, "无法读取内置 Python 版本（bin/python3 --version）。")
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)

    asset_match = PBS_ASSET_RE.match(source.name)
    if asset_match:
        source_desc = (f"python-build-standalone {asset_match.group(2)}"
                       f"（{asset_match.group(1)}）")
    else:
        source_desc = f"python-build-standalone（来源名未识别：{source.name}）"
    return {
        "version": version,
        "source": source_desc,
        "archive_sha256": archive_sha256,
        "symlinks_dereferenced": replaced,
        "pruned": pruned,
    }


def copy_pyyaml(source: Path, site_packages: Path, licenses_dir: Path, *,
                expected_sha256: str | None = None) -> dict[str, Any]:
    """把 PyYAML（wheel 或已解包目录）复制进 site-packages，并提取 MIT 许可证文本。

    只复制 `yaml/` 与 `_yaml/` 两个包（wheel 的 dist-info 不随包，来源以 SBOM 记录为准）。
    """
    source = Path(source).expanduser()
    _expect(source.exists(), f"PyYAML 来源不存在：{source}")
    wheel_sha256: str | None = None
    license_text: str | None = None
    version: str | None = None

    def _copy_from_dir(root: Path) -> int:
        nonlocal license_text, version
        yaml_pkg = root / "yaml"
        _expect((yaml_pkg / "__init__.py").is_file(),
                f"PyYAML 来源缺少 yaml/__init__.py：{root}")
        count = 0
        for name in ("yaml", "_yaml"):
            pkg = root / name
            if not pkg.is_dir():
                continue
            for path in sorted(pkg.rglob("*")):
                _expect(not path.is_symlink(), f"PyYAML 包内不得含符号链接：{path}")
                if path.is_file():
                    target = site_packages / name / path.relative_to(pkg)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                    count += 1
        for dist_info in sorted(root.glob("*.dist-info")):
            metadata = dist_info / "METADATA"
            if metadata.is_file():
                match = re.search(r"^Version:\s*(\S+)\s*$", metadata.read_text(encoding="utf-8"),
                                  re.MULTILINE)
                if match:
                    version = match.group(1)
            for license_file in sorted((dist_info / "licenses").glob("*")) if (dist_info / "licenses").is_dir() else []:
                if license_file.is_file():
                    licenses_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(license_file, licenses_dir / "LICENSE")
                    license_text = licenses_dir / "LICENSE"
                    break
        return count

    if source.is_dir():
        file_count = _copy_from_dir(source)
    else:
        _expect(source.suffix == ".whl", f"PyYAML 来源必须是 .whl 或目录：{source}")
        wheel_sha256 = sha256_file(source)
        if expected_sha256:
            _expect(wheel_sha256 == expected_sha256,
                    f"PyYAML wheel SHA-256 不符：期望 {expected_sha256}，实际 {wheel_sha256}")
        import zipfile  # noqa: PLC0415

        staging = Path(tempfile.mkdtemp(prefix=".pyyaml.", suffix=".tmp"))
        try:
            with zipfile.ZipFile(source) as archive:
                for member in archive.namelist():
                    name = PurePosixPath(member)
                    _expect(not name.is_absolute() and ".." not in name.parts,
                            f"PyYAML wheel 成员路径越界：{member}")
                archive.extractall(staging)  # noqa: S202  已逐个成员校验
            file_count = _copy_from_dir(staging)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    _expect(version, f"无法从 PyYAML 来源确定版本：{source}")
    _expect(license_text is not None,
            f"PyYAML 来源缺少许可证文本（dist-info/licenses/LICENSE）：{source}")
    name_match = re.match(r"^[Pp]y[Yy][Aa][Mm][Ll]-(\d+\.\d+\.\d+)-", source.name)
    if name_match:
        _expect(name_match.group(1) == version,
                f"PyYAML wheel 文件名版本（{name_match.group(1)}）与 METADATA（{version}）不一致")
    return {
        "version": version,
        "wheel_sha256": wheel_sha256,
        "files": file_count,
    }


def _qemu_semver(version_line: str | None) -> str | None:
    """从 `QEMU emulator version 11.1.0` 之类的首行提取版本号。"""
    if not version_line:
        return None
    match = re.search(r"version\s+([0-9][0-9A-Za-z.\-]*)", version_line)
    return match.group(1) if match else None


def _plus_three_years(generated_at: str) -> str:
    """按构建时间计算书面要约的有效期下限（GPL 要求至少三年）。"""
    try:
        moment = datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise AppBuildError(f"generated_at 格式不正确：{generated_at}") from exc
    try:
        later = moment.replace(year=moment.year + 3)
    except ValueError:  # 2 月 29 日
        later = moment.replace(year=moment.year + 3, day=28)
    return later.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_source_offer(*, qemu_version: str | None, formula_version: str | None,
                       generated_at: str,
                       source_description: str | None = None) -> tuple[dict[str, Any], str]:
    """生成 QEMU 对应源码的书面要约（GPL-2.0 §3）与机器可读元数据。

    源码归档哈希必须与随包二进制版本匹配；未登记的版本无法编造哈希，直接失败。
    """
    _expect(qemu_version, "无法确定 QEMU 版本，不能生成源码书面要约。")
    sha256 = QEMU_SOURCE_SHA256.get(qemu_version)
    _expect(sha256,
            f"QEMU {qemu_version} 的对应源码 SHA-256 未登记（见 QEMU_SOURCE_SHA256）："
            "请先核实 download.qemu.org 上的归档并登记后再构建，不得编造哈希。")
    url = QEMU_SOURCE_URL_TEMPLATE.format(version=qemu_version)
    valid_until = _plus_three_years(generated_at)
    meta = {
        "qemu_version": qemu_version,
        "url": url,
        "sha256": sha256,
        "source_formula": source_description or f"Homebrew qemu {formula_version or '?'}",
        "valid_until": valid_until,
        "text_file": SOURCE_OFFER_REL,
    }
    lines = [
        "# QEMU 对应源码书面要约（GPL-2.0 §3）",
        "",
        f"本 App 随包分发 QEMU {qemu_version} 的二进制（qemu-system-aarch64、qemu-system-x86_64、",
        "qemu-img 及其非系统动态库闭包、firmware/ROM/keymaps）。",
        "",
        "依据 GNU GPL 第 2 版第 3 节，CTFLab 项目承诺：自本 App 分发之日起三年内",
        f"（至 {valid_until}），任何收到本 App 的第三方均可索取上述组件的完整对应源码。",
        "",
        f"- 对应源码归档：{url}",
        f"- 归档 SHA-256：`{sha256}`",
        f"- 随包二进制版本：{qemu_version}（{meta['source_formula']}）",
        "- 构建配方：`--target-list=aarch64-softmmu,x86_64-softmmu --enable-hvf --enable-cocoa",
        "  --enable-spice --enable-spice-protocol --enable-slirp --disable-pvg`；第三方动态库来自",
        "  Homebrew keg，版本和许可证文本记录在 `SBOM.json`。",
        "- 获取方式：通过 CTFLab 源码仓库（私有镜像 zhangpu1211/ctf-lab）的联系渠道提出请求；",
        "  我们按 GPL 要求提供源码（下载链接、介质或成本价复制）。",
        "",
        "该要约不可撤回，且适用于所有收到本 App 的第三方。",
        "",
    ]
    return meta, "\n".join(lines)


def sign_level_from_identity(identity: str | None) -> str:
    if identity is None or identity == "-":
        return "ad-hoc"
    if "Developer ID Application" in identity:
        return "developer-id"
    return "custom"


def list_codesign_identities() -> list[str]:
    result = _run_tool(["security", "find-identity", "-v", "-p", "codesigning"], check=False)
    return re.findall(r'"([^"]+)"', result.stdout)


def codesign_path(path: Path, identity: str, entitlements_path: Path | None = None) -> None:
    _expect(shutil.which("codesign"), "需要 macOS codesign 来签名。")
    command = ["codesign", "--force", "--sign", identity]
    if identity == "-":
        command.append("--timestamp=none")
    if entitlements_path is not None:
        command += ["--entitlements", str(entitlements_path)]
    command.append(str(path))
    _run_tool(command)


def read_entitlements(path: Path) -> dict[str, Any] | None:
    """读取 Mach-O 的 entitlements；没有则返回 None（HVF 依赖 com.apple.security.hypervisor）。"""
    result = _run_tool(["codesign", "-d", "--entitlements", ":-", str(path)], check=False)
    text = result.stdout or ""
    if "<plist" not in text:
        return None
    try:
        parsed = plistlib.loads(text.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001  损坏的 entitlement 不能静默当成“不存在”
        raise AppBuildError(f"无法解析 {path.name} 的 entitlements：{exc}") from exc
    _expect(isinstance(parsed, dict), f"{path.name} 的 entitlements 不是字典。")
    return parsed


def entitlement_record(entitlements: dict[str, Any]) -> dict[str, Any]:
    """生成不暴露 entitlement 值的可复核摘要；校验时仍比较完整值。"""
    payload = plistlib.dumps(entitlements, fmt=plistlib.FMT_BINARY, sort_keys=True)
    return {
        "keys": sorted(entitlements),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def sign_with_entitlements(path: Path, identity: str, entitlements: dict[str, Any] | None) -> None:
    """重签名时保留源二进制的 entitlements（否则 HVF/虚拟化能力会丢失）。"""
    if not entitlements:
        codesign_path(path, identity)
        return
    handle = tempfile.NamedTemporaryFile("wb", suffix=".plist", delete=False)
    try:
        handle.write(plistlib.dumps(entitlements))
        handle.close()
        codesign_path(path, identity, entitlements_path=Path(handle.name))
    finally:
        Path(handle.name).unlink(missing_ok=True)


def codesign_verify(app: Path) -> dict[str, Any]:
    """按实际签名级别记录 codesign 校验结果（不得把 ad-hoc 写成 Developer ID 或公证）。"""
    verify = _run_tool(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)],
                       check=False)
    details = _run_tool(["codesign", "-dvv", str(app)], check=False)
    text = details.stdout + details.stderr
    if "Signature=adhoc" in text:
        level = "ad-hoc"
    elif "Authority=Developer ID Application" in text:
        level = "developer-id"
    elif "code object is not signed at all" in text:
        level = "unsigned"
    elif verify.returncode == 0:
        level = "custom"
    else:
        level = "unsigned"
    return {
        "level": level,
        "verify_returncode": verify.returncode,
        "verify_output": (verify.stderr or verify.stdout).strip().splitlines()[-4:],
        "notarized": False,
        "notarization_status": "未验证（本轮未执行公证；需要既有 Keychain Profile 与用户明确授权）",
    }


# --------------------------------------------------------------------------- app 构建

def _write_launcher(path: Path) -> None:
    path.write_text(LAUNCHER_TEMPLATE, encoding="utf-8")
    path.chmod(0o755)


def _info_plist(version: str) -> dict[str, Any]:
    return {
        "CFBundleDevelopmentRegion": "zh_CN",
        "CFBundleExecutable": GUI_EXECUTABLE,
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "CTFLab",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        # GUI 与随包 QEMU/SPICE 运行时统一以 macOS 26.0 为最低版本；让 Finder 在启动前
        # 给出正确兼容性判断，避免进入 dyld 才失败。
        "LSMinimumSystemVersion": MIN_BUNDLED_MACOS,
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.developer-tools",
    }


def _copy_ctflab_sources(source_root: Path, destination: Path) -> list[str]:
    """把仓库 tools/ 镜像进 app（结构与仓库一致，运行时的 PROJECT_ROOT 推导无需改动）。"""
    import ctflab_package  # noqa: PLC0415

    copied: list[str] = []
    rel_files = list(ctflab_package.RELEASE_TOOL_FILES)
    for rel in rel_files:
        source = source_root / rel
        _expect(source.is_file(), f"缺少源文件：{source}")
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(rel)
    for rel_root in ("tools/ctflab_profiles", "tools/guest_fixes", GUI_SOURCE_DIR):
        source_dir = source_root / rel_root
        if not source_dir.is_dir():
            continue
        for path in sorted(source_dir.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(source_root).as_posix()
            if ctflab_package.forbidden_reason(rel):
                continue
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied.append(rel)
    readme = source_root / "README.md"
    if readme.is_file():
        shutil.copy2(readme, destination / "README.md")
        copied.append("README.md")
    return copied


def build_gui_executable(source_root: Path, target: Path, *,
                         swiftc: str | None = None,
                         prebuilt: Path | None = None) -> dict[str, Any]:
    """把 `gui/` 下的 SwiftUI 源码编译成 app 的原生入口（或复制预编译产物）。

    没有 swiftc 时直接失败（不回退到脚本入口）：图形入口是交付形态的一部分。
    """
    if prebuilt is not None:
        _expect(prebuilt.is_file(), f"预编译 GUI 可执行文件不存在：{prebuilt}")
        shutil.copy2(prebuilt, target)
        target.chmod(0o755)
        return {"path": str(target), "source": "prebuilt-injected", "swift_version": None}

    compiler = swiftc or shutil.which("swiftc")
    _expect(compiler, "缺少 swiftc（Xcode 命令行工具）：构建图形入口需要它；不生成半成品，构建停止。")
    sources = [source_root / GUI_SOURCE_DIR / name for name in GUI_SOURCES]
    for source in sources:
        _expect(source.is_file(), f"缺少 GUI 源文件：{source}")
    command = [compiler, "-O", "-target", GUI_TARGET, "-parse-as-library",
               "-o", str(target), *[str(source) for source in sources]]
    # CommandLineTools/Swift 在不同小版本间会拒绝复用默认 clang module cache；构建使用
    # 本次临时、可写的缓存目录，避免把用户的 ~/.cache 权限或旧 SDK 缓存当成项目失败。
    cache_dir = Path(tempfile.mkdtemp(prefix="ctflab-swift-cache-"))
    build_env = os.environ.copy()
    build_env["CLANG_MODULE_CACHE_PATH"] = str(cache_dir)
    try:
        result = _run_tool(command, check=False, env=build_env)
        _expect(result.returncode == 0,
                "GUI 编译失败：" + (result.stderr or result.stdout).strip()[:800])
        target.chmod(0o755)
        version_line = _run_tool([compiler, "--version"], check=False,
                                 env=build_env).stdout.strip().splitlines()
    finally:
        shutil.rmtree(cache_dir, ignore_errors=True)
    return {"path": str(target), "source": "swiftc",
            "swift_version": version_line[0] if version_line else None,
            "sources": [f"{GUI_SOURCE_DIR}/{name}" for name in GUI_SOURCES]}


def _sign_macho_files(runtime_bin: Path, runtime_lib: Path, identity: str,
                      entitlements: dict[str, dict[str, Any]] | None = None,
                      extra_roots: Iterable[Path] = ()) -> list[str]:
    entitlements = entitlements or {}
    signed: list[str] = []
    for directory in (runtime_lib, runtime_bin):
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and not path.name.startswith("."):
                sign_with_entitlements(path, identity, entitlements.get(path.name))
                signed.append(str(path))
    # 额外子树（内置 Python 运行时）：递归签名所有 Mach-O，否则外层
    # `codesign --verify --deep --strict` 会因嵌套未签名代码失败。
    for root in extra_roots:
        for path in iter_macho_files(Path(root)):
            sign_with_entitlements(path, identity, entitlements.get(path.name))
            signed.append(str(path))
    return signed


def _rewrite_install_names(binaries: Iterable[Path], libs: dict[str, Path]) -> None:
    """把依赖改写为 @loader_path 相对引用，并设置 dylib 自身 install id。"""
    lib_paths = list(libs.values())
    for lib in lib_paths:
        _run_tool(["install_name_tool", "-id", f"@loader_path/{lib.name}", str(lib)])
    for binary in binaries:
        for dep in otool_deps(binary):
            if is_system_library(dep):
                continue
            name = resolve_dep(dep, binary).name
            _run_tool(["install_name_tool", "-change", dep, f"@loader_path/../lib/{name}", str(binary)])
    for lib in lib_paths:
        for dep in otool_deps(lib):
            if is_system_library(dep) or dep.startswith("@loader_path/"):
                continue
            target = resolve_dep(dep, lib)
            if target == lib:
                continue
            _run_tool(["install_name_tool", "-change", dep, f"@loader_path/{target.name}", str(lib)])
    # 删除指向宿主安装位置的 LC_RPATH，避免加载器再回退到 /opt/homebrew 等目录。
    for path in [*lib_paths, *binaries]:
        for rpath in otool_rpaths(path):
            if rpath.startswith("@") or any(p.search(rpath) for p in FORBIDDEN_BINARY_PATTERNS):
                _run_tool(["install_name_tool", "-delete_rpath", rpath, str(path)], check=False)


def _iter_manifest_files(app_root: Path) -> list[Path]:
    """清单覆盖除代码签名自身产物之外的所有文件。

    例外：主可执行文件（Contents/MacOS/CTFLabGUI）不在清单内——bundle 签名会重写它的
    签名节，哈希必然变化；它的完整性由代码签名（codesign --verify --deep --strict）保证。
    """
    files: list[Path] = []
    main_executable = f"Contents/MacOS/{GUI_EXECUTABLE}"
    for path in sorted(app_root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(app_root).as_posix()
        if rel.startswith(SIGNATURE_DIR_REL + "/") or rel == main_executable:
            continue
        files.append(path)
    return files


def _qemu_version(binary: Path) -> str | None:
    result = _run_tool([str(binary), "--version"], check=False)
    first = (result.stdout or result.stderr).strip().splitlines()
    return first[0] if first else None


def _binary_arch(path: Path) -> str | None:
    result = _run_tool(["file", "-b", str(path)], check=False)
    text = result.stdout.strip()
    return text.split(":")[0] if text else None


def build_sbom(*, version: str, generated_at: str, qemu_root: Path, libs: dict[str, Path],
               qemu_share: list[str], license_index: dict[str, list[str]],
               license_texts_complete: bool, vendored_index: dict[str, list[str]] | None = None,
               source_offer: dict[str, Any] | None = None,
               python_meta: dict[str, Any] | None = None,
               pyyaml_meta: dict[str, Any] | None = None,
               spice_client: Path | None = None) -> dict[str, Any]:
    import ctflab_package  # noqa: PLC0415  函数内导入，避免循环依赖

    vendored_index = vendored_index or {}
    qemu_source = qemu_source_description(qemu_root)
    qemu_bins = []
    for name in QEMU_BINARIES:
        source = qemu_root / "bin" / name
        qemu_bins.append({
            "file": f"{RUNTIME_REL}/bin/{name}",
            "version": _qemu_version(source),
            "arch": _binary_arch(source),
            "sha256": sha256_file(source),
            "license": KNOWN_LICENSES["qemu"],
            "bundled": True,
            # SBOM 记录可复现的来源类别与版本，不写入构建机绝对路径。
            "source": qemu_source,
        })
    dylib_components = []
    for name, source in sorted(libs.items()):
        formula = _formula_of(source) or "unknown"
        if license_index.get(formula):
            text_status = "present"
        elif vendored_index.get(formula):
            text_status = "vendored"
        else:
            text_status = "missing-in-keg"
        dylib_components.append({
            "file": f"{RUNTIME_REL}/lib/{name}",
            "formula": formula,
            "version": _formula_version(formula) if formula != "unknown" else None,
            "arch": _binary_arch(source),
            "sha256": sha256_file(source),
            "license": KNOWN_LICENSES.get(formula, f"unknown（见 licenses/{formula}/ 内文本）"),
            "license_text_status": text_status,
            "bundled": True,
            "source": f"Homebrew formula {formula}",
        })
    components = [{
        "name": "ctflab",
        "type": "application",
        "role": "runtime",
        "version": version,
        "license": ctflab_package.PROJECT_LICENSE,
        "license_detail": ctflab_package.PROJECT_LICENSE_DETAIL.replace(
            "随包根目录 LICENSE", f"`{LICENSE_REL}`"),
        "bundled": True,
    }, {
        "name": "QEMU",
        "type": "application",
        "role": "runtime",
        "version": _qemu_version(qemu_root / "bin" / "qemu-system-aarch64"),
        "license": KNOWN_LICENSES["qemu"],
        "bundled": True,
        "source": qemu_source,
        "binaries": qemu_bins,
        "runtime_assets": {
            "share_files": qemu_share,
            "note": "firmware/ROM/keymaps 属于 QEMU 运行时数据；EDK2 固件为 "
                    "BSD-2-Clause-Patent（见 licenses/edk2/）。",
        },
        "distribution_obligations": [
            "QEMU 为 GPL-2.0-only：随二进制分发须向接收者提供完整对应源码或书面要约；"
            f"本 app 未随附源码，已随包提供书面要约（{SOURCE_OFFER_REL}，GPL-2.0 §3），"
            "指向 qemu-<version> 上游归档与 SHA-256，有效期至少三年。",
            "EDK2 固件（edk2-*.fd、efi-*.rom）为 BSD-2-Clause-Patent；许可证文本见 licenses/edk2/。",
            "捆绑的 LGPL 组件（glib/gnutls/libssh/libidn2/nettle 等）以独立动态库形式随包，"
            "接收者可用兼容版本替换以实现重新链接；许可证文本随包提供。",
        ],
    }]
    components.extend(dylib_components)
    if spice_client is not None:
        client_formula = _formula_of(spice_client) or "spice-gtk"
        components.append({
            "name": "spicy",
            "type": "application",
            "role": "display-client",
            "version": _formula_version(client_formula),
            "license": KNOWN_LICENSES["spice-gtk"],
            "bundled": True,
            "source": f"Homebrew formula {client_formula}",
            "binaries": [{
                "file": f"{RUNTIME_REL}/bin/{SPICE_CLIENT_NAME}",
                "version": _formula_version(client_formula),
                "arch": _binary_arch(spice_client),
                "sha256": sha256_file(spice_client),
                "license": KNOWN_LICENSES["spice-gtk"],
                "bundled": True,
            }],
        })
    _expect(python_meta, "构建 SBOM 需要内置 Python 运行时元数据。")
    _expect(pyyaml_meta, "构建 SBOM 需要 PyYAML 元数据。")
    components.append({
        "name": "CPython",
        "type": "application",
        "role": "runtime",
        "version": python_meta["version"],
        "license": KNOWN_LICENSES["python"],
        "license_text_status": "present",
        "bundled": True,
        "directory": python_meta["root"],
        "source": python_meta["source"],
        "archive_sha256": python_meta.get("archive_sha256"),
        "pruned": python_meta.get("pruned", []),
        "note": "随包解释器与标准库；裁剪清单记录在本组件 pruned 字段，逐文件哈希见 MANIFEST.json。",
    })
    components.append({
        "name": "PyYAML",
        "type": "library",
        "role": "runtime",
        "version": pyyaml_meta["version"],
        "license": KNOWN_LICENSES["pyyaml"],
        "license_text_status": "present",
        "bundled": True,
        "directory": pyyaml_meta["package_rel"],
        "source": "PyPI wheel（原始文件未修改）",
        "wheel_sha256": pyyaml_meta.get("wheel_sha256"),
    })
    return {
        "schema": 1,
        "format": "ctflab-app-sbom",
        "generated_at": generated_at,
        "components": components,
        "license_texts_complete": license_texts_complete,
        "source_offer": source_offer,
        "notes": [
            "bundled=true 表示该组件实际位于 app 内；哈希为打包时值（见 MANIFEST.json）。",
            "许可证标识来自 Homebrew formula 声明与随包文本，未做法律审查；"
            "license_text_status=vendored 表示文本取自仓库 tools/licenses/（见 PROVENANCE.md）。",
            f"项目自身许可证为 {ctflab_package.PROJECT_LICENSE}，全文随包提供（{LICENSE_REL}）。",
        ],
    }


def third_party_markdown(sbom: dict[str, Any]) -> str:
    import ctflab_package  # noqa: PLC0415  函数内导入，避免循环依赖

    lines = [
        "# 第三方组件与许可证（CTFLab.app）",
        "",
        f"生成时间：{sbom['generated_at']}；机器可读版本见 `SBOM.json`。",
        "",
        "| 组件 | 版本 | 许可证 | 说明 |",
        "|---|---|---|---|",
    ]
    for component in sbom["components"]:
        if component.get("name") == "QEMU":
            for binary in component["binaries"]:
                lines.append(f"| {binary['file'].split('/')[-1]} | {binary['version']} | "
                             f"{binary['license']} | {binary['source']} |")
            continue
        if component.get("file"):
            lines.append(f"| {component['file'].split('/')[-1]} | {component.get('version') or '-'} | "
                         f"{component['license']} | {component['source']} |")
        else:
            detail = component.get("source") or component.get("license_detail", "")
            lines.append(f"| {component['name']} | {component.get('version')} | {component['license']} | "
                         f"{detail} |")
    lines += ["", "## QEMU / GPL 分发义务（单独列出）", ""]
    for obligation in sbom["components"][1]["distribution_obligations"]:
        lines.append(f"- {obligation}")
    lines += [
        "",
        "## 项目自身许可证",
        "",
        f"CTFLab 自身代码以 `{ctflab_package.PROJECT_LICENSE}` 许可证发布，全文随包提供"
        f"（`{LICENSE_REL}`）。许可证文本完整性："
        f"{'完整' if sbom['license_texts_complete'] else '不完整（见 SBOM.json 中 license_text_status=missing-in-keg 的条目）'}。",
        "",
    ]
    return "\n".join(lines)


def build_app(
    out_dir: Path,
    *,
    version: str | None = None,
    source_root: Path | None = None,
    qemu_root: Path | None = None,
    spice_client: Path | None = None,
    python_runtime: Path | None = None,
    python_runtime_sha256: str | None = None,
    pyyaml_source: Path | None = None,
    pyyaml_sha256: str | None = None,
    generated_at: str | None = None,
    sign_identity: str | None = None,
    allow_incomplete_license_texts: bool = False,
    unsigned: bool = False,
    share_files: Iterable[str] | None = None,
    gui_binary: Path | None = None,
    swiftc: str | None = None,
) -> dict[str, Any]:
    """构建 `CTFLab.app`；排他发布，目标已存在时拒绝覆盖。

    必填 `python_runtime`（python-build-standalone 的 `.tar.gz` 或解包目录）与
    `pyyaml_source`（PyPI wheel 或解包目录）：app 必须自带解释器与 PyYAML，
    否则学生机仍需系统 Python/pip，违背交付目标；缺参直接失败，不回退。
    """
    source_root = Path(source_root or DEFAULT_SOURCE_ROOT)
    runtime_version = ctflab_version()
    version = str(runtime_version if version is None else version)
    _expect(version == runtime_version,
            f"app 版本必须与 CTFLAB_VERSION 一致：当前 {runtime_version}，请求 {version}")
    generated_at = generated_at or now_iso()
    qemu_root = Path(qemu_root) if qemu_root else detect_qemu_root()
    if spice_client is not None:
        spice_client = Path(spice_client).expanduser().resolve()
        _expect(spice_client.is_file() and os.access(spice_client, os.X_OK),
                f"SPICE 客户端不存在或不可执行：{spice_client}")
    _expect(python_runtime,
            "缺少 --python-runtime：app 必须内置 Python 运行时（python-build-standalone "
            "install_only_stripped 的 .tar.gz 或解包目录），不回退系统 Python。")
    _expect(pyyaml_source,
            "缺少 --pyyaml：app 必须内置 PyYAML（PyPI wheel 或解包目录），"
            "否则接收者仍需联网 pip install。")

    if sign_identity is not None and sign_identity != "-":
        available = list_codesign_identities()
        _expect(sign_identity in available,
                f"本机未找到签名身份：{sign_identity}（可用：{available or '无'}）；"
                "不伪造签名结论，构建停止。")

    out_dir = Path(out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    final_path = out_dir / APP_BUNDLE_NAME
    sidecar_path = out_dir / f"{APP_BUNDLE_NAME}.sha256"
    _expect(not os.path.lexists(final_path), f"目标已存在，拒绝覆盖：{final_path}")
    _expect(not os.path.lexists(sidecar_path), f"旁车文件已存在，拒绝覆盖：{sidecar_path.name}")

    temp_dir = Path(tempfile.mkdtemp(prefix=f".{APP_BUNDLE_NAME}.", suffix=".tmp", dir=str(out_dir)))
    temp_app = temp_dir / APP_BUNDLE_NAME
    try:
        contents = temp_app / "Contents"
        resources = contents / "Resources"
        (contents / "MacOS").mkdir(parents=True)
        resources.mkdir(parents=True)
        runtime = resources / "runtime"
        runtime_bin = runtime / "bin"
        runtime_lib = runtime / "lib"
        runtime_share = runtime / "share" / "qemu"
        runtime_bin.mkdir(parents=True)
        runtime_lib.mkdir(parents=True)
        runtime_share.mkdir(parents=True)

        # 1) Info.plist：CLI 启动器（GUI 调用 + 兼容名）与原生图形入口
        (contents / "Info.plist").write_bytes(plistlib.dumps(_info_plist(version)))
        (resources / "bin").mkdir(parents=True, exist_ok=True)
        _write_launcher(contents / "Resources" / "bin" / CLI_EXECUTABLE)
        _write_launcher(contents / "Resources" / "bin" / APP_EXECUTABLE)
        gui_meta = build_gui_executable(source_root, contents / "MacOS" / GUI_EXECUTABLE,
                                        swiftc=swiftc, prebuilt=gui_binary)
        if unsigned:
            # 工具链会给 Mach-O 自动加 ad-hoc 签名；诊断用的 unsigned 构建必须真的没有签名。
            _run_tool(["codesign", "--remove-signature", str(contents / "MacOS" / GUI_EXECUTABLE)],
                      check=False)

        # 2) CTFLab 源码镜像
        _copy_ctflab_sources(source_root, resources / "ctflab")

        # 3) QEMU 程序与可选 SPICE 客户端（同时采集源二进制 entitlements：HVF 等能力不能丢）
        source_entitlements: dict[str, dict[str, Any]] = {}
        runtime_binary_sources: dict[str, Path] = {
            name: qemu_root / "bin" / name for name in QEMU_BINARIES
        }
        if spice_client is not None:
            runtime_binary_sources[SPICE_CLIENT_NAME] = spice_client
        for name, source in runtime_binary_sources.items():
            _expect(source.is_file(), f"缺少 QEMU 程序：{source}")
            shutil.copy2(source, runtime_bin / name)
            (runtime_bin / name).chmod(0o755)
            found = read_entitlements(source)
            if found:
                source_entitlements[name] = found
        copied_share = copy_qemu_share(qemu_root, runtime_share, share_files)

        # 4) 动态库闭包与 install_name 改写
        libs_sources = collect_dylib_closure([runtime_bin / name for name in runtime_binary_sources])
        for name, source in sorted(libs_sources.items()):
            shutil.copy2(source, runtime_lib / name)
            (runtime_lib / name).chmod(0o755)
            found = read_entitlements(source)
            if found:
                source_entitlements[name] = found
        libs_targets = {name: runtime_lib / name for name in libs_sources}
        _rewrite_install_names([runtime_bin / name for name in runtime_binary_sources], libs_targets)

        # 4.5) 内置 Python 运行时与 PyYAML（学生机零 Python 依赖的硬前提）
        licenses_dir = resources / "licenses"
        licenses_dir.mkdir()
        runtime_python = runtime / "python"
        python_meta = copy_python_runtime(python_runtime, runtime_python,
                                          expected_sha256=python_runtime_sha256)
        python_meta["root"] = PYTHON_RUNTIME_REL
        site_candidates = sorted(runtime_python.glob("lib/python3.*/site-packages"))
        _expect(len(site_candidates) == 1,
                f"内置 Python 缺少唯一的 lib/python3.*/site-packages 目录：{runtime_python}")
        site_packages = site_candidates[0]
        pyyaml_meta = copy_pyyaml(pyyaml_source, site_packages, licenses_dir / "pyyaml",
                                  expected_sha256=pyyaml_sha256)
        pyyaml_meta["package_rel"] = (site_packages / "yaml").relative_to(temp_app).as_posix()

        # 5) 签名 Mach-O（install_name_tool 之后必须重新签名；没有身份时 ad-hoc）
        if not unsigned:
            codesign_path(contents / "MacOS" / GUI_EXECUTABLE, sign_identity or "-")
            _sign_macho_files(runtime_bin, runtime_lib, sign_identity or "-", source_entitlements,
                              extra_roots=[runtime_python])
            # 断言：源二进制的能力（例如 com.apple.security.hypervisor）必须在副本上保留，
            # 否则 HVF 会在启动时拒绝创建 VGIC（HV_NO_DEVICE）。
            for name, expected in source_entitlements.items():
                directory = runtime_bin if name in QEMU_BINARIES else runtime_lib
                actual = read_entitlements(directory / name) or {}
                _expect(actual == expected,
                        f"{name} 重签名后的 entitlements 与源二进制不一致"
                        "（键和值都必须原样保留，虚拟化能力不能被降级）")

        bundled_entitlements: dict[str, dict[str, Any]] = {}
        for name in source_entitlements:
            directory = runtime_bin if name in runtime_binary_sources else runtime_lib
            actual = read_entitlements(directory / name)
            if actual:
                bundled_entitlements[name] = actual

        # 6) 许可证文本与合规文件（licenses/ 已在 4.5 创建：PyYAML 许可证已就位）
        import ctflab_package  # noqa: PLC0415  函数内导入，避免循环依赖

        license_index: dict[str, list[str]] = {}
        vendored_index: dict[str, list[str]] = {}
        formulas = sorted({_formula_of(source) or "unknown" for source in libs_sources.values()}
                          | {"qemu", "edk2"}
                          | ({_formula_of(spice_client) or "spice-gtk"}
                             if spice_client is not None else set()))
        missing: list[str] = []
        for formula in formulas:
            if formula == "edk2":
                target_dir = licenses_dir / "edk2"
                target_dir.mkdir()
                shutil.copy2(runtime_share / "edk2-licenses.txt", target_dir / "edk2-licenses.txt")
                license_index["edk2"] = ["edk2-licenses.txt"]
                continue
            texts = collect_license_texts(formula)
            source_kind = "keg"
            if not texts:
                texts = collect_vendored_license_texts(source_root, formula)
                source_kind = "vendored"
            if not texts:
                missing.append(formula)
                license_index[formula] = []
                continue
            target_dir = licenses_dir / formula
            target_dir.mkdir()
            names: list[str] = []
            for name, path in texts:
                shutil.copy2(path, target_dir / name)
                names.append(name)
            if source_kind == "vendored":
                vendored_index[formula] = names
            else:
                license_index[formula] = names
        _expect(not missing or allow_incomplete_license_texts,
                "以下随包组件的许可证文本在 Homebrew keg 与仓库 tools/licenses/ 中都不存在，"
                f"且未使用 --allow-incomplete-license-texts：{', '.join(missing)}；"
                "分发义务无法确认时停止，不猜测。")

        # 内置 Python 的 PSF 许可证文本（发行版自带，原样复制）
        python_licenses = sorted((runtime_python / "lib").glob("python3.*/LICENSE.txt"))
        _expect(len(python_licenses) == 1,
                f"内置 Python 缺少唯一的许可证文本 lib/python3.*/LICENSE.txt：{runtime_python}")
        target_dir = licenses_dir / "python"
        target_dir.mkdir()
        shutil.copy2(python_licenses[0], target_dir / "LICENSE.txt")

        # 项目自身许可证与 QEMU 源码书面要约（GPL-2.0 §3）随包分发
        project_license = source_root / "LICENSE"
        _expect(project_license.is_file(),
                f"缺少项目 LICENSE（应为 {ctflab_package.PROJECT_LICENSE} 全文）：{project_license}")
        shutil.copy2(project_license, resources / "LICENSE")
        offer_meta, offer_text = build_source_offer(
            qemu_version=_qemu_semver(_qemu_version(qemu_root / "bin" / "qemu-system-aarch64")),
            formula_version=_formula_version("qemu"),
            generated_at=generated_at,
            source_description=qemu_source_description(qemu_root))
        (resources / "SOURCE_OFFER.md").write_text(offer_text, encoding="utf-8")

        # 7) SBOM / 许可证说明 / MANIFEST（在签名后计算最终文件哈希）
        sbom = build_sbom(version=version, generated_at=generated_at, qemu_root=qemu_root,
                          libs=libs_sources, qemu_share=copied_share,
                          license_index=license_index, license_texts_complete=not missing,
                          vendored_index=vendored_index, source_offer=offer_meta,
                          python_meta=python_meta, pyyaml_meta=pyyaml_meta,
                          spice_client=spice_client)
        (resources / "SBOM.json").write_text(json.dumps(sbom, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
        (resources / "THIRD_PARTY_LICENSES.md").write_text(third_party_markdown(sbom), encoding="utf-8")

        signature_plan = {
            "requested": "unsigned" if unsigned else sign_level_from_identity(sign_identity),
            "identity": None if (unsigned or not sign_identity) else sign_identity,
            "notarized": False,
            "notarization_status": "未验证（需要既有 Keychain Profile 与用户明确授权）",
        }
        manifest = {
            "schema": 1,
            "format": "ctflab-app",
            "name": "CTFLab",
            "version": version,
            "generated_at": generated_at,
            "bundle_identifier": BUNDLE_IDENTIFIER,
            "entrypoint": f"Contents/MacOS/{GUI_EXECUTABLE}",
            "gui": {
                "executable": f"Contents/MacOS/{GUI_EXECUTABLE}",
                "cli": LAUNCHER_REL,
                "cli_compat": LAUNCHER_COMPAT_REL,
                "sources": gui_meta.get("sources", []),
                "swift_version": gui_meta.get("swift_version"),
                "source": gui_meta.get("source"),
                "note": "原生 SwiftUI 入口（AppKit 仅用于目录选择）；不依赖 Electron/Node/浏览器。",
            },
            "runtime": {
                "root": RUNTIME_REL,
                "minimum_macos": MIN_BUNDLED_MACOS,
                "dylibs": sorted(libs_sources),
                "binaries": list(runtime_binary_sources),
                "spice_client": (f"{RUNTIME_REL}/bin/{SPICE_CLIENT_NAME}"
                                  if spice_client is not None else None),
                "share_files": copied_share,
                "qemu_version": _qemu_version(qemu_root / "bin" / "qemu-system-aarch64"),
                "source": qemu_source_description(qemu_root),
                "entitlements": {
                    name: entitlement_record(value)
                    for name, value in sorted(bundled_entitlements.items())
                },
                "python": {
                    "root": PYTHON_RUNTIME_REL,
                    "bin": f"{PYTHON_RUNTIME_REL}/bin/python3",
                    "version": python_meta["version"],
                    "source": python_meta["source"],
                    "archive_sha256": python_meta.get("archive_sha256"),
                    "symlinks_dereferenced": python_meta.get("symlinks_dereferenced"),
                    "pruned": python_meta.get("pruned", []),
                    "pyyaml": {
                        "version": pyyaml_meta["version"],
                        "wheel_sha256": pyyaml_meta.get("wheel_sha256"),
                        "package": pyyaml_meta["package_rel"],
                    },
                },
            },
            "signature": dict(signature_plan),
            "signature_covers": [f"Contents/MacOS/{GUI_EXECUTABLE}"],
            "license": {
                "status": ctflab_package.PROJECT_LICENSE,
                "project_license_file": LICENSE_REL,
                "source_offer": offer_meta,
                "distribution_blockers": (
                    ["许可证文本不完整：" + ", ".join(missing)] if missing else []
                ),
            },
            "files": [
                {"path": path.relative_to(temp_app).as_posix(), "sha256": sha256_file(path),
                 "size": path.stat().st_size}
                for path in _iter_manifest_files(temp_app)
            ],
            "notes": [
                "运行状态不写入 app：状态、镜像、overlay、日志都在 ~/Library/Application Support/CTFLab。",
                "app 内不包含任何虚拟磁盘、凭据、日志或 PCAP。",
                "签名与公证分级见 signature 字段；未执行公证时不得宣称已公证。",
            ],
        }
        (resources / "MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # 8) 打包后自检 → 签名 bundle → 发布（发布前不改动任何内容文件）
        problems = verify_runtime_references(temp_app)
        _expect(not problems, "打包后仍存在禁止引用：\n" + "\n".join(problems))
        signature = {"level": "unsigned", "verify_returncode": None, "verify_output": [],
                     "notarized": False, "notarization_status": signature_plan["notarization_status"]}
        if not unsigned:
            codesign_path(temp_app, sign_identity or "-")
            signature = codesign_verify(temp_app)

        # 旁车内容在临时 app 上计算；目录与旁车均排他发布。若旁车发生外部竞态，
        # 回滚本次发布的 app，不能留下一个没有可信旁车的半成品。
        tree_digest = app_tree_hash(temp_app)
        manifest_digest = sha256_file(temp_app / MANIFEST_REL)
        sidecar_temp = temp_dir / f".{APP_BUNDLE_NAME}.sha256.tmp"
        sidecar_temp.write_text(
            f"{tree_digest}  {APP_BUNDLE_NAME}\n{manifest_digest}  {APP_BUNDLE_NAME}/{MANIFEST_REL}\n",
            encoding="utf-8")
        published_app = False
        try:
            _exclusive_publish_directory(temp_app, final_path)
            published_app = True
            _exclusive_publish_file(sidecar_temp, sidecar_path)
        except Exception:
            if published_app and final_path.is_dir() and not final_path.is_symlink():
                shutil.rmtree(final_path)
            raise
        sidecar_temp.unlink(missing_ok=True)
        os.rmdir(temp_dir)
        return {"app": str(final_path), "manifest": manifest, "sbom": sbom,
                "signature": signature, "missing_license_texts": missing,
                "tree_sha256": tree_digest, "sidecar": str(sidecar_path)}
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def _exclusive_publish_directory(source: Path, destination: Path) -> None:
    """以平台提供的排他 rename 发布目录；目标并发出现时绝不覆盖。"""
    try:
        from ctflab_utm import PublishError, exclusive_rename  # noqa: PLC0415

        exclusive_rename(source, destination)
    except PublishError as exc:
        raise AppBuildError(str(exc)) from exc
    except OSError as exc:
        raise AppBuildError(f"排他发布 app 失败：{destination}（{exc}）") from exc


def _exclusive_publish_file(source: Path, destination: Path) -> None:
    """用硬链接创建最终旁车；创建本身即排他，不跟随既有符号链接。"""
    try:
        os.link(source, destination)
    except FileExistsError as exc:
        raise AppBuildError(f"旁车文件已存在（并发创建），拒绝覆盖：{destination.name}") from exc
    except OSError as exc:
        raise AppBuildError(f"排他发布旁车失败：{destination.name}（{exc}）") from exc


def verify_runtime_references(app: Path) -> list[str]:
    """检查 app 内 Mach-O 引用与 QEMU/客户端最低系统版本。

    内置动态库仍按依赖闭包检查；可执行入口另做 ``minos`` 守卫，因为 QEMU 直接
    使用新 SDK 的系统符号时，旧 macOS 会在 ``qemu-img info`` 阶段由 dyld 拒绝启动。
    """
    runtime = app / RUNTIME_REL
    problems: list[str] = []
    macho_files = [p for p in (runtime / "bin").iterdir() if p.is_file()]
    macho_files += [p for p in (runtime / "lib").iterdir() if p.is_file()]
    # 内置 Python 运行时：解释器与扩展模块同样纳入引用检查（递归、按 Mach-O 魔数筛选）。
    macho_files += iter_macho_files(runtime / "python")
    allowed_roots = [(runtime / "lib").resolve(), (runtime / "python").resolve()]
    for path in macho_files:
        if path.parent == runtime / "bin":
            minimum = macho_minimum_os(path)
            if minimum is None:
                problems.append(f"{path.name}: 无法读取 Mach-O 最低 macOS 版本")
            elif minimum > MIN_BUNDLED_MACOS_VERSION:
                problems.append(
                    f"{path.name}: 最低 macOS {macho_version_text(minimum)} 高于支持目标 {MIN_BUNDLED_MACOS}")
            # macOS 26 之前不存在 strchrnul；最低版本提升到 26 后该符号是合法依赖。
            if path.name in QEMU_BINARIES and MIN_BUNDLED_MACOS_VERSION < (26, 0):
                symbols = _run_tool(["nm", "-u", str(path)], check=False).stdout
                if "strchrnul" in symbols:
                    problems.append(f"{path.name}: 仍引用旧系统不存在的 strchrnul")
        for dep in otool_deps(path):
            if dep.startswith("@loader_path/"):
                target = (path.parent / dep[len("@loader_path/"):]).resolve()
                if not any(target.is_relative_to(root) for root in allowed_roots):
                    problems.append(f"{path.name}: 相对依赖指向 app 外：{dep}")
                elif not target.exists():
                    problems.append(f"{path.name}: 相对依赖缺失：{dep}")
                continue
            if is_system_library(dep):
                continue
            problems.append(f"{path.name}: 非系统依赖未相对化：{dep}")
        for hit in forbidden_binary_reference(path):
            problems.append(f"{path.name}: 残留禁止引用：{hit}")
    return problems


def app_tree_hash(app_path: Path) -> str:
    """app 全量文件树哈希（含 _CodeSignature）：用于“运行前后 app 不变”的比对。"""
    digest = hashlib.sha256()
    for path in sorted(app_path.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(app_path).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def verify_app(app_path: Path, *, check_signature: bool = True) -> dict[str, Any]:
    """校验 `CTFLab.app`：结构、Info.plist、清单哈希、运行时、禁止内容与签名分级。"""
    app_path = Path(app_path).expanduser()
    _expect(app_path.is_dir() and not app_path.is_symlink() and app_path.suffix == ".app",
            f"不是普通 .app 目录：{app_path}")
    for rel in (INFO_PLIST_REL, LAUNCHER_REL, MANIFEST_REL, SBOM_REL, THIRD_PARTY_REL,
                LICENSE_REL, SOURCE_OFFER_REL,
                f"Contents/MacOS/{GUI_EXECUTABLE}", LAUNCHER_COMPAT_REL,
                f"{CTFLAB_REL}/tools/ctflab.py", f"{RUNTIME_REL}/bin/qemu-img"):
        _expect((app_path / rel).exists(), f"app 缺少必需内容：{rel}")

    try:
        info = plistlib.loads((app_path / INFO_PLIST_REL).read_bytes())
        manifest = json.loads((app_path / MANIFEST_REL).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, plistlib.InvalidFileException) as exc:
        raise AppBuildError(f"app 元数据无法解析：{exc}") from exc
    _expect(isinstance(info, dict), "Info.plist 顶层必须是字典。")
    _expect(isinstance(manifest, dict), "MANIFEST.json 顶层必须是对象。")
    _expect(isinstance(manifest.get("version"), str), "MANIFEST.json 缺少有效 version。")
    _expect(isinstance(manifest.get("runtime"), dict), "MANIFEST.json 缺少有效 runtime。")
    _expect(isinstance(manifest.get("files"), list), "MANIFEST.json 缺少有效 files。")
    _expect(isinstance(manifest.get("license"), dict), "MANIFEST.json 缺少有效 license。")
    _expect(info.get("CFBundleExecutable") == GUI_EXECUTABLE,
            f"Info.plist 的 CFBundleExecutable 必须指向原生图形入口 {GUI_EXECUTABLE}。")
    _expect(info.get("CFBundleIdentifier") == BUNDLE_IDENTIFIER, "Info.plist 的 CFBundleIdentifier 不正确。")
    _expect(str(info.get("CFBundleShortVersionString")) == str(manifest["version"]),
            "Info.plist 版本与 MANIFEST 不一致。")
    _expect(str(info.get("LSMinimumSystemVersion")) == MIN_BUNDLED_MACOS,
            f"Info.plist 的 LSMinimumSystemVersion 必须为 {MIN_BUNDLED_MACOS}。")

    launcher = (app_path / LAUNCHER_REL).read_text(encoding="utf-8")
    for pattern in FORBIDDEN_BINARY_PATTERNS:
        _expect(not pattern.search(launcher), f"启动器包含禁止路径：{pattern.pattern}")
    _expect("CTFLAB_RUNTIME_ROOT" in launcher, "启动器必须导出 CTFLAB_RUNTIME_ROOT。")
    _expect("command -v python3" not in launcher,
            "启动器不得探测系统 Python（必须使用 app 内置解释器）。")
    _expect(f"{Path(PYTHON_RUNTIME_REL).name}/bin/python3" in launcher,
            f"启动器必须使用内置解释器（{PYTHON_RUNTIME_REL}/bin/python3）。")
    _expect("-B -s -E" in launcher,
            "启动器必须以 -B -s -E 调用内置解释器（禁止写字节码缓存、忽略用户 site 与环境变量）。")

    gui_binary = app_path / "Contents/MacOS" / GUI_EXECUTABLE
    _expect(gui_binary.is_file(), f"缺少图形入口：Contents/MacOS/{GUI_EXECUTABLE}")
    _expect(os.access(gui_binary, os.X_OK), "图形入口不可执行。")
    for dep in otool_deps(gui_binary):
        if is_system_library(dep):
            continue
        _expect(dep.startswith("@loader_path/") or dep.startswith("@rpath/"),
                f"图形入口含绝对路径依赖：{dep}")
    for hit in forbidden_binary_reference(gui_binary):
        raise AppBuildError(f"图形入口残留禁止引用：{hit}")
    gui_record = manifest.get("gui") or {}
    _expect(gui_record.get("executable") == f"Contents/MacOS/{GUI_EXECUTABLE}",
            "MANIFEST.gui.executable 与 Info.plist 主入口不一致。")
    _expect(gui_record.get("cli") == LAUNCHER_REL,
            f"MANIFEST.gui.cli 必须指向 CLI 启动器 {LAUNCHER_REL}。")
    _expect(gui_record.get("cli_compat") == LAUNCHER_COMPAT_REL,
            f"MANIFEST.gui.cli_compat 必须保留兼容名 {LAUNCHER_COMPAT_REL}。")

    for name in QEMU_BINARIES:
        binary = app_path / RUNTIME_REL / "bin" / name
        _expect(binary.is_file(), f"缺少 QEMU 程序：{name}")
        _expect(os.access(binary, os.X_OK), f"QEMU 程序不可执行：{name}")
    share_dir = app_path / RUNTIME_REL / "share" / "qemu"
    share_files = manifest["runtime"].get("share_files")
    _expect(isinstance(share_files, list) and all(isinstance(name, str) for name in share_files),
            "MANIFEST.runtime.share_files 必须是字符串数组。")
    for name in share_files:
        _expect((share_dir / name).is_file(), f"缺少运行时资源：{name}")
    _expect((share_dir / "keymaps").is_dir(), "缺少 keymaps 目录。")

    # 内置 Python 运行时与 PyYAML：学生机零依赖的硬前提，缺一即校验失败。
    python_section = manifest["runtime"].get("python")
    _expect(isinstance(python_section, dict), "MANIFEST.runtime.python 必须是对象。")
    python_bin = app_path / str(python_section.get("bin", ""))
    _expect(python_bin.is_file() and os.access(python_bin, os.X_OK),
            f"内置 Python 解释器缺失或不可执行：{python_section.get('bin')!r}")
    _expect(re.fullmatch(r"\d+\.\d+\.\d+", str(python_section.get("version", ""))),
            "MANIFEST.runtime.python.version 必须是 X.Y.Z。")
    _expect((app_path / str(python_section.get("root", ""))).is_dir(),
            "MANIFEST.runtime.python.root 必须是 app 内目录。")
    pyyaml_section = python_section.get("pyyaml")
    _expect(isinstance(pyyaml_section, dict), "MANIFEST.runtime.python.pyyaml 必须是对象。")
    pyyaml_package = app_path / str(pyyaml_section.get("package", ""))
    _expect((pyyaml_package / "__init__.py").is_file(),
            f"内置 PyYAML 包缺失：{pyyaml_section.get('package')!r}")

    problems = verify_runtime_references(app_path)
    _expect(not problems, "运行时引用检查失败：\n" + "\n".join(problems))

    runtime_section = manifest.get("runtime", {})
    _expect(runtime_section.get("minimum_macos") == MIN_BUNDLED_MACOS,
            f"MANIFEST.runtime.minimum_macos 必须为 {MIN_BUNDLED_MACOS}。")
    runtime_binaries = runtime_section.get("binaries", list(QEMU_BINARIES))
    _expect(isinstance(runtime_binaries, list)
            and all(isinstance(name, str) for name in runtime_binaries),
            "MANIFEST.runtime.binaries 必须是字符串数组。")
    spice_client_rel = runtime_section.get("spice_client")
    if spice_client_rel is not None:
        _expect(spice_client_rel == f"{RUNTIME_REL}/bin/{SPICE_CLIENT_NAME}",
                "MANIFEST.runtime.spice_client 必须指向内置 spicy。")
        spice_client_path = app_path / spice_client_rel
        _expect(spice_client_path.is_file() and os.access(spice_client_path, os.X_OK),
                "MANIFEST.runtime.spice_client 缺失或不可执行。")
        _expect(SPICE_CLIENT_NAME in runtime_binaries,
                "MANIFEST.runtime.binaries 必须登记内置 spicy。")
    runtime_entitlements = runtime_section.get("entitlements", {})
    _expect(isinstance(runtime_entitlements, dict),
            "MANIFEST.runtime.entitlements 必须是字典。")
    allowed_entitlement_files = set(runtime_binaries) | set(runtime_section.get("dylibs", []))
    for name, recorded in runtime_entitlements.items():
        _expect(isinstance(name, str) and name in allowed_entitlement_files,
                f"MANIFEST.runtime.entitlements 含未知文件：{name!r}")
        _expect(isinstance(recorded, dict), f"{name} 的 entitlement 摘要格式无效。")
        keys = recorded.get("keys")
        _expect(isinstance(keys, list) and keys == sorted(keys)
                and all(isinstance(key, str) for key in keys),
                f"{name} 的 entitlement 键清单无效。")
        _expect(isinstance(recorded.get("sha256"), str)
                and re.fullmatch(r"[0-9a-f]{64}", recorded["sha256"]),
                f"{name} 的 entitlement 摘要哈希无效。")
        directory = (app_path / RUNTIME_REL / "bin") if name in runtime_binaries \
            else (app_path / RUNTIME_REL / "lib")
        actual = read_entitlements(directory / name) or {}
        _expect(entitlement_record(actual) == recorded,
                f"{name} 的 entitlements 与清单摘要不一致（键或值已变化）")

    seen_entries: set[str] = set()
    for entry in manifest["files"]:
        _expect(isinstance(entry, dict), "MANIFEST.files 含无效条目。")
        rel = entry.get("path")
        digest = entry.get("sha256")
        _expect(isinstance(rel, str) and rel and rel not in seen_entries,
                f"MANIFEST.files 含重复或无效路径：{rel!r}")
        rel_path = Path(rel)
        _expect(not rel_path.is_absolute() and ".." not in rel_path.parts,
                f"MANIFEST.files 路径越界：{rel}")
        _expect(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest),
                f"MANIFEST.files 哈希无效：{rel}")
        seen_entries.add(rel)
        path = app_path / rel
        _expect(path.is_file() and not path.is_symlink(), f"清单登记但 app 内缺失或不是普通文件：{rel}")
        _expect(sha256_file(path) == digest, f"文件哈希不符：{rel}")
    listed = seen_entries
    covered_by_signature = set(manifest.get("signature_covers", []))
    for path in _iter_manifest_files(app_path):
        rel = path.relative_to(app_path).as_posix()
        if rel == MANIFEST_REL:
            continue  # 清单自身不在清单内（其哈希记录在同级 .sha256 旁车文件里）
        if rel in covered_by_signature:
            continue  # 主可执行文件由代码签名覆盖（见 _iter_manifest_files 说明）
        _expect(rel in listed, f"app 内存在未登记文件：{rel}")

    for path in app_path.rglob("*"):
        _expect(not path.is_symlink(), f"app 内不允许符号链接：{path.relative_to(app_path)}")
        if path.is_dir():
            continue
        rel = path.relative_to(app_path).as_posix()
        name = path.name
        _expect(not name.lower().endswith(FORBIDDEN_APP_SUFFIXES), f"app 内出现禁止文件：{rel}")
        for pattern in FORBIDDEN_APP_NAMES:
            _expect(not pattern.match(name), f"app 内出现凭据类文件：{rel}")

    try:
        sbom = json.loads((app_path / SBOM_REL).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppBuildError(f"SBOM.json 无法解析：{exc}") from exc
    _expect(isinstance(sbom, dict) and isinstance(sbom.get("components"), list),
            "SBOM.json 缺少有效 components。")
    for component in sbom["components"]:
        _expect(isinstance(component, dict), "SBOM.components 含无效条目。")
        if not component.get("bundled"):
            continue
        file_rel = component.get("file")
        if file_rel:
            _expect(isinstance(file_rel, str), "SBOM bundled file 必须是字符串路径。")
            file_path = Path(file_rel)
            _expect(not file_path.is_absolute() and ".." not in file_path.parts,
                    f"SBOM bundled file 路径越界：{file_rel}")
            _expect((app_path / file_rel).is_file(),
                    f"SBOM 标记 bundled=true 但文件缺失：{file_rel}")
        directory = component.get("directory")
        if directory is not None:
            _expect(isinstance(directory, str) and directory,
                    "SBOM component.directory 必须是非空字符串。")
            directory_path = Path(directory)
            _expect(not directory_path.is_absolute() and ".." not in directory_path.parts,
                    f"SBOM directory 路径越界：{directory}")
            _expect((app_path / directory).is_dir(),
                    f"SBOM 标记 bundled=true 但目录缺失：{directory}")
        binaries = component.get("binaries", [])
        _expect(isinstance(binaries, list), "SBOM component.binaries 必须是数组。")
        for binary in binaries:
            _expect(isinstance(binary, dict) and isinstance(binary.get("file"), str),
                    "SBOM binaries 含无效条目。")
            binary_rel = binary["file"]
            binary_path = Path(binary_rel)
            _expect(not binary_path.is_absolute() and ".." not in binary_path.parts,
                    f"SBOM binary 路径越界：{binary_rel}")
            _expect((app_path / binary_rel).is_file(),
                    f"SBOM 标记 bundled=true 但文件缺失：{binary_rel}")
    import ctflab_package  # noqa: PLC0415  函数内导入，避免循环依赖

    blockers = manifest["license"].get("distribution_blockers")
    _expect(isinstance(blockers, list) and all(isinstance(item, str) for item in blockers),
            "MANIFEST.license.distribution_blockers 必须是字符串数组。")
    _expect(manifest["license"].get("status") == ctflab_package.PROJECT_LICENSE,
            f"MANIFEST.license.status 必须为 {ctflab_package.PROJECT_LICENSE}。")
    _expect(manifest["license"].get("project_license_file") == LICENSE_REL,
            f"MANIFEST.license.project_license_file 必须指向 {LICENSE_REL}。")

    # QEMU 源码书面要约：字段必须与随包 SOURCE_OFFER.md 的实际内容一致，防止文档过期。
    offer = manifest["license"].get("source_offer")
    _expect(isinstance(offer, dict), "MANIFEST.license.source_offer 必须是对象。")
    for field in ("qemu_version", "url", "sha256", "valid_until", "text_file"):
        _expect(isinstance(offer.get(field), str) and offer[field],
                f"MANIFEST.license.source_offer 缺少字段：{field}")
    _expect(offer["text_file"] == SOURCE_OFFER_REL,
            f"source_offer.text_file 必须指向 {SOURCE_OFFER_REL}。")
    _expect(re.fullmatch(r"[0-9a-f]{64}", offer["sha256"]),
            "source_offer.sha256 必须是 64 位十六进制摘要。")
    _expect(QEMU_SOURCE_SHA256.get(offer["qemu_version"]) == offer["sha256"],
            f"source_offer 的 QEMU {offer['qemu_version']} 源码哈希与登记表不一致。")
    _expect(offer["url"] == QEMU_SOURCE_URL_TEMPLATE.format(version=offer["qemu_version"]),
            "source_offer.url 与登记的源码地址模板不一致。")
    _expect(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", offer["valid_until"]),
            "source_offer.valid_until 必须是 ISO-8601 UTC 时间。")
    offer_text = (app_path / SOURCE_OFFER_REL).read_text(encoding="utf-8")
    for needle in (offer["qemu_version"], offer["url"], offer["sha256"], offer["valid_until"]):
        _expect(needle in offer_text,
                f"SOURCE_OFFER.md 未包含要约声明的 {needle!r}（文档与清单不一致）。")

    # 旁车是清单自身哈希和 app 全树哈希的唯一外部锚点，verify 必须实际复核它。
    sidecar_path = app_path.with_name(app_path.name + ".sha256")
    _expect(sidecar_path.is_file() and not sidecar_path.is_symlink(),
            f"缺少普通旁车校验文件：{sidecar_path.name}")
    try:
        sidecar_lines = sidecar_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise AppBuildError(f"无法读取旁车校验文件：{sidecar_path.name}（{exc}）") from exc
    expected_lines = [
        f"{app_tree_hash(app_path)}  {APP_BUNDLE_NAME}",
        f"{sha256_file(app_path / MANIFEST_REL)}  {APP_BUNDLE_NAME}/{MANIFEST_REL}",
    ]
    _expect(sidecar_lines == expected_lines, f"旁车校验不一致：{sidecar_path.name}")

    report = {
        "app": str(app_path),
        "version": manifest["version"],
        "file_count": len(manifest["files"]),
        "runtime": manifest["runtime"],
        "license_texts_complete": sbom.get("license_texts_complete"),
        "distribution_blockers": blockers,
    }
    if check_signature:
        report["signature"] = codesign_verify(app_path)
    return report
