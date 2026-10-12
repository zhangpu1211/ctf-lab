# 内容包缺陷修复验收（2026-10-12，第二轮）

> 历史验收快照；不替代当前软件状态。回应 [独立复核](verification-content-pack-independent-2026-10-12.md) 的五处实现缺陷与 GUI 实测三处问题；不替代 GUI 复测。

## 修复清单与位置

| 缺陷 | 根因 | 修复 |
|---|---|---|
| P1 多节点部分成功后回滚删除成功节点 YAML | `install_content_pack` 失败分支统一删除 `created_files` | 回滚带节点所有权：节点导入提交后其 YAML 移出回滚集合；失败信息注明“已完成并保留的节点”；失败节点不留半安装配置 |
| P1 失败重装删除旧包记录并提前改写节点元数据 | 说明冲突在导入/登记之后才检查；回滚无条件删记录 | 说明冲突预检提前到任何写入之前；已有 `pack.json` 永不删除；仅本轮导入的节点更新 `content_pack` 元数据，记录只在全部成功后重写 |
| P1 UEFI NVRAM 不自包含 | 导入登记的 `uefi_vars_path` 指向包内 | 导入时模板复制进 `state/images/<id>/uefi-vars-<hash>.fd` 并登记状态副本；移包后 `ensure_uefi_vars` 可用 |
| P1 readiness HTTP path 可改变目标主机 | path 直接拼接 URL，`@host/` 解析为外部主机 | 新增 `validate_http_check_path`（仅允许 `/` 开头站内相对路径，禁 `@`/空白）进入 `validate_profile` 与 `validate_pack_profile`；执行器用 `http_probe_url` 复核最终 URL 主机必须 127.0.0.1；新增 `_LoopbackRedirectBlocker` 不跟随离开回环的重定向 |
| P2 lab_ip 缺少网段校验 | 无检查 | `validate_pack_profile` 要求 `lab_ip` 位于 `192.168.242.0/24`（`LAB_NETWORK`） |
| GUI P1 校验失败仍自动导入包内磁盘 | `verifyDistribution` 的 `defer` 无条件链式导入；失败 JSON 被通用错误文案包装后无法解码 → 回退普通 onboard | 移除无条件 defer；新增 `DistImportGate`（失败/不可解码一律 abort）；`dist verify` 失败原始输出透传供结构化解码；`importMissingFromManifest`/`installContentPack` 双保险 `report.ok` 前置 |
| GUI 篡改错误横幅只有 JSON 尾部、无红色校验行 | 同上（失败 JSON 解码失败） | 失败 JSON 可解码后：校验表显示红色问题行，横幅给出具体问题（缺件/哈希不符） |
| GUI 包摘要未提前显示冲突 | `dist verify` 未带 `--conflicts` | GUI 校验命令加 `--conflicts`；包摘要卡显示内置/用户同名冲突预览 |

复核记录中“AX 文本称未选择”经其确认属辅助功能文本与画面不一致，无需代码修复。

## 测试与验证（本轮实际执行）

- `tools/tests/test_ctflab_content_pack.py` 扩至 32 项全部通过，新增：同包部分失败保留已提交节点（真实坏 OVA 触发导入期失败）、失败重装保留记录与元数据、NVRAM 副本入状态且移包后 `ensure_uefi_vars` 成功、**NVRAM 提交边界（重装复制失败时原登记保留、新副本回滚、记录不动）**、HTTP path 越界三层拒绝、重定向拦截、lab_ip 网段约束；并顺带修复损坏 OVA 抛裸 `tarfile.ReadError` 的问题（统一包装为 `CTFLabError`）。旧 NVRAM 用例期望同步更新为"登记状态副本"。
- `tools.tests.test_ctflab_gui` 25 项通过（新增 `DistImportGate` 决策、`--conflicts` 参数、失败原始输出保留、失败 JSON 结构化解码断言）。
- 独立复核 `reproduce.py` 重跑：在 P1 断言处如期中止（`assert missing` 不再成立），五处缺陷不再复现。
- 正向验证脚本 `verify-fixes.py`（证据根内，真实 qemu-img 转换、真实文件 IO、不启动来宾）：五场景全部按修复后行为通过，结果见 `fix-results.json`。
- 完整回归：`full-regression-fix2.log`——`python3 -m unittest discover -s tools/tests -v` 最终一次：**683 项全部通过、10 条件跳过**（223.184 秒，含 NVRAM 提交边界新增 2 项）。

## 本地打包（未发布）

`app-r2/CTFLab.app`：改用配套运行时 `ctflab-build/runtime-root`（含 aarch64/x86_64 QEMU，即此前 70 动态库来源）重新构建；`app verify` 与包内 CLI 结果见本轮记录附注。未替换镜像库 03-软件，未发布。

## GUI 点击复测与 ARM 实机复测（2026-10-12，用户确认空闲后执行）

