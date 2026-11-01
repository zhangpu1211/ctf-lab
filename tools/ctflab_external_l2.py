"""外部攻击机二层帧协议：版本化记录编解码、帧门禁与会话配额。

数据面记录通过固定SSH入口双向传输；不做逐包请求-应答。记录在分配缓冲区前
按类型上限拒绝超长长度；重复/回退序号关闭通道。门禁只放行登记绑定，不提供
MAC/IP伪造、分片绕过或二层攻击模式；广播发现独立限速。
"""
import hashlib
import ipaddress
import re
import struct

if __package__ in (None, ''):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctflab_contract import require, canonical

GENERAL_MAC = re.compile(r'[0-9a-f]{2}(?::[0-9a-f]{2}){5}')


def general_mac_bytes(text):
    """任意单播MAC文本；预订MAC的02前缀约束在契约层另行校验。"""
    require(type(text) is str and GENERAL_MAC.fullmatch(text.lower()) is not None,
            'invalid-request')
    raw = bytes(int(part, 16) for part in text.lower().split(':'))
    require(raw[0] & 1 == 0, 'invalid-request')
    return raw

RECORD_FRAME = 0x01
RECORD_CONTROL = 0x02
RECORD_HEARTBEAT = 0x03
RECORD_CLOSE = 0x04
RECORD_NAMES = {RECORD_FRAME: 'frame', RECORD_CONTROL: 'control',
                RECORD_HEARTBEAT: 'heartbeat', RECORD_CLOSE: 'close'}
RECORD_HEADER = 7  # type(1) + sequence(4) + length(2)
PAYLOAD_LIMITS = {RECORD_FRAME: 1514, RECORD_CONTROL: 4096,
                  RECORD_HEARTBEAT: 0, RECORD_CLOSE: 256}
ETHERTYPE_IPV4 = 0x0800
ETHERTYPE_ARP = 0x0806
BROADCAST_MAC = b'\xff' * 6
IP_PROTOCOLS = {1, 6, 17}  # ICMP/TCP/UDP；首版不转发其他协议。


def encode_record(kind, sequence, payload=b''):
    require(type(kind) is int and kind in RECORD_NAMES, 'invalid-request')
    require(type(sequence) is int and 0 <= sequence <= 2**32 - 1, 'invalid-request')
    limit = PAYLOAD_LIMITS[kind]
    require(type(payload) is bytes and len(payload) <= limit, 'invalid-request')
    return struct.pack('!BIH', kind, sequence, len(payload)) + payload


def decode_record(header):
    """header为7字节；调用方按返回长度继续读payload，长度在分配前拒绝。"""
    require(type(header) is bytes and len(header) == RECORD_HEADER, 'invalid-request')
    kind, sequence, length = struct.unpack('!BIH', header)
    require(kind in PAYLOAD_LIMITS and length <= PAYLOAD_LIMITS[kind], 'invalid-request')
    return kind, sequence, length


def control_payload(value):
    raw = canonical(value).encode()
    require(len(raw) <= PAYLOAD_LIMITS[RECORD_CONTROL], 'invalid-request')
    return raw


class RecordStream:
    """有界双向记录流；短读/超长即失败，不重放未知帧。"""

    def __init__(self, source, sink):
        self.source = source
        self.sink = sink
        self.sequence = 0
        self.expected_sequence = 0

    def send(self, kind, payload=b'', *, sequence=None):
        if sequence is None:
            sequence = self.sequence
            self.sequence += 1
        raw = encode_record(kind, sequence, payload)
        view = memoryview(raw)
        while view:
            written = self.sink.write(view)
            written = len(raw) if written is None else written
            view = view[written:]

    def receive(self, *, read_source=None):
        read = read_source or (lambda size: self.source.read(size))
        header = read(RECORD_HEADER)
        if len(header) < RECORD_HEADER:
            return None
        kind, sequence, length = decode_record(header)
        require(sequence == self.expected_sequence, 'invalid-request')
        self.expected_sequence += 1
        payload = b''
        if length:
            payload = read(length)
            require(payload is not None and len(payload) == length, 'invalid-request')
        return kind, sequence, payload


class TokenBucket:
    """固定速率+突发容量的令牌桶；时钟可注入。"""

    def __init__(self, rate_per_second, burst, *, clock=None):
        require(type(rate_per_second) is int and rate_per_second > 0, 'invalid-request')
        require(type(burst) is int and burst > 0, 'invalid-request')
        self.rate = rate_per_second
        self.burst = burst
        self.tokens = float(burst)
        self.clock = clock or __import__('time').monotonic
        self.updated = self.clock()

    def allow(self, cost=1):
        moment = self.clock()
        self.tokens = min(float(self.burst),
                          self.tokens + (moment - self.updated) * self.rate)
        self.updated = moment
        if self.tokens < cost:
            return False
        self.tokens -= cost
        return True


class SessionQuota:
    """会话级配额：帧速率/突发、双向字节累计与时长；超额即断开接入。"""

    def __init__(self, limits, *, started=None, clock=None):
        from ctflab_external_attach import validate_limits
        self.limits = validate_limits(limits)
        self.clock = clock or __import__('time').monotonic
        self.started = started if started is not None else self.clock()
        self.frames = self.limits['max_frames_per_second']
        self.burst = self.limits['burst_frames']
        self.main = TokenBucket(self.frames, self.burst, clock=self.clock)
        self.broadcast = TokenBucket(min(50, self.frames), min(50, self.burst), clock=self.clock)
        self.bytes = 0
        self.frames_total = 0
        self.frames_dropped = 0

    def expired(self):
        return self.clock() - self.started >= self.limits['max_seconds']

    def over_bytes(self, additional):
        return self.bytes + additional > self.limits['max_bytes']

    def consume(self, size, *, broadcast=False):
        """消费速率与配额；返回False表示该帧丢弃（计入丢弃计数）。"""
        if self.expired() or self.over_bytes(size):
            self.frames_dropped += 1
            return False
        bucket = self.broadcast if broadcast else self.main
        if not bucket.allow():
            self.frames_dropped += 1
            return False
        self.frames_total += 1
        self.bytes += size
        return True


