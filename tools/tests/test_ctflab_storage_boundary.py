"""专用文件系统容量绑定/漂移与生产调用链；全部内存观察及自有临时文件，不挂载磁盘。"""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
from ctflab_storage_boundary import Native,mounts,enroll,verify,settings,check_profile
from ctflab_generation_store import GenerationStore,digest
from ctflab_windows_recovery import record
from ctflab_windows_native import ProcessIdentity
import test_ctflab_generation_store as generation
import test_ctflab_remote_leases as leases


class Observer:
    def __init__(self):
        self.binding={'capacity_bytes':768*1024**2,'mount_namespace':[4,5],'filesystem_id':100,
            'root_identity':[1,2],'mount_identity':[1,3],'mount':{'id':20,'fstype':'ext4'}}
        self.available=600*1024**2;self.namespace=[4,5];self.calls=0
    def probe(self,*a):self.calls+=1;return copy.deepcopy(self.binding),self.available
    def process_namespace(self,pid):return self.namespace


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.instance=str(uuid.uuid4());self.observer=Observer()
        self.value=enroll('/srv/volume/instance','/srv/volume',self.instance,1024**3,observer=self.observer)
    def test_descriptor_is_read_only_and_pins_capacity_identity_and_namespace(self):
        value=verify(self.value,root='/srv/volume/instance',instance=self.instance,pid=123,observer=self.observer)
        self.assertEqual(value['scope'],'instance-filesystem-data-capacity');self.assertFalse(value['host_storage_modified'])
        self.assertFalse(value['aggregate_project_quota_verified']);self.assertFalse(value['external_cache_or_audit_included'])
        self.observer.available=1
        self.assertEqual(verify(self.value,observer=self.observer)['available_bytes'],1)
    def test_capacity_growth_remount_root_replacement_namespace_drift_all_refuse(self):
        for key,value in [('capacity_bytes',800*1024**2),('root_identity',[1,9]),('filesystem_id',101),('mount_namespace',[4,6])]:
            observer=Observer();observer.binding[key]=value
            with self.assertRaises(ContractError):verify(self.value,observer=observer)
        self.observer.namespace=[4,8]
        with self.assertRaises(ContractError):verify(self.value,pid=321,observer=self.observer)
    def test_wrong_root_instance_descriptor_tamper_and_unbounded_declarations_refuse(self):
        for extra in ({'root':'/srv/other/instance'},{'instance':str(uuid.uuid4())}):
            with self.assertRaises(ContractError):verify(self.value,observer=self.observer,**extra)
        for change in ({'max_bytes':True},{'max_bytes':64*1024**2},{'root':'/srv/volume/../instance'},{'command':'mount'}):
            value=copy.deepcopy(self.value);value.update(change)
            with self.assertRaises(ContractError):settings(value)
        with self.assertRaises(ContractError):enroll('/srv/volume/arbitrary','/srv/volume',self.instance,1024**3,observer=self.observer)
    def test_mountinfo_escapes_and_malformed_duplicate_or_unknown_escape_refuse(self):
        row='20 1 7:9 / /srv/a\\040b rw,nodev,nosuid - ext4 /dev/loop9 rw\n'
        self.assertEqual(mounts(row)[0]['mountpoint'],'/srv/a b')
        for raw in (row+row,row.replace('\\040','\\777'),row.replace(' - ',' '),row.replace('7:9','bad')):
            with self.assertRaises(ContractError):mounts(raw)
    def test_native_adapter_refuses_this_non_linux_host_and_cli_help_is_isolated(self):
        if sys.platform!='linux':
            with self.assertRaises(ContractError):Native()
        with tempfile.TemporaryDirectory() as temp:
            done=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve().parents[1]/'ctflab_storage_boundary.py'),'--help'],
                cwd=temp,capture_output=True,text=True,timeout=5)
            self.assertEqual(done.returncode,0,done.stderr)
            # 沿用driver既有8MiB边界；未声明的较大旧profile不能被本功能缩为1MiB。
            directory=Path(temp).resolve();profile=directory/'runtime-profile.json'
            profile.write_text(canonical({'legacy-fixture':'a'*(1024**2+1)}));profile.chmod(0o600)
            self.assertIsNone(check_profile(directory,self.instance))


