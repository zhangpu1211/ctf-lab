# 2026-10-05 输入坐标、窗口记忆与停止路径崩溃修复

本轮修改位于 /Users/pufei/Downloads/ctf-lab，保留已有未提交改动。没有操作用户
虚拟机、没有改写宿主剪贴板、没有向宿主桌面注入输入。涉及真实窗口的验证只使用
无盘 QEMU 的临时测试节点（与既有 E2E 相同模式），测试后均已停止并清理。

## 行为变化

1. 客户端按键跟踪（ctflab_spicy.c）：key snooper 记录已按下的 keyval，窗口
   失焦、抓取断裂或客户端退出（request_client_quit）时统一向来宾补发 release，
   避免 Cmd-Tab 切走后修饰键在来宾侧卡住。被客户端消费的 Shift+F11 不进跟踪
   集合。snooper 仍在 GTK 主线程，无新增锁。
2. 窗口几何记忆：客户端新增 --geometry WxH（显式覆盖，同时忽略记忆的全屏标记）
   与 --state-file PATH（跨次启动记忆尺寸/全屏/scale，单行文本、
   g_file_set_contents 原子替换、越界值按损坏拒绝）。runner 为每个节点传
   state/<node>/runtime/<profile>/spice/client-window.txt；spice_client_command
   对 geometry 做与 C 端一致的边界校验（宽 400-16384、高 300-16384），
   非受控客户端与 clipboard 参数同例静默忽略。
3. 全屏改进：进入全屏记录窗口化尺寸，退出恢复该尺寸（替代硬编码 1000x700）；
   全屏贴合窗口当前所在显示器（原来固定主显示器）；监听 GdkScreen 的
   monitors-changed/size-changed，全屏中显示器几何变化时重新贴合。
4. 分辨率切换过渡防护：显示区包进 GtkOverlay；提交 monitors config 前捕获
   最后一帧（spice_display_get_pixbuf），过渡期显示冻结帧并拦截指针输入，
   直到捕获帧尺寸与请求一致（120ms 轮询）或 1.5s 超时；来宾已在目标尺寸时
   跳过过渡。apply_guest_resize 增加同尺寸去重，窗口移动不再重复 modeset。
5. 停止路径崩溃规避（ctflab.py）：非优雅 stop 先 SIGTERM 显示客户端（有界
   1s，超时 SIGKILL）再发 QMP system_powerdown/quit；优雅 stop 保留显示，
   QEMU 退出后再回收客户端。新增 terminate_spice_client 辅助函数。
6. 客户端信号优雅退出（ctflab_spicy.c）：SIGTERM/SIGINT/SIGHUP 经
   g_idle_add 转到 GTK 主线程统一走 request_client_quit，因此停止信号也
   补发按键 release、干净断开并保存窗口状态文件，退出码 0；不再默认终止。
7. 分阶段启动状态（ctflab.py + gui/）：`status --json` 为每个运行节点嵌入
   `boot` 摘要——固定四阶段（进程启动/系统引导/显示连接/网络就绪）由既有
   信号推导（QEMU 存活、任一健康检查通过、SPICE 客户端日志 display-ready=1、
   宿主侧检查全部通过），phase 取已达成阶段；非 SPICE 后端的显示阶段与无宿主
   检查的网络阶段标记不适用（ok=null），不伪造进度。超过就绪超时仍未就绪时
   附 diagnosis（卡住检查、日志路径、单节点恢复说明）。文本 status 输出阶段
   行；GUI 节点表新增“启动阶段”列（超时橙色标记，提示列显示诊断 hint），
   旧版无 boot 字段的 JSON 仍兼容解析。
8. 优雅停止同样先断客户端（ctflab.py）：真机 E2E 实证来宾响应 ACPI 的干净
   关机同样触发 spice-server RedClient 销毁段错误（19:48/19:53 两份崩溃
   报告，与 QMP quit 路径同签名），且来宾关机快于任何固定等待（5 秒延时
   版本仍复现）；改为优雅/强制一律先 SIGTERM 客户端再发关机命令。停止时
   显示窗口随之关闭属预期语义变化。
