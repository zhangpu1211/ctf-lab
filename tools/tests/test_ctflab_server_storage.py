"""公共存储池路由与门禁：临时状态根、原生卷provider替身，不创建/改卷或启动VM。"""
import copy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
from ctflab_generation_store import GenerationStore,digest
from ctflab_remote import validate_policy,Runner,PROTOCOL
from ctflab_macos_storage import enroll
import ctflab_server_storage as storage
from test_ctflab_macos_storage import Observer
from test_ctflab_scenario_v2 import sample


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.mount=self.root/'mount';self.mount.mkdir(mode=0o700);self.pool=self.mount/'instance';self.pool.mkdir(mode=0o700)
        (self.pool/'instances').mkdir(mode=0o700);self.instance=str(uuid.uuid4());self.server=str(uuid.uuid4())
        self.run=self.pool/'instances'/self.instance;self.observer=Observer()
        self.observer.binding['mount']['mountpoint']=str(self.mount)
        self.volume=enroll(self.pool,self.mount,2*1024**3,observer=self.observer)
        self.policy={'schema':1,'server_uuid':self.server,'principals':{'admin':{'role':'administrator',
            'instances':[self.instance],'expires':'2099-01-01T00:00:00Z'}},
            'instances':{self.instance:{'root':str(self.run),'owner':'admin'}}}
        self.policy['storage_pool']=storage.describe(self.policy,'mac',self.volume)
        self.native=patch('ctflab_macos_storage.NativeMac',return_value=self.observer);self.native.start();self.addCleanup(self.native.stop)
    def all_roots(self):
        capacity={'cpus':64,'memory_mb':65536,'disk_reservation_bytes':1024**3}
        self.policy['uploads']={'cache_root':str(self.pool/'cache'),'sources':['https://example.invalid/courses/'],
            'quota_bytes':1024**3,'max_uploads':10}
        self.policy['audit']={'root':str(self.pool/'audit'),'max_attempts':10}
        self.policy['leases']={'root':str(self.pool/'leases'),'capacity':capacity,'limits':{'admin':capacity},
            'instances':{self.instance:{'disk_reservation_bytes':1024**3,'expiry_action':'notify'}},'max_ttl_seconds':60}
    def create_instance(self):
        base=self.root/'base';base.write_bytes(b'new-fixture');manifest=sample();manifest['assets']['linux']['sha256']=digest(base)
        store=GenerationStore.create(self.run,manifest,self.instance,{'linux':base})
        profile=self.run/'runtime-profile.json';profile.write_text(canonical({'fixture':'not-a-QEMU-runtime'}));profile.chmod(0o600)
        return store
    def bind_instance(self):
        value=storage.binding_preview(self.policy,self.instance)
        return storage.bind(self.policy,self.instance,value['binding_sha256'])
    def request(self):return {'protocol':PROTOCOL,'version':1,'request_id':str(uuid.uuid4()),'server_uuid':self.server,
        'action':'handshake','parameters':{}}
    def test_all_declared_roots_including_future_paths_share_only_preconfigured_capacity(self):
        self.all_roots();validate_policy(self.policy)
        value=storage.verify(self.policy)
        self.assertEqual(value['capacity_bytes'],1024**3);self.assertEqual(len(value['members']),4)
        self.assertTrue(value['aggregate_managed_roots_covered']);self.assertFalse(value['all_host_writes_covered'])
        self.assertFalse(value['per_instance_hard_disk_quota']);self.assertFalse(self.run.exists())
    def test_every_public_component_and_instance_must_be_inside_pool(self):
        self.all_roots()
        for component,key in (('uploads','cache_root'),('audit','root'),('leases','root')):
            candidate=copy.deepcopy(self.policy);candidate[component][key]=str(self.root/'outside')
            with self.subTest(component=component),self.assertRaises(ContractError):validate_policy(candidate)
        candidate=copy.deepcopy(self.policy);candidate['instances'][self.instance]['root']=str(self.root/'outside')
        with self.assertRaises(ContractError):validate_policy(candidate)
        candidate=copy.deepcopy(self.policy);candidate['instances'][self.instance]['root']=str(self.pool)
        with self.assertRaises(ContractError):validate_policy(candidate)
    def test_explicit_pool_hash_server_identity_or_capacity_drift_refused(self):
        for key,value in (('server_uuid',str(uuid.uuid4())),('sha256','0'*64),('schema',True)):
            candidate=copy.deepcopy(self.policy);candidate['storage_pool'][key]=value
            with self.subTest(key=key),self.assertRaises(ContractError):storage.settings(candidate)
        self.observer.binding['quota_bytes']+=1
        with self.assertRaises(ContractError):storage.verify(self.policy)
    def test_member_symlink_file_or_mount_device_change_refused(self):
        outside=self.root/'outside';outside.mkdir(mode=0o700);self.run.symlink_to(outside)
        with self.assertRaises(ContractError):storage.verify(self.policy)
        self.run.unlink();self.run.write_bytes(b'not-directory');self.run.chmod(0o600)
        with self.assertRaises(ContractError):storage.verify(self.policy)
        self.run.unlink();self.run.mkdir(mode=0o700)
        original=Path.lstat
        def changed(path,*args,**kwargs):
            result=original(path,*args,**kwargs)
            if path==self.run:
                values=list(result);values[2]+=1;return os.stat_result(values)
            return result
        with patch.object(Path,'lstat',changed),self.assertRaises(ContractError):storage.verify(self.policy)
    def test_extra_archive_destination_is_checked_before_any_write(self):
        with self.assertRaises(ContractError):storage.verify(self.policy,extra={'audit-archive':self.root/'outside'})
        value=storage.verify(self.policy,extra={'audit-archive':self.pool/'archives'/'new'})
        self.assertEqual(value['members']['audit-archive'],'not-created');self.assertFalse((self.pool/'archives').exists())
    def test_each_message_rechecks_pool_before_audit_intent_or_dispatch(self):
        self.all_roots()
        from ctflab_remote_audit import AuditStore
        audit=AuditStore.create(self.policy['audit'],self.server);calls=[]
        runner=Runner(self.policy,'admin',dispatch=lambda *args:calls.append(args))
        runner.exchange(self.request());self.assertEqual(audit.read()['head_seq'],2)
        self.observer.binding['root_identity']=[55,66]
        with self.assertRaises(ContractError):runner.exchange(self.request())
        self.assertEqual(audit.read()['head_seq'],2);self.assertEqual(calls,[])
    def test_preexisting_profile_requires_explicit_registration_not_auto_adoption(self):
        self.create_instance()
        with self.assertRaises((OSError,ValueError,RuntimeError)):storage.verify(self.policy)
        self.assertFalse((self.run/'server-storage.json').exists())
        preview=storage.binding_preview(self.policy,self.instance);self.assertFalse(preview['registered'])
        with self.assertRaises(ContractError):storage.bind(self.policy,self.instance,'0'*64)
        storage.bind(self.policy,self.instance,preview['binding_sha256'])
        self.assertTrue(storage.verify(self.policy)['aggregate_managed_roots_covered'])
    def test_registration_is_idempotent_without_touching_profile_or_original_asset(self):
        self.create_instance();before=(self.run/'runtime-profile.json').read_bytes();base=(self.root/'base').read_bytes()
        self.bind_instance();first=(self.run/'server-storage.json').read_bytes();self.bind_instance()
        self.assertEqual((self.run/'server-storage.json').read_bytes(),first)
        self.assertEqual((self.run/'runtime-profile.json').read_bytes(),before);self.assertEqual((self.root/'base').read_bytes(),base)
        self.assertEqual(storage.registered(self.run)['instance_uuid'],self.instance)
    def test_lost_sidecar_or_ledger_marker_never_falls_back_to_unbounded_backend(self):
        self.create_instance();self.bind_instance();path=self.run/'server-storage.json';raw=path.read_bytes();path.unlink()
        with self.assertRaises((OSError,ValueError,RuntimeError)):storage.check_instance(self.run)
        path.write_bytes(raw);path.chmod(0o600)
        with sqlite3.connect(self.run/'ledger.sqlite3') as db:db.execute("DELETE FROM metadata WHERE key='server-storage'")
        with self.assertRaises(ContractError):storage.check_instance(self.run)
    def test_pending_metadata_registration_can_resume_only_same_context(self):
        self.create_instance();preview=storage.binding_preview(self.policy,self.instance)
        with patch('ctflab_windows_recovery.record',side_effect=OSError('夹具丢失旁车回执')),self.assertRaises(OSError):
            storage.bind(self.policy,self.instance,preview['binding_sha256'])
        self.assertIsNotNone(storage.registered(self.run));self.assertFalse((self.run/'server-storage.json').exists())
        storage.bind(self.policy,self.instance,preview['binding_sha256']);storage.check_instance(self.run)
    def test_changed_profile_or_wrong_context_is_preserved_and_refuses_backend(self):
        self.create_instance();self.bind_instance();path=self.run/'server-storage.json';before=path.read_bytes()
        (self.run/'runtime-profile.json').write_text('{}')
        with self.assertRaises(ContractError):storage.check_instance(self.run)
        self.assertEqual(path.read_bytes(),before)
    def test_prepared_generation_blocks_registration_without_changing_sidecar_or_disks(self):
        store=self.create_instance()
        with store.db(write=True) as db:db.execute("UPDATE metadata SET value='1' WHERE key='active'")
        # 直接置入夹具活动代次；不创建或启动来宾。
        with self.assertRaises((ValueError,RuntimeError)):self.bind_instance()
        self.assertFalse((self.run/'server-storage.json').exists())
    def test_native_volume_is_rechecked_after_members_and_drift_is_not_accepted(self):
        original=self.observer.probe;calls=[]
        def probe(*args):
            calls.append(1)
            if len(calls)==2:self.observer.binding['quota_bytes']+=1
            return original(*args)
        with patch.object(self.observer,'probe',side_effect=probe),self.assertRaises(ContractError):storage.verify(self.policy)
        self.assertEqual(len(calls),2)
    def test_standalone_backend_and_generation_prepare_require_the_registered_pool(self):
        self.create_instance();self.bind_instance();self.observer.binding['quota_bytes']+=1
        import ctflab_desktop_bridge as bridge
        from ctflab_storage_boundary import check_profile
        with patch.object(bridge,'GenerationStore') as constructor,self.assertRaises(ContractError):bridge.backend(self.run)
        constructor.assert_not_called()
        with patch.object(bridge.subprocess,'Popen') as spawn,self.assertRaises(ContractError):bridge.launch(self.run,'execute')
        spawn.assert_not_called()
        with self.assertRaises(ContractError):check_profile(self.run,self.instance)
    def test_multiple_existing_instances_can_be_registered_one_at_a_time(self):
        self.create_instance();other=str(uuid.uuid4());other_root=self.pool/'instances'/other
        original=GenerationStore(self.run);GenerationStore.create(other_root,original.config['manifest'],other,
            {'linux':self.root/'base'})
        path=other_root/'runtime-profile.json';path.write_text('{}');path.chmod(0o600)
        self.policy['instances'][other]={'root':str(other_root),'owner':'admin'}
        self.policy['principals']['admin']['instances'].append(other)
        self.bind_instance()
        with self.assertRaises((OSError,ValueError,RuntimeError)):storage.verify(self.policy)
        preview=storage.binding_preview(self.policy,other);storage.bind(self.policy,other,preview['binding_sha256'])
        self.assertTrue(storage.verify(self.policy)['background_bindings_verified'])
    def test_qemu_launch_binding_survives_manager_exit_and_fails_before_process_spawn_on_drift(self):
        self.create_instance();self.bind_instance();attempt=self.run/'launch-attempt';attempt.mkdir(mode=0o700)
        binding=storage.launch_binding(self.run);spec={'disk':str(self.run/'disk.qcow2'),'server_storage':binding}
        self.assertTrue(storage.verify_launch(spec,attempt)['background_bindings_verified'])
        from ctflab_qemu_driver import worker
        for name,value in (('control.lock',{}),('launch.json',spec)):
            path=attempt/name;path.write_text(canonical(value));path.chmod(0o600)
        self.observer.binding['quota_bytes']+=1
        with patch('ctflab_qemu_driver.subprocess.Popen') as spawn,self.assertRaises(ContractError):worker(attempt)
        spawn.assert_not_called();self.assertFalse((attempt/'start.intent.json').exists())
    def test_scope_changed_launch_or_missing_registration_never_falls_back(self):
        self.create_instance();self.bind_instance();binding=storage.launch_binding(self.run)
        spec={'disk':str(self.run/'disk'),'server_storage':dict(binding,context_sha256='0'*64)}
        with self.assertRaises(ContractError):storage.verify_launch(spec,self.run/'attempt')
        with self.assertRaises(ContractError):storage.verify_launch(dict(spec,server_storage=binding),self.root/'outside')
        with sqlite3.connect(self.run/'ledger.sqlite3') as db:db.execute("DELETE FROM metadata WHERE key='server-storage'")
        with self.assertRaises(ContractError):storage.verify_launch(dict(spec,server_storage=binding),self.run/'attempt')
    def test_boolean_sidecar_schema_is_not_treated_as_integer_one(self):
        self.create_instance();self.bind_instance();path=self.run/'server-storage.json';value=json.loads(path.read_text())
        value['schema']=True;path.write_text(canonical(value))
        with self.assertRaises(ContractError):storage.check_instance(self.run)
    def test_positive_isolated_cli_uses_explicit_fake_volume_provider_and_only_own_temporary_state(self):
        self.create_instance();path=self.root/'policy.json';path.write_text(canonical(self.policy));path.chmod(0o600)
        tools=Path(__file__).resolve().parents[1]
        program="import sys,json;sys.path.insert(0,sys.argv[1]);import ctflab_macos_storage as m;import ctflab_server_storage as s;"+\
            "binding=json.loads(sys.argv[2]);O=type('O',(),{'probe':lambda self,*args:(binding,1024)});m.NativeMac=O;raise SystemExit(s.main(sys.argv[3:]))"
        def run(*args):return subprocess.run([sys.executable,'-I','-B','-c',program,str(tools),canonical(self.observer.binding),
            *args,'--policy',str(path)],capture_output=True,timeout=15)
        result=run('bind-preview','--instance',self.instance);self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads(result.stdout)
        result=run('bind','--instance',self.instance,'--binding-sha256',value['binding_sha256'])
        self.assertEqual(result.returncode,2);self.assertIsNone(storage.registered(self.run))
        result=run('bind','--instance',self.instance,'--binding-sha256',value['binding_sha256'],'--execute')
        self.assertEqual(result.returncode,0,result.stderr)
        result=run('inspect');self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['background_bindings_verified'])
    def test_legacy_policy_and_unregistered_instance_keep_original_behavior(self):
        policy=copy.deepcopy(self.policy);policy.pop('storage_pool');self.assertIsNone(storage.verify(policy))
        self.create_instance();self.assertIsNone(storage.check_instance(self.run))
    def test_readonly_isolated_cli_rejects_absent_pool_and_never_writes_policy(self):
        path=self.root/'policy.json';policy=copy.deepcopy(self.policy);policy.pop('storage_pool')
        path.write_text(canonical(policy));path.chmod(0o600);before=path.read_bytes()
        script=Path(__file__).resolve().parents[1]/'ctflab_server_storage.py'
        result=subprocess.run([sys.executable,'-I','-B',str(script),'inspect','--policy',str(path)],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,2);self.assertFalse(json.loads(result.stdout)['host_storage_modified'])
        self.assertEqual(path.read_bytes(),before)


