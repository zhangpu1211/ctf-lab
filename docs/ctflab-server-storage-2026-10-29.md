# 服务端公共存储池与后台绑定（2026-10-29）

本轮为R02/P03补充所有已声明服务端持久目录的公共容量边界源码：公共上传缓存、审计数据库/回收账本、租约账本及全部实例树可以显式放入同一预配置专用卷。复用既有Linux专用文件系统、Mac APFS quota与Windows专用NTFS实际簇容量的只读核验；不创建卷、设置配额、挂载或更改ACL。本轮仅临时目录/SQLite和原生provider替身验证，没有读写真实配额卷。

## 配置与容量范围

远程策略可选`storage_pool`，包含schema=1、server_uuid、kind（linux/mac/windows）、volume和sha256。volume是既有平台inspect/enroll得到的完整绑定，根必须是该专用卷下的固定受管根；Linux/Windows原绑定的instance_uuid在此按服务端server_uuid解释，作为池的稳定身份，不等于任一课程节点。配置不沿用任意宿主路径推测容量，不把剩余可用空间当作硬上限。

所有当前策略声明的instances[*].root、uploads.cache_root、audit.root、leases.root均须严格位于池根之下，不能等于池根或指向卷外；实例内部的代次、磁盘、显示/worker日志、证据、监督、契约及guest记录沿既有受管树布局进入同一卷。审计归档/换库的额外目的地也须在池内且继续满足原互不嵌套约束。新课程预分配目录可尚未创建，但已有祖先须为私有目录、同一设备，拒绝文件、符号链接、Windows重解析路径及路径规范化逃逸。

成员路径核对前后重新核验原平台卷绑定/容量，绑定、挂载或quota变化即拒绝，不迁移、修复或改为无约束。公共池是这些声明持久根共享的卷容量上限，**不是每个实例独立硬磁盘配额**；每人/每实例预约仍由原租约逻辑负责。现有实例级专用卷约束不会因此放宽，不能把Windows独占卷描述原样误用成多个实例各自独占同一卷。

只读运行时/程序、管理员信任根与原策略文件、用户自行选择的导出、外部虚拟机与不受本服务管理的路径不在该声明范围；第三方运行时在系统临时区/崩溃报告的写入也不作全局保证。结果明确`all_host_writes_covered=false`、`per_instance_hard_disk_quota=false`。这不是限制当前管理员任意改卷、其他进程写入或整个项目所有外部存储的机制。

## 请求、管理与独立后台

`ctflab_server_storage.py`提供preview/inspect及bind-preview/bind。preview读取既有volume-policy和服务端策略，只打印候选storage_pool、当前proof与原策略摘要，不写策略。inspect要求已有配置，默认要求已有运行时实例登记完成。preview允许尚未登记的已有实例，返回unregistered_instances及background_bindings_verified=false，不能用预览证明独立后台已受约束。

已有runtime-profile的实例不会自动接管。只有active_generation=0、没有代次/未决操作、桌面契约空闲时，bind-preview给出绑定摘要；bind同时要求同一摘要与`--execute`，在原契约/实例双门下登记。可逐个登记多个已有实例；程序不重写原runtime-profile或基盘。策略的采用由管理员另外操作，本工具不原位改写策略文件，也没有自动迁移已有运行实例。

登记先把完整上下文提交到实例SQLite metadata的server-storage项，再排他写server-storage.json旁车，绑定池/服务端/实例、根和账本inode、原profile摘要。旁车丢失或部分写入后，账本仍记住约束，后台拒绝而非退回旧模式；完整账本标记与缺失旁车只允许原摘要、原空闲实例的明确继续，畸形旁车保留。上下文与profile漂移拒绝；没有自动覆盖或在线重绑定活动实例。

每个远程消息在新审计intent与派发前重验。课程计划/配置、租约绑定和worker许可复核、审计查看/结清、审计导出/换库/恢复及调度读取入口使用同一守卫；新增检查不启动真实到期调度。新课程在原实例门中登记上下文，仍不prepare/start。独立桌面backend/worker启动、QEMU驱动节点路径及代次准备均读取账本登记；QEMU launch.json携带上下文摘要，QEMU worker在start.intent和Popen前再次复核，管理会话退出不解除约束。普通未配置池且未登记的历史实例沿原行为，不隐式迁移。

已经运行的进程不会因卷漂移被自动停止；观察可能拒绝或降级，原状态保留。源文件/账本与同用户恶意修改的全面防御、运行期间的物理容量写满/元数据耗尽及宿主故障需要原生验收，不能把应用守卫当成永久原子文件系统快照。

## 实际验证

22项新增测试使用自有临时字节、真实SQLite/文件、Mac卷provider替身和自有隔离Python命令。覆盖全部声明根/未来目录、越界/同根/链接/文件/设备漂移、池摘要/服务端身份/容量漂移、每消息先于审计与派发、显式空闲登记/原件保全、多实例分批登记、旁车/账本丢失、提交标记后丢旁车的恢复、profile漂移、布尔schema拒绝、独立后台与QEMU worker在Popen前拒绝，以及真实课程配置链登记。正向CLI子进程显式注入卷provider替身，仅修改本轮临时状态；不能当作真实APFS/NTFS/Linux卷或压力证据。

首次17项有2处夹具错误：漏接上传辅助方法、误写活动代次键，修正后17项通过；追加后台/多实例/CLI等反例后22项通过。早期失败日志保留，不以改计数消除失败。受影响旧路径及完整/独立最终结果见状态第120节与`output/storage-pool-20261029/final-evidence.json`。

本轮没有真实VM/SSH/Docker、停机/重启、资产删除、宿主网络/卷/ACL变更、到期调度、Windows Smoke、桌面控制、提交推送、打包或发布。Mac0.1.3已发布App与原更新器保留，本轮只是源码；Windows候选。全部真实平台容量/写满/inode/重启、多用户及失败恢复、Mac CPU/内存强限额、外部存储、真实课程/网络/分析镜像和最终安装签名闭包仍需开发或验收，43项/G0/G1/graceful_stop_verified和总目标未完成。
