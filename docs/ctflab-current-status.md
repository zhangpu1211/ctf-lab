# CTFLab 当前状态与文档入口

> 2026-10-11 文档复核。这里区分已发布软件、工作区实现、镜像资产与历史验收；不把代码完成或旧测试数替代本轮实机测试。

## 1. 三个不同交付物

| 对象 | 当前入口 | 边界 |
|---|---|---|
| 源码工作区 | `/Users/pufei/Downloads/ctf-lab` | 保留现有未提交修改；不是新的已发布 App |
| 已发布软件 | 镜像库 `03-软件/CTFLab-0.1.1-preview.20261012` 中 App/ZIP | GitHub 预发布 v0.1.1-preview.20261012；Apple Silicon、macOS 26+，ad-hoc、未公证；旧包保留 |
| 可迁移镜像库 | `/Users/pufei/Downloads/CTFLab-Library` | `01-待处理` 保存原始输入；`02-已处理` 保存三节点包及独立 Acfun 本地适配包；不含运行进度 |

旧 worktree、历史 build/e2e 目录不再是使用入口。保留历史文档里的路径只用于追溯，清理后的文件不能继续按旧命令调用。

### 镜像库与 Kali 配套关系（2026-10-11 补记）

- `02-已处理/kali-arm64-base.qcow2` 与 `kali-arm64-uefi-vars.fd` 必须保留，供接收者导入；本轮未删除它们。基盘沿用 2026-09-16 分发文件，其哈希与本机当前登记来源一致，并不是将后续运行 overlay 软件/设置重新固化的新镜像。
- 后续 Kali 显示、输入与窗口优化主要在 App/受控显示客户端；既有测试使用该基盘派生的独立运行副本。测试中的临时来宾适配、用户反馈与候选客户端结果不能自动扩展为“新机器用未修改基盘已全部通过”。实际运行效果需与对应 App、来宾适配和日期化证据一起判断。
- 本库软件是已发布 `0.1.1-preview`，不是尚未打包的最新工作区。不要把“当前基盘可配套使用”写成“所有最新优化已固化到基盘”。
- `01-待处理/安装ISO/kali-linux-2026.2-installer-arm64.iso` 仅为从零重装备用，现成三节点导入不需要它；用户尚未要求删除，保留中。
- 本库 WebServer 原始 OVA 和候选派生副本均已按用户要求删除；库外课程资料原件、应用状态目录中的主副本未动。根目录说明/文件清单/校验已同步。旧来源目录仍可能被现有登记或运行实例引用，不能继续按目录年龄批量删除。

## 2. 使用与能力

- GUI 选择具体镜像目录：有分发清单则校验并导入缺失节点；普通目录顶层镜像走候选登记；不递归扫描库根。
- 节点启动、停止以所选节点为准；已导入状态与新选择的分发目录状态分开。QEMU 已退出不能恢复内存会话。
- Kali 默认 auto 在完整 SPICE 能力可用时使用真实自动分辨率，缺件时 Cocoa 固定显示；显式 SPICE 缺件拒绝。共享默认关闭、剪贴板与文件拖放分别授权。
- x86 在 M 芯片使用 TCG 模拟，ARM64 使用 HVF；提前转换为 QCOW2 不改变客体架构。
- 外部预制磁盘可以读取，但完整分发需要匹配 profile、清单和固件。DISTRIBUTION.json 不自动安装任意自定义 profile。
- 原盘不改写；基盘、overlay、快照、备份的用途分开。运行状态保存在 App 外的用户状态目录。

## 3. 前一轮导入验收（2026-10-11 R3 历史快照）

单镜像导入进度、安全取消/重试、来源优先的受控启动矩阵、QEMU 子进程回收，以及人工确认保存矩阵候选已在工作区实现。保存前校验报告、profile 与基盘哈希并保留配置备份；命中仍不自动标记为已验证交付。

此前改进尚未重新打包；本轮已独立构建本地候选，版本仍为 0.1.1，以日期和树摘要区分，未替换镜像库 0.1.1-preview。最终 App：`/Users/pufei/Downloads/ctflab-import-acceptance-20261011/app-r3/CTFLab.app`，树摘要 `041401e605fea64e19829a950e8b79bd25fda6eb9eac3bcebf946fff3cdbcb45`。

本轮真实 Smoke 副本与新增 Acfun OVA 的取消/重试、原盘保护、重复导入和完整性检查通过；GUI 实际取消、重试和二次确认保存候选已验收。发现并修复模态向导内缺少进度/取消入口及重试后旧错误残留；R3 实际取消/重试和回主窗口已复测。保存正向样本明确配置已知 SSH 检查；App 无 OCR、仅 DHCP 的默认未知候选不会生成可保存命中。

本轮 R2 阶段完整回归 643 项：633 通过、10 条件跳过；矩阵专项显式 E2E 34 项通过；R3 改动另跑 GUI 专项 25 项通过；新版 App 清单/许可证/严格签名通过，三节点配套冷启动与 SSH/HTTP 协议证据通过，未复测认证登录及完整重启。失败、范围与恢复入口见[独立验收记录](verification-import-review-2026-10-11.md)。

