# C05完整自制证据与调查复盘源码（2026-10-30）

本轮按原C05“日志/PCAP/磁盘样本、真值和调查任务；原件只读、哈希/来源/时间说明完整、答案独立分发、可复盘”补整条离线课程。没有把真实生产事故或公开发布追加成C05硬门。材料均由项目自制，包含三类证据、学生标准库工具、独立教师逐条复盘和本轮实际调查报告；Windows原生、独立课堂和U03公开分发仍未验，G0/G1与整体目标继续开放。

## 材料、来源与时间

现有Web/认证/变更日志保留原事件，补6帧Ethernet/IPv4/TCP HTTP请求响应PCAP（r05/r06/r07）和360KiB FAT12数据卷。PCAP是手工构造字节，未捕获真实流量，无握手或登录凭据；全部IP为文档地址，域名training.invalid。FAT12只含CONFIG.TXT、ACCESS.LOG、COLLECT.TXT，无可执行文件，不是实际主机镜像；记录维护配置、原Web日志逐字副本和09:04 UTC合成快照标签。FAT目录DOS时间无指定时区，不可直接等同UTC；同一作者的材料不能当三个独立现场来源。

collection.json明确人工来源、生成日期、UTC、覆盖/缺失范围、PCAP与磁盘限制。生成器为确定性自制材料，不依赖第三方镜像或事故数据，也未获取/改变任何第三方资产许可；正式公开分发许可/维护另按U03/U04核对。新清单仍schema=1，kind=synthetic-offline-evidence-v2且content_version=2，全部文本/工具/二进制逐文件SHA256和长度登记；保留旧synthetic-text-only验证，不修改旧包/旧清单或迁移其字节。

PCAP布局参照[IETF PCAP工作草案09](https://www.ietf.org/archive/id/draft-ietf-opsawg-pcap-09.html)的小端微秒文件头及记录；FAT12布局依据[Microsoft FAT规范（公开镜像）](https://www.scs.stanford.edu/~zyedidia/docs/_other/fat.pdf)的BPB、根目录和12位簇链。仅引用格式，不随材料分发规范原文。解析器限本课固定头/几何/文件集合，不是通用恶意输入取证工具，拒绝超限/截断/分片/校验和错误、FAT副本不符/循环/交叉链接/未结束链/目录与异常长度；不挂载、不执行镜像或调用捕获接口。

## 学生与教师路径

`ctflab_evidence_course.build`只向不存在的新目录生成学生/教师测试包、ZIP摘要和独立student-manifest.sha256；后者也放在教师包中，教师可单独把清单指纹交学生核对。指纹不是发布者认证或真实性签名，工具不自动建立信任。学生包不含课程生成器、TEACHER或逐条答案。

学生已有verify.py，新增workspace.py和inspect_samples.py，均由白名单函数提取为独立标准库脚本，不依赖ctflab模块或教师包。普通学生不必安装完整项目、虚拟机或额外取证工具。

1. 保留原ZIP与外部摘要，运行verify.py；从教师独立核对MANIFEST.json的64位指纹。
2. `python -I -B workspace.py prepare /新的调查工作区 --manifest-sha256 指纹`只新建original/work/reports。original是完整证据快照，POSIX文件0400/目录0500；work可写，reports存报告。源解压目录的字节/权限均不改。Windows仅新文件只读属性，不改ACL或宣称原生已验；用户可撤销权限，故tamperproof=false。
3. 在未修改证据的work中运行`python -I -B inspect_samples.py --manifest-sha256 指纹`，先核验整包再显示PCAP记录号、时间/来源/HTTP/关联ID和FAT文件内容/摘要/无时区字段。不输出密码、执行样本、联网或自动打开外部工具。若work已被批注修改，应回到未改的original核对，不绕过摘要。
4. 在reports按模板写事件时间线、证据引用、事实/推断/未知、保全/授权/回退/业务复验方案；不修改original。运行workspace.py inspect复核original；working_copy_checked/reports_checked=false，不把原件通过冒充报告正确。prepare才返回本次准备已复核源目录；后来inspect仅核验快照，source_rechecked=false，不声称未观察的源目录一直未变。

原项目入口也可用evidence-course prepare SOURCE --destination NEW --manifest-sha256 SHA和inspect WORKSPACE --manifest-sha256 SHA。目标必须在源外、不存在、无链接/重解析路径；独占新文件，有限长度/读取身份和内容前后核对。中途失败保留部分目录，完成记录最后落盘，没有覆盖/自动继续/清理入口，需明确选择另一个新目录。已有原件、权限、ZIP与失败现场不动。

教师包新增逐条证据复盘.md：完整8事件排序/行号、r04/r05关联、PCAP记录1—6与FAT文件引用、证据摘要、事实/归因限制、保全与可回退方案、首页和健康分别复验、100分人工评分建议及提示。答案与精确学生清单绑定，学生提交后才单独分发；没有自动按关键词评分或自动执行处置。

## 本轮实际复盘与证据

证据根`output/evidence-workflow-20261030/`。在自有临时包中实际调用新生成器，独立取学生材料和教师材料到新replay-02目录，然后移除本轮自有临时ZIP；没有制作交付App/ZIP或覆盖旧C05包。replay_course-final.py先只读学生证据，实际用独立python -I -B执行校验/工作区准备/样本查看，按CSV/JSON/Web记录重建8条事件，交叉核对请求/状态码、配置和日志副本，写完整报告后才核对教师包的清单绑定。

保留student-materials、teacher-materials、investigation/original/work/reports、四次实际脚本输出、manifest指纹、原件模式/摘要与replay-02/evidence.json。完整报告在investigation/reports/完整调查报告.md，为本轮受控自动化复盘，不称独立学生或人工试点。来源字节和权限未改，最终只读original再次通过；教学预设维护模式与503相符，缺应用语义/现场恢复记录，报告仍保留因果与身份限制。修正前replay-01、frozen-replay-binding.json及2100项完整通过日志保留；独立inspect原先把未重新观察的源误标未变，现已改为未知并增负测，不能把原2100项当最终源码重跑。

系统独立读者：file识别PCAP2.4/Ethernet及FAT12；tcpdump以-r只读文件，6帧TCP校验和正确；fsck_msdos仅-n对本轮新普通文件做只读检查，3文件/702空闲簇、退出0，原输出中的Warning字样保留。检查前后PCAP/FAT12摘要完全相同，没有捕获、挂载或修复卷。初次tcpdump按本机时区显示17时，另以子进程TZ=UTC得到09时，两个日志保留，没有改变宿主时区。

专项包括实际独立学生脚本、源权限/字节不变、错误指纹/篡改/链接/重解析、源中途变化、未知部分目录不重用、只读权限丢失/原件变更拒绝、报告和work不会冒充原件核验、教师答案隔离；样本包括格式负测、完整链与旧文本清单兼容。准确计数、完整回归、独立白名单、保全和最后进程观察在状态第135节及final-evidence.json补录。初次复盘辅助脚本有Unicode bytes字面量语法错误，尚未运行任何准备动作；保留replay_course-initial.py，改编码后完整复盘通过，不是生产逻辑失败或放宽校验。

仍须区分：自制课程离线全链证据、实际Windows只读/运行、跨平台G2、人工课堂、最终发布与公开分发。classroom_verified、Windows原生与公开分发均false；整体43项/G0/G1/graceful_stop_verified未因此完成。全程无用户VM/SSH/Docker、宿主网络卷/ACL改动、真实到期调度、Smoke、桌面控制、用户资产删除、提交推送或发布。源码白名单包含新模块/测试/本文，原Mac更新器和旧App保持。
