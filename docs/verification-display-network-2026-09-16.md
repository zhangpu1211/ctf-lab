# CTFLab 联网与动态分辨率验证记录（2026-09-16）

本记录区分“代码已接入”“实际验证”和“运行时缺件”。当前课堂 App 的默认策略是：Kali 管理网通过
QEMU user-mode NAT 联网，Smoke/Basic 管理网使用 `restrict=on` 保持隔离；实验网仍只绑定本机回环交换机。
没有把口令、磁盘或运行日志写入仓库。

## 本轮补充：窗口跟随问题已修复

下面第 3 节保留早期链路验证过程；最新结论以本节为准。

- 根因：SPICE 已更新 virtio-gpu 首选模式，XFCE 未自动应用，实际分辨率卡在 1280×800。
  来宾日志还出现 Mutter DBus 无 owner；同类现象见 [Debian #1065434](https://bugs.debian.org/1065434)。
- 客户端：`tools/spice_client/ctflab_spicy.c` 显式开启 `resize-guest`；只有运行器传入 `--clipboard`
  时才开启客户端剪贴板，USB、音频与拖入文件始终关闭。主通道先建立再创建显示控件；测试缩放
  钩子仅在 `CTFLAB_E2E_TEST` 编译中存在。
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

原生 GUI 现在从 `DISTRIBUTION.json` 的 `role=base` 条目动态生成启动选择，并在状态表展示全部已登记
profile；用户可取消任意靶机后点击“启动未运行的所选节点”，或在单行直接启动/停止。因此一个节点已运行时，
其余已导入节点仍可启动；后续课程增加靶机无需为了 GUI 再写固定枚举。GUI 传入所选 profile，CLI 负责为
Kali 自动选择联网/SPICE，为靶机选择隔离/Cocoa。

2026-09-17 的客户端改动已通过 Swift 核心、GUI 源码与 C 语法/受控命令回归。真实 Kali 已用新客户端
连入（main/display/cursor/inputs 通道存在），正常 `stop kali-arm64` 后客户端进程消失；另一个无磁盘、
无网络的 QEMU+SPICE 最小会话中，直接结束 QEMU 后客户端也自行退出。真实 Kali 桌面上的点击坐标与连续
窗口拖动复测尚未执行，不能据此把黑屏刷新或像素偏移宣称为已完全消除。

同日新增“添加 x86 镜像…”向导：只读 `inspect --json` 后显示候选与置信度，用户确认才运行
`onboard --architecture x86_64`；候选 profile 外置到用户状态目录，既不改写 App 也不覆盖内置课程 profile。
首次 `probe` 失败后，用户可显式执行受控启动矩阵；矩阵命中不自动持久化。该向导目前只完成单元/编译验证，
尚未以任意真实外来 x86_64 镜像完成 GUI E2E。

## 3. 动态分辨率：SPICE 窗口跟随已验证，按钮已移除

已接入并通过定向测试：

- `run --display auto` 是默认策略：图形 Kali 自动使用 SPICE，靶机自动使用 Cocoa；
  `--headless` 不启动图形客户端；
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

- 最终完整回归：`python3 -m unittest discover -s tools/tests -q`，输出 `Ran 365 tests ... OK (skipped=5)`；即 360 项实际执行通过、5 项按历史 UTM 交付目录缺失规则跳过。负向口令用例输出的 `FAIL guest-password` 是预期失败样本，不是 unittest 失败；
- `python3 -m py_compile tools/ctflab.py tools/ctflab_app.py tools/ctflab_dist.py`：通过；
- Swift 核心测试：通过；
- 定向 CLI/GUI/安装器测试：通过；
- 动态分辨率的运行时 E2E：两档窗口尺寸实际跟随、冷启动恢复与重连后再次跟随均已验证；旧分发包保持不变，新版分发目录 `dist verify --json` 通过 4/4。
- 最终 App `app verify` 通过；测试结束后 `running_count=0`、全部 `internet_enabled=false`，临时测试客户端已退出。
