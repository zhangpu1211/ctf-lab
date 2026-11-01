# Mac通用v2运行链、原生工作区与完整运行时（2026-10-27）

本轮是未打包源码接入，实际结果以状态第104节和`output/mac-generic-20261026/final-evidence.json`为准。保留原Mac固定场景链、单节点功能和原更新器，不自动迁移用户状态或替换旧App。全部43项及G0/G1仍未关闭；源码支持不等于真实来宾、课程、跨平台或发布验收。

## 1. 本批接入内容

- 通用QemuDriver新增明确的`host: darwin-arm64`配置。ARM64仅UEFI/VirtIO，生成virt/HVF/host CPU、VirtIO GPU/RAMFB及USB输入；x86仅BIOS/IDE或VirtIO，由同一固定运行时内的x86 QEMU使用TCG。含任意x86节点的整课启动必须明确`allow_emulation=true`，否则首个节点启动前拒绝，避免先起ARM再遇未确认仿真。
- 运行时清单覆盖整个指定`runtime_root`，不只哈希bin目录：固定二进制在bin内，固件code也必须在该根内；拒绝越界、链接及清单漂移。生成参数仍为白名单，网络仅回环socket链路，每网段恰好两个成员。其他硬件组合、多成员交换网及Intel Mac不自动降级或猜测支持。
- UEFI NVRAM从独立只读模板复制到各代次。launch记录与恢复绑定核对NVRAM设备/inode、固件声明、二进制、计划及参数；允许本代次NVRAM正常变化，不允许换盘/换NVRAM冒充原实例。固件漂移拒绝新启动，已启动实例仍可沿原身份/认证通道正常停止，不为检查当前固件而阻断既有正常关机。
- Darwin进程身份由libproc的PID、UID/真实UID、启动时间与可执行路径采集，并混入本次启动会话UUID；前后采样拒绝漂移，路径按大小写精确匹配。kqueue先注册NOTE_EXIT、再次核验身份后才写ready。退出只证明同一已绑定内核进程退出，未知退出码保持null，绝不推测正常关机完成。
- 原Swift“本机场景…”新增“新版通用v2”：清单设计和双网连接、逐项选择基盘/NVRAM模板、选择私有运行配置、建立/列出实例、读状态、准备、明确仿真启停、保留旧代次重置、恢复、取消、两种准备恢复、显示请求和退出观测恢复。按配置开放来宾网络/DNS/时间、容器及离线分析入口。真实服务/隔离仍需验收，不能把“进程运行”写成可用。
- 固定`generic-client`标准输入桥接把根限制在当前状态根的`generic-instances/<UUID>`，拒绝任意命令、任意运行根与跨实例请求；状态/列出/预览不自动配置或启动。配置重试只可补齐未进入代次的缺失登记，输入必须与原配置完全一致；既有半写文件、磁盘、失败现场不覆盖、不删除。
- 导出使用校验后的源清单，保留`derived`语义，不把实例化MAC静默变成模板固定地址；已有输出不覆盖。未知回复不自动重试，当前上下文切换拒绝迟到状态。

## 2. 管理员运行配置

操作对象是管理员明确提供的许可资产、固定运行时和私有配置，不能把课程包中的任意宿主参数当作配置授权。配置文件按私有文件保存（0600）；清单中的标识应与资产、节点、网络映射完全相同。以下尖括号均为占位，必须替换后才能使用。

```json
{
  "host": "darwin-arm64",
  "runtime_root": "/absolute/runtime",
  "binary": "/absolute/runtime/bin/qemu-system-aarch64",
  "emulator": "/absolute/runtime/bin/qemu-system-x86_64",
  "inventory": "/absolute/private/runtime-inventory.json",
  "firmware": {
    "arm": {"code": "/absolute/runtime/share/qemu/edk2-aarch64-code.fd", "sha256": "<真实64位摘要>"}
  },
  "nodes": {"arm": {"qmp": 19000, "vnc": 5900}, "win": {"qmp": 19001, "vnc": 5901}},
  "networks": {"lab": 18001}
}
```