9. 诊断包导出（ctflab.py）：`doctor --diagnostics PATH` 输出脱敏 JSON
   （版本/能力/各节点四阶段摘要/日志尾行），疑似凭据行整行替换，0600 落盘。
10. 真机桌面 E2E（tools/tests/test_ctflab_resolution_lifecycle_e2e.py，
    环境门控）：四阶段时间线轮询、三档窗口+全屏往返驱动钩子（仅测试副本
    编入，agent 就绪后才启动）、ACPI 正常关机、重启复测、QEMU/客户端资源
    采样与多节点负载。日志行附单调毫秒时间戳（不改变既有断言子串）。
11. 快照与存储管理（ctflab.py，第 10 项）：`snapshot create/list/revert/
    delete` 对停止节点 overlay 的命名内部快照（NVRAM 成对副本，恢复一并
    还原）；`reset --backup NAME` 把整个实例盘移入状态目录备份区（rename，
    免受 reset 清除），`snapshot restore-backup/list-backups` 恢复与列举；
    `storage [--json]` 只读报告各节点基础镜像/overlay 占用、backing chain
    完整性、快照、备份与运行中引用。快照名限定 ^[a-z0-9][a-z0-9_.-]{0,31}$
    （空格/中文会破坏 qemu-img 列表解析）；基础镜像只读不变；GUI 接线未做。
12. 节点管理界面增强（gui/ + ctflab.py，第 8 项切片）：`status --json` 新增
    `spice_client` 字段（pid/alive/display_ready，仅 SPICE 节点）；GUI 节点
    表新增搜索框（匹配 ID/名称/显示名，显示过滤计数）、统一"状态"列
    （未导入/基盘失效/已停止/启动中/运行中/启动超时/状态残留，问题态橙色）、
    "显示客户端"列（已连接/连接中/未连接/—，与虚拟机状态分列）、单节点
    "重启所选节点"（组合既有 stop+run，两步任一失败即停并报告）。
    标签/分组/收藏与实验组合未做（需先设计状态目录持久化，不本轮伪造）。
13. VMDK/OVA 导入链路（ctflab_inspect.py + ctflab.py，第 9 项切片）：
    find_disk_and_ovf 升级为显式选盘（preferred_disk，按成员文件名）并返回
    全部磁盘名；import 复用同一安全解包（拒绝越界 tar 成员路径）；OVA 多磁盘
    时 inspect 默认第一个并警告、import/onboard 必须显式选择系统盘（写操作
    不猜测），导入登记 ova_disk/ova_disk_count；import/inspect/onboard 增加
    --disk；导入输出基盘实际/虚拟占用与选盘信息。
14b. 显示偏好（ctflab_spicy.c + ctflab.py，第 3/6 项）：`--display-quality
    sharp|smooth`（默认 sharp）。sharp=Retina 设备像素；smooth=逻辑分辨率
    （Retina 上像素数降为 1/4，滚动/拖动更流畅）。两者都真实改变来宾分辨率
    并沿用同一输入变换，不是拉伸冒充；偏好记忆进节点状态文件（quality 字段，
    旧 4 字段格式兼容），`run --display-quality` 一次性覆盖。日志行新增
    multiplier= 与 display-quality=。
14c. 启动前资源预检（ctflab.py，第 7 项）：run 前检查宿主物理内存（sysctl）
    × 0.9 与运行中+本批节点配置内存总和，超配拒绝并附全部数字；状态目录
    所在卷可用空间低于 5 GiB 告警；预检探针异常一律跳过、绝不阻塞启动。
    run 的顺序启动即启动队列；轻量/标准靶机配置由 profile 固定。
