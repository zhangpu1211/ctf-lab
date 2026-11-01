# A03事件实值对照与游标恢复（2026-10-30）

本轮沿原A03“带版本/实例/代次/幂等键的命令与事件、结构化错误；不重复创建、unknown/failed/ready区分、GUI/CLI语义一致”判据继续核验。保持旧Mac运行/更新链、已发布App与所有用户资产，不把Windows实机缺失追加为A03独立源码工作的前置，也不以源码功能替代W01/W04/G0/G1验收。

## 实际缺口与修复

真实LocalService生成3条事件，独立-I桥接CLI原样返回数组，原React consumeEvents却按response.events读取，结果cursor=0/events=[]/reload=false。原错误保留为output/contract-parity-20261030/initial-event-gap.json；这不是仅凭文档推断。修复后按实际数组读取，未知对象形状不再默认为空。

前端事件校验与Python merge_events按同组数据对照：固定字段、协议/版本、UUID、整数边界、实例、代次、revision、阶段/状态、时间长度、同序号内容冲突、事件ID跨序号复用、连续序列与重复去重。旧事件也先核验结构；结果副本与输入分离，字段顺序不同的相同事件仍去重。Unicode时间长度按码点处理，与Python保持相同已有契约；没有擅自改为新的时间格式要求。

另修复裁剪后反复归零的问题：前端refreshEvents在缺口/拒绝时，只用刚读取且协议/实例绑定、游标为安全整数的状态快照定位下一页；无可信快照仍保持0并要求重新读取。清空旧时间线并提示历史缺口，随后只读后续新事件，不提交/领取/取消/重发操作。不伪造被裁剪的旧事件，原操作历史另由第137节账本读取。

## 原判据的当前证据

| 判据 | 直接对照及范围 |
|---|---|
| 版本、实例、代次、幂等键与严格字段 | 前端实际request函数构造status/prepare/start/stop/reset/recover/cancel/guest八类消息，由当前Python validate_request/fingerprint核验；坏版本/参数和幂等冲突按同入口对照 |
| 同一请求不重复创建 | CLI JSON和GUI类型化桥接指向同一真实临时库；pending重复只登记/派发一次，terminal重试保持原操作，换传输请求UUID仍命中原幂等摘要；后端仅执行一次 |
| 状态与错误区分 | 完整合成准备/启动/来宾/停止/重置/恢复/取消链；执行中读取unknown/recovery-required，明确失败保留failed，ready仅保留受信后端显式状态；公开错误字典对照。不是实际来宾或服务已ready |
| 事件与日志语义 | 真实桥接CLI字节到实际前端模型，修复后3条全部消费；90组共享输入，29接受/61拒绝，两端结果相同。所有已定义状态/阶段分别核对，不把进程状态提升为服务/课程完成 |
| 断流/裁剪恢复 | 本轮自有合成根真实裁剪，旧游标被CLI拒绝；绑定状态将0重定位到3，显式合成start后只读新3条到6，读取前后数据库摘要相同，没有自动重发 |

CLI的默认只读能力门、受信后端注入和GUI异步派发仍分别保留。对照的是相同已授权协议作用域的响应/持久结果，不把CLI默认只读改成可选任意后端，也不假称所有入口具有相同权限。Tauri固定桥接调用原样传递JSON，React使用本模型；本轮未操作原生窗口/IPC。旧Mac专用运行器也未强行迁移为新协议。

上述是共享本机v1命令/事件的直接源码与受控功能证据，修复了实际产品接入差异；尚未证明全部GUI/原生交付路径的最终完整语义。A03完整产品接入/其余未证范围保留，43项/G0/G1不关闭。长导入取消归W04，后台长期故障、Windows接收/原生存储/控制及正常关机按各原任务核验，不能把这些都变成A03新增硬门。

## 验证入口与保全

新增test_ctflab_contract_parity.py的7个方法，覆盖上述实际桥接数组、90组事件、八类构造、全部合成生命周期/取消、故障结果和过期游标实际续读。前端新增6个模型用例，原2个过弱事件夹具改为真实严格结构。合同专项96项通过，前端66项及32模块构建通过；最终副本结果见状态第138节末/final-evidence.json。首次命令使用了错误的输出相对路径，未执行npm；改到desktop目录后执行通过，没有将入口错误计为测试通过。

Python生产运行模块、Rust/Swift薄壳均未改；A01 r2固定快照仍复核85模块/4薄壳/65真实符号，原始两个JSON均保留。第137节完整2116项仅作为对应未改Python输入的历史证据，本轮不冒称重跑整个根目录。新增测试/说明进入显式白名单，独立副本验证依赖；没有创建交付ZIP/App/安装器、修改宿主网络卷/ACL、真实VM/SSH/Docker/调度/Smoke、桌面控制、用户资产删除、提交推送或发布。