## 4. 未覆盖和后续路线

- 跨另一台 Mac、真实外接显示器、Mac 睡眠和干净长时闲置/持续负载按发布门槛记录保留；用户接受预览发布不等于这些实测通过。
- Acfun 已补登录画面、实验网 SSH 和正常关机再启动验收；认证登录、解题和长时负载未验收。其他未知镜像需逐个验收。
- 跨状态端口占用与长 QMP 路径修复已落地并进入本轮本地 App；真实隔离/长路径验证见四项续验记录。
- R3 原生 GUI 曾在 Downloads 来源的目录扫描停滞；用户随后确认有下载文件夹访问提示并已允许。同盘临时目录只读副本识别、取消/重试通过；授权后同一 R3 App 的原 Downloads 路径 GUI 只读识别复测通过，显示候选硬件，未新增导入或启动虚拟机。证据 `gui-r3-downloads-permission-recheck.json`；未开启完整磁盘访问。
- 待处理目录本轮新增 18 个 OVA，只选 Acfun 作验收样本；其余保持原始输入，未批量宣布可用。
- 自定义 profile 的统一分发/安装、签名内容索引仍需完善。
- 多主机、多网段与 Docker 联动是后续计划，不是现成内网能力；不连接真实办公 LAN。

## 5. 文档阅读顺序

新聊天交接：先读取本文件与 `AGENTS.md`，核对真实 Git/文件状态后再继续；本轮源码和文档未提交、未推送；已独立重建本地候选 App，未发布或替换原软件。保留既有工作区改动，不在旧 `ctf_lab-master` worktree 开发，不自动停止用户实例。用户在新聊天明确指定下一项任务后再实施，不默认续跑历史桌面验收。

1. [学生使用教程](ctflab-student-distribution-tutorial.md)：当前使用入口。
2. [镜像制作与分发](ctflab-distribution-guide.md)：完整包、外部镜像与迁移。
3. [源码快速使用](ctflab-phase1-quickstart.md)：开发维护/CLI。
4. [实施路线图](ctflab-mac-mvp-implementation-plan.md)：当前计划与历史阶段。
5. [发布说明](release-v0.1.1-preview.md)与[发布门槛](verification-release-gates-2026-10-09.md)：指定版本证据。
6. [动态分辨率设计](ctflab-dynamic-resolution-design.md)、[运行时打包设计](ctflab-task6-app-runtime-design.md)：实现约束与日期快照。

`verification-*.md` 是历史验收快照，保留当时数字、失败、路径与限制，不改成今天的结果。Task 6.1/6.2 早期缺依赖、许可证阻塞等只描述当时产物；现有 App 已内置 Python/PyYAML，许可证闭环见 Task 6.3B，但 Developer ID/公证仍未完成。

## 6. 前一轮交接（2026-10-11 R3，历史快照）

证据根 `/Users/pufei/Downloads/ctflab-import-acceptance-20261011`，包含最终本地 ZIP、驱动、初次失败及最终回归日志。状态目录：证据根内 `source-state`、`gui-state`、`gui-r2-state`、`pairing-state`，另有 `/private/tmp/ctflab-pair-20261011`、`/private/tmp/ctflab-ova-20261011`、`/private/tmp/ctflab-gui-r3-20261011`、`/private/tmp/ctflab-r3-pair-20261011`。R3 最终包在短独立目录串行三节点 cold probe 全部通过；现场核验本轮 QEMU/交换机/inspect 及 GUI 已退出，未停止用户实例。探测 JSON/PNG 副本在证据根 `tmp-probe-records`。保留本轮派生磁盘、报告和配置备份；后续不得凭旧 PID 操作实例，先现场核验。

源码与文档仍未提交，分支/HEAD 未变；本地已重新打包，未推送或发布，镜像库软件仍是原发布版本。后续可完善无 OCR 的人工截图复核入口、短路径与跨状态端口协调，或逐个适配待处理 OVA；这些是下一阶段目标，不能默认执行。

新聊天交接语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 `AGENTS.md`、本状态文件和 `docs/verification-import-review-2026-10-11.md`，核验 Git 与实例，保留现有未提交改动、原始 OVA、分发基盘和测试现场。本地候选已打包但未发布，旧 0.1.1-preview 未替换；不要自动停止用户虚拟机、删除资产、提交或发布。下一阶段目标由本次新请求指定。


## 7. 前一阶段四项续验（2026-10-11，历史快照）

用户要求的截图人工确认、跨状态端口/长 socket 修复、Acfun 适配、新版本地 App 四项在本轮实施并真实验证，详见 [四项独立验收](verification-followup-acfun-2026-10-11.md)。证据根 `/Users/pufei/Downloads/ctflab-followup-20261011`。当时最终 App：`app-final/CTFLab.app`；本地 ZIP：`CTFLab-0.1.1-followup-acfun-20261011-local.zip`。版本仍为 0.1.1，未替换或发布镜像库 0.1.1-preview。

