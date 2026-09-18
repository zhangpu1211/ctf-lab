# CTFLab 联网与动态分辨率验证记录（2026-09-16）

本记录区分“代码已接入”“实际验证”和“运行时缺件”。当前课堂 App 的默认策略是：Kali 管理网通过
QEMU user-mode NAT 联网，Smoke/Basic 管理网使用 `restrict=on` 保持隔离；实验网仍只绑定本机回环交换机。
没有把口令、磁盘或运行日志写入仓库。

## 本轮复核：SPICE 点击定位与 Retina 自动分辨率（2026-09-18）

本节记录 2026-09-18 使用带 SPICE 后端的候选 `CTFLab.app` 的人工复核结果，结论范围限于
Kali 单显示器、普通窗口会话；不把一次人工成功升级为完整发布验收。

- **构建候选**：`/private/tmp/ctflab-auto-resolution-stage-20260918-r5/CTFLab.app`；
  App 树 SHA-256 为 `814d19555e4cb660009e3c9723a41de735907e542aa7f7e5eb554474e745d3d7`，
  `MANIFEST.json` SHA-256 为 `80c27bf9710a5048c347205b8bca2dea8c5736068b4731f7bbc1cbd6f8a40be9`。
  该候选位于临时目录，不是仓库发布物。
- **运行时能力**：构建时使用带 `spice-app` 的 QEMU 11.1.0；能力探测同时确认
  `spicevmc`、`virtserialport` 与受控本地客户端均可用。此前从 Homebrew 无 SPICE 后端构建的
  r3/r4 只能走 Cocoa，不能作为自动分辨率证据；r5 改用带 SPICE 的运行时后才进入本次复核。
- **点击定位**：人工点击桌面顶栏终端、文件系统等图标，打开目标与点击位置一致；此前“点 A
  打开 B”的 Retina 偏移现象未在本次会话复现。
- **自动分辨率**：客户端日志记录了真实的物理尺寸更新：
  `resize-target logical=1000x700 scale=2 physical=2000x1400`。这表示 GTK 逻辑像素按 Retina
  缩放因子转换后发送给来宾，而不是仅对画面做宿主侧缩放。该日志位于本机运行日志
  `~/Library/Application Support/CTFLab/logs/kali-arm64-spice-client.log`，未复制进仓库。
- **客户端生命周期**：同一日志记录 `quit-requested`，本次会话结束后没有保留图形客户端进程。

**本轮结论**：Kali 默认 `auto` 使用带 SPICE 的 QEMU 时，普通窗口下的来宾分辨率跟随和宿主点击定位
已人工复核通过。仍未覆盖全屏、多显示器、长时间连续拖拽、跨 Mac 接收端，以及剪贴板授权/未授权和
本地未授权客户端连接负向专项；这些边界不能由本轮成功替代。临时 App 不作为 GitHub 二进制发布物，
正式分发仍需 Developer ID 签名、公证和接收端验收。

## 本轮补充：窗口跟随问题已修复

下面第 3 节保留早期链路验证过程；最新结论以本节为准。

