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

## 21. 当前交接：待处理镜像逐台适配（2026-10-13）

本轮18个原始OVA核对完成：Acfun来源与既有适配包一致，复用未重启；其余新增17个自包含内容包，16个完成启动/网络/初始服务验收，NoPort因原盘缺少 /etc/iptables/rules.v4 单列兼容候选，挑战完整性待确认。新增包位于 `/Users/pufei/Downloads/CTFLab-Library/02-已处理` 独立子目录，具体清单/地址/服务见库内 `已适配镜像目录-20261013.md`。在App中选择具体子目录导入，不递归安装整库。

每个新包两轮真实QEMU冷启动、登录提示截图、隔离实验网服务和正常关机再启动；制作后全新接收方安装再冷启动/正常停止，共51轮正式生命周期。逐项查看真实画面、逐包dist verify通过；18个原始OVA前后完整SHA一致。NoPort兼容部分同样完成上述流程，但不升级为完整可用。Smoke OVA与旧基盘虚拟内容不同，另存Smoke-OVA .56；派生副本补原名称hosts缓存才使原SmokePing主页HTTP200，外部监测未验证，访问端需映射smoke.dsz。Watcher Web入口为 .55:5000/login。

证据根 `/Users/pufei/Downloads/ctflab-image-adaptation-20261013`，事实索引 acceptance-summary.json、originals-final-hashes.json、逐台lifecycle/recipient-lifecycle日志/截图/绑定。详情见 [本轮验证记录](verification-image-adaptation-2026-10-13.md)。本轮只修正派生网络接口/Smoke名称缓存和受控硬件配置，不改账号、应用代码、漏洞或挑战内容。没有认证登录、解题、全站功能、长时负载、多节点同时运行、跨Mac结论；没有新增GUI点击或Kali桌面登录验收。

软件仍为库内已发布 v0.1.1-preview.20261012，包内app verify再次通过；本轮未修改运行实现或软件包。分支 codex/release-0.1.1-preview-20261010、HEAD 941db31114dbe811abadf46729295a72ec4bb30c。工作区只改.gitignore白名单、当前状态与新增验证记录，未提交/推送/发布。既有三节点清单/磁盘/NVRAM、旧Acfun和原OVA不改动；用户现有VM未操作，网络只在回环实验网。

空间紧张时，本轮scratch RAW和已停止状态基盘作可恢复压缩归档（虚拟内容compare/字节SHA通过后回收原表示）；恢复入口 scratch-archives/restore-index.json 与 closed-state-archives/restore-index.json。原盘/交付包/日志/截图/元数据全保留；历史测试状态需先恢复磁盘再使用，建议新状态安装内容包。用户随后明确确认NoPort保留原样并注明原盘问题，不补规则或改变挑战设计。用户授权永久删除上轮cleanup-result.json列出的160项，随后报告已手动清空废纸篓；本助手未执行删除，受macOS隐私限制未独立复核废纸篓。上轮160项的废纸篓恢复入口已失效，无需继续删除；本轮证据根内的可恢复压缩归档为独立资产。记录见 ctflab-release-20261012/permanent-cleanup-check-20261013.json。

本轮文档守卫94项=89通过+5条件跳过，git diff --check通过；库清单949项路径/大小核对无缺件。测试已正常结束，收口现场 final-process-snapshot.json 确认相关进程和本轮run.json均为空；后续操作需重新核验，不沿用旧PID。继续入口：先读AGENTS.md、本节与本轮验证记录，核对Git/软件/内容包清单，NoPort按用户确认保留原盘问题的候选状态；只有后续明确要求恢复挑战完整性时才补充来源资料。所有镜像功能边界仍以实际记录为准。

接续语：继续CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读AGENTS.md、当前状态第21节及 docs/verification-image-adaptation-2026-10-13.md，核对Git和实例；17个新单节点内容包在库内02-已处理，16个初始服务通过、NoPort原规则缺件候选、Acfun复用。证据根 ctflab-image-adaptation-20261013；部分历史测试磁盘已可恢复压缩归档。保留原盘/资产/已有改动，不自动提交、发布、删除或操作用户VM。

## 22. 当前交接：镜像说明与服务入口完善（2026-10-13）

用户选择完善镜像使用说明与服务入口。已更新17个新内容包的独立使用说明、包README、说明条目哈希/大小和SHA256SUMS；磁盘/profile/claims未变。补既有Acfun使用说明并更正其BIOS无NVRAM的旧模板提示；旧schema1清单/磁盘不变。新增库内 `02-已处理/镜像使用与服务入口.md`，汇总实际Web地址、节点ID、隔离网访问和单包说明链接；同步库README、目录索引、文件清单/SHA以及项目学生教程，更正旧文档“导入优化未打包”说法，当前软件是已发布0.1.1-preview.20261012。

使用路径：App选具体子目录导入，手动启动靶机和同状态Kali，从Kali浏览器访问。新包不含宿主端口映射，Mac不能直接访问这些实验网IP。Smoke-OVA .56需Kali内smoke.dsz映射，附curl --resolve临时GET与撤销说明；Watcher用 .55:5000/login；NoPort按用户选择保留原规则缺件候选；Acfun只引用历史SSH证据，不推测Web入口。未提供口令或解题步骤。

本轮证据根 `/Users/pufei/Downloads/ctflab-image-guides-20261013`：before保存原说明/清单；changes.json、verification-results.json、逐包verify日志。17包dist verify和旧Acfun分发verify通过；说明修改前后的磁盘/profile条目及claims逐项一致，文档相对链接可访问。库清单957项路径/大小无缺件；本轮没有启动虚拟机、操作桌面、修改App或重打软件。历史51轮验收仍属于上阶段，不能当成本轮新增。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 codex/release-0.1.1-preview-20261010、HEAD 941db31114dbe811abadf46729295a72ec4bb30c；保留前阶段.gitignore/状态/验收记录改动，并新增学生教程修改，未提交/推送/发布。NoPort完整性、认证登录、全站功能、长时负载、跨Mac范围未升级。本轮结束实例状态以 image-guides证据根process-snapshot.json现场读数为准，后续操作重新核验。

继续入口：先读AGENTS.md、本节与学生教程，再看库内服务入口表；按用户下一项明确任务推进，不自动启动用户VM、提交、发布或清理资产。

本阶段最终检查：文档守卫94项=89通过+5条件跳过，git diff --check通过，收口实际可执行文件核验无相关GUI/QEMU/显示/网络进程；没有新建测试实例。说明修改已更新本地清单，不表示GitHub软件或资产有新发布。

## 23. 当前交接：旧三节点结构、Smoke 同源与 NoPort 渗透复核（2026-10-13）

旧 Kali/Smoke/Basic 平铺在 `02-已处理` 是 schema 1 历史分发清单所决定；17 个新单靶机在独立目录是 schema 2 自包含内容包。没有迁移或改写旧分发。旧 `smoke` 与新 `smoke-ova` 的磁盘虚拟内容并非逐字节相同，但离线读取的 SmokePing 配置、Apache 配置、入口脚本、hosts 与 fstab 的 SHA-256 一致；同一服务的不同交付/profile，不应作为两道不同靶题。新盘仅对派生根分区副本回放 ext4 日志，原盘不动。详情见 [独立验证记录](verification-noport-smoke-2026-10-13.md)。

NoPort 在本轮全新独立状态 `ctflab-clarify-20261013/noport-state` 中实际启动；仅经回环实验网对 `.50` 受控访问，验证预存 `/1.php` 无认证命令执行，返回 `uid=101(apache)`，取得 Web 服务用户权限；源基盘与适配盘的虚拟内容 `qemu-img compare` 相同。没有证明 root、flag、预期解题链或原防火墙规则缺件对挑战难度的影响，因此仍按用户要求保留原盘问题和“兼容候选”定位。本轮 NoPort 已正常停止，`run.json` 清除，结束时原 QEMU PID 不在；后续重新核验实例绑定，不沿用该 PID。

证据根 `/Users/pufei/Downloads/ctflab-clarify-20261013`，含 Smoke 文件哈希对照、NoPort HTTP 响应、脱敏源码摘要与关机现场核验。正式项目目录、分支、HEAD 和已发布 App 仍为第 22 节所列；工作区保留既有未提交改动，只新增本验证记录与 `.gitignore` 文档白名单；未提交、推送、重打包、发布或改镜像库。后续若需判定 NoPort 完整通关，应明确验收目标，再在独立实例核验并保留原防火墙缺件说明。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、当前状态第 23 节及 docs/verification-noport-smoke-2026-10-13.md，现场核对 Git 和实例。旧三节点保持 schema 1 根目录分发；Smoke-OVA 与旧 Smoke 服务文件同源但分发配置不同；NoPort 已动态证实 apache 权限的无认证命令执行，整题通关未证实且原盘防火墙规则缺件。保留资产和已有改动，不自动操作用户虚拟机、提交、推送、发布或删除。

## 24. 当前交接：新三组原始镜像的受限适配（2026-10-13）

`01-待处理` 新增的三组目录实际包含四台机：Kioptrix Level 1、Stapler、Wintermute Straylight 与 Neuromancer。四份原始磁盘/OVA 已记录 SHA；Wintermute 两个 VMDK 转换后的 QCOW2 经 `qemu-img check`、与来源虚拟内容 compare 通过。只用已发布 0.1.1-preview.20261012 的包内 CLI 和新建状态；没有修改原始输入、已发布 App 或用户现有 VM。详情及原件哈希见 [本轮验证记录](verification-new-images-2026-10-13.md)，证据根 `/Users/pufei/Downloads/ctflab-new-three-20261013`。

**Stapler**：原 OVF 为 SATA/AHCI、PCNet32，来宾 DHCP 绑旧接口 `ens33`，导致初始登录画面虽出现却 ARP 不通。仅在派生盘将两个 `ens33` 改为 `eth0 `，原 VMDK 不动；修正后两次独立启动均到登录画面，FTP 21、SSH 22 TCP 与 HTTP 80（根路径 404）有真实协议响应。已做 schema 2 自包含包 `CTFLab-Library/02-已处理/Stapler-候选-20261013`，`dist verify` 与全新状态 `dist install`/启动/服务复验通过。第一次 `stop --graceful` 超时，接收实例第二次成功，关机稳定性未闭环，因此保留**候选**，不能作为已完整适配的课堂交付。

**Kioptrix**：原盘停在 `Starting sendmail`；派生盘只恢复 `/etc/hosts` 的 localhost 行后到 `kioptrix login:`，取得 DHCP ACK，但隔离探针 ARP 仍失败，正常关机超时；服务未证实，不制作内容包。**Wintermute**：Straylight 到 Debian 9 登录提示、Neuromancer 到 Ubuntu 16.04 登录提示且独立正常关机；单网卡状态均未得固定实验 IP。原题明确要求 Straylight 双网卡连接两个隔离网、Neuromancer 只在第二网、Kali 只在第一网；当前单实验网不能保持跳转设计，两盘仅留可复用转换候选，不交付为已适配内容包。没有认证登录、解题、长时负载或跨 Mac 验收。

同日库内 `01-待处理` 布局变为 `2.zip` 与三组提取目录；旧清单登记的18个散放 OVA 路径均已不存在。`2.zip` 含原 `1/basic_pentesting_2.ova`，该条目已流式读完并通过 ZIP CRC，SHA-256 为 `145a164df4c78dcecff670a13e9c8d07dd91237797c1a4b42017aefa4cca2661`；当前 `basic-pentesting-2-base.qcow2` 仍在 `02-已处理`。按现存文件重建本地库根清单与 SHA256SUMS，旧清单备份于本轮证据根；没有将缺失旧路径冒称仍在。镜像库说明与服务入口已标出 Stapler 候选、Kioptrix/Wintermute 未交付。

