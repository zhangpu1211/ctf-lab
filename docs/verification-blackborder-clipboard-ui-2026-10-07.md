# 验证记录：黑边根因修复、剪贴板路径、UI 简化（2026-10-07）

用户对重建 App（ad50be1a…）实测后反馈六项，本文记录其中可自动化部分的定位、
修复与验证。复现环境：用户真实状态目录（kali-arm64 持久 overlay，自动登录
桌面 = agent=1 场景）、受控 QEMU（app 内 11.1.0 SPICE 构建）、修复后现场编译
客户端。

## 1. 缩放后黑边（信箱效应）——根因与修复

### 定位链

1. 用户会话客户端日志（~/Library/Application Support/CTFLab/logs/
   kali-arm64-spice-client.log）：所有 `display-transition end` 均为
   `reason=timeout`，且窗口拖动产生 577 次 configure 事件、门禁全部通过
   （`agent=1 mouse-mode=2`，`SPICE_MOUSE_MODE_CLIENT=(1<<1)=2` 即绝对坐标
   正常）——请求确实发出，来宾从未应用任何分辨率。
2. spice-gtk 0.42 源码（brew bottle 对应上游 tag）核实：
   - `spice_main_channel_init` 不初始化 `display_state`，默认
     `DISPLAY_UNDEFINED`；
   - monitors config 组包只收录 `DISPLAY_ENABLED` 的显示器；
   - 发送前检查 `display_state == DISPLAY_UNDEFINED` 时直接
     `SPICE_DEBUG("Not sending monitors config, missing monitors")` 拒发。
   - 我们的客户端从未调用 `spice_main_channel_update_display_enabled()`，
     因此每次 `update_display()` 只更新内存映射，**monitors config 从未真正
     发给来宾**；spice-gtk 按画布原始宽高比缩放 → 窗口与来宾宽高比不一致
     → 上下黑边。
3. 此前 E2E 为什么没发现：test_ctflab_resolution_lifecycle_e2e 的 frame-matched
   断言只在 `agent=1` 时执行；登录墙下 agent 恒为 0，断言被条件跳过——
   **分辨率跟随从未在已登录桌面被真实验证过**。本轮用用户的自动登录 overlay
   补齐了这一场景。

### 修复（tools/spice_client/ctflab_spicy.c）

- `apply_guest_resize()` 首次发送前调用
  `spice_main_channel_update_display_enabled(main, 0, TRUE, FALSE)`，并记
  `CTFLAB_SPICE_STATE display-enabled id=0` 日志行。
- 过渡窗口 1500ms → 3000ms（实测来宾 modeset 1.7–2.7s，旧窗口把成功的
  应用误报为 timeout）；E2E `FOLLOW_TARGET_MS` 2000 → 3000 对齐。
- timeout 时新增 `display-transition observed=WxH target=WxH` 日志行，区分
  “来宾未应用”与“应用了别的模式”。

### 真机验证（用户 overlay，自动登录，Retina multiplier=2）

驱动计划 5 步（1280x800 → 1600x1000 → 1000x700 → 全屏 → 退出全屏）：
**5/5 `reason=frame-matched`**，跟随耗时 1731/2226/1876/2072/2672ms；
首次应用伴随 `display-ready=0→1`（来宾真实 modeset 重建 surface）。
修复前同一节点 0/6（全部 timeout）。停止路径干净：quit-requested →
window-state-saved，无新增崩溃报告。

## 2. 双向文本/文件复制

事实链（来自用户 run.json 与客户端日志）：

- 用户最后一次 GUI 运行 `clipboard_enabled: false`，QEMU 参数带
  `disable-copy-paste=on`——**剪贴板在服务端就是关闭的**，双向文本复制在
  该会话必然失效。GUI 的“剪贴板”是显式授权开关（默认关），本轮已用
  `run --clipboard` 实测：`clipboard-h2g bytes=48` 正常推送。
- 客户端剪贴板实现（pbpaste/pbcopy 桥 + 主机轮询线程 + 回声抑制）单元
  测试 7 项全过（test_ctflab_clipboard_lifecycle）。
