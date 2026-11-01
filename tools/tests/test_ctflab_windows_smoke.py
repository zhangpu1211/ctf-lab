"""启动实验的离线安全边界；不在测试中启动 QEMU。"""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab_windows_smoke as smoke


class SmokeTests(unittest.TestCase):
    def test_default_never_starts_or_copies(self):
        with mock.patch.object(smoke.subprocess, 'Popen', side_effect=AssertionError), mock.patch.object(smoke, 'copy_disk', side_effect=AssertionError), redirect_stdout(io.StringIO()):
            self.assertEqual(smoke.main([]), 0)

    def test_wrong_platform_refuses_start(self):
        with mock.patch.object(smoke.os, 'name', 'posix'), mock.patch.object(smoke.subprocess, 'Popen', side_effect=AssertionError), redirect_stdout(io.StringIO()):
            self.assertEqual(smoke.main(['--start']), 1)

    def test_fixed_offline_command_and_no_fallback(self):
        cmd = smoke.command(Path('qemu.exe'), Path('copy,disk.qcow2'))
        self.assertEqual(cmd[cmd.index('-accel')+1], 'whpx')
        self.assertEqual(cmd[cmd.index('-nic')+1], 'none')
        self.assertEqual(cmd[cmd.index('-monitor')+1], 'stdio')
        self.assertIn('-nodefaults', cmd)
        self.assertNotIn('-netdev', cmd)
        self.assertNotIn('-qmp', cmd)
        self.assertNotIn('tcg', ' '.join(cmd))
        self.assertIn('file=copy,,disk.qcow2,format=qcow2,if=ide', cmd)

    def test_copy_is_independent_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)/'source'; target = Path(temp)/'copy'
            source.write_bytes(b'fixture')
            with mock.patch.object(smoke, 'BASE_SHA', hashlib.sha256(b'fixture').hexdigest()):
                smoke.copy_disk(source, target)
                target.write_bytes(b'changed')
                self.assertEqual(source.read_bytes(), b'fixture')
                with self.assertRaises(FileExistsError): smoke.copy_disk(source, target)
                self.assertEqual(target.read_bytes(), b'changed')

    def test_bad_copy_hash_preserves_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)/'source'; target = Path(temp)/'copy'
            source.write_bytes(b'wrong')
            with self.assertRaises(ValueError): smoke.copy_disk(source, target)
            self.assertEqual(target.read_bytes(), b'wrong')
            self.assertEqual(source.read_bytes(), b'wrong')
