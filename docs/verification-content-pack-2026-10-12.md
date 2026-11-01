# 目录式内容包验收（2026-10-12）

> 历史验收快照；不替代当前软件状态。区分本轮实际执行、通过、失败与未执行项。

## 结果与边界

本轮实现并交付目录式内容包（`DISTRIBUTION.json` schema 2）：`dist make-pack` 制作、`dist verify` 扩展包摘要与冲突预览、`dist install` 事务导入（先整体校验→排他装配置→逐节点导入→复制说明→写包记录；失败回滚本轮写入、原包不动）、GUI 内容包展示与单次安装动作。真实自定义内容包（smoke-mini-pack，独立 ID）在独立状态完成校验、导入、真实启动、协议验证、正常停止、移包后再启动与篡改失败恢复。

**GUI 鼠标流程未在本轮执行**：桌面截图显示用户正在前台使用 Chrome（非空闲），按"桌面操作前确认本轮空闲时间"边界中止键鼠驱动，仅保留"新 App 进程启动成功 + 包内 CLI 识别内容包 + GUI 逻辑单元测试 25 项"作为 GUI 侧本轮证据。真实点击流程见文末待办配方。

正式目录 `/Users/pufei/Downloads/ctf-lab`；分支 `codex/release-0.1.1-preview-20261010`；HEAD `42a3aa71d2665e20d9aec27f4afa19eed43a784d` 不变，本轮全部改动未提交。未操作用户既有 VM、未接入物理 LAN、未删除资产、未推送或发布；镜像库与 03-软件未改动。原始 smoke 基盘只读（副本进包，hash 与库内一致 `7620acabaf1b…`）。

证据根 `/Users/pufei/Downloads/ctflab-contentpack-20261012`。

## 实现（工作区，未提交）

- `tools/ctflab_dist.py`：schema 2 解析（`parse_pack`：角色白名单 base/nvram/profile/doc、自包含、平铺文件名、大小/哈希格式、claims 归属）、`resolve_pack_file`（拒穿越/绝对路径/反斜杠/符号链接/越界 resolve）、`make_pack`（制作端同一解析器自检）、`verify_distribution` 扩展（schema 1 行为不变；schema 2 附 `pack` 摘要：节点资源、本机冲突预览、声明边界文案）、版本约束 `>=X.Y.Z` 校验。
- `tools/ctflab.py`：`validate_pack_profile`（在 validate_profile 之上收紧：白名单键、拒绝 `internet: true` 与非 lab 网段、端口映射只允许 name/guest_port/host_port、readiness 形状）、`LabManager.install_content_pack`（flock 可重入锁内：整体校验→冲突预检（内置同名拒绝；用户同名不同内容拒绝并给双方 sha256 前缀；相同内容幂等跳过）→排他硬链接装 profile→`_import_image_unlocked` 逐节点导入（来源哈希核对 method=manifest，NVRAM 按清单配对）→说明复制到状态目录→最后写 `content-packs/<pack-id>/pack.json`；异常/取消回滚本轮创建的 profile 与说明副本及记录，已完成节点如实保留并带节点名报错）、`cmd_dist_install`、`cmd_dist_make_pack`、`dist verify --conflicts`、`status --json` 增 `content_pack`/`has_pack_claims` 字段、main 分发与取消通道接线。
- `gui/GuiCore.swift`：`PackSummary`/`PackNode`/`PackLocalStatus`/`PackInstallReport` 解码、`DistReport.pack` 可选字段、`CliAction.distInstall`（`dist install --dir … --json`，复用导入取消通道）。
- `gui/GuiApp.swift`：内容包目录走单次 `dist install`（旧 schema 1 目录保持逐节点 import 循环）；校验区新增包摘要卡（名称/版本/最低运行器、节点资源需求、内置/用户同名冲突提示、说明文件、声明边界）。

## 单元与合成测试（本轮实际运行）

- `tools/tests/test_ctflab_content_pack.py` 新增 25 项全部通过：make-pack 产物可验证、schema 1 无 pack 段（兼容）、结构非法（缺 pack/坏 id/坏版本/坏约束/未知角色/穿越文件名/绝对路径/重复条目/不自包含/claims 越界/size 非法）、版本不满足、符号链接载荷拒绝、缺件/哈希/大小不符、冲突预览、正常导入登记（claims 仅声明、无 verification_status、status 带 content_pack）、NVRAM 配对、重复导入幂等、内置冲突、用户同名不同内容拒绝且不覆盖、相同内容跳过、六类非法配置逐项拒绝且零写入、导入失败回滚（配置/说明/记录移除、原包校验仍过、修复后重试成功）、取消回滚、多节点包部分成功保留、双线程并发锁串行化。
- 既有受影响套件同轮通过：distribution + user_profiles + import_integrity + ova_import 合计 87 项 OK。
- GUI：`tools.tests.test_ctflab_gui` 25 项通过（含新增包摘要解码、distInstall 参数、安装结果从带进度行输出解析、失败输出不误解析、源码守卫）。

## 真实验收（独立状态与可恢复派生磁盘）

证据根 `/Users/pufei/Downloads/ctflab-contentpack-20261012`；状态目录 `state/`（`CTFLAB_PROFILE_DIR=state/profiles`）。

