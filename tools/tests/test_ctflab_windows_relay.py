"""Windows原生API桩与生产桥接结合；本机不是Windows，不冒称原生验收。"""
import ctypes
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import os
import signal
import sys
import unittest
import uuid
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ctflab_desktop_bridge as bridge
from ctflab_windows_native import Win32,NativeError,ProcessIdentity,ProcessEntry32,HANDLE
import test_ctflab_external_disconnect as disconnect_fixture


class SnapshotDLL:
    def __init__(self,pids,*,first_error=18,next_error=18,invalid=False):
        self.pids=list(pids);self.first_error=first_error;self.next_error=next_error
        self.invalid=invalid;self.closed=[];self.index=0;self.error=0
    def CreateToolhelp32Snapshot(self,flags,pid):
        assert flags==2 and pid==0
        return HANDLE(-1).value if self.invalid else 77
    def fill(self,ptr):
        entry=ctypes.cast(ptr,ctypes.POINTER(ProcessEntry32)).contents
        assert entry.size==ctypes.sizeof(ProcessEntry32)
        entry.pid=self.pids[self.index]
        return 1
    def Process32FirstW(self,handle,ptr):
        if not self.pids:self.error=self.first_error;return 0
        return self.fill(ptr)
    def Process32NextW(self,handle,ptr):
        self.index+=1
        if self.index>=len(self.pids):self.error=self.next_error;return 0
        return self.fill(ptr)
    def GetLastError(self):return self.error
    def CloseHandle(self,handle):self.closed.append(handle)


class SnapshotTests(unittest.TestCase):
    def native(self,*args,**kwargs):
        native=Win32.__new__(Win32);native.dll=SnapshotDLL(*args,**kwargs);return native
    def test_fixed_windows_abi(self):
        self.assertEqual(ctypes.sizeof(ProcessEntry32),568 if ctypes.sizeof(ctypes.c_void_p)==8 else 556)
        self.assertEqual(ProcessEntry32.exe.offset,44 if ctypes.sizeof(ctypes.c_void_p)==8 else 36)
    def test_found_absent_and_empty_close_snapshot(self):
        for pids,expected in [([4,42],True),([4,7],False),([],False)]:
            native=self.native(pids)
            self.assertIs(native.pid_exists(42),expected)
            self.assertEqual(native.dll.closed,[77])
    def test_failed_enumeration_is_not_absence(self):
        for native in (self.native([],first_error=5),self.native([4],next_error=5)):
            with self.assertRaises(NativeError):native.pid_exists(42)
            self.assertEqual(native.dll.closed,[77])
    def test_invalid_snapshot_does_not_close_invalid_handle(self):
        native=self.native([],invalid=True)
        with self.assertRaises(NativeError):native.pid_exists(42)
        self.assertEqual(native.dll.closed,[])
    def test_bad_pid_does_not_open_snapshot(self):
        native=self.native([])
        for pid in (True,0,1,-1,2**32):
            with self.assertRaises(NativeError):native.pid_exists(pid)
        self.assertEqual(native.dll.closed,[])


class FakeNative:
    def __init__(self,identity=None):
        self.identity=identity or ProcessIdentity(42,100,r'C:\CTFLab\python.exe','running')
        self.exists=True;self.query_error=False;self.snapshot_error=False
        self.events=[];self.opened=False;self.on_wait=None;self.exit_code=0;self.retention_error=False
    def observe_handle(self,handle,pid):
        self.events.append(('capture',handle,pid));return self.identity
    def observe(self,pid):
        self.events.append(('observe',pid))
        if self.query_error:raise NativeError('identity-unknown')
        return self.identity
    def pid_exists(self,pid):
        self.events.append(('snapshot',pid))
        if self.snapshot_error:raise NativeError('process-list-unknown')
        return self.exists
    @contextmanager
    def retained(self,expected):
        self.events.append(('retain',expected))
        if self.retention_error:raise NativeError('identity-unknown')
        self.opened=True
        try:yield 77
        finally:self.opened=False;self.events.append(('close',77))
    def wait_exit(self,handle,timeout_ms):
        assert self.opened and handle==77
        self.events.append(('wait',timeout_ms))
        if timeout_ms==0:return None
        if self.on_wait:self.on_wait()
        return self.exit_code


