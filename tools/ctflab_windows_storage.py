"""预配置Windows专用NTFS卷的只读身份/实际簇容量绑定；不创建卷、提权或设置配额。"""
import argparse
import ctypes
import hashlib
import os
from pathlib import Path,PureWindowsPath
import re
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text
from ctflab_windows_native import DWORD,BOOL,HANDLE,FileTime


class FileInfo(ctypes.Structure):
    _fields_=[('attributes',DWORD),('created',FileTime),('accessed',FileTime),('written',FileTime),
        ('serial',DWORD),('size_high',DWORD),('size_low',DWORD),('links',DWORD),('index_high',DWORD),('index_low',DWORD)]


class NtfsData(ctypes.Structure):
    _fields_=[(name,ctypes.c_int64) for name in ('SerialNumber','NumberSectors','TotalClusters','FreeClusters','TotalReserved')]+[
        (name,DWORD) for name in ('BytesPerSector','BytesPerCluster','BytesPerRecord','ClustersPerRecord')]+[
        (name,ctypes.c_int64) for name in ('MftLength','MftStart','MftMirror','MftZoneStart','MftZoneEnd')]


def locations(root,mountpoint):
    from ctflab_windows_security import validate_local_path
    require(type(root) is str and type(mountpoint) is str)
    validate_local_path(root);validate_local_path(mountpoint)
    directory=PureWindowsPath(root);volume=PureWindowsPath(mountpoint)
    require(str(directory)==root and str(volume)==mountpoint and directory.parent==volume
        and directory.name.casefold()=='instance' and volume==PureWindowsPath(volume.anchor),'permission-denied')
    return directory,volume


def geometry(value):
    require(type(value) is NtfsData and value.TotalClusters>0 and 0<=value.FreeClusters<=value.TotalClusters
        and value.BytesPerSector in (512,1024,2048,4096) and value.BytesPerCluster>=value.BytesPerSector
        and value.BytesPerCluster<=2*1024**2 and value.BytesPerCluster&(value.BytesPerCluster-1)==0,'capability-unverified')
    return {'serial64':f'{value.SerialNumber&((1<<64)-1):016x}','total_clusters':value.TotalClusters,
        'bytes_per_cluster':value.BytesPerCluster,'capacity_bytes':value.TotalClusters*value.BytesPerCluster}


def require_exclusive_volume(mountpoint,instance,instances):
    from ctflab_windows_security import validate_local_path
    volume=PureWindowsPath(mountpoint)
    for other,entry in instances.items():
        if other==instance:continue
        validate_local_path(entry['root']);path=PureWindowsPath(entry['root'])
        require(volume!=path and volume not in path.parents and path not in volume.parents,'permission-denied')


