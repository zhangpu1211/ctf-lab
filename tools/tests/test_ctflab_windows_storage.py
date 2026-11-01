"""专用NTFS卷只读API/容量模型；Win32与ACL均为替身，不访问真实卷。"""
import copy
import ctypes
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ctflab_windows_storage as volume
from ctflab_contract import ContractError
from ctflab_windows_native import DWORD
import ctflab_qemu_driver as driver
import test_ctflab_qemu_driver as fixtures

GUID='\\\\?\\Volume{11111111-1111-1111-1111-111111111111}\\'
SYSTEM='\\\\?\\Volume{22222222-2222-2222-2222-222222222222}\\'


def set_value(pointer,kind,value):ctypes.cast(pointer,ctypes.POINTER(kind))[0]=value


class Kernel:
    def __init__(self):
        self.closed=[];self.opened=[];self.aliases=['E:\\'];self.system=SYSTEM;self.extra=False
        self.calls=0;self.drift=False;self.reparse=False;self.fs='NTFS'
    def GetDriveTypeW(self,path):return 3
    def GetVolumePathNameW(self,path,buffer,size):buffer.value='E:\\' if path[0].upper()=='E' else 'C:\\';return 1
    def GetVolumeNameForVolumeMountPointW(self,path,buffer,size):buffer.value=GUID if path[0].upper()=='E' else self.system;return 1
    def GetWindowsDirectoryW(self,buffer,size):buffer.value='C:\\Windows';return len(buffer.value)
    def GetVolumePathNamesForVolumeNameW(self,guid,buffer,size,needed):
        raw='\0'.join(self.aliases)+'\0\0'
        for index,char in enumerate(raw):buffer[index]=char
        set_value(needed,DWORD,len(raw));return 1
    def GetVolumeInformationW(self,path,label,size,serial,component,flags,fs,maximum):
        set_value(serial,DWORD,0x1234);set_value(component,DWORD,255);set_value(flags,DWORD,0);fs.value=self.fs;return 1
    def CreateFileW(self,*args):self.opened.append(args);return len(self.opened)
    def CloseHandle(self,handle):self.closed.append(handle);return 1
    def GetFileInformationByHandle(self,handle,pointer):
        value=ctypes.cast(pointer,ctypes.POINTER(volume.FileInfo)).contents
        value.attributes=0x10|(0x400 if self.reparse else 0);value.serial=0x1234;value.index_low=handle;return 1
    def GetFinalPathNameByHandleW(self,handle,buffer,size,flags):
        assert flags==1;buffer.value=GUID+('instance' if handle==2 else '');return len(buffer.value)
    def DeviceIoControl(self,handle,code,unused,size,pointer,maximum,returned,last):
        assert code==0x90064 and handle==3;self.calls+=1
        value=ctypes.cast(pointer,ctypes.POINTER(volume.NtfsData)).contents
        value.SerialNumber=0x1234;value.TotalClusters=1024**2+(int(self.drift and self.calls>=3))
        value.FreeClusters=700000;value.BytesPerSector=512;value.BytesPerCluster=4096
        set_value(returned,DWORD,ctypes.sizeof(volume.NtfsData));return 1
    def GetDiskFreeSpaceExW(self,path,available,total,free):
        set_value(available,ctypes.c_uint64,32*1024**2)
        # 刻意用更小的用户配额总量，不能把它说成整卷64MiB。
        set_value(total,ctypes.c_uint64,64*1024**2);set_value(free,ctypes.c_uint64,2*1024**3);return 1


