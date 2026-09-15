#!/usr/bin/env python3
"""CTFLab Task 6.2：包含受控 QEMU 运行时的 `CTFLab.app` 本地构建。

设计见 `docs/ctflab-task6-app-runtime-design.md`。核心约束：

- 只随包必要的 QEMU 程序、firmware/ROM/keymaps 与其非系统动态库；macOS 系统库不复制；
- 动态库闭包用 `otool -L` 递归求解，路径改写为 `@loader_path` 相对引用；无法确认的依赖直接失败，
  不猜测、不跳过；
- `.app` 内不出现任何虚拟磁盘、凭据、日志；运行状态仍写在 app 外部；
- 排他发布：同父目录内构建随机临时 `.app`，全部校验通过后才改名为最终目录；失败清理本次临时内容；
- 签名分级如实记录：`unsigned` / `ad-hoc` / `developer-id`；没有真实身份时不冒充 Developer ID；
  公证只记录“未验证/后续任务”，本模块不接触任何密码或凭据。
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
from pathlib import Path
from typing import Any, Iterable

TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_ROOT = TOOLS_DIR.parent

APP_BUNDLE_NAME = "CTFLab.app"
APP_EXECUTABLE = "CTFLab"
CTFLAB_VERSION_FALLBACK = "0.1.0"
BUNDLE_IDENTIFIER = "local.ctflab.app"
RUNTIME_REL = "Contents/Resources/runtime"
CTFLAB_REL = "Contents/Resources/ctflab"
LICENSES_REL = "Contents/Resources/licenses"
MANIFEST_REL = "Contents/Resources/MANIFEST.json"
SBOM_REL = "Contents/Resources/SBOM.json"
THIRD_PARTY_REL = "Contents/Resources/THIRD_PARTY_LICENSES.md"
LAUNCHER_REL = f"Contents/MacOS/{APP_EXECUTABLE}"
INFO_PLIST_REL = "Contents/Info.plist"
SIGNATURE_DIR_REL = "Contents/_CodeSignature"

QEMU_BINARIES = ("qemu-system-aarch64", "qemu-system-x86_64", "qemu-img")
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
    "snappy": "BSD-3-Clause",
    "vde": "GPL-2.0-or-later AND LGPL-2.1-or-later（libvdeplug）",
    "zstd": "BSD-3-Clause OR GPL-2.0",
}
LICENSE_GLOBS = ("COPYING*", "LICENSE*", "NOTICE*", "LGPL-*", "GPL-*", "MIT*", "BSD*")

LAUNCHER_TEMPLATE = """#!/bin/sh
# CTFLab 启动器（.app 内）：计算受控运行时路径，不依赖任何开发机绝对路径。
set -eu

contents_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
resources="$contents_dir/Resources"
runtime="$resources/runtime"
if [ -d "$runtime/bin" ]; then
  CTFLAB_RUNTIME_ROOT="$runtime"
  export CTFLAB_RUNTIME_ROOT
fi

python_bin=$(command -v python3 || true)
if [ -z "$python_bin" ]; then
  echo "错误：需要 Python 3.10+（未找到 python3）。" >&2
  exit 1
fi

exec "$python_bin" "$resources/ctflab/tools/ctflab.py" "$@"
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

def _run_tool(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, text=True)
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


def _formula_version(formula: str) -> str | None:
    opt = Path("/opt/homebrew/opt") / formula
    if opt.exists():
        target = opt.resolve()
        if target.parent.name == "Cellar":
            return target.name
    return None


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
        "CFBundleExecutable": APP_EXECUTABLE,
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "CTFLab",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": "13.0",
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
    for rel_root in ("tools/ctflab_profiles", "tools/guest_fixes"):
        source_dir = source_root / rel_root
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


