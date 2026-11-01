# 受管远程资源租约开发增量（2026-10-25）

本轮承接状态第87节，实现R02/R03的租约账本、远程准入与一次正常停止的显式到期处理。仅工作区源码；未连接真实SSH/KVM、未安装调度器、未操作用户VM。完整43项及实机总验收仍未完成。[验证记录](verification-remote-leases-2026-10-25.md)保留实际范围。

## 策略与入口

`ctflab_remote.py` 的旧策略不变；可选 `leases` 必须包含以下字段，未配置时沿用原行为，不宣称全主机强制配额。

- `root`：独立绝对路径，不能与实例根或上传缓存重叠；普通Linux服务用户独占，目录700、账本/许可600。
- `capacity`：全池 `cpus`、`memory_mb`、`disk_reservation_bytes` 正整数上限；`limits` 以已有principal为键指定同形个人上限。
- `instances`：以已登记实例UUID为键，每项指定 `disk_reservation_bytes` 和 `expiry_action`（`notify` 或 `request-stop`）。每个实例owner必须有个人限额；scope仍受原策略约束。
- `max_ttl_seconds`：10至86400。申请/续租TTL不得超过该值或主体权限到期时刻。

管理员准备私有策略后，可显式执行 `python3 -I tools/ctflab_remote_leases.py initialize --policy /绝对路径/policy.json`，只新建账本，不接管或启动实例；已有文件拒绝覆盖。实际服务与worker/expiry仅面向Linux普通用户。Runner新增四个协议动作：

| 动作 | parameters |
|---|---|
| lease-acquire | instance_uuid、全新lease_id（UUID）、ttl_seconds、明确确认expiry_action |
| lease-renew | instance_uuid、lease_id、全新renewal_id（UUID）、ttl_seconds |
| lease-release | instance_uuid、lease_id |
| lease-status | instance_uuid |

启用租约后，资源修改的 `submit` 外层还需 `lease_id`。这里只接受既有本地契约操作，不提供任意命令。status/cancel不等待长任务持有的租约门；stop和只观测的recover允许在租约失效后处理现场，主体权限过期仍禁止recover。教师在原scope内操作学生实例使用学生owner额度；不能借教师额度启动学生实例，也不能替owner申请或续租。

## 资源与身份绑定

`ctflab_lease_store.py` 使用SQLite持久化账本和独立跨进程排他门，额度判断、申请与续租串行。CPU/内存按照完整场景声明预留，不按当前已启动节点折算；实例没有证实全部停止前保持预留。磁盘是永久保留引用的逻辑预算，覆盖各节点源盘声明、NVRAM及32MiB余量；释放租约不释放磁盘额度或删除文件。它不是磁盘实际占用预测、cgroup或文件系统硬配额；可写overlay仍可能增长，未纳管的本地入口也不受本池准入约束。

申请新租约必须在实例工作门、契约门、代次门内证明无活动/未决操作、所有代次prepared、生产后端现场观测各节点停止；运行中的旧实例不会被收编。绑定服务器UUID、实例UUID、实例根/账本文件身份、配置/profile摘要、资源与到期策略。profile或绑定漂移即拒绝沿用；释放后旧lease_id仍只返回历史结果，不能复活。续租幂等键与新期限在同一事务持久化，故障回滚两者。

时间使用同一次启动的单调时钟与Linux boot_id，同时保留UTC交接时间；boot变化、单调值倒退或相对UTC偏差超过300秒进入clock-uncertain，停止新资源动作、保留额度，绝不以不确定时钟自动关机。Python单调时钟定义见[官方文档](https://docs.python.org/3.10/library/time.html#time.monotonic)，Linux标识见[内核文档](https://www.kernel.org/doc/html/latest/admin-guide/sysctl/kernel.html)。不实现跨宿主或重启后的自动时限恢复。

## 异步执行与到期

提交时先按原契约落地，再写操作专属私有许可并派发独立有界日志worker。许可绑定请求摘要、策略摘要、服务器/主体/实例/资源及原operation_id。worker重新读取权限与现场绑定，在资源门内调用既有LocalService/生产后端，并在协调器取消检查点再次检查权限/时限；排队延迟、策略撤销、profile变化或途中到期不能继续启动剩余节点。已启动节点保留，标记需恢复，不自动补发或回滚。只有在合法生产执行时登记当前worker身份。日志使用现有每日志8MiB接收器，无新监听。

到期处理必须由管理员显式执行 `python3 -I tools/ctflab_remote_leases.py expiry --policy /绝对路径/policy.json --lease-id UUID`。本轮没有安装或运行周期调度，不给现有实例新增到期行为。

- notify只记录需关注并保留额度。
- request-stop只适用于策略允许且owner申请时再次确认的租约；先查现场，已全停可释放CPU/内存，否则持久记录意图后提交一次原正常stop，沿用CAS、幂等和生产身份检查。
- 提交后不重复关机；结果未知、派发失败、超时、权限变化均保留记录和额度。再次显式处理只查询原操作，直到所有代次确实停止才释放CPU/内存，不删除磁盘、信号强杀、重试关机或重放启动。
- 正常停止命令完成不能证明来宾优雅关机，返回 `graceful_stop_verified=false`。调度器尚缺，不能宣称自动到期回收已投用。

## 仍需开发与验收

真实普通Linux/SSH/KVM的worker分离、时钟/重启、长操作权限撤销和一次停止故障矩阵尚未验；多人审计、调度器部署/健康检查、硬资源约束、桌面租约入口、远程显示与窄数据通道仍缺。单个池串行持有资源门至后端动作结束，取消可达，但长操作会暂时阻塞其他实例的申请/续租/修改；不是高并发多租户调度器。撤销scope后的未知任务保留在原契约，需要管理恢复，不自动重派。其他OCI/容器跨网/来宾半配置、安装器/启动器、课程及外部VM差距沿用台账。Windows Smoke不重做，G0/G1未通过。最后集中实机验收尚未开始。
