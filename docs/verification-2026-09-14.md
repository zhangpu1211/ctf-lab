# CTFLab 三节点网络、生命周期、干净环境与启动回退矩阵验证（2026-09-14）

本轮按优先级完成四项：三节点网络实测、20 次生命周期压力、干净用户环境验证、
受控启动回退矩阵（实现 + 单元测试 + 未知镜像实测）。不涉及跨平台、攻击功能或靶场网络范围的扩展。

本文所有结论只使用四类状态标签，不允许跨类宣称：

- **已验证**：有可复核的实测证据；
- **部分验证**：核心路径有证据，但仍有明确边界未覆盖，不得当作已完成；
- **未验证**：没有证据；
- **后续任务**：依赖尚未交付的组件（如 Task 6 打包），当前不宣称完成。

## 0. 状态总览

| 状态 | 本轮对应内容 |
|---|---|
| 已验证 | Kali→靶机 ICMP/全端口 Nmap/HTTP 200/SSH 横幅、靶机无公网、Mac 端口映射、20 次生命周期压力、启动回退矩阵机制与候选命中事件、本次完整回归（2026-09-15 复核，245 项） |
| 部分验证 | 干净环境（Task 6.1 源码级安装包已交付，但 PyYAML 仍需联网安装；导入/运行通过）、矩阵命中的候选配置（需人工复核截图后才能升级）、靶机→Kali 仅帧级双向、路径 A `utm-export`（R2 已通过 UTM 4.7.5 导入/解析、冷启动与 Kali 图形登录、剪贴板负向、网络隔离、来宾内正常关机；动态分辨率重启后复测失败，显示链路不稳定；Smoke 与 Basic Pentesting 2 两包已交付并通过 E2E，见第 6 节与两份独立验证记录） |
| 未验证 | 靶机应用级主动回连 Kali、干净环境无手工依赖的完整安装 |
| 后续任务 | `.app`/受控 QEMU 运行时、签名/公证与零手工依赖安装（Task 6.2）、应用级回连所需的靶机内执行流程（Task 4 剩余项） |

## 1. 三节点网络实测（Kali→靶机与服务：已验证；靶机→Kali：部分验证）

`./tools/ctflab run kali-arm64 smoke basic-pentesting-2 --pcap` 启动三个节点，
健康检查全部就绪（Kali DHCP+SSH、smoke DHCP+SSH、basic DHCP+HTTP 200）。
以下实测在 Kali 内执行（同时把结果跑在 Kali 图形终端里截图存档，截图留在状态目录不入库）。

| 检查 | 结果 | 状态 |
|---|---|---|
| Kali→smoke ICMP | 10 包 0% 丢包，RTT 均值 15ms | 已验证 |
| Kali→basic ICMP | 10 包 0% 丢包，RTT 均值 6.3ms | 已验证 |
| Kali→smoke 全端口 nmap | open：21/ftp、22/ssh、80/http（58402 closed + 7130 filtered，TCG 限速导致） | 已验证 |
| Kali→basic 全端口 nmap | open：22/ssh、80/http、139/445/smb、8009/ajp、8080/http-proxy | 已验证 |
| basic HTTP | 200，Apache/2.4.18 | 已验证 |
| smoke/basic SSH | OpenSSH 10.0 / 7.2p2-ubuntu2.4 横幅可达 | 已验证 |
| 靶机→Kali 帧级双向 | PCAP 中靶机→Kali 帧 124,103 条（ICMP 回复/TCP 响应含源 MAC） | 部分验证：只有帧级双向证据 |
| 靶机→Kali 应用级主动回连 | FTP 匿名 530 被拒；没有可免凭据的应用级回连通道 | 未验证：需要靶机内执行权限/凭据，未做 |
| 靶机无公网 | 管理网卡 `restrict=on`、交换机仅监听 127.0.0.1 且无上游、DHCP 不下发网关、28.8 万帧无实验网外 IP | 已验证 |
| Mac→basic Web 端口映射 | `127.0.0.1:18080` HTTP 200；三个 SSH 端口映射横幅均可访问 | 已验证 |

PCAP 保留：`~/Library/Application Support/CTFLab/pcap/lab-23400-20260914T010127Z.pcap`（288,036 帧，21MB，含双向帧与源 MAC）。

## 2. 20 次生命周期压力测试（已验证）