class NativeProbeTests(unittest.TestCase):
    def observe(self,raw):
        # 模拟内核读取和FD，不访问这些路径，不改变宿主存储。
        root=Path('/srv/volume/instance');volume=root.parent;device=os.makedev(7,9)
        def info(path):
            if str(path)=='/proc/self/ns/mnt':return SimpleNamespace(st_dev=4,st_ino=5)
            if str(path)=='/dev/loop9':return SimpleNamespace(st_mode=stat.S_IFBLK,st_rdev=device)
            return SimpleNamespace(st_dev=device,st_ino=2 if path==root else 3,st_mode=stat.S_IFDIR|0o700,st_uid=os.getuid())
        stats=SimpleNamespace(f_fsid=123,f_frsize=4096,f_blocks=200000,f_bavail=100000,f_flag=0)
        with patch('ctflab_storage_boundary.guard',side_effect=lambda p:p):
            # autospec使Path实例作为参数保留。
            with patch.object(Path,'stat',autospec=True,side_effect=info),patch.object(Path,'read_text',return_value=raw),\
                 patch('ctflab_storage_boundary.os.open',side_effect=[10,11]),patch('ctflab_storage_boundary.os.close'),\
                 patch('ctflab_storage_boundary.os.fstat',side_effect=[info(volume),info(root)]),\
                 patch('ctflab_storage_boundary.os.fstatvfs',return_value=stats):
                return Native.__new__(Native).probe(root,volume)
    def test_production_probe_reads_whole_device_root_and_statvfs_capacity(self):
        binding,available=self.observe('20 1 7:9 / /srv/volume rw,nodev,nosuid - ext4 /dev/loop9 rw\n')
        self.assertEqual(binding['capacity_bytes'],819200000);self.assertEqual(available,409600000)
    def test_bind_mount_alias_child_mount_other_filesystem_or_missing_guard_options_refuse(self):
        row='20 1 7:9 / /srv/volume rw,nodev,nosuid - ext4 /dev/loop9 rw\n'
        for raw in (row.replace('/ /srv','/subdir /srv'),row.replace('ext4','tmpfs'),row.replace('nodev,',''),
            row+'21 1 7:9 / /alias rw - ext4 /dev/loop9 rw\n',row+'21 20 8:1 / /srv/volume/instance/escape rw - ext4 /dev/sda rw\n'):
            with self.assertRaises(ContractError):self.observe(raw)


