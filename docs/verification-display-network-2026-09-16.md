# CTFLab 联网与动态分辨率验证记录（2026-09-16）

本记录区分“代码已接入”“实际验证”和“运行时缺件”。联网只在明确授权的 Kali 维护模式中测试，
结束后恢复默认隔离状态；没有把口令、磁盘或运行日志写入仓库。

## 本轮补充：窗口跟随问题已修复

下面第 3 节保留早期链路验证过程；最新结论以本节为准。

- 根因：SPICE 已更新 virtio-gpu 首选模式，XFCE 未自动应用，实际分辨率卡在 1280×800。
  来宾日志还出现 Mutter DBus 无 owner；同类现象见 [Debian #1065434](https://bugs.debian.org/1065434)。
- 客户端：`tools/spice_client/ctflab_spicy.c` 显式开启 `resize-guest`，关闭剪贴板、USB、音频与拖入文件。
  主通道先建立再创建显示控件。测试缩放钩子仅在 `CTFLAB_E2E_TEST` 编译中存在。
- 来宾：`configure.sh --display-only` 安装 XFCE 自启动适配；仅在 SPICE 端口存在的 X11 会话中，
  自动应用 `Virtual-*` 输出的有界首选模式，使用会话锁去重。它不修改持久分辨率配置和网络。
- 实测：16:52:29 来宾 `current 2000 x 1400`；16:52:49 来宾 `current 1600 x 1200`。
  对应真实 GTK 窗口 1000×700 / 800×600，当前 Retina 缩放因子为 2；过程中未手工执行 xrandr 设置命令。
- 冷启动复测：生产客户端登录后自动达到 2000×1400；适配由 XFCE 自动启动。
  重连同源码的测试客户端后，16:57:29 为 2000×1400，16:57:53 自动变为 1600×1200。
  同次启动还验证 `--internet --display spice` 联用，维护路由为 eth1，经域名访问 Debian HTTPS 返回 200。
- 交付 App：`/Users/pufei/Downloads/ctflab-app-build-spice-release-20260916/CTFLab.app`。
  生产客户端不包含自动缩放测试钩子。QEMU 11.1.0、797 个登记文件、70 个动态库。
- 当前 Kali 的派生磁盘已安装适配；原始基盘及旧分发目录未修改。旧镜像重新导入或重置后需补装，
  新版无人值守安装自动包含。尚未做公证及跨用户客户端连接拒绝 E2E。

客户端可复现构建（macOS 已安装 spice-gtk / GTK3 开发依赖）：

```sh
clang -Wall -Wextra -Werror tools/spice_client/ctflab_spicy.c -o /tmp/ctflab-spicy $(pkg-config --cflags --libs spice-client-gtk-3.0 gtk+-3.0)
```

将编译结果传给 `app build --spice-client`；构建器会将依赖库和许可证一并收集。

## 1. Kali 联网维护模式：已验证

使用已导入的 Kali 基盘，先确认其他节点均停止，再执行：

```zsh
CTFLAB_APP="/Users/pufei/Downloads/ctflab-app-build-spice-release-20260916/CTFLab.app"
"$CTFLAB_APP/Contents/Resources/bin/ctflab-cli" --state-dir "$HOME/Library/Application Support/CTFLab" run kali-arm64 --internet --headless
"$CTFLAB_APP/Contents/Resources/bin/ctflab-cli" --state-dir "$HOME/Library/Application Support/CTFLab" health kali-arm64 --json
"$CTFLAB_APP/Contents/Resources/bin/ctflab-cli" --state-dir "$HOME/Library/Application Support/CTFLab" stop --all
```

实际来宾证据：

- `health --json` 先正确报告 `pending=true`，获得 DHCP 与 SSH 后报告 `pending=false`、`dhcp=192.168.242.10`、
  `ssh:22=通过`；最终 App 的实际来宾地址为 `10.0.2.15`（维护网）与 `192.168.242.10`（实验网）；
- 来宾路由含 `default via 10.0.2.2 dev eth1`，实验网仍是独立的 `eth0 / 192.168.242.0/24`；
- 来宾 DNS 解析 `deb.debian.org` 成功，HTTPS 请求返回 `HTTP=200`；
- `stop --all` 后 `status --json` 显示 `running_count=0`，所有节点 `internet_enabled=false`，没有残留交换机。

联网边界保持不变：`--internet` 只能单独用于 `kali-arm64`，Smoke、Basic Pentesting 2 和多节点命令均拒绝；
课堂默认 `run` 仍使用 `restrict=on` 的隔离 user-net 和回环实验网。

## 2. GUI 联网入口：已接入，App 构建已覆盖

原生 GUI 已加入“Kali 联网维护…”按钮和二次确认；它调用固定的
`run kali-arm64 --internet`，不会把 `--internet` 混入“启动全部”。本轮生成的验收 App 已覆盖最新源码，
但本记录只对其 CLI 路径做了实际联网验证，GUI 按钮的再次点击证据仍未单独记录。

## 3. 动态分辨率：SPICE 窗口跟随已验证，边界项仍待专项验收

已接入并通过定向测试：

- `run --display cocoa|spice`，默认仍是 Cocoa `zoom-to-fit`；
- SPICE 只允许图形 Kali，不能和 `--headless` 或靶机一起启动；
- 显式请求 SPICE 前探测 `spice` 显示后端、`spicevmc`、`virtserialport` 和本地 `remote-viewer`/`spicy`；
- SPICE 使用 0700 runtime 目录下的 UNIX socket，保留唯一 virtio-serial + spicevmc agent transport；
- 未满足能力时在创建实验网、overlay 和 QEMU 进程前失败，明确写出缺件，不静默回退 Cocoa。

本轮用 QEMU 11.1.0 源码构建了带 SPICE 的 arm64 运行时，并把 `spicy` 及其动态库闭包纳入最终 App：

- 验收 App：`/Users/pufei/Downloads/ctflab-app-build-spice-release-20260916/CTFLab.app`；
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

当前仍保留的边界：`--clipboard` 正向与未授权剪贴板负向、未授权客户端连接拒绝，以及 TCP 回退模式
尚未完成独立 E2E。默认 Cocoa 路径不改变，也不会因为 SPICE 缺件自动回退。旧分发目录
`/Users/pufei/Downloads/ctflab-dist-20260916/` 未修改；已另生成包含显示适配的新版目录
`/Users/pufei/Downloads/ctflab-dist-spice-release-20260916/`，其 `dist verify --json` 已通过 4/4，
Kali 基盘哈希为 `974a319f596170d171e75a5ee3e0f0fd4d28439ab10373c14f0fd9348b396315`。

## 4. 回归

- 最终完整回归：`python3 -m unittest discover -s tools/tests -q`，输出 `Ran 359 tests ... OK (skipped=5)`；即 354 项实际执行通过、5 项按历史 UTM 交付目录缺失规则跳过。负向口令用例输出的 `FAIL guest-password` 是预期失败样本，不是 unittest 失败；
- `python3 -m py_compile tools/ctflab.py tools/ctflab_app.py tools/ctflab_dist.py`：通过；
- Swift 核心测试：通过；
- 定向 CLI/GUI/安装器测试：通过；
- 动态分辨率的运行时 E2E：两档窗口尺寸实际跟随、冷启动恢复与重连后再次跟随均已验证；旧分发包保持不变，新版分发目录 `dist verify --json` 通过 4/4。
- 最终 App `app verify` 通过；测试结束后 `running_count=0`、全部 `internet_enabled=false`，临时测试客户端已退出。
