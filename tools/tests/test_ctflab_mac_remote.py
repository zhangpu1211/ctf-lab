"""原Mac固定stdin桥接到生产客户端账本；假SSH/VM与临时SQLite，不连接实机。"""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if sys.platform!='win32':import ctflab
import test_ctflab_client_store as client
from ctflab_contract import canonical,MAX_MESSAGE_BYTES


@unittest.skipIf(sys.platform=='win32','原Mac CLI依赖fcntl，Windows沿现有桌面桥接')
class MacRemoteTests(unittest.TestCase):
    setUp=client.ClientTests.setUp
    configured_remote=client.ClientTests.configured_remote
    configured_lease=client.ClientTests.configured_lease
    make_manager=client.ClientTests.make_manager
    write_policy=client.ClientTests.write_policy
    request=client.ClientTests.request
    operate=client.ClientTests.operate
    def configured(self):
        client.ClientTests.configured(self)
        self.store.connect_send=lambda config,payload,**options:self.store.send(config,payload)
    def invoke(self,value,*,raw=None):
        manager=ctflab.LabManager(self.root/'mac-state');out=io.StringIO()
        with patch('ctflab_client_store.ClientStore',return_value=self.store) as factory,\
             patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(raw if raw is not None else canonical(value).encode()))),redirect_stdout(out):
            code=ctflab.cmd_remote_client(manager,SimpleNamespace())
        if code==0:factory.assert_called_once_with(manager.state_dir/'remote-client')
        return code,json.loads(out.getvalue()),factory
    def send(self):return self.invoke({'action':'request','id':self.target_id,'attempt_id':self.attempt,'payload':self.payload})
    def test_cli_has_fixed_command_without_payload_paths_or_commands_in_arguments(self):
        args=ctflab.build_parser().parse_args(['remote-client']);self.assertEqual(args.command,'remote-client')
        with self.assertRaises(SystemExit):ctflab.build_parser().parse_args(['remote-client','--command','anything'])
    def test_targets_only_reads_local_saved_metadata_and_never_connects(self):
        self.configured();count=self.sessions;code,value,_=self.invoke({'action':'targets'})
        self.assertEqual(code,0);self.assertEqual(value['targets'][0]['id'],self.target_id);self.assertEqual(self.sessions,count)
        self.assertNotIn(str(self.path),canonical(value));self.assertEqual(self.driver.calls,[])
    def test_mutation_commits_intent_and_repeated_attempt_does_not_send_twice(self):
        self.configured();code,result,_=self.send();self.assertEqual(code,0);self.assertEqual(result['client_phase'],'returned')
        count=self.sessions;again=self.send()[1];self.assertEqual(again,result);self.assertEqual(self.sessions,count)
        self.assertEqual(self.driver.calls,[])
    def test_lost_reply_remains_pending_after_reopen_until_explicit_same_attempt_retry(self):
        self.configured();self.drop='lease-acquire';result=self.send()[1];self.assertEqual(result['client_phase'],'unknown')
        expires=self.manager.pool.get(self.lease)['expires_utc'];count=self.sessions
        pending=self.invoke({'action':'pending','id':self.target_id})[1]
        self.assertEqual(pending['attempts'][0]['id'],self.attempt);self.assertEqual(self.sessions,count)
        retry=self.invoke({'action':'retry','attempt_id':self.attempt})[1];self.assertEqual(retry['client_phase'],'returned')
        self.assertEqual(self.manager.pool.get(self.lease)['expires_utc'],expires);self.assertEqual(self.driver.calls,[])
    def test_oversize_malformed_extra_root_and_unknown_action_do_not_expand_scope(self):
        self.configured()
        for raw in (b'x'*(MAX_MESSAGE_BYTES+1),b'not-json'):
            code,result,factory=self.invoke({},raw=raw);self.assertEqual(code,2);self.assertIn('error',result);factory.assert_not_called()
        code,result,_=self.invoke({'action':'targets','root':'/outside'})
        self.assertEqual(code,2);self.assertIn('error',result);self.assertEqual(self.sessions,0)
        self.assertEqual(self.driver.calls,[])
    def test_apfs_guard_refuses_before_client_action_without_stopping_anything(self):
        self.configured();manager=ctflab.LabManager(self.root/'mac-state')
        with patch.object(manager,'_storage_guard',side_effect=ctflab.CTFLabError('合成容量漂移')),\
             patch('ctflab_client_store.ClientStore') as factory,redirect_stdout(io.StringIO()) as out:
            code=ctflab.cmd_remote_client(manager,SimpleNamespace())
        self.assertEqual(code,2);factory.assert_not_called();self.assertIn('error',json.loads(out.getvalue()))
    def test_display_only_requests_fixed_worker_no_vm_lifecycle(self):
        self.configured();windows=[];self.store.display_spawn=lambda *args:windows.append(args)
        code,result,_=self.invoke({'action':'display','id':self.target_id,'instance_uuid':self.instance,'node':'client','lease_id':self.lease})
        self.assertEqual(code,0);self.assertEqual(result['state'],'display-window-requested');self.assertFalse(result['remote_connection_verified'])
        self.assertEqual(len(windows),1);self.assertEqual(self.driver.calls,[])
    def test_explicit_connect_validates_scope_and_late_cancel_does_not_stop_vm(self):
        self.configured();identity=str(uuid.uuid4())
        code,result,_=self.invoke({'action':'connect','id':self.target_id,'connection_id':identity})
        self.assertEqual(code,0);self.assertEqual(result['target'],self.fingerprint);self.assertEqual(result['result']['instances'],[self.instance])
        count=self.sessions;cancel=self.invoke({'action':'cancel-connect','id':self.target_id,'connection_id':identity})[1]
        self.assertEqual(cancel['connection_phase'],'returned');self.assertEqual(self.sessions,count);self.assertEqual(self.driver.calls,[])
    def test_cancel_before_connect_records_tombstone_and_never_opens_ssh(self):
        self.configured();identity=str(uuid.uuid4());count=self.sessions
        self.invoke({'action':'cancel-connect','id':self.target_id,'connection_id':identity})
        reply=self.invoke({'action':'connect','id':self.target_id,'connection_id':identity})[1]
        self.assertEqual(reply['connection_phase'],'cancelled');self.assertEqual(self.sessions,count);self.assertEqual(self.driver.calls,[])
    def test_native_configuration_wizard_saves_private_config_without_connecting_or_copying_key(self):
        self.configured();identity=str(uuid.uuid4());config={k:v for k,v in self.config.items() if k not in ('schema','known_hosts_sha256')}
        before=self.path.read_bytes();count=self.sessions
        code,result,_=self.invoke({'action':'create-target','id':identity,'label':'Mac课堂配置','config':config})
        self.assertEqual(code,0);self.assertEqual(self.sessions,count);self.assertEqual(self.path.read_bytes(),before)
        copied=self.store.root/'configs'/(identity+'.json');self.assertTrue(copied.is_file())
        self.assertEqual(copied.stat().st_mode&0o777,0o600)
        self.assertEqual(json.loads(copied.read_text())['identity'],self.config['identity'])
        self.assertFalse(list((self.store.root/'configs').glob('*.key')));self.assertEqual(self.driver.calls,[])


