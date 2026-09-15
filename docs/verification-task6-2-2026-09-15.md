# CTFLab Task 6.2 验证记录：受控 QEMU 运行时 `CTFLab.app`（2026-09-15）

本文记录 Task 6.2 的交付与实测证据。结论只使用四类状态标签：**已验证** / **部分验证** /
**未验证** / **后续任务**。

## 1. 交付物（本机路径，不入库）

| 交付物 | 位置 | 状态 |
|---|---|---|
| `CTFLab.app`（含受控 QEMU 运行时） | `~/Downloads/ctflab-app-build-20260915-final2/CTFLab.app` | 已验证（限定范围） |
| 旁车校验文件 | `~/Downloads/ctflab-app-build-20260915-final2/CTFLab.app.sha256` | 已验证 |
| 构建/校验模块 | `tools/ctflab_app.py`、CLI `ctflab app build/verify` | 已验证 |
| E2E 脚本 | `tools/ctflab_app_e2e.py` | 已验证 |
| 单元测试 | `tools/tests/test_ctflab_app.py`（33 项） | 已验证 |
| 设计文档 | `docs/ctflab-task6-app-runtime-design.md` | 已验证 |

关键记录：app 树 SHA-256 `2d5a950e9ef33f295aca6e56d100e81eb10d46bdf55f3ffa83a723024ae35c98`；
`MANIFEST.json` SHA-256 `c4678661579642178ee8ff29e2dce0bc5044527b256675f09f3314ff285b28d3`；
138 个登记文件；QEMU 11.1.0（arm64 原生：`qemu-system-aarch64`/`qemu-system-x86_64`/`qemu-img`）；
28 个非系统动态库闭包；50 个运行时资源（firmware/ROM/keymaps）；签名级别 **ad-hoc**。

随包固件哈希（抽样）：`edk2-aarch64-code.fd` `47765fe3…`、`edk2-x86_64-code.fd` `33090cc0…`、
`bios-256k.bin` `ae6f6aa9…`。

## 2. 真实 E2E（已验证：限定范围）

`python3 tools/ctflab_app_e2e.py --app …/CTFLab.app --profile smoke --workdir ~/Downloads/ctflab-app-e2e-20260915-final2`
在“独立 HOME + 最小 PATH = `/usr/bin:/bin:/usr/sbin:/sbin`（**不含 `/opt/homebrew/bin`**）+
独立 state-dir + 派生的 Smoke 基础镜像副本”下 15/15 步通过：

1. `verify-app`：结构/Info.plist/MANIFEST 逐文件哈希/动态库引用/SBOM 全部通过；
2. `doctor-missing-deps`：PyYAML 缺失提示正确（退出码 1）；
3. `install-pyyaml`：临时 HOME 里 venv 安装 PyYAML（**联网步骤**）；
4. `doctor-bundled-runtime`：`运行时：bundled（…/CTFLab.app/Contents/Resources/runtime）`，
   三个 QEMU 程序路径全部位于 app 内，输出中无 `/opt/homebrew`；
5. `firmware-provenance`：`sandbox-exec` 拒绝 `/opt/homebrew` 读取后，直接用 app 内
   `qemu-system-x86_64` 启动 pc 机器仍能持续运行（固件来自 app，不是宿主 QEMU）；
6. `import` → `run --headless` → `health`（**DHCP + SSH 就绪**）→ `stop` → `reset`：全部退出码 0；
7. `qemu-provenance`：运行中进程命令行为
   `…/CTFLab.app/Contents/Resources/runtime/bin/qemu-system-x86_64 -name CTFLab-smoke …`（无宿主路径）；
8. `residue-check`：无运行状态文件、无 `network-*.json`、无 overlay 残留；
9. `app-unchanged`：运行前后 app 树哈希一致（`2d5a950e…`），运行未修改 app 内容；
10. `codesign-verify`：`codesign --verify --deep --strict --verbose=2` 返回 **0**，级别 **ad-hoc**。

证据：`~/Downloads/ctflab-app-e2e-20260915-final2/app-e2e-evidence.json`（逐步命令、退出码、输出与范围说明）。
全程未操作 UTM、未触碰用户已有虚拟机。

## 3. 单元测试（已验证）

