# CTFLab 使用教程：从镜像目录到启动

> 2026-10-13 整理。适用于 Apple Silicon Mac、macOS 26.0+。当前发布版为 0.1.1-preview.20261012，已含导入优化与内容包；未来工作区改进是否进入软件须另核对。完整状态与历史证据见[当前状态](ctflab-current-status.md)。

## 1. 收到什么、选哪个目录

接收者需要 App ZIP 和一个完整镜像分发目录。App 内置 Python、PyYAML、QEMU 与受控显示客户端，无需另装 Homebrew 或 pip。App 不内置 Kali/靶机磁盘，也不在公开说明中提供账号口令。

本机统一镜像库是 `/Users/pufei/Downloads/CTFLab-Library`：

- `01-待处理`：原始磁盘或 OVA；安装 ISO 单独保存，不能当已安装系统导入。
- `02-已处理`：顶层为 Kali、Smoke、Basic 三节点分发，含 DISTRIBUTION.json、SHA256SUMS、三个基盘及配套 NVRAM；独立子目录为 Acfun 和新增单节点包。
- `03-软件`：发布版 App ZIP、校验与发布说明。

其他电脑可以把库放在任意可读位置，不依赖上述绝对路径。发送三节点课程包时只需软件与完整“已处理”目录；不要漏掉清单或固件模板。当前 GUI 只扫描所选目录顶层，不递归扫描库根。

## 2. 推荐图形流程

1. 解压并打开 CTFLab.app。当前签名为 ad-hoc，未做 Developer ID 签名/公证；首次打开如被系统阻止，核实来源与校验后在“系统设置 → 隐私与安全性”按系统提示允许，不关闭系统安全机制。
2. 在软件中选择含分发清单的“已处理”目录。软件校验后导入缺失节点，不会因此立即启动所有节点；不要依赖旧教程的按钮名称或额外手动导入顺序。
3. 选中一个已导入节点，点击“启动所选节点”。其他已运行节点不应阻塞该节点；停止也只作用于所选节点。
4. 等待真实健康检查。窗口出现、端口监听或 DHCP 到手均不单独代表目标服务已就绪。
5. Kali 使用课程单独提供的凭据登录。默认 auto 在完整 SPICE 能力可用时使用真实自动分辨率；缺件时明确退化 Cocoa 固定显示，显式 SPICE 缺件则拒绝、不静默回退。
6. 运行中的 SPICE 节点可从面板“打开显示窗口”或“重连显示”恢复显示，不重置来宾；QEMU 已退出不能恢复其内存会话。
7. 保存工作后正常关闭来宾或停止所选节点。重置会丢弃 overlay 中改动，需保留时先做停机备份。

“本机已登记”仅表示本机状态目录已有基盘，不表示新选择的文件夹已导入。文件夹切换不应抹掉已导入节点。

## 3. 外部制作的镜像

软件可以读取外部提前制作的 QCOW2、VMDK、VDI、VHD/VHDX、RAW、OVA，不要求由 CTFLab 自身转换。

- 只有磁盘：仍需识别架构、固件、控制器与网卡，再生成候选配置、探测和验收。
- 完整分发：除磁盘与哈希，还须匹配课程 profile 和固件模板。当前 schema 1 的 DISTRIBUTION.json 不是任意新 profile 的自动安装器；未内置的自定义 profile 应由制作者打成**目录式内容包**（schema 2，含随包配置），见[镜像制作与分发](ctflab-distribution-guide.md)第 2b 节。
- 内容包在 GUI 中与普通分发目录同一个入口：选中目录即校验，界面会显示包内节点、资源需求、与内置/已有配置的冲突提示；导入按钮一次完成"装配置→导基盘→复制说明"，失败会整体回滚并给出具体文件或配置项；导入不自动启动。
- 包内标注的"验收声明"只是制作者的话；导入后节点不会显示为本机已验证，仍需本机启动与探测确认。
- x86 客体在 M 芯片上仍使用 TCG 模拟，转 QCOW2 不会变为 ARM；ARM64 采用 HVF。
- 未知镜像向导先只读识别。多磁盘需明确选择系统盘，依赖盘、快照链、加密与 RAID 不能靠猜测交付。
- 当前 20261012 发布 ZIP 已含导入进度、安全取消/重试及人工确认保存矩阵结果。矩阵结果即使保存也仍是候选，不自动变成已验收镜像。

原始文件不覆盖，运行写入独立 overlay。公开分发第三方靶盘前须逐项确认再分发许可。

