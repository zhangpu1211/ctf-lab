# CTFLab Mac M 跨架构靶场实施方案

> 状态：Phase 1 MVP 已开始实现。当前已落地 Mac M 本地 QEMU 运行器的 manifest、镜像导入、qcow2 overlay、启动/状态/停止/重置、基础健康检查和跨进程操作锁；ARM64 Kali 镜像、完整二层交换机、主机直连和签名打包仍按后续任务推进。本文是后续开发、测试、打包和验收的范围基线。

## 1. 目标与边界

### 1.0 当前执行范围：UTM 镜像适配服务（Phase 0）

在 CTFLab 运行器开发开始前，当前唯一承诺的交付是：**用户每提供一份合法获得且用于本地实验的虚拟机镜像，完成一次独立的 Mac M + UTM 兼容适配。**

输入可以是原始磁盘或虚拟机目录，例如 VMDK、VDI、VHD/VHDX、raw、qcow2、OVA/OVF，或已有 UTM 包。每次适配的标准流程如下：

1. 只读盘点原始镜像，识别客体架构、分区、引导方式、磁盘控制器和网卡模型；
2. 保留原始文件不作覆盖，将磁盘转换为 qcow2；
3. 为 Mac M 生成正确的 UTM/QEMU 配置：x86 客体使用模拟，ARM 客体使用虚拟化；
4. 逐项排除 UEFI Shell、黑屏、找不到磁盘、网卡不工作、服务不可达等兼容问题；
5. 实际启动并验证登录、网络和目标服务；
6. 交付 UTM 可直接导入/打开的包、必要的启动说明、访问地址和 SHA-256 校验值。

每台机器的配置都独立记录，至少包括 CPU 架构、BIOS/UEFI、内存、CPU 数、磁盘总线/控制器、显示设备、网卡型号、MAC 地址和验证结果。遇到需要修改来宾系统网络名称的情况，必须先做可恢复副本，并在说明中写明改动。

Phase 0 的成功标准不是“成功转成 qcow2”，而是“在当前 Mac M 的 UTM 中稳定启动且可使用”。Smoke 与 Basic Pentesting 2 已验证过的硬件组合可作为后续同类镜像的排障参考，但不应强行套用到所有镜像。

### 1.1 第一阶段目标

第一阶段交付一个只支持 **macOS Apple Silicon（M 系列）** 的 CTFLab MVP。用户无需理解 UEFI、磁盘控制器或网卡型号，即可一键启动以下组件：

- ARM64 Kali Linux 图形桌面；
- x86_64 Smoke 靶机；
- x86_64 Basic Pentesting 2 靶机；
- 隔离实验网络、固定地址、健康检查、停止与重置；
- Mac 主机与 Kali 对靶机的访问能力。

第一阶段的主要体验如下：

```bash
ctflab import smoke-1.0.0.ctflab
ctflab import basic-pentesting-2-1.0.0.ctflab
ctflab run kali smoke basic-pentesting-2
ctflab status
ctflab reset smoke
ctflab stop --all
```

运行后，Kali 必须出现可交互的图形桌面。用户能够在 Kali 的 Firefox、Burp Suite、Wireshark、Nmap、Metasploit、Ghidra 等图形或终端工具中操作靶机。

### 1.2 不在第一阶段实施的内容

- Windows AMD64、Linux AMD64 运行器；
- 兼容并接入用户已有的 UTM、Parallels 或 VirtualBox Kali；
- 应用内镜像商店、在线账户、课程系统、流量分析大屏；
- 多拓扑编辑器、多人协作、分布式靶场；
- 复制或分发 LingJing 的二进制、路由镜像或配置。

现有 Kali 的接入会在第二阶段设计平台适配器。第一阶段只保证 CTFLab 自己启动的 Kali 与靶机完整互通，从而降低网络兼容风险。

## 2. 已确认的技术事实

