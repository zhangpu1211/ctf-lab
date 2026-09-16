# CTFLab 学生使用教程：从分发目录到第一次启动

本教程适用于 Apple Silicon Mac（M 系列），目标是让学生使用老师提供的
`CTFLab.app` 和课程分发目录，在本机导入 Kali、Smoke、Basic Pentesting 2，
并启动隔离实验网。

## 1. 先确认拿到的文件

老师应提供两项内容：

1. `CTFLab.app`：运行器，内置受控 QEMU 和 Python 运行时，不需要另装 Python、pip、Homebrew 或 QEMU；
2. 一个分发目录：包含三个压缩基盘、Kali 的 UEFI NVRAM 模板和校验清单。

当前开发机已生成的实际位置是：

```text
/Users/pufei/Downloads/ctflab-app-build-spice-clipboard-release2-20260916/CTFLab.app
/Users/pufei/Downloads/ctflab-dist-spice-release-20260916/
```

当前分发目录中的文件为：

```text
DISTRIBUTION.json
README.md
SHA256SUMS
kali-arm64-base.qcow2
kali-arm64-uefi-vars.fd
smoke-base.qcow2
basic-pentesting-2-base.qcow2
```

这两个绝对路径是本机产物位置，不是学生机器上的固定路径。复制或下载后，后续命令只需要把
`APP_DIR` 和 `DIST_DIR` 改成实际位置。分发目录约 9.2GB，`.app` 约 264MB；不要把这些
虚拟磁盘提交到 Git 仓库。当前新版 App 约 302MB；旧的无 SPICE 产物和旧分发目录已清理，课堂使用
应以这里列出的新版路径为准。

## 2. 图形界面流程（推荐：双击打开）

导入和启动现在不需要终端。双击 `CTFLab.app`（首次打开按 §3 手动放行一次）后：

1. **选择分发目录**：点“选择…”，选中包含 `DISTRIBUTION.json`、`SHA256SUMS` 与三个基盘的目录；
   App 会自动识别清单里登记的文件；对话框里可以直接用 `⌘⇧G` 粘贴路径。
2. **校验分发目录**：点“校验分发目录”。表格会逐文件显示大小、状态与失败原因；
   **任何一个文件哈希不一致时，“导入实验环境”和“启动全部”保持禁用**——先重新下载，不要绕过。
3. **导入实验环境**：点一次，App 会依次对 `kali-arm64`、`smoke`、`basic-pentesting-2` 执行
   与命令行完全相同的 `--manifest` 导入（Kali 的 UEFI NVRAM 会按清单自动配对）。
   进度、成功/失败与 CLI 原文都显示在窗口里；导入失败会停在该节点并给出可复制的错误信息。
4. **启动全部**：三个节点一起启动（Kali 图形窗口 + 两台靶机）。
5. **检查状态**：显示每个节点是否已导入、是否运行、健康检查结果与日志路径。

6. **Kali 联网维护**（仅在老师明确授权时）：确认所有节点都已停止后，点击“Kali 联网维护…”，
   再确认弹窗。它只启动 Kali 的临时 user-net 出口，不启动 Smoke/Basic；维护结束必须点击“停止全部”，
   然后用默认“启动全部”恢复隔离实验网。
7. **Kali 动态分辨率**：点击“Kali 动态分辨率…”可请求 SPICE 图形会话。只有 `app verify` 报告包含
   SPICE-capable QEMU 与本地客户端的构建才会启动；缺件会在创建虚拟机前明确报错，不会把窗口缩放冒充动态分辨率。

其他按钮：**停止全部**（同时停止三个节点并清理实验网）、**重置…**（逐节点删除运行 overlay；
会先弹出确认框，明确提示 overlay 中的实验改动会丢失，基础镜像不受影响）。

重新打开 App 时会自动读取状态目录，已导入/运行中的节点会恢复显示；重复导入同一份分发目录
是幂等的，不会覆盖已验证的基盘。窗口底部始终显示当前执行的 CLI 命令与输出，排障时可直接复制。

## 3. 命令行流程（开发者 / 排障）

需要脚本化或排查问题时，使用 App 内置的 CLI（与图形界面是同一套逻辑）：

将 `.app` 和分发目录放在本机可读写的位置后，在终端执行：

```zsh
APP_DIR="/path/to/CTFLab.app"
DIST_DIR="/path/to/ctflab-dist-20260916"
CLI="$APP_DIR/Contents/Resources/bin/CTFLab"
```

