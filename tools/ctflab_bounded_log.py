"""独立、有容量上限的后台日志接收器；达到配额后继续排空管道。

每次运行使用新目录，保留旧日志。不解析内容、不向外转发、不停止生产进程。
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from ctflab_tls_endpoint import guard
from ctflab_contract import require

NAMES = ('worker-console', 'observe-exit-console', 'qemu-stderr', 'desktop-execute', 'desktop-display-worker','remote-execute','version-launch')
LIMIT = 8 * 1024**2


def collect(root, name, stream, *, limit=LIMIT, remaining_budget=False):
    root = guard(Path(root).absolute())
    require(type(remaining_budget) is bool)
    require(name in NAMES and type(limit) is int and (0 if remaining_budget else 1024) <= limit <= LIMIT)
    path = root / (name + '.log')
    status = root / (name + '.log-status.json')
    temporary = root / (name + '.log-status.pending')
    require(not status.exists() and not temporary.exists(), 'state-conflict')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    total = stored = 0
    failure = None

    def report(complete):
        value = {'schema': 1, 'limit_bytes': limit, 'received_bytes': total,
                 'stored_bytes': stored, 'discarded_bytes': total-stored,
                 'complete': complete, 'storage_error': failure,
                 'process_exit_verified': False}
        if status.exists(): guard(status)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            json.dump(value, output, sort_keys=True); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, status)

    with os.fdopen(fd, 'wb', buffering=0) as output:
        report(False)
        updated = time.monotonic()
        while True:
            # read1避免等待64KiB填满后才记录短错误信息。
            block = stream.read1(65536) if hasattr(stream, 'read1') else stream.read(65536)
            if not block: break
            total += len(block)
            piece = block[:max(0, limit-stored)] if failure is None else b''
            if piece:
                try:
                    offset = 0
                    while offset < len(piece):
                        written = output.write(piece[offset:])
                        if not written: raise OSError('日志写入未推进')
                        offset += written; stored += written
                except OSError:
                    failure = 'write-failed'
            if time.monotonic()-updated >= 1:
                try: report(False)
                except OSError: pass  # 磁盘满时继续排空，避免阻塞QEMU。
                updated = time.monotonic()
        try: os.fsync(output.fileno())
        except OSError: failure = 'flush-failed'
        report(True)
    return {'received_bytes': total, 'stored_bytes': stored, 'discarded_bytes': total-stored}


def spawn(root, name):
    """返回自有接收进程；调用方将stdin交给生产进程后立即关闭本地副本。"""
    require(name in NAMES)
    guard(root)
    options = ({'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
               if os.name == 'nt' else {'start_new_session': True})
    require(not (Path(root)/(name+'.log')).exists(), 'state-conflict')
    process = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).resolve()),
                             '--run', str(root), '--name', name],
                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, close_fds=True, **options)
    deadline = time.monotonic()+10
    while time.monotonic() < deadline:
        if (Path(root)/(name+'.log-status.json')).exists() and process.poll() is None:
            return process
        if process.poll() is not None: break
        time.sleep(.02)
    process.stdin.close()
    raise RuntimeError('后台日志接收器未就绪；未启动生产进程')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--name', choices=NAMES, required=True)
    args = parser.parse_args()
    collect(args.run, args.name, sys.stdin.buffer)
