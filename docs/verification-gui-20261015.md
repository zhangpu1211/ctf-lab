# v0.1.2 发布 App GUI 验收（2026-10-15）

> 历史验收快照；不替代当前软件状态，仅覆盖本轮明确列出的界面操作，不替代后续修复后的复验。

## 结果：未通过

对象为 `/Users/pufei/Downloads/ctflab-release-0.1.2-preview-20261014/app/CTFLab.app`（0.1.2，发布标签 v0.1.2-preview.20261014）。通过原生桌面 UI 打开并读取辅助功能树及截图；默认状态目录为 `~/Library/Application Support/CTFLab`。

- 通过：App 主窗口可打开；四个既有节点列表显示已停止；选择 Kali 可展示详情和启动/快照/重置操作按钮，未点击这些操作。
- 通过：Wintermute 面板可见，刷新按钮可点击，异步读取期间禁用刷新；没有可用场景报告时停止和恢复按钮禁用。
- 阻断：初次自动读取及再次点击“刷新状态”均出现 `ctflab scenario status --json` 退出码 1，堆栈为随包 `tools/ctflab.py:6510` 导入 `ctflab_scenario`，报 `ModuleNotFoundError: No module named 'ctflab_scenario'`。错误横幅可见，刷新后仍持续存在。
- 误导提示：读取失败的同时，面板显示“状态根下没有场景实例；用 CLI scenario prepare 创建。”；失败不能证明没有实例。

## 原因定位

源代码 `tools/ctflab_app.py` 的 `_copy_ctflab_sources` 使用 `ctflab_package.RELEASE_TOOL_FILES`。后者白名单缺少场景模块；检查发布 App 的 tools 目录与发布 ZIP（`unzip -l ... '*ctflab_scenario*'`）均没有场景模块，ZIP 匹配文件数为 0。不是仅由默认目录没有实例引起。此前 App verify 与源码回归没有发现此随包依赖缺失，不能以这些通过结果替代 GUI 验收。

## 范围与后续

本轮仅验收及定位，未修改实现、重建/替换公开资产、提交、推送或编辑 Release。没有启动、停止、重置或删除任何 VM/资产。App 保持打开供查看；默认节点仅只读展示。

场景正常状态展示、运行态停止确认与取消、停止后状态刷新、事务收口/孤儿释放均因发布包依赖缺失未验收，不能标为通过。跨 Mac、公证与人工解题也未执行。

后续修复建议：补齐场景模块及其依赖的发布白名单；增加从真实打包目录运行 scenario status 的回归；区分读取失败与空状态；重建候选 App 后重新执行 GUI 验收，再决定修正版发布。

## 同日修复候选复验（不改变上面的发布版失败结论）

用户回复“继续”后修复：发布白名单补齐 7 个场景模块；GUI 用独立读取错误状态区分失败与空实例，失败时禁用场景停止/恢复操作；成功刷新只清除属于本次场景读取的旧错误。

新增测试从 `_copy_ctflab_sources` 生成的真实目录执行 `scenario status --json`、各生命周期子命令帮助及全部场景模块导入，移除 PYTHONPATH/PYTHONHOME，避免仓库源码掩盖漏文件。

验证命令与结果（2026-10-15）：
- `python3 -m unittest discover -s tools/tests -p test_ctflab_app.py -q`：62 项通过。日志包含故意缺口令的负测 FAIL 输出，最终 unittest 结果 OK；不表示执行了真实来宾验收。
- 同入口 `-p test_ctflab_gui.py -q`：25 项通过（包含 Swift 核心编译/运行和真实 GUI 构建路径）。
- 同入口 `-p test_ctflab_package.py -q`：37 项通过。
- `app build --out /Users/pufei/Downloads/ctflab-gui-fix-20261015/app --version 0.1.2 --qemu-root /Users/pufei/Downloads/ctflab-build/runtime-root --spice-client /opt/homebrew/bin/spicy --python-runtime /Users/pufei/Downloads/ctflab-build/inputs/python-runtime.tar.gz --pyyaml /Users/pufei/Downloads/ctflab-build/inputs/pyyaml-6.0.3-cp312-cp312-macosx_11_0_arm64.whl`：成功，812 个登记文件（比旧包增加 7）。
- `app verify /Users/pufei/Downloads/ctflab-gui-fix-20261015/app/CTFLab.app`：通过；许可完整，ad-hoc，未公证。
- 使用候选随包 Python 与随包 CLI，独立 `cli-state` 执行 `scenario status --json`：退出 0，正常无实例提示。

