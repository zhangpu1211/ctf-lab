# Wintermute 独立实机验收只读预检（2026-10-14）

> 历史验收快照；不替代当前软件状态。执行实机验收前必须现场重核以下哈希、路由与空间。

正式项目：`/Users/pufei/Downloads/ctf-lab`；分支 `codex/release-0.1.1-preview-20261010`；HEAD `941db31`。本轮只读预检：未启动任何 VM/网络服务、未解包 OVA、未修改任何镜像、未创建场景状态根、未操作用户实例。哈希用 `shasum -a 256` 现场重算，qemu-img/tar 仅只读读盘（OVF 经 `tar -xOf` 输出到 stdout）。

## 资产清单（现场重算 SHA-256）

| 资产 | 路径 | 大小（实际/虚拟） | SHA-256 |
|---|---|---|---|
| Neuromancer 候选基盘 | `~/Downloads/ctflab-new-three-20261013/staging/wintermute-neuromancer-base.qcow2` | 1.45 GB / 6.39 GB | `817452b4cd41cf0fa459c7835e5969f9525b0008d3c5c2ccb9479352d45cc562` |
| Straylight 候选基盘 | `~/Downloads/ctflab-new-three-20261013/staging/wintermute-straylight-base.qcow2` | 1.18 GB / 5.37 GB | `6724817218c88c3b126983c42e5824b48bdb02e93ce58de0a275e7c09aa4e235` |
| 原件 Neuromancer OVA | `~/Downloads/CTFLab-Library/01-待处理/wintermute-extract/Wintermute-Neuromancer.ova` | 1.3 GB | `6ca2c82219e043103db43e7cbb46ec21f62cacfacee02907e6bda95774f762f1` |
| 原件 Straylight OVA | `~/Downloads/CTFLab-Library/01-待处理/wintermute-extract/Wintermute-Straylight.ova` | 1.1 GB | `6ceadb8cf63be6aaa169626516f69396707e25e632eeeae57201baa39606c7d9` |
| 原题说明 | `~/Downloads/CTFLab-Library/01-待处理/wintermute-extract/Wintermute-Lab-Setup.txt` | 1.8 KB | `19a99d7b682a2bde228f4f547a9f44272d83696a3f8928e4767c9925054be0af` |
| Kali 候选基盘（库内副本，非用户实例） | `~/Downloads/CTFLab-Library/02-已处理/kali-arm64-base.qcow2` | 8.1 GB / 64 GB | `974a319f596170d171e75a5ee3e0f0fd4d28439ab10373c14f0fd9348b396315` |
| Kali UEFI vars（库内副本） | `~/Downloads/CTFLab-Library/02-已处理/kali-arm64-uefi-vars.fd` | 64 MB | `8639a3fb43ddec7cd1386c47babd19e76582fb29f757f286f1cb2a8b8c19d3c8` |
| 固件 code（QEMU 11.1.0 随附） | `/opt/homebrew/share/qemu/edk2-aarch64-code.fd` | — | `47765fe344818cbc464b1c14ae658fb4b854f5c2ceffa982411731eb4865594d` |

`qemu-img info`（Homebrew QEMU 11.1.0，只读）：三份基盘均为独立 QCOW2，无 backing、无 data-file。执行时的 `scenario prepare` 会现场重核哈希；如与上表不符必须停下核对来源，不得继续。

## 硬件与 NIC 证据（OVF 只读提取）

- Straylight：slot 0 = `82543GC`（Intel PRO/1000 T Server，host-only #1），slot 1 = `82540EM`（PRO/1000 MT Desktop，host-only #3/原说明 #2），双卡已启用；与原题说明一致。RAM 1024 MB。
- Neuromancer：slot 0 = `82540EM` 挂 **NAT**（原始导出默认，验收清单不得采用），slot 1 = `82543GC` host-only（原题要求使用的唯一网卡）。RAM 1024 MB。**执行项**：场景清单只声明 inner 一张卡，冷启动必须确认该来宾网络服务在单卡下正常 DHCP 起址；若来宾固件/服务绑定原 NAT 卡导致无地址，记录差异，不得自动改造基盘。
- 两张卡均为 QEMU e1000 家族；具体映射（`e1000-82545em` / `e1000-82544gc` / `e1000`）按设计第 9 节在首次冷启动以来宾命名确认，不在本轮臆断。
- Kali 节点用库内 aarch64 候选 + `edk2-aarch64-code.fd` + 库内 vars 副本（UEFI/VirtIO），清单 `hardware_verified` 保持 `false`，冷启动后按证据更新。

## 网络与资源核对（现场只读）

- 路由快照：`netstat -rn -f inet` 无任何 `192.168.243.x` / `192.168.244.x` 路由，仅默认路由经 en0；候选网段当前无冲突。执行前后仍须各采集一次（`collect_macos_routes` 已内置于 prepare/start）。
- 工具链：`qemu-img`/`qemu-system-x86_64`/`qemu-system-aarch64` 均为 Homebrew QEMU 11.1.0。
- **空间风险**：数据卷仅剩约 7.0 GiB（/System/Volumes/Data 100% 容量显示为近似满）。三节点 overlay 初始很薄，两轮冷启动 + 一代重置预计增长 1–3 GiB，可行但紧张；执行时应监控 `df`，或经 `--state-root/--socket-root` 指定有充足空间的位置（注意 socket 根受 104 字节路径上限）。

## 执行时仍需完成的门槛（设计第 9 节，未做）

场景清单尚未物化：执行时以三份基盘哈希与上述硬件证据生成候选 manifest（`hardware_verified=false`、四类 `checks` 为空），经 `scenario prepare` 绑定；冷启动后以来宾证据更新。两轮冷启动/停止、显示或登录、来宾地址、目标服务、应通/禁通矩阵、跳转解题、整场景重置与重开恢复全部待执行，且需当次明确授权。
