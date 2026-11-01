"""Windows Wintun/IP Helper API替身与跨平台代理协议；不加载DLL、安装驱动或改本机网络。"""
import base64
import copy
import ctypes as C
from dataclasses import asdict
import io
import json
from pathlib import Path
import sys
import subprocess
import os
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ctflab_windows_ip as module
import ctflab_windows_firewall as firewall
import ctflab_external as external
import test_ctflab_external_ip as packets
from ctflab_contract import ContractError
from ctflab_generation_store import digest
from ctflab_external_ip import policy_sha


def copy_row(row):return type(row).from_buffer_copy(bytes(row))
def output(pointer,value):C.memmove(pointer,C.byref(value),C.sizeof(value))
def configuration(kind='windows'):
    value=external.settings(__import__('test_ctflab_external').config(kind))
    value['ip_tunnels']={'peer':packets.specification()};value['principals']['runner'].append('peer')
    return value

def declaration(config,spec):
    names=('ctflab_windows_ip.py','ctflab_external.py','ctflab_external_ip.py','ctflab_contract.py',
        'ctflab_generation_store.py','ctflab_windows_security.py','ctflab_windows_native.py','ctflab_windows_firewall.py')
    value={key:config[key] for key in ('machine_uuid','node_uuid','cohort_uuid','checkpoint_uuid','generation')}
    value.update(schema=1,role='windows-external-ip-endpoint',policies=[policy_sha(spec)],
        runtime_sha256={name:'a'*64 for name in names},wintun_sha256='b'*64,driver_version=1,allow_driver_install=False)
    return value


class Api:
    """原始C指针接口；真实ctypes结构读写，所有系统操作为内存实现。"""
    def __init__(self):
        self.addresses=[];self.routes=[];self.interfaces={};self.buffers=[];self.calls=[]
        self.alias=None;self.guid=None;self.missing6=False;self.fail_address=0;self.fail_route=0;self.freed=0
        for name in ('GetUnicastIpAddressTable','GetIpForwardTable2','FreeMibTable','InitializeUnicastIpAddressEntry',
            'CreateUnicastIpAddressEntry','GetUnicastIpAddressEntry','InitializeIpForwardEntry','CreateIpForwardEntry2',
            'GetIpInterfaceEntry','SetIpInterfaceEntry','ConvertInterfaceAliasToLuid','ConvertInterfaceLuidToAlias',
            'ConvertInterfaceGuidToLuid','ConvertInterfaceLuidToGuid'):
            setattr(self,name,Mock(side_effect=getattr(self,'call_'+name)))
    def table(self,rows,row_type,pointer):
        class Table(C.Structure):_fields_=[('count',module.U32),('rows',row_type*max(1,len(rows)))]
        table=Table();table.count=len(rows)
        for index,row in enumerate(rows):table.rows[index]=row
        self.buffers.append(table);C.cast(pointer,C.POINTER(module.PTR))[0]=C.addressof(table);return 0
    def call_GetUnicastIpAddressTable(self,family,pointer):return self.table(self.addresses,module.Unicast,pointer)
    def call_GetIpForwardTable2(self,family,pointer):return self.table(self.routes,module.Route,pointer)
    def call_FreeMibTable(self,pointer):self.freed+=1
    def call_InitializeUnicastIpAddressEntry(self,pointer):pass
    def call_InitializeIpForwardEntry(self,pointer):pass
    def call_GetIpInterfaceEntry(self,pointer):
        row=C.cast(pointer,C.POINTER(module.Interface)).contents
        if row.family==23 and self.missing6:return 1168
        key=(row.luid,row.family)
        if key not in self.interfaces:
            value=module.Interface();value.family=row.family;value.luid=row.luid;value.index=17;value.mtu=1500
            value.forwarding=1;value.weak_send=1;value.weak_receive=1;value.connected=1
            value.transmit_offload=0x20;self.interfaces[key]=value
        output(pointer,self.interfaces[key]);return 0
    def call_SetIpInterfaceEntry(self,pointer):
        row=copy_row(C.cast(pointer,C.POINTER(module.Interface)).contents)
        self.calls.append(('set-interface',row.luid,row.family));self.interfaces[(row.luid,row.family)]=row;return 0
    def call_CreateUnicastIpAddressEntry(self,pointer):
        row=copy_row(C.cast(pointer,C.POINTER(module.Unicast)).contents)
        self.calls.append(('address',row.luid,row.address.ip(),row.prefix_length))
        if self.fail_address:return self.fail_address
        row.dad=4;self.addresses.append(row);return 0
    def call_GetUnicastIpAddressEntry(self,pointer):
        row=C.cast(pointer,C.POINTER(module.Unicast)).contents
        for value in self.addresses:
            if value.luid==row.luid and value.address.ip()==row.address.ip():output(pointer,value);return 0
        return 1168
    def call_CreateIpForwardEntry2(self,pointer):
        row=copy_row(C.cast(pointer,C.POINTER(module.Route)).contents)
        self.calls.append(('route',row.luid,row.prefix.address.ip(),row.prefix.length))
        if self.fail_route:return self.fail_route
        self.routes.append(row);return 0
    def call_ConvertInterfaceAliasToLuid(self,name,pointer):return 0 if name==self.alias else 2
    def call_ConvertInterfaceGuidToLuid(self,guid,pointer):return 0 if C.cast(guid,C.POINTER(module.Guid)).contents.text()==self.guid else 2
    def call_ConvertInterfaceLuidToAlias(self,luid,buffer,length):buffer.value=self.alias;return 0
    def call_ConvertInterfaceLuidToGuid(self,luid,pointer):output(pointer,module.Guid.of(self.guid));return 0


