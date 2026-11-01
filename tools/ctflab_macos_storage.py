"""Mac APFS预设卷配额的只读绑定及旧Mac运行器登记；不创建卷或修改配额。"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text
from ctflab_tls_endpoint import guard

POLICY='storage-boundary.json'


class StatFS64(ctypes.Structure):
    # 与当前Darwin SDK的statfs64布局一致，固定使用显式64位函数。
    _fields_=[('bsize',ctypes.c_uint32),('iosize',ctypes.c_int32),
        *[(key,ctypes.c_uint64) for key in ('blocks','bfree','bavail','files','ffree')],
        ('fsid',ctypes.c_int32*2),('owner',ctypes.c_uint32),('type',ctypes.c_uint32),
        ('flags',ctypes.c_uint32),('subtype',ctypes.c_uint32),('fstype',ctypes.c_char*16),
        ('mountpoint',ctypes.c_char*1024),('source',ctypes.c_char*1024),('flags_ext',ctypes.c_uint32),('reserved',ctypes.c_uint32*7)]


def mount_row(value):
    return {'fsid':list(value.fsid),'fstype':bytes(value.fstype).decode(),
        'mountpoint':bytes(value.mountpoint).decode(),'source':bytes(value.source).decode(),'flags':value.flags}


def kernel_mounts():
    require(sys.platform=='darwin' and ctypes.sizeof(ctypes.c_void_p)==8 and ctypes.sizeof(StatFS64)==2168,'unsupported-platform')
    lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True);call=lib.getfsstat64
    call.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int];call.restype=ctypes.c_int
    count=call(None,0,2);require(0<count<=4096,'capability-unverified')
    rows=(StatFS64*(count+16))();filled=call(rows,ctypes.sizeof(rows),2)
    require(0<filled<len(rows),'identity-unknown');return [mount_row(rows[i]) for i in range(filled)]


def diskutil(args):
    require(sys.platform=='darwin','unsupported-platform');binary=Path('/usr/sbin/diskutil');info=binary.stat()
    require(info.st_uid==0 and not info.st_mode&0o022,'permission-denied')
    require(len(args)==3 and args[:2]==['info','-plist'] and type(args[2]) is str and args[2].startswith('/')
        or len(args)==4 and args[:3]==['apfs','list','-plist'] and type(args[3]) is str and re.fullmatch(r'disk\d+',args[3]),'invalid-request')
    reply=subprocess.run([str(binary),*args],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        timeout=15,check=True,env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LC_ALL':'C'})
    require(len(reply.stdout)<=8*1024**2 and len(reply.stderr)<=1024**2,'storage-insufficient');return plistlib.loads(reply.stdout)


def apfs_quota(info,listing,mount):
    require(type(info) is dict and info.get('FilesystemType')=='apfs' and info.get('MountPoint')==mount['mountpoint']
        and not info.get('APFSSnapshot',False),'capability-unverified')
    device=info.get('DeviceIdentifier');container=info.get('APFSContainerReference')
    require(type(device) is str and re.fullmatch(r'disk\d+s\d+',device)
        and type(container) is str and re.fullmatch(r'disk\d+',container) and mount['source']=='/dev/'+device,'identity-unknown')
    require(type(info.get('VolumeUUID')) is str,'identity-unknown');volume_uuid=uuid_text(info['VolumeUUID'].lower())
    require(type(listing) is dict and type(listing.get('Containers')) is list and len(listing['Containers'])<=128,'capability-unverified')
    containers=[v for v in listing['Containers'] if v.get('ContainerReference')==container];require(len(containers)==1,'identity-unknown')
    owner=containers[0];container_uuid=uuid_text(owner['APFSContainerUUID'].lower())
    volumes=owner.get('Volumes');require(type(volumes) is list and len(volumes)<=1024,'capability-unverified')
    found=[v for v in volumes if v.get('DeviceIdentifier')==device];require(len(found)==1,'identity-unknown');volume=found[0]
    require(volume.get('APFSVolumeUUID','').lower()==volume_uuid and volume.get('Roles')==[]
        and volume.get('Locked') is False,'capability-unverified')
    quota=volume.get('CapacityQuota');used=volume.get('CapacityInUse')
    require(type(quota) is int and 0<quota<=1024**4 and type(used) is int and used>=0,'capability-unverified')
    return {'volume_uuid':volume_uuid,'container_uuid':container_uuid,'device':device,'quota_bytes':quota},max(0,quota-used)


class NativeMac:
    def __init__(self):
        require(sys.platform=='darwin' and os.getuid()==os.geteuid()!=0,'unsupported-platform')
    def probe(self,root,mountpoint):
        root=guard(Path(root));mountpoint=guard(Path(mountpoint));rows=kernel_mounts()
        selected=[r for r in rows if r['mountpoint']==str(mountpoint)];require(len(selected)==1,'capability-unverified');mount=selected[0]
        require(mount['fstype']=='apfs' and not mount['flags']&1 and mount['flags']&0x18==0x18,'capability-unverified')
        require(sum(r['fsid']==mount['fsid'] or r['source']==mount['source'] for r in rows)==1
            and all(r==mount or mountpoint not in Path(r['mountpoint']).parents for r in rows),'capability-unverified')
        info=diskutil(['info','-plist',str(mountpoint)]);container=info.get('APFSContainerReference')
        require(type(container) is str and re.fullmatch(r'disk\d+',container),'capability-unverified')
        quota,remaining=apfs_quota(info,diskutil(['apfs','list','-plist',container]),mount)
        lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True);fstatfs=lib.fstatfs64
        fstatfs.argtypes=[ctypes.c_int,ctypes.POINTER(StatFS64)];fstatfs.restype=ctypes.c_int
        fds=[]
        try:
            for path in (mountpoint,root):fds.append(os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_DIRECTORY|os.O_NOFOLLOW))
            volume,directory=[os.fstat(fd) for fd in fds]
            require(all(stat.S_ISDIR(i.st_mode) and i.st_uid==os.getuid() and not i.st_mode&0o077 for i in (volume,directory)),'permission-denied')
            stats=[]
            for fd in fds:
                value=StatFS64();require(fstatfs(fd,ctypes.byref(value))==0 and mount_row(value)==mount,'identity-unknown');stats.append(value)
            require(volume.st_dev==directory.st_dev and stats[1].bsize>0,'identity-unknown')
            after=diskutil(['info','-plist',str(mountpoint)])
            current,remaining_after=apfs_quota(after,diskutil(['apfs','list','-plist',container]),mount)
            require(current==quota and kernel_mounts()==rows,'identity-unknown')
            require([root.stat().st_dev,root.stat().st_ino]==[directory.st_dev,directory.st_ino]
                and [mountpoint.stat().st_dev,mountpoint.stat().st_ino]==[volume.st_dev,volume.st_ino],'identity-unknown')
            binding={'mount':mount,'root_identity':[directory.st_dev,directory.st_ino],
                'mount_identity':[volume.st_dev,volume.st_ino],**quota}
            return binding,min(remaining,remaining_after,stats[1].bavail*stats[1].bsize)
        finally:
            for fd in fds:os.close(fd)


def settings(value,root=None):
    require(type(value) is dict and set(value)=={'schema','kind','root','mountpoint','max_bytes','binding','sha256'}
        and type(value['schema']) is int and value['schema']==1 and value['kind']=='mac-apfs-quota')
    for key in ('root','mountpoint'):
        text=value[key];require(type(text) is str and text.startswith('/') and str(Path(text))==text
            and '..' not in text.split('/') and '.' not in text.split('/') and '\x00' not in text,'permission-denied')
    require(Path(value['root']).parent==Path(value['mountpoint']) and value['mountpoint']!='/'
        and type(value['max_bytes']) is int and 64*1024**2<=value['max_bytes']<=1024**4)
    require(type(value['binding']) is dict and type(value['binding'].get('quota_bytes')) is int
        and 0<value['binding']['quota_bytes']<=value['max_bytes'],'storage-insufficient')
    require(hashlib.sha256(canonical({k:v for k,v in value.items() if k!='sha256'}).encode()).hexdigest()==value['sha256'],'identity-unknown')
    if root is not None:require(Path(value['root'])==Path(root).absolute(),'identity-unknown')
    return value


def enroll(root,mountpoint,maximum,*,observer=None):
    require(type(maximum) is int and 64*1024**2<=maximum<=1024**4)
    root=Path(root).absolute();mountpoint=Path(mountpoint).absolute();require(root.parent==mountpoint and mountpoint!=Path('/'),'permission-denied')
    binding,_=(observer or NativeMac()).probe(root,mountpoint)
    result={'schema':1,'kind':'mac-apfs-quota','root':str(root),'mountpoint':str(mountpoint),'max_bytes':maximum,'binding':binding}
    result['sha256']=hashlib.sha256(canonical(result).encode()).hexdigest();return settings(result)


def verify(value,root,*,observer=None):
    settings(value,root);binding,available=(observer or NativeMac()).probe(Path(root),Path(value['mountpoint']))
    require(binding==value['binding'],'identity-unknown')
    return {'state':'apfs-quota-observed','quota_bytes':binding['quota_bytes'],'max_bytes':value['max_bytes'],
        'available_bytes':available,'policy_sha256':value['sha256'],'scope':'whole-dedicated-apfs-volume',
        'external_files_included':False,'host_volume_modified':False,'automatic_cleanup':False}


def read_policy(path):
    path=guard(Path(path));require(path.stat().st_size<=65536,'storage-insufficient')
    with path.open('rb') as stream:raw=stream.read(65537)
    require(len(raw)<=65536,'storage-insufficient');return raw,settings(json.loads(raw))


def check_state(root,expected=None):
    path=Path(root)/POLICY
    if not path.exists() and not path.is_symlink():require(expected is None,'identity-unknown');return None,None
    raw,value=read_policy(path)
    if expected is not None:require(raw==expected,'identity-unknown')
    proof=verify(value,root);require(read_policy(path)[0]==raw,'identity-unknown');return raw,proof


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('inspect',))
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--mountpoint',type=Path,required=True)
    parser.add_argument('--max-bytes',type=int,required=True);args=parser.parse_args()
    try:print(canonical(enroll(args.run,args.mountpoint,args.max_bytes)))
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,subprocess.SubprocessError):
        print(canonical({'state':'refused','host_volume_modified':False,'automatic_cleanup':False}));raise SystemExit(2)
