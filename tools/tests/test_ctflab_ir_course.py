"""C06真实文件/回环业务/派生处置，Windows事件为ctypes API替身；不操作VM。"""
import copy
import http.client
from http.server import HTTPServer
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch,Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
from ctflab_generation_store import digest
import ctflab_ir_course as ir
from ctflab_windows_course_events import WindowsEvents
from test_ctflab_windows_course_events import FakeAPI


class IncidentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.source=Path(__file__).resolve().parents[2];self.machine=str(uuid.uuid4());self.api=FakeAPI();self.run=self.root/'original'
        ir.materials(self.source,self.run,self.machine,1,self.port(),True)
        self.lab=self.open(self.run);self.lab.activate()
    def port(self):
        with socket.socket() as item:item.bind(('127.0.0.1',0));return item.getsockname()[1]
    def open(self,root):return ir.Lab(root,machine=lambda:{'machine_uuid':json.loads((root/'lab.json').read_text())['machine_uuid']},
        event_factory=lambda scope,key:WindowsEvents(scope,key,api=self.api))
    def change(self,lab,action):
        plan=lab.preview(action);operation=str(uuid.uuid4());return lab.apply(action,operation,plan['plan_sha256'])
    def start(self,lab):
        server=HTTPServer(('127.0.0.1',lab.config['port']),ir.Handler);server.lab=lab
        thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01});thread.start()
        def cleanup():server.shutdown();server.server_close();thread.join(3);self.assertFalse(thread.is_alive())
        self.addCleanup(cleanup)
    def get(self,lab,path='/'):
        connection=http.client.HTTPConnection('127.0.0.1',lab.config['port'],timeout=3)
        try:connection.request('GET',path);response=connection.getresponse();return response.status,json.loads(response.read())
        finally:connection.close()
    def capture(self):
        path=self.root/'capture';result=self.lab.capture(path);return path,result
    def derived(self,capture,result):
        root=self.root/'derived';ir.derive(self.source,capture,root,result['manifest_sha256'],str(uuid.uuid4()),2,self.port(),True)
        lab=self.open(root);lab.activate();return lab
    def test_real_business_incident_health_evidence_derived_repair_and_reset_preserve_original(self):
        self.start(self.lab);self.assertEqual(self.get(self.lab)[0],200)
        first=self.change(self.lab,'incident');self.assertEqual(self.get(self.lab)[0],503);self.assertEqual(self.get(self.lab,'/health')[0],200)
        capture,result=self.capture();before={name:digest(capture/name) for name in json.loads((capture/'MANIFEST.json').read_text())['files']}
        original_head=(self.run/'HEAD.json').read_bytes();derived=self.derived(capture,result);self.start(derived)
        self.assertEqual(self.get(derived)[0],503);self.change(derived,'repair');self.assertEqual(self.get(derived)[0],200)
        self.assertEqual(self.get(self.lab)[0],503);self.assertEqual((self.run/'HEAD.json').read_bytes(),original_head)
        self.change(derived,'reset');self.assertEqual(self.get(derived)[0],200)
        self.assertTrue(all(digest(capture/name)==value for name,value in before.items()))
        self.assertNotEqual(self.lab.config['lab_uuid'],derived.config['lab_uuid']);self.assertFalse(result['native_windows_api_executed'])
    def test_original_repair_forbidden_and_old_operation_result_never_claims_current_state(self):
        with self.assertRaises(ContractError):self.lab.preview('repair')
        plan=self.lab.preview('incident');operation=str(uuid.uuid4());self.lab.apply('incident',operation,plan['plan_sha256'])
        self.change(self.lab,'reset');calls=len([call for call in self.api.calls if call[0]=='report'])
        old=self.lab.apply('incident',operation,plan['plan_sha256']);self.assertFalse(old['current_state_verified'])
        self.assertEqual(self.lab.status()['state'],'serving');self.assertEqual(len([call for call in self.api.calls if call[0]=='report']),calls)
    def test_event_ack_loss_fences_new_effects_and_explicit_observation_resumes_without_reporting_again(self):
        plan=self.lab.preview('incident');operation=str(uuid.uuid4());self.api.fail_after_report=True
        with self.assertRaises(OSError):self.lab.apply('incident',operation,plan['plan_sha256'])
        self.assertEqual(self.lab.status()['state'],'serving');self.assertEqual(self.lab.status()['pending'],[operation])
        with self.assertRaises(ContractError):self.lab.preview('reset')
        with self.assertRaises(ContractError):self.lab.apply('incident',operation,plan['plan_sha256'])
        self.api.fail_after_report=False;view=self.lab.resume_preview(operation);calls=sum(call[0]=='report' for call in self.api.calls)
        self.lab.resume(operation,view['observation_sha256']);self.assertEqual(self.lab.status()['state'],'maintenance')
        self.assertEqual(sum(call[0]=='report' for call in self.api.calls),calls)
    def test_absent_or_duplicate_event_never_permits_resume_or_replays(self):
        plan=self.lab.preview('incident');operation=str(uuid.uuid4());self.api.report_ok=False
        with self.assertRaises(ContractError):self.lab.apply('incident',operation,plan['plan_sha256'])
        view=self.lab.resume_preview(operation);self.assertEqual(view['matching_events'],[])
        with self.assertRaises(ContractError):self.lab.resume(operation,view['observation_sha256'])
        self.assertEqual(self.lab.status()['state'],'serving');self.assertEqual(sum(call[0]=='report' for call in self.api.calls),1)
    def test_stale_observation_or_plan_is_refused_before_new_native_report(self):
        plan=self.lab.preview('incident');self.change(self.lab,'reset')
        with self.assertRaises(ContractError):self.lab.apply('incident',str(uuid.uuid4()),plan['plan_sha256'])
        before=len(self.api.rows);self.assertEqual(before,1)
    def test_config_runtime_key_or_owner_drift_is_not_adopted(self):
        old=(self.run/'key.json').read_bytes();(self.run/'key.json').write_text(canonical({'key':'f'*64}))
        with self.assertRaises(ContractError):self.lab.status()
        (self.run/'key.json').write_bytes(old);path=self.run/'runtime'/'ctflab_ir_course.py';path.write_bytes(path.read_bytes()+b'\n# drift\n')
        with self.assertRaises(ContractError):self.lab.status()
    def test_capture_raw_original_bytes_and_no_keys_or_teacher_files(self):
        self.change(self.lab,'incident');capture,result=self.capture();manifest=json.loads((capture/'MANIFEST.json').read_text())
        self.assertEqual((capture/'HEAD.json').read_bytes(),(self.run/'HEAD.json').read_bytes())
        self.assertEqual((capture/'lab.json').read_bytes(),(self.run/'lab.json').read_bytes())
        self.assertFalse(manifest['key_or_teacher_included']);self.assertFalse(manifest['whole_system_capture'])
        self.assertFalse((capture/'key.json').exists());self.assertFalse((capture/'teacher').exists())
        self.assertTrue(any(name.startswith('operations/') for name in manifest['files']))
        with self.assertRaises(FileExistsError):self.lab.capture(capture)
    def test_capture_drift_preserves_incomplete_materials_without_false_completion(self):
        self.change(self.lab,'incident');self.api.export_hook=lambda:(self.run/'HEAD.json').write_text('{}')
        with self.assertRaises(ContractError):self.lab.capture(self.root/'incomplete')
        self.assertTrue((self.root/'incomplete'/'INCOMPLETE.json').exists());self.assertFalse((self.root/'incomplete'/'MANIFEST.json').exists())
    def test_capture_digest_corruption_path_escape_and_incomplete_capture_refused_before_derive(self):
        self.change(self.lab,'incident');capture,result=self.capture()
        with self.assertRaises(ContractError):ir.derive(self.source,capture,self.root/'bad','0'*64,self.machine,2,self.port(),True)
        path=capture/'current-settings.json';path.write_text('{}')
        with self.assertRaises(ContractError):ir.derive(self.source,capture,self.root/'bad',result['manifest_sha256'],self.machine,2,self.port(),True)
        self.assertFalse((self.root/'bad').exists())
    def test_explicit_eventlog_permission_is_required_and_native_host_never_activates(self):
        root=self.root/'disabled';ir.materials(self.source,root,self.machine,1,self.port(),False)
        disabled=self.open(root);disabled.activate();plan=disabled.preview('incident')
        with self.assertRaises(ContractError):disabled.apply('incident',str(uuid.uuid4()),plan['plan_sha256'])
        self.assertEqual(disabled.journal(),[])
        with patch.object(ir,'WindowsEvents') as native,self.assertRaises(ContractError):ir.Lab(self.run)
        native.assert_not_called()
    def test_operation_identity_collision_limits_and_partial_settings_leave_unknown(self):
        plan=self.lab.preview('incident');operation=str(uuid.uuid4())
        with patch.object(ir,'MAX_CHANGES',0),self.assertRaises(ContractError):self.lab.apply('incident',operation,plan['plan_sha256'])
        self.assertEqual(self.lab.journal(),[])
        with patch.object(ir,'sealed',side_effect=OSError('测试半写入')),self.assertRaises(OSError):self.lab.apply('incident',operation,plan['plan_sha256'])
        self.assertEqual(self.lab.status()['pending'],[operation]);self.assertEqual(len(self.api.rows),0)
    def test_same_machine_derivation_and_unsealed_partial_copy_never_activate(self):
        self.change(self.lab,'incident');capture,result=self.capture()
        with self.assertRaises(ContractError):ir.derive(self.source,capture,self.root/'same',result['manifest_sha256'],self.machine,2,self.port(),True)
        self.assertFalse((self.root/'same').exists())
        target=self.root/'derived';original=ir.materials
        def interrupted(*args,**kwargs):
            value=original(*args,**kwargs);raise OSError('测试派生复制中断')
        with patch.object(ir,'materials',side_effect=interrupted),self.assertRaises(OSError):
            ir.derive(self.source,capture,target,result['manifest_sha256'],str(uuid.uuid4()),2,self.port(),True)
        with self.assertRaises((OSError,ValueError,RuntimeError)):self.open(target)
        self.assertFalse((target/'owner.json').exists())
    def test_source_evidence_path_escape_and_symlink_manifest_refused(self):
        self.change(self.lab,'incident');capture,result=self.capture();path=capture/'MANIFEST.json';value=json.loads(path.read_text())
        value['files']['../escape']={'sha256':'0'*64,'bytes':0};path.write_text(canonical(value))
        with self.assertRaises(ContractError):ir.evidence(capture,digest(path))
        outside=self.root/'outside-manifest';outside.write_bytes(path.read_bytes());outside.chmod(0o600);path.unlink();path.symlink_to(outside)
        with self.assertRaises((OSError,ValueError,RuntimeError)):ir.evidence(capture,digest(outside))
    def test_lost_receipt_after_local_commit_resumes_without_rewriting_event_or_head(self):
        plan=self.lab.preview('incident');operation=str(uuid.uuid4());original=ir.record
        def failure(path,value):
            if path.name=='receipt.json':raise OSError('测试本地提交后回执丢失')
            return original(path,value)
        with patch.object(ir,'record',side_effect=failure),self.assertRaises(OSError):self.lab.apply('incident',operation,plan['plan_sha256'])
        head=(self.run/'HEAD.json').read_bytes();self.assertEqual(self.lab.status()['state'],'maintenance')
        view=self.lab.resume_preview(operation);self.lab.resume(operation,view['observation_sha256'])
        self.assertEqual((self.run/'HEAD.json').read_bytes(),head);self.assertEqual(len(self.api.rows),1)
    def test_same_id_wrong_scope_or_approved_plan_mutation_never_writes_again(self):
        plan=self.lab.preview('incident');operation=str(uuid.uuid4());self.lab.apply('incident',operation,plan['plan_sha256'])
        with self.assertRaises(ContractError):self.lab.apply('reset',operation,plan['plan_sha256'])
        path=self.run/'operations'/operation/'intent.json';value=json.loads(path.read_text());value['lab_uuid']=str(uuid.uuid4());path.write_text(canonical(value))
        with self.assertRaises(ContractError):self.lab.apply('incident',operation,plan['plan_sha256'])
        self.assertEqual(len(self.api.rows),1)
    def test_duplicate_matching_event_and_changed_observation_cannot_advance_pending_head(self):
        plan=self.lab.preview('incident');operation=str(uuid.uuid4());self.api.fail_after_report=True
        with self.assertRaises(OSError):self.lab.apply('incident',operation,plan['plan_sha256'])
        self.api.fail_after_report=False;view=self.lab.resume_preview(operation)
        self.api.rows[0]['at']='2026-10-29T00:00:01.0000000Z'
        with self.assertRaises(ContractError):self.lab.resume(operation,view['observation_sha256'])
        duplicate=copy.deepcopy(self.api.rows[0]);duplicate['id']=2;self.api.rows.append(duplicate)
        fresh=self.lab.resume_preview(operation);self.assertEqual(len(fresh['matching_events']),2)
        with self.assertRaises(ContractError):self.lab.resume(operation,fresh['observation_sha256'])
        self.assertEqual(self.lab.status()['state'],'serving');self.assertEqual(sum(call[0]=='report' for call in self.api.calls),1)
    def test_copy_rechecks_approved_file_hashes_and_never_seals_corrupted_derivative(self):
        self.change(self.lab,'incident');capture,result=self.capture();original=ir.materials;target=self.root/'bad-copy'
        def changed(*args,**kwargs):
            value=original(*args,**kwargs)
            (capture/'application.evtx').write_bytes(b'changed after verification')
            return value
        with patch.object(ir,'materials',side_effect=changed),self.assertRaises(ContractError):
            ir.derive(self.source,capture,target,result['manifest_sha256'],str(uuid.uuid4()),2,self.port(),True)
        self.assertFalse((target/'derivation.complete.json').exists())
        with self.assertRaises((OSError,ValueError,RuntimeError)):self.open(target)
    def test_actual_isolated_materials_cli_produces_no_native_events_or_host_services(self):
        script=self.source/'tools'/'ctflab_ir_course.py';root=self.root/'cli'
        result=subprocess.run([sys.executable,'-I','-B',str(script),'materials','--destination',str(root),
            '--machine-uuid',self.machine,'--generation','1','--port',str(self.port())],capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertFalse(json.loads(result.stdout)['eventlog_written'])
        result=subprocess.run([sys.executable,'-I','-B',str(script),'activate','--run',str(root),'--execute'],capture_output=True,timeout=15)
        self.assertEqual(result.returncode,2);self.assertFalse((root/'owner.json').exists())
        with self.assertRaises(FileExistsError):ir.materials(self.source,root,self.machine,1,self.port(),False)


if __name__=='__main__':unittest.main()
