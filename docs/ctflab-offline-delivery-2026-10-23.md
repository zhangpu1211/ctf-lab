# 本地可实施部分交付与继续入口

日期：2026-10-23。正式目录 `/Users/pufei/Downloads/ctf-lab`。

本轮交付的是通用场景存储/协调基础、离线拓扑工具、C05合成课程和Windows回传汇总。不是全部43项完成，也不是Windows安装版。G0/G1仍未通过；Windows后台异常后接管、显示重连、隔离网络执行、生产运行驱动和桌面界面仍有实现工作，不能全部归因于缺少测试设备。

## 1. 可以直接使用的入口

以下统一入口兼容Python 3.10+，只使用标准库，不加载Mac专用运行器。路径含空格时使用双引号。输出文件已存在时拒绝覆盖。

```text
python -B tools/ctflab_offline.py --help
python -B tools/ctflab_offline.py topology scenario.json --instance 00000000-0000-4000-8000-000000000001 --format html --output topology.html
python -B tools/ctflab_offline.py topology scenario.json --instance 00000000-0000-4000-8000-000000000001 --format network-checks --output network-checks.json
python -B tools/ctflab_offline.py topology scenario.json --instance 00000000-0000-4000-8000-000000000001 --format diff --proposed proposed.json --output draft-diff.json
python -B tools/ctflab_offline.py evidence-course build C05-output
python -B tools/ctflab_offline.py evidence-course verify C05-student-unpacked
```

拓扑以场景v2清单为输入，地址明确区分设计值与观测值。没有观测时显示unknown；API接入的观测必须绑定实例、代次与计划摘要，过期或未来观测不提升当前状态。HTML无脚本、无外部资源，节点可展开。它是离线视图，未接桌面实时状态。

草稿比较先对新旧清单完整校验，再列字段差异与下一代次摘要；不修改运行场景。尚未提供图形拖拽、模板资源浏览或完整编辑器。

网络矩阵包含节点有向可达预期、宿主/控制面/物理LAN/外网的IPv4与IPv6禁通项。双网卡不自动视为路由。矩阵全部为not-run；没有设置网卡/防火墙、没有扫描地址，也不证明隔离。服务协议、授权测试目标与实际隔离后端仍需补齐。

## 2. 通用生命周期与存储基础

`ctflab_generation_store.py`保存基盘/固件摘要和每次代次尝试，以完整独立文件复制准备磁盘。复制前后核验源与副本；新代次完成后，活动指针和操作结果在同一SQLite事务提交。旧代次、取消副本与失败现场全部保留。空间预检计入新副本及512MiB余量；已有文件已占用空间由文件系统剩余空间反映。

`ctflab_scenario_coordinator.py`通过现有LocalService契约调用，使用可信宿主注入的driver；内容不能选择程序或参数。按DAG启动、逆序正常停止；每个副作用前记录意图。所有节点的实例、代次、身份与状态必须核验。部分启动失败可以显式正常停止已核验归属的节点；未知身份、正常关机超时、未完成关机意图不能自动重放。无driver时不提供启动能力。

重置必须全体停止，磁盘和UEFI变量成对准备；提交前取消保留旧代次，提交后不再报告取消。恢复只读观察实际节点后记录核验结果，不启动、不重放、不删除。部分运行且无法一致核验时保留recovery-required。

已连接本地契约的合成驱动测试，但没有接入实际QEMU/Windows网络与显示后端。完整复制不等于QEMU格式转换；生产驱动启用前须核验源盘格式、自包含性/外部backing引用和固件兼容。当前无删除或垃圾回收入口，不能称完整P03完成。私有存储的Windows原生行为、宿主突然断电及目录元数据持久性尚未实测。

初次prepare在活动代次提交前失败时保留全部材料，尚无自动修复/选择半成品入口；不手工改数据库把它标为完成。需核验失败后使用新的独立根重新准备。后续reset提交前失败则可核验旧活动代次并再次准备，新尝试不覆盖失败副本。

## 3. C05合成应急课程

以下原段落记录2026-10-23的v1文本包。2026-10-30工作区源码已补v2日志/PCAP/FAT12材料、学生独立只读工作区/查看器、教师完整复盘与实际报告；新build入口生成v2，不覆盖旧包，完整流程与限制见[当前增量说明](ctflab-evidence-workflow-2026-10-30.md)。学生清单指纹单独核对；正式交付与公开发布仍未执行，不能把源码增量当旧资产已更新。

生成物为`C05-student.zip`、`C05-teacher.zip`和`SHA256SUMS.json`。学生包仅包含Web/认证/变更审计合成文本、来源与UTC说明、调查任务、报告模板、摘要清单和独立`verify.py`校验器；教师答案独立。学生可执行`python -B verify.py`校验，无须收到含答案的课程生成器或完整开发工具包。没有真实账号、访问令牌、恶意程序或实际攻击记录。

先校验ZIP摘要，再解压学生包并运行verify。保留原ZIP；调查在独立副本进行。课程包含可核验的跨日志请求关联、维护开关变更、业务页面与健康接口差异，以及无法单靠日志确认的归因限制。只需要文本编辑器或表格软件。

校验器拒绝摘要/长度变化、缺失或额外文件、越界路径和符号链接；不解析或执行日志内容。清单摘要不等于签名或真实性证明。课程通过包结构及合成时间线测试，真实课堂效果和公开分发尚未验收/发布。

## 4. Windows：补已有材料，不重跑已通过闭环

对原control-r1实例目录执行只读汇总，输出放在该目录之外：

```text
python -B tools/ctflab_offline.py windows-evidence --run "C:\CTFLab-Test\Smoke-OVA\w01-control-01" --kit "C:\实际目录\CTFLab-Windows-control-r1.zip" --output "windows-evidence-summary.json"
```

只有确实关闭并重新打开过控制终端时，才补`--terminal-reopened yes`；不确定则省略，不为补记录重做已通过的关机闭环。工具只读config、host、result、exit、failure及两份日志的白名单文件；日志只输出SHA-256与大小，私人路径和自由文本错误不进入分享报告。默认不上传。

报告列缺失/无效材料、设备版本白名单字段、原结果字段和control-r1包摘要是否匹配。它不能独立证明设备真实性或日志无警告，不能替代必要时查看原始stderr。外层G0/G1始终false。工具不启动/停止/接管任何进程，不改原实例。

## 5. 后续实施与外部依赖

1. W01/W02：为可恢复的受保护QMP与显示通道选择并实现后端；现有匿名管道与SDL不具备异常后重新连接能力。需固定Windows构建探针与ACL负测后决定，不降级到无认证TCP。
2. S03/P03：接实际平台driver，补源盘自包含性检查、完整资源引用、首次准备失败恢复和生产故障矩阵；现有存储与协调模块可复用。
3. W03—W05/C01：网络和控制前置满足后，集成双节点课程、随包运行时、桌面界面、安装/升级/回退；当前不是只差打包。
4. W06/U01：最终包至少两台物理机及至少5名非开发者独立完成课程；签名、设备与参与者是外部输入，代码不能代替。
5. Docker、Linux执行器、远程、外部VM接入、AD与现场应急仍按43项任务表前置推进。本轮没有运行这些环境。

社区贡献和反馈准备见[社区协作说明](ctflab-community-workflow-2026-10-23.md)。独立验证结果见[本轮验证记录](verification-offline-foundation-2026-10-23.md)。
