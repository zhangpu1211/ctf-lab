# 异步worker执行审计验证（2026-10-25）

> 历史验收快照：不替代当前软件状态、原生Linux/SSH/KVM或用户实机总验收。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f62`。实现见[开发说明](ctflab-worker-audit-2026-10-25.md)，证据根 `output/worker-audit-20261025`，无新交付包。

## 最终集中检查

| 入口 | 结果 | 证据 |
|---|---|---|
| worker专项 | 15项通过，0.561秒；真实契约/SQLite、VM替身 | worker-final.log |
| 远程既有协议/上传/租约/请求审计 | 68项全部通过，4.385秒 | remote-final.log |
| 完整本地回归 | 1264项，1243通过/21条件跳过，231.068秒 | full-regression.log |
| 隔离源码/语法/独立入口 | 374项，366通过/8条件跳过，12.073秒；126文件摘要、90个Python语法、12个独立CLI入口通过 | isolated-tests.log、isolated-evidence.json |
| 文档/摘要/白名单/Mac更新器/进程收口 | 文档7项通过；最终源码摘要/白名单及空白差异通过；原Mac更新器无diff；无本机QEMU/固定日志接收器/租约worker | docs-final.log、final-evidence.json、process-snapshot.json |

覆盖接收记录/worker记录分离和服务端操作绑定；动作前意图实际提交；准备完成、取消、正常停止超时、租约到期拒绝；满库/缺库/坏链不登记身份且不进入资源后端；结果写入失败保留契约终态和pending；结果事件/attempt事务回滚；缓存结果再次观察不重放动作；撤销scope在更早阶段拒绝且不伪造worker记录；旧事件字节/哈希/检查点不变；请求不能自报worker来源；异常只存公开码；任意终态文本脱敏、错绑操作/实例响应保留pending。

首轮12项有1项测试错误：取消请求把operation_id放在顶层，遗漏原契约的CAS/幂等/parameters字段。按既有契约修正后12项通过，再补停止超时、坏链拒绝和结果事务回滚，最终15项通过。原失败保留worker-first.log；远程68项预检查在最终生产逻辑下通过，最终日志不使用第89节的历史计数冒充重跑。当前无未解决失败。

所有VM/后端为替身，SQLite/文件/原有CLI为自有临时材料，没有实际SSH/来宾/宿主网络操作，不运行到期停机调度。无前端/Rust改动，不重复构建；不重做Windows实机Smoke或本轮无来宾QEMU专项，完整回归中的smoke仅为不启动QEMU的既有单元边界用例。

许可绑定前拒绝、坏帧/认证失败、旧无leases桌面worker和来宾内部事件不在本轮覆盖；外部可信锚、pending核验工具、查询桌面与运维换库仍缺。新增worker尝试额外占审计容量；接收后可能因满库拒绝执行，没有自动重派。returned/契约stopped不证明课程服务或优雅关机，G0/G1、graceful_stop_verified仍false，实机总验收尚未开始。

所有已有改动保留；未停止现有VM、运行实际到期停机调度、删除资产、提交、推送、发布、重打Mac App或覆盖旧Windows/源码包。原Mac更新器未改，实际发行沿用状态历史，本轮不查远端。

源码保留核对：第89节记录的124文件中只有预定的ctflab_integrated_kit.py、ctflab_remote_audit.py、ctflab_remote_leases.py改变，其余摘要一致；新增worker测试和说明已进入最终126文件白名单。证据为source-preservation.json，不将其扩大为原始镜像或远端状态验证。