class WindowsIdentityTests(unittest.TestCase):
    def session(self):
        return {'pid':42,'session_uuid':str(uuid.uuid4()),'process_identity':asdict(FakeNative().identity)}
    def test_capture_uses_popen_original_handle(self):
        native=FakeNative()
        with patch('ctflab_windows_native.Win32',return_value=native):
            raw=bridge._capture_windows_relay(SimpleNamespace(pid=42,_handle=123))
        self.assertEqual(raw,asdict(native.identity));self.assertEqual(native.events,[('capture',123,42)])
        with self.assertRaises(NativeError):bridge._capture_windows_relay(SimpleNamespace(pid=42))
    def test_capture_rejects_malformed_kernel_identity(self):
        for value in (ProcessIdentity(42,0,r'C:\python.exe','running'),
                      ProcessIdentity(42,True,r'C:\python.exe','running'),
                      ProcessIdentity(42,2**64,r'C:\python.exe','running'),
                      ProcessIdentity(42,100,'relative.exe','running')):
            with self.subTest(value=value),patch('ctflab_windows_native.Win32',return_value=FakeNative(value)):
                with self.assertRaises(NativeError):bridge._capture_windows_relay(SimpleNamespace(pid=42,_handle=123))

    def test_matching_identity_reuse_and_image_change(self):
        session=self.session();native=FakeNative()
        self.assertIs(bridge._observe_windows_relay(session,native),True)
        native.identity=ProcessIdentity(42,101,native.identity.image_path,'running')
        self.assertIs(bridge._observe_windows_relay(session,native),False)
        native.identity=ProcessIdentity(42,100,r'C:\other.exe','running')
        self.assertIs(bridge._observe_windows_relay(session,native),False)
    def test_corrupt_filetime_cannot_prove_live_pid_is_gone(self):
        session=self.session();session['process_identity']['creation_ticks']=2**64
        native=FakeNative()
        self.assertIsNone(bridge._observe_windows_relay(session,native))
        self.assertFalse(any(item[0]=='observe' for item in native.events))
        native.exists=False
        self.assertIs(bridge._observe_windows_relay(session,native),False)

    def test_query_failure_requires_successful_absence_snapshot(self):
        session=self.session();native=FakeNative();native.query_error=True
        self.assertIsNone(bridge._observe_windows_relay(session,native))
        native.exists=False;self.assertIs(bridge._observe_windows_relay(session,native),False)
        native.snapshot_error=True;self.assertIsNone(bridge._observe_windows_relay(session,native))
    def test_incomplete_legacy_identity_only_recovers_when_pid_absent(self):
        session=self.session();session.pop('process_identity');native=FakeNative()
        self.assertIsNone(bridge._observe_windows_relay(session,native))
        self.assertFalse(any(item[0]=='observe' for item in native.events))
        native.exists=False;self.assertIs(bridge._observe_windows_relay(session,native),False)
    def test_worker_identity_barrier_rejects_wrong_self_before_network(self):
        session=self.session();attach=SimpleNamespace(load=lambda:{'session':session})
        native=FakeNative()
        with patch.object(bridge.os,'getpid',return_value=99),patch('ctflab_windows_native.Win32',return_value=native):
            with self.assertRaises(ValueError):bridge._wait_windows_relay_identity(attach,session['session_uuid'],timeout=.05)
        session.pop('process_identity')
        with self.assertRaises(ValueError):bridge._wait_windows_relay_identity(attach,session['session_uuid'],timeout=.02)
    def test_worker_identity_barrier_accepts_exact_kernel_identity(self):
        session=self.session();native=FakeNative()
        with patch.object(bridge.os,'getpid',return_value=42),patch('ctflab_windows_native.Win32',return_value=native):
            bridge._wait_windows_relay_identity(SimpleNamespace(load=lambda:{'session':session}),session['session_uuid'])


