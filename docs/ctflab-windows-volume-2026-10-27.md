# Windows专用卷与未准备实例的容量策略绑定（2026-10-27）

承接状态第110节，本批新增预配置Windows专用NTFS卷的只读容量/身份检查，以及通用实例的可恢复配置绑定入口。只操作明确指定实例的运行时配置，不创建/挂载/格式化卷，不修改配额、ACL、驱动或宿主网络。**本轮没有在Windows上执行卷检查或压力验证，没有修改用户实例；Native API均为替身。**

## 专用NTFS卷描述

`ctflab_windows_storage.py inspect --help`展示只读登记参数：实例根、盘符根、实例UUID和容量上限。限定64位Windows、本地固定盘符根和其下唯一`instance`目录，如`E:\instance`与`E:\`；不接受UNC、设备命名空间、ADS、路径回退或任意嵌套根。卷与实例目录需满足既有Windows私有路径/所有者/ACL要求；程序不会自动修复权限。普通用户查询权限不足时直接拒绝，不申请提权。

检查系统卷GUID并拒绝系统卷；检查候选卷只有一个盘符挂载路径，没有额外盘符或文件夹挂载别名。卷根只允许instance及Windows的System Volume Information、$RECYCLE.BIN名称，不读取后两者的内容，不接受其他用户目录作为专用卷。只支持NTFS可写卷。

以只读目录句柄和OPEN_REPARSE_POINT保留卷根/实例根，检查目录属性、非重解析点、文件身份、最终GUID路径；另外以无尾斜线的GUID打开零访问权限卷设备句柄，向该设备发送FSCTL并前后复核簇几何/序列与容量。参考[GetFinalPathNameByHandleW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew)与[卷挂载路径枚举](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getvolumepathnamesforvolumenamew)。句柄只读，成功或失败均关闭自有句柄。

普通GetDiskFreeSpace类返回的总量可能受当前用户配额影响，不能拿较小值当作整个卷的容量上限；依据[Microsoft GetDiskFreeSpace说明](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getdiskfreespacew)。本实现通过[只读FSCTL_GET_NTFS_VOLUME_DATA](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-fsctl_get_ntfs_volume_data)取得TotalClusters与BytesPerCluster，绑定实际簇容量，参考[NTFS_VOLUME_DATA_BUFFER](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-ntfs_volume_data_buffer)。用户可用空间另外取保守值，不将其作为整卷物理上限。如果系统不允许对所保留句柄执行该查询，拒绝此能力，不降级为配额推断；实际普通用户兼容性仍待Windows验证。

输出带kind=`windows-ntfs-volume`、实例UUID、根/盘符、容量上限、完整卷/目录绑定及SHA。支持上限64 MiB—1 TiB，实际卷簇容量必须不大于声明上限。现有管理员提供的卷必须已满足条件；本工具不会为了通过检查缩小卷、移动数据或设置配额。

范围是实例所在文件系统的数据簇容量，**不是整个项目/操作系统的总磁盘硬配额**。外部缓存、审计、临时目录、VHDX容器/底层thin空间与其他卷不包含，NTFS元数据也会占用可用空间。管理者从外部改卷仍可能改变边界，程序只在相关操作/观测时复核并拒绝漂移；不声称锁定外部管理员或完成了写满/重启验收。

## 接入位置

可信profile可选`windows_storage`；与storage_boundary/macos_storage互斥，Mac profile和非Windows实际启动拒绝。代次准备/逐文件复制/选择沿既有check_profile复核；启动记录绑定完整描述，启动前、worker日志/派生前和活动观察复核。描述缺失、变化或错误根不能降为无约束运行，不把旧启动追加新字段说成已受保护。

远程租约的保守记账至少计入整个声明上限，并登记描述SHA；策略里的其他实例不得使用同盘符或祖先/子目录。该记账接入不表示Windows远程执行已可用。本轮不释放额度、不运行到期调度；现有Linux/Windows平台限制继续有效。

## 未准备实例的显式绑定

新`ctflab_storage_bind.py`支持status、preview、apply。它只允许已配置而未准备的通用实例：active_generation=0、无代次、无未决磁盘操作，桌面工作门/契约门/代次门空闲，没有已登记活动请求。不是运行实例迁移或新代次卷切换。

建议流程：

1. 管理者按独立授权预配置专用卷/文件系统。保留卷根，不预建将由配置器创建的instance根，也不为此删除任何已有目录。
2. 使用原配置入口创建尚未准备的实例，先保存没有容量声明的合法运行时profile，不执行prepare/start。
3. 在对应平台显式只读登记原生策略（Windows inspect、Linux专用文件系统或Mac APFS既有入口），将输出保存为新的私有策略文件；不能把示例/推断字段当成原生结果。
4. `ctflab_storage_bind.py preview --run ... --kind windows|linux|mac --policy ...`只读核对策略和新profile，返回计划摘要。apply必须携带该摘要和一个新operation UUID。
5. apply持工作/契约/代次门，再次核验范围、原profile和卷策略；原始配置**逐字节**保存在新的before文件，意图绑定根/ledger身份及前后摘要。候选完整写入/fsync后才原子替换profile，卷再次核验，完整收据再原子发布。仍不准备磁盘或启动VM。

绑定标记未闭合时，新的prepare/reset在创建磁盘操作意图前拒绝，租约准入也拒绝，避免把没有副作用的失败请求变成妨碍绑定恢复的未决磁盘意图。删除策略字段或整个runtime-profile文件不能绕回“无声明的历史实例”。历史未绑定实例保持原行为。

## 中断与恢复

status只读本地元数据，不核验卷、不连接QMP或SSH；明确区分无记录、原配置/意图未闭合、已发布待收据、完成记录或需要复核。完成记录核验不等于当前原生卷验证。

存在完整意图时，用户明确重复原operation/原计划/原策略才能恢复。当前profile必须仍等于原始或批准后的完整摘要；根/ledger身份和卷策略都须重新核对。原配置仍在时可为缺失/部分备份写新的完整副本，旧partial保留；已发布新profile但缺收据时只补收据，不再次替换profile。候选和收据使用完整临时文件后发布，部分文件不覆盖、不截断，每类最多16份保留文件。用户改写配置、错标识/错策略、损坏意图/已完成收据或丢失原始备份不能由此自动修复，保留现场要求复核，不猜测曾发生的操作。

成功收据继续约束容量声明不能被悄悄移除/替换；不将它当作以后操作PID或停止VM的授权。绑定后若实例已经准备，本入口拒绝重绑定或迁移卷。原Mac宿主状态根的旧容量登记和更新器不变，此入口面向通用v2未准备实例。

## 本轮证据与未验证

专项覆盖：模拟Win32句柄/API、真实簇容量与更小用户配额的区分、系统卷/别名/重解析点/身份漂移/异常关闭、旧启动绑定拒绝、worker在日志/进程前拒绝；真实临时文件/SQLite的原字节保留、元数据门禁、发布后收据恢复、部分备份保全、删除profile拒绝、契约已排队请求拒绝、原始合成磁盘未变。最初一处准备夹具遗漏store.begin，及一处将DOS路径放进Mac服务器策略的夹具错误，已修正；后者改为在纯Windows路径模型测试共享盘符，未放宽生产校验。

没有真实Windows卷、NTFS普通用户查询、卷写满/重启/挂载别名现场验收，也没有真实VM/SSH/正常关机。完整/独立源码结果、最终保全及只读进程快照以状态第111节和`output/windows-volume-20261027/final-evidence.json`为准。43项/G0/G1、Mac本地CPU/内存限制、卷外总量、Windows三层端点/真实课程/最终安装器与其他未关闭开发仍保留，不把本批条件能力写成全部平台硬限额完成。

最终源码复核发现目录句柄不应作为卷控制码入口，已改为独立卷设备句柄，并令替身在非设备句柄收到FSCTL时立即失败；不以替身通过推断普通用户原生访问成功。修正前完整日志另存，不计入最终源码完整重跑。


最终证据：完整回归1729项（1708通过/21条件跳过，247.139秒）；独立源码240文件、166个Python语法、19个CLI帮助，844项（836通过/8跳过，21.206秒）。最终运行源码与独立副本一致；393份基线全在、原Mac更新器与HEAD一致，未发现本轮残留相关进程。详见状态第111节和`output/windows-volume-20261027/final-evidence.json`；没有新交付包、提交推送或发布。