证据：output/contract-parity-20261030下的actual-event-wire.json、initial-event-gap.json、event-parity-evidence.json/parity-cases.json、cursor-recovery-evidence.json、contracts-last.log、frontend-last.log/frontend-build-last.log、source-check-final.json以及独立副本/最终保全摘要。测试需要Node，缺失时明确skip，不将跳过视为跨语言通过；本轮Node实际已执行。

最终独立验证：1273项（1265通过/8条件跳过，47.324秒），309文件/203 Python语法/86运行时/30帮助/r2固定快照通过；7个跨语言方法实际执行，前端66项/32模块构建通过。463份开始文件无缺失，8预期修改/455相同、新增2份；251份非docs与副本一致，旧App/更新器/两个A01 JSON/四个旧课程ZIP保持。最终本机相关QEMU/CTFLabGUI进程名为空，测试会话均已结束，不推断其他服务/远端。根目录完整2116项仅为第137节历史，本轮未重跑；全部未关闭开发仍保留原范围。


## 2026-10-31 生产入口核对增补（A03继续开放）

本段是当前源码只读核对，不把旧合成对照扩展成全部GUI/CLI已通过。固定作用域为本地v1契约；传统Mac运行器、版本管理、课程配置、显示等独立动作另按自身合同核验，不能只因它们不接v1生命周期消息就认定旁路缺陷。

| 协议/操作 | CLI入口 | React入口 | Mac入口 | 当前共用后端/剩余 |
| --- | --- | --- | --- | --- |
| status | ctflab local-contract → LocalAdapter.dispatch；默认只读 | main.refresh → overview | sceneRequestGeneric(status) → overview | LocalService.status；overview额外含观测快照 |
| prepare/start/stop/reset/recover | 同上，CLI默认能力不执行副作用；受信宿主生产入口走desktop_bridge submit | main.operate → request → submit | sceneRequestGeneric → sceneSubmit → submit | LocalService＋GenerationStore/Coordinator；同权限作用域比较，不能移除CLI默认能力门 |
| cancel | 原operation_id参数，LocalAdapter | main.operate(cancel) | sceneRequestGeneric(cancel) | LocalService.cancel；原请求查询不自动取消 |
| guest | node/action及准备恢复参数，LocalAdapter | 节点动作 → request(guest) | sceneGuest/sceneGuestPreparation → sceneSubmit | 同v1严格参数与代次/CAS |
| query-request | desktop_bridge只读query-request（主local-contract JSON消息不提供该操作） | main.retry只读查询 | sceneQueryOriginal，内存sceneLastRequest | 共享已保存请求/响应；不重发 |
| 持久操作历史/结果 | ctflab_local_adapter.py与主ctflab local-contract均支持--history/--operation/--limit/--before | OperationHistory组件 → operation-history/operation-result | 未发现相应持久历史列表/结果重开UI，只有内存原请求 | **Mac实施缺口**：重开后应能只读查询历史，不依赖原窗口内存 |
| events | v1 events读取 | main.refresh → events(after)，refreshEvents核对/断流定位 | 未发现通用实例事件页读取/序号消费UI | **Mac实施缺口**：需接严格游标/绑定/过期恢复，不能拿前端90组结果替代Swift证据 |

Mac的`CliAction.genericClient`固定转入`generic-client`并将私有JSON经标准输入传递；`sceneGenericCall`拒绝过期ticket/context的迟到回复。它证明调用路由存在，不证明原生窗口实际操作或Mac消息构造与Python每个拒绝分支均已实测。下一实施切片应补Mac持久历史/事件读取和可测试构造器，再按同一消息夹具对照；A03、S01前置与G0/G1继续开放。


主CLI历史透传随后已补：`ctflab local-contract --root <私有根> --history <实例UUID> [--operation <原操作UUID> | --limit <数量> --before <上一页UUID>]`。新增真实子进程重开测试：对pending操作分别读取历史与原结果，前后SQLite字节相同，合成后端调用为0，不读取stdin、不派发。`PYTHONPATH=tools:tools/tests python3 -m unittest tools.tests.test_ctflab_operation_history tools.tests.test_ctflab_local_adapter tools.tests.test_ctflab_contract_parity`36项通过（2.877秒）；首次模块式执行缺测试目录搜索路径并有默认参数路由断言差异，保留日志，修正环境与默认路由兼容后通过。此补丁晚于R3完整2239项，仅上述受影响套件为补丁后证据。Mac历史/事件UI与完整A03仍未关闭。