class CourseIntegrationTests(unittest.TestCase):
    from test_ctflab_remote_course import CourseTests
    setUp=CourseTests.setUp
    configured=CourseTests.configured
    envelope=CourseTests.envelope
    accept=CourseTests.accept
    configured_upload=CourseTests.configured_upload
    begin=CourseTests.begin
    chunk=CourseTests.chunk
    def test_real_course_provision_registers_pool_for_detached_backend_without_starting(self):
        from ctflab_remote_course import RemoteCourse
        self.configured();observer=Observer();volume=enroll(self.root,self.root.parent,2*1024**3,observer=observer)
        self.policy['storage_pool']=storage.describe(self.policy,'mac',volume)
        self.policy_path.write_text(canonical(self.policy))
        with patch('ctflab_macos_storage.NativeMac',return_value=observer):
            mapper=RemoteCourse(self.policy_path,'admin',now=lambda:self.now);plan=mapper.plan(*self.args)[0]
            result=mapper.provision(*self.args,plan['mapping_sha256']);self.assertFalse(result['automatic_start'])
            proof=storage.check_instance(self.instance_root)
            self.assertTrue(proof['aggregate_managed_roots_covered'])
            self.assertEqual(GenerationStore(self.instance_root).snapshot()['active_generation'],0)
            self.assertFalse(storage.registered(self.instance_root) is None)
            mapper.provision(*self.args,plan['mapping_sha256'])


if __name__=='__main__':unittest.main()