class FirewallApi:
    def __init__(self):self.values={};self.calls=[];self.drift=False;self.closed=False;self.unknown_add=False;self.fail_remove=False
    def guard(self,alias):self.calls.append(('guard',alias))
    def find(self,name,fields):
        value=self.values.get(name)
        if value is None:return None
        result=copy.deepcopy(value)
        if self.drift:result['Interfaces']=['someone-else']
        return result
    def add(self,value):
        self.calls.append(('add',copy.deepcopy(value)));self.values[value['Name']]=copy.deepcopy(value)
        if self.unknown_add:raise OSError('创建禁用规则后丢回复')
    def set_enabled(self,expected,enabled):
        self.calls.append(('enabled',expected['Name'],enabled));self.values[expected['Name']]['Enabled']=enabled
    def remove(self,name):
        self.calls.append(('remove',name))
        if self.fail_remove:raise OSError('删除回执丢失')
        self.values.pop(name)
    def close(self):self.closed=True


class Native:
    def __init__(self):
        self.api=Api();self.network=module.Network(self.api);self.trace=[];self.queue=[];self.sent=[]
        self.firewall_api=FirewallApi();self.firewall=firewall.Firewall(self.firewall_api)
        self.changed=False;self.luid_changed=False;self.fail_end=False;self.fail_start=False
    def guard(self,**kwargs):
        self.trace.append('guard');require=__import__('ctflab_contract').require;require(not self.changed,'identity-unknown')
    def create(self,name,identity):
        self.network.unused(name,identity);self.api.alias=name;self.api.guid=identity;self.trace.append('create');return 123
    def luid(self,adapter):return 8 if self.luid_changed else 7
    def start(self,adapter):
        self.trace.append('start')
        if self.fail_start:raise OSError('synthetic session failure')
        return 456
    def receive(self,session):return self.queue.pop(0) if self.queue else None
    def send(self,session,data):self.sent.append(data)
    def end(self,session):
        self.trace.append(('end',session))
        if self.fail_end:raise OSError('synthetic end failure')
    def close(self,adapter):self.trace.append(('close',adapter))
    def dispose(self):self.firewall.close()


class LayoutTests(unittest.TestCase):
    def test_windows_64bit_sdk_layout_and_sockaddr_byte_order(self):
        self.assertEqual(module.abi()['interface'],168)
        self.assertEqual(module.Unicast.luid.offset,32);self.assertEqual(module.Unicast.created.offset,72)
        self.assertEqual(module.Route.prefix.offset,12);self.assertEqual(module.Route.next_hop.offset,44)
        self.assertEqual(module.Interface.mtu.offset,152);self.assertEqual(module.Interface.disable_default.offset,166)
        value=module.Address.ipv4('10.230.0.1');self.assertEqual(value.ip(),'10.230.0.1')
        self.assertEqual(bytes(value.raw[4:8]),b'\x0a\xe6\0\x01')
        identity=str(uuid.uuid4());self.assertEqual(module.Guid.of(identity).text(),identity)
    def test_marker_rejects_wrong_scope_paths_policy_and_boolean_versions(self):
        config=configuration();spec=config['ip_tunnels']['peer'];value=declaration(config,spec)
        self.assertEqual(module.marker(value,config,spec),value)
        for changes in ({'generation':True},{'node_uuid':str(uuid.uuid4())},{'role':'runner'},
            {'policies':['0'*64]},{'driver_version':True},{'allow_driver_install':1},
            {'wintun_sha256':'not-a-hash'},{'runtime_sha256':{'../escape.py':'a'*64}}):
            with self.subTest(changes=changes),self.assertRaises(ContractError):module.marker(dict(value,**changes),config,spec)
    def test_host_is_refused_before_dll_loading(self):
        with patch.object(module.platform,'system',return_value='Darwin'),patch.object(module.C,'WinDLL',create=True,side_effect=AssertionError('不能在宿主加载DLL')):
            with self.assertRaises(ContractError):module.Native(configuration(),packets.specification())


