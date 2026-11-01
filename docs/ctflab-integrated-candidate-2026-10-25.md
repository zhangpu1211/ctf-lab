# CTFLab 跨阶段集成候选与集中验收入口

日期：2026-10-24—25。正式目录 `/Users/pufei/Downloads/ctf-lab`。这是源码候选，包含桌面、后台、分发和集中核对工具；不是完整 Windows 安装资产，也不是全部43项完成。Windows Smoke 基础链路沿用状态第82节的用户实测通过，不要求重复原生基础、显示/键盘、显示重连、关机与原盘核对。

用户明确全部43项继续推进，Windows实测由用户执行，暂没有额外 Kali/Web、Windows/AD 镜像、Linux/SSH环境或签名证书。当前先提供能独立实现的集成，不把仍缺开发的分支统一写成“仅待实测”。本文件的验收入口供后续集中执行，**不要求现在逐项回传，也没有启动总验收**。

## 1. 已接通的实现

| 范围 | 源码入口与实际行为 | 边界 |
|---|---|---|
| W01/W02 监督故障 | `ctflab_supervisor_fault.py`；核对监督器/QEMU/独立观测器身份后，监督器处理一次不可变请求并自行以73退出；请求方预先持有监督器句柄并等待实际退出 | 不结束任意PID，不停止QEMU或观测器；真实Windows QEMU故障恢复仍待验 |
| A03/W03/W04 | `ctflab_desktop_bridge.py`；界面→可信本机主体→LocalService→独立后台执行→ScenarioCoordinator→QEMU | 后台派发意图防止重复点击重建进程；关闭管理窗口不执行停止；运行期间取消只记请求，在安全点处理 |
| W04/T01/T02/U02 | `desktop/` Tauri 2 + React；课程导入、准备/启动/保存停止/重置/取消/恢复、节点显示重连、拓扑、完整清单草稿差异、脱敏预览 | Mac原生编译与浏览器夹具验证不替代Windows界面实测；没有图形拖线编辑、运行中热改或自动上传 |
| W03/W05 | `ctflab_desktop_package.py`、`desktop/Build-Windows.ps1`；固定QEMU与干净独立Python运行时清单、复制后摘要、随包导入探针、NSIS/WebView2离线安装配置 | 需要Windows构建环境及准备好的运行时；未生成Windows最终安装包；来源/依赖闭包/签名不由目录哈希证明 |
| W05 | `ctflab_release_store.py`；Ed25519签名载荷、白名单路径、完整暂存、版本指针原子切换、手动回退、运行时引用与旧版本保留 | 此签名不是Windows Authenticode；只接受既有数据schema 1，不执行未经实现的迁移；版本库暂未接成安装器的自动更新流程 |
| P02/P03/U03 | `ctflab_content_cache.py`、`ctflab_delivery.py`；固定信任根、有效期/单调序号、单HTTPS源、Range续传、摘要后转正、损坏隔离、师生材料与许可分离、回收预览复核 | 下载默认不发生；重定向拒绝；实例创建自动登记受保护缓存引用；实例/旧代次/失败现场引用没有删除协议时不允许解除；密钥轮换与校内镜像运营未完成 |
| L01 | `ctflab_linux_native.py`及通用后端；普通用户Linux x64/KVM、启动时间+boot ID+映像、pidfd独立观测、TLS控制与同一代次逻辑 | Linux原生/KVM和最终运行包未验；独立pidfd只证明退出，不能获取的退出码保留null；Linux监督故障注入入口暂拒绝 |
| O01 | 既有Mac回环交换机 `PcapWriter` 默认64MiB配额、完整记录边界、配额丢帧/snaplen截断计数、采集元数据、实例/代次绑定 | 不覆盖旧捕获；上游丢包/时钟准确性未知；通用socket后端尚未接入捕获，不等于通用O01完成 |
| 集中证据 | `ctflab_acceptance_session.py`；只读快照、故障恢复/停止后继续/整课重置比较 | 比较控制身份、代次、盘身份、原盘摘要；重置检查新基线和旧进度仍在；不自动把网络、来宾或课程判通过 |

## 2. 一次收集源码专项

