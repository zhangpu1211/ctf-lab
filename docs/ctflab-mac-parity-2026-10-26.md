# Mac / Windows功能接入与交付状态（2026-10-26）

回答“之前的所有功能Mac具备了没，Windows是什么形式”：**Mac尚未具备全部后续功能；Windows是桌面程序开发候选，最终安装版未完成。** 共享Python源码、前端可构建、旧Mac App已接入、最终包可用和实机通过必须分别记录，不能互相替代。

本轮在`/Users/pufei/Downloads/ctf-lab`继续开发，分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`保持。既有改动保留未提交，旧Mac更新器与旧包保留，没有重新打包/提交/推送/发布。当前安装的旧App不会因源码修改自动更新。

## 1. 两端是什么形式

| 层面 | Mac原运行器 | Windows新工作台 |
|---|---|---|
| 界面 | `gui/GuiApp.swift`、`GuiCore.swift`的原生App，调用随包Python CLI | `desktop/`的Tauri/Rust薄壳与React界面；实验/拓扑/模板/远程/版本/诊断页源码 |
| 本地后端 | `tools/ctflab.py`及原场景模块，Apple Silicon QEMU/显示/本地实验网络 | 固定Python桥接、持久契约/代次、QEMU WHPX驱动；不从课程执行任意宿主命令 |
| 运行时 | 保留历史Mac App自己的运行时与更新链 | 计划随包提供Python/QEMU/固件及离线WebView2；运行时来源/闭包仍须验收 |
| 安装交付 | 原Mac App沿历史；本轮只是未打包源码 | NSIS当前用户安装包为目标；`tauri.conf.json`当前`bundle.active=false`，不能称已生成正式安装版 |
| 已有测试包 | 历史材料按各自证据范围理解 | Windows验证ZIP/测试脚本是候选验证材料；不是完整最终安装包。用户已通过Smoke不重做 |

Windows不是网站或网页服务；React界面放在桌面壳内。前端/桌面壳在Mac可构建，不表示Windows本地后端已成为Mac驱动；第104节通用`ctflab_qemu_driver.py`新增显式darwin-arm64分支（ARM/HVF与确认后的x86/TCG）；Mac原运行链和更新器仍保留。原生身份/退出内核项已在专用普通子进程验证，真实QEMU来宾和最终包未验。

## 2. 逐类接入状态

| 功能 | Mac原App/原运行器 | Windows/新版共享工作区 | 尚缺或未验证 |
|---|---|---|---|
| 导入/启动/停止/重置/快照/显示 | 既有原生入口与历史Mac证据保留；本轮不重验真实VM | 新本地契约、节点与显示入口已有源码，Windows已有部分用户实机回传 | 最终包、多节点故障/全部正常停机、干净机与课堂矩阵 |
| 原Mac更新 | Swift/CLI原链保留，更新器源码3文件与HEAD核对 | 独立签名版本库、协调/启动/恢复与版本页源码 | 新版本页在Mac只读，不能替代旧Mac更新器；最终安装/在线更新未完 |
| 原三节点双网场景 | 第103节新增原Swift面板：设计/绑定基盘/明确仿真/准备/启停/保留旧代次重置/收口中断重置；未打包 | 通用运行器另走v2清单，不能互换 | 原Mac场景格式仅kali/straylight/neuromancer固定拓扑；新版通用拓扑仍缺Mac适配，实机未验 |
| 退出观测器补建 | 第104节通用Mac链使用libproc/kqueue并接入补建；原固定场景链保留 | Windows/Linux通用驱动新增显式补建退出观察、独立证据/日志、桌面入口 | 需现场核验QEMU身份/认证通道；不接管匿名管道、不重放关机；原生故障未验 |
| 自由拓扑/模板 | 第104节新增通用v2原生入口、清单设计/绑定资产/NVRAM/启停重置/源模板导出；每网段两成员，尚非原生画布编辑 | React拓扑/草稿编辑、校验差异与新实例导入；通用后端新增Mac分支 | 原生画布/差异编辑、更多网络形态、实际网络观测与部署；旧App未更新 |
| 远程目标/租约/显示/证据 | 第100节原Swift远程页源码已接目标/连接/状态/租约/重试/传输/显示请求；原App包未更新 | React目标/连接取消/租约/传输/显示请求/证据页源码 | 真实SSH、原生IPC/显示及长期故障；不能称Mac原App已经有全套 |
| Docker/网关/DNS/时间/OCI | 第104节通用Mac链及原生按钮接入固定来宾网络/服务/容器/分析操作；未真实运行 | 专用Linux来宾、routed veth/回程、OCI与有限恢复核心源码 | 真实Mac来宾/D02隔离、OCI/卷及异常恢复；源码按钮不替代实际服务验收 |
| 审计/签名封存/换库/调度 | 有独立CLI与共享核心；未整合为Mac原App运营界面 | 受限Runner与CLI核心；调度默认不启用 | 外部可信锚/长期故障、真实环境；禁止本轮实际到期调度 |
| CPU/内存/PID限额 | 无对应Mac内核限额实现 | Linux预委派cgroup路径已有源码，Windows完整硬限额仍缺 | Mac/Windows平台实现与压力测试，不能把Linux结果移用 |
| 多文件磁盘增长 | **本轮新增APFS预设卷配额绑定，接原Mac CLI操作门及存储报告**；第104节继续绑定通用实例的复制/提交/后台/观察；原App包未更新，没有Swift配额设置页 | Linux预配置ext4/XFS容量绑定已实现；Windows总配额仍缺 | APFS真实限额卷/写满、Linux原生、公共缓存/审计总量与全平台覆盖 |
| 外部Kali→Windows→AD | 固定SSH TCP服务/恢复收据核心不等于完整Mac组网 | 同一共享核心与受限协议源码 | 全L3/UDP路由隧道、真实外部VM/AD恢复；原软件管理其生命周期 |
| C01—C07/O02课程与分析 | 历史Mac课程/样板不代表新全课程路线图完成 | 目录/精确变体/证据/分析器配方与有限执行核心 | 合法真实素材制作、分析镜像/重复输出、完整课程和5人试点 |

**43项、G0/G1仍未完成，集中实机总验收尚未开始。** 上表不是跨平台功能全部完成的承诺；后续按整批说明第4节推进，把每项的后端、界面、打包与验收分开收口。

## 3. 本轮Mac容量约束具体实现

新增`tools/ctflab_macos_storage.py`，使用Darwin `getfsstat64/fstatfs64`与固定只读`diskutil info -plist`、`diskutil apfs list -plist <容器>`：

- 只接受已有、已挂载且当前用户私有的专用APFS卷及其直接子状态根，要求nodev/nosuid、可写，拒绝系统/Data等有角色的卷、snapshot、无配额/无限额、锁定卷、设备/UUID错绑、同设备别名或嵌套挂载。
- 容量来自卷的`CapacityQuota`，不把共享APFS容器容量或空闲空间当作卷配额；UUID/设备/挂载FSID/标志、根和挂载点inode共同绑定。配额/身份漂移拒绝，不重绑、不增大配额。
- `inspect`只输出候选描述。旧Mac CLI新增`storage-limit --policy <私有描述> --policy-sha256 <描述sha256字段>`，只向**新的空状态根**独占登记，禁止覆盖/迁移已有用户资产；它不创建卷或设置配额。
- 原`LabManager.operation_lock`在会增长数据的操作前后核验；安装QEMU、实验网络和运行QEMU派生前再次检查，避免原声明被移走后降为无限额。未知/漂移保留部分文件，不自动清理。原`stop`/`stop-install`不因配额异常被额外阻断，不修改原正常停止语义。
- `ctflab storage --json`增加`capacity_limit`，文本报告显示已观察上限/当前可用或未核验；未配置的旧根不自动登记或改变配额。旧Mac运行器依赖已进入未来源码/App打包白名单，**本轮未构建或覆盖旧App**。

只读候选入口：

```text
python3 -I -B tools/ctflab_macos_storage.py inspect --run <专用卷中的新状态根> --mountpoint <专用APFS卷> --max-bytes <明确上限>
python3 tools/ctflab.py --state-dir <同一个新状态根> storage-limit --policy <私有描述文件> --policy-sha256 <描述sha256字段>
python3 tools/ctflab.py --state-dir <该状态根> storage --json
```

上述入口只说明用法，**本轮没有对用户状态根登记，没有创建/挂载/格式化/扩容或修改任何真实卷配额**。专用卷必须由部署方事先准备；不能拿系统卷或现有资产根试配。状态根中所有节点/镜像/快照/日志共同受该预设卷配额约束，卷外公共缓存/导出不包含。仍需真实卷正向绑定、写满/复制失败、长期运行与重挂恢复验证。

容量描述不含密码/票据。登记后若写满、中断或漂移，保留原描述/部分结果/磁盘，先只读核验；没有自动删除、强制重绑/解除或自动迁移入口。登记失败但文件已写的窗口明确为未完成，不自动覆盖重试。

## 4. 本轮验证范围

证据根`output/mac-storage-20261026`。Mac专项15项：APFS plist配额与系统卷/无限额拒绝、UUID/设备/根身份/配额漂移、空根独占登记/已有资产拒绝、旧根不迁移、导入/快照前拒绝、部分文件保留/锁释放、移走声明拒绝、存储报告与停止不额外受阻、CLI解析/隔离帮助、磁盘满时锁元数据刷新/关闭失败不掩盖原异常且释放内核锁。成功配额路径使用替身与自有临时目录，没有运行真实VM。

其中Darwin挂载表与保留目录FD的getfsstat64/fstatfs64读取在当前Mac真实执行并通过；这只证明只读挂载接口可用，不证明APFS配额成功约束或VM业务。固定diskutil plist字段也做了只读调查，没有保存真实UUID/卷名到项目文档。首次辅助调查将plist管道交给需seek的读取器而失败，改用内存字节解析；首次源码保全用了不存在的常量，改用实际发布白名单。两者是辅助脚本错误，不是产品测试通过证据。首轮独立副本还发现旧Mac CLI缺ctflab_platform依赖，现已复用Mac工具白名单并包含固定profile；独立副本再次运行，而不是依赖仓库路径绕过缺失。

完整/专项/独立源码副本最终结果见本文末尾与`final-evidence.json`。原Mac更新器、验收入口、测试三文件与HEAD核对；Swift/React/Rust未修改，不将旧构建结果当作本轮新原生验收。所有禁止事项继续遵守，不重做Windows Smoke，不停止现有VM，不实际到期调度，不删除用户资产、提交、推送、覆盖旧包或发布。

原生接口依据：[Apple XNU当前statfs64布局](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/mount.h)、[Apple getfsstat说明](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/getfsstat.2.html)。APFS配额语义另查本机`man diskutil`；归档文档中旧32位结构不能直接用于当前64位调用。

接续：继续`/Users/pufei/Downloads/ctf-lab`，读AGENTS.md、状态第99节、本Mac/Windows功能矩阵与43项台账末尾，现场核验并保留改动；继续补未关闭功能和Mac接入，最后集中实机验收。保持原Mac更新器及当前禁止事项，缺镜像/SSH/证书已知，不把43项/G0/G1或源码进展写成已发布App全部具备。

资源收口：最后完整/独立副本执行会话结束；本机只读快照未发现QEMU、本轮实际调度/显示/HTTP夹具或fixture-worker。没有创建HTTP服务器或浏览器夹具，没有操作用户VM/历史PID、真实卷/配额；不推断远端Windows/SSH状态。快照见output/mac-storage-20261026/process-final.json。

第99节最终核验：完整1534项，1513通过/21条件跳过（231.651秒）；独立源码644项，636通过/8跳过（17.735秒），207文件/147个Python语法/15个固定CLI帮助通过。Mac专项15项通过，原生命周期12项/快照17项通过，文档94项/89通过/5跳过。真实Mac仅只读挂载表/目录FD接口，配额正向/VM/原App更新未验；Swift/React/Rust未改未重跑。摘要output/mac-storage-20261026/final-evidence.json，完整full-final.log、独立isolated-corrected-final.log，早期失败/阶段日志保留。

第100节已补原Swift远程工作区源码接入，见[本轮说明](ctflab-mac-remote-2026-10-26.md)。这不改变旧App未更新、真实SSH/原生交互/全43项未验收的边界；本机拓扑/容器/审计等接入继续开放。

## 第104节增量（2026-10-27）

通用Mac后端/原生工作区与可选完整运行时见[接入说明](ctflab-mac-generic-2026-10-27.md)。完整运行时构建可保留并隔离核验cryptography/Tcl/Tk、登记许可证与相对动态库检查；默认历史裁剪和原更新器保留。本轮只编译独立GUI、构建开发前端和临时测试夹具，未打包或更新旧App。Mac/Windows CPU与内存等完整硬限额、服务器课程管理/审计运营、全L3/UDP、真实课程/分析镜像和最终交付仍未关闭；不改43项/G0/G1门槛。

## 第105节增量（2026-10-27）

Mac原生远程工作区和Windows React桌面均新增[课程/审计管理](ctflab-course-administration-2026-10-27.md)源代码入口：保存目标后按教师/管理员能力显示，登记课程预览/配置、管理员未决分页/终态观察与原请求恢复。配置不启动，观察保留原worker未知；Mac原更新器保留。未更新现有App或Windows安装包，真实SSH/双端交互尚未验。原生拓扑编辑、完整硬限额、长时监督与其他43项未关闭判据继续开放。

第106节继续补[原生拓扑草稿与差异](ctflab-mac-topology-2026-10-27.md)，Mac使用SwiftUI画布和固定generic-client，Windows沿既有React图形编辑器。两者都只编辑草稿并通过后端校验后导出，运行实例不热改。更丰富原生编辑与人工/来宾端到端验收仍未完成，未更新已安装软件。

第107节在原生/React两端继续补CPU/内存、启动依赖和空闲网段移除；两种模型生成的资源/依赖清单经生产Python逐值核对一致。原生关闭面板不受编辑禁用状态阻塞。硬配额、多成员网络执行和实机/最终包仍未完成，见状态107。
