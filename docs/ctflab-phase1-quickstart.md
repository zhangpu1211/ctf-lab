# CTFLab 第一阶段：Mac M 本地运行器

第一阶段提供一个不依赖 UTM GUI 的 QEMU 运行器。它负责把镜像导入为只读基础镜像，启动时创建 qcow2 overlay，并让 Kali、Smoke、Basic Pentesting 2 加入同一个隔离实验网。

## 0. 先选交付方式

- **课堂/学生**：用打包好的 `CTFLab.app`（内置 QEMU 与 Python，不需要任何环境）+
  课程分发目录里的压缩基盘与 `DISTRIBUTION.json`。完整步骤见
  [基盘分发指南](ctflab-distribution-guide.md)；首次打开 App 需在“系统设置 → 隐私与安全性”
  手动放行一次（本地 ad-hoc 构建，未做 Developer ID 公证）。
- **开发/本机维护**：按下文从源码运行。

```bash
# 学生侧（拿到分发目录后）
shasum -a 256 -c SHA256SUMS
CTFLab.app/Contents/Resources/bin/CTFLab import kali-arm64 kali-arm64-base.qcow2 --manifest DISTRIBUTION.json
CTFLab.app/Contents/Resources/bin/CTFLab run kali-arm64
```

## 1. 检查环境

```bash
cd /path/to/ctf-lab
./tools/ctflab doctor
./tools/ctflab list
```

本机当前使用 Homebrew QEMU；脚本会优先使用 `/opt/miniconda3/bin/python3`，因为其中已包含 PyYAML。

## 2. 导入现有镜像

```bash
./tools/ctflab import smoke /path/to/Smoke/smoke.qcow2
./tools/ctflab import basic-pentesting-2 /path/to/basic_pentesting_2/basic_pentesting_2-disk001.vmdk
```

拿到的文件附有分发清单时，导入会强制核对来源哈希（不一致拒绝导入），并自动套用配套的
UEFI NVRAM 模板：

```bash
./tools/ctflab import kali-arm64 kali-arm64-base.qcow2 --manifest DISTRIBUTION.json
./tools/ctflab import smoke smoke-base.qcow2 --expect-sha256 <sha256>
./tools/ctflab import kali-arm64 kali-arm64-base.qcow2 --nvram kali-arm64-uefi-vars.fd
```

校验结果写入 `~/Library/Application Support/CTFLab/images/<id>/image.json` 的
`source_verification` 字段；重复导入同一文件是幂等的，不会覆盖已验证的基盘。

基础镜像保存在 `~/Library/Application Support/CTFLab/images/`，不会覆盖源文件。VMDK、QCOW2 和 OVA 均会先经 `qemu-img` 转成独立 QCOW2。

Kali 可以导入现有 ARM64 磁盘，也可以从 ARM64 安装 ISO 创建：

```bash
./tools/ctflab import kali /path/to/kali-arm64.qcow2
```

### 从 Kali ARM64 ISO 安装

安装器要求含 `install.a64/vmlinuz` 与图形安装 initrd 的 Kali/Debian 风格 ARM64 ISO；不是任意 Live ISO。原 ISO 只读，目标盘默认虚拟容量 64GiB；默认配置 4 核、5120MiB、HVF、VirtIO 和独立 UEFI NVRAM。

在 macOS 默认 zsh 中，先交互读取本地安装口令（不进入命令历史）：

```zsh
read -rs 'CTFLAB_INSTALL_PASSWORD?设置 Kali 本地口令：'; echo
export CTFLAB_INSTALL_PASSWORD
./tools/ctflab install kali-arm64 /path/to/kali-installer-arm64.iso --unattended --headless
unset CTFLAB_INSTALL_PASSWORD
./tools/ctflab install-status kali-arm64 --log-tail
# 等安装正常完成并自动退出后：
./tools/ctflab finalize-install kali-arm64 --confirm
./tools/ctflab probe kali-arm64 --timeout 180
./tools/ctflab run kali-arm64
```

登录用户名是 `kali`，口令使用安装时输入的值。安装资产含本地口令，仅保存在权限受限的状态目录，不能公开分发。ISO 的 SHA-256 被记录，但这不等同于验证发行方签名。现有本机验收实例不受新安装口令参数影响。

