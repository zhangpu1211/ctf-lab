"""有界QMP协议核心；传输与身份认证由调用方负责，不自行连接或执行VM。"""
import json
import uuid


class ProtocolError(ValueError):
    pass


class Session:
    def __init__(self, limit=65536, *, identity_query=False):
        self.limit = limit
        self.buffer = b''
        self.state = 'greeting'
        self.pending = None
        self.prefix = uuid.uuid4().hex
        self.sequence = 0
        self.identity_query = identity_query

    def close(self):
        self.state = 'closed'
        self.buffer = b''
        self.pending = None

    def request(self, command):
        allowed = {'query-status', 'system_powerdown'} if self.state == 'ready' else {'qmp_capabilities'} if self.state == 'negotiate' else set()
        if self.state == 'ready' and self.identity_query:
            allowed.add('query-name')
        if command not in allowed or self.pending is not None:
            raise ProtocolError('命令未授权、会话未就绪或请求未完成')
        self.sequence += 1
        identity = f'{self.prefix}-{self.sequence}'
        self.pending = (identity, command)
        return json.dumps({'execute': command, 'id': identity}).encode()+b'\r\n'

    def feed(self, chunk):
        if self.state == 'closed' or not isinstance(chunk, bytes):
            raise ProtocolError('会话关闭或数据类型错误')
        if len(chunk) + len(self.buffer) > self.limit:
            self.close()
            raise ProtocolError('接收窗口超限')
        self.buffer += chunk
        results = []
        try:
            while b'\n' in self.buffer:
                raw, self.buffer = self.buffer.split(b'\n', 1)
                def unique(pairs):
                    out = {}
                    for key, value in pairs:
                        if key in out: raise ProtocolError('重复字段')
                        out[key] = value
                    return out
                def invalid(value): raise ProtocolError('非法JSON常量')
                message = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
                if not isinstance(message, dict): raise ProtocolError('消息不是对象')
                kinds = set(message) & {'QMP', 'event', 'return', 'error'}
                if len(kinds) != 1: raise ProtocolError('消息类型不明确')
                if self.state == 'greeting':
                    greeting = message.get('QMP')
                    if not isinstance(greeting, dict) or not isinstance(greeting.get('version'), dict) or not isinstance(greeting.get('capabilities'), list):
                        raise ProtocolError('握手无效')
                    self.state = 'negotiate'
                    results.append({'kind': 'greeting'})
                elif 'event' in message:
                    if self.state != 'ready' or not isinstance(message['event'], str): raise ProtocolError('事件无效')
                    results.append({'kind': 'event', 'message': message})
                elif 'return' in message or 'error' in message:
                    if self.pending is None or message.get('id') != self.pending[0]:
                        results.append({'kind': 'unmatched'})
                        continue
                    command = self.pending[1]
                    self.pending = None
                    if command == 'qmp_capabilities':
                        self.state = 'ready' if 'return' in message else 'negotiate'
                    results.append({'kind': 'response', 'command': command, 'message': message})
                else: raise ProtocolError('重复握手')
        except (ValueError, UnicodeError, RecursionError) as exc:
            self.close()
            raise ProtocolError('QMP格式错误；会话已关闭') from exc
        return results
