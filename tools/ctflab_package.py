#!/usr/bin/env python3
"""CTFLab Task 6.1：可分发安装包（release bundle）与 `.ctflab` 内容包。

设计见 `docs/ctflab-task6-packaging-design.md`。核心约束：

- 白名单构建：只收集明确列出的源码/配置/文档路径；任何磁盘、凭据、日志、缓存一律排除，
  显式命中时直接拒绝构建；
- 确定性归档：条目排序、固定 uid/gid/uname/gname 与统一 mtime，gzip mtime 也固定；
  相同输入与相同 `generated_at` 产出逐字节相同的包；
- 排他发布：目标已存在时拒绝覆盖；
- 完整性：包内 `MANIFEST.json` / `content.json` 逐文件 SHA-256，外层 tar.gz 另有 `.sha256` 旁车；
- 诚实边界：项目许可证未声明时如实标注 `undeclared`；内容包不含虚拟磁盘；SBOM 不虚构
  “已内置”的组件（第三方依赖标为 `bundled=false`，CTFLab 自身源码标为 `bundled=true`）。

本模块不导入 `ctflab` 的顶层实现（避免循环导入），仅在需要校验 profile 时做函数内导入。
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

TOOLS_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_ROOT = TOOLS_DIR.parent

RELEASE_FORMAT = "ctflab-release"
CONTENT_FORMAT = "ctflab-content"
FORMAT_VERSION = 1
RELEASE_PLATFORM = "macos-arm64"
MIN_PYTHON = "3.10"

# 发布包白名单：仓库内允许进入安装包的工具/文档（相对 PROJECT_ROOT）。
RELEASE_TOOL_FILES = (
    "tools/ctflab.py",
    "tools/ctflab_inspect.py",
    "tools/ctflab_network.py",
    "tools/ctflab_utm.py",
    "tools/ctflab_utm_fixture.json",
    "tools/ctflab_package.py",
    "tools/ctflab_acceptance.py",
    # `ctflab.py app build/verify` 会在运行时导入该模块；源码发布包必须一起带上，
    # 否则安装后的 CLI 虽然暴露 app 子命令，却会在真正执行时 ModuleNotFoundError。
    "tools/ctflab_app.py",
)
RELEASE_DOC_FILES = (
    "README.md",
    "docs/ctflab-phase1-quickstart.md",
    "docs/ctflab-mac-mvp-implementation-plan.md",
    "docs/ctflab-dynamic-resolution-design.md",
    "docs/ctflab-task6-packaging-design.md",
)

# 硬性排除：即使被显式列入白名单也不允许打包（防呆）。
FORBIDDEN_SUFFIXES = (
    ".qcow2", ".qcow", ".raw", ".img", ".fd", ".iso",
    ".vmdk", ".vdi", ".vhd", ".vhdx", ".ova",
    ".pem", ".key", ".pcap",
)
FORBIDDEN_COMPONENTS = ("logs", "runtime", "probes", "__pycache__", ".git", "dist", "build")
FORBIDDEN_NAME_PATTERNS = (
    re.compile(r"^credentials.*\.txt$"),
    re.compile(r"^guest-credentials.*$"),
    re.compile(r"^\.env(\.|$)"),
)

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_CONSTRAINT_RE = re.compile(r"^(>=|>|==)\s*(\d+\.\d+\.\d+)$")


class PackageError(Exception):
    """打包/校验失败的统一异常。"""


def _expect(condition: Any, message: str) -> None:
    if not condition:
        raise PackageError(message)


def ctflab_version() -> str:
    """当前 CTFLab 版本（单一来源：`tools/ctflab.py` 的 CTFLAB_VERSION）。"""
    import ctflab  # noqa: PLC0415  函数内导入，避免打包模块与主 CLI 循环依赖

    return str(ctflab.CTFLAB_VERSION)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_version(text: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(str(text))
    _expect(match, f"版本号必须形如 X.Y.Z：{text!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def version_satisfies(current: str, constraint: str) -> bool:
    """支持 `>=X.Y.Z`、`>X.Y.Z`、`==X.Y.Z` 三种约束。"""
    match = _CONSTRAINT_RE.match(str(constraint).strip())
    _expect(match, f"不支持的版本约束：{constraint!r}（只允许 >=、>、==）")
    operator, target_text = match.groups()
    current_tuple = parse_version(current)
    target = parse_version(target_text)
    if operator == ">=":
        return current_tuple >= target
    if operator == ">":
        return current_tuple > target
    return current_tuple == target


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def forbidden_reason(relative: str | PurePosixPath) -> str | None:
    """返回排除原因；None 表示允许。用于构建期与校验期的一致性判断。"""
    posix = PurePosixPath(str(relative))
    if posix.is_absolute() or any(part in ("", "..") for part in posix.parts):
        return "绝对路径或可疑路径"
    name = posix.name
    if name.startswith(".") and name not in {".gitignore"}:
        return "隐藏文件"
    for part in posix.parts:
        if part in FORBIDDEN_COMPONENTS:
            return f"禁止的目录：{part}"
    if name.lower().endswith(FORBIDDEN_SUFFIXES):
        return "禁止的文件类型（磁盘/凭据/抓包）"
    for pattern in FORBIDDEN_NAME_PATTERNS:
        if pattern.match(name):
            return "禁止的凭据类文件名"
    return None


def _collect_tree(root: Path, relative_root: str, collected: list[tuple[str, Path, int]]) -> None:
    """递归收集目录下的普通文件（跳过 __pycache__ 等禁止项）。"""
    base = root / relative_root if relative_root else root
    _expect(not base.is_symlink(), f"发布包白名单目录不得是符号链接：{base}")
    if not base.exists():
        return
    for path in sorted(base.rglob("*")):
        _expect(not path.is_symlink(), f"发布包白名单目录不得包含符号链接：{path}")
        if path.is_dir():
            continue
        _expect(path.is_file(), f"发布包白名单目录含非普通文件：{path}")
        rel = path.relative_to(root).as_posix()
        if forbidden_reason(rel):
            continue
        collected.append((rel, path, 0o755 if os.access(path, os.X_OK) else 0o644))


def collect_release_files(source_root: Path) -> list[tuple[str, Path, int]]:
    collected: list[tuple[str, Path, int]] = []
    for rel in RELEASE_TOOL_FILES + RELEASE_DOC_FILES:
        path = source_root / rel
        reason = forbidden_reason(rel)
        _expect(not reason, f"发布包白名单文件被禁止规则拦截：{rel}（{reason}）")
        _expect(path.is_file() and not path.is_symlink(), f"发布包白名单文件不存在或为符号链接：{path}")
        mode = 0o755 if path.name in {"ctflab"} or path.suffix == ".sh" else 0o644
        collected.append((rel, path, mode))
    _collect_tree(source_root, "tools/ctflab_profiles", collected)
    _collect_tree(source_root, "tools/guest_fixes", collected)
    _expect(any(rel.endswith(".yaml") for rel, _, _ in collected), "发布包缺少 profile 配置。")
    return collected


def collect_content_files(source_root: Path, profile_id: str) -> list[tuple[str, Path, int]]:
    _expect(re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(profile_id)) is not None,
            f"内容包 id 不合法：{profile_id!r}")
    collected: list[tuple[str, Path, int]] = []
    profile_rel = f"tools/ctflab_profiles/{profile_id}.yaml"
    profile_path = source_root / profile_rel
    _expect(profile_path.is_file() and not profile_path.is_symlink(),
            f"未找到 profile 或 profile 是符号链接：{profile_path}")
    collected.append((f"profile/{profile_id}.yaml", profile_path, 0o644))
    fixes_dir = source_root / "tools" / "guest_fixes" / profile_id
    _expect(not fixes_dir.is_symlink(), f"内容包来宾修复目录不得是符号链接：{fixes_dir}")
    if fixes_dir.is_dir():
        for path in sorted(fixes_dir.rglob("*")):
            _expect(not path.is_symlink(), f"内容包来宾修复目录不得包含符号链接：{path}")
            if path.is_dir():
                continue
            _expect(path.is_file(), f"内容包来宾修复目录含非普通文件：{path}")
            rel = f"guest_fixes/{profile_id}/{path.relative_to(fixes_dir).as_posix()}"
            if forbidden_reason(rel):
                continue
            collected.append((rel, path, 0o755 if os.access(path, os.X_OK) else 0o644))
    return collected


def _tar_timestamp(generated_at: str) -> int:
    text = str(generated_at).replace("Z", "+00:00")
    return int(datetime.fromisoformat(text).timestamp())


def write_deterministic_tar_gz(path: Path, entries: Iterable[tuple[str, bytes, int]], generated_at: str) -> None:
    """写确定性 tar.gz：条目排序、元数据固定、gzip mtime 固定。"""
    timestamp = _tar_timestamp(generated_at)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, data, mode in sorted(entries, key=lambda item: item[0]):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            info.mtime = timestamp
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    compressed = gzip.compress(buffer.getvalue(), compresslevel=9, mtime=timestamp)
    path.write_bytes(compressed)


def read_tar_gz(path: Path) -> dict[str, bytes]:
    """读取 tar.gz 为 {相对路径: 内容}；拒绝路径穿越、绝对路径与非常规条目。"""
    _expect(path.is_file(), f"包不存在：{path}")
    entries: dict[str, bytes] = {}
    member_names: set[str] = set()
    try:
        with tarfile.open(path, mode="r:gz") as tar:
            for member in tar.getmembers():
                name = member.name
                posix = PurePosixPath(name)
                _expect("\x00" not in name and not posix.is_absolute() and ".." not in posix.parts,
                        f"包内条目路径不合法：{name}")
                _expect(name not in member_names, f"包内存在重复条目：{name}")
                member_names.add(name)
                if member.isdir():
                    continue
                _expect(name not in {"", "."}, f"包内条目路径为空：{name!r}")
                _expect(member.isfile(), f"包内存在非常规条目（符号链接/设备等）：{name}")
                handle = tar.extractfile(member)
                _expect(handle is not None, f"无法读取条目：{name}")
                entries[name] = handle.read()
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise PackageError(f"不是有效的 tar.gz 包：{path}（{exc}）") from exc
    _expect(entries, f"包为空：{path}")
    return entries


def _publish_temp_file(source: Path, destination: Path) -> None:
    """以同目录硬链接实现“创建即排他”，避免检查后写入的竞态与跟随悬空符号链接。"""
    source = Path(source)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except FileExistsError as exc:
        raise PackageError(f"目标已存在，拒绝覆盖：{destination}") from exc
    except OSError as exc:
        raise PackageError(f"排他发布失败：{destination}（{exc}）") from exc


def _temporary_path(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=directory)
    os.close(fd)
    return Path(raw)


def _publish_file(path: Path, data: bytes, *, mode: int = 0o644) -> None:
    """先在目标目录写临时文件，再以排他方式发布；失败不触碰既有目标。"""
    path = Path(path)
    temporary = _temporary_path(path.parent, path.name)
    try:
        temporary.write_bytes(data)
        os.chmod(temporary, mode)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        _publish_temp_file(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json_entry(entries: dict[str, bytes], name: str) -> dict[str, Any]:
    data = entries.get(name)
    _expect(data is not None, f"包内缺少 {name}")
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"包内 {name} 不是有效 JSON") from exc
    _expect(isinstance(value, dict), f"包内 {name} 顶层必须是对象")
    return value


def _read_checksum_sidecar(path: Path) -> str:
    try:
        parts = path.read_text(encoding="utf-8").split()
    except (OSError, UnicodeDecodeError) as exc:
        raise PackageError(f"无法读取旁车校验文件：{path}") from exc
    _expect(len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]) is not None,
            f"旁车校验文件格式无效：{path.name}")
    return parts[0].lower()


def _validate_manifest_files(files: Any, *, label: str) -> list[dict[str, Any]]:
    _expect(isinstance(files, list), f"{label}.files 必须是数组")
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in files:
        _expect(isinstance(entry, dict), f"{label}.files 含无效条目")
        rel = entry.get("path")
        digest = entry.get("sha256")
        _expect(isinstance(rel, str) and rel and rel not in seen,
                f"{label}.files 含重复或无效路径：{rel!r}")
        reason = forbidden_reason(rel) if isinstance(rel, str) else "路径类型无效"
        _expect(not reason, f"{label}.files 含禁止路径：{rel}（{reason}）")
        _expect(isinstance(digest, str) and re.fullmatch(r"[0-9a-fA-F]{64}", digest) is not None,
                f"{label}.files 的 SHA-256 无效：{rel}")
        seen.add(rel)
        validated.append(entry)
    return validated


def _verify_sums_file(data: bytes, entries: dict[str, bytes], root: str) -> None:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise PackageError("SHA256SUMS 不是有效 UTF-8") from exc
    checksums: dict[str, str] = {}
    for line in lines:
        if not line.strip():
            continue
        parts = line.split("  ", 1)
        _expect(len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]) is not None,
                f"SHA256SUMS 行格式无效：{line!r}")
        rel = parts[1]
        _expect(rel and not PurePosixPath(rel).is_absolute() and ".." not in PurePosixPath(rel).parts,
                f"SHA256SUMS 路径不合法：{rel}")
        _expect(rel not in checksums, f"SHA256SUMS 存在重复条目：{rel}")
        checksums[rel] = parts[0].lower()
    prefix = f"{root}/"
    expected = {name[len(prefix):] for name in entries
                if name.startswith(prefix) and name != f"{root}/SHA256SUMS"}
    _expect(set(checksums) == expected, "SHA256SUMS 未精确覆盖包内文件（不含自身）")
    for rel, digest in checksums.items():
        _expect(sha256_bytes(entries[f"{root}/{rel}"]) == digest,
                f"SHA256SUMS 哈希不符：{rel}")


def build_sbom(*, version: str, generated_at: str) -> dict[str, Any]:
    """SBOM：组件清单 + 许可证标识；第三方组件均不随包分发。"""

    def detected(command: list[str]) -> str | None:
        try:
            import subprocess  # noqa: PLC0415

            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        except Exception:  # noqa: BLE001  探测失败不影响 SBOM 生成
            return None
        if result.returncode != 0:
            return None
        first = (result.stdout or result.stderr).strip().splitlines()
        return first[0] if first else None

    pyyaml_version = None
    try:
        import yaml  # noqa: PLC0415

        pyyaml_version = getattr(yaml, "__version__", None)
    except ImportError:
        pyyaml_version = None

    components = [
        {
            "name": "ctflab",
            "type": "application",
            "role": "runtime",
            "version": version,
            "license": "undeclared",
            "license_detail": "仓库尚未声明项目许可证；对外分发前必须由权利人补充 LICENSE。",
            "bundled": True,
            "source": "本仓库（私有源码镜像）",
        },
        {
            "name": "python",
            "type": "runtime",
            "role": "runtime",
            "requires": f">={MIN_PYTHON}",
            "license": "PSF-2.0",
            "bundled": False,
            "source": "系统或用户自备解释器",
        },
        {
            "name": "PyYAML",
            "type": "library",
            "role": "runtime",
            "detected_version": pyyaml_version,
            "license": "MIT",
            "bundled": False,
            "install": "python3 -m pip install pyyaml",
        },
        {
            "name": "QEMU (qemu-system-*, qemu-img)",
            "type": "application",
            "role": "external",
            "detected_version": detected(["qemu-img", "--version"]),
            "license": "GPL-2.0-only",
            "bundled": False,
            "install": "brew install qemu",
        },
        {
            "name": "bsdtar / libarchive",
            "type": "application",
            "role": "external",
            "license": "BSD-2-Clause",
            "bundled": False,
            "source": "macOS 自带",
        },
        {
            "name": "cpio",
            "type": "application",
            "role": "external",
            "license": "GPL-3.0-or-later",
            "bundled": False,
            "source": "macOS 自带",
        },
        {
            "name": "tesseract",
            "type": "application",
            "role": "optional",
            "license": "Apache-2.0",
            "bundled": False,
            "install": "brew install tesseract（可选，截图分类降级用）",
        },
        {
            "name": "utmctl (UTM)",
            "type": "application",
            "role": "optional",
            "license": "Apache-2.0",
            "bundled": False,
            "install": "可选；仅 UTM 镜像适配流程使用",
        },
    ]
    return {
        "schema": 1,
        "format": "ctflab-sbom",
        "generated_at": generated_at,
        "components": components,
        "notes": [
            "当前发布包不内置任何二进制或动态库；bundled=true 的条目仅 CTFLab 自身源码。",
            "第三方许可证全文未随包分发（未内置第三方组件）；本清单只登记标识与来源。",
        ],
    }


def third_party_licenses_markdown(sbom: dict[str, Any]) -> str:
    lines = [
        "# 第三方组件与许可证清单",
        "",
        f"生成时间：{sbom['generated_at']}（详见同目录 `SBOM.json`）",
        "",
        "| 组件 | 角色 | 许可证 | 是否随包分发 | 说明 |",
        "|---|---|---|---|---|",
    ]
    for component in sbom["components"]:
        detail = component.get("install") or component.get("source") or component.get("requires") or (
            component.get("license_detail", ""))
        lines.append(
            f"| {component['name']} | {component['role']} | {component['license']} | "
            f"{'是' if component.get('bundled') else '否'} | {detail} |"
        )
    lines += [
        "",
        "## 项目自身许可证",
        "",
        "本仓库尚未声明许可证（`MANIFEST.json.license.status = undeclared`）。对外分发前，"
        "权利人必须补充 `LICENSE`；在此之前不得把本安装包用于对外发布。",
        "",
    ]
    return "\n".join(lines)


LAUNCHER_TEMPLATE = """#!/bin/sh
# CTFLab 启动器（发布包内版本）：只使用 PATH 中的 python3，不依赖开发解释器。
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python_bin=$(command -v python3 || true)
if [ -z "$python_bin" ]; then
  echo "错误：未找到 python3（需要 Python {min_python}+）。" >&2
  exit 1
