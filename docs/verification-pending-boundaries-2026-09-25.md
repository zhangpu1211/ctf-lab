# 2026-09-25 待验收边界专项：剪贴板 E2E、未授权客户端、TCP 回退路径 B、全屏与拖拽

> 历史验收快照：结论、测试数与产物路径只对应本记录日期及被测候选，不替代当前软件状态；部分本机旧产物已清理。当前使用、分发与未验证边界见[当前状态](ctflab-current-status.md)。原有失败和范围限制保留，文档整理不补做或升级验收。

本轮目标：收口 `docs/verification-display-network-2026-09-16.md` 与
`docs/ctflab-dynamic-resolution-design.md` 遗留的待验收项。除特别说明外，
全部验证在本机（单显示器 Apple Silicon Mac，macOS 26）完成；跨 Mac 接收端
需要第二台 Mac，本轮无法本地验收。

## 结论速览

| 项目 | 结论 |
| --- | --- |
| `--clipboard` 关闭通道负向（双向哨兵） | **已验证**：宿主→来宾英文/中文/多行哨兵均不泄漏；来宾→宿主写入后宿主剪贴板逐字节不变 |
| `--clipboard` 开启正向（双向三哨兵） | **已验证**（含本轮新增的宿主→来宾修复，见下）；英文/中文/多行双向逐字节一致 |
| 未授权客户端连接拒绝（TCP 模式） | **已验证**：无 ticket / 错误 ticket 的客户端被 QEMU 拒绝（`reds_handle_ticket: Invalid password`），不建立任何通道 |
| 未授权客户端连接拒绝（unix 模式） | **部分验证**：0700 目录权限与无 TCP 监听已核对；跨用户连接拒绝未实测 |
| TCP 回退模式（路径 B） | **部分验证（2026-10-05 更正）**：URI/password 顺序已修复；历史 3/3 报告未被本次完整来宾验收复现。认证脚本已修正判据，当前独立验证为无来宾磁盘的真实 QEMU ticket 握手三轮，见新增记录 |
| SPICE 全屏 | **部分验证**：`--fullscreen` 启动与 Shift+F11 切换已实现，全屏几何（覆盖整屏、置顶）实测达成；全屏尺寸的动态分辨率跟随未通过（根因未证实，见下） |
| 长时间连续拖拽 | **待验收**：宿主→来宾鼠标绝对坐标映射多次实测有效；持续拖拽专项被桌面输入冲突打断，未完成 |
| 多显示器 | **未验证**：本机为单显示器（内建 Retina），无法构造多显示器场景 |
| 跨 Mac 接收端 | **未验证**：需要第二台 Mac，本轮无法本地验收 |
| x86 外来镜像向导（CLI 链路） | **部分验证**：命令链曾跑通；旧 probe 截图实际为 PXE，不能证明从磁盘启动 |

## 1. 剪贴板负向 E2E（未授权剪贴板）——已验证

前置：`run kali-arm64`（未传 `--clipboard`）。QEMU 命令行确认含
`disable-copy-paste=on,disable-agent-file-xfer=on`；客户端未带 `--clipboard`。

- 宿主→来宾：宿主分别写入英文、中文、多行哨兵（`pbcopy`），来宾侧
  `DISPLAY=:0 xclip -selection clipboard -o` 三次均返回
  `Error: target STRING not available`（来宾剪贴板无任何内容）。
- 来宾→宿主：来宾写入混合中文哨兵，宿主 `pbpaste` 哈希前后一致（写入前后
  `c85d0764f388cef6` == `c85d0764f388cef6`）。

## 2. 剪贴板正向 E2E——已验证（含本轮新增修复）

### 2.1 发现的缺陷：quartz 后端宿主→来宾方向失效

- **来宾→宿主方向**：来宾 `xclip -i` 写入哨兵后数秒内自动出现在宿主
  NSPasteboard，英文/中文内容逐字节一致（GRAB 推送路径，无需焦点）。
- **宿主→来宾方向**：无论窗口是否聚焦、是否重新聚焦，来宾剪贴板始终收不到
  宿主内容。定位：spice-gtk 的该方向依赖 GTK clipboard 的 `owner-change`
  信号，而 **quartz 后端在外部应用更新 NSPasteboard 时不会发出该信号**
  （上游已知限制；quickemu 文档同样标注 macOS 上 SPICE 剪贴板不可用）。

### 2.2 修复：客户端通道级实现（tools/spice_client/ctflab_spicy.c）