正式项目目录仍为 `/Users/pufei/Downloads/ctf-lab`；分支与已发布 App 沿用第 22 节，本轮未修改运行器代码或重打 App，未提交、推送、发布。保留前阶段未提交改动。本轮四份源哈希前后相同，库根 958 项校验通过，相关 QEMU 与 `run.json` 均为零；Stapler 接收状态已校验压缩归档，Kioptrix 两个停止测试状态仍保留，详情见验证记录与 `final-check.json`。后续不可沿用旧 PID。下一阶段优先定位 Kioptrix 的 sendmail/网络阻塞、确认 Stapler 正常关机稳定性；Wintermute 要在正式支持双隔离网并完整核验跳转后才可交付。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、当前状态第 24 节及 docs/verification-new-images-2026-10-13.md，核对 Git、镜像库和实例。Stapler 仅为兼容候选包；Kioptrix 服务未就绪；Wintermute 缺双网段，暂不发学生。原 Basic OVA 在 `01-待处理/2.zip` 内。保留原件、已有改动和证据，不自动停止用户 VM、删除、提交或发布。

## 25. 当前交接：Kioptrix 新候选与 Stapler 重启复验（2026-10-13）

本节覆盖第 24 节中“Kioptrix 未制包”的旧状态。详见 [新增镜像续验记录](verification-new-images-2026-10-13.md) 的“同日续验”与证据根 `/Users/pufei/Downloads/ctflab-new-three-20261013/followup`。正式项目目录 `/Users/pufei/Downloads/ctf-lab`，原盘、已发布 0.1.1-preview.20261012 App 与用户现有 VM 未修改。

Kioptrix 问题不是网卡驱动缺失：离线日志确认 PCNet/eth0；原来宾 DHCP 缓存仍写 `192.168.1.104`，造成交换机 ACK `.57` 而来宾 ARP 不可达。新派生盘在前轮 localhost 行修复基础上只删除两份旧 DHCP 租约；`qemu-img check/compare` 通过。制作状态两次、全新内容包接收状态一次真实冷启动均到 `kioptrix login:`，实验网 ARP、SSH 22、HTTP 80 的 Red Hat Apache 默认页 200、139/443 TCP 端口复现。现有 **兼容候选包** `CTFLab-Library/02-已处理/Kioptrix-候选-20261013` 已 `dist verify`、`dist install` 与接收状态真启动；尚未认证登录或解题。ACPI 请求 30 秒超时且接收状态 120 秒仍未自然退出，普通停止仅用于绑定核对后的独立测试实例，故不能标完整可用。

Stapler 的候选包另在全新状态两次冷启动到 `red login:`，ARP、FTP 220、SSH 标识与 HTTP 404 均复现。两次正常关机在运行器的 30 秒门槛超时，但来宾关机画面可见，第二次请求后 94.31 秒 QEMU 自然退出；旧轮一次 30 秒内成功。运行器尚未针对慢关机调整，用户仍会看到超时，因此包继续标**候选**。包内声明和说明已据实更新，基盘未改，`dist verify` 通过。Wintermute 原双网段跳转限制不变，未交付完整内容包。

本轮只修改候选包元数据、库说明索引及项目记录，没有运行器源码变更或新版 App 打包；不提交、推送、发布。库根 964 项 SHA256SUMS 全通过，四份原始输入 SHA 前后相同，相关 QEMU 与 `run.json` 均为零；两份当前候选包最终版在第三份独立状态真安装，未启动该状态。验收记录和 `followup/final-check.json` 为本轮证据，后续仍须现场复核。下一步若要把两包升为完整课堂交付，先解决 Kioptrix 关机与认证/题目功能验收，以及 Stapler 慢关机在 App 中的处理和业务内容验收；Wintermute 须支持原题两个隔离网。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、当前状态第 25 节及 docs/verification-new-images-2026-10-13.md 的续验部分，核对 Git、库根清单和实例。Kioptrix/Stapler 均是候选内容包，前者 ACPI 关机不响应，后者约 95 秒自然关机超过 App 30 秒门槛；Wintermute 仍缺双网段。保留原件、已有改动和证据，不自动停止用户 VM、删除、提交或发布。

## 26. 关机候选工作区复核（2026-10-14）

现场仍为正式目录 `/Users/pufei/Downloads/ctf-lab`、分支 `codex/release-0.1.1-preview-20261010`、HEAD `941db31`。保留全部原有未提交改动。库里已有 `Kioptrix-关机候选-20261013` 与 `Stapler-慢关机候选-20261013` 两份新增候选：profile 分别声明 Ctrl+Alt+Del/120 秒与 ACPI/120 秒；两包当前工作区 CLI 的 `dist verify --json` 均返回 `ok=true`。这些目录晚于第 25 节，尚未进入那一节的真实来宾验收结论；Kioptrix 包内说明记载先前独立测试，但本轮尚未重新验证其证据与启动路径。

工作区 `tools/ctflab.py` 已有逐镜像关机策略实现。本轮修复一处等待范围问题：`shutdown.timeout_seconds` 仅用于 `stop --graceful`；普通 `stop` 仍按全局短等待后回收，避免候选包的 120 秒配置使人工回收无端等待。对应生命周期测试加入长等待配置下的普通停止用例，并修正 CLI 帮助文字。

两包各在本轮独立新状态用工作区 CLI 完成 `dist install`、真实 QEMU `run`、`stop --graceful`；Kioptrix 的 Ctrl+Alt+Del 与 Stapler 的 ACPI 均返回正常停止，原 PID 消失、状态无运行实例或遗留登记。测试状态和派生盘保留在 `/Users/pufei/Downloads/ctflab-shutdown-20261014`。生命周期 12 项通过，完整本地回归退出码 0，`git diff --check` 通过。详见 [独立续验记录](verification-shutdown-candidates-2026-10-14.md)。未重打 App，因此已发布的 `0.1.1-preview.20261012` 不具备新策略；工作区版本 `0.1.2` 仍为未发布候选。Kioptrix/Stapler 继续标候选，认证登录、题目功能、长时稳定性和正式 App 包内验收仍待完成。未提交、推送或发布；原始输入与既有测试证据未修改。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、当前状态第 26 节和 `docs/verification-shutdown-candidates-2026-10-14.md`，现场核对 Git、镜像库与实例。两份 0.1.2 关机候选已在工作区 CLI 的独立状态完成一次真实正常停止，仍未完成认证/题目与 App 包内验收；保留原件、已有改动、测试状态和证据，不自动停止用户 VM、删除、提交或发布。

## 27. 第二次冷启动与 Stapler 显示误判修复（2026-10-14）

沿用第 26 节两份独立测试状态，Kioptrix、Stapler 各第二次真实冷启动并再次正常停止。Kioptrix 在 90 秒探测时 DHCP `.57` 已就绪但画面仍在 sendmail 阶段，稍后独立截图人工确认 `kioptrix login:`。Stapler 的 DHCP `.58` 和 `red login:` 画面均已取得；原探测因黑白画面只有两种颜色而错误报告无显示活动、退出码 1。工作区 `ppm_display_activity` 将颜色门槛从 4 调到 2，保留非黑像素比例门槛；对同一运行实例重测返回 `network_and_display_candidate`、退出码 0。屏幕专项 16 项通过，两机第二次 `stop --graceful` 均成功。详情及原失败/修复后证据见 [关机候选续验](verification-shutdown-candidates-2026-10-14.md) 的同日续验与 `/Users/pufei/Downloads/ctflab-shutdown-20261014`。

这是工作区 CLI 的测试，未重打或发布 App；两包仍是候选。本轮未重测 FTP/SSH/HTTP、认证登录、解题、长时稳定性或跨 Mac。Git 分支、HEAD 与原有未提交改动沿用第 26 节，本轮只追加显示判定代码、回归测试和状态/验证记录。结束时现场复核两份测试状态均无 `run.json`，相关 QEMU 进程均不存在；测试状态和派生盘仍保留，不能以后沿用本轮 PID。下一阶段可对候选包做独立服务与题目功能验收，或先将工作区实现做包内 App 验证；均不应将旧版 0.1.1 当成支持新关机策略。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、当前状态第 27 节及关机候选续验记录，现场核对 Git、镜像库和实例。两包在工作区 CLI 的独立状态均两次正常停止；Stapler 黑白登录画面的显示误判已修复并重测。保留原件、已有改动和证据，不自动操作用户 VM、删除、提交或发布。

## 28. Kioptrix、Stapler 本地运行兼容分发（2026-10-14）

完成两份 schema 2 内容包 `CTFLab-Library/02-已处理/Kioptrix-可分发-20261014`、`Stapler-可分发-20261014`，要求 >=0.1.2；配套 App/ZIP 位于 `03-软件/CTFLab-0.1.2-local-20261014`。旧软件、旧候选及原件保留，未变更外部发布渠道。基盘和运行 YAML 与既有关机候选逐字节相同，更新分发说明及独立验收记录，不再为修改历史验收字段触发同名配置冲突。

新构建 App 包内 CLI 在全新独立状态各完成两轮服务探测、正常停止和停止后冷启动。Kioptrix 两轮 SSH/HTTP 200/139/443 TCP；Stapler 两轮 FTP/SSH/HTTP 404。正常停止分别为 16.63/15.80 秒、94.72/16.42 秒。第一轮均人工核对 QMP 登录画面；第二轮 Kioptrix 截图仍为欢迎信息、Stapler 截图为空白，不以第二轮截图宣称登录通过。两份最终分发包另在独立配置/状态完成 verify/install；最终包安装状态未另外启动。

App 与交付副本 verify 通过，许可证完整，ad-hoc 未公证；专项 98 项通过，完整回归 687 项通过、跳过 10，退出 0。两份原 VMDK 哈希重算一致。仍未验证认证登录、完整解题、长时、跨 Mac、人工 GUI 或连续运行热重启；仅交付运行兼容，不标完整课堂业务验收。详见 [本轮分发验收](verification-distributable-images-2026-10-14.md)。

正式目录、分支和 HEAD 沿用第 27 节，已有改动保留，本轮只追加项目记录及本地库交付物；未提交、推送或外部发布。证据根 `/Users/pufei/Downloads/ctflab-distributable-20261014`；结束核对两份运行测试状态均无 run.json、四个测试 PID 均不存在；状态、派生盘和证据保留。后续不得沿用 PID。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、当前状态第 28 节和分发验收记录。Kioptrix/Stapler 已有要求 0.1.2 的本地运行兼容包及配套 App；两轮服务和正常停止通过，完整题目、第二轮登录显示、跨 Mac 和人工 GUI 尚未全验。保留原件、候选、既有改动与测试证据，不自动操作用户 VM、删除、提交或发布。本次目标：____。

第 28 节最终补充：ZIP 解压后的 app verify 通过。验收脚本直接调用包内 Python 曾改写三个已有缓存并生成 115 个额外缓存；已按原归档/清单恢复原字节，额外文件移至证据目录保留，补齐旁车 SHA 后重打 ZIP，完整签名及清单复核通过。库根最终 1801 项由一次完整检查的未变部分与新软件 813 项最终重验共同覆盖，首次检查退出 1 的修复现场保留，不冒称单次全库通过。

## 29. Wintermute 双隔离网静态设计（2026-10-14）

完成 [场景设计](ctflab-wintermute-scenario-design.md)，同步总体设计 Phase 5：三节点/双二层网清单契约、独立实例与 NIC 顺序、候选 DHCP 地址、无来宾管理 NIC/NAT/hostfwd 的策略、应通/禁通矩阵、场景锁和所有权、部分失败/停止超时恢复、整场景 generation 原子重置与分阶段实施门槛。Wintermute 是一台内部靶机的先导，不代替 Phase 5 的入口机加两台内部主机验收。

现场读取原 Wintermute-Lab-Setup.txt，确认原题双网卡/跳转关系；原说明允许 Kali 可选 NAT，本设计选离线。现场确认两份原 OVA 与 staging 候选基盘路径存在；未重算镜像哈希、解包、导入或启动。按当前源码确认单网固定 DHCP、附加管理网卡和 Kali 默认 NAT 的差距，未修改实现。原件、候选盘及既有改动保留。第 28 节的本地 0.1.2 App 与外部发布 0.1.1-preview 状态沿用历史记录，本轮没有软件验收或重新打包。

