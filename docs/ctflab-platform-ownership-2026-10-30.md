# A01当前平台责任与接口定义（2026-10-30）

本轮对应原A01：盘点ctflab.py、scenario/runtime/resources/services/app的平台依赖，定义能力、锁、进程、路径、网络和显示接口，给调用明确责任与替代路径，保留现有行为/异常语义。完成的是当前源码的盘点与接口定义，不是把接口命名当作跨平台实现或原生验收。原Windows Smoke不重做，旧Mac运行链/更新器/App保持。

## 范围与证据解释

固定正式目录/分支/HEAD见状态第136节。原六个文件加当前本机/桌面/版本入口共14个根，沿Python本地导入关系得到85个模块；同时保留Rust入口/有界传输和Swift核心/界面的4份源码摘要。盘点与快照复核器只做AST解析/文件读取，不导入或调用被盘点模块。后述合同测试另外导入相关实现、使用自有临时夹具；两者不混称原生执行证明，不控制真实VM或运行实际调度/打包。

全量22998个AST调用保存在output/platform-ownership-20261030/raw-call-inventory.json。交付JSON列3731个平台候选，逐项保留模块、作用域、行列/表达式摘要、调用方责任、逻辑接口和需关注的分派信息；85模块均有责任与执行位置说明。其余纯计算/未筛选调用仍能由模块找到调用方责任，不把它们都当系统调用。文件/方法名和原生provider范围采用过近似，可能包含纯调用；这不是可执行调用图，也不证明筛选器穷尽Python动态行为，不能用数量换算覆盖率或产品完成。

26处同名导入逐条核对当前函数先前局部导入或模块全局定义，避免把不同函数/平台分支的observe、declaration、verify混为一条绑定；目标符号存在性也核对。14处动态分派保留理由：CLI固定handlers字典、显示本地输入队列、内部固定Win32取路径函数、上传status/finish二选一。125处参数调用是受信Python调用方/构造器注入，含时钟/测试替身，不是JSON传入的可执行函数；其合同和实际provider必须分开，不能据此提升native_verified。

七个名称是**责任接口**，不是新建同名基类。JSON内60个当前符号均从源码核对定义/行号/参数：并不存在DarwinDriver模块、LocalService.gate或reserve_network_ports函数；Mac通用链复用QemuDriver，SQLite工作门在_transaction/execute，旧监听预约在prepare_network_resources及PreparedNetworks.ports。未用愿景名称冒充落地实现。

## 接口、当前入口和异常合同

| 责任接口 | 输入/输出及当前入口 | 平台替代与必须保留的语义 |
|---|---|---|
| HostCapabilities | 显式系统/架构/策略→HostPlatform/ExecutionPlan；plan_execution、native_observe、hypervisor_capability、runtime_dependencies | 三处旧Mac builder固定Mac策略；WHPX/KVM/HVF探针各分流。系统标签、模块存在/后端枚举只算候选，不证明硬件可用；不支持/未知不自动降级TCG；错误组合先拒绝 |
| StateLock | 私有根/对象作用域→独占上下文或忙；operation_lock、_resource_lock、command_lock/state_lock、GenerationStore.locked、LocalService._transaction/execute | POSIX flock/SQLite与Windows LockFileEx分别实现；线程门仅保护本进程，不冒充跨进程资源锁。内核锁崩溃释放不意味着意图成功，Supervisor旧排他标记中断仍保留；不能仅因锁文件存在/消失推断实例可接管 |
| ProcessSupervisor | 自有Popen、实例/代次/尝试、原生ProcessIdentity→running/absent/mismatch/unknown或绑定结果；QemuDriver、*_native.observe、Win32.retained、OwnedPipe/Supervisor | Darwin libproc、Linux proc/启动身份、Windows内核句柄/创建时间各有provider，角色化Job另验。PID/argv不单独授权控制；身份不明不重启/终止。先意图后派生，未知不重放，超时/GUI退出不能误杀VM；匿名管道不能凭磁盘记录重接 |
| PrivateStorage | 可信根/资产摘要/对象身份/容量声明→核验、派生材料、账本或拒绝；_guard_path/_windows_storage、GenerationStore、storage_*、server_storage、exclusive_rename | 原件只读使用，写新overlay/NVRAM/代次/临时材料；POSIX权限与Windows ACL/重解析/卷设备句柄分开。已配置专用卷只观察，不自动创建或改宿主卷。缺失/部分/身份变化/容量未知先拒绝，旧代次/失败材料留存，不假定跨卷原子或未测Windows持久性 |
| NetworkControl | 宿主批准的计划/端点/证书/就绪身份→控制会话或拒绝；prepare_network_resources、NetworkServiceSession、QemuDriver.network_arguments/connection、QMPClient | 旧Mac预先持监听FD并通过pass_fds交接；共享后端当前QEMU回环星形链路不是原交换机的Windows端口交接实测。私有UNIX或mTLS控制保持，不开放无认证QMP；监听存活不等于课程ready，身份/就绪/过期不符拒绝，丢回复不重发副作用 |
| DisplayBackend | 显式连接、实例/代次/证书及有界帧/输入→自有显示会话；Mac SPICE/Cocoa、RFBClient/show、QemuDriver.display、薄壳适配 | 原Mac入口保留，Windows/Linux RFB/Tk/Tauri候选另验；请求窗口不等于实际显示成功。连接身份不符或队列超限只断自有显示；不重放键鼠，共享按显式授权，关闭显示不关VM |
| RuntimeBundle | 固定运行时/入口、来源/文件集/签名/版本/许可证→布局、计划或结果；app/package、runtime_inventory、desktop_package、ReleaseLauncher/UpdateCoordinator/VersionSetup | Mac Mach-O/codesign与旧更新器保留；Windows Python/QEMU/WebView2/NSIS/Authenticode与独立管理入口各有未验门。验证精确文件集，未知退出保持unknown，当前版本内应用不能变更自身；不自动安装/迁移/回退/删除旧版 |

