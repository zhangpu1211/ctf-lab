#!/usr/bin/env python3
"""CTFLab Task 6.1：干净 Mac 用户验收脚本。

在“最小 PATH + 独立 HOME”（不含 conda、不含项目开发依赖、不继承 PYTHONPATH）下顺序执行：

1. 校验 release bundle（外层 `.sha256` 旁车 + 包内 MANIFEST 逐文件哈希）；
2. 解包到临时工作目录，确认启动器不含开发解释器硬编码；
3. 执行 `install.sh` 到独立安装目录，并改用安装后生成的启动器；
4. 第一次 `doctor`：断言缺少 PyYAML 时给出可执行安装提示（退出码 1）；
5. 在临时 HOME 建 venv 并安装 PyYAML（联网步骤；失败时如实记录并中止）；
6. 第二次 `doctor`：断言必选依赖全部 OK；
7. `import` → `run --headless` → `health` → `stop` → `reset`；
8. 复核无残留（运行状态文件、overlay），输出 JSON 证据。

边界：本脚本不覆盖 `.app` 安装、QEMU 运行时打包、签名与公证；运行通过不构成 Task 6
完整验收，也不能替代签名分发证据。结果标签只有“通过/失败/跳过（原因）”。
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

TOOLS_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

import ctflab_package  # noqa: E402

HOST_STATE_DIR = pathlib.Path.home() / "Library" / "Application Support" / "CTFLab"
# 最小编译环境 PATH：只保留系统目录与 Homebrew（QEMU 属于文档化的可安装依赖，不属于开发依赖）。
MINIMAL_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"


class StepRecorder:
    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.failed = False

    def record(self, name: str, status: str, detail: str = "", **extra) -> None:
        self.steps.append({"step": name, "status": status, "detail": detail, **extra})
        marker = {"通过": "OK  ", "失败": "FAIL", "跳过": "SKIP"}.get(status, "????")
        print(f"{marker} {name}: {detail}")
        if status == "失败":
            self.failed = True


def run(cmd: list[str], *, env: dict[str, str], timeout: int, cwd: pathlib.Path | None = None) -> dict:
    started = time.time()
    try:
        # macOS 系统工具在最小语言环境下偶尔输出非 UTF-8 字节；证据记录应保留可读替代字符，
        # 而不是因解码异常丢失整次验收结果。
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            env=env,
            timeout=timeout,
            cwd=cwd,
        )
        return {
            "command": " ".join(cmd),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "stdout_tail": result.stdout.strip().splitlines()[-6:],
            "stderr_tail": result.stderr.strip().splitlines()[-6:],
            "seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": " ".join(cmd),
            "returncode": None,
            "timeout": True,
            "stdout": exc.stdout if isinstance(exc.stdout, str) else "",
            "stderr": exc.stderr if isinstance(exc.stderr, str) else "",
            "stdout_tail": (exc.stdout or "").strip().splitlines()[-3:] if isinstance(exc.stdout, str) else [],
            "stderr_tail": (exc.stderr or "").strip().splitlines()[-3:] if isinstance(exc.stderr, str) else [],
            "seconds": round(time.time() - started, 1),
        }


def base_env(home: pathlib.Path) -> dict[str, str]:
    env = {
        "HOME": str(home),
        "PATH": MINIMAL_PATH,
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return env


def find_reuse_source(profile_id: str) -> pathlib.Path | None:
    """原始来源镜像通常已不在本机；默认复用已导入的基础镜像副本（文档化的等价输入）。"""
    state_path = HOST_STATE_DIR / "images" / profile_id / "image.json"
    if not state_path.is_file():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    base = pathlib.Path(str(state.get("base_path", "")))
    return base if base.is_file() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CTFLab 干净 Mac 用户验收（Task 6.1）")
    parser.add_argument("--bundle", type=pathlib.Path, required=True, help="ctflab-<version>-macos-arm64.tar.gz")
    parser.add_argument("--profile", default="smoke", help="用于导入/启动/停止/重置的配置 id，默认 smoke")
    parser.add_argument("--source-image", type=pathlib.Path, help="导入用来源镜像；缺省时复用本机已导入基础镜像副本")
    parser.add_argument("--workdir", type=pathlib.Path, help="工作目录；缺省为临时目录")
    parser.add_argument("--timeout", type=int, default=600, help="单步超时秒数，默认 600")
    args = parser.parse_args(argv)

    recorder = StepRecorder()
    workdir = pathlib.Path(args.workdir or tempfile.mkdtemp(prefix="ctflab-acceptance-")).expanduser()
    workdir.mkdir(parents=True, exist_ok=True)
    home = workdir / "home"
    home.mkdir(exist_ok=True)
    state_dir = workdir / "state"
    env = base_env(home)
    evidence_path = workdir / "acceptance-evidence.json"

    def finish() -> int:
        payload = {
            "schema": 1,
            "format": "ctflab-acceptance",
            "generated_at": ctflab_package.now_iso(),
            "bundle": str(args.bundle),
            "profile": args.profile,
            "workdir": str(workdir),
            "minimal_path": MINIMAL_PATH,
            "steps": recorder.steps,
            "result": "失败" if recorder.failed else "通过",
            "scope_note": (
                "范围＝源码级安装包的干净环境可用性（install/doctor/import/run/health/stop/reset）；"
                "不含 .app、QEMU 运行时打包、签名与公证，不构成 Task 6 完整验收。"
            ),
        }
        evidence_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"证据：{evidence_path}")
        print(f"结论：{payload['result']}")
        return 1 if recorder.failed else 0

    # 1. 校验安装包
    try:
        report = ctflab_package.verify_release_bundle(args.bundle)
    except ctflab_package.PackageError as exc:
        recorder.record("verify-bundle", "失败", str(exc))
        return finish()
    recorder.record("verify-bundle", "通过",
                    f"版本 {report['manifest']['version']}，{report['file_count']} 个文件，SHA-256 {report['sha256'][:12]}…")

    # 2. 解包
    extracted = workdir / "bundle"
    if extracted.exists():
        shutil.rmtree(extracted)
    extracted.mkdir()
    with tarfile.open(args.bundle, "r:gz") as tar:
        tar.extractall(extracted)
    root = next(extracted.glob("ctflab-*"))
    bundled_launcher = root / "tools" / "ctflab"
    if not bundled_launcher.is_file():
        recorder.record("extract", "失败", "包内缺少启动器 tools/ctflab")
        return finish()
    if "/opt/miniconda3" in bundled_launcher.read_text(encoding="utf-8"):
        recorder.record("extract", "失败", "启动器硬编码了开发解释器路径")
        return finish()
    recorder.record("extract", "通过", f"解包到 {root}")

    # 3. 真正执行安装脚本；后续命令均经安装后生成的 launcher 运行，避免把“可解包”误作“可安装”。
    install_prefix = workdir / "installed"
    install_env = dict(env)
    install_env["CTFLAB_PREFIX"] = str(install_prefix)
    install_result = run(["sh", str(root / "install.sh")], env=install_env, timeout=args.timeout)
    launcher = home / "Library" / "Application Support" / "CTFLab" / "bin" / "ctflab"
    installed_ok = (
        install_result["returncode"] == 0
        and launcher.is_file()
        and (launcher.stat().st_mode & 0o111) != 0
        and (install_prefix / "tools" / "ctflab.py").is_file()
    )
    recorder.record(
        "install",
        "通过" if installed_ok else "失败",
        "install.sh 安装完成，后续使用安装后启动器" if installed_ok else "install.sh 未完成可执行安装",
        evidence=install_result,
    )
    if not installed_ok:
        return finish()

    def ctflab(*extra: str) -> list[str]:
        return [str(launcher), "--state-dir", str(state_dir), *extra]

    # 4. 第一次 doctor：最小 PATH 下断言 PyYAML 缺失提示
    first = run(ctflab("doctor"), env=env, timeout=args.timeout)
    first_output = (first.get("stdout") or "") + (first.get("stderr") or "")
    hint_ok = first["returncode"] == 1 and "pip install pyyaml" in first_output
    recorder.record("doctor-missing-deps", "通过" if hint_ok else "失败",
                    "PyYAML 缺失提示正确" if hint_ok else "未按预期提示 PyYAML 安装指引",
                    evidence=first)

    # 5. venv + PyYAML
    venv_dir = workdir / "venv"
    venv_result = run(["python3", "-m", "venv", str(venv_dir)], env=env, timeout=args.timeout)
    if venv_result["returncode"] != 0:
        recorder.record("venv", "失败", "创建 venv 失败", evidence=venv_result)
        return finish()
    pip_env = dict(env)
    pip_env["PATH"] = f"{venv_dir / 'bin'}:{MINIMAL_PATH}"
    pip_result = run([str(venv_dir / "bin" / "python3"), "-m", "pip", "install", "pyyaml"],
                     env=pip_env, timeout=args.timeout)
    if pip_result["returncode"] != 0:
        recorder.record("install-pyyaml", "失败",
                        "pip install pyyaml 失败（联网步骤；无法代表干净用户安装成功）", evidence=pip_result)
        return finish()
    recorder.record("install-pyyaml", "通过", "PyYAML 已装入独立 venv", evidence=pip_result)
    env = pip_env  # 后续步骤使用 venv 解释器（PATH 首位）

    # 6. 第二次 doctor
    second = run(ctflab("doctor"), env=env, timeout=args.timeout)
    recorder.record("doctor-ready", "通过" if second["returncode"] == 0 else "失败",
                    "必选依赖全部就绪" if second["returncode"] == 0 else "doctor 仍有必选项失败",
                    evidence=second)
    if second["returncode"] != 0:
        return finish()

    # 7. 导入 → 启动 → 健康 → 停止 → 重置
    source = pathlib.Path(args.source_image).expanduser() if args.source_image else find_reuse_source(args.profile)
    if not source or not source.is_file():
        recorder.record("prepare-source", "失败",
                        "未找到来源镜像：原始来源缺失时必须显式提供 --source-image")
        return finish()
    local_source = workdir / source.name
    if not local_source.exists():
        shutil.copy2(source, local_source)
    recorder.record("prepare-source", "通过", f"来源：{local_source.name}（复用已导入基础镜像副本）")

    import_result = run(ctflab("import", args.profile, str(local_source)), env=env, timeout=args.timeout)
    recorder.record("import", "通过" if import_result["returncode"] == 0 else "失败",
                    "导入完成" if import_result["returncode"] == 0 else "导入失败", evidence=import_result)
    if import_result["returncode"] != 0:
        return finish()

    run_result = run(ctflab("run", args.profile, "--headless"), env=env, timeout=args.timeout)
    recorder.record("run", "通过" if run_result["returncode"] == 0 else "失败",
                    "无头启动完成" if run_result["returncode"] == 0 else "启动失败", evidence=run_result)
    if run_result["returncode"] != 0:
        return finish()

    health_result = run(ctflab("health", args.profile), env=env, timeout=args.timeout)
    recorder.record("health", "通过" if health_result["returncode"] == 0 else "失败",
                    "健康检查通过" if health_result["returncode"] == 0 else "健康检查失败",
                    evidence=health_result)

    stop_result = run(ctflab("stop", args.profile), env=env, timeout=args.timeout)
    recorder.record("stop", "通过" if stop_result["returncode"] == 0 else "失败",
                    "停止完成" if stop_result["returncode"] == 0 else "停止失败", evidence=stop_result)

    reset_result = run(ctflab("reset", args.profile), env=env, timeout=args.timeout)
    recorder.record("reset", "通过" if reset_result["returncode"] == 0 else "失败",
                    "重置完成" if reset_result["returncode"] == 0 else "重置失败", evidence=reset_result)

    # 8. 残留复核
    residue = []
    runtime_dir = state_dir / "runtime"
    if runtime_dir.is_dir():
        residue += [str(p) for p in runtime_dir.glob("*.json")]
    images_dir = state_dir / "images" / args.profile
    if images_dir.is_dir():
        residue += [str(p) for p in images_dir.glob("overlay*")]
    recorder.record("residue-check", "通过" if not residue else "失败",
                    "无运行状态与 overlay 残留" if not residue else f"存在残留：{residue[:3]}")
    return finish()


if __name__ == "__main__":
    raise SystemExit(main())