class NetworkTests(unittest.TestCase):
    def setUp(self):self.api=Api();self.network=module.Network(self.api);self.spec=packets.specification()
    def setup_network(self):
        self.api.alias='owned';self.api.guid=str(uuid.uuid4());self.network.configure(7,self.spec)
    def test_exact_32_address_peer_route_and_disabled_forwarding_read_back(self):
        self.setup_network();self.network.verify(7,self.api.alias,self.api.guid,self.spec)
        self.assertEqual([row for row in self.api.calls if row[0]=='address'],[('address',7,self.spec['local'],32)])
        self.assertEqual([row for row in self.api.calls if row[0]=='route'],[('route',7,self.spec['peer'],32)])
        self.assertEqual({(r[1],r[2]) for r in self.api.calls if r[0]=='set-interface'},{(7,2),(7,23)})
        self.assertEqual(self.api.interfaces[(7,2)].transmit_offload,0x20,'只读字段保留')
        self.assertTrue(all(not r.forwarding and not r.weak_send and not r.weak_receive and r.disable_default for r in self.api.interfaces.values()))
    def test_specific_route_or_existing_address_overlap_refused_default_route_preserved(self):
        route=module.Route();route.luid=99;route.prefix=module.Prefix(module.Address.ipv4('0.0.0.0'),0)
        route.next_hop=module.Address.ipv4('192.168.1.1');self.api.routes=[route]
        self.network.preflight(self.spec);before=bytes(route)
        address=module.Unicast();address.luid=99;address.address=module.Address.ipv4('10.230.0.10');address.prefix_length=24
        self.api.addresses=[address]
        with self.assertRaises(ContractError):self.network.preflight(self.spec)
        self.api.addresses=[];route.prefix=module.Prefix(module.Address.ipv4(self.spec['peer']),32)
        with self.assertRaises(ContractError):self.network.preflight(self.spec)
        self.assertEqual(self.api.calls,[])
    def test_existing_alias_or_guid_is_not_adopted(self):
        self.api.alias='existing';self.api.guid=str(uuid.uuid4())
        with self.assertRaises(ContractError):self.network.unused('existing',str(uuid.uuid4()))
        with self.assertRaises(ContractError):self.network.unused('new',self.api.guid)
        self.assertEqual(self.api.calls,[])
    def test_ipv6_binding_absent_is_allowed_without_enabling_it(self):
        self.api.missing6=True;self.setup_network();self.network.verify(7,self.api.alias,self.api.guid,self.spec)
        self.assertEqual([r for r in self.api.calls if r[0]=='set-interface'],[('set-interface',7,2)])
    def test_forwarding_mtu_ipv6_address_and_route_drift_rejected(self):
        self.setup_network();row=self.api.interfaces[(7,2)]
        for name,value in (('forwarding',1),('weak_receive',1),('disable_default',0),('mtu',1500),('metric',9)):
            old=getattr(row,name);setattr(row,name,value)
            with self.subTest(name=name),self.assertRaises(ContractError):self.network.verify(7,self.api.alias,self.api.guid,self.spec)
            setattr(row,name,old)
        extra=module.Unicast();extra.luid=7;extra.address.family=23;self.api.addresses.append(extra)
        with self.assertRaises(ContractError):self.network.verify(7,self.api.alias,self.api.guid,self.spec)
        self.api.addresses.pop();self.api.routes[0].prefix.length=0
        with self.assertRaises(ContractError):self.network.verify(7,self.api.alias,self.api.guid,self.spec)
    def test_duplicate_address_fails_without_creating_route(self):
        self.api.fail_address=183
        with self.assertRaises(ContractError):self.setup_network()
        self.assertFalse(any(row[0]=='route' for row in self.api.calls))
    def test_table_size_bound_frees_os_buffer(self):
        self.api.addresses=[module.Unicast() for _ in range(2049)]
        with self.assertRaises(ContractError):self.network.addresses()
        self.assertEqual(self.api.freed,1)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.native=Native();self.config=configuration();self.spec=self.config['ip_tunnels']['peer'];self.channel=str(uuid.uuid4())
    def endpoint(self):
        value=module.WindowsEndpoint(self.spec,self.config,self.channel,native=self.native);self.addCleanup(value.close);return value
    def test_receive_send_and_close_bind_only_new_adapter(self):
        endpoint=self.endpoint();raw=packets.raw_packet();self.native.queue=[raw]
        self.assertEqual(endpoint.receive(),raw)
        reply=packets.raw_packet(source=self.spec['peer'],destination=self.spec['local'],a=53,b=30000)
        endpoint.send(reply);self.assertEqual(self.native.sent,[reply]);endpoint.close();endpoint.close()
        self.assertEqual(self.native.trace.count(('end',456)),1);self.assertEqual(self.native.trace.count(('close',123)),1)
        self.assertEqual(self.native.api.alias,'CTFLab-'+self.channel)
    def test_identity_or_marker_drift_prevents_packet_injection(self):
        endpoint=self.endpoint();self.native.luid_changed=True
        with self.assertRaises(ContractError):endpoint.send(packets.raw_packet())
        self.assertEqual(self.native.sent,[])
        self.native.luid_changed=False;self.native.changed=True
        with self.assertRaises(ContractError):endpoint.receive()
    def test_cleanup_failure_still_closes_owned_adapter_and_does_not_repeat(self):
        endpoint=self.endpoint();self.native.fail_end=True
        with self.assertRaises(ContractError):endpoint.close()
        self.assertIn(('close',123),self.native.trace);endpoint.close()
        self.assertEqual(self.native.trace.count(('close',123)),1)
    def test_partial_creation_failure_closes_only_own_adapter(self):
        self.native.api.fail_route=5
        with self.assertRaises(ContractError):self.endpoint()
        self.assertIn(('close',123),self.native.trace);self.assertNotIn('start',self.native.trace)
        self.assertEqual([r for r in self.native.api.calls if r[0]=='address'],[('address',7,self.spec['local'],32)])
    def test_session_failure_closes_adapter_before_return(self):
        self.native.fail_start=True
        with self.assertRaises(OSError):self.endpoint()
        self.assertEqual(self.native.trace.count(('close',123)),1)
    def test_background_multicast_ipv6_discarded_with_bound_and_no_forwarding(self):
        endpoint=self.endpoint();noise=packets.raw_packet(destination='224.0.0.22');raw=packets.raw_packet()
        self.native.queue=[noise,b'\x60'+b'\0'*39,raw]
        self.assertEqual(endpoint.receive(),raw);self.assertEqual(endpoint.discarded,2)
        self.native.queue=[noise]*256
        for _ in range(15):self.assertIsNone(endpoint.receive())
        with self.assertRaises(ContractError):endpoint.receive()
        self.assertEqual(self.native.sent,[])


