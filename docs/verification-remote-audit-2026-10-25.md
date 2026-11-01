# 远程请求审计验证（2026-10-25）

> 历史验收快照：不替代当前软件状态、原生SSH/Linux或用户实机总验收。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f62`。实现见[开发说明](ctflab-remote-audit-2026-10-25.md)，证据根 `output/remote-audit-20261025`。无新包或原生服务安装。

## 集中检查

| 入口 | 结果 | 证据 |
|---|---|---|
| 审计专项 | 首轮14项通过；加入检查点后15项由远程合并加载 | audit-first.log、remote-final.log |
| 远程合并 | 68项全部通过，4.503秒 | remote-final.log |
| 完整本地回归 | 1249项，1228通过/21条件跳过，230.239秒 | full-regression.log |
| 隔离白名单源码/语法/独立入口 | 359项，351通过/8条件跳过，11.397秒；124文件摘要、89个Python语法、12个独立CLI入口通过 | isolated-tests.log、isolated-evidence.json |
| 文档、源码摘要、Mac更新器与进程收口 | 文档7项通过；源码摘要/白名单及空白差异通过，原Mac更新两个文件无diff；本机无QEMU/固定日志接收器/租约worker | docs-final.log、final-evidence.json、process-snapshot.json |

所有VM/dispatch均为替身，SQLite/文件/独立CLI是自有临时材料。覆盖先意图后调用、越权拒绝、无敏感原文、容量预留、重复请求独立attempt、意图失败无动作、结果失败保留pending、异常不存文本、跨连接写锁拒绝、坏链/删尾/坏索引拒绝、分页/主体与容量绑定、目录重叠/缺库/权限拒绝、CLI不覆盖和旧检查点可跨追加核对。没有SSH连接、用户VM操作、到期调度、宿主网络或监听变更。

首轮14项和最终远程合并均通过，当前无未解决测试失败。新说明/验证文件在完整检查前落盘，保留全部已有改动；不以第88节的历史测试数冒充本轮重跑。无前端/Rust变更，不重复构建；不重做Windows实机Smoke或无来宾QEMU专项。完整回归中的Windows smoke仅保留既有不启动QEMU的单元边界测试。

坏帧/主体构造前失败、worker和来宾终态、外部可信锚、查询桌面、换库运维、真实SSH/普通Linux并发和断线故障尚未完成或未验。容量满会拒绝新的远程stop/cancel，未自动绕过或停VM；无硬磁盘配额。哈希链证明本地一致性，不能抵抗同UID整库重写；提供历史可信检查点可核对相应前缀，未接外部锚。returned不等于操作成功，G0/G1、graceful_stop_verified及全项目实机验收仍未通过/开始。

未停止现有VM、运行到期停机调度、删除资产、提交、推送或发布。原Mac更新器保留；旧Windows/源码包与已发布Mac App未覆盖，实际发行沿用状态历史，本轮未查询远端。
