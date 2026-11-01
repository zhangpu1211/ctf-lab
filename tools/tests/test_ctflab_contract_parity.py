"""前端模型与Python契约实值对照；临时SQLite/合成后端，无桌面或来宾。"""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ctflab_contract as contract
import ctflab_desktop_bridge as bridge
from ctflab_local_adapter import LocalAdapter,process_actor
from ctflab_local_service import LocalService
from ctflab_windows_probe import FixtureBackend

ROOT=Path(__file__).resolve().parents[2]
NODE=shutil.which('node')


def node_model(program, value):
    script="import * as model from "+json.dumps((ROOT/'desktop/src/model.mjs').as_uri())+";let input='';for await(const chunk of process.stdin)input+=chunk;const data=JSON.parse(input);"+program
    result=subprocess.run([NODE,'--input-type=module','-e',script],input=contract.canonical(value),text=True,capture_output=True,cwd=ROOT,timeout=15)
    if result.returncode:raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def event_cases(events,instance):
    """各条件独立变异，避免一种错误掩盖另一判据。"""
    cases=[]
    def put(name,values,cursor=0,scope=instance,accepted=True):
        cases.append({'name':name,'cursor':cursor,'events':values,'instance':scope,'accepted':accepted})
    put('actual-three-events',events);put('empty',[]);put('infer-instance',events,scope=None)
    put('old-prefix',events,cursor=1);put('all-old',events,cursor=events[-1]['sequence'])
    put('identical-duplicate',events+[events[-1]])
    put('same-fields-different-order',events+[dict(reversed(list(events[-1].items())))])
    put('missing-first',events[1:],accepted=False)
    put('foreign-instance',events,scope=str(uuid.uuid4()),accepted=False)
    put('duplicate-id-different-sequence',[events[0],dict(events[1],event_id=events[0]['event_id'])],accepted=False)
    put('duplicate-sequence-different-content',[events[0],dict(events[0],state='failed')],accepted=False)
    for field in events[0]:
        changed=dict(events[0]);del changed[field];put('missing-'+field,[changed],accepted=False)
    changes={'protocol':['wrong',None], 'version':[True,2,'1'], 'event_id':['bad',None],
        'operation_id':['bad',None], 'instance_uuid':['bad',None], 'sequence':[True,0,-1,1.5,2**53],
        'generation':[True,0,-1,1.5,2**53], 'state_revision':[True,-1,1.5,2**53],
        'state':['ready',None,['prepared'],{}], 'stage':['fake',None,['intent']], 'timestamp':[None,1,'x'*65]}
    for field,values in changes.items():
        for index,value in enumerate(values):put(f'bad-{field}-{index}',[dict(events[0],**{field:value})],accepted=False)
    put('extra-field',[dict(events[0],extra='private')],accepted=False)
    put('bad-old-event',[dict(events[0],version=2)],cursor=1,accepted=False)
    put('over-limit',[events[0]]*1001,accepted=False)
    for index,value in enumerate((-1,True,1.5,2**53)):put('bad-cursor-'+str(index),[],cursor=value,accepted=False)
    for index,value in enumerate((None,{},'bad',{'events':events})):
        put('bad-wire-'+str(index),value,accepted=False)
    for state in sorted(contract.STATES):put('state-'+state,[dict(events[0],state=state)])
    for stage in ('intent','executing','cancel-requested','failed','cancelled','completed'):
        put('stage-'+stage,[dict(events[0],stage=stage)])
    # Python按Unicode码点计数时间字段，而非UTF-16码元。
    put('unicode-timestamp',[dict(events[0],timestamp='界'*64)])
    put('astral-timestamp',[dict(events[0],timestamp='🙂'*64)])
    return cases


