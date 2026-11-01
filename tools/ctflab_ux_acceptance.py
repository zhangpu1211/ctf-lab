#!/usr/bin/env python3
"""独立桌面体验验收：只准备/记录/收尾派生实例，不合成输入、不读取口令。

需用 PYTHONDONTWRITEBYTECODE=1 和候选 App 的 Python -B 执行，避免启动阶段
在已签名 App 内改写标准库缓存。prepare 返回唯一状态目录，用 GUI_STATE_DIR 打开
候选 GUI；人工/CUA 完成桌面步骤后执行 finish。源基盘仅只读复用。
"""
import argparse
import copy
import hashlib
import json
import os
import math
import re
from pathlib import Path
import socket
import signal
import sys
import tempfile
import time


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for data in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(data)
    return value.hexdigest()


def clipboard_fixture(out):
    """生成公开可重复的大文本，不读取或修改宿主/来宾剪贴板。"""
    unit = "CTFLAB-LARGE-20261010 中文剪贴板校验\n第二行 English 0123456789\n第三行 end\n"
    count = math.ceil(1024 * 1024 / len(unit.encode("utf-8")))
    payload = (unit * count).encode("utf-8")
    target = out / "clipboard-large-utf8.txt"
    report = {"schema_version": 1, "file": target.name, "bytes": len(payload),
              "encoding": "UTF-8", "newline": "LF", "sha256": hashlib.sha256(payload).hexdigest(),
              "scope": "fixture-only-not-clipboard-e2e"}
    out.mkdir(parents=True, exist_ok=True)
    # 单一自描述结果由调用方打印；输入文件排他写入，不覆盖既有资料。
    with target.open("xb") as handle:
        handle.write(payload)
    print(json.dumps(report, ensure_ascii=False))
    return report


def guest_load_fixture(out):
    """只生成需用户在独立来宾内执行的定时负载，不在宿主自动执行。"""
    script = """python3 - <<'CTFLAB_LOAD'
import hashlib
import multiprocessing as mp
import os
import time

seconds = int(os.environ.get('CTFLAB_LOAD_SECONDS', '180'))
if not 1 <= seconds <= 300:
    raise SystemExit('负载时长必须为 1～300 秒')

def worker(deadline):
    data = b'CTFLAB-TEST-ONLY' * 4096
    while time.monotonic() < deadline:
        hashlib.sha256(data).digest()

if __name__ == '__main__':
    ctx = mp.get_context('fork')
    started = time.monotonic()
    deadline = started + seconds
    children = [ctx.Process(target=worker, args=(deadline,)) for _ in range(2)]
    print('CTFLAB-LOAD-START seconds=%d workers=2' % seconds, flush=True)
    try:
        for child in children:
            child.start()
        for child in children:
            child.join(max(0, deadline - time.monotonic()) + 3)
    finally:
        for child in children:
            if child.pid is not None:
                if child.is_alive():
                    child.terminate()
                child.join(3)
    print('CTFLAB-LOAD-END elapsed=%.3f' % (time.monotonic() - started), flush=True)
CTFLAB_LOAD
"""
    out.mkdir(parents=True, exist_ok=True)
    target = out / "guest-cpu-load.sh"
    with target.open("x", encoding="utf-8") as handle:
        handle.write(script)
    print(json.dumps({"scope": "guest-workload-fixture-not-executed",
                      "file": str(target), "seconds": 180, "workers": 2}, ensure_ascii=False))
    return target


