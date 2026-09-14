# Kali 图形体验验证：剪贴板、分辨率、关闭策略与 Ghidra 帮助（2026-09-13）

本轮只针对 Kali 图形体验：双向文本剪贴板、动态分辨率可行性、窗口关闭/停止策略、Ghidra 帮助异常。
不涉及跨平台、攻击功能或靶场网络范围；所有来宾改动只写入运行 overlay，基础镜像未修改。

环境与输入：

- macOS Apple Silicon、Homebrew QEMU 11.1.0、宿主 16GiB 内存；
- Kali ARM64 基盘为 2026-09-13 固化版本（`base_sha256=ca1034606a82a7fa8372d23ab42ce8286638a0fadb247a141cc4f72d00c5a915`），未重新导入或修改；
- 来宾内验证通过 SSH（回环端口映射）、QMP、截图 OCR 与 xdotool 完成；测试只使用无敏感信息的测试文本。

## 1. 双向文本剪贴板（通过）

`./tools/ctflab run kali-arm64 --clipboard` 启动，来宾图形会话登录后 `spice-vdagent` 自动激活，
`/dev/virtio-ports/com.redhat.spice.0` 存在，`spice-vdagentd` 为 active。

| 用例 | 结果 |
|---|---|
| 英文 Mac→Kali / Kali→Mac | 通过，38 字节，SHA-256 一致 |
| 中文 Mac→Kali / Kali→Mac | 通过，44 字节，SHA-256 一致 |
| 多行文本 Mac→Kali / Kali→Mac | 通过，44 字节，SHA-256 一致 |

- 关闭通道后不共享：停止实例、以不带 `--clipboard` 重新启动后，来宾没有 `virtio-ports` 目录，
  `spice-vdagentd` inactive；Mac 剪贴板文本不会出现在来宾，来宾剪贴板文本也不会改写 Mac 剪贴板（负面测试通过）。
- 靶机不获得该通道：`run smoke --clipboard` 直接被拒绝（只有 Kali 图形模式可用），运行器也不会为靶机创建 vdagent 通道。
- 重启后仍正常：完整 `stop` → `run --clipboard` → 重新登录后，上述 6 项测试再次全部通过。
- 依赖：来宾必须登录图形会话（`spice-vdagent` 是会话级进程）；`--clipboard` 与 `--headless` 互斥，切换模式需要先停止。
- 剪贴板噪声仅限本次测试文本；Mac 原有剪贴板在测试前做了全格式快照、结束后按类型逐一还原（8 种格式负载一致）。

## 2. 动态分辨率（当前后端不支持，未冒充完成）

结论：QEMU 11.1.0 + cocoa + virtio-gpu 只能把来宾画面缩放到窗口（`zoom-to-fit`），
**无法让来宾分辨率跟随窗口**。三条独立证据：

1. QMP `display-update` 在本机 QEMU 中只接受 `type="vnc"`；EDID 变体已被移除
   （QMP schema 转储确认，实际调用返回 `Parameter 'type' does not accept value 'edid'`）。
2. `qemu-vdagent` chardev 只实现剪贴板/鼠标能力，没有 `VD_AGENT_MONITORS_CONFIG`
   （核对 QEMU v11.1.0 `ui/vdagent.c`），因此 vdagent 通道也不能驱动分辨率。
3. Homebrew QEMU 的显示后端只有 `none/curses/cocoa/dbus`，没有 spice；SPICE 客户端的动态分辨率不可用。

实测（来宾侧三种分辨率，宿主窗口尺寸不变）：

| 来宾 `xrandr` 当前模式 | 宿主 QEMU 窗口（点） |
|---|---|
| 640x360 | 320x212 |
| 1280x1024 | 320x212 |
| 1920x1080 | 320x212 |

即画面被整体缩放，来宾帧缓冲与宿主窗口尺寸解耦；窗口缩放期间没有反复震荡（模式与窗口都稳定）。
当前镜像默认分辨率是 640x360，体感偏小；来宾内可用 XFCE 显示设置或 `xrandr` 改到 1920x1080 等模式。

