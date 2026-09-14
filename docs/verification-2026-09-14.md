# CTFLab 三节点网络、生命周期、干净环境与启动回退矩阵验证（2026-09-14）

本轮按优先级完成四项：三节点网络实测、20 次生命周期压力、干净用户环境验证、
受控启动回退矩阵（实现 + 单元测试 + 未知镜像实测）。不涉及跨平台、攻击功能或靶场网络范围的扩展。

本文所有结论只使用四类状态标签，不允许跨类宣称：

- **已验证**：有可复核的实测证据；
- **部分验证**：核心路径有证据，但仍有明确边界未覆盖，不得当作已完成；
- **未验证**：没有证据；
- **后续任务**：依赖尚未交付的组件（如 Task 6 打包），当前不宣称完成。

## 0. 状态总览

| 状态 | 本轮对应内容 |
|---|---|
| 已验证 | Kali→靶机 ICMP/全端口 Nmap/HTTP 200/SSH 横幅、靶机无公网、Mac 端口映射、20 次生命周期压力、启动回退矩阵机制与候选命中事件、本次完整回归（2026-09-14） |
| 部分验证 | 干净环境（手工安装 PyYAML 后导入/运行通过；独立安装包未交付）、矩阵命中的候选配置（需人工复核截图后才能升级）、靶机→Kali 仅帧级双向 |
| 未验证 | 靶机应用级主动回连 Kali、干净环境无手工依赖的完整安装 |
| 后续任务 | 独立安装包/签名/公证（Task 6）、应用级回连所需的靶机内执行流程（Task 4 剩余项） |

## 1. 三节点网络实测（Kali→靶机与服务：已验证；靶机→Kali：部分验证）

`./tools/ctflab run kali-arm64 smoke basic-pentesting-2 --pcap` 启动三个节点，
健康检查全部就绪（Kali DHCP+SSH、smoke DHCP+SSH、basic DHCP+HTTP 200）。
以下实测在 Kali 内执行（同时把结果跑在 Kali 图形终端里截图存档，截图留在状态目录不入库）。

| 检查 | 结果 | 状态 |
|---|---|---|
| Kali→smoke ICMP | 10 包 0% 丢包，RTT 均值 15ms | 已验证 |
| Kali→basic ICMP | 10 包 0% 丢包，RTT 均值 6.3ms | 已验证 |
| Kali→smoke 全端口 nmap | open：21/ftp、22/ssh、80/http（58402 closed + 7130 filtered，TCG 限速导致） | 已验证 |
| Kali→basic 全端口 nmap | open：22/ssh、80/http、139/445/smb、8009/ajp、8080/http-proxy | 已验证 |
| basic HTTP | 200，Apache/2.4.18 | 已验证 |
| smoke/basic SSH | OpenSSH 10.0 / 7.2p2-ubuntu2.4 横幅可达 | 已验证 |
| 靶机→Kali 帧级双向 | PCAP 中靶机→Kali 帧 124,103 条（ICMP 回复/TCP 响应含源 MAC） | 部分验证：只有帧级双向证据 |
| 靶机→Kali 应用级主动回连 | FTP 匿名 530 被拒；没有可免凭据的应用级回连通道 | 未验证：需要靶机内执行权限/凭据，未做 |
| 靶机无公网 | 管理网卡 `restrict=on`、交换机仅监听 127.0.0.1 且无上游、DHCP 不下发网关、28.8 万帧无实验网外 IP | 已验证 |
| Mac→basic Web 端口映射 | `127.0.0.1:18080` HTTP 200；三个 SSH 端口映射横幅均可访问 | 已验证 |

PCAP 保留：`~/Library/Application Support/CTFLab/pcap/lab-23400-20260914T010127Z.pcap`（288,036 帧，21MB，含双向帧与源 MAC）。

## 2. 20 次生命周期压力测试（已验证）

连续 20 次 `run kali-arm64 --headless → health（等 DHCP）→ stop → reset`：

- 20/20 轮 run/stop/reset 退出码全部为 0，DHCP 每轮均在超时内获取；
- 每轮检查：无 QEMU 残留进程、无 qmp.sock、无 network-\*.json、无 overlay 残留；
- 基础镜像 SHA-256 前后一致：`ca1034606…`（与登记值相同，未变化）；
- `locks/operations.lock` 存在但未被持有（状态目录可正常获取操作锁），实验网状态清零。

顺带修复：`stop --all --graceful` 原来在第一个不响应 ACPI 的实例处中断，导致其余实例未处理；
现改为逐个处理，超时的实例保留并统一在完成后报告（新增测试覆盖）。

## 3. 干净用户环境验证（部分验证：手工安装依赖后可导入/运行；安装包未交付）

模拟新 HOME + 最小 PATH（无 conda、无项目开发依赖）：

- 系统 Python 3.9：doctor 可运行；缺 PyYAML 时 import 立即给出安装指引（
  `python3 -m pip install pyyaml`）；
