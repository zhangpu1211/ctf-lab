"""专用路由/容器来宾的严格声明与确定性配置，不执行宿主命令。"""
import copy
import hashlib
import ipaddress
import re
import uuid

from ctflab_contract import canonical, require, ContractError
from ctflab_scenario_v2 import instance_plan, identifier


def vm_uuid(plan,node):
    require(node in plan['manifest']['nodes'])
    return str(uuid.uuid5(uuid.UUID(plan['instance_uuid']),f'guest/{plan["generation"]}/{node}'))


def compile_policy(plan,node,devices,flows,*,containers=None,container_cidr=None,images=None,endpoint=None,routed=False,analysis=None):
    try:return _compile_policy(plan,node,devices,flows,containers=containers,container_cidr=container_cidr,images=images,endpoint=endpoint,routed=routed,analysis=analysis)
    except (ValueError,TypeError,KeyError,AttributeError) as exc:
        if isinstance(exc,ContractError):raise
        raise ContractError() from None


def _compile_policy(plan,node,devices,flows,*,containers=None,container_cidr=None,images=None,endpoint=None,routed=False,analysis=None):
    require(plan==instance_plan(plan['manifest'],plan['instance_uuid'],generation=plan['generation']),'state-conflict')
    require(node in plan['manifest']['nodes'])
    interfaces=plan['manifest']['nodes'][node]['interfaces']
    require(type(devices) is dict and set(devices)=={i['id'] for i in interfaces})
    require(all(isinstance(d,str) and re.fullmatch('[a-z][a-z0-9]{0,14}',d) and d!='lo' for d in devices.values()))
    require(len(set(devices.values()))==len(devices))
    attached={i['network']:dict(i,device=devices[i['id']],cidr=plan['manifest']['networks'][i['network']]['cidr']) for i in interfaces}
    require(type(routed) is bool)
    containers={} if containers is None else containers
    require(not routed or bool(containers),'capability-unverified')
    require(type(containers) is dict and len(containers)<=16)
    networks=[ipaddress.IPv4Network(v['cidr']) for v in plan['manifest']['networks'].values()]
    if containers:
        subnet=ipaddress.IPv4Network(container_cidr,strict=True)
        require(24<=subnet.prefixlen<=28 and subnet.is_private and not subnet.is_loopback
                and any(subnet.subnet_of(ipaddress.IPv4Network(n)) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))
                and not any(subnet.overlaps(n) for n in networks))
    else:require(container_cidr is None)
    names=set();addresses=set();validated={}
    for name,spec in sorted(containers.items()):
        identifier(name)
        require(type(spec) is dict and set(spec)=={'image','address','user','memory_mb','cpus','volumes'})
        require(isinstance(spec['image'],str) and re.fullmatch(r'[a-z0-9][a-z0-9./:_-]{0,180}@sha256:[0-9a-f]{64}',spec['image']))
        require(isinstance(spec['user'],str) and re.fullmatch(r'[1-9][0-9]{0,5}(?::[1-9][0-9]{0,5})?',spec['user']))
        require(type(spec['memory_mb']) is int and 128<=spec['memory_mb']<=8192)
        require(type(spec['cpus']) is int and 1<=spec['cpus']<=8)
        ip=ipaddress.IPv4Address(spec['address'])
        require(ip in subnet and ip not in (subnet.network_address,subnet.broadcast_address,subnet.network_address+1) and ip not in addresses)
        addresses.add(ip)
        require(type(spec['volumes']) is dict and len(spec['volumes'])<=8)
        targets=set()
        for volume,target in spec['volumes'].items():
            identifier(volume);require(volume not in names);names.add(volume)
            require(isinstance(target,str) and re.fullmatch(r'/(?:data|var/lib/[a-z0-9_-]+)(?:/[a-z0-9_-]+)*',target)
                    and target not in targets)
            require(not any(target.startswith(t+'/') or t.startswith(target+'/') for t in targets))
            targets.add(target)
        validated[name]=copy.deepcopy(spec)
    if images is not None:
        require(type(images) is dict and 1<=len(images)<=16 and set(images)<={v['image'] for v in validated.values()})
        require(all(isinstance(sha,str) and re.fullmatch('[0-9a-f]{64}',sha) for sha in images.values()))
    terminal=None
    if endpoint is not None:
        require(not containers and flows==[],'capability-unverified')
        from ctflab_guest_routes import compile_endpoint
        terminal=compile_endpoint(plan,node,devices,endpoint)
    require(type(flows) is list and len(flows)<=128)
    rules=[];seen=set()
    bridge='ctf'+plan['instance_uuid'].replace('-','')[:8]+str(plan['generation'])
    require(len(bridge)<=15,'capability-unverified')
    def endpoint(value):
        require(type(value) is dict and set(value)=={'node','interface'})
        target=value['node']
        require(isinstance(target,str))
        if target.startswith('container:'):
            require(routed and value['interface']=='container','capability-unverified')
            name=target.split(':',1)[1];require(name in validated)
            from ctflab_guest_routed import interface_names
            return {'address':validated[name]['address'],'device':interface_names(plan,name)[0],'network':target}
        require(target in plan['manifest']['nodes'] and target!=node)
        found=[i for i in plan['manifest']['nodes'][target]['interfaces'] if i['id']==value['interface']]
        require(len(found)==1 and found[0]['network'] in attached)
        nic=found[0];return {'address':nic['address'],'device':attached[nic['network']]['device'],'network':nic['network']}
    for flow in flows:
        require(type(flow) is dict and set(flow)=={'source','destination','protocol','ports','reason'})
        source,destination=endpoint(flow['source']),endpoint(flow['destination'])
        require(source['network']!=destination['network'],'capability-unverified')
        require(flow['protocol'] in ('tcp','udp','icmp'))
        require(type(flow['ports']) is list and len(flow['ports'])<=32
                and len(set(flow['ports']))==len(flow['ports']))
        require(all(type(p) is int and 1<=p<=65535 for p in flow['ports']))
        require(bool(flow['ports']) if flow['protocol']!='icmp' else flow['ports']==[])
        require(isinstance(flow['reason'],str) and 0<len(flow['reason'])<=256 and all(ord(c)>=32 for c in flow['reason']))
        rule={'source':source,'destination':destination,'protocol':flow['protocol'],'ports':sorted(flow['ports'])}
        fingerprint=canonical(rule);require(fingerprint not in seen);seen.add(fingerprint);rules.append(rule)
    records={f'{n}.{i["network"]}.ctflab.test':i['address'] for n,s in plan['manifest']['nodes'].items() for i in s['interfaces']}
    result={'schema':1,'instance_uuid':plan['instance_uuid'],'generation':plan['generation'],
            'plan_sha256':plan['plan_sha256'],'node':node,'vm_uuid':vm_uuid(plan,node),
            'interfaces':attached,'rules':rules,'dns_records':records,'containers':validated,
            'container_cidr':container_cidr,'container_bridge':bridge if containers else None,
            'network_verified':False,'service_verified':False}
    # 未声明OCI时不增加字段，保持既有已绑定策略的字节/摘要兼容。
    if images is not None:
        result['images']=copy.deepcopy(images)
        architecture=plan['manifest']['assets'][plan['manifest']['nodes'][node]['asset']]['architecture']
        require(architecture in ('x86_64','aarch64'),'capability-unverified')
        result['image_architecture']={'x86_64':'amd64','aarch64':'arm64'}[architecture]
    if analysis is not None:
        from ctflab_guest_analysis import settings
        result['analysis']=settings(analysis,validated)
    if routed:result['routed']={'mode':'point-to-point-v1','gateway':str(subnet.network_address+1)}
    if terminal is not None:result['endpoint']=terminal
    result['policy_sha256']=hashlib.sha256(canonical(result).encode()).hexdigest()
    return result


