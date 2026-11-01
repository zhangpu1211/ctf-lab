"""IPv4策略、固定SSH转送和TUN调用替身；不打开宿主TUN、不操作VM。"""
import base64
import copy
import json
from pathlib import Path
import struct
import sys
import unittest
import uuid
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError
from ctflab_external import ExternalAgent,ExternalSession
from ctflab_external_ip import policy,policy_sha,checksum,packet,PacketGate,NativeEndpoint,Circuit
from ctflab_generation_store import digest
import ctflab_external
from test_ctflab_external import config


def specification():
    return {'schema':1,'local':'10.230.0.1','peer':'10.230.0.2','mtu':1200,
        'flows':[{'initiator':'local','protocol':'udp','ports':[53]},
                 {'initiator':'local','protocol':'tcp','ports':[80]},
                 {'initiator':'local','protocol':'icmp','ports':[]}]}


def raw_packet(protocol='udp',*,source='10.230.0.1',destination='10.230.0.2',
               a=30000,b=None,flags=2,payload=b'x',icmp_type=8):
    import ipaddress
    number={'tcp':6,'udp':17,'icmp':1}[protocol]
    addresses=ipaddress.IPv4Address(source).packed+ipaddress.IPv4Address(destination).packed
    if protocol=='udp':body=struct.pack('!HHHH',a,53 if b is None else b,8+len(payload),0)+payload
    elif protocol=='tcp':body=struct.pack('!HHIIBBHHH',a,80 if b is None else b,0,0,0x50,flags,65535,0,0)+payload
    else:body=struct.pack('!BBHHH',icmp_type,0,0,123,1)+payload
    if protocol in ('tcp','icmp'):
        pseudo=addresses+bytes((0,number))+struct.pack('!H',len(body)) if protocol=='tcp' else b''
        offset=16 if protocol=='tcp' else 2
        body=body[:offset]+struct.pack('!H',checksum(pseudo+body))+body[offset+2:]
    header=struct.pack('!BBHHHBBH',0x45,0,20+len(body),0,0x4000,64,number,0)+addresses
    return header[:10]+struct.pack('!H',checksum(header))+header[12:]+body


