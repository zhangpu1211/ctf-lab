# 外部攻击机接入实现验证记录（2026-10-30）

> 本文是按日期归档的历史验收快照：记录 2026-10-30 本轮源码与本地合成验证结果；历史结果不替代当前软件状态，后续实机验收与发布以新的带日期记录为准，不回写本文。

本轮在同机外部 Kali 二层接入设计（`ctflab-external-kali-l2-design-2026-10-30.md`）基础上完成阶段 A—D 的源码实现与本地合成验证。真实 Kali、VMware、Windows 实机验收未执行（未获授权在现有 Kali 内部署助手或操作现有 VM），按矩阵保留为显式缺口。分支 `codex/release-0.1.1-preview-20261010`，起点 HEAD `0994f62`，全部改动未提交。

## 实现范围与文件

| 阶段 | 内容 | 文件 |
| --- | --- | --- |
| A 接入契约 | 登记绑定/槽位校验/hub规划兼容/策略摘要/挑战凭据/意图存储 | `tools/ctflab_external_attach.py` |
| B 帧协议与门禁 | 记录编解码/帧门禁/配额桶；Kali 助手材料生成 | `tools/ctflab_external_l2.py`、`tools/ctflab_kali_attach.py` |
| C 宿主集成 | 交换机认证接入口；QEMU hub 预留口；SSH 固定入口；双向中转 | `tools/ctflab_network.py`、`tools/ctflab_qemu_driver.py`、`tools/ctflab_remote.py`、`tools/ctflab_external_attach.py` |
| C 计划层 | 场景 v2 网段可选 external 槽位（含地址/MAC 查重） | `tools/ctflab_scenario_v2.py` |
| D 界面 | 桥接 4 动作；React 卡片与模型；Mac 卡片与展示模型 | `tools/ctflab_desktop_bridge.py`、`desktop/src/ExternalAttach.jsx`、`desktop/src/external-attach-model.mjs`、`gui/GuiCore.swift`、`gui/GuiApp.swift` |

## 实际执行的验证（2026-10-30，本机 macOS/arm64，全部合成或回环）

1. 新增单元测试：
   - `python3 -m unittest tools.tests.test_ctflab_external_attach` → 17 项通过（契约校验负向、旧格式兼容、挑战令牌、意图存储、v2 槽位集成、交换机接入口双向转发/门禁拒绝/计数/第二会话拒绝/错误令牌拒绝、中转 gated 转发与丢弃）。
   - `python3 -m unittest tools.tests.test_ctflab_external_l2` → 15 项通过（记录编解码上限、流序号、VLAN/IPv6/分片/伪造源/越权目的/ARP 绑定拒绝、回程门禁、令牌桶/广播桶/字节与时长配额）。
   - `python3 -m unittest tools.tests.test_ctflab_kali_attach` → 6 项通过（材料摘要一致、拒绝覆盖、无任意命令路径、sshd 转发禁用、固定命令参数）。
   - `python3 -m unittest tools.tests.test_ctflab_desktop_external_attach` → 5 项通过（状态/保存/清除/材料、越权网段拒绝、坏登记拒绝）。
2. 受影响既有套件：`test_ctflab_network`+`test_ctflab_external` 31 项、`test_ctflab_platform` 11 项、`test_ctflab_scenario*` 132 项、`test_ctflab_scenario_v2` 12 项通过（external 为可选字段，旧清单语义不变）。
3. 桌面前端：`cd desktop && npm test` 77 项（含新增 `external-attach-model.test.mjs` 8 项）通过；`npm run build` 成功。Swift：`/usr/bin/swiftc -typecheck gui/GuiCore.swift gui/GuiApp.swift` 通过；`swiftc -o /tmp/... gui/GuiCore.swift gui/GuiCoreTests.swift` 运行 397 项检查 0 失败（含新增 8 项）。
4. 交换机接入口回环冒烟（合成 ARP 帧）：Kali→实验广播经门禁转发至登记节点；实验→Kali 单播经回程门禁送达；未登记源 MAC egress 拒绝；伪造源 MAC ingress 拒绝并计入 `dropped_external_gate`；错误秘密认证被拒；已有会话时第二个连接不被接受。
5. 完整本地回归：`python3 -m unittest discover -s tools/tests`（结果见状态第 146 节收口记录）。

## 明确未验证（实机门槛，不因代码完成而宣称可用）

- 真实 Linux 内核 TAP 创建/netns setns/SCM_RIGHTS 传 fd/异常清理与原管理网保全（`ctflab-kali-attach` 助手为材料级实现）。
- Mac＋VMware Fusion＋Kali ARM64、Windows11 x64＋Workstation＋Kali x64 端到端；UTM/VirtualBox 未实测。
- 两类后端的真实帧往返（旧交换机模式需 v1/运行实例，未授权操作；hub 模式需真实 QEMU 启动新代次）。
- 扫描吞吐、SSH 队头阻塞、2 小时会话、睡眠/暂停恢复、快照后重连等性能与故障矩阵。
- Parallels/UTM/QEMU 来宾身份策略组合；图形工具（浏览器/Burp）真实 netns 归属。
- 桌面连接按钮：故意未启用（`connect_supported=false`），实机验收组合通过后才开放；当前仅登记/预览/材料。

