# 三节点生命周期与派生资产重置事务合成验证（2026-10-14）

> 历史验收快照；不替代当前软件状态。以后继续须现场核对路径、指针、日志、登记、锁与实际进程身份。

正式项目：`/Users/pufei/Downloads/ctf-lab`；分支 `codex/release-0.1.1-preview-20261010`；HEAD `941db31`。保留已有改动，没有提交、推送、打包或发布。

## 本轮实现

- 新增 `tools/ctflab_scenario_nodes.py`：三节点顺序/白名单 argv、启动身份与 QMP/overlay 就绪绑定、部分失败/退出降级、逆序正常关机、逐节点超时和只读节点恢复审计。
- 新增 `tools/ctflab_scenario_reset.py`：停止证明、初始活动代次、三盘/固件变量新代次准备与完整性清单、原子指针提交、崩溃审计与显式提交/放弃收口。
- 更新资源准备/登记：阻止旧代次或未接续重置资产重新预约；识别 committed/aborted 资产历史。新增源码及验证文档保持精确入库白名单，磁盘/日志不入库。

## 验证入口与结果

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tools:tools/tests python3 -m unittest test_ctflab_scenario_nodes_reset test_ctflab_scenario_resources test_ctflab_scenario_services test_ctflab_scenario_dhcp test_ctflab_network test_ctflab_scenario test_ctflab_network_report -q
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests -p '*doc*' -q
git diff --check
```

相关 83 项通过，含本轮新增 23 项；文档守卫 94 项通过、跳过 5 项。5 个本轮相关 Python 文件经 ast.parse 语法检查；diff 空白检查与新增文件白名单核对通过。

| 路径 | 合成证据 |
|---|---|
| 节点启动 | Neuromancer→Straylight→Kali、QMP/overlay 绑定、重复日志拒绝、第二 spawn 失败保留第一节点/双网、QMP 缺失截止时间 |
| 节点停止 | Kali→Straylight→Neuromancer、超时保留后续节点/双网、继续等待不重复请求、身份失配/日志失败不发关机请求 |
| 节点失联/恢复 | 退出只降级、不补启；pending 与 PID/启动身份失配要求恢复；只读观察不修改日志 |
| 资产重置 | 清单/MAC/IP 不变、三份 overlay/NVRAM 新建、旧盘保留、新网络目录无旧租约/记录 |
| 重置故障 | 第二盘失败、来源哈希错误、空间不足、错 backing、已有目标、停止证明变化、场景锁竞争、原子替换失败均保留旧活动指针 |
| 提交/恢复 | 提交后日志失败以新指针为准、显式补记提交；旧指针有效时显式记 aborted、另选新代次，不删除部分失败资产 |
| 完整性/旧入口 | 新代次盘被改动拒绝审计；旧代次与未接续新资产预约被拒绝 |
| 真实派生格式 | qemu-img 创建三份 1 MiB 合成 QCOW2、完整准备及新代次三份 overlay check；基盘 0400、哈希不变，无真实 VM |

本轮首轮 14 项、扩大后的 22 项以及最终 23 项新增验证均通过；扩大范围来自新增崩溃/完整性/接续门槛实现，未出现需反复修复的测试失败。上述测试均使用自身临时状态根、短 socket 根、合成固件/基盘、FD 和合成进程对象；真实 qemu-img 子进程已退出，测试夹具/FD 自行清理，没有本轮后台 VM/服务或持久测试资源。没有查询、启动、停止用户实例，没有删除用户资产。

## 实际限制

reset-ready 为停止态资产描述，没有网络端口/实际服务/旧 PID，也没有新的运行预约；旧预约保留。资产接续到新网络/socket/服务/节点的编排尚未实现，入口明确阻止绕过指针继续旧盘或直接启动未接续新资产。这里不交付可启动的 Wintermute 包。

节点 QMP、启动身份、ACPI 请求和停止证明均为注入的合成接口，没有真实 QEMU/QMP/服务控制。节点就绪不代表来宾地址、服务、题目或隔离可用；恢复观察不授予进程控制或清理权限。哈希清单验证的是启动前停止态资产，不能用于断言来宾正常写入后的运行盘不变。

完整全仓回归、生产身份/停止证明采集、锁下进程接管、重置资产接续启动、GUI/CLI、真实网络 FD 继承/隔离矩阵、真实来宾、人工桌面、Wintermute 题目、跨 Mac 和发布验收未运行或未完成。App 版本沿用历史信息，本轮未核验。