`stop-install` 保留安装盘；`install --resume` 重新启动安装器，并非断点恢复。无人值守重新启动会重新分区，必须再传 `--confirm-reinstall`；不要对需要保留的安装成果执行此操作。`finalize-install` 只登记候选基盘，仍需实际登录与网络验收。

### 软件维护与固化

离线 ISO 已提供 XFCE、Firefox、Wireshark、Nmap、Metasploit 等；Burp/Ghidra 是否包含取决于 ISO。本机测试另行通过 Kali 官方仓库安装了 Burp Community 与 Ghidra。

```bash
./tools/ctflab stop --all
./tools/ctflab run kali-arm64 --internet
# 在 Kali 中维护软件；需要 apt 源时参考 tools/guest_fixes/kali-arm64/kali.sources
# 维护完成后先在 Kali 内正常关机，再执行：
./tools/ctflab stop kali-arm64
./tools/ctflab finalize-install kali-arm64 --from-runtime --confirm
./tools/ctflab run kali-arm64 smoke basic-pentesting-2
```

联网维护仅允许单独 Kali，不能同时启动靶机。默认运行不允许公网访问；实验 DHCP 不下发不存在的网关，Kali 禁用 IP 转发。联网模式仅用于可信软件维护，不能连接未知靶机。

`--from-runtime` 展平当前 overlay 为新只读基盘，归档原运行目录并保留旧基盘；这样后续 `reset` 不会丢失已固化的软件。务必先正常关机，不能把强制停止等同于文件系统已干净卸载。归档会额外占用磁盘空间。

图形界面由 QEMU 独立窗口提供，`--headless` 不打开窗口。已验证 1920×1080 手动分辨率、键鼠和 XFCE、文本剪贴板双向复制、窗口关闭/停止策略，以及 Ghidra 项目/导入/反编译工作流；默认 Cocoa 路径的动态分辨率仍受 QEMU 后端限制（窗口只做缩放），尚未交付。新版内置 SPICE 的 App 配合 Kali 显示适配，已验证窗口尺寸跟随；旧课堂分发基盘仍需更新，3D 加速未验收，不能承诺与商业虚拟机相同体验。详见[2026-09-13 图形体验验证](verification-2026-09-13.md)、[联网与动态分辨率验证](verification-display-network-2026-09-16.md)与[动态分辨率设计](ctflab-dynamic-resolution-design.md)。

### 2.1 接收新的未知镜像

先执行只读探测。该命令会读取 `qemu-img` 信息、VMDK 描述符、相邻或 OVA 内的 OVF、MBR/GPT/EFI 分区签名，并为架构、固件、磁盘和网卡分别给出置信度：

```bash
./tools/ctflab inspect /path/to/new-machine.ova
./tools/ctflab inspect /path/to/new-disk.vmdk --json
```

确认候选结论后，生成白名单配置并导入派生 QCOW2：

```bash
./tools/ctflab onboard /path/to/new-machine.ova \
  --id new-machine \
  --name "New Machine"
```

如果来源文件无法提供可靠架构证据，应依据发布说明显式覆盖，而不是依赖低置信度默认值：

```bash
./tools/ctflab onboard /path/to/kali-arm64.qcow2 \
  --id kali-course \
  --architecture aarch64 \
  --firmware uefi
```

`onboard` 自动分配实验网 IP/MAC，但不会猜测来宾服务端口，也不会覆盖已有配置。导入完成后执行启动探测：

```bash
./tools/ctflab probe new-machine --timeout 180
```

`probe` 会后台启动 QEMU，采集 QMP 状态、截图、DHCP 和已配置的 HTTP/SSH 协议证据，报告与截图保存在 `~/Library/Application Support/CTFLab/logs/probes/`。若本机装有 Tesseract，还会通过 OCR 将最终画面分类为登录就绪、UEFI Shell、内核/根文件系统错误、无启动设备、启动中或未知：

```bash
brew install tesseract
./tools/ctflab probe new-machine --timeout 180
```