def verify_policy(value):
    required={'plan','node','devices','flows','containers','container_cidr','compiled'}
    require(type(value) is dict and required<=set(value)<=required|{'images','endpoint','routed','analysis'})
    for optional in ('images','endpoint'):
        if optional in value:require(type(value[optional]) is dict)
    expected=compile_policy(value['plan'],value['node'],value['devices'],value['flows'],
                            containers=value['containers'],container_cidr=value['container_cidr'],images=value.get('images'),endpoint=value.get('endpoint'),routed=value.get('routed',False),analysis=value.get('analysis'))
    require(value['compiled']==expected,'state-conflict')
    return expected


def firewall(policy):
    """只生成本代次命名表，不flush宿主/来宾的全局规则。IPv6默认禁通。"""
    table='ctflab_'+policy['instance_uuid'].replace('-','')[:12]+'_g'+str(policy['generation'])
    lines=[f'add table inet {table}']
    for chain in ('input','output','forward'):
        lines.append(f'add chain inet {table} {chain} {{ type filter hook {chain} priority -200; policy drop; }}')
        lines.append(f'add rule inet {table} {chain} meta nfproto ipv6 counter drop')
    for chain,interface in (('input','iifname'),('output','oifname')):
        lines.append(f'add rule inet {table} {chain} {interface} "lo" accept')
    for nic in policy['interfaces'].values():
        # 只服务本接口所属实验网；不提供递归外部DNS或时间源。
        for proto,ports in (('tcp','53'),('udp','{ 53, 123 }')):
            lines.append(f'add rule inet {table} input iifname "{nic["device"]}" ip saddr {nic["cidr"]} ip daddr {nic["address"]} {proto} dport {ports} counter accept')
            lines.append(f'add rule inet {table} output oifname "{nic["device"]}" ip saddr {nic["address"]} ip daddr {nic["cidr"]} {proto} sport {ports} ct state established counter accept')
    for rule in policy['rules']:
        a,b=rule['source'],rule['destination'];protocol=rule['protocol']
        route=f'iifname "{a["device"]}" oifname "{b["device"]}" ip saddr {a["address"]} ip daddr {b["address"]}'
        reverse=f'iifname "{b["device"]}" oifname "{a["device"]}" ip saddr {b["address"]} ip daddr {a["address"]}'
        if protocol=='icmp':
            lines.append(f'add rule inet {table} forward {route} icmp type echo-request counter accept')
            lines.append(f'add rule inet {table} forward {reverse} icmp type echo-reply ct state established counter accept')
        else:
            ports='{ '+', '.join(map(str,rule['ports']))+' }'
            lines.append(f'add rule inet {table} forward {route} {protocol} dport {ports} ct state new,established counter accept')
            lines.append(f'add rule inet {table} forward {reverse} {protocol} sport {ports} ct state established counter accept')
    if 'endpoint' in policy:
        from ctflab_guest_routes import firewall_lines
        lines.extend(firewall_lines(policy['endpoint'],table))
    return '\n'.join(lines)+'\n'