class DriverApiTests(unittest.TestCase):
    def test_packet_pointer_released_once_and_bad_length_not_copied(self):
        native=module.Native.__new__(module.Native);payload=C.create_string_buffer(b'x'*64)
        def receive(session,size):C.cast(size,C.POINTER(module.U32))[0]=64;return C.addressof(payload)
        native.dll=SimpleNamespace(WintunReceivePacket=Mock(side_effect=receive),WintunReleaseReceivePacket=Mock())
        self.assertEqual(native.receive(7),b'x'*64);native.dll.WintunReleaseReceivePacket.assert_called_once_with(7,C.addressof(payload))
        def invalid(session,size):C.cast(size,C.POINTER(module.U32))[0]=65536;return C.addressof(payload)
        native.dll.WintunReceivePacket.side_effect=invalid
        with patch.object(module.C,'string_at',side_effect=AssertionError('超大长度不能解引用')):
            with self.assertRaises(ContractError):native.receive(7)
        self.assertEqual(native.dll.WintunReleaseReceivePacket.call_count,2)
    def test_empty_receive_and_full_send_do_not_retry(self):
        native=module.Native.__new__(module.Native)
        native.dll=SimpleNamespace(WintunReceivePacket=Mock(return_value=None),WintunAllocateSendPacket=Mock(return_value=None),WintunSendPacket=Mock())
        with patch.object(module.C,'get_last_error',create=True,return_value=259):self.assertIsNone(native.receive(7))
        with patch.object(module.C,'get_last_error',create=True,return_value=5):
            with self.assertRaises(ContractError):native.receive(7)
        with self.assertRaises(ContractError):native.send(7,packets.raw_packet())
        self.assertEqual(native.dll.WintunAllocateSendPacket.call_count,1);native.dll.WintunSendPacket.assert_not_called()
    def test_send_copies_exact_bytes_then_transfers_once(self):
        native=module.Native.__new__(module.Native);raw=packets.raw_packet();payload=C.create_string_buffer(len(raw))
        native.dll=SimpleNamespace(WintunAllocateSendPacket=Mock(return_value=C.addressof(payload)),WintunSendPacket=Mock())
        native.send(7,raw);self.assertEqual(payload.raw,raw);native.dll.WintunSendPacket.assert_called_once_with(7,C.addressof(payload))
    def test_offline_authenticode_verification_always_closes_state(self):
        native=module.Native.__new__(module.Native)
        for result in (0,-1):
            actions=[]
            def verify(window,action,pointer):
                data=C.cast(pointer,C.POINTER(module.TrustData)).contents;actions.append(data.state_action)
                self.assertEqual(data.ui,2);self.assertEqual(data.flags,0x1080)
                self.assertEqual(C.cast(action,C.POINTER(module.Guid)).contents.text(),'00aac56b-cd44-11d0-8cc2-00c04fc295ee')
                return result if data.state_action==1 else 0
            library=SimpleNamespace(WinVerifyTrust=Mock(side_effect=verify))
            with patch.object(module.C,'WinDLL',create=True,return_value=library):
                if result==0:native.trust(Path('/synthetic/wintun.dll'))
                else:
                    with self.assertRaises(ContractError):native.trust(Path('/synthetic/wintun.dll'))
            self.assertEqual(actions,[1,2])


