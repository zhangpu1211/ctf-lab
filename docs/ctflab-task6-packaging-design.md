# CTFLab Task 6.1 打包设计：可分发安装包与 `.ctflab` 内容包

> 状态：**设计 + 最小实现**（2026-09-15）。本文件描述 Task 6.1 的包格式、依赖检查、版本与
> SHA-256、SBOM/许可证清单和干净 Mac 用户验收脚本；**不包含** `CTFLab.app`、受控 QEMU 运行时
> 打包、动态库改 `@loader_path`、签名与公证（这些属于 Task 6 的后续子任务，未实现）。
> 交付定位是“可校验、可审计的源码级安装包 + 内容包”，不是已完成签名分发的应用。

## 1. 范围与非目标

**本子任务交付：**

- 可分发安装包（release bundle）：`ctflab-<version>-macos-arm64.tar.gz` + `.sha256` 旁车文件；
- `.ctflab` 内容包：`<profile>-<version>.ctflab`（Smoke、Basic Pentesting 2 各一份）+ `.sha256`；
- 版本与 SHA-256：包内 `MANIFEST.json` 逐文件哈希、`SHA256SUMS`、外层 tar.gz 哈希；
- SBOM/许可证清单：`SBOM.json`（机器可读）与 `THIRD_PARTY_LICENSES.md`（人读）；
- 依赖检查：`doctor` 保持唯一检查入口，打包清单额外声明 Python 版本要求与外部工具角色；
- 干净 Mac 用户验收脚本：`tools/ctflab_acceptance.py`（干净 HOME + 最小 PATH，导入/启动/停止/重置）；
- 单元测试：`tools/tests/test_ctflab_package.py`。

**明确不做（保持未实现状态）：**

- 不打包 `CTFLab.app`、不内置 QEMU 运行时与动态库、不做 `@loader_path` 修复；
- 不做签名、公证、DMG/PKG 安装器；`install.sh` 只是校验 + 复制 + 生成启动脚本；
- 不把任何虚拟磁盘、凭据、运行日志、截图、PCAP 放进包内或提交进 Git；
- 不改变默认 QEMU 命令、`run/stop/reset` 语义与 UTM 导出路径的行为；
- 不把本次交付写成“完整 Path A”或“干净环境完整安装已验证”——后者依赖签名分发，仍是后续任务。

## 2. Release bundle 格式

```
ctflab-<version>-macos-arm64.tar.gz
├── ctflab-<version>/
│   ├── MANIFEST.json          # 格式版本、CTFLab 版本、Python 要求、逐文件 sha256/size、生成时间、许可证状态
│   ├── SBOM.json              # 组件清单（本包、运行时依赖、外部工具；SPDX 标识；bundled=false/true）
│   ├── THIRD_PARTY_LICENSES.md
│   ├── SHA256SUMS             # 包内文件的相对路径校验清单
│   ├── install.sh             # 校验 MANIFEST 后复制到目标目录并生成 bin/ctflab 启动脚本
│   ├── README.md              # 仓库 README
│   ├── docs/…                 # 选定文档（快速使用、实施计划、动态分辨率设计）
│   └── tools/
│       ├── ctflab             # 可移植启动器（只用 PATH 中的 python3，不硬编码 conda 等开发解释器）
│       ├── ctflab.py / ctflab_inspect.py / ctflab_network.py / ctflab_utm.py
│       ├── ctflab_utm_fixture.json
│       ├── ctflab_acceptance.py
│       ├── ctflab_profiles/*.yaml
│       └── guest_fixes/**（仅脚本/配置文本）
└── ctflab-<version>-macos-arm64.tar.gz.sha256
```

规则：

- **白名单构建**：只收集上表列出的路径；任何磁盘/凭据/日志/缓存（`*.qcow2`、`*.raw`、`*.fd`、
  `*.img`、`*.vmdk`、`*.ova`、`.env*`、`*.pem`、`*.key`、`credentials*.txt`、`logs/`、`runtime/`、
  `probes/`、`__pycache__/`、`.git/`）在构建时被跳过，若显式命中则整体拒绝；
- **确定性归档**：条目按名称排序，`uid/gid=0`、`uname/gname` 为空、mtime 统一取生成时间；
  相同输入 + 相同 `generated_at` 产出逐字节相同的 tar.gz（单元测试断言）;
- **版本一致性**：发布包版本必须与 `tools/ctflab.py` 中的 `CTFLAB_VERSION` 一致，避免清单版本与
  实际运行器版本漂移；`--version` 仅接受该单一来源的当前值；
