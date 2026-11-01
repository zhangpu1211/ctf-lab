"""真实消息/临时账本到宿主幂等记录；传输和Docker/VM身份为替身，不执行来宾操作。"""
import io
import json
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical,validate_request,MAX_MESSAGE_BYTES
from ctflab_guest_agent import serve,parse_frame
from ctflab_guest_channel import GuestClient
from ctflab_qemu_driver import QemuDriver,read
from ctflab_windows_recovery import record
import test_ctflab_guest_agent as agent_fixtures
import test_ctflab_guest_contract as contract_fixtures


class FramedSocket:
    def __init__(self,agent,*,legacy=False,lost=False):
        self.agent=agent;self.stream=io.BytesIO();self.requests=[];self.legacy=legacy;self.lost=lost
    def makefile(self,*args,**kwargs):return self.stream
    def sendall(self,raw):
        request=parse_frame(raw);self.requests.append(request);destination=io.BytesIO()
        serve(self.agent,io.BytesIO(raw),destination)
        value=json.loads(destination.getvalue())
        if self.legacy and request['action']=='configure':value['result'].pop('capabilities',None)
        self.stream.seek(0);self.stream.truncate()
        if not (self.lost and request['action']=='preparation-resume'):self.stream.write((canonical(value)+'\n').encode())
        self.stream.seek(0)
    def close(self):pass


class RecoveryIntegrationTests(unittest.TestCase):
    setUp=agent_fixtures.AgentTests.setUp
    request=agent_fixtures.AgentTests.request
    run_action=agent_fixtures.AgentTests.run_action
    partial=agent_fixtures.PreparationRecoveryTests.partial
    writes=agent_fixtures.PreparationRecoveryTests.writes
    def client(self,*,legacy=False,lost=False):
        socket=FramedSocket(self.agent,legacy=legacy,lost=lost);self.sockets.append(socket)
        d=self.definition
        definition={k:d[k] for k in ('devices','flows','containers','container_cidr')}
        with patch('ctflab_guest_channel.tcp',return_value=object()),patch('ctflab_guest_channel.wrap_client',return_value=socket):
            return GuestClient(46211,Path('/unused'),{},d['plan'],d['node'],definition)
    def host(self,*,legacy=False,lost=False):
        self.sockets=[];attempt=self.root/'host-attempt';attempt.mkdir(mode=0o700);record(attempt/'control.lock',{})
        driver=QemuDriver.__new__(QemuDriver);driver.location=lambda *args:attempt;driver.latest=lambda *args:attempt
        driver.guest_agent=lambda *args:self.client(legacy=legacy,lost=lost)
        self.attempt=attempt;self.driver=driver
    def command(self,action,target,expected=None,operation=None):
        extra={'target_operation_id':target}
        if expected is not None:extra['expected_sha256']=expected
        return self.driver.guest_command(self.definition['plan'],'middle',{},action,operation or str(uuid.uuid4()),**extra)

    def test_host_channel_snapshot_resume_preserves_volume_and_only_creates_missing_container(self):
        operation=self.partial();volume=self.backend.objects['volume',self.agent.prefix+'-web-data'];volume['data']='saved-progress'
        before=len(self.writes());self.host();snapshot=self.command('preparation-inspect',operation)
        self.assertEqual(len(self.writes()),before);self.assertTrue(snapshot['can_resume'])
        request=self.sockets[-1].requests[-1]
        self.assertNotEqual(request['operation_id'],operation);self.assertEqual(request['target_operation_id'],operation)
        result=self.command('preparation-resume',operation,snapshot['resume_sha256'])
        self.assertEqual(result['state'],'containers-prepared');self.assertFalse(result['services_started'])
        self.assertEqual(volume['data'],'saved-progress');self.assertEqual(len(self.writes())-before,1)
        self.assertEqual(self.writes()[-1][1:3],('container','create'))
        records=[read(p) for p in self.attempt.glob('guest-*.intent.json')]
        resumed=next(v for v in records if v['action']=='preparation-resume')
        self.assertEqual(resumed['expected_sha256'],snapshot['resume_sha256']);self.assertEqual(resumed['target_operation_id'],operation)

    def test_transport_id_cannot_change_accepted_target_or_snapshot(self):
        target=self.partial();self.host();snapshot=self.command('preparation-inspect',target);operation=str(uuid.uuid4())
        self.command('preparation-resume',target,snapshot['resume_sha256'],operation);count=len(self.writes());connections=len(self.sockets)
        self.command('preparation-resume',target,snapshot['resume_sha256'],operation)
        self.assertEqual(len(self.writes()),count);self.assertEqual(len(self.sockets),connections)
        for other,sha in [(str(uuid.uuid4()),snapshot['resume_sha256']),(target,'a'*64)]:
            with self.assertRaises(ContractError):self.command('preparation-resume',other,sha,operation)
        self.assertEqual(len(self.writes()),count)

    def test_old_agent_capabilities_refuse_before_host_intent_or_resume_request(self):
        target=self.partial();self.host(legacy=True);count=len(self.writes())
        with self.assertRaises(ContractError):self.command('preparation-inspect',target)
        self.assertEqual(list(self.attempt.glob('guest-*.intent.json')),[])
        self.assertEqual([r['action'] for r in self.sockets[0].requests],['configure'])
        self.assertEqual(len(self.writes()),count)
        with self.client(legacy=True) as client:self.assertEqual(client.command('status',str(uuid.uuid4()))['state'],'observed')

    def test_stale_snapshot_refused_without_creating_remaining_resources(self):
        target=self.partial();self.host();snapshot=self.command('preparation-inspect',target);count=len(self.writes())
        with self.agent.db() as db:db.execute("UPDATE effects SET result=NULL WHERE operation=? AND step='network'",(target,))
        result=self.command('preparation-resume',target,snapshot['resume_sha256'])
        self.assertEqual(result['state'],'unknown');self.assertEqual(len(self.writes()),count)
        self.assertFalse(self.backend.objects.get(('container',self.agent.prefix+'-web')))

    def test_lost_resume_response_not_replayed_and_new_inspection_reports_completed(self):
        target=self.partial();self.host(lost=True);snapshot=self.command('preparation-inspect',target);operation=str(uuid.uuid4())
        result=self.command('preparation-resume',target,snapshot['resume_sha256'],operation)
        self.assertEqual(result['state'],'unknown');count=len(self.writes())
        self.command('preparation-resume',target,snapshot['resume_sha256'],operation)
        self.assertEqual(len(self.writes()),count)
        self.assertEqual(self.command('preparation-inspect',target)['state'],'completed')
        self.assertEqual(len(self.writes()),count)

    def test_wrong_generation_policy_or_unknown_fields_refused_before_resource_mutation(self):
        target=self.partial();count=len(self.writes())
        valid=dict(self.request('preparation-inspect'),target_operation_id=target)
        for change in ({'generation':2},{'policy_sha256':'b'*64},{'target_operation_id':'bad'},{'shell':'anything'},{'expected_sha256':'a'*64}):
            with self.assertRaises((ContractError,ValueError,TypeError)):self.agent.dispatch(dict(valid,**change))
        self.assertEqual(len(self.writes()),count)

    def test_large_snapshot_is_bounded_on_wire_without_truncation_or_side_effect(self):
        target=self.partial();self.host();count=len(self.writes())
        with patch.object(self.agent,'inspect_preparation',return_value={'state':'preparation-observed','huge':'x'*MAX_MESSAGE_BYTES}):
            value=self.command('preparation-inspect',target)
        self.assertEqual(value['state'],'unknown');self.assertEqual(value['error'],'response-too-large')
        self.assertEqual(len(self.writes()),count);self.assertNotIn('huge',value)

    def test_desktop_history_exposes_original_unknown_and_target_bound_snapshot_without_probe(self):
        from ctflab_desktop_bridge import guest_history
        target=self.partial();self.host();snapshot=self.command('preparation-inspect',target)
        # 代表早先宿主丢回复的原准备记录，不替来宾判定当前pending。
        record(self.attempt/('guest-'+target+'.intent.json'),{'operation_id':target,'action':'containers-prepare',
            'plan_sha256':self.definition['plan']['plan_sha256']})
        value=guest_history(self.attempt,self.definition['plan']['plan_sha256'])
        self.assertEqual(value['preparation_records'],[{'operation_id':target,'state':'original-result-unconfirmed','guest_rechecked':False}])
        self.assertEqual(value['last_action'],'preparation-inspect');self.assertEqual(value['last_result'],snapshot)
        self.assertFalse(value['preparation_records'][0]['guest_rechecked'])
        with self.assertRaises(ContractError):guest_history(self.attempt,'b'*64)


