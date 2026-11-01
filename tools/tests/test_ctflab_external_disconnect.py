"""真实私有账本/独立worker函数复现断开锁冲突；无VM、SSH或真实网络。"""
import hashlib
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ctflab_desktop_bridge as bridge
from ctflab_contract import ContractError, canonical
from ctflab_external_attach import AttachStore
from ctflab_generation_store import GenerationStore
from ctflab_local_service import LocalService
from test_ctflab_external_attach_acceptance import plan
from test_ctflab_desktop_external_attach import registration


class WorkerLaunchMixin:
    """真实worker子进程夹具：网络传输用替身，代次/信号/锁/回执均为真函数。"""

    def launch_worker(self):
        source = """import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
root=Path(sys.argv[2]);sid=sys.argv[3]
while not (root/'go').exists(): time.sleep(.01)
import ctflab_external_attach as external
import ctflab_desktop_bridge as bridge
def relay(*args,**kwargs):
 kwargs['on_ready']({'identity_state':'verified'})
 (root/'ready').write_text('ready')
 while not kwargs['stop'](): time.sleep(.01)
 return {'reason':'completed','fixture_final_receipt':'preserved'}
external.run_relay=relay
bridge.external_relay_worker(root,sid)
"""
        worker = self.parent/'worker.py';worker.write_text(source)
        log = (self.parent/'worker.log').open('wb')
        self.addCleanup(log.close)
        child = subprocess.Popen([sys.executable,'-B',str(worker),str(Path(bridge.__file__).parent),
                                  str(self.root),self.sid,'ctflab_desktop_bridge','external-relay'],
                                 stdout=log,stderr=subprocess.STDOUT)
        def cleanup():
            if child.poll() is None:
                child.terminate()
                try: child.wait(2)
                except subprocess.TimeoutExpired:
                    child.kill();child.wait(2)
        self.addCleanup(cleanup)
        with self.store.locked():
            binding=self.attach.load();binding['session']['pid']=child.pid
            if bridge.platform.system() == 'Windows':
                binding['session']['process_identity']=bridge._capture_windows_relay(child)
            self.attach.save(binding)
        (self.root/'go').write_text('go')
        deadline=time.monotonic()+5
        while not (self.root/'ready').exists() and time.monotonic()<deadline:
            if child.poll() is not None:break
            time.sleep(.01)
        self.assertTrue((self.root/'ready').exists(),(self.parent/'worker.log').read_text())
        self.assertTrue(bridge.observe_relay_process(self.attach.load()['session']))
        return child


