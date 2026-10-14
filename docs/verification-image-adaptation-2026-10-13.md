# 待处理镜像逐台适配（2026-10-13）

> 历史验收快照（本轮日期：2026-10-13）；不替代当前软件状态。初始服务通过与原盘缺件候选分开记录。

## 范围与入口

正式源码 /Users/pufei/Downloads/ctf-lab，HEAD 941db31114dbe811abadf46729295a72ec4bb30c。使用镜像库已发布 v0.1.1-preview.20261012 的包内 CLI；本阶段未改运行实现、未重新打包软件、未提交/推送/发布。原 OVA 保持只读，镜像库旧基盘不改动。用户确认本轮桌面空闲，只授权本轮独立实例。

证据根 `/Users/pufei/Downloads/ctflab-image-adaptation-20261013`。inventory.json/原 OVF 记录 18 个来源；Acfun 的 OVA 完整哈希与此前适配来源一致，不重复适配；Smoke OVA 与既有基盘虚拟内容不同，另存独立版本。各节点独立 profile、state、recipient 和 DHCP 地址；生命周期通过文件锁串行，后台磁盘准备互不共享可写状态。不连接物理 LAN、不登录或破解目标。

## 方法与真实证据

包内 onboard 导入、真实 qemu-img 转换/check；离线在临时派生 RAW 分区中恢复 ext4 日志并对明确不匹配的接口名作最小修改。debugfs/e2fsck 不作用于原盘；原接口配置保留在派生来宾 /etc/network/interfaces.ctflab-original。不改账户、服务、漏洞和挑战内容。临时转换工作目录自动回收，原始输入及持久证据保留。

实验网核验通过仅连接 `127.0.0.1:<独立交换机端口>` 的临时以太网测试客户端进行，源 IP .250，仅向本轮指定靶机发送 ARP/TCP 与只读 HTTP 请求；不改宿主网络、不新增监听、不跟随外部重定向。保存第一协议行、页面标题和摘要，剔除 HTTP cookie 等无关会话数据。未返回协议的开放端口只记为 TCP 开放，不认定已完成应用验证。

每台两轮启动/截图/服务/正常关机，独立查看实际 PNG 后才能制作包，再用新 recipient 状态安装内容包、冷启动和正常停止。保留失败/跳过/未验证，不把窗口或进程存活当作可用。来源 OVA 前后完整 SHA 一致才收口。

可重复入口：证据根下 adapt_network_disk.py、lab_service_probe.py、lifecycle_accept.py、package_verified.py、batch_adapt.py；使用包内 CLI 和独立路径，重跑前应新建状态，不能覆盖已存在的产物或沿用旧 PID。

## 本轮交付

新增17个自包含内容包：16个通过启动/网络/初始服务范围，NoPort单列兼容候选；Acfun复用既有包。每个新包完成两轮测试及新接收方安装后一次冷启动/正常停止，共51轮正式生命周期（诊断/失败轮另记，不混入）。

