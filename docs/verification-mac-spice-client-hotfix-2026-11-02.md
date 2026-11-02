# CTFLab Mac 受控 SPICE 客户端修复验证（2026-11-02）

> 历史验收快照：本文只证明所列日期、源码、运行时与命令范围；后续改动须重新核对，
> 不替代当前软件状态或真实来宾验收。

## 问题

用户打开自带 Kali 后没有图形窗口。现场发现 QEMU 的 SPICE 服务端已经正常启动，
Kali 命令行包含 `-display none`、`-spice unix=on,...`、`spicevmc` 与
`virtserialport`；但显示客户端在参数解析阶段退出：

```text
option parsing failed: Unknown option --clipboard
```

上一个 hotfix 包虽然按文件名携带 `spicy`，实际二进制是 Homebrew 通用
`spice-gtk` 客户端。它接受 `--uri`，不接受 CTFLab 运行器必传的
`--clipboard`、`--qemu-pid`、`--state-file` 与 `--display-quality`。因此
QEMU 仍在运行，却没有显示客户端窗口。这不是 Kali 镜像或图形桌面故障。

## 当前运行现场处置

本轮没有重启、停止或重置用户的 Kali。使用当前
`tools/spice_client/ctflab_spicy.c` 编译受控客户端，并连接既有 SPICE
UNIX socket 后，日志记录：

```text
CTFLAB_SPICE_STATE guest-monitors=1512x917
CTFLAB_SPICE_STATE display-ready=1
```

随后用户在外部停止了虚拟机，状态文件和 QEMU 进程消失；本轮没有执行停止操作。
残留的手工显示客户端已单独回收。由于虚拟机随后已停止，新发布包中的最终二进制
没有再次连接新的真实来宾；其能力探针、文件闭包、签名、ZIP 回读和同一源码的
现场显示连接分别验收，不把这两种证据混写成完整 E2E。

## 代码修复

- `tools/spice_client/ctflab_spicy.c` 新增只读探针
  `--ctflab-capabilities`，声明受控客户端身份、状态协议和受支持参数。
- `tools/ctflab_app.py` 新增 `probe_spice_client_support()`。构建器在接受
  `--spice-client` 后先执行探针，Homebrew 通用 `spicy` 会在复制前被拒绝。
- 动态库复制和重签名后，构建器分别检查运行时 `bin/spicy` 与
  `CTFLabDisplay.app` 内客户端；两者能力必须一致。
- `MANIFEST.runtime.spice_client_capabilities` 记录能力声明；
  `app verify` 对两个实际二进制重新执行探针，并核对清单记录。

## 产物

| 项目 | 值 |
| --- | --- |
| App | `/Users/pufei/Downloads/ctf-lab/output/spice-display-client-hotfix-20261102/mac-final-r2/CTFLab.app` |
| ZIP | `/Users/pufei/Downloads/ctf-lab/output/spice-display-client-hotfix-20261102/CTFLab-0.1.4-preview.20261102-macos-arm64-spice-client-hotfix.zip` |
| ZIP 字节 | 62,368,041 |
| ZIP SHA-256 | `67ff67e66742f8d2f483dc8382801f652df5f8e3d58692d482b882e875c862ac` |
| 版本 | `0.1.4` |
| 登记文件 | 1301 |
| 动态库 | 70 |
| QEMU 运行时资源 | 50 |
| QEMU | `11.1.0`，arm64，SPICE 服务端能力完整 |
| 签名 | ad-hoc；未公证 |

受控客户端文件摘要：

| 文件 | SHA-256 |
| --- | --- |
| `runtime/bin/spicy` | `db4b3021e6effebc82e799441488598e425febd4376f5fd4dd01edb0f20122dd` |
| `CTFLabDisplay.app/Contents/MacOS/spicy` | `78c5470d32e97faed4f793d0eaaeba8e57f2656e99d831cfbcb297f43596f96e` |

## 实际验证

- App 内 QEMU：`spice-app`、`spicevmc`、`virtserialport` 均存在。
- App 内两个客户端执行 `--ctflab-capabilities` 均返回
  `client=ctflab-spicy`、`state_protocol=CTFLAB_SPICE_STATE` 和完整参数清单。
- `app verify` 通过 1301 个登记文件、运行时引用、QEMU SPICE 门禁、受控客户端
  门禁、许可证与旁车摘要。
- `codesign --verify --deep --strict --verbose=2` 通过。
- ZIP 解压后将旁车放在 App 同级，再次执行 `app verify` 通过；两个客户端探针均通过。
- `tools.tests.test_ctflab_app`、`test_ctflab_client_input` 与
  `test_ctflab_ux` 合计 123 项通过。测试日志中
  `FAIL guest-password` 是未提供 Kali 口令时的预期环境门禁输出，不是 unittest 失败。
- 负向测试使用通用客户端替身，构建在输出目录生成前以“不是 CTFLab 受控显示客户端”
  失败。
- 用新 `app verify` 校验上一个错误 hotfix 包，按预期在
  `runtime/bin/spicy` 处以“不支持 `--ctflab-capabilities`”失败。

## 证据位置

- `output/spice-display-client-hotfix-20261102/build-r2.log`
- `output/spice-display-client-hotfix-20261102/app-verify-r2.log`
- `output/spice-display-client-hotfix-20261102/test-targeted.log`
- `output/spice-display-client-hotfix-20261102/negative-generic-client-verify.log`
- `output/spice-display-client-hotfix-20261102/mac-final-r2/CTFLab.app.sha256`
- `output/spice-display-client-hotfix-20261102/zip-check/`

## 边界

新包为 ad-hoc 签名且未公证。最终包中的客户端没有在虚拟机随后停止后再次建立真实
来宾显示；真实来宾动态分辨率仍沿用 2026-09-18 的人工历史验收。Windows 安装器
本轮没有代码变化。正式发布页和远端回下载复核结果在本文件对应 Release 资产中记录。
