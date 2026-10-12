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
from typing import Any, Callable

DISTRIBUTION_FORMAT = "ctflab-distribution"
MANIFEST_NAME = "DISTRIBUTION.json"
SUMS_NAME = "SHA256SUMS"
README_NAME = "README.md"
COMPRESSION_ZSTD = "zstd"
COMPRESSION_NONE = "none"
BASE_ROLE = "base"
NVRAM_ROLE = "nvram"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# ---- 内容包（schema 2）：在分发目录格式上扩展 profile/doc 角色与包元数据 ----
# 设计边界：目录式内容包不引入新的压缩归档格式；包必须自包含（base/nvram 引用的
# profile 必须随包提供 YAML），导入后由状态目录管理，不依赖原包路径。
PACK_SCHEMA = 2
PROFILE_ROLE = "profile"
DOC_ROLE = "doc"
PACK_ROLES = (BASE_ROLE, NVRAM_ROLE, PROFILE_ROLE, DOC_ROLE)
PACK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
DOC_SUFFIXES = (".md", ".txt", ".pdf", ".png", ".jpg", ".jpeg")
# 内容包 profile 允许的顶层键：运行器读取的白名单字段 + 纯声明的附属块。
PACK_PROFILE_TOP_KEYS = frozenset({
    "schema", "id", "name", "version", "guest", "disk", "network",
    "readiness", "verification", "description",
})
PACK_PROFILE_GUEST_KEYS = frozenset({"architecture", "firmware", "machine", "memory_mb", "cpus"})
PACK_PROFILE_DISK_KEYS = frozenset({"format", "bus", "controller"})
PACK_PROFILE_NETWORK_KEYS = frozenset({"adapter", "mac", "lab_ip", "segment", "internet", "host_forwards"})


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


def verify_distribution(out_dir: Path, *, profile_status: "Callable[[str], dict[str, Any]] | None" = None,
                        runner_version: str | None = None) -> dict[str, Any]:
    """复核分发目录：清单内每个文件存在、大小与 SHA-256 与清单一致。

    schema 2 内容包额外做结构校验（角色白名单、自包含、路径/符号链接安全），
    并在报告中附 `pack` 摘要；schema 1 分发目录行为保持不变。
    """
    out_dir = Path(out_dir)
    manifest = load_manifest(out_dir)
    parsed_pack: dict[str, Any] | None = None
    if int(manifest.get("schema", 1)) == PACK_SCHEMA:
        parsed_pack = parse_pack(manifest, runner_version=runner_version)
    problems: list[str] = []
    checked: list[dict[str, Any]] = []
    for entry in manifest["entries"]:
        name = str(entry.get("file", ""))
        _expect(name and Path(name).name == name, f"清单条目文件名不合法：{name!r}")
        _expect(_SHA256_RE.match(str(entry.get("sha256", ""))),
                f"清单条目哈希不合法：{name}")
        row: dict[str, Any] = {
            "file": name,
            "profile": entry.get("profile"),
            "role": entry.get("role"),
            "expected_size": entry.get("size"),
            "expected_sha256": entry["sha256"],
        }
        path: Path
        if parsed_pack is not None:
            try:
                path = resolve_pack_file(out_dir, name)
            except DistError as exc:
                problems.append(f"{name}: {exc}")
                row.update({"status": "invalid-path", "problem": str(exc)})
                checked.append(row)
                continue
        else:
            path = out_dir / name
        if not path.is_file():
            problems.append(f"清单登记但文件缺失：{name}")
            row.update({"status": "missing", "problem": "文件缺失"})
            checked.append(row)
            continue
        size = path.stat().st_size
        row["size"] = size
        digest = sha256_file(path)
        row["sha256"] = digest
        size_ok = int(entry.get("size", -1)) == size
        hash_ok = digest == entry["sha256"]
        size_problem = f"大小不一致（清单 {entry.get('size')}，实际 {size}）"
        hash_problem = (f"SHA-256 不一致（清单 {entry['sha256'][:12]}…，"
                        f"实际 {digest[:12]}…）")
        # 两项都检查、都上报（沿用既有文本语义）；行状态取更严重的一类。
        if not size_ok:
            problems.append(f"{name}: {size_problem}")
        if not hash_ok:
            problems.append(f"{name}: {hash_problem}")
        if size_ok and hash_ok:
            row.update({"status": "ok", "problem": None})
        elif not hash_ok:
            row.update({"status": "sha256-mismatch", "problem": hash_problem})
        else:
            row.update({"status": "size-mismatch", "problem": size_problem})
        checked.append(row)
    ok_count = sum(1 for row in checked if row.get("status") == "ok")
    report = {
        "ok": not problems,
        "entries": checked,
        "problems": problems,
        "manifest": str(manifest_path(out_dir)),
        "dir": str(out_dir),
        "summary": {"total": len(checked), "ok": ok_count, "failed": len(problems)},
    }
    if parsed_pack is not None:
        report["pack"] = pack_summary(out_dir, manifest, parsed_pack,
                                      profile_status=profile_status,
                                      runner_version=runner_version)
    return report