@unittest.skipIf(sys.platform=='win32','原Mac CLI使用fcntl')
class MacScenarioTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.manager=ctflab.LabManager(self.root/'state')
        self.instance=str(uuid.uuid4());self.payload={'action':'status','instance_uuid':self.instance}
    def invoke(self,value,raw=None):
        output=io.StringIO()
        with patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(raw if raw is not None else canonical(value).encode()))),redirect_stdout(output):
            code=ctflab.cmd_scenario_client(self.manager,SimpleNamespace())
        return code,json.loads(output.getvalue())
    def snapshot(self):return self.invoke(self.payload)[1]['snapshot_sha256']
    def manifest(self):
        import test_ctflab_scenario as fixture
        self.path=self.root/'scene.json';self.path.write_text(json.dumps(fixture.candidate()))
        return self.invoke({'action':'preview','instance_uuid':self.instance,'manifest':str(self.path)})
    def test_status_reads_fixed_empty_root_without_launch(self):
        code,result=self.invoke(self.payload);self.assertEqual(code,0);self.assertEqual(result['reports'],[])
        self.assertFalse((self.manager.state_dir/'scenario-state').exists())
        self.assertIn('scenario-client',ctflab.build_parser().parse_args(['scenario-client']).command)
    def test_real_preview_validates_original_manifest_without_touching_assets(self):
        code,result=self.manifest();self.assertEqual(code,0);self.assertEqual(result['state'],'design')
        self.assertFalse(result['runtime_verified']);self.assertFalse(result['isolation_verified'])
        self.assertFalse((self.manager.state_dir/'scenario-state').exists())
    def test_prepare_passes_only_fixed_root_and_explicit_bound_paths(self):
        _,preview=self.manifest();request={'action':'prepare','instance_uuid':self.instance,'manifest':str(self.path),
            'manifest_sha256':preview['manifest_sha256'],'assets':{'disk':str(self.root/'asset')},'firmware':{},'expected_sha256':self.snapshot()}
        with patch.object(ctflab,'cmd_scenario_prepare',return_value=0) as handler:
            code,result=self.invoke(request)
        self.assertEqual(code,0);ns=handler.call_args.args[1]
        self.assertEqual(ns.state_root,self.manager.state_dir/'scenario-state');self.assertIsNone(ns.socket_root)
        self.assertEqual(ns.asset,['disk='+str(self.root/'asset')]);self.assertFalse(result['automatic_replay'])
    def test_manifest_drift_or_stale_snapshot_refuses_before_handler(self):
        _,preview=self.manifest();request={'action':'prepare','instance_uuid':self.instance,'manifest':str(self.path),
            'manifest_sha256':preview['manifest_sha256'],'assets':{},'firmware':{},'expected_sha256':self.snapshot()}
        with patch.object(ctflab,'cmd_scenario_prepare',side_effect=AssertionError('不得执行')):
            self.assertEqual(self.invoke(dict(request,expected_sha256='old'))[0],2)
            self.path.write_text('{}');self.assertEqual(self.invoke(request)[0],2)
    def test_start_requires_explicit_emulation_consent(self):
        value={'action':'start','instance_uuid':self.instance,'expected_sha256':self.snapshot(),'allow_emulation':False}
        with patch.object(ctflab,'cmd_scenario_start',return_value=0) as handler:
            self.assertEqual(self.invoke(value)[0],2);handler.assert_not_called()
            self.assertEqual(self.invoke(dict(value,allow_emulation=True))[0],0);handler.assert_called_once()
    def test_extra_root_command_release_oversize_and_bad_uuid_refused(self):
        for value in (dict(self.payload,state_root='/elsewhere'),dict(self.payload,command='shell'),
                      dict(self.payload,action='release'),dict(self.payload,instance_uuid='bad')):
            self.assertEqual(self.invoke(value)[0],2)
        self.assertEqual(self.invoke({},raw=b'x'*(MAX_MESSAGE_BYTES+1))[0],2)
    def test_storage_guard_refuses_before_original_handler(self):
        from ctflab_contract import ContractError
        with patch.object(self.manager,'_storage_guard',side_effect=ContractError('identity-unknown')):
            self.assertEqual(self.invoke(self.payload)[0],2)
    def test_recover_uses_only_close_reset_without_orphan_release(self):
        with patch.object(ctflab,'cmd_scenario_recover',return_value=0) as handler:
            code,_=self.invoke({'action':'recover','instance_uuid':self.instance,'expected_sha256':self.snapshot()})
        self.assertEqual(code,0);ns=handler.call_args.args[1]
        self.assertTrue(ns.close_reset);self.assertFalse(ns.release_orphan)

