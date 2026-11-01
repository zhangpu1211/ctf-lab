#!/usr/bin/env python3
"""独立 Kali 资源档位启动基准；不测桌面输入，不读取认证口令。"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import statistics
import sys
import tempfile
import time


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def ready(checks):
    """必须得到来宾协议响应；仅宿主监听或进程存活不算启动就绪。"""
    values = {item["name"]: item.get("ok") for item in checks}
    return all(values.get(name) is True for name in ("process", "dhcp", "ssh:22"))


def summary(rows):
    result = {}
    for name in ("light", "balanced", "performance"):
        samples = [row["network_ready_seconds"] for row in rows
                   if row["preset"] == name and row.get("network_ready_seconds") is not None]
        result[name] = {"completed_samples": len(samples),
                        "median_network_ready_seconds": round(statistics.median(samples), 3) if samples else None}
    return result


def free_port():
    with socket.socket() as endpoint:
        endpoint.bind(("127.0.0.1", 0))
        return endpoint.getsockname()[1]


def run_round(ctflab, record, preset, timeout):
    state = Path(tempfile.mkdtemp(prefix="ctflab-benchmark-", dir="/private/tmp"))
    manager = ctflab.LabManager(state)
    ctflab.write_json(manager.image_state_path("kali-arm64"), copy.deepcopy(record))
    profile = ctflab.resource_preset_overrides(["kali-arm64"], preset)["kali-arm64"]
    for forward in profile.get("network", {}).get("host_forwards", []):
        forward["host_port"] = free_port()
    manager.allocate_lab_port = free_port
    row = {"preset": preset, "state": str(state), "network_ready_seconds": None,
           "memory_mb": profile["guest"]["memory_mb"], "cpus": profile["guest"]["cpus"],
           "shutdown_scope": "runner-stop-not-guest-poweroff", "headless": True}
    try:
        started = time.monotonic()
        run = manager.run(["kali-arm64"], headless=True, allow_internet=False,
                          clipboard=False, file_transfer=False,
                          profile_overrides={"kali-arm64": profile})[0]
        row["qemu_pid"] = run["pid"]
        while time.monotonic() - started < timeout:
            checks = manager.health("kali-arm64")
            if ready(checks):
                row["network_ready_seconds"] = round(time.monotonic() - started, 3)
                row["health"] = checks
                row["host_process_usage"] = ctflab.sample_process_usage([run["pid"]]).get(run["pid"])
                row["qmp_status"] = ctflab.qmp_execute(Path(run["qmp_path"]), "query-status")
                break
            if not ctflab.bool_pid_alive(run["pid"]):
                raise ValueError("测试 QEMU 提前退出")
            time.sleep(1)
        if row["network_ready_seconds"] is None:
            row["health"] = manager.health("kali-arm64")
            row["error"] = "readiness-timeout"
    except (ValueError, OSError, ctflab.CTFLabError) as error:
        row["error"] = str(error)
    finally:
        try:
            manager.stop(["kali-arm64"])
        except (ValueError, OSError, ctflab.CTFLabError) as error:
            row["cleanup_error"] = str(error)
        row["no_running_instances_after_stop"] = not manager.running_states()
    return row


def main(argv=None):
    if not sys.dont_write_bytecode:
        raise SystemExit("必须使用 python3 -B，禁止修改候选 App 字节码缓存")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rounds", type=int, choices=range(1, 6), default=2)
    parser.add_argument("--timeout", type=int, choices=range(30, 601), default=180)
    args = parser.parse_args(argv)
    root = args.app.resolve()
    os.environ["CTFLAB_RUNTIME_ROOT"] = str(root / "Contents/Resources/runtime")
    os.environ.pop("CTFLAB_SPICE_CLIENT", None)
    sys.path.insert(0, str(root / "Contents/Resources/ctflab/tools"))
    import ctflab
    from ctflab_app import verify_app, app_tree_hash
    verify_app(root)
    record = ctflab.read_json(Path.home() / "Library/Application Support/CTFLab/images/kali-arm64/image.json")
    if not record:
        raise ValueError("需要已有可信 Kali 基盘登记")
    expected = {record[key]: record[key.replace("_path", "_sha256")]
                for key in ("base_path", "uefi_vars_path")}
    if not all(digest(path) == value for path, value in expected.items()):
        raise ValueError("源资产哈希与登记不一致，拒绝启动")
    app_hash = app_tree_hash(root)
    args.out.mkdir(parents=True, exist_ok=True)
    # 排他证据创建；测试实例、磁盘和日志均不写入仓库。
    with (args.out / "startup-benchmark.json").open("x", encoding="utf-8") as evidence:
        rows = []
        for cycle in range(args.rounds):
            for preset in ctflab.RESOURCE_PRESETS:
                row = run_round(ctflab, record, preset, args.timeout)
                row["round"] = cycle + 1
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                if row.get("error") or row.get("cleanup_error") or not row["no_running_instances_after_stop"]:
                    break
            if rows[-1].get("error") or rows[-1].get("cleanup_error") or not rows[-1]["no_running_instances_after_stop"]:
                break
        report = {"scope": "headless-boot-dhcp-ssh-not-desktop-performance",
                  "rows": rows, "summary": summary(rows),
                  "assets_unchanged": all(digest(path) == value for path, value in expected.items()),
                  "app_unchanged": app_tree_hash(root) == app_hash,
                  "limitations": ["不包含图形登录、滚动、拖拽、解锁或 CPU 工作负载",
                                  "不是 UTM/VirtualBox 性能对比；宿主进程 CPU/RSS 不等同来宾压力",
                                  "保留派生证据，不改用户实例，不自动调整默认档位"]}
        json.dump(report, evidence, ensure_ascii=False, indent=2)
        evidence.flush()
    if len(rows) != args.rounds * len(ctflab.RESOURCE_PRESETS) or any(row.get("error") or row.get("cleanup_error") or not row["no_running_instances_after_stop"] for row in rows) or not report["assets_unchanged"] or not report["app_unchanged"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
