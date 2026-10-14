"""内存帧及受控回环 socket 的双网合成验证，不启动 VM 或网络子进程。"""
from contextlib import redirect_stdout
import io
import ipaddress
from pathlib import Path
import socket
import struct
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ctflab_network import DHCPConfig, DHCPServer, MAGIC_COOKIE, checksum, dhcp_request_from_frame, mac_bytes, make_option, parse_args, parse_options
from ctflab_scenario import network_server_specs
from test_ctflab_scenario import candidate, CAPS, INSTANCE


def request(mac, kind=1, requested=None, server=None, ciaddr=None):
    chaddr = mac_bytes(mac)
    bootp = bytearray(236)
    bootp[:4] = b"\x01\x01\x06\x00"
    bootp[4:8] = struct.pack("!I", 12345)
    bootp[28:34] = chaddr
    if ciaddr:
        bootp[12:16] = ipaddress.IPv4Address(ciaddr).packed
    options = MAGIC_COOKIE + make_option(53, bytes([kind]))
    if requested:
        options += make_option(50, ipaddress.IPv4Address(requested).packed)
    if server:
        options += make_option(54, ipaddress.IPv4Address(server).packed)
    payload = bytes(bootp) + options + b"\xff"
    udp = struct.pack("!HHHH", 68, 67, len(payload) + 8, 0)
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp) + len(payload), 0, 0, 64, 17, 0, bytes(4), bytes([255]) * 4)
    ip = ip[:10] + struct.pack("!H", checksum(ip)) + ip[12:]
    return bytes([255]) * 6 + chaddr + b"\x08\x00" + ip + udp + payload


def response_fields(frame):
    options = parse_options(frame[282:])
    return str(ipaddress.IPv4Address(frame[58:62])), options


class DualNetworkTests(unittest.TestCase):
    def servers(self, identity=INSTANCE):
        specs = network_server_specs(candidate(), identity, generation=1, state_root="/synthetic-state", available_capabilities=CAPS)
        # 构造器不绑定监听端口，状态文件也不会写入。
        return {key: DHCPServer(12001 + index, **spec) for index, (key, spec) in enumerate(specs.items())}

    def test_discover_request_and_network_specific_options(self):
        with mock.patch("socket.socket", side_effect=AssertionError("不应创建网络")), mock.patch("builtins.open", side_effect=AssertionError("不应读写文件")):
            servers = self.servers()
            for network_id, server in servers.items():
                for mac, expected_ip in server.static_leases.items():
                    offered = server.dhcp_response(request(mac))
                    ip, options = response_fields(offered)
                    self.assertEqual(ip, expected_ip)
                    self.assertEqual(options[53], b"\x02")
                    self.assertEqual(options[54], ipaddress.IPv4Address(server.config.server_ip).packed)
                    self.assertEqual(offered[26:30], options[54])
                    self.assertEqual(options[1], server.config.subnet.netmask.packed)
                    self.assertEqual(options[28], server.config.subnet.broadcast_address.packed)
                    self.assertEqual(offered[6:12], mac_bytes(server.config.server_mac))
                    self.assertEqual(checksum(offered[14:34]), 0)
                    self.assertNotIn(3, options)
                    self.assertNotIn(6, options)
                    ack = server.dhcp_response(request(mac, 3, expected_ip, server.config.server_ip))
                    self.assertEqual(response_fields(ack)[1][53], b"\x05")
                other = servers["inner" if network_id == "outer" else "outer"]
                self.assertTrue(set(server.static_leases).isdisjoint(other.static_leases))
                for mac in other.static_leases:
                    before = dict(server.leases)
                    self.assertIsNone(server.dhcp_response(request(mac)))
                    self.assertEqual(server.leases, before)

    def test_foreign_server_wrong_address_and_spoof_do_not_change_lease(self):
        server = self.servers()["outer"]
        mac, ip = next(iter(server.static_leases.items()))
        invalid = [request(mac, 3, ip, "192.168.244.1"), request(mac, 3, "192.168.244.20"), request(mac, 3, "192.168.243.1"), request(mac, 3, "192.168.243.100"), request(mac, 3, ciaddr="192.168.244.20"), request("02:11:22:33:44:55")]
        spoofed = bytearray(request(mac))
        spoofed[6:12] = mac_bytes("02:11:22:33:44:55")
        invalid.append(bytes(spoofed))
        for frame in invalid:
            with self.subTest(frame=frame[-15:]):
                self.assertIsNone(server.dhcp_response(frame))
                self.assertEqual(server.leases, {})
        self.assertIsNotNone(server.dhcp_response(request(mac, 3, ciaddr=ip)))

    def test_broadcast_and_same_cidr_instances_keep_independent_state(self):
        a = self.servers()
        b = self.servers("22345678-1234-4234-8234-123456789abc")
        self.assertEqual(a["outer"].config.cidr, b["outer"].config.cidr)
        self.assertNotEqual(a["outer"].state_path, b["outer"].state_path)
        self.assertNotEqual(a["outer"].config.server_mac, b["outer"].config.server_mac)
        peers = {key: [object(), object()] for key in ("a-outer", "a-inner", "b-outer", "b-inner")}
        for label, server in [("a-outer", a["outer"]), ("a-inner", a["inner"]), ("b-outer", b["outer"]), ("b-inner", b["inner"])]:
            mac = next(iter(server.static_leases))
            frame = request(mac)
            self.assertEqual(server.switch.forwarding_targets(peers[label][0], frame, peers[label]), [peers[label][1]])
            self.assertIsNotNone(server.dhcp_response(frame))
            for other in (a["outer"], a["inner"], b["outer"], b["inner"]):
                if other is not server:
                    before = dict(other.leases)
                    self.assertIsNone(other.dhcp_response(frame))
                    self.assertEqual(other.leases, before)
        self.assertIsNot(a["outer"].switch.mac_table, b["outer"].switch.mac_table)
        self.assertIsNot(a["outer"].leases, a["inner"].leases)

    def test_specs_are_stable_and_generation_has_new_state_path(self):
        before = candidate()
        first = network_server_specs(before, INSTANCE, generation=1, state_root="/state", available_capabilities=CAPS)
        second = network_server_specs(before, INSTANCE, generation=2, state_root="/state", available_capabilities=CAPS)
        for net in first:
            self.assertEqual(first[net]["static_leases"], second[net]["static_leases"])
            self.assertEqual(first[net]["config"], second[net]["config"])
            self.assertNotEqual(first[net]["state_path"], second[net]["state_path"])
        self.assertEqual(before, candidate())


