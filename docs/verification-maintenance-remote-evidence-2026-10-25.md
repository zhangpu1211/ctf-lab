# 后台维护、更新、远程入口与证据封存验证（2026-10-25）

> 历史验收快照：本文件只记录本轮测试和范围，不替代当前软件状态或实机总验收。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f62`。保留已有改动；测试证据根 `output/maintenance-remote-20261025`。本轮没有Windows Smoke重测、SSH连接、用户VM操作或正式安装包构建。

实现与未完成项见[开发说明](ctflab-maintenance-remote-evidence-2026-10-25.md)。最终结果如下；不把本地代码结果当作实机总验收。


## 最终代码检查

| 检查 | 结果 | 证据 |
|---|---|---|
| 完整 `python3 -B -m unittest discover -s tools/tests -v` | 1162项，1141通过/21条件跳过，224.979秒，最终源代码全部加载 | `full-regression.log` |
| 日志/证书7项、更新协调10项、远程12项、证据5项 | 34项全部通过；真实临时SQLite/管道/POSIX脚本替身，非真实SSH或Windows | `log-cert-final.log`、`release-update-final2.log`、`remote-final2.log`、`export-first.log` |
| 原Mac更新 | 原源码/测试与本轮开始时一致，10项通过；CLI体验和文档专项通过 | `mac-update-restored.log`、`mac-update-preserved.diff`、`mac-cli-final.log`、`docs-final.log` |
| 隔离源码 | 272项，264通过/8条件跳过，9.629秒；109文件、78个Python语法及8个独立CLI入口通过 | `isolated-tests-complete.log`、`isolated-evidence-complete.json` |
| 显式无来宾QEMU专项 | 18项通过，0.752秒；自有空白派生磁盘、暂停CPU、TCG/TLS，不启动课程来宾 | `qemu-fixture.log` |
| React模型与生产构建 | 12项通过，前端生产构建通过；无新增Rust或原生GUI行为改动，不重复链接 | `frontend-tests.log`、`frontend-build.log` |

## 失败与修正

首轮完整回归1146项有2项失败：新更新模块命名覆盖了原先干净的Mac模块，造成旧CLI体验测试找不到status；新验证记录没有使用项目要求的精确快照声明。两个Mac文件已从本轮开始时的干净HEAD完整恢复，新功能改用release_update独立模块名；快照声明修正，原10项Mac测试与CLI体验通过。旧失败留在 `full-before-module-name-fix.log`，不覆盖。

首版隔离测试266项通过（8跳过），但源码材料生成器的 `-I --help` 缺固定模块目录而失败。修复独立入口后通过；日志与诊断保留 `isolated-before-fix.log/json`。随后增加实例锁跨版本事务提交的断言、父进程退出的实际管道测试、SSH传输错绑/超量/断线/超时测试，最终隔离272项及8入口通过。

中间完整回归1158项通过（21跳过，228.431秒），在追加最后4项传输故障用例前已加载，不作为最终完整覆盖；保留 `full-before-transport-coverage.log`。最后再次全量1162项通过，包含所有新增用例。测试没有真实SSH/KVM环境、Windows安装/更新、来宾应通禁通、Authenticode或课堂结果。

## 产物与现场

只更新工作区源码、文档、前端构建与本地验证证据，没有新发行ZIP、最终安装器、提交、推送或公开发布；旧App/Windows/源码包没有覆盖。当前Git分支/HEAD仍如上，保留全部既有改动。日志限额按运行尝试计算，历史总量不自动清理；文件系统停电持久性、真实Windows父进程故障和SSH部署仍未验。

最终名称快照无qemu-system或独立日志接收进程。未操作用户VM、宿主网络或真实SSH，无新增对外监听，不删除用户数据或旧现场。远端Windows状态未独立查询；G0/G1及graceful_stop_verified不升级。总目标仍有真实开发缺口，见开发说明和状态第85节。
