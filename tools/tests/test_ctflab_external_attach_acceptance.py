"""外部攻击机接入合成端到端验收：发现/服务访问/回连/断开后内部继续。

对应设计§12首项交付实验的合成等价物：真实交换机进程+真实接入口认证+中转帧泵，
来宾侧为注入通道替身。真实Kali/TAP与两平台组合仍属实机验收，不在本文件声明。
"""
import io
import ipaddress
import json
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ctflab_external_attach import GuestChannelStub
from ctflab_external_attach import (policy_summary, validate_attachment,
                                    derive_allowed_macs)
from ctflab_scenario_v2 import instance_plan
from ctflab_network import DHCPServer, DHCPConfig

EXTERNAL_MAC = '02:aa:bb:cc:dd:ee'
NODE_A_MAC, NODE_A_IP = '02:11:22:33:44:55', '192.168.242.20'
NODE_B_MAC, NODE_B_IP = '02:11:22:33:44:66', '192.168.242.21'
EXTERNAL_IP = '192.168.242.66'


def attachment():
    return validate_attachment({'schema': 1, 'kind': 'kali-l2-v1',
                                'instance_uuid': '0d1f7e57-7b1e-4c8e-9c8d-2f1a3b4c5d60',
                                'generation': 1, 'network_id': 'outer',
                                'cidr': '192.168.242.0/24', 'address': EXTERNAL_IP,
                                'mac': EXTERNAL_MAC, 'mtu': 1400, 'limits': {},
                                'expires': '2099-01-01T00:00:00Z'})


INSTANCE = '0d1f7e57-7b1e-4c8e-9c8d-2f1a3b4c5d60'


def plan():
    """生产装配来源：两台登记节点接入outer网段，MAC已派生。"""
    manifest = {
        'networks': {'outer': {'cidr': '192.168.242.0/24', 'uplink': 'none',
                               'external': {'schema': 1, 'address': EXTERNAL_IP,
                                            'mac': EXTERNAL_MAC}}},
        'nodes': {
            'alpha': {'asset': 'a', 'cpus': 1, 'memory_mb': 512, 'firmware': 'bios',
                      'disk_bus': 'ide', 'depends_on': [],
                      'interfaces': [{'id': 'eth0', 'network': 'outer',
                                      'address': NODE_A_IP, 'mac': NODE_A_MAC,
                                      'model': 'e1000'}]},
            'beta': {'asset': 'a', 'cpus': 1, 'memory_mb': 512, 'firmware': 'bios',
                     'disk_bus': 'ide', 'depends_on': [],
                     'interfaces': [{'id': 'eth0', 'network': 'outer',
                                     'address': NODE_B_IP, 'mac': NODE_B_MAC,
                                     'model': 'e1000'}]}},
        'assets': {'a': {'sha256': 'a' * 64, 'architecture': 'x86_64', 'source': '自建',
                         'license': '内部', 'verification': 'unverified'}},
        'policy': {'internet': False, 'host_forwards': [], 'failure': 'preserve'},
        'scenario_id': 'attach-e2e', 'schema': 2}
    return instance_plan(manifest, INSTANCE)


def registration():
    return {'node_uuid': INSTANCE,
            'machine_uuid': '0d1f7e57-7b1e-4c8e-9c8d-2f1a3b4c5d61',
            'assistant_sha256': 'a' * 64}


def mac_raw(text):
    return bytes.fromhex(text.replace(':', ''))


def addr(text):
    return ipaddress.IPv4Address(text).packed


def arp_broadcast(sender_ip):
    body = (b'\x00\x01\x08\x00\x06\x04\x00\x01' + mac_raw(EXTERNAL_MAC) + addr(sender_ip)
            + b'\x00' * 6 + addr(NODE_A_IP))
    return b'\xff' * 6 + mac_raw(EXTERNAL_MAC) + struct.pack('!H', 0x0806) + body


def icmp_echo(destination_mac, destination_ip, source_mac=EXTERNAL_MAC, source_ip=EXTERNAL_IP):
    ip_header = struct.pack('!BBHHHBBH', 0x45, 0, 28, 0, 0, 64, 1, 0) + addr(source_ip) + addr(destination_ip)
    return mac_raw(destination_mac) + mac_raw(source_mac) + struct.pack('!H', 0x0800) + ip_header + b'\x08\x00\x00\x00\x00\x00\x00\x00'


def ipv4_frame(destination_mac, source_mac, source_ip, destination_ip):
    ip_header = struct.pack('!BBHHHBBH', 0x45, 0, 28, 0, 0, 64, 6, 0) + addr(source_ip) + addr(destination_ip)
    return mac_raw(destination_mac) + mac_raw(source_mac) + struct.pack('!H', 0x0800) + ip_header + b'\x00' * 8


