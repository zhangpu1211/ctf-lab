# 内容包独立复核（2026-10-12）

> 历史验收快照；不替代当前软件状态。本文件为用户独立复核记录，正文未改动，仅按项目约定补充本抬头。

本轮结论：候选实现暂未通过完整验收。保留 ZCode 原始验收快照，以下是独立新增证据，不否定其 Smoke BIOS 正常路径结果。

## 可复现问题

证据根：`/Users/pufei/Downloads/ctflab-contentpack-independent-review-20261012`。入口 `reproduce.py`，输出 `reproduction.log` 和 `reproduction-results.json`。使用新建 16 MiB QCOW2、独立状态与实际 qemu-img 导入，没有启动虚拟机或访问外网。

1. **P1：多节点部分成功后回滚删除成功节点配置。** 同一个新包内第一节点真实导入成功，第二节点损坏 OVA 导入失败；第一节点基盘与 image.json 保留，但 YAML 被删除，load_profile 报未知配置。位置：tools/ctflab.py 的 install_content_pack，失败分支统一删除 created_files。现有同名测试实际上先安装另一个包，没有覆盖同一次多节点导入。
2. **P1：失败重装删除已有包记录，并提前改变既有节点元数据。** 初次安装成功后，同包 ID、同配置与基盘、不同说明文件的重装失败；旧 pack.json 消失，image.json 的 manifest_sha256 已改变。原记录备份在证据根 reinstall/previous-pack-record.json。需要冲突整体预检与本轮写入所有权/原值恢复。
3. **P1：UEFI NVRAM 未自包含。** ARM 包真实导入后登记原包 vars.fd 路径。移动并保留整个包后，ensure_uefi_vars 失败；模板没有复制到状态目录。Smoke BIOS 移包再启动不能覆盖此路径。
4. **P1：readiness HTTP path 能改变目标主机。** 校验接受 path 为 @example.invalid/；拼接后的 http://127.0.0.1:12345@example.invalid/ 被 URL 解析为 example.invalid 主机。仅静态解析，未请求该地址。应约束相对请求路径并检查最终目标；同时审查重定向是否能离开授权回环目标。
5. **P2：lab_ip 缺少实验网段校验。** segment 为 lab、lab_ip 为 10.42.0.5 的包配置被接受，与声明的实验网白名单边界不符。

## 验证范围与后续

本轮独立运行内容包专项 25 项全部通过；上述复现脚本也全部成功复现，因此专项通过不足以覆盖这些缺陷。ZCode 全回归日志是 676 项总数、10 跳过，即 666 通过；本轮没有重跑完整回归。

ZCode App 使用 Homebrew 运行时，与此前定制运行时不同；完整 Kali SPICE、Smoke、Basic、Acfun 配套不能从包结构校验推导。GUI 点击验收尚未执行，本轮桌面空闲询问未得到新答复。

本轮仅审查与落盘证据，未修改实现；没有启动或停止任何虚拟机，没有改写镜像库。分支/HEAD 保持 codex/release-0.1.1-preview-20261010 / 42a3aa71d2665e20d9aec27f4afa19eed43a784d，所有已有改动保留，无提交、推送或发布。独立复现没有产生运行中的虚拟机实例。

下一步先修复上述问题并补真实回归，再执行 GUI 正常导入、冲突、篡改失败及重试；最终使用配套运行时重新打包并验收。原始输入、派生状态与失败现场全部保留，不直接复用历史 PID。

## GUI 追加实测（用户确认桌面空闲后）

使用 ZCode 本地候选 App，独立状态为证据根 gui-state。通过原生目录选择器操作，没有启动任何节点。

- 正常选择 retained-packs/smoke-mini-pack：包摘要、资源和声明边界显示，三文件校验通过，自动安装成功，日志含“内容包安装完成：新装 smoke-mini”。再次扫描同包显示“内容一致跳过 smoke-mini”。
- **新增 P1：校验失败仍自动导入包内磁盘。** 选择 gui-tampered-pack 后 dist verify 退出 1，GUI 横幅显示失败；随后 GUI 日志出现“开始自动导入 1 个新镜像”及 onboard 对篡改包磁盘的调用，实际登记 smoke-mini-base。该节点 source_sha256 为 7efdfd8a4b3d1a7219b1a7dda85eeacabe0b9a002fd1d9b6e4045880bf420808，与包内期望 7620acabaf1b… 不同。落盘证据 gui-smoke-mini-base-image-snapshot.json，原状态保留。根因：GuiApp.swift verifyDistribution 的 defer 无条件执行 completion；失败 JSON 在命令错误文本中无法解码时 report 为空，importMissingFromManifest 后续走普通 onboard。修复必须在校验失败时中止全部导入，不能回退普通镜像路径。
- 同名不同内容：仅修改本轮 gui-state 的 smoke-mini.yaml，保留原件与冲突件快照。安装拒绝覆盖，横幅显示已有 2711f60bf106… 与包内 6c6906375445…；包摘要未提前显示冲突。GUI 调用 dist verify 没有 --conflicts。
- 恢复原测试 YAML 后点“扫描并导入新增”：成功、错误横幅消失；篡改绕过产生的第二个节点仍保留，未删除。只证明界面恢复，不能称为篡改失败无副作用。
- 篡改错误横幅仅显示命令失败与 JSON 尾部，没有正确呈现 SHA 不一致问题及红色校验行，需要修复失败 JSON 的结构化解析。

最终截图确认实际目录路径正确；此前 AX 文本仍称“未选择”属于辅助功能文本与画面不一致，不能据此认定可见路径错误。工具截图在本轮会话中可核对。

所有 GUI 操作均在上述独立状态，本轮测试 App 已通过 Cmd+Q 正常退出。新增节点未启动，失败现场、配置备份和磁盘保留。当前需修复原五处问题及本轮新增 GUI 校验绕过问题，再重新验收；不重新打包为通过版本。