class DHCPValidationTests(unittest.TestCase):
    def test_config_rejects_invalid_ranges_and_leases(self):
        for kwargs in [dict(cidr="127.0.0.0/24"), dict(cidr="192.168.242.1/24"), dict(server_ip="192.168.243.1"), dict(pool_start="192.168.242.0"), dict(pool_end="192.168.242.255"), dict(pool_start="192.168.242.200", pool_end="192.168.242.100"), dict(server_ip="192.168.242.100"), dict(server_mac="ff:ff:ff:ff:ff:ff"), dict(registered_only=1)]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                DHCPConfig(**kwargs)
        config = DHCPConfig(registered_only=True)
        for leases in [{"02:00:00:00:00:01": "192.168.243.10"}, {"02:00:00:00:00:01": "192.168.242.100"}, {"02:00:00:00:00:01": "192.168.242.10", "02:00:00:00:00:02": "192.168.242.10"}, {"ff:ff:ff:ff:ff:ff": "192.168.242.10"}]:
            with self.assertRaises(ValueError):
                DHCPServer(12001, leases, Path("/unused"), config=config)

    def test_pool_exhaustion_and_legacy_static_exclusion(self):
        config = DHCPConfig(pool_end="192.168.242.101")
        server = DHCPServer(12001, {"02:00:00:00:00:01": "192.168.242.100"}, Path("/unused"), config=config)
        self.assertEqual(server.allocate("02:00:00:00:00:02", "192.168.243.200"), "192.168.242.101")
        self.assertIsNone(server.allocate("02:00:00:00:00:03"))
        self.assertEqual(server.allocate("02:00:00:00:00:01"), "192.168.242.100")
        self.assertEqual(server.allocate("02:00:00:00:00:02"), "192.168.242.101")
        self.assertNotIn("02:00:00:00:00:03", server.leases)
        custom = DHCPConfig("10.50.0.0/23", "10.50.0.1", "10.50.1.10", "10.50.1.11")
        server = DHCPServer(12001, {}, Path("/unused"), config=custom)
        frame = server.dhcp_response(request("02:00:00:00:00:02", requested="10.50.1.11"))
        ip, options = response_fields(frame)
        self.assertEqual(ip, "10.50.1.11")
        self.assertEqual(options[1], bytes([255, 255, 254, 0]))
        self.assertEqual(options[28], bytes([10, 50, 1, 255]))

    def test_malformed_requests_are_ignored(self):
        base = request("02:00:00:00:00:01")
        frames = [base[:i] for i in (0, 13, 14, 34, 42, 281, len(base) - 2)]
        for position, value in [(14, 0x41), (20, 0x20), (44, 5), (45, 1)]:
            modified = bytearray(base)
            modified[position] = value
            frames.append(bytes(modified))
        # 长度保留的空 message-type，以及重复 option 53。
        modified = bytearray(base)
        modified[283] = 0
        frames.append(bytes(modified))
        frames.append(request("02:00:00:00:00:01")[:-1] + b"\x35\x01\x01\xff")
        for frame in frames:
            with self.subTest(length=len(frame)):
                self.assertIsNone(dhcp_request_from_frame(frame))

    def test_cli_defaults_and_parameterized_parse(self):
        args = parse_args(["--port", "12001", "--state", "/unused"])
        self.assertEqual((args.cidr, args.server_ip, args.registered_only), ("192.168.242.0/24", "192.168.242.1", False))
        args = parse_args(["--port", "12001", "--state", "/unused", "--cidr", "192.168.243.0/24", "--server-ip", "192.168.243.1", "--pool-start", "192.168.243.100", "--pool-end", "192.168.243.150", "--registered-only", "--instance-uuid", INSTANCE, "--network-id", "outer", "--generation", "1"])
        self.assertTrue(args.registered_only)
        self.assertEqual(args.network_id, "outer")