连续 20 次 `run kali-arm64 --headless → health（等 DHCP）→ stop → reset`：

- 20/20 轮 run/stop/reset 退出码全部为 0，DHCP 每轮均在超时内获取；
- 每轮检查：无 QEMU 残留进程、无 qmp.sock、无 network-\*.json、无 overlay 残留；
- 基础镜像 SHA-256 前后一致：`ca1034606…`（与登记值相同，未变化）；
- `locks/operations.lock` 存在但未被持有（状态目录可正常获取操作锁），实验网状态清零。

顺带修复：`stop --all --graceful` 原来在第一个不响应 ACPI 的实例处中断，导致其余实例未处理；
现改为逐个处理，超时的实例保留并统一在完成后报告（新增测试覆盖）。

## 3. 干净用户环境验证（部分验证：源码级安装包已交付；仍需联网补齐依赖）

模拟新 HOME + 最小 PATH（无 conda、无项目开发依赖）：

- 系统 Python 3.9：doctor 可运行；缺 PyYAML 时 import 立即给出安装指引（
  `python3 -m pip install pyyaml`）；
- venv（python3.14，**手工**按文档安装 PyYAML 6.0.3）后完整跑通：
  `doctor（全部 OK）→ import smoke → run --headless → status → health（DHCP+SSH 就绪）→ stop → reset`；
- reset 后状态目录无残留（无 overlay/qmp/网络状态），导入的基础镜像保留，无残留进程。

以上证明的是“依赖缺失时提示正确、手工补齐依赖后全流程可用”。Task 6.1 已补充源码级安装包与
干净环境验收脚本，但验收中的 PyYAML 仍需联网 `pip install`，**不构成**“零手工依赖的完整安装”
或签名分发验收；`.app`、受控运行时、签名与公证属于 Task 6.2，尚未验证。因此实施计划第 7 节的
对应验收项保持未通过（见 `docs/verification-task6-1-2026-09-15.md`）。

顺带修复：doctor 对必选依赖缺失时错误地显示“可选”文案，改为逐项安装提示；
`utmctl` 并非运行必需（仅 UTM 适配流程使用），从必选改为可选（新增测试覆盖）。
注意：smoke/basic 的原始源镜像路径已不在本机，干净环境验证改用已导入的基础镜像作为导入源，流程等价。

## 4. 受控启动回退矩阵（实现与单元测试：已验证；候选命中事件：部分验证）

实现（`tools/ctflab.py`）：

- `probe --matrix`：按白名单顺序尝试固件/磁盘组合
  （BIOS×IDE/SATA/SCSI/VirtIO → UEFI×IDE/SATA/SCSI/VirtIO；SCSI=lsi53c895a、SATA=ich9-ahci；
  aarch64 只允许 UEFI+VirtIO），每个候选的超时独立（`--matrix-timeout`，默认 90s）；
- 候选参数只作用于本次启动（运行状态记录 `boot_override` 审计字段），不写 profile；
- `probe` 轮询中实时对截图 OCR 分类，识别到 UEFI Shell/无启动盘/内核错误立即放弃当前候选，
  命中登录画面或协议/DHCP 就绪即停止（记录 `early_failure` 与矩阵 JSON 报告）；
- 附带支持 x86_64 UEFI 启动：OVMF pflash 代码 + 独立可写 NVRAM（`uefi-vars-x86_64.fd`），
  不影响 aarch64 既有路径与 `finalize-install --from-runtime`；
- 常用参数还有 `--matrix-max`（限制候选数）与 `--matrix-start`（跳过前 N 个候选，用于验证回退路径与定位）。

单元测试（`tools/tests/test_ctflab_boot_matrix.py`，10 项）：
矩阵白名单组合全部通过 profile 校验且覆盖 8 种组合、aarch64 单候选、
首个可启动候选即停止、全部失败时报告 8 个候选、启动错误续试、
不改写磁盘 profile、`--matrix-max`/`--matrix-start` 限制生效、x86 UEFI 命令含 OVMF pflash。

未知镜像实测（`WebServer.ova`，4.75GB，x86_64 候选，onboard 候选为 uefi/scsi）：

- 完整矩阵：**bios/scsi/lsi53c895a 首个候选即命中登录画面**（说明该镜像实际是 BIOS+SCSI，
  矩阵修正了 onboard 对 UEFI 的猜测），矩阵停止，报告 `login_ready/medium`；
