# A03 本地契约与 W01 独立驱动实施记录

2026-10-21。正式目录 `/Users/pufei/Downloads/ctf-lab`，HEAD `0994f62` 上保留前轮改动继续实施。用户授权实现本地契约与独立测试驱动，明确暂不操作 VM 或发布。本轮没有把新接口接入现有 Mac VM 的启停路径，也没有把 Windows 实机门槛标成通过。

关联：[第一阶段草案](ctflab-platform-foundation-2026-10-21.md)、[W01 实机清单](ctflab-windows-prototype-checklist-2026-10-21.md)、[Windows G0/G1](ctflab-windows-plan-2026-10-15.md#6-windows-社区预览范围与统一验收门槛)。

## 1. 已落地的模块与入口

| 模块 | 本轮实现 | 不应推导的能力 |
| --- | --- | --- |
| [ctflab_contract.py](../tools/ctflab_contract.py) | 严格 JSON/请求白名单、版本/类型/大小限制、规范化摘要、静态公开错误、事件去重与缺口检查 | 不检测硬件，不实现网络鉴权 |
| [ctflab_local_service.py](../tools/ctflab_local_service.py) | 受信主体绑定、持久意图/幂等、代次/revision CAS、取消、显式执行/恢复、只读状态与事件 | 不连接现有 VM，不取代 Windows 锁/ACL/进程监督适配器 |
| [ctflab_windows_probe.py](../tools/ctflab_windows_probe.py) | 默认候选计划、固定参数只读构建探针、临时存储与固定 Python 替身子进程自检 | 帮助输出与合成生命周期不证明 WHPX、受保护 QMP 或显示可用 |

这些模块可在没有 fcntl 和旧 Mac 运行器导入的情况下独立使用。三份模块已进入 Git/源码包白名单；复制到独立源码包后的 `-I` 自检也有测试，避免源码目录掩盖漏包。现有 Mac CLI/GUI 参数、状态格式和实际生命周期不变；本轮没有重打发布 App。

## 2. v1 消息与服务 API

协议名 `ctflab-local`、版本1。`parse_request` 拒绝重复 JSON 字段、NaN/Infinity、非法 Unicode、超过64KiB的消息；`validate_request` 拒绝未知版本、未知字段、路径/命令注入、伪布尔与非法 UUID。传输身份不在消息内。

- 所有请求：`protocol/version/request_id/instance_uuid/operation`。
- `status` 仅接受上述字段，不创建幂等记录或写操作。
- 写命令另要求 `expected_generation/expected_state_revision/idempotency_key/parameters`；prepare 的两个前置条件必须为 null，其他操作须显式给出当前代次与 revision。
- prepare 参数仅有 course_id/baseline_id；start 仅有 display（headless/console）和 allow_emulation；stop/recover 参数为空，stop 不接受 force；reset 仅有 baseline_id。
- 为落实草案的取消语义，新增显式 cancel 操作，参数只有 operation_id。取消响应表示请求已登记，目标操作的最终 cancelled 字段才表示取消是否生效。

`LocalService.create(root)` 只创建一个不存在的新目录，拒绝覆盖已有状态；`LocalService(root)` 只打开既有 v1 存储，不迁移旧 CTFLab 状态。传入的根必须是调用方选择的受保护本地目录，使用规范绝对路径；拒绝符号链接、重解析点与数据库硬链接，POSIX 下核验属主和私有权限。Windows ACL 仍由后续 PrivateStorage 现场验证，本轮不声称 chmod 或 SQLite 等同于 ACL。

调用接口：

| 方法 | 语义 |
| --- | --- |
| `submit(request, actor)` | 校验并登记写意图，返回 accepted；只读 status 直接查询。actor 来自受信调用方，不能从请求 JSON 自报 |
| `handle_json(text, actor)` | 供 CLI/GUI 传输适配共用的 JSON 边界，返回结构化错误且不回显非法请求/异常正文 |
| `execute(operation_id, actor, backend)` | 显式领取一次待执行意图并调用注入后端；默认没有 VM 后端，不自动重试执行 |
| `status(request, actor)` / `events(instance, actor, after, limit)` | 只读查询，跨主体拒绝；事件游标按实例，分页上限1000 |
| `prune_events(instance, actor, through)` | 受信维护接口，只修剪事件、推进最早游标，不删除幂等记录；没有自动清理或远程消息入口 |

后端实现 `observe(context) -> Observation` 和 `execute(request, context) -> Outcome`。Observation 必须表示现场核验的身份、代次、状态；Outcome 只接受受控状态、错误码、取消结果和不含路径的证据ID。后端自行解析已经登记的课程/基线和资源归属，不从消息直接执行宿主命令。普通操作要求观察代次完全相同，recover 才允许在后端证明下接受原代次或下一代次；不得用日志 PID 自证身份。

本轮提供的 FixtureBackend 只更新内存变量，它的 process-running 不表示有 QEMU 进程。原生适配器接入前仍需验证课程注册、磁盘绑定、进程身份、控制通道与权限。产品 CLI/GUI 的实际启停接入与受保护 IPC 尚未实现，A03 完整产品验收仍需这些证据。

## 3. 幂等、并发、取消和失败窗口

采用两个独立的本地 SQLite 文件：`contract.sqlite3` 保存实例、意图、结果及事件；`worker.sqlite3` 只提供跨进程执行互斥。它们位于新建私有根，不改变原场景账本、日志或磁盘布局。

1. 请求在契约事务中查归属与幂等，然后检查代次/revision、预约实例并提交 intent；这一步失败时不调用后端。
2. 幂等键按主体绑定完整请求摘要（排除本次 request_id），同时绑定实例、操作、参数和初始前置条件。同键同请求重试先返回旧结果，再考虑新的 revision；同键不同内容拒绝。
3. 执行器取得工作库写锁，确认意图仍为 pending 且仍属于活动操作，先持久化 executing，再调用后端。所有实例本阶段串行执行；提交、状态、事件和取消使用独立契约库，可以在长操作期间处理。
4. 执行器崩溃或结果提交失败时，已落盘 executing 意图不重新执行；状态/重试保守返回 unknown 或 recovery-required。没有依据进程存活猜测成功；一个活跃长操作尚未提交结果时也采用这种保守显示。
5. recover 先取得同一工作锁，防止与活跃执行器竞争，再把旧意图记为未知并创建新的恢复操作。工作锁已释放只证明原执行段不再持锁，不证明 VM 已停；后端仍须现场核验所有资源。后台仍在工作时 recover 返回 resource-busy。
6. reset 只有成功提交才递增代次；错误和取消不递增。新代次来自真实恢复观测的情况仅限受信 recover，身份未知时不进入破坏操作。

取消与提交按实际结果处理：排队操作收到取消后不调用后端；执行中的后端在安全点读取 `context.cancel_requested()`。不能取消的提交若已完成，返回真实完成且 cancelled=false，不能为了符合取消请求假称已撤销。正常 stop 超时保留现场，返回 stop-timeout/recovery-required；协议没有强制停止入口。

SQLite 使用事务和 FULL 同步模式，存储异常不抹除已有意图。版本不兼容、数据库损坏、权限读取失败必须显式处理，不自动建空库掩盖失败。SQLite 本地事务测试不替代 Windows 存储/ACL、真实断电或打开文件语义验收；不支持把网络共享或同步盘当作已验证活动状态存储。

## 4. 事件、输出与身份边界

事件包含实例、代次、操作ID、revision、单调 sequence、UTC 时间、状态与阶段，在事务提交后才能被订阅者读取。客户端 `merge_events` 支持重复页去重，拒绝缺口、混入其他实例、同一事件ID对应不同序号和未知结构。代次变化仍在同一实例事件流中连续；游标不是时间戳。游标已修剪或超前时返回 cursor-expired，必须重新读取状态。

结果区分 accepted/completed/conflict/failed/unknown；资源准备、进程运行、来宾就绪、服务就绪和课程验收仍分别表示。后端异常正文、stdout/stderr、私有路径、环境变量不会直接进入公开错误；证据仅使用受控ID。受信后端不能把凭据伪装为证据ID，这个接口边界不是任意日志的通用脱敏器。U02 完整诊断导出仍是独立任务。

主体身份是服务调用参数，写入时与实例绑定；真实 IPC 认证、Windows ACL、凭据管理和多用户服务均未完成。没有开放端口、命名管道或后台监听服务，不可把本模块直接暴露给不可信客户端。

## 5. W01 驱动的三种用法

默认只生成候选计划，九项实机探针全部显示 not-tested：

```bash
python3 -B tools/ctflab_windows_probe.py
```

合成自检创建临时契约根，运行准备/启动/停止/重置的内存替身、持久幂等重放、重新打开存储、事件重放，再启动固定自有 Python 子程序验证 stdio 身份关联。无网络与 VM，报告 `scope=synthetic-only`、`g0_passed=false`、`native_windows_verified=false`：

```bash
python3 -B tools/ctflab_windows_probe.py --self-test
```

后续在**获准 Windows x64 设备和可信锁定构建**上，可显式运行只读构建检查：

```powershell
python tools/ctflab_windows_probe.py --inspect-runtime C:\CTFLab-W01\runtime-manifest.json
```

本轮没有执行上述 Windows 命令。清单是严格 JSON：顶层仅 schema=1、build_id、target=windows-x86_64、components；components 必须有 qemu，可选 python/firmware/display-client。每项仅包含规范绝对 path、64位小写 sha256、version、source_id，qemu 文件名限定为 `qemu-system-x86_64.exe`。source_id 应引用另行保留的来源/许可/构建配方记录，不写凭据或访问链接。

驱动先核验所有列出组件的哈希和路径，再执行固定查询 `--version`、`-accel help`、`-display help`、`-device help`；每次执行前复查 QEMU 哈希。拒绝清单里的自定义参数，不启动来宾、不打开控制/显示端口、不启用系统功能或自动降级 TCG。版本输出不匹配、超时或非零退出保留失败，报告仅有输出哈希和固定能力标签，不回显原始输出/路径。完整组件缺失单独标记，帮助输出出现 whpx 不代表硬件探针通过；所有实机步骤仍为 not-tested。

九项实机验证仍按 W01 清单执行。当前驱动没有原生 VM 启停、QMP、显示、ACL、socket共享、Job 或真实恢复后端；这些需后续接入，不能用 self-test 或 build_inspection_passed 关闭 W01/G0。

## 6. 验证与继续入口

针对性测试：

```bash
python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_local_contract.py' -v
python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_windows_probe.py' -v
```

本地契约26项、驱动12项均通过，另增加独立复制源码后的驱动自检。覆盖非法版本/字段/参数、跨主体/实例/代次、重放/幂等冲突、线程与跨进程互斥、意图和结果写入失败、真实替身进程在模拟副作用后退出、未知身份禁止破坏、停止超时、取消竞争、事件缺口/过期、状态读取不写盘、输出边界、固定参数与哈希、版本不符、超时，以及无 fcntl 的导入。

完整回归与收口结果见 [当前状态第59节](ctflab-current-status.md)。后续先对接受保护的本地传输和经核验的实际后端；Windows 实机前仍须指定设备、来源资产、独立状态根及操作范围。已有用户 VM 不在本轮范围，不自动启动/停止、删除数据、提交、打包发布或建立外部服务。

## 7. 后续本机适配入口（2026-10-21）

新增 `tools/ctflab_local_adapter.py`，供受信本机宿主代码和命令入口共用。主体由当前普通 POSIX 进程的有效 UID 取得，拒绝 root、实际/有效 UID 或 GID 不一致的进程；每次请求复核身份。Windows 入口暂时拒绝，不能在未验证 token/ACL 时默认放行。身份来自进程而非请求体，**这不是跨用户 IPC 认证，也不防御同一用户运行的恶意代码**。

`LocalAdapter(root, backend=None)` 打开既有私有契约目录；默认只准 status，写操作在记录意图之前拒绝。受信宿主代码可以注入经过核验的后端，提交后显式执行 accepted 操作，重试仍使用原幂等结果；取消和事件遵循原服务语义。CLI 不提供选择后端、指定主体或放开写权限的选项，不初始化或迁移目录。

入口（从标准输入读取一行一个 v1 请求）：

```bash
python3 -B tools/ctflab_local_adapter.py --root /absolute/private/contract-root
python3 -B tools/ctflab.py local-contract --root /absolute/private/contract-root
```

第一条可独立使用，第二条复用 Mac 主 CLI，但在构造旧运行状态之前分派，不创建旧状态目录。输入按字节限制为64KiB，严格 UTF-8；超长或缺少换行的帧返回错误后结束会话，避免把尾部误当新请求。错误保持完整协议响应结构，不输出私有路径或异常正文。没有创建监听端点，不把继承的标准输入声明为已认证的共享服务。

新增12项适配测试涵盖同一核心调用、幂等、写入前拒绝、身份伪造/变化、特权及不支持平台拒绝、有界消息、UTF-8、截断、真实隔离 Python 子进程只读、缺失根不创建和主 CLI 不创建旧状态；另补隔离源码包中的适配模块入口检查。完整回归结果以状态第60节为准。

下一道必要决策是 W01 实机选型：命名管道/ACL 或受保护 TCP、显示组件、进程监督及 socket 交接仍需获准 Windows 物理机。依照 Windows 专项第6节，完整 Windows GUI 在 G0 后投入，不能用本机 stdio 入口或合成后端替代这一门槛。此处尚未接入现有 GUI，也未将实际 VM 后端标为完成。

## 8. Windows 身份与私有存储接入（2026-10-22）

第7节中“Windows 入口暂时拒绝”是当时状态；现已加入 `ctflab_windows_security.py`，接入 `LocalService.create`、打开根、每次数据库连接及 `LocalAdapter` 主体解析。它使用原生 token 中的当前用户 SID，并拒绝提权和线程模拟身份；持久主体使用 SID 摘要，不从消息接收身份。

新根通过 CreateDirectoryW 在创建时设置受保护 DACL，仅当前用户和 SYSTEM 全控制，文件/子目录继承该限制。不修改现有目录 ACL，不先建立宽权限目录再收紧。根属主须为当前用户，根 DACL 须保护；空 DACL、Everyone/Users/Administrators等其他主体、复杂或拒绝 ACE、当前用户权限不足均保守拒绝。数据库文件再次核验属主与 ACE。拒绝 UNC、设备命名空间、ADS、保留名、父级路径及链接/重解析点；不在网络共享上试探创建活动状态。

这不是跨用户 IPC 或对同用户恶意代码的隔离；受信调用方仍应选用当前用户私有目录的本地父路径。原生 API 代码已完成本地策略/契约测试，但本轮不是 Windows 主机，创建根、继承文件、拒绝宽松ACL和完整契约接入的原生测试明确跳过，不能据此声称 Windows 存储已实机验收。真实后端、受保护 QMP、显示和持久监督仍未完成。

依据：[GetNamedSecurityInfoW](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getnamedsecurityinfow)、[安全描述符转换](https://learn.microsoft.com/en-us/windows/win32/api/sddl/nf-sddl-convertstringsecuritydescriptortosecuritydescriptorw)、[GetTokenInformation](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-gettokeninformation)、[CreateDirectoryW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createdirectoryw)，2026-10-22核验。WHP前置检查使用 [WHvGetCapability](https://learn.microsoft.com/en-us/virtualization/api/hypervisor-platform/funcs/whvgetcapability)，只读查询，不创建分区。
