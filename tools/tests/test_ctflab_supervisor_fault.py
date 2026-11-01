"""故障请求的身份边界；合成进程不代表真实 Windows/QEMU 故障恢复。"""
from dataclasses import asdict, replace
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ctflab_windows_native import ProcessIdentity
from ctflab_windows_recovery import record
from ctflab_qemu_driver import read
import ctflab_supervisor_fault as fault


class FaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.values = {pid: ProcessIdentity(pid, pid*10, 'python-fixture', 'running')
                       for pid in (os.getpid(), os.getpid()+1, os.getpid()+2)}
        self.worker, self.qemu, self.observer = self.values.values()
        record(self.root/'worker.json', asdict(self.worker))
        record(self.root/'binding.json', {'identity': asdict(self.qemu)})
        record(self.root/'observer-ready.json', {'identity': asdict(self.qemu), 'observer': asdict(self.observer)})
        self.observe = lambda pid: self.values[pid]

    def request(self):
        return fault.request(self.root, read=read, record=record, observe=self.observe)

    def test_request_never_terminates_and_duplicate_rejected(self):
        self.assertEqual(self.request()['state'], 'fault-requested')
        with self.assertRaises(ValueError): self.request()

    def test_pid_reused_request_refused(self):
        self.values[self.qemu.pid] = replace(self.qemu, creation_ticks=9)
        with self.assertRaises(ValueError): self.request()
        self.assertFalse((self.root/'supervisor-fault.intent.json').exists())

    def test_observer_missing_request_refused(self):
        (self.root/'observer-ready.json').unlink()
        with self.assertRaises(OSError): self.request()

    def test_worker_exits_only_after_persisted_matching_request(self):
        self.request()
        class Process:
            pid = self.qemu.pid
            def poll(self): return None
        def exit_now(code):
            self.assertEqual(code, 73)
            self.assertTrue((self.root/'supervisor-fault.applied.json').exists())
            raise SystemExit(code)
        with self.assertRaises(SystemExit):
            fault.wait(Process(), self.root, read=read, record=record, observe=self.observe, exit_now=exit_now)

    def test_observer_dies_after_request_no_exit_or_retry(self):
        self.request()
        self.values[self.observer.pid] = replace(self.observer, state='exited')
        class Process:
            pid = self.qemu.pid
            calls = 0
            def poll(self):
                self.calls += 1
                return None if self.calls < 3 else 0
            def wait(self): return 0
        with patch.object(fault.time, 'sleep'), patch.object(fault.os, '_exit', side_effect=AssertionError):
            self.assertEqual(fault.wait(Process(), self.root, read=read, record=record, observe=self.observe,
                                        exit_now=lambda _: self.fail('不能退出')), 0)
        self.assertTrue((self.root/'supervisor-fault.rejected.json').exists())
        self.assertFalse((self.root/'supervisor-fault.applied.json').exists())

    def test_other_worker_cannot_consume_request(self):
        self.request()
        class Process:
            pid = self.qemu.pid
            calls = 0
            def poll(self):
                self.calls += 1
                return None if self.calls == 1 else 0
            def wait(self): return 0
        with patch.object(fault.os, 'getpid', return_value=self.observer.pid), patch.object(fault.time, 'sleep'):
            self.assertEqual(fault.wait(Process(), self.root, read=read, record=record, observe=self.observe,
                                        exit_now=lambda _: self.fail('不能退出')), 0)
        self.assertTrue((self.root/'supervisor-fault.rejected.json').exists())

    def test_no_request_preserves_owned_wait_returncode(self):
        class Process:
            def poll(self): return 7
            def wait(self): return 7
        self.assertEqual(fault.wait(Process(), self.root, read=read, record=record, observe=self.observe), 7)

    def test_request_retains_worker_before_writing_and_confirms_exit(self):
        owner=self
        class Native:
            @contextmanager
            def retained(self,identity):
                owner.assertEqual(identity,owner.worker)
                owner.assertFalse((owner.root/'supervisor-fault.intent.json').exists())
                yield 'held'
            def wait_exit(self,handle,timeout):
                owner.assertEqual(handle,'held');owner.assertEqual(timeout,10000)
                owner.assertTrue((owner.root/'supervisor-fault.intent.json').exists())
                return 73
        result=fault.request_and_wait(self.root,read=read,record=record,observe=self.observe,native=Native())
        self.assertEqual(result['state'],'supervisor-exited')
        self.assertEqual(read(self.root/'supervisor-fault.exit.json')['returncode'],73)

    def test_timeout_remains_unknown_without_forged_exit(self):
        class Native:
            @contextmanager
            def retained(self,identity):yield 'held'
            def wait_exit(self,handle,timeout):return None
        result=fault.request_and_wait(self.root,read=read,record=record,observe=self.observe,native=Native())
        self.assertEqual(result['state'],'unknown')
        self.assertFalse((self.root/'supervisor-fault.exit.json').exists())


@unittest.skipUnless(os.name=='nt','Windows监督器自行崩溃的原生用例待执行')
class NativeFaultTests(unittest.TestCase):
    def test_abrupt_supervisor_exit_preserves_child_and_observer(self):
        from ctflab_generation_store import private_directory
        from ctflab_windows_native import Win32
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'private';private_directory(root)
            tools=str(Path(__file__).resolve().parents[1])
            source='\n'.join([
                'import sys,os,time,subprocess',f'sys.path.insert(0,{tools!r})',
                'from pathlib import Path','from dataclasses import asdict',
                'from ctflab_windows_native import Win32',
                'from ctflab_windows_recovery import record',
                'from ctflab_qemu_driver import spawn_worker,read',
                'from ctflab_supervisor_fault import wait',f'root=Path({str(root)!r})',
                'native=Win32()',
                'record(root/"worker.json",asdict(native.observe(os.getpid())))',
                'p=subprocess.Popen([sys.executable,"-I","-c","import time;time.sleep(8);raise SystemExit(7)"],creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)',
                'record(root/"binding.json",{"identity":asdict(native.observe(p.pid))})',
                'spawn_worker("observe-exit",root)',
                'raise SystemExit(wait(p,root,read=read,record=record,observe=native.observe))',
            ])
            parent=subprocess.Popen([sys.executable,'-I','-c',source])
            try:
                deadline=time.monotonic()+6
                while not (root/'observer-ready.json').exists():
                    if time.monotonic()>deadline or parent.poll() is not None:self.fail('独立观测器未就绪')
                    time.sleep(.05)
                native=Win32();child=ProcessIdentity(**read(root/'binding.json')['identity'])
                with native.retained(child) as handle:
                    result=fault.request_and_wait(root,read=read,record=record,observe=native.observe,native=native)
                    self.assertEqual(result['returncode'],73)
                    self.assertEqual(parent.wait(timeout=2),73)
                    self.assertIsNone(native.wait_exit(handle,0),'监督器崩溃不能顺带结束子进程')
                    self.assertEqual(native.wait_exit(handle,12000),7)
                deadline=time.monotonic()+3
                while not (root/'observer-exit.json').exists() and time.monotonic()<deadline:time.sleep(.05)
                self.assertEqual(read(root/'observer-exit.json')['returncode'],7)
            finally:
                parent.wait(timeout=12)


if __name__ == '__main__': unittest.main()