- macOS 下（`__APPLE__` 编译分支）完全旁路 SpiceGtkSession 的
  auto-clipboard（`auto-clipboard` 置 FALSE），由客户端在 main channel 上
  自行实现双向：
  - 宿主→来宾：独立线程每秒轮询 `pbpaste`（**必须离开 GTK 主循环**——
    pasteboard 持有"来宾数据承诺"时 pbpaste 会同步阻塞，在主循环内执行会
    冻结事件处理并造成承诺超时）；连续两轮读到相同内容（防抖）且与最近一次
    来宾写入不同（防回声）时，发送 `clipboard_selection_grab` +
    `clipboard_selection_notify`（UTF8_TEXT）；来宾侧 X11 请求到达时经
    `main-clipboard-selection-request` 信号用缓存文本应答。
  - 来宾→宿主：`main-clipboard-selection-grab` 信号到达后请求 UTF8_TEXT，
    `main-clipboard-selection` 信号携带数据时直接写 `pbcopy` 并登记为
    "最近来宾写入"，轮询线程据此抑制回推回声。
- Linux 构建不编译此分支（X11 owner-change 正常，行为不变）。
- 状态证据行：`clipboard-h2g bytes=N` / `clipboard-g2h bytes=N` /
  `clipboard-request-answered bytes=N`。

### 2.3 实测结果（修复后客户端，tcp/unix 均验证）

- H2G：英文 `H2G PASS`、中文 `H2G PASS`、多行 `H2G PASS`（base64 逐字节一致；
  首轮记录中的"MISMATCH"为宿主侧管道尾换行假象，base64 复核一致）。
- G2H：英文/中文/多行三哨兵 `G2H PASS`（base64 一致）；G2H 之后轮询线程无
  回推（日志无多余 h2g 行），回声抑制生效。
- 开关语义不变：未传 `--clipboard` 时轮询线程不启动，通道在 QEMU 层
  `disable-copy-paste=on`。

**交付边界（历史与当前分开）**：本节为 2026-09-25 的验证记录。2026-10-05
客户端生命周期已重构，并生成本地候选 App；新的双向桌面剪贴板仍待验收，
公开 Release 尚未更新，见 `docs/verification-client-lifecycle-2026-10-05.md`。

## 3. 未授权客户端连接拒绝——已验证（负向矩阵）

### 3.1 TCP 回退模式（ticket 鉴权）

- 无 ticket 客户端：连接后 spice-gtk 收到鉴权要求，无法取得任何通道
  （`agent=0`、`display-ready=0`），无显示内容。
- 错误 ticket 客户端：QEMU 日志 `reds_handle_ticket: Invalid password`，
  无任何通道建立（`agent=0`、`display-ready=0`）。
- 正确 ticket 客户端：认证通过（连接后无新增 `Invalid password` 行）。

### 3.2 UNIX socket 模式（默认路径）

- 鉴权边界 = UNIX socket + 0700 runtime 目录（设计文档定义一致）：
  `runtime/<id>/spice/` 为 `drwx------`，跨用户进程按内核语义无法遍历目录
  触达 socket。
- **未真实演示跨用户进程连接**（创建第二用户进程需要 root/sudo，本轮环境
  不可用）；以权限位 + 内核语义 + 正向连接成功作为边界证据，如实记录。
- 非鉴权（disable-ticketing=on）unix socket 允许同用户第二客户端建立协议
  连接（spice 多客户端语义）；这是同用户进程，不在"未授权"范围。

### 3.3 无多余监听

`lsof -iTCP -sTCP:LISTEN`：SPICE 在 unix 模式下无任何 TCP 监听；TCP 模式下
仅 `127.0.0.1:<受控端口>`（另一监听 127.0.0.1:12210 为 Kali SSH hostfwd，
与本功能无关）。

## 4. TCP 回退模式（路径 B）——部分验证（历史报告待新脚本复测）

### 4.1 已交付

- 运行器：`run --spice-listen {unix,tcp}`（默认 unix）。tcp 模式：
  - `-spice addr=127.0.0.1,port=<受控端口>,disable-ticketing=off,...,password-secret=ctflab_spice_ticket`
    — 不含 `0.0.0.0`，不出现裸 `-spice`；
  - ticket 经 `-object secret,id=ctflab_spice_ticket,file=<0600 文件>,format=raw`
    注入，**不出现在命令行参数与运行状态明文**（单元测试断言）；
  - 端点等待、状态字段（`spice_endpoint=spice://127.0.0.1:<port>`、
    `spice_listen=tcp`）。
- 客户端：`--password-file PATH`（读取 0600 ticket 文件、去行尾换行、
  `session.password` 注入后即清零内存）。
