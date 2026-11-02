# CTFLab Mac 本地打包与发布门禁

> **强制入口**：任何 Mac `CTFLab.app` 构建、重打包、ZIP 制作或 Release 发布前，
> 必须先读完本文的“开工前门禁”和“发布前最终门禁”，再核对当前状态与真实工作区。
> 本文记录已经实际发生过的问题，不代替当前代码、测试和产物证据。

## 1. 适用范围与发布判据

适用于 Apple Silicon Mac 上的 `CTFLab.app`、Mac ZIP、源码包、证据包和 GitHub
Release。Windows 安装器有独立构建链，不能因为本轮只改 Mac 文档就重打或替换 Windows。

一个包只有同时满足以下条件，才可称为“可交付包”：

1. 产物从冻结后的最终源码和工作区构建，来源提交、版本、文件名一致。
2. 源 QEMU、重签名后的随包 QEMU、受控 SPICE 客户端及显示应用副本都通过真实能力探针。
3. `app verify`、严格代码签名、内置 Python/PyYAML、完整运行时导入和运行时动态库闭包通过。
4. Mac ZIP 包含顶层 `CTFLab.app` 与同级 `CTFLab.app.sha256`，且对它自己的解压结果
   执行过 `app verify`。
5. 源码 ZIP、证据 ZIP、`SHA256SUMS.txt` 已生成，回下载后哈希、解包和关键校验通过。

通过构建、`app verify`、进程存活或截图中的 QEMU 窗口，各自只能证明较窄范围。发布
说明必须区分构建门禁、文件回读、真实来宾显示和人工桌面验收。

## 2. 开工前门禁

开始前按顺序执行并保存实际命令与结果：

```bash
cd /Users/pufei/Downloads/ctf-lab
sed -n '1,220p' AGENTS.md
sed -n '1,360p' PACKAGING.md
sed -n '1,360p' README.md
git status --short --branch
git rev-parse HEAD
```

还须完成以下核对：

- 确认正式项目目录、分支、HEAD、已有修改和未跟踪文件；保留用户改动，不自动 stash、
  reset、clean、切分支或拉取覆盖。
- 查找已有 `CTFLab.app`、同名 ZIP、旧 Release 和正在运行的旧 App。多个包可能使用相同
  bundle ID，必须比较完整路径，不能只按应用名或进程名识别。
- 记录用户正在运行的 Kali/靶机。未经本次明确授权，不停止、重启、重置或替用户启动 VM。
- 所有输出写入新的、尚不存在的目录。构建器和归档步骤都应排他写入，不覆盖旧证据。
- 冻结本轮产品源码后再构建。若构建后仍修改随包源码、配置、GUI、白名单或运行时输入，
  必须重新回归并重建，旧构建只能作为历史证据。

建议在证据根记录：

| 字段 | 必须记录的内容 |
| --- | --- |
| 时间 | 构建和验证的本地时间、UTC 时间 |
| 源码 | 分支、完整提交 SHA、工作区状态 |
| 版本 | `tools/ctflab.py` 的 `CTFLAB_VERSION` 与产物版本 |
| 构建输入 | QEMU、SPICE 客户端、Python、PyYAML 的绝对路径和 SHA-256 |
| 签名 | ad-hoc、Developer ID 或 unsigned；是否公证 |
| 产物 | App、ZIP、源码包、证据包路径和 SHA-256 |
| 验证 | 命令、退出码、关键输出、真实来宾范围 |
| 现场 | 仍运行的 App/QEMU、状态目录；不得只留历史 PID |

## 3. 已发生的故障与硬门禁

### 3.1 客户端存在但 QEMU 没有 SPICE 后端

**现象**：App 内看得到 `spicy` 和 SPICE 动态库，Kali 却报缺少 SPICE 显示后端或
`spicevmc`，QEMU 启动流程不完整。

**根因**：把客户端文件存在误当成 QEMU 构建具备 SPICE 显示能力；仅检查动态库也不足以
证明 `-display spice`、`-chardev spicevmc` 和 `virtserialport` 可用。

**硬门禁**：构建器必须分别探测源 QEMU 和重签名后的随包 QEMU：

```bash
"$QEMU" -machine none -display help
"$QEMU" -machine none -chardev help
"$QEMU" -machine none -device help
```

输出必须包含 `spice`/`spice-app`、`spicevmc` 和 `virtserialport`。结果还应写入
`MANIFEST.runtime.spice_capabilities`，由 `app verify` 再次执行真实探针。

