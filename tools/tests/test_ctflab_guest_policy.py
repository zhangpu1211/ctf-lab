"""来宾声明与规则编译；不在测试宿主应用网络规则。"""
import copy
from pathlib import Path
import sys
import unittest
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError
from ctflab_scenario_v2 import instance_plan
from ctflab_guest_policy import compile_policy,verify_policy,firewall,service_config,service_units,vm_uuid
from test_ctflab_scenario_v2 import sample


def envelope(instance=None,generation=1,containers=False):
    plan=instance_plan(sample(),instance or str(uuid.uuid4()),generation=generation)
    devices={'eth0':'ens3','eth1':'ens4'}
    flows=[{'source':{'node':'client','interface':'eth0'},'destination':{'node':'server','interface':'eth0'},
            'protocol':'tcp','ports':[80,443],'reason':'课程Web访问'}]
    entries={'web':{'image':'example/web@sha256:'+'a'*64,'address':'10.99.0.10','user':'1000:1000',
                    'memory_mb':256,'cpus':1,'volumes':{'web-data':'/data'}}} if containers else {}
    cidr='10.99.0.0/24' if containers else None
    compiled=compile_policy(plan,'middle',devices,flows,containers=entries,container_cidr=cidr)
    return {'plan':plan,'node':'middle','devices':devices,'flows':flows,'containers':entries,'container_cidr':cidr,'compiled':compiled}


class PolicyTests(unittest.TestCase):
    def test_derived_identity_and_generation(self):
        a=envelope();b=envelope(a['plan']['instance_uuid'],2)
        self.assertNotEqual(a['compiled']['vm_uuid'],b['compiled']['vm_uuid'])
        self.assertNotEqual(a['compiled']['policy_sha256'],b['compiled']['policy_sha256'])
        self.assertEqual(verify_policy(a),a['compiled'])

    def test_forward_rules_only_explicit_endpoints_and_reverse_state(self):
        text=firewall(envelope()['compiled'])
        self.assertIn('iifname "ens3" oifname "ens4" ip saddr 10.80.0.10 ip daddr 10.81.0.30 tcp dport { 80, 443 }',text)
        self.assertIn('tcp sport { 80, 443 } ct state established',text)
        self.assertEqual(text.count('policy drop;'),3)
        self.assertEqual(text.count('meta nfproto ipv6 counter drop'),3)
        self.assertNotIn('flush ruleset',text);self.assertNotIn('masquerade',text)
        self.assertNotIn('0.0.0.0/0',text)

    def test_interface_shell_text_and_loopback_rejected(self):
        value=envelope()
        for device in ('lo','eth0; reboot','$(bad)','../../outside','eth0\n'):
            with self.assertRaises(ContractError):compile_policy(value['plan'],'middle',{'eth0':device,'eth1':'ens4'},value['flows'])

    def test_undeclared_destination_and_same_network_rejected(self):
        value=envelope()
        value['flows'][0]['destination']['node']='internet'
        with self.assertRaises(ContractError):compile_policy(value['plan'],'middle',value['devices'],value['flows'])
        value=envelope();value['flows'][0]['destination']=copy.deepcopy(value['flows'][0]['source'])
        with self.assertRaises(ContractError):compile_policy(value['plan'],'middle',value['devices'],value['flows'])

    def test_guest_command_mount_root_and_unpinned_image_refused(self):
        for change in ({'command':['sh']},{'image':'example/web:latest'},{'user':'0'},{'volumes':{'data':'/var/run/docker.sock'}}):
            value=envelope(containers=True);value['containers']['web'].update(change)
            with self.assertRaises(ContractError):compile_policy(value['plan'],'middle',value['devices'],value['flows'],containers=value['containers'],container_cidr=value['container_cidr'])

    def test_container_network_overlap_and_public_network_refused(self):
        value=envelope(containers=True)
        for cidr in ('10.80.0.0/24','8.8.8.0/24','127.0.0.0/24','::1/128'):
            with self.assertRaises(ContractError):compile_policy(value['plan'],'middle',value['devices'],value['flows'],containers=value['containers'],container_cidr=cidr)

    def test_compiled_policy_tamper_rejected(self):
        value=envelope();value['compiled']['rules'][0]['ports']=[22]
        with self.assertRaises(ContractError):verify_policy(value)

    def test_container_cross_network_flow_fails_closed_until_gateway_is_verified(self):
        value=envelope(containers=True)
        value['flows'][0]['destination']={'node':'container:web','interface':'container'}
        with self.assertRaises(ContractError):compile_policy(value['plan'],'middle',value['devices'],value['flows'],
                                                            containers=value['containers'],container_cidr=value['container_cidr'])

    def test_dns_has_no_upstream_and_ntp_cannot_set_clock(self):
        configs=service_config(envelope()['compiled'],'/var/lib/ctflab-guest')
        self.assertIn('no-resolv',configs['dnsmasq.conf'])
        self.assertNotIn('server=',configs['dnsmasq.conf'])
        self.assertIn('local stratum 10',configs['chrony.conf'])
        units=service_units();self.assertIn(' -x ',units['ctflab-time.service'])
        self.assertTrue(all('SendSIGKILL=no' in u and 'Restart=no' in u for u in units.values()))


if __name__=='__main__':unittest.main()