- 新增 macOS 肌肉记忆桥接：窗口聚焦时 **Command+C/V/X/A/Z 映射为来宾
  Ctrl+C/V/X/A/Z**（spice 协议不认识 Command；此前在来宾里按 Cmd+C 无效，
  是“复制不了”的直接原因之一）。snooper 消费原事件并注入 press+release
  组合，记 `CTFLAB_SPICE_STATE mac-shortcut ctrl+X` 日志行。
- 文件复制：SPICE 协议的 agent 文件传输只支持 **主机→来宾**（拖入），且
  本项目按边界设计默认 `disable-agent-file-xfer=on`（路线图为“文本共享与
  文件传输分开授权”）；**来宾→主机文件复制不是 SPICE 能力**（UTM/remote-
  viewer 同样没有），需走 sshfs/共享目录类方案，未实现、未伪造。

## 3. “没有登录直接进了 Kali”

仓库与 guest_fixes 无任何自动登录配置；此前多轮 E2E 的全新 overlay 都停在
登录界面（agent=0，275s 观测）。用户的 kali-arm64 overlay 里的自动登录是
来宾内（overlay 层）的改动，不是本仓库行为。恢复登录界面的途径：
`ctflab snapshot create kali-arm64 <名>` 留底后 `ctflab reset kali-arm64`，
或直接在来宾显示管理器里关闭自动登录。本轮未替用户重置（overlay 属用户数据）。

## 4. 列表中的两个 "Webserver"

- `webserver`：随包内置课程靶机（tools/ctflab_profiles/webserver.yaml，
  x86_64/UEFI/SCSI），未导入时也始终显示，属正常。
- `webserver-e2e`：早期接入测试遗留的用户目录登记（profiles/
  webserver-e2e.yaml，未导入）。新增 `ctflab deregister PROFILE` 子命令
  （守卫：拒绝内置配置、拒绝已导入/运行中，只删用户目录 yaml），已用它
  移除该遗留登记；`status --json` 新增 `builtin` 字段供 GUI 区分。

## 5. UI 简化（第 1 项切片）

- 主操作区只留 启动 / 停止 / 重启 + “导入…”菜单（添加 x86 镜像…、校验成套
  分发…、导入成套实验环境）+ “更多”菜单（检查状态、重置全部节点…）。
- “分发目录”改为“镜像文件夹”：可为普通文件夹、可为空；选择后自动扫描
  顶层磁盘镜像（qcow2/ova/vmdk/vdi/vhd/vhdx/img/raw）列出并可逐个进入
  接入向导；含成套分发清单时自动校验。
- **启动不再要求先校验镜像文件夹**：只依赖状态目录已导入节点（空文件夹/
  未选文件夹也能启动已导入节点）。
- 节点表：登记名与 ID 并列（同名登记可区分）、右键菜单（启动/停止/重启/
  移除未导入登记）；此前已交付的搜索框保留。
- Swift 核心测试 122 项全过（含新增：displayLabel 去重、ImageFolderScanner、
  deregister 参数、builtin 解析、启动门禁新语义）。

### 5b. 两栏主区（用户追加反馈：去掉“当前节点”下拉，左右分栏）

- 移除“当前节点”选择器；选择改在左侧列表完成。
- 主区两栏：**左侧统一镜像列表**（“已登记节点”分组 + “文件夹镜像（未导入）”
  分组，搜索框过滤两者，状态用圆点与短文案标注；未选文件夹时仍显示已登记
  节点），**右侧当前状态与操作**（节点：状态/启动进度/显示客户端/健康/PID/
  诊断提示/日志路径 + 启动/停止/重启/重置此节点…/移除登记…；文件夹镜像：
  文件信息 + 识别并导入…）。
- 新增单节点重置（独立确认弹窗，区别于“重置全部”）；顶部只留 导入… 与
  更多 两个菜单；成套分发校验表仅在有校验结果时出现（普通文件夹不占位）。
- GUI 测试更新为两栏断言（22 项全过，含从源码构建 GUI 可执行文件的用例）；
  相关回归 test_ctflab_status_docs + test_ctflab_app 共 141 项 OK。

### 5c. 文件夹即来源 + 自动导入（用户第二轮追加反馈）

