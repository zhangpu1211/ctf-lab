"""Darwin身份/退出内核边界；只观察自身与专用普通Python子进程，不启动VM。"""
import ctypes
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ctflab_darwin_native as native
from ctflab_windows_native import NativeError,ProcessIdentity


class DarwinTests(unittest.TestCase):
    def test_sdk_structure_has_fixed_width(self):
        self.assertEqual(ctypes.sizeof(native.BSDInfo),136)
        self.assertEqual(native.BSDInfo.start_sec.offset,120)

    def test_unsupported_platform_or_elevated_identity_fails_before_kernel_access(self):
        with patch.object(native.sys,'platform','linux'):
            with self.assertRaises(NativeError):native.permission()
        with patch.object(native.sys,'platform','darwin'),patch.object(native.os,'geteuid',return_value=0,create=True):
            with self.assertRaises(NativeError):native.permission()

    @unittest.skipUnless(sys.platform=='darwin','需要Darwin自身内核')
    def test_own_process_identity_is_stable_and_bound_to_boot(self):
        first=native.observe(os.getpid());second=native.observe(os.getpid())
        self.assertEqual(first,second);self.assertEqual(first.state,'running')
        self.assertTrue(Path(first.image_path).is_absolute());self.assertGreater(first.creation_ticks,2**64)

    @unittest.skipUnless(sys.platform=='darwin','需要Darwin自身kqueue')
    def test_dedicated_child_exit_uses_retained_kqueue_without_kill(self):
        child=subprocess.Popen([sys.executable,'-I','-B','-c',"import sys;sys.stdout.write('ready');sys.stdout.flush();sys.stdin.buffer.read(1)"],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        try:
            self.assertEqual(child.stdout.read(5),b'ready')
            expected=native.observe(child.pid);observer=native.DarwinObserver()
            with observer.retained(expected) as handle:
                child.stdin.close()
                evidence=None
                for _ in range(5):
                    evidence=observer.wait_exit(handle)
                    if evidence:break
                self.assertEqual(evidence,{'state':'exited','returncode':None,'source':'retained-darwin-kqueue','exit_code_known':False})
            self.assertEqual(child.wait(timeout=5),0)
        finally:
            child.stdout.close()
            if not child.stdin.closed:child.stdin.close()
            child.wait(timeout=5)

    def test_reused_pid_never_registers_exit_watch(self):
        expected=ProcessIdentity(123,100,'/own/process','running')
        with patch.object(native,'permission'),patch.object(native,'observe',return_value=replace(expected,creation_ticks=101)):
            with self.assertRaises(NativeError):
                with native.DarwinObserver().retained(expected):self.fail('不得接管复用PID')

    def test_case_changed_executable_is_not_accepted(self):
        expected=ProcessIdentity(123,100,'/own/Process','running')
        with patch.object(native,'permission'),patch.object(native,'observe',return_value=replace(expected,image_path='/own/process')):
            with self.assertRaises(NativeError):
                with native.DarwinObserver().retained(expected):self.fail('不得忽略路径大小写')
