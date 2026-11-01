"""外部攻击机接入契约/槽位规划/挑战凭据/交换机接入口；全部合成，不操作真实VM或网络边界。"""
import ipaddress
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
import uuid

from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError, canonical
from ctflab_external_attach import (AttachStore, validate_attachment, validate_registration,
                                    validate_ssh_reference, validate_network_external,
                                    validate_hub_networks, policy_summary, challenge_token,
                                    session_secret, attachment_digest, check_generation,
                                    authenticate_switch, FrameChannel, run_relay,
                                    approve_assistant, load_assistant_approvals,
                                    require_approved_assistant)
from ctflab_network import DHCPServer, DHCPConfig


def attachment(**overrides):
    value = {'schema': 1, 'kind': 'kali-l2-v1', 'instance_uuid': str(uuid.uuid4()),
             'generation': 3, 'network_id': 'lab0', 'cidr': '192.168.50.0/24',
             'address': '192.168.50.9', 'mac': '02:aa:bb:cc:dd:ee', 'mtu': 1400,
             'limits': {}, 'expires': '2099-01-01T00:00:00Z'}
    value.update(overrides)
    return value


def registration():
    return {'schema': 1, 'kind': 'kali-l2-v1', 'name': '教室Kali',
            'node_uuid': str(uuid.uuid4()), 'machine_uuid': str(uuid.uuid4()),
            'vendor': 'VMware, Inc.', 'product': 'VMware Virtual Platform',
            'ssh': {'host': '127.0.0.1', 'port': 22, 'user': 'ctflab_attach',
                    'identity': '/Users/student/.ssh/ctflab_kali'},
            'assistant_sha256': 'a' * 64}


def hub_plan(networks_with_external=(), nodes=('n1', 'n2', 'n3')):
    interfaces = {}
    manifest_nodes = {}
    for node in nodes:
        network = 'lab0'
        manifest_nodes[node] = {'interfaces': [{'id': f'{node}-eth0', 'network': network,
                                                'mac': '02:00:00:00:00:0' + node[-1]}]}
    manifest = {'nodes': manifest_nodes,
                'networks': {'lab0': {'external': {'address': '192.168.50.9',
                                                   'mac': '02:aa:bb:cc:dd:ee'}}
                             if 'lab0' in networks_with_external else {}}}
    return {'manifest': manifest, 'start_order': list(nodes)}


