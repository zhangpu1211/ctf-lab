# CTFLab 0.1.1 预览发布（2026-10-12）

发布标签 `v0.1.1-preview.20261012`，GitHub 预发布：
[下载 Release](https://github.com/zhangpu1211/ctf-lab/releases/tag/v0.1.1-preview.20261012)。

内部版本仍 0.1.1，Apple Silicon、macOS 26+，ad-hoc，未公证。来源提交 33754085338dce9c850c0a0ef62fa916e1e5a8a5；后续文档同步提交不改变发布二进制。旧 Release 保留。

## 产物与验收

- 软件库入口：`/Users/pufei/Downloads/CTFLab-Library/03-软件/CTFLab-0.1.1-preview.20261012/CTFLab.app`。
- ZIP：`CTFLab-0.1.1-preview.20261012-macos-arm64.zip`，53,700,787 bytes。
- ZIP SHA-256：`7678b62c0a66b346da2eaf42969d287a25fdf30745c3a32913571e231470e5f9`。
- App 树摘要：`3ed94af70b072197bbe0e81c225abbc3a2330eff87115bae3d1b2022d0a3b685`；清单自身摘要见同目录旁车。
- 805 登记文件，70 动态库，内置 Python 3.12.15/PyYAML 6.0.3；发布副本及 ZIP 解压副本、软件库副本的 app verify 通过。

含目录式内容包、冲突预览、失败导入门控、节点回滚保护、NVRAM 自包含和失败提交保护、取消/重试及人工矩阵候选确认。已验收 Kali 登录后基本交互/SPICE 重连/正常关机，四镜像配套与协议证据；范围见 [最终使用验收](verification-content-pack-final-20261012.md) 和 [独立复核](verification-content-pack-recheck-2026-10-12.md)。完整回归基线 683 项（673 通过、10 条件跳过），发布整理没有修改运行源码。

发布副本纠正旧 app-r4 的 SBOM 归属：70 库逐字节对照 input-recovery 已验收 App 后恢复各自组件/版本，补齐 55 个许可证目录，并纠正 QEMU 为 upstream 自编译来源。恢复证据随 Release 附件 license-provenance.json 提供；运行源码和二进制与 app-r4 一致，仅元数据/许可证/签名和摘要变更。没有因元数据整理再次启动来宾，不把旧 App 摘要用于本发布 ZIP。

未验证外接屏、睡眠恢复、长时负载、跨 Mac、课程解题及公证。发布附件不含镜像或凭据。

## 中间产物清理

用户授权清理 2026-10-11/12 生成的中间文件。本轮对已替代 App、独立测试派生磁盘/NVRAM 和旧 ZIP 共 160 项移入 `/Users/pufei/.Trash/CTFLab-intermediate-20261012-233305`，没有清空废纸篓。逻辑大小约 190 GiB，APFS 实际占用可能不同，空间尚未因此释放。

可恢复清单在 `/Users/pufei/Downloads/ctflab-release-20261012/cleanup-result.json`，其中 restore_from 为实际恢复来源。日志/截图/脚本/JSON 和 App 元数据快照保留，磁盘引用路径已不再适合直接重跑历史验收。镜像库原始及已处理基盘未移动，2026-10-10 源运行时证据保留；清理前后没有运行中 CTFLab/QEMU/spicy，不操作用户实例。
