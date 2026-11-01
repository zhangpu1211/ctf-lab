# 异步worker执行审计增量（2026-10-25）

承接状态第89节，为已验证许可的受管远程worker补充执行阶段记录。没有连接SSH、启动真实VM、运行到期停机调度或安装服务。新增测试使用生产契约/代次协调器、实际临时SQLite和VM替身。[验证记录](verification-worker-audit-2026-10-25.md)区分代码与原生环境。

## 执行链

`ctflab_remote_leases.execute_job` 先按原逻辑核对私有许可、当前策略、主体/scope、实例根和契约请求摘要，然后进入 `ctflab_remote_audit.execute_audited`。若策略未启用audit，沿用原执行行为；启用后先提交worker意图，再取得资源门、校验租约/权限、登记当前worker身份并执行原LocalService。

worker意图在旧的at/summary之外增加可选execution字段：origin固定worker，operation_id取自已验证的服务端许可/契约，不接受请求自报。Runner请求层意图仍保留旧结构；客户端额外发送execution字段会被原严格契约拒绝，不能伪造worker来源。意图提交失败、满库、坏链或私有文件缺失时，不登记worker身份、不触及实际资源后端，原契约任务可仍处于pending，需显式核验，不自动重派。

执行返回后记录同一operation_id和可选contract摘要：state、result、cancelled、error_code均受既有契约枚举约束；无效值转为null，不记录错误消息、任意状态文本、路径、参数、证据内容或完整响应。必须与意图的operation_id和instance_uuid匹配，否则保留pending并返回持久化失败，不把错误响应关联为成功。异常只保留公开错误码与服务端绑定的operation_id。旧请求事件及其哈希/已保存检查点保持不变，校验器兼容旧事件和新worker扩展，不迁移或改写旧库。

## 结果含义与故障

- returned表示执行函数返回；contract.result=failed仍是失败，unknown仍是未知，不能把returned写成来宾操作成功。
- prepared/process-running/stopped等是原LocalService返回的状态。它们不证明课程服务、完整隔离或优雅关机，guest_effect_verified和graceful_stop_verified仍false。
- 取消与stop-timeout按原契约状态记录；本模块不取消新任务、重试关机、释放租约、停止VM或删除现场。
- 执行已完成而审计结果追加失败，审计保留pending，原契约终态仍可查询。事件追加与attempt完成在同一SQLite事务，失败一起回滚；不通过审计失败逆转已发生的VM动作。
- 显式再次调用已有operation可能只返回LocalService缓存结果，会新增一条独立worker观察记录，不重放资源动作；本轮没有新增自动重试/补记或调度。该记录不表示重新执行过来宾动作。

## 容量、运维与范围

沿用第89节可选audit配置/初始化/分页查询/检查点入口，不新建全局服务或默认开启审计。请求接收与worker执行是两次独立尝试，通常共四条事件，容量按两次计算；为已有意图预留结果空间的约束保持不变。请求层可能已返回accepted，但worker申请审计槽位时满库而拒绝执行，需查原operation；本轮不增加自动换库。满库也继续拒绝新远程stop/cancel，本机原正常停止入口仅由用户显式使用。

执行前许可/主体/根/请求摘要都合法的worker才进入本轮审计；坏帧、坏策略、未知主体、被撤销scope或错误许可可能在更早阶段拒绝而没有worker记录。这里不覆盖无leases的旧桌面worker、真实来宾内部事件或原生SSH认证失败。异步许可本身与当前策略摘要绑定，策略变更仍由原权限门拒绝实际动作。

哈希链仍只有本地一致性与可选历史检查点核对，没有外部可信锚/签名，不能独自抵抗同UID整库重写；全链扫描与容量/换库运营限制沿用前节。外部封存、pending的只读对账工具、坏帧/认证失败审计、桌面查询与换库流程、真实Linux/SSH并发/断线/磁盘故障尚未完成。R03与43项整体未完成；远程显示、D02跨网、来宾恢复、安装器/启动器、外部VM及真实课程仍沿台账，实机总验收尚未开始。

原Mac更新器保留；本轮只修改工作区及本地证据，不提交、推送、发布或覆盖旧包。
