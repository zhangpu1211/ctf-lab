# CTFLab Task 6.2 设计：包含受控 QEMU 运行时的 `CTFLab.app`

> 状态：**已实现 + 真实 E2E 通过（限定范围）**，2026-09-15。本文件描述 `.app` 结构、运行时选择规则、
> 动态库打包与改写、SBOM/许可证、签名分级与验收方式。
> 许可证与 GPL 义务已在 Task 6.3B 闭环：项目代码 MIT（随包 `LICENSE`），`dtc`/libfdt 许可证文本
> 由仓库 `tools/licenses/` 提供（`license_text_status=vendored`），QEMU 源码义务以随包
> `SOURCE_OFFER.md`（GPL-2.0 §3 书面要约）履行。
> **未交付**：Developer ID 正式签名、公证、`.pkg`/DMG 安装器——对外分发前仍建议先完成，否则
> 每个接收者需要在系统设置中手动放行（见 §7）。

## 1. 目标与边界

目标：用户不再需要预装 Homebrew QEMU——`CTFLab.app` 自带 QEMU 运行时（aarch64 + x86_64 + qemu-img
及其非系统动态库、firmware/ROM/keymaps），在干净 Mac 上直接可用。

边界：

- **内置 Python 3.12 解释器与 PyYAML**（python-build-standalone，见 §11）：启动器只使用 app 内
  解释器，缺失即报错，**不回退**系统 Python；接收者无需 venv/pip/联网；
- 不改 `stop/reset` 行为；`run` 的默认策略是 Kali 图形自动 SPICE + user-mode NAT，其他节点
  Cocoa + 管理网隔离，显式 `--display cocoa` 可用于兼容性排障；不动 UTM 路径；
- 不写入 app：状态、镜像、overlay、日志仍在 `~/Library/Application Support/CTFLab`；
- 本地构建，不签名分发：默认 ad-hoc 签名；没有 Developer ID 身份时**不会**冒充正式签名。

## 2. `.app` 结构

```
CTFLab.app/
├── Contents/
│   ├── Info.plist                      # CFBundleExecutable=CTFLab、版本与 MANIFEST 一致
│   ├── MacOS/CTFLab                    # 启动器：导出 CTFLAB_RUNTIME_ROOT 后 exec 内置解释器
│   ├── _CodeSignature/                 # codesign 写入（不在 MANIFEST 内）
│   └── Resources/
│       ├── ctflab/tools/…              # 与仓库同构的源码镜像（profile、guest_fixes、fixture）
│       ├── runtime/bin/                # qemu-system-aarch64、qemu-system-x86_64、qemu-img
│       ├── runtime/lib/                # 全部非系统动态库（闭包，install id 改为 @loader_path）
│       ├── runtime/share/qemu/         # firmware/ROM/keymaps（见 §5 白名单）
│       ├── runtime/python/             # 内置 Python 3.12（裁剪后 stdlib + site-packages/yaml，见 §11）
│       ├── licenses/<formula>/…        # 随包组件的许可证文本（含 edk2、python、pyyaml、dtc vendored）
│       ├── LICENSE                     # 项目自身 MIT 许可证全文
│       ├── SOURCE_OFFER.md             # QEMU 对应源码书面要约（GPL-2.0 §3，见 §6）
│       ├── MANIFEST.json               # 逐文件 SHA-256、运行时清单、签名分级、许可证状态
│       ├── SBOM.json                   # 组件、版本、架构、哈希、许可证、bundled 状态
│       └── THIRD_PARTY_LICENSES.md     # 人读清单 + QEMU/GPL 义务单列
└── （app 外同级目录）CTFLab.app.sha256  # 旁车：app 树哈希 + MANIFEST.json 哈希
```

启动器内容经过测试与 `verify_app` 断言：不含 `/opt/homebrew`、`/usr/local`、`/Users/`、`conda`
等开发机路径，不含 `command -v python3`（禁止探测系统解释器）；运行时根由
`Contents/Resources/runtime` 计算并导出为 `CTFLAB_RUNTIME_ROOT`，解释器固定为
`runtime/python/bin/python3` 且以 `-B -s -E` 调用（见 §11）。

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
- **回退来源**：keg 内没有文本的组件（如 `dtc`/libfdt）回退到仓库 `tools/licenses/<formula>/` 的
  vendored 文本，来源与哈希登记在 `tools/licenses/PROVENANCE.md`；SBOM 记
  `license_text_status: "vendored"`。keg 与 vendored 都没有时构建仍然失败（除非显式
  `--allow-incomplete-license-texts`），不猜测；
