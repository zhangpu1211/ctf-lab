"""原操作账本的重开、只读、身份和未知边界；只用自有临时库/合成后端。"""
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab_local_adapter as adapter
import ctflab_desktop_bridge as bridge
import ctflab_desktop_remote as remote
from ctflab_contract import canonical, ContractError
from ctflab_local_service import LocalService
from ctflab_windows_probe import FixtureBackend, request


class HistoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()/'contract'
        self.service = LocalService.create(self.root)
        self.instance = str(uuid.uuid4()); self.actor = adapter.process_actor()
        self.backend = FixtureBackend()
        self.req = request(self.instance, 'prepare', parameters={'course_id':'course','baseline_id':'base'})
        self.accepted = self.service.submit(self.req, self.actor)
        self.op = self.accepted['operation_id']

    def saved(self):
        return self.service.operation_result(self.instance, self.op, self.actor)

    def update(self, **fields):
        with sqlite3.connect(self.root/'contract.sqlite3') as db:
            db.execute('UPDATE operations SET '+','.join(key+'=?' for key in fields)+' WHERE id=?', (*fields.values(), self.op))

    def test_reopen_preserves_original_after_later_generation_and_event_prune(self):
        original = self.service.execute(self.op, self.actor, self.backend)
        reset = request(self.instance, 'reset', generation=original['generation'], revision=original['state_revision'], parameters={'baseline_id':'base'})
        accepted = self.service.submit(reset, self.actor)
        later = self.service.execute(accepted['operation_id'], self.actor, self.backend)
        self.assertEqual(later['generation'], 2)
        self.service.prune_events(self.instance, self.actor, through=later['cursor'])
        before = (self.root/'contract.sqlite3').read_bytes()
        reopen = LocalService(self.root)
        result = reopen.operation_result(self.instance, self.op, self.actor)
        self.assertEqual(result['response'], original)
        self.assertTrue(result['historical']); self.assertFalse(result['current_runtime_verified'])
        self.assertFalse(result['automatic_replay'])
        history = reopen.operation_history(self.instance, self.actor)
        self.assertEqual(len(history['operations']), 2)
        self.assertEqual(set(history['operations'][0]), {'operation_id','request_id','operation','expected_generation','status','response_recorded','cancel_requested'})
        self.assertEqual(before, (self.root/'contract.sqlite3').read_bytes())
        self.assertEqual(self.backend.calls, ['prepare','reset'])

    def test_pending_and_executing_never_fabricate_response(self):
        for status in ('pending','executing','unknown'):
            self.update(status=status)
            result = self.saved()
            self.assertIsNone(result['response']); self.assertFalse(result['record']['response_recorded'])
            self.assertEqual(result['record']['status'], status)
        self.assertEqual(self.backend.calls, [])

    def test_cursor_pagination_remains_bound_and_includes_max_rowid(self):
        with sqlite3.connect(self.root/'contract.sqlite3') as db:
            db.execute('UPDATE operations SET rowid=? WHERE id=?', (2**63-1, self.op))
        first = self.service.operation_history(self.instance,self.actor,limit=1)
        self.assertEqual(first['operations'][0]['operation_id'],self.op)
        self.assertFalse(first['truncated'])
        cancel = request(self.instance,'cancel',generation=1,revision=self.accepted['state_revision'],parameters={'operation_id':self.op})
        second = self.service.submit(cancel,self.actor)
        # SQLite在最大rowid已占用时为新行分配其他正整数；列表仍按其持久顺序分页。
        page = self.service.operation_history(self.instance,self.actor,limit=1)
        self.assertTrue(page['truncated']); self.assertEqual(page['next_before'], self.op)
        older = self.service.operation_history(self.instance,self.actor,limit=1,before=page['next_before'])
        self.assertEqual(older['operations'][0]['operation_id'],second['operation_id'])
        self.assertFalse(older['truncated'])

    def test_cancel_original_query_and_saved_result_are_readonly(self):
        cancel = request(self.instance,'cancel',generation=1,revision=self.accepted['state_revision'],parameters={'operation_id':self.op})
        reply = self.service.submit(cancel,self.actor)
        before = (self.root/'contract.sqlite3').read_bytes()
        self.assertEqual(self.service.query_request(cancel,self.actor)['response'],reply)
        self.assertEqual(self.service.operation_result(self.instance,reply['operation_id'],self.actor)['response'],reply)
        self.assertTrue(self.saved()['record']['cancel_requested'])
        self.assertEqual(before,(self.root/'contract.sqlite3').read_bytes())

    def test_actor_instance_and_cursor_scope_cannot_be_substituted(self):
        for call in (lambda:self.service.operation_history(self.instance,'other-user'),
                     lambda:self.service.operation_result(self.instance,self.op,'other-user'),
                     lambda:self.service.operation_result(str(uuid.uuid4()),self.op,self.actor),
                     lambda:self.service.operation_history(str(uuid.uuid4()),self.actor,before=self.op),
                     lambda:self.service.operation_history(self.instance,self.actor,before=str(uuid.uuid4()))):
            with self.assertRaises(ContractError):call()
        self.assertEqual(self.service.operation_history(str(uuid.uuid4()),self.actor)['operations'],[])

    def test_limits_are_strict(self):
        for limit in (True,0,-1,51,1.5,'20'):
            with self.subTest(limit=limit), self.assertRaises(ContractError):
                self.service.operation_history(self.instance,self.actor,limit=limit)

    def test_primary_cli_history_and_original_result_are_readonly_after_reopen(self):
        before = (self.root/'contract.sqlite3').read_bytes()
        command = [sys.executable, str(Path(__file__).resolve().parents[1]/'ctflab.py'),
                   'local-contract', '--root', str(self.root), '--history', self.instance]
        for extra in (['--limit', '1'], ['--operation', self.op]):
            result = subprocess.run(command+extra, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr+result.stdout)
            reply = json.loads(result.stdout)
            self.assertTrue(reply['historical']); self.assertFalse(reply['automatic_replay'])
            if extra[0] == '--operation':
                self.assertEqual(reply['record']['status'], 'pending')
                self.assertIsNone(reply['response'])
            else:
                self.assertEqual(reply['operations'][0]['operation_id'], self.op)
            self.assertEqual(before, (self.root/'contract.sqlite3').read_bytes())
        self.assertEqual(self.backend.calls, [])

    def test_corrupt_saved_bindings_fail_closed_without_repair(self):
        original = self.service.execute(self.op,self.actor,self.backend)
        cases = [{'digest':'0'*64},{'idem':'wrong'}, {'response':None},
                 {'response':canonical(dict(original,instance_uuid=str(uuid.uuid4())))},
                 {'response':canonical(dict(original,request_id=str(uuid.uuid4())))},
                 {'response':canonical(dict(original,extra='private'))},
                 {'response':canonical(dict(original,error={'code':'backend-failed','message':'private'}))},
                 {'response':canonical(dict(original,result='accepted'))}]
        for changes in cases:
            self.update(digest=__import__('ctflab_contract').fingerprint(self.req),idem=self.req['idempotency_key'],response=canonical(original))
            self.update(**changes); before=(self.root/'contract.sqlite3').read_bytes()
            with self.subTest(changes=changes),self.assertRaises(ContractError):self.saved()
            self.assertEqual(before,(self.root/'contract.sqlite3').read_bytes())

    def test_lost_reply_after_commit_is_unknown_and_recoverable(self):
        a = adapter.LocalAdapter(self.root,backend=self.backend)
        second = request(str(uuid.uuid4()),'prepare',parameters={'course_id':'course','baseline_id':'base'})
        real = a.service.submit
        def lost(req,actor):
            real(req,actor); raise OSError('private path must not escape')
        with mock.patch.object(a.service,'submit',side_effect=lost):reply=a.dispatch(canonical(second))
        self.assertEqual(reply['result'],'unknown')
        self.assertNotIn('private path',canonical(reply))
        history=a.history(second['instance_uuid'])
        self.assertEqual(len(history['operations']),1)
        self.assertIsNone(a.history(second['instance_uuid'],operation_id=history['operations'][0]['operation_id'])['response'])
        self.assertEqual(self.backend.calls,[])

    def test_actual_isolated_cli_reads_saved_records_without_backend_or_writes(self):
        original=self.service.execute(self.op,self.actor,self.backend)
        before=(self.root/'contract.sqlite3').read_bytes()
        with tempfile.TemporaryDirectory() as unrelated:
            for extra in ([],['--operation',self.op]):
                proc=subprocess.run([sys.executable,'-I','-B',adapter.__file__,'--root',str(self.root),'--history',self.instance,*extra],cwd=unrelated,capture_output=True,text=True,timeout=10)
                self.assertEqual(proc.returncode,0,proc.stderr)
                value=json.loads(proc.stdout);self.assertFalse(value['automatic_replay'])
                if extra:self.assertEqual(value['response'],original)
                self.assertNotIn(str(self.root),proc.stdout)
        self.assertEqual(before,(self.root/'contract.sqlite3').read_bytes())

    def test_adapter_history_rechecks_process_actor(self):
        a=adapter.LocalAdapter(self.root)
        with mock.patch.object(adapter,'process_actor',return_value='other-user'):
            self.assertEqual(a.history(self.instance)['error']['code'],'permission-denied')


