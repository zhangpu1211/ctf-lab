# CTFLab for Mac M

CTFLab 是面向 Apple Silicon Mac 的本地虚拟靶场运行器。它使用 QEMU 管理 ARM64 与 x86_64 客体，以不可变 QCOW2 基盘和可重置 overlay 保存运行状态，并通过仅绑定回环地址的用户态二层交换机连接 Kali 与靶机。

当前仓库只包含运行器、候选配置、来宾修复模板、测试和设计文档，不包含虚拟磁盘、账号凭据、课程题库或成绩数据。

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
- Kali 图形启动默认使用 SPICE 自动分辨率；启动前会探测 SPICE QEMU、`spicevmc`、`virtserialport`
  与本地客户端，缺件直接失败，不回退为缩放。x86 靶机默认使用 Cocoa；无头模式不启动图形客户端。

## 快速开始

**用打包好的 `.app`（推荐给使用靶场的人）**：`CTFLab.app` 已内置受控 QEMU 与 Python 运行时
（含 PyYAML），目标机器**不需要**安装 Python、pip 或 Homebrew QEMU。拿到 app 后首次打开需在
“系统设置 → 隐私与安全性”手动放行一次（当前为本地 ad-hoc 构建，未做 Developer ID 公证）。

**学生拿到课程分发目录后**（基盘 + 清单，见[分发指南](docs/ctflab-distribution-guide.md)）：

```bash
shasum -a 256 -c SHA256SUMS                     # 1) 校验下载完整性
ctflab import kali-arm64 kali-arm64-base.qcow2 --manifest DISTRIBUTION.json
                                                # 2) 清单自动核对哈希并套用配套 NVRAM 模板
ctflab run kali-arm64                           # 3) 启动 Kali（默认联网、自动分辨率）
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

自动探测输出的是候选，不是启动保证。磁盘文件通常无法可靠提供客体 CPU 架构、来宾网卡名、登录状态和服务清单；低置信度字段必须核对来源，probe 截图也必须排除 UEFI Shell 或错误画面。`onboard` 生成的候选配置写入用户状态目录
`~/Library/Application Support/CTFLab/profiles/`，不会改写内置课程 profile 或 `.app` 本体；回退矩阵的命中只对本次探测有效，需人工复核后才可固化。

## 图形入口

`CTFLab.app` 的主入口是原生 SwiftUI 界面（Apple Silicon；随包 QEMU/SPICE 运行时要求 macOS 26.0+，
不依赖 Electron/Node/浏览器）：

- 流程：选择课程分发目录 → 校验（逐文件大小与 SHA-256，失败即禁用导入与启动）→ 导入分发包声明的基础节点 →
  勾选要启动的节点（通常是 Kali + 一个或多个靶机）→ 启动未运行的所选节点 → 检查状态（health）→
  停止全部 → 重置（先弹确认框，明确提示 overlay 改动会丢失）；
- “添加 x86 镜像…”向导复用 `inspect --json`、`onboard` 与 `probe`：先只读识别并展示架构、固件、磁盘、网卡的置信度，
  经用户确认后才创建候选 profile 和派生基盘；首次探测失败时可显式运行 BIOS/UEFI × SCSI/IDE/SATA/VirtIO 的受控矩阵，
  但矩阵命中不会自动写回配置；
- 图形界面只调用内置 CLI：`dist verify --json`、`import <profile> <基盘> --manifest`、`run`、
  `status --json`、`health --json`、`stop --all`、`reset <profile>`、`inspect --json`、`onboard`、`probe`；已运行的节点不会阻塞其余节点启动，表格也可逐节点启动或停止。启动所选节点时由 CLI 自动为 Kali
  配置联网与 SPICE 自动分辨率，为其他节点保持隔离，不解析任意 QEMU 参数、不绕过清单哈希；命令行可直接
  使用 `run kali-arm64 smoke` 或 `run kali-arm64 smoke basic-pentesting-2`；路径含空格按单一参数传递；
- 重新打开 App 会通过 `status` 恢复已导入/运行中显示；重复导入是幂等的，不覆盖已验证基盘；
  Kali 的 SPICE 客户端会随该节点的 QEMU 退出而自行关闭；窗口尺寸在来宾 agent 与绝对鼠标模式
  就绪后再协商，并合并连续拖动的中间尺寸，以降低刷新与点击偏移；
- CLI 保留在 `CTFLab.app/Contents/Resources/bin/ctflab-cli`（兼容名 `CTFLab`），
  供开发、脚本化与故障排查使用，与图形界面共享同一状态目录与同一导入逻辑。

Smoke/Basic 的 x86 靶机静态控制台 E2E 已在限定范围内通过；旧 UTM 路径的历史记录仍保留为边界说明，
其中固定显示与动态分辨率结论不适用于当前 App 的 SPICE 主路径。
当前 App 使用带 SPICE QEMU 与本地 `spicy` 客户端的构建，Kali 图形启动自动启用动态分辨率；未提供该运行时或能力探测失败时，命令会在创建虚拟机前拒绝，不自动回退 Cocoa。当前验收包与限制见
[`联网与动态分辨率验证记录`](docs/verification-display-network-2026-09-16.md)。

## 测试

```bash
python3 -m unittest discover -s tools/tests -v
python3 -m py_compile tools/ctflab.py tools/ctflab_inspect.py tools/ctflab_network.py
```

## 文档

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
- [联网与动态分辨率功能验证记录（2026-09-16）](docs/verification-display-network-2026-09-16.md)

## 许可证

- 本项目自身代码以 **MIT** 许可证发布，全文见 [LICENSE](LICENSE)；
- 随包分发的第三方组件按各自许可证提供（见 `THIRD_PARTY_LICENSES.md` 与 `SBOM.json`）；
  其中的 GPL 组件（QEMU）以随包 `SOURCE_OFFER.md` 书面要约履行源码义务。

## 安全边界

- 原始镜像只读，所有来宾修复写入可恢复的派生副本；
- 在线元数据不能传入任意 QEMU 参数；
- 虚拟磁盘、默认凭据和运行日志不得提交到本仓库；
- 只有完成冷启动、显示/登录、网络、重启与目标服务验证的镜像，才能标记为已验证交付。
