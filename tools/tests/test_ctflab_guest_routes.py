"""终端窄路由、定向访问、实际状态漂移与副作用顺序；不配置宿主网络。"""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
from ctflab_guest_policy import compile_policy,verify_policy,firewall
from ctflab_guest_routes import route_snapshot
from ctflab_guest_agent import NativeBackend,GuestAgent
import test_ctflab_guest_policy as policy_tests
import test_ctflab_guest_agent as agent_tests


def definition(node='client'):
    value=policy_tests.envelope()
    value['node']=node;value['devices']={'eth0':'ens3'};value['flows']=[]
    remote='server' if node=='client' else 'client'
    value['endpoint']={'routes':[{'destination':{'node':remote,'interface':'eth0'},
                         'gateway':{'node':'middle','interface':'eth0' if node=='client' else 'eth1'},'interface':'eth0'}],
                       'flows':[{'source':{'node':'client','interface':'eth0'},
                                 'destination':{'node':'server','interface':'eth0'},
                                 'protocol':'tcp','ports':[80],'reason':'课程HTTP访问'}]}
    recompile(value);return value


def recompile(value):
    value['compiled']=compile_policy(value['plan'],value['node'],value['devices'],value['flows'],
                containers=value['containers'],container_cidr=value['container_cidr'],endpoint=value['endpoint'])


def rows_for(policy):
    result=[{'dst':nic['cidr'],'dev':nic['device'],'protocol':'kernel','scope':'link','prefsrc':nic['address'],'flags':[]}
            for nic in policy['interfaces'].values()]
    result.extend({'dst':r['destination'].split('/')[0],'gateway':r['gateway'],'dev':r['device'],
                   'protocol':'static','prefsrc':r['source'],'flags':[]} for r in policy['endpoint']['routes'])
    return result


class RoutePolicyTests(unittest.TestCase):
    def test_client_server_have_exact_inverse_routes_and_stateful_endpoint_rules(self):
        client=definition();server=definition('server')
        route=client['compiled']['endpoint']['routes'][0]
        self.assertEqual(route,{'destination':'10.81.0.30/32','gateway':'10.80.0.20','device':'ens3','source':'10.80.0.10'})
        self.assertEqual(server['compiled']['endpoint']['routes'][0]['destination'],'10.80.0.10/32')
        for policy in (client,server):
            self.assertEqual(verify_policy(policy),policy['compiled'])
            text=firewall(policy['compiled'])
            self.assertIn('tcp dport { 80 } ct state new,established',text)
            self.assertIn('tcp sport { 80 } ct state established',text)
            self.assertNotIn('masquerade',text);self.assertNotIn('0.0.0.0/0',text)
            self.assertFalse(policy['compiled']['endpoint']['forwarding'])
        self.assertIn('output oifname "ens3" ip saddr 10.80.0.10 ip daddr 10.81.0.30',firewall(client['compiled']))
        self.assertIn('input iifname "ens3" ip saddr 10.80.0.10 ip daddr 10.81.0.30',firewall(server['compiled']))

    def test_missing_route_wrong_gateway_and_arbitrary_route_fields_refused(self):
        value=definition();value['endpoint']['routes']=[]
        with self.assertRaises(ContractError):recompile(value)
        for change in ({'gateway':{'node':'server','interface':'eth0'}},
                       {'destination':{'node':'internet','interface':'eth0'}},{'cidr':'0.0.0.0/0'}):
            value=definition();value['endpoint']['routes'][0].update(change)
            with self.assertRaises(ContractError):recompile(value)

    def test_direct_dns_flow_needs_no_route_and_no_arbitrary_service_port_is_opened(self):
        value=definition();value['endpoint']['routes']=[]
        value['endpoint']['flows'][0].update(destination={'node':'middle','interface':'eth0'},protocol='udp',ports=[53])
        recompile(value);text=firewall(value['compiled'])
        self.assertIn('ip daddr 10.80.0.20 udp dport { 53 }',text)
        self.assertNotIn('tcp dport { 80 }',text)

    def test_duplicate_rules_container_mixing_and_explicit_null_are_refused(self):
        value=definition();value['endpoint']['flows']*=2
        with self.assertRaises(ContractError):recompile(value)
        value=definition();value['flows']=policy_tests.envelope()['flows']
        with self.assertRaises(ContractError):recompile(value)
        value=definition();value['endpoint']=None
        with self.assertRaises(ContractError):verify_policy(value)
        old=policy_tests.envelope();old['images']=None
        with self.assertRaises(ContractError):verify_policy(old)

    def test_native_snapshot_requires_exact_routes_and_rejects_extra_routes(self):
        policy=definition()['compiled'];rows=rows_for(policy)
        self.assertEqual(len(route_snapshot(rows,policy,complete=True)),1)
        self.assertEqual(route_snapshot(rows[:1],policy,complete=False),[])
        with self.assertRaises(ContractError):route_snapshot(rows[:1],policy,complete=True)
        for change in ({'gateway':'10.80.0.99'},{'dst':'default'},{'protocol':'boot'},
                       {'multipath':[]},{'flags':['onlink']},{'prefsrc':'10.80.0.99'}):
            changed=copy.deepcopy(rows);changed[1].update(change)
            with self.assertRaises(ContractError):route_snapshot(changed,policy,complete=True)
        with self.assertRaises(ContractError):route_snapshot(rows+[rows[1]],policy,complete=True)

    def test_native_add_never_replaces_conflicting_route_or_readds_exact_route(self):
        native=NativeBackend.__new__(NativeBackend);native.policy=definition()['compiled'];rows=rows_for(native.policy)[:1];calls=[]
        native.json=lambda *a:copy.deepcopy(rows)
        def called(tool,args):
            calls.append((tool,args));rows.extend(rows_for(native.policy)[1:]);return ''
        native.call=called;route=native.policy['endpoint']['routes'][0]
        self.assertEqual(native.route_add(route)['state'],'added')
        self.assertEqual(native.route_add(route)['state'],'present');self.assertEqual(len(calls),1)
        self.assertNotIn('replace',calls[0][1])
        rows[1]['gateway']='10.80.0.99'
        with self.assertRaises(ContractError):native.route_add(route)
        self.assertEqual(len(calls),1)