### 3.2 把 Homebrew 通用 `spicy` 当成 CTFLab 显示客户端

**现象**：Kali 已启动，QEMU 正常，但桌面没有出现；客户端日志为：

```text
option parsing failed: Unknown option --clipboard
```

**根因**：Homebrew `spicy` 接受 `--uri`，但不接受 CTFLab 必传的
`--clipboard`、`--qemu-pid`、`--state-file`、`--display-quality` 等参数。

**硬门禁**：客户端必须从 `tools/spice_client/ctflab_spicy.c` 构建。参考编译入口：

```bash
clang -Wall -Wextra -Werror -mmacosx-version-min=26.0 \
  tools/spice_client/ctflab_spicy.c \
  -o /absolute/new-output/ctflab-spicy \
  $(pkg-config --cflags --libs spice-client-gtk-3.0 gtk+-3.0)
```

构建源客户端、`runtime/bin/spicy` 和 `CTFLabDisplay.app/Contents/MacOS/spicy`
三处都要满足：

```bash
"$CLIENT" --ctflab-capabilities
```

预期身份为 `ctflab-spicy`，状态协议为 `CTFLAB_SPICE_STATE`，参数清单完整。禁止传
`/opt/homebrew/bin/spicy`、只改文件名或通过复制旧客户端冒充受控客户端。

### 3.3 发布白名单漏掉运行依赖

**现象**：窗口能打开或 `app verify` 能通过，但某个页面、场景命令或延迟导入报
`ModuleNotFoundError`。

**实际案例**：

- 2026-10-15 的 GUI 验收发现 App 缺少整套 `ctflab_scenario*` 运行模块。
- 2026-11-01 发现 `RELEASE_TOOL_FILES` 缺少 `ctflab_external_attach.py`、
  `ctflab_external_l2.py`、`ctflab_kali_attach.py`，通用 v2 流程在 App 内置 Python 中
  真实报错。
- 后续白名单变更若发生在构建之后，旧包会含旧依赖清单；必须从代码冻结后的最终提交重建。

新增 Python 模块、配置或数据依赖时，必须同时检查：

1. 是否进入 `ctflab_package.RELEASE_TOOL_FILES` 或有明确的其他复制白名单。
2. 在隔离复制目录中删除对仓库 `cwd`/`PYTHONPATH` 的依赖，再用 `-I -B` 执行对应命令。
3. 至少覆盖入口页、GUI 调用的 CLI 子命令和延迟导入，不以模块文件“看起来在包里”代替。

### 3.4 内置 Python 或 PyYAML 不可用

**现象**：构建后的 App 启动失败、GUI 调用的 CLI 退出，或完整运行时导入门禁失败。

**实际案例**：2026-11-02 一次重打使用未完成验证的 Python 运行时输入，完整运行时导入
门禁失败；失败包 `mac-final-r1` 被保留。随后使用已验证 App 内的 Python 3.12.15
运行时，并通过完整导入、PyYAML、动态库和许可证校验后才生成 `mac-final-r2`。

**硬门禁**：

- 使用 `python-build-standalone` 的受控运行时和与架构匹配的 PyYAML wheel；
- 运行时、wheel 记录来源和 SHA-256；
- 使用 App 内 Python 执行完整导入探针，不依赖系统 Python、Homebrew Python 或
  `PYTHONPATH`；
- 若复用旧 App 的运行时，先核对版本、架构、摘要和许可证仍相同，再作为新构建输入；
- `app verify` 必须验证内置 Python、PyYAML、许可证和运行时引用。

### 3.5 Apple Silicon 上的 unsigned App

**现象**：`--unsigned` 产物在 Apple Silicon 上可能被内核直接 `SIGKILL`，无法作为正常
用户包验收。

**规则**：`--unsigned` 只用于签名诊断。可交付本地包至少使用 ad-hoc 签名，并在
`install_name_tool` 改写和嵌套显示 App 创建后重新签名全部 Mach-O。必须保留源二进制的
entitlements，尤其是 HVF 虚拟化能力。

```bash
codesign --verify --deep --strict --verbose=2 /absolute/CTFLab.app
```

ad-hoc 不等于 Developer ID，也不等于公证。没有真实证书和公证回执时，发布说明必须保留
“ad-hoc、未公证”，不能写成正式签名发行。

### 3.6 版本与构建入口不一致