# ---------------------------------------------------------------------------
# 内容包（schema 2）解析与制作
# ---------------------------------------------------------------------------


def _pack_error(message: str) -> DistError:
    return DistError(message)


def parse_pack(manifest: dict[str, Any], *, runner_version: str | None = None) -> dict[str, Any]:
    """解析并校验 schema 2 内容包结构；不符合直接抛 DistError。

    校验内容：包元数据（id/版本/最低运行器约束）、角色白名单、每条登记的
    文件名与哈希格式、base/nvram 的自包含（必须随包带 profile）、声明块归属。
    这里只看清单数据；文件本体的大小/哈希由 verify_distribution 逐个实测。
    """
    pack = manifest.get("pack")
    if not isinstance(pack, dict):
        raise _pack_error("内容包清单缺少 pack 元数据对象")
    pack_id = str(pack.get("id", ""))
    if not PACK_ID_RE.match(pack_id):
        raise _pack_error(f"内容包 id 不合法（小写字母/数字/短横线）：{pack_id!r}")
    version = str(pack.get("version", ""))
    if not VERSION_RE.match(version):
        raise _pack_error(f"内容包版本必须形如 X.Y.Z：{version!r}")
    requires = str(pack.get("requires_runner", ""))
    if not _RUNNER_CONSTRAINT_RE.match(requires):
        raise _pack_error(f"requires_runner 必须是 '>=X.Y.Z'、'>X.Y.Z' 或 '==X.Y.Z'：{requires!r}")
    if runner_version is not None and not _runner_satisfied(runner_version, requires):
        raise _pack_error(f"内容包要求运行器 {requires}，当前 {runner_version} 不满足")

    notes = pack.get("notes", [])
    if not isinstance(notes, list) or any(not isinstance(item, str) for item in notes):
        raise _pack_error("pack.notes 必须是字符串数组")

    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise _pack_error("内容包清单 entries 不能为空")

    profiles: dict[str, dict[str, Any]] = {}
    docs: list[dict[str, Any]] = []
    seen_roles: set[tuple[str, str]] = set()
    seen_files: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise _pack_error("entries 含非对象条目")
        role = str(entry.get("role", ""))
        if role not in PACK_ROLES:
            raise _pack_error(f"内容包不支持的角色：{role!r}（允许：{', '.join(PACK_ROLES)}）")
        name = str(entry.get("file", ""))
        if not name or Path(name).name != name or name in {".", ".."}:
            raise _pack_error(f"清单条目文件名不能包含路径：{name!r}")
        if name in seen_files:
            raise _pack_error(f"清单重复登记同一文件：{name}")
        seen_files.add(name)
        if not _SHA256_RE.match(str(entry.get("sha256", ""))):
            raise _pack_error(f"清单条目哈希不合法：{name}")
        size = entry.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise _pack_error(f"清单条目大小必须是正整数：{name}")
        if role in (BASE_ROLE, NVRAM_ROLE, PROFILE_ROLE):
            profile_id = str(entry.get("profile", ""))
            if not PACK_ID_RE.match(profile_id):
                raise _pack_error(f"条目 {name} 的 profile id 不合法：{profile_id!r}")
            key = (profile_id, role)
            if key in seen_roles:
                raise _pack_error(f"清单重复登记 {profile_id} 的 {role} 条目")
            seen_roles.add(key)
            slot = profiles.setdefault(profile_id, {"profile": profile_id,
                                                    BASE_ROLE: None, NVRAM_ROLE: None,
                                                    PROFILE_ROLE: None})
            slot[role] = entry
            if role == PROFILE_ROLE and name != f"{profile_id}.yaml":
                raise _pack_error(f"profile 登记文件名必须是 <id>.yaml：{name}")
        else:
            if not name.lower().endswith(DOC_SUFFIXES):
                raise _pack_error(f"说明文件只允许 {'、'.join(DOC_SUFFIXES)}：{name}")
            docs.append(entry)

    for profile_id, slot in profiles.items():
        if slot[PROFILE_ROLE] is None:
            raise _pack_error(
                f"内容包必须自包含：{profile_id} 有 base/nvram 登记但没有随包 profile 条目")

    claims = manifest.get("claims", {})
    if not isinstance(claims, dict):
        raise _pack_error("claims 必须是对象（profile id -> 声明）")
    for profile_id, claim in claims.items():
        if profile_id not in profiles:
            raise _pack_error(f"claims 引用了包外 profile：{profile_id}")
        if not isinstance(claim, dict):
            raise _pack_error(f"claims.{profile_id} 必须是对象")

    return {
        "id": pack_id,
        "name": str(pack.get("name") or pack_id),
        "version": version,
        "requires_runner": requires,
        "notes": [str(item) for item in notes],
        "profiles": profiles,
        "docs": docs,
        "claims": claims,
    }


