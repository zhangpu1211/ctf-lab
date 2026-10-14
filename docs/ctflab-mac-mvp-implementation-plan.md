# CTFLab Mac M 跨架构靶场实施方案

> 状态（2026-10-11 整理）：Phase 1 核心课堂主路径已交付，当前公开软件为 0.1.1-preview（最低 macOS 26、Apple Silicon，ad-hoc、未公证）。10 月 11 日工作区已加入单镜像导入进度/取消重试与受控矩阵候选保存，尚未重新构建到发布 ZIP；GUI 向导人工链路与真实新镜像专项不因回归测试通过而升级。最新使用/分发入口见 `docs/ctflab-current-status.md`，历史测试数只属于各自记录日期；外接屏、跨 Mac、Mac 睡眠和干净长时闲置/持续负载仍按发布门槛保留。验收状态只使用四类标签：**已验证 / 部分验证 / 未验证 / 后续任务**（定义见第 7 节）。

## 1. 目标与边界

### 1.0 历史起点与可选交付：UTM 镜像适配服务（Phase 0）

在 CTFLab 运行器开发开始前，曾以单镜像 UTM 适配为交付起点。现在 CTFLab 软件与完整镜像目录是主路径；用户明确需要 UTM 时仍可单独适配，不把 UTM 包与 CTFLab 分发包混用。

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

第一阶段的主要体验如下（命令与当前 CLI 一致；`.ctflab` 内容包已实现但不含虚拟磁盘，不能与 `DISTRIBUTION.json` 基盘包混称）：

