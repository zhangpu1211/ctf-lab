# CTFLab Mac SPICE 发布包修复验证（2026-11-02）

> 历史验收快照：本文只证明所列日期、源码、运行时与命令范围；后续改动须重新核对，
> 不替代当前软件状态或真实来宾验收。

## 问题与修复范围

用户复现 v0.1.4 Mac App 启动 Kali 时报告缺少 QEMU SPICE 显示后端与
`spicevmc` chardev。只读检查确认原发布包包含 `spicy` 客户端，却打包了不支持
SPICE 的 Homebrew QEMU；`-machine none -display help` 仅有
`none/curses/cocoa/dbus`，且 QEMU 未链接 `libspice-server`。

本轮修复不涉及镜像内容：

- 构建器在收到 `--spice-client` 时必须探测源 QEMU 的 `spice`/`spice-app`、
  `spicevmc` 与 `virtserialport` 能力；
- 复制、改写动态库并重签名后，再次探测 App 内 QEMU；
- `app verify` 重新执行相同探测，并核对
  `MANIFEST.runtime.spice_capabilities`；
- 任一能力缺失即失败，不允许客户端与无 SPICE QEMU 组合发布。

## 被测产物

| 项目 | 值 |
| --- | --- |
| App | `/Users/pufei/Downloads/ctf-lab/output/spice-hotfix-20261102/mac-final-r2/CTFLab.app` |
| 版本 | `0.1.4` |
| App 树 SHA-256 | `fb324cd19f9cb74ad4fdd16d287d5683d342f39ef70464dc3fb2222509419e05` |
| MANIFEST SHA-256 | `1581edd0fa5746f69edc4886494696e55224c7bdd9ff26e4ccf71b0e2c99515d` |
| 登记文件 | 1301 |
| 动态库 | 70 |
| QEMU 运行时资源 | 50 |
| QEMU | `11.1.0`，arm64，upstream source build |
| SPICE 客户端 | 同包 `spicy` 与 `CTFLabDisplay.app` 包装入口 |
| 签名 | ad-hoc，严格校验通过；未公证 |
| 许可证文本 | 完整 |

关键内置文件：

| 文件 | 字节 | SHA-256 |
| --- | ---: | --- |
| `runtime/bin/qemu-system-aarch64` | 37,288,960 | `7235949f45f773bdd494d1ef0b9eb229ee0f623e5b71db4f635ff884213c6026` |
| `runtime/bin/spicy` | 105,392 | `b8741e7c37c1ddd7a8b2cca8ba7ab628dc3d6ff45aa57e6972fd8d9fd927d9de` |
| `runtime/lib/libspice-server.1.dylib` | 1,239,728 | `f96523b60d2b17e9d79f4793b514649a113b7e67b48271a9211eb17150d726c8` |
| `runtime/lib/libspice-client-gtk-3.0.5.dylib` | 158,944 | `80d769ef996fd2b14ad96dba2deb4dc42b55673a15efcdd90e98c650e2dcc2c2` |

## 实际验证

使用 App 内真实 QEMU 执行：

```sh
QEMU="$APP/Contents/Resources/runtime/bin/qemu-system-aarch64"
"$QEMU" -machine none -display help
"$QEMU" -machine none -chardev help
"$QEMU" -machine none -device help
otool -L "$QEMU"
```

结果均通过：

- `-display help` 包含 `spice-app`；
- `-chardev help` 包含 `spicevmc`；
- `-device help` 包含 `virtserialport`；
- `otool -L` 含 `@loader_path/../lib/libspice-server.1.dylib`。

以该 App 的真实控制运行时调用 `LabManager.probe_spice()`，得到：

```json
{
  "spice_display": true,
  "spicevmc": true,
  "virtserialport": true,
  "client": true,
  "errors": [],
  "supported": true
}
```

`app verify` 通过 1301 个登记文件、运行时引用、SPICE 能力门禁、许可证文本与
ad-hoc 签名校验。`codesign --verify --deep --strict` 返回成功。

负向验证使用原 v0.1.4 无 SPICE 运行时作为输入，并以新构建器生成新 App；构建器
在生成输出目录前失败：

```text
错误：请求了 --spice-client，但 QEMU 运行时缺少 SPICE 动态分辨率能力：
QEMU spice 显示后端不可用；QEMU spicevmc chardev 不可用
```

`python3 -m unittest tools.tests.test_ctflab_app -v` 共 70 项通过。基类中的
`FAIL guest-password` 是未提供 Kali 口令时的预期环境门禁输出，不计作测试失败。

## 证据位置

- `output/spice-hotfix-20261102/build-r2.log`
- `output/spice-hotfix-20261102/app-verify-r2.log`
- `output/spice-hotfix-20261102/test-ctflab-app.log`
- `output/spice-hotfix-20261102/negative-no-spice.log`
- `output/spice-hotfix-20261102/mac-final-r2/CTFLab.app.sha256`

## 边界

本轮没有启动、停止或重置用户 Kali，也没有删除镜像；因此没有把命令行能力探测
表述成新的真实来宾动态分辨率验收。历史 SPICE 窗口跟随与来宾 `xrandr` 自动模式
证据仍见 `verification-display-network-2026-09-16.md`。修复后的实际 GUI 启动和
动态分辨率仍需用户以现有镜像在本机做一次确认。Mac App 为 ad-hoc 签名，未公证。
