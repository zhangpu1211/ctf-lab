# CTFLab Task 6.3A 验证记录：`CTFLab.app` 的 Kali ARM64 + UEFI 真实验收（2026-09-15）

结论只使用四类状态标签：**已验证** / **部分验证** / **未验证** / **后续任务**。

## 0. 结论摘要

- **已验证**：含受控 QEMU 运行时的 `CTFLab.app` 完成 Kali ARM64 + UEFI 的
  import / run / health / reboot / stop / reset 全链路（29/29 条记录全部通过），
  内置 QEMU、固件与 NVRAM 来源均有实证；原始资产与 App 自身未变化；`qemu-img check` 通过。
- **发现并修复 1 个打包缺陷**：6.2 的重签名丢失了源二进制的 `com.apple.security.hypervisor`
  entitlement，导致 App 内 QEMU 无法用 HVF 创建平台 VGIC（`HV_NO_DEVICE`）。修复后重建 App
  并重新完成全部验收。
- **未验证/后续任务**：Developer ID 签名、公证、分发（本轮不做）；动态分辨率；UTM。
- **复核修正**：原 final3 证据把含 `Advanced options`、`Firmware Settings`、`Booting in 4 seconds`
  的 GRUB 菜单误判为 `login_ready`；该证据已作废。final5 的首次启动与重启截图均由受控 OCR 规则
  命中登录专属信号，并经人工复核确认为 LightDM 图形登录界面。

## 1. 基线

`git pull origin main` → HEAD `285566d`（Task 6.2 提交），工作区干净，完整回归 **280 项通过**。
最终候选 App：`~/Downloads/ctflab-app-build-20260915-final5/CTFLab.app`
（树哈希 `108a93b09f3447ccb174defead46c154f9dac7bcb26eb03f9d457528c9bc6343`）。
验收脚本：`tools/ctflab_app_kali_e2e.py`（本轮新增）。全程未操作 UTM 与用户已有虚拟机；
未修改原始 Kali 基盘与 RAW NVRAM（只读校验 + 副本使用）。

## 2. 发现的缺陷与修复（必要修复）

**现象**：用 final2 的 App 启动 Kali，QEMU 立即退出：

```
qemu-system-aarch64: -accel hvf: error creating platform VGIC
qemu-system-aarch64: -accel hvf: Error: ret = HV_NO_DEVICE (0xfae94006, at ../accel/hvf/hvf-all.c:221)
```

**定位**（同一台机器、同一 QEMU 11.1.0）：

| 对象 | entitlements | HVF 4 vCPU 启动 |
|---|---|---|
| 宿主 `/opt/homebrew/opt/qemu/bin/qemu-system-aarch64` | `com.apple.security.hypervisor=true` | 正常（5 秒仍在运行） |
| App 内 `…/runtime/bin/qemu-system-aarch64`（final2） | **缺失** | 失败（VGIC/HV_NO_DEVICE） |

**根因**：6.2 的动态库改写后用 `codesign --force --sign -` 重新签名时**未保留源 entitlements**，
Hypervisor.framework 因此拒绝创建 VM 设备。烟测（smoke，x86_64 TCG）不需要 HVF，故此缺陷未被 6.2 E2E 覆盖。

**修复**（`tools/ctflab_app.py`）：

- 复制阶段用 `codesign -d --entitlements :-` 读取**源二进制** entitlements；
- 签名阶段用 `codesign --entitlements <plist>` 原样带回，并对每个源 entitlements 做**完整字典相等**
  断言（键或值变化均构建失败，禁止静默降级）；
- `MANIFEST.json.runtime.entitlements` 记录键集合与规范化 plist 的 SHA-256 摘要，`app verify` 同时复核
  键和值；`com.apple.security.hypervisor=false` 也会被明确拒绝；
- 验收脚本要求来宾口令，否则总结果直接失败；`sudo` 口令只经标准输入传入，不进入远端命令行或证据。

**复核修正后**：重建 `~/Downloads/ctflab-app-build-20260915-final5/CTFLab.app`
（树哈希 `108a93b09f3447ccb174defead46c154f9dac7bcb26eb03f9d457528c9bc6343`，
MANIFEST SHA-256 `cdd3fb847bc3cb31195f21dc94093cf536038d1ebd91b238aa075df67198b892`），
App 内 `qemu-system-aarch64` 重新带上 `com.apple.security.hypervisor=true`，HVF 启动正常。
final2–final4 均判定为被替代的历史候选，不再作为可用交付物。

## 3. 验收证据（29/29 条记录，证据 JSON：`~/Downloads/ctflab-app-kali-e2e-20260915-r4/kali-e2e-evidence.json`）

