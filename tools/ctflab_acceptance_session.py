"""集中验收的只读快照与跨步骤核对；不自动启动、停止或重置任何实例。"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))

from ctflab_contract import require,canonical
from ctflab_generation_store import GenerationStore,digest
from ctflab_qemu_driver import QemuDriver,read,record
from ctflab_windows_recovery import RuntimeClient
from ctflab_windows_smoke import BASE,BASE_SHA
from ctflab_tls_endpoint import guard


def attempt_snapshot(root):
    guard(root)
    names=('binding.json','worker.json','observer-ready.json','observer-exit.json',
           'supervisor-fault.applied.json','supervisor-fault.exit.json','exit.json')
    values={name:read(root/name) for name in names if (root/name).exists()}
    values['launch_sha256']=digest(root/'launch.json') if (root/'launch.json').exists() else None
    values['start_intents']=sorted(p.name for p in root.glob('*start*.intent.json'))
    values['attempt']=root.name
    return values


def capture(root,kind,*,verify_sources=False):
    root=Path(root).absolute();guard(root)
    result={'schema':1,'kind':kind,'timestamp':datetime.now(timezone.utc).isoformat(),
            'scope':'local-read-only-checkpoint','nodes':{},'sources':{},
            'guest_verified':False,'isolation_verified':False,'course_verified':False}
    if kind=='smoke':
        client=RuntimeClient(root)
        result.update(instance_uuid=client.config['instance_uuid'],generation=1,plan_sha256=None)
        result['nodes']['smoke']={'status':client.status(),'runtime':attempt_snapshot(root)}
        if verify_sources:result['sources']['smoke']={'expected':BASE_SHA,'actual':digest(BASE)}
    else:
        require(kind=='scenario')
        store=GenerationStore(root);generation=store.snapshot()['active_generation']
        require(generation>0,'state-conflict')
        plan=store.plan(generation);driver=QemuDriver(store,read(root/'runtime-profile.json'))
        result.update(instance_uuid=plan['instance_uuid'],generation=generation,plan_sha256=plan['plan_sha256'])
        for node in plan['start_order']:
            paths=store.node_paths(generation,node)
            attempt=driver.latest(driver.location(plan,node,paths))
            from dataclasses import asdict
            result['nodes'][node]={'status':asdict(driver.observe(plan,node,paths)),
                'runtime':attempt_snapshot(attempt) if attempt else None,
                'disk_path':str(paths['disk']),'disk_identity':[paths['disk'].stat().st_dev,paths['disk'].stat().st_ino]}
            result['nodes'][node]['baseline_sha256']=plan['resources'][node]['asset_sha256']
            if verify_sources and result['nodes'][node]['status']['state']=='stopped':
                from ctflab_runtime_inventory import hash_file
                result['nodes'][node]['disk_sha256']=hash_file(paths['disk'],paths['disk'].stat())
        if verify_sources:
            result['sources']={k:{'expected':v['sha256'],'actual':digest(v['path'])} for k,v in store.config['assets'].items()}
            result['retained_generations']={}
            for entry in store.snapshot()['generations']:
                if entry['state']!='prepared' or entry['number']>=generation:continue
                retained={}
                for node in plan['start_order']:
                    disk=store.node_paths(entry['number'],node)['disk'];info=disk.stat()
                    from ctflab_runtime_inventory import hash_file
                    retained[node]={'disk_path':str(disk),'disk_identity':[info.st_dev,info.st_ino],
                                    'disk_sha256':hash_file(disk,info)}
                result['retained_generations'][str(entry['number'])]=retained
    return result


def running(node):
    status=node['status']
    return (status.get('identity')=='running' and status.get('control_reconnected') is True
            or status.get('identity')=='verified' and status.get('state')=='process-running')


def compare(before,after,expect):
    require(before['schema']==after['schema']==1 and before['kind']==after['kind'])
    require(before['instance_uuid']==after['instance_uuid'],'identity-unknown')
    require(set(before['nodes'])==set(after['nodes']),'identity-unknown')
    require(expect in ('recovery','restart','reset'))
    checks=[]
    def check(name,passed):checks.append({'check':name,'result':'passed' if passed else 'failed'})
    check('source-hashes',bool(after['sources']) and all(v['expected']==v['actual'] for v in after['sources'].values()))
    if expect=='reset':
        check('next-generation',after['generation']==before['generation']+1)
        for node in before['nodes']:
            left,right=before['nodes'][node],after['nodes'][node]
            check(node+'-new-disk',left.get('disk_path')!=right.get('disk_path') and left.get('disk_identity')!=right.get('disk_identity'))
            check(node+'-stopped-before-and-after',left['status'].get('state')=='stopped' and right['status'].get('state')=='stopped')
            check(node+'-baseline-restored',bool(right.get('disk_sha256')) and right.get('disk_sha256')==right.get('baseline_sha256'))
            retained=after.get('retained_generations',{}).get(str(before['generation']),{}).get(node,{})
            check(node+'-old-progress-retained',bool(left.get('disk_sha256'))
                  and all(retained.get(k)==left.get(k) for k in ('disk_path','disk_identity','disk_sha256')))
    else:
        check('same-generation',before['generation']==after['generation'])
        check('same-plan',before['plan_sha256']==after['plan_sha256'])
        for node in before['nodes']:
            left,right=before['nodes'][node],after['nodes'][node]
            a,b=left['runtime'],right['runtime']
            check(node+'-running-before-and-after',running(left) and running(right))
            if not a or not b:
                check(node+'-binding-present',False);continue
            if expect=='recovery':
                check(node+'-same-qemu',a.get('binding.json')==b.get('binding.json'))
                check(node+'-same-attempt',a['attempt']==b['attempt'] and a['launch_sha256']==b['launch_sha256'])
                check(node+'-no-new-start',a['start_intents']==b['start_intents'])
                applied=b.get('supervisor-fault.applied.json');exit_record=b.get('supervisor-fault.exit.json')
                # 多节点只要求实际指定的节点有故障证据，其余节点必须保持绑定不变。
                if applied or exit_record:
                    check(node+'-supervisor-exit-confirmed',bool(applied and exit_record)
                          and exit_record.get('state')=='exited' and exit_record.get('returncode')==73
                          and exit_record.get('source')=='retained-native-handle'
                          and exit_record.get('identity')==a.get('worker.json')==applied.get('worker')
                          and applied.get('qemu')==a.get('binding.json',{}).get('identity'))
            else:
                check(node+'-new-attempt',a['attempt']!=b['attempt'])
                check(node+'-new-process',a.get('binding.json')!=b.get('binding.json'))
                check(node+'-same-disk',left.get('disk_path')==right.get('disk_path') and left.get('disk_identity')==right.get('disk_identity'))
        if expect=='recovery':
            check('fault-evidence-present',any(n['runtime'] and n['runtime'].get('supervisor-fault.exit.json') for n in after['nodes'].values()))
    return {'schema':1,'expect':expect,'instance_uuid':before['instance_uuid'],
            'result':'passed' if all(c['result']=='passed' for c in checks) else 'failed','checks':checks,
            'guest_verified':False,'isolation_verified':False,'course_verified':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('checkpoint');p.add_argument('--run',required=True,type=Path)
    p.add_argument('--kind',choices=('smoke','scenario'),required=True);p.add_argument('--verify-sources',action='store_true')
    p=sub.add_parser('compare');p.add_argument('--before',required=True,type=Path);p.add_argument('--after',required=True,type=Path)
    p.add_argument('--expect',choices=('recovery','restart','reset'),required=True)
    for p in sub.choices.values():p.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(argv)
    try:
        value=capture(args.run,args.kind,verify_sources=args.verify_sources) if args.action=='checkpoint' else compare(read(args.before),read(args.after),args.expect)
        record(args.output.absolute(),value)
        print(canonical({'state':'recorded','result':value.get('result','checkpoint-created'),'guest_verified':False}))
        return 2 if value.get('result')=='failed' else 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError):
        print(canonical({'state':'failed','preserved':True,'reason':'checkpoint-or-comparison-failed'}));return 2


if __name__=='__main__':raise SystemExit(main())
