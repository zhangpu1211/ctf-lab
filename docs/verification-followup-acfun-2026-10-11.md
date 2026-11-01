# 四项续验与 Acfun 本地适配（2026-10-11）

> 历史验收快照：记录 2026-10-11 本轮产物与实测范围，不替代当前软件状态，也不能替代以后版本和环境的现场验证。

正式项目 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `42a3aa71d2665e20d9aec27f4afa19eed43a784d`。保留既有未提交改动；本轮不提交、不推送、不发布。用户本轮确认桌面空闲，允许独立测试窗口；Acfun 无预期服务说明，按实际镜像服务核验。

证据根 `/Users/pufei/Downloads/ctflab-followup-20261011`。所有测试使用独立状态、派生磁盘和回环交换机，没有接入物理局域网、停止用户实例或修改原始 OVA。

## 实现与复核范围

1. 无 OCR 的实际显示截图现在产生“待人工复核”，不会变成自动成功。报告记录截图 SHA256；保存需明确选择该报告的 review_attempt，校验报告、profile、基盘和当前探测截图。GUI 显示打开截图、二次确认保存入口。保存保留 profile 备份及 candidate/未验收标志。失败画面、被篡改截图、越界文件拒绝保存。
2. 每个独立状态的 TCP 交换机由父进程真实 bind/listen 占位，文件描述符传给子进程；端口被占用时选择另一个回环端口，运行时记录实际端口。长 QMP/SPICE 路径映射到私有 0700 的 `/tmp/ctflab-sockets-<uid>/<state-profile-hash>/`，不移动磁盘；拒绝不安全目录。
3. Acfun 新增内置白名单 profile：BIOS、IDE、pcnet、1 GiB、1 vCPU、实验网 `192.168.242.32`，无互联网及宿主端口转发。DHCP 探测只表示网络候选，实际 SSH 另以实验网协议检查。
4. 最终本地 App 在 `app-final/CTFLab.app`，版本仍 0.1.1，以日期和哈希区别；镜像库 `03-软件` 的已发布 0.1.1-preview 不替换。

## Acfun 真实证据与失败保留

原始输入 `/Users/pufei/Downloads/CTFLab-Library/01-待处理/Acfun.ova`，SHA256 `1e15d8b848b7d9bf33eeb2ad2543f12c240da93117199efe5cdb0d235f787fec`。独立适配 profile `acfun-adapt`、实验 IP `.31`，长状态目录记录在 `acfun-state-path.txt`。

初次 4 GiB/2 vCPU 冷启动到 Alpine 6.12.83 的 Acfun 登录画面，DHCP 可用；第二块管理网卡的宿主 SSH/HTTP 转发超时。实验网实测 SSH 22 返回 `SSH-2.0-OpenSSH_10.0`；80、443、8080、8000、3000 关闭。保留失败探测，不把管理网卡推测当成成功。最终 profile 删除无效转发，入口为同实验网 Kali 的 SSH 22。

1 GiB/1 vCPU 配置冷启动恢复 DHCP/SSH 约 32.6 秒，实际 QMP 截图有登录提示。两轮 ACPI 正常关机（约 7.5、11.1 秒）后使用同一 overlay 再冷启动，SSH 约 30.7、30.8 秒恢复。`acfun-restart-evidence.json`、`acfun-lower-login.png`、`acfun-restart-1.png`、`acfun-restart-2.png` 可复核。是正常关机再启动，未使用来宾认证后的 reboot 命令。

短时闲置采样见 `acfun-resources.json`：降低分配的 vCPU/内存已可运行。原配置 headless、新配置 Cocoa，显示方式不同，因此 RSS/CPU 样本不能证明纯资源配置导致的性能提升；未做长时负载或挑战解题。未认证登录、未证明任意工作负载稳定性。

新分发目录 `/Users/pufei/Downloads/CTFLab-Library/02-已处理/Acfun-20261011`；压缩基盘 `acfun-base.qcow2` SHA256 `df612f71f3722599ba69d6089989a9df466beb23ffbd2a9f1d4e02bc669d6685`，247332864 字节，清单记录 `qemu-img-compare-equal`。原输入、适配基盘 hash 不变，qemu-img check 通过（`acfun-integrity.json`、`acfun-base-check.log`）。未改写来宾系统，适配在运行配置中。

## 验证入口

