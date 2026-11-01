"""远程审计的实际SQLite/权限门与故障；不连接SSH或调用真实VM。"""
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_ctflab_remote as remote_tests
from ctflab_contract import ContractError,canonical
from ctflab_remote import Runner,validate_policy
from ctflab_remote_audit import AuditStore,summary,ZERO


class AuditTests(unittest.TestCase):
    setUp=remote_tests.RemoteTests.setUp
    setup_runner=remote_tests.RemoteTests.setup_runner
    request=remote_tests.RemoteTests.request
    submit=remote_tests.RemoteTests.submit

    def configured(self,principal='alice',capacity=10):
        self.setup_runner(principal)
        self.policy['audit']={'root':str(self.root/'audit'),'max_attempts':capacity}
        self.audit=AuditStore.create(self.policy['audit'],self.server)
        self.runner=Runner(self.policy,principal,dispatch=lambda root,payload:self.dispatched(payload))
    def dispatched(self,payload):
        self.calls.append(payload)
        self.assertEqual(len(self.audit.read()['pending']),1)
        return {'state':'fixture','operation_id':str(uuid.uuid4()),'path':'/secret/host','token':'secret-response'}

    def test_intent_is_committed_before_dispatch_and_result_after(self):
        self.configured();response=self.runner.exchange(self.request())
        page=self.audit.read();self.assertEqual([r['phase'] for r in page['events']],['intent','result'])
        self.assertEqual(page['pending'],[]);self.assertTrue(page['chain_consistent'])
        self.assertFalse(page['externally_anchored']);self.assertFalse(page['guest_effect_verified'])
        self.assertEqual(page['events'][1]['payload']['operation_id'],response['result']['operation_id'])
        self.assertNotIn('secret',canonical(page));self.assertNotIn(str(self.root),canonical(page))

    def test_other_owner_denial_is_audited_without_dispatch(self):
        self.configured('bob')
        with self.assertRaises(ContractError):self.runner.exchange(self.request())
        events=self.audit.read()['events'];self.assertEqual(self.calls,[])
        self.assertEqual(events[0]['payload']['summary']['principal'],'bob')
        self.assertEqual(events[1]['payload']['code'],'permission-denied')
        self.assertEqual(events[1]['payload']['outcome'],'rejected')

    def test_malformed_messages_never_persist_supplied_paths_or_contents(self):
        self.configured()
        for value in (None,{'action':['secret'],'request_id':'secret','parameters':{'instance_uuid':'/secret'}},
                      self.request('shell',{'root':'/secret','password':'secret'})):
            with self.assertRaises((ContractError,TypeError)):self.runner.exchange(value)
        text=canonical(self.audit.read());self.assertNotIn('secret',text);self.assertEqual(self.calls,[])

    def test_upload_and_guest_payloads_are_reduced_to_identifiers(self):
        self.configured()
        for request in (self.request('asset-chunk',{'data':'secret','token':'secret'}),self.submit('guest')):
            try:self.runner.exchange(request)
            except ContractError:pass
        self.assertNotIn('secret',canonical(self.audit.read()))
        self.assertNotIn('parameters',canonical(self.audit.read()))

    def test_capacity_reserves_results_for_all_existing_pending_attempts(self):
        self.configured(capacity=2)
        one=self.audit.begin(self.request(),'alice');two=self.audit.begin(self.request(),'alice')
        with self.assertRaises(ContractError) as error:self.runner.exchange(self.request())
        self.assertEqual(error.exception.code,'storage-insufficient');self.assertEqual(self.calls,[])
        self.audit.finish(two);self.audit.finish(one)
        result=self.audit.read();self.assertEqual(result['head_seq'],4);self.assertEqual(result['pending'],[])

    def test_same_request_uuid_is_separate_audit_attempt_and_never_cached_response(self):
        self.configured();request=self.request('handshake',{})
        self.runner.exchange(request);self.runner.exchange(request)
        events=self.audit.read()['events'];self.assertNotEqual(events[0]['attempt_id'],events[2]['attempt_id'])
        self.assertEqual(events[0]['payload']['summary']['request_id'],events[2]['payload']['summary']['request_id'])
        self.assertEqual(self.calls,[])

    def test_failed_begin_prevents_effects_and_failed_finish_preserves_unknown(self):
        self.configured()
        with patch.object(AuditStore,'begin',side_effect=sqlite3.OperationalError('secret failure')):
            with self.assertRaises(ContractError) as error:self.runner.exchange(self.request())
        self.assertEqual(error.exception.code,'persistence-failed');self.assertEqual(self.calls,[])
        with patch.object(AuditStore,'finish',side_effect=OSError('secret failure')):
            with self.assertRaises(ContractError) as error:self.runner.exchange(self.request())
        self.assertEqual(error.exception.code,'persistence-failed');self.assertEqual(len(self.calls),1)
        page=self.audit.read();self.assertEqual(len(page['pending']),1);self.assertEqual(page['head_seq'],1)
        self.assertFalse(page['automatic_replay'])

    def test_action_exception_records_unknown_without_exception_text(self):
        self.configured()
        with patch.object(self.runner,'dispatch',side_effect=OSError('/secret/token')):
            with self.assertRaises(OSError):self.runner.exchange(self.request())
        result=self.audit.read();self.assertEqual(result['events'][1]['payload']['outcome'],'unknown')
        self.assertNotIn('secret',canonical(result));self.assertEqual(result['pending'],[])

    def test_crash_leaves_intent_readable_and_no_automatic_resolution(self):
        self.configured();attempt=self.audit.begin(self.request(),'alice')
        reopened=AuditStore(self.policy['audit'],self.server)
        self.assertEqual(reopened.read()['pending'],[attempt]);self.assertEqual(self.calls,[])
        self.audit.finish(attempt)
        with self.assertRaises(ContractError):self.audit.finish(attempt)

    def test_chain_edit_truncation_and_index_forgery_block_new_effects(self):
        for mutation in ("UPDATE events SET payload='{}' WHERE seq=1",'DELETE FROM events WHERE seq=2',
                         'UPDATE attempts SET completed=0'):
            with self.subTest(mutation=mutation):
                # 每个样本是独立账本，损坏保留到临时目录生命周期结束。
                self.setup_runner();self.policy['audit']={'root':str(self.root/str(uuid.uuid4())),'max_attempts':10}
                self.audit=AuditStore.create(self.policy['audit'],self.server)
                self.runner=Runner(self.policy,'alice',dispatch=lambda root,payload:self.dispatched(payload))
                self.runner.exchange(self.request());self.calls.clear()
                with self.audit.transaction(write=True) as db:db.execute(mutation)
                with self.assertRaises(ContractError):self.audit.read()
                with self.assertRaises(ContractError):self.runner.exchange(self.request())
                self.assertEqual(self.calls,[])

    def test_cross_connection_lock_never_enters_dispatch(self):
        self.configured()
        with self.audit.transaction(write=True):
            with self.assertRaises(ContractError) as error:self.runner.exchange(self.request())
        self.assertEqual(error.exception.code,'persistence-failed');self.assertEqual(self.calls,[])
        self.assertEqual(self.audit.read()['head_seq'],0)

    def test_paging_and_input_types_and_server_capacity_binding(self):
        self.configured();self.runner.exchange(self.request('handshake',{}))
        first=self.audit.read(limit=1);second=self.audit.read(after=first['next'],limit=1)
        self.assertEqual(first['events'][0]['previous'],ZERO)
        self.assertEqual(second['events'][0]['previous'],first['events'][0]['sha256'])
        for kwargs in ({'limit':True},{'after':-1},{'limit':101}):
            with self.assertRaises(ContractError):self.audit.read(**kwargs)
        for config,server in ((self.policy['audit'],str(uuid.uuid4())),(dict(self.policy['audit'],max_attempts=20),self.server)):
            with self.assertRaises(ContractError):AuditStore(config,server).read()

    def test_policy_overlap_and_missing_or_nonprivate_store_refuse_effects(self):
        self.configured()
        for root in (str(self.store.root),str(self.root/'missing'/'..'/'instance')):
            policy=copy.deepcopy(self.policy);policy['audit']['root']=root
            if root.endswith('/instance'):policy['instances'][self.instance]['root']=str(self.root/'instance')
            with self.assertRaises(ContractError):validate_policy(policy)
        self.policy['audit']['root']=str(self.root/'absent')
        with self.assertRaises(ContractError):Runner(self.policy,'alice').exchange(self.request())
        self.assertEqual(self.calls,[]);self.assertFalse((self.root/'absent').exists())
        self.policy['audit']['root']=str(self.audit.root);(self.audit.root/'audit.sqlite3').chmod(0o644)
        with self.assertRaises(ContractError):self.runner.exchange(self.request())
        self.assertEqual(self.calls,[])

    def test_saved_checkpoint_remains_valid_after_append_and_rejects_changed_prefix(self):
        self.configured();self.runner.exchange(self.request('handshake',{}))
        page=self.audit.read();checkpoint={'seq':page['head_seq'],'sha256':page['head_sha256']}
        self.runner.exchange(self.request('handshake',{}))
        self.assertTrue(self.audit.read(checkpoint=checkpoint)['checkpoint_verified'])
        for invalid in (dict(checkpoint,sha256='f'*64),dict(checkpoint,seq=100),dict(checkpoint,seq=True)):
            with self.assertRaises(ContractError):self.audit.read(checkpoint=invalid)

    def test_independent_cli_initializes_and_reads_without_dispatch_or_overwrite(self):
        self.setup_runner();self.policy['audit']={'root':str(self.root/'new-audit'),'max_attempts':10}
        policy=self.root/'policy.json';policy.write_text(canonical(self.policy));policy.chmod(0o600)
        script=Path(__file__).resolve().parents[1]/'ctflab_remote_audit.py'
        def run(action):return subprocess.run([sys.executable,'-I','-B',str(script),action,'--policy',str(policy)],capture_output=True,text=True)
        self.assertEqual(run('initialize').returncode,0);self.assertNotEqual(run('initialize').returncode,0)
        result=run('read');self.assertEqual(result.returncode,0);self.assertEqual(json.loads(result.stdout)['events'],[])
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
