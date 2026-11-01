"""专用Linux来宾代理：固定工具、实例绑定、持久意图；无宿主网络执行入口。"""
import argparse
from contextlib import contextmanager,closing
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import stat
import subprocess
import sys
import time

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))

from ctflab_contract import canonical, require, uuid_text, ContractError, MAX_MESSAGE_BYTES
from ctflab_generation_store import digest,private_directory
from ctflab_tls_endpoint import guard
from ctflab_guest_policy import verify_policy, firewall, service_config, service_units

OPTIONAL_ROUTED_TOOLS={'nsenter','iptables-save','ip6tables-save'}
TOOLS={'iptables-save':'/usr/sbin/iptables-save','ip6tables-save':'/usr/sbin/ip6tables-save','nsenter':'/usr/bin/nsenter','nft':'/usr/sbin/nft','ip':'/usr/sbin/ip','sysctl':'/usr/sbin/sysctl',
       'docker':'/usr/bin/docker','dnsmasq':'/usr/sbin/dnsmasq','chronyd':'/usr/sbin/chronyd',
       'systemctl':'/usr/bin/systemctl'}
MARKER=Path('/etc/ctflab-managed-guest.json')
STATE=Path('/var/lib/ctflab-guest')
DEVICE=Path('/dev/virtio-ports/org.ctflab.agent.0')