Acfun 分发包 `/Users/pufei/Downloads/CTFLab-Library/02-已处理/Acfun-20261011`：1 GiB/1 vCPU，BIOS/IDE/pcnet，实验网 192.168.242.32:22，须使用本轮含 acfun 内置配置的 App。原 OVA 保留；无宿主 SSH 转发。真实登录画面、DHCP、SSH 和两轮正常关机再启动通过；无认证登录/挑战解题/长期负载结论。最终包同时复测 Kali、Smoke、Basic 基盘冷启动与 SSH/HTTP，三个原分发基盘没有改写。

源码与文档未提交，分支/HEAD 不变，无推送或发布。本轮状态目录均在证据根：长 acfun-adapt 状态路径见 acfun-state-path.txt、gui-state、gui-final-state、pairing-state、final-acfun-state-long…；所有测试资产、报告及备份保留。收口现场本轮独立 QEMU/交换机/测试 App 已退出，原始 Acfun 与三个基盘/固件哈希不变；详细结果见独立验收记录，后续先核验 runtime.json 与实际命令再操作，不能沿用旧 PID。

新聊天交接语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先完整读 AGENTS.md、docs/ctflab-current-status.md 和 docs/verification-followup-acfun-2026-10-11.md，核验 Git 与实际实例，保留未提交改动、原始 OVA、Kali/Smoke/Basic/Acfun 基盘和测试现场。本地 App 已重新打包但未发布，旧 0.1.1-preview 未替换；不要自动停止用户虚拟机、删除资产、提交、推送或发布。下一阶段目标由本次新请求指定。

最终 App/ZIP 哈希见四项续验记录。最终全回归仅新文档快照标识失败，修正文档后 7 项文档专项通过；真实桌面取消/保存与候选备份、最终包四镜像配套均通过，范围与未测项保留。


## 8. 当前交接：Acfun同网、闲置与恢复（2026-10-12，历史快照）

本轮真实Kali来宾终端到Acfun SSH通过；Acfun 1GiB/1vCPU 完成1804秒闲置、139次协议/资源样本及三轮正常关机再启动，SSH恢复约32.6秒。未验证Acfun认证登录、挑战解题、持续负载、其他Mac或睡眠恢复。Kali同期有人为操作，不称为全程闲置。

发现上轮长SPICE路径的启动登记/等待及重连仍有遗漏；已补齐并用最终包真实冷启动、保持PID/磁盘的重连验证。已登录Kali关机确认导致超时后保留现场，恢复显示并由用户正常关机；没有强杀。最终完整回归651项：641通过、10条件跳过。具体失败/范围见 [本轮验收](verification-acfun-continuation-2026-10-12.md)。

最终干净本地App `/Users/pufei/Downloads/ctflab-continuation-20261012/app-final/CTFLab.app`；ZIP `CTFLab-0.1.1-acfun-stability-20261012-final-local.zip`。805登记文件、许可证/严格签名/解压副本校验通过；实测前后App树不变。外部验收导入在中间app-r4/app-r5产生缓存的失败记录保留；这些中间目录不作为交付入口。App内部版本仍0.1.1、ad-hoc、未公证；镜像库03-软件仍为原0.1.1-preview，无发布或替换。

证据根 `/Users/pufei/Downloads/ctflab-continuation-20261012`。本轮paired-state及长r4-spice-long-state目录的QEMU、交换机、显示客户端与测试主App已退出；保留overlay/NVRAM和所有证据。原Acfun、四镜像分发基盘及Kali固件hash不变，三份overlay检查通过。后续先核验绑定，不能凭旧PID或直接重跑历史驱动。

源码与文档未提交，分支 `codex/release-0.1.1-preview-20261010`、HEAD `42a3aa71d2665e20d9aec27f4afa19eed43a784d` 不变，无推送或发布。下一阶段可逐个适配其他镜像，或另行界定长期/负载验收；不默认实现多主机或Docker。

## 9. 当前交接：目录式内容包（2026-10-12，本轮）

**独立复核更新：本节保留 ZCode 阶段快照，当前验收结论以下方第 10 节为准。**

可迁移镜像内容包已落地：`DISTRIBUTION.json` schema 2 在原分发格式上扩展 `profile/doc` 角色与 `pack` 元数据，`dist make-pack` 制作、`dist verify` 显示包摘要与冲突预览、`dist install` 事务导入（整体校验→排他装配置→逐节点导入→说明入状态目录→包记录；失败回滚本轮写入、原包不动、内置同名拒绝、用户同名不同内容默认不覆盖）。包内 `verification`/`claims` 仅作为声明存储，导入不设置任何“已验证”标记。旧 schema 1 分发目录与逐节点 import 行为不变。GUI 选择内容包目录后展示包摘要并走单次 `dist install`。

真实验收：自制 smoke-mini-pack（独立 ID、基盘取自镜像库 smoke 副本、hash 一致 `7620acabaf1b…`）在独立状态完成校验、导入、真实启动（`service_ready`、DHCP 192.168.242.66、SSH `SSH-2.0-OpenSSH_10.0`、截图）、正常停止、移包后再启动、篡改（缺件/改字节）失败恢复；原包与状态全程完好。单元/合成：新增内容包 25 项、GUI 25 项、受影响套件 87 项通过；最终完整回归 676 项全部通过、10 条件跳过（213.355 秒，`full-regression-contentpack.log`）。

