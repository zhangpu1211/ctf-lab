# Windows 可恢复运行候选（2026-10-23）

> 2026-10-24 工作区补充：通用后端与独立原生退出观测已接入源码，见[新说明](ctflab-production-driver-2026-10-24.md)。下文保持 10 月 23 日 r1 包的历史范围；该包未更新，Windows 原生验收仍未通过。

本入口为未发布的固定 Smoke 运行候选，不接管 control-r1。旧版本真实查询/正常关机证据仍见当前状态第79节；无需重做旧闭环。本候选尚未通过 Windows 实机恢复、显示、权限及来宾验收，G0/G1 不通过。

## 行为与边界

`tools/ctflab_windows_recovery.py` 提供 start、status、recover、display、powerdown。QEMU 自己持有回环 TLS QMP/VNC 监听和日志文件，独立客户端重新连接，无需依靠监督进程的匿名管道。运行仍固定 Windows x64/WHPX、已锁定摘要的 QEMU 与 Smoke 基盘、独立完整磁盘副本、无网卡；不接受任意运行参数、外部地址或资产路径。原盘只读核验。

每实例生成独立 CA、服务端和客户端证书，私钥仅写私有状态目录，不导入系统证书信任。证书有效期30天，不保存 CA 私钥，不支持运行中续签；过期连接失败且保留实例，不自动重启。TLS 服务端要求客户端证书及精确 DN，客户端核验 CA、服务器证书指纹、QMP 名称，以及 Windows 原生 PID/创建时间/映像路径。普通同账户恶意程序与管理员不在隔离边界内；持有客户端私钥者能直接访问完整 QMP，客户端命令白名单不是服务端沙箱。

显示只接受 RFB 3.8 + VeNCrypt X509None，认证由双向证书完成；不回退无认证或匿名 TLS。Raw 帧有大小/数量/时限约束，支持键鼠和手动重新连接，关闭显示不停止 QEMU；不传剪贴板或文件。Tk 窗口尚未人工验收，刷新效率、键盘布局和高分屏需补测。

关机先落盘意图再发送一次，确认回包也不等于已关机。响应丢失记 unknown；相同操作 ID 只读取原结果，存在旧意图时禁止另换 ID 重发。recover 只重新核验/查询，不重放命令、不重启、不强杀。监督进程在写入 binding 前死亡时拒绝自动接管；之后死亡原则上不影响 QEMU 自持的端点，但 Windows 原生故障恢复仍待实测。监督进程已死亡且随后 QEMU 退出时，不能补造退出码/来宾关机事件。

本候选有实际 QEMU 启动入口，但不是通用场景的生产 driver：尚未接入 ScenarioCoordinator 的多代次/多节点、网络执行或产品 GUI；未提供安装器、证书续签、日志配额/轮转、持续退出事件归档。不得称为生产后端全部完成。日志直接由 QEMU 写文件，仍需磁盘容量监测。

## 独立验收入口

在已有固定 Windows 环境中，先核验 QEMU 运行时清单与源盘。Python 需要 ssl、tkinter；仅准备证书需要本轮已测试的 `cryptography==46.0.5`，工具不会安装依赖。该版本限制是候选复现约束。不要使用旧实例目录；下面的目录必须尚不存在，端口必须空闲。端口冲突会保留启动失败现场，不自动更换或停止占用者。

```powershell
python -I -B tools/ctflab_windows_recovery.py start --run C:\CTFLab-Test\Smoke-OVA\w01-recovery-01 --inventory C:\CTFLab-Test\qemu-inventory.json --qmp-port 46101 --vnc-port 46102
python -I -B tools/ctflab_windows_recovery.py status --run C:\CTFLab-Test\Smoke-OVA\w01-recovery-01
python -I -B tools/ctflab_windows_recovery.py display --run C:\CTFLab-Test\Smoke-OVA\w01-recovery-01
python -I -B tools/ctflab_windows_recovery.py recover --run C:\CTFLab-Test\Smoke-OVA\w01-recovery-01
```

清单路径是示例，应使用实际文件；worker-created 仅指工作进程创建，不证明 QEMU 启动成功。失败检查私有目录中的 worker-console.log、qemu-stderr.log、start.intent.json、binding.json、result.json，保留目录。不要公开 tls 目录或原始包含私密路径的运行记录。

只有用户明确决定对该新测试实例正常关机时才执行 powerdown，操作 ID 必须用一个新的 UUID 并保留；unknown 时仅用原 ID 读取，不换 ID 重发。不在本次本机开发中执行 Windows 关机命令或监督器故障注入。

实机剩余矩阵：固定构建 TLS/VeNCrypt 支持、正常显示/登录/键鼠、显示关闭后重连、客户端退出后查询、监督器中断后控制与显示重连、不同普通账户拒绝访问、端口占用/错误证书/超时、关机响应丢失及磁盘不变核验。故障注入须使用另行明确授权的新测试实例，不能复用用户正在运行的实验。

## 实现依据

依据 [QEMU TLS 文档](https://www.qemu.org/docs/master/system/tls.html)、[QEMU 启动参数](https://www.qemu.org/docs/master/system/invocation.html)与 [RFB 协议](https://github.com/rfbproto/rfbproto/blob/master/rfbproto.rst)。公开文档证明协议设计依据，不替代固定 Windows 构建的能力验证。本机 QEMU 提示旧 `-mon` 语法弃用；保留该语法是为了兼容既有 Windows 构建，警告原样保留，不等于本轮功能失败。