| 对象 | 结论 | 实施影响 |
|---|---|---|
| Mac M 宿主机 | ARM64 | ARM64 Kali 走 HVF 硬件虚拟化；x86 靶机走 TCG 指令翻译。 |
| Smoke | x86_64、Legacy BIOS、LSI SCSI、PCnet | manifest 必须固定这些硬件模型。 |
| Basic Pentesting 2 | x86_64、Legacy BIOS、IDE、e1000 | manifest 必须固定这些硬件模型。 |
| Kali | 使用 ARM64 Kali XFCE | 优先保证桌面和常用安全工具的响应。 |
| 路由器 | ARM64 Linux 小型路由器 | 使用原生架构，避免把 DHCP、NAT、抓包也放进 x86 模拟环境。 |
| QEMU | 第一阶段固定一个经验证的版本 | QEMU 内存快照与机器型号紧耦合，不允许随意升级。 |

已有镜像源仅作为制作输入，实施阶段不得覆盖：

- `<本地镜像目录>/Smoke/smoke.qcow2`
- `<本地镜像目录>/basic_pentesting_2/`

## 3. 总体架构

```text
                         macOS Apple Silicon
┌─────────────────────────────────────────────────────────────────┐
│ CTFLab CLI / 后续 GUI                                             │
│   ├── manifest 校验与镜像目录                                     │
│   ├── QEMU 生命周期管理（QMP）                                    │
│   ├── ctflab-switch（用户态二层交换机）                           │
│   ├── 就绪检查、日志与重置                                        │
│   └── 临时网络权限助手（仅“主机直连模式”需要）                    │
│                                                                  │
│                 192.168.242.0/24 实验网                         │
│              ┌────────── ctflab-switch ──────────┐              │
│              │                                    │              │
│       ARM64 Router                           管理平面/QMP        │
│       .1（DHCP、NAT、策略）                       │              │
│              │                 ┌──────────────────┼─────────┐    │
│        Kali ARM64 .10       Smoke x86 .20    Basic x86 .21   │    │
└─────────────────────────────────────────────────────────────────┘
```

### 3.1 性能策略

- **Kali ARM64：** 使用 `qemu-system-aarch64`、`-accel hvf`、VirtIO 磁盘/网卡/显示设备；这是日常图形桌面和工具的主力。
- **x86 靶机：** 使用 `qemu-system-x86_64`、`-accel tcg,thread=multi`；性能重点是服务可用和漏洞复现，不把它作为图形工作站。
- **显示：** 首版输出独立的本地图形窗口，使用 `virtio-gpu`，优先启用经过验证的 GL 路径，失败自动回落到 2D 模式。SPICE guest agent 用于动态分辨率和文本剪贴板；不以 VNC 作为默认显示路径。
- **存储：** 所有实验运行从不可变基础镜像创建 qcow2 overlay，重置时删除 overlay 后重新创建，基础镜像不被修改。

### 3.2 网络策略

网络必须同时满足“可练习”和“默认安全”：

| 方向 | 默认策略 |
|---|---|
| Kali → 靶机 | 允许 |
| Mac → 靶机 | 默认端口映射允许；直连模式允许全网段访问 |
| 靶机 → Kali | 允许，用于反向 Shell |
| 靶机 → Mac | 仅允许已建立连接及显式配置的回连端口 |
| 靶机 → 互联网 | 禁止 |
| Kali → 互联网 | 可由用户显式开启，默认关闭 |

网络分为两种模式：

1. **默认无管理员权限模式**：Mac 通过受控端口映射访问靶机，例如 `127.0.0.1:18080 → Basic:80`；Kali 在实验网内可完整扫描靶机。
2. **主机直连模式**：经用户一次管理员确认后，CTFLab 创建临时 host-only/路由接口，让 Mac 直接访问 `192.168.242.0/24`。停止靶场时必须移除路由、PF 规则和后台进程。

主机直连模式涉及 macOS 网络权限，是第一阶段中风险最高的部分；必须先做最小 PoC，确认所选 QEMU `vmnet` 后端或受控 L3 接口能可靠清理，再进入产品化。

## 4. 内容包与运行时约定

### 4.1 靶机包格式

每个 `.ctflab` 包为含签名清单的压缩内容包：

