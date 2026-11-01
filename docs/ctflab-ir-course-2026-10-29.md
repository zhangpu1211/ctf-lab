# C06 Windows应用应急现场、封存与派生处置源码（2026-10-29）

本轮补C06独立可运行教学内容与Windows事件适配源码。课程是教师明确触发的自建应用错误配置，不运行恶意样本、不猜测账户失陷；具备“观察业务故障→保存原现场→另建派生材料→处置→复验→本课基线恢复”的代码链路。当前仅Mac自有回环HTTP/文件与Windows API替身验证，真实Windows来宾/EVTX/课堂/整课VM重置尚未验，C06整体不关闭。

## 场景与边界

ctflab_ir_course.py提供新目录材料、明确activate、状态、变更预览/执行、未知观察/收口、capture、derive及固定回环服务。incident把本课私有配置改为维护状态和无效教学联系地址；业务/返回503而/health仍200。健康端只表示本次进程能应答，不证明业务正常或系统健康。HTTP不提供变更接口、文件浏览或命令入口；只监听来宾127.0.0.1，拒绝任意目标/请求体，不增加对外监听或宿主路由。

生产入口必须位于本套runtime中，绑定专用Windows虚拟来宾SMBIOS UUID、课程UUID/代次、当前用户私有权限、运行时/配置/密钥/根身份。Mac/错误机器拒绝。新目录不会自动激活；activate要求execute，仅建立根身份，不发Windows事件、不启服务。材料不含Windows镜像、Python、凭据或安装器，不创建VM、不调整服务/注册表/网络/卷/ACL；Windows普通用户读写权限和运行时闭包仍须实测。

已有课程/镜像/日志不被覆盖。基线与初始配置保留，变更写全新操作目录，保存原HEAD原字节、意图、目标配置和尝试标记，再以原HEAD摘要/CAS更新指针；旧配置/操作不删除。最多32次变更，不能以reset清空预算或历史。本课reset仅恢复自建应用配置，**不是VM整课重置**，也不停止服务/进程或清Windows日志；正式代次/磁盘重置继续由既有S03流程和授权执行。

## 自有Windows事件