class BridgeHistoryTests(unittest.TestCase):
    def setUp(self):
        from test_ctflab_generation_store import GenerationTests
        from test_ctflab_desktop_bridge import BridgeTests
        GenerationTests.setUp(self);BridgeTests.connect(self)
        self.actor=adapter.process_actor();self.service=LocalService(self.root/'desktop-contract')
        self.req=request(self.instance,'prepare',parameters={'course_id':'c01','baseline_id':'base'})
        self.accepted=self.service.submit(self.req,self.actor)

    def test_read_actions_do_not_create_backend_or_spawn(self):
        before=(self.root/'desktop-contract/contract.sqlite3').read_bytes()
        spawn=mock.Mock();backend=mock.Mock()
        for payload in ({'action':'operation-history','limit':20},{'action':'operation-result','operation_id':self.accepted['operation_id']}):
            reply=bridge.dispatch(self.root,payload,spawn=spawn,make_backend=backend)
            self.assertTrue(reply['historical']);self.assertFalse(reply['automatic_replay'])
        spawn.assert_not_called();backend.assert_not_called()
        self.assertEqual(before,(self.root/'desktop-contract/contract.sqlite3').read_bytes())

    def test_read_actions_reject_caller_scope_and_extra_fields(self):
        for value in ({'action':'operation-history','limit':20,'actor':'other'},
                      {'action':'operation-result','operation_id':self.accepted['operation_id'],'instance_uuid':str(uuid.uuid4())},
                      {'action':'operation-history','limit':20,'command':'start'}):
            with self.assertRaises(ContractError):bridge.dispatch(self.root,value)

    def test_bridge_lost_submit_response_reports_unknown_and_original_is_saved(self):
        prepared=self.service.execute(self.accepted['operation_id'],self.actor,self.backend)
        start=request(self.instance,'start',generation=1,revision=prepared['state_revision'],parameters={'display':'headless','allow_emulation':False})
        real=bridge.dispatch
        def lost(root,value):
            real(root,value,spawn=lambda *a,**kw:None,make_backend=mock.Mock());raise OSError('private')
        payload={'action':'submit','request':start}
        output=io.StringIO()
        with mock.patch.object(bridge,'dispatch',side_effect=lost),mock.patch.object(bridge.sys,'stdin',mock.Mock(buffer=io.BytesIO(canonical(payload).encode()))),mock.patch('sys.stdout',output):
            self.assertEqual(bridge.main(['bridge','--run',str(self.root)]),2)
        self.assertEqual(json.loads(output.getvalue())['result'],'unknown')
        records=self.service.operation_history(self.instance,self.actor)['operations']
        self.assertEqual(records[0]['request_id'],start['request_id'])
        self.assertIsNone(self.service.operation_result(self.instance,records[0]['operation_id'],self.actor)['response'])

    def test_invalid_bridge_wire_is_known_invalid_request(self):
        output=io.StringIO()
        with mock.patch.object(bridge.sys,'stdin',mock.Mock(buffer=io.BytesIO(b'\xff'))),mock.patch('sys.stdout',output),mock.patch.object(bridge,'dispatch') as dispatch:
            self.assertEqual(bridge.main(['bridge','--run',str(self.root)]),2)
        dispatch.assert_not_called();value=json.loads(output.getvalue())
        self.assertEqual(value['result'],'failed');self.assertEqual(value['error']['code'],'invalid-request')

    def test_remote_transport_error_is_unknown_without_ssh_replay(self):
        output=io.StringIO()
        with mock.patch.object(remote,'dispatch',side_effect=OSError('private')),mock.patch.object(remote.sys,'stdin',mock.Mock(buffer=io.BytesIO(b'{}'))),mock.patch('sys.stdout',output):
            self.assertEqual(remote.main(['--config',str(self.root/'unused')]),2)
        value=json.loads(output.getvalue());self.assertEqual(value['result'],'unknown');self.assertFalse(value['automatic_replay'])
