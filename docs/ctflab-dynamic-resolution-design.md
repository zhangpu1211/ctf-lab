# CTFLab 动态分辨率设计：UTM 导出路径与带 SPICE 的 QEMU 路径对比

> 当前实现状态：路径 B 的 CLI/GUI 能力门禁、QEMU 11.x SPICE 参数、可选运行时打包和 Kali XFCE
> 显示适配已接入。2026-09-16 已用带 SPICE 的 QEMU 与内置 `spicy` 完成 server/client/agent
> 连接、冷启动恢复，以及 1000×700 / 800×600 窗口对应来宾 2000×1400 / 1600×1200 的实际跟随验证。
> 旧分发基盘已清理；新版分发目录已包含 `configure.sh --display-only` 的适配结果。
> 详细证据见 `verification-display-network-2026-09-16.md`。

> 状态：**路径 A 的 `utm-export` 已实现并通过单元测试；UTM 4.7.5 必需段与必需键已按上游源码
> 补齐。2026-09-14：首次导入（R1）因缺必需段失败；补齐后导出 `CTFLab-Kali-E2E-20260914-R2`，
> 在 UTM 4.7.5 中通过“导入/解析”验收（虚拟机未启动），并完成一次冷启动与 Kali 图形登录
> （lightdm 登录 → XFCE 桌面）。同日两轮会话中另完成：剪贴板负向（英/中/多行、双向不泄漏）与
> 网络隔离（仅 lo、无路由、三向 ping 不可达、宿主无 socket/监听）。动态分辨率在重启前曾于三档
> 窗口尺寸下验证真实跟随（`step4-size-*.png`），但**重启后复测失败**：窗口缩放不再跟随并使 UTM
> 显示卡死（`step4-postreboot-failure.json`）。来宾内正常关机与无残留复核已完成；同日第三轮完成
> Smoke 与 Basic Pentesting 2 两个 x86_64 BIOS 包（`utm-export` 的 x86_64 变体）的导出与 E2E
> 交付（导入/解析、冷启动、控制台登录、基本交互、ACPI 正常关机、盘完整性与隔离核对；独立验证记录
> `verification-utm-smoke-2026-09-14.md`、`verification-utm-basic-pentesting-2-2026-09-14.md`）。
> **重启后复测失败，显示链路不稳定；当前 UTM 包仅保证固定显示可用。** 路径 A 保持“部分验证”，
> 不得宣称完整 Path A、动态分辨率或联网靶场验收；Smoke/Basic 的静态控制台 E2E 已在限定范围内通过；
> 路径 B 的运行时连接与窗口跟随已验证，但尚未达到完整动态分辨率可交付（剪贴板隔离和客户端鉴权负向仍待补齐）**。首次失败记录与证据保留在
> `~/Downloads/ctflab-utm-e2e-20260914/E2E-FAILURE-2026-09-14.md`；导入通过截图
> `import-accepted-R2.png`。默认显示路径（Homebrew QEMU + Cocoa + `zoom-to-fit`）
> 仍不支持动态分辨率；固定 `xres/yres` 与窗口缩放也都不是动态分辨率。**结构状态与运行状态分离**：
> 结构状态 `complete-required-keys` 只表示 UTM 4.7.5 必需段/必需键已按上游源码补齐；运行验收结论
> 记录在导出清单的 `runtime_status`（`e2e_scope`/`e2e_status`/`dynamic_resolution`，取值见 2.3）与
> 独立验证记录中。旧 schema 迁移标签仅用于 schema 2 兼容迁移，不作为当前 fixture 或当前结构状态
> 输出，避免 E2E 完成后产生歧义。
> 本文仍是路径对比与边界基线；SPICE 后端已接入源代码能力门禁，验收构建已能通过 `--qemu-root` 与
> `--spice-client` 纳入 QEMU/客户端，但默认 Cocoa 构建不自动携带该可选组合，也不改变现有 CLI 行为。
> 两条路径的默认关闭边界：A 的导出包默认不带网卡、默认关闭 UTM Clipboard Sharing；
> B 的动态分辨率保留唯一的 virtio-serial + spicevmc agent transport；剪贴板按 `--clipboard`
> 条件开关：未授权时 `disable-copy-paste=on`/`disable-agent-file-xfer=on` 且客户端关闭
> clipboard sharing，授权时才允许文本剪贴板（`disable-agent-file-xfer=on` 仍保留）。

## 1. 已确认事实

### 1.1 现场已验证（UTM 侧，非 CTFLab 默认路径）

在 UTM 中启用 `DynamicResolution=true`、显示设备使用 `virtio-gpu-pci`，并在 Kali 中安装
`spice-vdagent` 后，来宾 `xrandr` 的实际当前模式会随 UTM 窗口变化（现场实测 `1512x949` → `1496x909`，
2026-09-14）。这说明 **UTM 显示机制 PoC 已验证**：UTM 显示链存在由 SPICE agent monitors config
驱动的真实分辨率跟随通道，而不是把画面缩放到窗口。

该证据只覆盖 UTM 显示机制本身，**不覆盖 CTFLab 导出的 UTM 包**：导出包的动态分辨率必须按 2.4
另做 E2E 验收（实际 `xrandr` 跟随结果是唯一证据），在此之前不得声称导出包“动态分辨率就绪”。

### 1.2 CTFLab 默认路径的已确认限制（2026-09-13 记录，未变化）

- QEMU 11.1 + cocoa + virtio-gpu 只能把画面缩放到窗口（`zoom-to-fit`），来宾帧缓冲与窗口尺寸解耦；
- QMP `display-update` 在本机 QEMU 只接受 `type="vnc"`，没有 EDID 通道；
- `qemu-vdagent` chardev 只实现剪贴板/鼠标，没有 `VD_AGENT_MONITORS_CONFIG`；
- Homebrew QEMU 的显示后端只有 `none/curses/cocoa/dbus`，没有 spice。

