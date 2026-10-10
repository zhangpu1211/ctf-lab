# 2026-10-08 复核修正与新 App 验证

本轮修正复核发现的六类问题，不代表此前优化路线图全部完成。
原始镜像、用户运行中的 Kali 实例与旧 App 保持不动；未提交、推送或公开发布。

## 数据恢复与删除边界

- `reset --backup` 整目录一次移动，保留 overlay、内部快照配对 NVRAM 和显示偏好。
  移动失败保持原实例，避免分文件移动造成半备份。
- 恢复备份前检查 backing 基盘存在；恢复时保留当前实例为独立 `before-restore-*`
  备份；发布失败回滚当前实例。历史 run.json/QMP socket 不复用。
- 有整盘备份时拒绝删除该节点基盘。提供明确的 `snapshot delete-backup`，拒绝路径越界
  和符号链接；它不删除基础盘或当前实例，不具有恢复能力。
- 快照固件副本缺失时在修改磁盘前拒绝恢复；备份往返后恢复快照同时恢复正确 NVRAM。

## 导入与独立授权

- 待导入列表只过滤已导入的来源路径。未导入同名登记不再隐藏文件，生成 `smoke-2`
  等不覆盖现有登记的候选 ID；同批导入预留 ID，长名称仍满足长度限制。
- `--clipboard` 只允许文本共享；`--file-transfer` 单独允许 Mac→Kali 拖放。
  服务端、受控客户端和 GUI 独立控制，默认关闭；未知客户端和 Cocoa 文件传输明确拒绝。
- 桌面验收脚本关机异常类型修正为 CTFLabError。
- 两份先前被忽略的显示/输入验证文档纳入 Git 白名单。

## 验证与交付状态

小型真实 QCOW2 回归覆盖快照/备份往返、固件配对、删除引用保护、失败回滚和独立删除。
Swift 核心测试覆盖来源过滤、同名 ID 分配、长度边界及两个授权开关的命令拼接。
C 测试执行参数解析，Python 测试覆盖四种授权组合的 QEMU/客户端命令。

完整回归发现 **459 项，451 项通过，8 项跳过**，耗时 177.053 秒，退出码 0。
跳过项为五项历史 UTM 交付目录、TCP 来宾场景门控一项、桌面 E2E 门控两项。
日志中的 `FAIL guest-password` 是已有负向测试预期输出，不代表完整回归失败。
另外运行的快照/授权/C 参数/文档命令针对性回归 31 项通过；严格 C 编译通过；
`git diff --check` 无错误。

最终 App：`/Users/pufei/Downloads/ctflab-app-reviewed-20261008-final/CTFLab.app`。
本地 ad-hoc 签名，最低 macOS 26，未公证、未发布。797 个登记文件、70 个动态库、
50 个 QEMU 资源；QEMU 11.1.0、Python 3.12.15、PyYAML 6.0.3；许可证文本完整性 True。
App 树 SHA-256：`0218729c2b5971c7b9dd33ad3d8b50a6302d7a6ee26a12391e124a2509d67ebb`。
`app verify` 与 `codesign --verify --deep --strict` 通过；打包的 CLI/GuiApp/GuiCore
逐文件哈希与当前源码一致。没有使用不完整许可证文本的放行选项。

隔离真实启动两轮通过：仅借用只读 Kali 基盘和 RAW NVRAM 登记，使用独立临时状态、
派生 overlay/NVRAM、不同实验网及 SSH 端口；测试内存 2 GiB，避免竞争用户实例资源。
网络就绪分别 20.09 秒 / 19.98 秒（不是性能基准）；两轮 DHCP、SSH 横幅、
SPICE 显示连接和 **可见 lightdm 登录表单** 均通过。停止路径为运行器停止，非来宾
`poweroff`/ACPI 正常关机验收；客户端均优雅退出，独立状态无残留。
原始基盘与 RAW NVRAM SHA-256、App 树哈希前后不变；用户原实例 PID 56816/56817
仍存活。未重启 UTM、未改宿主剪贴板、未向用户桌面注入输入。

证据：`/Users/pufei/Downloads/ctflab-app-reviewed-20261008-final/evidence/final-check/isolated-app-check.json`，
配套 `login-1.ppm` / `login-2.ppm`、表单 PNG 与客户端日志。复现脚本保存在同级
`evidence/reproduce-check.py`（通过 CTFLAB_REVIEW_APP / CTFLAB_REVIEW_OUT 指定输入/输出）。
初次截图取在网络就绪时仅有黑屏游标；等待后实际已到登录界面，但全图 OCR 未识别
小字而导致首轮自动判定失败。该次证据保留在最终目录 `evidence/` 根层。
收尾增加等待，并对登录框区域核对“Enter your password”与“Cancel”两个标签，
模型也查看了完整登录截图；不修改运行器的通用画面分类、不把 unknown 升级为已验证。

## 保留边界

用户现有 Kali 正在运行，本轮不关闭、不重启、不向其注入输入。
独立测试以只读基盘和派生 NVRAM/overlay 验证；宿主剪贴板不改写。
不会把登录界面/DHCP/SSH 当成已登录桌面的鼠标精度、长拖拽、剪贴板或文件拖放验收。
Dock 恢复、多显示器、跨 Mac、macOS 26 实机、Developer ID/公证与 UTM 性能对比仍待验证。
