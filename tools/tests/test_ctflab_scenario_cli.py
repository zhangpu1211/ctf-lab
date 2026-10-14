"""场景 CLI 入口合成验证：status/prepare/start/stop/reset/recover 全链路。

start 使用合成 qemu 桩（真实子进程 + 真实 QMP UNIX socket）与真实 DHCP 服务
子进程（继承测试自身的回环 FD）；没有真实 VM、对外网络或用户实例/资产操作。
qemu-img 经注入的合成执行器处理，真实 qemu-img 不在本轮运行。
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import test_ctflab_scenario as scenario_fixture
from test_ctflab_scenario import INSTANCE
import ctflab
import ctflab_scenario as scenario
import ctflab_scenario_registry as registry
import ctflab_scenario_resources as resources

QEMU_STUB = '''#!/usr/bin/env python3
import json, os, socket, sys, time
args = sys.argv[1:]
qmp_path = None
for index, value in enumerate(args):
    if value == "-qmp":
        qmp_path = args[index + 1][5:].split(",")[0]
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(qmp_path)
server.listen(4)


def handle(conn):
    conn.sendall(b'{"QMP": {"version": "synthetic"}}\\n')
    while True:
        data = conn.recv(4096)
        if not data:
            return
        command = json.loads(data).get("execute")
        if command == "qmp_capabilities":
            conn.sendall(b'{"return": {}}\\n')
        elif command == "query-status":
            conn.sendall(b'{"return": {"status": "running"}}\\n')
        elif command == "system_powerdown":
            conn.sendall(b'{"return": {}}\\n')
            conn.close()
            time.sleep(0.05)
            os._exit(0)  # 模拟来宾 ACPI 关机后退出。
        else:
            conn.sendall(b'{"error": {"desc": "unknown"}}\\n')


while True:
    conn, _ = server.accept()
    handle(conn)
'''


def run_cli(*argv):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        code = ctflab.main(list(argv))
    return code, stdout.getvalue(), stderr.getvalue()


class ScenarioCliTests(unittest.TestCase):
    """通过真实 main() 与生产处理器走完整链路；qemu-img/路由/QEMU 二进制全部注入。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="csc-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "state"
        socket_temp = tempfile.TemporaryDirectory(prefix="sc-", dir="/private/tmp" if Path("/private/tmp").exists() else "/tmp")
        self.addCleanup(socket_temp.cleanup)
        self.sockets = Path(socket_temp.name).resolve() / "sc"
        self.manifest = self.build_manifest()
        self.qemu_stub = None
        self.stderr = ""

    def build_manifest(self) -> dict:
        manifest = scenario_fixture.candidate()
        for key, spec in manifest["assets"].items():
            path = self.base / f"{key}-cli.qcow2"
            path.write_bytes(("cli-base-" + key).encode())
            spec["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        return scenario.instance_plan(manifest, INSTANCE, available_capabilities=scenario_fixture.CAPS)["manifest"]

    def cli(self, *argv):
        tools = {"qemu-img": "/synthetic/qemu-img",
                 "qemu-system-aarch64": str(self.qemu_stub) if self.qemu_stub else None,
                 "qemu-system-x86_64": str(self.qemu_stub) if self.qemu_stub else None}
        started = [mock.patch.object(ctflab, "resolve_tool", lambda name, *a, **k: tools.get(name)),
                   mock.patch.object(ctflab, "scenario_image_run", lambda: self.image_run),
                   mock.patch.object(resources, "collect_macos_routes",
                                     lambda: {"routes": [], "observed_at": resources.time.monotonic()})]
        for patch in started:
            patch.start()
            self.addCleanup(patch.stop)
        code, output, errors = run_cli("scenario", *argv,
                                       "--state-root", str(self.root), "--socket-root", str(self.sockets))
        self.stderr = errors
        return code, output

    def image_run(self, args, **_kwargs):
        path = Path(args[-1])
        if args[1] == "create":
            path.write_text(args[-2])
            return subprocess.CompletedProcess(args, 0, "", "")
        if path.name == "overlay.qcow2":
            info = {"format": "qcow2", "full-backing-filename": path.read_text(),
                    "backing-filename-format": "qcow2"}
        else:
            info = {"format": "qcow2"}
        return subprocess.CompletedProcess(args, 0, json.dumps(info), "")

    def prepare_args(self):
        manifest_path = self.base / "manifest.json"
        manifest_path.write_text(json.dumps(self.manifest, ensure_ascii=False))
        args = ["prepare", "--manifest", str(manifest_path)]
        for key in self.manifest["assets"]:
            args += ["--asset", f"{key}={self.base / (key + '-cli.qcow2')}"]
        code = self.base / "code.fd"
        variables = self.base / "vars.fd"
        code.write_bytes(b"cli-firmware-code")
        variables.write_bytes(b"cli-firmware-vars")
        args += ["--firmware", f"kali={code},{variables}"]
        return args

    def cleanup_children(self):
        """兜底清理：按生命周期日志记录的 PID 终止本轮启动的合成子进程。"""
        pids = set()
        for journal in self.root.rglob("*-lifecycle.jsonl"):
            for event in registry.read_events(journal):
                for record in (event.get("processes") or {}).values():
                    if isinstance(record, dict) and isinstance(record.get("pid"), int):
                        pids.add(record["pid"])
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def full_lifecycle(self):
        self.qemu_stub = self.base / "qemu-stub.py"
        # shebang 直接指向当前解释器：避免 env 二次 exec 造成 ps 身份漂移。
        self.qemu_stub.write_text(f"#!{sys.executable}\n" + QEMU_STUB)
        self.qemu_stub.chmod(0o755)
        self.addCleanup(self.cleanup_children)
        code, output = self.cli(*self.prepare_args())
        self.assertEqual(code, 0, output)
        code, output = self.cli("start")
        self.assertEqual(code, 0, output)
        self.assertIn("场景已启动", output)

    def test_status_empty_state_root(self):
        code, output = self.cli("status")
        self.assertEqual(code, 0)
        self.assertIn("没有场景实例", output)

    def test_scenario_roots_follow_state_dir_and_avoid_profile_namespace(self):
        # GUI 经全局 --state-dir 覆盖时，场景根必须跟随同一状态目录，
        # 且与单机 profile/images 子树互不包含：单机入口不能摸到场景资产。
        parser_args = ctflab.build_parser().parse_args(
            ["--state-dir", "/tmp/fake-state", "scenario", "status"])
        state_root, socket_root = ctflab.scenario_state_roots(parser_args)
        self.assertEqual(state_root, Path("/tmp/fake-state/scenario-state"))
        base = Path("/tmp/fake-state")
        for profile_path in (base / "profiles" / "kali-arm64", base / "images" / "kali-arm64"):
            self.assertFalse(profile_path.is_relative_to(state_root))
            self.assertFalse(state_root.is_relative_to(profile_path))
        self.assertNotEqual(socket_root, base / "scenario-sockets")
        self.assertTrue(str(socket_root).startswith("/"))

    def test_instance_resolution_explicit_and_ambiguous(self):
        self.full_lifecycle()
        instance = next((self.root / "scenarios").iterdir()).name
        code, output = self.cli("status", "--instance", instance)
        self.assertEqual(code, 0, output)
        self.assertIn(instance, output)
        code, output = self.cli("status", "--instance", "00000000-0000-4000-8000-000000000000")
        self.assertEqual(code, 2)
        self.assertIn("没有场景实例", self.stderr)

    def test_prepare_writes_reservation_without_pointer(self):
        code, output = self.cli(*self.prepare_args())
        self.assertEqual(code, 0, output)
        self.assertIn("场景资产已准备", output)
        self.assertEqual(len(registry.active_reservations(self.root)), 1)
        self.assertFalse((self.root / "scenarios" / INSTANCE / "active-generation.json").exists())

    def test_start_status_stop_end_to_end_with_synthetic_children(self):
        self.full_lifecycle()
        code, output = self.cli("status", "--json")
        self.assertEqual(code, 0, output)
        report = json.loads(output)[0]
        self.assertEqual(report["active"], {"generation": 1, "descriptor": "prepared.json"})
        self.assertEqual(report["nodes"]["state"], "nodes-observed")
        self.assertEqual(report["services"]["state"], "networks-observed")
        self.assertEqual(sorted(report["nodes"]["live"]), ["kali", "neuromancer", "straylight"])
        self.assertEqual(len(report["reservations"]), 1)
        # 重复 start 必须拒绝：该代次已有启动记录。
        code, output = self.cli("start")
        self.assertEqual(code, 2)
        self.assertIn("已有启动记录", self.stderr)
        code, output = self.cli("stop")
        self.assertEqual(code, 0, output)
        self.assertIn("节点：stopped", output)
        code, output = self.cli("status", "--json")
        report = json.loads(output)[0]
        self.assertEqual(report["nodes"]["state"], "stopped-observed")
        self.assertEqual(report["services"]["state"], "stopped-observed")
        self.assertEqual(len(report["reservations"]), 1)  # 停止不释放预约。

    def test_stop_proof_gates_reset_then_multi_generation(self):
        self.full_lifecycle()
        code, output = self.cli("reset", "--new-generation", "2")
        self.assertEqual(code, 2)
        self.assertIn("未证明停止", self.stderr)
        code, output = self.cli("stop")
        self.assertEqual(code, 0, output)
        code, output = self.cli("reset", "--new-generation", "2")
        self.assertEqual(code, 0, output)
        self.assertIn("重置已提交", output)
        code, output = self.cli("status", "--json")
        report = json.loads(output)[0]
        self.assertEqual(report["active"]["generation"], 2)
        self.assertEqual(report["reset"]["state"], "committed-observed")
        # 新代次接续启动后再次停止、再重置，覆盖跨代次闭环。
        code, output = self.cli("start")
        self.assertEqual(code, 0, output)
        code, output = self.cli("stop")
        self.assertEqual(code, 0, output)
        code, output = self.cli("reset", "--new-generation", "3")
        self.assertEqual(code, 0, output)

    def test_recover_without_flags_reports_status(self):
        self.full_lifecycle()
        self.cli("stop")
        code, output = self.cli("recover")
        self.assertEqual(code, 0)
        self.assertIn("stopped-observed", output)

    def current_instance(self) -> str:
        return next((self.root / "scenarios").iterdir()).name

    def test_release_gated_by_stop_proof_then_idempotent(self):
        self.full_lifecycle()
        # 运行中释放必须被停止证明拒绝，预约保持活跃。
        code, output = self.cli("release")
        self.assertEqual(code, 2)
        self.assertIn("未证明全部停止", self.stderr)
        self.assertEqual(len(registry.active_reservations(self.root)), 1)
        code, output = self.cli("stop")
        self.assertEqual(code, 0, output)
        code, output = self.cli("status", "--json")
        report = json.loads(output)[0]
        self.assertTrue(any("scenario release" in item for item in report["next"]))
        code, output = self.cli("release", "--json")
        self.assertEqual(code, 0, output)
        result = json.loads(output)
        instance = self.current_instance()
        self.assertEqual(result["instance_uuid"], instance)
        self.assertEqual(len(result["released"]), 1)
        self.assertEqual(result["released"][0]["generation"], 1)
        self.assertGreater(len(result["released"][0]["macs"]), 0)
        self.assertEqual(registry.active_reservations(self.root), {})
        # 释放只追加登记历史：指针、准备记录与代次资产全部保留。
        scene = self.root / "scenarios" / instance
        self.assertTrue((scene / "active-generation.json").exists())
        self.assertTrue((scene / "generations" / "1" / "prepared.json").exists())
        self.assertTrue((scene / "generations" / "1" / "node-lifecycle.jsonl").exists())
        # 幂等：无活跃预约时再次 release 成功且不做任何事。
        code, output = self.cli("release")
        self.assertEqual(code, 0, output)
        self.assertIn("没有活跃预约", output)

    def test_release_then_new_generation_cycle(self):
        # 释放后状态根不是死路：reset→start 走"旧预约已释放"接续分支重新预约。
        self.full_lifecycle()
        self.cli("stop")
        code, output = self.cli("release")
        self.assertEqual(code, 0, output)
        self.assertIn("预约已释放", output)
        code, output = self.cli("reset", "--new-generation", "2")
        self.assertEqual(code, 0, output)
        code, output = self.cli("start")
        self.assertEqual(code, 0, output)
        self.assertEqual(len(registry.active_reservations(self.root)), 1)
        code, output = self.cli("stop")
        self.assertEqual(code, 0, output)

    def test_release_prepared_instance_without_pointer(self):
        # 只 prepare 未 start 的实例同样可释放：从未启动按停止证明处理。
        code, output = self.cli(*self.prepare_args())
        self.assertEqual(code, 0, output)
        instance = self.current_instance()
        self.assertFalse((self.root / "scenarios" / instance / "active-generation.json").exists())
        code, output = self.cli("release")
        self.assertEqual(code, 0, output)
        self.assertIn("预约已释放", output)
        self.assertEqual(registry.active_reservations(self.root), {})
        # 释放后代次进入登记历史，可在新代次重新 prepare。
        code, output = self.cli(*self.prepare_args(), "--generation", "2")
        self.assertEqual(code, 0, output)
        self.assertEqual(len(registry.active_reservations(self.root)), 1)


if __name__ == "__main__":
    unittest.main()