- 左侧列表改为**只显示已导入镜像**；未导入登记不再占列表。
- “选择文件夹”与“扫描并导入新增”按钮都会走 `scanAndImport()`：有
  DISTRIBUTION.json 的成套目录先校验再按清单导入缺失节点；普通文件夹对每个
  新镜像执行 `onboard`（不带 --architecture，由 inspect 证据推断，x86_64 与
  aarch64 均可接入）。幂等：`status --json` 新增 `source_path`，已导入来源
  与 id 冲突的文件自动跳过；失败记录日志并继续下一个。
- 左栏加宽到 460、主区最小高度 440、窗口最小 1080x760；CLI 输出收进默认
  折叠的 DisclosureGroup（错误横幅仍即时可见）。
- “更多”菜单新增 **“共享文本剪贴板（启动时生效）”** 开关（记忆在用户默认
  值）：此前 GUI 从不传 `--clipboard`，图形入口用户永远没有剪贴板——这是
  “双向文本复制存在问题”在 GUI 侧的另一半原因。
- Swift 核心测试 124 项全过；test_ctflab_gui/status_docs/app 共 163 项 OK。

### 5d. 删除镜像（用户问“还没导入为什么列表有镜像”）

- 说明：列表读取状态目录（~/Library/Application Support/CTFLab），条目是
  历史导入的留存（本轮测试中的 kali-arm64 与早前导入的 smoke/basic/
  webserver），与“本次会话是否导入过”无关。
- 新增 `ctflab remove PROFILE` 与右栏 **“删除镜像…”** 按钮（已导入且已停
  止时出现，独立确认弹窗）：删除基盘副本、运行 overlay 与导入登记
  （`LabManager.remove_image`，带运行守卫与“无数据”拒绝）；原始来源镜像与
  整盘备份区不受影响；内置课程配置保留（回到“未导入”），用户登记的 yaml
  一并移除。
- 单元测试：remove_image 的删除/运行守卫/幂等拒绝（test_ctflab_lifecycle
  RemoveImageTests 2 项）；Swift 核心测试 125 项全过。

### 5e. 消除“文件夹镜像”与“镜像”列表重合（用户第三轮追加反馈）

- 左栏“文件夹镜像”分组改为**只显示真正待导入的文件**：与自动导入共用
  `pendingImageEntries()` 同一判据（来源未导入且建议 id 未被占用）——
  已导入的文件、历史上从别处导入的同名来源都不再出现；导入完成后分组
  为空即整组隐藏。分组更名“文件夹新增（待导入）”。
- 从分组导入成功后自动退选该文件，右侧切到新导入的节点。
- 回归：GUI 测试 22 项 OK、Swift 核心测试 125 项全过；App 重建后
  verify 通过（许可证完整性 True）。

## 6. “鼠标无法点击 / 最小化后窗口打不开”（用户报告，本轮修复）

日志证据：该会话两次分辨率应用均 frame-matched、客户端全程响应、停止时
优雅退出——排除主循环卡死与 shield 覆盖层卡住。两项针对性修复：

1. **最小化后无法还原**：纯 GtkWindow + gtk_main 在 GTK3 quartz 后端没有
   NSApplicationDelegate，Dock 点击（applicationShouldHandleReopen）不会还原
   最小化窗口。客户端迁移到 **GtkApplication**（`G_APPLICATION_NON_UNIQUE`
   且不带 app id，多节点客户端互不抢占）：Dock 重开触发 activate，检测到
   已有窗口即 `gtk_window_present` 还原。
2. **点击无反应的可诊断性**：spice-gtk 的 `button_event` 对“换算后落在画面
   区域外”的点击**静默丢弃**（transform_input 越界检查）。新增
   `input-press win=x,y alloc=WxH guest=WxH` 日志行（用户信号先于 RUN_LAST
   类处理器执行，被丢弃的点击也会留下坐标证据）。再次复现时用该行区分
   “输入被丢弃”与“来宾未响应”。
3. 附带修复：最小化/隐藏时立即结束分辨率过渡并释放按键；runner 的客户端
   优雅退出窗口 1s → 6s，且客户端 SIGTERM 路径自带 alarm(4) 兜底——主循环
   偶发被过渡轮询（spice_display_get_pixbuf 在通道重建期间可阻塞）卡住时，
   优雅路径跑不完就被 SIGKILL 且日志全丢（本轮 E2E 一次失败与一次手工复现
   均为此形态）；兜底用 write(2) 记 `quit-forced-timeout` 后 _exit(0)。
   正常路径实测 0.2s 完整退出（quit-requested → window-state-saved →
   disconnected）。
