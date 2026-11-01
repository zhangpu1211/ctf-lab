"""普通用户的显式委派cgroup v2限额；只迁移本次监督进程，不修改委派根或清理其他组。"""
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
from ctflab_contract import canonical,require

CONTROLLERS={'cpu','memory','pids'}


def settings(value,plan):
    require(type(value) is dict and set(value)=={'cgroup_root','nodes'})
    root=value['cgroup_root']
    require(type(root) is str and re.fullmatch(r'/sys/fs/cgroup/[A-Za-z0-9_.@:-]+(?:/[A-Za-z0-9_.@:-]+)*',root)
            and '..' not in Path(root).parts and '.' not in Path(root).parts,'permission-denied')
    require(type(value['nodes']) is dict and set(value['nodes'])==set(plan['manifest']['nodes']))
    for name,limits in value['nodes'].items():
        node=plan['manifest']['nodes'][name]
        require(type(limits) is dict and {'memory_max_mb','cpu_quota_us','pids_max'}<=set(limits)<={'memory_max_mb','cpu_quota_us','pids_max','disk_max_bytes'})
        require(type(limits['memory_max_mb']) is int and node['memory_mb']+64<=limits['memory_max_mb']<=1024**2
                and type(limits['cpu_quota_us']) is int and 1000<=limits['cpu_quota_us']<=node['cpus']*100000
                and type(limits['pids_max']) is int and 32<=limits['pids_max']<=4096)
        if 'disk_max_bytes' in limits:require(type(limits['disk_max_bytes']) is int and 1024**2<=limits['disk_max_bytes']<=1024**4)
    require(all('disk_max_bytes' in v for v in value['nodes'].values()) or all('disk_max_bytes' not in v for v in value['nodes'].values()),'capability-unverified')
    return value


def controls(limits):
    return {'memory.max':str(limits['memory_max_mb']*1024**2),'memory.swap.max':'0','memory.oom.group':'1',
            'pids.max':str(limits['pids_max']),'cpu.max':str(limits['cpu_quota_us'])+' 100000'}


class KernelTree:
    def __init__(self,root):
        require(sys.platform=='linux' and os.geteuid()!=0 and os.geteuid()==os.getuid(),'unsupported-platform')
        self.root=Path(root);self.relative='/'+str(self.root.relative_to('/sys/fs/cgroup'))
        # 限定一个标准cgroup2根挂载；不猜测容器化/重映射的挂载语义。
        rows=Path('/proc/self/mountinfo').read_text().splitlines()
        require(any(len(fields:=line.split())>9 and fields[3]=='/' and fields[4]=='/sys/fs/cgroup'
                    and ' - cgroup2 ' in line for line in rows),'capability-unverified')
        self.stamp('')
    def path(self,name):
        path=self.root/name
        require(path==self.root or self.root in path.parents,'permission-denied')
        for part in (path,*path.parents):
            info=part.lstat();require(not stat.S_ISLNK(info.st_mode),'permission-denied')
        return path
    def stamp(self,name):
        path=self.path(name);info=path.stat()
        require(path.is_dir() and info.st_uid==os.getuid() and not info.st_mode&0o022,'permission-denied')
        return [info.st_dev,info.st_ino]
    def read(self,name):
        path=self.path(name);fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd);require(info.st_dev==self.root.stat().st_dev and stat.S_ISREG(info.st_mode),'identity-unknown')
            raw=os.read(fd,131073);require(len(raw)<=131072,'storage-insufficient');return raw.decode().strip()
        finally:os.close(fd)
    def write(self,name,value):
        path=self.path(name);fd=os.open(path,os.O_WRONLY|os.O_CLOEXEC|os.O_NOFOLLOW)
        try:
            info=os.fstat(fd);require(info.st_dev==self.root.stat().st_dev and info.st_uid==os.getuid()
                and stat.S_ISREG(info.st_mode) and not info.st_mode&0o022,'permission-denied')
            raw=(value+'\n').encode();require(os.write(fd,raw)==len(raw),'persistence-failed')
        finally:os.close(fd)
    def mkdir(self,name):
        require(type(name) is str and re.fullmatch('[a-zA-Z0-9_-]{1,192}',name))
        require(sum(p.is_dir() for p in self.root.iterdir())<4096,'storage-insufficient')
        (self.root/name).mkdir(mode=0o755);return self.stamp(name)
    def process_path(self,pid):
        require(type(pid) is int and pid>0)
        path=Path('/proc')/str(pid)/'cgroup';require(path.stat().st_uid==os.getuid(),'permission-denied')
        rows=path.read_text().splitlines();require(len(rows)==1 and rows[0].startswith('0::/'),'identity-unknown')
        return rows[0][3:]
    def join_self(self,group):
        # 必须已由部署方放进同一委派子树的manager叶子；不从别的user.slice接管进程。
        current=self.process_path(os.getpid())
        require(current.startswith(self.relative+'/'),'permission-denied')
        self.write(group+'/cgroup.procs',str(os.getpid()))
        require(self.process_path(os.getpid())==self.relative+'/'+group,'identity-unknown')
    def limit_files(self,maximum):
        import resource,signal
        require(type(maximum) is int and maximum>0)
        soft,hard=resource.getrlimit(resource.RLIMIT_FSIZE)
        require(hard==resource.RLIM_INFINITY or maximum<=hard,'permission-denied')
        # 只限制新监督进程与后续QEMU；超限写返回EFBIG，不主动发信号终止VM。
        signal.signal(signal.SIGXFSZ,signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE,(maximum,maximum))
        require(resource.getrlimit(resource.RLIMIT_FSIZE)==(maximum,maximum),'identity-unknown')
    def file_limits(self,pid):
        import resource
        require(hasattr(resource,'prlimit'),'capability-unverified')
        return resource.prlimit(pid,resource.RLIMIT_FSIZE)
    def contains(self,group,pid):return self.process_path(pid)==self.relative+'/'+group