**规则**：`--version` 必须与 `tools/ctflab.py` 的 `CTFLAB_VERSION` 一致；`Info.plist`、
`MANIFEST.json`、Release 标题、ZIP 文件名和源码标签必须使用同一版本。

验证入口是 shell 启动器，不是 Python 文件：

```bash
./tools/ctflab app verify /absolute/CTFLab.app
```

不要执行 `python3 tools/ctflab ...`。后者会把 shell 启动器当 Python 源码解析，
产生与 App 无关的 `SyntaxError`。

### 3.7 错误目录、嵌套 App 或旧包混淆

历史输出曾出现 `.../CTFLab.app/CTFLab.app` 路径和多个相同 bundle ID 的预览包。
构建、UI 验收和发布前都要锁定完整 App 路径，并检查：

```bash
test -f "$APP/Contents/Info.plist"
test -f "$APP/Contents/MacOS/CTFLabGUI"
test ! -e "$APP/CTFLab.app"
```

正在运行的 App 可能来自 App Translocation
`/private/var/folders/.../AppTranslocation/.../CTFLab.app`。在验证新包前先识别进程的
实际可执行路径，并请用户退出旧窗口；不要仅凭窗口标题判断正在运行的是哪个包。

### 3.8 Mac ZIP 漏带 App 旁车

**现象**：App 本体和签名正常，但 ZIP 顶层没有 `CTFLab.app.sha256`，从 ZIP 解压后
`app verify` 报“缺少普通旁车校验文件”。

**硬门禁**：制作 ZIP 时显式同时加入 App 和旁车，并在全新目录解压后验证：

```bash
(
  cd "$APP_PARENT"
  zip -q -X -r "$RELEASE_ZIP" CTFLab.app CTFLab.app.sha256
)

mkdir -p /absolute/new/readback
ditto -x -k "$RELEASE_ZIP" /absolute/new/readback
./tools/ctflab app verify /absolute/new/readback/CTFLab.app
```

禁止把旁车从别处手工复制到解压目录后冒充 ZIP 自带旁车。必须通过 archive listing
确认 `CTFLab.app.sha256` 位于顶层：

```bash
unzip -Z1 "$RELEASE_ZIP" | grep -E '^CTFLab\.app/$|^CTFLab\.app\.sha256$'
```

### 3.9 源码 ZIP 的中文文件名解包失败

**现象**：Git 源码 ZIP 在 macOS `unzip` 下可能对中文文件名报
`Illegal byte sequence`，看起来像源码损坏，实际是命令行解包编码限制。

**正确做法**：先检查压缩完整性，再使用 macOS 原生 `ditto` 或 Finder“归档实用工具”：

```bash
unzip -tq "$SOURCE_ZIP"
mkdir -p /absolute/new/source-readback
ditto -x -k "$SOURCE_ZIP" /absolute/new/source-readback
```

解包失败时保留日志，换原生解包器重试，不删除源码包或把它直接判成内容损坏。

### 3.10 运行时动态库与许可证漂移

Homebrew 升级后，同名 glib、pcre2 等动态库可能换版本。历史包中曾出现不同 glib
大版本的运行时闭包，不能只按同目录或同文件名复用。

每次构建都要检查：

- 所有 Mach-O 依赖都在 App 内解析为相对路径，没有 `/opt/homebrew` 或开发者目录泄漏；
- 动态库闭包、Mach-O 最低 macOS、架构和签名全部通过；
- SBOM、许可证文本、QEMU 源码书面要约与实际随包二进制一致；
- `MANIFEST.json`、`CTFLab.app.sha256` 和最终 App 树摘要来自同一最终产物。

`--allow-incomplete-license-texts` 只用于本地测试。许可证缺件时默认停止发布。

## 4. 构建顺序

1. 冻结产品源码，完成受影响测试和 GUI/Swift 检查。
2. 验证并记录 QEMU、受控 SPICE 客户端、Python、PyYAML 输入。
3. 选择新的构建目录，确认 `CTFLab.app` 和旁车都不存在。
4. 执行 `app build`，默认使用 ad-hoc；没有明确证书和授权时不要声称 Developer ID。
5. 立即运行 `app verify`、严格签名、客户端能力探针和内置运行时导入。
6. 在授权范围内启动独立测试实例，确认真实图形窗口、登录、SPICE 状态和正常退出；
   未执行时明确标为未验证。
