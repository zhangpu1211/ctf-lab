"""单网卡实验终端的显式/32窄路由与双向有状态访问规则；不操作宿主。"""
import ipaddress
from ctflab_contract import require,canonical


def compile_endpoint(plan,node,devices,definition):
    require(type(definition) is dict and {'routes','flows'}<=set(definition)<={'routes','flows','container_policy'})
    require(type(definition['routes']) is list and len(definition['routes'])<=64)
    require(type(definition['flows']) is list and len(definition['flows'])<=128)
    local=plan['manifest']['nodes'][node]['interfaces'];require(len(local)==1,'capability-unverified')
    local=local[0];device=devices[local['id']]
    def endpoint(value):
        require(type(value) is dict and set(value)=={'node','interface'})
        require(isinstance(value['node'],str) and value['node'] in plan['manifest']['nodes'])
        found=[nic for nic in plan['manifest']['nodes'][value['node']]['interfaces'] if nic['id']==value['interface']]
        require(len(found)==1)
        return value['node'],found[0]
    container_owner=None;container_policy=None
    if 'container_policy' in definition:
        from ctflab_guest_policy import verify_policy
        owner=definition['container_policy']
        require(type(owner) is dict and 'endpoint' not in owner and owner.get('routed') is True
                and owner.get('plan')==plan and owner.get('node')!=node,'identity-unknown')
        container_policy=verify_policy(owner);container_owner=owner['node']
    original_endpoint=endpoint
    def endpoint(value):
        require(type(value) is dict and set(value)=={'node','interface'})
        target=value['node']
        if isinstance(target,str) and target.startswith('container:'):
            name=target.split(':',1)[1]
            require(container_policy is not None and name in container_policy['containers']
                    and value['interface']=='container','capability-unverified')
            return target,{'id':'container','address':container_policy['containers'][name]['address'],
                           'network':target,'container_owner':container_owner}
        return original_endpoint(value)
    routes=[];seen=set()
    for route in definition['routes']:
        require(type(route) is dict and set(route)=={'destination','gateway','interface'})
        target,dest=endpoint(route['destination']);gateway,via=endpoint(route['gateway'])
        require(target!=node and gateway not in (node,target) and route['interface']==local['id'])
        gateway_nics=plan['manifest']['nodes'][gateway]['interfaces']
        require(len(gateway_nics)>=2 and via['network']==local['network'] and dest['network']!=local['network']
                and (dest.get('container_owner')==gateway or any(n['network']==dest['network'] for n in gateway_nics)),'route-conflict')
        destination=str(ipaddress.IPv4Address(dest['address']))+'/32'
        require(destination not in seen);seen.add(destination)
        routes.append({'destination':destination,'gateway':via['address'],'device':device,'source':local['address']})
    rules=[];seen=set()
    for flow in definition['flows']:
        require(type(flow) is dict and set(flow)=={'source','destination','protocol','ports','reason'})
        source,a=endpoint(flow['source']);destination,b=endpoint(flow['destination'])
        require((source==node)!=(destination==node))
        own,remote=(a,b) if source==node else (b,a)
        require(own['id']==local['id'])
        require(remote['network']==local['network'] or any(r['destination']==remote['address']+'/32' for r in routes),'route-conflict')
        require(flow['protocol'] in ('tcp','udp','icmp'))
        ports=flow['ports'];require(type(ports) is list and len(ports)<=32 and all(type(p) is int and 1<=p<=65535 for p in ports))
        require(len(set(ports))==len(ports) and (bool(ports) if flow['protocol']!='icmp' else ports==[]))
        require(isinstance(flow['reason'],str) and 0<len(flow['reason'])<=256 and all(ord(c)>=32 for c in flow['reason']))
        rule={'direction':'outbound' if source==node else 'inbound','local':own['address'],
              'remote':remote['address'],'device':device,'protocol':flow['protocol'],'ports':sorted(ports)}
        encoded=canonical(rule);require(encoded not in seen);seen.add(encoded);rules.append(rule)
    return {'routes':sorted(routes,key=lambda r:r['destination']),'rules':rules,'forwarding':False}


def firewall_lines(endpoint,table):
    lines=[]
    for rule in endpoint['rules']:
        outbound=rule['direction']=='outbound'
        initial,reply=('output','input') if outbound else ('input','output')
        a,b=(rule['local'],rule['remote']) if outbound else (rule['remote'],rule['local'])
        def match(chain,source,destination):
            interface='oifname' if chain=='output' else 'iifname'
            return f'add rule inet {table} {chain} {interface} "{rule["device"]}" ip saddr {source} ip daddr {destination}'
        if rule['protocol']=='icmp':
            lines.append(match(initial,a,b)+' icmp type echo-request counter accept')
            lines.append(match(reply,b,a)+' icmp type echo-reply ct state established counter accept')
        else:
            ports='{ '+', '.join(map(str,rule['ports']))+' }'
            lines.append(match(initial,a,b)+f' {rule["protocol"]} dport {ports} ct state new,established counter accept')
            lines.append(match(reply,b,a)+f' {rule["protocol"]} sport {ports} ct state established counter accept')
    return lines


def route_snapshot(rows,policy,*,complete):
    """拒绝额外/改写/多路径路由；只允许计划直连网及指定静态主机路由。"""
    require(type(rows) is list and len(rows)<=256,'route-conflict')
    expected={(r['destination'],r['gateway'],r['device'],r['source']) for r in policy['endpoint']['routes']}
    seen=set()
    for row in rows:
        require(type(row) is dict and set(row)<={'dst','gateway','dev','protocol','scope','prefsrc','flags','type'},'route-conflict')
        require(row.get('type','unicast')=='unicast' and row.get('flags',[])==[],'route-conflict')
        destination=row.get('dst');require(isinstance(destination,str) and destination!='default','route-conflict')
        destination=str(ipaddress.IPv4Network(destination if '/' in destination else destination+'/32',strict=True))
        if row.get('protocol')=='kernel':
            require(row.get('scope')=='link' and not row.get('gateway') and any(
                destination==nic['cidr'] and row.get('dev')==nic['device'] and row.get('prefsrc')==nic['address']
                for nic in policy['interfaces'].values()),'route-conflict')
        else:
            key=(destination,row.get('gateway'),row.get('dev'),row.get('prefsrc'))
            require(row.get('protocol')=='static' and row.get('scope','global')=='global'
                    and key in expected and key not in seen,'route-conflict');seen.add(key)
    require(not complete or seen==expected,'state-conflict')
    return sorted(seen)