```text
smoke-1.0.0.ctflab
├── manifest.yaml
├── disks/
│   └── base.qcow2
├── screenshots/
│   └── cover.png
├── README.md
└── SHA256SUMS
```

运行时数据不写入应用包，统一放在：

```text
~/Library/Application Support/CTFLab/
├── images/           # 导入后校验完成的只读基础镜像
├── runtime/          # 每次启动创建的 overlay 与 QMP 文件
├── logs/
├── pcap/
└── state/
```

### 4.2 Smoke 清单基线

```yaml
schema: 1
id: smoke
name: Smoke
version: 1.0.0

guest:
  architecture: x86_64
  firmware: bios
  machine: pc
  memory_mb: 4096
  cpus: 2

disk:
  file: disks/base.qcow2
  format: qcow2
  bus: scsi
  controller: lsi53c895a

network:
  adapter: pcnet
  mac: "52:54:00:24:00:20"
  segment: lab
  internet: false

readiness:
  timeout_seconds: 180
  checks: [dhcp, icmp]
```

### 4.3 Basic Pentesting 2 清单基线

```yaml
schema: 1
id: basic-pentesting-2
name: Basic Pentesting 2
version: 1.0.0

guest:
  architecture: x86_64
  firmware: bios
  machine: pc
  memory_mb: 1024
  cpus: 1

disk:
  file: disks/base.qcow2
  format: qcow2
  bus: ide

network:
  adapter: e1000
  mac: "52:54:00:24:00:21"
  segment: lab
  internet: false

readiness:
  timeout_seconds: 180
  checks:
    - dhcp
    - type: tcp
      port: 80
    - type: http
      port: 80
      path: /
      expected_status: 200
```

### 4.4 Kali 清单基线

```yaml
schema: 1
id: kali-arm64
name: Kali Linux ARM64
version: 1.0.0

guest:
  architecture: aarch64
  firmware: uefi
  machine: virt
  memory_mb: auto
  cpus: auto

disk:
  file: disks/base.qcow2
  format: qcow2
  bus: virtio

display:
  adapter: virtio-gpu
  mode: local-window
  clipboard: spice-agent

network:
  adapter: virtio-net
  mac: "52:54:00:24:00:10"
  segment: lab
  internet: disabled-by-default
```

内存自动策略：8GB Mac 优先 Kali 3GB/2 核且一次运行一台 x86 靶机；16GB Mac 使用 Kali 5GB/4 核并允许两台靶机；24GB 以上使用 Kali 6～8GB/4～6 核。

## 5. 关键实现方案

### 5.1 运行器

运行器的长期目标是 Go，首个可交付切片先采用 Python CLI 快速验证 QEMU 参数和生命周期；待网络交换机、跨平台运行时和打包边界稳定后再迁移为 Go。当前 Python 运行器负责：

- 解析并严格校验 manifest；
- 检测 Mac CPU、内存、QEMU 版本与必需设备；
- 创建、挂载和清理 qcow2 overlay；
- 选择 QEMU 参数并启动 QEMU；
- 使用 QMP 查询运行状态、优雅关机与异常回收；
- 分配 MAC、固定实验 IP、实验网端口、显示端口、QMP 端口与日志路径；
- 运行 DHCP、TCP、HTTP 健康检查；
- 维护单一状态文件，支持 `status`、`stop`、`reset`。

运行器不得允许网络下载的 manifest 直接附带任意 QEMU 原始参数。QEMU 参数必须由允许字段组合生成，避免恶意镜像包读取宿主文件或暴露设备。

### 5.2 二层交换机与路由器

`ctflab-switch` 是 Go 实现的本地二层转发服务。QEMU 虚拟网卡使用本地 socket 接入。交换机需要实现：

- MAC 学习与已知单播转发；
- ARP、DHCP、未知单播和广播转发；
- 每实验隔离的端口组；
- 广播风暴/异常包速率保护；
- 可选 PCAP 文件输出；
- 服务退出时关闭所有 socket。

路由器是自建的最小 ARM64 Linux 镜像，包含 DHCP、NAT、默认拒绝的防火墙与控制 API。它的基础镜像与配置必须可复现构建，不依赖第三方闭源路由镜像。

