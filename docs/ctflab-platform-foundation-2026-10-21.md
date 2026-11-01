# 平台基础第一阶段：A01/A02 与 A03 草案

后续实施更新（2026-10-21）：本地契约核心和独立驱动已完成，见 [A03 本地契约与 W01 独立驱动实施记录](ctflab-local-contract-w01-2026-10-21.md) 与当前状态第59节。本文原阶段草案/清单保留；Windows 实机、受保护 IPC 与原生后端仍待实现或验证，G0/G1 未通过。

2026-10-21，正式目录 `/Users/pufei/Downloads/ctf-lab`，基于 HEAD `0994f62` 与保留的工作区规划。用户同意完成上一轮列出的第一阶段：A01 依赖梳理、A02 纯策略实现、A03 本地协议草案、W01 原型验证清单。本文不表示全部 Windows 产品或 G0/G1 已完成。

关联：[Windows 社区预览门槛](ctflab-windows-plan-2026-10-15.md#6-windows-社区预览范围与统一验收门槛)、[任务表](ctflab-implementation-backlog-2026-10-15.md)、[W01 原型清单](ctflab-windows-prototype-checklist-2026-10-21.md)。

## 1. A01 真实入口与平台依赖归属

调查范围是单机/安装器、场景准备到恢复、打包与 GUI 调用边界。下面按调用族列出当前符号、平台假设、拟归属和必须保留的行为；接口名称为设计责任，不代表已有 Windows 实现。来宾安装脚本属于客体适配，不随宿主抽象一起重写。

主调用链：

- 单机：CLI/GuiApp → `LabManager.run` → `operation_lock` → overlay/固件准备、`ensure_network` → `qemu_command` → 子进程/状态登记。`stop/reset/snapshot` 仍通过同一操作锁和停止检查。
- 安装器：`start_install` → ISO 校验/安装副本 → `installer_command` → 子进程与安装状态；`stop_install/finalize_install` 独立处理，不能混作普通运行实例。
- 场景：`cmd_scenario_*` → 纯清单/计划 → resources 预约 → registry 登记 → services 网络就绪 → nodes 启动 → runtime 观测/接管。reset 另以旧代次停止证明、新资产准备、活动指针切换和恢复日志闭环。
- 打包/界面：`ctflab_package.RELEASE_TOOL_FILES` → `ctflab_app._copy_ctflab_sources` → Mac GUI 调用随包 CLI；新增纯模块必须进入白名单。新 Windows 界面后续只调用共享契约。

| 入口/符号与拥有文件 | 当前平台依赖 | 拟归属与 Windows 替代 | 不可退化的行为/验证入口 |
| --- | --- | --- | --- |
| [ctflab.py](../tools/ctflab.py)：`cmd_doctor`、默认状态目录、工具/固件查找 | Darwin arm64、Library、PATH/随包布局 | HostCapabilities / RuntimeBundle / PrivateStorage；系统标签与探针分开、显式本地状态根 | 不把候选当可用；随包优先；test_ctflab_lifecycle/app/runtime_isolation |
| 同文件 `installer_command/qemu_command`；[scenario](../tools/ctflab_scenario.py) `qemu_command` | 三处 HVF/TCG、host/max 参数 | A02 纯策略已接入；平台适配前仍固定生成 Mac 参数 | 原 argv、固件、磁盘、网络、显示和 QMP 顺序不变；平台/安装器/场景测试及旧版参数对照 |
| ctflab.py `operation_lock`；[resources](../tools/ctflab_scenario_resources.py) `_resource_lock` | 顶层 fcntl、flock、句柄继承 | StateLock；后续 Windows 原生排他锁原型 | 竞争拒绝/超时、崩溃释放；存在锁文件不等于持锁；lifecycle/resources 测试 |
| ctflab.py `_unix_socket_path/_spice_socket/_spice_ticket`；resources `_private_directory/_private_tree/_verified_file` | UID、st_uid、0700/0600、UNIX socket 长度、短目录 | PrivateStorage / ControlTransport / DisplayBackend；SID/ACL、reparse point 与私有端点 | 拒绝越界、冒名所有者/链接、非私有目录；不暴露 ticket；resources/runtime_isolation |
| [registry](../tools/ctflab_scenario_registry.py) `read_events/append_event/active_reservations`；[services](../tools/ctflab_scenario_services.py) `_read_binding` | 文件所有者/权限、持锁账本和日志 | PrivateStorage + StateLock；保留核心资源归属与事件语义 | 缺失、损坏、未登记对象不自动接管；registry/services/continuation 测试 |
| ctflab.py `qmp_execute`；[runtime](../tools/ctflab_scenario_runtime.py) QMP 连接/观测 | AF_UNIX、私有路径、QMP 握手 | ControlTransport；命名管道或受保护回环 TLS 候选 | 不开放无保护 QMP；重连核验实例/磁盘/代次；runtime/nodes_reset |
| runtime `process_start_identity/process_command/child_identity/popen_spawn`、接管停止；ctflab.py `bool_pid_alive`、stop 系列、显示客户端回收 | `/bin/ps`、POSIX signal、新会话、os.kill | ProcessSupervisor；原生进程句柄/创建时间/可执行身份、角色化 Job | PID 不自证归属；unknown 禁止破坏动作；关 GUI 不误杀 VM；runtime/lifecycle/clipboard_lifecycle |
| ctflab.py `ensure_network`；resources 网络预留；services `NetworkServiceSession.start/stop`；[network](../tools/ctflab_network.py) 主循环 | pass_fds、监听 FD、SIGTERM；回环交换机 | NetworkBackend / ProcessSupervisor；socket sharing 或一次绑定的私有就绪协议 | 不出现端口检查后再绑定窗口；身份/配置匹配才 ready；停止节点后释放网络；services/resources/dhcp |
| resources `collect_macos_routes/parse_macos_routes/fresh_routes` | `/usr/sbin/netstat -rn -f inet` | HostCapabilities / NetworkBackend；受控 Windows 结构化路由采集 | VPN、冲突、采集失败与过期拒绝；不能静默漏路由；resources 测试 |
| [reset](../tools/ctflab_scenario_reset.py) `_write_json/_sync_directory/reset_scenario_assets/resume_reset_resources`；ctflab.py overlay/NVRAM/snapshot | chmod、fsync、目录与文件替换、打开文件语义 | PrivateStorage；平台化持久化与提交语义 | 旧代次保留、所有资源停止证明、提交失败可恢复，禁假设跨卷原子；nodes_reset/continuation/snapshots |
| [utm](../tools/ctflab_utm.py) `exclusive_rename`；ctflab.py `_publish_pack_profile`/候选保存；[inspect](../tools/ctflab_inspect.py) 导入；[dist](../tools/ctflab_dist.py) 内容包 | Mac renameatx_np、os.link、权限/发布语义；其他平台回退存在竞争窗口 | PrivateStorage；W02 必须验证真正无覆盖发布，不能直接采信兼容回退 | 原始盘不改、并发不能覆盖目标、清单/哈希校验保持；import_integrity/utm_export/dist |
| ctflab.py ISO 提取/安装材料准备、`storage`/诊断 | bsdtar/cpio、statvfs、POSIX 权限；内容可能敏感 | RuntimeBundle / PrivateStorage；随包受控工具、跨平台空间查询；U02 另做脱敏 | 缺工具明确拒绝；空间不足不改原盘；诊断默认不上传；installer/storage/docs |
| ctflab.py SPICE 选择/共享/重连；[GuiApp](../gui/GuiApp.swift)、[GuiCore](../gui/GuiCore.swift) | Cocoa、SwiftUI/AppKit、Mac 客户端，CLI JSON/日志 | DisplayBackend + A03；Windows 显示候选独立验收、新薄壳后置 | 共享默认关闭、显式不支持则拒绝、关窗不误停；file_transfer/client_input/gui/status_docs |
| [app](../tools/ctflab_app.py)、[package](../tools/ctflab_package.py)、[update](../tools/ctflab_update.py) | Mach-O/otool、codesign、Swift 编译、shell 安装器、Mac 包路径 | RuntimeBundle；新增 Windows 构建器，旧 Mac 构建器保留 | 模块/固件/许可证清单齐全，版本/哈希/更新回退；app/package/update 测试 |
| UTM 导出/控制与 `tools/ctflab` 启动脚本 | UTM/utmctl、Mac 路径、POSIX shell | Mac 专属入口保留；Windows 有独立入口，外部接入由 E 系列负责 | 不因平台抽象承诺 UTM/VMware/VirtualBox 通用生命周期 |

本轮没有将 fcntl、进程监督、权限或控制端点“替换成空实现”；主 CLI 在 Windows 上仍不可作为运行器使用。纯模块可独立导入只是 A02 的边界证明。A01 的上述清单完成；各替代实现归 W01/W02/W03，不能将接口命名视为已完成适配。

## 2. A02 已实施接口与边界

[ctflab_platform.py](../tools/ctflab_platform.py) 只依赖 Python 标准库。`HostPlatform` 规范化系统与架构，`plan_execution` 接收目标宿主、来宾架构、加速策略、显式模拟许可和硬件要求，返回不可变 `ExecutionPlan`。`compute_arguments()` 仅给出 -accel/-cpu，`report()` 始终注明 `runtime_verified=false`、仍需探针，不检测或启动本机资源。

| 目标 | auto 选择 | 限制 |
| --- | --- | --- |
| Mac ARM64 → ARM64 | HVF / host | 保持既有 Mac 策略，不新增现场可用证明 |
| Mac ARM64 → x86_64 | TCG / max | 通用接口必须显式 allow_emulation，硬件必需课程拒绝；旧 Mac 包装器保留已有 TCG 约定 |
| Windows x64 → x86_64 | WHPX，不覆盖 CPU 默认参数 | candidate-only；W01 必须实测并锁定 CPU/运行时组合；不能直接交给 Mac builder |
| Linux x64 → x86_64 | KVM / host | candidate-only；后续 L01 独立验收 |
| 未纳入的宿主/架构、Windows/Linux ARM 来宾 | 拒绝 | allow_emulation 不能扩大首轮矩阵；不支持任意加速器参数 |

显式 `acceleration=tcg` 仍须 `allow_emulation=true` 且 `require_hardware=false`；auto 不因“允许模拟”改选 TCG。未来探针报告硬件不可用时必须解释并拒绝，用户另选兼容模式后重新规划，不得悄悄回退。

三个既有 builder 使用 `macos_execution_plan`，明确目标 Mac ARM64，避免在 CI/开发机不同系统上隐式改变参数。保留旧的固件、网络、磁盘、显示、锁和停止路径。单机内部 builder 额外拒绝非法架构，避免原先 else 分支将任何未知架构当 x86；正式 profile 的白名单校验保持原样。宿主别名规范化不等于放宽内容包 schema。

可独立查看 Windows 候选计划（不执行 VM，不写状态）：

```bash
python3 -B tools/ctflab_platform.py --host-system Windows --host-architecture AMD64 --guest-architecture x86_64
```

新增依赖已加入 Git 和 `RELEASE_TOOL_FILES` 白名单，并修订独立 App 布局测试夹具；本轮没有重建发布 App。

## 3. A03 本地命令/事件协议草案（未实现）

首版协议名 `ctflab-local`，版本1为候选。协议负责结构与业务语义，传输层必须独立提供用户身份与访问控制。不能相信请求体自报的用户名、PID、可执行文件或目录即授权；实例必须由受信运行器从已配置状态根解析，外部消息不能指定任意宿主路径/命令。现有 CLI/GUI 输出暂不改，后续以兼容适配层接入，不在本轮引入新常驻服务。

### 3.1 请求与幂等

| 字段 | 契约 |
| --- | --- |
| protocol/version | 固定协议名与整数版本，未知版本/字段拒绝；另有只读能力协商，能力声明不证明来宾就绪 |
| request_id | 每次调用的唯一关联标识，用于响应追踪 |
| operation | 白名单 status/prepare/start/stop/reset/recover；显示连接独立受控命令，禁 shell/qemu_args |
| instance_uuid / expected_generation | 除全局只读列表外必填；初始化 prepare 使用显式“尚未存在”前置条件；实例不存在/代次不匹配均不执行 |
| expected_state_revision | 写命令必填，锁内对照当前状态；过期返回冲突，不能由界面强行覆盖 |
| idempotency_key | 写命令必填，与调用主体、实例、操作及规范化参数摘要绑定；status 不要求也不创建操作记录 |
| parameters | 按操作严格白名单：prepare 引用已登记课程/资产；start 声明显示/策略；stop 默认正常关机；reset 指定已验证基线；禁任意路径、网络出口与强制绕过 |

同一幂等键/相同参数重试，返回原 operation_id 和结果；相同键/不同参数返回冲突，禁止重复创建。收到重试时先查已绑定幂等记录，再判断新操作的 revision，防止原请求成功后因 revision 前进而误报重试失败。不同键的并发命令仍在实例锁/资源锁内做 CAS，不以幂等键替代锁。

写操作必须先持久化 intent，再创建资源；执行成功、失败或未知窗口均记录同一操作。启动后持久化失败须进入 recovery-required，不重发创建。重启后依据意图、资源账本及实际身份恢复，禁止只靠旧 PID；去重记录保留期不得早于关联实例/代次恢复需求。准备新状态格式或清理记录需要独立迁移/回滚设计。

### 3.2 响应、事件与状态

响应含 protocol/version、request_id、operation_id（写操作）、instance_uuid、generation、state_revision、结果类型（accepted/completed/conflict/failed/unknown）与结构化错误。accepted 仅表示已受理，不表示 QEMU 或课程就绪；长操作返回事件游标供断线后续读。

事件至少包含 event_id、单调 sequence、UTC 时间、实例/代次、operation_id、state_revision、阶段及结构化详情。先持久化再发布；客户端按 event_id/sequence 去重，检测缺口，重新查询权威 status。跨操作按实例 revision 关联，不假设系统时钟单调。游标过期明确返回 cursor-expired 并要求快照重取，不伪造连续事件。

状态分层：prepared（资源准备）、process-running（进程身份有效）、guest-ready（来宾检查）、service-ready（服务检查）、course-verified（课程记录）。另有 starting/stopping/stopped/failed/unknown/recovery-required；界面不得把 process-running 显示为已可做实验，也不得把权限读取失败显示成 stopped。设计隔离与已测隔离单列，外部连接在线不代表全路径隔离通过。

错误至少包含 code、stage、message、retryable、preserved、recovery_actions 和脱敏 evidence_refs。候选 code：unsupported-platform、capability-unverified、version-mismatch、state-conflict、identity-unknown、permission-denied、route-conflict、resource-busy、storage-insufficient、control-unreachable、stop-timeout、reset-commit-failed。retryable 不能授权自动重启/重置；recovery_actions 必须受当前权限和状态约束，不能携带任意命令。

进度取消只是请求：准备阶段可撤销未提交派生对象；运行/提交后需重新核验状态并返回实际结果。正常停止超时保留现场，强制停止另有用户明确操作和独立授权，不作为默认重试。GUI 退出仅断开订阅；监督进程负责存续，不能由 GUI Job 关闭误杀课程。

### 3.3 后续实现前必须覆盖的契约测试

未知版本/字段、参数注入、跨主体/实例/代次、幂等重放与不同参数冲突、并发 CAS、创建后日志失败、监督进程重启、事件重复/缺口/游标过期、取消与提交竞争、正常停止超时、身份未知禁止破坏、状态只读无写入、脱敏前后关联可用。先为同一业务服务提供 CLI/GUI 适配测试，再接 Windows 界面；A03 只有草案完成，不能标成协议实现已验收。

## 4. 第一阶段验证与完成边界

新增测试入口：`python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_platform.py' -v`，11项通过。覆盖策略/架构/模拟许可/硬件要求/参数注入、无 IO、无 POSIX 运行器依赖的独立导入、候选 CLI 输出以及三处实际 builder 调用。

将修改前源文件快照与本轮代码在同一合成路径/固件绑定下逐项比较：5个内置 profile × 有头/无头10组、Kali SPICE监听/剪贴板/文件传输8组、安装器自动/交互与有头/无头4组、三场景节点含/不含SPICE6组，共28组完整 argv 和端口映射一致。没有启动 VM；这证明参数等价，不证明来宾或显示体验回归已通过。

完整本地回归、语法检查与最终状态见 [当前状态第58节](ctflab-current-status.md)。需要真实来宾/桌面的测试保持显式关闭或条件跳过；不把本轮单元/合成结果换算成 Windows、跨设备或发布验收。A01 清单与 A02 纯策略完成后，下一步是 A03 实现与获准 W01 实机原型，而不是直接开始完整 GUI。


2026-10-30当前增量：第134节重建当前28组完整Mac参数对照；第136节补当前实际入口/源级责任/接口符号与快照复核，见[当前平台责任定义](ctflab-platform-ownership-2026-10-30.md)。本文件上述内容保留2026-10-21范围，不把历史草案当当前实现说明；当前源级盘点/接口定义不等于Windows/Linux原生适配完成。
