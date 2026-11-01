# 外部接入缺陷修复验证记录（2026-10-31，独立核验逐项关闭）

> 历史验收快照：本文记录 2026-10-31 第二轮（缺陷修复轮）源码与本地合成验证；历史结果不替代当前软件状态，后续实机验收与发布以新的带日期记录为准。分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`（工作区改动，未提交）。独立核验报告 `verification-independent-review-2026-10-31.md` 原文保留；本文按其编号逐项关闭。

## 逐项关闭状态（对照核验报告 P1/P2 编号）

| # | 核验结论 | 修复位置 | 复现→修复后验证 |
| --- | --- | --- | --- |
| 1 | `create_tap_in_ns` recvmsg 第二参数为列表（TypeError） | `ctflab_kali_attach.py` 生成脚本拆出 `send_descriptor`/`receive_descriptor`（recvmsg 第二参数为整数缓冲区、校验恰好一个SCM_RIGHTS、os.dup 接管所有权）；父分支 waitpid 回收、失败清理、child `os._exit(code)` | `test_ctflab_kali_attach_functions`：真实 socketpair 描述符往返、真实 fork 失败分支（macOS 无 setns）返回 None 不挂起、截断 rights 拒绝；修复前 `create_tap_in_ns` 调用复现 TypeError，修复后通过 |
| 2 | 生产 `policy_summary(attachment, [])` 空白名单 | `ctflab_external_attach.derive_allowed_macs(plan, network_id)`（要求计划已派生MAC、拒绝空集）；`external_relay_worker` 经 `instance_plan` 派生 | 验收测试改为生产装配同源（`plan()` 夹具→derive→policy）；FrameGate 复现脚本修复前 ingress=False、修复后 True；worker 无名单即 `invalid-request` |
| 3 | ForceCommand `%i`、无会话握手、nologin 账户 | SSHD 片段固定 `attach`（无参数、无 `%i`）；会话经数据面 HELLO/VERIFY 控制记录握手（会话UUID+32hex一次性挑战）；安装说明改用 `/bin/sh` 并说明 nologin 不兼容原因 | `test_ctflab_kali_attach` 断言片段无 `%i`/`--session`；`GuestChannelStub` 动态应答握手的两个 RelayTests 与两个 E2E 验收经完整握手后转发 |
| 4 | 无实际来宾身份核验 | 握手应答携带 `assistant_sha256`+`machine_uuid`（daemon 读 `/sys/class/dmi/id/product_uuid`，不可读上报 null）；`verify_guest_handshake` 强制摘要匹配，机器UUID不匹配拒绝，null → 显式 `degraded-verified`（绑定=助手摘要+SSH主机密钥），worker 记录 `identity_state/binding` | `test_handshake_rejects_wrong_assistant_digest`、`test_handshake_rejects_machine_uuid_mismatch`、`test_handshake_degraded_identity_is_explicit` |
| 5 | 提前 connected；终止未证实仍落 disconnected | `run_relay(on_ready=...)` 仅在 SSH+认证+握手全部通过后回调；worker `update('connected')` 移入 on_ready；disconnect fail-closed：pid 异常/kill OSError/超时未证实 → `relay-unknown`+`disconnect_failure`（unknown 可重试收口）；会话更新以最新落盘为基底合并（不再覆盖派发方 PID）；stop 增加 `generation_changed()` 代次停泵 | `test_unconfirmed_termination_stays_unknown_not_disconnected`（kill 失败与存活两种路径）、`test_connect_requires_ssh_config_server_binding`、`test_dead_worker_without_report_marks_unknown_and_allows_clear`（复现报告原结论后修复） |
| 6 | shell 单向、daemon 阻塞 | daemon `shell` 按连接 fork：子进程 dup2 连接fd 为 stdio 并 `execvp(ip netns exec … setpriv … /bin/sh -i)`（降权、清组）；父进程立即返回继续控制循环，SIGCHLD 回收；client `shell_client` select 双向代理 stdin/stdout | 生成脚本真函数断言（dup2/execvp/read1/双向）；交互性属实机验收（无真实 Kali），不声明图形工具支持 |
| 7 | Mac 卡片只有状态文字 | `MacExternalAttachCard` 重写：登记表单（九字段+前置校验）、网段选择、SSH配置路径连接、断开、材料生成、实验地址展示、终端入口命令、恢复说明，全部经 `sceneGenericCall` 走同一桥接契约；表单状态入 `GuiModel.sceneAttachForm`（无宏依赖） | `swiftc -typecheck` 通过；397 项核心检查 0 失败；动作派发与桥接同契约（external-attach-* 六动作），实际点击属人工桌面验收并如实标注 |
| 8 | startsWith('/') 拒绝 Windows 路径 | React `isAbsoluteHostPath`（POSIX/盘符/UNC）用于私钥、SSH配置、材料目录三处；后端 `validate_ssh_reference` 同规则（跨平台正则），歧义相对路径（如 `C:relative`）拒绝 | React 模型测试新增 Windows/UNC 用例（12项通过、构建通过）；后端回归：`C:\Users\...` 接受、`C:relative` 拒绝（复现报告原拒绝后修复） |
| 9 | SIGTERM globals setattr、重复序号、无租约回收、TAP生命周期 | SIGTERM/INT → `threading.Event`；`read_record_checked` 期望序号严格递增（重复/回退/跳号断开不重放）；daemon 30s 租约清扫（到期即关TAP生命周期FD+删ns+删state）+ 退出时全量回收；`status` 如实报告 `tap_fd_alive` 并注明"客户端副本关闭不等于撤网"；宿主空闲心跳（10s）+ 有界载荷 | `test_ctflab_kali_attach_functions`：序号三连拒、租约清扫关闭FD、未到期不回收、SIGTERM 无 globals setattr；宿主侧心跳经 run_relay 代码路径（真实来宾行为属实机验收） |

## 本轮验证（2026-10-31，本机 macOS/arm64，合成/回环）

- `test_ctflab_external_attach` 23 项（新增握手3+身份2+更新2）、`test_ctflab_desktop_external_attach` 13 项（新增 fail-closed 2）、`test_ctflab_kali_attach` 7 项、**`test_ctflab_kali_attach_functions` 10 项（生成脚本真函数）**、`test_ctflab_external_l2` 15 项、`test_ctflab_external_attach_acceptance` 2 项（生产装配策略）通过；`test_ctflab_desktop_bridge` 36 项通过。
- 桌面 `npm test` 81 项 + `npm run build` 通过；Swift 类型检查 + 397 项检查通过。
- **完整回归 `python3 -m unittest discover -s tools/tests` 共 2224 项：2223 通过、21 条件跳过、1 失败**——该失败为文档守卫要求核验报告含"历史验收快照"标记（核验方原文无此短语），在保留原文前提下补标注后单独复跑该守卫 7 项通过；修复轮代码在回归期间未变更。
- 语法：270 个 Python 文件 ast.parse 无错误；`git diff --check` 干净。

## 未验证（实机门槛，与核验报告一致且不缩小）

真实 Linux/Kali 内核（TAP创建、setns、SCM_RIGHTS 真实移交、shell 交互、租约实际回收、原管理网保全）；Mac＋Fusion＋Kali ARM64、Windows11 x64＋Workstation＋Kali x64 端到端；SSH 真实通道吞吐/队头阻塞/睡眠恢复；React/Windows 桌面实际点击；Mac App 与 Windows 安装包重打（环境缺运行时输入/Windows 工具链，见候选材料说明）。核验报告"以上不是穷尽缺陷清单"仍有效：并发保存/连接竞态与长时运行未深查，不据此声明通过。

## R3：第二轮独立核验后的修复（2026-10-31）

本节覆盖第二轮报告已复现路径，历史结果不替代当前软件状态。第150节“九项全部关闭”不能作为本轮前提；第二轮报告原文与旧候选材料保留。

- 控制链改成单次 `attach` 请求；daemon先核对批准grant，再以换行分界返回元数据并交接FD。客户端逐字节读取JSON边界，取得FD后才发送身份应答，不再在已关闭连接上发送第二个请求。测试用生成脚本真函数、真实Unix socketpair和真实FD执行组合；`/dev/null`仅替代TAP，不宣称Linux内核验收。
- 空心跳使用bytes默认载荷；来宾回声使用连续序号，宿主收到合法记录刷新存活时间。模拟时钟验证50秒无业务会话不会在15秒退出；总会话时限仍独立由SessionQuota执行，不将该测试称为两小时实测。
- SCM_RIGHTS直接返回接收FD，不再dup；多描述符/截断消息拒绝并关闭已收到FD。回归比较关闭返回FD后的开放FD集合，并覆盖多FD拒绝清理。
- shell子进程按记录PID逐个WNOHANG回收；返回0立即保留到下轮，不使用全局SIGCHLD抢占TAP同步waitpid。daemon控制accept有超时，租约扫描在同一控制循环执行，退出可唤醒并进入清理。
- 宿主RecordStream从0严格检查接收序号；来宾身份应答消费0，帧泵从1继续。重复/回退/跳号/非零起点均拒绝；心跳与帧共享单向连续序列。
- 生产准备流程：保存登记的策略与worker均从instance_plan派生真实节点MAC；材料生成时持久化prepared会话并输出setup/shell/teardown命令；连接只消费该prepared一次，不即时换UUID。重新连接需新准备材料与管理员setup。React/Mac均展示命令且未准备或已消费时禁止连接。
- 管理员setup的grant新增实例UUID、整数代次、网段及策略SHA256批准字段；数据面HELLO与grant逐字段核对，并核对实际MAC/地址/MTU。不匹配在FD交接前拒绝。机器UUID不可读时拒绝，不再自动降级为degraded-verified。
- 同时修复Linux SO_PEERCRED取错字段（pid/uid/gid中的uid才是账户）、无session的status误拒绝、已过期shell入口。外部动作与worker状态更新复用GenerationStore锁，worker更新核对同一session；计划/代次变化停泵。

新增直接函数、描述符与生产准备回归位于 `tools/tests/test_ctflab_kali_attach_functions.py`、`test_ctflab_desktop_external_attach.py`、`test_ctflab_external_l2.py`、`test_ctflab_external_attach.py`。不以脚本文本存在代替上述组合测试。

验证汇总待本节末追加。证据目录：`output/external-attach-r3-20261031/`。本轮未部署助手、未操作用户VM、未改真实网络；真实Kali/TAP、SSH背压/长时/睡眠恢复、Windows/macOS组合仍未验。并发/进程观测未知等非穷尽范围不凭本节概括关闭；A03/T02/W05/U04及G0/G1继续按修订矩阵推进。

R3最终验证：末次完整`python3 -m unittest discover -s tools/tests -v`共2239项，2218通过、21条件跳过、0失败（341.590秒）；完整日志`output/external-attach-r3-20261031/final-full.log`，对应源码摘要`final-source.json`。CLI末补前的2237项日志另保留，不混用。最终受影响120项通过；前端81项+构建，Swift类型检查及397项（失败0）通过。完整回归后仅将材料INSTALL说明改成当前严格身份策略，并将React默认SSH账户对齐材料的`ctflab-attach`；材料/助手24项及前端81项+构建随后再通过，不冒称又重跑整仓。生成新`kali-materials-final`目录，旧材料保留。

用户随后授权恢复PD Kali“zhangpu”并部署助手/测试独立TAP。虚拟机已恢复且用户已解锁，但Tools未运行、宿主exec无法建立会话，自动桌面输入未进入来宾；目前尚未部署或创建真实TAP。用户截图确认ARM64、sshd已安装、来宾时间仍为2026-08-24、prltoolsd inactive；这些是环境诊断，不是接入验收。已请用户在Kali内启动现有prltoolsd以恢复命令通道，密码仅由用户在来宾输入。SSH只读尝试因没有已核验主机密钥被严格拒绝，未自动接纳新密钥、未尝试密码，也未增加监听。Windows 11保持挂起。

## R4：PD Kali ARM64 真实内核/SSH切片与突发缺陷修复（2026-10-31）

本节历史结果不替代当前软件状态。用户明确授权使用PD Kali“zhangpu”恢复运行、安装助手与独立TAP/netns验收；管理员动作由用户在Kali内执行，未向聊天提供密码。不是Mac+Fusion/Windows+Workstation最终组合验收，也不是实际靶机VM、原生UI或发行验收。

**环境与信任**：实际Kali aarch64、Linux 6.17.10+kali-arm64，已有ip/setpriv/python3/sshd及/dev/net/tun。PD Tools命令通道不可用，改走用户指定来宾的已有SSH服务；用户在Kali控制台确认主机公钥指纹，随后严格固定known_hosts。两条独立临时公钥限定本Mac来源；数据公钥另有固定助手ForceCommand，不改sshd配置或增加监听。真实DMI为`Parallels International GmbH.` / `Parallels ARM Virtual Machine`，此前精确白名单不接受该实际组合，现补此明确组合与回归；非root读不到product_uuid，root助手能读取并核对，与PD UUID一致，没有自动退化身份或绕过检查。来宾时间仍为8月24日，未擅自改时钟，不把本轮当2小时租约/时钟跳变验收。

**部署/范围**：独立目录`/usr/local/lib/ctflab-acceptance-r3-20261031`、`/var/lib/ctflab-acceptance-r3-20261031`及`/run/ctflab-acceptance-r3-20261031`；由用户执行已上传且摘要核对的安装/更新脚本。助手绑定现有用户、固定测试会话，创建独立TAP/netns；命名空间内仅lo+TAP及本网段直连路由，原管理网保留。靶机侧为Mac回环上的两个帧应答器，MAC集合经生产instance_plan/derive_allowed_macs派生，交换机/认证接入口与run_relay为产品代码。它验证真实来宾内核＋真实SSH＋产品中转/交换机，**两端应答器不是真实靶机VM**，不宣称课程或目标服务已验收。

**直接证据**：真实setns/TAP/SCM_RIGHTS交接、身份握手成功；两个应答端ARP与UDP回显成功；默认max_idle=15时空闲17秒仍存活。实际重放宿主序号使来宾客户端关闭，固定数据SSH公钥拒绝任意`id`命令；根管理网地址/路由与基线一致。首次降权shell执行ping因缺CAP_NET_RAW/ICMP权限失败，失败原文保留；没有扩大权限，改测普通用户UDP，不能据此声明raw扫描工具已可用。

**真实发现与修复**：连续50包UDP首先超时。宿主SSH stdout和来宾stdin的BufferedReader会预读后续记录，而select仅观察底层FD，完整记录被藏在用户态缓冲中。真实管道的两项回归在修复前均失败；宿主Popen改无缓冲，来宾在HELLO之前选用底层raw流，回归通过。仅修宿主时，两端应答器已收到/回送全部突发包，但Kali仍超时，构成来宾端独立证据；更新来宾后50包全部返回。另发现停止等待可能覆盖整段心跳周期，测试线程未及时退出；宿主等待上限改0.5秒，复跑断开/线程收口通过。初始失败、仅宿主修复、双端修复与最后收口日志分别保留，不用最终成功覆盖失败。

**收口证据**：用户执行固定cleanup脚本前确认命名空间无工具进程、无本助手帧客户端；实际TUN生命周期FD从1到0，命名空间/会话grant/控制socket消失、daemon PID退出，服务已停；地址、MTU、MAC、flags及路由均与管理网基线一致。安装、旧代码备份及证据文件保留。随后只撤销本次两条临时公钥，保留原authorized_keys其他字节与备份；两把临时私钥分别实测认证被拒绝。Kali最终running，Windows 11始终suspended，未自动停VM。PD多次观察到挂起，配置为关闭窗口suspend；触发者未实证。用户曾授权临时改keep-running，但PD要求Mac管理员认证，修改未生效，最终仍为原suspend，无待恢复改动。

**验证（实际范围）**：完整2241项，2220通过、21条件跳过、0失败（355.917秒，live-final-full.log及live-final-source.json）。该完整回归之后仅增加停止等待0.5秒上限与对应断言，受影响121项通过（41.370秒，live-final-affected.log），流/助手专项20项通过；不冒称完整回归已包含这一末补。A03主CLI历史透传另有36项通过；前端81项+构建、Swift类型检查及397项失败0为本轮已有证据，之后未改Swift。语法/diff及最终源摘要另存证据目录。

证据均位于`output/external-attach-r3-20261031/`：`pd-deployment-report*.json`、`pd-kali-netns-shell-*.log`、`pd-live-udp-result.json`、`pd-live-burst-result.json`、`pd-post-result.json`、`pd-cleanup-result.json`、`pd-key-revocation.json`、`pipe-readiness-before/after.log`及各失败日志。临时私钥不入库、不附在交接或候选材料。

**未完成**：真实靶机VM/业务及回连负向矩阵、QEMU hub后端真实来宾链、Fusion/Workstation与Windows原生、扫描/长时/睡眠故障矩阵、原生GUI操作、完整安装器与G0/G1均保留。普通TAP撤网路径已通过；teardown在命令失败时的回执与恢复仍须专门核对，不能凭本次正常收口推定全部故障路径正确。Mac持久历史/事件UI、T02执行模板门、W05安装准备和U04维护安排仍开放。
