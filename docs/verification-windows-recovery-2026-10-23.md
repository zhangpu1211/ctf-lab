# Windows 可重连候选验证（2026-10-23）

历史验收快照；不替代当前软件状态。正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`、HEAD `0994f62`；工作区保留此前未提交改动。本记录只证明所述版本与范围，不把 macOS 协议证据转换成 Windows 验收。

## 本轮证据

证据根：`output/windows-recovery-20261023/`。

- `qmp-tls-probe-first.log`：本机 QEMU machine=none、TCG、暂停、无磁盘/来宾，两个独立 TLS QMP 客户端核验同一实例名称并读取 prelaunch；非 WHPX 启动证据。
- `vnc-probe-first.log`：同类无来宾 QEMU，两次独立认证显示连接各取得640×480 Raw帧，PPM长度921615；未查看 Tk 窗口，不代表来宾登录成功。
- `recovery-first.log`：`CTFLAB_RECOVERY_QEMU=/opt/homebrew/bin/qemu-system-x86_64 python3 -B -m unittest discover -s tools/tests -p test_ctflab_windows_recovery.py -v`，11项全部通过，0.260秒。真实本机端点验证无客户端证书被拒、错误实例名拒绝、控制与显示重连；合成观察器验证原生身份未知时不连接、不同实例拒绝、意图不重放、丢回包unknown、关机确认不等于退出、证书篡改拒绝、配置与尺寸边界。
- `isolated-r1.log`：源码 ZIP 解压后以 Python `-I -B` 运行包内测试，显式启用无来宾 QEMU 测试，47项通过，5.717秒；独立 CLI `--help` 返回0。ZIP CRC、MANIFEST每文件哈希已核验。依赖来自本机 Python 环境，不代表干净 Windows 安装验证。
- 本机 QEMU 输出 `-mon` 弃用警告与测试结束信号记录均保留。测试只终止/reap本轮创建的无来宾子进程，未操作用户既有 VM、磁盘或运行状态。

源码候选 `CTFLab-Windows-Recovery-candidate-r1.zip`，SHA-256 `c4b38ccc0965a5b111cec41ee072ac2cf38cfc0c4cc65b6884ccececf4772735`。包含源码/测试/说明/清单，不包含运行时、镜像、实例记录、证书或私钥。对应说明为 [候选使用及边界](ctflab-windows-recovery-2026-10-23.md)。

## 未验收

Windows固定QEMU的TLS能力、原生worker中断后的控制/显示重连、实际ACL跨账户拒绝、Tk键鼠/画面、真实来宾、网络、多节点、多代次、证书续签、日志配额及最终安装包均未通过本轮验收。新增入口仍为固定Smoke候选，尚未成为ScenarioCoordinator生产driver。G0/G1维持未通过。不重做或覆盖第79节旧control-r1真实正向回传。

完整回归结果另在当前状态收口登记；不得把专项通过视为完整回归完成。未提交、推送、发布或重新打包Mac App。

最终补记：完整回归1012项，996通过/16条件跳过，219.105秒，`full-regression-first.log`；无来宾QEMU用例在全量中默认跳过，在专项/独立包测试中显式通过。本机QEMU为11.1.0。7项文档与6个模块语法检查通过，差异空白检查通过；源码ZIP与当前源码逐文件一致。`final-evidence.json`、`SHA256SUMS.txt`记录收口证据。本轮测试进程均已结束，无待移交运行实例；没有停止既有用户VM。
