# Windows后台控制开发集成验证

> 历史验收快照，不替代当前软件状态。日期2026-10-23；以下严格区分合成、本机QEMU协议与Windows真实来宾。

## 本轮交付

前轮分散的QMP协议、管道、监督核心已接到 `tools/ctflab_windows_control.py` 的完整开发入口：start、status、powerdown、recover。新后台持有自有QEMU匿名管道，控制客户端通过当前普通用户私有ACL文件请求调用；无TCP监听、不扩展网络、不接受任意QEMU参数。固定Smoke派生副本，旧原盘/旧测试目录不覆盖。

启动前核验已回传的安装目录清单、固定QEMU/原盘哈希、WHP与可用空间；后台再次核验，先记录启动意图再产生副作用。进程身份绑定PID/创建时间/映像；控制请求带实例/代次/操作UUID，提交标记最后写，重复操作不重放。退出与原盘检查独立记录，源盘不可读为未知。原始人工Smoke成功结果仍保留，不把这次新控制链称为Windows已测。

开发工具仅进入Git白名单与独立验证源码包，未加入正式App运行时模块或更新历史发行包。构建器 `tools/ctflab_windows_control_kit.py` 固定文件白名单/时间、独占新包、逐文件MANIFEST；不包含用户清单、磁盘、运行时或凭据。

## 首轮失败及修复

第一轮完整流程13项中11通过、2失败：断线/畸形QMP虽在操作结果记unknown，但进程立即退出时实例failure.json遗漏。已让请求处理返回控制失败并统一进入失败留证路径。原始 `control-integration-first.log` 保留；修复后原13项通过。随后增加多实例、启动意图阻止重启、严格类型、ACL拒绝、日志写入失败继续排空与源盘不可读场景。

集成复核还修正：非Windows拒绝测试在Windows路径构造前退出；日志写失败/截断仍持续排空stderr；控制已关闭时写线程不发送尚未发送的队列请求；QMP空闲事件定期消费且报告丢弃数；进程已退出时control_available不再为true。目录元数据断电一致性未验收。

## 验证入口和证据

- 控制流程：`python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_windows_control*.py' -v`。包含真实自有Python子进程、控制客户端退出后再次查询、正常请求/退出、两个实例独立、超时/断线、禁止重放、部分请求、跨实例拒绝及打包隔离测试。
- 协议和传输：`python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_qmp*.py' -v`。
- 监督：`python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_process_supervisor.py' -v`。
- 完整回归：`env -u CTFLAB_DESKTOP_E2E -u CTFLAB_SPICE_TCP_E2E -u CTFLAB_BOOT_MATRIX_E2E -u CTFLAB_SPICE_AUTH_QEMU python3 -B -m unittest discover -s tools/tests -v`。真实来宾/桌面显式E2E未启用。
- 本机真实QEMU仅协议：自有QEMU以machine=none、TCG、nodefaults、display=none、无磁盘、无来宾、无网络设备、暂停配置启动；握手与query-status返回prelaunch成功。随后只终止并回收本轮自有无来宾QEMU，未操作用户实例。证据 `output/windows-v2-20261023/local-qemu-protocol.json`。此项不是WHPX或Windows控制验证。

所有本轮日志在 `output/windows-v2-20261023/`；最终数字与包哈希在当前状态第77节。失败日志不覆盖。

## 实际限制和剩余门槛

尚未Windows执行新入口，不能证明普通用户ACL控制通道、关闭终端不退出VM、后台身份观察、WHPX/QMP与SDL组合在该设备已通过。需要按[集中验收说明](ctflab-windows-control-acceptance-2026-10-23.md)一次完成并回传。

监督器本身异常退出后匿名管道不能重新接管；recover只核验报告，不提供自动恢复控制。SDL显示窗口不能重新创建。完整G0的监督恢复、显示重连、共存及网络矩阵仍缺；W03—W06和其余路线图不能借本轮包宣称完成。后续运行器/课程/容器/远程/社区工作按原依赖推进；本轮不是全部43项完成。

无提交、推送、正式发布或重打Mac App，历史发布沿用v0.1.2-preview.20261015（未核验远端）。正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f62`。保留全部原始镜像、既有改动与失败现场。本轮没有真实来宾运行状态根；受控测试子进程结束后核验，后续不能照旧PID操作。

## 最终结果

最终全量969项：954通过、15跳过，213.642秒，退出码0。15跳过保留原生Windows5项、显式真实QEMU/桌面5项、历史产物5项的边界。最终包隔离测试36项全部通过（5.611秒）；控制专项20项通过（其中包测试再次覆盖内部36项，数量不能相加作为独立测试总数）。源码最终摘要与交付逐项一致，汇总control-final-evidence.json。

统一包SHA-256：bd001ff0cc7c18a63370bfbdd64c499be26118c76bd3042f3d6f7bf23ae85242。全量会话、本轮Python夹具及无来宾QEMU均已回收，未操作其他既有进程。Windows新控制链仍待一次集中实测，完整43项/G0/G1未完成。