- 根因：SPICE 已更新 virtio-gpu 首选模式，XFCE 未自动应用，实际分辨率卡在 1280×800。
  来宾日志还出现 Mutter DBus 无 owner；同类现象见 [Debian #1065434](https://bugs.debian.org/1065434)。
- 客户端：`tools/spice_client/ctflab_spicy.c` 保留输入缩放变换，并在显示 surface、agent 与绝对鼠标
  模式均就绪后按 GTK allocation × Retina scale factor 主动发送来宾尺寸；只有运行器传入
  `--clipboard` 时才开启客户端剪贴板，USB、音频与拖入文件始终关闭。主通道先建立再创建显示控件；
  测试缩放钩子仅在 `CTFLAB_E2E_TEST` 编译中存在。
- 来宾：`configure.sh --display-only` 安装 XFCE 自启动适配；仅在 SPICE 端口存在的 X11 会话中，
  自动应用 `Virtual-*` 输出的有界首选模式，使用会话锁去重。它不修改持久分辨率配置和网络。
- 实测：16:52:29 来宾 `current 2000 x 1400`；16:52:49 来宾 `current 1600 x 1200`。
  对应真实 GTK 窗口 1000×700 / 800×600，当前 Retina 缩放因子为 2；过程中未手工执行 xrandr 设置命令。
- 冷启动复测：生产客户端登录后自动达到 2000×1400；适配由 XFCE 自动启动。
  重连同源码的测试客户端后，16:57:29 为 2000×1400，16:57:53 自动变为 1600×1200。
  同次启动还验证 Kali 的 user-mode NAT 路由为 eth1，经域名访问 Debian HTTPS 返回 200。
- 交付 App：`/Users/pufei/Downloads/ctflab-app-build-macos15-auto-final2-20260916/CTFLab.app`。
  生产客户端不包含自动缩放测试钩子。QEMU 11.1.0、797 个登记文件、70 个动态库；本轮又将 QEMU
  与 SPICE 客户端按 macOS 15.0 最低版本重建，以修复当时旧 App 在 macOS 26 构建标记上的启动失败。
  这段仅记录历史验证；当前产品最低要求已提升为 macOS 26.0。
- 当前 Kali 的派生磁盘已安装适配；原始基盘未修改。旧分发目录已由后续清理移除，新版无人值守安装
  和新版分发目录均包含该适配。尚未做公证及跨用户客户端连接拒绝 E2E。

客户端可复现构建（macOS 已安装 spice-gtk / GTK3 开发依赖）：

```sh
clang -Wall -Wextra -Werror tools/spice_client/ctflab_spicy.c -o /tmp/ctflab-spicy $(pkg-config --cflags --libs spice-client-gtk-3.0 gtk+-3.0)
```

将编译结果传给 `app build --spice-client`；构建器会将依赖库和许可证一并收集。

## 1. Kali 默认联网与靶机隔离：已验证

使用已导入的基盘，Kali 可以与一个或多个靶机一起启动；不需要再附加 `--internet`：

```zsh
CTFLAB_APP="/Users/pufei/Downloads/ctflab-app-build-macos15-auto-final2-20260916/CTFLab.app"
"$CTFLAB_APP/Contents/Resources/bin/ctflab-cli" --state-dir "$HOME/Library/Application Support/CTFLab" run kali-arm64 smoke --headless
"$CTFLAB_APP/Contents/Resources/bin/ctflab-cli" --state-dir "$HOME/Library/Application Support/CTFLab" health kali-arm64 --json
"$CTFLAB_APP/Contents/Resources/bin/ctflab-cli" --state-dir "$HOME/Library/Application Support/CTFLab" stop --all
```

实际来宾证据：

- `health --json` 先正确报告 `pending=true`，获得 DHCP 与 SSH 后报告 `pending=false`、`dhcp=192.168.242.10`、
  `ssh:22=通过`；最终 App 的实际来宾地址为 `10.0.2.15`（维护网）与 `192.168.242.10`（实验网）；
- 来宾路由含 `default via 10.0.2.2 dev eth1`，实验网仍是独立的 `eth0 / 192.168.242.0/24`；
- 来宾 DNS 解析 `deb.debian.org` 成功，HTTPS 请求返回 `HTTP=200`；
- `stop --all` 后 `status --json` 显示 `running_count=0`，没有残留交换机；运行状态中 Kali 的
  `internet_enabled=true`、Smoke/Basic 的 `internet_enabled=false`，且状态字段按节点记录。

联网边界保持不变：只有 Kali 获得 user-mode NAT；Smoke、Basic Pentesting 2 无论是否与 Kali 同次启动，
都使用 `restrict=on`，不会得到公网出口。`--internet` 保留为旧脚本的兼容确认参数，不能用于仅靶机命令。

## 2. GUI 节点选择：已接入，App 构建已覆盖

原生 GUI 从 `DISTRIBUTION.json` 的 `role=base` 条目生成当前节点选择，并在状态表展示全部已登记
profile；本机历史基盘明确标为“本机已登记”，不等同于当前分发目录已导入。用户一次选择一个节点后启动或停止；
其它节点运行时不阻塞当前节点操作。后续课程增加靶机无需为了 GUI 再写固定枚举。GUI 传入所选 profile；
当前 CLI 默认给 Kali 联网，并在完整能力存在时选择 SPICE 真实自动分辨率；能力缺失时 `auto` 退化为
Cocoa，显式 SPICE 缺件不回退。

2026-09-17 的客户端改动已通过 Swift 核心、GUI 源码与 C 语法/受控命令回归。真实 Kali 已用新客户端
连入（main/display/cursor/inputs 通道存在），正常 `stop kali-arm64` 后客户端进程消失；另一个无磁盘、
无网络的 QEMU+SPICE 最小会话中，直接结束 QEMU 后客户端也自行退出。客户端现增加了显式状态诊断（agent、
mouse-mode、display-ready、resize generation）与 `pid_t` 安全生命周期承载，resize timer 只接受最新代数，
断开/窗口关闭共用幂等退出路径。真实 Kali 桌面上的宿主鼠标点击/连续手工拖动仍受 GTK 窗口未暴露可操作
AX window 与 macOS 合成事件不能可靠激活该独立客户端的环境限制，不能据此把像素偏移宣称为已完全消除；
旧的临时 GDK 坐标注入不作为产品坐标证据。

同日新增“添加 x86 镜像…”向导：只读 `inspect --json` 后显示候选与置信度，用户确认才运行
`onboard --architecture x86_64`；候选 profile 外置到用户状态目录，既不改写 App 也不覆盖内置课程 profile。
首次 `probe` 失败后，用户可显式执行受控启动矩阵；矩阵命中不自动持久化。该向导目前只完成单元/编译验证，
尚未以任意真实外来 x86_64 镜像完成 GUI E2E。

## 3. 动态分辨率：SPICE 实验路径有历史验证，但不再作为默认启动路径

已接入并通过定向测试：

- `run --display auto` 是默认策略：Kali 在完整 SPICE 能力可用时使用真实自动分辨率，能力缺失时退化为
  Cocoa 固定显示；x86 靶机仍使用 Cocoa，`--headless` 不启动图形客户端；
- 显式 `--display spice` 仍只允许单独的 Kali 图形会话，显式 `--display cocoa` 用于排障；
- 显式请求 SPICE 前探测 `spice` 显示后端、`spicevmc`、`virtserialport` 和本地 `remote-viewer`/`spicy`；
- SPICE 使用 0700 runtime 目录下的 UNIX socket，保留唯一 virtio-serial + spicevmc agent transport；
- 未满足能力时在创建实验网、overlay 和 QEMU 进程前失败，明确写出缺件，不静默回退 Cocoa。

本轮用 QEMU 11.1.0 源码构建了带 SPICE 的 arm64 运行时，并把 `spicy` 及其动态库闭包纳入最终 App；
QEMU 与客户端当时以 `MACOSX_DEPLOYMENT_TARGET=15.0`、macOS 15.4 SDK 重建，避免出现
`built for macOS 26.0` / `_strchrnul` 启动错误。这是历史兼容性实验，不是当前发布要求：
当前产品只支持 macOS 26.0+：

- 验收 App：`/Users/pufei/Downloads/ctflab-app-build-macos15-auto-final2-20260916/CTFLab.app`；
- `app verify`：797 个登记文件、70 个动态库、许可证文本完整性 `True`；
- 内置 QEMU `-display help` 含 `spice-app`，`-device help` 含 `virtserialport`；
- `run kali-arm64 --display spice` 实际启动成功，0700 runtime 目录下 UNIX socket 建立，内置 `spicy`
  连接成功，状态报告 `client_count=1`；
- 重启后再次登录 Kali，`/dev/virtio-ports/com.redhat.spice.0` 存在，`spice-vdagent` 与
  `spice-vdagentd` 均运行；XFCE 自启动适配会读取 SPICE 提供的 `Virtual-*` 首选模式并应用到当前
  `xrandr` 模式。
- 实际窗口跟随证据：真实 GTK 窗口 `1000x700` / `800x600`（当前 Retina 缩放因子为 2）对应来宾
  `2000x1400` / `1600x1200`；采样记录为 `16:52:29 current 2000 x 1400`、
  `16:52:49 current 1600 x 1200`。冷启动后自动恢复到 `2000x1400`，重连测试客户端后再次跟随到
  `1600x1200`。
- 该过程未由测试者手工执行 `xrandr` 设置命令；生产客户端不含测试缩放钩子。

当前仍保留的边界：`--clipboard` 正向/未授权剪贴板负向、未授权客户端连接拒绝，以及 TCP 回退模式
尚未完成独立 E2E。SPICE 缺件时不会自动回退 Cocoa，而是在创建虚拟机前明确失败。旧分发目录已清理；
现用包含显示适配的新版目录
`/Users/pufei/Downloads/ctflab-dist-spice-release-20260916/`，其 `dist verify --json` 已通过 4/4，
Kali 基盘哈希为 `974a319f596170d171e75a5ee3e0f0fd4d28439ab10373c14f0fd9348b396315`。

## 4. 回归

- 最终完整回归：`python3 -m unittest discover -s tools/tests -q`，输出 `Ran 366 tests ... OK (skipped=5)`；即 361 项实际执行通过、5 项按历史 UTM 交付目录缺失规则跳过。负向口令用例输出的 `FAIL guest-password` 是预期失败样本，不是 unittest 失败；
- `python3 -m py_compile tools/ctflab.py tools/ctflab_app.py tools/ctflab_dist.py`：通过；
- Swift 核心测试：通过；
- 定向 CLI/GUI/安装器测试：通过；
- 动态分辨率的运行时 E2E：两档窗口尺寸实际跟随、冷启动恢复与重连后再次跟随均已验证；旧分发包保持不变，新版分发目录 `dist verify --json` 通过 4/4。
- 最终 App `app verify` 通过；测试结束后 `running_count=0`、全部 `internet_enabled=false`，临时测试客户端已退出。
- 本轮生产 App 复测：`auto` 实际解析为 SPICE，干净 overlay 登录后 `xrandr` 自动恢复 `2000x1400`；QEMU、SPICE socket 和客户端 PID 状态可追踪。宿主真实点击/拖动的可复现验收仍需一个能把焦点交给独立 GTK 客户端窗口的 macOS GUI 测试环境；本机 AX 可见窗口但不暴露可操作 AX window，合成鼠标事件因此不能作为真实用户输入证据。