class ContractTests(unittest.TestCase):
    def test_valid_attachment_roundtrip_and_policy_digest_stable(self):
        value = validate_attachment(attachment())
        first = policy_summary(value, ['02:11:22:33:44:55', '52:54:00:24:00:01'])
        second = policy_summary(dict(value), ['52:54:00:24:00:01', '02:11:22:33:44:55'])
        self.assertEqual(first['policy_sha256'], second['policy_sha256'])
        self.assertEqual(first['policy']['ether_types'], ['0x0800', '0x0806'])
        self.assertEqual(first['policy']['allowed_macs'], ['02:11:22:33:44:55', '52:54:00:24:00:01'])

    def test_attachment_rejects_bad_cidr_address_mac_generation_mtu(self):
        for changed in ({'cidr': '8.8.8.0/24'}, {'address': '192.168.50.255'},
                        {'address': '192.168.50.0'}, {'mac': '03:aa:bb:cc:dd:ee'},
                        {'mac': 'ff:ff:ff:ff:ff:ff'}, {'generation': 0},
                        {'mtu': 1500}, {'network_id': '../evil'},
                        {'expires': '2099-01-01T00:00:00'}):
            with self.assertRaises(ContractError, msg=changed):
                validate_attachment(attachment(**changed))

    def test_limits_bounds_and_burst_queue_relation(self):
        value = validate_attachment(attachment(limits={'max_frames_per_second': 2000,
                                                       'burst_frames': 300,
                                                       'queue_frames': 400}))
        self.assertEqual(value['limits']['burst_frames'], 300)
        with self.assertRaises(ContractError):
            validate_attachment(attachment(limits={'burst_frames': 4096, 'queue_frames': 256}))
        with self.assertRaises(ContractError):
            validate_attachment(attachment(limits={'max_seconds': 10}))
        with self.assertRaises(ContractError):
            validate_attachment(attachment(limits={'max_bytes': 1024}))

    def test_registration_requires_full_identity_and_fixed_ssh_fields(self):
        value = registration()
        self.assertIs(validate_registration(value), value)
        with self.assertRaises(ContractError):
            validate_registration({**value, 'machine_uuid': 'not-a-uuid'})
        with self.assertRaises(ContractError):
            validate_registration({**value, 'ssh': {'host': '127.0.0.1', 'port': 22,
                                                    'user': 'ctflab_attach'}})
        with self.assertRaises(ContractError):
            validate_registration({**value, 'assistant_sha256': 'xyz'})
        with self.assertRaises(ContractError):
            validate_ssh_reference({'host': 'a b', 'port': 22, 'user': 'u',
                                    'identity': '/tmp/k'})

    def test_scenario_network_external_slot(self):
        self.assertIsNone(validate_network_external({'cidr': '192.168.50.0/24'}))
        slot = validate_network_external({'cidr': '192.168.50.0/24',
                                          'external': {'schema': 1, 'address': '192.168.50.9',
                                                       'mac': '02:AA:BB:CC:DD:EE'}})
        self.assertEqual(slot, {'address': '192.168.50.9', 'mac': '02:aa:bb:cc:dd:ee'})
        with self.assertRaises(ContractError):
            validate_network_external({'cidr': '192.168.50.0/24',
                                       'external': {'schema': 1, 'address': '192.168.60.9',
                                                    'mac': '02:aa:bb:cc:dd:ee'}})

    def test_hub_networks_old_formats_unchanged_and_external_strict(self):
        plan = hub_plan()
        # 旧格式：三成员dict、无external槽位
        flattened, external = validate_hub_networks(plan, {'lab0': {'n2': 40000, 'n3': 40001}})
        self.assertEqual(flattened, [40000, 40001])
        self.assertEqual(external, {})
        # 二成员整数直连 + external槽位声明 → 拒绝
        plan2 = hub_plan(networks_with_external=('lab0',), nodes=('n1', 'n2'))
        with self.assertRaises(ContractError):
            validate_hub_networks(plan2, {'lab0': 40000})
        # 带external槽位：dict必须含external端口
        plan3 = hub_plan(networks_with_external=('lab0',))
        flattened, external = validate_hub_networks(
            plan3, {'lab0': {'n2': 40000, 'n3': 40001, 'external': 40002}})
        self.assertEqual(external, {'lab0': 40002})
        # 声明槽位但端口规划缺预留口 → 拒绝（防静默丢弃）
        with self.assertRaises(ContractError):
            validate_hub_networks(plan3, {'lab0': {'n2': 40000, 'n3': 40001}})
        # dict键必须恰为非中心成员（保持旧契约）
        with self.assertRaises(ContractError):
            validate_hub_networks(plan3, {'lab0': {'n2': 40000, 'external': 40002}})
        # 未声明槽位却携带external端口 → 拒绝
        with self.assertRaises(ContractError):
            validate_hub_networks(plan, {'lab0': {'n2': 40000, 'n3': 40001, 'external': 40002}})

    def test_challenge_token_binds_secret_session_nonces(self):
        secret = session_secret()
        self.assertEqual(len(secret), 64)
        base = challenge_token(secret, str(uuid.uuid4()), 'b' * 32, 'c' * 32)
        self.assertEqual(len(base), 64)
        other = challenge_token('f' * 64, str(uuid.uuid4()), 'b' * 32, 'c' * 32)
        self.assertNotEqual(base, other)
        with self.assertRaises(ContractError):
            challenge_token('short', str(uuid.uuid4()), 'b' * 32, 'c' * 32)

    def test_attach_store_persists_and_rejects_generation_drift(self):
        with tempfile.TemporaryDirectory() as root:
            store = AttachStore(root, str(uuid.uuid4()), generation=2, network_id='lab0')
            self.assertIsNone(store.load())
            binding = {'schema': 1, 'instance_uuid': store.instance_uuid, 'generation': 2,
                       'network_id': 'lab0', 'plan_sha256': 'd' * 64, 'session_uuid': str(uuid.uuid4())}
            store.save(binding)
            loaded = store.load()
            self.assertEqual(loaded['session_uuid'], binding['session_uuid'])
            check_generation(loaded, instance_uuid=store.instance_uuid, generation=2,
                             plan_sha256='d' * 64)
            with self.assertRaises(ContractError):
                check_generation(loaded, instance_uuid=store.instance_uuid, generation=3,
                                 plan_sha256='d' * 64)
            store.clear()
            self.assertIsNone(store.load())


