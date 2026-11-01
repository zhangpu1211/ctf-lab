# 原43项完成判据审计（2026-10-29）

后续进展（第132节，2026-10-30）：已补VMGenID可选声明、私有随机材料/代次GUID、QEMU设备与工作器/QMP绑定的候选源码；真实设备/Windows/无伙伴域恢复仍未验。下表与requirements-audit.json保留第131节审计当时的源码快照，不把历史“未实现”描述冒充第132节后的最新源码，也不覆盖原审计摘要。

本轮以[原实施backlog](ctflab-implementation-backlog-2026-10-15.md)的43个任务ID、最小交付、完成判据和显式依赖为准。当前源码和第130节验证是证据入口，历史描述、模块存在、测试总数和候选材料不是整体完成证明。机器记录`output/completion-audit-20261029/requirements-audit.json`保存逐项原文、行号、当前源码摘要、判定和下一份所需证据；不省略条件任务或缺失项。

本轮证明S01原离线解析/计划功能判据，但其所列A02/A03依赖仍未完成关闭，未据此把S01整个任务或其他任务标为最终完成。43项任务级仍未全部关闭/条件未证，不宣称它们都只剩实机验收。整体目标、G0/G1和graceful_stop_verified仍未完成。S01通过也不替代S03运行/停止/恢复或W03最终课程。没有提交、打包、发布或操作现有虚拟机。

## 直接证据及范围纠偏

S01原文最小交付是“scenario-v2通用解析/计划”，原判据是新的三节点双网场景不改核心，以及重复ID/IP/MAC、环路、未知字段拒绝。新增一份与既有样例不同命名/地址/资源的新清单，验证DAG、明确代次路径、资源总量、确定性、输入不变及新代次隔离；负向案例分别只引入一个错误并核对具体拒绝原因，避免重复MAC掩盖重复IP。另实际调用原v1解析/计划，保持Wintermute。19项通过，核心源文件摘要未变。检查期间阻断文件打开/建目录/进程/网络，未操作任何真实磁盘、实例或网络。入口`output/completion-audit-20261029/check_s01.py`，证据`s01-direct-evidence.json`与新清单`s01-fresh-manifest.json`。这是S01原离线判据通过，不是范围缩成小切片后冒充整体完成。

A02历史28组完整Mac argv对照仍保留为历史结果；当前策略测试可查，但本轮没有重建当前28组对照，不能写成重跑。A01完整归属、A03端到端语义也仍需各自证据，不以模块数量关闭。

R02从R01的Linux远程Runner继承范围，原文未要求先实现Mac本机CPU/内存硬上限。该限制仍需对用户准确披露，但不能擅自追加为Linux远程任务的硬前置。R04是确有课程需要时的窄数据通道，任意子网、多跳、默认路由/真实LAN桥接不是默认目标。E02原文要求服务/双向路由/日志采集，不强制EVTX或跨会话持久导出；C06取证EVTX仍独立待验。

C05/C07允许有来源、合法自制的教学样本；不能把生产事故样本或生产WAF当作无依据的新硬门。但C05题目/真值独立分发/调查复盘和C07的D02/O02依赖仍未完成证明。U02不需要上传真实凭据来证明脱敏，使用受控敏感夹具与实际用户路径分别核验。

## 当前逐项判定

下表的源码链接仅表示当前责任入口，不表示其全部功能已验收。具体原文/依赖/摘要保存在机器记录，完成必须对应原判据而不是反推现有实现。

