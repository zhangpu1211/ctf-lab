"""日志限额、接收进程独立性与证书到期边界。"""
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ctflab_bounded_log import collect, spawn
from ctflab_contract import ContractError
from ctflab_tls_endpoint import provision, certificate_status, fingerprints


class LogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_quota_drains_entire_stream_and_keeps_exact_prefix(self):
        data = bytes(range(256))*1000
        result = collect(self.root, 'qemu-stderr', io.BytesIO(data), limit=1024)
        self.assertEqual((self.root/'qemu-stderr.log').read_bytes(), data[:1024])
        self.assertEqual(result['discarded_bytes'], len(data)-1024)
        status = json.loads((self.root/'qemu-stderr.log-status.json').read_text())
        self.assertTrue(status['complete']); self.assertFalse(status['process_exit_verified'])

    def test_exclusive_log_and_invalid_quota_do_not_overwrite(self):
        collect(self.root, 'worker-console', io.BytesIO(b'old'))
        with self.assertRaises((ContractError, FileExistsError)):
            collect(self.root, 'worker-console', io.BytesIO(b'new'))
        self.assertEqual((self.root/'worker-console.log').read_bytes(), b'old')
        for limit in (True, 0, 9*1024**2):
            with self.assertRaises(ContractError): collect(self.root, 'qemu-stderr', io.BytesIO(b''), limit=limit)

    def test_independent_receiver_drains_owned_producer_pipe(self):
        # 独立子进程写入10MiB。生产者退出后才检查接收器，覆盖真实管道而非mock。
        receiver = spawn(self.root, 'qemu-stderr')
        try:
            producer = subprocess.Popen([sys.executable, '-I', '-B', '-c',
                'import sys; sys.stderr.buffer.write(b"x"*(10*1024**2))'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=receiver.stdin)
            receiver.stdin.close()
            self.assertEqual(producer.wait(timeout=20), 0)
            self.assertEqual(receiver.wait(timeout=20), 0)
        finally:
            if not receiver.stdin.closed: receiver.stdin.close()
            if receiver.poll() is None: receiver.wait(timeout=20)
        value = json.loads((self.root/'qemu-stderr.log-status.json').read_text())
        self.assertEqual(value['received_bytes'], 10*1024**2)
        self.assertEqual(value['stored_bytes'], 8*1024**2)
        self.assertEqual(value['discarded_bytes'], 2*1024**2)

    def test_receiver_and_producer_survive_launching_parent_exit(self):
        script = '''import os,subprocess,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from ctflab_bounded_log import spawn
receiver=spawn(Path(sys.argv[2]),'qemu-stderr')
subprocess.Popen([sys.executable,'-I','-B','-c',
    'import sys,time; time.sleep(.2); sys.stderr.buffer.write(b"x"*(10*1024**2))'],
    stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=receiver.stdin,close_fds=True)
receiver.stdin.close()
os._exit(73)
'''
        parent = subprocess.run([sys.executable, '-I', '-B', '-c', script,
                                 str(Path(__file__).resolve().parents[1]), str(self.root)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=15)
        self.assertEqual(parent.returncode, 73, parent.stderr.decode())
        deadline = time.monotonic()+15
        value = {}
        while time.monotonic() < deadline:
            try: value = json.loads((self.root/'qemu-stderr.log-status.json').read_text())
            except (OSError, ValueError): pass
            if value.get('complete'): break
            time.sleep(.02)
        self.assertTrue(value.get('complete'))
        self.assertEqual(value['received_bytes'], 10*1024**2)
        self.assertEqual(value['discarded_bytes'], 2*1024**2)

    def test_write_failure_still_drains_stream(self):
        class Failing:
            def __init__(self, wrapped): self.wrapped = wrapped
            def __enter__(self): return self
            def __exit__(self, *args): self.wrapped.close()
            def write(self, data): raise OSError('synthetic disk full')
            def fileno(self): return self.wrapped.fileno()
        real = os.fdopen
        def opened(fd, mode, *args, **kwargs):
            stream = real(fd, mode, *args, **kwargs)
            return Failing(stream) if mode == 'wb' else stream
        with patch('ctflab_bounded_log.os.fdopen', side_effect=opened):
            result = collect(self.root, 'qemu-stderr', io.BytesIO(b'x'*100000), limit=1024)
        self.assertEqual(result, {'received_bytes': 100000, 'stored_bytes': 0, 'discarded_bytes': 100000})
        self.assertEqual(json.loads((self.root/'qemu-stderr.log-status.json').read_text())['storage_error'], 'write-failed')

    def test_symlink_refused_without_touching_target(self):
        other = self.root/'other'; other.write_bytes(b'protected')
        (self.root/'qemu-stderr.log').symlink_to(other)
        with self.assertRaises(FileExistsError): collect(self.root, 'qemu-stderr', io.BytesIO(b'overwrite'))
        self.assertEqual(other.read_bytes(), b'protected')


class CertificateTests(unittest.TestCase):
    setUp = LogTests.setUp

    def test_valid_due_expired_future_and_tampered(self):
        try: import cryptography
        except ImportError: self.skipTest('缺少证书依赖')
        now = datetime.now(timezone.utc)
        path = self.root/'tls'; expected = provision(path, str(uuid.uuid4()))
        self.assertEqual(certificate_status(path, expected, now=now)['state'], 'valid')
        self.assertEqual(certificate_status(path, expected, now=now+timedelta(days=25))['state'], 'renewal-due')
        self.assertEqual(certificate_status(path, expected, now=now+timedelta(days=31))['state'], 'invalid')
        self.assertEqual(certificate_status(path, expected, now=now-timedelta(hours=1))['state'], 'invalid')
        before = fingerprints(path)
        certificate_status(path, expected)
        self.assertEqual(fingerprints(path), before)
        (path/'server-cert.pem').write_bytes(b'changed')
        with self.assertRaises(ValueError): certificate_status(path, expected)


if __name__ == '__main__': unittest.main()
