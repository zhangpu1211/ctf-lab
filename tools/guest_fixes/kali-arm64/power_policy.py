#!/usr/bin/env python3
"""Kali ARM64 可撤销睡眠防护；只写自有 drop-in，不更改锁屏与电源按钮。"""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import tempfile


RELATIVE_PATH = Path("etc/systemd/sleep.conf.d/90-ctflab-no-sleep.conf")
POLICY = ("# CTFLab managed: remove only with power_policy.py restore --confirm\n"
          "# 仅阻止未验证的睡眠路径；不更改屏保、锁屏和正常关机。\n"
          "[Sleep]\nAllowSuspend=no\nAllowHibernation=no\n"
          "AllowHybridSleep=no\nAllowSuspendThenHibernate=no\n").encode("utf-8")
SLEEP_METHODS = ("CanSuspend", "CanHibernate", "CanHybridSleep", "CanSuspendThenHibernate")


def policy_path(root):
    """不跟随目标和父目录符号链接；root 参数仅供离线测试使用。"""
    root = Path(root).resolve(strict=True)
    current = root
    for part in RELATIVE_PATH.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("拒绝符号链接：" + str(current))
        if current.exists() and current != root / RELATIVE_PATH and not current.is_dir():
            raise ValueError("配置父路径不是目录：" + str(current))
    return root / RELATIVE_PATH


def installed_state(root=Path("/")):
    target = policy_path(root)
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return "not-installed"
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("配置目标不是普通文件")
        return "installed" if handle.read(len(POLICY) + 1) == POLICY else "conflict"


def apply_policy(root=Path("/")):
    target = policy_path(root)
    state = installed_state(root)
    if state == "conflict":
        raise ValueError("目标已有非本工具配置，拒绝覆盖，请人工复核。")
    if state == "installed":
        return {"changed": False, "policy": state}
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    policy_path(root)
    fd, name = tempfile.mkstemp(prefix=".ctflab-sleep-", dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(POLICY)
            handle.flush()
            os.fchmod(handle.fileno(), 0o644)
            os.fsync(handle.fileno())
        # 排他发布；并发出现的目标不能被 os.replace 静默覆盖。
        os.link(temporary, target, follow_symlinks=False)
    finally:
        temporary.unlink(missing_ok=True)
    return {"changed": True, "policy": installed_state(root)}


def restore_policy(root=Path("/")):
    state = installed_state(root)
    if state == "conflict":
        raise ValueError("本工具配置已被修改，拒绝删除，请人工复核。")
    if state == "not-installed":
        return {"changed": False, "policy": state}
    policy_path(root).unlink()
    # 不删除目录，不触碰其他 drop-in，不声称恢复后一定可睡眠。
    return {"changed": True, "policy": "not-installed"}


def sleep_capabilities():
    result = {}
    for method in SLEEP_METHODS:
        try:
            response = subprocess.run(
                ["busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1",
                 "org.freedesktop.login1.Manager", method],
                capture_output=True, text=True, timeout=5, check=False)
            match = re.fullmatch(r's "(yes|no|na|challenge)"\s*', response.stdout)
            result[method] = match.group(1) if response.returncode == 0 and match else "unknown"
        except (OSError, subprocess.TimeoutExpired):
            result[method] = "unknown"
    return result


def require_guest():
    if sys.platform != "linux" or platform.machine() not in ("aarch64", "arm64"):
        raise ValueError("只可在 Kali ARM64 来宾内执行，不可在 Mac 宿主执行。")


def require_systemd():
    result = subprocess.run(["systemctl", "--version"], capture_output=True,
                            text=True, timeout=5, check=False)
    match = re.match(r"systemd (\d+)\b", result.stdout)
    if result.returncode != 0 or not match or int(match.group(1)) < 240:
        raise ValueError("需要 systemd 240 或更新版本，未写入任何配置。")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "apply", "restore"))
    parser.add_argument("--confirm", action="store_true", help="明确允许更改来宾睡眠配置")
    args = parser.parse_args(argv)
    try:
        require_guest()
        if args.action != "status":
            if not args.confirm:
                parser.error("apply/restore 必须显式传入 --confirm")
            if os.geteuid() != 0:
                raise ValueError("请在来宾内使用 sudo；无需向 CTFLab 提供密码。")
            if args.action == "apply":
                require_systemd()
            result = (apply_policy if args.action == "apply" else restore_policy)()
        else:
            result = {"policy": installed_state()}
        result["sleep_capabilities"] = sleep_capabilities()
        result["sleep_block_verified"] = (result["policy"] == "installed" and
            all(value in ("no", "na") for value in result["sleep_capabilities"].values()))
        result["scope"] = "sleep-only; lock-screen-and-shutdown-unchanged"
        print(json.dumps(result, ensure_ascii=False))
        # 写入不等于生效；后置只读检查未证明阻止时明确返回非零并保留可撤销配置。
        return 2 if args.action == "apply" and not result["sleep_block_verified"] else 0
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print("错误：" + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