def resolve_pack_file(out_dir: Path, name: str) -> Path:
    """把清单登记名解析为包目录内的普通文件；拒绝穿越、绝对路径与符号链接。"""
    if not isinstance(name, str) or not name or name in {".", ".."}:
        raise _pack_error(f"清单条目文件名不合法：{name!r}")
    if "\x00" in name or "\\" in name or Path(name).name != name:
        raise _pack_error(f"清单条目文件名不能包含路径分隔符：{name!r}")
    root = Path(out_dir).resolve()
    candidate = root / name
    if candidate.is_symlink():
        raise _pack_error(f"包内文件不允许是符号链接：{name}")
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise _pack_error(f"清单条目解析后越出包目录：{name}")
    return candidate


def _version_tuple(text: str) -> tuple[int, int, int]:
    match = VERSION_RE.match(str(text))
    _expect(match is not None, f"版本号必须形如 X.Y.Z：{text!r}")
    return tuple(int(part) for part in str(text).split("."))  # type: ignore[return-value]


def _runner_constraint_parts(constraint: str) -> tuple[str, tuple[int, int, int]]:
    """把 '>=X.Y.Z' / '>X.Y.Z' / '==X.Y.Z' 拆成运算符与版本三元组（容忍空格）。"""
    match = _RUNNER_CONSTRAINT_RE.match(str(constraint))
    _expect(match is not None, f"不支持的运行器版本约束：{constraint!r}")
    return match.group(1), _version_tuple(match.group(2))


def _runner_satisfied(current: str, constraint: str) -> bool:
    operator, target = _runner_constraint_parts(constraint)
    value = _version_tuple(current)
    if operator == ">=":
        return value >= target
    if operator == ">":
        return value > target
    return value == target


_RUNNER_CONSTRAINT_RE = re.compile(r"^(>=|>|==)\s*(\d+\.\d+\.\d+)$")


def pack_summary(out_dir: Path, manifest: dict[str, Any], parsed: dict[str, Any], *,
                 profile_status: "Callable[[str], dict[str, Any]] | None" = None,
                 runner_version: str | None = None) -> dict[str, Any]:
    """生成给人/GUI 看的包摘要：节点资源、说明文件、声明与配置冲突预览。"""
    del manifest
    nodes: list[dict[str, Any]] = []
    for profile_id in sorted(parsed["profiles"]):
        slot = parsed["profiles"][profile_id]
        node: dict[str, Any] = {
            "profile": profile_id,
            "has_base": slot[BASE_ROLE] is not None,
            "has_nvram": slot[NVRAM_ROLE] is not None,
        }
        yaml_path = out_dir / slot[PROFILE_ROLE]["file"]
        data: dict[str, Any] | None = None
        try:
            import yaml  # noqa: PLC0415
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = None
        except Exception:  # noqa: BLE001  摘要尽力展示；权威校验在导入时进行
            data = None
        if data:
            guest = data.get("guest") or {}
            node.update({
                "name": data.get("name"),
                "architecture": guest.get("architecture"),
                "firmware": guest.get("firmware"),
                "memory_mb": guest.get("memory_mb"),
                "cpus": guest.get("cpus"),
            })
        if profile_status is not None:
            node["local"] = profile_status(profile_id)
        nodes.append(node)
    runner_satisfied: bool | None = None
    if runner_version is not None:
        runner_satisfied = _runner_satisfied(runner_version, parsed["requires_runner"])
    return {
        "id": parsed["id"],
        "name": parsed["name"],
        "version": parsed["version"],
        "requires_runner": parsed["requires_runner"],
        "runner": runner_version,
        "runner_satisfied": runner_satisfied,
        "notes": parsed["notes"],
        "nodes": nodes,
        "docs": [str(entry.get("file")) for entry in parsed["docs"]],
        "claims": sorted(str(key) for key in parsed["claims"]),
        "claims_note": "包内验收声明由制作者提供，仅供参考；导入后本机验收状态不变，仍需实际验收。",
    }


