# CTFLab for Mac M

> 2026-10-30：**0.1.4-preview.20261030** 已发布Mac可执行预览，新增原生分栏与整体界面更新，并纳入近期共享源码。Windows同步提供最新版构建源码，**不是EXE安装器**；原生环境/安装验收仍缺。见[本轮说明](docs/ctflab-ui-release-2026-10-30.md)与[当前状态第139节](docs/ctflab-current-status.md)。旧版保留，43项/G0/G1未整体完成。

2026-10-25 最新工作区增量：[桌面远程租约管理](docs/ctflab-desktop-leases-2026-10-25.md)补齐明确申请/续期/释放、服务器owner与期限门、停止策略额外确认和原标识手动重试；未知不自动重发，可显式保存不含连接配置的原请求。范围见[本轮验证](docs/verification-desktop-leases-2026-10-25.md)，剩余见[状态第93节](docs/ctflab-current-status.md)。前轮[远程目标](docs/ctflab-desktop-remote-2026-10-25.md)与[未决只读核验](docs/ctflab-audit-review-2026-10-25.md)保留；只有替身/代码检查，未连接真实SSH、操作用户VM、运行到期调度或覆盖旧包，集中实机验收尚未开始。

2026-10-24 工作区候选：[通用场景 QEMU 后端与 Windows 恢复验收](docs/ctflab-production-driver-2026-10-24.md)已提供实际启动路径与独立退出观测；Windows 原生、来宾网络和显示验收仍待执行，未更新发布 App。

> 2026-10-23 最新工作区入口：[本地可实施部分交付](docs/ctflab-offline-delivery-2026-10-23.md)。新增通用代次存储/协调基础、离线拓扑与网络检查计划、C05合成应急课程及Windows回传摘要工具；Windows真实查询/关机闭环已有回传，但G0/G1未完成。下方日期化记录保留历史范围，不能作为最新完整状态。跨平台离线入口：`python -B tools/ctflab_offline.py --help`；它不是Windows VM运行器或安装包。

CTFLab 是面向 Apple Silicon Mac 的本地虚拟靶场运行器。它使用 QEMU 管理 ARM64 与 x86_64 客体，以不可变 QCOW2 基盘和可重置 overlay 保存运行状态，并通过仅绑定回环地址的用户态二层交换机连接 Kali 与靶机。

当前仓库只包含运行器、候选配置、来宾修复模板、测试和设计文档，不包含虚拟磁盘、账号凭据、课程题库或成绩数据。

> 2026-10-28 Mac预览更新：**0.1.3-preview.20261028** 面向 Apple Silicon、macOS 26+，ad-hoc、未公证。本轮包含稳定性保护、通用架构拓扑、配置撤销/重做及差异导出；实际交付与验证见[当前状态第114节](docs/ctflab-current-status.md)和[本轮说明](docs/ctflab-stability-topology-2026-10-28.md)。旧包保留，Windows继续候选验证；43项、真实课程及G0/G1尚未完成。统一镜像库仍为 `/Users/pufei/Downloads/CTFLab-Library`。

后续建设入口：[教学与跨平台产品规划](docs/ctflab-product-roadmap-2026-10-15.md)、[Windows x64 专项设计](docs/ctflab-windows-plan-2026-10-15.md)、[实施任务与验收清单](docs/ctflab-implementation-backlog-2026-10-15.md)。方向为教学与个人练习、Windows x64 优先，覆盖 Windows 渗透、内网多靶机和应急响应；规划不代表这些新增能力已经实现。

2026-10-21 工作区进展：[平台基础第一阶段](docs/ctflab-platform-foundation-2026-10-21.md)已完成依赖清单、平台/加速器纯策略及 Mac 参数等价验证，另有本地协议草案和[Windows 原型清单](docs/ctflab-windows-prototype-checklist-2026-10-21.md)。Windows 运行器尚未实现/实机验收，当前发布 App 未重新打包。