源码包不含镜像、运行时、私钥或用户日志。解压后使用已有Python及 `cryptography==46.0.5`。完整Windows实测时间确定后，可一次执行：

```powershell
powershell -File .\desktop\Test-Integration.ps1 -Python 'C:\你的独立Python\python.exe' -Results 'C:\CTFLab-Test\results-integration-new'
```

结果目录必须不存在。脚本运行全部列出的专项，分别保存stdout/stderr和实际退出码，并在最后生成summary.json；不会因PowerShell把unittest的stderr包装成NativeCommandError而误判。包含一个新的“Python监督器自行崩溃、子进程和观测器继续”的Windows原生用例，不操作VM。不默认重复第82节已通过的两组原生基础用例。

测试夹具条件跳过保留，特别是Linux原生、无来宾QEMU fixture；不能把summary中退出码0解释为Windows来宾、网络、安装器或全部43项验收通过。无需上传整个运行目录或任何tls目录。

## 3. 监督器故障与重连的集中核对

这一组只在使用**当前源码启动的专用新实例**执行。旧r1已经运行过的worker不会因换了源码就自动更新等待循环。为新实例使用全新运行目录、派生盘和空闲端口；固定QEMU/基盘摘要及清单沿用已核验组合，准备与start参数见包内 `docs/ctflab-windows-test-steps-2026-10-24.md`。不重做基础验收，只需建立本组故障前的运行基线。

先用 `ctflab_desktop_package.py workspace --destination` 创建一个新的私有证据目录，例如 `C:\CTFLab-Test\evidence-integration-new`。以下 `$run` 指该新实例，`$evidence` 指该私有证据目录：

```powershell
python -I -B tools/ctflab_acceptance_session.py checkpoint --kind smoke --run $run --verify-sources --output "$evidence\before-fault.json"
python -I -B tools/ctflab_windows_recovery.py supervisor-fault --run $run
python -I -B tools/ctflab_windows_recovery.py recover --run $run
python -I -B tools/ctflab_windows_recovery.py display --run $run
python -I -B tools/ctflab_acceptance_session.py checkpoint --kind smoke --run $run --verify-sources --output "$evidence\after-fault.json"
python -I -B tools/ctflab_acceptance_session.py compare --expect recovery --before "$evidence\before-fault.json" --after "$evidence\after-fault.json" --output "$evidence\recovery-comparison.json"
```

监督器请求应返回 `supervisor-exited`、73；请求方会先保留该监督器的内核句柄，退出证据写为 `supervisor-fault.exit.json`。超时保留unknown，不结束任何进程、不重试注入。比较器要求QEMU同一身份、相同启动尝试、无新增启动意图、故障作用与监督器实际退出记录相匹配，且原盘摘要复核一致。故障恢复后显示/来宾输入是否保留仍需观察，不由比较器推断。

最后只对这个专用实例执行一次正常关机请求，并核对observer-exit；步骤沿用旧文档第5节，但本组重点是监督器已退出后仍取得匹配的持久退出记录。关机请求无回应或未退出时保留现场，不换ID重发，不按旧PID结束。

通用实例使用 `ctflab_qemu_driver.py supervisor-fault --run $run --node <实际节点>`；快照的kind改为scenario。故障只作用于指定节点的监督器，其余节点的绑定也必须保持不变。

## 4. 通用两节点课程、继续与重置

完整安装资产内，界面可从课程目录、课程ID/精确变体和镜像库导入课程，自动选用随包QEMU及清单、生成回环端口候选。候选探测不称为端口保留；实际启动必须通过实例身份和TLS握手。用户自行准备的课程JSON和资产必须通过现有目录/schema 2校验；不执行课程脚本。

源码开发者也可用主文档中的init→prepare→start。两种控制方式不要同时操作同一实例；桌面契约有自己的代次/revision，绕过契约的CLI写操作可能要求重新恢复核验。桌面附着既有实例仅允许尚未准备代次的新通用实例，不接管旧固定Smoke或用户正在运行的VM。