## 2026-10-31 增补：规划链贯通与修复（同分支、HEAD 0994f62 不变）

在上表基础上继续完成 E01 可实施收尾，全部为本地合成/回环验证：

1. **hub 后端生产链闭合**：`ctflab_desktop_bridge.import_course` 为声明 external 槽位的网段分配预留口（二成员自动转 hub 规划），修复"槽位被静默丢弃"；`validate_hub_networks` 反向强制"声明槽位 ⇒ 端口规划必须携带 external 预留口"，并修复 external 端口在扁平化中被双重计入导致的端口碰撞。
2. **连接凭据修正**：CLI `connect` 不再使用登记内的契约级 ssh 引用，改为独立 `--ssh-config`（完整 `ctflab_remote` schema），新增 `bind_ssh_config`：`server_uuid == 登记 node_uuid` 绑定＋固定入口 `ctflab-external-l2-v1` fail-fast 预检。
3. **CLI 入口**：`ctflab external-attach materials|check` 子命令（只读/仅新材料目录；私有 JSON 按 0600 约定，guard 校验私有权限）。
4. **验证**：`test_ctflab_external_attach` 20 项（新增 3 项 ssh 绑定）、`test_ctflab_desktop_bridge` 36 项（新增 import 槽位预约贯通测试）通过；CLI 冒烟（materials/check 正反向、check 输出 attachment/policy 摘要）通过；桌面 77 项＋构建通过；完整回归见状态第 147 节。
5. **生产路径结论**：CLI `scenario prepare` 仅接受 v1 清单（按设计保持原样）；生产 v2 路径走 hub 后端。交换机认证口由测试与显式编排消费，"v2 走交换机"的生产路径不存在——这是按设计的现状，不是缺口。实机门槛（真实 Kali/宿主组合）仍未验证。

## 2026-10-31 增补（二）：连接/断开链、身份策略与合成端到端验收

设计剩余可实施项在本轮全部落地（同分支、HEAD `0994f62` 不变；全部本地合成/回环验证）：

1. **来宾身份策略**：`ctflab_external_attach.GUEST_IDENTITY_FAMILIES` 覆盖 VMware/Parallels/UTM-QEMU/VirtualBox/Hyper-V 五族 DMI 组合；`validate_registration` 强制厂商/产品命中策略并派生 `identity_family`，策略外组合按 `identity-unknown` 拒绝——不关闭身份检查、不放宽为仅凭 IP。
2. **连接/断开动作链**（设计§8/§9）：桥接新增 `external-attach-connect/disconnect`；connect 仅在"登记有效＋本代次 profile 已预留口＋无进行中会话"时开放（`connect_supported` 按前置条件计算），派生会话 UUID、持久化会话记录（backend/endpoint/ssh-config 引用）并派生 `external-relay` 监督工作进程；disconnect 按**命令行身份核验**（非裸 PID）终止中转，状态机 idle→connecting→connected→disconnected/unknown（进程消失即惰性落 unknown，允许显式清除或重连），断开不停止 VM、不杀来宾工具。
3. **合成端到端验收**（新 `tools/tests/test_ctflab_external_attach_acceptance.py`，2 项）：真实交换机进程＋真实接入口认证＋真实中转帧泵＋来宾替身通道——①双登记节点收到 ARP 发现帧、节点 A 收到 ICMP 服务访问帧、节点 B 回连帧经回程门禁到达来宾通道、受控断开后外部口 `frames_out` 不再增加而内部 A→B 转发继续；②伪造源 MAC 的发现帧在中转门禁丢弃、零帧送达登记节点。未知单播洪泛为标准 L2 语义，断言按洪泛语义校验。
4. **双端 UI 收口**：React 卡片新增连接/断开按钮（按 `canConnect/canDisconnect` 前置门控）与"诊断与协议"展开区（协议版本/身份家族/槽位预留口/限额/策略摘要，不含宿主路径与凭据）；模型新增 `sessionView/diagnosticsView`，测试 11 项通过。Mac `sceneGenericCall` 直连同一桥接动作："读取外部攻击机状态"按钮＋卡片实时渲染（Swift 类型检查通过、397 项检查 0 失败）。
5. **CLI 冒烟**：`ctflab external-attach materials|check` 正反向通过；`external-attach-connect` 的 `--ssh-config`/`bind_ssh_config`（server_uuid 绑定＋固定入口预检）经 3 项单元测试覆盖。

**验证命令与结果（2026-10-31）**：`test_ctflab_external_attach` 20 项、`test_ctflab_desktop_external_attach` 11 项（身份策略 3＋会话链 4＋既有 4）、`test_ctflab_external_attach_acceptance` 2 项、`test_ctflab_external_l2` 15 项、`test_ctflab_kali_attach` 6 项通过；桌面 `npm test` 80 项（新增 3 项会话/诊断门控）＋构建通过；Swift 397 项。完整回归与最终数字见状态第 148 节。

**仍属实机门槛（不变）**：真实 Kali 内核 TAP/netns/助手部署与原管理网保全；Mac＋Fusion＋Kali ARM64、Windows11 x64＋Workstation＋Kali x64 端到端；真实 SSH 通道吞吐/队头阻塞/睡眠恢复；图形工具 netns 归属。连接链在真实环境验证前，按钮可用但连接目标须为已授权测试实例。
