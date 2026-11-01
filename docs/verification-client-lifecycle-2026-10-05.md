# 2026-10-05 客户端生命周期、TCP 认证与启动候选修复

> 历史验收快照：结论、测试数与产物路径只对应本记录日期及被测候选，不替代当前软件状态；部分本机旧产物已清理。当前使用、分发与未验证边界见[当前状态](ctflab-current-status.md)。原有失败和范围限制保留，文档整理不补做或升级验收。

本轮修改位于 /Users/pufei/Downloads/ctf-lab，保留已有未提交改动。
没有操作用户虚拟机或向宿主桌面注入输入。实际客户端启用剪贴板时会读取宿主
文本，但本次没有改写剪贴板或记录其内容。已生成新的本地候选 App，已发布 App 未更新。

## 行为变化

1. macOS 剪贴板后台线程只处理可取消的 pbpaste/pbcopy 子进程与缓存；所有
   agent 查询和 SPICE 发送由 GTK 主线程上的固定 timer 完成。只保留最新待发
   内容，agent 尚未就绪时保留缓存。来宾更新期间丢弃过时采样，抑制回声。
2. 退出先移除 timer、断开剪贴板信号，再取消子进程通信并回收子进程；有界等待
   thread_done 后才 join 和释放同步设施。两秒超时时保留静态状态到进程退出，
   不清理活跃线程仍在使用的锁。未启用剪贴板时清理为空操作。
3. TCP 口令仍在 URI 之后设置。删除无证据的 secret 延迟加载解释与固定 1.5 秒
   等待。认证探针修正 capability 位，按完整长度读取分片，要求明确的认证应答；
   EOF 和超时不再算成功。完整 E2E 要求 display-ready=1，不只检查 ESTABLISHED。
   E2E 读取来源基盘登记，在新建状态目录创建 overlay/NVRAM 副本，只清理本测试节点。
4. probe 先分类截图再判断是否结束；PXE 直接交给矩阵回退。未知画面即使有 DHCP
   和显示活动，也不能命中启动矩阵；需要登录画面或协议服务响应。
5. 修正计划与历史记录的矛盾状态，纳入此前被忽略的专项文档。旧 WebServer 报告
   留作历史证据，不能继续宣称磁盘引导通过。
6. macOS 的 QEMU 存活探测读取进程状态，僵尸进程按已退出处理，不再仅凭
   kill(pid, 0) 成功保留客户端窗口。新增真实 fork/未回收子进程测试。
7. App 构建从来源二进制位置解析动态库闭包，支持来源已经使用相对依赖的运行时；
   不再从旁边 lib 尚为空的目标副本解析。新增相对依赖重新打包并运行的测试。

## 已运行验证

- macOS C 实现运行测试 8 项：禁用剪贴板清理、40 次反复启停、待发送内容清理、
  agent 未就绪缓存保留、中文多行写入和回声抑制、阻塞读取消、阻塞写取消。
  测试以替代 pasteboard 程序执行，启用 AddressSanitizer、UndefinedBehaviorSanitizer
  和 G_DEBUG=fatal-warnings；验证子进程已回收、退出后 timer 不访问已清理状态，
  并验证活跃/不存在/未被父进程回收的僵尸 PID 三种状态。
- 实际 probe 调用链的 PXE + DHCP 失败回退与停止本次节点，未知画面矩阵继续下一
  候选；覆盖此前 WebServer 退化 OCR 样本。
- TCP 分片读取、EOF/超时拒绝成功、capability/机制位和明确应答解析测试。
- 使用本机既有 App 内的 SPICE QEMU，关闭显示、无来宾磁盘与网卡，三轮正确
  ticket 返回 0、错误 ticket 返回 7；临时进程与文件均由测试回收，日志不含 ticket。
- 客户端严格编译通过：clang -Wall -Wextra -Werror，链接本机 spice-gtk/GTK3。
  显式指定 -mmacosx-version-min=26.0，避免当前 macOS 27 SDK 默认抬高最低版本。
- 完整回归见下节；测试打印的 guest-password 失败来自预期的缺少凭据负向用例，
  不属于真实来宾 E2E，也不是回归失败。

## 本地 App 与真实来宾验证