## 4. CLI 排障

以下 APP_DIR 与 DIST_DIR 是示例，修改为接收者机器实际位置：

```zsh
APP_DIR="/path/to/CTFLab.app"
DIST_DIR="/path/to/CTFLab-Library/02-已处理"
CLI="$APP_DIR/Contents/Resources/bin/ctflab-cli"
"$CLI" doctor
"$CLI" app verify "$APP_DIR"
"$CLI" dist verify --dir "$DIST_DIR"
"$CLI" import kali-arm64 "$DIST_DIR/kali-arm64-base.qcow2" --manifest "$DIST_DIR/DISTRIBUTION.json"
"$CLI" import smoke "$DIST_DIR/smoke-base.qcow2" --manifest "$DIST_DIR/DISTRIBUTION.json"
"$CLI" import basic-pentesting-2 "$DIST_DIR/basic-pentesting-2-base.qcow2" --manifest "$DIST_DIR/DISTRIBUTION.json"
# 目录式内容包（自定义 profile 随包）一条命令完成校验+导入：
"$CLI" dist install --dir "/path/to/内容包目录"
"$CLI" run kali-arm64
"$CLI" status
"$CLI" health kali-arm64
```

清单校验失败应重新获取文件，不能把“实际哈希”改填为“期望哈希”。本机运行数据在 `~/Library/Application Support/CTFLab`；切换版本不要删除 image.json 或需要保留的 overlay。

## 5. 网络与共享

Kali 管理网默认 user-mode NAT 用于可信工具维护；脆弱靶机管理网 restrict 隔离。实验网经本机回环交换机互通，不是物理 LAN 或多主机复杂拓扑。默认实验地址：Kali 192.168.242.10、Smoke .20、Basic .21；Mac 经声明的回环端口映射访问。

新单节点包的地址为 .40–.56，具体入口见镜像库 `02-已处理/镜像使用与服务入口.md`，每包还有独立使用说明。启动同一 App 状态目录中的 Kali 和靶机，用 Kali 浏览器访问包内地址。这些新包没有宿主端口映射，Mac 浏览器不能直接访问实验网 IP；无需桥接物理 LAN 或给靶机开互联网。

Smoke-OVA 是 .56 的独立版本，访问端 Kali 的 `/etc/hosts` 需映射 `192.168.242.56 smoke.dsz`，然后访问 `http://smoke.dsz/`；既有 Smoke .20 不套用此说明。Watcher 的入口是 `http://192.168.242.55:5000/login`。NoPort .50 保留原盘防火墙规则缺件，只是兼容候选。初始服务响应不等于认证登录、全站功能或解题已验证。

文本剪贴板与文件拖放分别显式授权、默认关闭。剪贴板要求登录图形会话；文件拖放仅 Mac→Kali，不能宣称反向可用。开启共享时勿复制敏感内容。SPICE agent transport 存在不等于共享已开启。

## 6. 停止、重置与迁移

```zsh
"$CLI" stop kali-arm64 --graceful
"$CLI" reset smoke
```

graceful 可能需在来宾确认关机，超时保留实例而非强制断电。reset 只作用于停止的节点，基础镜像与原始下载不变，但实验改动会丢失。保存实验进度需正常停止后备份状态与配套 NVRAM；镜像库只含基线，不是运行进度备份。

不要删除仍被已登记来源或运行实例引用的旧目录。跨 Mac、外接显示器、真实 Mac 睡眠和长期负载未验证项仍按[发布门槛记录](verification-release-gates-2026-10-09.md)保留，不因文档整理升级。

## 2026-10-14 Kioptrix / Stapler 配套交付

新内容包为库内 `02-已处理/Kioptrix-可分发-20261014`、`Stapler-可分发-20261014`，要求配套 `03-软件/CTFLab-0.1.2-local-20261014` 的 App/ZIP。这是本地运行兼容交付，不替代既有 0.1.1 正式发布渠道。两机保留隔离实验网 .57/.58，无宿主转发；Kioptrix 旧系统服务启动较慢，Stapler 关机最长等待 120 秒。

发送完整单节点目录与配套 ZIP，选择具体包目录校验导入。同名旧关机候选已导入时，基盘与配置相同，无需为更新说明重复安装。首轮登录画面、两轮服务与正常停止已验证；第二轮截图有阶段/空白限制，完整解题、认证登录、人工 GUI、长期和跨 Mac 均未完成，见[本轮分发验收](verification-distributable-images-2026-10-14.md)。