class AgentTests(unittest.TestCase):
    def test_windows_and_domain_kinds_dispatch_authenticated_ip_without_lifecycle(self):
        for kind in ('windows','ad-dc','ad-member'):
            config=configuration(kind);native=Native();endpoints=[]
            def factory(*args):
                value=module.WindowsEndpoint(*args,native=native);endpoints.append(value);return value
            agent=external.ExternalAgent(config,'runner',observe=lambda:{'system':'Windows','native_verified':True,
                'machine_uuid':config['machine_uuid']},ip_factory=factory)
            try:
                challenge=str(uuid.uuid4());report=agent.handle('ext-handshake',{'challenge':challenge})
                self.assertFalse(report['health_verified']);self.assertEqual(report['lifecycle'],'manual-in-original-software')
                params={key:config[key] for key in ('node_uuid','cohort_uuid','checkpoint_uuid','generation')}
                params.update(challenge=challenge,channel_id=str(uuid.uuid4()))
                opened=agent.handle('ext-ip-open',dict(params,tunnel='peer'))
                self.assertEqual(opened['protocol'],'ipv4');self.assertTrue(opened['guest_network_change_requested'])
                self.assertFalse(opened['route_changed']);self.assertEqual(opened['route_scope'],'runner-host')
                self.assertFalse(opened['guest_network_cleanup_verified'])
                native.queue=[packets.raw_packet()]
                self.assertEqual(base64.b64decode(agent.handle('ext-ip-receive',dict(params,sequence=1))['data']),packets.raw_packet())
                reply=packets.raw_packet(source='10.230.0.2',destination='10.230.0.1',a=53,b=30000)
                agent.handle('ext-ip-send',dict(params,sequence=2,data=base64.b64encode(reply).decode()))
                self.assertEqual(native.sent,[reply])
                with self.assertRaises(ContractError):agent.handle('ext-ip-send',dict(params,sequence=2,data=base64.b64encode(reply).decode()))
                self.assertTrue(endpoints[0].closed);self.assertEqual(len(native.sent),1)
            finally:agent.close()
    def test_cleanup_failure_does_not_leave_other_owned_channels_open(self):
        config=configuration();agent=external.ExternalAgent(config,'runner',observe=lambda:{'system':'Windows',
            'native_verified':True,'machine_uuid':config['machine_uuid']})
        one=Mock();two=Mock();one.close.side_effect=ContractError('identity-unknown')
        agent.channels={'one':{'endpoint':one},'two':{'endpoint':two}}
        agent.close();one.close.assert_called_once();two.close.assert_called_once();self.assertEqual(agent.channels,{})

    def test_admin_config_reader_is_explicit_and_normal_reader_not_relaxed(self):
        config=configuration();fake=Mock()
        with patch.object(external,'ExternalAgent',return_value=fake),patch.object(module,'read_configuration',return_value=config) as reader,\
             patch.object(external,'private_json',side_effect=AssertionError('不应混用普通配置读取')):
            external.serve(Path('fixed-config'),'runner',io.BytesIO(),io.BytesIO(),windows_ip_guest=True)
            reader.assert_called_once_with(Path('fixed-config'));fake.close.assert_called_once()
        with patch.object(external,'private_json',side_effect=ValueError('normal denied')),patch.object(module,'read_configuration',side_effect=AssertionError('不得自动尝试管理员模式')):
            with self.assertRaises(ValueError):external.serve(Path('fixed-config'),'runner',io.BytesIO(),io.BytesIO())