- 候选路径：`/Users/pufei/Downloads/ctflab-app-local-20261005/CTFLab.app`，
  版本 0.1.0、最低系统配置 26.0、799 个登记文件、72 个动态库、50 个 QEMU 资源。
  QEMU 11.1.0 与 Python 3.12.14 复用既有受控运行时副本，PyYAML 6.0.3 wheel
  已核对登记哈希；本次没有从零重新编译 QEMU。客户端从当前源码重新编译。
  签名为 ad-hoc，未公证、未公开发布。本机实际系统为 macOS 27.0。
- 新客户端 TCP 三轮认证/显示通道验证通过：ESTABLISHED、display-ready=1、
  正确 ticket 返回 0、错误返回 7、日志/命令/状态不含 ticket 明文。
  该测试提前停止，不能据此认定完整引导或桌面操作已通过。
- 最终候选使用包内 Python/QEMU/客户端、最小 PATH、独立状态目录与派生盘。
  UNIX 主路径两轮（剪贴板开关分别关闭和开启）均达到图形登录界面，DHCP/SSH
  横幅通过，健康就绪耗时分别为 25.87 秒与 25.26 秒。这不是登录桌面后的
  剪贴板正/负向验证，也不是与其他虚拟机软件的性能对比。
- 两轮向本测试 QEMU 发送 QMP quit 后，客户端都自行退出（退出码 0），日志
  记录 qemu-exited。验收脚本只 waitpid 回收已退出的客户端，没有以强杀冒充
  自动退出。QMP quit 不是来宾正常关机，本次没有验收正常关机流程。
- 测试节点与交换机已停止；原始基盘/RAW NVRAM 哈希和最终 App 树哈希未变。
  最终 App 树 SHA-256：`4c7af264f323713a33b996e69fff0f84e22f36544230a2f4c979838c467d2ea3`。
  包内客户端 SHA-256：`32e0d6857b7981fe2ae5027345557d9183093cbdd113313d1ac6c5caafe2a8fc`。
- 证据位于同目录 `evidence/app-check-r3.json` 与两张 `kali-clipboard-*.png`。
  首次旧解释器验收曾黑屏/健康超时，原因未确定；随后包内解释器复测到达登录
  界面，发现并修复僵尸 PID 判断问题。早期失败记录与旧 App SPICE、新 App Cocoa
  的对照证据保留，不能将首次超时直接归因于 macOS 27 或称作已解决。
- 验收脚本绕过启动器时曾产生字节码缓存；已按照原 MANIFEST 哈希从未改动的
  同版副本还原被重写文件，额外缓存移至验收目录保留。后续脚本对子进程也设置
  PYTHONDONTWRITEBYTECODE=1。既有 App 的自身校验与新旧 App 签名校验均通过。

## 当前限制与下一步

本次改造后的真实 Kali 双向剪贴板、窗口关闭/断连交互，以及 TCP 模式的完整
桌面链路尚未重测。QEMU 退出后客户端自动退出已由最终本地 App 实测。
历史来宾 E2E 与本次无界面生命周期测试分别提供证据。
全屏分辨率跟随、长拖拽、GUI 镜像向导、多显示器和跨 Mac 验收仍未完成。

当前没有同机同配置的 VirtualBox/UTM 性能测量。Kali ARM64 使用 HVF，而 x86
靶机在 Apple Silicon 上使用 TCG。后续性能验收应分别记录冷启动耗时、工具
启动耗时、交互延迟、CPU/内存、窗口缩放与全屏稳定性；跨架构结果不得与同架构
硬件虚拟化结果混在一起比较。

## 完整回归

2026-10-05：发现 396 项，执行通过 390 项、跳过 6 项，耗时 164.177 秒，退出码 0。
其中 5 项因历史 UTM 交付目录缺失跳过，1 项为完整 Kali TCP 图形 E2E 环境门控；
真实 QEMU 无界面认证测试本次启用并通过。C 严格编译与 git diff --check 均通过。

复现命令（QEMU 路径须指向本机支持 SPICE 的受控运行时）：

```bash
CTFLAB_SPICE_AUTH_QEMU=/path/to/CTFLab.app/Contents/Resources/runtime/bin/qemu-system-aarch64 \
  /opt/miniconda3/bin/python3 -m unittest discover -s tools/tests -q
```

未设置该变量时，另有 1 项协议集成测试按明确原因跳过。修复与文档留在工作区，
未提交、推送或发布；保留原有用户改动。
