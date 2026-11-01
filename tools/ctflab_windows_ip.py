"""专用Windows x64虚拟来宾的Wintun IPv4端点；不在运行器宿主安装或配置网络。"""
import ctypes as C
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import stat
import time
import uuid

from ctflab_contract import canonical, require, uuid_text, ContractError
from ctflab_generation_store import digest, private_directory
from ctflab_windows_security import WindowsSecurity, guard_path
from ctflab_windows_native import NativeError

U8=C.c_uint8
U16=C.c_uint16
U32=C.c_uint32
U64=C.c_uint64
PTR=C.c_void_p


class Guid(C.Structure):
    _fields_=[('a',U32),('b',U16),('c',U16),('d',U8*8)]
    @classmethod
    def of(cls,value):return cls.from_buffer_copy(uuid.UUID(uuid_text(value)).bytes_le)
    def text(self):return str(uuid.UUID(bytes_le=bytes(self)))


class Address(C.Union):
    _fields_=[('raw',U8*28),('family',U16),('alignment',U32)]
    @classmethod
    def ipv4(cls,value):
        result=cls();result.family=2;result.raw[4:8]=ipaddress.IPv4Address(value).packed
        return result
    def ip(self):
        require(self.family in (2,23),'identity-unknown')
        return str(ipaddress.ip_address(bytes(self.raw[4:8] if self.family==2 else self.raw[8:24])))


class Prefix(C.Structure):
    _fields_=[('address',Address),('length',U8)]


class Unicast(C.Structure):
    _fields_=[('address',Address),('luid',U64),('index',U32),('prefix_origin',U32),('suffix_origin',U32),
        ('valid_lifetime',U32),('preferred_lifetime',U32),('prefix_length',U8),('skip_source',U8),
        ('dad',U32),('scope_id',U32),('created',C.c_int64)]


class Route(C.Structure):
    _fields_=[('luid',U64),('index',U32),('prefix',Prefix),('next_hop',Address),('site_prefix',U8),
        ('valid_lifetime',U32),('preferred_lifetime',U32),('metric',U32),('protocol',U32),
        ('loopback',U8),('autoconfigure',U8),('publish',U8),('immortal',U8),('age',U32),('origin',U32)]


IF_FLAGS=('advertising','forwarding','weak_send','weak_receive','automatic_metric','neighbor_detection',
          'managed_address','other_stateful','advertise_default')
class Interface(C.Structure):
    _fields_=[('family',U16),('luid',U64),('index',U32),('max_reassembly',U32),('identifier',U64),
        ('min_ra',U32),('max_ra',U32)]+[(name,U8) for name in IF_FLAGS]+[
        ('router_discovery',U32),('dad_transmits',U32),('base_reachable',U32),('retransmit',U32),('pmtu_timeout',U32),
        ('link_local',U32),('link_local_timeout',U32),('zones',U32*16),('site_prefix',U32),('metric',U32),('mtu',U32),
        ('connected',U8),('wake_patterns',U8),('neighbor_support',U8),('router_support',U8),('reachable',U32),
        ('transmit_offload',U8),('receive_offload',U8),('disable_default',U8)]


class TrustFile(C.Structure):
    _fields_=[('size',U32),('path',C.c_wchar_p),('file',PTR),('subject',PTR)]


class TrustData(C.Structure):
    _fields_=[('size',U32),('policy',PTR),('sip',PTR),('ui',U32),('revocation',U32),('choice',U32),('file',PTR),
        ('state_action',U32),('state',PTR),('url',C.c_wchar_p),('flags',U32),('context',U32),('signature',PTR)]


def abi():
    sizes={name:C.sizeof(value) for name,value in (('guid',Guid),('address',Address),('prefix',Prefix),
        ('unicast',Unicast),('route',Route),('interface',Interface),('trust_file',TrustFile),('trust_data',TrustData))}
    require(sizes=={'guid':16,'address':28,'prefix':32,'unicast':80,'route':104,'interface':168,
                   'trust_file':32,'trust_data':88},'unsupported-platform')
    return sizes