| ID | 当前结论 | 缺口或证据边界 | 当前责任入口 |
|---|---|---|---|
| A01 | 未关闭，证据不闭环 | 原调用族/接口清单已有；新增适配链的当前完整归属覆盖未逐调用核对。 | [ctflab.py](../tools/ctflab.py)、[ctflab_platform.py](../tools/ctflab_platform.py)、[ctflab_qemu_driver.py](../tools/ctflab_qemu_driver.py) |
| A02 | 未关闭，证据不闭环 | 纯策略和三处builder接入存在，当前策略测试通过；28组完整Mac参数对照是历史证据，本轮未重建当前对照。 | [ctflab_platform.py](../tools/ctflab_platform.py)、[test_ctflab_platform.py](../tools/tests/test_ctflab_platform.py) |
| A03 | 未关闭，证据不闭环 | 持久幂等/状态分层/错误/事件和GUI接入已有大量本地证据，端到端语义与实际重开/断线仍未完整证明。 | [ctflab_contract.py](../tools/ctflab_contract.py)、[ctflab_local_service.py](../tools/ctflab_local_service.py)、[ctflab_generation_store.py](../tools/ctflab_generation_store.py) |
| W01 | 未关闭，证据不闭环 | 已有用户Windows Smoke历史；固定组合完整G0负向/重连/异常监督/归属证据不足。 | [ctflab_windows_probe.py](../tools/ctflab_windows_probe.py)、[ctflab_windows_smoke.py](../tools/ctflab_windows_smoke.py)、[ctflab_windows_control.py](../tools/ctflab_windows_control.py) |
| W02 | 未关闭，证据不闭环 | 原生进程/ACL/锁/无覆盖存储/端口适配器有源码与替身，真实负向矩阵未闭环。 | [ctflab_windows_native.py](../tools/ctflab_windows_native.py)、[ctflab_windows_security.py](../tools/ctflab_windows_security.py)、[ctflab_windows_storage.py](../tools/ctflab_windows_storage.py) |
| W03 | 未关闭，证据不闭环 | 最终合法Windows运行时/固件/显示依赖闭包和双节点完整C01未交付验收。 | [ctflab_qemu_driver.py](../tools/ctflab_qemu_driver.py)、[ctflab_desktop_package.py](../tools/ctflab_desktop_package.py)、[ctflab_runtime_inventory.py](../tools/ctflab_runtime_inventory.py) |
| W04 | 未关闭，证据不闭环 | 薄壳/桥接/进度/取消/重连存在，干净Windows和关窗存续未验。 | [main.jsx](../desktop/src/main.jsx)、[main.rs](../desktop/src-tauri/src/main.rs)、[transport.rs](../desktop/src-tauri/src/transport.rs) |
| W05 | 仍缺实现与后续证据 | 独立CLI/版本库/签名/在线准备已有；最终原生安装管理引导、版本库布置/迁移/独立入口及安装卸载保留策略仍未形成最终产品闭环。 | [Build-Windows.ps1](../desktop/Build-Windows.ps1)、[tauri.conf.json](../desktop/src-tauri/tauri.conf.json)、[Versions.jsx](../desktop/src/Versions.jsx) |
| W06 | 未关闭，证据不闭环 | 设备/最终包/至少5名非开发者与三轮重置课堂记录缺少。 | [ctflab-windows-plan-2026-10-15.md](../docs/ctflab-windows-plan-2026-10-15.md) |
| S01 | 原离线判据已证 | 本轮19项直接证据证明原离线解析/计划判据；不存在把硬件/课堂验收追加到S01的依据。 | [ctflab_scenario_v2.py](../tools/ctflab_scenario_v2.py)、[ctflab_scenario.py](../tools/ctflab_scenario.py)、[test_ctflab_scenario_v2.py](../tools/tests/test_ctflab_scenario_v2.py) |
| S02 | 未关闭，证据不闭环 | 精确变体/兼容策略已实现；已验收Kali变体落入真实课程计划、旧包保全的完整证据不足。 | [ctflab_catalog.py](../tools/ctflab_catalog.py)、[ctflab_dist.py](../tools/ctflab_dist.py) |
| T01 | 未关闭，证据不闭环 | Mac设计拓扑有历史真实界面证据，设计与实际代次/过期运行状态全过程仍未核验。 | [GuiApp.swift](../gui/GuiApp.swift)、[GraphEditor.jsx](../desktop/src/GraphEditor.jsx)、[ctflab_topology.py](../tools/ctflab_topology.py) |
| T02 | 未关闭，证据不闭环 | 草稿/差异/编辑/往返代码与Mac旧包局部交互已证；新代次可执行模板门未完成。 | [graph-model.mjs](../desktop/src/graph-model.mjs)、[GraphEditor.jsx](../desktop/src/GraphEditor.jsx)、[GuiCore.swift](../gui/GuiCore.swift) |
| S03 | 未关闭，证据不闭环 | 多节点事务/停止证明/恢复源码与合成故障已覆盖；真实全部节点、磁盘/NVRAM/账本一致与两实例隔离未验。 | [ctflab_generation_store.py](../tools/ctflab_generation_store.py)、[ctflab_scenario_coordinator.py](../tools/ctflab_scenario_coordinator.py)、[ctflab_qemu_driver.py](../tools/ctflab_qemu_driver.py) |
| S04 | 未关闭，证据不闭环 | 受管路由/DNS/时间规则和部署材料存在；真实来宾默认不转发/按向矩阵/重置恢复未验。 | [ctflab_guest_policy.py](../tools/ctflab_guest_policy.py)、[ctflab_guest_agent.py](../tools/ctflab_guest_agent.py)、[ctflab_guest_routes.py](../tools/ctflab_guest_routes.py) |
| P01 | 未关闭，证据不闭环 | 元数据/验证等级/离线目录已有，真实首版课程来源许可/架构/资源/入口证据仍待对应。 | [ctflab_catalog.py](../tools/ctflab_catalog.py)、[ctflab_offline.py](../tools/ctflab_offline.py) |
| P02 | 未关闭，证据不闭环 | 签名/partial/源变化/过期等代码与自建TLS小文件已证；真实大文件与故障/离线课程未验。 | [ctflab_content_cache.py](../tools/ctflab_content_cache.py)、[ctflab_mirror_service.py](../tools/ctflab_mirror_service.py) |
| P03 | 未关闭，证据不闭环 | 引用/预算/代次/证据保全和逐对象回收源码存在，真实空间/引用图/物理失败与Windows持久性未验。 | [ctflab_content_cache.py](../tools/ctflab_content_cache.py)、[ctflab_storage_boundary.py](../tools/ctflab_storage_boundary.py)、[ctflab_storage_bind.py](../tools/ctflab_storage_bind.py) |
| P04 | 未关闭，证据不闭环 | 许可学生材料与仅回环HTTPS/真实小文件续传已证；校内实际服务部署/外部读取/长期运维仍缺。 | [ctflab_mirror.py](../tools/ctflab_mirror.py)、[ctflab_mirror_service.py](../tools/ctflab_mirror_service.py) |
| D01 | 未关闭，证据不闭环 | OCI/digest/受限声明与代次源码已具备；真实终端+Web+DB运行/重置与身份故障未验。 | [ctflab_oci.py](../tools/ctflab_oci.py)、[ctflab_guest_agent.py](../tools/ctflab_guest_agent.py)、[ctflab_guest_policy.py](../tools/ctflab_guest_policy.py) |
| D02 | 未关闭，证据不闭环 | 网关/命名空间/veth/规则有源码与替身，真实双向、默认出口/IPv6/宿主/控制面隔离未验。 | [ctflab_guest_routed.py](../tools/ctflab_guest_routed.py)、[ctflab_guest_routes.py](../tools/ctflab_guest_routes.py)、[ctflab_guest_policy.py](../tools/ctflab_guest_policy.py) |
| D03 | 未关闭，证据不闭环 | 统一代次/意图/失败保全存在，真实卷初始数据恢复与半创建/停止/提交故障未验。 | [ctflab_generation_store.py](../tools/ctflab_generation_store.py)、[ctflab_guest_agent.py](../tools/ctflab_guest_agent.py)、[ctflab_oci.py](../tools/ctflab_oci.py) |
| L01 | 未关闭，证据不闭环 | 固定Linux原生适配与KVM候选存在，无最终发行版包/普通用户真实单多节点记录。 | [ctflab_linux_native.py](../tools/ctflab_linux_native.py)、[ctflab_cgroup.py](../tools/ctflab_cgroup.py)、[ctflab_qemu_driver.py](../tools/ctflab_qemu_driver.py) |
| R01 | 未关闭，证据不闭环 | 受限固定SSH/角色/版本/持久意图和状态具备，真实SSH断网/身份变化/恢复尚未验。 | [ctflab_remote.py](../tools/ctflab_remote.py)、[ctflab_remote_assets.py](../tools/ctflab_remote_assets.py)、[ctflab_remote_audit.py](../tools/ctflab_remote_audit.py) |
| R02 | 未关闭，证据不闭环 | 显示/租约/限额/日志证据有源，真实期限/CPU内存PID存储压力与故障未验。 | [ctflab_remote_display.py](../tools/ctflab_remote_display.py)、[ctflab_remote_leases.py](../tools/ctflab_remote_leases.py)、[ctflab_lease_scheduler.py](../tools/ctflab_lease_scheduler.py) |
| E01 | 未关闭，证据不闭环 | 外部Kali固定SSH/TCP/UDP/点对点IPv4/ICMP差错已有；真实DNS/MTU/回连/退出清理/共存组合未验。 | [ctflab_external.py](../tools/ctflab_external.py)、[ctflab_external_ip.py](../tools/ctflab_external_ip.py) |
| E02 | 未关闭，证据不闭环 | 受控Windows点对点端点与只读日志XML已实现，原生服务/双向路由/日志采集/共存未验。 | [ctflab_external.py](../tools/ctflab_external.py)、[ctflab_windows_ip.py](../tools/ctflab_windows_ip.py)、[ctflab_external_events.py](../tools/ctflab_external_events.py) |
| E03 | 未关闭，证据不闭环 | 跨节点恢复收据和健康名称白名单有源；C04依赖及跨运行器全域/成员/业务实际检查未闭环，不额外强制新自动域检查器。 | [ctflab_external.py](../tools/ctflab_external.py) |
| R03 | 未关闭，证据不闭环 | 角色/课程登记/实例分配/审计入口已在React和Mac存在，不能仅因简化界面就认定完全没有产品入口；多用户实测缺失。 | [ctflab_remote.py](../tools/ctflab_remote.py)、[ctflab_remote_course.py](../tools/ctflab_remote_course.py)、[RemoteAdministration.jsx](../desktop/src/RemoteAdministration.jsx) |
| R04 | 按课条件未证 | 原文是确有课程需要才接窄数据通道；是否触发及具体矩阵未确证，不能擅自要求任意子网/多跳/默认路由。 | [ctflab_external_ip.py](../tools/ctflab_external_ip.py)、[ctflab_remote.py](../tools/ctflab_remote.py) |
| C01 | 未关闭，证据不闭环 | 样板配置/准备路径存在，合法精确资产和新手最终包完整课堂闭环仍缺。 | [ctflab_catalog.py](../tools/ctflab_catalog.py)、[ctflab_guest_kit.py](../tools/ctflab_guest_kit.py) |
| C02 | 未关闭，证据不闭环 | 配方/能力结构与原生事件适配有源，真实合法Windows桌面/服务/登录/重启/日志/重置未验。 | [ctflab_external.py](../tools/ctflab_external.py)、[ctflab_catalog.py](../tools/ctflab_catalog.py) |
| C03 | 未关闭，证据不闭环 | 三节点双网计划与路由源码已存在；课程实际任务/可达矩阵/初态恢复未验。 | [ctflab_guest_policy.py](../tools/ctflab_guest_policy.py)、[ctflab_guest_routes.py](../tools/ctflab_guest_routes.py)、[ctflab_scenario_v2.py](../tools/ctflab_scenario_v2.py) |
| C04 | 仍缺实现与后续证据 | 当前只有外部健康名称/恢复收据；原v2节点字段和QEMU驱动没有VMGenID设备/代次绑定实现。单DC/全域无伙伴连续恢复和域检查结果还缺真实环境；原文未强制自动检查器。 | [ctflab_external.py](../tools/ctflab_external.py)、[ctflab_qemu_driver.py](../tools/ctflab_qemu_driver.py) |
| C05 | 未关闭，证据不闭环 | 已有合法自制合成证据与答案分发基础；本轮未证明题目→只读原件→答案独立→调查复盘的全链。 | [ctflab_evidence_course.py](../tools/ctflab_evidence_course.py) |
| O01 | 未关闭，证据不闭环 | 限额捕获/时间线/导出有源，真实捕获边界、丢包/截断及代次链未验。 | [ctflab_evidence_export.py](../tools/ctflab_evidence_export.py)、[ctflab_network.py](../tools/ctflab_network.py) |
| O02 | 未关闭，证据不闭环 | 版本自述/内容指纹/流式归档/独立校验容器存在，固定合法分析镜像/规则与真实恶意畸形隔离复现未验。 | [ctflab_guest_analysis.py](../tools/ctflab_guest_analysis.py) |
| C06 | 未关闭，证据不闭环 | 现场封存/原生事件适配/派生处置已有；Windows原生事件/EVTX、不同VM派生、整课调查处置验证重置未验。 | [ctflab_ir_course.py](../tools/ctflab_ir_course.py)、[ctflab_windows_course_events.py](../tools/ctflab_windows_course_events.py) |
| C07 | 未关闭，证据不闭环 | 自制WAF观察/阻断/误报已有实际自有回环5例证据，D02/O02组合与整课流程未验。 | [ctflab_waf_course.py](../tools/ctflab_waf_course.py) |
| U01 | 未关闭，证据不闭环 | 教程/准备流程有，最终包至少5名非开发者C01和失败介入复验缺。 | [ctflab-student-distribution-tutorial.md](../docs/ctflab-student-distribution-tutorial.md)、[ctflab-community-workflow-2026-10-23.md](../docs/ctflab-community-workflow-2026-10-23.md) |
| U02 | 未关闭，证据不闭环 | Mac/React/CLI白名单预览与精确新文件保存已具备本地证据；真实用户导出/预览流程未验，原私密报告不等于公开摘要。 | [ctflab_diagnostics_public.py](../tools/ctflab_diagnostics_public.py)、[GuiCore.swift](../gui/GuiCore.swift)、[GuiApp.swift](../gui/GuiApp.swift) |
| U03 | 未关闭，证据不闭环 | 贡献模板和来源结构有，至少一套完整C01公开取得/合法准备及离线验证未整体核验。 | [ctflab-community-workflow-2026-10-23.md](../docs/ctflab-community-workflow-2026-10-23.md)、[ctflab_catalog.py](../tools/ctflab_catalog.py) |
| U04 | 未关闭，证据不闭环 | 维护责任人/复核承诺/私密反馈入口未指定，外部入口未核验；不编造责任或自动创建服务。 | [ctflab-community-workflow-2026-10-23.md](../docs/ctflab-community-workflow-2026-10-23.md) |

