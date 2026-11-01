"""Mac(Swift)模型与Python契约同输入对照；真实服务/真实SQLite，无桌面或来宾。

事件判定与 contract.merge_events 对照（含断流重定位）；历史/原响应回复以真实
LocalService账本为准：真实回复必须被接受，篡改字段必须被拒绝。跳过swiftc环境时
明确跳过，不把跳过当跨语言通过。
"""
import copy
import json
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

sys_path = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(sys_path))
import ctflab_contract as contract
import ctflab_desktop_bridge as bridge
from ctflab_local_service import LocalService
from ctflab_windows_probe import FixtureBackend

SWIFTC = shutil.which("swiftc")
GUI_DIR = Path(__file__).resolve().parents[2] / "gui"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def event_cases(events, instance):
    """复用前端对照的同一组变异矩阵，保证三端输入一致。"""
    from test_ctflab_contract_parity import event_cases as build
    return build(events, instance)


def expected_refresh(case, view):
    """与MacEventPage.refresh同语义：拒绝时只用绑定状态快照重定位。"""
    instance = case["instance"]
    try:
        cursor, fresh = contract.merge_events(case["cursor"], case["events"], instance_uuid=instance)
        return {"cursor": cursor, "reload": False, "count": len(fresh)}
    except contract.ContractError:
        status = view.get("status") if isinstance(view, dict) else None
        bound = (isinstance(status, dict) and status.get("protocol") == "ctflab-local"
                 and status.get("version") == 1 and isinstance(instance, str) and UUID.fullmatch(instance)
                 and status.get("instance_uuid") == instance
                 and type(status.get("cursor")) is int and 0 <= status["cursor"] <= 2**53 - 1)
        return {"cursor": status["cursor"] if bound else 0, "reload": True, "count": 0}