| 节点/内容包目录 | 实验网 IP | 内存/vCPU/网卡 | 实际初始服务 | 状态 |
|---|---|---|---|---|
| Base-20261013 | 192.168.242.40 | 1024MiB/1/e1000 | 22 SSH-2.0-OpenSSH_8.4p1 Debian-5+deb11u3；80 HTTP/1.1 200 OK；PivotX Powered | 启动/初始服务通过 |
| Bruteforce-20261013 | 192.168.242.41 | 2048MiB/1/e1000 | 22 SSH-2.0-OpenSSH_8.4p1 Debian-5+deb11u3；80 HTTP/1.1 200 OK；Service Unavailable | 启动/初始服务通过 |
| Busybox-20261013 | 192.168.242.42 | 1024MiB/1/e1000 | 22 SSH-2.0-OpenSSH_8.4p1 Debian-5+deb11u3；80 HTTP/1.1 200 OK；HACKED BY 0xWRATH | 启动/初始服务通过 |
| CPDD-20261013 | 192.168.242.43 | 1024MiB/1/e1000 | 22 SSH-2.0-OpenSSH_8.4p1 Debian-5+deb11u3；80 HTTP/1.1 200 OK；欢迎页；21 220 (vsFTPd 3.0.3)；3306 MariaDB访问限制响应；445 TCP开放（未验应用协议）；139 TCP开放（未验应用协议） | 启动/初始服务通过 |
| Config-20261013 | 192.168.242.44 | 1024MiB/1/e1000 | 22 SSH-2.0-OpenSSH_8.4p1 Debian-5+deb11u3；80 HTTP/1.1 200 OK；ConfigMaster - 智能运维配置管理平台 | 启动/初始服务通过 |
| Gost-20261013 | 192.168.242.45 | 2048MiB/1/pcnet | 80 HTTP/1.1 200 OK；Dashboard - Maze Cyber Ops | 启动/初始服务通过 |
| Grav-20261013 | 192.168.242.46 | 1024MiB/1/e1000 | 22 SSH-2.0-OpenSSH_8.4p1 Debian-5+deb11u3；80 HTTP/1.1 200 OK；Innovate - Your Digital Partner | 启动/初始服务通过 |
| Language-20261013 | 192.168.242.47 | 1024MiB/1/e1000 | 22 SSH-2.0-OpenSSH_8.4p1 Debian-5+deb11u3；80 HTTP/1.1 200 OK | 启动/初始服务通过 |
| Magic-20261013 | 192.168.242.48 | 1024MiB/1/e1000 | 22 SSH-2.0-OpenSSH_8.4p1 Debian-5+deb11u3；80 HTTP/1.1 200 OK；XML Processor；445 TCP开放（未验应用协议）；139 TCP开放（未验应用协议） | 启动/初始服务通过 |
| Merge-20261013 | 192.168.242.49 | 1024MiB/1/e1000 | 22 SSH-2.0-OpenSSH_10.0p2 Debian-7+deb13u1；80 HTTP/1.1 200 OK；离线IP地址查询 | 启动/初始服务通过 |
| NoPort-20261013 | 192.168.242.50 | 1024MiB/1/e1000 | 22 SSH-2.0-OpenSSH_8.1；80 HTTP/1.1 200 OK；Login | 兼容候选，原规则缺件 |
| Pane1-20261013 | 192.168.242.51 | 1024MiB/1/e1000 | 22 SSH-2.0-OpenSSH_8.4p1 Debian-5+deb11u3；80 HTTP/1.1 200 OK；运维管理面板 | 启动/初始服务通过 |
| Poppins-20261013 | 192.168.242.52 | 1024MiB/1/e1000 | 22 SSH-2.0-OpenSSH_8.4p1 Debian-5+deb11u3；80 HTTP/1.1 200 OK；Mary Poppins - A Timeless Classic；110 +OK Dovecot (Debian) ready. | 启动/初始服务通过 |
| Smoke-OVA-20261013 | 192.168.242.56 | 1024MiB/1/pcnet | 22 SSH-2.0-OpenSSH_10.0；80 HTTP/1.1 200 OK (Host: smoke.dsz)；SmokePing Latency Page for Network Latency Grapher；21 220 (vsFTPd 3.0.5) | 启动/初始服务通过 |
| Space-20261013 | 192.168.242.53 | 1024MiB/1/e1000 | 22 SSH-2.0-OpenSSH_8.4p1 Debian-5+deb11u3；80 HTTP/1.1 200 OK；Typing Challenge | 启动/初始服务通过 |
| Translate-20261013 | 192.168.242.54 | 1024MiB/1/e1000 | 22 SSH-2.0-OpenSSH_8.4p1 Debian-5+deb11u3；80 HTTP/1.1 200 OK；我的页面 | 启动/初始服务通过 |
| Watcher-20261013 | 192.168.242.55 | 1024MiB/1/e1000 | 22 SSH-2.0-OpenSSH_10.0p2 Debian-7+deb13u1；5000 HTTP/1.0 200 OK (/login)；Maze_Sec - Login | 启动/初始服务通过 |

内容包位于 `/Users/pufei/Downloads/CTFLab-Library/02-已处理` 的独立子目录，使用目录索引选择单包，不改顶层既有三节点清单。

## 失败与取舍


- Base 原盘能启动到登录提示，但 QEMU 网卡名 ens3 与原 enp0s3 不符，未取得 DHCP。离线派生盘只修正接口名，网络恢复。原盘 journal 未落盘，首次在恢复日志之前修改会被日志回放覆盖；后续流程固定先恢复日志再修改，并以只读 e2fsck 通过为准。
- 一份 Base probe 在仍采集时被本轮提前正常停止，报告为 qemu_exited；该记录保留，不作为通过证据。另行串行生命周期与接收方复验通过。
- Base 接收方首次截帧早于控制台就绪，画面全黑；此记录不算显示通过。新 recipient-r2 等待后捕获真实登录提示并核验服务、正常停止。
- 初次 Base make-pack 输入 YAML 文件名与 id 不符，被拒绝；更正文件名后通过，没有覆盖原资产。
- Gost 第一分区是启动分区，自动修改在缺少接口配置时中止；实际第三分区为 Alpine 根，eth0 原配置即可联网，未离线修改来宾。
- 维护页/初始页面标题按原镜像记录；未擅自修复或替换挑战内容。


