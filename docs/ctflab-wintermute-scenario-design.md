# Wintermute 双隔离网静态设计（2026-10-14）

本文件第 1—5 节是 Phase 5 的实现前设计历史快照，第 6 节记录清单校验与纯参数静态切片，第 7 节记录 DHCP 参数化与合成验证；不是可启动场景配置或实机验收记录。尚未接入场景编排或真实双网运行入口；Wintermute 仍为转换候选，不可据此交付为已适配靶场。

## 1. 依据、范围与差距

现场读取 `CTFLab-Library/01-待处理/wintermute-extract/Wintermute-Lab-Setup.txt`：Straylight 的两张网卡分别接 Network #1/#2；Neuromancer 只有 #2；Kali 只有 #1，原说明允许任选 NAT。本设计收紧为离线场景，不提供该可选 NAT。原说明要求先取得 Straylight 的控制再进入 Neuromancer；不由运行器提前打通两网。

两份 OVA 和证据目录 `ctflab-new-three-20261013/staging/` 下两个 Wintermute QCOW2 的路径现场存在；没有重算磁盘哈希、解包或启动。硬件、转换一致性和单机显示结论沿用 [历史镜像复核](verification-new-images-2026-10-13.md)，不是本轮重验。

当前实现差距（按源码静态核对）：

- `tools/ctflab.py` 的 `ensure_network` 为单实验网登记全部 profile 租约；`qemu_command` 网络段固定实验网卡加 user-net 管理网卡。场景不能复用默认管理网或全局租约。
- `tools/ctflab_network.py` 的 DHCP server IP、掩码、广播地址与分配池固定在现有网段；多开两个交换机并不自动成为两套正确的 DHCP。
- 启动路径对 Kali 默认开启 NAT；场景必须在参数生成层强制覆盖，GUI 与 CLI 都不能绕过。
- 现有运行目录按 profile 标识组织，停止和重置是节点级；尚无场景归属、跨节点事务或整场景重置。

本阶段只定义纯 QEMU 三节点拓扑、清单契约、管理面与生命周期。Docker、真实 LAN、远程协作、任意拓扑编辑和学生成绩不在本切片。Wintermute 只有一台内部靶机，可作为先导；不满足总体 Phase 5 所列“入口机 + 两台内部主机”的完整阶段门槛。

## 2. 拓扑与场景清单契约

```text
Kali [outer0] ── outer 二层交换机 ── [outer0] Straylight
                                               [inner0]
                                                   │
                                           inner 二层交换机
                                                   │
                                           [inner0] Neuromancer
```

两个交换机只提供独立二层域及 DHCP，无上联、跨网桥接、路由、网关或外部 DNS；不配置 macOS 路由、TAP 或系统转发。Straylight 双网卡不等于自动路由器，运行器不改来宾转发、路由或防火墙。需要核查来宾原始配置是否已产生跨网转发；若存在与原题隔离要求冲突的直通路径，验收失败并记录，不能隐瞒或自动补规则。

以下为拟议字段，不是当前 schema 2 内容包可安装的 manifest：

| 清单项 | 约束 |
|---|---|
| `schema` / `scenario_id` | 独立版本化场景 schema；Wintermute 稳定逻辑标识，不以名称判定资源归属 |
| `required_capabilities` | `scenario-v1`、`multi-nic`、`isolated-dhcp-v1`、`transactional-reset-v1`；旧运行器在导入/启动前明确拒绝，不降级成单网 |
| `assets` | 引用基盘哈希、来源、许可、节点 profile 与已验证硬件；不得包含任意 QEMU 参数、脚本、宿主路径或访问凭据 |
| `networks` | 恰好 `outer`、`inner`；独立 CIDR、DHCP server/pool、固定租约；`uplink=none`、gateway/DNS 为空；只登记本实例 NIC |
| `nodes` | 恰好 Kali、Straylight、Neuromancer；镜像引用、资源上限、固件/磁盘、排序 NIC 数组、健康检查与关机策略 |
| `interfaces` | Kali outer0；Straylight outer0 后 inner0；Neuromancer inner0。显式模型、PCI 顺序、MAC、网段引用；管理 NIC 数量为零 |
| `policy` | `internet=false`、`host_forwards=[]`、`guest_management_nic=false`；禁止外部监听和外部网络引用 |
| `lifecycle` | 网络先就绪，节点按下述顺序启动；每节点启动/关机截止时间、失败保留与重置备份规则 |
| `checks` | 分开登记启动、地址、服务和隔离检查；协议/端口以原题及后续实测确定，不把猜测写成已知服务 |

建议候选地址：outer `192.168.243.0/24`，DHCP server `.1`，Kali `.10`、Straylight `.20`；inner `192.168.244.0/24`，DHCP server `.1`，Straylight `.20`、Neuromancer `.30`。这些是运行器 DHCP 预约地址，不是原盘已验证地址；来宾仍使用 DHCP。启动前核对宿主路由、现有实验网及清单冲突，冲突则阻止或要求明确选取另一候选网段，不能自动修改用户网络。固定租约须排除 server、网络及广播地址；动态池与预约不重叠，默认仅接受登记 MAC 请求。

实例生成随机 UUID；MAC 由实例 UUID/节点/NIC 派生并做局部碰撞检查，同实例重启稳定，整场景重置保持。两个实例可以重复 CIDR，但交换机、端点与状态不可共用。Straylight 网卡模型/PCI 顺序以原 OVF 和来宾命名验证确定：随附说明第一卡 PRO/1000 T、第二卡 MT；不凭单机 E1000 成功推断双卡兼容。Kali 使用独立 overlay，不借用或接管用户运行中的 Kali。

清单校验拒绝未知字段、重复节点/NIC/MAC/IP、跨实例网络引用、循环依赖、超限资源、外部路径及管理面策略冲突；IPv6 不提供 RA、IPv6 路由或出口，链路本地通信也必须留在所属二层域。

## 3. 管理面限制与验证矩阵

管理控制通过每节点私有 QMP/SPICE UNIX socket 和磁盘状态完成，不通过来宾第三张 NIC。状态目录及短 socket 目录为当前用户私有 0700，端点归属绑定实例与启动代次。第一版不提供 SPICE TCP 回退、hostfwd、共享目录、文件传输和剪贴板；后续增加功能须单独定义边界。QMP 不代理任意外部输入。

交换机使用现有回环 TCP/监听 FD 交接模式，每实例每网独占端点，记录实际绑定端口。回环限制不能防同一用户本地程序注入以太帧；这是单用户教学隔离边界，不宣称抵御恶意宿主用户。端口预约、身份绑定与场景归属不构成密码学网络认证。

