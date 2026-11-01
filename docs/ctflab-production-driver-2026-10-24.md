# 通用场景 QEMU 后端与 Windows 恢复验收（2026-10-24）

本轮提供可执行生产路径的工作区候选，尚未通过 Windows 产品验收，也未更新任何已发布 App。正式目录为 `/Users/pufei/Downloads/ctf-lab`。沿用 GenerationStore → ScenarioCoordinator → QemuDriver 接口；已有固定 Smoke 与 control-r1 目录不迁移、不复用。验证见 [本轮记录](verification-production-driver-2026-10-24.md)。

## 支持范围

- Windows x64/WHPX，场景 schema 2，多节点、多代次、BIOS、IDE/VirtIO 磁盘；不回退 TCG。当前拒绝 ARM、UEFI、SATA 与每网段不恰好两个节点的场景。
- 场景只能提供既有白名单硬件字段；宿主另行提供固定运行时清单、绝对路径和端口。启动前核验运行时目录清单、原盘摘要与运行盘自包含 QCOW2 格式，拒绝外部 backing/data 文件。
- 每网段两个节点，按启动顺序让先启动节点监听 `127.0.0.1`，后启动节点连接；无 user 网络、默认出口、桥接或宿主转发。来宾静态地址仍需提前配置。回环数据链路没有 TLS/跨用户认证，不能声称恶意同机用户不可接入，也没有实测来宾禁通矩阵。
- QMP/VNC 使用每次启动独立证书、双向 TLS 与实例名称核验；原生 PID、创建时间、映像路径、计划摘要及运行盘文件身份共同约束控制。支持显式显示重连，不重启节点。
- 代次内每次启动使用独立递增运行目录；原有运行盘、旧运行目录、失败副本保留。记录不完整、身份不符、退出证据缺失均拒绝重启/重置。正常停止只发送一次 ACPI 关机，超时不强杀、不自动重发。

## 独立退出观测

`ctflab_windows_native.Win32.retained` 以查询/等待权限打开并核验进程，持续保留同一个内核句柄；`wait_exit` 在对象已退出后才读取退出码。这样 PID 重用不会把退出记录关联到另一个进程，退出码 259 也不会误当成仍在运行。

新增独立 `observe-exit` 进程。成功持有句柄后写 `observer-ready.json`，退出后写 `observer-exit.json`，包含绑定身份、真实退出码和证据来源。通用启动等待该就绪记录与绑定一致；固定 Smoke 也启动该观测器，其 status/recover 可以读取匹配的持久退出记录。

该记录只证明内核对象退出，不证明来宾正常关机、服务健康或课堂可用。监督器和观测器都退出、绑定前崩溃、观测器尚未就绪、ACL/身份查询失败时仍可能无法恢复退出码；不能补造退出记录。证书续签、日志配额和安装器仍待实现。

## 通用场景入口

由可信宿主准备私有配置目录，配置文件须通过现有 Windows ACL 检查。场景 JSON 按 schema 2 编写，资产映射是逻辑资产 ID 到原始只读 QCOW2 路径的 JSON 对象。源盘必须自包含，不把课程文本中的路径直接当作宿主配置。

宿主 profile 示例（路径、端口和节点 ID 必须与实际环境/场景匹配；这不是已验证的本机配置）：

```json
{
  "binary": "C:\\CTFLab-Test\\qemu\\qemu-system-x86_64.exe",
  "inventory": "C:\\CTFLab-Test\\qemu-inventory.json",
  "nodes": {
    "server": {"qmp": 46201, "vnc": 46202},
    "client": {"qmp": 46203, "vnc": 46204}
  },
  "networks": {"lab": 46205}
}
```

运行时根必须同时具有清单覆盖的 `qemu-img.exe`、固件及依赖。先用既有 `ctflab_runtime_inventory.py` 生成并核验所选固定构建的清单；不能用本机 Mac 构建的结果替代 Windows 构建验证。

以下入口只用于本轮授权的新测试目录，先配置再复制代次；不会操作旧 Smoke/control-r1 目录：

```powershell
python -I -B tools/ctflab_qemu_driver.py init --run C:\CTFLab-Test\scenario-new --manifest C:\CTFLab-Test\private-config\scenario.json --assets C:\CTFLab-Test\private-config\assets.json --profile C:\CTFLab-Test\private-config\profile.json
python -I -B tools/ctflab_qemu_driver.py prepare --run C:\CTFLab-Test\scenario-new
python -I -B tools/ctflab_qemu_driver.py start --run C:\CTFLab-Test\scenario-new
python -I -B tools/ctflab_qemu_driver.py status --run C:\CTFLab-Test\scenario-new
python -I -B tools/ctflab_qemu_driver.py display --run C:\CTFLab-Test\scenario-new --node server
python -I -B tools/ctflab_qemu_driver.py recover --run C:\CTFLab-Test\scenario-new
```

`init` 仅新建存储及固定 profile，`prepare` 复制第一代盘。`start` 只报告进程/控制状态；`recover` 只观测，不重放。`stop`、`reset` 是显式操作，不能对用户已有实例自动执行。需要产品契约时以 `QemuDriver(store, profile)` 注入现有 ScenarioCoordinator，再通过 LocalService 的既有认证/幂等入口使用；本 CLI 不提供跨用户 IPC 服务。

## Windows 原生验收

第一步不启动 VM，仅执行 Windows 内核与短寿命 Python 子进程测试：