```bash
./tools/ctflab import smoke /path/to/smoke.qcow2
./tools/ctflab import basic-pentesting-2 /path/to/basic_pentesting_2-disk001.vmdk
./tools/ctflab run kali-arm64 smoke basic-pentesting-2
./tools/ctflab status
./tools/ctflab reset smoke
./tools/ctflab stop --all
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
- **显示：** 首版输出独立的本地图形窗口，使用 `virtio-gpu`。`run --display auto` 对 Kali 图形会话先做
  完整能力探测，能力齐全时默认使用带 `spicevmc` agent transport 的 SPICE 真实自动分辨率；缺件时退化为
  Cocoa 固定显示。无头模式不启动图形客户端；显式 SPICE 缺件时在启动前报错且不回退。
- **存储：** 所有实验运行从不可变基础镜像创建 qcow2 overlay，重置时删除 overlay 后重新创建，基础镜像不被修改。

### 3.2 网络策略

网络必须同时满足“可练习”和“默认安全”：

| 方向 | 默认策略 |
|---|---|
| Kali → 靶机 | 允许 |
| Mac → 靶机 | 默认端口映射允许；直连模式允许全网段访问 |
| 靶机 → Kali | 设计允许（用于反向 Shell）；应用级回连尚未验证（当前仅帧级双向证据） |
| 靶机 → Mac | 仅允许已建立连接及显式配置的回连端口 |
| 靶机 → 互联网 | 禁止 |
| Kali → 互联网 | 默认通过 user-mode NAT 允许；仍不加入靶机管理网 |

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
- 自动安装并验证 guest agent 的文本剪贴板（已交付）；`qemu-vdagent` 仅是经授权的文本剪贴板路径；SPICE 显示与动态分辨率已完成当前 App 主路径的窗口跟随、冷启动恢复和重连验证，剪贴板和 TCP 鉴权有历史验收证据；本次客户端重构后的来宾正/负向 E2E 与跨用户连接仍是单独的待验收边界（见第 7 节与 `docs/ctflab-dynamic-resolution-design.md`）；
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

- [x] 固定首版 QEMU 版本、构建来源和许可证清单（2026-09-15 Task 6.3B：随包 QEMU 11.1.0，
  SBOM 记录 Homebrew 来源与逐文件哈希；项目 MIT、`dtc` vendored 文本、QEMU 书面要约见
  `docs/ctflab-task6-app-runtime-design.md` 第 6 节）。
- [x] 在 Mac M 上验证 `qemu-system-aarch64 -accel hvf`（2026-09-15 Task 6.3A：App 内 QEMU 在最小 PATH、宿主工具路径被拒绝的条件下完成 Kali 首次启动与重启）。
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
- [x] 实现截图 OCR/画面分类，区分登录界面、UEFI Shell、内核错误和无启动盘；缺少 OCR 时安全降级。
- [x] 实现受控的 BIOS/UEFI、IDE/SATA/SCSI/VirtIO 启动回退矩阵（2026-09-14：probe --matrix，白名单组合+画面分类续试，WebServer.ova 实测）。

**验收：** 使用 manifest 启动两台靶机；无效 manifest 或缺失镜像被清晰拒绝；未知镜像能生成带证据、置信度和人工复核状态的候选配置。

### Task 2：存储与生命周期

- [x] 实现基础镜像只读导入和 qcow2 overlay 创建。
- [x] 实现 QMP 优雅关机和超时强制停止。
- [x] 实现 reset 幂等性，并防止未加 `--force` 时删除运行中的 overlay。
- [x] 增加跨进程锁，防止并发启动、导入与 reset 竞争。
- [x] 为每个实例写入独立日志。

**验收：** 连续 20 次启动、停止、重置后，没有残留 QEMU 进程、QMP socket 或基础镜像改动；锁文件可以持久存在，但不得有锁被持有或阻塞后续操作（2026-09-14 实测：`locks/operations.lock` 存在但未持有，状态目录可正常获取操作锁）。

### Task 3：Kali 图形桌面

- [x] 支持从用户提供的 Kali ARM64 ISO 自动安装，记录源哈希；发行方签名仍需独立核验。
- [x] 配置 HVF、VirtIO 磁盘、双网卡、显示设备及独立可写 UEFI NVRAM。
- [x] 验证 XFCE 登录、键盘、鼠标、1920×1080 手动显示及 Firefox/Burp/Wireshark 主界面。
- [x] 验证 XFCE 登录、窗口缩放、键盘、鼠标和至少 1920×1080 显示。
- [x] 安装/验证 guest agent 的文本剪贴板：Mac↔Kali 双向（英文/中文/多行）、关闭通道不共享、重启后可用。
- [x] 动态分辨率：`run --display auto` 在 Kali 图形启动时自动选择 SPICE，内置客户端、`spicevmc`
  transport 与 XFCE 适配已验证窗口跟随、冷启动恢复和重连；无头模式不启动客户端，Smoke/Basic
  仍使用 Cocoa。旧 UTM 路径的历史失败记录保留在独立验证文档，不影响当前 App 主路径。
- [x] 明确显示窗口关闭策略：确认框 + ACPI 电源键，来宾确认后正常关机；不提供隐藏后台（需要后台请用 `--headless`）。

2026-09-07 历史记录：`--headless` 已实现，当时窗口关闭策略、动态缩放和剪贴板仍未验收；当时的 `--internet` 还是 Kali 独占维护模式。后续版本已改为 Kali 默认 user-mode NAT，GUI 可选择启动节点。`--from-runtime` 可保留旧盘并固化维护成果。独立重装实例已验证无需手工修复即可 DHCP/SSH 登录。Ghidra 已安装并出现项目窗口，但首次帮助页报错，不能列为完整工具验收通过。

2026-09-13 历史记录：剪贴板通过双向验收；窗口关闭/停止策略实测（图形会话下 ACPI 会先打开来宾确认框，未确认时 `stop --graceful` 超时保留实例，确认后来宾关机、QEMU 退出、CLI 清理状态与残留网络）。当时默认后端不支持动态分辨率，未冒充完成；当前 App 的 SPICE 主路径已在 2026-09-16 独立验证。Ghidra 帮助异常已定位为 Kali `+ds` 发行包缺少 JavaHelp 搜索索引，新增 `tools/guest_fixes/kali-arm64/ghidra_help_fix.py` 生成索引并补齐 Search 视图；连续两次启动无异常，项目/导入/反编译与帮助窗口通过。详见 `docs/verification-2026-09-13.md`。

**验收：** Kali 能稳定运行 Firefox、Burp Suite、Wireshark 和终端；图形窗口无持续高 CPU 占用或明显输入延迟。

### Task 4：实验网与 Kali 互通

- [x] 用回环 TCP socket 实现无 root 的 MVP 二层转发与最小 DHCP。
- [x] 为 Python MVP 交换机增加 MAC 学习、逐连接限速、状态计数与可选 PCAP。
- [ ] 将已验证的交换机能力迁移为独立 Go `ctflab-switch`。
- [ ] 制作可复现的 ARM64 路由器镜像及 DHCP、防火墙规则。
- [x] 固定 Kali、Smoke、Basic 的 DHCP 租约和 IP。
- [x] 修复 PCnet 对不足 60 字节以太帧的兼容问题；实验 DHCP 不再下发不存在的默认网关。
- [x] 实现 Kali 到两个靶机的 ICMP、TCP 和全端口扫描验证（2026-09-14 实测 0% 丢包、全端口开放清单记录）。
- [x] 验证靶机无法访问互联网（2026-09-14：restrict=on + 无上游交换机 + 无网关 + PCAP 无外部 IP）。
- [ ] 靶机对 Kali 的应用级回连（需要靶机内执行权限/凭据；帧级双向已在 PCAP 实证，应用级未做）。
- [x] 输出可选 PCAP（回环交换机已有实现与回归测试）。

**验收：** Kali 能对 `192.168.242.20` 与 `192.168.242.21` 执行 Nmap；Basic 的 HTTP 服务可达。靶机公网隔离已实测（已验证，2026-09-14）；靶机应用级主动回连 Kali 是未验证项（当前只有 ICMP/TCP 响应的帧级双向证据，需要靶机内执行权限/凭据），在完成并记录前不得暗示该项已通过。

### Task 5：Mac 主机访问

- [x] 实现无权限模式端口映射与状态展示。
- [ ] 完成 macOS 主机直连模式 PoC。
- [ ] 添加临时权限助手、明确授权提示和操作日志。
- [ ] 实现停止/异常退出后的路由、PF 规则与接口清理。
- [ ] 测试 Wi-Fi 切换、睡眠唤醒和 CTFLab 崩溃后的恢复命令。

**验收：** 无权限模式下 Mac 能访问 Basic Web 服务；直连模式下 Mac 能访问实验网 IP；停止后 `netstat`、路由表和 PF 规则无 CTFLab 残留。

### Task 6：封装与交付

- [x] 打包 `CTFLab.app`、受控 QEMU 运行时和所需动态库（2026-09-15：本地构建，含 aarch64/x86_64 QEMU
  + qemu-img + 28 个动态库闭包 + firmware/ROM/keymaps；未签名分发）。
- [x] 将运行时数据移出 `.app`，避免运行破坏签名（2026-09-15：状态/镜像/overlay/日志均在
  `~/Library/Application Support/CTFLab`；E2E 复核运行前后 app 树哈希一致）。
- [x] 修复所有动态库为 `@loader_path` 相对路径（2026-09-15：`install_name_tool` 改写 + 删除宿主
  LC_RPATH；打包后自检与 `otool -l` 全量扫描无 Homebrew/conda/用户路径）。
- [x] 生成 SBOM、许可证说明、SHA-256 和版本信息（2026-09-15：源码级安装包与两个内容包已生成
  `MANIFEST.json`/`SBOM.json`/`THIRD_PARTY_LICENSES.md`/`SHA256SUMS` 与 `.sha256` 旁车；
  Task 6.3B 又补齐项目 `MIT`、`dtc`/libfdt 文本和 QEMU `SOURCE_OFFER.md`，当前分发阻塞项为零）。
- [ ] 完成 Developer ID 签名、公证和实际新 macOS 用户验收；当前只完成 ad-hoc 签名、最小 PATH + 独立 HOME
  下的 `.app` 验证，接收者仍需手动放行一次。
- [x] 建立路线 A 基盘分发链：`dist prepare/verify` 生成 zstd 压缩基盘、NVRAM 模板、
  `DISTRIBUTION.json`、`SHA256SUMS` 与分发说明；`import --manifest/--expect-sha256` 强制校验来源并记录
  `image.json.source_verification`（2026-09-16，详见 `docs/verification-distribution-2026-09-16.md`）。
- [x] 用最终路线 A 分发目录中的三个压缩基盘完成 App 侧 Kali ARM64 + UEFI 29/29 E2E；目录校验、
  manifest 导入、NVRAM 自动附加、重启、隔离网络、停止与 reset 均通过（2026-09-16，证据目录：
  `~/Downloads/ctflab-dist-e2e-20260916/`）。
- [x] 构建 `smoke-1.0.0.ctflab` 与 `basic-pentesting-2-1.0.0.ctflab`（2026-09-15，内容包不含虚拟磁盘，
  已通过 `ctflab content verify`）。
- [x] 建立私有 GitHub 源码镜像 `zhangpu1211/ctf-lab`，仅同步 CTFLab 源码、配置模板与文档，不上传虚拟磁盘、凭据或课程数据。

**验收：** 在一台未安装开发依赖的 Mac M 上，用户可以安装 CTFLab、导入两份内容包并完成实验；不需要手工编辑 QEMU 参数。

2026-09-14 部分证据：模拟干净 HOME + 最小 PATH 下，doctor 依赖检测与提示正确，手工安装 PyYAML 后导入、启动、停止、重置全流程通过。这只证明“依赖缺失时提示正确、手工补齐依赖后可用”，**不构成**上述验收：独立安装包、签名与公证尚未交付，因此第 7 节对应验收项保持未通过（见 `docs/verification-2026-09-14.md` 第 3 节）。

2026-09-15（Task 6.1）证据：交付源码级安装包 `ctflab-0.1.0-macos-arm64.tar.gz`
（复核后 22 个登记文件，含 MANIFEST/SBOM/许可证清单/install.sh；精确 SHA-256 只记录在不入包的
独立验证记录中，避免包内文档与包自身哈希形成自引用）与两份内容包
`smoke-1.0.0.ctflab`、`basic-pentesting-2-1.0.0.ctflab`（均通过 `content verify`；**不含虚拟磁盘**）；
干净环境验收脚本在独立 HOME + 最小 PATH 下 13/13 步通过（校验/解包 → 执行 install.sh →
doctor 缺依赖提示 → venv 安装 PyYAML → doctor 就绪 → import → run --headless → health → stop →
reset → 无残留）。范围限制：`.app`、
受控 QEMU 运行时、动态库、签名与公证在该子任务产物中**尚未实现**；PyYAML 一步为联网 `pip install`，不是零手工
依赖的完整安装；项目许可证未声明（`undeclared`），对外分发前必须补充。详见
`docs/ctflab-task6-packaging-design.md` 与 `docs/verification-task6-1-2026-09-15.md`。

2026-09-15（Task 6.2）证据：交付含受控 QEMU 运行时的 `CTFLab.app` 本地构建
（树哈希 `2d5a950e…`，138 个登记文件，QEMU 11.1.0 arm64，ad-hoc 签名；
`CTFLAB_RUNTIME_ROOT` / `.app` 布局优先，PATH 仅作开发回退）。真实 E2E 在
最小 PATH（**不含 `/opt/homebrew/bin`**）下 15/15 步通过：doctor 显示 bundled 运行时 →
`sandbox-exec` 拒绝 `/opt/homebrew` 后 app 内 QEMU 仍可启动（固件来自 app）→ import → run →
health（DHCP+SSH）→ stop → reset → 无残留 → app 树哈希不变 → `codesign --verify --deep --strict`
返回 0（级别 ad-hoc，**公证未执行**）。**当时分发阻塞（Task 6.3B 后已闭环）**：项目许可证 `undeclared`、QEMU GPL 源码义务
未随附、`dtc` 许可证文本缺失（`missing-in-keg`）——禁止公开发布，详见
`docs/ctflab-task6-app-runtime-design.md` 与 `docs/verification-task6-2-2026-09-15.md`。

2026-09-15（Task 6.3A）证据：用含受控运行时的 `CTFLab.app` 完成 Kali ARM64 + UEFI 的
import/run/health/reboot/stop/reset 全链路（29/29 条记录通过）：最小 PATH（无 `/opt/homebrew/bin`）下
doctor 显示 bundled 运行时；`sandbox-exec` 拒绝 `/opt/homebrew` 后 App 内 QEMU + 固件仍可启动；
UEFI 首次与重启均到图形登录界面（独立截图经 OCR 登录专属信号与人工复核，未进入 UEFI Shell）；
派生 NVRAM 可写而 App 模板与用户原始 RAW NVRAM
哈希不变；Kali 在隔离网内可达 smoke/basic（HTTP 200）且无默认路由、公网不可达；重启后再次健康；
reset 后无残留、App 树哈希不变、`qemu-img check` 通过。过程中定位并修复 6.2 的
entitlement 丢失缺陷（HVF `HV_NO_DEVICE`），并在复核中收紧为 entitlement 键和值完全一致。
**仍未做** Developer ID 签名与公证。详见
`docs/verification-task6-3a-2026-09-15.md`。

2026-09-16（图形入口）证据：`CTFLab.app` 主入口改为原生 SwiftUI/AppKit（`Contents/MacOS/CTFLabGUI`），
CLI 保留在 `Contents/Resources/bin/{ctflab-cli,CTFLab}` 供开发与排障；学生双击 App 即可完成
“选择分发目录 → 校验 → 导入三个节点 → 选择一个节点 → 启动/停止所选节点 → 检查状态（健康）→ 重置（带确认框）”，
不再需要手输 import 命令。GUI 只调用既有 CLI（`dist verify --json`、`import <profile> <基盘> --manifest`、
`run`、`status --json`、`health --json`、`stop <profile>`、`reset <profile>`），启动所选节点时由 CLI 默认给 Kali
联网和 Cocoa 固定显示，为靶机保持隔离，不解析任意 QEMU 参数、不绕过清单哈希。`stop --all` 仅保留为 CLI 故障恢复命令。验证：GUI 单元测试（Swift 核心 + CLI JSON 契约 +
构建集成）与实机点击验证（校验通过/错误目录拒绝/导入完成/三节点启动并健康通过/停止无残留/重置确认）
见 `docs/verification-gui-2026-09-16.md`；**未做** Developer ID 签名与公证。

2026-09-15（Task 6.3B）证据：许可证闭环（项目 MIT + `LICENSE` 随包、`dtc`/libfdt 文本
vendored、QEMU 源码书面要约 `SOURCE_OFFER.md`，`distribution_blockers` 清零）与 `.app`
内置 Python 3.12.14 + PyYAML 6.0.3：最小 PATH + 独立 HOME 下首次 `doctor` 即 0 退出
（无 venv/pip/联网），`sandbox-exec` 拒绝宿主 Python 后仍通过；smoke E2E 15/15、
Kali ARM64 + UEFI E2E 29/29（含重启、隔离网连通性与 `qemu-img check`）；运行后 App 树
哈希不变、无 `__pycache__` 写入。同时修复 `_formula_version` 的 Cellar 层级缺陷与旧启动器
的字节码写入潜在缺陷。**仍未做** Developer ID 签名与公证、面向学生的基盘镜像分发渠道。
详见 `docs/verification-task6-3b-2026-09-15.md`。

## 7. 第一阶段验收清单与收口判定

以下清单区分“核心课堂版”与“延期能力/正式发布门槛”。核心课堂版项目全部达到“已验证”后，
Phase 1 核心课堂版即可收口；标为“部分验证 / 未验证 / 后续任务”的项目继续保留边界，不把它们
伪装成已完成，也不反向阻塞当前已验证的本地课堂主路径。每条只写一个主状态标签，位于复选框之后、说明冒号之前
（例如 `已验证：…`）：

- **已验证**：有验证记录中的实测证据；
- **部分验证**：核心路径有证据，但仍有明确边界未覆盖，不得当作已完成；
- **未验证**：没有证据；
- **后续任务**：依赖尚未交付的组件（如 Task 6 打包），当前不宣称完成。

- [x] 已验证：`ctflab run kali-arm64 smoke basic-pentesting-2` 可以一次启动三个已导入组件。
- [x] 已验证：Kali 显示完整 XFCE 图形桌面，Firefox/Burp/Wireshark 实际打开；深层工具功能和性能基准另行验收。
- [x] 已验证：2026-09-25 剪贴板专项，`--clipboard` 正/负向独立 E2E——负向（未开剪贴板）双向哨兵不泄漏；正向双向英文/中文/多行逐字节一致。宿主→来宾方向发现 quartz `owner-change` 缺陷（上游 spice-gtk 限制），已在受控客户端内以通道级实现修复。此项为历史结果；2026-10-05 生命周期重构已打入本地候选 App，新的桌面传输仍待重测，公开 Release 尚未更新。
- [x] 已验证：2026-09-25 未授权客户端拒绝，——TCP 回退模式下无 ticket/错误 ticket 客户端被 QEMU 拒绝（`Invalid password`），不建立通道；unix 模式无多余 TCP 监听。
- [ ] 部分验证：TCP 回退路径 B，URI 先于 password 的修复与隔离属性已落地；2026-10-05 无来宾磁盘的真实 QEMU 认证三轮通过，新客户端 runner 三轮认证/显示通道也通过（正确 ticket 返回 0、错误返回 7、display-ready=1）。未等待登录桌面，不能算完整 TCP 图形链路通过。默认仍为 unix socket；本地候选 App 的 UNIX 登录界面/DHCP/SSH/QEMU 退出后客户端自动关闭已两轮通过。
- [ ] 部分验证：2026-09-25 SPICE 全屏，`--fullscreen`/Shift+F11 已实现，全屏几何（无边框全屏尺寸置顶）实测达成；全屏尺寸动态分辨率跟随未通过（观察到客户端已发送 3024x1964 monitors config 而来宾 EDID 未出现对应模式、强制重探测无效；疑似 virtio-gpu 运行中 EDID 刷新行为，根因未证实）；交互切换端到端验收因桌面输入冲突未完成。
- [ ] 未验证：2026-09-25 起记录，长时间连续拖拽专项（宿主→来宾鼠标映射多次实测有效；持续拖拽被桌面输入冲突打断）、多显示器（本机单显示器）、跨 Mac 接收端（需第二台 Mac）。
- [ ] 部分验证：真实外来镜像向导 CLI 链路，WebServer.ova 的 inspect/onboard/probe 命令曾完成，但截图实际为 PXE，旧 network_and_display_candidate 不能证明磁盘引导。PXE 与未知画面矩阵误命中已修复；真实镜像需重新探测，GUI 点击级验收仍待补做。
- [x] 已验证：Kali 能扫描并访问两台靶机（2026-09-14 实测：ICMP 0% 丢包、全端口 Nmap 开放清单、Basic HTTP 200、SSH 横幅可达；见 `docs/verification-2026-09-14.md`）。
- [x] 已验证：Smoke 地址固定为 `192.168.242.20`，Basic 地址固定为 `192.168.242.21`。
- [x] 已验证：Mac 能通过无权限端口映射访问 Basic（HTTP 200 与 SSH 横幅，2026-09-14）。
- [ ] 后续任务：Mac 主机直连模式（Task 5 未实现；不阻塞当前 Phase 1 核心课堂版收口）。
- [x] 已验证：靶机无法访问公网（restrict=on、交换机无上游、DHCP 不下发网关、PCAP 无实验网外 IP，2026-09-14）。
- [ ] 未验证：靶机应用级主动回连 Kali（目前只有 ICMP/TCP 响应的帧级双向证据；应用级回连需要靶机内执行权限/凭据，未做；不阻塞当前 Phase 1 核心课堂版收口）。
- [x] 已验证：运行、停止、重置连续 20 次无残留进程或网络规则（2026-09-14 实测，20/20，基础镜像哈希不变）。
- [x] 已验证：`reset` 后靶机从基础镜像重新创建 overlay，基础镜像哈希未变化。
- [x] 已验证：新镜像可通过 `inspect → onboard → probe` 进入候选适配流程，并明确区分候选与已验证交付。
- [x] 已验证：Kali 与两个靶机均通过 DHCP 和已配置的 SSH/HTTP 协议健康检查。
- [x] 已验证：`.app` 已内置解释器、PyYAML、QEMU 与固件；在最小 PATH + 独立 HOME 下首次 `doctor` 无需 venv、pip 或联网，smoke E2E 15/15、Kali ARM64 + UEFI E2E 29/29 通过（见 `docs/verification-task6-3b-2026-09-15.md`）。
- [ ] 部分验证：在干净的 Mac M 用户环境完成安装、导入和运行。`.app` 已在最小 PATH + 独立 HOME 下完成零手工依赖验证；最终路线 A 分发目录也已通过全量哈希校验，并用三个压缩基盘完成 Kali 29/29 E2E。仍未测真实网盘下载/回传、真实新 macOS 用户安装，VulnHub 等第三方靶盘再分发条款也未逐个确认。Task 6.1 的 13/13 是源码级安装包验收，其中 PyYAML 仍需联网安装，不能与当前 `.app` 证据混称。
- [ ] 后续任务：Developer ID 签名、公证和新 macOS 用户/接收者验收；签名完成前，课堂交付只能按本地 ad-hoc 构建并说明首次手动放行。

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

**范围：** 本文第 2～8 节定义的 CLI、manifest、overlay、Kali 图形桌面、用户态交换机、健康检查、
Mac 端口映射、受控 QEMU/Python 运行时、许可证闭环和路线 A 分发链。路由器镜像、主机直连和正式签名分发
不作为当前课堂版的必要组件。

**退出条件：** 第 7 节核心课堂版项目全部达到“已验证”；内容包、运行时和基础镜像可被清晰区分；最终分发目录
可校验导入；停止后没有进程、路由或防火墙规则残留。正式签名、公证、真实新用户安装和可选网络能力另设发布门槛。

### Phase 1 收口：Mac M 课堂发布候选（2026-09-16 已完成）

**定位：** 这是 Phase 1 的交付收口，不是继续扩展运行器能力。核心课堂版已经形成可复核的发布候选；后续
只处理正式发布门槛或由课程需求触发的专项能力。

**收口结果：**

1. **已完成：** 冻结带版本号的 `.app` 与分发目录，保留 `app verify`、`dist verify`、哈希旁车和完整 E2E 证据；
2. **已完成：** 使用最终分发目录中的三个压缩基盘走完清单导入、NVRAM 自动附加、冷启动、重启、隔离网络、停止和
   reset；29/29 证据见 `/Users/pufei/Downloads/ctflab-dist-e2e-20260916/`；
3. **待正式发布前完成：** 在一次真实上传/下载或课程资料区回收后重新执行哈希校验，确认大文件、分卷重组和学生
   README 的路径可复现；
4. **待正式发布前完成：** 若要面向非开发用户发布，补 Developer ID 签名、公证和真实新 macOS 用户验收；在没有
   Apple 开发者身份时，
   保持 ad-hoc 作为受限试用交付，不把“手动放行一次”描述成正式发布；
5. **待正式发布前完成：** 逐项确认 Smoke、Basic Pentesting 2 等第三方靶盘的再分发授权；无法确认的条目改为学生自行下载，
   课程资料只提供来源、固定哈希和 `--expect-sha256` 路径。
6. **已明确边界：** 现有 Kali 基盘保留标准默认口令；当前 App 只给 Kali 的 QEMU user-mode NAT
   提供默认互联网出口，Smoke/Basic 管理网仍隔离，实验网仍只走回环交换机。若要接入物理网络，
   应先用 `CTFLAB_INSTALL_PASSWORD` 重装/固化新基盘，并在分发说明中明确该边界。

**当前不建议插入的工作：** 主机直连、Go 交换机迁移仍会扩大权限与网络风险；当前无权限端口映射已经满足
Kali→靶机和 Mac→靶机的已验证教学路径。SPICE 动态分辨率已进入默认 App 主路径；剪贴板隔离、客户端鉴权负向
E2E 和正式签名仍是发布前边界，Task 5、靶机应用级回连按明确课程用例和可逆夹具单独启动。
靶机应用级回连则应在有明确课程用例、两端均为自有靶机且有可逆验证夹具后单独验收，不能用现有 PCAP 帧级证据替代。

**收口门槛：** 当前课堂版已满足：`.app` 运行时零手工依赖证据、最终分发目录哈希可复核、三个压缩基盘完成真实
来宾 E2E、许可证/来源/来宾凭据边界写清、失败导入不写入状态，以及停止/重置无残留。真实下载、正式签名/公证、
第三方授权和可选网络能力继续留在第 7 节的“部分验证 / 未验证 / 后续任务”，不反向改变当前核心课堂版已收口的判定。

### Phase 2：单机体验完善与外部 Kali 兼容

#### 当前优先级：单靶机导入性能与容错（2026-10-10）

先完善单镜像接入，不立即开展多主机网络或 Docker 运行器。

- [x] 消除向导识别和正常 onboard 阶段重复的整盘哈希；正式 import 仍计算来源哈希和基盘哈希，接入报告使用正式登记摘要。`onboard --no-import` 保留独立来源哈希。
- [x] 已登记、来源与选盘一致的 OVA 重复导入先复核完整来源/基盘哈希，不再解包；旧记录仍走内容比对，换盘拒绝静默复用，多盘仍须显式选盘。
- [x] 同一次正常 OVA onboard 共用受控解包暂存，来源/选盘发生变化则拒绝，成功或失败均清理；正式来源哈希仍由 import 核验，不提供跨次可信缓存。
- [x] 解包按归档成员大小、转换按来源实际占用作最低空间预检，额外保留 64 MiB；压缩镜像膨胀和其他进程占用空间仍可能导致中途不足，不能承诺峰值充足。
- [x] 加入阶段进度、耗时与协作式安全取消/重试；失败不得污染已登记镜像。代码/专项验收通过范围见下，GUI 人工点击验收尚未执行。
- [x] 根据来源候选硬件证据和启动失败分类执行受控回退；人工确认后保存白名单固件/总线参数并备份原配置，候选保持未验收。代码、单元与独立合成盘 QEMU 验收通过；真实外来镜像与 GUI 人工确认流程仍待验收。
- [ ] 完整支持多磁盘顺序与依赖；以独立真实镜像测量冷导入/重复导入的读写量、耗时和峰值空间，不预先承诺提速比例。

**验收：** 来源和基盘哈希校验不减弱、重复导入不重转换、失败无半成品；同时记录性能结果与实际启动/服务验证范围。以上代码优化不等于任意 x86 镜像都可启动。

本轮受控实测使用合成单盘 OVA（虚拟 256 MiB、写入 128 MiB 非零数据），只导入独立临时状态目录，不启动虚拟机。
同一文件、同一已登记基盘、同一 Python 进程下各做 5 次重复导入，旧提交实现中位 200.589 ms，新实现中位 140.358 ms。
这是热缓存小样本约 30% 的耗时减少，不代表大镜像、冷缓存或端到端首次接入的通用提速比例。
完整来源与基盘哈希仍每次核验；新路径避免重复解包，`qemu-img check` 通过。
证据保存在本机 `/private/tmp/ctflab-import-perf-UwXAik/verification.md`，测试资产未入库。
2026-10-10 第一轮完整回归共 600 项：591 项通过、9 项按条件跳过（包含 Swift 核心与新增 7 项导入专项）；文档命令校验与 `git diff --check` 通过。改动尚未提交或打包覆盖已发布 App。

第二轮在同一合成 OVA 上各执行 3 次新状态目录的真实 onboard，旧提交中位 599.899 ms，新实现 455.895 ms，样本中约减少 24%；记录解包调用旧版每次 2 次、新版每次 1 次。
“新状态”指首次登记，不是清空系统磁盘缓存；不宣称大镜像端到端同比提速。GUI 独立的只读预览仍需单独解包，本轮复用范围仅限单次 onboard 内部，不引入跨命令缓存。
专项覆盖真实识别+转换共用暂存、来源变化/选盘变化拒绝、成功/失败清理、解包/转换最低空间不足；没有启动用户虚拟机，也未修改原始资产。
第二轮完整回归 606 项：597 项通过、9 项按条件跳过；新增 6 项受控暂存/空间专项，文档命令和 `git diff --check` 通过。仍未提交、推送或覆盖已发布 App。

第三轮增加解包、来源校验、转换、完整性检查、发布/登记的结构化进度。解包和哈希显示阶段字节百分比，转换仅显示阶段与经过时间，不伪造整体百分比或完成时间预测。
GUI 增加“取消当前导入”，与“停止后续导入”分开；只通过本次私有 0700 临时目录的取消标记协作通知 CLI，不强杀运行器或用户虚拟机。
转换取消时先终止并回收本次 qemu-img，再清理本次 partial；发布前接受取消，进入发布阶段后先完成登记再结束本项。短元数据读取、完整性检查或旧盘内容 compare 期间的请求在下一检查点处理，不承诺立即响应；SIGKILL/宿主掉电残留自动恢复尚未实现。
失败保留候选 YAML 与检测报告。向导同一来源/ID 的本次失败可再次点击导入重试；CLI 的 `onboard --resume` 只接受同来源、同选盘且未登记基盘的用户候选，不重新生成或覆盖 YAML，不允许对已登记节点重试。候选生成之前失败则按普通首次导入重试。
专项包含真实转换子进程取消/回收、OVA 暂存取消清理、提交阶段迟到取消仍完成登记，以及真实小 OVA“取消后重试”通过 qemu-img check；来源摘要与候选 YAML 保持不变。GUI 进度解析/命令规则自动验证，完整 GUI 编译验证；未操作桌面或运行虚拟机，人工按钮流程尚未验收，也未覆盖已发布 App。
2026-10-10 第三轮完整回归 614 项：605 项通过、9 项按条件跳过；新增 8 项取消/重试专项，Swift 核心增加完整/拆分进度行及重试参数断言。最后的界面重试状态修正另经完整 Swift 类型检查；Python 语法检查和 `git diff --check` 通过。回归日志：`/private/tmp/ctflab-import-round3-tests.log`。改动未提交、推送或发布。

第四轮（2026-10-11）完善启动回退与命中参数保存。用户候选优先尝试来源推断的固件、总线和控制器，仍只使用既有 BIOS/UEFI × SCSI/IDE/SATA/VirtIO 白名单。存储不足、锁冲突、资源不足、缺 QEMU 或未知启动错误停止后续尝试并给出提示；可回退的设备或固件错误继续下一个候选。UEFI Shell、PXE、无启动盘、内核错误均保留截图和排障建议；失败画面与已退出进程的旧登录截图不能选为成功候选。
矩阵入口拒绝正在运行的实例及已有 overlay/NVRAM，每轮使用新的运行盘和 NVRAM，停止并回收本轮子进程后清理；不能结束的实例保留现场并终止矩阵。报告绑定探测开始时的 profile 摘要、来源和基盘登记摘要，运行期间 profile 发生变化则拒绝生成可固化报告。
GUI 增加“确认保存命中参数”及二次确认；只在明确成功且包含报告路径时显示。保存时操作锁覆盖报告/配置/基盘复核、备份和原子替换；拒绝外部报告、过期报告、非白名单参数、已有运行盘、修改过的基盘及内置配置。只更新候选固件/磁盘参数，保留 candidate，并明确 boot_verified/service_verified 为 false。
独立合成空盘 QEMU 验收已执行：真实导入和 5 秒探测判为 no_boot_device，原基盘哈希不变、qemu-img check 通过、派生运行目录清理、QEMU/交换机进程结束；同时以 ResourceWarning 作为错误验证子进程回收。专项 34 项全部通过，证据：`/private/tmp/ctflab-matrix-round4-e2e-final.log`。该验证不证明外来镜像可启动或目标服务可用。GUI 自动规则和完整编译检查通过，人工按钮流程尚未执行；已发布 App 尚未替换。
2026-10-11 第四轮最终完整回归 636 项：626 项通过、10 项按条件跳过。其中独立合成盘验收在完整回归默认跳过，已通过上述显式运行补验；其余跳过涉及桌面 E2E、TCP/SPICE 特定运行时及已不存在的历史交付目录。语法检查、Swift 类型检查和 `git diff --check` 通过。最终回归日志：`/private/tmp/ctflab-import-round4-final-tests.log`。新增启动矩阵/候选保存专项共 22 项，包含基盘篡改、过期报告、失败画面、原子替换失败、外部配置修改与 CLI 参数混用。改动尚未提交、推送或发布。

2026-10-11 独立续验完成真实 Smoke/Acfun 导入取消与恢复、GUI 二次确认候选保存及本地候选打包；修复向导内进度/取消入口，最终回归 643 项、633 通过、10 跳过。三节点配套冷启动/协议就绪通过；原始资产保留、未发布。无 OCR 默认未知候选、并行状态端口和长 QMP 路径限制详见 [独立验收记录](verification-import-review-2026-10-11.md)。

2026-10-08 体验优化实施与逐项验收见 [体验记录](ctflab-ux-2026-10-08.md)：
自动刷新/分阶段显示、单节点显示恢复、导入冲突提示、GUI 快照备份、Kali 资源档位、
脱敏诊断已实施；登录后的桌面交互与 Developer ID/公证继续保留未验收状态，
不因单元测试通过升级为全部完成。

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
- [ ] 下载断点续传、校验、镜像缓存和可恢复导入（2026-09-16 部分实现：`ctflab dist prepare/verify`
  生成压缩基盘与 `DISTRIBUTION.json`/`SHA256SUMS`，`ctflab import --manifest/--expect-sha256`
  强制校验来源哈希并把证据写入 `image.json`；断点续传与镜像缓存未做。见
  `docs/ctflab-distribution-guide.md`）；
- [ ] 生成 SBOM、许可证清单、来源和完整性证明；
- [ ] 提供 PCAP 录制、基础流量筛选和靶场事件时间线；
- [ ] 提供实验说明、账号、入口、提示与一键恢复初始状态；
- [ ] 添加离线内容源，保证教学环境不依赖公网。

**退出条件：** 用户可以从可信目录导入课程靶场；每个内容包都能显示来源、哈希、许可和兼容性；离线环境仍可完成启动和重置。

### Phase 5：复杂拓扑与协作能力

2026-10-14 已完成 [Wintermute 双隔离网静态设计](ctflab-wintermute-scenario-design.md)：定义三节点场景清单、无来宾管理 NIC/NAT/hostfwd 的管理面、场景归属与故障恢复、整场景原子重置及正负验收矩阵。尚未实现或启动多网场景；Wintermute 只作先导，不替代下述“入口机 + 两台内部主机”阶段门槛。

#### 已纳入的多主机靶场与 Docker 联动路线（尚未实施）

这里的“内网”是靶场内部多主机、多网段拓扑，不是接入真实办公网络。
顺序为：单靶机导入性能/容错 → 纯 QEMU 双网段/多网卡场景 → Docker 混合场景。

1. 场景清单定义节点、隔离网段、多网卡、地址及启动依赖；入口机连接外围与内部实验网，Kali 默认不可直接访问内部网段，不隐式开启转发。
2. 场景级启动、健康检查、停止和重置只管理所属资源；部分启动失败明确保留状态，不影响其他场景或用户已有实例。
3. Docker Desktop 可选后端：校验受控 Compose 项目，记录 ARM64/amd64 兼容性，只管理 CTFLab 创建的容器和网络；默认拒绝特权、host 网络、Docker socket 与任意宿主路径挂载。
4. QEMU 与 Docker 通过受控网络通道联动；宿主两类网络并非天然互通，未经正/负向验收不宣称联动可用。

**分阶段验收：** 先完成至少一个入口机 + 两台内部主机的纯 VM 场景，再验证混合容器场景；逐路径验证应通/禁通矩阵、无公网和物理 LAN 出口、故障恢复及完整重置。多主机、Docker 均为后续任务，本轮不实现或开通网络。

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

在 Phase 1 收口及后续阶段，Phase 0 仍作为独立支持能力持续：每收到一个新镜像，先以 UTM 适配流程验证其可运行性，并把得到的硬件元数据沉淀进未来的 manifest 规则库。


### 2026-10-11 四项续验补记

单镜像导入后无 OCR 的截图人工确认已补受控入口，保存仍保留候选状态及备份；跨状态交换机占位/FD 交接与长 QMP/SPICE socket 私有短路径已进入本地 App。Acfun 新增独立适配配置和分发包，真实登录画面、DHCP/SSH、两轮正常关机再启动通过。最终 App 与既有三节点基盘本轮重新配套探测；不是新发布版本。证据、失败与未测范围见 [四项续验记录](verification-followup-acfun-2026-10-11.md)。其他待处理镜像、多主机网络和 Docker 不属于本轮完成范围。


### 2026-10-12 Acfun续验与长SPICE路径闭环

Acfun同实验网Kali真实SSH、30分钟闲置与三轮正常关机再启动通过。长SPICE路径进一步补齐运行状态、等待与重连的实际端点；真实包保持PID/磁盘的重连通过，正常关机确认超时保留现场并安全恢复。最终本地包校验通过，版本仍0.1.1、未发布。范围/失败/资源口径见 [2026-10-12验收](verification-acfun-continuation-2026-10-12.md)。未将闲置当成负载或跨设备验收。