- venv（python3.14，**手工**按文档安装 PyYAML 6.0.3）后完整跑通：
  `doctor（全部 OK）→ import smoke → run --headless → status → health（DHCP+SSH 就绪）→ stop → reset`；
- reset 后状态目录无残留（无 overlay/qmp/网络状态），导入的基础镜像保留，无残留进程。

以上证明的是“依赖缺失时提示正确、手工补齐依赖后全流程可用”，**不构成**“干净 Mac M 用户环境可完成
完整安装、导入、运行”的验收：本轮没有交付独立安装包，无手工 `pip install` 步骤的完整安装属于
Task 6 打包的交付内容，尚未验证。因此实施计划第 7 节的对应验收项保持未通过。

顺带修复：doctor 对必选依赖缺失时错误地显示“可选”文案，改为逐项安装提示；
`utmctl` 并非运行必需（仅 UTM 适配流程使用），从必选改为可选（新增测试覆盖）。
注意：smoke/basic 的原始源镜像路径已不在本机，干净环境验证改用已导入的基础镜像作为导入源，流程等价。

## 4. 受控启动回退矩阵（实现与单元测试：已验证；候选命中事件：部分验证）

实现（`tools/ctflab.py`）：

- `probe --matrix`：按白名单顺序尝试固件/磁盘组合
  （BIOS×IDE/SATA/SCSI/VirtIO → UEFI×IDE/SATA/SCSI/VirtIO；SCSI=lsi53c895a、SATA=ich9-ahci；
  aarch64 只允许 UEFI+VirtIO），每个候选的超时独立（`--matrix-timeout`，默认 90s）；
- 候选参数只作用于本次启动（运行状态记录 `boot_override` 审计字段），不写 profile；
- `probe` 轮询中实时对截图 OCR 分类，识别到 UEFI Shell/无启动盘/内核错误立即放弃当前候选，
  命中登录画面或协议/DHCP 就绪即停止（记录 `early_failure` 与矩阵 JSON 报告）；
- 附带支持 x86_64 UEFI 启动：OVMF pflash 代码 + 独立可写 NVRAM（`uefi-vars-x86_64.fd`），
  不影响 aarch64 既有路径与 `finalize-install --from-runtime`；
- 常用参数还有 `--matrix-max`（限制候选数）与 `--matrix-start`（跳过前 N 个候选，用于验证回退路径与定位）。

单元测试（`tools/tests/test_ctflab_boot_matrix.py`，11 项）：
矩阵白名单组合全部通过 profile 校验且覆盖 8 种组合、aarch64 单候选、
首个可启动候选即停止、全部失败时报告 8 个候选、启动错误续试、
不改写磁盘 profile、`--matrix-max`/`--matrix-start` 限制生效、x86 UEFI 命令含 OVMF pflash。

未知镜像实测（`WebServer.ova`，4.75GB，x86_64 候选，onboard 候选为 uefi/scsi）：

- 完整矩阵：**bios/scsi/lsi53c895a 首个候选即命中登录画面**（说明该镜像实际是 BIOS+SCSI，
  矩阵修正了 onboard 对 UEFI 的猜测），矩阵停止，报告 `login_ready/medium`；
- `--matrix-start 2` 演示失败续试：bios/ide 未达登录（boot_progress）→ 自动继续 →
  **bios/sata/ich9-ahci 命中登录画面**，矩阵停止并给出“请人工查看截图后再修改 profile”提示；
- 矩阵报告写入 `logs/probes/webserver-matrix-*.json`，候选参数未写入
  `tools/ctflab_profiles/webserver.yaml`（该候选 profile 当前保留在工作区，未提交）。

状态判定：矩阵机制本身（回退、早停、报告、不改写 profile）**已验证**；
“WebServer.ova 可在 CTFLab 中稳定使用”仍属**部分验证**——候选命中只提供截图证据，
必须人工复核登录/服务后才能按已验证交付（这是设计上的候选/交付区分，不是缺陷）。

## 5. 回归与边界

- `python3 -m unittest discover -s tools/tests`：本次完整回归（2026-09-14）95 项通过（66 项既有回归——含 11 项矩阵测试、
  优雅停止聚合测试、doctor 提示测试与 Ghidra/文档命令测试——加 29 项验收状态与设计边界守卫测试）。
- 未提交虚拟磁盘、日志、截图或凭据；临时口令文件验证后删除。
- 本轮状态汇总（与第 0 节一致）：
  - 已验证：三节点网络（Kali→靶机与服务）、靶机无公网、Mac 端口映射、20 次生命周期、
    启动回退矩阵机制与候选命中事件、本次完整回归（2026-09-14）；
  - 部分验证：干净环境（手工安装依赖后可运行）、矩阵命中的候选配置、靶机→Kali 仅帧级双向；
  - 未验证：靶机应用级主动回连 Kali、干净环境无手工依赖的完整安装；
  - 后续任务：独立安装包与签名/公证（Task 6）、应用级回连所需的靶机内执行流程（Task 4 剩余项）。