```powershell
python -B -m unittest discover -s tools/tests -p test_ctflab_windows_native.py -v
python -B -m unittest discover -s tools/tests -p test_ctflab_windows_exit_observer.py -v
```

新增原生用例会启动一个 Python 父进程、一个短寿命 Python 子进程和独立退出观测器；父进程在观测器持有句柄后自愿退出，子进程随后退出码为 7，检查独立观测器仍能持久记录相同身份和退出码。无 VM、无进程强杀。非 Windows 宿主明确跳过，不算原生通过。

第二步在新实例验证固定 Windows 构建的 TLS、WHPX、显示与恢复。必须记录以下证据，不用截图或进程存活替代来宾验收：

| 验收项 | 必要证据 | 本轮状态 |
|---|---|---|
| 原生持有句柄跨父进程退出 | 原生用例日志、相同身份、退出码 7 | 待 Windows 执行 |
| 新实例重连 | 相同代次/进程创建时间、QMP 查询成功、无新增启动意图 | 待验 |
| 监督器退出后的恢复 | 专用实例的监督器故障记录，observer-ready 与 binding 匹配；重连查询/显示；之后 observer-exit | 待验，不能自动对已有 VM 制造故障 |
| 显示与键鼠 | 真实来宾登录、窗口重连与键鼠操作记录 | 待验 |
| 来宾正常关机 | ACPI 单次意图/结果、实际来宾关机与匹配退出观测 | 待验 |
| 网络隔离 | 两来宾应通项与禁通项、宿主监听范围 | 待验 |
| 代次恢复 | 仅在确认停止后 reset；旧盘保留、新代次路径隔离 | 合成文件验证，原生待验 |
| 权限/故障拒绝 | ACL 拒绝、错误身份/证书、端口冲突、响应丢失 | 部分合成验证，原生待验 |

本轮未取得 Windows 主机连接信息。已有第79节正向闭环不要求重做；新验收不能冒用该历史结果。G0/G1 仍未通过。未创建发行包，也未启动/停止用户 VM。

## API 核对依据

退出观测按 [Microsoft WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject) 的对象已触发/超时语义判定，再按 [GetExitCodeProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getexitcodeprocess) 读取退出码。参数路径的逗号转义与启动参数参考 [QEMU Invocation](https://www.qemu.org/docs/master/system/invocation.html)。这些文档核对不替代 Windows 固定构建的实际验收。

## 2026-10-27：多成员回环网段执行增量（状态第108节）

通用QEMU后端不再把每个网段限制为两个节点。每个网段按原计划`start_order`选最先启动的成员作为中心；该成员内部建立独立QEMU hub，为每个其他成员建立一条回环TCP链路。不同网段使用不同hub；不修改宿主网卡、路由、防火墙或默认出口，不增加宿主常驻交换进程。命令语义依据[QEMU hubport和socket官方文档](https://www.qemu.org/docs/master/system/qemu-manpage.html)。中心退出会使该网段通信中断；既有逆序停止保证正常停止时中心最后退出，异常退出仍沿现有恢复规则，不能把其余进程存活当作网络健康。没有新增自动重启/管道接管。

双成员旧配置继续使用单个整数端口，命令保持原样。多成员配置的值为以**非中心节点ID**为键的显式端口表，恰好覆盖所有非中心成员；单成员/未使用网段使用空对象。所有链路端口与QMP、显示及代理端口共同校验整数范围和全局唯一性，不接受地址、任意QEMU参数或推测端口。示例：启动顺序为`server,middle,client`且三者同属`inner`时，`"networks":{"inner":{"middle":18002,"client":18003}}`；场景还有其他网段时仍须完整声明。依赖变化导致中心变化后须重新提供匹配配置，不能沿用旧运行绑定。

桌面课程导入已按每条链路分配候选端口，双成员格式保持兼容；探测结束释放自有探测socket，候选不代表启动时已预留。Mac通用实例、Linux/Windows与服务器已配置实例共用该驱动，已有App未更新；不把共享源码当成三个平台均已实机验证。启动记录仍绑定完整profile摘要及命令，映射变化拒绝重连旧启动。

同期外部固定SSH服务通道补充UDP：服务器私有`services`条目显式设置`protocol:udp`；客户端使用`ExternalSession.open(service, protocol='udp')`、`send_datagram`、`receive_datagram`。每个RPC保留一包，`None`表示超时，`b''`表示收到空包。只允许当前角色授权的固定来宾回环服务、原challenge/代次/检查点，不允许请求地址、默认路由、广播、多播或任意命令；TCP动作不能用于UDP，反向同样拒绝。累计收发字节沿每通道`max_bytes`限制，每通道最多4096次数据报动作（包括超时/空包），最大单包16384字节。读取多一字节识别超长包，超出大小或剩余额度直接关闭，不能返回截断前缀；平台自身更小的数据报限制仍可能拒绝。发送超时/部分发送/丢回复不重发。此处是命名UDP服务通道，**完整L3、DNS路由/MTU、外部Kali→Windows→AD及双向路由集成仍未完成**。

实现入口：`ctflab_qemu_driver.py`、`ctflab_desktop_bridge.py`、`ctflab_external.py`；验证和实际限制见状态第108节及`output/multimember-network-20261027`。本轮没有启动QEMU、连接SSH、操作外部VM或改宿主网络。UDP内核检查只使用自有回环socket和假来宾身份；[Python socket文档](https://docs.python.org/3/library/socket.html)说明接口具有平台差异，不能把Mac内核检查视为Windows/Linux原生验收。