- `--matrix-start 2` 演示失败续试：bios/ide 未达登录（boot_progress）→ 自动继续 →
  **bios/sata/ich9-ahci 命中登录画面**，矩阵停止并给出“请人工查看截图后再修改 profile”提示；
- 矩阵报告写入 `logs/probes/webserver-matrix-*.json`，候选参数未写入
  `tools/ctflab_profiles/webserver.yaml`（该候选 profile 当前保留在工作区，未提交）。

状态判定：矩阵机制本身（回退、早停、报告、不改写 profile）**已验证**；
“WebServer.ova 可在 CTFLab 中稳定使用”仍属**部分验证**——候选命中只提供截图证据，
必须人工复核登录/服务后才能按已验证交付（这是设计上的候选/交付区分，不是缺陷）。

## 5. 回归与边界

- `python3 -m unittest discover -s tools/tests`：本次完整回归 245 项通过（2026-09-15 复核；66 项既有回归——
  含 10 项矩阵测试、优雅停止聚合测试、doctor 提示测试与 Ghidra/文档命令测试——加 51 项验收状态与设计边界守卫测试、
  82 项路径 A `utm-export` 单元测试（含 x86_64 BIOS 变体、fixture 与旧标签守卫）、9 项导入完整性回归测试、
  37 项 Task 6.1 打包测试）。
- 路径 A（`utm-export`）：关键启动与显示字段以本机 UTM 4.7.5 现有包为只读参考、脱敏后作为
  哈希固定的 golden fixture（`tools/ctflab_utm_fixture.json`，哈希登记在 `tools/ctflab_utm.py`，
  完整键集合未对齐）；
  实现基盘 `base_sha256` 与 UEFI NVRAM `uefi_vars_sha256` 登记核对、RAW NVRAM → QCOW2
  `Data/efi_vars.fd` 转换（各自 `qemu-img info`/`check`）、排他发布（macOS `RENAME_EXCL`；
  临时 `.utm` 目录、失败清理、既有文件不动）与无绝对路径的导出清单；
  重复导入只在 `qemu-img compare -s` 证明宾客可见内容一致时补登记，未验证的既有基盘一律拒绝。
- 路径 A 首次真实 UTM E2E（2026-09-14）：R1 包 `CTFLab-Kali-E2E-20260914` 通过 23 项离线检查后
  被 UTM 4.7.5 以“配置无效”拒绝（缺 `Input`/`Serial`/`Sound` 等必需段/键，上游源码使用必需
  `decode`；失败证据 `~/Downloads/ctflab-utm-e2e-20260914/E2E-FAILURE-2026-09-14.md`）。
  按上游 v4.7.5 源码补齐全部必需段与必需键（fixture v4）后导出 R2 `CTFLab-Kali-E2E-20260914-R2`：
  离线 21 项结构检查（顶层 12 段精确、各段必需键集精确、Network/Serial/Sound=[]、
  DirectoryShareMode=None、ClipboardSharing=false、AdditionalArguments=[]、两盘 qcow2 且
  `qemu-img check` 通过、清单无绝对路径）全部通过；UTM 成功导入/解析（侧栏出现该 VM，
  aarch64/virt、5GB、状态“已停止”，未启动；截图 `import-accepted-R2.png`，包仍位于独立测试
  目录、未复制进 UTM 库）。
- 路径 A 冷启动与图形登录（2026-09-14，R2）：UTM 启动 R2 → lightdm 图形登录界面 → kali 用户
  登录 → XFCE 桌面出现且菜单可交互；QEMU 参数确认 `-nic none`（无网卡）、使用 R2 包内
  `Data/data.qcow2` 与 `Data/efi_vars.fd`、`virt + hvf`、4 核/5120MiB。证据：
  `~/Downloads/ctflab-utm-e2e-20260914/step2-boot-01.png`、`step2-boot-03-desktop.png`、
  `step2-utm-status.png`、`step2-evidence.json`。
- 路径 A 动态分辨率初测（同日会话内，R2）：窗口 1280×840 → 来宾 `xrandr` 1280x800；
  1000×660 → 1000x620；800×640 → 800x600；1416×900 → 1416x860（现场观察）。为真实模式切换，
  非缩放；证据 `step4-size-*.png`。来宾内 agent transport 存在（`/dev/virtio-ports/
  com.redhat.spice.0`、`org.qemu.guest_agent.0`；`spice-vdagent`/`spice-vdagentd` 运行）。
  限制：尺寸切换有延迟；过渡期短暂黑屏；快速连续缩放两次导致 UTM 显示端卡死
  （`step4-display-stall-black.png`）。