- **目标保护**：输出目录中同名目标已存在一律拒绝，不覆盖（与 `utm-export` 一致的排他发布原则）；
- **许可证状态**：项目自身代码以 **MIT** 发布（`ctflab_package.PROJECT_LICENSE` 单一来源），
  `MANIFEST.json.license.status = "MIT"`、`SBOM.json` 的同名组件与 `install.sh` 输出同一状态；
  根目录 `LICENSE` 全文随包分发（`RELEASE_DOC_FILES` 白名单）。第三方组件许可证见
  `THIRD_PARTY_LICENSES.md`。发布包不内置 QEMU 等第三方二进制，因此不含 GPL 源码义务；
  该义务只适用于 `.app`（见 `docs/ctflab-task6-app-runtime-design.md` 的书面要约设计）。

## 3. `.ctflab` 内容包格式

```
smoke-1.0.0.ctflab
├── content.json               # schema、id、name、version、requires_ctflab、逐文件哈希、镜像前提
├── profile/<id>.yaml          # 运行器配置（白名单字段，套用 validate_profile）
├── guest_fixes/<id>/**        # 该配置的来宾修复脚本/配置（可缺省）
├── README.md                  # 人读说明（含“不包含虚拟磁盘”的明确声明）
└── <name>.ctflab.sha256
```

规则：

- **不含虚拟磁盘**：`content.json.image.disk_included = false`，`source_required = true`；
  用户须自备原始镜像并按 `ctflab import <profile> <镜像>` 导入；
- **拒收清单**：与 release bundle 相同的磁盘/凭据/日志模式；另拒绝绝对路径、`..` 条目与
  未在 `content.json.files` 登记的额外文件；
- **版本门禁**：`requires_ctflab` 形如 `>=0.1.0`；当前 CTFLab 版本不满足时 `content verify` 失败；
- **配置校验**：包内 profile 必须通过 `ctflab.validate_profile`（拒绝任意 QEMU 原始参数）；
- **确定性**：同 release bundle（排序、固定 mtime、排他发布）。

## 4. 依赖检查

- `ctflab doctor` 是唯一的依赖检查入口（保持既有行为与提示文案），打包不新增第二套检查；
- `MANIFEST.json.requires.python` 声明最低 Python 版本（3.10，与 `ctflab.py` 的类型标注一致）；
- `SBOM.json` 逐条标注 `role`（`runtime`/`optional`/`external`）与 `bundled`；CTFLab 自身源码为
  `bundled=true`，第三方运行时与工具均为 `bundled=false`，因为本子任务不内置任何二进制；
- 干净验收脚本把 `doctor` 的输出作为机器可读步骤结果（退出码 + 关键字）记录到 JSON 证据。

## 5. 干净 Mac 用户验收脚本（`tools/ctflab_acceptance.py`）

在“干净 HOME + 最小 PATH（`/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin`，无 conda、无开发依赖，
保留 Homebrew 以提供已安装的 QEMU）”下顺序执行：

1. 校验 release bundle 的 `.sha256` 旁车与包内 `MANIFEST.json`/`SHA256SUMS`；
2. 解包到临时目录，确认启动器不含开发解释器硬编码；
3. 真正执行 `install.sh` 到独立安装目录，确认安装后启动器可执行；后续命令只使用该启动器；
4. 第一次 `doctor`：断言缺少 PyYAML 时给出可执行安装提示（退出码 1）；
5. 在临时 HOME 建 venv 并 `pip install pyyaml`（联网步骤；失败则如实记录并中止）；
6. 第二次 `doctor`：断言全部必选依赖 OK（退出码 0）；
7. `import`（默认复用本机已导入基础镜像；原始来源镜像缺失时这是文档化的等价输入）→
   `run --headless` → `health` → `stop` → `reset`；
8. 每步写 JSON 证据（命令、退出码、关键输出、耗时），失败即停并保留证据目录。

结论标签只允许“通过/失败/跳过（原因）”；本脚本**不**负责签名、公证、`.app` 安装，
运行通过也不构成 Task 6 的完整验收。

## 6. 与 Git 的边界

- 仓库新增内容仅有：本设计文档、`tools/ctflab_package.py`、`tools/ctflab_acceptance.py`、
  单元测试、验证记录与必要的文档/测试更新；
- `*.ctflab`、`dist/`、`*.tar.gz` 等打包产物写入 `.gitignore`，只在本机 `dist/` 或临时目录存在；
- 任何情况下不提交虚拟磁盘、凭据、日志、截图、PCAP（沿用既有规则与测试）。

## 7. 仍需决策

1. ~~项目许可证~~ 已决定：MIT（2026-09-15，`LICENSE` 入库，`PROJECT_LICENSE` 单一来源）；
2. `.app`/QEMU 运行时打包方案与签名、公证流程（Task 6 后续子任务）；
3. 内容包是否需要签名（当前只有 SHA-256 完整性，无来源认证）；
4. 面向学生的基盘镜像分发渠道与校验方式（内容包不含虚拟磁盘，该问题在 .app 交付路线中另行设计）。