验证入口：`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests -p '*doc*' -q` 与 `git diff --check`。首次文档守卫 94 项、跳过 5 项，因上一阶段分发验收记录缺少历史快照声明失败；仅补声明，不改验收事实，修正后结果见本节收口补记。未运行完整回归、合成多网测试或真实 VM；方案、地址及超时均未标为运行验证事实。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `941db31`；本轮新增设计文档与白名单、追加本节、同步 Phase 5，并补历史记录声明。未提交、推送、发布、删除或操作用户 VM。本轮没有创建测试实例/状态目录/进程，不查询或接管用户实例；既有实例是否运行未核验，不将旧轮零进程结论当作当前结论。

下一步最小切片：实现场景清单校验与纯参数生成，覆盖独立命名空间、多 NIC 顺序及禁止管理网/NAT/映射的策略；暂不启动网络或 VM。其后再推进参数化 DHCP 与生命周期。真实 Wintermute 启动、停止、重置与解题验收需新阶段明确授权，不能沿用旧实例 PID。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、当前状态第 29 节和 `docs/ctflab-wintermute-scenario-design.md`，核对 Git 并保留已有改动。本次目标：实现场景清单校验和纯 QEMU 参数生成及对应静态测试；不启动网络/VM，不操作用户实例、不删除、不提交或发布。双网 DHCP、生命周期和 Wintermute 实机尚未实现或验收。

第 29 节收口补记：修正后文档守卫 94 项运行，OK、跳过 5 项，退出 0；`git diff --check` 通过。测试使用禁写字节码模式；没有运行虚拟机或修改镜像。所有设计仍为待实现/待实测。

## 30. Wintermute 场景清单与纯参数静态切片（2026-10-14）

完成 `tools/ctflab_scenario.py`：独立 schema 1、严格 JSON/字段/能力校验、三节点双网拓扑与 NIC PCI 顺序、资源上限、地址/租约/依赖校验、UUID 命名空间及稳定 MAC、独立 overlay/NVRAM 与 QMP/SPICE 参数。默认能力空即拒绝；必需能力集合仅描述契约，不宣称当前运行器支持编排。参数强制关闭默认网络，仅清单 NIC，无 NAT/hostfwd/管理 NIC/共享；SPICE 仅 UNIX 并关闭剪贴板、文件传输。未接入 CLI/GUI/内容包，保留单机实现及已有改动。

接口、白名单、合成清单与可信调用方责任见 [设计第 6 节](ctflab-wintermute-scenario-design.md)。资产哈希/硬件标记仅结构校验，不是 Wintermute 验证事实；checks 暂为空。实际目录权限/符号链接、固件和基盘核验、端口所有权及宿主路由检查留给后续准备入口。双网 DHCP、生命周期、事务重置、真实 QEMU 参数兼容性与隔离尚未实现/验收。

验证（2026-10-14）：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools:tools/tests python3 -m unittest test_ctflab_scenario test_ctflab_installer.InstallerCommandTests.test_clipboard_is_scoped_to_graphical_kali test_ctflab_installer.InstallerCommandTests.test_arm64_command_uses_hvf_pflash_and_input_devices test_ctflab_installer.InstallerCommandTests.test_kali_defaults_to_internet_but_targets_remain_isolated test_ctflab_status_docs.SpiceDisplayCliTests.test_default_command_stays_cocoa_without_spice -v`，10 项通过（6 项场景测试含多组负测，4 项现有单机静态兼容测试）。文档守卫、语法与 diff 检查见收口补记；未跑完整回归、合成网络或实机测试。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `941db31`。新增模块/测试、追加设计和状态，源码白名单新增模块；其余先前改动保留。未重新打包、删除用户资产、提交、推送或发布。本地 0.1.2 App/外部 0.1.1-preview 为第 28–29 节历史状态，本轮不验证或更新。本轮未创建网络/VM/测试运行状态，不查询或控制用户实例，既有 VM 状态未核验；测试仅合成数据和临时静态测试目录。

下一步：在新阶段明确范围后实现参数化双网 DHCP 与端点资源分配，先合成验证，再推进编排；真实 VM 测试需另行明确授权。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，读取 AGENTS.md、当前状态第 30 节、Wintermute 设计第 6 节和 `tools/ctflab_scenario.py`，核对 Git 并保留已有改动。静态清单/参数切片已完成，未接启动入口；本次目标：____。不要自动启动网络/VM、操作用户实例、删除资产、提交或发布。

第 30 节收口补记：文档守卫 `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests -p '*doc*' -q` 运行 94 项，OK、跳过 5 项；新增模块和测试以 `ast.parse` 检查语法通过（不生成字节码）；`git diff --check` 通过。结束时 Git 分支/HEAD 与阶段开始一致，新增模块/测试仍未跟踪，已有改动未提交。未创建任何网络或 VM 进程；没有查询既有实例 PID，不能据此认定宿主零实例。

## 31. 双网 DHCP 参数化与合成验证（2026-10-14）

完成 `tools/ctflab_network.py` 的实例级 DHCP 配置，按 subnet 生成掩码/广播/server ID，限定地址池、预约与登记客户端；保留单机默认网段和允许动态客户端的行为。动态池耗尽不越界，非法/错网请求不生成错误租约。场景模块新增纯 `network_server_specs`，将 UUID/NIC 派生 MAC 与逻辑预约变为 outer/inner 独立配置、server MAC 和代次状态路径；不启动或预约资源。服务循环使用可合成调用的 `dhcp_response`。网络状态新增 subnet/pool/登记策略与实例/网段/代次字段，继承监听 FD 仍限回环 IPv4 TCP。接口、协议限制及实际边界见 [设计第 7 节](ctflab-wintermute-scenario-design.md)。

验证入口（2026-10-14）：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools:tools/tests python3 -m unittest test_ctflab_scenario_dhcp test_ctflab_network test_ctflab_scenario test_ctflab_network_report test_ctflab_installer.InstallerCommandTests.test_clipboard_is_scoped_to_graphical_kali test_ctflab_installer.InstallerCommandTests.test_arm64_command_uses_hvf_pflash_and_input_devices test_ctflab_installer.InstallerCommandTests.test_kali_defaults_to_internet_but_targets_remain_isolated test_ctflab_status_docs.SpiceDisplayCliTests.test_default_command_stays_cocoa_without_spice -q`，33 项通过。新增 11 项双网/地址/异常帧/服务循环/端口与 FD 测试，含多组子测试；其余为现有网络、清单、网络报告和单机静态兼容检查。初次扩大验证 33 项中 FD 测试 2 项因本机 `SO_ACCEPTCONN` 查询返回协议不可用失败；去掉该不可移植查询、保留 TCP/端点校验并调整负测后重跑全部通过。失败测试进程已结束，重跑 FD 测试关闭全部 socket。

本轮没有启动 VM、网络子进程或接触用户实例。端口竞争测试只在当前测试进程临时绑定回环随机端口，FD 测试无服务等待循环；模拟客户端测试用 mock 替代 socket/select/send 和状态写入。既有网络测试使用临时文件及 socketpair。结束后没有本轮持久运行实例、状态目录或进程；用户既有实例状态未查询，不能据此认定宿主零实例。未修改磁盘、原件、用户状态或凭据。

正式目录 `/Users/pufei/Downloads/ctf-lab`；分支 `codex/release-0.1.1-preview-20261010`、HEAD `941db31`，保留此前所有改动。本轮修改网络模块/场景模块，新增 `tools/tests/test_ctflab_scenario_dhcp.py`，追加设计/状态文档；未删除用户资产、提交、推送、打包或发布。第 28–30 节本地 0.1.2 App/外部 0.1.1-preview 状态为历史沿用，本轮未更新或验证。

未完成：真实双交换机/QEMU 抓包隔离矩阵、场景端点资源分配与所有权/宿主路由校验、编排/恢复/事务重置、GUI/CLI 场景入口、Wintermute 实机与跨 Mac 验收。DHCP 协议暂未实现 NAK/DECLINE/RELEASE/租约到期；场景固定预约不依赖动态回收。下一阶段先实现资源准备及网络就绪的合成故障验证，再推进生命周期；真实 VM 启停需另行明确授权。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，读取 AGENTS.md、当前状态第 31 节、Wintermute 设计第 6–7 节及场景/网络模块，现场核对 Git，保留已有改动。清单、纯 QEMU 参数和参数化 DHCP 合成验证已完成，场景运行入口未接入。本次目标：____；不要自动启动 VM、操作用户实例、删除资产、提交或发布。

第 31 节收口补记：文档守卫 `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests -p '*doc*' -q` 运行 94 项，OK、跳过 5 项；网络模块、场景模块和新增测试通过 `ast.parse` 语法检查，无字节码生成；`git diff --check` 通过。结束时再次核对分支/HEAD 仍为上述值；没有本轮后台服务或 VM，受控 socket 全部由测试关闭，既有实例未查询/操作。完整本地回归、真实来宾、跨 Mac 和发布验收未运行。

## 32. 场景网络资源准备与就绪合成故障验证（2026-10-14）

新增 `tools/ctflab_scenario_resources.py`：明确路由快照校验、私有目录/链接/归属检查、非阻塞资源锁、既有记录拒绝覆盖、双回环监听 FD 持有与失败释放；增加双网就绪门槛，严格核对实例/代次/端点/DHCP 配置并依赖可信进程身份核验，单网成功不放行，超时保留现场。网络状态增加 server_mac/static_leases。接口与限制见 [设计第 8 节](ctflab-wintermute-scenario-design.md)。保留此前改动，未接入单机入口或生命周期。

