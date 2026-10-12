# app-r4 最终使用与四镜像配套验收（2026-10-12）

> 历史验收快照；不替代当前软件状态。区分本轮实际执行、通过、失败与未验证项。

## 任务与授权

用户指定三项：① app-r4 最终使用验收（Kali 登录后实际使用）② 与四镜像分发基盘的配套验收 ③ 本地交付 ZIP 整理。只做三项，不扩展功能、不发布。**三项全部完成**；用户确认桌面空闲并亲自完成 Kali 登录与交互。

## 开始前结构验收（本轮实测，不沿用旧证据）

- `app verify` 通过：743 登记文件、QEMU 11.1.0、内置 Python 3.12.15/PyYAML 6.0.3、许可证完整、ad-hoc（`final-acceptance/app-verify.log`）。
- 包内 `ctflab.py`/`ctflab_dist.py`/`ctflab_network.py`/`ctflab_inspect.py` 与工作区源码 `cmp` 逐字节一致。
- 旁车：树摘要 `bdba17328b527e…`、MANIFEST `95897de7269a…` 与构建器算法复核一致；spicy `4f158923…`。
- 运行时配套对照 app-final：QEMU 三件 + spicy SAME；70 dylib 名称一致、65 个字节相同、5 个为 glib 2.88.3 家族（溯源 `dylib-provenance-trace.json`；SBOM 归属说明见任务3 节末）。

## 任务2：四镜像配套验收（本轮完成）

镜像库现场识别（非历史路径）：`02-已处理/`（DISTRIBUTION.json：kali-arm64 base+nvram、smoke、basic-pentesting-2）与 `02-已处理/Acfun-20261011/`（DISTRIBUTION.json：acfun base；另有随包 `acfun.yaml`，App 内置同 id 配置）。

**导入**（全部经 app-r4 包内 CLI、`final-state`、真转换；来源哈希全部与清单一致）：
- smoke `7620acabaf1b…`、basic-pentesting-2 `f3fe2a8a4345…`、acfun `df612f71f372…`、kali-arm64 `974a319f5961…` + NVRAM `8639a3fb43dd…`。

**串行 probe**（headless 真启动 + QMP 截图；绑定与证据 `final-acceptance/final-task2-bindings.json`）：

| 节点 | 结论 | 画面 | DHCP | 协议证据 | 停止 |
|---|---|---|---|---|---|
| smoke | service_ready | 非全黑（boot_progress） | 192.168.242.20 | SSH `SSH-2.0-OpenSSH_10.0`（12220 就绪检查） | ✅ 无残留 |
| basic-pentesting-2 | 登录画面就绪 + 服务 | 登录界面（OCR） | 192.168.242.21 | HTTP 200（158B 维护页，:18080）；SSH `OpenSSH_7.2p2 Ubuntu`（:12221） | ✅ 无残留 |
| acfun | network_and_display_candidate | **tty1 登录提示符，画面内自报 Hostname: Acfun / IP 192.168.242.32** | 192.168.242.32 | SSH 按配置需实验网内源 → 与任务1 配对完成（见下） | ✅ 无残留 |
| kali-arm64 | = 任务1（登录使用验收） | — | — | — | 任务1 执行 |

probe 截图/报告在 `final-state/logs/probes/`；每节点 probe 后确认无 QEMU 残留。

## 任务1：Kali 登录后实际使用（本轮完成，用户确认空闲并亲自操作）

独立状态 `final-state`；SPICE 显示（app-r4 包内 CTFLabDisplay.app，spicy=glib 2.88.3 闭包）。

| 步骤 | 实际结果 | 证据 |
|---|---|---|
| SPICE 冷启动 | 登录界面完整渲染（lightdm + KALI 壁纸，时钟 21:58）；health 三项 OK（PID 4013 / DHCP 192.168.242.10 / SSH `10.3p1`） | `task1-01-login-screen.png`、`task1-kali-start.log` |
| 用户登录与交互 | 用户手动登录；键盘与中英文输入（截图含误输入 `shello` 完整回显）、鼠标点击/窗口切换/滚动、宿主窗口缩放、终端 `uname -a && whoami` → `Kali 6.19.14+kali-arm64` | `task1-02-desktop-terminal.png`（终端全文可见） |
| 配对连通 | 本轮独立 Kali → 本轮独立 Acfun（同回环实验网）：`nc -w5 192.168.242.32 22` 返回 `SSH-2.0-OpenSSH_10.0`（同截图终端内） | 同上 |
| 关窗重连 | 显示客户端退出后 QEMU PID 4013 保持运行；`show --reconnect` 新客户端 PID 4544、`reconnected: true`；恢复画面仍是原登录会话（终端历史与 banner 原样，时钟 22:04）；无第二实例 | `task1-reconnect.log`、`task1-03-reconnected.png` |
| 正常关机 | ACPI 触发 Kali "Log out Kali User" 确认框 → 按协议保留现场（`task1-04-shutdown-state.png` QMP 截图）→ 恢复显示由用户点击 Shut Down → QEMU 自然退出 → `stop` 清理状态；配对 acfun 正常停止 | `task1-stop-kali.log`、`task1-stop-acfun.log` |
| 子进程核验 | QEMU/spicy/ctflab-network 全部退出归零；`status`：无运行实例 | 本节记录 |