因此本轮设计要求是：任何动态分辨率能力都必须建立在**真实通道**（UTM 的显示链，或带 SPICE 的
QEMU + 本地 SPICE 客户端）之上，默认 Cocoa 路径与现有命令保持不变。

## 2. 路径 A：独立 UTM 导出/适配路径

### 2.1 形态

- 新增一次性导出：从已导入的只读基础镜像生成一个**全新的 `<name>.utm` 包**，包内磁盘放在
  `Data/data.qcow2`，`Drive.ImageName` 只写 `data.qcow2`；
- 不修改、不覆盖、不重命名用户已有的任何 UTM 虚拟机；只做只读枚举以避免重名（大小写不敏感）；
- 首版**不接受任意用户 `.utm` 模板**：配置来自脱敏、版本固定、SHA-256 登记的内置 fixture，
  按 UTM 4.7.5 源码要求的必需段与必需键做严格白名单重建（顶层含
  `Information`/`System`/`QEMU`/`Input`/`Sharing`/`Display`/`Drive`/`Network`/`Serial`/`Sound`；
  `Display` 单元素数组、`System.MemorySize`(MiB)、`System.Target=virt`、`System.CPU=default`、
  `Drive.InterfaceVersion=1`、`QEMU.UEFIBoot=true`、`QEMU.Hypervisor=true`、
  `QEMU.AdditionalArguments=[]`、`Input.UsbBusSupport=3.0`、`Sharing.DirectoryShareMode=None`、
  `Network=[]`、`Serial=[]`、`Sound=[]`）；**变体由 profile 决定**：aarch64 + UEFI →
  `Target=virt`/`CPU=default`/`virtio-gpu-pci`/动态分辨率结构；x86_64 + BIOS →
  `Target=pc`/`CPU=qemu64`/VGA 固定显示（`DynamicResolution=false`）/IDE 或 SCSI 磁盘（无 NVRAM）；
  其余架构/固件组合明确拒绝；禁止共享目录、额外 QEMU 参数与端口转发，
  越界字段一律拒绝导出，绝不透传；
- 输出边界：目标路径已存在（文件或目录）一律拒绝，没有强制覆盖，也没有
  “本工具生成标记可复用”的例外；构建使用输出目录内不可预测、独占创建的临时 `.utm` 目录，
  全部转换与校验通过后才发布最终名称，任一失败只清理本次临时文件；
- 包内显示参数固定为现场 PoC 组合：启用动态分辨率 + `virtio-gpu-pci`；生成配置不包含任何
  CTFLab 自定义状态键（如 `CTFLabMappingStatus`），状态只保留在导出清单；
- 来宾前提（只记录可核验的基盘事实）：导出前仅记录离线可核验的基盘前提（例如镜像导入记录
  中的 `spice-vdagent` 安装/服务启用证据），写入导出清单。**离线 `utm-export` 不得声称
  已证明图形会话 agent 连接**：真正的 agent 会话、`spice-vdagent` 进程与 `xrandr` 跟随，
  只能在导出包启动后的 UTM E2E 中验收；仅 `spice-vdagentd active` 也不构成充分证据；
- 包由 UTM 打开与运行，UTM 负责该包的生命周期；CTFLab 的 `run/stop/reset` 不管理它；
  “重置”= 删除包后重新导出；
- 网络边界：导出包**默认不含任何网卡**（无 Network 条目），因此不存在 WAN 出口、物理 LAN
  可达或 CTFLab 实验网接入。若未来确需网络（单独决策），只允许显式写入固定的 Host Only
  配置并启用 UTM 的 “Isolate Guest from Host”；相关键进入白名单逐键校验，禁止 Shared、
  Bridged、端口转发，禁止继承用户模板中的任何网络配置。Host Only 的验收必须证明来宾
  无法访问宿主 Host Only IP（并复核宿主侧没有端口映射可达来宾）；
- 剪贴板边界：导出包默认关闭 UTM Clipboard Sharing（不启用任何宿主/来宾剪贴板共享，也不
  添加共享目录），生成配置禁止出现剪贴板共享相关键；E2E 必须包含宿主→来宾、来宾→宿主
  两个方向的英文、中文、多行文本负向测试（哨兵文本不泄漏）。

### 2.2 磁盘只读 / overlay / 隔离网络边界

- 基础镜像：只读；导入时登记 `base_sha256`（新转换先写临时文件，`qemu-img info/check` 通过后
  排他发布并设为只读；重复导入仅在 `qemu-img compare -s`（严格模式，容量不同也判不一致）证明宾客可见内容一致时才补登记），
  导出前核对当前基盘与登记值一致、导出前后复核未变化；缺少 `base_sha256` 的旧记录不会被
  静默信任（明确拒绝并给出处理提示）；绝不写入 `images/` 目录；
- UEFI NVRAM：`kali-arm64` 等 UEFI profile 必须登记 `uefi_vars_path` 与 `uefi_vars_sha256`；
  导出前核对原始 RAW NVRAM 哈希，转换为 UTM 使用的 QCOW2 `Data/efi_vars.fd` 并执行
  `qemu-img info`/`check`，导出后再次核对原 RAW 未变化；
- 包内磁盘：`qemu-img convert` 生成的独立副本，可写、可丢弃；转换后必须通过 `qemu-img info`
  （格式 = qcow2）与 `qemu-img check` 才能发布；不存在 CTFLab overlay 语义，每次重新导出即
  回到初始状态；
