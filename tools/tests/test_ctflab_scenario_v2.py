"""通用场景计划测试，无来宾和网络副作用。"""
import copy
import json
from pathlib import Path
import sys
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab_scenario_v2 as scenario


def sample():
    asset = {'sha256':'a'*64, 'architecture':'x86_64', 'source':'local-test-fixture',
             'license':'synthetic-only', 'verification':'unverified'}
    def nic(name, network, address):
        return {'id':name, 'network':network, 'address':address, 'mac':'derived', 'model':'e1000'}
    def node(interfaces, deps):
        return {'asset':'linux', 'cpus':1, 'memory_mb':512, 'firmware':'bios', 'disk_bus':'ide',
                'interfaces':interfaces, 'depends_on':deps}
    return {'schema':2, 'scenario_id':'three-node-example', 'assets':{'linux':asset},
            'networks':{'outer':{'cidr':'10.80.0.0/24','uplink':'none'},
                        'inner':{'cidr':'10.81.0.0/24','uplink':'none'}},
            'nodes':{'client':node([nic('eth0','outer','10.80.0.10')],['middle']),
                     'middle':node([nic('eth0','outer','10.80.0.20'),nic('eth1','inner','10.81.0.20')],['server']),
                     'server':node([nic('eth0','inner','10.81.0.30')],[])},
            'policy':{'internet':False,'host_forwards':[],'failure':'preserve'}}


class ScenarioV2Tests(unittest.TestCase):
    def setUp(self):
        self.value = sample()
        self.instance = str(uuid.uuid4())

    def test_three_nodes_two_networks(self):
        before = copy.deepcopy(self.value)
        plan = scenario.instance_plan(self.value, self.instance)
        self.assertEqual(plan['start_order'], ['server','middle','client'])
        self.assertEqual(plan['stop_order'], ['client','middle','server'])
        self.assertEqual(plan['total_memory_mb'],1536)
        self.assertEqual(plan['manifest']['assets']['linux']['verification'],'unverified')
        self.assertFalse(plan['isolation_verified'])
        self.assertEqual(self.value,before)

    def test_same_plan_deterministic(self):
        first = scenario.instance_plan(self.value,self.instance)
        self.value['nodes'] = dict(reversed(list(self.value['nodes'].items())))
        self.assertEqual(first,scenario.instance_plan(self.value,self.instance))

    def test_instance_generation_paths_and_mac(self):
        first = scenario.instance_plan(self.value,self.instance)
        nextgen = scenario.instance_plan(self.value,self.instance,generation=2)
        other = scenario.instance_plan(self.value,str(uuid.uuid4()))
        self.assertNotEqual(first['resources'],nextgen['resources'])
        self.assertEqual(first['manifest'],nextgen['manifest'])
        self.assertNotEqual(first['manifest'],other['manifest'])

    def test_cycle(self):
        self.value['nodes']['server']['depends_on']=['client']
        with self.assertRaises(scenario.ScenarioError):scenario.validate_manifest(self.value)

    def test_unknown_fields_and_host_command(self):
        for target in (self.value,self.value['nodes']['client'],self.value['assets']['linux']):
            target['command']='echo unwanted'
            with self.assertRaises(scenario.ScenarioError):scenario.validate_manifest(self.value)
            del target['command']

    def test_duplicate_ip_mac_nic(self):
        for field,value in [('address','10.80.0.20'),('mac','02:00:00:00:00:01')]:
            data=sample();data['nodes']['middle']['interfaces'][0]['mac']='02:00:00:00:00:01'
            data['nodes']['client']['interfaces'][0][field]=value
            with self.assertRaises(scenario.ScenarioError):scenario.validate_manifest(data)
        self.value['nodes']['middle']['interfaces'][1]['id']='eth0'
        with self.assertRaises(scenario.ScenarioError):scenario.validate_manifest(self.value)

    def test_network_overlap_public_and_network_address(self):
        for cidr in ('10.80.0.0/24','8.8.8.0/24','10.81.0.1/24'):
            self.value['networks']['inner']['cidr']=cidr
            with self.assertRaises(scenario.ScenarioError):scenario.validate_manifest(self.value)
        self.value=sample();self.value['nodes']['client']['interfaces'][0]['address']='10.80.0.0'
        with self.assertRaises(scenario.ScenarioError):scenario.validate_manifest(self.value)

    def test_no_exit_or_forward(self):
        self.value['policy']['internet']=True
        with self.assertRaises(scenario.ScenarioError):scenario.validate_manifest(self.value)
        self.value=sample();self.value['networks']['outer']['uplink']='bridge'
        with self.assertRaises(scenario.ScenarioError):scenario.validate_manifest(self.value)

    def test_bad_type_unknown_reference_and_resource_bounds(self):
        for key,value in [('cpus',True),('memory_mb',0),('asset',[]),('depends_on',['missing'])]:
            data=sample();data['nodes']['client'][key]=value
            with self.assertRaises(scenario.ScenarioError):scenario.validate_manifest(data)

    def test_arm_hardware(self):
        self.value['assets']['linux']['architecture']='aarch64'
        with self.assertRaises(scenario.ScenarioError):scenario.validate_manifest(self.value)
        for node in self.value['nodes'].values():
            node.update(firmware='uefi',disk_bus='virtio')
            for nic in node['interfaces']:nic['model']='virtio-net-pci'
        self.assertEqual(scenario.validate_manifest(self.value),self.value)

    def test_json_bounds_duplicates_and_constants(self):
        for raw in ('{"schema":2,"schema":2}', '{"schema":NaN}', '[]', '\ud800', 'x'*(scenario.MAX_BYTES+1)):
            with self.assertRaises(scenario.ScenarioError):scenario.parse_manifest(raw)
        self.assertEqual(scenario.parse_manifest(json.dumps(self.value)),self.value)

    def test_noncanonical_identity_and_generation(self):
        for identity,gen in [('bad',1),(self.instance,True),(self.instance,0)]:
            with self.assertRaises(scenario.ScenarioError):scenario.instance_plan(self.value,identity,generation=gen)
