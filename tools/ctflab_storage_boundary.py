"""Linux预配置专用文件系统的只读容量绑定；不挂载、格式化、扩容、删除或设置配额。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text
from ctflab_tls_endpoint import guard


def unescape(value):
    # mountinfo仅转义空格、制表、换行、反斜线；不接受猜测的路径语义。
    require(type(value) is str and not re.search(r'\\(?!040|011|012|134)',value),'capability-unverified')
    return re.sub(r'\\(040|011|012|134)',lambda m:chr(int(m[1],8)),value)


def mounts(raw):
    require(type(raw) is str and len(raw.encode())<=4*1024**2,'storage-insufficient')
    result=[];ids=set()
    for line in raw.splitlines():
        fields=line.split();require(fields.count('-')==1,'capability-unverified');split=fields.index('-')
        require(split>=6 and len(fields)==split+4 and fields[0].isdigit() and fields[1].isdigit()
                and re.fullmatch(r'[0-9]+:[0-9]+',fields[2]),'capability-unverified')
        identity=int(fields[0]);require(identity>0 and identity not in ids,'identity-unknown');ids.add(identity)
        result.append({'id':identity,'parent':int(fields[1]),'device':fields[2],
            'root':unescape(fields[3]),'mountpoint':unescape(fields[4]),'options':sorted(fields[5].split(',')),
            'optional':fields[6:split],'fstype':fields[split+1],'source':unescape(fields[split+2]),
            'super_options':sorted(fields[split+3].split(','))})
    require(0<len(result)<=20000,'capability-unverified');return result


def path_text(value):
    require(type(value) is str and value.startswith('/') and '\x00' not in value
        and str(Path(value))==value and '.' not in value.split('/') and '..' not in value.split('/'),'permission-denied')
    return Path(value)


class Native:
    """从当前命名空间与保留目录FD观察，不执行宿主命令或写控制文件。"""
    def __init__(self):
        require(sys.platform=='linux' and os.getuid()==os.geteuid()!=0,'unsupported-platform')
    def probe(self,root,mountpoint):
        root=guard(path_text(str(root)));mountpoint=guard(path_text(str(mountpoint)))
        namespace=Path('/proc/self/ns/mnt').stat();namespace_identity=[namespace.st_dev,namespace.st_ino]
        raw=Path('/proc/self/mountinfo').read_text();rows=mounts(raw)
        selected=[r for r in rows if r['mountpoint']==str(mountpoint)]
        require(len(selected)==1,'capability-unverified');mount=selected[0]
        require(mount['root']=='/' and mount['fstype'] in ('ext4','xfs')
            and {'rw','nodev','nosuid'}<=set(mount['options']) and 'rw' in mount['super_options']
            and mount['source'].startswith('/dev/'),'capability-unverified')
        # 同一设备的bind别名与嵌套/叠加挂载均拒绝，不把共享根误称专用卷。
        require(sum(r['device']==mount['device'] for r in rows)==1
            and all(r==mount or mountpoint not in Path(r['mountpoint']).parents for r in rows),'capability-unverified')
        with_fd=[]
        try:
            for path in (mountpoint,root):
                fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_DIRECTORY|os.O_NOFOLLOW);with_fd.append(fd)
            volume,instance=[os.fstat(fd) for fd in with_fd];volume_info=os.fstatvfs(with_fd[0]);info=os.fstatvfs(with_fd[1])
            require(all(stat.S_ISDIR(item.st_mode) and item.st_uid==os.getuid() and not item.st_mode&0o077
                for item in (volume,instance)),'permission-denied')
            device=f'{os.major(instance.st_dev)}:{os.minor(instance.st_dev)}'
            block=Path(mount['source']).stat()
            require(stat.S_ISBLK(block.st_mode) and block.st_rdev==instance.st_dev==volume.st_dev
                    and mount['device']==device,'identity-unknown')
            require(info.f_fsid==volume_info.f_fsid and info.f_frsize==volume_info.f_frsize
                    and info.f_blocks==volume_info.f_blocks and info.f_frsize>0 and info.f_blocks>0
                    and not info.f_flag&os.ST_RDONLY,'identity-unknown')
            require([volume.st_dev,volume.st_ino]==[mountpoint.stat().st_dev,mountpoint.stat().st_ino]
                and [instance.st_dev,instance.st_ino]==[root.stat().st_dev,root.stat().st_ino],'identity-unknown')
            after=Path('/proc/self/ns/mnt').stat()
            require(namespace_identity==[after.st_dev,after.st_ino] and Path('/proc/self/mountinfo').read_text()==raw,'identity-unknown')
            binding={'mount':mount,'mount_namespace':namespace_identity,'root_identity':[instance.st_dev,instance.st_ino],
                'mount_identity':[volume.st_dev,volume.st_ino],'filesystem_id':info.f_fsid,
                'capacity_bytes':info.f_blocks*info.f_frsize}
            return binding,max(0,info.f_bavail)*info.f_frsize
        finally:
            for fd in with_fd:os.close(fd)
    def process_namespace(self,pid):
        require(type(pid) is int and pid>0)
        info=(Path('/proc')/str(pid)/'ns/mnt').stat();return [info.st_dev,info.st_ino]


def settings(value,*,root=None,instance=None):
    require(type(value) is dict and set(value)=={'schema','instance_uuid','root','mountpoint','max_bytes','binding','sha256'}
        and type(value['schema']) is int and value['schema']==1)
    uuid_text(value['instance_uuid']);directory=path_text(value['root']);volume=path_text(value['mountpoint'])
    require(directory.parent==volume and volume!=Path('/') and directory.name=='instance','permission-denied')
    require(type(value['max_bytes']) is int and 64*1024**2<=value['max_bytes']<=1024**4)
    require(type(value['binding']) is dict and type(value['binding'].get('capacity_bytes')) is int
        and 0<value['binding']['capacity_bytes']<=value['max_bytes'],'storage-insufficient')
    material={k:v for k,v in value.items() if k!='sha256'}
    require(type(value['sha256']) is str and hashlib.sha256(canonical(material).encode()).hexdigest()==value['sha256'],'identity-unknown')
    if root is not None:require(directory==Path(root).absolute(),'identity-unknown')
    if instance is not None:require(value['instance_uuid']==instance,'identity-unknown')
    return value


def enroll(root,mountpoint,instance,maximum,*,observer=None):
    uuid_text(instance);directory=path_text(str(root));volume=path_text(str(mountpoint))
    require(directory.parent==volume and directory.name=='instance' and volume!=Path('/'),'permission-denied')
    require(type(maximum) is int and 64*1024**2<=maximum<=1024**4)
    observer=observer or Native();binding,_=observer.probe(directory,volume)
    value={'schema':1,'instance_uuid':instance,'root':str(directory),'mountpoint':str(volume),'max_bytes':maximum,'binding':binding}
    value['sha256']=hashlib.sha256(canonical(value).encode()).hexdigest();return settings(value)


def verify(value,*,root=None,instance=None,pid=None,observer=None):
    settings(value,root=root,instance=instance);observer=observer or Native()
    before,available=observer.probe(Path(value['root']),Path(value['mountpoint']))
    require(before==value['binding'],'identity-unknown')
    if pid is not None:require(observer.process_namespace(pid)==before['mount_namespace'],'identity-unknown')
    return {'state':'dedicated-filesystem-observed','binding_sha256':value['sha256'],
        'capacity_bytes':before['capacity_bytes'],'available_bytes':available,'max_bytes':value['max_bytes'],
        'scope':'instance-filesystem-data-capacity','native_filesystem_verified':True,
        'aggregate_project_quota_verified':False,'external_cache_or_audit_included':False,
        'host_storage_modified':False,'automatic_cleanup':False}


def check_mac_profile(profile,root,*,observer=None):
    from ctflab_macos_storage import settings as mac_settings,verify as mac_verify
    policy=profile['macos_storage'];mac_settings(policy)
    root=Path(root).absolute();owner=Path(policy['root'])
    require(root==owner or owner in root.parents,'identity-unknown');guard(root)
    proof=mac_verify(policy,owner,observer=observer)
    return dict(proof,binding_sha256=policy['sha256'])


def check_windows_profile(profile,root,*,instance=None,observer=None):
    from ctflab_windows_storage import verify as windows_verify
    policy=profile['windows_storage'];directory=Path(root).absolute();owner=Path(policy['root'])
    require(directory==owner or owner in directory.parents,'identity-unknown');guard(directory)
    return windows_verify(policy,root=owner,instance=instance,observer=observer)


def check_profile(root,instance,*,observer=None):
    """代次准备/重置在复制前及选择前检查；未声明的历史profile不迁移。"""
    from ctflab_server_storage import check_instance
    check_instance(root)
    path=Path(root)/'runtime-profile.json'
    if not path.exists():
        require(not (Path(root)/'storage-bind.intent.json').exists(),'identity-unknown')
        return None
    guard(path);require(path.stat().st_size<=8*1024**2,'storage-insufficient')
    with path.open('rb') as stream:raw=stream.read(8*1024**2+1)
    require(len(raw)<=8*1024**2,'storage-insufficient');profile=json.loads(raw)
    require(type(profile) is dict)
    from ctflab_storage_bind import assert_closed
    assert_closed(root,profile,instance=instance)
    require(len({'storage_boundary','macos_storage','windows_storage'}&set(profile))<=1,'identity-unknown')
    if 'macos_storage' in profile:proof=check_mac_profile(profile,root,observer=observer)
    elif 'windows_storage' in profile:proof=check_windows_profile(profile,root,instance=instance,observer=observer)
    elif 'storage_boundary' in profile:proof=verify(profile['storage_boundary'],root=root,instance=instance,observer=observer)
    else:return None
    with path.open('rb') as stream:require(stream.read(8*1024**2+1)==raw,'identity-unknown')
    return proof


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('inspect',))
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--mountpoint',type=Path,required=True)
    parser.add_argument('--instance',required=True);parser.add_argument('--max-bytes',required=True,type=int);args=parser.parse_args()
    try:print(canonical(enroll(args.run,args.mountpoint,args.instance,args.max_bytes)))
    except (OSError,ValueError,RuntimeError,KeyError,TypeError):
        print(canonical({'state':'refused','host_storage_modified':False,'automatic_cleanup':False}));raise SystemExit(2)
