"""Windows 保留句柄实测：只创建短寿命 Python 子进程，不操作 VM。"""
import ctypes
from dataclasses import asdict, replace
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_windows_native import Win32, NativeError, ProcessIdentity, DWORD


class HandleTests(unittest.TestCase):
    def test_signaled_exit_259_is_not_running(self):
        class DLL:
            def WaitForSingleObject(self,h,t):return 0
            def GetExitCodeProcess(self,h,p):
                ctypes.cast(p,ctypes.POINTER(DWORD)).contents.value=259
                return True
        native=object.__new__(Win32);native.dll=DLL()
        self.assertEqual(native.wait_exit(123),259)

    def test_timeout_does_not_read_exit(self):
        class DLL:
            def WaitForSingleObject(self,h,t):return 258
            def GetExitCodeProcess(self,*args):raise AssertionError('尚未退出')
        native=object.__new__(Win32);native.dll=DLL()
        self.assertIsNone(native.wait_exit(123))

    def test_mismatch_closes_handle(self):
        class DLL:
            closed=[]
            def OpenProcess(self,*args):return 123
            def CloseHandle(self,h):self.closed.append(h)
        native=object.__new__(Win32);native.dll=DLL()
        identity=ProcessIdentity(1,2,'fixture','running')
        native.observe_handle=lambda h,p:replace(identity,creation_ticks=3)
        with self.assertRaises(NativeError):
            with native.retained(identity):self.fail('不应获得句柄')
        self.assertEqual(native.dll.closed,[123])


@unittest.skipUnless(os.name=='nt','Windows 原生内核验收待执行')
class NativeExitTests(unittest.TestCase):
    def test_independent_observer_survives_parent_exit(self):
        from ctflab_generation_store import private_directory
        from ctflab_windows_recovery import record
        from ctflab_qemu_driver import read
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'private';private_directory(root)
            tools=str(Path(__file__).resolve().parents[1])
            # 父进程自愿退出；子进程8秒后正常退出7，不强杀任何进程。
            source='\n'.join([
                'import sys, subprocess, time',
                f'sys.path.insert(0,{tools!r})',
                'from pathlib import Path',
                'from dataclasses import asdict',
                'from ctflab_windows_native import Win32',
                'from ctflab_windows_recovery import record',
                'from ctflab_qemu_driver import spawn_worker',
                f'root=Path({str(root)!r})',
                'p=subprocess.Popen([sys.executable,"-I","-c","import time;time.sleep(8);raise SystemExit(7)"],creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)',
                'record(root/"binding.json",{"identity":asdict(Win32().observe(p.pid))})',
                'spawn_worker("observe-exit", root)',
                'deadline=time.monotonic()+10',
                'while not (root/"observer-ready.json").exists() and time.monotonic()<deadline: time.sleep(.05)',
                'raise SystemExit(0 if (root/"observer-ready.json").exists() else 2)',
            ])
            parent=subprocess.Popen([sys.executable,'-I','-c',source])
            self.assertEqual(parent.wait(timeout=12),0)
            native=Win32()
            identity=ProcessIdentity(**read(root/'observer-ready.json')['observer'])
            # 观测器同样由已退出的父进程创建，不能靠测试主进程代养来冒充恢复。
            with native.retained(identity) as handle:
                self.assertIsNone(native.wait_exit(handle,0))
                self.assertEqual(native.wait_exit(handle,12000),0)
            value=read(root/'observer-exit.json')
            self.assertEqual(value['identity'],read(root/'binding.json')['identity'])
            self.assertEqual(value['returncode'],7)
            self.assertFalse(value['graceful_stop_verified'])


if __name__=='__main__':unittest.main()