14d. 实验网只读视图（ctflab.py，第 11 项展示切片）：`network [--json]` 并排
    profile 声明策略（segment/实验 IP/网卡/联网）与运行实际（DHCP 租约/端口
    映射/交换机客户端、MAC、收发计数/残留实例）；Kali 默认 user-mode NAT
    单独注明；靶机运行时联网与声明不一致明确标记。只读，不做变更。

## 崩溃根因证据（停止路径段错误）

2026-10-05 系统共 10 份 qemu-system-aarch64 崩溃报告（~/Library/Logs/
DiagnosticReports），其中 9 份为同一签名：

```
libspice-server: InputsChannel::release_keys()
  ← RedChannelClient::disconnect() ← RedClient::destroy()
  ← reds_disconnect ← spice_server_destroy ← qemu_spice_cleanup ← qemu_cleanup
```

EXC_BAD_ACCESS（KERN_INVALID_ADDRESS，小地址偏移，呈 use-after-free 特征）。
触发条件与“QEMU 干净退出（ACPI 关机或 QMP quit）时 SPICE 客户端仍连接”吻合：
本日 16:44 的 3 轮 TCP E2E（QMP quit + 客户端连接）产生 2 份新报告；无客户端
连接的 SIGTERM 认证探针未产生报告。修复后同一 E2E 先后重跑两轮（含信号优雅
退出版本客户端），崩溃报告数保持 10，零新增（此前同场景每轮 1-2 份）。这是
行为对照证据；spice-server 内部的 UAF 机制未做源码级定位，优雅关机（来客
ACPI 自行退出）路径仍保留客户端，崩溃窗口未完全关闭，属已知限制。

首次启动黑屏/健康超时与此崩溃的因果关系（例如段错误是否跳过磁盘/NVRAM
flush 导致下次启动异常）仅为待验证假设，本轮没有证据支持，不作为结论。

## 首次启动黑屏/健康超时的证据核对

对照当日证据后的结论（不把推断写成事实）：

- 失败的两轮验收（evidence/app-check.json、app-check-r2.json 的 rounds 均为
  空）运行在隔离临时状态目录，日志已随目录清理，本轮无法从日志归因。
- 14:35:51/14:36:05 两份崩溃报告与失败轮的清理停止时间吻合，崩溃栈同样是
  停止路径 spice-server 签名——它们是失败轮“停止清理”的产物，不是启动失败
  的原因证据。
- 成功轮 r3 第一轮的 QEMU（健康检查记录 PID 60834）与 15:53:43 崩溃报告
  byPid 60834 一致：证明停止路径崩溃同样发生在真实图形显示会话，不只发生在
  E2E 无界面场景；该缺陷本轮已修复（见上）。
- 结论：首次超时的根因仍未定位。相邻机制（僵尸 PID 误判——前次会话已修；
  停止路径段错误——本轮已修）已消除，后续若复现需保留当轮 QEMU 与客户端
  日志再归因。

## 真机桌面 E2E 结果（第 1/3/7 项可自动化部分）

`CTFLAB_DESKTOP_E2E=1` 运行 test_ctflab_resolution_lifecycle_e2e（r2 候选
App 的受控 QEMU + 现场编译客户端），证据存
`/Users/pufei/Downloads/ctflab-e2e-evidence-20261005/`：

- 四阶段时间线：两轮启动均 21.98s / 21.73s 达到网络就绪；观测到
  显示连接（约 2s）→ 网络就绪（约 18s）两档（进程启动/系统引导在 1 秒
  轮询间隔内完成，DHCP 租约为运行器侧状态）。阶段无回退。
- ACPI 正常关机：stop --graceful 后来宾在 30s 内自行关机（不落强制梯级），
  状态清理、客户端优雅退出并保存窗口状态（1000x700）、零新增崩溃报告。