| 路径 | 初始状态期望 | 后续证据要求 |
|---|---|---|
| Kali ↔ Straylight outer | 二层、地址与已知服务可达 | 双向 ARP/协议响应，不能只看宿主监听 |
| Straylight inner ↔ Neuromancer | 二层与题目服务可达 | 授权独立探针/来宾观测，避免使用漏洞解题作为健康检查 |
| Kali ↔ Neuromancer | 禁止直接到达 | ARP/ICMP/TCP 与人为加内部路由后的直通负测；抓包解释失败原因 |
| outer DHCP ↔ inner | 禁止泄漏 | 两侧抓包、server ID、租约及广播均不混用 |
| 任意节点 → 公网/物理 LAN/宿主非场景服务 | 无运行器提供的出口 | 拒绝路径、来宾路由/网络参数检查及受控本地出口探针；外部探测另需范围授权 |
| 宿主 → 两靶机服务 | 无常驻映射或宿主网络接口 | 参数与监听检查；临时验收探针必须授权、登记并撤离 |
| 实例 A ↔ 实例 B / 现有单机实验网 | 禁止互通 | 同 CIDR 双实例正负测、MAC/租约/端口/状态不串用 |
| 学生取得 Straylight 后经其访问 Neuromancer | 符合原题跳转目标 | 后续独立题目验收；与初始直通负测分开，不由编排器预置隧道 |

“禁止”表示运行器不创建该路径，仍需真实网络验收。宿主能通过受控二层客户端参与网络，不能把“无 hostfwd”写成“宿主绝对不可访问”。不向公网或真实 LAN 发包来证明无出口；先用受控本地边界探针和配置证据。

## 4. 生命周期、所有权和恢复

拟议布局：`scenarios/<instance_uuid>/manifest.lock.json`（解析后清单和基盘引用）、`journal.jsonl`、`networks/<network_id>/`、`nodes/<node_id>/`、`generations/<generation>/`、`backups/<generation>/`。运行记录保存实例/节点/网段、代次、进程启动身份、端点、overlay 路径及实际参数摘要，不保存 ticket 或密码。目录均限制在经校验的状态根内，拒绝符号链接逃逸。

锁顺序固定为状态根资源分配锁 → 场景锁 → 排序后的节点锁；耗时健康等待不持全局资源锁。场景实例不按普通 profile 暴露可写运行目录，所有节点写操作先经过场景锁；单机 stop/reset 入口对所属节点明确拒绝或导向场景动作，不能绕过编排。无关场景可并行，冲突操作返回当前状态。

| 状态/操作 | 行为与失败处理 |
|---|---|
| `prepared` → `starting` | 先校验能力、来源、空间/资源及策略；创建独立 overlay/NVRAM，日志写入操作 ID；预约两端监听 FD，失败释放本次预约，不触碰外部占用端口 |
| 网络就绪 → 节点启动 | 验证两个交换机身份和 DHCP 配置，再 Neuromancer → Straylight → Kali；顺序用于可观测启动，不要求先解题或已有服务才启动其他节点 |
| `starting` → `running` | 所有 QMP/进程就绪、各 NIC 地址证据与已定义健康检查通过；显示/登录、题目可用及隔离验收另列等级，不由进程存活推断 |
| 部分失败 → `degraded` | 停止创建后续节点，保留已启动节点/网络/overlay 与错误，明示占用资源；仅回收未使用的本次预约。恢复重验所属资源，不能自动拉起重复进程 |
| 网络崩溃/节点退出 | 降为 `degraded`，记录受影响路径；不自动迁移到其他实验网或重启来宾。重连同交换机能力须先合成验证，首版可要求停止后重新启动 |
| `stopping` → `stopped` | Kali → Straylight → Neuromancer，逐节点发送其白名单关机动作；断开所属显示客户端，按节点截止时间确认真实退出；全部退出后才停两交换机 |
| 关机超时 → `stop-pending` | 保留存活节点及网络、绑定记录，显示已停止/待停止集合；不静默强制结束。允许继续等待或用户明确强制停止，不能以 ACPI 已发送宣称成功 |
| 崩溃重开 CLI/App | 读取 journal，复核进程启动身份、QMP、状态根和实际盘/端点；PID 复用或归属不明进入 `recovery-required`，禁止发送信号或删除资源 |
| 已停止 → 再启动 | 使用原 overlay/MAC 和新启动代次；重验端口、两网 DHCP、所属资源，绝不沿用旧 PID 发控制命令 |

初始候选超时为节点启动 180 秒、正常停止 120 秒，作为清单受限参数，待 Wintermute 实测校准；目前不能套用 Kioptrix/Stapler 的历史时延当作 Wintermute 依据。超时不是强制退出授权。事件包含操作 ID、代次、状态变化、退出原因和检查结果；日志不含凭据。

### 整场景重置

第一版只允许全部节点已停止且所有权明确时重置，不提供自动 stop 或 `reset --force`；局部单节点重置暂不支持，以免产生跨节点不同时间点的题目状态。

1. 持场景锁核对三节点/两网络全部停止、无并发写入、基盘引用有效及空间足够，写 `reset-preparing` journal。
2. 在新 generation 创建三份 overlay 和所需 NVRAM，检查 backing chain/来源哈希；旧 generation 完整保留。重置范围涵盖三节点运行盘、固件变量和两网租约/运行缓存，基盘、证据、历史备份不改变。
3. 校验新 generation 完整性，原子替换单一 active-generation 指针并写提交记录；实例 UUID、MAC、清单和候选地址保持。禁止逐节点切换活动盘。
4. 成功进入 `prepared`，旧代次作为可恢复备份登记，不自动删除，不自动启动。后续恢复备份也须整场景停止、逐盘核验并原子切换。
5. 提交前崩溃继续使用旧代次；提交后崩溃以指针和完整性记录恢复新代次。记录不一致则阻塞写操作，保存现场；不能把半重置标为完成。交换机状态及租约按新代次创建，旧 run.json 不可复制为活跃记录。

## 5. 实施切片与验收门槛

1. **清单与参数生成**：实现独立 schema/能力检查、实例命名空间、NIC 顺序、禁止管理 NIC/NAT/hostfwd；单元测试非法字段、策略绕过和单机场景兼容。不先接入 GUI。
2. **双网交换/DHCP**：参数化 subnet/server/broadcast/pool，限定实例租约及客户端，保持回环 FD 交接；合成测试两网广播不混、地址校验、端口竞争、同 CIDR 双实例隔离。
3. **编排与恢复**：故障注入覆盖第二网络失败、第二节点失败、并发 start/stop/reset、PID 复用、关机超时、reset 每个提交边界与 App 重开；检查无关实例和原盘未变。
4. **Wintermute 独立实机**：取得明确测试授权后新建三节点状态，核验 OVF/NIC/来宾地址、两轮冷启动/停止、显示或登录、服务、应通/禁通矩阵和整场景重置；来宾配置调整仅写派生盘并记录差异。不接管用户 Kali。
5. **内容交付**：实机跳转、完整题目与必要跨 Mac/GUI 验收后再定最低软件版本及分发等级；原件许可、校验和候选保留。打包/提交/发布各按当时授权执行。

本轮只完成静态设计和文档检查；上述实现、合成网络、真实来宾、GUI、跳转解题、重置恢复、跨 Mac 均未执行。下一阶段最小切片为第 1 项，并保持所有网络/VM 测试入口默认关闭；随后单独推进第 2 项，不直接制作 Wintermute 分发包。

## 6. 静态切片实现契约（2026-10-14）

`tools/ctflab_scenario.py` 已实现独立场景 schema 1 的 JSON 解析、严格校验、实例计划和纯 QEMU argv 生成；不接入当前单机 CLI、GUI、内容包或运行器。本节为第 30 节阶段契约，DHCP 的后续进展见第 7 节；编排和实机验收仍为后续设计。

调用入口：

