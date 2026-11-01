"""受管Runner租约准入/异步执行/显式到期处理；默认不安装定时任务。

到期正常停止仅限先确认停机、明确申请request-stop的租约；不接管正在运行的旧实例。
"""
import argparse
from contextlib import contextmanager,ExitStack
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text,identifier,ContractError,fingerprint
from ctflab_generation_store import GenerationStore,digest,private_directory
from ctflab_local_service import LocalService,Outcome
from ctflab_local_adapter import process_actor
from ctflab_lease_store import LeaseStore,validate_settings
from ctflab_tls_endpoint import guard

SAFE={'status','cancel','stop','recover'}


class RemoteLeases:
    def __init__(self,policy,principal,*,policy_path=None,clock=None,make_backend=None,spawn=None):
        from ctflab_remote import validate_policy
        self.policy=validate_policy(policy);identifier(principal)
        require(principal in policy['principals'],'permission-denied')
        self.principal=principal;self.settings=validate_settings(policy['leases'])
        self.pool=LeaseStore(self.settings['root'],policy['server_uuid'],clock=clock)
        self.policy_path=Path(policy_path).absolute() if policy_path is not None else None
        self.make_backend=make_backend or self.backend
        self.spawn=spawn or spawn_job

    @staticmethod
    def backend(root):
        from ctflab_desktop_bridge import backend
        return backend(root)

    def entry(self,instance,*,owner=False):
        from ctflab_server_storage import verify as verify_storage
        verify_storage(self.policy)
        uuid_text(instance);account=self.policy['principals'][self.principal]
        require(instance in account['instances'] and instance in self.policy['instances'],'permission-denied')
        entry=self.policy['instances'][instance]
        require(account['role']!='student' or entry['owner']==self.principal,'permission-denied')
        if owner:require(entry['owner']==self.principal,'permission-denied')
        require(instance in self.settings['instances'],'capability-unverified')
        return entry

    def until(self):
        return datetime.fromisoformat(self.policy['principals'][self.principal]['expires'].replace('Z','+00:00')).timestamp()

    def binding(self,instance):
        entry=self.entry(instance);root=guard(Path(entry['root']))
        store=GenerationStore(root);require(store.config['instance_uuid']==instance,'identity-unknown')
        root_info=root.stat();ledger_info=guard(root/'ledger.sqlite3').stat()
        profile=guard(root/'runtime-profile.json');require(profile.stat().st_size<=1024**2)
        plan=store.plan(1);allocation=self.settings['instances'][instance]
        from ctflab_remote import private_json
        before=digest(profile);runtime=private_json(profile);memory=plan['total_memory_mb']
        if (root/'storage-bind.intent.json').exists():
            from ctflab_storage_bind import assert_closed
            assert_closed(root,runtime,instance=instance)
        if 'resource_limits' in runtime:
            from ctflab_cgroup import settings as limit_settings
            limits=limit_settings(runtime['resource_limits'],plan)
            memory=sum(entry['memory_max_mb'] for entry in limits['nodes'].values())
        if 'windows_limits' in runtime:
            require('resource_limits' not in runtime,'capability-unverified')
            from ctflab_windows_limits import settings as windows_limit_settings
            limits=windows_limit_settings(runtime['windows_limits'],plan)
            memory=sum(entry['memory_max_mb'] for entry in limits['nodes'].values())
        require(before==digest(profile),'identity-unknown')
        minimum=sum(store.config['assets'][v['asset']]['size'] for v in plan['manifest']['nodes'].values())
        minimum+=sum(v['size'] for v in store.config['nvram'].values())+32*1024**2
        if 'resource_limits' in runtime and all('disk_max_bytes' in entry for entry in runtime['resource_limits']['nodes'].values()):
            minimum+=sum(entry['disk_max_bytes'] for entry in runtime['resource_limits']['nodes'].values())
        storage={}
        require(len({'storage_boundary','macos_storage','windows_storage'}&set(runtime))<=1,'capability-unverified')
        if 'windows_storage' in runtime:
            from ctflab_windows_storage import verify as verify_windows_storage,require_exclusive_volume
            boundary=runtime['windows_storage'];verify_windows_storage(boundary,root=root,instance=instance)
            require_exclusive_volume(boundary['mountpoint'],instance,self.policy['instances'])
            minimum=max(minimum,boundary['max_bytes']);storage['windows_storage_sha256']=boundary['sha256']
        if 'storage_boundary' in runtime:
            from ctflab_storage_boundary import verify as verify_storage
            boundary=runtime['storage_boundary'];verify_storage(boundary,root=root,instance=instance)
            volume=Path(boundary['mountpoint'])
            require(all(other==instance or volume!=Path(item['root']) and volume not in Path(item['root']).parents
                and Path(item['root']) not in volume.parents
                for other,item in self.policy['instances'].items()),'permission-denied')
            minimum=max(minimum,boundary['max_bytes']);storage['storage_boundary_sha256']=boundary['sha256']
        require(allocation['disk_reservation_bytes']>=minimum,'storage-insufficient')
        return dict(storage,**{'instance_uuid':instance,'root':str(root),'root_identity':[root_info.st_dev,root_info.st_ino],
                'ledger_identity':[ledger_info.st_dev,ledger_info.st_ino],
                'config_sha256':hashlib.sha256(canonical(store.config).encode()).hexdigest(),
                'profile_sha256':before,'cpus':plan['total_cpus'],'memory_mb':memory,
                'disk_reservation_bytes':allocation['disk_reservation_bytes'],'expiry_action':allocation['expiry_action']})

    @contextmanager
    def quiet(self,instance,binding):
        """持工作/契约/代次门直到调用者提交决定，不能从历史状态推断停机。"""
        self.pool.held();root=Path(binding['root']);store=GenerationStore(root)
        with ExitStack() as stack:
            service=LocalService(root/'desktop-contract')
            stack.enter_context(service._transaction(worker=True))
            db=stack.enter_context(service._transaction())
            require(not db.execute('SELECT 1 FROM instances WHERE active IS NOT NULL').fetchone(),'resource-busy')
            stack.enter_context(store.locked());require(self.binding(instance)==binding,'identity-unknown')
            snapshot=store.snapshot();require(not snapshot['unresolved'],'identity-unknown')
            if snapshot['active_generation']>0:
                contract=db.execute('SELECT generation FROM instances WHERE id=?',(instance,)).fetchone()
                require(contract is not None and contract['generation']==snapshot['active_generation'],'identity-unknown')
            backend=self.make_backend(root) if snapshot['generations'] else None
            for generation in snapshot['generations']:
                require(generation['state']=='prepared','identity-unknown')
                values=backend.observations(generation['number'])
                require(all(v.state=='stopped' for v in values.values()),'state-conflict')
            yield

    def acquire(self,instance,lease,ttl,expiry_action):
        self.entry(instance,owner=True);binding=self.binding(instance)
        require(expiry_action==binding['expiry_action'],'permission-denied')
        with self.pool.locked():
            with self.pool.db() as db:prior=db.execute('SELECT 1 FROM leases WHERE id=?',(uuid_text(lease),)).fetchone()
            if prior:return self.pool.acquire_locked(self.principal,lease,ttl,binding,self.settings,self.until())
            with self.quiet(instance,binding):
                return self.pool.acquire_locked(self.principal,lease,ttl,binding,self.settings,self.until())

    def renew(self,instance,lease,renewal,ttl):
        self.entry(instance,owner=True);binding=self.binding(instance)
        with self.pool.locked():
            return self.pool.renew_locked(self.principal,lease,renewal,ttl,binding,self.settings,self.until())

    def status(self,instance,lease=None):
        self.entry(instance)
        if lease is not None:
            row=self.pool.get(lease);require(row['instance_uuid']==instance,'permission-denied')
            return self.pool.view(row)
        with self.pool.db() as db:
            ids=[r[0] for r in db.execute('SELECT id FROM leases WHERE instance=? ORDER BY rowid DESC LIMIT 100',(instance,))]
            count=db.execute('SELECT COUNT(*) FROM leases WHERE instance=?',(instance,)).fetchone()[0]
        rows=[self.pool.get(lease) for lease in ids]
        return {'leases':[self.pool.view(r) for r in rows],'usage':self.pool.usage(self.principal),
                'expiry_action':self.settings['instances'][instance]['expiry_action'],
                'max_ttl_seconds':self.settings['max_ttl_seconds'],
                'owner_actions':self.policy['instances'][instance]['owner']==self.principal,
                'history_truncated':count>len(rows),'disk_hard_enforced':False,'scheduler_installed':False}

    def release(self,instance,lease):
        self.entry(instance,owner=True)
        with self.pool.locked():
            row=self.pool.get(lease)
            require(row['principal']==self.principal and row['instance_uuid']==instance,'permission-denied')
            if row['state']=='released':return self.pool.view(row)
            binding=self.binding(instance);require(row['binding']==binding,'identity-unknown')
            with self.quiet(instance,binding):
                row['state']='released';self.pool.save(row)
            return self.pool.view(row)

    def require_policy(self,expected=None):
        from ctflab_server_storage import verify as verify_storage
        verify_storage(self.policy)
        require(self.policy_path is not None,'capability-unverified')
        from ctflab_remote import private_json
        require(canonical(private_json(self.policy_path))==canonical(self.policy),'permission-denied')
        actual=digest(guard(self.policy_path))
        if expected is not None:require(actual==expected,'permission-denied')
        return actual

    def submit(self,instance,request,lease=None):
        self.entry(instance)
        from ctflab_contract import validate_request
        request=validate_request(request);require(request['instance_uuid']==instance,'permission-denied')
        require(request['operation'] in ('status','cancel','stop') or self.pool.sample()['utc']<self.until(),'permission-denied')
        if request['operation'] in ('status','cancel'):
            # 取消走独立契约库；不能排在持有租约门的长执行之后。
            self.require_policy();root=guard(Path(self.entry(instance)['root']))
            require(GenerationStore(root).config['instance_uuid']==instance,'identity-unknown')
            from ctflab_desktop_bridge import dispatch
            return dispatch(root,{'action':'submit','request':request})
        with self.pool.locked():return self.submit_locked(instance,request,lease)

    def submit_locked(self,instance,request,lease=None,*,purpose='remote'):
        self.pool.held()
        from ctflab_contract import validate_request
        request=validate_request(request);require(request['instance_uuid']==instance,'permission-denied')
        binding=self.binding(instance);operation=request['operation']
        if operation not in SAFE:
            subject=self.entry(instance)['owner']
            self.pool.admit_locked(subject,lease,binding,self.settings)
            require(self.pool.sample()['utc']<self.until(),'permission-denied')
        policy_sha=self.require_policy()
        from ctflab_desktop_bridge import dispatch
        def spawn(root,action,*,operation=None,node=None):
            require(action=='execute' and node is None)
            path=self.pool.root/'jobs'/(uuid_text(operation)+'.json')
            permit={'schema':1,'server_uuid':self.policy['server_uuid'],'principal':self.principal,
                    'instance_uuid':instance,'operation_id':operation,'request_sha256':fingerprint(request),
                    'policy_path':str(self.policy_path),'policy_sha256':policy_sha,'lease_id':lease,
                    'binding':binding,'purpose':purpose}
            from ctflab_windows_recovery import record
            record(path,permit);self.spawn(path)
        return dispatch(Path(binding['root']),{'action':'submit','request':request},spawn=spawn)

    def expiry(self,lease):
        """显式到期处理一次；未知/超时保留额度，不重发关机或启动工作进程。"""
        with self.pool.locked():
            row=self.pool.get(lease);instance=row['instance_uuid']
            self.entry(instance,owner=True);require(row['principal']==self.principal,'permission-denied')
            if row['state']=='released':return self.pool.view(row)
            require(self.binding(instance)==row['binding'],'identity-unknown')
            timing=self.pool.time_state(row)
            if timing=='active' and row['stop_request'] is None:return self.pool.view(row)
            if timing=='clock-uncertain':
                row['state']='attention';row['attention']='clock-uncertain';self.pool.save(row);return self.pool.view(row)
            if row['binding']['expiry_action']=='notify':
                row['state']='attention';row['attention']='expired-notify-only';self.pool.save(row);return self.pool.view(row)
            try:
                with self.quiet(instance,row['binding']):
                    row['state']='released';self.pool.save(row)
                return self.pool.view(row)
            except ContractError as error:
                if error.code!='state-conflict':
                    row['state']='attention';row['attention']=error.code;self.pool.save(row);return self.pool.view(row)
            service=LocalService(Path(row['binding']['root'])/'desktop-contract')
            if row['stop_request'] is not None:
                # 已有提交意图即不再派发。即使断在submit和记录之间，也只读查契约原幂等键。
                with service._read() as db:
                    found=db.execute('SELECT id,digest,response FROM operations WHERE actor=? AND idem=?',
                        (process_actor(),row['stop_request']['idempotency_key'])).fetchone()
                if found:
                    require(found['digest']==fingerprint(row['stop_request']),'identity-unknown')
                    row['stop_operation_id']=found['id'];row['stop_response']=json.loads(found['response']) if found['response'] else None
                row['state']='attention';row['attention']='stop-pending-or-unknown';self.pool.save(row)
                return self.pool.view(row)
            status=service.status({'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),
                                   'operation':'status','instance_uuid':instance},process_actor())
            if not (type(status['generation']) is int and status['generation']>0 and type(status['state_revision']) is int):
                row['state']='attention';row['attention']='contract-unbound';self.pool.save(row);return self.pool.view(row)
            request={'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),'operation':'stop',
                     'instance_uuid':instance,'expected_generation':status['generation'],
                     'expected_state_revision':status['state_revision'],'idempotency_key':'lease-stop-'+lease,'parameters':{}}
            row['state']='stop-intent';row['stop_request']=request;self.pool.save(row)
            try:
                response=self.submit_locked(instance,request,lease,purpose='expiry')
                row['stop_response']=response;row['stop_operation_id']=response.get('operation_id')
                row['state']='stop-submitted' if response.get('result')=='accepted' else 'attention'
            except (OSError,ValueError,RuntimeError,sqlite3.Error):
                row['state']='attention';row['attention']='stop-dispatch-unknown'
            self.pool.save(row);return self.pool.view(row)