class SshBindingTests(unittest.TestCase):
    """连接前SSH配置绑定：server_uuid必须等于登记node_uuid，并按固定入口预检。"""

    def config(self, node_uuid):
        import tempfile
        root = Path(tempfile.mkdtemp()).resolve()
        identity = root / 'kali-key'; identity.write_bytes(b'key')
        identity.chmod(0o600)
        known = root / 'known_hosts'; known.write_bytes(b'')
        known.chmod(0o600)
        ssh = root / 'ssh'; ssh.write_bytes(b'')
        return {'schema': 1, 'host': '127.0.0.1', 'port': 22, 'user': 'ctflab_attach',
                'ssh': str(ssh), 'identity': str(identity), 'known_hosts': str(known),
                'known_hosts_sha256': __import__('hashlib').sha256(b'').hexdigest(),
                'server_uuid': node_uuid}

    def test_matching_server_uuid_passes_fixed_entry_check(self):
        from ctflab_external_attach import bind_ssh_config
        node = str(uuid.uuid4())
        arguments = bind_ssh_config(self.config(node), {'node_uuid': node})
        self.assertIn('ctflab-external-l2-v1', arguments)

    def test_mismatched_server_uuid_rejected(self):
        from ctflab_external_attach import bind_ssh_config
        with self.assertRaises(ContractError):
            bind_ssh_config(self.config(str(uuid.uuid4())), {'node_uuid': str(uuid.uuid4())})

    def test_incomplete_config_rejected_before_spawn(self):
        from ctflab_external_attach import bind_ssh_config
        node = str(uuid.uuid4())
        broken = self.config(node); broken.pop('known_hosts_sha256')
        with self.assertRaises(ContractError):
            bind_ssh_config(broken, {'node_uuid': node})


class SwitchAttachTests(unittest.TestCase):
    """交换机认证接入口：转发/门禁/拒绝路径/计数；全部回环合成。"""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.secret = 'ab' * 32
        self.external_listener = socket.socket()
        self.external_listener.bind(('127.0.0.1', 0))
        self.external_listener.listen(1)
        self.external_port = self.external_listener.getsockname()[1]
        self.port = 25710
        self.server = DHCPServer(self.port, {'02:11:22:33:44:55': '192.168.242.20'},
                                 self.root / 'net.json',
                                 config=DHCPConfig(registered_only=True), instance_uuid=None,
                                 external={'mac': '02:aa:bb:cc:dd:ee', 'address': '192.168.242.66',
                                           'secret': self.secret,
                                           'allowed_macs': ['02:11:22:33:44:55']})
        original = self.server._prepare_external_listener

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

    def test_authenticated_external_bidirectional_gated_forwarding(self):
        session_uuid = str(uuid.uuid4())
        node = socket.create_connection(('127.0.0.1', self.port))
        self.addCleanup(node.close)
        relay = socket.create_connection(('127.0.0.1', self.external_port))
        self.addCleanup(relay.close)
        authenticate_switch(relay, session_uuid, self.secret)
        # Kali广播ARP（源/发送方绑定预约MAC+IP）→ 放行转发
        arp_request = (bytes.fromhex('ffffffffffff') + bytes.fromhex('02aabbccddee')
                       + struct.pack('!H', 0x0806) + b'\x00\x01\x08\x00\x06\x04\x00\x01'
                       + bytes.fromhex('02aabbccddee') + socket.inet_aton('192.168.242.66')
                       + b'\x00' * 6 + socket.inet_aton('192.168.242.20'))
        relay.sendall(struct.pack('!I', len(arp_request)) + arp_request)
        node.settimeout(2)
        received = node.recv(65536)
        self.assertEqual(received[4:10], b'\xff' * 6)
        # 靶机单播回应 → egress门禁放行（源为登记节点MAC）
        arp_reply = (bytes.fromhex('02aabbccddee') + bytes.fromhex('021122334455')
                     + struct.pack('!H', 0x0806) + b'\x00\x02\x08\x00\x06\x04\x00\x02'
                     + bytes.fromhex('021122334455') + socket.inet_aton('192.168.242.20')
                     + bytes.fromhex('02aabbccddee') + socket.inet_aton('192.168.242.66'))
        node.sendall(struct.pack('!I', len(arp_reply)) + arp_reply)
        relay.settimeout(2)
        reply = relay.recv(65536)
        self.assertEqual(reply[4:10], bytes.fromhex('02aabbccddee'))
        # 未登记节点MAC发往外部 → egress拒绝
        stray = (bytes.fromhex('02aabbccddee') + bytes.fromhex('029988776655')
                 + struct.pack('!H', 0x0806) + b'\x00\x02\x08\x00\x06\x04\x00\x02'
                 + bytes.fromhex('029988776655') + socket.inet_aton('192.168.242.77')
                 + bytes.fromhex('02aabbccddee') + socket.inet_aton('192.168.242.66'))
        node.sendall(struct.pack('!I', len(stray)) + stray)
        with self.assertRaises(socket.timeout):
            relay.recv(65536)
        # 伪造源MAC的入站帧 → ingress拒绝并计入门禁丢弃
        spoofed = (bytes.fromhex('ffffffffffff') + bytes.fromhex('021122334455')
                   + struct.pack('!H', 0x0806) + b'\x00' * 28)
        relay.sendall(struct.pack('!I', len(spoofed)) + spoofed)
        time.sleep(0.4)
        state = json.loads((self.root / 'net.json').read_text())
        self.assertGreaterEqual(state['counters']['dropped_external_gate'], 1)
        self.assertEqual(state['external']['frames_dropped'], state['counters']['dropped_external_gate'])
        self.assertEqual(state['external']['authenticated_session'], session_uuid)
        self.assertEqual(state['external']['mac'], '02:aa:bb:cc:dd:ee')
        self.assertIsNotNone(state['external']['port'])

    def test_second_connection_not_accepted_while_session_active(self):
        first = socket.create_connection(('127.0.0.1', self.external_port))
        self.addCleanup(first.close)
        authenticate_switch(first, str(uuid.uuid4()), self.secret)
        second = socket.create_connection(('127.0.0.1', self.external_port))
        self.addCleanup(second.close)
        with self.assertRaises(Exception):
            authenticate_switch(second, str(uuid.uuid4()), self.secret)

    def test_wrong_token_never_authenticates(self):
        peer = socket.create_connection(('127.0.0.1', self.external_port))
        self.addCleanup(peer.close)
        # 用错误秘密计算令牌：交换机拒绝并断开，认证函数报错。
        with self.assertRaises(Exception):
            authenticate_switch(peer, str(uuid.uuid4()), 'cd' * 32)

    def test_state_without_external_keeps_original_shape(self):
        plain = DHCPServer(self.port + 1, {}, self.root / 'plain.json',
                           config=DHCPConfig(registered_only=True), instance_uuid=None)
        self.assertIsNone(plain.external)
        self.assertIsNone(plain.external_gate)