| 步骤 | 结果 |
|---|---|
| verify-app | 138 个登记文件，树哈希 `108a93b0…`，ad-hoc 签名；**旁车 `CTFLab.app.sha256` 一致** |
| app-runtime-assets | `qemu-system-aarch64` `b7817897…`、`qemu-img` `83e7caf3…`、`edk2-aarch64-code.fd` `47765fe3…`、`edk2-arm-vars.fd` `b3b855c5…` |
| doctor（最小 PATH，无 `/opt/homebrew/bin`） | 缺 PyYAML 提示正确；`运行时：bundled（…/CTFLab.app/Contents/Resources/runtime）`；固件路径全部在 App 内 |
| venv + PyYAML 后 doctor | 必选依赖就绪，仍为 bundled，输出无宿主路径 |
| firmware-provenance | `sandbox-exec` 拒绝 `/opt/homebrew` 读取后，App 内 `qemu-system-aarch64` + App 内固件仍可启动（沙箱内用 TCG：sandbox-exec 无法创建 HVF，见 §5） |
| asset-baseline / copies | 原始基盘 `ca1034606a82…`、原始 RAW NVRAM `8639a3fb43dd…` 与登记值一致；副本哈希一致 |
| import ×3 | kali-arm64（base `ca1034606a82…`，NVRAM 模板指向原始 RAW 副本）、smoke、basic-pentesting-2 全部导入 |
| run | Kali QEMU 进程命令行来自 `…/CTFLab.app/Contents/Resources/runtime/bin/qemu-system-aarch64`（`-accel hvf`、App 内 `edk2-aarch64-code.fd`、派生 NVRAM），无宿主路径 |
| uefi-boot | QMP 截图多模式 OCR 分类 = `login_ready`（medium），人工复核 `final-screen-initial.png` 确认为 LightDM；**从未命中 UEFI Shell / 无启动盘 / kernel error** |
| nvram-derivation | 派生 NVRAM `state/runtime/kali-arm64/uefi-vars.fd` 可写（0644，`7f45c82d…`）；App 模板 `b3b855c5…` 与原始 RAW `8639a3fb…` 未变 |
| health ×3 | kali-arm64（DHCP+SSH）、smoke、basic-pentesting-2 全部通过 |
| guest-lab-warmup + guest-connectivity | 经 SSH 在 Kali 内实测：ping smoke/basic 0% 丢包、`http://192.168.242.21/` **HTTP 200**、`1.1.1.1` 不可达（WAN_BLOCKED）、路由表无默认路由（仅 10.0.2.0/24 与 192.168.242.0/24 直连） |
| guest-poweroff + stop-1 | 来宾内 `sudo poweroff` 正常关机 → `ctflab stop` 清理 |
| reboot + reboot-boot + health-after-reboot | 再次启动成功；`final-screen-reboot.png` 人工复核为 LightDM；健康检查再次通过 |
| stop-2 + reset | 第二次停止与重置完成（smoke/basic 同步停止与重置） |
| residue-check | 无 QEMU/QMP/网络/overlay/运行状态残留 |
| hash-invariants | App 树、App 固件模板、原始基盘、原始 RAW NVRAM 哈希**全部未变**（`108a93b0…` / `b3b855c5…` / `ca1034606a82…` / `8639a3fb…`） |
| qemu-img-check | 用 App 内 `qemu-img`（最小 PATH）检查导入基盘：通过 |

## 4. 范围与限制（不得跨类宣称）

- **签名**：ad-hoc（`codesign --verify --deep --strict` 返回 0）；**未做** Developer ID 签名与公证，
  资格与凭据均未使用；不得宣称已签名分发。
- **分发**：项目许可证 `undeclared`、QEMU GPL 源码义务未随附、`dtc` 许可证文本缺失（沿用 6.2 结论），
  **禁止公开发布**该 App。
- **依赖**：PyYAML 仍需联网 `pip install`（App 未内置解释器与依赖）。
- **未覆盖**：动态分辨率、UTM、`probe --matrix` 的 x86 UEFI 路径、签名/公证自动化、
  “零手工依赖的完整安装”（属 Task 6 后续）。
- 验收使用用户环境中已导入资产（基盘 + RAW NVRAM）的**副本**；原始文件只读校验，未修改。

## 5. 验收方法学说明（供复核）

- **沙箱固件来源检查用 TCG**：`sandbox-exec` 内无法创建 HVF（平台 VGIC 被沙盒限制），
  因此该步只用 TCG 证明“固件来自 App”；真实运行使用 HVF 的事实由 `run` 步的进程命令行证据覆盖。
- **图形登录界面用多模式 OCR + 人工复核**：单次 `--psm 6` 对 LightDM 渐变背景识别极差；
  原图 + 2 倍放大 × psm 6/11/12 取并集后，只有 `Password`、`LightDM`、`Log In`，或
  `KALI + Log!`（本机实测 OCR 退化）这类登录专属组合才能判为 `login_ready`。单独出现 `Kali` 不足以
  通过；GRUB 的 `Advanced options` / `Firmware Settings` / 倒计时信号优先判为 `boot_progress`。
  首次与重启截图分别保存并人工复核；失败时保留 `last-screen.png`。
- **隔离网连通性等待靶机服务**：靶机走 TCG，比 Kali（HVF）慢；先轮询直到 ping 与 HTTP 200 同时成立
  （最多 300 秒）再做完整断言，避免把“启动未完成”误判为“网络不通”。
- 每条失败路径都会执行收尾（停止实例、清理本 workdir 的交换机进程），并保留命令行、退出码与
  截图证据。