fi
exec "$python_bin" "$script_dir/ctflab.py" "$@"
"""

INSTALL_SH_TEMPLATE = """#!/bin/sh
# CTFLab 安装脚本：校验包内哈希后复制到用户目录，并生成 bin/ctflab 启动脚本。
# 不使用 sudo；默认安装到 ~/Library/Application Support/CTFLab/dist/<version>。
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
version="{version}"

python_bin=$(command -v python3 || true)
if [ -z "$python_bin" ]; then
  echo "错误：需要 Python {min_python}+，未找到 python3。" >&2
  exit 1
fi

echo "校验包内哈希（MANIFEST.json）…"
"$python_bin" - "$script_dir" <<'PY'
import hashlib
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
failed = []
for entry in manifest["files"]:
    path = root / entry["path"]
    if not path.is_file():
        failed.append(f"缺失文件：{{entry['path']}}")
        continue
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry["sha256"]:
        failed.append(f"哈希不符：{{entry['path']}}")
if failed:
    print("校验失败：", file=sys.stderr)
    for item in failed:
        print("  -", item, file=sys.stderr)
    sys.exit(1)
print(f"校验通过：{{len(manifest['files'])}} 个文件")
PY

prefix="${{CTFLAB_PREFIX:-$HOME/Library/Application Support/CTFLab/dist/$version}}"
if [ -e "$prefix" ]; then
  echo "错误：目标已存在，拒绝覆盖：$prefix" >&2
  exit 1