class ListenerHandoffTests(unittest.TestCase):
    def test_serve_uses_configured_response_and_only_own_clients(self):
        specs = network_server_specs(candidate(), INSTANCE, generation=1, state_root="/unused", available_capabilities=CAPS)
        for name, spec in specs.items():
            with self.subTest(network=name):
                server = DHCPServer(12001, **spec)
                mac = next(iter(server.static_leases))
                frame = request(mac)
                listener = mock.Mock()
                peer, observer = mock.Mock(), mock.Mock()
                listener.accept.side_effect = [(peer, ("127.0.0.1", 1)), (observer, ("127.0.0.1", 2))]
                peer.recv.return_value = struct.pack("!I", len(frame)) + frame
                calls = 0
                def readable(*args):
                    nonlocal calls
                    calls += 1
                    if calls <= 2:
                        return [listener], [], []
                    server.running = False
                    return [peer], [], []
                with mock.patch("ctflab_network.socket.socket", return_value=listener), mock.patch("select.select", side_effect=readable), mock.patch.object(server, "write_state"), mock.patch.object(server, "send_frame") as send, redirect_stdout(io.StringIO()):
                    self.assertEqual(server.serve(), 0)
                self.assertEqual(send.call_count, 2)
                self.assertEqual(send.call_args_list[0].args, (observer, frame))
                destination, response = send.call_args_list[1].args
                self.assertIs(destination, peer)
                self.assertEqual(response_fields(response)[1][54], ipaddress.IPv4Address(server.config.server_ip).packed)
                self.assertEqual(server.frames_forwarded, 1)
                self.assertEqual(server.frames_generated, 1)
                peer.close.assert_called_once()
                observer.close.assert_called_once()
                listener.close.assert_called_once()

    def test_inherited_wrong_endpoint_is_rejected_without_state_write(self):
        import os
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
            server = DHCPServer(port - 1, {}, Path("/unused"), listener_fd=os.dup(reserved.fileno()))
            with mock.patch.object(server, "write_state") as write, self.assertRaises(ValueError):
                server.serve()
            write.assert_not_called()
            self.assertEqual(reserved.getsockname(), ("127.0.0.1", port))

    def test_reserved_loopback_port_collision_and_fd_handoff(self):
        # 仅本进程的临时回环监听器；不启动服务循环、子进程或来宾。
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
            reserved.bind(("127.0.0.1", 0))
            reserved.listen(1)
            port = reserved.getsockname()[1]
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as competing:
                with self.assertRaises(OSError):
                    competing.bind(("127.0.0.1", port))
            import os
            inherited = os.dup(reserved.fileno())
            server = DHCPServer(port, {}, Path("/unused"), listener_fd=inherited)
            server.running = False
            with mock.patch.object(server, "write_state"), redirect_stdout(io.StringIO()):
                self.assertEqual(server.serve(), 0)
            self.assertEqual(reserved.getsockname(), ("127.0.0.1", port))


if __name__ == "__main__":
    unittest.main()
