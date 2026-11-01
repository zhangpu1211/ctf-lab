"""本地协议与恢复负测：临时数据库、合成后端，不启动 VM。"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab_contract as contract
from ctflab_local_service import LocalService, Observation, Outcome
from ctflab_windows_probe import FixtureBackend, request

ACTOR = 'test-user'


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.req = request(str(uuid.uuid4()), 'prepare', parameters={'course_id': 'course', 'baseline_id': 'base'})

    def test_strict_json_and_version(self):
        self.assertEqual(contract.parse_request(contract.canonical(self.req)), self.req)
        for text in ('{"version":1,"version":1}', '{"x":NaN}', '[]', '{', '\ud800', 'x'*65537):
            with self.subTest(text=text[:40]), self.assertRaises(contract.ContractError):
                contract.parse_request(text)
        for version in (True, 2, '1', None):
            with self.assertRaises(contract.ContractError):
                contract.validate_request(dict(self.req, version=version))

    def test_request_fields_and_parameters_are_allowlisted(self):
        mutations = [lambda r: r.update(actor='admin'), lambda r: r.update(qemu_args=['-netdev', 'user']),
                     lambda r: r['parameters'].update(path='/private/user/secret'),
                     lambda r: r['parameters'].update(course_id='../bad'),
                     lambda r: r.update(expected_generation=0), lambda r: r.update(instance_uuid='invalid'),
                     lambda r: r.update(operation=['start']), lambda r: r.update(idempotency_key='a\nb')]
        for mutate in mutations:
            req = copy.deepcopy(self.req); mutate(req)
            with self.assertRaises(contract.ContractError): contract.validate_request(req)
        for op, params in [('stop', {'force': True}), ('start', {'display':'console','allow_emulation':1}),
                           ('reset', {'baseline_id':'/outside'}), ('recover', {'pid':42})]:
            with self.assertRaises(contract.ContractError):
                contract.validate_request(request(self.req['instance_uuid'], op, parameters=params))

    def test_digest_excludes_only_request_id(self):
        retry = dict(self.req, request_id=str(uuid.uuid4()))
        self.assertEqual(contract.fingerprint(self.req), contract.fingerprint(retry))
        retry['parameters'] = {'course_id':'other','baseline_id':'base'}
        self.assertNotEqual(contract.fingerprint(self.req), contract.fingerprint(retry))

    def test_public_errors_do_not_accept_backend_text(self):
        error = contract.public_error('backend-failed', evidence_refs=['evidence-1'])
        self.assertTrue(error['preserved']); self.assertFalse(error['retryable'])
        with self.assertRaises(contract.ContractError): contract.public_error('/secret/password')
        with self.assertRaises(contract.ContractError): contract.public_error('backend-failed', evidence_refs=['/Users/private'])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve() / 'contract'
        self.service = LocalService.create(self.root)
        self.instance = str(uuid.uuid4()); self.backend = FixtureBackend()
        self.prep = request(self.instance, 'prepare', key='one', parameters={'course_id':'course','baseline_id':'base'})

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self):
        accepted = self.service.submit(self.prep, ACTOR)
        self.assertEqual(accepted['result'], 'accepted')
        return self.service.execute(accepted['operation_id'], ACTOR, self.backend)

    def next(self, op, state, **params):
        return request(self.instance, op, generation=state['generation'], revision=state['state_revision'], parameters=params)

    def test_durable_replay_precedes_stale_revision_and_ignores_request_id(self):
        done = self.prepare()
        start = self.next('start', done, display='headless', allow_emulation=False)
        accepted = self.service.submit(start, ACTOR)
        self.service.execute(accepted['operation_id'], ACTOR, self.backend)
        reopen = LocalService(self.root)
        retry = dict(start, request_id=str(uuid.uuid4()))
        response = reopen.submit(retry, ACTOR)
        self.assertEqual(response['result'], 'completed'); self.assertEqual(response['request_id'], retry['request_id'])
        self.assertEqual(self.backend.calls, ['prepare','start'])
        response2 = reopen.execute(accepted['operation_id'], ACTOR, self.backend)
        self.assertEqual(response2['operation_id'], response['operation_id'])
        self.assertEqual(len(self.backend.calls), 2)

    def test_key_reuse_for_different_parameters_or_instance_conflicts(self):
        self.prepare()
        for req in [dict(self.prep, instance_uuid=str(uuid.uuid4())),
                    dict(self.prep, parameters={'course_id':'different','baseline_id':'base'})]:
            response = self.service.submit(req, ACTOR)
            self.assertEqual(response['error']['code'], 'idempotency-conflict')

    def test_actor_is_external_and_cannot_access_or_replay_foreign_instance(self):
        self.prepare()
        for req in (self.prep, request(self.instance, 'status')):
            response = self.service.handle_json(contract.canonical(req), 'other-user')
            self.assertEqual(response['error']['code'], 'permission-denied')
        with self.assertRaises(contract.ContractError): self.service.events(self.instance, 'other-user')

    def test_generation_revision_conflicts_have_no_side_effect(self):
        done = self.prepare(); count = len(self.service.events(self.instance, ACTOR))
        for gen, rev in [(2, done['state_revision']), (1,0)]:
            response = self.service.submit(request(self.instance,'stop',generation=gen,revision=rev),ACTOR)
            self.assertEqual(response['error']['code'],'state-conflict')
        self.assertEqual(len(self.service.events(self.instance, ACTOR)),count)

    def test_reset_advances_generation_only_after_success(self):
        done=self.prepare()
        reset=self.service.submit(self.next('reset',done,baseline_id='base'),ACTOR)
        with mock.patch.object(self.backend,'execute',return_value=Outcome('recovery-required','reset-commit-failed')):
            failed=self.service.execute(reset['operation_id'],ACTOR,self.backend)
        self.assertEqual(failed['generation'],1)
        recover=self.service.submit(self.next('recover',failed),ACTOR)
        ready=self.service.execute(recover['operation_id'],ACTOR,self.backend)
        reset=self.service.submit(self.next('reset',ready,baseline_id='base'),ACTOR)
        done=self.service.execute(reset['operation_id'],ACTOR,self.backend)
        self.assertEqual(done['generation'],2)

    def test_evidence_reference_survives_retry_without_private_details(self):
        accepted=self.service.submit(self.prep,ACTOR)
        with mock.patch.object(self.backend,'execute',return_value=Outcome('prepared',evidence_refs=('probe-1',))):
            result=self.service.execute(accepted['operation_id'],ACTOR,self.backend)
        self.assertEqual(result['evidence_refs'],['probe-1'])
        self.assertEqual(self.service.submit(self.prep,ACTOR)['evidence_refs'],['probe-1'])

    def test_competing_threads_only_one_reservation_and_no_duplicate_backend(self):
        done = self.prepare(); barrier = threading.Barrier(2); results = []
        def submit():
            barrier.wait()
            results.append(self.service.submit(self.next('start',done,display='headless',allow_emulation=False),ACTOR))
        threads=[threading.Thread(target=submit) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(5); self.assertFalse(thread.is_alive())
        accepted=[x for x in results if x['result']=='accepted'];self.assertEqual(len(accepted),1)
        self.service.execute(accepted[0]['operation_id'],ACTOR,self.backend)
        self.assertEqual(self.backend.calls,['prepare','start'])

    def test_readonly_status_and_events_do_not_write(self):
        self.prepare()
        def snapshot():
            return {p.name:(p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest()) for p in self.root.iterdir()}
        before=snapshot()
        self.service.status(request(self.instance,'status'),ACTOR)
        self.service.events(self.instance,ACTOR)
        self.assertEqual(snapshot(),before)

    def test_intent_failure_prevents_backend_and_instance_creation(self):
        with mock.patch.object(self.service,'_event',side_effect=sqlite3.OperationalError('fixture failure')):
            result=self.service.submit(self.prep,ACTOR)
        self.assertEqual(result['error']['code'],'persistence-failed')
        self.assertEqual(self.backend.calls,[])
        self.assertIsNone(self.service.status(request(self.instance,'status'),ACTOR)['generation'])

    def test_commit_failure_preserves_intent_and_requires_explicit_recovery(self):
        accepted=self.service.submit(self.prep,ACTOR)
        original=self.service._event
        def fail_final(db, instance, op, stage):
            if stage=='completed': raise sqlite3.OperationalError('fixture disk full')
            return original(db,instance,op,stage)
        with mock.patch.object(self.service,'_event',side_effect=fail_final):
            result=self.service.execute(accepted['operation_id'],ACTOR,self.backend)
        self.assertEqual(result['result'],'unknown'); self.assertEqual(self.backend.calls,['prepare'])
        self.service=LocalService(self.root)
        replay=self.service.submit(self.prep,ACTOR)
        self.assertEqual(replay['result'],'unknown')
        with self.assertRaises(contract.ContractError): self.service.execute(accepted['operation_id'],ACTOR,self.backend)
        status=self.service.status(request(self.instance,'status'),ACTOR)
        self.assertEqual(status['state'],'recovery-required')
        accepted_recover=self.service.submit(self.next('recover',status),ACTOR)
        result=self.service.execute(accepted_recover['operation_id'],ACTOR,self.backend)
        self.assertEqual(result['state'],'prepared')
        self.assertEqual(self.backend.calls,['prepare','recover'])

    def test_process_restart_after_backend_side_effect_does_not_repeat(self):
        accepted=self.service.submit(self.prep,ACTOR)
        marker=self.root/'synthetic-marker'
        script='''
import sys, os
sys.path.insert(0, sys.argv[1])
from ctflab_local_service import LocalService
class Backend:
 def execute(self, req, ctx):
  open(sys.argv[4], 'w').write('fixture-created')
  os._exit(23)
LocalService(sys.argv[2]).execute(sys.argv[3], 'test-user', Backend())
'''
        result=subprocess.run([sys.executable,'-I','-c',script,str(Path(__file__).resolve().parents[1]),
                               str(self.root),accepted['operation_id'],str(marker)],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,23);self.assertTrue(marker.is_file())
        reopened=LocalService(self.root)
        self.assertEqual(reopened.submit(self.prep,ACTOR)['result'],'unknown')
        status=reopened.status(request(self.instance,'status'),ACTOR)
        recover=reopened.submit(self.next('recover',status),ACTOR)
        self.assertEqual(recover['result'],'accepted')
        self.assertEqual(reopened.execute(recover['operation_id'],ACTOR,self.backend)['state'],'prepared')

    def test_unknown_identity_never_calls_destructive_backend(self):
        done=self.prepare()
        for identity in ('unknown','mismatch'):
            accepted=self.service.submit(self.next('stop',done),ACTOR)
            with mock.patch.object(self.backend,'observe',return_value=Observation(identity,1,'prepared')):
                result=self.service.execute(accepted['operation_id'],ACTOR,self.backend)
            self.assertEqual(result['error']['code'],'identity-unknown')
            self.assertEqual(self.backend.calls,['prepare'])
            # 下一轮重新建立独立实例，不从失败状态跳过恢复。
            if identity=='unknown':
                self.instance=str(uuid.uuid4());self.prep=request(self.instance,'prepare',parameters={'course_id':'c','baseline_id':'b'})
                done=self.prepare();self.backend.calls=['prepare']

    def test_normal_stop_timeout_does_not_claim_stopped(self):
        done=self.prepare();start=self.service.submit(self.next('start',done,display='headless',allow_emulation=False),ACTOR)
        running=self.service.execute(start['operation_id'],ACTOR,self.backend)
        stop=self.service.submit(self.next('stop',running),ACTOR)
        with mock.patch.object(self.backend,'execute',return_value=Outcome('recovery-required','stop-timeout')):
            result=self.service.execute(stop['operation_id'],ACTOR,self.backend)
        self.assertEqual(result['error']['code'],'stop-timeout');self.assertNotEqual(result['state'],'stopped')
        self.assertTrue(result['error']['preserved'])

    def test_pending_cancel_does_not_call_backend(self):
        accepted=self.service.submit(self.prep,ACTOR)
        cancel=self.next('cancel',accepted,operation_id=accepted['operation_id'])
        self.assertEqual(self.service.submit(cancel,ACTOR)['result'],'completed')
        result=self.service.execute(accepted['operation_id'],ACTOR,self.backend)
        self.assertTrue(result['cancelled']);self.assertEqual(self.backend.calls,[])

    def test_cancel_during_execute_and_recovery_cannot_race_worker(self):
        done=self.prepare();entered=threading.Event();release=threading.Event();results=[]
        accepted=self.service.submit(self.next('start',done,display='headless',allow_emulation=False),ACTOR)
        def execute(req,ctx):
            entered.set();self.assertTrue(release.wait(5))
            return Outcome('stopped',cancelled=ctx.cancel_requested())
        with mock.patch.object(self.backend,'execute',side_effect=execute):
            thread=threading.Thread(target=lambda:results.append(self.service.execute(accepted['operation_id'],ACTOR,self.backend)))
            thread.start();self.assertTrue(entered.wait(5))
            status=self.service.status(request(self.instance,'status'),ACTOR)
            blocked=self.service.submit(self.next('recover',status),ACTOR)
            self.assertEqual(blocked['error']['code'],'resource-busy')
            cancel=self.service.submit(self.next('cancel',status,operation_id=accepted['operation_id']),ACTOR)
            self.assertEqual(cancel['result'],'completed')
            release.set();thread.join(5);self.assertFalse(thread.is_alive())
        self.assertTrue(results[0]['cancelled'])
        late=self.service.submit(self.next('cancel',results[0],operation_id=accepted['operation_id']),ACTOR)
        self.assertEqual(late['error']['code'],'operation-finished')

    def test_worker_mutex_is_shared_across_processes(self):
        done=self.prepare()
        script='''
import sqlite3, sys
db=sqlite3.connect(sys.argv[1], isolation_level=None)
db.execute('BEGIN IMMEDIATE')
print('locked', flush=True)
sys.stdin.readline()
db.rollback()
db.close()
'''
        with subprocess.Popen([sys.executable,'-I','-c',script,str(self.service.worker)],
                              stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) as child:
            try:
                self.assertEqual(child.stdout.readline().strip(),'locked')
                result=self.service.submit(self.next('recover',done),ACTOR)
                self.assertEqual(result['error']['code'],'resource-busy')
            finally:
                child.communicate('\n',timeout=5)
        self.assertEqual(child.returncode,0)

    def test_cancel_requested_but_commit_won_is_not_reported_cancelled(self):
        done=self.prepare();accepted=self.service.submit(self.next('start',done,display='headless',allow_emulation=False),ACTOR)
        def execute(req,ctx):
            state=self.service.status(request(self.instance,'status'),ACTOR)
            self.service.submit(self.next('cancel',state,operation_id=ctx.operation_id),ACTOR)
            return Outcome('process-running')
        with mock.patch.object(self.backend,'execute',side_effect=execute):
            result=self.service.execute(accepted['operation_id'],ACTOR,self.backend)
        self.assertFalse(result['cancelled']);self.assertEqual(result['state'],'process-running')

    def test_backend_exception_and_invalid_evidence_are_sanitized(self):
        accepted=self.service.submit(self.prep,ACTOR)
        with mock.patch.object(self.backend,'execute',side_effect=RuntimeError('/Users/private token=secret')):
            result=self.service.execute(accepted['operation_id'],ACTOR,self.backend)
        self.assertNotIn('secret',json.dumps(result));self.assertNotIn('/Users',json.dumps(result))
        self.assertEqual(result['error']['code'],'backend-failed')
        recovery=self.service.submit(self.next('recover',result),ACTOR)
        with mock.patch.object(self.backend,'execute',return_value=Outcome('prepared',evidence_refs=('/Users/private',))):
            response=self.service.execute(recovery['operation_id'],ACTOR,self.backend)
        self.assertNotIn('/Users',json.dumps(response));self.assertEqual(response['result'],'failed')

    def test_events_replay_duplicate_gap_mixed_stream_and_expiration(self):
        self.prepare();events=self.service.events(self.instance,ACTOR)
        cursor,fresh=contract.merge_events(0,events+[events[-1]])
        self.assertEqual(cursor,len(events));self.assertEqual(len(fresh),len(events))
        with self.assertRaises(contract.ContractError):contract.merge_events(0,events[1:])
        mixed=copy.deepcopy(events);mixed[-1]['instance_uuid']=str(uuid.uuid4())
        with self.assertRaises(contract.ContractError):contract.merge_events(0,mixed)
        self.service.prune_events(self.instance,ACTOR,through=1)
        with self.assertRaises(contract.ContractError) as raised:self.service.events(self.instance,ACTOR,after=0)
        self.assertEqual(raised.exception.code,'cursor-expired')
        self.assertEqual(self.service.events(self.instance,ACTOR,after=1),events[1:])
        self.assertEqual(self.service.submit(self.prep,ACTOR)['result'],'completed')

    def test_duplicate_event_identity_for_different_sequence_rejected(self):
        self.prepare();events=self.service.events(self.instance,ACTOR)
        events[-1]['event_id']=events[0]['event_id']
        with self.assertRaises(contract.ContractError):contract.merge_events(0,events)

    def test_json_adapter_matches_typed_adapter_and_rejects_hidden_identity(self):
        typed=self.service.submit(self.prep,ACTOR)
        encoded=self.service.handle_json(contract.canonical(self.prep),ACTOR)
        self.assertEqual(typed,encoded)
        encoded=self.service.handle_json(contract.canonical(dict(self.prep,actor='admin')),ACTOR)
        self.assertEqual(encoded['error']['code'],'invalid-request')
        self.assertIsNone(encoded['request_id'])

    def test_state_root_must_be_new_private_and_not_linked(self):
        with self.assertRaises(FileExistsError):LocalService.create(self.root)
        linked=Path(self.temp.name).resolve()/'linked';linked.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(contract.ContractError):LocalService(linked)
        if os.name=='posix':
            os.chmod(self.root,0o755)
            with self.assertRaises(contract.ContractError):LocalService(self.root)
            os.chmod(self.root,0o700)


if __name__=='__main__':unittest.main()