**未完成**：GUI 鼠标点击全流程未执行——桌面截图显示用户正使用 Chrome（非空闲），按边界中止；配方见验收记录。本地测试候选 App 在证据根 `app/`（Homebrew QEMU 根构建，28 动态库，非上轮定制 runtime-root），`app verify` 与包内 CLI 通过；未发布、未替换 0.1.1-preview。

分支/HEAD 不变，全部改动未提交；证据根 `/Users/pufei/Downloads/ctflab-contentpack-20261012`（含 retained-packs、独立 state、probe 报告、回归日志）。本轮 QEMU/交换机/测试 App 均已退出（PID 91561/93846 核验退出），无残留。详细范围、失败与 GUI 配方见 [内容包验收](verification-content-pack-2026-10-12.md)。

新聊天交接语：继续CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先完整读AGENTS.md、本状态文件与docs/verification-content-pack-2026-10-12.md，核验Git、产物与实际进程。保留未提交改动、原OVA、四镜像基盘、内容包证据根。内容包机制已CLI真实验收；GUI点击流程待用户空闲后按配方执行；不要自动停止用户VM、删除资产、提交/推送/发布或直接重跑旧驱动。

## 10. 当前交接：内容包独立复核（2026-10-12）

**GUI 追加实测已完成，发现新增 P1：篡改包校验失败后仍走普通 onboard，实际导入了校验失败的磁盘。** 独立 gui-state 正常导入/同内容重复/冲突拒绝/恢复重试已操作；篡改失败产生第二节点，故失败恢复不通过。冲突摘要和失败结构化提示也未达到配方预期。详情与节点快照见独立复核记录，测试 App 正常退出，没有启动任何虚拟机。之前的“GUI 未执行”是追加实测前快照，不能作为当前状态。

候选尚未通过完整验收：独立实际导入复现了多节点失败删除成功节点配置、失败重装删除原包记录且改变节点元数据、UEFI 模板依赖原包路径；静态验证还确认 HTTP readiness 路径可改变目标主机、lab_ip 越界配置被接受。证据、范围与下一步见 [独立复核](verification-content-pack-independent-2026-10-12.md)。专项 25 项通过不能覆盖上述缺陷；ZCode 的 676 项总数应读作 666 通过、10 跳过。

证据根 `/Users/pufei/Downloads/ctflab-contentpack-independent-review-20261012`。本轮未改实现、未启动虚拟机或访问外网，未操作用户实例与镜像库。已有未提交改动、分支与 HEAD 保留；无提交、推送或发布。原始验收文档此前被 .gitignore 忽略，本轮已补文档白名单。GUI 点击尚未执行，后续先修复并补复现回归，再确认桌面空闲并验收；重新打包还需核对定制运行时及 Kali/Smoke/Basic/Acfun 配套。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、当前状态与 docs/verification-content-pack-independent-2026-10-12.md，核验实际 diff 和证据；本次目标是修复内容包五处复核问题、补真实失败恢复和 UEFI 移包验收，再做 GUI 与本地打包。保留所有既有改动、原始资产与失败现场；桌面实测前确认本轮空闲，不自动停止用户虚拟机、删除资产、提交、推送或发布。


## 11. 当前交接：内容包修复轮（2026-10-12，本轮）

**独立复验更新：原五个后台场景通过，但 NVRAM 失败重装仍改变既有登记，当前结论以第 12 节为准。**

第 10 节列出的五处复核缺陷与 GUI 校验绕过已全部修复，当前结论以本节为准。修复内容：回滚按节点所有权（同包多节点部分失败时已提交节点的 YAML/基盘/登记完整保留）、说明冲突预检提前且既有 `pack.json` 永不删除、NVRAM 模板导入即复制进状态目录（移包后 `ensure_uefi_vars` 可用）、readiness HTTP path 白名单 + 执行器回环主机断言 + 重定向离开回环即拦截、`lab_ip` 限 192.168.242.0/24、GUI `DistImportGate`（校验失败/输出不可解码一律中止，绝不回退普通镜像 onboard）、失败 JSON 原始透传结构化解码（红色校验行+具体横幅）、`dist verify --conflicts` 冲突预览进包摘要卡。损坏 OVA 的裸 `tarfile.ReadError` 顺带包装为 `CTFLabError`。详见 [修复轮验收](verification-content-pack-fix-2026-10-12.md)。

修复验证（本轮实际执行）：内容包专项 30 项、GUI 25 项通过；独立复核 `reproduce.py` 重跑在 P1 断言处不再复现；正向 `verify-fixes.py`（真实 qemu-img/文件 IO、不启动来宾）五场景全部通过（`fix-results.json`）。最终完整回归 **681 项全部通过、10 条件跳过**（212.914 秒，`full-regression-fix.log`）。文档守卫曾拦下独立复核记录与本轮修复记录缺规定抬头短语，已按项目约定补抬头行（正文均未改动）。

