# 桌面远程目标验证（2026-10-25）

> 历史验收快照：不替代当前软件状态、真实SSH/原生桌面/VM或用户实机总验收。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f62`。实现见[开发说明](ctflab-desktop-remote-2026-10-25.md)，证据根 `output/desktop-remote-20261025`。本轮没有新交付包或真实SSH/用户VM操作。

| 检查 | 结果 | 证据 |
|---|---|---|
| 桌面远程Python桥接 | 15项通过，0.135秒；假SSH/真实Runner拒绝路径 | remote-desktop-final.log |
| Node前端模型 | 21项全部通过，0跳过（新增9项远程模型用例） | frontend-final.log |
| 前端生产构建 | 通过，22模块；不启动原生App | frontend-build.log |
| Rust检查/构建 | cargo check --locked、cargo test --locked通过；test为0例，只作为编译验证 | rust-check.log、rust-test.log |
| 格式 | 固定1.90缺rustfmt；已用现有stable rustfmt核对 | rust-format-first.log、rust-format-final.log、rust-format-stable.log |
| 浏览器替身 | 明确连接/选实例、一次启动、旧修订拒绝、断开后迟到节点不显示且无stop；新实例一次prepare/CAS为null且接收后禁重复 | browser-evidence.json、browser-fresh-evidence.json |
| 完整Python回归 | 1294项，1273通过/21条件跳过，226.989秒 | full-regression.log |
| 隔离源码/语法/独立入口 | 404项，396通过/8条件跳过，13.224秒；135文件摘要、94个Python语法、14个独立CLI入口通过 | isolated-tests.log、isolated-evidence.json |
| 文档、白名单、摘要保留及现场 | 文档7项通过；前轮129文件仅预定6文件改变，其余摘要一致；最终源码/白名单及空白差异通过；原Mac更新器无diff；本机无QEMU/固定日志接收器/租约worker及HTTP夹具监听 | docs-final.log、source-preservation.json、final-evidence.json |

首轮前端测试文件写入目录有误，脚本先报告缺文件；纠正到项目源码目录后20项通过，加入新实例null修订边界后最终21项通过。初版严格状态修订门在代码复核中发现会拒绝未准备实例，已限制为精确generation=0/unknown/null组合并补Python/Node/浏览器用例。Rust固定工具链缺格式组件，未安装；使用本机现有stable格式工具完成检查。上述早期日志保留，当前无未解决测试失败。

浏览器通过自有回环HTTP夹具和invoke替身验证，没有经Rust/SSH操作VM；关闭后已按本机UID、精确命令和cwd核对，停止自有临时HTTP服务，浏览器回到空白页。没有停止用户VM或改宿主实验网络。构建dist仅为本地开发产物，不是新发布App或Windows安装包。

Python覆盖配置/身份/主机密钥变化、动作与参数白名单、目标/内外实例/请求错绑、启用租约的显式要求、旧策略兼容、stop仍用普通契约、错状态修订、握手/list畸形、cursor类型、超时一次发送且关闭自有传输、真实Runner scope撤销，以及无真实SSH的独立CLI拒绝路径。前端验证未连接/忙碌/未知禁操作、租约门、禁guest/display、目标与代次/CAS、迟到修订和初次准备；不是完整组件并发矩阵或真实网络验收。

剩余包括真实普通Linux/SSH/KVM和Windows原生IPC/用户交互、配置向导/目标保存、资产/课程映射、租约管理UI、远程显示/窄通道、长期连接与故障矩阵。43项/G0/G1及集中实机验收尚未完成，graceful_stop_verified仍false。没有重做Windows实机Smoke；完整回归仅含既有不启动QEMU的Smoke单元边界用例。全部改动及原Mac更新器保留，未提交、推送、发布、覆盖旧包或删除资产。