复测 App：`app-r3/CTFLab.app`（配套运行时；在 app-r2 基础上补了冲突预览按哈希区分一致/不同的精度修正：`DistEntry.expectedSha256` 解码 + `DistImportGate.conflictNote` 纯函数，GUI 核心检查 207 项 0 失败）。独立状态 `gui-r2-state`，原生目录选择器+AX 坐标点击操作。

| 步骤 | 实际结果 | 证据 |
|---|---|---|
| 正常导入（app-r2） | 包摘要卡（资源/说明/声明边界）+ 三行绿色校验 + 自动安装成功；节点 smoke-mini 已停止 | gui-r2-02/03 截图 |
| 同名不同内容（app-r2） | "扫描并导入新增"：摘要卡提前显示橙色冲突提示；拒绝横幅给出双方 sha 前缀（946788240d27… vs 6c6906375445…，与终端写入一致） | gui-r2-04 截图 |
| 恢复重试（app-r2） | 还原候选后重扫：横幅消失、状态就绪；暴露包摘要卡对内容一致的候选仍误报"将拒绝覆盖"→ 以 `conflictNote` 按哈希区分修正（app-r3） | gui-r2-05 截图 + 修正记录 |
| **篡改包（原 GUI P1）** | 选择 gui-tampered-pack：横幅+红色行给出具体 SHA 问题（清单 7620acabaf1b…，实际 7efdfd8a4b3d…）；**日志无"开始自动导入"，状态目录无第二节点**；篡改基盘在"文件夹新增"分组保持未导入；摘要卡正确显示"同名候选内容一致，重复导入将跳过" | gui-r3-06 截图、gui-r2-state profiles/images 核验 |
| 篡改后恢复 | 重选好包：横幅消失；重复导入"内容一致跳过" | gui-r3-08 截图 |

ARM 包实机复测（NVRAM 移包路径）：以镜像库 Kali 基盘与 NVRAM 只读副本制作 kali-mini-pack（基盘 `974a319f5961…`、NVRAM `8639a3fb43ddec7c` 与库一致），独立状态 `arm/state` 真实转换导入，`uefi_vars_path` 登记 `state/images/kali-mini/uefi-vars-8639a3fb43dd.fd`（状态目录内）；**移走整包后** headless 真实启动：`service_ready`、DHCP `192.168.242.88`、SSH banner `SSH-2.0-OpenSSH_10.3p1 Debian-4`、非全黑画面截图；probe 结束自动停止，无 QEMU 残留。证据 `arm/`（probe-run.log、state/logs/probes/kali-mini-20261012T071701Z.{json,png}、retained-pack）。

现场核验：GUI App 经 Cmd+Q 正常退出、无 CTFLabGUI/QEMU 进程；gui-r2-state 与 arm/state 各保留 1 个已导入未运行节点；用户独立复核现场未动。镜像库 smoke/kali/Acfun 基盘与 kali NVRAM 哈希复核不变。

现场核验：GUI App 已退出、无 CTFLabGUI/QEMU 进程；gui-r2-state 与 arm/state 保留（各含 1 个已导入节点、未运行）；用户独立复核现场的 smoke-mini-base 登记仍未动，由用户决定去留。

## app-r4 交付打包与包内复验（2026-10-12，用户指示）

**任务边界**：只完成新版 App 本地打包与独立验收；不扩展功能。背景：第 14 节确认 app-r3 包内仍是旧 manifest 导入路径，不含 NVRAM 提交边界修复。

**SPICE 客户端核对（ 不静默省略）**：已验收 App（`ctflab-continuation-20261012/app-final`）随包携带的是**自研受控客户端**（源码 `tools/spice_client/ctflab_spicy.c`，与 HEAD 42a3aa7 一致、无未提交改动），其预编译二进制（bin 内 `4f158923c5da806a…`、CTFLabDisplay.app 内 `a6c6154526c5008b…`）可从 `ctflab-input-recovery-20261010/app/CTFLab.app` 逐字节溯源。app-r4 沿用该二进制，未退回 Homebrew 现货 spicy。

**配套运行时决策**：历史 70-dylib QEMU 构建根已清理（`ctflab-build/qemu-11.1.0` 仅剩源码树）。为避免 spice-gtk 闭包（依赖 OLD App 内部 dylib，与现行 Homebrew 库同名不同字节）触发"同名冲突"的正确失败，以已验收 App 的完整 runtime（bin 4 + lib 70 + share 51）构造配套暂存根（`/tmp/app-r4-dylib-root/opt/homebrew/opt/{qemu,spice-gtk}`，spice-gtk/lib 为指向 qemu/lib 的 symlink 以保证 `resolve()` 一致性）；app verify 与哈希见下。