- `parse_manifest(text, available_capabilities=...)` 拒绝重复 JSON 键、未知字段和非 JSON 常量；`validate_manifest` 校验字典并返回独立副本。
- `instance_plan(manifest, instance_uuid, available_capabilities=...)` 要求规范 UUID，生成 `scenarios/<uuid>` 命名空间，按 UUID/节点/NIC 派生稳定局部单播 MAC，检测本实例碰撞。清单 NIC 的 `mac` 使用 `derived`，或显式局部单播 MAC；显式 MAC 的跨实例不重复由未来资源分配器负责。
- `qemu_command(manifest, instance_uuid, node_id, generation=..., state_root=..., socket_root=..., network_ports=..., qemu_binary=..., firmware_code=..., available_capabilities=...)` 返回字符串列表，不读写文件、不探测固件、不预约端口、不创建 socket、不执行 QEMU。两个网络端点必须为不同的有效回环 TCP 端口；生成参数不证明端口已绑定或归属正确。

能力参数默认空，缺少任一必需能力即拒绝。`REQUIRED_CAPABILITIES` 是清单契约，不是现有 App 的支持能力声明；静态测试明确提供合成能力集合，不表示双网 DHCP 或事务重置已实现。

具体字段见源码 `_fields` 校验及 `tools/tests/test_ctflab_scenario.py` 的 `candidate()` 合成清单。清单只有逻辑资产引用，不接受宿主路径；资产字段为 `sha256/source/license/profile/hardware_verified`，验证标记是输入声明，模块不核验原盘哈希或硬件事实。节点硬件白名单为 x86_64 BIOS/UEFI + IDE/VirtIO、ARM64 UEFI + VirtIO；NIC 模型接受 `e1000`、`e1000-82544gc`、`e1000-82545em`、`virtio-net-pci`（ARM64 只接受 VirtIO）。双卡具体模型仍须后续原 OVF 与来宾命名实测确定。

网络限定互不重叠的 RFC1918 /24；DHCP pool 是两个地址组成的闭区间，固定 `leases` 的键为 `node_id/nic_id`。仅登记这四块网卡，租约不得与动态池/server/网络/广播重叠。本切片仅校验数据，不实现 DHCP。每节点 CPU 1–8、内存 256–8192 MiB，总 CPU ≤16、内存 ≤16384 MiB；NIC PCI slot 为 5–30 且按数组严格递增。生命周期固定启动/停止顺序，依赖须无环且与顺序一致，截止时间为 1–600 秒，失败策略 `preserve`、重置策略 `stopped-atomic-preserve`。四类 `checks` 当前必须为空数组，不接受猜测的服务或可执行脚本。

运行资源只能由可信调用方传入：overlay/NVRAM 固定在实例/代次/节点命名空间，QMP/SPICE 为实例/代次/节点 UNIX socket；路径拒绝逗号、控制字符和 `..`，socket 路径限制 103 字节。路径真实归属、符号链接逃逸、目录 0700、固件白名单及 QEMU 架构/SPICE 能力、端口预约、宿主路由冲突、原盘哈希与硬件对应关系，都须未来 prepare/启动入口核验；纯函数无文件访问，不能声称完成这些检查。

生成参数使用 `-nodefaults -net none`，仅创建声明的 NIC，无 user-net/NAT/hostfwd/TAP/bridge/来宾管理 NIC；SPICE 仅 UNIX，关闭剪贴板和 agent 文件传输，无共享目录或 agent 通道。本轮参数未交给真实 QEMU，因此参数兼容性、显示、双网隔离及题目可用均未实测。现有单机参数入口保持原行为。

## 7. 双网 DHCP 参数化与合成验证（2026-10-14）

`tools/ctflab_network.py` 新增不可变 `DHCPConfig`：每服务独立的 CIDR/server/pool/server MAC/登记策略，掩码与广播由 CIDR 计算。不下发默认网关、DNS，也不配置上联。单机无新参数时仍使用 `192.168.242.0/24`、server `.1`、动态池 `.100–.254`，并允许未登记客户端；旧静态预约可以位于池内，动态分配会排除。自定义配置限定 RFC1918 /16–/30，server、池端点、预约必须为有效主机地址，禁止重复预约与 server 冲突；场景登记模式还禁止预约与动态池重叠。

`network_server_specs(...)` 是场景模块的纯函数入口：使用清单与实例派生 NIC MAC，把逻辑租约转换为两份只包含所属网卡的 MAC→IP 表，派生独立 DHCP server MAC，并返回 `DHCPServer` 构造参数（不含 port/listener FD）。状态路径为 `scenarios/<uuid>/generations/<generation>/networks/<outer|inner>/network.json`。重启/重置代次改变状态路径，保持实例 MAC 与预约地址；调用方须重新创建空租约服务，不复制历史运行记录。默认能力检查沿用第 6 节；尚未声明 App 支持场景运行。

场景配置固定 `registered_only=True`。`DHCPServer.dhcp_response(frame)` 可在内存中处理 Discover/Request，仅更新本服务租约；未登记 MAC、以太源 MAC 与 chaddr 不一致、选择其他 server、请求错预约/错网段地址不响应，不产生租约。不 ACK 错地址，本切片尚未实现 NAK、DECLINE、RELEASE 或租约到期回收。动态分配限制在配置池内，优先采用可用请求地址，池耗尽返回无地址而不越界。对截断帧、IPv4 分片、relay 请求、错误 DHCP option 长度/重复 option 等返回无响应，避免异常击穿服务。服务循环调用同一处理函数生成响应。

网络脚本 CLI 新增 `--cidr`、`--server-ip`、`--pool-start`、`--pool-end`、`--server-mac`、`--registered-only` 和可选完整 `--instance-uuid/--network-id/--generation` 身份组合；身份组合要求登记模式。脚本仍只监听回环；继承 FD 检查 IPv4 TCP 类型和实际回环端点。本机对 `SO_ACCEPTCONN` 查询返回协议不可用，因此不依赖它；可信资源分配器必须交接已 listen 的 FD。实例身份字段只是记录，不是网络认证或所有权证明。

本轮合成证据见 `tools/tests/test_ctflab_scenario_dhcp.py`：两网 Discover/OFFER/Request/ACK 的 server ID、掩码、广播、源 MAC 和 IPv4 校验和；无 gateway/DNS；外来网卡、错地址、错 server、伪造源、异常帧负测；同 CIDR 双实例与不同网段的独立租约/学习表/状态路径；代次路径变化；动态池耗尽与旧单机预约兼容；模拟客户端执行真实服务循环路径，确认广播只交给服务自身的客户端且回复使用本服务配置。另用当前测试进程的临时回环监听器检验端口竞争、FD 交接和错误端点拒绝，测试退出前关闭全部 socket；不启动网络子进程或 VM。

上述隔离结果是内存/模拟服务合成验证，不是两个真实 QEMU 交换网络的抓包证据。未知源二层帧仍可在其已接入交换机内转发，登记 MAC 策略只限定 DHCP；不能据此声称抵御恶意宿主或来宾。两份服务配置不自动构成场景资源分配器：宿主路由冲突、真实端口预约与所有权绑定、私有目录及符号链接、网络就绪和恢复、GUI/CLI 场景启动入口仍待实现。不得据本轮生成可运行 Wintermute 分发包。

## 8. 网络资源准备与就绪合成故障切片（2026-10-14）