- 重启复测：第二次启动同样 21.73s 就绪。
- 分辨率跟随（三档窗口 + 全屏往返）：**未执行**——vdagent 用户态代理只在
  已登录桌面会话运行，登录界面恒为 agent=0（275s 观测证实）；断言按 agent
  连接条件化并记录原因。复测方式：启动本 E2E 后在弹出的 Kali 窗口手动登录，
  agent 连接即自动执行三档窗口/全屏驱动与 frame-matched 断言；或提供
  CTFLAB_KALI_PASSWORD 使脚本可自动登录（未实现）。
- 性能基线（第 5 项首轮，2 秒采样）：启动期 QEMU CPU 均值 76.7%/峰值
  135.8%、RSS 峰值 1.85GB；空闲期 QEMU 0.7%/190MB、显示客户端 0.35%/95MB。
  多节点（Kali+smoke+basic 同时运行，Kali 仍达 ready）：Kali 26.3%、
  smoke（x86 TCG）55.0%、basic（x86 TCG）50.2%（均值），RSS 峰值
  1.73G/560M/453M。UTM 对比未执行：本仓库不操作用户已有虚拟机；同机
  UTM 侧按同镜像同资源复测由用户执行后并入此表。
- 图形登录级 20 次循环：未执行（登录墙）；E2E 级 20 次零崩溃见上。

## 已运行验证

- C 客户端严格编译：clang -Wall -Wextra -Werror -mmacosx-version-min=26.0，
  链接本机 spice-gtk/GTK3；-DCTFLAB_E2E_TEST 变体同样编译通过。
- 新增 tools/tests/test_ctflab_client_input.py（4 项，ASAN/UBSAN +
  G_DEBUG=fatal-warnings）：几何解析边界与非法值拒绝、--geometry/--state-file
  参数解析、状态文件往返/损坏拒绝/NULL 安全、按键跟踪幂等/未按下 release
  忽略/容量上限/display 为 NULL 时只清空不发送。
- TCP E2E（CTFLAB_SPICE_TCP_E2E=1，旧候选 App 的受控 QEMU，现场编译本轮
  客户端源码）3 轮通过：认证、显示通道、ticket 隔离、停止清理；修复后重跑
  两轮（含最终信号优雅退出版本）均零新增 QEMU 崩溃报告。
- 20 轮启停稳定性（CTFLAB_SPICE_TCP_E2E_ROUNDS=20，299.5 秒）：每轮
  run→认证/显示通道断言→stop 全部通过；QEMU 崩溃报告 10→10 零新增；
  结束后 pgrep 无 qemu/spicy 残留进程。范围为 E2E 级（无盘无来宾系统），
  图形登录级别的连续 20 次循环仍需真实桌面验收，不得引用本条冒充。
- 停止顺序回归（test_ctflab_lifecycle.py 新增 2 项）：非优雅 stop 断开客户
  端先于任何 QMP 关机命令；优雅 stop 先 ACPI、QEMU 退出后才回收客户端。
- 分阶段状态回归（test_ctflab_status_docs.py 新增 5 项）：未运行无 boot 段、
  就绪节点四阶段全过且 phase=network、启动中节点停在 process 且显示/网络
  阶段未就绪、超时附 diagnosis（失败项清单与单节点恢复说明）、Cocoa 后端
  显示阶段不适用。
- Swift GUI 核心测试（GuiCoreTests.swift，swiftc -O arm64-apple-macos26.0
  编译运行）：92 项检查全部通过（新增 14 项：boot 字段解码、旧 JSON 兼容、
  阶段标签/计时/超时标记、诊断字段解码）。
- 真机桌面 E2E（最终版，264 秒）：两项全部通过，结论见上节；此前三轮迭代
  分别定位并修复驱动时机（agent 门控）、log_text 初始化、优雅停止崩溃。
- 诊断包（新增 3 项单测 + 真机 smoke）：疑似凭据行整行脱敏、boot 摘要包含、
  0600 落盘、CLI 参数接线；真机导出确认无 password/ticket/secret 字样。
