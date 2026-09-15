# UTM 导出包验证记录：CTFLab-Smoke-E2E-20260914（2026-09-14）

本文是 Smoke（`smoke` profile）UTM 导出包的独立验证记录，与
`docs/verification-utm-basic-pentesting-2-2026-09-14.md` 分开归档。
结论只使用四类状态标签：**已验证** / **部分验证** / **未验证** / **后续任务**。

## 1. 包身份与校验

| 项 | 值 |
|---|---|
| 包名 | `CTFLab-Smoke-E2E-20260914.utm`（独立输出目录，未覆盖任何已有 UTM 虚拟机） |
| 变体 | `x86_64-bios`（架构 x86_64、固件 BIOS、磁盘总线 SCSI、2 vCPU / 4096 MiB） |
| 来源 profile | `smoke` |
| 基盘 | `base-b3112d219743-netfix1.qcow2`，SHA-256 `f0da1da7…`（导出前后一致，与导入登记值一致） |
| NVRAM | 不适用（BIOS 固件无 UEFI NVRAM；清单 `uefi_vars.status=not-applicable`） |
| 清单 schema | 3（离线导出字段保持导出时原值；运行结论在 `runtime_status`） |
| 结构状态 | `fixture.structure_status=complete-required-keys`（只描述必需段/必需键，与运行状态分离；
  本包导出时为 v5 的 `complete-required-keys-pending-utm-e2e`——旧 schema 迁移标签，仅标签迁移，
  `config.plist` 未受影响） |
| `utm_disk.sha256_at_export` | `e49a2cc3b2ec9fb2d03d492a638b8ada8d3d647371b374c16d5fa750b2a03305`（导出时历史记录，见 `SHA256SUMS.at-export`） |
| `utm_disk.sha256_after_e2e` | `e8ef6f1d07efea8fc5063c941bbeac30e43f1011e5a24663dc3c03831509e76d`（与当前 `SHA256SUMS` 一致） |
| `config.plist` SHA-256 | `68df1eadd07efa0686c482cad182d9e1a33073110ca5b4151c2181e90c71aba2`（E2E 前后一致，UTM 未改写） |
| 来源复核 | `source-matches-recorded`（来源镜像存在且哈希与导入登记值一致） |

**哈希字段语义**：包内磁盘是可写副本，来宾每次启动/关机会改变 `Data/data.qcow2` 的内容与 SHA-256；
`sha256_at_export` 与 `sha256_after_e2e` 是两个独立字段，不得混用，也不得用其中任何一个推断未记录的
运行状态。`SHA256SUMS` 校验当前包（与 `sha256_after_e2e` 一致）；`SHA256SUMS.at-export` 只是导出时的
历史记录，不能对 E2E 后可写盘执行校验。

**范围状态（与清单 `runtime_status` 一致）**：

- `e2e_scope: static-console-and-isolation`
- `e2e_status: passed-with-scope-limits`
- `dynamic_resolution: not-tested-for-x86-fixed-display`
- 清单说明（逐字）：本清单记录离线导出结果；静态控制台 E2E 结果以独立验证记录为准。
  该包已验证导入、冷启动、控制台交互、正常关机和无网卡隔离，但不构成动态分辨率或联网靶场验收。

离线复核（导出时，`~/Downloads/ctflab-utm-e2e-20260914/offline-report.json` 与
`offline-verification.txt`，共享记录在 E2E 根目录）：plist 与本机 UTM 4.7.5 参考结构逐键一致
（`Target=pc`、`CPU=qemu64`、`ForceMulticore=true`（2 vCPU）、`UEFIBoot=false`、`Hypervisor=false`、
`PS2Controller=true`、`RNGDevice=true`、`Display=VGA`、`DynamicResolution=false`、
`Drive.Interface=SCSI`、`Network=[]`、`Serial=[]`、`Sound=[]`、`ClipboardSharing=false`、
`DirectoryShareMode=None`、`AdditionalArguments=[]`），`qemu-img info/check` 通过。

## 2. E2E 步骤（UTM 4.7.5，原地引用包目录，不复制进 UTM 库）