def _sign_macho_files(runtime_bin: Path, runtime_lib: Path, identity: str,
                      entitlements: dict[str, dict[str, Any]] | None = None) -> list[str]:
    entitlements = entitlements or {}
    signed: list[str] = []
    for directory in (runtime_lib, runtime_bin):
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and not path.name.startswith("."):
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
    files: list[Path] = []
    for path in sorted(app_root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(app_root).as_posix()
        if rel.startswith(SIGNATURE_DIR_REL + "/"):
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
               license_texts_complete: bool) -> dict[str, Any]:
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
            "source": f"Homebrew qemu {_formula_version('qemu') or '?'}",
        })
    dylib_components = []
    for name, source in sorted(libs.items()):
        formula = _formula_of(source) or "unknown"
        dylib_components.append({
            "file": f"{RUNTIME_REL}/lib/{name}",
            "formula": formula,
            "version": _formula_version(formula) if formula != "unknown" else None,
            "arch": _binary_arch(source),
            "sha256": sha256_file(source),
            "license": KNOWN_LICENSES.get(formula, f"unknown（见 licenses/{formula}/ 内文本）"),
            "license_text_status": "present" if license_index.get(formula) else "missing-in-keg",
            "bundled": True,
            "source": f"Homebrew formula {formula}",
        })
    components = [{
        "name": "ctflab",
        "type": "application",
        "role": "runtime",
        "version": version,
        "license": "undeclared",
        "license_detail": "仓库尚未声明项目许可证；对外分发/公开发布被禁止，直到权利人补充 LICENSE。",
        "bundled": True,
    }, {
        "name": "QEMU",
        "type": "application",
        "role": "runtime",
        "version": _qemu_version(qemu_root / "bin" / "qemu-system-aarch64"),
        "license": KNOWN_LICENSES["qemu"],
        "bundled": True,
        "source": f"Homebrew qemu {_formula_version('qemu') or '?'}",
        "binaries": qemu_bins,
        "runtime_assets": {
            "share_files": qemu_share,
            "note": "firmware/ROM/keymaps 属于 QEMU 运行时数据；EDK2 固件为 "
                    "BSD-2-Clause-Patent（见 licenses/edk2/）。",
        },
        "distribution_obligations": [
            "QEMU 为 GPL-2.0-only：随二进制分发时须向接收者提供完整对应源码或书面要约；"
            "本 app 未随附源码，不得据此宣称 GPL 合规或对外发布。",
            "EDK2 固件（edk2-*.fd、efi-*.rom）为 BSD-2-Clause-Patent；许可证文本见 licenses/edk2/。",
            "捆绑的 LGPL 组件（glib/gnutls/libssh/libidn2/nettle 等）以独立动态库形式随包，"
            "接收者可用兼容版本替换以实现重新链接；许可证文本随包提供。",
        ],
    }]
    components.extend(dylib_components)
    return {
        "schema": 1,
        "format": "ctflab-app-sbom",
        "generated_at": generated_at,
        "components": components,
        "license_texts_complete": license_texts_complete,
        "notes": [
            "bundled=true 表示该组件实际位于 app 内；哈希为打包时值（见 MANIFEST.json）。",
            "许可证标识来自 Homebrew formula 声明与随包文本，未做法律审查。",
            "项目自身许可证仍为 undeclared：禁止公开发布本 app。",
        ],
    }


