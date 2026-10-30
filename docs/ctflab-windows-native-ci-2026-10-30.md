# Windows原生构建与自动安装检查候选（2026-10-30）

## 当前结果

本机是Darwin arm64；现场UTM仅有停止的Basic/Smoke/Linux条目，没有Windows。本仓库当前没有Actions工作流或自托管运行器。没有启动、停止或修改这些实例。Mac0.1.4已发布，Windows仍无安装EXE。

已准备工作流、固定输入要求、原生检查脚本和本地安全输入测试；**尚未提交到GitHub、未启动云端任务、未生成或安装Windows包**。这是一份待批准执行的具体方案，不是Windows验收结果。

## 拟执行范围

仅向`codex/windows-native-acceptance-20261030`独立分支提交下列5份文件，基于现有远端HEAD创建，不切换本地分支、不将现有未提交代码批量提交、不修改默认分支：

1. `.github/workflows/ctflab-windows-native.yml`
2. `desktop/windows_native_ci.py`
3. `desktop/requirements-windows-native-ci.txt`
4. `tools/tests/test_ctflab_windows_native_ci.py`
5. 本说明。

提交触发该分支的push工作流。采用GitHub临时`windows-2025`主机、60分钟上限、只读contents权限、固定Actions提交、不持久化Git凭据，不使用签名/SSH等自定义secret、不自动发布Release。候选安装器与日志保存为7天Actions artifact，失败亦保留已有日志。仓库当前为公开仓库；不创建或购买付费运行器。

源代码不从旧Git标签自动Source code取得，而是下载已经发布的0.1.4源码快照，固定SHA256 `62e870b6700a83031a3c9f1e4cfbded3207be7d9a839e2ef6d72c200608093fd`，核对每个文件及完整集合再解包。既有0.1.4运行源码不因新增CI而修改。

## 固定输入与流程

