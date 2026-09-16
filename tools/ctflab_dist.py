#!/usr/bin/env python3
"""CTFLab 分发包准备（路线 A）：压缩基盘、生成 `DISTRIBUTION.json` / `SHA256SUMS` / `README.md`。

设计边界：

- 只处理“要发给学生的文件”（已导入基盘、UEFI NVRAM 模板）与哈希清单，不读写状态目录；
- 清单可增量合并：多次 `ctflab dist prepare --profile …` 写入同一目录，按 (profile, role) 覆盖登记；
- 压缩使用 qcow2 `compression_type=zstd`（QEMU 5.1+ 支持，产物仍可直接被 `qemu-img`/CTFLab 导入，
  学生无需解包）；压缩后用 `qemu-img check` 复核再登记；
- 每条登记记录：文件、角色、profile、字节数、SHA-256、压缩方式，以及该 profile 已导入基盘的
  `base_sha256`（即验证记录里那份基盘的哈希），供分发前交叉核对；
- 不猜测：默认从状态目录解析“当前已导入的基盘/NVRAM”，也可显式指定；哈希一律实测。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DISTRIBUTION_FORMAT = "ctflab-distribution"
MANIFEST_NAME = "DISTRIBUTION.json"
SUMS_NAME = "SHA256SUMS"
README_NAME = "README.md"
COMPRESSION_ZSTD = "zstd"
COMPRESSION_NONE = "none"
BASE_ROLE = "base"
NVRAM_ROLE = "nvram"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class DistError(Exception):
    """分发准备/复核失败的统一异常。"""


def _expect(condition: Any, message: str) -> None:
    if not condition:
        raise DistError(message)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_tool(command: list[str], *, timeout: int,
              check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise DistError(f"找不到命令：{command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise DistError(f"命令超时（{timeout}s）：{' '.join(command)}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise DistError(f"命令失败：{' '.join(command)}\n{detail}")
    return result


def _virtual_size(qemu_img: str, path: Path) -> int:
    result = _run_tool([qemu_img, "info", "--output=json", str(path)], timeout=600)
    try:
        info = json.loads(result.stdout)
        return int(info["virtual-size"])
    except (ValueError, KeyError, TypeError) as exc:
        raise DistError(f"无法解析 qemu-img info 输出：{path}（{exc}）") from exc


def compress_qcow2(qemu_img: str, source: Path, target: Path, *, timeout: int = 7200) -> str:
    """把来源镜像压缩转换为 qcow2，并证明产物与来源的来宾可见内容一致。

    顺序：convert（zstd）→ `qemu-img check` → 容量一致 → 非严格 `qemu-img compare`
    （来宾可见内容逐字节一致）。

    两个必须注意的语义（实测）：

    - 严格模式 `-s` 还会比较块的分配状态；压缩会重排分配布局，必然报
      `block status mismatch`，因此这里**不能**用 `-s`；
    - 非严格模式对容量不一致只警告不报错，所以容量必须用 `qemu-img info` 显式核对。
    """
    _run_tool([qemu_img, "convert", "-c", "-O", "qcow2",
               "-o", f"compression_type={COMPRESSION_ZSTD}",
               str(source), str(target)], timeout=timeout)
    _run_tool([qemu_img, "check", "-q", str(target)], timeout=timeout)
    source_size = _virtual_size(qemu_img, source)
    target_size = _virtual_size(qemu_img, target)
    if source_size != target_size:
        raise DistError(
            f"压缩产物容量与来源基盘不一致（来源 {source_size}，产物 {target_size}），拒绝发布")
    comparison = _run_tool([qemu_img, "compare", "-f", "qcow2", "-F", "qcow2",
                            str(source), str(target)], timeout=timeout, check=False)
    if comparison.returncode != 0:
        detail = (comparison.stdout or comparison.stderr or "").strip()
        raise DistError(
            f"压缩产物的来宾可见内容与来源基盘不一致（qemu-img compare 返回 "
            f"{comparison.returncode}），拒绝发布：{detail[:300]}")
    return COMPRESSION_ZSTD


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.2f} TB"


def manifest_path(out_dir: Path) -> Path:
    return Path(out_dir) / MANIFEST_NAME


def load_manifest(out_dir_or_path: Path) -> dict[str, Any]:
    """读取分发清单（接受目录或 `DISTRIBUTION.json` 路径）。"""
    path = Path(out_dir_or_path)
    if path.is_dir():
        path = path / MANIFEST_NAME
    _expect(path.is_file(), f"未找到分发清单：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DistError(f"分发清单无法解析：{path}（{exc}）") from exc
    _expect(isinstance(data, dict) and data.get("format") == DISTRIBUTION_FORMAT,
            f"不是 {DISTRIBUTION_FORMAT} 清单：{path}")
    _expect(isinstance(data.get("entries"), list), f"分发清单缺少 entries：{path}")
    return data


def expected_for_profile(manifest: dict[str, Any], profile_id: str,
                         role: str = BASE_ROLE) -> dict[str, Any] | None:
    for entry in manifest.get("entries", []):
        if entry.get("profile") == profile_id and entry.get("role") == role:
            return entry
    return None


def _merge_entry(out_dir: Path, entry: dict[str, Any]) -> dict[str, Any]:
    path = manifest_path(out_dir)
    if path.is_file():
        manifest = load_manifest(out_dir)
    else:
        manifest = {"schema": 1, "format": DISTRIBUTION_FORMAT, "generated_at": now_iso(),
                    "entries": []}
    key = (entry["profile"], entry["role"])
    manifest["entries"] = [item for item in manifest["entries"]
                           if (item.get("profile"), item.get("role")) != key]
    manifest["entries"].append(entry)
    manifest["entries"].sort(key=lambda item: (item.get("profile", ""), item.get("role", "")))
    manifest["generated_at"] = now_iso()
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_sums(out_dir, manifest["entries"])
    _write_readme(out_dir, manifest)
    return manifest


def _write_sums(out_dir: Path, entries: list[dict[str, Any]]) -> None:
    lines = [f"{entry['sha256']}  {entry['file']}" for entry in entries]
    (Path(out_dir) / SUMS_NAME).write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")


def _write_readme(out_dir: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "# CTFLab 分发目录",
        "",
        f"由 `ctflab dist prepare` 生成；清单时间：{manifest.get('generated_at')}。",
        "机器可读清单见 `DISTRIBUTION.json`，哈希清单见 `SHA256SUMS`。",
        "",
        "| 文件 | 用途 | 大小 | SHA-256 |",
        "|---|---|---|---|",
    ]
    for entry in manifest.get("entries", []):
        role = "基盘（导入用）" if entry.get("role") == BASE_ROLE else "UEFI NVRAM 模板（aarch64 配套）"
        profile = entry.get("profile", "?")
        compression = f"（{entry['compression']} 压缩）" if entry.get("compression") == COMPRESSION_ZSTD else ""
        lines.append(f"| `{entry['file']}` | {profile} {role}{compression} | "
                     f"{human_size(int(entry.get('size', 0)))} | `{entry['sha256']}` |")
    lines += [
        "",
        "## 学生步骤",
        "",
        "1. 下载本目录中的文件（镜像较大，建议一次下完再校验）；",
        f"2. 校验哈希：`shasum -a 256 -c {SUMS_NAME}`（与文件同目录执行）；",
        "3. 导入（清单会自动核对哈希，并套用配套的 UEFI NVRAM 模板）：",
        "",
        "   ```bash",
        "   ctflab import <profile> <基盘文件> --manifest DISTRIBUTION.json",
        "   ```",
        "",
        "4. 启动：`ctflab run <profile>`。",
        "",
        "## 注意",
        "",
        "- `source_base_sha256` 是**老师侧**验证记录中原始基盘文件的哈希（供老师确认分发的是验证过的那份）；",
        "  学生导入后生成的基盘是重新编码的 qcow2，**文件哈希不同但来宾可见内容一致**",
        "  （`content_verified: qemu-img-compare-equal` 表示分发前已用 `qemu-img check`、容量核对与",
        "  `qemu-img compare` 证明内容一致）；",
        "- 分发前请确认第三方镜像（VulnHub 等）的再分发条款；镜像不得提交进任何 Git 仓库；",
        "- 基盘内含的来宾口令只用于本地隔离实验网；不要把本目录用于公开分发。",
        "",
    ]
    (Path(out_dir) / README_NAME).write_text("\n".join(lines), encoding="utf-8")


def prepare_image_entry(out_dir: Path, *, profile_id: str, source: Path, qemu_img: str,
                        file_name: str | None = None, compress: bool = True,
                        base_sha256: str | None = None) -> dict[str, Any]:
    """把一个基盘镜像压缩（或原样复制）进分发目录并登记。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    source = Path(source).expanduser()
    _expect(source.is_file(), f"基盘来源不存在：{source}")
    name = file_name or f"{profile_id}-base.qcow2"
    _expect(Path(name).name == name, f"分发文件名不能包含路径：{name}")
    target = out_dir / name
    temporary = out_dir / f".{name}.partial-{os.getpid()}"
    if temporary.exists():
        temporary.unlink()
    try:
        if compress:
            compression = compress_qcow2(qemu_img, source, temporary)
        else:
            shutil.copy2(source, temporary)
            compression = COMPRESSION_NONE
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    digest = sha256_file(target)
    if base_sha256:
        _expect(_SHA256_RE.match(base_sha256), f"base_sha256 格式不正确：{base_sha256!r}")
    entry = {
        "role": BASE_ROLE,
        "profile": profile_id,
        "file": name,
        "size": target.stat().st_size,
        "sha256": digest,
        "compression": compression,
        "content_verified": "qemu-img-compare-equal" if compression == COMPRESSION_ZSTD else "copied-as-is",
        "source_base_sha256": base_sha256,
        "generated_at": now_iso(),
    }
    _merge_entry(out_dir, entry)
    return entry


