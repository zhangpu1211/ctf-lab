# zcode 修复交付第二轮独立核验（2026-10-31）

> 历史验收快照：本记录只代表本轮现场，历史结果不替代当前软件状态。正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`，已有工作区改动全部保留。

结论：修复不是空报告，源码已有实质变化；但第150节“九项全部关闭”仍不能成立。真实助手的控制链仍不能完成接入，新增心跳与进程回收也有可复现错误。未做真实 Kali/Windows/VM 操作，不能认定可用、规划全部完成或双平台安装交付完成。

## 已确认有修补的部分

- TAP父分支 `recvmsg` 的第二参数已改整数，原 TypeError 已修；但描述符所有权仍有泄漏，见下。
- `external_relay_worker` 已从 `instance_plan` 派生非空节点 MAC；原生产空白名单已修。登记保存时的预览策略仍为空名单，与运行策略摘要不一致，后续需统一。
- SSH 强制命令已去 `%i`，安装说明改用 `/bin/sh`，新增 HELLO 和摘要/机器UUID比对。它们不代表整条握手已通过，见下。
- `kill` 抛异常路径现落 unknown，原无条件 disconnected 的具体复现已修；没有据此认可所有观测失败、竞态和撤网情况。
- shell 增加双向代理与按连接 fork；Mac 增加登记/连接/断开/材料按钮；前端和契约增加 Windows 路径判定。均为源码级确认，未实际点击或在 Kali 内交互验收。
- 来宾接收序号增加严格检查；宿主接收端仍未检查。SIGTERM 改用 Event，但 daemon 阻塞 accept 时退出唤醒/最终清理仍需验证。

## 本轮阻断与残留缺陷

| 级别 | 位置 | 已确认的问题、触发与影响 |
| --- | --- | --- |
| P1 | `tools/ctflab_kali_attach.py:532`；`:319`—`:326` | `attach_client` 在同一控制连接先 verify 再 attach；daemon 一次 recv/handle/reply 后就在 finally 关闭连接。执行生成后的真实 attach_client 与 handle_daemon，以真实 Unix socketpair 复现 `BrokenPipeError: [Errno 32] Broken pipe`。没有实际 TAP 或 root 依赖，属于代码阻断。并且身份应答先于 TAP 获取完成发送，宿主收到应答可提前落 connected。 |
| P1 | `tools/ctflab_external_attach.py:566` | 空闲心跳调用 `stream.send(RECORD_HEARTBEAT, 0)`，第二参数是整数payload而不是序号；编码器要求 bytes 且心跳载荷长度0。执行同一调用复现 ContractError。默认约10秒空闲触发退出；即使修正参数，当前15秒无业务流量超时与2小时可用会话目标也需明确协调。 |
| P1 | `tools/ctflab_kali_attach.py:299`—`:303` | SIGCHLD处理函数循环 waitpid(-1,WNOHANG)，没有在返回pid=0时退出。一个子进程退出而另一个shell等子进程仍存活时，处理函数持续自旋，阻塞主控制逻辑。执行生成脚本中同一函数，注入合法(0,0)返回，探针确认连续循环，主动在第4次终止探针，未运行真实daemon。全局回收还可能抢先回收 create_tap_in_ns 等待的子进程，需统一子进程所有权。 |
| P2 | `tools/ctflab_kali_attach.py:138` | SCM_RIGHTS接收已新分配一个FD，又os.dup返回新副本，原接收FD没有关闭。用真实socketpair和/dev/null，在调用者关闭返回FD后仍多出1个FD，已复现。原“描述符所有权修复”未完成；错误/截断附带描述符也需完整收口。 |
| P1 | `tools/ctflab_external_l2.py::RecordStream.receive` | 宿主只解码并返回序号，没有持久化/比较接收期望值。执行真实RecordStream，重复7/7均被接受；来宾身份应答序号0后，pump_frames输出也从0重启。需要定义并验证整会话双向序号，不能仅凭来宾read_record_checked测试宣称防重放完整。 |
| P1 | `tools/ctflab_desktop_bridge.py:419`；`tools/ctflab_kali_attach.py:704`；`gui/GuiApp.swift:3897` | 产品准备流程未闭环：connect即时随机生成新session并立即派发，但来宾要求管理员预先setup同一session。没有独立prepare/复用会话流程；Mac提示从材料manifest取setup参数，但materials的manifest只包含文件摘要、用户、协议，没有会话UUID、地址或setup参数。setup_command只有定义，没有接入该生产UI流程。不能依靠用户猜UUID、手改状态文件完成使用。 |
| P1 | `tools/ctflab_kali_attach.py::attach_client/handle_daemon/setup_session` | HELLO虽携带实例/代次/网段/策略摘要，来宾只验证会话存在/到期，丢弃上述绑定，未与管理员批准的grant比对；客户端只传session/challenge给daemon，机器UUID不可读还自动进入degraded-verified，缺少显式登记替代身份策略。新增字段不能直接等同于已实施绑定。 |

这些是本轮范围内发现的问题，不是穷尽审计。并发读改写、unknown重连、代次/计划变化撤网、背压以及真实内核行为仍不能判为通过。

## 本轮实际执行

1. 专项Python：
   `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tools.tests.test_ctflab_external_attach tools.tests.test_ctflab_external_l2 tools.tests.test_ctflab_kali_attach tools.tests.test_ctflab_kali_attach_functions tools.tests.test_ctflab_desktop_external_attach tools.tests.test_ctflab_external_attach_acceptance`
   结果69项通过，40.478秒。日志：`output/independent-review-20261031-r2/python-tests.log`。有unclosed socket警告。测试没有覆盖上述真实客户端/daemon组合，部分助手检查仍为脚本文本断言。
2. `cd desktop && npm test`：81项通过；日志 `output/independent-review-20261031-r2/frontend-tests.log`。
3. `/usr/bin/swiftc -typecheck gui/GuiCore.swift gui/GuiApp.swift`：退出0；日志 `output/independent-review-20261031-r2/swift-typecheck.log`。未实际点击、未重跑397项Swift检查。
4. 可重复独立探针：`PYTHONDONTWRITEBYTECODE=1 python3 output/independent-review-20261031-r2/reproduce.py`。该脚本复现真实助手断管、FD泄漏、SIGCHLD循环和宿主重复序号接受；补充心跳调用复现见同目录 `reproductions.txt`。只用本地进程内函数、Unix socketpair与/dev/null，不启动daemon、SSH、VM或创建真实TAP。无特权、不改变真实网络。
5. 候选材料核对：MANIFEST中26份源文件有2份文档摘要与当前文件不符（剩余矩阵、上一轮独立核验报告）；其余登记文件匹配。3份前端产物均匹配。日志 `candidate-check.txt`。这只是前端bundle和源码摘要材料，不是Mac App或Windows安装器。
6. 未重跑全仓2224项、没有新安装包构建或真实平台验收；第150节历史回归不能算本轮重跑。

## 规划与交付状态

状态第150节已明确A03完整入口对照、T02执行模板门、W05离线部分以及U04等仍有实施或决策缺口；矩阵仍列出大量平台/资产/人员门槛，G0/G1未通过。因此“其余规划已经全部完成”仍不成立。矩阵修订说明称已分列实施缺口，但主表中相关项仍多列为“证据缺口”，需逐项统一而非概括关闭。

本轮核验未搜索全部历史运行时资产，也未验证候选材料说明中的“缺打包输入”是否确实无法解决；不替该环境阻塞结论背书。没有Mac/Windows新安装包可供本轮安装验收。

本轮只新增核验记录/状态/精确白名单和本地证据；不修产品代码、不操作现有VM、不部署助手、不改真实网络、不删除资产、不提交推送或发布。下一步应先完成真实客户端→daemon→TAP准备→帧泵的受控集成测试与上述修复，再进行专用实机验收。