- 固定Python3.12.10 x64（固定setup-python Action）、Node22.14.0、Rust1.90.0；实际Windows系统和解释器版本写入证据。
- 从PyPI官方版本元数据核对cryptography46.0.5、cffi2.1.1、PyYAML6.0.3、typing_extensions4.16.0和pycparser3.12的Windows/通用wheel摘要；仅二进制wheel、禁止源码构建及自动解析额外依赖。
- 运行时只从已准备Python复制需要的标准库、DLL、Tcl/Tk与许可证；不把pip中32位辅助启动器作为x64运行时依赖。来源目录不删除、不修改。
- QEMU采用此前用户已测的Stefan Weil 20260811固定构建。下载前述[官方入口](https://www.qemu.org/download/)指向的[维护者版本目录](https://qemu.weilnetz.de/w64/2026/)文件，以[上游SHA512](https://qemu.weilnetz.de/w64/2026/qemu-w64-setup-20260811.sha512)核对，再7z解包；不运行QEMU安装器、不注册系统QEMU。实际x86_64二进制须保持既有`47d57a60...`完整摘要，不改常量绕过。
- 先运行Windows原生基础与控制测试（自有测试进程/替身，不重做Smoke或运行真实VM），再调用0.1.4原构建脚本。静态PE依赖、清单/载荷、Python包内来源或构建任一步不符即失败，不用跳过来记通过。
- 安装到本轮临时独立目录，核对实际安装后的完整runtime集合与暂存清单；只启动本次安装的GUI并观察自有PID可见顶层窗口，再发送WM_CLOSE请求正常退出。失败不强杀或继续卸载。
- 仅在两类真实应用数据根不存在时，创建本轮私有保留标记；若已有数据则拒绝安装/卸载。不改已有ACL。卸载本轮程序后核对程序移除、标记原字节保留，不删除这些标记或用户数据。

所有安装/卸载只在上述临时云主机中执行，不在用户Mac、现有虚拟机或未授权远端设备上运行。

## 判据与尚未覆盖

成功构建、安装后载荷/导入、实际窗口观察、正常退出、卸载和数据标记保留分别记录，任一步失败保留现场。窗口出现只证明入口可启动，不证明按钮/原生IPC、真实显示、课程或来宾通过。

GitHub Windows2025是构建/自动检查环境，不是Windows11用户设备；不能据此关闭Windows11人工桌面、干净机、WHPX/真实VM、图形显示、VPN/睡眠、迁移回退、合法课程/至少5人试点、Authenticode签名或G0/G1。签名证书尚未配置，即使生成未签名候选也只供明确范围测试，不自动公开发布安装器。

官方依据：[Tauri Windows安装器](https://v2.tauri.app/distribute/windows-installer/)、[GitHub事件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)、[工作流权限](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions)。首次新工作流走受限分支push触发，不依赖默认分支尚不存在的workflow_dispatch。

## 本地验证与继续入口

`python3 -B -m unittest discover -s tools/tests -p test_ctflab_windows_native_ci.py -v`检查归档路径穿越、大小写别名、链接、额外/缺失文件、摘要变化、源目录复制保全、下载摘要拒绝及非Windows不执行边界；本轮12项通过。对实际已发布源码ZIP运行`verify-snapshot`验证316份载荷。工作流解析/Action固定提交与权限、脚本语法另留本轮证据。没有重跑无关全仓回归或宣称Windows原生通过。

需要用户新增确认的动作是“仅提交上述5文件到独立CI分支并启动临时Windows任务”。依据项目AGENTS.md阶段启动第5项，提交/推送分别遵守当前授权；本次仅明确要求构建验收，没有自动扩大为提交或修改默认分支。确认后可按上述方案执行并以实际日志继续修复，无需触碰现有虚拟机或数据。

## 首轮执行后的候选修复

用户已批准独立CI分支与执行。首轮41027392700在真实Windows2025上准备依赖并运行原生测试：基础8项6通过/2非Windows分支跳过；控制19项18通过，1项因英文Windows cp1252输出中文产生UnicodeEncodeError。保留原日志，不改断言。

下一轮显式以`-X utf8`执行测试；Rust桌面启动Python同样显式指定UTF8，避免中文路径/JSON受系统区域影响。为维持仅5文件的独立分支范围，CI脚本对下载快照中精确SHA绑定的main.rs施加这一处候选补丁，输出补丁前后摘要与candidate-main.rs，原ZIP不改；本地对应Rust源码同步修正但不批量提交。该差异未进入已公开0.1.4，候选不能冒称与原发布源码完全相同。新增2项源漂移/补丁绑定测试。

第二轮41027970390：19项控制测试已在Windows全部通过；固定QEMU安装器SHA512和主程序SHA256匹配。清单校验在stat/fstat身份比较处拒绝。CPython3.12.10官方posixmodule.c的win32_xstat明确把ctime映射到birthtime，fstat走不同实现，因而补充Windows原字段探针及精确SHA绑定的清单候选补丁：统一比较st_birthtime_ns，仍核对设备/inode/大小/mtime和内容摘要；POSIX仍用ctime。原发布清单源码及ZIP保留，本地相应修复与候选内容单列。第三轮将以原生字段结果复核诊断，不据推断宣布通过。
官方实现：https://raw.githubusercontent.com/python/cpython/v3.12.10/Modules/posixmodule.c 。

第三轮41028690543：原始字段证实同一QEMU文件stat/fstat的设备、inode、大小、mtime、birthtime一致，仅ctime不同，修复后QEMU清单完成。构建器workspace阶段拒绝管理员身份；GitHub官方说明Windows runner默认管理员且UAC关闭。第四轮仅在本轮新云端根授予一次性普通测试用户Modify，密码随机且只留进程内，不输出/入库、不复制任何token。切换后的进程明确验证非提权、加载自身AppData及独立Rust工具链后才构建/安装/卸载，保持原WindowsSecurity拒绝管理员的门禁；不是修改个人电脑账户或已有ACL。账户随临时主机回收，不自动删除任何用户资产。
官方环境依据：https://docs.github.com/en/actions/reference/runners/github-hosted-runners#administrative-privileges 。

第四轮41030090181：普通非提权账户和自身配置目录已实际验证，QEMU清单3321文件完成，候选Rust/清单源与本地对应源摘要一致；独立Rust工具链下载后因rustup不在新CARGO_HOME/bin中拒绝，未放宽应用权限。下一轮把复制的既有rustup布置到准确独立位置，并在编译前保留Python/QEMU静态导入报告；仍不把下载完成记为安装包构建成功。

第五轮41030623039：静态报告发现Python的_msi/_wmi分别导入msi.dll/propsys.dll，原系统DLL声明遗漏。依据Microsoft一手文档补充精确两项，仍保持os-contract-unverified及本地同名DLL遮蔽拒绝。用第三个精确SHA候选源补丁保留五文件分支边界，输出完整候选PE解析源码；未放宽缺失第三方依赖检查。
依据：https://learn.microsoft.com/en-us/windows/win32/api/msiquery/nf-msiquery-msiopendatabasew 、https://learn.microsoft.com/en-us/windows/desktop/api/propsys/nf-propsys-psgetpropertykeyfromname 。

第六/七轮：Python静态依赖通过，逐文件诊断明确只有libgtk-3-0.dll（SHA256 e2cc2698e2e04214e04b18d685550b76558423ebdb2b0a0782171876fe13eb9c）的108160字节导入目录超过原width×4097大小上限。目录包含描述符之外数据，修正为已映射文件/256MiB目录大小上限，描述符仍最多扫描4097条并强制终止符，路径、重叠、别名及缺失依赖检查保持。新增大目录可解析、无终止符仍拒绝测试。原始证据在run-07-artifacts/qemu-pe-diagnostics.json；PE格式依据：https://learn.microsoft.com/en-us/windows/win32/debug/pe-format#import-section 。

第八轮41043610311：所有QEMU PE均解析通过，实际报告列出此前系统声明遗漏9项：cfgmgr32/d3d9/dxgi/dwrite/gdiplus/msimg32/mswsock/opengl32/usp10。逐项核对Microsoft API要求后补充声明，仍只归类os-contract-unverified，不复制宿主DLL、不把静态分析当系统加载或驱动验收。原始missing完整列表保留；第三方DLL和遮蔽检查不变。官方依据见下列链接。
- https://learn.microsoft.com/en-us/windows/win32/api/cfgmgr32/nf-cfgmgr32-cm_locate_devnodew
- https://learn.microsoft.com/en-us/windows/win32/api/d3d9/nf-d3d9-direct3dcreate9
- https://learn.microsoft.com/en-us/windows/win32/api/dxgi/nf-dxgi-createdxgifactory
- https://learn.microsoft.com/en-us/windows/win32/api/mswsock/nf-mswsock-acceptex
- https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-alphablend
- https://learn.microsoft.com/en-us/windows/win32/api/dwrite/nf-dwrite-dwritecreatefactory
- https://learn.microsoft.com/en-us/windows/win32/api/usp10/nf-usp10-scriptitemize
- https://learn.microsoft.com/en-us/windows/win32/opengl/glbegin
- https://learn.microsoft.com/en-us/windows/win32/api/gdiplusinit/nf-gdiplusinit-gdiplusstartup

第九轮41043965820：Python/QEMU静态检查、普通用户Rust1.90、运行时暂存与包内Python探测通过；Windows前端69项通过。npm调用Tauri时--config被吞掉，配置路径误传cargo；直接使用node执行锁定依赖包@tauri-apps/cli/tauri.js build --config避免npm参数转发，原配置及检查保持。新增第四份精确SHA源补丁及候选完整脚本，原发布源码不改。

## 最终结果：原生构建与云端自动安装检查通过

2026-10-30北京时间19:21，第十轮[41044544057](https://github.com/zhangpu1211/ctf-lab/actions/runs/41044544057)成功，输入提交`b7f481639e88e7570dcf8b059a9677a6452c16a9`。Windows Server 2025普通非提权账户完成：运行时静态核对、包内Python、前端69项、Rust release实际编译、NSIS生成、安装、5625文件载荷集合/摘要匹配、包内依赖、可见自有GUI窗口/正常退出、卸载及两类应用数据标记保留。基础测试8项6通过2非Windows路径跳过，控制19项通过。没有Windows Rust单测或全项目单测重跑声明。

安装器`CTFLab_0.1.4_x64-setup.exe`为302903771字节，SHA256 `8583d7796dcd231aeec9ca334f18978547af92d810a062f80e4f93ece46b13a2`，Authenticode为NotSigned。artifact ZIP为303008779字节，SHA256 `9461db717f66bc425e8d43f382026f0924f8864cfdd9688053c3b47fbd74aca4`，本地回下载一致。静态解包安装器5625份runtime文件，重建bundle-manifest与云端独立保留的摘要`0b1312d26a83595c1dbb37cced8618e7ddd0d45dab8ce7309e6331941b326616`完全一致，四份候选源与本地源逐字节一致。Mac没有执行EXE。

本地持久交付：`/Users/pufei/Downloads/CTFLab-Library/03-软件/CTFLab-0.1.4-Windows-native-candidate-20261030/`，含EXE、对应316文件候选源码ZIP、清单/校验及验收证据。源码清单明确标为windows-native-candidate-source，记录原源ZIP摘要和四份补丁；原公开0.1.4源ZIP/Windows构建源码ZIP均不改写。完整云端artifact在`output/windows-native-20261030/run-10-artifacts.zip`，解压材料、完整日志、收据、installer-readback-verification.json、reconstructed-bundle-manifest.json及delivery.json均在该输出目录。云端artifact保留7天，本地副本不依赖其期限。

stage-result.json中的installer_built=false是编译前暂存阶段的原始记录，保留不篡改；最终构建/安装结果以installer-results.json、installation-results.json及completion.json为准。Windows11人工界面/干净机、真实WHPX/来宾/课程、升级迁移回退、签名及G0/G1仍未关闭。云端仅自动检查自有窗口，不冒称完整UI人工验收；没有VM启动/停止或个人资产删除。

本地最终准备器17项、PE11项通过；相关package19项和inventory10项通过，详见本轮对应日志。最后仅补文档与一项源漂移测试时，以[skip ci]保存到同一获批分支，构建脚本/工作流输入不变，不重新生成相同安装器。候选仍不公开Release，不修改默认分支或本地HEAD。
