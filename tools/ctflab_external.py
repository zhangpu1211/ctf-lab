"""外部Kali/Windows/域节点的固定SSH TCP/UDP服务通道与恢复绑定；不管理外部VM生命周期或修改路由。"""
import argparse
import base64
import ctypes
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import struct
import sys
import uuid
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text,identifier,MAX_MESSAGE_BYTES
from ctflab_remote import SSHSession,PROTOCOL,decode,private_json
from ctflab_generation_store import digest

COMMAND='ctflab-external-v1'
CHUNK=16384
KINDS=('kali','windows','ad-dc','ad-member')
HEALTH={'kali':{'network-allow','network-deny','dns','mtu','reconnect','no-extra-egress'},
    'windows':{'network-allow','network-deny','service-access','log-collection'},
    'ad-dc':{'sysvol','netlogon','dns','time','new-authentication','domain-business','restore-without-partner','vmgenid-checked'},
    'ad-member':{'secure-channel','new-authentication','domain-business','vmgenid-checked'}}


def virtual_vendor(vendor,product):
    return (vendor in ('QEMU','Bochs') or vendor=='VMware, Inc.' and product.startswith('VMware')
        or vendor in ('innotek GmbH','Oracle Corporation') and product=='VirtualBox'
        or vendor=='Microsoft Corporation' and product=='Virtual Machine')


def smbios_identity(raw):
    require(type(raw) is bytes and 8<=len(raw)<=1024**2 and (raw[1],raw[2])>=(2,6)
        and struct.unpack('<I',raw[4:8])[0]==len(raw)-8,'capability-unverified')
    position=8;found=[];count=0
    while position<len(raw):
        count+=1;require(count<=4096 and position+4<=len(raw),'identity-unknown')
        kind,size=raw[position:position+2];require(size>=4 and position+size<=len(raw),'identity-unknown')
        end=raw.find(b'\0\0',position+size);require(end>=0,'identity-unknown')
        if kind==1:
            require(size>=24,'identity-unknown');part=raw[position:position+size]
            strings=raw[position+size:end].decode('ascii').split('\0')
            require(0<part[4]<=len(strings) and 0<part[5]<=len(strings),'identity-unknown')
            value=part[8:24];require(value not in (b'\0'*16,b'\xff'*16),'identity-unknown')
            found.append({'machine_uuid':str(uuid.UUID(bytes_le=value)),'vendor':strings[part[4]-1],'product':strings[part[5]-1]})
        position=end+2
        if kind==127:break
    require(len(found)==1 and virtual_vendor(found[0]['vendor'],found[0]['product']),'capability-unverified')
    return dict(found[0],native_verified=True)


def native_machine():
    if platform.system()=='Linux':
        root=Path('/sys/class/dmi/id');vendor=(root/'sys_vendor').read_text().strip();product=(root/'product_name').read_text().strip()
        require(virtual_vendor(vendor,product),'capability-unverified')
        machine=uuid_text((root/'product_uuid').read_text().strip().lower())
        return {'machine_uuid':machine,'vendor':vendor,'product':product,'native_verified':True,'system':'Linux'}
    require(platform.system()=='Windows' and ctypes.sizeof(ctypes.c_void_p)==8,'unsupported-platform')
    kernel=ctypes.WinDLL('kernel32.dll',winmode=0x800);call=kernel.GetSystemFirmwareTable
    call.argtypes=[ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32];call.restype=ctypes.c_uint32
    provider=int.from_bytes(b'RSMB','big');size=call(provider,0,None,0);require(8<=size<=1024**2,'identity-unknown')
    data=ctypes.create_string_buffer(size);require(call(provider,0,data,size)==size,'identity-unknown')
    return dict(smbios_identity(data.raw),system='Windows')