新增独立 `tools/ctflab_scenario_resources.py`，未接入 GUI/CLI 或 VM 生命周期。`prepare_network_resources` 先校验清单和调用方明确提供的当前宿主 IPv4 路由 CIDR 快照（默认路由除外，其余重叠即拒绝），再检查状态根及实例/代次/网络目录：拒绝路径组件符号链接，所属目录要求当前 UID、0700，不自动修正已有权限。资源锁要求普通单链接文件、当前 UID、0600，通过 `O_NOFOLLOW` 打开和非阻塞 flock 排斥竞争。既存 network.json（含断链）要求恢复核验，禁止覆盖。随后绑定并 listen 两个不同的回环随机 TCP 端点，FD 默认不继承；后续可信编排器须明确 pass_fds 交接，不能先关闭再绑定。

返回 `PreparedNetworks` 持有配置、监听 FD 和锁。准备中失败仅关闭本次 FD/锁，目录保留；`close` 幂等且仅释放本对象资源，不删除记录、磁盘或目录。当前为独立准备切片，锁持续持有至 close；尚未实现全局锁→场景锁交接，因此不能直接接长时间服务等待或声称已满足并发场景编排。路径检查也不是抵御同 UID 恶意并发替换目录的完整 dirfd 防护。

`wait_network_ready` 由调用方注入新鲜状态观察函数及可信进程启动身份检查函数，要求两网同时匹配实例 UUID、网段 ID、代次、回环端点、CIDR/server/MAC/掩码/广播/pool/登记策略/固定预约与所属存活进程。状态里的 PID 不是身份依据；调用方必须按实际启动对象/启动时间/参数核验，不可只检查 PID 存活。None 表示记录未出现；错误记录立即失败，缺一网到截止时间失败；不会因端口可连接或单网成功放行。失败保留部分现场与资源，不发信号或自动停进程。网络状态新增 server_mac/static_leases 供完整比对，旧记录不能满足新门槛。观察函数的新鲜度与进程核验由可信编排器负责，当前没有生产调用方。

合成测试覆盖真实回环端口竞争、第二监听器创建失败后的 FD 释放、锁竞争、路由冲突/缺失/非法、目录权限/链接、既有记录保留、错身份/代次/端点/配置/退出或身份失配、单网就绪超时及重试、真实 DHCPServer 状态写入输出。无网络服务子进程、VM 或用户状态访问。尚未实现基盘哈希/硬件/固件/空间核验、overlay/NVRAM 准备、socket 目录、跨实例显式 MAC 登记、宿主路由采集及锁交接、服务启动/恢复/停止/事务重置；本切片只是场景资源准备的网络部分，不能生成已适配 Wintermute 内容包。

### 8.1 资产准备、可信观察与锁交接补充（2026-10-14）

`prepare_scenario_resources` 是新的独立准备入口，不接 GUI/CLI、不启动网络服务或 VM。调用方显式绑定三个基盘路径以及每个 UEFI 节点的 code/vars 路径与 SHA-256；来源文本不当作磁盘路径。准备前只读核对哈希、普通单链接文件、路径组件无符号链接，并通过 `qemu-img info` 要求独立 QCOW2（无 backing/data-file）。固件哈希证明与调用方选定输入一致，不证明硬件适配、可信来源或授权许可。空间门槛为调用方给定且不小于 64 MiB 的准备余量加 NVRAM 大小，不预约文件系统空间，也不保证来宾长期写入容量。

入口复用双网 FD 预约，在全局资源锁下按固定顺序取得实例场景锁。检查全部节点/端点不存在及 UNIX socket 长度后，创建独立 overlay，核对 QCOW2/backing 格式和绝对基盘引用；复制私有 NVRAM，校验复制哈希，准备 0700 socket 目录。完成后重新核验全部来源资产/固件并重新采集路由，以独占创建、0600、flush/fsync 保存代次 `prepared.json`（规范清单、资产哈希/路径、固件绑定、运行目录及预约端口，状态为 `assets-prepared`）。它不是网络存活记录或运行成功证据，尚无恢复消费者和 active-generation 事务。任何失败保留已创建的目录/派生盘，仅关闭本次 FD/锁；现存节点现场不能覆盖，重试需后续恢复入口或另选代次。

完成准备后把 `PreparedNetworks.lock` 从全局锁切换为场景锁，再释放全局锁；全局锁不进入就绪等待。同一实例其他代次准备会在场景锁处拒绝；其他实例可取得全局锁。调用方应在操作期间持有准备对象，明确管理服务继承 FD 与对象关闭时机；`close` 不会停止已启动服务，其监听副本和存活状态必须由后续生命周期负责。独立 `prepare_network_resources` 仍保留原全局锁行为，仅供网络切片/合成调用，不可替代完整编排入口。

`collect_macos_routes` 只读执行固定 `/usr/sbin/netstat -rn -f inet`，解析缩写 IPv4/CIDR、主机路由及 VPN 路由；未知格式、无表头/空表均拒绝。`fresh_routes` 要求采集时间在本次调用的单调时钟窗口内且不超过 2 秒，未来/过期/非有限值拒绝。准备前与结束前各采集一次；采集后宿主仍可能改变路由，不能据此宣称持续隔离，后续启动/恢复须重验。

`OwnedNetworkProcesses` 仅绑定可信编排器实际取得的启动对象与明确 argv，每个网段只绑定一次；就绪时要求匹配 PID、argv 且启动对象 `poll()` 未退出。状态文件 PID 不能自行取得控制权限；`observe` 每次重新打开所属代次的普通单链接、当前 UID 文件，拒绝链接、超大/损坏 JSON；`wait_ready` 使用本对象观察/所属检查调用既有双网门槛。它只适用于本进程持有启动对象的会话，不能用于重开后的 PID 恢复，也不证明 FD 已被正确继承。未发送进程信号。

本轮合成负测包含错误资产/固件哈希、过期/未来/缓慢路由采集、准备中路由变更、错误 backing、空间不足、第二 overlay 故障、现场保留/拒绝覆盖、全局锁释放/场景锁竞争、进程退出/参数变化和损坏/链接记录。另用真实 `qemu-img` 创建三份 1 MiB 合成 QCOW2 基盘并准备/检查 overlay；不是 Wintermute 真实来宾验证。跨实例显式 MAC 登记、同 UID 恶意并发路径替换防护、正式硬件/来源绑定、服务 argv/FD 启动链、journal/崩溃恢复、事务重置及真实拓扑仍待后续实施。

### 8.2 跨实例资源登记与双网服务生命周期/恢复合成验证（2026-10-14）

完整准备入口新增 `ctflab_scenario_registry.reserve_prepared`，在全局锁→场景锁均持有时，派生资产写入之前登记实例 UUID、代次、四个来宾 NIC 与两个 DHCP server MAC、两端口及节点/网络/socket 路径。`scenario-reservations.jsonl` 为 0600、当前 UID、普通单链接的追加事件文件，序号连续，禁止重复 JSON 字段；完整行写入、文件与父目录 fsync。跨实例重复 MAC/端口/路径和同实例未释放预约闭锁；部分准备失败也保留预约，不能凭 FD 关闭自动认定没有进程。尾部半行、损坏 JSON、未知/重复释放、非法占用均阻止后续写入。登记过且已释放的历史资产继续保留；未登记的旧 prepared/节点/网络现场要求恢复，不能自动迁移或推断无占用。登记范围只覆盖同一状态根的场景，不覆盖其它状态根、旧单机入口或外部进程。

