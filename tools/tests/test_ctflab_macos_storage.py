"""Mac APFS只读解析与旧运行器接入；原生读取/替身分列，不创建卷或启动VM。"""
import copy
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if os.name!='nt':import ctflab
from ctflab_contract import ContractError,canonical
from ctflab_macos_storage import StatFS64,kernel_mounts,apfs_quota,enroll,settings,verify,check_state,NativeMac,POLICY


class Observer:
    def __init__(self):
        self.binding={'quota_bytes':1024**3,'volume_uuid':str(uuid.uuid4()),'container_uuid':str(uuid.uuid4()),
            'device':'disk9s1','root_identity':[1,2],'mount_identity':[1,3],
            'mount':{'fsid':[1,2],'fstype':'apfs','mountpoint':'/Volumes/Lab','source':'/dev/disk9s1','flags':0x18}}
        self.available=512*1024**2
    def probe(self,*a):return copy.deepcopy(self.binding),self.available


class APFSTests(unittest.TestCase):
    def setUp(self):
        self.volume=str(uuid.uuid4());self.container=str(uuid.uuid4())
        self.mount={'mountpoint':'/Volumes/Lab','source':'/dev/disk9s1'}
        self.info={'FilesystemType':'apfs','MountPoint':'/Volumes/Lab','VolumeUUID':self.volume.upper(),
            'DeviceIdentifier':'disk9s1','APFSContainerReference':'disk9'}
        self.v={'APFSVolumeUUID':self.volume.upper(),'DeviceIdentifier':'disk9s1','CapacityQuota':1024**3,
            'CapacityInUse':256*1024**2,'Locked':False,'Roles':[]}
        self.listing={'Containers':[{'ContainerReference':'disk9','APFSContainerUUID':self.container.upper(),'Volumes':[self.v]}]}
    def test_generic_instance_inherits_enrolled_parent_capacity_and_rejects_escape_or_drift(self):
        from ctflab_storage_boundary import check_mac_profile,check_profile
        with tempfile.TemporaryDirectory() as temporary:
            mount=Path(temporary).resolve();owner=mount/'state';owner.mkdir(mode=0o700)
            parent=owner/'generic-instances';parent.mkdir(mode=0o700);root=parent/str(uuid.uuid4());root.mkdir(mode=0o700)
            observer=Observer();observer.binding['mount']['mountpoint']=str(mount)
            policy=enroll(owner,mount,2*1024**3,observer=observer)
            profile={'host':'darwin-arm64','macos_storage':policy}
            path=root/'runtime-profile.json';path.write_text(canonical(profile));path.chmod(0o600)
            result=check_profile(root,str(uuid.uuid4()),observer=observer)
            self.assertEqual(result['binding_sha256'],policy['sha256']);self.assertEqual(result['available_bytes'],observer.available)
            outside=mount/'other';outside.mkdir(mode=0o700)
            with self.assertRaises(ContractError):check_mac_profile(profile,outside,observer=observer)
            observer.binding['root_identity']=[5,6]
            with self.assertRaises(ContractError):check_profile(root,str(uuid.uuid4()),observer=observer)

    def test_quota_is_read_from_volume_not_shared_container_capacity_or_free_space(self):
        self.listing['Containers'][0]['CapacityCeiling']=10*1024**4
        value,free=apfs_quota(self.info,self.listing,self.mount)
        self.assertEqual(value['quota_bytes'],1024**3);self.assertEqual(free,768*1024**2)
        self.assertEqual(value['volume_uuid'],self.volume)
    def test_absent_unlimited_changed_volume_system_role_snapshot_or_locked_refuse(self):
        for change in ({'CapacityQuota':0},{'CapacityQuota':None},{'CapacityQuota':True},
            {'Roles':['Data']},{'Roles':['System']},{'Locked':True},{'APFSVolumeUUID':str(uuid.uuid4())}):
            old=copy.deepcopy(self.v);self.v.update(change)
            with self.assertRaises(ContractError):apfs_quota(self.info,self.listing,self.mount)
            self.v.clear();self.v.update(old)
        self.info['APFSSnapshot']=True
        with self.assertRaises(ContractError):apfs_quota(self.info,self.listing,self.mount)
    def test_duplicate_volume_wrong_device_and_wrong_container_refuse(self):
        self.listing['Containers'][0]['Volumes'].append(copy.deepcopy(self.v))
        with self.assertRaises(ContractError):apfs_quota(self.info,self.listing,self.mount)
        self.listing['Containers'][0]['Volumes'].pop();self.mount['source']='/dev/disk8s1'
        with self.assertRaises(ContractError):apfs_quota(self.info,self.listing,self.mount)
    def test_descriptor_drift_root_substitution_and_tampering_refuse(self):
        observer=Observer();value=enroll('/Volumes/Lab/state','/Volumes/Lab',2*1024**3,observer=observer)
        self.assertEqual(verify(value,'/Volumes/Lab/state',observer=observer)['scope'],'whole-dedicated-apfs-volume')
        for field,item in [('quota_bytes',2*1024**3),('root_identity',[1,9]),('volume_uuid',str(uuid.uuid4())),('device','disk10s1')]:
            saved=copy.deepcopy(observer.binding);observer.binding[field]=item
            with self.assertRaises(ContractError):verify(value,'/Volumes/Lab/state',observer=observer)
            observer.binding=saved
        bad=copy.deepcopy(value);bad['max_bytes']=True
        with self.assertRaises(ContractError):settings(bad)
        with self.assertRaises(ContractError):verify(value,'/Volumes/Lab/other',observer=observer)
    def test_real_mac_mount_table_abi_read_only_without_volume_or_quota_operations(self):
        if sys.platform!='darwin':self.skipTest('仅Mac原生只读接口')
        self.assertEqual(ctypes.sizeof(StatFS64),2168);rows=kernel_mounts()
        self.assertTrue(rows);self.assertTrue(any(r['mountpoint']=='/' for r in rows))
        self.assertTrue(all(set(row)=={'fsid','fstype','mountpoint','source','flags'} for row in rows))
    def test_cli_isolated_help_has_inspect_only(self):
        with tempfile.TemporaryDirectory() as temp:
            done=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve().parents[1]/'ctflab_macos_storage.py'),'--help'],
                cwd=temp,capture_output=True,text=True,timeout=5)
            self.assertEqual(done.returncode,0,done.stderr);self.assertIn('inspect',done.stdout);self.assertNotIn('addVolume',done.stdout)