def preflight(root,*,tree=None):
    tree=tree or KernelTree(root);stamp=tree.stamp('')
    require(CONTROLLERS<=set(tree.read('cgroup.controllers').split())
            and CONTROLLERS<=set(tree.read('cgroup.subtree_control').split())
            and tree.read('cgroup.procs')=='','capability-unverified')
    require(tree.stamp('')==stamp,'identity-unknown')
    return stamp


def declaration(profile,plan,node,attempt,*,tree=None):
    config=settings(profile['resource_limits'],plan);require(node in config['nodes'])
    require(type(attempt) is str and re.fullmatch('[0-9]{8}',attempt))
    group='ctflab-'+plan['instance_uuid']+'-g'+str(plan['generation'])+'-'+node+'-a'+attempt
    value={'schema':1,'root':config['cgroup_root'],'root_identity':preflight(config['cgroup_root'],tree=tree),
        'group':group,'limits':config['nodes'][node],'instance_uuid':plan['instance_uuid'],'generation':plan['generation'],'node':node}
    value['declaration_sha256']=hashlib.sha256(canonical(value).encode()).hexdigest();return value


def validate_declaration(value):
    require(type(value) is dict and set(value)=={'schema','root','root_identity','group','limits','instance_uuid','generation','node','declaration_sha256'}
            and type(value['schema']) is int and value['schema']==1)
    raw={key:item for key,item in value.items() if key!='declaration_sha256'}
    require(hashlib.sha256(canonical(raw).encode()).hexdigest()==value['declaration_sha256'],'identity-unknown')
    require(type(value['group']) is str and re.fullmatch('[a-zA-Z0-9_-]{1,192}',value['group']))
    # 非profile调用也不能把控制文件名称/内容作为输入。
    require(type(value['root']) is str and value['root'].startswith('/sys/fs/cgroup/') and '..' not in Path(value['root']).parts)
    require(type(value['limits']) is dict and {'memory_max_mb','cpu_quota_us','pids_max'}<=set(value['limits'])<={'memory_max_mb','cpu_quota_us','pids_max','disk_max_bytes'}
            and all(type(x) is int and x>0 for x in value['limits'].values()))
    return value


def enter(value,*,tree=None):
    value=validate_declaration(value);tree=tree or KernelTree(value['root'])
    require(preflight(value['root'],tree=tree)==value['root_identity'],'identity-unknown')
    identity=tree.mkdir(value['group']);require(tree.read(value['group']+'/cgroup.procs')=='','resource-busy')
    for name,text in controls(value['limits']).items():
        tree.write(value['group']+'/'+name,text)
        require(tree.read(value['group']+'/'+name)==text,'state-conflict')
    tree.join_self(value['group'])
    if 'disk_max_bytes' in value['limits']:tree.limit_files(value['limits']['disk_max_bytes'])
    proof={'schema':1,'declaration_sha256':value['declaration_sha256'],'group_identity':identity,
        'supervisor_pid':os.getpid(),'cpu_memory_pids_enforced_before_qemu':True,'disk_quota_hard_enforced':False}
    if 'disk_max_bytes' in value['limits']:proof['overlay_file_limit_bytes']=value['limits']['disk_max_bytes']
    verify(value,proof,os.getpid(),tree=tree)
    return proof


def verify(value,proof,pid,*,tree=None):
    value=validate_declaration(value);tree=tree or KernelTree(value['root'])
    require(type(proof) is dict and set(proof)=={'schema','declaration_sha256','group_identity','supervisor_pid',
                'cpu_memory_pids_enforced_before_qemu','disk_quota_hard_enforced'}|({'overlay_file_limit_bytes'} if 'disk_max_bytes' in value['limits'] else set())
            and type(proof['schema']) is int and proof['schema']==1 and proof['declaration_sha256']==value['declaration_sha256']
            and type(proof['supervisor_pid']) is int and proof['supervisor_pid']>0
            and proof['cpu_memory_pids_enforced_before_qemu'] is True and proof['disk_quota_hard_enforced'] is False
            and tree.stamp('')==value['root_identity'] and tree.stamp(value['group'])==proof['group_identity'],'identity-unknown')
    for name,text in controls(value['limits']).items():require(tree.read(value['group']+'/'+name)==text,'state-conflict')
    require(tree.contains(value['group'],pid),'identity-unknown')
    observed=False
    if 'disk_max_bytes' in value['limits']:
        maximum=value['limits']['disk_max_bytes'];require(proof['overlay_file_limit_bytes']==maximum and tree.file_limits(pid)==(maximum,maximum),'state-conflict');observed=True
    return {'cpu_memory_pids_limits_observed':True,'overlay_file_limit_observed':observed,'disk_quota_hard_enforced':False}