配套运行时重新打包：`/Users/pufei/Downloads/ctflab-contentpack-fix-20261012/app-r2/CTFLab.app`（`ctflab-build/runtime-root`，782 登记文件、59 动态库，`app verify` 通过；包内 CLI 篡改失败 JSON 结构化输出与 `--conflicts` 冲突预览实测正确）。未替换镜像库 03-软件，未发布。

**GUI 点击复测与 ARM 实机复测已完成（2026-10-12，用户确认空闲后）**：app-r3 原生目录选择器实测——正常导入（包摘要+三行通过+自动安装）、同名不同内容提前显示橙色冲突并拒绝（双方 sha 前缀）、内容一致提示"重复导入将跳过"、**篡改包仅具体 SHA 横幅+红色行，无任何自动导入、无第二节点**、恢复重试横幅消失；ARM 包（Kali 基盘+NVRAM 只读副本，hash 与库一致）独立状态导入后**移走整包** headless 真实启动 `service_ready`（DHCP 192.168.242.88、SSH `SSH-2.0-OpenSSH_10.3p1 Debian-4`、截图），probe 自动停止，无 QEMU 残留。app-r3 在 app-r2 基础上补了冲突预览按哈希区分一致/不同的精度修正（GUI 核心检查 207 项 0 失败）。详见修复轮验收记录"GUI 点击复测与 ARM 实机复测"一节。用户 gui-state 失败现场的 smoke-mini-base 第二节点登记保留未动，由用户决定去留。证据根：第一轮 `ctflab-contentpack-20261012`、用户复核 `ctflab-contentpack-independent-review-20261012`（保留未动）、修复轮 `ctflab-contentpack-fix-20261012`。分支/HEAD 不变，全部改动未提交，无推送或发布；本轮无运行中实例。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、当前状态第 11 节与 docs/verification-content-pack-fix-2026-10-12.md，核验实际 diff、证据与进程。保留所有既有改动、原始资产、失败现场与三个证据根。本次目标：用户确认空闲后做 GUI 点击复测与 ARM 实机启动复测；不要自动停止用户虚拟机、删除资产（含复核现场的节点登记）、提交、推送或发布。

## 12. 当前交接：修复后的独立复验（2026-10-12）

独立新状态真实导入验证原五个后台场景通过、内容包专项 30 项通过，app-r3 结构/清单/许可证/签名校验通过。仍复现 P1：状态 NVRAM 模板损坏时重装失败，却提前把既有 image.json 的 uefi_vars_path 改为原包路径。详情及复现证据见 [独立复验](verification-content-pack-recheck-2026-10-12.md)。原成功结果保留，当前整体验收暂不通过。

证据根 `/Users/pufei/Downloads/ctflab-contentpack-independent-recheck-20261012`。本轮未启动虚拟机、未操作桌面、未访问外网，未改实现或镜像库；已有改动和失败现场全部保留，分支/HEAD 未变，无提交、推送或发布。修复轮文档此前被忽略，已补白名单。下一步修复 NVRAM 节点提交边界并补失败重装/复制失败恢复，再复核打包；桌面复验须确认本轮空闲。


## 13. 当前交接：NVRAM 提交边界修复（2026-10-12，已收口）

**独立复验更正：源码补修通过，但所列 app-r3 仍含旧代码，当前交付状态以第 14 节为准。**

第 12 节复现的 NVRAM 提交边界缺陷已修复：内容包导入不再向 `_import_image_unlocked` 传 `manifest`（消除"导入路径把 `uefi_vars_path` 临时写成包内路径"的根因），改为前置完成模板校验与状态目录复制、基盘只做 `expect_sha256` 哈希核对（`source_verification.method` 记为 `content-pack-manifest`），节点提交后才登记状态副本；复制失败包装为 `CTFLabError` 并整体回滚，原登记原样保留；模板与登记不一致时拒绝覆盖。导入前缺 base 的节点也明确拒绝。

修复验证（本轮实际执行）：内容包专项 32 项通过（新增"重装时 NVRAM 复制失败→原登记保留、新副本回滚、包记录不动"与"缺 base 拒绝"两项，复制失败以真实 OSError 注入）；GUI 点击复测与 ARM 实机启动复测全部通过（见修复轮验收记录，app-r3：正常导入、冲突预览按哈希区分一致/不同、篡改包仅具体 SHA 横幅+红色行无任何自动导入无第二节点、恢复重试；kali-mini-pack 移包后真实启动 `service_ready`、DHCP 192.168.242.88、SSH `SSH-2.0-OpenSSH_10.3p1 Debian-4`）。最终完整回归 **683 项全部通过、10 条件跳过**（223.184 秒，`full-regression-fix2.log`）。