@unittest.skipIf(os.name=='nt','Mac旧CLI使用fcntl；Windows只验证APFS解析/拒绝边界')
class MacRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.volume=Path(self.tmp.name).resolve()
        self.root=self.volume/'state';self.root.mkdir(mode=0o700);self.manager=ctflab.LabManager(self.root)
        self.observer=Observer();self.value=enroll(self.root,self.volume,2*1024**3,observer=self.observer)
        self.path=self.volume/'policy.json';self.path.write_text(canonical(self.value));self.path.chmod(0o600)
        self.patcher=patch('ctflab_macos_storage.NativeMac',return_value=self.observer);self.patcher.start();self.addCleanup(self.patcher.stop)
    def configured(self):return self.manager.configure_storage_limit(self.path,self.value['sha256'])
    def test_existing_state_is_not_automatically_configured_and_storage_is_read_only(self):
        with patch.object(ctflab,'available_profiles',return_value=[]):report=self.manager.storage_report()
        self.assertEqual(report['capacity_limit']['state'],'not-configured');self.assertFalse((self.root/POLICY).exists())
        with self.manager.operation_lock('旧路径'):pass
        self.assertFalse((self.root/POLICY).exists())
    def test_explicit_empty_root_enrollment_persists_original_bytes_once_and_reports_capacity(self):
        result=self.configured();self.assertFalse(result['quota_modified']);self.assertFalse(result['assets_migrated'])
        self.assertEqual((self.root/POLICY).read_bytes(),self.path.read_bytes())
        with self.assertRaises(ctflab.CTFLabError):self.configured()
        with patch.object(ctflab,'available_profiles',return_value=[]):report=self.manager.storage_report()
        self.assertEqual(report['capacity_limit']['quota_bytes'],1024**3)
    def test_existing_assets_and_wrong_review_digest_refuse_without_migration_or_overwrite(self):
        asset=self.root/'user-data';asset.write_bytes(b'preserve-user-input')
        with self.assertRaises(ctflab.CTFLabError):self.configured()
        self.assertEqual(asset.read_bytes(),b'preserve-user-input');self.assertFalse((self.root/POLICY).exists())
        empty=self.volume/'other';empty.mkdir(mode=0o700);manager=ctflab.LabManager(empty)
        with self.assertRaises(ctflab.CTFLabError):manager.configure_storage_limit(self.path,'a'*64)
        self.assertFalse((empty/POLICY).exists())
    def test_quota_drift_refuses_import_and_snapshot_before_disk_side_effects(self):
        self.configured();self.observer.binding['quota_bytes']+=1
        with patch.object(self.manager,'_import_image_unlocked') as importing:
            with self.assertRaises(ctflab.CTFLabError):self.manager.import_image('smoke','unused')
            importing.assert_not_called()
        with patch.object(self.manager,'_instance_files') as snapshot:
            with self.assertRaises(ctflab.CTFLabError):self.manager.snapshot_create('smoke','sample')
            snapshot.assert_not_called()
    def test_operation_checks_after_mutation_keeps_partial_and_releases_lock_on_drift(self):
        self.configured();partial=self.root/'partial'
        with self.assertRaises(ctflab.CTFLabError):
            with self.manager.operation_lock('合成复制'):
                partial.write_bytes(b'preserved-partial');self.observer.binding['root_identity']=[1,99]
        self.assertEqual(partial.read_bytes(),b'preserved-partial');self.assertEqual(self.manager._operation_lock_depth,0)
        with self.manager.operation_lock('停止控制',storage_check=False):pass
    def test_removed_policy_is_refused_during_operation_before_any_spawn(self):
        self.configured()
        with self.assertRaises(ctflab.CTFLabError):
            with self.manager.operation_lock('合成启动'):
                (self.root/POLICY).rename(self.volume/'retained-policy.json')
                with patch.object(ctflab.subprocess,'Popen') as spawn:
                    try:self.manager._storage_guard()
                    finally:spawn.assert_not_called()
        self.assertTrue((self.volume/'retained-policy.json').is_file())
    def test_storage_unverified_is_visible_and_stop_control_not_gated_by_volume(self):
        self.configured();self.observer.binding['device']='disk10s1'
        with patch.object(ctflab,'available_profiles',return_value=[]):report=self.manager.storage_report()
        self.assertEqual(report['capacity_limit']['state'],'unverified')
        with patch.object(ctflab,'available_profiles',return_value=[]),patch.object(self.manager,'running_states',return_value=[]):self.manager.stop([])
    def test_parser_has_explicit_storage_limit_command_without_changing_update(self):
        args=ctflab.build_parser().parse_args(['storage-limit','--policy',str(self.path),'--policy-sha256',self.value['sha256']])
        self.assertEqual(args.command,'storage-limit');self.assertEqual(args.policy,self.path)
    def test_full_disk_during_lock_metadata_cleanup_preserves_original_error_and_unlocks(self):
        self.configured();original=Path.open
        class FailingCleanup:
            def __init__(self,stream):self.stream=stream;self.flushes=0
            def __getattr__(self,name):return getattr(self.stream,name)
            def flush(self):
                self.flushes+=1
                if self.flushes==2:raise OSError(28,'合成磁盘满，仅锁诊断元数据')
                self.stream.flush()
            def close(self):
                self.stream.close();raise OSError(28,'合成关闭时刷新失败')
        def opening(path,*args,**kw):
            stream=original(path,*args,**kw)
            return FailingCleanup(stream) if path.name=='operations.lock' else stream
        with patch.object(Path,'open',autospec=True,side_effect=opening):
            with self.assertRaisesRegex(RuntimeError,'保留原失败'):
                with self.manager.operation_lock('合成失败'):raise RuntimeError('保留原失败')
        with self.manager.operation_lock('核验释放',timeout_seconds=.1):pass
        self.assertEqual(self.manager._operation_lock_depth,0)


if __name__=='__main__':unittest.main()