def marker(value,configuration,specification):
    from ctflab_external_ip import policy_sha
    fields={'schema','role','machine_uuid','node_uuid','cohort_uuid','checkpoint_uuid','generation',
            'policies','runtime_sha256','wintun_sha256','driver_version','allow_driver_install'}
    require(type(value) is dict and set(value)==fields and type(value['schema']) is int and value['schema']==1
        and value['role']=='windows-external-ip-endpoint','permission-denied')
    require(all(value[key]==configuration[key] for key in ('machine_uuid','node_uuid','cohort_uuid','checkpoint_uuid','generation'))
        and type(value['generation']) is int,'identity-unknown')
    require(type(value['policies']) is list and len(value['policies'])<=4
        and policy_sha(specification) in value['policies'],'permission-denied')
    hashes=value['runtime_sha256']
    require(type(hashes) is dict and 1<=len(hashes)<=256 and all(type(name) is str
        and re.fullmatch(r'ctflab_[a-z0-9_]+\.py',name) and type(sha) is str and re.fullmatch('[0-9a-f]{64}',sha)
        for name,sha in hashes.items()),'permission-denied')
    required={'ctflab_windows_ip.py','ctflab_external.py','ctflab_external_ip.py','ctflab_contract.py',
              'ctflab_generation_store.py','ctflab_windows_security.py','ctflab_windows_native.py','ctflab_windows_firewall.py'}
    require(required<=set(hashes) and type(value['wintun_sha256']) is str
        and re.fullmatch('[0-9a-f]{64}',value['wintun_sha256']) and type(value['driver_version']) is int
        and 0<value['driver_version']<=2**32-1 and type(value['allow_driver_install']) is bool,'permission-denied')
    return value


class GuestSecurity(WindowsSecurity):
    """只用于明确部署的管理员来宾端点；不改变普通Windows运行器的非提权边界。"""
    def current_user(self):
        thread=PTR()
        if self.security.OpenThreadToken(self.kernel.GetCurrentThread(),8,True,C.byref(thread)):
            self.kernel.CloseHandle(thread);raise NativeError('permission-denied')
        require(C.get_last_error()==1008,'permission-denied')
        token=PTR();require(self.security.OpenProcessToken(self.kernel.GetCurrentProcess(),8,C.byref(token)),'permission-denied')
        try:
            elevated=U32();written=U32()
            require(self.security.GetTokenInformation(token,20,C.byref(elevated),4,C.byref(written))
                and written.value==4 and elevated.value==1,'permission-denied')
            shell=C.WinDLL('shell32.dll',winmode=0x800);shell.IsUserAnAdmin.argtypes=[];shell.IsUserAnAdmin.restype=C.c_int32
            require(bool(shell.IsUserAnAdmin()),'permission-denied')
            needed=U32();self.security.GetTokenInformation(token,1,None,0,C.byref(needed))
            require(C.sizeof(PTR)<=needed.value<=4096,'permission-denied')
            data=C.create_string_buffer(needed.value)
            require(self.security.GetTokenInformation(token,1,data,needed.value,C.byref(needed)),'permission-denied')
            return self._sid(C.cast(data,C.POINTER(PTR)).contents)
        finally:self.kernel.CloseHandle(token)


def native_platform():
    require(os.name=='nt' and platform.system()=='Windows' and platform.machine().lower() in ('amd64','x86_64')
            and C.sizeof(PTR)==8,'unsupported-platform')
    abi()


def guest_root():
    native_platform();shell=C.WinDLL('shell32.dll',winmode=0x800);ole=C.WinDLL('ole32.dll',winmode=0x800)
    call=shell.SHGetKnownFolderPath;call.argtypes=[C.POINTER(Guid),U32,PTR,C.POINTER(PTR)];call.restype=C.c_int32
    ole.CoTaskMemFree.argtypes=[PTR];ole.CoTaskMemFree.restype=None
    value=PTR();identity=Guid.of('62ab5d82-fdc1-4dc3-a9dd-070d1d495d97')
    require(call(C.byref(identity),0,None,C.byref(value))==0 and value.value,'permission-denied')
    try:return Path(C.wstring_at(value))/'CTFLabExternalIP'
    finally:ole.CoTaskMemFree(value)