- 真机冒烟：GtkApplication 版客户端启动/连接/分辨率跟随/优雅停止全链正常，
  无新增崩溃报告。修复后桌面 E2E 2/2 通过（ACPI 正常关机），全量回归 443 项
  OK（8 项既有环境门控跳过）。点击与 Dock 还原需用户在桌面环境复测。
- 另观测一次来宾 30s 未响应 ACPI（`stop --graceful` 保留实例并提示关机确认
  框）：graceful 路径按设计保留进程与数据；GUI 停止走强制梯级不受影响；根因
  在来宾会话侧，未定位，复现时保留 QEMU/客户端日志再归因。

## 7. 用户复测三轮反馈：分辨率疑问 / 点击向下偏移 / 最小化后消失

日志证据（用户会话，21:5x）：

- **分辨率**：客户端两次请求（3024×1834、2984×1794）均 frame-matched，
  来宾真实应用；窗口与画布等比全填充。客户端侧跟随正常。
- **点击偏移**：input-press 诊断行记录了 `alloc=1158x739` 与多次点击坐标，
  但 `guest=0x0`——诊断接线传了 NULL 而不是上下文（本轮已修）。spice-gtk
  的换算数学在等比全填充下自洽，"左上角正常、越往下偏得越多"最可能来自：
  (a) 冻结帧拉伸填满与输入映射（按信箱几何换算）的视差——本轮已把冻结帧
  改为与 spice 完全一致的等比居中；(b) 来宾侧 X 状态（显示跟随 watcher 与
  客户端 monitors config 的模式竞争、或 panning）——诊断已增强（guest 与
  canvas-req 两个维度），下次复现即可定位。
- **最小化后消失**：会话日志显示客户端全程存活、最终优雅退出——窗口层
  问题。activate 的恢复路径从无条件 `gtk_window_present`（quartz 上对已
  最小化窗口可能把窗口撤下）改为**按窗口状态分支**：最小化时
  `gtk_window_deiconify`，否则 present。
- 修复后回归：客户端单元测试 12 项 OK、桌面 E2E 2/2 通过（ACPI 正常关机）、
  App 重建 verify 通过。点击偏移与 Dock 恢复需用户复测；偏移若仍在，
  input-press 行的 guest/canvas-req 数据可直接判定客户端映射还是来宾侧。

### 7b. 窗口权威护栏（点击偏移的直接修复，真实根因见 7c）

### 7c. 【最终根因】来宾 vdagent 指针映射缓存旧屏幕尺寸（2026-10-08 破案）

用户复测"点击还是不行 + 分辨率显示太小"。SSH 进入来宾（口令取自本机
0600 安装资产，用后即删）直接测量：

- `xdotool getmouselocation`：指针冻结在 (640,400)=**旧 1280x800 模式的
  中心**，屏幕已是 3024x1834；键盘正常、XTest（xdotool mousemove）正常、
  spice-vdagent/-vdagentd 均存活。
- 客户端经 inputs 通道直发绝对位置（绕过 GTK）(200,300) → 指针落在
  (472,687)：**472=200×(3024/1280)、687=300×(1834/800)** —— spice-vdagent
  0.23 在客户端驱动的分辨率切换后，仍按会话启动时的屏幕尺寸换算绝对指针
  坐标再映射到当前屏幕。这精确解释全部症状：点击向右下偏移、左上角近似
  正常、分辨率越高（×2 密度）偏移越大、键盘不受影响。
- `systemctl restart spice-vdagentd` 后重发 (400,500)/(300,600) →
  **像素级精确命中**。

修复（两层）：

1. **来宾侧（对现有 overlay 即时生效）**：DRM 模式切换的 udev 规则
   （92-ctflab-vdagent-refresh.rules）→ 节流脚本（≥2s 一次）重启
   spice-vdagentd。真机验证：来宾内 xrandr 改模式 → 守护进程自动重启
   （ActiveEnterTimestamp 更新）→ 注入位置像素级命中。已通过 SSH 装进
   用户当前 overlay；并入库
   tools/guest_fixes/kali-arm64/configure.sh（新镜像自带）。