class Native:
    def __init__(self):
        require(os.name=='nt' and ctypes.sizeof(ctypes.c_void_p)==8 and ctypes.sizeof(NtfsData)==96
                and ctypes.sizeof(FileInfo)==52,'unsupported-platform')
        from ctflab_windows_security import guard_path
        self.guard=guard_path;self.kernel=ctypes.WinDLL('kernel32.dll',winmode=0x800,use_last_error=True)
        wchar=ctypes.c_wchar_p;pointer=ctypes.c_void_p
        definitions={
            'CreateFileW':([wchar,DWORD,DWORD,pointer,DWORD,DWORD,HANDLE],HANDLE),
            'CloseHandle':([HANDLE],BOOL),'GetFileInformationByHandle':([HANDLE,ctypes.POINTER(FileInfo)],BOOL),
            'GetFinalPathNameByHandleW':([HANDLE,wchar,DWORD,DWORD],DWORD),
            'GetVolumePathNameW':([wchar,wchar,DWORD],BOOL),
            'GetVolumeNameForVolumeMountPointW':([wchar,wchar,DWORD],BOOL),
            'GetVolumePathNamesForVolumeNameW':([wchar,wchar,DWORD,ctypes.POINTER(DWORD)],BOOL),
            'GetVolumeInformationW':([wchar,wchar,DWORD,ctypes.POINTER(DWORD),ctypes.POINTER(DWORD),ctypes.POINTER(DWORD),wchar,DWORD],BOOL),
            'GetDiskFreeSpaceExW':([wchar,ctypes.POINTER(ctypes.c_uint64),ctypes.POINTER(ctypes.c_uint64),ctypes.POINTER(ctypes.c_uint64)],BOOL),
            'GetDriveTypeW':([wchar],DWORD),'GetWindowsDirectoryW':([wchar,DWORD],DWORD),
            'DeviceIoControl':([HANDLE,DWORD,pointer,DWORD,pointer,DWORD,ctypes.POINTER(DWORD),pointer],BOOL)}
        for name,(args,result) in definitions.items():
            call=getattr(self.kernel,name);call.argtypes=args;call.restype=result

    def text(self,function,*args):
        buffer=ctypes.create_unicode_buffer(32768)
        result=getattr(self.kernel,function)(*args,buffer,len(buffer))
        require(bool(result) and (function!='GetFinalPathNameByHandleW' or result<len(buffer)),'identity-unknown')
        return buffer.value

    def file(self,handle):
        value=FileInfo();require(self.kernel.GetFileInformationByHandle(handle,ctypes.byref(value)),'identity-unknown')
        require(value.attributes&0x10 and not value.attributes&0x400,'permission-denied')
        return [value.serial,value.index_high,value.index_low]

    def final(self,handle):
        buffer=ctypes.create_unicode_buffer(32768)
        size=self.kernel.GetFinalPathNameByHandleW(handle,buffer,len(buffer),1)
        require(0<size<len(buffer),'identity-unknown');return buffer.value

    def ntfs(self,handle):
        value=NtfsData();returned=DWORD()
        require(self.kernel.DeviceIoControl(handle,0x90064,None,0,ctypes.byref(value),ctypes.sizeof(value),
                ctypes.byref(returned),None) and returned.value==ctypes.sizeof(value),'capability-unverified')
        geometry(value);return value

    def probe(self,root,mountpoint):
        locations(str(root),str(mountpoint));root=str(root);mountpoint=str(mountpoint)
        self.guard(root);self.guard(mountpoint)
        require(self.kernel.GetDriveTypeW(mountpoint)==3,'capability-unverified')
        require(self.text('GetVolumePathNameW',root).casefold()==mountpoint.casefold(),'identity-unknown')
        guid=self.text('GetVolumeNameForVolumeMountPointW',mountpoint)
        require(re.fullmatch(r'\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\',guid),'identity-unknown')
        uuid_text(guid[11:47].lower())
        windows=ctypes.create_unicode_buffer(32768)
        size=self.kernel.GetWindowsDirectoryW(windows,len(windows));require(0<size<len(windows),'identity-unknown')
        system=self.text('GetVolumePathNameW',windows.value)
        require(self.text('GetVolumeNameForVolumeMountPointW',system).casefold()!=guid.casefold(),'permission-denied')
        aliases=ctypes.create_unicode_buffer(32768);needed=DWORD()
        require(self.kernel.GetVolumePathNamesForVolumeNameW(guid,aliases,len(aliases),ctypes.byref(needed))
            and 2<=needed.value<=len(aliases),'identity-unknown')
        raw=''.join(aliases[:needed.value]);require(raw.endswith('\0\0'),'identity-unknown')
        paths=raw[:-2].split('\0')
        require(len(paths)==1 and PureWindowsPath(paths[0])==PureWindowsPath(mountpoint),'capability-unverified')
        fs=ctypes.create_unicode_buffer(32);serial=DWORD();component=DWORD();flags=DWORD()
        require(self.kernel.GetVolumeInformationW(mountpoint,None,0,ctypes.byref(serial),ctypes.byref(component),
            ctypes.byref(flags),fs,len(fs)) and fs.value=='NTFS' and not flags.value&0x80000,'capability-unverified')
        names=os.listdir(mountpoint)
        require(len(names)<=3 and {name.casefold() for name in names}<={'instance','system volume information','$recycle.bin'}
            and 'instance' in {name.casefold() for name in names},'permission-denied')
        handles=[]
        try:
            for path in (mountpoint,root):
                handle=self.kernel.CreateFileW(path,0x80,7,None,3,0x2200000,None)
                require(handle not in (None,0,ctypes.c_void_p(-1).value),'permission-denied');handles.append(handle)
            volume_handle,root_handle=handles;volume_id=self.file(volume_handle);root_id=self.file(root_handle)
            require(self.final(volume_handle).casefold()==guid.casefold()
                and self.final(root_handle).casefold()==(guid+'instance').casefold(),'identity-unknown')
            # 卷控制码使用无尾斜线的卷设备句柄，不向目录句柄发送。
            device=self.kernel.CreateFileW(guid[:-1],0,7,None,3,0,None)
            require(device not in (None,0,ctypes.c_void_p(-1).value),'permission-denied');handles.append(device)
            first=self.ntfs(device);second=self.ntfs(device)
            physical=geometry(first)
            require(physical==geometry(second) and volume_id[0]==root_id[0]==serial.value,'identity-unknown')
            available=ctypes.c_uint64();caller_total=ctypes.c_uint64();unused=ctypes.c_uint64()
            require(self.kernel.GetDiskFreeSpaceExW(root,ctypes.byref(available),ctypes.byref(caller_total),ctypes.byref(unused))
                and available.value<=physical['capacity_bytes'],'identity-unknown')
            self.guard(root);self.guard(mountpoint)
            require(self.file(volume_handle)==volume_id and self.file(root_handle)==root_id
                and geometry(self.ntfs(device))==physical
                and self.text('GetVolumeNameForVolumeMountPointW',mountpoint)==guid
                and sorted(os.listdir(mountpoint))==sorted(names),'identity-unknown')
            return {'filesystem':'NTFS','volume_guid':guid.lower(),'mount_identity':volume_id,'root_identity':root_id,
                'aliases':paths,**physical},min(available.value,second.FreeClusters*second.BytesPerCluster)
        finally:
            for handle in handles:self.kernel.CloseHandle(handle)


def settings(value,*,root=None,instance=None):
    require(type(value) is dict and set(value)=={'schema','kind','instance_uuid','root','mountpoint','max_bytes','binding','sha256'}
        and type(value['schema']) is int and value['schema']==1 and value['kind']=='windows-ntfs-volume')
    locations(value['root'],value['mountpoint']);uuid_text(value['instance_uuid'])
    require(type(value['max_bytes']) is int and 64*1024**2<=value['max_bytes']<=1024**4)
    binding=value['binding']
    require(type(binding) is dict and type(binding.get('capacity_bytes')) is int
        and 0<binding['capacity_bytes']<=value['max_bytes'],'storage-insufficient')
    require(hashlib.sha256(canonical({k:v for k,v in value.items() if k!='sha256'}).encode()).hexdigest()==value['sha256'],'identity-unknown')
    if root is not None:require(PureWindowsPath(value['root'])==PureWindowsPath(str(root)),'identity-unknown')
    if instance is not None:require(value['instance_uuid']==instance,'identity-unknown')
    return value


def enroll(root,mountpoint,instance,maximum,*,observer=None):
    locations(str(root),str(mountpoint));uuid_text(instance)
    require(type(maximum) is int and 64*1024**2<=maximum<=1024**4)
    binding,_=(observer or Native()).probe(str(root),str(mountpoint))
    result={'schema':1,'kind':'windows-ntfs-volume','instance_uuid':instance,'root':str(root),
        'mountpoint':str(mountpoint),'max_bytes':maximum,'binding':binding}
    result['sha256']=hashlib.sha256(canonical(result).encode()).hexdigest();return settings(result)


def verify(value,*,root=None,instance=None,observer=None):
    settings(value,root=root,instance=instance)
    binding,available=(observer or Native()).probe(value['root'],value['mountpoint'])
    require(binding==value['binding'],'identity-unknown')
    return {'state':'dedicated-ntfs-volume-observed','binding_sha256':value['sha256'],
        'capacity_bytes':binding['capacity_bytes'],'max_bytes':value['max_bytes'],'available_bytes':available,
        'scope':'instance-filesystem-cluster-capacity','native_volume_verified':True,'aggregate_project_quota_verified':False,
        'external_cache_or_audit_included':False,'host_storage_modified':False,'automatic_cleanup':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('inspect',))
    parser.add_argument('--run',required=True);parser.add_argument('--mountpoint',required=True)
    parser.add_argument('--instance',required=True);parser.add_argument('--max-bytes',required=True,type=int);args=parser.parse_args()
    try:print(canonical(enroll(args.run,args.mountpoint,args.instance,args.max_bytes)))
    except (OSError,ValueError,RuntimeError,KeyError,TypeError):
        print(canonical({'state':'refused','host_storage_modified':False,'automatic_cleanup':False}));raise SystemExit(2)
