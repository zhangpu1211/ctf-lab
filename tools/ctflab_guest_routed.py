"""专用容器来宾的点对点三层网；不创建桥、默认路由、NAT或宿主入口。"""
from contextlib import contextmanager
import hashlib
import ipaddress
import os
import re
from pathlib import Path

from ctflab_contract import canonical,require


def interface_names(plan,name):
    seed=canonical([plan['instance_uuid'],plan['generation'],name]).encode()
    suffix=hashlib.sha256(seed).hexdigest()[:11]
    return 'ch'+suffix,'cp'+suffix


def route_plan(policy,name):
    require(policy.get('routed',{}).get('mode')=='point-to-point-v1' and name in policy['containers'])
    host,peer=interface_names(policy,name);address=policy['containers'][name]['address']
    remotes=set()
    for rule in policy['rules']:
        a,b=rule['source'],rule['destination']
        if a['network']=='container:'+name:remotes.add(b['address'])
        if b['network']=='container:'+name:remotes.add(a['address'])
    return {'host':host,'peer':peer,'address':address,'gateway':policy['routed']['gateway'],
            'remotes':sorted(remotes),'interface':'ctf0'}


def namespace_binding(backend,container_id,pid):
    """查询只读Docker身份并复核/proc启动时间；不把PID存在当归属。"""
    from ctflab_linux_native import parse_stat
    require(type(pid) is int and pid>0,'identity-unknown')
    rows=backend.json('docker',['container','inspect',container_id])
    require(type(rows) is list and len(rows)==1 and rows[0].get('Id')==container_id
            and rows[0].get('State',{}).get('Running') is True and rows[0]['State'].get('Pid')==pid,'identity-unknown')
    first=parse_stat((Path('/proc')/str(pid)/'stat').read_text())
    require(first[0] not in ('Z','X'),'identity-unknown')
    namespace=Path('/proc')/str(pid)/'ns/net'
    info=namespace.stat()
    second=parse_stat((Path('/proc')/str(pid)/'stat').read_text())
    require(first[1]==second[1] and second[0] not in ('Z','X'),'identity-unknown')
    return {'pid':pid,'ticks':first[1],'namespace_device':info.st_dev,'namespace_inode':info.st_ino}


@contextmanager
def retained_namespace(backend,container_id,pid):
    before=namespace_binding(backend,container_id,pid)
    fd=os.open('/proc/'+str(pid)+'/ns/net',os.O_RDONLY|os.O_CLOEXEC)
    try:
        held=os.fstat(fd)
        require((held.st_dev,held.st_ino)==(before['namespace_device'],before['namespace_inode'])
                and namespace_binding(backend,container_id,pid)==before,'identity-unknown')
        yield fd,before
        require(namespace_binding(backend,container_id,pid)==before,'identity-unknown')
    finally:os.close(fd)


def move_peer(backend,peer,fd):
    """以已保留namespace FD发送NETLINK，不用可重用PID作为移动目标。"""
    import socket,struct,secrets
    backend.guard()
    index=socket.if_nametoindex(peer);require(index>0 and os.fstat(fd).st_ino>0,'identity-unknown')
    sequence=secrets.randbelow(2**31-1)+1
    payload=struct.pack('BxHiII',socket.AF_UNSPEC,0,index,0,0)+struct.pack('HHI',8,28,fd)
    request=struct.pack('IHHII',16+len(payload),16,5,sequence,0)+payload
    with socket.socket(socket.AF_NETLINK,socket.SOCK_RAW,socket.NETLINK_ROUTE) as channel:
        channel.settimeout(2);channel.bind((0,0));channel.sendto(request,(0,0));response=channel.recv(65536)
        require(len(response)>=20,'control-unreachable')
        length,kind,flags,reply_seq,pid=struct.unpack('IHHII',response[:16])
        require(length>=20 and length<=len(response) and kind==2 and reply_seq==sequence
                and struct.unpack('i',response[16:20])[0]==0,'backend-failed')
    backend.guard()
    return {'state':'moved-to-retained-namespace'}


