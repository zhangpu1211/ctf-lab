"""外部虚拟来宾身份/固定SSH服务流/跨节点恢复签名；全部字节与进程替身，不操作外部VM。"""
import base64
import copy
from datetime import datetime,timedelta,timezone
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import unittest
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from ctflab_contract import ContractError,canonical
from ctflab_generation_store import digest
from ctflab_external import ExternalAgent,ExternalSession,smbios_identity,settings,recovery_report,HEALTH
import ctflab_external


def config(kind='kali'):
    return {'schema':1,'node_uuid':str(uuid.uuid4()),'machine_uuid':str(uuid.uuid4()),'cohort_uuid':str(uuid.uuid4()),
        'checkpoint_uuid':str(uuid.uuid4()),'generation':1,'kind':kind,'principals':{'runner':['web']},
        'services':{'web':{'port':80,'protocol':'tcp'}},'max_channels':2,'max_bytes':4096,'expires':'2099-01-01T00:00:00Z'}


class Stream:
    def __init__(self):self.sent=[];self.closed=False;self.incoming=io.BytesIO(b'HTTP/1.0 200 OK\r\n\r\n')
    def settimeout(self,value):pass
    def sendall(self,data):self.sent.append(data)
    def recv(self,n):return self.incoming.read(n)
    def close(self):self.closed=True