class DisconnectLockTests(WorkerLaunchMixin, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name).resolve()
        asset = self.parent/'base.raw'
        asset.write_bytes(b'independent-disconnect-fixture')
        manifest = plan()['manifest']
        manifest['assets']['a']['sha256'] = hashlib.sha256(asset.read_bytes()).hexdigest()
        self.instance = str(uuid.uuid4())
        self.root = self.parent/'state'
        self.store = GenerationStore.create(self.root, manifest, self.instance, {'a': asset})
        LocalService.create(self.root/'desktop-contract')
        bridge.record(self.root/'runtime-profile.json', {'networks': {'outer': {'external':40011}}})
        bridge.dispatch(self.root, {'action':'external-attach-save', 'registration':registration(),
                                   'network':'outer'})
        self.attach = AttachStore(self.root,self.instance,generation=1,network_id='outer')
        self.sid = str(uuid.uuid4())
        config = self.parent/'ssh.json'
        config.write_text('{}');config.chmod(0o600)
        binding = self.attach.load()
        binding['session'] = {'session_uuid':self.sid, 'state':'connecting', 'pid':0,
                              'ssh_config':str(config), 'secret':'a'*64, 'backend':'hub'}
        self.attach.save(binding)

    @unittest.skipUnless(os.name in ('posix','nt'), '等待支持的平台进程API')
    def test_production_disconnect_preserves_worker_receipt_and_normal_exit(self):
        child=self.launch_worker()
        result=bridge.dispatch(self.root,{'action':'external-attach-disconnect'})
        child.wait(5)
        log=(self.parent/'worker.log').read_text()
        self.assertEqual(child.returncode,0,log)
        self.assertEqual(result['state'],'relay-detached')
        final=self.attach.load()['session']
        self.assertEqual(final['state'],'disconnected')
        self.assertEqual(final['report']['fixture_final_receipt'],'preserved')
        self.assertFalse(bridge.observe_relay_process(final))


    def disconnected_fixture(self, *, receipt=False):
        binding=self.attach.load()
        binding['session'].update(state='unknown',pid=424242)
        if receipt:
            binding['session']['report']={'transport_closed':True,'reason':'completed'}
        self.attach.save(binding)

    @unittest.skipUnless(os.name == 'posix', '真实POSIX信号/ps路径，Windows原生适配另验')
    def test_worker_final_receipt_retries_transient_gate_contention(self):
        child=self.launch_worker()
        with self.store.locked():
            child.terminate()  # 仅本测试刚创建并持有的子进程。
            time.sleep(.25)
            self.assertIsNone(child.poll(),(self.parent/'worker.log').read_text())
        child.wait(5)
        self.assertEqual(child.returncode,0,(self.parent/'worker.log').read_text())
        self.assertTrue(self.attach.load()['session']['report']['transport_closed'])

    def test_missing_receipt_is_unknown_even_when_pid_is_gone(self):
        self.disconnected_fixture()
        with patch.object(bridge,'observe_relay_process',return_value=False), patch.object(bridge.os,'kill') as kill:
            result=bridge.dispatch(self.root,{'action':'external-attach-disconnect'})
        kill.assert_not_called()
        self.assertEqual(result['state'],'relay-unknown')
        self.assertEqual(self.attach.load()['session']['disconnect_failure'],'final-receipt-missing')

    def test_observation_unknown_does_not_send_signal(self):
        self.disconnected_fixture(receipt=True)
        with patch.object(bridge,'observe_relay_process',return_value=None), patch.object(bridge.os,'kill') as kill:
            result=bridge.dispatch(self.root,{'action':'external-attach-disconnect'})
        kill.assert_not_called()
        self.assertEqual(result['state'],'relay-unknown')
        self.assertEqual(self.attach.load()['session']['disconnect_failure'],'process-observation-unknown')

    def test_already_exited_with_receipt_reports_without_claiming_signal(self):
        self.disconnected_fixture(receipt=True)
        with patch.object(bridge,'observe_relay_process',return_value=False), patch.object(bridge.os,'kill') as kill:
            result=bridge.dispatch(self.root,{'action':'external-attach-disconnect'})
        kill.assert_not_called()
        self.assertEqual(result['state'],'relay-detached')
        self.assertFalse(result['terminated_by_user'])
        self.assertTrue(self.attach.load()['session']['already_exited'])

    @unittest.skipUnless(os.name == 'posix', 'POSIX ps/signal只读探测分支')
    def test_read_failure_with_existing_pid_is_not_proof_of_exit(self):
        with patch('ctflab_scenario_runtime.process_command',return_value=None), patch.object(bridge.os,'kill') as probe:
            self.assertIsNone(bridge.observe_relay_process({'pid':424242,'session_uuid':self.sid}))
        probe.assert_called_once_with(424242,0)
        with patch('ctflab_scenario_runtime.process_command',return_value=None), patch.object(bridge.os,'kill',side_effect=ProcessLookupError):
            self.assertIs(bridge.observe_relay_process({'pid':424242,'session_uuid':self.sid}),False)

    @unittest.skipUnless(os.name == 'posix', 'POSIX命令行身份分支')
    def test_identity_mismatch_cannot_authorize_signal(self):
        with patch('ctflab_scenario_runtime.process_command',return_value='/usr/bin/unrelated'), patch.object(bridge.os,'kill') as kill:
            self.assertIs(bridge.observe_relay_process({'pid':424242,'session_uuid':self.sid}),False)
        kill.assert_not_called()

    def test_session_replacement_during_wait_is_not_overwritten(self):
        self.disconnected_fixture(receipt=True)
        changed=[]
        calls=[]
        def signal(pid,sig):
            calls.append((pid,sig))
            with self.store.locked():  # 必须能取得锁，等待阶段不得占锁。
                fresh=self.attach.load()
                fresh['session']={'session_uuid':str(uuid.uuid4()),'pid':999999,'state':'connected'}
                self.attach.save(fresh)
                changed.append(self.attach.path.read_bytes())
        # 协作窗口（10次）内保持True，杀进程后的等待观察返回False。
        with patch.object(bridge,'observe_relay_process',side_effect=[True]*11+[False]), patch.object(bridge.os,'kill',side_effect=signal):
            with self.assertRaises(ContractError) as error:
                bridge.dispatch(self.root,{'action':'external-attach-disconnect'})
        self.assertEqual(error.exception.code,'state-conflict')
        self.assertEqual(self.attach.path.read_bytes(),changed[0])
        self.assertEqual(calls[0][0],424242)
        self.assertEqual(len(calls),1)

    def test_binding_change_during_wait_is_not_overwritten(self):
        self.disconnected_fixture(receipt=True)
        changed=[]
        def signal(*_):
            with self.store.locked():
                fresh=self.attach.load();fresh['policy_sha256']='b'*64
                self.attach.save(fresh);changed.append(self.attach.path.read_bytes())
        with patch.object(bridge,'observe_relay_process',side_effect=[True]*11+[False]), patch.object(bridge.os,'kill',side_effect=signal):
            with self.assertRaises(ContractError):
                bridge.dispatch(self.root,{'action':'external-attach-disconnect'})
        self.assertEqual(self.attach.path.read_bytes(),changed[0])


    def test_active_or_unobservable_unknown_session_cannot_clear_or_reconnect(self):
        self.disconnected_fixture()
        for observation in (True,None):
            with self.subTest(observation=observation), patch.object(bridge,'observe_relay_process',return_value=observation), patch.object(bridge,'launch') as launch:
                for value in ({'action':'external-attach-clear'},
                              {'action':'external-attach-connect','ssh_config':'unused.json'}):
                    with self.assertRaises(ContractError) as error:
                        bridge.dispatch(self.root,value)
                    self.assertEqual(error.exception.code,'resource-busy')
                launch.assert_not_called()
        self.assertIsNotNone(self.attach.load())


    def test_windows_observation_never_uses_posix_probe_or_signal(self):
        from types import SimpleNamespace
        with patch.object(bridge.platform,'system',return_value='Windows'), patch('ctflab_windows_native.Win32',return_value=SimpleNamespace(pid_exists=lambda _:True)), patch('ctflab_scenario_runtime.process_command') as command, patch.object(bridge.os,'kill') as kill:
            self.assertIsNone(bridge.observe_relay_process({'pid':424242,'session_uuid':self.sid}))
        command.assert_not_called()
        kill.assert_not_called()


    @unittest.skipUnless(os.name in ('posix','nt'), '等待支持的平台进程API')
    def test_real_worker_exits_from_private_cooperative_request_without_signal(self):
        child=self.launch_worker()
        with self.store.locked():
            binding=self.attach.load()
            binding['session'].update(disconnect_requested=True,disconnect_request_id=str(uuid.uuid4()))
            self.attach.save(binding)
        child.wait(5)
        self.assertEqual(child.returncode,0,(self.parent/'worker.log').read_text())
        self.assertTrue(self.attach.load()['session']['report']['transport_closed'])