def third_party_markdown(sbom: dict[str, Any]) -> str:
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
            lines.append(f"| {component['name']} | {component.get('version')} | {component['license']} | "
                         f"{component.get('license_detail', '')} |")
    lines += ["", "## QEMU / GPL 分发义务（单独列出）", ""]
    for obligation in sbom["components"][1]["distribution_obligations"]:
        lines.append(f"- {obligation}")
    lines += [
        "",
        "## 项目自身许可证",
        "",
        "`undeclared`：未声明许可证，**禁止公开发布本 app**。许可证文本完整性："
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
    generated_at: str | None = None,
    sign_identity: str | None = None,
    allow_incomplete_license_texts: bool = False,
    unsigned: bool = False,
    share_files: Iterable[str] | None = None,
) -> dict[str, Any]:
    """构建 `CTFLab.app`；排他发布，目标已存在时拒绝覆盖。"""
    source_root = Path(source_root or DEFAULT_SOURCE_ROOT)
    runtime_version = ctflab_version()
    version = str(runtime_version if version is None else version)
    _expect(version == runtime_version,
            f"app 版本必须与 CTFLAB_VERSION 一致：当前 {runtime_version}，请求 {version}")
    generated_at = generated_at or now_iso()
    qemu_root = Path(qemu_root) if qemu_root else detect_qemu_root()

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

        # 1) Info.plist 与启动器
        (contents / "Info.plist").write_bytes(plistlib.dumps(_info_plist(version)))
        _write_launcher(contents / "MacOS" / APP_EXECUTABLE)

        # 2) CTFLab 源码镜像
        _copy_ctflab_sources(source_root, resources / "ctflab")

        # 3) QEMU 程序与资源（同时采集源二进制 entitlements：HVF 等能力不能丢）
        source_entitlements: dict[str, dict[str, Any]] = {}
        for name in QEMU_BINARIES:
            source = qemu_root / "bin" / name
            _expect(source.is_file(), f"缺少 QEMU 程序：{source}")
            shutil.copy2(source, runtime_bin / name)
            (runtime_bin / name).chmod(0o755)
            found = read_entitlements(source)
            if found:
                source_entitlements[name] = found
        copied_share = copy_qemu_share(qemu_root, runtime_share, share_files)

        # 4) 动态库闭包与 install_name 改写
        libs_sources = collect_dylib_closure([runtime_bin / name for name in QEMU_BINARIES])
        for name, source in sorted(libs_sources.items()):
            shutil.copy2(source, runtime_lib / name)
            (runtime_lib / name).chmod(0o755)
            found = read_entitlements(source)
            if found:
                source_entitlements[name] = found
        libs_targets = {name: runtime_lib / name for name in libs_sources}
        _rewrite_install_names([runtime_bin / name for name in QEMU_BINARIES], libs_targets)

        # 5) 签名 Mach-O（install_name_tool 之后必须重新签名；没有身份时 ad-hoc）
        if not unsigned:
            _sign_macho_files(runtime_bin, runtime_lib, sign_identity or "-", source_entitlements)
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
            directory = runtime_bin if name in QEMU_BINARIES else runtime_lib
            actual = read_entitlements(directory / name)
            if actual:
                bundled_entitlements[name] = actual

        # 6) 许可证文本
        licenses_dir = resources / "licenses"
        licenses_dir.mkdir()
        license_index: dict[str, list[str]] = {}
        formulas = sorted({_formula_of(source) or "unknown" for source in libs_sources.values()}
                          | {"qemu", "edk2"})
        missing: list[str] = []
        for formula in formulas:
            if formula == "edk2":
                target_dir = licenses_dir / "edk2"
                target_dir.mkdir()
                shutil.copy2(runtime_share / "edk2-licenses.txt", target_dir / "edk2-licenses.txt")
                license_index["edk2"] = ["edk2-licenses.txt"]
                continue
            texts = collect_license_texts(formula)
            if not texts:
                missing.append(formula)
                license_index[formula] = []
                continue
            target_dir = licenses_dir / formula
            target_dir.mkdir()
            license_index[formula] = []
            for name, path in texts:
                shutil.copy2(path, target_dir / name)
                license_index[formula].append(name)
        _expect(not missing or allow_incomplete_license_texts,
                "以下随包组件的许可证文本在 Homebrew keg 中不存在，且未使用 "
                f"--allow-incomplete-license-texts：{', '.join(missing)}；"
                "分发义务无法确认时停止，不猜测。")

        # 7) SBOM / 许可证说明 / MANIFEST（在签名后计算最终文件哈希）
        sbom = build_sbom(version=version, generated_at=generated_at, qemu_root=qemu_root,
                          libs=libs_sources, qemu_share=copied_share,
                          license_index=license_index, license_texts_complete=not missing)
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
            "runtime": {
                "root": RUNTIME_REL,
                "binaries": list(QEMU_BINARIES),
                "dylibs": sorted(libs_sources),
                "share_files": copied_share,
                "qemu_version": _qemu_version(qemu_root / "bin" / "qemu-system-aarch64"),
                "source": f"Homebrew qemu {_formula_version('qemu') or '?'}",
                "entitlements": {
                    name: entitlement_record(value)
                    for name, value in sorted(bundled_entitlements.items())
                },
            },
            "signature": dict(signature_plan),
            "license": {
                "status": "undeclared",
                "distribution_blockers": (
                    (["许可证文本不完整：" + ", ".join(missing)] if missing else [])
                    + ["项目许可证未声明且未随附 QEMU 对应源码；禁止公开发布"]
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
    """检查 app 内所有 Mach-O 文件：无禁止引用，且非系统依赖都在 runtime/lib 内。"""
    runtime = app / RUNTIME_REL
    problems: list[str] = []
    macho_files = [p for p in (runtime / "bin").iterdir() if p.is_file()]
    macho_files += [p for p in (runtime / "lib").iterdir() if p.is_file()]
    lib_dir = (runtime / "lib").resolve()
    for path in macho_files:
        for dep in otool_deps(path):
            if dep.startswith("@loader_path/"):
                target = (path.parent / dep[len("@loader_path/"):]).resolve()
                if not target.is_relative_to(lib_dir):
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
    _expect(info.get("CFBundleExecutable") == APP_EXECUTABLE, "Info.plist 的 CFBundleExecutable 不正确。")
    _expect(info.get("CFBundleIdentifier") == BUNDLE_IDENTIFIER, "Info.plist 的 CFBundleIdentifier 不正确。")
    _expect(str(info.get("CFBundleShortVersionString")) == str(manifest["version"]),
            "Info.plist 版本与 MANIFEST 不一致。")

    launcher = (app_path / LAUNCHER_REL).read_text(encoding="utf-8")
    for pattern in FORBIDDEN_BINARY_PATTERNS:
        _expect(not pattern.search(launcher), f"启动器包含禁止路径：{pattern.pattern}")
    _expect("CTFLAB_RUNTIME_ROOT" in launcher, "启动器必须导出 CTFLAB_RUNTIME_ROOT。")

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

    problems = verify_runtime_references(app_path)
    _expect(not problems, "运行时引用检查失败：\n" + "\n".join(problems))

    runtime_section = manifest.get("runtime", {})
    runtime_entitlements = runtime_section.get("entitlements", {})
    _expect(isinstance(runtime_entitlements, dict),
            "MANIFEST.runtime.entitlements 必须是字典。")
    allowed_entitlement_files = set(QEMU_BINARIES) | set(runtime_section.get("dylibs", []))
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
        directory = (app_path / RUNTIME_REL / "bin") if name in QEMU_BINARIES \
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
    for path in _iter_manifest_files(app_path):
        rel = path.relative_to(app_path).as_posix()
        if rel == MANIFEST_REL:
            continue  # 清单自身不在清单内（其哈希记录在同级 .sha256 旁车文件里）
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
    blockers = manifest["license"].get("distribution_blockers")
    _expect(isinstance(blockers, list) and all(isinstance(item, str) for item in blockers),
            "MANIFEST.license.distribution_blockers 必须是字符串数组。")

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
