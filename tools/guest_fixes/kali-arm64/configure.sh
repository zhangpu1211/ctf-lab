#!/bin/sh
# 配置 CTFLab 自管 Kali；可在安装器 chroot 和已安装系统中重复执行。
set -eu
[ "$(id -u)" = 0 ] || { echo '请以 root 运行。' >&2; exit 1; }

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
