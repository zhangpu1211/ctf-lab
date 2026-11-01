# 外部Linux来宾点对点IPv4通道（2026-10-27）

本轮承接状态第108节，新增固定SSH通道内的点对点IPv4包转送、专用Linux来宾临时TUN端点、显式CLI与只生成不安装的材料。没有在宿主上执行TUN、ip、路由、服务安装或VM操作，没有连接真实SSH。它不是完整外部Kali→Windows→AD课程交付；Windows原生三层端点、子网转发、更多路由/DNS/MTU集成与真实隔离仍有缺口。

## 端点与授权

服务器私有配置可选`ip_tunnels`，以名称引用策略，`principals`显式授权名称。原TCP/UDP命名服务配置仍有效，两种名称不可重复。只有`kind=kali`可声明本轮三层策略；原Windows命名TCP/UDP通道保留，但不冒称支持Windows TUN。

```json
{
  "schema": 1,
  "local": "10.230.0.1",
  "peer": "10.230.0.2",
  "mtu": 1200,
  "flows": [
    {"initiator": "local", "protocol": "tcp", "ports": [80]},
    {"initiator": "local", "protocol": "udp", "ports": [53]},
    {"initiator": "local", "protocol": "icmp", "ports": []}
  ]
}
```

以上只是策略示例，不是已登记地址。另一端必须互换local/peer、反转每个initiator并保持MTU和流规则一致。地址必须是两个不同的RFC1918单地址；576—1500字节MTU；最多64条规则、每条最多32端口。不能声明任意目的地址/子网/默认路由，管理SSH、Docker API和VNC端口继续拒绝。UDP 53可传送到固定对端的DNS报文，但本轮不自动配置系统解析器或声称DNS服务存在。

NativeEndpoint只支持64位Linux root运行、具有受信虚拟机DMI身份且根所有标记匹配的专用来宾。`/etc/ctflab-external-ip.json`必须绑定machine/node/cohort/checkpoint/generation、允许的策略SHA、同目录全部Python源码的SHA和固定`/usr/sbin/ip`的SHA。源码、工具、标记及祖先路径的所有者/写权限/符号链接均检查；每次读写前重新核验。没有标记或平台不符，在打开TUN前拒绝。

## 临时接口与收口

接口名从本次channel UUID派生，不采用用户命令文字。打开`/dev/net/tun`时核对字符设备10:200和文件身份；使用完整64位ifreq、IFF_TUN/IFF_NO_PI/IFF_TUN_EXCL创建独占非持久接口，同名接口存在即拒绝。核对接口索引和当前网络命名空间；不接管现有接口。

在分配地址前检查现有地址/非默认路由，端点与已有直连网或具体路由重叠则拒绝。仅为本次接口添加本地/32与peer/32，禁用该接口自动生成IPv6地址，设置声明MTU并up。不添加NAT、转发或宿主默认路由，不清空路由表；已有默认出口不被本轮管理，也不据此宣称整台外部VM出口隔离。关闭自有FD由内核回收非持久接口及其对应路由，不发出删除其他接口的命令；配置失败也关闭自有FD。此行为依据[Linux TUN文档](https://docs.kernel.org/networking/tuntap.html)，**本轮尚未在真实Linux内核执行验证**。

## 包规则与故障语义

SSH请求必须继续携带原node/cohort/checkpoint/generation/challenge/channel_id，严格递增序号；一条请求只携带完整一包。只接受策略端点间IPv4，无IP选项、分片、IPv6或嵌套隧道；检查IP长度/校验和/TTL及TCP、UDP、ICMP echo结构和必要校验和。首次TCP要求SYN且无ACK，UDP按服务目的端口登记，ICMP只支持echo；未知回程拒绝。回程绑定地址方向、协议及端口/echo标识，每端最多256条流，空闲60秒过期。

每通道累计收发字节受`max_bytes`限制，最多4096次IP读写动作（空轮询也计数），连接数受原`max_channels`限制。超长、越权、漂移、错误序号、额度不足、部分写入或网络异常时关闭该会话所有自有通道；Circuit失败时关闭双端，不自动重连、重新创建端点或重复注入未知包。不会因此停止VM或改变原软件快照。poll次数限制可能先于CLI声明的最长运行时间耗尽，不能理解为保证持续一小时。60秒流空闲过期也可能使长期空闲TCP连接被拒绝，需要显式重建新会话。

IPv4和UDP字段核对参考[RFC 791](https://www.rfc-editor.org/rfc/rfc791)、[RFC 768](https://www.rfc-editor.org/rfc/rfc768)。这是一条受限点对点数据通道，不是完整透明IP网络；不支持ICMP错误/PMTU发现、片段重组、自动DNS、任意多跳/子网转发或Windows内核端点。

## 显式入口

`python3 -I -B tools/ctflab_external.py relay-ip --help`展示双方私有SSH配置、双方预期身份、双方已授权tunnel名称及duration/interval参数。执行该动作才连接；双方必须同cohort/代次、不同machine，策略互为镜像。中转方只经固定`ctflab-external-v1`传输，不在宿主打开TUN。SIGINT/SIGTERM请求在当前有界SSH请求结束后关闭自有会话，不保证立即返回；原SSH请求仍有自己的超时。SSH强制命令环境不能调用此出站客户端入口。

`python3 -I -B tools/ctflab_external.py materials-ip --help`仅生成全新私有目录，要求外部代理配置及目标来宾已独立核验的ip工具SHA。目录含固定源码运行时、逐文件摘要清单、根标记候选、代理配置和部署边界说明；已有目录拒绝，失败保留部分材料，不自动覆盖/清理。生成器自身及延迟依赖也收录，源码工作区和独立材料副本均可生成新目录。不会安装标记、创建SSH账户/密钥、启用服务或修改任何网络。Python/cryptography/ip/内核TUN等原生依赖不在材料中，工具SHA只是声明，生成时不把它当成目标工具已核验。部署到新专用来宾仍需对应环境和授权。

## 验证与未完成项

专项包含包/策略负向、状态回程、限额、双端代理与会话、真实自有进程管道、固定TUN调用替身、材料摘要/不覆盖及独立材料CLI。真实进程仅运行合成Python程序，NativeEndpoint的TUN/ioctl/ip全部为替身；没有真实SSH、Linux TUN、来宾服务或网络隔离验收。早期一次用例误写数据长度断言，修正为真实完整回复包后通过，初轮失败日志保留。

本轮完整与独立白名单核验、文件保全和进程收口见`docs/ctflab-current-status.md`第109节及`output/external-ip-20261027/final-evidence.json`。43项/G0/G1/正常关机与集中实机验收继续开放；剩余平台硬限额、长期监督、真实课程/分析镜像、最终安装更新及原生依赖闭包不是被本模块解决了。

取消补充：CLI停止事件在第一次SSH前、两次握手之间、创建端点前后逐步复核。第一端点打开后若收到停止请求，不再创建第二端点；已在途请求仍可能完成，随后只关闭本次自有SSH/TUN。两项专项覆盖预先取消零连接、第一端点后取消零第二次创建，不把这一行为当成真实SSH信号时延验收。
