# C04 VMGenID声明与代次绑定（2026-10-29启动，10-30收口）

第131节确认原C04要求的VMGenID尚未实现。本轮补可选节点声明、实例私有随机材料、代次GUID、QEMU设备参数、工作器与QMP核对。旧v2清单没有该字段时计划/参数保持，原Wintermute v1不变；不迁移或热改已有实例，未打包/部署到旧App。域恢复/Windows来宾实际读取与C04完整验收仍未完成。

## 新实例显式启用

在v2节点中增加`"vmgenid": "managed-generation-v1"`。不接受任意GUID、auto、布尔值或QEMU参数，当前仅x86_64/BIOS/pc候选路径；没有扩展ARM/UEFI或已有Windows运行时支持声明。其他字段/来源/许可/能力门保留，值只是申请能力，不表示来宾已接受。

创建新的GenerationStore时，只有声明节点的实例才生成一次32字节随机材料`vmgenid.key`，排他0600文件，SQLite配置只记录模式与材料摘要。随机材料不进入计划、运行摘要、CLI响应或分享诊断。HMAC-SHA256以私有材料为key，对规范化实例UUID/节点/代次和固定域分离标签计算，取128位并设置RFC4122 v4格式；不使用公开UUID5，也不用每次启动都变的guid=auto。

同一实例/节点/代次普通重开、重启和原尝试恢复保持GUID；正常reset提交的新代次改变GUID，其他节点/新实例各自区分。失败/取消准备不会把旧代次数据或GUID覆盖。旧盘/旧NVRAM/旧材料保留。材料丢失、内容/权限/链接变化拒绝读取，不静默补发或重建；新root创建失败留现场，不覆盖原文件。完整状态根拷贝不构成受支持的实例克隆：正确新实例必须经create获得新随机材料；不自动迁移未知历史实例或做内存快照/live migration；不得回滚整个旧ledger/key/代次目录后直接复用原GUID并称为安全域恢复，该类恢复须作为新实例重新准备并独立检查。

## 启动、接管与控制

QemuDriver从该实例实际材料计算期望绑定，只生成`-device vmgenid,guid=<固定规范GUID>`，写入原启动意图/账本保护的launch.json。运行器接管重算实例/代次/节点/设备参数，与launch及磁盘身份匹配；旧节点不能注入额外VMGenID。工作器从实际generation/node/runtime/attempt目录重建状态根与计划，不接受launch任意指定状态根，核对登记磁盘所在runtime/8位尝试目录、GUID和唯一设备参数后才写start.intent或创建QEMU；声明节点还必须属于当前活动代次，迟到的旧代次工作器拒绝启动。删声明、改GUID、旧代次回放、漏设备/重复设备均拒绝。

经过原进程身份与TLS/名称绑定的每次QMP连接，在声明节点追加只读query-vm-generation-id，返回必须是原GUID；不支持/不符则关闭该连接，状态保持拒绝/未知，不自动改GUID、重发启动、杀VM或热改设备。正常状态/显示/控制沿原连接门；这个检查只证明QEMU报告设备值，guest_guid_verified和domain_health_verified仍false。未针对缺失能力先虚假标ready，也不以QEMU进程存在通过域恢复。

设备/固件实际支持仍须固定运行时验证。官方[QEMU VMGenID说明](https://www.qemu.org/docs/master/specs/vmgenid.html)规定该设备以128位标识通知配置/快照恢复变化，GUID从启动参数设置，可由QMP查询。本文使用当前官方接口核对设计，没有据此证明候选旧运行时/固件支持。微软[域控制器虚拟化架构](https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/get-started/virtual-dc/virtualized-domain-controller-architecture)说明普通重启比较同一值，恢复/克隆变化会触发AD安全处理；GUID变化并不自动创建新域身份或证明恢复成功。原单DC/全域无健康复制伙伴、SYSVOL/NETLOGON、DNS/时间、安全通道、新认证及课程业务仍需逐项检查，手动或受控探针均可，不强加后台自动化要求。

## 本轮证据与限制

16项VMGenID专项覆盖显式模式/硬件拒绝、私有材料与保密、不变/变化边界、reset旧进度保留、材料失效不重建、参数/worker/接管篡改和QMP不符关闭。原驱动36项中35通过/1条件跳过。另以第130节按摘要锁定的原解析器对6种实例/代次完整计划作相等比较，未声明节点保持原计划字节结构/哈希语义。首次专项误用原排他record去构造篡改夹具导致1项错误，保留日志，改为只篡改本轮临时文件，没有放宽record或生产断言。首轮完整2052项中1项旧存储精简夹具先触发argv缺字段异常，保留full-regression-initial.log，恢复原存储校验顺序并容纳未声明旧记录，原22项存储检查通过，未修改其断言；另补迟到旧代次工作器拒绝检查。随后2053项完整回归通过；再用临时状态发现检查器接受复制到未登记同代次目录的声明，保留location-initial-evidence.json与该次通过日志，补严格位置/尝试名绑定后按最终源码验证。

最终完整/独立材料结果见状态第132节和`output/vmgenid-20261029/final-evidence.json`。全部使用临时目录、字节基盘、Fake驱动与QMP替身，无QEMU/Windows来宾/AD/SSH/网络操作，未执行真实停止/重置或到期调度。没有实际QEMU设备/ACPI/Windows VMGenerationCounter/无伙伴恢复证明；源代码设备参数不等于C04完成。原生安装管理、其他未闭项/43项/G0/G1/graceful_stop_verified仍开放。