`prepared.json` 新增 `reservation_token`（操作身份，不是访问凭据）。`release_reservation` 仅通过可信现场观察器证明所属代次三节点与双网络全部停止后追加释放事件；不删除记录或资产。调用顺序必须先结束持场景锁的会话，再以全局→场景锁重新观察和释放，禁止持场景锁反向等待全局锁。观察失败、归属不明、场景锁竞争或停止集合不完整保留预约。该观察器没有默认生产实现，单纯读取旧 stopped 字样不能作为证据。

新增独立 `ctflab_scenario_services`，没有 GUI/CLI 接线、默认启动器或 VM 启停。`network_service_command` 从准备对象构造网络模块白名单 argv 和单个监听 pass_fds，不关闭再重绑端口，FD 默认仍不全局继承。`NetworkServiceSession` 要求完整准备绑定、有效预约和所持场景锁，通过显式注入的 spawn/启动身份提供器执行 outer→inner 服务流程。总截止时间覆盖两次启动和双网就绪，不给每个阶段重新计时；两网配置与所属启动对象通过才记录 `networks-ready`，不称整场景 running。

每次 spawn 前先追加 `starting` 与 pending 网段，成功取得对象/argv/启动身份后再记录绑定；第二网失败、单网就绪、超时、日志写入异常均停止创建后续资源并保留对象/FD/预约。启动抛异常不证明没有子进程；未记录身份的启动窗口须恢复，不会自动重试。健康检查发现服务退出、启动身份变化或配置/记录错误时仅降级，不重启服务。日志 `network-lifecycle.jsonl` 按序号、实例、代次、预约身份和完整准备绑定 SHA-256 保存状态快照；不记录密码或 SPICE ticket。

网络停止须外层明确证明全部节点已停止，再核对会话实际启动对象、argv 与启动身份，记录 stopping 后逆序请求 inner→outer 的正常 terminate；每网请求意图先写盘，重试只等待，不重复发送。截止时间到进入 `stop-pending`，不 kill、不关闭仍持有的准备资源、不释放预约；只有所有实际启动对象退出才记 stopped。日志失败在发送请求前闭锁；请求结果不明或异常保留降级现场。本轮只用合成进程对象验证这些动作，没有对真实 PID 发信号。节点证明、启动身份以及真实进程控制仍是可信外层责任。

`recover_network_services` 是只读审计，不自动接管/补启/发信号/释放资源。它按调用方 UUID/代次定位私有准备记录，重验清单与登记的完整 MAC/端口/路径集合、连续日志及准备绑定摘要，要求可信 inspect 同时核对 PID、argv、启动身份；PID 复用、pending 启动窗口、降级或不明停止窗口报告 `recovery-required`。观察结束重新读准备、日志和登记，变化则拒绝结果。只报告 `prepared-observed`、`networks-observed` 或 `stopped-observed` 等观察等级；networks-observed 未重新验 DHCP/节点/隔离，stopped-observed 仅指网络服务，不证明三节点或磁盘可重置。没有生产身份采集器、锁下恢复接管、来宾/QMP 资产现场审计与事务重置。

验收命令、60 项相关测试与 94 项文档守卫结果见 [本轮验证记录](verification-scenario-services-2026-10-14.md)。既有网络独立准备接口仍只用于低层合成调用，不经过登记，不能当作可发布场景入口；旧无预约 prepared 记录不能直接启用新会话。原有同 UID 恶意并发路径替换防护、空间硬预约、真实 FD 继承及隔离矩阵、Wintermute 题目与跨 Mac 验收继续未完成。

### 8.3 三节点生命周期与派生资产重置事务合成切片（2026-10-14）

新增 `ctflab_scenario_nodes.ScenarioNodeSession`：要求双网会话已就绪、准备对象仍持场景锁，按节点名称排序取得节点锁；使用既有白名单 `qemu_command` 生成三节点 argv。启动器、实际启动身份、QMP 观察和 ACPI powerdown 全部必须显式注入，没有默认真实 QEMU/QMP 客户端。启动顺序为 Neuromancer→Straylight→Kali，总截止时间包括各节点就绪等待；每次 spawn 前记录 pending 窗口，随后绑定启动对象/argv/启动身份。就绪要求 PID/启动身份、实例/代次、节点 ID、overlay 与 QMP 路径及明确 qmp_ready 匹配，只记录 `nodes-ready`，不声称 DHCP/业务/题目/隔离验收通过。

部分启动失败、QMP 缺失/错盘/错代次、网络降级或进程退出停止创建后续节点并保留现场，不自动补启。关机顺序 Kali→Straylight→Neuromancer；每节点正常关机请求意图先写日志，每节点独立截止时间，超时进入 stop-pending，保留后续节点与双网；再次等待不重复发送已记录请求，无 kill/强制停止。只有全部本会话节点退出后 `nodes_stopped` 才允许网络会话停止。节点 close 只释放其锁，不停止对象或关闭外层场景资源，调用方仍需遵守所有权与恢复门槛。`recover_scenario_nodes` 只读审计绑定摘要、日志与可信现场 PID/argv/启动身份；pending、PID 复用或观察期间记录变化要求恢复，不接管 QMP或补发关机请求。人工桌面、来宾地址及服务检查未接入。

新增 `ctflab_scenario_reset`，提供明确的资产事务入口。`initialize_active_generation` 在全局→场景锁及三节点/双网停止证明下显式创建初始 `active-generation.json`，拒绝已有指针覆盖。`reset_scenario_assets` 在同样锁与可信新鲜停止证明下，仅向更大的新代次创建三份 overlay 和 UEFI NVRAM；只读复核基盘/固件哈希、独立 QCOW2、准备空间、backing 格式/路径与 qemu-img check。原基盘、旧代次及旧记录保持；目标代次有任何现场即拒绝覆盖。新网络目录为空，不复制 network.json、租约、PID或旧端口。

新代次 `reset-ready.json` 保存原清单/稳定 MAC/候选 IP/基盘及固件引用、新运行目录和 overlay/NVRAM SHA-256 完整性清单，状态专门标为 `reset-assets-ready`。完成资产文件与目录 fsync、重新核验来源、再次确认三节点/双网停止及旧指针未变后，创建唯一 pending 指针文件，通过单次 os.replace 切换活动指针，随后 fsync 场景目录并追加 committed 日志。任一失败保留新旧资产、pending 文件和日志，不逐节点切换、不回删失败代次、不自动 stop/启动或释放旧资源预约。

`audit_reset` 只读核对活动指针、描述摘要和新代次磁盘/变量完整性。提交前中断报告 `old-active-preserved`；指针已切换但提交日志中断报告 `committed-observed`；不一致闭锁。`recover_reset_transaction` 在重新取得全局→场景锁、重验完整性并提供停止证明后，显式补记 committed，或在旧指针仍活动时记 aborted；不改变指针、删除资产或自动重试。放弃后只能另选尚不存在的新代次。资源登记能识别 committed/aborted 的资产历史，不为它虚构活跃端口预约。