## 任务3：交付 ZIP（本轮完成）

交付目录 `/Users/pufei/Downloads/ctflab-final-delivery-20261012/`：

| 项 | 值 |
|---|---|
| ZIP | `CTFLab-0.1.1-contentpack-final-20261012-local.zip`（52,975,929 bytes） |
| ZIP SHA-256 | `5aaa76d35b5d799c2a5671e9b8549f7b7ef4b4a806d6fc86a8af58f14e97e8f0` |
| 内容 | CTFLab.app（743 文件）+ `使用说明.md` + `验收摘要.md` + `CTFLab.app.sha256`（树摘要 `bdba17328b527e…` + MANIFEST `95897de7269a…`） |
| 解压复验 | 新目录解压：`app verify` 通过；包内源码与工作区逐字节一致；旁车 MANIFEST 行 `shasum -c` OK；QEMU/SPICE/licenses 齐备；包内启动器 `status --json` 只读检查正常（临时状态目录） |
| 污染检查 | 实测前后树摘要均 `bdba17328b527e…` 无变化；无新增 `__pycache__`（runtime/python 内 1 处为构建上游原样，app-r4 构建源相同）；临时状态目录在包外 |

**SBOM 归属说明**：app-r4 的 licenses 目录为 5 个 formula（qemu/edk2/python/pyyaml/spice-gtk）——因配套暂存根布局，70 个 dylib 在 SBOM 中统一归属 `qemu` formula 的 GPL 文本；逐库真实来源（glib 2.88.3 家族等）以 `dylib-provenance-trace.json` 为准。许可证文本完整、分发义务有文本支撑，归属粒度如实记录于此。

## 边界与未验证项

### 独立交付核对追加（同日）

独立计算 ZIP SHA-256 与上表完全一致；ZIP CRC 检查通过，829 个目录/文件条目逐项与交付目录比较，文件及符号链接内容无差异。交付 App 的 app verify 通过，树摘要仍为 bdba17328b527e3093c238793ed07c589fc52ddf2893631ba4ac975e4d03748e。实际查看 task1-03-reconnected.png 确认登录后的终端、uname/whoami 和 Acfun SSH banner；现场未发现 QEMU/CTFLabGUI/spicy 进程。本次没有重做桌面操作或来宾启动，区分证据复核与实机重跑。

SBOM 说明需要精确化：实际包内 libgio/libglib 等条目归属 spice-gtk、版本 0.42_3，并非全部 70 库归属 qemu；这同样不是这些库的真实组件名称/版本。5 个许可证目录存在及 app verify 通过只证明当前登记要求的文件完整，不能据此证明全部第三方归属和分发义务已正确核实。保留此问题为正式分发前的 SBOM/许可证整理项，不影响本轮本地功能验收结论；发布前按真实组件补准确映射及对应文本，再重签与重新校验。

- 未验证：真实外接显示器、Mac 睡眠恢复、长时闲置（>30 分钟）与持续负载、Kali 认证登录后的课程内容与解题、跨 Mac 迁移、Developer ID 公证。
- 剪贴板/文件共享默认关闭（本轮全程未开启）；未接入物理 LAN。
- 分支 `codex/release-0.1.1-preview-20261010`、HEAD `42a3aa71…` 不变；全部改动未提交（61 项），无推送/发布；镜像库 03-软件未替换。
- 来源资产前后哈希一致（`assets-pre-hashes.txt` = `assets-post-hashes.txt`）。
- 最终完整回归 683 项 = **673 通过 + 10 条件跳过**（第 13 节，本轮无源码变更未重跑；跳过不计入通过）。
- 本轮状态目录 `final-state`（含四节点登记与派生盘，均已停止）、`spice-state`（上轮 SPICE 验收，已停止）；证据根 `ctflab-contentpack-fix-20261012/final-acceptance`；收口现场核验进程 0。
