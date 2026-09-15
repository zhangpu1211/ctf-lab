#!/usr/bin/env python3
"""CTFLab Task 6.3A/6.3B：`CTFLab.app` 的 Kali ARM64 + UEFI 真实验收（含内置 Python 运行时）。

只做验收与必要修复：不签名、不公证、不做动态分辨率、不操作 UTM 与用户已有虚拟机。

流程（每步记录 JSON 证据，任一步失败即停止）：

1. 复核 App：结构/MANIFEST/动态库引用/SBOM/codesign，并与 `CTFLab.app.sha256` 旁车交叉核对；
2. 独立 HOME + 最小 PATH（**不含 `/opt/homebrew/bin`**）：首次 doctor 必须 0 退出——解释器与
   PyYAML 来自 App 内（无 venv/pip），aarch64 QEMU、`edk2-aarch64-code.fd`、`edk2-arm-vars.fd`
   全部来自 App；`sandbox-exec` 拒绝宿主 Python 位置后 doctor 仍通过（非空证明）；
3. `sandbox-exec` 拒绝 `/opt/homebrew` 读取后，直接用 App 内 `qemu-system-aarch64` + App 内固件
   启动 virt 机器（证明固件/运行时来源）；
4. 复用经哈希验证的 `kali-arm64` 基盘与原始 RAW NVRAM 的**副本**（原文件只读校验）；
5. 启动 kali：QEMU 进程来自 App 内；截屏 OCR 判定 UEFI 引导到登录界面（而非 UEFI Shell）；
6. 派生 NVRAM 可写；App 内模板与用户原始 RAW NVRAM 哈希不变；
7. 健康检查（DHCP+SSH）通过；Kali 在隔离实验网内可达 smoke/basic，公网不可达（经 SSH 来宾内验证）；
8. 来宾内正常关机 → 再次启动（重启）→ 再次健康检查 → 停止 → reset；
9. 复核：无 QEMU/QMP/网络/overlay 残留、原始基盘与 RAW NVRAM 哈希不变、App 内无 `__pycache__`
   写入、App 树哈希不变、`qemu-img check` 通过。
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

TOOLS_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

import ctflab  # noqa: E402
import ctflab_app  # noqa: E402

HOST_STATE_DIR = pathlib.Path.home() / "Library" / "Application Support" / "CTFLab"
MINIMAL_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
SANDBOX_PROFILE = (
    '(version 1)\n(allow default)\n(deny file-read* (subpath "/opt/homebrew"))\n'
    '(deny file-read* (subpath "/opt/miniconda3"))\n(deny file-read* (subpath "/usr/local"))\n'
    '(deny file-read* (subpath "/Library/Frameworks/Python.framework"))\n'
    '(deny file-read* (literal "/usr/bin/python3"))\n'
)
KALI_SSH_PORT = 12210
SMOKE_IP = "192.168.242.20"
BASIC_IP = "192.168.242.21"


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


def run(cmd: list[str], *, env: dict[str, str], timeout: int, redact: list[str] | None = None,
        input_text: str | None = None) -> dict:
    display = " ".join(cmd)
    for secret in redact or []:
        if secret:
            display = display.replace(secret, "***")
    started = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", env=env,
                                timeout=timeout, input=input_text)
        return {
            "command": display,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "seconds": round(time.time() - started, 1),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": display,
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


def ocr_screen_text(png: pathlib.Path, workdir: pathlib.Path) -> str:
    """多模式 OCR：原图与 2 倍放大图分别用 psm 6/11/12，取并集提升图形界面的识别率。"""
    sips = "/usr/bin/sips"
    tesseract = "/opt/homebrew/bin/tesseract"
    if not png.is_file() or not pathlib.Path(tesseract).is_file():
        return ""
    scaled = workdir / "screen-2x.png"
    subprocess.run([sips, "-Z", "2560", str(png), "--out", str(scaled)], capture_output=True)
    texts: list[str] = []
    for image in (png, scaled):
        if not image.is_file():
            continue
        for psm in ("6", "11", "12"):
            try:
                result = subprocess.run([tesseract, str(image), "stdout", "-l", "eng", "--psm", psm],
                                        capture_output=True, timeout=30)
            except subprocess.TimeoutExpired:
                continue
            # tesseract 的 stderr 可能不是 UTF-8：按字节读取后容错解码
            texts.append(result.stdout.decode("utf-8", errors="replace"))
    return "\n".join(texts)


def classify_kali_screen(text: str) -> dict:
    """Kali 专用屏幕判定：GRUB/固件画面优先，品牌文字本身不能证明登录就绪。"""
    base = ctflab.classify_screen_text(text)
    lowered = text.lower()
    bootloader_signals = [label for label, pattern in (
        ("GRUB 高级选项", r"advanced\s+options\s+for\s+kali"),
        ("固件设置菜单", r"firmware\s+settings"),
        ("GRUB 倒计时", r"booting\s+in\s+\d+\s+seconds?"),
    ) if re.search(pattern, lowered)]
    if bootloader_signals:
        return {
            "classification": "boot_progress",
            "confidence": "high",
            "matched_signals": bootloader_signals,
            "all_signals": base.get("all_signals", {}),
            "warnings": base.get("warnings", []),
        }

    greeter_signals = [label for label, pattern in (
        ("登录按钮", r"\blog\s+in\b"),
        ("口令提示", r"\bpassword\b|enter\s+your"),
        ("显示管理器", r"\blightdm\b"),
    ) if re.search(pattern, lowered)]
    # 渐变背景会让 Tesseract 把 “Log In” 识别成 “Log!”；仅在同时识别到 Kali 品牌时
    # 接受这一已实测退化样本，避免把任意日志/启动文本中的 “log” 当成登录按钮。
    if re.search(r"\bkali\b", lowered) and re.search(r"\blog(?:!n|!)", lowered):
        greeter_signals.append("登录按钮（OCR 退化 Log!）")
    # 至少命中一个登录专属信号；“Kali”或“Kali Linux”可能来自 GRUB，不能单独作为证据。
    if base["classification"] == "unknown" and greeter_signals:
        base = {
            "classification": "login_ready",
            "confidence": "medium",
            "matched_signals": greeter_signals,
            "all_signals": base.get("all_signals", {}),
            "warnings": base.get("warnings", []),
        }
    return base


def sha256(path: pathlib.Path) -> str:
    return ctflab.sha256_file(path)


def file_mode(path: pathlib.Path) -> str:
    return oct(path.stat().st_mode & 0o777)


def wait_for_screen(qmp_path: pathlib.Path, workdir: pathlib.Path, kind: str,
                    timeout: int, *, label: str) -> dict:
    """轮询 QMP screendump + OCR，直到分类命中目标；返回最后一次分类。"""
    sips = "/usr/bin/sips"
    tesseract = "/opt/homebrew/bin/tesseract"
    deadline = time.time() + timeout
    history: list[dict] = []
    last: dict = {"classification": "unknown"}
    while time.time() < deadline:
        ppm = workdir / "screen.ppm"
        png = workdir / "screen.png"
        try:
            ctflab.qmp_execute(qmp_path, "screendump", {"filename": str(ppm)})
        except Exception as exc:  # noqa: BLE001  截图失败时继续重试
            last = {"classification": "unknown", "error": str(exc)}
            time.sleep(3)
            continue
        subprocess.run([sips, "-s", "format", "png", str(ppm), "--out", str(png)],
                       capture_output=True)
        text = ocr_screen_text(png, workdir)
        last = classify_kali_screen(text)
        last["ocr_chars"] = len(text)
        last["ocr_text"] = text[-400:]
        history.append({"at": round(time.time() - (deadline - timeout), 1),
                        "classification": last.get("classification"),
                        "confidence": last.get("confidence"),
                        "signals": last.get("matched_signals")})
        if last.get("classification") == kind:
            final_screen = workdir / f"final-screen-{label}.png"
            shutil.copy2(png, final_screen)
            last["screenshot"] = str(final_screen)
            return {"classification": last, "history": history}
        (workdir / "last-screen.png").unlink(missing_ok=True)
        if png.is_file():
            shutil.copy2(png, workdir / "last-screen.png")
        time.sleep(5)
    return {"classification": last, "history": history, "timeout": True}


class GuestSSH:
    """通过系统 ssh + SSH_ASKPASS 在来宾内执行命令（口令不进命令行与证据）。"""

    def __init__(self, workdir: pathlib.Path, password: str, port: int = KALI_SSH_PORT,
                 user: str = "kali") -> None:
        self.port = port
        self.user = user
        self.password = password
        self.askpass = workdir / "askpass.sh"
        self.askpass.write_text('#!/bin/sh\nprintf "%s\\n" "$CTFLAB_ASKPASS_SECRET"\n', encoding="utf-8")
        self.askpass.chmod(0o700)

    def env(self) -> dict[str, str]:
        return {
            "PATH": MINIMAL_PATH,
            "HOME": os.environ.get("HOME", "/tmp"),
            "SSH_ASKPASS": str(self.askpass),
            "SSH_ASKPASS_REQUIRE": "force",
            "DISPLAY": ":0",
            "CTFLAB_ASKPASS_SECRET": self.password,
        }

    def command(self, remote: str, timeout: int = 60, input_text: str | None = None) -> dict:
        cmd = [
            "/usr/bin/ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "PreferredAuthentications=password",
            "-o", "PubkeyAuthentication=no",
            "-o", "ConnectTimeout=10",
            "-o", "LogLevel=ERROR",
            "-p", str(self.port),
            f"{self.user}@127.0.0.1",
            remote,
        ]
        return run(cmd, env=self.env(), timeout=timeout, redact=[self.password], input_text=input_text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CTFLab Task 6.3A：.app 的 Kali ARM64+UEFI 验收")
    parser.add_argument("--app", type=pathlib.Path, required=True, help="CTFLab.app 路径")
    parser.add_argument("--workdir", type=pathlib.Path, help="工作目录（默认临时目录，保留证据）")
    parser.add_argument("--password", help="kali 来宾 SSH 口令（默认从环境变量 CTFLAB_KALI_PASSWORD 读取）")
    parser.add_argument("--boot-timeout", type=int, default=420, help="等待 Kali 登录界面的秒数")
    parser.add_argument("--timeout", type=int, default=900, help="单步超时秒数")
    args = parser.parse_args(argv)

    recorder = Recorder()
    workdir = pathlib.Path(args.workdir or tempfile.mkdtemp(prefix="ctflab-kali-e2e-")).expanduser()
    workdir.mkdir(parents=True, exist_ok=True)
    home = workdir / "home"
    home.mkdir(exist_ok=True)
    state_dir = workdir / "state"
    app = pathlib.Path(args.app).expanduser().resolve()
    launcher = app / ctflab_app.LAUNCHER_REL
    evidence_path = workdir / "kali-e2e-evidence.json"
    password = args.password or os.environ.get("CTFLAB_KALI_PASSWORD", "")
    env = base_env(home)

    def ctflab_cmd(*extra: str) -> list[str]:
        return [str(launcher), "--state-dir", str(state_dir), *extra]

    def cleanup() -> None:
        """失败路径也必须收尾：停止本 state-dir 的实例并清理遗留的交换机进程。"""
        try:
            run(ctflab_cmd("stop", "--all"), env=env, timeout=180)
        except Exception:  # noqa: BLE001
            pass
        try:
            listing = subprocess.run(["pgrep", "-f", "ctflab_network.py"],
                                     capture_output=True, text=True).stdout.split()
            for raw_pid in listing:
                command = subprocess.run(["ps", "-o", "command=", "-p", raw_pid],
                                         capture_output=True, text=True).stdout
                if str(workdir) in command:
                    os.kill(int(raw_pid), 15)
        except Exception:  # noqa: BLE001
            pass

    def finish() -> int:
        cleanup()
        payload = {
            "schema": 1,
            "format": "ctflab-app-kali-e2e",
            "generated_at": ctflab_app.now_iso(),
            "app": str(app),
            "workdir": str(workdir),
            "minimal_path": MINIMAL_PATH,
            "steps": recorder.steps,
            "result": "失败" if recorder.failed else "通过",
            "scope_note": (
                "范围＝Kali ARM64 + UEFI 的 import/run/health/reboot/stop/reset 与运行时来源证明；"
                "不含签名/公证、动态分辨率、UTM 与用户既有虚拟机操作。"
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

    if not password:
        recorder.record("guest-password", "失败",
                        "Task 6.3A 必须提供 --password 或 CTFLAB_KALI_PASSWORD，"
                        "否则无法完成来宾连通性与正常关机验收")
        return finish()

    # --- 1. 复核 App / 旁车 / 运行时引用 ---
    try:
        report = ctflab_app.verify_app(app)
    except ctflab_app.AppBuildError as exc:
        recorder.record("verify-app", "失败", str(exc))
        return finish()
    tree_before = ctflab_app.app_tree_hash(app)
    pycache_before = {path.relative_to(app).as_posix() for path in app.rglob("__pycache__")}
    sidecar = app.parent / "CTFLab.app.sha256"
    sidecar_ok = False
    if sidecar.is_file():
        lines = [line.split() for line in sidecar.read_text(encoding="utf-8").splitlines() if line.strip()]
        sidecar_ok = (len(lines) >= 2 and len(lines[0]) >= 1 and len(lines[1]) >= 1
                      and lines[0][0] == tree_before
                      and lines[1][0] == sha256(app / ctflab_app.MANIFEST_REL))
    recorder.record("verify-app", "通过" if sidecar_ok else "失败",
                    f"版本 {report['version']}，{report['file_count']} 文件，树哈希 {tree_before[:12]}…；"
                    f"签名 {report['signature']['level']}；旁车{'一致' if sidecar_ok else '不一致'}",
                    evidence=report, tree_sha256=tree_before)
    if not sidecar_ok:
        return finish()

    runtime = app / ctflab_app.RUNTIME_REL
    asset_hashes = {
        "qemu-system-aarch64": sha256(runtime / "bin" / "qemu-system-aarch64"),
        "qemu-img": sha256(runtime / "bin" / "qemu-img"),
        "edk2-aarch64-code.fd": sha256(runtime / "share" / "qemu" / "edk2-aarch64-code.fd"),
        "edk2-arm-vars.fd": sha256(runtime / "share" / "qemu" / "edk2-arm-vars.fd"),
    }
    recorder.record("app-runtime-assets", "通过",
                    "；".join(f"{k}={v[:12]}…" for k, v in asset_hashes.items()), hashes=asset_hashes)

    # --- 2. 独立 HOME + 最小 PATH：零手工依赖（无 venv/pip） ---
    python_bin = app / ctflab_app.PYTHON_RUNTIME_REL / "bin" / "python3"
    first = run(ctflab_cmd("doctor"), env=env, timeout=args.timeout)
    first_out = first["stdout"] + first["stderr"]
    zero_setup = (first["returncode"] == 0
                  and f"运行时：bundled（{runtime}）" in first_out
                  and str(python_bin) in first_out
                  and "OK   PyYAML: available" in first_out
                  and "edk2-aarch64-code.fd" in first_out
                  and "/opt/homebrew" not in first_out)
    recorder.record("doctor-zero-setup", "通过" if zero_setup else "失败",
                    "最小 PATH 下 doctor 直接通过：内置解释器 + PyYAML + App 内固件"
                    if zero_setup else "doctor 未证明零手工依赖与 App 内运行时/固件",
                    evidence={"returncode": first["returncode"], "stdout": first["stdout"]})
    if not zero_setup:
        return finish()

    # --- 2.5 沙箱拒绝宿主 Python/开发路径后 doctor 仍通过（非空证明） ---
    sandbox_doctor = run(["/usr/bin/sandbox-exec", "-p", SANDBOX_PROFILE, *ctflab_cmd("doctor")],
                         env=env, timeout=args.timeout)
    sandbox_doctor_out = sandbox_doctor["stdout"] + sandbox_doctor["stderr"]
    denied_ok = (sandbox_doctor["returncode"] == 0
                 and str(python_bin) in sandbox_doctor_out
                 and f"运行时：bundled（{runtime}）" in sandbox_doctor_out)
    recorder.record("host-python-denied", "通过" if denied_ok else "失败",
                    "拒绝 /usr/bin/python3、/opt/homebrew 等宿主路径后 doctor 仍通过" if denied_ok
                    else f"沙盒内 doctor 异常：{sandbox_doctor_out.strip()[-200:]}",
                    evidence=sandbox_doctor)
    if not denied_ok:
        return finish()

    # --- 3. 沙箱固件来源证明（aarch64 + App 内固件） ---
    sandbox_vars = workdir / "sandbox-vars.fd"
    shutil.copy2(runtime / "share" / "qemu" / "edk2-arm-vars.fd", sandbox_vars)
    # sandbox-exec 内无法创建 HVF（VGIC/platform 设备被沙盒限制），这里用 TCG 只验证
    # 「固件来自 App」；真实运行仍按 profile 使用 HVF（见 run 步骤的进程证据）。
    sandbox_cmd = [
        "/usr/bin/sandbox-exec", "-p", SANDBOX_PROFILE,
        str(runtime / "bin" / "qemu-system-aarch64"),
        "-machine", "virt", "-accel", "tcg", "-m", "1024", "-display", "none",
        "-serial", "none", "-monitor", "none", "-nodefaults", "-S",
        "-drive", f"if=pflash,format=raw,unit=0,file={runtime}/share/qemu/edk2-aarch64-code.fd,readonly=on",
        "-drive", f"if=pflash,format=raw,unit=1,file={sandbox_vars}",
    ]
    sandbox_result = run(sandbox_cmd, env={"HOME": str(home), "PATH": MINIMAL_PATH}, timeout=12)
    stderr = sandbox_result["stderr"]
    firmware_error = any(token in stderr for token in ("could not load", "failed to find",
                                                       "could not open", "No such file"))
    sandbox_ok = sandbox_result.get("timeout") is True and not firmware_error
    recorder.record("firmware-provenance", "通过" if sandbox_ok else "失败",
                    "拒绝 /opt/homebrew 后 App 内 qemu-system-aarch64 + 固件仍可启动" if sandbox_ok
                    else f"沙盒启动异常：{stderr.strip()[:200]}", evidence=sandbox_result)
    if not sandbox_ok:
        return finish()

    # --- 4. 复用经哈希验证的 kali 基盘与原始 RAW NVRAM（副本） ---
    host_image_state = HOST_STATE_DIR / "images" / "kali-arm64" / "image.json"
    if not host_image_state.is_file():
        recorder.record("asset-source", "失败", f"未找到真实 kali 导入记录：{host_image_state}")
        return finish()
    host_state = json.loads(host_image_state.read_text(encoding="utf-8"))
    host_base = pathlib.Path(str(host_state.get("base_path", "")))
    host_raw = pathlib.Path(str(host_state.get("uefi_vars_path", "")))
    host_base_sha = sha256(host_base)
    host_raw_sha = sha256(host_raw)
    recorded_base = str(host_state.get("base_sha256", ""))
    recorded_raw = str(host_state.get("uefi_vars_sha256", ""))
    assets_ok = (host_base_sha == recorded_base and host_raw_sha == recorded_raw)
    recorder.record("asset-baseline", "通过" if assets_ok else "失败",
                    f"基盘 {host_base.name} {host_base_sha[:12]}…；RAW NVRAM {host_raw.name} "
                    f"{host_raw_sha[:12]}…；与登记值{'一致' if assets_ok else '不一致'}",
                    base_path=str(host_base), base_sha256=host_base_sha,
                    raw_path=str(host_raw), raw_sha256=host_raw_sha)
    if not assets_ok:
        return finish()

    local_base = workdir / host_base.name
    local_raw = workdir / host_raw.name
    if not local_base.exists():
        shutil.copy2(host_base, local_base)
    if not local_raw.exists():
        shutil.copy2(host_raw, local_raw)
    copies_ok = sha256(local_base) == host_base_sha and sha256(local_raw) == host_raw_sha
    recorder.record("asset-copies", "通过" if copies_ok else "失败",
                    "基盘与 RAW NVRAM 副本哈希与原始一致")
    if not copies_ok:
        return finish()

    import_result = run(ctflab_cmd("import", "kali-arm64", str(local_base)), env=env, timeout=args.timeout)
    if import_result["returncode"] != 0:
        recorder.record("import", "失败", "导入失败", evidence=import_result)
        return finish()
    # 按 install/finalize-install 的登记形状补上 NVRAM 来源（指向 RAW 副本），
    # 使 ensure_uefi_vars 以原始 RAW 为模板派生实例 NVRAM。
    image_json = state_dir / "images" / "kali-arm64" / "image.json"
    image_state = json.loads(image_json.read_text(encoding="utf-8"))
    image_state["uefi_vars_path"] = str(local_raw)
    image_state["uefi_vars_sha256"] = host_raw_sha
    image_json.write_text(json.dumps(image_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    recorder.record("import", "通过",
                    f"已导入 {local_base.name}（base_sha256 {sha256(local_base)[:12]}…）；"
                    "NVRAM 模板指向原始 RAW 副本", evidence=import_result)

    # 靶机同样从宿主经哈希验证的基盘副本导入（隔离网连通性验证需要它们运行）
    for target_id in ("smoke", "basic-pentesting-2"):
        target_state_path = HOST_STATE_DIR / "images" / target_id / "image.json"
        if not target_state_path.is_file():
            recorder.record(f"import-{target_id}", "失败", f"未找到真实导入记录：{target_state_path}")
            return finish()
        target_state = json.loads(target_state_path.read_text(encoding="utf-8"))
        target_base = pathlib.Path(str(target_state.get("base_path", "")))
        target_sha = sha256(target_base)
        if target_sha != str(target_state.get("base_sha256", "")):
            recorder.record(f"import-{target_id}", "失败", "宿主基盘哈希与登记值不一致")
            return finish()
        local_target = workdir / target_base.name
        if not local_target.exists():
            shutil.copy2(target_base, local_target)
        result = run(ctflab_cmd("import", target_id, str(local_target)), env=env, timeout=args.timeout)
        recorder.record(f"import-{target_id}", "通过" if result["returncode"] == 0 else "失败",
                        f"{target_base.name} {target_sha[:12]}…", evidence=result)
        if result["returncode"] != 0:
            return finish()

    # --- 5. 启动三节点并判定 UEFI 引导 ---
    run_result = run(ctflab_cmd("run", "kali-arm64", "smoke", "basic-pentesting-2", "--headless"),
                     env=env, timeout=args.timeout)
    if run_result["returncode"] != 0:
        recorder.record("run", "失败", "启动失败", evidence=run_result)
        return finish()

    kali_state = json.loads((state_dir / "runtime" / "kali-arm64" / "run.json").read_text(encoding="utf-8"))
    process_ok = (f"{app}/Contents/Resources/runtime/bin/qemu-system-aarch64" in " ".join(
        str(item) for item in kali_state.get("command", [])) and "/opt/homebrew" not in " ".join(
        str(item) for item in kali_state.get("command", [])))
    recorder.record("run", "通过" if process_ok else "失败",
                    f"QEMU 命令来自 App 内运行时；PID {kali_state.get('pid')}", evidence=run_result)
    if not process_ok:
        return finish()

    derived_vars = state_dir / "runtime" / "kali-arm64" / "uefi-vars.fd"
    derived_sha_before = sha256(derived_vars) if derived_vars.is_file() else None
    screen = wait_for_screen(pathlib.Path(kali_state["qmp_path"]), workdir, "login_ready",
                             args.boot_timeout, label="initial")
    classification = screen["classification"]
    boot_ok = classification.get("classification") == "login_ready"
    recorder.record("uefi-boot", "通过" if boot_ok else "失败",
                    f"截屏分类={classification.get('classification')}"
                    f"（置信度 {classification.get('confidence')}）；未进入 UEFI Shell",
                    evidence={"final": classification, "history": screen["history"][-6:]})
    if not boot_ok:
        return finish()

    derived_sha_after = sha256(derived_vars) if derived_vars.is_file() else None
    derived_ok = (derived_sha_before is not None and derived_sha_after is not None
                  and os.access(derived_vars, os.W_OK) and file_mode(derived_vars)[-1] in "6420")
    nvram_ok = (derived_ok
                and sha256(runtime / "share" / "qemu" / "edk2-arm-vars.fd") == asset_hashes["edk2-arm-vars.fd"]
                and sha256(host_raw) == host_raw_sha)
    recorder.record("nvram-derivation", "通过" if nvram_ok else "失败",
                    f"派生 NVRAM {derived_vars.name} 可写（模式 {file_mode(derived_vars) if derived_vars.exists() else '—'}，"
                    f"哈希 {str(derived_sha_after)[:12]}…）；App 模板与原始 RAW 未变",
                    derived_sha_before=derived_sha_before, derived_sha_after=derived_sha_after)
    if not nvram_ok:
        return finish()

    # --- 6. 健康检查 ---
    health = {}
    for profile_id in ("kali-arm64", "smoke", "basic-pentesting-2"):
        result = run(ctflab_cmd("health", profile_id), env=env, timeout=args.timeout)
        health[profile_id] = result
        recorder.record(f"health-{profile_id}", "通过" if result["returncode"] == 0 else "失败",
                        "健康检查通过" if result["returncode"] == 0 else "健康检查失败",
                        evidence=result)
    if any(item["returncode"] != 0 for item in health.values()):
        return finish()

    # --- 7. 来宾内连通性（隔离实验网可达、公网不可达） ---
    ssh = GuestSSH(workdir, password)
    # 靶机走 TCG，比 Kali（HVF）慢得多：先轮询等待隔离网可达，再做完整断言。
    ready = False
    wait_history: list[dict] = []
    for attempt in range(30):
        warmup = ssh.command(
            f"ping -c 1 -W 2 {SMOKE_IP} >/dev/null 2>&1 && echo SMOKE_OK || echo SMOKE_FAIL; "
            f"ping -c 1 -W 2 {BASIC_IP} >/dev/null 2>&1 && echo BASIC_OK || echo BASIC_FAIL; "
            "curl -s -o /dev/null -w 'WARMUP_HTTP=%{http_code}\n' --max-time 5 "
            f"http://{BASIC_IP}/",
            timeout=60)
        reached = ("SMOKE_OK" in warmup["stdout"] and "BASIC_OK" in warmup["stdout"]
                   and "WARMUP_HTTP=200" in warmup["stdout"])
        wait_history.append({"attempt": attempt, "output": warmup["stdout"].strip()})
        if reached:
            ready = True
            break
        time.sleep(10)
    recorder.record("guest-lab-warmup", "通过" if ready else "失败",
                    f"第 {len(wait_history)} 次探测时隔离网可达" if ready
                    else f"等待 300 秒后靶机服务仍不可达：{wait_history[-1]['output'][:120]}",
                    evidence={"history": wait_history[-6:]})
    if not ready:
        return finish()
    probe = ssh.command(
        f"ping -c 3 -W 3 {SMOKE_IP}; echo SMOKE_RC=$?; "
        f"ping -c 3 -W 3 {BASIC_IP}; echo BASIC_RC=$?; "
        "curl -s -o /dev/null -w 'HTTP=%{http_code}\\n' --max-time 10 "
        f"http://{BASIC_IP}/ ; "
        f"ping -c 2 -W 3 1.1.1.1 >/dev/null 2>&1 && echo WAN_OK || echo WAN_BLOCKED; "
        "ip route",
        timeout=180)
    out = probe["stdout"]
    connectivity_ok = ("SMOKE_RC=0" in out and "BASIC_RC=0" in out
                       and "HTTP=200" in out and "WAN_BLOCKED" in out
                       and "default via" not in out)
    recorder.record("guest-connectivity", "通过" if connectivity_ok else "失败",
                    "Kali 可达 smoke/basic（HTTP 200）且无默认路由、公网不可达"
                    if connectivity_ok else f"来宾内连通性不符合预期：{out.strip()[:200]}",
                    evidence=probe)
    if not connectivity_ok:
        return finish()

    # --- 8. 正常停止 → 重启 → 健康 → 停止 → reset ---
    ssh = GuestSSH(workdir, password)
    shutdown = ssh.command("sudo -S poweroff", timeout=60, input_text=password + "\n")
    for _ in range(30):
        if not ctflab.bool_pid_alive(int(kali_state["pid"])):
            break
        time.sleep(5)
    powered_off = not ctflab.bool_pid_alive(int(kali_state["pid"]))
    recorder.record("guest-poweroff", "通过" if powered_off else "失败",
                    "来宾内 sudo poweroff 后 QEMU 已退出（正常关机）" if powered_off
                    else "来宾内 sudo poweroff 后 150 秒内 QEMU 仍未退出",
                    evidence={"returncode": shutdown["returncode"],
                              "stdout": shutdown["stdout"][-200:]})
    if not powered_off:
        return finish()
    stop_result = run(ctflab_cmd("stop", "kali-arm64"), env=env, timeout=args.timeout)
    recorder.record("stop-1", "通过" if stop_result["returncode"] == 0 else "失败",
                    "停止完成" if stop_result["returncode"] == 0 else "停止失败", evidence=stop_result)
    if stop_result["returncode"] != 0:
        return finish()

    rerun = run(ctflab_cmd("run", "kali-arm64", "--headless"), env=env, timeout=args.timeout)
    recorder.record("reboot", "通过" if rerun["returncode"] == 0 else "失败",
                    "再次启动完成（重启）" if rerun["returncode"] == 0 else "重启失败", evidence=rerun)
    if rerun["returncode"] != 0:
        return finish()
    kali_state2 = json.loads((state_dir / "runtime" / "kali-arm64" / "run.json").read_text(encoding="utf-8"))
    screen2 = wait_for_screen(pathlib.Path(kali_state2["qmp_path"]), workdir, "login_ready",
                              args.boot_timeout, label="reboot")
    recorder.record("reboot-boot", "通过" if screen2["classification"].get("classification") == "login_ready" else "失败",
                    f"重启后截屏分类={screen2['classification'].get('classification')}",
                    evidence={"final": screen2["classification"]})
    health2 = run(ctflab_cmd("health", "kali-arm64"), env=env, timeout=args.timeout)
    recorder.record("health-after-reboot", "通过" if health2["returncode"] == 0 else "失败",
                    "重启后健康检查通过" if health2["returncode"] == 0 else "重启后健康检查失败",
                    evidence=health2)

    ssh = GuestSSH(workdir, password)
    ssh.command("sudo -S poweroff", timeout=60, input_text=password + "\n")
    for _ in range(30):
        if not ctflab.bool_pid_alive(int(kali_state2["pid"])):
            break
        time.sleep(5)
    stop2 = run(ctflab_cmd("stop", "kali-arm64"), env=env, timeout=args.timeout)
    recorder.record("stop-2", "通过" if stop2["returncode"] == 0 else "失败",
                    "第二次停止完成" if stop2["returncode"] == 0 else "第二次停止失败", evidence=stop2)

    for profile_id in ("smoke", "basic-pentesting-2"):
        run(ctflab_cmd("stop", profile_id), env=env, timeout=args.timeout)

    reset = run(ctflab_cmd("reset", "kali-arm64"), env=env, timeout=args.timeout)
    recorder.record("reset", "通过" if reset["returncode"] == 0 else "失败",
                    "重置完成" if reset["returncode"] == 0 else "重置失败", evidence=reset)
    for profile_id in ("smoke", "basic-pentesting-2"):
        run(ctflab_cmd("reset", profile_id), env=env, timeout=args.timeout)

    # --- 9. 复核 ---
    residue: list[str] = []
    runtime_dir = state_dir / "runtime"
    if runtime_dir.is_dir():
        residue += [str(path) for path in runtime_dir.rglob("run.json")]
        residue += [str(path) for path in runtime_dir.glob("network-*.json")]
        residue += [str(path) for path in runtime_dir.rglob("qmp.sock")]
    for profile_id in ("kali-arm64", "smoke", "basic-pentesting-2"):
        images_dir = state_dir / "images" / profile_id
        if images_dir.is_dir():
            residue += [str(path) for path in images_dir.glob("overlay*")]
    leftover_qemu = subprocess.run(["pgrep", "-fl", f"qemu-system.*{state_dir}"],
                                   capture_output=True, text=True).stdout.strip()
    residue_ok = not residue and not leftover_qemu
    recorder.record("residue-check", "通过" if residue_ok else "失败",
                    "无 QEMU/QMP/网络/overlay/运行状态残留" if residue_ok
                    else f"残留：{residue[:3]} {leftover_qemu[:120]}")

    invariants = {
        "app_tree": (ctflab_app.app_tree_hash(app), tree_before),
        "app_template": (sha256(runtime / "share" / "qemu" / "edk2-arm-vars.fd"), asset_hashes["edk2-arm-vars.fd"]),
        "host_base": (sha256(host_base), host_base_sha),
        "host_raw_nvram": (sha256(host_raw), host_raw_sha),
    }
    changed = {name: pair for name, pair in invariants.items() if pair[0] != pair[1]}
    recorder.record("hash-invariants", "通过" if not changed else "失败",
                    "App 树、App 固件模板、原始基盘与原始 RAW NVRAM 哈希均未变化" if not changed
                    else f"以下对象发生变化：{list(changed)}",
                    invariants={name: pair[0] for name, pair in invariants.items()})

    pycache_after = {path.relative_to(app).as_posix() for path in app.rglob("__pycache__")}
    new_pycache = sorted(pycache_after - pycache_before)
    recorder.record("no-bytecode-writes", "通过" if not new_pycache else "失败",
                    f"运行后无新增字节码缓存（-B 生效；随包预编译缓存 {len(pycache_before)} 处保持原样）"
                    if not new_pycache else f"运行写入新的字节码缓存：{new_pycache[:3]}")

    check_result = run([str(runtime / "bin" / "qemu-img"), "check", str(local_base)],
                       env=env, timeout=args.timeout)
    recorder.record("qemu-img-check", "通过" if check_result["returncode"] == 0 else "失败",
                    "qemu-img check 通过" if check_result["returncode"] == 0 else "check 失败",
                    evidence={"command": check_result["command"],
                              "returncode": check_result["returncode"],
                              "stdout": check_result["stdout"][-200:]})
    return finish()


if __name__ == "__main__":
    raise SystemExit(main())
