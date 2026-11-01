# zcode 交付独立核验（2026-10-31）

> 历史验收快照：本文为独立核验方留档，历史结果不替代当前软件状态；所列缺陷的逐项修复见状态第150节与本目录后续记录，原结论原文保留、不改写。

本记录是按日期归档的核验快照，历史结果不替代当前软件状态。正式目录 `/Users/pufei/Downloads/ctf-lab`；分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`。保留全部工作区改动。本轮是核验，不修改产品实现，不操作现有 VM、部署助手、改变真实网络、提交、打包或发布。

结论：新增协议、契约、回环中转、React 操作和测试确实存在，但“外部接入可实施项全部完成、只差实机”不成立；生产链仍有可直接确认的代码缺陷。项目其余规划也未全部关闭，剩余矩阵仍明确列出大量证据/条件缺口和 G0/G1 未通过。未对其余全部模块逐行审计，不能反向认定其实现都正确或都不存在。

## 需要先修复的实现问题

以下行号对应本次现场源码；后续修改后以函数名重新定位。

| 级别 | 位置 | 核验结果与影响 |
| --- | --- | --- |
| P1 | `tools/ctflab_kali_attach.py:136`，生成脚本 `create_tap_in_ns` | `recvmsg` 的第二参数传了列表，实际 API 要求整数。用生成脚本函数、真实 socketpair、仅替换 fork 返回值复现 `TypeError: 'list' object cannot be interpreted as an integer`。该异常不在 OSError 捕获内，无法完成 TAP 描述符交接；并非只缺实机证据。 |
| P1 | `tools/ctflab_desktop_bridge.py:259`，`external_relay_worker` | 生产中转调用 `policy_summary(attachment, [])`，没有从选定网段提取节点 MAC。按实际 FrameGate 复现合法 Kali→靶机 IPv4 与靶机→Kali ARP 都被拒；合成 E2E 则手工传了非空白名单，没有覆盖生产装配。 |
| P1 | `tools/ctflab_kali_attach.py:470`；`tools/ctflab_remote.py:306` | SSH 强制命令把 `%i` 当会话 UUID，但 ForceCommand 不提供这种会话替换；宿主也只发送固定命令名，没有传输会话选择握手。生成助手要求 `--session` 为 UUID，材料无法把宿主新建 session 对应到来宾 setup。安装说明创建账户时还使用 nologin，而 ForceCommand 经用户登录 shell 执行，部署路径同样需修正。 |
| P1 | `tools/ctflab_external_attach.py:335`、`:437`；`tools/ctflab_kali_attach.py:325` | 登记表校验了用户填写的 machine UUID、厂商、产品和助手摘要，但帧通道没有采集/比对实际来宾身份、助手摘要及实例/代次挑战的握手。现有 SSH 主机密钥校验仍有作用；五族字符串白名单不等于实际来宾身份验收。 |
| P1 | `tools/ctflab_desktop_bridge.py:267`、`:429` | SSH 和端点连接前便写 connected；disconnect 即使没有确认终止也无条件写 disconnected。替换进程观测为“存活”、令 kill 抛 OSError，实际仍返回 relay-detached、落 disconnected。不能据此认定通道已撤销，需 fail-closed/unknown 与端点收口证据。 |
| P1 | `tools/ctflab_kali_attach.py:398`，生成脚本 `client` 的 shell 分支 | 只从控制 socket 读取并输出，未把用户 stdin 转发给交互 shell；daemon 同步执行 shell 时还阻塞其控制请求循环。不能交付可操作的专用实验终端。 |
| P1 | `gui/GuiApp.swift:3751`，`MacExternalAttachCard` | 卡片只有文字、槽位与说明，外围只有“读取状态”。未找到原生卡片的登记、连接、断开、材料或终端操作。第148节“双端 UI 收口”超出实际实现。 |
| P1 | `desktop/src/external-attach-model.mjs:40`；`desktop/src/ExternalAttach.jsx` | 私钥和 SSH 配置路径按 startsWith('/') 门控。实际调用表单校验，合法 `C:\\Users\\student\\.ssh\\kali` 被拒；Windows 本地使用流程未完成。 |
| P2 | `tools/ctflab_kali_attach.py:201`、`:325` | SIGTERM 回调对 globals() 字典执行 setattr，实际复现 AttributeError；来宾 read_record 连续接受重复序号7/7。daemon 持有 TAP fd，客户端关闭自身副本不保证撤网，且未见周期租约回收循环。异常退出与重放防护仍需实现和验证。 |

SSH 判据已查阅 [OpenSSH sshd_config 官方文档](https://man.openbsd.org/sshd_config)：ForceCommand 经登录 shell 的 -c 执行，忽略客户端命令；TOKENS 段未将 ForceCommand 列为接受 `%i` 的配置项，`%i` 本身指证书 key ID，不能当 CTFLab 会话 UUID。

以上不是穷尽缺陷清单。尤其并发保存/连接、代次变化期间撤网、有界双向背压与长时运行仍需深入检查；本轮不对其作通过判定。

## 实际复核与测试

- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.tests.test_ctflab_external_attach tools.tests.test_ctflab_external_l2 tools.tests.test_ctflab_kali_attach tools.tests.test_ctflab_desktop_external_attach tools.tests.test_ctflab_external_attach_acceptance`：54项通过，37.643秒；出现一条 unclosed socket ResourceWarning。测试使用合成帧/回环/替身，不操作现有 VM。
- `cd desktop && npm test`：80项通过，日志 `output/independent-review-20261031/frontend-tests.log`。它是模型测试，不是实际 React/Windows 桌面操作验收。
- `/usr/bin/swiftc -typecheck gui/GuiCore.swift gui/GuiApp.swift`：退出0，日志 `output/independent-review-20261031/swift-typecheck.log`；没有重跑397项 Swift 检查，没有实际点击界面。
- 追加针对性复现：生成助手 TAP 父分支类型错误、生产空白名单拒绝合法帧、信号回调错误、重复序号接受、终止失败仍显示断开、Windows 路径被拒。记录 `output/independent-review-20261031/reproductions.txt`。均不需要特权，不 fork、不 setns、不创建 TAP，不操作真实进程。
- `git diff --check` 通过。没有重跑全仓2209项；状态第148节的完整回归仍为 zcode 当轮历史记录，本轮没有把它写成独立复跑证据。

## 其余规划与交付判定

`docs/ctflab-remaining-work-matrix-2026-10-30.md` 的“其余规划项”仍列出 Windows x64/WHPX、最终包与干净机、课堂、多节点/容器/域环境、真实 SSH/跨用户、课程资产、维护责任等未关闭项，并明确 G0/G1 未通过。矩阵结尾还说明其余条目在无新环境/授权期间不重复开工。这不支持“此前剩余规划也已全部完成”。部分缺口确实需要设备、合法资产或人员；不能把所有缺口一概解释为代码缺失，也不能据此宣称全部完成。

第146—148节均说明未重新打包；本轮也未构建新包。不能把新增工作区实现当作已发布 Mac App 或原 Windows 候选已包含的能力。

建议顺序：先修复上述生产与材料缺陷并补真实函数/生产装配回归；补齐双端操作和安装材料；再用指定专用 Kali 与测试靶场完成真实内核及平台验收；其余43项按原完成标准逐项关闭，区分实施与证据。实机部署与操作仍需对应授权。