@unittest.skipUnless(SWIFTC, "需要 swiftc（Xcode 命令行工具）编译 Mac 契约模型")
class MacContractParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp = tempfile.TemporaryDirectory()
        cls._swift_cache = tempfile.TemporaryDirectory(prefix="ctflab-swift-parity-cache-")
        binary = Path(cls._temp.name) / "gui-core-tests"
        import os
        env = dict(os.environ); env["CLANG_MODULE_CACHE_PATH"] = cls._swift_cache.name
        cls._compile = subprocess.run(
            [SWIFTC, "-O", "-target", "arm64-apple-macos14", "-o", str(binary),
             str(GUI_DIR / "GuiCore.swift"), str(GUI_DIR / "GuiCoreTests.swift")],
            capture_output=True, text=True, env=env)
        cls._binary = str(binary) if cls._compile.returncode == 0 else None

    @classmethod
    def tearDownClass(cls):
        cls._swift_cache.cleanup(); cls._temp.cleanup()

    def setUp(self):
        self.assertIsNotNone(self._binary, f"Mac 契约模型编译失败：{self._compile.stderr[:400]}")
        from test_ctflab_generation_store import GenerationTests
        GenerationTests.setUp(self)
        from ctflab_local_adapter import process_actor
        self.actor = process_actor()
        self.service = LocalService.create(self.store.root / "desktop-contract")
        self.backend = FixtureBackend()

    def swift_decide(self, vectors):
        result = subprocess.run([self._binary, "--contract-vectors"], cwd=str(Path(__file__).resolve().parents[2]),
                                input=contract.canonical(vectors), capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        return json.loads(result.stdout)

    def prepare(self):
        req = {"protocol": "ctflab-local", "version": 1, "request_id": str(uuid.uuid4()),
               "instance_uuid": self.instance, "operation": "prepare", "expected_generation": None,
               "expected_state_revision": None, "idempotency_key": str(uuid.uuid4()),
               "parameters": {"course_id": "course", "baseline_id": "base"}}
        accepted = self.service.submit(req, self.actor)
        self.service.execute(accepted["operation_id"], self.actor, self.backend)
        return accepted

    def test_event_vectors_match_merge_events_including_relocation(self):
        self.prepare()
        events = self.service.events(self.instance, self.actor)
        self.assertEqual(len(events), 3)
        status = self.service.status({"protocol": "ctflab-local", "version": 1, "request_id": str(uuid.uuid4()),
                                      "operation": "status", "instance_uuid": self.instance}, self.actor)
        vectors, expected = [], []
        for case in event_cases(events, self.instance):
            unbound = {"instance_uuid": case["instance"]} if case["instance"] else None
            bound = {"instance_uuid": case["instance"], "status": status} if case["instance"] else None
            for view in (unbound, bound):
                vectors.append({"cursor": case["cursor"], "response": case["events"], "view": view or None})
                expected.append(expected_refresh(case, view or {}))
        original = copy.deepcopy(vectors)
        results = self.swift_decide({"events": vectors, "history": [], "records": []})["events"]
        self.assertEqual(len(results), len(expected))
        for row, want, vector in zip(results, expected, original):
            with self.subTest(row=row, want=want):
                self.assertEqual(row, want)
        self.assertGreater(len(results), 150)
        self.assertEqual(vectors, original)

    def test_real_history_and_record_replies_accepted_and_tampering_rejected(self):
        self.prepare()
        root = self.store.root / "desktop-contract"
        history = self.service.operation_history(self.instance, self.actor, limit=20)
        op_id = history["operations"][0]["operation_id"]
        pending = self.service.operation_result(self.instance, op_id, self.actor)
        wire = subprocess.run([sys.executable, "-I", "-B", str(sys_path / "ctflab_desktop_bridge.py"),
                               "bridge", "--run", str(self.store.root)],
                              input=contract.canonical({"action": "operation-result", "operation_id": op_id}),
                              capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[2]), timeout=15)
        self.assertEqual(wire.returncode, 0, wire.stderr[-400:])
        recorded = json.loads(wire.stdout)
        self.assertEqual(recorded["state"], "operation-recorded")
        self.service.execute(op_id, self.actor, self.backend)
        completed = self.service.operation_result(self.instance, op_id, self.actor)
        self.assertIsNotNone(completed["response"])
        vectors, expected = [], []
        def add(reply, accept, instance=None):
            vectors.append({"reply": reply, "instance": instance or self.instance}); expected.append(accept)
        history_vectors = [{"reply": history, "instance": self.instance}]
        for reply in (pending, completed):
            add(reply, True)
        other = str(uuid.uuid4())
        add(dict(history, instance_uuid=other), False)
        add(dict(history, historical=False), False)
        add(dict(history, current_runtime_verified=True), False)
        add(dict(history, automatic_replay=True), False)
        add({k: v for k, v in history.items() if k != "truncated"}, False)
        add(dict(history, next_before=str(uuid.uuid4())), False)
        add(dict(history, operations=history["operations"] + [dict(history["operations"][0], status="pending")]), False)
        add(dict(history, operations=[dict(history["operations"][0], idempotency_key="private")]), False)
        add(dict(pending, record=dict(pending["record"], status="pending")), False)
        add(dict(completed, response=None), False)
        add(dict(completed, response=dict(completed["response"], request_id=str(uuid.uuid4()))), False)
        add(dict(completed, response=dict(completed["response"], result="accepted")), False)
        add(dict(completed, response=dict(completed["response"], extra="private")), False)
        add(dict(completed, response=dict(completed["response"],
            error={"code": "backend-failed", "stage": "dispatch", "message": "私有路径", "retryable": False,
                   "preserved": True, "recovery_actions": ["status"], "evidence_refs": []})), False)
        add(dict(completed, response=dict(completed["response"], evidence_refs=["x" * 97])), False)
        add(dict(completed, response=dict(completed["response"], state="ready")), False)
        results = self.swift_decide({"events": [], "history": history_vectors, "records": vectors})
        self.assertEqual(results["history"], [True])
        self.assertEqual(results["records"], expected)
        self.assertEqual(results["records"][0], True)
        # 桥接真实历史wire同样被接受；SQLite字节不变，读取无副作用。
        before = (root / "contract.sqlite3").read_bytes()
        history_wire = subprocess.run([sys.executable, "-I", "-B", str(sys_path / "ctflab_desktop_bridge.py"),
                                       "bridge", "--run", str(self.store.root)],
                                      input=contract.canonical({"action": "operation-history", "limit": 20}),
                                      capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[2]), timeout=15)
        self.assertEqual(history_wire.returncode, 0, history_wire.stderr[-400:])
        page = json.loads(history_wire.stdout)
        self.assertEqual(self.swift_decide({"events": [], "history": [{"reply": page, "instance": self.instance}],
                                            "records": []})["history"], [True])
        self.assertEqual(before, (root / "contract.sqlite3").read_bytes())

    def test_relocation_after_real_cursor_expiration_matches_bound_status(self):
        self.prepare()
        status = self.service.status({"protocol": "ctflab-local", "version": 1, "request_id": str(uuid.uuid4()),
                                      "operation": "status", "instance_uuid": self.instance}, self.actor)
        events = self.service.events(self.instance, self.actor)
        self.service.prune_events(self.instance, self.actor, through=1)
        first = dict(events[0], version=2)
        vectors = [{"cursor": 0, "response": [], "view": {"instance_uuid": self.instance, "status": status}},
                   {"cursor": 0, "response": [first], "view": {"instance_uuid": self.instance, "status": status}},
                   {"cursor": 0, "response": [first], "view": {"instance_uuid": self.instance}}]
        results = self.swift_decide({"events": vectors, "history": [], "records": []})["events"]
        # 空数组是合法回复（游标不动）；真实被裁剪游标拒绝后按绑定状态重定位，未绑定不决定游标。
        self.assertEqual(results[0], {"cursor": 0, "reload": False, "count": 0})
        self.assertEqual(results[1], {"cursor": status["cursor"], "reload": True, "count": 0})
        self.assertEqual(results[2], {"cursor": 0, "reload": True, "count": 0})


if __name__ == "__main__":
    unittest.main()
