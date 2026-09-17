# CTFLab 图形入口验证记录（2026-09-16）

结论只使用四类状态标签：**已验证** / **部分验证** / **未验证** / **后续任务**。
本记录区分“实际点击验证”与“仅单元测试”，不把 CLI 测试冒充 GUI E2E。

## 1. 交付内容

| 交付物 | 位置 | 状态 |
|---|---|---|
| 原生图形入口源码 | `gui/GuiCore.swift`（状态机/命令构造）、`gui/GuiApp.swift`（SwiftUI）、`gui/GuiCoreTests.swift`（无 XCTest 的核心测试） | 已验证 |
| `.app` 主入口 | `Contents/MacOS/CTFLabGUI`（`CFBundleExecutable`）；CLI 启动器保留在 `Contents/Resources/bin/{ctflab-cli,CTFLab}` | 已验证 |
| 构建/校验集成 | `tools/ctflab_app.py`（`swiftc` 编译、启动器位置、`MANIFEST.gui`、`signature_covers`、`app verify` 检查） | 已验证 |
| CLI 机器可读输出 | `dist verify --json`、`status --json`、`health --json` 与 `inspect --json`（GUI 的机器可读数据来源） | 已验证 |
| 单元测试 | `tools/tests/test_ctflab_gui.py`（21 项：Swift 核心断言 + CLI JSON 契约 + 构建集成 + 文档守卫） | 已验证 |
| 最终测试构建产物 | `/Users/pufei/Downloads/ctflab-app-build-macos15-auto-final2-20260916/CTFLab.app`（当时按 macOS 15.0 兼容目标构建的 QEMU/SPICE，ad-hoc 签名，797 个登记文件；仅为历史验证证据，当前产品最低要求已提升至 macOS 26.0） | 已验证 |

本次 GUI 验证未覆盖既有旧产物：`/Users/pufei/Downloads/ctflab-app-build-20260916/CTFLab.app` 与旧分发目录
`/Users/pufei/Downloads/ctflab-dist-20260916/`；二者已由后续清理移除，验证截图与 JSON 证据保留。

## 2. 实际点击验证（GUI E2E，截图见 `~/Downloads/ctflab-gui-verify-20260916/`）

环境：`open -a` 双击等价启动；隔离实例用 `open -na … --env CTFLAB_GUI_STATE_DIR=/tmp/ctflab-gui-state`
（测试钩子，避免写入学生真实状态目录；默认双击启动的实例只做了只读的状态/校验操作）。

| 步骤 | 结果 | 证据 |
|---|---|---|
| 打开 App（状态恢复到默认状态目录） | 窗口显示“请选择并校验分发目录”；节点表将历史基础镜像标为“本机已登记”，不把它表述为当前分发目录已导入 | `01-launched.png`（历史截图中的旧文案已被后续 UI 修正） |
| 选择分发目录（含空格路径的对话框操作：`⌘⇧G` + 路径） | 显示所选绝对路径；校验按钮启用，导入/启动/停止/重置禁用 | `03-open-panel.png`、`04-dir-selected.png` |
| 校验分发目录（真实 10GB 校验） | 表格逐文件显示大小（1.43GB/8.1GB/67.1MB/267.6MB）与“通过” | `05-verified.png` |
| 错误目录被拒绝 | 选 `/tmp/ctflab-empty-dist`：横幅显示“未找到分发清单 …/DISTRIBUTION.json”、退出码 1、可复制；导入/启动保持禁用 | `06-wrong-dir-rejected.png` |
| **导入实验环境可调用并真实完成** | 三次 `import <profile> <基盘> --manifest DISTRIBUTION.json` 全部完成（App 内 `qemu-img convert` 解压分发基盘到隔离状态目录，约 22GB）；节点表全部“已导入=是”，启动按钮启用 | `08-importing.png`、`10-imported.png` |
| **选择并启动所选节点** | 单选菜单不默认选择；一次只启动一个明确选中的已导入节点。CLI 自动给 Kali user-mode NAT + Cocoa 固定显示，给靶机 restrict + Cocoa；SPICE 仅由显式参数请求 | GUI 源码/Swift 核心测试（本轮 UI 语义未重新做点击 E2E） |
| **检查状态（健康）** | 三个节点均显示 PID、“健康=通过”与日志路径 | `12-health-checked.png` |
| 停止所选节点 | 仅停止当前选择的实例；`stop --all` 保留为 CLI 故障恢复命令 | 本轮 GUI 单元/编译测试（UI 语义未重新做点击 E2E） |
| 重置（确认框 + 取消 + 确认） | 确认框逐字提示“overlay 中的实验改动（安装的软件、产生的文件、被攻击后的状态）会全部丢失”；取消后 overlay 保留；确认后三节点 overlay 被删除、基盘保留 | `14-reset-confirm.png`、`15-reset-done.png` |
| 失败可见性（实机缺陷复现） | 早期版本漏传 `import` 的位置参数，GUI 原样显示 CLI 用法错误、退出码与可复制文本（该缺陷已修复并加契约测试） | `08-importing.png`（同一路径的失败态截图已覆盖） |