@unittest.skipIf(sys.platform=='win32','原Mac CLI使用fcntl')
class MacGenericTests(unittest.TestCase):
    def setUp(self):
        import test_ctflab_darwin_driver as fixture
        fixture.DarwinDriverTests.setUp(self)
        self.build=fixture.DarwinDriverTests.build.__get__(self)
        self.action=fixture.DarwinDriverTests.action.__get__(self)
        self.build(mixed=True)
        self.manager=ctflab.LabManager(self.root/'native-state')
        self.manifest_path=self.root/'v2.json';self.manifest_path.write_text(json.dumps(self.store.config['manifest']))
        self.manifest_sha=ctflab.sha256_file(self.manifest_path)
    def invoke(self,payload,**outer):
        output=io.StringIO();value={'instance_uuid':self.instance,'payload':payload}|outer
        with patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(canonical(value).encode()))),redirect_stdout(output):
            code=ctflab.cmd_generic_client(self.manager,SimpleNamespace())
        return code,json.loads(output.getvalue())
    def configure(self):
        return self.invoke({'action':'configure','manifest':str(self.manifest_path),'manifest_sha256':self.manifest_sha,
            'assets':{k:v['path'] for k,v in self.store.config['assets'].items()},'nvram':{k:v['path'] for k,v in self.store.config['nvram'].items()},'profile':self.profile})
    def test_graph_draft_validates_diff_without_mutating_instance_and_rejects_incomplete_graph(self):
        import copy,hashlib
        self.assertEqual(self.configure()[0],0)
        root=self.manager.state_dir/'generic-instances'/self.instance
        before={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
        candidate=copy.deepcopy(self.store.config['manifest'])
        candidate['networks']['analysis-net']={'cidr':'10.90.0.0/24','uplink':'none'}
        node=copy.deepcopy(next(iter(candidate['nodes'].values())));node['depends_on']=[]
        node['interfaces']=[dict(node['interfaces'][0],id='eth0',network='analysis-net',address='10.90.0.1',mac='derived')]
        node['cpus']=2;node['memory_mb']=1024;node['depends_on']=[next(iter(candidate['nodes']))]
        candidate['nodes']['analysis']=node
        code,result=self.invoke({'action':'draft','manifest':candidate})
        self.assertEqual(code,0);self.assertFalse(result['applied']);self.assertTrue(result['requires_new_generation'])
        self.assertEqual(result['manifest'],candidate);self.assertTrue(result['changes'])
        cyclic=copy.deepcopy(candidate);cyclic['nodes'][node['depends_on'][0]]['depends_on']=['analysis']
        self.assertEqual(self.invoke({'action':'draft','manifest':cyclic})[0],2)
        candidate['nodes']['analysis']['interfaces']=[]
        self.assertEqual(self.invoke({'action':'draft','manifest':candidate})[0],2)
        after={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
        self.assertEqual(before,after);self.assertEqual(list((root/'generations').iterdir()),[])

    def test_empty_overview_and_listing_do_not_create_instance_or_launch(self):
        self.assertFalse(self.invoke({'action':'overview'})[1]['configured'])
        self.assertEqual(self.invoke({'action':'instances'})[1]['reports'],[])
        self.assertFalse((self.manager.state_dir/'generic-instances').exists())
    def test_real_v2_preview_and_configuration_bind_fixed_instance_root(self):
        code,preview=self.invoke({'action':'preview','manifest':str(self.manifest_path)})
        self.assertEqual(code,0);self.assertEqual(preview['manifest_sha256'],self.manifest_sha)
        self.assertEqual(preview['source_manifest']['nodes']['server']['interfaces'][0]['mac'],'derived')
        self.assertNotEqual(preview['plan']['manifest']['nodes']['server']['interfaces'][0]['mac'],'derived')
        self.assertEqual(self.configure()[0],0)
        from ctflab_generation_store import GenerationStore
        root=self.manager.state_dir/'generic-instances'/self.instance
        self.assertEqual(GenerationStore(root).config['instance_uuid'],self.instance)
        view=self.invoke({'action':'overview'})[1]
        self.assertTrue(view['runtime']['emulation_required']);self.assertEqual(view['generation'],0)
        self.assertEqual(self.invoke({'action':'instances'})[1]['reports'][0]['instance_uuid'],self.instance)
    def test_prepare_uses_real_ledger_and_new_nvram_without_spawning_real_worker(self):
        import ctflab_desktop_bridge as bridge
        from ctflab_local_service import LocalService
        from ctflab_local_adapter import process_actor
        self.assertEqual(self.configure()[0],0)
        req={'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),'instance_uuid':self.instance,'operation':'prepare',
             'expected_generation':None,'expected_state_revision':None,'idempotency_key':str(uuid.uuid4()),'parameters':{'course_id':'host','baseline_id':'host'}}
        with patch.object(bridge,'launch',return_value=None) as spawn:
            code,reply=self.invoke({'action':'submit','request':req})
            self.assertEqual(code,0);spawn.assert_called_once()
        root=self.manager.state_dir/'generic-instances'/self.instance
        self.assertEqual(LocalService(root/'desktop-contract').execute(reply['operation_id'],process_actor(),bridge.backend(root))['state'],'prepared')
        self.assertEqual(self.invoke({'action':'overview'})[1]['generation'],1)
        self.assertEqual(bridge.GenerationStore(root).node_paths(1,'server')['nvram'].read_bytes(),self.template.read_bytes())
    def test_fixed_root_cross_instance_unknown_command_and_source_drift_refuse(self):
        self.assertEqual(self.invoke({'action':'shell','command':'anything'})[0],2)
        self.assertEqual(self.invoke({'action':'overview'},root='/other')[0],2)
        self.manifest_path.write_text('{}');self.assertEqual(self.configure()[0],2)
        self.assertEqual(self.invoke({'action':'overview'},instance_uuid='../bad')[0],2)
    def test_interrupted_configuration_restores_missing_records_without_overwrite(self):
        self.assertEqual(self.configure()[0],0)
        root=self.manager.state_dir/'generic-instances'/self.instance
        profile=root/'runtime-profile.json';before=profile.read_bytes();profile.rename(root/'runtime-profile.retained')
        contract=root/'desktop-contract';contract.rename(root/'desktop-contract.retained')
        self.assertEqual(self.configure()[0],0)
        self.assertEqual(profile.read_bytes(),before);self.assertEqual((root/'runtime-profile.retained').read_bytes(),before)
        self.assertTrue((root/'desktop-contract.retained').is_dir())
        self.assertEqual(self.invoke({'action':'overview'})[1]['generation'],0)

    def test_configuration_never_overwrites_existing_root(self):
        self.assertEqual(self.configure()[0],0)
        root=self.manager.state_dir/'generic-instances'/self.instance
        before=(root/'runtime-profile.json').read_bytes()
        self.assertEqual(self.configure()[0],0);self.assertEqual((root/'runtime-profile.json').read_bytes(),before)
        self.profile['nodes']['server']['qmp']=25000
        self.assertEqual(self.configure()[0],2);self.assertEqual((root/'runtime-profile.json').read_bytes(),before)

    def test_log_rearm_passes_only_to_same_fixed_generic_root(self):
        import ctflab_desktop_bridge as bridge
        self.assertEqual(self.configure()[0],0)
        value={'action':'rearm-log','instance_uuid':self.instance,'generation':1,'state_revision':4,
            'node':'server','attempt_id':str(uuid.uuid4())}
        with patch.object(bridge,'dispatch',return_value={'state':'log-receiver-requested','qemu_changed':False}) as dispatch:
            code,result=self.invoke(value)
        self.assertEqual(code,0);self.assertEqual(result['state'],'log-receiver-requested')
        self.assertEqual(dispatch.call_args.args[0],self.manager.state_dir/'generic-instances'/self.instance)
        self.assertEqual(dispatch.call_args.args[1],value)

    def test_saved_operation_history_entries_are_readonly_through_generic_client(self):
        import hashlib
        import sqlite3
        from ctflab_local_service import LocalService
        self.assertEqual(self.configure()[0],0)
        root=self.manager.state_dir/'generic-instances'/self.instance
        service=LocalService(root/'desktop-contract')
        from ctflab_local_adapter import process_actor
        req={'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),'instance_uuid':self.instance,'operation':'prepare',
             'expected_generation':None,'expected_state_revision':None,'idempotency_key':str(uuid.uuid4()),
             'parameters':{'course_id':'host','baseline_id':'host'}}
        accepted=service.submit(req,process_actor())
        def tree():
            return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
        before=tree()
        code,page=self.invoke({'action':'operation-history','limit':20})
        self.assertEqual(code,0);self.assertTrue(page['historical']);self.assertFalse(page['automatic_replay'])
        self.assertEqual(page['operations'][0]['operation_id'],accepted['operation_id'])
        code,record=self.invoke({'action':'operation-result','operation_id':accepted['operation_id']})
        self.assertEqual(code,0);self.assertIsNone(record['response']);self.assertEqual(record['record']['status'],'pending')
        # 越界limit与替换主体在固定入口即拒绝；SQLite与文件树保持不变。
        self.assertEqual(self.invoke({'action':'operation-history','limit':51})[0],2)
        self.assertEqual(self.invoke({'action':'operation-history','limit':20,'actor':'other'})[0],2)
        self.assertEqual(tree(),before)
        self.assertEqual(list((root/'generations').iterdir()),[])

    def test_template_qualification_gate_reads_exact_acceptance_without_hot_change(self):
        import copy
        from ctflab_topology import canonical_digest, draft_diff
        self.assertEqual(self.configure()[0],0)
        root=self.manager.state_dir/'generic-instances'/self.instance
        before=(root/'generations').exists() and sorted(p.name for p in (root/'generations').iterdir()) or []
        candidate=copy.deepcopy(self.store.config['manifest'])
        node=next(iter(candidate['nodes']));candidate['nodes'][node]['memory_mb']=1024
        diff=draft_diff(self.store.config['manifest'],candidate,self.instance,1)
        acceptance={'schema':1,'kind':'scenario-acceptance','scenario_id':candidate['scenario_id'],
            'manifest_sha256':canonical_digest(candidate),'next_plan_sha256':diff['next_plan_sha256'],
            'next_generation':diff['next_generation'],'result':'passed',
            'evidence_ref':'scenario-acceptance-run-1','recorded_at':'2026-10-31T10:00:00+00:00'}
        code,record=self.invoke({'action':'template-qualify','manifest':candidate,'acceptance':acceptance})
        self.assertEqual(code,0);self.assertFalse(record['applied']);self.assertTrue(record['requires_new_generation'])
        self.assertFalse(record['runtime_verified']);self.assertFalse(record['automatic_replay'])
        # 摘要不匹配的验收记录与错误图均拒绝；固定入口不修改运行代次。
        stale=dict(acceptance,manifest_sha256='0'*64)
        self.assertEqual(self.invoke({'action':'template-qualify','manifest':candidate,'acceptance':stale})[0],2)
        cyclic=copy.deepcopy(candidate);first,second=list(cyclic['nodes'])[:2]
        cyclic['nodes'][first]['depends_on']=[second];cyclic['nodes'][second]['depends_on']=[first]
        self.assertEqual(self.invoke({'action':'template-qualify','manifest':cyclic,'acceptance':acceptance})[0],2)
        self.assertEqual(self.invoke({'action':'template-qualify','manifest':candidate})[0],2)
        after=(root/'generations').exists() and sorted(p.name for p in (root/'generations').iterdir()) or []
        self.assertEqual(before,after)
        # 资格门不创建代次：配置后仍为0代，概览不变。
        self.assertEqual(self.invoke({'action':'overview'})[1]['generation'],0)

if __name__=='__main__':unittest.main()