- 快照与存储（tools/tests/test_ctflab_snapshots.py，8 项，qemu-img 小夹具
  无头验证）：创建/列表/恢复/删除往返、重名与不存在错误、非法名拒绝
  （空格/中文/大写/超长）、NVRAM 成对恢复与删除清理、运行中节点四类操作
  全部拒绝、reset --backup 保留并 restore-backup 完整还原（内部快照随盘
  保留）、普通 reset 丢弃快照、storage 报告字段与 backing 引用、CLI 参数
  接线。另在用户真实状态目录上 smoke：storage 正确报告 Kali overlay
  464.7 MiB、backing 完整。
- 节点管理界面（GuiCoreTests 新增 20 项，共 112 项全过 + Python 2 项）：
  七种统一状态推导（含残留优先级与问题态标记）、搜索空查询/大小写/过滤
  计数、spice_client 字段解码与四档客户端列文案、启动中详情附阶段标签；
  Python 侧覆盖客户端存活/display 判定、停止与 Cocoa 节点为 null。GUI 编译
  验证含 swiftc 真实构建（test_ctflab_gui 的 GuiAppBuildTests 随回归通过）。
- VMDK/OVA 导入（tools/tests/test_ctflab_ova_import.py，10 项，真实
  qemu-img VMDK 夹具）：单盘 OVA 识别与选盘报告、多盘默认第一个+警告、
  显式选盘切换与虚拟大小校验、指定不存在盘列出可选项并拒绝、越界成员
  路径拒绝、单盘导入真实转换为 qcow2 并登记 ova_disk/占用、多盘不指定
  拒绝导入且不写状态、显式选盘导入第二块盘、CLI 三个子命令 --disk 接线。
  既有 inspect/import 完整性测试（25 项）随签名变更同步通过。
- 实验网视图（tools/tests/test_ctflab_network_report.py，5 项，全 mock）：
  停止节点只显声明策略、运行 Kali 的默认 NAT 策略可见且一致、靶机联网与
  声明不一致标记、交换机计数与残留展示、CLI --json 接线；另在用户真实
  状态目录 smoke 输出正常。
- 显示偏好与资源预检（新增 6 项 + C harness 扩展）：sharp/smooth 参数校验
  与非受控客户端忽略、内存超配拒绝附数字（含运行中节点计入）、低磁盘告警、
  sysctl 异常不阻塞；C harness 状态文件往返含 quality、旧 4 字段格式兼容；
  包内客户端实测 smooth 链路（display-quality=smooth 日志、SIGTERM 退出码 0、
  状态文件 quality=1 记忆）。
- 完整回归（最终版）：发现 443 项（基线 396 + 累计新增 47），通过 435 项、
  跳过 8 项（构成同前），耗时 186.578 秒，退出码 0；git diff --check 通过。
  早期同日记录：438 项通过 430（资源预检首版与安装器测试的 subprocess mock
  冲突，已改为探针宽捕获后全过）。
- 历史记录：438 项（基线 396 + 累计新增 42），通过 430 项、
  跳过 8 项（5 项历史 UTM 交付目录缺失、1 项 TCP E2E 门控——本轮多次单独
  启用通过、2 项桌面 E2E 门控——本轮以最终版通过），耗时 169.320 秒，
  退出码 0；git diff --check 通过。
- 包内/本机客户端端到端小验证（无盘 QEMU + disable-ticketing unix socket）：
  QEMU 退出后客户端自动退出（退出码 0），日志记录 qemu-exited、quit-requested、
  window-state-saved 1000x700，状态文件内容含 scale=2（Retina）；对客户端直接
  SIGTERM 同样走 quit-requested → 保存状态 → 退出码 0。
- 早期回归记录（同日迭代）：403 项通过 397、408 项通过 402，均 6 项已知
  跳过，退出码 0；最终数字以上一条为准。

