# CTFLab 当前状态与文档入口

> 最新交付（2026-10-30）：第139节0.1.4双端UI与Mac预览发布。Mac可执行包已发布，Windows同步提供最新版构建源码，**没有Windows EXE安装器**；暂无Windows原生环境，原生构建/安装验收未完成。旧版保留，43项/G0/G1仍开放。

> 最新开发入口（2026-10-28）：第113节来宾准备恢复桌面接入与Windows PE静态依赖核对；全部未关闭判据继续保留。源码未打包发布，原生平台/安装/课程/43项/G0/G1仍未完成。

> 最新开发入口（2026-10-28）：第112节OCI未开始装载续建与双端拓扑布局；全部剩余判据继续见本节与剩余说明第4节。源码未打包发布，真实平台/课程/安装与43项/G0/G1保持开放。

> 最新开发入口（2026-10-27）：第111节Windows专用NTFS卷只读绑定与未准备实例恢复；剩余开发以第111节及剩余说明第4节为准。原生Windows卷尚未实测，源码未打包发布，43项/G0/G1保持开放。

> 最新开发（2026-10-29）：见第117节新启动的可重接日志通道、驱动及两端恢复入口，尚未重新打包。已发布Mac预览仍为第114节v0.1.3-preview.20261028；Windows继续候选验证。稳定版、完整G0/G1及43项路线图未完成。

> 最新开发入口（2026-10-23）：第77节的Windows后台控制集成与集中验收包；Smoke和安装目录清单已有回传。全43项与G0/G1尚未完成，以下早期记录按日期追溯。

> 最新入口（2026-10-21）：软件发布与资产归并见第 50、52 节；教学、Windows x64、Docker、拓扑与远程运行的后续规划见第 53 节及[产品路线](ctflab-product-roadmap-2026-10-15.md)，外部 VMware/VirtualBox 接入顺序见第 54 节。下方早期条目保留为历史记录，不能覆盖这些后续状态。

> 2026-10-11 文档复核。这里区分已发布软件、工作区实现、镜像资产与历史验收；不把代码完成或旧测试数替代本轮实机测试。

## 1. 三个不同交付物

| 对象 | 当前入口 | 边界 |
|---|---|---|
| 源码工作区 | `/Users/pufei/Downloads/ctf-lab` | 保留现有未提交修改；不是新的已发布 App |
| 已发布软件 | 镜像库 `03-软件/CTFLab-0.1.4-preview.20261030` 中新App；本轮下载包见第139节 | GitHub预发布v0.1.4-preview.20261030；Apple Silicon、macOS 26+，ad-hoc、未公证；旧0.1.2及更旧包保留 |
| 可迁移镜像库 | `/Users/pufei/Downloads/CTFLab-Library` | `01-待处理` 保存原始输入；`02-已处理` 保存三节点包及独立 Acfun 本地适配包；不含运行进度 |

旧 worktree、历史 build/e2e 目录不再是使用入口。保留历史文档里的路径只用于追溯，清理后的文件不能继续按旧命令调用。

### 镜像库与 Kali 配套关系（2026-10-11 补记）

- `02-已处理/kali-arm64-base.qcow2` 与 `kali-arm64-uefi-vars.fd` 必须保留，供接收者导入；本轮未删除它们。基盘沿用 2026-09-16 分发文件，其哈希与本机当前登记来源一致，并不是将后续运行 overlay 软件/设置重新固化的新镜像。
- 后续 Kali 显示、输入与窗口优化主要在 App/受控显示客户端；既有测试使用该基盘派生的独立运行副本。测试中的临时来宾适配、用户反馈与候选客户端结果不能自动扩展为“新机器用未修改基盘已全部通过”。实际运行效果需与对应 App、来宾适配和日期化证据一起判断。
- 本库最新Mac预览为 `0.1.4-preview.20261030`；Windows候选及未关闭验收另列。不要把“当前基盘可配套使用”写成“所有最新优化已固化到基盘”。
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

## 51. 项目中间产物清理（2026-10-15，用户授权）

用户要求删除本项目全部中间产品。本轮按可恢复方式将55项已确认中间产物移入 `/Users/pufei/.Trash/CTFLab-中间产物-20261015-104626`，没有清空废纸篓或永久删除；du显示约125G，因仍在同一磁盘废纸篓，不能记为已释放空间。逐项原路径/废纸篓目标均核验一致，完整恢复映射保存在 `/Users/pufei/Downloads/CTFLab-清理记录-20261015.json`。

清理范围：Downloads 下历次临时验收/适配/测试状态根、旧候选构建与重复交付目录；最新发布目录中的 app/、app-r2/、zip-check/、zip-check-state/、rejected-r1/r2 和候选说明；ctflab-build/qemu-11.1.0 解包构建树（原始归档仍保留）；仓库未跟踪的 QEMU configure 生成物、__pycache__、无进程绑定的短socket根及本聊天临时日志/草稿。历史验收文档描述的原证据路径现已移走，不能再据旧路径直接重跑，恢复需按清单先核对目标路径和实例身份。

明确保留：正式源码仓库及Git/编辑器资料；完整 CTFLab-Library（原始镜像、已处理内容包、正式软件包）；最新发布目录的 app-final/CTFLab.app、ZIP和sha256；构建原始输入、QEMU源码归档和可重建用定制 runtime-root；默认应用状态目录。旧来源分发目录（精确路径见清理清单 preserved 字段）仍有默认节点的基盘/UEFI模板/分发元数据引用，因此保留，不当作中间目录删除。没有改用户节点登记或镜像库，也未改远端发布。

清理前：相关GUI、QEMU和场景网络进程均不存在；5个测试场景资源账本无活跃预约。对镜像库及默认状态目录内36个QCOW2逐一用qemu-img info --backing-chain核验，全部可读，无依赖待清理目录的外部磁盘或符号链接。清理后：最终App verify通过（812项、许可完整、ad-hoc、未公证），最新ZIP sha256 -c通过。未改实现、未启动VM或重跑完整回归；本节为本地文档更新，尚未提交/推送。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 AGENTS.md、状态第51节并核对Git与当前目录。20261015修正版发布仍有效；历史中间状态/证据已按清单移入废纸篓，不能使用原路径/PID继续操作。正式资产、默认状态和重建输入保留；若需恢复，先按 CTFLab-清理记录-20261015.json 核对路径，勿直接覆盖新文件或清空废纸篓。

第51节检查补记：文档守卫94项通过、跳过5，git diff --check通过。首轮因精确旧来源目录名触发“旧构建不得作为当前入口”文本守卫，改为指向清理清单的资产保留记录后通过，保留资产本身未改动。清理检查日志随废纸篓清理批次保存；源码没有变更，当前仅本状态文档未提交。

## 52. 软件与配套归并镜像库、清除库外重复目录（2026-10-15）

用户进一步要求把最新App放入镜像库并清理其他相关目录。现 Downloads 下本项目仅保留正式源码 `/Users/pufei/Downloads/ctf-lab` 与 `/Users/pufei/Downloads/CTFLab-Library` 两个目录；默认应用状态仍在 `~/Library/Application Support/CTFLab`，不作为中间产物删除。

当前App入口：`CTFLab-Library/03-软件/CTFLab-0.1.2-preview.20261015/CTFLab.app`，同目录有 App清单校验；ZIP和sha256仍在03-软件根目录，哈希不变。库外最新发布目录移走App后，其重复ZIP等移入新一批废纸篓。软件区旧App、local候选、旧ZIP及旧发布说明共8项亦移入废纸篓，03-软件只剩本版App目录、ZIP、校验、最新版.md以及 `构建资料-0.1.2/`。后者是原构建输入、定制runtime-root和QEMU源码归档的整体迁移，构建时请使用库内新路径。

旧来源分发目录的三张基盘、UEFI模板、DISTRIBUTION清单与镜像库02-已处理对应文件逐一SHA256相同。持默认应用 operations.lock，备份并只替换 smoke/basic-pentesting-2/kali-arm64 三个image.json中的来源前缀，改为02-已处理，原运行基盘/overlay/设置不变，所有新引用存在。旧来源目录不再被活动配置引用，连同重复发布目录及8个旧软件条目共10项移入废纸篓，没有永久删除。没有改变镜像内容或停止/启动用户VM；迁移前只正常退出待移动GUI，迁移后从库内App重新打开。

维护与恢复清单：`/Users/pufei/Library/Application Support/CTFLab/maintenance/20261015-consolidation/归并清理.json`，含移动映射、废纸篓位置和三份用户节点登记的原文备份；目录权限0700，不进入可分发镜像库。上一轮 Downloads 下的清理JSON已收纳为该目录 `上一轮清理记录.json`，第51节旧清单路径不再有效。恢复时应先核对现有路径并成组恢复登记/资产，勿将旧备份直接覆盖新运行状态。

镜像库根README、03-软件/最新版.md、文件清单.json与SHA256SUMS已同步；索引共1148项，新增/变更981项重算，167项未变镜像等沿用原哈希，去掉1632项旧软件路径，不冒充全量镜像重算。检查：移库后App verify通过（812项、ad-hoc、未公证），ZIP sha256 -c通过；随包CLI读取默认状态成功、无运行节点，三节点基盘/来源/固件/清单引用有效；原生GUI从新库内路径启动，四节点显示已停止，场景正常空状态。本轮未启动VM或重跑来宾业务验收，没有提交/推送或更改GitHub发布；当前仅状态文档有本地改动。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第52节并核对实际Git/目录/实例。App、ZIP和构建资料统一在CTFLab-Library/03-软件，默认节点来源已迁移至02-已处理；库外历史路径不可再直接使用。清理与登记备份在默认状态的maintenance/20261015-consolidation；不要自动恢复旧登记、清空废纸篓或操作用户VM。

## 53. 教学与跨平台产品规划（2026-10-15，仅设计）

用户要求结合参考图制定 Docker、拓扑编辑、Windows/Linux、远程运行及镜像分发、路由、流量分析、WAF 等能力的规划；明确“教学与个人练习优先，Windows x64 为下一重点”，随后补充 Windows 渗透、内网多靶机和应急响应课程需求。本轮完成源码定向调查、一手技术资料核对及可实施设计，没有实施上述新增能力。

交付：[产品路线与实施原则](ctflab-product-roadmap-2026-10-15.md)、[Windows x64 专项](ctflab-windows-plan-2026-10-15.md)、[任务与验收清单](ctflab-implementation-backlog-2026-10-15.md)。优先级为平台抽象/Windows 原型→Windows 本地预览→通用场景与拓扑→Docker/内容与观测/Linux 执行器→远程和高级课程。若学生设备无法承载域实验，可提前 Linux x64 单节点远程路线。已明确 Windows 宿主和 Windows 来宾分别验收、AD 整体重置/VMGenID、应急证据与处置副本分离。

代码依据：场景 v1 校验仍固定 Wintermute 三节点两网；命令生成按客体架构硬编码 HVF/TCG；锁/权限/进程/控制端点/监听 FD 与 GUI 存在 POSIX/macOS 依赖。因此通用拓扑和 Windows 不视作现成能力。推荐在保留 Python 内核和 Mac GUI 的前提下抽离适配器；Windows 新界面与 QMP/显示技术均须原型验收。Docker 优先在受管 Linux VM 内执行，远程第一版把整个场景放在同一 Linux x64 节点。

正式目录仍为 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、调查 HEAD `0994f62`。开始时已有的当前状态文档修改完整保留；本轮新增三份规划，更新 README/旧路线图导航与 `.gitignore` 文档白名单。没有修改运行实现或镜像，没有打包、提交、推送或发布；软件仍为第 50/52 节记录的 v0.1.2-preview.20261015。

验证（2026-10-15）：`python3 -B -m unittest discover -s tools/tests -p '*docs*.py'` 共94项，89通过、5条件跳过；`git diff --check` 通过。三份规划的链接由现有文档守卫检查，另核对代码块闭合、37个任务ID无重复及新文件未被Git忽略。Windows、Docker、通用拓扑、远程执行与新增课程均未实测；现有来宾/GUI/隔离矩阵也未重跑。本轮没有创建测试实例、操作用户 VM 或改宿主网络，资产与默认状态未写入。结束时仅按进程名只读核验：QEMU system进程0个、SPICE客户端0个、既有CTFLabGUI 1个；未读取或接管用户运行目录，不能以该摘要替代以后操作时的实例绑定核验。

下一步建议实施 A01/A02 的纯策略切片，并形成 A03/W01 草案；Windows 实机验收需要用户指定 Windows 11 x64 测试机和允许操作范围，Windows 来宾还需授权介质。原图的实线/虚线状态没有转述为 CTFLab 已实现；本规划不授予对外监听、公开分发镜像或发布权限。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、状态第53节、三份2026-10-15规划与任务表，核对 Git 并保留现有改动。本次目标：A01/A02 平台依赖与加速器纯策略切片，附 A03/W01 草案；维持 Mac 行为兼容。不要自动启动 VM、操作桌面、改宿主网络、删除资产、提交或发布；Windows 实机设备与范围另行指定。

## 54. VMware/VirtualBox 接入顺序确认（2026-10-21，仅规划更新）

用户确认先外部 Kali，再外部 Windows/域环境。已将主规划第9.3节细化为 E01→E02→E03，并在任务表新增 E02 外部 Windows 单机、E03 外部域环境；Windows x64 本地适配主线优先级不变。初期原虚拟化软件负责外部 VM 启停、快照和恢复，CTFLab 负责连接、策略与检查；跨运行器恢复需核对外部恢复点和内部代次，不能把单方重置称为整体恢复。

本轮仅修改规划与本状态文件，保留此前全部改动；正式目录与分支不变。没有创建或操作测试实例、修改网络、运行实现、镜像或软件产物，没有提交、推送、打包或发布。外部接入功能仍未实现、未实测；没有本轮实例绑定需要交接，后续操作必须现场重新核验。

验证（2026-10-21）：`python3 -B -m unittest discover -s tools/tests -p '*docs*.py'` 共94项，89通过、5条件跳过；`git diff --check` 通过。仅验证文档相关约束，没有重跑来宾或网络验收。

接续入口：[产品规划第9.3节](ctflab-product-roadmap-2026-10-15.md)、[任务表 E01—E03](ctflab-implementation-backlog-2026-10-15.md)。继续该支线时先指定外部虚拟化软件、宿主系统、测试实例与允许调整的网络范围；本次同意为规划顺序确认，不扩大为现有 VM 的操作权限。

## 55. 现有产品方案评审（2026-10-21，仅评审）

用户要求评价和审核现有方案。本轮核对三份规划、真实场景/资源代码及相关官方资料，形成[独立评审记录](ctflab-plan-review-2026-10-21.md)。结论是值得建设教学工具，但先交付 Windows + 一门完整课程的稳定闭环，不把全部 39 项任务作为一次平台交付或确定工期。

发现 R1—R7：G1 门槛与任务编号不一致；Windows 运行时/显示组合尚未验证；缺少 WHPX 与 VMware/VirtualBox 同宿主共存门槛；外部 VM 隔离承诺需限于可控制路径；单 DC/全域恢复需补无健康复制伙伴样本；本地存储/课程/外部接入依赖可拆分；维护成本与排期需以原型校准。已有设计明确标为候选的部分作为待关闭风险，不当作现有产品缺陷。本轮没有采纳或实施这些建议；Windows 优先与 E01→E02→E03 的约定未改变。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f62`。既有改动保留；本轮新增评审文档和精确白名单，在总规划增加评审入口并追加本节。没有修改运行实现或资产，没有创建测试实例、操作用户 VM/网络、打包、提交、推送或发布。发布版本沿用第50/52节记录的 v0.1.2-preview.20261015，本轮没有重新核验远端发布。

验证（2026-10-21）：`python3 -B -m unittest discover -s tools/tests -p '*docs*.py'` 共94项，89通过、5条件跳过；`git diff --check` 通过。另核对四份规划/评审的本地链接、代码块与任务ID；39个任务ID无重复，新评审未被Git忽略。Windows、VMware、VirtualBox、AD、课堂使用和原有来宾验收均未运行。本轮没有相关运行实例或状态根需要交接，也不复用历史进程记录作为当前绑定证据；用户既有实例未接管。

后续可先按 R1—R7 修订规划与依赖，再进入 A01/A02 与 W01 的分阶段实施。实机测试仍需明确设备、资产与操作范围。

接续语：继续 CTFLab，目录 `/Users/pufei/Downloads/ctf-lab`。先读 `AGENTS.md`、状态第55节、`docs/ctflab-plan-review-2026-10-21.md`，核对 Git 并保留既有改动。本次目标：修订规划和任务依赖，统一 Windows 首版验收门槛；只修订文档，不自动实施代码、启动 VM、修改网络、删除资产或发布。

## 56. 增加社区使用目标（2026-10-21，仅规划）

用户补充“后面还想给别人社区用”。总规划新增第1.1节，明确本地自助使用与课程分享优先，社区交付提前补齐安装/入门、版本兼容、脱敏诊断、公开样板、贡献流程与维护入口；任务表新增 U01—U04，共43个任务ID。评审记录保留原39项基线并说明目标增补。Windows x64 优先和 E01→E02→E03 顺序未变，R1—R7未自动关闭；社区使用也不等于已授权公开上传镜像或开通托管服务。

正式目录、分支和 HEAD 与第55节一致，现场核对 HEAD `0994f62`；保留既有改动。本轮只更新总规划、任务表、评审补记与本状态，没有创建测试实例、操作用户 VM/网络、改实现、打包、提交、推送或发布，也未建立外部反馈渠道。已有软件发布沿用第50/52节记录，本轮未重新验证远端资产。

验证（2026-10-21）：`python3 -B -m unittest discover -s tools/tests -p '*docs*.py'` 共94项，89通过、5条件跳过；`git diff --check` 通过。四份规划/评审的本地链接、代码块和空白检查通过，43个任务ID无重复。当前无本轮测试实例/状态根需要交接；社区安装体验、内容分发依据和跨设备使用仍须后续实测/核验，不能用文档检查替代。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 `AGENTS.md`、状态第55—56节、评审和总规划第1.1节；保留已有改动。本次目标：统一 R1—R7 与 U01—U04，形成 Windows 社区预览的范围和验收表。只修改规划文档，不自动操作 VM、改网络、上传镜像或发布软件。

## 57. Windows 社区预览范围与门槛统一（2026-10-21，仅规划修订）

已读取 AGENTS.md、第55—56节和评审，按用户要求统一规划；本阶段文档修订完成，Windows 实现与产品验收尚未开始。以 [Windows 专项第6节](ctflab-windows-plan-2026-10-15.md#6-windows-社区预览范围与统一验收门槛) 为范围与验收的唯一入口，同步 [总规划](ctflab-product-roadmap-2026-10-15.md)、[任务表](ctflab-implementation-backlog-2026-10-15.md)；[评审第7节](ctflab-plan-review-2026-10-21.md#7-规划修订处理表2026-10-21不是实测关闭) 记录 R1—R7 的文档处理与剩余实测证据，第1—6节保留原评审时点。

本次确定的规划范围与门槛：

- G1 统一称为 Windows 社区预览，限已验收 Windows 11 x64/WHPX、单用户本地、一套离线 C01（Kali x64 + Linux/Web 靶机）。任务范围为 A01—A03 本地契约、W01—W06、P01、P03 本地切片、C01、U01—U04 首版要求；撤销专项 W0—W5 切片编号。
- 公开 G1 要求签名最终包、干净环境离线安装、至少两台物理机（含一台非开发干净机）、至少5名未参与开发者独立完成 C01、连续3轮停止/重置/重做和整课运行。CPU 支持仅按已通过组合声明；未签名只能封闭试点，15分钟入课保留为体验目标。失败/人工介入全部留证，阻塞修复后独立复验。
- C01 的双节点资源归属、整体停止/重置和失败保留归 W03/W04；不因后置完整通用 v2 而省略安全语义，若实施依赖通用路径须补入必要 S01/S03 切片。保存进度以持久运行盘及停止后继续为界。
- U01—U04 纳入自助教程、诊断脱敏/预览、完整样板的合法取得及分发依据、贡献校验、反馈入口与维护责任。未核验镜像不能公开分发；可提供合法来源/制作配方并验证准备路径，不要求内容市场。
- R3/R4 的共存及外部隔离分别归 W01 探针与 E01—E03；R5 的单 DC/全域无健康复制伙伴恢复归 C04/E03，不阻断 C01。E01 在 S03/S04 后可按课程需求提前，保留 E01→E02→E03，Windows 主线优先。
- R6 已调整 T02 可执行依赖、P03 本地/在线切片、O01 本地依赖及 C02 配方/运行器验收分离；仍为43个任务ID。R7 将旧工期标为历史粗估，要求 G0 后重估开发、课程、设备/签名与支持成本。

正式目录 `/Users/pufei/Downloads/ctf-lab`，现场分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f62`。既有改动保留，本轮仅改上述四份规划/评审和本状态；`.gitignore`、README、旧 Mac MVP 规划的已有改动逐文件哈希核对未变，状态第1—56节保持原样。三份规划与评审仍是未跟踪文件，未自动暂存或提交。没有改运行实现、镜像或软件产物，没有打包、提交、推送、发布或启用外部反馈渠道。已发布版本沿用第50/52节的 v0.1.2-preview.20261015，本轮未重新核验远端资产，工作区规划不代表发布包更新。

验证（2026-10-21）：`python3 -B -m unittest discover -s tools/tests -p '*docs*.py'` 共94项，89通过、5条件跳过；`git diff --check` 通过。另以 Python 对四份规划/评审检查28个本地链接及锚点、代码块闭合、空白和43个任务ID唯一性，并核对既有无关改动哈希；通过。未运行实现回归、Windows/VMware/VirtualBox/AD/网络/跨设备或课堂验收，也未重新查阅外部技术资料；原有引用保留其核验时点，后续落地须按选定版本核验。

本轮未创建或接管测试实例，没有相关测试状态根/运行进程绑定需要移交；未检查或操作用户既有 VM，不据此断言宿主无运行实例。镜像库、用户状态和原始资产均未写入；以后操作必须重新核验实例身份、状态根和派生磁盘。

未完成与下一步：全部运行任务仍为计划；运行时/显示组合、签名、设备覆盖、公开样板依据、维护责任与用户试点均待落实，技术风险没有因文档修订关闭。可在另行指定的实施阶段先做 A01/A02 纯策略切片与 A03/W01 草案。G0 实机前须指定 Windows 物理机、Linux 测试资产与操作范围；G1 再落实第二台设备、试点人员和签名/维护安排。Windows 来宾介质到 C02 再确认。本轮不需新增授权即可完成文档修订，未自动进入实现或实机阶段。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 `AGENTS.md`、当前状态第57节、Windows 专项第6节、评审第7节与任务表，核对 Git 并保留已有改动。Windows 社区预览的范围和门槛已统一，功能尚未实施。本次目标：____。如进入实现，可先选择 A01/A02 纯策略切片并形成 A03/W01 草案；未另行授权前不要启动或停止 VM、操作桌面、改宿主网络、删除资产、提交、上传镜像或发布软件。

## 58. 第一阶段开发完成：A01/A02 与 A03/W01 草案（2026-10-21）

用户在确认“可以开始第一阶段开发”后同意全部完成，范围按上一轮列出的 A01 依赖梳理、A02 纯策略实现与 Mac 兼容验证、A03 本地协议草案、W01 原型清单执行；不是全部43项平台任务或 Windows 产品交付。上述第一阶段交付完成；A03 协议实现、W01 实机和 G0/G1 均未完成。

交付：

- [平台基础实施记录](ctflab-platform-foundation-2026-10-21.md)：真实入口/调用链、平台依赖归属、Windows 替代路径及需保留异常语义；A03 请求/响应、代次/revision、幂等、事件重连、状态/错误与恢复草案。
- [纯策略模块](../tools/ctflab_platform.py)：HostPlatform/ExecutionPlan、架构白名单、显式 TCG 许可与硬件要求；Windows/Linux 输出标为 candidate-only、runtime_verified=false。独立计划查看器不启动进程/网络或写入运行状态，不以开发机平台隐式改变目标。
- 单机、ARM 安装器、Wintermute 场景的三处 Mac 参数生成接入共同策略；非法来宾架构在单机 builder 产生副作用前拒绝。现有 CLI/场景的锁、固件、网络、控制/显示和恢复路径保留；主 CLI 的 fcntl/POSIX 依赖尚未移植，不能在 Windows 当成运行器使用。
- [Windows 原型清单](ctflab-windows-prototype-checklist-2026-10-21.md)：设备/合法Linux样本/版本哈希登记、WHPX、受保护QMP、显示、锁/ACL、socket交接、监督异常与停止恢复、存储及共存探针；全部实机项待执行。
- 新模块加入 `.gitignore` 与发布模块白名单，修订独立 App 布局测试夹具；[新测试](../tools/tests/test_ctflab_platform.py)覆盖策略与实际调用接入。README、总规划第13节、任务表第9节同步工作区状态，保留旧发布说明。

本轮验证（2026-10-21）：

1. `python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_platform.py' -v`：11通过；禁用 fcntl 的独立导入仅证明纯模块边界，不是 Windows 测试。
2. 修改前源码快照与本轮生成器在合成绑定下比较28组完整 argv/端口映射：5个内置profile的有头/无头10组、Kali SPICE监听/剪贴板/文件传输8组、安装器4组、场景三节点含/不含SPICE6组，全部一致；没有启动真实来宾。
3. `env -u CTFLAB_DESKTOP_E2E -u CTFLAB_SPICE_TCP_E2E -u CTFLAB_BOOT_MATRIX_E2E -u CTFLAB_SPICE_AUTH_QEMU python3 -B -m unittest discover -s tools/tests -v`：819项，809通过、10条件跳过，215.629秒，测试进程退出码0。日志 `/tmp/ctflab-a01-a02-tests-20261021.log`（本地临时证据，不入库）；跳过5项显式真实QEMU/桌面验收及5项缺失历史交付目录检查。
4. 收口后的纯策略11项、文档94项（89通过/5跳过）通过；README规定的3个文件及本轮实现/测试文件的 `py_compile` 通过。`git diff --check`、40个相关本地链接/锚点、代码块、43个唯一任务ID及新增文件白名单检查通过。

未验证项：Windows/Linux真实后端、WHPX/QMP/显示/ACL/socket与共存、实际Mac来宾/人工桌面/隔离矩阵、跨设备、学生课程、最终发布包。完整本地回归包含临时合成资产/包夹具检查，不等于重打发布App或发布验收；Windows技术风险仍须实机关闭。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f62`。已有改动保留；旧Mac MVP规划、既有评审与Windows专项逐字核对未变，状态第1—57节原样保留；README/白名单/总规划/任务表只作本阶段增补或当前入口更新。源码与新文档未提交/推送，未重打正式软件或发布。实际发布版本仍沿用第50/52节记录的 v0.1.2-preview.20261015，本轮未查远端状态。

没有创建或接管真实VM/桌面/外部设备，没有改宿主网络或写镜像库/用户运行盘；测试在临时夹具目录运行，完整测试会话已退出，无本轮真实实例状态根或进程绑定待移交。未检查用户既有VM，不声称宿主没有其他运行实例。后续操作必须现场核验身份、状态根、来源资产与派生磁盘，不能沿用历史PID。

下一步：A03 实现与 W01 独立测试驱动；W01 实机前需用户指定 Windows 11 x64 物理机、访问方式、合法Linux样本和允许操作范围。没有设备不阻止独立协议工作，但不能宣布 G0/G1 完成；签名、第二台设备、试点与维护责任仍按 G1 门槛落实。此次第一阶段完成不自动授权下一阶段的VM操作、安装/更改宿主功能、提交或发布。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读 `AGENTS.md`、状态第58节、平台基础实施记录、Windows原型清单和任务表第9节，核对Git并保留已有改动。A01/A02第一阶段及A03/W01草案已完成，Windows尚未实机验收。本次目标：____（可先实现A03本地契约与W01独立测试驱动）；未经另行授权，不操作用户VM、改宿主网络、删除资产、提交或发布。

## 59. A03 本地契约与 W01 独立测试驱动完成（2026-10-21）

按本轮授权实现本地核心和独立驱动，保留已有改动；未操作 VM 或发布。详见 [实施与验证记录](ctflab-local-contract-w01-2026-10-21.md)，前阶段记录保留原样。

完成项：

- `tools/ctflab_contract.py`：严格版本/字段/类型/大小白名单、规范化请求、固定公开错误及事件去重/缺口检查。
- `tools/ctflab_local_service.py`：注入式后端，主体绑定、持久意图/幂等、代次/revision CAS、跨进程执行互斥、显式恢复、取消竞争、只读状态与事件。中断执行不自动重放；身份未知拒绝破坏动作。没有接入旧 Mac 生命周期或开放监听。
- `tools/ctflab_windows_probe.py`：独立计划、自测与固定运行时能力查询；校验清单、路径、哈希和版本，不接收任意命令或 QEMU 参数。默认九项原生探针均为未测试，G0=false；自测使用合成后端和自有 Python 子进程，无 VM。
- Git/发布模块白名单与隔离 App 布局测试已包含新增模块；README、基础记录、清单、路线图和任务表同步。没有重打正式 App。

本轮验证：

1. 契约测试26项、驱动测试12项通过；独立 `--self-test` 通过。另新增1项隔离包测试，证明不依赖仓库导入环境。
2. `env -u CTFLAB_DESKTOP_E2E -u CTFLAB_SPICE_TCP_E2E -u CTFLAB_BOOT_MATRIX_E2E -u CTFLAB_SPICE_AUTH_QEMU python3 -B -m unittest discover -s tools/tests -v`：858项，848通过、10条件跳过，230.274秒，退出码0。日志 `/tmp/ctflab-a03-w01-tests-20261021.log` 为本地临时证据。跳过包含5项显式真实QEMU/桌面验收和5项缺失历史交付目录检查。
3. 覆盖真实子进程中断后的合成副作用不重放、跨进程互斥、提交故障、取消/提交竞争、跨主体/代次、只读无写入、事件断档及脱敏；能力查询只使用注入测试，没有执行 Windows QEMU。新增模块/测试语法检查通过。

收口检查：文档回归94项，89通过、5条件跳过；`git diff --check`、50个本地文件链接、代码块闭合及43个任务ID唯一性检查通过。7个既有实现/规划文件与阶段开始快照哈希一致，状态第1—58节逐字保留。

限制与下一步：完整 A03 的现有 CLI/GUI 接入、受保护 IPC/可信身份提供方、Windows ACL/原生锁/进程监督及真实后端尚未完成；POSIX 私有目录检查不能替代 Windows ACL。W01 全部原生实机项、WHPX/QMP/显示/网络共存与 G0/G1 待验收。下一阶段可实现可信适配层；实机前须指定 Windows 11 x64 物理机、合法 Linux 测试资产和允许操作范围。不得把本地回归或运行时能力清单视为课程可用证明。

正式目录 `/Users/pufei/Downloads/ctf-lab`；分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f62`。源码与文档仍未提交/推送，未打正式包或发布；发布版本沿用历史记录 v0.1.2-preview.20261015，本轮未核验远端。原有 Mac 实现、纯策略及评审/Windows专项保留。

测试只使用临时夹具和自有子进程，完整回归进程已退出；没有本轮真实 VM 状态根或进程绑定待移交，没有检查或操作用户已有 VM，不声称宿主无其他实例。未写镜像库或用户运行盘。以后操作仍须现场核验实例、状态根和派生磁盘。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，读取 `AGENTS.md`、当前状态第59节、`docs/ctflab-local-contract-w01-2026-10-21.md` 和 Windows 原型清单，核对 Git 并保留已有改动。A03 本地核心与 W01 独立驱动已实现，本地回归848通过、10跳过，Windows 实机及产品接入未验收。本次目标：____；未经另行授权，不操作 VM、改宿主网络、删除资产、提交或发布。

## 60. 本机适配入口与全路线图接续（2026-10-21）

用户确认后续范围为全部43项路线图，并解除此前 VM 操作限制，Windows 机器由用户自行验证。此授权不等于实机结果，也不等于公开发布；不自动接管无关用户实例。按依赖持续实施，Windows 验收交付可重复入口，由用户回传结果。G0/G1 和各课程/网络门槛保持原标准。

本机适配切片已完成：`tools/ctflab_local_adapter.py` 从普通 POSIX 进程获取主体，拒绝特权/身份变化；默认只读，写请求在登记前拒绝；受信宿主代码可注入后端。标准输入按字节限额、严格 UTF-8、拒绝超长/截断帧。主 CLI 新增 `local-contract --root`，在旧状态管理器创建前分派。错误保留完整公开响应结构，不回显路径。模块已加入源码包白名单，独立包入口测试覆盖。详见 [实施记录第7节](ctflab-local-contract-w01-2026-10-21.md#7-后续本机适配入口2026-10-21)。

验证：新增适配测试12项通过；完整入口 `env -u CTFLAB_DESKTOP_E2E -u CTFLAB_SPICE_TCP_E2E -u CTFLAB_BOOT_MATRIX_E2E -u CTFLAB_SPICE_AUTH_QEMU python3 -B -m unittest discover -s tools/tests -v` 共870项，860通过、10条件跳过，218.051秒，退出码0。日志 `/tmp/ctflab-adapter-tests-20261021.log`。跳过仍为真实QEMU/桌面及历史交付目录条件项；文档回归94项中89通过、5跳过；适配文件语法检查、`git diff --check`通过。随后场景v2工作另记，不算入这次870项。

限制：本机进程身份不是跨用户 IPC 认证；Windows token/ACL 未实现，入口在 Windows 明确拒绝，不以 chmod 假称保护完成。未接入真实 VM 后端或 GUI，也未执行 Windows 实机。下一步推进通用场景和课程/资产基础，同时准备 Windows 原生适配与验收。受 G0 阻塞的下游不能仅凭源码存在标为完成。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f62`；保留前轮改动，未提交、推送或发布，未重打正式 App，历史发布版本仍为 v0.1.2-preview.20261015（未核验远端）。本阶段只运行临时合成夹具与自有 Python 子进程，测试会话已退出，没有真实 VM 状态根需要移交；未核验其他用户实例。

接续：继续 CTFLab 全部43项路线图，读取 AGENTS.md、状态第60节与之后新增记录、任务表及 A03/W01 实施记录；保留已有改动。用户负责 Windows 实机验证，逐项保留未测/失败，不自动公开发布或操作无关实例。继续当前尚未完成的实现切片，不将此前本地测试换算为实机验收。

## 61. 全路线图实施进行中：场景 v2 与 Windows 原生基础（2026-10-21）

本节为进行中记录，不表示43项完成。新增 `tools/ctflab_scenario_v2.py`：独立 schema 2 解析、确定性依赖排序、通用三节点双网与逻辑资源计划。未知字段、重复地址/MAC、网段重叠、依赖环和默认出口拒绝；按实例派生 MAC，按代次派生 overlay/NVRAM 相对资源名。资产仅声明哈希/来源/许可/验证等级，不读取镜像；网络静态地址须由后续来宾配置实现，不能把计划当作地址已生效。Wintermute v1 实现保持兼容，本模块尚未接入通用执行层。

新增 `tools/ctflab_windows_native.py`：Windows `LockFileEx` 非阻塞排他锁、`GetProcessTimes` 创建时间与 `QueryFullProcessImageNameW` 只读进程身份。句柄不申请终止权限，读取失败为未知，PID/创建时间/映像不符为 mismatch。锁调用方仍须提供 ACL 已验证的私有根；不声称已完成 Windows ACL、监督/Job、端点归属或 QMP。两模块已加入源码白名单。

新增验证：场景 v2 测试12项通过；Windows 原生边界5项中3通过、2项仅 Windows 可运行的测试跳过。命令分别为 `python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_scenario_v2.py'` 和 `python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_windows_native.py'`。原生代码尚未在 Windows 执行，用户可在 Windows 用后一个入口复验；不是 W01/G0 完成。前一节870项完整回归未包含本节新增测试。

API 依据于2026-10-21核验 Microsoft 一手文档：[LockFileEx](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex)、[GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes)、[QueryFullProcessImageNameW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-queryfullprocessimagenamew)。文档存在不是当前设备验证证据。

当前仍在正式目录和原分支/HEAD上持续实施，未提交/打正式包/发布，也未操作真实 VM。下一步为课程目录/架构变体、通用执行接入及 Windows 私有存储/控制通道；Windows结果由用户回传，失败与未测继续保留。后续接续先读本节及之后记录，保留全部已有改动。

## 62. 课程目录、分享预览及 Windows 验证包（2026-10-21）

在全43项范围内继续独立基础切片，未宣称全部完成。逐项差距见 [执行台账](ctflab-roadmap-execution-2026-10-21.md)。

- `tools/ctflab_catalog.py`：严格目录 schema 1、独立场景 schema 2、精确宿主架构/变体选择；多匹配须显式选择，不偷偷降级。课程来源/许可/分发声明与入口可见，验证等级是目录声明，不提升为当前来宾证据。受信镜像库根下只读验证资产哈希，拒绝越界、链接/重解析点/硬链接、未知资产，保留缺失与哈希不符。
- 主 CLI 新增 `scenario-plan-v2`、`course-catalog`；与 `local-contract` 一样在旧状态创建前分派，独立模块也可直接运行。Wintermute v1 和旧内容包不自动迁移。
- `tools/ctflab_diagnostics_public.py`：读取已有本地诊断，按白名单重建分享摘要，省略日志、路径、IP、PID、私人ID、自由文本；默认预览，导出须匹配预览摘要哈希，不覆盖文件、不上传。旧 `doctor --diagnostics` 仍是含本地路径的私有诊断，不作为可公开分享包。分享入口为 `python3 -B tools/ctflab_diagnostics_public.py INPUT.json`；确认后加 `--export OUTPUT.json --preview-sha256 DIGEST`。
- `tools/ctflab_windows_kit.py`：可复现白名单验证包构建器，拒绝覆盖。开发工具不放入正式源码发行模块列表；新运行模块纳入白名单。产物 `output/windows-foundation-20261021/CTFLab-Windows-foundation-validation-r2.zip`，SHA-256 `f47abf7770d9a450a4f90e3f7723a22c46336d8a0e7228b004010d7822fe5fe7`，旁有 SHA256-r2.txt。r2修正普通Windows用户无符号链接创建权限时的负测跳过，旧zip保留，不覆盖原产物。隔离解压后运行所附测试和自测通过。本包不含运行时/镜像/凭据，不启动 VM，不是签名安装包或 G0 交付。

新增针对性证据：目录8项、分享预览5项、验证包可复现/隔离运行1项通过；本机适配测试现为13项（新增两个主CLI入口不创建旧状态的测试）。场景v2为12项；Windows原生边界5项中3通过/2待Windows。完整收口回归：与第60节相同的禁用真实E2E入口，共902项，890通过、12条件跳过，220.745秒，退出码0；日志 `/tmp/ctflab-roadmap-foundation-tests-20261021.log`。新增2项跳过为Windows原生测试，原10项条件跳过保留。其后只修订Windows无符号链接权限时的明确跳过行为，验证包隔离测试重跑通过（含所附全部37项，当前Mac为35通过/2跳过）；没有重跑完整902项。文档94项中89通过/5跳过，语法、43项台账、本地链接、白名单包源码一致性与 `git diff --check` 通过。第60节870项仅代表当时版本。

当前实际缺口：Windows运行时组合尚未指定，QMP/显示/ACL/Job/端口交接/冷启动恢复没有实机证据；已请用户运行验证包并回传运行时来源/版本。通用多节点执行、GUI/安装包、课程资产、容器/远程/外部接入、多人/签名/课堂等仍未完成。后续不把“用户自行验证”写成“已验证”。

目录、分支、HEAD沿用第60节，未提交/推送/公开发布；只生成基础验证源码zip，未重打正式App。没有本轮真实VM/宿主网络变更或运行磁盘写入。保留此前所有阶段改动和历史状态；后续继续先读本节与执行台账。


本阶段收口：完整测试会话已退出，无本轮真实VM/测试进程绑定待移交。全部43项仍未完成，不能宣称Windows可用或发布就绪；当前Windows主线的下一步需要用户基础验证结果与选定QEMU构建的来源/版本清单，再决定受保护控制/显示与监督接入。无此证据不跨过G0。其他路线图项按执行台账保留未完成状态，不以本轮基础模块代替课程、网络或真实用户验收。

接续语：继续 `/Users/pufei/Downloads/ctf-lab` 全43项路线图，读取 AGENTS.md、状态第60—62节和执行台账，保留已有改动；Windows实机由用户验证。最新基础验证包为 `output/windows-foundation-20261021/CTFLab-Windows-foundation-validation-r2.zip`。先处理用户回传的Windows结果和运行时组合，再推进W01/W02及通用执行接入；未明确指定的用户实例不操作，不自动公开发布。

## 63. Windows x64 路线说明、宿主预检查与私有存储（2026-10-22）

用户询问原生x86 Windows是否仍用QEMU，并要求继续。按Intel/AMD的64位Windows理解，路线仍为QEMU + WHPX：QEMU负责虚拟硬件/磁盘，WHPX用于同架构CPU硬件加速；默认不回退跨架构TCG。首版限定Windows 11 x64，32位Windows不在范围。依据 [QEMU WHPX](https://www.qemu.org/docs/master/system/whpx.html)（2026-10-22核验）；开发文档不替代锁定构建实测。本轮没有挑选或下载未经核验的Windows二进制。

实现：

- `ctflab_windows_probe.py --native-preflight`：仅在Windows x64/64位Python查询系统目录的WHP API；区分api-unavailable、query-failed、not-present、available。查询HypervisorPresent，不创建partition、不启用系统功能、不运行QEMU。即使前置检查成功，G0、QEMU执行、九项原生验收均不提升为通过。
- `ctflab_windows_security.py`：当前普通进程token/SID、拒绝提权和线程模拟；新目录创建时附带受保护DACL，仅当前用户和SYSTEM完全控制。根属主/保护位、文件继承权限和允许ACE白名单逐次核验；空/宽松/复杂ACL、其他主体、权限不足拒绝。不修改任何已有目录ACL。禁止UNC、设备命名空间、ADS、父路径/保留名、符号链接和reparse point。
- `LocalService`的新根创建、根打开和每次数据库连接接入原生核验；`LocalAdapter` Windows主体取SID摘要，不接受消息自报身份。POSIX路径保持既有逻辑。私有目录父路径仍由受信本机调用方选择，不防御同用户恶意代码，不作为跨用户IPC认证。
- 新模块进入Git/源码包白名单。Windows原生测试包含私有根/继承文件、不覆盖已有根、拒绝Everyone宽松目录及契约/适配器同主体重开。它们未在本机Mac执行，明确条件跳过。

新验证包：`output/windows-foundation-20261022/CTFLab-Windows-foundation-validation-r3.zip`，SHA-256 `5a885351ee9d5c4cd93a85df203120f141c865923ea68ff0eac531bf1cbf2121`，旁有SHA256-r3.txt；r1/r2均保留。无需QEMU即可执行基础检查，原生功能不要求管理员。源码zip不含镜像/运行时，不是正式App、签名发行或G0验收。API依据与边界见 [实施记录第8节](ctflab-local-contract-w01-2026-10-21.md#8-windows-身份与私有存储接入2026-10-22)。

针对性结果：契约26通过、适配13通过、驱动15通过、Windows原生8项中6通过/2跳过、权限9项中6通过/3跳过；验证包隔离解压后的全部所附测试/自测通过，原生项仍条件跳过。完整回归入口与第60节相同（显式关闭真实E2E）：916项，901通过、15条件跳过，214.967秒，退出码0，日志 `/tmp/ctflab-windows-security-tests-20261022.log`。15跳过含原10项及5项Windows原生检查。随后追加的本地路径拒绝测试、WHP返回长度兼容与路径提前拒绝修订已重跑权限9项、原生8项、契约26项和验证包隔离测试（内含52项：本机47通过/5跳过）；未再次重跑全量。文档94项中89通过/5跳过，语法与 `git diff --check` 通过。

仍未完成：Windows ACL/WHP/锁/身份的实际设备结果、受保护QMP/显示与持久监督、真实来宾/课程验收及其余路线图项。Windows由用户自行验证；用户回传宿主前置检查、原生测试结果与锁定运行时来源/版本后推进W01选型。全部43项仍未完成，不自动发布。

正式目录 `/Users/pufei/Downloads/ctf-lab`，原分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f62`；保留已有改动及前62节历史，未提交/推送/正式发布，未重打Mac App。没有真实VM或宿主网络变更，未动镜像库/用户运行盘。历史已发布版本仍沿用v0.1.2-preview.20261015，本轮未核验远端。


收口：测试会话已退出，临时合成夹具已清理，无本轮真实VM实例/进程绑定需移交；未检查用户其他VM，不声明宿主无实例。接续语：继续 `/Users/pufei/Downloads/ctf-lab` 全43项路线图，读取AGENTS.md、状态第63节、A03/W01实施记录第8节及执行台账；保留已有改动。Windows采用QEMU+WHPX，用户负责原生验证，最新版验证包为20261022/r3。先处理原生预检查/ACL结果和运行时组合，再推进受保护QMP/显示/监督；不自动公开发布或操作无关实例。

## 64. 用户 Windows r3 回传与数据库句柄释放修复（2026-10-22）

用户提供的原始文本保持不变；本节只记录脱敏结果，不复制个人目录。r3 实机共52项：46通过、1错误、5跳过（2项符号链接权限限制、3项非Windows边界）。原生文件锁、当前进程身份、私有根/继承文件ACL与拒绝宽松目录已有通过记录；不能再统称全部原生未测。`test_contract_and_adapter_share_native_identity` 在临时目录清理时因 `worker.sqlite3` 的 WinError 32 失败，整体仍失败。独立自测返回 driver-error，日志未给出内部异常；与同一泄漏相关的判断仍待r4复测确认。

宿主预检查识别Windows x86_64，WHP查询返回 not-present / hypervisor_present=false。只表明当前hypervisor未运行，不能据此断定BIOS关闭。host_preflight_passed、qemu_execution_verified、G0均为false。用户可在Windows功能中核对 Windows Hypervisor Platform，按系统提示启用并重启再查；依据2026-10-22核验的 [QEMU官方说明](https://www.qemu.org/docs/master/system/whpx.html)。不自动更改系统设置或回退TCG。

修复：`LocalService.create` 显式关闭两个初始化SQLite连接，包括建表异常路径。Connection上下文只管理事务，不保证关闭连接；先前依赖垃圾回收导致Windows临时数据库不能立即删除。新增2项持有连接强引用的测试，分别验证成功关闭全部连接、首个/第二个数据库初始化失败后关闭已开连接；不以忽略清理错误或强制垃圾回收掩盖问题。原生契约/适配测试保留等待复测。

新版验证包：`output/windows-foundation-20261022/CTFLab-Windows-foundation-validation-r4.zip`，SHA-256 `baa7c75764f04672dd37f90aafbe257ac7eca5e6eb4251e97b294ab0150da61b`，旁有 `SHA256-r4.txt`。保留旧r3。白名单包现含54项测试；可复现构建、隔离解压测试与自测在Mac通过，Windows特有5项仍跳过。新增存储测试11项中8通过、3原生跳过。r4尚未在用户Windows运行，不算G0或正式发布。

原始回传文本SHA-256：`8b30e0e87c33c2beba27abf3be7aa424610e7b2175dc8efe2a070af55089a61f`；仅用于区分本轮输入，原文含私人路径，不纳入源码包。文档回归94项中89通过、5跳过；修订文件语法、r4源码逐文件一致性、`git diff --check`通过。

完整本地回归：`env -u CTFLAB_DESKTOP_E2E -u CTFLAB_SPICE_TCP_E2E -u CTFLAB_BOOT_MATRIX_E2E -u CTFLAB_SPICE_AUTH_QEMU python3 -B -m unittest discover -s tools/tests -v`，919项，904通过、15条件跳过，212.670秒，退出码0。日志 `/tmp/ctflab-windows-r4-tests-20261022.log`；文档日志 `/tmp/ctflab-r4-doc-tests-20261022.log`。这些是Mac本地/合成证据，不能代替r4 Windows实机或真实来宾验收。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f62`；保留此前全部改动，未提交、推送或发布，未重打正式Mac App。只生成r4源码验证包；历史发布版本仍沿用v0.1.2-preview.20261015，本轮未核验远端。没有操作真实VM、用户实例、镜像库或宿主网络。测试会话已退出，本轮没有真实VM/进程绑定需移交；未检查其他用户VM。

未完成与下一步：用户将r4解压到新目录，运行所附测试、`--self-test`、`--native-preflight`并回传脱敏结果；还需Windows具体版本与QEMU来源/版本/锁定清单。W01受保护控制/显示/监督、G0及全43项路线图仍未完成，不能把本次资源释放修复写成Windows运行器已可用。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第64节与43项执行台账，保留已有改动。处理r4 Windows复测和运行时组合，再推进W01/W02及通用执行；Windows实机由用户验证，不自动发布或操作无关实例。

## 65. 用户回传 r4 Windows 基础验证通过（2026-10-22）

本轮依据用户回传文本，原文保持不变、不复制私人路径；输入SHA-256为 `35b1282eedecbc3b2ea22b545c64e033e7c554dd195b1eef2dcb01e0fafb1527`。输出目录名称指向r4，但未附ZIP哈希、Windows具体构建和Python版本，产物身份与设备信息仍需补齐；不据不同私人目录推断同机升级或跨设备验收。

- `python -B -m unittest discover -s tools/tests -v`：54项，49通过、5跳过，1.209秒，OK。跳过为2项缺少符号链接创建权限的负测、3项非Windows边界检查；不将跳过记为通过。
- 原生契约/适配器同主体重开测试通过，临时目录清理未再出现WinError 32；两个初始化连接释放回归测试通过。r3失败保留为历史，本次回传支持r4修复有效。
- `python -B tools/ctflab_windows_probe.py --self-test`：持久幂等、存储重开、合成生命周期、事件重放、自有stdio夹具五项passed；scope仍为synthetic-only，无真实VM。
- `python -B tools/ctflab_windows_probe.py --native-preflight`：Windows x86_64，host_supported=true，hypervisor为available/present=true，host_preflight_passed=true。说明回传环境的宿主前置检查通过；qemu_execution_verified=false。
- 默认驱动输出九项原生验收仍not-tested，G0=false。基础单元证据不能自动提升受保护控制、显示、监督恢复或完整存储场景的验收状态。

本轮只更新状态和执行台账，未修改实现或验证包，未重跑完整源码回归；第64节919项仍为上一轮本地证据。下一步补充Windows版本、Python版本、r4包哈希及QEMU是否已安装；已有QEMU需给出版本/下载来源，之后锁定组件清单并运行固定能力查询，再推进受保护QMP/显示/监督。当前没有QEMU执行或真实来宾证据，43项路线图尚未完成。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f62`；保留已有改动，未提交、推送、重打包或发布。未操作VM、镜像或系统网络，本轮无新增运行实例需移交，未检查用户其他实例。历史发布版本沿用v0.1.2-preview.20261015，未核验远端。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，读取AGENTS.md、状态第65节及43项执行台账，保留已有改动。r4 Windows基础测试和宿主预检查已有用户通过回传；补齐运行时来源与版本后推进W01/W02，不把基础结果当G0，不自动发布或操作无关实例。

本轮文档验证：`python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_*docs*.py'`，94项中89通过、5条件跳过，0.354秒；日志 `/tmp/ctflab-r4-return-doc-tests-20261022.log`，`git diff --check`通过。

第65节后续：用户确认尚未安装QEMU。2026-10-22核验QEMU官方下载页的Windows入口指向Stefan Weil构建；w64目录列出 `qemu-w64-setup-20260811.exe`，构建历史标为11.1.0，并提供同名.sha512。暂选该固定构建作为W01待验证候选，不宣称CTFLab支持或正式分发认可。来源：https://www.qemu.org/download/#windows 与 https://qemu.weilnetz.de/w64/ 。用户下载、比对站点SHA-512并安装后，普通PowerShell查询固定路径的 `--version`、`-accel help`、`-display help`；同时记录可执行文件SHA-256。帮助列表不是WHPX启动证据，后续仍需锁定依赖/固件/显示组合与真实来宾验收。本轮未代用户下载或安装，未更改验证包或运行VM。

## 66. Windows QEMU 候选构建回传（2026-10-22）

用户回传固定安装路径的查询结果：完整版本 `QEMU emulator version 11.1.0 (v11.1.0-12130-ge470268ff4)`；不能省略后缀并认定与上游纯11.1.0标签一致。可执行文件SHA-256 `47d57a6072e0bb3bd98f87926eb129eb1736dfe818c67b3b81ef7ce4edd0b3cd`。加速器列表为tcg/whpx；显示列表为none/gtk/sdl/egl-headless/curses/spice-app/dbus。列表只证明构建报告这些标签，不证明WHPX执行、SPICE服务保护、客户端或实际显示成功。

生成 `output/windows-foundation-20261022/qemu-runtime-candidate-r4.json`，供r4现有 `--inspect-runtime` 入口使用；包含用户报告的固定路径、版本和哈希，只执行固定版本/加速器/显示/设备帮助查询，无VM或监听。source_id明确为用户回传候选，未将建议的下载来源与安装包校验擅自认定为用户已完成。未锁定DLL、固件、Python、显示客户端，因此不是完整运行时锁定包，components_complete应仍false。下一步将清单放入r4解压目录运行查询，保留完整输出、失败和G0=false。

本轮只生成候选JSON并更新文档，保留已有改动；未修改实现、旧验证包或正式App，未操作VM、提交、推送或发布。正式目录、分支和HEAD沿用第65节；无新增运行实例。仍待完整组件来源/清单、受保护控制与显示/监督方案、实际来宾验证。接续：读取AGENTS.md、状态第66节及执行台账，处理固定构建查询后推进W01/W02，不能将help标签提升为运行验收。

## 67. 用户固定构建检查通过，转入实际启动准备（2026-10-22）

用户在Windows运行r4 `--inspect-runtime` 回传：build_id为windows-qemu-11.1.0-47d57a60，QEMU SHA-256与第66节一致；版本/加速器/显示/设备四项查询均inspected、returncode=0，build_inspection_passed=true。加速器提取tcg/whpx，显示提取sdl/spice，设备提取qemu-xhci/virtio-gpu-pci。显示中的spice标签由spice-app文字提取，不等于SPICE服务端认证/TLS或客户端已验证。

四项输出SHA-256依次为 `e7b39f6d8a73023856fe2fa3254802e12fc98c81991e486ef6177ddd96fa7f3d`、`23cd4f2dafbac787e53f334f53b291f233d05a5cc39b72aabd75c2f17ce5ca15`、`5a514f7981e1c9366787df5f6ecd185a3130dff43df20fbe7b583790d89052c8`、`c7fb28acec9cdf4428fc68a84e3c2c272a537b0970a74886908fc8a0d5d823d9`。来源为用户回传而非本机重跑。

components_complete=false、vm_started=false、runtime_verified=false、G0=false；九项原生端到端探针仍not-tested。r4没有真实VM启动入口，不能让用户反复跑help代替下一阶段实施。下一阶段需准备独立状态根/派生磁盘、合法Linux x86_64样本及对应启动/受保护控制测试驱动。尚未确认用户Windows侧样本是否可用，先询问样本类型/来源，不能自行复用其既有运行盘。固件/DLL/显示组件清单和监督仍未完成。

本轮只记录结果并同步台账，未修改源码/验证包，未重跑实现回归，未操作VM、网络、镜像或发布。正式目录 `/Users/pufei/Downloads/ctf-lab`，分支/HEAD沿用第66节，已有改动保留；无新增测试进程或实例。接续语：继续CTFLab，读取AGENTS.md、状态第67节及执行台账；基础和固定构建查询已通过，准备合法样本与真正的Windows启动验证切片，不自动发布或操作无关实例。

## 68. Smoke Windows 独立冷启动实验包（2026-10-22）

用户确认沿用此前处理的Smoke等OVA，并已将Smoke-OVA目录复制到Windows `C:\CTFLab-Test\Smoke-OVA`。本机只读核验库内 `Smoke-OVA-20261013/smoke-ova-base.qcow2` SHA-256为 `f9c2edc334c9e2839c1d605d6d870e8f68ad1242f892fe3f96ed75bfaf554052`，与SHA256SUMS一致。profile声明x86_64、BIOS、pc/IDE、1GB/1CPU；此前Mac验收不算Windows通过。未重新提取或修改原始OVA/基盘。

新增开发实验入口 `tools/ctflab_windows_smoke.py`：默认不启动，显式--start且Windows普通用户、WHP可用、固定QEMU/基盘哈希匹配后，建立原生私有ACL的独立w01-run目录，独占复制磁盘、fsync并核验副本。使用持久副本而非临时快照，保留失败现场。只用WHPX，无TCG回退；关闭默认设备并显式SDL/VGA、IDE、无网络/串口/并口。本次控制台直连stdio monitor，不监听TCP。记录子进程PID/创建时间/映像（失败则unknown）、退出码、前后基盘哈希，stderr与副本保留。用户观察登录画面后输入system_powerdown，超时保留；明确决定强制结束时才输入quit。退出码不能推断正常关机。该入口没有自动关停或恢复旧PID，不是持久受保护QMP/显示方案，也不是G0。monitor用户操作仅限实验副本，不应输入commit。

产物 `output/windows-foundation-20261022/CTFLab-Windows-Smoke-boot-r1.zip`，SHA-256 `8d73644626ab0d9171825ca227e45dde9b8f1dd90c3544ed3ed952752d9c6372`；含独立脚本、原生依赖、5项测试和README，不含镜像/运行时。新目录解压即可运行，无需覆盖r4。新增Git白名单；开发实验工具未放入正式App模块清单。

本轮验证：`python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_windows_smoke.py'` 5项通过；验证默认不执行、错误平台拒绝、固定无网络参数/无TCG、复制独立/不覆盖、坏哈希保留现场。ZIP隔离解压后同5项与默认入口通过。本机未执行Windows VM，完整源码回归未重跑。参数依据2026-10-22核验QEMU invocation官方文档。用户需回传SDL画面、是否到登录提示、system_powerdown结果及本轮result.json/stderr；人工与实机证据仍待回传。

保留已有改动、原r4及其证据，未提交/推送/正式发布，未重打Mac App。正式目录 `/Users/pufei/Downloads/ctf-lab`，原分支/HEAD未变。本机未操作任何真实VM、网络或用户运行盘，无本轮常驻进程；Windows端只有用户执行--start后才创建实例，其目录/进程绑定须以回传和现场核验为准。接续语：继续CTFLab，读取AGENTS.md、状态第68节和执行台账，处理Smoke启动实验回传，保留副本/失败现场，不自动操作旧PID或发布；继续W01/W02的受保护控制/显示/监督实现。

## 69. 全路线图设计补齐并开始验证（2026-10-22）

用户要求先完成后续所有设计再开始验证。本轮形成[43项详细设计基线](ctflab-detailed-design-2026-10-22.md)：统一入口/契约、资源归属、多节点生命周期、提交与取消、崩溃恢复、Windows控制显示监督、网络/内容/远程边界、逐项交付与负测、V0—V5验证顺序。与执行台账43项逐项对应，实施状态未提升为完成。已有用户Windows基础及固定构建查询回传继续有效，Smoke冷启动仍待实测。

设计落盘后执行验证：文档94项中89通过/5跳过；11组基础模块115项中110通过/5 Windows原生跳过；43项唯一性/覆盖、本地链接及diff空白检查通过。命令、范围和日志见[验证记录](verification-design-baseline-2026-10-22.md)。未重跑全量，未验证尚未实现的模块，不声称G0/G1或全部路线图通过。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f62`。保留全部既有改动；未提交、推送、重打App或发布，发布状态沿用第68节。本轮无真实VM或常驻测试进程，无新增运行状态根；未检查/操作用户其他实例，原盘和镜像库未动。

下一步：依据设计V2处理Windows Smoke回传，补齐完整运行时清单与受保护控制/显示/监督探针；其后按依赖实施产品和扩展再验证。仍需Windows实测、合法课程资产、设备/用户与签名等对应阶段输入。接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第69节和43项详细设计及验证记录，核对现场并保留已有改动。后续设计已覆盖，已有基础测试通过；继续V2与依赖实施，未测不得标通过，不自动操作无关实例或发布。

## 70. V2运行时清单前置实现与验证（2026-10-23）

读取第69节与设计后，推进W01运行时登记前置切片：新增 `tools/ctflab_runtime_inventory.py`，显式指定QEMU安装根，只读记录普通文件相对名/大小/哈希、系统与Python版本；不执行二进制。拒绝链接/重解析点/硬链接，限制数量/大小，检测采集中变化；参考清单先校验再比较新增/删除/变化，输出独占创建且不能落在安装目录内。清单一致不等于运行依赖闭包或来源可信，所有能力/G0声明保持false。当前是开发验收工具，未加入正式App模块。

[操作说明及边界](ctflab-windows-v2-validation-2026-10-23.md)。交付 `output/windows-v2-20261023/CTFLab-Windows-V2-inventory-r1.zip`，SHA-256 `14e60e100e690794ffbb9b0c0f4db33b3496b602b35440cee4308b3cc40985c6`；旁有SHA256-r1.txt。独立新包未覆盖前轮r4/Smoke包，内含源码/8项测试/说明和逐文件MANIFEST，不含镜像或运行时。

验证：新增测试8项通过；独立临时目录解压后逐文件一致、包内8项通过；Windows已有专项40项中35通过、5原生条件跳过。入口为 `python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_runtime_inventory.py' -v` 与同命令模式 `test_ctflab_windows*.py`。日志在 `output/windows-v2-20261023/`。未重跑完整回归，没有Windows原生或真实VM执行。最初正向临时夹具因macOS父路径符号链接被拒绝，已将测试夹具解析为实际路径，生产拒绝规则不变。

文档证据更正：上一轮第69节引用的89通过/5跳过是新增验收记录前的结果；现场读取 `output/design-validation-20261022/docs-final.log` 确认最终为88通过/1失败/5跳过。本轮复现相同失败，补齐该记录要求的“历史验收快照、不替代当前软件状态”标识；旧日志与本轮失败docs.log均保留。最终复验另附，不以shell最后一条命令成功代替测试退出状态。

当前正式目录/分支/HEAD仍为 `/Users/pufei/Downloads/ctf-lab`、`codex/release-0.1.1-preview-20261010`、`0994f62`。既有源码与失败现场保留，未提交/推送/正式发布或重打Mac App；已发布版本仍沿用历史v0.1.2-preview.20261015（未核验远端）。本轮只用自有临时夹具，测试已退出，无真实VM状态根/常驻进程绑定移交，未检查或操作其他用户VM。

下一步及输入：用户在Windows采集安装目录清单并预览后回传，补充Smoke是否到登录画面、正常关机结果与脱敏result.json/错误。受保护控制、显示重连、监督/端口/恢复尚未实现验收；以具体构建与回传为依据推进，G0/G1保持未通过。当前工具不抵御同用户恶意并发替换，不作为后续启动的授权或原子锁。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第70节和V2验证说明，核对Git与现场，保留所有改动/失败记录。处理Windows安装目录清单和Smoke回传，再推进受保护控制/监督及依赖实施；不得把清单一致或本机单元通过当作G0，不自动操作无关实例或发布。

第70节最终验证：文档回归94项，89通过/5条件跳过，退出码0（docs-final.log）；新增源码与测试AST语法检查通过，git diff --check通过。

## 71. 用户Smoke登录画面与退出反馈（2026-10-23）

用户回传QEMU窗口截图：标题CTFLab-Smoke-WHPX-test-0，画面显示Alpine Linux 6.12.74-0-lts on x86_64、Hostname Smoke及 `Smoke login:`。足以确认本次进入Linux登录提示，不是UEFI Shell或仅窗口出现。IP栏为空与第68节关闭网络的配置一致，不推断网络故障或网络通过。未进行认证登录/服务/解题验收。

截图副本保存在 `output/windows-v2-20261023/smoke-login-user-20261023.png`，SHA-256 `982e17ba975b3d40fde0a3079e71b475e5d4b110098a66cda347cf26a11ce17b`；原附件不变。用户同时反馈“可以正常退出”，记录为人工退出成功反馈；尚未明确是system_powerdown还是窗口关闭/quit，也未收到result.json、stderr或退出后的基盘哈希。因此不直接标记ACPI正常关机、进程退出码及源盘不变已核实。结合前轮固定WHPX无回退脚本，可记为该实验的用户启动画面证据，仍不替代完整运行时/控制/监督验收。

下一步无需重复r4或本次启动：回传该w01-run目录的result.json、qemu-stderr.log，并确认退出方式；依据第70节V2入口补齐安装目录清单。若此前未采集启动前清单，当前采集只能作为启动后基线，不能补称前后未变化。G0/G1及43项全路线图保持未完成。

本轮只保存用户截图并更新状态/台账，保留其他窗口已落地的第69—70节与设计/清单工具；未修改源码、重打包、提交、推送、发布或操作VM。正式目录 `/Users/pufei/Downloads/ctf-lab`，现场分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f62`。本机无新增运行实例；Windows退出为用户反馈，未远程核验进程绑定。接续语：读取AGENTS.md、状态第71节及V2说明，保留已有改动；Smoke已见登录提示并获退出反馈，补齐退出日志与运行时清单后推进控制/监督，不重做已通过基础检查，不自动操作旧PID或发布。

## 72. Smoke首次Windows启动与正常关机证据收口（2026-10-23）

用户明确确认第71节退出方式为输入system_powerdown后自行退出，并提供原始result.json和qemu-stderr.log。结果为scope=manual-whpx-sdl-offline-smoke、state=exited、returncode=0、source_unchanged=true；QEMU与源基盘哈希均匹配第68节固定值。结合登录截图和人工确认，本轮固定构建/该样本的无网络WHPX冷启动、SDL登录画面、人工触发正常关机及源基盘前后哈希不变证据已齐。不是认证登录、服务/网络、重启、长期稳定性或整个W01/G0通过。

原始结果中的guest_verified/graceful_stop_verified仍为false：实验脚本没有自动观测登录及关机原因，字段保持原样；本节综合截图/人工确认作为单独人工证据，不篡改原始JSON。process_identity.state=running是启动时采样，顶层state=exited是等待子进程结束后的结果，不将旧PID当作当前存活实例或操作依据。

stderr仅一条 `warning: Ignoring request for interrupt vector 0`。保留为警告；本次已到登录并正常退出，未见它阻断该闭环，但未诊断根因、不能宣称对其他负载无影响，也不据此改CPU/中断配置。

附件原文保持不变，证据副本在 `output/windows-v2-20261023/smoke-return-20261023`。result.json SHA-256 `1840ad276b5dd4ec6b845bd5e205f3a8fc081ed3aa5b07d8c03c0a3f9810d6b5`；qemu-stderr.log SHA-256 `769b67a801e48ec3d94be5c306160b56c732676a6effe2026eedc0416fc0b788`。这些是用户设备回传，不是本机复跑。

下一步无需重跑本次Smoke或r4；按第70节采集QEMU安装目录清单并推进V2受保护控制/监督/显示重连。若首次清单在本次关机后才采集，只能作为后续基线，不能声称已验证本次启动前后安装目录一致。完整运行时来源/依赖、恢复与网络隔离矩阵仍缺，G0/G1保持未通过。

本轮只归档回传并更新台账，未修改源码、包、基盘或既有改动；未提交/推送/发布或操作VM。正式目录与原分支/HEAD沿用第71节，未重打正式App。无本机新增进程；用户提供的子进程已退出记录不替代未来操作前现场身份核验。接续语：继续CTFLab，读取AGENTS.md、状态第72节与V2说明；Smoke首次无网络启动/画面/正常关机闭环证据已齐，补运行时清单后推进受保护控制/监督，不重复已通过测试，不自动操作旧PID或发布。


## 73. Windows运行时目录清单回传核验（2026-10-23）

用户已完成清单工具：8项测试中7通过、1因宿主不允许创建符号链接跳过，0.165秒。该负测仍为跳过，不建议为此放宽权限。首次命令在CMD中使用单引号导致参数解析失败，改双引号后生成附件；不是运行时校验失败。

本轮只读解析用户提供的runtime-after-smoke.json，调用validate_reference校验字段、规范相对路径、顺序/重复项与整体摘要，通过。清单共3385个文件、1255998954字节，含114个DLL及BIOS/EDK2固件候选；这些只是安装目录内容，不代表实际加载闭包。qemu-system-x86_64.exe SHA-256与第66/72节一致：47d57a6072e0bb3bd98f87926eb129eb1736dfe818c67b3b81ef7ce4edd0b3cd。本机未访问Windows设备重算3385个文件，仅验证回传清单的内部一致性和已知QEMU身份。

报告记录Windows、release=10、AMD64、Python 3.10.20；release字段不足以判定Windows产品名/具体构建或宣布Windows 11门槛通过。清单摘要aaa1757e56fa5208ece248e08272a95605266495b94400b5f0ca52caa39fe63b；附件字节SHA-256为2fdc821f54014b93ae02acc65c9a05d9a9108213812118457543564b82027669。原附件未改，逐字副本为output/windows-v2-20261023/runtime-after-smoke-user.json，不入库。没有启动前清单，本次只能作为后续比较基线。

目录清单回传项已收口，无需重复Smoke、r4或本轮采集。components_complete/dependency_closure_verified/source_verified/g0_passed保留false，不篡改原始输入。下一实施入口是W01受保护控制与W02监督/恢复探针，仍需对锁定构建验证；安装来源/许可证、实际加载依赖、具体系统构建和网络矩阵另验。不能据此宣称G0/G1通过。

正式目录/分支/HEAD沿用第72节：/Users/pufei/Downloads/ctf-lab、codex/release-0.1.1-preview-20261010、0994f62。本轮仅归档附件、更新记录，保留已有改动；未改源码、打包、提交/推送/发布或操作VM，无新增运行实例/进程。历史发布仍沿用v0.1.2-preview.20261015（未查远端）。接续语：先读AGENTS.md、状态第73节及详细设计；Smoke闭环和运行时目录清单已有回传，继续受保护控制/监督实现与针对性验证，不重复索要已验材料，不操作旧PID或发布。

## 74. QMP控制协议核心开发切片（2026-10-23）

按用户“先开发然后测试”推进：新增tools/ctflab_qmp_protocol.py，独立有界会话状态机，覆盖握手/能力协商、唯一请求ID、异步事件与响应分离、未知响应丢弃、不自动重放、关闭后拒绝操作。仅允许qmp_capabilities、query-status、system_powerdown，不提供quit、任意monitor或磁盘提交。重复字段、非法JSON/编码和超限关闭会话。消息接收窗口上限64KiB，调用方需分块输入；本模块不承担传输超时和认证。

依据2026-10-23核验的QEMU一手协议：https://www.qemu.org/docs/master/interop/qmp-spec.html 。这是协议核心，不是受保护传输或监督器；没有接入现有VM或正式App。system_powerdown响应不被转换为正常关机完成；实际进程退出与来宾结果仍由后续监督层观察。

开发后执行python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_qmp_protocol.py' -v，6项合成测试通过，覆盖分片、协商前拒绝、异步事件、旧ID、禁止命令、重复请求、畸形输入与限额。未运行Windows原生、真实QEMU或完整回归。

全部后续工作仍在进行中，不能称已完成：下一切片是经过身份核验的传输、持久监督与恢复，并接入本协议。Windows实机由用户验证，已有Smoke/清单不重复。正式目录/分支/HEAD沿用第73节，保留所有已有修改与失败现场；未提交、推送、打包或发布，无本轮VM或常驻测试实例。发布版本仍沿用历史记录，未查远端。

接续语：继续CTFLab，读取AGENTS.md、状态第74节和详细设计；QMP纯协议6项合成验证通过，继续传输与监督实现，完成可运行切片再测试；不得把协议层称为受保护控制验收，不操作旧PID或发布。

## 75. 自有子进程QMP管道传输（2026-10-23）

新增tools/ctflab_qmp_transport.py：调用方持有自有Popen及专用匿名stdin/stdout管道，接入第74节协议；独立读写线程、限额接收队列、串行请求、有界超时、断线未知状态和有限事件缓存/丢弃计数。超时不重放、不杀进程，不监听TCP、不按旧PID接管。观察进程退出码但不自动判断正常关机；退出后reap释放句柄，运行中拒绝回收。

开发后运行python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_qmp*.py' -v：协议6项加真实自有Python子进程管道集成4项，共10项通过。覆盖协商/查询/事件与响应/退出、断线、超时后进程仍存活且不重放、拒绝回收活进程。不是Windows/QEMU实测；测试清理只处理自己创建的Python夹具，没有操作用户VM。

边界：本模块只是调用方进程内的管道生命周期，不是持久监督器或认证IPC。close在阻塞I/O时只标记失效、保留进程句柄；直到自有进程及管道写端实际退出后才能reap，不能宣传无残留恢复。调用方须负责独立stderr日志、可信二进制/身份绑定、超时现场持久化。监督器退出后的重连接管、Windows端原生验证和产品入口仍待实施；没有把本切片称为G0。

正式目录/分支/HEAD沿用第74节；保留所有既有改动和失败现场，未提交/推送/重打App/发布，无真实VM或网络改动。本轮测试子进程已退出，无新增运行状态根；未检查用户其他实例。后续继续实现持久监督与身份绑定，再生成Windows实机入口，Smoke/清单不用重复。接续语：读AGENTS.md、状态第75节及详细设计，继续监督与恢复实现；协议/管道10项通过，不等于受保护控制或Windows验证通过，不操作旧PID或发布。

## 76. 监督意图持久化与身份核验核心（2026-10-23）

新增tools/ctflab_process_supervisor.py：绑定实例/代次/进程身份及自有传输PID，操作前查询内核身份，PID复用或未知拒绝控制；独占操作锁、不可覆盖的绑定/意图/结果记录、写入flush/fsync，先记意图后发送命令。相同操作ID不重放；超时记录unknown；遗留锁保留供现场核验。恢复入口只读报告身份及未完成意图，不重新接管旧PID或匿名管道。退出记录不以returncode=0推断正常关机。

这是监督核心，仍不是可独立重启的后台服务：调用方必须提供已验证私有根guard、真实身份观察器和持有的Popen传输，未接GUI/CLI或Windows真实QEMU。目录元数据未做跨平台断电一致性保证；同用户恶意篡改不在此层防御范围。未完成结果只报告，不自动补执行。尚需原生接入、后台服务/重连路径和真实故障验证，G0保持未完成。

开发后新增7项合成测试通过：先落意图、禁止重放、PID复用/未知拒绝、超时unknown、中断意图、遗留锁、退出不提升关机结论。入口python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_process_supervisor.py' -v。本轮没有真实VM、Windows原生、断电或完整回归证据。

正式目录/分支/HEAD沿用第75节；已有改动与失败现场保留，未提交/推送/打包/发布。测试只使用临时夹具，无常驻进程/VM状态根移交，未操作用户实例。接续语：读取AGENTS.md、状态第76节和详细设计，继续把监督核心接到Windows自有进程及控制入口，完成端到端切片再验收；不要将核心单测称为持久后台恢复可用，不重复Smoke/目录清单或操作旧PID。

## 77. Windows后台控制完整开发入口与集中验收包（2026-10-23）

按用户要求不再逐模块交接，本轮把第74—76节协议/管道/监督接成完整开发验收入口。`tools/ctflab_windows_control.py` 提供start/status/powerdown/recover：固定Smoke独立磁盘、全安装目录清单复核、WHP/哈希/空间门禁、普通用户私有ACL请求目录、后台独立进程、原生生命周期锁、进程身份、操作意图及退出结果。关控制终端不主动结束后台；新客户端通过文件通道查询与请求正常关机；没有TCP监听、HMP、quit、磁盘commit或旧PID自动接管。

集中交付：`output/windows-v2-20261023/CTFLab-Windows-control-r1.zip`，SHA-256 `bd001ff0cc7c18a63370bfbdd64c499be26118c76bd3042f3d6f7bf23ae85242`，旁有SHA256-control-r1.txt。[集中操作说明](ctflab-windows-control-acceptance-2026-10-23.md)与[验证记录](verification-windows-control-2026-10-23.md)。构建器可复现，旧包未覆盖；逐文件与最终源码一致、ZIP CRC/MANIFEST哈希通过，隔离解压包内36项测试全部通过。包只含源码/测试/文档，不含镜像、QEMU、用户清单或凭据，不是正式App。

本轮首次集成13项中2失败：断线/非法QMP的操作级unknown未同步到实例failure记录，已修复并保留首轮日志。最终针对性20项（19控制流程+1包验证）通过；包验证内部另跑上述36项。覆盖独立后台/客户端退出再查询、双实例互不影响、重复/部分请求、实例/代次不符、启动意图阻止重启、未知身份/超时/断线留证、日志上限及写失败仍排空、源盘读取失败记录未知。Windows运行和真实来宾并未在本机执行。

本机真实QEMU补充验证：无磁盘/无来宾/无网络设备、machine=none、TCG暂停进程，实际QMP协商与query-status=prelaunch通过；只终止并回收本轮自有该进程。证据local-qemu-protocol.json，不算WHPX/Windows/课程验收。

第一轮完整回归966项，951通过/15跳过，213.172秒；日志control-full-regression-first.log。该轮启动后追加了日志失败/原盘未知等保护，专项已验证；最终全量复验969项，954通过/15条件跳过，213.642秒，退出码0（control-full-regression-final.log）。所有日志位于output/windows-v2-20261023，失败记录保留。

关键边界：这是可集中测试的Windows原型开发交付，不是所有43项路线图完成。新组合的Windows原生ACL/后台控制/QMP/退出需要一次集中实测；已有人工Smoke与清单不用重跑。监督器本身异常退出后匿名管道不能恢复接管，recover只做身份核验和保留现场；SDL显示窗口不能重建。完整G0/G1、网络/共存、GUI/安装器、课程和扩展仍未验收，不能借本轮测试提升状态。后续按这些真实依赖推进，不把“等待用户实测”写成通过。

正式目录/分支/HEAD仍为/Users/pufei/Downloads/ctf-lab、codex/release-0.1.1-preview-20261010、0994f62。既有改动、原始镜像、旧测试目录及失败现场保留；未提交/推送/正式发布、未重打Mac App，发布版本沿用历史v0.1.2-preview.20261015（未查远端）。本轮只有自有临时Python和无来宾QEMU测试，无Windows/真实来宾状态根；后续不能按旧PID操作。

接续语：先读AGENTS.md、状态第77节与集中验收说明。Windows后台控制已完成开发集成和本地测试，统一control-r1包待用户集中实测；不重复旧Smoke/目录采集。处理该包回传后推进尚缺的监督恢复/显示/网络与产品门槛；保留所有改动与失败现场，不操作旧PID或发布。

第77节最终收口：最终包与源文件SHA逐项再次一致，汇总证据control-final-evidence.json；全量测试会话和本轮自有子进程均已退出，未终止其他既有Python/用户进程。跳过保留为5项Windows原生、5项显式QEMU/桌面E2E及5项历史产物条件检查。文档/语法/空白检查按最终版本复核。

## 78. control-r1 Windows合成测试回传与清单路径问题（2026-10-23）

用户回传：控制流程19项通过（6.935秒）、QMP10项通过（1.599秒）、监督7项通过（0.099秒），合计36项无跳过。wrong_platform用例的“仅Windows原生入口”是故意模拟不支持平台的预期输出，不表示当前Windows被拒绝。上述是在Windows运行的合成/自有Python子进程证据，不是真实QEMU新控制链通过。

随后start使用相对runtime-after-smoke.json报“JSON必须是普通文件”。本轮核对实际入口：prepare中先校验固定QEMU/基盘和WHP，再读取传入清单；read_json的is_file失败发生于新状态目录创建/复制/后台启动之前。本次失败未创建本轮目录或启动VM；不推断此前其他运行目录不存在。该提示不能单独区分路径缺失/指向目录/不可访问，常见原因是清单还在上轮inventory包目录。下一步使用原清单的实际路径或先复制到control包目录；不重新采集清单，不重跑已通过36项，不删除旧实例。

本轮只记录回传与只读核对源码，未改实现/包、未运行VM、未提交/推送/发布。其余目录/分支/HEAD及保护边界沿用第77节。接续：处理清单路径后继续同一集中Windows验收，保留现有结果和失败，不提升G0。

## 79. control-r1 Windows真实查询与关机闭环回传（2026-10-23）

用户修正清单路径后start返回worker-created，并报告出现Smoke login、无IP；无网络是本轮固定参数的预期行为，非网络故障，也不算网络验收。两次独立status均acknowledged、qemu_status=running。用户按指引进行了第二次查询，但尚未明确文字确认其间确实关闭并重新打开终端，故控制客户端退出独立性保留为待明确，不据两条查询输出自行推定。

powerdown操作abb2e211-b6f8-4674-85e0-23d1b307a346返回acknowledged。随后recover返回持久result：state=exited、returncode=0、shutdown_guest_event=true、source_unchanged=true、control_failure=null、events_dropped=0、stderr_complete=true、control_ready_recorded=true。接受该固定Windows构建/Smoke无网络实例的新后台控制链“运行查询→QMP正常关机请求→来宾关机事件→进程退出→源盘未变”的用户设备回传证据。不要求重复该闭环。

worker_identity/qemu_identity=unknown表示recover当前无法确认旧进程身份；结合已落盘退出记录，与进程已退出相容，不能单独把unknown当作失败或严格的当前进程不存在证明。control_reconnected=false符合只读恢复查询，无重连操作。graceful_stop_verified与g0_passed仍为false，保留原始机器字段；人工与事件/退出证据单独登记，不伪造自动验收位。

回传JSON按用户消息逐字转存（文件尾增加换行），不是直接读取Windows源文件：output/windows-v2-20261023/control-user-return/{powerdown-message,recover-message}.json。原用户消息保留；尚未收到host.json、原result.json、stderr文件和本轮ZIP哈希，设备/完整产物绑定及警告内容仍待补齐。不能把stderr_complete=true解读为没有警告。

G0/G1仍未完成：监督器异常后的控制重接管、显示重连、负向访问/故障矩阵及网络另验。新控制链正向闭环已有结果，后续不继续表述为全部Windows未测。用户实例目录为C:\CTFLab-Test\Smoke-OVA\w01-control-01，用户回传记已退出；保留该独立磁盘/日志，不按旧PID操作。

本轮仅归档消息并更新状态/台账，未改源码、包、原盘，未操作用户VM、提交/推送/发布。正式目录、分支、HEAD沿用第78节，历史发布版本未变（未查远端）。本机无新增测试进程或真实来宾状态根。接续语：读取AGENTS.md、状态第79节，control-r1真实QMP查询与关机闭环已获回传；保留证据，补必要产物绑定后继续未完成恢复/显示/网络工作，不重做已通过闭环或自动发布。

## 80. 通用代次存储、场景协调与离线工具交付（2026-10-23）

本轮响应“完成所有可做的内容/继续”，推进不依赖新设备的实现与验证，但没有把整个43项路线图宣称完成。[交付说明](ctflab-offline-delivery-2026-10-23.md)、[独立验证](verification-offline-foundation-2026-10-23.md)、[社区协作准备](ctflab-community-workflow-2026-10-23.md)是新入口。

新增GenerationStore与ScenarioCoordinator：真实独立文件复制、基盘与UEFI变量哈希、空间预检、操作意图、DAG启动/逆序正常停止、代次原子选择、旧进度/失败副本保留；接通LocalService契约。修复部分启动失败后的显式正常停止路径，仍须全部节点现场身份已验证，不授权强杀。后端为可信宿主注入；本轮仅以合成driver验证，没有接真实QEMU/网络/显示生产后端，也没有删除/回收功能。首次准备失败尚无自动恢复入口；后续reset可核验旧代次后另起尝试，失败副本保留。

新增跨平台离线入口`tools/ctflab_offline.py`：拓扑HTML/SVG、观测绑定/时效、草稿校验与差异、网络应通/禁通计划、C05课程生成/校验、已有Windows材料脱敏摘要。拓扑设计不代表实测可达；不执行扫描或修改宿主网络。C05使用新编合成文本，学生包内独立校验器不含答案；教师答案独立包，生成器供教师使用。Windows摘要只读取已有control-r1材料、记录摘要和缺失项，不要求重做第79节闭环，不操作旧PID或上传数据。

本轮初始完整回归998项有2失败：新增协调器未进入打包白名单、文档缺历史快照标记；实际依赖与文档均已修复，11项专项复验通过。离线暂存包首次43项测试通过但额外隔离CLI入口失败，修复Python -I路径并新增回归后，44项隔离验证通过。最终代次专项18项、离线专项14项通过；首次失败日志保留。完整复验与最终产物摘要见随后收口记录，不把初次回归写为通过。

证据与产物根`output/offline-foundation-20261023`：`topology.html`、`network-checks-example.json`、`C05-r2/C05-student.zip`、`C05-r2/C05-teacher.zip`及测试日志。旧C05/暂存包用于追溯，不作为最终入口。原始镜像、旧control-r1包、已有用户改动均保留。

剩余工作含实际开发：Windows可重连接管的受保护控制与显示方案、原生故障/权限探针、网络执行、生产driver、GUI/安装器；还有实机/签名/最终包/课堂外部验收。不能将其统称“只等用户测试”，G0/G1保持未通过。Docker/Linux/远程/外部VM/AD等按原任务依赖继续。本轮社区模板已写，维护责任人和实际反馈入口待指定，未配置远端。

正式目录`/Users/pufei/Downloads/ctf-lab`，分支`codex/release-0.1.1-preview-20261010`、HEAD `0994f62`。未提交/推送/正式发布或重打Mac App；历史发布仍沿用v0.1.2-preview.20261015，未查询远端。本轮无真实VM/网络实例，仅临时文件、自有Python测试与无头浏览器；测试进程结束状态在最终收口核验，不操作用户其他实例。

接续语：继续CTFLab，正式目录`/Users/pufei/Downloads/ctf-lab`。先读AGENTS.md、状态第79—80节和本地交付说明，现场核验Git与相关实例，保留已有改动/资产/失败证据。Windows正向查询关机已有回传，不重做；下一步优先补可恢复控制/显示与生产driver，再接网络和双节点课程。不要把合成协调器、离线拓扑或源码包称为Windows产品已完成，不自动停止VM、删除资产、提交或发布。


第80节最终收口：完整复验1000项，985通过/15条件跳过，224.732秒；日志full-regression-final.log，执行会话已正常退出。该轮加载后补充的隔离CLI/学生校验器另以最终代码44项隔离测试通过（0.631秒）覆盖；不把后补修改冒充已加载进全量。7项文档检查与语法/白名单/空白检查通过。最终源码工具包为output/offline-foundation-20261023/CTFLab-Offline-Foundation-20261023-r1.zip，SHA-256 bfcf8a933ec7a52ae0c7d149517a2beec814c359514812c4155640ef80c1009c；CRC、MANIFEST、源码一致性、包内文档链接和已测r3工具/测试字节一致性通过。final-evidence.json记录结果，SHA256-offline.txt提供摘要。早期不带r1的ZIP和staging包仅追溯，不是交付入口。

最终课程入口C05-r2：学生ZIP SHA-256 60b6c8a8886d7ee16586dc535bcfb43ce0308f57b50efa6d626b8544afbb481b，教师ZIP SHA-256 ad88562d583a946220a7c7e315ee9d7a493bd8b00fddbf1dcc0fec538edb726c。学生独立校验器实际运行，7个文件通过。自有测试执行会话与用于故障测试的Python子进程已退出；未创建或移交本轮真实VM实例，未检查/停止用户其他实例。无头浏览器仅用于本轮离线HTML检查。未提交、推送、发布、重打Mac App；仍保留全部原始资产、既有改动和失败证据。

## 81. Windows TLS可重连控制、显示与固定运行候选（2026-10-23）

按第79—80节接续，新增独立 `ctflab_windows_recovery.py`，保留旧control-r1与全部已有改动。QEMU自持仅回环双向TLS控制/显示端点，客户端核验私有证书、实例名称和原生进程身份；关机落盘意图后只发一次，未知结果不重放。新增受限RFB显示客户端与Tk窗口、实际固定Smoke/WHPX启动入口；不是只有合成driver，但尚未接通通用ScenarioCoordinator生产driver。

[候选使用与限制](ctflab-windows-recovery-2026-10-23.md)、[独立验证记录](verification-windows-recovery-2026-10-23.md)为本阶段入口。源码候选ZIP位于 `output/windows-recovery-20261023/CTFLab-Windows-Recovery-candidate-r1.zip`，SHA-256 c4b38ccc0965a5b111cec41ee072ac2cf38cfc0c4cc65b6884ccececf4772735；不含私钥/镜像/运行时。

本机无来宾QEMU验证QMP与VNC双向证书连接、重复连接、无客户端证书拒绝、错误实例名拒绝及640×480 Raw帧；11项专项通过，独立源码包47项通过，CLI隔离入口与CRC/清单核验通过。原生身份故障/意图重放用合成观察器测试，不代表Windows故障接管已通过。完整回归收口结果随后补记。

未完成：Windows固定构建TLS实测、监督器退出后的原生恢复/退出记录、显示窗口与来宾键鼠、日志配额、证书续签、通用场景生产driver及网络；G0/G1仍未通过。已知边界：启动后绑定前崩溃不能自动接管；监督器死亡后不能补造进程退出码；证书30天后失效，不自动续签/重启。完整限制见候选说明，不把剩余工作全部归为等待用户测试。

正式目录 `/Users/pufei/Downloads/ctf-lab`；分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f62`。未提交/推送/发布/重打Mac App，已发布版本仍沿用第80节历史记录。本轮只创建无磁盘无来宾测试进程，均由测试终止并等待退出；未检查或停止用户其他VM。临时证书仅属于自动测试临时目录，现有资产/失败证据/旧运行目录均保留。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、当前状态第79—81节与Windows可重连候选说明；保留改动与失败证据。优先补通用生产driver、持久退出观测及Windows新实例的原生恢复/显示验收，不重做旧control-r1正向闭环；不自动停止现有VM、删除资产、提交或发布。

第81节最终收口：完整本地回归 `python3 -B -m unittest discover -s tools/tests -v` 共1012项，996通过/16条件跳过，219.105秒，执行会话正常退出；记录 `output/windows-recovery-20261023/full-regression-first.log`。其中无来宾QEMU用例默认条件跳过，已在11项专项与47项独立包测试中显式启用并通过。本轮本机QEMU版本11.1.0，不代表Windows固定构建。7项文档检查、6个相关模块语法检查、差异空白检查通过；最终包每文件与当前源码及清单一致，`final-evidence.json` 与 `SHA256SUMS.txt` 已写入证据根。全部本轮测试执行会话已结束，独立QEMU fixture由测试持有Popen对象并等待退出，无待继续运行的本轮实例；未按历史PID操作。保留日志中的弃用警告，未改动历史失败证据。

## 82. 通用 QEMU 后端与 Windows 独立退出观测（2026-10-24）

按第81节继续，已读取 AGENTS.md、现场核对正式目录与 Git，保留全部既有修改、旧运行目录和 r1 包。新增 [后端与原生验收说明](ctflab-production-driver-2026-10-24.md)、[独立验证记录](verification-production-driver-2026-10-24.md)。

工作区新增 `tools/ctflab_qemu_driver.py`，接通 GenerationStore/ScenarioCoordinator 的实际 QEMU 启动、正常停止、只读恢复与显示重连；有 init/prepare/start/status/display/recover/stop/reset CLI。运行 profile 固定到实例，启动前核验运行时清单、原盘摘要和运行盘自包含格式。绑定计划、代次、盘文件身份、进程创建时间/映像路径与双向 TLS，启动意图、旧代次和每次启动目录均保留；未知结果不重放、不强杀。

当前范围为 Windows x64/WHPX、BIOS、IDE/VirtIO、每网段恰好两个节点的回环 socket 链路，不回退 TCG，不提供宿主出口。ARM/UEFI/SATA、更多节点共享同一网段尚未实现；回环数据链路未做跨用户认证，来宾静态地址/应通禁通矩阵未实测。此为可执行后端候选，不是通用产品验收全部完成。

新增 Windows 保留内核句柄 API 与独立 observe-exit 进程，监督器退出后仍可由独立观测器记录相同内核对象的退出码；观测器必须先成功持有句柄。已接入固定 Smoke 源码与新通用后端；退出码不代表正常关机或来宾健康。绑定前崩溃、观测器未就绪、监督器/观测器同时消失仍保留未知，不伪造结果。原生测试用例让父进程创建短寿命 Python 子进程及观测器，再自愿退出；测试不操作 VM。

2026-10-24 验证：完整本地回归1032项，1014通过/18条件跳过，221.439秒；显式启用本机无来宾QEMU的通用专项14项、恢复专项13项通过；最终Windows相关77项，70通过/7条件跳过。完整回归加载后补充的显示入口、用户配置禁用、监督器身份记录和原生测试拓扑由专项覆盖，不冒称已加载进早先完整回归。一次过宽测试断言把 `-no-user-config` 当作 user 网络而失败，修正为检查 netdev 值后14项通过，失败日志保留。新增原生退出专项4项中3通过、1仅Windows用例跳过。临时隔离包53项，51通过/2条件跳过，CRC/清单/CLI入口通过。证据根 `output/production-driver-20261024`。

未完成：当前没有可访问Windows主机的连接信息，尚不能完成原生句柄、固定Windows QEMU/WHPX、监督器故障后的真实VM恢复/退出记录、真实显示键鼠与来宾网络/服务验收；G0/G1仍未通过。证书续签、日志配额、GUI/安装器和更广泛硬件/网络支持仍有实际开发工作。第79节旧control-r1正向闭环不用重做。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`；保留大量已有未提交文件，本轮未提交、推送、发布、重打Mac App或创建新发行包。已发布版本仍按历史记录为 `v0.1.2-preview.20261015`，本轮未查询远端。旧 `output/windows-recovery-20261023/CTFLab-Windows-Recovery-candidate-r1.zip` 未覆盖，新源码不能代表旧包内容。

本轮仅创建自有短寿命Python测试、空白磁盘/暂停CPU的无来宾QEMU fixture及临时隔离源码包；QEMU由测试持有Popen对象并等待退出，不按历史PID操作。没有启动、停止或重置用户VM，没有删除用户资产或旧证据。最终进程与执行会话核验见本节收口补记。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第82节与 `docs/ctflab-production-driver-2026-10-24.md`，现场核验Git和实例并保留已有修改。下一步在用户提供的Windows专用新测试环境执行原生退出用例及固定构建恢复/显示/网络验收；没有环境时不要把Mac通过或Windows跳过写成原生通过。不要自动停止已有VM、删除资产、提交或发布；不要重做旧control-r1闭环。

第82节收口补记：完整回归、Windows专项与临时隔离包执行会话均已正常退出；最终本机进程名称快照未发现 `qemu-system-*`，不据此推断远端/其他平台实例状态。7个相关Python文件语法、入库白名单、空白检查及 `git diff --check` 通过。最终源码摘要、测试范围和未通过的原生门槛写入 `output/production-driver-20261024/final-evidence.json`，检查日志为 `final-checks.log`。无本轮待继续运行的实例；后续仍须现场重新核验，不按本记录操作PID。

第82节用户自测交付补记（2026-10-24）：用户明确 Windows 实测由自己执行，并要求具体源码及步骤。已生成本地测试源码包 `output/production-driver-20261024/CTFLab-Windows-Test-20261024-r1.zip`，SHA-256 `88acb527e19450c1defefa217cdd6fa22a9ce0eb54d4a57a54b08cd67d8ee26a`。包内README为新增 `docs/ctflab-windows-test-steps-2026-10-24.md`，包含环境核对、无VM原生测试、固定新Smoke实例重连/显示/正常关机、日志回传及通用后端入口；补齐原生、通用driver及其依赖测试源码。隔离解压测试105项，100通过/5条件跳过，6.171秒；CRC、逐文件摘要与两个CLI入口通过，日志 `test-kit-validation.log`。这是用户请求的本地源码测试交付，不是正式发布或App重打；旧r1包不变，Windows实测状态仍待用户回传。未操作用户VM。


### Windows 原生测试用户回传（2026-10-24）

用户在 Windows 自行执行测试源码包，并在本聊天粘贴控制台结果；未由助手远程执行，也未收到原始日志文件或独立核验主机/源码摘要。`test_ctflab_windows_native.py`：8项，6通过、2项非Windows边界测试按预期跳过，0.008秒；包含真实进程身份重复查询、原生文件锁竞争与释放。`test_ctflab_windows_exit_observer.py`：4项全部通过，8.436秒；关键 `test_independent_observer_survives_parent_exit` 为 ok，确认本用例下父进程自愿退出后，独立观测器仍记录短寿命Python子进程的退出码。

据此将“Windows原生身份/锁基础”和“Python测试进程的独立退出观测”更新为用户回传通过。PowerShell在合并原生命令stderr时显示NativeCommandError，但两组unittest最终均为OK；未回传进程退出码，不据该包装提示认定用例失败。无需重跑已通过用例。

范围不扩大：真实QEMU监督器故障、WHPX/TLS固定构建、来宾显示/键鼠、正常关机与网络/课程验收仍待执行，G0/G1未通过。下一步按自测步骤第3—5节，在核验固定运行时/基盘后使用新的Smoke运行目录验证显示和重连。未操作用户VM、未修改实现、未重打包或发布；旧日志与历史待验记录保留为当时状态。

第82节Windows启动诊断补记（2026-10-24）：用户新实例 start 返回被统一处理的 ValueError，尚无具体异常原因或启动成功证据；正在通过只读检查核对依赖、固定文件与运行目录阶段。保留现场，不重复启动、不清理或操作进程。原生基础/独立Python退出观测的用户回传通过仍有效，不扩大为真实QEMU恢复通过。


Windows固定恢复候选用户回传补记（2026-10-24）：依赖版本不符及清单路径不存在的问题经用户调整后，start 返回 worker-created，observer-ready.json 存在。首次 status 返回 FileNotFoundError；随后用户通过 RuntimeClient.status() 只读直连得到 identity=running、control_reconnected=true、qemu_status=running、unfinished_operations=[]。据此记录“该Windows实例原生身份核验及双向TLS QMP重连：用户回传通过”。首次缺文件异常未复现，未取得其具体路径/堆栈，不能归因为已确认的启动竞争或宣称已修复。

用户回传worker-console日志为空，QEMU日志含旧-mon参数弃用及Ignoring request for interrupt vector 0警告。保留两项警告，不将查询成功扩大为来宾正常启动或警告无害。显示、登录、键鼠、窗口重连、正常关机/退出持久记录及真实监督器故障仍待验；G0/G1保持未通过。用户Windows实例可能仍在运行，助手未远程核验或操作，不按历史PID停止。下一步由用户在同一实例打开显示并验证来宾交互，无需重复start。


Windows显示与键盘用户验收补记（2026-10-24）：用户回传CTFLab实验显示截图，窗口显示已连接（Raw显示），Smoke已到Linux登录提示；随后明确反馈“可以正常输入和显示”。据此记录该固定Windows新实例的来宾登录提示画面、显示链路及键盘输入为用户实测通过。未据此认定登录成功、鼠标交互、窗口关闭后的重连保留会话、监督器故障恢复或正常关机通过。下一步由用户验证显示重连，保留运行实例；助手未操作VM、未提交或发布，G0/G1仍未通过。


Windows显示重连用户验收补记（2026-10-24）：用户按步骤在Smoke登录提示输入标记且不提交，关闭显示窗口后重新执行display，并明确回传“保留了”。据此记录“关闭显示窗口后重新连接并保留来宾输入状态”为用户实测通过。仅覆盖显示客户端退出/重连，不等同于监督器死亡、宿主重启或VM重启恢复。正常关机及匹配的observer-exit持久记录仍待核验；真实监督器故障、网络和课程服务仍待验，G0/G1保持未通过。助手未停止VM或执行其他现场操作。


Windows关机与持久退出用户验收补记（2026-10-24）：用户对该专用新Smoke实例执行一次powerdown，返回acknowledged、automatic_replay=false；等待15秒后status返回identity=exited，result.state=exited、returncode=0、source=retained-native-handle，observer-exit.json存在。RuntimeClient读取该记录时会比对实例/代次和binding身份；据用户回传记录“单次ACPI关机请求获确认后QEMU实际退出，独立原生句柄观测的持久退出记录可读”为通过。result.identity.state=running为启动时保存的身份快照，当前退出状态以外层identity/result.state为准；control_reconnected=false与退出后直接读取持久记录一致。

保留graceful_stop_verified=false，不据退出码0断言来宾服务完整关闭、文件系统一致性或已采集来宾关机事件。当前基础链路已有用户实测：原生身份/锁、Python父进程退出后的独立观测、固定QEMU TLS查询、显示/键盘、显示重连保留输入状态、关机请求后实际退出和持久记录。真实QEMU监督器故障恢复、原盘关机后摘要复核、来宾网络/课程服务及完整产品门槛仍未完成，G0/G1未通过。用户报告该实例已退出，助手未远程独立核验或按历史PID操作；保留运行目录、日志和证书，不自动清理、提交、重打包或发布。


Windows固定Smoke基础流程收口（2026-10-24）：用户按关机后原盘SHA-256核对步骤明确反馈“没有变化”，据此记录原盘摘要关机后复核为用户回传通过（预期摘要f9c2edc334c9e2839c1d605d6d870e8f68ad1242f892fe3f96ed75bfaf554052；未收到原始命令输出，不冒称助手独立核验）。本轮固定Windows新Smoke实例的基础流程已完成用户实测：原生身份/锁与Python独立退出观测、QEMU TLS查询、来宾登录提示画面/键盘、关闭显示后重连保留输入、单次ACPI请求后QEMU以0退出、匹配的持久退出记录、原盘摘要不变。

该收口不是完整Windows产品或通用生产后端验收：真实QEMU监督器故障恢复、通用多节点网络应通/禁通、来宾服务/课程与安装分发等仍待验；graceful_stop_verified保持false，G0/G1保持未通过。用户回传实例已退出，现场目录与日志保留，不按历史PID操作。无新增实现变更、自动清理、提交、推送、打包或发布。

后续接续语：继续 `/Users/pufei/Downloads/ctf-lab`，读取AGENTS.md、状态第82节末尾及 `docs/verification-production-driver-2026-10-24.md`。固定Windows Smoke基础流程已有用户实测闭环，不必重复；先核对源码与现场，下一阶段明确选择真实监督器故障恢复或通用多节点网络验收。Windows操作由用户执行，保留既有目录与资产，不自动停止VM、删除数据或发布。

## 83. 全路线图跨阶段集成候选（2026-10-24—25）

用户要求后续所有任务一起推进并集中验收，进一步明确包含桌面界面、安装分发及全部43项。已读取AGENTS.md与第82节末尾，核对正式目录/Git并保留所有原有改动。用户确认暂没有额外x64 Kali/Web、Windows/AD合法镜像、Linux/SSH环境和Windows签名证书；这些缺口集中登记，不重复索要。固定Windows Smoke基础流程沿用第82节用户实测闭环，不重做、不把其范围扩大为通用产品通过。

### 本轮落地

- 精确绑定QEMU/监督器/独立观测器的故障注入：监督器处理一次持久请求后自行退出73，请求方预先保留监督器句柄并等待真实退出；QEMU和独立观测器保持独立。Windows真实QEMU新故障路径仍待用户集中实测，不按旧PID结束进程。
- React/Tauri桌面薄壳与本地契约/独立后台接通，提供课程/宿主配置导入、准备、启动、保存停止、取消、重置、恢复、节点显示重连、只读拓扑、清单草稿差异和诊断预览。后台执行身份单独核验，重复请求不重复派发；关闭管理窗口没有停止动作。Mac原生编译/链接通过，浏览器双节点夹具通过，不等于Windows GUI验收。
- Windows运行时白名单暂存/清单复核/独立Python探针及NSIS/WebView2离线安装配置；签名版本库、原子激活和手动回退API。没有Windows最终安装包，安装迁移/自动更新协调仍有开发工作，Ed25519载荷签名不等于Authenticode。
- 单HTTPS源签名索引、有效期/防回滚序号、Range续传、内容摘要、损坏隔离、师生材料分离、引用保护与显式预览回收；GenerationStore在创建实例前自动登记受保护缓存引用。实例/旧代次/失败现场引用没有安全删除协议时持续保留，不自动解除或清理。
- Linux x64/KVM普通用户能力门禁、boot ID/创建时间/映像身份与独立pidfd退出观测接入通用后端；无法取得的独立退出码保留null。Linux原生/KVM/最终包未验，Linux监督故障注入入口暂拒绝。
- Mac既有回环交换机默认64MiB PCAP配额、完整记录边界、配额丢帧/截断计数、实例/代次元数据与旧捕获保留；未接入通用socket后端，不冒称通用O01完成。
- 集中只读快照与故障恢复/同盘继续/整课重置比较工具，核对进程/启动记录/代次/原盘，重置检查新基线与旧进度仍保留，不自动给网络或课程打勾。

实现与集中入口：[集成说明](ctflab-integrated-candidate-2026-10-25.md)。独立记录：[本轮验证](verification-integrated-candidate-2026-10-25.md)。全部43项当前增量和未实现部分已同步[执行台账](ctflab-roadmap-execution-2026-10-21.md)末尾。

### 验证、失败与交付

最终 `python3 -B -m unittest discover -s tools/tests -v`：1086项，1065通过/21条件跳过，224.813秒。明确启用本机无来宾QEMU专项14项通过；React模型5项、生产前端构建、Rust1.90源码检查及Mac原生链接通过。隔离解压源码包196项，188通过/8条件跳过，6.804秒；86文件CRC/摘要和5个CLI隔离入口通过。59个包内Python源码语法检查通过。

首轮完整回归1083项仅1个旧文档缺历史快照声明而失败；PCAP首轮过严链接检查误拒macOS系统别名；Rust首轮版本不足、随后缺图标。均已修正并通过对应最终检查，原失败日志保留，不隐去失败/条件跳过。包内生成README与仓库README的错误映射检查也保留错误报告，最终按真实生成源核对无漂移。全部日志/源码摘要根为 `output/roadmap-integration-20261024`，最终范围在 `final-evidence.json`。

新本地交付：`output/roadmap-integration-20261024/CTFLab-Integrated-Source-20261025-r1.zip`，SHA-256 `728d260277ec09c9fb6b96cc96110e877c3e0d6de3650757129190b236e1bd7c`。仅源码、测试、界面源及构建/验收脚本，不含镜像、运行时、私钥、用户现场或安装器。旧Windows r1、10月24日测试包及已发布Mac App没有覆盖。**本轮不要求用户现在逐项执行这些入口，总验收尚未启动。**

### 尚未完成与接续

全部43项尚未完成，不能概括成“只等用户测试”。独立开发缺口仍包括：完整G0负向矩阵、证书续签/后台日志配额、Windows安装迁移/自动更新、图形连线编辑、路由/DNS/时间/网络规则、校内镜像服务、Docker整合、SSH/租约/多用户/数据通道、E01→E02→E03外部接入、真实课程及隔离分析器等。Windows实机故障恢复、通用多节点来宾网络/服务、Linux/KVM、最终安装/干净机/跨设备/课堂和签名仍未验。graceful_stop_verified、G0/G1不因上述本地测试自动变为true。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`；保留大量既有和新增未提交/未跟踪源码。本轮无提交、推送、公开发布或旧Mac App重打；仅新增源码候选和Mac桌面调试可执行文件。已发布版本仍沿用历史 `v0.1.2-preview.20261015`，本轮未查询远端发布。

资源收口：所有本轮执行会话已结束，自有127.0.0.1:1420预览服务已停止，端口复查无监听；本机最终名称快照未发现qemu-system进程。仅运行测试自己持有的空白磁盘/暂停CPU QEMU和临时测试文件，没有启动/停止/重置用户VM、修改宿主网络、删除用户磁盘/旧证据或清理现有镜像库。远端Windows实例未独立核验，只保留第82节用户“已退出”的反馈；记录不是以后操作PID的依据。

接续语：继续CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读AGENTS.md、状态第83节、跨阶段集成说明和执行台账末尾，核验Git/源码/实例并保留已有改动。目标仍为全部43项连续推进、最后一次总验收，不重做Windows Smoke基础闭环。当前镜像/SSH环境/签名证书暂缺，继续尚未实现模块，不把缺口全写成待实测；Windows操作由用户集中执行。不要自动停止已有VM、删除资产、提交、推送或发布。

## 84. 受管来宾、图形草稿与镜像材料（2026-10-25）

按用户要求读取AGENTS.md和第83节、核对正式目录/Git并保留全部既有修改；继续全43项，包含界面和安装分发，最后集中验收。Windows Smoke基础流程不重做，镜像/SSH环境/签名证书暂无的已知回答不重复索要。实现见[本轮说明](ctflab-managed-guest-2026-10-25.md)，验证与失败见[独立记录](verification-managed-guest-2026-10-25.md)，路线图末尾已逐项同步本轮增量。

### 已落地的开发切片

- 图形拓扑草稿：节点/网段/网卡连线、拖动与键盘连接、设计地址、新增/移除/断开、完整清单往返、后端差异校验后导出。任何编辑或实验目录变化使校验失效，迟到旧结果不能启用导出；不修改运行实例。浏览器实际检查3节点/2网段/4条SVG连线及草稿同步。
- 专用Linux来宾代理：宿主回环双向TLS转固定virtio串口；派生DMI UUID、实例/代次/策略/profile和运行进程身份绑定。只允许固定操作，不提供来宾网络管理监听或任意命令。原profile未启用agents时保持兼容，已启用时禁止热改策略。
- 来宾网络/DNS/本地时间：检查专用QEMU/root标记与固定工具摘要，无默认出口、接口MAC/地址验证、确定性方向规则和IPv6默认禁通；不清空全局规则、不做NAT。固定DNS/chronyd unit不自动重启、不超时强杀；chronyd -x不改系统时钟，不能代表可信UTC/AD。宿主/来宾每次副作用前落意图，重复操作不重放；中断保留unknown。后续服务/容器动作重验当前接口、转发开关、实际nft规则摘要，拒绝VM重启后过期账本。
- 受限容器入口：仅专用来宾固定Unix socket；digest/非root/只读/无capabilities/CPU内存日志配额、内部bridge、带代次标签命名卷，准备不启动；停止只发一次SIGTERM，无强杀/删除。原生Docker未验，离线OCI和容器跨网路由仍未实现；D02明确拒绝，不能勾选完成。
- 代理与容器操作接入桌面和LocalService异步后台，不绕过锁、代次及取消边界。新增专用来宾安装材料生成器：仅生成新目录；安装器拒绝非专用Linux QEMU、覆盖既有文件或工具不符；未在本机/用户VM安装，未启动来宾服务。
- 纯学生内容镜像：保留完整原签名索引/字节，仅允许student且许可明确允许再分发；混教师/仅配方索引先拒绝，不能裁剪后复用签名。显式HTTPS镜像只替换下载传输根，信任来源不变。未部署网络服务，P04仍有运营/部署工作。

### 实际验证及交付

完整 `python3 -B -m unittest discover -s tools/tests -v`：1125项，1104通过/21条件跳过，219.215秒。全量加载后追加的3项重启一致性增量和隔离入口修复，由最终来宾32项（全通过）、隔离源码238项（230通过/8跳过，7.083秒）覆盖，不冒称全量已加载后改动。真实无来宾QEMU参数/TLS专项18项通过；镜像6项、桥接6项、React模型12项通过；前端生产构建、Mac原生调试链接通过。无Linux来宾或新增Windows实机结果。

首版隔离源码测试235项通过（8跳过），但guest_kit的 `-I --help` 缺固定模块目录而失败，修复后r2八个入口通过；旧r1包/失败日志保留。较早镜像专项因测试类直接导入重复发现缓存用例，改为模块别名，最终镜像只计6项。重启一致性问题来自实现复核，追加实际状态指纹检查并通过专项，不伪称先有真实来宾故障回传。

最新本地源码包 `output/managed-guest-20261025/CTFLab-Managed-Guest-Source-20261025-r2.zip`，SHA-256 `43cd800aa151b5943474673798badea769727899e856d55891a61f8488d42512`，101文件摘要/CRC、70个Python语法和8个隔离入口通过。另有 `dedicated-guest-bootstrap-r2`（14文件）和浏览器证据 `browser-assertions.json`、`graph-ui-fixture.png`。不含镜像/运行时/密钥/用户现场/最终安装器，不覆盖前轮Windows/源码包。本轮不要求用户立即执行单项测试，集中总验收尚未启动。

### 未完成、现场与继续入口

全部43项尚未完成，仍有实际开发：完整故障负向矩阵、证书续签/后台日志配额、安装迁移/自动更新、OCI装载/容器跨网、部分来宾效果对账修复、SSH/租约/多用户角色/数据通道、外部Kali→Windows→AD、真实课程及隔离分析器等。已有来宾网络、服务、容器代码尚无Linux真实执行/应通禁通证据；新Windows故障恢复、安装/干净机、跨设备/课堂及签名也未验。graceful_stop_verified保持false，G0/G1未通过，不把本地测试当作总验收。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`；保留大量原有及新增未提交/未跟踪源码。未提交、推送、公开发布或重打已发布Mac App；历史发布仍按 `v0.1.2-preview.20261015`，未查询远端。本轮只新增本地开发源码材料，旧发行/测试包保持独立。

资源：本轮自有127.0.0.1:1420预览服务已停止，复查无监听；浏览器为后台替身，不连接用户实例。测试仅用自有临时SQLite/文件及持有Popen的空白磁盘暂停CPU QEMU；没有操作用户VM、修改宿主网络、删除原盘/旧证据或清理资产。最终名称快照未发现本机qemu-system进程，不推断远端状态；不用历史PID操作。最终检查/源码摘要与执行会话结果见 `output/managed-guest-20261025/final-evidence.json`。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第84节、本轮说明和路线图末尾，核验Git/实例并保留已有改动。目标仍为全部43项连续实施、最后集中验收；先继续尚未实现模块，不重做Windows Smoke，不把开发缺口统称待用户测试。镜像/SSH/签名证书暂缺已知。不要自动停止现有VM、删资产、提交、推送或发布。

## 85. 后台维护、更新协调、远程受限入口与证据封存（2026-10-25）

用户要求继续第84节、保留改动并连续推进剩余开发，最后集中验收。已读取AGENTS.md/第84节/相关设计与执行台账，核对正式目录、分支和HEAD，保留既有修改；没有重做Windows Smoke或向用户重复索要镜像、SSH环境、签名证书。实现与边界见[开发说明](ctflab-maintenance-remote-evidence-2026-10-25.md)，本轮检查及失败见[验证记录](verification-maintenance-remote-evidence-2026-10-25.md)。

### 本轮新增开发

- 通用QEMU监督、独立退出观测与桌面后台使用独立日志接收进程；每日志保留前8MiB，超额继续排空并记录丢弃字节，旧运行记录保留。自有子进程的父进程退出73后，生产与接收仍完成；不等于真实Windows监督故障验收。接收器自身故障及所有历史日志总容量仍有工作。
- TLS材料绑定/有效期检查、7天到期提醒、桌面提示和只读certificate-status；到期前确认正常停止，再次启动生成新CA/证书，旧材料保留。没有在线热换密钥或自动停机，不掩盖过期后可能无法通过QMP停止的限制。
- 新 `ctflab_release_update.py` 实现安装库兼容升级前备份、登记通用实例、全代次节点停机核验、契约/工作/代次锁、绑定预览、元数据备份和事务切换/同门槛回退。提交版本事务前持续持有实例锁；备份不含磁盘/私钥。中断现场阻止新切换，显式abandon只保留旧指针并结清，不删除文件或重放。只支持现有data_schema=1，最终安装器/在线更新/启动器集成仍缺。
- `ctflab_remote.py` 增加普通Linux用户SSH固定命令服务和显式客户端；主机密钥摘要、服务器UUID/协议、请求关联、容量/时间限制。principal固定在服务器配置，不接受请求自报身份或宿主路径；学生owner、教师/管理员scope、授权到期及学生禁止来宾管理。复用契约和异步后台，断线不重放；未连接真实SSH，不是远程资产/显示/租约/配额/数据通道已完成。
- `ctflab_evidence_export.py` 对已封口项目PCAP核验结构、配额、绑定和复制稳定性，封存到新目录并保留丢帧/未知时钟。可按明确运行尝试提取白名单生命周期时间线，时间是文件mtime，不导出私钥、argv或磁盘路径。完整采集/网络/课程标志仍false；通用socket捕获和O02仍缺。
- 依赖加入源码/桌面暂存白名单，README与43项台账更新；原Mac更新源码和10项测试完整保留。没有生成新的正式发行或覆盖旧候选包。

### 检查、失败与实际边界

最终完整 `python3 -B -m unittest discover -s tools/tests -v`：1162项，1141通过/21条件跳过，224.979秒；覆盖本轮最终34项新增用例及保留的10项Mac更新测试。隔离源码272项，264通过/8跳过，9.629秒；109文件、78个Python源码语法和8个 `-I --help` 入口通过。额外无来宾QEMU专项18项、React模型12项、前端生产构建通过。测试仅为本地代码/夹具，不是Windows、SSH、来宾网络或课堂验收。全部日志与源码摘要见 `output/maintenance-remote-20261025`。

实现时新更新模块曾误用既有Mac模块名，复核发现后将原先干净的两个Mac文件完整恢复，新模块/测试改为release_update独立命名；原Mac测试10项及CLI体验专项通过。最早全量1146项有该冲突错误和新验证文档缺项目要求的精确快照声明两个失败，已修复并保留日志。首轮隔离入口也发现材料生成器缺固定模块导入路径，修复后独立入口通过。中间全量与最终全量区分记录，不用早先加载的测试冒充后续新增传输测试。

全部43项仍未完成，不能概括成只等用户测试。实际开发缺口仍包括完整G0负向矩阵、在线证书/失效恢复、最终安装/启动器/在线更新、终端窄路由/OCI/容器跨网/部分来宾对账、远程资产/显示/租约/配额/数据通道、外部Kali→Windows→AD、真实课程与隔离分析器。原生Windows/Linux/SSH、新来宾应通禁通、干净机/跨设备/签名及课堂尚未新增验收；G0/G1与graceful_stop_verified不升级。用户集中实机总验收尚未启动。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`。保留全部既有及新增未提交/未跟踪改动；没有提交、推送、公开发布、制作最终安装包或重打已发布Mac App。历史发行仍沿用第84节记录的 `v0.1.2-preview.20261015`，本轮未查询远端。新证据只在 `output/maintenance-remote-20261025`，没有新交付ZIP。

资源收口：本阶段所有执行会话已完成，最终名称快照未发现qemu-system或独立日志接收进程。只运行自有临时SQLite、派生空白磁盘/暂停CPU QEMU、管道与POSIX SSH脚本替身；没有启动/停止/重置用户VM、连接真实SSH、修改宿主网络、删除资产/旧证据或启动预览监听。不推断远端Windows现场；历史记录/PID不是后续操作依据。

接续语：继续CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读取AGENTS.md、状态第85节、维护/远程/证据说明和执行台账末尾，现场核验Git/实例并保留改动。继续全部43项剩余开发，最后集中实机验收，不重做Windows Smoke，不把未实现项统称待用户测试。镜像/SSH环境/签名证书暂缺已知；不要自动停止现有VM、删除资产、提交、推送、覆盖旧包或发布。原Mac `ctflab_update.py` 已完整恢复，新增协调在 `ctflab_release_update.py`。

## 86. 继续实现受限远程资产同步（2026-10-25）

用户再次要求继续，承接第85节，不停在远程协议外壳。新实现 `ctflab_remote_assets.py`、SSHSession及Runner可选uploads策略；说明见[远程资产开发增量](ctflab-remote-assets-2026-10-25.md)，失败/测试边界见[验证记录](verification-remote-assets-2026-10-25.md)。保留全部原有及第85节改动，没有重做Windows Smoke或连接用户SSH环境。

### 本轮落地

- 服务端只接受已有签名内容缓存中允许源、精确摘要/大小、有效期、许可和audience一致的条目。请求不能提供信任根、任意宿主路径或命令；principal来自服务器固定SSH命令。学生不能上传教师材料或接管他人上传ID。
- 32KiB分块、幂等offset/内容校验、文件fsync后提交水位、匹配未提交前缀续传；未完成/损坏字节不能被实例使用。每主体全部历史上传计入数量/逻辑字节保留额度，另有全缓存待写量和每块剩余空间检查；不自动删现场或释放额度。
- 完整文件重验稳定身份/大小/摘要后，先持久登记保护引用再公布对象。重命名后账本中断可只读识别promotion_pending、显式finish核验；GC不误收无主新对象。已成功记录若对象消失，不再报告verified。
- 一条固定SSH进程上的有界JSONL多请求，避免每块重新连接；回复按服务器/协议/请求ID绑定，异常只结束自有传输、不重放生命周期。服务端每条消息重读权限；授权过期禁止新上传副作用。单连接上限100万请求，超过后保留水位，可显式重连继续。
- 新上传CLI保留源文件，只同步选定字节、不自动创建实例。ContentCache初始化显式关闭SQLite句柄，避免Windows句柄延迟释放。新依赖/测试/说明加入白名单，旧Mac更新模块仍完整保留。

### 集中代码检查与实际限制

最终完整 `python3 -B -m unittest discover -s tools/tests -v`：1180项，1159通过/21条件跳过，222.169秒。隔离源码290项，282通过/8条件跳过，10.591秒；112文件、80个Python源码语法和9个独立CLI入口通过。远程/上传专项30项全部通过。第85节前端模型12项、生产构建和无来宾QEMU18项沿用本次已运行结果，不冒称本阶段重复执行。全部新代码均在最终全量加载前完成；日志与源码摘要在 `output/remote-assets-20261025`。

专项首轮28项通过，复核又补充已验证对象消失和完整多块客户端→Runner→缓存实际管道，两项统一纳入最终30项；没有真实SSH连接。重命名中断保留保护引用、损坏/未完成不晋升、跨主体/教师材料/recipe-only/过期拒绝、断点重复/分歧拒绝及配额均有临时文件/SQLite测试。POSIX SSH脚本替身不等于Windows OpenSSH或真实Linux/KVM验收。

R01仍缺桌面远程目标/课程资产映射和真实SSH/KVM部署。R02的VM租约/续租/到期正常停止、算力/内存/磁盘配额与显示隧道，R03完整多人审计、R04数据通道仍未完成。其余43项实际开发继续沿用第85节/台账：完整G0负向矩阵、最终安装/启动器/在线更新、OCI/容器跨网/终端窄路由/部分来宾对账、外部Kali→Windows→AD、真实课程、隔离分析器等。缺镜像/SSH/签名证书已知，不重复索要，不把开发缺口统称待实机测试。G0/G1与graceful_stop_verified不升级，用户集中实机总验收尚未启动。

正式目录、分支、HEAD与第85节一致；保留全部既有和本轮未提交/未跟踪改动。没有提交、推送、公开发布、覆盖旧候选ZIP或制作最终安装器/重打已发布Mac App；历史发行沿用第84节记录，本轮未查远端。新增证据仅在 `output/remote-assets-20261025`，没有新交付ZIP。

资源收口：本阶段所有执行会话已完成，最终进程名称快照未发现qemu-system或独立日志接收进程。本阶段只用自有临时签名缓存/SQLite/文件和SSH脚本替身；没有发起真实SSH、启动或停止用户VM、修改宿主网络、新增监听、删除资产/旧证据。旧Mac更新源码和测试与本轮开始时一致；不按历史PID操作任何远端实例。

接续语：继续CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读AGENTS.md、状态第86节、远程资产说明和43项台账末尾，核验Git/实例并保留所有改动。继续剩余开发（优先OCI/容器跨网、来宾对账及远程显示/租约等真实缺口），最后集中实机验收；不重做Windows Smoke，不把未实现项统称待用户测试。镜像/SSH/签名证书暂缺已知；不要自动停止已有VM、删除资产、提交、推送、覆盖旧包或发布。

## 87. 离线OCI、终端窄路由与保守网络对账（2026-10-25）

按用户要求先读AGENTS.md/第86节，核验正式目录、Git和本机实例名称；保留全部已有修改，未重做Windows Smoke或要求用户补已知暂无的镜像/SSH/签名证书。继续实际开发，说明见[本轮开发记录](ctflab-oci-routing-2026-10-25.md)，失败和集中检查见[验证记录](verification-oci-routing-2026-10-25.md)。

### 本轮实现

- `ctflab_oci.py`：明确选择OCI tar的整包/manifest/config/blob/未压缩DiffID校验、Linux架构绑定、有界gzip展开与流式USTAR检查。只写新目录生成无标签Docker载荷，不在宿主解包或执行。当前仅单manifest、SHA-256、普通USTAR及raw/gzip层；PAX/GNU/zstd等拒绝，不冒充通用OCI全支持。
- images可选声明接入完整profile和受保护来宾策略；未启用时原编译字节/摘要保持兼容。专用来宾containers-prepare验证固定暂存材料后，持久意图下转换/装载并复核配置ImageID/架构/RootFS，按ID且pull=never创建，不启动。后续容器动作再验映像；素材/profile变更不能重连旧运行绑定。没有自动入客或真实Docker执行。
- `ctflab_guest_routes.py`：单网卡终端的endpoint配置，只引用已声明节点/网关/接口，生成/32路由和明确输入/输出流及有状态返回。终端先默认拒绝、转发关闭，再配置接口/路由；不添加默认出口、不做NAT、不清空/替换已有路由。缺失、额外或改变的路由、下一跳/来源/多路径拒绝；现场网络指纹包含路由。双端/路由器都需相应声明，不自动配置resolv.conf或系统时间。
- 分步骤状态查询和保守网络对账：独立逐操作证明不破坏旧network-proof格式；仅唯一未决network-apply已全部完成、步骤/操作证明/配置/当前网络都一致时，来宾内显式CLI补记末尾结果或证明效果结果。没有ip/nft/systemctl写命令重放；半配置、旧/错误证明和漂移仍拒绝，不修复OCI/宿主未知记录。
- 固定工具超时转为未知控制结果，代理保持只读查询能力，daemon可能仍工作，不重放load、不重启daemon或停止VM。新模块加入源码/桌面暂存/恢复候选白名单，专用来宾安装材料现在11模块/16文件并创建空oci目录；本机/已有用户来宾未安装。

### 验证与失败

最终完整 `python3 -B -m unittest discover -s tools/tests -v`：1211项，1190通过/21条件跳过，246.858秒。隔离源码321项，313通过/8条件跳过，10.980秒；117文件摘要、84个Python源码语法、10个独立CLI入口及临时生成的16文件专用来宾材料/独立代理入口通过。最终来宾专项48项、OCI专项13项通过；显式无来宾QEMU专项20项通过（1.135秒）。未改前端/Rust，本轮不重复构建；不将这些代码/替身结果作为真实Linux/Docker/网络或Windows验收。源码摘要与日志在 `output/oci-routing-20261025`。

首版对账专项45项有2项错误：给旧证明加入操作UUID破坏同内容重配；测试插入位置误移旧断言。改为独立逐操作证明、保留旧证明内容并归位旧断言后45项通过；原失败日志保留。首轮完整1207项通过（21跳过，235.932秒），但尚未加载最后追加的装载超时消息流用例；随后完整1208项通过（21跳过，243.619秒），又复核补上3项重连握手迟到回复边界；最终1211项和隔离321项加载全部最终代码，不以早先结果替代。重连configure最多排空8条同绑定迟到回复，修改操作仍严格拒绝错配ID且不重发，真实virtio重连仍待验。

### 真实未完成项及现场

全部43项仍未完成。OCI更广格式/镜像入客、原生Docker、容器跨网、半配置网络/半装载/卷及宿主记录修复、多跳/多网卡终端、客户端DNS/时间与真实C03服务仍有开发/验收。远程显示/资源租约/调度配额/多人审计/数据通道、最终安装/启动器/在线更新、外部Kali→Windows→AD、真实课程和隔离分析器、完整G0负向矩阵等沿用台账；不能概括成只等实机。缺镜像/SSH/签名证书已知，不重复索要。G0/G1与graceful_stop_verified仍未通过/false，用户实机总验收尚未启动。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`；保留所有既有及新增未提交/未跟踪源码。没有提交、推送、公开发布、覆盖旧Windows/源码候选、制作最终安装器或重打已发布Mac App；发行版本沿用前节历史记录，本轮未查远端。新证据根 `output/oci-routing-20261025`，没有新交付ZIP。

资源收口：所有本轮执行会话结束，最终只读进程/固定日志脚本快照未发现qemu-system或独立日志接收器。仅使用自有临时OCI字节、SQLite、网络/Docker替身、派生空白磁盘且暂停CPU的QEMU；没有在宿主运行Docker、安装来宾代码、连接真实SSH、操作用户VM或修改宿主网络，无新增监听或删除资产/旧证据。不推断远端Windows状态，不用历史PID操作。原Mac更新源码/测试与本轮开始时一致。

接续语：继续CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读AGENTS.md、状态第87节、本轮OCI/路由/对账说明和43项台账末尾，核验Git/实例并保留所有改动。继续实际剩余开发，最后集中实机验收；不重做Windows Smoke，不把未实现项统称待用户测试。镜像/SSH/签名证书暂缺已知；不要自动停止已有VM、删除资产、提交、推送、覆盖旧包或发布。保留原Mac更新模块，新增版本协调仍在ctflab_release_update.py。


## 88. 受管远程资源租约、异步准入与显式到期处理（2026-10-25）

先读AGENTS.md和第87节，核对正式目录、分支/HEAD与相关实例；保留全部既有改动。继续R02/R03的实际开发，没有重做Windows实机Smoke或要求用户重供已知暂无的镜像/SSH/签名证书。[实现说明](ctflab-remote-leases-2026-10-25.md)、[本轮验证](verification-remote-leases-2026-10-25.md)记录源码能力与限制，仍按最后集中实机验收推进。

### 本轮实现

- 新增 `ctflab_lease_store.py`：SQLite持久全池/owner CPU、内存与磁盘预留，独立跨进程排他门；owner申请、幂等续租及历史ID不复活。续租期限/幂等记录同事务，磁盘引用释放后仍保留计费、不删除资产。CPU/内存按完整场景预算，不凭少数节点停止释放。磁盘为逻辑预算，不是实际占用预测或硬配额。
- 可选leases策略接入Runner，旧无leases策略兼容。首次纳管在工作/契约/代次门内证明无活动/未知记录、全部代次与当前生产观察均停止；不能收编运行中的旧实例。绑定服务器/实例UUID、根/账本文件身份、配置/profile与预算/到期策略。策略目录父组件规范化后检查重叠，不能绕过实例/缓存隔离。
- `ctflab_remote_leases.py`：固定SSH协议的申请/续租/状态/释放，以及按私有操作许可派发异步worker。提交和执行时重读权限、请求摘要、scope、owner额度、实例/profile；节点间继续检查，排队后到期/撤销拒绝，中途到期保留已启动节点、不继续余下启动。教师按scope使用owner额度但不能替owner续租。status/cancel不等待长执行持有的资源门。
- 同boot单调时间、boot_id和UTC相对漂移门；时钟不确定保留额度、不关机。到期notify或明确策略+申请双重确认的request-stop，只有显式expiry入口；先持久意图再提交一次原正常stop，结果未知、超时、派发失败不重发、不强杀、不释放未证实额度。再次显式处理只查原契约/当前停机证据，全部停止才释放CPU/内存；graceful_stop_verified仍false。
- 新模块/测试/说明加入入库、桌面暂存和集成源码显式白名单，最新说明可作为候选guide。仅临时白名单复制验证，未生成新交付ZIP或安装器。

### 集中检查与失败记录

最终完整 `python3 -B -m unittest discover -s tools/tests -v`：1234项，1213通过/21条件跳过，233.240秒。远程合并53项全部通过（3.068秒，其中租约23项）；隔离源码344项，336通过/8条件跳过（11.905秒），121文件逐个摘要、87个Python语法、11个独立CLI入口通过，最终与工作区源码一致。文档7项复查通过。没有前端/Rust变更，不重复构建；没有重做Windows实机Smoke或本轮无来宾QEMU专项。所有VM动作/时钟/后端为替身，SQLite/文件为自有临时材料；代码/替身结果不等于真实Linux/SSH/KVM、Windows或用户实机总验收。完整证据见 `output/remote-leases-20261025/final-evidence.json`。

首轮测试入口辅助方法覆盖unittest.run，未运行用例；修正方法名后16项通过，扩展22项通过。首轮完整1233项有1项文档链接失败（验证文件尚未落盘）；随后文档专项发现缺少历史快照标识，补齐后复查。首轮完整/隔离检查未含最后发现的父组件目录重叠边界；补规范化与第23项后，最终重新完整加载。独立白名单检查后又补最新guide选项，最终隔离重新加载该收口；早期日志保留并以before-path-normalization/before-guide-closure标识。不是产品环境故障或实机验收。

### 剩余、现场与接续

全部43项仍未完成：资源租约核心已有增量，但周期调度器、实际Linux/SSH/KVM worker与到期故障、硬资源控制、跨重启时限恢复、多人审计、桌面租约/远程目标、认证显示和窄数据通道仍缺。单池门跨越完整动作，取消可达，但长动作会阻塞其他实例申请/续租；不是成熟多租户调度器。撤销scope后的未知操作保留需管理恢复，不重派。D02容器跨网、OCI更广格式/入客及半装载/网络/卷修复、多跳终端/DNS/时间、最终安装器/启动器/在线更新、外部Kali→Windows→AD、真实课程和隔离分析器、完整G0负向矩阵继续沿台账；不能把开发缺口写成只等用户测试。G0/G1未通过，实机总验收尚未启动。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`；所有既有及新增未提交/未跟踪修改保留。没有提交、推送、公开发布、覆盖旧包、重打已发布Mac App或制作最终安装器；实际发行沿用前节历史，本轮不查远端。证据根 `output/remote-leases-20261025`，无新交付包。原Mac更新源码/测试保留，新协调模块仍为ctflab_release_update.py。

资源收口：所有本轮执行会话结束；最终只读本机进程快照未发现qemu-system、固定脚本日志接收器或租约worker。本轮只使用自有临时SQLite/文件及VM/时钟替身，没有启动来宾或对现有VM执行stop/expiry，未安装调度服务、连接真实SSH、增加监听或修改宿主网络，没有删除资产/旧证据。不能由本机快照推断远端Windows状态，不用历史PID操作。

接续语：继续CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读AGENTS.md、状态第88节、受管远程租约说明及43项台账末尾，核验Git/实例并保留全部改动。连续推进实际剩余开发，最后集中实机验收；不重做Windows Smoke，不把未实现项统称待用户测试。镜像/SSH/签名证书暂缺已知；不要自动停止现有VM、运行租约到期停机调度、删除资产、提交、推送、覆盖旧包或发布。保留原Mac更新模块。


## 89. 远程请求审计、未决记录与检查点核对（2026-10-25）

承接用户要求，先读AGENTS.md、第88节，核验正式目录、Git和本机实例；保留全部已有改动，不重做Windows实机Smoke，不运行租约到期调度。继续R03实际开发；[开发说明](ctflab-remote-audit-2026-10-25.md)、[验证记录](verification-remote-audit-2026-10-25.md)区分本轮代码/替身与真实环境。

### 实现与边界

- 新增 `ctflab_remote_audit.py` 及可选audit策略。私有SQLite绑定服务器UUID/容量；路径规范化后不能与实例/缓存/租约根重叠，旧无audit策略继续兼容。Runner每次尝试生成服务端UUID，先提交意图，再沿原授权/owner/scope/租约调用链执行，返回或异常后追加结果；拒绝也记录，不把重复request_id当缓存回复。
- 仅保存主体、动作/操作枚举、有效UUID、服务端UTC、结果类别与公开错误；响应只取operation_id，不落原请求/响应/异常文本、载荷摘要、上传字节、凭据或路径。returned只代表函数返回，不代表权限通过、异步worker/来宾成功；guest_effect_verified=false。
- 意图失败、坏链/被占用/满库时不进入后端；结果写失败保留pending并返回未知，不伪造未执行或自动重放。容量按尝试计数，为已有意图预留结果槽位。满库也拒绝新的远程stop/cancel，运维需监控并显式新建独立库换策略，旧库不删除；本机原正常停止入口由用户显式使用，本轮没有换库或VM操作。
- 连续序号/SHA-256前后链、metadata head与attempt配对/索引事务核对，拒绝改内容、删尾及坏索引。读取最多100条，未决独立截断并标识；可传入已保存检查点验证历史前缀，追加后仍可核对。无外部可信锚或签名，同UID整库重写不能仅靠本地链发现；externally_anchored=false。最多10000尝试/20000事件，每次全链核验随容量变慢，不是高吞吐集中审计。
- 本机CLI只初始化新库/分页查询，不新增远程学生审计查询或任意命令。坏帧、坏策略/未知主体构造前失败、worker/来宾终态、外部封存、桌面查询/换库工作流和真实并发/断线/磁盘满仍有开发/验收缺口。新源码/测试/说明进入入库、桌面暂存、集成源码guide白名单。

### 本轮验证

最终完整 `python3 -B -m unittest discover -s tools/tests -v`：1249项，1228通过/21条件跳过，230.239秒。远程合并68项全部通过（4.503秒，含15项审计）；隔离源码359项，351通过/8条件跳过（11.397秒），124文件逐个摘要、89个Python语法、12个独立CLI入口通过，最终摘要与源码一致。文档7项通过，原Mac更新器及测试无diff。完整证据见 `output/remote-audit-20261025/final-evidence.json`。前端/Rust未改，不重复构建；Windows smoke仅保留既有不启动QEMU的单元边界用例，没有重做实机Smoke。

首轮审计14项通过；补历史检查点用例后15项由最终远程合并覆盖。当前无未解决测试失败，不以第88节的历史结果冒充本轮。所有VM/dispatch为替身、SQLite/文件与独立CLI为自有临时材料，没有SSH连接、宿主网络或实际来宾操作。不把代码/替身检查写成R03整体、G0/G1或实机总验收通过。

### 剩余与现场

43项整体仍未完成。下一步仍需实际开发：worker终态/坏帧审计、运维换库与桌面查询；远程显示/窄数据通道/周期调度、硬额度和原生worker；D02容器跨网、OCI半装载/网络/卷恢复、多跳终端/DNS/时间；最终安装器/启动器/在线更新、外部Kali→Windows→AD、真实课程/隔离分析器及完整G0负向矩阵。已知暂无镜像/SSH/签名证书不重复索要；缺实现不写成只等用户测试，实机总验收尚未开始，graceful_stop_verified仍false。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`；全部已有及本轮未提交/未跟踪改动保留。未提交、推送、公开发布、覆盖旧包、重打已发布Mac App或制作新安装器，实际发行沿用历史记录，本轮未查远端。证据根 `output/remote-audit-20261025`，无新交付ZIP；原Mac更新器及测试保留，新版本协调仍独立为ctflab_release_update.py。

资源收口：所有本轮执行会话结束；最终只读本机进程快照未发现qemu-system、固定脚本日志接收器或租约worker。本轮只使用自有临时SQLite/文件、独立只读/初始化CLI与VM/dispatch替身，没有启动来宾、对用户VM调用stop/expiry、安装审计/到期调度服务、连接真实SSH、增加监听、修改宿主网络或删除资产/旧证据。不能从本机快照推断远端Windows状态，不用历史PID操作。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第89节、远程请求审计说明和43项台账末尾，核验Git/实例并保留全部改动，推进剩余实际开发、最后集中实机验收。不重做Windows Smoke，不自动停止现有VM、运行到期停机调度、删除资产、提交、推送、覆盖旧包或发布。镜像/SSH/签名证书暂缺已知，保留原Mac更新器。


## 90. 异步worker执行前与契约结果审计（2026-10-25）

先读AGENTS.md/第89节，核验正式目录、Git与本机实例；保留所有既有改动。不重做Windows实机Smoke，不停止现有VM或运行到期停机调度。继续补齐R03实际执行阶段缺口；[实现说明](ctflab-worker-audit-2026-10-25.md)与[验证记录](verification-worker-audit-2026-10-25.md)保留当前边界。

### 本轮实现

- `ctflab_remote_leases.execute_job` 验证当前私有许可、策略/主体/scope、实例根和契约请求摘要后，进入审计包装；先提交服务端worker意图，再取得资源门、权限/租约校验、当前worker身份记录与原LocalService执行。审计无法提交、满库/缺库/坏链时不登记worker身份或进入资源后端；原契约可保留pending，不自动重派。未配置audit时旧路径兼容。
- worker意图增加可选execution字段，origin固定worker、operation_id来自服务端已验证许可；原Runner请求意图结构不变，客户端不能自报worker来源。完成后绑定同operation/instance，仅存契约state/result/cancelled/error_code白名单；任意文本、原响应、路径、证据内容不入审计。异常只保留公开码和绑定操作。
- 旧请求事件、字节/哈希链及历史检查点保持不变，核验器兼容新扩展。结果事件与attempt完成同事务，故障一起回滚；实际动作已完成但结果写失败则保留pending、返回未知，原契约终态仍可查询，不逆转VM行为。显式再次执行既有operation可能只读取缓存结果，会新增一次观察，不重放资源动作；没有自动重试。
- returned仅表示函数返回，contract.failed/unknown仍是失败/未知；stopped也不证明优雅关机或课程服务，guest_effect_verified和graceful_stop_verified仍false。请求与worker分别占审计尝试，accepted可能在worker因满库而未执行；容量/本地链信任/换库限制沿用第89节。
- 新worker专项/说明和guide纳入入库/集成源码白名单。没有新增运行时依赖，桌面暂存沿用已有审计模块；未制作新包或安装服务。

### 验证与失败

最终完整 `python3 -B -m unittest discover -s tools/tests -v`：1264项，1243通过/21条件跳过，231.068秒。worker专项15项全部通过（0.561秒），远程既有合并68项全部通过（4.385秒）；隔离源码374项，366通过/8条件跳过（12.073秒），126文件摘要、90个Python语法、12个独立CLI入口通过，最终源码摘要一致。文档7项通过；对照第89节124文件仅3个预定文件变化，其余源码摘要保留，证据source-preservation.json。完整证据见 `output/worker-audit-20261025/final-evidence.json`，原Mac更新两个文件无diff。前端/Rust未改，不重复构建；Windows Smoke只保留既有不启动QEMU的单元边界用例，未重做实机Smoke。

首轮worker12项中1项测试结构错误：取消请求把operation_id放顶层，遗漏原契约CAS/幂等/parameters。按现有契约修正后12项通过，补正常stop超时、坏链拒绝、结果事务回滚后最终15项通过。原失败日志worker-first.log保留；没有未解决测试失败，不以第89节结果冒充本轮。全部VM/dispatch为替身，契约/SQLite/文件为自有临时材料；没有SSH、宿主网络或来宾操作，不是原生Linux/Windows或实机总验收。

### 剩余与现场

43项整体未完成。许可绑定前拒绝/坏帧/认证失败、旧无leases桌面worker、真实来宾事件未覆盖；pending只读核验、外部可信封存、审计查询桌面/换库运营与真实Linux/SSH并发/断线/磁盘故障仍需开发或验证。远程显示/窄数据通道/周期调度/硬额度、D02容器跨网、OCI半装载/网络/卷恢复、多跳终端/DNS/时间、最终安装器/启动器/在线更新、外部Kali→Windows→AD、真实课程/隔离分析器及G0负向矩阵沿用台账。缺镜像/SSH/签名证书已知，不重复索要，不把缺实现写成只等用户测试。G0/G1仍未通过，集中实机验收尚未开始。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`。全部既有及新增未提交/未跟踪改动保留；未提交、推送、发布、重打已发布Mac App、覆盖旧Windows/源码包或制作最终安装器，实际发行沿历史记录，本轮不查远端。证据根 `output/worker-audit-20261025`，无新交付ZIP；原Mac更新器及其测试保留，新版本协调仍独立为ctflab_release_update.py。

资源收口：所有本轮执行会话结束；最终只读本机进程快照未发现qemu-system、固定脚本日志接收器或租约worker。本轮只用自有临时SQLite/文件和VM/后端替身；没有启动来宾、对现有VM调用stop/expiry、运行实际到期停机调度、安装服务、连接真实SSH、增加监听、修改宿主网络或删除资产/旧证据。不能由本机快照推断远端Windows状态，不用历史PID操作。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第90节、worker执行审计说明及43项台账末尾，核验Git/实例并保留全部改动，推进剩余实际开发、最后集中实机验收。不重做Windows Smoke，不自动停止现有VM、运行到期停机调度、删除资产、提交、推送、覆盖旧包或发布；镜像/SSH/签名证书暂缺已知，保留原Mac更新器。


## 91. 审计未决项与原契约的只读核验（2026-10-25）

先读AGENTS.md和第90节，核验正式目录、Git与本机实例；用户途中“继续”作为同一目标接续。保留全部既有改动，不重做Windows实机Smoke、不停止现有VM或运行到期停机调度。继续补齐R03未决项核验入口；[实现说明](ctflab-audit-review-2026-10-25.md)、[验证记录](verification-audit-review-2026-10-25.md)保留当前能力与真实环境边界。

### 本轮实现

- 新增 `ctflab_audit_review.py` 本机只读CLI。只从已核验审计链/索引选择pending意图，分页返回意图序号、pending总量、审计head及可选历史检查点核对。worker按服务端operation_id查固定私有许可，检查当前主体/scope/学生owner、服务器/实例/操作、原策略路径/摘要、实例根/账本文件身份、配置/profile与契约actor/请求/响应绑定。
- 区分原契约pending/executing、已有绑定响应、无操作关联、scope不可用、策略变更、缺操作/文件、绑定冲突或不可核验。旧请求层意图无operation绑定不按时间或相似内容猜测；不输出原许可/请求/响应、任意错误文本、路径、PID、凭据或来宾数据。
- 策略初次读取前后与返回报告前校验摘要，实例绑定在契约读取前后复核；变更拒绝沿用旧权限/身份。审计、代次元数据和契约均为只读数据库连接，禁止SQL写入，缺库不创建、不恢复热日志。文件前后核对不等于全局原子现场；各数据库快照独立，snapshots_atomic=false。
- 不追加result/结清pending，不调用VM观察/执行后端，不取得资源门、重派任务、关机或释放租约。即使原契约已有终态，审计pending仍保留。audit_modified/contract_modified/vm_observed/automatic_replay/guest_effect_verified/graceful_stop_verified均false，contract-recorded不证明来宾服务或真实停机。
- 新模块/测试/说明与guide纳入入库、桌面暂存和集成源码白名单；原Mac更新器保留。未增加远程学生查询接口、服务、监听或运行时依赖。

### 验证

最终完整 `python3 -B -m unittest discover -s tools/tests -v`：1279项，1258通过/21条件跳过，232.608秒。只读核验15项全部通过（0.674秒），远程既有合并68项通过（4.450秒），原worker专项15项通过（0.578秒）；隔离源码389项，381通过/8条件跳过（12.956秒），129文件摘要、92个Python语法、13个独立CLI入口通过。最终源码摘要与白名单一致，文档7项通过；对照第90节126文件只有预定3个文件变化，其余摘要保留。原Mac更新器及测试无diff，证据见 `output/audit-review-20261025/final-evidence.json` 和source-preservation.json。前端/Rust未改，不重复构建，未重做Windows实机Smoke；完整回归只含既有不启动QEMU的Smoke单元边界用例。

首轮13项通过，补初次策略读取与查询途中实例绑定漂移后15项通过；当前无未解决失败。文件摘要前后比较覆盖整个自有临时目录，原pending和VM替身调用均未变化；直接SQL写入只读事务被拒绝，独立CLI不输出宿主路径。所有契约/SQLite/文件为自有临时材料，VM/worker后端为替身；未连接SSH、读取虚拟磁盘或操作真实来宾，不是原生Linux/Windows或实机总验收。

### 剩余与现场

43项整体未完成。请求层无绑定意图、许可绑定前/坏帧/认证失败、旧无leases桌面worker、真实来宾事件、外部可信封存、只读报告桌面、运维换库与显式pending处理、真实Linux/SSH并发/断线/热日志/磁盘故障仍需实际开发或验收。本地链/容量/独立快照限制沿用前节。远程显示/窄通道/周期调度/硬额度、D02容器跨网、OCI半装载/网络/卷恢复、多跳终端/DNS/时间、最终安装器/启动器/在线更新、外部Kali→Windows→AD、真实课程/隔离分析器及G0负向矩阵继续沿台账。镜像/SSH/签名证书暂缺已知，不重复索要；未实现不概括成只等用户测试，G0/G1未通过，集中实机验收尚未开始。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`。全部既有及新增未提交/未跟踪改动保留；未提交、推送、公开发布、重打已发布Mac App、覆盖旧Windows/源码包或制作最终安装器，实际发行沿历史记录，本轮不查远端。证据根 `output/audit-review-20261025`，无新交付ZIP；原Mac更新器及其测试保留，新版本协调仍独立为ctflab_release_update.py。

资源收口：所有本轮执行会话结束；最终只读本机进程快照未发现qemu-system、固定脚本日志接收器或租约worker。本轮仅用自有临时SQLite/文件及VM/worker替身；没有启动来宾、对用户VM执行stop/expiry、运行实际到期停机调度、安装服务、连接真实SSH、增加监听、修改宿主网络或删除资产/旧证据。不能从本机快照推断远端Windows状态，不用历史PID操作。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第91节、未决审计只读核验说明和43项台账末尾，核验Git/实例并保留全部改动，推进剩余实际开发、最后集中实机验收。不重做Windows Smoke，不自动停止现有VM、运行到期停机调度、删除资产、提交、推送、覆盖旧包或发布。镜像/SSH/签名证书暂缺已知，保留原Mac更新器。


## 92. 桌面远程目标、实例选择与原契约操作（2026-10-25）

用户途中继续要求读取第91节及未决审计说明/台账，先完成第91节真实结果收口并核验，再连续推进R01/R03桌面缺口，没有停在交接或重复索要已知缺少的镜像/SSH/签名证书。[实现说明](ctflab-desktop-remote-2026-10-25.md)、[验证记录](verification-desktop-remote-2026-10-25.md)区分工作区、浏览器/传输替身和原生验收。保留全部改动，不重做Windows实机Smoke，不操作用户VM或运行到期停机调度。

### 本轮实现

- 新增 `ctflab_desktop_remote.py`：显式本机私有连接JSON，沿用固定SSHSession、主机密钥/服务器UUID/消息关联和有界期限；目标指纹绑定配置及身份文件摘要，变更在传输前拒绝、传输中变更返回未知，不重发。只允许connect/overview/events/submit/lease-status，submit保留status/prepare/start/stop/reset/recover/cancel，拒绝guest/display/导入/任意命令。内外实例、请求ID和状态修订核对。
- Rust固定remote_bridge路由仅选择新脚本与配置参数，原本机bridge保留；界面不能选择命令/脚本。新增RemoteWorkspace与远程模型：显式连接后读取角色/分配UUID，选择实例打开，4秒只读刷新概览/事件/租约；已有租约UUID手动输入，原契约操作沿CAS/幂等，stop/reset需明确确认。无自动申请/续期/释放或到期策略变更。
- 新目标、实例、断开或组件卸载使旧响应失效，较旧修订/迟到空修订不能覆盖已接收操作；传输未知只提示读状态，不自动重发。新实例无契约修订的精确generation=0/unknown/null组合可以打开并准备。远程页隐藏本地导入/原请求重试控件，无显示、文件导入、任意转发或来宾管理。
- 断开/离开页停止该页刷新，远程实验不停止；不保存目标到localStorage、不自动重连。真实owner/scope/预算/租约/授权到期仍由服务端检查，UI不是新授权边界。安装材料不新增分发OpenSSH，仍需显式准备本机ssh/ssh.exe及固定连接配置。
- 新Python/前端源码和测试、说明与guide加入入库/桌面暂存/集成源码白名单；无新运行时依赖。原Mac更新器、独立版本协调及旧包保留，没有新发布App/Windows安装器/源码ZIP。

### 验证与迭代

最终完整 `python3 -B -m unittest discover -s tools/tests -v`：1294项，1273通过/21条件跳过，226.989秒。桌面远程Python15项通过（0.135秒）、原远程合并68项通过（4.085秒），Node21项全通过（新增9项远程模型），前端生产构建22模块通过。Rust cargo check --locked与cargo test --locked通过（0用例，仅编译），现有stable rustfmt核对通过。隔离源码404项，396通过/8条件跳过（13.224秒），135文件摘要、94个Python语法、14个独立CLI入口通过。文档7项通过，对照第91节129文件仅预定6文件变化，其余摘要一致；最终源码/白名单及空白差异通过，原Mac更新两个文件无diff。证据见 `output/desktop-remote-20261025/final-evidence.json`。

浏览器替身检查：明确连接/选择实例后一次启动，旧修订不重启按钮，断开后迟到节点不显示、stop请求0、本机bridge调用0；新实例准备按钮可用，只发一次prepare且CAS为null，接收后禁重复。invoke由替身替代，不经过真实Rust IPC/SSH/VM，不能作为原生/实机验收。自有回环HTTP夹具结束后按UID、精确命令及cwd核验并停止，浏览器回空白页；不操作用户服务或VM。

首轮前端测试文件写入目录有误，纠正源码路径后20项通过，补新实例边界后21项通过。状态修订门在代码复核发现会拒绝新实例，已改为精确零代次空修订组合并补Python/Node/浏览器用例。固定Rust 1.90缺rustfmt，原失败日志保留，改用已安装stable格式工具核对；没有安装组件/修改工具链锁。Rust test为0例，只当编译通过，不冒充业务用例；当前无未解决测试失败。

### 剩余与现场

43项整体未完成。真实SSH/普通Linux/KVM、Windows原生IPC/用户交互、配置向导/安全文件选择/目标保存/连接取消、资产/课程映射、租约管理UI、远程认证显示与窄通道仍需开发/验收。短SSH会话逐次刷新有性能/长期在线限制，不能宣称成熟多人平台。外部可信封存/换库/显式审计pending处理、周期调度/硬额度、D02容器跨网和部分来宾修复、最终安装器/启动器/在线更新、外部Kali→Windows→AD、真实课程/分析器及G0负向矩阵继续沿台账。已知暂无镜像/SSH/签名证书不重复索要，缺实现不写成只等用户测试；G0/G1、graceful_stop_verified仍未通过/false，集中实机验收尚未开始。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`；全部既有与新增未提交/未跟踪改动保留。未提交、推送、公开发布、重打已发布Mac App、覆盖旧Windows/源码包或制作最终安装器；本地dist仅开发构建，实际发行沿用历史，本轮不查远端。新证据根 `output/desktop-remote-20261025`，原Mac更新器及其测试保留，新版本协调仍独立为ctflab_release_update.py。

资源收口：所有本轮执行会话结束；最终只读本机快照未发现qemu-system、固定日志接收器或租约worker；自有HTTP夹具已按当前UID/精确命令/cwd核验后停止，18742端口无监听，浏览器回空白页。仅使用自有临时SQLite/文件、假SSH/Runner拒绝路径、浏览器invoke替身和本地开发构建，没有连接真实SSH、启动来宾、停止现有VM、执行实际到期调度、安装服务、增加对外监听、修改宿主实验网络或删除资产/旧证据。不能从本机快照推断远端Windows状态，不用历史PID操作。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第92节、桌面远程目标说明与43项台账末尾，核验Git/实例并保留全部改动，推进剩余实际开发、最后集中实机验收。不重做Windows Smoke，不自动停止现有VM、运行到期停机调度、删除资产、提交、推送、覆盖旧包或发布；镜像/SSH/签名证书暂缺已知，保留原Mac更新器。


## 93. 桌面远程租约申请、续期、释放与原标识重试（2026-10-25）

先读AGENTS.md、第92节与43项台账末尾，核验正式目录、Git/本机实例；中断后用户继续时重新核对源文件/进程再实施。保留全部改动与原Mac更新器，未重做Windows实机Smoke、不操作现有VM或运行实际到期调度。[实现说明](ctflab-desktop-leases-2026-10-25.md)、[验证记录](verification-desktop-leases-2026-10-25.md)保留工作区/替身与实机边界。

### 本轮实现

- 服务端lease-status增加当前owner_actions和max_ttl_seconds，沿原scope/owner/预算/完整停机证明和账本幂等，不放宽资源授权。固定Python桥接增加lease-acquire/renew/release严格字段，传输前核对UUID/TTL/到期枚举；每次握手确认租约能力，返回核对实例/lease_id，续期还校验renewal_id。
- 远程页补明确申请、续期、释放与现有租约选择；服务器管理能力/上限齐备后启用，旧服务器不猜测owner权限。request-stop需额外勾选并明确确认，策略只读不可改，不安装或运行调度。申请只有当前active返回才选择；续期需活动状态，释放沿服务端全部停止证明，磁盘引用保留、不发送stop。
- 未知/拒绝响应保留完整原动作/标识/TTL/策略，阻止生成新的租约变更请求，不自动重发；用户可先刷新，或明确点击同标识重试，复制原参数不换UUID、跨目标/实例拒绝。原续租幂等记录避免重复延长。可显式保存原请求JSON，不含连接配置路径/身份/主机密钥或凭据；本地跟踪仅组件内存，离开前需自行保存，不自动导入/恢复发送。
- 状态或权限读取失败清空管理能力，不沿用旧owner标记启用按钮；UI仍不是授权凭证，服务器期限/权限/绑定变化可拒绝。教师scope不能代owner管理租约，仍可沿原规则使用owner额度执行实例操作。新测试/说明与guide纳入入库/集成源码白名单，没有新运行时依赖或Rust入口变化。

### 验证

最终完整 `python3 -B -m unittest discover -s tools/tests -v`：1303项，1282通过/21条件跳过，241.253秒。新租约合成链路9项通过（0.265秒）、原桌面远程15项通过（0.153秒）、原远程合并68项通过（4.503秒）；Node26项全部通过（新增5项租约模型），前端22模块生产构建通过。隔离源码413项，405通过/8条件跳过（14.071秒），137文件摘要、95个Python语法、14个独立CLI入口通过；最终源码/白名单/空白差异通过，文档7项通过。对照第92节135文件仅预定7文件变化，其余摘要一致，原Mac更新两个文件无diff；证据见 `output/desktop-leases-20261025/final-evidence.json` 与source-preservation.json。Rust入口未改，本轮未重跑，不冒称新原生结果。

合成链路覆盖先读取owner/上限再申请、原ID续期/重试不重复延长、释放保留磁盘/源摘要；丢回复只发送一次直至手动同ID重试；教师拒绝、TTL/UUID/额外字段拒绝、request-stop额外确认后推进假时钟仅查状态不运行expiry，运行中释放拒绝且不stop/不释放额度，错绑续期回复不能触发二次延长，旧notify确认不能授权新停止策略。所有VM/SSH为替身、Runner/契约/SQLite为真实代码与自有临时材料，没有读取/操作用户磁盘或VM。

浏览器替身确认申请前变更0、未勾选停止策略按钮禁用、申请1次、丢续期回复后调用1次且新变更禁用，明确重试后同renewal_id两次请求只延长1次；释放1次、stop为0；导出Blob只含原请求字段，没有连接路径/凭据，也未写用户下载目录。invoke为替身，不是Rust IPC/真实SSH验收。自有回环HTTP夹具结束后核验UID/命令/cwd再停止，浏览器回空白页。前端追加测试路径首次有误，改绝对路径后最终26项覆盖新增5项，不把早期21项当最终；当前无未解决测试失败。

### 剩余与现场

43项整体未完成。租约跟踪仅内存、显式导出不自动恢复/导入，真实SSH/Windows原生IPC/用户交互/长期并发与时钟/断线/热日志/磁盘故障仍待实际开发或验收。配置向导/安全文件选择/目标保存/连接取消、远程资产/课程映射、认证显示/窄通道、周期调度/硬额度、审计外部可信封存/换库/显式pending处理、D02容器跨网和部分来宾修复、最终安装器/启动器/在线更新、外部Kali→Windows→AD、真实课程/分析器与G0负向矩阵沿台账继续。已知缺镜像/SSH/签名证书不重复索要，缺实现不写成只等用户测试；G0/G1、graceful_stop_verified仍未通过/false，集中实机验收尚未开始。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`。全部既有与新增未提交/未跟踪改动保留；原Mac更新器及测试、独立版本协调与旧包保留。未提交、推送、公开发布、重打已发布Mac App、覆盖旧包或制作最终安装器，dist仅本地开发构建，实际发行沿历史，本轮未查远端。证据根 `output/desktop-leases-20261025`，无新交付ZIP。

资源收口：所有本轮执行会话结束；最终只读本机快照未发现qemu-system、固定日志接收器或租约worker；自有HTTP夹具经当前UID/精确命令/cwd核验后停止，18743端口无监听，浏览器回空白页。本轮仅自有临时SQLite/文件、假SSH/VM和浏览器invoke替身以及本地前端构建，没有连接真实SSH、启动来宾、停止现有VM、运行实际到期停机调度、安装服务、增加对外监听、修改宿主实验网络、删除资产或旧证据。不能从本机快照推断远端Windows状态，不用历史PID操作；Windows实机Smoke不重做，完整回归只含既有不启动QEMU的Smoke单元边界。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第93节、桌面租约说明与43项台账末尾，核验Git/实例并保留全部改动，推进剩余开发、最后集中实机验收。不重做Windows Smoke，不自动停止现有VM、运行到期停机调度、删除资产、提交、推送、覆盖旧包或发布。已知缺镜像/SSH/签名证书，保留原Mac更新器。


## 94. 配置/持久恢复/资产传输与来宾部分准备恢复（2026-10-26）

从第93节连续推进，已读取AGENTS.md、第93节和43项台账末尾，现场核验目录/Git及本机QEMU快照。目录`/Users/pufei/Downloads/ctf-lab`，分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`不变；保留全部已有改动，原Mac更新器及其测试与HEAD无差异。没有重新打包、提交、推送或发布，已发布App和旧包没有因此更新。

本轮实际实施：

- 修正桌面桥接重复解包`SSHSession.request`结果的真实接口错误，新增真实会话类/固定本机管道替身回归，纠正旧FakeSession多包一层的漏检。没有真实SSH。
- 私有目标列表、配置向导、公用主机密钥私有副本、固定类型原生文件选择源码；旧手工配置为只读预览。保存目标后明确连接才可变更，私钥不复制。
- 已保存目标连接可明确取消；独立连接ID/终止记录处理取消先到，真实会话类在等待回复/阻塞输入时仅关闭自有SSH传输。迟到回复丢弃，不解除新连接的等待保护；不向实例发停止/释放/到期请求。旧手工预览尚无该传输取消入口，关闭页面不自动取消。
- 变更意图先落盘；中断/丢回复保留未知，重开/恢复跟踪不发送，明确点击才用原请求/原标识重试。未知结果摘要按白名单保存；目标/载荷漂移拒绝。
- 远程许可缓存的上传、进度、暂停、原ID续传与显式远端核对。历史verified不代表当前远端，字节不足的verified响应拒绝；尚无课程实例映射。大文件仍有逐RPC审计容量/扫描限制。
- 离线跨节点策略闭合检查：找出缺终端放行、回程路由、网关规则及方向/端口不匹配，列出同网段不受转发规则覆盖的限制；不是O02分析器，不证明运行隔离。
- 来宾管理员显式检查/接受摘要后续建准备：新资源绑定原操作/网络ID/容器ID/卷创建身份。只创建从未开始的步骤；未知但观察到本操作资源时仅补记录；缺资源、漂移、外来/运行中资源拒绝，不重建/删除/停止。新准备记录在启动/停止前后复核，移除标签不能降级绕过绑定。旧未知记录不能套用新恢复。
- OCI仅在原归档/config/架构/全部层与实际已载入镜像一致时允许补记录续建，不重发load；原未知effect保留unknown并明确标注。未载入、层漂移、更广半装载修复仍缺。

实现、操作入口、证据范围与后续恢复语见[连续开发与核验记录](ctflab-continuous-development-2026-10-26.md)。证据根`output/continuous-dev-20261026`。前端27项/构建、Rust检查/1项白名单用例、来宾62项、OCI17项、独立源码466项（458通过/8条件跳过）已通过；连接取消后最终完整回归1366项（1345通过/21条件跳过，230.723秒），独立源码476项（468通过/8跳过，16.810秒）；147文件/101个Python语法/4个CLI帮助入口通过。客户端22项、固定SSH传输19项通过。最终摘要在output/continuous-dev-20261026/final-evidence.json，前述466项为阶段历史。浏览器仅invoke替身，原生文件对话框/IPC、真实SSH、来宾、VM和课程未验。没有重做Windows实机Smoke。

自有HTTP夹具127.0.0.1:18744/18745在复核UID/完整命令/cwd后已关闭，浏览器回空白页；本机QEMU开始/结束快照未发现，不据此推断远程Windows状态。没有停止现有VM、运行实际到期停机调度、删除用户资产、覆盖旧包或发布。缺镜像/SSH/签名证书已知，不重复索要。

**43项整体仍未完成，集中实机总验收尚未开始。** D02三层回程/二层隔离、远程课程映射/旧手工预览传输取消/认证显示/窄数据通道、周期调度/硬额度、审计外部封存/换库/显式pending处理、更广来宾半装载和异常修复、最终安装器/版本启动器/在线更新、外部Kali→Windows→AD、真实课程/O02分析器/完整G0负向矩阵仍需实际开发或验收，不能概括为只等用户测试。G0/G1与`graceful_stop_verified`仍未通过/false。下一步按连续记录继续这些缺口，维持当前操作边界。


## 95. 签名版本固定入口启动器与更新互斥（2026-10-26）

在第94节全部改动上继续，已重读AGENTS.md/状态/43项台账，现场核验Git与本机进程。正式目录、分支和HEAD不变；没有本机QEMU或旧HTTP夹具，不能推断远端Windows状态。原Mac更新器、旧包和用户资产保留。

新增`ctflab_release_launcher.py`：新应用包schema=2签名覆盖固定平台入口和执行文件列表，原信封留在暂存目录，启动重新验证信任根/签名/数据库摘要/精确文件集合/平台/入口；Windows增加无UI、缓存限定的WinVerifyTrust源码，签名后再核对全文件摘要。旧包schema=1仍可暂存/手动管理，不猜入口自动执行；Mac新启动器不开放，原更新链不替换。

版本根新增私有应用门和启动意图/绑定/退出记录；应用存活时阻止激活、回退和协调更新，版本数据库仍可读。中断或派生/记录失败保留unknown，不重发/杀进程/停止VM/删除记录；新启动或版本切换保守拒绝，独立未决核验/结清仍未实现。已登记实例原有工作门/契约门/代次/全部节点停机检查保留。范围仅经本版本库启动器的应用，不冒称所有应用/后代/未登记VM已检查。

新schema=2还拒绝额外文件/空目录、目录大小写别名、尾点、保留清单名及执行位漂移。旧安装根需显式update-initialize补启动器状态，普通读取不自动迁移。新模块/测试/说明与运行时/源码白名单、Windows源码专项入口同步，没有制作包或发布。

实现、入口、失败范围与继续语见[版本启动器说明](ctflab-version-launcher-2026-10-26.md)。专项38项（含22项新启动器/SDK结构/provider替身）和运行时复制5项已通过。真实Popen只执行自有临时脚本，保留退出码7；host标签为测试注入，不是Linux原生桌面证据。没有真实Windows WinVerifyTrust/证书/安装器/桌面/VM验证，Windows Smoke不重做。最终完整回归1388项（1367通过/21条件跳过，238.146秒）；独立源码498项（490通过/8跳过，16.758秒），150文件/103个Python语法/3个CLI帮助入口通过。对照第94节147文件仅预定5文件变化，其余142原摘要保留，新增模块/测试/说明3文件。证据根output/version-launcher-20261026，最终摘要final-evidence.json。前端/Rust未改不重跑，旧结果不充当本轮新原生证据。

43项整体与最终实机验收未完成。稳定安装引导/UI、启动器中断后的独立核验/显式结清、真实Windows签名/缓存与Linux依赖闭包仍缺；D02、远程认证显示/窄通道/课程映射/调度/硬额度、审计运营、外部VM/真实课程/O02与G0负向矩阵继续开发。已知缺镜像/SSH/签名证书不重复索要。未自动停止现有VM、运行到期调度、删除用户资产、提交、推送、覆盖旧包或发布。

## 96. 启动器中断独立核验、显式结清与手工预览取消（2026-10-26）

按用户要求读取AGENTS.md、第95节、版本启动器说明和43项台账末尾，再核验正式目录/Git/本机实例。正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0` 不变；保留全部既有修改/未跟踪文件，未切换工作区或拉取。初始本机未发现QEMU/旧HTTP夹具，不能推断远端Windows状态；缺镜像/SSH/签名证书已知，不重复索要。

### 本轮实际实现

- 版本启动器新增review/settle固定CLI：新派生尽力追加创建时间/映像/原派生摘要身份，前后以所持子进程对象确认仍运行，避免已退出后误绑复用PID。快速退出/观察不支持时不猜身份，仍由原父进程正常wait封存退出；身份记录写失败保留未知。
- 独立review核对原意图/派生/身份摘要及平台/固定路径/创建时间，只读观察并返回核验摘要。明确settle携带该摘要，再持应用/数据库门，保留同一Windows查询等待句柄/Linux pidfd，最多等待1000毫秒；运行中、缺PID、身份/记录漂移、旧缺身份、权限失败均拒绝。只追加settled.json，不覆盖原始文件；Windows保留退出码，Linux退出码未知为null。版本门重新核验独立证据；坏原父进程退出证明不能由结清掩盖，不自动杀进程/重发启动/停VM。
- 手工配置只读预览也经client_bridge使用独立连接标识，明确取消；注册表仅绑定规范化配置路径摘要，不存路径/凭据/回复正文、不自动保存目标。取消先到留终止记录，等待中仅结束自有SSH传输，迟到回复不重连；配置移走后仍可取消原连接，已返回连接不被迟到取消关闭。预览依然不能发送实验变更；关闭页面仍只丢弃旧回复，未增加自动传输取消。

详见[启动器说明末尾](ctflab-version-launcher-2026-10-26.md)及[连续开发说明末尾](ctflab-continuous-development-2026-10-26.md)。本轮无新模块/运行时依赖/白名单文件，无Rust入口改动。

### 验证范围与限制

版本/更新专项51项通过（新增13项），客户端27项通过（新增5项）；Node27项和24模块前端生产构建通过。独立复制既有150文件后516项（508通过/8条件跳过，16.750秒），103个Python语法、启动器/客户端/集成源码包3个独立CLI帮助入口通过。对照第95节，只有预定8文件变化，其余142文件摘要一致；复制后源码摘要一致，白名单与git diff --check通过，原Mac更新器/验收入口/测试均与HEAD一致。前端dist仅本地开发构建，Rust未改未重跑，旧编译结果不冒充本轮新原生证据。

启动器独立观察/句柄/pidfd使用注入替身，没有真实Windows/Linux应用恢复。原有真实Popen仅执行自有临时脚本；客户端使用生产SSHSession与自有固定管道/假服务器，浏览器invoke替身确认一次手工预览连接、一次同标识取消、迟到回复无重连、实验变更为0。没有真实SSH、原生文件对话框/IPC、来宾/VM/课程验收。首轮调整缺文件拒绝时3项旧专项暴露FileNotFoundError，修正明确拒绝后51项全部通过，失败日志为开发历史，不作为成功证据。

独立结清只证明该应用进程已退出，不证明后代/VM停止。Linux现有观察器无法对已消失/僵尸等重新取得完整映像身份，仍保留未知；旧缺身份和派生/记录失败窗口也不能强制解锁。持久监督者、更完整恢复、稳定安装/UI/真实Windows签名缓存/Linux依赖闭包等仍需开发或实测，不将本核心增量写成W05整体已完成。

43项整体未完成，集中实机总验收尚未开始，G0/G1未通过、graceful_stop_verified仍false。D02三层回程/二层隔离、远程认证显示/窄通道/课程映射/调度/硬额度、审计外部封存/换库/显式pending处理、更广来宾/OCI异常修复、最终安装/更新、外部Kali→Windows→AD、真实课程/O02与完整G0负向矩阵继续沿台账推进，缺实现不概括为只等用户测试。

### 工作区与恢复入口

全部改动保留未提交；未提交、推送、重打已发布App、制作新ZIP/最终安装器、覆盖旧包或发布，原Mac更新器保留。未重做Windows实机Smoke（完整回归只有既有不启动真实QEMU的单元边界），未停止现有VM、运行实际到期调度、删除用户资产或扩大宿主实验网络。证据根 `output/launcher-recovery-20261026`。

自有HTTP夹具127.0.0.1:18746经当前UID/完整命令/cwd核验后结束，浏览器回空白页；不使用历史PID操作用户资源。完整回归内的短命fakeqemu --version/fixture-worker不作VM运行事实。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第96节、版本启动器/连续开发说明末尾与43项台账末尾，现场核验Git/实例并保留全部改动；推进剩余实际开发，最后集中实机验收。旧无身份/不可重查启动保持未知，不能无证据强制解锁。不重做Windows Smoke，不停止现有VM、运行实际到期调度、删除用户资产、提交、推送、覆盖旧包或发布；保留原Mac更新器，缺镜像/SSH/证书已知。

本轮最终完整 `python3 -B -m unittest discover -s tools/tests -v`：1406项，1385通过/21条件跳过，234.281秒，退出码0；日志末尾guest-password为既有预期拒绝路径输出，不是实机失败/成功或新增授权。最终摘要 `output/launcher-recovery-20261026/final-evidence.json`，完整日志full-tests.log、独立副本isolated-tests.log、源码保全source-preservation.json。最终只读本机快照未发现QEMU/本轮HTTP夹具/fixture-worker，18746无监听；执行会话全部结束。远端实例未现场查询，不推断状态；未停止用户VM、执行实际调度或删除资产。下一步继续真实开发缺口，再统一准备受限实机验收。

## 97. 剩余开发整批集成与统一核验（2026-10-26）

用户在第96节后要求“一次完成后续所有任务”并继续。已现场读取AGENTS.md/状态/说明/43项台账，核验正式目录、Git及本机进程，保留全部既有改动。目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`不变。初始本机未发现QEMU/旧HTTP夹具，不据此推断远端Windows状态。

本轮没有停在计划，新增并接入：D02独立veth/容器与终端/32回程及显式新来宾Docker安装材料；固定离线分析器配方/预算/原件保护/原始输出封存；审计未决显式观察结清、签名快照、无pending/active契约的显式换库与冻结后续建；周期调度开发入口（默认只读、从未运行真实到期调度）；教师/管理员许可缓存课程映射；固定SSH会话内认证显示与活动租约/归属逐次核验；普通用户预委派Linux cgroup CPU/内存/PID约束及单文件限额、实际内存预算准入；实例封存证据下载/暂停/续传与桌面入口；独立版本管理桥接/界面；外部Kali→Windows→AD的固定TCP服务通道、虚拟硬件身份/新challenge及签名恢复收据。具体入口、行为、失败保全、全部43项剩余判据和集中实机验收次序见[整批说明](ctflab-remaining-development-2026-10-26.md)。

整批复核修正离线分析原件权限与非root读取冲突：保持原件，先落意图，在私有父目录创建独立可读副本，核对原件/副本摘要与文件身份；显式处理namespace PID1的SIGTERM，封存后正常退出本次专用容器。分析专项最终12项通过，其中实际Popen只执行自有假分析程序并验证正常退出，不是Linux namespace/Docker/VM验证。测试夹具1秒预算出现一次超时，独立诊断正常后增加该信号测试的假程序预算为10秒，状态生成后仍限2秒退出；生产分析预算不放宽。独立源码核验脚本首次将运行时路径重复拼tools，确认全部文件存在后修正，是辅助脚本错误，不是产品闭包缺失。新增隔离CLI检查又发现分析入口缺相邻模块搜索路径，已修正并新增用例；副本准备的延迟依赖补入来宾材料，独立源码中实际执行副本准备与原件权限核验，材料专项2项通过。首次夹具未规范化的Mac临时目录被符号链接保护拒绝，改为resolve后的自有目录后通过，不放宽产品保护。

### 验证口径

证据根 `output/remaining-development-20261026`。早期阶段完整1460项/1439通过/21跳过，以及修正前整批1503项/1482通过/21跳过均保留为历史，不能冒充下方最终修正代码结果。新增模块专项、最终完整回归及独立源码副本结果在本节末尾追加。前端30项模型检查和27模块生产构建已通过；Rust `cargo check --locked`、`cargo test --locked`（1项固定入口白名单）及stable rustfmt检查通过，仅表示编译/入口约束，不是原生业务或安装验收。

测试使用临时SQLite/文件、假VM/SSH/显示/分析器/时钟、内存cgroup树、SMBIOS结构及provider注入。没有真实SSH、来宾Docker/KVM/cgroup压力、原生Windows API/IPC、真实课程或最终包验证；本轮没有浏览器人工验收，不挪用前轮invoke替身结论。源码副本仅复制显式FILES，不生成交付ZIP。运行时64模块本地导入闭包静态核对无缺失，不等于系统依赖闭包已验。

### 未完成项与操作边界

**43项整体仍未完成，集中实机总验收尚未开始，G0/G1未通过、graceful_stop_verified=false。** 尚缺全L3/UDP外部隧道及真实路由、文件系统总磁盘配额/全平台限额、长期监督和更广未知/来宾半装载恢复、稳定安装管理/最终安装器/在线更新与原生依赖闭包、真实C01—C07内容/教学和O02镜像/重复分析、完整G0负向矩阵及最终包5人试点。不能把这些缺实现写成只等用户测试。受限TCP服务不是完整E01—E03；RLIMIT_FSIZE不是总配额；签名快照不是外部可信锚；AD收据核验不是现场健康实测；分析配方不是已构建可复现镜像。

全部改动未提交，未推送或公开发布，未重打已发布Mac App、制作新ZIP/最终安装器或覆盖旧包；dist仅本机开发构建。原Mac更新器/验收入口/测试3文件与HEAD一致；实际发行沿历史，本轮不查远端。没有停止现有VM、运行实际到期调度、删除用户资产、修改宿主实验网络、增加对外监听或安装系统服务。Windows实机Smoke不重做，完整回归仅含既有不启动真实QEMU的单元边界。缺镜像/SSH/签名证书已知，不重复索要。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第97节、整批开发说明与43项台账末尾，现场核验Git/实例并保留全部改动；按整批说明第4节继续未关闭开发，最后集中实机验收，不把43项/G0/G1写成完成。不重做Windows Smoke，不停止现有VM、运行实际到期调度、删除用户资产、提交、推送、覆盖旧包或发布；保留原Mac更新器，缺镜像/SSH/证书已知。

资源收口：最后完整/独立副本执行会话已结束；只读本机快照未发现qemu-system、本轮显示/到期调度/HTTP夹具或fixture-worker。未操作任何用户VM或使用历史PID。本轮未创建HTTP服务器/浏览器夹具；短命测试程序均由测试收回，不能推断远端Windows状态。进程快照见output/remaining-development-20261026/process-final.json。

本轮最后统一核验：完整1506项，1485通过/21条件跳过（227.492秒）；独立源码616项，608通过/8跳过（17.348秒），178文件/126个Python语法/12个固定CLI帮助通过。前端30项与27模块构建、Rust检查/1项白名单测试/格式通过；文档94项（89通过/5条件跳过）。最终摘要output/remaining-development-20261026/final-evidence.json，完整full-last.log、独立isolated-corrected-final.log。早期1503/1505/1506等日志仅阶段历史；最后整批在CLI及来宾依赖修正后启动，未用早期通过替代最终。

## 98. Linux专用文件系统容量绑定与复制/启动门（2026-10-26）

按用户要求读取AGENTS.md、第97节、整批说明与43项台账末尾，现场核验正式目录、Git/本机实例。目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`不变；保留全部既有修改/未跟踪文件。开始本机未发现QEMU或到期调度/HTTP夹具，不能推断远端Windows状态。

本轮推进整批说明第4节的多文件存储增长缺口：新增`ctflab_storage_boundary.py`，普通用户Linux对部署方预配置的独立ext4/XFS文件系统做只读描述/绑定，核验当前mountinfo、保留目录FD、设备/文件系统ID、数据容量、普通用户可用空间、根目录inode和挂载命名空间。仅支持完整本地块设备根，要求私有目录、rw/nodev/nosuid，拒绝bind别名/共享设备/嵌套或叠加挂载、容量/身份漂移和不支持平台。不创建/挂载/格式化/扩容/删除任何卷，不设置项目配额。

可选profile.storage_boundary接入代次准备/重置复制前、逐文件前和选择新代次前；中途删除/替换声明不能变成无限额提交，失败保留部分副本/未决意图和原件。QEMU启动前、worker日志/派生前与活进程观察复核；launch.json绑定完整描述，storage.json明确观察范围。远程租约至少按整个声明上限计入预算、固定描述摘要，拒绝同卷/祖先实例根；不释放额度或运行到期动作。原有限额路径与无声明旧profile保持，Mac更新器不改。

[实现、入口和限制](ctflab-storage-boundary-2026-10-26.md)。证据根`output/storage-boundary-20261026`，start-source.json保全183文件。新增专项13项通过，含生产probe的内存内核FD替身、复制中漂移/删声明拒绝、普通用户可用空间不足、整卷预算、QEMU启动拒绝及worker核验顺序；原代次18项、租约24项、driver20项（19通过/1条件跳过）、来宾材料2项通过。首次专项3处夹具错误（Path.stat双重mock、重复独占创建profile）修正后通过，没有放宽保护。最终完整/独立副本结果在本节末尾追加。

范围必须保留：只读描述绑定不是已经部署的Linux磁盘，也不是项目配额/全局物理存储计费；容量为文件系统数据容量，元数据/底层thin或稀疏容器、公共缓存/审计/作业日志不包含。原disk_reservation_hard_enforced不整体置true；真实Linux容量写满/inode耗尽/重启重登记、Windows总配额仍缺。没有真实块设备、Linux原生/VM、SSH或最终包验收；本轮Mac只运行临时文件/SQLite、内存内核观察和假进程/控制器。未运行用户路径inspect，CLI只核验帮助/拒绝与替身。前端/Rust未修改，不重跑或挪用旧结果作为本轮新证据。

43项/G0/G1仍未完成，graceful_stop_verified=false，集中实机总验收尚未开始。全L3/UDP外部隧道、长期监督/未知恢复、更广来宾/OCI修复、完整平台存储/资源支持、稳定安装管理/最终安装器/在线更新、真实C01—C07和O02镜像/重复输出、原生闭包/G0负向/最终包5人试点等沿整批说明继续，不能概括为只等测试。缺镜像/SSH/证书已知，不重复索要。

全部改动保留未提交，未提交/推送/覆盖旧包/发布，未重打已发布Mac App或制作交付ZIP/安装器；实际发行沿历史，本轮未查远端。没有重做Windows实机Smoke、停止现有VM、运行实际到期调度、删除用户资产、安装宿主服务、修改宿主网络或增加对外监听。新增模块/测试/说明及运行时/离线/来宾材料依赖已纳入白名单，材料测试仅临时生成，不安装到本机。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第98节、专用文件系统容量说明与43项台账末尾，现场核验Git/实例并保留全部改动；按整批说明第4节继续未关闭开发，最后集中实机验收，不把43项/G0/G1写成完成。不重做Windows Smoke，不停止现有VM、运行实际到期调度、删除用户资产、提交、推送、覆盖旧包或发布；保留原Mac更新器，缺镜像/SSH/证书已知。

资源收口：最终执行会话结束；只读本机快照未发现QEMU、本轮调度/显示/HTTP夹具或fixture-worker。未创建HTTP服务器或浏览器夹具，未操作历史PID或用户VM；不推断远端Windows/SSH状态。完整进程核验见output/storage-boundary-20261026/process-final.json。

第98节最终核验：完整1519项，1498通过/21条件跳过（230.331秒）；独立源码629项，621通过/8跳过（18.137秒），181文件/128个Python语法/13个固定CLI帮助通过。新增专项13项通过，文档94项/89通过/5跳过。前端/Rust未改未重跑。最终摘要output/storage-boundary-20261026/final-evidence.json；完整full-final.log与独立isolated-corrected-final.log，早期日志仅阶段历史，不代表当前源码重跑。

## 99. Mac APFS容量约束接入原运行器与跨平台功能矩阵（2026-10-26）

用户继续并要求Mac也改，同时询问“之前所有功能Mac具备了没，Windows是什么形式”。明确答复：**Mac尚未具备全部后续功能；Windows是Tauri/React桌面工作台源码/测试候选，最终NSIS安装版未完成。** 原Mac为Swift原生界面调用原Python CLI，既有导入/启动/停止/重置/快照/显示和旧更新链保留；共享Python/新版React页面不能当作已经进入原Mac App。Windows运行时/离线WebView2/当前用户NSIS为目标，当前bundle.active=false，没有新的最终安装包。详见[Mac/Windows功能接入与交付矩阵](ctflab-mac-parity-2026-10-26.md)。

已读AGENTS.md、第98节、容量说明与43项台账末尾，核验正式目录/Git/本机实例。目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`不变；全部既有修改/未跟踪文件保留。开始本机未发现QEMU/实际调度/HTTP夹具，不能推断远端Windows状态。

本轮实际实施：新增`ctflab_macos_storage.py`，Darwin显式64位getfsstat64/fstatfs64、固定只读diskutil plist核对APFS卷CapacityQuota及UUID/设备/挂载FSID/根inode，拒绝系统/Data角色卷、无限额/锁定/snapshot/错绑/别名/嵌套及配额身份漂移。原Mac CLI新增storage-limit，只向新的空私有状态根独占登记明确接受的描述，不创建卷/设置配额/迁移资产；storage文本/JSON报告新增容量状态。原LabManager操作门与安装QEMU/实验网络/运行QEMU派生前核验，移走声明不降为无限额，失败保留部分文件；stop/stop-install不因配额异常被额外阻断。磁盘满时锁诊断刷新/关闭失败不掩盖原操作异常，并保证解锁/关闭。原Mac更新器未改。

Mac工具/App候选白名单增加新依赖；集成源码白名单复用Mac工具白名单并包含固定profile，使新Mac专项/原CLI帮助可在独立副本运行。源码进展不等于已安装App更新：没有重建或覆盖用户原Mac App，也没有新增Swift配额设置页；当前只能通过未打包源码CLI明确登记。未来补齐Mac其他功能须同时完成对应后端与界面/打包/实机，不能只开平台判断或复制React页就宣称全部具备。

证据根`output/mac-storage-20261026`。Mac专项15项通过，原生命周期12项、快照17项通过（临时文件/假QEMU或自有短命程序，不是VM验收）。当前Mac真实执行getfsstat64/fstatfs64只读ABI核对，目录FD与挂载表一致，见native-readonly.json；仅接口读取，APFS专用限额卷成功路径为替身，未实测真实配额/写满。未对用户路径inspect/登记、改配额或创建/挂载/格式化/扩容真实卷。

辅助调查曾错误使用需seek的plist管道读取器及不存在的源码常量，已改为字节解析和实际白名单；首轮独立副本暴露ctflab_platform遗漏，已复用Mac工具闭包再验证，失败日志保留。完整与独立副本最终结果见本节末尾，不以旧轮或修正前结果替代。Swift/React/Rust未修改，本轮不重跑其构建，不把旧结果当作新原生验证。

全部改动保留未提交；不重做Windows实机Smoke，不停止现有VM、运行实际到期调度、删除用户资产、提交/推送、覆盖旧包或发布。未制作交付ZIP/最终安装包，实际发行沿历史，本轮未查远端。原Mac更新器/验收入口/测试三文件与HEAD核对；镜像/SSH/签名证书暂缺已知，不重复索要。43项/G0/G1未完成，graceful_stop_verified=false，集中实机总验收尚未开始。

仍需推进：Mac原App的新版拓扑/远程/容器/审计等接入、Mac/Windows完整硬资源限额和原生存储验证、全L3/UDP外部隧道、长期监督/更广恢复、真实C01—C07/分析镜像与重复输出、最终安装更新/原生闭包/G0负向及5人试点。不是只等测试，后续按整批说明第4节和本轮矩阵开发，最后集中实机验收。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第99节、Mac/Windows功能矩阵和43项台账末尾，现场核验Git/实例并保留全部改动；继续补未关闭开发与Mac接入，最后集中实机验收，区分共享核心/界面/包/实机，不把43项/G0/G1写成完成。不重做Windows Smoke，不停止现有VM、实际到期调度、删除用户资产、提交/推送、覆盖旧包或发布；保留原Mac更新器，缺镜像/SSH/证书已知。

资源收口：最后完整/独立副本执行会话结束；本机只读快照未发现QEMU、本轮实际调度/显示/HTTP夹具或fixture-worker。没有创建HTTP服务器或浏览器夹具，没有操作用户VM/历史PID、真实卷/配额；不推断远端Windows/SSH状态。快照见output/mac-storage-20261026/process-final.json。

第99节最终核验：完整1534项，1513通过/21条件跳过（231.651秒）；独立源码644项，636通过/8跳过（17.735秒），207文件/147个Python语法/15个固定CLI帮助通过。Mac专项15项通过，原生命周期12项/快照17项通过，文档94项/89通过/5跳过。真实Mac仅只读挂载表/目录FD接口，配额正向/VM/原App更新未验；Swift/React/Rust未改未重跑。摘要output/mac-storage-20261026/final-evidence.json，完整full-final.log、独立isolated-corrected-final.log，早期失败/阶段日志保留。

## 100. Mac原生远程工作区、固定stdin桥接与请求保全（2026-10-26）

用户要求继续完成后续所有功能，期间再次“继续”，沿同一目标推进。已读AGENTS.md、第99节/矩阵/43项台账末尾，现场核验正式目录/Git与本机实例。目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`不变；全部既有修改/未跟踪文件保留。开始本机未发现QEMU/实际到期调度/HTTP夹具，不推断远端Windows状态。

本轮把既有受限远程客户端接入原Swift Mac界面，新增“远程实验…”面板：[实现与边界](ctflab-mac-remote-2026-10-26.md)。原生保存/读取私有目标、显式连接与取消、分配实例/当前状态、准备/启动/正常停止/整课重置/恢复/取消后续、租约申请/原ID续期/释放、未决账本只读恢复与明确原标识重试、独立显示请求、许可资产上传/暂停/续传/当前远端核对、封存证据下载/暂停/续传与本机历史。读取/界面打开不自动连接或变更；关闭面板不停止VM或自动重发。配置既可选择管理员给的私有文件，也可填写服务器/UUID/端口/用户、选择身份与固定主机密钥并使用系统SSH生成私有配置；私钥不复制，不自动连接。服务器课程管理仍未接入。

原CLI新增固定remote-client标准输入桥接，根固定为当前状态根/remote-client，不从JSON接受root或任意命令，复用ClientStore及原固定SSH协议/角色/范围/租约/持久意图和传输逻辑。Swift载荷不入argv/操作日志，JSON请求64KiB/回复缓冲4MiB，未知保留原记录；独立上下文序号拒绝迟到回复，状态/租约/owner读取失败不沿用旧观测。取消先到沿原终止记录，迟到取消不追溯已返回连接。传输进度只轮询本机SQLite，下载记录按目标/实例隔离，verified历史不作为当前证据。Mac原工具白名单补客户端固定模块闭包（70工具文件，静态本地导入无缺失）；原Mac更新器未改，本机运行链保留。

证据根output/mac-remote-20261026。固定桥接专项10项通过（真实ClientStore/SQLite/契约/租约，SSH和VM为替身），Swift核心241项检查通过，SwiftUI类型检查/独立GUI编译通过；完整/独立源码及最终结果见本节末尾。没有人工窗口交互、真实SSH/远程显示/Tk/来宾/VM验证。编译产物仅output内独立可执行文件，没有启动该界面或构建/覆盖正式App包。首次Swift检查发现嵌套回调缺主线程隔离声明；补充后通过。连接专项首次漏注入connect_send，尝试运行自有不可执行夹具即拒绝、没有启动SSH/联网；补齐替身后通过，失败日志保留。

仍未完成：原Mac App包未更新；Mac本机通用拓扑/部署、容器来宾、审计运营、服务器课程管理与原生权限/交互仍需接入或验收。长期监督/更广未知恢复、全L3/UDP外部隧道、完整平台配额、真实C01—C07和分析镜像/重复输出、最终安装更新/原生闭包/G0负向/干净机/5人试点继续沿整批说明。43项/G0/G1未完成，graceful_stop_verified=false，集中实机总验收未开始，不概括成只等测试。

未重做Windows实机Smoke、不停止现有VM、运行实际到期调度、删除用户资产、提交/推送、覆盖旧包或发布；未生成交付ZIP/最终安装器、未重打已发布Mac App。Windows形式仍为Tauri/React桌面候选，目标NSIS当前用户安装包，不能拿Mac编译证明Windows最终包完成。原Mac更新器/验收入口/测试三文件与HEAD核对。已知缺镜像/SSH/证书，不重复索要。

接续：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第100节、Mac原生远程说明和43项台账末尾，现场核验Git/实例并保留全部改动；继续补未关闭开发与Mac本机接入，最后集中实机验收。不重做Windows Smoke、不停止现有VM/实际到期调度/删除资产/提交推送/覆盖旧包/发布，保留原Mac更新器，缺镜像/SSH/证书已知；不把共享核心/源码界面/编译写成旧App更新、全43项或G0/G1完成。

资源收口：完整/独立源码执行会话结束；只读本机快照未发现QEMU、本轮实际调度/显示/HTTP夹具/fixture-worker或独立GUI进程。没有启动该GUI、真实SSH或来宾，没有停止用户VM/操作历史PID、修改宿主网络/卷；不推断远端Windows状态。编译产物仅output内，不是更新后的原App。快照见output/mac-remote-20261026/process-final.json。

第100节最终核验：完整1544项/1523通过/21条件跳过（236.831秒）；独立源码654项/646通过/8跳过（18.678秒），212文件/148个Python语法/15个固定CLI帮助通过。Mac固定桥接10项通过，Swift核心241项检查及原生GUI编译通过；文档94项/89通过/5跳过。Swift编译检查在工作区单独执行，不冒称独立副本做了窗口或SSH验收。摘要output/mac-remote-20261026/final-evidence.json，完整full-complete.log、独立isolated-corrected-final.log；前期1543等阶段日志不替代最终新配置向导结果。

## 101. 桌面未领取原请求的显式继续派发（2026-10-26）

承接用户“读AGENTS.md和状态第100节，核验并保留改动，沿用全部操作边界，推进剩余功能”。已读取AGENTS.md、第100节、整批说明第4节/43项台账末尾，核验正式目录 `/Users/pufei/Downloads/ctf-lab`、分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`。全部既有修改与未跟踪内容保留，初始本机未发现QEMU/实际到期调度/HTTP夹具，不推断远端Windows状态。保全摘要output/dispatch-recovery-20261026/baseline.json。

本轮修复A03/W04/W05一处实际恢复缺口：桌面请求已提交而后台派发失败时，旧派发标记会阻止重复提交再次派发；初次prepare尚无运行代次，界面也无法走常规恢复。现增加只读LocalService.dispatch_status与桌面“继续派发原请求”入口，打开/刷新只核对数据库，不自动派发。用户明确确认后仅继续**仍为pending且当前active的原操作**，复核实例、所有者、操作UUID、当前状态版本；不创建新业务操作，不改变幂等键、参数、代次或取消标记。界面重开后亦可使用，不依赖原窗口内存。取消使版本变化，旧版本继续派发被拒绝；读新版本后领取仍先处理原取消，不继续准备/启动。

继续派发自身有独立attempt_id和独占不可变记录desktop-redelivery-*.json。同一次尝试重复到达只返回已有登记，不再次启动执行器；派发异常保留unknown，先读状态后才能由用户决定新尝试。已executing/unknown/completed或非active的业务操作一律拒绝继续派发，不能据此重放启动/关机或来宾命令。其安全依据是LocalService原有工作门锁与pending→executing事务：即使原执行器迟到或两个执行器同时到达，只有一次后端领取；额外进程可能返回忙/原结果，不承诺恰好只创建一个操作系统进程。

执行器身份记录改成每次独立文件desktop-execution-<operation>-<uuid>.json，旧同名身份文件保留并兼容读取，避免旧记录阻断尚未领取请求。概览最多核验64份身份记录，任何一份现场确认running都报告running；缺失、损坏、超限或身份不符保留unknown，不把记录存在当作退出证明。不据文件PID自动重开控制通道、终止进程或接管匿名管道。

影响源码：tools/ctflab_local_service.py、tools/ctflab_desktop_bridge.py、tools/tests/test_ctflab_desktop_bridge.py、desktop/src/model.mjs、desktop/src/model.test.mjs、desktop/src/main.jsx。Mac原Swift远程工作区/本地链/原更新器本轮未修改；该入口属于通用Tauri桌面源码，不能当作Mac本机通用QEMU后端已支持或旧Mac App已更新。没有改Rust桥接协议或重新制作安装器。

验证证据根output/dispatch-recovery-20261026。桥接17项通过：真实临时SQLite与派生文件、重新打开、派发失败、原ID重复、取消、过期版本/跨实例/所有者、已执行未知拒绝、旧身份保全、迟到和并发执行器；后端与内核身份为替身，未启动真实SSH/VM。React32项通过，前端生产编译通过。独立白名单源码复制212文件/148个Python语法/15个固定CLI帮助通过，665项/657通过/8条件跳过（18.024秒），没有创建交付ZIP。完整回归结果记录于本节末尾；最终仅调整拒绝派发的公共错误码为state-conflict，完整回归期间另重跑桥接17项及独立源码665项覆盖最终源码，不把取消专用错误提示用作派发状态。

剩余：本轮仅闭合“尚未领取”的派发窗口。已开始执行后的崩溃、尤其首次prepare提交运行代次前的半成品，只保留unknown/现场，不能使用本入口重放，仍需后续更广恢复设计；长期后台监督/匿名管道接管、Mac本机通用拓扑/容器/审计和服务器课程管理、全L3/UDP、完整平台配额、真实C01—C07与分析镜像、最终安装更新/原生依赖/G0负向/干净机/5人试点均未关闭。43项/G0/G1未完成，graceful_stop_verified=false，集中实机总验收未开始，不能概括为只等测试。

沿用全部禁止事项：未重做Windows实机Smoke、未停止既有VM/运行实际到期调度/删除用户资产/修改宿主网络或卷/提交推送/覆盖旧包或发布。没有生成交付ZIP/最终安装器或更新已发布Mac App，已知缺镜像/SSH/证书不重复索要。本轮只构建desktop/dist开发前端产物。资源与原Mac更新器保全结果见本节最终核验。

接续：继续 `/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第101节、整批说明第4节和43项台账末尾，现场核验Git/实例并保留全部改动；继续已领取未知恢复及Mac本机接入等剩余功能，最后集中实机验收。沿用全部边界，不重做Windows Smoke，不停止既有VM、运行实际到期调度、删除资产、提交推送、覆盖旧包或发布，保留原Mac更新器；不把43项/G0/G1写成完成。

第101节最终核验：完整1555项/1534通过/21条件跳过（237.105秒）；最终桥接17项通过，React32项通过/前端构建通过；独立源码665项/657通过/8跳过（18.024秒），212文件/148个Python语法/15个固定CLI帮助通过。完整测试期间仅调整派发拒绝的公共错误码，最终专项及独立副本已覆盖该改动，不重复把早期导入当作最终错误提示验证。未改Swift/Rust，本轮未重跑其编译。摘要output/dispatch-recovery-20261026/final-evidence.json；完整full-tests.log、最终桥接bridge-final.log、独立isolated-corrected-final.log。最终只读本机快照未发现QEMU/调度/显示/HTTP或本轮执行器，不推断远端实例。原Mac更新器三文件与HEAD一致，全部369份基线文件仍在（本轮预期9份变化/360份相同）；未操作既有VM或用户资产，没有提交/推送/打包旧App/覆盖旧包/发布，G0/G1和集中实机验收不改变。

## 102. 首次准备中断的保全封存与全新准备（2026-10-26）

承接用户“读AGENTS.md和状态第101节，沿用全部边界，推进剩余功能”。已读AGENTS.md、第101节及相关存储/协调/契约/桌面入口，核验正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`不变；既有修改/未跟踪内容全部保留。开始只读本机进程快照未发现QEMU或实际到期调度/HTTP夹具，不推断远端Windows状态。基线output/preparation-recovery-20261026/baseline.json。

本轮闭合第101节“首次prepare已领取、生成半成品但尚无选定代次”的一段恢复缺口。通用Tauri桌面新增“保留现场，重新准备”：只有原首次prepare已执行/失败/未知（或已取消）、契约代次仍为1且状态符合、实例存储active_generation=0时才可显式申请。仍为pending的请求继续走第101节原ID派发，不能把待领取请求当作失败重新建立。界面打开/刷新只读；新入口须用户明确确认。

实现沿用原工作门锁，再取得代次门锁：原执行器尚在执行、锁被占用时拒绝。服务端核对所有者/实例/原操作UUID/状态版本，参数固定复制原准备的course_id/baseline_id，不接受新命令/路径/参数；以新操作UUID和绑定原操作/版本/attempt_id的幂等标识登记全新准备。重复同次请求返回同一新操作，不自动重新派发。新派发失败保留pending，仍可用第101节入口显式继续；迟到的旧执行器只得到原未知或失败结果，不会继续复制。固定本地契约协议未新增远程操作，也未给远程角色或租约增加绕行入口。

GenerationStore.preserve_initial_preparation仅允许active=0、没有任何启动/关机effects、没有其他未决操作、候选计划/首次prepare归属可核验；发现prepared代次、非首次准备、外来未决或启动记录即拒绝。不修改、覆盖或删除旧磁盘、NVRAM、目录及原始资产。旧preparing候选在账本标记preserved；未决prepare记录为保全封存，不能标作原准备成功；既有失败/取消回复保留。独立preparation_restarts表只在明确封存时按需新增，记录原/新操作收据；不为只读打开迁移或修改状态。

新准备使用新操作命名的独立目录，旧候选与新候选可同为编号1，但只有唯一prepared记录允许node_paths选择；半成品不自动采用。容量检查仍计入保留副本占用，不为腾空间回收资产。封存账本与契约库不是跨库原子事务：封存后、新意图提交前再次中断，会留下保全收据和旧现场；后续显式申请能继续创建新操作，不回滚封存、不重放旧准备。该窗口有专项验证。恢复来源从canonical持久操作账本定位，事件时间线裁剪后仍可核对。

影响源码：tools/ctflab_generation_store.py、tools/ctflab_scenario_coordinator.py、tools/ctflab_local_service.py、tools/ctflab_desktop_bridge.py、tools/tests/test_ctflab_desktop_bridge.py、desktop/src/model.mjs/model.test.mjs/main.jsx。原Swift Mac界面、原Mac更新器和Rust桥接未修改；本轮不是Mac本机通用QEMU后端接入或已发布App更新，没有重建旧App、交付ZIP或最终安装器。

证据根output/preparation-recovery-20261026。最终桥接32项通过（原17项加15项），覆盖部分复制、领取后首磁盘前、原失败/取消回复保全、待领取拒绝、原ID/同次请求幂等、锁占用/并发、新代次已提交/启动effects/外来未决拒绝、封存后契约提交前再次中断、多次半成品保留、事件裁剪及新派发失败接回第101节。均为真实临时SQLite/文件与后端/内核替身，不启动真实SSH/VM。React34项通过/生产构建通过。独立源码复制212文件、148个Python语法和15个固定CLI帮助通过；680项/672通过/8条件跳过（19.440秒）。完整回归及最终保全结果见本节末尾。

额外合成链路check_lifecycle.py：在保留旧半成品后，经真实契约/协调器完成新代次启动、停止、重置到第2代；原盘及4份已有磁盘文件逐字节不变，旧preserved与新prepared均保留。证据lifecycle-evidence.json。driver为内存替身，不能当作实机启动/正常关机或真实来宾业务验收；本轮未操作既有VM、宿主网络/卷或远程实例。

仍未完成：已选定/已启动代次的更广未知窗口与长期后台监督/匿名管道接管；Mac本机通用拓扑/容器/审计/服务器课程管理；全L3/UDP、完整平台配额、真实C01—C07与分析镜像/重复输出；最终安装更新/原生依赖闭包/G0负向/干净机/5人试点。该保全入口不能解决任意代次/来宾未知，不概括为只等测试。43项/G0/G1未完成，graceful_stop_verified=false，集中实机总验收未开始。

全部边界保持：不重做Windows实机Smoke，不停止既有VM、运行实际到期调度、删除用户资产、提交/推送、覆盖旧包或发布，保留原Mac更新器。已知缺镜像/SSH/证书不重复索要。本轮仅更新desktop/dist开发前端构建，不代表Windows最终安装包或旧Mac App更新。

接续：继续 `/Users/pufei/Downloads/ctf-lab`，读AGENTS.md和状态第102节、整批说明第4节与43项台账末尾，现场核验Git/实例并保留全部改动；沿用全部操作边界，继续长期监督/更广恢复、Mac本机接入等剩余功能，最后集中实机验收。不重做Windows Smoke、不停止既有VM/跑实际到期调度/删除资产/提交推送/覆盖旧包/发布，保留原Mac更新器；不把43项/G0/G1写成完成。

第102节最终核验：完整1570项/1549通过/21条件跳过（236.13秒）；最终桥接32项、React34项/前端构建通过；独立源码680项/672通过/8跳过（19.44秒），212文件/148个Python语法/15个固定CLI帮助通过。所有本轮运行源码在完整回归启动前已固定，独立副本与最终运行源码一致；后续仅补本节交接文档和output证据。合成后续启动/停止/重置到第2代且4份既有磁盘逐字节保留，不能替代实机验收。摘要output/preparation-recovery-20261026/final-evidence.json，完整full-tests.log、桥接bridge-final.log、独立isolated-corrected-final.log及lifecycle-evidence.json。最终只读快照未发现QEMU/调度/显示/HTTP或本轮执行器，不推断远端实例。原Mac更新器三文件与HEAD一致，369份基线文件全部在（本轮预期11份变化/358份相同）；未改Swift/Rust及其编译产物，未操作既有VM/真实SSH/宿主网络或卷/实际到期调度/删除用户资产/提交推送/打包旧App/覆盖旧包/发布；43项/G0/G1与正常关机门未关闭，集中实机总验收未开始。

## 103. 整批接入：退出观测器恢复、原Mac本机场景面板（2026-10-26）

用户承接第102节后要求“一次性完成后面任务，现在太慢了”。本轮改为跨后端/桥接/两端界面集中实施与一次完整回归，不再每个小功能单独收口；**全部后续任务尚未完成，仍有开发缺口，不能以局部批次冒称43项/G0/G1完成**。已读AGENTS.md和第102节，核对正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`保持；已有改动/未跟踪文件保留。开始只读本机未发现QEMU/实际调度/HTTP，不推断远端Windows状态。保全基线output/observer-recovery-20261026/baseline.json。

1. **通用退出观测恢复**：Windows/Linux QemuDriver新增supervision/rearm_observer，CLI对应supervision/rearm-observer，Tauri节点新增“恢复退出观测”。明确操作先核验当前实例/代次/版本/节点、无活动业务操作、QEMU内核身份/磁盘/认证QMP；已有观测器确认running时拒绝补建。新观测器在retained内核对象/pidfd后登记ready，再等待退出，既不发送启动/关机/kill，也不重新接管匿名管道。QEMU已经消失但无留存退出证据时仍未知，不能补造过去的退出证明。

2. **独立保全证据**：每次UUID会话在运行尝试内observers/<uuid>独占登记intent/ready/exit和独立有界日志，绑定原binding摘要与QEMU身份，旧worker/observer/退出文件、日志不覆盖。原日志接收器禁止覆盖同名日志，新会话已使用自己的日志根；避免实际补建时被旧日志阻断。重复同次请求不再spawn，失败/超时保留unknown；每运行尝试最多16会话，不自动清理。读取概览只查询观测身份，不自动补建。新退出证据接入原observe/stop等待链；不重发既有stop.intent，graceful_stop_verified仍false。

3. **原Mac本机场景工作区**：Swift新增“本机场景…”面板与固定scenario-client stdin桥接。复用已有原Mac场景资源/网络/节点/重置处理器，不另建一套生命周期。可选择清单并校验设计、显示双网连接与节点配置、逐项选择只读基盘/UEFI code/vars模板、列出/选择实例与读状态、准备派生副本、显式启动/正常停止/新代次重置及收口中断重置。打开/关闭/读状态不自动准备或启停，未知不重发；变更前须重新读取当前状态摘要。准备核对已预览清单摘要，文件漂移拒绝；start须明确勾选x86仿真。面板不开放任意命令、任意状态/socket根、release或release-orphan。载荷只走stdin，不进argv/操作日志，复用64KiB请求/4MiB回复限制及结构化错误。

4. **能力界限**：原Mac场景格式是既有固定kali/straylight/neuromancer三节点/双网模式，不是v2自由拓扑后端。新版通用QEMU驱动仍只支持Windows/Linux；Mac原运行链/原更新器保留。Swift原生GUI编译通过也不代表旧Mac App已更新或真实场景可用。两端矩阵已同步，不能把原场景面板写成通用拓扑/容器/审计/课程管理全部接入。

影响：tools/ctflab_qemu_driver.py、ctflab_desktop_bridge.py、ctflab.py及对应3项测试文件；desktop/src/main.jsx/model.mjs/model.test.mjs；gui三文件；ctflab_integrated_kit.py补原场景测试夹具/设计文档依赖。没有增加发布工具模块或更改原Mac更新器。证据根output/observer-recovery-20261026。

专项：驱动28项/27通过/1条件跳过（真实QEMU fixture未指定），桥接33项通过，Mac固定桥接18项通过（原远程10+本机场景8）；Swift核心245项检查通过，原生GUI独立编译通过；React35项与前端构建通过。驱动专项覆盖新退出身份/摘要拒绝、PID复用、只query-status、同次不重发、spawn失败、retained内核对象替身、日志独立和会话上限；桥接覆盖跨实例/过期版本/代次/节点拒绝；Mac专项用真实原清单校验和临时根，变更处理器注入替身，未启动真实VM或SSH。原Mac场景CLI的原生产处理器合成回归由完整测试一并覆盖，不能替代真实来宾/窗口/网络验收。

独立源码前两次发现缺少原场景测试夹具，保留pre-guard-*和missing-fixture-*失败现场；定位后把原测试和设计文档明确加入白名单，无下载/无交付ZIP。修正后的214文件/149个Python语法/15个固定CLI帮助通过，705项/697通过/8条件跳过（18.571秒）。完整回归期间补了畸形观测身份字段拒绝和此验证依赖；最终驱动专项与独立副本覆盖最终代码，不将早期导入当作最终字段校验验证。完整回归与最后进程/保全结果见本节末尾。

未完成开发继续明确保留：长期后台监督/匿名管道重接、更广已启动未知恢复；Mac v2通用拓扑/容器来宾/审计运营/服务器课程管理；全L3/UDP外部隧道与完整平台配额；真实C01—C07/分析镜像及课程内容、最终安装更新/依赖闭包/G0负向/干净机/5人试点。缺镜像/SSH/证书已知，不能把这些实现缺口都归为外部条件。43项/G0/G1未完成，graceful_stop_verified=false，集中实机总验收未开始。当前已发布App/包没有更新，完整本地测试不证明发布就绪。

全部边界不变：未重做Windows实机Smoke、停止既有VM、运行实际到期调度、删除用户资产、改宿主网络/卷、提交推送、覆盖旧包或发布。只在output编译独立GUI，在desktop/dist构建前端；没有启动该GUI或制作旧App/最终安装器/交付ZIP。原Mac更新器三文件最终与HEAD核对。

接续：继续 `/Users/pufei/Downloads/ctf-lab`，读AGENTS.md和状态第103节、整批说明第4节及43项台账末尾，核验Git/实例并保留改动；按整批方式连续推进剩余开发和统一验证，不再每个小功能收口。沿用全部边界，不重做Windows Smoke、不停止既有VM/跑实际到期调度/删除资产/提交推送/覆盖旧包/发布，保留原Mac更新器；不将43项/G0/G1写成完成，最后集中实机验收。

第103节最终集中核验：完整1587项/1566通过/21条件跳过（244.196秒）；最终驱动28项/27通过/1跳过、桌面桥接33项、Mac桥接18项、React35项/前端构建、Swift核心245项和原生GUI独立编译通过。独立源码705项/697通过/8跳过（18.571秒），214文件/149个Python语法/15个固定CLI帮助通过，白名单无忽略文件。完整期间的字段防御与验证依赖修正已由最终驱动专项/独立副本覆盖，缺夹具的失败日志保留，不误报早期导入范围。证据output/observer-recovery-20261026/final-evidence.json，完整full-tests.log、独立isolated-corrected-final.log、driver-final.log、bridge-final.log、mac-bridge.log、swift-core.log及swift-gui-final.log。369份基线全部在（预期17份变化/352份相同），原Mac更新器三文件与HEAD一致。最终只读快照未发现QEMU/实际调度/显示/HTTP/本轮执行器或独立GUI，未操作旧PID/现有VM/真实SSH/宿主网络卷、未删除用户资产、提交推送/更新旧App/覆盖旧包/制作最终安装器或交付ZIP/发布。不推断远端Windows状态。43项/G0/G1/正常关机门未关闭，集中实机总验收未开始；剩余实现见本节与整批说明。

## 104. 连续整批：Mac通用v2后端、原生工作区、配额衔接与运行时构建支持（2026-10-26开始，2026-10-27继续）

承接用户“全部完成后续内容”并再次“继续”。保持整批实施和统一验证，不逐小点收口；**当前仍不能声明全部后续内容完成**。已读AGENTS.md、第103节与整批剩余表，核验正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`不变。跨日继续时再次核验；未发现QEMU/实际到期调度/HTTP，不推断远端Windows状态。基线output/mac-generic-20261026/baseline.json，既有源码、改动、原始输入和资产保留。

实现与操作入口：[Mac通用v2与完整运行时](ctflab-mac-generic-2026-10-27.md)。本批联通以下链路：

- Darwin原生身份/退出：新增ctflab_darwin_native.py，用本机SDK的proc_bsdinfo/libproc布局（136字节）核对PID/真实UID/启动时间/路径，混入启动会话UUID；路径精确大小写匹配。kqueue注册NOTE_EXIT、再次确认身份后才登记ready，退出码未知保持null。未申请终止/调试权限，不把查不到PID当作已停止。真实内核项只观察自身和专用普通Python子进程，没有VM。
- 通用QemuDriver新增显式darwin-arm64配置，支持ARM64 UEFI/VirtIO/HVF和同一固定运行时内x86 BIOS/TCG；整课含x86时必须明确allow_emulation=true，首节点启动前即检查。全runtime_root清单覆盖bin/动态库/固件等，不只哈希可执行文件目录；拒绝路径越界、链接、固件/清单漂移。NVRAM复制到私有代次并绑定设备/inode，正常写入可保留，替换拒绝。当前固件漂移拒绝新启动，已运行实例仍可沿既有身份/认证通道正常停止。网络仍每网段两成员的回环链路，不声称任意交换网或Intel Mac支持。
- 配置/CLI新增NVRAM模板映射，原BIOS路径不要求该可选文件；已有未启动配置可按相同UUID/清单/源路径/运行配置补齐缺失登记，不能覆盖不同输入、半写文件、已有代次或未决操作。跨实例、旧版本、原始资产和旧候选保全规则沿第101—103节。
- 固定generic-client桥接根限定在当前状态根/generic-instances/UUID，配置、列出、预览、状态、提交、恢复、显示等只走白名单。原Swift“本机场景…”新增“新版通用v2”，接设计/资产/NVRAM/配置、列出选择实例、准备/启停/重置/恢复/取消、两种准备恢复、显示/退出观测补建，以及已配置来宾的网络/DNS/时间/容器/分析入口。源模板导出保留derived语义且不覆盖已有文件；新上下文丢弃迟到状态，未知不重发。原固定三节点与单机入口仍保留。
- 第99节已登记的APFS描述可随新实例配置继续核验父根/配额/挂载身份，在复制、提交、启动、后台执行及运行观察中使用；不创建/挂载/扩容/设配额，不回收文件。跨父根与绑定漂移拒绝。此项不覆盖卷外公共缓存或完整CPU/RSS/PID硬限额，Windows完整配额仍缺。
- 原Mac打包器新增可选generic-runtime-manifest：仅使用明确提供的固定Python运行时和三份摘要匹配的cryptography/Tcl/Tk许可证，保留Tk、隔离导入crypto 46.0.5/Rust、Tcl脚本与依赖，做内存EC操作和相对Mach-O引用检查，写入MANIFEST/SBOM并在verify重复核验；不下载/安装，不打开窗口/套接字/VM。默认历史裁剪与原更新器不变。界面检查依赖可定位性，缺依赖时阻止对应启动/显示；模块存在不冒称原生验证。
- 通用React配置支持可选NVRAM，保留原BIOS导入；增加Mac仿真确认与运行时标识，切换目录清除旧上下文并拒绝迟到回复。修复“可选NVRAM空值阻断所有导入”的集成风险，不让新Mac字段破坏Windows/Linux。

验证证据根output/mac-generic-20261026。最终专项：Darwin内核6项、Mac驱动6项、Mac固定桥接24项（原18+通用6）、桌面桥接33项、Mac存储16项/Linux存储13项、可选完整运行时构建3项通过；Swift核心249项及原生GUI独立编译通过，React37项/构建通过。混合整课用真实SQLite/文件/证书，QEMU/QMP为替身，覆盖准备、3节点启动/正常停止请求、退出、恢复、重置到第2代、旧NVRAM进度/基盘保留；实际未启动/停止任何VM。运行时构建3项使用临时Mach-O/Python替身与注入导入证明，不伪称真实Tcl/Tk或完整App验收。

独立白名单副本218文件/152个Python语法/15个固定CLI帮助通过，724项/716通过/8条件跳过（21.141秒）。原生Swift编译单独在工作区执行。完整回归结果与最后保全/进程绑定记录见本节末尾。全部运行源码在统一完整/独立检查前固定；后续只更新文档与output证据。打包扩展首轮校验代码位置错误及测试断言错误已修正，失败记录保留在generic-runtime-tests*.log，不把前期失败冒充通过。

本批影响ctflab_qemu_driver/desktop_bridge/runtime_inventory/storage_boundary/ctflab.py、App构建器、原Swift三文件/React三文件与对应测试；新增Darwin原生模块和两份测试，Mac工具白名单71文件、独立源码白名单同步。原Mac更新器三文件不修改。

**剩余必须分开记录，不能把“全部完成”写成事实：**

1. 仍有开发：完整多成员网络与全L3/UDP外部隧道；Windows/Mac完整平台硬限额与卷外总量；长期监督/匿名管道重接及更广未知恢复；Mac原生画布/差异编辑、审计运营与服务器课程管理；真实C01—C07/分析镜像/课程制作及最终安装更新/原生依赖闭包。这些不是仅缺实机数据。
2. 外部条件与验收：许可镜像/SSH/证书已知缺少；真实来宾地址/服务/隔离、APFS正向限额卷/写满、真正完整Python/Tcl/Tk运行时、签名/干净机/5人试点和完整G0负向未验，不能由单元数或GUI编译替代。
3. 当前禁止操作不因“全部完成”自动解除：不重做Windows Smoke，不停止既有VM、运行实际到期调度、删除用户资产、修改宿主网络/卷、提交推送、覆盖旧包或发布。本轮仅output独立GUI/desktop/dist和自有临时测试夹具；没有创建交付App/ZIP/最终安装器或更新已发布App。原Mac运行链/更新器保留。

43项/G0/G1未完成，graceful_stop_verified=false，集中实机总验收尚未开始。接续应沿整批剩余表推进，不重复索要已知缺失资源，也不把未完成开发归成只等验收。

接续语：继续 `/Users/pufei/Downloads/ctf-lab`，读AGENTS.md和状态第104节、Mac通用v2说明、整批说明第4节与43项台账末尾；现场核验Git/实例并保留全部改动，连续推进剩余开发并统一验证，最后集中实机验收。沿用全部边界，不重做Windows Smoke、不停止既有VM/跑实际到期调度/删除资产/提交推送/覆盖旧包/发布，保留原Mac更新器；不把43项/G0/G1写成完成。

第104节最终集中核验（2026-10-27）：完整1609项/1588通过/21条件跳过（254.589秒）；独立724项/716通过/8跳过（21.141秒），218文件/152个Python语法/15个固定CLI帮助通过。Darwin原生6、Mac驱动6、Mac桥接24、桌面桥接33、Mac存储16/Linux存储13、可选运行时3项通过；Swift249项/原生GUI编译、React37项/前端构建通过。所有本轮运行代码在完整/独立检查前固定且与最终一致；独立副本未运行App构建替身3项，其验证在完整/专项日志，不混用范围。摘要output/mac-generic-20261026/final-evidence.json，完整full-tests.log、独立isolated-corrected-final.log、native-tests-final.log、mac-driver-final.log、mac-rpc-tests-final.log、generic-runtime-tests-final.log、swift-core-final.log及swift-build-complete.log。369份基线全部在（23份预期变化/346份相同），新增3份Darwin源码/测试及1份说明白名单登记；原Mac更新器三文件与HEAD一致。最后只读快照未发现QEMU/调度/显示/HTTP/日志接收器/本轮执行器或独立GUI，不推断远端Windows状态。没有真实VM/SSH操作、重做Windows Smoke、到期调度、宿主网络/卷变更、用户资产删除、提交推送、旧包覆盖或发布；只编译独立GUI及临时合成App夹具，没有重建交付App/ZIP/最终安装器。43项/G0/G1/正常关机门未关闭，集中实机总验收未开始；剩余开发及外部条件见本节分列。

## 105. 教师/管理员课程与审计双端入口、原请求恢复（2026-10-27）

继续正式目录`/Users/pufei/Downloads/ctf-lab`，现场Git分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`，原修改和未跟踪资产全部保留；没有拉取、切换、提交或推送。阶段开始只读核验未发现本机QEMU或实际到期调度；不推断远端Windows状态。证据`output/course-admin-20261027`，开始摘要`baseline.json`，新增说明`docs/ctflab-course-administration-2026-10-27.md`。

沿整批说明第4节推进R01/R03与审计管理的产品接入：服务器私有策略显式登记courses（catalog/profile当前SHA、课程变体、签名索引源URL及预分配UUID范围），客户端RPC只选择offer/实例，不能提交服务器路径或任意命令。当前未过期教师/管理员、当前策略/目录/profile/许可缓存及索引共同核验；provision只配置实例、契约和引用，不prepare/start。完成收据绑定根/ledger文件身份、配置/profile摘要；中断时仅补同一未准备实例缺失的元数据，拒绝覆盖不同配置、身份替换或已执行后残缺记录。跨文件/缓存引用不是原子事务，失败现场保留。

服务器audit_management显式开启后，管理员可读取分页未决/检查点、预览当前终态关联并明确追加观察。获授权的管理调用不先写普通请求审计，避免自行改变链头导致所有预览立即失效；未授权/结构不符仍常规审计。结清记录包含当前管理员principal，原worker结果保持unknown，VM/来宾/正常退出及自动重放标记均false。RPC同一预览摘要/当前策略/管理员可取回原结清收据；原CLI严格一次性settle保持。需本轮审计核验工具读取含可选principal的新resolution，旧历史记录仍兼容。

React桌面与原SwiftUI远程工作区均新增课程与审计管理区，保存目标/握手角色和能力门禁，先预览再单独确认变更，迟到回复与错目标/错实例/摘要拒绝。React打开管理页暂停实例自动overview/events/lease读取；Mac保持明确读取。两类新变更在ClientStore传输前落意图，unknown保留，重开只读本机记录，恢复原请求后需明确重试，不能自动派发/重放原worker。Mac与Windows源代码接入不表示已安装App更新或两平台实机可用。

本轮新增前端管理组件/模型/3组模型测试与说明白名单；后端改动集中remote_course、remote/audit_review/remote_audit、desktop_remote、client_store及对应测试，Swift核心/模型/界面与核心规则测试同步。没有改Rust接口或原Mac更新器。本轮仅开发前端dist、output独立GUI和自有临时测试夹具，没有构建交付App/ZIP/最终安装器，没有覆盖旧包或发布。

集中验证范围：私有临时文件/SQLite、假SSH/VM、实际ClientStore记录与中断恢复；课程11项、审计23项、桌面桥接17项、ClientStore30项专项通过，Swift256项/原生GUI编译与React40项/前端构建通过。最终完整回归、独立白名单复制及保留核验结果在本节末尾追加；早期fixture源URL误用identifier、时钟与策略摘要夹具错误及审计resolution结构修正日志均保留，不把失败冒充通过。

**尚未完成，分别保留：**

- 开发：全L3/UDP外部隧道、更多网络成员、Windows/Mac完整硬限额与磁盘总量、长期监督/匿名管道重接与更广未知恢复、Mac原生拓扑编辑、真实C01—C07课程/分析镜像及最终安装更新。课程/审计入口已补这一批源代码，真实多用户远程运行与运营验收仍缺，封存换库/调度没有自动接到GUI执行。
- 外部条件/验收：许可镜像/SSH/签名证书已知缺少；真实课程登录/地址/服务/隔离/重置/正常关机、APFS正向限额卷/写满、最终Python/Tcl/Tk闭包、原生交互/安装器/签名/干净机/课堂试点及完整G0负向仍未验。不把单元、编译或合成数据写成实机验收。
- 操作边界：不重做Windows Smoke，不停止既有VM、跑实际到期调度、删除用户资产、改宿主网络/卷、提交推送、覆盖旧包或发布；原Mac运行链/更新器保留，集中实机总验收仍未开始。43项/G0/G1与graceful_stop_verified均不关闭。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，读AGENTS.md、状态第105节、课程与审计管理说明、整批说明第4节和43项台账末尾；现场核验Git/实例并保留全部改动，继续推进未关闭开发并集中验证，最后统一实机验收。沿用全部禁止事项和原Mac更新器，不重复Windows Smoke或索要已知缺失资源，不把43项/G0/G1写成完成。

第105节最终集中核验：完整首轮执行1617项（1596通过/21条件跳过），另有GuiAppBuildTests类准备阶段1项编译错误，原因是初版@Published合并声明。修正为独立声明并使用当前onChange写法后，真实arm64独立GUI编译通过，原构建类3项复测通过（62.602秒）；没有为已通过路径重复全量。本轮最终路径覆盖合计1620项/1599通过/21跳过，**这是完整首轮加修正构建类覆盖，不是一次无错误全量重跑**。Swift核心256项通过；React40项及构建通过。最终独立白名单222文件/152个Python语法/15个固定CLI帮助通过，735项/727通过/8跳过（20.631秒，含帮助核验22.026秒）；独立副本不编译GUI，原生构建结果单列。

保全：373份开始基线全部仍在（22份预期改动/351份相同），原Mac更新器三文件与HEAD一致；222个白名单文件存在且未被忽略，最终运行源码与独立副本摘要一致。阶段最后只读进程快照无本机QEMU/独立GUI/显示进程；没有真实SSH/到期调度或用户VM操作，不推断远端状态。git diff --check通过。摘要output/course-admin-20261027/final-evidence.json，原完整full-regression.log及修正gui-build-tests-final.log、swift-build-final.log、swift-core.log、frontend-tests.log、isolated-corrected-final.log、preservation-final.json和process-final.json保留。没有交付打包/提交/推送/覆盖旧包/发布；43项/G0/G1与集中实机总验收继续开放。

## 106. 连续推进：Mac原生拓扑画布、草稿差异与保留导出（2026-10-27）

第105节课程/审计入口收口后继续实现Mac原生拓扑草稿，没有结束后要求用户再次逐项授权。正式目录、Git分支/HEAD及全部操作边界沿用105；未切换/清理工作区，373份基线与原Mac更新器继续保留。新证据output/mac-topology-20261027，说明docs/ctflab-mac-topology-2026-10-27.md。

原SwiftUI通用实例明确读取后新增编辑面板：原生画布展示节点/网卡/网段与设计连线，添加/移除草稿节点、引用已有资产、增添私有网段、重连/断开/新增网卡；分配未占用设计地址，保持旧MAC及原策略/资产，新增MAC声明derived。ARM节点默认UEFI/VirtIO。纯值副本编辑，不写活动清单或操作VM；暂不完整草稿允许编辑，但生产后端完整校验失败后不能导出为已校验结果。

固定generic-client draft接到生产draft_diff，核对完整清单、依赖、地址及差异；只接受同实例/修订号的迟到回复。差异变动即失效，manifest与当前草稿一致且applied=false才可导出新文件，已有文件不覆盖。导出后按新实例UUID与匹配运行时profile配置；不自动应用下一代次或热改当前运行场景。原生画布尚未提供全部资源/依赖编辑或拖动布局，T02全部判据与实际交互/运行对照仍开放。

Swift271项（新增15项）通过；Swift实际生成草稿经生产Python清单/差异校验，语义不变且未应用。Mac桥接25项（新增1项）通过，真实临时配置实例前后文件摘要不变、代次目录仍空，错误断网草稿被拒绝，无真实VM/SSH。当前命令行SDK缺少State宏插件，初次编译失败日志保留，已沿既有Published模型状态改写，独立arm64GUI编译通过；最后GUI/构建及独立源码影响检查在本节末尾记录。本轮不修改React/Rust、QEMU驱动或原Mac更新器，不重复其无变化路径的测试。

尚有开发与验收分别保留：全L3/UDP/更多网络成员、完整硬限额/磁盘总量、长期监督/匿名管道重接、更丰富原生画布编辑、真实课程/分析镜像与最终安装更新仍缺；镜像/SSH/证书已知缺少，真实来宾/网络/配额/安装签名/干净机/试点及G0负向尚未验。没有重新Windows Smoke、停止既有VM、跑实际到期调度、删除用户资产、改宿主网络/卷、提交推送、覆盖旧包或发布；43项/G0/G1/正常关机门与集中实机总验收均不关闭。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，读AGENTS.md、状态第106节、Mac拓扑草稿与课程审计说明、整批说明第4节和43项台账末尾；现场核验Git/实例并保留全部改动，连续推进未关闭开发并集中验证，最后统一实机验收。沿用全部禁止事项、保留原Mac更新器，不重复Windows Smoke或索要已知缺失资源，不把43项/G0/G1写成完成。

第106节最终核验：最新Swift核心271项通过，原生GUI独立编译通过；受影响GUI/核心/文档及真实Swift参与的临时合成App构建12项通过（94.374秒）；Mac固定桥接25项通过，Swift→生产Python草稿语义核对通过。沿第105节全量基础按本批影响重跑，**没有把增量检查写成新一轮全量无错误重跑**。最终独立白名单223文件/152个Python语法/15个固定CLI帮助通过，736项/728通过/8条件跳过（21.301秒，含帮助22.616秒）；副本不编译GUI，构建验证单列。React本批未改，沿第105节40项及构建结果，不冒称本批重跑。

373份连续批次基线全部保留（23份预期改动/350份相同），原Mac更新器三文件与HEAD一致；223白名单文件存在且未被忽略，最终运行源码与独立副本摘要一致。最后只读快照未发现本机QEMU/实际调度/独立GUI/显示进程，不推断远端Windows状态；未对现有用户实例做操作。git diff --check通过。摘要output/mac-topology-20261027/final-evidence.json，gui-regression-final.log、swift-core-final.log、swift-build-final.log、mac-bridge-tests-final.log、cross-language-evidence.json、isolated-corrected-final.log及preservation-final.json/process-final.json；初次State宏插件错误及目录断言失败日志保留。未创建交付包/提交/推送/覆盖旧包或发布，43项/G0/G1与集中实机验收继续开放。

## 107. 连续开发：双端资源/依赖编辑、循环保护与空闲网段移除（2026-10-27）

按第106节重新读取AGENTS、Mac拓扑/课程审计说明、整批第4节与43项台账末尾；现场Git仍为`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`，保留全部既有修改/未跟踪文件。阶段开始未见本机QEMU，默认CTFLab状态根下generic-instances/scenario-instances均不存在，不据此推断其他目录或远端实例状态；没有创建/改动用户实例。证据output/topology-editing-20261027，基线baseline.json、只读目录计数instance-start.json。

本批沿T02未关闭开发补双端节点资源与启动依赖编辑：Swift MacGraphDraft及React graph-model提供CPU/内存纯值副本变更、依赖集合变更和拓扑排序循环保护，拒绝自引用/重复/缺失节点/间接循环，范围与生产清单一致（CPU1—64，内存256—262144 MiB整数）。两端UI选择/步进CPU及常用内存档位，并保留原有非标准内存值；不是实际硬配额/预留或平台运行支持证明。原生Menu/React依赖复选只修改草稿，不派发当前实例启停。

新增空闲网段移除：网卡仍引用则拒绝，必须先明确断开草稿连接，不为移除网段而隐式移除网卡或用户资产。失败草稿保持原值，成功编辑使旧差异失效，完整后端重校后才能导出。原生面板把关闭按钮移到编辑禁用范围外，等待或上下文变化仍可关闭管理，不触发停止。没有增加QEMU参数/外部监听/宿主网络操作。

本轮涉及Swift核心/模型界面/测试、React图形组件/模型/测试与Mac桥接既有测试增强；没有改原Mac更新器、QEMU驱动、调度、Rust接口或用户资产。Swift281项（新增10项）、React43项（新增3组）及前端构建、Mac桥接25项已通过；两套模型生成同一资源/依赖草稿完全一致，并经生产Python validate_manifest/draft_diff核验applied=false。桥接增加资源/依赖变更及循环拒绝，实例文件摘要与空代次目录保持不变。集中完整回归和最终源码副本/构建结果在本节末尾记录；未把旧轮编译结果充当最终源码验证。

仍需开发：完整多成员网络执行、全L3/UDP外部通道、Windows/Mac完整硬限额/磁盘总量、长期监督/匿名管道重接、更广画布/观测交互、真实课程/分析镜像与最终安装更新。资源声明编辑不替代硬限制，图形连线不替代真实网络。许可镜像/SSH/证书已知缺少，真实来宾/隔离/关机/配额/安装签名/干净机/课堂试点及G0负向仍未验。43项/G0/G1/graceful_stop_verified及集中实机总验收保持开放。

边界全部沿用：不重做Windows Smoke，不停止既有VM、跑实际到期调度、删除用户资产、改宿主网络/卷、提交/推送、覆盖旧包或发布；原Mac运行链及更新器保留。本轮只编译开发前端/output独立GUI和临时合成App测试夹具，不更新已发布App或制作交付安装包。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，读AGENTS.md、状态第107节、Mac拓扑/课程审计说明、整批第4节与43项台账末尾；核验Git/实例并保留全部改动，继续未关闭开发、集中验证、最后统一实机验收。沿用全部禁止事项和原Mac更新器，不重复Windows Smoke或索要已知缺失资源，不把43项/G0/G1写成完成。

第107节最终集中核验（2026-10-27）：完整回归1621项/1600通过/21条件跳过（261.223秒），无失败；该轮启动后只调整Swift弹出sheet所属层级，避免继承父内容禁用状态，最终界面源码另跑真实Swift参与的临时App构建类3项通过（63.403秒），**不把这种组合覆盖写成同一最终源码的一次全量重跑**。Swift核心281项、React43项及最终前端构建、Mac桥接25项通过；两端模型的同一资源/依赖草稿逐值相等且生产Python完整校验通过。独立副本223文件/152个Python语法/15个固定CLI帮助通过，736项/728通过/8条件跳过（20.269秒，含帮助21.645秒）；最终运行源码与该副本一致，GUI编译结果单列。真实窗口关闭交互及来宾/网络未验，不以编译代替。

本轮364份开始基线全在（13份预期改动/351份相同），上轮373份基线文件也全部仍在；原Mac更新器三文件与HEAD一致，白名单未被忽略，git diff --check通过。最后只读进程快照无本机QEMU/实际调度/独立GUI/显示进程；默认通用/场景实例目录计数与开始相同，不推断其他路径或远端状态。摘要output/topology-editing-20261027/final-evidence.json；完整full-regression.log、最终gui-final-source-build.log、swift-core.log、frontend-tests-final.log/frontend-build-final.log、mac-bridge-tests.log、cross-language-evidence.json、isolated-corrected-final.log、preservation-final.json/process-final.json/instance-final.json。弹出层级修正前的副本日志以before-sheet-fix前缀保留，不冒充最终源码。未创建交付包、提交/推送/覆盖旧包或发布；全部操作边界和43项/G0/G1/正常关机门、集中实机总验收开放状态保持。

## 108. 连续开发：多成员回环网段执行与外部UDP命名服务（2026-10-27）

本轮按用户要求读取AGENTS.md及第107节，正式目录仍为`/Users/pufei/Downloads/ctf-lab`，现场分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`。381份开始文件摘要保全在`output/multimember-network-20261027/baseline.json`；全部既有修改/未跟踪文件保留，未拉取/清理/切换。本机开始未发现QEMU；不推断其他目录或远端实例状态。本轮无真实VM/SSH操作。

沿S03/S04/E01—E03/R04推进两个执行缺口，详见[驱动说明末尾](ctflab-production-driver-2026-10-24.md)。通用后端新增按原start_order首成员建立QEMU内部hub、各非中心成员独立回环TCP链路的多成员网段。保留双成员整数端口格式与原命令；其他网段以非中心节点ID映射端口，单成员/空网段为空对象。完整键集合、类型/范围与所有控制/显示/代理端口共同冲突校验；内部ID避开用户网卡ID，不接受任意地址/QEMU参数。完整profile与启动命令继续绑定，端口或中心变化不能重连旧启动。桌面课程导入自动分配每条链路的候选端口，配置不prepare/start；Mac/Linux/Windows共享驱动，不据此宣称各平台实机通过。

外部固定SSH服务增加显式UDP协议：当前角色授权的命名回环服务、原challenge/检查点/代次和序号仍必需。独立数据报send/receive动作保持包边界；空包与超时可区分，累计字节和4096次动作限制、超长/超额拒绝且关闭、不返回截断前缀。TCP/UDP动作不可混用，发送不成功/丢回复不重放，协议需客户端明确选择。固定IPv4回环连接不改路由，不连接真实LAN或外部VM，完整L3隧道与路由集成尚缺。

专项：驱动34项（33通过/1条件跳过）、桌面桥接34项、外部身份/通道/签名21项通过，新增16项用例。驱动首次1处夹具仍绑定旧场景存储，被身份保护拒绝；改为独立合成多成员实例后通过，没有绕过生产绑定。真实本机UDP内核检查验证完整包/空包/超时及剩余额度拒绝，身份仍为替身，无SSH/来宾；macOS自身拒绝16385字节发送（EMSGSIZE），未修改宿主参数，该超长包内核路径保留未测，合成超长拒绝用例单列通过。失败记录`udp-kernel-first-failure.json`及初轮driver-tests.log保留。

实现修改限于通用驱动、课程导入桥接、外部通道及三份既有测试；没有修改Swift/React/Rust、原Mac更新器、调度或用户资产。没有新交付App/ZIP/安装器、旧包覆盖或发布；完整回归可能编译自有临时合成App夹具，不能当成更新已发布App。独立源码白名单/语法/帮助及完整回归最终结果见本节末尾追加；前端未改不重跑。

仍有实际开发：完整L3外部通道/路由集成、Windows/Mac完整硬限额/卷外总量、长期监督/匿名管道重接及更广未知恢复、更广画布/观测交互、真实C01—C07课程/分析镜像、最终稳定安装管理/在线更新及原生依赖闭包。真实来宾多成员网络/隔离、外部SSH/UDP、正常关机、配额压力、安装签名/干净机/5人课堂试点与完整G0负向仍未验；许可镜像/SSH/证书已知缺少，不重复索要。不能把本轮两个执行增量写成全部开发已完成，也不能把真实缺口统归为只等实测。43项/G0/G1/graceful_stop_verified及集中实机总验收保持开放。

全部边界沿用：不重做Windows Smoke、不停止既有VM、跑实际到期调度、删除用户资产、改宿主网络/卷、提交推送、覆盖旧包或发布，保留原Mac运行链/更新器。UDP检查仅使用自有临时回环socket，均由上下文/finally关闭，不安装服务。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，读AGENTS.md、状态第108节、整批说明第4节与43项台账，核验Git/实例并保留全部改动；继续剩余实际开发，集中验证后统一实机验收。沿用全部边界，保留原Mac更新器，不重做Windows Smoke，不停止既有VM/跑实际到期调度/删资产/改宿主网络卷/提交推送/覆盖旧包/发布，不把43项/G0/G1写成完成。

第108节最终集中核验（2026-10-27）：最终运行源码固定后一次完整回归1637项/1616通过/21条件跳过（246.921秒），无失败；本轮完整及独立检查启动后只更新文档和output核验脚本/证据，运行源码未再改变。独立白名单223文件/152个Python语法/15个固定CLI帮助通过，752项/744通过/8跳过（20.803秒；含帮助22.079秒），最终运行源码与独立副本一致；副本文档为复制时快照，后续文档增量不冒称已在副本重跑。Swift/前端/Rust无修改未另跑专项，完整入口中的临时App编译只按该日志覆盖范围记录。

381份开始基线全部仍在（9份预期改动/372份相同），原Mac更新器三文件与HEAD一致；223白名单文件存在且未被忽略，git diff --check通过。最后只读进程快照未发现本机QEMU/实际调度/独立GUI/显示/后台日志接收器，不推断远端Windows/SSH状态。完整执行会话及独立副本会话已结束；没有创建用户实例，自有UDP socket已关闭，未停止既有VM或操作历史PID。最终摘要`output/multimember-network-20261027/final-evidence.json`，完整full-regression.log、独立isolated-corrected-final.log、driver-tests-final.log、bridge-tests.log、external-tests.log、udp-kernel-evidence.json及preservation-final.json/process-final.json。全部操作边界保持；未创建交付包/提交推送/覆盖旧包/发布，43项/G0/G1/正常关机与集中实机验收仍未完成，上述实际开发缺口保留。

## 109. 连续开发：外部Linux点对点IPv4端点、双端转送与部署材料（2026-10-27）

按本次授权重新读取AGENTS.md、状态108及整批说明第4节，正式目录仍为`/Users/pufei/Downloads/ctf-lab`，现场分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`。381份阶段开始文件摘要在`output/external-ip-20261027/baseline.json`；全部既有修改和未跟踪输入保留，没有拉取/切换/清理。本机开始只读快照未发现QEMU；不推断远端或其他目录状态。未创建或操作用户实例。

新增[点对点IPv4实现及边界说明](ctflab-external-ip-2026-10-27.md)。配置显式登记ip_tunnels与principal授权，限制两个不同RFC1918单地址、MTU576—1500及TCP/UDP/ICMP echo；管理端口、任意地址/子网/默认路由、IP选项/分片/IPv6拒绝。包长度/校验和/TTL、传输层结构、服务端口及256条有界60秒空闲回程状态复核；原channel/challenge/checkpoint/代次/序号与累计字节/4096动作额度保持，超限/漂移/错误序号或未知发送关闭自有会话，不重放数据包或VM生命周期。

NativeEndpoint仅允许根所有标记匹配的64位专用Linux虚拟来宾：DMI身份、节点/cohort/checkpoint/代次、允许策略SHA、同目录全部Python源码和固定ip工具SHA绑定。TUN字符设备/FD/命名空间/ifindex核验，以独占非持久接口避开已有接口；检查已有地址/非默认具体路由不重叠，仅配置本次点对点地址、MTU、up及接口内IPv6自动地址关闭。关闭/失败只关闭自有FD，由内核回收该临时接口，不执行删除已有接口/路由命令。**上述内核/工具行为本轮全部通过替身验证，没有在宿主或真实来宾执行**；已有外部默认出口保持不受管，不宣称整台VM隔离。

固定SSH入口新增`relay-ip`：同cohort/代次、不同machine、策略相互镜像的两个端点显式打开并有界转送；不在运行器宿主打开TUN，不自动重连。握手/端点创建之间读取停止请求，第一端打开后取消不再创建第二端；在途请求仍可能完成，随后关闭本次自有通道。SSH强制命令身份不能使用relay-ip扩成出站连接器。新增`materials-ip`只生成新私有目录，含源码/摘要、标记候选、配置及部署边界；不安装账户/密钥/服务/网络，不包含Python/cryptography/ip/TUN原生依赖，工具SHA声明不冒充真实目标已核验。材料生成器自身与延迟依赖纳入67文件运行时闭包，材料副本实际生成第二目录通过，无覆盖或清理。

专项最终29项通过，原外部TCP/UDP/身份/签名21项兼容通过。包括生产ExternalAgent/ExternalSession/Circuit双向检查，以及两条真实SSHSession类经自有固定Python子进程JSONL管道转送完整请求/回复包并收回进程；后者不是实际SSH，端点和来宾身份仍为替身。首次一项固定回复长度断言误写，已改为完整合法IPv4回复包，初轮失败日志ip-tests-first.log保留；没有放宽包策略。Native构造专项核验完整64位ifreq、独占标志及仅针对自有接口的固定命令，Mac平台在打开TUN前拒绝。

本批实现新增external_ip模块及测试，改external代理/会话与CLI、桌面运行时和独立源码白名单；没有修改Swift/React/Rust、原Mac更新器、QEMU生命周期、调度或用户资产。新增说明/源码/测试纳入.gitignore白名单。完整及最终源码独立检查在本节末尾追加；完整运行过程中追加取消与双端清理修正，仅受影响专项与最终独立副本复核，不能冒称同一最终源码的一次全量重跑。未改变前端不另跑其专项。

**未完成的实际开发继续保留：**Windows原生三层端点、子网/更多路由/自动DNS/PMTU与完整外部域课程集成，Windows/Mac完整硬限额/卷外总量、长期监督/匿名管道重接与更广未知恢复、更广画布/观测交互、真实C01—C07课程与分析镜像、稳定安装管理/在线更新/最终原生依赖闭包。镜像/SSH/签名证书已知缺少，不重复索要；真实Linux TUN/服务/隔离、外部Kali→Windows→AD、正常关机、配额压力、最终安装签名/干净机/5人课堂及完整G0负向尚未验。新模块不等于这些任务全部完成，43项/G0/G1/graceful_stop_verified和集中实机总验收保持开放。

所有原边界沿用：不重做Windows Smoke、不停止既有VM/运行实际到期调度/删除用户资产/改宿主网络或卷/提交推送/覆盖旧包/发布；原Mac运行链与更新器保留。本轮只用临时文件、源码副本、材料及自有短命Python管道；完整回归中的临时合成App构建不当成新交付App。没有生成交付ZIP/安装器，没有连接真实SSH、打开宿主TUN或执行ip组网。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，读AGENTS.md、状态第109节、外部IPv4说明和整批说明第4节，核验Git/实例并保留全部改动；继续未关闭实际开发，集中验证后统一实机验收。沿用全部边界，保留原Mac更新器，不重复Windows Smoke、不停止既有VM/跑实际到期调度/删资产/改宿主网络卷/提交推送/覆盖旧包/发布，不把43项/G0/G1写成完成。

第109节最终集中核验（2026-10-27）：完整入口1663项/1642通过/21条件跳过（260.022秒），无失败；运行期间追加取消与双端清理修正，最终external_ip模块专项29项通过（0.409秒）、原外部21项通过，最终独立白名单226文件/154个Python语法/15个固定CLI帮助通过，781项/773通过/8跳过（20.788秒；含帮助22.171秒）。**这是完整运行与修正后专项/独立副本的组合覆盖，不是同一最终源码的一次全量重跑。**最终运行源码与副本摘要一致；后续只更新状态/剩余说明及output证据，不把副本文档快照冒充最新文档重跑。专项包含材料副本实际再生成与两条自有Python进程JSONL管道，仍无真实SSH、Linux TUN/来宾或人工界面验收。

381份开始基线全部仍在（6份预期改动/375份相同），新增模块/测试/说明3份已收录白名单；原Mac更新器三文件与HEAD一致，226白名单文件存在且未被忽略，git diff --check通过。最后只读快照未发现本机QEMU/实际调度/独立GUI/显示/后台日志接收器/外部传输或固定管道夹具进程；完整/独立执行会话均结束。不推断远端Windows或SSH状态，未操作历史PID、用户VM或用户实例目录。摘要`output/external-ip-20261027/final-evidence.json`，完整full-regression.log、最终ip-tests-final.log/external-final.log、isolated-corrected-final.log、preservation-final.json/process-final.json及source-files-final.json保留；before-cancel/before-cleanup日志为阶段记录，不作为最终源码证据。未创建交付App/ZIP/安装器、提交/推送/覆盖旧包/发布；全部边界、43项/G0/G1/正常关机及集中实机验收未完成状态保持。

## 110. 遗留项整批开发：在线版本、独立管理、Windows Job与持续观测（2026-10-27）

用户要求“一次完成后续所有遗留问题”，期间再次要求继续。本批没有在完成单个小点后结束：核对AGENTS、109及整批第4节后连续推进默认启动故障、在线准备/暂停/恢复、独立管理、Windows限额/预算和只读持续监督，最后统一验证。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`未切换；384份开始文件摘要在`output/consolidated-20261027/baseline.json`，保留全部已有修改和未跟踪输入。开始本机只读快照无QEMU，不推断其他目录或远端状态。

[整批行为、入口与真实限制](ctflab-consolidated-2026-10-27.md)：

1. **默认启动故障已修复。**版本桥使用version-launch日志名，但旧接收器白名单遗漏；补白名单并实际用自有接收器/短命Python进程走默认派生路径，保存输出且收回。稳定管理判定也复核模块与解释器不在versions内，保留未知父进程拒绝。
2. **在线准备与恢复。**固定HTTPS INDEX/RELEASE材料双重验签、索引序号/期限/许可受众、文件SHA/预算、无跳转/压缩及有限元数据。预览不建缓存；确认下载绑定当前信任/库/来源/上限/计划，复用缓存Range、篡改隔离和引用。材料写新操作根，完成仍需单独暂存/切换/启动，不自动安装。新增原请求恢复（零网络）、独立暂停与显式续传；暂停先到阻止下载、缓存锁内可记录暂停、保留前缀。旧计划、旧续传摘要、预览期间迟到暂停、旧cancel_id重发及部分pending保守处理，不解除更新的暂停或自动清现场。
3. **独立管理入口。**ctflab_manage.py提供可读的固定CLI动作，修改要求先前target，源码本身不能位于受管versions内；复用原摘要/实验停机门。React版本页补签名预览/确认下载/暂停/原请求核对和保留记录恢复，迟到回复保持目标隔离，Mac新版本库仍只读。CLI不等于最终独立原生管理App/安装器已经交付。
4. **Windows可选Job声明。**绑定每节点CPU hard cap、Job提交内存和活进程数，新自有worker在QEMU/日志子进程前创建并加入新Job，读回后才继续；既有同名对象拒绝，不设置KILL_ON_JOB_CLOSE或BREAKAWAY。启动记录绑定声明，派生后/活动观测保留进程句柄复核归属与限制。失败不降为无约束运行，不修改既有VM。租约按声明上限计入预算；不是Windows远程执行已经可用。Mac/Linux拒绝实际使用该Win32限额，不冒充跨平台支持。
5. **持续只读观测。**显式ctflab_watch.py固定实例/代次/配置及根/ledger身份，范围变化即结束，未知只记unknown，只调用observe；保留意图/原子快照/最多2MiB变化日志/完成记录，日志满继续采样。history零网络；不安装服务/自动重启，不接管已丢失匿名管道，不发送启停/重置，不把进程采样当来宾或课程健康。

新增四个模块、四份测试和整批说明，运行时71文件、独立源码白名单同步；Mac运行时另收录watch及共享Job校验依赖，原更新器三文件未改。影响既有bounded_log/version_bridge/qemu_driver/remote_leases/content_cache、打包清单、React版本页/模型及相应测试，没有修改Swift/Rust或宿主配置。前端构建只更新开发dist，完整回归的App构建只使用自有临时合成材料；未重建交付App/ZIP/安装器或覆盖旧包。

验证在统一检查前持续完成，最后一轮运行源码固定；最终数字与保全/进程快照在本节末尾追加。专项Windows Job11、租约25、watch7、管理3、版本桥8、在线15、内容缓存12、原驱动34（33通过/1条件跳过）通过；前端44项及构建通过。Windows API/Job/压力全为替身与ABI/顺序核验，没有Win32内核运行；watch为临时实例/假时钟，未对用户实例启动；在线为真实签名/SQLite/文件及内存HTTP，不连接真实发行源；默认日志路径只运行自有Python，不启动实际App/VM。初次驱动专项命令从desktop目录重定向失败，未启动该项，已在正式目录正确重跑，不把未执行命令记通过。1698/813与1702/817为暂停/竞态修正前的阶段覆盖，保留before-pause与before-cancel-race日志，不冒充最终源码。

**一次完成全部遗留项的整体目标仍未达到，以下不能被测试总数替代：**

- 尚有实际开发：Windows原生三层端点、子网/多跳/自动DNS/PMTU及整域集成；Mac本地CPU/内存强制限制、Windows与卷外总磁盘策略；更广未知/半装载/资源丢失恢复、更多画布/观测交互；真实C01—C07课程/固定分析镜像与规则；稳定原生管理应用/最终安装更新与原生依赖闭包。
- 外部条件/实机：许可镜像、SSH、签名证书已知缺少，不重复索要。真实Windows Job/压力、Linux TUN/外部SSH/来宾隔离/服务/正常关机、APFS及磁盘写满、真实长期故障、最终安装签名/干净机/5人课堂及完整G0负向未验。新代码不把这些记为已投入使用。
- 边界继续：不重做Windows Smoke，不停止既有VM/运行实际到期调度/删除用户资产/改宿主网络或卷/提交推送/覆盖旧包/发布，原Mac运行链和更新器保留。43项/G0/G1/graceful_stop_verified与集中实机总验收保持开放，不概括成只等测试。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，读取AGENTS.md、状态第110节、整批开发说明与剩余说明第4节，核验Git/实例并保留全部改动；针对明确未关闭项继续，不重复已通过验证或把全部遗留写成已完成。沿用全部操作边界及原Mac更新器，不重做Windows Smoke、不自动停机/到期调度/删资产/改宿主网络卷/提交推送/覆盖旧包/发布。

第110节最终集中核验（2026-10-27）：最终运行源码固定后一次完整入口1705项/1684通过/21条件跳过（248.664秒），无失败；独立白名单235文件/162个Python语法/17个固定CLI帮助通过，820项/812通过/8跳过（21.841秒；含帮助23.335秒）。最终源码与副本一致，后续只更新文档/证据；1698/1702/1704及其副本日志是修正前阶段记录，不混入最终数字。最终前端44项及构建通过，原生IPC/真实窗口交互未验。Swift/Rust没有修改，不另跑其专项；完整入口中的临时App/原生GUI构建仅按该日志范围记录，不当成已发布App更新。

384份阶段开始基线全部仍在（17份预期改动/367份相同），新增四个模块、四份测试与整批说明9份已收录白名单；71文件运行时/235文件独立源码清单存在且未被忽略，原Mac更新器三文件与HEAD一致，git diff --check通过。最终完整/独立执行会话均结束；只读进程快照未发现本机QEMU/实际调度/独立GUI/显示/日志接收器/外部传输/持续watch或固定管道夹具，未操作既有用户VM或历史PID，不推断远端Windows/SSH状态。本轮没有对用户实例执行watch、真实Windows Job/SSH/到期调度或宿主网络/卷操作。

摘要`output/consolidated-20261027/final-evidence.json`，完整full-regression.log、独立isolated-corrected-final.log及source-files-final.json、前端frontend-final-tests.log/frontend-final-build.log、专项online-final.log/windows-limits-final.log/watch-final.log/manage-pause-final.log/version-pause-final.log/leases-final.log/cache-final.log/driver-final.log、preservation-final.json/process-final.json保留。未创建交付包/提交/推送/覆盖旧包/发布；实际发行沿既有记录，本轮没有查远端发布。整体遗留目标尚未全部完成，未关闭开发/外部条件按本节分列保留，43项/G0/G1/正常关机与集中实机验收仍开放。


## 111. 连续开发：Windows专用NTFS卷容量绑定与未准备实例配置恢复（2026-10-27）

本轮按用户要求读取AGENTS.md、状态第110节及剩余清单，正式目录仍为`/Users/pufei/Downloads/ctf-lab`。现场分支`codex/release-0.1.1-preview-20261010`，HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`；393份阶段开始文件摘要在`output/windows-volume-20261027/baseline.json`。全部既有修改和未跟踪输入保留，未拉取/清理/切换。开始只读进程快照未发现本机QEMU，不推断其他目录或远端状态；本轮未创建用户实例或操作已有VM。

新增[Windows卷与恢复说明](ctflab-windows-volume-2026-10-27.md)。可选windows_storage只允许已预配置本地固定非系统NTFS专用盘符、唯一别名及盘根直接instance目录；核验GUID、非重解析点目录身份、卷实际簇几何与容量并绑定摘要。独立零访问权限GUID卷设备句柄负责FSCTL，目录句柄负责路径身份；所有自有句柄finally关闭。不会用可能受用户配额限制的总量冒充整卷上限，不提权/配置卷或配额。准备/复制、驱动启动前与worker派生前、观察和租约预算复核；三类存储策略互斥，共享盘符拒绝。**原生Win32/ACL/FSCTL本轮全部为替身，真实普通用户兼容性、压力/写满和重启未验。**这是条件式实例文件系统容量边界，不是全项目/卷外总磁盘策略。

新增storage-bind独立CLI：只针对没有代次/未决磁盘操作/活动桌面请求的通用实例，preview生成绑定摘要，apply要求同摘要与显式操作UUID；保留原配置字节、部分文件、意图和完成收据。发布配置后缺收据可由同操作补齐，不重新替换配置；配置/根目录/账本/策略漂移拒绝。新prepare在写入操作意图前检查绑定闭合，防止恢复死锁；删除策略或整个配置不能退回无绑定运行。损坏意图或完成收据保留并要求复核，不擅自删除或猜修。status只读本地元数据，不探测卷。源码与guest-kit/两类运行时/独立副本白名单闭包同步，原Mac更新器保留。

专项使用临时文件/SQLite与Win32/卷观察替身；没有真实Windows API、SSH、来宾或宿主卷操作。初轮准备夹具遗漏store.begin、将DOS路径放入Mac策略的夹具错误已修正，没有放宽生产保护。最终复核另发现卷控制码入口应为卷设备句柄，已修正并加强替身断言；修正前完整日志before-device-full-regression.log单列，最终源码完整及独立验证结果在下文追加。Swift/React/Rust未改，不另跑其专项，完整入口中的临时GUI构建只按本次日志范围记录，不更新已发布App。

仍有实际开发：Windows原生三层端点、更多路由/DNS/PMTU与整域集成，Mac本地CPU/内存强制限制、卷外/公共缓存/审计总量策略，更广未知/OCI半装载/资源丢失恢复，更多画布和观测交互，真实C01—C07课程/固定分析镜像及规则，最终原生管理安装更新与原生依赖闭包。许可镜像/SSH/签名证书缺失已知，不重复索要；真实各平台限额/网络/隔离/服务/正常关机/长期故障、安装签名/干净机/课堂试点与完整G0负向尚未验证。全部遗留目标未完成，43项/G0/G1/graceful_stop_verified与集中实机验收继续开放。

沿用全部边界：不重做Windows Smoke、不自动停机/重启既有VM、运行实际到期调度、删除资产、改宿主网络/卷/ACL、提交推送、覆盖旧包或发布。没有创建交付App/安装包/ZIP；实际发行沿既有记录，本轮未查远端发布。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，读取AGENTS.md、状态第111节及剩余说明第4节，核验Git/实例并保留全部改动；继续未关闭开发并区分真实平台缺口，沿用全部边界和原Mac更新器，不重做Windows Smoke、不停机/到期调度/删资产/改宿主网络卷/提交推送/覆盖旧包/发布，不将43项/G0/G1写成完成。


第111节最终集中核验（2026-10-27）：设备句柄修正后的最终运行源码固定，一次完整入口1729项/1708通过/21条件跳过（247.139秒），无失败。独立白名单240文件/166个Python语法/19个固定CLI帮助通过，844项/836通过/8跳过（21.206秒）；最终运行源码与副本一致，后续只补文档和output证据。修正前完整1729项（253.770秒）单列before-device-full-regression.log，不冒充最终源码覆盖；最终Windows专项12、绑定恢复10、租约27、Linux存储13、代次18、guest-kit2、Mac存储16通过，驱动34项/33通过/1条件跳过。前端/Swift/Rust无修改不另跑专项，完整入口的临时GUI构建按日志范围记录。

393份开始基线全部仍在（12份预期改动/381份相同），新增两模块/两测试/说明5份已收录白名单；73文件桌面运行时、240文件独立源码闭包完整，白名单未被忽略，原Mac更新器三文件与HEAD一致，git diff --check通过。完整与独立执行会话均结束；最后只读本机快照未发现QEMU/实际调度/独立GUI/显示/日志接收器/持续watch或外部传输进程，不推断远端或任意其他目录状态。没有操作用户VM或历史PID，没有宿主网络/卷/ACL写入，没有新交付包/提交/推送/覆盖旧包/发布。

最终摘要`output/windows-volume-20261027/final-evidence.json`；完整full-regression.log、独立isolated-corrected-final.log/isolated-corrected-evidence.json/source-files-final.json、专项windows-device-final.log/bind-final.log/leases-final.log/storage-regression.log/generation-regression.log/guest-kit.log/driver-final.log/mac-storage-final.log及preservation-final.json/process-final.json保留。早期windows-first.log、bind-first/second/third.log及before-device完整日志单列；原生Windows卷/限额压力及所有已列实机门仍未通过，实际未关闭开发按本节与剩余第4节保留，全部遗留工作尚未完成。


## 112. 连续开发：OCI未开始装载续建与双端拓扑布局（2026-10-28）

按本次要求读取AGENTS.md、状态第111节与剩余清单，现场正式目录仍为`/Users/pufei/Downloads/ctf-lab`，分支`codex/release-0.1.1-preview-20261010`，HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`。Git开始228项已有修改/未跟踪输入，398份文件摘要记录在`output/continuation-20261028/baseline.json`，全部保留，没有拉取/清理/切换。开始本机只读快照未发现QEMU，不推断远端或任意其他路径的实例。没有创建/操作用户VM。

[本轮说明](ctflab-continuation-2026-10-28.md)记录三个接入点：来宾OCI未开始装载的续建、React布局画布、Mac原生共享布局。原inspect/resume-preparation基于当前快照显式恢复：未知转换保留、新目录重做本地有界转换，仅未登记load意图才首次装载；已有load未知绝不重发。再次中断需重新读快照，原归档变化/旧摘要/恢复目录上限拒绝。新意图与原未知记录并存；不启动服务/容器，不删除或猜修丢失卷。真实临时OCI转换/SQLite及假Docker专项22项、来宾代理31项通过，尚未操作真实Docker/来宾。

双端画布支持节点/网段标题拖动、微调、自动排列和共享schema1布局文件；React方向键及Shift加速、Mac标题方向菜单，坐标和64KiB输入有界。布局只改变编辑页显示/独立旁车，不进入执行manifest、网卡/依赖/资产/运行代次。导入精确绑定草稿及元素，失败保留；Mac不覆盖已有导出文件。实际Node→Swift→Node往返逐值相同并拒绝异草稿。React浏览器合成草稿检查了方向键位移、连线跟随、旁车导出/导入及错误导入保全，下载在夹具拦截；不是原生Tauri IPC/物理指针捕获。检查后仅微调提示文案与资源控件样式，最终构建及完整入口覆盖另列。Mac真实窗口/辅助功能/指针、高DPI及复杂展开布局尚未验，声明锚点不冒充运行网络。

Swift核心290项通过；首次新增State触发本机工具链缺SwiftUIMacros插件，改沿项目已有StateObject模式后类型检查通过，原失败日志保留，没有安装依赖或改变发布要求。首次布局模型写入因工作目录相对路径错误未落地，修正后新增测试47项通过，不将初轮44项算作新增覆盖。开发服务仅绑定127.0.0.1:1427用于自有夹具，经过当前命令及cwd核验后SIGTERM收回自己的服务，非操作用户虚拟机/旧PID；两次会话绑定记录与关闭结果保留。源码集中检查启动后只改文档和output证据。

**所有遗留工作尚未全部完成**：Windows原生三层端点、子网/多跳/DNS/PMTU及整域集成；Mac CPU/内存强制限制、卷外/缓存/审计总量策略；更广未知/资源丢失/半装载及长期故障、匿名管道接管；真实C01—C07课程/固定分析镜像及规则；最终原生管理安装更新/依赖闭包。许可镜像/SSH/签名证书缺失已知，不重复索要；真实多平台限额压力/网络隔离/正常关机/安装签名/干净机/课堂试点及完整G0负向仍未验，不能由本轮源码和单元数替代。43项/G0/G1/graceful_stop_verified与集中实机总验收保持开放。

边界全部沿用：不重做Windows Smoke、不停机/重启既有VM、不跑实际到期调度、不删除资产或改宿主网络/卷/ACL、不提交推送/覆盖旧包/发布，原Mac更新器保留。只构建前端开发产物和完整入口自有临时App夹具，没有更新已发布App或创建交付包；实际发行沿既有记录，本轮未查远端发布。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，读取AGENTS.md、状态第112节及剩余说明第4节，核验Git/实例并保留全部改动；继续未关闭开发，沿用全部边界和原Mac更新器，不重做Windows Smoke、不停机/到期调度/删资产/改宿主网络卷/提交推送/覆盖旧包/发布，不将43项/G0/G1写成完成。


第112节最终集中核验（2026-10-28）：最终运行源码固定后一次完整入口1734项/1713通过/21条件跳过（255.968秒），无失败；独立白名单241文件/166个Python语法/19个固定CLI帮助通过，849项/841通过/8跳过（22.533秒，含帮助24.223秒），最终运行源码与副本一致，后续只改文档/output证据。React最终47项与构建通过，Swift核心290项通过，完整入口包含最终GUI源码的临时App构建；类型检查日志及Node→Swift→Node布局逐值一致证据单列，不把这些当成原生窗口/指针/Tauri IPC验收。OCI22、来宾代理31项专项通过，真实Docker/来宾未验。

398份开始基线全部仍在（13份预期改动/385份相同），仅新增本轮说明1份，已列入白名单；73文件运行时/241文件独立源码清单存在且未被忽略，原Mac更新器三文件与HEAD一致，git diff --check通过。完整和独立执行会话已结束；最后只读本机快照未发现QEMU/实际调度/独立GUI/显示/日志接收器/watch/外部传输或固定管道夹具，自己的两次Vite回环服务经当前命令/cwd绑定核验后收回，不操作用户实例或其他旧PID，不推断远端Windows/SSH状态。

最终摘要`output/continuation-20261028/final-evidence.json`；完整full-regression.log、独立isolated-corrected-final.log/isolated-corrected-evidence.json/source-files-final.json、oci-final.log/guest-agent-final.log、frontend-model-final.log/frontend-build-final.log、swift-core-final.log/swift-ui-typecheck-final.log、cross-language-evidence.json/browser-final-evidence.json及preservation-final.json/process-final.json保留。swift-ui-typecheck.log是State宏插件失败记录，frontend-initial.log是新增布局代码落地前44项记录，不混入最终数字。浏览器证据的核心交互后只改提示文案/资源控件样式，最终构建/完整入口覆盖这些增量，浏览器证据不冒称逐字相同源码的原生交互验收。没有交付包/提交/推送/覆盖旧包/发布；全部操作边界及上述未关闭开发/外部条件保持，不能将所有遗留或43项/G0/G1写成完成。


## 113. 连续开发：来宾准备恢复桌面接入与Windows静态依赖核对（2026-10-28）

按用户“一次性推进所有未完成开发/继续”要求承接第112节，重新核对正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`及HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`，开始229项已有修改/未跟踪输入，399份文件摘要记录在`output/recovery-integration-20261028/baseline.json`，全部保留，无拉取/清理/切换。开始本机只读快照未发现QEMU，不推断其他目录或远端实例状态。本轮无用户VM或真实Docker/SSH操作。

[本批实现说明](ctflab-recovery-dependencies-2026-10-28.md)覆盖两条实际缺口。其一：原来宾内OCI/资源准备核对和续建接通GuestClient认证消息、QEMU驱动、桌面契约/协调器、React及SwiftUI。握手显式恢复能力；旧代理拒绝新动作，不重发prepare/load或降为shell。传输操作与原target操作分开，严格绑定当前实例/代次/策略、原操作及当前快照摘要；宿主保留意图/回复，同ID不得换目标/摘要。丢回复保持unknown，通过新只读核对确认原操作，不自动重放。

新入口沿原CAS/工作/代次门和现场身份观测，先恢复核验整课进程再允许核对/续建。桌面有界列出本次启动中原准备结果未确认记录，不把历史unknown当成来宾当前pending。只有当前节点/原操作的有效快照可续建，明确确认后可能创建缺少容器但保持停止，取消不派发。后续仍沿第112节恢复规则，不删丢失资源或猜修进度、不启动服务/容器。超大快照返回明确unknown，不返回截断前缀；来宾完整本地现场保留。没有扩展远程租约协议或自动接管原来宾生命周期。

其二：新增Windows x64 PE32+有界静态导入核对及安装材料可选复制前检查。普通/延迟导入和导出转发递归检查，限定显式入口及搜索目录，拒绝缺失、歧义/系统遮蔽、路径导入、非法RVA/重叠/截断、链接/漂移/数量超限；不执行二进制、加载DLL、查PATH/系统目录或下载。OS/API-set仅为未核验声明，动态LoadLibrary/SxS/插件发现/导出符号、全部PE合法性、签名/来源和实际原生闭包不由此证明，相关flag保持false。后续显式stage --inspect-imports失败时不创建材料目录，通过后把报告摘要绑定到新材料清单；默认旧stage兼容，旧交付包没有更新。本轮只运行临时合成PE/许可/目录测试，没有检查真实Windows运行时或调用旧包stage。

专项：集成10项、桌面桥接34项、通道7项、原契约4项、OCI22项、来宾代理31项、驱动34项（33通过/1跳过）、PE9项、临时材料8项；最终数字与完整入口下文追加。首次新增历史助手遗漏guard导入由用例发现，修正后通过；integration-history-import-failure.log保留。早期集成44项因导入测试类重复收集，改为模块引用后按最终10项计。Mac接入脚本一度因错误工作目录未落地，修正后才计编译/模型结果。Swift核心299项、最终类型检查通过；React48项/构建通过，Node与Swift续建参数逐值相等并拒绝错原操作。浏览器程序化事件/替身IPC检查核对前禁用、取消不派发、目标/摘要/CAS、旧快照禁用，只产生2条夹具submit；不是原生IPC/认证TLS/真实来宾或人工Mac窗口验收。

自己的回环浏览器服务仅监听127.0.0.1:1428，核验当前命令及cwd绑定后收回，夹具页已转空白，未操作其他进程。原Mac运行链及更新器、既有资产和旧包保留；不重做Windows Smoke、不停机/重启既有VM、不跑实际到期调度、不删资产/改宿主网络卷ACL、不提交推送/覆盖旧包/发布。完整入口的临时App/材料夹具不是新交付包，实际发行仍沿既有记录，本轮未查远端发布。

所有遗留目标仍未达到：Windows原生三层端点、子网/多跳/DNS/PMTU和整域集成，Mac CPU/内存强制限制、卷外/公共缓存/审计总量，更广未知/资源丢失恢复和长期故障/匿名管道，真实C01—C07课程/固定分析镜像/规则，最终原生管理安装更新/运行时实际闭包，以及真实多平台压力/隔离/正常关机/签名/干净机/课堂试点/完整G0负向仍有实际开发或验收。镜像/SSH/证书缺失已知，不重复索要；不能把CLI/静态检查器/替身测试写成全部完成或只剩用户验收。43项/G0/G1/graceful_stop_verified及集中实机总验收保持开放。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，读取AGENTS.md、状态第113节和剩余说明第4节，核验Git/实例并保留全部改动；继续未关闭开发，沿用全部边界及原Mac更新器，不重做Windows Smoke、不停机/到期调度/删资产/改宿主网络卷/提交推送/覆盖旧包/发布，不将43项/G0/G1写成完成。


第113节最终集中核验（2026-10-28）：最终运行源码固定后一次完整入口1756项/1735通过/21条件跳过（257.310秒），无失败；独立白名单246文件/169个Python语法/21个固定CLI帮助通过，871项/863通过/8跳过（22.604秒，含帮助24.305秒）。最终运行源码与副本一致，之后仅更新文档/output证据。React48项及最终构建、Swift核心299项/类型检查、Node→Swift续建参数逐值相同与错目标拒绝通过；完整入口也覆盖最终GUI源码的临时App构建。浏览器使用程序化事件及替身IPC，不作为Tauri/Mac窗口或真实来宾验收。PE9项与安装材料8项仅为纯字节及临时目录测试，不作为真实Windows加载/签名/依赖闭包。

399份开始基线全部仍在（20份预期修改/379份相同），新增GuestRecovery组件、恢复集成测试、PE模块/测试及本轮说明5份已列白名单；74文件桌面运行时/246文件独立源码闭包存在且未被忽略，原Mac更新器三文件与HEAD一致，git diff --check通过。完整和独立执行会话均结束；自己的1428回环服务在核验当前命令/cwd后收回且夹具页置空。最后只读本机快照未发现QEMU/实际调度/独立GUI/显示/日志接收器/watch/外部传输或固定管道夹具，不操作用户VM/其他历史PID，不推断远端状态。

最终摘要`output/recovery-integration-20261028/final-evidence.json`；完整full-regression.log，独立isolated-corrected-final.log/isolated-corrected-evidence.json/source-files-final.json，integration-final.log/bridge-final.log/channel-final.log/contract-final.log/oci-final.log/agent-final.log/driver-final.log，pe-initial.log（最终同一PE源码9项）/package-initial.log（最终同一材料实现8项），frontend-final.log/frontend-build-final.log、swift-core-final.log/swift-ui-initial.log（成功类型检查）、cross-language-evidence.json/browser-evidence.json及preservation-final.json/process-final.json保留。integration-initial.log的44项是重复收集阶段覆盖，历史助手缺guard失败日志单列，不混入最终10项。没有交付包/提交/推送/覆盖旧包/发布；全部禁止事项、实际未关闭开发与实机门保持，整体遗留目标尚未完成。


## 114. Mac预览发布：稳定性与架构拓扑（2026-10-28）

用户要求“先完成稳定和架构拓扑功能后发版”，并明确选择“先更新Mac预览版，Windows继续候选验证”。本轮新增授权仅用于该Mac预览的独立打包与发布；旧有不自动停机/重启既有VM、删除资产、改宿主网络/卷/ACL、实际到期调度、提交/推送及重做Windows Smoke边界继续保持。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`不变。开始233项修改/未跟踪输入、404份文件摘要记录在`output/stability-topology-20261028/baseline.json`；全部保留。

[本轮说明](ctflab-stability-topology-2026-10-28.md)记录具体实现。后端提供逐节点有时间戳的只读身份/进程采样，预算过期不发起更多查询，单次调用仍沿驱动期限；非同时快照，不证明来宾、服务或隔离。Mac/React本地概览最多60秒，缺失/未来/过期/不完整观测保留设计并显示未知、禁用新变更，恢复/取消沿原契约。30秒界面等待不杀后台或重放请求，迟到回复被本次票据隔离。React另防同实例重开时旧刷新/旧finally覆盖新轮次。远程React协议沿已有独立绑定，不要求本地新增新鲜度字段，不能以此声称远程协议也完成了该升级。

原请求查询改为真正只读：验证实例/操作者/原幂等键及指纹，原记录不存在时不创建实例/意图，不补派发标记、不启动执行器。Mac原生工作区显示设计拓扑和现场进程采样；未知地址仍空。原生草稿按网卡行/网络标题实际位置连线、按实测卡片高度排列；配置20步撤销/重做与64KiB上限、布局独立导出/导入，新编辑清空重做，后端差异校验后导出，不热改运行实例。

完整Mac运行时从原Python归档建立独立副本，保留Tcl/Tk，固定cryptography46.0.5及cffi2.1.1、typing_extensions4.16.0、pycparser3.12。官方PyPI元数据与wheel SHA一致，不运行安装脚本；原SSL内置模块误拒绝已修正为验证真实built-in或包内文件，外部/伪造模块仍拒绝。Tcl/Tk脚本9.0.4许可取自官方对应标签；原wheel/归档保留。仅在副本内裁cryptography为ARM64、将Tcl/Tk/扩展引用改为包内loader_path、移除rpath并重签，所有前后摘要保留。Mac显式打包白名单另补22份延迟导入模块，加入“覆盖74份共享运行模块”回归，避免只验证窗口设计路径。原Mac更新器三文件与HEAD相同。

最终验证：完整入口`python3 -B -m unittest discover -s tools/tests -v`共1765项，1744通过/21条件跳过（270.180秒）；独立白名单249文件/171个Python语法、904项（896通过/8跳过）及21个源码固定帮助入口通过。React53项及构建通过；Swift核心310项通过，完整入口重新编译最终GUI。实际最终App导入74份共享模块、20个包内固定帮助入口通过；主CLI使用公共启动器，不把直接-I运行ctflab.py脚本当公共入口。实际App、独立解压副本和整树摘要/严格签名/许可证闭包通过；最终1265个登记文件、QEMU11.1.0、Python3.12.15、PyYAML6.0.3、70动态库/50运行资源，ad-hoc、未公证。

原生窗口在自有状态根`output/stability-topology-20261028/native-fixture/state`、实例`3139f1b6-4da5-4424-9103-79d3bc9995d0`核验：三节点/双网显示、CPU1→2、撤销→1/重做→2、菜单移动后连线仍连接网卡、后端精确1项差异、真实草稿导出，过期后未知及准备/显示/观测恢复禁用。最终补模块包再复核拓扑/编辑/差异/撤销。原清单/实例CPU仍1，导出CPU2，代次0且generations为空，未启动VM。没有物理拖动、真实来宾/服务/网络/压力/原生挂起注入验收。初次退出后的工具观察自动重开App到默认根，仅只读观察后关闭，未操作默认实例；最终退出不用该方式重读窗口，另核进程。

发布前失败全部保留：新增测试夹具参数、新鲜度夹具兼容、独立副本漏测试依赖、旧版本测试写死、缺Tcl/Tk许可、SSL内置误拒绝、旧显示组件与当前库同名冲突、通用Rust安装标识与Tcl/Tk rpath、首包漏延迟模块。编译期间我改了GUI源码导致一次编译失败，随后冻结源码重建；无失败候选作为最终包。直接-I测试主脚本失败后改用真正公共启动器，保留该错误入口日志。早期1764项通过及904项结果不是后续新增防遗漏检查的完整入口结果，以上1765项为最终口径。

**已发布Mac预览**：[v0.1.3-preview.20261028](https://github.com/zhangpu1211/ctf-lab/releases/tag/v0.1.3-preview.20261028)，GitHub release id426804854，prerelease=true/draft=false。四项资产（MacZIP、源码快照ZIP及各自SHA256）上传后GitHub摘要与本地一致，回下载核验另见下文。最新旧发行现场实际为0.1.2-preview.20261015，已纠正此前顶部0.1.1过时记录；旧App整树摘要未变化。新本地App：`/Users/pufei/Downloads/CTFLab-Library/03-软件/CTFLab-0.1.3-preview.20261028/CTFLab.app`。最终构建`output/stability-topology-20261028/mac-preview-0.1.3-final`，可交付资产`output/stability-topology-20261028/release-assets`；第一份不完整包保留在mac-preview-0.1.3及镜像库带build1-incomplete后缀目录，不是交付入口。

源码没有自动提交或git push；发布通过API创建新版本标签，标签指向上述既有基准HEAD。GitHub自动Source code仅代表基准，**对应当前App的是单独source-snapshot.zip**及其中253份文件SHA和RELEASE-INFO.json。打包后只补工作区状态/说明，代码与包的对应关系单独核验，不能把文档后续补录冒称已重新打包。

稳定版外接屏/Mac睡眠/长时闲置与负载/干净机门保留；Windows原生三层端点、多跳/DNS/PMTU/整域、安装/签名/实际依赖闭包，以及Mac CPU/RSS硬限额、卷外总量、全部真实课程/正常停机/隔离/故障/课堂试点和完整G0/G1仍开放。镜像/SSH/证书缺失已知，不重复索要；不能将Mac预览发行写成43项或全部遗留开发完成。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读取AGENTS.md、状态第114节和剩余清单，核验Git/实例并保留全部改动；Mac已发布v0.1.3-preview.20261028，Windows继续候选验证。下一阶段继续实际未关闭开发，不重做Windows Smoke，不自动停机/删资产/改宿主网络卷/提交推送或再次发布，不将43项/G0/G1写成完成。

第114节最终发行核验：GitHub于2026-10-28T14:57:19Z（北京时间22:57:19）发布新预览。四项资产已实际回下载，大小和SHA-256逐项与本地/服务端一致。MacZIP61,724,809字节，SHA256`081262c77a06c08bbee64141a2da56d3cba85cf860bbd2616bbe27961ee85eca`；源码ZIP1,174,363字节，SHA256`3a157d79bfcc9b80e037e5f5abfd083dc4bcfed7716017cc335543c37baf7cb0`。镜像库新目录已另存四项资产，不覆盖任何旧文件。253份源码快照内217份tools/gui/desktop运行及测试源与当前工作区逐字一致，后续只补文档。

404份开始文件全部保留，无缺失；最终22份预期修改/382份相同。旧0.1.2 App整树摘要仍`56bd85ccd41762ed8f5ac8f5cea39c5d310ab3bee66d33da4191e88ddd3d3f9f`；原Mac更新器三文件与HEAD一致；HEAD/分支未变，没有提交或git push。最后本机快照无QEMU/CTFLabGUI相关进程，独立实例仍代次0、无generation；没有停机、删除资产、宿主网络/卷/ACL改变或到期调度。不推断远端Windows/SSH现场。

最终摘要`output/stability-topology-20261028/final-evidence.json`。证据：full-regression-complete.log、isolated-corrected-final.log/isolated-corrected-evidence.json/source-files-final.json、frontend-final.log/frontend-build-final.log、swift-core-final.log、app-build-complete.log、final-runtime-final.log/final-runtime-evidence.json、native-ui-evidence.json、package-evidence.json/archive-roundtrip-evidence.json、published-release.json/download-verified.json、preservation-final.json。更早失败日志及不完整候选全部保留；测试计数、源码/窗口、真实来宾和稳定版门各按上述范围解释。

## 115. 继续源码开发：概览跨代次竞态与观测绑定（2026-10-29）

承接第114节及用户“继续”，正式目录仍为`/Users/pufei/Downloads/ctf-lab`，分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`不变。开始236项修改/未跟踪输入、406份文件摘要存于`output/coherent-overview-20261029/baseline.json`；保留全部输入。沿用不自动停机/重启既有VM、删除资产、改宿主网络/卷/ACL、实际到期调度、提交推送或再次发布边界，不重做Windows Smoke。本轮无桌面控制、真实VM/Docker/SSH或发布操作；本机只读进程快照无QEMU/CTFLabGUI，不推断远端状态。

[本轮说明](ctflab-coherent-observation-2026-10-29.md)记录修复的实际竞态：原概览的操作状态、活动代次、逐节点及附加记录分次读取，后台期间开始操作或完成代次切换可能混合不同现场。现采样前记录代次账本与操作状态，读完退出监督/证书/来宾历史后再次只读核对；任一变化使freshness.complete/coherent为false、reason为changed-during-sampling。保留设计，将所有进程/拓扑覆盖和附加记录降级未知，撤回本轮准备/派发建议。不跨驱动I/O持数据库锁、不自动重采样/派发/重放；每次真实操作仍须后台身份/CAS/代次核验，非所有节点同时原子快照。

桥接边界另逐项核对观测本身的实例、严格整数代次、节点、verified及stopped/process-running状态和本次采样期间有时区时间戳。拒绝错实例/代次/节点、布尔代次、未来/非法时间、非字典及无效状态，不再把外部结果重新盖成本次身份。诊断分享也不保留混合代次状态，来宾IP与隔离仍不推断。React/Swift对明确coherent=false的窗口拒绝，即使complete误为true；旧窗口没有新字段时沿原规则兼容，界面提示采样期间变化而非继续显示运行。

12项专项覆盖新操作、代次指针变化、附加记录读取末尾变化、诊断降级及错误观测。另用真实临时SQLite/合成磁盘/假驱动验证ABA：采样期间启动再停止，状态仍stopped、代次仍1、代次快照相同，但操作revision6→10；本次采样1次即失效、全部观测unknown，没有重试或真实VM操作。React53项/构建、Swift核心311项通过；完整及独立回归最终结果下文补录。以上不是物理故障/来宾/网络/课堂或原生窗口挂起注入验收。

本轮仅源文件与前端开发构建、测试临时App夹具；没有新交付App/安装包/源码ZIP，不修改0.1.3已发布App或原Mac更新器。实际发行沿第114节v0.1.3-preview.20261028，本轮未重新查询远端；该包不含本轮增量。Windows继续候选验证。其余43项/G0/G1、Windows原生三层/整域/安装签名、Mac硬限额/卷外总量、真实课程/网络/正常停机/长期故障与稳定版外屏/睡眠/负载/干净机门保持开放，不能将本轮修复记成全部开发完成。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，读取AGENTS.md、状态第115节及剩余清单，核验现场并保留全部改动；已发布Mac0.1.3预览不含本轮概览一致性增量，继续实际未关闭开发，Windows保持候选。沿用不重做Smoke、不停机/删资产/改宿主网络卷/到期调度/提交推送或再次发布边界，不将43项/G0/G1写成完成。

第115节最终集中验证：最终完整入口1770项，1749通过/21条件跳过（246.925秒）；独立白名单250文件/171个Python语法、909项（901通过/8跳过，23.497秒；含CLI帮助25.203秒）及21个固定帮助入口通过。React53项/构建、Swift核心311项、实际同一桥接夹具JSON送入Swift/React的交叉核验通过：原不一致结果及误设complete=true均拒绝，合成coherent=true控制样本接受。完整入口重新编译最终GUI；没有原生窗口、真实VM/网络或物理故障验收。

首次完整1770项有1项文档检查失败：上一轮表格写成macOS26而非macOS 26，修正文档后7项专项及上述最终完整入口全部通过；原full-regression.log保留，不能将其标成通过。源代码从最终测试开始保持不变，之后只补状态/证据。独立副本215份非docs文件与当前源码逐字一致，后续文档补录没有重打包。

406份开始基线全部保留，无缺失；最终12份预期修改/394份相同，新增本轮说明1份已列白名单。原Mac更新器三文件与HEAD一致；本地已发布Mac0.1.3 App整树摘要与第114节相同。最后相关进程快照无QEMU/CTFLabGUI；没有操作用户VM、删除资产、改宿主网络卷/ACL、实际到期调度、提交/git push/重新打包或再次发布。

最终摘要`output/coherent-overview-20261029/final-evidence.json`。证据：stability-final.log、bridge-initial.log（本轮同一桥接实现34项）、full-regression-final.log、docs-corrected.log、isolated-corrected-final.log/isolated-corrected-evidence.json/source-files-final.json、frontend-final.log/frontend-build-final.log、swift-core-final.log、aba-check.log/aba-evidence.json/aba-overview.json、cross-language-evidence.json及preservation-final.json。ABA和交叉语言仅为真实临时账本/假驱动/模型核验，不作为真实启动停止或原生UI验收；旧失败与现场保留。


## 116. 连续源码开发：缓存总预算、持续监督与IPv4差错回程（2026-10-29）

按用户“读取第115节及剩余清单、沿原边界一次性推进”要求，已读AGENTS.md、第115节及剩余第4节/后续增量，核对正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`。407份开始文件摘要见`output/continuation-20261029/baseline.json`；全部既有修改和未跟踪输入保留，无拉取/清理/切换。本机开始只读快照无QEMU/CTFLabGUI，不推断远端Windows或其他目录状态。

[本轮说明](ctflab-cache-watch-ip-2026-10-29.md)记录整批增量：P03/R02公共缓存四类载荷与全部上传预约的共享预算，显式预览摘要登记、本地下载联网前准入、跨用户预约/尾部与孤立文件计费及只读引用报告；A03/T01持续监督核对账本/契约SQLite提交与连接身份，ABA或活动操作降级unknown、结束撤回采样，并在React/Swift通用概览展示明确的历史区；E01/R04双端显式授权的ICMP差错回程，引用已见TCP/UDP、过期/容量边界和受限MTU字段核验，保持原SSH/包限额/未知不重发。

预算是受管载荷准入，不是文件系统硬配额，SQLite/审计/日志/其他根和外部写入未覆盖；监督不重接匿名管道或自动重启服务；差错转送不是完整PMTU/子网/多跳或Windows内核端点。原Mac更新器与已发布App保持，所有真实VM/Docker/SSH/网络/卷/ACL/到期调度/Smoke/删除/提交推送/再次发布边界不变。本轮只改源码、文档及前端开发构建/测试临时夹具，没有交付App/ZIP/安装器。

实际未关闭开发继续包括Windows原生三层/整域/安装链，Mac CPU/内存强限额、全公共存储总量，更广未知/资源丢失/匿名管道恢复、真实C01—C07/固定分析镜像与规则、最终原生依赖/签名/管理安装等。真实平台故障/网络/隔离/正常停机/压力/长期/窗口交互、完整G0负向、干净机/5人试点仍未验；镜像/SSH/证书缺失已知，不重复索要，不将所有剩余工作概括为只等验收。Mac实际发行沿第114节v0.1.3-preview.20261028，本轮未重新查询远端；发布包不含115—116节源码。Windows继续候选；43项/G0/G1/graceful_stop_verified与集中实机总验收保持开放。

本轮最终验证与保全在本节末补录，以最终日志为准；前期专项不冒充完整重跑。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第116节及剩余清单第4节，核验Git/实例并保留全部改动；承接缓存预算、持续监督历史/一致性与IPv4差错增量，继续实际未关闭开发。Mac已发布0.1.3预览不含115—116节源码，Windows保持候选。不重做Smoke，不自动停机/删资产/改宿主网络卷/到期调度/提交推送或发布，不将43项/G0/G1写成完成。

第116节集中结果：完整入口1795项，1774通过/21条件跳过（253.230秒）；该完整进程在最终ICMP引用缓存淘汰调整前已导入模块，不能称全部1795项都重新执行了最后这处修正。最终网络代码另外通过IPv4专项37项、外部接入21项，以及最终白名单独立副本934项（926通过/8跳过，22.226秒）。前端53项/构建通过，Swift类型检查及完整入口内的核心测试/真实GUI编译通过；未做原生窗口或真实来宾/网络验收。初轮完整1794项（1773通过/21跳过）属于阶段记录，保留，不替代上述范围。

最终独立副本251文件、171个Python语法、74运行时模块和22个帮助入口通过；215份非docs文件与当前源码逐字一致。首次独立934项测试已通过，但验证脚本错误地对旧ctflab.py加-I造成1个帮助入口失败；旧包装器实际按普通脚本运行，按原入口修正后通过，随后最终副本重跑934项及全部22帮助通过。新缓存CLI的-I帮助和实际只读storage调用均通过。原错误日志及首轮证据保留，不把失败阶段标成全部通过。后续仅补本节文档/摘要，没有重打包。

407份开始基线全部保留：16份本轮预期修改、391份相同，无缺失；新增说明1份已纳入.gitignore与集成白名单。原Mac更新器三文件与HEAD一致，本地已发布0.1.3 App整树摘要与第114节相同，git diff --check通过。完整及独立测试执行会话均已结束；最后按本机进程名未见QEMU/CTFLabGUI，不推断其他Python服务或远端状态。没有新建/操作用户实例、桌面控制、真实调度、宿主网络卷变更、删除资产、提交/git push/交付打包或再次发布。

最终摘要`output/continuation-20261029/final-evidence.json`；完整full-regression-final.log、最终网络ip-final.log/external-final.log、独立isolated-current.log/isolated-current-evidence.json/source-files-current.json、frontend-last.log/frontend-build-last.log、swift-ui-initial.log（成功类型检查）、cache-final.log/uploads-final.log/watch-last.log/overview-final.log/bridge-initial.log及preservation-final.json/process-final.json保留。isolated-final.log虽有934项通过，其同阶段帮助有1项验证入口失败；最终依据isolated-current系列。实现、单元/合成集成、原生编译与真实用户验收按上述范围分开，全部遗留开发及实机门尚未完成。


## 117. 连续开发：新启动的可重接日志通道与两端恢复（2026-10-29）

按本次接续要求读取AGENTS.md、第116节及剩余清单，核对正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`不变。开始238项已有修改/未跟踪输入、408份文件摘要记录在`output/recoverable-logs-20261029/baseline.json`；所有输入保留，无拉取/覆盖/清理/切换。开始按本机进程名未见QEMU/CTFLabGUI，不推断远端或其他Python服务状态。

[本轮说明](ctflab-recoverable-log-2026-10-29.md)记录A03/W04/W05新增实现：Darwin/Linux新通用实例可明确选择recoverable_logs=true；新QEMU stderr用实例/代次/节点/启动摘要/FIFO inode绑定的私有读写FD，独立接收器持内核排他锁；接收器退出后有限队列产生背压，用户明确重接后继续排空。原匿名通道与Windows默认链保留，旧启动没有登记FIFO时拒绝，不能凭PID接管旧管道或恢复宿主重启前的队列。

所有片段合计8MiB、最多16次会话（含首次）；新目录/原操作幂等不重发，零剩余预算只排空；旧片段/部分材料不覆盖、截断或删除。ready核对自有Popen及原生创建身份；未确认接收器时不启动生产者。丢回执保留未知。崩溃时已读未写字节可能丢失，capture_complete=false，EOF不是退出/正常关机证明。

驱动、CLI、桌面CAS及Mac固定根白名单接入rearm-log，React/SwiftUI增加只读锁/缺口提示和显式恢复按钮。日志背压可能阻塞QMP，故该恢复仅依赖重新核验的原生源进程身份、已登记通道、原代次及状态revision；仅日志入口可使用一致但逐节点不完整的有效窗口，不放宽生命周期/来宾按钮。错实例/代次/revision/节点、活动操作、陈旧/不一致窗口、旧匿名管道或未知身份均拒绝；不发送QMP、不重启/停止VM、不自动重试。

本轮真实内核验证仅为临时根、自有Python生产者和接收器：启动父进程自愿退出后接收完成；接收器退出后9MiB生产者等待、明确重接后继续并保留旧片段、合计8MiB；另外验证零预算、会话上限、文件身份/跨scope、worker传FD与未就绪拒绝、CAS/固定根与QMP不可达路径。假QEMU/契约测试不启动真实来宾。没有用户VM/桌面控制/真实SSH/Docker/网络/卷/ACL/到期调度/Smoke/删除/提交推送或发布操作。Mac0.1.3已发布App与原更新器不改，本轮只是源码及开发前端构建/测试夹具。

本轮没有关闭全部遗留：Windows/旧匿名管道、持锁挂起与更广未知/资源丢失/长期监督，Mac CPU/内存硬限额、全部公共审计/日志与卷外总量，Windows原生三层/多跳/DNS/完整PMTU/整域，真实C01—C07和分析镜像/规则、最终原生安装管理/签名/闭包等继续开放；原生压力/网络隔离/正常停机/长期故障/睡眠外屏/人工窗口、完整G0负向、干净机/5人试点未验。已知镜像/SSH/证书缺失不重复索要，不能把实际未开发归为只等验收。43项/G0/G1/graceful_stop_verified及集中实机总验收保持开放。实际发行沿第114节Mac0.1.3-preview.20261028，Windows候选；本轮未重新查询远端，没有交付包或发布。

最终集中验证、保全和失败/跳过范围在本节末补录，以最终日志为准。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读取AGENTS.md、状态第117节和剩余清单，核验现场并保留全部改动；承接新POSIX启动可重接日志及两端恢复，继续全部实际未关闭开发。Mac0.1.3发布包不含115—117节源码，Windows保持候选；不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/提交推送或发布，不将43项/G0/G1写成完成。

第117节最终集中结果：最终完整入口1811项，1790通过/21条件跳过（261.803秒）；最终白名单独立副本950项，942通过/8跳过（26.318秒），254文件/173个Python语法/75运行时模块/24帮助入口通过。217份非docs文件与最终源码逐字一致，最后完整入口启动后没有再改代码。React54项/构建、Swift类型检查和完整入口内核心测试/真实GUI编译通过。前期1810项完整、949项独立及6/9/11项日志专项属于阶段记录；新增就绪文件半写入反例后，以最终1811/950/日志12项为准，没有把前期通过冒充最终重跑。

最终日志通道专项12项、驱动36项（35通过/1条件跳过）、桌面桥接35项、Mac固定根26项、有界旧日志7项、cgroup10项、Windows Job限制11项通过（后两者是原有替身路径回归，不是原生压力验收）。新增真实内核路径仅为本机Darwin自有Python生产者/接收器/私有FIFO与文件锁；没有QEMU来宾或真实网络/宿主故障/原生Windows/Linux/课堂验收。日志可能丢失已读未写字节，不能以重接或EOF记作完整日志、进程退出或正常停机。

408份开始文件全部保留：19份本轮预期修改、389份相同，无缺失；新增模块/测试/说明3份已纳入白名单。原Mac更新器三文件与HEAD一致，本地已发布Mac0.1.3 App整树摘要与第114节相同；git diff --check与白名单核对通过。完整/独立和专项执行会话已结束，最后本机未见QEMU/CTFLabGUI进程名或项目日志接收器进程；其他Python服务与远端状态未推断。测试只收回自有Popen，不使用磁盘/历史PID控制进程；父进程退出用例中的短命自有生产者/接收器正常结束。没有创建/操作用户实例、停机、删资产、桌面控制、宿主网络卷/ACL变更、真实到期调度、原生Smoke、提交推送、交付打包或发布。

最终摘要`output/recoverable-logs-20261029/final-evidence.json`，证据包括full-regression-complete.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json、channel-final.log、driver-second.log、bridge-second.log、mac-initial.log、bounded-final.log/cgroup-final.log/windows-limits-final.log、frontend-second.log/frontend-build-second.log、swift-typecheck.log（成功）、preservation-final.json/process-final.json。早期full-regression-final.log、isolated-current系列及channel-initial/second/third.log保留，不混淆计数和源码范围。后续只补文档/证据，没有重新打包；所有剩余开发及实机门按本节和剩余第4节继续保留，整体尚未完成。


## 118. 连续开发：Windows专用来宾IPv4原生端点与接口规则（2026-10-29）

承接第117节与全部未关闭开发目标，已读取AGENTS.md、状态及剩余第4节，核对正式目录、分支与HEAD保持：`/Users/pufei/Downloads/ctf-lab`、`codex/release-0.1.1-preview-20261010`、`0994f620516c49d84badc3a606c1cd5ae4b483d0`。411份开始文件摘要见`output/windows-ip-20261029/baseline.json`，全部既有修改保留，无拉取/切换/清理。开始本机进程名未见QEMU/CTFLabGUI，不推断远端状态。

[本轮说明](ctflab-windows-ip-2026-10-29.md)记录E01/R04新Windows x64 Wintun/IP Helper端点、固定COM接口级Windows Firewall规则、受保护管理员来宾配置/标记与源材料生成。只在专用来宾模式中允许提升令牌，普通Windows运行器读取边界不变；机器/节点/策略/代次/运行时/DLL绑定，默认不初始化缺失驱动。新会话只创建新UUID接口、精确/32路由，拒绝冲突；关闭只尝试自有资源，未知不重放。原SSH认证、双端状态包门与限额保留，不改运行器宿主网络；不宣称其他现有网卡/防火墙规则已隔离。

全部验证使用Mac内存Win32/COM/Wintun替身、临时目录与自有命令子进程。没有加载第三方DLL、安装驱动、创建真实网卡、改ACL/防火墙/宿主网络卷、部署SSH、操作VM、运行到期调度、重做Windows Smoke、停机、删资产、提交推送、打包或发布。原更新器/旧包保持，已发布Mac仍沿第114节0.1.3-preview.20261028，包不含115—118节源码，Windows候选。

首次36项有1个测试误判异常类型的错误，实际模拟令牌路径已拒绝；修正断言并加入实际隔离CLI材料生成后37项通过。完整及独立集中结果在下文补录，早期失败日志保留。原生Windows SDK调用/管理员SSH/驱动/路由/防火墙/真实流量与清理尚未验，不能关闭完整Windows三层/AD课程；多跳/DNS/完整PMTU、Mac强限额/公共存储总量、更广恢复、真实课程/分析镜像、最终安装签名闭包及第4节其余开发/实机门保持开放。43项/G0/G1/graceful_stop_verified及全部开发总目标未完成，不把未开发归成只等验收。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，读取AGENTS.md、状态第118节及剩余第4节，核验现场并保留改动；承接Windows专用来宾IPv4端点源码，继续全部未关闭开发。Mac0.1.3发布包不含115—118节源码，Windows保持候选；不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/提交推送或发布，不将43项/G0/G1写成完成。


第118节最终集中结果：最终完整入口1848项，1827通过/21条件跳过（262.050秒）；最终白名单独立副本987项，979通过/8跳过（26.046秒），258文件/176个Python语法/77运行时模块/24固定帮助入口通过（含帮助共28.298秒）。220份非docs文件与最终源码逐字一致，完整入口开始后没有修改代码。完整入口中的Swift核心和实际GUI编译通过；本轮未修改React/SwiftUI，没有重新运行前端专项，不把第117节React54项当成本轮重跑。

Windows端点最终专项37项、原外部代理21项、原IPv4通道37项通过；普通Windows安全11项中8通过/3条件跳过。只执行Mac内存原生API替身、临时SQLite/文件及实际隔离材料CLI；没有原生Windows API、Wintun驱动/适配器/Firewall/SSH/真实流量或原生窗口验收。kit-final.log是误用不存在文件模式得到的0项发现，明确不作为专项通过证据；材料CLI37项、最终独立副本与完整入口才是实际验证依据。windows-final.log中的错误断言失败保留，修正后以windows-corrected.log为准。

411份开始文件全部保留：7份本轮预期修改、404份相同，无缺失；新增两模块/一测试/一说明4份已列白名单，git diff --check通过。原Mac更新器三文件与HEAD一致，本地已发布Mac0.1.3 App整树摘要与第114节相同；Git分支/HEAD未变，无提交推送或打包发布。完整和独立执行会话均已结束，最后按本机进程名未见QEMU/CTFLabGUI；不推断其他Python服务、远端Windows或SSH状态。没有操作用户实例、停机/重启、删资产、修改宿主网络卷/ACL、执行真实到期调度或重做Windows Smoke。

最终摘要`output/windows-ip-20261029/final-evidence.json`，证据包括full-regression-complete.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json、windows-corrected.log、external-final.log、ip-final.log、security-final.log及preservation-final.json/process-final.json。代码/材料与原生实际行为按上述范围区分，所有剩余开发及实机门继续开放，整体未完成；后续继续第4节实际未关闭判据，不把本轮源码增量或测试数量当作全目标达成。


## 119. 连续开发：缓存逐对象回收账本与显式恢复（2026-10-29）

承接第118节及全部未关闭目标，本轮继续第4节P03实际开发。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持；415份开始文件摘要见`output/cache-gc-20261029/baseline.json`，保留已有改动，无拉取/切换/清理。上一轮已核验最后无本机QEMU/CTFLabGUI，结束时再次核验，不把历史PID作为操作依据。

[本轮说明](ctflab-cache-gc-2026-10-29.md)记录P03回收恢复：新计划绑定根/DB/objects身份及逐对象inode/大小/mtime/ctime/内容摘要；先落逐对象attempt再unlink/result，原SQLite排他门覆盖新引用竞态。明确接受新operation与plan摘要才开始；只读status区分未尝试/未知/删除/保留，接受新observation摘要才可继续所有仍匹配无引用的未尝试对象；所有已尝试对象永不从旧操作重试，同名重现保留。旧无attempt意图只读legacy-unresolved，孤立/部分回执拒绝，不自动清理账本。新增固定CLI，缺execute/错摘要拒绝；原collect API接同一账本。

测试只用自动生成的临时字节、SQLite/文件与自有Python CLI。没有删除用户既有资产、读取/清理真实课程缓存、操作VM/SSH/Docker、停机重启、改宿主网络卷/ACL、执行到期调度、重做Windows Smoke、提交推送/打包发布。POSIX文件/目录fsync与故障注入不等于物理断电，Windows目录持久性/ACL/NTFS及真实缓存/大文件/长期故障未验；cleanup_verified=false，应用锁不约束外部同用户写入，公共审计/日志/卷外完整硬配额仍开放。Mac0.1.3发布包不含115—119节源码，Windows候选；原更新器/旧App保持。

新增18项先行通过；最终集中验证与保全在下文补录。其他第4节未关闭开发及实机门、43项/G0/G1/graceful_stop_verified与总目标未完成，不能将本轮恢复功能替代全部验收。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第119节及剩余第4节，核验Git/实例并保留全部改动；承接Windows专用IPv4端点和缓存逐对象恢复源码，继续全部未关闭开发。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/提交推送/打包发布，不将43项/G0/G1写成完成。


第119节最终集中结果：最终完整入口1866项，1845通过/21条件跳过（263.282秒）；最终白名单独立副本1005项，997通过/8跳过（26.859秒），261文件/178个Python语法/78运行时模块/24固定帮助入口通过（含帮助共29.094秒）。222份非docs文件与最终源码逐字一致，完整入口开始后没有修改代码；之后仅补本节结果和输出证据。完整入口含Swift核心及真实GUI编译通过；本轮未改React/SwiftUI，没有重复前端专项，不把以前的54项计成本轮重跑。

新回收恢复18项、原内容缓存18项、上传18项、课程映射11项通过。临时夹具中真实unlink/SQLite排他门和`-I`命令验证只涉及本轮自动生成的字节；没有访问实际课程缓存、删除用户既有资产或调用真实VM/网络/SSH/Docker。内存故障/回执注入不替代物理断电/Windows NTFS/大文件/跨设备验收；unknown和cleanup_verified=false保留。gc-initial.log最初17项、gc-final.log调整边界前18项、cache-initial/final.log等是阶段记录，以gc-complete/cache-complete和最终完整/独立结果为准。

415份开始文件全部保留：7份本轮预期修改、408份相同，无缺失；新增一模块/一测试/一说明3份已纳入白名单，git diff --check通过。原Mac更新器三文件与HEAD一致，本地已发布Mac0.1.3 App整树摘要与第114节相同；分支/HEAD未变，无提交推送、交付打包或发布。完整及独立会话均结束，最后按本机进程名未见QEMU/CTFLabGUI，不推断其他服务或远端状态。没有停机/重启用户实例、删除已有资产、改宿主网络卷/ACL、实际到期调度、桌面控制或重做Windows Smoke。

最终摘要`output/cache-gc-20261029/final-evidence.json`，证据包括full-regression-complete.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json、gc-complete.log、cache-complete.log、uploads-final.log、course-final.log及preservation-final.json/process-final.json。仍有公共存储完整平台配额、更广未知恢复/长期监督、多跳/DNS/完整PMTU、真实课程/分析镜像、最终安装签名闭包及第4节各原生门需要继续开发或验收；不把本轮明确恢复入口当作全部开发完成。43项/G0/G1/graceful_stop_verified及整体目标保持开放。


## 120. 连续开发：服务端公共存储池与独立后台容量绑定（2026-10-29）

承接第119节和全部未关闭目标，本轮推进R02/P03公共缓存、审计/日志和租约等卷外存储缺口。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持；418份开始文件摘要见`output/storage-pool-20261029/baseline.json`，全部既有输入保留，无清理/拉取/切换。开始只读本机进程名快照未见QEMU/CTFLabGUI，不推断远端。

[本轮说明](ctflab-server-storage-2026-10-29.md)记录可选storage_pool：复用已有Linux/Mac APFS/Windows NTFS只读容量绑定，要求所有策略声明的实例、缓存、审计和租约持久根位于同一专用池内；额外审计归档/换库目的地也检查。前后重验原卷/容量与已有路径，拒绝越界、链接/重解析及设备漂移。每消息在审计/派发前、课程/租约/审计/调度管理与后台许可重验，新课程登记原profile摘要；已有实例必须先在原双门下明确登记，不能自动接管活动/已准备实例。

上下文先提交实例账本再写排他旁车；旁车丢失/部分写入不撤销已登记限制，独立后台/代次准备/驱动节点路径读取原登记，QEMU launch带上下文摘要且worker在start.intent/Popen前重验。preview/inspect只读，bind需要当前摘要及execute，不改原profile/基盘，不自动写策略或建卷/设置quota。池是全部已声明服务端持久根共享容量，不是逐实例硬配额；管理员配置/用户导出/外部VM及第三方临时写入等不作全宿主覆盖，all_host_writes_covered=false。

仅临时目录、SQLite/文件、原生卷provider替身与自有Python命令验证，未读取/改变真实配额卷。首次17项有2处夹具错误（上传辅助方法遗漏、活动代次键错误），修正后17项通过；追加反例后22项通过，旧日志保留。真实平台容量/写满/元数据耗尽/重启/多用户与长期故障未验，Mac CPU/内存强限制及卷外未受管写入仍开放。没有VM/SSH/Docker、停机/重启、资产删除、宿主网络卷/ACL变更、真实到期调度、重做Windows Smoke、桌面控制、提交推送/打包发布。Mac0.1.3发布包不含115—120节源码，Windows候选；原App/更新器保持。

最终集中结果与保全在本节末补录。第4节所有未关闭开发及真实课程/网络/分析镜像、最终原生安装/签名/闭包等继续推进；43项/G0/G1/graceful_stop_verified和全部目标未完成。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第120节和剩余第4节，核验Git/实例并保留全部改动；承接服务端公共池/账本与独立后台绑定、缓存回收恢复和Windows IPv4源码，继续全部未关闭开发。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/提交推送/打包发布，不将43项/G0/G1写成完成。


第120节最终集中结果：最终完整入口1888项，1867通过/21条件跳过（262.363秒）；最终白名单独立副本1027项，1019通过/8跳过（27.556秒），264文件/180个Python语法/79运行时模块/25固定帮助入口通过（含帮助时间见isolated-final-evidence.json）。224份非docs文件与最终源码逐字一致，完整入口开始后没有修改代码；之后只补本节结果及输出证据。完整入口内Swift核心/真实GUI编译通过；本轮没有改React/SwiftUI或重复前端专项，旧前端计数不作为本轮重跑。

公共池最终22项通过；先行原远程19项、课程11项、租约27项、驱动36项（35通过/1跳过）、审计换库6项、审计结清23项、调度7项通过。上述旧专项启动早于最后少量守卫/严格比较调整，最终源码依据完整1888/独立1027及pool-complete.log，不能把先行日志冒充全部最后重跑。pool-initial.log中的17项2处夹具失败保留，pool-second/third.log的17项、pool-final.log的22项是阶段记录，以最终pool-complete及集中结果为准。

新增实际内核范围是临时文件/SQLite/自有Python命令；容量依据明确是provider替身，没有真实APFS/NTFS/Linux配额卷、物理写满/inode/断电/重启、多用户、VM/SSH/网络或Windows原生验收。公共池源码覆盖声明的受管持久根，不覆盖整个宿主写入或逐实例独立硬配额；现有外部资产、系统临时写入等边界保留。没有操作用户实例、自动停机/重启、删除已有资产、宿主网络卷/ACL变更、实际到期调度、桌面控制、原生Smoke、提交推送、交付打包或发布。

418份开始文件全部保留：17份本轮预期修改、401份相同，无缺失；新增一模块/一测试/一说明3份列入白名单，git diff --check通过。原Mac更新器三文件与HEAD一致，本地已发布Mac0.1.3 App整树摘要与第114节相同；分支/HEAD未变。完整、独立及先行专项会话均已结束，最后按本机进程名未见QEMU/CTFLabGUI，不推断其他服务或远端状态。

最终摘要`output/storage-pool-20261029/final-evidence.json`，证据包括full-regression-complete.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json、pool-complete.log、remote-initial/course-initial/leases-initial/driver-initial.log、rotation-final/review-final/scheduler-final.log及preservation-final.json/process-final.json。Mac0.1.3已发布包未更新，Windows继续候选；第4节全部尚未关闭的开发及实机门继续，43项/G0/G1/graceful_stop_verified和整体目标保持开放，不能以本轮公共池/后台绑定或回归总数认定全部完成。


## 121. 连续开发：C07独立WAF/应用对照与结构化事件（2026-10-29）

核对第120节、剩余第4节与43项原判据后，推进C07缺少实际独立内容的问题。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`不变；421份开始文件摘要见`output/waf-course-20261029/baseline.json`，保留全部既有输入，无拉取/覆盖/清理/切换。上轮最后本机未见QEMU/CTFLabGUI，本轮结束重新核验，不以历史PID操作进程。

[本轮说明](ctflab-waf-course-2026-10-29.md)记录独立固定目录搜索应用、WAF观察/阻断、合法书名误报、请求标识关联与只读事件页/全量封存；学生任务和教师部署/答案独立。输入不进入SQL/HTML/命令执行，这只是教学匹配器，不是生产WAF或真实漏洞证明；没有改普通渗透课默认路径。所有服务限专用来宾回环，生产CLI先核对原生VM UUID/代次/配置/清单/执行路径；Mac宿主CLI拒绝，不创建服务。候选TCP登记不部署SSH或自动注册。

私有HMAC绑定请求/范围、应用拒绝重放，代理固定回环上游不随客户端目标/头变化；上游未知保留pending不重试。线程/头/查询/响应/请求账本有界，配置/软件/密钥/代次不能混入旧记录；只读导出新目录，不带查询原文/认证头/cookie/密钥/教师答案，原库与旧现场保持。事件不是全量访问/PCAP/Windows事件日志或外部可信锚，客户端实际交付未证明。

本轮22项先行通过；其后发现只回显ID不能验证上游响应，补齐方向/范围/状态/正文HMAC与伪造响应拒绝反例后最终专项23项通过。使用临时文件/SQLite与真实自有回环HTTP、来宾身份provider替身，未启动实际VM/容器。早期失败是路径编码与不同关闭阶段RST断言，保留日志；超大头在排空后按EOF/RST/431拒绝验证且无业务记录，服务限制不放宽。最终集中结果、独立业务演示及保全在末尾补录。未进行真实Windows/Linux来宾、Docker/D02网络/O02分析、浏览器人工或课堂验收，C07整体、C06和其余第4节开发/实机门不关闭；43项/G0/G1/graceful_stop_verified与总目标保持开放。

没有操作用户VM/SSH/Docker、停机/重启、删除已有资产、改宿主网络卷/ACL、跑到期调度、重做Windows Smoke、桌面控制、提交推送、交付打包或发布；新HTTP测试仅自有127.0.0.1临时监听，不增加对外监听。原Mac更新器/已发布App保持，Mac0.1.3包不含115—121节源码，Windows候选。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第121节与剩余第4节，核验Git/实例并保留全部改动；承接C07教学应用/WAF真实回环业务、公共存储池、缓存恢复和Windows IPv4源码，继续全部未关闭开发。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/提交推送/交付打包发布，不将43项/G0/G1写成完成。


第121节最终集中结果：最终完整入口1911项，1890通过/21条件跳过（291.877秒）；最终白名单独立副本1050项，1042通过/8跳过（29.112秒），267文件/182个Python语法/80运行时模块/26固定帮助入口通过。226份非docs文件与最终源码逐字一致，最终full-regression-current启动后未再改源代码，之后仅补本节与输出证据；完整入口内Swift核心/真实GUI编译通过。React/SwiftUI未改且未重跑前端专项，新C07中文事件表的JS通过node --check，但没有浏览器实际渲染/交互或原生桌面验收。

最终WAF专项23项通过，日志waf-ui-final.log；初期19项路径编码/RST断言失败、后续21/22项与waf-final.log（23项但中文表调整前）均保留。先前full-regression-complete.log/isolated-final系列属于响应HMAC修正前，full-regression-final.log/isolated-current系列属于展示页调整前，不替代最终current完整与isolated-complete独立结果。上游身份只回显请求ID的缺口已经修复为方向/范围/请求/状态/正文HMAC，不在旧22项上冒充重测。

最终独立自有回环业务演示见business-current-evidence.json：5组固定公开教学查询，两种模式共10个请求，观察端5组均200；阻断端正常词200，SQL/HTML/父路径样式及合法书名误报4组403。应用实际处理6个请求，标识逐一对应，4个被阻断标识没有应用结果；合法书名在观察端实际返回database目录项。导出app12、observe10、block10条intent/result，三个原事件库摘要导出前后一致，事件文件/清单不含密钥或教师材料。演示驱动记录自己的公开输入，服务事件仍不记录查询原文；pending/客户端未证明与搜索账本覆盖范围不扩大。三份演示服务均为本进程自有127.0.0.1线程，明确注入来宾身份provider，已全部关闭；不是实际VM/Docker/SSH/浏览器或真实隔离/课堂验收。

421份开始文件全部保留：6份本轮预期修改、415份相同，无缺失；新增一模块/一测试/一说明3份列白名单，git diff --check通过。原Mac更新器三文件与HEAD一致，本地已发布Mac0.1.3 App整树摘要与第114节相同，分支/HEAD未变；本轮未重新查询远端或制作交付包。所有完整、独立、专项与自有演示执行会话结束，最后按本机进程名未见QEMU/CTFLabGUI；不推断其他服务或远端状态。没有停机/重启用户VM、已有资产删除、宿主网络卷/ACL变更、到期调度、原生Windows Smoke、桌面控制、提交推送或发布。

最终摘要`output/waf-course-20261029/final-evidence.json`，证据包括full-regression-current.log、isolated-complete.log/isolated-complete-evidence.json/source-files-complete.json、waf-ui-final.log、event-page-syntax-evidence.json、business-current-evidence.json/business-demo-current.log、business-demo-exports-current各角色封存及preservation-final.json/process-final.json。可审阅材料位于business-demo-current/student/学生任务.md和teacher/部署与说明.md，其他私有角色材料/密钥不分发；旧演示/失败/源码副本全部保留。C07还缺真实来宾/容器/D02/O02、浏览器/课堂验收，不能替代C06或其余第4节实际开发；43项/G0/G1/graceful_stop_verified和全部目标继续开放。


## 122. 连续开发：C06自建Windows应用现场、原生事件适配与派生处置（2026-10-29）

承接第121节与全目标，核对C06原判据后补独立教学链。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持；424份开始摘要见`output/ir-course-20261029/baseline.json`，保留既有输入，无拉取/覆盖/清理/切换。上轮结束无本机QEMU/CTFLabGUI，本轮结束重新核验，不按历史PID操作。

[本轮说明](ctflab-ir-course-2026-10-29.md)记录C06源模块：教师明确触发自建应用配置事件，业务503而health200；固定Windows Application自有源事件/范围/HMAC、原件捕获、不同目标VM UUID的新材料派生、派生修复/复验与本课基线恢复。生产须专用Windows原生SMBIOS/私有根/软件/密钥/代次绑定，activate与动作需明确execute/当前摘要；默认不允许发事件。没有HTTP控制入口、任意系统动作、日志清空、注册表写、服务/VM生命周期或系统网络变更。

原事件源若已注册即拒绝接管；只使用固定ReportEvent/查询/UTF-16渲染/有界RecordID范围EVTX导出，原生句柄错误路径也释放。Windows事件表示变更准备，不能单独证明本地状态提交。意图/原HEAD原字节/目标配置/尝试先于事件，未知不重报；明确接受重新观察的唯一匹配事件与状态摘要才补本地提交，旧收据不当现在状态。capture逐字节保存配置/操作与自有事件，失败留INCOMPLETE；derive不执行/解析EVTX或捕获内代码，复制后封存前不可激活，原件保持。

先行事件适配13项、课程18项通过，真实文件/文件锁/回环HTTP配合Windows API及机器身份替身；没有实际Windows DLL/注册表/事件写入/EVTX或两台Windows设备验收。真实授权来宾/ACL/权限/消息/导出/克隆/课堂与整课VM重置仍未验；本课reset只是自身配置恢复，不能替代S03或C02/C06整体验收。最终集中验证、流程证据与保全在末尾补录。

没有用户VM/SSH/Docker、停机/重启、已有资产删除、宿主网络卷/ACL变更、到期调度、原生Smoke、桌面控制、提交推送/交付打包发布。原Mac更新器与已发布App保持；Mac0.1.3包不含115—122节源码，Windows候选。本轮未重新查询远端，第4节其他实际开发/实机门与43项/G0/G1/graceful_stop_verified和总目标继续开放。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第122节与剩余第4节，核验Git/实例并保留全部改动；承接C06现场/Windows事件适配/派生处置、C07与公共池等源码，继续全部未关闭开发。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/提交推送/交付打包发布，不将43项/G0/G1写成完成。


第122节最终集中结果：最终完整入口1942项，1921通过/21条件跳过（271.107秒）；最终白名单独立副本1081项，1073通过/8跳过（32.849秒），272文件/186个Python语法/82运行时模块/27固定帮助入口通过。230份非docs文件与最终源码逐字一致，最终full-regression-final启动后没有再改源代码；之后仅补本节/输出证据。完整入口中的Swift核心/真实GUI编译通过；React/SwiftUI未改，没有重复前端专项，也不把本课JSON业务端点当作原生UI验收。

最终事件适配13项（events-current.log）、课程流程18项（ir-current.log）通过。先行events-initial11/ir-initial12及events-final/ir-final等是开发阶段记录；补齐原字节/目标UUID/派生封存/复制重验/UTC时间/未知恢复等后，以最终完整/独立及current专项为准。第一次full-regression-complete/isolated-complete系列启动后，只把一个拒绝测试显式隔离为posix替身，避免未来Windows上误调真实平台；最终full-regression-final与isolated-final副本已按全部最后测试文件重跑，不混用先行通过作最终范围。

独立业务演示business-evidence.json使用本机自有私有目录/真实回环HTTP与两个明确模拟Windows机器标识、ctypes事件API替身：原服务200→明确incident后503，health仍200；原快照完整导出；不同目标UUID/新lab_uuid派生初态503→repair后200，原现场仍503且原HEAD/所有封存文件摘要不变；派生自身reset后仍200，原事件/旧配置保留。模拟ReportEvent共3次，EVTX明确是假夹具，native_windows_api_executed=false；没有实际Windows记录、磁盘克隆或两台设备验收。两个自有服务已全部关闭，没有停止VM或清Windows日志。

424份开始文件全部保留：6份本轮预期修改、418份相同，无缺失；新增两模块/两测试/一说明5份列白名单，git diff --check通过。原Mac更新器三文件与HEAD一致，本地已发布Mac0.1.3 App整树摘要与第114节相同；分支/HEAD未变，无提交推送/交付打包或发布，本轮未重新查询远端。所有完整/独立/专项和自有演示会话均结束，最后按本机进程名未见QEMU/CTFLabGUI，不推断其他服务或远端状态。没有用户VM/SSH/Docker、停机/重启、已有资产删除、宿主网络卷/ACL变更、实际到期调度、原生Windows Smoke或桌面控制。

最终摘要`output/ir-course-20261029/final-evidence.json`；证据包括full-regression-final.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json、events-current.log、ir-current.log、business-evidence.json/business-demo.log、original-capture及derived-demo/evidence-original、preservation-final.json/process-final.json。可审阅original-demo/student/学生任务.md与teacher/部署与真值.md；角色密钥不分发，EVTX假夹具不作原生样本。真实Windows ACL/权限/消息/记录/EVTX/原VM与克隆/整课重置/课堂门仍需验证，C06整体和其余第4节实际开发/实机门继续；43项/G0/G1/graceful_stop_verified及全部目标保持开放。


## 123. 连续开发：安装运行时探测的清单绑定与剩余判据校正（2026-10-29）

正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持；读取AGENTS.md、当前状态与剩余第4节，核对原43项边界。429份开始文件摘要在`output/installer-probe-20261029/baseline.json`，保留所有已有修改与未跟踪文件，无拉取/切换/清理。只读本机进程名未见QEMU/CTFLabGUI，不推断远端状态。

本轮发现W05实际执行缺口：`ctflab_desktop_package.py probe`此前在运行随包Python前没有重新核对暂存材料。现stage返回`manifest_sha256`供调用方独立保存；新增跨平台只读verify，必须传入原摘要，校验有界清单/相对路径/完整文件集合/独立普通文件及内容摘要。probe保持Windows门，执行前后都核对，固定已核对Python工作目录并关闭标准输入；已有结果不覆盖，结果结构/版本不符或执行中漂移不写成功收据。清单和exe一起改写无法通过原摘要。原Mac更新器未改。

这些检查不把原本未核验的输入变成可信发行物，不证明来源/签名/系统DLL和最终动态闭包，也不能消除同用户可写目录的全部原生加载竞争。生产probe没有在当前Mac执行；平台/子进程回复为替身。实际隔离CLI只对自有临时合成载荷做只读核对，不执行Windows exe、不接触原交付包。说明见`docs/ctflab-recovery-dependencies-2026-10-28.md`第123节增量。

剩余说明第4节同步§108—122实际源码：UDP与点对点IP、公共存储池、独立管理/在线准备、缓存回收恢复及C06/C07已有增量；保留未实现的集成、更广恢复和原生验收，避免旧表把已有实现笼统写为完全缺失。这不是全部开发完成声明，子网/多跳/DNS/完整PMTU与域课程、Mac CPU/内存硬限制、旧匿名管道/Windows/挂起恢复、真实课程/分析镜像及规则、最终原生安装/签名/干净机/课堂等继续开放，原43项/G0/G1/graceful_stop_verified未关闭。

首轮安装专项17项通过；补隔离CLI与链接拒绝后最终19项通过。首轮独立副本1092项有3项既有Windows控制夹具失败（等待control-ready.json），8条件跳过；不能记成通过。随后原控制测试19项单列通过，尚未确定首次就绪超时原因，没有修改控制源码或放宽超时。首轮副本检查期间剩余说明文档有更新，快照检查据实报漂移，全部230份非docs源码保持一致；首轮日志及错误保留。确认副本最终结果见下文。

本轮未重跑完整全仓入口，上一节1942项是历史结果，不作为本轮重跑。本轮范围是安装载荷与独立源码依赖闭包，无React/SwiftUI变更或原生桌面验收。没有VM/SSH/Docker/Windows原生API、停机/重启、既有资产删除、宿主网络卷/ACL改动、实际到期调度、原生Smoke、桌面控制、提交推送/交付打包发布；Mac实际发行仍0.1.3预览，Windows候选，源码增量未入已发布包。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第123节和剩余第4节，核验现场并保留改动；承接安装探测清单绑定及§117—122源码，继续原43项尚未关闭的实际开发，先核实具体缺口再实施。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/提交推送/交付打包发布；保留原Mac更新器，不将代码增量或替身结果当作实机验收。

第123节最终确认：安装专项19项通过（10.745秒），原Windows控制专项19项通过（7.604秒）；全新白名单副本1092项，1084通过/8条件跳过（298.864秒），272文件/186个Python语法/82运行时模块/27固定帮助入口通过。确认复制到结束源码摘要不变，230份非docs文件与当前源码逐字一致；首轮181.276秒的3项失败和文档漂移保留，不与确认结果混淆，没有更改控制超时或以其单列通过掩盖首轮失败。本轮没有重跑完整全仓/原生界面。

最终摘要`output/installer-probe-20261029/final-evidence.json`；关键日志package-final.log、control-diagnostic.log、isolated-final.log（首轮失败）、isolated-confirmation.log、isolated-confirmation-evidence.json及preservation-final.json。429份开始文件全部保留，5份预期修改/424份相同，原Mac更新器三文件与HEAD一致、已发布App摘要保持，git diff --check和白名单检查通过。最后只读进程名快照未见本机QEMU/CTFLabGUI，不推断远端状态、不操作历史PID；自有临时测试子进程会话已结束。所有未关闭开发/实机门继续开放，全部原边界保持，整体目标尚未完成。


## 124. 连续开发：离线分析程序版本自述与输出原字节对照（2026-10-29）

本轮按原O02判据继续实际执行链，已读取AGENTS.md、状态第123节与剩余第4节。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持；429份开始文件摘要在`output/analysis-reproducibility-20261029/baseline.json`。保留全部既有修改/原始资产/旧包，无拉取/切换/清理。上轮结束及本轮最后只读本机进程名核验，不操作历史PID或推断远端状态。

修复过去只比较镜像标签、不检查程序自述版本的执行缺口：原隔离wrapper先运行固定Zeek --version/Suricata -V入口，接受精确版本/固定输出形状，输出不超过4096字节；版本和分析共用原timeout预算，版本最多5秒。版本不符/混杂/过长/失败不开始分析，报告与stderr保留；新wrapper摘要使旧镜像不能静默兼容。没有构建/运行任何真实分析镜像。

分析结束后在原容器内按名称/大小/原字节SHA生成输出内容指纹：包括全部正常输出文件及版本报告/stderr，最多512目录项/8层目录/2MiB内容，拒绝非法名、链接/硬链接、非普通文件、原件/树漂移及分析器预占wrapper控制文件。保留完整output-manifest.json，不清除日志时间戳/随机字段来强行相等；文件系统时间不参与最终内容摘要。成功状态必须附相符版本与合法指纹，旧状态/缺失字段不能作为成功导出，未知不重放。容器/tmpfs/网络none/只读挂载/CPU内存PID及先封存再结束自有容器流程保持。

结果补操作/实例/代次/策略/wrapper绑定；新增compare-results只读两份64KiB以内、调用方原SHA匹配的普通独立JSON，拒绝重复字段/非标准常量和漂移。要求不同操作且全部上下文一致，只输出报告的文件内容和版本报告是否相同，不读取PCAP或tar、不运行分析器或连接Docker。GuestKit原有白名单无新运行时依赖，实际在生成材料的隔离副本执行新延迟读取/对照入口，避免仅import掩盖缺依赖。新说明`docs/ctflab-analysis-reproducibility-2026-10-29.md`加入忽略规则/独立源码白名单，第4节同步O02增量。

边界：版本文本是程序自述，不证明来源签名或分析器未被攻击；工具与wrapper同处容器，被攻陷工具可伪造自身输出。指纹是容器内文件快照，不证明后续tar封存期间无竞争或归档字节相等；独立保存的JSON摘要也不赋予认证。因此reports_authenticated/analysis_findings_verified/byte_reproducibility_verified继续false，真实镜像/规则、畸形输入隔离、同证据真实重复分析和归档一致性仍开放。本轮没有把元数据相等当作完整O02或C07验收。

专项首轮27项通过，补数量/深度/硬链接/总量和JSON负向后最终31项通过（4.956秒）；来宾安装材料3项通过（0.251秒）。真实子进程仅自有替身程序：先行版本/拒绝、预算超时、SIGTERM、两次相同字节与一次差异，均执行原wrapper但无真实Zeek/Suricata/PCAP解析。保留演示output/analysis-reproducibility-20261029/business-demo、business-evidence.json及business-demo.log；3份结果使用显式合成上下文，原始版本报告/日志/manifest/status可复核，子进程全部收回。

完整回归1973项，1952通过/21条件跳过（265.435秒）；源码冻结后开始，没有在运行中修补测试或生产代码。最终独立副本结果与保全见下文。React/SwiftUI产品代码未变，完整入口含Swift核心/实际GUI编译通过，不等于真实窗口/用户操作验收。本机发现Docker CLI只表示命令存在，没有连接引擎、下载/构建或运行容器。

没有用户VM/SSH/Docker/真实分析工具、停机/重启、既有资产删除、宿主网络卷/ACL改动、实际到期调度、原生Smoke、桌面控制、提交推送/交付打包发布；原Mac更新器与发布App保留，Mac实际发行仍0.1.3预览、Windows候选，后续源码没有更新已发布包。第4节其他未关闭开发/实机门、43项/G0/G1/graceful_stop_verified和整体目标仍未完成。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第124节和剩余第4节，核验现场并保留全部改动；承接隔离分析版本/输出对照与§117—123源码，继续原43项尚未关闭的实际开发，最终按原判据逐项验证。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/提交推送/交付打包发布；保留原Mac更新器，不用替身或报告匹配替代实机验收。

第124节最终集中确认：完整1973项，1952通过/21条件跳过（265.435秒）；白名单独立副本1112项，1104通过/8跳过（35.127秒），273文件/186个Python语法/82运行时模块/27固定帮助入口通过。复制及执行期间源码摘要不变，230份非docs文件与当前源码逐字一致；之后仅补状态/输出证据。原wrapper演示同字节指纹相等、差异字节不等，原始材料仍在且摘要一致；它不是实际分析镜像/PCAP或归档证明。

429份开始文件全部保留，7份预期修改/422份相同，新增1份分析说明；原Mac更新器三文件与HEAD一致、已发布App摘要不变，git diff --check及白名单检查通过。最终只读进程名快照未见本机QEMU/CTFLabGUI，不推断远端状态、不操作用户进程；完整与独立验证会话已结束。最终摘要`output/analysis-reproducibility-20261029/final-evidence.json`；完整full-regression-final.log、独立isolated-final.log/isolated-final-evidence.json/source-files-final.json、analysis-current.log、guest-kit-current.log、business-evidence.json及preservation-final.json保留。最初analysis-initial.log是27项阶段记录，不与最终31项混用。操作边界、实际发布状态和全部未关闭门保持，整体目标尚未完成。


## 125. 连续开发：tmpfs流式归档与独立隔离内容核对（2026-10-29）

按原O02及第124节归档一致性缺口继续实施，已读AGENTS.md、当前状态和剩余第4节，并核对原43项判据。正式目录`/Users/pufei/Downloads/ctf-lab`，分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`不变；430份开始文件摘要在`output/analysis-archive-20261029/baseline.json`。保留已有修改/原始资产/旧包，无拉取/切换/清理。

核对Docker一手文档发现旧导出使用docker cp读取tmpfs不符合其支持路径。`ctflab_guest_analysis.py`现由原分析容器的固定Python -I -B/wrapper archive模式流式生成PAX tar；宿主仅保存原字节，原20秒/4MiB和0600 partial、越界/断线保留及只回收本次客户端的规则保持。没有运行宿主tar或解包原始归档。

有内容指纹时新增独立校验容器：原归档保持0600，新私有操作目录内0444独立副本仅只读挂载到固定路径。校验前后核对原件/副本SHA和inode/时间；容器绑定原实例/代次/策略/操作及独立角色，network none、只读根、UID1000、cap-drop ALL、no-new-privileges、128MiB内存及同量swap上限、1 CPU/16 PID、无重启和有界日志，20秒客户端预算。创建前拒绝镜像声明的任何VOLUME，两容器均禁用继承HEALTHCHECK，避免未跟踪卷/后台程序；实际配置和固定Python参数先读回校验。

校验器仅在新容器读取成员流，不创建成员文件或执行成员：有界未压缩tar/PAX、路径/普通文件/目录、最多515成员、巨大声明/PAX长度、链接/FIFO/稀疏/重复/越界/尾部数据及串接归档拒绝；原status规范SHA绑定导出前观察，完整manifest逐项匹配实际成员字节及新内容指纹，完整归档SHA再与原件匹配。只有实际退出码与结果/原件均匹配，才记录archive_content_consistent及校验容器/收据。它不表示工具未被攻击、两次分析相同或结论正确，byte_reproducibility_verified和analysis_findings_verified仍false。已知分析失败且无清单时仅封存未核验原归档，不能伪装成功。

复制/创建/运行先落原操作意图；丢回复、非法或重复JSON、非零退出、配置/原件漂移保持unknown，不自动重试原操作、不自动重新归档/停止未核对容器、不删除原件/副本/记录。宿主状态元数据也新增大小/重复字段/非法常量拒绝。来宾材料没有新增非标准依赖，镜像须明确准备新wrapper，旧镜像不静默兼容。说明与一手依据见`docs/ctflab-analysis-reproducibility-2026-10-29.md`第125节；剩余第4节已同步本源码增量，原门未关闭。

专项从50→53→54→最终55项均通过；最终`python3 -B -m unittest discover -s tools/tests -p test_ctflab_guest_analysis.py -v`，55项通过（8.756秒），含Docker接口替身、真实自有Python归档生产/校验子进程、恶意结构合成成员与失败保全。来宾材料专项3项通过（0.282秒），生产模块在此后未再修改。完整`python3 -B -m unittest discover -s tools/tests -v`最终1997项，1976通过/21条件跳过（279.797秒）；源码冻结后启动，运行中没有修补代码/测试。Swift核心/实际GUI编译在完整入口通过，React/SwiftUI未改，没有声称用户窗口/原生容器验收。

独立复制显式白名单后相同发现入口1136项，1128通过/8跳过（39.431秒），273文件/186个Python语法/82运行时模块/27固定CLI帮助全部通过。复制/运行期间源码不变，230份非docs文件与最终源码逐字一致；之后只补本节/输出证据。两次验证会话已结束。

保留业务演示`output/analysis-archive-20261029/business-demo`：原wrapper产生原始tar，在独立Python子进程核对为archive-content-matches；只改新派生归档日志字节后返回archive-refused，原始归档/原输出所有字节前后相同，子进程均已收回。这里的分析器/身份/上下文为自有合成替身；没有真实PCAP、Docker、来宾、128MiB容器隔离或实际镜像复现，不能把Mac子进程当作原生沙箱验证。

430份开始文件全部保留，5份预期修改/425份相同；原Mac更新器三文件与HEAD一致、已发布App摘要不变，git diff --check与白名单检查通过。最终进程名快照见final-evidence.json，不操作用户进程/历史PID或推断远端状态，本轮未创建用户VM。无实际Docker/镜像构建/SSH、停机/重启、已有资产删除、宿主网络卷/ACL改动、实际到期调度、原生Smoke、桌面控制、提交推送/交付打包发布。已知本地Mac发行仍0.1.3预览、Windows候选，本轮未查询远端发行，后续源码未更新旧包。

最终摘要`output/analysis-archive-20261029/final-evidence.json`；证据包括full-regression-final.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json、analysis-complete.log、guest-kit-final.log、business-evidence.json/business-demo.log及preservation-final.json。initial/current/final专项日志分别是50/53/54项阶段记录，不代替最终55项。所有真实镜像/规则/畸形输入隔离/复现和第4节其他实际开发及原生验收仍开放，43项/G0/G1/graceful_stop_verified和整体目标尚未完成。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第125节及剩余第4节，核验现场并保留改动；承接tmpfs归档与独立校验及§117—124源码，继续原43项全部未关闭开发和验证。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/提交推送/交付打包发布；保留原Mac更新器，不以元数据或替身通过替代真实来宾/最终包验收。


## 126. 连续开发：桌面桥接有界输出、等待与后台回收（2026-10-29）

承接原43项A03/W04/W05，已读AGENTS.md、状态第125节与剩余第4节，并核对桌面/版本调用链。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持；430份开始文件摘要见`output/desktop-transport-20261029/baseline.json`。保留已有修改、资产与旧包，无拉取/切换/清理。

原Tauri桥接先write_all，再wait_with_output无限收集全部stdout，最后才检查4MiB；后台不退出/后代持管道时会无限等待，输出越限前也可能过量分配。新增`desktop/src-tauri/src/transport.rs`供原本机/远程/客户端/版本四条固定路由共用：64KiB输入、读取中4MiB上限、90秒界面等待、全局8在途槽位，发送/读取/退出监督分开，避免等待预算依赖管道先收口。没有增加任意程序/shell/脚本选择入口或改变JSON业务契约。

输出越限立即报告结果未确认，但继续排空并丢弃后续输出，不关闭管道让原后台中途写失败；等待超时只结束本次等待，原请求可能继续处理。原操作幂等键/账本仍须核对，不能重新创建。只有进程实际退出且两条管道结束才释放槽位；父进程已退出但后代持管道仍占槽，退出观察失败保留槽位，并发满在新进程创建前拒绝。没有kill/终止进程树/VM关机/自动重放路径，传输内存/线程约束不等于VM硬配额。非零退出的契约错误JSON保留给原解析，非法响应不被当成业务成功。

原目录Rust1.90锁定编译`cargo test --locked --offline`最终11项通过（0.23秒），其中9项新自有进程断言、1个测试子进程入口、既有文件选择白名单1项；`cargo check --locked --offline`通过。覆盖完整输入、越限后写入完成、接收方延迟读取时超时且后台继续、并发拒绝/完成后释放、父退出后代持管道、无效程序/过量输入不创建后台、非零错误内容、非法UTF8。测试只执行本Rust测试二进制，未启动Python/VM/真实Tauri窗口。延迟接收不测量内核管道容量，不宣称覆盖所有平台的实际阻塞写入。

1.90 minimal工具链缺rustfmt，首次默认fmt明确失败；未安装组件，改用机器已有stable rustfmt（1.8.0）格式化/检查两份实际改动Rust源文件，最终通过。全目录fmt一次触及build.rs后，已从阶段开始摘要一致的既有源码副本恢复原字节，最终build.rs/rust-toolchain/Cargo.lock均与开始一致。初始格式差异日志保留，编译工具链未改，未新增依赖或下载。

白名单新增模块及说明；独立副本275文件/186个Python语法/82运行时模块/27帮助入口通过，相同发现入口1136项，1128通过/8跳过（43.429秒）。还在该副本实际执行锁定Rust测试11项通过（0.22秒）及cargo check通过，复用既有Cargo依赖/target缓存，无外部源码回退或新下载。231份非docs文件与最终源码逐字一致；复制/测试期间源码不变，之后仅澄清说明文字及补本节/输出证据。

本轮未重跑Python完整全仓、React或Swift编译，上一节1997项是历史结果，不作本轮重跑。当前验证是Mac原生Rust自有进程/副本编译与Python依赖闭包，不是Windows原生IPC/GUI、生产90秒/8并发长期故障或关窗后真实QEMU证明。原Swift Process链未替换，尾部仍有整块读取及既有等待策略，后续需按实际调用/结果语义另核对，不能用本轮Tauri结果关闭Mac链路。README接续入口去掉固定第114节及“本轮已打包”歧义，改为当前状态和发行包/源码分列。

430份开始文件全部保留，6份预期修改/424份相同，新增Rust模块与说明2份；原Mac更新器三文件与HEAD一致、已发布App摘要不变，git diff --check/白名单检查通过。最终只读本机进程名快照见final-evidence.json，不操作历史PID或推断远端状态，测试自有进程随句柄/管道收口回收。无用户VM/SSH/Docker、停机/重启、已有资产删除、宿主网络卷/ACL变更、到期调度、原生Smoke、桌面控制、提交推送/交付打包发布。已知本地Mac发行仍0.1.3预览、Windows候选，本轮未查询远端发行或更新旧包。

最终摘要`output/desktop-transport-20261029/final-evidence.json`；证据为rust-final.log/rust-check-final.log/rust-format-final.log、rust-isolated-final.log/rust-isolated-check-final.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json、toolchain-evidence.json及preservation-final.json。initial/current的10项Rust记录为阶段历史，不与最终11项混用。全部第4节其他实际开发/原生验收、43项/G0/G1/graceful_stop_verified和整体目标继续开放。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第126节及剩余第4节，核验Git/实例并保留全部改动；承接桌面有界桥接与§117—125源码，继续原43项全部未关闭开发，原Swift读取/等待链按具体语义核对，不以传输错误推断业务未发生。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/提交推送/交付打包发布；保留原Mac更新器与旧包，不把替身/编译通过当实机验收。


## 127. 连续开发：Mac输出、显示通知与私有请求等待保全（2026-10-29）

承接原A03/Mac接入与第126节实际读取缺口，已读AGENTS.md、状态和剩余第4节。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持；432份开始文件摘要见`output/mac-transport-20261029/baseline.json`。保留全部既有修改/原始资产/旧包，无拉取/切换/清理。

Swift原输出链退出时整块readDataToEndOfFile，以及逐chunk完整正文快照排队，均可能绕过缓冲上限。现将读取/有界正文/显示合并/资源票据/一次性回复抽至Foundation核心：独立CLOEXEC读描述符绑定原管道，单次Darwin.read最多64KiB，读和append串行；正文私有4MiB/普通16MiB，越限继续排空却不信任截断前缀，编码/读取/发送错误均未知。候选创建提示独立按字节扫描，跨UTF8块及越限后仍保留原恢复提示，不等于候选已验证。进度窗口64KiB/显示最多一个待批次64KiB，不把私有请求写流式日志。

私有remote/scenario/generic请求90秒等待，只先交付未知，不取消/杀CLI或VM、不换幂等键/重发。回复门只能一次，迟到终态不会重复更新界面；计时器交付后取消。同进程共享8在途槽，必须进程退出、输出EOF、输入写端关闭后才释放；未核对/后代持管道/观察失败保留占用。普通长导入保留原等待与用户取消，不能套私有90秒或越限时提前清取消目录；只有实际进程/输出收口才清理本次自建控制目录。启动/观察通道失败在未执行CLI时收口，原更新器未改。进度百分比改为先截断后Int，超大/非有限/负耗时显示耗时未知，避免整数转换崩溃。

首次25项GUI入口1项依赖守卫失败：新增显式Dispatch导入不在白名单；已用小探针确认Foundation现有桥接可用后移除，原守卫不放宽，单列复查通过。最初核心355项与类型检查通过，但补充实时管道检查发现Foundation read(upToCount:)会等待满块/EOF，360项中1项失败；保留日志并改为有界单次系统读取，360项通过，再补句柄独立/两管道收口后364项通过。实际检查证明写端仍打开即可读出已有数据，不是只看API名称猜测。后续仅将异常耗时文案改为耗时未知，最终完整/副本覆盖当前源码。

本轮完整`python3 -B -m unittest discover -s tools/tests -v`1997项，1976通过/21条件跳过（277.132秒），包括优化Swift核心及真实GUI编译，源码冻结后没有在运行中修改代码/测试。独立白名单276文件/186个Python语法/82运行时模块/27帮助入口通过，1136项，1128通过/8跳过（41.490秒）。还在该副本实际编译/运行当前Swift核心，364项检查失败0项，GUI类型检查通过；231份非docs文件与最终源码逐字一致，复制/执行期间无源码漂移，之后仅补本节/输出证据。

Swift检查仅当前Mac自有管道/测试二进制/临时文件，覆盖UTF8/字节顺序、上限/提示、千次显示合并、极端进度、FD原句柄关闭且另一管道不被读取、父退出后代持管道、超时后仍有后台完成标记、输入未关保留槽位、一次性交付。没有真实窗口、用户长导入取消、私有生产90秒/8并发长期故障、真实VM/SSH/Docker或关窗后业务证明；Rust/React未改未重复专项，不以传输限额冒充Mac CPU/内存硬配额。

432份开始文件全部保留，7份预期修改/425份相同，新增Mac传输说明1份；原Mac更新器三文件与HEAD一致、已发布App摘要不变，git diff --check/白名单检查通过。最终只读本机进程名快照见final-evidence.json，所有本轮验证会话已结束，不操作历史PID或推断远端状态。没有用户VM停机/重启、已有资产删除、宿主网络卷/ACL变更、实际到期调度、原生Smoke、桌面控制、提交推送/交付打包发布；本地既有Mac发行仍0.1.3预览、Windows候选，本轮未查远端发行或更新旧包。

最终摘要`output/mac-transport-20261029/final-evidence.json`；证据为full-regression-final.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json、core-isolated.log/core-isolated-compile.log/gui-isolated-typecheck.log、core-bounded.log/gui-typecheck-bounded.log、dependency-guard.log与preservation-final.json。gui-initial.log保留依赖失败，core-complete.log保留实时读取失败；core-current/final/verified分别355/358/360阶段记录，不替代最终副本364项。说明`docs/ctflab-mac-transport-2026-10-29.md`与剩余第4节已同步。原43项/G0/G1/graceful_stop_verified、第4节其他实际开发/实机门和整体目标尚未完成。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第127节与剩余第4节，核验Git/实例并保留全部改动；承接Mac/Tauri有界传输与§117—125源码，继续原43项全部未关闭开发和验证，不用超时推断业务未发生。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/提交推送/交付打包发布；保留原更新器与旧包，不以自有进程/编译结果冒充真实窗口/来宾/最终包验收。

## 128. 连续开发：外部Windows受控事件XML采集与取回（2026-10-29）

已读AGENTS.md、最新第127节/剩余第4节，并回查原E02实施backlog与详细设计的日志采集/取回判据。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持。433份开始文件摘要见`output/external-events-20261029/baseline.json`，保留既有改动/资产/原包，无拉取、切换或清理。

现有外部通道只有TCP/UDP/IP，缺少日志读取。新增`tools/ctflab_external_events.py`只加载系统目录wevtapi的EvtQuery/EvtNext/EvtRender/EvtClose；默认配置不读取事件，仅Windows/ad节点显式event_sources且principal获授源名时允许。固定通道名、单provider、至多4个事件ID、最长24小时左闭右开UTC窗口，100ns比较不截断第七位小数；至多32条、单条64KiB、总快照256KiB。禁止任意路径/XPath/命令，权限不足即失败，不提权、不注册源/清日志/写注册表，不启动外部程序或操作VM。

前向枚举同线程关闭所有事件/查询句柄；逐条二次核对通道、provider、事件ID、时间、记录ID、XML摘要，拒绝重复/倒序、DTD/实体、编码/关闭错误、超量和读取超时。超过上限不返回截断成功，空集合只在正常枚举结束时成立。原生SMBIOS/配置/期限在请求前核对，采集后再核对，防止长查询期间身份变化后交付。注入API只标native_collection=false，不冒充原生执行。

原`ctflab_external.py`增加两项固定RPC和collect-events客户端CLI。每会话至多4次尝试，成功UUID/来源重复请求返回原内存快照，失败标识先占位且不再查询；关闭清空原文，仍保留该agent已尝试标识。取回只接受snapshot UUID、原SHA256和16KiB对齐偏移，合计受配置max_bytes限制，无任意文件下载。客户端严格核对完整身份、policy摘要、长度/偏移/eof、整体摘要、规范JSON和每条XML元数据；失败关闭通道且不自动重试。收据固定health_verified/automatic_replay/event_log_modified为false。

保存只接受现有私有父目录的新目标文件；全部下载校验通过后排他创建，POSIX0600，Windows沿用原私有存储检查而不改ACL；原文包含潜在敏感信息，不打印/自动打开或执行，写入错误保留现场。receipt与snapshot同文件保存，控制台只输出严格收据字段。新增模块/测试/说明已纳入.gitignore、发布源码/桌面运行时/独立材料显式白名单；未生成部署材料或交付包，旧agent/旧expected摘要不能未经核对混用新接口。

这是有界XML观测快照，不是原始EVTX导出、原子事件通道历史或取证完整性保证；轮转/清除/并发写入可能改变所见历史。跨SSH会话没有持久幂等/续传，结果未知不自动重连/换UUID/再次采集，显式新采集是新观测。EvtNext每次1秒等待，不能宣称整个原生调用链有硬截止。普通API权限、真实Windows版本/语言/轮转/断线、同宿主Workstation/VirtualBox组合及E03域业务仍未验，EVTX持久导出/恢复仍未实现；不关闭E02/E03。

验证：新增25个测试方法，只用ctypes指针替身、自有XML/临时私有文件；未加载Windows DLL。`python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_external*.py' -v`83项通过（0.639秒）；Windows IP材料相关37项通过（0.158秒）。覆盖白名单/身份/代次/未握手/其他principal、100ns边界、重复ID、超量/坏XML/关闭失败/查询超时、失败占位/四次上限、采集中身份漂移、原文缓存不随源变化、多块摘要/偏移篡改、旧peer能力拒绝及私有保存不覆盖。首次专项78项中1项临时目录系统别名被原私有路径守卫拒绝，已将测试临时路径显式取真实路径；保留focused-initial.log，未放宽安全守卫。

实现冻结后完整`python3 -B -m unittest discover -s tools/tests -v`2022项，2001通过/21条件跳过（283.262秒）；独立白名单279文件/188 Python语法/83运行时模块/27帮助入口通过，副本1161项，1153通过/8跳过（39.414秒）。复制/执行期间无源码漂移，之后只更新本节和剩余文档/证据。233份非docs文件与副本逐字一致；没有在测试运行中修源码，也未重复运行既有Smoke或Rust专项。

433份开始文件全部保留，7份预期修改/426份相同；新增事件模块、测试、说明3份。原Mac更新器三文件与HEAD一致，既有Mac发布App摘要不变；git diff --check与白名单检查通过。最终本机相关进程名只读快照见final-evidence.json，本轮测试会话均已结束，不操作历史PID或推断远端状态。没有用户VM停机/重启、资产删除、宿主网络/卷/ACL变更、实际到期调度、桌面控制、提交推送或打包发布；本地既有Mac发行仍0.1.3预览、Windows候选，未查询远端发行。

证据`output/external-events-20261029/final-evidence.json`、full-regression-final.log、focused-final.log/windows-materials.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json、preservation-final.json；说明`docs/ctflab-external-events-2026-10-29.md`。原43项/G0/G1/graceful_stop_verified、第4节其他开发与实机门和全部开发目标尚未完成；本轮补齐XML路径，不用该路径替代EVTX或真实路由/课堂验收。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第128节和剩余第4节，核验Git/实例并保留全部改动；承接外部Windows只读事件XML路径及§117—127源码，继续全部未关闭开发，不将内存快照称为跨会话EVTX恢复。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/桌面控制/提交推送/交付打包发布；保留原更新器与旧包，不以替身/API结构或测试数冒充真实来宾/最终包验收。

## 129. 连续开发：学生镜像回环HTTPS只读与实际续传（2026-10-29）

承接第128节，核对AGENTS.md、剩余第4节与原backlog，发现P04只有许可导出材料与显式HTTPS镜像客户端，没有受控只读服务入口。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持；436份开始文件摘要见`output/mirror-service-20261029/baseline.json`，保留既有改动/资产/原包，没有拉取、切换或清理。

新增`tools/ctflab_mirror_service.py`和`ctflab_mirror.py serve`，旧导出CLI不变。仅127.0.0.1，端口内核分配或显式给定，不支持LAN地址；实际绑定后才输出就绪。启动前核对私有路径、来源信任根/签名/期限、学生audience与allowed许可、原收据映射，以及每个文件大小/摘要/设备文件ID/链接数/mtime/ctime，完成预检后才监听。只提供原字节INDEX.json和签名学生条目，不提供MIRROR.json/目录索引/教师或其他文件；不接受任意路径、百分号解码、查询参数和目录穿越，原始路径必须等于白名单路径。

GET/HEAD与单段bytes范围（起止/尾部/开放终点）返回精确长度/范围/ETag；多范围、重复/坏Range或越界返回416，If-Range不符回完整200。文件以64KiB流式读取，索引最多4MiB。每请求重核索引/收据/文件身份、签名与期限，打开后fstat再绑定；漂移/替换/软硬链接/过期拒绝新请求。传输中其他同账户程序写盘仍可能改变已发数据，最终SHA256由客户端下载后核对；HTTP200不是内容身份或课程验收证明，不假称不可变卷。

用户显式提供现有私有证书/密钥，最低TLS1.2，ALPN仅HTTP/1.1，拒绝明文；工作线程内握手，最多8个连接，空闲握手/读写5秒超时，不让一个未握手连接堵住主接收循环。无请求路径/头持久日志，不修改系统信任/ACL、不生成证书/下载资产或接管VM。即使误将服务TLS私钥/证书合法签入学生分发索引，也直接拒绝启动该配置，不能让服务凭据成为分发对象。没有mTLS身份服务，许可允许的学生文件只读分发；Python http.server基础不等于生产部署，本入口固定回环，校内生产/代理/限流/续签和跨设备仍未验。

专项首先20项中1个子例失败：BaseHTTPRequestHandler自动把//INDEX.json归一化为/INDEX.json。已保留focused-initial.log，补原始请求路径核对后21项通过。随后主实现冻结并完整`python3 -B -m unittest discover -s tools/tests -v`2037项，2016通过/21条件跳过（279.239秒），记录full-before-credential-guard.log。复核发现凭据分发配置应明确拒绝，之后补该守卫和一项真实PEM/合法签名条目测试，最终专项22项通过（0.422秒）。**完整2037项在最后凭据守卫之前，不冒充最终源码的完整重跑**；最终守卫及当前源码由专项和下述独立副本覆盖，未重复无关GUI编译/Rust检查。

最终独立白名单282文件/190 Python语法/84运行时模块/29帮助入口通过，副本1177项，1169通过/8跳过（45.514秒），复制/执行期间无源码漂移。当前235份非docs文件与副本逐字一致，之后只补本节/剩余文档和证据。新增16个服务测试方法覆盖实际TLS原文GET/HEAD、Range/If-Range、原ContentCache.download真实续传且源身份不变/最终SHA一致、坏证书/明文、索引过期/替换/链接、未登记文件/目录穿越、写方法拒绝、连接槽拒绝与恢复、一个握手等待不堵另一个合法连接、TLS凭据排除等；原6项镜像材料测试保留运行。

还分别在正式源码与独立副本实际启动CLI、自建回环TLS下载1400字节自有夹具并正常退出，stderr空，没有用户VM控制。副本首次通过未固定python3的命令落到Homebrew3.14，缺少cryptography，在创建服务前失败，保留cli-isolated-stderr.log与空输出；现场确认正式目录python3为Miniconda3.10，与副本目录解析不同，改用同一`/opt/miniconda3/bin/python3`明确执行后通过，见cli-isolated-confirmation.json。未安装依赖、改全局PATH/环境或放宽签名校验。独立副本unittest本来已使用脚本sys.executable（Miniconda3.10），其通过结果不受该额外CLI入口失败替代或掩盖。

436份开始文件全部保留，7份预期修改/429份相同，新服务模块、测试、说明3份。原Mac更新器三文件与HEAD一致，既有Mac发布App摘要不变；git diff --check与白名单检查通过。最终本机相关进程名只读快照见final-evidence.json，验证会话和自建服务均已结束，不操作历史PID或推断远端状态。没有用户VM停机/重启、已有资产删除、宿主网络/卷/ACL变更、实际到期调度、桌面控制、提交推送或打包发布；本地既有Mac发行仍0.1.3预览、Windows候选，未查远端发行。

说明`docs/ctflab-mirror-service-2026-10-29.md`；证据`output/mirror-service-20261029/final-evidence.json`、full-before-credential-guard.log、focused-initial/final.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json、cli-evidence.json/cli-isolated-confirmation.json、初次CLI失败日志与preservation-final.json。原43项/G0/G1/graceful_stop_verified、校内生产/真实课程/最终包及全部开发目标未完成。回查原E02判据是受控服务、双向路由和日志采集/取回，不额外把EVTX/跨会话持久导出变成其硬前置；第128节XML观测不承诺该能力，C06取证EVTX仍独立待验。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第129节与剩余第4节，现场核验并保留全部改动；承接学生镜像回环HTTPS及§117—128源码，继续全部未关闭开发，按原43项判据判断，不用回环TLS冒充校内生产部署。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/桌面控制/提交推送/交付打包发布；保留原更新器与旧包，命令行验证显式使用已核对解释器，区分最终副本与守卫前完整回归。

## 130. 连续开发：Mac分享诊断的白名单预览与原字节保存（2026-10-29）

已读AGENTS.md、状态第129节、剩余第4节和原43项backlog。按原判据开始收口核对时发现U02具体产品缺口：Python/React有匿名白名单摘要，Mac“导出脱敏诊断”仍是含路径/日志的私密报告。先修该缺口，不将原43项审计称为已完成，也不继续把可选扩展当硬门。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持；439份开始文件摘要见`output/mac-diagnostics-20261029/baseline.json`，保留全部既有改动/资产/旧包，无拉取、切换或清理。

GuiCore新增MacPublicDiagnostics，用Foundation从已显示StatusProfile重建字段，不复制原始对象。分享文件只含受限版本/系统架构、匿名node-N、固定state/boot_phase、排除项及uploaded=false；陈旧进程登记unknown，未知版本/架构/阶段不回显自由文本。加入observation=displayed-snapshot/may_be_stale=true，明确可能过期的列表快照，不查询来宾/服务或读取原日志，不把process/running标记冒充业务验收。最多256节点/64KiB，超量拒绝而非截断，窗口UUID不写入文件，不生成稳定节点指纹或时间戳。

GuiApp新增“更多→分享诊断摘要”及完整不可编辑预览，用户明确“保存此预览”再选择新文件。Data在预览时构建并不可变持有；后台状态刷新不改该份字节，保存不重采集或重新编码。不上传、不运行额外CLI/网络请求。排他新建0600文件，拒绝既有文件/符号链接/非文件URL，不建父目录，不删除失败现场；失败消息在预览内可见。成功仅在Finder定位本次文件，没有自动打开正文。未读到节点列表时入口禁用；核心空集合可合法编码，不把初始空UI冒充完整诊断。

原exportDiagnostics及CLI未删未改，更名为“完整本机诊断（私密）”，提示含路径/日志并可能敏感，公开反馈应走新摘要入口。原私密日志的关键字过滤及旧CLI文案不是全量可靠脱敏承诺；新入口通过不复制自由字段解决分享边界，不声称原报告已彻底清除所有敏感信息。README已明确这只是未打包工作区行为，既有已发布App仍旧菜单/旧运行时，未更新包或原Mac更新器。

本轮新增25项Swift核心检查：恶意id/name/地址/路径/PID/磁盘指纹、boot诊断/阶段细节、未知阶段/版本/架构不进入摘要；陈旧登记unknown；固定字段、可能过期、无上传；相同输入字节稳定且UUID不泄露；Data/text一致；真实临时文件写入精确原字节/0600、拒绝重复保存/软链接/网络URL；256/257节点边界/64KiB与空集合。实际根目录核心389项、界面类型检查通过；没有编造窗口/保存面板/人工点击或用户反馈结果。

实现冻结后完整`python3 -B -m unittest discover -s tools/tests -v`2038项，2017通过/21条件跳过（282.137秒），包括实际GUI编译和原依赖守卫。独立白名单283文件/190 Python语法/84运行时模块/29帮助入口通过，副本1177项，1169通过/8跳过（44.388秒），复制/执行期间无源码漂移。从该副本用/usr/bin/swiftc实际编译运行当前核心，389项失败0；GuiCore+GuiApp类型检查无错误。235份非docs文件与副本逐字一致，之后只补本节/剩余文档和证据，没有在验证进行中修改实现，也未重复Rust或Windows Smoke。

439份开始文件全部保留，8份预期修改/431份相同，新增Mac诊断说明1份。原Mac更新器三文件与HEAD一致，既有Mac App摘要不变，git diff --check与白名单检查通过。最终只读本机相关进程名快照见final-evidence.json，本轮验证会话和自有测试文件/进程收口，不操作历史PID或推断远端状态。没有用户VM停机/重启、已有资产删除、宿主网络/卷/ACL变更、实际到期调度、桌面控制、提交推送或交付打包发布；本地既有Mac发行仍0.1.3预览、Windows候选，未查询远端发行。

说明`docs/ctflab-mac-diagnostics-2026-10-29.md`；证据`output/mac-diagnostics-20261029/final-evidence.json`、full-regression-final.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json、core-current.log/core-compile.log/gui-typecheck.log、core-isolated.log/core-isolated-compile.log/gui-isolated-typecheck.log和preservation-final.json。没有新增依赖或放宽Foundation/AppKit/SwiftUI导入守卫；独立副本Python沿用脚本sys.executable，不受目录下python3解析差异影响。真实窗口/保存面板交互、真实脱敏流程和最终包/5人C01/公开反馈仍未验，U02、原43项/G0/G1/graceful_stop_verified及全部开发目标仍未关闭。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第130节和剩余第4节，核验Git/实例并保留全部改动；承接Mac匿名诊断预览与§117—129源码，按原43项继续未关闭开发及收口核对，不把显示快照/核心编译称作实际窗口或用户验收。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/桌面控制/提交推送/交付打包发布；保留原更新器和旧App，公开反馈不能使用原私密完整诊断替代匿名摘要。

## 131. 原43项完成判据审计：离线功能证据、条件范围与C04实现缺口（2026-10-29）

承接第130节。已读AGENTS.md、最新状态/剩余第4节和原backlog的43个唯一任务ID，区分原最小交付、完成判据、显式前置和后续扩展。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持；440份开始文件摘要见`output/completion-audit-20261029/baseline.json`，全部保留，无拉取/切换/清理。

新增`docs/ctflab-completion-audit-2026-10-29.md`及机器记录requirements-audit.json，43项均保留原文、行号、依赖、最小交付/判据、当前责任源文件/摘要/声明符号、结论与下一份所需证据。责任入口存在/AST声明只定位实现，不是功能完成证明。审计没有把未测项划成已完成，不能说所有未闭项都只等用户实机；W05及C04仍有明确实现缺口，E03还有C04依赖与实际验收，A01/A02/A03当前证据也未整体闭环。

S01原最小交付/判据是离线v2解析、DAG/网段/明确资源计划、保留Wintermute v1、全新三节点双网场景不改核心及重复ID/IP/MAC/环路/未知字段拒绝，不含真实启动作为额外离线功能门。用新节点/网络/地址/资源命名的清单实际验证19项：确定DAG与资源预算/代次路径、映射顺序无影响、输入不改、新代次资源区分、不提升资产/隔离声明；每个负向只引入一个错误并核对拒绝原因，尤其重复IP不被重复MAC掩盖；v1解析/计划仍成立。核心拥有文件与开始摘要一致。检查上下文拦截open/Path.open/mkdir/os.open/子进程/socket，未创建真实磁盘/实例/网络或读取用户运行状态，仅审计脚本在上下文外写本轮证据。

19项通过，原S01离线功能判据已可证明；机器记录own_offline_acceptance_proved=true。但原S01所列A02/A03前置未关闭，所以task_fully_closed仍false，不擅自取消依赖、关闭S01整个任务或G0/G1；真实执行/整体停止/恢复属于S03/W03等后续任务。A02历史28组完整Mac参数等价仍是历史证据，本轮未复跑，不据当前策略测试或模块数量新增任务级完成声明。

范围纠偏：R02从R01的Linux远程Runner继承，Mac本机硬配额不是新增硬前置，限制仍需披露；R04是确有课程需要的窄通道，不默认要求任意子网/多跳/默认路由或LAN桥接。E02原文要日志采集/取回，不强制EVTX/跨会话持久导出，C06取证仍独立；C05/C07合法自制样本可满足教学目标，不强迫生产事故或生产WAF。原条件和缺失证据未因此豁免。

最关键的新发现是C04实现缺口：原v2节点字段和当前QEMU驱动没有VMGenID设备及实例/代次/恢复绑定参数；Python实现搜索只发现外部HEALTH名称vmgenid-checked/SYSVOL/NETLOGON及签名收据测试，没有原生域恢复检查器。字符串白名单和恢复收据不等于设备或执行器，不能把C04/E03概括为“只剩实机”。W05最终安装管理引导/版本库布置/迁移/独立入口/安装卸载保留策略也尚未形成最终产品闭环，当前独立管理CLI不能代替原生安装器。

下一安全开发动作：先补C04所需VMGenID声明/设备/代次恢复语义和拒绝错误回放，再准备实际域检查流程（手动或受控探针均可，非强制后台自动化）；最终Server/QEMU/固件和无伙伴恢复仍需实际环境。A02当前完整argv等价复核、C05自制证据从题目到独立真值/调查复盘亦可先做。实际Windows/Linux/合法资产/SSH/外部软件/最终包/课堂/维护责任和反馈入口等缺失不能由代码伪造，本轮不重复索要、不新建外部服务/反馈、不派生代理。

本轮没有重跑第130节完整2038项/独立1177项/Swift389项或真实GUI编译；只新增19项直接审计，以及43项唯一覆盖/原文/源文件摘要/AST定位、显式材料清单284文件存在/无重复/白名单和git diff --check检查。除清单文件新增文档条目外，234份非docs材料源仍与第130节副本逐字一致。没有修改运行实现、降低断言/放宽边界、替换历史失败结果或借新测试条数宣称整体可用。

440份开始文件全部保留，4份预期修改/436份相同，新增审计说明1份。原更新器三文件与HEAD一致，既有Mac App摘要不变。最终本机相关进程名只读快照见final-evidence.json；本轮没有等待中的执行会话/测试实例，不照抄历史PID或推断远端。没有用户VM停机/重启、已有资产删除、宿主网络/卷/ACL变更、实际到期调度、Smoke、桌面控制、提交推送或交付打包发布；既有本地Mac发行仍0.1.3预览、Windows候选，未查远端发行。

证据`output/completion-audit-20261029/final-evidence.json`、requirements-audit.json、s01-direct-evidence.json/s01-fresh-manifest.json/s01-check.log/check_s01.py、domain-symbol-search.log、preservation-final.json；原判据仍为`docs/ctflab-implementation-backlog-2026-10-15.md`，逐项解释见新增审计文档。整体目标、43项任务级、G0/G1和graceful_stop_verified仍未完成。审计已明确下一实现入口，目标保持active，不因为设备/签名缺失就停止尚能进行的源码工作。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第131节、剩余第4节和原43项审计，核验现场并保留全部改动；优先补C04当前缺失的VMGenID设备/代次恢复绑定，不把外部health名称或签名收据当成设备实现。继续全部未关闭开发与原判据验证，不追加无依据硬门；沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/桌面控制/提交推送/交付打包发布，保留原更新器和旧App。

## 132. 连续开发：C04 VMGenID声明、设备与代次恢复绑定（2026-10-29—30）

承接第131节原43项审计，优先补其明确的C04设备实现缺口。已核对现有规划/GenerationStore/QemuDriver/工作器入口、原C04判据和QEMU/Microsoft官方VMGenID说明。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持；441份开始文件摘要见`output/vmgenid-20261029/baseline.json`，全部保留。跨日收口于10月30日，证据目录/说明文件沿用启动日29日，不改写前轮日期或已有日志。

新增`tools/ctflab_vmgenid.py`，v2节点可选`vmgenid=managed-generation-v1`，拒绝auto/原始GUID/布尔值/任意QEMU参数，首版仅x86_64 BIOS/pc路径。没有该字段的原清单保持原计划/参数与无材料行为，不迁移旧实例/v1场景。新GenerationStore只为声明实例排他创建一次0600/32字节vmgenid.key，配置只留模式与材料摘要；材料不进入计划、状态或公开诊断。以私有随机材料HMAC绑定实例UUID/节点/代次和域分离标签，生成RFC4122 v4格式GUID，避免公开UUID5或每次启动auto。重开同代次稳定，reset新代次变化，各节点/新实例区分；旧进度/盘/NVRAM/材料保留，缺失/内容/权限/链接变化拒绝读取，不补发或重新生成。

QemuDriver从实际实例重算绑定，生成唯一固定`-device vmgenid,guid=...`，写入原launch记录；接管核对原计划、磁盘身份、声明与argv。工作器保留原公共池/存储核验顺序，再从实际generation/node/runtime/8位尝试目录重建状态根/计划，位置必须与登记磁盘对应，声明节点还必须属于活动代次；删声明/改GUID/漏设备/重复设备/复制到未登记位置/迟到旧代次均在start.intent与Popen之前拒绝。没有新的客户端任意路径/UUID/设备参数入口，也不热改运行设备。

经过原原生进程身份/TLS/名称绑定的QMP连接，对声明节点追加只读query-vm-generation-id并要求精确值；不支持/不符时关闭连接，拒绝后续控制/显示/状态核验，不改GUID/重试/杀VM。这个证据层只到QEMU报告设备值，guest_guid_verified/domain_health_verified仍false，不能当Windows读取/AD恢复证明。当前QEMU/固件实际是否支持仍须固定运行时验证；没有静默删设备或以进程存活通过。原外部HEALTH名称/签名收据未被改称原生检查器，外部VM生命周期仍留原软件。

官方依据：QEMU specs/vmgenid说明128位标识、启动设置及QMP查询接口；Microsoft virtualized-domain-controller-architecture说明普通重启同值与恢复/克隆变化触发安全处理。链接见新说明，使用当前官方接口核对设计，不替代固定候选运行时/固件的原生证据。GUID变化不会自动创造新域身份，完整状态根拷贝/旧ledger+key回滚、内存快照/live migration不在本实现支持范围；受控冷基线reset或新实例创建才有上述绑定保证，不能据此启动重复域身份或声称安全森林恢复。

新增16个VMGenID测试方法仅用临时状态根、字节基盘、Fake协调驱动/QMP：显式模式/硬件/UUID注入拒绝、私有材料/不泄露、不变/变化边界、重开、reset保留旧进度、材料失效不重建、声明/argv/工作器入口/接管篡改、迟到旧代次、复制/无效尝试位置、QMP不符先关闭。专项16项通过（0.219秒）；原驱动36项35通过/1条件跳过（0.458秒），原公共池存储22项通过（0.498秒）。还按第130节保存源码摘要锁定旧v2模块，用两实例/三代次6组完整计划对照，新旧无声明计划完全相等，未把该结果冒充A02原28组Mac argv对照。

初次专项12项中1项测试误用原排他record来篡改夹具，改为只写本轮临时文件，保留focused-initial.log，没有放宽record。首轮完整2052项1项错误：旧存储精简记录缺argv，新检查先触发KeyError；恢复原存储校验优先级并容纳无声明旧记录，保留full-regression-initial.log，原存储断言不改。随后2053项完整通过，保留full-before-location-guard.log；再用临时状态复现检查器接受复制到未登记同代次目录的声明，保留location-initial-evidence.json（没有真实QEMU），补位置/8位尝试名绑定后再冻结实现验证，不能拿前一2053项当最终源码结果。

最终完整`python3 -B -m unittest discover -s tools/tests -v`2054项，2033通过/21条件跳过（268.722秒）。独立白名单287文件/192 Python语法/85运行时模块/29帮助入口通过，副本1193项，1185通过/8跳过（39.378秒），复制/执行期间无源码漂移，之后仅补交接文档/证据。237份非docs文件与最终副本逐字一致；原Swift/React/Rust源码未改，完整回归包含既有GUI编译/核心，不重复其他专项，不重做Windows Smoke。

本轮441份开始文件全部保留，11份预期修改/430份相同，新增VMGenID模块/测试/说明3份。新模块/测试纳入Mac源文件白名单、离线/恢复材料继承链与集成白名单（桌面运行时由恢复清单继承）；不只在当前tools目录碰巧可导入。原Mac更新器三文件与HEAD一致，既有Mac发布App摘要不变，git diff --check与白名单检查通过。最终本机相关进程名快照见final-evidence.json，所有本轮测试会话已结束，不操作历史PID或推断远端状态。

没有真实QEMU设备/ACPI/Windows/域/SSH/网络或现有实例操作；元数据reset只用于本轮临时字节夹具。没有用户VM停机/重启、已有资产删除、宿主网络/卷/ACL变更、实际到期调度、桌面控制、提交推送或交付打包发布；本地既有Mac仍0.1.3预览、Windows候选，未查远端发行。真实VMGenerationCounter/单DC/全域无健康复制伙伴的连续恢复、SYSVOL/NETLOGON/DNS/时间/安全通道/新认证/课程业务仍缺证据，C04/E03与43项/G0/G1/graceful_stop_verified未关闭。手动或受控域检查均可，不追加后台自动化硬门。

说明`docs/ctflab-vmgenid-2026-10-29.md`；最终证据`output/vmgenid-20261029/final-evidence.json`、full-regression-final.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json、focused-final.log/driver-final.log/storage-final.log、legacy-plan-equivalence.json/check_legacy_plans.py、失败/中间日志与preservation-final.json。第131节审计文档补后续注记，原JSON/源码摘要保留当时快照，不覆盖历史。下一步继续原C04的合法固定Windows设备/域检查准备及W05安装管理整合、A02当前等价复核/C05复盘等其他安全源码工作；目标保持active，缺少实机不抹去其余未完成开发。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第132节、剩余第4节和原43项审计，核验现场并保留全部改动；承接VMGenID可选声明/私有材料/代次GUID与工作器/QMP绑定源码，继续全部未关闭开发，不把设备参数或Mock QMP当Windows/AD恢复证明。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/桌面控制/提交推送/交付打包发布，保留原更新器和旧App；日期已跨至2026-10-30，旧证据目录保留原名。


## 133. 连续开发：W05首次私有版本库设置与原操作恢复（2026-10-30）

承接第132节与原43项审计，补W05仍缺的首轮管理引导源码；本轮已读AGENTS.md、第116/132节、剩余第4节并核对真实入口/调用链。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持。开始444份文件摘要`output/version-setup-20261030/baseline.json`，保留已有修改/未跟踪输入，不拉取/切换/清理。

新`tools/ctflab_version_setup.py`和`desktop/src/VersionSetup.jsx`通过固定Tauri version_setup与原有界版本桥接，首次检查无需预先手工建立manager.json。宿主固定通用local_data_dir的CTFLabData/version-manager目录，界面不可指定数据根；父入口身份未知、版本树内、安装/解释器/工具目录内拒绝创建。用户选择独立核对的发布公钥JSON，预览目录/数量/文件指纹，明确确认后重算原计划/祖先身份，只对不存在的新根排他创建原ReleaseStore、版本树外公钥与固定配置。成功仍零安装/无活动版本/不登记工作区，明确“使用此配置”才接入原版本页。Mac平台保持只读与原更新链；不增加下载/自动启动或任意命令入口。

bootstrap.json保存原UUID/预览/公钥与根身份，store/keys/config各有意图/完成收据；原任务继续只接受同UUID及摘要。已完成项核对实际身份/内容；未知项只能观察，完整且仍空的库或精确文件可补收据，缺失/部分/损坏不重做、不覆盖或清理。无意图的后续步骤仅明确继续时执行。bootstrap.json之前中断留下的未知目录只读保留，不能自动恢复或接管；更广未知应用启动也未因此解决。软件不认证用户选择的发布者，publisher_identity_verified=false，不用文件指纹替代外部信任确认。

19项专项真实临时SQLite/私有文件通过（0.210秒），包括已存在目录保留、公钥与祖先变化、安装目录/未知父入口拒绝、各阶段中断/部分配置/未知不重放、原任务标识、来源消失后原任务继续、正常后续库使用。实际python -I -B子进程验证Mac桥接只读分派，无现有配置也可检查。Windows标签注入只在POSIX临时文件系统运行，非原生Windows/ACL/IPC验收。初次16项1失败为未知普通权限目录被严格私有守卫提前拒绝，改为先查路径链接再返回只读保留；已知设置仍严格核验权限与锁。保留focused-initial.log，修后16项与最终19项通过，不放宽已知库权限。

冻结实现后完整`/opt/miniconda3/bin/python3 -B -m unittest discover -s tools/tests -v`2073项，2052通过/21条件跳过（268.840秒）；独立显式白名单副本1212项，1204通过/8跳过（40.265秒）。291文件/194 Python语法/86运行时模块/29帮助入口通过，复制与运行期间源文件不变。前端npm test 55项、npm run build、Rust1.90 cargo check/test --locked --offline（11项）、单独main.rs格式检查通过；build.rs/Cargo.lock/工具链未变。早期npm误在根目录执行没有形成有效结果，最终使用desktop工作目录记录，不把误执行当通过。没有原生窗口/文件面板/Windows安装卸载验收；普通应用是否作为独立稳定管理入口仍须最终安装布置验证。

新模块/测试/组件/说明纳入Mac源文件、桌面运行时和集成白名单，不只依赖当前tools目录偶然可导入；独立复制没有创建交付ZIP。之后只补文档/保全证据，非docs实现与验证副本逐字核对。原Mac更新器三文件/旧App、开始文件保全与最后本机进程名核验见最终证据；不以历史PID操作或推断远端状态。没有用户VM启停/重置、已有资产删除、宿主网络/卷/ACL变更、真实到期调度、Windows Smoke、桌面控制、提交推送/安装/迁移/交付打包发布。已发布Mac仍0.1.3-preview.20261028，工作区增量未进App；Windows候选。

说明`docs/ctflab-version-setup-2026-10-30.md`；证据`output/version-setup-20261030/final-evidence.json`及baseline/preservation-final.json、full-regression-final.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json、focused初次/修后/最终日志、react-model.log/react-build.log、rust-check.log/rust-test.log。W05最终安装/卸载/离线WebView2/签名、旧库迁移保留/升级回退/干净机和更广未知启动仍缺，不能因源码引导关闭W05。原43项、G0/G1及graceful_stop_verified继续开放；C04原生QEMU/Windows/AD恢复、A02当前28组等价、C05完整调查复盘及其他安全源码工作继续沿剩余第4节推进，缺实机不等于开发全部完成。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，读取AGENTS.md、状态第133节、剩余第4节与原43项审计，核验现场并保留全部改动；承接W05首次设置源码及原任务恢复，继续全部未关闭开发，不把临时POSIX/编译当Windows原生安装验收。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/桌面控制/提交推送/安装迁移/交付打包发布，保留原更新器和旧App。

第133节保全补录：444份开始文件无缺失，12份预期修改/432份相同，新增版本设置模块/测试/组件/说明4份；240份非docs白名单文件与最终独立副本逐字一致。原更新器三文件与HEAD一致、既有0.1.3 App整树摘要不变、git diff --check与白名单检查通过。最后本机进程名快照无QEMU/CTFLabGUI；本轮完整、独立、Rust执行会话均已结束，没有自有常驻测试服务，不能据此推断远端状态。


## 134. 连续开发：A02当前28组完整Mac参数等价补证（2026-10-30）

上一轮第133节已有实际源码进展，本轮继续原审计列出的A02当前证据缺口。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持；读取原A02要求、第58/133节、剩余第4节与真实三处生成器，448份开始文件摘要`output/mac-argv-20261030/baseline.json`。未拉取/切换/清理，保留已有改动及输入。

已从固定Git HEAD直接读取尚未策略抽取的旧ctflab.py/ctflab_scenario.py；原两个源文件SHA256、原字节副本与三个完整函数diff保留本轮output。五份内置profile与该提交逐字一致。实际旧模块在固定可信路径/依赖绑定下生成完整预期，保存为`tools/tests/fixtures/mac-argv-0994f62.json`（SHA256 `3ee65591a407486ec418783900601283b7c2d90c9e8522fee03b250c2ac3cd0e`），正常测试不读取Git、不更新预期，也不以当前代码给自身生成预期。

新增`test_ctflab_mac_argv_equivalence.py`锁定夹具摘要、来源提交、28个唯一case及18/4/6类别和当前profile摘要，并实际调用当前三处builder逐项比完整argv（顺序/固件/磁盘/显示/网络/QMP路径）和端口映射。五profile有头/无头10组、Kali SPICE监听/剪贴板/文件传输8组、安装器自动/交互与有头/无头4组、三场景节点含/不含SPICE6组，28组全部相等。这里是2个测试方法内的28子例，不虚增unittest数量。固定运行时查找/固件/NVRAM/端点/ticket和能力依赖不代表实际资源已准备；绕过LabManager写状态初始化，参数执行期间禁止文件打开/写入/删除、Popen和socket。没有探测QEMU/分配端口/创建ticket/准备固件/启动VM，假ticket仅文件名，无凭据。

专项最终2项通过（0.048秒），原平台11项（0.024秒）、原场景8项（0.009秒）通过。平台测试覆盖错误宿主/来宾组合、注入、显式模拟/硬件要求、不静默降级、不可变计划、无IO/隐式宿主探测、禁用fcntl的独立导入与候选CLI及三处实际接入。Windows/Linux仍candidate-only，runtime_verified=false；该结果不证明WHPX/HVF/KVM、真实来宾/窗口/网络。

本轮只改测试/固定预期、集成清单和文档，原运行器/策略/生成器/profile及React/Swift/Rust实现未变；按影响不重跑第133节完整2073项或不受影响的前端/原生编译，明确保留其历史范围。最终独立白名单源码副本1225项，1217通过/8条件跳过（43.380秒）；295文件/196 Python语法/86运行时模块/29固定帮助入口通过（总45.785秒），复制/执行期间源不变，之后仅补交接与保全。原平台测试及新测试/固定JSON/说明纳入集成FILES，Git只放行该明确JSON，不开放任意资产。没有创建交付ZIP/安装器或重新打包App。

A02原本要求批准Mac参数等价、错误组合拒绝与WHPX只标计划，当前已有直接离线证据，own_offline_acceptance_proved=true。A02所列A01前置的当前逐调用完整归属仍未核对，所以task_fully_closed=false；不擅自取消依赖，不新增真实VM作为A02离线功能门，不因此关闭S01/A03/W01、43项、G0/G1或graceful_stop_verified。§131原审计JSON/源摘要仍为当时快照，文档追加本轮进展，不覆盖历史。

说明`docs/ctflab-mac-argv-equivalence-2026-10-30.md`；直接证据`output/mac-argv-20261030/equivalence-evidence.json`/reference-generation.json/generate_reference.py/reference-ctflab.py/reference-ctflab_scenario.py/three-builder-diff.txt；验证equivalence-final.log/platform-final.log/scenario-final.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json，最终final-evidence.json与preservation-final.json。原更新器/旧App保全及最后本机进程名核验见最终摘要，不操作历史PID或推断远端状态。没有用户VM启停/已有资产删除/宿主网络卷ACL/真实到期调度/Smoke/桌面控制/安装迁移/提交推送/打包发布；Mac实际仍0.1.3预览，工作区增量未进入App，Windows候选。

下一步继续A01当前调用归属、C05合法自制证据的完整调查复盘及其他原判据未闭合开发，C04/W05实机/安装链限制保留；不把所有剩余都归为只等外部资源。接续语：继续`/Users/pufei/Downloads/ctf-lab`，读AGENTS.md、状态第134节、剩余第4节与原43项审计，核验现场并保留全部改动；承接当前28组Mac argv等价补证，沿原边界推进全部未关闭开发，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/桌面控制/提交推送/安装打包发布，保留原更新器和旧App。

第134节保全补录：448份开始文件无缺失，5份预期修改/443份相同，新增测试/固定JSON/说明3份；243份非docs白名单文件与最终独立副本一致。原更新器三文件与HEAD一致，旧0.1.3 App整树摘要不变，Git白名单和diff检查通过。独立执行会话已结束，本轮无常驻测试服务；最后本机相关进程名快照为空，仅代表该次本机观察，不代表远端状态。


## 135. 连续开发：C05日志/PCAP/FAT12、只读学生工作区与完整复盘（2026-10-30）

承接第134节和原43项审计，继续C05明确的源码/复盘缺口。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持；读取真实课程生成器/校验器/统一入口、原C05判据与路线图，451份开始文件摘要`output/evidence-workflow-20261030/baseline.json`。保留全部既有修改、原始资产及旧C05/软件包，未拉取/切换/清理。

新增ctflab_evidence_workspace.py与ctflab_evidence_samples.py，扩展原ctflab_evidence_course.py：保留Web/认证/变更事件，补手工构造6帧Ethernet/IPv4/TCP HTTP PCAP与360KiB FAT12数据卷，CONFIG.TXT维护配置、ACCESS.LOG原日志副本、COLLECT.TXT合成09:04快照标签。没有第三方镜像、真实攻击/捕获或可执行样本，地址/域名均教学用途。来源/时区/覆盖/缺失及同作者非独立佐证限制写入collection.json；FAT目录时间无指定时区，不当UTC实证。新kind=synthetic-offline-evidence-v2/content_version=2，全部11份学生文件按SHA256/长度登记，仍接受旧文本清单，不改旧包。格式参考PCAP工作草案与Microsoft FAT规范，链接见新说明；规范原文未随材料分发。

学生包只含校验、workspace.py、inspect_samples.py、任务/模板和证据，不含生成器/TEACHER/逐条答案；提取白名单函数为独立标准库脚本，不依赖项目或教师模块。由教师另给MANIFEST指纹，明确prepare才在源外新目录创建original/work/reports；原件快照POSIX文件0400/目录0500，可写副本和报告分开；源目录字节/权限不改。Windows仅新文件只读属性，不动ACL且本轮未原生验。独占写入/有限读数/路径与重解析守卫、源身份/内容前后核对；部分失败保留、无完成记录不复用，不覆盖/自动继续或清理。权限可被所有者撤销，tamperproof=false，指纹不认证发布者。inspect只证明快照/权限，不核报告、work或未重查源。

查看器先核整包及外部清单指纹，再有界读取本课PCAP与固定FAT12；拒绝截断/超限/分片/头部/校验和错误、FAT副本变化、循环/交叉链接/不完整簇链/目录/异常大小。不捕获、不挂载或运行镜像，不是通用恶意样本取证工具。教师独立包新增逐条证据复盘，完整8事件排序/原行号、请求/会话/审计关联、PCAP1—6与FAT文件引用、未知/保全/授权/回退/首页及健康分开复验、人工评分建议；与精确学生清单绑定。无自动评分或处置。

实际受控复盘见replay-02：自有临时测试包分别取学生/教师材料到新目录，再按测试清理自有临时ZIP，保留原始材料/全部报告与输出；没有制作交付ZIP/App或覆盖旧包。先只读学生证据，用独立python -I -B执行verify、prepare、样本查看、最终原件检查，按CSV/JSON/Web与PCAP/FAT重建8条事件并写完整调查报告，之后才核教师清单绑定。学生源字节/权限未变、original最终只读与摘要通过，答案未进入学生材料。另从无关目录实际执行统一ctflab_offline.py evidence-course帮助、prepare到另一新自有根及inspect，全通过；只有prepare返回源已重查，后续inspect不冒充源保持未变。

系统独立读者对本轮普通样本文件交叉核对：file识别PCAP2.4/Ethernet和FAT12，tcpdump -r读到6帧且TCP校验和均正确，fsck_msdos -n只读检查3文件/702空闲簇、退出0，输出Warning字样保留。前后两样本摘要相同，无捕获/挂载/卷修复。初次tcpdump按本机时区显示17时，另仅给子进程TZ=UTC得到09时，两日志保留，未改宿主时区。不是Windows/FAT驱动或真实网络验收。

最终专项工作区16项（0.402秒）、样本10项（0.078秒）、原离线14项（0.268秒）通过，含实际学生独立工具、错误pin/变化/链接/重解析、源中途变更、部分写入保留、只读丢失/篡改拒绝、后续源未重查不标未变、教师分离、格式负测及旧文本兼容。初次复盘辅助脚本Unicode bytes字面量语法错误，未执行准备，保留replay_course-initial.py；改编码后通过。第一轮完整2100项已通过，但复核发现inspect把未重查的源误标未变，修字段/增负测/另建replay-02后重冻验证；保留full-before-source-observation-fix.log和replay-01，不用它们冒充最终源码。

最终完整`/opt/miniconda3/bin/python3 -B -m unittest discover -s tools/tests -v`2101项，2080通过/21条件跳过（275.581秒）；最终白名单独立副本1251项，1243通过/8跳过（40.851秒）。300文件/200 Python语法/86桌面运行时模块/29固定帮助通过（总43.408秒），复制/运行期间源不变，之后只补文档/保全。Mac源码与离线/集成白名单纳入新模块/测试/说明，桌面运行时未新增C05页面，不称原生桌面已集成。React/Swift/Rust实现未改，不重复额外前端/原生专项；完整入口仍含原有App/GUI检查。独立副本只是源码复制，无交付ZIP。

C05原离线功能判据（含三类样本、真值任务、只读/哈希/来源/时间、答案分离和可复盘）已逐项直接证明，own_original_offline_acceptance_proved=true，要求/证据映射requirements-evidence.json。当前是自制材料、POSIX和受控自动化报告，不是独立学生/课堂/真实事故或Windows原生证明；不追加生产事故或公开分发为C05原离线门。跨平台G2、独立课堂、正式交付/U03公开分发及维护仍未验；整体43项、G0/G1、graceful_stop_verified继续开放。未自动提交/发布或把代码/测试数当产品完成。

说明docs/ctflab-evidence-workflow-2026-10-30.md，完整调查报告`output/evidence-workflow-20261030/replay-02/investigation/reports/完整调查报告.md`，学生任务与教师逐条复盘分目录保留。最终证据final-evidence.json、requirements-evidence.json、replay-02/evidence.json、frozen-replay-binding-current.json、unified-course-evidence.json、native-formats/evidence.json、full-regression-final.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json、focused-current.log/samples-final.log/offline-final.log与preservation-final.json；早期日志/材料均保留。旧两版C05各两资产与原摘要清单仍相符，原Mac更新器/旧App及最后本机进程名检查见最终摘要，不操作历史PID或推断远端状态。

无用户VM启停/真实SSH/Docker/捕获/挂载/宿主网络卷ACL/到期调度/Smoke/桌面控制、已有资产删除、安装迁移、提交推送/交付打包发布。已发布Mac仍0.1.3-preview.20261028，工作区增量未进入App；Windows仍候选。下一步继续A01当前逐调用归属、A03等价与恢复、更广未知/安装/实际课程和原生证据缺口，不将所有剩余都归为外部资源。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，读AGENTS.md、状态第135节、剩余第4节和原43项审计，核验现场并保留全部改动；承接C05完整自制日志/PCAP/FAT12、只读工作区与实际复盘，继续全部未关闭开发，不把受控POSIX报告当Windows/课堂/发布验收。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/桌面控制/提交推送/安装打包发布，保留原更新器和旧资产。

第135节保全补录：451份开始文件无缺失，8份预期修改/443份相同，新增两个模块、两个测试与说明共5份；247份非docs白名单文件与最终副本一致。原Mac更新器三文件与HEAD一致，旧0.1.3 App整树摘要不变，旧C05/r2的四个ZIP与原清单摘要相符；Git白名单/diff检查通过。完整/独立执行会话均已结束，未另启常驻服务；最后仅按本机相关进程名未见QEMU/CTFLabGUI，不推断其他Python服务或远端状态。


## 136. 连续开发：A01当前平台责任/接口快照与A02前置补证（2026-10-30）

上一轮第135节已有C05实际源码/复盘进展，本轮继续原审计明确未补的A01当前调用归属。正式目录`/Users/pufei/Downloads/ctf-lab`、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持。已读原A01/A02判据、历史基础清单与最新剩余项，沿真实入口/导入/符号调查，456份开始文件摘要`output/platform-ownership-20261030/baseline.json`；保留原始输入/已有改动，不拉取/切换/清理。

新增`docs/ctflab-platform-ownership-2026-10-30.md/.json`和只读开发复核器`tools/tests/check_ctflab_platform_ownership.py`；只改当前盘点/合同/白名单，运行器、原生适配、CLI/GUI和包内运行时实现不变。原六个Python文件加当前本机/桌面/版本入口共14根，本地导入闭包85模块，4份Rust/Swift薄壳摘要；原始22998 AST调用留output，交付JSON列3731平台候选、调用方责任、源位置/表达式摘要及七份逻辑接口合同。候选筛选采用过近似，包含纯构造/辅助方法；不是实际调用图、穷尽所有Python动态行为的证明或原生覆盖率，不用计数关闭产品门。

能力、状态锁、自有进程、私有存储、网络控制、显示、运行时版本七个名称是责任合同，不是凭空新建同名类；60个实际定义/行号/参数从当前源码核对。Mac通用运行链复用QemuDriver并分流Darwin/Linux/Windows观察器，不存在独立DarwinDriver；SQLite工作门在LocalService._transaction/execute，不是gate方法，旧监听预约在prepare_network_resources/PreparedNetworks.ports。26处同名导入逐条按当前函数局部import或全局定义核验，14处动态分派说明固定CLI/本地UI队列/内部Win32函数/上传两动作边界；125处参数调用明示受信代码/测试注入，不把函数合同当JSON授予执行权限或实际nativeprovider证明。来宾、远程、旧Mac与共享本机责任分开，不把导入关系当执行地点或生命周期接管。

合同保留候选/unknown分层、不静默降级、内核锁与遗留意图区分、原生身份/实例代次与自有句柄、未知禁止破坏或重放、原件/旧代次/失败材料留存、监听FD交接与就绪身份、私有UNIX/mTLS控制、显示断开不关VM、有界事务及精确文件集/签名/退出核验。旧Mac专用路径保留；Windows套接字交接/硬件/ACL/显示/持久性与W05最终安装仍未验证，不因接口名或源码分配责任就通过。原Mac更新器不改，新版本管理不替换它。

复核器只读固定JSON/源文件，AST解析不导入被查模块、加载DLL或调用其中API；校验固定快照摘要、85源码/4薄壳摘要、3731调用位置/表达式、60接口符号及参数，AST规范化明确要求Python3.10。新增源码/快照变化会失败，不能自动生成新数字当验收。6项自有临时副本负向检查通过：源字节漂移、快照字节变化、即使更新摘要后的虚假runtime提升、假符号、错行/错责任接口均拒绝。构造器与注入回调是责任边界，不是实际动态派发兼容性证明。

本轮相关已有合同回归98项，97通过/1条件跳过（1.517秒）；包括平台/28参数子例、锁、旧场景资源/运行/服务及共享QemuDriver。跳过为显式无来宾QEMU夹具缺失，没有启动真实QEMU。独立白名单303文件/201 Python语法/86运行时模块存在性、复核器及其帮助/集成工具帮助通过；副本平台11项（0.030秒）和参数2方法/28子例（0.043秒）通过，总1.761秒，复制/执行期间源不变。此阶段不重跑全部Python/前端/Swift/Rust/Smoke；85模块和4薄壳与第135节已验证输入逐字相同，§135完整2101项仅按未变代码引用，不能写成本轮重跑。之后仅补交接/保全，非docs白名单源与副本核对。

盘点辅助初稿曾引用不存在DarwinDriver，实际查入口后更正；链式调用共享起始行列导致ID重复，改完整范围/表达式摘要；原始跨作用域别名搜索过近似，把storage.settings误写成另一名，增加实际定义与局部导入检查后校正。负向辅助脚本Unicode bytes字面量语法失败发生在执行前，改为ASCII测试字节后通过。初稿脚本/JSON/错误日志留output，不改生产实现、不拿初稿当完成证据。最终JSON/工具含固定摘要，说明/快照/复核器均纳入明确白名单。

A01原要求是当前依赖盘点、接口定义与基线/异常语义保留，不是跨平台实现完成；本轮源级交付已有直接证据，承接A02原Mac28组等价/错误组合拒绝/Windows只标计划的证据，A02所列A01源级前置已补。不追加真实硬件为A01/A02规划/纯策略硬门；S01仍有A03前置，A03/W01/W02/真实网络显示课程、43项/G0/G1/graceful_stop_verified保持未关闭。原第131节审计JSON/表为当时快照，追加本轮进展而不覆盖旧源码摘要。后续继续A03端到端同请求/unknown语义、监督与更广恢复、原生/课程/安装链等未关闭开发，不能把它们都归为只等外部资源。

说明`docs/ctflab-platform-ownership-2026-10-30.md`，可复核数据同名.json；证据`output/platform-ownership-20261030/final-evidence.json`、source-check-final.json/standalone-check-final.log、negative-checks.json、previous-evidence-binding.json、raw-call-inventory.json、inventory.py/review.py/各初稿、contracts-final.log、isolated-final-evidence.json/source-files-final.json、isolated-snapshot-check.log/isolated-platform.log/isolated-argv.log及preservation-final.json。最终保全/本机进程名检查见摘要，不按历史PID操作或推断远端状态。

本轮无真实VM/SSH/Docker、宿主网络卷/ACL改动、到期调度、Smoke、桌面控制、已有资产删除、安装迁移、提交推送/交付打包发布；独立副本仅复制源码，未创建交付ZIP。已发布Mac仍0.1.3-preview.20261028，工作区增量未进入App；Windows候选。接续语：继续`/Users/pufei/Downloads/ctf-lab`，读AGENTS.md、状态第136节、剩余第4节与原43项审计，核验现场并保留全部改动；承接A01当前源级责任/接口盘点和A02前置补证，继续全部未关闭开发，不把静态责任快照当原生兼容验收。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/桌面控制/提交推送/安装打包发布，保留原更新器和旧App。

第136节保全补录：456份开始文件无缺失，6份预期修改/450份相同，新增说明、JSON快照与只读复核器3份；248份非docs白名单文件与独立副本一致。原更新器三文件与HEAD一致，旧0.1.3 App整树摘要不变，Git白名单/diff检查通过。相关合同与独立执行会话已结束，未另启常驻服务；最后仅按本机相关进程名未见QEMU/CTFLabGUI，不推断远端或其他服务状态。

## 137. 连续开发：A03原操作账本重开与未知响应（2026-10-30）

承接第136节，在正式目录`/Users/pufei/Downloads/ctf-lab`核对AGENTS.md、第116及最新状态、剩余第4节/原43项审计与真实入口。分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`不变；459份开始文件摘要见`output/contract-reopen-20261030/baseline.json`，保留已有修改与输入，无拉取/切换/清理。

本轮实际复现LocalAdapter在submit已提交意图后OSError仍返回failed的缺口，改为存储/非契约桌面桥接/远程传输异常保留unknown；明确非法输入/权限拒绝保留原语义。新增LocalService原账本只读分页/按原UUID读取响应、本机CLI重开入口和React“已保存操作（历史）”；实例与actor取可信宿主配置/普通进程身份，不允许输入替换，不创建backend/spawn，不领取/重发/取消原操作。原查询接口补持久化cancel查询。响应校验请求摘要/幂等/UUID/公开错误与账本状态；未保存结果返回null，历史旧代次不伪造当前运行事实。说明见[原操作重开说明](ctflab-contract-reopen-2026-10-30.md)。

新增15项专项、5项前端历史模型用例。首轮专项缺常量导入而失败，修正并补响应状态一致性拒绝后15项通过；前端60项与32模块构建通过。另真实启动自有writer进程，将意图提交后注入丢回复并正常退出；新独立-I CLI进程读到原pending操作/无保存响应，查询前后数据库摘要相同，未派发。全过程仅临时真实SQLite/合成后端，无VM/来宾。证据`process-reopen-evidence.json`、history-final.log、frontend-tests.log/frontend-build.log；失败初轮也保留，不冒充通过。

A01原冻结JSON原字节保留为第136节历史，新`ctflab-platform-ownership-2026-10-30-r2.json`重新读取14根/85模块与4薄壳摘要，23087 AST调用/3731候选、26同名导入/14动态分派仍分开；补5个实际账本/包装符号，共65，当前检查器精确固定r2摘要。只读源码责任审查不等于运行绑定/原生兼容证明。

完整及独立源码副本集中回归的最终结果在本节末补录；未完成的验证不提前计为通过。新增React组件、专项/说明和r2快照纳入显式源码白名单；没有创建交付包或更新已发布App。Mac仍0.1.3-preview.20261028，Windows候选；本轮无真实VM/SSH/Docker、桌面控制、宿主网络卷/ACL改动、实际到期调度、Smoke重做、用户资产删除、安装迁移、提交推送或发布。

A03原GUI/CLI语义一致仍需完整入口对照，不能据本轮重开查询就关闭A03或S01前置。长导入取消归W04，真实GUI后台/长期故障、持锁挂起/旧匿名管道/Windows日志接收及原生边界按各原任务核验，不追加Windows实机或这些运行限制为A03独立源码工作的硬门。W05最终安装/独立入口/迁移、更广未知恢复、全部课程/分析器及其他原43项仍按原清单继续，不能概括为全部只等外部验收。G0/G1/graceful_stop_verified与总体目标保持开放。所有旧实例/资产受保护，不能用历史PID接管或清理。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第137节、剩余清单第4节与原43项审计，核验现场并保留全部改动；承接原操作账本只读重开/未知包装及A01 r2快照，继续所有未关闭开发，最后按授权集中验收。沿原边界，不自动停机/删资产/改宿主网络卷/跑到期调度/重做Smoke/桌面控制/提交推送/安装打包发布，保留原Mac更新器和旧App，不把历史响应当当前状态或43项/G0/G1完成。

第137节最终集中结果：完整2116项，2095通过/21条件跳过（283.875秒）；白名单独立副本1266项，1258通过/8条件跳过（41.987秒）。副本307文件/202 Python语法/86运行时模块/30固定CLI帮助通过，新增历史CLI还在真正独立-I进程执行；65实际符号的r2源快照检查通过。前端60项/32模块构建通过，未改Rust/Swift源；完整入口中的既有Swift/GUI编译测试不等于窗口人工验收。完整日志末尾的guest-password FAIL文本是已有缺凭据拒绝负测输出，整套unittest最终OK，不是来宾验收通过。所有跳过保留原原因，没有启动VM或重做Windows Smoke。

最终459份开始文件无缺失，14份预期修改/445份相同；新增React组件、专项、说明及r2 JSON共4份。原A01 JSON、旧C05/C05-r2四个课程ZIP摘要保持，原Mac更新器3文件与HEAD相同，已发布0.1.3 App整树摘要不变；非docs白名单与受测独立副本逐字一致。完整及独立执行会话均已结束，最后按本机相关进程名未见QEMU/CTFLabGUI；不推断远端或其他服务，不操作历史PID。没有新常驻进程，没有交付打包/安装/推送/发布。

最终证据`output/contract-reopen-20261030/final-evidence.json`、preservation-final.json/old-packages-preserved.json、full-final.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json/isolated-source-check.json、process-reopen-evidence.json以及history-final.log和前端两份日志保留。独立副本完成后只补本节等文档，代码输入不变。A03原GUI/CLI整体语义对照及其他原任务继续开放，不能把单项重开功能或测试总数称作所有未关闭开发已完成。

## 138. 连续开发：A03真实事件数组、跨语言对照与裁剪续读（2026-10-30）

上一轮第137节为实际进展，本轮在正式目录`/Users/pufei/Downloads/ctf-lab`继续原A03判据；已读AGENTS.md、第137节、剩余第4节及原backlog，现场分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`不变。463份开始文件摘要`output/contract-parity-20261030/baseline.json`，保留全部已有输入，无拉取/切换/清理。原A03不是长导入/Windows实机的追加前置，W04及原生门分别保留。

真实临时库生成3条事件，独立-I桥接CLI返回数组，原React模型却读取response.events而静默显示空列表，已复现并修复。前端按实际数组严格校验版本/字段/UUID/实例/整数/状态/阶段/重复与缺口，未知形状不再视为空；与Python merge_events的90组同输入实值对照全部一致（29接受/61拒绝）。另修复事件裁剪后反复请求0的位置：只用本次绑定状态快照重定位，清空时间线/提示历史缺口，后续只读新事件。实际本轮自有合成根由过期0定位3，再读显式合成start的新3条到6，数据库只读摘要未变，没有自动重发。

新增7个Python跨语言/跨入口方法；前端八类实际请求构造经Python契约验证，同一临时库CLI JSON/GUI类型化桥接的pending/terminal重试、全合成生命周期/取消、unknown/failed/ready与公开错误一致。合同专项96项、前端66项与32模块构建通过。说明[事件实值与续读](ctflab-contract-parity-2026-10-30.md)明确实际CLI字节/模型/合成后端范围；未操作原生Tauri窗口或真实来宾，不把这些证据写成完整A03产品接入、43项或G0/G1完成。

Python生产运行模块、Rust/Swift薄壳未改，A01 r2仍核对85模块/4薄壳/65符号；两个历史JSON保持，不为本轮模型修改重写旧快照。第137节完整2116项作为未改Python输入的有日期历史结果，本轮不冒称根目录完整重跑；最终独立副本、保全和进程名核验在本节末补录。新增测试/说明纳入源码白名单，前端开发构建不是交付打包。

Mac已发布仍0.1.3-preview.20261028，工作区增量未进入App，Windows候选。A03全部原生产接入尚未作完整证明，W01/W04/W05、真实课程/网络/隔离/安装/用户验收与其他原43项继续开放；不把剩余工作全部概括为只等外部验收，也不将长导入取消等追加为A03独立硬门。G0/G1/graceful_stop_verified仍false。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第138节、剩余第4节与原43项审计，核验现场并保留改动；承接真实事件数组/90组协议对照/裁剪后只读续读，继续全部未关闭开发。沿原边界，不自动停机/删资产/改宿主网络卷/到期调度/重做Smoke/桌面控制/安装迁移/提交推送/打包发布，保留原更新器和旧App，不以源码或合成结果关闭整体目标。

第138节最终结果：合同专项96项全部通过（3.268秒），独立白名单副本1273项，1265通过/8条件跳过（47.324秒）；副本309文件/203 Python语法/86运行时模块/30帮助入口及r2源快照通过，跨语言7个方法在副本中实际执行，未因缺Node跳过。前端66项/32模块构建通过。第137节根完整2116项没有本轮重跑；89份A01绑定源码（85 Python/4薄壳）与那轮受测输入逐字一致，历史结果仅用于对应未改输入。新增协议/事件对照与本轮模型改动以当前96/66/1273及90组实值证据为准，不把历史全量代替本轮验证。

463份开始文件全部保留：8份预期修改/455份相同，新增跨语言测试和说明2份；251份非docs白名单与独立受测副本一致。两个A01 JSON、原Mac更新器3文件、旧0.1.3 App整树及C05/C05-r2四个课程ZIP均保持原摘要，Git diff/白名单检查通过。合同和独立执行会话均结束，无本轮常驻服务；最终按本机相关进程名未见QEMU/CTFLabGUI，不推断其他服务或远端。本轮自有event-fixture根、合成基盘/事件账本与失败初始证据保留，不据其历史UUID/PID操作用户实例；没有真实VM进程或网络/桌面操作。

最终摘要`output/contract-parity-20261030/final-evidence.json`；preservation-final.json、source-files-final.json/isolated-final-evidence.json/isolated-source-check.json、isolated-final.log、contracts-last.log、frontend-last.log/frontend-build-last.log、event-parity-evidence.json/parity-cases.json、cursor-recovery-evidence.json、initial-event-gap.json/actual-event-wire.json及生成/重放脚本保留。独立副本后仅补收口文档，代码不变。所有边界和未关闭开发仍按本节/剩余清单继续，没有为收口停止实例、删资产、安装打包、提交推送或发布。


## 139. 双端UI美化、Windows构建入口修复与Mac 0.1.4预览发布（2026-10-30）

用户要求Mac与Windows更新，并确认优先范围为稳定操作/恢复、拓扑编辑、诊断与Windows安装入口，完整AD/Docker及课堂继续单列；随后要求整体UI美化并复核Apple设计。用户确认暂无Windows原生环境，因此授权先完成两端代码、Mac构建和Windows构建材料。正式目录与分支仍为`/Users/pufei/Downloads/ctf-lab`、`codex/release-0.1.1-preview-20261010`，HEAD仍`0994f620516c49d84badc3a606c1cd5ae4b483d0`。本轮467份开始文件保全，未提交/推送、未覆盖旧App或删除资产。

设计/构建说明见[双端UI与预览交付](ctflab-ui-release-2026-10-30.md)。Mac主窗口改为原生NavigationSplitView，可调整/收起侧栏、详情独立滚动，统一系统字体/语义色/标题与空状态。React实验/拓扑/模板/远程/版本/诊断统一中性色、蓝色强调、线性图标、表单/卡片；新增自动/浅色/深色外观，保留键盘焦点、高对比度与减少透明/动态。依据Apple官方HIG作项目复核，不声称Apple认证或Windows原生Liquid Glass。

版本号统一0.1.4。Windows Build-Windows.ps1从stage返回值独立保留清单摘要，传给probe并在构建后verify，启用PE静态依赖检查，使用每轮独立Cargo target和本轮安装器收集。原清单引用不存在的A01 r3与准备进度说明；前者引用移除，后者依据既有代码/专项证据补录，历史r2不改写、不冒充当前审计。

实际验证：完整`python3 -B -m unittest discover -s tools/tests -v`2133项，2112通过/21条件跳过（298.167秒）；独立白名单312文件/204 Python语法/86共享模块/30帮助入口，1283项1275通过/8跳过（50.009秒）。根全回归期间补齐打包材料清单，独立副本核对最终清单；不把时间上变化的清单宣称为全轮冻结。前端npm test69项和构建通过；Rust1.90 `cargo test --locked --offline`11项通过。之后仅CSS修正系统深色下手选浅色的按钮/高对比度作用域，再构建及浏览器实值复核；Python/Swift/Rust/JS模型与独立受测输入不变，不重复全回归。历史A01 r2源码审计因本轮源变化不再作为当前源码证明，新版本用逐文件发布清单绑定。

Mac App实际构建/签名/许可检查通过，1289个登记文件；86共享模块实际包内导入、20个固定帮助入口通过。最终ZIP独立解压后App树摘要一致、严格签名通过，包内公共CLI在临时目录显示0.1.4。首份交付漏App旁车校验文件，解压核验明确拒绝；补齐后以新最终目录重新打包复验，失败/中间候选保留为build1/build2，没有发布这些候选。Mac仍ad-hoc/未公证。

实际Mac窗口只读检查原生侧栏、空状态及选中已有Kali行后的详情，未点击启动/停止/重置/删除；默认用户根仅只读观察，之后退出本轮窗口。浏览器1280×900检查六导航页面无横向溢出、浅/深外观及模拟系统深色/高对比度下手选浅色的实值；浏览器没有Tauri桥接，远程/版本预览的桥接不可用不当作原生功能验收。未测试全部sheet/原生深色、物理拖动、Windows窗口或真实来宾。

已发布[GitHub预览v0.1.4-preview.20261030](https://github.com/zhangpu1211/ctf-lab/releases/tag/v0.1.4-preview.20261030)。资产包括Mac可执行ZIP、对应源码ZIP、Windows构建源码ZIP及校验；**没有Windows安装EXE**。标签基于既有HEAD，GitHub自动生成的Source code不能代表当前工作区，以独立source-snapshot.zip及SOURCE-MANIFEST.json为准。镜像库新交付目录`/Users/pufei/Downloads/CTFLab-Library/03-软件/CTFLab-0.1.4-preview.20261030`；0.1.3及原Mac更新器保持原摘要。回下载核对结果另补本节末及最终JSON。

本轮没有真实VM/SSH/Docker/域/课堂、硬配额/宿主网络卷ACL、真实到期调度或Windows Smoke操作。Windows原生构建/安装/卸载/签名/干净机/迁移回退仍缺环境与证据；43项/G0/G1/graceful_stop_verified仍未关闭。优先范围的Mac预览与Windows源码材料已交付，不等于整个路线图一次性完成。后续先准备已授权Windows原生构建环境，再固定合法运行时、实际生成/验收安装包后单独发布。

证据目录`output/dual-release-20261030/`：final-evidence.json、ui-evidence.json/ui-light.png/ui-dark.png、full-regression.log、isolated-final.log/isolated-final-evidence.json/source-files-final.json、frontend与Rust日志、mac-build-result.json/final-runtime-evidence.json、archive-roundtrip-evidence.json、post-test-css-change.json、package-evidence.json、published-release.json及回下载材料。没有本轮常驻测试实例；最后进程状态另现场核验，不按历史PID操作。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第139节和双端UI发布说明，现场核验并保留改动。Mac0.1.4预览已发布，Windows仅最新构建源码、无EXE；下一目标为具备原生Windows环境后的构建与安装验收。不要把源码/静态检查当Windows实机，不自动停止VM、删资产、改宿主网络卷或提交推送；发布动作按本次新任务授权执行。

第139节最终发行核验：GitHub于2026-10-30T05:00:23Z（北京时间13:00:23）发布。7项资产已全部实际回下载，与本地、服务端SHA256及镜像库副本逐项一致。最终Mac ZIP为59,600,248字节，SHA256 `9baec3b4e1c2608601f62654e27b2c17d37c6580647e5eda3d9167f612254a5b`；源码ZIP为1,902,389字节，Windows构建源码ZIP为1,902,422字节。App树摘要`3ab00c13516522c4eb20c68aba0348a92f118f9da98335d555f93b0429328d63`。467份开始文件无缺失，旧0.1.3 App和原更新器三文件摘要保持；最后本机进程名未见QEMU/CTFLabGUI/vite，本轮预览服务与窗口已退出，无本轮常驻实例，不推断远端。发布后只补README/教程入口及本节发行收据，源代码不变；源码ZIP内文档为发布前快照。Windows无安装器、原生门与43项/G0/G1仍未关闭，最终JSON及download-verified.json保留实际证据。


## 140. Windows原生构建/安装检查方案准备，待独立CI分支提交授权（2026-10-30）

本次用户明确继续正式目录，目标为Windows原生构建与安装验收，保留改动且不自动停止VM/删除资产。已读取AGENTS.md及第139节，分支仍`codex/release-0.1.1-preview-20261010`、HEAD`0994f62`。新开始快照469份文件见`output/windows-native-20261030/baseline.json`；当前原有源码未变，只追加明确入库白名单与本节记录。

只读现场：本机Darwin arm64，UTM列表仅Basic/Smoke/Linux停止实例，没有Windows；不操作这些实例。GitHub仓库当前公开、Actions已启用，但工作流0、自托管runner0。远端main为`6f434e3d50e5f9b58da94c0b7481a2e9b5086715`，与本地旧HEAD分开记录，未拉取/切换/提交/推送。

已新增[Windows原生CI方案](ctflab-windows-native-ci-2026-10-30.md)、固定Action提交的`.github/workflows/ctflab-windows-native.yml`、`desktop/windows_native_ci.py`、wheel摘要要求及`tools/tests/test_ctflab_windows_native_ci.py`。拟仅向`codex/windows-native-acceptance-20261030`独立分支提交方案所列5文件，不批量提交现有脏工作区，不改默认分支；该分支push触发GitHub临时Windows2025任务。固定0.1.4已发布源码ZIP及完整文件摘要，准备Python3.12.10/Node22.14/Rust1.90及此前固定QEMU，构建NSIS，在本轮云端目录检查实际安装载荷、包内依赖、自有GUI可见窗口/正常退出、卸载及两类应用数据标记保留。只读contents权限，候选/日志保留7天，不自动发布Release或使用签名凭据，不运行VM。

本轮只完成本地准备验证：`python3 -B -m unittest discover -s tools/tests -p test_ctflab_windows_native_ci.py -v`最终12项通过；实际固定源码ZIP`verify-snapshot`验证316份文件。Python语法、工作流解析、分支/只读权限/60分钟限时及4个Action完整提交固定检查、git diff --check通过；证据`output/windows-native-20261030/preparation-evidence.json`、preparation-tests-final.log及source-verification.json。不重复第139节全回归，也不把本机检查当Windows原生验收。

已向用户请求明确批准上述独立分支提交与云端执行，依据AGENTS.md阶段启动第5项对提交/推送的当前授权要求。当前尚未收到该新增批准，**没有提交/推送/云端任务/Windows安装包/原生安装结果**。等待期间不执行依赖批准的操作。旧Mac0.1.4预览及Windows源码材料不变，未重新打包或发布。

即使未来云端自动检查成功，也只证明Windows2025对应路径；Windows11人工桌面/干净机、真实WHPX/来宾显示/课程、升级迁移回退、Authenticode与G0/G1仍独立保留。本轮无自有常驻测试进程/服务，无用户VM/网络/卷/ACL操作或资产删除。后续现场重新核验后按用户回复继续，不从本记录推断批准已授予。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，读取AGENTS.md、状态第140节及Windows原生CI方案；先核对用户是否明确批准仅向独立CI分支提交5文件并启动临时Windows任务。未批准前不提交/推送；保留现有改动，不停止VM或删资产，不将源码/本地测试当Windows验收。


## 141. 已获授权执行Windows独立CI分支（2026-10-30，进行中）

用户已明确批准第140节所列5文件提交到`codex/windows-native-acceptance-20261030`并执行临时Windows构建/自动安装检查；无需重复申请此相同范围。GitHub连接器返回integration 403，改用本机已登录gh完成相同获批范围，无权限扩展。基于远端main `6f434e3d50e5f9b58da94c0b7481a2e9b5086715`创建独立分支，提交`66d7c616ef9e5ac9ac4286caf4f276a9c8b36cf1`逐文件比对恰为5文件；未提交本地其他改动，不修改默认分支，本地分支/HEAD保持原值。

首轮[Windows云端任务41027392700](https://github.com/zhangpu1211/ctf-lab/actions/runs/41027392700)已实际启动，当前进行中，尚无原生构建/安装成功结论。源快照仍固定0.1.4资产，实际环境Windows2025；没有操作本机VM/宿主网络卷ACL或删除资产。运行收据及后续失败/修复/结果写入`output/windows-native-20261030/`。此前第140节“待授权”仅为当时快照，以本节用户批准和实际任务状态为准。候选不自动公开发布，G0/G1等原门不变。

第141节中间进展：首轮Windows基础8项6通过/2非Windows跳过；控制19项因cp1252中文输出1错误。第二轮显式UTF8后19项控制全通过，QEMU固定安装器/主程序摘要通过。第三轮原始stat/fstat字段证实Windows3.12的ctime含义不同；候选清单统一birthtime后3321文件清单通过，设备/inode/大小/mtime/摘要检查保留。第四轮一次性普通用户及非提权/自身配置目录已实际核验，保持原应用拒绝管理员策略；Rust下载完成但入口布置导致拒绝，继续修正。本地Rust入口及runtime_inventory签名已作对应可逆源码修复，未重新打包Mac或发布Windows。CI分支仍仅原授权5文件，通过精确SHA绑定的候选补丁记录源差异；原0.1.4源码ZIP不改。所有失败日志与artifact保留在output/windows-native-20261030/run-01至run-04材料中；G0/G1等未关闭。

第141节续进：第五轮41030623039原生静态检查识别到_msi/_wmi使用的msi.dll/propsys.dll原声明遗漏；按Microsoft系统API要求精确补齐，未将其标成已验证。第六轮41042834586中Python静态报告missing/ambiguous均为空，QEMU则在PE导入目录大小约束处拒绝。第七轮增加逐文件PE原始目录/摘要诊断，继续定位，不跳过检查、不把尚未开始的安装验收写为成功。本地PE10项、准备器16项、desktop_package19项及inventory10项通过；实际日志见对应r6/r7文件。新增PE源码候选补丁与本地源字节核对一致，默认分支、本地HEAD和已发布包未动。

第141节续进2：第七轮41043283214逐文件证据定位libgtk-3-0.dll导入目录108160字节，原解析器把目录容量错误等同描述符数量上限；拆开容量与条目限制，仍最多4097条/强制终止符，PE专项11项通过。第八轮41043610311全部QEMU PE解析通过，又列出9项Windows系统API库声明遗漏，逐项查询Microsoft后补齐，仍为os-contract-unverified。第九轮41043965820进行中；尚无安装器完成结论。失败包/字段/摘要及官方依据保留，不覆盖旧版本。

第141节续进3：第九轮41043965820在普通用户下完成Python/QEMU静态依赖、Rust1.90安装、运行时暂存和包内Python探测，前端69项全通过；Tauri经npm转发时--config丢失，配置路径误入cargo参数而拒绝。以第四份精确SHA候选补丁改为node直接执行锁定依赖的@tauri-apps/cli/tauri.js，原tauri.bundle.json不改；本地四份候选与工作区逐字节核验一致。第十轮41044544057（独立分支提交b7f481639e88e7570dcf8b059a9677a6452c16a9）原生构建/安装检查进行中，尚无安装器或成功结论。开始快照469份均保留，无缺失；八份已有文件发生必要修复/测试/记录变化，见preservation-r10.json。远端main仍6f434e3、本地HEAD仍0994f62。


## 142. Windows原生候选构建与自动安装验收完成（2026-10-30）

本阶段用户已授权5文件独立CI分支及临时Windows构建/安装检查，候选不自动公开发布。最终[任务41044544057](https://github.com/zhangpu1211/ctf-lab/actions/runs/41044544057)于北京时间19:21成功，构建输入提交`b7f481639e88e7570dcf8b059a9677a6452c16a9`。详见[Windows原生CI记录](ctflab-windows-native-ci-2026-10-30.md)。此前各轮失败与原始材料完整保留，不追改成成功。

完成：Windows Server2025真实普通账户校验、固定Python3.12.10/QEMU输入、5625文件运行时准备/静态核对/包内探测、Windows前端69项通过、Rust release编译、NSIS生成、安装后载荷集合与摘要一致、包内Python依赖、精确绑定自有进程可见窗口及正常退出、卸载移除程序、两类应用数据标记保留。Windows基础8项6通过/2非Windows条件跳过，控制19项通过。本地准备器最终17项、PE11项，相关package19及inventory10通过；没有重跑全项目测试或Windows Rust单测的声明。

必要修复保留到工作区：Rust桥接明确UTF8；Windows清单stat/fstat用birthtime统一身份时间并保持其他身份/摘要检查；PE补齐Microsoft系统库部署声明、分离目录大小与4097描述符上限；Build-Windows.ps1直接调用锁定的Tauri node入口避免npm吞--config。独立分支仍仅原批准5文件，四处生产修复以精确SHA候选补丁应用到原固定源码，输出前后摘要及完整候选源。原公开Mac/源ZIP保持原样。

候选持久目录：`/Users/pufei/Downloads/CTFLab-Library/03-软件/CTFLab-0.1.4-Windows-native-candidate-20261030/`，含`CTFLab_0.1.4_x64-setup.exe`（302903771字节，SHA256 `8583d7796dcd231aeec9ca334f18978547af92d810a062f80e4f93ece46b13a2`）、对应候选源码ZIP、说明/校验及证据。安装器未签名，未公开Release。Mac仍第139节已发布0.1.4，无重新打包。

证据：`output/windows-native-20261030/`中的run-10-artifacts.zip（服务端/本地SHA256一致）、run-10-artifacts/三类最终JSON、run-10-full.log、run-10-receipt.json。回下载后仅静态解包EXE的5625 runtime文件，重建清单摘要`0b1312d26a83595c1dbb37cced8618e7ddd0d45dab8ce7309e6331941b326616`与云端独立摘要完全一致；installer-readback-verification.json与reconstructed-bundle-manifest.json保留证明。stage-result中installer_built=false是暂存阶段原值，最终结果看completion/installation/installer三记录，不篡改中间证据。四份候选源与本地字节一致；候选源码ZIP317项（316源文件+清单）独立回读一致。

未完成门槛：Windows11人工桌面/干净机与全部UI、真实WHPX/来宾/网络/课程、旧版升级迁移回退、Authenticode及G0/G1。云端可见窗口不等于完整人工操作或真实来宾验收；43项路线图未整体完成。下一阶段应在授权的Windows11环境完成这些实际验收，再单独决定签名/公开发布。

保全：正式目录`/Users/pufei/Downloads/ctf-lab`，本地分支仍`codex/release-0.1.1-preview-20261010`，HEAD仍`0994f620516c49d84badc3a606c1cd5ae4b483d0`；开始469份文件无缺失，已有工作区未整体提交。远端main仍`6f434e3d50e5f9b58da94c0b7481a2e9b5086715`，仅独立CI分支更新。收尾只追加文档/一项准备器源漂移测试，以skip-ci提交避免重复同包构建，实际构建提交仍以上述SHA为准。本轮本机进程名只读核对未见QEMU/CTFLabGUI/ctflab-desktop；没有启动/停止用户VM、删除资产或改本机网络/卷/ACL。云端一次性普通账户/根仅用于本轮临时主机，任务已结束，没有需后续操作的持久测试实例或可复用PID。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md和状态第142节并保留改动；Windows0.1.4原生未签名候选已完成Server2025自动安装/窗口退出/卸载及数据标记保留验收，本地候选目录见本节。下一步完成授权Windows11人工/真实来宾与升级迁移回退验收；不自动停止VM、删资产或公开发布，不把云端窗口检查当完整Windows11/G0/G1。

第142节最终保全收据：独立CI分支收尾提交`7dad06a48be822ed196234ad5e92a46045bed876`仅文档/源漂移测试变化（skip-ci），与main累计差异仍精确为获批5文件；实际构建/安装测试提交仍b7f4816。本地分支/HEAD、远端main再次核对保持原值，469份开始文件均在；镜像库交付清单全部文件逐项复验通过，git diff --check通过，本机只读进程名核对仍未见上述VM/App。本轮最终机器可读收据为output/windows-native-20261030/final-evidence.json，无候选公开发布。


## 143. Windows11实机验收入口核验，等待目标环境选择（2026-10-30）

用户继续第142节，要求推进Windows11实机验收，保留改动、不停止VM/删资产/自动发布。正式目录与本地分支/HEAD保持第142节值。本轮仅只读调查与补验收材料；没有恢复、启动或停止任何VM，没有安装/卸载候选，没有提交/推送/重新打包/发布。

现场发现：本机Darwin arm64，Parallels中“Windows 11”确实存在但为suspended，CPU type=arm、6核/8192MiB，Tools20.4.1-55996；另一个Parallels实例也暂停，不接管。UTM三个实例停止，VirtualBox仅Smoke且无运行实例。本轮结束再次查询Parallels两实例仍暂停。ARM环境只能单列安装/界面兼容性，不能替代Intel/AMD Windows11 x64/WHPX。没有收到后者连接入口。

本地候选EXE302903771字节，SHA256重新现场核对仍为8583d7796dcd231aeec9ca334f18978547af92d810a062f80e4f93ece46b13a2。第142节Server2025成功记录仍是历史实际结果，本轮没有重跑，不冒称Windows11实机已通过。

已通过异步问题请求选择：提供已授权Intel/AMD Windows11入口，或明确授权恢复本机ARM Windows11只验安装/界面，或只准备材料。截至本节写入尚未收到选择。当前缺失信息实质决定验收平台及是否恢复个人暂停实例，不能推断第142节临时云端授权覆盖此台个人VM。依据AGENTS.md“阶段启动”第3/5项，等待选择后才执行依赖该环境的操作，无需重申请已批准的旧云端范围。

独立工作完成：修正学生教程首页过时“没有EXE”说法，明确公开源材料与本地未公开候选区别；准备output/windows11-acceptance-20261030/的environment-discovery.json、验收阶段.md、第一阶段-只读环境核对.ps1。脚本仅核对显式文件摘要并显示系统/CPU原始架构码/提权状态/相关进程计数，不写文件、不安装、不操作VM、不输出用户名/机器名；没有Windows运行证据，本机无pwsh，明确未完成PowerShell原生语法/执行检查。不把材料准备计为实机验收，不重复源码全回归。git diff --check通过。

下一步：收到目标选择后先跑只读环境/普通用户/既有安装数据检查，再给一份下一阶段操作或在获准目标内执行；不默认停止当前或测试VM、不覆盖旧版本/资产、不重复历史已验收Smoke，不自动进入卸载或迁移破坏性操作。Windows11人工/真实来宾/升级回退、签名及G0/G1仍未完成。

接续语：继续/Users/pufei/Downloads/ctf-lab，先读AGENTS.md和状态第143节。候选摘要已复核，本机Parallels Windows11是暂停的ARM实例；先核对用户是否选定Intel/AMD入口或明确授权恢复ARM兼容性测试，再运行依赖环境的验收。保留改动，不停止VM、删资产或自动发布。


## 144. Windows11 ARM候选安装与基本界面兼容性验收完成（2026-10-30）

用户明确批准恢复本机Parallels“Windows 11”，先做ARM上的安装/界面兼容检查；其后检测到并发状态变化，再次明确交接“现在交给你继续验收，我不再操作这台虚拟机”。正式项目仍/Users/pufei/Downloads/ctf-lab，本地分支codex/release-0.1.1-preview-20261010、HEAD0994f620516c49d84badc3a606c1cd5ae4b483d0不变。本轮生产源码四文件与第142节实际候选源仍逐字节一致，没有新源码/包构建、提交/推送/公开发布。

环境：Windows11专业版ARM，版本10.0.22000.2176，当前桌面用户未提权且非SYSTEM；恢复前没有CTFLab登记/相关数据、CTFLab或QEMU进程。固定未签名x64安装器本地及来宾复制SHA256均8583d7796dcd231aeec9ca334f18978547af92d810a062f80e4f93ece46b13a2，302903771字节。通过既有Mac共享复制，不新增共享权限。中文NSIS实际成功，安装在`%LOCALAPPDATA%\CTFLabAcceptance\20261030-arm-01\app`，系统登记0.1.4；默认CTFLab目录没有新增安装。未覆盖旧安装或数据，不执行卸载。

实际验证：来宾独立参考清单摘要0b1312d26a83595c1dbb37cced8618e7ddd0d45dab8ce7309e6331941b326616匹配，5625份安装runtime文件数量/摘要全一致，无mismatch。包内Python3.12.10实际导入ssl/tkinter/yaml6.0.3/cryptography46.0.5，路径限制在随包Python内；四个包内桥接入口desktop_bridge/client_store/version_bridge/desktop_remote的--help均0退出。帮助仅证明入口加载，不当作业务操作验收。

界面：助手实际观察安装成功、实验页、网络拓扑页和最终“诊断与支持”页；模拟鼠标/按键未能可靠送入来宾，未使用其他UI自动化技术绕过。用户按集中步骤实际操作并明确回传“全部正常，已停在诊断页”：模板/远程/版本/诊断页均出现，深色/浅色/自动切换正常，缩小窗口再恢复后导航/输入框/按钮可见。该部分记为用户人工回传，不宣称助手自动逐控件验证或真实实验可用。

环境异常保留：20:31与20:43虚拟机日志收到DspCmdVmSuspend；本轮未显式发送暂停/停止命令，发起者未定位；曾有一次恢复因已运行而被拒绝。配置确实启用Pause idle及PauseIdleVMTimeout30，但不足以证明上述中止原因，未改电源/网络/共享/ACL。按现有授权恢复同一实例继续，未发送暂停/停止/重启/关机命令。首次窗口消失与并发/显示状态未能分离，事件日志未找到对应CTFLab崩溃，不能直接认定产品崩溃或完整稳定性通过。长EncodedCommand触发Parallels传输空间不足，保留失败现场，改749字符短命令后实际完成5625文件核对；原生脚本执行策略Restricted保持，未修改策略。

结果限于现有ARM设备上的x64候选安装与基本UI兼容性通过。Windows11 Intel/AMD x64/WHPX、真实来宾/网络/课程、全部业务、诊断导出、旧版升级迁移回退、ARM卸载/正常退出/长时稳定性、签名及G0/G1仍未验收。第142节Server2025的卸载/正常退出是当轮证据，不转移为本机已测。

证据与恢复入口：output/windows11-acceptance-20261030/验收结果.md、final-evidence.json、host-preflight.log、candidate-copy.log、installed-preflight.log、audit-compact.log、installed-python-probe.log、installed-help-probes.log、final-live-state.log，以及中间失败/暂停诊断材料。截图含私人桌面背景，仅本地保存，不入库或公开分享。没有改候选镜像库原交付清单，原资产保留；没有全项目单测重跑，本轮为实际设备检查及文档更新，git diff --check通过。

最终现场：Windows11保持running，另一个Parallels实例仍suspended；CTFLab实际安装路径与启动时间再次绑定，标题“CTFLab · 实验台”、Responding=true，QEMU进程数0。应用与VM留在运行状态供复核；两类实验/远程数据根仍未创建，未导入真实实验、删除资产或停止VM。不根据本轮PID做以后操作，后续需重新采集身份。

接续语：继续/Users/pufei/Downloads/ctf-lab，先读AGENTS.md与状态第144节。Windows11 ARM上的0.1.4 x64候选已完成安装/载荷/Python/基本UI兼容性；用户人工页面与外观/缩放回传正常，VM和App保留运行。下一步应选择授权Intel/AMD Windows11做x64/WHPX及真实来宾验收；若继续ARM业务诊断需明确范围，保留现场，不停止VM、删资产或自动发布。

第144节收尾复核：最终文件保全469份无缺失，git diff --check通过。收尾再次发现VM处于suspended，未定位发起者；按已有恢复授权恢复同一实例，新的final-live-state-after-resume.log确认应用仍为原路径/同一创建时间、Responding=true、QEMU0，VM现场再次核对为running。暂停事件汇总suspension-events-final.log已保留；不能把安装/基本UI通过扩展为宿主/来宾持续稳定性通过。没有改变自动暂停设置、停止VM或删除资产。


## 145. 同机VMware外部Kali接入设计完成（2026-10-30，设计阶段）

用户澄清目标：同一台Mac或Windows电脑，保留VMware中已安装的Kali，使其与CTFLab管理的靶场网络互通；随后明确要求编写设计方案。本轮仅设计/资料核验/文档，不实现接入、不修改VM或任何网络/权限、不运行扫描、不重新打包/提交/推送/发布。既有源码、候选包及资产保留。

已落地[同机外部Kali二层接入设计](ctflab-external-kali-l2-design-2026-10-30.md)：普通用户宿主中转+固定SSH帧协议+Kali专用TAP/网络命名空间，提供隔离实验终端；不在宿主装TAP/Wintun，不桥接物理网卡。VM生命周期归VMware；首版一台Kali/一个预留实验网段，IPv4/ARP/服务扫描与明确的靶机回连。现有v1服务/IP通道不冒充完整二层接入，协议与资源权限新增设计单列。

实际调查确认两种网络入口不同：ctflab_network回环交换机与qemu_driver首节点内部hub/二成员直连必须分别适配。设计要求生产计划准备时预留外部槽位；未预留的运行中旧实验不热接入、不自动停机。文档给出权限助手/SSH密钥限制、身份/代次/策略绑定、帧门禁/配额、断线与残留命名空间语义、双端UI、10—17有效开发日条件估算及实机验收矩阵。时间和限额均为设计目标，不是当前能力或交付保证。

核验来源为项目真实调用链，以及Linux TUN/TAP、network_namespaces、OpenSSH sshd_config、QEMU官方参数文档，链接在方案对应段落。原QEMU设备文档首次读取超时，随后官方参数与网络文档检索取得；未依赖第三方教程。不把规划或官方基础能力当项目实机证据。

文档链接、两段Mermaid围栏/引用路径及git diff --check核对；没有产品代码变化，不重跑单测或旧设备验收。本地分支/HEAD仍codex/release-0.1.1-preview-20261010、0994f620516c49d84badc3a606c1cd5ae4b483d0。只追加该设计文档的gitignore精确白名单与本节，未检查/操作现有VM新状态；第144节实例状态是当时收据，后续操作必须现场重新核验。

下一步若进入实施：先A接入契约，再B专用Linux真内核端点原型和保全验证，再集成两类宿主网络、双端UI及两平台集中实机验收。需实际指定专用测试Kali/测试网络并授权助手部署后，才进行对应环境操作。接续语：继续/Users/pufei/Downloads/ctf-lab，读取AGENTS.md、状态第145节与外部Kali二层接入设计，保留改动；按本次明确的实施范围推进，不停止现有VM、删除资产、桥接物理网络或自动发布。

## 146. 外部Kali二层接入实现（2026-10-30，阶段A—D源码完成，实机验收保留）

依据[同机外部Kali二层接入设计](ctflab-external-kali-l2-design-2026-10-30.md)完成阶段A—D实现；先建[剩余工作矩阵](ctflab-remaining-work-matrix-2026-10-30.md)后立即实施。本轮全部为本地合成/回环验证，未操作任何现有VM、未在真实Kali内部署助手、未改宿主网络。分支`codex/release-0.1.1-preview-20261010`、起点HEAD`0994f62`不变；所有改动未提交、未推送、未重新打包、未发布。

**已实现**：A接入契约`tools/ctflab_external_attach.py`（登记/绑定/静态预约/槽位规划/策略摘要/HMAC挑战/私有意图存储，旧格式保持原语义）；B帧协议`tools/ctflab_external_l2.py`（记录编解码上限前置拒绝、FrameGate白名单与双向MAC/IP绑定、TokenBucket/广播桶/字节时长配额）+Kali助手材料`tools/ctflab_kali_attach.py`（root daemon窄子命令+专用账户client+SCM_RIGHTS传TAP fd+setns建TAP+降权shell，sshd固定ForceCommand片段与systemd单元，材料只生成不安装）；C宿主集成：`ctflab_network.py`交换机认证外部接入口（AUTH/CHALLENGE/TOKEN/READY单会话、ingress/egress门禁、计数入状态）、`ctflab_qemu_driver.py`hub预留external listen口（三成员/二成员旧格式回归保持）、`ctflab_remote.py`固定入口`ctflab-external-l2-v1`、中转`run_relay`（switch认证/hub裸连两模式，可注入时钟/通道/等待）；场景v2网段可选`external`槽位含全局查重。D界面：桥接`external-attach-status/save/clear/materials`四动作（均无VM副作用）、React`ExternalAttach.jsx`卡片+模型8项测试、Mac`MacExternalAttachCard`+`MacExternalAttachSummary`（8项新检查），连接按钮在实机验收组合通过前显式不提供（`connect_supported=false`）。

**验证（2026-10-30本机macOS/arm64）**：新增单测43项（attach 17、l2 15、kali 6、桥接5）通过；交换机接入口回环冒烟（合成ARP）：双向gated转发、未登记源/伪造源/错误令牌/第二会话拒绝、门禁计数落盘。React 63项+构建、Swift类型检查与397项检查（0失败）通过。首轮完整回归曾出现3处失败，均为真实回归或边改边跑产物：qemu_driver三成员整数端口误放行（已修，恢复旧契约）、windows基础验证包隔离副本缺`ctflab_external_attach.py`（已补FILES）、scenario_v2中间态（当时修毕）。最终完整回归结果见本节末补记。

**未验证（实机门槛）**：真实Linux内核TAP/netns/SCM_RIGHTS/异常清理与原管理网保全；Mac+Fusion+Kali ARM64与Windows11 x64+Workstation+Kali x64端到端；两类后端真实帧往返；扫描吞吐/SSH队头阻塞/2小时会话/睡眠暂停恢复/快照重连；Parallels/UTM/VirtualBox身份组合与图形工具真实netns归属。均记录于[验证记录](verification-external-attach-2026-10-30.md)与矩阵，不因代码完成宣称可用。U04维护责任、W06课堂等条目维持矩阵原状。

**最终完整回归（2026-10-30，树稳定后）**：`python3 -m unittest discover -s tools/tests` 共2197项：2196通过、21条件跳过、1失败（`test_verification_records_are_dated_snapshots`要求验证记录含"不替代当前软件状态"标记；该失败发生在标记补写之前，属文档守卫，修复后单独复跑该守卫7项通过，代码在回归期间未再变更）。桌面`npm test`77项通过（含新增8项）、`npm run build`成功；Swift类型检查通过、397项检查0失败（含新增8项）；270个Python文件ast.parse无错误；`git diff --check`干净。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、状态第146节、剩余工作矩阵与 verification-external-attach-2026-10-30.md，核对 Git 与文件实际状态，保留已有改动。外部Kali接入阶段A—D源码与本地合成验证已完成；下一步需用户指定专用测试Kali/宿主组合并授权助手部署后做实机验收（阶段E），或继续推进矩阵中其他可实施项。不要自动停止现有VM、删除资产、在真实Kali内部署、桥接物理网络、提交推送或发布。

## 147. 外部攻击机接入规划链贯通与CLI入口（2026-10-31，同分支，实机验收仍保留）

接第146节继续E01可实施收尾，全部为本地合成/回环验证，未操作任何VM、未部署助手、未改宿主网络。分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f62`不变；改动未提交。

**完成**：①hub后端生产链闭合——`ctflab_desktop_bridge.import_course`为声明external槽位的网段分配预留口（二成员自动转hub规划），修复槽位被静默丢弃；`validate_hub_networks`反向强制"声明槽位⇒端口规划必须携带预留口"，并修复external端口双重计入导致的端口碰撞（首次回归以resource-busy暴露）。②连接凭据修正——CLI `connect`改用独立`--ssh-config`（完整ctflab_remote schema），新增`bind_ssh_config`绑定`server_uuid==登记node_uuid`并fail-fast预检固定入口`ctflab-external-l2-v1`；修正此前"契约级ssh引用直接传入FrameChannel必然失败"的缺陷。③CLI入口——`ctflab external-attach materials|check`子命令（只读/仅新材料，私有JSON按0600约定）。④生产路径结论——CLI `scenario prepare`仅接受v1清单（按设计保持原样）；生产v2路径走hub后端；交换机认证口由测试与显式编排消费，不是缺口。

**验证（2026-10-31）**：`test_ctflab_external_attach`20项（新增3项ssh绑定：匹配通过/错server_uuid拒绝/缺字段拒绝）；`test_ctflab_desktop_bridge`36项（新增import槽位预约贯通：outer二成员带槽位转dict携带external、inner保持int、全局端口唯一）；CLI冒烟（materials生成、check正反向与摘要输出）通过；桌面`npm test`77项＋构建通过；`test_ctflab_kali_attach`6项、`test_ctflab_external_l2`15项、`test_ctflab_desktop_external_attach`5项、文档守卫7项复跑通过。**最终完整回归（2026-10-31，树稳定后）**：`python3 -m unittest discover -s tools/tests` 共2201项：全部通过、21条件跳过（316.7秒，EXIT=0）。桌面`npm test`77项通过、`npm run build`成功。

**未验证**：与第146节实机门槛清单相同（真实Kali/宿主组合、真内核TAP、两后端真实帧往返、性能故障矩阵、图形工具netns归属）；连接按钮仍显式未启用。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、状态第147节、剩余工作矩阵（含2026-10-31增补）与验证记录增补节，核对 Git 与文件实际状态，保留已有改动。外部Kali接入A—D及规划链贯通已完成；实机验收（阶段E）需用户指定专用测试Kali/宿主组合并授权助手部署；其余规划项按矩阵推进。不要自动停止现有VM、删除资产、在真实Kali内部署或改其网络、桥接物理网络、提交推送或发布。

## 148. 外部攻击机连接链、身份策略与合成端到端验收（2026-10-31，设计可实施项全部完成）

按用户目标"完成设计方案所有未完成的，然后整体验收"，本轮落地外部Kali二层接入设计中剩余可实施项（同分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f62`不变；全部本地合成/回环验证，未操作VM、未部署助手、未改宿主网络、未提交推送）。

**完成**：①五族来宾身份策略（`GUEST_IDENTITY_FAMILIES`：VMware/Parallels/UTM-QEMU/VirtualBox/Hyper-V），`validate_registration`强制命中并派生`identity_family`，策略外拒绝——不关闭身份检查；②桥接连接/断开动作链（设计§8/§9）：connect按前置条件（登记有效＋本代次profile预留口＋无进行中会话）开放，派生`external-relay`监督进程并持久化会话记录；disconnect按命令行身份核验终止（非裸PID），状态机idle→connecting→connected→disconnected/unknown，进程消失惰性落unknown、允许显式清除/重连；断开不停VM不杀工具；③合成端到端验收`test_ctflab_external_attach_acceptance.py`（设计§12首项的合成等价）：真实交换机+认证接入口+中转帧泵+来宾替身——双登记节点发现、ICMP服务访问、靶机回连经回程门禁到达来宾、受控断开后`frames_out`归零而内部A→B转发继续、伪造源MAC发现帧中转门禁丢弃零送达（未知单播洪泛按标准L2语义断言）；④React卡片连接/断开按钮（canConnect/canDisconnect前置门控）+"诊断与协议"展开区（协议/身份家族/预留口/限额/策略摘要，无宿主路径凭据）；Mac`sceneGenericCall`直读同一桥接状态，卡片实时渲染。

**验证（2026-10-31）**：新增/更新测试——attach 20项（含身份策略）、桥接attach 11项（身份策略3+会话链4+既有4）、E2E验收2项、React模型11项（会话/诊断门控3项新增）；**完整回归`python3 -m unittest discover -s tools/tests`共2209项全部通过、21条件跳过（355.6秒，EXIT=0）**；桌面`npm test`80项+构建通过；Swift类型检查通过、397项检查0失败；270个Python文件ast.parse无错误；`git diff --check`干净。

**E01剩余收敛为纯实机门槛**：真实Kali内核TAP/netns/助手部署与原管理网保全；Mac+Fusion+Kali ARM64与Windows11 x64+Workstation+Kali x64端到端；真实SSH吞吐/队头阻塞/睡眠恢复；图形工具netns归属。连接链在真实环境验证前可用，连接目标须为已授权测试实例。其余43项规划状态见剩余工作矩阵；G0/G1仍未通过。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、状态第148节、剩余工作矩阵与验证记录（含两份2026-10-31增补），核对 Git 与文件实际状态，保留已有改动。外部Kali二层接入设计内可实施项已全部完成并通过合成端到端验收；剩余为纯实机门槛（需用户指定专用测试Kali/宿主组合并授权助手部署）。不要自动停止现有VM、删除资产、在真实Kali内部署或改其网络、桥接物理网络、提交推送或发布。

## 149. zcode交付独立核验（2026-10-31，发现实现缺陷，未实施修复）

用户要求核验外部Kali及此前剩余规划“已经完成”的说法。本轮核对真实源码/生产入口、状态第146—148节、剩余矩阵和验证记录，保留所有改动；分支与HEAD仍为codex/release-0.1.1-preview-20261010、0994f620516c49d84badc3a606c1cd5ae4b483d0。

结论：新增代码和合成测试属实，但“可实施项全部完成、仅差实机”不成立。独立发现并复现TAP recvmsg列表参数TypeError、生产空节点白名单拒绝合法流量、终止失败仍落已断开、来宾信号回调AttributeError、重复序号未拒绝和Windows路径门控不兼容；另核对SSH会话材料不贯通、实际来宾身份握手缺失、专用shell缺输入转发以及Mac卡片只有展示。详见[独立核验记录](verification-independent-review-2026-10-31.md)，这些是源码/材料缺口，不能全部归为环境门槛。

本轮受影响Python54项通过（37.643秒，含unclosed socket警告）、前端80项通过、Swift类型检查退出0、git diff --check通过；没有重跑全仓2209项或Swift397项，旧结果不冒充本轮证据。针对性复现与前端/Swift日志位于output/independent-review-20261031/；所有复现无特权、不操作VM/真实进程、不更改网络。

其余43项不能认定全部完成：当前矩阵仍明确大量证据/条件缺口、G0/G1未通过；本轮没有逐行审计其余全部模块，不宣称它们实现已全部正确或全部缺失。第146—148节均未重打包，新工作区能力不等于已发布App/原Windows候选已更新。

仅新增核验记录、本节与记录的精确gitignore白名单；未修产品实现、未部署助手、未操作现有VM、未改变网络、未提交推送、未打包发布。未重新查询现有VM运行状态；此前状态不能用于当前控制。

接续语：继续/Users/pufei/Downloads/ctf-lab，先读AGENTS.md、状态第149节与verification-independent-review-2026-10-31.md，保留所有改动。先按独立核验修复外部接入生产/材料/双端UI缺陷，再补验证并逐项核对剩余规划。修复需本次明确任务；不要自动操作现有VM、部署来宾助手、删除资产、改真实网络或发布。

## 150. 独立核验九项缺陷逐项修复（2026-10-31，缺陷关闭轮）

第149节独立核验确认9项生产缺陷（8×P1、1×P2）；本轮全部修复并补"生成脚本真函数/生产装配/复现回归"测试。分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f62`不变；改动未提交。逐项修复位置、验证命令与证据见[缺陷修复验证记录](verification-external-attach-fixes-2026-10-31.md)（核验报告原文保留，仅补文档守卫标注）。

**关闭摘要**：①TAP描述符交接拆为send/receive_descriptor（recvmsg整数缓冲、单SCM_RIGHTS校验、dup所有权、waitpid回收、失败清理），真函数测试含真实fork失败分支；②生产白名单`derive_allowed_macs`从实例计划派生并强制非空，验收测试改为生产装配同源；③SSH固定入口去`%i`，会话经数据面HELLO/VERIFY握手（会话UUID+32hex挑战），安装说明改`/bin/sh`并说明nologin不兼容；④握手核验实际来宾身份（助手摘要+machine_uuid，null→显式degraded-verified绑定，不匹配拒绝）；⑤connected后置到握手完成（on_ready），disconnect fail-closed（kill失败/超时未证实→unknown+disconnect_failure，unknown可重试），会话更新合并防覆盖，代次变化停泵；⑥shell按连接fork双向stdio+降权，daemon不阻塞；⑦Mac卡片补登记/网段/连接/断开/材料/实验地址/终端/恢复说明（同桥接契约，无宏依赖）；⑧Windows路径跨平台判定贯穿React模型/JSX与后端契约，歧义相对路径拒绝；⑨SIGTERM改Event、来宾序号严格递增（重复/回退/跳号断开）、30s租约清扫+退出回收、status如实报告tap_fd_alive与"客户端关闭≠撤网"、宿主10s心跳。

**验证（2026-10-31）**：专项套件全绿（attach 23、桥接attach 13、kali 7、kali函数 10、l2 15、E2E验收 2、desktop_bridge 36）；完整回归2224项：2223通过/21条件跳过/1失败（核验报告缺文档守卫标注，保留下补注后守卫7项单独复跑通过，代码未再变更）；桌面81项+构建；Swift类型检查+397项。核验报告"非穷尽清单"提示的并发保存/连接竞态与长时运行仍未深查，不作通过声明。

**候选材料**：`output/candidate-materials-20261031/`（桌面前端bundle+26个源文件SHA-256清单+MANIFEST.json+打包说明）；Mac App重打缺运行时输入（runtime-root/Python包不在环境），Windows安装包需Windows/Rust工具链——均为环境门槛，未重打、未发布。

**其余规划**：仍按[剩余工作矩阵](ctflab-remaining-work-matrix-2026-10-30.md)逐项状态执行；本轮未再有"只差实机"的概括——实施缺口（如A03完整入口对照、T02执行模板门、W05可离线部分、U04需用户决策）与实机/资产/人员门槛在矩阵分列，后续按矩阵逐项推进。

接续语：继续 CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先读 AGENTS.md、状态第150节、`docs/verification-external-attach-fixes-2026-10-31.md` 与独立核验报告，核对 Git 与文件实际状态，保留已有改动。九项核验缺陷已逐项修复并有复现回归；剩余：矩阵中其他实施缺口（A03对照/T02/W05/U04）与实机门槛（需用户指定专用Kali/宿主并授权助手部署）。不要自动停止现有VM、删除资产、在真实Kali内部署或改其网络、桥接物理网络、提交推送或发布。

## 151. 修复交付第二轮独立核验（2026-10-31，仍不通过）

用户要求再次核验。核对第150节源码和候选材料：原recvmsg参数、生产空白名单、kill抛异常落unknown、Mac按钮、Windows路径及来宾序号确有修补，但“九项全部关闭”仍不成立。执行生成助手真函数与真实Unix socketpair，verify后同连接attach触发BrokenPipeError；另外复现空闲心跳整数payload触发ContractError、SIGCHLD在WNOHANG返回0时自旋、收到SCM_RIGHTS后多dup导致FD泄漏、宿主接受重复序号。生产会话准备/setup材料与实例/代次/策略绑定仍未闭环。详见[第二轮独立核验](verification-independent-review-r2-2026-10-31.md)。

本轮专项Python69项通过（40.478秒，含socket资源警告）、前端81项通过、Swift类型检查退出0。独立探针代码与失败证据在output/independent-review-20261031-r2/。没有重跑全仓2224项或Swift397项、没有实机验收。候选材料26源文件中2份文档摘要过期，3份前端产物匹配；没有新的Mac App/Windows安装器，不将材料清单当完整安装交付。

原分支codex/release-0.1.1-preview-20261010、HEAD0994f620516c49d84badc3a606c1cd5ae4b483d0不变，保留全部已有改动。本轮仅核验记录与本地探针，未修产品源码、未操作现有VM或部署助手、未改变真实网络、未删除资产、未提交推送/打包发布。未现场刷新VM状态，不根据历史PID做操作。

剩余规划未完成：第150节本身保留A03/T02/W05/U04等实施或决策缺口及实机门槛，矩阵G0/G1仍未通过。不能将未实施和待验收混为“全部完成”。接续语：继续/Users/pufei/Downloads/ctf-lab，先读AGENTS.md、状态第151节与第二轮独立核验报告，保留改动；按本次明确任务修复真实客户端/daemon、心跳、子进程回收、FD所有权、双向序号和会话准备/授权绑定，再补生产路径集成测试。不要自动操作VM、部署来宾助手、改真实网络、删资产或发布。

## 152. 第二轮核验修复与 PD Kali 实机准备（2026-10-31，持续推进）

目标为按核验与设计完善后续任务，保留正式目录全部已有改动。分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f62`不变；未提交、推送、重新打包App/安装器或发布。

**本轮实现**：生成助手单请求attach完成grant核对/元数据分界/FD移交后再应答身份；心跳bytes编码与连续序号回声；SCM_RIGHTS单所有权和多FD拒绝清理；shell子进程独立回收，不抢TAP同步子进程；宿主接收严格从0连续，来宾身份后从1继续；管理员grant绑定实例/代次/网段/策略及MAC/IP/MTU；机器UUID不可读拒绝自动降级；SO_PEERCRED正确取uid、status无session和过期shell修正。生产登记与运行策略同源，材料prepared固定会话和setup/shell/teardown命令，连接一次消费，重连需新批准；双端显示及前置门控。桌面动作与worker写入复用代次锁，更新核对原会话，计划/代次变化停泵。独立CLI补已批准`--session`、身份传参、实际生效且只能缩短的quota，主CLI材料入口可携带绑定参数，与桌面共用prepare_session。细节见[修复验证记录R3](verification-external-attach-fixes-2026-10-31.md)。

**验证**：首轮完整回归2237项，2216通过、21条件跳过、0失败（331.599秒），源码摘要`output/external-attach-r3-20261031/full-regression-source.json`；其后CLI补丁的35项与最终受影响120项通过（41.067秒）；前端81项+构建、Swift类型检查与397项检查（失败0）通过。最终补丁后的完整回归正在执行，结果在本节末补记。早期针对性失败包括旧桩重用序号0、旧桥接夹具缺完整v2清单/未准备材料、macOS临时路径未resolve；分别调整为当前真实契约后通过，没有将失败冒充通过。首轮全仓仍出现非本轮socket泄漏的其他测试文件ResourceWarning，原日志保留。证据目录`output/external-attach-r3-20261031/`；272个Python文件语法通过（CLI末补后另复核），git diff --check通过。

**实机授权与现场**：用户明确PD有Kali，并在本聊天授权使用`zhangpu`恢复运行、安装助手和创建独立实验命名空间/TAP；原管理网保持，不自动关机/删资产。只读核对Parallels Desktop 20.4.2：Kali UUID`d3770648-df6a-44be-bbac-43a84b78d070`原`suspended`，经本次授权resume已`running`；另一台Windows 11仍`suspended`、未操作。Kali锁屏截图已保存；GuestTools报告`possibly_installed`、20.4.1-55996，prlctl exec连续两次无法建立来宾会话，停止重复重试。已请用户在PD解锁，不索取密码。当前未部署助手、未改来宾或宿主网络、未创建真实TAP，也未操作任何QEMU用户实例；不能将resume或桌面出现当接入验收。后续先由已授权Kali读取基线，再部署独立材料和验证，停止/重启VM与删除资产仍不自动执行。

**后续任务**：剩余矩阵已将A03完整入口对照、T02执行模板门、W05离线安装准备明确恢复为实施缺口；U04维护人/反馈入口待用户指定，G0/G1未通过。第二轮核验非穷尽的并发/观测未知/SSH背压等范围仍需继续；不再概括“其余全部完成”或“只差实机”。

接续语：继续CTFLab，正式目录`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第152节、第二轮独立核验与修复记录R3，核对Git/文件/实例实际状态，保留全部改动。用户本聊天已授权PD Kali“zhangpu”恢复运行、助手部署与独立TAP/netns验收，原管理网保持；当前Kali已恢复、等用户解锁，来宾命令通道失败尚未部署。不要重复请求已有授权，也不要自动停止VM、删资产、桥接物理网络、提交推送或发布。并行独立工作按矩阵顺序A03/T02/W05/U04推进。

第152节验证与现场补记：最终完整回归2239项（2218通过、21条件跳过、0失败，341.590秒）；`final-full.log`与`final-source.json`对应。随后仅改材料说明的旧退化身份表述、React默认用户与材料账户不一致，助手/材料24项和前端81项＋构建复跑通过；不将整仓结果冒充末补后再次执行。Swift397项检查失败0。用户已解锁Kali；截图确认aarch64、prltoolsd inactive、sshd已有、来宾日期停在2026-08-24。宿主exec仍失败，自动输入也未进入终端；用户已被请在Kali手动启动现有prltoolsd，等待结果。未部署助手、未建TAP、未改原网络；SSH尝试严格拒绝未核验主机密钥，不自动信任。授权继续有效。

A03入口核对增补见`docs/ctflab-contract-parity-2026-10-30.md`末段：Mac缺持久历史重开和严格事件游标UI，主CLI local-contract缺历史参数透传；不能以React对照代替这些入口。后续实施已明确，而A03及G0/G1仍开放。继续本聊天无需重问PD Kali部署范围。

第152节后续入口与SSH补记：主CLI `local-contract` 已补`--history/--operation/--limit/--before`透传，默认stdin路径保持原参数兼容；真实子进程历史/结果查询确认SQLite不变、无后端调用。原操作历史/本机适配/跨语言合同36项通过（2.877秒），晚于完整2239项，不冒称全仓再跑。Mac持久历史/事件UI仍缺，A03不关闭。用户反馈Kali不存在prltoolsd服务并要求改走SSH；未安装或重装PD Tools。仅向用户指定来宾地址SSH 22端口握手，严格主机密钥检查拒绝未知密钥；已取得候选公钥指纹，请用户在Kali控制台核对（不在交接记录保留IP、密钥或凭据）。尚未认证、未尝试密码、未部署助手或修改来宾网络。后续先完成主机身份核对，再用已有认证方式或用户在本机完成认证，不向聊天索取密码。

SSH接续（本轮待办）：用户已在Kali控制台确认候选SSH主机指纹一致，已生成单独known_hosts并严格校验；现有密钥认证被拒绝。已生成本次临时Ed25519密钥，私钥只在output下700目录/600文件中，不提交、不在交接贴出；公钥限制来源为当前Mac且禁转发，已请用户追加到来宾authorized_keys，等待“已添加”。测试结束仅撤销本条临时授权，不删除用户其他密钥。下一步使用该临时identity与已核验known_hosts登录zhangpu，先检查sudo -n、真实内核/网络基线、DMI读取和既有助手路径，不自动扩大监听或修改原管理网。详细临时连接材料留在output/external-attach-r3-20261031/ssh-auth/，后续按实际文件核对，禁止把私钥内容写入聊天或记录。

## 153. PD Kali真实TAP/SSH切片、突发预读修复与安全收口（2026-10-31）

接第152节，用户已授权的PD Kali验收实际推进，目标并未全部完成。正式目录、分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f62`不变，保留已有改动；未提交、推送、生成新App/Windows安装器或发布。详情与精确范围见[修复验证记录R4](verification-external-attach-fixes-2026-10-31.md)。

**完成与实际限制**：Kali ARM64真实内核TAP/netns/SCM_RIGHTS与SSH身份握手通过，实际Parallels ARM DMI组合补入白名单；原管理网未改。通过产品交换机/认证口及run_relay，与两个Mac回环帧应答器完成ARP/UDP回显；默认15秒空闲门槛下空闲17秒仍存活，实际重复序号关闭来宾客户端、固定数据SSH入口拒绝任意命令。两个应答器不是实际靶机VM，未测试完整课程/业务、原生GUI、QEMU hub、Windows或Fusion/Workstation组合。降权shell的ping因ICMP/raw权限失败，保留失败且未扩大权限。

**新缺陷修复**：50包突发真实复现双端BufferedReader预读使select失去可读信号；真实管道两项回归修前失败。宿主SSH进程管道无缓冲、来宾从HELLO起读取raw流后50包全部返回；仅修宿主仍失败的独立证据保留。停止等待上限缩为0.5秒，避免断开等待整个心跳周期；最后复跑宿主线程与SSH通道均正常收口。

**本轮验证**：末次完整2241项（2220通过、21条件跳过、0失败，355.917秒）；之后仅停止等待上限/断言末补，最终受影响121项通过（41.370秒）及流/助手20项通过。A03主CLI历史透传36项通过；前端81项＋构建、Swift类型检查与397项检查失败0为本轮先前证据，Swift未再改。完整回归与最后末补的源码差异明确保留，不把前者写成后者已整仓再跑。日志/摘要均在`output/external-attach-r3-20261031/`。

**已收口现场**：用户在Kali执行已核对摘要的cleanup脚本，实际TAP生命周期FD 1→0、命名空间/grant/socket消失、临时daemon退出，管理网地址/MTU/MAC/flags/路由保全；两条临时SSH公钥已撤销并分别实测认证拒绝，原其他字节与备份保留，私钥只留本地私有忽略目录，不入库、不贴入交接。安装和代码备份/证据文件保留。Kali `d3770648-df6a-44be-bbac-43a84b78d070`最终running；Windows 11仍suspended，未操作。今后不得凭本节旧PID直接控制。PD关闭窗口策略仍为原suspend：用户虽授权临时keep-running，但应用要求Mac管理员认证，实际未改，无待恢复设置。多次挂起与此配置相符，但未实证由谁触发。

**后续**：E01仍有真实靶机/两后端/平台与故障门槛，普通撤网通过不代表撤网失败回执/恢复已通过；下一切片先核对该实现与故障测试，再推进Mac持久历史/严格事件UI、T02执行模板门、W05离线安装准备。U04维护责任与入口仍需用户指定，G0/G1未通过。用户对本次Kali恢复/助手/独立TAP的授权已给出，不重复询问同一范围；但临时SSH授权已撤销，后续需要时须重新建立认证，不索取聊天密码，不由Kali授权推断其他VM操作权限。

接续语：继续CTFLab正式目录`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第153节、修复记录R4和剩余矩阵，现场核对Git/文件/实例，保留全部改动。本轮PD Kali真实内核/SSH＋回环应答器切片与突发预读修复已验，测试资源/临时公钥已收口，Kali保留运行，未发布。继续核对撤网失败回执，再补A03 Mac历史/事件、T02/W05；不要自动停止VM、删除资产、桥接物理网络、提交推送或发布，也不要把该切片当完整E01/G0/G1通过。

第153节最终证据：`output/external-attach-r3-20261031/final-evidence.json`与`source-final.json`汇总测试范围、原生/发布未完成、当前源摘要及现场收口；272份Python AST和git diff --check通过，文档守卫7项通过。候选`output/candidate-materials-20261031-r4/`仅含31份固定源码/文档副本、3份前端产物和脱敏验证摘要，不含运行时、VM资产、SSH材料或私钥，不是App/Windows安装器。旧r3及此前候选保留为各自时间快照。

## 154. A03/T02/W05/U04 本地实施与G0/G1核对（2026-10-31，四项实施/决策缺口按矩阵推进）

按[剩余矩阵]2026-10-31执行顺序第2—4、6项推进，详见[本轮验证记录](ctflab-a03-t02-w05-u04-20261031.md)。分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f62`不变；改动保留工作区，未提交/推送/打包/发布，未操作VM、真实网络、来宾助手或用户资产。

**A03**：Mac补"已保存操作（历史）"与"实验事件（严格游标）"只读UI及`MacContractRules/MacSavedOperation/MacHistoryPage/MacSavedRecord/MacEventPage`模型（与`public_error`/`_saved_operation`/`merge_events`同判定）；generic-client白名单补`operation-history/operation-result`（只读、不spawn、SQLite不变）；新增`test_ctflab_mac_contract_parity.py`用`--contract-vectors`驱动Swift二进制与`merge_events`同输入对照（>150事件向量含绑定重定位、真实账本wire、16类篡改拒绝）。三端（CLI/React/Mac）源码级对照闭合；原生窗口实测保留。

**T02**：`ctflab_topology.py`新增`publish_qualification/verify_qualification`执行资格门——S03校验失败即拒（错误图不可执行）、具体场景验收记录绑定精确manifest/计划摘要与代次、摘要变化即失效、草稿导出与执行资格分开（双端文案同步）、运行代次不热改（applied=false、requires_new_generation、实例+代次绑定）；CLI`publish-qualification/verify-qualification`与桥接/generic-client只读`template-qualify`入口；门控测试含CLI不覆盖与生产路径。真实场景验收记录需环境。

**W05**：新增`ctflab_w05_readiness.py`+6项测试；对0.1.4未签名候选现场重算SHA256一致、PE证书表为空确认未签名、5625文件载荷逐项摘要与CI重建清单一致、run-10卸载保留证据核对；报告`output/w05-offline-20261031/readiness-report.json`：安装布局/运行时依赖verified、卸载保留verified（历史）、签名verified-unsigned-candidate-only、**WebView2供应missing-evidence**（静态解包未见安装器，须无WebView2干净机验证）、干净Win11/升级回退/最终包open。

**U04**：用户指定维护责任人张璞本人、复核周期每周、私密安全反馈=仓库GitHub私密安全报告、公开入口本地先行；社区工作流维护表已更新，`.github/SECURITY.md`与`.github/ISSUE_TEMPLATE/问题反馈.md`进入白名单（未提交未推送、远端未启用未实测）。远端实测与支持范围/兼容淘汰按授权及最终包保留。

**G0/G1**：未通过。G0阻塞＝获准Windows x64物理机（本机PD Win11为ARM、无实测授权）；G1另需W04—W06/P/C/U真实验收与签名。本轮仅闭合其本地前置（A03对照/T02门/W05离线/U04决策），不宣称43项或G0/G1完成。

**验证（2026-10-31）**：Swift类型检查退出0、测试二进制423项失败0（较上轮397+26，新增A03判定）；前端npm test+build通过；受影响专项89项通过（Mac契约对照3、operation_history 16、local_adapter 13、contract_parity 7、mac_remote 28、roadmap_offline含资格门16、w05就绪6）；279个Python文件AST通过、git diff --check通过。全量回归`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tools/tests`：**2254项（2233通过、21条件跳过、0失败），388.079秒**（日志`output/a03-t02-w05-u04-20261031/full-regression.log`，含本轮全部新增模块与测试）。首轮回归两次因日志相对路径与shell cwd错误未实际执行，未冒充通过，改绝对路径后完成。

接续语：继续CTFLab正式目录`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第154节、`docs/ctflab-a03-t02-w05-u04-20261031.md`与剩余矩阵，现场核对Git/文件/实例，保留全部改动。A03/T02/W05离线/U04决策四项本地实施已闭并有跨语言/门控/就绪证据；剩余为各任务实机/平台/人员门槛（见矩阵）——G0需获准Windows x64实机，W05需干净Windows机核验WebView2供应与升级回退，U04远端入口实测需授权，A03原生窗口与T02真实场景验收需环境。不要自动停止VM、删除资产、桥接物理网络、提交推送或发布；E01撤网失败回执等实机切片另行推进。

## 155. U04远端入口上线与G0实机决策（2026-11-01）

接第154节核验结论，用户本轮两项决策：**G0暂无获准Windows x64实机**（保持条件阻塞，等待后续指定设备与授权；本机PD Windows 11为ARM不替代）；**授权U04推送并开启远端入口**。

**U04执行（按第141节最小范围先例）**：①release分支`codex/release-0.1.1-preview-20261010`追加提交`4e8c058`，仅含`.github/SECURITY.md`、`.github/ISSUE_TEMPLATE/问题反馈.md`与`.gitignore`白名单8行（经git plumbing从HEAD内容最小增量构造，未携带工作区其余约300个未提交文件）；②远端默认分支`main`在`6f434e3`之上新建独立提交`a6fd5a8`（同样仅3文件，未合并release分支历史）并快进推送；③仓库私密安全报告经API开启并核验`enabled:true`。远端核验：main与release分支两个提交中的SECURITY.md/模板blob sha与本地一致（faf50e3d/26334b54）；GitHub新建issue将显示模板，Security页显示政策。本地分支HEAD已随提交推进到`4e8c058`（与远端release分支一致），其余约318个未提交改动原样保留；远端`main`=`a6fd5a8`为独立历史，未合并到本地分支、也未拉取。后续会话现场核对这三处即可。中途一次push因shell变量丢失被远端拒绝（按删除保护），未改变远端状态，以SHA重推成功。

**U04状态**：backlog首版要求闭合——模板/分类/责任人（张璞）/复核周期（每周）/非公开安全流程/公开前入口实际可用均已落地并有远端证据。剩余：支持范围与兼容淘汰随最终包与具体版本落实；首个真实报告的分流与响应记录由维护人按每周周期履行。

**G0/G1**：仍未通过（G0＝x64实机未指定；G1＝W04—W06/P/C/U真实验收与签名）。W05的干净机/WebView2供应/升级回退核验随未来实机授权执行。

接续语：继续CTFLab正式目录`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第155节与剩余矩阵，现场核对Git（本地HEAD 0994f62+未提交改动 vs 远端release分支4e8c058、远端main a6fd5a8），保留全部本地改动，不自动拉取/合并。A03/T02/W05离线/U04四项已闭；剩余为G0（需用户指定获准Windows x64实机并授权受保护控制/重连/异常恢复/端口交接验收，同环境可顺带W05干净机核验）与G1其余真实验收及签名门槛。不要自动停止VM、删除资产、桥接物理网络、推送其他未提交改动或发布。


## 156. E01 撤网失败回执、持久恢复与setup回滚（2026-11-01）

现场核对正式目录、分支`codex/release-0.1.1-preview-20261010`、HEAD`4e8c058`；第154—155节的A03/T02/W05离线/U04成果保留，不根据旧聊天重做。目标仍未完成，G0/G1不关闭。本轮仅生成助手源码、对应测试、验证记录和本地材料，未提交、推送、打包App/安装器或发布，未操作VM、真实网络或来宾助手，没有新建真实运行实例；未现场刷新VM状态，不把第153节旧运行状态当本轮观察。

**修复**：旧撤网在网络删除失败时仍回报已关闭并丢失会话；真实旧脚本故障探针复现。现在先持久化cleanup_pending并禁接入，关闭FD后清空所有权，检查真实TAP/网卡/进程残留与命名空间存在性，失败保留授权与重试回执；重启只恢复清理条目、不恢复连接，不自动杀工具进程或删除额外网卡。setup网络变更前保存恢复记录，中途失败复用撤网；损坏授权文件不覆盖，权限错误不冒充命令成功。命名引用消失不等于证明所有匿名内核引用消失，真实Linux故障矩阵仍开放。详见[验证记录](verification-teardown-recovery-2026-11-01.md)。

**验证**：完整2266项＝2244通过、21条件跳过、1失败（386.987秒），唯一失败是新验证文档缺少规定的历史快照说明；已补正，文档94项复跑89通过/5跳过。全量启动后末补授权防覆盖/命令权限处理两点，最终受影响97项通过（13.605秒），没有冒称末补后整仓再跑。输出中guest-password负向测试的“FAIL”不是额外交换机失败。源码AST、git diff --check、新助手材料4文件摘要/生成脚本语法通过。完整与末补源码摘要、修前/修后故障回执及原始失败日志均在`output/teardown-recovery-20261101/`；旧候选与证据未覆盖。没有部署新版，真实Kali普通撤网历史结果不替代本版故障恢复实机验收。

**下一步**：E01宿主中转使用select等待SSH管道与socket，仍需跨平台可限时/可停止的实现及部分记录/背压回归；这属于实施项，不能泛称只差Windows实机。然后按剩余矩阵继续真实靶机、原生窗口、G0/W05获准Windows x64实机与最终包等门槛。临时SSH授权已在第153节撤销，后续不能假设仍可登录；不重复索取已有Kali范围授权，也不扩大为其他VM或网络权限。

接续语：继续CTFLab，正式目录`/Users/pufei/Downloads/ctf-lab`。先读AGENTS.md、状态第156节、撤网恢复验证记录和剩余矩阵，核对Git/文件/实际实例，保留改动。下一步修复宿主SSH帧泵跨平台等待、部分记录和背压/限时停止；E01真实故障、原生GUI、G0/G1仍未完成。不要自动停止VM、删除资产、桥接真实网络、推送未授权改动或发布；本轮新助手仅在output生成，未部署。


## 157. E01 宿主帧泵跨平台等待、限时停止与背压（2026-11-01）

现场正式目录、分支`codex/release-0.1.1-preview-20261010`、HEAD`4e8c058`不变；保留此前改动。本轮修改`tools/ctflab_external_attach.py`、原帧泵测试及新增`test_ctflab_external_io.py`，没有提交、推送、打包App/安装器或发布，没有操作真实VM、SSH来宾、物理网络或用户资产。未现场刷新VM状态，不以第153节状态当本轮观察。

**实现**：SSH管道改由两个有界搬运线程处理，主循环只select socket；记录头与正文共享截止时间，读写/认证可停止、检查会话过期，部分交换机帧有时限，非法长度立即结束。交换机短写/背压有续传与停止检查；关闭回收自己持有的SSH子进程与线程，不确认收口就抛错。补靶场→Kali方向同一会话配额。固定SSH入口、机器身份与助手摘要严格校验仍保留。真实旧代码探针2字节后阻塞已复现，修后按150ms配置超时退出，所有探针子进程已回收。见[验证记录](verification-relay-io-2026-11-01.md)。

**验证**：真实子进程/管道/socket专项17项通过（4.628秒），受影响116项通过（44.642秒）。最终完整2285项＝2264通过、21条件跳过、0失败（400.230秒），覆盖第156节最终撤网补丁和本轮最终源码。280份Python AST、全量前后280份源摘要一致、git diff --check通过；文档94项（89通过/5条件跳过）收口后复核。首轮新增测试的两处失败已解释并修复/调整，原日志保留，不将其冒充通过。本轮没有全量后的产品源码末补，没有重跑前端构建或独立Swift检查；完整套件内检查按实际日志为准。证据`output/relay-io-20261101/`含固定3份源码副本与摘要，不是新App/安装器或发行候选。

**实际范围**：仅本地实际进程/管道/loopback socket；用只接受socket的select替身核对跨平台等待接口，不代表Windows原生内核与SSH客户端验收。真实Kali SSH与新版撤网助手部署、两小时/性能/睡眠、真实靶机/原生UI/最终包仍开放。第153节临时SSH授权仍已撤销，本轮没有恢复认证或部署材料。

**下一步**：先复现桌面断开持GenerationStore锁等worker退出、worker退出前又取同锁落回执的跨进程锁顺序；现有直接dispatcher桩未覆盖此路径，不能仅凭源码认定实测失败。随后补设计§4.3安装路径/祖先所有者、可写性与链接检查，控制socket对端root身份和降权shell环境/能力边界；受控raw工具仍不得改成通用sudo/CAP_SYS_ADMIN shell。A03/T02/W05/U04既有成果保留，G0/G1及矩阵原实机/人员门槛不关闭。

接续语：继续CTFLab，正式目录`/Users/pufei/Downloads/ctf-lab`。先读AGENTS.md、状态第157节、帧泵I/O验证记录及剩余矩阵，核对Git/文件/实际实例，保留改动。下一步真实临时账本/测试进程复现并修补两阶段断开的锁顺序，再补助手部署安全检查。不要自动操作用户VM、真实网络、删除资产、推送未授权改动或发布；新助手仍未部署，SSH临时密钥已撤销，不假设可登录。

## 156. T02真实场景验收与A03开发版窗口实测（2026-11-01，用户授权本机执行）

用户本轮授权：T02本机真实场景验收（派生磁盘+回环隔离）、A03开发版App窗口实测；同时确认G1签名证书暂无（候选保持未签名仅限封闭试点）、W06非开发者试点暂不安排（条件阻塞）。

**T02场景证据缺口关闭**：测试状态根`/Users/pufei/Downloads/CTFLab-T02-acceptance-20261101/`（独立于用户状态目录），清单`kali-standalone-acceptance-20261101`（单节点kali，UEFI/VirtIO，10.80.0.0/24无宿主出口，资产=用户自有kali-arm64基盘只读副本，实测SHA256 `79ed36f0…`）。全产品generic-client路径：configure→prepare（generation 1，真实派生overlay/NVRAM/TLS）→start（**真实Kali VM在0.1.4预览版App受控QEMU上以hvf原生加速启动**，process-running且identity verified，稳定45秒+；QEMU仅hubport无user网络、QMP/VNC仅127.0.0.1+TLS+客户端身份）→stop（system_powerdown正常关机，进程确认退出）→reset（**generation 2新代次路径验证通过**）。验收记录`scenario-acceptance-record.json`（result=passed，绑定canonical manifest摘要与next plan摘要）经`publish_qualification`发布为`executable-template-qualification.json`并`verify_qualification`通过——T02"发布可执行模板须通过S03及具体场景验收"首次以真实运行证据闭环；账本4操作（prepare/start/stop/reset）与事件历史已导出为证据。测试实例保留在generation 2 prepared（停止态）作现场，未删除；未触碰用户实例/原盘/真实网络。

**过程真实缺陷与修复（留档）**：首次start失败＝worker继承`/usr/bin/python3`（无cryptography）导致TLS provision失败（attempt目录为空、账本backend-failed、recover重试同样失败留证）；改用miniconda Python（含cryptography 3.10.19）全链路通过。该发现对后续诊断有价值：worker依赖随启动方解释器。

**A03原生窗口实测（部分完成，点击验证待人工收尾）**：从工作区源码构建开发版CTFLab.app（ad-hoc签名，输出`/Users/pufei/Downloads/CTFLab-A03-window-20261101/app/`，884登记文件；构建输入复用0.1.2构建资料）。已实测：窗口启动、实验工作台、本机场景面板、新版通用v2切换、实例列表（显示伪造HOME下的prepared测试实例`d5f5cb92-…`，gen 1、3事件、1历史操作）——截图screenshot-3/4/5/6/7/9。新"已保存操作（历史）/实验事件（严格游标）"面板的人工点击验证因System Events键盘注入被限制未完成，App保持运行（伪造HOME隔离，状态目录`CTFLab-A03-window-20261101/home`）待用户按5步点击；若无法完成，A03窗口项以"源码级三端对照+跨语言向量回归+窗口结构实测"为当前结论并如实保留缺口。实测发现：`--unsigned`App在Apple Silicon被内核SIGKILL（必须ad-hoc）；`--version`须与CTFLAB_VERSION一致。

**G1门槛记录**：签名证书暂无——0.1.4 Windows候选与Mac开发版均未签名，公开发布前G1签名条件不满足（本机PE证书表核验为空）；W06试点人员暂不安排，≥5名非开发者条件保持阻塞。G0仍需获准Windows x64实机（用户此前确认暂无）。G0/G1未通过；A03/T02/W05离线/U04四项的本地可实施与可授权范围至此全部闭合。

**验证（2026-11-01本轮）**：场景验收运行真实完成（各步回执/账本/事件/launch.json见evidence目录）；publish/verify资格门在真实清单上通过；dev app构建成功并实测窗口结构。前端/全量回归未重跑（本轮未改Python/Swift源码——T02用既有资格门、A03窗口用既有构建入口）；此前§154的2254项0失败仍为本轮源码基线。

接续语：继续CTFLab正式目录`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第155/156节与剩余矩阵，现场核对Git（本地HEAD 4e8c058+未提交改动 vs 远端release 4e8c058、远端main a6fd5a8），保留全部改动。四项具名任务本地可实施范围已闭合；T02真实场景验收已闭环（`/Users/pufei/Downloads/CTFLab-T02-acceptance-20261101/`）。A03窗口新面板的人工点击验证待完成（App在伪造HOME下运行中，5步点击见本节）；G0（x64实机）、G1签名与W06试点为用户侧条件。不要自动停止该App或删除测试状态根、不要自动停止VM、删除资产、桥接物理网络、推送其他未提交改动或发布。


## 158. E01 桌面断开锁冲突、最终回执与三态观测（2026-11-01）

正式目录、分支`codex/release-0.1.1-preview-20261010`、HEAD`4e8c058`不变，保留全部既有改动。本轮仅桥接实现、测试与记录；没有提交、推送、原生打包或发布，没有控制用户VM、连接SSH来宾或改变真实网络/用户资产。真实测试进程仅为本轮临时目录内自建并持有Popen句柄的Python子进程，均已回收；未现场刷新用户VM状态。

**实证与实现**：独立`external_relay_worker`+真实GenerationStore/LocalService/dispatch复现第157节锁顺序疑点：gate忙时立即报错，worker最终回执与异常回执都写失败，以1退出。现改短锁登记断开意图、锁外等退出、短锁核对会话/PID/请求标识/绑定/代次并合并最新session；worker只对状态持久化的短时锁忙有界重试，不重放网络操作。run_relay的finally确认通道收口后才落transport_closed；进程消失但缺该回执仍unknown。进程观测区分匹配/原身份不在/不可判定，不对不明身份发终止信号。unknown仍活跃或不可观测时拒绝清除和另启连接，防止先抹掉恢复记录。详见[验证记录](verification-external-disconnect-2026-11-01.md)。

**平台复核**：新增signal 0存在性探测仅限POSIX；Windows禁用整个ps/signal观察路径，返回未知、不发信号，依据Python官方os.kill语义。Windows外部中转的原生进程身份与协作停止仍是明确实施项，不能称为只缺实机。此项属E01外部接入，不能据此扩大G1的原始范围或撤销既有本机Windows后端证据。

**验证**：全量2295项＝2274通过、21条件跳过、0失败（396.487秒）；全量启动后仅平台POSIX限制与对应新测试/跳过标记末补，最终扩展125项通过（46.703秒）。独立真实worker退出码0且最终report保留、短锁争用重试、缺失回执/观测失败、会话或绑定被替换不覆盖、活动unknown不可清除/重连均覆盖。全量与最终源码快照明确分开，不冒称末补已整仓再跑。281份Python AST、git diff --check、文档94项（89通过/5条件跳过）复核通过。证据`output/disconnect-lock-20261101/`含修前真实失败、专项/完整日志、源码摘要与最终固定3源副本；不是App/安装器。本轮未重跑前端构建或独立Swift检查。

**继续入口**：Windows外部中转原生身份/协作停止适配，设计§4.3可信部署路径和控制socket对端root身份、普通shell环境/能力边界，以及缺PID/完整身份的历史unknown记录的受验证恢复，仍需实施；不把安全拒绝未知当恢复功能已完成。真实SSH/Kali新版助手、Windows原生/两后端/长期故障/真实靶机/原生UI与最终包证据仍按矩阵保留。第153节临时SSH授权已撤销，本轮未恢复，未部署第156节新版助手。G0/G1未通过，目标保持进行中。

接续语：继续CTFLab正式目录`/Users/pufei/Downloads/ctf-lab`。先读AGENTS.md、状态第158节、断开验证记录和剩余矩阵，核对Git/文件/实际实例，保留改动。断开锁冲突已实证修复；接下来沿真实入口补Windows外部中转原生观察/协作停止与助手部署安全/未知记录恢复。不要自动控制用户VM、删除资产、改变真实网络、推送未授权改动或发布；本轮没有新来宾部署，不能假设历史SSH密钥仍可用。

## 157. A03窗口验证闭环与Mac App打包缺陷修复（2026-11-01）

接第156节。A03开发版窗口5步验证全部通过（本会话以System Events辅助点击完成，均截图存证`CTFLab-A03-window-20261101/screenshot-*.png`）：①列出已有场景→②选择`d5f5cb92-…`测试实例→③读取状态（当前代次1·操作记录已准备+设计拓扑）→④「已保存操作（历史）」展开并「读取历史」＝`prepare · completed · 代次 —`（expected_generation为null如实显示"—"）、「原响应」＝`原响应（历史）：prepare · completed`+「未派发任何操作」→⑤「实验事件（严格游标）」展开并「读取新事件」＝三条真实事件`#1 intent→#2 executing→#3 completed`按序号倒序显示。只读文案、无自动加载、原响应/历史/事件契约全部按§154设计在原生窗口实际工作。

**过程中发现并修复Mac App打包P1缺陷**：`ctflab_scenario_v2.validate_network_external`导入`ctflab_external_attach`，但`ctflab_package.RELEASE_TOOL_FILES`未含E01三模块（Windows/integrated kit已补、Mac清单遗漏）——任何新建Mac App的通用v2流程`ModuleNotFoundError`（窗口实测"回复无法核验"，App内置Python真实复现）。已补`ctflab_external_attach/external_l2/kali_attach`三行进白名单并加注释；受影响套件（package 37、app 68、windows_native_ci 17）通过；重建App后内置Python overview实测正常，窗口链路随之全部走通。0.1.4已发布App不含E01代码不受影响；此缺陷只影响"从当前工作区新构建"的包——本轮修复使后续Mac重打可用。

**运行现场**：dev App（pid见§156更新，ad-hoc）保持运行于伪造HOME，可关闭；T02测试状态根（gen 2 prepared）与A03窗口实例（gen 1 prepared）保留为现场，未删除。本轮源码变更仅`tools/ctflab_package.py`白名单+3行；最终全量回归`PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tools/tests`＝**2296项（2275通过、21条件跳过、0失败），384.182秒**（`output/a03-t02-w05-u04-20261031/full-regression-final.log`，较§154的2254项新增42项＝打包白名单守卫、窗口/契约新增用例）。

接续语补充：A03/T02/W05离线/U04四项连同窗口实测均已闭合；剩余G0（x64实机）、G1签名与W06试点、W05干净机三项均为用户侧条件，见矩阵。


## 159. 并行记录范围澄清与E01集成接续（2026-11-01）

本节承接标题为“158. E01桌面断开锁冲突、最终回执与三态观测”的阶段。文件因并行追加存在两组156/157编号：E01撤网/帧泵，与T02/A03场景/窗口。原文均保留，请按**日期+标题**定位，不只依赖节号；A03/T02/W05离线/U04四项的收口结论不替代E01或43项/G0/G1整体完成。

本阶段全量2295项（2274通过/21条件跳过，0失败）加载快照以后，自己的差异是桥接平台保护及对应测试两文件，最终125项通过。摘要还发现同期`ctflab_package.py`新增E01三个运行依赖的白名单增量；本阶段未编辑或覆盖它，去除该新增段重算精确匹配全量输入摘要。已另跑package37项、App CLI/闭包5项通过；实际复制源到独立临时目录，再以`python -I -B`执行v2 external生产校验与桥接/助手导入通过。完整日志仍对应旧全量输入，不冒称同期白名单已包含在该全量快照。最终281份Python AST、git diff --check及文档检查通过。

证据`output/disconnect-lock-20261101/`含完整与最终摘要、原失败、最终125项、打包37项、闭包5项、隔离v2记录、自己的3份源与同期打包1份源的固定副本。同期A03开发版App、T02/窗口状态根与资产按各自记录保留，本阶段未操作；不能把同期开发版App当本轮最终E01代码已重新打包或实测。

继续目标保持完整：E01 Windows原生进程身份/协作停止、可信助手部署与普通shell权限、缺完整身份unknown记录的受验证恢复仍有实施工作；真实来宾/平台/故障/课程及原G0/G1门槛仍分别保留。不能概括“其余只差用户环境”。没有本阶段提交、推送、发布或真实VM/网络操作。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态标题“158. E01桌面断开…”与“159. 并行记录范围澄清…”、断开验证记录和剩余矩阵，核对实际文件与Git，保留全部改动。E01下一步补Windows原生观察/协作停止与助手部署安全、unknown恢复。A03/T02并行现场保持，不停止其App/VM或删除资产，不假设历史SSH认证有效，不推送未授权改动或发布。


## 160. E01 Windows原生进程身份、协作停止与状态ACL（2026-11-01）

接标题“158. E01桌面断开…”与“159. 并行记录范围澄清…”的剩余源级工作，正式目录、分支`codex/release-0.1.1-preview-20261010`、HEAD`4e8c058`不变。保留全部已有改动；本轮没有操作用户VM、真实SSH/Kali、物理网络或并行A03/T02现场，没有提交、推送、新App/安装器构建或发布。测试子进程均为本轮自行创建并持有句柄，已回收，未现场刷新用户VM状态。

**实现**：复用Win32查询/等待接口，启动方从自有Popen原始句柄捕获PID/创建时间/程序路径；worker打开网络前严格绑定自身原生身份。控制器在停止意图前保留匹配对象，锁外等同一对象退出及退出码，合并最新会话回执；Windows不调用ps或POSIX信号。私有UUID停止请求驱动协作退出，超时后请求不撤销；启动前取消不打开通道。原生只读PID快照区分已不存在与查询失败，不因访问拒绝冒充退出，句柄按路径回收。身份捕获失败只回收本次自有Popen，成功等待后记录未进入传输的启动退出证明；不以任意PID强杀替代身份。

**存储与恢复**：AttachStore补Windows ACL与重解析点检查，不再在Windows调用getuid；验证状态/临时文件权限，拒绝临时文件符号链接/硬链接覆盖。含PID但缺创建时间的旧unknown，仅在成功原生快照确认PID不在时才可清理；新启动捕获失败且已回收的自有进程有启动退出证明。连PID都缺失的旧unknown仍需受验证恢复入口，不以本轮局部恢复宣称全部未知场景已完成。创建时间必须为有效64位FILETIME，损坏字段不会据此假定原进程不在。

**验证**：完整2323项＝2300通过、23条件跳过、0失败（376.849秒）；全量后仅桥接FILETIME上界及对应测试末补，最终扩展161项＝157通过、4原生Windows条件跳过、0失败（46.652秒）。同一保留句柄/进程重用/权限失败/启动闸门/启动前取消/正常与异常退出/协作请求/私有存储保护均有本地真实账本、实际ctypes结构和Windows API桩覆盖；另有本机独立worker不用信号也能正常退出并保留回执。27项新Windows中转测试不重复导入基类夹具；其中真实Kernel32快照和保留子进程自然退出在非Windows跳过，没有冒充原生通过。282份Python AST、git diff --check与文档94项（89通过/5跳过）复核通过。详见[验证记录](verification-windows-external-relay-2026-11-01.md)及`output/windows-relay-20261101/`，含全量/最终摘要、固定5源副本与原日志；不是新原生包。本轮未重跑前端构建/独立Swift检查。

**边界与继续**：Windows原生身份/协作停止/ACL的生产代码已接入，不等于真实Windows x64/ARM、ACL、SSH/管道/桌面存续或最终包已验。G0仍缺获准Windows x64实机，原G1签名/试点等门槛不取消，也不把E01额外内容扩大成G1原门槛。下一实施为设计§4.3助手可信路径/祖先、控制socket对端root身份、普通shell环境与能力边界、受控raw工具，以及缺PID旧unknown的受验证恢复；真实Kali新版失败恢复与两后端/靶机/长期故障等证据继续按矩阵。第153节临时SSH授权已撤销，本轮未恢复认证或部署第156节新助手。不能概括其余只差用户环境。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态标题“160. E01 Windows原生进程身份…”、对应验证记录及剩余矩阵，核对实际Git/文件/实例，保留改动。Windows中转原生API路径已本地接入并有协作进程测试，下一步集中补助手部署与权限边界、未知记录恢复，再按授权安排真实平台验证。不要自动操作用户VM/并行A03/T02现场、删除资产、改变真实网络、推送未授权改动或发布，不假设旧SSH认证可用。


## 161. Mac界面美化回归调查与当前优先项（2026-11-01）

用户继“两套UI”问题后反馈美化似乎恢复旧版，并明确指Mac App。当前优先排查该视觉问题；第160节之后尚未修改助手权限代码，不将计划当实施。正式目录、分支和HEAD`4e8c058`不变，既有改动/所有App与资产保留。

已查：第139节美化分别实施于SwiftUI和React；Mac0.1.4源码与二进制仍含新版原生侧栏，A03开发包内GuiApp.swift与当前源码一致；旧0.1.2/0.1.3缺此布局。未发现侧栏美化被回滚的证据，但Mac仍是镜像列表/旧工作台结构，React六导航视觉未移植，不能凭“代码还在”认定视觉已恢复。多份同名同bundle ID App确有歧义，也不能直接断言用户先前打开旧版。详见[调查记录](verification-mac-ui-investigation-2026-11-01.md)。

默认应用解析尝试意外启动历史构建`output/dual-release-20261030/mac-0.1.4/CTFLab.app`且AppleEvent查询超时；之后用CUA全路径实际读取该窗口和截图，只读检查，未点击启动/停止/重置/删除。窗口当前保持打开，后续控制必须重新核验归属，不按历史PID；并行A03/T02现场未操作。静态四版本证据`output/ui-regression-check-20261101/app-ui-comparison.json`。没有修改视觉/用户偏好、覆盖App、部署来宾或发布；没有为此重跑全仓，文档检查按本轮日志。

待用户确认：之前认可的是否为“实验/拓扑/模板/远程/版本/诊断”六导航工作台，还是原生镜像列表样式。收到后先完成Mac视觉/入口修复，再继续助手可信路径/控制对端/终端权限与未知记录恢复；不是取消原目标，也不标记任何整体完成。第160节2323全量与161专项是Windows适配阶段证据，不冒称本轮UI恢复已验。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md及状态标题“161. Mac界面美化回归调查…”、对应调查记录；用户确认问题在Mac，等待具体视觉基线。保留全部App/资产/改动，先定位与修复用户所指UI，不把React截图当Mac实际效果，不覆盖已发布App或控制VM；助手安全等原目标后续工作继续保留。

## 162. Mac原生工作台整合与ZCode交接（2026-11-01）

用户明确要求结合原生镜像列表与分区工作台：保留直接节点操作，突出各页功能，并直接呈现拓扑图。本轮已改`gui/GuiApp.swift`、`GuiCore.swift`与核心测试：七导航+原生列表同窗；实验先运行/状态、配置折叠；模板集中设计配置；拓扑显示设计/运行图并内嵌草稿编辑；远程、版本、诊断独立。运行观察按时间失效；没有采样的设计图不伪造运行证据。默认通用v2，旧三节点链和原节点生命周期门禁/确认保留。

独立新包`output/mac-workbench-20261101/final-preview/CTFLab.app`构建和app verify通过，1292文件、ad-hoc、未公证，版本仍0.1.4；旧发布App未覆盖。初版GUI25项通过，最终全量`full-regression-final.log`确认2335项＝2312通过/23条件跳过/0失败（412.379秒）。初始`full-regression.log`被会话中断，无结尾，不计通过。实际CUA核对七页面、原生节点操作入口、设计文件预览→三节点双网段四连线，以及最终包独立实例的载入草稿/CPU1→2/后端差异校验；原账本CPU仍1、active_generation=0、generations=[]。这是原生UI+生产桥接的合成配置证据，不是真实来宾/网络/生命周期验收。详见`verification-mac-workbench-2026-11-01.md`和对应输出证据。

输出内初版preview与最终final-preview测试窗口保持打开；最终窗口由专用包装注入`CTFLAB_GUI_STATE_DIR=/private/tmp/ctflab-workbench-window-20261101`。合成实例`8fb98fed-2e48-4121-b44e-f06a1116eb58`未prepare/start；该窗口当前草稿CPU2仅内存值副本。第一次Downloads状态包装只读目录等待，命令行同请求正常；失败现场保留，未确定根因，改独立tmp根实测通过，不能写成所有目录兼容已验。后续不按旧PID操作。旧A03/T02现场、本机资产与用户VM未动；未现场刷新VM状态。无提交/推送/发布。

**同时保留的助手增量**：`tools/ctflab_kali_attach.py`已有可信祖先/权限/符号链接与硬链接检查、固定绝对工具和过程内摘要复核、隔离Python/环境、控制socket对端SO_PEERCRED root检查、旧socket inode保护、setpriv去组/去能力/no-new-privs等；`tools/tests/test_ctflab_kali_security.py`等49项通过，证据`output/kali-security-20261101/security.log`。没有部署Kali；没有持久签名/批准安装摘要记录，安装指南与实际兼容仍须核对；raw工具权限、无PID旧unknown恢复及完整故障/平台证据未完成，不把这些增量写成整体安全闭合。

用户现要求完整后续prompt交给ZCode；接续文件`ctflab-zcode-handoff-2026-11-01.md`。下一步复核最终回归范围并收口Mac UI，再补E01剩余实现，逐43项原判据推进。G0/G1保持未通过；A03/T02/W05离线/U04首版已有闭合证据，不无故重做。临时SSH密钥已撤销，PD电源策略从未更改，无恢复设置待办。后续新增VM/网络/部署/发布授权须另核，不能从“全部完成”推断任意操作权限。

第162节收口补记：最终文档94项＝89通过/5条件跳过，git diff --check通过。最终全量正常结束，当前无本轮回归或generic-client测试请求待等待；两份UI预览窗口保留，后续仍须现场识别。完整ZCode接续文件已落地，包含全43项原判据、真实缺口、授权限制与证据入口；本轮目标未标记整体完成。


## 163. E01剩余源级四项落地、撤网竞态修复与Mac收口复核（2026-11-01，ZCode接手轮）

承接`ctflab-zcode-handoff-2026-11-01.md`。正式目录、分支`codex/release-0.1.1-preview-20261010`、HEAD`4e8c058`不变；全部既有改动保留，本轮未提交、未推送、未发布，未操作用户VM、真实网络、历史SSH或并行A03/T02现场。

**Mac工作台收口（代码/测试/CLI级）**：本会话CUA不可用（前会话窗口级证据在`output/mac-workbench-20261101/`仍有效）。深色=全语义色无硬编码；窗口min 1040×740自适应；镜像列表为懒加载List。新增侧栏Cmd+1…7页面快捷键（typecheck macos26.0通过、GUI 25项通过）。草稿导出新增CLI级闭环：审计实例`6610429a`（仅configure）的GUI等效草稿导出文件经生产`draft_diff`回灌＝applied:false、差异1项`/nodes/client/cpus 1→2`、账本零代次。窗口级复核（尺寸/深色截图/键盘/长列表滚动/save panel）仍待CUA或用户会话；审计环境已备`output/mac-workbench-audit-20261101/`（状态根`/private/tmp/ctflab-workbench-audit-20261101`、40合成镜像长列表、独立bundle ID包装App）。最终预览包不含Cmd+1…7增量，重建与窗口验证同轮执行。测试窗口82716/66949保持打开，后续按完整路径+环境变量现场识别。

**E01源级四项**（详见[验证记录](verification-e01-remaining-2026-11-01.md)）：①受控raw工具（设计§4.2）：`ctflab_kali_attach.py`白名单ping/nmap、固定路径+过程内摘要复核、参数逐旗标校验+目标限会话网段、`ip netns exec`+setpriv仅`net_raw`+NNP、`RAW_CHILDREN`进程归属/回收/超时终止/撤网终止/status计数；无sudo、无CAP_SYS_ADMIN shell、无可继承能力旁路。②缺PID旧unknown受验证恢复：`scan_relay_pid`命令行身份扫描（Darwin/Linux，桥接程序+external-relay+完整会话UUID三重匹配），采信PID/确认缺席/不可用None/多匹配拒绝四态；Windows无完整argv枚举保持pid-unknown不冒充。③助手持久批准账本（设计§4.3）：登记助手摘要必须等于本机材料清单摘要，私有0700/0600追加式JSONL+fsync，同节点+机器+摘要幂等；CLI`external-attach approve`+`connect --approvals-dir`强制核验；损坏行整体拒绝。④生产组合测试：并发三会话隔离、重启+过期租约、断流+清理。

**撤网竞态修复（既有缺陷，本轮发现并修复）**：worker协作退出（约15–30ms）与dispatch的observe→SIGTERM备份路径竞态，信号可命中正在退出/刚退出的进程（-15），回执不受影响。修复为先等有界协作窗口（10×0.1s）仍存活才SIGTERM；两个"等待期不得占锁/不得覆盖"测试更新观察桩，采纳测试按协作语义更新断言。修复后断开套件6轮全过。Windows路径未动。

**usr-merge代码级核对**：trusted_path逐组件usr-merge链接解析、TOOL/RAW候选双路径、daemon自建目录校验、安装指南（含批准第2步、raw第8步）在usr-merge布局下成立；useradd HOME行为、Kali工具版本、systemd实机启动属外部验收。

**验证**：最终全量`full-regression-final.log`＝2360项、0失败、23条件跳过（406.408s），终结摘要完整（较上轮+25项为本轮新增）；第一轮`full-regression-e01.log`含未修复竞态的3项失败，保留不计通过。本轮直接重跑：Kali助手61项、E01全套267项、桥接36项、GUI 25项、swiftc typecheck、8文件AST、git diff --check。证据目录`output/mac-workbench-audit-20261101/`（含draft-roundtrip.json、两轮全量日志、审计scope）。

**边界与继续**：真实Kali部署（助手+raw工具实际能力+usr-merge工具版本）、QEMU hub+真实靶机、GUI账本接线与窗口级UI复核、最终包重建、E01实机矩阵、W01—W06/L01/G0/G1等照旧保留，不因源级落地改称完成。GUI/桌面hub路径的批准强制点（保存登记/连接自动核验）仍是实施缺口。审计环境合成实例未prepare/start。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态标题"163. E01剩余源级四项…"、`verification-e01-remaining-2026-11-01.md`与剩余矩阵，核对Git/文件/窗口现场，保留改动。下一步可做：GUI批准账本接线、窗口级UI复核（需CUA/用户）、最终包重建；真实Kali/实机矩阵需具体授权。不自动操作用户VM、不清理测试窗口、不提交推送发布。

## 164. 桌面连接批准强制接线与收口补记（2026-11-01）

承接第163节。桌面桥接`external-attach-connect`接入设计§4.3持久批准强制：`approval_ledger_dir()`统一解析（`CTFLAB_EXTERNAL_ATTACH_APPROVALS`＞`CTFLAB_PROFILE_DIR/external-attach`＞用户默认profile），未批准一律identity-unknown拒绝且不派发worker；`ctflab.py external-attach approve`默认目录同源；Mac外部攻击机卡片在prepared命令区显示批准要求与固定命令（typecheck通过、GUI 25项通过）。测试：桌面接入16项（新增未批准拒绝+批准后放行）、Windows relay夹具补批准、E01全套277项。最终全量`full-regression-final.log`＝2361项、0失败、23条件跳过（403.826s）；随后Swift批准提示typecheck+GUI 25项通过（该提示为纯UI文本，不改Python全量覆盖范围）。仍开放：真实Kali部署、Windows宿主默认账本目录适配（须显式环境变量）、React桌面端提示、窗口级UI复核、最终包重建、G0/G1。无提交/推送/发布；测试窗口82716/66949保持打开。

## 165. React桌面批准提示与阶段收口补记（2026-11-01）

`desktop/src/ExternalAttach.jsx` prepared命令区加入与Mac一致的助手安装批准要求提示；React模型测试81项通过、vite build通过（dist仅本地）。本轮（§163—§165）全部交付为源码+本地测试+文档，无提交/推送/发布；全量基线2361项0失败。窗口级UI复核（CUA/用户会话）、最终包重建、真实Kali部署与实机矩阵、Windows宿主账本目录适配、G0/G1照旧保留。测试窗口82716（final-preview，状态根/private/tmp/ctflab-workbench-window-20261101）与66949（初版preview）保持打开，须按完整路径现场识别；审计环境`output/mac-workbench-audit-20261101/`与其状态根保留。

## 166. 现场变更补记：测试窗口进程已退出（2026-11-01）

收尾核验发现会话开始时保持打开的两个测试窗口进程（82716 final-preview、66949 初版preview）在本会话期间已自行退出；本轮未向其发送任何信号或交互，退出原因未查（可能为用户关闭或系统行为）。状态根`/private/tmp/ctflab-workbench-window-20261101`与`/private/tmp/ctflab-workbench-audit-20261101`及`output/mac-workbench-20261101/`证据文件均完好保留。§163/§165中"窗口保持打开"的描述自本节起失效；后续窗口级UI复核须以`final-preview/CTFLab.app`完整路径+独立状态根重新启动（审计包装App在`output/mac-workbench-audit-20261101/window-test/`），不引用任何历史PID。无用户VM/真实网络操作，无提交/推送/发布。

## 167. PD Kali r4实机验收通过、nmap白名单修正与预览包重建（2026-11-01）

用户当日授权三项并已执行其一：①PD Kali部署（本轮完成）；②CUA窗口级复核（用户将启用，待执行）；③指定Windows x64实机（已备G0清单）。

**r4实机验收（详见[验证记录](verification-kali-r4-2026-11-01.md)）**：Kali Rolling内核6.17.10、usr-merge、OpenSSH 10.2p1。用户控制台sudo执行deploy.py（自动建ctflab-attach账户、独立目录、forced-command、systemd-run daemon）。真实内核证据：①受控raw工具ping 3/3成功（ambient授予的CAP_NET_RAW生效）；②白名单外工具/未登记旗标/网段外目标全部`raw-tool-rejected`；③实验shell `CapEff/CapBnd全零、NoNewPrivs=1、uid=997`，netns内仅lo+TAP；④teardown session-closed/leftover=[]，cleanup后目录/服务/密钥条目/账户全清；⑤持久批准经r4真实材料闭环（manifest_sha256 35254e9e…绑定6537755f…，摘要不符拒绝）。

**重大发现与修正**：Kali的/usr/bin/nmap为shell包装+`cap_net_admin,cap_net_raw=eip`文件能力，内核对NNP进程exec带filecap二进制一律EPERM——nmap从RAW_TOOLS白名单移除（首版只声明已测工具，指南说明原因），白名单边界同时获真实内核证明。**附带修复**：客户端CLI `nargs=REMAINDER`贪婪吞掉--session/--tool（亦影响shell入口）→parse_known_args，新增回归测试。r4部署脚本三轮现场修复（账户/路径判据/回执落盘/EOF竞态）。

**预览包重建**：`output/mac-workbench-audit-20261101/final-preview/CTFLab.app/CTFLab.app`——含Cmd+1…7与批准提示，1311文件/73动态库/QEMU 11.1.0/Python 3.12.15/PyYAML 6.0.3，ad-hoc未公证；app verify通过、许可证完整；源码7文件（GUI/助手/桥接/CLI）与工作区位级一致（source-evidence.json）；运行时/PyYAML/许可证文本位级复用上轮包内件（来源不变）。审计包装App已指向新包并启动验证。

**验证**：最终全量`full-regression-final.log`＝2362项、0失败、23条件跳过（405.4s）；r4前后受影响93项通过；React 81项+build、GUI 25项、typecheck通过。G0执行清单已备：`docs/ctflab-g0-acceptance-plan-2026-11-01.md`（待用户设备）。

**边界**：帧泵端到端/QEMU hub/真实靶机矩阵未在本轮重测（r3切片属旧源码版本）；持久批准GUI全流程属窗口级；长租约/并发实机组合未重测；nmap替代工具待设计。Kali遗留`~/ctflab-r4/`（用户目录脚本+回执）；r4 SSH授权已在cleanup撤销；PD电源策略未改（验收中两次自动挂起均按授权恢复）。无提交/推送/发布。

## 168. 预览包对齐最终源码重建（2026-11-01收口补记）

§167的重建包不含随后的nmap白名单修正——已用最终源码再次重建`output/mac-workbench-audit-20261101/final-preview/CTFLab.app/CTFLab.app`（app build+verify通过、许可证完整、73动态库），7文件源码与工作区位级一致（source-evidence.json all bundle_matches=true，含nmap移除与CLI解析修复），审计包装窗口已重启至该包（新PID现场识别）。此包为本轮最终预览交付：0.1.4/ad-hoc/未公证/未发布。

## 169. r5交接文件落盘与用户侧待办确认（2026-11-01收口）

CUA第四次探测仍不可用；两次AskUserQuestion用户未应答（离席）。两项待办均为用户侧条件：①窗口级五项复核——执行脚本`output/mac-workbench-audit-20261101/cua-verification-plan.md`就绪，CUA可用的任一会话或用户手动执行均可，审计窗口以最终包运行就绪；②G0——清单就绪，等实机信息。新落盘`docs/ctflab-zcode-handoff-r5-20261101.md`为下一会话接续prompt（已闭合清单/待用户条件/后续依赖/边界全列）。除上述两项外，本轮无剩余可独立推进项；43项其余行均为证据缺口或条件阻塞，不重复开工。无提交/推送/发布。

## 170. 用户启用CUA与复核移交（2026-11-01收口）

用户确认已在ZCode设置启用计算机控制——该能力对新会话生效，本会话执行通道固定（第七次探测仍不可用）。经用户选择，窗口级五项复核移交新会话执行：`docs/ctflab-zcode-handoff-r5-20261101.md`顶部已加入可直接粘贴的复核专项接续语（含目标/入口/判据/禁止事项/回灌核对），审计窗口以最终预览包运行中（现场识别）。G0实机信息用户选择"现在提供"但未附明细，接续语外仍需催收。本会话到此收口：全部可独立实施工作已完成，全量基线2362项0失败，无提交/推送/发布。

## 171. 新会话复核启动确认与G0明细延后（2026-11-01最终收口）

用户确认：①已开新聊天并粘贴r5粘贴语，五项窗口复核由新会话以CUA执行（本会话通道固定不可用，移交完成）；②G0实机四项明细稍后提供（清单docs/ctflab-g0-acceptance-plan-2026-11-01.md保留待用）。本会话职责到此结束：窗口复核结果由新会话按cua-verification-plan.md存证至window-verify/并写入其验证记录；本会话不再重复探测。审计窗口（PID 86575）保留供新会话绑定，后续按现场识别。全量基线2362项0失败；工作区全部改动保留；无提交/推送/发布。

## 172. 当前源码帧泵端到端重测：环境就绪待一轮控制台（2026-11-01）

回应"r3切片属旧源码版本"的开放项：已按r3探针架构搭建**当前工作区源码**的帧泵端到端重测——`output/kali-deploy-r4-20261101/pd-frame-pump-revalidate.py`（导入当前tools/的run_relay+DHCPServer；真实SSH数据面+真实TAP/netns+两个回环应答器；ICMP/ARP/UDP双向+心跳17秒判据）。已预计算真实policy摘要`14d44d15…`回填setup绑定（避免r3式合成摘要），deploy.py新增baseline阶段采DMI身份。**时序错位一次**：用户第一轮执行发生在修正摘要推送前且已teardown；修正版install-config已推送（23:11）。待用户一轮：deploy→baseline→setup（我跑探针约45秒）→teardown→cleanup。新会话窗口复核进行中（window-verify/已出现01-launch.png等存证，不干涉）。无提交/推送/发布。

## 173. 窗口复核存证核验与GUI导出回灌闭环（2026-11-01）

新会话五项窗口复核进行中/近完成：`window-verify/` 已有15项存证（01-launch、尺寸系列、05-cmd-1…7、06-save-panel/06-diff-validated、07-gate-start-disabled门禁、draft-export-gui.json）。本会话对**GUI实际导出物**独立核验：draft-export-gui.json（save panel真实导出）含client cpus=2，经生产`draft_diff`回灌＝applied:false、差异恰1项`/nodes/client/cpus 1→2`、账本generations=0——save panel→导出→后端链路完整闭环，与前轮CLI级证据同判据。复核记录正文由新会话回填（其职责）；本节登记宿主侧交叉核验结果。帧泵端到端重测环境就绪（Kali已恢复可达），待用户三条控制台命令。G0明细待用户。无提交/推送/发布。

## 174. 窗口级五项复核收口：三项通过、两项环境受限（2026-11-01，CUA复核会话）

本会话（§171移交的CUA复核会话）五项复核完成，详见[验证记录](verification-mac-window-verify-2026-11-01.md)与`window-verify/`（20个证据文件）。**通过**：①启动观察（1512×916≥min、七导航+Cmd标注、splitter=320、01-launch.png）；③深色模式（经系统设置App的AX按钮切换，四页语义色自适应无白底残留，浅色已恢复且defaults复核）；④Cmd+1…7七页依次切换正确（7/7截图+窗口标题核对；**方法发现：主窗口键盘投递不需要前台，失败仅限NSOpenPanel/save panel的XPC键路由**）；⑤草稿导出全闭环（读取代次0→载入三节点双网段四连线→client CPU 1→2→后端校验差异恰1项→save panel保存→落盘cpus==2→生产bridge draft_diff回灌applied=false/差异1项/账本两轮generation=0→门禁抽查disabled启动按钮无请求发出）。§173宿主侧交叉核验与本会话结果一致，互证成立。**环境受限（三次独立复现，不冒充完成）**：40夹具经文件面板载入（长列表滚动/搜索11项）与多档窗口resize——本机ZCode全屏遮挡主屏致真实指针落点无效、exec包装进程无法持久前台（CUA枚举pid=-1）、面板键盘与文件列表AX不可达；补足方式=窗口前台或退出ZCode全屏后按脚本重跑1b与2的多档两项（已通过项无需重跑）。save panel默认位置保存后经shell移入window-verify/（位置差异如实记录，往返判据不受影响）。边界：未操作用户VM/真实网络/历史现场，未确认生命周期弹窗，未提交/推送/发布；系统外观开始浅色结束浅色；审计窗口PID 86575与状态根保持原状。

## 174. 新会话窗口复核记录确认（2026-11-01）

新会话已交付`verification-mac-window-verify-2026-11-01.md`（20项存证）：**启动观察通过**（AX frame 1512×916≥min、七导航+Command标注）、**深色模式通过含恢复**（系统设置AX路径、defaults复核）、**Cmd+1…7通过7/7**（主窗口键盘投递不需前台）、**草稿导出save panel往返+后端回灌+门禁通过**（disabled生命周期按钮无请求、账本零代次——与本会话§173交叉核验一致）。**两项环境受限未冒充**：NSOpenPanel长列表载入（1b）与多档resize（2部分）——根因为ZCode主窗口全屏覆盖致审计窗口后台化（面板XPC键等价与文件列表AX不可达），三次独立复现记录在案。解锁路径已留：审计窗口置前台后重跑两项，或退出ZCode全屏。主窗口级发现（Cmd快捷键无需前台）本身是有价值的键盘验收证据。

## 175. 补跑路径确认与等待状态（2026-11-01）

补跑技术核查：审计App的defaults域为空，且`GuiState.distDir`不经UserDefaults持久化（仅NodeLibraryPreferences的收藏/分组/最近使用持久化）——文件选择面板是distDir唯一设置途径，**置前台补跑是长列表项的必需路径**，无绕过实现。当前三项均待用户：①新会话置前台补跑1b长列表+多档resize（用户已选择，执行中）；②Kali帧泵轮三条控制台命令（环境就绪，VM按需恢复）；③G0实机四项明细。文档至§175，无提交/推送/发布。

## 176. 当前源码帧泵端到端重测通过（2026-11-01）

§172就绪项执行完毕。**当前工作区源码的run_relay全链在真实Kali 6.17.10上通过**：SSH握手+身份verified（assistant摘要6537755f+DMI绑定）、受控raw ping **3/3 ICMP回显往返**（TAP→SSH帧泵→交换机→节点→回程，节点侧计数）、UDP双节点往返、17秒空闲存活（超max_idle=15边界）。关键修正：**数据面身份必须为专用账户**——数据密钥从zhangpu迁移至/home/ctflab-attach/.ssh（forced attach+restrict），与设计§4.3一致；setup绑定严格四键+真实policy摘要14d44d15预计算回填。详见[验证记录](verification-frame-pump-r5-2026-11-01.md)。合成应答端非真实靶机、hub预留口路径/两平台组合未覆盖（边界照旧）。**待用户最后一条撤键**：sudo sh -c '> /home/ctflab-attach/.ssh/authorized_keys'（非forced shell密钥仍活跃）。无提交/推送/发布。

## 177. r5帧泵轮最终收口与残留授权项（2026-11-01）

r4/r5验收与清理核验：daemon inactive、r4目录/netns全清、ctflab-attach账户及主目录已随cleanup删除（userdel --remove，数据/shell密钥随之失效——SSH实测Permission denied×2）、zhangpu名下数据密钥条目已移除。**唯一残留**：operator诊断密钥（restrict,from="192.168.0.122"限定，注释ctflab-deploy-r4-20261101）仍在zhangpu authorized_keys——撤键命令已交付用户两次（sudo下~展开为/root的路径错误一次；重试待执行），SSH实测仍可达。下次会话或用户可随时以`grep -v ctflab-deploy-r4 /home/zhangpu/.ssh/authorized_keys`显式路径撤销；该密钥限定来源IP、无root权限，风险边界明确。帧泵端到端（当前源码）证据闭环见§176与[验证记录](verification-frame-pump-r5-2026-11-01.md)。窗口级复核剩余两项补跑（置前台）与G0明细仍待用户。无提交/推送/发布。

## 178. operator密钥撤销核验与Mac侧私钥销毁（2026-11-01）

用户执行撤键意图明确但命令两次未生效（sudo遗留root属主ak.tmp阻断重定向+grep -v全过滤返回码1中断&&链）——经既有SSH通道代为执行修正版（新临时名+mv，`|| true`吸收grep返回码），authorized_keys清空后**SSH实测Permission denied**。Mac侧三把r4/r5私钥已销毁（摘要前缀记录于output/kali-deploy-r4-20261101/ssh-auth/revocation-record.json；公钥与回执保留作审计）。Kali侧残留：0字节root属主ak.tmp（cosmetic，用户可rm）。至此r4/r5全部临时授权彻底撤销。窗口两项补跑与G0明细仍待用户（§175入口不变）。无提交/推送/发布。
