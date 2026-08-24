# CTFLab 第一阶段：Mac M 本地运行器

第一阶段提供一个不依赖 UTM GUI 的 QEMU 运行器。它负责把镜像导入为只读基础镜像，启动时创建 qcow2 overlay，并让 Kali、Smoke、Basic Pentesting 2 加入同一个隔离实验网。

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

基础镜像保存在 `~/Library/Application Support/CTFLab/images/`，不会覆盖源文件。VMDK、QCOW2 和 OVA 均会先经 `qemu-img` 转成独立 QCOW2。

Kali 配置已经预置，但需要用户提供 ARM64 Kali 磁盘后再导入：

```bash
./tools/ctflab import kali /path/to/kali-arm64.qcow2
```

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

`probe` 会后台启动 QEMU，采集 QMP 状态、非全黑截图、DHCP 和已配置的 HTTP/SSH 协议证据，报告与截图保存在 `~/Library/Application Support/CTFLab/logs/probes/`。非全黑画面仍可能是 UEFI Shell 或内核错误；候选配置必须人工查看截图，确认登录或目标服务后才能标记为已验证。

## 3. 启动和访问

```bash
./tools/ctflab run smoke basic-pentesting-2
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

Basic Pentesting 2 会等待原镜像中一个失效磁盘 UUID 的 90 秒启动超时，冷启动约需两分钟；这属于来宾历史配置，不代表 QEMU 卡死。以 `health` 出现 `HTTP 200` 为可用标准。

## 4. 停止、重置和排错

```bash
./tools/ctflab stop --all
./tools/ctflab reset smoke
./tools/ctflab health basic-pentesting-2
tail -f "$HOME/Library/Application Support/CTFLab/logs/basic-pentesting-2.log"
```

`reset` 只删除运行 overlay，不删除导入的基础镜像，也不会触碰原始下载目录。第一阶段暂不创建 macOS 的 host-only 网卡，因此 Mac 侧采用端口映射；Kali 与靶机通过回环 TCP 二层交换机互通。后续阶段再补充可选的 Mac 主机直连模式，以及带 MAC 学习、限速和 PCAP 的正式交换机实现。

说明：`health` 中的 `tcp` 项只表示 QEMU 的主机端口映射已经建立，最终可用性以 `http` 等协议级检查为准；这是为了避免把 user-net 的监听端口误认为来宾服务已经启动。

## 5. 自动适配的能力边界

自动探测可以可靠读取格式、容量、VMDK/OVF 硬件元数据以及 MBR/GPT/EFI 证据，但普通磁盘文件通常不包含客体 CPU 架构、Linux 网卡名称、登录状态或目标服务清单。因此自动流程输出的是“候选配置”，不是万能启动保证。

出现以下情况时仍需按探测报告回退并制作可恢复的来宾修复副本：

- 进入 UEFI Shell：切换 BIOS/UEFI，核对启动顺序；
- 找不到根磁盘：回退 IDE、SATA、LSI SCSI 或 VirtIO；
- 启动但无 DHCP：核对网卡型号和来宾接口名；
- 显示活动但无登录/服务：人工查看 probe 截图与日志；
- 多磁盘、加密盘、RAID 或快照链：当前不能直接自动交付。
