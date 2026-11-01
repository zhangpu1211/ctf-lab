"""临时SQLite及模拟来宾后端；不会执行Docker、nftables或systemd。"""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical,require
from ctflab_guest_agent import GuestAgent,NativeBackend,serve
from test_ctflab_guest_policy import envelope


class FakeBackend:
    def __init__(self,objects=None):
        self.calls=[];self.objects={} if objects is None else objects;self.fail=None
        self.rules='a'*64
        self.services={u:{'state':'inactive','pid':0} for u in ('ctflab-dns.service','ctflab-time.service')}
    def guard(self):pass
    def network_preflight(self):
        self.calls.append(('preflight',))
        if self.fail=='preflight':raise OSError('合成预检失败')
    def docker_find(self,kind,name):return copy.deepcopy(self.objects.get((kind,name)))
    def network_fingerprint(self):
        if self.rules is None:raise ContractError('state-conflict')
        return self.rules
    def service(self,unit,action='status'):
        self.calls.append(('service',unit,action))
        if action=='start':self.services[unit]={'state':'active','pid':42}
        if action=='stop':self.services[unit]={'state':'inactive','pid':0}
        return self.services[unit]
    def json(self,tool,args):
        self.calls.append((tool,*args))
        if args[:2]==['image','inspect']:return [{'RepoDigests':[args[2]]}]
        raise AssertionError(args)
    def call(self,tool,args,**kwargs):
        self.calls.append((tool,*args))
        if self.fail and self.fail in args:raise OSError('合成副作用中断')
        if tool!='docker':return ''
        labels=dict(args[i+1].split('=',1) for i,a in enumerate(args[:-1]) if a=='--label')
        if args[:2]==['network','create']:
            self.objects['network',args[-1]]={'Id':hashlib.sha256(args[-1].encode()).hexdigest(),'Labels':labels,'Internal':True,'EnableIPv6':False,'Driver':'bridge',
                                            'Options':{'com.docker.network.bridge.name':args[args.index('--opt')+1].split('=',1)[1]},
                                            'IPAM':{'Config':[{'Subnet':args[args.index('--subnet')+1]}]}}
        elif args[:2]==['volume','create']:self.objects['volume',args[-1]]={'Labels':labels,'CreatedAt':'2026-10-26T00:00:00Z','Driver':'local','Options':None,'data':'initial'}
        elif args[:2]==['container','create']:
            name=args[args.index('--name')+1]
            mounts=[]
            for i,a in enumerate(args[:-1]):
                if a=='--mount':
                    value=dict(p.split('=',1) for p in args[i+1].split(','))
                    mounts.append({'Type':value['type'],'Name':value['source'],'Destination':value['target']})
            self.objects['container',name]={'Id':hashlib.sha256(name.encode()).hexdigest(),
                'Config':{'Labels':labels,'Image':args[-1],'User':args[args.index('--user')+1]},
                'HostConfig':{'ReadonlyRootfs':True,'Privileged':False,'CapDrop':['ALL'],
                              'SecurityOpt':['no-new-privileges'],'NetworkMode':args[args.index('--network')+1],
                              'Memory':int(args[args.index('--memory')+1][:-1])*1024**2,
                              'MemorySwap':int(args[args.index('--memory-swap')+1][:-1])*1024**2,
                              'NanoCpus':int(args[args.index('--cpus')+1])*10**9,'PidsLimit':128,
                              'RestartPolicy':{'Name':'no'},'LogConfig':{'Type':'local','Config':{'max-size':'4m','max-file':'2'}},
                              'Tmpfs':{'/tmp':'rw,noexec,nosuid,size=64m'}},
                'Mounts':mounts,'State':{'Running':False},
                'NetworkSettings':{'Networks':{args[args.index('--network')+1]:{
                    'NetworkID':self.objects['network',args[args.index('--network')+1]]['Id'],
                    'IPAMConfig':{'IPv4Address':args[args.index('--ip')+1]},'IPAddress':''}}}}
        elif args[:2] in (['container','start'],['container','kill']):
            value=next(v for (kind,n),v in self.objects.items() if kind=='container' and v['Id']==args[-1])
            value['State']['Running']=args[1]=='start'
        else:raise AssertionError(args)
        return ''


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.definition=envelope(containers=True)
        self.backend=FakeBackend();self.agent=GuestAgent(self.root/'guest',self.definition,self.backend)
    def request(self,action,operation=None):
        p=self.agent.policy
        return {'schema':1,'instance_uuid':p['instance_uuid'],'generation':p['generation'],
                'policy_sha256':p['policy_sha256'],'operation_id':operation or str(uuid.uuid4()),'action':action}
    def run_action(self,action):return self.agent.dispatch(self.request(action))
    def prepared(self):
        self.run_action('network-apply');self.run_action('containers-prepare')

    def test_network_and_services_are_explicit_and_never_mark_service_verified(self):
        value=self.run_action('network-apply');self.assertEqual(value['state'],'network-configured')
        self.assertFalse(value['network_verified']);self.assertFalse(value['services_started'])
        self.assertEqual(self.run_action('services-start')['state'],'services-running')
        self.assertEqual(self.run_action('services-stop')['state'],'services-stopped')
        self.assertTrue((self.agent.root/'dnsmasq.conf').exists())

    def test_prepare_start_stop_pins_image_and_never_uses_forced_stop(self):
        self.prepared();self.assertEqual(self.run_action('containers-start')['state'],'containers-running')
        self.assertEqual(self.run_action('containers-stop')['state'],'containers-stopped')
        commands=[c for c in self.backend.calls if c[0]=='docker']
        create=next(c for c in commands if c[1:3]==('container','create'))
        for flag in ('--pull=never','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges'):self.assertIn(flag,create)
        self.assertFalse(any(c[1:3]==('container','stop') for c in commands))
        signals=[c for c in commands if c[1:3]==('container','kill')]
        self.assertEqual(len(signals),1);self.assertIn('--signal=SIGTERM',signals[0])
        self.assertFalse(any('--privileged' in c or '--network=host' in c for c in commands))

    def test_reboot_or_changed_live_rules_refuses_service_and_container_effects(self):
        self.prepared()
        for rules in (None,'b'*64):
            self.backend.rules=rules
            for action in ('services-start','containers-start'):
                before=len(self.backend.calls)
                result=self.run_action(action)
                self.assertEqual(result['state'],'failed');self.assertFalse(result['effects_started'])
                self.assertEqual(len(self.backend.calls),before)

    def test_identical_configs_survive_reapply_but_changed_config_is_never_overwritten(self):
        self.run_action('network-apply')
        self.assertEqual(self.run_action('network-apply')['state'],'network-configured')
        original=self.agent.root/'dnsmasq.conf';original.write_text('changed')
        with self.assertRaises(ContractError):self.run_action('network-apply')
        self.assertEqual(original.read_text(),'changed')

    def test_duplicate_operation_returns_record_without_side_effects(self):
        req=self.request('network-apply');first=self.agent.dispatch(req);before=len(self.backend.calls)
        self.assertEqual(self.agent.dispatch(req),first);self.assertEqual(len(self.backend.calls),before)
        req['action']='containers-start'
        with self.assertRaises(ContractError):self.agent.dispatch(req)

    def test_partial_failure_and_lost_result_are_never_replayed(self):
        self.backend.fail='replace';req=self.request('network-apply')
        with self.assertRaises(OSError):self.agent.dispatch(req)
        before=len(self.backend.calls)
        self.assertEqual(self.agent.dispatch(req)['state'],'unknown');self.assertEqual(len(self.backend.calls),before)
        self.assertTrue(self.run_action('status')['pending'])
        with self.assertRaises(ContractError):self.run_action('containers-prepare')
        req['action']='operation-status'
        self.assertEqual(self.agent.dispatch(req)['state'],'unknown')

    def test_preflight_failure_records_no_effects_and_allows_new_request(self):
        self.backend.fail='preflight';value=self.run_action('network-apply')
        self.assertEqual(value['state'],'failed');self.assertFalse(value['effects_started'])
        self.assertEqual(self.run_action('status')['pending'],[])
        self.backend.fail=None;self.assertEqual(self.run_action('network-apply')['state'],'network-configured')

    def test_cross_generation_and_unknown_action_refused_before_backend(self):
        req=self.request('network-apply');req['generation']+=1
        with self.assertRaises(ContractError):self.agent.dispatch(req)
        req=self.request('shell')
        with self.assertRaises(ContractError):self.agent.dispatch(req)
        self.assertEqual(self.backend.calls,[])

    def test_foreign_or_privileged_container_refuses_all_stop_signals(self):
        self.prepared();self.run_action('containers-start')
        key=next(k for k in self.backend.objects if k[0]=='container')
        self.backend.objects[key]['HostConfig']['Privileged']=True
        before=len(self.backend.calls);result=self.run_action('containers-stop')
        self.assertEqual(result['state'],'failed')
        self.assertFalse(any('kill' in c for c in self.backend.calls[before:]))

    def test_new_generation_resources_do_not_replace_old_volume(self):
        self.prepared();key=next(k for k in self.backend.objects if k[0]=='volume')
        self.backend.objects[key]['data']='saved-progress'
        next_definition=envelope(self.definition['plan']['instance_uuid'],2,containers=True)
        other=GuestAgent(self.root/'next-generation',next_definition,self.backend)
        for action in ('network-apply','containers-prepare'):
            p=other.policy
            other.dispatch({'schema':1,'instance_uuid':p['instance_uuid'],'generation':p['generation'],
                            'policy_sha256':p['policy_sha256'],'operation_id':str(uuid.uuid4()),'action':action})
        self.assertEqual(self.backend.objects[key]['data'],'saved-progress')
        self.assertEqual(sum(k[0]=='volume' for k in self.backend.objects),2)

    def test_stream_duplicate_keys_and_oversize_refused(self):
        output=io.BytesIO();serve(self.agent,io.BytesIO(b'{"action":"status","action":"shell"}\n'),output)
        self.assertEqual(json.loads(output.getvalue())['result']['state'],'unknown')
        output=io.BytesIO();self.assertEqual(serve(self.agent,io.BytesIO(b'x'*70000+b'\n'),output),2)
        self.assertEqual(output.getvalue(),b'')

    def test_non_linux_backend_never_calls_system_tools(self):
        with patch('ctflab_guest_agent.platform.system',return_value='Darwin'),patch('ctflab_guest_agent.subprocess.run',side_effect=AssertionError('不得执行')):
            with self.assertRaises(ContractError):NativeBackend(self.agent.policy)

    def test_native_network_snapshot_ignores_counters_but_rejects_rule_or_interface_drift(self):
        native=NativeBackend.__new__(NativeBackend);native.policy=self.agent.policy
        table='ctflab_'+native.policy['instance_uuid'].replace('-','')[:12]+'_g1'
        rules={'nftables':[{'metainfo':{'version':'fixture'}},{'table':{'family':'inet','name':table,'handle':1}},
                         {'rule':{'expr':[{'counter':{'packets':1,'bytes':2}},{'drop':None}],'handle':2}}]}
        override={};switch={'value':'1'}
        def query(tool,args):
            if tool=='nft':return rules
            if 'route' in args:return []
            nic=next(n for n in native.policy['interfaces'].values() if n['device']==args[-1])
            return [{'address':nic['mac'],'flags':['UP'],'addr_info':[{'family':'inet','local':nic['address'],
                        'prefixlen':24}],**override}]
        native.json=query;native.call=lambda *a,**k:switch['value']
        expected=native.network_fingerprint()
        rules['nftables'][1]['table']['handle']=99
        rules['nftables'][2]['rule']['expr'][0]['counter']['packets']=1000
        self.assertEqual(native.network_fingerprint(),expected)
        rules['nftables'][2]['rule']['expr'][1]={'accept':None}
        self.assertNotEqual(native.network_fingerprint(),expected)
        override['flags']=[]
        with self.assertRaises(ContractError):native.network_fingerprint()
        override.clear();switch['value']='0'
        with self.assertRaises(ContractError):native.network_fingerprint()

    def lost_network(self):
        request=self.request('network-apply');original=self.agent.network_apply
        def lost(operation):original(operation);raise OSError('合成网络完成后结果丢失')
        with patch.object(self.agent,'network_apply',side_effect=lost):
            with self.assertRaises(OSError):self.agent.dispatch(request)
        return request

    def test_explicit_reconcile_records_complete_network_without_replaying_tools(self):
        request=self.lost_network();count=len(self.backend.calls)
        result=self.agent.reconcile_network(request['operation_id'])
        self.assertTrue(result['reconciled']);self.assertFalse(result['network_verified'])
        self.assertEqual(len(self.backend.calls),count)
        self.assertTrue(self.agent.dispatch(request)['reconciled']);self.assertEqual(len(self.backend.calls),count)
        self.assertEqual(self.run_action('services-start')['state'],'services-running')

    def test_reconcile_handles_only_proof_effect_result_gap_and_reports_step_states(self):
        request=self.request('network-apply');original=self.agent.effect
        def lost(operation,step,call):
            if step!='network-proof':return original(operation,step,call)
            with self.agent.db() as db:db.execute('INSERT INTO effects VALUES(?,?,NULL)',(operation,step))
            call();raise OSError('合成证明文件已写、效果结果未提交')
        with patch.object(self.agent,'effect',side_effect=lost):
            with self.assertRaises(OSError):self.agent.dispatch(request)
        query=dict(request,action='operation-status')
        self.assertIn({'step':'network-proof','state':'unknown'},self.agent.dispatch(query)['effects'])
        count=len(self.backend.calls);self.agent.reconcile_network(request['operation_id'])
        self.assertEqual(len(self.backend.calls),count)
        self.assertTrue(all(e['state']=='recorded' for e in self.agent.dispatch(query)['effects']))

    def test_reconcile_refuses_live_drift_changed_config_or_legacy_proof(self):
        request=self.lost_network();self.backend.rules='b'*64
        with self.assertRaises(ContractError):self.agent.reconcile_network(request['operation_id'])
        self.backend.rules='a'*64
        config=self.agent.root/'dnsmasq.conf';original=config.read_text();config.write_text('changed')
        with self.assertRaises(ContractError):self.agent.reconcile_network(request['operation_id'])
        config.write_text(original)
        proof=self.agent.root/('network-proof-'+request['operation_id']+'.json');value=json.loads(proof.read_text());value.pop('operation_id');proof.write_text(canonical(value))
        with self.assertRaises(ContractError):self.agent.reconcile_network(request['operation_id'])
        self.assertEqual(self.agent.dispatch(dict(request,action='operation-status'))['state'],'unknown')

    def test_reconcile_cannot_adopt_old_proof_or_partial_configuration(self):
        self.run_action('network-apply');request=self.request('network-apply');self.backend.fail='address'
        with self.assertRaises(OSError):self.agent.dispatch(request)
        count=len(self.backend.calls)
        with self.assertRaises(ContractError):self.agent.reconcile_network(request['operation_id'])
        self.assertEqual(len(self.backend.calls),count)


