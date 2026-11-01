"""新POSIX启动的可显式重接FIFO日志；只接日志，不控制或停止生产进程。"""
import argparse
from contextlib import contextmanager
from dataclasses import asdict
import os
from pathlib import Path
import select
import stat
import subprocess
import sys
import time
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from ctflab_contract import require, uuid_text, integer
from ctflab_generation_store import private_directory, digest
from ctflab_tls_endpoint import guard
from ctflab_windows_recovery import record, read_json
from ctflab_bounded_log import collect, LIMIT

MAX_SESSIONS = 16


def supported():
    require(sys.platform in ('darwin', 'linux') and os.name == 'posix', 'unsupported-platform')


def read(path):
    return read_json(Path(path), guard, 65536)


def file_identity(path, kind):
    info = guard(path).stat()
    require((stat.S_ISFIFO(info.st_mode) if kind == 'fifo' else stat.S_ISREG(info.st_mode))
            and info.st_nlink == 1, 'identity-unknown')
    return [info.st_dev, info.st_ino]


def scope(value):
    require(type(value) is dict and set(value) == {'instance_uuid', 'generation', 'node', 'attempt'})
    uuid_text(value['instance_uuid']); integer(value['generation'], 1)
    from ctflab_contract import identifier
    identifier(value['node'])
    require(type(value['attempt']) is str and len(value['attempt']) == 8
            and value['attempt'].isascii() and value['attempt'].isdigit(), 'identity-unknown')
    return value


def channel(root):
    supported(); root = guard(Path(root).absolute()); directory = guard(root/'log-channel')
    value = read(directory/'channel.json'); launch = read(root/'launch.json')
    require(type(value) is dict and set(value) == {'schema', 'scope', 'launch_sha256', 'fifo_identity', 'limit_bytes'}
            and type(value['schema']) is int and value['schema'] == 1 and value['limit_bytes'] == LIMIT
            and type(value['limit_bytes']) is int, 'identity-unknown')
    scope(value['scope'])
    require(launch.get('recoverable_logs') is True and launch.get('log_scope') == value['scope']
            and root.name == value['scope']['attempt'] and digest(root/'launch.json') == value['launch_sha256']
            and file_identity(directory/'stderr.fifo', 'fifo') == value['fifo_identity'], 'identity-unknown')
    file_identity(directory/'receiver.lock', 'regular')
    return directory, value


@contextmanager
def receiver_lock(directory):
    import fcntl
    expected = file_identity(directory/'receiver.lock', 'regular')
    fd = os.open(directory/'receiver.lock', os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require([info.st_dev, info.st_ino] == expected, 'identity-unknown')
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: require(False, 'resource-busy')
        yield
    finally: os.close(fd)


def initialize(root):
    """仅在新启动尝试中创建通道并返回生产者FD；失败保留现场。"""
    supported(); root = guard(Path(root).absolute()); launch = read(root/'launch.json')
    require(launch.get('recoverable_logs') is True, 'capability-unverified'); scope(launch['log_scope'])
    require(root.name == launch['log_scope']['attempt'], 'identity-unknown')
    directory = root/'log-channel'; private_directory(directory)
    private_directory(directory/'sessions'); record(directory/'receiver.lock', {})
    fifo = directory/'stderr.fifo'; os.mkfifo(fifo, 0o600)
    identity = file_identity(fifo, 'fifo')
    record(directory/'channel.json', {'schema': 1, 'scope': launch['log_scope'],
        'launch_sha256': digest(root/'launch.json'), 'fifo_identity': identity, 'limit_bytes': LIMIT})
    fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd); require([info.st_dev, info.st_ino] == identity, 'identity-unknown')
        os.set_blocking(fd, True)
        return fd
    except BaseException: os.close(fd); raise


def sessions(root):
    directory, value = channel(root); parent = guard(directory/'sessions'); result = []
    for index, path in enumerate(sorted(parent.iterdir()), 1):
        require(index <= MAX_SESSIONS, 'storage-insufficient'); uuid_text(path.name); guard(path)
        intent = read(path/'intent.json')
        require(intent == {'operation_id': path.name, 'channel_sha256': digest(directory/'channel.json'),
                           'automatic_replay': False}, 'identity-unknown')
        result.append(path)
    return result


def stored(root):
    total = 0
    for path in sessions(root):
        log = path/'qemu-stderr.log'
        if log.exists() or log.is_symlink():
            file_identity(log, 'regular'); total += log.stat().st_size
    require(total <= LIMIT, 'storage-insufficient')
    return total


def binding(root):
    directory, value = channel(root); bound = read(Path(root)/'binding.json')
    require(bound.get('launch_sha256') == value['launch_sha256'], 'identity-unknown')
    return bound


