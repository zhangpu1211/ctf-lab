# A03原操作账本重开与未知响应（2026-10-30）

本轮发现并实际复现：LocalAdapter的submit已经提交prepare意图，但提交后的响应阶段发生OSError时，外层给出result=failed。数据库内原操作实际为accepted；这不能证明未发生副作用。原复现保留在output/contract-reopen-20261030/initial-boundary-gap.json。

现在本机存储异常、桌面桥接的非契约异常及远程传输异常返回result=unknown；非法输入和明确权限/能力拒绝保留failed。错误仍为固定public_error，不透出路径/后端异常文本；不自动重试、派发、取消或终止进程。核心执行中有明确失败响应时仍保留其业务语义，并不将所有failed改成unknown。

## 只读入口与恢复方式

LocalService.operation_history按认证actor和实例读取原operations账本，limit为1—50；每页给出原操作UUID、请求UUID、动作、预期代次、账本状态、是否有响应和取消请求标志，不返回请求参数或幂等键。使用SQLite只读事务；不初始化/迁移、不删除记录、不依赖可裁剪events。next_before是本页末尾操作UUID，后续页必须校验其actor及原请求实例；不向界面暴露大整数rowid。列表按账本rowid降序，未提供真实墙钟时间保证。

operation_result按原操作UUID读取同一账本响应，核验请求摘要/幂等绑定、实例、请求/操作UUID、协议和响应状态、结果/账本状态一致及公开错误结构。pending/executing/无响应的unknown只返回response=null；不根据当前实例状态伪造过去响应。已保存的prepared也可能属于旧代次；全部标记historical=true/current_runtime_verified=false/automatic_replay=false。取消标志只证明曾记录取消意图，不证明目标已经停止。请求参数已有可信输入校验，账本读取不新增任意路径或执行器选择。

本机CLI可在无后端的新进程中查询：

```text
/opt/miniconda3/bin/python3 -I -B tools/ctflab_local_adapter.py --root <已有契约私有目录> --history <实例UUID> --limit 20
/opt/miniconda3/bin/python3 -I -B tools/ctflab_local_adapter.py --root <已有契约私有目录> --history <实例UUID> --operation <原操作UUID>
```

桌面action固定为operation-history/operation-result，实例来自可信GenerationStore，主体来自当前普通本机进程；调用者不能传入actor/实例替换。React实验页增加“已保存操作（历史）”，用户明确点击读取、翻页和查看原响应；无自动加载或恢复动作，不依赖原窗口内存、localStorage或原请求体。切换实例/关闭后丢弃迟到响应，有界传输超时仍按未知提示。原“查询原请求”同时支持已持久化的cancel。未给远程SSH新增此历史接口，旧Mac Swift界面未接入此React组件。

## 验证与限制

新增15项临时真实SQLite/合成后端专项，包括丢回复后原意图仍在、跨进程-I CLI重新读取、后续代次/事件裁剪后的原响应、数据库字节不变、actor/实例/游标/坏参数拒绝、损坏绑定拒绝且不修复、最大SQLite rowid分页、取消查询，以及桥接不创建backend/不spawn。前端增加5项历史协议模型测试；构建包含新组件。首次专项发现常量未导入，修正后通过；所有阶段日志保留，最终统一结果见状态第137节及final-evidence.json。

原A01冻结JSON保持，第137节新r2快照重新读取85模块/4薄壳并增补5个真实符号；当前检查器固定r2摘要。没有把重新生成当原生兼容证明。

这里只证明源码、只读账本/受控失联和前端模型/构建。A03原判据中的GUI/CLI语义一致仍需完整入口对照；本轮仅补未知包装/历史读取，不追加Windows实机为A03独立源码工作的硬前置。长导入取消归W04进度/取消，真实GUI交互、Windows原生身份/持久化/IPC、持锁挂起恢复、旧匿名管道和Windows日志接收分别沿原任务核验，不将所有运行限制追加为A03硬门。43项、G0/G1及graceful_stop_verified不据此置为完成。没有真实VM/SSH/Docker/桌面控制、到期调度、宿主网络卷改动、用户资产删除、安装迁移、提交推送或打包发布。旧Mac更新器/App和失败材料保持。

最终集中验证：完整2116项（2095通过/21跳过，283.875秒）；独立副本1266项（1258通过/8跳过，41.987秒）、307文件/202 Python/86运行时/30帮助入口/r2源快照通过；前端60项及32模块构建通过。459份开始文件无缺失，14预期修改/445相同、新增4份，原更新器/旧App/历史平台JSON与旧课程ZIP均保持。没有原生窗口或真实来宾验收；两套测试执行会话已结束。最终摘要见output/contract-reopen-20261030/final-evidence.json。