def settings(value):
    fields={'schema','node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation','kind','principals','services','max_channels','max_bytes','expires'}
    require(type(value) is dict and fields<=set(value)<=fields|{'ip_tunnels','event_sources'} and type(value['schema']) is int and value['schema']==1)
    for key in ('node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid'):uuid_text(value[key])
    require(value['kind'] in KINDS and type(value['generation']) is int and 1<=value['generation']<=2**31-1)
    require(type(value['max_channels']) is int and 1<=value['max_channels']<=4
        and type(value['max_bytes']) is int and 1<=value['max_bytes']<=16*1024**2)
    require(type(value['services']) is dict and 1<=len(value['services'])<=32)
    for name,entry in value['services'].items():
        identifier(name);require(type(entry) is dict and set(entry)=={'port','protocol'} and entry['protocol'] in ('tcp','udp')
            and type(entry['port']) is int and 1<=entry['port']<=65535 and entry['port'] not in (22,2375,2376)
            and not 5900<=entry['port']<=5999,'permission-denied')
    tunnels=value.get('ip_tunnels',{})
    require(type(tunnels) is dict and len(tunnels)<=4 and not set(tunnels)&set(value['services']))
    if tunnels:
        from ctflab_external_ip import policy
        require(value['kind'] in KINDS,'capability-unverified')
        for name,spec in tunnels.items():identifier(name);policy(spec)
    events=value.get('event_sources',{})
    require(type(events) is dict and len(events)<=4 and not set(events)&(set(value['services'])|set(tunnels)))
    if events:
        from ctflab_external_events import policy
        require(value['kind']!='kali','unsupported-platform')
        for name,spec in events.items():identifier(name);policy(spec)
    require(type(value['principals']) is dict and 1<=len(value['principals'])<=32)
    for name,allowed in value['principals'].items():
        identifier(name);require(type(allowed) is list and len(set(allowed))==len(allowed) and set(allowed)<=set(value['services'])|set(tunnels)|set(events))
    expiry=datetime.fromisoformat(value['expires'].replace('Z','+00:00'));require(expiry.tzinfo is not None)
    return value


def datagram_connection(address, timeout):
    """只由当前已授权服务提供回环地址；UDP connect固定收发对端。"""
    stream=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    try:
        stream.settimeout(timeout);stream.connect(address);return stream
    except BaseException:
        stream.close();raise