class GuestChannelStub:
    """Kali助手替身：动态应答握手，随后按预置帧序发送；收集宿主→来宾记录。"""

    def __init__(self, frames, registration, session_uuid, *, machine_uuid='sentinel'):
        import io
        from ctflab_external_l2 import encode_record
        self.incoming = io.BytesIO()
        self.collected = io.BytesIO()
        self._read_pos = 0
        self._frames = list(frames)
        self._sequence = 1
        self._replied = False
        self.registration = registration
        self.session_uuid = session_uuid
        self.machine_uuid = machine_uuid
        self.process = type('P', (), {})()
        self.process.stdout = self.incoming
        self.process.stdin = self.collected
        self.process.poll = lambda: None

    def _fill(self):
        import json
        import struct
        from ctflab_contract import canonical
        from ctflab_external_l2 import encode_record, RECORD_CONTROL, RECORD_FRAME
        data = self.collected.getvalue()
        if not self._replied and len(data) >= 7:
            kind, _sequence, length = struct.unpack('!BIH', data[:7])
            if kind == RECORD_CONTROL and len(data) >= 7 + length:
                hello = json.loads(data[7:7 + length])
                reply = {'handshake': 'ctflab-kali-attach/1',
                         'session_uuid': self.session_uuid,
                         'challenge_echo': hello['challenge'],
                         'assistant_sha256': self.registration['assistant_sha256'],
                         'machine_uuid': self.machine_uuid}
                self.incoming.write(encode_record(RECORD_CONTROL, 0,
                                                  canonical(reply).encode()))
                self._replied = True
        if self._replied and self._frames:
            self.incoming.write(encode_record(RECORD_FRAME, self._sequence,
                                              self._frames.pop(0)))
            self._sequence += 1

    def read(self, size):
        # BytesIO读写共用位置；读侧维护独立位置避免写入后读不到。
        self._fill()
        data = self.incoming.getvalue()
        chunk = data[self._read_pos:self._read_pos + size]
        self._read_pos += len(chunk)
        return chunk

    def write(self, raw):
        return self.collected.write(raw)

    def close(self):
        pass