- 输出原子性：在输出目录内用不可预测、独占创建的临时 `.utm` 目录构建，构建期间最终 `.utm`
  路径不出现；任一失败只清理本次临时文件，既有文件完全不动；不使用固定 `<manifest>.tmp`
  名称覆盖用户文件；发布使用 macOS `renameatx_np(RENAME_EXCL)` 排他重命名，目标被外部并发
  创建时拒绝而不是覆盖（非 macOS 回退为“先检查后 rename”，存在并发窗口，见 2.5 边界说明）；
- 导出清单：不包含基础镜像、来源镜像、fixture 或输出目录的绝对路径，只记录相对文件名、
  profile、版本与哈希；
- 用户现有虚拟机：绝不写入；导出前后对已有 `.utm` 的清单（路径 + mtime + 内容哈希）做前后比对，
  作为测试断言；
- 网络：导出过程不监听任何端口、不建路由、不写 PF 规则；导出包默认无网卡。
  验收必须覆盖三层隔离声明：无 WAN 出口、无物理 LAN 可达、不接入 CTFLab 实验网
  （例如 `192.168.242.0/24` 不可达，Mac 也无法经端口映射访问导出包）。
  未来若启用 Host Only，另加“来宾不能访问宿主 Host Only IP”的验收；
- 剪贴板：默认关闭 UTM Clipboard Sharing，不添加共享目录；宿主/来宾双向负向 E2E 见 2.1 与 2.4。

### 2.3 CLI/API（已实现：`utm-export`；两个变体均完成限定范围 UTM E2E：x86_64 固定显示通过，aarch64 动态分辨率重启后失败，见 2.4）

```yaml
# 接口：一次性导出到新的 UTM 包（已实现）
subcommand: utm-export
usage: <profile> --out <dir> [--name <display-name>]
inputs:
  - 已导入的只读基础镜像（按 profile）；导入记录必须含 base_sha256
  - UEFI profile 的 RAW NVRAM（uefi_vars_path）+ uefi_vars_sha256
  - 内置 UTM fixture：UTM 4.7.5 必需段与必需键（按上游源码 decode 集合，键名大小写敏感）已补齐、版本固定、SHA-256 随发布登记；不接受用户提供的模板
outputs:
  - <name>.utm/              # 新包（Data/data.qcow2；aarch64+UEFI 变体另含 Data/efi_vars.fd，x86_64+BIOS 变体无 NVRAM）；目标已存在时拒绝，构建期间不出现，校验通过后才发布
  - <name>.utm.export.json   # 离线导出清单 schema 3（无绝对路径）：离线字段保持导出时原值；
                             #   磁盘哈希分列 utm_disk.sha256_at_export 与 utm_disk.sha256_after_e2e
                             #   （包内盘可写，来宾启动/关机会改变内容与哈希，两字段不得混用）；
                             #   运行结论在 runtime_status（e2e_scope / e2e_status / dynamic_resolution /
                             #   verification_records / note）；结构状态只写在 fixture.structure_status
checks:
  - 导入记录含 base_sha256，且当前基盘哈希与登记值一致；来源镜像存在时其哈希也必须与登记值一致
  - 缺少 base_sha256 的旧记录明确拒绝并给出处理提示；重复导入只在 qemu-img compare -s 证明内容一致时补登记
  - 导入记录含 uefi_vars_path/uefi_vars_sha256，且 RAW NVRAM 哈希与登记值一致；导出后复核未变化（仅 aarch64+UEFI 变体需要）
  - profile 属于受支持变体：aarch64 + UEFI + virtio 磁盘/显示，或 x86_64 + BIOS + IDE/SCSI 磁盘；
    其余架构/固件与总线组合明确拒绝并说明原因
  - fixture 哈希与登记值一致，生成配置只允许白名单键（Display 单元素数组、MemorySize(MiB)、
    Target=virt、CPU=default、Data/data.qcow2、InterfaceVersion=1、UEFIBoot、Hypervisor、
    AdditionalArguments=[]、Network=[]、ClipboardSharing=false；无自定义状态键）
  - 转换后 qemu-img info 必须为 qcow2、qemu-img check 必须通过（磁盘与 NVRAM 各自校验）
  - 目标路径已存在（文件或目录）一律拒绝；排他发布（macOS RENAME_EXCL）防止并发覆盖；无强制覆盖选项
  - 未来 Host Only 若启用：只允许固定键集 + “Isolate Guest from Host”，其余网络键一律拒绝
state:
  # 不进入 CTFLab 运行状态文件；导出是离线操作，不占用实验端口
  # 结构状态（fixture.structure_status=complete-required-keys）：只描述必需段/必需键已按源码补齐
  # 运行状态（清单 runtime_status）：导出时为 e2e_scope/e2e_status=not-run-at-export；
  #   E2E 后由验证记录补记为 static-console-and-isolation / passed-with-scope-limits（x86_64 靶机包），
  #   动态分辨率取值 not-tested-for-x86-fixed-display 或 unstable-after-reboot-not-guaranteed；
  #   补记只写运行结论与磁盘的 E2E 后哈希，不改动任何离线导出字段
```

### 2.4 最小实现切片

1. [已实现] 内置 fixture 的脱敏结构与本机 UTM 4.7.5 的**关键启动与显示字段**静态对齐
   （`tools/ctflab_utm_fixture.json`，版本与 SHA-256 登记在 `tools/ctflab_utm.py`），
   严格键白名单重建、占位符白名单校验；结构状态 `complete-required-keys`
   （只描述必需段/键，运行验收状态独立，见第 5、6 条）；
2. [已实现] `utm-export`：基盘 `base_sha256` 与 UEFI NVRAM `uefi_vars_sha256` 登记核对、
   RAW NVRAM → QCOW2 `Data/efi_vars.fd` 转换、磁盘与 NVRAM 各自 `qemu-img info`/`check`、
   排他发布（临时 `.utm` 目录 → 最终名称，macOS `RENAME_EXCL`）、输出覆盖保护与本次失败清理；
