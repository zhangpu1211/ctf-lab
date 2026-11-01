"""桌面契约到协调器的来宾操作；保留CAS/幂等/取消和未知结果。"""
import copy
from pathlib import Path
import sys
import unittest
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_ctflab_generation_store as generation_tests
from ctflab_contract import validate_request,ContractError
from ctflab_local_service import LocalService
from ctflab_local_adapter import process_actor


class GuestContractTests(unittest.TestCase):
    setUp=generation_tests.GenerationTests.setUp
    context=generation_tests.GenerationTests.context
    run_action=generation_tests.GenerationTests.run_action
    def prepare_service(self):
        self.service=LocalService.create(self.root/'contract');self.actor=process_actor()
        self.calls=[];self.response={'state':'containers-running','service_verified':False}
        def guest(plan,node,paths,action,operation):self.calls.append((node,action,operation));return self.response
        self.driver.guest_command=guest
        for action in ('prepare','start'):
            req=self.request(action)
            accepted=self.service.submit(req,self.actor)
            self.service.execute(accepted['operation_id'],self.actor,self.backend)
    def request(self,action,guest_action='containers-start'):
        base={'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),'operation':'status','instance_uuid':self.instance}
        if action=='status':return base
        status=self.service.status(base,self.actor)
        params={'prepare':{'course_id':'c01','baseline_id':'base'},'start':{'display':'headless','allow_emulation':False},
                'guest':{'node':'middle','action':guest_action},'stop':{},'cancel':{'operation_id':status['operation_id']}}[action]
        return dict(base,operation=action,expected_generation=None if action=='prepare' else status['generation'],
                    expected_state_revision=None if action=='prepare' else status['state_revision'],
                    idempotency_key=str(uuid.uuid4()),parameters=params)
    def test_guest_operation_executes_once_with_unchanged_generation(self):
        self.prepare_service();req=self.request('guest');accepted=self.service.submit(req,self.actor)
        result=self.service.execute(accepted['operation_id'],self.actor,self.backend)
        self.assertEqual(result['state'],'process-running');self.assertEqual(result['generation'],1)
        self.assertEqual(self.service.submit(req,self.actor)['operation_id'],accepted['operation_id'])
        self.assertEqual(len(self.calls),1)
        self.assertEqual(result['evidence_refs'],['guest-'+accepted['operation_id']])
    def test_unknown_guest_outcome_preserves_recovery_required(self):
        self.prepare_service();self.response={'state':'unknown','automatic_replay':False}
        accepted=self.service.submit(self.request('guest'),self.actor)
        result=self.service.execute(accepted['operation_id'],self.actor,self.backend)
        self.assertEqual(result['state'],'recovery-required');self.assertEqual(len(self.calls),1)
    def test_cancel_before_guest_effect_preserves_running_vm(self):
        self.prepare_service();accepted=self.service.submit(self.request('guest'),self.actor)
        self.service.submit(self.request('cancel'),self.actor)
        result=self.service.execute(accepted['operation_id'],self.actor,self.backend)
        self.assertTrue(result['cancelled']);self.assertEqual(result['state'],'process-running');self.assertEqual(self.calls,[])
    def test_shell_parameters_or_stale_revision_rejected(self):
        self.prepare_service();req=self.request('guest');req['parameters']['command']='anything'
        with self.assertRaises(ContractError):validate_request(req)
        req=self.request('guest');req['expected_state_revision']-=1
        self.assertEqual(self.service.submit(req,self.actor)['result'],'conflict')
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