未完成与环境限制：本次自动化环境没有屏幕录制/辅助功能权限，宿主窗口拖动（CUA 坐标与合成拖拽）都被拒绝，
因此“三种宿主窗口尺寸 + 全屏进入/退出”的宿主侧操作没有做全；结论以上面的后端证据与解耦实测为准，
不把“缩放”当作动态分辨率。

后续可选方案（都需要单独确认，本轮未实施）：

- 来宾内调整分辨率（现在即可用，不改变 QEMU 参数）；
- 增加 `run --resolution WxH`，把 virtio-gpu 的 `xres/yres` 固定为期望尺寸（静态初始分辨率，非动态）；
- 使用带 SPICE 的 QEMU 构建 + SPICE 客户端，才能获得真正的动态分辨率；需要重编译 QEMU 并安装额外宿主软件。

## 3. 窗口关闭与停止策略（已明确并验证）

cocoa 关闭按钮不是无提示断电（核对 QEMU v11.1.0 `ui/cocoa.m`）：

1. 关闭窗口先弹出 “Are you sure you want to quit QEMU?”；选择 Cancel 时窗口不会关闭；
2. 选择 Quit 时 `applicationWillTerminate` 调用 `qemu_system_shutdown_request(SHUTDOWN_CAUSE_HOST_UI)`，
   等价于按 ACPI 电源键，QEMU 等来宾退出后再结束，不是直接断电。

实测行为：

- 来宾有活动图形会话时，ACPI 电源键会打开 XFCE 关机确认框（“Log out Kali User … Shut Down”）。
  用户未确认时来宾不会关机，`stop --graceful` 在 30 秒超时后保留实例（进程、磁盘、网络都在，退出码 2），
  错误信息会提示在 QEMU 窗口中确认或先在来宾内关机；
- 用户在来宾里确认 Shut Down 后，来宾正常关机、QEMU 自行退出；`status` 显示“进程已退出（原 PID …），
  状态文件待清理”，`stop --all` 清理状态文件与交换机，`pgrep` 无 qemu/交换机残留，overlay `qemu-img check` 无错误。

停止语义与 CLI 一致性：

- `stop --graceful`：只发 ACPI 电源请求，30 秒内来宾未退出就报错并保留实例；
- `stop`（默认）：短暂等待后经 QMP `quit`、SIGTERM、SIGKILL 结束 QEMU；
- `status` 现在会报告“进程已退出但状态文件残留”的实例，以及没有实例的残留实验网交换机；
  `stop --all` 会一并清理（包括只剩网络状态文件的残留端口）。

未提供隐藏到后台：确认退出后窗口不会重新显示；需要后台运行请从一开始使用 `--headless`。
macOS 自带的 Hide（Cmd+H）未在本轮验证。未真实点击宿主关闭按钮（自动化环境缺权限），
关闭按钮路径的依据是 QEMU 源码：`ui/cocoa.m` 中 `windowShouldClose:` 调用 `[NSApp terminate:]`
（用户取消时返回 NO，窗口不关闭），`applicationShouldTerminate:` 调用 `verifyQuit` 显示
“Are you sure you want to quit QEMU?”，确认后 `applicationWillTerminate:` 执行
`qemu_system_shutdown_request(SHUTDOWN_CAUSE_HOST_UI)` 并等主循环结束进程
（本机核对 v11.1.0，并与上游 `https://raw.githubusercontent.com/qemu/qemu/master/ui/cocoa.m` 一致）。

## 4. Ghidra 帮助异常（已修复并验证）

根因：Kali 的 `ghidra 12.1.2+ds-0kali1` 打包时只保留了空的 `help/<Module>_JavaHelpSearch/` 目录，
没有 JavaHelp 索引文件，但 33 个 helpset 仍然写入了**不带 `<data>` 的 Search 视图**。
JavaHelp 创建帮助窗口时 `MergingSearchEngine.makeEngine()` 对缺少 data 参数的视图返回 null，
`merge()` 抛出 `IllegalArgumentException: view is invalid`（首次 What's New/帮助页报错弹窗）；
搜索导航器缺失还会让 `docking.help.HelpViewSearcher` 抛 “Unable to locate help search engine”。

修复（来宾 overlay，可重复执行）：`tools/guest_fixes/kali-arm64/ghidra_help_fix.py`