交付入口：`/Users/pufei/Downloads/ctflab-contentpack-fix-20261012/app-r3/CTFLab.app`（配套运行时，782 登记文件（app-r2 构建；app-r3 变更为 GUI 源码级，登记文件数一致），`app verify` 通过；未替换镜像库 03-软件，未发布）。证据根：第一轮 `ctflab-contentpack-20261012`、用户复核 `ctflab-contentpack-independent-review-20261012`、独立复验 `ctflab-contentpack-independent-recheck-20261012`（保留未动）、修复轮 `ctflab-contentpack-fix-20261012`。分支 `codex/release-0.1.1-preview-20261010`、HEAD `42a3aa71…` 不变，全部改动未提交，无推送或发布；当前无运行中的 CTFLabGUI/QEMU 实例。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、当前状态第 13 节与 docs/verification-content-pack-fix-2026-10-12.md，核验实际 diff、证据与进程。保留所有既有改动、原始资产、失败现场与四个证据根中用户标记保留的部分。内容包机制五处复核缺陷、GUI 校验绕过与 NVRAM 提交边界均已修复并实机复验；如需下一目标（如其他镜像适配、发布打包），由新请求指定；不要自动停止用户虚拟机、删除资产（含复核现场的节点登记）、提交、推送或发布。

## 14. 当前交接：源码补修通过，App 更新待完成（2026-10-12）

独立新状态验证原五场景及 NVRAM 模板损坏/复制失败保护通过，原登记和包记录逐字节不变；内容包 32 项通过。源码缺陷关闭。app-r3 结构/签名校验通过，但包内 ctflab.py 仍是旧 manifest 导入路径，与源码哈希不同，尚未包含本次提交边界修复，不能作为完成的新版交付。详见 [独立复验追加](verification-content-pack-recheck-2026-10-12.md)。

证据根 `/Users/pufei/Downloads/ctflab-contentpack-independent-final-20261012`。本轮没有启动虚拟机、操作桌面、修改实现或重新打包；所有原资产与失败现场保留，分支/HEAD 未变，无提交、推送或发布。下一步使用配套运行时在新目录重建 App，核对包内源码并用包内入口复验失败恢复，更新交付入口；不覆盖旧验收产物或镜像库软件。683 项全量日志是 673 通过、10 跳过，本轮未重跑全量。


## 15. 当前交接：app-r4 交付打包完成（2026-10-12，本轮）

**独立核对追加：app-r4 校验、源码一致性、包内 NVRAM 两种失败恢复通过；运行时“全部逐字节同源”表述不成立。** 对比上一轮 app-final，QEMU/SPICE 的 bin 4 件相同，70 个 dylib 中 5 个不同，排除签名数据区后仍不同。证据根 ctflab-contentpack-independent-r4-20261012，详情见 [独立复验追加](verification-content-pack-recheck-2026-10-12.md)。该差异不是已证明的故障，但 app-r4 的 SPICE 运行兼容性仍须溯源或真实复验；当前作为含修复的本地候选，不发布。原源码/App 不一致问题已关闭。

第 14 节待办完成：**app-r4 已用配套运行时构建并通过包内复验，成为新版交付入口**。要点：

1. 构建 `ctflab-contentpack-fix-20261012/app-r4/CTFLab.app`（743 登记文件、70 动态库；未覆盖 app-r3）；`app verify` 通过；旁车树摘要 `bdba17328b527e…`/MANIFEST `95897de7269a…` 用构建器算法复核一致。
2. SPICE：沿用已验收自研 spicy（字节 `4f158923…`/`a6c61545…`，与 `app-final` 完全一致，源码与 HEAD 一致），未退回 Homebrew 现货。因历史 70-dylib QEMU 构建根已清理，以已验收 App 的完整 runtime 构造配套暂存根完成闭包自洽构建（app-r4 运行时与已验收 App 逐字节同源：QEMU 三件/spicy/70 dylib/share 全部 SAME）。
3. 包内 `ctflab.py`/`ctflab_dist.py` 与源码 `cmp` 逐字节一致，确认含 NVRAM 前置校验/复制与 `expect_sha256` 导入。
4. 包内 NVRAM 边界复验（包内 Python `-B`、全新状态、无 `__pycache__`）：模板损坏与复制失败两场景均拒绝安装，原 `image.json`/`pack.json` 逐字节不变、登记未指向包内路径、无模板残留（`r4-nvram-recheck-results.json`）。

本轮未启动虚拟机、未操作桌面；此前 GUI 点击与 ARM 实机结果仍属对应轮证据。源码与文档未提交，分支/HEAD 不变，无推送或发布，镜像库 03-软件未替换。最终完整回归 683 项（673 通过+10 条件跳过）截至第 13 节，本轮未重跑（无源码变更）。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、当前状态第 15 节与 docs/verification-content-pack-fix-2026-10-12.md 的 app-r4 节，核验 Git、产物哈希与进程。交付入口 `ctflab-contentpack-fix-20261012/app-r4/CTFLab.app`（含内容包机制与 NVRAM 边界修复、SPICE 配套）；保留所有既有改动、资产与失败现场；不提交、不推送、不发布、不替换镜像库软件；如需实机运行复验（GUI 点击/ARM 启动）须先确认桌面空闲。


## 16. 当前交接：app-r4 溯源更正与 SPICE 实机验收（2026-10-12，已收口）

独立追加核对：5 库与 input-recovery App 逐字节相同；实际查看单窗口截图确认 Kali 登录画面，客户端日志记录显示就绪与正常退出，现场无相关进程。运行时疑虑在登录画面显示范围内关闭，app-r4 接受为本阶段本地候选交付；未重跑实机，不将 ZCode 证据表述为本轮独立启动。详情见独立复验记录的同日追加。