路由器启动优化分两层：

1. 先确保普通冷启动稳定；
2. 再固定 QEMU 版本、机器型号与 CPU 参数，生成 `quickStart` QEMU 快照以缩短热启动。

任何 QEMU 版本或机器型号变动都必须使快照失效并回退冷启动，避免不兼容的内存状态造成文件系统损坏。

### 5.3 图形桌面

首版验收的重点是 Kali 图形桌面可用，而非将画面嵌入 CTFLab 主窗口。

- 默认启动 Kali 本地图形窗口；
- 支持全屏、窗口缩放、1920×1080、键盘与鼠标；
- 自动安装并验证 guest agent，支持文本剪贴板与动态分辨率；
- 允许 `ctflab run kali --headless`，但默认不启用；
- 关闭显示窗口时明确选择“关机”或“后台继续运行”；
- 对 VirGL/GL 渲染失败自动退回稳定的 2D 显示设备。

### 5.4 镜像导入、分发与重置

导入过程：

1. 解压到临时目录；
2. 拒绝绝对路径与路径穿越；
3. 校验 SHA-256 与 manifest；
4. 将基础镜像写入只读镜像目录；
5. 记录内容版本与导入时间。

启动时创建 overlay：

```bash
qemu-img create -f qcow2 -F qcow2 \
  -b /绝对路径/base.qcow2 \
  /运行目录/runtime.qcow2
```

重置只删除本次实验对应的 `runtime.qcow2` 和临时状态文件，再重新生成 overlay。导入后的基础镜像绝不修改。

## 6. 开发任务与验收

### Task 0：基线与兼容性验证

- [ ] 固定首版 QEMU 版本、构建来源和许可证清单。
- [ ] 在 Mac M 上验证 `qemu-system-aarch64 -accel hvf`。
- [x] 在 Mac M 上验证 x86_64 TCG 多线程启动 Smoke 与 Basic。
- [x] 记录每台镜像的 BIOS、磁盘控制器、网卡、内存和 CPU 最小配置。
- [x] 检查两个现有靶机基础镜像的 SHA-256，并创建不覆盖原件的独立副本。

**验收：** 两台 x86 靶机均能从命令行冷启动至登录/服务可用；不依赖 UTM 的图形配置。

### Task 1：CLI 骨架与 manifest

- [x] 创建 `tools/ctflab` CLI 和统一错误处理。
- [x] 实现 `import`、`list`、`run`、`status`、`stop`、`reset` 命令。
- [x] 实现 YAML manifest schema 校验与 QEMU 参数白名单。
- [x] 编写 Smoke、Basic Pentesting 2 和 Kali 的 manifest。
- [x] 实现状态文件、日志目录与异常进程回收。
- [x] 实现 `inspect`：读取格式、VMDK/OVF、MBR/GPT/EFI，并输出逐字段置信度。
- [x] 实现 `onboard`：生成不覆盖已有配置的候选 manifest、固定 IP/MAC 和派生 QCOW2。
- [x] 实现 `probe`：采集 QMP 状态、非全黑截图、DHCP 与 HTTP/SSH 协议证据。
- [ ] 实现截图 OCR/画面分类，区分登录界面、UEFI Shell、内核错误和无启动盘。
- [ ] 实现受控的 BIOS/UEFI、IDE/SATA/SCSI/VirtIO 启动回退矩阵。

**验收：** 使用 manifest 启动两台靶机；无效 manifest 或缺失镜像被清晰拒绝；未知镜像能生成带证据、置信度和人工复核状态的候选配置。

### Task 2：存储与生命周期

- [x] 实现基础镜像只读导入和 qcow2 overlay 创建。
- [x] 实现 QMP 优雅关机和超时强制停止。
- [x] 实现 reset 幂等性，并防止未加 `--force` 时删除运行中的 overlay。
- [x] 增加跨进程锁，防止并发启动、导入与 reset 竞争。
- [x] 为每个实例写入独立日志。

