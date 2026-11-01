# Windows专用来宾IPv4端点源码与验证边界（2026-10-29）

本轮为E01/R04增加Windows x64专用虚拟来宾Wintun端点与按接口限制的Windows Firewall规则。只完成源码、临时材料生成和原生API替身验证；没有加载实际DLL、安装驱动、创建网卡、部署SSH或修改任何真实网络。不能据此关闭Windows三层/完整课程及原生隔离验收。

## 入口与部署前提

`ctflab_external.py materials-windows-ip`读取私有配置，在全新目录生成运行时、配置、摘要标记与清单。必须显式声明Wintun SHA-256和驱动版本；不包括DLL、驱动、Python或SSH，不下载、解包或执行第三方程序。不覆盖已有目录，不把材料写入ProgramData。

生产模式只接受专用Windows x64虚拟来宾。部署者须独立核验Wintun来源、许可、签名、摘要及驱动版本，在系统ProgramData下新建`CTFLabExternalIP`，放入`runtime/`、`external-config.json`、`endpoint.json`及独立核验的`wintun.dll`。根/runtime须为当前管理员SID所有，保护DACL仅含该SID与SYSTEM；配置/DLL/运行时逐文件验证。这里没有ACL修复或自动安装入口，不防御相同管理员身份恶意代码。

SSH强制命令仍固定为`ctflab-external-v1`；服务端显式选择`serve --windows-ip-guest`，只读固定根配置。普通Windows运行器仍使用原非提权配置路径，不在失败后自动切换管理员读取。必须由独立配置的已提升管理员来宾会话运行，拒绝线程模拟、未提升令牌、错误SMBIOS虚拟机UUID、错节点/cohort/checkpoint/代次或策略摘要。不能把此选项用于运行器宿主。

驱动缺失默认拒绝；材料生成时只有显式`--allow-driver-install`才在受保护标记中许可Wintun初始化驱动。初始化是未来部署到专用来宾后的行为，本轮没有执行。DLL须为固定摘要的x64 PE32+；系统WinVerifyTrust使用离线缓存、无界面模式，失败不联网补证书或降级。绝对路径加载DLL，依赖搜索只用System32；运行时文件集/摘要、DLL、机器/标记与驱动版本持续复核。

## 网络与包边界

每个认证通道使用新UUID命名与GUID创建新适配器，拒绝既有名称/GUID冲突，不打开或接管现存网卡。原生IP Helper只配置该新LUID：IPv4精确本地/32与对端/32 on-link路由；禁用转发、weak-host、路由发现/通告、自动默认路由、自动度量与动态地址配置，明确MTU。IPv6仅对已绑定族关闭自动配置/转发，不主动绑定IPv6；不添加IPv6地址或对外转送IPv6。

配置前有界读取其他网卡地址与路由，拒绝本地/对端地址重叠及具体路由冲突。既有默认路由保持；不加默认/子网路由、NAT、DNS、桥或监听。此拒绝策略不会隔离来宾其他现有网卡，不能宣称来宾所有出口已封锁。每次收发核验新适配器身份、接口标志、精确地址与路由；系统可能产生的本地组播/IPv6背景包有界丢弃，超过预算则拒绝。

Windows Firewall通过固定COM接口创建仅作用于本通道接口、精确双端IP及已声明TCP/UDP端口/ICMP类型的规则。先核对本机策略可修改、三类配置文件防火墙启用且无全局阻断、新接口不在排除列表；不修改全局策略或既有规则。新规则先禁用，读回范围一致才启用；写入回执不明时不重试，不启用无法确认的新规则。可选ICMP差错只列既有策略允许的type/code，仍须经过原双端PacketGate引用状态核对。

既有Windows Firewall规则可能更宽，新增允许规则不构成全局最小权限证明。固定SSH通道的双端包门仍按精确IP、协议、端口、长度、校验和、连接状态、ICMP引用和限额过滤；断线/丢回执不重新注入。生产Wintun收包指针无论复制成功与否均释放一次；发包失败不重试。没有自动子网转发、多跳路由、DNS集成、完整PMTU或AD整域配置。

## 关闭与未知状态

关闭尝试结束自有ring、清理已确认归属且字段未变的本通道防火墙规则，并关闭本会话新建适配器；其中一步失败仍尝试其他自有资源。规则字段改变时保留，不按组批量删除，不卸载共享Wintun驱动。COM对象与线程初始化成对释放。未知Add回执可能保留禁用的规则，未知启用/删除可能需要管理员核对；没有自动重放或清理外部资源。

响应保留`route_changed=false`并明确`route_scope=runner-host`，以说明运行器宿主没有修改；另有`guest_network_change_requested`、`network_scope`，不能拿旧布尔字段宣称来宾路由没有变化。`guest_network_cleanup_verified=false`保留关闭未确认边界；代理关闭一条端点失败仍关闭其他自有通道，不伪造清理完成。

## 验证与尚未完成

本轮使用Mac上的真实ctypes结构/指针内存、Win32/COM/Wintun替身、协议代理和临时材料目录；不调用Windows系统DLL。37项专项覆盖SDK结构尺寸/字节序、地址/路由冲突与漂移、DAD/IPv6边界、收包释放/一次发送、离线签名调用释放、接口级规则与失败清理、管理员固定根/模拟令牌拒绝、三种Windows角色、原认证序号不重放，以及实际`-I`子进程材料命令。外部代理21项、既有IPv4通道37项亦通过。首次36项中模拟令牌拒绝已正确发生，但测试误写异常父类，修正断言后的最终日志为准，原失败日志保留。

完整回归、独立白名单副本/语法/命令与保全结果在状态第118节和`output/windows-ip-20261029/final-evidence.json`补录。发布包没有更新；本地已发布Mac版本仍为0.1.3-preview.20261028，Windows候选。未做原生Windows/SSH、实际驱动安装、网卡/防火墙、跨平台包流量或断线清理验收；不重做Windows Smoke。

下一步必须在未来获授权的独立Windows来宾核对SDK/API实际返回、受保护部署/强制SSH管理员令牌、签名链缓存、驱动版本、系统自动路由、防火墙策略、真实TCP/UDP/ICMP双向与应通/禁通矩阵、失败及关闭残留。缺少原生证明时保持`native_verified=false`，43项/G0/G1/正常停机门继续开放。其余Mac硬资源限制、全部公共存储计费、更广恢复、真实课程/分析镜像及最终原生安装签名闭包仍有开发或验收，不能写成全部已完成。

## 一手接口依据

- [Wintun固定API](https://git.zx2c4.com/wintun/tree/api/wintun.h)及[运行与驱动说明](https://git.zx2c4.com/wintun/about/)
- [Windows IP Helper接口结构](https://learn.microsoft.com/en-us/windows/win32/api/netioapi/ns-netioapi-mib_ipinterface_row)与[路由创建](https://learn.microsoft.com/en-us/windows/win32/api/netioapi/nf-netioapi-createipforwardentry2)
- [Windows Firewall接口范围](https://learn.microsoft.com/en-us/windows/win32/api/netfw/nf-netfw-inetfwrule-put_interfaces)与[规则接口](https://learn.microsoft.com/en-us/windows/win32/api/netfw/nn-netfw-inetfwrule)
- [WinVerifyTrust](https://learn.microsoft.com/en-us/windows/win32/api/wintrust/nf-wintrust-winverifytrust)

原生ABI尺寸按Windows SDK固定宽度字段核对；本机内存布局验证不等于Windows调用已执行。
