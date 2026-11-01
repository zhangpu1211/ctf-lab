"""未决审计只读关联：实际SQLite/文件，VM全部替身。"""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_ctflab_worker_audit as worker
from ctflab_audit_review import AuditReview,readonly
from ctflab_contract import canonical,ContractError
from ctflab_remote_audit import AuditStore


class ReviewTests(unittest.TestCase):
    setUp=worker.WorkerAuditTests.setUp
    configured_lease=worker.WorkerAuditTests.configured_lease
    make_manager=worker.WorkerAuditTests.make_manager
    write_policy=worker.WorkerAuditTests.write_policy
    acquire=worker.WorkerAuditTests.acquire
    request=worker.WorkerAuditTests.request
    operate=worker.WorkerAuditTests.operate
    configured=worker.WorkerAuditTests.configured
    submitted=worker.WorkerAuditTests.submitted
    execute=worker.WorkerAuditTests.execute

    def intent(self,accepted):
        with self.service._read() as db:
            request=json.loads(db.execute('SELECT request FROM operations WHERE id=?',(accepted['operation_id'],)).fetchone()[0])
        return self.audit.begin({'action':'submit','request_id':request['request_id'],
            'parameters':{'instance_uuid':self.instance,'request':request}},'alice',
            execution={'origin':'worker','operation_id':accepted['operation_id']})
    def completed_pending(self,admin=False):
        self.configured()
        if admin:self.enable_admin();self.manager=self.make_manager()
        accepted=self.submitted()
        with patch.object(AuditStore,'finish',side_effect=OSError('synthetic audit failure')):
            with self.assertRaises(ContractError):self.execute()
        return accepted
    def hashes(self):
        return {str(p.relative_to(self.root)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def admin_rpc(self,action,parameters,principal='admin'):
        import uuid
        from ctflab_remote import Runner,PROTOCOL
        return Runner(self.policy,principal,policy_path=self.policy_path,now=lambda:__import__('datetime').datetime.fromtimestamp(self.clock.utc,__import__('datetime').timezone.utc)).exchange(
            {'protocol':PROTOCOL,'version':1,'request_id':str(uuid.uuid4()),'server_uuid':self.server,
             'action':action,'parameters':parameters})['result']
    def enable_admin(self):
        self.policy['principals']['admin']=dict(self.policy['principals']['alice'],role='administrator')
        self.policy['audit_management']=True;self.write_policy()
    def test_admin_rpc_read_preview_settle_retry_preserves_original_unknown_and_never_dispatches(self):
        self.completed_pending(admin=True);calls=list(self.driver.calls)
        before=self.audit.read()['events'];page=self.admin_rpc('audit-review',{'after':0,'limit':100,'checkpoint':None})
        attempt=next(r['attempt_id'] for r in page['pending'] if r['origin']=='worker')
        plan=self.admin_rpc('audit-settlement-preview',{'attempt_id':attempt})
        self.assertEqual(self.audit.read()['events'],before)
        params={'attempt_id':attempt,'review_sha256':plan['review_sha256']}
        result=self.admin_rpc('audit-settle',params)
        self.assertEqual(result['original_worker_result'],'unknown');self.assertFalse(result['vm_observed'])
        events=self.audit.read()['events'];self.assertEqual(events[-1]['payload']['resolution']['principal'],'admin');self.assertTrue(self.admin_rpc('audit-settle',params)['already_settled'])
        self.assertEqual(self.audit.read()['events'],events);self.assertEqual(self.driver.calls,calls)
    def test_admin_rpc_requires_optin_role_and_current_policy_and_rejects_extra_paths(self):
        self.configured();self.enable_admin();params={'after':0,'limit':100,'checkpoint':None}
        before=len(self.audit.read()['events'])
        with self.assertRaises(ContractError):self.admin_rpc('audit-review',params,'alice')
        self.assertGreater(len(self.audit.read()['events']),before)
        with self.assertRaises(ContractError):self.admin_rpc('audit-review',params|{'path':'/outside'})
        self.policy_path.write_text(self.policy_path.read_text()+' ')
        # 语义相同的当前策略允许读取；实际授权改变则拒绝旧Runner。
        current=json.loads(self.policy_path.read_text());current['audit_management']=False
        self.policy_path.write_text(canonical(current))
        with self.assertRaises(ContractError):self.admin_rpc('audit-review',params)
    def test_admin_rpc_stale_preview_cannot_settle(self):
        self.completed_pending(admin=True);attempt=self.audit.read()['pending'][0]
        plan=self.admin_rpc('audit-settlement-preview',{'attempt_id':attempt})
        self.audit.begin({'action':'list'},'alice')
        with self.assertRaises(ContractError):self.admin_rpc('audit-settle',{'attempt_id':attempt,'review_sha256':plan['review_sha256']})
        self.assertIn(attempt,self.audit.read()['pending'])

    def test_explicit_settlement_keeps_original_worker_result_unknown_and_no_vm_replay(self):
        self.completed_pending();review=AuditReview(self.policy_path);attempt=self.audit.read()['pending'][0]
        before=self.hashes();calls=list(self.driver.calls);plan=review.preview_settlement(attempt)
        self.assertEqual(self.hashes(),before)
        result=review.settle(attempt,plan['review_sha256'])
        self.assertEqual(result['original_worker_result'],'unknown');self.assertFalse(result['vm_observed'])
        self.assertEqual(self.driver.calls,calls);self.assertEqual(self.audit.read()['pending'],[])
        event=self.audit.read()['events'][-1]
        self.assertEqual(event['payload']['outcome'],'unknown')
        self.assertEqual(event['payload']['resolution']['source'],'explicit-contract-observation')
        with self.assertRaises(ContractError):review.settle(attempt,plan['review_sha256'])
        for name,sha in before.items():
            if not name.startswith('audit/'):
                self.assertEqual(self.hashes()[name],sha)

    def test_pending_contract_cannot_be_settled_or_force_marked_returned(self):
        self.configured();accepted=self.submitted();attempt=self.intent(accepted)
        review=AuditReview(self.policy_path)
        with self.assertRaises(ContractError):review.preview_settlement(attempt)
        with self.assertRaises(ContractError):review.settle(attempt,'0'*64)
        self.assertIn(attempt,self.audit.read()['pending'])

    def test_settlement_requires_current_head_and_current_policy(self):
        self.completed_pending();attempt=self.audit.read()['pending'][0];review=AuditReview(self.policy_path)
        plan=review.preview_settlement(attempt)
        self.audit.begin({'action':'list'},'alice')
        with self.assertRaises(ContractError):review.settle(attempt,plan['review_sha256'])
        plan=review.preview_settlement(attempt)
        self.policy_path.write_text(self.policy_path.read_text()+' ')
        with self.assertRaises(ContractError):review.settle(attempt,plan['review_sha256'])
        self.assertIn(attempt,self.audit.read()['pending'])

    def test_request_intent_without_worker_binding_cannot_be_settled(self):
        self.configured();attempt=self.audit.begin({'action':'list'},'alice')
        with self.assertRaises(ContractError):AuditReview(self.policy_path).preview_settlement(attempt)
        self.assertIn(attempt,self.audit.read()['pending'])

    def test_observation_drift_within_settlement_rolls_back_append(self):
        self.completed_pending();attempt=self.audit.read()['pending'][0];review=AuditReview(self.policy_path)
        plan=review.preview_settlement(attempt);original=review.observation;calls=[]
        def observation(intent):
            value=original(intent);calls.append(True)
            if len(calls)==2:value['contract']['generation']+=1
            return value
        with patch.object(review,'observation',side_effect=observation):
            with self.assertRaises(ContractError):review.settle(attempt,plan['review_sha256'])
        self.assertIn(attempt,self.audit.read()['pending'])

    def test_recorded_contract_is_reported_without_modifying_any_fixture_or_replaying(self):
        accepted=self.completed_pending();before=self.hashes();calls=list(self.driver.calls)
        report=AuditReview(self.policy_path).read();row=report['pending'][0]
        self.assertEqual(row['operation_id'],accepted['operation_id']);self.assertEqual(row['observation'],'contract-recorded')
        self.assertEqual(row['contract']['state'],'prepared');self.assertEqual(row['contract']['result'],'completed')
        self.assertEqual(self.hashes(),before);self.assertEqual(self.driver.calls,calls)
        for field in ('audit_modified','contract_modified','vm_observed','automatic_replay','guest_effect_verified','graceful_stop_verified','snapshots_atomic'):
            self.assertFalse(report[field])
        self.assertEqual(len(self.audit.read()['pending']),1)

    def test_pending_and_executing_are_ledger_status_only(self):
        self.configured();accepted=self.submitted();self.intent(accepted)
        self.assertEqual(AuditReview(self.policy_path).read()['pending'][0]['observation'],'contract-pending')
        with self.service._transaction() as db:db.execute("UPDATE operations SET status='executing' WHERE id=?",(accepted['operation_id'],))
        self.assertEqual(AuditReview(self.policy_path).read()['pending'][0]['observation'],'contract-executing')
        self.assertEqual(self.driver.calls,[])

    def test_request_intent_without_bound_operation_is_never_guessed(self):
        self.configured();request=self.request('prepare')
        self.audit.begin({'action':'submit','request_id':request['request_id'],
            'parameters':{'instance_uuid':self.instance,'request':request}},'alice')
        with patch('ctflab_audit_review.LocalService',side_effect=AssertionError('must not query')):
            row=AuditReview(self.policy_path).read()['pending'][0]
        self.assertEqual(row['observation'],'not-linked');self.assertIsNone(row['operation_id'])

    def test_revoked_scope_never_opens_instance_and_never_leaks_path(self):
        self.completed_pending();self.policy['principals']['alice']['instances']=[];self.write_policy()
        with patch('ctflab_audit_review.LocalService',side_effect=AssertionError('must not query')):
            report=AuditReview(self.policy_path).read()
        self.assertEqual(report['pending'][0]['observation'],'scope-unavailable')
        self.assertNotIn(str(self.root),canonical(report))

    def test_policy_change_and_profile_change_are_not_silently_correlated(self):
        self.completed_pending();policy=copy.deepcopy(self.policy)
        self.policy['principals']['alice']['expires']='2098-01-01T00:00:00Z';self.write_policy()
        self.assertEqual(AuditReview(self.policy_path).read()['pending'][0]['observation'],'policy-changed')
        self.policy=policy;self.write_policy();(self.store.root/'runtime-profile.json').write_text('{"private":"secret"}')
        report=AuditReview(self.policy_path).read();self.assertEqual(report['pending'][0]['observation'],'identity-conflict')
        self.assertNotIn('secret',canonical(report))

    def test_wrong_permit_actor_or_request_digest_refuses_correlation(self):
        self.completed_pending();path=self.jobs[-1];original=path.read_text();permit=json.loads(original)
        permit['principal']='teacher';path.write_text(canonical(permit))
        self.assertEqual(AuditReview(self.policy_path).read()['pending'][0]['observation'],'identity-conflict')
        path.write_text(original)
        with self.service._transaction() as db:db.execute("UPDATE operations SET digest=?",('0'*64,))
        self.assertEqual(AuditReview(self.policy_path).read()['pending'][0]['observation'],'identity-conflict')

    def test_wrong_terminal_operation_instance_and_raw_error_are_not_exported(self):
        accepted=self.completed_pending()
        with self.service._transaction() as db:
            row=db.execute('SELECT response FROM operations WHERE id=?',(accepted['operation_id'],)).fetchone()
            response=json.loads(row[0]);response['operation_id']='secret';response['error']={'code':'secret','message':'/secret'}
            db.execute('UPDATE operations SET response=? WHERE id=?',(canonical(response),accepted['operation_id']))
        report=AuditReview(self.policy_path).read();self.assertEqual(report['pending'][0]['observation'],'identity-conflict')
        self.assertNotIn('secret',canonical(report))

    def test_missing_contract_is_distinguished_from_missing_file_without_creating_it(self):
        accepted=self.completed_pending()
        with self.service._transaction() as db:db.execute('DELETE FROM operations WHERE id=?',(accepted['operation_id'],))
        self.assertEqual(AuditReview(self.policy_path).read()['pending'][0]['observation'],'contract-missing')
        database=self.service.database;database.rename(database.with_suffix('.preserved'))
        report=AuditReview(self.policy_path).read();self.assertEqual(report['pending'][0]['observation'],'unavailable')
        self.assertFalse(database.exists())

    def test_generation_and_ledger_file_replacement_are_not_old_pid_evidence(self):
        self.completed_pending();ledger=self.store.root/'ledger.sqlite3';raw=ledger.read_bytes()
        ledger.rename(ledger.with_suffix('.preserved'));ledger.write_bytes(raw);ledger.chmod(0o600)
        self.assertEqual(AuditReview(self.policy_path).read()['pending'][0]['observation'],'identity-conflict')
        self.assertFalse(any(call[0]=='stop' for call in self.driver.calls))

    def test_pagination_checkpoint_and_completed_attempts_exclusion(self):
        self.configured();accepted=self.submitted();one=self.intent(accepted);two=self.intent(accepted)
        self.audit.finish(self.audit.begin({},'alice'))
        review=AuditReview(self.policy_path);first=review.read(limit=1)
        checkpoint={'seq':first['audit_head_seq'],'sha256':first['audit_head_sha256']}
        second=review.read(after=first['next_intent'],limit=1,checkpoint=checkpoint)
        self.assertEqual(first['pending_count'],2);self.assertTrue(first['more']);self.assertFalse(second['more'])
        self.assertEqual([first['pending'][0]['attempt_id'],second['pending'][0]['attempt_id']],[one,two])
        self.assertTrue(second['checkpoint_verified'])
        with self.assertRaises(ContractError):review.read(checkpoint=dict(checkpoint,sha256='f'*64))
        for kwargs in ({'after':True},{'limit':0},{'after':-1}):
            with self.assertRaises(ContractError):review.read(**kwargs)

    def test_corrupt_audit_aborts_report_and_read_transactions_reject_writes(self):
        self.completed_pending()
        with self.audit.transaction() as db:
            with self.assertRaises(sqlite3.OperationalError):db.execute('DELETE FROM events')
        with readonly(self.store.root/'ledger.sqlite3') as db:
            with self.assertRaises(sqlite3.OperationalError):db.execute('DELETE FROM metadata')
        with self.audit.transaction(write=True) as db:db.execute("UPDATE events SET payload='{}' WHERE seq=1")
        with self.assertRaises(ContractError):AuditReview(self.policy_path).read()

    def test_policy_drift_during_observation_aborts_old_scope_report(self):
        self.completed_pending();review=AuditReview(self.policy_path);original=review.observation
        def changed(intent):
            value=original(intent);self.policy['principals']['alice']['instances']=[];self.write_policy();return value
        with patch.object(review,'observation',side_effect=changed):
            with self.assertRaises(ContractError):review.read()

    def test_independent_cli_is_readonly_and_does_not_expose_private_paths(self):
        self.completed_pending();before=self.hashes()
        script=Path(__file__).resolve().parents[1]/'ctflab_audit_review.py'
        result=subprocess.run([sys.executable,'-I','-B',str(script),'--policy',str(self.policy_path),'--limit','1'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertNotIn(str(self.root),result.stdout)
        self.assertEqual(json.loads(result.stdout)['pending'][0]['observation'],'contract-recorded')
        self.assertEqual(self.hashes(),before)

    def test_initial_policy_read_drift_is_rejected_before_instance_access(self):
        self.completed_pending()
        from ctflab_remote import private_json
        def drift(path):
            value=private_json(path);self.policy['principals']['alice']['instances']=[];self.write_policy();return value
        with patch('ctflab_audit_review.private_json',side_effect=drift):
            with self.assertRaises(ContractError):AuditReview(self.policy_path)

    def test_instance_binding_change_during_contract_read_cannot_be_reported_as_recorded(self):
        self.completed_pending()
        from contextlib import contextmanager
        from ctflab_local_service import LocalService
        original=LocalService._read
        @contextmanager
        def changed(service):
            with original(service) as db:yield db
            (self.store.root/'runtime-profile.json').write_text('{"changed":true}')
        with patch.object(LocalService,'_read',new=changed):
            report=AuditReview(self.policy_path).read()
        self.assertEqual(report['pending'][0]['observation'],'identity-conflict')


if __name__=='__main__':unittest.main()