def private_read(path,security):
    security.verify(path);info=path.stat();require(info.st_size<=65536,'storage-insufficient')
    from ctflab_remote import decode
    value=decode(path.read_bytes(),65536)
    after=path.stat();require((info.st_dev,info.st_ino,info.st_mtime_ns,info.st_size)==
        (after.st_dev,after.st_ino,after.st_mtime_ns,after.st_size),'identity-unknown')
    return value


def read_configuration(path):
    """仅新管理员强制命令模式可读固定位置，不放宽普通远程配置读取。"""
    root=guest_root();security=GuestSecurity();security.verify(root,root=True)
    path=Path(path).absolute();require(path==root/'external-config.json','permission-denied')
    value=private_read(path,security)
    from ctflab_external import settings,native_machine
    settings(value);require(value['kind'] in ('windows','ad-dc','ad-member') and value.get('ip_tunnels'),'permission-denied')
    identity=native_machine();require(identity['machine_uuid']==value['machine_uuid'],'identity-unknown')
    declaration=private_read(root/'endpoint.json',security)
    for specification in value['ip_tunnels'].values():marker(declaration,value,specification)
    return value


def table_values(library,name,row_type,maximum):
    class Table(C.Structure):_fields_=[('count',U32),('rows',row_type*1)]
    value=PTR();require(getattr(library,name)(0,C.byref(value))==0 and value.value,'identity-unknown')
    try:
        count=C.cast(value,C.POINTER(U32)).contents.value;require(count<=maximum,'storage-insufficient')
        return [row_type.from_buffer_copy(C.string_at(value.value+Table.rows.offset+i*C.sizeof(row_type),C.sizeof(row_type)))
                for i in range(count)]
    finally:library.FreeMibTable(value)