`emulator`只在有x86节点时必需。`firmware`恰好覆盖所有ARM节点，x86 BIOS节点不能伪填UEFI。全部端口必须独立且在允许范围，探测空闲不等于预留；真正启动仍核验身份/TLS。运行时内容清单写在被采集目录外，且目标必须不存在：

```sh
python3 -I -B tools/ctflab_runtime_inventory.py --root /absolute/runtime --executable bin/qemu-system-aarch64 --output /absolute/private/runtime-inventory.json
```

原Swift面板直接逐项选择基盘和NVRAM模板。CLI/通用桌面导入可提供资产映射与NVRAM映射JSON：各键为清单资产/UEFI节点标识，各值为对应源文件绝对路径；`ctflab_qemu_driver.py init`新增`--nvram`。原Windows/Linux BIOS导入仍不要求NVRAM文件。

## 3. 配额衔接

若原Mac状态根已经显式登记第99节的专用APFS配额描述，固定桥接把已核验的描述嵌入新通用实例配置。代次复制/提交前、启动、后台执行及运行身份观察继续核验父状态根与卷绑定；拒绝跨出父根、设备/配额/inode漂移。直接宿主配置也只能引用实际覆盖当前实例根的描述，不能借其他目录配额作证明。

此机制不创建卷、挂载、扩容或设置配额；不回收文件。它约束该预配置APFS卷内的数据，不覆盖卷外公共缓存或整个宿主，也不实现Mac CPU/RSS/PID硬限额或Windows完整配额。不能把这些剩余项写成已实现。

## 4. 可选完整Mac运行时构建

原构建默认继续使用历史裁剪策略。仅在管理员提供已准备好的固定Python运行时及许可证清单时启用：

```sh
python3 tools/ctflab.py app build --out /absolute/new-output --python-runtime /absolute/python-runtime --pyyaml /absolute/PyYAML.whl --generic-runtime-manifest /absolute/private/generic-licenses.json
```

此命令为后续构建入口说明，本轮没有执行真实App打包。`new-output`不能覆盖旧包。工具不联网安装、下载Tk、复制系统用户site-packages或更改原更新器。

许可证清单结构为`{"schema":1,"licenses":{...}}`，licenses必须恰好有cryptography、tcl、tk三项，每项必须含`path`（明确提供的文本绝对路径）、`sha256`（真实摘要）、`license`（来源给出的SPDX表达式）。文本及清单均限大小、拒绝重复字段与摘要不符，登记不替代法律/来源审核。

启用后保留Tcl/Tk、tkinter、_tkinter，要求固定运行时已经自带cryptography 46.0.5及所需依赖。用`-I -B`、固定环境隔离加载ssl/cryptography Rust和Tcl/Tk，做内存中的EC密钥生成，核对所有模块及Tcl脚本均来自包内；不创建显示窗口、套接字或VM。随后检查Mach-O相对依赖、记录版本/许可证/哈希到MANIFEST与SBOM，verify再次核验。实际窗口、显示输入、签名、公证、干净机及来宾仍未验。

原裁剪运行时缺依赖时，界面不把入口存在当作能力可用：认证控制依赖缺失时阻止启动，显示依赖缺失时阻止打开显示；设计和离线配置可以保留。模块可定位只是前置检查，不能冒称原生运行验证。

## 5. 证据与继续边界

本轮Darwin内核正向只涉及当前进程和专用普通Python子进程；混合架构整课使用真实SQLite/代次/派生文件/证书，QEMU和QMP为替身。真实VM、镜像服务、SSH、APFS正向限额卷、界面人工交互、最终包和发布状态分别记录，不能合并为实机通过。

不重做Windows Smoke，不停止既有VM、运行实际到期调度、删除用户资产、改宿主网络/卷、提交推送、覆盖旧包或发布；保留原Mac更新器。全43项、G0/G1和集中实机总验收以状态台账为准。
