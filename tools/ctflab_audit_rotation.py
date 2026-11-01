"""显式审计换库：无未决审计/契约动作、签名快照、冻结旧库后切换私有策略；不操作VM。"""
import argparse
from contextlib import contextmanager,ExitStack
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require
from ctflab_generation_store import digest,GenerationStore
from ctflab_remote import validate_policy,private_json
from ctflab_remote_audit import AuditStore,ZERO
from ctflab_audit_archive import seal,verify as verify_archive
from ctflab_local_service import LocalService
from ctflab_lease_store import LeaseStore
from ctflab_tls_endpoint import guard
from ctflab_windows_recovery import record


def key_identity(signing):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    from ctflab_contract import identifier
    require(type(signing) is dict and set(signing)=={'key_id','private_key_hex'} and type(signing['private_key_hex']) is str and len(signing['private_key_hex'])==64)
    identifier(signing['key_id'])
    key=Ed25519PrivateKey.from_private_bytes(bytes.fromhex(signing['private_key_hex']))
    public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
    return {'key_id':signing['key_id'],'public_key_sha256':hashlib.sha256(bytes.fromhex(public)).hexdigest()},public


@contextmanager
def contracts_idle(policy):
    with ExitStack() as stack:
        if 'leases' in policy:
            pool=LeaseStore(policy['leases']['root'],policy['server_uuid']);stack.enter_context(pool.locked())
        for instance,entry in sorted(policy['instances'].items()):
            root=guard(Path(entry['root']));service=LocalService(root/'desktop-contract')
            db=stack.enter_context(service._transaction())
            require(GenerationStore(root).config['instance_uuid']==instance,'identity-unknown')
            rows=db.execute('SELECT id,active FROM instances').fetchall()
            require(not rows or len(rows)==1 and rows[0][0]==instance and rows[0][1] is None,'resource-busy')
            require(db.execute("SELECT COUNT(*) FROM operations WHERE status IN ('pending','executing')").fetchone()[0]==0,'resource-busy')
        yield


def switched(policy,new_root):
    result=json.loads(canonical(policy));result['audit']['root']=str(Path(new_root).absolute());return validate_policy(result)


def plan(db,policy_path,policy,new_root,archive,signer):
    policy_path=guard(Path(policy_path).absolute());current=validate_policy(private_json(policy_path));require(current==policy,'permission-denied')
    from ctflab_server_storage import verify as verify_storage
    verify_storage(policy)
    store=AuditStore(policy['audit'],policy['server_uuid']);events=store.verify(db);store.require_writable(db)
    require(db.execute('SELECT COUNT(*) FROM attempts WHERE completed=0').fetchone()[0]==0,'resource-busy')
    new_root=Path(new_root).absolute();archive=Path(archive).absolute();candidate=switched(policy,new_root)
    verify_storage(candidate,extra={'audit-archive':archive})
    require(new_root!=store.root and new_root not in store.root.parents and store.root not in new_root.parents,'permission-denied')
    require(not new_root.exists() and not new_root.is_symlink() and not archive.exists() and not archive.is_symlink(),'state-conflict')
    roots=[Path(entry['root']) for entry in policy['instances'].values()]+[store.root,new_root]
    if 'uploads' in policy:roots.append(Path(policy['uploads']['cache_root']))
    if 'leases' in policy:roots.append(Path(policy['leases']['root']))
    require(all(archive!=root and archive not in root.parents and root not in archive.parents for root in roots),'permission-denied')
    before=digest(policy_path);after=hashlib.sha256(canonical(candidate).encode()).hexdigest()
    value={'schema':1,'server_uuid':policy['server_uuid'],'policy_before_sha256':before,'policy_after_sha256':after,
        'head_seq':len(events),'head_sha256':events[-1]['sha256'] if events else ZERO,'signer':signer,
        'new_root':str(new_root),'archive':str(archive),'pending_count':0,'vm_observed':False,'automatic_replay':False}
    value['rotation_sha256']=hashlib.sha256(canonical(value).encode()).hexdigest();return value,candidate


def preview(policy_path,new_root,archive,signing):
    path=guard(Path(policy_path).absolute());policy=validate_policy(private_json(path));signer,_=key_identity(signing)
    require('audit' in policy,'capability-unverified');store=AuditStore(policy['audit'],policy['server_uuid'])
    # 预览只读，不取得契约写门或初始化新根；执行时才统一排他复核。
    with store.transaction() as db:return plan(db,path,policy,new_root,archive,signer)[0]


def replace_policy(path,before,after):
    require(digest(guard(path))==before,'permission-denied')
    temporary=path.with_name(path.name+'.rotation-'+hashlib.sha256(after.encode()).hexdigest()[:16])
    # 固定内容临时文件也不覆盖；中断遗留须人工检查或显式resume采用同字节。
    if temporary.exists():require(guard(temporary).read_bytes()==after.encode(),'identity-unknown')
    else:
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(after.encode());stream.flush();os.fsync(stream.fileno())
    require(digest(guard(path))==before,'permission-denied');os.replace(temporary,path)
    if os.name!='nt':
        fd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)