def display_metrics(text):
    """只统计日志可证明的完成样本；输出不是桌面/认证验收结论。"""
    def stats(values):
        ordered = sorted(values)
        if not ordered:
            return {"count": 0, "median_ms": None, "p95_ms": None, "max_ms": None}
        return {"count": len(ordered),
                "median_ms": round((ordered[(len(ordered)-1)//2] + ordered[len(ordered)//2])/2, 3),
                "p95_ms": ordered[math.ceil(len(ordered)*.95)-1], "max_ms": ordered[-1]}
    resize = []
    input_draw = []
    pending = None
    buttons = {}
    superseded = 0
    failed_transition = 0
    malformed = 0
    reasons = {}
    for line in text.splitlines():
        cycle = re.search(r"recovery-cycle=(\d+) phase=input reason=([^ ]+)", line)
        if cycle:
            reasons[cycle[1]] = cycle[2]
            if cycle[2] == "button-press":
                buttons[cycle[1]] = None
        draw = re.search(r"recovery-cycle=(\d+) phase=first-gtk-draw input-us=(\d+)", line)
        if draw and draw[1] in buttons and buttons[draw[1]] is None:
            value = int(draw[2]) / 1000
            buttons[draw[1]] = value
            input_draw.append(value)
        send = re.search(r"resize-send .*accepted=1 target=(\d+)x(\d+) t=(\d+)ms", line)
        if send:
            if pending is not None:
                superseded += 1
            pending = int(send[3])
        end = re.search(r"display-transition end reason=([^ ]+) t=(\d+)ms", line)
        if end and pending is not None:
            elapsed = int(end[2]) - pending
            if elapsed < 0:
                malformed += 1
            elif end[1] == "frame-matched":
                resize.append(elapsed)
            else:
                failed_transition += 1
            pending = None
    return {"schema_version": 1, "scope": "client-log-samples-not-guest-business-verdict",
            "percentile_method": "nearest-rank",
            "resize_send_to_matched_frame_ms": stats(resize),
            "button_press_to_first_gtk_draw_ms": stats(input_draw),
            "button_presses_without_draw_record": sum(v is None for v in buttons.values()),
            "button_samples_over_5000ms": sum(v > 5000 for v in input_draw),
            "excluded_focus_or_motion_cycles": sum(v != "button-press" for v in reasons.values()),
            "superseded_resize_requests": superseded,
            "unmatched_transition_ends": failed_transition,
            "pending_resize_at_log_end": pending is not None,
            "invalid_time_samples": malformed,
            "limitations": ["绘制事件不证明点击命中了预期控件", "不测量屏保认证耗时",
                            "缺失或超时样本保留计数，不自动判定通过", "去抖等待不包含在 resize-send 延迟内"]}


def idle_observation(ctflab, manager, baseline):
    """仅观察绑定会话；黑画面不等于死机，不发送输入或 monitors config。"""
    current = manager.runtime_state("kali-arm64")
    keys = ("pid", "spice_client_pid", "qmp_path", "spice_client_log_path",
            "clipboard_enabled", "file_transfer_enabled")
    if not current or any(current.get(key) != baseline.get(key) for key in keys):
        raise ValueError("独立会话已改变，停止闲置观察，不跟随新实例")
    row = {"scope": "read-only-idle-observation-not-guest-health-verdict",
           "qemu_alive": ctflab.bool_pid_alive(int(current["pid"])),
           "client_alive": ctflab.bool_pid_alive(int(current["spice_client_pid"]))}
    if not row["qemu_alive"] or not row["client_alive"]:
        row["terminal"] = "bound-process-exited"
        return row
    row["host_process_usage"] = ctflab.sample_process_usage(
        [int(current["pid"]), int(current["spice_client_pid"])])
    try:
        row["qmp"] = ctflab.qmp_execute(Path(current["qmp_path"]), "query-status")
        # 不保留桌面内容，只记录尺寸和非黑比例；清理仅限工具自己的临时文件。
        with tempfile.TemporaryDirectory(prefix="ctflab-idle-frame-") as directory:
            frame = Path(directory) / "guest.ppm"
            ctflab.qmp_execute(Path(current["qmp_path"]), "screendump",
                               {"filename": str(frame)})
            row["frame"] = ctflab.ppm_display_activity(frame)
    except (OSError, ctflab.CTFLabError) as error:
        # 查询超时只记观察失败，不能当作进程退出或自动恢复触发器。
        row["observation_error"] = type(error).__name__
    try:
        info = Path(current["spice_client_log_path"]).stat()
        row["client_log"] = {"bytes": info.st_size, "modified_ns": info.st_mtime_ns}
    except OSError:
        row["client_log"] = {"available": False}
    return row


def main():
    if not sys.dont_write_bytecode:
        raise SystemExit("验收驱动必须使用 PYTHONDONTWRITEBYTECODE=1 和 python3 -B；请先校验候选 App，不能继续使用可能改写缓存的副本。")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "capture", "cycle-display", "finish", "metrics", "observe-idle", "clipboard-fixture", "guest-load-fixture"])
    parser.add_argument("--cycles", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--app", type=Path)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, default=2100)
    parser.add_argument("--sample-period-seconds", type=int, choices=range(1, 61), default=60)
    parser.add_argument("--observation-kind", choices=["idle", "load"], default="idle")
    parser.add_argument("--clipboard", action="store_true",
                        help="仅 prepare 可显式开启文本剪贴板；默认隔离，文件传输仍关闭")
    args = parser.parse_args()
    if args.clipboard and args.action != "prepare":
        parser.error("--clipboard 只允许 prepare；不得更改已有会话的共享授权")
    if args.action == "clipboard-fixture":
        clipboard_fixture(args.out)
        return
    if args.action == "guest-load-fixture":
        guest_load_fixture(args.out)
        return
    if args.action == "metrics":
        if not args.log or not args.log.is_file():
            parser.error("metrics 需要客户端 --log 文件")
        if args.log.stat().st_size > 64 * 1024 * 1024:
            parser.error("客户端日志超过 64 MiB，请先选取独立测试会话")
        report = display_metrics(args.log.read_text(encoding="utf-8", errors="replace"))
        report["log_sha256"] = digest(args.log)
        args.out.mkdir(parents=True, exist_ok=True)
        target = args.out / "display-metrics.json"
        # 验收证据排他创建，不覆盖先前测量结果。
        with target.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False))
        return
    if args.action == "observe-idle":
        if not args.state or not 60 <= args.duration_seconds <= 7200:
            parser.error("observe-idle 需要独立 --state，时长范围 60～7200 秒")
        import ctflab
        marker = json.loads((args.state / "ux-acceptance.json").read_text())
        if args.state.resolve() != Path(marker["state"]).resolve():
            raise ValueError("不是验收绑定的独立状态目录")
        manager = ctflab.LabManager(args.state)
        baseline = manager.runtime_state("kali-arm64")
        if not baseline:
            raise ValueError("独立 Kali 尚未运行")
        args.out.mkdir(parents=True, exist_ok=True)
        # 证据不可覆盖；不扫描其他会话，不访问口令、磁盘或剪贴板。
        with (args.out / "idle-observations.jsonl").open("x", encoding="utf-8") as output:
            started = time.monotonic()
            while True:
                row = idle_observation(ctflab, manager, baseline)
                row["scope"] = "read-only-%s-observation-not-guest-health-verdict" % args.observation_kind
                row["elapsed_seconds"] = round(time.monotonic() - started, 3)
                row["observed_unix_seconds"] = time.time()
                line = json.dumps(row, ensure_ascii=False)
                output.write(line + "\n")
                output.flush()
                print(line, flush=True)
                if row.get("terminal") or time.monotonic() - started >= args.duration_seconds:
                    break
                time.sleep(max(0, min(args.sample_period_seconds,
                                     args.duration_seconds - (time.monotonic() - started))))
        return
    if not args.app:
        parser.error("实例验收需要 --app")
    root = args.app.resolve()
    os.environ["CTFLAB_RUNTIME_ROOT"] = str(root / "Contents/Resources/runtime")
    # 验收 App 自己的解析结果，不继承开发终端的旧客户端覆盖。
    os.environ.pop("CTFLAB_SPICE_CLIENT", None)
    sys.path.insert(0, str(root / "Contents/Resources/ctflab/tools"))
    import ctflab
    from ctflab_app import app_tree_hash, verify_app
    args.out.mkdir(parents=True, exist_ok=True)
    if args.action == "prepare":
        # 先校验原始清单，不能把已损坏的候选作为“不变”基线。
        verify_app(root)
        record_path = Path.home() / "Library/Application Support/CTFLab/images/kali-arm64/image.json"
        record = json.loads(record_path.read_text())
        hashes = {record[key]: digest(record[key]) for key in ("base_path", "uefi_vars_path")}
        for key in ("base_path", "uefi_vars_path"):
            assert hashes[record[key]] == record[key.replace("_path", "_sha256")]
        state = Path(tempfile.mkdtemp(prefix="ctflab-ux-", dir="/private/tmp"))
        marker = {"state": str(state), "app": str(root), "asset_hashes": hashes,
                  "app_tree_hash": app_tree_hash(root)}
        ctflab.write_json(state / "ux-acceptance.json", marker)
        manager = ctflab.LabManager(state)
        target = manager.image_state_path("kali-arm64")
        target.parent.mkdir(parents=True)
        ctflab.write_json(target, record)
        profile = copy.deepcopy(ctflab.load_profile("kali-arm64"))
        profile["guest"].update(memory_mb=2048, cpus=2)
        def port():
            with socket.socket() as endpoint:
                endpoint.bind(("127.0.0.1", 0))
                return endpoint.getsockname()[1]
        manager.allocate_lab_port = port
        for forward in profile["network"].get("host_forwards", []):
            forward["host_port"] = port()
        try:
            run = manager.run(["kali-arm64"], display="spice", clipboard=args.clipboard,
                              file_transfer=False, profile_overrides={"kali-arm64": profile})[0]
        except BaseException:
            manager.stop(["kali-arm64"])
            raise
        ctflab.write_json(args.out / "prepare.json", {"state": str(state), "qemu_pid": run["pid"],
                          "client_pid": run["spice_client_pid"], "clipboard": args.clipboard, "file_transfer": False})
        print(json.dumps({"state": str(state), "qemu_pid": run["pid"], "client_pid": run["spice_client_pid"]}))
        return
    if not args.state:
        parser.error("capture/finish 需要 prepare 返回的 --state")
    marker_path = args.state / "ux-acceptance.json"
    marker = json.loads(marker_path.read_text())
    if args.state.resolve() != Path(marker["state"]).resolve() or str(root) != marker["app"]:
        raise ValueError("不是本验收的状态目录或 App")
    manager = ctflab.LabManager(args.state)
    if args.action == "cycle-display":
        # 仅操作 marker 绑定的派生实例；失败保留现场，由 finish 收尾。
        baseline = manager.runtime_state("kali-arm64")
        vm_pid = baseline["pid"]
        records = []
        try:
            for cycle in range(args.cycles):
                state = manager.runtime_state("kali-arm64")
                assert state["pid"] == vm_pid and ctflab.bool_pid_alive(vm_pid)
                pid = state["spice_client_pid"]
                assert ctflab.bool_pid_alive(pid)
                started = time.monotonic()
                os.kill(pid, signal.SIGTERM)
                while ctflab.bool_pid_alive(pid) and time.monotonic() - started < 7:
                    time.sleep(.05)
                log = Path(state["spice_client_log_path"]).read_text()
                row = {"cycle": cycle + 1, "client_pid": pid, "qemu_pid": vm_pid,
                       "exit_seconds": round(time.monotonic() - started, 3),
                       "cleanup_complete": "quit-cleanup-complete" in log,
                       "forced_timeout": "quit-forced-timeout" in log,
                       "client_exited": not ctflab.bool_pid_alive(pid)}
                records.append(row)
                assert row["client_exited"] and row["cleanup_complete"] and not row["forced_timeout"], row
                shown = manager.show_display("kali-arm64")
                restored = manager.runtime_state("kali-arm64")
                assert shown["reconnected"] and restored["pid"] == vm_pid
                assert all(restored.get(key) == baseline.get(key) for key in
                           ("clipboard_enabled", "file_transfer_enabled"))
                row["restored_client_pid"] = shown["pid"]
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if ctflab.spice_client_summary(restored)["display_ready"]:
                        break
                    time.sleep(.1)
                row["display_ready"] = ctflab.spice_client_summary(restored)["display_ready"]
                assert row["display_ready"], row
                print(json.dumps(row), flush=True)
        finally:
            ctflab.write_json(args.out / "client-cycles.json", records)
    elif args.action == "capture":
        state = manager.runtime_state("kali-arm64")
        ctflab.qmp_command(Path(state["qmp_path"]), "screendump", {"filename": str((args.out / "guest.ppm").resolve())})
        ctflab.write_json(args.out / "health.json", {"checks": manager.health("kali-arm64"), "qemu_pid": state["pid"]})
    else:
        manager.stop(["kali-arm64"])
        result = {"no_running_instances": not manager.running_states(),
                  "assets_unchanged": all(digest(path) == expected for path, expected in marker["asset_hashes"].items()),
                  "app_unchanged": app_tree_hash(root) == marker["app_tree_hash"],
                  "shutdown": "runner-stop-not-guest-poweroff"}
        ctflab.write_json(args.out / "finish.json", result)
        assert all(result[key] for key in ("no_running_instances", "assets_unchanged", "app_unchanged"))
        print(json.dumps(result))


if __name__ == "__main__":
    main()
