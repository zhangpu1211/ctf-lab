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
