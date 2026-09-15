# CTFLab Task 6.1 验证记录：可分发安装包与 `.ctflab` 内容包（2026-09-15）

本文记录 Task 6.1 的交付与实测证据。结论只使用四类状态标签：**已验证** / **部分验证** /
**未验证** / **后续任务**。

## 1. 交付内容

| 交付物 | 位置（本机，不入库） | 状态 |
|---|---|---|
| 可分发安装包 | `~/Downloads/ctflab-dist-20260915-final/ctflab-0.1.0-macos-arm64.tar.gz`（+ `.sha256` 旁车） | 已验证 |
| Smoke 内容包 | `~/Downloads/ctflab-dist-20260915-final/smoke-1.0.0.ctflab`（+ `.sha256`） | 已验证 |
| Basic Pentesting 2 内容包 | `~/Downloads/ctflab-dist-20260915-final/basic-pentesting-2-1.0.0.ctflab`（+ `.sha256`） | 已验证 |
| 干净 Mac 验收脚本 | `tools/ctflab_acceptance.py`（含 JSON 证据输出） | 已验证 |
| 单元测试 | `tools/tests/test_ctflab_package.py`（37 项）+ 文档守卫（3 项） | 已验证 |
| 包格式设计 | `docs/ctflab-task6-packaging-design.md` | 已验证 |

关键哈希：安装包外层 SHA-256 `450e59f6bfa5566f17af9b7237a82e50295b157a7fb972fa063ef353504ee69e`
（22 个登记文件）；Smoke 内容包 `234750ebdb32580228eb8f3fed760051189e3e142f9097fcf3c181889167154d`；
Basic 内容包 `1c628156309b7e8c9c26d5a9832025b7764fa8adfa8cf86da67553db69839af0`。

## 2. 实测证据

**打包与校验 CLI（已验证）**：`ctflab package build/verify`、`ctflab content pack/verify/unpack`
全部通过；`package verify` 复核外层哈希、包内 MANIFEST 逐文件哈希、启动器无开发解释器硬编码、
SBOM 组件数 8；`content verify` 复核两包 `disk_included=false` 与 `requires_ctflab=>=0.1.0`。

**干净环境验收（已验证：源码级安装包的可用性；见范围限制）**：
`python3 tools/ctflab_acceptance.py --bundle … --profile smoke --workdir ~/Downloads/ctflab-acceptance-20260915-final`
在“独立 HOME + 最小 PATH（`/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin`，无 conda、不继承
PYTHONPATH）”下 13/13 步通过：

1. `verify-bundle`：外层 SHA-256 与包内逐文件哈希通过；
2. `extract`：解包成功，启动器无开发解释器硬编码；
3. `install`：实际执行 `install.sh` 到独立安装目录，确认安装后启动器可执行；后续步骤均使用该启动器；
4. `doctor-missing-deps`：最小 PATH 下 PyYAML 缺失被检出且给出 `pip install pyyaml` 指引（退出码 1）；
5. `install-pyyaml`：在临时 HOME 的 venv 中安装 PyYAML（**联网步骤**）；
6. `doctor-ready`：必选依赖全部就绪（退出码 0）；
7. `prepare-source` + `import`：复用本机已导入基础镜像副本（`base-b3112d219743-netfix1.qcow2`，
   原始来源镜像已不在本机，属文档化的等价输入）完成导入；
8. `run --headless` → `health`（DHCP+SSH 就绪）→ `stop` → `reset`：全部退出码 0；
9. `residue-check`：无运行状态文件、无 overlay 残留。

证据：`~/Downloads/ctflab-acceptance-20260915-final/acceptance-evidence.json`（逐步命令、退出码、
输出、耗时与范围说明）。

**单元测试（已验证）**：`tools/tests/test_ctflab_package.py` 37 项覆盖确定性归档（同输入同
`generated_at` 逐字节一致）、篡改拦截（外层哈希与逐文件哈希两级）、白名单与拒收清单（磁盘/凭据/
日志/缓存不进包）、路径安全（绝对路径、`..`、符号链接条目拒绝）、版本门禁（`requires_ctflab`）、
解包不覆盖、SBOM 许可证标识与 `bundled=false` 真实性、`SHA256SUMS` 覆盖全部文件。

2026-09-15 复核补充：构建失败或旁车发布失败时不留 tar/校验半成品；输出目标采用同目录排他创建，
归档重复条目与畸形 JSON 会被拒绝，内容包解包先完成全量冲突预检并恢复清单声明的文件权限。复核后
`tools/tests/test_ctflab_package.py` 为 37 项；全仓库回归为 245 项，均通过。

## 3. 范围与限制（不得跨类宣称）

- **未交付**：`CTFLab.app`、受控 QEMU 运行时与动态库打包、`@loader_path` 修复、macOS 签名与公证、
  DMG/PKG 安装器——Task 6 中这些条目保持未完成，本记录不构成 Task 6 完整验收；
- **部分验证**：“干净 Mac 用户环境完成安装、导入和运行”仍属后续任务：本次验收在 PyYAML 一步
  需要联网 `pip install`，不是“零手工依赖的完整安装”；
- **项目许可证未声明**：`MANIFEST.json.license.status = undeclared`，`install.sh` 会原样提示；
  对外分发前必须由权利人补充 LICENSE；
- **内容包不含虚拟磁盘**：用户须自备来源镜像后 `ctflab import`；内容包当前只有 SHA-256 完整性，
  无来源签名认证；
- 本次未触碰 UTM 或用户现有虚拟机；干净环境验收只在独立状态目录中启动并清理派生的 Smoke
  无头实例。未提交虚拟磁盘、凭据、日志或截图；打包产物只存在于本机 `~/Downloads` 与临时目录，
  `*.ctflab`/`dist/`/`*.tar.gz` 已加入 `.gitignore`；
- 路径 A 的结论不受本次影响，仍为限定范围：Smoke/Basic 的静态控制台 E2E 已在限定范围内通过；
  动态分辨率重启后复测失败、显示链路不稳定、当前包仅保证固定显示可用；路径 B 未实现。
