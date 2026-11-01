"""D02点对点编译、生产命令、身份/路由漂移与持久意图；不运行宿主网络或Docker。"""
from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
from ctflab_guest_policy import compile_policy,verify_policy,firewall
from ctflab_guest_agent import GuestAgent
from ctflab_guest_routed import route_plan,interface_names,RoutedNetwork
import test_ctflab_guest_policy as policy_tests
import test_ctflab_guest_agent as agent_tests
import test_ctflab_guest_routes as endpoint_tests


def envelope():
    value=policy_tests.envelope(containers=True);value['routed']=True
    value['flows'][0]['destination']={'node':'container:web','interface':'container'}
    value['compiled']=compile_policy(value['plan'],value['node'],value['devices'],value['flows'],
        containers=value['containers'],container_cidr=value['container_cidr'],routed=True)
    return value


class RoutedPolicyTests(unittest.TestCase):
    def test_point_to_point_exact_rules_return_routes_and_no_default_or_nat(self):
        value=envelope();policy=verify_policy(value);route=route_plan(policy,'web');text=firewall(policy)
        self.assertEqual(route['remotes'],['10.80.0.10']);self.assertEqual(route['gateway'],'10.99.0.1')
        self.assertIn('oifname "'+route['host']+'" ip saddr 10.80.0.10 ip daddr 10.99.0.10',text)
        self.assertIn('tcp sport { 80, 443 } ct state established',text)
        self.assertNotIn('masquerade',text);self.assertNotIn('0.0.0.0/0',text);self.assertEqual(text.count('policy drop'),3)
        self.assertNotEqual(interface_names(policy,'web'),interface_names(dict(policy,generation=2),'web'))
        self.assertTrue(all(len(x)<=15 for x in interface_names(policy,'web')))

    def test_routed_mode_requires_explicit_boolean_and_declared_container(self):
        value=envelope()
        for routed in (False,1,'true',None):
            with self.assertRaises(ContractError):compile_policy(value['plan'],value['node'],value['devices'],value['flows'],
                containers=value['containers'],container_cidr=value['container_cidr'],routed=routed)
        for dest in ({'node':'container:other','interface':'container'},{'node':'container:web','interface':'eth0'}):
            bad=copy.deepcopy(value);bad['flows'][0]['destination']=dest
            with self.assertRaises(ContractError):compile_policy(bad['plan'],bad['node'],bad['devices'],bad['flows'],
                containers=bad['containers'],container_cidr=bad['container_cidr'],routed=True)

    def test_terminal_uses_verified_same_plan_container_owner_and_host_route(self):
        owner=envelope();value=endpoint_tests.definition();value['plan']=owner['plan']
        destination={'node':'container:web','interface':'container'}
        value['endpoint']['container_policy']=owner
        value['endpoint']['routes'][0]['destination']=destination
        value['endpoint']['flows'][0]['destination']=destination
        endpoint_tests.recompile(value)
        self.assertEqual(value['compiled']['endpoint']['routes'][0]['destination'],'10.99.0.10/32')
        self.assertEqual(verify_policy(value),value['compiled'])
        value['endpoint']['container_policy']['compiled']['containers']['web']['address']='10.99.0.11'
        with self.assertRaises(ContractError):endpoint_tests.recompile(value)

    def test_other_instance_owner_and_recursive_endpoint_owner_are_rejected(self):
        owner=envelope();value=endpoint_tests.definition();value['endpoint']['container_policy']=owner
        with self.assertRaises(ContractError):endpoint_tests.recompile(value)
        value['plan']=owner['plan'];owner['endpoint']={}
        with self.assertRaises(ContractError):endpoint_tests.recompile(value)


class CommandBackend:
    def __init__(self,policy):self.policy=policy;self.calls=[];self.rows=[];self.links=[{'ifname':'lo'}]
    def check_tool(self,tool):self.calls.append(('check',tool))
    def json(self,tool,args):
        if tool=='nft':return {'nftables':[]}
        if args==['-j','link','show']:return self.links
        return copy.deepcopy(self.rows)
    def call(self,tool,args,**kw):self.calls.append((tool,args,kw));return ''
    def guard(self):pass