- 单元测试（`tools/tests/test_ctflab_status_docs.py::SpiceDisplayCliTests`）：
  tcp 命令形状/无 0.0.0.0/ticket 不在参数与 0600 文件、unix 默认不变且无
  `port=`、tcp 需要 spice 显示、客户端命令携带 `--password-file`、
  非受控客户端拒绝 tcp。

### 4.2 E2E 结果（第二轮开发报告，非本次独立复测）

2026-10-05 发现原认证探针的超时/EOF 成功判据及 capability 位错误；原 ESTABLISHED
判断也只证明传输层。以下 3/3 是历史开发报告，不能替代修正后的显示通道 ready +
明确认证应答验收。新脚本只使用独立状态目录，不再执行用户状态的 stop --all。

- 隔离/负向：**通过**（见 §3.1 与 §4.1 断言；错误/无 ticket 拒绝已进入
  自动化 E2E 断言）。
- 正向连接：**已稳定通过（3/3 轮）**。第一轮记录的"非确定失败"实为确定性
  失败，根因在客户端：
  **spice-gtk 的 `session:uri` setter 会清空此前设置的 `password` 属性
  （实测 `g_object_get` 读回 NULL）**，客户端先设 password 后设 uri，导致
  TCP ticket 认证始终以空口令发送，服务器 `strcmp` 失败报
  `Invalid password`；unix 主路径 `disable-ticketing=on` 不走认证，因此
  完全不受影响。第一轮"最小化复现通过"的记录无效——判定条件只统计
  Invalid password 行数、未确认通道建立，3 秒即被终止的客户端根本没有
  产出认证结果。
- 修复：客户端改为 **uri 先于 password 设置**（`ctflab_spicy.c`，附注释说明
  该 spice-gtk 行为），并以源码顺序断言钉进单元测试。
- 可重复 E2E：`tools/tests/test_ctflab_spice_tcp_e2e.py`（环境门控，默认
  跳过；`CTFLAB_SPICE_TCP_E2E=1` + app 路径启用）。现场按可复现构建命令
  编译受控客户端，3 轮 runner 全流程断言：通道建立（ESTABLISHED>0）、
  零新增 Invalid password、ticket 不进命令行/状态 JSON/日志、仅绑
  127.0.0.1、错误 ticket 原始链路探针得到 PERMISSION_DENIED(7)。
  2026-09-25 实测 3/3 通过（55s）。

## 5. SPICE 全屏——部分验证

- 新增 `--fullscreen` 启动参数与 Shift+F11 切换（GTK3 key snooper 在事件
  进入 SpiceDisplay 前拦截，组合键不向来宾转发裸 F11）。
- quartz 后端 `gtk_window_fullscreen` 不可靠（状态位不翻转），因此全屏以
  **无边框 + 全屏尺寸（1512x982）+ 置顶**等效实现，实测窗口几何
  `0,0 1512x982 layer=1` 覆盖整屏。
- **动态分辨率跟随在全屏尺寸下未通过**：已观察到的现象——客户端已发送
  `resize-target logical=1512x982 scale=2 physical=3024x1964`，来宾
  EDID/模式表没有出现对应模式（停留 1280x800），强制 DRM re-detect 亦无效。
  疑似与 QEMU virtio-gpu 运行中 EDID 刷新行为有关，**根因未证实**（未做
  QEMU/来宾侧专项定位），不应据此断定责任边界。普通窗口尺寸的跟随
  （2000x1400@boot）已验证（2026-09-16 与本轮）。
- 交互切换（Shift+F11）的端到端验收被桌面输入冲突打断（见 §6）。

## 6. 长时间连续拖拽——待验收

- 宿主→来宾绝对坐标鼠标映射多次实测有效（宿主 move → 来宾
  `xdotool getmouselocation` 跟随变化）。
- 持续拖拽专项需要独占桌面输入；本轮验证期间使用者正在使用该 Mac，合成
  输入与用户操作互相干扰（输入焦点多次被宿主侧其他应用夺走），未能完成。
  按设计文档回归要求，不以不完整的事件注入记录冒充验收。

## 7. 多显示器——未验证

本机为单内建显示器（Liquid Retina XDR 3024x1964），无法构造多显示器场景。
`gdk_display_get_primary_monitor` 几何逻辑已按单显示器实现。

## 8. 跨 Mac 接收端——未验证

需要第二台 Mac 构造接收端，本轮无法本地验收。

## 9. x86 外来镜像向导——命令链部分验证

对真实外来镜像 `WebServer.ova`（4.75GB OVA/VMDK，GPT，20GB 虚拟盘）在隔离
状态目录完成：