## 下一步与仍需外部条件

可在当前开发边界继续的明确动作：先补C04的VMGenID设备声明、实例/代次/恢复绑定和拒绝错误回放，再准备按原文执行的域恢复检查流程；手动检查或受控探针均可，不追加自动检查器硬门。并行时须有明确授权，本轮未派生代理。W05最终安装管理引导/版本库布置/迁移与独立入口仍缺产品闭环，不能把独立CLI当成原生安装器。A02当前28组等价复核、C05自制证据完整调查复盘也可先做，不必等待新的镜像许可。

资源/授权不能由代码或测试替代：固定Windows/Linux实际环境、合法课程/运行时/签名组件、获准SSH端点/账户与来宾、外部虚拟化软件组合、最终安装/课堂至少5名非开发者、维护责任/反馈入口。缺失条件已在状态记录，不重复索要。未获授权不自动停机/重置/删除、改宿主网络卷/ACL、跑实际到期调度、重做Smoke、操作桌面或提交推送/发布。

C04现有Python实现检索只发现ctflab_external的健康名称白名单与对应签名收据测试；v2节点字段无VMGenID，QEMU驱动无该设备/代次参数。字符串“vmgenid-checked”不是设备实现，也不是域检查。审计因此将C04设备/代次绑定明确列为实现缺口，E03还未通过其C04依赖及实际域恢复验收，不能概括整个项目只待实机；原文不强制新增自动域检查器。未因此修改现有运行实例或设备参数。

