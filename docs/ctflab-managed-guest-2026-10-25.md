# 受管来宾、图形草稿与内容镜像开发候选（2026-10-25）

本候选承接状态第83节，继续全部43项路线图。Windows Smoke基础用户实测结果沿用第82节，不要求重复。总验收尚未启动；本文件不是43项完成声明，不替代Windows、Linux来宾、干净机、跨设备和课堂验收。

## 桌面草稿

模板页提供节点、网段、网卡连线，支持拖动和键盘下拉框、新增/移除草稿节点、断开连接。图与完整清单往返保留硬件、许可、依赖和接口顺序；自动分配的地址明确是设计地址。断开最后一张网卡可形成待补全草稿。后台完整校验通过才允许导出；任何编辑或切换实验目录都会使校验失效，迟到的旧校验结果不能恢复导出权限。

图形校验与运行时能力分别判断。例如当前通用QEMU socket后端仍要求每网段恰好两个节点。有效草稿不代表运行时支持任意共享网段；导出后建立新实例，不热改已有实例。

## 专用Linux来宾通道

新增 `ctflab_guest_policy.py`、`ctflab_guest_channel.py`、`ctflab_guest_agent.py`、`ctflab_guest_kit.py`。QEMU profile可为指定节点增加 `agents` 声明，保持既有未启用profile兼容。每个代理声明含 `port`、`devices`、`flows`、`containers`、`container_cidr`。端口必须不与已有控制/显示/网段端口冲突；devices把清单网卡id映射为实际Linux设备名。

例如路由节点middle的定义结构如下，端口与设备名须由未来专用测试实例核对，不直接套用到用户已有VM：

```json
{
  "port": 46301,
  "devices": {"eth0": "ens3", "eth1": "ens4"},
  "flows": [{
    "source": {"node": "client", "interface": "eth0"},
    "destination": {"node": "server", "interface": "eth0"},
    "protocol": "tcp", "ports": [80], "reason": "课程指定HTTP检查"
  }],
  "containers": {}, "container_cidr": null
}
```

受管节点使用与实例/代次派生UUID匹配的QEMU DMI身份；宿主启动记录还绑定完整运行profile摘要。代理通过固定virtio串口通信，宿主侧只有回环双向TLS端点；没有来宾管理网络监听或任意命令接口。宿主先验证同一QEMU进程和QMP身份，再发固定操作。操作包含 `network-apply`、`services-start/stop`、`containers-prepare/start/stop` 和只读 `status/recover/operation-status`。桌面操作复用LocalService异步请求，不绕过代次/运行身份/并发保护。

代理只在Linux root、QEMU/Bochs、匹配DMI UUID且有root所有专用标记的来宾运行。固定工具须与安装时的摘要一致；检查已有默认路由、接口MAC/地址后才写配置。拒绝在Mac宿主、裸机或未知来宾执行。当前没有实际Linux测试来宾，所有原生执行仍未验证。

## 网络、DNS与时间

网络策略重新计算原v2计划并比对，拒绝未声明端点、公共出口、重复规则及任意命令。仅为明确的跨实验网IPv4源/目的、TCP/UDP端口或ICMP echo生成规则，返回流量要求连接状态；IPv6默认禁通。独立命名nft表默认拒绝input/output/forward，不清空全局规则、不做NAT。仅在专用来宾内配置接口、关闭IPv6及按顺序开转发；客户端和服务端仍须在各自来宾配置对应静态窄路由，本候选没有替其热改路由。

DNS只发布计划中的 `.ctflab.test` 静态记录，不使用宿主hosts/resolv或外部上游。时间服务为chronyd本地stratum10，`-x`不改系统时钟，不等于可信UTC或AD时间验收。固定systemd unit不自动重启、禁止超时SIGKILL；服务入口校验配置、unit内容和实际加载路径。返回服务运行状态不升级为网络、应用或课程健康通过。

