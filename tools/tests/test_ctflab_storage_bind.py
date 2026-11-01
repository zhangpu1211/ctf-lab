"""绑定空实例、保存原字节及中断恢复；真实临时文件/SQLite，卷观察替身。"""
import copy
import json
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError
from ctflab_generation_store import GenerationStore,digest
from ctflab_storage_boundary import enroll,check_profile
import ctflab_storage_bind as binding
import test_ctflab_generation_store as fixtures


class BindTests(unittest.TestCase):
    def setUp(self):
        fixtures.GenerationTests.setUp(self)
        volume=self.root/'volume';volume.mkdir(mode=0o700)
        self.store=GenerationStore.create(volume/'instance',self.manifest,self.instance,{'linux':self.base})
        profile={'binary':str(self.root/'qemu'),'inventory':str(self.root/'inventory.json'),
            'nodes':{n:{'qmp':19000+2*i,'vnc':19001+2*i} for i,n in enumerate(self.manifest['nodes'])},
            'networks':{'outer':18001,'inner':18002}}
        self.path=self.store.root/'runtime-profile.json';self.original=(json.dumps(profile,indent=4)+'\n').encode()
        self.path.write_bytes(self.original);self.path.chmod(0o600)
        class Observer:
            def probe(self,*args):return {'capacity_bytes':4*1024**3,'filesystem_id':17},3*1024**3
        self.observer=Observer();self.policy=enroll(self.store.root,volume,self.instance,4*1024**3,observer=self.observer)
        self.operation=str(uuid.uuid4())
    def preview(self):return binding.preview(self.store.root,'linux',self.policy,observer=self.observer)
    def apply(self,preview):return binding.apply(self.store.root,'linux',self.policy,self.operation,preview['plan_sha256'],observer=self.observer)
    def test_preview_is_readonly_apply_preserves_exact_original_and_prepares_only_synthetic_disks(self):
        preview=self.preview();self.assertEqual(self.path.read_bytes(),self.original)
        self.assertEqual(list(self.store.root.glob('storage-bind.*')),[])
        result=self.apply(preview);self.assertEqual((self.store.root/result['backup']).read_bytes(),self.original)
        self.assertFalse(result['host_storage_modified']);self.assertFalse(result['vm_started'])
        self.assertEqual(self.apply(preview),result)
        with patch('ctflab_storage_boundary.Native',return_value=self.observer):
            self.assertEqual(check_profile(self.store.root,self.instance)['binding_sha256'],self.policy['sha256'])
            with self.store.locked():
                operation=str(uuid.uuid4());self.store.begin(operation,'prepare',0)
                value=self.store.prepare_generation(operation,0)
        self.assertEqual(value['state'],'prepared');self.assertEqual(digest(self.base),self.manifest['assets']['linux']['sha256'])
    def test_interruption_after_profile_publication_blocks_prepare_and_same_request_only_finishes_receipt(self):
        preview=self.preview();original=binding.preserved_file
        def failed(root,role,expected,raw=None):
            if role=='result':raise OSError('合成收据写入中断')
            return original(root,role,expected,raw)
        with patch.object(binding,'preserved_file',side_effect=failed):
            with self.assertRaises(OSError):self.apply(preview)
        info=self.path.stat();sha=digest(self.path)
        with self.assertRaises((OSError,ContractError)):check_profile(self.store.root,self.instance)
        with self.store.locked():
            with self.assertRaises((OSError,ContractError)):self.store.begin(str(uuid.uuid4()),'prepare',0)
        self.assertEqual(self.store.snapshot()['unresolved'],[])
        self.apply(preview)
        self.assertEqual(digest(self.path),sha);self.assertEqual(self.path.stat().st_ino,info.st_ino)
    def test_partial_backup_is_kept_and_recovery_writes_a_new_complete_backup(self):
        preview=self.preview();original=binding.preserved_file;bad=self.store.root/('storage-bind.before.'+str(uuid.uuid4())+'.json')
        def failed(root,role,expected,raw=None):
            if role=='before':bad.write_bytes(b'partial');bad.chmod(0o600);raise OSError('合成磁盘写入中断')
            return original(root,role,expected,raw)
        with patch.object(binding,'preserved_file',side_effect=failed):
            with self.assertRaises(OSError):self.apply(preview)
        self.assertEqual(self.path.read_bytes(),self.original)
        result=self.apply(preview);self.assertEqual(bad.read_bytes(),b'partial')
        self.assertNotEqual(result['backup'],bad.name)
    def test_changed_runtime_profile_or_plan_is_refused_without_overwrite(self):
        preview=self.preview();self.path.write_bytes(self.original+b' ')
        with self.assertRaises(ContractError):self.apply(preview)
        self.assertEqual(self.path.read_bytes(),self.original+b' ')
        self.assertFalse((self.store.root/'storage-bind.intent.json').exists())
    def test_unclosed_binding_cannot_be_bypassed_by_removing_policy(self):
        preview=self.preview();self.apply(preview);self.path.write_bytes(self.original)
        with patch('ctflab_storage_boundary.Native',return_value=self.observer):
            with self.assertRaises(ContractError):check_profile(self.store.root,self.instance)

    def test_deleting_whole_profile_cannot_downgrade_bound_instance_to_legacy(self):
        preview=self.preview();self.apply(preview);self.path.rename(self.path.with_suffix('.preserved'))
        with self.assertRaises(ContractError):check_profile(self.store.root,self.instance)
    def test_forged_intent_plan_digest_does_not_launder_metadata(self):
        preview=self.preview();original=binding.preserved_file
        with patch.object(binding,'preserved_file',side_effect=OSError('合成中断')):
            with self.assertRaises(OSError):self.apply(preview)
        path=self.store.root/'storage-bind.intent.json';value=json.loads(path.read_text())
        value['plan']['before_sha256']='a'*64;path.write_text(json.dumps(value))
        with self.assertRaises(ContractError):self.apply(preview)
        self.assertEqual(self.path.read_bytes(),self.original)
    def test_prepared_pending_or_busy_instance_cannot_bind(self):
        with self.store.locked():
            with self.assertRaises(ContractError):self.preview()
        with self.store.locked():self.store.begin(str(uuid.uuid4()),'prepare',0)
        with self.assertRaises(ContractError):self.preview()
        self.assertFalse((self.store.root/'storage-bind.intent.json').exists())
    def test_pending_desktop_contract_refuses_before_writing_any_binding(self):
        from ctflab_local_service import LocalService
        from ctflab_local_adapter import process_actor
        service=LocalService.create(self.store.root/'desktop-contract')
        service.submit({'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),'operation':'prepare',
            'instance_uuid':self.instance,'expected_generation':None,'expected_state_revision':None,
            'idempotency_key':str(uuid.uuid4()),'parameters':{'course_id':'c01','baseline_id':'base'}},process_actor())
        with self.assertRaises(ContractError):self.preview()
        self.assertFalse((self.store.root/'storage-bind.intent.json').exists())

    def test_status_is_local_metadata_only_and_distinguishes_completion(self):
        with patch.object(self.observer,'probe',side_effect=AssertionError('状态不能核验卷')):
            self.assertEqual(binding.status(self.store.root)['state'],'no-storage-binding-record')
        self.apply(self.preview())
        with patch.object(self.observer,'probe',side_effect=AssertionError('状态不能核验卷')):
            value=binding.status(self.store.root)
        self.assertEqual(value['state'],'bound-record-verified');self.assertFalse(value['native_volume_rechecked'])


if __name__=='__main__':unittest.main()
