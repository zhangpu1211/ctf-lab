"""二层帧协议/门禁/配额单元测试；全部合成帧与可注入时钟。"""
import io
import ipaddress
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError
from ctflab_external_l2 import (FrameGate, RecordStream, SessionQuota, TokenBucket,
                                encode_record, decode_record, control_payload,
                                RECORD_FRAME, RECORD_CONTROL, RECORD_HEARTBEAT,
                                RECORD_CLOSE, policy_digest)

RESERVED_MAC = '02:aa:bb:cc:dd:ee'
NODE_MAC = '02:11:22:33:44:55'
RESERVED_IP = '192.168.50.9'
NODE_IP = '192.168.50.20'


def policy(**overrides):
    value = {'schema': 1, 'cidr': '192.168.50.0/24', 'address': RESERVED_IP,
             'mac': RESERVED_MAC, 'mtu': 1400,
             'limits': {'max_frames_per_second': 1000, 'burst_frames': 250,
                        'max_bytes': 2**30, 'max_seconds': 7200, 'queue_frames': 256},
             'allowed_macs': [NODE_MAC, '52:54:00:24:00:01']}
    value.update(overrides)
    return value


def gate():
    return FrameGate(policy())


def ethernet(destination, source, ethertype, payload=b''):
    return bytes.fromhex(destination.replace(':', '')) + bytes.fromhex(source.replace(':', '')) \
        + struct.pack('!H', ethertype) + payload


def arp_frame(sender_mac, sender_ip, target_mac, target_ip, operation=1):
    body = (b'\x00\x01\x08\x00\x06\x04' + struct.pack('!H', operation)
            + bytes.fromhex(sender_mac.replace(':', '')) + socket_addr(sender_ip)
            + bytes.fromhex(target_mac.replace(':', '')) + socket_addr(target_ip))
    return ethernet('ff:ff:ff:ff:ff:ff', sender_mac, 0x0806, body)


def ipv4_frame(source_ip, destination_ip, protocol=6, fragment=0, source_mac=RESERVED_MAC):
    header = struct.pack('!BBHHHBBH', 0x45, 0, 28, 0, fragment, 64, protocol, 0) \
        + socket_addr(source_ip) + socket_addr(destination_ip)
    return ethernet(NODE_MAC, source_mac, 0x0800, header + b'\x00' * 8)


def socket_addr(text):
    return ipaddress.IPv4Address(text).packed


class RecordTests(unittest.TestCase):
    def test_encode_decode_roundtrip_and_limits(self):
        raw = encode_record(RECORD_FRAME, 7, b'\x01' * 1514)
        kind, sequence, length = decode_record(raw[:7])
        self.assertEqual((kind, sequence, length), (RECORD_FRAME, 7, 1514))
        with self.assertRaises(ContractError):
            encode_record(RECORD_FRAME, 0, b'\x00' * 1515)
        with self.assertRaises(ContractError):
            encode_record(RECORD_HEARTBEAT, 0, b'\x00')
        with self.assertRaises(ContractError):
            decode_record(b'\x01\x00\x00\x00\x07\xff\xff')

    def test_record_stream_sequence_and_bounded_read(self):
        source = io.BytesIO(encode_record(RECORD_FRAME, 0, b'abcd')
                            + encode_record(RECORD_CLOSE, 1, b'bye'))
        sink = io.BytesIO()
        stream = RecordStream(source, sink)
        first = stream.receive()
        self.assertEqual(first, (RECORD_FRAME, 0, b'abcd'))
        second = stream.receive()
        self.assertEqual(second[0], RECORD_CLOSE)
        exhausted = stream.receive()
        self.assertIsNone(exhausted)
        stream.send(RECORD_CONTROL, control_payload({'hello': 'world'}))
        written = sink.getvalue()
        self.assertEqual(decode_record(written[:7]), (RECORD_CONTROL, 0, len(written) - 7))

    def test_control_payload_rejects_oversize(self):
        with self.assertRaises(ContractError):
            control_payload({'blob': 'x' * 5000})