class RecoveryContractTests(unittest.TestCase):
    setUp=contract_fixtures.GuestContractTests.setUp
    context=contract_fixtures.GuestContractTests.context
    run_action=contract_fixtures.GuestContractTests.run_action
    prepare_service=contract_fixtures.GuestContractTests.prepare_service
    request=contract_fixtures.GuestContractTests.request
    def test_contract_routes_target_and_hash_under_existing_cas_and_work_gate(self):
        self.prepare_service();calls=[]
        def guest(plan,node,paths,action,operation,**extra):
            calls.append((action,extra));return {'state':'containers-prepared'}
        self.driver.guest_command=guest;request=self.request('guest','preparation-resume')
        target=str(uuid.uuid4());request['parameters'].update(target_operation_id=target,expected_sha256='a'*64)
        self.assertEqual(validate_request(request),request)
        accepted=self.service.submit(request,self.actor);result=self.service.execute(accepted['operation_id'],self.actor,self.backend)
        self.assertEqual(result['state'],'process-running')
        self.assertEqual(calls,[('preparation-resume',{'target_operation_id':target,'expected_sha256':'a'*64})])
        self.service.execute(accepted['operation_id'],self.actor,self.backend);self.assertEqual(len(calls),1)
    def test_contract_rejects_missing_extra_or_malformed_recovery_parameters(self):
        self.prepare_service();base=self.request('guest','preparation-resume')
        for params in [base['parameters'],dict(base['parameters'],target_operation_id=str(uuid.uuid4()),expected_sha256='A'*64),
            {'node':'middle','action':'preparation-inspect','target_operation_id':str(uuid.uuid4()),'expected_sha256':'a'*64},
            {'node':'middle','action':'status','target_operation_id':str(uuid.uuid4())}]:
            with self.assertRaises(ContractError):validate_request(dict(base,parameters=params))