**接续门槛**：此切片完成的是节点控制的合成契约和派生资产事务，不是正式可启动的整场景重置功能。`reset-ready.json` 与原 `prepared.json` 的网络/socket/资源预约绑定分开，新资产还没有接入“停止旧预约→新代次资源重新预约→复用已核验资产→服务/节点启动”的生产或合成编排入口。旧资源预约保留；现有准备入口对旧活动代次及未接续的 reset-assets-ready 明确拒绝，不能绕过指针继续旧盘。下一阶段优先补该接续链与合成故障验证，之后再考虑 GUI/CLI 和真实运行授权。

验收见 [节点与重置事务验证](verification-scenario-nodes-reset-2026-10-14.md)：新增 23 项合成/派生格式测试，相关总计 83 项通过；真实 qemu-img 只操作三份 1 MiB 合成基盘，没有真实 VM、QMP 或服务子进程。停止证明/启动身份/现场观察器仍由可信调用方提供；尚无真实来宾、业务、持续路由隔离、跨 Mac 或发布验收。完整性清单用于启动前停止态资产，不能把来宾合法写入后的哈希变化直接当作运行故障，后续接续链须区分资产准备与运行状态。

### 8.4 重置接续链、生产控制与 CLI/GUI 入口（2026-10-14）

新增 `resume_reset_resources`：把已提交的 `reset-ready.json` 资产接续为新代次运行预约，也覆盖"指针已切到 prepared 但服务未及启动"的崩溃现场（此时监听 FD 已随旧进程死亡）。顺序固定：指针与资产完整性核验（`_source` 校验 reset-ready 清单哈希）→ 全局→场景锁 → 停止证明 → 释放旧预约（reset-ready 路径）或释放失效当前预约（已激活重接路径）→ 路由检查 → 绑定新回环监听 FD → 新代次 socket 目录 → 锁内复核 overlay/NVRAM/固件完整性 → 资源登记 → 写/替换准备记录 → 原子切换活动指针 → 场景锁交接返回 `PreparedNetworks`。复用已准备的 overlay/NVRAM，不创建磁盘、不沿用旧端口/租约/运行记录；server MAC 与实例 NIC MAC 与代次无关，因此旧预约必须先释放才能登记新预约（6 个 MAC 全部同代次相同）。任一失败保留现场：旧预约释放失败即中止；新预约失败可重跑（重跑会跳过已释放旧预约）；准备记录仅在其预约可证明消失、无运行日志且资产一致时原子替换；孤儿预约由新入口 `recover_reset_continuation` 在"指针仍指 reset-ready/prepared、无运行日志、可信停止证明"三条件下显式释放，不删资产、不改指针。`NetworkServiceSession` 新增活动指针门槛：指针存在时必须指向本准备记录，堵住接续中断的孤儿记录绕过激活启动。`registry.release_reservation` 拆出锁内核 `_release_locked` 供接续链在已持锁时复用，观察器契约改为接收 {instance_uuid, generation} 并由内核注入 token。

新增 `ctflab_scenario_runtime`（生产采集与恢复接管，全部可注入合成验证）：`process_start_identity`/`build_inspect` 用只读 `ps -ww` 采集"启动时间+命令行"摘要，接受包装脚本（shebang/env）产生的解释器前缀，把僵尸 `<defunct>` 按 absent 处理，对 macOS 在退出窗口期退化输出的 `(进程名)` 做有界重读后仍失配才判 unknown；`child_identity` 连续两次一致才采信；`qmp_query`/`qmp_powerdown` 走私有 UNIX socket 完成握手/查询/ACPI 请求；`node_observer`/`node_powerdown` 把身份与 QMP 接到会话注入点；`stopped_observer` 逐一核对已记录进程与 QMP 端点，产出与 `_stopped` 契约同形的证据（日志损坏按 unknown，绝不冒充停止；旧代次释放时指针已切换则直接读该代次准备记录自洽校验）；`stop_recovered_nodes`/`stop_recovered_services` 在全局→场景（→排序节点锁）内按日志身份核验后接管正常关机/终止，意图先写日志、不重复发送、超时进入 stop-pending、从 `stopping` 状态可重试，不以 PID 存活或旧状态文件授权控制。

CLI 新增 `scenario` 子命令组（prepare/status/start/stop/reset/recover，2026-10-14 起另含 release，见 8.5），独立状态根（默认 `<状态目录>/scenario-state`，可被全局 `--state-dir` 带动）与短 socket 根（`/tmp/ctflab-sc-<uid>`，受 104 字节路径上限约束）。`start` 先初始化指针（无指针时）再经 `resume_reset_resources` 接续，随后在同一进程内创建双网会话与三节点会话；子进程以新会话启动并在就绪后落盘身份，命令本身退出（"节点就绪"只表示进程与 QMP 已核验，不表示来宾地址、题目或隔离可用）。`stop` 经恢复审计与接管函数工作；超时返回非零并保留 stop-pending。`status --json` 输出指针、重置事务、双网/节点恢复审计、停止证据与建议入口，明确区分已停止/仍存活/不明归属/失败阶段；单机入口按 profile 命名空间工作，与 `scenarios/<uuid>` 状态根无交集，不能绕过场景所有权操作所属节点。GUI（GuiCore/GuiApp）新增场景面板：解码 `scenario status --json`、诚实概括（待恢复/仍存活/已停止/未初始化）、确认后请求正常停止、显式收口/释放孤儿；准备/启动/重置仍走 CLI。

验证见 [本轮验证记录](verification-scenario-resume-runtime-2026-10-14.md)：接续链 13 项、生产运行时 13 项、CLI 端到端 5 项（合成 qemu 桩 + 真实 DHCP 服务子进程 + 真实 ps/QMP 身份链）、GUI 核心 217 项检查、完整本地回归 790 项（跳过 10）。真实 VM、真实 Wintermute 题目、双网隔离矩阵、跨 Mac 与发布验收仍未运行；`scenario prepare/start` 的生产路径只在合成资产上验证过，不构成 Wintermute 适配证据。

### 8.5 显式释放入口 `scenario release`（2026-10-14）

补齐实机验收暴露的已知缺口：停止不释放预约，销毁验收状态根前需要显式释放入口。`scenario release` 复用登记层 `release_reservation` 与生产 `stopped_observer`，语义固定：解析状态根与实例 → 读取活跃预约（预约流程保证同一实例至多一项，多项即拒并要求恢复核验）→ 以现场停止证明（非持久化 stopped 字样）核对所属代次三节点与双网络全部停止后追加 release 事件。释放失败保留预约并引导 `scenario stop`/`status`；实例没有活跃预约时幂等成功。登记是追加式账本：release 不删除资产、生命周期日志或活动指针，销毁/归档状态根属用户显式操作；释放后的代次进入登记历史，`reset --new-generation N`/重新 `prepare` 均可开新周期（接续链跳过已释放旧预约的分支有合成覆盖）。只 prepare 未 start 的实例（无指针、无日志）按"从未启动"证明释放。`status` 在观测全停且预约活跃时给出 release 建议入口；GUI 面板不覆盖 release，走 CLI。

