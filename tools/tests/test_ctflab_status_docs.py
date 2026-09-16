#!/usr/bin/env python3
"""验收状态与动态分辨率设计边界的回归测试。

覆盖四类约束：

- 验收状态一致性：第 7 节每条验收项在复选框之后、说明冒号之前只有一个合法主状态标签；
  `[x]` 只能对应“已验证”，`[ ]` 不得对应“已验证”；关键验收项恰好一条，拒绝重复且相反的状态；
- 计划正文边界：网络策略表把靶机→Kali 标为“设计允许、应用级回连尚未验证”；显示章节把
  `qemu-vdagent` 限定为经授权的文本剪贴板路径，SPICE 显示与动态分辨率仍未实现；Task 2
  验收允许持久锁文件但不允许锁被持有；
- 设计文档边界：首段状态必须是“路径 A 已实现、路径 B 未实现”；路径 A 默认无网卡、默认关闭 UTM
  Clipboard Sharing、未来 Host Only 需 “Isolate Guest from Host”；路径 B 保留 agent
  transport 并强制三层剪贴板禁用、本机端点 + 每次运行本地鉴权、仅 kali-arm64、
  独立 PoC 前置；离线导出不得声称图形会话 agent 已连接；
- 当前阶段 CLI 边界：`run` 还没有显示后端选项，默认 QEMU 命令仍是 Cocoa 且没有 SPICE。
  未来的路径 B 经授权实现时应同步更新本测试与设计文档，而不是被旧断言误拦。
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
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
SMOKE_RECORD = PROJECT_ROOT / "docs" / "verification-utm-smoke-2026-09-14.md"
BASIC_RECORD = PROJECT_ROOT / "docs" / "verification-utm-basic-pentesting-2-2026-09-14.md"
PACKAGING_DESIGN = PROJECT_ROOT / "docs" / "ctflab-task6-packaging-design.md"
ROOT_README = PROJECT_ROOT / "README.md"
STATUS_LABELS = ("已验证", "部分验证", "未验证", "后续任务")

# 交付目录（含两份脱敏 README）：默认按本机路径解析，可用环境变量覆盖；
# 目录不存在时相关测试跳过并在跳过原因中说明，不静默通过。
DELIVERY_ROOT = pathlib.Path(
    os.environ.get("CTFLAB_UTM_E2E_DIR", pathlib.Path.home() / "Downloads" / "ctflab-utm-e2e-20260914")
)
DELIVERY_PACKAGES = {"smoke": "CTFLab-Smoke-E2E-20260914", "basic": "CTFLab-BasicPentest2-E2E-20260914"}
LEGACY_STRUCTURE_LABEL = "complete-required-keys-pending-utm-e2e"
# 未加限定的否定标记：命中这些宣称短语的句子必须同时含否定/限定措辞，否则判失败。
NEGATION_MARKERS = ("不得", "不是", "不构成", "不支持", "尚未", "未通过", "不能", "禁止",
                    "未实现", "没有", "不做", "未开始", "不含", "不把", "不涉及", "未验证", "未做")


def delivery_readme(slug: str) -> pathlib.Path:
    return DELIVERY_ROOT / slug / "README.md"


def delivery_available() -> bool:
    return all(delivery_readme(slug).is_file() for slug in DELIVERY_PACKAGES)


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[。；\n]", text) if part.strip()]


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
        self.assertIn("重启后复测失败", items[0])
        self.assertIn("仅保证固定显示可用", items[0])

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
        # 不钉死细分数字（测试集会增长），但必须带复核日期与当前总数，陈旧计数不得残留
        self.assertIn("本次完整回归", self.text)
        self.assertIn("2026-09-15 复核", self.text)
        self.assertIn("331 项通过", self.text)
        self.assertIn("56 项验收状态与设计边界守卫测试", self.text)
        self.assertIn("82 项路径 A `utm-export` 单元测试", self.text)
        self.assertIn("37 项 Task 6.1 打包测试", self.text)
        self.assertIn("58 项 Task 6.2/6.3A/6.3B app 受控运行时、许可证与验收守卫测试", self.text)
        for stale in ("66 项通过", "当前完整回归", "174 项通过", "161 项通过", "202 项", "205 项", "235 项", "245 项", "280 项", "283 项", "286 项", "279 项", "278 项", "269 项", "267 项", "242 项", "243 项", "244 项", "48 项", "95 项", "293 项", "309 项", "312 项", "313 项", "43 项 Task 6.2"):
            self.assertNotIn(stale, self.text)

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

    def test_smoke_and_basic_delivery_section_is_honest(self) -> None:
        """Smoke/Basic 交付：两包、独立记录、ACPI 正常关机与隔离证据必须写明；
        交付定位、元数据范围状态与显示不稳定声明必须保留。"""
        flat = normalized(self.text)
        section = self.text[self.text.index("## 6. Smoke 与 Basic Pentesting 2 的 UTM 包交付"):]
        self.assertIn("已验证", section)
        self.assertIn("CTFLab-Smoke-E2E-20260914", section)
        self.assertIn("CTFLab-BasicPentest2-E2E-20260914", section)
        self.assertIn("未覆盖/未改动用户已有 UTM 虚拟机", section)
        self.assertIn("ACPI", section)
        self.assertIn("qemu-img check", section)
        self.assertIn("Network=[]", section)
        self.assertIn("e2e_scope=static-console-and-isolation", section)
        self.assertIn("e2e_status=passed-with-scope-limits", section)
        self.assertIn("dynamic_resolution=not-tested-for-x86-fixed-display", section)
        self.assertIn("sha256_at_export", section)
        self.assertIn("sha256_after_e2e", section)
        self.assertIn("不是**已接入 Kali 的联网靶场", section)
        self.assertIn("重启后复测失败，显示链路不稳定；当前包仅保证固定显示可用。", flat)
        self.assertNotIn("Smoke/Basic 交付待做", flat)
        self.assertNotIn("（第 8 步）未开始", flat)

    def test_no_full_path_a_or_dynamic_resolution_claim(self) -> None:
        """“静态控制台 E2E 通过”不得被写成“完整 Path A 通过”，也不得暗示动态分辨率或联网靶场。"""
        for stale in ("完整 Path A 通过", "Path A 完整验收通过", "完整 E2E 通过",
                      "动态分辨率已支持", "动态分辨率就绪", "联网靶场已验收"):
            self.assertNotIn(stale, self.text, f"验证记录不得出现：{stale}")


class PackageDeliveryRecordTests(unittest.TestCase):
    """Smoke/Basic 独立验证记录：范围收敛、哈希字段分离、默认无网卡，不得升级宣称。"""

    def records(self) -> list[tuple[str, str]]:
        return [(path.name, path.read_text(encoding="utf-8"))
                for path in (SMOKE_RECORD, BASIC_RECORD)]

    def test_scope_statuses_and_required_note(self) -> None:
        for name, text in self.records():
            flat = normalized(text)
            self.assertIn("e2e_scope: static-console-and-isolation", flat, name)
            self.assertIn("e2e_status: passed-with-scope-limits", flat, name)
            self.assertIn("dynamic_resolution: not-tested-for-x86-fixed-display", flat, name)
            self.assertIn("本清单记录离线导出结果；静态控制台 E2E 结果以独立验证记录为准。", flat, name)
            self.assertIn("但不构成动态分辨率或联网靶场验收。", flat, name)

    def test_disk_hash_fields_are_distinct(self) -> None:
        for name, text in self.records():
            flat = normalized(text)
            self.assertIn("utm_disk.sha256_at_export", flat, name)
            self.assertIn("utm_disk.sha256_after_e2e", flat, name)
            self.assertIn("不得混用", flat, name)
            self.assertNotIn("导出时磁盘 SHA-256", flat, f"{name} 仍使用旧字段名")
            self.assertNotIn("E2E 后磁盘 SHA-256", flat, f"{name} 仍使用旧字段名")

    def test_console_scope_wording_is_not_graphical_login(self) -> None:
        for name, text in self.records():
            self.assertIn("控制台登录界面，范围收敛", text, name)
            self.assertNotIn("图形登录通过", text, f"{name} 不得写成图形登录通过")

    @unittest.skipUnless(delivery_available(), f"交付目录不存在：{DELIVERY_ROOT}（设置 CTFLAB_UTM_E2E_DIR 可覆盖）")
    def test_delivery_readmes_keep_console_scope(self) -> None:
        for slug in DELIVERY_PACKAGES:
            text = delivery_readme(slug).read_text(encoding="utf-8")
            self.assertIn("控制台登录界面，范围收敛", text, slug)
            self.assertNotIn("图形登录通过", text, f"{slug} 不得写成图形登录通过")
            self.assertIn("不是**完整 Path A 验收", text, slug)

    def test_network_remains_default_no_nic(self) -> None:
        for name, text in self.records():
            flat = normalized(text)
            self.assertIn("Network=[]", flat, name)
            self.assertIn("默认无网卡", flat, name)
            for stale in ("联网靶场已验收", "已接入实验网"):
                self.assertNotIn(stale, flat, f"{name} 不得出现：{stale}")

    def test_structure_status_and_exported_label_are_explained(self) -> None:
        for name, text in self.records():
            flat = normalized(text)
            self.assertIn("complete-required-keys", flat, name)
            self.assertIn("旧 schema 迁移标签", flat, name)
            self.assertIn("仅标签迁移", flat, name)
            self.assertIn("fixture.structure_status", flat, name)


class DesignBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = DESIGN.read_text(encoding="utf-8")

    def test_header_status_blocks_claims(self) -> None:
        """锚定文档首段状态：必需段/键补齐、导入已通过、冷启动未做、路径 B 未实现。"""
        header = text_between(self.text, "# CTFLab 动态分辨率设计", "## 1.")
        self.assertIn("utm-export", header)
        self.assertIn("必需段与必需键", header)
        self.assertIn("首次导入（R1）因缺必需段失败", header)
        self.assertIn("通过“导入/解析”验收", header)
        self.assertIn("部分验证", header)
        self.assertIn("路径 B 未实现", header)
        self.assertIn("不得宣称", header)
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
        self.assertIn("本次新增的仅有路径 A 的 `utm-export`", flat)
        self.assertIn("`probe --matrix`", flat)
        self.assertNotIn("未新增任何 CLI", flat)
        self.assertNotIn("本次未新增动态分辨率相关 CLI", flat)

    def test_path_a_implementation_status_is_honest(self) -> None:
        """导入、冷启动、剪贴板负向、网络隔离、正常关机与 Smoke/Basic 交付均有记录；
        动态分辨率重启后复测失败必须保留，且显示稳定性声明必须逐字在案。"""
        flat = normalized(self.text)
        self.assertIn("complete-required-keys", flat)
        self.assertNotIn("complete-required-keys-pending-utm-e2e", flat)
        self.assertIn("[冷启动/图形登录通过；剪贴板负向与网络隔离通过；动态分辨率重启后复测失败；", flat)
        self.assertIn("来宾内正常关机通过；Smoke/Basic 已交付（x86_64 BIOS 变体，两包 E2E 通过并各有独立验证记录）]", flat)
        self.assertIn("两个变体均完成限定范围 UTM E2E", flat)
        self.assertNotIn("两个变体的真实 UTM E2E 均已完成", flat)
        self.assertIn("重启后复测失败，显示链路不稳定；当前包仅保证固定显示可用。", flat)
        self.assertIn("verification-utm-smoke-2026-09-14.md", flat)
        self.assertIn("verification-utm-basic-pentesting-2-2026-09-14.md", flat)
        self.assertIn("step4-postreboot-failure.json", flat)
        self.assertIn("import-accepted-R2.png", flat)
        self.assertIn("step2-evidence.json", flat)
        self.assertIn("E2E-FAILURE-2026-09-14.md", flat)

    def test_structure_and_runtime_status_are_separate(self) -> None:
        """结构状态只描述必需段/键；运行状态独立，旧 schema 迁移标签不得作为当前状态。"""
        flat = normalized(self.text)
        self.assertIn("结构状态与运行状态分离", flat)
        self.assertIn("runtime_status", flat)
        self.assertIn("e2e_scope", flat)
        self.assertIn("e2e_status", flat)
        self.assertIn("旧 schema 迁移标签仅用于 schema 2 兼容迁移", flat)
        for stale in ("complete-required-keys-pending-utm-e2e",):
            self.assertNotIn(stale, flat)

    def test_x86_64_bios_variant_is_documented(self) -> None:
        """x86_64 BIOS 变体必须写明其固定结构边界，且不得残留“只支持 aarch64”式表述。"""
        flat = normalized(self.text)
        self.assertIn("x86_64 + BIOS", flat)
        self.assertIn("VGA 固定显示", flat)
        self.assertIn("IDE 或 SCSI 磁盘", flat)
        for stale in ("非 aarch64 明确拒绝", "路径 A 首版只支持 aarch64"):
            self.assertNotIn(stale, flat)

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


class DeliveryClaimGuardTests(unittest.TestCase):
    """交付语义守卫：设计文档、验证记录与两份交付说明都不得出现未加限定的升级宣称。

    范围：把静态控制台 E2E 写成完整 Path A、把固定显示写成动态分辨率支持、
    把离线包写成已接入 Kali 的联网靶场、把旧 schema 迁移标签写成当前状态。
    """

    CLAIM_PHRASES = (
        "完整 Path A",
        "Path A 完整验收",
        "完整 E2E",
        "启动验收",
        "动态分辨率已支持",
        "支持动态分辨率",
        "动态分辨率就绪",
        "已接入 Kali",
        "联网靶场",
        "已接入实验网",
    )

    def scanned_docs(self) -> list[tuple[str, str]]:
        docs = [(path.name, path.read_text(encoding="utf-8"))
                for path in (DESIGN, VERIFICATION, SMOKE_RECORD, BASIC_RECORD, ROOT_README)]
        if delivery_available():
            docs += [(f"{slug}/README.md", delivery_readme(slug).read_text(encoding="utf-8"))
                     for slug in DELIVERY_PACKAGES]
        return docs

    def test_root_readme_carries_scoped_delivery_wording(self) -> None:
        """根 README 不得再把路径 A 写成“已实现并完成 UTM E2E”，必须按范围与限制表述。"""
        flat = normalized(ROOT_README.read_text(encoding="utf-8"))
        self.assertIn("静态控制台 E2E 已在限定范围内通过", flat)
        self.assertIn("动态分辨率仍不稳定", flat)
        self.assertIn("路径 B 未实现", flat)
        for stale in ("已实现并完成 UTM E2E", "完成 UTM E2E"):
            self.assertNotIn(stale, flat)

    def test_claim_phrases_are_always_negated_or_scoped(self) -> None:
        for label, text in self.scanned_docs():
            for phrase in self.CLAIM_PHRASES:
                for sentence in sentences(text):
                    if phrase in sentence and not any(m in sentence for m in NEGATION_MARKERS):
                        self.fail(f"{label} 出现未加限定的宣称“{phrase}”：{sentence[:90]}")

    @unittest.skipUnless(delivery_available(), f"交付目录不存在：{DELIVERY_ROOT}（设置 CTFLAB_UTM_E2E_DIR 可覆盖）")
    def test_scanned_docs_include_delivery_readmes(self) -> None:
        labels = [label for label, _ in self.scanned_docs()]
        for slug in DELIVERY_PACKAGES:
            self.assertIn(f"{slug}/README.md", labels)

    def test_legacy_label_is_only_a_migration_label(self) -> None:
        for label, text in self.scanned_docs():
            for sentence in sentences(text):
                if LEGACY_STRUCTURE_LABEL in sentence:
                    self.assertNotEqual(label, DESIGN.name,
                                        "设计文档不得再出现旧 schema 迁移标签字面量")
                    self.assertIn("旧 schema 迁移标签", sentence,
                                  f"{label} 中的旧标签必须标为“旧 schema 迁移标签”：{sentence[:90]}")

    def test_static_console_scope_is_stated_where_deliveries_are_described(self) -> None:
        boundary_phrases = ("not-tested-for-x86-fixed-display", "仅保证固定显示可用",
                            "动态分辨率仍不稳定", "固定显示")
        for label, text in self.scanned_docs():
            if "Smoke" not in text and "CTFLab-Smoke" not in text:
                continue
            flat = normalized(text)
            self.assertIn("静态控制台", flat, f"{label} 必须写明交付 E2E 的静态控制台范围")
            self.assertTrue(
                any(phrase in flat for phrase in boundary_phrases),
                f"{label} 必须写明固定显示/动态分辨率边界")


class DeliveryConsistencyTests(unittest.TestCase):
    """交付一致性：清单字段、SHA256SUMS 与 README 引用必须互相对得上。"""

    def package_dir(self, slug: str) -> pathlib.Path:
        return DELIVERY_ROOT / slug

    @unittest.skipUnless(delivery_available(), f"交付目录不存在：{DELIVERY_ROOT}（设置 CTFLAB_UTM_E2E_DIR 可覆盖）")
    def test_sha256sums_lists_current_package_and_at_export_is_historical(self) -> None:
        for slug, name in DELIVERY_PACKAGES.items():
            root = self.package_dir(slug)
            manifest = json.loads((root / f"{name}.utm.export.json").read_text(encoding="utf-8"))
            disk = manifest["utm_disk"]
            current = {}
            for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
                digest, path = line.split()
                current[path] = digest
            historical = {}
            for line in (root / "SHA256SUMS.at-export").read_text(encoding="utf-8").splitlines():
                digest, path = line.split()
                historical[path] = digest
            disk_path = f"{name}.utm/Data/data.qcow2"
            self.assertEqual(current[disk_path], disk["sha256_after_e2e"],
                             f"{slug}: 当前 SHA256SUMS 必须与 sha256_after_e2e 一致")
            self.assertEqual(historical[disk_path], disk["sha256_at_export"],
                             f"{slug}: SHA256SUMS.at-export 必须记录导出时哈希")
            self.assertNotEqual(current[disk_path], historical[disk_path],
                                f"{slug}: 两个哈希字段与实际盘不得混用")
            real = hashlib.sha256((root / disk_path).read_bytes()).hexdigest()
            self.assertEqual(real, disk["sha256_after_e2e"], f"{slug}: 磁盘现状必须等于 E2E 后哈希")

    @unittest.skipUnless(delivery_available(), f"交付目录不存在：{DELIVERY_ROOT}（设置 CTFLAB_UTM_E2E_DIR 可覆盖）")
    def test_manifests_do_not_output_legacy_label(self) -> None:
        """清单 JSON 不得再带旧 schema 迁移标签字面量（只允许“旧 schema 迁移标签”这一中性表述），
        迁移注释也不得把当前 fixture 哈希写成导出时的历史哈希。"""
        import ctflab_utm  # noqa: PLC0415
        for slug, name in DELIVERY_PACKAGES.items():
            path = self.package_dir(slug) / f"{name}.utm.export.json"
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(LEGACY_STRUCTURE_LABEL, text,
                             f"{slug}: 清单仍输出旧 schema 迁移标签字面量")
            manifest = json.loads(text)
            note = manifest["fixture"]["fixture_migration_note"]
            self.assertIn("旧 schema 迁移标签", note, slug)
            self.assertIn("sha256 0461a8b9", note, slug)
            self.assertNotIn(ctflab_utm.FIXTURE_SHA256[:8], note,
                             f"{slug}: 迁移注释把当前 fixture 哈希写成了导出时 v5 的哈希")

    @unittest.skipUnless(delivery_available(), f"交付目录不存在：{DELIVERY_ROOT}（设置 CTFLAB_UTM_E2E_DIR 可覆盖）")
    def test_readme_cites_the_same_hashes_as_manifest(self) -> None:
        for slug, name in DELIVERY_PACKAGES.items():
            root = self.package_dir(slug)
            manifest = json.loads((root / f"{name}.utm.export.json").read_text(encoding="utf-8"))
            readme = (root / "README.md").read_text(encoding="utf-8")
            self.assertIn(manifest["utm_disk"]["sha256_at_export"], readme, slug)
            self.assertIn(manifest["utm_disk"]["sha256_after_e2e"], readme, slug)
            self.assertIn("SHA256SUMS.at-export", readme, slug)
            self.assertIn("不能对 E2E 后可写盘执行校验", readme, slug)


class Task61PackagingDocsTests(unittest.TestCase):
    """Task 6.1 打包设计：范围与边界必须写清，且不得宣称未交付的能力。"""

    def setUp(self) -> None:
        self.text = PACKAGING_DESIGN.read_text(encoding="utf-8")

    def test_design_states_scope_limits(self) -> None:
        flat = normalized(self.text)
        self.assertIn("不包含", flat)
        self.assertIn("CTFLab.app", flat)
        self.assertIn("不含虚拟磁盘", flat)
        self.assertIn("不构成 Task 6", flat)
        self.assertIn("MIT", flat)
        self.assertIn("LICENSE", flat)
        self.assertIn("干净 Mac 用户验收脚本", flat)

    def test_design_does_not_claim_undelivered_capabilities(self) -> None:
        """提及未交付能力时句子必须带否定/限定措辞，不得出现正面宣称。"""
        for phrase in ("签名已完成", "公证已完成", "完整安装已验证", "已内置 QEMU 运行时",
                       "完整 Path A", "动态分辨率已支持"):
            for sentence in sentences(self.text):
                if phrase in sentence:
                    self.assertTrue(
                        any(marker in sentence for marker in NEGATION_MARKERS),
                        f"设计文档出现未加限定的宣称“{phrase}”：{sentence[:90]}")

    def test_design_keeps_dynamic_resolution_scope_untouched(self) -> None:
        flat = normalized(self.text)
        self.assertIn("不改变默认 QEMU 命令", flat)
        self.assertIn("run/stop/reset", flat)


class Task62AppRuntimeDocsTests(unittest.TestCase):
    """Task 6.2 设计/验证文档：范围与限制必须写清，不得宣称未交付能力。"""

    APP_DESIGN = PROJECT_ROOT / "docs" / "ctflab-task6-app-runtime-design.md"
    APP_RECORD = PROJECT_ROOT / "docs" / "verification-task6-2-2026-09-15.md"

    def test_design_states_license_closure(self) -> None:
        """设计文档描述当前设计：MIT + vendored 文本 + 书面要约必须写清。"""
        flat = normalized(self.APP_DESIGN.read_text(encoding="utf-8"))
        self.assertIn("MIT", flat)
        self.assertIn("LICENSE", flat)
        self.assertIn("vendored", flat)
        self.assertIn("SOURCE_OFFER.md", flat)
        self.assertIn("书面要约", flat)
        self.assertIn("dtc", flat)
        self.assertIn("未验证", flat, "公证状态必须继续如实标注为未验证")
        self.assertIn("公证", flat)

    def test_historical_record_keeps_period_limits(self) -> None:
        """6.2 验证记录是历史文件：当时的 undeclared/dtc/禁止公开发布事实不得被改写。"""
        flat = normalized(self.APP_RECORD.read_text(encoding="utf-8"))
        self.assertIn("未验证", flat, self.APP_RECORD.name)
        self.assertIn("undeclared", flat, self.APP_RECORD.name)
        self.assertIn("dtc", flat, self.APP_RECORD.name)
        self.assertIn("禁止公开发布", flat, self.APP_RECORD.name)

    def test_no_fake_signing_or_notarization_claims(self) -> None:
        for path in (self.APP_DESIGN, self.APP_RECORD):
            for sentence in sentences(path.read_text(encoding="utf-8")):
                if "公证" in sentence and "未" not in sentence and "不得" not in sentence:
                    self.fail(f"{path.name} 疑似声称已公证：{sentence[:90]}")
        flat = normalized(self.APP_RECORD.read_text(encoding="utf-8"))
        self.assertIn("ad-hoc", flat)
        self.assertNotIn("Developer ID 签名通过", flat)
        self.assertNotIn("公证通过", flat)


class Task63BLicensePythonDocsTests(unittest.TestCase):
    """Task 6.3B 记录：许可证闭环与内置 Python 运行时的证据与边界必须写清。"""

    RECORD = PROJECT_ROOT / "docs" / "verification-task6-3b-2026-09-15.md"

    def setUp(self) -> None:
        self.text = self.RECORD.read_text(encoding="utf-8")

    def test_record_documents_license_closure(self) -> None:
        flat = normalized(self.text)
        self.assertIn("MIT", flat)
        self.assertIn("vendored", flat)
        self.assertIn("SOURCE_OFFER.md", flat)
        self.assertIn("distribution_blockers", flat)
        self.assertIn("qemu-11.1.0.tar.xz", flat)
        self.assertIn("6ee1d1a61f68", flat)

    def test_record_documents_bundled_python_evidence(self) -> None:
        flat = normalized(self.text)
        self.assertIn("python-build-standalone", flat)
        self.assertIn("3.12.14", flat)
        self.assertIn("PyYAML", flat)
        self.assertIn("doctor-zero-setup", flat)
        self.assertIn("host-python-denied", flat)
        self.assertIn("no-bytecode-writes", flat)
        self.assertIn("15/15", flat)
        self.assertIn("__pycache__", flat)

    def test_record_documents_kali_e2e_evidence(self) -> None:
        flat = normalized(self.text)
        self.assertIn("29/29", flat)
        self.assertIn("guest-connectivity", flat)
        self.assertIn("login_ready", flat)
        self.assertIn("qemu-img-check", flat)

    def test_record_keeps_undelivered_limits(self) -> None:
        flat = normalized(self.text)
        self.assertIn("未做", flat)
        self.assertIn("公证", flat)
        self.assertIn("基盘镜像分发", flat)
        self.assertIn("未执行", flat)
        for stale in ("公证通过", "Developer ID 签名通过"):
            self.assertNotIn(stale, flat)


class Task63AKaliAcceptanceDocsTests(unittest.TestCase):
    """Task 6.3A 记录：缺陷与修复、范围限制、未交付项必须写清。"""

    RECORD = PROJECT_ROOT / "docs" / "verification-task6-3a-2026-09-15.md"

    def setUp(self) -> None:
        self.text = self.RECORD.read_text(encoding="utf-8")

    def test_record_documents_defect_and_fix(self) -> None:
        flat = normalized(self.text)
        self.assertIn("com.apple.security.hypervisor", flat)
        self.assertIn("HV_NO_DEVICE", flat)
        self.assertIn("entitlements", flat)
        self.assertIn("已验证", flat)
        self.assertIn("qemu-img check", flat)
        self.assertIn("login_ready", flat)
        self.assertIn("GRUB", flat)
        self.assertIn("29/29", flat)
        self.assertIn("键和值", flat)
        self.assertIn("final-screen-initial.png", flat)
        self.assertIn("final-screen-reboot.png", flat)

    def test_record_keeps_signing_and_distribution_limits(self) -> None:
        flat = normalized(self.text)
        self.assertIn("ad-hoc", flat)
        self.assertIn("未做", flat)
        self.assertIn("公证", flat)
        self.assertIn("禁止公开发布", flat)
        for stale in ("Developer ID 签名通过", "公证通过"):
            self.assertNotIn(stale, flat)
        for sentence in sentences(self.text):
            if "已签名分发" in sentence:
                self.assertTrue(any(marker in sentence for marker in NEGATION_MARKERS),
                                f"疑似声称已签名分发：{sentence[:80]}")

    def test_record_keeps_runtime_provenance_evidence(self) -> None:
        flat = normalized(self.text)
        self.assertIn("bundled", flat)
        self.assertIn("sandbox-exec", flat)
        self.assertIn("/opt/homebrew", flat)
        self.assertTrue("CTFLAB_RUNTIME_ROOT" in flat or "runtime" in flat)
        self.assertIn("runtime/bin/qemu-system-aarch64", flat)


if __name__ == "__main__":
    unittest.main()