例如，直接使用当前开发机产物：

```zsh
APP_DIR="/Users/pufei/Downloads/ctflab-app-build-spice-clipboard-release2-20260916/CTFLab.app"
DIST_DIR="/Users/pufei/Downloads/ctflab-dist-spice-release-20260916"
CLI="$APP_DIR/Contents/Resources/bin/CTFLab"
```

## 4. 首次打开 App

首次双击 `CTFLab.app` 时，macOS 可能提示无法验证开发者。当前构建为本地 ad-hoc 签名，尚未
进行 Developer ID 签名和公证：

1. 尝试打开一次 App；
2. 打开“系统设置 → 隐私与安全性”；
3. 在安全提示旁选择“仍要打开”，然后再次启动 App。

也可以直接使用上面设置的 `CLI` 路径运行命令。不要从网上下载其他 QEMU 或替换 App 内的
运行时文件。

## 5. 校验 App 和分发目录

先校验 App 本身：

```zsh
"$CLI" app verify "$APP_DIR"
```

再校验分发目录。第一条命令检查清单中的文件哈希，第二条由 CTFLab 复核文件大小和 SHA-256：

```zsh
(
  cd "$DIST_DIR"
  shasum -a 256 -c SHA256SUMS
)
"$CLI" dist verify --dir "$DIST_DIR"
```

两次校验都必须通过。若出现 SHA-256 不一致，删除不完整的下载并重新获取；不要使用参数绕过校验，
也不要继续导入损坏或被替换的文件。

## 6. 导入三个实验节点

清单会按 profile 核对每个基盘的 SHA-256。导入 Kali 时，还会从同一清单自动找到并登记配套的
UEFI NVRAM 模板；不要把 Kali 基盘和其他 profile 的文件混用。

```zsh
"$CLI" import kali-arm64 "$DIST_DIR/kali-arm64-base.qcow2" \
  --manifest "$DIST_DIR/DISTRIBUTION.json"

"$CLI" import smoke "$DIST_DIR/smoke-base.qcow2" \
  --manifest "$DIST_DIR/DISTRIBUTION.json"

"$CLI" import basic-pentesting-2 "$DIST_DIR/basic-pentesting-2-base.qcow2" \
  --manifest "$DIST_DIR/DISTRIBUTION.json"
```

导入成功后，基盘和运行状态保存在：

```text
~/Library/Application Support/CTFLab/
```

源分发目录保持不变，运行时写入独立 overlay。导入记录中的 `image.json.source_verification` 会
保存清单校验的证据。重复导入同一文件是幂等操作，不会覆盖已验证的基盘。

## 7. 启动并检查实验网

首次使用建议同时启动 Kali 和两台靶机：

```zsh
"$CLI" run kali-arm64 smoke basic-pentesting-2
"$CLI" status
"$CLI" health kali-arm64
"$CLI" health smoke
"$CLI" health basic-pentesting-2
```

默认网络只绑定本机回环地址，不把脆弱靶机接入物理局域网，也不提供公网出口。实验网地址为：

| 节点 | 实验网地址 | Mac 端口映射 |
|---|---|---|
| Kali ARM64 | `192.168.242.10` | SSH `127.0.0.1:12210` |
| Smoke | `192.168.242.20` | SSH `127.0.0.1:12220` |
| Basic Pentesting 2 | `192.168.242.21` | HTTP `127.0.0.1:18080`；SSH `127.0.0.1:12221` |

Kali 会打开 QEMU 图形窗口；两台 x86 靶机也可能打开窗口，但主要用于提供网络服务。Kali 登录
使用课程单独提供的账号口令，不要把口令写入 GitHub、清单或公开课程资料。需要后台运行时，
在启动时加 `--headless`：

```zsh
"$CLI" run kali-arm64 smoke basic-pentesting-2 --headless
```

## 8. 课堂中的常用操作

需要在 Kali 图形桌面中复制文本时，停止后用 `--clipboard` 重新启动：

```zsh
"$CLI" stop --all
"$CLI" run kali-arm64 --clipboard
```

需要抓取隔离实验网流量时，启动时加 `--pcap`。PCAP 可能包含实验口令和利用流量，不要上传或
公开分享：

```zsh
"$CLI" stop --all
"$CLI" run kali-arm64 smoke basic-pentesting-2 --pcap
```

结束实验时，先保存来宾内的工作，再停止节点：