集中顺序：准备→全部节点启动→显示与课程任务→只读快照→保存停止→再次启动→快照→`compare --expect restart`→保存停止→带源摘要的快照→整课重置→带源摘要的快照→`compare --expect reset`。每个快照和比较输出使用新文件名，不覆盖证据。restart核对同一代次/同一运行盘、不同启动尝试/进程；reset核对下一代次、新基盘副本、原盘摘要及旧进度文件保留。

来宾网络、应通/禁通和服务需要用户提供明确测试地址/协议/端口及合法课程资产；现阶段没有这些输入。不会为凑禁通矩阵扫描真实LAN或互联网，也不把无默认出口的参数计划当成隔离实测。

## 5. Windows安装构建入口

此入口给构建者，不是要求学生安装开发环境。先准备独立、可再分发且许可材料完整的Windows Python运行时（含Tk/SSL/cryptography 46.0.5）与已锁定QEMU目录。不能把用户Home、开发虚拟环境或含无关私人文件的目录当作运行时。构建需要Node/npm、Rust 1.90.0及Windows C++构建工具。

```powershell
powershell -File .\desktop\Build-Windows.ps1 -PythonRoot 'C:\CTFLab-Runtime\Python' -QemuRoot 'C:\Program Files\qemu' -QemuInventory 'C:\CTFLab-Test\qemu-inventory.json' -BuildRoot 'C:\CTFLab-Build-integration-new'
```

BuildRoot必须不存在，且在输入源码和运行时目录之外。脚本创建私有构建根、采集Python清单、核对固定QEMU与原清单、复制运行时、检查复制后的Python依赖加载位置，再构建Tauri/NSIS。WebView2离线安装器在构建时准备并纳入最终安装资产；不表示本机已经构建或做过干净机离线验收。

输出实际安装文件哈希与Authenticode状态。当前没有签名证书，未签名资产只用于封闭测试。程序版本与实验目录分离，构建脚本不删除实验、镜像、旧包或旧构建。版本库的签名验证/回退API有独立测试，但自动安装迁移和更新协调尚未完成，不能据此声称W05整体完成。

## 6. 内容缓存与版本库

`python -I -B tools/ctflab_delivery.py --help`列出显式入口。缓存和版本库必须使用新私有目录。信任根由宿主提供，工具不生成或信任索引附带的新公钥，不下载未知来源。P02索引payload字段为schema、sequence、带时区expires、固定HTTPS source和以SHA-256为键的assets；签名为Ed25519对canonical JSON的签名。asset明确path、size、redistribution和audience，teacher材料不进入student请求。

缓存对象作为GenerationStore来源时，创建实例之前会自动持久登记受保护引用。旧代次和失败现场也依赖这些来源，因此普通unpin拒绝instance-前缀的引用；尚无安全实例删除协议时，宁可保留引用，不自动回收。一般无引用缓存可preview-gc，再以精确预览调用collect；新增引用、文件身份或摘要变化会整批拒绝，实际删除结果逐对象落盘。此实现没有清理现有镜像库。

## 7. 仍需开发及外部验证

全部43项的任务定义不变。当前并未完成：完整G0负向矩阵、Windows最终包/升级迁移/干净机/签名/课堂试点，图形拖线编辑，路由/DNS/时间及网络规则执行，校内镜像服务，Docker宿主/网关/代次整合，Linux最终包，SSH远程/鉴权显示/租约/多人角色/数据通道，E01→E02→E03外部接入，各真实C01—C04/C06/C07课程和隔离分析器。证书续签、后台日志配额也仍有开发工作。

暂缺的镜像、Linux/SSH环境和签名证书已由用户确认为暂无。缺少这些输入阻止对应实测/最终资产，不阻止其他独立开发；不能把上述仍需开发的项目写成已实现。总验收须在实际实现和所需环境齐备后集中进行。

实现依据：[Tauri资源嵌入](https://v2.tauri.app/develop/resources/)、[Windows安装与WebView2](https://v2.tauri.app/distribute/windows-installer/)、[Ed25519校验](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/)、[Linux KVM API](https://docs.kernel.org/virt/kvm/api.html)、[Python pidfd](https://docs.python.org/3/library/os.html)。API文档核对不代替任何平台的实际验收。
