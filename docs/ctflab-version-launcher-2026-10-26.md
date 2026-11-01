# 签名版本固定入口启动器（2026-10-26）

正式目录`/Users/pufei/Downloads/ctf-lab`，分支`codex/release-0.1.1-preview-20261010`、HEAD`0994f620516c49d84badc3a606c1cd5ae4b483d0`。从状态第94节继续，保留全部改动、原Mac更新器和旧包。此处交付可测试的启动器核心/CLI与更新互斥，**不是最终安装器、Windows/Linux实机验收或43项完成**。

## 行为

- `ctflab_release_store.py`兼容旧schema=1版本暂存；新schema=2增加签名覆盖的`launch`字段，仅接受`platform`、`entry`、`executables`。Windows x64入口固定`ctflab-desktop.exe`，Linux x64固定`ctflab-desktop`；入口必须在文件白名单和执行文件列表中。不接受参数、脚本钩子或自报任意入口。新路径声明拒绝大小写目录别名、尾点和保留清单名。应用包schema与实验数据schema分开，`data_schema`仍仅1。
- 新暂存保存原Ed25519签名信封`RELEASE-MANIFEST.json`。目录文件必须完整且精确，额外文件/空目录、符号链接/重解析点、硬链接或内容漂移拒绝；原输入目录未选文件不复制。Linux仅对签名声明的执行文件设置执行位，后续执行位丢失也拒绝。
- 新`ctflab_release_launcher.py`从活动版本重新验证信任根、签名信封、数据库摘要、完整文件集合、平台和固定入口；旧schema=1不猜入口，不自动升级或回退。数据库活动版本/路径异常不能引导读取版本目录外的清单。
- Windows入口额外要求本机Authenticode验证通过，不支持无签名绕过；检查无UI，仅用本机缓存的证书链/撤销信息，缓存或可信链不足会拒绝。严格以WinVerifyTrust返回0为成功并始终关闭provider状态；验证后再核对全文件摘要。Ed25519发布信任根与Windows代码签名证书是不同要求，测试用临时密钥不构成生产信任根。
- 预览返回`plan_sha256`，明确run必须使用对应摘要；活动版本或内容变化则拒绝。只派生固定可执行文件、无附加参数，限制继承环境并关闭多余句柄；不继承动态预载入、Python搜索路径或WebView额外启动参数。Mac不在此新启动器的运行白名单，原Mac更新链不替换。