def _write_pack_readme(out_dir: Path, manifest: dict[str, Any]) -> None:
    pack = manifest["pack"]
    entries = manifest["entries"]
    lines = [
        f"# CTFLab 内容包：{pack.get('name')}（{pack.get('id')} v{pack.get('version')}）",
        "",
        f"由 `ctflab dist make-pack` 生成；清单时间：{manifest.get('generated_at')}。",
        f"最低运行器要求：`{pack.get('requires_runner')}`。",
        "",
        "## 包内文件",
        "",
        "| 文件 | 角色 | 大小 | SHA-256 |",
        "|---|---|---|---|",
    ]
    role_names = {BASE_ROLE: "基盘镜像", NVRAM_ROLE: "UEFI NVRAM 模板",
                  PROFILE_ROLE: "节点配置", DOC_ROLE: "使用说明"}
    for entry in entries:
        lines.append(f"| `{entry['file']}` | {role_names.get(entry.get('role'), entry.get('role'))} | "
                     f"{human_size(int(entry.get('size', 0)))} | `{entry['sha256']}` |")
    lines += [
        "",
        "## 接收者步骤",
        "",
        "1. 校验哈希：`shasum -a 256 -c SHA256SUMS`（与文件同目录执行）；",
        "2. 导入（先整体校验，再安装配置并导入基盘，不自动启动）：",
        "",
        "   ```bash",
        "   ctflab dist install --dir <本目录>",
        "   ```",
        "",
        f"3. 启动：`ctflab run <profile>`（GUI 中选中本文件夹后同样会先校验再导入）。",
        "",
        "## 注意",
        "",
        "- `claims`/配置中的 `verification` 段是制作者的验收声明，仅供参考；",
        "  导入不会把任何节点标记为本机已验证，实际验收以本机 probe/matrix 证据为准。",
        "- 导入后的配置与基盘由状态目录管理；本目录移走或删除后已导入节点仍可启动。",
        "",
    ]
    (Path(out_dir) / README_NAME).write_text("\n".join(lines), encoding="utf-8")


