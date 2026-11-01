"""租约准入、时钟漂移、异步执行与一次正常停机；真实SQLite，VM全部替身。"""
from contextlib import contextmanager
from datetime import datetime,timezone
import copy
import json
from pathlib import Path
import sqlite3
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import canonical,ContractError
from ctflab_local_service import LocalService
from ctflab_local_adapter import process_actor
from ctflab_generation_store import GenerationStore
from ctflab_lease_store import LeaseStore
from ctflab_remote_leases import RemoteLeases,execute_job
from ctflab_windows_recovery import record
from ctflab_remote import Runner,PROTOCOL
import test_ctflab_generation_store as generation_tests


class Clock:
    def __init__(self):
        self.boot=str(uuid.uuid4());self.mono=100.0;self.utc=datetime(2026,10,25,tzinfo=timezone.utc).timestamp()
    def sample(self):return {'boot_id':self.boot,'mono':self.mono,'utc':self.utc}
    def advance(self,seconds):self.mono+=seconds;self.utc+=seconds


class LeaseTests(unittest.TestCase):
    setUp=generation_tests.GenerationTests.setUp
    def configured(self,action='notify'):
        record(self.store.root/'runtime-profile.json',{})
        self.service=LocalService.create(self.store.root/'desktop-contract')
        self.clock=Clock();self.server=str(uuid.uuid4());self.jobs=[];self.lease=str(uuid.uuid4())
        plan=self.store.plan(1)
        limit={'cpus':plan['total_cpus'],'memory_mb':plan['total_memory_mb'],'disk_reservation_bytes':128*1024**2}
        self.policy={'schema':1,'server_uuid':self.server,
            'principals':{name:{'role':role,'instances':[self.instance],'expires':'2099-01-01T00:00:00Z'}
                          for name,role in [('alice','student'),('bob','student'),('teacher','teacher')]},
            'instances':{self.instance:{'root':str(self.store.root),'owner':'alice'}},
            'leases':{'root':str(self.root/'leases'),'capacity':dict(limit),'limits':{'alice':dict(limit)},
                      'max_ttl_seconds':3600,'instances':{self.instance:{'disk_reservation_bytes':64*1024**2,'expiry_action':action}}}}
        self.policy_path=self.root/'server-policy.json';record(self.policy_path,self.policy)
        LeaseStore.create(self.policy['leases']['root'],self.server,clock=self.clock)
        self.manager=self.make_manager()
    def write_policy(self):self.policy_path.write_text(canonical(self.policy))
    def make_manager(self,principal='alice'):
        return RemoteLeases(self.policy,principal,policy_path=self.policy_path,clock=self.clock,
                            make_backend=lambda _:self.backend,spawn=lambda path:self.jobs.append(path))
    def test_explicit_hard_memory_ceiling_is_counted_in_admission_budget(self):
        self.configured();plan=self.store.plan(1)
        limits={'cgroup_root':'/sys/fs/cgroup/user.slice/ctflab-delegated','nodes':{
            name:{'memory_max_mb':node['memory_mb']+128,'cpu_quota_us':node['cpus']*100000,'pids_max':128}
            for name,node in plan['manifest']['nodes'].items()}}
        profile=self.store.root/'runtime-profile.json';profile.write_text(canonical({'resource_limits':limits}))
        binding=self.manager.binding(self.instance)
        self.assertEqual(binding['memory_mb'],plan['total_memory_mb']+128*len(limits['nodes']))
        # 原来只预留来宾内存的额度不足时拒绝，不自动提高容量或降为软限额。
        with self.assertRaises(ContractError):self.acquire()

    def test_windows_job_commit_ceiling_is_counted_without_claiming_windows_remote_execution(self):
        self.configured();plan=self.store.plan(1)
        limits={'schema':1,'nodes':{name:{'memory_max_mb':node['memory_mb']+256,'cpu_rate':2000,'processes_max':16}
            for name,node in plan['manifest']['nodes'].items()}}
        (self.store.root/'runtime-profile.json').write_text(canonical({'windows_limits':limits}))
        self.assertEqual(self.manager.binding(self.instance)['memory_mb'],plan['total_memory_mb']+3*256)
        with self.assertRaises(ContractError):self.acquire()
        self.assertEqual(self.driver.calls,[])

    def test_windows_dedicated_volume_reserves_whole_declared_ceiling(self):
        from ctflab_windows_storage import enroll
        self.configured()
        class Observer:
            def probe(self,*args):return {'capacity_bytes':512*1024**2},256*1024**2
        boundary=enroll('E:\\instance','E:\\',self.instance,1024**3,observer=Observer())
        (self.store.root/'runtime-profile.json').write_text(canonical({'windows_storage':boundary}))
        with patch('ctflab_windows_storage.verify',return_value={'available_bytes':256*1024**2}):
            with self.assertRaises(ContractError):self.manager.binding(self.instance)
            self.policy['leases']['instances'][self.instance]['disk_reservation_bytes']=1024**3
            self.write_policy();self.manager=self.make_manager()
            value=self.manager.binding(self.instance);self.assertEqual(value['windows_storage_sha256'],boundary['sha256'])
            self.assertEqual(value['disk_reservation_bytes'],1024**3)
        self.assertEqual(self.driver.calls,[])

    def test_unclosed_storage_binding_prevents_lease_admission(self):
        self.configured();record(self.store.root/'storage-bind.intent.json',{})
        with self.assertRaises((OSError,ContractError)):self.acquire()
        self.assertEqual(self.driver.calls,[])

    def acquire(self,ttl=60):
        return self.manager.acquire(self.instance,self.lease,ttl,self.policy['leases']['instances'][self.instance]['expiry_action'])
    def request(self,action):
        status=self.service.status({'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),
                                   'instance_uuid':self.instance,'operation':'status'},process_actor())
        parameters={'prepare':{'course_id':'c01','baseline_id':'base'},'start':{'display':'headless','allow_emulation':False},
                    'stop':{},'recover':{},'reset':{'baseline_id':'base'}}[action]
        return {'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),'operation':action,
                'instance_uuid':self.instance,'expected_generation':None if action=='prepare' else status['generation'],
                'expected_state_revision':None if action=='prepare' else status['state_revision'],
                'idempotency_key':str(uuid.uuid4()),'parameters':parameters}
    def operate(self,action):
        value=self.manager.submit(self.instance,self.request(action),None if action in ('stop','recover') else self.lease)
        self.assertEqual(value['result'],'accepted')
        return execute_job(self.jobs[-1],clock=self.clock,make_backend=lambda _:self.backend)

    def test_acquire_renew_release_keeps_disk_reference_and_never_stops_vm(self):
        self.configured();value=self.acquire();self.assertEqual(value['state'],'active')
        self.clock.advance(5);renewal=str(uuid.uuid4())
        value=self.manager.renew(self.instance,self.lease,renewal,100);expires=value['expires_at']
        self.clock.advance(5)
        value=self.manager.renew(self.instance,self.lease,renewal,100)
        self.assertEqual(value['expires_at'],expires);self.assertTrue(value['already_recorded'])
        self.assertEqual(self.manager.release(self.instance,self.lease)['state'],'released')
        usage=self.manager.pool.usage('alice')['principal']
        self.assertEqual(usage['cpus'],0);self.assertEqual(usage['disk_reservation_bytes'],64*1024**2)
        self.assertEqual(self.driver.calls,[])

    def test_ttl_and_renewal_ids_are_strict_and_no_revive_after_expiry(self):
        self.configured()
        for ttl in (True,0,3601):
            with self.assertRaises(ContractError):self.acquire(ttl)
        self.acquire(10);renewal=str(uuid.uuid4());self.manager.renew(self.instance,self.lease,renewal,10)
        with self.assertRaises(ContractError):self.manager.renew(self.instance,self.lease,renewal,20)
        self.clock.advance(11)
        with self.assertRaises(ContractError):self.manager.renew(self.instance,self.lease,str(uuid.uuid4()),10)
        self.assertEqual(self.manager.status(self.instance,self.lease)['state'],'expired')

    def test_storage_charged_once_on_reacquire_and_lease_history_cannot_be_revived(self):
        self.configured();self.acquire();self.manager.release(self.instance,self.lease)
        old=self.acquire();self.assertEqual(old['state'],'released')
        self.lease=str(uuid.uuid4());self.acquire()
        self.assertEqual(self.manager.pool.usage('alice')['principal']['disk_reservation_bytes'],64*1024**2)

    def test_unknown_principal_owner_or_server_cannot_borrow_quota(self):
        self.configured()
        for name in ('bob','teacher'):
            with self.assertRaises(ContractError):self.make_manager(name).acquire(self.instance,self.lease,60,'notify')
        with self.assertRaises(ContractError):LeaseStore(self.policy['leases']['root'],str(uuid.uuid4()),clock=self.clock)
        self.assertEqual(self.driver.calls,[])

    def test_clock_rollback_or_new_boot_retains_quota_and_never_stops(self):
        self.configured('request-stop');self.acquire(10)
        self.clock.utc-=600
        value=self.manager.expiry(self.lease);self.assertEqual(value['time_state'],'clock-uncertain')
        self.assertEqual(self.jobs,[])
        self.clock.utc+=600;self.clock.boot=str(uuid.uuid4())
        with self.assertRaises(ContractError):self.manager.renew(self.instance,self.lease,str(uuid.uuid4()),60)
        self.assertGreater(self.manager.pool.usage('alice')['principal']['cpus'],0)

    def test_pool_gate_is_cross_connection_and_never_reentrant(self):
        self.configured();other=self.make_manager()
        with self.manager.pool.locked():
            with self.assertRaises(ContractError):other.acquire(self.instance,self.lease,60,'notify')
            with self.assertRaises(ContractError):
                with self.manager.pool.locked():pass

    def test_quota_denial_has_no_contract_or_vm_effect(self):
        self.configured();self.policy['leases']['limits']['alice']['cpus']=1;self.write_policy();self.manager=self.make_manager()
        with self.assertRaises(ContractError):self.acquire()
        self.assertEqual(self.driver.calls,[])
        with self.service._read() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM operations').fetchone()[0],0)

    def test_running_unenrolled_instance_cannot_be_adopted_or_stopped(self):
        self.configured()
        self.backend.execute({'operation':'prepare','parameters':{'course_id':'c01','baseline_id':'base'}},
                             generation_tests.GenerationTests.context(self))
        self.backend.execute({'operation':'start','parameters':{'display':'headless','allow_emulation':False}},
                             generation_tests.GenerationTests.context(self))
        before=list(self.driver.calls)
        with self.assertRaises(ContractError):self.acquire()
        self.assertEqual(self.driver.calls,before)

    def test_submit_requires_lease_and_worker_rechecks_after_queue_delay(self):
        self.configured();self.acquire(10)
        with self.assertRaises(ContractError):self.manager.submit(self.instance,self.request('prepare'),None)
        accepted=self.manager.submit(self.instance,self.request('prepare'),self.lease)
        self.assertEqual(accepted['result'],'accepted');self.clock.advance(11)
        result=execute_job(self.jobs[-1],clock=self.clock,make_backend=lambda _:self.backend)
        self.assertEqual(result['state'],'recovery-required');self.assertEqual(self.driver.calls,[])

    def test_worker_and_normal_lifecycle_are_bound_and_idempotent(self):
        self.configured();self.acquire();self.assertEqual(self.operate('prepare')['state'],'prepared')
        self.assertEqual(self.operate('start')['state'],'process-running')
        path=self.jobs[-1];before=list(self.driver.calls)
        self.assertEqual(execute_job(path,clock=self.clock,make_backend=lambda _:self.backend)['state'],'process-running')
        self.assertEqual(self.driver.calls,before)
        self.assertEqual(self.operate('stop')['state'],'stopped')
        self.assertEqual(self.manager.release(self.instance,self.lease)['state'],'released')

    def test_expiry_notify_never_submits_stop_and_keeps_reserved_cpu(self):
        self.configured();self.acquire(10);self.operate('prepare');self.operate('start')
        before=len(self.jobs);self.clock.advance(11);value=self.manager.expiry(self.lease)
        self.assertEqual(value['state'],'attention');self.assertEqual(len(self.jobs),before)
        self.assertFalse(any(c[0]=='stop' for c in self.driver.calls))
        with self.assertRaises(ContractError):self.manager.release(self.instance,self.lease)
        self.assertGreater(self.manager.pool.usage('alice')['principal']['cpus'],0)

    def test_opted_expiry_submits_one_normal_stop_then_verifies_release(self):
        self.configured('request-stop');self.acquire(10);self.operate('prepare');self.operate('start')
        self.clock.advance(11);before=len(self.jobs)
        value=self.manager.expiry(self.lease);self.assertEqual(value['state'],'stop-submitted')
        self.assertEqual(len(self.jobs),before+1)
        self.manager.expiry(self.lease);self.assertEqual(len(self.jobs),before+1)
        self.assertEqual(execute_job(self.jobs[-1],clock=self.clock,make_backend=lambda _:self.backend)['state'],'stopped')
        value=self.manager.expiry(self.lease);self.assertEqual(value['state'],'released');self.assertFalse(value['graceful_stop_verified'])
        self.assertEqual(len([c for c in self.driver.calls if c[0]=='stop']),len(self.manifest['nodes']))

    def test_stop_timeout_or_dispatch_loss_retains_quota_and_never_retries(self):
        self.configured('request-stop');self.acquire(10);self.operate('prepare');self.operate('start')
        self.clock.advance(11);self.driver.timeout=True;self.manager.expiry(self.lease)
        execute_job(self.jobs[-1],clock=self.clock,make_backend=lambda _:self.backend)
        before=list(self.driver.calls);count=len(self.jobs)
        for _ in range(2):self.assertEqual(self.manager.expiry(self.lease)['state'],'attention')
        self.assertEqual(self.driver.calls,before);self.assertEqual(len(self.jobs),count)
        self.assertGreater(self.manager.pool.usage('alice')['principal']['cpus'],0)

    def test_worker_policy_revocation_or_profile_change_prevents_resource_action(self):
        self.configured();self.acquire();self.manager.submit(self.instance,self.request('prepare'),self.lease)
        self.policy['principals']['alice']['instances']=[];self.write_policy()
        with self.assertRaises(ContractError):execute_job(self.jobs[-1],clock=self.clock,make_backend=lambda _:self.backend)
        self.assertEqual(self.driver.calls,[])

    def test_expiry_during_start_does_not_start_remaining_nodes(self):
        self.configured('request-stop');self.acquire(10);self.operate('prepare')
        original=self.driver.start
        def slow(*args):original(*args);self.clock.advance(6)
        self.driver.start=slow
        value=self.operate('start');self.assertEqual(value['state'],'recovery-required')
        self.assertEqual(len([c for c in self.driver.calls if c[0]=='start']),2)

    def test_runner_lease_api_and_submit_cannot_bypass_admission(self):
        self.configured();runner=Runner(self.policy,'alice',lease_manager=self.manager,policy_path=self.policy_path)
        def req(action,parameters):return {'protocol':PROTOCOL,'version':1,'request_id':str(uuid.uuid4()),
                    'server_uuid':self.server,'action':action,'parameters':parameters}
        capabilities=runner.exchange(req('handshake',{}))['result'];self.assertTrue(capabilities['resource_leases'])
        with self.assertRaises(ContractError):runner.exchange(req('submit',{'instance_uuid':self.instance,'request':self.request('prepare')}))
        value=runner.exchange(req('lease-acquire',{'instance_uuid':self.instance,'lease_id':self.lease,'ttl_seconds':60,'expiry_action':'notify'}))
        self.assertEqual(value['result']['state'],'active')
        accepted=runner.exchange(req('submit',{'instance_uuid':self.instance,'request':self.request('prepare'),'lease_id':self.lease}))
        self.assertEqual(accepted['result']['result'],'accepted')

    def test_teacher_controls_scoped_instance_using_owner_quota_but_cannot_extend_owner_lease(self):
        self.configured();self.acquire();teacher=self.make_manager('teacher')
        with self.assertRaises(ContractError):teacher.renew(self.instance,self.lease,str(uuid.uuid4()),120)
        value=teacher.submit(self.instance,self.request('prepare'),self.lease)
        self.assertEqual(value['result'],'accepted')
        self.assertEqual(execute_job(self.jobs[-1],clock=self.clock,make_backend=lambda _:self.backend)['state'],'prepared')
        self.assertEqual(self.manager.pool.usage('teacher')['principal']['cpus'],0)
        self.assertEqual(self.manager.pool.usage('alice')['principal']['cpus'],self.store.plan(1)['total_cpus'])

    def test_cancellation_remains_available_while_worker_holds_lease_gate(self):
        self.configured();self.acquire();self.operate('prepare');original=self.driver.start;results=[]
        def cancel_after_first(*args):
            original(*args)
            if results:return
            status=self.service.status({'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),
                    'operation':'status','instance_uuid':self.instance},process_actor())
            request={'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),'operation':'cancel',
                     'instance_uuid':self.instance,'expected_generation':status['generation'],
                     'expected_state_revision':status['state_revision'],'idempotency_key':str(uuid.uuid4()),
                     'parameters':{'operation_id':status['operation_id']}}
            results.append(self.manager.submit(self.instance,request))
        self.driver.start=cancel_after_first
        self.assertEqual(self.operate('start')['state'],'recovery-required')
        self.assertEqual(results[0]['result'],'completed')
        self.assertEqual(len([c for c in self.driver.calls if c[0]=='start']),1)

    def test_no_stop_opt_in_or_explicit_profile_change_cannot_be_ignored(self):
        self.configured('request-stop')
        with self.assertRaises(ContractError):self.manager.acquire(self.instance,self.lease,60,'notify')
        self.acquire();self.manager.submit(self.instance,self.request('prepare'),self.lease)
        (self.store.root/'runtime-profile.json').write_text('{"changed":true}')
        value=execute_job(self.jobs[-1],clock=self.clock,make_backend=lambda _:self.backend)
        self.assertEqual(value['state'],'recovery-required');self.assertEqual(self.driver.calls,[])

    def test_global_capacity_blocks_other_owner_even_with_individual_capacity(self):
        self.configured();self.acquire()
        instance=str(uuid.uuid4());root=self.root/'second'
        GenerationStore.create(root,self.manifest,instance,{'linux':self.base})
        record(root/'runtime-profile.json',{});LocalService.create(root/'desktop-contract')
        self.policy['instances'][instance]={'root':str(root),'owner':'bob'}
        self.policy['principals']['bob']['instances']=[instance]
        self.policy['leases']['instances'][instance]={'disk_reservation_bytes':64*1024**2,'expiry_action':'notify'}
        self.policy['leases']['limits']['bob']=dict(self.policy['leases']['capacity']);self.write_policy()
        bob=self.make_manager('bob')
        with self.assertRaises(ContractError):bob.acquire(instance,str(uuid.uuid4()),60,'notify')
        self.assertEqual(self.manager.pool.usage('bob')['principal']['cpus'],0)

    def test_renewal_write_failure_rolls_back_deadline_and_idempotency_record_together(self):
        self.configured();self.acquire(10);before=self.manager.pool.get(self.lease)['deadline_mono']
        self.clock.advance(5);original=self.manager.pool.db
        class Proxy:
            def __init__(self,db):self.db=db
            def execute(self,sql,*args):
                if sql.startswith('INSERT INTO renewals'):raise sqlite3.OperationalError('synthetic renewal write failure')
                return self.db.execute(sql,*args)
        @contextmanager
        def fail_commit(**kwargs):
            with original(**kwargs) as db:yield Proxy(db) if kwargs.get('write') else db
        renewal=str(uuid.uuid4())
        with patch.object(self.manager.pool,'db',fail_commit):
            with self.assertRaises(ContractError):self.manager.renew(self.instance,self.lease,renewal,60)
        self.assertEqual(self.manager.pool.get(self.lease)['deadline_mono'],before)
        with self.manager.pool.db() as db:self.assertIsNone(db.execute('SELECT 1 FROM renewals WHERE id=?',(renewal,)).fetchone())

    def test_expiry_dispatch_failure_is_not_automatically_retried(self):
        self.configured('request-stop');self.acquire(10);self.operate('prepare');self.operate('start');self.clock.advance(11)
        calls=[]
        def failed(path):calls.append(path);raise OSError('synthetic worker spawn failure')
        self.manager.spawn=failed
        self.assertEqual(self.manager.expiry(self.lease)['state'],'attention')
        for _ in range(2):self.assertEqual(self.manager.expiry(self.lease)['state'],'attention')
        self.assertEqual(len(calls),1);self.assertFalse(any(c[0]=='stop' for c in self.driver.calls))


    def test_lease_pool_overlap_cannot_hide_behind_parent_components(self):
        self.configured()
        from ctflab_remote import validate_policy
        policy=copy.deepcopy(self.policy)
        policy['leases']['root']=str(self.store.root.parent/'uncreated'/'..'/self.store.root.name)
        with self.assertRaises(ContractError):validate_policy(policy)
        policy=copy.deepcopy(self.policy)
        policy['instances'][self.instance]['root']=str(self.root/'uncreated'/'..'/'leases'/'instance')
        with self.assertRaises(ContractError):validate_policy(policy)
        self.assertFalse((self.root/'uncreated').exists());self.assertEqual(self.jobs,[])


if __name__=='__main__':unittest.main()
