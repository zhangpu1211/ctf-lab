# 离线分析程序版本与输出内容对照（2026-10-29）

承接状态第123节，推进原O02“固定工具/规则、同证据输出可复现”的执行与核对入口。正式目录仍为`/Users/pufei/Downloads/ctf-lab`；原43项验收范围不变。本轮不下载/构建/运行真实分析镜像，不对用户PCAP进行解析，不执行Docker、SSH、VM或原生桌面操作，不修改宿主网络/卷，不自动删除资产、执行到期调度、打包或发布。

## 执行链变化

`ctflab_guest_analysis.py`过去只比较镜像标签中的工具版本与wrapper摘要。现在生成的wrapper在读取PCAP之前，先调用固定程序的版本入口，并要求程序报告与策略版本完全匹配。Zeek使用`--version`（[项目官方材料中的示例](https://zeek.org/wp-content/uploads/2025/03/MUC-2025-Inside-the-Zeek-Project.pdf)），Suricata使用官方说明的[`-V`](https://docs.suricata.io/en/suricata-8.0.4/command-line-options.html)。只接受相应固定格式；前缀相似、混杂多行、超4096字节、非ASCII、非零退出或超时均不继续分析，不从标签推定二进制的实际版本。

版本核对和实际分析共用原`timeout_seconds`预算；版本阶段至多5秒。版本输出落在原有有界tmpfs中，不无限捕获到内存；`version.report`与分析器stderr一并保留。镜像digest、配置/输入SHA和原容器隔离约束保持。新wrapper的摘要改变，因此旧配方/镜像不会被新运行时静默当成已兼容；要使用新链路须显式制作并登记新镜像，本轮没有执行此操作。

版本文本只是选定程序的自述，不是来源签名或对分析器未被攻击的证明。工具与wrapper同处隔离容器；被攻陷的工具仍可能伪造本容器输出，所以`analysis_findings_verified=false`继续保留。

## 输出内容指纹

分析程序结束后，wrapper只按原始字节计算本次输出文件清单，不解析日志语法、PCAP或归档。每项包含相对名称、字节数和SHA；按名称排序后再计算整体内容摘要。所有正常输出文件都参与，包括`version.report`和`tool.stderr`，不删除日志中的时间戳/随机字段来制造一致。

范围为最多512个目录项、8层目录、2MiB原始文件；名称限制为128字符的ASCII字母/数字/点/下划线/短横线。符号链接、硬链接、非普通文件、越界、文件身份/内容变化及前后目录树漂移拒绝。保留的`output-manifest.json`与`status.json`由wrapper在清单完成后新建，不能由分析器预占；这两个控制文件不参与内容摘要。文件系统mtime/ctime、权限和空目录不参与最终内容摘要，但身份/时间变化用于采集期间的漂移检查。

清单是本次容器内观察到的文件内容快照，不证明后续归档期间绝无变化，也不证明原始tar的字节相等。归档继续原样流式封存，不在宿主解包；`byte_reproducibility_verified=false`保持。若有残留进程、恶意分析器或输出竞争，仍须原生隔离/归档验收，不能用此元数据越过O02门槛。

成功状态必须带相符的程序自述版本、版本报告摘要与合法内容指纹。旧成功结构、额外字段或缺少版本/指纹不能直接进入导出与正常结束步骤；原操作保持未知且不自动重放。已知版本/工具错误则保留失败输出，沿原自有分析容器封存/结束流程，不能写成业务成功。

## 两次结果的显式只读对照

结果增加操作/实例/代次/策略及wrapper绑定。新`compare-results`只读取两份明确选择的JSON结果，不运行程序、不连接Docker、不读取归档或原PCAP、不写输出文件。每份必须提供调用方独立保存的原文件SHA，限制64KiB、普通独立文件及无重复JSON字段/非标准常量，并在读取前后核对内容与身份。

```text
python3 tools/ctflab_guest_analysis.py compare-results --left /explicit/first-result.json --left-sha256 <原摘要> --right /explicit/second-result.json --right-sha256 <原摘要>
```

示例说明参数形式，不代表本轮选取过用户材料。两份结果必须成功、属于不同操作，实例/代次/策略、输入/配置、工具/版本、镜像与wrapper完全相同。输出明确区分`same_output_content`、`same_version_report`；同一操作的幂等回复不能当两次独立分析。上下文或版本不符直接拒绝，不将不匹配解释成可复现。

对照结果只证明选定报告中的元数据是否相同。独立保存的SHA保护调用方选定字节，不赋予JSON发行签名或远程认证，因此`reports_authenticated=false`、`archives_extracted=false`、`byte_reproducibility_verified=false`始终保留。实际运行结果应从已有认证来宾通道和操作账本取回；是否可信及真实输出可复现，需要单独检查其来源与原生执行证据。

## 本轮验证与未关闭项

专项真实执行的是自有短命替身程序、原wrapper及临时文件；它们覆盖版本先行、精确匹配/超限拒绝、同字节两次指纹、变化对照、链接/深度/数量/大小/预占控制文件拒绝、原预算超时和正常信号退出。Docker/来宾/镜像/分析器本体为替身；PCAP与tar在宿主保持不解析。来宾安装材料副本实际执行新的延迟读取/对照逻辑，核验运行时依赖闭包，未运行安装器。

完整命令/通过/失败/跳过、保全与最终源码范围见状态第124节及`output/analysis-reproducibility-20261029/final-evidence.json`。真实Zeek/Suricata镜像和规则的构建/来源、真实畸形输入隔离、真实相同证据重复分析、动态字段导致的差异和归档一致性仍开放；本轮不修改43项/G0/G1或`graceful_stop_verified`。


## 第125节增量：tmpfs归档导出与独立内容核对

本轮进一步修正原`docker cp`导出路径。[Docker官方说明](https://docs.docker.com/reference/cli/docker/container/cp/)列明tmpfs等特殊目录不能这样复制。生产导出改为在原分析容器中显式执行固定Python/wrapper的`archive`模式，将固定`/output`目录流式生成PAX tar；原有20秒/4MiB客户端限额、0600原始partial、失败保留及只结束本次客户端的规则保持。没有调用宿主tar或把归档解包到宿主目录。

有内容指纹的结果，导出后还必须经过独立校验容器。原归档保持0600原字节，另在本操作私有目录新建0444独立副本作为唯一只读输入；复制前后与校验后均核对原件/副本的身份和SHA。校验沿同一固定镜像digest/wrapper，不运行分析工具，不挂原PCAP或其他目录。配置为network none、只读根、UID1000、全部capabilities丢弃、no-new-privileges、128MiB内存/同等swap上限、1 CPU/16 PID、无重启、20秒客户端等待和有界本地日志；所有配置与操作/实例/代次/策略/角色标签先读回核对。使用[`docker start --attach`](https://docs.docker.com/reference/cli/docker/container/start/)只取得固定校验器输出及实际退出状态，不提供任意程序/命令入口。

两个容器均显式禁用镜像继承的[HEALTHCHECK](https://docs.docker.com/reference/cli/docker/container/create/)，Python使用`-I -B`固定入口。镜像若声明任何VOLUME，在创建前直接拒绝，避免隐式卷在create时被初始化后才发现。材料生成器不检查基础镜像，部署方必须明确选用没有VOLUME声明且满足固定程序路径的基础镜像；生成配方不证明这些条件已满足，也不能移除基础镜像继承的VOLUME。本轮没有构建镜像或创建容器。

校验器只在该独立容器读取成员流，完全不创建成员文件或执行成员。输入为1024字节至4MiB的未压缩tar，只接受普通文件/目录及有界本地PAX头。最多515个成员（原512项及wrapper两个控制文件/根目录），拒绝绝对/越界/歧义/重复路径、链接/FIFO/设备/稀疏或其他格式、巨大声明长度、过大PAX、尾部非零数据或串接归档。控制JSON去重且有大小上限；必须包含原status和完整manifest。实际成员文件名/原字节SHA/字节数需逐项匹配清单，重新计算的内容指纹须匹配状态；归档中的状态又必须匹配导出前已观察状态的规范摘要。检查归档读前/读后身份与完整原字节SHA，不依赖tar中的mtime、UID或用户名取得权限。

只有上述校验和实际退出码均匹配，结果才新增`archive_content_consistent=true`与校验容器/收据。它表示这份封存归档与已观察文件指纹一致，不表示两次分析结果相同、分析结论正确或工具未受攻击；`byte_reproducibility_verified`和`analysis_findings_verified`仍false。已知分析失败且没有清单时，仅保留原始归档，明确`archive_content_consistent=false`，不会把失败伪装成校验通过。

复制、创建和校验运行都先落原操作意图；丢回复、非零退出、非法/重复JSON或原件漂移保持unknown，不重放原操作、不自动重新生成归档，不结束未核对的分析容器、不删除原件/副本/容器记录。新镜像摘要/配方须明确准备，旧已发布包不变。资源限额/挂载/真实Docker故障、受攻击解析器的容器隔离仍需来宾实测；本轮只执行自有替身、归档生成与隔离Python子进程里的解析器，不能将Mac子进程视为已经验证Linux容器隔离。

专项及最终全量/独立副本结果见状态第125节与`output/analysis-archive-20261029/final-evidence.json`。原43项及第4节其他实际开发/原生验收继续开放。
