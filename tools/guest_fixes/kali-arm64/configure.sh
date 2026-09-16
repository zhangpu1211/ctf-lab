#!/bin/sh
# 配置 CTFLab 自管 Kali；可在安装器 chroot 和已安装系统中重复执行。
set -eu
[ "$(id -u)" = 0 ] || { echo '请以 root 运行。' >&2; exit 1; }

# XFCE 不一定应用 virtio-gpu 随 SPICE 更新的首选模式；仅在图形用户会话中补齐。
install -d -m 755 /usr/local/libexec /etc/xdg/autostart
cat > /usr/local/libexec/ctflab-display-follow <<'PYTHON'
#!/usr/bin/python3
"""只跟随本机 SPICE 虚拟显示器；不接收网络命令、不修改持久显示配置。"""
import fcntl
import os
from pathlib import Path
import re
import subprocess
import time


def preferred_changes(text):
    output = None
    changes = []
    for line in text.splitlines():
        if line and not line[0].isspace():
            parts = line.split()
            output = (parts[0] if len(parts) > 1 and parts[1] == 'connected'
                      and re.fullmatch(r'Virtual-\d+', parts[0]) else None)
        elif output and '+' in line and '*' not in line:
            mode = line.split()[0]
            match = re.fullmatch(r'(\d+)x(\d+)', mode)
            if match and 320 <= int(match[1]) <= 8192 and 200 <= int(match[2]) <= 8192:
                changes.append((output, mode))
    return changes


def main():
    if not os.environ.get('DISPLAY') or os.environ.get('XDG_SESSION_TYPE', 'x11') != 'x11':
        return
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
    with (runtime / 'ctflab-display-follow.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        failures = 0
        while failures < 5:
            # Cocoa 启动没有此端口；不干预普通显示会话或真实物理显示器。
            if not Path('/dev/virtio-ports/com.redhat.spice.0').exists():
                time.sleep(2)
                continue
            try:
                result = subprocess.run(['/usr/bin/xrandr', '--current'],
                                        capture_output=True, text=True, timeout=3,
                                        env={**os.environ, 'LC_ALL': 'C'})
                if result.returncode:
                    failures += 1
                else:
                    failures = 0
                    for output, mode in preferred_changes(result.stdout):
                        subprocess.run(['/usr/bin/xrandr', '--output', output,
                                        '--mode', mode], timeout=3,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.TimeoutExpired):
                failures += 1
            time.sleep(1)


if __name__ == '__main__':
    main()
PYTHON
chmod 755 /usr/local/libexec/ctflab-display-follow
cat > /etc/xdg/autostart/ctflab-display-follow.desktop <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=CTFLab Display Follow
Exec=/usr/local/libexec/ctflab-display-follow
OnlyShowIn=XFCE;
NoDisplay=true
Terminal=false
DESKTOP
chmod 644 /etc/xdg/autostart/ctflab-display-follow.desktop
# 现有来宾可只更新显示适配，避免重新应用网络配置。
[ "${1:-}" != --display-only ] || exit 0

install -d -m 700 /etc/NetworkManager/system-connections
for interface in eth0 eth1; do
    if [ "$interface" = eth0 ]; then
        connection=ctflab-lab
        never_default=true
    else
        connection=ctflab-mgmt
        never_default=false
    fi
    # 使用原子替换，NetworkManager 只接受权限为 600 的连接文件。
    connection_path=/etc/NetworkManager/system-connections/$connection.nmconnection
    umask 077
    printf '[connection]\nid=%s\ntype=ethernet\ninterface-name=%s\nautoconnect=true\nautoconnect-priority=100\n[ethernet]\n[ipv4]\nmethod=auto\nnever-default=%s\n[ipv6]\nmethod=disabled\n' \
        "$connection" "$interface" "$never_default" > "$connection_path.tmp"
    chmod 600 "$connection_path.tmp"
    mv "$connection_path.tmp" "$connection_path"
done

systemctl enable ssh
# Kali 作为工作站使用，默认不充当实验网到互联网的路由器。
install -d /etc/sysctl.d
printf 'net.ipv4.ip_forward=0\nnet.ipv6.conf.all.forwarding=0\n' > /etc/sysctl.d/90-ctflab.conf
if [ -d /run/systemd/system ]; then
    sysctl -p /etc/sysctl.d/90-ctflab.conf
    systemctl start ssh
    nmcli connection reload
fi
