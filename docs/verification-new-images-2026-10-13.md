# 新增 Kioptrix、Stapler、Wintermute 镜像复核（2026-10-13）

> 历史验收快照；不替代当前软件状态。来源目录、进程与空间以后均须现场重核。

正式项目目录 `/Users/pufei/Downloads/ctf-lab`。证据根 `/Users/pufei/Downloads/ctflab-new-three-20261013`；使用已发布 `CTFLab-0.1.1-preview.20261012/CTFLab.app` 包内 CLI 和受控 QEMU。没有操作用户已有虚拟机、桌面或原始镜像；测试只在新建状态目录运行，服务请求只经过回环实验网。新目录表面是三组，实际有四台虚拟机。

| 来源 | SHA-256 | 虚拟磁盘及原硬件 | 本轮结论 |
|---|---|---|---|
| `kioptrix-extract/Kioptix Level 1/Kioptix Level 1.vmdk` | `2a44b063e04758e63f1b5d971d5498d5e3661d93e6eb78840339180a672b806d` | 3 GiB VMware VMDK，IDE；旧 Red Hat | 原盘停在 `Starting sendmail`。只修改派生盘 hosts 后到 `kioptrix login:`，但隔离客户端仍无法 ARP `.57`，正常关机超时，服务未证实。**未制作交付包**。 |
| `stapler-extract/Stapler/Stapler-disk1.vmdk` | `d07fb20daa375f16f9a9e49d7109c7aa6dc14f98130f232f389fc123b74b345b` | 20 GiB streamOptimized VMDK；OVF 指定 SATA/AHCI 与 PCNet32 | 制成**兼容候选**内容包，登录画面和初始服务在全新接收状态复现；正常关机一次超时、一次成功，稳定性未闭环。 |
| `wintermute-extract/Wintermute-Straylight.ova` | `6ceadb8cf63be6aaa169626516f69396707e25e632eeeae57201baa39606c7d9` | 单 VMDK，5 GiB；SATA/AHCI、原双 E1000 | 转换后 `qemu-img check` 和 `compare` 通过；单网卡测试到 Debian 9 登录提示，但未获固定实验 IP；缺第二隔离网，**未制作交付包**。 |
| `wintermute-extract/Wintermute-Neuromancer.ova` | `6ca2c82219e043103db43e7cbb46ec21f62cacfacee02907e6bda95774f762f1` | 单 VMDK，约 5.95 GiB；SATA/AHCI、原单 E1000 | 转换后 `qemu-img check` 和 `compare` 通过；独立测试到 Ubuntu 16.04 登录提示、正常关机，未获固定实验 IP；**未制作交付包**。 |

Wintermute 随附 `Wintermute-Lab-Setup.txt` 明确规定 Straylight 接外侧与内侧两张 host-only 网，Neuromancer 只接内侧，Kali 只接外侧；从 Kali 直通 Neuromancer 会改变题目。现行 CTFLab 单实验网不能原样实现这条跳转链，因此单机启动不能升格为整题适配通过。原 OVA 未修改；转换的 QCOW2 留在本轮证据根 `staging/`，仅为后续双网段功能的可复用候选。

Stapler 原盘 `/etc/network/interfaces` 把 DHCP 绑定到 VMware 的 `ens33`。原硬件配置在 QEMU 到 `red login:`，但启动报告 `Failed to start Raise network interfaces`，实验客户端 ARP 失败。对**派生 RAW 副本**仅将文件数据块的两个 `ens33` 替换为等长 `eth0 `，没有修改账号、服务或漏洞；偏移与数据块修改前后 SHA 见 `stapler-network-patch.json`。派生 RAW 与压缩后的 `stapler-adapted.qcow2` 经 `qemu-img compare` 虚拟内容相同，原 VMDK 不变。修正后独立实例与从内容包全新安装的接收实例均能 ARP `192.168.242.58`，FTP 21 返回 220，SSH 22 TCP 开放（未取得 banner），HTTP 80 `/` 返回 404。404 是服务回应，不等于主页或挑战功能通过。两轮均见 `red login:`；没有认证登录或解题。