class RoutedNetwork:
    def __init__(self,backend,policy):self.backend=backend;self.policy=policy

    def firewall_environment(self):
        # nft accept不能越过后续iptables/nft drop；不能通过清空Docker/系统规则伪造可达。
        for tool in ('iptables-save','ip6tables-save'):
            self.backend.check_tool(tool);raw=self.backend.call(tool,[])
            require(type(raw) is str and len(raw)<=1024*1024,'capability-unverified')
            for line in raw.splitlines():
                if not line or line.startswith('#') or line=='COMMIT':continue
                require(line in ('*filter','*nat','*mangle','*raw','*security') or re.fullmatch(
                    r':(?:PREROUTING|INPUT|FORWARD|OUTPUT|POSTROUTING) ACCEPT \[\d+:\d+\]',line),'capability-unverified')
        rows=self.backend.json('nft',['-j','list','ruleset'])
        require(type(rows) is dict and type(rows.get('nftables')) is list,'identity-unknown')
        table='ctflab_'+self.policy['instance_uuid'].replace('-','')[:12]+'_g'+str(self.policy['generation'])
        for row in rows['nftables']:
            chain=row.get('chain',{}) if type(row) is dict else {}
            if 'hook' in chain:require(chain.get('family')=='inet' and chain.get('table')==table
                and chain.get('name') in ('input','output','forward'),'capability-unverified')

    def preflight(self):
        self.firewall_environment()
        self.backend.check_tool('nsenter');self.backend.check_tool('ip');self.backend.check_tool('sysctl')
        names=[interface_names(self.policy,n) for n in self.policy['containers']]
        links=self.backend.json('ip',['-j','link','show'])
        require(type(links) is list and len(links)<=256,'state-conflict')
        present={row.get('ifname') for row in links}
        require(all(not ({a,b}&present) for a,b in names),'state-conflict')
        self.host_routes(complete=False)

    def ns(self,fd,tool,args):
        from ctflab_guest_agent import TOOLS
        require(tool in ('ip','sysctl'))
        self.backend.check_tool(tool)
        return self.backend.call('nsenter',['--net=/proc/self/fd/'+str(fd),'--',TOOLS[tool],*args],pass_fds=(fd,))

    def ns_json(self,fd,args):
        import json
        return json.loads(self.ns(fd,'ip',args))

    def host_routes(self,*,complete):
        """路由器主表只允许计划直连物理网及本代次容器/32链路。"""
        self.firewall_environment()
        rows=self.backend.json('ip',['-4','-j','route','show','table','main'])
        require(type(rows) is list and len(rows)<=256,'route-conflict')
        expected={(route_plan(self.policy,n)['address']+'/32',route_plan(self.policy,n)['host']) for n in self.policy['containers']}
        seen=set()
        for row in rows:
            require(type(row) is dict and set(row)<={'dst','dev','protocol','scope','prefsrc','flags','type'}
                    and row.get('type','unicast')=='unicast' and row.get('flags',[])==[],'route-conflict')
            dst=str(ipaddress.IPv4Network(row['dst'],strict=False));key=(dst,row.get('dev'))
            if key in expected:
                require(key not in seen and row.get('protocol')=='static' and row.get('scope')=='link'
                        and row.get('prefsrc')==self.policy['routed']['gateway'],'route-conflict');seen.add(key)
            else:
                require(any(dst==nic['cidr'] and row.get('dev')==nic['device'] and row.get('prefsrc')==nic['address']
                            and row.get('protocol')=='kernel' and row.get('scope')=='link' for nic in self.policy['interfaces'].values()),'route-conflict')
        require(not complete or seen==expected,'route-conflict')
        return sorted(seen)

    def namespace_routes(self,fd,name):
        route=route_plan(self.policy,name)
        links=self.ns_json(fd,['-j','address','show'])
        require(type(links) is list and {r.get('ifname') for r in links}=={'lo',route['interface']},'identity-unknown')
        link=next(r for r in links if r['ifname']==route['interface'])
        addresses=link.get('addr_info')
        require('UP' in link.get('flags',[]) and type(addresses) is list and len(addresses)==1
                and addresses[0].get('family')=='inet' and addresses[0].get('local')==route['address']
                and addresses[0].get('prefixlen')==32 and addresses[0].get('scope')=='global','state-conflict')
        rows=self.ns_json(fd,['-4','-j','route','show','table','main'])
        expected={(route['gateway']+'/32',None,'link')}|{(ip+'/32',route['gateway'],'global') for ip in route['remotes']}
        found=set()
        require(type(rows) is list and len(rows)<=128,'route-conflict')
        for row in rows:
            require(type(row) is dict and set(row)<={'dst','dev','protocol','scope','prefsrc','gateway','flags','type'}
                    and row.get('dev')==route['interface'] and row.get('protocol')=='static'
                    and row.get('prefsrc')==route['address'] and row.get('flags',[])==[]
                    and row.get('type','unicast')=='unicast','route-conflict')
            item=(str(ipaddress.IPv4Network(row['dst'],strict=False)),row.get('gateway'),row.get('scope','global'))
            require(item in expected and item not in found,'route-conflict');found.add(item)
        require(found==expected and self.ns_json(fd,['-6','-j','route','show','table','main'])==[],'route-conflict')
        return {'address':route['address'],'routes':sorted(route['remotes'])}

    def attach(self,name,container_id,pid,effect):
        route=route_plan(self.policy,name);host,peer=route['host'],route['peer']
        with retained_namespace(self.backend,container_id,pid) as (fd,binding):
            # network=none的初态必须是只有lo；不接管外来/半创建接口，不自动删除。
            links=self.ns_json(fd,['-j','link','show'])
            require(type(links) is list and [r.get('ifname') for r in links]==['lo'],'state-conflict')
            require(self.ns_json(fd,['-4','-j','route','show','table','main'])==[],'route-conflict')
            def apply(step,call):return effect('route-'+name+'-'+step,call)
            apply('pair',lambda:self.backend.call('ip',['link','add',host,'type','veth','peer','name',peer]))
            apply('move',lambda:move_peer(self.backend,peer,fd))
            apply('rename',lambda:self.ns(fd,'ip',['link','set',peer,'name',route['interface']]))
            apply('ipv6',lambda:self.ns(fd,'sysctl',['-w','net.ipv6.conf.all.disable_ipv6=1']))
            apply('host-ipv6',lambda:self.backend.call('sysctl',['-w','net.ipv6.conf.'+host+'.disable_ipv6=1']))
            apply('host-address',lambda:self.backend.call('ip',['address','add',route['gateway']+'/32','dev',host,'noprefixroute']))
            apply('address',lambda:self.ns(fd,'ip',['address','add',route['address']+'/32','dev',route['interface'],'noprefixroute']))
            apply('host-up',lambda:self.backend.call('ip',['link','set',host,'up']))
            apply('up',lambda:self.ns(fd,'ip',['link','set',route['interface'],'up']))
            apply('host-route',lambda:self.backend.call('ip',['-4','route','add',route['address']+'/32','dev',host,
                    'proto','static','scope','link','src',route['gateway']]))
            apply('gateway-route',lambda:self.ns(fd,'ip',['-4','route','add',route['gateway']+'/32','dev',route['interface'],
                    'proto','static','scope','link','src',route['address']]))
            for index,ip in enumerate(route['remotes']):
                apply('remote-'+str(index),lambda ip=ip:self.ns(fd,'ip',['-4','route','add',ip+'/32','via',route['gateway'],
                    'dev',route['interface'],'proto','static','src',route['address']]))
            observed=self.namespace_routes(fd,name)
            observed.update(binding=binding,container_id=container_id,policy_sha256=self.policy['policy_sha256'])
            return observed

    def inspect(self,name,container_id,pid):
        self.firewall_environment()
        with retained_namespace(self.backend,container_id,pid) as (fd,binding):
            value=self.namespace_routes(fd,name)
            value.update(binding=binding,container_id=container_id,policy_sha256=self.policy['policy_sha256'])
            return value