3. [已实现] 单元测试（`tools/tests/test_ctflab_utm_export.py`、
   `tools/tests/test_ctflab_import_integrity.py`）：golden 结构、Display 单元素数组、
   MemorySize(MiB)、Target=virt、CPU=default、Data/data.qcow2、InterfaceVersion、
   UEFI/Hypervisor/无附加参数、Network=[]、ClipboardSharing=false、无自定义状态键；
   基盘完整性（修改后必须拒绝、旧记录明确拒绝、compare 补登记）；NVRAM（缺失/哈希不符/
   转换失败/格式错误/check 失败/输入未变化/成功产出）；排他发布与并发创建不覆盖；
   导入不得直接登记未验证的既有基盘；清单无绝对路径；真实 qemu-img 管线；
4. [已实现] 离线基盘前提记录：`guest_agent_prerequisite` 标记 `not-verified-offline`，
   `utm_e2e_required` 列出待办；不声称图形会话 agent 已连接；
5. [冷启动/图形登录通过；剪贴板负向与网络隔离通过；动态分辨率重启后复测失败；
   来宾内正常关机通过；Smoke/Basic 已交付（x86_64 BIOS 变体，两包 E2E 通过并各有独立验证记录）]
   2026-09-14 首次真实 E2E：R1 包
   （`CTFLab-Kali-E2E-20260914`）因缺必需段/键被 UTM 4.7.5 以“配置无效”拒绝（失败记录
   `E2E-FAILURE-2026-09-14.md`）；按上游 v4.7.5 源码补齐全部必需段与必需键后导出 R2
   （`CTFLab-Kali-E2E-20260914-R2`），UTM 成功导入/解析（截图 `import-accepted-R2.png`，
   路径仍指向独立测试目录、未复制进 UTM 库）。
   同日完成一次冷启动与图形登录验收：UTM 启动 R2 → lightdm 图形登录界面 → 以 kali 用户
   登录 → XFCE 桌面出现（菜单可交互）；QEMU 进程参数确认 `-nic none`（无网卡）、使用 R2 包内
   `Data/data.qcow2` 与 `Data/efi_vars.fd`、`virt + hvf`、4 核/5120MiB、新生成 UUID。
   证据：`step2-boot-01.png`（登录界面）、`step2-boot-03-desktop.png`（桌面）、
   `step2-utm-status.png`（UTM 状态=已启动、库中无 R2 副本）、`step2-evidence.json`。
   同日会话内完成动态分辨率初测（三档窗口尺寸）：窗口 1280×840 → 来宾 `xrandr` 当前模式
   1280x800；窗口 1000×660 → 1000x620；窗口 800×640 → 800x600；窗口 1416×900 → 1416x860
   （现场观察；模式为真实切换而非缩放，证据 `step4-size-*.png`）。来宾内确认 agent transport
   存在：`/dev/virtio-ports/com.redhat.spice.0` 与 `org.qemu.guest_agent.0`，`spice-vdagent`
   与 `spice-vdagentd -x` 均在运行。
   发现两点：尺寸切换有数秒延迟，过渡期 UTM 会临时缩放旧画面或黑屏；较快连续调整窗口尺寸
   两次导致 UTM 显示端卡死全黑（`step4-display-stall-black.png`），一次经按键+等待恢复、
   一次需主机侧重启才恢复。
   **阻塞**：本会话后续宿主 macOS 进入锁屏，GUI 自动化无法继续；来宾重启/正常关机复测、
   剪贴板负向、网络隔离、重启后动态分辨率复测均未完成（见
   `step3-4-session-status.json`）。R2 虚拟机仍在运行、未关机，未删除任何包。
   同日后续（第二轮会话）：完成剪贴板负向（见第 6 条补记）与网络隔离（见第 7 条补记）。
   **动态分辨率重启后复测失败**：窗口 1288×845（来宾 1288x805）→ 改为 1000×660 后 60 秒以上
   来宾未跟随，随后 UTM 显示转黑且键盘输入不再进入来宾；恢复窗口后显示曾短暂恢复，再次改为
   1100×720 又立即卡黑，第二次恢复未成功。失败记录与截图：
   `~/Downloads/ctflab-utm-e2e-20260914/step4-postreboot-failure.json`、
   `step4-postreboot-wedge-2.png`、`step4-postreboot-recovery.png`。对照：重启前同一包曾在三档
   尺寸下真实验证跟随（`step4-size-*.png`）。因此在 UTM 侧该动态分辨率路径仍不稳定，路径 A 保持
   “部分验证”，不得宣称动态分辨率已支持。
   **卡死恢复与正常关机（同日晚间，按用户约束仅操作 R2）**：保留黑屏现场（截图、AX 窗口状态、
   进程命令行、错误日志）后，只读检查发现 `utmctl` 在本环境不可用（Apple Events -1743，且外部
   打开的包不在其列表）；改用 UTM 单 VM 的“虚拟机 → 电源”菜单：先发送“请求关闭电源”（ACPI），
   来宾因显示卡死无法确认 XFCE 关机框而未完成；经确认进程 91580 命令行属于 R2 后执行单 VM
   “强制关机”（记录：此为强制停止）；随后重新打开 R2 包，校验 config.plist 哈希、两盘 qcow2
   与虚拟容量均与操作前一致，显示恢复为登录界面；登录桌面后执行来宾内 `sudo poweroff`，QEMU
   在 5 秒内退出、无残留进程，停止后 `qemu-img check` 两个盘均为 ok；全程未重启 UTM、未触碰
   正在运行的 Linux VM（其进程 60371 始终存活）。证据：
   `~/Downloads/ctflab-utm-e2e-20260914/wedge-scene/`（含 final-integrity.txt、
   final-stopped-main-window.png、r2-process-identity.txt）。
   后续验收清单（在导出包启动后执行，写入验证记录才算交付）：
   UTM 打开包 → 启动 → 来宾图形会话中 `spice-vdagent` 进程运行且 agent 已连接 → 至少两种
   窗口尺寸下实际 `xrandr --current` 模式跟随（这是动态分辨率的唯一证据）→ 宿主/来宾剪贴板
   双向负向（英文、中文、多行哨兵均不泄漏，Clipboard Sharing 已关闭）→ 网络三层隔离
   （无 WAN 出口、无物理 LAN 可达、无法访问 CTFLab 实验网）→ 关闭并删除包后无残留。
   在任何证据记录在案之前，不得对外称动态分辨率就绪；仅有 `zoom-to-fit`、仅
   `spice-vdagentd active` 或仅离线基盘前提都不算证据。
