"""签名清单/固定入口/版本门与中断现场；只执行自有临时脚本，不启动桌面或VM。"""
import ctypes
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_windows_native import ProcessIdentity,NativeError
from ctflab_contract import ContractError,canonical
from ctflab_generation_store import digest
from ctflab_release_store import SIGNED_MANIFEST,release_manifest
from ctflab_release_launcher import ReleaseLauncher,WINTRUST_DATA,WINTRUST_FILE_INFO,GUID,verify_embedded_signature
from ctflab_release_update import UpdateCoordinator
import test_ctflab_release_store as fixtures


class FakeProcess:
    pid=123
    def __init__(self,wait=None):self.callback=wait
    def poll(self):return None
    def wait(self):return self.callback() if self.callback else 0
    def kill(self):raise AssertionError('启动器不得自动杀进程')
    terminate=kill


class LauncherTests(unittest.TestCase):
    setUp=fixtures.ReleaseTests.setUp
    envelope=fixtures.ReleaseTests.envelope
    stage=fixtures.ReleaseTests.stage

    def configured(self,target='linux-x64',*,wait=None):
        entry='ctflab-desktop.exe' if target=='windows-x64' else 'ctflab-desktop'
        (self.source/entry).write_bytes(b'fixture executable')
        self.payload.update(schema=2,launch={'platform':target,'entry':entry,'executables':[entry]})
        self.payload['files']={n:digest(self.source/n) for n in ('LICENSE',entry)}
        self.stage();self.store.activate('0.1.0');self.spawns=[];self.signatures=[]
        def spawn(argv,**kwargs):self.spawns.append((argv,kwargs));return FakeProcess(wait)
        def signature(path):self.signatures.append(path);return True
        self.launcher=ReleaseLauncher(self.store,self.keys,host=lambda:target,signature=signature,spawn=spawn)

    def pending(self,target='linux-x64'):
        def interrupt():raise KeyboardInterrupt()
        self.configured(target,wait=interrupt)
        entry=self.store.root/'versions/0.1.0'/self.payload['launch']['entry']
        class Observer:
            identity=ProcessIdentity(123,456,str(entry),'running')
            outcome=None
            unavailable=False
            calls=0
            def observe(inner,pid):
                if inner.unavailable:raise NativeError('identity-unknown')
                return inner.identity
            @contextmanager
            def retained(inner,expected):
                inner.calls+=1
                if expected.creation_ticks!=inner.identity.creation_ticks:raise NativeError('identity-mismatch')
                yield object()
            def wait_exit(inner,handle,timeout_ms):return inner.outcome
        self.observer=Observer();self.launcher.observer=lambda:self.observer
        with self.assertRaises(KeyboardInterrupt):self.launcher.run(self.launcher.preview()['plan_sha256'])
        self.attempt=next((self.store.root/'launches').iterdir());self.launch_id=self.attempt.name

    def test_pending_review_is_read_only_and_cannot_clear_running_application(self):
        self.pending();before={p.name:p.read_bytes() for p in self.attempt.iterdir()}
        review=self.launcher.review(self.launch_id)
        self.assertEqual(review['process_state'],'running');self.assertFalse(review['vm_stopped'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.attempt.iterdir()})
        with self.assertRaises(ContractError):self.launcher.settle(self.launch_id,review['review_sha256'])
        with self.assertRaises(ContractError):self.store.check_launches()
        self.assertFalse((self.attempt/'settled.json').exists());self.assertEqual(len(self.spawns),1)

    def test_retained_linux_exit_settles_without_inventing_exit_code_or_vm_stop(self):
        self.pending();review=self.launcher.review(self.launch_id)
        self.observer.outcome={'state':'exited','returncode':None,'source':'retained-linux-pidfd','exit_code_known':False}
        result=self.launcher.settle(self.launch_id,review['review_sha256'],1000)
        self.assertIsNone(result['returncode']);self.assertFalse(result['exit_code_known']);self.assertFalse(result['vm_stopped'])
        self.store.check_launches();self.store.activate('0.1.0')
        self.assertEqual(self.launcher.history()['launches'][0]['state'],'exit-recorded')
        self.assertFalse((self.attempt/'exit.json').exists());self.assertTrue((self.attempt/'intent.json').exists())
        with self.assertRaises(ContractError):self.launcher.settle(self.launch_id,review['review_sha256'])
        self.assertEqual(len(self.spawns),1)

    def test_retained_windows_exit_preserves_exit_code_259(self):
        self.pending('windows-x64');review=self.launcher.review(self.launch_id);self.observer.outcome=259
        result=self.launcher.settle(self.launch_id,review['review_sha256'])
        self.assertEqual(result['returncode'],259);self.assertTrue(result['exit_code_known']);self.store.check_launches()

    def test_missing_pid_is_unknown_and_does_not_unlock_version_switch(self):
        self.pending();review=self.launcher.review(self.launch_id);self.observer.unavailable=True
        with self.assertRaises(NativeError):self.launcher.settle(self.launch_id,review['review_sha256'])
        with self.assertRaises(ContractError):self.store.activate('0.1.0')
        self.assertFalse((self.attempt/'settled.json').exists())

    def test_reused_pid_and_image_drift_refuse_before_retaining(self):
        self.pending();review=self.launcher.review(self.launch_id)
        for identity in (ProcessIdentity(123,457,self.observer.identity.image_path,'running'),ProcessIdentity(123,456,'/other','running')):
            self.observer.identity=identity
            with self.assertRaises(ContractError):self.launcher.settle(self.launch_id,review['review_sha256'])
        self.assertEqual(self.observer.calls,0)

    def test_stale_review_and_changed_process_state_refuse(self):
        self.pending();review=self.launcher.review(self.launch_id)
        with self.assertRaises(ContractError):self.launcher.settle(self.launch_id,'0'*64)
        self.observer.identity=ProcessIdentity(123,456,self.observer.identity.image_path,'exited')
        with self.assertRaises(ContractError):self.launcher.settle(self.launch_id,review['review_sha256'])
        self.assertEqual(self.observer.calls,0)

    def test_records_changed_during_wait_cannot_be_settled(self):
        self.pending();review=self.launcher.review(self.launch_id)
        def wait(handle,timeout):
            saved=json.loads((self.attempt/'identity.json').read_text());saved['process']['creation_ticks']=999
            (self.attempt/'identity.json').write_text(canonical(saved))
            return {'state':'exited','returncode':None,'source':'retained-linux-pidfd','exit_code_known':False}
        self.observer.wait_exit=wait
        with self.assertRaises(ContractError):self.launcher.settle(self.launch_id,review['review_sha256'])
        self.assertFalse((self.attempt/'settled.json').exists())

    def test_legacy_missing_identity_never_guesses_from_pid(self):
        self.pending();(self.attempt/'identity.json').unlink()
        with self.assertRaises(OSError):self.launcher.review(self.launch_id)
        with self.assertRaises(ContractError):self.store.check_launches()
        self.assertEqual(self.observer.calls,0)

    def test_linux_case_sensitive_image_and_platform_binding(self):
        self.pending();review=self.launcher.review(self.launch_id)
        self.observer.identity=ProcessIdentity(123,456,self.observer.identity.image_path.upper(),'running')
        with self.assertRaises(ContractError):self.launcher.review(self.launch_id)
        self.launcher.host=lambda:'windows-x64'
        with self.assertRaises(ContractError):self.launcher.settle(self.launch_id,review['review_sha256'])

    def test_fake_linux_code_or_cross_platform_proof_refuses(self):
        self.pending();review=self.launcher.review(self.launch_id)
        for outcome in (0,True,{'state':'exited','returncode':0,'source':'retained-linux-pidfd','exit_code_known':True}):
            self.observer.outcome=outcome
            with self.assertRaises(ContractError):self.launcher.settle(self.launch_id,review['review_sha256'])
        self.assertFalse((self.attempt/'settled.json').exists())

    def test_settlement_write_failure_preserves_unknown_without_replay(self):
        self.pending('windows-x64');review=self.launcher.review(self.launch_id);self.observer.outcome=0
        with patch('ctflab_release_launcher.record',side_effect=OSError('fixture full')):
            with self.assertRaises(OSError):self.launcher.settle(self.launch_id,review['review_sha256'])
        with self.assertRaises(ContractError):self.store.check_launches()
        self.assertEqual(len(self.spawns),1)

    def test_capture_does_not_bind_reused_pid_after_original_child_exits(self):
        self.configured();seen=[]
        class Observer:
            def observe(inner,pid):seen.append(pid);raise AssertionError('原子进程已退出，不查询可重用PID')
        self.launcher.observer=Observer
        process=FakeProcess();process.poll=lambda:0
        self.launcher.spawn=lambda *a,**k:process
        self.launcher.run(self.launcher.preview()['plan_sha256'])
        attempt=next((self.store.root/'launches').iterdir())
        self.assertEqual(seen,[]);self.assertFalse((attempt/'identity.json').exists());self.store.check_launches()

    def test_corrupt_settlement_cannot_unlock_and_wait_is_bounded(self):
        self.pending('windows-x64');review=self.launcher.review(self.launch_id);self.observer.outcome=0
        for timeout in (-1,1001,True):
            with self.assertRaises(ContractError):self.launcher.settle(self.launch_id,review['review_sha256'],timeout)
        self.launcher.settle(self.launch_id,review['review_sha256'])
        saved=json.loads((self.attempt/'settled.json').read_text());saved['identity_sha256']='0'*64
        (self.attempt/'settled.json').write_text(canonical(saved))
        with self.assertRaises(ContractError):self.store.check_launches()


    def test_stage_retains_signature_and_launch_rechecks_fixed_entry_without_source_extras(self):
        self.configured();version=self.store.root/'versions/0.1.0'
        self.assertTrue((version/SIGNED_MANIFEST).exists());self.assertFalse((version/'app.exe').exists())
        envelope=json.loads((version/SIGNED_MANIFEST).read_text())
        self.assertEqual(release_manifest(envelope,self.keys)[0],self.payload)
        preview=self.launcher.preview();self.assertTrue(preview['release_signature_verified'])
        self.assertFalse(preview['runtime_verified']);self.assertFalse(preview['authenticode_verified'])
        with patch.dict(os.environ,{'LD_PRELOAD':'fixture-danger','PYTHONPATH':'fixture-danger','WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS':'fixture-danger'}):
            result=self.launcher.run(preview['plan_sha256'])
        self.assertEqual(result['state'],'application-exited');self.assertFalse(result['vm_stopped'])
        self.assertEqual(self.spawns[0][0],[str(version/'ctflab-desktop')]);options=self.spawns[0][1]
        self.assertEqual(options['cwd'],str(version));self.assertTrue(options['close_fds'])
        self.assertNotIn('LD_PRELOAD',options['env']);self.assertNotIn('PYTHONPATH',options['env'])
        self.assertNotIn('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS',options['env'])
        self.assertEqual(self.launcher.history()['launches'][0]['state'],'exit-recorded')
        self.store.check_launches()

    def test_new_schema_requires_exact_entry_platform_and_executable_fields(self):
        self.configured()
        for change in ({'entry':'app.exe'},{'platform':'macos-arm64'},{'arguments':['--delete']},
                       {'executables':[]},{'executables':['LICENSE']},{'executables':['ctflab-desktop','ctflab-desktop']}):
            old=dict(self.payload['launch']);self.payload['launch'].update(change)
            with self.assertRaises((ContractError,TypeError)):release_manifest(self.envelope(),self.keys)
            self.payload['launch']=old
        self.payload['files'][SIGNED_MANIFEST]='a'*64
        with self.assertRaises(ContractError):release_manifest(self.envelope(),self.keys)

    def test_signed_file_change_refuses_before_any_spawn(self):
        self.configured();preview=self.launcher.preview()
        (self.store.root/'versions/0.1.0/ctflab-desktop').write_bytes(b'changed')
        with self.assertRaises((ContractError,ValueError)):self.launcher.run(preview['plan_sha256'])
        self.assertEqual(self.spawns,[]);self.assertEqual(self.store.status()['active'],'0.1.0')

    def test_extra_unsigned_library_or_empty_directory_refuses_launch(self):
        self.configured();version=self.store.root/'versions/0.1.0'
        extra=version/'unexpected.dll';extra.write_bytes(b'extra')
        with self.assertRaises(ContractError):self.launcher.preview()
        extra.unlink();(version/'unexpected').mkdir()
        with self.assertRaises(ContractError):self.launcher.preview()
        self.assertEqual(self.spawns,[])

    def test_signature_tamper_and_unknown_trust_root_refused(self):
        self.configured();version=self.store.root/'versions/0.1.0'
        envelope=json.loads((version/SIGNED_MANIFEST).read_text());envelope['signature']='AAAA'
        (version/SIGNED_MANIFEST).write_text(canonical(envelope))
        with self.assertRaises(ContractError):self.launcher.preview()
        self.assertEqual(self.spawns,[])

    def test_windows_os_signature_is_mandatory_and_failure_never_spawns(self):
        self.configured('windows-x64');preview=self.launcher.preview()
        self.assertTrue(preview['authenticode_verified']);self.assertEqual(len(self.signatures),1)
        self.launcher.signature=lambda _:False
        with self.assertRaises(ContractError):self.launcher.run(preview['plan_sha256'])
        self.assertEqual(self.spawns,[])

    def test_wrong_host_or_database_path_is_rejected_without_fallback(self):
        self.configured();self.launcher.host=lambda:'windows-x64'
        with self.assertRaises(ContractError):self.launcher.preview()
        self.launcher.host=lambda:'linux-x64'
        with self.store.locked() as db:db.execute('UPDATE versions SET path=?',(str(self.source),))
        with self.assertRaises(ContractError):self.launcher.preview()
        self.assertEqual(self.spawns,[])

    def test_stale_launch_preview_cannot_run_new_active_version(self):
        self.configured();preview=self.launcher.preview();self.payload['version']='0.2.0'
        self.stage();self.store.activate('0.2.0')
        with self.assertRaises(ContractError):self.launcher.run(preview['plan_sha256'])
        self.assertEqual(self.spawns,[])

    def test_active_launcher_blocks_switch_and_update_but_keeps_database_readable(self):
        def waiting():
            self.assertEqual(self.store.status()['active'],'0.1.0')
            for operation in (lambda:self.store.activate('0.1.0'),self.store.rollback,
                              lambda:UpdateCoordinator(self.store).preview('0.1.0'),
                              lambda:self.launcher.run(preview['plan_sha256'])):
                with self.assertRaises((OSError,RuntimeError,ValueError)):operation()
            return 0
        self.configured(wait=waiting);preview=self.launcher.preview()
        self.launcher.run(preview['plan_sha256']);self.assertEqual(len(self.spawns),1)
        self.store.activate('0.1.0')

    def test_interrupt_preserves_unknown_without_kill_replay_or_switch(self):
        def interrupted():raise KeyboardInterrupt()
        self.configured(wait=interrupted);preview=self.launcher.preview()
        with self.assertRaises(KeyboardInterrupt):self.launcher.run(preview['plan_sha256'])
        self.assertEqual(self.launcher.history()['launches'][0]['state'],'unknown')
        with self.assertRaises(ContractError):self.store.activate('0.1.0')
        with self.assertRaises(ContractError):self.launcher.run(preview['plan_sha256'])
        self.assertEqual(len(self.spawns),1);self.assertEqual(self.store.status()['active'],'0.1.0')

    def test_spawn_error_keeps_unknown_intent_and_never_auto_retries(self):
        self.configured();preview=self.launcher.preview()
        def failed(*a,**k):raise OSError('合成派生错误')
        self.launcher.spawn=failed
        with self.assertRaises(OSError):self.launcher.run(preview['plan_sha256'])
        self.assertEqual(self.launcher.history()['launches'][0]['state'],'unknown')
        with self.assertRaises(ContractError):self.launcher.preview()

    def test_false_exit_record_cannot_clear_unknown_launch(self):
        def interrupted():raise KeyboardInterrupt()
        self.configured(wait=interrupted);preview=self.launcher.preview()
        with self.assertRaises(KeyboardInterrupt):self.launcher.run(preview['plan_sha256'])
        attempt=next((self.store.root/'launches').iterdir())
        (attempt/'exit.json').write_text(json.dumps({'source':'retained-child-process','returncode':0,'intent_sha256':'0'*64}))
        (attempt/'exit.json').chmod(0o600)
        self.assertEqual(self.launcher.history()['launches'][0]['state'],'unknown')
        with self.assertRaises(ContractError):self.store.activate('0.1.0')

    @unittest.skipIf(os.name=='nt','POSIX脚本替身；不代替Linux/Windows原生桌面验收')
    def test_real_owned_script_runs_fixed_path_and_retains_nonzero_exit(self):
        self.configured();self.payload['version']='0.2.0';output=self.root/'fixture-result.json'
        binary=self.source/'ctflab-desktop'
        binary.write_text('#!'+sys.executable+'\nimport json,os\nfrom pathlib import Path\n'+
            'Path('+repr(str(output))+').write_text(json.dumps({"injected":"LD_PRELOAD" in os.environ}))\nraise SystemExit(7)\n')
        self.payload['files']['ctflab-desktop']=digest(binary);self.stage();self.store.activate('0.2.0')
        launcher=ReleaseLauncher(self.store,self.keys,host=lambda:'linux-x64')
        with patch.dict(os.environ,{'LD_PRELOAD':'fixture-danger'}):result=launcher.run(launcher.preview()['plan_sha256'])
        self.assertEqual(result['returncode'],7);self.assertFalse(json.loads(output.read_text())['injected'])
        self.store.check_launches();self.assertEqual(launcher.history()['launches'][0]['state'],'exit-recorded')

    def test_nested_runtime_executables_are_explicit_and_directory_aliases_refused(self):
        self.configured();self.payload['version']='0.2.0';directory=self.source/'runtime/python';directory.mkdir(parents=True)
        runtime=directory/'python3';runtime.write_bytes(b'fixture helper')
        self.payload['files']['runtime/python/python3']=digest(runtime);self.payload['launch']['executables'].append('runtime/python/python3')
        self.stage();self.store.activate('0.2.0');self.launcher.preview()
        if os.name!='nt':self.assertTrue(os.access(self.store.root/'versions/0.2.0/runtime/python/python3',os.X_OK))
        for name in ('runtime/Python/other','runtime./other'):
            self.payload['files'][name]='a'*64
            with self.assertRaises(ContractError):release_manifest(self.envelope(),self.keys)
            del self.payload['files'][name]

    def test_old_manifest_never_guesses_an_executable(self):
        self.stage();self.store.activate('0.1.0')
        launcher=ReleaseLauncher(self.store,self.keys,host=lambda:'linux-x64')
        with self.assertRaises(ContractError) as failure:launcher.preview()
        self.assertEqual(failure.exception.code,'version-mismatch')

    def test_corrupt_active_version_cannot_read_outside_version_directory(self):
        self.configured()
        with self.store.locked() as db:
            db.execute("UPDATE versions SET id='../outside'");db.execute("UPDATE pointers SET active='../outside'")
        with patch('ctflab_release_launcher.read_json',side_effect=AssertionError('不得读取越界清单')):
            with self.assertRaises(ContractError):self.launcher.preview()
        self.assertEqual(self.spawns,[])

    def test_spawn_record_failure_preserves_child_and_blocks_new_launch(self):
        self.configured();preview=self.launcher.preview()
        from ctflab_windows_recovery import record
        def failing(path,value):
            if path.name=='spawned.json':raise OSError('合成派生后记录失败')
            return record(path,value)
        with patch('ctflab_release_launcher.record',side_effect=failing):
            with self.assertRaises(OSError):self.launcher.run(preview['plan_sha256'])
        self.assertEqual(len(self.spawns),1);self.assertEqual(self.launcher.history()['launches'][0]['state'],'unknown')
        with self.assertRaises(ContractError):self.store.activate('0.1.0')

    def test_legacy_root_requires_explicit_launcher_state_initialization(self):
        self.stage();self.store.activate('0.1.0')
        (self.store.root/'application.lock').unlink();(self.store.root/'launches').rmdir()
        with self.assertRaises(OSError):self.store.activate('0.1.0')
        UpdateCoordinator(self.store).initialize()
        self.assertTrue((self.store.root/'application.lock').is_file());self.store.activate('0.1.0')

    def test_file_change_during_os_signature_check_is_rejected_before_spawn(self):
        self.configured('windows-x64')
        def changed(path):path.write_bytes(b'changed during verification');return True
        self.launcher.signature=changed
        with self.assertRaises(ContractError):self.launcher.preview()
        self.assertEqual(self.spawns,[])

    @unittest.skipIf(os.name=='nt','文件执行位只在POSIX校验，不替代Windows ACL')
    def test_declared_runtime_executable_mode_drift_refuses_preview(self):
        self.configured();self.payload['version']='0.2.0';directory=self.source/'runtime/python';directory.mkdir(parents=True)
        runtime=directory/'python3';runtime.write_bytes(b'fixture helper')
        self.payload['files']['runtime/python/python3']=digest(runtime);self.payload['launch']['executables'].append('runtime/python/python3')
        self.stage();self.store.activate('0.2.0')
        (self.store.root/'versions/0.2.0/runtime/python/python3').chmod(0o600)
        with self.assertRaises(ContractError):self.launcher.preview()
        self.assertEqual(self.spawns,[])