def service_config(policy,state):
    dns=['no-resolv','no-hosts','bind-interfaces','domain-needed','bogus-priv','port=53','cache-size=256',
         f'pid-file={state}/dnsmasq.pid']
    for nic in policy['interfaces'].values():dns += ['interface='+nic['device'],'listen-address='+nic['address']]
    dns += ['host-record='+name+','+ip for name,ip in sorted(policy['dns_records'].items())]
    ntp=['local stratum 10','manual','cmdport 0','port 123',f'driftfile {state}/chrony.drift',f'pidfile {state}/chronyd.pid']
    ntp += ['allow '+nic['cidr'] for nic in policy['interfaces'].values()]
    # chronyd -x运行：不更改系统时钟；此本地参考不代表可信UTC同步。
    return {'dnsmasq.conf':'\n'.join(dns)+'\n','chrony.conf':'\n'.join(ntp)+'\n'}


def service_units():
    """安装在专用来宾内的固定unit；没有宿主自启或停止入口。"""
    common=('\nRestart=no\nTimeoutStopSec=15\nSendSIGKILL=no\nNoNewPrivileges=yes\n'
            'ProtectSystem=strict\nProtectHome=yes\nPrivateTmp=yes\nPrivateDevices=yes\n'
            'ReadWritePaths=/var/lib/ctflab-guest\n'
            'RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX AF_NETLINK\n'
            'StandardOutput=journal\nStandardError=journal\n')
    commands={'dns':'/usr/sbin/dnsmasq --keep-in-foreground --user=root --group=root --conf-file=/var/lib/ctflab-guest/dnsmasq.conf',
              'time':'/usr/sbin/chronyd -n -x -u root -f /var/lib/ctflab-guest/chrony.conf'}
    return {'ctflab-'+name+'.service':('[Unit]\nDescription=CTFLab managed guest '+name+'\n'
            '[Service]\nType=simple\nExecStart='+command+common+
            'CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_SETUID CAP_SETGID\n') for name,command in commands.items()}


def agent_unit():
    return ('[Unit]\nDescription=CTFLab dedicated guest agent\nAfter=local-fs.target\n'
            'ConditionPathExists=/dev/virtio-ports/org.ctflab.agent.0\n[Service]\nType=simple\n'
            'ExecStart=/usr/bin/python3 -I -B /usr/local/lib/ctflab/ctflab_guest_agent.py\n'
            'Restart=no\nNoNewPrivileges=yes\nProtectSystem=strict\nProtectHome=yes\n'
            'ReadWritePaths=/var/lib/ctflab-guest\n[Install]\nWantedBy=multi-user.target\n')


def agent_path_unit():
    return ('[Unit]\nDescription=Wait for CTFLab guest channel\n[Path]\n'
            'PathExists=/dev/virtio-ports/org.ctflab.agent.0\nUnit=ctflab-agent.service\n'
            '[Install]\nWantedBy=multi-user.target\n')
