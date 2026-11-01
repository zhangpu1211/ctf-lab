# 通用后端与原生退出观测验证（2026-10-24）

> 历史验收快照：本文件记录对应日期、源码和用户回传范围，不替代当前软件状态；后续实现以状态文档和新的验证记录为准。

范围：工作区候选；Windows 原生能力与来宾验收不由 Mac 测试替代。实现/操作边界见 [说明](ctflab-production-driver-2026-10-24.md)。证据根：`output/production-driver-20261024`。

## 本轮已执行

- `CTFLAB_RECOVERY_QEMU=/opt/homebrew/bin/qemu-system-x86_64 python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_qemu_driver.py' -v`：14 项通过。包括实际三节点参数、双回环链路、TLS QMP 与 VNC 帧；使用空白磁盘、TCG 和暂停 CPU，不启动来宾。日志 `driver-tests-final.log`。测试仅回收自己持有的 Popen 对象。
- `CTFLAB_RECOVERY_QEMU=/opt/homebrew/bin/qemu-system-x86_64 python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_windows_recovery.py' -v`：13 项通过，含既有无来宾 TLS 拒绝/重连和新增匹配退出记录读取/错误绑定拒绝。日志 `recovery-tests.log`。
- `python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_windows_exit_observer.py' -v`：4 项，3 项通过、1 项仅 Windows 原生用例跳过。覆盖句柄不匹配时关闭、超时不读退出码、合法退出码 259；不是原生 API 实测。
- Windows 相关测试首次运行 75 项，68 通过、7 条件跳过；该轮早于随后两项恢复记录测试，不能冒称最终全部源码均已被该轮覆盖。日志 `windows-tests-first.log`。

完整回归及最终检查将在收口时补记。测试输出中的 QEMU `-mon` 弃用警告原样保留，未掩盖。旧 r1 交付包保持原样，工作区源码有更新不代表该包更新。

## 明确未验证

Windows 固定构建、原生句柄跨父进程退出、监督器故障后的真实 QEMU 恢复、WHPX、来宾显示/键鼠、真实网络应通/禁通与课程服务均未验证。没有 Windows 连接信息，不能将条件跳过视为验收通过。产品 GUI、安装器、跨设备、签名、公证和发布未执行。

## 最终收口

完整本地回归 `python3 -B -m unittest discover -s tools/tests -v`：1032 项，1014 通过、18 条件跳过，221.439 秒，执行会话正常退出，日志 `full-regression-first.log`。完整回归加载后补充了显示入口、禁用 QEMU 用户配置、监督器身份记录及原生测试父进程拓扑；这些最终变更由对应专项复验覆盖，不宣称早先完整回归加载了后补代码。

补充禁用用户配置参数后，专项出现一次测试断言失败：原断言在整条命令中搜索 `user`，误把 `-no-user-config` 当成 user 网络。改为只检查 `-netdev` 的值，最终 14 项通过；真实三节点 fixture 在该次失败运行中已通过。失败日志保留为 `driver-tests-user-config-assertion-failure.log`。

最终 Windows 相关测试及隔离包检查结果见随后状态收口记录。临时源码包先前 53 项，51 通过、2 条件跳过，CRC、逐文件清单和两个 CLI 隔离入口通过；仅用于依赖验证，未保留为交付包。源码语法/差异空白检查通过。未提交、推送、发布、更新已发布 App 或覆盖旧 r1 包。

最终补记：Windows相关77项，70通过/7条件跳过，10.577秒，日志 `windows-tests-final.log`；最终通用专项14项通过，0.817秒。所有执行会话已退出，最终本机名称快照未发现QEMU进程；这不表示已盘点远端或其他平台实例。7个相关Python文件语法、入库白名单与空白检查通过，`git diff --check`通过。`final-evidence.json`记录最终源码摘要、各层验证范围与Windows原生待验状态。


### Windows 原生测试用户回传（2026-10-24）

用户在 Windows 自行执行测试源码包，并在本聊天粘贴控制台结果；未由助手远程执行，也未收到原始日志文件或独立核验主机/源码摘要。`test_ctflab_windows_native.py`：8项，6通过、2项非Windows边界测试按预期跳过，0.008秒；包含真实进程身份重复查询、原生文件锁竞争与释放。`test_ctflab_windows_exit_observer.py`：4项全部通过，8.436秒；关键 `test_independent_observer_survives_parent_exit` 为 ok，确认本用例下父进程自愿退出后，独立观测器仍记录短寿命Python子进程的退出码。

据此将“Windows原生身份/锁基础”和“Python测试进程的独立退出观测”更新为用户回传通过。PowerShell在合并原生命令stderr时显示NativeCommandError，但两组unittest最终均为OK；未回传进程退出码，不据该包装提示认定用例失败。无需重跑已通过用例。

范围不扩大：真实QEMU监督器故障、WHPX/TLS固定构建、来宾显示/键鼠、正常关机与网络/课程验收仍待执行，G0/G1未通过。下一步按自测步骤第3—5节，在核验固定运行时/基盘后使用新的Smoke运行目录验证显示和重连。未操作用户VM、未修改实现、未重打包或发布；旧日志与历史待验记录保留为当时状态。

### Windows 新实例启动失败回传（2026-10-24）

