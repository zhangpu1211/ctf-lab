"""服务端受管持久目录的公共存储池；只复核预配置卷，不创建卷或修改容量。"""
import argparse
from contextlib import closing
import hashlib
import json
import sqlite3
import os
from pathlib import Path
import stat
import sys

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text,ContractError
from ctflab_tls_endpoint import guard


def fingerprint(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def directory(value):
    require(type(value) is str and '\x00' not in value,'permission-denied')
    path=Path(value)
    require(path.is_absolute() and str(path)==value and all(part not in ('.','..')
        for part in value.replace('\\','/').split('/')),'permission-denied')
    return path


def members(policy):
    result={'instance:'+name:directory(entry['root']) for name,entry in policy['instances'].items()}
    for name,key in (('uploads','cache_root'),('audit','root'),('leases','root')):
        if name in policy:result[name]=directory(policy[name][key])
    require(0<len(result)<=1027,'capability-unverified')
    return result


def settings(policy):
    if 'storage_pool' not in policy:return None
    value=policy['storage_pool'];server=uuid_text(policy['server_uuid'])
    require(type(value) is dict and set(value)=={'schema','server_uuid','kind','volume','sha256'}
        and type(value['schema']) is int and value['schema']==1 and value['server_uuid']==server
        and value['kind'] in ('linux','mac','windows'),'identity-unknown')
    require(value['sha256']==fingerprint({key:item for key,item in value.items() if key!='sha256'}),'identity-unknown')
    volume=value['volume'];require(type(volume) is dict,'identity-unknown')
    if value['kind']=='mac':
        from ctflab_macos_storage import settings as validate
        validate(volume)
    elif value['kind']=='windows':
        from ctflab_windows_storage import settings as validate
        validate(volume,instance=server)
    else:
        from ctflab_storage_boundary import settings as validate
        validate(volume,instance=server)
    root=directory(volume['root'])
    # 所有当前声明的服务端写根均须在池内；根目录自身留作固定边界而非组件数据目录。
    for path in members(policy).values():require(root!=path and root in path.parents,'permission-denied')
    return value


def describe(policy,kind,volume):
    value={'schema':1,'server_uuid':policy['server_uuid'],'kind':kind,'volume':volume}
    value['sha256']=fingerprint(value);candidate=dict(policy,storage_pool=value);settings(candidate)
    return value


def observe(volume,kind,server,observer):
    if kind=='mac':
        from ctflab_macos_storage import verify
        proof=verify(volume,volume['root'],observer=observer)
        capacity=proof['quota_bytes']
    elif kind=='windows':
        from ctflab_windows_storage import verify
        proof=verify(volume,root=volume['root'],instance=server,observer=observer)
        capacity=proof['capacity_bytes']
    else:
        from ctflab_storage_boundary import verify
        proof=verify(volume,root=volume['root'],instance=server,observer=observer)
        capacity=proof['capacity_bytes']
    require(type(capacity) is int and 0<capacity<=volume['max_bytes']
        and type(proof['available_bytes']) is int and proof['available_bytes']>=0,'identity-unknown')
    return capacity,proof['available_bytes']


def inspect_paths(root,declared):
    base=guard(root).stat();require(stat.S_ISDIR(base.st_mode),'identity-unknown')
    result={}
    for name,path in declared.items():
        parent=root;missing=False
        for part in path.relative_to(root).parts:
            parent=parent/part
            try:info=parent.lstat()
            except FileNotFoundError:missing=True;continue
            require(not missing and stat.S_ISDIR(info.st_mode) and info.st_dev==base.st_dev,'identity-unknown')
            guard(parent)
        result[name]='not-created' if missing else 'directory-observed'
    after=guard(root).stat()
    require((base.st_dev,base.st_ino)==(after.st_dev,after.st_ino),'identity-unknown')
    return result


def _verify(policy,*,observer=None,extra=None,allow_unbound=None):
    """每次受管入口重新核对；无配置的旧服务保持原行为，不隐式加入或迁移。"""
    value=settings(policy)
    if value is None:return None
    volume=value['volume'];root=directory(volume['root']);declared=members(policy)
    if extra:
        require(type(extra) is dict and not set(extra)&set(declared),'invalid-request')
        for name,path in extra.items():
            candidate=directory(str(path));require(root!=candidate and root in candidate.parents,'permission-denied')
            declared[name]=candidate
    capacity,available=observe(volume,value['kind'],value['server_uuid'],observer)
    checked=inspect_paths(root,declared)
    permitted={allow_unbound} if type(allow_unbound) is str else set(allow_unbound or ())
    unregistered=[]
    for instance,entry in policy['instances'].items():
        candidate=Path(entry['root'])
        if (candidate/'runtime-profile.json').exists() or (candidate/'server-storage.json').exists():
            if instance in permitted and not (candidate/'server-storage.json').exists():
                unregistered.append(instance);continue
            check_context(candidate,instance,value)
    # 成员路径核对前后均验证原卷，拒绝挂载/容量漂移，不通过单次stat伪造卷证明。
    after_capacity,after_available=observe(volume,value['kind'],value['server_uuid'],observer)
    require(capacity==after_capacity,'identity-unknown')
    return {'state':'server-storage-pool-observed','policy_sha256':value['sha256'],
        'scope':'all-declared-server-managed-persistent-roots','capacity_bytes':capacity,
        'available_bytes':min(available,after_available),'members':checked,
        'aggregate_managed_roots_covered':True,'unregistered_instances':unregistered,
        'background_bindings_verified':not unregistered,'all_host_writes_covered':False,
        'per_instance_hard_disk_quota':False,'host_storage_modified':False,'automatic_cleanup':False}


def verify(policy,*,observer=None,extra=None,allow_unbound=None):
    try:return _verify(policy,observer=observer,extra=extra,allow_unbound=allow_unbound)
    except ContractError:raise
    except (OSError,ValueError,RuntimeError,sqlite3.Error,TypeError,KeyError):
        # RPC前的路径/数据库失败只暴露结构化未知，不向学生返回宿主路径或原始错误。
        raise ContractError('identity-unknown') from None


def context(root,instance,pool):
    from ctflab_generation_store import GenerationStore,digest
    root=guard(Path(root).absolute());store=GenerationStore(root)
    require(store.config['instance_uuid']==instance,'identity-unknown')
    directory_info=root.stat();ledger=guard(root/'ledger.sqlite3').stat();profile=guard(root/'runtime-profile.json')
    require(profile.stat().st_size<=8*1024**2,'storage-insufficient')
    value={'schema':1,'server_uuid':pool['server_uuid'],'instance_uuid':instance,'root':str(root),
        'root_identity':[directory_info.st_dev,directory_info.st_ino],
        'ledger_identity':[ledger.st_dev,ledger.st_ino],'profile_sha256':digest(profile),'storage_pool':pool}
    require(len(canonical(value).encode())<=65536,'storage-insufficient');return value


def registered(root):
    ledger=root/'ledger.sqlite3'
    if not ledger.exists():return None
    guard(ledger)
    with closing(sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True,timeout=0)) as db:
        row=db.execute("SELECT value FROM metadata WHERE key='server-storage'").fetchone()
    if row is None:return None
    require(type(row[0]) is str and len(row[0].encode())<=65536,'storage-insufficient')
    from ctflab_remote import decode
    return decode(row[0].encode(),65536)