OCR 结果会记录置信度、命中信号、识别文本和局部服务失败警告。字体、语言和分辨率仍可能造成误识别；候选配置即使出现登录界面也必须人工查看截图，确认登录或目标服务后才能标记为已验证。若识别到 UEFI Shell、内核错误或无启动设备，且没有协议级服务证据，`probe` 会返回失败结论。

## 3. 启动和访问

```bash
./tools/ctflab run smoke basic-pentesting-2
# 需要用 Wireshark/tcpdump 分析实验流量时：
./tools/ctflab run smoke basic-pentesting-2 --pcap
./tools/ctflab status
./tools/ctflab health basic-pentesting-2
./tools/ctflab health smoke
```

运行器会启动仅绑定 `127.0.0.1` 的用户态二层交换机/DHCP 服务；QEMU 通过 `tcp://127.0.0.1:<实验端口>` 接入，流量不会进入物理局域网，也不需要管理员权限。当前固定地址如下：

| 节点 | 实验网地址 |
|---|---|
| Kali ARM64 | `192.168.242.10` |
| Smoke | `192.168.242.20` |
| Basic Pentesting 2 | `192.168.242.21` |

Kali ARM64 镜像导入后，会与两台靶机处于同一二层网络，可直接扫描上述地址。Mac 不直接加入隔离网，而是通过受控端口映射访问：

| 节点 | 来宾端口 | Mac 地址 |
|---|---:|---|
| Smoke | SSH 22 | `127.0.0.1:12220` |
| Basic Pentesting 2 | HTTP 80 | `127.0.0.1:18080` |
| Basic Pentesting 2 | SSH 22 | `127.0.0.1:12221` |
| Kali | SSH 22 | `127.0.0.1:12210` |

Kali 图形窗口由 `qemu-system-aarch64` 打开；x86 靶机也会各自打开 QEMU 窗口，但它们的主要用途是提供网络服务。若只做后台验证，可以使用 `--headless`，日志在 `~/Library/Application Support/CTFLab/logs/`。

实验网会学习来宾 MAC，仅把已知单播发往目标端口；广播、组播和未知单播仍按二层交换规则转发。每个来宾默认限制为每秒 10000 帧，超出部分会丢弃并显示在 `status` 的 `dropped` 计数中。使用 `run --pcap` 后，抓包写入 `~/Library/Application Support/CTFLab/pcap/`；PCAP 可能包含实验口令或利用流量，不应直接公开分发。

Basic Pentesting 2 会等待原镜像中一个失效磁盘 UUID 的 90 秒启动超时，冷启动约需两分钟；这属于来宾历史配置，不代表 QEMU 卡死。以 `health` 出现 `HTTP 200` 为可用标准。

## 4. 停止、重置和排错

桌面使用建议先保存工作，再执行 `./tools/ctflab stop kali-arm64 --graceful`。该模式只发正常关机请求（ACPI 电源键），等待最多 30 秒；若来宾未退出则报错并保留运行实例，不发强制退出或进程终止信号。不带该选项的 `stop` 保持旧行为，短暂等待后可能强制退出。

Kali 图形会话处于活动状态时，ACPI 电源键会打开来宾自己的关机确认框；用户未确认时来宾不会关机，`--graceful` 因此会超时并保留实例。此时可在 QEMU 窗口中确认关机，或先在来宾里正常关机，再执行不带 `--graceful` 的 `stop` 结束进程并清理状态。

不要用 Cocoa 窗口红色关闭按钮代替来宾关机：关闭窗口会先弹 “Are you sure you want to quit QEMU?” 确认框，确认后 QEMU 发送 ACPI 电源键，但仍需要来宾确认并在来宾退出后才会结束；窗口关闭后无法重新显示同一实例。后台使用应从一开始选择 `--headless`。

### 图形体验增量（2026-09-13）