class WindowsDisconnectTests(unittest.TestCase):
    def setUp(self):
        disconnect_fixture.DisconnectLockTests.setUp(self)
        self.native=FakeNative()
        binding=self.attach.load();binding['session'].update(pid=42,state='connected',process_identity=asdict(self.native.identity))
        self.attach.save(binding)
    def receipt(self):
        self.assertTrue(self.native.opened)
        with self.store.locked():
            fresh=self.attach.load();session=fresh['session']
            self.assertTrue(session['disconnect_requested'])
            self.assertTrue(bridge._valid_disconnect_request(session))
            session.update(state='disconnected',report={'transport_closed':True,'reason':'completed','marker':'latest'})
            self.attach.save(fresh)
    def dispatch(self):
        with patch.object(bridge.platform,'system',return_value='Windows'),patch('ctflab_windows_native.Win32',return_value=self.native),patch.object(bridge.os,'kill') as kill,patch('ctflab_scenario_runtime.process_command') as command:
            result=bridge.dispatch(self.root,{'action':'external-attach-disconnect'})
        kill.assert_not_called();command.assert_not_called();return result
    def test_cooperative_disconnect_waits_same_handle_and_merges_receipt(self):
        self.native.on_wait=self.receipt
        result=self.dispatch()
        self.assertEqual(result['state'],'relay-detached')
        self.assertEqual(self.attach.load()['session']['report']['marker'],'latest')
        self.assertEqual([x for x in self.native.events if x[0]=='wait'],[('wait',0),('wait',2000)])
        self.assertEqual(self.native.events[-1],('close',77));self.assertFalse(self.native.opened)
    def test_timeout_error_exit_and_missing_receipt_remain_unknown(self):
        for code,receipt,reason in [(None,False,'termination-unconfirmed'),(1,True,'relay-exit-error'),(259,True,'relay-exit-error'),(0,False,'final-receipt-missing')]:
            with self.subTest(code=code,receipt=receipt):
                self.native.exit_code=code;self.native.on_wait=self.receipt if receipt else None
                fresh=self.attach.load();fresh['session']['state']='connected';fresh['session'].pop('report',None);self.attach.save(fresh)
                result=self.dispatch()
                self.assertEqual(result['state'],'relay-unknown')
                self.assertEqual(self.attach.load()['session']['disconnect_failure'],reason)
                self.assertTrue(self.attach.load()['session']['disconnect_requested'])
                self.assertFalse(self.native.opened)
    def test_access_denied_cannot_be_treated_as_process_exit(self):
        self.native.retention_error=True;self.native.query_error=True
        self.assertEqual(self.dispatch()['state'],'relay-unknown')
        self.assertFalse(self.native.opened)
        self.assertEqual(self.attach.load()['session']['disconnect_failure'],'process-observation-unknown')


    def prepare_connect(self):
        fresh=self.attach.load();fresh['session']={'state':'idle'};self.attach.save(fresh)
        # 设计§4.3持久批准：连接路径统一核验账本；本夹具登记摘要绑定材料清单。
        from ctflab_external_attach import approve_assistant
        ledger=self.parent/'approvals'
        registration=self.attach.load()['registration']
        approve_assistant(registration,{'schema':1,'kind':'ctflab-kali-attach-materials',
                                        'files':{'ctflab-kali-attach':registration['assistant_sha256']}},ledger)
        env=patch.dict('os.environ',{'CTFLAB_EXTERNAL_ATTACH_APPROVALS':str(ledger)})
        env.start();self.addCleanup(env.stop)
        bridge.dispatch(self.root,{'action':'external-attach-materials','destination':str(self.parent/'materials')})
        directory=self.parent/'ssh-input';directory.mkdir()
        identity=directory/'key';identity.write_bytes(b'fixture');identity.chmod(0o600)
        known=directory/'known';known.write_bytes(b'');known.chmod(0o600)
        binary=directory/'ssh';binary.write_bytes(b'fixture');binary.chmod(0o755)
        import hashlib,json
        config={'schema':1,'host':'127.0.0.1','port':22,'user':'ctflab_attach',
                'ssh':str(binary),'identity':str(identity),'known_hosts':str(known),
                'known_hosts_sha256':hashlib.sha256(b'').hexdigest(),
                'server_uuid':self.attach.load()['registration']['node_uuid']}
        path=directory/'config.json';path.write_text(json.dumps(config));path.chmod(0o600)
        return str(path)

    def test_connect_records_identity_from_its_own_popen_handle(self):
        config=self.prepare_connect();process=SimpleNamespace(pid=42,_handle=123)
        with patch.object(bridge.platform,'system',return_value='Windows'),patch('ctflab_windows_native.Win32',return_value=self.native),patch.object(bridge,'launch',return_value=process):
            result=bridge.dispatch(self.root,{'action':'external-attach-connect','ssh_config':config})
        self.assertEqual(result['state'],'relay-requested')
        self.assertEqual(self.attach.load()['session']['process_identity'],asdict(self.native.identity))
        self.assertIn(('capture',123,42),self.native.events)

    def test_failed_capture_reaps_only_own_popen_and_records_not_started(self):
        config=self.prepare_connect()
        process=SimpleNamespace(pid=42,_handle=123,returncode=1,terminate=Mock(),wait=Mock(return_value=1))
        with patch.object(bridge.platform,'system',return_value='Windows'),patch.object(bridge,'_capture_windows_relay',side_effect=NativeError('identity-unknown')),patch.object(bridge,'launch',return_value=process),patch.object(bridge.os,'kill') as kill:
            result=bridge.dispatch(self.root,{'action':'external-attach-connect','ssh_config':config})
        process.terminate.assert_called_once();process.wait.assert_called_once_with(timeout=2);kill.assert_not_called()
        self.assertEqual(result['state'],'relay-unknown')
        session=self.attach.load()['session']
        self.assertTrue(session['report']['transport_closed'])
        with patch('ctflab_windows_native.Win32') as factory:
            self.assertIs(bridge._observe_windows_relay(session),False)
        factory.assert_not_called()

    def test_native_identity_change_during_wait_preserves_new_record(self):
        def change():
            with self.store.locked():
                fresh=self.attach.load();fresh['session']['process_identity']['creation_ticks']=999
                self.attach.save(fresh)
        self.native.on_wait=change
        with self.assertRaises(ValueError):self.dispatch()
        self.assertEqual(self.attach.load()['session']['process_identity']['creation_ticks'],999)
        self.assertFalse(self.native.opened)


