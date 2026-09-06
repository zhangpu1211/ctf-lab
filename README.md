# CTFLab for Mac M

CTFLab 是面向 Apple Silicon Mac 的本地虚拟靶场运行器。它使用 QEMU 管理 ARM64 与 x86_64 客体，以不可变 QCOW2 基盘和可重置 overlay 保存运行状态，并通过仅绑定回环地址的用户态二层交换机连接 Kali 与靶机。

当前仓库只包含运行器、候选配置、来宾修复模板、测试和设计文档，不包含虚拟磁盘、账号凭据、课程题库或成绩数据。

## 当前能力

- 导入 QCOW2、VMDK、VDI、VHD/VHDX、RAW、OVA；
- `inspect` 只读识别 VMDK/OVF、MBR/GPT/EFI 和候选虚拟硬件；
- `onboard` 生成带置信度、警告和人工复核状态的白名单配置；
- `probe` 收集 QMP 状态、截图、DHCP 与 HTTP/SSH 协议证据；
- x86_64 在 Mac M 上使用 QEMU TCG，ARM64 使用 HVF；
- 不覆盖原始镜像，运行时写入独立 QCOW2 overlay；
- 跨进程文件锁保护导入、启动、停止、重置和候选配置生成，避免多终端竞争；
- 回环 TCP 二层交换机提供固定 DHCP，默认不把脆弱靶机接入物理局域网。

## 快速开始

环境要求：macOS Apple Silicon、Python 3.10+、PyYAML、Homebrew QEMU。

```bash
./tools/ctflab doctor

# 已知配置
./tools/ctflab import smoke /path/to/smoke.qcow2
./tools/ctflab run smoke
./tools/ctflab health smoke

# 未知镜像候选适配
./tools/ctflab inspect /path/to/machine.ova
./tools/ctflab onboard /path/to/machine.ova --id machine-1
./tools/ctflab probe machine-1 --timeout 180

./tools/ctflab stop --all
./tools/ctflab reset smoke
```

自动探测输出的是候选，不是启动保证。磁盘文件通常无法可靠提供客体 CPU 架构、来宾网卡名、登录状态和服务清单；低置信度字段必须核对来源，probe 截图也必须排除 UEFI Shell 或错误画面。

## 测试

```bash
python3 -m unittest discover -s tools/tests -v
python3 -m py_compile tools/ctflab.py tools/ctflab_inspect.py tools/ctflab_network.py
```

## 文档

- [第一阶段快速使用](docs/ctflab-phase1-quickstart.md)
- [完整实施计划与路线图](docs/ctflab-mac-mvp-implementation-plan.md)

## 安全边界

- 原始镜像只读，所有来宾修复写入可恢复的派生副本；
- 在线元数据不能传入任意 QEMU 参数；
- 虚拟磁盘、默认凭据和运行日志不得提交到本仓库；
- 只有完成冷启动、显示/登录、网络、重启与目标服务验证的镜像，才能标记为已验证交付。