class RelayTests(unittest.TestCase):
    def _registration(self):
        return {'node_uuid': str(uuid.uuid4()),
                'machine_uuid': '0d1f7e57-7b1e-4c8e-9c8d-2f1a3b4c5d60',
                'assistant_sha256': 'a' * 64}

    def test_relay_forwards_gated_frames_both_directions(self):
        import io
        from ctflab_external_l2 import encode_record, RECORD_FRAME
        attachment_value = attachment()
        policy = policy_summary(attachment_value, ['02:11:22:33:44:55'])
        # 交换机侧替身：accept一次认证，然后收发帧。
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        endpoint = ('127.0.0.1', listener.getsockname()[1])
        switch_frames = []
        accepted = []

        def switch_thread():
            peer, _ = listener.accept()
            accepted.append(peer)
            self.addCleanup(peer.close)
            peer.settimeout(5)
            line = b''
            while not line.endswith(b'\n'):
                line += peer.recv(256)
            text = line.decode().split()
            self.assertEqual(text[0], 'AUTH')
            nonce_switch = 'e' * 32
            peer.sendall(f'CHALLENGE {nonce_switch}\n'.encode())
            token_line = b''
            while not token_line.endswith(b'\n'):
                token_line += peer.recv(256)
            expected = challenge_token(self_secret, text[1], nonce_switch, text[2])
            self.assertEqual(token_line.decode().strip(), 'TOKEN ' + expected)
            peer.sendall(f'READY {text[1]}\n'.encode())
            # 收一条来自Kali的帧
            header = peer.recv(4)
            length = struct.unpack('!I', header)[0]
            frame = peer.recv(length)
            switch_frames.append(frame)

        self_secret = self.secret = 'ab' * 32
        thread = threading.Thread(target=switch_thread, daemon=True)
        thread.start()
        # SSH通道替身：动态握手应答 + Kali发出的ARP广播帧。
        arp_request = (bytes.fromhex('ffffffffffff') + bytes.fromhex('02aabbccddee')
                       + struct.pack('!H', 0x0806) + b'\x00\x01\x08\x00\x06\x04\x00\x01'
                       + bytes.fromhex('02aabbccddee') + socket.inet_aton('192.168.50.9')
                       + b'\x00' * 6 + socket.inet_aton('192.168.50.20'))
        registration = self._registration()
        session_uuid = str(uuid.uuid4())
        channel = GuestChannelStub([arp_request], registration, session_uuid,
                                   machine_uuid=registration['machine_uuid'])
        ready_marks = []
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

        report = run_relay({'host': '127.0.0.1'}, attachment_value, policy, self.secret,
                           session_uuid, endpoint,
                           spawn=lambda arguments: channel.process, max_idle=1.0,
                           channel=channel, wait=wait_readable,
                           registration=registration,
                           on_ready=lambda identity: ready_marks.append(identity))
        thread.join(timeout=3)
        self.assertEqual(len(ready_marks), 1, '握手通过后应回调on_ready')
        self.assertEqual(ready_marks[0]['identity_state'], 'verified')
        self.assertEqual(len(switch_frames), 1)
        self.assertEqual(switch_frames[0].ljust(60, b'\x00'), arp_request.ljust(60, b'\x00'))
        self.assertEqual(report['frames_to_lab'], 1)
        listener.close()

    def test_relay_rejects_spoofed_source_without_forwarding(self):
        from ctflab_external_l2 import encode_record, RECORD_FRAME
        attachment_value = attachment()
        policy = policy_summary(attachment_value, ['02:11:22:33:44:55'])
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        endpoint = ('127.0.0.1', listener.getsockname()[1])

        def switch_thread():
            peer, _ = listener.accept()
            peer.settimeout(5)
            line = b''
            while not line.endswith(b'\n'):
                line += peer.recv(256)
            text = line.decode().split()
            peer.sendall(f'CHALLENGE {"e" * 32}\n'.encode())
            token_line = b''
            while not token_line.endswith(b'\n'):
                token_line += peer.recv(256)
            peer.sendall(f'READY {text[1]}\n'.encode())
            time.sleep(0.8)
            peer.close()

        thread = threading.Thread(target=switch_thread, daemon=True)
        thread.start()
        spoofed = (bytes.fromhex('ffffffffffff') + bytes.fromhex('021122334455')
                   + struct.pack('!H', 0x0806) + b'\x00' * 28)
        registration = self._registration()
        session_uuid = str(uuid.uuid4())
        channel = GuestChannelStub([spoofed], registration, session_uuid,
                                   machine_uuid=registration['machine_uuid'])
        ready = []
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

        report = run_relay({'host': '127.0.0.1'}, attachment_value, policy, 'ab' * 32,
                           session_uuid, endpoint,
                           spawn=lambda arguments: channel.process, max_idle=1.0,
                           channel=channel, wait=wait_readable,
                           registration=registration,
                           on_ready=lambda identity: ready.append(identity))
        thread.join(timeout=3)
        self.assertEqual(len(ready), 1)
        self.assertEqual(report['frames_to_lab'], 0)
        self.assertEqual(report['dropped'], 1)
        listener.close()

    def _holding_endpoint(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        self.addCleanup(listener.close)
        holder = threading.Thread(target=lambda: (lambda peer: (time.sleep(1.5), peer.close()))(
            listener.accept()[0]), daemon=True)
        holder.start()
        return ('127.0.0.1', listener.getsockname()[1])

    def test_handshake_rejects_wrong_assistant_digest(self):
        attachment_value = attachment()
        policy = policy_summary(attachment_value, ['02:11:22:33:44:55'])
        registration = self._registration()
        session_uuid = str(uuid.uuid4())
        channel = GuestChannelStub([], registration, session_uuid,
                                   machine_uuid=registration['machine_uuid'])
        # 桩按自身registration回显——改成不匹配摘要
        channel.registration = {'assistant_sha256': 'c' * 64}
        with self.assertRaises(Exception):
            run_relay({'host': '127.0.0.1'}, attachment_value, policy, 'ab' * 32,
                      session_uuid, self._holding_endpoint(), backend='hub',
                      channel=channel, wait=lambda readables, timeout: [],
                      registration=registration, max_idle=0.5)

    def test_handshake_rejects_machine_uuid_mismatch(self):
        attachment_value = attachment()
        policy = policy_summary(attachment_value, ['02:11:22:33:44:55'])
        registration = self._registration()
        session_uuid = str(uuid.uuid4())
        channel = GuestChannelStub([], registration, session_uuid,
                                   machine_uuid='99999999-9999-9999-9999-999999999999')
        with self.assertRaises(Exception):
            run_relay({'host': '127.0.0.1'}, attachment_value, policy, 'ab' * 32,
                      session_uuid, self._holding_endpoint(), backend='hub',
                      channel=channel, wait=lambda readables, timeout: [],
                      registration=registration, max_idle=0.5)

    def test_handshake_degraded_identity_is_explicit(self):
        attachment_value = attachment()
        policy = policy_summary(attachment_value, ['02:11:22:33:44:55'])
        registration = self._registration()
        session_uuid = str(uuid.uuid4())
        # 未登记替代身份策略时不可自动降级。
        channel = GuestChannelStub([], registration, session_uuid, machine_uuid=None)
        marks = []
        with self.assertRaises(ContractError):
            run_relay({'host': '127.0.0.1'}, attachment_value, policy, 'ab' * 32,
                      session_uuid, self._holding_endpoint(), backend='hub',
                      channel=channel, wait=lambda readables, timeout: [],
                      registration=registration, on_ready=marks.append, max_idle=0.5)
        self.assertEqual(marks, [])


class ScenarioV2ExternalTests(unittest.TestCase):
    """场景v2 external槽位：通过校验进入计划；与节点地址/MAC冲突或重复被拒。"""

    def manifest(self, external=True, duplicate_address=False, duplicate_mac=False):
        node = {'asset': 'linux', 'cpus': 1, 'memory_mb': 512, 'firmware': 'bios',
                'disk_bus': 'ide', 'depends_on': [],
                'interfaces': [{'id': 'eth0', 'network': 'lab0',
                                'address': '192.168.50.9' if duplicate_address else '192.168.50.20',
                                'mac': '02:aa:bb:cc:dd:ee' if duplicate_mac else 'derived',
                                'model': 'e1000'}]}
        networks = {'lab0': {'cidr': '192.168.50.0/24', 'uplink': 'none'}}
        if external:
            networks['lab0']['external'] = {'schema': 1, 'address': '192.168.50.9',
                                            'mac': '02:aa:bb:cc:dd:ee'}
        return {'schema': 2, 'scenario_id': 'extlab',
                'assets': {'linux': {'sha256': 'b' * 64, 'architecture': 'x86_64',
                                     'source': '自建', 'license': '内部',
                                     'verification': 'unverified'}},
                'networks': networks, 'nodes': {'n1': node},
                'policy': {'internet': False, 'host_forwards': [], 'failure': 'preserve'}}

    def test_external_slot_accepted_and_plan_keeps_field(self):
        from ctflab_scenario_v2 import instance_plan
        plan = instance_plan(self.manifest(), str(uuid.uuid4()))
        self.assertEqual(plan['manifest']['networks']['lab0']['external']['address'], '192.168.50.9')

    def test_external_conflicts_with_node_address_or_mac_rejected(self):
        from ctflab_scenario_v2 import instance_plan
        with self.assertRaises(Exception):
            instance_plan(self.manifest(duplicate_address=True), str(uuid.uuid4()))
        with self.assertRaises(Exception):
            instance_plan(self.manifest(duplicate_mac=True), str(uuid.uuid4()))

    def test_invalid_slot_shape_rejected(self):
        from ctflab_scenario_v2 import instance_plan
        value = self.manifest()
        value['networks']['lab0']['external'] = {'schema': 1, 'address': '192.168.60.9',
                                                 'mac': '02:aa:bb:cc:dd:ee'}
        with self.assertRaises(Exception):
            instance_plan(value, str(uuid.uuid4()))
        value['networks']['lab0']['external'] = {'schema': 1, 'address': '192.168.50.9',
                                                 'mac': '06:aa:bb:cc:dd:ee'}
        with self.assertRaises(Exception):
            instance_plan(value, str(uuid.uuid4()))



class IdleHeartbeatRegressionTests(unittest.TestCase):
    def test_idle_session_survives_fifteen_seconds_with_real_encoded_heartbeats(self):
        from unittest.mock import patch
        import struct
        from ctflab_external_l2 import encode_record, RECORD_HEARTBEAT
        current = [0.0]
        registration = {'machine_uuid': str(uuid.uuid4()), 'assistant_sha256': 'a' * 64}
        class EchoChannel(GuestChannelStub):
            def write(self, raw):
                super().write(raw)
                kind, _, _ = struct.unpack('!BIH', bytes(raw[:7]))
                if kind == RECORD_HEARTBEAT:
                    self.incoming.write(encode_record(RECORD_HEARTBEAT, self._sequence))
                    self._sequence += 1
        channel = EchoChannel([], registration, str(uuid.uuid4()),
                              machine_uuid=registration['machine_uuid'])
        peer, remote = socket.socketpair()
        self.addCleanup(remote.close)
        def wait(readables, timeout):
            self.assertLessEqual(timeout, 0.5, '空闲等待必须及时响应停止，不等待整个心跳周期')
            current[0] += min(timeout, 5)
            channel._fill()
            if channel._read_pos < len(channel.incoming.getvalue()):
                return [channel.process.stdout]
            return []
        value = attachment()
        with patch('ctflab_external_attach.connect_switch', return_value=peer):
            report = run_relay({}, value, policy_summary(value, ['02:11:22:33:44:55']),
                               'ab' * 32, channel.session_uuid, ('127.0.0.1', 1),
                               backend='hub', channel=channel, registration=registration,
                               clock=lambda: current[0], wait=wait,
                               stop=lambda: current[0] >= 50)
        self.assertEqual(report['reason'], 'completed')
        self.assertGreaterEqual(channel._sequence, 4)



class CLIPreparationRegressionTests(unittest.TestCase):
    def test_primary_cli_materials_contains_executable_approved_parameters(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            value = attachment()
            for name, data in [('attachment', value), ('policy', {'allowed_macs': ['02:11:22:33:44:55']})]:
                path = root/(name+'.json')
                path.write_text(json.dumps(data)); path.chmod(0o600)
            session = str(uuid.uuid4())
            result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1]/'ctflab.py'),
                                     'external-attach', 'materials', '--destination', str(root/'materials'),
                                     '--attachment', str(root/'attachment.json'),
                                     '--policy', str(root/'policy.json'), '--session', session],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr+result.stdout)
            manifest = json.loads(result.stdout)
            self.assertEqual(manifest['prepared']['session_uuid'], session)
            self.assertIn('--instance-uuid '+value['instance_uuid'], manifest['prepared']['setup_command'])
            self.assertIn('--policy-sha256 '+policy_summary(value, ['02:11:22:33:44:55'])['policy_sha256'],
                          manifest['prepared']['setup_command'])

    def test_connect_passes_preapproved_uuid_registration_and_bounded_quota(self):
        from unittest.mock import patch
        from contextlib import redirect_stdout
        import ctflab_external_attach as module
        import io
        registration = {'schema': 1, 'kind': 'kali-l2-v1', 'name': 'test',
                        'node_uuid': str(uuid.uuid4()), 'machine_uuid': str(uuid.uuid4()),
                        'vendor': 'VMware, Inc.', 'product': 'VMware Virtual Platform',
                        'ssh': {'host': '127.0.0.1', 'port': 22, 'user': 'ctflab_attach',
                                'identity': '/tmp/test-key'}, 'assistant_sha256': 'a'*64}
        session = str(uuid.uuid4())
        values = {'reg': registration, 'attachment': attachment(),
                  'policy': {'allowed_macs': ['02:11:22:33:44:55']}, 'ssh': {}}
        args = ['connect', '--registration', 'reg', '--attachment', 'attachment',
                '--policy', 'policy', '--ssh-config', 'ssh', '--secret', 'a'*64,
                '--endpoint', '127.0.0.1:40000', '--session', session, '--duration', '60']
        with patch.object(module, '_load_json', side_effect=values.__getitem__), \
             patch.object(module, 'bind_ssh_config'), patch('signal.signal'), \
             patch.object(module, 'run_relay', return_value={'reason': 'completed'}) as relay, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(args), 0)
            self.assertEqual(relay.call_args.args[4], session)
            self.assertEqual(relay.call_args.kwargs['registration']['machine_uuid'], registration['machine_uuid'])
            self.assertEqual(relay.call_args.kwargs['quota'].limits['max_seconds'], 60)
            # 不能借本次duration扩大原批准的两小时会话上限。
            self.assertEqual(module.main(args[:-1]+['86400']), 2)
            self.assertEqual(relay.call_count, 1)