fi
prefix_created=0
launcher_tmp=""
cleanup() {{
  if [ -n "$launcher_tmp" ]; then
    rm -f "$launcher_tmp"
  fi
  if [ "$prefix_created" = "1" ] && [ -d "$prefix" ]; then
    rm -rf "$prefix"
  fi
}}
trap cleanup EXIT HUP INT TERM

# 先用 mkdir 排他占用最终目录；后续任一步失败时，只清理本次新建的目录。
mkdir -p "$(dirname "$prefix")"
if ! mkdir "$prefix"; then
  echo "错误：无法排他创建安装目录：$prefix" >&2
  exit 1
fi
prefix_created=1
archive="$prefix/.ctflab-install.tar"
tar -C "$script_dir" -cf "$archive" .
tar -C "$prefix" -xf "$archive"
rm -f "$archive"

bin_dir="$HOME/Library/Application Support/CTFLab/bin"
mkdir -p "$bin_dir"
launcher="$bin_dir/ctflab"
launcher_tmp="$bin_dir/.ctflab.$$"
printf '#!/bin/sh\\nexec "%s/tools/ctflab" "$@"\\n' "$prefix" > "$launcher_tmp"
chmod 755 "$launcher_tmp"
mv -f "$launcher_tmp" "$launcher"
launcher_tmp=""