class NativeRoutedTests(unittest.TestCase):
    def setUp(self):
        self.policy=envelope()['compiled'];self.backend=CommandBackend(self.policy);self.network=RoutedNetwork(self.backend,self.policy)
        self.route=route_plan(self.policy,'web')
    def host_rows(self):
        return [{'dst':n['cidr'],'dev':n['device'],'protocol':'kernel','scope':'link','prefsrc':n['address']} for n in self.policy['interfaces'].values()]
    def test_preflight_rejects_any_existing_owned_name_and_foreign_route(self):
        self.backend.rows=self.host_rows();self.network.preflight()
        self.backend.links.append({'ifname':self.route['host']})
        with self.assertRaises(ContractError):self.network.preflight()
        self.backend.links=[];self.backend.rows.append({'dst':'default','gateway':'10.80.0.1'})
        with self.assertRaises(ContractError):self.network.preflight()
        self.assertFalse(any(call[0]=='ip' for call in self.backend.calls))
    def test_later_docker_drop_and_foreign_base_hook_refuse_without_flushing(self):
        self.backend.rows=self.host_rows();original=self.backend.call
        self.backend.call=lambda tool,args,**kw:'*filter\n:FORWARD DROP [0:0]\nCOMMIT\n' if tool=='iptables-save' else original(tool,args,**kw)
        with self.assertRaises(ContractError):self.network.preflight()
        self.backend.call=original;original_json=self.backend.json
        self.backend.json=lambda tool,args:{'nftables':[{'chain':{'family':'inet','table':'foreign','name':'forward','hook':'forward'}}]} if tool=='nft' else original_json(tool,args)
        with self.assertRaises(ContractError):self.network.preflight()
        self.assertFalse(any(call[0]=='ip' for call in self.backend.calls))

    def test_host_routes_require_all_exact_no_extra_or_wrong_source(self):
        self.backend.rows=self.host_rows()
        with self.assertRaises(ContractError):self.network.host_routes(complete=True)
        self.backend.rows.append({'dst':self.route['address'],'dev':self.route['host'],'protocol':'static','scope':'link','prefsrc':self.route['gateway']})
        self.assertEqual(len(self.network.host_routes(complete=True)),1)
        self.backend.rows[-1]['prefsrc']='10.99.0.8'
        with self.assertRaises(ContractError):self.network.host_routes(complete=True)
    def test_namespace_exact_addresses_and_routes_reject_default_ipv6_extra_interface(self):
        r=self.route
        links=[{'ifname':'lo'},{'ifname':'ctf0','flags':['UP'],'addr_info':[{'family':'inet','local':r['address'],'prefixlen':32,'scope':'global'}]}]
        rows=[{'dst':r['gateway'],'dev':'ctf0','protocol':'static','scope':'link','prefsrc':r['address']},
              {'dst':r['remotes'][0],'gateway':r['gateway'],'dev':'ctf0','protocol':'static','prefsrc':r['address']}]
        self.network.ns_json=lambda fd,args:copy.deepcopy(links if args==['-j','address','show'] else [] if args[0]=='-6' else rows)
        self.network.namespace_routes(10,'web')
        rows.append({'dst':'default','gateway':r['gateway'],'dev':'ctf0','protocol':'static','prefsrc':r['address']})
        with self.assertRaises((ValueError,ContractError)):self.network.namespace_routes(10,'web')
        rows.pop();links.append({'ifname':'extra'})
        with self.assertRaises(ContractError):self.network.namespace_routes(10,'web')
    def test_attach_holds_namespace_fd_and_persists_each_step_without_pid_move(self):
        effects=[]
        @contextmanager
        def held(*a):yield 10,{'pid':123,'ticks':456,'namespace_inode':789,'namespace_device':1}
        self.network.ns_json=lambda fd,args:[{'ifname':'lo'}] if args==['-j','link','show'] else []
        self.network.namespace_routes=lambda *a:{'routes':self.route['remotes'],'address':self.route['address']}
        def effect(step,call):effects.append(step);return call()
        with patch('ctflab_guest_routed.retained_namespace',held),patch('ctflab_guest_routed.move_peer',return_value={}) as move:
            result=self.network.attach('web','a'*64,123,effect)
        self.assertEqual(result['binding']['ticks'],456);move.assert_called_once_with(self.backend,self.route['peer'],10)
        self.assertEqual(len(effects),12)
        commands=canonical(self.backend.calls)
        self.assertNotIn('default',commands);self.assertNotIn('replace',commands);self.assertNotIn('delete',commands)
        self.assertNotIn('netns',commands);self.assertIn('noprefixroute',commands)
        self.assertTrue(all(c[2].get('pass_fds')==(10,) for c in self.backend.calls if c[0]=='nsenter'))


class RoutedAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        self.value=envelope();self.backend=agent_tests.FakeBackend();original=self.backend.call
        def call(tool,args,**kw):
            if tool=='docker' and args[:2]==['container','create']:
                # 复用旧Docker替身构造其他安全字段；最终回写none网络。
                staged=list(args);i=staged.index('--network');staged[i+1]='fixture-network';staged[i+2:i+2]=['--ip','10.99.0.10']
                self.backend.objects['network','fixture-network']={'Id':'b'*64}
                original(tool,staged,**kw)
                name=staged[staged.index('--name')+1];obj=self.backend.objects['container',name]
                obj['HostConfig']['NetworkMode']='none';obj['NetworkSettings']['Networks']={'none':{'IPAddress':''}}
                return ''
            result=original(tool,args,**kw)
            if tool=='docker' and args[:2]==['container','start']:
                obj=next(v for (k,n),v in self.backend.objects.items() if k=='container' and v['Id']==args[-1]);obj['State']['Pid']=123
            return result
        self.backend.call=call;self.agent=GuestAgent(self.root/'guest',self.value,self.backend)
    def action(self,action,operation=None):
        p=self.agent.policy
        return self.agent.dispatch({'schema':1,'instance_uuid':p['instance_uuid'],'generation':p['generation'],
            'policy_sha256':p['policy_sha256'],'operation_id':operation or str(uuid.uuid4()),'action':action})
    def test_prepare_uses_none_no_docker_bridge_and_partial_route_is_unknown_no_replay(self):
        self.action('network-apply');self.action('containers-prepare')
        self.assertFalse(any(c[:3]==('docker','network','create') for c in self.backend.calls))
        operation=str(uuid.uuid4())
        class Routes:
            def __init__(inner,*a):pass
            def preflight(inner):pass
            def attach(inner,name,identity,pid,effect):
                effect('route-web-pair',lambda:None);raise OSError('fixture interrupted')
        with patch('ctflab_guest_routed.RoutedNetwork',Routes):
            with self.assertRaises(OSError):self.action('containers-start',operation)
            count=len(self.backend.calls);self.assertEqual(self.action('containers-start',operation)['state'],'unknown')
            self.assertEqual(len(self.backend.calls),count)
        self.assertTrue(any(r['operation_id']==operation for r in self.action('status')['pending']))
        self.assertFalse(any('delete' in c for c in self.backend.calls))
    def test_start_records_exact_route_proof_and_stop_refuses_drift(self):
        self.action('network-apply');self.action('containers-prepare');proof={'binding':{'pid':123},'container_id':'a'*64}
        class Routes:
            def __init__(inner,*a):pass
            def preflight(inner):pass
            def attach(inner,*a):return proof
            def inspect(inner,*a):return dict(proof,binding={'pid':999})
            def host_routes(inner,**kw):pass
        with patch('ctflab_guest_routed.RoutedNetwork',Routes):
            self.assertEqual(self.action('containers-start')['state'],'containers-running')
            with patch('ctflab_guest_agent.guarded_file',side_effect=lambda p:json.loads(Path(p).read_text())):
                response=self.action('containers-stop');self.assertEqual(response['state'],'failed')
        self.assertFalse(any(c[:3]==('docker','container','kill') for c in self.backend.calls))


if __name__=='__main__':unittest.main()