def check_context(root,instance,pool):
    from ctflab_remote import private_json
    expected=context(root,instance,pool)
    require(canonical(registered(root))==canonical(expected)
        and canonical(private_json(root/'server-storage.json'))==canonical(expected),'identity-unknown')


def check_instance(root,*,observer=None):
    """独立后台/本机入口读取已登记上下文，不依赖原SSH管理进程继续存活。"""
    from ctflab_remote import private_json
    root=Path(root).absolute();path=root/'server-storage.json'
    value=registered(root)
    if value is None:
        require(not path.exists() and not path.is_symlink(),'identity-unknown');return None
    require(canonical(private_json(path))==canonical(value),'identity-unknown')
    require(type(value) is dict and value.get('root')==str(root),'identity-unknown')
    instance=uuid_text(value.get('instance_uuid'));server=uuid_text(value.get('server_uuid'))
    policy={'server_uuid':server,'instances':{instance:{'root':str(root)}},'storage_pool':value.get('storage_pool')}
    return verify(policy,observer=observer)


def _register_context(policy,instance):
    """仅已持实例门的新课程/显式绑定调用；原文件一致可取回，不覆盖旧登记。"""
    from ctflab_generation_store import GenerationStore
    from ctflab_remote import private_json
    from ctflab_windows_recovery import record
    root=Path(policy['instances'][instance]['root']);pool=settings(policy)
    require(pool is not None,'capability-unverified');store=GenerationStore(root)
    value=context(root,instance,pool);path=root/'server-storage.json'
    snapshot=store.snapshot()
    require(snapshot['active_generation']==0 and not snapshot['generations'] and not snapshot['unresolved'],'state-conflict')
    # 先提交账本标记；旁车丢失/部分写入时后台仍记得该实例已经受池约束。
    with store.db(write=True) as db:
        row=db.execute("SELECT value FROM metadata WHERE key='server-storage'").fetchone()
        if row is None:
            require(not path.exists() and not path.is_symlink(),'identity-unknown')
            db.execute('INSERT INTO metadata VALUES(?,?)',('server-storage',canonical(value)))
        else:require(canonical(json.loads(row['value']))==canonical(value),'identity-unknown')
    if path.exists() or path.is_symlink():require(canonical(private_json(path))==canonical(value),'identity-unknown')
    else:record(path,value)
    return value


