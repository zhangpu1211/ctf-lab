# Kali 小幅移动唤醒：隔离构建与验收

## 状态与范围

这是尚未来宾编译、安装及认证验收的源码候选，不是已生效修复。
当前独立实例手动大幅移动可出现密码框，解锁后桌面及点击正常；
本次不以降低安全性换取恢复速度，不关闭密码、自动锁屏或认证。

源码来自 [Xfce 官方归档](https://archive.xfce.org/src/apps/xfce4-screensaver/4.20/)。
固定版本 4.20.2，归档 SHA-256 为
`5032f60a31df5e50a80512e301b595be5ea6a6bd762cdd95cacc24cbd29a01d7`。
生成器只改 `gs-window.c` 两行真实鼠标移动门槛，原文件另有独立哈希门禁。
源码、许可证与补丁一并保留，不下载未固定版本的依赖或执行任意来源脚本。

## 准备与构建

在 Mac 上准备离线包，使用全新输出目录：

```bash
python3 tools/guest_fixes/kali-arm64/screen_wake_build.py prepare \
  /path/to/xfce4-screensaver-4.20.2.tar.xz --out /path/to/new-build-bundle
```

将完整包与 `screen_wake_build.py`、`screen_wake_patch.py` 放在 Kali 同一目录；
两份脚本相邻即可导入。由普通用户执行：

```bash
python3 screen_wake_build.py build ./new-build-bundle
```

脚本拒绝 Mac、非 ARM64 和 root。构建前重新核验原始归档、每份源码与补丁，
不把可编辑的清单视为信任根；额外源码和符号链接也会被拒绝。
需已有 C 编译器、Meson、Ninja、pkg-config 及上游 Meson 声明的开发依赖。
缺依赖直接报错，不自行执行 sudo、apt 或 pip。认证固定 PAM，X11 启用，
systemd 会话管理保留；Meson 禁止自动下载 subproject。

生成 `build/`、`stage/`、`BUILD.json`。`stage/` 只是私有安装树：未写入 `/usr`、
`/etc`，未启动、停止或替换系统屏保。失败保留构建诊断但不生成成功记录；
再次构建需重新准备全新目录，不能把半成品当成合格产物。
`BUILD.json` 即使存在，`runtime_verified` 仍为 false。

## 部署前硬门槛

构建不是安装。先在可恢复独立 overlay 内确认发行版原包版本、二进制和
libexec 路径、PAM 服务名、原包校验、构建动态依赖及发行版补丁差异。
上游包不能未经对照直接覆盖 Kali 包；构建候选不能作为用户默认屏保。
部署须保留发行版包与回滚副本，不能全量复制 staging 的 `/etc` 内容覆盖认证。
当前工具故意没有无人值守安装或卸载命令，避免半部署破坏锁屏。

仅对本次测试实例验收：真实鼠标移动 8～24 像素后显示密码框，但保持锁定；
错误密码不能进桌面，正确密码由用户手动输入；轻微抖动不反复唤醒。
再验证 DPMS 息屏、Command+Tab、缩放往返、鼠标点击及自动锁屏时间不变。
测试失败立即退回发行版屏保，并正常注销/重新登录确认原锁屏工作。
通过之前不固化基础镜像、不更新公开分发包。

## 当前实际阻塞

当前尚没有已核验的来宾 SSH 主机密钥及已认证构建会话。
不会接受未核验主机密钥、提取密码或使用不可靠的合成键盘输入 sudo 命令。
需要用户在独立 Kali 手动核对指纹并完成登录，或自行运行离线构建步骤。
这不是已有代码通过测试即可绕过的条件。