class FirewallTests(unittest.TestCase):
    def test_rules_only_cover_exact_interface_addresses_and_declared_direction(self):
        spec=packets.specification();spec['flows'][1]['initiator']='peer';channel=str(uuid.uuid4());alias='CTFLab-'+channel
        values=firewall.recipes(spec,alias,channel)
        self.assertEqual(len(values),3)
        self.assertEqual(values[0]['Direction'],2);self.assertEqual(values[0]['RemotePorts'],'53');self.assertEqual(values[0]['LocalPorts'],'*')
        self.assertEqual(values[1]['Direction'],1);self.assertEqual(values[1]['LocalPorts'],'80')
        self.assertEqual(values[2]['IcmpTypesAndCodes'],'8:0')
        self.assertTrue(all(v['Interfaces']==[alias] and v['LocalAddresses']==spec['local'] and v['RemoteAddresses']==spec['peer']
            and v['Action']==1 and not v['EdgeTraversal'] for v in values))
    def test_disabled_rule_verified_before_enabling_and_own_only_cleanup(self):
        api=FirewallApi();owner=firewall.Firewall(api);channel=str(uuid.uuid4());alias='CTFLab-'+channel
        api.values['unrelated']={'Name':'unrelated','Enabled':True}
        owner.install(packets.specification(),alias,channel);owner.verify()
        for operation in api.calls:
            if operation[0]=='add':self.assertFalse(operation[1]['Enabled'])
        self.assertTrue(all(v['Enabled'] for key,v in api.values.items() if key!='unrelated'))
        owner.close();self.assertEqual(api.values,{'unrelated':{'Name':'unrelated','Enabled':True}});self.assertTrue(api.closed)
        removed=[entry[1] for entry in api.calls if entry[0]=='remove'];self.assertEqual(len(removed),3)
        owner.close();self.assertEqual(len([entry for entry in api.calls if entry[0]=='remove']),3)
    def test_unknown_add_preserves_disabled_rule_and_does_not_retry(self):
        api=FirewallApi();api.unknown_add=True;owner=firewall.Firewall(api);channel=str(uuid.uuid4())
        with self.assertRaises(OSError):owner.install(packets.specification(),'CTFLab-'+channel,channel)
        owner.close();self.assertEqual(len(api.values),1);self.assertFalse(next(iter(api.values.values()))['Enabled'])
        self.assertEqual(len([entry for entry in api.calls if entry[0]=='add']),1)
    def test_existing_name_or_changed_ownership_is_never_modified_or_removed(self):
        api=FirewallApi();owner=firewall.Firewall(api);channel=str(uuid.uuid4());alias='CTFLab-'+channel
        expected=firewall.recipes(packets.specification(),alias,channel)[0];api.values[expected['Name']]=expected
        with self.assertRaises(ContractError):owner.install(packets.specification(),alias,channel)
        self.assertFalse(any(row[0]=='add' for row in api.calls));api.values.clear()
        owner.install(packets.specification(),alias,channel);api.drift=True
        with self.assertRaises(ContractError):owner.verify()
        with self.assertRaises(ContractError):owner.close()
        self.assertFalse(any(row[0]=='remove' for row in api.calls));self.assertTrue(api.closed)
    def test_failed_removal_leaves_disabled_rule_and_releases_com(self):
        api=FirewallApi();owner=firewall.Firewall(api);channel=str(uuid.uuid4())
        owner.install(packets.specification(),'CTFLab-'+channel,channel);api.fail_remove=True
        with self.assertRaises(ContractError):owner.close()
        self.assertTrue(api.closed);self.assertTrue(all(not value['Enabled'] for value in api.values.values()))
    def test_icmp_errors_explicit_and_canonical_address_readback_no_widening(self):
        spec=dict(packets.specification(),icmp_errors=True);channel=str(uuid.uuid4());values=firewall.recipes(spec,'CTFLab-'+channel,channel)
        self.assertEqual(len(values),5);self.assertEqual({v['Direction'] for v in values[-2:]},{1,2})
        value=values[0];other=copy.deepcopy(value);other['LocalAddresses']+='/32';other['InterfaceTypes']='all'
        self.assertTrue(firewall.matches(value,other));other['RemoteAddresses']='10.230.0.0/24';self.assertFalse(firewall.matches(value,other))
        other=copy.deepcopy(value);other['Interfaces']=[];self.assertFalse(firewall.matches(value,other))


