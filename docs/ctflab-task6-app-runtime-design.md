# CTFLab Task 6.2 设计：包含受控 QEMU 运行时的 `CTFLab.app`

> 状态：**已实现 + 真实 E2E 通过（限定范围）**，2026-09-15。本文件描述 `.app` 结构、运行时选择规则、
> 动态库打包与改写、SBOM/许可证、签名分级与验收方式。
> **未交付**：Developer ID 正式签名、公证、`.pkg`/DMG 安装器；项目许可证仍为 `undeclared`，
> **禁止公开发布**；一个随包组件的许可证文本缺失（见 §6）。

## 1. 目标与边界

目标：用户不再需要预装 Homebrew QEMU——`CTFLab.app` 自带 QEMU 运行时（aarch64 + x86_64 + qemu-img
及其非系统动态库、firmware/ROM/keymaps），在干净 Mac 上直接可用。

边界：

- 不内置 Python 解释器与 PyYAML（`.app` 使用 PATH 中的 `python3`，验收脚本用它建 venv 安装 PyYAML）；
- 不改默认 QEMU 命令语义、不改 `run/stop/reset` 行为、不动 UTM 路径；
- 不写入 app：状态、镜像、overlay、日志仍在 `~/Library/Application Support/CTFLab`；
- 本地构建，不签名分发：默认 ad-hoc 签名；没有 Developer ID 身份时**不会**冒充正式签名。

## 2. `.app` 结构

```
CTFLab.app/
├── Contents/
│   ├── Info.plist                      # CFBundleExecutable=CTFLab、版本与 MANIFEST 一致
│   ├── MacOS/CTFLab                    # 启动器：导出 CTFLAB_RUNTIME_ROOT 后 exec python3
│   ├── _CodeSignature/                 # codesign 写入（不在 MANIFEST 内）
│   └── Resources/
│       ├── ctflab/tools/…              # 与仓库同构的源码镜像（profile、guest_fixes、fixture）
│       ├── runtime/bin/                # qemu-system-aarch64、qemu-system-x86_64、qemu-img
│       ├── runtime/lib/                # 全部非系统动态库（闭包，install id 改为 @loader_path）
│       ├── runtime/share/qemu/         # firmware/ROM/keymaps（见 §5 白名单）
│       ├── licenses/<formula>/…        # 随包组件的许可证文本（含 edk2）
│       ├── MANIFEST.json               # 逐文件 SHA-256、运行时清单、签名分级、分发阻塞
│       ├── SBOM.json                   # 组件、版本、架构、哈希、许可证、bundled 状态
│       └── THIRD_PARTY_LICENSES.md     # 人读清单 + QEMU/GPL 义务单列
└── （app 外同级目录）CTFLab.app.sha256  # 旁车：app 树哈希 + MANIFEST.json 哈希
```

启动器内容经过测试断言：不含 `/opt/homebrew`、`/usr/local`、`/Users/`、`conda` 等开发机路径；
运行时根由 `Contents/Resources/runtime` 计算并导出为 `CTFLAB_RUNTIME_ROOT`。

## 3. 运行时选择规则（`tools/ctflab.py`）

1. `CTFLAB_RUNTIME_ROOT`（`.app` 启动器导出）→ 使用 `<root>/bin/<tool>`；
2. 否则识别 `.app` 布局（`…/Contents/Resources/runtime/bin`，按模块路径向上查找 `Resources` 目录）；
3. 否则回退 PATH（开发环境，等价于 brew 安装的 QEMU）。

受控运行时一旦激活，程序缺失也**不得**回退宿主 PATH；缺件必须由 `doctor`/调用方明确报错，
防止开发机恰好安装的 Homebrew QEMU 掩盖残缺 App。

固件查找同规则：受控运行时激活时**只查** app 内 `share/qemu`，**不回退**宿主路径——
避免“宿主兜底”掩盖缺件（E2E 用 `sandbox-exec` 拒绝 `/opt/homebrew` 读取来证明）。

`doctor` 会打印 `运行时：bundled（…）` 或 `运行时：PATH（…）`，并逐项列出三个 QEMU 程序的实际路径。

## 4. 动态库处理

- 用 `otool -L` 从三个 QEMU 程序递归收集非系统依赖（`/usr/lib/`、`/System/` 视为系统库，不复制）；
- `@rpath/…` 依赖先用二进制自身的 LC_RPATH 解析成真实文件；解析不到即失败（不猜测、不跳过）；
- 同名不同文件视为冲突并失败；`/opt/homebrew/opt/<f>` 与 Cellar 下的同一文件按真实路径去重；
- 复制到 `runtime/lib/`，文件名沿用加载器期望的 soname；
- `install_name_tool` 改写：程序 → `@loader_path/../lib/<name>`；dylib 自身 id 与依赖 →
  `@loader_path/<name>`；删除指向宿主安装位置的 LC_RPATH；
- 改写后所有 Mach-O 逐个签名（默认 ad-hoc）并**原样保留源二进制的 entitlements**
  （`com.apple.security.hypervisor` 是 HVF 的硬前提；丢失会以 `HV_NO_DEVICE` 创建 VGIC 失败告终），
  签名后断言副本的 entitlement 键和值与源文件完全一致，并把键集合与规范化值摘要记入
  `MANIFEST.json.runtime.entitlements`，再计算 MANIFEST 哈希；
