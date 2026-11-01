"""自有子进程匿名管道QMP传输；不监听网络，不接管旧PID，不自动杀进程。

调用方创建并持有Popen和专用stdin/stdout，stderr须另行接日志。
本模块不提供跨用户认证、监督器重启接管或持久监督。
"""
from collections import deque
import queue
import threading
import time
from ctflab_qmp_protocol import Session, ProtocolError


class TransportError(RuntimeError):
    pass


class OwnedPipe:
    def __init__(self, process, timeout=5):
        if process.stdin is None or process.stdout is None or not 0 < timeout <= 60:
            raise ValueError('需要专用管道与有界超时')
        self.process = process
        self.timeout = timeout
        self.session = Session()
        self.events = deque(maxlen=128)
        self.events_dropped = 0
        self.incoming = queue.Queue(maxsize=32)
        self.writes = queue.Queue(maxsize=1)
        self.failed = threading.Event()
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.writer = threading.Thread(target=self._write, daemon=True)
        self.reader.start(); self.writer.start()

    def _read(self):
        try:
            while not self.closed.is_set():
                data = self.process.stdout.read1(4096)
                self.incoming.put_nowait(data)
                if not data: return
        except (OSError, ValueError, queue.Full):
            self.failed.set()

    def _write(self):
        while not self.closed.is_set():
            try: data, done = self.writes.get(timeout=.1)
            except queue.Empty: continue
            if self.closed.is_set():
                done.set()
                continue
            try:
                self.process.stdin.write(data)
                self.process.stdin.flush()
            except (OSError, ValueError): self.failed.set()
            finally: done.set()

    def _remaining(self, deadline):
        remaining = deadline-time.monotonic()
        if remaining <= 0 or self.closed.is_set() or self.failed.is_set():
            raise TransportError('控制超时或通道不可用；结果未知，不重放')
        return remaining

    def _receive(self, deadline, kind):
        while True:
            remaining = self._remaining(deadline)
            try: data = self.incoming.get(timeout=min(remaining,.05))
            except queue.Empty: continue
            if not data: raise TransportError('控制管道已断开；未确认命令结果')
            wanted = None
            for item in self.session.feed(data):
                if item['kind'] == 'event':
                    if len(self.events) == self.events.maxlen: self.events_dropped += 1
                    self.events.append(item['message'])
                elif item['kind'] == kind: wanted = item
            if wanted is not None: return wanted

    def _command(self, command, deadline):
        data = self.session.request(command)
        done = threading.Event()
        self.writes.put_nowait((data, done))
        while not done.wait(min(.05,self._remaining(deadline))): pass
        self._remaining(deadline)
        return self._receive(deadline,'response')

    def connect(self):
        with self.lock:
            try:
                deadline=time.monotonic()+self.timeout
                self._receive(deadline,'greeting')
                response=self._command('qmp_capabilities',deadline)
                if self.session.state != 'ready': raise TransportError('能力协商失败')
                return response
            except (ProtocolError, TransportError, queue.Full):
                self.close(); raise

    def command(self, command):
        with self.lock:
            try: return self._command(command,time.monotonic()+self.timeout)
            except (ProtocolError, TransportError, queue.Full):
                self.close(); raise

    def pump(self):
        """空闲时消费事件；不发查询、不改变来宾状态。"""
        with self.lock:
            if self.closed.is_set(): return
            try:
                if self.failed.is_set(): raise TransportError('管道失败')
                while True:
                    try: data = self.incoming.get_nowait()
                    except queue.Empty: break
                    if not data:
                        self.close()
                        return
                    for item in self.session.feed(data):
                        if item['kind'] == 'event':
                            if len(self.events) == self.events.maxlen: self.events_dropped += 1
                            self.events.append(item['message'])
            except (ProtocolError, TransportError):
                self.close()
                raise

    def observe(self):
        code=self.process.poll()
        return {'pid':self.process.pid,'state':'running' if code is None else 'exited',
                'returncode':code,'control_available':code is None and self.session.state == 'ready' and not self.closed.is_set() and not self.failed.is_set(),
                'graceful_stop_verified':False,'events_dropped':self.events_dropped}

    def close(self):
        # 不关闭另一个线程正在阻塞读取的流，以免close本身无限阻塞。
        # 调用方仍持有进程/管道；实际退出后调用reap释放句柄。
        self.closed.set()
        self.session.close()

    def reap(self):
        if self.process.poll() is None:
            raise TransportError('进程仍在运行；保留句柄，不强制停止')
        self.close()
        self.reader.join(timeout=self.timeout)
        self.writer.join(timeout=self.timeout)
        if self.reader.is_alive() or self.writer.is_alive():
            raise TransportError('管道仍被占用；保留现场')
        self.process.stdin.close(); self.process.stdout.close()