@unittest.skipUnless(NODE,'前端协议实值对照需要Node；不把跳过当通过')
class ContractParityTests(unittest.TestCase):
    def setUp(self):
        from test_ctflab_generation_store import GenerationTests
        GenerationTests.setUp(self)
        self.actor=process_actor();self.service=LocalService.create(self.store.root/'desktop-contract')
        self.calls=[];self.synthetic=FixtureBackend()

    def typed(self,req):
        return bridge.dispatch(self.store.root,{'action':'submit','request':req},spawn=lambda *a,**kw:self.calls.append((a,kw)))

    def build(self,operation,state=None,parameters=None,key=None,request_id=None):
        view={'instance_uuid':self.instance,'status':state or {'generation':1,'state_revision':0}}
        return node_model('console.log(JSON.stringify(model.request(data.operation,data.view,data.parameters,data.key,data.request_id)));',
            {'operation':operation,'view':view,'parameters':parameters or {},'key':key or str(uuid.uuid4()),'request_id':request_id or str(uuid.uuid4())})

    def prepare(self):
        req=self.build('prepare',parameters={'course_id':'course','baseline_id':'base'})
        accepted=self.service.handle_json(contract.canonical(req),self.actor)
        return req,accepted

    def test_actual_bridge_cli_array_and_frontend_consume_same_events(self):
        req,accepted=self.prepare();self.service.execute(accepted['operation_id'],self.actor,self.synthetic)
        before=(self.store.root/'desktop-contract/contract.sqlite3').read_bytes()
        proc=subprocess.run([sys.executable,'-I','-B',str(ROOT/'tools/ctflab_desktop_bridge.py'),'bridge','--run',str(self.store.root)],input=contract.canonical({'action':'events','after':0}),capture_output=True,text=True,cwd=self.root,timeout=15)
        self.assertEqual(proc.returncode,0,proc.stderr);wire=json.loads(proc.stdout)
        self.assertIs(type(wire),list);self.assertEqual(len(wire),3)
        result=node_model('console.log(JSON.stringify(model.consumeEvents(0,data.events,data.instance)));',{'events':wire,'instance':self.instance})
        cursor,events=contract.merge_events(0,wire,instance_uuid=self.instance)
        self.assertEqual(result,{'cursor':cursor,'events':events,'reload':False})
        self.assertEqual(before,(self.store.root/'desktop-contract/contract.sqlite3').read_bytes())

    def test_event_contract_negative_matrix_matches_python_without_input_mutation(self):
        req,accepted=self.prepare();self.service.execute(accepted['operation_id'],self.actor,self.synthetic)
        events=self.service.events(self.instance,self.actor);cases=event_cases(events,self.instance);original=copy.deepcopy(cases)
        results=node_model('console.log(JSON.stringify(data.map(row=>model.consumeEvents(row.cursor,row.events,row.instance))));',cases)
        for case,result in zip(cases,results):
            with self.subTest(case=case['name']):
                try:
                    cursor,fresh=contract.merge_events(case['cursor'],case['events'],instance_uuid=case['instance'])
                    expected={'cursor':cursor,'events':fresh,'reload':False}
                except contract.ContractError:expected={'cursor':0,'events':[],'reload':True}
                self.assertEqual(result,expected);self.assertEqual(not result['reload'],case['accepted'])
        self.assertEqual(len(results),len(cases));self.assertGreater(len(cases),80);self.assertEqual(cases,original)

    def test_request_builders_all_operations_validate_and_retries_keep_digest(self):
        values={'status':{},'prepare':{'course_id':'course','baseline_id':'base'},'start':{'display':'headless','allow_emulation':False},
            'stop':{},'reset':{'baseline_id':'base'},'recover':{},'cancel':{'operation_id':str(uuid.uuid4())},'guest':{'node':'client','action':'status'}}
        for operation,parameters in values.items():
            with self.subTest(operation=operation):
                req=self.build(operation,parameters=parameters)
                self.assertEqual(contract.validate_request(req),req)
                retry=dict(req,request_id=str(uuid.uuid4()))
                self.assertEqual(contract.fingerprint(req),contract.fingerprint(retry))
                if operation!='status':
                    changed=dict(req,idempotency_key=str(uuid.uuid4()))
                    self.assertNotEqual(contract.fingerprint(req),contract.fingerprint(changed))

    def test_cli_and_typed_gui_share_pending_terminal_replay_and_status(self):
        req,accepted=self.prepare()
        self.assertEqual(self.typed(req),accepted);self.assertEqual(len(self.calls),1)
        self.assertEqual(self.typed(req),accepted);self.assertEqual(len(self.calls),1)
        complete=self.service.execute(accepted['operation_id'],self.actor,self.synthetic)
        retry=dict(req,request_id=str(uuid.uuid4()))
        cli=self.service.handle_json(contract.canonical(retry),self.actor);gui=self.typed(retry)
        self.assertEqual(cli,gui);self.assertEqual(gui['operation_id'],accepted['operation_id']);self.assertEqual(gui['result'],'completed')
        self.assertEqual(self.synthetic.calls,['prepare']);self.assertEqual(len(self.calls),1)
        status=self.build('status');before=(self.store.root/'desktop-contract/contract.sqlite3').read_bytes()
        self.assertEqual(LocalAdapter(self.store.root/'desktop-contract').dispatch(contract.canonical(status)),self.typed(status))
        self.assertEqual(before,(self.store.root/'desktop-contract/contract.sqlite3').read_bytes())
        for bad in (dict(req,version=2),dict(req,parameters={'course_id':'different','baseline_id':'base'})):
            cli=self.service.handle_json(contract.canonical(bad),self.actor)
            try:gui=self.typed(bad)
            except contract.ContractError as error:gui={'error':contract.public_error(error.code)}
            self.assertEqual(cli['error'],gui['error'])
        self.assertEqual(complete['state'],'prepared')

    def test_all_lifecycle_requests_and_cancel_share_durable_semantics(self):
        from ctflab_local_service import Outcome
        class Backend(FixtureBackend):
            def execute(self,req,context):
                if req['operation']=='guest':
                    self.calls.append('guest');return Outcome('process-running')
                return super().execute(req,context)
        backend=Backend();state=None
        for operation,parameters in [('prepare',{'course_id':'course','baseline_id':'base'}),
                ('start',{'display':'headless','allow_emulation':False}),('guest',{'node':'client','action':'status'}),
                ('stop',{}),('reset',{'baseline_id':'base'}),('recover',{})]:
            req=self.build(operation,state=state,parameters=parameters)
            cli=self.service.handle_json(contract.canonical(req),self.actor)
            self.assertEqual(cli,self.typed(req));self.assertEqual(cli['result'],'accepted')
            state=self.service.execute(cli['operation_id'],self.actor,backend)
            self.assertEqual(state['result'],'completed')
            self.assertEqual(self.service.handle_json(contract.canonical(req),self.actor),self.typed(req))
            status=self.build('status');self.assertEqual(LocalAdapter(self.store.root/'desktop-contract').dispatch(contract.canonical(status)),self.typed(status))
        self.assertEqual(backend.calls,['prepare','start','guest','stop','reset','recover'])
        start=self.build('start',state=state,parameters={'display':'headless','allow_emulation':False})
        accepted=self.service.handle_json(contract.canonical(start),self.actor)
        cancel=self.build('cancel',state=accepted,parameters={'operation_id':accepted['operation_id']})
        self.assertEqual(self.service.handle_json(contract.canonical(cancel),self.actor),self.typed(cancel))
        cancelled=self.service.execute(accepted['operation_id'],self.actor,backend)
        self.assertTrue(cancelled['cancelled']);self.assertEqual(backend.calls,['prepare','start','guest','stop','reset','recover'])
        self.assertEqual(self.service.query_request(cancel,self.actor)['response'],self.typed(cancel))

    def test_failed_unknown_and_ready_are_not_relabelled_by_readers(self):
        from unittest import mock
        from ctflab_local_service import Outcome
        req,accepted=self.prepare();prepared=self.service.execute(accepted['operation_id'],self.actor,self.synthetic)
        start=self.build('start',state=prepared,parameters={'display':'headless','allow_emulation':False})
        pending=self.service.handle_json(contract.canonical(start),self.actor)
        # 执行器只保存了executing而未有结果时，两个读取入口保持unknown/recovery-required。
        with self.service._transaction() as db:db.execute('UPDATE operations SET status=? WHERE id=?',('executing',pending['operation_id']))
        status=self.build('status');a=LocalAdapter(self.store.root/'desktop-contract')
        value=a.dispatch(contract.canonical(status));self.assertEqual(value,self.typed(status));self.assertEqual(value['result'],'unknown');self.assertEqual(value['state'],'recovery-required')
        # 恢复夹具领取前状态，再由合成后端返回明确失败，不推断为ready。
        with self.service._transaction() as db:db.execute('UPDATE operations SET status=? WHERE id=?',('pending',pending['operation_id']))
        with mock.patch.object(self.synthetic,'execute',return_value=Outcome('unknown','identity-unknown')):
            failed=self.service.execute(pending['operation_id'],self.actor,self.synthetic)
        self.assertEqual(failed['result'],'failed');self.assertEqual(failed['state'],'unknown')
        self.assertEqual(self.service.handle_json(contract.canonical(start),self.actor),self.typed(start))
        # ready仅在受信后端显式给出成功观察时保留，不从进程运行标签升级。
        recover=self.build('recover',state=failed)
        pending=self.service.handle_json(contract.canonical(recover),self.actor)
        with mock.patch.object(self.synthetic,'execute',return_value=Outcome('service-ready')):
            ready=self.service.execute(pending['operation_id'],self.actor,self.synthetic)
        self.assertEqual(ready['state'],'service-ready')
        value=a.dispatch(contract.canonical(status));self.assertEqual(value,self.typed(status));self.assertEqual(value['state'],'service-ready')

    def test_real_cursor_expiration_relocates_to_bound_status_and_reads_next_events(self):
        req,accepted=self.prepare();prepared=self.service.execute(accepted['operation_id'],self.actor,self.synthetic)
        status_req=self.build('status');status=self.service.status(status_req,self.actor)
        self.service.prune_events(self.instance,self.actor,through=1)
        def wire(after):
            proc=subprocess.run([sys.executable,'-I','-B',str(ROOT/'tools/ctflab_desktop_bridge.py'),'bridge','--run',str(self.store.root)],input=contract.canonical({'action':'events','after':after}),text=True,capture_output=True,cwd=self.root,timeout=15)
            return proc.returncode,json.loads(proc.stdout)
        code,response=wire(0);self.assertEqual(code,2);self.assertEqual(response['error']['code'],'cursor-expired')
        view={'instance_uuid':self.instance,'status':status}
        program='console.log(JSON.stringify(model.refreshEvents(data.cursor,data.response,data.view)));'
        relocated=node_model(program,{'cursor':0,'response':response,'view':view})
        self.assertEqual(relocated,{'cursor':status['cursor'],'events':[],'reload':True})
        start=self.build('start',state=prepared,parameters={'display':'headless','allow_emulation':False})
        accepted=self.service.submit(start,self.actor);self.service.execute(accepted['operation_id'],self.actor,self.synthetic)
        code,response=wire(relocated['cursor']);self.assertEqual(code,0)
        resumed=node_model(program,{'cursor':relocated['cursor'],'response':response,'view':view})
        self.assertFalse(resumed['reload']);self.assertEqual(len(resumed['events']),3);self.assertEqual(resumed['cursor'],6)
        self.assertEqual(self.synthetic.calls,['prepare','start']);self.assertEqual(self.calls,[])
