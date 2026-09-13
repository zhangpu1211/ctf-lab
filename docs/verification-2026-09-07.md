# Kali ARM64 安装与互通验证（2026-09-07）

## 输入与环境

- macOS Apple Silicon，16GiB 宿主内存，Homebrew QEMU 11.1.0。
- 用户提供 `kali-linux-2026.2-installer-arm64.iso`，大小 3972624384 字节。
- 原 ISO SHA-256：`b9a08050ee522fbee7cac703b1bc48178f79eb974c962d4ed9dc1ccfdfa77fb6`。
- 原 ISO 未改写；安装写入派生 QCOW2，运行时使用 overlay。
- Kali：aarch64/HVF、4 核、5120MiB、64GiB 虚拟磁盘、VirtIO GPU/双网卡、独立 UEFI NVRAM。
- 哈希只证明本次输入一致性，未独立验证发行方签名，不宣称来源认证完成。

## 自动安装与冷启动

主实例完成图形安装与维护后，使用独立 `validation-kali` 状态目录重新执行无人值守全流程。新实例的来宾初始化模板自动配置双网卡与 SSH，无需人工修网卡或启用服务。

- 安装日志正常进入系统重启，QEMU 因 `-no-reboot` 退出。
- 独立实例基盘 SHA-256：`ab50e93160181d31fab14fc1c9dee01aeb9958c09ff047f299f76585a86d91df`。
- 从该基盘冷启动，probe 返回 `service_ready`。
- SSH 实际登录成功；`eth0=192.168.242.10/24`，`eth1=10.0.2.15/24`。
- NetworkManager 活动连接为 `ctflab-lab`、`ctflab-mgmt`；`systemctl is-enabled ssh` 返回 `enabled`。
- SSH 横幅：`OpenSSH_10.3p1 Debian-4`。
- 完成后在来宾正常关机，停止独立测试实例。

最终源码不内置安装口令，改为 `CTFLAB_INSTALL_PASSWORD` 输入；该输入校验、initrd 注入和来宾模板有单元测试。完整重装验证发生在口令输入接口调整之前，同一 preseed 安装机制已实测；没有再次以最终接口重装整套系统。

## 图形软件

XFCE 登录、键鼠、终端和 1920×1080 手动分辨率通过。Firefox ESR 140.11、Wireshark 4.6.6、Burp Community 2026.8 均进入实际主界面。Burp 与 Ghidra 通过 Kali 官方软件仓库补装，`dpkg --audit` 无输出。

Ghidra 12.1.2 项目管理窗口可显示，但首次 What's New 帮助页触发 JavaHelp `IllegalArgumentException: view is invalid`。关闭错误弹窗后主窗口仍在；未验证二进制导入/反编译，不标记完整可用。

截图保留在本机状态目录 `logs/kali-firefox-wireshark.png` 与 `logs/kali-tools-final.png`，不上传运行截图或日志。未量化图形延迟、持续 CPU 或与其他虚拟机软件的性能差异；剪贴板、动态分辨率、3D 加速仍未验收。

## 实验网与服务

三个实例以默认隔离模式同时运行，交换机仅监听回环地址。

| 检查 | 实际结果 |
|---|---|
| Kali → Smoke ICMP | 3 发 3 收，0% 丢包 |
| Kali → Basic ICMP | 2 发 2 收，0% 丢包 |
| Kali → Smoke TCP 22 | 收到 `SSH-2.0-OpenSSH_10.0` |
| Kali → Basic HTTP 80 | HTTP 200，Apache/2.4.18 |
| Mac → Smoke 健康检查 | DHCP、SSH 成功 |
| Mac → Basic 健康检查 | DHCP、HTTP 200 成功 |
| Kali IPv4 转发 | `/proc/sys/net/ipv4/ip_forward` 为 0 |
| 默认隔离 Kali 访问公网 | HTTPS 请求 DNS 超时，未连接公网 |

Smoke PCnet 原先丢弃 VirtIO 发出的 42 字节 ARP。实际对比发现补至 60 字节后立即响应；交换机现在统一补齐短帧，并有 socketpair 回归测试。默认 DHCP 不再下发并不存在的实验网网关。

公网失败仅记录该次 Kali 请求，不把它当成对所有出站通道的形式证明。靶机主动回连 Kali、靶机内部出站阻断仍未单独验收。

## 验证边界

2026-09-13 续验：34 项单元测试、Python 语法检查和 `git diff --check` 全部通过。Kali 再次从既有运行盘冷启动，SSH 实际登录成功，ARM64 架构、双网卡地址和四个图形软件安装版本均仍正确；随后执行来宾正常关机。此前全端口扫描因任务中断未收回最终结果，因此不记录为通过。

正常关机后执行 `finalize-install --from-runtime --confirm`，新基盘 SHA-256 为 `ca1034606a82a7fa8372d23ab42ce8286638a0fadb247a141cc4f72d00c5a915`。旧基盘及运行盘保留在本地归档。随后从新基盘创建全新 overlay，probe 再次返回 `service_ready`，DHCP 与 SSH 成功；人工检查截图确认为 Kali 图形登录界面，而非 UEFI Shell。SSH 登录再次确认四个图形软件版本保留。验收实例最后正常关机，未保持联网维护模式。

已实现的运行器、安装器、网络修复不代表任意新 ISO/磁盘必定启动。受控硬件回退、20 次生命周期耐久、Go 交换机、外部 Kali 接入、Mac 主机直连、签名安装包和干净账户测试继续按路线图推进。主机访问实验服务目前使用回环端口映射。
