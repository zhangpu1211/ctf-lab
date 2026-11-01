# 远程课程与审计管理入口（2026-10-27）

本轮为未打包工作区实现。Windows React桌面和Mac原生SwiftUI工作区均提供保存目标上的显式课程/审计管理入口；不是已发布App功能证明，也不代表43项、G0/G1或实机验收完成。证据目录：`output/course-admin-20261027`。

## 服务器课程登记

当前私有策略可选`courses`，最多64项。每项键是offer标识，字段严格为：`catalog`、`catalog_sha256`、`course_id`、`variant_id`、`profile`、`profile_sha256`、`source`、`instances`。catalog/profile为服务器私有绝对文件路径及当前SHA256，source为uploads已允许的签名索引源URL，instances为预分配实例UUID子集。客户端仅发送offer_id、instance_uuid与预览所得mapping_sha256，不能提交服务器路径、脚本或QEMU参数。

需当前未过期teacher/administrator权限、当前策略和offer范围；仍经过目录/许可/签名缓存/源索引/对象大小及摘要与运行时profile校验。当前远程映射沿用x86_64课程路径，不把该入口冒称Mac ARM课程的远程部署。

RPC：`course-list {}`、`course-preview {offer_id,instance_uuid}`、`course-provision {offer_id,instance_uuid,mapping_sha256}`。provision只配置实例、契约与引用，active_generation保持0；不准备派生磁盘，不启动来宾。当前配置使用的许可及元数据在操作时重核；变动需重新预览。CLI仍可显式preview/provision。

中断后使用原请求可在同一实例配置、profile、映射一致且尚未准备/派发时补齐缺失元数据；原有文件不同则拒绝，失败现场与引用保留。完成收据绑定根/账本文件身份、配置及profile摘要。完成后缺文件、替换根/账本、改变配置均拒绝收养；不会覆盖旧配置或自动清理。跨缓存引用、实例文件和策略的操作不构成一个原子事务，状态变化时可以拒绝并保留部分现场。

## 审计管理

私有策略可选`audit_management: true`，要求已有audit配置。仅当前未过期administrator、真实当前私有策略路径且策略语义一致时启用；旧策略/握手未声明能力则隐藏入口。

RPC：`audit-review {after,limit,checkpoint}`、`audit-settlement-preview {attempt_id}`、`audit-settle {attempt_id,review_sha256}`。分页limit为1至100，checkpoint为null或`{seq,sha256}`。读取返回未决记录、独立契约观察、链头及分页游标；跨库快照不原子，不是现场VM观测。

只有原worker绑定与现有契约终态、当前策略摘要、完整审计链头及观察均匹配的明确预览才能追加观察。原worker结果仍为unknown；vm_observed/guest_effect_verified/graceful_stop_verified/automatic_replay保持false。RPC追加resolution包含当前管理员principal，后续核验需支持此可选字段的本轮审计工具；既有无principal历史记录仍接受。原CLI严格一次settle行为保留，RPC以相同review摘要/策略/管理员显式重试可取回原收据。

获授权且结构完整的管理读取/预览/结清直接进入专用处理，不先追加普通请求审计，否则每次preview会自行改变链头而使settle永远过期。未授权/结构不符的请求仍进入常规拒绝审计。管理读取及有权限请求的语义失败不额外自写审计；结清本身有追加resolution与管理员归属。其他连接仍可能改变链头，遇到变化应重新读取和预览；不能强制结清。该入口不提供封存、换库、调度或来宾控制。

## 桌面与恢复

两套界面先明确连接保存目标，以角色/能力显示管理入口；先选择登记课程与分配实例再预览配置，先读取未决审计再预览终态观察，变更前单独确认。React管理页暂停实例overview/events/lease自动读取；Mac沿用显式读取。切换目标/实例废弃旧预览，迟到回复不能更新新上下文。后端每次仍重核固定目标、角色、能力、实例及摘要，不把UI门禁视为权限边界。

course-provision/audit-settle在ClientStore先记录意图后传输。响应丢失保留unknown，重开只读取，不自动发送。恢复原请求并确认重试时使用原本机attempt及原预览摘要；当前策略/链头不符仍拒绝。磁盘缓存收据只保留白名单字段，不保存服务器私有路径或原始观察输出。恢复记录不意味着自动准备、启动、停止或重放原worker操作。

## 验证边界

测试使用私有临时目录、真实SQLite/文件、虚拟QEMU/SSH，以及Swift核心与构建、前端模型/构建和独立白名单源码核验。没有运行真实SSH/课程来宾，没有重做Windows Smoke，没有运行真实到期调度、改动宿主网络/卷、停止用户VM或删除资产；未提交、推送、覆盖旧包或发布。原Mac更新器保持原内容。

集中验证结果和保留核对见状态第105节及`output/course-admin-20261027/final-evidence.json`。仍需开发的完整L3/UDP、更多网络成员、完整硬配额/总量、长时监管和原生拓扑编辑等不能转写为仅待测试；已知缺镜像/SSH/证书的课程/来宾/安装器/签名/实机验收另保留。
