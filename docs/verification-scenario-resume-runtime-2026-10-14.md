# 重置接续链、生产运行时与场景 CLI/GUI 入口合成验证（2026-10-14）

> 历史验收快照；不替代当前软件状态。以后继续须现场核对路径、指针、日志、登记、锁与实际进程身份。

正式项目：`/Users/pufei/Downloads/ctf-lab`；分支 `codex/release-0.1.1-preview-20261010`；HEAD `941db31`。保留已有改动，没有提交、推送、打包或发布。

## 本轮实现

- 接续链：`ctflab_scenario_reset.resume_reset_resources` 覆盖 reset-ready 接续与"指针已切换但服务未启动"重接；`recover_reset_continuation` 显式释放接续孤儿预约；`_commit_binding` 仅在旧准备记录可证明未激活时原子替换；registry 拆出 `_release_locked` 锁内核。
- 服务会话新增活动指针门槛：指针存在时必须指向本准备记录，孤儿记录不能绕过激活启动。
- `ctflab_scenario_runtime`：只读 ps 身份采集（`-ww`、单/双行输出、包装脚本前缀、僵尸 `<defunct>`、`(进程名)` 瞬时退化重读）、`child_identity` 稳定窗、QMP 查询/ACPI 关机、节点观察器/关机请求器、`stopped_observer` 停止证明（指针切换后按代次准备记录自洽校验）、`stop_recovered_nodes`/`stop_recovered_services` 接管停止（锁内、意图先写日志、不重复发送、超时 stop-pending、`stopping` 可重试）。
- CLI `scenario` 子命令组：prepare/status/start/stop/reset/recover；独立状态根（随全局 `--state-dir`）与 `/tmp/ctflab-sc-<uid>` socket 根；`ScenarioError` 统一转为 CLI 错误。
- GUI（GuiCore/GuiApp）：`ScenarioReport` 解码、诚实状态概括（待恢复/仍存活/已停止/未初始化）、确认后请求正常停止、收口/释放孤儿入口；`swiftc -typecheck` 通过。

## 验证入口与结果

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools:tools/tests python3 -m unittest \
  test_ctflab_scenario_cli test_ctflab_scenario_runtime test_ctflab_scenario_continuation \
  test_ctflab_scenario_nodes_reset test_ctflab_scenario_resources test_ctflab_scenario_services \
  test_ctflab_scenario_dhcp test_ctflab_network test_ctflab_scenario test_ctflab_network_report -q
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests -p '*doc*' -q
git diff --check
swiftc gui/GuiCore.swift gui/GuiCoreTests.swift -o /tmp/guicore-tests && /tmp/guicore-tests
swiftc -typecheck gui/GuiCore.swift gui/GuiApp.swift
```

| 入口 | 结果（2026-10-14） |
|---|---|
| 场景相关 10 个测试模块 | 115 项，连续 3 轮全部通过（CLI 5 项多次重跑稳定） |
| 完整本地回归 | 790 项通过，跳过 10 项（既有保留项），无真实 VM 启动 |
| GUI 核心检查 | 217 项检查全部通过（含本轮 13 项场景用例） |
| GUI 类型检查 | `swiftc -typecheck` 通过 |
| 文档守卫 / diff 检查 | 见收口补记 |
| 语法检查 | 12 个相关 Python 文件 `ast.parse` 通过，无字节码生成 |

## 合成证据要点

| 路径 | 证据 |
|---|---|
| 接续链 | reset-ready→新代次预约/指针切换→服务/节点全链；旧代次资产保留；重复接续拒绝；未收口事务阻断；孤儿预约显式释放后重试；指针切换失败/预约失败/资产哈希失败/锁竞争/来宾写入不误判；已激活未启动现场重接 |
| 生产身份 | ps 单/双行解析、lstart 绑定（PID 复用识别）、命令行后缀匹配（包装脚本）、僵尸按 absent、`(进程名)` 瞬时退化重读后仍失配判 unknown、稳定窗失败关闭 |
| QMP | 假 socket 握手/查询/关机协议；连接拒绝/坏问候/错误响应失败关闭 |
| 停止证明 | 无日志按停止、日志畸形整侧 unknown、QMP 可达不冒充停止、指针已切时代次记录自洽校验 |
| 接管停止 | 排序节点锁、意图先写日志、不重复发送、超时 stop-pending 保留现场、`stopping` 重试、预约失效拒绝、锁释放核验 |
| CLI 端到端 | 真实 main() 全链：prepare（合成基盘/固件 + 注入 qemu-img/路由）→ start（真实 DHCP 服务子进程继承测试自身 FD + 合成 qemu 桩真实子进程 + 真实 ps/QMP 身份链）→ status（nodes-observed）→ 重复 start 拒绝 → stop（ACPI 关机后桩退出 + SIGTERM 停服务）→ reset 门槛与跨代次 start/stop/reset 闭环 → recover 报告 |
| 桌面边界 | GUI 场景面板仅状态/确认停止/显式恢复；准备/启动/重置走 CLI；单机 profile 命名空间与场景状态根无交集 |

## 故障修复过程（本轮真实发生）

首轮 CLI 端到端发现并修复：资产路径被哈希覆盖、socket 路径超 104 字节（生产默认根因此改到 /tmp）、首次准备被重置收口门槛误拦、`#!/usr/bin/env` 二次 exec 导致 ps 身份漂移（`child_identity` 增加稳定窗）、macOS 退出窗口 ps 退化输出 `(进程名)`（`build_inspect` 有界重读）、僵尸进程被当身份变化、接管后 `stopping` 状态无法重试（开放重试并按日志去重请求）、旧代次释放时指针已切换导致停止证明失败（按代次准备记录自洽校验）、reset-ready 代次无 sockets 绑定时 QMP 检查崩溃。

## 实际限制

- `scenario prepare/start` 生产路径只在合成资产 + 合成 qemu 桩上运行过；没有真实 Wintermute 基盘、真实来宾、真实双网隔离抓包或题目验收。真实 VM 启停需新授权（方案见设计第 9 节）。
- 进程身份依赖 `ps` 只读采集，存在信号发送前后的固有 TOCTOU 窗口（身份在发送前一刻核验）；这是单用户教学边界，不抵御同 UID 恶意进程。
- 停止证明核对"已记录进程不存在 + QMP 不可达"，不能排除未记录的外部进程；GUI 面板不提供准备/启动/重置。
- 完整回归通过不代表发布包更新：本地 0.1.2 工作区与外部 0.1.1-preview 均未重新打包，App 版本未复核。无本轮后台实例；测试子进程均由测试清理或 `cleanup_children` 兜底终止，临时目录/FD 自行清理，未查询或操作用户既有实例。