- **项目自身许可证**：MIT（`ctflab_package.PROJECT_LICENSE` 单一来源）。`LICENSE` 全文随包放在
  `Contents/Resources/LICENSE`，`MANIFEST.json.license.status = "MIT"`；
- **QEMU/GPL 义务单独列出**：GPL-2.0-only 随二进制分发需要提供对应源码或书面要约；本 app 不随附
  源码，改为随包 `SOURCE_OFFER.md`（GPL-2.0 §3 书面要约）：写明 QEMU 精确版本、上游源码归档 URL
  与 SHA-256（登记于 `QEMU_SOURCE_SHA256`，未知版本直接构建失败）、有效期（分发之日起三年）与获取
  渠道；`MANIFEST.json.license.source_offer` 与 `app verify` 校验要约字段、与登记表的一致性以及
  `SOURCE_OFFER.md` 内容确实包含所声明的版本/URL/哈希，防止文档过期。

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

- 单元测试 `tools/tests/test_ctflab_app.py`（58 项，用 clang 现场编译的最小 QEMU/Python 替身，
  不依赖 Homebrew；含 entitlement 键和值摘要、许可证与书面要约、Python 裁剪与符号链接解引用、
  GRUB/LightDM 分类、口令必填与标准输入传递守卫）；
- 真实 E2E `tools/ctflab_app_e2e.py`：独立 HOME + 最小 PATH（**不含 `/opt/homebrew/bin`**）下
  校验 app → doctor **首次即 0 退出**（内置解释器 + PyYAML + bundled 运行时，无 venv/pip）→
  `sandbox-exec` 拒绝宿主 Python 位置后 doctor 仍通过 → `sandbox-exec` 固件来源证明 →
  import → run --headless → health（DHCP/SSH）→ stop → reset → 无残留 → app 树哈希不变与
  无新增 `__pycache__` → `codesign --verify --deep --strict` 按实际级别记录；
  过程中从进程命令行证明 QEMU 来自 `.app`。
- 证据与结论见 `docs/verification-task6-2-2026-09-15.md`、`docs/verification-task6-3a-2026-09-15.md`
  （entitlement 丢失缺陷的定位与修复）与 `docs/verification-task6-3b-2026-09-15.md`
  （许可证闭环与内置 Python 运行时）。

## 12. 图形入口（Task 6.4）

主入口改为原生 SwiftUI/AppKit 可执行文件（`Contents/MacOS/CTFLabGUI`，`CFBundleExecutable` 指向它）；
CLI 启动器保留在 `Contents/Resources/bin/`（`ctflab-cli` 与兼容名 `CTFLab`），由 GUI 以固定路径调用。

- **不做第二套逻辑**：GUI 只调用既有 CLI（`dist verify --json`、`import <profile> <基盘> --manifest`、
  `run`、`status --json`、`health <profile> --json`、`stop --all`、`reset <profile>`），
  另以固定动作调用 `run` 的节点选择；Kali 的联网与 SPICE 自动分辨率由 CLI 默认策略统一处理，
  不解析任意 QEMU 参数、不绕过清单哈希；
- **状态机门禁**：校验未通过时导入/启动禁用；未全部导入时启动/重置禁用；运行中禁止再次启动；
  执行中所有动作禁用；重新打开 App 时通过 `status --json` 恢复“已导入/运行中”显示；
- **重置必须确认**：确认框明确说明 overlay 中的实验改动会丢失，只有确认后才逐节点 `reset`；
- **命令拼接**：参数以数组传递（不做 shell 拼接），路径含空格保持为单一参数；基盘路径由
  `DISTRIBUTION.json` 的 `profile + role=base` 条目解析，找不到即报错而不是猜文件名；