def rotate(policy_path,new_root,archive,signing,expected):
    path=guard(Path(policy_path).absolute());policy=validate_policy(private_json(path));signer,public=key_identity(signing)
    store=AuditStore(policy['audit'],policy['server_uuid'])
    with store.transaction(write=True) as db,contracts_idle(policy):
        value,candidate=plan(db,path,policy,new_root,archive,signer);require(value['rotation_sha256']==expected,'state-conflict')
        new_store=AuditStore.create(candidate['audit'],policy['server_uuid']);root=new_store.root
        raw_before=path.read_bytes();require(hashlib.sha256(raw_before).hexdigest()==value['policy_before_sha256'],'permission-denied')
        fd=os.open(root/'policy.before.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as backup:backup.write(raw_before);backup.flush();os.fsync(backup.fileno())
        record(root/'policy.after.json',candidate)
        intent=dict(value,policy_path=str(path),old_root=str(store.root))
        record(root/'rotation.intent.json',intent)
        seal(store,archive,signing);verified=verify_archive(archive,{signer['key_id']:public})
        require(verified['head_seq']==value['head_seq'] and verified['head_sha256']==value['head_sha256'],'identity-unknown')
        record(root/'PREVIOUS.json',{'schema':1,'head_seq':value['head_seq'],'head_sha256':value['head_sha256'],
            'checkpoint_sha256':digest(Path(archive)/'CHECKPOINT.json'),'database_sha256':verified['database_sha256'],'signer':signer})
        db.execute('CREATE TABLE audit_seal(document TEXT NOT NULL)')
        db.execute('INSERT INTO audit_seal VALUES(?)',(canonical({'schema':1,'rotation_sha256':expected,
            'new_root':str(root),'head_seq':value['head_seq'],'head_sha256':value['head_sha256']}),))
        db.commit() # 先冻结旧库；中断不回滚为可写、不删除任何原材料。
        require(digest(guard(path))==value['policy_before_sha256'],'permission-denied')
        replace_policy(path,value['policy_before_sha256'],canonical(candidate))
        record(root/'rotation.completed.json',{'schema':1,'rotation_sha256':expected,'policy_sha256':digest(path)})
    return {'state':'audit-rotated','rotation_sha256':expected,'old_audit_preserved':True,'policy_changed':True,
        'pending_count':0,'vm_observed':False,'vm_stopped':False,'externally_anchored':False,'automatic_replay':False}


def resume(root,keys,expected):
    root=guard(Path(root).absolute());intent_path=guard(root/'rotation.intent.json');intent=private_json(intent_path)
    require(digest(intent_path)==expected and Path(intent['new_root'])==root,'identity-unknown')
    policy=validate_policy(private_json(root/'policy.before.json'));candidate=validate_policy(private_json(root/'policy.after.json'))
    from ctflab_server_storage import verify as verify_storage
    verify_storage(policy,extra={'audit-archive':Path(intent['archive']),'audit-new':root})
    verify_storage(candidate)
    require(candidate==switched(policy,root) and digest(root/'policy.before.json')==intent['policy_before_sha256']
        and hashlib.sha256(canonical(candidate).encode()).hexdigest()==intent['policy_after_sha256'],'identity-unknown')
    verified=verify_archive(intent['archive'],keys);link=private_json(root/'PREVIOUS.json')
    require(verified['head_seq']==intent['head_seq'] and verified['head_sha256']==intent['head_sha256']
        and link['checkpoint_sha256']==digest(Path(intent['archive'])/'CHECKPOINT.json')
        and verified['key_id']==intent['signer']['key_id'],'identity-unknown')
    require(hashlib.sha256(bytes.fromhex(keys[verified['key_id']])).hexdigest()==intent['signer']['public_key_sha256'],'permission-denied')
    path=guard(Path(intent['policy_path']));current=digest(path)
    require(current in (intent['policy_before_sha256'],intent['policy_after_sha256']),'permission-denied')
    old=AuditStore(policy['audit'],policy['server_uuid']);new=AuditStore(candidate['audit'],policy['server_uuid'])
    with old.transaction(write=True) as db,contracts_idle(policy):
        events=old.verify(db);require(len(events)==intent['head_seq'] and (events[-1]['sha256'] if events else ZERO)==intent['head_sha256'],'identity-unknown')
        rows=db.execute('SELECT document FROM audit_seal').fetchall()
        require(len(rows)==1 and json.loads(rows[0][0]).get('rotation_sha256')==intent['rotation_sha256'],'identity-unknown')
        with new.transaction() as fresh:require(new.verify(fresh)==[],'resource-busy')
        if current==intent['policy_before_sha256']:replace_policy(path,current,canonical(candidate))
        require(digest(path)==intent['policy_after_sha256'],'identity-unknown')
        completed={'schema':1,'rotation_sha256':intent['rotation_sha256'],'policy_sha256':digest(path)}
        if (root/'rotation.completed.json').exists():require(private_json(root/'rotation.completed.json')==completed,'identity-unknown')
        else:record(root/'rotation.completed.json',completed)
    return {'state':'audit-rotation-resumed','policy_changed':current!=intent['policy_after_sha256'],
        'old_audit_preserved':True,'vm_stopped':False,'automatic_replay':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('preview','rotate','resume'))
    parser.add_argument('--policy',type=Path);parser.add_argument('--new-root',type=Path,required=True);parser.add_argument('--archive',type=Path)
    parser.add_argument('--signing-key',type=Path);parser.add_argument('--keys',type=Path);parser.add_argument('--expected-sha256');args=parser.parse_args(argv)
    try:
        if args.action=='resume':
            require(args.keys is not None and args.expected_sha256 is not None and args.policy is None and args.archive is None and args.signing_key is None)
            value=resume(args.new_root,private_json(args.keys),args.expected_sha256)
        else:
            require(args.policy is not None and args.archive is not None and args.signing_key is not None and args.keys is None)
            require(bool(args.expected_sha256)==(args.action=='rotate'));signing=private_json(args.signing_key)
            params=(args.policy,args.new_root,args.archive,signing)
            value=rotate(*params,args.expected_sha256) if args.action=='rotate' else preview(*params)
        print(canonical(value));return 0
    except Exception:
        print(canonical({'state':'refused-or-partial','preserved':True,'vm_stopped':False,'automatic_replay':False}));return 2


if __name__=='__main__':raise SystemExit(main())