验证（2026-10-14）：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools:tools/tests python3 -m unittest test_ctflab_scenario_resources test_ctflab_scenario_dhcp test_ctflab_network test_ctflab_scenario test_ctflab_network_report -q`，36 项通过。新增 7 项合成准备/故障测试，包含多组负测、真实回环端口竞争、第二监听器失败释放、锁竞争、单网超时保留、真实 DHCPServer 状态写入。首轮 30 项中新增 6 项因临时目录经过 macOS /var 符号链接被拒绝而失败；夹具改为规范真实路径，原拒绝策略保留，重跑通过。测试仅使用自身临时目录/FD（退出清理自身夹具），不访问或删除用户资产。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `941db31`；本轮未启动 VM/网络子进程、操作用户实例、提交、推送、打包或发布，既有 App 版本沿用第 28–31 节历史信息，本轮未核验。没有本轮后台实例；测试 FD 均关闭，用户既有实例未查询，不能宣称宿主零实例。

未完成：完整资产/固件/overlay/NVRAM/socket 准备、路由现场采集与新鲜度、进程身份生产核验、全局锁到场景锁交接、跨实例 MAC 资源登记、生命周期/恢复/事务重置、真实双交换机和 Wintermute 验收。当前锁持有至显式 close，不能直接用于长时间编排等待；路径检查尚无同 UID 恶意并发替换防护。下一阶段优先完善可信准备调用链及锁交接，再实施服务生命周期合成故障验证；实机操作需要明确授权。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、状态第 32 节和 Wintermute 设计第 8 节，核对 Git，保留已有改动。下一阶段完善资产准备、可信路由/进程绑定与锁交接及合成故障验证；不要自动启动 VM、操作用户实例、删除资产、提交或发布。

第 32 节收口补记：文档守卫 `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests -p '*doc*' -q` 运行 94 项，通过、跳过 5 项；本轮网络模块、资源模块和新增测试经 `ast.parse` 语法检查通过，`git diff --check` 通过。结束核对分支/HEAD 未变；完整本地回归、真实来宾、跨设备、发布验收未运行。没有本轮持久后台资源；未查询或操作用户既有实例。

## 33. 场景资产准备、可信绑定与锁交接（2026-10-14）

在第 32 节独立模块上新增 `prepare_scenario_resources`：显式基盘/UEFI code/vars 路径与哈希核验、独立 QCOW2 检查、准备空间门槛、三节点 overlay/backing 校验、私有 NVRAM/socket 目录及代次 `prepared.json` 绑定记录。原始资产只读；全部节点现场预检，现存目录拒绝覆盖；部分失败保留派生现场，只释放本次 FD/锁。目录逐层核对私有权限。完成后保留实例场景锁并释放全局资源锁，不在双网就绪等待期间占用全局锁。现有网络单独准备接口仍保留原锁行为，未接入单机或场景启动入口。

新增本机数字 IPv4 路由只读采集、严格缩写解析与单调时钟新鲜度门槛；资产准备前后各核对一次，新增冲突闭锁。`OwnedNetworkProcesses` 绑定可信调用方持有的实际启动对象/argv，通过所属代次记录的新鲜读取及 `poll()` 支撑双网门槛；不以状态文件 PID 授权控制，不提供重开后的恢复。详细契约及限制见 [Wintermute 设计第 8.1 节](ctflab-wintermute-scenario-design.md)。

验证（2026-10-14）：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools:tools/tests python3 -m unittest test_ctflab_scenario_resources test_ctflab_scenario_dhcp test_ctflab_network test_ctflab_scenario test_ctflab_network_report -q`，44 项通过。新增资产/路由/进程/锁交接与故障覆盖；真实 `qemu-img` 对三份 1 MiB 合成基盘创建 overlay 并 `check` 通过，基盘保持 0400，仅验证派生格式，不验证来宾启动。路由采集在本机只读执行，新鲜度校验通过（75 条，不在文档保存具体宿主路由）。文档守卫 `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests -p '*doc*' -q`：94 项通过、跳过 5 项。首轮新增夹具超 UNIX socket 长度而失败，改为短临时目录后通过；拆分测试类时一次遗漏夹具方法导致失败，补齐后通过。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `941db31`；已有改动保留。本轮仅新增/完善场景资源模块、对应测试与设计/状态文档，没有 VM 或网络服务子进程，没有查询/操作用户实例、删除用户资产、提交、推送、打包或发布。`qemu-img` 和只读 netstat 子进程均已结束；临时测试夹具/FD 由测试自身清理，没有本轮后台资源。App 版本沿用第 28–32 节历史信息，本轮未核验，不能宣称宿主零实例。

未完成：GUI/CLI 与服务 argv/继承 FD 的正式启动链、跨实例显式 MAC 登记、硬件/来源许可验证、同 UID 恶意并发路径替换防护、journal/进程重开恢复、停止/事务重置、真实双交换机/隔离矩阵与 Wintermute 来宾验收。空间检查不等于磁盘容量预约；路由快照不等于持续隔离；`prepared.json` 不等于网络运行或可用内容包。下一步在不启动 VM 的范围实现跨实例资源登记与服务生命周期/恢复的合成验证；任何真实 VM/用户实例操作需新阶段授权。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、状态第 33 节和 Wintermute 设计第 8.1 节，核对 Git 并保留已有改动。资产准备、可信观察与全局锁到场景锁交接已有独立接口和合成验证；下一步完善跨实例资源登记及服务生命周期/恢复的合成验证。不要自动启动 VM、操作用户实例、删除资产、提交或发布。

第 33 节收口核验：最终目录逐层校验改动及文档更新后，相关 44 项与文档守卫 94 项（跳过 5）再次通过；资源模块和测试经 `ast.parse` 通过，`git diff --check` 通过。分支/HEAD 未变。完整全仓回归、真实来宾、人工桌面、跨设备和发布验收未运行。

## 34. 跨实例资源登记与服务生命周期/恢复合成验证（2026-10-14）

完成本阶段剩余实现：新增 `ctflab_scenario_registry`，在完整准备的全局→场景锁内登记六个 MAC、两端口和状态/socket 路径；冲突、未释放预约、损坏/半行记录与旧未登记场景现场闭锁。部分准备失败保留预约；显式观察全部三节点/双网停止后，按全局→场景锁追加释放历史，不删除资产。`prepared.json` 增加预约操作身份。旧低层网络准备仍不登记，不能直接当作发布入口。

新增 `ctflab_scenario_services`：从白名单配置生成服务 argv/pass_fds；显式注入启动器/身份观察器，outer→inner 启动及总截止时间、双网就绪、健康失败降级、节点停止前置条件、inner→outer 正常停止、超时保留且只继续等待。spawn/stop 意图先写私有追加日志，日志失败、不明启动窗口或归属变化不自动继续。只读恢复核对完整预约资源、准备摘要/代次、PID/argv/启动身份，并在观察结束重读记录；PID 复用或记录变化拒绝恢复结果，不接管/补启/发信号。

验证（2026-10-14）：相关 60 项通过，含新增 16 项登记/生命周期/恢复合成故障验证及既有真实 qemu-img 合成派生盘检查；文档守卫 94 项通过、跳过 5 项；5 个相关文件 `ast.parse` 通过，`git diff --check` 通过。实际命令、故障过程、范围和限制见 [本轮验证记录](verification-scenario-services-2026-10-14.md)，接口见 [Wintermute 设计第 8.2 节](ctflab-wintermute-scenario-design.md)。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `941db31`；保留既有改动，本轮未启动 VM/真实网络服务、操作/查询用户实例、删除用户资产、提交、推送、打包或发布。新增 `.gitignore` 仅放行两个源码模块和本轮验证文档。服务及恢复进程观察全部使用合成对象；本轮 qemu-img 子进程已结束、临时 FD/夹具由测试清理，没有本轮后台实例或持久测试资源。App 版本沿用历史记录，本轮未核验；不宣称宿主零实例。

未完成：GUI/CLI 接线、生产启动身份/停止证明/恢复 inspect、真实服务 FD 继承、锁下恢复接管、VM 生命周期与 QMP、整场景事务重置、跨状态根/单机资源协调、同 UID 恶意并发路径替换防护、真实双网隔离与 Wintermute 业务/跨 Mac 验收。观察等级不等于来宾停止或场景可用；没有默认真实 spawn，也没有自动解除异常预约。完整全仓回归与发布验收未运行。下一阶段可先完善节点生命周期与整场景重置事务的合成验证；真实服务/VM 启停和用户实例操作需另行明确授权。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，读取 AGENTS.md、状态第 34 节、Wintermute 设计第 8.2 节及本轮服务验证记录，核对 Git 并保留已有改动。资源登记和双网服务生命周期/只读恢复已有独立合成验证；下一步完善节点生命周期与整场景重置事务的合成验证。不要自动启动 VM、操作用户实例、删除资产、提交或发布。

第 34 节收口核验：新增验证文档首次触发历史快照标记守卫，补齐标记后文档守卫重跑 94 项通过、跳过 5 项；相关实现最终 60 项通过。5 个相关 Python 文件语法与最终 `git diff --check` 通过；新增源码/测试/验证文档未被 Git 忽略。结束核对分支/HEAD 未变；无本轮真实服务或 VM，未操作用户实例，未提交、打包或发布。

## 35. 三节点生命周期与派生资产重置事务合成验证（2026-10-14）

新增节点会话：双网就绪后 Neuromancer→Straylight→Kali 顺序创建，白名单 argv、实际启动对象/身份和 QMP/overlay 绑定；失败/失联仅降级、保留 pending 窗口与双网。关机按 Kali→Straylight→Neuromancer，逐节点截止时间，超时不继续停止后续节点/网络、不强杀，重试只等待；日志先于请求写入。提供只读节点身份恢复审计。全部启动、QMP/关机/身份接口明确注入，没有默认真实 VM 控制。

新增停止态资产重置事务：显式初始活动代次，来源哈希/独立 QCOW2/空间/backing/check 验证；新代次三盘与 NVRAM、完整性清单、空网络目录准备完成后单次原子切换 active-generation 指针。提交前失败保留旧活动代次；提交后日志中断以指针和完整性核验为准。可显式补记提交或记 aborted 后另选新代次；旧/部分失败资产不删除。资源登记识别已提交/放弃的资产历史，旧代次与未接续重置资产的准备入口闭锁。

验证（2026-10-14）：相关 83 项通过，含本轮新增 23 项合成/派生格式验证；文档守卫 94 项通过、跳过 5 项；5 个相关 Python 文件 ast.parse、diff 空白和新增文件白名单检查通过。真实 qemu-img 仅操作三份 1 MiB 合成基盘，重置后 overlay check 通过，基盘 0400/哈希不变。详情见 [本轮验证记录](verification-scenario-nodes-reset-2026-10-14.md)及 [Wintermute 设计第 8.3 节](ctflab-wintermute-scenario-design.md)。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `941db31`；保留既有改动。未启动真实 VM/网络服务、查询或控制用户实例、删除用户资产、提交、推送、打包或发布。合成进程不是宿主进程；本轮 qemu-img 子进程已结束、临时夹具与 FD 自行清理，没有本轮后台资源。实际 App 版本未复核，不能声称宿主零实例。

重要未完成：重置的 `reset-assets-ready` 尚未接入新的网络/socket/运行预约及启动链；旧预约保留，不能称正式可启动的整场景重置已完成。下一阶段优先实现“停止旧预约→重新预约新代次→复用完整性已核验资产→服务/节点启动”的接续链及合成故障验证，禁止绕过活动指针。生产 QMP/启动身份/停止证明、恢复接管、GUI/CLI、真实 FD 继承和持续隔离、Wintermute 业务/跨 Mac/发布验收继续未完成；完整全仓回归未运行。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、状态第 35 节、Wintermute 设计第 8.3 节和节点/重置验证记录，核对 Git 并保留已有改动。完善 reset-ready 资产到新代次网络/socket/运行预约及服务/节点启动的接续链与合成故障验证。不要自动启动真实 VM/服务、操作用户实例、删除资产、提交或发布。

## 36. 重置接续链、生产运行时与场景 CLI/GUI 入口（2026-10-14）

完成第 35 节遗留的接续链：`resume_reset_resources` 把已提交 reset-ready 资产接入"停止旧预约→新代次预约→复用已核验资产→服务/节点启动"，并覆盖"指针已切换但服务未启动"的崩溃重接；孤儿预约由 `recover_reset_continuation` 显式释放。服务会话新增活动指针门槛，孤儿准备记录不能绕过激活启动；registry 拆出锁内核供接续链复用。新增 `ctflab_scenario_runtime`：只读 ps 身份采集（包装脚本前缀、僵尸、`(进程名)` 瞬时退化、稳定窗）、QMP 查询/ACPI 关机、停止证明（指针切换后按代次记录自洽校验）、`stop_recovered_nodes/services` 锁内接管正常停止（意图先写日志、不重复发送、超时 stop-pending、stopping 可重试）。CLI 新增 `scenario` 六个子命令（独立状态根、/tmp 短 socket 根）；`start` 以新会话启动子进程并落盘身份后退出，"节点就绪"仅指进程与 QMP 已核验。GUI 增加场景面板（状态解码、确认后正常停止、显式收口/释放孤儿），不提供准备/启动/重置。设计文档新增 8.4 节与第 9/10 节（独立实机与交付验收方案，仅方案未执行）。

验证（2026-10-14）：场景相关 10 模块 115 项连续 3 轮通过（接续链 13、运行时 13、CLI 端到端 5 项为真实 main() + 合成 qemu 桩 + 真实 DHCP 服务子进程 + 真实 ps/QMP 身份链）；完整本地回归 790 项通过、跳过 10；GUI 核心 217 项检查、`swiftc -typecheck` 通过；12 个相关 Python 文件 ast.parse、`git diff --check`、文档守卫见收口补记。故障过程见 [本轮验证记录](verification-scenario-resume-runtime-2026-10-14.md)，接口契约见 [Wintermute 设计 8.4](ctflab-wintermute-scenario-design.md)。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `941db31`；保留既有改动。新增 `ctflab_scenario_runtime.py` 与 3 个测试模块并加入白名单；未提交、推送、打包或发布。本地 0.1.2 工作区与外部 0.1.1-preview 为历史状态，本轮未重新打包。本轮没有真实 VM/真实网络服务：CLI 端到端的子进程是测试自身的合成桩与 DHCP 服务（继承测试自身回环 FD），结束前按日志记录 PID 兜底终止；未查询或操作用户既有实例，不宣称宿主零实例。

