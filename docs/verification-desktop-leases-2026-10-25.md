# 桌面远程租约管理验证（2026-10-25）

> 历史验收快照：不替代当前软件状态、真实SSH/原生桌面/VM或用户实机总验收。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f62`。实现见[开发说明](ctflab-desktop-leases-2026-10-25.md)，证据根 `output/desktop-leases-20261025`，没有新交付包。

| 检查 | 结果 | 证据 |
|---|---|---|
| 桌面租约合成链路 | 9项通过，0.265秒 | leases-final.log |
| 原桌面远程桥接 | 15项通过，0.153秒 | remote-desktop-final.log |
| 原远程协议/上传/租约/请求审计 | 68项通过，4.503秒 | remote-final.log |
| Node前端模型与生产构建 | 26项全部通过（新增5项租约模型），22模块生产构建通过 | frontend-final.log、frontend-build.log |
| 浏览器替身 | 停止策略未确认禁申请；申请一次，续期丢回复不自动重发；手动重试同renewal_id只延长一次；释放一次、stop为0；导出无连接路径/凭据 | browser-evidence.json |
| 完整Python回归 | 1303项，1282通过/21条件跳过，241.253秒 | full-regression.log |
| 隔离源码/语法/独立入口 | 413项，405通过/8条件跳过，14.071秒；137文件摘要、95个Python语法、14个独立CLI入口通过 | isolated-tests.log、isolated-evidence.json |
| 文档、源码保留及进程 | 文档7项通过；前轮135源码仅预定7文件变化，其余摘要一致；最终摘要/白名单/空白差异通过；原Mac更新器无diff；无本机QEMU/固定日志接收器/租约worker和18743夹具监听 | docs-final.log、source-preservation.json、final-evidence.json |

合成链路使用真实Runner/私有账本及契约、假SSH与VM替身：owner/上限/固定策略读取；申请、续期、原ID重试不重复延长、释放保留磁盘引用与源文件；提交后丢回复不重发；教师不借所有者权限；request-stop确认后推进假时钟仅查状态、不运行expiry或派发任务；TTL/UUID/额外宿主字段在传输前拒绝；运行中释放不stop/不释放额度；错绑续期回复保留未知，原标识再查不重复延长；旧notify确认不能授权新停止策略。

首轮9项合成链路通过；前端追加用例时目录路径首次有误，改用绝对文件路径完成追加。早期frontend-first仅21项，最终补5项租约模型后26项；不以早期结果冒充最终。原remote-first日志保留，最终重新加载受影响用例。当前无未解决测试失败。Rust入口未改，本轮不重跑编译或将旧0用例结果写成新验收。

浏览器运行于自有回环HTTP夹具，invoke为替身，不经过Rust/真实SSH或VM。导出通过Blob/锚点替身捕获，不写入用户下载目录。结束后浏览器回空白页，自有HTTP服务按UID/精确命令/cwd核验后停止；没有停止用户VM或删除资产。完整回归只含不启动QEMU的既有Windows Smoke单元边界，不重做Windows实机Smoke或本轮无来宾QEMU专项。

跟踪状态仅组件内存，离开前需用户显式保存未知原请求；无自动恢复或重发。真实SSH/原生IPC/用户交互、长期并发/断线/时钟/热日志/磁盘故障、完整配置与资产/课程流程、远程显示/窄通道/周期调度和硬额度仍缺。G0/G1、graceful_stop_verified仍false，集中实机验收尚未开始。全部改动与原Mac更新器保留，未提交、推送、发布、覆盖旧包或更新已发布App。