def private_file(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as stream:
        stream.write(canonical(value));stream.flush();os.fsync(stream.fileno())


def guarded_file(path,*,limit=1024*1024):
    path=Path(path)
    for part in (path,*path.parents):
        info=part.lstat()
        require(not stat.S_ISLNK(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'permission-denied')
    info=path.stat();require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=limit,'permission-denied')
    return json.loads(path.read_text(encoding='utf-8'))


class NativeBackend:
    """只允许配置了根所有标记、匹配DMI UUID的专用QEMU来宾。"""
    def __init__(self,policy,state=STATE):
        self.policy=policy;self.state=Path(state)
        require(platform.system()=='Linux' and os.geteuid()==0,'unsupported-platform')
        self.marker=guarded_file(MARKER)
        require({'schema','role','runtime_sha256'}<=set(self.marker)<={'schema','role','runtime_sha256','routing_mode','docker_config_sha256'} and type(self.marker['schema']) is int
                and self.marker['schema']==1 and self.marker['role']=='managed-router','permission-denied')
        require(type(self.marker['runtime_sha256']) is dict
                and set(TOOLS)-OPTIONAL_ROUTED_TOOLS<=set(self.marker['runtime_sha256'])<=set(TOOLS),'permission-denied')
        self.guard()

    def guard(self):
        require(guarded_file(MARKER)==self.marker,'permission-denied')
        if 'routed' in self.policy or self.marker.get('routing_mode') is not None:
            require(self.marker.get('routing_mode')=='point-to-point-v1' and ('routed' in self.policy or not self.policy['containers']),'capability-unverified')
            daemon=Path('/etc/docker/daemon.json')
            require(guarded_file(daemon)=={'iptables':False,'ip6tables':False,'ip-forward':False,'bridge':'none','userland-proxy':False}
                and digest(daemon)==self.marker.get('docker_config_sha256'),'state-conflict')
        actual=Path('/sys/class/dmi/id/product_uuid').read_text().strip().lower()
        require(actual==self.policy['vm_uuid'],'identity-unknown')
        vendor=Path('/sys/class/dmi/id/sys_vendor').read_text().strip()
        require(vendor in ('QEMU','Bochs'),'capability-unverified')

    def call(self,tool,args,*,input=None,timeout=30,pass_fds=()):
        self.guard();self.check_tool(tool)
        binary=Path(TOOLS[tool])
        command=[str(binary)]
        if tool=='docker':command+=['--host=unix:///var/run/docker.sock','--config',str(self.state/'docker-config')]
        try:
            reply=subprocess.run(command+args,input=input,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                 timeout=timeout,pass_fds=pass_fds,env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'},check=False)
        except subprocess.TimeoutExpired:
            # CLI退出不证明daemon副作用未发生。交由已持久意图保留unknown，代理继续接受只读查询。
            require(False,'control-unreachable')
        require(len(reply.stdout)<=4*1024**2 and len(reply.stderr)<=1024**2,'backend-failed')
        require(reply.returncode==0,'backend-failed')
        return reply.stdout.decode('utf-8')

    def check_tool(self,tool):
        require(tool in TOOLS and tool in self.marker['runtime_sha256'],'capability-unverified')
        binary=Path(TOOLS[tool]);info=binary.stat()
        require(info.st_uid==0 and not info.st_mode&0o022
                and digest(binary)==self.marker['runtime_sha256'][tool],'state-conflict')

    def json(self,tool,args):return json.loads(self.call(tool,args))

    def network_preflight(self):
        if 'routed' in self.policy:
            self.check_tool('nsenter')
            from ctflab_guest_routed import RoutedNetwork
            RoutedNetwork(self,self.policy).firewall_environment()
        # 已有出口/额外地址拒绝，绝不清空全局路由或猜测哪个接口可以删除。
        for family in ('-4','-6'):
            routes=self.json('ip',[family,'-j','route','show','default'])
            require(routes==[],'route-conflict')
        for nic in self.policy['interfaces'].values():
            rows=self.json('ip',['-j','address','show','dev',nic['device']])
            require(type(rows) is list and len(rows)==1 and rows[0]['address'].lower()==nic['mac'],'identity-unknown')
            allowed=str(nic['address'])
            require(all(a['family']=='inet6' and a.get('scope')=='link' or a['family']=='inet' and a['local']==allowed
                        for a in rows[0].get('addr_info',[])),'route-conflict')
        if 'endpoint' in self.policy:self.route_snapshot(complete=False)
        self.call('nft',['--check','-f','-'],input=firewall(self.policy).encode())

    def route_snapshot(self,*,complete):
        from ctflab_guest_routes import route_snapshot
        return route_snapshot(self.json('ip',['-4','-j','route','show','table','main']),self.policy,complete=complete)

    def route_add(self,route):
        require(route in self.policy['endpoint']['routes'],'permission-denied')
        expected=(route['destination'],route['gateway'],route['device'],route['source'])
        if expected in self.route_snapshot(complete=False):return {'state':'present'}
        self.call('ip',['-4','route','add',route['destination'],'via',route['gateway'],'dev',route['device'],
                        'proto','static','src',route['source']])
        require(expected in self.route_snapshot(complete=False),'state-conflict')
        return {'state':'added'}

    def docker_find(self,kind,name):
        args=[kind,'ls']+(['--all'] if kind=='container' else [])+['--format','{{.Name}}' if kind!='container' else '{{.Names}}']
        found=self.call('docker',args).splitlines()
        if name not in found:return None
        rows=self.json('docker',[kind,'inspect',name]);require(type(rows) is list and len(rows)==1,'identity-unknown')
        return rows[0]

    def network_fingerprint(self):
        """只读核对本次启动仍持有相同接口/转发/规则，不能沿用重启前账本。"""
        import ipaddress
        for family in ('-4','-6'):
            require(self.json('ip',[family,'-j','route','show','default'])==[],'route-conflict')
        require(self.call('sysctl',['-n','net.ipv4.ip_forward']).strip()==('0' if 'endpoint' in self.policy else '1'),'state-conflict')
        for nic in self.policy['interfaces'].values():
            rows=self.json('ip',['-j','address','show','dev',nic['device']])
            require(type(rows) is list and len(rows)==1 and rows[0]['address'].lower()==nic['mac']
                    and 'UP' in rows[0].get('flags',[]),'identity-unknown')
            addresses=rows[0].get('addr_info',[])
            require(len(addresses)==1 and addresses[0].get('family')=='inet'
                    and addresses[0].get('local')==nic['address']
                    and addresses[0].get('prefixlen')==ipaddress.IPv4Network(nic['cidr']).prefixlen,'state-conflict')
            require(self.call('sysctl',['-n','net.ipv6.conf.'+nic['device']+'.disable_ipv6']).strip()=='1','state-conflict')
        table='ctflab_'+self.policy['instance_uuid'].replace('-','')[:12]+'_g'+str(self.policy['generation'])
        rules=self.json('nft',['-j','list','table','inet',table])
        require(type(rules) is dict and type(rules.get('nftables')) is list,'state-conflict')
        def stable(value):
            if type(value) is list:return [stable(v) for v in value]
            if type(value) is dict:return {k:({} if k=='counter' else stable(v)) for k,v in value.items() if k!='handle'}
            return value
        data=[stable(v) for v in rules['nftables'] if type(v) is dict and 'metainfo' not in v]
        require(any(v.get('table',{}).get('name')==table for v in data),'state-conflict')
        if 'endpoint' in self.policy:data={'rules':data,'routes':self.route_snapshot(complete=True)}
        if 'routed' in self.policy:
            from ctflab_guest_routed import RoutedNetwork
            RoutedNetwork(self,self.policy).firewall_environment()
        return hashlib.sha256(canonical(data).encode()).hexdigest()

    def service(self,unit,action='status'):
        self.guard();self.check_tool('dnsmasq' if unit=='ctflab-dns.service' else 'chronyd')
        configs=service_config(self.policy,str(self.state))
        for filename,text in configs.items():
            candidate=self.state/filename;meta=candidate.lstat()
            require(stat.S_ISREG(meta.st_mode) and meta.st_uid==0 and meta.st_nlink==1
                    and not meta.st_mode&0o077 and candidate.read_text()==text,'state-conflict')
        expected=service_units();require(unit in expected and action in ('status','start','stop'))
        path=Path('/etc/systemd/system')/unit
        info=path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022
                and path.read_text()==expected[unit],'permission-denied')
        raw=self.call('systemctl',['show',unit,'--property=FragmentPath,DropInPaths,NeedDaemonReload,Restart,SendSIGKILL,ActiveState,MainPID'])
        values=dict(line.split('=',1) for line in raw.splitlines() if '=' in line)
        require(values.get('FragmentPath')==str(path) and values.get('DropInPaths')==''
                and values.get('NeedDaemonReload')=='no' and values.get('Restart')=='no'
                and values.get('SendSIGKILL')=='no','identity-unknown')
        if action!='status':self.call('systemctl',[action,'--no-block',unit])
        return {'state':values.get('ActiveState','unknown'),'pid':int(values.get('MainPID','0'))}


class GuestAgent:
    """每次副作用前独立提交意图。中断后只读恢复，不自动重放。"""
    def __init__(self,root,envelope,backend):
        self.root=Path(root);self.policy=verify_policy(envelope);self.backend=backend;self.envelope=envelope
        if not self.root.exists():private_directory(self.root)
        guard(self.root)
        config=self.root/'policy.json'
        if config.exists():require(json.loads(config.read_text())==envelope,'state-conflict')
        else:private_file(config,envelope)
        self.database=self.root/'agent.sqlite3'
        if not self.database.exists():
            fd=os.open(self.database,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
            with closing(sqlite3.connect(self.database)) as db:
                db.executescript('CREATE TABLE operations(id TEXT PRIMARY KEY,action TEXT,digest TEXT,result TEXT);'
                                 'CREATE TABLE effects(operation TEXT,step TEXT,result TEXT,PRIMARY KEY(operation,step));')
        guard(self.database)
        self.gate=self.root/'gate.lock'
        if not self.gate.exists():private_file(self.gate,{})
        self.labels={'org.ctflab.instance':self.policy['instance_uuid'],'org.ctflab.generation':str(self.policy['generation']),
                     'org.ctflab.policy':self.policy['policy_sha256']}
        self.prefix='ctflab-'+self.policy['instance_uuid']+'-g'+str(self.policy['generation'])

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.database,timeout=0)
        try:db.execute('PRAGMA synchronous=FULL');yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    @contextmanager
    def locked(self):
        guard(self.gate)
        if os.name=='nt':
            from ctflab_windows_native import state_lock
            with state_lock(self.gate):yield
        else:
            import fcntl
            with self.gate.open('rb') as stream:
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
                yield

    def effect(self,operation,step,call):
        with self.db() as db:db.execute('INSERT INTO effects VALUES(?,?,NULL)',(operation,step))
        result=call()
        with self.db() as db:db.execute('UPDATE effects SET result=? WHERE operation=? AND step=?',(canonical(result),operation,step))
        return result

    def owned(self,value,kind):
        require(type(value) is dict,'identity-unknown')
        labels=value.get('Config',{}).get('Labels',{}) if kind=='container' else value.get('Labels',{})
        require(all(labels.get(k)==v for k,v in self.labels.items()),'identity-unknown')
        if kind=='network':
            require(value.get('Internal') is True and value.get('EnableIPv6') is False and value.get('Driver')=='bridge'
                    and len(value.get('IPAM',{}).get('Config',[]))==1
                    and value['IPAM']['Config'][0].get('Subnet')==self.policy['container_cidr']
                    and value.get('Options',{}).get('com.docker.network.bridge.name')==self.policy['container_bridge'],'identity-unknown')
        if kind=='volume':require(value.get('Driver')=='local' and not value.get('Options'),'identity-unknown')
        return value

    def container_owned(self,value,name):
        self.owned(value,'container');spec=self.policy['containers'][name]
        config=value.get('Config',{});host=value.get('HostConfig',{})
        require(config.get('Image')==self.image_ref(spec['image']) and config.get('User')==spec['user']
                and host.get('ReadonlyRootfs') is True and host.get('Privileged') is False
                and host.get('CapAdd') in (None,[]) and 'ALL' in host.get('CapDrop',[])
                and any(s in ('no-new-privileges','no-new-privileges:true') for s in host.get('SecurityOpt',[]))
                and host.get('NetworkMode')==('none' if 'routed' in self.policy else self.prefix+'-network')
                and not host.get('Binds') and not host.get('Devices') and not host.get('PortBindings')
                and host.get('PidMode','')=='' and host.get('IpcMode','private') in ('','private')
                and not host.get('VolumesFrom') and host.get('Memory')==spec['memory_mb']*1024**2
                and host.get('MemorySwap')==spec['memory_mb']*1024**2 and host.get('NanoCpus')==spec['cpus']*10**9
                and host.get('PidsLimit')==128 and host.get('RestartPolicy',{}).get('Name')=='no'
                and host.get('LogConfig',{}).get('Type')=='local'
                and host.get('LogConfig',{}).get('Config',{}).get('max-size')=='4m'
                and host.get('LogConfig',{}).get('Config',{}).get('max-file')=='2','identity-unknown')
        mounts=value.get('Mounts',[])
        require(type(mounts) is list and all(m.get('Type')!='tmpfs' or m.get('Destination')=='/tmp' for m in mounts),'identity-unknown')
        mounts=[m for m in mounts if m.get('Type')!='tmpfs']
        require(set(host.get('Tmpfs',{}))=={'/tmp'} and
                set(host['Tmpfs']['/tmp'].split(','))=={'rw','noexec','nosuid','size=64m'},'identity-unknown')
        expected={self.prefix+'-'+volume:target for volume,target in spec['volumes'].items()}
        require(type(mounts) is list and len(mounts)==len(expected)
                and {m.get('Name') for m in mounts}==set(expected)
                and all(m.get('Type')=='volume' and m.get('Name') in expected and m.get('Destination')==expected[m['Name']] for m in mounts),'identity-unknown')
        return value

    def services_action(self,op,action):
        self.network_ready();units=service_units()
        for unit in units:self.backend.service(unit) # 所有unit先核验，不能半途才发现越权配置。
        for unit in sorted(units,reverse=action=='services-stop'):
            self.effect(op,action+'-'+unit,lambda u=unit:self.backend.service(u,'start' if action=='services-start' else 'stop'))
        deadline=time.monotonic()+20
        while True:
            values=[self.backend.service(unit) for unit in units]
            if action=='services-start' and all(v['state']=='active' and v['pid']>0 for v in values):
                return {'state':'services-running','service_verified':False,'time_scope':'local-reference-not-trusted-utc'}
            if action=='services-stop' and all(v['state']=='inactive' and v['pid']==0 for v in values):
                return {'state':'services-stopped','service_verified':False}
            require(time.monotonic()<deadline,'stop-timeout');time.sleep(.1)

    def label_args(self):return [item for k,v in self.labels.items() for item in ('--label',k+'='+v)]

    def network_apply(self,op):
        self.backend.network_preflight()
        self.effect(op,'forward-off',lambda:self.backend.call('sysctl',['-w','net.ipv4.ip_forward=0']))
        terminal='endpoint' in self.policy
        if terminal:self.effect(op,'firewall',lambda:self.backend.call('nft',['-f','-'],input=firewall(self.policy).encode()))
        for nic in self.policy['interfaces'].values():
            # replace仅触及已按MAC核验的专用来宾网卡；没有宿主入口。
            import ipaddress
            address=nic['address']+'/'+str(ipaddress.IPv4Network(nic['cidr']).prefixlen)
            self.effect(op,'address-'+nic['id'],lambda n=nic,a=address:self.backend.call('ip',['address','replace',a,'dev',n['device']]))
            self.effect(op,'up-'+nic['id'],lambda n=nic:self.backend.call('ip',['link','set','dev',n['device'],'up']))
            self.effect(op,'ipv6-off-'+nic['id'],lambda n=nic:self.backend.call('sysctl',['-w','net.ipv6.conf.'+n['device']+'.disable_ipv6=1']))
        if terminal:
            for index,route in enumerate(self.policy['endpoint']['routes']):
                self.effect(op,'route-'+str(index),lambda r=route:self.backend.route_add(r))
        else:self.effect(op,'firewall',lambda:self.backend.call('nft',['-f','-'],input=firewall(self.policy).encode()))
        for name,text in service_config(self.policy,str(self.root)).items():
            self.effect(op,'config-'+name,lambda n=name,t=text:self.write_config(n,t))
        self.effect(op,'forward-final' if terminal else 'forward-on',lambda:self.backend.call(
            'sysctl',['-w','net.ipv4.ip_forward='+('0' if terminal else '1')]))
        self.effect(op,'network-proof',lambda:self.write_network_proof(op))
        return {'state':'network-configured','network_verified':False,'services_started':False}

    def write_config(self,name,text):
        path=self.root/name
        if path.exists():
            guard(path);require(path.read_text()==text,'state-conflict')
            return {'sha256':digest(path)}
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:stream.write(text);stream.flush();os.fsync(stream.fileno())
        return {'sha256':digest(path)}

    def network_ready(self):
        with self.db() as db:
            rows=db.execute("SELECT result FROM operations WHERE action='network-apply' AND result IS NOT NULL").fetchall()
        require(any(json.loads(r[0]).get('state')=='network-configured' for r in rows),'state-conflict')
        self.network_proof()

    def network_proof(self):
        path=guard(self.root/'network-proof.json');require(path.stat().st_size<=4096)
        proof=json.loads(path.read_text())
        require(type(proof) is dict and set(proof) in ({'policy_sha256','rules_sha256'},
                                                      {'policy_sha256','rules_sha256','operation_id'}),'state-conflict')
        if 'operation_id' in proof:uuid_text(proof['operation_id'])
        require(proof['policy_sha256']==self.policy['policy_sha256'] and
                proof['rules_sha256']==self.backend.network_fingerprint(),'state-conflict')
        return proof

    def write_network_proof(self,operation):
        proof={'policy_sha256':self.policy['policy_sha256'],'rules_sha256':self.backend.network_fingerprint()}
        result=self.write_config('network-proof.json',canonical(proof))
        self.write_config('network-proof-'+operation+'.json',canonical(dict(proof,operation_id=operation)))
        return result

    def reconcile_network(self,operation):
        """显式结清已全部配置、仅末尾记录丢失的网络操作；不重新执行任何工具。"""
        uuid_text(operation)
        with self.locked():
            self.backend.guard()
            require(json.loads(guard(self.root/'policy.json').read_text())==self.envelope,'identity-unknown')
            with self.db() as db:
                row=db.execute('SELECT action,digest,result FROM operations WHERE id=?',(operation,)).fetchone()
                require(row is not None and row[0]=='network-apply','state-conflict')
                if row[2] is not None:return json.loads(row[2])
                require([r[0] for r in db.execute('SELECT id FROM operations WHERE result IS NULL')]==[operation],'identity-unknown')
                effects=dict(db.execute('SELECT step,result FROM effects WHERE operation=?',(operation,)))
            current=self.network_proof()
            proof_path=self.root/('network-proof-'+operation+'.json')
            require(proof_path.exists(),'identity-unknown');guard(proof_path);require(proof_path.stat().st_size<=4096)
            proof=json.loads(proof_path.read_text())
            require(proof=={'policy_sha256':current['policy_sha256'],'rules_sha256':current['rules_sha256'],
                            'operation_id':operation},'identity-unknown')
            terminal='endpoint' in self.policy
            expected={'forward-off','firewall','network-proof','forward-final' if terminal else 'forward-on'}
            for nic in self.policy['interfaces'].values():
                expected.update(prefix+nic['id'] for prefix in ('address-','up-','ipv6-off-'))
            if terminal:expected.update('route-'+str(i) for i in range(len(self.policy['endpoint']['routes'])))
            for name,text in service_config(self.policy,str(self.root)).items():
                expected.add('config-'+name)
                path=guard(self.root/name);require(path.stat().st_size<=65536 and path.read_text()==text,'state-conflict')
                require(effects.get('config-'+name)==canonical({'sha256':digest(path)}),'state-conflict')
            require(set(effects)==expected and all(result is not None for step,result in effects.items() if step!='network-proof'),'identity-unknown')
            proof_result=canonical({'sha256':digest(self.root/'network-proof.json')})
            require(effects['network-proof'] in (None,proof_result),'state-conflict')
            resolution={'schema':1,'operation_id':operation,'policy_sha256':self.policy['policy_sha256'],
                        'request_sha256':row[1],'proof_sha256':digest(proof_path),
                        'rules_sha256':proof['rules_sha256'],'decision':'record-existing-network','commands_replayed':False}
            path=self.root/('network-reconciled-'+operation+'.json')
            if path.exists():require(json.loads(guard(path).read_text())==resolution,'state-conflict')
            else:private_file(path,resolution)
            result={'state':'network-configured','network_verified':False,'services_started':False,
                    'reconciled':True,'automatic_replay':False}
            self.backend.guard()
            with self.db() as db:
                db.execute('UPDATE effects SET result=? WHERE operation=? AND step=?',(proof_result,operation,'network-proof'))
                require(db.execute('UPDATE operations SET result=? WHERE id=? AND result IS NULL',(canonical(result),operation)).rowcount==1,'state-conflict')
            return result

    def container_prepare(self,op):
        require(bool(self.policy['containers']),'capability-unverified');self.network_ready()
        network=self.prefix+'-network'
        if 'routed' not in self.policy:require(self.backend.docker_find('network',network) is None,'state-conflict')
        imports={}
        for reference,sha in self.policy.get('images',{}).items():
            from ctflab_oci import inspect_archive
            path=guard(self.root/'oci'/sha)
            imports[reference]=(path,inspect_archive(path,sha,reference.rsplit('@sha256:',1)[1],self.policy['image_architecture']))
        for name,spec in self.policy['containers'].items():
            if spec['image'] not in imports:
                image=self.backend.json('docker',['image','inspect',spec['image']])
                require(type(image) is list and len(image)==1 and spec['image'] in (image[0].get('RepoDigests') or []),'state-conflict')
            require(self.backend.docker_find('container',self.prefix+'-'+name) is None,'state-conflict')
            for volume in spec['volumes']:
                require(self.backend.docker_find('volume',self.prefix+'-'+volume) is None,'state-conflict')
        if imports:
            work=self.root/'oci-work'
            if not work.exists():self.effect(op,'oci-work',lambda:private_directory(work))
            guard(work)
            attempt=work/op
            self.effect(op,'oci-attempt',lambda:private_directory(attempt))
            for index,(reference,(path,report)) in enumerate(sorted(imports.items())):
                from ctflab_oci import convert
                destination=attempt/str(index)
                self.effect(op,'oci-convert-'+str(index),lambda p=path,d=destination,r=report:convert(
                    p,d,r['archive_sha256'],r['manifest_sha256'],r['architecture']))
                self.effect(op,'oci-load-'+str(index),lambda d=destination:self.backend.call(
                    'docker',['image','load','--quiet','--input',str(d/'docker.tar')],timeout=120))
                self.verify_image(report)
                saved={key:report[key] for key in ('archive_sha256','manifest_sha256','config_sha256','architecture','diff_ids')}
                saved.update(reference=reference,policy_sha256=self.policy['policy_sha256'])
                self.effect(op,'oci-record-'+str(index),lambda r=reference,s=saved:self.write_config(self.image_record(r).name,canonical(s)))
        for step,kind,name,args in self.preparation_steps(op):
            self.effect(op,step,lambda k=kind,n=name,a=args:self.create_resource(k,n,a,op))
        with self.db() as db:recorded=dict(db.execute('SELECT step,result FROM effects WHERE operation=?',(op,)))
        for step,kind,name,args in self.preparation_steps(op):
            require(json.loads(recorded[step])==self.resource_identity(self.backend.docker_find(kind,name),kind,name,op),'identity-unknown')
        return {'state':'containers-prepared','service_verified':False}

    def preparation_steps(self,operation,*,resolved=None):
        """同一代次的创建配方；恢复只可执行尚无意图的步骤。"""
        uuid_text(operation)
        labels=[*self.label_args(),'--label','org.ctflab.prepare='+operation]
        network=self.prefix+'-network'
        steps=[] if 'routed' in self.policy else [('network','network',network,['network','create','--internal','--ipv6=false',
                '--subnet',self.policy['container_cidr'],'--opt',
                'com.docker.network.bridge.name='+self.policy['container_bridge'],*labels,network])]
        for name,spec in self.policy['containers'].items():
            for volume in spec['volumes']:
                target=self.prefix+'-'+volume
                steps.append(('volume-'+volume,'volume',target,['volume','create',*labels,target]))
            args=['container','create','--name',self.prefix+'-'+name,'--pull=never','--read-only','--cap-drop=ALL',
                  '--security-opt=no-new-privileges','--pids-limit=128','--memory',str(spec['memory_mb'])+'m',
                  '--memory-swap',str(spec['memory_mb'])+'m','--cpus',str(spec['cpus']),'--user',spec['user'],
                  '--network',network,'--network-alias',name,'--ip',spec['address'],'--restart=no','--log-driver=local',
                  '--log-opt','max-size=4m','--log-opt','max-file=2','--tmpfs','/tmp:rw,noexec,nosuid,size=64m',*labels]
            if 'routed' in self.policy:
                start=args.index('--network');end=args.index('--restart=no');args[start:end]=['--network','none']
            for volume,target in spec['volumes'].items():args+=['--mount',f'type=volume,source={self.prefix}-{volume},target={target}']
            args.append(resolved[spec['image']] if resolved is not None and spec['image'] in resolved else self.image_ref(spec['image']))
            steps.append(('container-'+name,'container',self.prefix+'-'+name,args))
        return steps

    def resource_identity(self,value,kind,name,operation,*,stopped=True):
        self.owned(value,kind)
        labels=value.get('Config',{}).get('Labels',{}) if kind=='container' else value.get('Labels',{})
        require(labels.get('org.ctflab.prepare')==operation,'identity-unknown')
        if kind=='container':
            node=name[len(self.prefix)+1:];self.container_owned(value,node)
            running=value.get('State',{}).get('Running')
            require(type(running) is bool and (not stopped or not running),'resource-busy')
            if 'routed' in self.policy:
                attached=value.get('NetworkSettings',{}).get('Networks')
                require(type(attached) is dict and set(attached)<={'none'} and all(
                    not entry.get('IPAddress') and not entry.get('GlobalIPv6Address') for entry in attached.values()),'identity-unknown')
            else:
                network=self.prefix+'-network';attached=value.get('NetworkSettings',{}).get('Networks')
                require(type(attached) is dict and set(attached)=={network},'identity-unknown')
                endpoint=attached[network];require(type(endpoint) is dict,'identity-unknown')
                live_network=self.backend.docker_find('network',network)
                self.owned(live_network,'network')
                require(endpoint.get('NetworkID')==live_network.get('Id')
                        and type(endpoint.get('IPAMConfig')) is dict
                        and endpoint['IPAMConfig'].get('IPv4Address')==self.policy['containers'][node]['address']
                        and not endpoint['IPAMConfig'].get('IPv6Address')
                        and endpoint.get('IPAddress','') in ('',self.policy['containers'][node]['address'])
                        and not endpoint.get('GlobalIPv6Address'),'identity-unknown')
        import re
        if kind in ('network','container'):
            identity=value.get('Id');require(type(identity) is str and re.fullmatch('[0-9a-f]{64}',identity),'identity-unknown')
        else:
            created=value.get('CreatedAt');require(type(created) is str and 1<=len(created)<=96,'identity-unknown')
            identity=hashlib.sha256(canonical({'created':created,'name':name,'labels':labels}).encode()).hexdigest()
        return {'kind':kind,'name':name,'identity':identity}

    def preparation_owner(self,value,name):
        operation=value.get('Config',{}).get('Labels',{}).get('org.ctflab.prepare')
        with self.db() as db:
            rows=db.execute('SELECT operation,result FROM effects WHERE step=?',('container-'+name,)).fetchall()
        pinned=[(op,json.loads(encoded)) for op,encoded in rows if encoded is not None and type(json.loads(encoded)) is dict
                and json.loads(encoded).get('kind')=='container']
        if pinned:
            require(len(pinned)==1 and operation==pinned[0][0] and value.get('Id')==pinned[0][1]['identity'],'identity-unknown')
        return operation

    def prepared_identity(self,operation):
        """新准备记录在启动/停止前后重新绑定网络/卷/容器；旧记录不推断新身份。"""
        uuid_text(operation)
        with self.db() as db:
            row=db.execute('SELECT action,result FROM operations WHERE id=?',(operation,)).fetchone()
            require(row is not None and row[0]=='containers-prepare' and row[1] is not None
                    and json.loads(row[1]).get('state')=='containers-prepared','identity-unknown')
            effects=dict(db.execute('SELECT step,result FROM effects WHERE operation=?',(operation,)))
        for step,kind,name,args in self.preparation_steps(operation):
            require(effects.get(step) is not None,'identity-unknown')
            require(json.loads(effects[step])==self.resource_identity(self.backend.docker_find(kind,name),
                    kind,name,operation,stopped=False),'identity-unknown')

    def create_resource(self,kind,name,args,operation):
        self.backend.call('docker',args)
        return self.resource_identity(self.backend.docker_find(kind,name),kind,name,operation)

    def preparation_images(self,effects):
        """区分未登记load与已有load意图；后者只核验，不重发。"""
        resolved={};records={}
        for index,(reference,sha) in enumerate(sorted(self.policy.get('images',{}).items())):
            from ctflab_oci import inspect_archive
            report=inspect_archive(guard(self.root/'oci'/sha),sha,reference.rsplit('@sha256:',1)[1],self.policy['image_architecture'])
            pending='oci-load-'+str(index) not in effects
            resolved[reference]='sha256:'+report['config_sha256'] if pending else self.verify_image(report)
            saved={key:report[key] for key in ('archive_sha256','manifest_sha256','config_sha256','architecture','diff_ids')}
            saved.update(reference=reference,policy_sha256=self.policy['policy_sha256'])
            path=self.image_record(reference)
            if path.exists():
                guard(path);require(path.stat().st_size<=32768 and json.loads(path.read_text())==saved,'identity-unknown')
            records[reference]={'record':saved,'present':path.exists(),'image_id':resolved[reference],
                'load_state':'not-started' if pending else 'observed-loaded'}
        return resolved,records

    def preparation_snapshot(self,operation):
        """只读事实；未知但查无资源仍不允许重建，以免掩盖丢失数据。调用者持有来宾门。"""
        uuid_text(operation);self.backend.guard()
        require(json.loads(guard(self.root/'policy.json').read_text())==self.envelope,'identity-unknown')
        require(self.policy['containers'],'capability-unverified')
        with self.db() as db:
            row=db.execute('SELECT action,digest,result FROM operations WHERE id=?',(operation,)).fetchone()
            require(row is not None and row[0]=='containers-prepare','state-conflict')
            if row[2] is not None:
                result=json.loads(row[2]);require(result.get('state')=='containers-prepared','state-conflict')
                return {'state':'completed','operation_id':operation,'policy_sha256':self.policy['policy_sha256'],'result':result,'automatic_replay':False}
            require([r[0] for r in db.execute('SELECT id FROM operations WHERE result IS NULL')]==[operation],'identity-unknown')
            effects=dict(db.execute('SELECT step,result FROM effects WHERE operation=?',(operation,)))
        request={'schema':1,'instance_uuid':self.policy['instance_uuid'],'generation':self.policy['generation'],
                 'policy_sha256':self.policy['policy_sha256'],'operation_id':operation,'action':'containers-prepare'}
        require(row[1]==hashlib.sha256(canonical(request).encode()).hexdigest(),'identity-unknown')
        self.network_ready()
        resolved,images=self.preparation_images(effects)
        for spec in self.policy['containers'].values():
            if spec['image'] in resolved:continue
            rows=self.backend.json('docker',['image','inspect',spec['image']])
            require(type(rows) is list and len(rows)==1 and spec['image'] in (rows[0].get('RepoDigests') or []),'state-conflict')
        steps=self.preparation_steps(operation,resolved=resolved)
        image_steps={'oci-work','oci-attempt'} if images else set()
        image_steps.update(prefix+str(i) for i in range(len(images)) for prefix in ('oci-convert-','oci-load-','oci-record-'))
        # 恢复转换只写新的本地目录；原未知转换及装载意图永久保留。
        import re
        recovery_steps={step for step in effects if re.fullmatch(r'oci-resume-[0-9a-f]{64}',step) or
            (re.fullmatch(r'oci-reconvert-[0-9a-f]{64}-[0-9]+',step) and int(step.rsplit('-',1)[1])<len(images))}
        require(len(recovery_steps)<=16*(len(images)+1),'storage-insufficient')
        require(set(effects)<={step for step,_,_,_ in steps}|image_steps|recovery_steps,'identity-unknown')
        values=[]
        for step,kind,name,args in steps:
            live=self.backend.docker_find(kind,name)
            identity=self.resource_identity(live,kind,name,operation) if live is not None else None
            if step not in effects:
                require(identity is None,'identity-unknown');state='not-started'
            elif effects[step] is None:state='observed-unrecorded' if identity else 'unknown-absent'
            elif identity is None:state='recorded-missing'
            else:
                require(json.loads(effects[step])==identity,'identity-unknown');state='recorded'
            values.append({'step':step,'state':state,'resource':identity})
        result={'state':'preparation-observed','operation_id':operation,'policy_sha256':self.policy['policy_sha256'],
                'request_sha256':row[1],'network_proof':self.network_proof(),'steps':values,
                'images':images,'oci_effects':{step:('unknown' if result is None else 'recorded') for step,result in sorted(effects.items()) if step in image_steps|recovery_steps},
                'can_resume':all(v['state'] not in ('unknown-absent','recorded-missing') for v in values),
                'automatic_replay':False,'services_started':False,'service_verified':False}
        result['resume_sha256']=hashlib.sha256(canonical(result).encode()).hexdigest()
        return result

    def inspect_preparation(self,operation):
        with self.locked():return self.preparation_snapshot(operation)

    def resume_preparation(self,operation,expected):
        """管理员明确接受只读快照后续建；不重发已有未知创建，不删除/启动资源。"""
        require(type(expected) is str and len(expected)==64 and all(c in '0123456789abcdef' for c in expected))
        with self.locked():
            snapshot=self.preparation_snapshot(operation)
            if snapshot['state']=='completed':return dict(snapshot['result'],historical_result=True,automatic_replay=False)
            require(snapshot['resume_sha256']==expected and snapshot['can_resume'],'state-conflict')
            intent=self.root/('preparation-resume-'+operation+'-'+expected+'.json')
            if intent.exists():require(json.loads(guard(intent).read_text())==snapshot,'state-conflict')
            else:private_file(intent,snapshot)
            pending=[(index,reference,value) for index,(reference,value) in enumerate(sorted(snapshot['images'].items()))
                     if value['load_state']=='not-started']
            if pending:
                # 只有从未登记过load意图才可新发一次；目录/转换中断保留原件，重新快照另建目录。
                require(len(list(self.root.glob('oci-resume-'+operation+'-*')))<16,'storage-insufficient')
                destination=self.root/('oci-resume-'+operation+'-'+expected)
                self.effect(operation,'oci-resume-'+expected,lambda:private_directory(destination))
                for index,reference,value in pending:
                    from ctflab_oci import convert
                    saved=value['record'];target=destination/str(index)
                    report=self.effect(operation,'oci-reconvert-'+expected+'-'+str(index),lambda t=target,r=saved:convert(
                        guard(self.root/'oci'/r['archive_sha256']),t,r['archive_sha256'],r['manifest_sha256'],r['architecture']))
                    # 归档在转换中再次校验，装载前也重核策略和来宾身份。
                    self.backend.guard()
                    require(json.loads(guard(self.root/'policy.json').read_text())==self.envelope,'identity-unknown')
                    with self.db() as db:
                        require(not db.execute('SELECT 1 FROM effects WHERE operation=? AND step=?',
                            (operation,'oci-load-'+str(index))).fetchone(),'state-conflict')
                    self.effect(operation,'oci-load-'+str(index),lambda t=target:self.backend.call(
                        'docker',['image','load','--quiet','--input',str(t/'docker.tar')],timeout=120))
                    require(self.verify_image(report)==value['image_id'],'identity-unknown')
            for reference,value in snapshot['images'].items():
                self.write_config(self.image_record(reference).name,canonical(value['record']))
                require(self.image_ref(reference)==value['image_id'],'identity-unknown')
            states={v['step']:v for v in snapshot['steps']}
            for step,kind,name,args in self.preparation_steps(operation):
                value=states[step]
                if value['state']=='not-started':
                    self.effect(operation,step,lambda k=kind,n=name,a=args:self.create_resource(k,n,a,operation))
                elif value['state']=='observed-unrecorded':
                    require(self.resource_identity(self.backend.docker_find(kind,name),kind,name,operation)==value['resource'],'identity-unknown')
                    with self.db() as db:
                        require(db.execute('UPDATE effects SET result=? WHERE operation=? AND step=? AND result IS NULL',
                            (canonical(value['resource']),operation,step)).rowcount==1,'state-conflict')
            current=self.preparation_snapshot(operation)
            require(all(v['state']=='recorded' for v in current['steps']),'identity-unknown')
            result={'state':'containers-prepared','service_verified':False,'reconciled':True,
                    'automatic_replay':False,'services_started':False,
                    'oci_load_replayed':False,'oci_loads_first_started':len(pending),'oci_unknown_effects_preserved':any(s=='unknown' for s in snapshot['oci_effects'].values())}
            with self.db() as db:
                require(db.execute('UPDATE operations SET result=? WHERE id=? AND result IS NULL',
                    (canonical(result),operation)).rowcount==1,'state-conflict')
            return result

    def image_record(self,reference):
        return self.root/('oci-image-'+hashlib.sha256(reference.encode()).hexdigest()+'.json')

    def verify_image(self,report):
        image_id='sha256:'+report['config_sha256']
        rows=self.backend.json('docker',['image','inspect',image_id])
        require(type(rows) is list and len(rows)==1 and rows[0].get('Id')==image_id
                and rows[0].get('Os')=='linux' and rows[0].get('Architecture')==report['architecture']
                and rows[0].get('RootFS',{}).get('Type')=='layers'
                and rows[0]['RootFS'].get('Layers',[])==report['diff_ids'],'identity-unknown')
        return image_id

    def image_ref(self,reference):
        if reference not in self.policy.get('images',{}):return reference
        path=guard(self.image_record(reference));require(path.stat().st_size<=32768)
        record=json.loads(path.read_text())
        require(type(record) is dict and set(record)=={'archive_sha256','manifest_sha256','config_sha256','architecture',
                                                        'diff_ids','reference','policy_sha256'})
        require(record['reference']==reference and record['policy_sha256']==self.policy['policy_sha256']
                and record['archive_sha256']==self.policy['images'][reference]
                and record['manifest_sha256']==reference.rsplit('@sha256:',1)[1]
                and record['architecture']==self.policy['image_architecture'],'identity-unknown')
        from ctflab_oci import checksum
        checksum(record['config_sha256'])
        return self.verify_image(record)

    def container_action(self,op,action):
        require(bool(self.policy['containers']),'capability-unverified');self.network_ready();values={};prepared=set()
        # 先核验所有资源，不能停到一半才发现另一节点属于其他实例。
        for name in self.policy['containers']:
            value=self.backend.docker_find('container',self.prefix+'-'+name)
            require(value is not None,'identity-unknown');self.container_owned(value,name)
            operation=self.preparation_owner(value,name)
            if operation is not None:prepared.add(operation)
            import re
            require(isinstance(value.get('Id'),str) and re.fullmatch('[0-9a-f]{64}',value['Id']),'identity-unknown');values[name]=value
        for operation in prepared:self.prepared_identity(operation)
        routed=None
        if 'routed' in self.policy:
            from ctflab_guest_routed import RoutedNetwork
            routed=RoutedNetwork(self.backend,self.policy)
            if action=='containers-start':routed.preflight()
            else:
                for name,value in values.items():
                    if value.get('State',{}).get('Running') is True:self.routed_proof(name,value,routed)
                if any(v.get('State',{}).get('Running') for v in values.values()):routed.host_routes(complete=True)
        order=sorted(values,reverse=action=='containers-stop')
        for name in order:
            value=values[name];running=value.get('State',{}).get('Running')
            require(type(running) is bool,'identity-unknown')
            if action=='containers-start':
                require(not running,'state-conflict')
                self.effect(op,'start-'+name,lambda v=value:self.backend.call('docker',['container','start',v['Id']]))
            elif running:
                # docker stop超时会SIGKILL，故只发一次显式SIGTERM并等待，不回退强杀。
                self.effect(op,'stop-'+name,lambda v=value:self.backend.call('docker',['container','kill','--signal=SIGTERM',v['Id']]))
        deadline=time.monotonic()+15
        while True:
            states=[]
            for name,old in values.items():
                now=self.backend.docker_find('container',self.prefix+'-'+name)
                require(now is not None and now['Id']==old['Id'],'identity-unknown');self.container_owned(now,name)
                states.append(now['State']['Running'])
            for operation in prepared:self.prepared_identity(operation)
            expected=action=='containers-start'
            if all(s is expected for s in states):
                if routed and expected:
                    for name,value in values.items():
                        current=self.backend.docker_find('container',self.prefix+'-'+name)
                        proof=self.effect(op,'routing-'+name,lambda n=name,v=current:routed.attach(n,v['Id'],v['State']['Pid'],
                            lambda step,call:self.effect(op,step,call)))
                        self.effect(op,'routing-record-'+name,lambda n=name,p=proof:self.write_config('routing-'+op+'-'+n+'.json',canonical(p)))
                    routed.host_routes(complete=True)
                return {'state':'containers-running' if expected else 'containers-stopped','service_verified':False}

            require(time.monotonic()<deadline,'stop-timeout');time.sleep(.1)

    def routed_proof(self,name,value,routed):
        observed=routed.inspect(name,value['Id'],value['State'].get('Pid'))
        paths=list(self.root.glob('routing-*-'+name+'.json'));require(len(paths)<=4096,'storage-insufficient')
        require(any(guarded_file(p)==observed for p in paths),'identity-unknown')
        return observed

    def status(self):
        result={}
        for name in self.policy['containers']:
            value=self.backend.docker_find('container',self.prefix+'-'+name)
            if value is None:result[name]={'state':'absent'}
            else:
                self.owned(value,'container');state=value['State']
                result[name]={'state':'process-running' if state['Running'] else 'stopped','id':value['Id']}
        with self.db() as db:
            pending=[{'operation_id':r[0],'action':r[1]} for r in db.execute('SELECT id,action FROM operations WHERE result IS NULL')]
        return {'state':'observed','containers':result,'pending':pending,'automatic_replay':False,
                'network_verified':False,'service_verified':False}

    def dispatch(self,request):
        if hasattr(self.backend,'guard'):self.backend.guard()
        if type(request) is dict and request.get('action')=='configure':
            require(set(request)=={'schema','action','operation_id','envelope'} and type(request['schema']) is int and request['schema']==1)
            uuid_text(request['operation_id']);require(request['envelope']==self.envelope,'state-conflict')
            return {'state':'configured','automatic_replay':False,'capabilities':['preparation-inspect','preparation-resume']}
        if type(request) is dict and request.get('action') in ('preparation-inspect','preparation-resume'):
            action=request['action'];fields={'schema','instance_uuid','generation','policy_sha256','operation_id','action','target_operation_id'}
            if action=='preparation-resume':fields.add('expected_sha256')
            require(set(request)==fields and type(request['schema']) is int and request['schema']==1)
            uuid_text(request['operation_id']);uuid_text(request['target_operation_id'])
            require(request['instance_uuid']==self.policy['instance_uuid'] and type(request['generation']) is int
                and request['generation']==self.policy['generation'] and request['policy_sha256']==self.policy['policy_sha256'],'identity-unknown')
            if action=='preparation-inspect':return self.inspect_preparation(request['target_operation_id'])
            return self.resume_preparation(request['target_operation_id'],request['expected_sha256'])
        require(type(request) is dict and set(request)=={'schema','instance_uuid','generation','policy_sha256','operation_id','action'})
        require(type(request['schema']) is int and request['schema']==1)
        uuid_text(request['operation_id'])
        require(request['instance_uuid']==self.policy['instance_uuid'] and type(request['generation']) is int
                and request['generation']==self.policy['generation'] and request['policy_sha256']==self.policy['policy_sha256'],'state-conflict')
        action=request['action'];require(action in ('status','recover','operation-status','network-apply','services-start','services-stop',
                                                   'containers-prepare','containers-start','containers-stop','analysis-run'))
        if action in ('status','recover'):return self.status()
        if action=='operation-status':
            with self.db() as db:
                row=db.execute('SELECT action,result FROM operations WHERE id=?',(request['operation_id'],)).fetchone()
                effects=[{'step':r[0],'state':'recorded' if r[1] is not None else 'unknown'} for r in db.execute(
                    'SELECT step,result FROM effects WHERE operation=? ORDER BY rowid',(request['operation_id'],))]
            return {'state':'absent'} if row is None else {'state':'completed' if row[1] else 'unknown','action':row[0],
                    'result':json.loads(row[1]) if row[1] else None,'effects':effects,'automatic_replay':False}
        with self.locked():
            sha=hashlib.sha256(canonical(request).encode()).hexdigest()
            with self.db() as db:
                prior=db.execute('SELECT digest,result FROM operations WHERE id=?',(request['operation_id'],)).fetchone()
                if prior:
                    require(prior[0]==sha,'idempotency-conflict')
                    return json.loads(prior[1]) if prior[1] else {'state':'unknown','automatic_replay':False}
                require(not db.execute('SELECT 1 FROM operations WHERE result IS NULL').fetchone(),'identity-unknown')
                db.execute('INSERT INTO operations VALUES(?,?,?,NULL)',(request['operation_id'],action,sha))
            op=request['operation_id']
            try:
                if action=='analysis-run':
                    from ctflab_guest_analysis import OfflineAnalysis
                    result=OfflineAnalysis(self).run(op)
                elif action=='network-apply':result=self.network_apply(op)
                elif action in ('services-start','services-stop'):result=self.services_action(op,action)
                elif action=='containers-prepare':result=self.container_prepare(op)
                else:result=self.container_action(op,action)
            except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
                with self.db() as db:effects=db.execute('SELECT COUNT(*) FROM effects WHERE operation=?',(op,)).fetchone()[0]
                if effects:raise
                result={'state':'failed','error':exc.code if isinstance(exc,ContractError) else 'backend-failed',
                        'effects_started':False,'automatic_replay':False}
            with self.db() as db:db.execute('UPDATE operations SET result=? WHERE id=?',(canonical(result),op))
            return result


def parse_frame(raw):
    require(raw.endswith(b'\n') and len(raw)<=MAX_MESSAGE_BYTES+1)
    def unique(pairs):
        result={}
        for k,v in pairs:require(k not in result);result[k]=v
        return result
    return json.loads(raw.decode('utf-8'),object_pairs_hook=unique,parse_constant=lambda _:require(False))


def response(agent,request,value):
    if len(canonical(value).encode())>MAX_MESSAGE_BYTES-1024:
        value={'state':'unknown','error':'response-too-large','preserved':True,'automatic_replay':False}
    return {'schema':1,'instance_uuid':agent.policy['instance_uuid'],'generation':agent.policy['generation'],
            'policy_sha256':agent.policy['policy_sha256'],'operation_id':request.get('operation_id') if type(request) is dict else None,'result':value}


def serve(agent,source,destination):
    while True:
        raw=source.readline(MAX_MESSAGE_BYTES+2)
        if not raw:return 0
        if not raw.endswith(b'\n') or len(raw)>MAX_MESSAGE_BYTES+1:return 2
        request=None
        try:
            request=parse_frame(raw)
            value=agent.dispatch(request)
        except (OSError,ValueError,RuntimeError,KeyError,TypeError,sqlite3.Error) as exc:
            value={'state':'unknown','preserved':True,'automatic_replay':False,
                   'error':exc.code if isinstance(exc,ContractError) else 'backend-failed'}
        destination.write((canonical(response(agent,request,value))+'\n').encode());destination.flush()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--policy',type=Path)
    actions=parser.add_mutually_exclusive_group()
    actions.add_argument('--reconcile-network',help='专用来宾内显式结清该UUID的末尾记录；不重放网络命令')
    actions.add_argument('--inspect-preparation',help='只读检查该UUID的容器资源准备现场')
    actions.add_argument('--resume-preparation',help='明确恢复该UUID尚未开始的资源创建步骤')
    parser.add_argument('--expected-sha256',help='恢复前只读快照的resume_sha256')
    args=parser.parse_args(argv)
    try:
        require(bool(args.expected_sha256)==bool(args.resume_preparation))
        require(platform.system()=='Linux' and os.geteuid()==0,'unsupported-platform')
        require(DEVICE.is_char_device(),'capability-unverified')
        envelope=guarded_file(args.policy) if args.policy else guarded_file(STATE/'policy.json') if (STATE/'policy.json').exists() else None
        agent=None
        if envelope is not None:
            policy=verify_policy(envelope);backend=NativeBackend(policy);agent=GuestAgent(STATE,envelope,backend)
        if args.reconcile_network:
            require(agent is not None,'state-conflict')
            print(canonical(agent.reconcile_network(args.reconcile_network)));return 0
        if args.inspect_preparation or args.resume_preparation:
            require(agent is not None,'state-conflict')
            result=agent.inspect_preparation(args.inspect_preparation) if args.inspect_preparation else agent.resume_preparation(args.resume_preparation,args.expected_sha256)
            print(canonical(result));return 0
        while True:
            with DEVICE.open('r+b',buffering=0) as channel:
                if agent is None:
                    raw=channel.readline(MAX_MESSAGE_BYTES+2)
                    if not raw:time.sleep(.2);continue
                    request=parse_frame(raw)
                    require(type(request) is dict and set(request)=={'schema','action','operation_id','envelope'}
                            and type(request['schema']) is int and request['schema']==1 and request['action']=='configure')
                    uuid_text(request['operation_id'])
                    envelope=request['envelope'];policy=verify_policy(envelope)
                    backend=NativeBackend(policy);agent=GuestAgent(STATE,envelope,backend)
                    channel.write((canonical(response(agent,request,agent.dispatch(request)))+'\n').encode());channel.flush()
                serve(agent,channel,channel)
            time.sleep(.2)
    except (OSError,ValueError,RuntimeError,KeyError,TypeError):
        print(canonical({'state':'refused','host_network_modified':False,'preserved':True}));return 2


if __name__=='__main__':raise SystemExit(main())