**验收：** 连续 20 次启动、停止、重置后，没有残留 QEMU 进程、锁、QMP socket 或基础镜像改动。

### Task 3：Kali 图形桌面

- [ ] 准备合法来源的 Kali ARM64 基础镜像。
- [ ] 配置 HVF、VirtIO 磁盘、网卡和显示设备。
- [ ] 验证 XFCE 登录、窗口缩放、键盘、鼠标和至少 1920×1080 显示。
- [ ] 安装/验证 guest agent 的文本剪贴板与动态分辨率。
- [ ] 实现 `--headless` 和显示窗口关闭后的行为选择。

**验收：** Kali 能稳定运行 Firefox、Burp Suite、Wireshark 和终端；图形窗口无持续高 CPU 占用或明显输入延迟。

### Task 4：实验网与 Kali 互通

- [x] 用回环 TCP socket 实现无 root 的 MVP 二层转发与最小 DHCP。
- [ ] 将 MVP 交换机迁移为带 MAC 学习、限速与 PCAP 的 `ctflab-switch`。
- [ ] 制作可复现的 ARM64 路由器镜像及 DHCP、防火墙规则。
- [x] 固定 Kali、Smoke、Basic 的 DHCP 租约和 IP。
- [ ] 实现 Kali 到两个靶机的 ICMP、TCP 和全端口扫描验证。
- [ ] 验证靶机对 Kali 的回连；验证靶机无法访问互联网。
- [ ] 输出可选 PCAP。

**验收：** Kali 能对 `192.168.242.20` 与 `192.168.242.21` 执行 Nmap；Basic 的 HTTP 服务可达；反向 Shell 可回连 Kali；靶机无法访问公网。

### Task 5：Mac 主机访问

- [x] 实现无权限模式端口映射与状态展示。
- [ ] 完成 macOS 主机直连模式 PoC。
- [ ] 添加临时权限助手、明确授权提示和操作日志。
- [ ] 实现停止/异常退出后的路由、PF 规则与接口清理。
- [ ] 测试 Wi-Fi 切换、睡眠唤醒和 CTFLab 崩溃后的恢复命令。

**验收：** 无权限模式下 Mac 能访问 Basic Web 服务；直连模式下 Mac 能访问实验网 IP；停止后 `netstat`、路由表和 PF 规则无 CTFLab 残留。

### Task 6：封装与交付

- [ ] 打包 `CTFLab.app`、受控 QEMU 运行时和所需动态库。
- [ ] 将运行时数据移出 `.app`，避免运行破坏签名。
- [ ] 修复所有动态库为 `@loader_path` 相对路径。
- [ ] 生成 SBOM、许可证说明、SHA-256 和版本信息。
- [ ] 完成 macOS 签名、公证和干净账户测试。
- [ ] 构建 `smoke-1.0.0.ctflab` 与 `basic-pentesting-2-1.0.0.ctflab`。
- [x] 建立私有 GitHub 源码镜像 `zhangpu1211/ctf-lab`，仅同步 CTFLab 源码、配置模板与文档，不上传虚拟磁盘、凭据或课程数据。

**验收：** 在一台未安装开发依赖的 Mac M 上，用户可以安装 CTFLab、导入两份内容包并完成实验；不需要手工编辑 QEMU 参数。

## 7. 第一阶段验收清单

以下项目必须全部通过，第一阶段才可以宣布完成；已完成的 MVP 子项先标记，带有“待 Kali/网络”字样的项目仍未宣称完成：

- [x] `ctflab run kali-arm64 smoke basic-pentesting-2` 的运行器可以一次启动已导入的组件（Kali 需先提供 ARM64 镜像）。
- [ ] Kali 显示完整图形桌面，可使用图形化安全软件。
- [ ] Kali 能扫描并访问两台靶机（待完整实验交换机/ARM64 Kali 验证）。
- [x] Smoke 地址固定为 `192.168.242.20`，Basic 地址固定为 `192.168.242.21`。
- [x] Mac 能通过无权限端口映射访问 Basic；直连模式仍待实现。
- [ ] 靶机可按配置回连 Kali，但不能访问公网。
- [ ] 运行、停止、重置连续 20 次无残留进程或网络规则。
- [x] `reset` 后靶机从基础镜像重新创建 overlay，基础镜像哈希未变化。
- [x] 新镜像可通过 `inspect → onboard → probe` 进入候选适配流程，并明确区分候选与已验证交付。
- [ ] Kali 与两个靶机的可用性都有自动健康检查结果（两个靶机已通过 DHCP、HTTP/SSH 协议检查，Kali 待导入）。
- [ ] 在干净的 Mac M 用户环境可完成安装、导入和运行。