class FirewallComTests(unittest.TestCase):
    def test_variant_layout_and_sdk_vtable_indices(self):
        self.assertEqual(C.sizeof(firewall.Variant),24);self.assertEqual(firewall.Variant.value.offset,8)
        self.assertEqual(firewall.FIELDS['Protocol'],(15,'integer'));self.assertEqual(firewall.FIELDS['Interfaces'],(29,'interfaces'))
        self.assertEqual(firewall.FIELDS['Enabled'],(33,'bool'));self.assertEqual(firewall.FIELDS['Action'],(41,'integer'))
    def test_rule_built_disabled_protocol_before_ports_and_optional_empty_fields_skipped(self):
        api=firewall.Com.__new__(firewall.Com);api.rules=123;api.create=Mock(return_value=456)
        api.put=Mock();api.call=Mock(return_value=0);api.release=Mock()
        channel=str(uuid.uuid4());value=dict(firewall.recipes(packets.specification(),'CTFLab-'+channel,channel)[0],Enabled=False)
        api.add(value);names=[call.args[1] for call in api.put.call_args_list]
        self.assertLess(names.index('Protocol'),names.index('RemotePorts'));self.assertEqual(names[-1],'Enabled')
        self.assertFalse(api.put.call_args_list[-1].args[2]);self.assertNotIn('ApplicationName',names);self.assertNotIn('ServiceName',names)
        self.assertEqual(api.call.call_args.args[1],8);api.release.assert_called_once_with(456)
        api.put.side_effect=ValueError('setter failure');api.call.reset_mock()
        with self.assertRaises(ValueError):api.add(value)
        api.call.assert_not_called();self.assertEqual(api.release.call_count,2)
    def test_com_guard_only_reads_policy_and_refuses_disabled_or_managed_environment(self):
        api=firewall.Com.__new__(firewall.Com);api.policy=123;api.auto=SimpleNamespace(VariantClear=Mock(return_value=0))
        mode=[0];enabled=[-1];calls=[]
        def call(obj,index,result,args,*values):
            calls.append(index)
            if index==28:C.cast(values[0],C.POINTER(firewall.I32))[0]=mode[0]
            elif index in (8,12):C.cast(values[1],C.POINTER(firewall.I16))[0]=enabled[0] if index==8 else 0
            elif index==10:C.cast(values[1],C.POINTER(firewall.Variant)).contents.kind=0
            else:raise AssertionError('不能写全局防火墙')
            return 0
        api.call=call;api.guard('CTFLab-owned');self.assertEqual(set(calls),{8,10,12,28})
        mode[0]=1
        with self.assertRaises(ContractError):api.guard('CTFLab-owned')
        mode[0]=0;enabled[0]=0
        with self.assertRaises(ContractError):api.guard('CTFLab-owned')
    def test_native_admin_reader_requires_elevation_and_never_accepts_impersonation(self):
        security=module.GuestSecurity.__new__(module.GuestSecurity)
        closed=[];elevation=[1];impersonated=[False]
        def open_thread(*args):
            if impersonated[0]:C.cast(args[-1],C.POINTER(module.PTR))[0]=66;return 1
            return 0
        def open_process(process,rights,pointer):C.cast(pointer,C.POINTER(module.PTR))[0]=55;return 1
        def information(token,kind,buffer,size,written):
            if kind==20:C.cast(buffer,C.POINTER(module.U32))[0]=elevation[0];C.cast(written,C.POINTER(module.U32))[0]=4;return 1
            C.cast(written,C.POINTER(module.U32))[0]=16
            if buffer is None:return 0
            C.cast(buffer,C.POINTER(module.PTR))[0]=77;return 1
        security.kernel=SimpleNamespace(GetCurrentThread=lambda:1,GetCurrentProcess=lambda:2,CloseHandle=lambda value:closed.append(value.value))
        security.security=SimpleNamespace(OpenThreadToken=open_thread,OpenProcessToken=open_process,GetTokenInformation=information)
        security._sid=Mock(return_value='S-1-5-21-1');library=SimpleNamespace(IsUserAnAdmin=Mock(return_value=1))
        with patch.object(module.C,'get_last_error',create=True,return_value=1008),patch.object(module.C,'WinDLL',create=True,return_value=library):
            self.assertEqual(security.current_user(),'S-1-5-21-1');elevation[0]=0
            with self.assertRaises(ContractError):security.current_user()
            impersonated[0]=True
            with self.assertRaises(module.NativeError):security.current_user()
        self.assertEqual(closed,[55,55,66])
    def test_fixed_admin_configuration_is_acl_checked_and_cross_root_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();config=configuration();value=declaration(config,config['ip_tunnels']['peer'])
            (root/'external-config.json').write_text(json.dumps(config));(root/'endpoint.json').write_text(json.dumps(value))
            security=SimpleNamespace(verify=Mock())
            with patch.object(module,'guest_root',return_value=root),patch.object(module,'GuestSecurity',return_value=security),\
                 patch.object(external,'native_machine',return_value={'machine_uuid':config['machine_uuid']}):
                self.assertEqual(module.read_configuration(root/'external-config.json'),config)
                with self.assertRaises(ContractError):module.read_configuration(root/'other-config.json')
            checked=[row.args[0] for row in security.verify.call_args_list]
            self.assertIn(root/'endpoint.json',checked);self.assertIn(root/'external-config.json',checked);self.assertNotIn(root/'other-config.json',checked)


