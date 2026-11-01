# 远程受限资产同步开发增量（2026-10-25）

承接状态第85节及用户再次要求继续。只补充R01资产同步与持久消息通道，不新增SSH部署/监听，不连接真实远端或启动用户实例。此前[维护/远程/证据说明](ctflab-maintenance-remote-evidence-2026-10-25.md)保留当时范围，最新检查见[本轮验证](verification-remote-assets-2026-10-25.md)。全部43项原完成判据不变。

## 签名缓存与分块上传

新增 `ctflab_remote_assets.py`。服务端操作者先显式初始化已有ContentCache的uploads目录/账本，再在私有Runner策略中加入可选uploads配置。索引仍使用已有签名接收、防回滚和有效期机制；上传者不能指定信任根、签名密钥、任意宿主路径、许可或执行命令。只接受服务器已接收索引中的原源、摘要、精确大小、允许再分发和当前角色可用的audience。

```json
{
  "cache_root": "/absolute/private/content-cache",
  "sources": ["https://school.example.invalid/courses/"],
  "quota_bytes": 8589934592,
  "max_uploads": 32
}
```

配置示例不是可直接连接的真实学校地址。quota_bytes/max_uploads均按principal计入全部已登记上传，包含未完成、成功和损坏现场；逻辑保留量不因缓存去重自动释放。开始上传还检查全缓存待写保留量与剩余空间，每块写入前复查空间。没有自动删除/释放额度入口。

学生只能同步student材料，教师/管理员也必须使用索引允许的audience。所有状态/分块/完成操作绑定服务端固定principal和上传UUID；另一个principal不能接管同一ID。授权过期拒绝新begin/chunk/finish，保留状态查询；签名索引过期或许可变更后也拒绝继续旧上传。不会因digest相同绕过权限。

每块最多32KiB，使用有上限的base64 JSON消息。重复offset/相同字节只返回当前进度；不同内容、间隙、越界、错误base64或链接/硬链接均拒绝。文件先写、fsync再提交水位；进程中断后只有匹配的未提交前缀可以补完，不能猜测新内容。未完成/损坏字节始终在独立uploads目录，不能作为缓存对象供实例使用。

完成时重验整文件大小/稳定身份/SHA-256；错误摘要持久标记corrupt并保留现场。先独立提交缓存保护引用，再把已核验对象公布到objects。若重命名完成而账本提交中断，引用仍保护对象，状态明确promotion_pending，显式再次finish核验后登记；不重新复制、不自动清理。已经标为verified的记录若对象消失或损坏，也不能继续返回成功。

这里只同步明确选择的二进制字节。上传成功不创建实例，不执行文件，不标记镜像可启动、来宾服务或课程通过。客户端源文件始终只读。

## 单条SSH连接中的持久消息

Runner serve兼容单请求EOF，并新增有界JSONL多请求；每条消息重新读取服务器权限，长连接不继续沿用已经撤销的scope/旧授权期限。仍要求部署方的固定命令、principal及禁转发设置，客户端固定ctflab-runner-v1命令。

客户端 `SSHSession` 在一条自有SSH进程上顺序传送握手/开始/多块/完成，避免每32KiB重建SSH连接。每条回复核验协议、服务器UUID与请求ID；输入、单行输出、排队数量及等待时间均有界。异常仅结束自有传输进程，生命周期请求不自动重发。服务端单连接上限100万条消息，约32GiB有效分块量；超出后保留进度，用相同upload-id显式重连继续。

```text
python3 -B tools/ctflab_remote_assets.py initialize --cache-root <服务端已有签名缓存>
python3 -B tools/ctflab_remote_assets.py upload --config <本地受保护SSH配置> --file <明确选择的本地文件> --source <已登记HTTPS原源> --audience student --upload-id <操作者保存的新UUID>
```

本轮没有执行以上操作去连接用户远端；验证使用临时签名缓存和POSIX SSH脚本替身。中断后操作者保留原upload-id、源文件与配置，显式重用入口会从已提交水位继续；不自动重新信任主机密钥，不改SSH配置，不引入端口转发。真实SSH、网络抖动、Windows OpenSSH及多用户规模仍未验。

## 仍需开发与验收

R01仍缺桌面远程目标/课程资产映射、真实Linux/KVM/SSH部署与完整远程课程流程；上传成功的缓存可复用已有GenerationStore资产引用保护，但不会自动创建或迁移用户实验。R02资源租约/续租/到期正常停机、鉴权显示与配额调度，R03完整多人审计，R04数据通道仍未完成。远程上传配额不是VM算力/内存/磁盘配额。

其他43项开发缺口继续见执行台账：OCI装载/容器跨网、终端窄路由/部分来宾对账、外部Kali→Windows→AD、真实课程和隔离分析器等。本轮不包装为全部功能完成，不启动实机总验收，不要求用户现在逐项执行。原Mac更新模块、旧Windows/源码交付与已发布App不覆盖。