def make_pack(out_dir: Path, *, pack_id: str, profile_yaml: Path, base_image: Path,
              name: str | None = None, version: str = "1.0.0",
              requires_runner: str | None = None, nvram: Path | None = None,
              docs: "list[Path] | tuple[Path, ...]" = (),
              profile_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """制作 schema 2 内容包目录（复制文件 + 写清单/校验/说明）。

    只复制、不改写来源；目标目录必须不存在或为空（拒绝覆盖已有内容）。
    `profile_data` 由调用方在完整校验（白名单+内容包约束）后传入，避免这里
    重复实现运行器校验；未传时按原始 YAML 复制但仍要求 id/文件名一致。
    """
    out_dir = Path(out_dir)
    if not PACK_ID_RE.match(str(pack_id)):
        raise _pack_error(f"内容包 id 不合法（小写字母/数字/短横线）：{pack_id!r}")
    if not VERSION_RE.match(str(version)):
        raise _pack_error(f"内容包版本必须形如 X.Y.Z：{version!r}")
    if requires_runner is None:
        import ctflab  # noqa: PLC0415  函数内导入，取当前运行器版本作为默认约束
        requires_runner = f">={ctflab.CTFLAB_VERSION}"
    if not _RUNNER_CONSTRAINT_RE.match(str(requires_runner)):
        raise _pack_error(f"requires_runner 必须是 '>=X.Y.Z'、'>X.Y.Z' 或 '==X.Y.Z'：{requires_runner!r}")

    profile_yaml = Path(profile_yaml)
    base_image = Path(base_image)
    _expect(profile_yaml.is_file() and not profile_yaml.is_symlink(),
            f"profile YAML 不存在或是符号链接：{profile_yaml}")
    _expect(base_image.is_file() and not base_image.is_symlink(),
            f"基盘镜像不存在或是符号链接：{base_image}")
    if profile_data is None:
        import yaml  # noqa: PLC0415
        profile_data = yaml.safe_load(profile_yaml.read_text(encoding="utf-8"))
    _expect(isinstance(profile_data, dict), f"profile 不是有效的 YAML 映射：{profile_yaml}")
    profile_id = str(profile_data.get("id", ""))
    if profile_id != Path(profile_yaml.name).stem:
        raise _pack_error(f"profile id 与文件名不一致：{profile_yaml.name}（id={profile_id!r}）")
    if profile_id == pack_id:
        raise _pack_error("内容包 id 与节点 profile id 相同；包 id 描述整个包，请换一个名字")

    if out_dir.exists():
        _expect(out_dir.is_dir() and not out_dir.is_symlink(), f"目标不是普通目录：{out_dir}")
        _expect(not any(out_dir.iterdir()), f"目标目录非空，拒绝覆盖：{out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    def _copy_into(source: Path, file_name: str) -> dict[str, Any]:
        target = out_dir / file_name
        temporary = out_dir / f".{file_name}.partial-{os.getpid()}"
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "file": file_name,
            "size": target.stat().st_size,
            "sha256": sha256_file(target),
        }

    entries: list[dict[str, Any]] = []
    profile_entry = _copy_into(profile_yaml, f"{profile_id}.yaml")
    entries.append({"role": PROFILE_ROLE, "profile": profile_id, **profile_entry,
                    "compression": COMPRESSION_NONE})
    base_suffix = base_image.suffix.lower() or ".qcow2"
    base_entry = _copy_into(base_image, f"{profile_id}-base{base_suffix}")
    entries.append({"role": BASE_ROLE, "profile": profile_id, **base_entry,
                    "compression": COMPRESSION_NONE, "content_verified": "copied-as-is"})
    if nvram is not None:
        nvram_path = Path(nvram)
        _expect(nvram_path.is_file() and not nvram_path.is_symlink(),
                f"NVRAM 模板不存在或是符号链接：{nvram_path}")
        entries.append({"role": NVRAM_ROLE, "profile": profile_id,
                        **_copy_into(nvram_path, f"{profile_id}-uefi-vars.fd"),
                        "compression": COMPRESSION_NONE})
    used_names = {entry["file"] for entry in entries}
    doc_files: list[str] = []
    for doc in docs:
        doc_path = Path(doc)
        doc_name = doc_path.name
        _expect(doc_path.is_file() and not doc_path.is_symlink(), f"说明文件不存在或是符号链接：{doc_path}")
        _expect(doc_name.lower().endswith(DOC_SUFFIXES),
                f"说明文件只允许 {'、'.join(DOC_SUFFIXES)}：{doc_name}")
        _expect(doc_name not in used_names, f"说明文件名与包内文件冲突：{doc_name}")
        _expect(doc_name not in {MANIFEST_NAME, SUMS_NAME, README_NAME},
                f"说明文件名保留：{doc_name}")
        used_names.add(doc_name)
        doc_files.append(doc_name)
        entries.append({"role": DOC_ROLE, "file": doc_name, **{
            key: value for key, value in _copy_into(doc_path, doc_name).items()}})

    claims: dict[str, Any] = {}
    verification = profile_data.get("verification")
    if isinstance(verification, dict):
        claims[profile_id] = verification
    generated_at = now_iso()
    manifest = {
        "schema": PACK_SCHEMA,
        "format": DISTRIBUTION_FORMAT,
        "generated_at": generated_at,
        "pack": {
            "id": pack_id,
            "name": str(name or pack_id),
            "version": version,
            "requires_runner": requires_runner,
            "notes": ["由 ctflab dist make-pack 生成；包内验收声明仅为制作者声明，不代表接收方本机验收。"],
        },
        "entries": entries,
        **({"claims": claims} if claims else {}),
    }
    (out_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_sums(out_dir, entries)
    _write_pack_readme(out_dir, manifest)
    parse_pack(manifest)  # 制作者侧也走同一解析器，防止生成即非法的清单
    return {"dir": str(out_dir), "manifest": manifest, "entries": entries}
