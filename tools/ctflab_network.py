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
from typing import Any, BinaryIO, Iterable


HUB_HOST = "127.0.0.1"
SERVER_IP = "192.168.242.1"
SUBNET_MASK = "255.255.255.0"
LEASE_SECONDS = 86400
MAGIC_COOKIE = b"\x63\x82\x53\x63"
PCAP_SNAPLEN = 65535


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


class LearningSwitch:
    """为本地实验网提供最小的二层 MAC 学习与转发决策。"""

    def __init__(self) -> None:
        self.mac_table: dict[bytes, Any] = {}

    def forwarding_targets(self, ingress: Any, frame: bytes, peers: Iterable[Any]) -> list[Any]:
        if len(frame) < 14:
            return []
        destination = frame[:6]
        source = frame[6:12]
        peer_list = list(peers)
        if source != b"\x00" * 6 and not source[0] & 1:
            self.mac_table[source] = ingress

        if destination[0] & 1:  # 广播或组播
            return [peer for peer in peer_list if peer is not ingress]
        target = self.mac_table.get(destination)
        if target is None:
            return [peer for peer in peer_list if peer is not ingress]
        if target is ingress:
            return []
        if target not in peer_list:
            self.mac_table.pop(destination, None)
            return [peer for peer in peer_list if peer is not ingress]
        return [target]

    def forget(self, peer: Any) -> None:
        for address, owner in list(self.mac_table.items()):
            if owner is peer:
                self.mac_table.pop(address, None)

    def learned_macs(self) -> list[str]:
        return sorted(mac_text(address) for address in self.mac_table)


class FrameRateLimiter:
    """按连接限制每秒接收帧数，避免单个来宾形成广播风暴。"""

    def __init__(self, max_frames_per_second: int):
        if max_frames_per_second <= 0:
            raise ValueError("每秒帧数上限必须为正整数")
        self.max_frames_per_second = max_frames_per_second
        self.windows: dict[Any, tuple[float, int]] = {}

    def allow(self, peer: Any, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        window_start, count = self.windows.get(peer, (current, 0))
        if current - window_start >= 1.0:
            window_start, count = current, 0
        if count >= self.max_frames_per_second:
            self.windows[peer] = (window_start, count)
            return False
        self.windows[peer] = (window_start, count + 1)
        return True

    def forget(self, peer: Any) -> None:
        self.windows.pop(peer, None)


class PcapWriter:
    """写入标准 Ethernet PCAP，供 Wireshark/tcpdump 离线分析。"""

    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle: BinaryIO = self.path.open("wb")
        self.handle.write(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, PCAP_SNAPLEN, 1))
        self.handle.flush()

    def write(self, frame: bytes, timestamp: float | None = None) -> None:
        moment = time.time() if timestamp is None else timestamp
        seconds = int(moment)
        microseconds = int((moment - seconds) * 1_000_000)
        captured = frame[:PCAP_SNAPLEN]
        self.handle.write(struct.pack("<IIII", seconds, microseconds, len(captured), len(frame)))
        self.handle.write(captured)
        self.handle.flush()

    def close(self) -> None:
        self.handle.close()


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
    def __init__(
        self,
        port: int,
        static_leases: dict[str, str],
        state_path: Path,
        *,
        pcap_path: Path | None = None,
        max_frames_per_second: int = 10000,
    ):
        self.port = port
        self.static_leases = {key.lower(): value for key, value in static_leases.items()}
        self.state_path = state_path
        self.leases: dict[str, str] = {}
        self.next_dynamic = 100
        self.running = True
        self.client_count = 0
        self.switch = LearningSwitch()
        self.rate_limiter = FrameRateLimiter(max_frames_per_second)
        self.pcap = PcapWriter(pcap_path) if pcap_path else None
        self.frames_received = 0
        self.frames_forwarded = 0
        self.frames_generated = 0
        self.frames_dropped_rate_limit = 0
        self.last_state_write = 0.0

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
            "learned_macs": self.switch.learned_macs(),
            "rate_limit_frames_per_second": self.rate_limiter.max_frames_per_second,
            "pcap_path": str(self.pcap.path) if self.pcap else None,
            "counters": {
                "received": self.frames_received,
                "forwarded": self.frames_forwarded,
                "generated": self.frames_generated,
                "dropped_rate_limit": self.frames_dropped_rate_limit,
            },
            "updated_at": now_iso(),
        }
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)
        self.last_state_write = time.monotonic()

    def maybe_write_state(self) -> None:
        if time.monotonic() - self.last_state_write >= 1.0:
            self.write_state()

    def forget_client(self, peer: socket.socket) -> None:
        self.switch.forget(peer)
        self.rate_limiter.forget(peer)

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
                        self.forget_client(current)
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

                        self.frames_received += 1
                        if not self.rate_limiter.allow(current):
                            self.frames_dropped_rate_limit += 1
                            self.maybe_write_state()
                            continue
                        if self.pcap:
                            self.pcap.write(frame)

                        for other in self.switch.forwarding_targets(current, frame, clients):
                            try:
                                self.send_frame(other, frame)
                                self.frames_forwarded += 1
                            except (ConnectionError, OSError):
                                other.close()
                                clients.pop(other, None)
                                self.forget_client(other)

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
                        if self.pcap:
                            self.pcap.write(response)
                        self.send_frame(current, response)
                        self.frames_generated += 1
                        self.write_state()
                        print(f"DHCP {'OFFER' if response_type == 2 else 'ACK'} {mac} -> {assigned}", flush=True)
                    self.maybe_write_state()
        finally:
            for peer in clients:
                peer.close()
            listener.close()
            self.client_count = 0
            if self.pcap:
                self.pcap.close()
            self.write_state()
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CTFLab 回环 TCP 二层交换机和 DHCP 服务")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--lease", action="append", default=[], metavar="MAC=IP")
    parser.add_argument("--pcap", type=Path, help="可选的 Ethernet PCAP 输出路径")
    parser.add_argument("--max-frames-per-second", type=int, default=10000, help="每个来宾的帧速率上限")
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
    if args.max_frames_per_second <= 0:
        raise SystemExit("--max-frames-per-second 必须为正整数")
    server = DHCPServer(
        args.port,
        static_leases,
        args.state,
        pcap_path=args.pcap,
        max_frames_per_second=args.max_frames_per_second,
    )
    signal.signal(signal.SIGTERM, lambda _signum, _frame: setattr(server, "running", False))
    signal.signal(signal.SIGINT, lambda _signum, _frame: setattr(server, "running", False))
    return server.serve()


if __name__ == "__main__":
    raise SystemExit(main())
