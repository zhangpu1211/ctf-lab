"""桌面远程目标绑定/协议白名单；真实Runner与假SSH，不连接任何主机。"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import canonical,ContractError
from ctflab_generation_store import digest
from ctflab_desktop_remote import dispatch,target
from ctflab_remote import Runner,PROTOCOL
import test_ctflab_remote as remote_tests


class DesktopRemoteTests(unittest.TestCase):
    setUp=remote_tests.RemoteTests.setUp
    setup_runner=remote_tests.RemoteTests.setup_runner
    submit=remote_tests.RemoteTests.submit
    request=remote_tests.RemoteTests.request

    def configured(self):
        self.setup_runner();self.messages=[];self.sessions=0;self.closed=0;self.leased=False
        ssh=self.root/'ssh';ssh.write_bytes(b'fixture-not-executed')
        key=self.root/'identity';key.write_text('fixture-key');key.chmod(0o600)
        known=self.root/'known_hosts';known.write_text('fixture-host');known.chmod(0o600)
        self.config={'schema':1,'host':'fixture.test','port':22,'user':'alice','ssh':str(ssh),
            'identity':str(key),'known_hosts':str(known),'known_hosts_sha256':digest(known),'server_uuid':self.server}
        self.path=self.root/'connection.json';self.path.write_text(canonical(self.config));self.path.chmod(0o600)
        self.fingerprint=target(self.path)[1]
        self.reply=lambda action,params:self.normal(action,params)
        owner=self
        class Session:
            def __init__(self,config,timeout):owner.sessions+=1;owner.assertEqual(config,owner.config);owner.assertEqual(timeout,30)
            def __enter__(self):return self
            def __exit__(self,*args):owner.closed+=1
            def request(self,action,params):
                owner.messages.append((action,copy.deepcopy(params)));return owner.reply(action,params)
        self.session=Session
    def normal(self,action,params):
        if action=='handshake':return {'state':'compatible','contract_version':1,'role':'student','resource_leases':self.leased}
        if action=='list':return {'instances':[self.instance]}
        if action=='events':return {'events':[]}
        if action=='lease-status':return {'leases':[]}
        if action=='overview':return {'instance_uuid':self.instance,'generation':1,'status':{'instance_uuid':self.instance,'state':'stopped','state_revision':3},'topology':{'nodes':[]}}
        if action=='submit':return {'instance_uuid':self.instance,'request_id':params['request']['request_id'],'state':'starting','state_revision':4,'result':'accepted'}
        raise AssertionError(action)
    def call(self,action='overview',**values):
        payload={'action':action}
        if action!='connect':payload.update(target=self.fingerprint,instance_uuid=self.instance)
        payload.update(values);return dispatch(self.path,payload,session=self.session)

    def test_admin_bridge_shape_role_capability_and_binding(self):
        self.configured();original=self.normal
        def reply(action,params):
            if action=='handshake':return dict(original(action,params),role='administrator',course_management=True,audit_management=True)
            if action=='course-preview':return {'instance_uuid':self.instance,'mapping_sha256':'a'*64}
            if action=='audit-settle':return {'attempt_id':params['attempt_id'],'original_worker_result':'unknown','vm_observed':False,'automatic_replay':False}
            return original(action,params)
        self.reply=reply
        payload={'action':'course-preview','target':self.fingerprint,'offer_id':'web','instance_uuid':self.instance}
        result=dispatch(self.path,payload,session=self.session)
        self.assertEqual(result['result']['mapping_sha256'],'a'*64)
        self.assertEqual(self.messages[-1],('course-preview',{'offer_id':'web','instance_uuid':self.instance}))
        for extra in ({'catalog':'/outside'},{'request':{}}):
            with self.assertRaises(ContractError):dispatch(self.path,payload|extra,session=self.session)
        self.reply=original
        with self.assertRaises(ContractError):dispatch(self.path,payload,session=self.session)

    def test_explicit_connect_only_handshakes_and_lists_and_never_claims_display(self):
        self.configured();result=self.call('connect')
        self.assertEqual([m[0] for m in self.messages],['handshake','list']);self.assertEqual(result['target'],self.fingerprint)
        self.assertEqual(result['result']['instances'],[self.instance]);self.assertFalse(result['result']['display_available'])
        self.assertEqual(self.sessions,self.closed)

    def test_read_actions_and_lease_status_are_fixed_and_bound(self):
        self.configured();self.call();self.call('events',after=0);self.leased=True;self.call('lease-status')
        self.assertEqual([a for a,_ in self.messages],['handshake','overview','handshake','events','handshake','lease-status'])
        self.assertTrue(all(p['instance_uuid']==self.instance for a,p in self.messages if a!='handshake'))

    def test_changed_identity_or_config_rejects_before_opening_transport(self):
        self.configured();Path(self.config['identity']).write_text('changed')
        with self.assertRaises(ContractError):self.call()
        self.assertEqual(self.sessions,0)
        self.config['user']='teacher';self.path.write_text(canonical(self.config))
        with self.assertRaises(ContractError):self.call()
        self.assertEqual(self.sessions,0)

    def test_configuration_drift_during_send_is_unknown_without_replay(self):
        self.configured();original=self.reply
        def changed(action,params):
            result=original(action,params)
            if action=='overview':Path(self.config['identity']).write_text('changed')
            return result
        self.reply=changed
        with self.assertRaises(ContractError):self.call()
        self.assertEqual([a for a,_ in self.messages].count('overview'),1);self.assertEqual(self.closed,1)

    def test_forbidden_actions_and_extra_host_paths_never_open_transport(self):
        self.configured()
        for payload in ({'action':'display'},{'action':'configure'},{'action':'shell'},
                        {'action':'connect','root':'/secret'}, {'action':'submit','target':self.fingerprint,'instance_uuid':self.instance,'request':self.submit()['parameters']['request'],'command':'stop'}):
            with self.assertRaises(ContractError):dispatch(self.path,payload,session=self.session)
        self.assertEqual(self.sessions,0)

    def test_wrong_instance_and_guest_operation_refuse_before_transport(self):
        self.configured();request=self.submit()['parameters']['request'];request['instance_uuid']=str(uuid.uuid4())
        with self.assertRaises(ContractError):self.call('submit',request=request)
        request=self.submit()['parameters']['request'];request['operation']='guest';request['parameters']={'node':'router','action':'status'}
        with self.assertRaises(ContractError):self.call('submit',request=request)
        self.assertEqual(self.sessions,0)

    def test_enabled_lease_requires_explicit_uuid_and_legacy_server_does_not(self):
        self.configured();self.leased=True;request=self.submit()['parameters']['request']
        with self.assertRaises(ContractError):self.call('submit',request=request)
        self.assertEqual([a for a,_ in self.messages],['handshake'])
        lease=str(uuid.uuid4());self.call('submit',request=request,lease_id=lease)
        self.assertEqual(self.messages[-1][1]['lease_id'],lease)
        self.leased=False;self.call('submit',request=request);self.assertNotIn('lease_id',self.messages[-1][1])

    def test_stop_does_not_require_active_lease_but_still_uses_normal_contract(self):
        self.configured();self.leased=True;request=self.submit('stop')['parameters']['request']
        self.call('submit',request=request);self.assertEqual(self.messages[-1],('submit',{'instance_uuid':self.instance,'request':request}))

    def test_wrong_nested_instance_request_and_state_revision_never_return_as_valid(self):
        self.configured();original=self.reply
        for mutation in ('instance','revision','request'):
            def wrong(action,params):
                result=original(action,params)
                if action=='submit':
                    if mutation=='instance':result['instance_uuid']=str(uuid.uuid4())
                    elif mutation=='revision':result['state_revision']=True
                    else:result['request_id']=str(uuid.uuid4())
                return result
            self.reply=wrong
            with self.assertRaises(ContractError):self.call('submit',request=self.submit()['parameters']['request'])
        self.assertEqual(self.sessions,self.closed)

    def test_handshake_mismatch_and_list_aliases_do_not_enter_resource_action(self):
        self.configured();original=self.reply
        self.reply=lambda action,params:{'state':'compatible','contract_version':True,'role':'student'} if action=='handshake' else original(action,params)
        with self.assertRaises(ContractError):self.call()
        self.assertEqual([a for a,_ in self.messages],['handshake'])
        self.reply=lambda action,params:{'instances':[self.instance,self.instance]} if action=='list' else original(action,params)
        with self.assertRaises(ContractError):self.call('connect')

    def test_invalid_cursor_and_known_hosts_change_cannot_start_ssh(self):
        self.configured()
        for after in (-1,True,'0'):
            with self.assertRaises(ContractError):self.call('events',after=after)
        Path(self.config['known_hosts']).write_text('changed')
        with self.assertRaises(ContractError):self.call('connect')
        self.assertEqual(self.sessions,0)

    def test_session_failure_is_closed_and_never_retried(self):
        self.configured()
        def fail(action,params):
            if action=='handshake':return self.normal(action,params)
            raise TimeoutError('fixture transport timeout')
        self.reply=fail
        with self.assertRaises(TimeoutError):self.call('submit',request=self.submit()['parameters']['request'])
        self.assertEqual(self.closed,1);self.assertEqual([a for a,_ in self.messages].count('submit'),1)

    def test_real_runner_owner_scope_rejection_reaches_bridge_without_local_vm_call(self):
        self.configured();self.policy['principals']['alice']['instances']=[]
        self.reply=lambda action,params:Runner(self.policy,'alice',dispatch=lambda *_:self.fail('must not dispatch')).exchange(
            {'protocol':PROTOCOL,'version':1,'server_uuid':self.server,'request_id':str(uuid.uuid4()),'action':action,'parameters':params})['result']
        with self.assertRaises(ContractError):self.call()
        self.assertEqual(self.closed,1)

    def test_cli_invalid_action_is_private_and_does_not_execute_ssh(self):
        self.configured();script=Path(__file__).resolve().parents[1]/'ctflab_desktop_remote.py'
        result=subprocess.run([sys.executable,'-I','-B',str(script),'--config',str(self.path)],input='{"action":"display"}',capture_output=True,text=True)
        self.assertEqual(result.returncode,2);self.assertNotIn(str(self.root),result.stdout)
        self.assertEqual(json.loads(result.stdout)['automatic_replay'],False)

    def test_unprepared_instance_has_no_contract_revision_and_can_be_opened(self):
        self.configured();original=self.reply
        def initial(action,params):
            result=original(action,params)
            if action=='overview':
                result['generation']=0;result['status'].update(generation=None,state_revision=None,state='unknown')
            return result
        self.reply=initial
        self.assertIsNone(self.call()['result']['status']['state_revision'])

    @unittest.skipUnless(sys.platform!='win32','使用本机POSIX管道替身')
    def test_real_ssh_session_unwraps_fixed_command_protocol_once(self):
        self.configured();binary=Path(self.config['ssh'])
        script='''import json,sys
for raw in sys.stdin:
 value=json.loads(raw)
 if value['action']=='handshake':result={'state':'compatible','contract_version':1,'role':'student','resource_leases':False}
 elif value['action']=='list':result={'instances':[INSTANCE]}
 else:raise SystemExit(2)
 print(json.dumps({'protocol':value['protocol'],'version':1,'server_uuid':value['server_uuid'],'request_id':value['request_id'],'result':result}),flush=True)
'''.replace('INSTANCE',repr(self.instance))
        binary.write_text('#!'+sys.executable+'\n'+script);binary.chmod(0o700)
        result=dispatch(self.path,{'action':'connect'})
        self.assertEqual(result['result']['instances'],[self.instance]);self.assertFalse(result['result']['resource_leases'])


if __name__=='__main__':unittest.main()