class FrameGate:
    """帧门禁：以太类型白名单与登记MAC/IP绑定；方向区分接入与回程。"""

    def __init__(self, policy):
        require(type(policy) is dict and policy.get('schema') == 1, 'invalid-request')
        self.reserved_mac = general_mac_bytes(policy['mac'])
        self.reserved_ip = ipaddress.IPv4Address(policy['address'])
        self.subnet = ipaddress.IPv4Network(policy['cidr'], strict=True)
        self.allowed_macs = {general_mac_bytes(item) for item in policy['allowed_macs']}
        self.rejected = {'ethertype': 0, 'source-mac': 0, 'destination': 0,
                         'source-ip': 0, 'fragment': 0, 'protocol': 0,
                         'arp-binding': 0, 'short': 0}

    def _reject(self, reason):
        self.rejected[reason] += 1
        return False

    def _ethertype_ok(self, frame):
        if len(frame) < 14:
            return self._reject('short')
        ethertype = struct.unpack('!H', frame[12:14])[0]
        if ethertype not in (ETHERTYPE_IPV4, ETHERTYPE_ARP):
            return self._reject('ethertype')
        return True

    def ingress(self, frame):
        """Kali→实验：源绑定预约MAC/IP；目的只允许登记节点与必要发现地址。"""
        if not self._ethertype_ok(frame):
            return False
        destination, source = frame[:6], frame[6:12]
        if source != self.reserved_mac:
            return self._reject('source-mac')
        ethertype = struct.unpack('!H', frame[12:14])[0]
        if destination == BROADCAST_MAC:
            pass
        elif destination not in self.allowed_macs:
            return self._reject('destination')
        if ethertype == ETHERTYPE_ARP:
            return self._arp_ingress(frame)
        return self._ipv4_ingress(frame)

    def _ipv4_ingress(self, frame):
        if struct.unpack('!H', frame[12:14])[0] != ETHERTYPE_IPV4:
            return self._reject('ethertype')
        version_ihl = frame[14]
        if version_ihl >> 4 != 4 or (version_ihl & 0x0F) < 5 or len(frame) < 34:
            return self._reject('short')
        ihl = (version_ihl & 0x0F) * 4
        total_length = struct.unpack('!H', frame[16:18])[0]
        fragment = struct.unpack('!H', frame[20:22])[0]
        if total_length < ihl or 14 + total_length > len(frame):
            return self._reject('short')
        if fragment & 0x3FFF:  # MF置位或偏移非零：首版不分片转发，杜绝分片绕过。
            return self._reject('fragment')
        if frame[23] not in IP_PROTOCOLS:
            return self._reject('protocol')
        source = ipaddress.IPv4Address(frame[26:30])
        if source != self.reserved_ip:
            return self._reject('source-ip')
        destination = ipaddress.IPv4Address(frame[30:34])
        if destination not in self.subnet:
            return self._reject('destination')
        return True

    def _arp_ingress(self, frame):
        if len(frame) < 42:
            return self._reject('short')
        hardware, protocol = struct.unpack('!HH', frame[14:18])
        hlen, plen, operation = frame[18], frame[19], struct.unpack('!H', frame[20:22])[0]
        if hardware != 1 or protocol != ETHERTYPE_IPV4 or hlen != 6 or plen != 4 \
                or operation not in (1, 2):
            return self._reject('arp-binding')
        sender_mac, sender_ip = frame[22:28], ipaddress.IPv4Address(frame[28:32])
        target_ip = ipaddress.IPv4Address(frame[38:42])
        if sender_mac != self.reserved_mac or sender_ip not in (self.reserved_ip,
                                                                ipaddress.IPv4Address('0.0.0.0')):
            return self._reject('arp-binding')
        if target_ip not in self.subnet:
            return self._reject('destination')
        return True

    def egress(self, frame):
        """实验→Kali：来源必须为登记节点或网段DHCP；目的必须预约MAC或广播。"""
        if not self._ethertype_ok(frame):
            return False
        destination, source = frame[:6], frame[6:12]
        if source not in self.allowed_macs:
            return self._reject('source-mac')
        if destination != self.reserved_mac and destination != BROADCAST_MAC:
            return self._reject('destination')
        if struct.unpack('!H', frame[12:14])[0] == ETHERTYPE_ARP:
            if len(frame) < 42:
                return self._reject('short')
            sender_ip = ipaddress.IPv4Address(frame[28:32])
            if sender_ip not in self.subnet and sender_ip != ipaddress.IPv4Address('0.0.0.0'):
                return self._reject('source-ip')
            return True
        if struct.unpack('!H', frame[12:14])[0] == ETHERTYPE_IPV4:
            if len(frame) < 34:
                return self._reject('short')
            source_ip = ipaddress.IPv4Address(frame[26:30])
            if source_ip not in self.subnet:
                return self._reject('source-ip')
            fragment = struct.unpack('!H', frame[20:22])[0]
            if fragment & 0x3FFF:
                return self._reject('fragment')
        return True


def policy_digest(policy):
    return hashlib.sha256(canonical(policy).encode()).hexdigest()
