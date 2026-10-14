# 场景资源登记与双网服务生命周期合成验证（2026-10-14）

> 历史验收快照；不替代当前软件状态。以后继续时须现场重核文件、登记、锁与进程绑定。

正式目录：`/Users/pufei/Downloads/ctf-lab`。分支：`codex/release-0.1.1-preview-20261010`；HEAD：`941db31`。本轮保留已有改动，未提交、推送、打包或发布；历史 App 版本未重新核验。

## 范围与实现

- 新增 `tools/ctflab_scenario_registry.py`，接入完整资产准备入口：跨实例 MAC/端口/路径登记、同实例残留预约拒绝、追加历史、显式观察后释放、旧无登记现场拒绝迁移。
- 新增 `tools/ctflab_scenario_services.py`：白名单 argv/pass_fds 生成、总截止时间、两网就绪、降级、节点停止前置条件、逆序正常停止、超时等待及只读恢复审计。
- 新增 `tools/tests/test_ctflab_scenario_services.py`，保留既有测试并调整路由故障夹具使用独立状态根（前一 backing 故障现在会合法保留预约）。白名单仅加入两个源码模块及本验证文档；没有扩大资产入库范围。

## 本轮验证

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools:tools/tests python3 -m unittest test_ctflab_scenario_resources test_ctflab_scenario_services test_ctflab_scenario_dhcp test_ctflab_network test_ctflab_scenario test_ctflab_network_report -q
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests -p '*doc*' -q
git diff --check
```

结果：相关 60 项通过；文档守卫 94 项通过、跳过 5 项；5 个受影响源码/测试文件经 `ast.parse` 语法检查通过；diff 空白检查通过。相关测试中包括既有真实 `qemu-img` 三份 1 MiB 合成 QCOW2/overlay 检查，无真实来宾。新增 16 项测试，覆盖：

| 路径 | 证据/故障 |
|---|---|
| 资源登记 | 六个 MAC 与两端口登记、关闭后预约保留、显式释放追加历史、重复释放拒绝 |
| 跨实例/锁 | 显式 MAC 冲突拒绝、不同 MAC 的另一实例准备成功、持场景锁时释放竞争拒绝 |
| 崩溃/旧现场 | 损坏/半行尾部及链接拒绝、fsync 失败保留完整已写预约且不创建 overlay、旧未登记场景拒绝 |
| 启动/就绪 | argv 经过真实网络模块解析、继承 FD 精确匹配、双网就绪、重复启动拒绝、第二 spawn 故障、单网超时、总启动截止时间 |
| 停止/降级 | 节点未停禁止请求、归属改变及日志失败不发请求、超时保留并可继续等待、不重复请求、服务退出降级且不重启 |
| 恢复 | 存活/停止观察等级、启动身份失配、日志记录中断窗口、准备摘要/路径/代次错误、审计期间记录变化拒绝 |
| 失败释放 | 观察器抛错不改变登记且释放本次锁，不删除现场 |

过程失败据实保留：首次接入登记后，旧路由故障夹具在先前 backing 故障留下预约，按新策略先被拒绝；改为独立根覆盖路由路径。首次半行尾部测试因原异常被统一损坏提示包裹而失败，保留 `ScenarioError` 的具体诊断后通过。最终测试类不继承/导入其它 unittest 类为模块全局，避免重复计数。新增验证文档首次文档守卫因缺少“历史验收快照；不替代当前软件状态”标记失败，补齐后重新验证。以上不是生产运行失败，也没有操作用户实例。

## 操作与未验证项

本轮测试只在自身临时状态根、短 socket 根、合成资产和 FD 上运行；服务进程、启动身份、退出及请求均为合成对象，未启动网络服务或 VM、未查询/控制用户实例。真实 `qemu-img` 临时子进程均已退出，测试自身夹具/FD 清理后没有本轮后台资源。不能由此宣称宿主没有其它 VM。

完整全仓回归、真实服务 FD 继承、生产进程身份采集、锁下恢复接管、VM 生命周期/QMP、整场景事务重置、双网隔离矩阵、Wintermute 业务、人工桌面/跨设备/发布验收未运行或未实现。登记仅覆盖同一状态根的场景；释放证据与恢复 inspect 仍由可信调用方提供。恢复观察不授予信号/删除权限，不证明资产当前完整、来宾停止或实验可用。
