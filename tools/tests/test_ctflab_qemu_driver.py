"""通用后端边界与持久退出；合成测试不冒充 Windows 来宾验收。"""
from dataclasses import asdict
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_ctflab_generation_store as generation_tests
from ctflab_contract import ContractError
from ctflab_generation_store import private_directory, digest
from ctflab_windows_native import ProcessIdentity
from ctflab_windows_recovery import record
import ctflab_qemu_driver as driver


class DriverTests(unittest.TestCase):
    setUp = generation_tests.GenerationTests.setUp
    context = generation_tests.GenerationTests.context
    run_action = generation_tests.GenerationTests.run_action

    def setup_driver(self):
        self.run_action('prepare')
        self.profile = {'binary': str(self.root/'qemu.exe'), 'inventory': str(self.root/'inventory.json'),
                        'networks': {'outer': 18001, 'inner': 18002},
                        'nodes': {n: {'qmp': 19000+2*i, 'vnc': 19001+2*i}
                                  for i, n in enumerate(self.manifest['nodes'])}}
        self.real = driver.QemuDriver(self.store, self.profile)
        self.plan = self.store.plan(1)
        self.paths = self.store.node_paths(1, 'server')

    def attempt(self):
        root = self.real.location(self.plan, 'server', self.paths)
        private_directory(root); attempt = root/'00000001';private_directory(attempt)
        info = self.paths['disk'].stat()
        args, name = driver.arguments(self.plan, 'server', self.paths, self.profile, attempt, {})
        record(attempt/'launch.json', {'argv':args, 'plan_sha256': self.plan['plan_sha256'], 'node': 'server',
               'runtime_profile_sha256':driver.profile_sha(self.profile),
               'disk': str(self.paths['disk']), 'disk_identity': [info.st_dev, info.st_ino],
               'binary': self.profile['binary'], 'qmp': self.profile['nodes']['server']['qmp'], 'certificates': {}, 'name': name})
        self.identity = ProcessIdentity(123,456,self.profile['binary'],'running')
        record(attempt/'binding.json', {'identity': asdict(self.identity), 'launch_sha256': digest(attempt/'launch.json')})
        return attempt

    def test_network_is_loopback_pair_and_follows_start_order(self):
        self.setup_driver()
        self.assertIn('socket,id=eth0,listen=127.0.0.1:18002', driver.network_arguments(self.plan,'server',self.profile['networks']))
        self.assertIn('socket,id=eth1,connect=127.0.0.1:18002', driver.network_arguments(self.plan,'middle',self.profile['networks']))
        args, name = driver.arguments(self.plan, 'server', self.paths, self.profile, self.root, {})
        self.assertIn('-no-user-config',args);self.assertIn('-nodefaults',args);self.assertIn('kvm' if sys.platform=='linux' else 'whpx',args)
        self.assertFalse(any(args[i+1].startswith('user') for i,v in enumerate(args[:-1]) if v == '-netdev'));self.assertNotIn('0.0.0.0',' '.join(args))
        self.assertIn('-g1-server',name)

    def test_duplicate_ports_rejected_before_launch(self):
        self.setup_driver(); self.profile['networks']['inner']=18001
        with self.assertRaises(ContractError): driver.QemuDriver(self.store,self.profile)

    def shared_network(self):
        import copy
        from ctflab_scenario_v2 import instance_plan
        self.setup_driver()
        manifest = copy.deepcopy(self.manifest)
        manifest['nodes']['client']['interfaces'].append(dict(
            id='eth1', network='inner', address='10.81.0.40', mac='derived', model='e1000'))
        self.profile['networks']['inner'] = {'middle':18002, 'client':18003}
        self.store = driver.GenerationStore.create(self.root/'多成员实例',manifest,self.instance,{'linux':self.base})
        self.backend = driver.ScenarioCoordinator(self.store,course_id='c01',baseline_id='base',driver=self.driver)
        self.run_action('prepare')
        self.plan = self.store.plan(1)
        self.real = driver.QemuDriver(self.store,self.profile)
        self.paths = self.store.node_paths(1,'server')

    def test_three_members_use_separate_loopback_links_on_first_member_hub(self):
        self.shared_network();driver.validate_profile(self.plan,self.profile)
        first = driver.network_arguments(self.plan,'server',self.profile['networks'])
        self.assertIn('socket,id=ctflab0s0,listen=127.0.0.1:18002',first)
        self.assertIn('socket,id=ctflab0s1,listen=127.0.0.1:18003',first)
        self.assertIn('hubport,id=ctflab0p0,hubid=0,netdev=ctflab0s0',first)
        self.assertIn('hubport,id=eth0,hubid=0',first)
        for node,nic,port in [('middle','eth1',18002),('client','eth1',18003)]:
            self.assertIn(f'socket,id={nic},connect=127.0.0.1:{port}',
                          driver.network_arguments(self.plan,node,self.profile['networks']))
        self.assertEqual(driver.network_ports(self.plan,self.profile['networks']),[18001,18002,18003])

    def test_multimember_requires_exact_peer_keys_and_valid_integer_ports(self):
        self.shared_network()
        for invalid in (18002,{}, {'client':18003}, {'middle':18002,'client':18003,'server':18004},
                        {'middle':True,'client':18003}, {'middle':80,'client':18003},
                        {'middle':65536,'client':18003}, {'middle':'18002','client':18003}):
            with self.subTest(invalid=invalid),self.assertRaises(ContractError):
                driver.validate_profile(self.plan,dict(self.profile,networks={'outer':18001,'inner':invalid}))

    def test_all_link_ports_participate_in_global_collision_detection(self):
        self.shared_network()
        for port in (18001,18002,self.profile['nodes']['server']['qmp'],self.profile['nodes']['client']['vnc']):
            self.profile['networks']['inner']['client']=port
            with self.subTest(port=port),self.assertRaises(ContractError):driver.validate_profile(self.plan,self.profile)

    def test_hub_ids_do_not_collide_with_interface_names_or_other_networks(self):
        self.shared_network()
        spec=self.plan['manifest']['nodes']['server']
        spec['interfaces'][0]['id']='ctflab0s0'
        spec['interfaces'].append(dict(id='eth2',network='outer',address='10.80.0.30',mac='02:00:00:00:00:fe',model='e1000'))
        self.profile['networks']['outer']={'middle':18001,'client':18004}
        args=driver.network_arguments(self.plan,'server',self.profile['networks'])
        ids=[v.split('id=',1)[1].split(',',1)[0] for k,v in zip(args,args[1:]) if k=='-netdev']
        self.assertEqual(len(ids),len(set(ids)))
        self.assertIn('hubport,id=ctflab0s0,hubid=0',args)
        self.assertIn('hubport,id=eth2,hubid=1',args)
        self.assertIn('socket,id=ctflabx0s0,listen=127.0.0.1:18002',args)

    def test_single_member_and_unused_networks_have_no_socket_backend(self):
        self.setup_driver()
        self.plan['manifest']['nodes']['middle']['interfaces']=self.plan['manifest']['nodes']['middle']['interfaces'][:1]
        self.profile['networks']['inner']={}
        self.plan['manifest']['networks']['unused']={'cidr':'10.90.0.0/24','uplink':'none'}
        self.profile['networks']['unused']={}
        driver.validate_profile(self.plan,self.profile)
        args=driver.network_arguments(self.plan,'server',self.profile['networks'])
        self.assertEqual(args,['-netdev','hubport,id=eth0,hubid=0','-device',
                              'e1000,netdev=eth0,mac='+self.plan['manifest']['nodes']['server']['interfaces'][0]['mac']])

    def test_changed_multimember_port_map_cannot_reconnect_old_launch(self):
        self.shared_network();attempt=self.attempt()
        self.profile['networks']['inner']['client']=18004
        with patch.object(driver,'QMPClient',side_effect=AssertionError('不得连接')):
            with self.assertRaises(ContractError):self.real.binding(self.plan,'server',self.paths,attempt)

    def test_agent_profile_is_opt_in_and_binds_new_generation_uuid(self):
        self.setup_driver()
        before,_=driver.arguments(self.plan,'server',self.paths,self.profile,self.root,{})
        self.assertNotIn('-uuid',before)
        self.profile['agents']={'server':{'port':21001,'devices':{'eth0':'ens3'},'flows':[],
                                          'containers':{},'container_cidr':None}}
        first,_=driver.arguments(self.plan,'server',self.paths,self.profile,self.root,{})
        second,_=driver.arguments(self.store.plan(2),'server',self.paths,self.profile,self.root,{})
        self.assertNotEqual(first[first.index('-uuid')+1],second[second.index('-uuid')+1])
        self.assertIn('name=org.ctflab.agent.0',' '.join(first))
        self.assertIn('host=127.0.0.1,port=21001',' '.join(first))

    def test_agent_port_collision_and_unknown_fields_refused(self):
        self.setup_driver()
        agent={'port':self.profile['nodes']['server']['qmp'],'devices':{'eth0':'ens3'},'flows':[],
               'containers':{},'container_cidr':None}
        self.profile['agents']={'server':agent}
        with self.assertRaises(ContractError):driver.validate_profile(self.plan,self.profile)
        agent['port']=21001;agent['command']='anything'
        with self.assertRaises(ContractError):driver.validate_profile(self.plan,self.profile)

    def test_unconfigured_guest_channel_refused_before_connect(self):
        self.setup_driver()
        with patch.object(driver,'QMPClient',side_effect=AssertionError('不得连接')):
            with self.assertRaises(ContractError):self.real.guest_agent(self.plan,'server',self.paths)

    def test_terminal_route_profile_rejects_default_route_or_arbitrary_command_fields(self):
        self.setup_driver()
        entry={'port':21001,'devices':{'eth0':'ens3'},'flows':[],'containers':{},'container_cidr':None,
               'endpoint':{'routes':[{'destination':{'node':'server','interface':'eth0'},
                                     'gateway':{'node':'middle','interface':'eth0'},'interface':'eth0'}],
                           'flows':[{'source':{'node':'client','interface':'eth0'},'destination':{'node':'server','interface':'eth0'},
                                     'protocol':'tcp','ports':[80],'reason':'课程HTTP'}]}}
        self.profile['agents']={'client':entry}
        driver.validate_profile(self.plan,self.profile)
        entry['endpoint']['routes'][0]['cidr']='0.0.0.0/0'
        with self.assertRaises(ContractError):driver.validate_profile(self.plan,self.profile)
        del entry['endpoint']['routes'][0]['cidr'];entry['command']='arbitrary'
        with self.assertRaises(ContractError):driver.validate_profile(self.plan,self.profile)

    def test_oci_archive_change_invalidates_full_runtime_binding_before_reconnect(self):
        self.setup_driver()
        self.profile['agents']={'middle':{'port':21001,'devices':{'eth0':'ens3','eth1':'ens4'},'flows':[],
            'container_cidr':'10.99.0.0/24','containers':{'web':{'image':'example/web@sha256:'+'a'*64,
                'address':'10.99.0.10','user':'1000:1000','memory_mb':256,'cpus':1,'volumes':{}}},
            'images':{'example/web@sha256:'+'a'*64:'b'*64}}}
        attempt=self.attempt();self.profile['agents']['middle']['images']['example/web@sha256:'+'a'*64]='c'*64
        with patch.object(driver,'QMPClient',side_effect=AssertionError('不得连接')):
            with self.assertRaises(ContractError):self.real.binding(self.plan,'server',self.paths,attempt)

    def test_runtime_policy_change_refused_before_guest_reconnect(self):
        self.setup_driver();self.attempt()
        self.profile['agents']={'server':{'port':21001,'devices':{'eth0':'ens3'},'flows':[],
                                          'containers':{},'container_cidr':None}}
        with patch.object(driver,'QMPClient',side_effect=AssertionError('不得连接')):
            with self.assertRaises(ContractError):self.real.guest_agent(self.plan,'server',self.paths)

    def test_unsupported_firmware_fails_closed(self):
        self.setup_driver(); self.plan['manifest']['nodes']['server']['firmware']='uefi'
        with self.assertRaises(ContractError):driver.validate_profile(self.plan,self.profile)

    def test_unstarted_generation_is_stopped(self):
        self.setup_driver()
        self.assertEqual(self.real.observe(self.plan,'server',self.paths).state,'stopped')

    def test_start_intent_without_binding_blocks_recovery(self):
        self.setup_driver();root=self.real.location(self.plan,'server',self.paths)
        private_directory(root);private_directory(root/'00000001')
        with self.assertRaises(OSError):self.real.observe(self.plan,'server',self.paths)

    def test_exit_requires_matching_native_binding(self):
        self.setup_driver();attempt=self.attempt()
        record(attempt/'observer-exit.json', {'state':'exited','identity':asdict(self.identity),'returncode':7})
        with patch.object(driver,'native_observe',side_effect=AssertionError('不得重新打开旧PID')):
            self.assertEqual(self.real.observe(self.plan,'server',self.paths).state,'stopped')

    def test_forged_exit_identity_rejected(self):
        self.setup_driver();attempt=self.attempt()
        record(attempt/'observer-exit.json', {'state':'exited','identity':{},'returncode':0})
        with self.assertRaises(ContractError):self.real.observe(self.plan,'server',self.paths)

    def test_disk_replacement_rejected(self):
        self.setup_driver();attempt=self.attempt()
        self.paths['disk'].rename(self.paths['disk'].with_suffix('.retained'))
        self.paths['disk'].write_bytes(b'replacement');self.paths['disk'].chmod(0o600)
        with self.assertRaises(ContractError):self.real.observe(self.plan,'server',self.paths)

    def test_pid_reuse_never_connects(self):
        self.setup_driver();self.attempt()
        with patch.object(driver,'native_observe',return_value=ProcessIdentity(123,999,self.profile['binary'],'running')):
            with patch.object(driver,'QMPClient',side_effect=AssertionError('不得连接')):
                with self.assertRaises(ContractError):self.real.observe(self.plan,'server',self.paths)

    def observer_session(self, attempt, operation=None, ready=True):
        import uuid
        parent=attempt/'observers'
        if not parent.exists():private_directory(parent)
        session=parent/(operation or str(uuid.uuid4()));private_directory(session)
        record(session/'intent.json',{'operation_id':session.name,'binding_sha256':digest(attempt/'binding.json'),'automatic_replay':False})
        self.observer=ProcessIdentity(444,7,'synthetic-observer','running')
        if ready:record(session/'ready.json',{'identity':asdict(self.identity),'observer':asdict(self.observer),'binding_sha256':digest(attempt/'binding.json')})
        return session

    def test_new_observer_exit_is_bound_and_does_not_reopen_pid(self):
        self.setup_driver();attempt=self.attempt();session=self.observer_session(attempt)
        record(session/'exit.json',{'state':'exited','identity':asdict(self.identity),'returncode':0,'binding_sha256':digest(attempt/'binding.json')})
        with patch.object(driver,'native_observe',side_effect=AssertionError('退出证据不重开PID')):
            self.assertEqual(self.real.observe(self.plan,'server',self.paths).state,'stopped')
        self.assertFalse((attempt/'observer-exit.json').exists())

    def test_new_observer_exit_wrong_binding_is_unknown(self):
        self.setup_driver();attempt=self.attempt();session=self.observer_session(attempt)
        record(session/'exit.json',{'state':'exited','identity':asdict(self.identity),'returncode':0,'binding_sha256':'bad'})
        with self.assertRaises(ContractError):self.real.observe(self.plan,'server',self.paths)

    def test_explicit_rearm_queries_only_and_reuses_same_attempt_without_spawn(self):
        import uuid
        self.setup_driver();attempt=self.attempt();record(attempt/'control.lock',{});commands=[];calls=[]
        class Client:
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def command(self,command):commands.append(command);return {'return':{'status':'running'}}
        def observe(pid):return self.identity if pid==self.identity.pid else self.observer
        def spawn(action,root,*,session):
            calls.append(action);target=root/'observers'/session
            self.observer=ProcessIdentity(444,7,'synthetic-observer','running')
            record(target/'ready.json',{'identity':asdict(self.identity),'observer':asdict(self.observer),'binding_sha256':digest(root/'binding.json')})
        operation=str(uuid.uuid4())
        with patch.object(driver,'native_observe',side_effect=observe),patch.object(self.real,'connection',return_value=Client()),patch.object(driver,'spawn_worker',side_effect=spawn):
            self.assertEqual(self.real.rearm_observer(self.plan,'server',self.paths,operation)['state'],'observer-ready')
            self.assertEqual(self.real.rearm_observer(self.plan,'server',self.paths,operation)['state'],'observer-ready')
            with self.assertRaises(ContractError):self.real.rearm_observer(self.plan,'server',self.paths,str(uuid.uuid4()))
        self.assertEqual(calls,['observe-exit']);self.assertEqual(set(commands),{'query-status'})
        self.assertFalse((attempt/'stop.intent.json').exists())

    def test_spawn_failure_is_preserved_without_automatic_repeat(self):
        import uuid
        self.setup_driver();attempt=self.attempt();record(attempt/'control.lock',{});operation=str(uuid.uuid4())
        with patch.object(self.real,'observe',return_value=driver.NodeObservation(self.plan['instance_uuid'],1,'server','verified','process-running')),patch.object(self.real,'supervision',return_value={'observer':'unknown'}),patch.object(driver,'spawn_worker',side_effect=OSError) as spawn:
            self.assertEqual(self.real.rearm_observer(self.plan,'server',self.paths,operation)['state'],'unknown')
            self.assertEqual(self.real.rearm_observer(self.plan,'server',self.paths,operation)['state'],'unknown')
            self.assertEqual(spawn.call_count,1)

    def test_pid_reuse_refuses_rearm_before_spawn(self):
        import uuid
        self.setup_driver();attempt=self.attempt();record(attempt/'control.lock',{})
        with patch.object(driver,'native_observe',return_value=ProcessIdentity(123,999,self.profile['binary'],'running')),patch.object(driver,'spawn_worker',side_effect=AssertionError('不得启动')):
            with self.assertRaises(ContractError):self.real.rearm_observer(self.plan,'server',self.paths,str(uuid.uuid4()))

    def test_observer_child_retains_target_and_writes_independent_exit(self):
        from contextlib import contextmanager
        import os
        self.setup_driver();attempt=self.attempt();session=self.observer_session(attempt,ready=False);held=[]
        class Native:
            @contextmanager
            def retained(_,expected):held.append(expected);yield 'kernel-handle'
            def observe(_,pid):return ProcessIdentity(pid,8,'synthetic-observer','running')
            def wait_exit(_,handle):self.assertEqual(handle,'kernel-handle');return 0
        driver.observe_exit(attempt,session.name,native=Native())
        self.assertEqual(held,[self.identity])
        self.assertEqual(driver.read(session/'exit.json')['identity'],asdict(self.identity))
        self.assertFalse((attempt/'observer-ready.json').exists())
        self.assertFalse((attempt/'observer-exit.json').exists())

    def test_observer_session_cap_and_corrupt_intent_fail_closed(self):
        self.assertEqual(driver.identity_status({'pid':123,'creation_ticks':1,'image_path':None,'state':'running'}),'unknown')
        self.setup_driver();attempt=self.attempt();session=self.observer_session(attempt)
        intent=session/'intent.json';intent.write_text('{}');intent.chmod(0o600)
        with self.assertRaises(ContractError):driver.observer_binding(attempt,session)
        for _ in range(16):self.observer_session(attempt,ready=False)
        with self.assertRaises(ContractError):driver.observer_sessions(attempt)

    def test_rearmed_worker_uses_session_log_without_overwriting_original_console(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        self.setup_driver();attempt=self.attempt();session=self.observer_session(attempt,ready=False)
        original=attempt/'observe-exit-console.log';original.write_bytes(b'old log');original.chmod(0o600)
        sink=Mock();receiver=SimpleNamespace(stdin=sink)
        with patch('ctflab_bounded_log.spawn',return_value=receiver) as logs,patch.object(driver.subprocess,'Popen',return_value=object()) as spawn:
            driver.spawn_worker('observe-exit',attempt,session=session.name)
        self.assertEqual(logs.call_args.args[0],session);self.assertEqual(original.read_bytes(),b'old log')
        self.assertIn('--observer-session',spawn.call_args.args[0]);sink.close.assert_called_once()

    def test_recoverable_log_flag_is_strict_and_windows_refuses_before_mutation(self):
        self.setup_driver()
        for flag in (1,'yes',None):
            with self.assertRaises(ContractError):driver.validate_profile(self.plan,dict(self.profile,recoverable_logs=flag))
        with patch.object(sys,'platform','win32'):
            with self.assertRaises(ContractError):driver.validate_profile(self.plan,dict(self.profile,recoverable_logs=True))

    @unittest.skipUnless(sys.platform in ('linux','darwin'),'POSIX可重接日志，Windows保持旧链')
    def test_log_rearm_native_identity_gate_does_not_need_qmp(self):
        import uuid
        import ctflab_recoverable_log as logs
        self.setup_driver();self.profile['recoverable_logs']=True
        self.real=driver.QemuDriver(self.store,self.profile);attempt=self.attempt();record(attempt/'control.lock',{})
        # 补入新启动的明确scope，再绑定相同的合成进程身份。
        spec=driver.read(attempt/'launch.json');spec.update(recoverable_logs=True,log_scope={'instance_uuid':self.instance,
            'generation':1,'node':'server','attempt':attempt.name})
        (attempt/'launch.json').write_text(__import__('json').dumps(spec));(attempt/'binding.json').write_text(__import__('json').dumps({
            'identity':asdict(self.identity),'launch_sha256':digest(attempt/'launch.json')}))
        fd=logs.initialize(attempt)
        try:
            with patch.object(driver,'native_observe',return_value=self.identity),patch.object(self.real,'connection',side_effect=AssertionError('不能依赖已堵塞QMP')),\
                 patch.object(logs,'spawn',return_value={'state':'log-receiver-requested','process':object()}) as spawned:
                result=self.real.rearm_log(self.plan,'server',self.paths,str(uuid.uuid4()))
                self.assertNotIn('process',result);self.assertFalse(result['qemu_changed']);spawned.assert_called_once()
            with patch.object(driver,'native_observe',return_value=ProcessIdentity(123,999,self.profile['binary'],'running')),\
                 patch.object(logs,'spawn',side_effect=AssertionError('不能创建接收器')):
                with self.assertRaises(ContractError):self.real.rearm_log(self.plan,'server',self.paths,str(uuid.uuid4()))
        finally:__import__('os').close(fd)
        self.assertFalse((attempt/'stop.intent.json').exists())

    def test_stop_intent_never_replayed(self):
        self.setup_driver();attempt=self.attempt();record(attempt/'control.lock',{})
        record(attempt/'stop.intent.json',{})
        with patch.object(driver,'QMPClient',side_effect=AssertionError('不得重发')):
            with self.assertRaises(ContractError):self.real.stop(self.plan,'server',self.paths)

    def test_wrong_generation_rejected(self):
        self.setup_driver();plan=dict(self.plan,generation=2)
        with self.assertRaises(ContractError):self.real.observe(plan,'server',self.paths)



class DiskBoundaryTests(unittest.TestCase):
    def test_external_backing_and_data_files_rejected(self):
        import json
        from types import SimpleNamespace
        for value in ([{'format':'qcow2','backing-filename':'outside'}],
                      [{'format':'qcow2','format-specific':{'data':{'data-file':'outside'}}}],
                      [{'format':'qcow2'},{'format':'raw'}]):
            with patch.object(driver.subprocess,'run',return_value=SimpleNamespace(stdout=json.dumps(value).encode())):
                with self.assertRaises(ContractError):driver.verify_disk('/qemu.exe','/disk')
    def test_standalone_qcow2_accepted(self):
        from types import SimpleNamespace
        with patch.object(driver.subprocess,'run',return_value=SimpleNamespace(stdout=b'[{"format":"qcow2"}]')):
            driver.verify_disk('/qemu.exe','/disk')

import os
@unittest.skipUnless(os.environ.get('CTFLAB_RECOVERY_QEMU'), '显式指定无来宾 QEMU fixture 后运行')
class QemuArgumentsTests(unittest.TestCase):
    def test_three_nodes_use_generated_arguments_and_tls(self):
        import socket
        import subprocess
        import tempfile
        import time
        import uuid
        from ctflab_scenario_v2 import instance_plan
        from test_ctflab_scenario_v2 import sample
        from ctflab_tls_endpoint import provision
        from ctflab_qmp_tls import QMPClient
        binary=Path(os.environ['CTFLAB_RECOVERY_QEMU'])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            plan=instance_plan(sample(),str(uuid.uuid4()))
            sockets=[]
            for _ in range(9):
                s=socket.socket();s.bind(('127.0.0.1',0));sockets.append(s)
            ports=[s.getsockname()[1] for s in sockets]
            profile={'binary':str(binary),'inventory':str(root/'inventory'),
                     'networks':dict(zip(('outer','inner'),ports[:2])),
                     'nodes':{n:dict(zip(('qmp','vnc'),ports[2+2*i:4+2*i])) for i,n in enumerate(plan['start_order'])}}
            profile['agents']={'middle':{'port':ports[-1],'devices':{'eth0':'ens3','eth1':'ens4'},
                                         'flows':[],'containers':{},'container_cidr':None}}
            for s in sockets:s.close()
            processes=[]
            try:
                for node in plan['start_order']:
                    attempt=root/node;private_directory(attempt)
                    disk=attempt/'disk.qcow2'
                    subprocess.run([str(binary.with_name('qemu-img')),'create','-f','qcow2',str(disk),'1M'],check=True,capture_output=True)
                    certificates=provision(attempt/'tls',plan['instance_uuid'])
                    args,name=driver.arguments(plan,node,{'disk':disk},profile,attempt,certificates)
                    # 无来宾 fixture 仅覆盖本机参数/链路/TLS，不冒充 WHPX 或 Windows 身份。
                    args[args.index('-accel')+1]='tcg';args.append('-S')
                    if '-cpu' in args:args[args.index('-cpu')+1]='max'
                    log=(attempt/'stderr.log').open('wb')
                    p=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=log)
                    processes.append((p,log))
                    deadline=time.monotonic()+8
                    while True:
                        try:
                            with QMPClient(profile['nodes'][node]['qmp'],attempt/'tls',certificates,name) as c:
                                self.assertIn('return',c.command('query-status'))
                            from ctflab_rfb_tls import RFBClient
                            display=RFBClient(profile['nodes'][node]['vnc'],attempt/'tls',certificates)
                            try:self.assertTrue(display.frame().startswith(b'P6\n'))
                            finally:display.close()
                            if node=='middle':
                                from ctflab_tls_endpoint import tcp,wrap_client
                                from ctflab_guest_policy import vm_uuid
                                self.assertEqual(args[args.index('-uuid')+1],vm_uuid(plan,node))
                                channel=wrap_client(tcp(profile['agents'][node]['port']),attempt/'tls',certificates)
                                channel.close()
                            break
                        except ConnectionRefusedError:
                            if p.poll() is not None or time.monotonic()>deadline:
                                self.fail((attempt/'stderr.log').read_text())
                            time.sleep(.05)
                self.assertTrue(all(p.poll() is None for p,_ in processes))
            finally:
                # 只回收本测试持有的空白磁盘、暂停 CPU fixture。
                for p,log in reversed(processes):
                    if p.poll() is None:p.terminate()
                    p.wait(timeout=8);log.close()

if __name__=='__main__':unittest.main()