本轮没有重跑第130节完整2038项/独立1177项/Swift389项；它们作为带日期/源码摘要的既有证据，不充当这次新增19项直接审计的替代。仅文档及显式材料清单变更做文件/语法/白名单检查，不重复无关GUI编译和全回归。状态第131节记录当前保全与恢复入口。


第133节后续进展（2026-10-30）：W05新增版本页首次设置入口、固定宿主数据路径和新私有版本库预览/显式创建/原操作恢复，原Mac更新链保留。专项19项、完整2073项和独立1212项通过（条件跳过分别21/8），前端55项与Rust11项通过；仅POSIX临时状态/SQLite和本机编译，Windows标识注入不是原生安装证据。安装/卸载/签名、最终独立入口/迁移保留与干净机仍未闭环，W05及43项不关闭。原审计表/requirements-audit.json仍为第131节快照，未改写其源文件摘要；最新实现见ctflab-version-setup-2026-10-30.md与状态第133节。


第134节后续进展（2026-10-30）：A02原28组完整Mac argv/端口等价已在当前源码直接重建。预期独立来自固定Git 0994f62的旧内联实现，五份profile原字节一致；新固定SHA夹具/2个测试方法覆盖28子例，原平台11项与场景8项复跑，白名单副本1225项（1217通过/8跳过）及295文件/196 Python/29帮助入口通过。A02自身原离线功能判据已有证据，A01当前调用归属前置仍未关闭，task_fully_closed=false；不追加真实VM为A02硬门，也不关闭S01/A03/W01/G0/G1。原第131节表/JSON保留历史快照，当前证据见ctflab-mac-argv-equivalence-2026-10-30.md及output/mac-argv-20261030/final-evidence.json。


