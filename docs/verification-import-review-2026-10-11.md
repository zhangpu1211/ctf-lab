# 单镜像导入独立复核与本地候选 App 验收（2026-10-11）

> 历史验收快照：仅对应本记录日期、指定源码和候选，不替代当前软件状态。未发布、未提交、未推送；不把本机短程验收扩展为任意镜像或跨 Mac 可用。

## 结论与候选

正式目录 `/Users/pufei/Downloads/ctf-lab`；分支 `codex/release-0.1.1-preview-20261010`，HEAD `42a3aa71d2665e20d9aec27f4afa19eed43a784d`。既有未提交修改均保留。
已发布版仍为镜像库 `03-软件` 的 0.1.1-preview。本轮独立构建保持源码版本 0.1.1，以日期和树摘要区分本地候选，不覆盖发布 ZIP。

- 最终 App：`/Users/pufei/Downloads/ctflab-import-acceptance-20261011/app-r3/CTFLab.app`。
- App 树 SHA-256：`041401e605fea64e19829a950e8b79bd25fda6eb9eac3bcebf946fff3cdbcb45`。
- 本地 ZIP：同证据目录 `CTFLab-0.1.1-import-review-20261011-r3-local.zip`；SHA-256 `ad63b2ef0b5ca542da9d08ae05e83f007941b5ae8be8c9c7a0e5790eb59adec6`。
- 证据根：`/Users/pufei/Downloads/ctflab-import-acceptance-20261011`。含驱动、失败日志、JSON、基盘检查和 QMP 来宾截图；原生 GUI 截图另见本次聊天工具记录。

## 独立复核及修正

复核真实调用链：GUI `run` 建立私有取消通道 → CLI `import_session` → `onboard`/`import_image` → 转换子进程轮询 → 完整性检查 → 发布登记；矩阵 → 独立 overlay/NVRAM → 探测 → 停止和清理 → 保存前报告/profile/基盘复核。

桌面发现模态导入向导遮住主窗口，阶段文字与取消按钮仅在主窗口，向导只有转圈。修正 `gui/GuiApp.swift`，在向导内显示阶段进度、安全取消，并在忙时禁止重新选择来源。重新构建 R2 后实际点击验收。收尾又发现重试成功后主窗口保留第一次取消的旧错误；清除重新导入、探测和保存开始时的旧错误，追加 R3 本地构建及复核。
完整回归另发现旧教程标题和按钮名断言失效；更新文档测试为当前教程语义，未回滚用户文档整理。

## 真实导入和失败恢复

1. Smoke 分发基盘独立 QCOW2 副本：转换阶段协作取消（退出 2），无登记基盘/partial；保留候选后 `--resume` 成功，配置摘要不变；重复导入保留基盘 inode/mtime；错误期望哈希拒绝且登记不变；`qemu-img check` 通过。原盘与副本摘要核对。证据 `real-import-review.py`、`real-import-evidence.json` 和对应日志。
2. 用户本轮新增 `01-待处理/Acfun.ova`：新版 App 内 CLI 完成同样取消、重试、重复导入、错误哈希拒绝和完整性检查。原 OVA 不改写。冷 onboard 在另一个短状态目录执行，真实矩阵 BIOS/IDE 命中登录画面和 DHCP，人工查看 PNG 确认为 Acfun 登录提示。证据 `acfun-real/`、`acfun-cold-onboard.log`、`acfun-real-matrix.log`，状态 `/private/tmp/ctflab-ova-20261011`。
3. GUI R2：Smoke 独立 RAW 副本扩至虚拟 40 GiB，仅作为可操作取消窗口的测试输入，不宣称原镜像性能。界面显示“来源校验 15% · 4 秒”；实际点取消，出现“重试候选导入”；复核无登记/partial。实际点重试完成登记，候选 YAML 摘要不变。证据 `gui-cancel-evidence.json`、`gui-retry-evidence.json` 和 `gui-r2-state`。

4. GUI R3 再次实际取消并重试成功，候选 YAML 摘要保持，基盘登记完成，无 partial；关闭向导后主窗口没有旧取消错误。证据 `gui-r3-cancel-evidence.json`、`gui-r3-retry-evidence.json`，状态 `/private/tmp/ctflab-gui-r3-20261011`。

R3 从 Downloads 读取 RAW 时曾停在 `os_scandir → __open_nocancel`，未确认是否为系统目录访问问题，不能归因已定。仅对核验绑定的本轮 inspect 子进程发送 SIGTERM 后，GUI 显示只读识别失败、未导入；换同输入的只读 clone `/private/tmp/ctflab-r3-input.raw` 完成上述桌面复测。现场栈在 `r3-inspect-sample.txt`，随后用户确认存在“CTFLab 访问下载文件夹”系统提示，并已允许。授权后重新启动同一 R3 App，在同一独立状态目录选择原 Downloads RAW 路径并点击“只读识别”，界面显示候选硬件及“识别完成；未启动、未导入”，未复现停滞。此项更新为“授权后原路径复测通过”；此前现场仍保留。证据 `gui-r3-downloads-permission-recheck.json` 和本次原生 GUI 截图。未开启完整磁盘访问；本次未新增导入或启动虚拟机。

耗时属于本机缓存状态和小样本：Smoke QCOW2 重试约 1.027 秒、重复约 0.554 秒；Acfun OVA 重试约 1.912 秒、重复约 0.684 秒。不是清空系统缓存后的冷盘基准，不提供通用提速比例或峰值空间保证。