验证（2026-10-14）：在 [场景 CLI 验证](verification-scenario-resume-runtime-2026-10-14.md) 同套合成链路（合成 qemu 桩 + 真实 DHCP 服务子进程 + 真实 ps/QMP 身份链）上新增 3 项测试——运行中被停止证明拒绝、释放后幂等且资产/指针保留；释放→reset→start→stop 跨代次闭环（覆盖旧预约已释放的接续分支）；未启动实例释放后重新 prepare。场景组 110 项通过；无真实 VM 或网络服务参与，本节实现不代表已在验收状态根上执行过 release。

## 9. Wintermute 独立实机验收方案（待授权执行）

本节是可执行方案，不是验收记录；任何真实服务/VM 启停需新阶段明确授权，并使用独立实例与派生盘，不接管用户现有 Kali。

前置与资产：读取 `ctflab-new-three-20261013/staging/` 两个 Wintermute QCOW2 候选基盘并重算 SHA-256 与来源/许可核对（原件 OVA、说明文本一并归档哈希）；在独立状态根（如 `/tmp` 下或用户指定目录）执行 `scenario prepare`，绑定三份基盘与 Kali UEFI code/vars；准备前后各采集一次宿主路由，确认 192.168.243.0/24 与 192.168.244.0/24 无冲突。硬件与 NIC 顺序：先按 OVF 与首冷启动确认 Straylight 双卡模型（PRO/1000 T、MT 的清单映射）与 PCI 顺序，必要时仅修改派生清单，不触碰基盘。

执行序列（每步保存证据）：① 两轮冷启动与正常停止：`scenario prepare` → `start`（Neuromancer→Straylight→Kali 就绪日志）→ `status --json` 存档 → `stop`（Kali→Straylight→Neuromancer 关机日志 + 双网退出）→ 确认进程/端口/QMP 全部退出；第二轮验证停止后再启动路径（经 `reset` 新代次）。② 显示或登录：对每节点经 SPICE UNIX socket 连接截图，记录登录界面或控制台可用性，不把 UEFI Shell 或错误画面当作成功。③ 来宾地址：每节点内执行 `ip addr`/`ifconfig`，核对 Kali=outer.10、Straylight outer.20/inner.20、Neuromancer=inner.30 与 DHCP server ID；与清单候选一致才记录为通过。④ 目标服务：按原 Wintermute-Lab-Setup.txt 记录的服务清单逐项探测（仅记录已知服务，不猜端口），保存命令输出。⑤ 应通/禁通矩阵：Kali↔Straylight（outer，应通）、Straylight↔Neuromancer（inner，应通）、Kali↔Neuromancer（禁通，双向 ARP/ICMP/TCP 负测）、outer DHCP↔inner（禁泄漏，抓包 server ID 与广播域）、任意节点→公网/宿主（无运行器出口，受控本地探针）。⑥ 跳转解题：人工完成原题跳转（取得 Straylight 后经其访问 Neuromancer），证明与初始禁通不矛盾（来自攻陷后的来宾路由，不由运行器预置）。⑦ 整场景重置：全部停止后 `reset --new-generation N`，核对旧代次保留、新代次 overlay/NVRAM 哈希清单、`start` 后地址与服务复位。⑧ 重开恢复：每轮停止/运行中各杀死一次编排 CLI，重开 `status` 核对观测等级，`stop` 完成接管停止。

判定与记录：只有矩阵全部符合、地址一致、服务可达且两轮冷启动/重置/恢复完成才可标注"已适配、可用"；差异（服务缺失、NIC 顺序不符、来宾未 DHCP）写入差异记录，不自动修补来宾，不把失败项标为通过。全程产物：状态根、生命周期日志、`status --json` 快照、截图、抓包与命令输出，归档到带日期的 verification 文档。


### 9.1 候选清单提案与执行命令序列（2026-10-14，已通过 schema 校验，未物化执行）

以下清单使用预检记录的现场哈希起草，已通过 `parse_manifest` 严格校验（能力集、拓扑、租约、资源上限、生命周期顺序）。`hardware_verified` 保持 `false`：只有两轮冷启动与矩阵证据齐备后才可由执行轮次改写。NIC 模型 `e1000` 对 Straylight slot1（82540EM）为精确对应，对 slot0（82543GC）与 Neuromancer 为最接近可用模型——以来宾内驱动命名为准，冷启动确认前不得宣称原卡型已复现。

```json
{
  "schema": 1,
  "scenario_id": "wintermute",
  "required_capabilities": ["isolated-dhcp-v1", "multi-nic", "scenario-v1", "transactional-reset-v1"],
  "assets": {
    "kali": {"sha256": "974a319f596170d171e75a5ee3e0f0fd4d28439ab10373c14f0fd9348b396315", "source": "CTFLab-Library kali-arm64 processed copy", "license": "own-installed-system-image", "profile": "kali", "hardware_verified": false},
    "straylight": {"sha256": "6724817218c88c3b126983c42e5824b48bdb02e93ce58de0a275e7c09aa4e235", "source": "Wintermute-Straylight OVA conversion staging candidate", "license": "community-lab-vm", "profile": "straylight", "hardware_verified": false},
    "neuromancer": {"sha256": "817452b4cd41cf0fa459c7835e5969f9525b0008d3c5c2ccb9479352d45cc562", "source": "Wintermute-Neuromancer OVA conversion staging candidate", "license": "community-lab-vm", "profile": "neuromancer", "hardware_verified": false}
  },
  "networks": {
    "outer": {"cidr": "192.168.243.0/24", "server": "192.168.243.1", "pool": ["192.168.243.100", "192.168.243.150"], "leases": {"kali/outer0": "192.168.243.10", "straylight/outer0": "192.168.243.20"}, "uplink": "none", "gateway": null, "dns": []},
    "inner": {"cidr": "192.168.244.0/24", "server": "192.168.244.1", "pool": ["192.168.244.100", "192.168.244.150"], "leases": {"straylight/inner0": "192.168.244.20", "neuromancer/inner0": "192.168.244.30"}, "uplink": "none", "gateway": null, "dns": []}
  },
  "nodes": {
    "kali": {"asset": "kali", "architecture": "aarch64", "firmware": "uefi", "disk_bus": "virtio", "cpus": 2, "memory_mb": 2048, "interfaces": [{"id": "outer0", "network": "outer", "model": "virtio-net-pci", "pci_slot": 5, "mac": "derived"}], "depends_on": [], "shutdown": "acpi"},
    "straylight": {"asset": "straylight", "architecture": "x86_64", "firmware": "bios", "disk_bus": "ide", "cpus": 1, "memory_mb": 1024, "interfaces": [{"id": "outer0", "network": "outer", "model": "e1000", "pci_slot": 5, "mac": "derived"}, {"id": "inner0", "network": "inner", "model": "e1000", "pci_slot": 6, "mac": "derived"}], "depends_on": [], "shutdown": "acpi"},
    "neuromancer": {"asset": "neuromancer", "architecture": "x86_64", "firmware": "bios", "disk_bus": "ide", "cpus": 1, "memory_mb": 1024, "interfaces": [{"id": "inner0", "network": "inner", "model": "e1000", "pci_slot": 5, "mac": "derived"}], "depends_on": [], "shutdown": "acpi"}
  },
  "policy": {"internet": false, "host_forwards": [], "guest_management_nic": false},
  "lifecycle": {"start_order": ["neuromancer", "straylight", "kali"], "stop_order": ["kali", "straylight", "neuromancer"], "startup_timeout_seconds": 180, "shutdown_timeout_seconds": 120, "failure": "preserve", "reset": "stopped-atomic-preserve"},
  "checks": {"boot": [], "address": [], "service": [], "isolation": []}
}
```