`run` 的 Cocoa 窗口默认启用 `zoom-to-fit`，把画面缩放到窗口大小；这是缩放，不是来宾改变分辨率。当前 QEMU 11.1 + cocoa + virtio-gpu 没有让来宾分辨率跟随窗口的通道（QMP `display-update` 已不接受 EDID，vdagent 只支持剪贴板和鼠标）。默认路径仍需在来宾内用 XFCE 显示设置或 `xrandr` 选择分辨率，窗口会按比例缩放。新版 App 可显式使用 `run kali-arm64 --display spice`：内置 SPICE 客户端配合 Kali XFCE 自启动适配，已验证两档窗口尺寸的实际 `xrandr` 跟随及冷启动恢复；旧分发基盘需先补装显示适配，剪贴板负向与未授权客户端拒绝仍待专项验收。见[联网与动态分辨率验证](verification-display-network-2026-09-16.md)与[动态分辨率设计](ctflab-dynamic-resolution-design.md)。

文本剪贴板用 `run kali-arm64 --clipboard` 显式开启：默认关闭，仅对 Kali 图形模式生效，不为靶机创建通道；需要来宾已登录图形会话（`spice-vdagent` 是会话级进程），不能与 `--headless` 同用，切换需先停止再启动。已验收英文、中文和多行文本的双向复制粘贴（内容逐字节一致）、关闭通道后不共享、重启后仍可用。开启期间 Kali 能读到复制的文本，请勿复制个人密码或其他敏感内容。

Ghidra 的帮助异常（JavaHelp `view is invalid`）来自 Kali `ghidra` 发行包缺少搜索索引：可用
`sudo python3 tools/guest_fixes/kali-arm64/ghidra_help_fix.py` 修复（用 Ghidra 自带索引器生成搜索索引并补齐 Search 视图；先在临时文件里构建完整 JAR 再原子替换，中途失败不会留下半修复的 JAR；脚本可重复执行，原始 helpset 备份在 `/var/tmp/ctflab-ghidra-backup/`）。修复写在运行 overlay 中，`reset kali-arm64` 会丢弃；需要固化时先正常关机，再执行 `./tools/ctflab finalize-install kali-arm64 --from-runtime --confirm`。

`status` 会报告“进程已退出但状态文件残留”的实例和没有实例的残留实验网；`stop --all` 会一并清理。

```bash
./tools/ctflab stop --all
./tools/ctflab reset smoke
./tools/ctflab health basic-pentesting-2
tail -f "$HOME/Library/Application Support/CTFLab/logs/basic-pentesting-2.log"
```

`reset` 只删除运行 overlay，不删除导入的基础镜像，也不会触碰原始下载目录。第一阶段暂不创建 macOS 的 host-only 网卡，因此 Mac 侧采用端口映射；Kali 与靶机通过回环 TCP 二层交换机互通。当前 Python 交换机已具备 MAC 学习、限速和 PCAP，后续仍会迁移为独立的 Go `ctflab-switch`，并补充可选的 Mac 主机直连模式。

导入、候选配置生成、启动、停止和重置由状态目录中的内核文件锁串行化。两个终端同时修改运行状态时，后发命令最多等待 10 秒；仍未取得锁会显示当前占用进程和操作，且不会删除或覆盖对方的中间文件。锁由操作系统随进程退出自动释放，不需要手工清理锁文件。

说明：`health` 中的 `tcp` 项只表示 QEMU 的主机端口映射已经建立，最终可用性以 `http` 等协议级检查为准；这是为了避免把 user-net 的监听端口误认为来宾服务已经启动。

## 5. 自动适配的能力边界

自动探测可以可靠读取格式、容量、VMDK/OVF 硬件元数据以及 MBR/GPT/EFI 证据，但普通磁盘文件通常不包含客体 CPU 架构、Linux 网卡名称、登录状态或目标服务清单。因此自动流程输出的是“候选配置”，不是万能启动保证。

出现以下情况时仍需按探测报告回退并制作可恢复的来宾修复副本：

- 进入 UEFI Shell：切换 BIOS/UEFI，核对启动顺序；
- 找不到根磁盘：回退 IDE、SATA、LSI SCSI 或 VirtIO；
- 启动但无 DHCP：核对网卡型号和来宾接口名；
- 显示活动但无登录/服务：人工查看 probe 截图与日志；
- 多磁盘、加密盘、RAID 或快照链：当前不能直接自动交付。
