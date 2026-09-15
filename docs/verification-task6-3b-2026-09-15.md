# CTFLab Task 6.3B 验证记录：许可证闭环与内置 Python 运行时（2026-09-15）

结论只使用四类状态标签：**已验证** / **部分验证** / **未验证** / **后续任务**。

## 0. 结论摘要

- **已验证**：项目许可证从 `undeclared` 落定为 **MIT**（`LICENSE` 入库并随包分发，代码中
  `PROJECT_LICENSE` 为单一来源）；`dtc`/libfdt 许可证文本补齐（上游 1.8.1 归档原样收录，
  `license_text_status: vendored`）；QEMU 的 GPL-2.0 §3 源码义务以随包 `SOURCE_OFFER.md`
  书面要约履行（精确版本、上游归档 URL、登记的真实 SHA-256、三年有效期）。
  `distribution_blockers` 清零、`license_texts_complete: true`。
- **已验证**：`CTFLab.app` 内置 Python 运行时与 PyYAML——最小 PATH + 独立 HOME 下首次 `doctor`
  即 0 退出（**无 venv、无 pip、无联网**）；`sandbox-exec` 拒绝 `/usr/bin/python3`、
  `/opt/homebrew`、`/opt/miniconda3`、`/usr/local`、`Python.framework` 后仍通过；
  smoke E2E 15/15 与 Kali ARM64 + UEFI E2E 29/29 条记录通过；运行后 App 树哈希不变、
  无新增 `__pycache__`。
- **发现并修复 3 个缺陷**（详见 §3）：`_formula_version` 的 Cellar 层级判断错误（SBOM 来源
  字段自 6.2 起静默降级为 `?`）；旧启动器未禁用字节码写入（真实运行会在已签名 bundle 内写
  `__pycache__`，破坏清单与签名，旧 E2E 靠环境变量掩盖）；E2E 新增的字节码检查最初把发行版
  自带预编译缓存误报为"运行写入"（检查改为运行前后对比）。
- **未验证/后续任务**：Developer ID 签名与公证（本轮不做，Gatekeeper 需接收者手动放行一次）；
  面向学生的**基盘镜像分发渠道与校验**（内容包不含虚拟磁盘，尚未有交付方案）。

## 1. 基线

- 分支 `feature/license-and-bundled-python`（基线 `main@bb25fb2`，Task 6.3A 成果已先提交）；
- 完整回归 **313 项通过**（新增 20 项：许可证合规、Python 运行时、Cellar 解析与 6.3B 文档守卫）；
- 本轮提交：`fd1ddc1`（许可证与 GPL 义务）、`bbfa1fe`（内置 Python/PyYAML）、本记录所在提交。

## 2. 交付物与证据

### 2.1 许可证闭环

| 项目 | 值 |
|---|---|
| 项目许可证 | MIT（`LICENSE`，`Copyright (c) 2026 zhangpu1211`） |
| 单一来源 | `ctflab_package.PROJECT_LICENSE`，SBOM/MANIFEST/`install.sh`/文档同源 |
| vendored 文本 | `tools/licenses/dtc/{GPL,BSD-2-Clause,README.license}` ← dtc 1.8.1 上游归档，SHA-256 与 keg `sbom.spdx.json` 记录一致（`23526015a6f1…`），来源登记见 `tools/licenses/PROVENANCE.md` |
| QEMU 源码要约 | `qemu-11.1.0.tar.xz`，SHA-256 `6ee1d1a61f68…`（实测下载核对 141MB 有效归档），URL/SHA-256/有效期由 `app verify` 与登记表强制一致 |
| 最终状态 | `license.status = MIT`、`license_texts_complete: true`、`distribution_blockers: []` |

### 2.2 内置 Python 运行时（真实构建）

构建命令（`--unsigned` 之外的真实构建，ad-hoc 签名）：

```bash
python3 tools/ctflab.py app build --out <out> \
  --python-runtime <cpython-3.12.14+20260901-aarch64-apple-darwin-install_only_stripped.tar.gz> \
  --python-runtime-sha256 81a359f1cfadd4da11766534c5913791cea55f26e1bb902cacd2a531bb1e4b2b \
  --pyyaml <pyyaml-6.0.3-cp312-cp312-macosx_11_0_arm64.whl> \
  --pyyaml-sha256 fc09d0aa354569bc501d4e787133afc08552722d3ab34836a80547331bb5d4a0
```