class GateTests(unittest.TestCase):
    def test_valid_arp_and_ipv4_ingress(self):
        value = gate()
        self.assertTrue(value.ingress(arp_frame(RESERVED_MAC, RESERVED_IP, '00:00:00:00:00:00', NODE_IP)))
        self.assertTrue(value.ingress(ipv4_frame(RESERVED_IP, NODE_IP)))
        # ARP探测sender IP为0.0.0.0允许
        self.assertTrue(value.ingress(arp_frame(RESERVED_MAC, '0.0.0.0', '00:00:00:00:00:00', NODE_IP)))

    def test_ingress_rejects_spoofed_source_mac_and_ip(self):
        value = gate()
        self.assertFalse(value.ingress(arp_frame(NODE_MAC, RESERVED_IP, '00:00:00:00:00:00', NODE_IP)))
        self.assertEqual(value.rejected['source-mac'], 1)
        self.assertFalse(value.ingress(ipv4_frame(NODE_IP, NODE_IP)))
        self.assertEqual(value.rejected['source-ip'], 1)

    def test_ingress_rejects_vlan_ipv6_other_ethertypes(self):
        value = gate()
        vlan = ethernet(NODE_MAC, RESERVED_MAC, 0x8100, b'\x00' * 8)
        self.assertFalse(value.ingress(vlan))
        self.assertEqual(value.rejected['ethertype'], 1)
        ipv6 = ethernet(NODE_MAC, RESERVED_MAC, 0x86DD, b'\x00' * 8)
        self.assertFalse(value.ingress(ipv6))
        lldp = ethernet(NODE_MAC, RESERVED_MAC, 0x88CC, b'\x00' * 8)
        self.assertFalse(value.ingress(lldp))
        self.assertEqual(value.rejected['ethertype'], 3)

    def test_ingress_rejects_fragments_and_unknown_protocols(self):
        value = gate()
        self.assertFalse(value.ingress(ipv4_frame(RESERVED_IP, NODE_IP, fragment=0x2000)))
        self.assertEqual(value.rejected['fragment'], 1)
        self.assertFalse(value.ingress(ipv4_frame(RESERVED_IP, NODE_IP, fragment=0x0003)))
        self.assertFalse(value.ingress(ipv4_frame(RESERVED_IP, NODE_IP, protocol=47)))
        self.assertEqual(value.rejected['protocol'], 1)

    def test_ingress_rejects_unknown_destination_and_off_subnet(self):
        value = gate()
        stranger = ethernet('02:de:ad:be:ef:00', RESERVED_MAC, 0x0800,
                            struct.pack('!BBHHHBBH', 0x45, 0, 28, 0, 0, 64, 6, 0)
                            + socket_addr(RESERVED_IP) + socket_addr(NODE_IP) + b'\x00' * 8)
        self.assertFalse(value.ingress(stranger))
        self.assertEqual(value.rejected['destination'], 1)
        outside = ipv4_frame(RESERVED_IP, '192.168.60.20')
        self.assertFalse(value.ingress(outside))
        self.assertEqual(value.rejected['destination'], 2)

    def test_ingress_rejects_arp_server_and_foreign_binding_claims(self):
        value = gate()
        # 冒充DHCP服务器IP被ARP绑定检查拒绝（sender mac不符即拒）
        claim = arp_frame(RESERVED_MAC, '192.168.50.1', '00:00:00:00:00:00', NODE_IP, operation=2)
        self.assertFalse(value.ingress(claim))
        self.assertEqual(value.rejected['arp-binding'], 1)
        # 目标不在网段拒绝
        outside = arp_frame(RESERVED_MAC, RESERVED_IP, '00:00:00:00:00:00', '192.168.60.1')
        self.assertFalse(value.ingress(outside))

    def test_egress_allows_registered_nodes_and_rejects_others(self):
        value = gate()
        dhcp_offer = ethernet(RESERVED_MAC, '52:54:00:24:00:01', 0x0800,
                              struct.pack('!BBHHHBBH', 0x45, 0, 28, 0, 0, 64, 17, 0)
                              + socket_addr(NODE_IP) + socket_addr(RESERVED_IP) + b'\x00' * 8)
        self.assertTrue(value.egress(dhcp_offer))
        broadcast = ethernet('ff:ff:ff:ff:ff:ff', NODE_MAC, 0x0806,
                             b'\x00\x01\x08\x00\x06\x04\x00\x01' + bytes.fromhex(NODE_MAC.replace(':', ''))
                             + socket_addr(NODE_IP) + b'\x00' * 10)
        self.assertTrue(value.egress(broadcast))
        rogue = ethernet(RESERVED_MAC, '02:99:88:77:66:55', 0x0800,
                         struct.pack('!BBHHHBBH', 0x45, 0, 28, 0, 0, 64, 6, 0)
                         + socket_addr(NODE_IP) + socket_addr(RESERVED_IP) + b'\x00' * 8)
        self.assertFalse(value.egress(rogue))
        self.assertEqual(value.rejected['source-mac'], 1)
        wrong_destination = ethernet('02:99:88:77:66:55', NODE_MAC, 0x0806, b'\x00' * 28)
        self.assertFalse(value.egress(wrong_destination))
        self.assertEqual(value.rejected['destination'], 1)

    def test_short_frames_rejected_both_directions(self):
        value = gate()
        self.assertFalse(value.ingress(b'\x00' * 13))
        self.assertFalse(value.egress(b'\x00' * 8))
        self.assertEqual(value.rejected['short'], 2)