原生 UI 复验：候选原件首次读取与点击刷新均正常，无缺模块错误；默认四节点可见且已停止。独立 `fault/CTFLab.app` 副本将场景主模块暂时改名注入同类失败，确认显示“场景状态读取失败；无法判断是否存在或运行实例”，不再显示空实例提示，场景操作禁用；恢复文件后点击刷新，错误横幅与失败提示清除，正常空状态恢复。故障副本已退出，文件已恢复；候选原件保持打开。故障副本仅作测试，分发使用 app/ 下通过 verify 的原件。

构建/验证/三组测试日志保存在 `/Users/pufei/Downloads/ctflab-gui-fix-20261015/ctflab-gui-*.log`。本轮没有真实 VM 或网络服务启停，没有重跑完整 805 项回归；运行态停止确认及取消、停止后刷新、事务收口/孤儿释放仍未验收。没有替换旧 App、ZIP、镜像库或公开 Release，没有提交/推送。

文档守卫收口：`python3 -m unittest discover -s tools/tests -p '*doc*' -q`：94 项通过，跳过 5。首轮因快照头缺少固定措辞失败，补齐“不替代当前软件状态”后复跑通过；`git diff --check` 通过。结束进程核对只见候选 GUI，没有 QEMU/场景网络服务。

## 运行态验收进行中：跨语言进程身份修复

用户授权完成运行态验收和修正版交付后，在 `ctflab-gui-runtime-20261015/app-state` 新建独立实例 `f9d11feb-185f-4132-80d8-21f28ef688fc` gen1，使用安装副本只读来源 prepare/start 成功。三节点与双网在 CLI 核验存活、四卡租约齐全。代理 TUN 覆盖路由由用户关闭，启动前已重新核验。

用户通过带 CTFLAB_GUI_STATE_DIR 的命令打开 GUI；初始中文环境将所有所属进程判为 unknown，而英文 CLI 判 live。受控对照：只改变 LANG=zh_CN.UTF-8/en_US.UTF-8 即稳定复现；根因是 ps 的 lstart 本地化改变摘要。补齐 `ctflab_scenario_runtime.py` 三处 ps 调用的 LC_ALL=C/LANG=C，身份采集与恢复观测使用固定格式；保留 PID/完整命令/QMP 的原安全门槛。新增覆盖 LANG、LC_ALL、LC_TIME 差异的回归，运行时模块 15 项通过；真实运行实例在中英文环境都恢复 nodes-observed/networks-observed。旧版若曾用本地化时间生成身份摘要，仍可能 fail-closed 为 unknown，不能据此放宽身份验证或强杀。

停止确认弹窗已通过原生 UI 打开，并点击取消；取消后现场 CLI 核验三节点+双网仍全部 live，证据 `status-after-cancel.json`。尚未点击确认停止。最终修复候选改用 `ctflab-release-0.1.2-preview-20261015/app-r2/CTFLab.app`，本节结果需结合后续收口。

## 运行态与显式恢复验收收口

本轮原生 GUI 使用 r2（app-r2/CTFLab.app），显示隔离状态目录与实例 UUID 后才操作；没有接管默认目录节点。三项通过：

1. 中文环境正确显示“仍存活（进程已核验）”；停止确认弹窗可取消，取消后 CLI 再核验三节点+双网仍 live（`status-r2-after-cancel.json`）。
2. GUI 再次确认“请求正常停止”，显示进度且禁用场景按钮；正常 ACPI 关机完成后自动刷新为“已停止”，双网/节点均 stopped-observed；`status-gui-stopped.json` 的五成员停止证明全为 stopped。没有强杀。
3. 在同一独立实例停止态用 `fault-steps.py` 仅注入指针原子替换 OSError，不伪造/改写生命周期日志：gen2 重置在切指针前中断，GUI 点击“收口重置事务”补记 aborted；随后 CLI 正常 reset 到 gen3，接续准备在切指针前中断，GUI 点击“释放接续孤儿预约”返回 orphan-released。资源账本核验活跃预约归零，进程现场核验无本轮 QEMU/网络服务，派生资产与失败现场全部保留。