class Network:
    def __init__(self,library=None):
        if library is None:native_platform();library=C.WinDLL('iphlpapi.dll',winmode=0x800,use_last_error=True)
        self.library=library
        definitions={
            'GetUnicastIpAddressTable':([U16,C.POINTER(PTR)],U32),'GetIpForwardTable2':([U16,C.POINTER(PTR)],U32),
            'FreeMibTable':([PTR],None),'InitializeUnicastIpAddressEntry':([C.POINTER(Unicast)],None),
            'CreateUnicastIpAddressEntry':([C.POINTER(Unicast)],U32),'GetUnicastIpAddressEntry':([C.POINTER(Unicast)],U32),
            'InitializeIpForwardEntry':([C.POINTER(Route)],None),'CreateIpForwardEntry2':([C.POINTER(Route)],U32),
            'GetIpInterfaceEntry':([C.POINTER(Interface)],U32),'SetIpInterfaceEntry':([C.POINTER(Interface)],U32),
            'ConvertInterfaceAliasToLuid':([C.c_wchar_p,C.POINTER(U64)],U32),
            'ConvertInterfaceLuidToAlias':([C.POINTER(U64),C.c_wchar_p,C.c_size_t],U32),
            'ConvertInterfaceGuidToLuid':([C.POINTER(Guid),C.POINTER(U64)],U32),
            'ConvertInterfaceLuidToGuid':([C.POINTER(U64),C.POINTER(Guid)],U32)}
        for name,(args,result) in definitions.items():
            method=getattr(library,name);method.argtypes=args;method.restype=result

    def addresses(self):return table_values(self.library,'GetUnicastIpAddressTable',Unicast,2048)
    def routes(self):return table_values(self.library,'GetIpForwardTable2',Route,4096)

    def preflight(self,specification,own=None):
        targets=[ipaddress.IPv4Address(specification[key]) for key in ('local','peer')]
        for row in self.addresses():
            if row.address.family!=2 or row.luid==own:continue
            network=ipaddress.IPv4Network(f'{row.address.ip()}/{row.prefix_length}',strict=False)
            require(not any(target in network for target in targets),'route-conflict')
        for row in self.routes():
            if row.prefix.address.family!=2 or row.luid==own or row.prefix.length==0:continue
            network=ipaddress.IPv4Network(f'{row.prefix.address.ip()}/{row.prefix.length}',strict=False)
            require(not any(target in network for target in targets),'route-conflict')

    def unused(self,name,identity):
        value=U64();guid=Guid.of(identity)
        for code in (self.library.ConvertInterfaceAliasToLuid(name,C.byref(value)),
                     self.library.ConvertInterfaceGuidToLuid(C.byref(guid),C.byref(value))):
            require(code in (2,1168),'resource-busy')

    def interface(self,luid,family):
        value=Interface();value.family=family;value.luid=luid
        code=self.library.GetIpInterfaceEntry(C.byref(value))
        if family==23 and code in (2,1168):return None
        require(code==0 and value.luid==luid and value.family==family,'identity-unknown')
        return value

    def configure(self,luid,specification):
        for family in (2,23):
            row=self.interface(luid,family)
            if row is None:continue
            for name in ('advertising','forwarding','weak_send','weak_receive','automatic_metric',
                         'managed_address','other_stateful','advertise_default'):setattr(row,name,0)
            row.router_discovery=0;row.link_local=0;row.dad_transmits=0;row.disable_default=1
            row.site_prefix=0;row.metric=1;row.mtu=specification['mtu'] if family==2 else max(1280,specification['mtu'])
            require(self.library.SetIpInterfaceEntry(C.byref(row))==0,'backend-failed')
        address=Unicast();self.library.InitializeUnicastIpAddressEntry(C.byref(address))
        address.address=Address.ipv4(specification['local']);address.luid=luid;address.prefix_length=32
        address.prefix_origin=1;address.suffix_origin=1;address.valid_lifetime=0xffffffff;address.preferred_lifetime=0xffffffff
        address.skip_source=0
        require(self.library.CreateUnicastIpAddressEntry(C.byref(address))==0,'backend-failed')
        route=Route();self.library.InitializeIpForwardEntry(C.byref(route))
        route.luid=luid;route.prefix=Prefix(Address.ipv4(specification['peer']),32);route.next_hop=Address.ipv4('0.0.0.0')
        route.protocol=3;route.metric=1;route.valid_lifetime=0xffffffff;route.preferred_lifetime=0xffffffff
        route.immortal=1
        require(self.library.CreateIpForwardEntry2(C.byref(route))==0,'backend-failed')
        # 仅轮询本次新地址的DAD读回，不重复创建地址/路由。
        deadline=time.monotonic()+2
        while True:
            require(self.library.GetUnicastIpAddressEntry(C.byref(address))==0,'identity-unknown')
            if address.dad==4:break
            require(address.dad==1 and time.monotonic()<deadline,'identity-unknown');time.sleep(.05)

    def verify(self,luid,name,identity,specification):
        value=U64(luid);guid=Guid();alias=C.create_unicode_buffer(257)
        require(self.library.ConvertInterfaceLuidToGuid(C.byref(value),C.byref(guid))==0 and guid.text()==identity
            and self.library.ConvertInterfaceLuidToAlias(C.byref(value),alias,len(alias))==0 and alias.value==name,'identity-unknown')
        for family in (2,23):
            row=self.interface(luid,family)
            if row is None:continue
            require(all(getattr(row,key)==0 for key in ('advertising','forwarding','weak_send','weak_receive',
                'managed_address','other_stateful','advertise_default','router_discovery','link_local','automatic_metric','dad_transmits'))
                and row.disable_default==1 and row.metric==1 and row.site_prefix==0 and row.mtu==(specification['mtu'] if family==2 else max(1280,specification['mtu'])),'route-conflict')
        addresses=[row for row in self.addresses() if row.luid==luid]
        require(len(addresses)==1 and addresses[0].address.family==2 and addresses[0].address.ip()==specification['local']
            and addresses[0].prefix_length==32 and addresses[0].skip_source==0 and addresses[0].dad==4
            and addresses[0].prefix_origin==1 and addresses[0].suffix_origin==1,'identity-unknown')
        found=False
        for row in self.routes():
            if row.luid!=luid:continue
            destination=str(ipaddress.ip_network(f'{row.prefix.address.ip()}/{row.prefix.length}',strict=False))
            require(row.next_hop.ip() in ('0.0.0.0','::') and not row.publish,'route-conflict')
            if destination==specification['peer']+'/32':
                require(row.protocol==3 and row.metric==1 and not row.loopback,'route-conflict');found=True
            else:
                require(row.protocol==2 and destination in (specification['local']+'/32','224.0.0.0/4',
                    '255.255.255.255/32','ff00::/8'),'route-conflict')
        require(found,'route-conflict');self.preflight(specification,own=luid)