class WinTrustLayoutTests(unittest.TestCase):
    @unittest.skipUnless(ctypes.sizeof(ctypes.c_void_p)==8,'当前实现/矩阵仅x64')
    def test_x64_layout_and_offline_no_ui_provider_state_cleanup(self):
        self.assertEqual(ctypes.sizeof(GUID),16);self.assertEqual(ctypes.sizeof(WINTRUST_FILE_INFO),32)
        self.assertEqual(ctypes.sizeof(WINTRUST_DATA),88);states=[]
        def verify(hwnd,action,data):
            value=ctypes.cast(data,ctypes.POINTER(WINTRUST_DATA)).contents
            self.assertEqual(value.dwUIChoice,2);self.assertEqual(value.dwUnionChoice,1)
            self.assertTrue(value.dwProvFlags&0x1000);self.assertTrue(value.dwProvFlags&0x80)
            states.append(value.dwStateAction);return 0
        self.assertTrue(verify_embedded_signature(Path('/fixture/app.exe'),verify=verify));self.assertEqual(states,[1,2])

    def test_nonzero_provider_result_always_refused_and_closed(self):
        states=[]
        def verify(hwnd,action,data):
            state=ctypes.cast(data,ctypes.POINTER(WINTRUST_DATA)).contents.dwStateAction;states.append(state)
            return -1 if state==1 else 0
        with self.assertRaises(ContractError):verify_embedded_signature(Path('/fixture/app.exe'),verify=verify)
        self.assertEqual(states,[1,2])


if __name__=='__main__':unittest.main()