| 项目 | 值 |
|---|---|
| App | `~/Downloads/ctflab-app-build-phaseB/CTFLab.app`，树哈希 `69917483c516d1320a4a5037373c2117679ef4d007c40e8888372b5809a877a0`，MANIFEST SHA-256 `256c95a699b6…`，**720 个登记文件**、体积 264MB |
| 内置 Python | CPython 3.12.14（python-build-standalone 20260901，归档 SHA-256 `81a359f1…`），裁剪 30 项、解引用符号链接 1 个 |
| 内置 PyYAML | 6.0.3（wheel SHA-256 `fc09d0aa…`），`yaml/` 与 `_yaml/` 原样装入 `site-packages`，MIT 文本随包 |
| 签名 | ad-hoc；`codesign --verify --deep --strict` 返回 0（嵌套解释器与 `.so` 全部预签名） |

裁剪清单（逐项记录在 `MANIFEST.runtime.python.pruned`）：`pip`/`ensurepip`、`idle3`/`idlelib`、
`lib2to3`/`2to3`、`tkinter`/Tcl/Tk、`pydoc3`、`include/`、`share/`、`config-*`、静态链接下
运行时不加载的 `libpython3.12.dylib` 等 30 项。裁剪理由：CTFLab 只需 stdlib；Tcl/Tk 不随包
可避免许可证文本缺口；接收者不需要 pip。

### 2.3 smoke E2E（`tools/ctflab_app_e2e.py`，15/15 通过）

证据：`~/Downloads/ctflab-app-e2e-20260915-r5/app-e2e-evidence.json`。

| 步骤 | 结果 |
|---|---|
| verify-app | 720 文件，ad-hoc，树哈希 `69917483c516…`；旁车一致 |
| doctor-zero-setup | 最小 PATH（`/usr/bin:/bin:/usr/sbin:/sbin`）下**首次即 0 退出**：`python` 指向 `…/runtime/python/bin/python3（3.12.14）`、`PyYAML: available`、`运行时：bundled`，输出无 `/opt/homebrew` |
| host-python-denied | `sandbox-exec` 拒绝宿主 Python 位置后 `doctor` 仍 0 退出且为 bundled 解释器 |
| firmware-provenance | 拒绝 `/opt/homebrew` 读取后 App 内 `qemu-system-x86_64` 仍可启动（固件来自 App） |
| import/run/health/stop/reset | 全部通过；进程命令行证明 QEMU 来自 App |
| residue-check | 无运行状态与 overlay 残留 |
| app-unchanged | 运行前后树哈希一致（`69917483c516…`） |
| no-bytecode-writes | 运行后无新增 `__pycache__`（`-B` 生效；随包预编译缓存 1 处保持原样） |
| codesign-verify | `codesign --verify --deep --strict` 返回 0；级别 ad-hoc；公证未执行 |

### 2.4 Kali ARM64 + UEFI E2E（`tools/ctflab_app_kali_e2e.py`，29/29 通过）

证据：`~/Downloads/ctflab-app-kali-e2e-20260915-r5/kali-e2e-evidence.json`（来宾口令只经
标准输入传入，不进入证据与命令行）。

| 步骤 | 结果 |
|---|---|
| verify-app / app-runtime-assets | 720 文件、旁车一致；四个 QEMU/固件资产的哈希与登记值一致 |
| doctor-zero-setup | 最小 PATH 下**首次即 0 退出**：内置解释器 + PyYAML + App 内固件 |
| host-python-denied | 拒绝宿主 Python 与开发路径后 `doctor` 仍通过 |
| firmware-provenance | 拒绝 `/opt/homebrew` 后 App 内 `qemu-system-aarch64` + 固件仍可启动 |
| asset-baseline / copies | 基盘 `ca1034606a82…`、RAW NVRAM `8639a3fb43dd…` 与登记值一致，副本哈希一致 |
| import ×3 | kali-arm64（NVRAM 模板指向原始 RAW 副本）、smoke、basic-pentesting-2 |
| run / uefi-boot | QEMU 来自 App 内运行时；截屏分类 `login_ready`（未进入 UEFI Shell） |
| nvram-derivation | 派生 NVRAM 可写；App 模板与原始 RAW 未变 |
| health ×3 + guest-lab-warmup | 三节点健康检查通过；隔离网可达 |
| guest-connectivity | Kali 可达 smoke/basic（HTTP 200）、无默认路由、公网不可达（来宾内验证） |
| guest-poweroff / stop-1 / reboot / reboot-boot / health-after-reboot / stop-2 / reset | 正常关机、重启后再次到登录界面并健康、停止与重置完成 |
| residue-check / hash-invariants | 无残留；App 树、App 固件模板、原始基盘与原始 RAW NVRAM 哈希均未变化 |
| no-bytecode-writes | 运行后无新增字节码缓存（`-B` 生效） |
| qemu-img-check | App 内 `qemu-img check` 通过 |

