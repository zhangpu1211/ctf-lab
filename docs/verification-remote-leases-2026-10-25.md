# 受管远程资源租约验证（2026-10-25）

> 历史验收快照：不替代当前软件状态或真实来宾/用户实机总验收。

仅工作区代码/替身验证，不是Linux/SSH/KVM原生验收、Windows Smoke或用户实机总验收。正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f62`。实现与配置见[开发说明](ctflab-remote-leases-2026-10-25.md)；证据根 `output/remote-leases-20261025`，无新ZIP或安装材料。

## 最终检查

| 入口 | 结果 | 证据 |
|---|---|---|
| 租约专项 | 23项通过；原生SQLite/文件、时钟和VM替身 | 最终远程合并日志包含全部23项 |
| `python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_remote*.py' -v` | 53项全部通过，3.068秒；原远程协议16项、上传14项、租约23项 | `remote-final.log` |
| 完整 `python3 -B -m unittest discover -s tools/tests -v` | 1234项，1213通过/21条件跳过，233.240秒；包含最终代码与23项租约用例 | `full-regression.log` |
| 显式白名单隔离源码 | 344项，336通过/8条件跳过，11.905秒；121文件逐个摘要、87个Python语法、11个独立 `-I -B --help` 入口通过 | `isolated-tests.log`、`isolated-evidence.json`、`check-isolated.py` |
| 工作区/进程收口 | 空白差异/白名单/摘要检查通过；原Mac更新两个文件无diff；无本机qemu-system/固定脚本日志接收器/租约worker | `diff-check.log`、`mac-update-preserved.diff`、`process-snapshot.json`、`final-evidence.json` |

没有前端/Rust变更，不重复构建；本轮不重跑原生Windows Smoke或无来宾QEMU专项。完整回归中的Windows smoke测试仅为无启动/文件边界单元用例，不执行WHPX实机实验；平台条件项保留跳过。本轮未使用用户VM、真实远程服务或宿主网络/Docker命令。

## 业务与故障边界

- 停机申请/续租幂等、历史ID不复活、磁盘只计一次且释放后保留；全池与个人配额拒绝不写契约或调用VM。
- 主体/owner/scope/服务器绑定；教师只可按已有scope使用owner预算，不能借自身额度或延长owner租约；目录重叠不能用父组件隐藏。
- 跨连接排他和非重入门；续租记录写入故障同时回滚期限与幂等记录；status/cancel不被长任务门堵住。
- 排队后租约到期、权限撤销、profile漂移拒绝资源动作；中途到期只保留已启动节点、不启动余下节点。取消能够到达现有协调器检查点。
- notify、boot变化/墙钟回拨不关机且保留额度；request-stop必须策略与申请双重确认，只提交一次原正常停止。超时、派发失败与意图提交中断不重发、不强杀、不自动释放。
- 所有节点停止且无未决记录后才释放CPU/内存；磁盘引用和现场始终保留。`graceful_stop_verified=false`，G0/G1未通过。

## 迭代与限制

初次运行测试时辅助方法名覆盖unittest的run，属于测试入口错误，未完成用例执行；原日志 `leases-first.log` 保留，改名后16项通过。扩展后22项通过（`leases-matrix.log`），远程合并52项通过（`remote-combined.log`）。首轮完整1233项有1项文档链接失败（验证文件尚未落盘），原日志保留；隔离343项通过。随后文档专项发现缺少项目规定的历史快照标识，补齐后复查。首轮完整/隔离加载22项租约用例，后续复核发现策略目录父组件可绕过词法重叠比较，改为规范化比较并增加第23项；最终完整与隔离均重新加载。早期日志以 `before-path-normalization` 标记，不冒充最终结果。补充最新guide白名单选项后隔离344项再次通过，最终121文件摘要与源码一致；之前的隔离结果另存before-guide-closure。文档补齐后的7项复查通过，最终完整回归也含该检查。

原生Linux普通用户worker/真实SSH/KVM、多租户高并发、实际时钟/重启与权限撤销、到期停止故障矩阵尚未验。周期调度器尚未开发部署，磁盘为逻辑预算而非硬限额；没有全主机强制资源控制、远程显示、桌面租约入口或数据通道。租约/续租历史不自动回收，仍需运维监控元数据容量。权限scope撤销后未知契约保留需管理恢复，不重派；全池单门在动作期间串行，长操作会阻塞其他租约申请/续租。实机总验收继续等完整开发收齐后集中开展，不把代码测试当作业务可用结论。

全部已有改动保留，原Mac更新器及其测试未改。没有停止现有VM、删除资产、连接真实SSH、安装系统服务、提交、推送、公开发布或重打/覆盖旧包；实际发行仍沿用前节，本轮不查询远端。
