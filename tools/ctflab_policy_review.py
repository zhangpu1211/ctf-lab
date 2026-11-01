"""离线检查同一实例的路由与终端策略是否闭合；不探测网络或解析PCAP。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in (None, ''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require
from ctflab_guest_policy import verify_policy
from ctflab_scenario_v2 import instance_plan


def review(plan,envelopes):
    require(plan==instance_plan(plan['manifest'],plan['instance_uuid'],generation=plan['generation']),'state-conflict')
    require(type(envelopes) is list and len(envelopes)<=32)
    policies={}
    for envelope in envelopes:
        policy=verify_policy(envelope)
        require(envelope['plan']==plan,'identity-unknown')
        require(policy['node'] not in policies,'state-conflict')
        policies[policy['node']]=policy
    nodes=plan['manifest']['nodes']
    # 一地址一网卡由场景校验保证；只按精确地址绑定，不猜测主机或动态路由。
    addresses={nic['address']:(node,nic) for node,spec in nodes.items() for nic in spec['interfaces']}
    findings=[];paths=[]
    def finding(code,node,peer=None,router=None):
        value={'code':code,'node':node}
        if peer is not None:value['peer']=peer
        if router is not None:value['router']=router
        if value not in findings:findings.append(value)
    def terminal(node,peer,local_ip,remote_ip,protocol,ports,direction,gateway):
        policy=policies.get(node)
        if policy is None or 'endpoint' not in policy:
            finding('endpoint-policy-missing',node,peer,gateway);return False
        endpoint=policy['endpoint']
        own_nic=addresses[local_ip][1];remote_nic=addresses[remote_ip][1]
        routed=own_nic['network']!=remote_nic['network']
        good=True
        if routed:
            via=[nic for nic in nodes[gateway]['interfaces'] if nic['network']==own_nic['network']]
            route=next((r for r in endpoint['routes'] if r['destination']==remote_ip+'/32'),None)
            if len(via)!=1 or route is None or route['gateway']!=via[0]['address'] or route['source']!=local_ip:
                finding('endpoint-return-route-missing-or-different',node,peer,gateway);good=False
        matches=[r for r in endpoint['rules'] if r['direction']==direction and r['local']==local_ip
                 and r['remote']==remote_ip and r['protocol']==protocol]
        allowed={p for r in matches for p in r['ports']}
        if not matches or not set(ports)<=allowed:
            finding('endpoint-flow-missing-or-narrower',node,peer,gateway);good=False
        return good
    for router,policy in sorted(policies.items()):
        if 'endpoint' in policy:continue
        for rule in policy['rules']:
            a,b=rule['source'],rule['destination'];source=addresses[a['address']][0];destination=addresses[b['address']][0]
            left=terminal(source,destination,a['address'],b['address'],rule['protocol'],rule['ports'],'outbound',router)
            right=terminal(destination,source,b['address'],a['address'],rule['protocol'],rule['ports'],'inbound',router)
            paths.append({'source':source,'destination':destination,'source_address':a['address'],
                'destination_address':b['address'],'router':router,'protocol':rule['protocol'],'ports':rule['ports'],
                'declarations_complete':left and right,'runtime_verified':False})
    # 终端有放行而网关没有对应转发规则，同样属于未闭合声明。
    for node,policy in sorted(policies.items()):
        if 'endpoint' not in policy:continue
        for rule in policy['endpoint']['rules']:
            remote,nic=addresses[rule['remote']];own=addresses[rule['local']][1]
            if own['network']==nic['network']:continue
            source,destination=(node,remote) if rule['direction']=='outbound' else (remote,node)
            candidate=[p for p in paths if p['source']==source and p['destination']==destination
                       and p['protocol']==rule['protocol']]
            if not candidate or not set(rule['ports'])<={port for p in candidate for port in p['ports']}:
                finding('router-flow-missing-or-narrower',node,remote)
    shared=[]
    for network in sorted(plan['manifest']['networks']):
        members=sorted(node for node,spec in nodes.items() if any(n['network']==network for n in spec['interfaces']))
        if len(members)>1:shared.append({'network':network,'nodes':members,'restriction':'router-forward-rules-do-not-cover-same-network-traffic'})
    result={'schema':1,'kind':'offline-policy-review','instance_uuid':plan['instance_uuid'],
        'generation':plan['generation'],'plan_sha256':plan['plan_sha256'],
        'policy_sha256':{n:p['policy_sha256'] for n,p in sorted(policies.items())},
        'paths':paths,'findings':sorted(findings,key=canonical),'shared_networks':shared,
        'declarations_complete':bool(paths) and all(p['declarations_complete'] for p in paths) and not findings,
        'executed':False,'isolation_verified':False,'service_verified':False,
        'limitations':['single-router-ipv4-declarations-only','no-live-rules-routes-or-services-observed',
                       'same-network-traffic-not-proven-isolated','container-cross-network-unsupported',
                       'not-zeek-or-suricata-evidence-analysis']}
    result['review_sha256']=hashlib.sha256(canonical(result).encode()).hexdigest()
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--policy',type=Path,action='append',default=[])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    def read(path):
        with path.open('rb') as stream:raw=stream.read(4*1024**2+1)
        require(len(raw)<=4*1024**2)
        def unique(pairs):
            result={}
            for key,value in pairs:require(key not in result);result[key]=value
            return result
        def invalid(_):require(False)
        return json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)
    try:
        result=review(read(args.plan),[read(p) for p in args.policy])
        from ctflab_windows_recovery import record
        record(args.output.absolute(),result)
        print(canonical({'state':'reviewed','declarations_complete':result['declarations_complete'],
                         'isolation_verified':False,'executed':False}))
        return 0 if result['declarations_complete'] else 2
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,RecursionError):
        print(canonical({'state':'refused','preserved':True,'executed':False}));return 2


if __name__=='__main__':raise SystemExit(main())