## 本地候选 App

- 路径：/Users/pufei/Downloads/ctflab-app-local-20261005-r2/CTFLab.app，
  版本 0.1.0，738 个文件、70 个动态库、50 个 QEMU 资源。
- QEMU 11.1.0（带 SPICE）与 Python 3.12.14 复用 20261005 候选 App 的受控
  运行时副本；客户端从当前源码重新编译（依赖改指旧运行时库后由构建器收
  闭包并改写为相对引用）。ad-hoc 签名，未公证、未发布。
- PyYAML 来源为本机组装的解包目录：yaml/_yaml 包与 MIT 许可证文本取自旧
  候选 App 已登记树（wheel 哈希 fc09d0aa… 与旧 MANIFEST 一致性未重新核对
  wheel 本体，PyPI 直连在本环境不可用）；dist-info 为按旧登记版本构造的
  来源标记，wheel_sha256 记为 null。
- 已知分发阻塞：运行时库经 App 内路径转手后无法归因 Homebrew formula，
  构建以 --allow-incomplete-license-texts 完成，MANIFEST 记录许可证归因
  unknown。正式分发前必须回到原始构建树重新闭包归因；本包仅用于本机行为
  验证。app verify 通过（许可证完整性 False 如实报告）。
- App 树 SHA-256：baaca657cdcd983b58182a3f407ef0a276846c9bc3d2ce0b840fab33c642fdf0
  （最终版：含显示偏好、资源预检、OVA 选盘、网络视图；包内客户端
  3c3ec8a65ada30cbba05a7ae3fe6a76ace33f2aa01cf98f7218e7ccc449f1f5e，app verify
  通过）。
  同日早期版本：3c1c2beb57333306e3b9ae472db71809afaf84f4271afd18ec425e36b4b50142
  （含分阶段启动状态、诊断包导出、停止路径修复、E2E 驱动钩子、快照/存储
  管理、节点管理界面、VMDK/OVA 选盘导入与实验网视图；app verify 通过）。
  包内客户端 SHA-256：198532a69d6fa90797295d78014d58813c228b2868f59b37545100137a1062f2。
  同日早期版本：3501481e…（节点管理版）、825ecc71…（快照版）、6e66f0bf…
  （桌面 E2E 版）、3e664be2…（分阶段状态版）、db6a60fe…（输入/停止路径首版）。

## 2026-10-07 运行时重建（原 App 误删后）

用户误删了 20261005 及 r2 两个候选 App（废纸篓已清、无本地快照），SPICE QEMU
运行时随之丢失；Homebrew QEMU 无 SPICE 后端，无法直接替代。按原始登记来源
从零重建：

- QEMU 11.1.0：download.qemu.org 源码包 SHA-256 与源码要约登记值一致
  （6ee1d1a6…）；configure --enable-spice（Homebrew spice-server 0.16.0）
  --disable-pvg --disable-sdl --target-list=aarch64-softmmu,x86_64-softmmu，
  CFLAGS/OBJCFLAGS/LDFLAGS=-mmacosx-version-min=26.0。禁 pvg 的原因：macOS 27
  SDK 将 ParavirtualizedGraphics API 标记 obsoleted（该设备靶场不使用）；禁
  SDL 的原因：SDL2 初始化在打包上下文中弹模态错误框导致挂起（sample 栈定位，
  SDL 显示后端靶场不使用）。edk2 固件从 Homebrew share 补齐。
- Python 3.12.15（python-build-standalone 20261003 tag；被删 App 为 3.12.14，
  同 3.12 线补丁升级）；PyYAML 6.0.3 wheel 为 PyPI 上与原登记哈希完全相同的
  文件（fc09d0aa…，强制校验通过）。
- 重建产物：/Users/pufei/Downloads/ctflab-app-rebuild-20261007/CTFLab.app，
  800 个文件，app verify 通过。**许可证文本完整性 True**——源码构建 QEMU 与
  Homebrew 库均可归因，此前候选 App 的 unknown 分发阻塞解除。ad-hoc 签名。