class PolicyTests(unittest.TestCase):
    def test_exact_private_endpoints_and_bounded_protocols(self):
        self.assertEqual(policy(specification()),specification())
        for change in ({'local':'127.0.0.1'},{'peer':'8.8.8.8'},{'peer':'10.230.0.1'},
                       {'local':'10.230.0.1/32'},{'mtu':True},{'mtu':1501},{'mtu':575},{'command':'ip'}):
            with self.subTest(change=change),self.assertRaises((ContractError,ValueError)):
                policy(dict(specification(),**change))
        for flow in ({'initiator':'local','protocol':'raw','ports':[]},
                     {'initiator':'local','protocol':'udp','ports':[22]},
                     {'initiator':'peer','protocol':'icmp','ports':[80]}):
            with self.assertRaises(ContractError):policy(dict(specification(),flows=[flow]))

    def test_header_spoof_fragment_options_ttl_checksum_and_mtu_refused(self):
        good=raw_packet();self.assertEqual(packet(good,specification(),True)[:3],('udp',30000,53))
        invalid=[good[:24],good+b'x',raw_packet(source='10.230.0.3'),raw_packet(payload=b'x'*1200)]
        for index,value in ((0,0x46),(6,0x20),(6,0x80),(7,1),(8,0),(10,0)):
            changed=bytearray(good);changed[index]=value
            if index!=10:changed[10:12]=b'\0\0';changed[10:12]=struct.pack('!H',checksum(bytes(changed[:20])))
            invalid.append(bytes(changed))
        for raw in invalid:
            with self.subTest(raw=raw[:20].hex()),self.assertRaises(ContractError):packet(raw,specification(),True)

    def test_transport_length_and_tcp_checksum_refused(self):
        for good,index in ((raw_packet('tcp'),30),(raw_packet(),25)):
            bad=bytearray(good);bad[index]^=1
            with self.assertRaises(ContractError):packet(bytes(bad),specification(),True)
        invalid=raw_packet(source='10.230.0.2',destination='10.230.0.1')
        with self.assertRaises(ContractError):packet(invalid,specification(),True)

    def test_stateful_udp_return_and_unknown_return_denied(self):
        gate=PacketGate(specification())
        reply=raw_packet(source='10.230.0.2',destination='10.230.0.1',a=53,b=30000)
        with self.assertRaises(ContractError):gate.accept(reply,outbound=False)
        gate.accept(raw_packet(),outbound=True);gate.accept(reply,outbound=False)
        with self.assertRaises(ContractError):gate.accept(raw_packet(b=54),outbound=True)

    def test_tcp_initial_syn_and_bound_return(self):
        gate=PacketGate(specification())
        with self.assertRaises(ContractError):gate.accept(raw_packet('tcp',flags=16),outbound=True)
        gate.accept(raw_packet('tcp'),outbound=True)
        gate.accept(raw_packet('tcp',source='10.230.0.2',destination='10.230.0.1',a=80,b=30000,flags=18),outbound=False)
        with self.assertRaises(ContractError):gate.accept(raw_packet('tcp',source='10.230.0.2',destination='10.230.0.1',a=80,b=30001,flags=18),outbound=False)

    def test_icmp_echo_only_and_expired_reply(self):
        now=[0];gate=PacketGate(specification(),clock=lambda:now[0])
        gate.accept(raw_packet('icmp'),outbound=True)
        reply=raw_packet('icmp',source='10.230.0.2',destination='10.230.0.1',icmp_type=0)
        gate.accept(reply,outbound=False)
        with self.assertRaises(ContractError):gate.accept(raw_packet('icmp',source='10.230.0.2',destination='10.230.0.1'),outbound=False)
        now[0]=61
        with self.assertRaises(ContractError):gate.accept(reply,outbound=False)

    def test_active_flow_table_is_bounded(self):
        gate=PacketGate(specification(),clock=lambda:0)
        for port in range(30000,30256):gate.accept(raw_packet(a=port),outbound=True)
        with self.assertRaises(ContractError):gate.accept(raw_packet(a=30256),outbound=True)


def error_packet(original, *, kind=3, code=3, mtu=0, quoted=None):
    body=struct.pack('!BBHHH',kind,code,0,0,mtu)+(original[:28] if quoted is None else quoted)
    body=body[:2]+struct.pack('!H',checksum(body))+body[4:]
    header=struct.pack('!BBHHHBBH',0x45,0,20+len(body),0,0x4000,64,1,0)+original[16:20]+original[12:16]
    return header[:10]+struct.pack('!H',checksum(header))+header[12:]+body