class PreparationRecoveryTests(unittest.TestCase):
    setUp=AgentTests.setUp
    request=AgentTests.request
    run_action=AgentTests.run_action

    def partial(self,kind='volume',*,after=True):
        from unittest.mock import patch
        self.run_action('network-apply');request=self.request('containers-prepare');original=self.backend.call
        def failed(tool,args,**kwargs):
            if tool=='docker' and args[:2]==[kind,'create']:
                if after:original(tool,args,**kwargs)
                raise OSError('合成创建结果丢失')
            return original(tool,args,**kwargs)
        with patch.object(self.backend,'call',side_effect=failed):
            with self.assertRaises(OSError):self.agent.dispatch(request)
        return request['operation_id']

    def writes(self):
        return [c for c in self.backend.calls if len(c)>2 and c[0]=='docker' and c[2] in ('create','start','kill','rm','remove','load')]

    def test_lost_volume_reply_adopted_without_recreation_or_progress_loss(self):
        operation=self.partial();volume=self.backend.objects['volume',self.agent.prefix+'-web-data'];volume['data']='saved-progress'
        before=len(self.writes());snapshot=self.agent.inspect_preparation(operation)
        self.assertEqual(len(self.writes()),before);self.assertTrue(snapshot['can_resume'])
        self.assertEqual([r['state'] for r in snapshot['steps']],['recorded','observed-unrecorded','not-started'])
        result=self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        self.assertEqual(result['state'],'containers-prepared');self.assertFalse(result['services_started'])
        self.assertEqual(volume['data'],'saved-progress');self.assertEqual(len(self.writes())-before,1)
        self.assertEqual(self.writes()[-1][1:3],('container','create'))
        count=len(self.writes());again=self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        self.assertTrue(again['historical_result']);self.assertEqual(len(self.writes()),count)

    def test_unknown_network_observed_and_original_id_retained(self):
        operation=self.partial('network');snapshot=self.agent.inspect_preparation(operation)
        self.assertEqual(snapshot['steps'][0]['state'],'observed-unrecorded')
        self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        self.assertEqual(sum(c[1:3]==('network','create') for c in self.writes()),1)
        with self.agent.db() as db:
            row=db.execute('SELECT result FROM operations WHERE id=?',(operation,)).fetchone()
            self.assertEqual(json.loads(row[0])['state'],'containers-prepared')

    def test_unknown_absent_network_is_never_recreated(self):
        operation=self.partial('network',after=False);snapshot=self.agent.inspect_preparation(operation)
        self.assertFalse(snapshot['can_resume']);self.assertEqual(snapshot['steps'][0]['state'],'unknown-absent')
        count=len(self.writes())
        with self.assertRaises(ContractError):self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        self.assertEqual(len(self.writes()),count);self.assertFalse(self.backend.objects)

    def test_missing_recorded_network_does_not_recreate_or_delete_volume(self):
        operation=self.partial();del self.backend.objects['network',self.agent.prefix+'-network']
        snapshot=self.agent.inspect_preparation(operation);self.assertFalse(snapshot['can_resume'])
        self.assertEqual(snapshot['steps'][0]['state'],'recorded-missing');count=len(self.writes())
        with self.assertRaises(ContractError):self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        self.assertEqual(len(self.writes()),count);self.assertIn(('volume',self.agent.prefix+'-web-data'),self.backend.objects)

    def test_changed_recorded_network_id_and_foreign_operation_label_refused(self):
        operation=self.partial();network=self.backend.objects['network',self.agent.prefix+'-network'];old=network['Id']
        network['Id']='f'*64;count=len(self.writes())
        with self.assertRaises(ContractError):self.agent.inspect_preparation(operation)
        network['Id']=old;network['Labels']['org.ctflab.prepare']=str(uuid.uuid4())
        with self.assertRaises(ContractError):self.agent.inspect_preparation(operation)
        self.assertEqual(len(self.writes()),count)

    def test_stale_snapshot_cannot_resume_after_journal_state_changes(self):
        operation=self.partial();snapshot=self.agent.inspect_preparation(operation)
        identity=snapshot['steps'][1]['resource']
        with self.agent.db() as db:db.execute('UPDATE effects SET result=? WHERE operation=? AND step=?',
            (canonical(identity),operation,'volume-web-data'))
        count=len(self.writes())
        with self.assertRaises(ContractError):self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        self.assertEqual(len(self.writes()),count)

    def test_crash_during_resume_remains_unknown_until_new_explicit_snapshot(self):
        from unittest.mock import patch
        operation=self.partial();snapshot=self.agent.inspect_preparation(operation);original=self.backend.call
        def failed(tool,args,**kwargs):
            result=original(tool,args,**kwargs)
            if tool=='docker' and args[:2]==['container','create']:raise OSError('合成恢复时丢回复')
            return result
        with patch.object(self.backend,'call',side_effect=failed):
            with self.assertRaises(OSError):self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        count=len(self.writes());fresh=self.agent.inspect_preparation(operation)
        self.assertEqual(fresh['steps'][-1]['state'],'observed-unrecorded')
        self.agent.resume_preparation(operation,fresh['resume_sha256']);self.assertEqual(len(self.writes()),count)

    def test_running_container_is_not_stopped_or_adopted(self):
        operation=self.partial('container');value=self.backend.objects['container',self.agent.prefix+'-web'];value['State']['Running']=True
        count=len(self.writes())
        with self.assertRaises(ContractError):self.agent.inspect_preparation(operation)
        self.assertTrue(value['State']['Running']);self.assertEqual(len(self.writes()),count)

    def test_fully_prepared_lost_final_result_settles_without_commands(self):
        from unittest.mock import patch
        self.run_action('network-apply');request=self.request('containers-prepare');original=self.agent.container_prepare
        def failed(operation):original(operation);raise OSError('合成末尾结果丢失')
        with patch.object(self.agent,'container_prepare',side_effect=failed):
            with self.assertRaises(OSError):self.agent.dispatch(request)
        operation=request['operation_id'];snapshot=self.agent.inspect_preparation(operation)
        self.assertEqual({r['state'] for r in snapshot['steps']},{'recorded'});count=len(self.writes())
        self.agent.resume_preparation(operation,snapshot['resume_sha256']);self.assertEqual(len(self.writes()),count)

    def test_changed_rules_and_legacy_unpinned_records_refused(self):
        operation=self.partial();self.backend.rules='b'*64
        with self.assertRaises(ContractError):self.agent.inspect_preparation(operation)
        self.backend.rules='a'*64
        with self.agent.db() as db:db.execute('UPDATE effects SET result=? WHERE operation=? AND step=?',
            (canonical('legacy-unpinned-output'),operation,'network'))
        count=len(self.writes())
        with self.assertRaises(ContractError):self.agent.inspect_preparation(operation)
        self.assertEqual(len(self.writes()),count)

    def test_extra_network_and_changed_static_address_are_not_adopted(self):
        operation=self.partial('container');value=self.backend.objects['container',self.agent.prefix+'-web']
        networks=value['NetworkSettings']['Networks'];original=copy.deepcopy(networks)
        networks['foreign']={};count=len(self.writes())
        with self.assertRaises(ContractError):self.agent.inspect_preparation(operation)
        networks.clear();networks.update(original)
        networks[self.agent.prefix+'-network']['IPAMConfig']['IPv4Address']='10.99.0.11'
        with self.assertRaises(ContractError):self.agent.inspect_preparation(operation)
        self.assertEqual(len(self.writes()),count)

    def test_recreated_volume_and_extra_network_block_start_before_any_signal(self):
        self.run_action('network-apply');self.run_action('containers-prepare')
        volume=self.backend.objects['volume',self.agent.prefix+'-web-data'];old=volume['CreatedAt']
        volume['CreatedAt']='2026-10-26T00:00:01Z';count=len(self.writes())
        result=self.run_action('containers-start');self.assertEqual(result['state'],'failed')
        volume['CreatedAt']=old
        self.backend.objects['container',self.agent.prefix+'-web']['NetworkSettings']['Networks']['foreign']={}
        self.assertEqual(self.run_action('containers-start')['state'],'failed')
        self.assertEqual(len(self.writes()),count)

    def test_removing_prepare_label_cannot_downgrade_pinned_container_to_legacy(self):
        self.run_action('network-apply');self.run_action('containers-prepare')
        value=self.backend.objects['container',self.agent.prefix+'-web']
        del value['Config']['Labels']['org.ctflab.prepare'];count=len(self.writes())
        self.assertEqual(self.run_action('containers-start')['state'],'failed')
        self.assertEqual(len(self.writes()),count)

    def test_inspection_obeys_existing_guest_exclusive_gate(self):
        operation=self.partial();count=len(self.writes())
        with self.agent.locked():
            with self.assertRaises(OSError):self.agent.inspect_preparation(operation)
        self.assertEqual(len(self.writes()),count)


if __name__=='__main__':unittest.main()