2. **分辨率显示太小**：默认清晰度由 sharp（Retina ×2，UI 减半）改为
   **smooth（1:1 逻辑分辨率，UI 正常大小）**——客户端无记忆时回退
   smooth；GUI"更多"菜单新增"清晰优先"开关（默认关=流畅，经
   --display-quality 透传并沿用节点记忆）。用户节点此前记忆的 sharp 由
   GUI 显式 smooth 覆盖。

凭据处理：安装资产口令仅提取到 0600 临时文件用于本次诊断 SSH，验证
完成后已删除；未回显、未入库、未写入任何日志。

回归：客户端单元 12 项、GUI/status/app 163 项、Swift 核心 126 项全过；
App 重建后 verify 通过（许可证完整性 True）、桌面 E2E 2/2（ACPI 通过）。



用户复测反馈偏移仍在。真机日志（自动登录会话）在启动阶段捕获到**来宾侧
分辨率抢夺**：guest-monitors 序列 1280x800 → 1280x720（来宾守护改写）→
护栏重申(count=1) → 1280x800 → 重申(count=2) → **2316x1478（窗口目标）**。
这证实偏移的根源：来宾侧守护（显示跟随/会话设置）自行改分辨率后，客户端
仍认为窗口目标已生效——绘制用新画布、输入按旧几何换算，表现为"左上角
正常、越往下偏得越多"（用户两次会话的 input-press 证据与此一致）。

修复（tools/spice_client/ctflab_spicy.c）：

- 显示通道 `notify::monitors`（来宾上报）→ `on_guest_monitors_changed`：
  上报值 ≠ 最近提交值时限速（≥4s）重申窗口推导目标，连续 5 次被改写即
  停手并留 `guest-override-reassert count=N` 日志（防与来宾守护打持久战）。
- input-press 诊断升级：`canvas=` 记录真实画布（get_pixbuf），与 `guest=`
  （提交值）并列——再出现分叉一眼可辨。
- 真机验证：护栏两次重申后收敛到窗口目标，随后 E2E 驱动 5 步全部干净跟随
  （guest-monitors 与目标一一对应、5/5 frame-matched）；客户端单元测试
  12 项 OK；App 重建后桌面 E2E 2/2 通过（一次失败为当晚多轮 VM 叠加的
  偶发时序，复跑通过）。

## 复现命令

```bash
# 严格编译客户端（含 E2E 驱动副本）
clang -Wall -Wextra -Werror -mmacosx-version-min=26.0 tools/spice_client/ctflab_spicy.c \
  -o /tmp/ctflab-spicy $(pkg-config --cflags --libs spice-client-gtk-3.0 gtk+-3.0)
clang -Wall -Wextra -Werror -mmacosx-version-min=26.0 -DCTFLAB_E2E_TEST \
  tools/spice_client/ctflab_spicy.c -o /tmp/ctflab-spicy-e2e \
  $(pkg-config --cflags --libs spice-client-gtk-3.0 gtk+-3.0)

# 真机分辨率跟随（用户 overlay 自动登录场景；会弹窗并自动驱动 5 步）
CTFLAB_TEST_RESIZE=1 CTFLAB_RUNTIME_ROOT=<app>/Contents/Resources/runtime \
  CTFLAB_SPICE_CLIENT=/tmp/ctflab-spicy-e2e \
  python3 tools/ctflab.py run kali-arm64 --display spice --internet --clipboard
# 观察日志：display-enabled id=0 后 5 步全部 frame-matched
grep -E "display-enabled|drive-step|transition end" \
  "$HOME/Library/Application Support/CTFLab/logs/kali-arm64-spice-client.log"

# GUI 核心测试与相关回归
cd tools/tests && /opt/miniconda3/bin/python3 -m unittest \
  test_ctflab_client_input test_ctflab_clipboard_lifecycle \
  test_ctflab_gui test_ctflab_status_docs -v
swiftc gui/GuiCore.swift gui/GuiCoreTests.swift -o /tmp/guicore-tests && /tmp/guicore-tests
```