class RouteBackend(agent_tests.FakeBackend):
    def __init__(self):super().__init__();self.routes=[]
    def route_add(self,route):
        self.calls.append(('route-add',route))
        if self.fail=='route':raise OSError('合成路由写入中断')
        self.routes.append(copy.deepcopy(route));return {'state':'added'}
    def network_fingerprint(self):return hashlib.sha256(canonical(self.routes).encode()).hexdigest()


class RouteAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.definition=definition()
        self.backend=RouteBackend();self.agent=GuestAgent(self.root/'guest',self.definition,self.backend)
    def request(self,action):
        p=self.agent.policy
        return {'schema':1,'instance_uuid':p['instance_uuid'],'generation':p['generation'],'policy_sha256':p['policy_sha256'],
                'operation_id':str(uuid.uuid4()),'action':action}

    def test_default_deny_is_installed_before_interface_up_and_narrow_route(self):
        value=self.agent.dispatch(self.request('network-apply'))
        self.assertEqual(value['state'],'network-configured');self.assertFalse(value['network_verified'])
        calls=self.backend.calls
        firewall=next(i for i,c in enumerate(calls) if c[:3]==('nft','-f','-'))
        up=next(i for i,c in enumerate(calls) if c[:4]==('ip','link','set','dev'))
        route=next(i for i,c in enumerate(calls) if c[0]=='route-add')
        self.assertLess(firewall,up);self.assertLess(up,route)
        self.assertNotIn(('sysctl','-w','net.ipv4.ip_forward=1'),calls)

    def test_route_drift_blocks_later_services_without_replaying_network(self):
        self.agent.dispatch(self.request('network-apply'));self.backend.routes=[];before=len(self.backend.calls)
        value=self.agent.dispatch(self.request('services-start'))
        self.assertEqual(value['state'],'failed')
        self.assertFalse(any(c[0]=='service' for c in self.backend.calls[before:]))

    def test_route_failure_is_unknown_and_never_replayed(self):
        self.backend.fail='route';request=self.request('network-apply')
        with self.assertRaises(OSError):self.agent.dispatch(request)
        count=len(self.backend.calls)
        self.assertEqual(self.agent.dispatch(request)['state'],'unknown');self.assertEqual(len(self.backend.calls),count)
        with self.assertRaises(ContractError):self.agent.dispatch(self.request('network-apply'))


if __name__=='__main__':unittest.main()