class ErrorGateTests(unittest.TestCase):
    def gate(self, **kwargs):return PacketGate(dict(specification(),icmp_errors=True),**kwargs)

    def test_errors_require_explicit_opt_in_and_exact_seen_packet(self):
        raw=raw_packet();error=error_packet(raw)
        legacy=PacketGate(specification());legacy.accept(raw,outbound=True)
        with self.assertRaises(ContractError):legacy.accept(error,outbound=False)
        gate=self.gate()
        with self.assertRaises(ContractError):gate.accept(error,outbound=False)
        gate.accept(raw,outbound=True);gate.accept(error,outbound=False)
        self.assertEqual(len(gate.flows),1)
        with self.assertRaises(ContractError):gate.accept(error_packet(raw_packet(a=30001)),outbound=False)

    def test_pmtu_requires_smaller_safe_mtu_and_df(self):
        raw=raw_packet('tcp',payload=b'x'*800);gate=self.gate();gate.accept(raw,outbound=True)
        gate.accept(error_packet(raw,code=4,mtu=600),outbound=False)
        for mtu in (0,575,len(raw),1500):
            with self.subTest(mtu=mtu),self.assertRaises(ContractError):gate.accept(error_packet(raw,code=4,mtu=mtu),outbound=False)
        quoted=bytearray(raw[:28]);quoted[6:8]=b'\0\0';quoted[10:12]=b'\0\0'
        quoted[10:12]=struct.pack('!H',checksum(bytes(quoted[:20])))
        with self.assertRaises(ContractError):gate.accept(error_packet(raw,code=4,mtu=600,quoted=bytes(quoted)),outbound=False)

    def test_truncated_spoof_nested_redirect_and_corrupt_quotes_rejected(self):
        raw=raw_packet();gate=self.gate();gate.accept(raw,outbound=True)
        for quote in (raw[:27],raw_packet(source='10.230.0.3')[:28],raw_packet('icmp')[:28],
                      bytes([0x46])+raw[1:28],raw[:10]+b'xx'+raw[12:28]):
            with self.subTest(quote=quote.hex()),self.assertRaises(ContractError):gate.accept(error_packet(raw,quoted=quote),outbound=False)
        for kind,code in ((5,0),(12,0),(3,16),(11,2)):
            with self.assertRaises(ContractError):gate.accept(error_packet(raw,kind=kind,code=code),outbound=False)
        with self.assertRaises(ContractError):gate.accept(error_packet(raw),outbound=True)

    def test_ttl_decrement_allowed_but_error_never_renews_authorization(self):
        now=[0];gate=self.gate(clock=lambda:now[0]);raw=raw_packet();gate.accept(raw,outbound=True)
        quoted=bytearray(raw[:28]);quoted[8]-=1;quoted[10:12]=b'\0\0'
        quoted[10:12]=struct.pack('!H',checksum(bytes(quoted[:20])))
        now[0]=59;gate.accept(error_packet(raw,kind=11,code=0,quoted=bytes(quoted)),outbound=False)
        now[0]=60
        with self.assertRaises(ContractError):gate.accept(error_packet(raw),outbound=False)

    def test_recent_quotes_evict_oldest_without_interrupting_normal_data(self):
        gate=self.gate(clock=lambda:0)
        # 同一UDP流，不同IP ID，保持流数1而达到引用上限。
        for number in range(1024):
            raw=bytearray(raw_packet());raw[4:6]=struct.pack('!H',number);raw[10:12]=b'\0\0'
            raw[10:12]=struct.pack('!H',checksum(bytes(raw[:20])))
            gate.accept(bytes(raw),outbound=True)
        newest=raw_packet(a=30002);gate.accept(newest,outbound=True)
        self.assertEqual(len(gate.recent),1024);self.assertEqual(len(gate.flows),2)
        gate.accept(error_packet(newest),outbound=False)
        with self.assertRaises(ContractError):gate.accept(error_packet(raw_packet()),outbound=False)
        # 不同原始引用的差错仍不能被新引用授权。
        with self.assertRaises(ContractError):gate.accept(error_packet(raw_packet(a=30003)),outbound=False)

    def test_nonboolean_opt_in_rejected(self):
        for value in (1,0,'true',None):
            with self.assertRaises(ContractError):policy(dict(specification(),icmp_errors=value))


