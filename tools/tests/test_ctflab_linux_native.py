"""Linux进程/KVM边界；原生项只在普通用户Linux运行，不把Mac跳过写成通过。"""
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ctflab_linux_native as native
from ctflab_windows_native import NativeError


class ParserTests(unittest.TestCase):
    def test_process_name_with_spaces_and_parentheses(self):
        raw='42 (fixture ) process (name)) S '+' '.join(['0']*18+['1234']+['0']*10)
        self.assertEqual(native.parse_stat(raw),('S',1234))
    def test_short_or_invalid_stat_rejected(self):
        for raw in ('invalid','1 (fixture) S 1','1 (fixture) ? '+' '.join(['0']*30)):
            with self.assertRaises(NativeError):native.parse_stat(raw)
    def test_non_linux_never_opens_process_or_kvm(self):
        with patch.object(native.platform,'system',return_value='Darwin'):
            self.assertFalse(native.capability()['hypervisor_present'])
            with self.assertRaises(NativeError):native.observe(1)


@unittest.skipUnless(sys.platform=='linux' and os.geteuid()!=0,'普通用户Linux原生项待执行')
class LinuxTests(unittest.TestCase):
    def test_pidfd_tracks_owned_short_lived_child(self):
        if not hasattr(os,'pidfd_open'):self.skipTest('宿主无pidfd_open')
        p=subprocess.Popen([sys.executable,'-I','-c','import time;time.sleep(.3);raise SystemExit(7)'])
        try:
            identity=native.observe(p.pid)
            observer=native.LinuxObserver()
            with observer.retained(identity) as fd:
                self.assertIsNone(observer.wait_exit(fd,0))
                result=observer.wait_exit(fd,3000)
                self.assertEqual(result['state'],'exited')
                self.assertIsNone(result['returncode'])
                self.assertFalse(result['exit_code_known'])
            self.assertEqual(p.wait(timeout=3),7)
        finally:
            # 只等待自有短寿命测试进程，不操作VM或任意外部PID。
            p.wait(timeout=4)

    def test_pid_reuse_mismatch_refuses_retained_descriptor(self):
        if not hasattr(os,'pidfd_open'):self.skipTest('宿主无pidfd_open')
        identity=native.observe(os.getpid())
        with self.assertRaises(NativeError):
            with native.LinuxObserver().retained(replace(identity,creation_ticks=identity.creation_ticks+1)):self.fail('应拒绝')


if __name__=='__main__':unittest.main()