重要未完成：Wintermute 真实基盘从未启动——`scenario prepare/start` 生产路径只在合成资产上验证；真实来宾地址、目标服务、应通/禁通矩阵、跳转解题、两轮冷启动与跨 Mac/内容包/发布验收全部未做（方案见设计第 9/10 节，执行需新授权）。进程身份存在信号发送前 TOCTOU 窗口；停止证明不能排除未记录进程；GUI 不覆盖准备/启动/重置。完整功能仍不可称为"可启动的 Wintermute 靶场"。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、当前状态第 36 节、Wintermute 设计 8.4 与第 9 节、本轮验证记录，核对 Git 并保留已有改动。合成链路已闭环；下一步需要明确授权后按设计第 9 节做 Wintermute 独立实机验收（独立状态根与派生盘，不接管用户 Kali），或先做 GUI/CLI 细节打磨。不要自动启动真实 VM/网络服务、操作用户实例、删除资产、提交或发布。

第 36 节收口补记：文档守卫 94 项通过、跳过 5 项；`git diff --check` 通过；12 个相关 Python 文件 ast.parse 无字节码；GUI 核心检查 217 项与 `swiftc -typecheck` 通过。结束核对分支 `codex/release-0.1.1-preview-20261010`、HEAD `941db31` 未变；工作区改动与新增文件未提交。测试遗留的 6 个合成 DHCP 子进程（本轮调试产生，状态路径均在本轮 /var/folders 临时目录下）已按 PID 清理并复核为零；未查询或操作用户既有实例，未删除用户资产。

## 37. Wintermute 实机验收只读预检与入口细节修复（2026-10-14）

按设计第 9 节完成只读预检（未启动任何 VM/服务、未解包 OVA、未修改镜像、未创建场景状态根、未操作用户实例）：现场重算两份 Wintermute 候选基盘、两份原 OVA、原题说明、库内 Kali aarch64 候选与 vars、`edk2-aarch64-code.fd` 的 SHA-256；`qemu-img info` 确认三份基盘均为独立 QCOW2；OVF 只读提取 NIC 证据——Straylight 双卡 82543GC+82540EM 与原题一致，Neuromancer OVF 含 NAT slot0（不得采用）与 host-only slot1，清单只挂 inner 单卡时来宾能否起址列为执行时门槛；当前宿主路由与 192.168.243/244 零冲突；QEMU 11.1.0 工具链在位；发现数据卷仅剩约 7.0 GiB 的空间风险（执行时须监控或另指定状态根）。全部数字见 [预检记录](verification-wintermute-acceptance-preflight-2026-10-14.md)，设计第 9 节已补预检补记。场景清单仍未物化，实机验收待当次明确授权。

入口打磨：发现并修复场景根推导 bug——scenario 子解析器给 `--state-root` 预设默认值，压过全局 `--state-dir` 推导，GUI 覆盖状态目录时场景命令会找错状态根；改为子解析器默认 None、由 `scenario_state_roots` 统一推导。新增两项测试：场景状态根/socket 根随 `--state-dir` 且与单机 profile/images 子树互不包含（命名空间隔离防绕过），以及 `--instance` 显式选择与未知实例报错。

验证（2026-10-14）：CLI 场景测试 7 项通过（含新增 2 项）；完整本地回归 792 项通过、跳过 10（既有保留项）；无真实 VM/网络服务，无新增持久进程。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `941db31`；保留既有改动，未提交、推送、打包或发布。本轮新增预检记录文档并加入白名单，修改 ctflab.py 场景参数默认与场景 CLI 测试；哈希重算的 shasum、qemu-img info、tar -xOf 子进程均已结束。

重要未完成与上节一致：实机验收执行（两轮冷启动、显示、地址、服务、矩阵、跳转、重置、重开恢复）、场景清单物化、Neuromancer 单卡起址确认、e1000 模型映射确认、空间问题解决；GUI 仍不覆盖准备/启动/重置；停止后同代次重启（保留来宾状态的 restart）未实现，当前停止后再运行走 reset 新代次路径（教学场景每次重置本就是主流程，restart 作为后续可选项）。实机验收必须由用户明确授权后按设计第 9 节与预检记录执行。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、当前状态第 37 节、设计第 9 节及预检补记、预检记录文档，核对 Git 并保留已有改动。预检已就绪；本次目标：____（如"授权执行第 9 节实机验收"或"继续入口/文档打磨"）；不要自动启动真实 VM/网络服务、操作用户实例、删除资产、提交、推送、打包或发布；执行实机验收需在本次消息中明确授权并确认状态根位置与空间。

## 38. 证据根瘦身维护与 Wintermute 候选清单提案（2026-10-14）

用户授权的三轮清理（均删除前核对引用与打开句柄，删除后复核资产完好）：① 本轮测试/调试中间件——临时状态根、stub 调试图、GUI 测试二进制、`__pycache__`、`.DS_Store`；② 无引用派生中间件——clarify 轮 smoke raw/root ×4（比对结论已录 `smoke-file-comparison.json`，与该轮 `archive-index.json` 自身的"哈希入档后删派生件"惯例一致）、new-three followup 的 kioptrix raw/分区 img ×8（文档零引用，结论在 JSON）；③ 适配证据根磁盘副本——17 台机器的 adapted/distribution/state/recipient 全部磁盘副本（删除前对 17/17 台做 `distribution.qcow2`↔`02-已处理/-base.qcow2` 逐字节比较全部一致，pane1 state 副本另经 `qemu-img compare` 内容级确认 identical）。保留：`noport/source-state` 与 `smoke-ova/source-state`（源 OVA 已在库整理中消失，此为原始源盘最后现存副本，作溯源）、`scratch-archives/` 与 `closed-state-archives/`（归档证据本体）、全部 JSON/日志/说明/截图、库与 staging 资产、App Support 用户数据。适配证据根 126 GB→44 GB，数据卷可用 13→103 GiB，预检记录的 7 GiB 空间风险解除。被删文件的历史验收结论不受影响（其文档记录与 JSON 均在）；仅 state/recipient 现场原件不再留存，后续如需复核只能按库内包重新安装验证。

入口/文档打磨：Wintermute 候选清单已物化为提案——用预检真实哈希起草、通过 `parse_manifest` 严格校验，嵌入 [Wintermute 设计 9.1 节](ctflab-wintermute-scenario-design.md)（含执行命令序列；`hardware_verified=false`，NIC `e1000` 对 82540EM 精确、对 82543GC 为最近似，冷启动以来宾命名确认前不得宣称原卡型复现）。新增防腐化测试：从设计文档提取内嵌 JSON 逐块跑当前 schema 校验，文档随实现演进而失配会直接红。

验证（2026-10-14）：`test_ctflab_scenario` 7 项通过（含新守卫）；清理三轮各自删除前后做了引用 grep、句柄检查与资产哈希抽查（Wintermute staging 哈希与预检记录一致、库内盘完好）；文档守卫与空白检查见收口补记。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `941db31`；保留既有改动，未提交、推送、打包或发布。本轮修改设计文档（9.1 节）与场景测试文件，未改任何生产代码。清理只动 Downloads 下证据根与临时目录，未触碰项目工作区、库资产、staging、App Support。

重要未完成与第 37 节一致：实机验收执行（两轮冷启动、显示、地址、服务、矩阵、跳转、重置、重开恢复）待当次明确授权与状态根指定；Neuromancer 单卡起址、e1000 卡型映射按 9.1 节执行时确认；GUI 不覆盖准备/启动/重置；同代次 restart 未实现。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、当前状态第 38 节、Wintermute 设计 9/9.1 节与预检记录，核对 Git 并保留已有改动。候选清单与预检均就绪；本次目标：____。若授权执行第 9 节实机验收，请在本次消息明确授权、按 9.1 节命令序列指定状态根并确认不接管用户 Kali；否则继续入口/文档打磨。不要自动启动真实 VM/网络服务、操作用户实例、删除资产、提交、推送、打包或发布。

## 39. Wintermute 实机验收第一轮（2026-10-14，用户授权执行）

用户当次明确授权后，按设计第 9 节完成 Wintermute 三节点双隔离网的首轮实机验收。证据根 `/Users/pufei/Downloads/ctflab-wintermute-acceptance-20261014`（状态根在其 `scenario-state/`，实例 `59fcf32b-f9f4-4729-9300-91df15654328`，gen1→2→3），Kali 用库内副本派生，未接管用户实例；代理 fake-IP 路由由用户关闭后解除路由门阻塞。

**真机达成**：三台真实 VM 两轮冷启动与 ACPI 正常停止全部一次通过（Kali hvf + Straylight/Neuromancer TCG，进程与 QMP 核验后 `nodes-ready`；停止序列 Kali→Straylight→Neuromancer 后双网 SIGTERM，进程归零）；显示证据：Kali GUI 登录界面、`straylight login:`（Debian 9）、`neuromancer login:`（Ubuntu 16.04），主机名自证；Kali 两轮均经 DHCP 预约获得 `192.168.243.10`（实例 MAC 稳定，代次租约全新——重置语义实证）；结构性隔离核验：接线为 Kali 仅 outer、Neuromancer 仅 inner、Straylight 双宿，argv 无 hostfwd/user/tap，L2 学习表 outer 仅 Kali、inner 为空；整场景重置两次提交、旧代次保留；恢复/接管路径真实执行 3 次（含首次失败后对孤儿 DHCP 服务的 SIGTERM 接管）。

**过程中发现并修复**：① 默认 socket 根 `/tmp` 符号链接被状态路径守卫拒绝（解析真实路径修复；失败 prepare 会留下未登记空实例目录，已确认后清除）；② 本机全部可用 QEMU 中 x86_64 仅 App 运行时带 SPICE、aarch64 全部无 SPICE → 新增 `scenario start` SPICE 预检与 headless 模式（Kali headless + QMP 截图作为记录在案的显示偏差）；③ `audit_reset` 不识别"提交后已接续"（指针 reset-ready→同代次 prepared）误报 recovery-required（补 committed-observed 分支 + 守卫测试）。

**门槛结果**：两轮冷启动/停止 ✅、显示/登录 ✅（含 headless 偏差）、整场景重置 ✅、重开恢复 ✅；来宾地址 ⚠️（Kali ✅，x86 双机网卡启动未激活，控制台登录凭据未提供而阻塞）；目标服务/应通禁通来宾级探测/跳转解题 ⛔（依赖 x86 起址）；结构性矩阵证据 ✅。完整明细见证据根 `evidence/README.md` 与全部日志/截图。

**未完成**：来宾内验证链（x86 起址→服务→矩阵→e1000 卡型确认→跳转解题）待来宾控制台凭据；跨 Mac、内容包、发布未做。Wintermute 距"可交付"仍差来宾内验证与解题确认，不能宣称整题适配通过。

验证（2026-10-14）：完整本地回归 794 项通过、跳过 10；场景组 65 项通过（含本轮新增 headless/审计守卫）；文档守卫与空白检查见收口补记。本轮生产修复：ctflab.py（socket 根解析、SPICE 预检、headless 传递）、ctflab_scenario.py（include_spice）、ctflab_scenario_nodes.py（headless_architectures）、ctflab_scenario_reset.py（审计分支）；均已入工作区未提交。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支与 HEAD 未变；未提交、推送、打包或发布。状态根保留供复核；结束时段无任何 qemu/服务进程。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、当前状态第 39 节、`/Users/pufei/Downloads/ctflab-wintermute-acceptance-20261014/evidence/README.md`，核对 Git 并保留改动。真机骨架验证已完成；本次目标：____（如提供 Straylight/Neuromancer 控制台凭据以完成来宾内验证，或继续其他模块）。凭据仅用于 QMP 键入，不入任何文档；不要自动启动 VM、操作用户实例、删除资产、提交或发布。