class Native:
    def __init__(self,configuration,specification):
        native_platform();self.configuration=configuration;self.specification=specification
        from ctflab_external import native_machine
        require(native_machine()['machine_uuid']==configuration['machine_uuid'],'identity-unknown')
        self.root=guest_root();self.security=GuestSecurity();self.security.verify(self.root,root=True)
        self.marker=private_read(self.root/'endpoint.json',self.security)
        marker(self.marker,configuration,specification);self.guard(check_driver=False)
        self.trust(self.root/'wintun.dll')
        self.dll=C.WinDLL(str(self.root/'wintun.dll'),winmode=0x800,use_last_error=True)
        definitions={'WintunCreateAdapter':([C.c_wchar_p,C.c_wchar_p,C.POINTER(Guid)],PTR),
            'WintunCloseAdapter':([PTR],None),'WintunGetAdapterLuid':([PTR,C.POINTER(U64)],None),
            'WintunGetRunningDriverVersion':([],U32),'WintunStartSession':([PTR,U32],PTR),
            'WintunEndSession':([PTR],None),'WintunReceivePacket':([PTR,C.POINTER(U32)],PTR),
            'WintunReleaseReceivePacket':([PTR,PTR],None),'WintunAllocateSendPacket':([PTR,U32],PTR),
            'WintunSendPacket':([PTR,PTR],None)}
        for name,(args,result) in definitions.items():
            function=getattr(self.dll,name);function.argtypes=args;function.restype=result
        version=self.dll.WintunGetRunningDriverVersion()
        require(version==self.marker['driver_version'] or version==0 and self.marker['allow_driver_install'],'capability-unverified')
        self.network=Network()
        from ctflab_windows_firewall import Firewall
        self.firewall=Firewall()

    def guard(self,*,check_driver=True):
        from ctflab_external import native_machine
        require(native_machine()['machine_uuid']==self.configuration['machine_uuid'],'identity-unknown')
        self.security.verify(self.root,root=True)
        require(private_read(self.root/'endpoint.json',self.security)==self.marker,'permission-denied')
        marker(self.marker,self.configuration,self.specification)
        runtime=self.root/'runtime';self.security.verify(runtime,root=True)
        names={path.name for path in runtime.glob('*.py')}
        require(names==set(self.marker['runtime_sha256']) and Path(__file__).resolve().parent==runtime,'permission-denied')
        total=0
        for name,sha in self.marker['runtime_sha256'].items():
            path=runtime/name;self.security.verify(path);size=path.stat().st_size;total+=size
            require(size<=8*1024**2 and total<=32*1024**2 and digest(path)==sha,'identity-unknown')
        dll=self.root/'wintun.dll';self.security.verify(dll)
        require(0<dll.stat().st_size<=16*1024**2 and digest(dll)==self.marker['wintun_sha256'],'identity-unknown')
        raw=dll.read_bytes();require(raw[:2]==b'MZ' and len(raw)>=64,'capability-unverified')
        import struct
        offset=struct.unpack_from('<I',raw,60)[0]
        require(64<=offset<=len(raw)-26 and raw[offset:offset+4]==b'PE\0\0'
            and struct.unpack_from('<H',raw,offset+4)[0]==0x8664
            and struct.unpack_from('<H',raw,offset+24)[0]==0x20b,'capability-unverified')
        if check_driver:require(self.dll.WintunGetRunningDriverVersion()==self.marker['driver_version'],'identity-unknown')

    def trust(self,path):
        library=C.WinDLL('wintrust.dll',winmode=0x800);call=library.WinVerifyTrust
        call.argtypes=[PTR,C.POINTER(Guid),PTR];call.restype=C.c_int32
        info=TrustFile();info.size=C.sizeof(info);info.path=str(path)
        data=TrustData();data.size=C.sizeof(data);data.ui=2;data.revocation=1;data.choice=1
        data.file=C.cast(C.pointer(info),PTR);data.state_action=1;data.flags=0x1080
        action=Guid.of('00aac56b-cd44-11d0-8cc2-00c04fc295ee')
        try:require(call(PTR(-1),C.byref(action),C.byref(data))==0,'permission-denied')
        finally:data.state_action=2;call(PTR(-1),C.byref(action),C.byref(data))

    def create(self,name,identity):
        self.network.unused(name,identity);guid=Guid.of(identity)
        adapter=self.dll.WintunCreateAdapter(name,'CTFLab',C.byref(guid));require(bool(adapter),'backend-failed')
        return adapter
    def luid(self,adapter):
        value=U64();self.dll.WintunGetAdapterLuid(adapter,C.byref(value));require(value.value>0,'identity-unknown');return value.value
    def start(self,adapter):
        value=self.dll.WintunStartSession(adapter,0x20000);require(bool(value),'control-unreachable');return value
    def receive(self,session):
        size=U32();pointer=self.dll.WintunReceivePacket(session,C.byref(size))
        if not pointer:
            require(C.get_last_error()==259,'control-unreachable');return None
        try:
            require(20<=size.value<=65535,'identity-unknown');return C.string_at(pointer,size.value)
        finally:self.dll.WintunReleaseReceivePacket(session,pointer)
    def send(self,session,data):
        require(type(data) is bytes and 28<=len(data)<=1500)
        pointer=self.dll.WintunAllocateSendPacket(session,len(data));require(bool(pointer),'resource-busy')
        C.memmove(pointer,data,len(data));self.dll.WintunSendPacket(session,pointer)
    def end(self,session):self.dll.WintunEndSession(session)
    def close(self,adapter):self.dll.WintunCloseAdapter(adapter)
    def dispose(self):self.firewall.close()


