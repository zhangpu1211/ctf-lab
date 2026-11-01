# Kioptrix、Stapler 本地分发验收（2026-10-14）

> 历史验收快照；不替代当前软件状态。来源目录、进程与产物以后均须现场重核。

正式项目 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `941db31`；保留原有未提交改动。本轮未再修改运行器实现，未提交、推送或外部发布。

## 交付

镜像库 `02-已处理/Kioptrix-可分发-20261014`、`Stapler-可分发-20261014` 为 schema 2 内容包，版本 1.2.0，要求运行器 >=0.1.2。配套软件在 `03-软件/CTFLab-0.1.2-local-20261014/CTFLab.app` 与同目录 ZIP。旧版发布入口、旧候选包和原始资产均保留。

基盘和 YAML 与 10 月 13 日关机候选逐字节一致；修复已经落在此前派生盘，本轮主要补齐配套 App、重新验收与分发说明。Kioptrix 保留 hosts/DHCP 修复，使用 Ctrl+Alt+Del 经来宾 shutdown 重启流程配合 QEMU -no-reboot 退出；Stapler 保留 ens33→eth0 修复，ACPI 最长等待 120 秒。原 YAML 的历史 verification 声明不改写；本轮范围由本记录和新包说明补充，避免只为更新声明导致同名已登记配置冲突。初版元数据草稿留在本轮证据根，未交付。

## 本轮命令与结果

证据根 `/Users/pufei/Downloads/ctflab-distributable-20261014`；`accept.py` 为可重复验收脚本，`accept.log` 四个 cycle 均 passed。脚本使用**新构建 App 包内 CLI**与全新 `kioptrix-state`、`stapler-state`，两台各运行两轮 `dist install → run --headless --pcap → 隔离实验网协议检查 → QMP 截图 → stop --graceful → status`（第二轮复用本轮 overlay）。未打开或操控桌面窗口；未修改宿主网络或操作用户 VM。运行配置读取已有同字节候选配置；最终新版包另在 `*-final-v2-state` 并设置独立 `CTFLAB_PROFILE_DIR` 完成全新校验/安装。

| 节点 | 两轮服务 | 显示证据 | 正常停止耗时 |
|---|---|---|---|
| Kioptrix .57 | ARP；SSH-1.99-OpenSSH_2.9p2；HTTP 200 Red Hat Apache 默认页；139/443 TCP | 第一轮 kioptrix login；第二轮采集时为欢迎信息，未声称已到登录 | 16.63 / 15.80 秒 |
| Stapler .58 | ARP；FTP 220；SSH-2.0-OpenSSH_7.2p2 Ubuntu-4；HTTP 根路径 404 | 第一轮 red login；第二轮采集为空白，服务响应和正常停止仍通过，未声称该截图证明登录 | 94.72 / 16.42 秒 |

Kioptrix 服务启动分阶段，SSH 先于 HTTP/Samba；不要把 DHCP 或登录提示当成所有服务就绪。正常停止后再次冷启动并复验服务，不等同来宾连续运行的热重启验收。所有请求仅访问本轮状态的回环交换机与 .57/.58，不认证登录、不写入目标业务、不解题。

- `app build --version 0.1.2`：成功；内置 Python 3.12.15、PyYAML 6.0.3、QEMU 11.1.0。`app verify` 对构建 App 和交付副本通过；805 项登记文件，许可证文本完整，ad-hoc 签名，未公证。
- 屏幕、生命周期、内容包、打包专项：98 项通过（`tests.log`）。
- `python3 -m unittest discover -s tools/tests -q`：687 项，OK，跳过 10 项，退出 0（`full-tests.log`）。夹杂的预期失败场景输出不代表整体回归失败；跳过不能当作真实来宾验收。
- 最终内容包 `dist verify --json` 与全新 `dist install --json`：均成功，见 `*-final-v2-{verify,install}.json`。最终基盘哈希与实测候选完全相同，运行 YAML 逐字节相同；最终包安装状态未另启动。
- 两份原 VMDK 重算 SHA 与既有记录一致，见 `sources-check.json`。未重算其他原件，不宣称全库原件全部重验。
- 结束现场核对 `final-check.json`：本轮两实例均不运行，无 run.json，四个实际测试 PID 均不存在；所有测试状态、overlay、PCAP、截图保留。以后必须重新核验绑定。

## 交付限制

可作为本机验证的**运行兼容内容包**，不能宣称认证登录、完整解题、课堂业务、长时稳定性、跨 Mac 或人工 GUI 验收通过。Stapler 第二轮显示未取得登录，Kioptrix 第二轮截图未到登录，证据如实保留。App ZIP 是本地配套构建，不替代原已发布 0.1.1，不改变发布渠道，未公证。第三方原镜像公开再分发许可本轮未核验；没有上传或公开发布。

## 压缩包复核修正

首次 ZIP 解压后的 app verify 发现三个 encodings 字节码缓存哈希变化，原因是本轮验收脚本直接调用包内 Python 时未使用 -B。从原 Python 运行时归档读取对应文件，逐项确认归档字节的 SHA 与原 App 清单一致后恢复（不修改清单或签名来掩盖差异），重新校验 App 与重打 ZIP。验收脚本子进程已加 -B；以后执行脚本的解释器也须使用 -B，避免变更受保护 bundle。首次失败日志保留为诊断证据，最终以 restored-app-verify.log 与最终 ZIP 校验为准。

另有 115 个本轮运行时新生成的未登记 pyc，已移出 App 并保留到证据根 generated-cache-backup；补齐交付副本的 CTFLab.app.sha256。恢复后完整 app verify（含签名）通过。最终 ZIP 将 App、旁车校验与说明一同封装。

最终 ZIP 解压到证据根 zip-final-check 后 app verify 退出 0，805 项文件、签名及许可证通过（zip-final-verify.log）。库根清单最终 1801 项：首次完整库校验中非新软件项全部通过；新软件目录在修复期间发生的失败/移出缓存记录保留，最终对该目录 813 项重新生成并逐项校验全部通过（library-final-changed.log）。不把首次全库退出 1 写成通过；两阶段复核共同覆盖最终清单文件。git diff --check 通过。