| 步骤 | 结果 | 状态 |
|---|---|---|
| 导入/解析 | UTM 库出现 `CTFLab-Smoke-E2E-20260914`，状态“已停止”，架构 x86_64，路径指向独立输出目录；无“配置无效”报错 | 已验证 |
| 冷启动 | 到达控制台登录界面：`Welcome to Alpine Linux 6.12.74-0-lts on an x86_64 (/dev/tty1)`、`Hostname : Smoke`、`Smoke login:`；`IP :` 为空（无网卡） | 已验证 |
| 图形登录 | **不适用**：该镜像为纯控制台系统（无显示管理器/桌面）；登录界面即“控制台登录界面，范围收敛”，不按图形登录验收或升级声明 | 已验证（范围收敛） |
| 基本 GUI/控制台交互 | 控制台字符输入回显：逐字符输入在 `login:` 提示符回显；回车后进入 `Password:` 提示 | 已验证 |
| 来宾正常关机 | UTM 菜单“虚拟机 → 电源 → 请求关闭电源”（ACPI）：QEMU 进程正常退出；UTM 停止缩略图显示来宾 OpenRC 关机序列（`* Stopping local ...`、`* Stopping vsftpd ...`） | 已验证 |
| 磁盘完整性 | 关机后 `qemu-img check`：`No errors were found on the image`；来宾 ext4 分区 1/3 超级块 `s_state=0x0001`（干净卸载，挂载/写入时间与本轮一致） | 已验证 |
| NVRAM 完整性 | 不适用（BIOS 包无 NVRAM；包内无 `Data/efi_vars.fd`） | 不适用 |
| 网络隔离 | 配置 `Network=[]`（默认无网卡）；QEMU 进程参数含 `-nic none`，无任何 netdev/网卡设备；来宾启动日志显示无 `eth*` 设备；导出清单 `network.mode=none` | 已验证 |
| 剪贴板/共享目录 | `ClipboardSharing=false`、`DirectoryShareMode=None`、无共享目录设备；QEMU 参数无 vdagent/spicevmc 剪贴板通道 | 已验证（配置与进程参数层面） |
| 用户已有虚拟机未受影响 | 用户自有 `Smoke.utm`（8 月 24 日）与 `Basic Pentesting 2.utm`、`Linux.utm` 的目录内容/时间戳未变化；全程未重启 UTM、未操作正在运行的 Linux 虚拟机 | 已验证 |

## 3. 证据（保留于 `~/Downloads/ctflab-utm-e2e-20260914/smoke/`，不入库）

`evidence/import-accepted.png`（导入后在 UTM 库中的状态与路径）、`evidence/boot-01.png`、
`evidence/boot-02.png`（登录界面）、`evidence/console-echo.png`、`evidence/console-typed-root.png`、
`evidence/console-password-prompt.png`、`evidence/shutdown-acpi.png`、
`evidence/shutdown-sequence.png`（UTM 停止缩略图＝关机序列）；
`CTFLab-Smoke-E2E-20260914.utm.export.json`、`README.md`、`SHA256SUMS`、`SHA256SUMS.at-export`。
共享记录在 E2E 根目录：`offline-report.json`、`offline-verification.txt`、`pre-export-checks.txt`；
UTM 库状态截图（含两包与用户虚拟机并排）见 `basic/evidence/library-after-e2e.png`。

## 4. 边界与限制

- **显示**：本包为固定显示（`DynamicResolution=false`），仅保证固定显示可用；不涉及动态分辨率，
  也不对动态分辨率做任何声明。Kali 包（aarch64 变体）的显示不稳定限制见设计文档：
  “重启后复测失败，显示链路不稳定；当前包仅保证固定显示可用。”
- 未尝试任何登录口令（无凭据，也不需要）：交互验证只到 `Password:` 提示为止，不产生失败认证。
- “图形登录”按镜像真实形态收敛为“控制台登录界面”，两者不可互相替代宣称。
- 宿主键鼠注入经 UTM 合成焦点完成（修饰键组合可能丢失修饰位，已在记录中说明），不影响本包结论。