class VolumeTests(unittest.TestCase):
    def setUp(self):
        self.native=volume.Native.__new__(volume.Native);self.native.kernel=Kernel();self.guards=[]
        self.native.guard=self.guards.append;self.instance=str(uuid.uuid4())
    def probe(self):
        with patch.object(volume.os,'listdir',return_value=['instance','System Volume Information']):
            return self.native.probe('E:\\instance','E:\\')
    def test_api_reads_actual_cluster_capacity_not_smaller_caller_quota(self):
        binding,available=self.probe()
        self.assertEqual(ctypes.sizeof(volume.NtfsData),96);self.assertEqual(ctypes.sizeof(volume.FileInfo),52)
        self.assertEqual(binding['capacity_bytes'],4*1024**3);self.assertEqual(available,32*1024**2)
        self.assertEqual(self.native.kernel.closed,[1,2,3]);self.assertEqual(len(self.guards),4)
        for args in self.native.kernel.opened[:2]:self.assertEqual((args[1],args[2],args[4],args[5]),(0x80,7,3,0x2200000))
        self.assertEqual(self.native.kernel.opened[2],(GUID[:-1],0,7,None,3,0,None))
    def test_small_user_quota_cannot_enroll_large_volume_as_small_capacity(self):
        with patch.object(volume.os,'listdir',return_value=['instance']):
            with self.assertRaises(ContractError):volume.enroll('E:\\instance','E:\\',self.instance,64*1024**2,observer=self.native)
        self.assertEqual(self.native.kernel.closed,[1,2,3])
    def test_system_volume_extra_alias_other_root_content_and_non_ntfs_refused(self):
        for case in ('system','alias','content','fs'):
            self.setUp();names=['instance']
            if case=='system':self.native.kernel.system=GUID
            elif case=='alias':self.native.kernel.aliases.append('F:\\')
            elif case=='content':names.append('unrelated-user-data')
            else:self.native.kernel.fs='ReFS'
            with self.subTest(case=case),patch.object(volume.os,'listdir',return_value=names),self.assertRaises(ContractError):
                self.native.probe('E:\\instance','E:\\')
            self.assertEqual(self.native.kernel.opened,[])
    def test_reparse_or_geometry_drift_closes_all_retained_handles(self):
        for case in ('reparse','drift'):
            self.setUp();setattr(self.native.kernel,case,True)
            with self.assertRaises(ContractError):self.probe()
            self.assertEqual(self.native.kernel.closed,[1,2] if case=='reparse' else [1,2,3])
    def test_unc_ads_traversal_nested_root_and_wrong_drive_rejected(self):
        for root,mount in [('\\\\server\\share\\instance','\\\\server\\share\\'),
            ('E:\\instance:stream','E:\\'),('E:\\x\\..\\instance','E:\\'),
            ('E:\\other\\instance','E:\\'),('E:\\instance','F:\\')]:
            with self.subTest(root=root),self.assertRaises((ContractError,RuntimeError)):volume.locations(root,mount)
    def test_descriptor_digest_and_fresh_observation_are_required(self):
        class Observer:
            def __init__(self):self.binding={'capacity_bytes':1024**3,'serial64':'a'}
            def probe(self,*args):return copy.deepcopy(self.binding),512*1024**2
        observer=Observer();value=volume.enroll('E:\\instance','E:\\',self.instance,2*1024**3,observer=observer)
        self.assertFalse(volume.verify(value,observer=observer)['aggregate_project_quota_verified'])
        observer.binding['serial64']='b'
        with self.assertRaises(ContractError):volume.verify(value,observer=observer)
        with self.assertRaises(ContractError):volume.settings(dict(value,max_bytes=3*1024**3))
    def test_non_windows_host_refuses_before_dll_access(self):
        with patch.object(volume.os,'name','posix'):
            with self.assertRaises(ContractError):volume.Native()

    def test_policy_cannot_allocate_same_volume_or_ancestor_to_another_instance(self):
        other=str(uuid.uuid4())
        for path in ('E:\\another-instance','e:\\','E:\\instance\\nested'):
            with self.assertRaises(ContractError):volume.require_exclusive_volume('E:\\',self.instance,{other:{'root':path}})
        volume.require_exclusive_volume('E:\\',self.instance,{other:{'root':'F:\\instance'}})


class DriverTests(unittest.TestCase):
    setUp=fixtures.DriverTests.setUp
    setup_driver=fixtures.DriverTests.setup_driver
    context=fixtures.DriverTests.context
    run_action=fixtures.DriverTests.run_action
    attempt=fixtures.DriverTests.attempt
    def policy(self):
        class Observer:
            def probe(self,*args):return {'capacity_bytes':1024**3},512*1024**2
        return volume.enroll('E:\\instance','E:\\',self.instance,2*1024**3,observer=Observer())
    def test_optional_profile_compiles_but_non_windows_start_does_not_observe_or_spawn(self):
        self.setup_driver();self.profile['windows_storage']=self.policy();driver.validate_profile(self.plan,self.profile)
        with patch.object(driver.os,'name','posix'),patch.object(self.real,'observe',side_effect=AssertionError('不能观察或派生')):
            with self.assertRaises(ContractError):self.real.start(self.plan,'server',self.paths,{'display':'headless','allow_emulation':False})
    def test_old_launch_cannot_be_upgraded_by_adding_volume_policy(self):
        self.setup_driver();attempt=self.attempt();self.profile['windows_storage']=self.policy()
        with self.assertRaises(ContractError):self.real.binding(self.plan,'server',self.paths,attempt)
    def test_multiple_storage_backends_are_refused(self):
        self.setup_driver();self.profile.update(windows_storage=self.policy(),storage_boundary={})
        with self.assertRaises(ContractError):driver.validate_profile(self.plan,self.profile)

    def test_worker_checks_windows_storage_before_observer_logger_or_qemu(self):
        from ctflab_generation_store import private_directory,digest
        from ctflab_windows_recovery import record
        self.setup_driver();root=self.root/'worker';private_directory(root)
        binary=self.root/'fake-qemu';binary.write_bytes(b'fixture');binary.chmod(0o600)
        disk=self.paths['disk'];record(root/'control.lock',{})
        record(root/'launch.json',{'binary':str(binary),'binary_sha256':digest(binary),'argv':[str(binary)],
            'disk':str(disk),'disk_identity':[disk.stat().st_dev,disk.stat().st_ino],
            'certificates':{},'windows_storage':self.policy()})
        with patch.object(driver,'fingerprints',return_value={}),\
             patch('ctflab_storage_boundary.check_windows_profile',side_effect=ContractError('identity-unknown')),\
             patch.object(driver,'native_observe',side_effect=AssertionError('不能观察其他进程')),\
             patch('ctflab_bounded_log.spawn',side_effect=AssertionError('不能派生日志接收器')),\
             patch.object(driver.subprocess,'Popen',side_effect=AssertionError('不能启动QEMU')):
            with self.assertRaises(ContractError):driver.worker(root)
        self.assertFalse((root/'start.intent.json').exists())


if __name__=='__main__':unittest.main()
