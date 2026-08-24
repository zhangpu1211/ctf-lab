#!/usr/bin/env python3
"""CTFLab 回环 TCP 二层交换机和最小 DHCP 服务。

每个 QEMU socket 网卡都连接本机 TCP 端点。服务按 QEMU 的四字节长度前缀
协议转发以太网帧，并响应 DHCP Discover/Request。实验流量不会发往物理局域网，
不需要 root；宿主机端口映射由来宾的第二张受限 user-net 网卡承担。
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import signal
import socket
import struct
import sys
import time
from datetime import datetime, timezone


HUB_HOST = "127.0.0.1"
SERVER_IP = "192.168.242.1"
SUBNET_MASK = "255.255.255.0"
LEASE_SECONDS = 86400
MAGIC_COOKIE = b"\x63\x82\x53\x63"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def parse_options(options: bytes) -> dict[int, bytes]:
    result: dict[int, bytes] = {}
    index = 0
    while index < len(options):
        option = options[index]
        index += 1
        if option == 0:
            continue
        if option == 255:
            break
        if index >= len(options):
            break
        length = options[index]
        index += 1
        if index + length > len(options):
            break
        result[option] = options[index:index + length]
        index += length
    return result


def mac_text(raw: bytes) -> str:
    return ":".join(f"{value:02x}" for value in raw[:6])


def mac_bytes(text: str) -> bytes:
    parts = text.lower().split(":")
    if len(parts) != 6:
        raise ValueError(f"MAC 地址格式错误：{text}")
    return bytes(int(part, 16) for part in parts)


def dhcp_request_from_frame(frame: bytes) -> tuple[str, bytes, int, int, int, dict[int, bytes]] | None:
    if len(frame) < 14 + 20 + 8 + 240:
        return None
    if struct.unpack("!H", frame[12:14])[0] != 0x0800:
        return None
    ip_start = 14
    version_ihl = frame[ip_start]
    if version_ihl >> 4 != 4:
        return None
    ip_header_length = (version_ihl & 0x0F) * 4
    if len(frame) < ip_start + ip_header_length + 8:
        return None
    if frame[ip_start + 9] != 17:
        return None
    udp_start = ip_start + ip_header_length
    src_port, dst_port, udp_length, _checksum = struct.unpack("!HHHH", frame[udp_start:udp_start + 8])
    if src_port != 68 or dst_port != 67:
        return None
    payload = frame[udp_start + 8:udp_start + udp_length]
    if len(payload) < 240 or payload[236:240] != MAGIC_COOKIE:
        return None
    op, htype, hlen, _hops = struct.unpack("!BBBB", payload[:4])
    if op != 1 or htype != 1 or hlen < 6:
        return None
    xid = struct.unpack("!I", payload[4:8])[0]
    flags = struct.unpack("!H", payload[10:12])[0]
    chaddr = payload[28:44]
    options = parse_options(payload[240:])
    message_type = options.get(53, b"\x00")[0]
    requested_ip = options.get(50, b"\x00\x00\x00\x00")
    return mac_text(chaddr), chaddr, xid, flags, message_type, {50: requested_ip, **options}


def make_option(code: int, value: bytes) -> bytes:
    return bytes((code, len(value))) + value


def build_dhcp_frame(
    request_frame: bytes,
    chaddr: bytes,
    xid: int,
    flags: int,
    message_type: int,
    assigned_ip: str,
) -> bytes:
    payload = request_frame[14:]
    ip_start = 0
    ihl = (payload[0] & 0x0F) * 4
    udp_start = ihl
    request_payload = payload[udp_start + 8:]
    secs = request_payload[8:10]
    client_flags = struct.pack("!H", flags)
    bootp = b"".join(
        (
            b"\x02\x01\x06\x00",
            struct.pack("!I", xid),
            secs,
            client_flags,
            b"\x00" * 4,
            ipaddress.IPv4Address(assigned_ip).packed,
            b"\x00" * 8,
            chaddr[:6].ljust(16, b"\x00"),
            b"\x00" * (64 + 128),
        )
    )
    options = b"".join(
        (
            MAGIC_COOKIE,
            make_option(53, bytes((message_type,))),
            make_option(54, ipaddress.IPv4Address(SERVER_IP).packed),
            make_option(51, struct.pack("!I", LEASE_SECONDS)),
            make_option(1, ipaddress.IPv4Address(SUBNET_MASK).packed),
            make_option(3, ipaddress.IPv4Address(SERVER_IP).packed),
            make_option(28, ipaddress.IPv4Address("192.168.242.255").packed),
            b"\xff",
        )
    )
    dhcp_payload = bootp + options
    src_mac = mac_bytes("52:54:00:24:00:01")
    dst_mac = b"\xff" * 6
    ethernet = dst_mac + src_mac + struct.pack("!H", 0x0800)
    ip_total_length = 20 + 8 + len(dhcp_payload)
    ip_header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        ip_total_length,
        0,
        0,
        64,
        17,
        0,
        ipaddress.IPv4Address(SERVER_IP).packed,
        ipaddress.IPv4Address("255.255.255.255").packed,
    )
    ip_header = ip_header[:10] + struct.pack("!H", checksum(ip_header)) + ip_header[12:]
    # IPv4 UDP checksum 0 表示“不计算”，在本地实验网中由以太网/IPv4 校验保护。
    udp_header = struct.pack("!HHHH", 67, 68, 8 + len(dhcp_payload), 0)
    return ethernet + ip_header + udp_header + dhcp_payload


class DHCPServer:
    def __init__(self, port: int, static_leases: dict[str, str], state_path: Path):
        self.port = port
        self.static_leases = {key.lower(): value for key, value in static_leases.items()}
        self.state_path = state_path
        self.leases: dict[str, str] = {}
        self.next_dynamic = 100
        self.running = True
        self.client_count = 0

    def write_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "schema": 1,
            "pid": os.getpid(),
            "endpoint": f"tcp://{HUB_HOST}:{self.port}",
            "port": self.port,
            "server_ip": SERVER_IP,
            "client_count": self.client_count,
            "leases": self.leases,
            "updated_at": now_iso(),
        }
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    def allocate(self, mac: str, requested: str | None = None) -> str:
        if mac in self.static_leases:
            address = self.static_leases[mac]
        elif mac in self.leases:
            address = self.leases[mac]
        else:
            address = requested if requested and requested.startswith("192.168.242.") else f"192.168.242.{self.next_dynamic}"
            used = set(self.static_leases.values()) | set(self.leases.values())
            while address in used or address.endswith((".0", ".1", ".255")):
                self.next_dynamic += 1
                address = f"192.168.242.{self.next_dynamic}"
            self.next_dynamic += 1
        self.leases[mac] = address
        return address

    @staticmethod
    def send_frame(peer: socket.socket, frame: bytes) -> None:
        packet = memoryview(struct.pack("!I", len(frame)) + frame)
        while packet:
            try:
                sent = peer.send(packet)
            except BlockingIOError:
                # 本地少量实验节点不会形成持续背压；短暂等待可处理瞬时满缓冲区。
                import select

                select.select([], [peer], [], 0.2)
                continue
            if sent == 0:
                raise ConnectionError("实验网连接已关闭")
            packet = packet[sent:]

    def serve(self) -> int:
        import select

        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((HUB_HOST, self.port))
        listener.listen(8)
        listener.setblocking(False)
        clients: dict[socket.socket, bytearray] = {}
        self.write_state()
        print(f"L2 hub + DHCP listening on tcp://{HUB_HOST}:{self.port}", flush=True)
        try:
            while self.running:
                readable, _, _ = select.select([listener, *clients], [], [], 1.0)
                for current in readable:
                    if current is listener:
                        peer, _address = listener.accept()
                        peer.setblocking(False)
                        clients[peer] = bytearray()
                        self.client_count = len(clients)
                        self.write_state()
                        print(f"L2 client connected ({self.client_count})", flush=True)
                        continue

                    try:
                        chunk = current.recv(65536)
                    except (ConnectionError, OSError):
                        chunk = b""
                    if not chunk:
                        current.close()
                        clients.pop(current, None)
                        self.client_count = len(clients)
                        self.write_state()
                        print(f"L2 client disconnected ({self.client_count})", flush=True)
                        continue

                    buffer = clients[current]
                    buffer.extend(chunk)
                    while len(buffer) >= 4:
                        frame_length = struct.unpack("!I", buffer[:4])[0]
                        if frame_length < 14 or frame_length > 65536:
                            raise RuntimeError(f"QEMU socket 帧长度异常：{frame_length}")
                        if len(buffer) < 4 + frame_length:
                            break
                        frame = bytes(buffer[4:4 + frame_length])
                        del buffer[:4 + frame_length]

                        for other in list(clients):
                            if other is current:
                                continue
                            try:
                                self.send_frame(other, frame)
                            except (ConnectionError, OSError):
                                other.close()
                                clients.pop(other, None)

                        request = dhcp_request_from_frame(frame)
                        if request is None:
                            continue
                        mac, chaddr, xid, flags, message_type, options = request
                        if message_type not in {1, 3}:  # Discover / Request
                            continue
                        requested_raw = options.get(50, b"")
                        requested = str(ipaddress.IPv4Address(requested_raw)) if len(requested_raw) == 4 else None
                        assigned = self.allocate(mac, requested)
                        response_type = 2 if message_type == 1 else 5
                        response = build_dhcp_frame(frame, chaddr, xid, flags, response_type, assigned)
                        self.send_frame(current, response)
                        self.write_state()
                        print(f"DHCP {'OFFER' if response_type == 2 else 'ACK'} {mac} -> {assigned}", flush=True)
        finally:
            for peer in clients:
                peer.close()
            listener.close()
            self.client_count = 0
            self.write_state()
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CTFLab 回环 TCP 二层交换机和 DHCP 服务")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--lease", action="append", default=[], metavar="MAC=IP")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    static_leases: dict[str, str] = {}
    for value in args.lease:
        if "=" not in value:
            raise SystemExit(f"--lease 格式错误：{value}")
        mac, address = value.split("=", 1)
        mac_bytes(mac)
        ipaddress.IPv4Address(address)
        static_leases[mac.lower()] = address
    server = DHCPServer(args.port, static_leases, args.state)
    signal.signal(signal.SIGTERM, lambda _signum, _frame: setattr(server, "running", False))
    signal.signal(signal.SIGINT, lambda _signum, _frame: setattr(server, "running", False))
    return server.serve()


if __name__ == "__main__":
    raise SystemExit(main())
