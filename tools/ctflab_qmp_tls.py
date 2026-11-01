"""经双向TLS和实例名称核验的可重连QMP；不会重放任何旧命令。"""
from collections import deque
import time
from ctflab_qmp_protocol import Session, ProtocolError
from ctflab_tls_endpoint import tcp, wrap_client


class QMPClient:
    def __init__(self, port, credentials, fingerprints, expected_name, timeout=5):
        self.socket = None
        self.timeout = timeout
        self.session = Session(identity_query=True)
        self.events = deque(maxlen=128)
        self.events_dropped = 0
        self.deadline = time.monotonic()+timeout
        try:
            self.socket = wrap_client(tcp(port, timeout), credentials, fingerprints)
            self.receive('greeting')
            self.request('qmp_capabilities')
            reply = self.request('query-name')
            if reply.get('return') != {'name': expected_name}:
                raise ProtocolError('QMP实例名称不匹配')
        except BaseException:
            self.close()
            raise

    def receive(self, kind):
        while True:
            remaining = self.deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('QMP超时；命令结果未知，不重放')
            self.socket.settimeout(remaining)
            data = self.socket.recv(4096)
            if not data:
                raise ConnectionError('QMP连接关闭')
            wanted = None
            for item in self.session.feed(data):
                if item['kind'] == 'event':
                    if len(self.events) == self.events.maxlen:
                        self.events_dropped += 1
                    self.events.append(item['message'])
                elif item['kind'] == kind:
                    wanted = item
            if wanted is not None:
                return wanted

    def request(self, command):
        try:
            remaining = self.deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('QMP操作超时')
            self.socket.settimeout(remaining)
            self.socket.sendall(self.session.request(command))
            return self.receive('response')['message']
        except BaseException:
            self.close()
            raise

    def command(self, command):
        if command not in ('query-status', 'system_powerdown'):
            raise ProtocolError('公开控制命令不允许')
        self.deadline = time.monotonic()+self.timeout
        return self.request(command)

    def close(self):
        self.session.close()
        if self.socket is not None:
            self.socket.close()
            self.socket = None

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.close()