6. [已交付：x86_64 BIOS 变体（Smoke / Basic Pentesting 2）] `utm-export` 新增
   x86_64 + BIOS 支持（`Target=pc`、`CPU=qemu64`、VGA 固定显示、IDE/SCSI 磁盘、无 NVRAM），
   两包各自独立输出目录、唯一命名，未覆盖或改动用户已有虚拟机。每包交付 `.utm`、SHA-256
   （`SHA256SUMS` 校验当前包、与 `sha256_after_e2e` 一致；`SHA256SUMS.at-export` 只是导出时的
   历史记录，不能对 E2E 后可写盘执行校验）、脱敏 README、独立验证记录。E2E 全通过：
   UTM 4.7.5 导入/解析（状态“已停止”）、冷启动到控制台登录界面（Alpine、Ubuntu 16.04）、
   控制台输入回显、UTM 菜单“请求关闭电源”（ACPI）正常关机（来宾 ext4 `s_state` 干净卸载、
   `qemu-img check` 通过、`config.plist` 哈希未变）、`-nic none` 与 `Network=[]` 隔离核对；
   两包均为固定显示（`DynamicResolution=false`），不涉及动态分辨率，也不作相关声明。
   **范围与元数据（两包一致）**：`e2e_scope=static-console-and-isolation`、
   `e2e_status=passed-with-scope-limits`、`dynamic_resolution=not-tested-for-x86-fixed-display`；
   磁盘哈希分列 `sha256_at_export` 与 `sha256_after_e2e`（包内盘可写，启动/关机会改哈希，不得混用）；
   清单说明（逐字）：本清单记录离线导出结果；静态控制台 E2E 结果以独立验证记录为准。
   该包已验证导入、冷启动、控制台交互、正常关机和无网卡隔离，但不构成动态分辨率或联网靶场验收。
   两个包的交付定位是“可在 UTM 4.7.5 中导入与启动的离线控制台镜像包”，不是已接入 Kali 的联网靶场。
   显示稳定性的既有结论不变：**重启后复测失败，显示链路不稳定；当前包仅保证固定显示可用。**
   （历史说明：更早交付的 Kali R2 清单仍是 schema 2 的原始失败现场证据，保留原样不改写；
   重新导出时按 schema 3 生成。）

### 2.5 并发与权限边界

- CTFLab 的操作锁只序列化本工具自身的导入/导出/启动/停止/重置等操作，**不约束输出目录中
  外部进程的并发创建**；对抗外部并发依赖排他发布（macOS `renameatx_np(RENAME_EXCL)`）
  在发布点返回 `EEXIST` 而非覆盖，构建期与发布前的存在性检查只提供更早的清晰报错；
- 非 macOS 平台没有 `RENAME_EXCL` 时退化为“先检查后 rename”，存在极小的并发覆盖窗口，
  跨平台运行时（Phase 3）必须重新实现等价机制；
- 基础镜像发布同样使用排他重命名；登记完成后基盘设为只读（0444），导出与运行都以只读
  方式使用，overlay 不写回基盘。

## 3. 路径 B：将来分发带 SPICE 的 QEMU 与本地 SPICE 客户端

### 3.1 形态

- 随 CTFLab 分发（或在用户显式确认后引导安装）带 SPICE 的 QEMU 构建与本地 SPICE 客户端，
  作为**可选显示后端**；Cocoa 仍是默认显示路径（未传显示参数时的唯一行为）；
- 动态分辨率由来宾 `spice-vdagent` 的 monitors config 能力驱动，因此**无论是否开启剪贴板，
  都必须保留唯一的 virtio-serial + spicevmc agent transport**（这是分辨率跟随的前提，
  不是剪贴板开关）；文本剪贴板仅在显式 `--clipboard` 时启用，并复用同一条 spicevmc 通道
  （替代当前 `qemu-vdagent` chardev，二者不能同时占用同一来宾端口）；
- 生命周期、overlay、实验网语义与现在完全一致，`stop/status/reset` 行为不变。

### 3.2 硬性要求

- **能力探测与失败语义**：启动前探测 QEMU 是否支持 spice 显示后端与 spicevmc/virtserialport，
  以及本地客户端可执行文件是否存在。用户**显式请求** spice 时，任一缺失必须在启动前明确报错
  并停止（不启动虚拟机、不悄悄回退 Cocoa）；只有**未传显示参数**时，默认 Cocoa 路径才保持不变；
- **本机端点 + 每次运行本地鉴权（两种模式互斥，不叠加要求）**：仅本机端点不足以阻止同机
  其他进程，必须叠加每次运行的本地鉴权；按实现选型二者之一：
  - **UNIX socket 模式（优先）**：命令使用 `unix=<socket 路径>`，socket 位于权限 0700 的
    runtime 目录；不开放 TCP，因此该模式不要求也不应出现 `addr=127.0.0.1`/`port=`；
  - **TCP 模式（回退）**：命令必须包含 `addr=127.0.0.1,port=<受控端口>`；禁止裸 `-spice`
    与 `0.0.0.0`；必须有每次运行随机生成的 ticket/secret，且不得出现在进程参数与状态文件
    明文中（经 0600 受限文件或文件描述符传递，运行结束即失效）；端口来自与 QMP/实验端口
    同一受控范围并写入运行状态；
  E2E 必须包含“未授权本地客户端无法连接”，并按所选模式分别验证；