用户执行固定恢复入口 start，返回“操作未完成，现场保留：ValueError”，未出现 worker-created。尚无具体异常消息、目录阶段或日志，不能认定QEMU已启动或断定失败原因。源码入口会隐藏异常正文；已定位准备路径中的精确cryptography版本检查、QEMU/基盘校验、派生盘复制校验和证书准备等可能触发点，等待只读诊断回传。不重复启动、不删除现场、不绕过摘要校验；此前Windows原生两组通过结论保持，真实QEMU恢复仍待验。


Windows固定恢复候选用户回传补记（2026-10-24）：依赖版本不符及清单路径不存在的问题经用户调整后，start 返回 worker-created，observer-ready.json 存在。首次 status 返回 FileNotFoundError；随后用户通过 RuntimeClient.status() 只读直连得到 identity=running、control_reconnected=true、qemu_status=running、unfinished_operations=[]。据此记录“该Windows实例原生身份核验及双向TLS QMP重连：用户回传通过”。首次缺文件异常未复现，未取得其具体路径/堆栈，不能归因为已确认的启动竞争或宣称已修复。

用户回传worker-console日志为空，QEMU日志含旧-mon参数弃用及Ignoring request for interrupt vector 0警告。保留两项警告，不将查询成功扩大为来宾正常启动或警告无害。显示、登录、键鼠、窗口重连、正常关机/退出持久记录及真实监督器故障仍待验；G0/G1保持未通过。用户Windows实例可能仍在运行，助手未远程核验或操作，不按历史PID停止。下一步由用户在同一实例打开显示并验证来宾交互，无需重复start。


Windows显示与键盘用户验收补记（2026-10-24）：用户回传CTFLab实验显示截图，窗口显示已连接（Raw显示），Smoke已到Linux登录提示；随后明确反馈“可以正常输入和显示”。据此记录该固定Windows新实例的来宾登录提示画面、显示链路及键盘输入为用户实测通过。未据此认定登录成功、鼠标交互、窗口关闭后的重连保留会话、监督器故障恢复或正常关机通过。下一步由用户验证显示重连，保留运行实例；助手未操作VM、未提交或发布，G0/G1仍未通过。


Windows显示重连用户验收补记（2026-10-24）：用户按步骤在Smoke登录提示输入标记且不提交，关闭显示窗口后重新执行display，并明确回传“保留了”。据此记录“关闭显示窗口后重新连接并保留来宾输入状态”为用户实测通过。仅覆盖显示客户端退出/重连，不等同于监督器死亡、宿主重启或VM重启恢复。正常关机及匹配的observer-exit持久记录仍待核验；真实监督器故障、网络和课程服务仍待验，G0/G1保持未通过。助手未停止VM或执行其他现场操作。


Windows关机与持久退出用户验收补记（2026-10-24）：用户对该专用新Smoke实例执行一次powerdown，返回acknowledged、automatic_replay=false；等待15秒后status返回identity=exited，result.state=exited、returncode=0、source=retained-native-handle，observer-exit.json存在。RuntimeClient读取该记录时会比对实例/代次和binding身份；据用户回传记录“单次ACPI关机请求获确认后QEMU实际退出，独立原生句柄观测的持久退出记录可读”为通过。result.identity.state=running为启动时保存的身份快照，当前退出状态以外层identity/result.state为准；control_reconnected=false与退出后直接读取持久记录一致。

保留graceful_stop_verified=false，不据退出码0断言来宾服务完整关闭、文件系统一致性或已采集来宾关机事件。当前基础链路已有用户实测：原生身份/锁、Python父进程退出后的独立观测、固定QEMU TLS查询、显示/键盘、显示重连保留输入状态、关机请求后实际退出和持久记录。真实QEMU监督器故障恢复、原盘关机后摘要复核、来宾网络/课程服务及完整产品门槛仍未完成，G0/G1未通过。用户报告该实例已退出，助手未远程独立核验或按历史PID操作；保留运行目录、日志和证书，不自动清理、提交、重打包或发布。


Windows固定Smoke基础流程收口（2026-10-24）：用户按关机后原盘SHA-256核对步骤明确反馈“没有变化”，据此记录原盘摘要关机后复核为用户回传通过（预期摘要f9c2edc334c9e2839c1d605d6d870e8f68ad1242f892fe3f96ed75bfaf554052；未收到原始命令输出，不冒称助手独立核验）。本轮固定Windows新Smoke实例的基础流程已完成用户实测：原生身份/锁与Python独立退出观测、QEMU TLS查询、来宾登录提示画面/键盘、关闭显示后重连保留输入、单次ACPI请求后QEMU以0退出、匹配的持久退出记录、原盘摘要不变。

该收口不是完整Windows产品或通用生产后端验收：真实QEMU监督器故障恢复、通用多节点网络应通/禁通、来宾服务/课程与安装分发等仍待验；graceful_stop_verified保持false，G0/G1保持未通过。用户回传实例已退出，现场目录与日志保留，不按历史PID操作。无新增实现变更、自动清理、提交、推送、打包或发布。

后续接续语：继续 `/Users/pufei/Downloads/ctf-lab`，读取AGENTS.md、状态第82节末尾及 `docs/verification-production-driver-2026-10-24.md`。固定Windows Smoke基础流程已有用户实测闭环，不必重复；先核对源码与现场，下一阶段明确选择真实监督器故障恢复或通用多节点网络验收。Windows操作由用户执行，保留既有目录与资产，不自动停止VM、删除数据或发布。
