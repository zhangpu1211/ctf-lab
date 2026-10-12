# Acfun 同网、闲置与恢复验收（2026-10-12）

> 历史验收快照；不替代当前软件状态。记录本轮实际执行、失败及修复，不将上轮证据冒充本轮重跑。

## 结果与边界

Acfun 在 1 GiB/1 vCPU 下完成 30 分钟闲置与三轮正常 ACPI 关机、再启动；独立 Kali 来宾终端访问其 SSH 22 返回真实协议标识。发现并修复长 SPICE socket 的启动登记/等待与显示重连两条遗漏。最终干净本地 App 通过真实冷启动、保持 PID/磁盘的重连、清单/许可证/严格签名和交付 ZIP 校验。

正式目录 `/Users/pufei/Downloads/ctf-lab`；分支 `codex/release-0.1.1-preview-20261010`；HEAD `42a3aa71d2665e20d9aec27f4afa19eed43a784d`，已有未提交改动保留。用户明确授权本轮独立 Kali/Acfun 同网、30分钟闲置、重复启动与桌面操作。没有操作用户既有 VM、接入物理 LAN、删除资产、提交/推送或发布。

证据根 `/Users/pufei/Downloads/ctflab-continuation-20261012`。最终入口是 `app-final/CTFLab.app`，不是中间 app-r4/app-r5 目录。已发布软件仍是镜像库 03-软件 的 0.1.1-preview。

## 真实同网、闲置和三轮恢复

| 验收 | 本轮实际结果 | 可复核证据 |
|---|---|---|
| Kali 来宾到 Acfun | 用户在已登录的独立 Kali 终端执行 `nc -w 5 192.168.242.32 22`；代理核对窗口与保存的 QMP 截图，返回 `SSH-2.0-OpenSSH_10.0` | kali-to-acfun-evidence.json、kali-to-acfun-terminal.png |
| 同实验交换机 | paired-state 中两节点实际端口23400，Kali租约 .10，Acfun租约 .32 | live-binding-review.json、idle-binding.json、runtime/探测记录 |
| Acfun闲置 | 1804.365秒，139次样本；实际样本首尾跨度1801.273秒，全部SSH返回正常、两节点QMP均运行，进程启动时间不变 | idle-observations.jsonl、idle-summary.json、idle-metrics.json |
| 正常关机 | 三轮旧进程退出，分别约6.48、12.21、11.41秒 | restart-evidence.json |
| 再启动恢复 | 使用R4包内QEMU、同一派生磁盘，DHCP/SSH约32.65、32.61、32.77秒恢复；每轮Kali原PID保持不变 | restart-evidence.json、acfun-restart-1/2/3.png |

采样间隔设置10秒，另含SSH查询耗时，实际约13秒一次；以JSONL时间戳为准。Acfun QEMU RSS最小54.64 MiB、最大101.56 MiB、中位91.22 MiB，首54.64、尾80.39 MiB；累计宿主CPU增加58.16秒，平均约3.23%。这是本轮闲置数据，没有匹配基线，不宣称配置带来因果性能提升或不存在长期泄漏。

Kali同期包含人工登录、打开终端与连通操作，因此不能把其139次资源样本称为全程无交互闲置。没有执行 Acfun 认证登录、挑战解题、持续负载、另一台Mac或睡眠恢复。显示控制工具的点击/快捷键及长文本输入未可靠落到来宾；用户手动登录、打开终端和执行短命令，代理独立复核画面。剪贴板保持关闭，未传递密码。

## 实际失败、修复和恢复

