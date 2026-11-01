"""当前签名许可缓存→预分配课程实例的实际文件/引用映射；不启动VM或连接SSH。"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
from ctflab_remote_course import RemoteCourse
from ctflab_generation_store import GenerationStore
from ctflab_remote import Runner,PROTOCOL
import test_ctflab_remote_assets as upload_tests
import test_ctflab_catalog as catalog_tests


class CourseTests(unittest.TestCase):
    setUp=upload_tests.UploadTests.setUp
    envelope=upload_tests.UploadTests.envelope
    accept=upload_tests.UploadTests.accept
    configured_upload=upload_tests.UploadTests.configured
    begin=upload_tests.UploadTests.begin
    chunk=upload_tests.UploadTests.chunk
    def configured(self):
        self.configured_upload();self.begin();self.chunk(0,self.data);self.uploads.finish(self.upload)
        self.instance=str(uuid.uuid4());self.server=str(uuid.uuid4());self.instance_root=self.root/'assigned'
        self.policy={'schema':1,'server_uuid':self.server,'uploads':self.settings,
            'principals':{'admin':{'role':'administrator','instances':[self.instance],'expires':'2099-01-01T00:00:00Z'},
                'alice':{'role':'student','instances':[self.instance],'expires':'2099-01-01T00:00:00Z'}},
            'instances':{self.instance:{'root':str(self.instance_root),'owner':'alice'}}}
        self.policy_path=self.root/'policy.json';self.policy_path.write_text(canonical(self.policy));self.policy_path.chmod(0o600)
        catalog=catalog_tests.fixture();course=catalog['courses']['course'];course['redistribution']='allowed'
        manifest=course['variants']['x64']['scenario'];manifest['assets']['linux']['sha256']=self.sha
        self.catalog=self.root/'catalog.json';self.catalog.write_text(canonical(catalog));self.catalog.chmod(0o600)
        self.profile=self.root/'profile.json';self.profile.write_text(canonical({'binary':str(self.root/'qemu'),'inventory':str(self.root/'inventory.json'),
            'nodes':{n:{'qmp':16000+i*2,'vnc':16001+i*2} for i,n in enumerate(sorted(manifest['nodes']))},
            'networks':{'inner':17000,'outer':17001}}));self.profile.chmod(0o600)
        self.mapper=RemoteCourse(self.policy_path,'admin',now=lambda:self.now)
        self.args=(self.instance,self.catalog,'course','x64',self.profile,self.source)
    def test_preview_no_files_created_then_provision_pins_originals_and_keeps_initial_generation_zero(self):
        self.configured();before=self.cache.object(self.sha).read_bytes();plan=self.mapper.plan(*self.args)[0]
        self.assertFalse(self.instance_root.exists());self.assertFalse(plan['runtime_verified'])
        result=self.mapper.provision(*self.args,plan['mapping_sha256'])
        self.assertTrue(result['instance_created']);self.assertFalse(result['automatic_start'])
        store=GenerationStore(self.instance_root);self.assertEqual(store.config['instance_uuid'],self.instance)
        self.assertEqual(store.snapshot()['active_generation'],0);self.assertTrue(store.config['cache_references'])
        self.assertEqual(self.cache.object(self.sha).read_bytes(),before)
        self.assertNotIn(self.sha,[r.get('sha256') for r in self.cache.preview_gc()])
        self.assertEqual(json.loads((self.instance_root/'course-selection.json').read_text())['course_id'],'course')
    def test_student_and_wrong_scope_cannot_map_or_provision(self):
        self.configured()
        with self.assertRaises(ContractError):RemoteCourse(self.policy_path,'alice',now=lambda:self.now)
        with self.assertRaises(ContractError):self.mapper.plan(str(uuid.uuid4()),*self.args[1:])
        self.assertFalse(self.instance_root.exists())
    def test_stale_mapping_and_existing_instance_refuse_without_overwriting(self):
        self.configured();plan=self.mapper.plan(*self.args)[0];self.profile.write_text(self.profile.read_text()+' ')
        with self.assertRaises(ContractError):self.mapper.provision(*self.args,plan['mapping_sha256'])
        plan=self.mapper.plan(*self.args)[0];self.mapper.provision(*self.args,plan['mapping_sha256'])
        before=(self.instance_root/'ledger.sqlite3').read_bytes()
        self.assertTrue(self.mapper.provision(*self.args,plan['mapping_sha256'])['already_configured'])
        self.assertEqual((self.instance_root/'ledger.sqlite3').read_bytes(),before)
    def test_teacher_material_or_corrupt_current_object_is_refused(self):
        self.configured();(self.cache.root/'objects'/self.sha).write_bytes(b'corrupt')
        with self.assertRaises(ContractError):self.mapper.plan(*self.args)
        self.assertFalse(self.instance_root.exists())
    def offer(self):
        self.configured()
        self.policy['principals']['teacher']=dict(self.policy['principals']['admin'],role='teacher')
        self.policy['courses']={'web-lab':{'catalog':str(self.catalog),'catalog_sha256':hashlib.sha256(self.catalog.read_bytes()).hexdigest(),
            'course_id':'course','variant_id':'x64','profile':str(self.profile),'profile_sha256':hashlib.sha256(self.profile.read_bytes()).hexdigest(),
            'source':self.source,'instances':[self.instance]}}
        self.policy_path.write_text(canonical(self.policy))
    def rpc(self,action,parameters,principal='admin'):
        return Runner(self.policy,principal,now=lambda:self.now,policy_path=self.policy_path).exchange(
            {'protocol':PROTOCOL,'version':1,'request_id':str(uuid.uuid4()),'server_uuid':self.server,'action':action,'parameters':parameters})['result']
    def test_offer_rpc_only_uses_server_paths_and_requires_current_role_scope(self):
        self.offer();listing=self.rpc('course-list',{},'teacher')
        self.assertEqual(listing['offers'][0]['offer_id'],'web-lab')
        self.assertNotIn(str(self.root),canonical(listing))
        with self.assertRaises(ContractError):self.rpc('course-list',{},'alice')
        for parameters in ({'offer_id':'web-lab','instance_uuid':str(uuid.uuid4())},
                           {'offer_id':'web-lab','instance_uuid':self.instance,'catalog':'/elsewhere'},
                           {'offer_id':'outside','instance_uuid':self.instance}):
            with self.assertRaises(ContractError):self.rpc('course-preview',parameters)
        self.assertFalse(self.instance_root.exists())
    def test_offer_preview_provision_and_original_retry_never_start_or_overwrite(self):
        self.offer();parameters={'offer_id':'web-lab','instance_uuid':self.instance}
        preview=self.rpc('course-preview',parameters)
        self.assertFalse(self.instance_root.exists())
        value=parameters|{'mapping_sha256':preview['mapping_sha256']}
        result=self.rpc('course-provision',value);self.assertFalse(result['automatic_start'])
        files={str(p):p.read_bytes() for p in self.instance_root.rglob('*') if p.is_file()}
        self.assertTrue(self.rpc('course-provision',value)['already_configured'])
        self.assertEqual({str(p):p.read_bytes() for p in self.instance_root.rglob('*') if p.is_file()},files)
        self.assertEqual(GenerationStore(self.instance_root).snapshot()['active_generation'],0)
    def test_offer_rejects_registration_drift_expired_account_and_stale_mapping(self):
        self.offer();parameters={'offer_id':'web-lab','instance_uuid':self.instance}
        preview=self.rpc('course-preview',parameters)
        self.catalog.write_text(self.catalog.read_text()+' ')
        with self.assertRaises(ContractError):self.rpc('course-provision',parameters|{'mapping_sha256':preview['mapping_sha256']})
        self.assertFalse(self.instance_root.exists())
        self.policy['principals']['teacher']['expires']='2000-01-01T00:00:00Z';self.policy_path.write_text(canonical(self.policy))
        with self.assertRaises(ContractError):self.rpc('course-list',{},'teacher')
    def test_interrupted_configuration_can_complete_missing_records_without_replacing_old(self):
        import ctflab_remote_course as module
        from unittest.mock import patch
        self.offer();parameters={'offer_id':'web-lab','instance_uuid':self.instance};preview=self.rpc('course-preview',parameters)
        value=parameters|{'mapping_sha256':preview['mapping_sha256']};record=module.record
        def interrupt(path,item):
            if path.name=='course-selection.json':raise OSError('配置中断夹具')
            return record(path,item)
        with patch.object(module,'record',side_effect=interrupt):
            with self.assertRaises(OSError):self.rpc('course-provision',value)
        before=(self.instance_root/'runtime-profile.json').read_bytes()
        self.assertTrue(self.rpc('course-provision',value)['already_configured'])
        self.assertEqual((self.instance_root/'runtime-profile.json').read_bytes(),before)
        self.assertTrue((self.instance_root/'course-provision-complete.json').is_file())
    def test_replaced_instance_root_or_completion_record_refuses_adoption(self):
        self.offer();parameters={'offer_id':'web-lab','instance_uuid':self.instance};preview=self.rpc('course-preview',parameters)
        value=parameters|{'mapping_sha256':preview['mapping_sha256']};self.rpc('course-provision',value)
        receipt=self.instance_root/'course-provision-complete.json';record=json.loads(receipt.read_text());record['root_identity']=[0,0];receipt.write_text(canonical(record))
        with self.assertRaises(ContractError):self.rpc('course-provision',value)
    def test_handshake_hides_administration_for_students_and_old_policy(self):
        self.offer();self.assertTrue(self.rpc('handshake',{})['course_management'])
        self.assertFalse(self.rpc('handshake',{},'alice')['course_management'])
        del self.policy['courses'];self.policy_path.write_text(canonical(self.policy))
        self.assertFalse(self.rpc('handshake',{})['course_management'])

    def test_policy_drift_and_expired_index_are_not_historical_permission(self):
        self.configured();plan=self.mapper.plan(*self.args)[0];self.policy_path.write_text(self.policy_path.read_text()+' ')
        with self.assertRaises(ContractError):self.mapper.provision(*self.args,plan['mapping_sha256'])
        self.assertFalse(self.instance_root.exists())


if __name__=='__main__':unittest.main()
