# Smoke 与 NoPort 独立复核（2026-10-13）

> 历史验收快照；不替代当前软件状态。后续使用前仍须核对现有资产和运行实例。

证据根：`/Users/pufei/Downloads/ctflab-clarify-20261013`。本轮只用已发布 App 的包内 CLI、独立测试状态和回环实验网；未操作用户已有虚拟机或原始 OVA。工作区没有运行器代码变更。

## 旧三节点的目录结构

`CTFLab-Library/02-已处理/DISTRIBUTION.json` 为历史 schema 1 清单，在同一目录平铺登记 Kali、Smoke、Basic 的基盘及 Kali NVRAM。新适配镜像是各自子目录中的 schema 2 自包含内容包，附带本机可安装的 profile、说明和基盘。两种形式对应不同制作/导入机制；旧三节点不必为了目录外观迁移，更不能只移动文件而不更新清单与校验。

## Smoke 是否相同

旧 `smoke` 与新 `smoke-ova` 是同一 SmokePing 系统/应用的不同交付配置，不是已证实的两道不同题。离线提取两份根分区后，`/etc/hosts`、`/etc/apache2/httpd.conf`、`/etc/smokeping/config`、`/usr/share/webapps/smokeping/smokeping.cgi` 及 `/etc/fstab` 的内容 SHA-256 逐项一致；见 `smoke-file-comparison.json`。新源盘的 ext4 日志未回放，先对**派生的根分区副本**执行 `e2fsck -y`，再用 `debugfs cat` 读取；源镜像未修改。整盘 `qemu-img compare` 返回不同，因此不能称两份磁盘逐字节相同。旧 `smoke` 用 .20 和原有硬件/profile，新 `smoke-ova` 用 .56 和适配后的硬件/profile；原 SmokePing 服务内容在本次抽查范围内相同。保留两个入口只因旧分发兼容和新 OVA 单包交付，不建议学生将两者当作不同靶题。

## NoPort 渗透验证

目标是本轮独立安装的 `noport`，状态目录 `ctflab-clarify-20261013/noport-state`，实验网 `192.168.242.50`，客户端只连 `127.0.0.1:23400` 的本轮交换机，源 IP `.250`。已发布 App 包内 CLI 启动，不使用宿主端口映射或桥接。`noport-http-baseline.json` 记录 Web 初始状态；`noport-rce-id.json` 与 `noport-foothold-checks.json` 记录对预存 `/1.php` 发出一次受控 POST 命令执行检查，HTTP 200 响应为 `uid=101(apache) gid=102(apache) groups=82(www-data),102(apache),102(apache)`，主机名 `noport`。`sudo -n -l` 仅列出 `(root) NOPASSWD: /sbin/reboot`。由此已动态证实**无认证 Web 命令执行、取得 apache 权限**；未证实 root、flag 或预期解题路径，亦未执行重启、持久化或外联。

离线源盘检查显示 `/var/www/localhost/htdocs/1.php` 原有 `eval($_POST[1])`；`source-state/images/noport/base-c34923c71846.qcow2` 与本轮 `adapted.qcow2` 的 `qemu-img compare -f qcow2 -F qcow2` 返回 `Images are identical.`，所以该文件不来自适配修改。`noport-source-redacted.json` 只保存脱敏的源码定位。原镜像缺少 `/etc/iptables/rules.v4` 的问题仍在；用户此前要求保留原样，本轮未补规则。该问题可能影响原设计的防火墙边界，因此 NoPort 仍列为兼容候选，不能凭已取得的 Web 权限宣布整题完整可用。

正常关机仅针对本轮状态中的 NoPort。`final-instance-check.json` 显示本轮 QEMU PID 57804 已退出、`run.json` 已清除。源盘、已处理包、已发布 App 未改；本轮无提交、推送或发布。下一步若要判定“完整通关”，需有题目预期目标或授权在此独立实例继续验证 root/flag 路径，并记录原防火墙缺件对难度的影响。