ctflab_windows_course_events.py使用固定宽度ctypes与System32 DLL，只有本地Application、固定CTFLabC06源及1001/1002/1003三类事件。只读检查经典事件日志注册表，不创建/修改/删除事件源键；任意日志下已有同名注册源时拒绝接管。Microsoft说明未注册源会默认写Application且可能缺少可显示的消息描述；这不等于原始记录不存在。[事件源说明](https://learn.microsoft.com/en-us/windows/win32/eventlog/event-sources)

每条记录含课程/代次/操作/配置摘要及私有HMAC，签名绑定机器/范围/动作/目标状态；密钥不导出，不把自报字段或普通Provider名称当成来源认证。事件表示变更准备，不单独证明本地HEAD已提交；UTC意图/尝试/收据时间只来自来宾时钟，不当作独立时间锚。ReportEvent失败或回执丢失留下未决尝试，不换ID自动重报。句柄在异常路径也尝试释放，关闭失败不能计为成功。[ReportEvent接口](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-reporteventw)

查询只选本源、本lab_uuid/代次，最多128条，单条XML缓冲最多64KiB；拒绝DTD/实体、错误范围/签名/事件ID/重复记录。查询在同一线程中遍历并逐个关闭事件/查询句柄，XML使用显式UTF-16字节缓冲而非假定测试宿主wchar宽度。[EvtQuery](https://learn.microsoft.com/en-us/windows/win32/api/winevt/nf-winevt-evtquery)、[EvtNext](https://learn.microsoft.com/en-us/windows/win32/api/winevt/nf-winevt-evtnext)、[EvtRender](https://learn.microsoft.com/en-us/windows/win32/api/winevt/nf-winevt-evtrender)

EVTX导出固定到新文件，以已经观察的RecordID上下界封闭范围；不容忍部分查询错误、不覆盖、不清日志、不导入或执行EVTX。导出前后复核同一范围的记录与XML摘要，未来新增记录不属于这个封闭范围。EVTX生成后限16MiB，这不是内核文件写入硬配额或全系统抓取。[EvtExportLog及目标文件规则](https://learn.microsoft.com/en-us/windows/win32/api/winevt/nf-winevt-evtexportlog)

## 未知恢复与原件保全

操作先落意图/配置/Native尝试再报告事件；丢回执、写设置/指针/收据中断都保留现场，新变更受未决栅栏阻止。原操作已有收据时只读返回历史结果，不将其当作当前业务状态。resume-preview重新核对原意图、当前HEAD/原字节摘要、目标文件、精确匹配事件；明确接受当前observation摘要且唯一匹配后，resume仅补本地提交/收据，不再ReportEvent。没有事件、多条匹配、错范围、配置/观察变化都拒绝，不猜测成功或失败。

capture持本课门，复制配置、HEAD、当前/基线及每份操作JSON的原始字节，再收本课EVTX与结构化事件；前后核对HEAD/日志/文件摘要。失败留下INCOMPLETE与部分文件，不能当作完整快照。清单不含密钥或教师答案，不收全Security/System日志、进程内存或磁盘；EVTX包含本课记录的Windows系统元数据，公开分发前仍须另行检查隐私。摘要用于一致性，不自动成为外部可信锚。

derive要求外部保存的原清单摘要、完整捕获、严格文件白名单/数量/大小、无链接/路径逃逸和逐文件摘要；从当前可信源码建立新runtime，不执行捕获内代码或解析EVTX。复制过程中再次核对批准摘要，未写derivation.complete之前不可激活，之后仍核验保存的原证据。必须明确给出**不同的目标来宾UUID**，新lab_uuid/密钥/私有状态与原件分开。真正创建或克隆Windows磁盘/VM不由该命令执行，仍需对应资产与授权。

repair只允许派生材料，并只恢复本课基线；原现场服务应仍503，派生目标应从503恢复200，原封存摘要不变。学生须对照目标状态和Windows事件，区分受控误配置、真实攻击推断及未覆盖范围。本课程文件派生和配置修复不能替代真实Windows系统持久化排查、磁盘/VM克隆、C02/整课一致重置或干净机验收。

## 实际验证与继续入口

事件适配13项：ctypes指针/UTF-16、固定System32函数声明与先验VM身份、只读注册表拒绝同名源、HMAC/范围/ID/XML限制、全部句柄释放、128条/缓冲限制、未知/关闭失败、新文件导出、封闭ID范围和导出中漂移。课程18项：自有HTTP正常200→明确事件503/health200、保全、不同目标UUID派生、修复200且原503、reset、原字节/密钥隔离、丢回执/无记录/重复记录/陈旧观察、提交后缺收据、跨范围/操作冲突、路径/复制中篡改/未封存派生拒绝、宿主CLI拒绝及实际-I材料生成。

真实内核仅为本轮新建私有文件/文件锁/回环HTTP；Windows DLL、注册表、Application记录和EVTX全部由显式替身提供，模拟EVTX不是原生有效文件。没有实际Windows接口调用或原生日志验收。故障注入不等于物理断电。事件时间是替身数据/本机时钟，不推导来宾时钟准确；派生使用两个模拟机器标识，不冒称两台Windows设备互通。

集中完整/独立回归、保全及可重复流程证据见状态第122节与output/ir-course-20261029。仍须在未来获准专用Windows来宾验证普通用户ACL、注册表/ReportEvent权限、实际XPath/EVTX/消息描述、应用/独立副本、采集故障和原生课程重置。缺镜像/设备已知不重复索要，也不因源码齐全将其余43项/G0/G1/graceful_stop_verified改为完成。

本轮未操作用户VM/SSH/Docker、停机/重启、已有资产删除、宿主网络卷/ACL变更、到期调度、原生Windows Smoke、桌面控制、提交推送、交付打包或发布。Mac0.1.3原App与更新器保留，发布包不含115—122节源码，Windows候选。