第135节后续进展（2026-10-30）：C05补齐日志/6帧PCAP/360KiB FAT12自制材料、学生独立只读快照/查看器、教师逐条真值与实际完整报告。受控POSIX路径实际运行四次独立学生CLI与统一离线命令；系统tcpdump及只读fsck对普通样本交叉核对，未捕获/挂载/修复，摘要未变。原C05离线功能判据已有逐项直接证据，见output/evidence-workflow-20261030/requirements-evidence.json与replay-02；不再把该源码链列为未实现，也不追加生产事故/公开分发/人类课堂为原离线功能门。最终完整2101项（2080通过/21跳过）、独立1251项（1243通过/8跳过）；未证明Windows原生/跨平台G2、独立课堂或正式公开发行，整体43项/G0/G1仍未完成。原审计表/JSON继续保留第131节快照，不覆盖其旧源码摘要。


第136节后续进展（2026-10-30）：A01当前源级盘点/接口定义已有可复核交付：原六文件及新控制入口14根、85本地导入模块、4薄壳摘要，原始22998 AST调用与3731候选分开；七份逻辑合同、60真实符号、26处同名导入与14处分派记录，附固定源快照复核器。它只核对调用方责任/源码与定义，明确不证明筛选器穷尽动态行为、原生调用图或兼容性。85模块/4薄壳与第135节输入字节相同，本轮合同98项（97通过/1条件跳过）、6负向漂移及独立303文件/201 Python/副本平台11项/28 argv子例通过。A01源级原交付可承接A02；A02原离线判据及其A01源级前置已有当前证据，不额外追加原生测试门。S01仍有A03前置，A03/W01/W02及整体43项/G0/G1均未因此关闭。第131节表/JSON仍为历史快照，不覆盖其摘要。


