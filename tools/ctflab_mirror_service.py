"""已许可学生镜像的回环HTTPS只读入口；不对外监听，不改变系统信任或源签名。"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import ssl
import stat
import threading

from ctflab_contract import require
from ctflab_content_cache import verify_index
from ctflab_generation_store import digest
from ctflab_tls_endpoint import guard
from ctflab_windows_control import read_json


def identity(path):
    info = guard(path).stat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'permission-denied')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class MirrorView:
    def __init__(self, root, keys, origin, *, now=None):
        self.root = guard(Path(root).absolute())
        require(self.root.is_dir(), 'permission-denied')
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.keys = json.loads(json.dumps(keys))
        self.origin = origin
        self.index_identity = identity(self.root/'INDEX.json')
        self.receipt_identity = identity(self.root/'MIRROR.json')
        self.envelope = read_json(self.root/'INDEX.json', guard, 4*1024**2)
        payload, sha = verify_index(self.envelope, self.keys, origin, now=self.now())
        receipt = read_json(self.root/'MIRROR.json', guard, 4*1024**2)
        require(type(receipt) is dict and receipt.get('kind') == 'student-mirror-materials'
                and receipt.get('origin') == origin and receipt.get('signed_index_sha256') == sha
                and receipt.get('teacher_materials_included') is False, 'identity-unknown')
        require(identity(self.root/'INDEX.json') == self.index_identity
                and identity(self.root/'MIRROR.json') == self.receipt_identity, 'identity-unknown')
        require(payload['assets'] and all(a['audience'] == 'student' and a['redistribution'] == 'allowed'
                for a in payload['assets'].values()), 'permission-denied')
        expected = {a['path']: checksum for checksum, a in payload['assets'].items()}
        require(len(expected) == len(payload['assets']) and receipt.get('files') == expected, 'identity-unknown')
        self.entries = {}
        for checksum, asset in payload['assets'].items():
            name = asset['path']
            require(name.split('/')[0].casefold() not in ('index.json', 'mirror.json', 'sha256sums')
                    and name.casefold() not in {n.casefold() for n in self.entries}, 'permission-denied')
            path = self.root/name
            before = identity(path)
            require(before[2] == asset['size'] and digest(path) == checksum and identity(path) == before, 'identity-unknown')
            self.entries[name] = (path, checksum, before)
        raw = (self.root/'INDEX.json').read_bytes()
        require(identity(self.root/'INDEX.json') == self.index_identity and len(raw) <= 4*1024**2, 'identity-unknown')
        self.entries['INDEX.json'] = (self.root/'INDEX.json', hashlib.sha256(raw).hexdigest(), self.index_identity)

    def check(self):
        require(identity(self.root/'INDEX.json') == self.index_identity
                and identity(self.root/'MIRROR.json') == self.receipt_identity, 'identity-unknown')
        verify_index(self.envelope, self.keys, self.origin, now=self.now())

    @contextmanager
    def opened(self, name):
        self.check()
        require(name in self.entries, 'permission-denied')
        path, checksum, expected = self.entries[name]
        require(identity(path) == expected, 'identity-unknown')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            require((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) == expected
                    and stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'identity-unknown')
            yield stream, checksum, expected[2]


def byte_range(value, size):
    if value is None:
        return 0, size-1, False
    require(type(value) is str and len(value) <= 64, 'invalid-request')
    match = re.fullmatch(r'bytes=(\d{0,20})-(\d{0,20})', value)
    require(match and (match[1] or match[2]), 'invalid-request')
    if match[1]:
        start = int(match[1]); end = min(int(match[2]), size-1) if match[2] else size-1
        require(start <= end and start < size, 'invalid-request')
    else:
        suffix = int(match[2]); require(suffix > 0, 'invalid-request')
        start, end = max(0, size-suffix), size-1
    return start, end, True


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'CTFLabMirror/1'
    sys_version = ''

    def log_message(self, *args):
        pass  # 不将路径、HTTP头或无关网络输入写入持久日志。

    def do_HEAD(self):
        self.deliver(False)

    def do_GET(self):
        self.deliver(True)

    def error(self, code, *, size=None):
        self.send_response(code)
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        if size is not None:
            self.send_header('Content-Range', 'bytes */'+str(size))
        self.end_headers()

    def deliver(self, body):
        self.close_connection = True
        response_started = False
        original = self.requestline.split()
        if (len(original) != 3 or original[1] != self.path or len(self.path) > 2048
                or not self.path.startswith('/') or self.path[1:] not in self.server.view.entries):
            self.error(404); return
        # 固定ASCII索引路径；不解码百分号、不解析查询参数或目录索引，不暴露镜像收据/其他文件。
        name = self.path[1:]
        try:
            with self.server.view.opened(name) as (stream, checksum, size):
                etag = '"'+checksum+'"'
                ranges = self.headers.get_all('Range', [])
                if len(ranges) > 1:
                    self.error(416, size=size); return
                value = ranges[0] if ranges else None
                if value is not None and self.headers.get('If-Range', etag) != etag:
                    value = None
                try:
                    start, end, partial = byte_range(value, size)
                except (ValueError, RuntimeError):
                    self.error(416, size=size); return
                self.send_response(206 if partial else 200)
                self.send_header('Content-Length', str(end-start+1))
                self.send_header('Content-Type', 'application/json' if name == 'INDEX.json' else 'application/octet-stream')
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('ETag', etag)
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Connection', 'close')
                if partial:
                    self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                response_started = True
                self.end_headers()
                if body:
                    stream.seek(start); remaining = end-start+1
                    while remaining:
                        data = stream.read(min(65536, remaining))
                        require(data, 'identity-unknown')
                        self.wfile.write(data); remaining -= len(data)
        except (OSError, ValueError, RuntimeError):
            # 写出响应后不能再伪造第二份成功/错误HTTP；客户端仍必须验证签名与内容摘要。
            if not response_started:
                self.error(503)


class MirrorServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False
    request_queue_size = 8

    def __init__(self, view, certificate, key, *, port=0, host='127.0.0.1', maximum=8):
        require(host == '127.0.0.1' and type(port) is int and 0 <= port <= 65535
                and type(maximum) is int and 1 <= maximum <= 8, 'permission-denied')
        require(isinstance(view, MirrorView), 'permission-denied')
        certificate, key = guard(Path(certificate).absolute()), guard(Path(key).absolute())
        served = {entry[0] for entry in view.entries.values()}
        require(certificate not in served and key not in served, 'permission-denied')
        require(0 < certificate.stat().st_size <= 65536 and 0 < key.stat().st_size <= 65536, 'permission-denied')
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(certificate), str(key))
        context.set_alpn_protocols(['http/1.1'])
        self.context, self.view = context, view
        self.slots = threading.BoundedSemaphore(maximum)
        super().__init__((host, port), Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request); return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release(); raise

    def process_request_thread(self, request, client_address):
        connection = request
        try:
            # 在受限工作线程握手，未握手连接不能阻塞主接受循环；不接受明文HTTP。
            request.settimeout(5)
            connection = self.context.wrap_socket(request, server_side=True)
            self.finish_request(connection, client_address)
        except (OSError, ValueError, RuntimeError):
            pass
        finally:
            self.shutdown_request(connection)
            self.slots.release()

    def handle_error(self, request, client_address):
        pass