- `/opt/miniconda3/bin/python3 -m unittest discover -s tools/tests -v`：初轮 649 项，639 通过、10 条件跳过，203.540 秒；`full-regression-initial.log`。最终轮 649 项中 638 通过、10 跳过、1 文档约束失败（新记录缺少“历史验收快照”标识）；已补标识，仅重跑受影响文档测试，完整失败日志保留。
- 运行时隔离 4 项通过，3.402 秒；包含真实双交换机并存、外部监听保留及真实长 UNIX socket bind。
- 矩阵显式 E2E：`CTFLAB_BOOT_MATRIX_E2E=1 /opt/miniconda3/bin/python3 -W error::ResourceWarning -m unittest discover -s tools/tests -p test_ctflab_boot_matrix.py -v`，36 项通过，7.745 秒；包含子进程资源警告检查。初次 mock 参数断言失败已修正，保留 `matrix-tests-initial.log`。
- GUI 专项 25 项通过，80.822 秒；`gui-tests-initial.log`。真实桌面证据及最终 App 配套结果在收口时补录。
- `./tools/ctflab app verify <app-final/CTFLab.app>` 已通过：805 登记文件、内置 Python 3.12.15/PyYAML 6.0.3、许可证完整、ad-hoc。本轮无 Developer ID/公证/跨 Mac 验收。

## 恢复与交接

保留适配状态、GUI 状态、最终包导入状态、三节点 pairing 状态及全部派生磁盘。结束现场重新核验进程绑定，不凭本文旧 PID 操作。恢复入口：先读 AGENTS.md、current-status 和本文，检查 Git 及对应 runtime.json，再决定新任务；不自动删除测试资产或扩大网络范围。


## 最终包与桌面收口结果

- 最终 App 树 SHA256（路径+文件 SHA256 列表算法，详见 app-final-artifact.json）：`3dfb4d25b4b40f4853dcae0e52266c827c41c4626c5dc3da2db6eec793fc52dc`。ZIP `CTFLab-0.1.1-followup-acfun-20261011-local.zip` SHA256：`e5721c9e1e7e794e591c7f5eba730fbc7870315c60a8d3dd7c9b862e2cb42b86`。包内 ctflab.py/ctflab_network.py 与最后源码一致；严格 deep codesign 和 ZIP 完整性校验通过。
- 最终原生 App 的 `gui-final-state` 实测原 Downloads OVA 只读识别、导入、无 OCR 矩阵。首个 BIOS/IDE 尝试显示 Acfun 登录提示，报告 `selected=null`、`succeeded=false`、`review_attempt=1`。中间 App 的“打开启动截图”实际在预览打开同镜像登录 PNG；最终 App 截图另逐张查看。
- 最终 App 二次确认先点取消：原 profile 字节保持一致；再确认保存：备份与保存前文件字节一致，GUI CLI 输出明确“状态仍为 candidate”，boot_verified/service_verified=false，review_mode=screenshot-only。返回主窗口显示已停止。证据 gui-final-evidence.json、保存前 YAML、profile-backups、矩阵 JSON/PNG；未把人工选择写成自动服务成功。
- 最终包实际配套：Smoke 约 33.5 秒 SSH、Basic 约 122.6 秒 HTTP 200、Kali 约 21.4 秒 SSH，三者 verdict=service_ready；原基盘/固件哈希对照分发清单保持一致。pairing-evidence.json 与 packaged-probe-*.log。范围仅冷启动显示/协议，不是重跑三个镜像的认证登录和完整重启。
- 最终包 Acfun 分发清单校验并新导入，通过真实长状态路径、私有短 QMP 路径截图、实验 IP .32 登录画面与 SSH-2.0-OpenSSH_10.0。实际端口23402，与当时 GUI/配套测试的23400/23401分离。final-acfun-evidence.json、final-acfun-login.png。驱动初次误用旧 runtime 文件位置，触发 FileNotFoundError；过早 graceful stop 超时保留进程，修正驱动读取 runtime/acfun/run.json 后复核已启动实例，SSH成功，再正常关机成功。3.175 秒是已启动实例的复核耗时，不能当成冷启动耗时。初次失败日志保留。
- 最终完整回归 649 项中 638 通过、10 条件跳过、1 文档快照标识失败；仅修正文档标识后受影响 7 项全部通过（docs-final-tests.log）。没有将这次完整日志写成全绿，也没有无意义重跑全部来宾测试。代码语法与 git diff --check 通过。
- 收口现场 final-process-check.json：本轮独立 QEMU、交换机与测试 App 已退出；原 OVA、三节点基盘/固件保持完整。保留所有运行 overlay、长状态目录、报告和备份；未触碰用户实例。分支与 HEAD 不变，未提交/推送/发布。