- **失败可见**：CLI 的 stderr/stdout 原样进入日志面板，失败时给出“命令 + 退出码 + 原文”的
  可复制错误块；主可执行文件由代码签名覆盖、其余文件由 `MANIFEST.json` 覆盖；
- **放置约定**：CLI 启动器放在 `Contents/Resources/bin` 而非 `Contents/MacOS`——codesign 会把
  `MacOS/` 里的额外可执行文件当作嵌套代码要求单独签名，而脚本签名依赖扩展属性、不适合随包分发；
  放在 `Resources/` 里由 bundle 签名按哈希封存（`app verify` 会检查两个启动器都在位）。

源码在仓库 `gui/`（`GuiCore.swift` 状态机与命令构造、`GuiApp.swift` SwiftUI 界面、
`GuiCoreTests.swift` 无需 XCTest 的核心测试），随包镜像到 `Contents/Resources/ctflab/gui/` 供审计。

## 10. 仍需决策

1. ~~项目许可证~~ 已决定：MIT（2026-09-15）；
2. ~~`dtc`/libfdt 许可证文本补齐方式与 QEMU 源码义务~~ 已实现：仓库 vendored 文本
   （`tools/licenses/`，见 PROVENANCE.md）+ 随包书面要约（`SOURCE_OFFER.md`）；
3. Developer ID 身份与公证 Keychain Profile（依赖用户提供，本轮未使用）；
4. 面向学生的基盘镜像分发渠道与校验方式。

## 11. 内置 Python 运行时与 PyYAML（2026-09-15）

目标：接收者机器**不需要**任何 Python 环境——无系统解释器、无 venv、无 pip、无联网。

- **来源**：python-build-standalone 的 `install_only_stripped` 发行版
  （`cpython-<版本>+<release>-aarch64-apple-darwin-...tar.gz`，实测 3.12.14 归档 25MB/解压 66MB）；
  构建时必填 `--python-runtime` 与其可选 SHA-256，归档成员逐个校验路径与类型后再解包；
- **复制与裁剪**：复制进 `runtime/python/`，按 `PYTHON_PRUNE_GLOBS` 裁剪 30 项（pip/ensurepip、
  idle/lib2to3、tkinter/Tcl/Tk、include/share、静态链接下运行时不加载的 libpython 等），
  逐项记录到 `MANIFEST.runtime.python.pruned`；裁剪不猜测，新增删除项必须写明理由；
- **符号链接**：解引用为硬链接（去重别名体积），复制后断言零残留——`verify_app` 禁止 app 内
  出现任何符号链接；
- **PyYAML**：必填 `--pyyaml`（wheel 或目录），`yaml/` 与 `_yaml/` 原样装入
  `lib/python3.X/site-packages/`；C 扩展（`_yaml*.so`）依赖均为系统库，保留并签名；
  MIT 许可证文本从 wheel 的 `dist-info/licenses/` 提取到 `licenses/pyyaml/`；
- **解释器与 stdlib 许可证**：PSF `LICENSE.txt` 从发行版提取到 `licenses/python/`；
- **签名与扫描**：递归签名 python 树内全部 Mach-O（解释器、扩展模块），引用扫描覆盖该子树
  （嵌套未签名代码会让 `codesign --verify --deep --strict` 失败）；
- **启动器**：固定 `runtime/python/bin/python3`，缺失即报错、不回退系统 Python；以
  `-B -s -E` 调用并导出 `PYTHONDONTWRITEBYTECODE`/`PYTHONNOUSERSITE`——**禁止**在已签名
  bundle 内写 `__pycache__`（否则清单与签名被破坏；旧启动器的这一潜在缺陷已修复并加断言）；
- **SBOM**：`CPython` 与 `PyYAML` 组件记录版本、来源、归档/wheel SHA-256、`directory`
  与裁剪清单；`app verify` 校验组件目录存在、`runtime.python` 字段与 Python 条目的完整性。

实测（`docs/verification-task6-3b-2026-09-15.md`）：最小 PATH + 独立 HOME 下首次 `doctor`
即 0 退出；`sandbox-exec` 拒绝宿主 Python 位置后仍通过；smoke E2E 15/15；App 体积
218MB → 264MB。