## 未验证项 / 边界

- 剪贴板“来宾→主机”文本方向与 Cmd 快捷键映射需人工在来宾桌面复测（自动
  化无来宾内输入通道）；本轮仅验证协议路径与 h2g 推送。
- 文件传输（主机→来宾拖入）仍按边界默认关闭，未实现开关与验证。
- UI 改版为 Swift 编译与核心逻辑测试级验证，未做真实点击级验收（需用户
  打开新 App）。
- GUI 快照/存储/network 接线、UTM 对比、签名公证仍未做（此前记录不变）。


## 8. 【2026-10-08 终局】usb-tablet 鼠标路径 + 检测机制

### 8a. udev 重启方案的失败与撤销（诚实记录）

首次"udev 重启 vdagentd"方案在受控注入下看似生效，但用户复测仍偏移且新增
卡顿。深入测量推翻了它：

- 会话代理 `spice-vdagent`（X 客户端，xdg autostart）不随
  `spice-vdagentd`（系统守护）重启而重生；它缓存的绝对轴范围才是映射基准。
- 顺序实验（新代理→重启守护 / 风暴→防抖重启）均无法稳定恢复映射；
  且 agent 反复断连重连正是"明显卡顿"的来源。
- udev 规则与脚本已从用户 overlay 删除，guest_fixes 的对应草稿也已撤销。

### 8b. 架构级修复：绝对鼠标改走 usb-tablet（内核映射）

QEMU `-spice` 加 `agent-mouse=off`：绝对指针不再经 vdagent 的 uinput
（其轴范围在守护进程启动时按当时屏幕创建，动态分辨率后不更新——实测
1512x917 下注入 (400,500) 落 (472,573)=×1512/1280），改由 QEMU 内置
usb-tablet 直达内核 evdev，坐标按当前屏幕实时换算，不存在任何缓存层。

真机验证矩阵（注入 (x,y) → xdotool 回读）：

| 场景 | 注入 | 回读 | 判定 |
|---|---|---|---|
| 初始（1512x917） | 300,300 | 299,299 | 像素级（±1 为 X 取整） |
| 模式切换 1024x768↔1512x917 后 | 500,400 | 499,399 | 像素级 |
| 连续 4 次 modeset 风暴后 | 200,200 | 199,199 | 像素级 |
| 客户端存活 | — | — | 风暴后 alive（修复通道销毁崩溃后） |

顺带修复：inputs 通道销毁回调未清空指针（E2E 注入钩子在 agent-mouse=off
下触发 spice channel_destroy 路径崩溃，崩溃报告
ctflab-spicy-e2e-2026-10-08-093423.ips）；destroy 时置空 + 使用前 SPICE_IS
判活。测试钩子仍仅在 E2E 构建编译。

### 8c. 检测机制（用户要求落实）

1. **指针映射自检（判定性，无需看屏幕）**：E2E 客户端
   `CTFLAB_TEST_SENDPOS=1` 下写 `/tmp/ctflab-sendpos`（内容 `x y seq`，
   seq 递增）经 inputs 通道直发绝对位置，SSH `xdotool getmouselocation`
   回读比对（容差 ±2px）。任何"点击偏移"类报告用此 30 秒定位到层
   （客户端换算 / vdagent 缓存 / 内核映射）。
2. **持续可观测**：客户端日志现有 `input-press win/alloc/guest/canvas`
   逐点击记录——canvas≠guest 即模式分叉；`guest-monitors=` 记录来宾每次
   上报；`guest-override-reassert` 记录护栏动作。
3. **回归守护**：桌面 E2E（CTFLAB_DESKTOP_E2E=1）在 agent 就绪后驱动
   三档窗口+全屏并断言 frame-matched（分辨率真实应用）。
4. **新镜像防线**：configure.sh 的 vdagent 重启方案已撤销回退；usb-tablet
   路径为运行器默认（无需来宾改动），随 App 分发自动生效。

### 8d. 回归

客户端单元 12 项、GUI/status/app 163 项、Swift 核心 126 项全过；App 重建
verify 通过；桌面 E2E 2/2（ACPI 通过）。凭据临时文件已删除。