class QuotaTests(unittest.TestCase):
    def test_token_bucket_refill_with_injected_clock(self):
        moment = [0.0]
        bucket = TokenBucket(100, 10, clock=lambda: moment[0])
        self.assertTrue(bucket.allow(10))
        self.assertFalse(bucket.allow())
        moment[0] = 0.05  # 5个令牌
        self.assertTrue(bucket.allow(5))
        self.assertFalse(bucket.allow())

    def test_session_quota_broadcast_limit_and_bytes(self):
        moment = [0.0]
        limits = {'max_frames_per_second': 100, 'burst_frames': 50, 'max_bytes': 2**20,
                  'max_seconds': 7200, 'queue_frames': 256}
        quota = SessionQuota(limits, clock=lambda: moment[0])
        # 广播桶独立：连续50个广播帧内允许，之后拒绝
        accepted = sum(quota.consume(10, broadcast=True) for _ in range(60))
        self.assertLessEqual(accepted, 50)
        self.assertGreater(quota.frames_dropped, 0)

    def test_session_quota_byte_and_duration_exhaustion(self):
        moment = [0.0]
        limits = {'max_frames_per_second': 1000, 'burst_frames': 500, 'max_bytes': 2**20,
                  'max_seconds': 60, 'queue_frames': 512}
        quota = SessionQuota(limits, clock=lambda: moment[0])
        accepted = sum(quota.consume(1024) for _ in range(1200))
        self.assertLess(accepted, 1200)  # 超过1MiB后拒绝
        self.assertLess(quota.bytes, 1200 * 1024)
        moment[0] = 61.0
        self.assertFalse(quota.consume(10))  # 超时长
        self.assertTrue(quota.expired())

    def test_policy_digest_stable(self):
        self.assertEqual(policy_digest(policy()), policy_digest(policy()))



class ReceiveSequenceRegressionTests(unittest.TestCase):
    def test_duplicate_regressed_skipped_and_nonzero_initial_rejected(self):
        for sequences in ((0, 0), (0, 2), (7,), (0, 1, 0)):
            stream = RecordStream(io.BytesIO(b''.join(
                encode_record(RECORD_HEARTBEAT, seq) for seq in sequences)), io.BytesIO())
            with self.assertRaises(ContractError):
                for _ in sequences:
                    stream.receive()

    def test_sequence_continues_across_identity_heartbeat_frame_and_close(self):
        records = [(RECORD_CONTROL, b'{}'), (RECORD_HEARTBEAT, b''),
                   (RECORD_FRAME, bytes(14)), (RECORD_CLOSE, b'bye')]
        stream = RecordStream(io.BytesIO(b''.join(encode_record(kind, i, data)
                              for i, (kind, data) in enumerate(records))), io.BytesIO())
        self.assertEqual([stream.receive()[1] for _ in records], [0, 1, 2, 3])


if __name__ == '__main__':
    unittest.main()