```zsh
"$CLI" stop --all --graceful
```

如果图形桌面弹出自己的关机确认框，需要在 Kali 窗口中确认；否则 `--graceful` 超时后会保留
实例，不会强制断电。确认不需要保留本次实验改动后，可恢复到干净状态：

```zsh
"$CLI" stop --all
"$CLI" reset kali-arm64
"$CLI" reset smoke
"$CLI" reset basic-pentesting-2
```

`reset` 只删除运行 overlay，不删除已导入基盘，也不修改原始分发目录；但本次 overlay 中的
实验改动会丢失。

## 9. 常见问题

### 导入时报 SHA-256 不一致

说明文件与清单登记值不同，常见原因是下载未完成、分卷重组错误或文件被替换。重新下载后，
在分发目录中重新执行：

```zsh
(
  cd "$DIST_DIR"
  shasum -a 256 -c SHA256SUMS
)
```

不要用 `--expect-sha256` 填入“实际值”来掩盖错误，也不要删除 `--manifest`。

### 提示找不到 Python、PyYAML、QEMU 或 qemu-img

确认使用的是 `.app` 内的 CLI：

```zsh
echo "$CLI"
"$CLI" doctor
```

若使用 `./tools/ctflab`，那是源码开发路径，需要本机另有 Python、PyYAML 和 Homebrew QEMU；
学生使用分发版时不应混用两条路径。

### `health` 尚未通过

先等待靶机冷启动完成，再重复执行对应的 `health`。Basic Pentesting 2 原镜像有较长的启动等待，
不能把短时间内的 TCP 监听或 QEMU 窗口出现当作服务已就绪。最终应以 HTTP/SSH 等协议级检查通过
为准：

```zsh
"$CLI" health basic-pentesting-2
```

### 想让靶机访问公网

课堂默认不允许这样做。`--internet` 仅用于单独启动 Kali 的软件维护，不能与 Smoke 或 Basic
Pentesting 2 同时启动；未经授权不要扩大网络边界。

图形界面的“Kali 联网维护…”与命令行下面的 `--internet` 是同一能力。联网完成后必须先停止 Kali，
再按默认隔离模式启动实验节点；不要把 `--internet` 用在 Smoke、Basic Pentesting 2 或多节点命令上。

### 想让 Kali 窗口跟随来宾分辨率

使用带 SPICE 的新版 App，点击“Kali 动态分辨率…”，登录 Kali 桌面后拖动窗口即可。
Retina 屏的窗口逻辑尺寸与来宾像素尺寸可能为 1:2，例如 1000×700 对应 2000×1400。
当前机器上的 Kali 已安装显示适配；旧分发目录内的基盘尚未更新，重新导入或重置旧基盘后需由老师补装。
老师在 Kali 内运行新版 `tools/guest_fixes/kali-arm64/configure.sh --display-only`（需 sudo）后重新登录；
此选项仅安装显示适配，不重配网络。新版无人值守安装会自动包含该适配。

命令行显式请求 SPICE：

```zsh
"$CLI" run kali-arm64 --display spice
```

如需在 SPICE 图形会话中显式开启文本剪贴板，追加 `--clipboard`；不追加时客户端和来宾通道均保持关闭：

```zsh
"$CLI" stop --all
"$CLI" run kali-arm64 --display spice --clipboard
```

该模式要求 SPICE-capable QEMU、`spicevmc`/`virtserialport` 和本地 SPICE 客户端；缺任一项会在启动前
拒绝。默认 `"$CLI" run kali-arm64` 仍使用 Cocoa 缩放，不是动态分辨率。

## 10. 给老师/助教的交付核对

发布给学生前，至少确认：

- `CTFLab.app` 的 `app verify` 通过；
- 分发目录的 `shasum -a 256 -c SHA256SUMS` 和 `dist verify` 都通过；
- `.app`、`DISTRIBUTION.json`、`SHA256SUMS` 和三个基盘来自同一发布批次；
- 第三方靶机镜像的再分发条款已确认；不能确认时，改为让学生从原始来源自行下载，并提供
  `--expect-sha256` 哈希；
- 不把虚拟磁盘、PCAP、日志、账号口令、课程题库或成绩数据上传到 GitHub。

分发链的实现说明与真实验证记录见[基盘分发指南](ctflab-distribution-guide.md)和
[分发链验证记录](verification-distribution-2026-09-16.md)。
