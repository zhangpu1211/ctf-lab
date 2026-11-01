# OCI、终端窄路由与网络对账验证（2026-10-25）

> 历史验收快照：仅记录本轮代码与夹具，不替代当前软件状态或真实来宾/实机总验收。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f62`。保留全部已有改动。实现/边界见[开发说明](ctflab-oci-routing-2026-10-25.md)，证据根 `output/oci-routing-20261025`。

最终来宾专项48项通过（含3项重连迟到回复边界），OCI静态/集成13项通过（含装载超时消息流），显式无来宾QEMU专项20项通过；较早未启用QEMU的driver预检查为19通过/1条件跳过。Docker、nft、ip和systemd均为替身或纯函数；没有在宿主执行Docker或在真实来宾配置网络。

首轮来宾对账专项45项有2项错误：逐操作UUID加入旧证明破坏同内容重配测试，测试插入位置使一段旧断言落入新用例。已改为独立逐操作证明、保留旧证明内容，并把旧断言归位，最终45项通过。原失败保留 `guest-reconcile-first.log`，修正结果为 `guest-reconcile-final.log`。最终结果见下表；前轮计数不代替最终加载。


## 最终集中代码检查

| 入口 | 结果 | 证据 |
|---|---|---|
| 完整 `python3 -B -m unittest discover -s tools/tests -v` | 1211项，1190通过/21条件跳过，246.858秒；包含所有最终模块与用例 | `full-regression.log` |
| 来宾策略/代理/通道/安装材料 | 48项全部通过；终端路由、拒绝/漂移、默认拒绝顺序、末尾对账、重连旧回复边界 | `guest-handshake-final.log` |
| OCI静态及代理集成 | 13项全部通过；USTAR/gzip/摘要链、畸形层/穿越/额度、镜像ID复核、未知结果不重放、超时后步骤可读 | `oci-complete.log`、`oci-timeout-final.log` |
| 显式无来宾QEMU | 20项全部通过，1.135秒；自有空白派生盘/暂停CPU/TCG/TLS参数及profile绑定，不启动课程来宾 | `qemu-fixture-final.log` |
| 隔离源码 | 321项，313通过/8条件跳过，10.980秒；117文件摘要、84个Python语法、10个 `-I --help` 入口通过 | `isolated-tests.log`、`isolated-evidence.json` |
| 专用来宾材料 | 临时生成16文件，逐个摘要/语法及独立agent入口通过；未执行安装，没有新持久材料包 | `isolated-evidence.json` |
| 工作区/资源 | 空白差异检查通过；原Mac更新两个文件无diff；无qemu-system/本轮固定脚本日志接收器 | `diff-check.log`、`mac-update-preserved.diff`、`process-snapshot.json` |

来宾/OCI专项使用真实临时SQLite/字节/文件，所有Docker/nft/ip/systemd均为替身，没有宿主Docker、真实来宾或服务效果。新策略完整profile绑定测试是合成身份/参数检查，无来宾QEMU测试不是WHPX/KVM/Windows设备验收。前端/Rust源码未修改，不重复构建并冒称新结果。

## 迭代、失败与边界

首轮OCI11项、来宾41项通过；加入对账后45项出现上述2个错误，修复后通过。首轮完整1207项通过（21跳过、235.932秒），隔离317项通过（8跳过），但未包含后来装载超时用例，保留 `full-before-timeout-matrix.log`、`isolated-before-timeout.log/json`。补上超时转换和代理消息流后，完整1208项通过（21跳过、243.619秒），隔离318项通过（8跳过），保留 `full-before-handshake-drain.log`、`isolated-before-handshake.log/json`。

随后考虑长操作迟到回复与重连握手错位，加入3项：仅configure可排空8条同绑定旧回复、外部绑定/过量拒绝、修改操作错配不接受也不重发。最终1211项及隔离321项重新完整加载；其他专项的旧计数不冒称包含这些新增用例。真实virtio长操作/断线重连、Docker daemon超时取消与部分配置修复均未验或未完成。

资源快照脚本首版遇到无关进程参数中的非UTF-8字节，解码失败且没有完成收口写入。改为容错解码并仅记录相关进程摘要后通过，没有输出无关命令行；不影响已完成测试结果。

原始镜像、用户VM与旧交付包没有操作或覆盖，未提交/推送/发布/重打已发布App。本轮只更新工作区和本地证据，无新交付ZIP；历史发行沿用状态记录，未查远端。G0/G1与graceful_stop_verified仍未通过/false，用户实机总验收尚未启动。剩余43项真实开发见状态第87节和台账末尾。