class WindowsEndpoint:
    """只创建本会话的新适配器；关闭只释放自有句柄，不打开/删除既有适配器。"""
    def __init__(self,specification,configuration,channel,*,native=None):
        from ctflab_external_ip import policy
        self.specification=policy(specification);self.configuration=configuration
        self.adapter=None;self.session=None;self.closed=False;self.discarded=0
        self.identity=uuid_text(channel);self.name='CTFLab-'+self.identity
        require(configuration['kind'] in ('windows','ad-dc','ad-member'),'capability-unverified')
        self.native=native or Native(configuration,specification)
        try:
            self.native.guard(check_driver=False);self.native.network.preflight(specification)
            self.adapter=self.native.create(self.name,self.identity);self.luid=self.native.luid(self.adapter)
            self.native.guard();self.native.network.configure(self.luid,specification)
            self.native.network.verify(self.luid,self.name,self.identity,specification)
            self.native.firewall.install(specification,self.name,self.identity)
            self.session=self.native.start(self.adapter)
            self.guard()
        except BaseException:self.close();raise
    def guard(self):
        require(not self.closed,'control-unreachable');self.native.guard()
        require(self.native.luid(self.adapter)==self.luid,'identity-unknown')
        self.native.network.verify(self.luid,self.name,self.identity,self.specification)
        self.native.firewall.verify()
    def receive(self):
        self.guard()
        for _ in range(16):
            data=self.native.receive(self.session)
            if data is None:return None
            require(type(data) is bytes and len(data)>=20,'identity-unknown')
            # 新Windows接口可能产生本地组播/IPv6背景包；有界丢弃，不转送或注入。
            if data[0]>>4==6 or data[0]>>4==4 and data[16:20]!=ipaddress.IPv4Address(self.specification['peer']).packed:
                self.discarded+=1;require(self.discarded<=256,'resource-busy');continue
            return data
        return None
    def send(self,data):
        self.guard()
        from ctflab_external_ip import packet
        packet(data,self.specification,False)
        self.native.send(self.session,data)
    def close(self):
        if self.closed:return
        failed=False
        if self.session is not None:
            value=self.session;self.session=None
            try:self.native.end(value)
            except Exception:failed=True
        try:self.native.dispose()
        except Exception:failed=True
        if self.adapter is not None:
            value=self.adapter;self.adapter=None
            try:self.native.close(value)
            except Exception:failed=True
        self.closed=True
        require(not failed,'control-unreachable')


