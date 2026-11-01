"""本地受控更新槽位：验证副本、原子切换指针、保留前版；不改用户镜像。"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

from ctflab_app import AppBuildError, app_tree_hash, verify_app


class UpdateError(ValueError):
    pass


def _root(root):
    root = Path(root).expanduser().absolute()
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise UpdateError("更新目录不允许符号链接")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise UpdateError("更新目录必须属于当前用户且权限为 0700")
    return root


@contextmanager
def _lock(root):
    descriptor = os.open(root / "update.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise UpdateError("另一项更新正在进行") from error
        yield
    finally:
        os.close(descriptor)


def _read(root):
    path = root / "selection.json"
    if path.is_symlink():
        raise UpdateError("更新指针不允许符号链接")
    if not path.exists():
        return {"schema": 1, "active": None, "previous": None, "slots": {}}
    value = json.loads(path.read_text())
    if value.get("schema") != 1 or not isinstance(value.get("slots"), dict):
        raise UpdateError("更新登记结构无效")
    return value


def _write(root, value):
    descriptor, temporary = tempfile.mkstemp(prefix=".selection-", dir=root)
    try:
        with os.fdopen(descriptor, "w") as target:
            json.dump(value, target, ensure_ascii=False, indent=2)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, root / "selection.json")
    finally:
        Path(temporary).unlink(missing_ok=True)


def _verify(app, expected, allow_local):
    if not re.fullmatch(r"[0-9a-f]{64}", expected or ""):
        raise UpdateError("需要可信来源提供的完整 App 树 SHA-256")
    if app_tree_hash(app) != expected:
        raise UpdateError("App 树哈希不匹配")
    report = verify_app(app)
    signature = report.get("signature", {})
    if signature.get("verify_returncode") != 0:
        raise UpdateError("App 签名校验失败")
    if not allow_local and (signature.get("level") != "developer-id" or not signature.get("notarized")):
        raise UpdateError("正式更新要求 Developer ID 与公证；本地候选需明确 --allow-local-candidate")
    return report


def _app(root, identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{32}", identifier):
        raise UpdateError("非法更新槽位")
    app = root / identifier / "CTFLab.app"
    if app.parent.is_symlink() or app.is_symlink():
        raise UpdateError("更新槽位不允许符号链接")
    return app


def stage(root, source, expected, allow_local=False):
    root, source = _root(root), Path(source).expanduser().absolute()
    if source.name != "CTFLab.app" or root == source or root in source.parents or source in root.parents:
        raise UpdateError("来源须为独立 CTFLab.app，不得与更新目录嵌套")
    with _lock(root):
        _verify(source, expected, allow_local)
        selected = _read(root)
        identifier = uuid.uuid4().hex
        slot = root / identifier
        slot.mkdir(mode=0o700)
        try:
            target = slot / "CTFLab.app"
            # 不执行安装脚本、不解压不可信归档、不覆盖旧版本。
            shutil.copytree(source, target, symlinks=True)
            shutil.copy2(source.with_suffix(".app.sha256"), target.with_suffix(".app.sha256"))
            report = _verify(target, expected, allow_local)
            selected["slots"][identifier] = {"sha256": expected, "version": report["version"],
                                               "allow_local_candidate": bool(allow_local)}
            _write(root, selected)
        except Exception:
            shutil.rmtree(slot)
            raise
        return {"slot": identifier, "app": str(target), "version": report["version"], "activated": False}


def select(root, identifier=None, rollback=False):
    root = _root(root)
    with _lock(root):
        value = _read(root)
        identifier = value.get("previous") if rollback else identifier
        app = _app(root, identifier)
        record = value["slots"].get(identifier)
        if not record:
            raise UpdateError("槽位未登记")
        _verify(app, record["sha256"], record.get("allow_local_candidate") is True)
        if identifier != value.get("active"):
            value["previous"], value["active"] = value.get("active"), identifier
            _write(root, value)
        return {"active": identifier, "app": str(app), "previous": value.get("previous"),
                "scope": "next-launch-only-no-running-app-or-image-mutation"}


def status(root):
    root = _root(root)
    with _lock(root):
        value = _read(root)
        return {**value, "root": str(root), "active_app": str(_app(root, value["active"])) if value.get("active") else None}


def launch(root, state_dir):
    """显式打开已选版本；再次校验，不替换系统安装或停止现有节点。"""
    root = _root(root)
    with _lock(root):
        value = _read(root)
        app = _app(root, value.get("active"))
        record = value["slots"].get(value.get("active"))
        if not record:
            raise UpdateError("尚未选择更新槽位")
        _verify(app, record["sha256"], record.get("allow_local_candidate") is True)
        subprocess.run(["/usr/bin/open", "-n", "--env", f"CTFLAB_GUI_STATE_DIR={Path(state_dir).absolute()}", str(app)], check=True)
        return {"app": str(app), "launch_requested": True, "gui_ready_verified": False}
