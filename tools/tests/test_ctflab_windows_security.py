"""Windows 私有存储策略负测；原生执行明确按平台条件登记。"""
import copy
import ctypes
import os
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_windows_security import WindowsSecurity, validate_acl, validate_local_path, SecurityAttributes
from ctflab_windows_native import NativeError

USER = 'S-1-5-21-1-2-3-1001'


def ace(sid=USER, mask=0x1f01ff, flags=0, kind=0):
    return {'sid':sid,'mask':mask,'flags':flags,'kind':kind}


class AclPolicyTests(unittest.TestCase):
    def test_private_root_and_inherited_file(self):
        validate_acl(USER,True,[ace(),ace('S-1-5-18')],USER,root=True)
        validate_acl(USER,False,[ace(flags=0x10)],USER,root=False)

    def test_broad_principals_owner_and_null_acl_refused(self):
        for owner, entries in [(USER,[]),('S-1-5-18',[ace()]),(USER,[ace(),ace('S-1-1-0')]),
                               (USER,[ace(),ace('S-1-5-32-545')]),(USER,[ace(),ace('S-1-5-32-544')])]:
            with self.assertRaises(NativeError):validate_acl(owner,True,entries,USER,root=True)

    def test_unprotected_root_insufficient_and_inherit_only_refused(self):
        for protected, entries in [(False,[ace()]),(True,[ace(mask=1)]),(True,[ace(flags=8)]),
                                    (True,[ace(kind=1)]),(True,[ace(kind=5)])]:
            with self.assertRaises(NativeError):validate_acl(USER,protected,entries,USER,root=True)

    def test_local_path_rejects_network_device_stream_and_aliases(self):
        validate_local_path(r'C:\Users\student\CTFLab')
        for value in (r'\\server\share\state', r'\\?\C:\state', r'C:\state:stream',
                      r'C:\parent\..\state', r'C:\state.', r'C:\CON', 'relative'):
            with self.assertRaises(NativeError):validate_local_path(value)

    def test_abi_layout(self):
        self.assertEqual(ctypes.sizeof(SecurityAttributes),24 if ctypes.sizeof(ctypes.c_void_p)==8 else 12)

    @unittest.skipIf(os.name=='nt','非 Windows 边界')
    def test_wrong_platform_fails_closed(self):
        with self.assertRaises(NativeError):WindowsSecurity()


class StorageConnectionTests(unittest.TestCase):
    def check_closed(self, fail_at=None):
        from ctflab_local_service import LocalService
        connections = []

        class TrackedConnection(sqlite3.Connection):
            def executescript(self, script):
                if len(connections) == fail_at:
                    raise sqlite3.OperationalError('初始化失败夹具')
                return super().executescript(script)

        connect = sqlite3.connect

        def tracked(*args, **kwargs):
            db = connect(*args, **kwargs, factory=TrackedConnection)
            connections.append(db)  # 持有强引用，禁止依赖垃圾回收释放句柄。
            return db

        with tempfile.TemporaryDirectory() as temp:
            try:
                with mock.patch('ctflab_local_service.sqlite3.connect', side_effect=tracked):
                    if fail_at is None:
                        LocalService.create(Path(temp).resolve() / 'contract')
                    else:
                        with self.assertRaisesRegex(sqlite3.OperationalError, '初始化失败夹具'):
                            LocalService.create(Path(temp).resolve() / 'contract')
                self.assertEqual(len(connections), 3 if fail_at is None else fail_at)
                for db in connections:
                    with self.assertRaises(sqlite3.ProgrammingError):
                        db.execute('SELECT 1')
            finally:
                for db in connections:
                    db.close()

    def test_initialization_closes_both_databases(self):
        self.check_closed()

    def test_initialization_failure_closes_connections(self):
        for fail_at in (1, 2):
            with self.subTest(fail_at=fail_at):
                self.check_closed(fail_at)


@unittest.skipUnless(os.name=='nt','待用户 Windows ACL 实机验证')
class NativeStorageTests(unittest.TestCase):
    def test_private_root_file_and_no_overwrite(self):
        security=WindowsSecurity()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'private'
            security.create_directory(root)
            self.assertEqual(security.verify(root,root=True),security.current_user())
            child=root/'gate';child.write_bytes(b'fixture')
            self.assertEqual(security.verify(child),security.current_user())
            with self.assertRaises(FileExistsError):security.create_directory(root)
            self.assertEqual(child.read_bytes(),b'fixture')

    def test_contract_and_adapter_share_native_identity(self):
        from ctflab_local_service import LocalService
        from ctflab_local_adapter import LocalAdapter
        from ctflab_windows_probe import FixtureBackend, request
        from ctflab_contract import canonical
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'contract'
            LocalService.create(root)
            instance=str(uuid.uuid4())
            adapter=LocalAdapter(root,backend=FixtureBackend())
            result=adapter.dispatch(canonical(request(instance,'prepare',parameters={'course_id':'fixture','baseline_id':'base'})))
            self.assertEqual(result['result'],'completed')
            reopened=LocalAdapter(root)
            status=reopened.dispatch(canonical(request(instance,'status')))
            self.assertEqual(status['state'],'prepared')
            self.assertEqual(status['generation'],1)

    def test_world_accessible_directory_is_refused(self):
        security=WindowsSecurity()
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'insecure-fixture'
            descriptor=ctypes.c_void_p()
            self.assertTrue(security.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                'D:P(A;OICI;FA;;;WD)',1,ctypes.byref(descriptor),None))
            try:
                attributes=SecurityAttributes(ctypes.sizeof(SecurityAttributes),descriptor,False)
                self.assertTrue(security.kernel.CreateDirectoryW(str(path),ctypes.byref(attributes)))
            finally:
                security.kernel.LocalFree(descriptor)
            with self.assertRaises(NativeError):security.verify(path,root=True)
