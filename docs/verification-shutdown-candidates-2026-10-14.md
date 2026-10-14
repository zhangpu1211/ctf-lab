# Kioptrix、Stapler 关机候选续验（2026-10-14）

本文件是历史验收快照，不替代当前软件状态；后续使用须现场复核工作区、候选包及实例状态。

正式项目目录 `/Users/pufei/Downloads/ctf-lab`；工作区分支 `codex/release-0.1.1-preview-20261010`，HEAD `941db31`，源码版本为未打包的 `0.1.2`。本轮没有操作用户已有实例、原始镜像、已发布 App 或外部网络；没有提交、推送或发布。

现场发现镜像库另有 `02-已处理/Kioptrix-关机候选-20261013` 和 `02-已处理/Stapler-慢关机候选-20261013`。两包均要求运行器 `>=0.1.2`，本轮 `python3 tools/ctflab.py dist verify --dir <包目录> --json` 均返回 `ok=true`。这两包并非第 25 节使用的旧候选包。

工作区关机实现已有 profile 的 `shutdown.method` 与 `shutdown.timeout_seconds`。本轮修复其作用范围：自定义等待仅用于 `stop --graceful`；普通 `stop` 继续使用全局短等待，再按既有流程回收。更新 CLI 帮助文字，生命周期回归加入“profile 配置 120 秒但普通停止仍短等待”的用例。`python3 -m unittest tools.tests.test_ctflab_lifecycle -q`：12 项通过；`python3 -m unittest discover -s tools/tests -q`：退出码 0；`git diff --check`：通过。完整回归输出有大量夹杂日志，本轮没有用其计数证明真实来宾行为。

独立证据根 `/Users/pufei/Downloads/ctflab-shutdown-20261014`。两包分别在新建 `kioptrix-state`、`stapler-state` 中用工作区 CLI 执行 `dist install --json`，结果 `ok=true` 且 `runner_satisfied=true`；然后各执行一次 `run` 与 `stop --graceful`。Kioptrix 启动 PID 28718 后通过配置的 Ctrl+Alt+Del 正常停止；Stapler 启动 PID 29140 后通过配置的 ACPI 正常停止。两次停止命令均退出 0、输出“已停止”，随后状态查询均为 `running=false`、`stale_pid=null`，原 PID 已不存在，测试状态没有 `run.json`。两台没有复用同一可写状态或用户实例。证据包含各自 `*-install.json`、`*-running.json`、`*-stop.log` 与 `*-after.json`；测试状态和派生盘保留，未清理。

本轮只验证真实 QEMU 的启动与正常停止路径，没有重新截图判定登录画面、检查网络服务、认证登录、重启、解题或长时稳定性。Kioptrix/Stapler 继续是候选包；工作区修复和本轮验收都不代表已发布 0.1.1 App 具备该能力。库根 SHA256SUMS 的一次命令因管道只保留末三行且未保留原命令退出码，本轮不宣称全库校验通过。原始输入哈希未在本轮重算；既有原件验收属于 10 月 13 日记录。

## 同日续验：第二次冷启动与黑白画面判定

复用上述两份独立测试状态，各自第二次 `run`，未改变基盘或 profile。Kioptrix 的 90 秒 `probe --keep-running` 得到 DHCP `.57` 与 `network_and_display_candidate`，但当时截图仍在 `Starting sendmail`，不能据此认为已到登录；继续观察后保存 `kioptrix-boot2-final.png`，人工确认 `kioptrix login:`。随后的 `stop --graceful` 再次成功。旧 Linux 冷启动明显慢于 90 秒窗口，探测终态与最终登录画面须分开陈述。

Stapler 第二次启动的首份 `probe --timeout 90 --keep-running` 报 `process_running_no_readiness`、退出码 1；同一报告已有 DHCP `.58`，OCR 为 `login_ready`，人工查看截图确实显示 `red login:`。根因是显示活动采样要求至少四种颜色，而该登录画面仅黑白两色（非黑采样比例 `0.002233`）。工作区将颜色门槛调整为两种，仍保留非黑像素比例 `0.002` 门槛；新增黑白 PPM 回归用例。对**同一运行实例**重跑探测得到 `network_and_display_candidate`、退出码 0，随后 `stop --graceful` 再次成功。原失败报告与修复后报告都保留在 `stapler-state/logs/probes/`，对应终端记录为 `stapler-boot2-probe.log`、`stapler-boot2-probe-fixed.log`。`python3 -m unittest tools.tests.test_ctflab_screen -q`：16 项通过。

这次续验没有重新探测 FTP、SSH、HTTP 协议，也没有认证登录或解题；2026-10-13 的服务结果仍只属于历史验收。两台测试实例在续验结束时均以正常停止返回，派生盘和探测截图保留。已发布 App 和原件未改。