class Endpoint:
    def __init__(self,spec,configuration,channel):self.queue=[];self.sent=[];self.closed=False;self.spec=spec
    def receive(self):return self.queue.pop(0) if self.queue else None
    def send(self,data):self.sent.append(data)
    def close(self):self.closed=True


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.configuration=config();self.configuration['ip_tunnels']={'peer':specification()}
        self.configuration['principals']['runner'].append('peer');self.endpoints=[]
        def factory(*args):endpoint=Endpoint(*args);self.endpoints.append(endpoint);return endpoint
        self.agent=ExternalAgent(self.configuration,'runner',observe=lambda:{'system':'Linux',
            'native_verified':True,'machine_uuid':self.configuration['machine_uuid']},ip_factory=factory)
        self.addCleanup(self.agent.close)
        self.challenge=str(uuid.uuid4());self.agent.handle('ext-handshake',{'challenge':self.challenge})
        self.channel=str(uuid.uuid4())
        self.params={k:self.configuration[k] for k in ('node_uuid','cohort_uuid','checkpoint_uuid','generation')}
        self.params.update(challenge=self.challenge,channel_id=self.channel)

    def open(self):return self.agent.handle('ext-ip-open',dict(self.params,tunnel='peer'))
    def call(self,action,sequence,**extra):return self.agent.handle(action,dict(self.params,sequence=sequence,**extra))

    def test_open_binds_policy_and_preserves_packet_boundary(self):
        self.assertEqual(self.open()['policy_sha256'],policy_sha(specification()))
        self.endpoints[0].queue=[raw_packet()]
        response=self.call('ext-ip-receive',1)
        self.assertEqual(base64.b64decode(response['data']),raw_packet())
        reply=raw_packet(source='10.230.0.2',destination='10.230.0.1',a=53,b=30000)
        sent=self.call('ext-ip-send',2,data=base64.b64encode(reply).decode())
        self.assertFalse(sent['application_result_verified']);self.assertEqual(self.endpoints[0].sent,[reply])
        self.assertFalse(self.call('ext-ip-receive',3)['received'])

    def test_opt_in_error_roundtrip_uses_authenticated_channel_without_new_flow(self):
        self.configuration['ip_tunnels']['peer']['icmp_errors']=True
        self.open();raw=raw_packet();self.endpoints[0].queue=[raw]
        self.call('ext-ip-receive',1)
        error=error_packet(raw)
        self.call('ext-ip-send',2,data=base64.b64encode(error).decode())
        self.assertEqual(self.endpoints[0].sent,[error])

    def test_spoof_packet_closes_before_endpoint_write(self):
        self.open()
        with self.assertRaises(ContractError):self.call('ext-ip-send',1,data=base64.b64encode(raw_packet()).decode())
        self.assertTrue(self.endpoints[0].closed);self.assertEqual(self.endpoints[0].sent,[])

    def test_sequence_replay_does_not_reinject(self):
        spec=self.configuration['ip_tunnels']['peer'];spec['flows'][0]['initiator']='peer'
        self.open();raw=raw_packet(source=spec['peer'],destination=spec['local'])
        self.call('ext-ip-send',1,data=base64.b64encode(raw).decode())
        with self.assertRaises(ContractError):self.call('ext-ip-send',1,data=base64.b64encode(raw).decode())
        self.assertEqual(self.endpoints[0].sent,[raw]);self.assertTrue(self.endpoints[0].closed)

    def test_unknown_principal_tunnel_or_old_generation_never_opens(self):
        self.configuration['principals']['runner'].remove('peer')
        with self.assertRaises(ContractError):self.open()
        self.assertEqual(self.endpoints,[])
        self.configuration['principals']['runner'].append('peer');self.params['generation']=2
        with self.assertRaises(ContractError):self.open()
        self.assertEqual(self.endpoints,[])

    def test_budget_drift_and_tcp_action_close_tun(self):
        self.open();self.endpoints[0].queue=[raw_packet()];self.configuration['max_bytes']=1
        with self.assertRaises(ContractError):self.call('ext-ip-receive',1)
        self.assertTrue(self.endpoints[0].closed)

    def test_tcp_actions_cannot_read_tun(self):
        self.open()
        with self.assertRaises(ContractError):self.call('ext-read',1)
        self.assertTrue(self.endpoints[0].closed)

    def test_client_ip_policy_digest_mismatch_closes(self):
        outer=self
        class Session:
            def __init__(self,*args,**kwargs):pass
            def request(self,action,params):
                if action=='ext-handshake':outer.agent.challenge=None
                result=outer.agent.handle(action,params)
                if action=='ext-ip-open':result['policy_sha256']='a'*64
                return result
            def close(self,**kwargs):outer.agent.close()
        expected={k:self.configuration[k] for k in ('node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation','kind')}
        expected['agent_sha256']=digest(Path(ctflab_external.__file__))
        client=ExternalSession({'server_uuid':expected['node_uuid']},expected,factory=Session)
        with self.assertRaises(ContractError):client.open_ip('peer')
        self.assertTrue(client.closed);self.assertTrue(self.endpoints[0].closed)


