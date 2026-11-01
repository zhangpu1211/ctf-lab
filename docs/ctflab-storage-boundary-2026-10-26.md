# Linux专用文件系统容量绑定（2026-10-26）

承接状态第97节和整批说明第4节的多文件增长缺口。新增`tools/ctflab_storage_boundary.py`，将部署方预先提供的独立ext4/XFS文件系统绑定到一个实例，核验整个文件系统的数据容量。**不创建、挂载、格式化、扩容、删除磁盘，不设置项目配额，不改变现有VM或Mac更新器。**

本轮只在Mac执行内存内核观察替身与临时文件集成测试，尚未在Linux真实块设备上执行。原生支持、磁盘写满/ inode耗尽、重启后的重新登记与课堂效果未验；不关闭R02、L01、43项、G0/G1或正常关机门槛。

## 行为

- 只开放普通用户Linux路径。部署方先准备新的独立挂载点，实例根固定为其直接子目录`instance`；两级目录须当前用户拥有且私有。该目录可沿现有初始化/课程映射流程创建，不能将挂载点本身当作要求不存在的新实例根。
- 从当前`/proc/self/mountinfo`、保留目录FD和`fstatvfs`读取挂载ID/父ID、设备号、文件系统类型与来源、选项、文件系统ID、容量，以及挂载命名空间和根目录inode身份。仅完整ext4/XFS设备根、可写且nodev/nosuid、实际本地块设备；拒绝bind根、同设备别名、嵌套/叠加挂载、tmpfs/overlay/远程文件系统。前后观察不一致拒绝。
- 容量按`f_blocks * f_frsize`核对，须不高于明确的`max_bytes`；可用空间用普通用户可用的`f_bavail`，不用含保留块的free冒充。已登记容量改变、卸载重挂、根目录替换、命名空间改变均拒绝；不自动重绑或把旧描述迁移为新事实。
- 私有运行时profile新增可选`storage_boundary`完整描述。仅明确声明的实例启用，历史profile不自动迁移。该描述不是签名授权凭据，必须由可信管理员固定在私有profile中；学生RPC不能提供它。
- 代次准备/重置在复制前、每个文件前与选择新代次前核验；普通用户可用空间不足提前拒绝。复制中移除/替换约束、容量或身份漂移拒绝提交新代次；保留原件、旧代次、部分新文件与未决意图，不清理或重试。
- QEMU启动先核验，再创建本次启动材料；launch.json绑定完整描述。worker在日志接收器与QEMU派生前再次核验，storage.json保留观察范围；活进程观察同时核验其挂载命名空间。失败不降为无限额启动、不杀已存在进程。原有磁盘外部backing/data-file拒绝仍保留。
- 远程租约按至少整个声明上限预留容量，并固定描述摘要；同一卷内的其他实例根或祖先实例根拒绝。描述/容量漂移使原租约绑定失配，不释放额度、不运行到期调度。

## 范围与限制

此约束限制同一实例文件系统中多文件共同增长，涵盖在该根内的代次盘、快照、运行记录和证据；它与第97节的RLIMIT_FSIZE单文件限制可同时使用。**不是XFS/ext4项目配额实现，也不是按物理宿主占用计费的全局限额。** 文件系统元数据/日志、底层thin/稀疏宿主容器和物理设备故障需部署层单独计量；公共缓存、Runner公共审计/作业日志在卷外，不包含在此证明中。原有`disk_reservation_hard_enforced=false`不被整体改为true。

不承诺抵御拥有宿主root权限者扩容/重挂或修改进程；检测到变化只拒绝新操作/新观察，不以资源限额为由自动终止用户VM。停止仍沿原固定正常停止路径与用户当次授权，不能因本模块开发完成自动停止实例。

Windows没有开放本实现，Mac继续原路径。现阶段不提供自动磁盘配置或配额设置服务，避免把管理员预配置误写成已经部署。

## 入口与恢复

只读候选描述入口：

```text
python3 -I -B tools/ctflab_storage_boundary.py inspect --run <专用卷/instance> --mountpoint <专用卷> --instance <实例UUID> --max-bytes <明确上限>
```

必须先有部署方准备的真实Linux专用卷和私有实例目录。本轮仅运行`--help`及不支持平台拒绝/替身；没有对任何用户路径执行inspect。输出只到标准输出，不写profile、不应用挂载、不自动启用限制。管理员确认实际布局后才能在停止且未持有旧租约的实例上显式配置；不要更改正在运行实例的profile来追加此约束。

未知、磁盘满或身份漂移后保留全部材料；先只读核验实际卷/挂载/进程和旧描述，不能自动删除旧代次腾空间或强制换描述。跨宿主/卸载重挂后的新描述需要独立核验并遵守原实例/租约恢复门，不复用历史mount ID或PID作为授权。

## 验证

证据根`output/storage-boundary-20261026`。专项覆盖描述摘要/上限、容量增长/重挂/根身份/命名空间拒绝、mountinfo转义/坏数据、实际生产probe的内存内核FD替身、bind/嵌套/共享设备拒绝、代次中断/移除约束/空间不足保留现场、租约整卷预算和共享根拒绝、QEMU启动前拒绝及worker核验顺序。测试不接真实VM、块设备、SSH或cgroup。

首次专项有3处夹具错误：Path.stat双重mock与重复独占创建profile；修正夹具后通过，没有放宽生产保护。最终专项、完整回归、白名单独立副本及源码保全结果以本说明末尾和final-evidence.json为准。

实现依据：[Linux mountinfo字段与设备语义](https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html)、[statvfs容量与普通用户可用空间](https://man7.org/linux/man-pages/man3/statvfs.3.html)、[内核proc文档](https://www.kernel.org/doc/html/latest/filesystems/proc.html)。这些接口文档不是本轮原生运行证据。

接续：继续`/Users/pufei/Downloads/ctf-lab`，读AGENTS.md、状态第98节、本说明和43项台账末尾，现场核验并保留改动；按整批说明第4节继续未关闭开发，最后集中实机验收。沿用禁止重做Windows Smoke、停止现有VM、实际到期调度、删除资产、提交/推送、覆盖旧包和发布的限制；保留原Mac更新器，镜像/SSH/证书暂缺已知。

资源收口：最终执行会话结束；只读本机快照未发现QEMU、本轮调度/显示/HTTP夹具或fixture-worker。未创建HTTP服务器或浏览器夹具，未操作历史PID或用户VM；不推断远端Windows/SSH状态。完整进程核验见output/storage-boundary-20261026/process-final.json。

第98节最终核验：完整1519项，1498通过/21条件跳过（230.331秒）；独立源码629项，621通过/8跳过（18.137秒），181文件/128个Python语法/13个固定CLI帮助通过。新增专项13项通过，文档94项/89通过/5跳过。前端/Rust未改未重跑。最终摘要output/storage-boundary-20261026/final-evidence.json；完整full-final.log与独立isolated-corrected-final.log，早期日志仅阶段历史，不代表当前源码重跑。