def spawn_job(permit):
    require(sys.platform=='linux' and os.geteuid()!=0,'unsupported-platform')
    permit=guard(Path(permit));pool=permit.parent.parent
    logs=pool/'job-logs'/permit.stem;private_directory(logs)
    from ctflab_bounded_log import spawn
    receiver=spawn(logs,'remote-execute')
    try:
        return subprocess.Popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),'worker','--permit',str(permit)],
            stdin=subprocess.DEVNULL,stdout=receiver.stdin,stderr=receiver.stdin,close_fds=True,start_new_session=True)
    finally:receiver.stdin.close()


def execute_job(path,*,clock=None,make_backend=None,record_identity=False):
    from ctflab_remote import private_json
    path=guard(Path(path).absolute());permit=private_json(path)
    require(type(permit) is dict and set(permit)=={'schema','server_uuid','principal','instance_uuid','operation_id',
             'request_sha256','policy_path','policy_sha256','lease_id','binding','purpose'})
    require(type(permit['schema']) is int and permit['schema']==1)
    uuid_text(permit['operation_id']);require(path.name==permit['operation_id']+'.json')
    policy=private_json(permit['policy_path'])
    manager=RemoteLeases(policy,permit['principal'],policy_path=permit['policy_path'],clock=clock,make_backend=make_backend)
    require(path.parent==manager.pool.root/'jobs' and policy['server_uuid']==permit['server_uuid'],'identity-unknown')
    instance=permit['instance_uuid'];entry=manager.entry(instance)
    require(permit['binding']['root']==entry['root'],'identity-unknown')
    root=guard(Path(entry['root']));service=LocalService(root/'desktop-contract')
    with service._read() as db:
        operation=db.execute('SELECT request,digest FROM operations WHERE id=? AND actor=?',
                             (permit['operation_id'],process_actor())).fetchone()
    require(operation is not None and operation['digest']==permit['request_sha256'],'identity-unknown')
    request=json.loads(operation['request'])
    def authorized():
        manager.entry(instance);manager.require_policy(permit['policy_sha256'])
        require(manager.binding(instance)==permit['binding'],'identity-unknown')
        require(request['instance_uuid']==instance and permit['purpose'] in ('remote','expiry'),'permission-denied')
        require(request['operation'] in ('status','cancel','stop') or manager.pool.sample()['utc']<manager.until(),'permission-denied')
        if permit['purpose']=='expiry':
            row=manager.pool.get(permit['lease_id'])
            require(request['operation']=='stop' and row['principal']==manager.principal
                    and row['instance_uuid']==instance and row['binding']==permit['binding']
                    and row['binding']['expiry_action']=='request-stop' and row['stop_request']==request,'permission-denied')
        if request['operation'] not in SAFE:
            subject=manager.entry(instance)['owner']
            manager.pool.admit_locked(subject,permit['lease_id'],permit['binding'],manager.settings)
            require(manager.pool.sample()['utc']<manager.until(),'permission-denied')
    class BoundBackend:
        def __init__(self):self.backend=None
        def actual(self):
            authorized()
            if self.backend is None:self.backend=manager.make_backend(root)
            return self.backend
        def observe(self,context):return self.actual().observe(context)
        def execute(self,req,context):
            backend=self.actual()
            def cancelled():
                if context.cancel_requested():return True
                try:authorized();return False
                except (OSError,ValueError,RuntimeError,sqlite3.Error):return True
            result=backend.execute(req,replace(context,cancel_requested=cancelled))
            if result.cancelled and not context.cancel_requested():return Outcome('recovery-required','state-conflict')
            return result
    class Denied:
        def observe(self,context):raise ContractError('permission-denied')
        def execute(self,req,context):raise ContractError('permission-denied')
    def execute():
        try:
            with manager.pool.locked():
                authorized()
                if record_identity:
                    from ctflab_windows_recovery import record
                    from ctflab_qemu_driver import native_observe
                    from dataclasses import asdict
                    record(root/('desktop-execution-'+permit['operation_id']+'.json'),asdict(native_observe(os.getpid())))
                return service.execute(permit['operation_id'],process_actor(),BoundBackend())
        except ContractError:
            # 没有取得租约门时只完成失败记录，不运行真实后端，也不留待自动重派发。
            return service.execute(permit['operation_id'],process_actor(),Denied())
    from ctflab_remote_audit import execute_audited
    return execute_audited(policy,manager.principal,request,permit['operation_id'],execute)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    init=sub.add_parser('initialize');init.add_argument('--policy',type=Path,required=True)
    worker=sub.add_parser('worker');worker.add_argument('--permit',type=Path,required=True)
    expiry=sub.add_parser('expiry');expiry.add_argument('--policy',type=Path,required=True);expiry.add_argument('--lease-id',required=True)
    args=parser.parse_args(argv)
    try:
        from ctflab_remote import private_json,validate_policy
        if args.action=='initialize':
            policy=validate_policy(private_json(args.policy));settings=validate_settings(policy['leases'])
            from ctflab_server_storage import verify as verify_storage
            verify_storage(policy)
            LeaseStore.create(settings['root'],policy['server_uuid']);value={'state':'initialized','scheduler_installed':False}
        else:
            require(sys.platform=='linux' and os.geteuid()!=0,'unsupported-platform')
            if args.action=='worker':
                value=execute_job(args.permit,record_identity=True)
            else:
                policy=validate_policy(private_json(args.policy));pool=LeaseStore(policy['leases']['root'],policy['server_uuid'])
                row=pool.get(args.lease_id)
                value=RemoteLeases(policy,row['principal'],policy_path=args.policy).expiry(args.lease_id)
        print(canonical(value));return 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,sqlite3.Error):
        print(canonical({'state':'unknown','automatic_replay':False,'preserved':True}));return 2


if __name__=='__main__':raise SystemExit(main())