## 40. Wintermute 实机验收第二轮：来宾起址门槛通过（2026-10-14 续）

用户再次授权执行后，完成来宾起址门槛：公开检索证实 Wintermute 无公开控制台口令（原题入口为 Straylight Tomcat admin:admin 利用链），转走设计允许的"配置调整仅写派生盘/基盘副本并记录差异"路径。离线读取派生盘定位根因——BIOS+pc 机型下 Debian 9/Ubuntu 16.04 将网卡命名为 **ens5/ens8**（内核日志 `ens8: renamed from eth1` 实证），而盘内 `/etc/network/interfaces` 写 `enp0s3`/`enp0s8`，名称错位致接口全部未激活。修复：两份 staging 基盘**副本**做等长字节替换（`enp0s3→"ens5  "`、`enp0s8→"ens8  "`，配置行上下文过滤 + 含日志/历史副本，before/after SHA 入 `base-ens-patch.json`；原始基盘未动；e2fsprogs 位图校验和告警经对照证实为原始 base 既有状态、内核两轮容忍启动）。中途一次在 v2 代次 overlay 上补丁被重置完整性清单正确拦截（SHA 不匹配），促使修复进基盘谱系——与 Kioptrix/Stapler 同型。

**结果**：v3 实例 `d5505db2-6531-4027-ac84-35598b2fd4c5` 四块网卡全部按清单预约起址（Kali outer=.10、Straylight outer=.20/inner=.20、Neuromancer inner=.30；MAC/网段/地址程序化全匹配）；QMP `info network` 接线核验一致；`scenario stop` 一次通过、进程归零。至此两轮冷启动/停止、显示或登录、来宾地址、结构性矩阵、整场景重置、重开恢复六项门槛完成；目标服务探测、来宾级应通/禁通正负测、跳转解题待后续（Kali 控制台口令不在档；可经 SPICE 连接 x86 双机人工进行）。v2 现场保留作守卫拦截证据；两个状态根的预约处于活跃登记，销毁环境前需显式 release（CLI 尚无 release 子命令，已知缺口）。

生产修复（本轮新增，未提交）：scenario 默认 socket 根解析 `/tmp` 符号链接；`scenario start` 新增 SPICE 预检与 headless 模式（`qemu_command include_spice` + 会话 `headless_architectures`，严格布尔校验）；`audit_reset` 识别"提交后已接续"分支。全部带测试（场景组 65 项+完整回归 794 项通过；文档守卫/空白/语法见收口补记）。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `941db31`；未提交、推送、打包或发布。验收证据根 `/Users/pufei/Downloads/ctflab-wintermute-acceptance-20261014`（README 含两轮全程、v3 为当前有效实例）；三个状态根（主/v2/v3）与基盘副本均保留；结束时段无任何 qemu/服务进程；原始 staging 基盘与库资产未动。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、当前状态第 40 节、`/Users/pufei/Downloads/ctflab-wintermute-acceptance-20261014/evidence/README.md`，核对 Git 并保留改动。来宾起址已通；本次目标：____（如提供 Kali 口令做来宾级矩阵与目标服务探测，或经 SPICE 人工登录 x86 双机，或收口清理验收环境）。不要自动启动 VM、操作用户实例、删除资产、提交、推送、打包或发布。

## 41. Wintermute 实机验收第三轮：目标服务与隔离矩阵通过（2026-10-14 续）

用户继续授权后完成剩余可自动化门槛。复用 Kioptrix/Stapler 同款用户态 L2 探针（参数化源 IP 与目标网段守卫后为 `probe_v3.py`），在 v3 gen2（重置后新代次，四卡再次全部按清单起址，基盘补丁跨重置持续生效）执行：**目标服务**——Kali→Straylight outer :80 得 `HTTP/1.1 200 OK`、探针→Neuromancer inner :8080 得 `HTTP/1.1 200`（Secure Remote Access 门户）、→Kali :22 得 `SSH-2.0-OpenSSH_10.3p1`，四路同网段 ARP 全部解析到正确 MAC，服务拓扑与公开 writeup 一致；**禁通负测**——outer 交换机对 inner 网段目标 ARP 零响应（隔离核心证据）、不存在地址无冒充应答；三层证据（接线 argv + L2 学习表 + 负测）一致证明 Kali 与 Neuromancer 无共享路径。结束时段三台 VM 于 gen2 正常停止（本轮第三次 ACPI 成功），进程归零，截图/租约/探针 JSON 落档。

至此 Wintermute 场景全部可自动化实机门槛通过（两轮冷启动停止/显示/四卡起址/目标服务/隔离矩阵/整场景重置/重开恢复）。剩余为人工任务与交付阶段：跳转解题验证（原题利用链 Tomcat admin:admin→提权→pivot，不属自动化范围）、跨 Mac、内容包化、发布，各需对应授权。当前现场：`v3/scenario-state` gen2 已停止、预约活跃登记；`v2` 保留守卫拦截证据；销毁验收环境前需显式 release（CLI 缺 release 子命令为已知缺口，可作下一迭代项）。

本轮无生产代码变更（探针为证据根内验收脚本）；验证命令与结果全部记录于验收证据根 `/Users/pufei/Downloads/ctflab-wintermute-acceptance-20261014/evidence/README.md`（项目外路径，不入库）。正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `941db31`；未提交、推送、打包或发布；原始 staging 基盘与库资产未动；结束时段无任何 qemu/服务进程。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、当前状态第 41 节、`/Users/pufei/Downloads/ctflab-wintermute-acceptance-20261014/evidence/README.md`，核对 Git 并保留改动。全部可自动化实机门槛已通过；本次目标：____（如：设计并实现 scenario release 子命令后清理验收环境；或人工跳转解题验证；或进入跨 Mac/内容包交付阶段）。不要自动启动 VM、操作用户实例、删除资产（含验收状态根与补丁基盘副本）、提交、推送、打包或发布。

## 42. scenario release 显式释放入口实现（2026-10-14 续，纯代码切片）

按第 41 节接续语的候选目标一实施其可执行部分：设计并实现 `scenario release` 子命令，补齐"停止不释放预约、销毁验收状态根前缺显式释放入口"的已知缺口。**本轮未在任何真实状态根上执行 release，未启动任何 VM/服务，未删除任何资产**——对验收现场（`v3/scenario-state` gen2 已停止、预约活跃；`v2` 守卫证据保留）的 release 执行与环境清理属后续独立授权。

实现（复用既有内核，无新底层语义）：`cmd_scenario_release`（tools/ctflab.py）解析状态根与实例后读取活跃预约——无活跃预约幂等成功（exit 0）；同一实例多项活跃预约（正常流程不可能）拒绝并引导恢复；恰一项时经 `release_reservation`（登记层既有内核）以生产 `stopped_observer` 现场停止证明（三节点+双网络全部 stopped，非持久化字样）为门槛追加 release 事件。运行中释放被停止证明拒绝（exit 2，引导 stop/status）；登记只追加历史，不删除资产、日志或活动指针；释放后代次进登记历史，`reset --new-generation`/重新 `prepare` 可开新周期（含"旧预约已释放"的接续分支）；只 prepare 未 start 的实例按"从未启动"证明释放。`scenario status` 在观测全停且预约活跃时新增 release 建议入口；GUI 面板不覆盖 release（走 CLI，维持既有边界）。设计文档同步：新增 8.5 节、8.4 节子命令列表补 release、9.1 节执行序列补"stop → release → 用户显式处置状态根"销毁顺序与证据归档提醒。

验证（2026-10-14，全部合成，无真实 VM/网络服务）：`test_ctflab_scenario_cli.py` 新增 3 项——运行中被停止证明拒绝且预约保持活跃、停止后释放并核对幂等/资产与指针保留/status 建议；释放→reset→start→stop 跨代次闭环；未启动实例释放后重新 prepare。场景组 `python3 -m unittest discover -s tools/tests -p "test_ctflab_scenario*.py"` 110 项通过；完整回归 `python3 -m unittest discover -s tools/tests` 797 项通过、跳过 10（既有保留项，上轮 794+3）；`python3 -m py_compile` 覆盖改动文件通过。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `941db31`；本轮改动：`tools/ctflab.py`（release 命令/子解析器/status 建议）、`tools/tests/test_ctflab_scenario_cli.py`、`docs/ctflab-wintermute-scenario-design.md`，叠加此前全部未提交改动一并保留；未提交、推送、打包或发布。验收证据根与三个状态根（主/v2/v3）、staging 基盘与补丁基盘副本均未触碰；结束时段无任何 qemu/服务进程（本轮未创建）。

未完成与下一步：① 验收环境处置待授权——`v3` 先 `scenario stop`（若再启动过）再 `scenario release`（幂等可复核），随后归档/删除状态根需用户显式授权与确认（v2 作为守卫拦截证据的去留由用户决定）；② 人工跳转解题验证（需启动 VM 与登录授权）；③ 跨 Mac、内容包化与发布验收（需打包/发布授权）。release 的生产路径仅在合成链路验证，未在真实状态根执行过。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、当前状态第 42 节、设计 8.5/9.1 节、`/Users/pufei/Downloads/ctflab-wintermute-acceptance-20261014/evidence/README.md`，核对 Git 并保留改动。release 子命令已实现并合成验证；本次目标：____（候选：授权在验收状态根执行 scenario release 并清理验收环境；人工跳转解题验证；进入跨 Mac/内容包交付阶段）。不要自动启动 VM、操作用户实例、删除资产（含验收状态根与补丁基盘副本）、提交、推送、打包或发布；执行 release 与环境清理需在本次消息明确授权。

## 43. 验收状态根 release 执行完成（2026-10-14 续，用户授权执行）

用户在三个候选目标中明确选择"授权执行 release（仅释放预约）"。用第 42 节实现的 `scenario release` 对验收证据根三个状态根完成首次生产执行并程序化复核：主 `scenario-state`（59fcf32b/gen3）、`v3`（d5505db2/gen2）、`v2`（25e2e7b3/gen1，从未启动即释放）各释放一项预约（token 分别 380d98c9…/a471d846…/ebb2423a…，各 6 MAC、2 端口、8 路径）；三根活跃预约归零，代次目录与活动指针完整保留，三份登记账本均为完整 reserve→release 配对（8/6/4 事件），未删除任何文件、未产生任何进程。v2 的 reset"资产 SHA-256 不匹配"守卫证据现场不受影响。执行记录与证据见验收根 `evidence/README.md` 第四轮小节及 `release-*.log`、`status-after-release.json`（项目外路径，不入库）。

过程中发现并修正一处提示瑕疵：`--state-root` 传相对路径被场景路径守卫拒绝（要求绝对路径，属既有防线），但 release 的错误包装把该失败误导为"先 stop 核验停止状态"——已改为中性的"可先 scenario status 核验状态"（tools/ctflab.py 一行）；CLI 测试组 10 项复跑通过。

验收环境至此满足销毁前置（预约全释放）。**未完成与下一步**：① 删除性清理待单独授权——三个状态根的归档/删除（v2 守卫证据现场去留由用户决定）、补丁基盘副本处置；② 人工跳转解题验证（需 VM 启动授权；注意三个根现已无活跃预约，解题前需 `scenario reset --new-generation N` 重新准备代次或恢复现场另议）；③ 跨 Mac、内容包化与发布验收（需打包/发布授权）。

