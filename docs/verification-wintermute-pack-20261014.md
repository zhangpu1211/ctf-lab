# Wintermute 场景内容包构建、安装与实机验证（2026-10-14）

> 历史验收快照；不替代当前软件状态。以后继续须现场核对路径、哈希、日志与实际进程身份。

> 本轮验证记录：schema 3 真实场景包的构建、目标侧安装与完整 VM 实测（prepare→start→服务/隔离→stop→release）全部通过；测试无误后按用户授权执行提交/推送/打包/发布。

## 授权与边界

用户当次消息授权"启动 VM 后测试无误就发包、提交、推送、发布、打包"。VM 实测首轮被宿主代理 fake-IP 路由（128.0/1→utun4）拦截，用户关闭代理后完成实测；全部门槛通过后按授权执行发布链。未触碰用户实例、验收状态根与补丁基盘副本原件（补丁副本只读取复制）。

## 已验证

- **资产核对**（只读）：v3 清单（`ctflab-wintermute-acceptance-20261014/v3/manifest.json`）三资产哈希与实际文件逐一相符——kali=库内 `kali-arm64-base.qcow2`（974a319f…）、straylight/neuromancer=验收根 v3 的 enspatched 副本（4d8fdb4d…/915ab98b…，与 `base-ens-patch.json` 的 after_sha256 一致）。
- **真实包构建**：`dist make-scenario-pack` 生成 `CTFLab-Library/02-已处理/Wintermute-可分发-20261014`（pack-id `wintermute-lab` v1.0.0）：wintermute.json（3.64 KB）+ 三基盘（7.54/2.68/2.84 GB）+ kali-uefi-vars.fd（64 MB），共约 13.1 GB；制作侧断言随包基盘哈希与清单一致通过；README 含接收者步骤。
- **目标侧安装**：全新状态目录 `ctflab-wintermute-pack-20261014/app-state` 执行 `dist install`：整体哈希校验→复制到 `content-packs/wintermute-lab/scenario/`（只读）→schema 3 安装记录→输出可直接粘贴的 `scenario prepare` 命令（仅固件 code 为占位符）。缺失资产为空。
- **发布渠道预检**（只读）：origin=`github.com/zhangpu1211/ctf-lab`，gh 已登录；现有发布 v0.1.0→v0.1.1-preview.20261010（Latest）/20261012（Pre-release）；工作区 `CTFLAB_VERSION=0.1.2`；App 运行时（0.1.2-local，QEMU 11.1.0）与 edk2-aarch64-code.fd 双源可用。

## VM 实测（用户关闭代理后执行，全部通过）

状态根 `app-state/scenario-state`，实例 `3b5a03a1-46ab-4034-9438-2f8912519a8a` gen1，QEMU=App 运行时 11.1.0（aarch64 headless 已知偏差，x86_64 SPICE）。

| 门槛 | 结果 | 证据 |
|---|---|---|
| prepare（安装副本作资产） | ✅ 预约 gen1 token 190bc7d2…，端口 55165/55166 | `prepare.log` |
| start 三节点 | ✅ nodes-ready（进程+QMP 核验）；resume 重绑端口 55180/55181 | `start.log`、`status-running.json` |
| 来宾地址（四卡） | ✅ DHCP 全部按清单预约：outer .10/.20、inner .20/.30（`networks/*/network.json` leases 与 learned_macs 一致，服务日志含 DHCP 应答） | 状态根 networks/ |
| 显示/登录 | ✅ QMP 截图：`straylight login:`（Debian 9）、Ubuntu 16.04.4 neuromancer tty1；Kali 为 GUI（headless 偏差，SSH 自证） | `screens/*.png` |
| 目标服务 | ✅ kali :22 `SSH-2.0-OpenSSH_10.3p1 Debian-4`；straylight :80 `HTTP/1.1 200 OK`；neuromancer :8080 `HTTP/1.1 200`（与 v3 验收指纹一致） | `probe3-*.json` |
| 隔离负测 | ✅ outer 探针对 inner 目标 ARP 零响应 | `probe3-negative.json` |
| stop / release | ✅ 三节点+双网正常停止一次通过；预约释放（token 229a78c6…），进程归零 | `stop.log`、`release.log`、`status-final.json` |

探针说明：首轮探测用脚本默认源 IP（192.168.242.250，网段外）对 kali/neuromancer ARP 无应答；改用**网段内源 IP**（.243.250/.244.250，验收轮同款参数化路径）后全部通过——属来宾对网段外源的过滤行为，非运行器或包缺陷，`probe-*.json`/`probe2-*.json` 留作对照。

## 发布链（按授权执行）

- 发布门槛完整回归：`python3 -m unittest discover -s tools/tests` —— 805 项通过、跳过 10（见状态文档第 46 节当日重跑记录）。
- 提交：全部未提交改动（含第 42–44 节实现的 release 子命令、schema 3 场景内容包与全部文档）；推送分支 `codex/release-0.1.1-preview-20261010` 至 origin。
- 打包：`app build --version 0.1.2` + `app verify` + ZIP + SHA256。
- 发布：tag `v0.1.2-preview.20261014`（Pre-release），GitHub Release 附 ZIP 与哈希；内容包仅入镜像库（第三方镜像公开再分发许可未核验，不上传公开渠道）。

## 证据位置

`/Users/pufei/Downloads/ctflab-wintermute-pack-20261014/`：`install.json`、`prepare.log`、`start.log`、`status-running.json`、`probe*-*.json`（三轮探针：默认源 IP 对照、复测、网段内源 IP 通过）、`screens/*.png`、`stop.log`、`release.log`、`status-final.json`、`app-state/`（安装副本与场景状态根，预约已释放）。内容包本体在库 `02-已处理/Wintermute-可分发-20261014`。

## 未验证与限制

- 跨 Mac（第二台 Mac 的安装/启动链路）、GUI 场景面板、内容包公开再分发许可等级未做；库内包仅限自用分发。
- Kali 显示为 headless+QMP 截图偏差（本机 aarch64 运行时无 SPICE，既有事实）；SSH 服务自证网络栈。
- 人工跳转解题未做（原题利用链属人工任务）。