prefix_created=0
trap - EXIT HUP INT TERM

echo "已安装到：${{prefix}}"
echo "启动脚本：${{launcher}}（请把 ${{bin_dir}} 加入 PATH）"
echo "许可证状态：{license_status}（对外分发前必须补充项目 LICENSE）"
"""

CONTENT_README_TEMPLATE = """# {name} 内容包（{file_name}）

- 内容包 id：`{profile_id}`，版本：`{version}`
- 最低 CTFLab 版本：`{requires}`
- **本包不包含虚拟磁盘**：请自备原始镜像并按 `ctflab import {profile_id} <镜像路径>` 导入；
- 导入镜像后即可 `ctflab run {profile_id}`；配置与来宾修复随包提供，无需手工编辑 QEMU 参数；
- 完整性：本包与 `{file_name}.sha256` 旁车文件配套；`ctflab content verify {file_name}` 可复验。
"""


def _file_entries(collected: Iterable[tuple[str, Path, int]]) -> list[dict[str, Any]]:
    entries = []
    for rel, path, mode in sorted(collected, key=lambda item: item[0]):
        data = path.read_bytes()
        entries.append({"path": rel, "sha256": sha256_bytes(data), "size": len(data), "mode": f"{mode:04o}"})
    return entries


def build_release_bundle(
    out_dir: Path,
    *,
    version: str | None = None,
    source_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """构建 release bundle（tar.gz + .sha256 旁车），返回清单。目标已存在时拒绝覆盖。"""
    source_root = Path(source_root or DEFAULT_SOURCE_ROOT)
    runtime_version = ctflab_version()
    version = str(runtime_version if version is None else version)
    _expect(version == runtime_version,
            f"发布包版本必须与 CTFLAB_VERSION 一致：当前 {runtime_version}，请求 {version}")
    parse_version(version)
    generated_at = generated_at or now_iso()
    _expect(forbidden_reason("MANIFEST.json") is None, "内部错误：包内文件名被禁止规则拦截。")

    collected = collect_release_files(source_root)
    launcher_bytes = LAUNCHER_TEMPLATE.format(min_python=MIN_PYTHON).encode("utf-8")

    file_entries = _file_entries(collected)
    file_entries.append({
        "path": "tools/ctflab",
        "sha256": sha256_bytes(launcher_bytes),
        "size": len(launcher_bytes),
        "mode": "0755",
    })
    file_entries.sort(key=lambda item: item["path"])

    sbom = build_sbom(version=version, generated_at=generated_at)
    license_status = "undeclared"
    install_sh = INSTALL_SH_TEMPLATE.format(
        version=version, min_python=MIN_PYTHON, license_status=license_status
    )
    manifest = {
        "schema": FORMAT_VERSION,
        "format": RELEASE_FORMAT,
        "name": "CTFLab",
        "version": version,
        "platform": RELEASE_PLATFORM,
        "generated_at": generated_at,
        "entrypoint": "tools/ctflab",
        "installer": "install.sh",
        "requires": {
            "python": f">={MIN_PYTHON}",
            "platform": "macOS Apple Silicon（Darwin arm64）",
            "external_tools": ["qemu-img", "qemu-system-x86_64", "qemu-system-aarch64", "bsdtar/tar", "cpio"],
        },
        "license": {
            "status": license_status,
            "detail": "仓库尚未声明项目许可证；对外分发前必须由权利人补充 LICENSE。",
        },
        "files": file_entries,
        "sbom": "SBOM.json",
        "notes": [
            "本包是源码级安装包：不包含 CTFLab.app、QEMU 运行时、动态库、签名或公证。",
            "包内不含任何虚拟磁盘、凭据、运行日志、截图或 PCAP。",
            "干净环境验收脚本：tools/ctflab_acceptance.py。",
        ],
    }
    extra_entries = [
        ("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"), 0o644),
        ("SBOM.json", json.dumps(sbom, ensure_ascii=False, indent=2).encode("utf-8"), 0o644),
        ("THIRD_PARTY_LICENSES.md", third_party_licenses_markdown(sbom).encode("utf-8"), 0o644),
        ("install.sh", install_sh.encode("utf-8"), 0o755),
    ]
    sums = [f"{sha256_bytes(data)}  {rel}" for rel, data, _mode in extra_entries]
    sums += [f"{entry['sha256']}  {entry['path']}" for entry in manifest["files"]]
    extra_entries.append(("SHA256SUMS", ("\n".join(sorted(sums)) + "\n").encode("utf-8"), 0o644))

    root_name = f"ctflab-{version}"
    payload: list[tuple[str, bytes, int]] = []
    for rel, path, mode in collected:
        payload.append((f"{root_name}/{rel}", path.read_bytes(), mode))
    payload.append((f"{root_name}/tools/ctflab", launcher_bytes, 0o755))
    for rel, data, mode in extra_entries:
        payload.append((f"{root_name}/{rel}", data, mode))

    out_dir = Path(out_dir).expanduser()
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PackageError(f"无法创建输出目录：{out_dir}（{exc}）") from exc
    bundle_name = f"ctflab-{version}-{RELEASE_PLATFORM}.tar.gz"
    bundle_path = out_dir / bundle_name
    checksum_path = out_dir / f"{bundle_name}.sha256"
    _expect(not bundle_path.exists() and not bundle_path.is_symlink()
            and not checksum_path.exists() and not checksum_path.is_symlink(),
            f"目标已存在，拒绝覆盖：{bundle_path.name if bundle_path.exists() else checksum_path.name}")
    bundle_tmp = _temporary_path(out_dir, bundle_name)
    published_bundle = False
    try:
        write_deterministic_tar_gz(bundle_tmp, payload, generated_at)
        os.chmod(bundle_tmp, 0o644)
        bundle_digest = sha256_file(bundle_tmp)
        _publish_temp_file(bundle_tmp, bundle_path)
        published_bundle = True
        try:
            _publish_file(checksum_path, f"{bundle_digest}  {bundle_name}\n".encode("utf-8"))
        except Exception:
            # 清单旁车发布失败时回滚本次已经发布的 bundle，避免留下不可验证的半成品。
            if published_bundle:
                bundle_path.unlink(missing_ok=True)
            raise
    except PackageError:
        raise
    except (OSError, ValueError) as exc:
        raise PackageError(f"构建发布包失败：{exc}") from exc
    finally:
        bundle_tmp.unlink(missing_ok=True)
    return {
        "bundle": str(bundle_path),
        "checksum": str(checksum_path),
        "sha256": bundle_digest,
        "manifest": manifest,
    }


def verify_release_bundle(bundle_path: Path) -> dict[str, Any]:
    """校验 release bundle：旁车哈希、包内清单、逐文件哈希与禁止项。"""
    bundle_path = Path(bundle_path).expanduser()
    _expect(bundle_path.is_file() and not bundle_path.is_symlink(),
            f"安装包必须是普通文件：{bundle_path}")
    checksum_path = bundle_path.with_name(bundle_path.name + ".sha256")
    _expect(checksum_path.is_file(), f"缺少旁车校验文件：{checksum_path.name}")
    expected_digest = _read_checksum_sidecar(checksum_path)
    actual_digest = sha256_file(bundle_path)
    _expect(expected_digest == actual_digest,
            f"外层 SHA-256 不一致：期望 {expected_digest[:12]}…，实际 {actual_digest[:12]}…")

    entries = read_tar_gz(bundle_path)
    roots = {PurePosixPath(name).parts[0] for name in entries}
    _expect(len(roots) == 1, f"包内根目录不唯一：{sorted(roots)}")
    root = roots.pop()
    _expect(root.startswith("ctflab-"), f"根目录命名不符合格式：{root}")
    manifest_name = f"{root}/MANIFEST.json"
    _expect(manifest_name in entries, "包内缺少 MANIFEST.json")
    manifest = _write_json_entry(entries, manifest_name)
    _expect(manifest.get("format") == RELEASE_FORMAT, "MANIFEST.format 不是 ctflab-release")
    _expect(manifest.get("schema") == FORMAT_VERSION, f"MANIFEST.schema 必须是 {FORMAT_VERSION}")
    version = str(manifest.get("version", ""))
    parse_version(version)
    _expect(root == f"ctflab-{version}", f"根目录名与版本不一致：{root} vs {version}")

    manifest_files = _validate_manifest_files(manifest.get("files"), label="MANIFEST")
    listed = {entry["path"] for entry in manifest_files}
    for entry in manifest_files:
        rel = entry["path"]
        name = f"{root}/{rel}"
        _expect(name in entries, f"清单登记但包内缺失：{rel}")
        digest = sha256_bytes(entries[name])
        _expect(digest == entry["sha256"], f"文件哈希不符：{rel}")
        reason = forbidden_reason(rel)
        _expect(not reason, f"包内出现禁止内容：{rel}（{reason}）")
    payload_names = {name for name in entries if not name.endswith("/")}
    auxiliary = {f"{root}/MANIFEST.json", f"{root}/SBOM.json", f"{root}/THIRD_PARTY_LICENSES.md",
                 f"{root}/install.sh", f"{root}/SHA256SUMS"}
    extra = payload_names - {f"{root}/{rel}" for rel in listed} - auxiliary
    _expect(not extra, f"包内存在未登记文件：{sorted(extra)[:3]}")
    _expect(f"{root}/SBOM.json" in entries, "包内缺少 SBOM.json")
    _expect(f"{root}/install.sh" in entries, "包内缺少 install.sh")
    sbom = _write_json_entry(entries, f"{root}/SBOM.json")
    _expect(sbom.get("format") == "ctflab-sbom", "SBOM.format 不是 ctflab-sbom")
    _expect(f"{root}/SHA256SUMS" in entries, "包内缺少 SHA256SUMS")
    _verify_sums_file(entries[f"{root}/SHA256SUMS"], entries, root)
    launcher = entries.get(f"{root}/tools/ctflab")
    _expect(launcher is not None, "包内缺少启动器 tools/ctflab")
    _expect(b"/opt/miniconda3" not in launcher, "发布包启动器不得硬编码开发解释器路径")
    try:
        install_sh = entries[f"{root}/install.sh"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PackageError("包内 install.sh 不是有效 UTF-8") from exc
    _expect("MANIFEST.json" in install_sh, "install.sh 未校验 MANIFEST.json")
    return {
        "bundle": str(bundle_path),
        "sha256": actual_digest,
        "manifest": manifest,
        "sbom": sbom,
        "file_count": len(manifest["files"]),
    }


def build_content_package(
    profile_id: str,
    out_dir: Path,
    *,
    version: str = "1.0.0",
    source_root: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """构建 `<profile>-<version>.ctflab` 内容包（不含虚拟磁盘）。目标已存在时拒绝覆盖。"""
    import ctflab  # noqa: PLC0415  函数内导入，避免循环依赖

    source_root = Path(source_root or DEFAULT_SOURCE_ROOT)
    _expect(re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(profile_id)) is not None,
            f"内容包 id 不合法：{profile_id!r}")
    parse_version(version)
    generated_at = generated_at or now_iso()
    profile_path = source_root / "tools" / "ctflab_profiles" / f"{profile_id}.yaml"
    _expect(profile_path.is_file() and not profile_path.is_symlink(),
            f"未找到 profile 或 profile 是符号链接：{profile_path}")
    _expect(ctflab.yaml is not None, "打包需要 PyYAML：python3 -m pip install pyyaml")
    try:
        profile_data = ctflab.yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except (OSError, ctflab.yaml.YAMLError) as exc:
        raise PackageError(f"无法读取 profile：{profile_path}（{exc}）") from exc
    _expect(isinstance(profile_data, dict), f"profile 不是有效的 YAML 映射：{profile_path}")
    # 校验的是将被打包的那份副本，而不是仓库当前版本，避免两者漂移。
    try:
        ctflab.validate_profile(profile_data, profile_path)
    except Exception as exc:  # noqa: BLE001  将运行器校验错误统一为打包错误
        raise PackageError(str(exc)) from exc

    collected = collect_content_files(source_root, profile_id)
    file_entries = _file_entries(collected)
    profile_entry = next(entry for entry in file_entries if entry["path"].startswith("profile/"))
    fixes_entries = [entry for entry in file_entries if entry["path"].startswith("guest_fixes/")]

    current = ctflab_version()
    content = {
        "schema": FORMAT_VERSION,
        "format": CONTENT_FORMAT,
        "id": profile_id,
        "name": str(profile_data.get("name", profile_id)),
        "version": version,
        "generated_at": generated_at,
        "requires_ctflab": f">={current}",
        "profile": {
            "file": profile_entry["path"],
            "sha256": profile_entry["sha256"],
            "source_name": f"{profile_id}.yaml",
        },
        "guest_fixes": [{"file": entry["path"], "sha256": entry["sha256"]} for entry in fixes_entries],
        "image": {
            "disk_included": False,
            "source_required": True,
            "note": "本内容包不包含虚拟磁盘；用户需自备原始镜像并按 profile 导入。",
        },
        "files": file_entries,
        "notes": [
            f"导入镜像：ctflab import {profile_id} <镜像路径>",
            f"启动：ctflab run {profile_id}",
            "包内不含虚拟磁盘、凭据、日志、截图或 PCAP。",
        ],
    }
    file_name = f"{profile_id}-{version}.ctflab"
    readme = CONTENT_README_TEMPLATE.format(
        name=content["name"], file_name=file_name, profile_id=profile_id,
        version=version, requires=content["requires_ctflab"],
    )
    payload: list[tuple[str, bytes, int]] = [
        ("content.json", json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8"), 0o644),
        ("README.md", readme.encode("utf-8"), 0o644),
    ]
    for rel, path, mode in collected:
        payload.append((rel, path.read_bytes(), mode))

    out_dir = Path(out_dir).expanduser()
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PackageError(f"无法创建输出目录：{out_dir}（{exc}）") from exc
    package_path = out_dir / file_name
    checksum_path = out_dir / f"{file_name}.sha256"
    _expect(not package_path.exists() and not package_path.is_symlink()
            and not checksum_path.exists() and not checksum_path.is_symlink(),
            f"目标已存在，拒绝覆盖：{package_path.name if package_path.exists() else checksum_path.name}")
    package_tmp = _temporary_path(out_dir, file_name)
    published_package = False
    try:
        write_deterministic_tar_gz(package_tmp, payload, generated_at)
        os.chmod(package_tmp, 0o644)
        digest = sha256_file(package_tmp)
        _publish_temp_file(package_tmp, package_path)
        published_package = True
        try:
            _publish_file(checksum_path, f"{digest}  {file_name}\n".encode("utf-8"))
        except Exception:
            if published_package:
                package_path.unlink(missing_ok=True)
            raise
    except PackageError:
        raise
    except (OSError, ValueError) as exc:
        raise PackageError(f"构建内容包失败：{exc}") from exc
    finally:
        package_tmp.unlink(missing_ok=True)
    return {"package": str(package_path), "checksum": str(checksum_path), "sha256": digest,
            "content": content}


def verify_content_package(package_path: Path, *, check_version: bool = True) -> dict[str, Any]:
    """校验 `.ctflab` 内容包：旁车哈希、清单、逐文件哈希、禁止项与版本门禁。"""
    package_path = Path(package_path).expanduser()
    _expect(package_path.suffix == ".ctflab", f"内容包扩展名必须是 .ctflab：{package_path.name}")
    _expect(package_path.is_file() and not package_path.is_symlink(),
            f"内容包必须是普通文件：{package_path}")
    checksum_path = package_path.with_name(package_path.name + ".sha256")
    # 内容包可以脱离旁车文件单独做包内清单校验；若旁车存在则必须严格校验，
    # 这样既支持最小内容包传输，也不会静默接受损坏的旁车。
    if checksum_path.exists() or checksum_path.is_symlink():
        _expect(checksum_path.is_file() and not checksum_path.is_symlink(),
                f"旁车校验文件不是普通文件：{checksum_path.name}")
        expected = _read_checksum_sidecar(checksum_path)
        actual = sha256_file(package_path)
        _expect(expected == actual, "外层 SHA-256 与旁车文件不一致。")
    entries = read_tar_gz(package_path)
    _expect("content.json" in entries, "内容包缺少 content.json")
    content = _write_json_entry(entries, "content.json")
    _expect(content.get("format") == CONTENT_FORMAT, "content.format 不是 ctflab-content")
    _expect(content.get("schema") == FORMAT_VERSION, f"content.schema 必须是 {FORMAT_VERSION}")
    profile_id = str(content.get("id", ""))
    _expect(re.fullmatch(r"[a-z0-9][a-z0-9-]*", profile_id), f"内容包 id 不合法：{profile_id!r}")
    version = str(content.get("version", ""))
    parse_version(version)
    _expect(package_path.name == f"{profile_id}-{version}.ctflab",
            f"文件名与 id/version 不一致：{package_path.name}")
    if check_version:
        constraint = str(content.get("requires_ctflab", ""))
        _expect(version_satisfies(ctflab_version(), constraint),
                f"内容包要求 CTFLab {constraint}，当前 {ctflab_version()} 不满足。")
    image = content.get("image")
    _expect(isinstance(image, dict), "content.image 必须是对象")
    _expect(image.get("disk_included") is False,
            "内容包不得包含虚拟磁盘（image.disk_included 必须为 false）")
    content_files = _validate_manifest_files(content.get("files"), label="content")
    listed = set()
    for entry in content_files:
        rel = entry["path"]
        reason = forbidden_reason(rel)
        _expect(not reason, f"内容包含禁止内容：{rel}（{reason}）")
        _expect(rel in entries, f"清单登记但包内缺失：{rel}")
        _expect(sha256_bytes(entries[rel]) == entry["sha256"], f"文件哈希不符：{rel}")
        listed.add(rel)
    auxiliary = {"content.json", "README.md"}
    extra = set(entries) - listed - auxiliary
    _expect(not extra, f"内容包存在未登记文件：{sorted(extra)[:3]}")
    profile_entry = content.get("profile", {})
    _expect(isinstance(profile_entry, dict), "content.profile 必须是对象")
    expected_profile_file = f"profile/{profile_id}.yaml"
    _expect(profile_entry.get("file") == expected_profile_file,
            "content.profile.file 必须是 profile/<id>.yaml")
    _expect(profile_entry.get("file") in listed, "content.profile.file 未登记在 files 中")
    matching_profile = next(entry for entry in content_files if entry["path"] == expected_profile_file)
    _expect(profile_entry.get("sha256") == matching_profile["sha256"],
            "content.profile.sha256 与 files 清单不一致")
    for rel in listed:
        if rel.startswith("guest_fixes/"):
            _expect(rel.startswith(f"guest_fixes/{profile_id}/"),
                    f"来宾修复路径不属于 profile：{rel}")
    return {"package": str(package_path), "content": content, "file_count": len(content_files)}


def unpack_content_package(package_path: Path, out_dir: Path) -> list[Path]:
    """校验后解包；写入前再次逐文件校验哈希，目标已存在时拒绝覆盖。"""
    report = verify_content_package(package_path)
    entries = read_tar_gz(Path(report["package"]))
    out_dir = Path(out_dir).expanduser()
    if out_dir.exists() or out_dir.is_symlink():
        _expect(out_dir.is_dir() and not out_dir.is_symlink(),
                f"解包目标必须是普通目录：{out_dir}")
    content_files = report["content"].get("files", [])
    modes = {entry["path"]: entry.get("mode", "0644") for entry in content_files}
    targets: list[tuple[str, bytes, Path, int]] = []
    # 先完成整包冲突预检，避免第二个文件冲突时留下第一个文件的半解包目录。
    for rel in sorted(set(entries) - {"content.json", "README.md"}):
        reason = forbidden_reason(rel)
        _expect(not reason, f"内容包含禁止内容：{rel}（{reason}）")
        target = out_dir / rel
        parent = target.parent
        while parent != out_dir and parent != parent.parent:
            _expect(not parent.is_symlink(), f"解包路径包含符号链接目录：{parent}")
            parent = parent.parent
        _expect(not target.exists() and not target.is_symlink(), f"目标已存在，拒绝覆盖：{target}")
        mode_text = str(modes.get(rel, "0644"))
        _expect(re.fullmatch(r"[0-7]{3,4}", mode_text) is not None,
                f"文件权限字段无效：{rel}")
        targets.append((rel, entries[rel], target, int(mode_text, 8)))
    written: list[Path] = []
    for rel, data, target, mode in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        os.chmod(target, mode)
        written.append(target)
    return written