class ExternalAttachAcceptance(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.secret = 'ab' * 32
        self.external_listener = socket.socket()
        self.external_listener.bind(('127.0.0.1', 0))
        self.external_listener.listen(1)
        self.external_port = self.external_listener.getsockname()[1]
        self.port = 25730
        self.server = DHCPServer(
            self.port,
            {NODE_A_MAC: NODE_A_IP, NODE_B_MAC: NODE_B_IP},
            self.root / 'net.json',
            config=DHCPConfig(registered_only=True), instance_uuid=None,
            external={'mac': EXTERNAL_MAC, 'address': EXTERNAL_IP, 'secret': self.secret,
                      'allowed_macs': [NODE_A_MAC, NODE_B_MAC]})
        def patched():
            self.server.external['port'] = self.external_port
            self.external_listener.setblocking(False)
            return self.external_listener
        self.server._prepare_external_listener = patched
        self.thread = threading.Thread(target=self.server.serve, daemon=True)
        self.thread.start()
        time.sleep(0.3)
        self.addCleanup(self._teardown)

    def _teardown(self):
        self.server.running = False
        self.thread.join(timeout=3)
        self.external_listener.close()

    def _connect_node(self):
        peer = socket.create_connection(('127.0.0.1', self.port))
        peer.settimeout(3)
        self.addCleanup(peer.close)
        time.sleep(0.05)
        return peer

    def _send(self, peer, frame):
        peer.sendall(struct.pack('!I', len(frame)) + frame)

    SESSION = '11111111-2222-3333-4444-555555555555'

    def _recv_frames(self, peer, count, timeout=3.0):
        """TCP可能合并帧；按对端持久缓冲沿长度前缀边界取count个完整帧。"""
        if not hasattr(self, '_buffers'):
            self._buffers = {}
        buffer = self._buffers.setdefault(id(peer), bytearray())
        deadline = time.time() + timeout
        frames = []
        while len(frames) < count and time.time() < deadline:
            while len(buffer) >= 4:
                length = struct.unpack('!I', buffer[:4])[0]
                if len(buffer) < 4 + length:
                    break
                frames.append(bytes(buffer[4:4 + length]))
                del buffer[:4 + length]
                if len(frames) >= count:
                    break
            try:
                chunk = peer.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            buffer += chunk
        return frames

    def _start_relay(self, guest_frames):
        """后台运行中转；测试线程按序断言后用stop受控收尾。

        策略从实例计划派生（生产装配同源），不再手工传白名单。
        """
        import threading as _threading
        from ctflab_external_attach import run_relay
        value = attachment()
        derived = derive_allowed_macs(plan(), 'outer')
        self.assertEqual(derived, sorted([NODE_A_MAC, NODE_B_MAC]))
        policy = policy_summary(value, derived)
        registration_value = registration()
        channel = GuestChannelStub(guest_frames, registration_value, self.SESSION,
                                   machine_uuid=registration_value['machine_uuid'])
        stop = _threading.Event()

        def wait_readable(readables, timeout):
            import select as _select
            ready = []
            for item in readables:
                if item is channel.incoming:
                    channel._fill()
                    if channel._read_pos < len(channel.incoming.getvalue()):
                        ready.append(item)
                else:
                    active, _, _ = _select.select([item], [], [], 0)
                    if active:
                        ready.append(item)
            if not ready:
                time.sleep(min(timeout, 0.05))
            return ready

        holder = {}

        def run():
            holder['report'] = run_relay(
                {'host': '127.0.0.1'}, value, policy, self.secret,
                self.SESSION, ('127.0.0.1', self.external_port),
                backend='switch', channel=channel, wait=wait_readable, max_idle=60.0,
                stop=stop.is_set, registration=registration_value,
                on_ready=lambda identity: holder.setdefault('identity', identity))

        thread = _threading.Thread(target=run, daemon=True)
        thread.start()
        return thread, stop, channel, holder

    def test_first_deliverable_experiment_synthetic(self):
        """设计§12首项合成等价：发现→服务访问→回连→断开后外部不可达而内部继续。"""
        node_a = self._connect_node()
        node_b = self._connect_node()
        # 来宾发出：ARP广播发现 + 访问节点A（ICMP）；随后节点B回连（发往预约IP）。
        guest_frames = [arp_broadcast(EXTERNAL_IP), icmp_echo(NODE_A_MAC, NODE_A_IP)]
        thread, stop, stub, holder = self._start_relay(guest_frames)
        time.sleep(0.5)  # 认证+来宾帧处理
        # 1) 两台登记靶机都收到发现帧（TCP可能合包，按帧边界读取）
        for node in (node_a, node_b):
            received = self._recv_frames(node, 1)[0]
            self.assertEqual(received[:6], b'\xff' * 6)
            # ARP发送方硬件地址=外部预约MAC（帧内偏移：以太14+ARP头8）
            self.assertEqual(received[14 + 8:14 + 14], mac_raw(EXTERNAL_MAC))
        # 2) 节点A收到来宾的服务访问帧（ICMP；广播已在步骤1消费）。
        # 节点MAC尚未学习时未知单播按标准L2语义洪泛，节点B也可能收到副本。
        node_a_frames = self._recv_frames(node_a, 1)
        self.assertEqual(len(node_a_frames), 1, '节点A应收到ICMP服务访问帧')
        icmp_frame = node_a_frames[0]
        self.assertEqual(icmp_frame[:6], mac_raw(NODE_A_MAC))
        self.assertEqual(icmp_frame[14 + 9], 1)  # ICMP协议号
        self.assertEqual(icmp_frame[6:12], mac_raw(EXTERNAL_MAC))
        # 3) 中转把回连帧（宿主→来宾）送到来宾通道
        self._send(node_b, ipv4_frame(EXTERNAL_MAC, NODE_B_MAC, NODE_B_IP, EXTERNAL_IP))
        def last_frame_record(raw):
            """收集流含宿主HELLO与帧记录；沿记录边界取最后一条帧载荷。"""
            position, found = 0, b''
            while position + 7 <= len(raw):
                kind, _sequence, length = struct.unpack('!BIH', raw[position:position + 7])
                if position + 7 + length > len(raw):
                    break
                if kind == 0x01:
                    found = raw[position + 7:position + 7 + length]
                position += 7 + length
            return found

        deadline = time.time() + 5
        back = b''
        while time.time() < deadline:
            back = last_frame_record(stub.collected.getvalue())
            if back:
                break
            time.sleep(0.05)
        self.assertTrue(back, '靶机回连帧未到达来宾通道')
        self.assertEqual(back[:6], mac_raw(EXTERNAL_MAC))
        # 4) 受控断开来宾侧通道：外部不可达，而内部节点互通继续
        stop.set()
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive(), '中转应在stop后受控退出')
        self._send(node_a, ipv4_frame(EXTERNAL_MAC, NODE_A_MAC, NODE_A_IP, EXTERNAL_IP))
        time.sleep(0.3)
        # 外部会话已关：该帧按洪泛到达其他节点，先排空再验证内部转发。
        self._recv_frames(node_a, 10, timeout=0.3)
        self._recv_frames(node_b, 10, timeout=0.3)
        state = json.loads((self.root / 'net.json').read_text())
        self.assertIsNone(state['external']['authenticated_session'])
        self.assertGreaterEqual(holder['report']['frames_to_lab'], 2)
        self.assertGreaterEqual(holder['report']['frames_to_kali'], 1)
        # 内部实验继续运行：A→B单播仍被交换（与外部口无关）。
        # 外部会话已关闭，external MAC不再学习，回连帧按洪泛到达node_a——
        # 但外部口的frames_out不再增加，证明外部不可达。
        self._send(node_a, ipv4_frame(NODE_B_MAC, NODE_A_MAC, NODE_A_IP, NODE_B_IP))
        deadline = time.time() + 3
        got = []
        while time.time() < deadline:
            got = self._recv_frames(node_b, 1, timeout=0.5)
            if got:
                break
        self.assertTrue(got, '内部A→B转发应继续工作')
        self.assertEqual(got[0][:6], mac_raw(NODE_B_MAC))
        # 外部口已撤：新的回连不再送达（无认证会话，中转已断开）
        state = json.loads((self.root / 'net.json').read_text())
        before_out = state['external']['frames_out']
        self._send(node_b, ipv4_frame(EXTERNAL_MAC, NODE_B_MAC, NODE_B_IP, EXTERNAL_IP))
        time.sleep(0.3)
        state = json.loads((self.root / 'net.json').read_text())
        self.assertEqual(state['external']['frames_out'], before_out,
                         '断开后外部口仍向外发帧')

    def test_spoofed_discovery_never_reaches_registered_nodes(self):
        node_a = self._connect_node()
        node_b = self._connect_node()
        # 伪造源MAC的"发现"帧必须被门禁拒绝：两台靶机都收不到。
        spoofed = (b'\xff' * 6 + mac_raw(NODE_A_MAC) + struct.pack('!H', 0x0806)
                   + b'\x00\x01\x08\x00\x06\x04\x00\x01' + mac_raw(NODE_A_MAC)
                   + addr(EXTERNAL_IP) + b'\x00' * 6 + addr(NODE_A_IP))
        thread, stop, _stub, holder = self._start_relay([spoofed])
        time.sleep(0.5)
        stop.set()
        thread.join(timeout=10)
        for node in (node_a, node_b):
            self.assertEqual(self._recv_frames(node, 1, timeout=0.8), [],
                             '伪造发现帧不得送达任何登记节点')
        self.assertEqual(holder['report']['frames_to_lab'], 0)
        self.assertGreaterEqual(holder['report']['dropped'], 1, '伪造帧应在中转门禁被丢弃')
        state = json.loads((self.root / 'net.json').read_text())
        self.assertIsNone(state['external']['authenticated_session'])


if __name__ == '__main__':
    unittest.main()