独立核对更正"运行时全部逐字节同源"表述属实：app-r4 与 app-final 相比 5 个 dylib 不同（libpcre2-8.0、libglib/gobject/gmodule/gio），排除签名区仍不同。已完成**溯源与运行双重闭环**：

1. **溯源**（`dylib-provenance-trace.json`）：这 5 库是 **glib 2.88.3 家族**（dylib current version 8801.3.0；pcre2 为 10.47 世代），与 input-recovery/app、import-acceptance/app-r2 包内字节逐一致；其 SBOM 记录的 keg 原件哈希（glib 2.88.3=`629b656720b2`）仍在当前 Cellar 吻合。app-final 用的是 Homebrew 升级后 glib 2.90.1（r3 轮重建，SBOM 双证）。差异=相邻大版本，非构建漂移。
2. **运行验收**：app-r4 对 kali-arm64 `--display spice` 真实启动——包内 spicy（2.88.3 闭包）渲染出完整 Kali 登录界面（截图 `spice-r4-clean.png`），health 三项 OK（DHCP .10、SSH 10.3p1），正常停止无残留。5 库差异未表现任何运行故障。

交付入口不变：`ctflab-contentpack-fix-20261012/app-r4/CTFLab.app`。SPICE 门禁（仅 kali-arm64 单独启动）保持。未登录桌面交互、未长时闲置、未跨 Mac。源码/文档未提交，分支/HEAD 不变，无推送或发布，镜像库未动；当前无运行实例。完整回归截至第 13 节的 683 项（673 通过+10 跳过）仍有效（此后无源码变更）。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、当前状态第 16 节与 docs/verification-content-pack-fix-2026-10-12.md，核验 Git、产物哈希与进程。app-r4 为含内容包机制+NVRAM 边界修复+SPICE 配套的本地候选，已完成溯源与 SPICE 实机验收；保留所有既有改动、资产与失败现场；不提交、不推送、不发布、不替换镜像库软件。


## 17. 当前交接：app-r4 最终验收进行中（2026-10-12，任务2完成）

用户指定三项：① Kali 登录后实际使用验收 ② 四镜像配套验收 ③ 交付 ZIP。**任务2 已完成**：四镜像经 app-r4 包内 CLI 导入 `final-state`（哈希全对），smoke/basic/acfun 串行 probe 全部通过——smoke `service_ready`+SSH 10.0；basic 登录画面+HTTP 200+SSH 7.2p2 Ubuntu；acfun tty1 登录提示符画面内自报 IP .32。绑定与截图见 `final-acceptance/final-task2-bindings.json` 与 `final-state/logs/probes/`；记录见 [最终验收](verification-content-pack-final-20261012.md)。

**任务1 待执行**（kali-arm64 已导入未启动；需用户确认桌面空闲并亲自登录）：SPICE 冷启动→登录→输入/鼠标/缩放/终端交互→重连→正常关机，同时配对 acfun 取 SSH 证据。**任务3 待任务1 通过后执行**。本轮结构验收重做并绑定（app verify/源码/树摘要/运行时配套全过）。分支/HEAD 不变、61 项未提交改动保留、无运行实例、未提交/推送/发布、镜像库未动（前测哈希已存，后测在任务1 后）。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、当前状态第 17 节与 docs/verification-content-pack-final-20261012.md，核验 Git/进程/状态目录。任务2 证据在 `ctflab-contentpack-fix-20261012/final-acceptance` 与 `final-state/logs/probes`；kali-arm64 已导入未启动，任务1 需用户确认桌面空闲并亲自登录（不记录密码），任务3 随后。保留全部既有改动、资产与失败现场；不提交、不推送、不发布、不替换镜像库软件。


## 18. 当前交接：app-r4 最终验收与交付 ZIP 完成（2026-10-12，已收口）

独立交付核对追加：ZIP 完整 SHA 与记录一致，CRC 通过、逐项与交付目录无差异，App 校验及树摘要通过；重连截图可见真实登录终端及 Acfun SSH banner，现场无相关进程。三项接受为本地功能验收/候选交付完成。本次只核对已有实机证据。SBOM“70 库全部归属 qemu”表述不准确，实际还有 spice-gtk 归属，真实组件映射与许可证归属仍需在正式分发前整理，不把 app verify 当作完整分发义务验收。

三项任务全部完成，详见 [最终验收](verification-content-pack-final-20261012.md)：

1. **任务1 Kali 登录后实际使用**：app-r4 SPICE 冷启动→用户手动登录→键盘/中英文输入、鼠标、窗口切换、滚动、缩放、终端命令实测通过；本轮独立 Kali→Acfun（回环隔离网）`nc .32 22` 取得 `SSH-2.0-OpenSSH_10.0`；关窗重连后 QEMU PID 4013/overlay 不变、无第二实例；正常关机路径含 ACPI 确认框（保留现场→用户点击 Shut Down→自然退出）；QEMU/spicy/网络子进程归零。
2. **任务2 四镜像配套**：kali-arm64、smoke、basic-pentesting-2、acfun 全部经包内 CLI 导入（哈希对清单）+ 串行真启动（QMP 截图）+ DHCP + 协议证据（SSH/HTTP）+ 正常停止；来源资产前后哈希一致。
3. **任务3 交付 ZIP**：`/Users/pufei/Downloads/ctflab-final-delivery-20261012/CTFLab-0.1.1-contentpack-final-20261012-local.zip`（SHA-256 `5aaa76d3…`，52,975,929 bytes），含 App+树/MANIFEST 摘要+中文使用说明+验收摘要；解压复验（app verify/源码/旁车/运行时/SPICE/包内 CLI 只读检查）全过，实测后树摘要无污染。