第137节后续进展（2026-10-30）：A03新增原操作账本只读历史/结果、本机CLI及React重开入口、cancel原请求查询；实际跨进程提交意图后丢响应再退出，新进程读取原pending/无保存响应，数据库摘要不变且不重发。15专项与前端60项/构建通过，完整/副本最终证据见状态第137节末。存储/传输外层未知不再报成确定failed；历史仍明确不证明当前状态。A01原JSON保留为第136节历史，新增r2固定当前85模块/4薄壳、65实际符号，筛选候选不作原生证明。A03原GUI/CLI语义一致仍需完整入口对照，本轮不直接关闭A03；长导入取消归W04，后台长期故障、持锁/旧匿名管道/Windows接收及实际GUI/原生协议按各任务核验，不将它们追加为A03的独立硬门。整体43项/G0/G1不关闭。原第131节表/JSON继续保持历史摘要。


第138节后续进展（2026-10-30）：真实桥接CLI返回事件数组而React按对象读取的实际缺口已复现/修复，并补裁剪游标按本次绑定快照重定位，实际过期0→3→后续6且不重发。90组事件同输入实值对照（29接受/61拒绝）、八类前端构造/全合成生命周期/取消/故障状态对照已完成；合同96项、前端66项/构建通过，最终副本见状态第138节。当前是共享本机协议/模型和受控功能证据，未证明全部原生产GUI/CLI接入或原生窗口，不直接关闭完整A03、43项/G0/G1；W04长导入/后台与各原生门不追加为A03硬前置。Python生产/4薄壳未改，A01 r2继续有效；原第131节审计表/JSON和旧快照保持。