验证（2026-10-14）：release 执行与复核如上（真实状态根，用户授权范围内）；`python3 -m unittest discover -s tools/tests -p "test_ctflab_scenario_cli.py"` 10 项通过。release 功能仍在工作区未提交、未打包，验收根用它执行的记录已注明此事实。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `941db31`；本轮改动仅 `tools/ctflab.py` 一行提示措辞与 `docs/ctflab-current-status.md` 本节，叠加既有未提交改动保留；未提交、推送、打包或发布。验收证据根三状态根与补丁基盘副本全部保留；结束时段无任何 qemu/服务进程（release 不启动进程）。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、当前状态第 43 节、`/Users/pufei/Downloads/ctflab-wintermute-acceptance-20261014/evidence/README.md` 第四轮小节，核对 Git 并保留改动。三个验收状态根预约已全部释放、现场完整保留；本次目标：____（候选：授权清理验收环境——删除/归档状态根与补丁基盘副本；人工跳转解题验证——需 VM 启动与重新准备代次授权；进入跨 Mac/内容包交付阶段）。不要自动启动 VM、操作用户实例、删除资产（含验收状态根与补丁基盘副本）、提交、推送、打包或发布；清理与新阶段各需本次消息明确授权。

## 44. 场景内容包 schema 3：make/verify/install 全链路（2026-10-14 续，交付阶段准备切片）

用户指示"继续"后推进交付阶段中无需授权的部分（清理与跳转解题仍各需单独授权）：按设计第 10 节③实现 Wintermute 场景的内容包承载——新增 **schema 3 场景内容包**（schema 2 保持 profile 包语义不变，两种角色白名单互不混用，旧运行器按白名单拒绝）。本轮全部合成验证：未构建真实 Wintermute 包，未打包、发布、启动 VM 或触碰任何既有资产/状态根。

实现：`ctflab_dist.py` 新增 `parse_scenario_pack`（场景清单全文严格校验 + 交叉校验：`scenario_id` 与 `pack.scenario.id` 一致；**随包基盘登记 SHA-256 必须与场景清单声明一致**；固件 vars 只能挂 UEFI 节点；claims 只能挂场景 id）、`make_scenario_pack`（清单必带、基盘/固件/说明按需随包；引用式分发合法）、`_scenario_pack_summary` 与场景包 README；`parse_pack` 与 schema 3 共用元数据/条目名校验（消息不变）。`ctflab.py` 新增 `dist make-scenario-pack` 子命令（免状态目录快路径）、`dist verify` 场景摘要输出、`dist install` 场景分支与 `LabManager._install_scenario_pack`：整体校验通过后复制场景文件到 `content-packs/<id>/scenario/`（只读、同名不同哈希拒绝、重装幂等、回滚只删本轮创建），写 schema 3 安装记录，输出可直接粘贴的 `scenario prepare` 命令（随包项给绝对路径，未随包资产与 edk2 code 固件给占位符）；不创建 profile、不注册镜像、不自动准备场景。GUI 未改动（场景包摘要对 GUI 保持 `nodes: []` 形状兼容）。取舍：跨 Mac 基盘为多 GB 文件，安装复制使状态目录占用翻倍（与 schema 2"导入后不依赖原包路径"同边界）。

验证（2026-10-14，全部合成，字节级基盘/vars 模板）：新增 `tools/tests/test_ctflab_scenario_pack.py` 8 项——制作/校验往返与摘要、随包基盘哈希不匹配拒绝、清单外资产/非 UEFI 节点拒绝、引用式包未随包资产提示、篡改/缺失文件检出、解析层负测（角色混用/嵌套路径/场景 id 不一致/claims 越界/运行器版本约束）、CLI 端到端（make→verify→install→幂等重装含 prepare 命令断言）、篡改包与安装目录冲突拒绝。既有内容包 33 项、分发 18 项通过（`parse_pack` 重构无回归）；完整回归 `python3 -m unittest discover -s tools/tests` **805 项通过、跳过 10**（上轮 797+8）；py_compile 覆盖改动文件；文档守卫随全量回归通过。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `941db31`；本轮改动：`tools/ctflab_dist.py`、`tools/ctflab.py`、新增 `tools/tests/test_ctflab_scenario_pack.py`、设计文档 10.1 节与本文档；叠加既有未提交改动保留；未提交、推送、打包或发布。三个验收状态根（已释放预约）与补丁基盘副本未触碰；无新增运行进程。

未完成与下一步：① 真实 Wintermute 场景包构建（三基盘+vars，需当次授权与许可等级确认；引用式包可先行试制）；② 跨 Mac 实测（第二台 Mac 的 app + 内容包 + 最低版本声明全链路）；③ 交付阶段其余项（GUI 全流程验收、最低软件版本门槛、发布）；④ 验收环境清理与人工跳转解题仍各需单独授权。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、当前状态第 44 节、设计 10.1 节，核对 Git（分支 codex/release-0.1.1-preview-20261010、HEAD 941db31）并保留全部未提交改动。schema 3 场景内容包已实现并合成验证；本次目标：____（候选：构建真实 Wintermute 场景包并本机 dist install 验证；跨 Mac 交付实测；验收环境清理或人工跳转解题——后两者各需对应授权）。不要自动启动 VM、操作用户实例、删除资产（含验收状态根与补丁基盘副本）、提交、推送、打包或发布；构建真实包、清理与跳转解题各需本次消息明确授权。

## 45. 真实 Wintermute 场景包构建/安装验证；VM 实测被代理路由阻塞（2026-10-14 续）

用户当次授权"启动 VM 后测试无误就发包、提交、推送、发布、打包"。本轮完成：**发包**——真实场景内容包已构建进库 `CTFLab-Library/02-已处理/Wintermute-可分发-20261014`（pack-id `wintermute-lab` v1.0.0；wintermute.json + kali 7.54 GB/straylight 2.68 GB/neuromancer 2.84 GB + kali vars 64 MB，共约 13.1 GB；资产哈希与验收记录逐项核对：kali=库内基盘 974a319f…，x86 双机=验收根 v3 enspatched 副本 4d8fdb4d…/915ab98b…）；**安装验证**——全新状态目录 `ctflab-wintermute-pack-20261014/app-state` 的 `dist install` 整体校验+复制+schema 3 记录+prepare 命令输出全部通过。发布渠道预检：origin GitHub `zhangpu1211/ctf-lab`、gh 已登录、现有 Latest=v0.1.1-preview.20261010、工作区版本 0.1.2、App 运行时与 edk2 固件双源可用。

**阻塞**：`scenario prepare`（资产用安装副本、固件 code 用 App 运行时 edk2）被路由门拒绝——宿主代理 fake-IP 路由 `128.0/1 → 198.18.0.1（utun4）`覆盖 192.168.243/244，与实机验收第一轮同根因，需用户关闭代理（曾发询问与约 3 分钟路由复查未解除）。失败发生在任何状态写入之前，零残留。按用户前置条件"测试无误"，**提交、推送、打包、发布本轮均未执行**；用户未确认前不得把包级验证冒充 VM 实测通过。详见 [本轮验证记录](verification-wintermute-pack-20261014.md)。

验证（2026-10-14）：包构建/安装链路如上（真实资产，实测）；VM 未启动（路由门拦截属设计行为）；无生产代码变更（本轮仅使用第 44 节实现）。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `941db31`，未提交改动 40 项（第 44 节后新增本验证记录）；未提交、推送、打包或发布。内容包在库内（自用分发，未公开上传）；安装副本 13 GB 保留在 `ctflab-wintermute-pack-20261014/app-state` 供下轮复用；验收状态根与补丁基盘副本未触碰；无运行进程；数据卷剩约 54 GiB。

未完成与下一步：① **等用户关闭代理后继续 VM 实测**（prepare→start→status→stop→release，命令见验证记录"复现/继续入口"），无误后按既有授权执行提交→推送→打包（`app build --version 0.1.2` + zip + sha256）→gh 发布（tag 建议 `v0.1.2-preview.20261014`，Pre-release，附 zip 资产与说明）；② 跨 Mac 实测；③ 验收环境清理与人工跳转解题各需单独授权。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、当前状态第 45 节、`docs/verification-wintermute-pack-20261014.md`，核对 Git 并保留全部未提交改动。真实场景包已进库、安装链路已验证；本次目标：____（默认：代理已关闭，继续 VM 实测 prepare→start→stop→release，无误后执行提交/推送/打包/发布；或其他目标）。若 VM 实测仍被路由门拦截，先请用户关闭代理；不要操作用户实例、删除资产、或在前置条件未满足时提交/推送/发布。

## 46. VM 实测通过、提交与打包完成；网络中断后的发布链已于 2026-10-15 完成（原验收 2026-10-14）

用户关闭代理后 VM 实测**全部通过**（详见 [验证记录](verification-wintermute-pack-20261014.md)）：安装副本作资产的 prepare→start 三节点就绪→四卡 DHCP 全部按清单起址→QMP 截图（straylight/neuromancer 登录提示）→服务探测（kali :22 SSH-2.0-OpenSSH_10.3p1、straylight :80 HTTP 200、neuromancer :8080 HTTP 200，与 v3 验收指纹一致；首轮探针失败系脚本默认网段外源 IP 被来宾过滤，改网段内源 IP 后全通，非缺陷）→跨网 ARP 负测零响应→stop 全停→release 释放、进程归零。实测状态根 `ctflab-wintermute-pack-20261014/app-state/scenario-state`（实例 3b5a03a1 gen1，预约已释放，现场保留）。

发布链执行至打包：①发布门槛完整回归 805 项通过、跳过 10（一次文档守卫失败为验证记录缺"历史验收快照"头，补齐后复跑全绿）；②提交 `da0f963`（40 文件、+7845 行，工作区干净）；③**app 打包完成**——首轮构建 782 文件比上一构建少 23（全部为 spice-gtk 相关），补 `--spice-client /opt/homebrew/bin/spicy` 重建后 805 文件与上一构建一致，`app verify` 通过（许可完整、ad-hoc 签名、未公证）；ZIP `CTFLab-0.1.2-preview-macos-arm64.zip`（51 MB，sha256 `163fb08b9985961b1854db426baf757f1570ee640304c1d15a3b5b50d24505d5`）与 `.sha256` 在 `/Users/pufei/Downloads/ctflab-release-0.1.2-preview-20261014/`；④本地 tag `v0.1.2-preview.20261014` 已建在 `da0f963`。

**2026-10-15 发布收口**：本轮先核对正式目录、Git 与上述验收记录，现场确认仅本节未提交；未重跑已完成的 VM 验收、完整回归及 App 构建。`git ls-remote` 探通后，分支由 `941db31` 推送至 `da0f963`，标签 `v0.1.2-preview.20261014` 同步推送且仍固定在 `da0f963`。此前网络失败已解除。