def binding_preview(policy,instance,*,observer=None):
    from contextlib import ExitStack
    from ctflab_generation_store import GenerationStore
    from ctflab_storage_bind import quiet
    uuid_text(instance);require(instance in policy['instances'],'permission-denied')
    require('storage_pool' in policy,'capability-unverified')
    verify(policy,observer=observer,allow_unbound=tuple(policy['instances']))
    store=GenerationStore(policy['instances'][instance]['root'])
    with ExitStack() as stack:
        quiet(stack,store);value=context(store.root,instance,settings(policy))
        return {'context':value,'binding_sha256':fingerprint(value),'registered':(store.root/'server-storage.json').exists(),
            'host_storage_modified':False,'vm_operated':False}


def bind(policy,instance,expected,*,observer=None):
    from contextlib import ExitStack
    from ctflab_generation_store import GenerationStore
    from ctflab_storage_bind import quiet
    uuid_text(instance);require(instance in policy['instances'],'permission-denied')
    require('storage_pool' in policy,'capability-unverified')
    verify(policy,observer=observer,allow_unbound=tuple(policy['instances']))
    store=GenerationStore(policy['instances'][instance]['root'])
    with ExitStack() as stack:
        quiet(stack,store);value=context(store.root,instance,settings(policy))
        require(expected==fingerprint(value),'state-conflict');_register_context(policy,instance)
    return {'state':'server-storage-instance-registered','instance_uuid':instance,'host_storage_modified':False,'vm_operated':False}


def launch_binding(root):
    root=Path(root).absolute();value=registered(root)
    if value is None:return None
    check_instance(root)
    return {'root':str(root),'context_sha256':fingerprint(value)}


def verify_launch(spec,attempt):
    if 'server_storage' not in spec:return None
    value=spec['server_storage'];require(type(value) is dict and set(value)=={'root','context_sha256'},'identity-unknown')
    root=directory(value['root']);require(root in Path(attempt).parents and root in Path(spec['disk']).parents,'identity-unknown')
    context_value=registered(root)
    require(context_value is not None and fingerprint(context_value)==value['context_sha256'],'identity-unknown')
    return check_instance(root)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('preview','inspect','bind-preview','bind'));parser.add_argument('--policy',type=Path,required=True)
    parser.add_argument('--kind',choices=('linux','mac','windows'));parser.add_argument('--volume-policy',type=Path)
    parser.add_argument('--instance');parser.add_argument('--binding-sha256');parser.add_argument('--execute',action='store_true')
    args=parser.parse_args(argv)
    try:
        from ctflab_remote import private_json,validate_policy
        policy=validate_policy(private_json(args.policy))
        if args.action in ('bind','bind-preview'):
            require(args.kind is None and args.volume_policy is None)
            if args.action=='bind':
                require(args.execute and args.binding_sha256 is not None)
                result=bind(policy,args.instance,args.binding_sha256)
            else:
                require(not args.execute and args.binding_sha256 is None)
                result=binding_preview(policy,args.instance)
            print(canonical(result));return 0
        require(args.instance is None and args.binding_sha256 is None and not args.execute)
        if args.action=='preview':
            require(args.kind is not None and args.volume_policy is not None and 'storage_pool' not in policy,'state-conflict')
            value=describe(policy,args.kind,private_json(args.volume_policy));candidate=dict(policy,storage_pool=value)
            proof=verify(candidate,allow_unbound=tuple(candidate['instances']))
            print(canonical({'storage_pool':value,'proof':proof,'policy_before_sha256':fingerprint(policy),
                'policy_written':False,'host_storage_modified':False}));return 0
        require(args.kind is None and args.volume_policy is None and 'storage_pool' in policy)
        print(canonical(verify(policy)));return 0
    except (OSError,ValueError,RuntimeError,TypeError,KeyError,sqlite3.Error):
        print(canonical({'state':'refused-or-unknown','policy_written':False,'host_storage_modified':False,
            'automatic_cleanup':False}));return 2


if __name__=='__main__':raise SystemExit(main())