内容包位于 `/Users/pufei/Downloads/CTFLab-Library/02-已处理/Stapler-候选-20261013`，schema 2，自包含 `stapler.yaml`、基盘、使用说明和校验。包内 `dist verify` 通过，独立 `stapler-recipient-state` 的 `dist install` 真导入与再次启动/服务复测通过。制作阶段 `stop --graceful` 超时后只对本轮独立实例执行默认停止；接收实例的 `stop --graceful` 成功。由于结果不一致，包和索引保持**候选**标记；未验证正常关机稳定性、再次重启后的服务、登录或跨 Mac。

Kioptrix 原盘 `probe` 的 `network_and_display_candidate` 只说明显示活动和 DHCP 分配；QMP 实际截图长期停在 sendmail，隔离探针 ARP 失败。原盘 `ifcfg-eth0` 已是 DHCP。进一步在**派生盘**恢复 `/etc/hosts` 被注释的 localhost 行（只替换行首一个字节，原块 SHA/偏移见 `kioptrix-hosts-patch.json`），`qemu-img compare` 确认压缩后虚拟内容与修改后的 RAW 一致。新独立实例截图 `kioptrix-hosts-current.png` 见到 `kioptrix login:`，网络日志有 DHCP ACK `.57`，但 `kioptrix-hosts-services.json` 显示隔离客户端 ARP 仍为空，22/80/443/139 均未取得协议证据。`stop --graceful` 超时并保留实例；随后仅对该独立测试状态执行普通 `stop`，返回成功。启动画面已修复，但网络未通过，仍不交付给学生。

本轮为磁盘空间回收，仅将**已停止的本轮测试状态**压缩并验证压缩流及 TAR 列表，再移除可恢复的散放测试状态；见 `wintermute-*-test-state.tar.zst`、`stapler-adapted-state.tar.zst`、`stapler-recipient-state.tar.zst` 与 `scratch-rebuild-index.json`。原始输入、发布 App、内容包、日志与截图保留。另有上一轮 NoPort 临时 RAW 的可验证压缩归档，索引在 `ctflab-clarify-20261013/archive-index.json`。

镜像库 `01-待处理` 同日被整理：旧清单登记的 18 个散放 OVA 路径均不再存在；当前有 `2.zip` 与三组新提取目录。旧库清单已备份到本轮证据根，根级清单按现存文件树重建，不能用旧路径追溯原件。`2.zip` 内有 `1/basic_pentesting_2.ova`，已直接流式读取、核对 ZIP CRC 与 SHA-256 `145a164df4c78dcecff670a13e9c8d07dd91237797c1a4b42017aefa4cca2661`；未解压或修改。此项回答原始 Basic 文件的位置，不代表其内容与当前分发基盘再次比对。

工作区仅新增本记录、当前状态及 `.gitignore` 白名单，保留原有未提交修改；本轮没有运行器实现变更、软件重打包、提交、推送或发布。最终源文件哈希、库根清单验证与进程状态见证据根的收口检查文件。

收口复核：`final-check.json` 四份原件 SHA-256 前后一致，相关 QEMU 进程及 `run.json` 均为零；`stapler-recipient-state.tar.zst` 经 `zstd -t` 与 TAR 列表核验后才移除散放状态，Kioptrix 的两个停止测试状态仍保留。库根 `shasum -a 256 -c SHA256SUMS` 对 958 项全部通过，日志为 `library-sha-verify-final.log`；Stapler 包内 `dist verify --json` 的 `ok=true`，见 `stapler-pack-verify-final.json`。项目文档守卫 `python3 -m unittest discover -s tools/tests -p "*doc*" -q` 为 94 项通过、5 项条件跳过；`git diff --check` 通过。磁盘余量约 4.4 GiB，下一轮再导入大型镜像前需要释放或迁移本轮可恢复测试证据。

## 同日续验：Kioptrix 租约修复与 Stapler 慢关机

以下续验覆盖上文“Kioptrix 未制作交付包”的**旧阶段结论**；该旧结论不得再作为当前状态引用。使用同一已发布 App 的包内 CLI，未改运行器源码或原盘；独立证据均在 `/Users/pufei/Downloads/ctflab-new-three-20261013/followup`。

