"""桌面桥接契约验证；真实数据库和临时磁盘，不启动 VM 或桌面。"""
import json
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_ctflab_generation_store as generation_tests
import ctflab_desktop_bridge as bridge
from ctflab_local_service import LocalService
from ctflab_local_adapter import process_actor
from ctflab_contract import ContractError


class BridgeTests(unittest.TestCase):
    setUp = generation_tests.GenerationTests.setUp

    def test_course_import_allocates_each_multimember_link_without_starting(self):
        from test_ctflab_catalog import fixture
        from ctflab_generation_store import digest,GenerationStore
        value=fixture();variant=value['courses']['course']['variants']['x64']
        manifest=variant['scenario'];manifest['assets']['linux']['sha256']=digest(self.base)
        manifest['nodes']['client']['interfaces'].append(dict(id='eth1',network='inner',
            address='10.81.0.40',mac='derived',model='e1000'))
        manifest['networks']['unused']={'cidr':'10.90.0.0/24','uplink':'none'}
        variant['assets']['linux']=self.base.name
        catalog=self.root/'catalog.json';catalog.write_text(json.dumps(value))
        probes=[]
        class Probe:
            def __init__(self):self.port=20000+len(probes);self.closed=False;probes.append(self)
            def bind(self,address):assert address==('127.0.0.1',0)
            def getsockname(self):return ('127.0.0.1',self.port)
            def close(self):self.closed=True
        root=self.root/'imported'
        with patch.object(bridge.socket,'socket',Probe),patch('ctflab_runtime_inventory.inventory',return_value={}),\
             patch('ctflab_runtime_inventory.compare',return_value={'matches':True}),\
             patch('ctflab_windows_control.read_json',return_value={}):
            result=bridge.import_course(root,dict(action='import-course',catalog=str(catalog),course_id='course',
                variant_id='x64',asset_root=str(self.root)))
        self.assertEqual(result['state'],'configured');self.assertFalse(result['runtime_verified'])
        profile=bridge.read(root/'runtime-profile.json')
        self.assertEqual(profile['networks'],{'inner':{'middle':20006,'client':20007},'outer':20008,'unused':{}})
        self.assertEqual(len(probes),9);self.assertTrue(all(p.closed for p in probes))
        self.assertEqual(GenerationStore(root).snapshot()['generations'],[])
        self.assertEqual(digest(self.base),manifest['assets']['linux']['sha256'])

    def test_course_import_reserves_external_attach_slot_without_starting(self):
        from test_ctflab_catalog import fixture
        from ctflab_generation_store import digest,GenerationStore
        from ctflab_external_attach import validate_hub_networks
        value=fixture();variant=value['courses']['course']['variants']['x64']
        manifest=variant['scenario'];manifest['assets']['linux']['sha256']=digest(self.base)
        manifest['networks']['outer']['external']={'schema':1,'address':'10.80.0.9','mac':'02:aa:bb:cc:dd:0e'}
        variant['assets']['linux']=self.base.name
        catalog=self.root/'catalog.json';catalog.write_text(json.dumps(value))
        probes=[]
        class Probe:
            def __init__(self):self.port=30000+len(probes);self.closed=False;probes.append(self)
            def bind(self,address):assert address==('127.0.0.1',0)
            def getsockname(self):return ('127.0.0.1',self.port)
            def close(self):self.closed=True
        root=self.root/'imported-attach'
        with patch.object(bridge.socket,'socket',Probe),patch('ctflab_runtime_inventory.inventory',return_value={}),\
             patch('ctflab_runtime_inventory.compare',return_value={'matches':True}),\
             patch('ctflab_windows_control.read_json',return_value={}):
            result=bridge.import_course(root,dict(action='import-course',catalog=str(catalog),course_id='course',
                variant_id='x64',asset_root=str(self.root)))
        self.assertEqual(result['state'],'configured')
        profile=bridge.read(root/'runtime-profile.json')
        # 二成员带槽位必须转hub规划并携带预留口；其余网段保持原格式。
        self.assertIsInstance(profile['networks']['outer'],dict)
        self.assertIn('external',profile['networks']['outer'])
        self.assertIsInstance(profile['networks']['inner'],int)
        from ctflab_scenario_v2 import instance_plan
        store=GenerationStore(root)
        plan=instance_plan(store.config['manifest'],store.config['instance_uuid'])
        _flattened,external=validate_hub_networks(plan,profile['networks'])
        self.assertEqual(external,{'outer':profile['networks']['outer']['external']})
        self.assertTrue(all(p.closed for p in probes))
        self.assertEqual(GenerationStore(root).snapshot()['generations'],[])

    def connect(self):
        self.calls = []
        self.root = self.store.root
        LocalService.create(self.root/'desktop-contract')
        bridge.record(self.root/'runtime-profile.json',{'agents':{}})

    def dispatch(self, value):
        return bridge.dispatch(self.root, value, spawn=lambda *a, **k: self.calls.append((a,k)),
                               make_backend=lambda _: self.backend)

    def prepare(self):
        req = {'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),'operation':'prepare',
               'instance_uuid':self.instance,'expected_generation':None,'expected_state_revision':None,
               'idempotency_key':str(uuid.uuid4()),'parameters':{'course_id':'c01','baseline_id':'base'}}
        response = self.dispatch({'action':'submit','request':req})
        return req,response

    def test_repeated_click_spawns_only_once(self):
        self.connect();req, response = self.prepare()
        self.assertEqual(response['result'], 'accepted')
        req['request_id'] = str(uuid.uuid4())
        self.assertEqual(self.dispatch({'action':'submit','request':req})['operation_id'], response['operation_id'])
        self.assertEqual(len(self.calls), 1)
        service = LocalService(self.root/'desktop-contract')
        self.assertEqual(service.execute(response['operation_id'], process_actor(), self.backend)['state'], 'prepared')

    def test_overview_never_upgrades_process_to_guest_or_service(self):
        self.connect();req, response = self.prepare()
        LocalService(self.root/'desktop-contract').execute(response['operation_id'], process_actor(), self.backend)
        result = self.dispatch({'action':'overview'})
        self.assertEqual(result['generation'],1)
        self.assertFalse(result['isolation_verified'])
        self.assertEqual({v['state'] for v in result['observations'].values()}, {'stopped'})
        self.assertEqual(result['manifest'], self.manifest)

    def test_cross_instance_submit_rejected_before_spawn(self):
        self.connect();req,response=self.prepare(); self.calls.clear()
        req['instance_uuid']=str(uuid.uuid4())
        with self.assertRaises(ContractError):self.dispatch({'action':'submit','request':req})
        self.assertEqual(self.calls,[])

    def test_unknown_action_and_extra_fields_rejected(self):
        self.connect()
        for value in ({'action':'shell','command':'anything'},{'action':'overview','command':'anything'}):
            with self.assertRaises(ContractError):self.dispatch(value)

    def test_spawn_failure_preserves_pending_operation_no_replay(self):
        self.connect()
        with patch.object(bridge,'launch',side_effect=OSError):
            # 显式注入失败，不依赖函数默认参数的绑定时间。
            req = {'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),'operation':'prepare',
                   'instance_uuid':self.instance,'expected_generation':None,'expected_state_revision':None,
                   'idempotency_key':str(uuid.uuid4()),'parameters':{'course_id':'c01','baseline_id':'base'}}
            def fail(*a,**k):raise OSError('合成派发失败')
            result = bridge.dispatch(self.root,{'action':'submit','request':req},spawn=fail)
        self.assertEqual(result['state'],'recovery-required')
        self.dispatch({'action':'submit','request':req})
        self.assertEqual(self.calls,[])
        self.assertEqual(self.store.snapshot()['active_generation'],0)

    def resume_value(self, response):
        return {'action':'resume-dispatch','instance_uuid':self.instance,
                'operation_id':response['operation_id'],'state_revision':response['state_revision'],
                'attempt_id':str(uuid.uuid4())}

    def test_pending_dispatch_can_continue_after_reopen_without_new_intent(self):
        self.connect();req,response=self.prepare()
        before=(self.root/('desktop-dispatch-'+response['operation_id']+'.json')).read_bytes()
        view=self.dispatch({'action':'overview'})
        self.assertTrue(view['dispatch']['resume_allowed'])
        value=self.resume_value(response)
        self.assertEqual(self.dispatch(value)['state'],'dispatch-requested')
        self.assertEqual(self.dispatch(value)['state'],'dispatch-already-requested')
        self.assertEqual(len(self.calls),2)
        self.assertEqual({call[1]['operation'] for call in self.calls},{response['operation_id']})
        self.assertEqual(LocalService(self.root/'desktop-contract').status(
            dict(protocol='ctflab-local',version=1,request_id=str(uuid.uuid4()),operation='status',instance_uuid=self.instance),
            process_actor())['state_revision'],response['state_revision'])
        self.assertEqual((self.root/('desktop-dispatch-'+response['operation_id']+'.json')).read_bytes(),before)
        self.assertEqual(self.store.snapshot()['active_generation'],0)

    def test_resume_spawn_failure_is_unknown_and_not_automatically_repeated(self):
        self.connect();_,response=self.prepare();value=self.resume_value(response)
        def fail(*a,**k):raise OSError('夹具派发失败')
        result=bridge.dispatch(self.root,value,spawn=fail)
        self.assertEqual(result['state'],'dispatch-unknown')
        self.assertEqual(self.dispatch(value)['state'],'dispatch-already-requested')
        self.assertEqual(len(self.calls),1)
        value['attempt_id']=str(uuid.uuid4())
        self.assertEqual(self.dispatch(value)['operation_id'],response['operation_id'])
        self.assertEqual(len(self.calls),2)

    def test_resume_refuses_cross_instance_stale_version_and_extra_fields(self):
        self.connect();_,response=self.prepare();value=self.resume_value(response)
        for changes in ({'instance_uuid':str(uuid.uuid4())},{'state_revision':0},
                        {'state_revision':True},{'command':'anything'},{'attempt_id':'bad'}):
            with self.subTest(changes=changes),self.assertRaises(ContractError):self.dispatch(dict(value,**changes))
        self.assertEqual(len(self.calls),1)

    def test_dispatch_status_refuses_other_actor_or_operation(self):
        self.connect();_,response=self.prepare();service=LocalService(self.root/'desktop-contract')
        with self.assertRaises(ContractError):service.dispatch_status(self.instance,response['operation_id'],'another-owner')
        with self.assertRaises(ContractError):service.dispatch_status(self.instance,str(uuid.uuid4()),process_actor())
        with self.assertRaises(ContractError):service.dispatch_status(str(uuid.uuid4()),response['operation_id'],process_actor())

    def test_resume_attempt_id_cannot_refer_to_different_version(self):
        self.connect();_,response=self.prepare();value=self.resume_value(response)
        self.dispatch(value)
        path=self.root/('desktop-redelivery-'+value['attempt_id']+'.json')
        prior=path.read_bytes()
        with patch.object(bridge,'read',return_value={'operation_id':str(uuid.uuid4())}):
            with self.assertRaises(ContractError):self.dispatch(value)
        self.assertEqual(path.read_bytes(),prior)
        self.assertEqual(len(self.calls),2)

    def test_executing_and_unknown_operations_are_never_redelivered(self):
        self.connect();_,response=self.prepare();service=LocalService(self.root/'desktop-contract')
        for state in ('executing','unknown'):
            with service._transaction() as db:db.execute('UPDATE operations SET status=? WHERE id=?',(state,response['operation_id']))
            self.assertFalse(service.dispatch_status(self.instance,response['operation_id'],process_actor())['resume_allowed'])
            with self.assertRaises(ContractError):self.dispatch(self.resume_value(response))
        self.assertEqual(len(self.calls),1)

    def test_completed_operation_cannot_be_resumed(self):
        self.connect();_,response=self.prepare()
        LocalService(self.root/'desktop-contract').execute(response['operation_id'],process_actor(),self.backend)
        with self.assertRaises(ContractError):self.dispatch(self.resume_value(response))
        self.assertIsNone(self.dispatch({'action':'overview'})['dispatch'])
        self.assertEqual(len(self.calls),1)

    def test_cancel_before_resume_keeps_original_cancel_and_never_prepares(self):
        self.connect();_,response=self.prepare()
        req={'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),'operation':'cancel',
             'instance_uuid':self.instance,'expected_generation':response['generation'],
             'expected_state_revision':response['state_revision'],'idempotency_key':str(uuid.uuid4()),
             'parameters':{'operation_id':response['operation_id']}}
        result=self.dispatch({'action':'submit','request':req})
        value=self.resume_value(response)
        with self.assertRaises(ContractError):self.dispatch(value)
        value['state_revision']=result['state_revision']
        self.assertTrue(self.dispatch(value)['cancel_requested'])
        done=LocalService(self.root/'desktop-contract').execute(response['operation_id'],process_actor(),self.backend)
        self.assertTrue(done['cancelled']);self.assertEqual(self.store.snapshot()['active_generation'],0)

    def test_late_and_duplicate_workers_preserve_old_markers_and_execute_once(self):
        from ctflab_windows_native import ProcessIdentity
        self.connect();_,response=self.prepare();operation=response['operation_id']
        old=self.root/('desktop-execution-'+operation+'.json')
        bridge.record(old,{'pid':11,'creation_ticks':1,'image_path':'old-worker','state':'exited'})
        original=old.read_bytes();execute=self.backend.execute;calls=[]
        def counted(*a,**k):calls.append(1);return execute(*a,**k)
        def observed(pid):return ProcessIdentity(pid,42,'synthetic-worker','running')
        self.dispatch(self.resume_value(response))
        with patch.object(self.backend,'execute',side_effect=counted):
            for _ in range(2):
                result=bridge.execute_operation(self.root,operation,make_backend=lambda _:self.backend,observe=observed)
                self.assertEqual(result['state'],'prepared')
        self.assertEqual(calls,[1]);self.assertEqual(old.read_bytes(),original)
        self.assertEqual(len(list(self.root.glob('desktop-execution-'+operation+'-*.json'))),2)

    def test_simultaneous_workers_claim_backend_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from ctflab_windows_native import ProcessIdentity
        self.connect();_,response=self.prepare();gate=Barrier(2);execute=self.backend.execute;calls=[]
        def counted(*a,**k):calls.append(1);return execute(*a,**k)
        def job():
            gate.wait(timeout=5)
            try:return bridge.execute_operation(self.root,response['operation_id'],make_backend=lambda _:self.backend,
                observe=lambda pid:ProcessIdentity(pid,42,'synthetic-worker','running'))
            except ContractError as exc:return {'error':exc.code}
        with patch.object(self.backend,'execute',side_effect=counted),ThreadPoolExecutor(max_workers=2) as workers:
            results=list(workers.map(lambda _:job(),range(2)))
        self.assertEqual(calls,[1]);self.assertTrue(any(r.get('state')=='prepared' for r in results))
        self.assertEqual(self.store.snapshot()['active_generation'],1)

    def test_execution_snapshot_keeps_any_running_identity_and_damaged_record_unknown(self):
        from ctflab_windows_native import ProcessIdentity
        self.connect();_,response=self.prepare();operation=response['operation_id']
        for pid,state in ((101,'exited'),(102,'running')):
            bridge.record(self.root/('desktop-execution-'+operation+'-'+str(uuid.uuid4())+'.json'),
                          {'pid':pid,'creation_ticks':1,'image_path':'synthetic','state':state})
        with patch('ctflab_qemu_driver.native_observe',side_effect=lambda pid:ProcessIdentity(pid,1,'synthetic','running' if pid==102 else 'exited')):
            self.assertEqual(bridge.execution_status(self.root,operation)['identity'],'running')
        with patch('ctflab_qemu_driver.native_observe',side_effect=OSError):
            self.assertEqual(bridge.execution_status(self.root,operation)['identity'],'unknown')

    def interrupt_preparation(self, stage='copied-server-disk.qcow2'):
        self.connect();req,accepted=self.prepare();prepare=self.store.prepare_generation
        def crash(point):
            if point==stage:raise RuntimeError('首次准备夹具中断')
        def failing(operation,expected,**kwargs):return prepare(operation,expected,checkpoint=crash,**kwargs)
        with patch.object(self.store,'prepare_generation',side_effect=failing):
            result=LocalService(self.root/'desktop-contract').execute(accepted['operation_id'],process_actor(),self.backend)
        self.assertEqual(result['state'],'recovery-required')
        self.assertEqual(self.store.snapshot()['active_generation'],0)
        return accepted,result

    def restart_value(self, original):
        view=self.dispatch({'action':'overview'})
        return {'action':'restart-preparation','instance_uuid':self.instance,
                'operation_id':original['operation_id'],'state_revision':view['status']['state_revision'],
                'attempt_id':str(uuid.uuid4())}

    def test_partial_first_preparation_restarts_in_new_directory_preserving_every_byte(self):
        accepted,_=self.interrupt_preparation();original=accepted['operation_id'];base=self.base.read_bytes()
        old_files={p:p.read_bytes() for p in (self.root/'generations').rglob('*.qcow2')}
        self.assertTrue(old_files)
        view=self.dispatch({'action':'overview'});self.assertTrue(view['preparation']['restart_allowed'])
        value=self.restart_value(accepted);replacement=self.dispatch(value)
        self.assertNotEqual(replacement['operation_id'],original)
        result=LocalService(self.root/'desktop-contract').execute(replacement['operation_id'],process_actor(),self.backend)
        self.assertEqual(result['state'],'prepared')
        self.assertEqual(self.store.snapshot()['active_generation'],1)
        self.assertEqual([g['state'] for g in self.store.snapshot()['generations']],['preserved','prepared'])
        for path,data in old_files.items():self.assertEqual(path.read_bytes(),data)
        self.assertEqual(self.base.read_bytes(),base);self.assertEqual(self.driver.calls,[])
        self.assertNotIn(self.store.node_paths(1,'server')['disk'],old_files)
        self.assertIsNone(self.dispatch({'action':'overview'})['preparation'])

    def test_restart_after_claim_before_first_disk_intent(self):
        self.connect();_,accepted=self.prepare();service=LocalService(self.root/'desktop-contract')
        with service._transaction() as db:db.execute("UPDATE operations SET status='executing' WHERE id=?",(accepted['operation_id'],))
        value=self.restart_value(accepted);new=self.dispatch(value)
        self.assertEqual(service.execute(accepted['operation_id'],process_actor(),self.backend)['result'],'unknown')
        self.assertEqual(service.execute(new['operation_id'],process_actor(),self.backend)['state'],'prepared')
        self.assertEqual(len(self.store.snapshot()['generations']),1)

    def test_restart_does_not_supersede_still_pending_operation(self):
        self.connect();_,accepted=self.prepare();value=self.restart_value(accepted)
        self.assertFalse(self.dispatch({'action':'overview'})['preparation']['restart_allowed'])
        with self.assertRaises(ContractError):self.dispatch(value)
        self.assertEqual(len(self.calls),1)

    def test_restart_is_idempotent_and_preserves_original_failure_response(self):
        accepted,failed=self.interrupt_preparation();value=self.restart_value(accepted)
        first=self.dispatch(value);second=self.dispatch(value)
        self.assertEqual(first['operation_id'],second['operation_id']);self.assertEqual(len(self.calls),2)
        service=LocalService(self.root/'desktop-contract')
        self.assertEqual(service.execute(accepted['operation_id'],process_actor(),self.backend),failed)
        with self.assertRaises(ContractError):self.dispatch(dict(value,attempt_id=str(uuid.uuid4())))

    def test_restart_refuses_cross_instance_old_version_or_extra_parameters(self):
        accepted,_=self.interrupt_preparation();value=self.restart_value(accepted)
        for changed in ({'instance_uuid':str(uuid.uuid4())},{'state_revision':value['state_revision']-1},
                        {'state_revision':True},{'operation_id':str(uuid.uuid4())},
                        {'attempt_id':'invalid'},{'parameters':{'course_id':'other'}}):
            with self.subTest(changed=changed),self.assertRaises(ContractError):self.dispatch(dict(value,**changed))
        with self.assertRaises(ContractError):LocalService(self.root/'desktop-contract').restart_preparation(
            self.instance,value['operation_id'],value['state_revision'],value['attempt_id'],'another-owner',self.backend)
        self.assertEqual(len(self.calls),1)

    def test_restart_refuses_while_old_worker_holds_work_gate(self):
        accepted,_=self.interrupt_preparation();value=self.restart_value(accepted)
        with LocalService(self.root/'desktop-contract')._transaction(worker=True):
            with self.assertRaises(ContractError) as error:self.dispatch(value)
        self.assertEqual(error.exception.code,'resource-busy')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.store.snapshot()['generations'][0]['state'],'preparing')

    def test_restart_refuses_while_generation_gate_is_held(self):
        accepted,_=self.interrupt_preparation();value=self.restart_value(accepted)
        with self.store.locked():
            with self.assertRaises(ContractError) as error:self.dispatch(value)
        self.assertEqual(error.exception.code,'resource-busy')
        self.assertEqual(len(self.calls),1)

    def test_restart_refuses_committed_first_generation(self):
        self.connect();_,accepted=self.prepare();prepare=self.store.prepare_generation
        def failing(operation,expected,**kwargs):
            value=prepare(operation,expected,**kwargs);raise RuntimeError('选择代次后契约返回前中断')
        with patch.object(self.store,'prepare_generation',side_effect=failing):
            LocalService(self.root/'desktop-contract').execute(accepted['operation_id'],process_actor(),self.backend)
        self.assertEqual(self.store.snapshot()['active_generation'],1)
        self.assertIsNone(self.dispatch({'action':'overview'})['preparation'])
        with self.assertRaises(ContractError):self.dispatch(self.restart_value(accepted))
        self.assertEqual(self.store.snapshot()['active_generation'],1)

    def test_restart_refuses_any_start_effect_or_foreign_unresolved_operation(self):
        accepted,_=self.interrupt_preparation();value=self.restart_value(accepted)
        with self.store.db(write=True) as db:db.execute("INSERT INTO effects VALUES(?,?,?,'intent',NULL)",(accepted['operation_id'],'server','start'))
        with self.assertRaises(ContractError):self.dispatch(value)
        with self.store.db(write=True) as db:
            db.execute('DELETE FROM effects')  # 仅清理由本测试插入的临时数据库夹具。
            db.execute("INSERT INTO operations VALUES(?,?,?,'intent',NULL)",(str(uuid.uuid4()),'start',0))
        with self.assertRaises(ContractError):self.dispatch(value)
        self.assertEqual(len(self.calls),1)

    def test_restart_survives_interruption_after_ledger_preservation_before_contract_commit(self):
        accepted,_=self.interrupt_preparation();value=self.restart_value(accepted)
        preserve=self.backend.preserve_initial_preparation
        def fail(*args):preserve(*args);raise OSError('封存后契约提交前夹具中断')
        with patch.object(self.backend,'preserve_initial_preparation',side_effect=fail):
            with self.assertRaises(OSError):self.dispatch(value)
        self.assertEqual(self.store.snapshot()['generations'][0]['state'],'preserved')
        self.assertTrue(self.dispatch({'action':'overview'})['preparation']['restart_allowed'])
        replacement=self.dispatch(value)
        done=LocalService(self.root/'desktop-contract').execute(replacement['operation_id'],process_actor(),self.backend)
        self.assertEqual(done['state'],'prepared')
        with self.store.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM preparation_restarts').fetchone()[0],2)

    def test_restart_can_preserve_multiple_failed_candidates_without_selecting_them(self):
        accepted,_=self.interrupt_preparation();new=self.dispatch(self.restart_value(accepted))
        prepare=self.store.prepare_generation
        def fail(operation,expected,**kwargs):
            return prepare(operation,expected,checkpoint=lambda _:(_ for _ in ()).throw(RuntimeError('再次准备中断')),**kwargs)
        service=LocalService(self.root/'desktop-contract')
        with patch.object(self.store,'prepare_generation',side_effect=fail):service.execute(new['operation_id'],process_actor(),self.backend)
        third=self.dispatch(self.restart_value(new))
        self.assertEqual(service.execute(third['operation_id'],process_actor(),self.backend)['state'],'prepared')
        self.assertEqual([g['state'] for g in self.store.snapshot()['generations']],['preserved','preserved','prepared'])

    def test_new_preparation_spawn_failure_uses_existing_resume_path(self):
        accepted,_=self.interrupt_preparation();value=self.restart_value(accepted)
        def fail(*a,**k):raise OSError('新派发夹具失败')
        replacement=bridge.dispatch(self.root,value,spawn=fail,make_backend=lambda _:self.backend)
        self.assertEqual(replacement['result'],'unknown')
        current=self.dispatch({'action':'overview'})
        self.assertTrue(current['dispatch']['resume_allowed'])
        self.assertFalse(current['preparation']['restart_allowed'])
        original=self.resume_value(dict(replacement,state_revision=current['status']['state_revision']))
        self.assertEqual(self.dispatch(original)['state'],'dispatch-requested')

    def test_canceled_first_preparation_retains_cancel_receipt_and_requires_new_operation(self):
        self.connect();_,accepted=self.prepare();service=LocalService(self.root/'desktop-contract')
        req={'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),'operation':'cancel',
             'instance_uuid':self.instance,'expected_generation':accepted['generation'],
             'expected_state_revision':accepted['state_revision'],'idempotency_key':str(uuid.uuid4()),
             'parameters':{'operation_id':accepted['operation_id']}}
        self.dispatch({'action':'submit','request':req})
        canceled=service.execute(accepted['operation_id'],process_actor(),self.backend);self.assertTrue(canceled['cancelled'])
        new=self.dispatch(self.restart_value(accepted))
        self.assertEqual(service.execute(accepted['operation_id'],process_actor(),self.backend),canceled)
        self.assertNotEqual(new['operation_id'],accepted['operation_id'])
        self.assertEqual(service.execute(new['operation_id'],process_actor(),self.backend)['state'],'prepared')

    def test_concurrent_restart_requests_create_one_replacement_and_preservation_receipt(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        accepted,_=self.interrupt_preparation();value=self.restart_value(accepted);gate=Barrier(2)
        def job():
            gate.wait(timeout=5)
            try:return self.dispatch(value)
            except ContractError as exc:return {'error':exc.code}
        with ThreadPoolExecutor(max_workers=2) as workers:results=list(workers.map(lambda _:job(),range(2)))
        successful=[r for r in results if r.get('result')=='accepted']
        self.assertTrue(successful)
        self.assertEqual(len({r['operation_id'] for r in successful}),1)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM preparation_restarts').fetchone()[0],1)
        self.assertEqual(len(self.calls),2)

    def test_restart_lookup_does_not_depend_on_retained_events(self):
        accepted,_=self.interrupt_preparation();service=LocalService(self.root/'desktop-contract')
        before=self.dispatch({'action':'overview'});service.prune_events(self.instance,process_actor(),through=before['status']['cursor'])
        after=self.dispatch({'action':'overview'})
        self.assertTrue(after['preparation']['restart_allowed'])
        replacement=self.dispatch(self.restart_value(accepted))
        self.assertEqual(service.execute(replacement['operation_id'],process_actor(),self.backend)['state'],'prepared')

    def test_rearm_observer_bridge_checks_instance_generation_revision_and_node(self):
        self.connect();_,accepted=self.prepare();service=LocalService(self.root/'desktop-contract')
        service.execute(accepted['operation_id'],process_actor(),self.backend)
        view=self.dispatch({'action':'overview'})
        value={'action':'rearm-observer','instance_uuid':self.instance,'generation':view['status']['generation'],
               'state_revision':view['status']['state_revision'],'node':'server','attempt_id':str(uuid.uuid4())}
        with patch.object(self.driver,'rearm_observer',create=True,return_value={'state':'observer-ready','qemu_changed':False}) as rearm:
            self.assertEqual(self.dispatch(value)['state'],'observer-ready');rearm.assert_called_once()
            for changed in ({'instance_uuid':str(uuid.uuid4())},{'generation':2},{'state_revision':0},{'node':'outside'},{'command':'shell'}):
                with self.subTest(changed=changed),self.assertRaises(ContractError):self.dispatch(dict(value,**changed))
            self.assertEqual(rearm.call_count,1)
        self.assertEqual(self.driver.calls,[])

    def test_log_rearm_uses_current_cas_and_does_not_submit_lifecycle(self):
        self.connect();_,accepted=self.prepare();service=LocalService(self.root/'desktop-contract')
        service.execute(accepted['operation_id'],process_actor(),self.backend);self.calls.clear()
        view=self.dispatch({'action':'overview'})
        value={'action':'rearm-log','instance_uuid':self.instance,'generation':view['status']['generation'],
            'state_revision':view['status']['state_revision'],'node':'server','attempt_id':str(uuid.uuid4())}
        with patch.object(self.driver,'rearm_log',create=True,return_value={'state':'log-receiver-requested','qemu_changed':False}) as rearm:
            self.assertEqual(self.dispatch(value)['state'],'log-receiver-requested')
            for changed in ({'instance_uuid':str(uuid.uuid4())},{'generation':2},{'state_revision':0},{'node':'outside'},{'command':'shell'}):
                with self.subTest(changed=changed),self.assertRaises(ContractError):self.dispatch(dict(value,**changed))
            self.assertEqual(rearm.call_count,1)
        self.assertEqual(self.calls,[]);self.assertEqual(self.driver.calls,[])

    def test_diagnostics_excludes_root_instance_and_raw_state(self):
        self.connect()
        result=self.dispatch({'action':'diagnostics'})
        raw=json.dumps(result)
        self.assertNotIn(str(self.root),raw)
        self.assertNotIn(self.instance,raw)
        self.assertFalse(result['uploaded'])


if __name__=='__main__':unittest.main()
