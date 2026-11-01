# 审计未决项只读核验（2026-10-25）

承接状态第90节，新增本机运维入口 `ctflab_audit_review.py`，关联审计worker意图与既有契约记录。它不补记/关闭审计，不重派任务，不取得VM资源门、不调用后端，也不查询或操作QEMU。当前只在临时SQLite/替身环境验证，[验证记录](verification-audit-review-2026-10-25.md)保留范围。

## 使用入口

```text
python3 -I -B tools/ctflab_audit_review.py --policy /绝对路径/policy.json --after-intent 0 --limit 100
```

沿用已有私有Runner策略、audit目录与服务用户，必须显式提供本机策略文件；不初始化或创建缺失库。可成对传入 `--checkpoint-seq N --checkpoint-sha256 SHA256` 核对已保存的审计前缀。每页最多100项，按意图序号分页，返回next_intent/more、完整pending_count和本次审计head。普通远程学生没有新增查询动作，结果不通过SSH自动发出。

## 关联与报告含义

审计全链/索引先在只读快照核验，只选择completed=0的意图；有结果的审计尝试不混入pending。旧请求层意图没有绑定operation_id，不按时间、主体或相近请求猜测关联。worker只使用已记录的服务端operation_id读取固定jobs许可，再按当前策略检查主体/scope/owner、服务器/实例/操作、原策略路径/摘要、实例根和代次账本文件身份、配置/profile摘要，以及契约本机actor、请求摘要、request_id/operation、响应绑定。

| observation | 含义 |
|---|---|
| contract-pending / contract-executing | 原契约账本仍标排队/执行中，且active操作匹配；不是进程或VM现场观察 |
| contract-recorded | 原契约已有绑定的completed/failed响应；只返回state/result/cancelled/公开错误码、代次与状态修订号 |
| not-linked | 请求层意图无服务端操作绑定，不猜测 |
| scope-unavailable | 当前主体/实例/scope/学生owner不允许关联，不打开实例 |
| binding-unavailable / policy-changed | 缺受管登记或原策略绑定已变，不沿用旧权限推断 |
| contract-missing | 在已核验实例/许可下没有原操作记录 |
| identity-conflict / unavailable | 绑定不符，或文件/数据库无法只读核验；不输出异常文本或宿主路径 |

策略读取前后、报告返回前均检查文件摘要；实例根/账本身份及配置/profile在契约读取前后再核对，遇到漂移拒绝关联或报告。审计与各契约是独立数据库快照，不构成全局原子快照；audit_head只对应审计读取时刻，pending随后可能已发生变化。`snapshots_atomic=false`，不能把这份报告当作当前VM状态。

## 保留现场与只读保证

审计查询事务现在使用SQLite mode=ro和query_only；实例代次元数据以及LocalService契约同样只读。缺文件不创建，SQLite需要恢复/无法读取时报告不可核验，不切换成读写、不运行恢复。原pending保持原样，即使观察到契约已有结果也不追加审计result或自动结清。读取文件范围限于已登记策略、审计、许可、配置/profile与契约，不读虚拟磁盘或来宾业务数据。

只输出白名单标识和状态，不导出许可内容、原请求/响应、载荷摘要、路径、PID、错误消息或凭据。contract-recorded、stopped或completed仍只是契约记录，不证明来宾业务、优雅关机或真实资源释放。`audit_modified`、`contract_modified`、`vm_observed`、`automatic_replay`、`guest_effect_verified`、`graceful_stop_verified`均false。

## 限制与剩余

策略、scope、profile或实例被替换后可能无法核验旧意图；不要为了关联而回改策略、覆盖文件或重用历史PID。请求层无操作绑定的意图、许可绑定前失败、坏帧/SSH认证、旧无leases桌面worker和真实来宾事件仍未完整覆盖。外部可信封存、只读报告的桌面展示、运维换库、审计pending的显式处理流程及真实Linux/SSH并发/断线/磁盘故障仍需开发或验收。本地链/可选检查点不抵抗同UID整库重写；权限/文件发生短暂变更再恢复也不构成可信主机防护。

远程显示、周期调度/硬额度、D02容器跨网、部分来宾恢复、最终安装器/启动器、外部VM与真实课程等继续沿台账。43项整体、G0/G1和集中实机验收尚未完成。本轮保留全部改动与原Mac更新器，没有新交付包、用户VM操作、实际到期调度、资产删除、提交、推送或发布。
