"""异步worker执行前/终态审计；生产契约协调器、实际SQLite、VM为替身。"""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_ctflab_remote_leases as leases
from ctflab_contract import ContractError,canonical
from ctflab_remote import Runner,PROTOCOL
from ctflab_remote_leases import execute_job
from ctflab_remote_audit import AuditStore,execute_audited
from ctflab_local_adapter import process_actor


class WorkerAuditTests(unittest.TestCase):
    setUp=leases.LeaseTests.setUp
    configured_lease=leases.LeaseTests.configured
    make_manager=leases.LeaseTests.make_manager
    write_policy=leases.LeaseTests.write_policy
    acquire=leases.LeaseTests.acquire
    request=leases.LeaseTests.request
    operate=leases.LeaseTests.operate

    def configured(self,capacity=100):
        self.configured_lease()
        self.policy['audit']={'root':str(self.root/'audit'),'max_attempts':capacity}
        self.audit=AuditStore.create(self.policy['audit'],self.server)
        self.write_policy();self.manager=self.make_manager();self.acquire()
    def submitted(self,action='prepare'):
        return self.manager.submit(self.instance,self.request(action),self.lease)
    def execute(self):return execute_job(self.jobs[-1],clock=self.clock,make_backend=lambda _:self.backend)
    def worker_events(self):
        rows=self.audit.read()['events']
        intents={r['attempt_id']:r for r in rows if r['phase']=='intent' and 'execution' in r['payload']}
        return [r for r in rows if r['attempt_id'] in intents]

    def test_request_receipt_and_worker_terminal_are_distinct_and_bound(self):
        self.configured();request=self.request('prepare')
        outer={'protocol':PROTOCOL,'version':1,'server_uuid':self.server,'request_id':str(uuid.uuid4()),
               'action':'submit','parameters':{'instance_uuid':self.instance,'request':request,'lease_id':self.lease}}
        accepted=Runner(self.policy,'alice',lease_manager=self.manager,policy_path=self.policy_path).exchange(outer)['result']
        rows=self.audit.read()['events'];self.assertEqual(len(rows),2);self.assertNotIn('execution',rows[0]['payload'])
        original=self.backend.execute
        def observed(req,context):
            events=self.worker_events();self.assertEqual(len(events),1)
            self.assertEqual(events[0]['payload']['execution']['operation_id'],accepted['operation_id'])
            return original(req,context)
        with patch.object(self.backend,'execute',side_effect=observed):result=self.execute()
        events=self.worker_events();self.assertEqual(len(events),2)
        self.assertEqual(events[1]['payload']['operation_id'],accepted['operation_id'])
        self.assertEqual(events[1]['payload']['contract']['state'],'prepared')
        self.assertEqual(events[1]['payload']['contract']['result'],result['result'])
        self.assertEqual(self.audit.read()['pending'],[])

    def test_worker_lease_expiry_records_contract_failure_without_driver_effect(self):
        self.configured();self.submitted();self.clock.advance(61)
        result=self.execute();self.assertEqual(result['state'],'recovery-required');self.assertEqual(self.driver.calls,[])
        terminal=self.worker_events()[-1]['payload']
        self.assertEqual(terminal['contract']['result'],'failed')
        self.assertEqual(terminal['contract']['error_code'],'permission-denied')
        self.assertFalse(self.audit.read()['guest_effect_verified'])

    def test_missing_audit_or_capacity_exhaustion_prevents_native_identity_and_effects(self):
        for failure in ('capacity','missing'):
            with self.subTest(failure=failure):
                # 每个分支独立契约/代次，避免未决任务影响下一分支。
                if failure=='missing':self.doCleanups();self.setUp()
                self.configured(capacity=1);accepted=self.submitted()
                if failure=='capacity':self.audit.begin({},'alice')
                else:(self.audit.root/'audit.sqlite3').rename(self.audit.root/'audit-preserved.sqlite3')
                with self.assertRaises(ContractError):execute_job(self.jobs[-1],clock=self.clock,make_backend=lambda _:self.backend,record_identity=True)
                self.assertEqual(self.driver.calls,[])
                self.assertFalse((self.store.root/('desktop-execution-'+accepted['operation_id']+'.json')).exists())
                with self.service._read() as db:
                    self.assertEqual(db.execute('SELECT status FROM operations WHERE id=?',(accepted['operation_id'],)).fetchone()[0],'pending')

    def test_result_write_failure_preserves_terminal_contract_and_audit_pending(self):
        self.configured();accepted=self.submitted()
        with patch.object(AuditStore,'finish',side_effect=sqlite3.OperationalError('secret failure')):
            with self.assertRaises(ContractError) as error:self.execute()
        self.assertEqual(error.exception.code,'persistence-failed')
        self.assertEqual(len(self.audit.read()['pending']),1)
        with self.service._read() as db:
            response=json.loads(db.execute('SELECT response FROM operations WHERE id=?',(accepted['operation_id'],)).fetchone()[0])
        self.assertEqual(response['state'],'prepared');self.assertNotIn('secret',canonical(self.audit.read()))
        before=list(self.driver.calls);self.assertEqual(self.execute()['state'],'prepared');self.assertEqual(self.driver.calls,before)
        self.assertEqual(len(self.audit.read()['pending']),1)

    def test_cached_execution_adds_observation_without_replaying_resource_action(self):
        self.configured();self.submitted();self.execute();before=list(self.driver.calls)
        self.execute();self.assertEqual(self.driver.calls,before)
        events=self.worker_events();self.assertEqual(len(events),4)
        self.assertNotEqual(events[0]['attempt_id'],events[2]['attempt_id'])
        self.assertEqual(events[1]['payload']['operation_id'],events[3]['payload']['operation_id'])

    def test_contract_cancellation_is_recorded_without_start(self):
        self.configured();self.operate('prepare');accepted=self.submitted('start')
        request={'protocol':'ctflab-local','version':1,'operation':'cancel','request_id':str(uuid.uuid4()),
                 'instance_uuid':self.instance,'expected_generation':accepted['generation'],
                 'expected_state_revision':accepted['state_revision'],'idempotency_key':str(uuid.uuid4()),
                 'parameters':{'operation_id':accepted['operation_id']}}
        self.service.submit(request,process_actor());before=list(self.driver.calls)
        result=self.execute();self.assertTrue(result['cancelled']);self.assertEqual(self.driver.calls,before)
        terminal=self.worker_events()[-1]['payload']['contract'];self.assertTrue(terminal['cancelled'])
        self.assertEqual(terminal['state'],'prepared')

    def test_revoked_scope_before_permit_binding_is_not_falsely_marked_executed(self):
        self.configured();self.submitted();self.policy['principals']['alice']['instances']=[];self.write_policy()
        with self.assertRaises(ContractError):self.execute()
        self.assertEqual(self.audit.read()['events'],[]);self.assertEqual(self.driver.calls,[])

    def test_legacy_request_events_keep_bytes_and_checkpoint_after_worker_append(self):
        self.configured();attempt=self.audit.begin({},'alice');self.audit.finish(attempt)
        before=self.audit.read();old=copy.deepcopy(before['events'])
        checkpoint={'seq':before['head_seq'],'sha256':before['head_sha256']}
        self.submitted();self.execute();after=self.audit.read(checkpoint=checkpoint)
        self.assertEqual(after['events'][:2],old);self.assertTrue(after['checkpoint_verified'])
        self.assertNotIn('execution',old[0]['payload']);self.assertNotIn('contract',old[1]['payload'])

    def test_request_cannot_forge_worker_origin(self):
        self.configured()
        request={'protocol':PROTOCOL,'version':1,'server_uuid':self.server,'request_id':str(uuid.uuid4()),
                 'action':'handshake','parameters':{},'execution':{'origin':'worker','operation_id':str(uuid.uuid4())}}
        with self.assertRaises(ContractError):Runner(self.policy,'alice').exchange(request)
        events=self.audit.read()['events'];self.assertNotIn('execution',events[0]['payload'])
        self.assertEqual(events[1]['payload']['code'],'invalid-request')

    def test_wrapper_exception_keeps_bound_operation_and_public_code_only(self):
        self.configured();operation=str(uuid.uuid4())
        def fail():raise ContractError('control-unreachable')
        with self.assertRaises(ContractError):execute_audited(self.policy,'alice',self.request('prepare'),operation,fail)
        terminal=self.worker_events()[-1]['payload'];self.assertEqual(terminal['operation_id'],operation)
        self.assertEqual(terminal['code'],'control-unreachable');self.assertNotIn('contract',terminal)

    def test_terminal_response_redacts_arbitrary_state_error_and_paths(self):
        self.configured();operation=str(uuid.uuid4())
        response={'operation_id':operation,'instance_uuid':self.instance,'state':'secret',
                  'result':'secret','error':{'code':'secret','message':'secret'},'cancelled':'secret','path':'/secret'}
        execute_audited(self.policy,'alice',self.request('prepare'),operation,lambda:response)
        result=self.audit.read();self.assertNotIn('secret',canonical(result))
        self.assertEqual(result['events'][-1]['payload']['contract'],{'state':None,'result':None,'cancelled':None,'error_code':None})

    def test_wrong_operation_or_instance_response_stays_pending(self):
        self.configured();operation=str(uuid.uuid4())
        for response in ({'operation_id':str(uuid.uuid4()),'instance_uuid':self.instance},
                         {'operation_id':operation,'instance_uuid':str(uuid.uuid4())}):
            with self.assertRaises(ContractError):execute_audited(self.policy,'alice',self.request('prepare'),operation,lambda:response)
        self.assertEqual(len(self.audit.read()['pending']),2)

    def test_normal_stop_timeout_records_failed_contract_without_retry(self):
        self.configured();self.operate('prepare');self.operate('start');self.driver.timeout=True
        self.submitted('stop');result=self.execute();before=list(self.driver.calls)
        terminal=self.worker_events()[-1]['payload']['contract']
        self.assertEqual(result['state'],'recovery-required');self.assertEqual(terminal['error_code'],'stop-timeout')
        self.assertEqual(terminal['result'],'failed');self.audit.read();self.assertEqual(self.driver.calls,before)

    def test_corrupt_audit_blocks_worker_before_resource_gate(self):
        self.configured();attempt=self.audit.begin({},'alice');self.audit.finish(attempt);self.submitted()
        with self.audit.transaction(write=True) as db:db.execute("UPDATE events SET payload='{}' WHERE seq=1")
        with self.assertRaises(ContractError):self.execute()
        self.assertEqual(self.driver.calls,[])

    def test_result_append_and_attempt_completion_roll_back_together(self):
        self.configured();self.submitted();original=AuditStore.append
        def fail(store,db,attempt,phase,payload):
            result=original(store,db,attempt,phase,payload)
            if phase=='result':raise sqlite3.OperationalError('synthetic result transaction failure')
            return result
        with patch.object(AuditStore,'append',new=fail):
            with self.assertRaises(ContractError):self.execute()
        result=self.audit.read();self.assertEqual(result['head_seq'],1)
        self.assertEqual(len(result['pending']),1)


if __name__=='__main__':unittest.main()