- 打包后自检：任何 `otool -L` 非系统依赖必须落在 `runtime/lib/` 内、且不得残留
  `/opt/homebrew`、`/usr/local`、`/Users/`、`conda` 字符串；LC_RPATH 与 install id 同样纳入校验。

## 5. 随包的 QEMU 运行时资源（白名单）

`edk2-aarch64-code.fd`、`edk2-arm-vars.fd`（aarch64 UEFI 与 NVRAM 模板）、
`edk2-x86_64-code.fd`、`edk2-i386-vars.fd`（x86_64 UEFI）、`bios-256k.bin`、`bios.bin`（pc BIOS）、
`kvmvapic.bin`、`vgabios-stdvga.bin`、`vgabios-virtio.bin`、`efi-{e1000,pcnet,virtio}.rom`、
`pxe-{e1000,pcnet,virtio}.rom`、`keymaps/`、`edk2-licenses.txt`；`sgabios.bin` 存在才复制。
不复制其它架构固件（riscv/loongarch/ppc/sparc/hppa 等），也不复制 `qemu-img` 之外的宿主工具。

## 6. SBOM 与许可证

- 每个随包组件（QEMU、28 个 dylib、EDK2 固件）记录：版本、架构、SHA-256、许可证标识、来源，
  并把 Task 6.1 中的 `bundled=false` 全部改为 `bundled=true`（与实际文件一一对应，`app verify` 会复查）；
- SBOM 的来源字段只保留 formula/版本等可复现信息，不记录 Homebrew keg、用户目录或临时构建目录的
  绝对路径；
- 许可证文本从 Homebrew keg 收集（`COPYING*`/`LICENSE*`/`NOTICE*`/`LGPL-*`/`GPL-*` 等），
  EDK2 许可证文本随固件提供；
- **QEMU/GPL 义务单独列出**：GPL-2.0-only 随二进制分发需要提供对应源码或书面要约；
  本 app 未随附源码，因此**不得宣称 GPL 合规、不得公开发布**；
- 已知缺口：`dtc`（libfdt）在 Homebrew keg 中没有许可证文本——构建默认会**失败**；
  本地测试用 `--allow-incomplete-license-texts` 放行，并在 `MANIFEST.json.license.distribution_blockers`
  与 `SBOM.json`（`license_text_status: missing-in-keg`）中如实记录。对外分发前必须补齐文本；
- 项目自身许可证仍为 `undeclared`：不得公开发布，也不得宣称许可证问题已解决。

## 7. 签名分级

| 级别 | 触发条件 | 记录方式 |
|---|---|---|
| `unsigned` | `--unsigned`（仅诊断） | MANIFEST.signature.requested=unsigned；verify 记录 codesign 失败输出 |
| `ad-hoc` | 默认（`--sign-identity` 缺省或 `-`） | MANIFEST.signature.requested=ad-hoc；codesign 校验通过（rc=0） |
| `developer-id` | 显式 `--sign-identity "<Developer ID Application: …>"` 且本机 `security find-identity` 中存在 | 记录身份名与 codesign 校验结果 |
| `notarized` | 本轮**未执行** | 一律记录“未验证/后续任务”；需要既有 Keychain Profile 与用户明确授权 |

不接触任何密码/凭据：只接受已存在于 Keychain 的身份名与 profile 名；身份不存在时构建直接失败。

## 8. 排他发布与失败清理

在输出目录内创建随机临时 `<.CTFLab.app.*.tmp>/CTFLab.app`，全部构建与自检通过后通过 macOS
`renameatx_np(RENAME_EXCL)` 排他发布最终目录；旁车用排他硬链接发布。目标或旁车已存在（包括外部并发
创建）一律拒绝；若 App 已发布而旁车发布失败，只回滚本次 App 并保留外部目标。`app verify` 会同时
复核旁车中的 App 全树哈希与 `MANIFEST.json` 哈希；任一步失败清理本次临时内容，不触碰既有用户文件。

## 9. 验收方式

- 单元测试 `tools/tests/test_ctflab_app.py`（43 项，用 clang 现场编译的最小 QEMU 替身，不依赖 Homebrew；
  含 entitlement 键和值摘要、GRUB/LightDM 分类、口令必填与标准输入传递守卫）；
- 真实 E2E `tools/ctflab_app_e2e.py`：独立 HOME + 最小 PATH（**不含 `/opt/homebrew/bin`**）下
  校验 app → doctor（bundled 运行时）→ venv 安装 PyYAML → `sandbox-exec` 固件来源证明 →
  import → run --headless → health（DHCP/SSH）→ stop → reset → 无残留 → app 树哈希不变 →
  `codesign --verify --deep --strict` 按实际级别记录；过程中从进程命令行证明 QEMU 来自 `.app`。
- 证据与结论见 `docs/verification-task6-2-2026-09-15.md`；Kali ARM64 + UEFI 的真实运行验收见
  `docs/verification-task6-3a-2026-09-15.md`（该记录同时给出 entitlement 丢失缺陷的定位与修复）。

## 10. 仍需决策

1. 项目许可证（公开分发前提）与 `dtc`/libfdt 许可证文本的补齐方式；
2. 是否随附 QEMU 对应源码或书面要约以满足 GPL 分发义务；
3. Developer ID 身份与公证 Keychain Profile（依赖用户提供，本轮未使用）。