class NativeTests(unittest.TestCase):
    def test_host_platform_denied_before_tun_open(self):
        with patch('ctflab_external_ip.platform.system',return_value='Darwin'),patch('ctflab_external_ip.os.open',side_effect=AssertionError('不能打开宿主TUN')):
            with self.assertRaises(ContractError):NativeEndpoint(specification(),config(),str(uuid.uuid4()))

    def test_preflight_denies_address_or_specific_route_overlap(self):
        endpoint=NativeEndpoint.__new__(NativeEndpoint);endpoint.specification=specification()
        for rows in ([{'addr_info':[{'family':'inet','local':'10.230.0.10','prefixlen':24}]}],[]):
            routes=[] if rows else [{'dst':'10.230.0.2/32'}]
            endpoint.call=Mock(side_effect=[json.dumps(rows).encode(),json.dumps(routes).encode()])
            with self.assertRaises(ContractError):endpoint.preflight_addresses()
        endpoint.call=Mock(side_effect=[b'[]',b'[{"dst":"default"}]'])
        endpoint.preflight_addresses()

    def test_close_only_own_fd_and_never_deletes_other_interface(self):
        endpoint=NativeEndpoint.__new__(NativeEndpoint);endpoint.fd=44;endpoint.closed=False
        with patch('ctflab_external_ip.os.close') as close,patch('ctflab_external_ip.subprocess.run',side_effect=AssertionError('不运行删除命令')):
            endpoint.close();endpoint.close()
        close.assert_called_once_with(44)

    def test_native_creation_uses_exclusive_nonpersistent_tun_and_fixed_commands(self):
        import os,stat
        from types import SimpleNamespace
        import fcntl
        calls=[];configuration=config();channel=str(uuid.uuid4())
        marker={k:None for k in ('schema','role','machine_uuid','node_uuid','cohort_uuid','checkpoint_uuid',
            'generation','policies','runtime_sha256','ip_sha256')};marker.update(schema=1,role='external-ip-endpoint')
        info=SimpleNamespace(st_mode=stat.S_IFCHR,st_rdev=os.makedev(10,200),st_dev=1,st_ino=1)
        def call(endpoint,args):calls.append(args);return b'[]' if '-j' in args else b''
        with patch('ctflab_external_ip.platform.system',return_value='Linux'),patch('ctflab_external_ip.os.geteuid',return_value=0),\
             patch('ctflab_guest_agent.guarded_file',return_value=marker),patch.object(NativeEndpoint,'guard'),\
             patch.object(NativeEndpoint,'call',call),patch.object(Path,'lstat',return_value=info),\
             patch.object(Path,'stat',return_value=SimpleNamespace(st_ino=55)),patch.object(Path,'read_text',return_value='5'),\
             patch('ctflab_external_ip.os.open',return_value=44),patch('ctflab_external_ip.os.fstat',return_value=info),\
             patch('ctflab_external_ip.os.close') as close,patch.object(fcntl,'ioctl',side_effect=lambda fd,request,value:value) as ioctl:
            endpoint=NativeEndpoint(specification(),configuration,channel)
            endpoint.close()
        name='ctl'+channel.replace('-','')[:12]
        self.assertEqual(ioctl.call_args.args,(44,0x400454ca,struct.pack('16sH22x',name.encode(),0x9001)))
        self.assertIn(['-4','address','add','10.230.0.1/32','peer','10.230.0.2/32','dev',name],calls)
        self.assertIn(['link','set','dev',name,'addrgenmode','none'],calls)
        self.assertIn(['link','set','dev',name,'mtu','1200','up'],calls)
        self.assertFalse(any('default' in command or 'delete' in command for command in calls))
        close.assert_called_once_with(44)


