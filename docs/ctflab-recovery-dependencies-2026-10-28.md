# 来宾准备恢复接入与Windows静态依赖核对（2026-10-28）

承接状态第112节，正式目录/分支/HEAD不变，399份开始文件摘要见`output/recovery-integration-20261028/baseline.json`。本轮不操作用户VM、真实来宾/Docker/SSH或宿主网络/卷/ACL，不重做Windows Smoke，不运行实际到期调度，不删除资产、提交推送、覆盖旧包或发布。原Mac更新器保留。下面的安装材料验证只使用临时合成PE/许可文本和新临时目录，不是重新打包交付软件。

## 从桌面到原准备操作

原先OCI续建仅能在专用来宾内执行命令行。本轮将`preparation-inspect`与`preparation-resume`接入受认证GuestClient、QEMU驱动、桌面契约/协调器及React、SwiftUI本地实验入口：

- 配置握手显式宣告两项恢复能力。旧代理仍可使用原有动作，但新恢复动作在发送前拒绝；不降级为shell、重新prepare或重发装载。
- 传输operation_id与待恢复target_operation_id分开。消息精确绑定当前instance/generation/policy，target必须为原containers-prepare；续建还须携带刚核对的resume_sha256。多余字段、错误UUID/摘要、陈旧快照/跨代次或策略变化拒绝。
- 宿主按新操作保留意图及回复，并绑定target/hash。相同操作再次查询返回既有结果，不重发；不能用同一个宿主标识换目标或摘要。丢回复后保留unknown，以新的只读核对确认原操作，不能推断无副作用。
- 桌面契约仍经过原CAS、工作/代次门、身份观测和取消门。整课进程未确认运行时不开放来宾恢复，须先用原“恢复核验”检查现场；不自动恢复VM生命周期或扩展远程租约协议。
- 来宾仍沿原锁/账本和第112节的续建规则，只续建未开始的步骤或登记已核对身份；未知load/create不重放，不删除或猜修丢失数据，不启动容器/服务。恢复目录及次数限制保持。
- 超过消息容量的快照返回明确unknown/response-too-large，不发送截断前缀；完整本地现场保留，可在专用来宾中核对，不把消息失败当作未执行。

桌面只列本次启动目录中最多16条原准备结果未确认记录；扫描4096意图有界，核验文件名/操作/当前plan摘要。它不探测来宾，不把原unknown当成现在仍pending。核对结果展示步骤状态，只有当前节点/原操作的有效快照才能开放“保留现场，继续准备”。续建需要显式确认；可创建缺少容器但保持停止，取消不派发。完成记录也绑定原操作，选择另一记录不能借用前一快照。刷新只读，不自动执行恢复。

验证：真实临时SQLite/JSONL消息与宿主意图，Docker/VM/TLS底层均为替身；集成10项覆盖保进度续建、传输幂等、旧代理拒绝、陈旧快照、丢回复与新核对、跨策略/代次、多余参数、超大消息、原记录展示、桌面契约CAS。初次历史助手遗漏guard导入由新增用例发现，修正后通过；失败日志integration-history-import-failure.log保留。早期集成44项含导入测试类被重复收集，已改为模块引用；最终10项单列，不混用计数。Mac接入脚本曾因工作目录错误未落地，修正后编译与模型验证，不把失败执行算作完成。

React/Swift续建参数真实Node→Swift逐值相同，错误原操作两端拒绝；Swift核心299项与类型检查通过。React48项/构建通过，真实浏览器程序化事件以替身IPC检查未核对禁用、目标绑定、取消不派发、原快照及CAS、续建后旧快照禁用；只产生2条夹具submit。没有操作Tauri原生IPC、Mac真实窗口、认证TLS、真实来宾或用户实例，不能据此声称端到端实机验收通过。

## Windows x64 PE静态依赖

新增`ctflab_pe_dependencies.py`，以及`ctflab_desktop_package.py inspect-imports`：只读取明确目录及相对入口/搜索目录，不执行二进制、加载DLL、扫描系统目录、读取PATH或注册表、下载或安装依赖。依据[Microsoft PE结构](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)解析x64 PE32+，覆盖普通导入、RVA格式延迟导入和导出转发；不兼容的架构/格式明确拒绝，不推断32位或旧VA语义。

文件256MiB、解析二进制2048个、目录/边/导出数量均有界；核验偏移、原始数据范围、RVA映射、重叠与终止符，拒绝绝对/相对目录形式的DLL名称、链接/硬链接和采集期间文件漂移。每个入口只在其父目录与显式声明的搜索目录解析依赖，大小写重名/多候选和本地系统库遮蔽拒绝。递归及循环有界，包含延迟和转发依赖，不因“暂时未加载”而省略。