- 用 Ghidra 自带 `javahelp-2.0.05.jar` 里的 `com.sun.java.help.search.Indexer` 为每个模块的
  `help/topics` 生成 `DOCS/DOCS.TAB/OFFSETS/POSITIONS/SCHEMA/TMAP`，写入既有的空搜索目录；
- 给对应 Search 视图补上 `<data engine="com.sun.java.help.search.DefaultSearchEngine">…</data>`；
- 所有改动先在临时文件里构建成完整 JAR 并校验，再用 `os.replace` 原子替换原文件；途中任何失败都只删除临时文件，
  JAR 保持原样。同一个 JAR 里的所有 helpset 会一次性生成索引、汇总全部 helpset 修改与索引文件，只构建一个临时 JAR、
  只替换一次，不会出现“第一个 helpset 已写入、第二个失败”的半修复状态。不依赖外部 `zip` 命令（只用 Python `zipfile`）；
- 原始 helpset 备份到 `/var/tmp/ctflab-ghidra-backup/`，脚本结束前复核剩余 0 个无 data 的 Search 视图；
- 单独 JAR 的失败只记录并保持该 JAR 原样，脚本可重复执行（已带 data 的 helpset 会跳过）。

回归测试：`tools/tests/test_ctflab_ghidra_fix.py` 用模拟 JAR 覆盖修复、幂等（第二次运行不改写 JAR）、
索引器失败/替换失败时原 JAR 不变且不留临时文件、索引不完整视为失败、root 检查与剩余复核；
其中包含同一个 JAR 内两个 helpset 的用例（一次替换全部修复；第二个 helpset 索引失败时 JAR 字节完全不变、
两个 helpset 都不带 data）。`tools/tests/test_ctflab_docs_commands.py` 会扫描 README 与 docs 里的
ctflab 命令：行内引用校验子命令与选项，代码块中的可执行示例还按 argparse 定义校验位置参数数量与
choices 取值（当前 55 处命令样例），示例里尚未 onboard 的 profile 需显式登记；实现计划中把 `.ctflab`
内容包写进可执行示例的两条 `import` 命令已改成真实命令，并注明内容包属于 Task 6 的交付物。

验证结果：

- 修复前后各复现一次 `view is invalid`（记录在 `application.log`）；
- 修复后连续两次启动（第一次显示 What's New，第二次通过 Help→Contents 打开帮助）日志中无 ERROR/Exception；
  What's New 与帮助窗口都实际显示，目录（TOC）可展开；
- 新建本地项目（GUI 向导，`~/ctflabtest`）、导入来宾内 gcc 编译的 aarch64 ELF、打开反编译窗口，
  Decompiler 输出与源码一致的 `main`/`adder` 代码；
- 搜索索引可查询：用 `DefaultSearchEngine` 直接查询 “decompiler” 命中 67 条，文档路径为 `topics/...`；
  帮助窗口内搜索标签页的点击与结果跳转没有做可视化确认。

恢复路径：`reset kali-arm64` 会丢弃 overlay 里的修复（回到未修复的发行包状态）；需要固化时先在来宾正常关机，
再执行 `./tools/ctflab finalize-install kali-arm64 --from-runtime --confirm`（会归档旧运行盘）。
更彻底的替代方案是改用上游官方 Ghidra 发行包（自带搜索索引），需要联网维护模式与单独确认。

## 5. 回归与边界

- `python3 -m unittest discover -s tools/tests`：54 项通过（新增停止/状态一致性测试、9 项 Ghidra 修复脚本测试
  ——模拟 JAR、幂等、同 JAR 双 helpset 回滚、索引器/替换失败、root 检查——以及 5 项文档命令校验测试：
  子命令/选项存在性、代码块命令的位置参数数量与 choices 取值、坏命令必须被拦住、内容包示例标注）。
- 未提交虚拟磁盘、日志、截图或凭据；临时测试口令只存在于权限受限的临时文件并在验证后删除。
- 本轮未验证：宿主窗口手动拖动缩放与全屏进出的主观体感、Cmd+H 隐藏/恢复、
  Ghidra GUI 内搜索标签页交互、剪贴板大文本/图片（仅文本）、动态分辨率的替代方案。
