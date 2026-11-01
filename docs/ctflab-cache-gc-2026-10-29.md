# 缓存回收的逐对象尝试与显式恢复（2026-10-29）

本轮补P03在线缓存回收的实际中断恢复缺口。旧`collect`仅有整批意图与删除后结果；中途退出后无法区分后续未尝试对象和已尝试但没有回执的对象。新实现先封存逐对象尝试，再删除，保留未知而不重放；本轮只操作自动生成的临时夹具，没有读取或清理用户镜像库/实际课程缓存，没有删除既有资产。

## 计划与恢复边界

`ctflab_cache_gc.py`共享内容缓存原SQLite排他门。完整预览绑定缓存根、数据库及objects目录的设备/inode，逐对象SHA名称、内容摘要、大小、inode和mtime/ctime；相同大小/恢复mtime仍须通过完整身份核验。新引用使对应对象退出候选，开始前预览摘要不一致即整批拒绝。引用总数/目录枚举各最多20000，先限枚举再排序；拒绝非普通文件、硬链接、符号链接、未知文件名及哈希期间变化。

新操作UUID必须没有旧意图或孤立回执；根下最多256份保留回收意图，不自动删除旧账本腾空间。意图绑定原计划摘要与根身份；跨根复制不能继续。原`preview_gc/collect(approved)` API保留，但使用新逐对象尝试账本，不能拿旧格式预览跳过新身份字段。

每个对象先写排他的attempt文件并fsync，再核验一次精确对象身份；SQLite门始终持有，新pin/download/upload不能在删除前插入新引用。删除后写独立result。POSIX同步对象目录与回执目录；Windows只沿用文件fsync，未验证断电下目录项持久性，不宣称跨设备原生崩溃持久性已通过。对不遵守缓存门的同用户/外部写入没有全局硬隔离，不能把应用锁当作文件系统快照。

只读状态将对象分为unattempted、unknown、removed、preserved，并另列当前对象身份及引用。缺结果的attempt永远unknown，即使当前文件仍在，也不能推断删除从未发生；原removed对象同名重现时也不再删除。已确认删除失败的preserved也不自动重试。状态有`cleanup_verified=false`，不会因为原removed回执或当前缺文件就宣称全部清理完成。

显式继续要求接受当前observation摘要，且所有未尝试对象仍精确匹配、无引用；任一个未尝试对象变化使整批继续拒绝。继续仅处理从未落attempt的对象，跳过所有已有attempt。可在保留unknown的同时继续其他未尝试对象，结果仍gc-observed；没有未尝试对象时不再可继续。对已尝试对象如将来仍需回收，必须作为独立新计划重新审阅，不从旧操作重试。旧版没有逐对象attempt的意图仅返回legacy-unresolved，不猜测继续范围。畸形/部分/错scope回执保留并拒绝。

## 命令入口

`ctflab_content_cache.py`增加gc-preview、gc-status、gc-start、gc-resume，继续使用固定私有`--root`；所有参数都可先查看`--help`。preview只读完整计划与plan_sha256，status以operation-id只读当前情况与observation_sha256。start必须同时有新operation-id、同一计划摘要及`--execute`；resume必须同时有原operation-id、当前观察摘要及`--execute`。缺少任一项拒绝，没有自动开始/继续或后台服务。普通storage/budget操作拒绝混入执行/操作参数，不扩展远程RPC许可。

这里交付的是源码入口，当前用户禁止删除资产，因此没有对任何实际缓存运行start/resume/collect。未来操作实际缓存仍须对应授权，不能因为源码存在就自动清理。

## 验证

18项新增测试仅使用本轮创建的临时字节/真实SQLite/文件与自有隔离Python命令；覆盖意图写完即中断、attempt写完即中断、unlink后丢结果、删除失败、同名重现、引用竞态、原mtime恢复、对象变化、跨缓存复制、旧格式、部分/错scope/孤立回执、软/硬链接及数量边界、目录落盘失败和操作冲突。实际`-I`命令验证只读预览/状态、无execute或错摘要拒绝、仅自有临时对象执行成功。

原内容缓存、上传/课程引用等受影响回归及最终完整/独立副本结果见状态第119节和`output/cache-gc-20261029/final-evidence.json`。Windows回收没有原生ACL/NTFS/断电验证，POSIX测试注入中断不是物理断电/磁盘故障。应用容量准入仍不是公共审计/日志/卷外全部存储硬配额；真实大文件/真实缓存来源/跨设备/长期故障验收保持开放。

本轮没有VM/SSH/Docker、停机/重启、旧资产删除、宿主网络卷/ACL变更、到期调度、Windows Smoke、提交推送、打包或发布。原Mac更新器及本地已发布App保持；实际发行仍沿第114节Mac0.1.3预览、Windows候选，不含115—119节源码。43项/G0/G1/graceful_stop_verified和全部未关闭开发总目标继续开放。