## 8. 工期、风险与决策

### 8.1 工作量预估

| 里程碑 | 预估工作量 |
|---|---:|
| 运行器、manifest、两台靶机与 overlay | 2～3 个工作日 |
| ARM64 Kali 图形桌面 | 2～3 个工作日 |
| 实验交换机、路由器、Kali 互通 | 2～3 个工作日 |
| Mac 主机访问与权限清理 | 1～2 个工作日 |
| 打包、签名与干净环境验证 | 1～2 个工作日 |

Mac M MVP 的合理预期为约一周。现有外部 Kali 兼容、Windows/Linux 适配和完整 GUI 都不能插入该周期，否则会显著增加联调风险。

### 8.2 主要风险与处置

| 风险 | 影响 | 处置 |
|---|---|---|
| macOS 实验网直连需要权限 | 可能影响主机直接 ping/扫描靶机 | 默认提供无权限端口映射；直连模式单独 PoC、显式授权、可靠清理。 |
| x86 靶机在 M 系列上较慢 | 靶机启动慢于 Kali | 保持靶机最小资源；使用 TCG 多线程；不将 Kali 也设为 x86。 |
| 图形 GL 驱动兼容性 | 3D 或少数应用不稳定 | 先使用 XFCE；提供稳定 2D 回退；不把 3D 加速作为首版验收条件。 |
| QEMU 快照兼容性 | 升级后可能无法恢复 | 固定 QEMU/机器类型；快照不兼容时回退冷启动。 |
| 闭源软件供应链/许可 | 不可合法再分发 | 不复制 LingJing 资源；只使用自行构建或明确许可的组件。 |
| 靶机存在真实漏洞 | 可能影响宿主网络 | 默认阻断公网；最小化宿主访问；拒绝任意 QEMU 参数。 |
| 自动探测误判架构或控制器 | 可能进入 Shell、黑屏或找不到根盘 | 输出逐字段置信度；低置信度要求显式覆盖；probe 结果不自动升级为已验证交付。 |

## 9. 完整后续路线图

完整路线图按阶段推进，每个阶段都必须有独立验收门槛。任何后续功能不得破坏已经验证过的镜像包、manifest 或重置语义。

### Phase 0：按需 UTM 适配（当前执行）

**目的：** 将每次收到的镜像交付为可在当前 Mac M + UTM 中使用的实验机。

**交付物：** UTM 包或可导入磁盘、配置记录、启动说明、网络/服务验证结果、SHA-256。

**自动化入口：** 先用 `ctflab inspect` 生成只读事实和候选硬件，再用 `ctflab onboard` 生成白名单 manifest，最后以 `ctflab probe` 收集启动证据。任何低置信度字段及非全黑截图仍需人工复核。

**退出条件：** 镜像在 UTM 中稳定启动；目标服务或登录界面可访问；原始输入未被覆盖。

### Phase 1：Mac M 单机 CTFLab MVP

**目的：** 不依赖 UTM 图形配置，交付 CTFLab 自管的 ARM64 Kali、Smoke、Basic Pentesting 2 和隔离实验网络。

**范围：** 本文第 2～8 节定义的 CLI、manifest、overlay、Kali 图形桌面、用户态交换机、路由器、健康检查、Mac 访问与 Mac 打包。

**退出条件：** 第 7 节验收清单全部通过；内容包、运行时和基础镜像可被清晰区分；停止后没有进程、路由或防火墙规则残留。

### Phase 2：单机体验完善与外部 Kali 兼容