恢复证据：reset-interrupt.log、reset3.log、resume-interrupt.log、status-reset-closed.json、status-orphan-released.json，以及状态根内 reset-lifecycle/node-lifecycle/network-lifecycle 与资源账本。孤儿释放后 gen3 指针保留 reset-ready，未运行代次缺少节点日志、准备预约已失效，状态保守显示待恢复；这不代表进程仍在运行。继续入口是 scenario start，不能强杀或手改记录。

另发现事务 aborted 后仍提示 --close-reset，最终源码已让审计显式携带 aborted 状态，状态建议不再重复要求收口；新增真实 CLI+合成子进程的中断→收口→状态回归。最终 app-final 与 r2 的 GUI、停止/恢复执行逻辑一致，额外变更仅为已收口事务的只读提示。最终构建与发布结果见后续收口；r2 ZIP 不是最终分发物。

本轮重跑完整回归两次阶段结果：初始依赖修复 806 项通过/跳过10，locale 修复后 807 项通过/跳过10；最终提示修复后再次回归，结果以 full-regression-final.log 为准。未执行跨 Mac、公证或人工解题；本轮运行态未重复目标 HTTP/SSH 与隔离矩阵验证，其通过结果仍属于 2026-10-14 原验收。

## 最终发布门槛（2026-10-15）

- `python3 -m unittest discover -s tools/tests -q`：最终源码 808 项通过、跳过 10，耗时 230.098 秒，日志 `ctflab-gui-runtime-20261015/full-regression-final.log`。
- 最终 `app-final/CTFLab.app` 构建与 app verify 通过（812 个登记文件、SPICE 客户端随包、许可完整、ad-hoc、未公证）。最终 App 原生默认窗口正常读取四个已停止节点与空场景，没有导入异常；GUI 源码逐字节核对与运行态验收 r2 一致。
- 最终 ZIP `CTFLab-0.1.2-preview.20261015-macos-arm64.zip` 为 53,797,125 字节；SHA256 `7ffd66736b8970483e53af7990f7d93f33d4568366b18cb4884283b8e056a5fd`。实际解压到 zip-check 后用其随包 CLI 在中文环境执行 scenario status 成功，7 个场景模块齐全，见 zip-smoke.log。
- 最终状态 status-final.json：独立实例 gen3 reset-ready 保留，活跃预约为空，节点/双网停止证明全为 stopped；结束时重新核验无本轮 QEMU/网络进程。没有删除原始资产、旧验收或受控故障现场。最终默认 GUI 保持打开，不操作默认节点。

源码与日期标签、远端发布及镜像库交付以状态文档最终收口为准。旧 r1/r2 ZIP 保留在 rejected-r1/rejected-r2，不得用于分发。

## 发布交付收口

本轮修复及验收文档提交 `3cc1339`，分支与日期标签 `v0.1.2-preview.20261015` 均已推送；发布包中的 19 个入口/依赖/GUI 文件与该提交逐字节一致。

[修正版预发布](https://github.com/zhangpu1211/ctf-lab/releases/tag/v0.1.2-preview.20261015) 已上线，API 复核 draft=false、prerelease=true，仅 ZIP 与 SHA256 两个资产，uploaded，大小分别 53,797,125/112 字节，服务端 digest 与本地及镜像库一致。API 证据 release-api-final.json；旧 20261014 预发布已追加被修正版替代及漏模块说明，旧资产保留。

镜像库 03-软件 已新增两个日期资产并更新 最新版.md，原入口文本备份于证据根 library-latest-before.md。场景内容包没有公开上传。最终状态文档以单独 docs 提交收口，不移动构建标签；无运行测试 VM/双网服务、无活跃预约，process-final.json 记录结束核验，所有状态根与派生资产保留。