class WindowsWorkerGateTests(unittest.TestCase):
    def setUp(self):
        disconnect_fixture.DisconnectLockTests.setUp(self)
        self.native=FakeNative(ProcessIdentity(os.getpid(),100,r'C:\CTFLab\python.exe','running'))
        binding=self.attach.load()
        binding['session'].update(pid=os.getpid(),state='connecting',process_identity=asdict(self.native.identity))
        self.attach.save(binding)
    def invoke(self,relay):
        with patch.object(bridge.platform,'system',return_value='Windows'),patch('ctflab_windows_native.Win32',return_value=self.native),patch('signal.signal'),patch('ctflab_external_attach.run_relay',relay),patch.object(bridge.os,'kill') as kill:
            bridge.external_relay_worker(self.root,self.sid)
        kill.assert_not_called()
    def test_pre_start_cooperative_cancel_never_opens_transport(self):
        binding=self.attach.load();binding['session'].update(disconnect_requested=True,disconnect_request_id=str(uuid.uuid4()));self.attach.save(binding)
        relay=Mock()
        self.invoke(relay);relay.assert_not_called()
        self.assertEqual(self.attach.load()['session']['state'],'disconnected')
        self.assertTrue(self.attach.load()['session']['report']['not_started'])
    def test_wrong_kernel_identity_rejects_transport_and_keeps_failure(self):
        binding=self.attach.load();binding['session']['process_identity']['creation_ticks']=999;self.attach.save(binding)
        relay=Mock()
        with self.assertRaises(ValueError):self.invoke(relay)
        relay.assert_not_called()
        self.assertEqual(self.attach.load()['session']['state'],'unknown')
        self.assertTrue(self.attach.load()['session']['report']['transport_closed'])
    def test_valid_identity_allows_normal_worker_contract(self):
        relay=Mock(return_value={'reason':'completed','marker':'valid'})
        self.invoke(relay);relay.assert_called_once()
        self.assertEqual(self.attach.load()['session']['report']['marker'],'valid')
        self.assertTrue(self.attach.load()['session']['report']['transport_closed'])


@unittest.skipUnless(os.name=='nt','等待Windows原生Kernel32验收，不以API桩代替')
class NativeWindowsRelayTests(unittest.TestCase):
    def test_snapshot_contains_self(self):
        self.assertTrue(Win32().pid_exists(os.getpid()))
    def test_retained_child_handle_observes_natural_exit(self):
        import subprocess
        child=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(.5)'])
        def cleanup():
            if child.poll() is None:
                child.terminate();child.wait(3)
        self.addCleanup(cleanup)
        native=Win32()
        expected=native.observe_handle(int(child._handle),child.pid)
        with native.retained(expected) as handle:
            self.assertEqual(native.wait_exit(handle,3000),0)
        child.wait(3)
        self.assertEqual(child.returncode,0)


class WindowsAttachStorageTests(unittest.TestCase):
    def setUp(self):
        disconnect_fixture.DisconnectLockTests.setUp(self)
    def windows_os(self):
        import ctflab_external_attach as external
        proxy=SimpleNamespace(**vars(external.os));proxy.name='nt'
        proxy.getuid=Mock(side_effect=AssertionError('Windows不得读取POSIX uid'))
        return external,proxy
    def test_existing_private_directory_and_file_use_acl_verification(self):
        external,proxy=self.windows_os();calls=[]
        def security(path,**kwargs):calls.append((Path(path),kwargs))
        with patch.object(external,'os',proxy),patch('ctflab_local_service._windows_storage',side_effect=security):
            value=self.attach.load();self.attach.save(value)
        proxy.getuid.assert_not_called()
        self.assertIn((self.attach.path.parent,{'root':True}),calls)
        self.assertIn((self.attach.path,{}),calls)
        self.assertIn((self.attach.path.with_suffix('.tmp'),{}),calls)
    def test_acl_rejection_preserves_existing_record(self):
        external,proxy=self.windows_os();before=self.attach.path.read_bytes()
        with patch.object(external,'os',proxy),patch('ctflab_local_service._windows_storage',side_effect=ValueError('ACL rejected')):
            with self.assertRaises(ValueError):self.attach.save({'schema':1,'instance_uuid':self.instance})
        self.assertEqual(self.attach.path.read_bytes(),before)
    def test_existing_temporary_hardlink_is_not_truncated(self):
        target=self.parent/'protected';target.write_bytes(b'preserve')
        temporary=self.attach.path.with_suffix('.tmp');os.link(target,temporary)
        with self.assertRaises(ValueError):self.attach.save(self.attach.load())
        self.assertEqual(target.read_bytes(),b'preserve')


if __name__=='__main__':unittest.main()
