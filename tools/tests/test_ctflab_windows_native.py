"""Windows 原生边界；非 Windows 只验证结构和身份比较，不伪称原生执行。"""
import ctypes
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ctflab_windows_native import _query_hypervisor, hypervisor_capability, Win32, NativeError, ProcessIdentity, compare_identity, FileTime, Overlapped, state_lock


class NativeBoundaryTests(unittest.TestCase):
    def test_abi_layout(self):
        self.assertEqual(ctypes.sizeof(FileTime), 8)
        self.assertEqual(ctypes.sizeof(Overlapped), 32 if ctypes.sizeof(ctypes.c_void_p)==8 else 20)

    def test_pid_reuse_image_change_and_unknown(self):
        original=ProcessIdentity(1,100,'C:\\QEMU\\qemu.exe','running')
        self.assertEqual(compare_identity(original,ProcessIdentity(1,101,original.image_path,'running')),'mismatch')
        self.assertEqual(compare_identity(original,ProcessIdentity(1,100,'C:\\other.exe','running')),'mismatch')
        self.assertEqual(compare_identity(original,None),'unknown')
        self.assertEqual(compare_identity(original,ProcessIdentity(1,100,original.image_path,'exited')),'exited')
        self.assertEqual(compare_identity(original,ProcessIdentity(1,100,original.image_path.upper(),'running')),'running')

    @unittest.skipIf(os.name=='nt','此项检查非 Windows 拒绝')
    def test_wrong_host_refused(self):
        with self.assertRaises(NativeError):Win32()

    @unittest.skipUnless(os.name=='nt','待用户 Windows 原生验证')
    def test_observe_self_and_repeat(self):
        native=Win32();first=native.observe(os.getpid());second=native.observe(os.getpid())
        self.assertEqual(compare_identity(first,second),'running')
        self.assertTrue(Path(first.image_path).is_file())

    @unittest.skipUnless(os.name=='nt','待用户 Windows 原生验证')
    def test_lock_second_open_and_release(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'gate';file.write_bytes(b'0')
            with state_lock(file):
                with self.assertRaises(NativeError) as error:
                    with state_lock(file):pass
                self.assertEqual(error.exception.code,'resource-busy')
            with state_lock(file):pass


class HypervisorTests(unittest.TestCase):
    def query(self, present=1, result=0, size=4):
        def call(code, buffer, capacity, written):
            self.assertEqual(code, 0)
            self.assertEqual(capacity, 8)
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_int32)).contents.value = present
            ctypes.cast(written, ctypes.POINTER(ctypes.c_uint32)).contents.value = size
            return result
        return call

    def test_present_and_absent_are_distinct(self):
        self.assertEqual(_query_hypervisor(self.query())['hypervisor_present'], True)
        self.assertTrue(_query_hypervisor(self.query(size=8))['hypervisor_present'])
        result = _query_hypervisor(self.query(present=0))
        self.assertEqual(result, {'status':'not-present','hypervisor_present':False})

    def test_failed_or_wrong_size_is_unknown(self):
        for query in (self.query(result=-1), self.query(size=0), self.query(size=3), self.query(size=16)):
            self.assertEqual(_query_hypervisor(query), {'status':'query-failed','hypervisor_present':None})

    @unittest.skipIf(os.name=='nt','非 Windows 边界')
    def test_wrong_host_does_not_load_dll(self):
        self.assertEqual(hypervisor_capability()['status'], 'unsupported-platform')