class ExternalTests(unittest.TestCase):
    def setUp(self):
        self.config=config();self.opens=[];self.machine={'machine_uuid':self.config['machine_uuid'],'native_verified':True,'system':'Linux'}
        def connect(address,timeout):
            self.opens.append(address);stream=Stream();self.stream=stream;return stream
        self.agent=ExternalAgent(self.config,'runner',observe=lambda:self.machine,connect=connect)
        self.addCleanup(self.agent.close);self.challenge=str(uuid.uuid4())
    def params(self,channel=None,**fields):
        return {k:self.config[k] for k in ('node_uuid','cohort_uuid','checkpoint_uuid','generation')}|{
            'challenge':self.challenge,'channel_id':channel or str(uuid.uuid4())}|fields
    def handshake(self):return self.agent.handle('ext-handshake',{'challenge':self.challenge})
    def test_only_named_loopback_service_opens_and_control_actions_are_absent(self):
        report=self.handshake();self.assertFalse(report['provider_checkpoint_verified']);self.assertFalse(report['health_verified'])
        channel=str(uuid.uuid4());opened=self.agent.handle('ext-open',self.params(channel,service='web'))
        self.assertEqual(self.opens,[('127.0.0.1',80)])
        result=self.agent.handle('ext-write',self.params(channel,sequence=1,data=base64.b64encode(b'GET / HTTP/1.0\r\n\r\n').decode()))
        self.assertFalse(result['application_result_verified']);self.assertEqual(len(self.stream.sent),1)
        data=self.agent.handle('ext-read',self.params(channel,sequence=2));self.assertTrue(base64.b64decode(data['data']).startswith(b'HTTP'))
        with self.assertRaises(ContractError):self.agent.handle('shutdown',self.params(channel))
        self.assertTrue(self.stream.closed)
    def test_checkpoint_generation_challenge_or_hardware_drift_closes_without_new_send(self):
        self.handshake();channel=str(uuid.uuid4());self.agent.handle('ext-open',self.params(channel,service='web'))
        changed=self.params(channel,sequence=1,data=base64.b64encode(b'x').decode());changed['generation']=2
        with self.assertRaises(ContractError):self.agent.handle('ext-write',changed)
        self.assertEqual(self.stream.sent,[]);self.assertTrue(self.stream.closed)
        self.machine['machine_uuid']=str(uuid.uuid4())
        with self.assertRaises(ContractError):ExternalAgent(self.config,'runner',observe=lambda:self.machine)
    def test_control_ports_arbitrary_address_and_unknown_protocol_or_shell_are_rejected(self):
        for change in ({'port':22},{'port':2375},{'port':5901},{'protocol':'raw'},{'host':'8.8.8.8'},{'command':['sh']}):
            value=copy.deepcopy(self.config);value['services']['web'].update(change)
            with self.assertRaises(ContractError):settings(value)
        self.assertEqual(self.opens,[])

    def udp(self):
        import socket
        outer=self
        class Datagram(Stream):
            def __init__(inner):super().__init__();inner.packets=[b'one',b'',b'two'];inner.partial=False
            def send(inner,data):inner.sent.append(data);return len(data)-int(inner.partial)
            def recv(inner,n):
                if not inner.packets:raise socket.timeout()
                return inner.packets.pop(0)[:n]
        def connect(address,timeout):
            outer.opens.append(address);outer.stream=Datagram();return outer.stream
        self.config['services']['web']['protocol']='udp'
        self.agent.connect_datagram=connect
        self.handshake();identity=str(uuid.uuid4())
        self.agent.handle('ext-open',self.params(identity,service='web'))
        return identity

    def test_udp_preserves_packet_boundaries_zero_datagram_and_timeout(self):
        channel=self.udp();self.assertEqual(self.opens,[('127.0.0.1',80)])
        received=[]
        for sequence in range(1,5):
            reply=self.agent.handle('ext-datagram-receive',self.params(channel,sequence=sequence))
            received.append((base64.b64decode(reply['data']),reply['received']))
        self.assertEqual(received,[(b'one',True),(b'',True),(b'two',True),(b'',False)])
        for sequence,data in ((5,b'first'),(6,b''),(7,b'next')):
            self.agent.handle('ext-datagram-send',self.params(channel,sequence=sequence,data=base64.b64encode(data).decode()))
        self.assertEqual(self.stream.sent,[b'first',b'',b'next'])

    def test_udp_replay_or_partial_send_closes_without_retry(self):
        channel=self.udp();self.stream.partial=True
        params=self.params(channel,sequence=1,data=base64.b64encode(b'once').decode())
        with self.assertRaises(ContractError):self.agent.handle('ext-datagram-send',params)
        with self.assertRaises(ContractError):self.agent.handle('ext-datagram-send',params)
        self.assertEqual(self.stream.sent,[b'once']);self.assertTrue(self.stream.closed)

    def test_udp_budget_and_oversize_receive_refuse_truncated_result(self):
        channel=self.udp();self.stream.packets=[b'x'*(ctflab_external.CHUNK+100)]
        with self.assertRaises(ContractError):self.agent.handle('ext-datagram-receive',self.params(channel,sequence=1))
        self.assertTrue(self.stream.closed)

    def test_udp_receive_cannot_exceed_remaining_byte_budget(self):
        channel=self.udp();self.config['max_bytes']=2
        with self.assertRaises(ContractError):self.agent.handle('ext-datagram-receive',self.params(channel,sequence=1))
        self.assertTrue(self.stream.closed)

    def test_udp_zero_datagrams_are_bounded_and_tcp_action_refused(self):
        channel=self.udp();self.agent.channels[channel]['datagrams']=4096
        with self.assertRaises(ContractError):self.agent.handle('ext-datagram-send',self.params(channel,sequence=1,data=''))
        self.assertEqual(self.stream.sent,[])
        self.agent.challenge=None;channel=self.udp()
        with self.assertRaises(ContractError):self.agent.handle('ext-read',self.params(channel,sequence=1))
        self.assertTrue(self.stream.closed)

    def test_tcp_channel_refuses_udp_before_application_write(self):
        self.handshake();channel=str(uuid.uuid4());self.agent.handle('ext-open',self.params(channel,service='web'))
        with self.assertRaises(ContractError):self.agent.handle('ext-datagram-send',self.params(channel,sequence=1,data=''))
        self.assertEqual(self.stream.sent,[])

    def test_udp_expiry_or_configuration_drift_prevents_send(self):
        channel=self.udp();self.agent.current=lambda:dict(self.config,generation=2)
        with self.assertRaises(ContractError):self.agent.handle('ext-datagram-send',self.params(channel,sequence=1,data=''))
        self.assertTrue(self.stream.closed);self.assertEqual(self.stream.sent,[])

    def test_datagram_socket_creation_uses_ipv4_and_closes_failed_connect(self):
        import socket
        from unittest.mock import Mock,patch
        stream=Mock();stream.connect.side_effect=OSError('合成失败')
        with patch.object(ctflab_external.socket,'socket',return_value=stream) as create:
            with self.assertRaises(OSError):ctflab_external.datagram_connection(('127.0.0.1',53),2)
        create.assert_called_once_with(socket.AF_INET,socket.SOCK_DGRAM);stream.close.assert_called_once()

    def test_udp_client_opt_in_roundtrip_and_lost_send_no_replay(self):
        channel=self.udp();self.agent.drop(channel);self.agent.challenge=None
        outer=self;calls=[]
        class Session:
            def __init__(inner,config,*,purpose):self.assertEqual(purpose,'external')
            def request(inner,action,params):calls.append(action);return outer.agent.handle(action,params)
            def close(inner,**kw):outer.agent.close()
        expected={k:self.config[k] for k in ('node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation','kind')}
        expected['agent_sha256']=digest(Path(ctflab_external.__file__))
        client=ExternalSession({'server_uuid':self.config['node_uuid']},expected,factory=Session)
        self.addCleanup(client.close)
        with self.assertRaises(ContractError):client.open('web')
        self.assertEqual(calls,['ext-handshake'])
        identity=client.open('web',protocol='udp')
        self.assertEqual(client.receive_datagram(identity),b'one')
        self.assertEqual(client.receive_datagram(identity),b'')
        self.assertEqual(client.receive_datagram(identity),b'two')
        self.assertIsNone(client.receive_datagram(identity))
        with self.assertRaises(ContractError):client.write(identity,b'forbidden')
        original=client.session.request
        def lost(action,params):
            reply=original(action,params)
            if action=='ext-datagram-send':raise OSError('一次发送后丢回复')
            return reply
        client.session.request=lost
        with self.assertRaises(OSError):client.send_datagram(identity,b'once')
        with self.assertRaises(ContractError):client.send_datagram(identity,b'once')
        self.assertTrue(client.closed);self.assertEqual(self.stream.sent,[b'once'])
    def test_sequence_replay_and_byte_budget_do_not_duplicate_application_input(self):
        self.handshake();channel=str(uuid.uuid4());self.agent.handle('ext-open',self.params(channel,service='web'))
        params=self.params(channel,sequence=1,data=base64.b64encode(b'once').decode());self.agent.handle('ext-write',params)
        with self.assertRaises(ContractError):self.agent.handle('ext-write',params)
        self.assertEqual(self.stream.sent,[b'once']);self.assertTrue(self.stream.closed)
    def test_principal_expiry_and_current_configuration_change_revoke_channels(self):
        self.handshake();channel=str(uuid.uuid4());self.agent.handle('ext-open',self.params(channel,service='web'))
        self.agent.current=lambda:dict(self.config,generation=2)
        with self.assertRaises(ContractError):self.agent.handle('ext-read',self.params(channel,sequence=1))
        self.assertTrue(self.stream.closed)
    def test_external_client_uses_fixed_purpose_and_lost_write_never_retries(self):
        outer=self;calls=[];purposes=[]
        class Session:
            def __init__(inner,config,*,purpose):purposes.append(purpose)
            def request(inner,action,params):
                calls.append(action);reply=outer.agent.handle(action,params)
                if action=='ext-write':raise OSError('fixture lost reply after one write')
                return reply
            def close(inner,**kw):outer.agent.close()
        expected={k:self.config[k] for k in ('node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation','kind')}
        expected['agent_sha256']=digest(Path(ctflab_external.__file__))
        client=ExternalSession({'server_uuid':self.config['node_uuid']},expected,factory=Session)
        channel=client.open('web')
        with self.assertRaises(OSError):client.write(channel,b'once')
        self.assertTrue(client.closed);self.assertEqual(self.stream.sent,[b'once']);self.assertEqual(purposes,['external'])
        self.assertEqual(calls.count('ext-write'),1)
    def test_ssh_builder_has_only_two_fixed_purposes_and_never_enables_forwarding(self):
        import tempfile
        from ctflab_remote import ssh_arguments
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();binary=root/'ssh';binary.write_bytes(b'fixture-only-not-executed')
            identity=root/'identity';identity.write_bytes(b'fixture-key');identity.chmod(0o600)
            known=root/'known';known.write_bytes(b'fixture-host');known.chmod(0o600)
            value={'schema':1,'host':'example.invalid','port':22,'user':'runner','ssh':str(binary),'identity':str(identity),
                'known_hosts':str(known),'known_hosts_sha256':digest(known),'server_uuid':self.config['node_uuid']}
            arguments=ssh_arguments(value,purpose='external');self.assertEqual(arguments[-1],'ctflab-external-v1')
            self.assertIn('ClearAllForwardings=yes',arguments);self.assertNotIn('-L',arguments);self.assertNotIn('-D',arguments)
            with self.assertRaises(ContractError):ssh_arguments(value,purpose='shell')

    def test_raw_smbios_uuid_little_endian_and_virtual_vendor_guard(self):
        identity=uuid.uuid4();part=bytearray(25);part[0]=1;part[1]=25;part[4]=1;part[5]=2;part[8:24]=identity.bytes_le
        table=bytes(part)+b'VMware, Inc.\0VMware Virtual Platform\0\0'+b'\x7f\x04\0\0\0\0'
        raw=bytes([0,3,0,0])+struct.pack('<I',len(table))+table
        result=smbios_identity(raw);self.assertEqual(result['machine_uuid'],str(identity));self.assertTrue(result['native_verified'])
        for bad in (raw[:12],bytes([0,2,5,0])+raw[4:],raw.replace(b'VMware, Inc.',b'PhysicalOEM!')):
            with self.assertRaises((ContractError,ValueError)):smbios_identity(bad)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.key=Ed25519PrivateKey.generate();self.keys={'controller':self.key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()}
        self.now=datetime(2026,10,26,tzinfo=timezone.utc);self.expected={};self.reports={};self.receipts={};cohort=str(uuid.uuid4())
        for name,kind in (('kali','kali'),('dc','ad-dc'),('member','ad-member')):
            spec=config(kind);spec['cohort_uuid']=cohort
            expected={k:spec[k] for k in ('node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation','kind')}
            expected['agent_sha256']='a'*64;self.expected[name]=expected
            report=dict(expected,challenge=str(uuid.uuid4()),native_guest_identity_verified=True)
            self.reports[name]=report
            payload={k:report[k] for k in ('node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation','challenge')}
            payload.update(schema=1,kind='external-course-checks',issued_at=self.now.isoformat(),expires=(self.now+timedelta(hours=1)).isoformat(),
                checks={key:{'passed':True,'evidence_sha256':'b'*64} for key in HEALTH[kind]})
            self.receipts[name]=self.envelope(payload)
    def envelope(self,payload):return {'key_id':'controller','payload':payload,'signature':base64.b64encode(self.key.sign(canonical(payload).encode())).decode()}
    def test_whole_cohort_needs_signed_fresh_new_auth_dns_time_and_vmgenid_receipts(self):
        result=recovery_report(self.expected,self.reports,self.receipts,self.keys,now=self.now)
        self.assertEqual(result['state'],'cohort-health-receipts-verified');self.assertFalse(result['vm_lifecycle_changed'])
        self.assertFalse(result['machine_acceptance_repeated'])
    def test_single_side_reset_or_old_challenge_never_passes_whole_cohort(self):
        self.reports['member']['checkpoint_uuid']=str(uuid.uuid4())
        with self.assertRaises(ContractError):recovery_report(self.expected,self.reports,self.receipts,self.keys,now=self.now)
    def test_missing_failed_or_expired_health_receipt_rejects_without_fabricating_domain_health(self):
        receipt=self.receipts['dc']['payload'];receipt['checks']['new-authentication']['passed']=False;self.receipts['dc']=self.envelope(receipt)
        with self.assertRaises(ContractError):recovery_report(self.expected,self.reports,self.receipts,self.keys,now=self.now)
        receipt['checks']['new-authentication']['passed']=True;self.receipts['dc']=self.envelope(receipt)
        with self.assertRaises(ContractError):recovery_report(self.expected,self.reports,self.receipts,self.keys,now=self.now+timedelta(hours=2))
    def test_unknown_signer_tamper_and_duplicate_machine_are_refused(self):
        with self.assertRaises(ContractError):recovery_report(self.expected,self.reports,self.receipts,{},now=self.now)
        self.expected['member']['machine_uuid']=self.expected['dc']['machine_uuid'];self.reports['member']['machine_uuid']=self.expected['dc']['machine_uuid']
        with self.assertRaises(ContractError):recovery_report(self.expected,self.reports,self.receipts,self.keys,now=self.now)


if __name__=='__main__':unittest.main()