- 端到端验证：包内 QEMU -spice 正常；真机桌面 E2E 两项通过（四阶段到网络
  就绪、ACPI 正常关机、零新增崩溃），证明重建运行时与此前行为一致。
- App 树 SHA-256：ad50be1a15af2ae871cbc9d6590412e25b2e6b9e82dbd103dacec500c5f6df1b；
  包内客户端 c1f4268312455f145e03517b50b98ced0f7d7fc430a7b3a0e6561df38c545f4a。
  构建输入保留在 /tmp/ctflab-rebuild/（重启后失效；正式分发需固化来源清单）。

## 未验证项与已知限制

- 分辨率跟随真机断言（三档窗口/全屏往返/2 秒目标/重启几何恢复断言）：被
  登录墙阻挡——vdagent 用户态代理只在已登录会话运行，E2E 在登录界面恒为
  agent=0。E2E 已条件化：登录后自动执行全量断言。冻结帧过渡、失焦按键
  释放、坐标误差网格（≤2 像素）、中文输入同理需要登录桌面。
- 已登录 Kali 桌面的剪贴板重验（英文/中文/多行/大文本/连续复制/回声抑制、
  关闭共享双向不泄漏）仍未执行；涉及宿主真实剪贴板，建议用户在场时进行。
- Mac 睡眠与唤醒路径：自动化会使本机会话休眠，未测。
- UTM 同机对比（第 5 项）：本仓库不操作用户已有虚拟机；等待用户在 UTM 侧
  以同镜像同资源复测并并入性能表。
- 首次启动黑屏/健康超时根因仍未定位（证据核对见上文）；后续复现需保留当轮
  QEMU 与客户端日志。
- 候选 App 的许可证归因分发阻塞（unknown）未解除；正式分发前须回原始构建
  树重建闭包归因，并完成 Developer ID 签名/公证（需用户证书与授权）、
  无 Homebrew 新用户机与另一台 Mac 的验收（第 13 项）。
- 第三阶段（第 8～11 项）：第 10 项核心已交付（快照/重置前备份/存储报告，
  CLI 层）；第 8 项切片已交付（搜索、统一状态、客户端/虚拟机分列、单节点
  重启；标签/分组/收藏与实验组合未做，需先设计状态目录持久化）；第 9 项
  切片已交付（VMDK/OVA 安全解包与显式选盘导入；多磁盘数据盘、向导 GUI
  化、隔离试启动→服务检查→保存节点的完整流程串联未做）；第 11 项展示
  切片已交付（network 只读视图；组合独立网段、UI/CLI 策略一致性执行与
  应用级回连验证未做）。快照/存储/network 的 GUI 接线未做。GUI 新增列与
  重启按钮未经真实点击级验收（Swift 编译与核心逻辑测试已过）。

## 复现命令

```bash
# 严格编译
clang -Wall -Wextra -Werror -mmacosx-version-min=26.0 tools/spice_client/ctflab_spicy.c \
  -o /tmp/ctflab-spicy $(pkg-config --cflags --libs spice-client-gtk-3.0 gtk+-3.0)

# 全量回归（认证探针需受控 SPICE QEMU）
CTFLAB_SPICE_AUTH_QEMU=/path/to/CTFLab.app/Contents/Resources/runtime/bin/qemu-system-aarch64 \
  /opt/miniconda3/bin/python3 -m unittest discover -s tools/tests -q

# TCP E2E
CTFLAB_SPICE_TCP_E2E=1 CTFLAB_SPICE_TCP_E2E_APP=/path/to/CTFLab.app \
  /opt/miniconda3/bin/python3 -m unittest tools.tests.test_ctflab_spice_tcp_e2e -v
```

修复与文档留在工作区，未提交、推送或发布；保留原有用户改动。