2026-10-21 后续工作区进展：[A03 本地契约与 W01 独立驱动](docs/ctflab-local-contract-w01-2026-10-21.md)已实现持久幂等、并发前置条件、恢复/取消与事件读取；独立驱动通过本地合成自测和隔离包测试。Windows 原生后端、受保护 IPC 和实机验收尚未完成，未更新发布 App。

本机契约入口：`python3 -B tools/ctflab.py local-contract --root /absolute/private/contract-root`，读取标准输入中的 v1 JSON 行；默认只读，不创建目录或启动 VM。普通本机身份边界见[实施记录第7—8节](docs/ctflab-local-contract-w01-2026-10-21.md#8-windows-身份与私有存储接入2026-10-22)。

2026-10-21 全路线图接续：[执行台账](docs/ctflab-roadmap-execution-2026-10-21.md)逐项记录43项差距。已新增通用场景离线计划、课程目录、Windows原生基础和诊断分享预览；仍非 Windows 可用运行器。用户负责 Windows 实机验证，当前 G0/G1 未通过。

## 当前能力

- 导入 QCOW2、VMDK、VDI、VHD/VHDX、RAW、OVA；
- `inspect` 只读识别 VMDK/OVF、MBR/GPT/EFI 和候选虚拟硬件；
- `onboard` 生成带置信度、警告和人工复核状态的白名单配置；
- `probe` 收集 QMP、截图 OCR/画面分类、DHCP 与 HTTP/SSH 协议证据；
- x86_64 在 Mac M 上使用 QEMU TCG，ARM64 使用 HVF；
- 从 Kali ARM64 安装 ISO 无人值守安装 XFCE，支持安装状态查询、UEFI NVRAM 与运行盘固化；
- Kali 默认通过 user-mode NAT 联网，方便直接安装/更新工具；Smoke、Basic Pentesting 2 的管理网仍为
  `restrict=on`，三者的实验网继续只经回环交换机互通；
- 不覆盖原始镜像，运行时写入独立 QCOW2 overlay；
- 跨进程文件锁保护导入、启动、停止、重置和候选配置生成，避免多终端竞争；
- 回环 TCP 二层交换机提供固定 DHCP、MAC 学习、逐连接限速和可选 PCAP，默认不把脆弱靶机接入物理局域网；
- `CTFLab.app` 自带受控 QEMU 与 Python 运行时（含 PyYAML），目标机器无需安装任何环境；
- 基盘分发链（路线 A）：`dist prepare/verify` 生成 zstd 压缩基盘、`DISTRIBUTION.json`、`SHA256SUMS`
  与分发说明；`import --manifest/--expect-sha256` 强制核对下载文件哈希并把校验证据写入导入记录。
- 目录式内容包（schema 2）：`dist make-pack` 把自定义 profile、基盘、可选 NVRAM 与说明打成
  自包含目录；`dist install` 校验后整体导入（白名单配置、排他装 profile、事务回滚、不自动启动），
  旧 schema 1 分发目录行为不变。
- Kali 默认使用 SPICE 真实自动分辨率：启动前探测 SPICE QEMU、`spicevmc`、`virtserialport`
  与受控客户端；能力完整时窗口尺寸会驱动来宾实际分辨率。能力缺失时 `auto` 明确退化为 Cocoa 固定显示，
  显式 `--display spice` 缺件时会在创建虚拟机前拒绝。无头模式不启动图形客户端。

## 快速开始

**用打包好的 `.app`（推荐给使用靶场的人）**：`CTFLab.app` 已内置受控 QEMU 与 Python 运行时
（含 PyYAML），目标机器**不需要**安装 Python、pip 或 Homebrew QEMU。拿到 app 后首次打开需在
“系统设置 → 隐私与安全性”手动放行一次（当前为本地 ad-hoc 构建，未做 Developer ID 公证）。

**学生拿到课程分发目录后**（基盘 + 清单，见[分发指南](docs/ctflab-distribution-guide.md)）：

```bash
shasum -a 256 -c SHA256SUMS                     # 1) 校验下载完整性
ctflab import kali-arm64 kali-arm64-base.qcow2 --manifest DISTRIBUTION.json
                                                # 2) 清单自动核对哈希并套用配套 NVRAM 模板
ctflab run kali-arm64                           # 3) 启动 Kali（默认联网、真实自动分辨率）
```

哈希不一致时导入会直接失败并打印期望值与实际值：重新下载，不要绕过校验。

**从源码运行（开发用）**：环境要求 macOS Apple Silicon、Python 3.10+、PyYAML、Homebrew QEMU。
推荐安装 Tesseract 以自动区分登录界面、UEFI Shell、内核错误和无启动盘；未安装时会安全降级为人工复核。

```bash
./tools/ctflab doctor

# 已知配置
./tools/ctflab import smoke /path/to/smoke.qcow2
./tools/ctflab run smoke --pcap
./tools/ctflab health smoke

# 未知镜像候选适配
./tools/ctflab inspect /path/to/machine.ova
./tools/ctflab onboard /path/to/machine.ova --id machine-1
./tools/ctflab probe machine-1 --timeout 180
./tools/ctflab probe machine-1 --matrix --matrix-timeout 90  # 首次探测失败时，显式尝试受控回退矩阵

./tools/ctflab stop --all
./tools/ctflab reset smoke
```

### 快照、重置备份与存储清单

2026-10-08 复核修正：重置前备份保留整个实例（包括快照配对 NVRAM）。
恢复备份时，原实例自动另存为 `before-restore-*` 备份，不静默丢弃。
有整盘备份依赖时禁止删除基础镜像；确认不再需要的备份可用
`./tools/ctflab snapshot delete-backup smoke 备份名` 明确删除（不可恢复）。
缺少配对 NVRAM 的快照会在恢复磁盘前拒绝，而不是返回半恢复成功。

文本共享与文件写入独立授权：`run kali-arm64 --clipboard` 只共享文本；
`run kali-arm64 --file-transfer` 只允许从 Mac 拖入文件到 Kali 的 SPICE 窗口。
两个选项默认关闭，GUI 也提供分开的开关。文件传输不能在 Cocoa 中静默启用，
且当前没有来宾→宿主文件传输功能。已登录桌面的文本剪贴板正/负向和重连有日期化人工证据，见发布门槛记录；不能扩展为任意文件拖放或跨设备验收。

节点停止后可对运行 overlay 建命名快照（基础镜像只读、不受影响；快照连同 NVRAM
副本存放在节点运行目录内，普通 `reset` 会一并丢弃）：

```bash
./tools/ctflab snapshot create smoke lab-1     # 建快照（含 NVRAM 副本）
./tools/ctflab snapshot list smoke             # 列出（NVRAM✓ 表示配对完整）
./tools/ctflab snapshot revert smoke lab-1     # 回到快照（当前实例改动丢弃）
./tools/ctflab snapshot delete smoke lab-1

./tools/ctflab reset smoke --backup before-class   # 重置前整盘备份（overlay+NVRAM 移入备份区）
./tools/ctflab snapshot list-backups smoke
./tools/ctflab snapshot restore-backup smoke before-class
```

`./tools/ctflab storage`（或 `--json`）只读列出各节点基础镜像/overlay 占用、
backing chain 完整性、快照与整盘备份清单，以及运行中节点对基础镜像的引用，
供清理决策；当前版本不做自动清理。快照与备份操作只作用于已停止的节点，
运行中会明确拒绝。

自动探测输出的是候选，不是启动保证。磁盘文件通常无法可靠提供客体 CPU 架构、来宾网卡名、登录状态和服务清单；低置信度字段必须核对来源，probe 截图也必须排除 UEFI Shell 或错误画面。`onboard` 生成的候选配置写入用户状态目录
`~/Library/Application Support/CTFLab/profiles/`，不会改写内置课程 profile 或 `.app` 本体；回退矩阵的命中只对本次探测有效，需人工复核后才可固化。
VMDK/OVA 导入链路：`inspect` 与 `import` 支持 VMDK/QCOW2/VDI/VHD/VHDX 与 OVA 安全解包（拒绝越界成员路径）；OVA 含多磁盘时 inspect 默认取第一个并警告，
`import`/`onboard` 必须用 `--disk <文件名>` 显式选择系统盘（不猜测），导入登记记录选盘与磁盘总数；导入输出含基盘实际/虚拟占用。

### 实验网只读视图

```bash
./tools/ctflab network            # 或 --json：各节点策略/端口映射/实验网交换机与流量计数
```

并排展示 profile 声明策略与运行实际：segment、实验 IP、网卡、Kali 默认 user-mode NAT
（实验网仍经回环交换机隔离）、端口映射、交换机客户端/MAC/收发计数与残留实例。
靶机运行时联网与声明不一致会明确标记；本视图只读，不做任何变更。

## 图形入口

`CTFLab.app` 的主入口是原生 SwiftUI 界面（Apple Silicon；随包 QEMU/SPICE 运行时要求 macOS 26.0+，
不依赖 Electron/Node/浏览器）：

- 流程：选择具体镜像文件夹（不递归扫描整个镜像库）→ 分发清单校验（失败不导入本包）→ 自动导入分发包缺失的基础节点 →
  选择一个节点 → 启动所选节点/停止所选节点 → 检查状态（health）→ 重置（先弹确认框，明确提示 overlay 改动会丢失）。
  表格中的“本机已登记”只表示该状态目录已有基础镜像，不表示当前分发目录已经导入；
  `stop --all` 仍作为 CLI 的显式故障恢复命令保留；
- “添加 x86 镜像…”向导复用 `inspect --json`、`onboard` 与 `probe`：先只读识别并展示架构、固件、磁盘、网卡的置信度，
  经用户确认后才创建候选 profile 和派生基盘；首次探测失败时可显式运行 BIOS/UEFI × SCSI/IDE/SATA/VirtIO 的受控矩阵，
  但矩阵命中不会自动写回配置；工作区新增人工确认保存候选，写入前核对报告/profile/基盘哈希并保留备份，仍不自动标记已验证；该后续改进尚未重新打包；
- 图形界面只调用内置 CLI：`dist verify --json`、`import <profile> <基盘> --manifest`、`run`、
  `status --json`、`health --json`、`stop <profile>`、`reset <profile>`、`inspect --json`、`onboard`、`probe`；
  已运行的其它节点不会阻塞当前节点操作。启动所选节点时由 CLI 自动为 Kali 配置联网并优先使用 SPICE 真实自动分辨率，为其他节点保持隔离，
  不解析任意 QEMU 参数、不绕过清单哈希；命令行可直接
  使用 `run kali-arm64 smoke` 或 `run kali-arm64 smoke basic-pentesting-2`；路径含空格按单一参数传递；
- 重新打开 App 会通过 `status` 恢复已导入/运行中显示；重复导入是幂等的，不覆盖已验证基盘；
  SPICE 客户端会随该节点的 QEMU 退出而自行关闭；能力缺失时自动退化的 Cocoa 显示不依赖 SPICE。
- CLI 保留在 `CTFLab.app/Contents/Resources/bin/ctflab-cli`（兼容名 `CTFLab`），
  供开发、脚本化与故障排查使用，与图形界面共享同一状态目录与同一导入逻辑。

Smoke/Basic 的 x86 靶机静态控制台 E2E 已在限定范围内通过；旧 UTM 路径的历史记录仍保留为边界说明，
其中固定显示与动态分辨率结论不适用于显式请求的 SPICE 实验路径。
当前 App 的 Kali 默认选择带 SPICE QEMU 与本地 `spicy` 客户端的真实自动分辨率路径；`auto` 在能力缺失时退化为 Cocoa 固定显示，显式 `--display spice` 缺件时不会回退。当前验收包与限制见
[`当前状态与证据入口`](docs/ctflab-current-status.md)；2026-09-16 显示验证仅作历史证据。

## 测试

```bash
python3 -m unittest discover -s tools/tests -v
python3 -m py_compile tools/ctflab.py tools/ctflab_inspect.py tools/ctflab_network.py
```

未打包工作区的最新整批开发入口、验证范围和43项剩余判据见[连续开发记录](docs/ctflab-remaining-development-2026-10-26.md)与[当前状态](docs/ctflab-current-status.md)。Mac既有预览包与后续未打包源码分别记录，Windows仍是候选；不能将源码进展视为发布包已更新、跨平台实机或完整路线图完成。

## 文档

- [当前状态、分发目录与文档阅读顺序（2026-10-11）](docs/ctflab-current-status.md)

- [第一阶段快速使用](docs/ctflab-phase1-quickstart.md)
- [学生分发版使用教程：校验、导入、启动与重置](docs/ctflab-student-distribution-tutorial.md)
- [完整实施计划与路线图](docs/ctflab-mac-mvp-implementation-plan.md)
- [动态分辨率设计：UTM 导出与 SPICE 路径对比（SPICE 窗口跟随已验证，旧镜像需显示适配）](docs/ctflab-dynamic-resolution-design.md)
- [2026-09-06 Mac M 回归验证](docs/verification-2026-09-06.md)
- [2026-09-07 Kali 安装、图形与互通验证](docs/verification-2026-09-07.md)
- [2026-09-13 Kali 图形体验验证（剪贴板、分辨率、关闭策略、Ghidra 帮助）](docs/verification-2026-09-13.md)
- [2026-09-14 三节点网络、生命周期、干净环境与启动回退矩阵验证](docs/verification-2026-09-14.md)
- [UTM 导出包验证：Smoke（2026-09-14）](docs/verification-utm-smoke-2026-09-14.md)
- [UTM 导出包验证：Basic Pentesting 2（2026-09-14）](docs/verification-utm-basic-pentesting-2-2026-09-14.md)
- [Task 6.1 打包设计：可分发安装包与 .ctflab 内容包](docs/ctflab-task6-packaging-design.md)
- [Task 6.1 验证记录（2026-09-15）](docs/verification-task6-1-2026-09-15.md)
- [Task 6.2 设计：受控 QEMU 运行时的 CTFLab.app](docs/ctflab-task6-app-runtime-design.md)
- [Task 6.2 验证记录（2026-09-15）](docs/verification-task6-2-2026-09-15.md)
- [Task 6.3A 验证记录：Kali ARM64 + UEFI 真实验收（2026-09-15）](docs/verification-task6-3a-2026-09-15.md)
- [图形入口验证记录（2026-09-16）](docs/verification-gui-2026-09-16.md)
- [Task 6.3B 验证记录：许可证闭环与内置 Python 运行时（2026-09-15）](docs/verification-task6-3b-2026-09-15.md)
- [基盘分发指南（路线 A：网盘 / 课程资料区）](docs/ctflab-distribution-guide.md)
- [分发链验证记录：压缩基盘与可校验导入（2026-09-16）](docs/verification-distribution-2026-09-16.md)
- [联网与动态分辨率功能验证记录（2026-09-16／18）](docs/verification-display-network-2026-09-16.md)

## 许可证

- 本项目自身代码以 **MIT** 许可证发布，全文见 [LICENSE](LICENSE)；
- 随包分发的第三方组件按各自许可证提供（见 `THIRD_PARTY_LICENSES.md` 与 `SBOM.json`）；
  其中的 GPL 组件（QEMU）以随包 `SOURCE_OFFER.md` 书面要约履行源码义务。

## 安全边界

- 原始镜像只读，所有来宾修复写入可恢复的派生副本；
- 在线元数据不能传入任意 QEMU 参数；
- 虚拟磁盘、默认凭据和运行日志不得提交到本仓库；
- 只有完成冷启动、显示/登录、网络、重启与目标服务验证的镜像，才能标记为已验证交付。
## 日常操作补充（2026-10-11 整理）

2026-10-09 新增[六项稳定性与本地更新实施记录](docs/verification-stability-2026-10-09.md)：
显示诊断、输入释放、启动预检、状态筛选与本地更新槽位已实现；人工结果以指定候选、日期和发布门槛记录为准，不因代码完成而标为长期/跨设备通过。本地更新不覆盖系统安装或镜像。

- 节点状态自动刷新：运行时约 3 秒，全部停止时约 15 秒；启动阶段依据运行器信号，不使用虚构百分比。
- 运行中节点的“打开显示窗口”复用现有窗口或重连 SPICE，不重启虚拟机、不重置实验。Cocoa 窗口关闭若已导致节点退出，需要重新启动；不能恢复已停止进程的内存状态。
- SPICE 画面卡住但节点仍运行时，使用“重连显示”，或 `./tools/ctflab show kali-arm64 --reconnect`：只重建显示连接，保留来宾会话和共享授权。Cocoa 不显示该按钮，也不会以重启冒充恢复。
- 停止后的节点可进入“快照与备份”：快照恢复前自动保存保护快照；整盘恢复保留当前实例；删除操作须确认且不能撤销。
- Kali 资源档位在“更多”中选择，只影响下一次启动：沿用原配置、轻量（2GiB/2核）、均衡（4GiB/4核）、性能（8GiB/4核）。没有跨软件性能提升保证；内存预检仍会拒绝超配。
- [资源档位启动基准与候选交付复核（2026-10-09）](docs/verification-startup-presets-2026-10-09.md)：每档两轮 DHCP/SSH 就绪基线已记录，不作为桌面流畅度或闲置恢复通过结论。
- 节点支持收藏、分组与最近使用排序；“课程组合”保存已导入节点的组合，确认后逐台启动未运行节点，中途失败保留已启动节点，不自动回滚。默认启动/停止仍只操作选中节点。
- 导入过程中可“停止后续导入”：当前镜像安全处理完后停止，已完成节点保留；不是立即中断当前转换。
- 详情显示本次配置与宿主 QEMU 进程的 CPU/RSS；停止后显示下次默认配置。CPU 可超过 100%，RSS 不是来宾内存压力，采样失败显示未知。
- 文本剪贴板与拖入文件各自授权，默认关闭；清晰/流畅偏好不影响输入坐标策略。
- 未打包工作区新增“更多 → 分享诊断摘要”：只显示白名单匿名摘要，先预览再排他保存同一份内容，不上传；快照可能过期。原含路径/日志报告保留为“完整本机诊断（私密）”，不用于公开分享。已发布旧App菜单未更新，范围见[Mac诊断分享说明](docs/ctflab-mac-diagnostics-2026-10-29.md)。
- Kali 睡眠恢复尚未通过验收，暂用锁定屏幕或正常关机。提供可撤销的[睡眠避险工具与验证步骤](docs/ctflab-kali-sleep-guard.md)，需在派生来宾内显式应用，默认不会安装；不关闭锁屏，也不把防护称为唤醒支持。

Mac与Windows的后端、界面、包和实机状态分别见[跨平台功能接入矩阵](docs/ctflab-mac-parity-2026-10-26.md)。Mac原App未自动获得全部后续功能；Windows桌面工作台仍为开发候选。

Mac通用v2后端、原生工作区和可选完整运行时见[接入说明](docs/ctflab-mac-generic-2026-10-27.md)；这是未打包源码能力，真实来宾、最终包和G0/G1另行验收。

2026-10-27 课程与审计双端管理源码见[接入说明](docs/ctflab-course-administration-2026-10-27.md)：教师登记课程配置、管理员终态观察和原请求恢复已接到React/原SwiftUI，配置不启动、审计不重放；未更新发布App，真实远程/完整课程验收仍未完成。

Mac原生[拓扑草稿与差异导出](docs/ctflab-mac-topology-2026-10-27.md)已接通生产清单校验，编辑保留运行实例和原文件；需导出后按新实例配置；本轮Mac预览包含该入口，验证范围见状态第114节。

第107节继续补Mac/React拓扑资源与启动依赖编辑、循环拒绝和空闲网段移除；只改草稿声明，完整后端校验后导出，不热改实例或宣称已具备硬配额。结果见[当前状态第107节](docs/ctflab-current-status.md)。
