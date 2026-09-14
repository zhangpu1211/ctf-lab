#!/usr/bin/env python3
"""验收状态与动态分辨率设计边界的回归测试。

覆盖四类约束：

- 验收状态一致性：第 7 节每条验收项在复选框之后、说明冒号之前只有一个合法主状态标签；
  `[x]` 只能对应“已验证”，`[ ]` 不得对应“已验证”；关键验收项恰好一条，拒绝重复且相反的状态；
- 计划正文边界：网络策略表把靶机→Kali 标为“设计允许、应用级回连尚未验证”；显示章节把
  `qemu-vdagent` 限定为经授权的文本剪贴板路径，SPICE 显示与动态分辨率仍未实现；Task 2
  验收允许持久锁文件但不允许锁被持有；
- 设计文档边界：首段状态必须是“未实现任何后端”；路径 A 默认无网卡、默认关闭 UTM
  Clipboard Sharing、未来 Host Only 需 “Isolate Guest from Host”；路径 B 保留 agent
  transport 并强制三层剪贴板禁用、本机端点 + 每次运行本地鉴权、仅 kali-arm64、
  独立 PoC 前置；离线导出不得声称图形会话 agent 已连接；
- 当前阶段 CLI 边界：`run` 还没有显示后端选项，默认 QEMU 命令仍是 Cocoa 且没有 SPICE。
  未来的路径 B 经授权实现时应同步更新本测试与设计文档，而不是被旧断言误拦。
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from unittest import mock

TOOLS_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

import ctflab  # noqa: E402

PLAN = PROJECT_ROOT / "docs" / "ctflab-mac-mvp-implementation-plan.md"
VERIFICATION = PROJECT_ROOT / "docs" / "verification-2026-09-14.md"
DESIGN = PROJECT_ROOT / "docs" / "ctflab-dynamic-resolution-design.md"
STATUS_LABELS = ("已验证", "部分验证", "未验证", "后续任务")


def find_line(text: str, *needles: str) -> str:
    for line in text.splitlines():
        if all(needle in line for needle in needles):
            return line.strip()
    raise AssertionError(f"未找到同时包含 {needles} 的行")


def find_all_lines(text: str, *needles: str) -> list[str]:
    return [line.strip() for line in text.splitlines()
            if all(needle in line for needle in needles)]


def text_between(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


def normalized(text: str) -> str:
    """折叠换行与多余空白，便于断言跨行短语。"""
    return " ".join(text.split())


def primary_status(line: str) -> str:
    """取出验收项的主状态：复选框之后、说明冒号之前的唯一标签。"""
    stripped = line.strip()
    for prefix in ("- [x] ", "- [ ] "):
        if stripped.startswith(prefix):
            tail = stripped[len(prefix):]
            break
    else:
        raise AssertionError(f"不是验收项行：{line}")
    head, separator, _ = tail.partition("：")
    if not separator:
        raise AssertionError(f"验收项缺少主状态冒号：{line}")
    return head.strip()


def acceptance_items() -> list[str]:
    return [line.strip() for line in plan_acceptance_section().splitlines()
            if line.strip().startswith(("- [x]", "- [ ]"))]


def plan_acceptance_section() -> str:
    return text_between(PLAN.read_text(encoding="utf-8"),
                        "## 7. 第一阶段验收清单", "## 8. ")


def plan_section(start_marker: str, end_marker: str) -> str:
    return text_between(PLAN.read_text(encoding="utf-8"), start_marker, end_marker)


class PlanAcceptanceTests(unittest.TestCase):
    def test_status_categories_are_defined(self) -> None:
        section = plan_acceptance_section()
        for label in STATUS_LABELS:
            self.assertIn(label, section)

    def test_every_item_has_exactly_one_primary_status(self) -> None:
        items = acceptance_items()
        self.assertGreaterEqual(len(items), 10)
        for line in items:
            status = primary_status(line)
            self.assertIn(status, STATUS_LABELS,
                          f"验收项主状态必须是四个标签之一：{line}")

    def test_checked_items_are_verified_only(self) -> None:
        checked = [line for line in acceptance_items() if line.startswith("- [x]")]
        self.assertGreaterEqual(len(checked), 5)
        for line in checked:
            self.assertEqual(primary_status(line), "已验证",
                             f"[x] 只能对应“已验证”：{line}")

    def test_unchecked_items_are_not_verified(self) -> None:
        unchecked = [line for line in acceptance_items() if line.startswith("- [ ]")]
        self.assertGreaterEqual(len(unchecked), 3)
        for line in unchecked:
            self.assertNotEqual(primary_status(line), "已验证",
                                f"[ ] 不得对应“已验证”：{line}")

    def test_key_acceptance_items_are_unique(self) -> None:
        section = plan_acceptance_section()
        for needle in ("扫描并访问两台靶机", "应用级主动回连", "干净的 Mac M 用户环境"):
            lines = find_all_lines(section, needle)
            self.assertEqual(len(lines), 1, f"关键验收项应恰好一条：{needle}（实际 {len(lines)}）")

    def test_scan_and_access_targets_is_passed(self) -> None:
        line = find_all_lines(plan_acceptance_section(), "扫描并访问两台靶机")[0]
        self.assertTrue(line.startswith("- [x]"), line)
        self.assertEqual(primary_status(line), "已验证")

    def test_app_level_callback_is_not_passed(self) -> None:
        line = find_all_lines(plan_acceptance_section(), "应用级主动回连")[0]
        self.assertTrue(line.startswith("- [ ]"), line)
        self.assertEqual(primary_status(line), "未验证")

    def test_clean_environment_install_is_not_passed(self) -> None:
        line = find_all_lines(plan_acceptance_section(), "干净的 Mac M 用户环境")[0]
        self.assertTrue(line.startswith("- [ ]"), line)
        self.assertEqual(primary_status(line), "后续任务")
        self.assertIn("Task 6", line)

    def test_task3_dynamic_resolution_item_is_unchecked(self) -> None:
        task3 = plan_section("### Task 3：Kali 图形桌面", "### Task 4：")
        items = [line.strip() for line in task3.splitlines()
                 if line.strip().startswith(("- [x]", "- [ ]")) and "动态分辨率" in line]
        self.assertEqual(len(items), 1, "Task 3 应只有一条动态分辨率验收项")
        self.assertTrue(items[0].startswith("- [ ]"), items[0])
        self.assertIn("尚未 E2E 验收", items[0])

    def test_task2_acceptance_allows_persistent_lock_file(self) -> None:
        task2 = plan_section("### Task 2：存储与生命周期", "### Task 3：")
        line = find_line(task2, "**验收：**")
        self.assertIn("锁文件可以持久存在", line)
        self.assertIn("不得有锁被持有", line)
        self.assertNotIn("没有残留 QEMU 进程、锁", line)

    def test_task4_acceptance_splits_isolation_and_callback(self) -> None:
        task4 = plan_section("### Task 4：实验网与 Kali 互通", "### Task 5：")
        line = find_line(task4, "**验收：**")
        self.assertIn("已验证", line)
        self.assertIn("未验证项", line)
        self.assertNotIn("反向 Shell 可回连 Kali", line)


class PlanDocumentTests(unittest.TestCase):
    def test_network_policy_marks_callback_unverified(self) -> None:
        policy = plan_section("### 3.2 网络策略", "## 4. 内容包与运行时约定")
        line = find_line(policy, "靶机 → Kali")
        self.assertIn("设计允许", line)
        self.assertIn("尚未验证", line)

    def test_display_section_scopes_qemu_vdagent(self) -> None:
        plan = PLAN.read_text(encoding="utf-8")
        line = find_line(plan, "qemu-vdagent")
        self.assertIn("仅是经授权的文本剪贴板路径", line)
        self.assertIn("SPICE 显示与动态分辨率", line)
        self.assertIn("均未实现", line)


class VerificationRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = VERIFICATION.read_text(encoding="utf-8")

    def test_four_categories_are_explicit(self) -> None:
        for label in STATUS_LABELS:
            self.assertIn(label, self.text)

    def test_regression_count_is_dated(self) -> None:
        # 不钉死数字（测试集会增长），但必须带日期表述，避免未来语义陈旧
        self.assertIn("本次完整回归（2026-09-14）", self.text)
        self.assertNotIn("66 项通过", self.text)
        self.assertNotIn("当前完整回归", self.text)

    def test_matrix_wording_avoids_adapted_claim(self) -> None:
        self.assertIn("候选命中事件", self.text)
        self.assertNotIn("实测命中", self.text)

    def test_clean_environment_is_partial_not_passed(self) -> None:
        self.assertNotIn("干净用户环境验证（通过）", self.text)
        self.assertIn("干净用户环境验证（部分验证", self.text)
        self.assertIn("不构成", self.text)
        self.assertIn("Task 6", self.text)

    def test_callback_only_has_frame_level_evidence(self) -> None:
        line = find_line(self.text, "靶机→Kali 帧级双向")
        self.assertIn("部分验证", line)
        app_level = find_line(self.text, "应用级主动回连")
        self.assertIn("未验证", app_level)


class DesignBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = DESIGN.read_text(encoding="utf-8")

    def test_header_status_blocks_claims(self) -> None:
        """锚定文档首段状态，而不是全文任意位置出现“未实现”。"""
        header = text_between(self.text, "# CTFLab 动态分辨率设计", "## 1.")
        self.assertIn("未实现任何后端", header)
        self.assertIn("不支持动态分辨率", header)
        self.assertIn("默认不带网卡", header)
        self.assertIn("默认关闭 UTM Clipboard Sharing", header)
        self.assertIn("剪贴板按 `--clipboard`", header)
        self.assertIn("授权时才允许文本剪贴板", header)

    def test_design_covers_both_paths_and_non_goals(self) -> None:
        for needle in ("UTM", "SPICE", "最小实现切片", "测试矩阵", "不做"):
            self.assertIn(needle, self.text)

    def test_path_a_boundaries(self) -> None:
        for needle in ("默认不含任何网卡", "不接受任意用户", "一律拒绝",
                       "Isolate Guest from Host", "Clipboard Sharing",
                       "Host Only IP", "不得声称", "动态分辨率的唯一证据"):
            self.assertIn(needle, self.text)

    def test_path_a_offline_export_does_not_claim_agent_session(self) -> None:
        flat = normalized(self.text)
        self.assertIn("不得声称 已证明图形会话 agent 连接", flat)
        self.assertIn("只能在导出包启动后的 UTM E2E 中验收", flat)

    def test_path_b_boundaries(self) -> None:
        for needle in ("启动前明确报错", "不得实现路径 B", "addr=127.0.0.1", "负向 E2E",
                       "disable-copy-paste=on", "disable-agent-file-xfer=on",
                       "本地鉴权", "kali-arm64", "前置 PoC",
                       "virtio-serial + spicevmc agent transport"):
            self.assertIn(needle, self.text)

    def test_clipboard_flags_are_conditional(self) -> None:
        """剪贴板标志必须随 `--clipboard` 条件切换，不得写成无条件固定值。"""
        flat = normalized(self.text)
        self.assertIn("未传 `--clipboard` 时", flat)
        self.assertIn("`disable-copy-paste=on`", flat)
        self.assertIn("传入 `--clipboard` 时", flat)
        self.assertIn("`disable-copy-paste=off`", flat)
        self.assertIn("允许文本剪贴板", flat)
        for stale in ("始终存在", "剪贴板能力逐层关闭", "SPICE 侧强制", "必须逐层关闭剪贴板"):
            self.assertNotIn(stale, flat, f"仍存在无条件剪贴板表述：{stale}")

    def test_endpoint_modes_are_separate(self) -> None:
        """UNIX socket 与 TCP 是两套互斥要求，不得混写为同时成立。"""
        flat = normalized(self.text)
        self.assertIn("`unix=<socket 路径>`", flat)
        self.assertIn("不要求也不应出现 `addr=127.0.0.1`/`port=`", flat)
        self.assertIn("`addr=127.0.0.1,port=<受控端口>`", flat)
        self.assertNotIn("生成的命令必须包含 `addr=127.0.0.1`", flat)

    def test_cli_scope_wording_is_precise(self) -> None:
        flat = normalized(self.text)
        self.assertIn("本次未新增动态分辨率相关 CLI", flat)
        self.assertIn("`probe --matrix`", flat)
        self.assertNotIn("未新增任何 CLI", flat)

    def test_obsolete_clipboard_wording_is_gone(self) -> None:
        for stale in ("不建立任何 vdagent/spicevmc 剪贴板通道",
                      "未传 `--clipboard` 时命令不含任何 vdagent/spicevmc 通道",
                      "默认不创建任何剪贴板设备",
                      "不得创建任何"):
            self.assertNotIn(stale, self.text)


class CurrentStageCliTests(unittest.TestCase):
    """路径 B 未实现前的当前阶段断言；实现路径 B 时需同步更新本测试与设计文档。"""

    def run_options(self) -> set[str]:
        parser = ctflab.build_parser()
        subcommands: dict[str, object] = {}
        for action in parser._subparsers._group_actions:
            subcommands.update(action.choices)
        return {option for action in subcommands["run"]._actions
                for option in action.option_strings}

    def test_run_has_no_display_option_yet(self) -> None:
        self.assertNotIn("--display", self.run_options(),
                         "显示后端选项属于路径 B，未授权实现前不应出现在 run 上")

    def test_default_command_stays_cocoa_without_spice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            manager = ctflab.LabManager(root)
            profile = {"guest": {"architecture": "aarch64"}, "network": {}}
            with mock.patch.object(manager, "ensure_uefi_vars",
                                   return_value=(root / "code", root / "vars")), \
                    mock.patch("ctflab.which_any", return_value="qemu"):
                command, _ = manager.qemu_command("kali-arm64", profile,
                                                  root / "disk.qcow2", 23400, False)
        joined = " ".join(command)
        self.assertIn("cocoa", joined)
        self.assertNotIn("spice", joined.lower())
        self.assertNotIn("qemu-vdagent", joined, "默认不传 --clipboard 时不得创建剪贴板通道")


if __name__ == "__main__":
    unittest.main()