**运行时溯源更正（2026-10-12 独立核对后）**：~~app-r4 运行时与已验收 App 逐字节同源~~——更正为：bin 4 文件、share 50 文件与 65/70 dylib 相同；**5 个 dylib 不同**（libpcre2-8.0、libglib/gobject/gmodule/gio），排除代码签名区后仍不同（独立核对 `dylib-signature-comparison.json`）。完整溯源见 `dylib-provenance-trace.json`：这 5 库为 **glib 2.88.3 家族（dylib current version 8801.3.0）**，字节与 input-recovery/app、import-acceptance/app-r2 逐字节一致，其 SBOM 记录的 keg 原件（glib 2.88.3 = `629b656720b2`）仍在当前 Cellar 且哈希吻合；app-final 系 Homebrew glib 升级 2.90.1（9001.1.0）后的 r3 轮重建。差异是相邻大版本而非构建漂移；r4 签名重签有效（codesign strict 通过）。该 2.88.3 家族即 2026-10-10 input-recovery 轮已验收 SPICE 显示证据对应的库组合，但 app-r4 内整套闭包的运行验收仍以本轮真实 SPICE 显示复测为准。

| 项 | 结果 |
|---|---|
| 构建 | `app-r4/CTFLab.app`：743 登记文件、70 动态库、内置 Python 3.12.15 + PyYAML 6.0.3、ad-hoc、未公证；未覆盖 app-r3 |
| `app verify` | 通过（结构/清单/许可证/签名分级；`app-r4-verify.log`） |
| 旁车校验 | `CTFLab.app.sha256`：树摘要 `bdba17328b527e…` 与 MANIFEST `95897de7269a…` 用构建器 `app_tree_hash` 算法复核一致 |
| 包内源码逐字节 | `cmp` 证实包内 `ctflab/tools/ctflab.py`、`ctflab_dist.py` 与工作区源码 **IDENTICAL**；含 NVRAM 前置校验/复制（`复制 UEFI NVRAM 模板到状态目录失败`）与 `expect_sha256` 导入（`content-pack-manifest`）标记 |
| SPICE 字节 | 包内 spicy 两处哈希与已验收 App 完全一致（`4f158923…`/`a6c61545…`） |
| 运行时溯源 | bin/share 与 65/70 dylib 与已验收 App 相同；5 个 glib 家族库为 2.88.3 世代（溯源 `dylib-provenance-trace.json`），真实 SPICE 显示验收见下节 |
| 包内 NVRAM 边界复验 | `verify-app-r4-nvram.py`（包内 Python `-B`，全新状态）：模板损坏（`拒绝覆盖`）与复制失败（images 目录只读注入 OSError）两场景均"安装拒绝 + image.json/pack.json 逐字节不变 + 登记仍指状态原副本 + 无模板残留"；结果 `r4-nvram-recheck-results.json`；无 `__pycache__`/pyc 产生 |

**边界**：本轮为打包与结构/导入层真实验证；未启动虚拟机、未操作桌面。此前 GUI 点击与 ARM 实机启动结果属于对应轮证据，结构校验不能替代运行验收；NVRAM 修复的实机启动复验可复用 `arm/` 配方，本轮未重复。源码与文档未提交，分支/HEAD 不变，无推送或发布；镜像库与 03-软件未动。

## app-r4 真实 SPICE 显示验收（2026-10-12，用户确认桌面空闲）

| 步骤 | 实际结果 | 证据 |
|---|---|---|
| 启动（SPICE） | `run kali-arm64 --display spice`：QEMU PID 97338 就绪，SPICE UNIX 端点 `/tmp/ctflab-sockets-501/90ef4729…/display.sock`；包内 `CTFLabDisplay.app/Contents/MacOS/spicy`（PID 97339）真实拉起 | 本节记录、status 输出 |
| 显示验证 | "CTFLab Kali"窗口完整渲染 **Kali 登录界面**（lightdm 登录框、KALI 壁纸、时钟 20:31 与宿主一致）；非全黑、非 UEFI Shell | `spice-r4-clean.png`（按 CGWindowID 仅截该窗口） |
| 健康检查 | `health ok: true`：process/DHCP 192.168.242.10/SSH `SSH-2.0-OpenSSH_10.3p1 Debian-4` | state/logs |
| 停止 | 正常 `stop`；QEMU（97338）与 spicy（97339）退出，无残留进程 | 本节记录 |

**结论**：glib 2.88.3 家族 5 库在 app-r4 整套运行时中实际加载并完成显示链路端到端渲染——5 库差异未表现任何运行故障；结合溯源（与 2026-10-10 input-recovery 轮已验收 SPICE 显示证据同一库组合），运行兼容性疑虑关闭。SPICE 门禁（仅 kali-arm64 单独启动）保持不变。

**边界**：未登录 Kali 桌面进行交互（登录画面验证为限，延续各轮边界）；未长时闲置；未跨 Mac。