## 3. 发现的缺陷与修复

1. **`_formula_version` Cellar 层级错误**（`tools/ctflab_app.py`）：判断写为
   `target.parent.name == "Cellar"`，而真实路径是 `<prefix>/Cellar/<formula>/<version>`，
   应比对两级之上的目录；因此 6.2 起所有 SBOM/MANIFEST 的来源字段都静默降级为
   `Homebrew qemu ?`。修复后真实构建记录 `Homebrew qemu 11.1.0`；新增 `FormulaVersionTests`
   用临时目录 + symlink 覆盖正确与错误路径。
2. **启动器未禁用字节码写入**（潜在缺陷，本轮修复）：旧启动器直接 `exec python3 <脚本>`，
   真实用户运行会在已签名 bundle 内写 `__pycache__`（尤其解释器换成内置之后，`yaml` 等
   导入也会写），破坏清单完整性与签名；旧 E2E 用 `PYTHONDONTWRITEBYTECODE=1` 环境变量掩盖了
   这一点。新启动器固定 `-B -s -E` 并导出 `PYTHONDONTWRITEBYTECODE`/`PYTHONNOUSERSITE`
   （子进程同样生效），E2E 增加"无新增 `__pycache__`"断言。
3. **E2E 检查自身的误报**（本轮发现并修正）：新增检查最初把发行版**自带**的预编译
   `__pycache__` 误判为"运行写入"；改为运行前后集合对比，并如实记录随包缓存数量。

## 4. 范围与限制（不得跨类宣称）

- **签名与公证**：ad-hoc（`codesign --verify --deep --strict` 返回 0）；**未做** Developer ID
  签名与公证。接收者首次打开需在"系统设置 → 隐私与安全性"手动放行一次；
  该摩擦属于 6.3B 已知边界，不是许可证或运行时问题。
- **基盘镜像分发**：内容包不含虚拟磁盘（沿用 6.1 边界），面向学生的镜像分发渠道与校验
  方式**未验证**，属后续任务。
- **体积**：App 从 218MB（6.3A）增至 264MB，主要来自内置解释器与 stdlib；裁剪清单已记录，
  未做进一步压缩。
- 内置 Python 来自 python-build-standalone 的官方构建（PSF-2.0，许可证文本随包），
  **不是**本项目自行构建；对外分发时该来源与哈希已登记在 SBOM，可复核。

## 5. 方法学说明（供复核）

- **裁剪不猜测**：只删除有明确理由的路径（开发工具、Tcl/Tk、pip、静态链接下不加载的
  libpython 等），逐项记入 MANIFEST；复制后断言符号链接零残留（`verify_app` 禁止符号链接，
  解引用用硬链接去重，避免别名重复占体积）。
- **宿主依赖的非空证明**：`sandbox-exec` 拒绝宿主 Python 与开发路径后重跑 `doctor`，
  并要求输出中的解释器路径仍在 App 内；三层证据（路径断言 + 沙箱拒绝 + 进程/文件哈希不变）
  共同支撑"零系统依赖"，而不是"本机恰好装了 Python 所以能跑"。
- **合规字段的可验证性**：`app verify` 强制校验 `source_offer` 的字段与登记表一致、且
  `SOURCE_OFFER.md` 正文确实包含所声明的版本/URL/哈希（防止文档过期）；`dtc` 文本的来源
  与哈希登记在 `tools/licenses/PROVENANCE.md`，可用上游归档复核。
- **历史记录不改写**：6.1/6.2/6.3A 验证记录保持原样（其 `undeclared`/`dtc` 缺失等陈述是
  当时事实）；状态守卫测试拆分为"设计文档断新状态、历史记录断旧状态"。

## 6. 复现命令

```bash
python3 -m unittest discover -s tools/tests          # 313 项

python3 tools/ctflab.py app build --out <out> \
  --python-runtime <pbs install_only_stripped .tar.gz> --pyyaml <pyyaml .whl>
python3 tools/ctflab.py app verify <out>/CTFLab.app

python3 tools/ctflab_app_e2e.py --app <out>/CTFLab.app --workdir <dir>
python3 tools/ctflab_app_kali_e2e.py --app <out>/CTFLab.app --workdir <dir> --password <口令>
```