**目的：** 让用户能够继续使用已经存在的 UTM、Parallels 或 VirtualBox Kali，并提升单机靶场的日常体验。

**工作项：**

- [ ] 为 UTM、Parallels、VirtualBox 制作独立网络适配器和探测器；
- [ ] 支持外部 Kali 到 CTFLab 实验网的静态路由/受控转发；
- [ ] 将 Kali 显示嵌入 CTFLab GUI，保留独立窗口回退；
- [ ] 增加共享文件夹、文本剪贴板、可选 USB 设备转接；
- [ ] 提供图形化靶机列表、状态、IP、服务入口、启动/停止/重置；
- [ ] 提供路由、网络与日志的“自检/修复”页面。

**退出条件：** 至少一种外部 Kali（优先 UTM）可以完整扫描、访问和回连 CTFLab 靶机；图形界面不影响 CLI 的稳定使用。

### Phase 3：跨平台运行时与内容包

**目的：** 同一份 `.ctflab` 内容包可在 macOS ARM64、Windows AMD64、Linux AMD64 上运行。

**工作项：**

- [ ] 抽象平台运行时接口：进程、QMP、网络、显示、权限与存储；
- [ ] Windows 使用 WHPX，Linux 使用 KVM，分别完成运行器和打包；
- [ ] 为每个平台提供对应的原生路由器镜像；
- [ ] 建立三平台 CI 冒烟测试，验证导入、启动、网络、重置和停止；
- [ ] 定义内容包兼容矩阵：客体架构、最低运行时版本、资源要求和已知限制；
- [ ] 实现版本迁移和不兼容快照的安全回退。

**退出条件：** Smoke 与 Basic Pentesting 2 的同一内容包在三平台完成自动化启动、网络和重置验证；平台差异在 UI 与文档中明确显示。

### Phase 4：内容供应链与可观测性

**目的：** 支持安全、可追溯的镜像分发、课程靶场目录和实验过程观测。

**工作项：**

- [ ] 建立签名内容索引、镜像元数据、版本、依赖和弃用策略；
- [ ] 下载断点续传、校验、镜像缓存和可恢复导入；
- [ ] 生成 SBOM、许可证清单、来源和完整性证明；
- [ ] 提供 PCAP 录制、基础流量筛选和靶场事件时间线；
- [ ] 提供实验说明、账号、入口、提示与一键恢复初始状态；
- [ ] 添加离线内容源，保证教学环境不依赖公网。

**退出条件：** 用户可以从可信目录导入课程靶场；每个内容包都能显示来源、哈希、许可和兼容性；离线环境仍可完成启动和重置。

### Phase 5：复杂拓扑与协作能力

**目的：** 从单机多虚拟机扩展到可编排的复杂靶场。

**工作项：**

- [ ] 多网段、路由、防火墙、DNS、域控与多跳拓扑模板；
- [ ] 可视化拓扑编辑、模板参数化和实验快照；
- [ ] 多人实例隔离、配额、实验生命周期和审计；
- [ ] 局域网分发节点或远程运行节点；
- [ ] 课程/竞赛集成、成绩或进度记录（仅在明确需求时实现）。

**退出条件：** 至少一个多网段靶场可以被模板化复制、独立运行、完整重置并保留审计记录。

### 长期架构约束

无论进入哪个阶段，必须遵守以下约束：

1. 基础镜像不可变，用户运行状态只能写入 overlay；
2. 在线元数据不能直接传入任意 QEMU 参数；
3. 脆弱靶机默认无互联网出口；
4. 临时网络权限和系统规则必须可审计、可恢复、可清理；
5. 内容包、运行器、镜像和用户数据必须分离存放；
6. 只使用自行构建或许可明确可分发的二进制、镜像和驱动；
7. 保持 CLI 可用，GUI 不能成为启动或恢复靶场的单点依赖。

在正式进入 Phase 1 前，Phase 0 将持续作为独立支持能力：每收到一个新镜像，先以 UTM 适配流程验证其可运行性，并把得到的硬件元数据沉淀进未来的 manifest 规则库。