## 3. 仅单元测试覆盖（未逐项点击）

- 状态机门禁组合（未校验/校验失败/执行中/未全部导入/运行中）与按钮启用状态：Swift 核心 58 条断言；
- 命令拼接：`--manifest` 基盘位置参数、路径含空格、单节点选择、Kali 默认联网/Cocoa 固定显示与显式 `--display spice`、
  逐节点 `stop`、逐节点 `reset`；
- JSON 解析：分发报告（含缺失/大小不符/哈希不符三类失败）、状态报告、健康报告；字段名契约由
  Python 测试锁定（`dist verify --json`、`status --json`、`health --json`）；
- 构建集成：真实 `gui/` 源码经 `swiftc` 编译进 app、`Info.plist` 主入口、`MANIFEST.gui`、
  主可执行文件由代码签名覆盖、缺 GUI 入口/缺 `MANIFEST.gui` 时 `verify_app` 拒绝；
- 重置门禁：未确认时 `ResetGate` 不产生任何 reset 命令。
- **x86_64 接入向导（仅单元/编译验证）**：向导依次调用 `inspect --json`、用户确认后的
  `onboard --architecture x86_64`、`probe` 与用户显式请求的 `probe --matrix`；候选 profile 排他写入
  `~/Library/Application Support/CTFLab/profiles/`，内置 profile 与 App 不可覆盖。矩阵命中不自动写回配置。

## 4. 未验证 / 后续任务

- **未验证**：Developer ID 签名与公证后的首次打开体验（当前 ad-hoc，学生首次打开仍需在
  “系统设置 → 隐私与安全性”手动放行一次，与既有文档一致）；GUI 在浅色/深色之外的辅助功能
  （VoiceOver）未测试；GUI 未做“记住上次分发目录”的持久化（每次启动需重新选择，属体验项）；
  新 x86_64 向导尚未用任意真实外来镜像完成 GUI 点击、冷启动、重启、DHCP/服务验证，不能据此宣称
  “任意 x86_64 镜像已适配”。
- **后续任务**：把 GUI 的导入/启动流程接入课程分发自动化（例如一键脚本），以及
  `CTFLab.app` 的签名/公证流水线。

## 5. 回归与边界

- `python3 -m unittest discover -s tools/tests`：当前全量 **366 项**（361 项实际执行通过，5 项历史 UTM 目录缺失跳过）；GUI 定向测试与 Swift 核心测试均通过；
- `swiftc` 构建检查：`GuiCore.swift + GuiCoreTests.swift` 编译并运行 80 条检查全部通过；
  `GuiCore.swift + GuiApp.swift` 以 `-parse-as-library` 编译通过（app 构建即真实编译）；
- `python3 -m py_compile tools/ctflab.py tools/ctflab_app.py tools/ctflab_dist.py` 通过；
- 图形界面遵守既有边界：原始镜像只读 + overlay 运行、回环隔离实验网；Kali 默认通过 user-mode NAT
  联网并使用 Cocoa 固定显示，Smoke/Basic 始终使用 restrict + Cocoa；SPICE 动态分辨率只可显式请求；
  不把口令写入命令行/日志/JSON、不把磁盘与日志加入 Git；
- 本轮未提交、未推送；未修改既有最终 App 与分发目录。