class ScanRecoveryTests(WorkerLaunchMixin, unittest.TestCase):
    """缺PID旧unknown记录的受验证恢复：命令行扫描证明，不清账不猜进程。"""

    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent=Path(temporary.name).resolve()
        asset=self.parent/'base.raw'
        asset.write_bytes(b'independent-disconnect-fixture')
        manifest=plan()['manifest']
        manifest['assets']['a']['sha256']=hashlib.sha256(asset.read_bytes()).hexdigest()
        self.instance=str(uuid.uuid4())
        self.root=self.parent/'state'
        self.store=GenerationStore.create(self.root,manifest,self.instance,{'a':asset})
        LocalService.create(self.root/'desktop-contract')
        bridge.record(self.root/'runtime-profile.json',{'networks':{'outer':{'external':40012}}})
        bridge.dispatch(self.root,{'action':'external-attach-save','registration':registration(),
                                   'network':'outer'})
        self.attach=AttachStore(self.root,self.instance,generation=1,network_id='outer')
        self.sid=str(uuid.uuid4())
        config=self.parent/'ssh.json'
        config.write_text('{}');config.chmod(0o600)
        binding=self.attach.load()
        binding['session']={'session_uuid':self.sid,'state':'connecting','pid':0,
                            'ssh_config':str(config),'secret':'a'*64,'backend':'hub'}
        self.attach.save(binding)

    def legacy_fixture(self, *, receipt=False):
        binding=self.attach.load()
        binding['session'].update(state='unknown',pid=0)
        binding['session'].pop('process_identity',None)
        if receipt:
            binding['session']['report']={'transport_closed':True,'reason':'completed'}
        self.attach.save(binding)

    def test_scan_relay_pid_parses_single_match_and_refuses_ambiguity(self):
        from types import SimpleNamespace
        if bridge.platform.system() not in ('Darwin','Linux'):
            self.skipTest('命令行扫描为Darwin/Linux路径')
        session_line='  4711 python3 -B worker.py ctflab_desktop_bridge external-relay %s'%self.sid
        other_line='  4712 /usr/sbin/syslogd'
        output=session_line+'\n'+other_line+'\n'
        fake=SimpleNamespace(returncode=0,stdout=output)
        with patch('subprocess.run',return_value=fake) as run:
            self.assertEqual(bridge.scan_relay_pid(self.sid),4711)
            run.assert_called_once()
        with patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=other_line+'\n')):
            self.assertIs(bridge.scan_relay_pid(self.sid),False)
        twice=session_line+'\n'+session_line+'\n'
        with patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=twice)):
            with self.assertRaises(RuntimeError):bridge.scan_relay_pid(self.sid)
        with patch('subprocess.run',side_effect=OSError('ps unavailable')):
            self.assertIsNone(bridge.scan_relay_pid(self.sid))
        self.assertIsNone(bridge.scan_relay_pid('not-a-uuid'))

    def test_observe_without_pid_falls_back_to_scan(self):
        if bridge.platform.system() not in ('Darwin','Linux'):
            self.skipTest('命令行扫描为Darwin/Linux路径')
        session={'session_uuid':self.sid,'state':'connecting','pid':0}
        for scanned,expected in ((4711,True),(False,False),(None,None)):
            with patch.object(bridge,'scan_relay_pid',return_value=scanned):
                self.assertIs(bridge.observe_relay_process(session),expected)

    @unittest.skipUnless(os.name=='posix','真实POSIX ps扫描与信号路径')
    def test_scan_unavailable_keeps_pid_unknown_without_kill(self):
        self.legacy_fixture()
        with patch.object(bridge,'scan_relay_pid',return_value=None), patch.object(bridge.os,'kill') as kill:
            result=bridge.dispatch(self.root,{'action':'external-attach-disconnect'})
        kill.assert_not_called()
        self.assertEqual(result['state'],'relay-unknown')
        self.assertEqual(self.attach.load()['session']['disconnect_failure'],'pid-unknown')

    @unittest.skipUnless(os.name=='posix','真实POSIX ps扫描路径')
    def test_scan_absence_with_receipt_recovers_to_disconnected(self):
        self.legacy_fixture(receipt=True)
        with patch.object(bridge,'scan_relay_pid',return_value=False), patch.object(bridge.os,'kill') as kill:
            result=bridge.dispatch(self.root,{'action':'external-attach-disconnect'})
        kill.assert_not_called()
        self.assertEqual(result['state'],'relay-detached')
        final=self.attach.load()['session']
        self.assertEqual(final['state'],'disconnected')
        self.assertEqual(final['pid_source'],'command-scan-absent')
        self.assertTrue(final['already_exited'])

    @unittest.skipUnless(os.name=='posix','真实POSIX ps扫描路径')
    def test_scan_absence_without_receipt_stays_unknown_with_evidence(self):
        self.legacy_fixture()
        with patch.object(bridge,'scan_relay_pid',return_value=False), patch.object(bridge.os,'kill') as kill:
            result=bridge.dispatch(self.root,{'action':'external-attach-disconnect'})
        kill.assert_not_called()
        self.assertEqual(result['state'],'relay-unknown')
        final=self.attach.load()['session']
        self.assertEqual(final['disconnect_failure'],'final-receipt-missing')
        self.assertEqual(final['pid_source'],'command-scan-absent')

    @unittest.skipUnless(os.name=='posix','真实POSIX ps扫描与信号路径')
    def test_scan_ambiguity_refuses_recovery(self):
        self.legacy_fixture(receipt=True)
        with patch.object(bridge,'scan_relay_pid',side_effect=RuntimeError('relay-scan-ambiguous')), \
             patch.object(bridge.os,'kill') as kill:
            result=bridge.dispatch(self.root,{'action':'external-attach-disconnect'})
        kill.assert_not_called()
        self.assertEqual(result['state'],'relay-unknown')
        self.assertEqual(self.attach.load()['session']['disconnect_failure'],'relay-scan-ambiguous')

    @unittest.skipUnless(os.name=='posix','真实POSIX ps扫描与信号路径')
    def test_verified_absence_by_scan_allows_clear_and_reconnect_gates(self):
        self.legacy_fixture()
        with patch.object(bridge,'scan_relay_pid',return_value=False), patch.object(bridge,'launch') as launch:
            status=bridge.dispatch(self.root,{'action':'external-attach-status'})
            self.assertEqual(status['session']['state'],'unknown')
            cleared=bridge.dispatch(self.root,{'action':'external-attach-clear'})
            self.assertEqual(cleared['state'],'external-attach-cleared')
        self.assertIsNone(self.attach.load())

    @unittest.skipUnless(os.name=='posix','真实worker进程、ps与信号路径')
    def test_no_pid_session_adopts_scanned_pid_and_terminates_relay(self):
        child=self.launch_worker()
        with self.store.locked():
            binding=self.attach.load()
            binding['session']['pid']=0  # 模拟缺PID旧记录；worker已在运行。
            binding['session'].pop('process_identity',None)
            self.attach.save(binding)
        with patch.object(bridge,'scan_relay_pid',return_value=child.pid):
            result=bridge.dispatch(self.root,{'action':'external-attach-disconnect'})
        child.wait(5)
        self.assertEqual(child.returncode,0,(self.parent/'worker.log').read_text())
        self.assertEqual(result['state'],'relay-detached')
        final=self.attach.load()['session']
        self.assertEqual(final['state'],'disconnected')
        self.assertEqual(final['pid'],child.pid)
        self.assertEqual(final['pid_source'],'command-scan')
        # worker响应disconnect_requested在协作窗口内自行收口；不要求SIGTERM路径。
        self.assertTrue(final['report']['transport_closed'])
        self.assertTrue(result['terminated_by_user'] or final['already_exited'])

    @unittest.skipUnless(os.name=='posix','真实worker进程与真实ps扫描端到端')
    def test_no_pid_session_real_scan_confirms_exit_with_receipt(self):
        child=self.launch_worker()
        with self.store.locked():
            binding=self.attach.load()
            binding['session']['pid']=0  # 缺PID旧记录；协作退出与真实扫描竞争。
            binding['session'].pop('process_identity',None)
            self.attach.save(binding)
        result=bridge.dispatch(self.root,{'action':'external-attach-disconnect'})
        child.wait(5)
        self.assertEqual(child.returncode,0,(self.parent/'worker.log').read_text())
        self.assertEqual(result['state'],'relay-detached')
        final=self.attach.load()['session']
        self.assertEqual(final['state'],'disconnected')
        # 协作退出先于扫描→command-scan-absent；扫描先看到进程→采信PID并SIGTERM。
        self.assertIn(final.get('pid_source'),('command-scan','command-scan-absent'))
        self.assertTrue(final['report']['transport_closed'])
        self.assertFalse(bridge.observe_relay_process(final))


if __name__=='__main__':
    unittest.main()