class CircuitTests(unittest.TestCase):
    def pair(self):
        a=specification();b=copy.deepcopy(a);b['local'],b['peer']=a['peer'],a['local']
        for flow in b['flows']:flow['initiator']='peer'
        left=Mock();right=Mock();cohort=str(uuid.uuid4())
        for session,spec in ((left,a),(right,b)):
            session.report={'ip_tunnels':{'test':spec}};session.expected={'cohort_uuid':cohort,'generation':1,'machine_uuid':str(uuid.uuid4())}
            session.open_ip.return_value=str(uuid.uuid4());session.receive_ip.return_value=None
        return left,right

    def test_explicit_pair_checks_and_forwards_both_directions_once(self):
        left,right=self.pair();circuit=Circuit(left,'test',right,'test')
        reply=raw_packet(source='10.230.0.2',destination='10.230.0.1',a=53,b=30000)
        left.receive_ip.return_value=raw_packet();right.receive_ip.return_value=reply
        self.assertEqual(circuit.step()['forwarded_bytes'],[29,29])
        right.send_ip.assert_called_once_with(right.open_ip.return_value,raw_packet())
        left.send_ip.assert_called_once_with(left.open_ip.return_value,reply)
        circuit.close();left.close.assert_called_once();right.close.assert_called_once()

    def test_wrong_generation_or_asymmetric_policy_closes_before_open(self):
        for change in ('generation','policy'):
            left,right=self.pair()
            if change=='generation':right.expected['generation']=2
            else:right.report['ip_tunnels']['test']['flows'][0]['ports']=[54]
            with self.assertRaises(ContractError):Circuit(left,'test',right,'test')
            left.open_ip.assert_not_called();right.open_ip.assert_not_called()
            left.close.assert_called_once();right.close.assert_called_once()

    def test_error_opt_in_must_be_symmetric(self):
        left,right=self.pair();left.report['ip_tunnels']['test']['icmp_errors']=True
        with self.assertRaises(ContractError):Circuit(left,'test',right,'test')
        left.open_ip.assert_not_called();right.open_ip.assert_not_called()

    def test_lost_write_closes_both_and_never_automatically_retries(self):
        left,right=self.pair();circuit=Circuit(left,'test',right,'test')
        left.receive_ip.return_value=raw_packet();right.send_ip.side_effect=OSError('一次注入后丢回复')
        with self.assertRaises(OSError):circuit.step()
        with self.assertRaises(ContractError):circuit.step()
        right.send_ip.assert_called_once();left.close.assert_called_once();right.close.assert_called_once()

    def test_cancel_after_first_open_never_opens_second_endpoint(self):
        left,right=self.pair();cancelled=[False]
        def opened(name):cancelled[0]=True;return str(uuid.uuid4())
        left.open_ip.side_effect=opened
        with self.assertRaises(ContractError):Circuit(left,'test',right,'test',cancel_requested=lambda:cancelled[0])
        left.open_ip.assert_called_once();right.open_ip.assert_not_called()
        left.close.assert_called_once();right.close.assert_called_once()

    def test_first_transport_cleanup_failure_still_closes_second(self):
        import subprocess
        left,right=self.pair();circuit=Circuit(left,'test',right,'test')
        left.close.side_effect=subprocess.TimeoutExpired('owned-transport',5)
        with self.assertRaises(ContractError):circuit.close()
        self.assertTrue(circuit.closed);right.close.assert_called_once()

    def test_real_agent_session_pair_enforces_both_packet_gates(self):
        configurations=[config(),config()];spec=specification();other=copy.deepcopy(spec)
        other['local'],other['peer']=spec['peer'],spec['local']
        for flow in other['flows']:flow['initiator']='peer'
        configurations[1]['cohort_uuid']=configurations[0]['cohort_uuid'];endpoints=[];sessions=[]
        for index,(configuration,specification_value) in enumerate(zip(configurations,(spec,other))):
            configuration['ip_tunnels']={'test':specification_value};configuration['principals']['runner'].append('test')
            def factory(*args):
                endpoint=Endpoint(*args);endpoints.append(endpoint);return endpoint
            agent=ExternalAgent(configuration,'runner',observe=lambda c=configuration:{'system':'Linux',
                'native_verified':True,'machine_uuid':c['machine_uuid']},ip_factory=factory)
            self.addCleanup(agent.close)
            class Transport:
                def __init__(self,config,*,purpose,agent=agent):self.agent=agent
                def request(self,action,params):return self.agent.handle(action,params)
                def close(self,**kwargs):self.agent.close()
            expected={k:configuration[k] for k in ('node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation','kind')}
            expected['agent_sha256']=digest(Path(ctflab_external.__file__))
            session=ExternalSession({'server_uuid':expected['node_uuid']},expected,factory=Transport)
            self.addCleanup(session.close);sessions.append(session)
        circuit=Circuit(sessions[0],'test',sessions[1],'test');self.addCleanup(circuit.close)
        endpoints[0].queue=[raw_packet()]
        self.assertEqual(circuit.step()['forwarded_bytes'],[29,0]);self.assertEqual(endpoints[1].sent,[raw_packet()])
        reply=raw_packet(source='10.230.0.2',destination='10.230.0.1',a=53,b=30000)
        endpoints[1].queue=[reply]
        self.assertEqual(circuit.step()['forwarded_bytes'],[0,29]);self.assertEqual(endpoints[0].sent,[reply])
        endpoints[0].queue=[raw_packet(source='10.230.0.5')]
        with self.assertRaises(ContractError):circuit.step()
        self.assertTrue(all(endpoint.closed for endpoint in endpoints))