- **保留 Cocoa 默认**：不传新选项时命令与现状一致；`zoom-to-fit` 保留但仍称缩放；
- **剪贴板按 `--clipboard` 条件开关（分层控制）**：动态分辨率所需的 agent transport 始终
  保留；未传 `--clipboard` 时：SPICE 侧 `disable-copy-paste=on`、`disable-agent-file-xfer=on`，
  受控 SPICE 客户端也关闭 clipboard sharing，不启用任何剪贴板方向；传入 `--clipboard` 时：
  `disable-copy-paste=off`（或省略），允许文本剪贴板，`disable-agent-file-xfer=on` 仍保留。
  负向 E2E 必须在 agent transport 存在的前提下验证未授权时英文、中文、多行文本双向均不泄漏；
  任一层不能证明隔离，则**不得实现路径 B**；
- **范围限制**：仅允许 `kali-arm64`；靶机 profile（smoke、basic-pentesting-2 等）一律拒绝，
  并有对应的拒绝测试；
- **前置 PoC（独立门槛）**：自管 QEMU + SPICE 的图形设备与客户端组合必须先做独立 PoC；
  UTM 的 `virtio-gpu-pci` 动态分辨率结果不能直接套用，PoC 通过前不进入实现；
- **分发边界**：QEMU 构建与 SPICE 客户端的许可、体积、签名、SBOM 属于 Task 6 打包范畴；
  在此之前只做本机能力探测与手工 PoC，不分发二进制、不写入任何发布渠道。

### 3.3 CLI/API（已实现能力门禁；运行时仍需 SPICE 构建）

```yaml
# 接口：可选显示后端（默认 cocoa，行为不变）
flag: display
usage: run <profile...> [--display <cocoa|spice>]
allowed_profiles:
  - kali-arm64        # 靶机 profile（smoke、basic-pentesting-2 等）一律拒绝
behavior:
  cocoa: 现状；本地窗口；zoom-to-fit 缩放；不是动态分辨率
  spice: 需能力探测通过；本机端点 + 每次运行本地鉴权；由受控 SPICE 客户端显示；
         agent transport 始终保留；剪贴板按下方 clipboard 条件开关
state:
  display_backend: cocoa|spice
  spice_endpoint_unix: unix=on,addr=<runtime_dir>/spice.sock   # QEMU 11.x 语法；目录 0700；不监听 TCP
  spice_endpoint_tcp: addr=127.0.0.1,port=<受控端口>    # 回退；必须带每次运行鉴权
  spice_auth: unix-socket-0700|per-run-ticket          # ticket 不落进程参数与状态明文
  spice_flags_without_clipboard: "disable-copy-paste=on,disable-agent-file-xfer=on"
  spice_flags_with_clipboard: "disable-copy-paste=off,disable-agent-file-xfer=on"
  spice_probe:                        # 探测结果与失败原因，供 status/doctor 展示
    spice_display: true|false
    spicevmc: true|false
    client: true|false
probe:
  - qemu -display help 输出包含 spice 或 spice-app
  - -chardev spicevmc 可用（virtserialport 可用）
  - 本地客户端（例如 remote-viewer）存在于 PATH；未传 `--clipboard` 时受控启动方式强制
    关闭 clipboard sharing，传入时仅允许文本方向
failure:
  - 显式请求 spice 且探测失败：启动前报错退出，列出缺失项与安装提示；不自动回退 Cocoa
  - 未显式传入显示参数：不执行探测，不改变任何现有参数（默认 cocoa）
```

### 3.4 磁盘只读 / overlay / 隔离网络边界

- 磁盘与 overlay：与现状完全一致（不可变基础镜像 + 每次运行 overlay），SPICE 不接触磁盘层；
- 网络：SPICE 只提供显示通道；剪贴板能力在未授权时逐层关闭（服务端参数 + 客户端），
  agent transport 本身仅服务于显示/分辨率；端点必须仅限本机：UNIX socket 模式使用 0700
  runtime 目录下的 socket（无 TCP 监听），TCP 模式仅允许 `127.0.0.1` 且带每次运行鉴权；
  不改变实验网拓扑，不为来宾增加任何网络设备；测试按所选模式分别断言不存在非本机监听；
- 威胁模型：脆弱靶机（x86 目标）不使用 SPICE 显示，且路径 B 只允许 `kali-arm64`
  （延续“剪贴板等通道只对 Kali 图形模式开放”的既有约束）；SPICE 能力、端点与禁用标志
  写入状态文件（ticket/secret 不落明文），供 `status` 展示与清理。

### 3.5 最小实现切片

0. [已实现门禁] 显式请求时探测 QEMU 的 spice 显示后端、`spicevmc`、`virtserialport` 与本地客户端；
   任一缺失在启动前失败，不创建实验网或虚拟机；
1. [已实现] 显示后端选择与命令拼装：本机 UNIX socket、0700 runtime 目录、唯一 virtio-serial +
   spicevmc agent transport、`--clipboard` 分层开关、仅 `kali-arm64`；
2. [已实现] 显式请求失败语义与状态记录；默认 Cocoa 命令保持不变；
3. [部分验证] 自管 QEMU + SPICE 客户端组合已纳入独立验收 App，并完成 UNIX socket 连接、Kali
   `spice-vdagent`、重启后恢复与两种窗口尺寸的实际 `xrandr` 跟随；未授权客户端/剪贴板负向 E2E 尚未完成；