| 验收 | 实际结果 | 证据 |
|---|---|---|
| 制作真实包 | `dist make-pack` 从镜像库 smoke 基盘副本生成 smoke-mini-pack（3 文件+清单+SHA256SUMS+README）；`shasum -a 256 -c` OK；基盘 hash 与库内一致 `7620acabaf1b…` | `retained-packs/smoke-mini-pack/`、`sources/` |
| 校验与冲突预览 | `dist verify --conflicts` 通过；显示节点 4096MiB/2vCPU、说明文件、声明边界 | 本记录与 CLI 输出 |
| 导入（真转换） | `dist install` 独立状态成功；profile 排他装入 `state/profiles/smoke-mini.yaml`；基盘 `state/images/smoke-mini/base-7620acabaf1b.qcow2`；说明与 pack.json 落位；`source_verification.method=manifest`；`claims_from_pack` 仅声明；无 `verification_status` | `state/content-packs/smoke-mini-pack/pack.json` |
| 真实启动 | `probe smoke-mini`：`service_ready`，DHCP `192.168.242.66`（包内声明地址），SSH `SSH-2.0-OpenSSH_10.0`，非全黑画面截图；探测后自动停止 | `state/logs/probes/smoke-mini-20261012T021758Z.{json,png}` |
| 移包后启动 | 包移至 `retained-packs/` 后 `run smoke-mini --headless` 再启动成功；health 三项 OK（process/DHCP/SSH）；`stop` 正常退出（旧 PID 91561 确认退出） | health JSON（本轮终端记录）、`state/logs/` |
| 篡改失败恢复 | 副本缺件→verify/install 均拒绝"未做任何导入"；副本改字节→哈希不一致拒绝；原包 verify 仍通过、hash 前缀 `7620acabaf1b` 不变、状态目录 profile/基盘/记录完整 | 本轮终端输出 |
| 独立 CLI 冒烟（/tmp） | mini-pack 两轮安装（首装+幂等）、回滚路径复核 | /tmp 临时目录已清理 |

**未在本轮执行**：GUI 鼠标点击全流程（用户非空闲）；Acfun/Kali/Basic 内容包化（本轮只做 smoke-mini 样本）；跨 Mac、多节点包的真实启动（多节点事务有合成测试，未实机验证第二个节点）；内容包签名。

## 实际失败与修复

1. 首次全量回归 676 项中 1 项失败：`test_fenced_commands_parse_with_positional_arguments` 拦下我在分发指南命令块里写的 `[--nvram …]` 方括号占位与 `<节点 id>`（文档命令守卫要求 fenced 命令可被真实 argparse 解析）。已改为显式 `--nvram/--doc` 与示例节点 `smoke-mini`（列入守卫测试的占位 profile 清单并注明来源），修复后文档守卫 94 项通过；最终全量回归以修复后状态重跑留档。
2. App 构建首次失败：`ctflab-build/qemu-11.1.0` 缺 `qemu-system-aarch64`；改用 Homebrew QEMU 根构建成功。因此本轮候选 App 的动态库数（28）与上轮定制 runtime-root（70）不同，如实记录。
3. 首次启动测试 App 用错二进制名（CTFLab → 实际 CTFLabGUI），nohup 记录了失败；改名后正常。

## 来源资产核验

镜像库基盘本轮只读未动：smoke `7620acabaf1b…`（mtime 2026-09-16 不变）、kali `974a319f5961…`、acfun `df612f71f372…`，与 2026-10-11/12 状态记录一致。

## 本地打包（未发布）

`app/CTFLab.app`：版本 0.1.1、730 登记文件、QEMU 11.1.0（本轮用 Homebrew QEMU 根，动态库 28 个，与上轮定制 runtime-root 的 70 个不同）、内置 Python 3.12.15 + PyYAML 6.0.3、ad-hoc、未公证；`app verify` 通过（结构/清单/许可证/签名）；包内 `ctflab-cli dist verify --json` 正确识别 smoke-mini-pack。该 App 是**本地测试候选**，不替换镜像库 03-软件 的 0.1.1-preview，不含 SPICE 客户端差异核对（Kali SPICE 路径未随本轮验收）。

## 收口与继续入口

本轮进程现场：probe/run 的 QEMU 与交换机已随 `stop` 退出（旧 PID 91561 已核验退出）；测试 App CTFLabGUI（PID 93846）已正常退出；无本轮残留进程。保留：证据根全部内容、`retained-packs/`、独立状态 `state/`（含 overlay/NVRAM/probe 报告）。`/tmp/ctflab-pack-smoke` 冒烟目录与 `/tmp/pack-tamper` 已删除。

完整回归：`full-regression-contentpack.log`——修复文档命令块后最终一次 `python3 -m unittest discover -s tools/tests -v`：**676 项，全部通过，10 条件跳过**，213.355 秒（首次运行 675 通过 + 1 文档守卫失败，见"实际失败与修复"）。

**GUI 点击流程配方**（需用户确认空闲后执行）：

1. `CTFLAB_GUI_STATE_DIR=<证据根>/gui-state <证据根>/app/CTFLab.app/Contents/MacOS/CTFLabGUI`；
2. "选择镜像文件夹"选 `retained-packs/smoke-mini-pack` → 自动校验出现包摘要卡与三行校验 → 自动安装 → 日志"内容包安装完成"；
3. 冲突路径：先向 `gui-state/profiles/smoke-mini.yaml` 写入不同内容，再选包 → 摘要卡黄色提示"已有同名候选"→ 安装失败提示含双方 sha256 前缀；移除该文件后重试成功且无旧错误残留；
4. 失败路径：选 `gui-tampered-pack`（已备好，基盘被改）→ 校验失败横幅与红色行；重选好包可恢复。

新聊天交接语：继续CTFLab，正式目录 `/Users/pufei/Downloads/ctf-lab`。先完整读 AGENTS.md、docs/ctflab-current-status.md 与 docs/verification-content-pack-2026-10-12.md，核对 Git、产物与实际进程。保留未提交改动、原 OVA、四镜像基盘、内容包证据根 `ctflab-contentpack-20261012`。本轮内容包机制已实现并经 CLI 真实验收；GUI 点击流程待用户空闲后按验收记录配方执行；不要自动停止用户 VM、删除资产、提交/推送/发布。
