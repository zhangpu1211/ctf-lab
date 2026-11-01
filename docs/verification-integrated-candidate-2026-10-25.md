# 跨阶段集成候选验证（2026-10-24—25）

> 历史验收快照：仅记录本轮源码、日期和环境，不替代当前软件状态；Windows Smoke基础流程的用户实测结论保留在状态第82节末尾，本轮不冒称重跑。

正式目录 `/Users/pufei/Downloads/ctf-lab`，分支 `codex/release-0.1.1-preview-20261010`，HEAD `0994f620516c49d84badc3a606c1cd5ae4b483d0`。保留原有修改，新增集成源码没有提交、推送或发布。实现及集中入口见[集成说明](ctflab-integrated-candidate-2026-10-25.md)。证据根 `output/roadmap-integration-20261024`，包含跨日结果。

## 已运行的验证

| 验证 | 入口/结果 | 证据 |
|---|---|---|
| 最终完整本地回归 | `python3 -B -m unittest discover -s tools/tests -v`；1086项，1065通过、21条件跳过，224.813秒 | `full-regression-final.log` |
| 真实无来宾QEMU参数/TLS | `CTFLAB_RECOVERY_QEMU=/opt/homebrew/bin/qemu-system-x86_64 python3 -B -m unittest discover -s tools/tests -p test_ctflab_qemu_driver.py -v`；14项通过，0.998秒 | `qemu-driver-tests.log` |
| 监督器故障单元与原生待验 | 10项，9通过、1仅Windows原生用例跳过 | `supervisor-fault-tests.log` |
| 集中比较 | 8项通过；故障身份/同盘继续/新代次基线及旧进度 | `acceptance-tests-final.log` |
| 内容缓存 | 12项通过；包括实例创建自动登记受保护引用和拒绝过期回收预览 | `content-cache-tests-final.log` |
| 版本存储 | 6项通过；签名、复制失败、篡改、手动回退、路径与迁移拒绝 | `release-store-tests.log` |
| 安装暂存 | 5项通过；使用合成文件，不是Windows运行时 | `desktop-package-tests.log` |
| Linux基础 | 5项，3通过、2普通用户Linux原生用例跳过 | `linux-tests.log` |
| 回环交换机捕获 | 9项通过；PCAP配额、完整记录边界、旧捕获保留 | `network-tests-final.log` |
| React状态模型 | `npm test`；5项通过 | `desktop-model-tests-final.log` |
| React生产构建 | `npm run build` 通过；无外部字体/CDN，锁文件入白名单 | `desktop-frontend-build-final.log` |
| Tauri源码检查 | `cargo +1.90.0 check --manifest-path desktop/src-tauri/Cargo.toml` 通过 | `desktop-cargo-check-final.log` |
| Mac原生桌面链接 | `cargo +1.90.0 build --locked --manifest-path desktop/src-tauri/Cargo.toml` 通过 | `desktop-native-build.log` |
| 隔离解压源码包 | 196项，188通过、8条件跳过，6.804秒；CRC/86文件摘要/5个CLI隔离入口通过 | `isolated-source-tests.log`、`isolated-source-evidence.json` |

完整回归的环境门槛/人工/Windows/Linux/QEMU等条件跳过均保留，不等于对应功能验收通过。真实QEMU专项仅使用测试自己创建的空白磁盘、暂停CPU及TCG，不启动合法课程来宾，不证明WHPX/KVM或真实网络应通禁通。全部执行会话正常结束，专用预览服务也已关闭。

桌面浏览器检查使用注入的双节点响应夹具；检查到节点2个、运行中禁止再次启动/重置、可见停止与恢复、1280宽度无横向溢出，视觉检查通过。没有由浏览器连接真实QEMU或直接证明Tauri桥接/Windows桌面行为；Mac只做原生编译链接，没有启动管理App接管实例。

## 失败与修复保留

- 首轮全量1083项：1062通过、20跳过、1失败。唯一失败为旧 `verification-production-driver-2026-10-24.md` 缺少项目要求的历史快照声明；添加声明而不改历史结果。日志 `full-regression.log` 保留。之后的最终1086项已覆盖最终实现和新增测试。
- PCAP首轮3个错误：过严的父路径链接拒绝把macOS `/var` 系统别名也拒绝。改为先固定明确选择的父目录、拒绝最终文件链接、独占新建及拒绝旧元数据，最终9项通过。首轮日志 `network-tests.log` 保留。
- 本机默认Rust 1.88低于所锁依赖要求；独立安装Rust 1.90.0，不更改全局默认版本。随后原生检查发现缺少应用图标，补齐本地生成的PNG/ICO，最终check和链接通过。初始日志 `desktop-cargo-check.log`、`desktop-cargo-check-rust190.log`、`rust-toolchain.log` 保留。
- 源码对应关系检查最初把包内生成的README与仓库主README误作同一输入；已改为与集成说明对应，86文件没有源码漂移。错误报告保留为 `final-evidence-readme-mapping-failure.json`，最终映射及摘要在 `final-evidence.json`。

## 未验证与未完成

本轮没有Windows新实机结果，也没有Linux/SSH或合法课程/Windows/AD资产和签名证书，用户已明确暂无。没有生成Windows最终安装包、完成干净机离线安装/更新/卸载、签名、课堂或跨设备验收。新的监督器故障路径、通用双节点来宾网络/服务、Linux KVM和课程仍待实际执行。

全43项仍有开发工作：路由/DNS/时间/规则、Docker整合、校内镜像、SSH/租约/多人/外部接入、实际课程及隔离分析器、图形连线编辑、安装迁移与自动更新、证书续签、后台日志配额等。不得将这些写成“开发已全部完成，仅等用户测试”。G0/G1仍未通过，总验收未启动。

本轮只生成新的源码候选和Mac调试可执行文件，没有重打旧Mac App、覆盖旧Windows包、操作用户VM、删除原始镜像或用户现场。完整源文件摘要、包检查和范围记录见 `final-evidence.json`。远端Windows实例只沿用用户前轮“已退出”的反馈，未独立远程盘点；不能按旧记录PID操作。
