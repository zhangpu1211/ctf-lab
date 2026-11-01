# 学生镜像回环HTTPS只读入口（2026-10-29工作区）

P04已有按许可导出目录和显式HTTPS镜像客户端，但缺少实际提供文件的受控入口。本轮补`ctflab_mirror_service.py`与`ctflab_mirror.py serve`，只在127.0.0.1提供现有学生材料，不增加局域网监听、系统信任、账户或资产权限。它是本机验证/受控材料入口，校内生产部署、跨设备和反向代理配置没有实现或验收，不因此关闭P04。

## 显式使用

先沿原`ctflab_mirror.py --cache ... --index ... --keys ... --source ... --destination ...`生成一个新学生镜像目录；旧构建命令不变。教师条目/recipe-only不会被删除后冒用旧签名，而是拒绝构建；服务也独立复查同一要求。

```sh
python3 -B tools/ctflab_mirror.py serve \
  --root /absolute/private/student-mirror \
  --keys /absolute/private/trusted-public-keys.json \
  --origin https://publisher.example/courses/ \
  --certificate /absolute/private/server-cert.pem \
  --key /absolute/private/server-key.pem \
  --port 8443
```

省略端口则由内核选择空闲端口，控制台返回实际端口。没有绑定地址参数，不能监听LAN；启动前完整核验签名、许可、收据映射、文件大小/摘要和私有路径，完成后才绑定。大镜像预检可能耗时，不跳过摘要检查。缺少可信证书/私钥、信任根、有效学生索引或完整材料时拒绝；不生成证书、不安装信任、不联网找证书、不下载或启动镜像。进程结束只关闭自己的服务，不发虚拟机控制命令或删除材料。

TLS证书/私钥若同时是待分发索引条目，启动直接拒绝，即使该条目有合法学生签名也不能提供本服务凭据。证书/密钥和材料沿用原私有路径检查，拒绝符号链接/reparse point、硬链接和不符合权限的文件；不修改ACL。证书必须适用于客户端实际访问名称/IP，并由客户端已信任的CA签发。客户端仍使用原内容源身份验证签名，通过显式`mirror=https://127.0.0.1:端口/`改变传输位置；不重签/改写源索引或默认关闭TLS验证。本轮测试只在自建客户端SSLContext信任一次性夹具证书，未写系统信任。

## 只读与传输边界

服务只接受GET/HEAD，只提供原字节INDEX.json和签名索引中audience=student、redistribution=allowed的文件。MIRROR.json、目录索引、教师文件、密钥与目录外文件不提供；原始请求路径必须与精确白名单一致，不归一化别名、解码百分号或接受查询参数。POST/PUT/DELETE/OPTIONS不写入任何数据。

每个请求重新核对索引/收据文件身份、签名与期限，以及目标文件设备/文件ID、大小、mtime/ctime、链接数；打开后fstat再绑定同一文件。启动后替换、编辑、权限漂移或索引过期会拒绝新请求。不会自动重新导出、采用新信任根或重启，需显式重新核验配置。这里没有操作系统级不可变卷保证：传输中其他同账户程序修改文件仍可能使已发字节失效，最终内容身份必须由客户端下载完成后的SHA256核验，不能拿HTTP200当成完整性证明。

单段bytes范围支持start-end、start-及-suffix，越界/多范围/重复Range/坏格式返回416及总大小。合法请求返回精确Content-Length/Content-Range，If-Range不匹配时返回完整200。文件64KiB逐块读取，不把镜像整体载入内存；签名索引最大4MiB。HTTP强制关闭连接，不记录请求路径/HTTP头。最多8个工作连接，TLS握手在受限线程中进行，空闲握手/读写5秒超时，不以假就绪后再绑定代替实际端口持有。

TLS最低1.2，ALPN只声明HTTP/1.1，不接受明文，也不用TLS服务端证书替代内容签名。这里是服务端证书验证，未配置mTLS身份授权；许可允许的学生文件是只读分发对象，不应把教师私密资料混入源索引。Python官方说明[http.server只实现基础安全检查](https://docs.python.org/3/library/http.server.html)，因此本入口固定回环，不能据此声明校内/公网生产服务器已交付。实际外部服务、限流/长期负载、证书续签与部署身份仍需单独设计和验收。

## 验证与未完成项

本轮用一次性证书、签名索引、自有回环监听和临时缓存实际执行TLS GET/HEAD、Range、原ContentCache.download断点续传；源URL保持不变且最终SHA256一致。不受信任证书/明文请求、索引过期/文件替换/软硬链接/目录穿越/未登记文件、超量连接及停滞握手不影响另一个合法连接等分别检查。

首轮发现BaseHTTPRequestHandler把双斜杠路径归一化，测试保留失败，现增加原始请求路径核对后通过。主实现完整回归后另补TLS凭据分发拒绝，最终源码用22项专项及独立副本覆盖，不将先前完整回归冒充最后一处守卫的验证。命令与各阶段结果见状态第129节及`output/mirror-service-20261029/final-evidence.json`。没有真实课程磁盘/校内服务器/LAN/正式证书、Windows/Linux原生服务长期运行或最终包验收；没有提交、打包或发布，原43项和G0/G1仍未完成。