class ExternalAgent:
    def __init__(self,config,principal,*,observe=native_machine,connect=socket.create_connection,
                 connect_datagram=datagram_connection,ip_factory=None,events_factory=None,now=None,current=None):
        self.config=settings(config);identifier(principal);require(principal in config['principals'],'permission-denied')
        self.principal=principal;self.observe=observe;self.connect=connect;self.now=now or (lambda:datetime.now(timezone.utc));self.current=current
        self.connect_datagram=connect_datagram
        self.ip_factory=ip_factory
        self.events_factory=events_factory;self.event_snapshots={};self.event_attempts=set();self.event_bytes=0
        self.channels={};self.used=set();self.challenge=None;self.identity=self.guard()
    def guard(self):
        require(self.now()<datetime.fromisoformat(self.config['expires'].replace('Z','+00:00')),'permission-denied')
        if self.current:require(self.current()==self.config,'permission-denied')
        identity=self.observe();require(identity.get('system')==('Linux' if self.config['kind']=='kali' else 'Windows'),'unsupported-platform')
        require(identity.get('native_verified') is True and identity.get('machine_uuid')==self.config['machine_uuid'],'identity-unknown')
        return identity
    def close(self):
        for value in self.channels.values():
            try:value.get('socket',value.get('endpoint')).close()
            except (OSError,ValueError,RuntimeError):pass
        self.channels.clear()
        self.event_snapshots.clear()
    def drop(self,identity):
        value=self.channels.pop(identity,None)
        if value:value.get('socket',value.get('endpoint')).close()
    def events(self,action,params):
        from ctflab_external_events import Collector,MAX_SNAPSHOT
        fields={'node_uuid','cohort_uuid','checkpoint_uuid','generation','challenge','snapshot_id'}
        extra={'source'} if action=='ext-events-capture' else {'offset','sha256'}
        require(set(params)==fields|extra)
        require(self.challenge is not None and params['challenge']==self.challenge
            and type(params['generation']) is int
            and all(params[k]==self.config[k] for k in ('node_uuid','cohort_uuid','checkpoint_uuid','generation')),'identity-unknown')
        identity=uuid_text(params['snapshot_id'])
        if action=='ext-events-capture':
            source=params['source']
            require(type(source) is str and source in self.config['principals'][self.principal]
                and source in self.config.get('event_sources',{}),'permission-denied')
            if identity not in self.event_snapshots:
                require(identity not in self.event_attempts,'state-conflict')
                require(len(self.event_attempts)<4,'resource-busy')
                # 原标识先占位；查询中断/失败不能在同会话重复采集，重连也不自动恢复或重发。
                self.event_attempts.add(identity);self.event_snapshots[identity]=None
                collector=(self.events_factory or Collector)(self.config['machine_uuid'])
                spec=self.config['event_sources'][source]
                data,count=collector.collect(spec)
                self.guard()
                require(type(data) is bytes and len(data)<=min(MAX_SNAPSHOT,self.config['max_bytes'])
                    and type(count) is int and 0<=count<=spec['max_records'],'storage-insufficient')
                report={k:self.config[k] for k in ('node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation')}
                report.update(snapshot_id=identity,source=source,policy_sha256=hashlib.sha256(canonical(spec).encode()).hexdigest(),
                    sha256=hashlib.sha256(data).hexdigest(),size=len(data),records=count,native_collection=collector.is_native,
                    format='event-xml-json-v1',event_log_modified=False,health_verified=False,automatic_replay=False)
                self.event_snapshots[identity]=(source,data,report)
            entry=self.event_snapshots[identity]
            require(entry is not None and entry[0]==source,'state-conflict')
            return dict(entry[2])
        entry=self.event_snapshots.get(identity)
        require(entry is not None and params['sha256']==entry[2]['sha256'],'identity-unknown')
        offset=params['offset'];data=entry[1]
        require(type(offset) is int and 0<=offset<len(data) and offset%CHUNK==0)
        chunk=data[offset:offset+CHUNK]
        require(self.event_bytes+len(chunk)<=self.config['max_bytes'],'storage-insufficient')
        self.event_bytes+=len(chunk)
        return {'node_uuid':self.config['node_uuid'],'snapshot_id':identity,'sha256':entry[2]['sha256'],
            'offset':offset,'data':base64.b64encode(chunk).decode(),'eof':offset+len(chunk)==len(data)}
    def handle(self,action,params):
        require(type(params) is dict)
        network_changed=False
        try:
            machine=self.guard()
            if action=='ext-handshake':
                require(set(params)=={'challenge'});uuid_text(params['challenge']);require(self.challenge is None,'state-conflict')
                self.challenge=params['challenge']
                return {k:self.config[k] for k in ('node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation','kind')}|{
                    'challenge':self.challenge,'native_guest_identity_verified':True,'services':sorted(name for name in self.config['principals'][self.principal] if name not in self.config.get('event_sources',{})),
                    'service_protocols':{name:self.config['services'][name]['protocol'] for name in self.config['principals'][self.principal] if name in self.config['services']},
                    'ip_tunnels':{name:self.config['ip_tunnels'][name] for name in self.config['principals'][self.principal] if name in self.config.get('ip_tunnels',{})},
                    'event_sources':{name:self.config['event_sources'][name] for name in self.config['principals'][self.principal] if name in self.config.get('event_sources',{})},
                    'event_protocol':'bounded-event-xml-v1',
                    'agent_sha256':digest(Path(__file__)),'lifecycle':'manual-in-original-software','provider_checkpoint_verified':False,
                    'network_isolation_verified':False,'health_verified':False}
            if action in ('ext-events-capture','ext-events-read'):
                return self.events(action,params)
            fields={'node_uuid','cohort_uuid','checkpoint_uuid','generation','challenge','channel_id'}
            extra={'ext-open':{'service'},'ext-read':{'sequence'},'ext-write':{'sequence','data'},'ext-close':{'sequence'},
                   'ext-datagram-send':{'sequence','data'},'ext-datagram-receive':{'sequence'},
                   'ext-ip-open':{'tunnel'},'ext-ip-send':{'sequence','data'},'ext-ip-receive':{'sequence'}}
            require(action in extra and set(params)==fields|extra[action]);identity=uuid_text(params['channel_id'])
            require(self.challenge is not None and params['challenge']==self.challenge and all(params[k]==self.config[k] for k in ('node_uuid','cohort_uuid','checkpoint_uuid','generation'))
                and type(params['generation']) is int,'identity-unknown')
            if action in ('ext-open','ext-ip-open'):
                require(identity not in self.used and len(self.used)<4096 and len(self.channels)<self.config['max_channels'],'resource-busy')
                name=params['service'] if action=='ext-open' else params['tunnel']
                require(type(name) is str and name in self.config['principals'][self.principal],'permission-denied');self.used.add(identity)
                if action=='ext-ip-open':
                    require(name in self.config.get('ip_tunnels',{}),'permission-denied')
                    from ctflab_external_ip import NativeEndpoint,PacketGate,policy_sha
                    spec=self.config['ip_tunnels'][name]
                    endpoint_type=NativeEndpoint
                    if self.config['kind']!='kali':
                        from ctflab_windows_ip import WindowsEndpoint
                        endpoint_type=WindowsEndpoint
                    endpoint=(self.ip_factory or endpoint_type)(spec,self.config,identity)
                    network_changed=True
                    self.channels[identity]={'endpoint':endpoint,'gate':PacketGate(spec),'sequence':0,
                        'bytes':0,'protocol':'ipv4','packets':0}
                    result={'state':'channel-opened','sequence':0,'protocol':'ipv4','policy_sha256':policy_sha(spec)}
                else:
                    require(name in self.config['services'],'permission-denied');endpoint=self.config['services'][name]
                    connect=self.connect if endpoint['protocol']=='tcp' else self.connect_datagram
                    stream=connect(('127.0.0.1',endpoint['port']),timeout=2)
                    self.channels[identity]={'socket':stream,'sequence':0,'bytes':0,'protocol':endpoint['protocol'],'datagrams':0}
                    stream.settimeout(.2)
                    result={'state':'channel-opened','sequence':0,'protocol':endpoint['protocol']}
            else:
                require(identity in self.channels,'identity-unknown');entry=self.channels[identity]
                require(type(params['sequence']) is int and params['sequence']==entry['sequence']+1,'state-conflict');entry['sequence']=params['sequence']
                if action=='ext-close':
                    network_changed=entry['protocol']=='ipv4'
                    self.drop(identity);result={'state':'channel-closed','sequence':params['sequence']}
                elif action in ('ext-ip-send','ext-ip-receive'):
                    require(entry['protocol']=='ipv4' and entry['packets']<4096,'permission-denied');entry['packets']+=1
                    if action=='ext-ip-send':
                        require(type(params['data']) is str and len(params['data'])<=2000)
                        data=base64.b64decode(params['data'],validate=True)
                        require(entry['bytes']+len(data)<=self.config['max_bytes'],'storage-insufficient')
                        entry['gate'].accept(data,outbound=False);entry['bytes']+=len(data)
                        entry['endpoint'].send(data)
                        result={'state':'packet-sent','bytes':len(data),'sequence':entry['sequence'],'application_result_verified':False}
                    else:
                        require(entry['bytes']<self.config['max_bytes'],'storage-insufficient')
                        data=entry['endpoint'].receive()
                        if data is not None:
                            entry['gate'].accept(data,outbound=True)
                            require(entry['bytes']+len(data)<=self.config['max_bytes'],'storage-insufficient');entry['bytes']+=len(data)
                        result={'state':'packet-received','data':base64.b64encode(data or b'').decode(),
                            'received':data is not None,'sequence':entry['sequence']}
                elif action in ('ext-datagram-send','ext-datagram-receive'):
                    require(entry['protocol']=='udp','permission-denied')
                    require(entry['datagrams']<4096,'resource-busy')
                    entry['datagrams']+=1
                    if action=='ext-datagram-send':
                        require(type(params['data']) is str and len(params['data'])<=4*((CHUNK+2)//3))
                        data=base64.b64decode(params['data'],validate=True);require(len(data)<=CHUNK)
                        require(entry['bytes']+len(data)<=self.config['max_bytes'],'storage-insufficient')
                        entry['bytes']+=len(data)
                        require(entry['socket'].send(data)==len(data),'control-unreachable')
                        result={'state':'datagram-sent','bytes':len(data),'sequence':entry['sequence'],
                                'application_result_verified':False}
                    else:
                        require(entry['bytes']<self.config['max_bytes'],'storage-insufficient')
                        # 多读一字节识别超长数据报；绝不返回截断前缀或拆成下一包。
                        try:data=entry['socket'].recv(CHUNK+1);received=True
                        except socket.timeout:data=b'';received=False
                        require(len(data)<=CHUNK and entry['bytes']+len(data)<=self.config['max_bytes'],'storage-insufficient')
                        entry['bytes']+=len(data)
                        result={'state':'datagram-received','data':base64.b64encode(data).decode(),
                                'received':received,'sequence':entry['sequence']}
                elif action=='ext-write':
                    require(entry['protocol']=='tcp','permission-denied')
                    require(type(params['data']) is str and len(params['data'])<=4*((CHUNK+2)//3))
                    data=base64.b64decode(params['data'],validate=True);require(0<len(data)<=CHUNK)
                    require(entry['bytes']+len(data)<=self.config['max_bytes'],'storage-insufficient')
                    entry['bytes']+=len(data);entry['socket'].sendall(data)
                    result={'state':'bytes-sent','bytes':len(data),'sequence':entry['sequence'],'application_result_verified':False}
                else:
                    require(entry['protocol']=='tcp','permission-denied')
                    require(entry['bytes']<self.config['max_bytes'],'storage-insufficient')
                    try:data=entry['socket'].recv(min(CHUNK,self.config['max_bytes']-entry['bytes']));eof=not data
                    except socket.timeout:data=b'';eof=False
                    entry['bytes']+=len(data);result={'state':'bytes-received','data':base64.b64encode(data).decode(),'eof':eof,'sequence':entry['sequence']}
            self.guard()
            return dict(result,channel_id=identity,node_uuid=self.config['node_uuid'],vm_stopped=False,route_changed=False,route_scope='runner-host',host_network_modified=False,
                guest_network_change_requested=network_changed,guest_network_cleanup_verified=False,
                network_scope='dedicated-guest-interface' if network_changed else 'no-network-change',automatic_replay=False)
        except Exception:self.close();raise


class ExternalSession:
    def __init__(self,ssh_config,expected,*,factory=SSHSession):
        self.expected=expected;self.challenge=str(uuid.uuid4());self.closed=False;self.channels={};self.protocols={}
        require(type(expected) is dict and set(expected)=={'node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation','kind','agent_sha256'})
        require(ssh_config['server_uuid']==expected['node_uuid'],'identity-unknown')
        self.session=factory(ssh_config,purpose='external')
        try:
            report=self.session.request('ext-handshake',{'challenge':self.challenge})
            require(type(report) is dict and report.get('challenge')==self.challenge
                and report.get('native_guest_identity_verified') is True and all(report.get(k)==v for k,v in expected.items()),'identity-unknown')
            self.report=report
        except BaseException:self.session.close(failed=True);self.closed=True;raise
    def __enter__(self):return self
    def __exit__(self,*a):self.close()
    def params(self,identity):
        return {k:self.expected[k] for k in ('node_uuid','cohort_uuid','checkpoint_uuid','generation')}|{'challenge':self.challenge,'channel_id':identity}
    def collect_events(self,source,*,snapshot_id=None):
        """显式采集一次并校验分块；返回含敏感原始XML的字节，由调用方决定私有保存位置。"""
        from ctflab_external_events import MAX_SNAPSHOT,policy,parsed
        require(not self.closed,'control-unreachable')
        sources=self.report.get('event_sources',{})
        require(self.report.get('event_protocol')=='bounded-event-xml-v1' and type(sources) is dict
            and type(source) is str and source in sources,'capability-unverified')
        spec=policy(sources[source]);identity=uuid_text(snapshot_id or str(uuid.uuid4()))
        params={k:self.expected[k] for k in ('node_uuid','cohort_uuid','checkpoint_uuid','generation')}
        params.update(challenge=self.challenge,snapshot_id=identity)
        try:
            report=self.session.request('ext-events-capture',dict(params,source=source))
            report_fields={'node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation','snapshot_id','source',
                'policy_sha256','sha256','size','records','native_collection','format','event_log_modified','health_verified','automatic_replay'}
            require(type(report) is dict and set(report)==report_fields and all(report.get(k)==self.expected[k] for k in ('node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation'))
                and type(report.get('generation')) is int and report.get('snapshot_id')==identity and report.get('source')==source
                and report.get('policy_sha256')==hashlib.sha256(canonical(spec).encode()).hexdigest()
                and report.get('format')=='event-xml-json-v1' and report.get('event_log_modified') is False
                and report.get('automatic_replay') is False and report.get('health_verified') is False
                and type(report.get('native_collection')) is bool
                and type(report.get('records')) is int and 0<=report['records']<=spec['max_records']
                and type(report.get('size')) is int and 0<report['size']<=MAX_SNAPSHOT
                and type(report.get('sha256')) is str and len(report['sha256'])==64,'identity-unknown')
            data=bytearray()
            while len(data)<report['size']:
                reply=self.session.request('ext-events-read',dict(params,offset=len(data),sha256=report['sha256']))
                require(type(reply) is dict and reply.get('node_uuid')==self.expected['node_uuid']
                    and reply.get('snapshot_id')==identity and reply.get('sha256')==report['sha256']
                    and type(reply.get('offset')) is int and reply['offset']==len(data)
                    and type(reply.get('eof')) is bool and type(reply.get('data')) is str
                    and len(reply['data'])<=4*((CHUNK+2)//3),'identity-unknown')
                chunk=base64.b64decode(reply['data'],validate=True)
                require(len(chunk)==min(CHUNK,report['size']-len(data))
                    and reply['eof']==(len(data)+len(chunk)==report['size']),'identity-unknown')
                data.extend(chunk)
            require(hashlib.sha256(data).hexdigest()==report['sha256'],'identity-unknown')
            value=json.loads(data)
            require(canonical(value).encode()==data,'identity-unknown')
            require(type(value) is dict and set(value)=={'schema','policy','records'} and type(value['schema']) is int
                and value['schema']==1 and value['policy']==spec and type(value['records']) is list
                and len(value['records'])==report['records'],'identity-unknown')
            ids=[]
            for row in value['records']:
                require(type(row) is dict and canonical(parsed(row.get('xml'),spec))==canonical(row),'identity-unknown');ids.append(row['record_id'])
            require(ids==sorted(set(ids)),'identity-unknown')
            return report,bytes(data)
        except BaseException:self.session.close(failed=True);self.closed=True;raise
    def request(self,action,identity,**extra):
        require(not self.closed,'control-unreachable')
        try:
            reply=self.session.request(action,dict(self.params(identity),**extra))
            require(type(reply) is dict and reply.get('node_uuid')==self.expected['node_uuid'] and reply.get('channel_id')==identity
                and type(reply.get('sequence')) is int and (action in ('ext-open','ext-ip-open') and reply.get('sequence')==0 or action not in ('ext-open','ext-ip-open') and reply.get('sequence')==self.channels[identity]),'identity-unknown')
            return reply
        except BaseException:self.session.close(failed=True);self.closed=True;raise
    def open(self,service,*,protocol='tcp'):
        require(protocol in ('tcp','udp'))
        advertised=self.report.get('service_protocols',{})
        require(type(advertised) is dict and advertised.get(service,'tcp')==protocol,'capability-unverified')
        identity=str(uuid.uuid4());self.channels[identity]=0
        reply=self.request('ext-open',identity,service=service)
        if reply.get('protocol','tcp')!=protocol:
            self.session.close(failed=True);self.closed=True
            require(False,'identity-unknown')
        self.protocols[identity]=protocol
        return identity
    def write(self,identity,data):
        require(self.protocols.get(identity)=='tcp','permission-denied')
        require(type(data) is bytes and 0<len(data)<=CHUNK);self.channels[identity]+=1
        return self.request('ext-write',identity,sequence=self.channels[identity],data=base64.b64encode(data).decode())
    def read(self,identity):
        require(self.protocols.get(identity)=='tcp','permission-denied')
        self.channels[identity]+=1;reply=self.request('ext-read',identity,sequence=self.channels[identity])
        require(type(reply.get('data')) is str and len(reply['data'])<=4*((CHUNK+2)//3) and type(reply.get('eof')) is bool)
        data=base64.b64decode(reply['data'],validate=True);require(len(data)<=CHUNK);return data,reply['eof']
    def send_datagram(self,identity,data):
        require(self.protocols.get(identity)=='udp' and type(data) is bytes and len(data)<=CHUNK)
        self.channels[identity]+=1
        return self.request('ext-datagram-send',identity,sequence=self.channels[identity],data=base64.b64encode(data).decode())
    def receive_datagram(self,identity):
        require(self.protocols.get(identity)=='udp')
        self.channels[identity]+=1
        try:
            reply=self.request('ext-datagram-receive',identity,sequence=self.channels[identity])
            require(type(reply.get('received')) is bool and type(reply.get('data')) is str
                    and len(reply['data'])<=4*((CHUNK+2)//3))
            data=base64.b64decode(reply['data'],validate=True)
            require(len(data)<=CHUNK and (reply['received'] or not data))
            return data if reply['received'] else None
        except BaseException:
            self.session.close(failed=True);self.closed=True;raise
    def open_ip(self,tunnel):
        from ctflab_external_ip import policy_sha
        tunnels=self.report.get('ip_tunnels',{})
        require(type(tunnels) is dict and type(tunnel) is str and tunnel in tunnels,'capability-unverified')
        expected=policy_sha(tunnels[tunnel]);identity=str(uuid.uuid4());self.channels[identity]=0
        reply=self.request('ext-ip-open',identity,tunnel=tunnel)
        if reply.get('protocol')!='ipv4' or reply.get('policy_sha256')!=expected:
            self.session.close(failed=True);self.closed=True;require(False,'identity-unknown')
        self.protocols[identity]='ipv4';return identity
    def send_ip(self,identity,data):
        require(self.protocols.get(identity)=='ipv4' and type(data) is bytes and 28<=len(data)<=1500)
        self.channels[identity]+=1
        return self.request('ext-ip-send',identity,sequence=self.channels[identity],data=base64.b64encode(data).decode())
    def receive_ip(self,identity):
        require(self.protocols.get(identity)=='ipv4');self.channels[identity]+=1
        try:
            reply=self.request('ext-ip-receive',identity,sequence=self.channels[identity])
            require(type(reply.get('received')) is bool and type(reply.get('data')) is str and len(reply['data'])<=2000)
            data=base64.b64decode(reply['data'],validate=True)
            require(28<=len(data)<=1500 if reply['received'] else not data)
            return data if reply['received'] else None
        except BaseException:self.session.close(failed=True);self.closed=True;raise
    def close(self):
        if not self.closed:self.session.close();self.closed=True


def recovery_report(expected,reports,receipts,keys,*,now=None):
    """跨节点恢复须有独立控制者签名的新挑战健康证据；单边重置/旧认证不能整体ready。"""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    now=now or datetime.now(timezone.utc);require(isinstance(now,datetime) and now.tzinfo is not None)
    require(type(expected) is dict and set(expected)==set(reports)==set(receipts) and 1<=len(expected)<=32)
    cohorts=set();generations=set();nodes=[];node_ids=set();machine_ids=set()
    for name,spec in sorted(expected.items()):
        require(type(spec) is dict and set(spec)=={'node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation','kind','agent_sha256'}
            and spec['kind'] in KINDS and type(spec['generation']) is int and 1<=spec['generation']<=2**31-1)
        require(spec['node_uuid'] not in node_ids and spec['machine_uuid'] not in machine_ids,'identity-unknown')
        node_ids.add(spec['node_uuid']);machine_ids.add(spec['machine_uuid'])
        report=reports[name];require(all(report.get(k)==v for k,v in spec.items()) and report.get('native_guest_identity_verified') is True,'identity-unknown')
        uuid_text(report['challenge']);cohorts.add(spec['cohort_uuid']);generations.add(spec['generation'])
        envelope=receipts[name];require(type(envelope) is dict and set(envelope)=={'key_id','payload','signature'} and envelope['key_id'] in keys and type(envelope['signature']) is str and len(envelope['signature'])<=128,'permission-denied')
        payload=envelope['payload'];Ed25519PublicKey.from_public_bytes(bytes.fromhex(keys[envelope['key_id']])).verify(
            base64.b64decode(envelope['signature'],validate=True),canonical(payload).encode())
        require(type(payload) is dict and set(payload)=={'schema','kind','node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation','challenge','issued_at','expires','checks'}
            and type(payload['schema']) is int and payload['schema']==1 and payload['kind']=='external-course-checks'
            and all(payload[k]==report[k] for k in ('node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation','challenge')),'identity-unknown')
        issued=datetime.fromisoformat(payload['issued_at'].replace('Z','+00:00'));expiry=datetime.fromisoformat(payload['expires'].replace('Z','+00:00'))
        require(issued.tzinfo is not None and expiry.tzinfo is not None and issued<=now<expiry and (expiry-issued).total_seconds()<=86400,'permission-denied')
        checks=payload['checks'];require(type(checks) is dict and set(checks)==HEALTH[spec['kind']],'identity-unknown')
        for check,value in checks.items():
            require(type(value) is dict and set(value)=={'passed','evidence_sha256'} and value['passed'] is True
                and type(value['evidence_sha256']) is str and len(value['evidence_sha256'])==64
                and all(c in '0123456789abcdef' for c in value['evidence_sha256']),'identity-unknown')
        nodes.append({'node_uuid':spec['node_uuid'],'kind':spec['kind'],'checks':sorted(checks),'receipt_sha256':hashlib.sha256(canonical(envelope).encode()).hexdigest()})
    require(len(cohorts)==len(generations)==1,'state-conflict')
    return {'state':'cohort-health-receipts-verified','nodes':nodes,'generation':next(iter(generations)),
        'cohort_uuid':next(iter(cohorts)),'scope':'signed-controller-evidence-not-reexecuted-health-tests',
        'vm_lifecycle_changed':False,'route_changed':False,'machine_acceptance_repeated':False}


def save_events(ssh_config,expected,source,destination,*,factory=ExternalSession):
    """只写调用者指定私有目录里的新文件；失败保留现场，不覆盖或自动解析显示原文。"""
    from ctflab_tls_endpoint import guard
    destination=Path(destination).absolute();guard(destination.parent)
    require(not destination.exists() and not destination.is_symlink(),'state-conflict')
    with factory(ssh_config,expected) as session:report,data=session.collect_events(source)
    # 所有传输/摘要校验成功后才创建本机文件；新文件继承私有目录，跨平台再核对权限。
    fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:
        guard(destination)
        stream.write((canonical({'schema':1,'receipt':report,'snapshot':json.loads(data)})+'\n').encode())
        stream.flush();os.fsync(stream.fileno())
    return report


def serve(config_path,principal,source,destination,*,windows_ip_guest=False):
    reader=private_json
    if windows_ip_guest:
        from ctflab_windows_ip import read_configuration
        reader=read_configuration
    config=settings(reader(config_path))
    agent=ExternalAgent(config,principal,current=lambda:settings(reader(config_path)))
    try:
        for _ in range(1000000):
            raw=source.readline(MAX_MESSAGE_BYTES+2)
            if not raw:return
            require(raw.endswith(b'\n') and len(raw)<=MAX_MESSAGE_BYTES+1)
            value=decode(raw.rstrip(b'\n'))
            require(set(value)=={'protocol','version','server_uuid','request_id','action','parameters'}
                and value['protocol']==PROTOCOL and type(value['version']) is int and value['version']==1
                and value['server_uuid']==config['node_uuid'],'identity-unknown');uuid_text(value['request_id'])
            result=agent.handle(value['action'],value['parameters'])
            reply={'protocol':PROTOCOL,'version':1,'server_uuid':config['node_uuid'],'request_id':value['request_id'],'result':result}
            destination.write((canonical(reply)+'\n').encode());destination.flush()
    finally:agent.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    server=sub.add_parser('serve');server.add_argument('--config',type=Path,required=True);server.add_argument('--principal',required=True);server.add_argument('--windows-ip-guest',action='store_true')
    client=sub.add_parser('relay-ip',help='显式连接两个已配置专用来宾的IPv4端点；不改宿主网络')
    for side in ('left','right'):
        client.add_argument('--'+side+'-config',type=Path,required=True)
        client.add_argument('--'+side+'-expected',type=Path,required=True)
        client.add_argument('--'+side+'-tunnel',required=True)
    client.add_argument('--duration',type=int,default=60);client.add_argument('--interval-ms',type=int,default=50)
    kit=sub.add_parser('materials-ip',help='只生成新专用Linux来宾材料目录，不安装或配置网络')
    kit.add_argument('--config',type=Path,required=True);kit.add_argument('--destination',type=Path,required=True)
    kit.add_argument('--ip-sha256',required=True)
    windows=sub.add_parser('materials-windows-ip',help='只生成专用Windows来宾Wintun部署材料，不安装或改网络')
    windows.add_argument('--config',type=Path,required=True);windows.add_argument('--destination',type=Path,required=True)
    windows.add_argument('--wintun-sha256',required=True);windows.add_argument('--driver-version',type=lambda value:int(value,0),required=True)
    windows.add_argument('--allow-driver-install',action='store_true')
    events=sub.add_parser('collect-events',help='显式读取已授权外部Windows事件XML，保存至私有目录新文件')
    events.add_argument('--ssh-config',type=Path,required=True);events.add_argument('--expected',type=Path,required=True)
    events.add_argument('--source',required=True);events.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.action=='serve':
            require(os.environ.get('SSH_ORIGINAL_COMMAND')==COMMAND,'permission-denied')
            serve(args.config,args.principal,sys.stdin.buffer,sys.stdout.buffer,windows_ip_guest=args.windows_ip_guest)
        elif args.action=='collect-events':
            require('SSH_ORIGINAL_COMMAND' not in os.environ,'permission-denied')
            print(canonical(save_events(private_json(args.ssh_config),private_json(args.expected),args.source,args.destination)))
        elif args.action=='relay-ip':
            # SSH强制命令身份不能借新的客户端子命令扩展为出站连接器。
            require('SSH_ORIGINAL_COMMAND' not in os.environ,'permission-denied')
            import signal,threading
            from ctflab_external_ip import relay
            stopped=threading.Event()
            for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stopped.set())
            result=relay(private_json(args.left_config),private_json(args.left_expected),args.left_tunnel,
                private_json(args.right_config),private_json(args.right_expected),args.right_tunnel,
                duration=args.duration,interval_ms=args.interval_ms,stop=stopped)
            print(canonical(result))
        elif args.action=='materials-windows-ip':
            require('SSH_ORIGINAL_COMMAND' not in os.environ,'permission-denied')
            from ctflab_windows_ip import materials
            print(canonical(materials(Path(__file__).resolve().parent.parent,args.destination,private_json(args.config),
                args.wintun_sha256,args.driver_version,allow_driver_install=args.allow_driver_install)))
        else:
            require('SSH_ORIGINAL_COMMAND' not in os.environ,'permission-denied')
            from ctflab_external_ip import materials
            print(canonical(materials(Path(__file__).resolve().parent.parent,args.destination,private_json(args.config),args.ip_sha256)))
    except (OSError,ValueError,RuntimeError,TypeError,KeyError):raise SystemExit(2)