执行命令序列（物化时把上表 JSON 存为独立文件并重新 `parse_manifest` 校验；状态根位置由当次授权指定）：

```bash
python3 tools/ctflab.py scenario prepare \
  --manifest <物化清单.json> \
  --asset kali=$HOME/Downloads/CTFLab-Library/02-已处理/kali-arm64-base.qcow2 \
  --asset straylight=$HOME/Downloads/ctflab-new-three-20261013/staging/wintermute-straylight-base.qcow2 \
  --asset neuromancer=$HOME/Downloads/ctflab-new-three-20261013/staging/wintermute-neuromancer-base.qcow2 \
  --firmware kali=/opt/homebrew/share/qemu/edk2-aarch64-code.fd,$HOME/Downloads/CTFLab-Library/02-已处理/kali-arm64-uefi-vars.fd \
  --state-root <授权状态根> --socket-root <短路径 socket 根>
python3 tools/ctflab.py scenario start --state-root <同上>   # 初始化指针→接续→双网→三节点
python3 tools/ctflab.py scenario status --json
python3 tools/ctflab.py scenario stop    # 每轮验收后
python3 tools/ctflab.py scenario reset --new-generation 2   # 第二轮冷启动前
python3 tools/ctflab.py scenario release   # 销毁状态根前：显式释放活跃预约（不删除资产）
```

销毁验收环境的固定顺序：`stop`（三节点与双网正常停止）→ `release`（现场停止证明通过后追加登记释放事件；幂等，可重复执行核对）→ 用户显式归档或删除状态根。release 不删除任何资产、日志或指针，`scenario-reservations.jsonl` 追加历史随状态根一同处置；证据材料（日志、截图、探针输出）应在删除前另行归档。

Kali UEFI vars 由 prepare 从库内文件只读复制为运行副本，原件不变。2026-10-14 清理后数据卷可用约 103 GiB，预检记录中的 7 GiB 空间风险已解除，执行时仍须监控增长。

第 9 节预检补记（2026-10-14，只读，未启动任何 VM/服务）：两份 Wintermute 候选基盘、两份原 OVA、原题说明、库内 Kali aarch64 候选与 vars、`edk2-aarch64-code.fd` 的现场 SHA-256、独立 QCOW2 格式核对、OVF NIC 证据（Straylight 82543GC+82540EM 双卡；Neuromancer slot0=NAT 82540EM 不得采用、slot1=82543GC）、路由零冲突（192.168.243/244 当前无宿主路由）、QEMU 11.1.0 工具链与空间风险（数据卷仅剩约 7.0 GiB，须监控或另指定状态根），见 [本轮预检记录](verification-wintermute-acceptance-preflight-2026-10-14.md)。场景清单尚未物化；Neuromancer 单卡冷启动起址与 e1000 具体模型映射仍属执行时门槛。实机验收需当次明确授权。

## 10. 交付验收方案（实机验收通过后执行）

实机验收通过后才进入交付阶段；候选资产、未打包工作区、已发布 App 与正式可用内容包四类状态必须区分标注，不得混用历史验收。

范围：① GUI 全流程验收——本机 GUI 走场景面板（状态/停止/恢复）与 CLI 准备/启动/重置协同，确认 GUI 不绕过场景所有权；② 跨 Mac——在第二台 Apple Silicon Mac 以分发形态（app + 内容包 + 最小软件版本声明）完成 prepare→start→stop→reset 全链路与矩阵抽查，记录 QEMU/Python 版本下限证据；③ 内容包——Wintermute 以内容包 schema 携带清单与资产引用（不含虚拟磁盘原件的分发等级另行按许可决定），`content verify/pack/unpack` 全链路（schema 3 场景包已实现，见 10.1）；④ 最低软件版本——按跨 Mac 实测确定运行器能力声明与版本门槛，更新发布说明；⑤ 回归——交付前完整本地回归、GUI 核心检查、文档守卫全绿。

发布动作（提交/推送/打包/发布）分别按当时授权执行；本轮不自动执行。任一环节失败保持候选状态并在验证记录中保留未验证项，不降级为"可用"。

### 10.1 场景内容包 schema 3（2026-10-14，已实现并合成验证）

schema 2 面向单机 profile（base/nvram 必须绑定随包 profile，导入后走 `ctflab run`）；场景资产由 `scenario prepare` 消费、没有单机 profile 语义，因此独立为 schema 3：一个包恰承载一个场景，`pack.scenario = {id, manifest}`，entries 角色白名单为 `scenario-manifest`（恰一条，文件名与 pack.scenario.manifest 一致）、`scenario-base`（可选，按 `asset` 绑定，唯一）、`scenario-firmware-vars`（可选，按 `node` 绑定，只能挂清单中的 UEFI 节点）与 `doc`；两种 schema 的角色互不混用，旧运行器按角色白名单拒绝。

交叉校验（`parse_scenario_pack`）：读取场景清单全文并按场景 schema 严格校验（`parse_manifest` + 当前运行器能力集）后，`scenario_id` 必须与 `pack.scenario.id` 一致；**随包基盘的登记 SHA-256 必须与场景清单声明完全一致**（包不能运输与清单矛盾的资产）；未随包资产由接收方按清单哈希自备（引用式分发，分发等级按许可另行决定）。claims 只能挂在场景 id 上。文件本体大小/哈希仍由 `verify_distribution` 逐个实测，`--json` 报告附场景摘要（资产 shipped 与否、哈希、固件 vars、运行器约束）。

制作与安装：`dist make-scenario-pack`（清单必带；`--asset 资产id=路径`/`--firmware-vars 节点=路径`/`--doc` 按需；复制后断言基盘哈希与清单一致，文件名规范为 `<场景id>.json`/`<asset>-base.<后缀>`/`<node>-uefi-vars.fd`；README 含接收者步骤与未随包资产提示）与 `dist install` 场景分支（整体校验通过后把场景文件复制进 `content-packs/<id>/scenario/`、只读保护、写 schema 3 安装记录；同名不同哈希拒绝覆盖，重装内容一致幂等；**不创建 profile、不注册镜像、不自动准备场景**），安装输出可直接粘贴的 `scenario prepare` 命令——随包资产/vars 给绝对路径，未随包资产与 edk2 code 固件给占位符（code 由接收方本机 QEMU/运行时提供）。跨 Mac 基盘为多 GB 文件，安装复制会使状态目录占用翻倍，属既定取舍（与 schema 2"导入后不依赖原包路径"同边界）。

验证（2026-10-14）：`test_ctflab_scenario_pack.py` 8 项——制作/校验往返与摘要、清单哈希不匹配拒绝、清单外资产/非 UEFI 节点拒绝、引用式包、篡改/缺失文件检出、解析层交叉校验负测（角色混用/路径/场景 id 不一致/claims 越界/运行器版本约束）、CLI 端到端（make→verify→install→幂等重装，含 prepare 命令断言）、篡改包与安装目录冲突拒绝；内容包/分发既有测试 51 项与完整回归 805 项通过（跳过 10 既有保留）。全部合成资产，未构建真实 Wintermute 包，未打包或发布。