- `inspect --json`：识别 vmdk/GPT/LSI Logic/E1000；候选
  `x86_64 + uefi + scsi(lsi53c895a) + e1000`；逐字段置信度
  （arch=low、firmware=medium、disk=high、network=high）；两条诚实警告
  （架构不可判定需人工确认；未做冷启动验证不构成可用性结论）。
- `onboard --id webserver-e2e`：生成候选配置与派生基盘
  （`base-ee30335cfcd9.qcow2`，不覆盖原始 OVA），退出码 0。
- `probe webserver-e2e --timeout 420`：冷启动探测（结果见 §9.1）。

### 9.1 probe 结果——旧报告误判，已修正

旧报告输出 network_and_display_candidate、非黑画面与 DHCP 地址；此前复核
截图实际为 TianoCore 的「Start PXE over IPv4」。DHCP 可能来自固件网络启动，
这些证据不能证明磁盘引导。原始报告不改写，以保留错误判定的来龙去脉。

2026-10-05 当前实现对 PXE 返回 pxe_network_boot；矩阵对未知画面也不再仅凭
DHCP + 显示活动命中。完整 probe 调用链与矩阵回退已进入自动化测试。WebServer
真实磁盘引导和 GUI 向导仍需重新验收。

## 10. 回归记录

此前记录中的 379/380 项是历史执行范围；本次测试与执行结果统一见
[2026-10-05 验证记录](verification-client-lifecycle-2026-10-05.md)。完整 Kali
E2E 的环境门控跳过不能记为通过。

## 10.1 第二轮修订（2026-09-25，历史实现）

以下退出方案已被 2026-10-05 的可取消子进程 + 固定主线程 timer 方案取代；
历史源码契约检查不能替代本次 C 运行测试。

- 剪贴板轮询线程退出流程修复：`request_client_quit`（窗口关闭/QEMU 退出/
  SPICE 断开共用）先置 shutdown 并摘除待执行推送，主循环结束后以 GCond
  有界等待线程退出（不使用 join；线程仍阻塞在 pbpaste 时放弃等待并有意
  保留静态缓存），确认退出后才释放缓存与互斥锁/条件变量；未启用
  `--clipboard` 时不初始化、不清理剪贴板状态。另修复推送在 agent 未就绪时
  触发 GLib 断言的问题（能力检查 + 未就绪时不消费、下一轮重试）。
- `probe` PXE 判定修复：新增 `pxe_network_boot` 画面分类（含 WebServer.ova
  真实退化 OCR 样本 `>>Start PXE over [Pu4` 回归）；PXE 画面即使 QEMU 在
  运行、非黑且 DHCP 正常，也不再产生可被启动矩阵接受的
  `network_and_display_candidate` 磁盘启动候选，矩阵按失败类立即换下一个
  候选；报告新增 `recommendations` 并在输出中提示检查固件、磁盘总线与
  启动顺序。"候选需人工确认"边界不变。
- 全屏 EDID 表述修正：仅记录观察现象，根因未证实（见 §5）。

## 11. 本轮行为变化清单

- `tools/spice_client/ctflab_spicy.c`：
  - macOS 剪贴板通道级双向实现（`--clipboard` 时启用；Linux 不变）；
  - `--fullscreen` 启动与 Shift+F11 切换（quartz 等效全屏）；
  - `--password-file`（TCP 回退模式 ticket 注入）；
  - 显示死锁解锁：agent 已连接而 display 未就绪时按当前窗口尺寸主动发送
    monitors config（来宾 blank/DPMS 后 virtio-gpu 管线恢复）。
- `tools/ctflab.py`：`run --spice-listen {unix,tcp}`、ticket 文件（0600）、
  端点等待与状态字段、`spice_client_command` 支持 TCP URI 与
  `--password-file`。
- 第二轮修订（生命周期与候选纠错，见 §10.1）：客户端退出生命周期、PXE 判定、
  TCP 正向修复（password 设置顺序）与可重复 E2E。
- 未改动：默认 `run` 命令语义、stop/reset 语义、PCAP、健康检查、unix 主路径。

## 12. 仍保留的边界

- 跨用户进程连接 unix socket 的真实演示（需 root）；
- TCP 完整 Kali 图形链路需用本次客户端与修正后的验收脚本重测（URI/password
  设置顺序缺陷已修复，但当前独立证据仅覆盖协议握手）；
- 全屏尺寸动态分辨率跟随（已观察到来宾 EDID 未出现对应模式；疑似 virtio-gpu
  运行中 EDID 刷新行为，根因未证实）；
- 长时间连续拖拽专项、多显示器专项、跨 Mac 接收端；
- `.app` 内置客户端为旧版，上述客户端修复随下次发布重打包生效；
- Developer ID 签名/公证与真实网盘链路（发布边界，按约定本轮不动）。
