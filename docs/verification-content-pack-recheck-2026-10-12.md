# 内容包修复后的独立复验（2026-10-12）

> 历史验收快照；不替代当前软件状态。

证据根 `/Users/pufei/Downloads/ctflab-contentpack-independent-recheck-20261012`。在全新目录运行 verify-fixes-independent.py（复制修复轮脚本，使用当前源码与真实 qemu-img），原五个后台场景通过，结果见 fix-results.json 与 verification.log；没有启动虚拟机或访问外网。内容包专项 30 项通过。app-r3 的 app verify 独立通过：782 登记文件、QEMU 11.1.0、内置 Python/PyYAML、ad-hoc。原 GUI 绕过已在代码中加失败门控，本轮没有重做桌面点击；ZCode 的 GUI 与 ARM 实机结果属于其验收证据。

## 尚存问题：NVRAM 失败重装改变既有登记（P1）

追加独立验证：GUI 专项 25 项通过（93.691 秒）；app-r3 内 ctflab.py 与 ctflab_dist.py 均与当前源码逐字节一致。测试包含 Swift 核心编译和决策检查，不等同本轮 GUI 点击复验。

在本轮独立 ARM 状态中保存模板字节，再将状态目录的模板改成损坏测试副本，重装保留的原包。安装正确报告“状态目录中的 UEFI NVRAM 模板与包内登记不一致”，但失败前 image.json 的 uefi_vars_path 已从状态目录改成 retained-pack/vars.fd；其元数据发生变化。模板测试后恢复原字节，登记失败现场保留，未操作其他状态。

证据 nvram-failed-reinstall.json。根因：install_content_pack 在复制/校验状态 NVRAM 之前调用 _import_image_unlocked；该调用先把包内 NVRAM 路径写入既有 image.json，随后节点被标为 committed。模板失败无法恢复已有登记。修复应将模板校验/安装纳入节点提交边界，既有节点失败时保留原登记，新节点失败时不要交付引用包内路径的半安装状态。补已登记 ARM 节点模板损坏及模板复制失败的恢复用例。

当前结论：原五场景关闭证据成立，但失败重装保护仍有遗漏，暂不宣布整体验收通过。当前未重新打包；ZCode app-r3 未发布。分支/HEAD 保持 codex/release-0.1.1-preview-20261010 / 42a3aa71d2665e20d9aec27f4afa19eed43a784d。所有既有改动与资产保留，无提交、推送或发布。本轮无启动的测试虚拟机。

## NVRAM 补修后的独立复验（同日追加）

当前源码的前置模板校验/复制和 expect_sha256 导入已经落地。在全新证据根 `/Users/pufei/Downloads/ctflab-contentpack-independent-final-20261012` 运行 verify-independent-final.py：原五个场景通过，追加真实状态模板损坏、注入 OSError 复制失败均保持 image.json 和 pack.json 逐字节不变，新模板无残留。前者是实际文件 IO 与导入，后者注入复制错误、其余使用真实 qemu-img/文件 IO。原始包与旧失败现场没有改写，无来宾启动或外网请求。内容包专项独立重跑 32 项通过。结果 independent-final-results.json、verification.log。

**源码缺陷可关闭，但交付 App 尚未更新。** 本轮 app-r3 的 app verify 通过，然而包内 ctflab.py 与当前源码不一致，包内 install_content_pack 仍向 _import_image_unlocked 传 manifest，缺少此次 NVRAM 前置提交边界修复。证据 app-source-comparison.json 记录两份 SHA-256。本轮没有重新构建或替换 App，不能将源码测试或之前 GUI/ARM 实机结果作为新版 App 已包含补修的证明。下一步用配套运行时输出新的独立 App 目录，比较包内源码并做包内失败恢复验证，再收口本地交付。

ZCode 全量日志 683 项总数、10 跳过，应读作 673 通过、10 条件跳过；本轮只重跑受影响专项，未重跑完整回归。分支/HEAD 未变，现有改动与资产保留，无提交、推送或发布。

## app-r4 独立交付核对（同日追加）

证据根 `/Users/pufei/Downloads/ctflab-contentpack-independent-r4-20261012`。app verify 独立通过，743 登记文件；包内 ctflab.py、ctflab_dist.py 与源码逐字节相同。树摘要 bdba17328b527e3093c238793ed07c589fc52ddf2893631ba4ac975e4d03748e、MANIFEST 摘要 95897de7269a2bfde50fbfe585d98ab101b09b1089a6a5c703147abdf9e31fd1，与旁车相同。在新状态复制并运行包内验收脚本，模板损坏与复制失败均拒绝，原节点/包记录逐字节不变，登记保留状态副本，新模板无残留。结果 r4-nvram-recheck-results.json、nvram.log。源码/App 不一致问题关闭。

运行时溯源表述需更正：对照 ctflab-continuation-20261012/app-final，bin 的 4 个文件及 share 的 50 个文件均相同；70 个 dylib 中 65 个相同，libpcre2-8.0、libglib-2.0.0、libgobject-2.0.0、libgmodule-2.0.0、libgio-2.0.0 这 5 个不同。排除 Mach-O LC_CODE_SIGNATURE 指定的数据区后仍不同，不能解释为仅签名字节改变，也不能认定全部逐字节同源。对照结果 artifact-check.json 与 dylib-signature-comparison.json；这不是已证明的运行故障，但旧 SPICE 实机证据不能无条件替代这套闭包的运行验收。

app-r4 可作为含修复的本地候选入口，ad-hoc、未公证、未发布。当前没有本轮 GUI/来宾运行验收；后续补动态库差异溯源或在用户确认空闲后验证 app-r4 的真实 SPICE 显示路径。未操作桌面或启动虚拟机，未提交/推送/发布，原失败现场与资产保留。

## 溯源与 SPICE 证据追加核对（同日）

实际逐字节比较确认 app-r4 的上述 5 个库均与 ctflab-input-recovery-20261010/app 内对应库相同，SHA 前缀与 dylib-provenance-trace.json 的 per_lib 表一致。相对 continuation/app-final 的差异仍成立，不能恢复“全部库字节相同”的表述。溯源文件 chain 第一项把 libgio 的 fa3f18c1de7a 写在 libglib 项中属于标签笔误，应以 per_lib 与实际字节为准。

独立查看 spice-r4-clean.png：CTFLab Kali 窗口完整显示 Kali 登录框及壁纸；spice-state 的客户端日志包含 display-ready=1、来宾显示尺寸、quit-requested、quit-cleanup-complete。现场 pgrep 未发现 qemu-system、CTFLabGUI 或 spicy 进程。此次仅核对 ZCode 已产生的实机证据，没有再次启动来宾或操控桌面。

结合已独立完成的 app 校验、包内源码一致性与 NVRAM 失败恢复，这项运行时疑虑按实际范围关闭：app-r4 的 SPICE 路径有登录画面渲染证据，接受其作为本阶段本地候选交付。未认证登录、未验收登录后输入交互/长时运行/跨 Mac，不扩展为全场景稳定性结论。当前入口 app-r4，源码和文档未提交，未推送或发布。