class StorageIntegrationTests(unittest.TestCase):
    setUp=generation.GenerationTests.setUp
    configured=leases.LeaseTests.configured
    make_manager=leases.LeaseTests.make_manager
    write_policy=leases.LeaseTests.write_policy
    def configure_boundary(self):
        volume=self.root/'volume';volume.mkdir(mode=0o700)
        self.store=GenerationStore.create(volume/'instance',self.manifest,self.instance,{'linux':self.base})
        self.driver=generation.Driver()
        from ctflab_scenario_coordinator import ScenarioCoordinator
        self.backend=ScenarioCoordinator(self.store,course_id='c01',baseline_id='base',driver=self.driver)
        self.observer=Observer();self.boundary=enroll(str(self.store.root),str(volume),self.instance,1024**3,observer=self.observer)
    def test_prepare_and_reset_copies_check_before_write_and_before_selecting_generation(self):
        self.configure_boundary();record(self.store.root/'runtime-profile.json',{'storage_boundary':self.boundary})
        operation=str(uuid.uuid4());before=digest(self.base)
        def checkpoint(stage):
            if stage.startswith('copied-'):self.observer.binding['filesystem_id']=999
        with patch('ctflab_storage_boundary.Native',return_value=self.observer),self.store.locked():
            self.store.begin(operation,'prepare',1)
            with self.assertRaises(ContractError):self.store.prepare_generation(operation,0,checkpoint=checkpoint)
        self.assertEqual(self.store.snapshot()['active_generation'],0);self.assertEqual(digest(self.base),before)
        self.assertTrue(list((self.store.root/'generations').rglob('disk.qcow2')))
        self.assertTrue(self.store.snapshot()['unresolved']);self.assertEqual(self.driver.calls,[])
    def test_insufficient_unprivileged_available_space_refuses_before_new_generation_directory(self):
        self.configure_boundary();record(self.store.root/'runtime-profile.json',{'storage_boundary':self.boundary});self.observer.available=1
        operation=str(uuid.uuid4())
        with patch('ctflab_storage_boundary.Native',return_value=self.observer),self.store.locked():
            self.store.begin(operation,'prepare',1)
            with self.assertRaises(ContractError):self.store.prepare_generation(operation,0)
        self.assertFalse(list((self.store.root/'generations').iterdir()))
    def test_removing_declared_limit_during_copy_cannot_select_unbounded_generation(self):
        self.configure_boundary();profile=self.store.root/'runtime-profile.json';record(profile,{'storage_boundary':self.boundary})
        operation=str(uuid.uuid4())
        def checkpoint(stage):
            if stage.startswith('copied-'):profile.write_text('{}')
        with patch('ctflab_storage_boundary.Native',return_value=self.observer),self.store.locked():
            self.store.begin(operation,'prepare',1)
            with self.assertRaises(ContractError):self.store.prepare_generation(operation,0,checkpoint=checkpoint)
        self.assertEqual(self.store.snapshot()['active_generation'],0);self.assertTrue(self.store.snapshot()['unresolved'])
        self.assertTrue(list((self.store.root/'generations').rglob('disk.qcow2')))
    def test_lease_charges_declared_whole_filesystem_ceiling_and_retains_binding(self):
        self.configure_boundary();self.configured();(self.store.root/'runtime-profile.json').write_text(canonical({'storage_boundary':self.boundary}))
        with patch('ctflab_storage_boundary.Native',return_value=self.observer):
            with self.assertRaises(ContractError):self.manager.binding(self.instance)
            self.policy['leases']['instances'][self.instance]['disk_reservation_bytes']=1024**3
            binding=self.manager.binding(self.instance)
            self.assertEqual(binding['storage_boundary_sha256'],self.boundary['sha256']);self.assertEqual(binding['disk_reservation_bytes'],1024**3)
            other=str(uuid.uuid4());self.policy['instances'][other]={'root':str(self.store.root/'other'),'owner':'alice'}
            with self.assertRaises(ContractError):self.manager.binding(self.instance)
    def test_qemu_start_storage_drift_refuses_before_observe_or_spawn(self):
        self.configure_boundary()
        from ctflab_qemu_driver import QemuDriver
        profile={'binary':str(self.root/'qemu'),'inventory':str(self.root/'inventory'),'storage_boundary':self.boundary,
            'networks':{'outer':18001,'inner':18002},'nodes':{n:{'qmp':19000+2*i,'vnc':19001+2*i} for i,n in enumerate(self.manifest['nodes'])}}
        driver=QemuDriver(self.store,profile);self.observer.binding['filesystem_id']=999
        with patch('ctflab_storage_boundary.Native',return_value=self.observer),patch.object(driver,'observe') as observe,patch('ctflab_qemu_driver.spawn_worker') as spawn:
            with self.assertRaises(ContractError):driver.start(self.store.plan(1),'client',{}, {'display':'headless','allow_emulation':False})
            observe.assert_not_called();spawn.assert_not_called()
    def test_worker_verifies_storage_before_logger_and_qemu(self):
        self.configure_boundary();root=self.store.root/'runtime';root.mkdir(mode=0o700)
        binary=self.root/'fake-qemu';binary.write_bytes(b'fixture');binary.chmod(0o600)
        disk=self.store.root/'disk.qcow2';disk.write_bytes(b'fixture');disk.chmod(0o600);record(root/'control.lock',{})
        record(root/'launch.json',{'binary':str(binary),'binary_sha256':digest(binary),'argv':[str(binary)],'disk':str(disk),
            'disk_identity':[disk.stat().st_dev,disk.stat().st_ino],'certificates':{},'storage_boundary':self.boundary})
        from ctflab_qemu_driver import worker
        trace=[]
        def checking(*a,**kw):trace.append('storage');return {'fixture':True}
        def spawning(*a,**kw):trace.append('qemu');return SimpleNamespace(pid=123)
        def logger(*a):trace.append('logger');return SimpleNamespace(stdin=io.BytesIO())
        with patch('ctflab_storage_boundary.verify',side_effect=checking),patch('ctflab_bounded_log.spawn',side_effect=logger),\
             patch('ctflab_qemu_driver.subprocess.Popen',side_effect=spawning),patch('ctflab_qemu_driver.fingerprints',return_value={}),\
             patch('ctflab_qemu_driver.native_observe',side_effect=lambda pid:ProcessIdentity(pid,456,str(binary),'running')),\
             patch('ctflab_qemu_driver.spawn_worker'),patch('ctflab_supervisor_fault.wait',return_value=0):worker(root)
        self.assertEqual(trace,['storage','logger','storage','qemu']);self.assertTrue((root/'storage.json').is_file())


if __name__=='__main__':unittest.main()