GitHub [v0.1.2 预发布](https://github.com/zhangpu1211/ctf-lab/releases/tag/v0.1.2-preview.20261014) 已创建，标题为“CTFLab v0.1.2 预览版（Wintermute 场景运行器与场景内容包）”。通过 GitHub API 复核 `draft=false`、`prerelease=true`；仅附 ZIP（53,753,388 字节）及 `.sha256`（164 字节）两个资产，均为 uploaded。服务端 ZIP digest、本地构建文件、镜像库副本均为 `163fb08b9985961b1854db426baf757f1570ee640304c1d15a3b5b50d24505d5`。发布说明明确 Wintermute 实机验收与内容包实测通过，以及跨 Mac、GUI 场景面板人工验收、公证未做；13.1 GB 内容包没有上传公开渠道。

镜像库 `/Users/pufei/Downloads/CTFLab-Library/03-软件/` 已按现有根目录 ZIP 惯例新增 `CTFLab-0.1.2-preview-macos-arm64.zip` 与原始 `.sha256`，更新 `最新版.md` 指向本次预发布，并保留旧版。校验文件保留原构建目录的绝对路径，入口文档给出在库内直接计算哈希的命令，避免误将原路径当作库内副本。

本轮验证：`git ls-remote` 复核分支/标签；`shasum -a 256` 复核构建与库内 ZIP；GitHub API 复核发布类型、资产大小、上传状态及服务端 digest；`git diff --check` 检查文档。源码与发布二进制没有修改，未重复 805 项回归（其结果属于上一验收轮）。本节作为独立 docs 提交推送；发布标签仍指向实际构建来源 `da0f963`，不因状态文档提交移动。

实例与边界：按实际进程命令行核对，未发现绑定 `/Users/pufei/Downloads/ctflab-wintermute-pack-20261014` 的 QEMU 或场景网络服务进程；本轮未启动、停止或重置 VM。实测状态根、验收状态根、补丁基盘副本和库内内容包原样保留。后续仍待跨 Mac、GUI 场景面板人工验收；公证需 Keychain Profile 与另行授权，内容包公开再分发许可未核验。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 `AGENTS.md`、当前状态第 46 节及 `docs/verification-wintermute-pack-20261014.md`，现场核对 Git、发布与实例。v0.1.2-preview.20261014 发布链已完成，发布标签/二进制来源是 da0f963，后续 docs 提交只记录收口。下一阶段目标需另行明确；不要自动重做验收、启动或停止 VM、删除资产、公开上传内容包或执行公证。

## 47. 发布 App GUI 验收发现阻断（2026-10-15）

按用户“跑一下 GUI 验收”执行已发布 0.1.2 App 的原生桌面验收，结果**未通过**。主窗口、节点列表和 Kali 详情可展示；Wintermute 初次状态读取与点击刷新均报 `ModuleNotFoundError: No module named 'ctflab_scenario'`。App 与发布 ZIP 都缺少场景模块，根因是 `ctflab_package.RELEASE_TOOL_FILES` 未纳入相关依赖。错误横幅显示时面板仍提示“没有场景实例”，不能视为空状态成功。证据与未验收项见 [GUI 验收记录](verification-gui-20261015.md)。

本轮未启动/停止/重置 VM、删除资产或修改默认节点；App 保持打开。未修复源码、重新打包、修改公开资产、提交或推送；当前 HEAD 仍为 `ce90ff4`，新增本轮验收文档与本节待提交。既有 v0.1.2 预发布仍在线，GUI 场景功能存在上述已确认阻断；此前源码实机验收与包内容实测不能证明发布 App 包含完整依赖。

下一步：修复发布依赖清单与错误/空状态展示，补打包目录级验证，重建候选并复验 GUI；修正版发布另按用户指示。接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、状态第 47 节和 `docs/verification-gui-20261015.md`，核对实际 Git 与 App；本次 GUI 验收失败现场保留，不自动操作 VM、删除资产或替换公开发布。

## 48. GUI 发布依赖与失败提示修复，候选空状态/故障恢复复验通过（2026-10-15）

按用户“继续”修复第 47 节问题：`tools/ctflab_package.py` 补齐 7 个场景依赖，`gui/GuiApp.swift` 区分场景读取失败与空列表、失败时禁用操作、成功刷新清理对应旧错误。增加从复制后打包目录执行场景 CLI/导入的回归；`.gitignore` 纳入本轮验收记录。

App/GUI/package 三组测试分别 62/25/37 项通过；新候选构建 812 个登记文件，app verify 通过。原生桌面完成候选首次读取、刷新、空状态，以及独立故障副本的错误提示/操作禁用/恢复刷新验证，均通过。完整命令、日志与范围见 [GUI 验收记录](verification-gui-20261015.md)。没有重跑全量 805 项或启动真实 VM；运行态停止确认/取消、停止后刷新、事务恢复仍未验收，不能标为完整 GUI 验收通过。

候选 `/Users/pufei/Downloads/ctflab-gui-fix-20261015/app/CTFLab.app`（0.1.2，本地修复候选，ad-hoc、未公证）保持打开；故障副本 fault/ 已恢复模块并退出，不用于分发。默认节点仅只读查询，无 VM 启停/重置/删除。原发布目录、镜像库和 GitHub v0.1.2-preview.20261014 未替换，因此公开旧包仍有第 47 节缺陷。

正式目录与分支未变，HEAD `ce90ff4`；本轮代码、测试、白名单及文档尚未提交/推送，没有新 ZIP/标签/发布。下一步应在独立实例补验 GUI 运行态操作，再按用户指示做修正版交付。接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、状态第 48 节和 GUI 验收记录，核对现有 diff 与候选；不要使用 fault/ 分发，不自动替换公开资产或操作用户 VM。

第 48 节收口补记：文档守卫 94 项通过、跳过 5（补齐验收快照固定措辞后复跑），`git diff --check` 通过；结束时现场只见候选 GUI，没有 QEMU/场景网络服务。

## 49. GUI 运行态验收与修正版发布进行中（2026-10-15）

用户授权完成 GUI 运行态验收、提交打包发布修正版及镜像库更新。发布前完整回归本轮实际重跑 806 项通过、跳过 10，日志 `ctflab-gui-fix-20261015/full-regression.log`。用户关闭 TUN 后现场路由复核通过。

独立实机测试根 `/Users/pufei/Downloads/ctflab-gui-runtime-20261015`，状态目录 `app-state`，实例 `f9d11feb-185f-4132-80d8-21f28ef688fc` gen1；仅用旧包已安装资产作只读来源，prepare/start 成功，三节点+双网存活、四卡租约完整，见 prepare/start 日志与 `status-running.json`。此为测试进行中状态，操作前必须重验 PID/命令/QMP 身份，不得据本记录直接发信号。

GUI 启动接口不能传隔离状态环境，桌面工具拒绝控制 Terminal；已请求用户手工运行 `CTFLAB_GUI_STATE_DIR=/Users/pufei/Downloads/ctflab-gui-runtime-20261015/app-state /Users/pufei/Downloads/ctflab-gui-fix-20261015/app/CTFLab.app/Contents/MacOS/CTFLabGUI`。默认 GUI 已退出。等待窗口打开后验证停止取消、正常停止、事务收口与孤儿释放；尚未执行受控故障脚本 `fault-steps.py`。当前不得标为完成。

待发布目录 `/Users/pufei/Downloads/ctflab-release-0.1.2-preview-20261015`，候选仍为 0.1.2（修正版日期标签计划 v0.1.2-preview.20261015），尚未提交/推送/建标签/发布，也未更新镜像库软件入口。跨 Mac、公证与人工解题仍不在本轮完成结果中。

第 49 节进行中补记：用户已打开隔离 GUI；发现中文 ps lstart 导致进程身份摘要漂移，已在源码固定三处 ps 采集的 C locale，新增跨语言回归（运行时模块 15 项通过）及实机中英文对照（均 live）。停止确认取消已验证不影响三节点+双网。正在重建 app-r2 和重跑完整回归，未发布；最初日期 ZIP 仅为待淘汰候选，不得发布。

第 49 节运行态验收收口：r2 GUI 已通过运行状态、停止确认取消、正常 ACPI 停止及自动刷新，三节点/双网已全停。对独立实例受控注入指针切换失败，GUI 重置事务收口返回 aborted，GUI 孤儿预约释放返回 orphan-released，账本活跃预约归零。实例 gen1/失败gen2/reset-ready gen3 现场全部保留，无本轮 QEMU/网络进程；r2 GUI 已正常退出。详见 GUI 验收记录。

事务收口后重复建议收口的提示缺陷已在源码修正并补 CLI 故障恢复回归；最终构建输出 app-final，r2 ZIP 不再分发。807 项完整回归属于 locale 修复阶段，最终提示修复后回归正在进行，完成后再记录最终结果并提交/推送/发布。跨 Mac、公证及人工解题未做。

第 49 节最终发布门槛：最终源码完整回归 808 项通过、跳过 10（230.098 秒），app-final 构建/verify 与实际 ZIP 解压随包 CLI 通过；默认 GUI 正常空状态，GUI 源码与运行态验收 r2 完全一致。最终 ZIP 53,797,125 字节，SHA256 `7ffd66736b8970483e53af7990f7d93f33d4568366b18cb4884283b8e056a5fd`。默认 GUI 保持打开；独立测试实例全停、零预约，gen3 reset-ready 故障现场保留。准备将本轮修复与验收文档提交为修正版构建来源，并创建日期标签/预发布；完成结果另记第 50 节。

## 50. GUI 运行态验收与 v0.1.2 日期修正版发布完成（2026-10-15）

本阶段目标已完成：本机 GUI 运行态停止确认/取消、正常 ACPI 停止与自动刷新、受控故障下事务收口/孤儿预约释放均通过；修复了场景漏打包、读取失败误报空状态、中文 ps 身份摘要漂移及收口后重复提示。最终源码完整回归 808 项通过、跳过10；文档守卫94项通过、跳过5；app-final 构建/verify、默认原生 GUI、实际 ZIP 解压随包场景 CLI 通过。GUI 运行态在 r2 执行，final 仅另改只读提示，GUI 源码/停止恢复执行逻辑不变，并有新增 CLI 中断恢复回归。

构建来源提交 `3cc1339`，正式分支仍为 `codex/release-0.1.1-preview-20261010`，已推送；标签 `v0.1.2-preview.20261015` 固定在该提交并已推送。公开 [2026-10-15 预览修正版](https://github.com/zhangpu1211/ctf-lab/releases/tag/v0.1.2-preview.20261015) 已创建且非草稿、为预发布，两个资产均 uploaded；旧 20261014 发布与资产保留，已追加缺陷/替代说明。本节及验收记录的发布结果随后作为 docs 提交推送，不移动标签。发布门槛细节见 [GUI 验收记录](verification-gui-20261015.md)。

最终产物 `/Users/pufei/Downloads/ctflab-release-0.1.2-preview-20261015/app-final/CTFLab.app` 与根目录 `CTFLab-0.1.2-preview.20261015-macos-arm64.zip`、`.sha256`；ZIP SHA256 `7ffd66736b8970483e53af7990f7d93f33d4568366b18cb4884283b8e056a5fd`，53,797,125 字节，校验文件112字节（相对文件名，可直接 shasum -c）。GitHub 服务端 digest、本地和镜像库副本均核对一致；包内19个入口/依赖/GUI文件与构建提交一致。03-软件 两个新资产已入库、最新版.md 已更新；旧 app/、app-r2/ 和 rejected-r1/rejected-r2 只作本地追溯，不分发。

独立测试根 `/Users/pufei/Downloads/ctflab-gui-runtime-20261015`，实例 `f9d11feb-185f-4132-80d8-21f28ef688fc`：gen1 经 GUI 正常停止，gen2 受控失败收口为 aborted，gen3 reset-ready 接续失败后孤儿预约释放。结束现场核验无该根绑定的 QEMU/双网服务进程，资源账本活跃预约为零，停止证明五成员均 stopped；gen3 保守显示待接续/恢复并不表示有运行进程。证据 status-final.json、process-final.json 及完整日志/账本均保留。默认目录仅查询，最终默认 GUI 保持打开，没有操作用户节点。

网络记录：TUN 覆盖路由由用户关闭后复核通过；Git 直连失败，改为仅本次命令使用系统现有 127.0.0.1:7897 代理后推送成功，没有修改持久代理配置。用户已告知测试结束可自行恢复 TUN。

实际限制：跨 Mac、Apple 公证、人工解题未做；本轮未重跑服务/隔离矩阵，其成功证据仍属10月14日验收。旧版若以本地化时间登记身份，可能继续 fail-closed 为 unknown，不放宽核验或强杀。13.1GB 第三方内容包仅库内自用分发，许可未核验且没有公开上传。无本轮阻塞；后续跨 Mac 需第二台设备，公证需签名资料与另行授权，不列为本轮已完成。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、状态第50节和 GUI验收记录并核对 Git/实际产物/实例。日期修正版 v0.1.2-preview.20261015 已发布，构建来源3cc1339，后续 docs 提交仅收口。下一阶段目标另行明确；不要重做发布、启动测试实例、删除故障现场或公开上传场景内容包。