class MaterialsTests(unittest.TestCase):
    def test_materials_are_new_source_only_and_marker_binds_exact_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();target=root/'new';config=configuration()
            value=module.materials(Path(__file__).resolve().parents[2],target,config,'a'*64,1)
            self.assertFalse(value['installed']);self.assertFalse(value['host_network_modified'])
            self.assertFalse((target/'wintun.dll').exists());data=json.loads((target/'endpoint.json').read_text())
            self.assertFalse(data['allow_driver_install']);self.assertIn('ctflab_windows_ip.py',data['runtime_sha256'])
            module.marker(data,config,config['ip_tunnels']['peer'])
            before=(target/'MANIFEST.json').read_bytes()
            with self.assertRaises(FileExistsError):module.materials(Path(__file__).resolve().parents[2],target,config,'a'*64,1)
            self.assertEqual((target/'MANIFEST.json').read_bytes(),before)
    def test_isolated_cli_generates_materials_without_native_deployment(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();config=root/'config.json'
            config.write_text(json.dumps(configuration()));config.chmod(0o600)
            target=root/'materials';script=Path(__file__).resolve().parents[1]/'ctflab_external.py'
            environment=dict(os.environ);environment.pop('SSH_ORIGINAL_COMMAND',None)
            result=subprocess.run([sys.executable,'-I','-B',str(script),'materials-windows-ip',
                '--config',str(config),'--destination',str(target),'--wintun-sha256','a'*64,
                '--driver-version','0x1'],env=environment,capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
            evidence=json.loads(result.stdout);self.assertFalse(evidence['native_verified'])
            self.assertFalse(evidence['host_network_modified']);self.assertFalse(evidence['installed'])
            self.assertEqual(json.loads((target/'endpoint.json').read_text())['driver_version'],1)
            self.assertFalse((target/'wintun.dll').exists())
    def test_invalid_native_declaration_refused_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();target=root/'missing'
            with self.assertRaises(ContractError):module.materials(Path(__file__).resolve().parents[2],target,configuration(),'bad',1)
            self.assertFalse(target.exists())


if __name__=='__main__':unittest.main()