`tools/tests/test_ctflab_app.py` 33 项，用一个**用 clang 现场编译的最小 QEMU 替身**（3 个可执行 +
两级 dylib 依赖 + 假 firmware），不依赖 Homebrew、不联网，覆盖：必需目录与 Info.plist；启动器无开发机
绝对路径且导出 `CTFLAB_RUNTIME_ROOT`，SBOM 不泄露构建机绝对路径；三个 QEMU 程序存在且可执行；
firmware/ROM 可解析，可选资源只在来源存在时复制；
非系统 dylib 全部位于 app 内且两级传递依赖完整；`otool -l` 无 Homebrew/conda/用户路径；
依赖无法解析时构建失败；MANIFEST 逐文件哈希与篡改检测；未登记文件被拒；SBOM `bundled=true`
与实际文件一致、缺文件即失败；磁盘/凭据/日志/PCAP 不进入 app；默认状态目录在 app 外；
目标已存在拒绝覆盖；失败清理不留半成品；树哈希稳定且对改动敏感；ad-hoc 记录为 ad-hoc、
unsigned 记录为 unsigned、未知签名身份直接失败；运行时选择三条规则（env → app 布局 → PATH 回退），
并断言受控运行时缺件时不得回退宿主 PATH；源码发布包必须包含 `ctflab_app.py`；旁车缺失/篡改、
禁止 RPATH、SBOM 构建机绝对路径、App/旁车并发发布、非法版本和损坏元数据均会被拒绝。

全量回归 280 项通过（247 项其他回归 + 33 项 Task 6.2 App 测试）。

2026-09-15 Codex 提交前复核修正：原实现的源码 release 白名单漏带 `ctflab_app.py`，App 目录使用
普通 `os.rename`、旁车直写且 `app verify` 未复核旁车，生产校验未检查 LC_RPATH，SBOM 记录了构建机
绝对路径；上述问题均已修正并由新增回归覆盖。最终候选已重新构建并完整执行 15/15 E2E。

## 4. 范围与限制（不得跨类宣称）

- **部分验证：干净环境可用性**——E2E 覆盖 Smoke（x86_64 BIOS）的导入/启动/健康/停止/重置；
  Kali（aarch64 + UEFI）经 `.app` 的完整启动、以及 `probe --matrix` 的 OVMF 路径**未在本轮 E2E 中执行**
  （仅验证了固件随包存在、aarch64 程序存在且可执行）；
- PyYAML 仍需联网 `pip install`（未内置解释器与依赖），因此“零手工依赖的完整安装”仍是后续任务；
- **未交付**：Developer ID 正式签名、公证、`.pkg`/DMG 安装器；公证状态一律记录为“未验证/后续任务”；
  ad-hoc 签名不代表任何开发者身份；
- **分发阻塞（已写入 MANIFEST 与 SBOM）**：
  1. 项目许可证未声明（`undeclared`），**禁止公开发布**；
  2. QEMU（GPL-2.0-only）未随附对应源码或书面要约，不得宣称 GPL 合规；
  3. `dtc`（libfdt）在 Homebrew keg 中没有许可证文本（`license_text_status: missing-in-keg`），
     本地构建使用 `--allow-incomplete-license-texts` 放行并如实记录；
- 未触碰 UTM 与任何虚拟机；app 内不含虚拟磁盘、凭据、日志、截图或 PCAP；
- 路径 A 的 UTM 结论不受本轮影响（Smoke/Basic 静态控制台 E2E 限定范围内通过；动态分辨率重启后
  复测失败、显示链路不稳定、当前包仅保证固定显示可用；路径 B 未实现）。

## 5. 停止条件复核

| 停止条件 | 本轮情况 |
|---|---|
| 缺少无法合法分发的组件 | 命中 1 项：`dtc` 许可证文本缺失 → 默认构建失败，仅本地测试放行并记录阻塞（见 §4） |
| 动态库引用 Homebrew/用户路径 | 未出现（打包后自检 + `otool -l` 全量扫描通过） |
| bundled QEMU 无法启动 Smoke | 未出现（DHCP/SSH 健康检查通过） |
| `.app` 运行后自身内容变化 | 未出现（运行前后树哈希一致） |
| 签名导致运行时失效 | 未出现（ad-hoc 后 `codesign --verify` 返回 0 且 Smoke 正常运行） |
| 需要 Developer ID / 公证凭据 / 新网络授权 | 未使用 Developer ID 与公证凭据；仅 PyYAML 的 pip 联网步骤（已记录） |
| 需要修改用户现有虚拟机或 UTM | 未发生 |