Kioptrix 的离线来宾日志显示 PCNet 驱动已识别 `52:54:00:24:00:57`，`eth0` 启动脚本报告成功；但旧 `/etc/dhcpc/dhcpcd-eth0.info` 中 `IPADDR=192.168.1.104`，即使实验网 DHCP 已 ACK `.57`，来宾仍保留 VMware 旧地址。取前轮仅恢复 localhost 行的派生 RAW 再派生新盘，只删除来宾 `/etc/dhcpc/dhcpcd-eth0.cache` 与 `.info` 两份旧租约；`kioptrix-dhcp-patch.json` 记录原/派生分区与磁盘 SHA，`qemu-img check`、RAW 对压缩 QCOW2 的 `compare` 均通过。原 VMDK 未改。

新盘在制作状态两次冷启动及从内容包**全新安装状态**一次冷启动，QMP 均见 `kioptrix login:`；PCAP 有 DHCP OFFER/ACK、`.57` 的 ARP 响应。三个实例在系统服务完全启动后均取得 SSH 22 `SSH-1.99-OpenSSH_2.9p2`、HTTP 80 `200 OK`（Red Hat Apache 默认页）、139 和 443 TCP 开放。第三次接收状态的 `dist install`、截图与协议结果分别见 `kioptrix-recipient-install.json`、`kioptrix-recipient.png`、`kioptrix-recipient-services-r2.json`；较早的探测 HTTP 关闭，说明仅凭登录提示或 DHCP 不应提前宣布服务就绪。没有认证登录或题目解题。

已制作 schema 2 **兼容候选**包 `CTFLab-Library/02-已处理/Kioptrix-候选-20261013`，内含白名单 profile、派生基盘和使用说明；`kioptrix-pack-verify-updated.json` 为 `ok=true`。它不等同于完整课堂验收。两次制作状态的 `stop --graceful` 超过 30 秒；接收状态同样超时，QMP 截图仍是登录提示，并且 ACPI 请求后继续观察 120 秒仍未自然退出（`kioptrix-recipient-shutdown.json`）。运行器正确保留进程/磁盘；核对 PID 后只对独立实例执行普通 `stop`。此关机限制与旧系统启动耗时已写进包内说明，不能将它标为稳定可用。

Stapler 使用已发布候选包另建 `stapler-reboot-state`，`dist install` 后连续两次真实冷启动均见 `red login:`，ARP、FTP 21 的 220、SSH 22 `OpenSSH_7.2p2 Ubuntu-4`、HTTP 80 的 404 服务响应均复现；截图及探针见 `stapler-boot{1,2}.png`、`stapler-boot{1,2}-services.json`。两次 `stop --graceful` 均在 30 秒超时，但一次 QMP 截图明确在 systemd 停止用户会话任务，随后 QEMU 自然退出；第二次从请求到自然退出为 **94.31 秒**，没有强制断电（`stapler-boot2-shutdown.json`）。旧轮一次 30 秒内成功仍保留为历史事实。只在进程自然退出后调用 `stop` 清理登记，随后再次冷启动。候选包的 profile 声明、说明和 SHA256SUMS 已更新并 `dist verify` 通过，旧版元数据留在 `stapler-pack-before-update/`，基盘逐字节未改。运行器固定 30 秒等待与来宾约 95 秒关机不匹配，当前软件仍会向使用者报告超时，因此继续标“候选”。

Wintermute 未在本次续验中改变拓扑或候选级别。两候选包的公开说明均不放登录凭据；没有操作用户已有虚拟机、桌面或外部网络。续验收口：两份当前候选包 `dist verify` 均 `ok=true`，自动生成 README 的条目哈希与当前清单一致；更新后包又共同在 `final-pack-install-state` 真安装（`kioptrix-final-pack-install.json`、`stapler-final-pack-install.json`），该最后安装状态未启动虚拟机。库根清单增至 964 项，`shasum -a 256 -c SHA256SUMS` 全部通过，见 `library-sha-verify.log`。`final-check.json` 四份原始输入 SHA 前后相同，本轮相关 QEMU、`run.json` 均为零；当前测试状态保留供复核。文档守卫 94 项通过、5 项条件跳过，`git diff --check` 通过。分支 `codex/release-0.1.1-preview-20261010`、HEAD `941db31`；保留原有未提交改动，未修改运行器源码、未重打 App、未提交、推送或发布。