新共享契约的ContractError/结构化public_error不替换旧Mac CTFLabError/ScenarioError语义；本轮没有重写运行代码或抹掉旧错误/恢复路径。平台原生故障、正常停机证明、完整G0负向、真实网络/显示/总量压力仍按原W/S/D/R任务验，不因分配了接口名而通过。

## 实际入口和分流

- 旧Mac：GuiApp以固定CLI命令驱动LabManager；操作锁、overlay/NVRAM与原网络/显示/QMP路径继续存在。A02仍为三处参数策略抽取，没有同时替换磁盘布局或生命周期。
- 共享本机：desktop_bridge→LocalService持久意图/幂等与工作门→ScenarioCoordinator/GenerationStore→QemuDriver。运行时/计划/原生进程/磁盘/代次/证书核验分层；VMGenID在明确声明时绑定，不热改运行设备。原生查询与不确定结果不等于课程或域健康。
- 系统观察：QemuDriver.native_observe按sys.platform进入Darwin/Linux观察器，否则走原Windows观察；hypervisor_capability同样分开。不把Darwin测试文件名当独立Driver实现，未知/不支持平台不授予变更能力。
- 远程：desktop_remote/client_store→固定SSH命令/配置身份→账户/角色/租约/审计→相应服务器或来宾后端。来宾agent/routed/analysis的系统操作在来宾执行；导入其编译/协议函数不代表在宿主执行。SSH、E系列外部VM和D系列来宾资源不由本机A01接口自动接管。
- UI：Tauri main.rs/run_bridge经Transport.execute持自有有界事务；Swift GuiApp中的Process执行CLI，GuiCore持收集/请求寿命/一次性交付类型。4份非Python源摘要只固定这些入口边界，不声称完成了AppKit/Tauri调用图、窗口或用户体验验收。
- 版本：首次设置和签名版本操作由固定桥接进私有版本库，Mac保持只读与旧更新链。新配置、信任根/签名、运行程序退出绑定是不同证据；W05安装/卸载/干净机和更广未知恢复仍未闭环。

## 可复核快照与验证

`ctflab-platform-ownership-2026-10-30.json`记录当前源摘要、模块责任、七份合同、60个实际符号及候选位置。`tools/tests/check_ctflab_platform_ownership.py`只读核对固定快照摘要、85源文件/4薄壳摘要、调用表达式位置和符号参数；不导入被查模块、不调用其中API。源或快照变化会明确失败，不能自动生成新数字来维持“已完成”。因AST规范化，使用项目CPython3.10；其他解释器明确不予复核，不把AST差异当运行器回归。

```text
/opt/miniconda3/bin/python3 -I -B tools/tests/check_ctflab_platform_ownership.py
```

上述工具只证明已审快照与源码一致，不证明自动筛选器完整性、实际动态分派或原生兼容性。原始全量AST、inventory.py、review.py及中间修正保存在output/platform-ownership-20261030；重新盘点必须人工核对合同/替代路径和未验项，不直接照旧结果自动签字。

本轮以源码字节/参数/当前测试维护基线，实际结果在状态第136节和final-evidence.json补录。§135完整2101项属于上一轮证据，只在确认相关实现未变时引用，不冒充本轮重跑；本轮按影响核验当前源快照、负向漂移、相关合同测试及独立源码副本，不重打App或运行真实VM。A01源级交付与A02已证明的28组参数兼容可承接，A03、原生W任务、43项/G0/G1仍须各自证据。

最终结果：98项相关已有合同回归，97通过/1条件跳过（1.517秒），跳过为需显式指定无来宾QEMU夹具的用例，没有启动真实QEMU。源快照复核85模块/3731候选/60符号/4薄壳通过；6项自有临时副本负向检查全部拒绝源字节漂移、快照变更、虚假原生提升、假符号、错行和错责任接口。独立303文件/201 Python语法/86桌面运行时存在性及复核器/帮助入口通过，副本平台11项与参数对照2方法/28子例通过（0.030/0.043秒）；复制/执行期间源不变，总1.761秒。85模块与4薄壳确认为第135节测试输入的相同字节，未重复整套2101项、前端/Swift/Rust或Smoke。原始初稿、位置ID重复/目标名校正、辅助脚本语法失败均保留output，最终只用已复核版本。

## 第137节源码更新后的快照

上述22998调用/60符号及原JSON保留为第136节历史输入。第137节修改LocalService、本机适配、桌面/远程桥接后重新读取14根/85模块：23087个AST调用、3731平台候选、26同名绑定/14动态分派；新增账本读取、原请求查询和未知包装的5个真实定义，共65个符号。当前固定复核器指向`ctflab-platform-ownership-2026-10-30-r2.json`及其精确摘要，原JSON不覆盖。新读入口归入StateLock责任合同，已核对只读事务、身份/实例作用域与历史结果边界；异常后unknown并非原生兼容证明。生成/逐条绑定检查脚本留在output/contract-reopen-20261030，AST筛选仍为过近似。