## GUI 矩阵与人工确认

默认打包 App 没有 Tesseract，未知候选默认只有 DHCP：GUI 首次 Smoke 矩阵虽有登录截图，分类 unknown，未生成可固化成功结果；没有将 DHCP/非黑画面当成功。为收尾本轮测试，对绑定的本轮矩阵 CLI 发送 SIGINT，finally 结束其 QEMU 并清理派生盘；未操作其他实例。

R2 的独立 Smoke 候选在矩阵前明确加入已知 SSH 22 检查和回环转发 12331，备份为 `gui-before-service-check.yaml`。此配置是测试样本准备，产品不会自动猜测开放服务。GUI 点击矩阵取得实际 SSH 协议就绪 `service_ready`；人工查看截图为正常引导至 sshd，非 UEFI/PXE/内核错误。先取消二次确认，摘要不变且无备份；再次确认保存，备份摘要等于矩阵开始时 profile 摘要，`candidate`、`boot_verified=false`、`service_verified=false` 保持。证据 `gui-r2-state/logs/probes/`、`profile-backups/`、`final-integrity-evidence.json`。

另用 R2 App CLI 保存已人工检查的源码 Smoke 矩阵报告，成功并保留原配置备份，见 `apply-real-candidate.log`。默认无 OCR/无服务检查的未知镜像不会出现保存入口，这是仍需后续完善的可用性边界。

## 新 App 与三节点分发配套

最终 App `app verify`：804 个登记文件、Python 3.12.15、PyYAML 6.0.3、QEMU 11.1.0、许可证完整；`codesign --verify --deep --strict` 通过，ad-hoc，未公证。最小 PATH、独立 HOME 下 doctor 和分发清单校验通过。三节点均以现有分发基盘导入，不修改分发基盘或 Kali vars。

| 节点 | 本轮实际结果 | 边界 |
| --- | --- | --- |
| Kali ARM64 | 配套 NVRAM 导入，HVF 冷启动，DHCP 和 SSH 协议就绪 | 无来宾登录、桌面/重启复测 |
| Smoke | TCG 冷启动，DHCP，SSH-2.0 协议就绪 | 无来宾认证登录 |
| Basic Pentesting 2 | TCG 冷启动，登录画面、DHCP、HTTP 200 | 无登录或完整重启复测 |

最终 R3 另用短独立目录、最小 PATH 和独立 HOME 串行重新导入及冷启动三节点，doctor、分发校验、三次 import/probe/stop 全部退出 0。Smoke 与 Kali 返回 SSH 协议，Basic 返回 HTTP 200；人工查看三张截图为正常用户空间引导/服务启动，R3 本轮未等待每台登录提示或认证登录。证据 `r3-pairing-review.py`、`r3-pairing-evidence.json`、`r3-packaged-*.log`，对应 JSON/PNG 已复制到证据根 `tmp-probe-records/ctflab-r3-pair-20261011`。

首次并行矩阵/配套测试共用回环交换机 23400，Smoke/Basic 因端口冲突失败；保留原日志，改串行。串行 Basic 又因测试目录使 QMP socket 路径过长而失败；改用 `/private/tmp/ctflab-pair-20261011` 独立导入后通过。两项是实际失败，不能从最终记录删除；本轮未实现跨状态目录自动端口协调或长路径映射。

R2 的初次失败与恢复证据 `pairing-evidence.json`、`pairing-retry-evidence.json`、`basic-short-import.log`、`basic-short-probe.log`；来宾 PNG 和 JSON 在各独立状态的 `logs/probes`。

## 检查与收尾

- 首次完整回归 643 项，1 项旧文档断言错误、10 跳过，日志 `regression-initial.log`。
- 修正后 `python3 -m unittest discover -s tools/tests -v`：643 项，633 通过、10 跳过，`regression-final.log`；包括 Swift 核心和 GUI 编译验证。
- `CTFLAB_BOOT_MATRIX_E2E=1 python3 -W error::ResourceWarning -m unittest discover -s tools/tests -p test_ctflab_boot_matrix.py -v`：34 项通过，真实合成空盘失败画面、基盘保护与子进程回收另补验，不作为外来镜像成功证据。
- R2 完整回归后，R3 的清除旧错误改动另跑 GUI 专项 25 项通过（`gui-r3-tests.log`）；未把完整回归数字称为 R3 全量重跑。Python 语法检查、`git diff --check` 通过。
- 最终原盘、基盘、备份与测试进程复核见 `final-integrity-evidence.json`；R3 RAW 来源/副本摘要、QCOW2 检查、App 使用后树摘要见 `r3-final-integrity.json`；R3 ZIP 解压检查见 `r3-zip-integrity.log`，摘要见 `r3-zip-sha256.txt`；所有运行操作只绑定本轮独立状态。

收尾现场重新核验：本轮 QEMU、网络交换机、inspect 子进程均已退出；本轮 R3 GUI 已退出。未停止用户实例。临时目录的探测 JSON/PNG 已复制到证据根 `tmp-probe-records`，派生盘和状态仍保留在原目录。保留本轮派生测试数据，不自动删除。未提交、推送、发布、替换镜像库软件；未连接物理 LAN，未实现多主机或 Docker。其他新增 OVA 未逐个处理或验收，Acfun 仍是候选，不称“已适配可用”。本轮不覆盖登录、完整重启、目标攻击路径、跨 Mac、外接屏、睡眠或长期负载。