Windows接口依据：[WinVerifyTrust](https://learn.microsoft.com/en-us/windows/win32/api/wintrust/nf-wintrust-winverifytrust)、[WINTRUST_DATA](https://learn.microsoft.com/en-us/windows/win32/api/wintrust/ns-wintrust-wintrust_data)、[WINTRUST_FILE_INFO](https://learn.microsoft.com/en-us/windows/win32/api/wintrust/ns-wintrust-wintrust_file_info)。当前只有结构布局及注入provider替身测试，没有调用用户Windows机器或证明本机证书缓存满足要求。

## 并发与失败

版本根增加私有`application.lock`与`launches/`。启动器在核验、派生和等待应用退出期间持有应用门；版本数据库只在核验/记录期间短暂持锁，应用运行时仍可读取版本状态。直接激活、回退、协调更新预览/执行必须取得同一应用门；已有工作区/契约/代次/全部节点停机门仍保留。没有任何自动停机代码。

派生前写独立意图，派生后写绑定，只有所持子进程对象wait返回才写退出证明，绑定意图/派生记录摘要。派生失败、记录失败、终端中断或缺失退出证明保持unknown，阻止新的启动/版本切换，不自动重放、清理、终止应用或停止VM。历史查询只报告私有记录，不能当作当前进程观察，也不凭历史PID操作；未决记录的独立实机核验/显式结清仍待后续开发。

应用门只覆盖经该版本库启动器启动的应用，不证明所有直接启动的应用或后代进程都已退出。后台VM继续由原实例生命周期和已登记工作区门管理，未登记工作区不冒充已经核验。旧安装根需明确调用已有`update-initialize`补启动状态；普通读取、预览或启动不自动迁移。旧版本、部分暂存、失败备份、启动记录和磁盘均保留；启动历史上限4096，没有自动删除入口。

## 入口与验证范围

新CLI提供`preview --root <版本根> --keys <受信公钥文件>`、`run --root <版本根> --keys <受信公钥文件> --plan-sha256 <预览摘要>`、`history --root <版本根>`。公钥由操作者预先信任，文件需通过私有所有权/权限检查，不从版本载荷取得；本轮没有生成生产密钥、证书、用户安装根或最终包，也不要求用户现在运行这些命令。

专项入口`python3 -m unittest discover -s tools/tests -p 'test_ctflab_release*.py' -v`：38项通过，涵盖原版本/更新流程及新22项启动器/Windows布局和provider替身验证。临时自有POSIX脚本经过真实Popen执行、继承环境核验和退出码7封存；host标签为测试注入，不是Linux桌面实测。其他派生用FakeProcess，不启动桌面/QEMU/来宾，不调用真实Windows WinVerifyTrust。测试全部使用自有临时目录、临时签名密钥与合成字节，不操作用户资产。

新模块、测试、说明纳入入库/源码白名单，运行时闭包与Windows源码专项入口同步；未重打包、覆盖旧包或发布。前端/Rust未改，不重复跑或借用第94节结果冒称新的原生验收。完整回归/独立源码与最终摘要会写入`output/version-launcher-20261026/`，结果补在文末。

## 剩余

稳定安装器/引导程序的实际集成、安装/更新界面、启动器中断后的独立核验与显式结清、真实Windows签名/离线证书缓存、Linux桌面/运行时依赖闭包及干净机回退仍未完成。用户暂无镜像/SSH/签名证书已知，不重复索要；完整G0/G1与集中实机总验收尚未开始。

D02跨网/二层隔离、远程课程映射/认证显示/窄通道/调度与硬额度、审计外部封存/换库/显式pending、更广来宾修复、外部VM、真实课程和O02等继续按43项台账推进，不能把未实现项统称只等实测。

接续语：继续`/Users/pufei/Downloads/ctf-lab`，先读AGENTS.md、状态第95节、本说明与43项台账末尾，现场核验Git/实例并保留全部改动，推进剩余开发，最后集中实机验收。不重做Windows Smoke，不停止现有VM、运行实际到期调度、删除用户资产、提交、推送、覆盖旧包或发布，保留原Mac更新器；缺镜像/SSH/证书已知。


## 本轮最终本地验证

- 完整`python3 -m unittest discover -s tools/tests -v`：1388项，1367通过/21条件跳过，238.146秒（full-tests.log）。
- 独立复制集成白名单150文件后运行unittest：498项，490通过/8条件跳过，16.758秒；103个Python文件语法检查、启动器/交付/源码包3个独立CLI帮助入口通过（isolated-tests.log、isolated-evidence.json）。未生成ZIP或新安装根。
- 版本/更新专项38项，运行时复制5项通过（release-final.log、package-current.log）。前端/Rust此阶段未修改、未重跑；第94节结果仅为历史证据。
- 对照第94节147文件，仅预定5个既有文件变化，其他142文件原摘要保留，新模块/测试/说明3文件新增。原Mac更新器及其测试与HEAD一致；最终摘要和白名单检查见output/version-launcher-20261026/final-evidence.json。
- 本轮没有真实WinVerifyTrust、原生Windows/Linux桌面、安装器、QEMU/来宾或课程操作，没有重做Windows Smoke、运行实际到期调度、停止现有VM、删除用户资产、提交、推送、覆盖旧包或发布。结束时本机未发现QEMU/固定网页夹具/测试进程，不据此推断远端Windows状态。

上述验证未关闭W05、G0/G1或43项整体；graceful_stop_verified保持false，集中实机总验收尚未开始。继续入口为当前状态第95节与本说明“剩余”。

## 2026-10-26 中断后独立观察与显式结清增量（状态第96节）

新增 `review --root <版本根> --launch-id <启动标识>` 和 `settle --root <版本根> --launch-id <启动标识> --review-sha256 <本轮核验摘要> [--wait-ms 0到1000]`。这两个动作不启动应用、不重发启动、不切换版本、不停止进程或VM，也不要求重新提供发布签名公钥：它们只处理既有启动记录；后续启动仍重新验证发布签名。

新启动在 `spawned.json` 之后尽力追加 `identity.json`，绑定原派生记录摘要、PID、创建时间和版本固定入口的完整映像路径。通过所持子进程对象在观察前后都确认尚未退出，防止子进程已退出后误记重用PID。快速退出、映像不符、平台不支持或观察权限不足时不猜身份；原父进程仍可正常等待并封存退出码，独立结清则不可用。新增身份记录写入失败保留未知，原记录不覆盖。

`review` 仅读取原记录与当前进程身份，核对平台、版本路径、固定入口、创建时间及摘要，返回本次核验摘要；不写退出证明、结清或数据库。`settle` 需要明确提供该摘要，重新核验，持有版本应用门和数据库门，以已有Windows查询/等待句柄或Linux pidfd保留同一内核对象，最多等待1000毫秒。运行中拒绝结清，缺PID、权限失败、PID复用、映像变化、旧记录缺身份均保持未知；观察期间记录漂移也拒绝。没有用“PID不存在”推断已退出。

只在保留对象实际报告退出后追加独立 `settled.json`，绑定意图、派生、身份与核验摘要；旧原文件保留。Windows保留真实句柄退出码（含259），Linux pidfd只证明退出、退出码为null，明确 `exit_code_known=false`。版本存储验证该证据后允许原有后续门禁继续执行，其他未决启动仍阻塞；损坏的父进程退出证明不能被结清掩盖。结清只涉及绑定的应用进程，不证明后代、VM、课程已停止或可用。

本轮Windows句柄/Linux pidfd接口由替身注入测试，未做真实Windows/Linux应用恢复。Linux现有观察器要求仍能读取进程映像并在retained入口核对running；已消失/僵尸等无法重新核验的旧进程继续未知，尚需持久独立监督者或更完整的恢复流程。没有提供无证据的强制结清、人工填退出码或删除记录入口；本增量不关闭W05整体。

专项入口 `python3 -B -m unittest discover -s tools/tests -p 'test_ctflab_release*.py' -v`：51项通过（新增13项）。覆盖只读、不杀进程/重放、PID/映像/平台/摘要漂移、运行中拒绝、两平台退出证明、缺身份、等待上限、写入失败与损坏证据。最初调整缺文件拒绝时3个既有测试出现FileNotFoundError，已恢复明确拒绝边界后全部通过；没有遗留该失败。证据根 `output/launcher-recovery-20261026`；完整与独立副本结果见状态第96节及最终摘要。