- 路径 A 剪贴板负向（同日第二轮会话，R2）：ClipboardSharing=false 且 agent transport 在场
  （`spice-vdagentd`、`/dev/virtio-ports/com.redhat.spice.0`）条件下，用 xclip/pbpaste 做双向
  交叉读取：英文（GUEST-EN-2026 vs HOST-EN-2026）、中文（来宾中文-2026 vs 主机中文-2026）、
  多行（GUEST-L1/2/3 vs HOST-L1/2/3）三种文本均未被对侧读取；宿主剪贴板测试前备份、测试后
  恢复（SHA-256 一致）。证据：`step5-EN-cross-read.png`、`step5-ZH-cross-read.png`、
  `step5-ML-cross-read.png`。
- 路径 A 网络隔离（同日第二轮会话）：来宾仅 `lo`（127.0.0.1/8、::1/128）、无任何路由；对
  1.1.1.1、192.168.242.1、192.168.64.1 的 ping 均返回 `Network is unreachable`；宿主侧该 VM
  进程无互联网套接字、无 TCP 监听，仅 spice unix socket，进程参数为 `-nic none`。
  证据：`step6-network-full.png`、`step6-host-sockets.txt`。
- **路径 A 动态分辨率重启后复测失败**：窗口 1288×845→1000×660 后来宾未跟随（仍 1288x805），
  随后 UTM 显示卡死为全黑、键盘输入中断；再次尝试 1100×720 仍复现，第二次恢复未成功。
  对照：重启前曾在三档尺寸下验证跟随（`step4-size-*.png`）。失败记录：
  `~/Downloads/ctflab-utm-e2e-20260914/step4-postreboot-failure.json`。路径 A 保持“部分验证”。
- **卡死恢复与来宾内正常关机（第 3 步：通过）**：宿主两次自动锁屏后按用户约束只操作 R2
  恢复：保留现场证据 → `utmctl` 不可用（Apple Events -1743，外部包不可见）→ UTM 单 VM “电源”
  菜单先发 ACPI 关机请求（来宾卡在不可见的关机确认框未完成）→ 核实进程属于 R2 后执行单 VM
  强制关机 → 重新打开 R2 并校验 config.plist/磁盘/NVRAM 与操作前一致 → 显示恢复 → 登录桌面 →
  来宾内 `sudo poweroff` 正常关机，QEMU 5 秒内退出、无残留进程，两盘 `qemu-img check` 均 ok，
  原 CTFLab 基盘/NVRAM 哈希未变；全程未重启 UTM、未影响运行中的 Linux VM。
  证据：`~/Downloads/ctflab-utm-e2e-20260914/wedge-scene/`（final-integrity.txt、
  final-stopped-main-window.png、r2-process-identity.txt、after-force-stop-integrity.txt）。
- **Smoke/Basic 的 UTM 包与交付文档（第 8 步）：已交付**（第三轮会话，见第 6 节）；动态分辨率
  维持“重启后复测失败，显示链路不稳定”的结论。
- 未提交虚拟磁盘、日志、截图或凭据；E2E 目录中的来宾口令文件（本轮未新增）保留在仓库外，不入库。
- 本轮状态汇总（与第 0 节一致）：
  - 已验证：三节点网络（Kali→靶机与服务）、靶机无公网、Mac 端口映射、20 次生命周期、
    启动回退矩阵机制与候选命中事件、本次完整回归（2026-09-15 复核，245 项）；
  - 部分验证：干净环境（手工安装依赖后可运行）、矩阵命中的候选配置、靶机→Kali 仅帧级双向、
    路径 A `utm-export`（R2 已通过导入/解析、冷启动/图形登录、剪贴板负向、网络隔离与来宾内正常关机；
    动态分辨率重启后复测失败；Smoke/Basic 两包已交付并通过 E2E，见第 6 节）；
  - 未验证：靶机应用级主动回连 Kali、干净环境无手工依赖的完整安装；
  - 后续任务：`.app`/受控 QEMU 运行时、签名/公证与零手工依赖安装（Task 6.2）、应用级回连所需的靶机内执行流程（Task 4 剩余项）。