**未验证保留**：外接屏、睡眠恢复、长时闲置/持续负载、认证登录后课程内容、跨 Mac、公证。SPICE 门禁（仅 kali-arm64 单独启动）不变。SBOM 中 70 dylib 统一归属 qemu formula（暂存根布局所致），逐库真实来源见 `dylib-provenance-trace.json`。

分支 `codex/release-0.1.1-preview-20261010`、HEAD `42a3aa71…` 不变，全部改动未提交（61 项），无推送/发布，镜像库 03-软件未替换。本轮状态：`final-state`（四节点已停止）、`spice-state`（已停止）、交付目录、证据根 `ctflab-contentpack-fix-20261012/final-acceptance`；收口核验无运行实例。回归基线仍为 683 项 = 673 通过+10 跳过（本轮无源码变更未重跑）。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、当前状态第 18 节与 docs/verification-content-pack-final-20261012.md，核验 Git、交付 ZIP 哈希与进程。本地候选入口：`ctflab-contentpack-fix-20261012/app-r4/CTFLab.app`；交付包：`ctflab-final-delivery-20261012/CTFLab-0.1.1-contentpack-final-20261012-local.zip`。保留全部既有改动、资产与失败现场；不提交、不推送、不发布、不替换镜像库软件。

## 19. 当前交接：GitHub 源码同步（2026-10-12）

用户本轮明确授权提交并推送当前阶段的源码与文档，撤销先前对此次 Git 同步的禁止；不授权软件 Release、镜像/ZIP 上传或替换镜像库软件。同步目标 origin（zhangpu1211/ctf-lab）的 codex/release-0.1.1-preview-20261010 分支；不合并主分支，不强制推送。

提交范围包含导入性能/取消与候选确认、运行路径保护、Acfun 内置配置、内容包导入与失败恢复、GUI 和回归测试、阶段验证记录及协作说明。原镜像、运行状态、凭据和交付 ZIP 不入库。提交前已核对远端分支与本地基础 HEAD 一致，检查差异与凭据模式；完整回归在独立证据根 pre-push-regression.log 保存。历史各节的“未提交/未推送”保留为当时快照，当前实际提交/远端状态以 Git 查询为准。

本次推送前完整回归通过：683 项总数，673 通过、10 条件跳过；Python 语法与 Git 差异格式检查通过。没有启动桌面或用户虚拟机，软件 App/ZIP 内容未改写；许可证组件映射待办仍保留，源码推送不等于正式软件发布。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、当前状态第 19 节及最终验收记录，核对 Git 本地与 origin 分支、交付 ZIP 哈希和实际实例。用户已授权本次源码提交推送；本地 App/ZIP 仍未正式发布。保留资产与失败现场，不自动操作用户虚拟机或创建软件 Release。

## 20. 当前交接：GitHub 预发布与软件库归档（2026-10-12）

用户本轮明确授权创建 Release、清理这两天的中间文件、将最终 App 放入 CTFLab-Library，撤销历史对此次发布及中间产物清理的禁止。已发布 [v0.1.1-preview.20261012](https://github.com/zhangpu1211/ctf-lab/releases/tag/v0.1.1-preview.20261012)，含 ZIP/SHA-256/许可证溯源附件，来源提交 3375408；旧 Release 未覆盖。

当前 App：`/Users/pufei/Downloads/CTFLab-Library/03-软件/CTFLab-0.1.1-preview.20261012/CTFLab.app`；同目录 ZIP 与说明。发布整理恢复逐库 SBOM 和 55 个许可证目录、重新签名；运行实现与已验收 app-r4 一致。新树摘要 3ed94af7…，ZIP 7678b62c…；旧 app-r4/旧本地 ZIP 的 bdba1732…/5aaa76d3… 只用于历史。三份副本校验通过，软件库索引与 SHA256SUMS 更新；原镜像基盘未改动。详情见 [发布记录](release-v0.1.1-preview-20261012.md)。

160 项旧 App、独立测试磁盘/NVRAM/旧 ZIP 已可恢复移入废纸篓，未清空；日志、截图、脚本、JSON 与元数据快照保留。恢复清单 `/Users/pufei/Downloads/ctflab-release-20261012/cleanup-result.json`，历史状态不能再按磁盘路径直接运行。原始/已处理资产和 20261010 源运行时证据保留，现场无相关实例。没有操作桌面或用户虚拟机，没有合并主分支。

后续先读取本节、发布记录并现场核验软件库与 Git，不沿用旧 PID。未验证跨 Mac、外接屏、睡眠、长时负载等范围不变；预发布不升级为这些项目已通过。