- NoPort 原 SCSI 路径进入 initramfs、找不到 root UUID；截图和进程绑定保留。确认根盘未挂载后只退出本轮失败测试进程，换独立 IDE 状态启动通过。原盘规则缺件没有修补，仍为候选。
- Pane1 因独立画面复核超时，批处理曾标 needs_individual_review；随后实际查看画面、手工制作包并完成新状态复验。原超时记录保留，以最终 acceptance-summary.json 为准。
- Smoke 原站点跳转 smoke.dsz，指定 Host 后原 CGI 在隔离网内仍超时（60秒证据保留）。在独立派生副本添加原名称的 /etc/hosts 缓存后，两轮及接收方均 HTTP200。来源DNS的宿主代理198.18地址被拒绝，改用一手DNS接口生成候选，未启用来宾互联网；没有修改监测目标或 CGI 代码。
- Watcher 启动中截帧为 GRUB 欢迎，随后约62秒进入系统；不是故障通过证据。最终两轮登录提示/SSH/5000重定向通过，接收方另验 /login HTTP200。端口80关闭按实际记录。

## 最终证据与恢复

最终事实索引 acceptance-summary.json：每节点两轮结果、接收方结果、服务、配置、证据路径；originals-final-hashes.json：18个原始OVA前后完整哈希核对（包括复用Acfun）；recipient-visual-review.json：真实截图逐项复核。逐包 final-pack-verify.log 和 released-app-final-verify.log 保存结构校验。原始/已处理旧资产不改动。

本轮脚本（证据根）：adapt_network_disk.py、adapt_smoke_hosts.py、lab_service_probe.py、lifecycle_accept.py、package_verified.py、batch_adapt.py、finalize_evidence.py、recheck_originals.py。先复核源码与路径，使用 /opt/miniconda3/bin/python3 -B；重跑用全新目录/profile，勿复用历史PID或覆盖既有产物。生命周期用 vm-acceptance.lock 串行。动态QMP端点从当次 run.json 读取，不能照抄旧记录。

磁盘空间紧张时，仅本轮生成的 scratch RAW 保存为可恢复 QCOW2，qemu compare 验证虚拟内容一致；已停止测试状态基盘保存为 Zstd 字节归档，解压流完整SHA与原登记一致才回收原表示。恢复清单 scratch-archives/restore-index.json（虚拟内容恢复）和 closed-state-archives/restore-index.json（逐字节恢复+原只读权限）。日志、截图、metadata、最终包和原OVA全保留。历史测试状态需先按清单恢复磁盘才可复用；推荐全新状态安装内容包。用户后续授权仅永久删除上轮清单160项，随后报告已手动清空废纸篓。本助手未执行删除，受macOS隐私限制未独立复核废纸篓；上轮160项废纸篓恢复入口已失效，无需继续清理。本轮证据根的压缩归档独立保留。

本轮未改运行实现、未重打软件、未提交/推送/发布。Git 分支 codex/release-0.1.1-preview-20261010、HEAD 941db31114dbe811abadf46729295a72ec4bb30c。仅 .gitignore 白名单、当前状态和本验证记录在工作区有变更；库内新内容包/目录索引/文件清单为本地资产。文档守卫、git diff --check 和最终进程现场另附检查日志；历史683项回归未当成本轮重跑。

未认证登录或解题、课程完整性、全站功能、持续负载、多机并发、跨 Mac、外接屏/睡眠。没有碰用户虚拟机或物理 LAN。用户后续明确确认NoPort保留原样并注明原盘问题，继续保留候选。桌面虽授权空闲，本轮实际走包内CLI、QMP真实帧和隔离网协议，没有新增桌面登录结论。

本轮最终检查：17包 dist verify 全通过；已发布 App 的805个登记文件/运行时/签名校验通过；18个OVA哈希一致；17个新IP/MAC唯一且internet=false、host_forwards为空。库文件清单949项路径/大小核对无缺件，新条目哈希来自本轮完整校验，旧资产条目保持。文档守卫94项总数=89通过+5条件跳过（document-guards.log），git diff --check通过。final-process-snapshot.json 中相关GUI/QEMU/网络/显示进程和本轮run.json均为空。

## 后续说明整理（2026-10-13，不新增运行验收）

17个新包改为教师/学生可用步骤：具体导入目录、节点ID、资源、Kali访问的实际服务URL/端口、Smoke名称映射及撤销、Watcher/login、NoPort缺件候选、停止/重置/迁移。补Acfun说明，仅引用历史SSH，不推测Web。库内新增镜像使用与服务入口表，并修正库README/学生教程对当前发布软件的陈旧说法。

文档变更后更新每包doc角色大小/哈希、SHA256SUMS和README以及库文件清单。17包与旧Acfun分发整体verify通过；profile/base条目与claims前后不变，说明相对链接已核对。文档整理证据根 `/Users/pufei/Downloads/ctflab-image-guides-20261013`，原说明/清单备份在before。本轮未运行来宾、修改磁盘或App，未提交/发布；上面的运行证据保留为上阶段快照。

说明整理检查：17包和Acfun清单verify通过；链接检查通过；库索引957项路径/大小无缺件。文档守卫94项=89通过+5条件跳过（image-guides证据根document-guards.log），git diff --check通过。process-snapshot.json核验无相关实例；没有新增真实运行验收。