## 6. Smoke 与 Basic Pentesting 2 的 UTM 包交付（2026-09-14 第三轮，已验证）

按第 8 步要求，为 `x86_64` + BIOS profile 新增 `utm-export` 变体支持并交付两个包；
两包各自独立输出目录、唯一命名，未覆盖/未改动用户已有 UTM 虚拟机（`Smoke.utm`、`Basic
Pentesting 2.utm`、`Linux.utm` 目录内容与时间戳未变化；未重启 UTM，未操作运行中的 Linux VM）。

| 项 | CTFLab-Smoke-E2E-20260914 | CTFLab-BasicPentest2-E2E-20260914 |
|---|---|---|
| profile / 变体 | `smoke` / x86_64-bios（SCSI, 2 vCPU, 4096 MiB） | `basic-pentesting-2` / x86_64-bios（IDE, 1 vCPU, 1024 MiB） |
| 基盘哈希（登记值一致） | `f0da1da7…` | `87bb1dc7…` |
| `utm_disk.sha256_at_export` | `e49a2cc3…`（导出时历史记录，见 `SHA256SUMS.at-export`） | `169eae77…`（导出时历史记录，见 `SHA256SUMS.at-export`） |
| `utm_disk.sha256_after_e2e` | `e8ef6f1d…`（与当前 `SHA256SUMS` 一致） | `54629336…`（与当前 `SHA256SUMS` 一致） |
| 导入/解析（UTM 4.7.5） | 通过（状态“已停止”，x86_64） | 通过（状态“已停止”，x86_64） |
| 冷启动 → 登录界面 | Alpine Linux `Smoke login:`；`IP :` 为空（无网卡） | Ubuntu 16.04.4 `basic2 login:`（含镜像已知 90 秒磁盘等待） |
| 基本交互（控制台回显） | 通过 | 通过（`basic2 login: bas` → `Password:`） |
| 正常关机（ACPI） | 通过：UTM“请求关闭电源”，缩略图含 OpenRC 关机序列 | 通过：ACPI 后 QEMU 正常退出，来宾 ext4 `s_state` 干净卸载 |
| 磁盘完整性 | `qemu-img check` ok；ext4 干净 | `qemu-img check` ok；ext4 干净 |
| NVRAM | 不适用（BIOS 无 NVRAM） | 不适用（BIOS 无 NVRAM） |
| 隔离核对 | `Network=[]`、`-nic none`、无共享目录、`ClipboardSharing=false` | 同左 |
| 显示 | 固定显示（`DynamicResolution=false`），不涉动态分辨率 | 同左 |

交付物（每包）：`.utm` 包、`SHA256SUMS`（当前包校验，与 `sha256_after_e2e` 一致）
+ `SHA256SUMS.at-export`（仅导出时历史记录，不能对 E2E 后可写盘执行校验）、脱敏 `README.md`、
独立验证记录（`docs/verification-utm-smoke-2026-09-14.md`、
`docs/verification-utm-basic-pentesting-2-2026-09-14.md`）；包与截图保留在
`~/Downloads/ctflab-utm-e2e-20260914/{smoke,basic}/`，不入库。

交付元数据（2026-09-15 修正，两包一致）：清单 schema 3，离线导出字段保持导出时原值；
磁盘哈希分列 `sha256_at_export` 与 `sha256_after_e2e`（包内盘可写，来宾启动/关机会改哈希，不得混用）；
`fixture.structure_status=complete-required-keys` 只描述必需段/必需键，与运行验收状态分离
（`complete-required-keys-pending-utm-e2e` 是旧 schema 迁移标签，不再作为当前 fixture 或当前状态输出）；运行状态
`e2e_scope=static-console-and-isolation`、`e2e_status=passed-with-scope-limits`、
`dynamic_resolution=not-tested-for-x86-fixed-display`。清单说明（逐字）：本清单记录离线导出结果；
静态控制台 E2E 结果以独立验证记录为准。该包已验证导入、冷启动、控制台交互、正常关机和无网卡隔离，
但不构成动态分辨率或联网靶场验收。两包的交付定位是“可在 UTM 4.7.5 中导入与启动的离线控制台镜像包”，
**不是**已接入 Kali 的联网靶场；也不得据此宣称完整路径 A 验收或动态分辨率支持。
显示稳定性声明对全部导出包一致：**重启后复测失败，显示链路不稳定；当前包仅保证固定显示可用。**