def prepare_nvram_entry(out_dir: Path, *, profile_id: str, source: Path,
                        file_name: str | None = None) -> dict[str, Any]:
    """把一个 UEFI NVRAM 模板复制进分发目录并登记。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    source = Path(source).expanduser()
    _expect(source.is_file(), f"NVRAM 模板不存在：{source}")
    name = file_name or f"{profile_id}-uefi-vars.fd"
    _expect(Path(name).name == name, f"分发文件名不能包含路径：{name}")
    target = out_dir / name
    if target.resolve() != source.resolve():
        shutil.copy2(source, target)
    entry = {
        "role": NVRAM_ROLE,
        "profile": profile_id,
        "file": name,
        "size": target.stat().st_size,
        "sha256": sha256_file(target),
        "compression": COMPRESSION_NONE,
        "generated_at": now_iso(),
    }
    _merge_entry(out_dir, entry)
    return entry


def verify_distribution(out_dir: Path) -> dict[str, Any]:
    """复核分发目录：清单内每个文件存在、大小与 SHA-256 与清单一致。"""
    out_dir = Path(out_dir)
    manifest = load_manifest(out_dir)
    problems: list[str] = []
    checked: list[dict[str, Any]] = []
    for entry in manifest["entries"]:
        name = str(entry.get("file", ""))
        _expect(name and Path(name).name == name, f"清单条目文件名不合法：{name!r}")
        _expect(_SHA256_RE.match(str(entry.get("sha256", ""))),
                f"清单条目哈希不合法：{name}")
        path = out_dir / name
        if not path.is_file():
            problems.append(f"清单登记但文件缺失：{name}")
            continue
        size = path.stat().st_size
        if int(entry.get("size", -1)) != size:
            problems.append(f"{name}: 大小不一致（清单 {entry.get('size')}，实际 {size}）")
        digest = sha256_file(path)
        if digest != entry["sha256"]:
            problems.append(f"{name}: SHA-256 不一致（清单 {entry['sha256'][:12]}…，"
                            f"实际 {digest[:12]}…）")
        checked.append({"file": name, "profile": entry.get("profile"), "role": entry.get("role")})
    return {"ok": not problems, "entries": checked, "problems": problems,
            "manifest": str(manifest_path(out_dir))}
