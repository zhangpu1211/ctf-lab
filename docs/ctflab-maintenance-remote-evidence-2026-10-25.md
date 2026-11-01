# 后台维护、更新协调、远程受限入口与证据封存（2026-10-25）

承接状态第84节，保留全部43项原完成判据。以下是工作区开发增量；没有重做Windows Smoke，没有部署SSH、接管用户VM或更新已发布App。集中实机总验收尚未启动，代码测试统一记录于[本轮验证](verification-maintenance-remote-evidence-2026-10-25.md)。

## 后台日志与证书

通用QEMU监督器、独立退出观测器和桌面execute/display后台改为独立管道接收进程；每日志保留前8MiB，超额继续排空，记录received/stored/discarded字节。每次启动新目录，保留旧日志。达到配额不截断旧现场，不向QEMU发送信号。接收器先写状态再允许生产进程启动；进程中断时complete=false，日志EOF不等于QEMU已退出。磁盘写入失败后继续排空，状态文件也写不出时保留旧/partial状态，不能宣称最终计数完整。每次尝试有上限，全部历史尝试的总容量仍会增长；本轮不自动清理。

TLS增加CA/服务端/客户端有效期与材料摘要检查、7天内续期提醒、过期/时钟提前拒绝提示。桌面显示即将到期或无效；CLI的 `certificate-status --run <实例目录> --node <节点>` 只读。生成仍为每次启动独立CA、30天有效；**在到期前正常停止并确认退出，再启动生成新材料**，保留旧材料。没有在线热换证书/私钥或自动停机；已经过期且失去控制的实例仍需另行授权恢复，不能假装能正常关机。固定旧Smoke入口不改行为。

## 安装版本更新协调

`ctflab_delivery.py`新增 `update-initialize/register/preview/apply/recovery/abandon`。新版本库自带协调表；旧版本库必须显式initialize，先用SQLite backup保留旧安装库，再事务增加表，不搬移实验磁盘、不运行任意迁移脚本。schema=1以外的实验迁移继续拒绝。

先用register登记宿主明确指定的既有通用实例；客户端不能在更新请求中附任意实验路径。preview在锁内核验登记实例的所有保留代次/节点确已停止，拒绝未决意图或身份不明；检查桌面工作门、活动契约与代次门。预览绑定目标载荷、旧版本、代次、config/profile摘要。apply重验预览，再保持工作/代次锁，备份ledger、desktop-contract和profile；备份清单不含磁盘/私钥。最后重验载荷并在版本库事务中切换指针。登记后旧activate/rollback捷径拒绝，回退也对旧目标执行preview/apply。

更新前先落目录意图；异常或进程中断保留备份、旧版本和失败目录。recovery只读识别已提交/未提交；未结清失败目录阻止后续切换。abandon是操作者显式“保留当前旧版本”决策，仅当当前指针仍等于意图previous时记录结清，保留文件；不会重放旧操作或恢复旧账本覆盖新进度。同operation_id不重复切换。

入口示例只描述未来操作者选择，不在本轮对用户安装执行：

```text
python3 -B tools/ctflab_delivery.py update-register --root <安装版本库> --workspace <既有通用实例>
python3 -B tools/ctflab_delivery.py update-preview --root <安装版本库> --version <已暂存版本>
python3 -B tools/ctflab_delivery.py update-apply --root <安装版本库> --version <已暂存版本> --operation-id <新UUID> --plan-sha256 <预览摘要>
python3 -B tools/ctflab_delivery.py update-recovery --root <安装版本库>
```

只核验已登记的通用实例；没有全机实例发现、最终Windows安装器、版本选择启动器集成、在线更新调度或Authenticode。旧版本目录永久保留，运行中旧二进制不会被覆盖。上述原子指针不等于最终安装器已更新。

## 受限SSH Runner与角色

`ctflab_remote.py`提供serve/request两个入口。SSH服务器必须由有权限的部署方配置每把公钥的固定命令，固定策略文件与principal；`SSH_ORIGINAL_COMMAND`须精确等于ctflab-runner-v1，普通Linux用户执行，禁止root。请求不能携带principal或宿主路径；只允许handshake/list/overview/diagnostics/submit/events，复用原LocalService与桌面异步派发。SSH断线不重放生命周期请求；原幂等键和事件游标用于重新查询。

服务策略schema=1包含server_uuid、principals与instances。principal含role(student/teacher/administrator)、实例UUID列表和带时区expires；实例映射只在服务器本地含root/owner。学生即使被误配他人实例scope也不能跨owner访问；教师/管理员仍需显式scope。过期禁止start/reset/其他新副作用，保留status/cancel/正常stop。学生不能执行来宾网络/服务/容器管理。

客户端配置显式锁定server_uuid、SSH可执行文件、目标host/port/user、identity和known_hosts摘要；StrictHostKeyChecking=yes，不读取用户/系统SSH配置、不转发agent/X11/端口、不使用代理或复用主连接、不运行LocalCommand。响应有容量/时间限制，异常只结束自己持有的SSH传输进程，远程任务结果保留unknown。主机密钥变化拒绝；不会自动信任新密钥。

部署必须另外核验authorized_keys的restrict/固定command与禁止PTY/转发设置；本轮没有修改SSH配置或发起SSH连接。[OpenSSH客户端](https://man.openbsd.org/ssh)、[服务端固定命令说明](https://man.openbsd.org/sshd)是参数/部署语义的一手来源。CLI request从stdin接收一条受限JSON，serve亦为单请求，不是对公网新增监听。

**R01/R02/R03/R04仍未完成。** 当前未实现远程资产同步、显示隧道、续租/到期正常停机调度、算力/磁盘配额、多人完整审计或数据通道；expires仅访问授权期限，不冒称资源租约。尚未接入桌面远程目标选择器或真实SSH/KVM验证。

## O01本地证据封存

`ctflab_evidence_export.py`只接收用户明确选择的已封口项目Ethernet PCAP和精确实例/代次/网段绑定。拒绝未关闭捕获、错误绑定、畸形记录、超限、链接/硬链接和复制期间变化；逐记录核验长度/时间字段，不解析或执行载荷。复制到新目录并生成摘要清单，保留丢帧、截断、未知上游损失及不可信宿主时钟标识。即使摘要全匹配，complete_capture_verified仍为false。

Python API还允许显式选择通用QEMU运行尝试，按launch/进程绑定提取固定生命周期事件；时间明确是文件mtime，不能当作精确来宾事件时间。只导出状态/退出码等白名单，不复制argv、宿主磁盘路径、PID、密钥或原始后台日志。PCAP保留原始包字节；只本地封存，不上传或自动公开。通用socket后端捕获、完整事件时间同步与隔离分析器仍缺。

## 交付边界

新增依赖已加入桌面暂存与源码白名单，旧包不覆盖。全部43项仍有实际开发缺口：完整G0负向矩阵、在线证书更换恢复、最终安装/更新启动器、终端窄路由/OCI装载/容器跨网/部分来宾对账、远程资产/显示/租约/配额/数据通道、外部Kali→Windows→AD、真实课程、通用捕获与隔离分析器。缺镜像/SSH环境/签名证书的既有回答不重复索要；不能把这些开发项写成只等用户测试。