def materials(source,destination,configuration,wintun_sha256,driver_version,*,allow_driver_install=False):
    """只生成新目录中的管理员核对材料，不下载DLL、提权、安装或配置网络。"""
    from ctflab_external import settings
    from ctflab_desktop_package import TOOLS
    from ctflab_external_ip import policy_sha
    settings(configuration);require(configuration['kind'] in ('windows','ad-dc','ad-member') and configuration.get('ip_tunnels'),'capability-unverified')
    source=Path(source);destination=Path(destination).absolute()
    def source_file(name):
        path=source/name
        return path if path.is_file() else source/'runtime'/Path(name).name
    payload={'runtime/'+Path(name).name:source_file(name).read_bytes() for name in TOOLS}
    require(len(payload)==len(TOOLS),'identity-unknown')
    value={key:configuration[key] for key in ('machine_uuid','node_uuid','cohort_uuid','checkpoint_uuid','generation')}
    value.update(schema=1,role='windows-external-ip-endpoint',policies=sorted({policy_sha(spec) for spec in configuration['ip_tunnels'].values()}),
        runtime_sha256={Path(name).name:hashlib.sha256(raw).hexdigest() for name,raw in payload.items()},
        wintun_sha256=wintun_sha256,driver_version=driver_version,allow_driver_install=allow_driver_install)
    for specification in configuration['ip_tunnels'].values():marker(value,configuration,specification)
    payload['endpoint.json']=canonical(value).encode();payload['external-config.json']=canonical(configuration).encode()
    payload['README.txt']=('仅新专用Windows x64虚拟来宾；管理员先独立核验Wintun来源/许可/签名/摘要。\n'
        '本目录不含Wintun DLL/驱动/Python/SSH，不下载或安装。部署到系统ProgramData下CTFLabExternalIP，拒绝覆盖已有部署。\n'
        '根和runtime使用受保护的仅当前管理员SID与SYSTEM DACL；其他用户无权写入，不防御同一用户恶意代码。\n'
        '另放入已独立核对的wintun.dll；代码使用系统离线缓存WinVerifyTrust核验，不联网补证书或降级。\n'
        '固定SSH强制命令ctflab-external-v1；serve使用--windows-ip-guest和固定external-config.json，不给交互shell或转发。\n'
        '端点需要显式提升的管理员会话，普通Windows运行器/原远程读取不提权。\n'
        '只在原生SMBIOS虚拟来宾身份、标记/策略/代次均一致时创建新适配器；驱动缺失默认拒绝。\n'
        'allow_driver_install=true才授权Wintun在该来宾初始化驱动；关闭仅删除本会话新建适配器，不卸载共享驱动。\n'
        '不改宿主网络，不接管外部VM生命周期，不承诺其他网卡默认出口隔离。首次必须实测路由/防火墙/服务/重连与关闭。\n').encode()
    payload['MANIFEST.json']=canonical({'schema':1,'kind':'windows-external-ip-materials',
        'files':{name:hashlib.sha256(raw).hexdigest() for name,raw in payload.items()},
        'installed':False,'native_dependencies_included':False,'network_modified':False,'native_verified':False}).encode()
    private_directory(destination);private_directory(destination/'runtime')
    for name,raw in payload.items():
        fd=os.open(destination/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    return {'state':'windows-ip-materials-written','files':len(payload),'installed':False,
        'host_network_modified':False,'native_verified':False,'automatic_cleanup':False}
