# 受管来宾、镜像与图形草稿验证（2026-10-25）

> 历史验收快照：本文件记录本轮源代码、日期与测试范围，不替代当前软件状态。Windows Smoke沿用状态第82节用户实测，本轮没有重做。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`；保留既有和新增未提交修改。实现与限制见[候选说明](ctflab-managed-guest-2026-10-25.md)，证据根 `output/managed-guest-20261025`。

## 本轮已运行

| 入口 | 结果与范围 | 日志 |
|---|---|---|
| `python3 -B -m unittest discover -s tools/tests -v` | 1125项，1104通过/21条件跳过，219.215秒；全量加载之后的3项重启一致性增量与隔离入口修复由下列最终专项覆盖 | `full-regression.log` |
| `python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_guest*.py' -v` | 最终32项通过，0.431秒；真实临时SQLite/消息账本，模拟来宾工具；包括网络规则/重启漂移拒绝、无副作用失败重试、部分结果不重放、容器信号/卷/代次及安装材料边界 | `guest-tests-restart-proof-final.log` |
| 显式 `CTFLAB_RECOVERY_QEMU=/opt/homebrew/bin/qemu-system-x86_64`，通用driver专项 | 18项通过，0.832秒；测试自己持有的空白磁盘、暂停CPU、TCG QEMU，核验新增virtio/TLS参数、派生UUID/profile绑定，不启动课程来宾 | `qemu-agent-fixture-final.log` |
| 内容镜像专项 | 6项通过，0.053秒；真实临时签名/缓存材料、纯学生索引/许可和路径拒绝、镜像传输源保持原信任 | `mirror-tests-final.log` |
| 桌面桥接专项 | 6项通过，0.069秒；契约替身及临时目录 | `bridge-tests-final.log` |
| `npm test` | 12项通过；图/清单往返、设计地址、删除依赖/断开草稿、重叠/原型字段拒绝及操作权限模型 | `desktop-model-final.log` |
| `npm run build` | React生产构建通过 | `desktop-build-final.log` |
| `cargo +1.90.0 build --locked --manifest-path desktop/src-tauri/Cargo.toml` | Mac原生调试链接通过；没有启动管理App接管实例 | `native-desktop-build.log` |
| 隔离解压源码r2 | 238项，230通过/8条件跳过，7.083秒；101文件摘要/CRC、70个Python语法及8个隔离CLI入口通过 | `isolated-source-tests-final.log`、`isolated-source-evidence-final.json` |
| 专用来宾安装材料r2 | 14文件摘要、Python语法及隔离agent `--help`通过；安装器仅在非Linux/root边界测试拒绝，本机未安装 | `dedicated-guest-bootstrap-r2/MANIFEST.json` |

完整回归结果另见状态第84节及 `full-regression.log`。全量测试开始后新增的重启一致性检查和隔离入口修复由最终32项专项及隔离r2覆盖，不把早先加载的测试冒称包含后续改动。

浏览器检查使用本轮自有回环预览服务和三节点合成后台；没有连接真实VM。实际检查3节点/2网段/4条SVG连线、client网卡拖到inner后清单同步、迟到旧校验不能导出/新校验可导出、middle配置按钮提交含代次/revision的guest契约。证据 `browser-assertions.json` 与 `graph-ui-fixture.png`；没有下载、上传或应用实际网络设置。预览服务已停止，1420端口复查无监听。

## 失败、补充与保留

- 首版隔离源码235项测试通过（8跳过），但 `python3 -I .../ctflab_guest_kit.py --help` 缺模块搜索路径而失败。修复固定脚本目录导入后，r2八个入口全部通过；旧r1包和失败 `source-validation.log`、`isolated-source-evidence.json` 保留，不覆盖成成功。
- 复核发现来宾重启后历史网络配置记录不能代表当前规则。追加只读接口/开关/nft摘要核验，规则丢失或变化时先于服务/容器副作用拒绝。忽略计数/内核句柄易变字段，规则行为变化仍触发不一致；同内容配置可保留，被修改配置不覆盖。最终专项包含新增3项用例。
- 较早镜像专项因直接导入测试类而重复发现缓存12项，改为模块别名后独立镜像6项；早期日志保留，最终不将重复项算作新增覆盖。

## 本地材料及未通过门槛

可复查源码：`output/managed-guest-20261025/CTFLab-Managed-Guest-Source-20261025-r2.zip`，SHA-256 `43cd800aa151b5943474673798badea769727899e856d55891a61f8488d42512`。生成README来自本轮候选说明，明确不含镜像/运行时/私钥/现场/安装器。专用来宾安装材料为同根 `dedicated-guest-bootstrap-r2`，不把生成源码等同安装成功。

没有Linux专用来宾中的nft/Docker/systemd/DNS/NTP执行结果、OCI离线装载、容器跨网、真实服务/课程网络矩阵，部分副作用的完整对账修复仍未实现。没有Windows新增实机、最终安装/迁移/更新/干净机、Authenticode、SSH/角色/租约/外部VM或课堂结果。全部43项尚未完成，不能把未实现项一律写成待用户实测。

G0/G1与graceful_stop_verified保持未通过/false，总验收尚未启动。不操作用户VM、不改宿主网络、不删资产/旧证据、不提交/推送/公开发布或覆盖已发布Mac App。远端实例状态只沿用用户历史回传，不能按旧PID操作。