4. [后续任务] 补齐剪贴板与未授权客户端边界，并更新课堂分发基盘中的 XFCE 显示适配。

## 4. 路径对比

| 维度 | A：独立 UTM 导出 | B：带 SPICE 的 QEMU + 本地客户端 |
|---|---|---|
| 动态分辨率证据 | UTM 显示机制 PoC 已验证（2026-09-14）；Smoke/Basic（x86_64 固定显示）的静态控制台 E2E 已在限定范围内通过；Kali 包动态分辨率重启后复测失败，仅保证固定显示可用 | 带 SPICE QEMU + 受控客户端 + XFCE 适配已验证两档窗口的实际 `xrandr` 跟随；新版分发基盘已包含适配 |
| 网络默认与隔离 | 默认无网卡；未来 Host Only 需固定键集 + “Isolate Guest from Host” | 保持 CTFLab 实验网与现有隔离语义 |
| 剪贴板默认 | 关闭 UTM Clipboard Sharing；宿主/来宾双向负向 E2E | agent transport 始终保留；按 `--clipboard` 条件开关（未授权禁用复制粘贴/文件传输 + 客户端关闭共享；授权允许文本） |
| 端点与鉴权 | 不适用（UTM 管理） | 两种互斥模式：UNIX socket（0700 目录，优先）或 TCP `127.0.0.1` + 每次运行鉴权 |
| 前置条件 | 离线基盘前提记录 + 导出后 UTM E2E | 图形设备/客户端组合独立 PoC 通过 |
| 磁盘边界 | 独立副本；来源只读 + 哈希复核 | 现有 overlay 语义不变 |
| 依赖 | 用户已安装的 UTM | 需带 SPICE 的 QEMU 构建 + 本地 SPICE 客户端 |
| 打包/签名 | 不涉及二进制分发 | 依赖 Task 6（许可、SBOM、签名、公证） |
| CLI 影响 | 新增独立导出子命令，不触碰 run 路径 | 新增显示选项 + 能力探测 + 状态字段 |
| 生命周期 | UTM 管理，CTFLab 不介入 | CTFLab 管理，行为不变 |
| 适用定位 | 显示体验导出 / Phase 0 适配 | 集成式长期方案 |

## 5. 测试矩阵

单元测试（已补入 `tools/tests/`）：

| 用例 | 断言 |
|---|---|
| A：fixture 与白名单 | fixture 哈希与登记值一致；生成配置只允许白名单键，无网络/剪贴板共享/共享目录/附加参数 |
| A：无网卡默认 | 导出配置不含任何 Network 条目；模板试图注入的网络配置被拒绝 |
| A：剪贴板共享默认关闭 | 配置不含 UTM Clipboard Sharing 与共享目录相关键 |
| A：Host Only 边界（未来） | 只允许固定 Host Only 键集 + “Isolate Guest from Host”；拒绝 Shared/Bridged/端口转发；来宾无法访问宿主 Host Only IP（E2E） |
| A：覆盖保护 | 目标已存在（文件或目录，含已有 `.utm`）一律拒绝，不写入；无强制覆盖 |
| A：只读来源 | 导出前后来源镜像 SHA-256 不变 |
| A：架构边界 | 仅 aarch64+UEFI（virtio）与 x86_64+BIOS（IDE/SCSI）两种变体；其余架构/固件组合、总线不匹配（含 SATA 之类不存在的枚举值）均明确拒绝并给出说明 |
| B：探测三态 | 支持 / 不支持 / 命令异常分别返回预期结果 |
| B：显式请求失败不静默回退 | 显式请求 spice 且探测失败时启动前报错，进程不启动 |
| B：仅 kali-arm64 | 靶机 profile 请求 spice 显示被明确拒绝 |
| B：默认命令不含 SPICE | 不传显示参数时命令与现状一致，无 `-spice`，仍为 Cocoa |
| B：agent transport 保留 | 两种剪贴板状态下都含唯一 virtio-serial + spicevmc transport |
| B：未授权剪贴板命令 | 未传 `--clipboard` 时命令含 `disable-copy-paste=on` 与 `disable-agent-file-xfer=on`，不启用任何剪贴板方向 |
| B：已授权剪贴板命令 | 传入 `--clipboard` 时命令为 `disable-copy-paste=off`（或省略），保留 `disable-agent-file-xfer=on`，文本方向可用 |
| B：UNIX socket 模式 | QEMU 11.x 命令含 `unix=on,addr=<0700 目录下 socket>`，且不含 `port=`（不监听 TCP） |
| B：TCP 模式（回退） | 命令含 `addr=127.0.0.1,port=<受控端口>`，不含 `0.0.0.0` 或裸 `-spice`；每次运行 ticket 不出现在命令参数与状态明文 |
| B：剪贴板通道唯一 | `--clipboard` + spice 复用同一 spicevmc 通道，不创建第二个 vdagent 通道 |

手工 E2E（写入验证记录；正向窗口跟随已完成，边界项仍单独保留）：

