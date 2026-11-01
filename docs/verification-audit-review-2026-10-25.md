# 审计未决项只读核验验证（2026-10-25）

> 历史验收快照：不替代当前软件状态、真实Linux/SSH/VM或用户实机总验收。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f62`。[实现说明](ctflab-audit-review-2026-10-25.md)，证据根 `output/audit-review-20261025`，无新包。

| 检查 | 结果 | 证据 |
|---|---|---|
| 只读核验专项 | 15项全部通过，0.674秒 | review-final.log |
| 远程协议/上传/租约/请求审计 | 68项全部通过，4.450秒 | remote-final.log |
| 原worker审计专项 | 15项全部通过，0.578秒 | worker-final.log |
| 完整本地回归 | 1279项，1258通过/21条件跳过，232.608秒 | full-regression.log |
| 隔离源码/语法/独立入口 | 389项，381通过/8条件跳过，12.956秒；129文件摘要、92个Python语法、13个独立CLI入口通过 | isolated-tests.log、isolated-evidence.json |
| 文档、白名单、摘要保留、Mac更新器与进程 | 文档7项通过；白名单/最终源码摘要及空白差异通过；前轮126文件仅3个预定文件改变，其余摘要一致；原Mac更新器无diff；无本机QEMU/固定日志接收器/租约worker | docs-final.log、source-preservation.json、final-evidence.json |

首轮13项通过，补策略初次读取与实例绑定在查询期间变化后15项通过；当前无未解决失败。覆盖契约已完成但审计pending的只读关联、原排队/执行中状态、无绑定请求不猜测、撤销scope不打开实例、策略/profile/账本文件身份漂移、许可主体/请求摘要与响应错绑、原操作缺失/文件缺失不创建、分页/检查点与过滤已完成审计、坏链拒绝、只读事务直接写SQL被拒绝、查询中策略变化终止，以及独立CLI结果不含宿主路径。完成核验前后整个自有临时目录文件摘要与VM替身调用一致；原pending不结清、不追加result。

所有状态来自自有临时SQLite/文件，原契约/worker为真实生产代码调用，VM全部替身。没有使用用户实例、读取虚拟磁盘、连接真实SSH、操作QEMU、运行实际到期调度、改宿主网络或新增监听；不把contract-recorded当作VM观察。各数据库为独立快照，实例/策略前后核对不构成全局原子现场或恶意主机防护。

原生Linux/SSH并发/断线/热日志/磁盘故障、桌面只读报告、坏帧/认证失败、旧无leases worker、外部封存、换库和显式pending处理流程仍未完成或未验。G0/G1、graceful_stop_verified仍false，集中实机验收尚未开始。前端/Rust未改，不重复构建；不重做Windows实机Smoke或本轮无来宾QEMU专项，完整回归只保留既有不启动QEMU的Windows Smoke单元边界用例。

保留全部既有改动及原Mac更新器，未停止现有VM、运行到期停机调度、删除资产、提交、推送、发布或覆盖旧包；实际发行沿用状态历史，本轮不查远端。