固定Windows库和API-set仅标为`os-contract-unverified`部署声明，不读取系统来证明存在，未知API-set也不能据此宣称目标系统支持。按[Microsoft DLL搜索规则](https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-search-order)，实际搜索还受系统版本、SxS、已加载模块及运行时API影响；本工具只核对声明范围。动态LoadLibrary、插件发现/导出符号、全部PE合法性、API-set映射、安装许可/来源签名、实际加载/干净机均不由此证明。`native_dependency_closure_verified`、`dynamic_loads_verified`、`source_verified`、`signature_verified`始终为false。

独立入口示例：

```text
python3 tools/ctflab_pe_dependencies.py --root /explicit/runtime --entry qemu-system-x86_64.exe --search-dir .
python3 tools/ctflab_desktop_package.py inspect-imports --root /explicit/runtime --entry python.exe --search-dir DLLs
```

只能按实际选定目录执行；示例不代表本轮已检查真实Windows运行时。报告包含相对文件名、SHA、静态边、缺失/歧义及报告摘要；不执行文件且不创建输出文件。缺失/歧义返回非零，不删原件。

后续显式`stage --inspect-imports`可在复制前核对Python/QEMU目录中所有exe/dll/pyd/drv（含插件候选）；搜索范围为入口父目录、根及存在的DLLs目录。失败时不创建staging目录；通过后把报告及摘要绑定到新的临时材料清单，仍不把dependency_closure_verified改为true。默认旧stage兼容保留且报告未检查；旧交付物没有因此更新。

专项使用纯字节PE夹具9项、临时安装材料8项，覆盖三类依赖、递归循环、缺延迟库、显式搜索、重名/系统遮蔽、API-set未核验、恶意路径/架构/截断/VA格式/RVA/重叠、链接/漂移/数量限额与复制前拒绝。没有真实QEMU/Python Windows文件或原生加载验证。新模块及其依赖纳入两类运行时和独立源码白名单，没有对旧包执行stage。

## 仍未完成

本轮没有关闭全部遗留：Windows原生三层端点、子网/多跳/DNS/PMTU及整域集成，Mac CPU/内存强制限制、卷外/公共缓存/审计总量，更广未知/资源丢失与长期故障/匿名管道接管，真实C01—C07课程/分析镜像与规则，最终原生管理安装更新/原生依赖实际闭包，以及多平台实机/签名/干净机/课堂试点/完整G0负向仍开放。镜像/SSH/证书缺失已知，不重复索要。43项/G0/G1/graceful_stop_verified及集中实机总验收保持开放；不能把新增检查器或桌面入口写成整体已完成。

集中命令、最终通过/跳过数、源码保全和进程核验见状态第113节及`output/recovery-integration-20261028/final-evidence.json`。


最终集中证据：完整1756项（1735通过/21条件跳过，257.310秒），独立871项（863通过/8跳过，22.604秒）、246文件/169个Python语法/21个CLI帮助通过；最终源码一致。399份基线全在，原Mac更新器与HEAD一致，无本机相关夹具进程残留。未创建交付包、提交推送或发布；这些结果没有关闭上述其余开发与真实验收缺口。


## 第123节增量：运行时探测前后绑定暂存清单（2026-10-29）

`stage`结果新增`manifest_sha256`，调用方应在暂存目录以外独立保存。新增`verify --destination ... --manifest-sha256 ...`只读核对完整runtime文件集合、内容摘要、路径和普通独立文件身份；缺失、额外文件、链接/重解析点或摘要漂移均拒绝，不执行Windows载荷。不从当前目录重新计算摘要充当原有信任依据。

`probe`现在必须显式传入同一`--manifest-sha256`，Windows平台门后、执行前先核对，子进程结束后再次核对。仅运行固定随包Python的隔离导入检查，工作目录固定在已核对的Python目录、标准输入关闭；已有探测结果拒绝覆盖。返回内容须符合固定结构/版本，文件或清单变化时保留现场，不写成功结果。结果继续明确`signature_verified=false`与`dependency_closure_verified=false`。

此检查比较调用方选定载荷，不能赋予原本未验证的源码/二进制可信来源或签名，也不能锁死同一用户可写目录、消除原生加载时竞争或证明系统DLL闭包。本轮使用临时合成文件、注入Windows平台门和进程结果；实际隔离CLI只运行当前Mac上的本项目核对代码，不运行Windows exe、不制作新交付包。真实Windows导入、安装签名、离线WebView2、干净机和最终W05仍未验。专项及保全证据见状态第123节与`output/installer-probe-20261029/`。