配置后保存本次实际nft规则摘要，忽略计数器和内核句柄这些易变字段。后续服务/容器动作重新核验接口MAC/地址/掩码/UP、无默认路由、IPv4转发及IPv6禁用开关，并比对实际规则。重启后规则消失或被改写时拒绝继续，不沿用历史账本；同内容配置可保留，不覆盖被修改的文件。这是配置一致性检查，仍不等于应通/禁通实测。

## 容器候选与真实缺口

容器声明要求精确 `repo@sha256`、非root数字用户、CPU/内存限制、只读根文件系统、无capabilities、无宿主绑定目录/端口/特权。只使用专用来宾Docker Unix socket。网络限内部IPv4 bridge，卷是带实例/代次/策略标签的独立命名卷；所有资源使用前复核身份、标签和安全配置。日志使用Docker local驱动并限制4MiB×2。prepare创建但不启动；stop仅发一次显式SIGTERM并有界等待，不升级强杀，不删除卷、容器或网络。

**D01/D02/D03尚未完成。** 当前要求已预载本地digest镜像，离线OCI校验/装载没有实现。Docker internal网络没有默认出口，跨网容器端点明确拒绝；不能把生成nft allow当作三层网关完成。容器进度保存在运行盘内，宿主代次记录和来宾资源标签绑定；整课代次与真实容器卷恢复仍需进一步集成/实测。

宿主和来宾均在副作用前落持久意图，同operation_id不重复执行。配置成功之前的无副作用失败可重试新请求；已开始副作用的中断/异常保留unknown/pending并阻止新修改。recover和operation-status只读，不自动重放、回滚或清空失败现场。部分配置的完整对账/修复仍有开发工作。

## 专用来宾安装材料

宿主上只生成新目录，不安装、不改网络：

```text
python3 -B tools/ctflab_guest_kit.py <新的材料目录>
```

材料含固定代理源码、systemd unit、摘要清单和install.py，无镜像/运行时/密钥。未来仅在**新的专用Linux QEMU来宾**中，核验派生UUID及来源后显式运行 `python3 install.py --expected-vm <UUID>`。安装要求固定路径工具已存在且root所有；拒绝覆盖既有标记/状态/代码/unit，失败保留部分写入，不自动清理。启用agent.path供后续启动等待virtio设备，不当场启动网络、DNS、时间或容器。不要把安装脚本运行在用户现有VM或宿主。本轮没有执行安装。

## 纯学生镜像材料

`ctflab_mirror.py`从已有内容缓存构建可交给运维部署的静态材料，保留原签名索引及逐文件字节；索引必须非空、所有条目均student且明确允许再分发。混有教师材料或仅配方的签名索引在写出前拒绝，不能删掉条目继续使用旧签名。文件重验摘要并保护缓存引用，拒绝大小写/Windows保留名等路径碰撞。

下载入口 `ctflab_delivery.py --mirror <HTTPS根>` 仅在操作者明确指定时替换传输地址，信任根、源身份和索引签名保持原始来源；没有自动镜像发现、降级HTTP或绕过许可。镜像构建不访问网络、不启动服务。实际校内HTTPS部署、运营授权和轮换仍未完成；P04不是已交付运行服务。

## 本地交付与总验收

本地源码包使用新名称，不覆盖第83节或Windows历史包。源码包不含镜像、运行时、证书、私钥、用户运行现场或最终安装器。当前新增代码、界面测试和受控QEMU夹具的证据见同日独立验证记录及 `output/managed-guest-20261025`。浏览器使用合成实例和后台替身，未操作用户VM。

后续继续43项真实开发缺口：完整故障负向矩阵/证书续签/日志配额、安装迁移/更新协调、OCI/容器跨网、部分来宾效果对账、SSH/角色/租约/数据通道、外部Kali→Windows→AD接入、真实课程/隔离分析器等。缺镜像/SSH/签名证书已知，不重复索要；本地测试不能代替这些实现与最终集中实机验收。