class AssistantApprovalTests(unittest.TestCase):
    """持久批准账本（设计§4.3）：登记摘要绑定材料清单，未批准不得连接。"""

    def setUp(self):
        import hashlib
        self.hashlib = hashlib
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.ledger = self.root/'approvals'
        from ctflab_kali_attach import materials
        self.manifest = materials(self.root/'materials')
        self.assistant_sha = self.manifest['files']['ctflab-kali-attach']

    def approved_registration(self, **overrides):
        # 节点/机器标识在同组断言内保持稳定；变化场景用overrides显式表达。
        if not hasattr(self, '_registration'):
            self._registration = registration()
            self._registration['assistant_sha256'] = self.assistant_sha
        value = dict(self._registration)
        value.update(overrides)
        return value

    def test_approve_binds_digest_and_is_idempotent(self):
        record = approve_assistant(self.approved_registration(), self.manifest, self.ledger)
        self.assertEqual(record['assistant_sha256'], self.assistant_sha)
        self.assertEqual(record['manifest_sha256'],
                         self.hashlib.sha256(canonical(self.manifest).encode()).hexdigest())
        again = approve_assistant(self.approved_registration(), self.manifest, self.ledger)
        self.assertTrue(again['duplicate'])
        self.assertEqual(len(load_assistant_approvals(self.ledger)), 1)
        # 换摘要必须有新清单批准；旧清单批准不覆盖新摘要。
        with self.assertRaises(ContractError):
            approve_assistant(self.approved_registration(assistant_sha256='b'*64),
                              self.manifest, self.ledger)

    def test_digest_mismatch_bad_manifest_and_corrupt_ledger_rejected(self):
        with self.assertRaises(ContractError):
            approve_assistant(self.approved_registration(assistant_sha256='b'*64),
                              self.manifest, self.ledger)
        with self.assertRaises(ContractError):
            approve_assistant(self.approved_registration(), dict(self.manifest, kind='other'),
                              self.ledger)
        approve_assistant(self.approved_registration(), self.manifest, self.ledger)
        ledger_file = self.ledger/'assistant-approvals.jsonl'
        self.assertEqual(ledger_file.stat().st_mode & 0o077, 0, '账本文件必须私有')
        ledger_file.write_text('not-json\n', encoding='utf-8')
        with self.assertRaises(ContractError):
            load_assistant_approvals(self.ledger)

    def test_require_approval_matches_node_machine_and_digest(self):
        approve_assistant(self.approved_registration(), self.manifest, self.ledger)
        entry = require_approved_assistant(self.approved_registration(), self.ledger)
        self.assertEqual(entry['assistant_sha256'], self.assistant_sha)
        for changed in (self.approved_registration(node_uuid=str(uuid.uuid4())),
                        self.approved_registration(machine_uuid=str(uuid.uuid4())),
                        self.approved_registration(assistant_sha256='b'*64)):
            with self.assertRaises(ContractError):
                require_approved_assistant(changed, self.ledger)

    def test_connect_cli_enforces_approval_when_ledger_provided(self):
        import io
        from contextlib import redirect_stdout
        import ctflab_external_attach as module
        record = self.approved_registration()
        values = {'reg': record, 'attachment': attachment(),
                  'policy': {'allowed_macs': ['02:11:22:33:44:55']}, 'ssh': {}}
        args = ['connect', '--registration', 'reg', '--attachment', 'attachment',
                '--policy', 'policy', '--ssh-config', 'ssh', '--secret', 'a'*64,
                '--endpoint', '127.0.0.1:40000', '--session', str(uuid.uuid4()),
                '--approvals-dir', str(self.ledger)]
        with patch.object(module, '_load_json', side_effect=values.__getitem__), \
             patch.object(module, 'bind_ssh_config'), patch('signal.signal'), \
             patch.object(module, 'run_relay', return_value={'reason': 'completed'}) as relay, \
             redirect_stdout(io.StringIO()):
            # main()把ContractError转成退出码2；未批准不得进入run_relay。
            self.assertEqual(module.main(args), 2)
            relay.assert_not_called()
            approve_assistant(record, self.manifest, self.ledger)
            self.assertEqual(module.main(args), 0)
            self.assertEqual(relay.call_count, 1)


class FrameChannelPipeReadinessTests(unittest.TestCase):
    def test_multiple_records_remain_visible_to_select_after_first_read(self):
        import select
        from ctflab_external_l2 import RecordStream, encode_record, RECORD_HEARTBEAT
        channel = FrameChannel.__new__(FrameChannel)
        wire = encode_record(RECORD_HEARTBEAT, 0) + encode_record(RECORD_HEARTBEAT, 1)
        channel.process = channel._spawn([sys.executable, '-u', '-c',
            'import sys,time; sys.stdout.buffer.write('+repr(wire)+'); sys.stdout.buffer.flush(); time.sleep(5)'])
        channel._start_transport()
        self.addCleanup(channel.close)
        stream = RecordStream(channel, channel)
        self.assertTrue(select.select([channel.readable], [], [], 3)[0])
        self.assertEqual(stream.receive()[1], 0)
        self.assertTrue(select.select([channel.readable], [], [], 0)[0],
                        '管道预读不能使完整下一条记录对select不可见')
        self.assertEqual(stream.receive()[1], 1)


if __name__ == '__main__':
    unittest.main()