| 路径 | 步骤 |
|---|---|
| A | UTM 打开新包 → 启动 → 来宾图形会话中 `spice-vdagent` 进程运行、agent 已连接 → 两种窗口尺寸下实际 `xrandr --current` 模式跟随（动态分辨率唯一证据）→ 宿主/来宾剪贴板双向负向：英文、中文、多行哨兵均不泄漏（Clipboard Sharing 已关闭）→ 网络三层隔离：无 WAN 出口、无物理 LAN 可达、无法访问 CTFLab 实验网（`192.168.242.0/24` 不可达、Mac 无端口映射可达）→ 删除包无残留 → 用户已有 UTM 虚拟机前后哈希一致 |
| B（正向：UNIX socket 模式） | 客户端经 `unix:<runtime_dir>/spice.sock` 连接（目录 0700、无 TCP 监听）→ 两种实际窗口尺寸下 xrandr 跟随及冷启动恢复已验证 → `stop --all`、默认 Cocoa 与 `--headless` 回归已验证；`--clipboard` 正向专项仍待补齐 |
| B（正向：TCP 模式回退） | 客户端经 `127.0.0.1:<受控端口>` + 每次运行鉴权连接 → 窗口缩放/全屏时 xrandr 跟随 → `lsof -iTCP` 无非回环监听、无未授权连接 → 当前未实现/未验收 TCP 回退路径 |
| B（负向：未授权剪贴板 + 未授权客户端） | agent transport 存在、未传 `--clipboard`：宿主侧放入英文、中文、多行哨兵文本，来宾侧确认剪贴板无内容；来宾侧写入哨兵文本，宿主剪贴板哈希不变；受控客户端 clipboard sharing 已关闭；另一未授权本地客户端无法连接端点 → 任一层失败即判定隔离不成立，不得实现路径 B |

回归要求：两条路径的改动都不得改变默认 `run` 命令、`stop/reset` 语义、PCAP 与健康检查行为；
本次完整回归（2026-09-16 复核，360 项，5 项按历史 UTM 目录缺失规则跳过）全部通过。

## 6. 推荐路径

- **近期（已实现最小切片）**：路径 A 的 `utm-export` 已实现并通过单元测试（2026-09-14），
  定位为“显示体验导出”能力：复用已通过 PoC 的 UTM 显示机制（Smoke/Basic 的静态控制台 E2E 已在
  限定范围内通过；Kali 包的动态分辨率重启后复测失败，仅保证固定显示可用；该项待修复后按 2.4 重新验收），
  不动运行器、不动默认 QEMU 命令；导出包默认无网卡，不接入实验网。
- **中期（依赖 Task 6）**：路径 B 的自管 QEMU + SPICE 客户端组合已通过 UNIX socket 连接、窗口跟随
  和冷启动恢复验证；仍需完成本地鉴权与三层剪贴板负向 E2E，并更新课堂分发基盘。全部通过前，显示
  后端不进入默认路径，文档与 CLI 只能把它标为显式可选能力。
- **两条路径的共同底线**：默认 Cocoa 与 `zoom-to-fit` 现状不变；
  在对应路径的 E2E 验收记录给出之前，不得声明动态分辨率已支持。

## 7. 明确不做

- 不新增 `--dynamic-resolution` 之类的假开关（只做缩放或固定 `xres/yres` 的选项不得命名为动态分辨率）；
- 不向现有默认 QEMU 命令加入 `-spice`，不改变默认 Cocoa/`zoom-to-fit` 行为；
- 不把窗口缩放或固定 `xres/yres` 称为动态分辨率；
- 不修改、不重命名、不移动用户已有 UTM 虚拟机；导出只写新目标路径；
- 不接受任意用户 `.utm` 模板；不向导出包加入网卡、共享目录、端口转发，也不允许
  Shared/Bridged 网络或继承用户模板网络；不启用 UTM Clipboard Sharing；未来 Host Only
  必须启用 “Isolate Guest from Host” 并证明来宾访问不了宿主 Host Only IP；
- 不提供输出覆盖，也不存在“本工具生成标记可复用”的例外；
- 剪贴板不做隐式开关：agent transport 始终保留；未授权时禁用复制粘贴与文件传输（含客户端），
  授权时才允许文本方向；任一层无法证明未授权隔离就不实现路径 B；
- 不允许路径 B 用于 `kali-arm64` 之外的 profile；不把 UTM 的 `virtio-gpu-pci` 结果直接
  套用到自管 QEMU + SPICE（自管路径的窗口跟随已单独验收，剪贴板和鉴权边界仍待验收）；
- 不允许 SPICE 以非本机方式暴露：TCP 仅 `127.0.0.1` + 每次运行鉴权，UNIX socket 仅
  0700 runtime 目录；不以 VNC 作为默认显示路径；
- 本次路径 B 新增的是显式 `run --display cocoa|spice` 能力门禁与 SPICE 命令构造；默认不传参数时
  仍是 Cocoa，绝不静默回退；SPICE 二进制与客户端只在经过许可/SBOM/签名核验的可选 runtime 中进入验收包；
- 本轮不改变 UTM 后端；SPICE 后端与可选 runtime 配合 XFCE 适配已完成两档窗口跟随，
  旧分发基盘未更新，当前不宣称所有既有分发包的动态分辨率已交付。

## 8. 仍需决策的问题

1. 路径 A 的交付归属：纳入第一阶段验收，还是作为 Phase 0/Phase 2 的外部适配能力？
   （当前设计：导出包默认无网卡、不接入实验网；未来如确需网络，只允许 Host Only + 来宾/宿主隔离。
   最小切片已实现，交付归属与 E2E 安排仍待确定。）
2. 路径 B 的 QEMU 构建来源：自行构建 `--enable-spice`，还是采用可再分发的既有构建？
   （许可、版本固定、SBOM、公证成本不同。）
3. 本地 SPICE 客户端选型（例如 Homebrew `virt-viewer`/`remote-viewer`，或自研嵌入），
   CTFLab 是否允许引导安装？
4. 端点模式选型：UNIX socket（0700 目录，优先）与 TCP `127.0.0.1` + 每次运行 ticket 两种
   互斥模式，按客户端兼容性确定默认。
5. 动态分辨率验收的量化标准：窗口尺寸序列、跟随容差、全屏进入/退出、多显示器场景。
6. SPICE 模式的剪贴板开关是否复用既有 `--clipboard`（当前设计：是；未传即禁用复制粘贴与
   文件传输，授权才允许文本方向，`disable-agent-file-xfer=on` 始终保留）。