7. 生成 Mac ZIP、源码 ZIP、证据 ZIP 和 SHA 清单。
8. 对每个归档执行 CRC/哈希检查，对 Mac ZIP 和源码 ZIP 做原生解包回读。
9. 只有在最终回读全部通过后才创建或公布 Release。

构建命令中的路径必须替换成已核验的本轮绝对路径：

```bash
./tools/ctflab app build \
  --out "$NEW_PACK_ROOT/mac" \
  --version "$VERSION" \
  --qemu-root "$QEMU_ROOT" \
  --spice-client "$CONTROLLED_SPICY" \
  --python-runtime "$PYTHON_RUNTIME" \
  --python-runtime-sha256 "$PYTHON_RUNTIME_SHA256" \
  --pyyaml "$PYYAML_WHEEL" \
  --pyyaml-sha256 "$PYYAML_SHA256"
```

版本参数可省略；若显式传入，必须等于 `CTFLAB_VERSION`。需要完整 Tk/cryptography
运行时能力时，还要提供经过核验的 `--generic-runtime-manifest`。

## 5. 发布前最终门禁

以下每项都要有日志或机器可读证据：

- `app verify` 通过登记文件、旁车、运行时引用、QEMU SPICE、受控客户端、许可证和签名检查。
- `codesign --verify --deep --strict --verbose=2` 通过，entitlements 未被降级。
- 两个随包 `spicy` 的 `--ctflab-capabilities` 都通过。
- App 内 Python/PyYAML 的完整导入和至少一个 GUI 调用 CLI 子命令通过。
- Mac ZIP 顶层有旁车；全新解压后无需补文件即可通过 `app verify`。
- 源码 ZIP 来自准确的最终提交，关键修复文件与当前源码逐字一致。
- 证据 ZIP 包含失败现场、最终日志、构建输入摘要、MANIFEST/App 摘要和命令范围。
- `SHA256SUMS.txt` 覆盖 Mac、源码和证据资产，并在同目录执行
  `shasum -a 256 -c SHA256SUMS.txt`。
- GitHub 回下载后再次核对哈希、原生解包、`app verify`、签名、客户端探针和源码提交。
- 发布说明写明 ad-hoc/Developer ID、公证状态、真实来宾验证范围、Windows 是否重建。
- 旧标签和旧资产不被覆盖。已经对外公布的包需要修正时，发布新补丁标签；不要静默替换
  同名二进制。

推荐的回读顺序：

```bash
mkdir -p "$NEW_READBACK_ROOT"
gh release download "$TAG" --dir "$NEW_READBACK_ROOT"
(
  cd "$NEW_READBACK_ROOT"
  shasum -a 256 -c SHA256SUMS.txt
)

mkdir -p "$NEW_READBACK_ROOT/mac"
ditto -x -k "$NEW_READBACK_ROOT/$MAC_ZIP" "$NEW_READBACK_ROOT/mac"
./tools/ctflab app verify "$NEW_READBACK_ROOT/mac/CTFLab.app"
codesign --verify --deep --strict --verbose=2 \
  "$NEW_READBACK_ROOT/mac/CTFLab.app"
```

## 6. 失败处置

- 先保存失败日志、命令、退出码、输入摘要和现场；不要覆盖失败目录后只留成功结果。
- 同一错误连续两次没有改善时停止重复重建，检查真实调用链、输入类型、签名阶段和最终路径。
- 已生成但未通过最终门禁的包标记为 `invalid-*` 或保留在旧输出目录，不进入 Release。
- 修复产品源码后从最终代码重跑受影响测试；修复打包步骤后重新制作整个归档，不从坏 ZIP
  中局部补文件充当新包。
- 已公开的错误 Release 保留原标签；新修复使用新标签，发布说明明确替代关系。
- 结束前更新 `README.md` 的“项目进度”和“未完成”部分，并重新核验仍在运行的 App/VM、状态目录、
  Git 工作区和发布资产。

## 7. 最小交接语

> 继续 CTFLab Mac 打包，正式目录是 `/Users/pufei/Downloads/ctf-lab`。先读
> `AGENTS.md`、`PACKAGING.md` 和 `README.md`。核对 Git、工作区、已有 App/VM 和发布标签，保留现有
> 改动。先完成开工前门禁，再从冻结源码构建到全新目录；必须验证受控 SPICE 客户端、
> App 内 Python/PyYAML、签名、顶层旁车、原生解包、真实来宾范围、GitHub 回读和哈希。
> 不覆盖旧 Release，不把构建成功或能力探针冒充完整图形 E2E。
