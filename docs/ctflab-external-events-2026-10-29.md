# 外部Windows事件XML采集（2026-10-29工作区）

补齐E02原判据中的受控日志采集/取回入口。只读Windows Event Log XML，不导出EVTX、不修改日志或注册表，不扩大网络/生命周期权限。真实Windows来宾、权限矩阵、日志轮转和现场取回尚未验收，E02/E03与G0/G1仍未关闭。已发布App/旧材料包没有更新。

## 使用范围

在已部署可信运行时、固定SSH强制命令和虚拟来宾身份绑定的现有外部节点配置中，显式增加`event_sources`。例如：

```json
{
  "event_sources": {
    "system-events": {
      "channel": "System",
      "provider": "Service Control Manager",
      "event_ids": [7036],
      "after": "2026-10-29T00:00:00Z",
      "before": "2026-10-29T01:00:00Z",
      "max_records": 32
    }
  },
  "principals": {"runner": ["system-events"]}
}
```

这是现有配置的相关字段示例，不能替代原schema、VM/node/cohort/checkpoint/代次、services、限额与过期字段。服务可以不授予该principal；日志名称不能与服务/隧道名称重合。仅windows/ad-dc/ad-member允许日志配置，默认没有日志源。固定时间范围左闭右开、最长24小时，UTC精确到100ns；至多4个事件编号、32条记录、单条64KiB和总快照256KiB。来源名支持空格和中文，不能携带XPath；通道只接受名字，不接受磁盘路径。每会话至多4次采集尝试，所有取回字节合计受原`max_bytes`约束，不能用重复读取绕过限额。

客户端使用原预登记SSH连接文件和expected身份文件；后者仍固定七个身份/agent摘要字段。需按实际部署后的`ctflab_external.py`更新可信摘要，不能沿用旧版本摘要或在报错时忽略核验。模块已加入显式运行时/独立材料白名单；这里只更新源码，未生成或部署新材料包。

```sh
python3 -B tools/ctflab_external.py collect-events \
  --ssh-config /absolute/private/ssh.json \
  --expected /absolute/private/expected.json \
  --source system-events \
  --destination /absolute/private/new-events.json
```

目标父目录须已存在且通过现有私有路径检查；目标必须是新文件。下载完成并校验全部摘要/身份/事件元数据后，才排他创建文件；POSIX为0600，Windows沿用原私有存储检查，不改变ACL。文件含receipt与snapshot，snapshot中含原始XML，可能包含敏感信息，应继续私有保存。控制台只输出严格字段收据，不输出事件正文，不自动打开/执行/解包。写入失败保留本次文件现场，不能拿部分文件当成功证据。

## 协议与失败语义

`ext-handshake`只列出当前principal获准的event_sources，声明`bounded-event-xml-v1`。`ext-events-capture`绑定challenge、node/cohort/checkpoint/代次与snapshot UUID；原生SMBIOS虚拟来宾身份和配置/期限在每个请求重新核对。新UUID先占位，再执行只读EvtQuery/EvtNext/EvtRender，Windows权限不足即失败，不提权，不安装源、不清日志、不启动程序。未注入测试API才标native_collection=true；这个标记也不代表真实业务健康。

采集按通道前向枚举并二次核对每条XML的通道、来源、事件ID、记录ID与时间，拒绝重复/倒序ID、DTD/实体、异常编码及超量。遇到上限会再读一条以识别溢出，拒绝返回截断成功；所有事件/查询句柄在原线程关闭。权限/读取超时/句柄关闭错误均失败，不能伪装为空集合。查询不是Windows日志的原子事务，不能保证轮转/清除/并发写入时获得通道的完整历史，也不能替代原始EVTX取证。

成功快照只缓存在当前SSH agent内存中。相同UUID/来源在同会话返回同一摘要和字节，不重查询；失败UUID保留占位不能重做。关闭/失败清空快照原文；UUID占位在agent存活期间保留。**跨会话没有持久幂等或续传承诺**：连接结果未知时不自动重连、换UUID或再次采集，显式新会话采集属于新的只读观测。不要把它叫作崩溃可恢复EVTX导出。

`ext-events-read`仅允许已缓存UUID、原SHA256与16KiB对齐偏移，不接受任意文件路径，返回固定大小原文字节。客户端核对分块偏移/终态、总长/SHA256、规范JSON及每条XML元数据才交付。收据包含完整身份和policy摘要，health_verified/automatic_replay/event_log_modified固定false，外部快照/恢复点、域业务、隔离和生命周期仍按原验收门处理。

Windows API依据：[EvtQuery](https://learn.microsoft.com/en-us/windows/win32/api/winevt/nf-winevt-evtquery)、[EvtNext](https://learn.microsoft.com/en-us/windows/win32/api/winevt/nf-winevt-evtnext)、[EvtRender](https://learn.microsoft.com/en-us/windows/win32/api/winevt/nf-winevt-evtrender)。固定XPath表达式数低于官方20表达式阈值；未传入容错查询标记。EvtNext单次等待1秒，不能保证整个原生调用链有硬截止，客户端超时仍按未知处理。

## 本轮验证

本轮仅使用ctypes指针替身、自有XML与临时私有文件，没有加载Windows DLL或读取系统事件。验证命令、结果及保全摘要见状态第128节和`output/external-events-20261029/final-evidence.json`。事件API原生权限、通道差异、语言/轮转与真实SSH断线、EVTX原始导出/持久恢复仍待后续实现或验收，不用测试条数关闭原43项。