class MaterialsTests(unittest.TestCase):
    def test_materials_are_complete_pinned_and_do_not_install(self):
        import tempfile
        from ctflab_external_ip import materials
        configuration=config();configuration['ip_tunnels']={'test':specification()}
        configuration['principals']['runner'].append('test')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();target=root/'new-kit'
            result=materials(Path(__file__).resolve().parents[2],target,configuration,'a'*64)
            self.assertFalse(result['installed']);self.assertFalse(result['host_network_modified'])
            marker=json.loads((target/'ctflab-external-ip.json').read_text())
            runtime={p.name:digest(p) for p in (target/'runtime').glob('*.py')}
            self.assertEqual(marker['runtime_sha256'],runtime)
            self.assertIn('ctflab_external_ip.py',runtime);self.assertIn('ctflab_external.py',runtime)
            self.assertEqual(marker['policies'],[policy_sha(specification())])
            manifest=json.loads((target/'MANIFEST.json').read_text())
            self.assertTrue(all(digest(target/name)==sha for name,sha in manifest['files'].items()))
            before=digest(target/'external-config.json')
            with self.assertRaises((OSError,ContractError)):materials(Path(__file__).resolve().parents[2],target,configuration,'a'*64)
            self.assertEqual(digest(target/'external-config.json'),before)
            # 独立材料运行时实际导入新模块并读取CLI帮助，不打开TUN/SSH。
            import subprocess
            result=subprocess.run([sys.executable,'-I','-B',str(target/'runtime/ctflab_external.py'),'relay-ip','--help'],capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([sys.executable,'-I','-B',str(target/'runtime/ctflab_external.py'),'materials-ip',
                '--config',str(target/'external-config.json'),'--destination',str(root/'second-kit'),
                '--ip-sha256','a'*64],capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue((root/'second-kit/runtime/ctflab_external_ip.py').is_file())

    def test_relay_checks_bounds_before_connecting(self):
        from ctflab_external_ip import relay
        with patch.object(ctflab_external,'ExternalSession',side_effect=AssertionError('不能连接')):
            for changes in ({'duration':0},{'duration':3601},{'interval_ms':1},{'duration':True}):
                with self.assertRaises(ContractError):relay({}, {},'a',{}, {},'b',**changes)

    def test_cancelled_relay_does_not_start_first_ssh(self):
        import threading
        from ctflab_external_ip import relay
        stop=threading.Event();stop.set()
        with patch.object(ctflab_external,'ExternalSession',side_effect=AssertionError('不能连接')):
            with self.assertRaises(ContractError):relay({'server_uuid':'a'},{},'a',{'server_uuid':'b'},{},'b',stop=stop)

    def test_cli_refuses_forced_command_to_use_outbound_relay(self):
        import subprocess,os
        program=Path(ctflab_external.__file__)
        result=subprocess.run([sys.executable,'-I','-B',str(program),'relay-ip',
            '--left-config','/missing','--left-expected','/missing','--left-tunnel','x',
            '--right-config','/missing','--right-expected','/missing','--right-tunnel','y'],
            env={**os.environ,'SSH_ORIGINAL_COMMAND':'ctflab-external-v1'},capture_output=True,timeout=10)
        self.assertEqual(result.returncode,2);self.assertEqual(result.stderr,b'')


class PipeTransportTests(unittest.TestCase):
    def test_real_jsonl_sessions_transfer_packets_over_owned_process_pipes(self):
        import tempfile
        import ctflab_remote
        program='''import base64,json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[2])
from ctflab_external import ExternalAgent
from ctflab_contract import canonical
c=json.loads(Path(sys.argv[1]).read_text())
request=base64.b64decode(sys.argv[3]);reply=base64.b64decode(sys.argv[4])
class Endpoint:
 def __init__(self,spec,*args):self.spec=spec;self.queue=[request] if spec['local']=='10.230.0.1' else [];self.sent=[]
 def receive(self):return self.queue.pop(0) if self.queue else None
 def send(self,data):
  self.sent.append(data)
  if self.spec['local']=='10.230.0.2':self.queue.append(reply)
 def close(self):pass
agent=ExternalAgent(c,'runner',observe=lambda:{'system':'Linux','native_verified':True,'machine_uuid':c['machine_uuid']},ip_factory=Endpoint)
try:
 for line in sys.stdin.buffer:
  v=json.loads(line);result=agent.handle(v['action'],v['parameters'])
  response={k:v[k] for k in ('protocol','version','server_uuid','request_id')};response['result']=result
  sys.stdout.write(canonical(response)+'\\n');sys.stdout.flush()
finally:agent.close()
'''
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();script=root/'fixed-fixture.py';script.write_text(program)
            left=config();right=config();right['cohort_uuid']=left['cohort_uuid']
            a=specification();b=copy.deepcopy(a);b['local'],b['peer']=a['peer'],a['local']
            for flow in b['flows']:flow['initiator']='peer'
            paths={};expected=[]
            for index,(configuration,spec) in enumerate(((left,a),(right,b))):
                configuration['ip_tunnels']={'test':spec};configuration['principals']['runner'].append('test')
                path=root/f'{index}.json';path.write_text(json.dumps(configuration));paths[configuration['node_uuid']]=path
                value={k:configuration[k] for k in ('node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation','kind')}
                value['agent_sha256']=digest(Path(ctflab_external.__file__));expected.append(value)
            reply=raw_packet(source=a['peer'],destination=a['local'],a=53,b=30000)
            def arguments(configuration,*,purpose):
                self.assertEqual(purpose,'external')
                return [sys.executable,'-I','-B',str(script),str(paths[configuration['server_uuid']]),
                    str(Path(__file__).resolve().parents[1]),base64.b64encode(raw_packet()).decode(),base64.b64encode(reply).decode()]
            with patch.object(ctflab_remote,'ssh_arguments',side_effect=arguments):
                with ExternalSession({'server_uuid':left['node_uuid']},expected[0]) as first,\
                     ExternalSession({'server_uuid':right['node_uuid']},expected[1]) as second:
                    processes=[first.session.process,second.session.process]
                    circuit=Circuit(first,'test',second,'test')
                    self.assertEqual(circuit.step()['forwarded_bytes'],[29,29]);circuit.close()
                self.assertTrue(all(process.poll() is not None for process in processes))


if __name__=='__main__':unittest.main()
