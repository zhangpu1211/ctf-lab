#!/usr/bin/env python3
"""CTFLab Task 6.2 真实 E2E：`.app` 内受控 QEMU 运行时的导入/启动/停止/重置验收。

与 `tools/ctflab_acceptance.py`（Task 6.1 源码包）分离：本脚本针对 `CTFLab.app`，在
“独立 HOME + 最小 PATH（不含 /opt/homebrew/bin、不含 conda）”下执行，证明 QEMU 不是来自宿主：

1. 校验 app（结构/MANIFEST 哈希/动态库引用/SBOM）并记录 app 树哈希；
2. 从 app 启动器执行 `doctor`（第一次：断言缺 PyYAML 提示，且运行时显示 bundled）；
3. 独立 venv 安装 PyYAML 后再次 `doctor`（断言 QEMU 路径位于 app 内）；
4. `sandbox-exec` 拒绝 `/opt/homebrew` 读取，直接用 app 内 QEMU 启动 pc 机器：
   固件必须来自 app（宿主路径被拒仍能启动）；
5. `import`（复用已导入基础镜像副本）→ `run --headless` → `health` → `stop` → `reset`；
6. 运行中从进程命令行证明 QEMU 来自 `CTFLab.app`；
7. 复核无残留、app 树哈希运行前后一致、`codesign --verify --deep --strict` 结果按实际级别记录。

不操作 UTM、不触碰用户已有虚拟机；不写 app 内任何文件。
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

TOOLS_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

import ctflab_app  # noqa: E402

HOST_STATE_DIR = pathlib.Path.home() / "Library" / "Application Support" / "CTFLab"
# 最小编译环境 PATH：系统目录 + 临时 venv（由脚本插入）；**不含** /opt/homebrew/bin。
MINIMAL_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
SANDBOX_PROFILE = """(version 1)
(allow default)
(deny file-read* (subpath "/opt/homebrew"))
"""


class Recorder:
    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.failed = False

    def record(self, name: str, status: str, detail: str = "", **extra) -> None:
        self.steps.append({"step": name, "status": status, "detail": detail, **extra})
        marker = {"通过": "OK  ", "失败": "FAIL", "跳过": "SKIP"}.get(status, "????")
        print(f"{marker} {name}: {detail}")
        if status == "失败":
            self.failed = True


def run(cmd: list[str], *, env: dict[str, str], timeout: int) -> dict:
    started = time.time()
    try:
        # 来宾工具或底层 QEMU 偶尔会输出非 UTF-8 字节；验收记录必须保留可读证据，
        # 不能因为解码异常提前中断清理流程。
        result = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", env=env, timeout=timeout
        )
        return {
            "command": " ".join(cmd),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": " ".join(cmd),
            "returncode": None,
            "timeout": True,
            "stdout": exc.stdout if isinstance(exc.stdout, str) else "",
            "stderr": exc.stderr if isinstance(exc.stderr, str) else "",
            "seconds": round(time.time() - started, 1),
        }


def base_env(home: pathlib.Path) -> dict[str, str]:
    return {
        "HOME": str(home),
        "PATH": MINIMAL_PATH,
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def find_reuse_source(profile_id: str) -> pathlib.Path | None:
    state_path = HOST_STATE_DIR / "images" / profile_id / "image.json"
    if not state_path.is_file():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    base = pathlib.Path(str(state.get("base_path", "")))
    return base if base.is_file() else None


def sandboxed_firmware_check(app: pathlib.Path, timeout: int) -> dict:
    """在拒绝 /opt/homebrew 读的沙盒里启动 app 内 QEMU；能持续运行说明固件来自 app。"""
    qemu = app / ctflab_app.RUNTIME_REL / "bin" / "qemu-system-x86_64"
    env = {"HOME": os.environ.get("HOME", "/tmp"), "PATH": MINIMAL_PATH, "LANG": "C"}
    cmd = ["sandbox-exec", "-p", SANDBOX_PROFILE, str(qemu),
           "-machine", "pc", "-accel", "tcg", "-m", "128", "-display", "none",
           "-serial", "none", "-monitor", "none", "-nodefaults", "-S"]
    return run(cmd, env=env, timeout=timeout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CTFLab Task 6.2：.app 受控运行时 E2E")
    parser.add_argument("--app", type=pathlib.Path, required=True, help="CTFLab.app 路径")
    parser.add_argument("--profile", default="smoke", help="用于导入/启动的配置 id，默认 smoke")
    parser.add_argument("--source-image", type=pathlib.Path, help="导入来源镜像；缺省复用已导入基础镜像副本")
    parser.add_argument("--workdir", type=pathlib.Path, help="工作目录；缺省为临时目录（结束后保留）")
    parser.add_argument("--timeout", type=int, default=600, help="单步超时秒数，默认 600")
    args = parser.parse_args(argv)

    recorder = Recorder()
    workdir = pathlib.Path(args.workdir or tempfile.mkdtemp(prefix="ctflab-app-e2e-")).expanduser()
    workdir.mkdir(parents=True, exist_ok=True)
    home = workdir / "home"
    home.mkdir(exist_ok=True)
    state_dir = workdir / "state"
    env = base_env(home)
    app = pathlib.Path(args.app).expanduser().resolve()
    launcher = app / ctflab_app.LAUNCHER_REL
    evidence_path = workdir / "app-e2e-evidence.json"

    def finish() -> int:
        payload = {
            "schema": 1,
            "format": "ctflab-app-e2e",
            "generated_at": ctflab_app.now_iso(),
            "app": str(app),
            "profile": args.profile,
            "workdir": str(workdir),
            "minimal_path": MINIMAL_PATH,
            "steps": recorder.steps,
            "result": "失败" if recorder.failed else "通过",
            "scope_note": (
                "范围＝.app 内受控 QEMU 运行时的导入/启动/停止/重置与固件来源证明；"
                "不含公证（未执行）、不含 UTM、不含用户既有虚拟机。"
            ),
        }
        evidence_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        print(f"证据：{evidence_path}")
        print(f"结论：{payload['result']}")
        return 1 if recorder.failed else 0

    if not launcher.is_file():
        recorder.record("app-launcher", "失败", f"未找到 app 启动器：{launcher}")
        return finish()

    # 1. 校验 app 与基线哈希
    try:
        report = ctflab_app.verify_app(app)
    except ctflab_app.AppBuildError as exc:
        recorder.record("verify-app", "失败", str(exc))
        return finish()
    hash_before = ctflab_app.app_tree_hash(app)
    recorder.record("verify-app", "通过",
                    f"版本 {report['version']}，{report['file_count']} 文件；"
                    f"签名 {report['signature']['level']}；树哈希 {hash_before[:12]}…")

    def ctflab(*extra: str) -> list[str]:
        return [str(launcher), "--state-dir", str(state_dir), *extra]

    # 2. 第一次 doctor：最小 PATH 下 PyYAML 缺失 + bundled 运行时
    first = run(ctflab("doctor"), env=env, timeout=args.timeout)
    first_out = first["stdout"] + first["stderr"]
    hint_ok = first["returncode"] == 1 and "pip install pyyaml" in first_out
    recorder.record("doctor-missing-deps", "通过" if hint_ok else "失败",
                    "PyYAML 缺失提示正确" if hint_ok else "未按预期提示 PyYAML",
                    evidence=first)

    # 3. venv + PyYAML，再 doctor：断言 QEMU 路径来自 app
    venv_dir = workdir / "venv"
    venv_result = run(["python3", "-m", "venv", str(venv_dir)], env=env, timeout=args.timeout)
    if venv_result["returncode"] != 0:
        recorder.record("venv", "失败", "创建 venv 失败", evidence=venv_result)
        return finish()
    env = dict(env)
    env["PATH"] = f"{venv_dir / 'bin'}:{MINIMAL_PATH}"
    pip_result = run([str(venv_dir / "bin" / "python3"), "-m", "pip", "install", "pyyaml"],
                     env=env, timeout=args.timeout)
    if pip_result["returncode"] != 0:
        recorder.record("install-pyyaml", "失败", "pip install pyyaml 失败（联网步骤）", evidence=pip_result)
        return finish()
    recorder.record("install-pyyaml", "通过", "PyYAML 已装入独立 venv")

    second = run(ctflab("doctor"), env=env, timeout=args.timeout)
    second_out = second["stdout"] + second["stderr"]
    bundled_ok = (second["returncode"] == 0
                  and "运行时：bundled" in second_out
                  and str(app / ctflab_app.RUNTIME_REL) in second_out
                  and "/opt/homebrew" not in second_out)
    recorder.record("doctor-bundled-runtime", "通过" if bundled_ok else "失败",
                    "doctor 显示使用 app 内运行时且无宿主 QEMU" if bundled_ok
                    else "doctor 未证明使用 app 内运行时", evidence=second)
    if not bundled_ok:
        return finish()

    # 4. 沙盒固件来源检查：拒绝 /opt/homebrew 后 app 内 QEMU 仍能启动
    if shutil.which("sandbox-exec"):
        sandbox_result = sandboxed_firmware_check(app, timeout=8)
        stderr = sandbox_result["stderr"]
        firmware_error = any(token in stderr for token in ("could not load", "failed to find",
                                                           "No such file or directory",
                                                           "could not open"))
        ok = sandbox_result.get("timeout") is True and not firmware_error
        recorder.record("firmware-provenance", "通过" if ok else "失败",
                        "拒绝 /opt/homebrew 读取后 app 内 QEMU 仍可启动（固件来自 app）" if ok
                        else f"沙盒内启动异常：{stderr.strip()[:160]}", evidence=sandbox_result)
        if not ok:
            return finish()
    else:
        recorder.record("firmware-provenance", "跳过", "本机没有 sandbox-exec，无法证明固件来源")

    # 5. 导入 → 启动 → 健康 → 停止 → 重置
    source = pathlib.Path(args.source_image).expanduser() if args.source_image \
        else find_reuse_source(args.profile)
    if not source or not source.is_file():
        recorder.record("prepare-source", "失败", "未找到来源镜像（可显式 --source-image）")
        return finish()
    local_source = workdir / source.name
    if not local_source.exists():
        shutil.copy2(source, local_source)
    recorder.record("prepare-source", "通过", f"来源：{local_source.name}")

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

    # 6. 进程命令行证明 QEMU 来自 app
    runtime_state = state_dir / "runtime" / args.profile / "run.json"
    provenance_ok = False
    provenance_detail = "未找到运行状态文件"
    if runtime_state.is_file():
        state = json.loads(runtime_state.read_text(encoding="utf-8"))
        pid = int(state.get("pid", 0))
        ps = run(["ps", "-o", "command=", "-p", str(pid)], env=env, timeout=30)
        command = ps["stdout"].strip()
        provenance_ok = (str(app) in command and "/opt/homebrew" not in command)
        provenance_detail = command[:200] if command else "进程命令行读取为空"
    recorder.record("qemu-provenance", "通过" if provenance_ok else "失败", provenance_detail)

    health_result = run(ctflab("health", args.profile), env=env, timeout=args.timeout)
    recorder.record("health", "通过" if health_result["returncode"] == 0 else "失败",
                    "DHCP/SSH 健康检查通过" if health_result["returncode"] == 0 else "健康检查失败",
                    evidence=health_result)

    stop_result = run(ctflab("stop", args.profile), env=env, timeout=args.timeout)
    recorder.record("stop", "通过" if stop_result["returncode"] == 0 else "失败",
                    "停止完成" if stop_result["returncode"] == 0 else "停止失败", evidence=stop_result)

    reset_result = run(ctflab("reset", args.profile), env=env, timeout=args.timeout)
    recorder.record("reset", "通过" if reset_result["returncode"] == 0 else "失败",
                    "重置完成" if reset_result["returncode"] == 0 else "重置失败", evidence=reset_result)

    # 7. 残留、app 不变与签名复核
    residue: list[str] = []
    runtime_dir = state_dir / "runtime"
    if runtime_dir.is_dir():
        residue += [str(path) for path in runtime_dir.rglob("run.json")]
        residue += [str(path) for path in runtime_dir.glob("network-*.json")]
    images_dir = state_dir / "images" / args.profile
    if images_dir.is_dir():
        residue += [str(path) for path in images_dir.glob("overlay*")]
    recorder.record("residue-check", "通过" if not residue else "失败",
                    "无运行状态与 overlay 残留" if not residue else f"存在残留：{residue[:3]}")

    hash_after = ctflab_app.app_tree_hash(app)
    recorder.record("app-unchanged", "通过" if hash_after == hash_before else "失败",
                    f"运行前后树哈希一致（{hash_after[:12]}…）" if hash_after == hash_before
                    else f"app 内容发生变化：{hash_before[:12]}… → {hash_after[:12]}…")

    signature = ctflab_app.codesign_verify(app)
    recorder.record("codesign-verify",
                    "通过" if signature["verify_returncode"] == 0 else "失败",
                    f"级别 {signature['level']}；codesign --verify --deep --strict 返回 "
                    f"{signature['verify_returncode']}；公证：{signature['notarization_status']}",
                    evidence=signature)
    return finish()


if __name__ == "__main__":
    raise SystemExit(main())