1. 首次启动恰逢独立 Kali 导入持锁，启动被拒绝；导入完成后重试成功，失败日志保留。App状态读取停在macOS open系统调用；用户允许下载文件夹访问后恢复，未开启完整磁盘访问。
2. 上轮包在本轮长状态目录启动 Kali SPICE 失败：QEMU已经使用短路径，但state.spice_endpoint和等待仍使用旧长路径；运行器清理本次Kali，Acfun继续运行。`kali-start.log` 保留原失败。
3. 新增无删除副作用的 `_spice_endpoint_path`，让准备QEMU、状态登记、等待连接使用同一端点。R4独立包在长目录真正启动到登录画面，display-ready=1、DHCP就绪；其额外实例使用2GiB/2vCPU和无宿主转发，交换机23401与配对状态23400隔离，只验证显示路径，不作性能比较。
4. 收口时已登录Kali的ACPI触发来宾关机确认，30秒超时后保留进程和磁盘。发现show_display仍使用旧长路径，重连失败；补为读取记录中的真实端点。源码实际恢复原窗口，QEMU PID/overlay不变。用户点击Shut Down正常关闭，再由CLI清理已退出状态。没有强杀。`owned-stop-evidence.json`、`kali-reconnect-source-r5.log`、`kali-human-shutdown-cleanup.log`保留失败和恢复。
5. 最终R5代码修复停止时对UNIX socket类型的清理。真实包冷启动和重连均显示登录界面；重连只替换显示客户端，保持QEMU PID、overlay、端点及共享权限。`r5-package-display-evidence.json`与最终干净包 `final-clean-package-evidence.json`、`clean-kali-cold/reconnected.png` 记录范围；没有要求第二次认证登录。
6. 外部验收脚本直接导入中间App Python模块，意外生成未登记pyc，App后验校验拒绝，失败日志保留。这是验收脚本副作用。最终从已生成的干净R5 ZIP解出App，恢复原始构建旁车；改用包内 `-B` CLI，外部只读QMP helper用源码与禁止字节码模式。最终App实测前后树摘要不变、无新增工具pyc，校验/严格签名通过。中间app-r4/app-r5目录保留追溯，不作为交付入口。

## 代码与自动检查

- `tools/ctflab.py`：统一长SPICE端点的生成、登记、启动等待和重连；停止时清理socket类型。维持并发锁、权限、只替换客户端的重连及正常关机失败保留。
- `tools/tests/test_ctflab_runtime_isolation.py`：新增真实UNIX监听在重复端点查询时仍可连接；重连实际短路径、PID/overlay/权限保持的回归。
- 最终完整回归：`/opt/miniconda3/bin/python3 -m unittest discover -s tools/tests -v`，651项，641通过、10条件跳过，205.724秒；full-regression-r5.log。中间650项640通过/10跳过，220.180秒，另存日志，不能混成最终计数。
- 运行时专项6项通过，3.431秒；runtime-tests-r5.log。矩阵显式E2E36项通过，7.858秒；matrix-tests.log。源码语法、git diff --check通过。
- 最终App与解压交付副本：805登记文件，内置Python3.12.15/PyYAML6.0.3，许可证完整，strict deep ad-hoc签名通过。无Developer ID、公证或跨Mac验收。

## 最终产物与完整性

最终ZIP `CTFLab-0.1.1-acfun-stability-20261012-final-local.zip`，SHA256 `409fe5834d8ae246c492885b910805acfc3925401665dd6b9e5ddc05ee4933ca`。包含app-final目录内的App、原始CTFLab.app.sha256及本地候选说明；交付副本解压后包内CLI校验/严格签名通过。

最终App树SHA256（排序的路径+文件hash列表，算法见final-audit.py）：`4ad94a0f8937b6dc0dce5b105a31e88f968c11eb66b97aed349cf1c78cacc340`。final-audit.json记录实测前后同摘要、代码与最终源码相同、没有生成工具pyc。

原始Acfun OVA SHA256仍为 `1e15d8b848b7d9bf33eeb2ad2543f12c240da93117199efe5cdb0d235f787fec`；Acfun分发基盘、原Kali/Smoke/Basic基盘及Kali固件共6项来源hash重新核对保持一致。三份本轮overlay的qemu-img check通过（只读检查，不修复）。source-integrity.json、final-audit.json与overlay-check日志保留。

## 收口与继续入口

本轮独立QEMU、交换机、显示客户端和主测试App已退出；GUI曾现场显示两节点已停止。保留paired-state和长r4-spice-long-state目录、所有overlay/NVRAM、备份、失败日志和截图。最终正常停止记录clean-kali-final-stop.log；失败关机未伪装成功，用户确认后才清理。

若继续，先读取AGENTS.md、本记录和current-status，核对Git与实际runtime/进程，再选择新目标。不要直接重复非幂等历史驱动：恢复验收驱动已加重复执行护栏；未执行的早期final-r4-kali-review草案已禁用。不能凭旧PID停止任何实例。源码与文档未提交、未推送；本地已打包，未发布/替换原软件。

新聊天交接语：继续CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先完整读AGENTS.md、docs/ctflab-current-status.md与docs/verification-acfun-continuation-2026-10-12.md，核验Git、产物和实际实例。保留未提交改动、原OVA、四镜像分发基盘和测试现场。最终本地包在ctflab-continuation-20261012/app-final，旧0.1.1-preview未替换；不要自动停止用户VM、删除资产、提交/推送/发布或直接重跑旧驱动。本次下一目标由新请求指定。
