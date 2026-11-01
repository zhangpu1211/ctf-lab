"""未准备实例的显式容量策略绑定；保留原配置和部分文件，不创建或改配宿主卷。"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text
from ctflab_generation_store import GenerationStore,digest
from ctflab_tls_endpoint import guard

KINDS={'linux':'storage_boundary','mac':'macos_storage','windows':'windows_storage'}


def read_json(path,limit=8*1024**2):
    path=guard(Path(path).absolute());info=path.stat()
    require(path.is_file() and info.st_nlink==1 and info.st_size<=limit,'identity-unknown')
    with path.open('rb') as stream:raw=stream.read(limit+1)
    require(len(raw)<=limit and hashlib.sha256(raw).hexdigest()==digest(path),'identity-unknown')
    def unique(pairs):
        result={}
        for key,value in pairs:require(key not in result);result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:require(False))


def record(path,value):
    guard(path.parent);fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(canonical(value));stream.flush();os.fsync(stream.fileno())
    guard(path)


def verify_policy(kind,policy,root,instance,observer=None):
    require(kind in KINDS)
    if kind=='linux':
        from ctflab_storage_boundary import verify
        return verify(policy,root=root,instance=instance,observer=observer)
    if kind=='windows':
        from ctflab_windows_storage import verify
        return verify(policy,root=root,instance=instance,observer=observer)
    from ctflab_storage_boundary import check_mac_profile
    return check_mac_profile({'macos_storage':policy},root,observer=observer)


def quiet(stack,store):
    contract=store.root/'desktop-contract'
    if contract.exists():
        from ctflab_local_service import LocalService
        service=LocalService(contract);stack.enter_context(service._transaction(worker=True))
        db=stack.enter_context(service._transaction())
        require(not db.execute('SELECT 1 FROM instances WHERE active IS NOT NULL').fetchone(),'resource-busy')
    stack.enter_context(store.locked());snapshot=store.snapshot()
    require(snapshot['active_generation']==0 and not snapshot['generations'] and not snapshot['unresolved'],'state-conflict')


def capture(store,kind,policy,*,observer=None):
    path=guard(store.root/'runtime-profile.json');require(path.stat().st_size<=8*1024**2,'storage-insufficient')
    before_sha=digest(path);before=read_json(path,8*1024**2)
    require(digest(path)==before_sha,'identity-unknown')
    require(type(before) is dict and not set(KINDS.values())&set(before),'state-conflict')
    info=store.root.stat();ledger=guard(store.root/'ledger.sqlite3').stat()
    proof=verify_policy(kind,policy,store.root,store.config['instance_uuid'],observer)
    after=dict(before,**{KINDS[kind]:policy})
    from ctflab_qemu_driver import validate_profile
    validate_profile(store.plan(1),after)
    raw=path.read_bytes();require(hashlib.sha256(raw).hexdigest()==before_sha==digest(path),'identity-unknown')
    descriptor={'instance_uuid':store.config['instance_uuid'],'root_identity':[info.st_dev,info.st_ino],
        'ledger_identity':[ledger.st_dev,ledger.st_ino],'kind':kind,'policy':policy,'before_sha256':before_sha,
        'after_sha256':hashlib.sha256(canonical(after).encode()).hexdigest()}
    descriptor['plan_sha256']=hashlib.sha256(canonical(descriptor).encode()).hexdigest()
    return descriptor,raw,canonical(after).encode(),proof


def preview(root,kind,policy,*,observer=None):
    store=GenerationStore(root)
    with ExitStack() as stack:
        quiet(stack,store);require(not (store.root/'storage-bind.intent.json').exists(),'state-conflict')
        plan,_,_,proof=capture(store,kind,policy,observer=observer)
    return {'state':'storage-binding-reviewed','plan_sha256':plan['plan_sha256'],'before_sha256':plan['before_sha256'],
        'after_sha256':plan['after_sha256'],'instance_uuid':plan['instance_uuid'],'kind':kind,
        'available_bytes':proof['available_bytes'],'profile_changed':False,'host_storage_modified':False}


def preserved_file(root,role,expected,raw=None):
    entries=sorted(root.glob('storage-bind.'+role+'.*.json'));require(len(entries)<16,'resource-busy')
    for path in entries:
        guard(path)
        if path.stat().st_nlink==1 and digest(path)==expected:return path
    require(raw is not None and hashlib.sha256(raw).hexdigest()==expected,'identity-unknown')
    path=root/('storage-bind.'+role+'.'+str(uuid.uuid4())+'.json')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    require(digest(path)==expected,'identity-unknown');return path


def checked_plan(intent):
    require(type(intent) is dict and set(intent)=={'schema','operation_id','plan'}
        and type(intent['schema']) is int and intent['schema']==1,'identity-unknown')
    uuid_text(intent['operation_id']);plan=intent['plan']
    require(type(plan) is dict and set(plan)=={'instance_uuid','root_identity','ledger_identity','kind','policy',
        'before_sha256','after_sha256','plan_sha256'} and plan['kind'] in KINDS
        and plan['plan_sha256']==hashlib.sha256(canonical({k:v for k,v in plan.items() if k!='plan_sha256'}).encode()).hexdigest(),'identity-unknown')
    return plan


def apply(root,kind,policy,operation,expected,*,observer=None):
    uuid_text(operation);require(kind in KINDS);store=GenerationStore(root)
    intent_path=store.root/'storage-bind.intent.json';receipt=store.root/'storage-bind.result.json'
    with ExitStack() as stack:
        quiet(stack,store)
        if intent_path.exists():
            intent=read_json(intent_path);plan=checked_plan(intent)
            require(intent.get('operation_id')==operation and plan['plan_sha256']==expected
                and plan['kind']==kind and plan['policy']==policy,'idempotency-conflict')
            info=store.root.stat();ledger=(store.root/'ledger.sqlite3').stat()
            require(plan['instance_uuid']==store.config['instance_uuid'] and plan['root_identity']==[info.st_dev,info.st_ino]
                and plan['ledger_identity']==[ledger.st_dev,ledger.st_ino],'identity-unknown')
            verify_policy(kind,policy,store.root,store.config['instance_uuid'],observer)
            path=guard(store.root/'runtime-profile.json');current=digest(path)
            require(current in (plan['before_sha256'],plan['after_sha256']),'identity-unknown')
            if receipt.exists():
                require(current==plan['after_sha256'],'identity-unknown');assert_closed(store.root,read_json(path),instance=store.config['instance_uuid']);return read_json(receipt)
            raw=path.read_bytes() if current==plan['before_sha256'] else None
            backup=preserved_file(store.root,'before',plan['before_sha256'],raw)
            before=read_json(backup);require(not set(KINDS.values())&set(before),'identity-unknown')
            new=canonical(dict(before,**{KINDS[kind]:policy})).encode()
            require(hashlib.sha256(new).hexdigest()==plan['after_sha256'],'identity-unknown')
        else:
            plan,raw,new,_=capture(store,kind,policy,observer=observer)
            require(plan['plan_sha256']==expected,'state-conflict')
            require(shutil.disk_usage(store.root).free>=len(raw)+len(new)+65536,'storage-insufficient')
            intent={'schema':1,'operation_id':operation,'plan':plan};record(intent_path,intent)
            backup=preserved_file(store.root,'before',plan['before_sha256'],raw);current=plan['before_sha256']
        if current==plan['before_sha256']:
            candidate=preserved_file(store.root,'candidate',plan['after_sha256'],new)
            verify_policy(kind,policy,store.root,store.config['instance_uuid'],observer)
            require(digest(store.root/'runtime-profile.json')==plan['before_sha256'],'identity-unknown')
            os.replace(candidate,store.root/'runtime-profile.json')
        require(digest(store.root/'runtime-profile.json')==plan['after_sha256'],'identity-unknown')
        verify_policy(kind,policy,store.root,store.config['instance_uuid'],observer)
        info=store.root.stat();ledger=(store.root/'ledger.sqlite3').stat()
        require(plan['root_identity']==[info.st_dev,info.st_ino] and plan['ledger_identity']==[ledger.st_dev,ledger.st_ino],'identity-unknown')
        result={'schema':1,'state':'storage-profile-bound','operation_id':operation,'plan_sha256':expected,
            'intent_sha256':digest(intent_path),'backup':backup.name,'before_sha256':plan['before_sha256'],
            'after_sha256':plan['after_sha256'],'profile_changed':True,'host_storage_modified':False,'vm_started':False}
        raw=canonical(result).encode();temporary=preserved_file(store.root,'result',hashlib.sha256(raw).hexdigest(),raw)
        require(not receipt.exists(),'state-conflict');os.replace(temporary,receipt)
        assert_closed(store.root,read_json(store.root/'runtime-profile.json'),instance=store.config['instance_uuid'])
        return result


def assert_closed(root,profile,*,instance=None):
    root=Path(root);path=root/'storage-bind.intent.json'
    if not path.exists():return
    intent=read_json(path);result=read_json(root/'storage-bind.result.json');plan=checked_plan(intent)
    info=root.stat();ledger=guard(root/'ledger.sqlite3').stat()
    require(plan['root_identity']==[info.st_dev,info.st_ino] and plan['ledger_identity']==[ledger.st_dev,ledger.st_ino]
        and (instance is None or plan['instance_uuid']==instance),'identity-unknown')
    require(type(result) is dict and set(result)=={'schema','state','operation_id','plan_sha256','intent_sha256','backup',
        'before_sha256','after_sha256','profile_changed','host_storage_modified','vm_started'}
        and type(result['schema']) is int and result['schema']==1 and result['state']=='storage-profile-bound'
        and result['profile_changed'] is True and result['host_storage_modified'] is False and result['vm_started'] is False
        and result.get('operation_id')==intent.get('operation_id') and result.get('intent_sha256')==digest(path)
        and result.get('plan_sha256')==plan['plan_sha256'] and result.get('before_sha256')==plan['before_sha256']
        and result.get('after_sha256')==plan['after_sha256'] and plan['kind'] in KINDS
        and profile.get(KINDS[plan['kind']])==plan['policy'],'identity-unknown')
    backup=result['backup'];require(type(backup) is str and Path(backup).name==backup
        and backup.startswith('storage-bind.before.') and backup.endswith('.json'),'identity-unknown')
    require(digest(guard(root/backup))==plan['before_sha256'],'identity-unknown')


def status(root):
    store=GenerationStore(root);intent_path=store.root/'storage-bind.intent.json'
    result={'state':'no-storage-binding-record','instance_uuid':store.config['instance_uuid'],
        'active_generation':store.snapshot()['active_generation'],'native_volume_rechecked':False,
        'profile_changed':False,'host_storage_modified':False,'vm_started':False}
    if not intent_path.exists():return result
    try:intent=read_json(intent_path);plan=checked_plan(intent)
    except (OSError,ValueError,RuntimeError,KeyError,TypeError):return dict(result,state='binding-intent-needs-review',preserved=True)
    path=store.root/'runtime-profile.json';current=None
    if path.exists():
        guard(path);require(path.stat().st_size<=8*1024**2,'storage-insufficient');current=digest(path)
    state=('profile-published-receipt-pending' if current==plan['after_sha256'] else
           'profile-original-intent-pending' if current==plan['before_sha256'] else 'profile-changed-review-required')
    if (store.root/'storage-bind.result.json').exists():
        try:assert_closed(store.root,read_json(path),instance=store.config['instance_uuid']);state='bound-record-verified'
        except (OSError,ValueError,RuntimeError,KeyError,TypeError):state='binding-receipt-needs-review'
    return dict(result,state=state,operation_id=intent['operation_id'],kind=plan['kind'],
        plan_sha256=plan['plan_sha256'],profile_sha256=current,preserved=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('status','preview','apply'))
    parser.add_argument('--run',required=True,type=Path);parser.add_argument('--kind',choices=tuple(KINDS))
    parser.add_argument('--policy',type=Path);parser.add_argument('--operation-id');parser.add_argument('--plan-sha256')
    args=parser.parse_args(argv)
    try:
        if args.action=='status':
            require(args.kind is None and args.policy is None and args.operation_id is None and args.plan_sha256 is None)
            result=status(args.run)
        else:
            require(args.kind is not None and args.policy is not None);value=read_json(args.policy)
            if args.action=='preview':require(args.operation_id is None and args.plan_sha256 is None);result=preview(args.run,args.kind,value)
            else:result=apply(args.run,args.kind,value,args.operation_id,args.plan_sha256)
        print(canonical(result));return 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError):
        print(canonical({'state':'storage-binding-refused-or-interrupted','preserved':True,'host_storage_modified':False,'vm_started':False}));return 2


if __name__=='__main__':raise SystemExit(main())