def status(root):
    """只读报告锁及源进程身份；不打开FIFO或建立接收器。"""
    directory, value = channel(root); paths = sessions(root); amount = stored(root)
    try:
        with receiver_lock(directory): active = False
    except ValueError as error:
        if getattr(error, 'code', None) != 'resource-busy': raise
        active = True
    from ctflab_qemu_driver import identity_status
    state = identity_status(binding(root)['identity'])
    return {'kind': 'posix-fifo-v1', 'receiver': 'lock-held' if active else 'not-receiving',
        'source_identity': state, 'sessions': len(paths), 'stored_bytes': amount, 'limit_bytes': LIMIT,
        'rearm_allowed': not active and state == 'running' and len(paths) < MAX_SESSIONS,
        'capture_complete': False, 'automatic_replay': False, 'vm_control_sent': False}


def spawn(root, operation, *, timeout=10):
    """调用方必须已持启动尝试命令门；同一操作重复只查询，不再次启动。"""
    uuid_text(operation); directory, value = channel(root)
    target = directory/'sessions'/operation
    if target.exists():
        sessions(root)
        return {'state': 'log-receiver-already-requested', 'automatic_replay': False, 'vm_control_sent': False}
    with receiver_lock(directory):
        require(len(sessions(root)) < MAX_SESSIONS, 'storage-insufficient')
        stored(root); private_directory(target)
        record(target/'intent.json', {'operation_id': operation, 'channel_sha256': digest(directory/'channel.json'),
                                     'automatic_replay': False})
    process = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).resolve()),
        '--run', str(root), '--operation-id', operation], stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if (target/'ready.json').exists() and process.poll() is None:
            try:
                ready = read(target/'ready.json')
                require(ready.get('operation_id') == operation
                        and ready.get('channel_sha256') == digest(directory/'channel.json'), 'identity-unknown')
                from ctflab_qemu_driver import native_observe, compare_identity
                from ctflab_windows_native import ProcessIdentity
                expected=ProcessIdentity(**ready['receiver_identity'])
                require(expected.pid==process.pid and compare_identity(expected,native_observe(process.pid))=='running','identity-unknown')
                return {'state': 'log-receiver-requested', 'automatic_replay': False, 'vm_control_sent': False,
                        'process': process}
            except (OSError,ValueError,RuntimeError,KeyError,TypeError):
                pass  # 独占记录可能尚在写入；只继续等待同一子进程，不派生或重发。
        if process.poll() is not None: break
        time.sleep(.02)
    # 无就绪回执不代表子进程未启动；保留意图，不终止/重放。
    return {'state': 'unknown', 'automatic_replay': False, 'vm_control_sent': False, 'process': process}


class Source:
    def __init__(self, root, fd):
        self.root = Path(root); self.fd = fd; self.deadline = time.monotonic()+30
        self.had_binding = False

    def read1(self, size):
        while True:
            directory, value = channel(self.root)
            info = os.fstat(self.fd)
            require([info.st_dev, info.st_ino] == value['fifo_identity'], 'identity-unknown')
            present = (self.root/'binding.json').exists()
            if present:
                binding(self.root); self.had_binding = True
            else:
                require(not self.had_binding and time.monotonic() < self.deadline, 'identity-unknown')
            try: block = os.read(self.fd, size)
            except BlockingIOError: block = None
            if block: return block
            # EOF只说明写端已关闭；不推断生产者退出或正常关机。
            if block == b'' and present: return b''
            select.select([self.fd], [], [], .1)
            if block == b'': time.sleep(.02)


def run(root, operation):
    supported(); uuid_text(operation); directory, value = channel(root)
    target = directory/'sessions'/operation; require(target in sessions(root), 'identity-unknown')
    with receiver_lock(directory):
        remaining = LIMIT-stored(root)
        fd = os.open(directory/'stderr.fifo', os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            from ctflab_qemu_driver import native_observe
            record(target/'ready.json', {'operation_id': operation, 'channel_sha256': digest(directory/'channel.json'),
                'receiver_identity': asdict(native_observe(os.getpid()))})
            result = collect(target, 'qemu-stderr', Source(root, fd), limit=remaining, remaining_budget=True)
            record(target/'complete.json', dict(result, capture_complete=False, process_exit_verified=False))
            return result
        finally: os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path); parser.add_argument('--operation-id', required=True)
    args = parser.parse_args(argv)
    try: run(args.run, args.operation_id); return 0
    except (OSError, ValueError, RuntimeError, TypeError, KeyError): return 2


if __name__ == '__main__': raise SystemExit(main())
