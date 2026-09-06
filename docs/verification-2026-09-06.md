# CTFLab Mac M 回归验证（2026-09-06）

## 环境

- 宿主：macOS Apple Silicon（arm64）
- 后端：Homebrew QEMU；x86_64 靶机使用 TCG 多线程
- 网络：仅绑定 `127.0.0.1` 的用户态二层交换机

## 启动与服务

| 节点 | 启动结论 | 图形画面 | 实验网地址 | 协议证据 |
|---|---|---|---|---|
| Smoke | `service_ready` | 非全黑、显示活动 | `192.168.242.20` | SSH 返回 `OpenSSH_10.0` 横幅 |
| Basic Pentesting 2 | `service_ready` | 非全黑、显示活动 | `192.168.242.21` | HTTP 80 返回 200 |

Basic Pentesting 2 仍存在原镜像内失效磁盘 UUID 导致的约 90 秒等待，最终服务正常。

## 交换机与 PCAP

使用以下方式同时启动两台靶机：

```bash
./tools/ctflab run smoke basic-pentesting-2 --headless --pcap
```

验证时交换机状态：

- 两个 QEMU 客户端均已连接；
- 学习到 Smoke 与 Basic 的两个固定 MAC；
- 两台机器均取得预设 DHCP 地址；
- PCAP 被系统识别为 Ethernet、PCAP 2.4，`tcpdump` 可解析 DHCP 与 IPv6 帧；
- 本次正常实验流量未触发每连接每秒 10000 帧的保护阈值。

执行 `ctflab stop --all` 后，两台 QEMU、交换机进程和 TCP 23400 监听均已清理。PCAP 作为用户生成的验证证据保留在状态目录，不提交到源码仓库。

## OCR 画面分类

- Smoke 的真实截图识别为 `boot_progress`，中等置信度；同时 SSH 与 DHCP 已就绪，因此最终仍为 `service_ready`；
- Basic Pentesting 2 的真实截图识别为 `login_ready`，高置信度，并单独记录 Tomcat9 启动失败文字；
- UEFI Shell、无启动设备和内核/根文件系统错误已通过确定性分类测试覆盖；
- 新版 `probe` 已对 Smoke 完成一次实际冷启动集成验证，报告包含 OCR 引擎、分类、置信度和命中信号，结束后自动清理进程。

## 尚未完成的验收

- Kali ARM64 镜像尚未导入，因此 Kali 图形桌面、对两台靶机扫描和反向连接仍待验证；
- 运行/停止/重置连续 20 次的耐久测试尚未完成；
- Mac 主机直连、Go `ctflab-switch`、应用打包、签名和干净账户测试尚未完成。
