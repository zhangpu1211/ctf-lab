"""专用Linux来宾的临时点对点IPv4端点；不在运行器宿主配置网络。"""
import hashlib
import ipaddress
import os
from pathlib import Path
import platform
import stat
import struct
import subprocess
import time

from ctflab_contract import canonical, require, uuid_text


def policy(value):
    require(type(value) is dict and {'schema','local','peer','mtu','flows'} <= set(value)
        <= {'schema','local','peer','mtu','flows','icmp_errors'})
    require('icmp_errors' not in value or type(value['icmp_errors']) is bool)
    require(type(value['schema']) is int and value['schema']==1)
    addresses=[]
    for key in ('local','peer'):
        require(type(value[key]) is str)
        address=ipaddress.IPv4Address(value[key])
        require(str(address)==value[key] and any(address in ipaddress.IPv4Network(block)
            for block in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')),'permission-denied')
        addresses.append(address)
    require(addresses[0]!=addresses[1])
    require(type(value['mtu']) is int and 576<=value['mtu']<=1500)
    require(type(value['flows']) is list and 1<=len(value['flows'])<=64)
    seen=set()
    for flow in value['flows']:
        require(type(flow) is dict and set(flow)=={'initiator','protocol','ports'})
        require(flow['initiator'] in ('local','peer') and flow['protocol'] in ('tcp','udp','icmp'))
        ports=flow['ports']
        require(type(ports) is list and len(ports)<=32 and all(type(p) is int and 1<=p<=65535 for p in ports))
        require(len(ports)==len(set(ports)) and (bool(ports) if flow['protocol']!='icmp' else not ports))
        # 管理/容器API/显示端口不能借三层通道绕开原命名服务边界。
        require(not any(p in (22,2375,2376) or 5900<=p<=5999 for p in ports),'permission-denied')
        key=canonical(flow);require(key not in seen);seen.add(key)
    return value


def policy_sha(value):
    return hashlib.sha256(canonical(policy(value)).encode()).hexdigest()


def checksum(data):
    if len(data)%2:data+=b'\0'
    total=sum(struct.unpack('!%dH'%(len(data)//2),data))
    while total>>16:total=(total&65535)+(total>>16)
    return (~total)&65535


def packet(raw, specification, outbound):
    """只解析经过大小检查的一包；不支持分片、IP选项、IPv6或嵌套隧道。"""
    require(type(raw) is bytes and 28<=len(raw)<=specification['mtu'],'permission-denied')
    require(raw[0]==0x45 and struct.unpack('!H',raw[2:4])[0]==len(raw)
        and not struct.unpack('!H',raw[6:8])[0]&0xbfff and raw[8]>0 and checksum(raw[:20])==0,'permission-denied')
    local,peer=specification['local'],specification['peer']
    source,destination=map(str,(ipaddress.IPv4Address(raw[12:16]),ipaddress.IPv4Address(raw[16:20])))
    require((source,destination)==((local,peer) if outbound else (peer,local)),'permission-denied')
    body=raw[20:];number=raw[9]
    if number in (6,17):
        protocol='tcp' if number==6 else 'udp'
        require(len(body)>=(20 if number==6 else 8),'permission-denied')
        a,b=struct.unpack('!HH',body[:4]);require(a>0 and b>0,'permission-denied')
        pseudo=raw[12:20]+bytes((0,number))+struct.pack('!H',len(body))
        if number==6:
            require(20<=(body[12]>>4)*4<=len(body) and checksum(pseudo+body)==0,'permission-denied')
            initial=bool(body[13]&2) and not bool(body[13]&16)
        else:
            require(struct.unpack('!H',body[4:6])[0]==len(body)
                and (body[6:8]==b'\0\0' or checksum(pseudo+body)==0),'permission-denied')
            initial=True
        return protocol,a,b,initial
    require(number==1 and checksum(body)==0,'permission-denied')
    if body[0] in (3,11):
        require(specification.get('icmp_errors') is True, 'permission-denied')
        return 'icmp-error', quoted_error(body, raw, specification), (body[0], body[1]), False
    require(body[0] in (0,8) and body[1]==0,'permission-denied')
    identity,sequence=struct.unpack('!HH',body[4:8])
    return 'icmp',identity,sequence,body[0]==8


def quote_key(raw):
    # 路由中的TTL/校验和可变化；其余首部（含IP ID）和前8字节必须匹配已见报文。
    return raw[:8]+raw[9:10]+raw[12:28]


def quoted_error(body, outer, specification):
    """RFC 792/1191的最小引用；只转送精确对端关于已见TCP/UDP的差错。"""
    require(len(body) >= 36 and ((body[0] == 3 and body[1] in (0,1,2,3,4,9,10,13))
        or (body[0] == 11 and body[1] in (0,1))), 'permission-denied')
    quoted = body[8:]
    size = struct.unpack('!H', quoted[2:4])[0]
    require(quoted[0] == 0x45 and 28 <= len(quoted) <= size <= specification['mtu']
        and not struct.unpack('!H', quoted[6:8])[0] & 0xbfff and checksum(quoted[:20]) == 0
        and quoted[9] in (6,17) and quoted[12:16] == outer[16:20]
        and quoted[16:20] == outer[12:16], 'permission-denied')
    a,b = struct.unpack('!HH',quoted[20:24])
    require(a > 0 and b > 0 and size >= (40 if quoted[9] == 6 else 28), 'permission-denied')
    if body[0] == 3 and body[1] == 4:
        mtu = struct.unpack('!H',body[6:8])[0]
        # 明确只接受有MTU值的现代回报；旧式零值与低于本通道下界的值保守拒绝。
        require(body[4:6] == b'\0\0' and 576 <= mtu < size
            and struct.unpack('!H',quoted[6:8])[0] & 0x4000, 'permission-denied')
    return quote_key(quoted)


class PacketGate:
    """精确端点、服务及回程状态；有界空闲过期，不证明应用成功。"""
    def __init__(self,specification,*,clock=time.monotonic):
        self.specification=policy(specification);self.clock=clock;self.flows={};self.recent={}

    def accept(self,raw,*,outbound):
        protocol,source,destination,initial=packet(raw,self.specification,outbound)
        now=self.clock();self.flows={k:t for k,t in self.flows.items() if 0<=now-t<60}
        self.recent={k:t for k,t in self.recent.items() if 0<=now-t<60}
        if protocol=='icmp-error':
            require((source,not outbound) in self.recent, 'permission-denied')
            # 差错不能建立/续期流或续期引用，不因差错回报无限延长授权。
            return
        if protocol in ('tcp','udp') and self.specification.get('icmp_errors') is True:
            recent=(quote_key(raw),outbound)
            # 引用缓存满时淘汰旧引用；不能让正常数据流在1024包后被中断。
        else: recent=None
        key=(protocol,source,destination,outbound)
        reverse=(protocol,destination,source,not outbound) if protocol!='icmp' else (protocol,source,destination,not outbound)
        if key in self.flows or reverse in self.flows:
            # ICMP回程只接受echo-reply，不能复用ID把peer请求变成授权。
            require(protocol!='icmp' or (key in self.flows)==initial,'permission-denied')
            self.flows[key if key in self.flows else reverse]=now
            if recent is not None:self.remember(recent,now)
            return
        require(initial and any(flow['initiator']==('local' if outbound else 'peer')
            and flow['protocol']==protocol and (protocol=='icmp' or destination in flow['ports'])
            for flow in self.specification['flows']),'permission-denied')
        require(len(self.flows)<256,'resource-busy');self.flows[key]=now
        if recent is not None:self.remember(recent,now)


    def remember(self,key,now):
        self.recent.pop(key,None)
        if len(self.recent)>=1024:self.recent.pop(next(iter(self.recent)))
        self.recent[key]=now


class NativeEndpoint:
    """仅在根所有标记授权的虚拟来宾创建非持久TUN；关闭自有FD由内核回收。"""
    MARKER=Path('/etc/ctflab-external-ip.json')
    IP=Path('/usr/sbin/ip')

    def __init__(self,specification,config,channel):
        self.specification=policy(specification);self.fd=None;self.closed=False;self.config=config
        self.name='ctl'+uuid_text(channel).replace('-','')[:12]
        import ctypes
        require(platform.system()=='Linux' and ctypes.sizeof(ctypes.c_void_p)==8
                and os.geteuid()==0 and config['kind']=='kali','unsupported-platform')
        from ctflab_guest_agent import guarded_file
        self.marker=guarded_file(self.MARKER)
        require(type(self.marker) is dict and set(self.marker)=={'schema','role','machine_uuid','node_uuid',
            'cohort_uuid','checkpoint_uuid','generation','policies','runtime_sha256','ip_sha256'}
            and type(self.marker['schema']) is int and self.marker['schema']==1
            and self.marker['role']=='external-ip-endpoint','permission-denied')
        self.guard()
        import fcntl
        try:
            info=Path('/dev/net/tun').lstat()
            require(stat.S_ISCHR(info.st_mode) and os.major(info.st_rdev)==10 and os.minor(info.st_rdev)==200,'identity-unknown')
            self.fd=os.open('/dev/net/tun',os.O_RDWR|os.O_CLOEXEC|os.O_NONBLOCK|os.O_NOFOLLOW)
            opened=os.fstat(self.fd);require((opened.st_dev,opened.st_ino)==(info.st_dev,info.st_ino),'identity-unknown')
            # IFF_TUN|IFF_NO_PI|IFF_TUN_EXCL：同名接口已存在则失败，不接管它。
            result=fcntl.ioctl(self.fd,0x400454ca,struct.pack('16sH22x',self.name.encode(),0x9001))
            require(result[:16].split(b'\0')[0].decode()==self.name,'identity-unknown')
            self.index=int((Path('/sys/class/net')/self.name/'ifindex').read_text())
            self.namespace=Path('/proc/self/ns/net').stat().st_ino
            self.preflight_addresses()
            self.call(['-4','address','add',specification['local']+'/32','peer',specification['peer']+'/32','dev',self.name])
            self.call(['link','set','dev',self.name,'addrgenmode','none'])
            self.call(['link','set','dev',self.name,'mtu',str(specification['mtu']),'up'])
            self.guard()
        except BaseException:self.close();raise

    def guard(self):
        from ctflab_guest_agent import guarded_file
        from ctflab_external import native_machine
        require(guarded_file(self.MARKER)==self.marker,'permission-denied')
        require(all(self.marker[k]==self.config[k] for k in ('machine_uuid','node_uuid','cohort_uuid','checkpoint_uuid','generation')),'identity-unknown')
        identity=native_machine();require(identity['machine_uuid']==self.config['machine_uuid'],'identity-unknown')
        require(type(self.marker['policies']) is list and policy_sha(self.specification) in self.marker['policies'],'permission-denied')
        required={'ctflab_external_ip.py','ctflab_external.py','ctflab_guest_agent.py','ctflab_contract.py',
                  'ctflab_generation_store.py','ctflab_remote.py','ctflab_tls_endpoint.py'}
        expected={path.name for path in Path(__file__).resolve().parent.glob('*.py')}
        require(required<=expected and len(expected)<=256 and type(self.marker['runtime_sha256']) is dict
                and set(self.marker['runtime_sha256'])==expected,'permission-denied')
        for name,sha in self.marker['runtime_sha256'].items():
            path=Path(__file__).resolve().parent/name
            # guarded_file是JSON读取器；源码/工具的所有者与路径单独核验。
            for part in (path,*path.parents):
                info=part.lstat();require(not stat.S_ISLNK(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'permission-denied')
            require(stat.S_ISREG(path.stat().st_mode) and hashlib.sha256(path.read_bytes()).hexdigest()==sha,'identity-unknown')
        for part in (self.IP,*self.IP.parents):
            info=part.lstat();require(not stat.S_ISLNK(info.st_mode) and info.st_uid==0 and not info.st_mode&0o022,'permission-denied')
        require(hashlib.sha256(self.IP.read_bytes()).hexdigest()==self.marker['ip_sha256'],'identity-unknown')
        if hasattr(self,'index'):
            require(int((Path('/sys/class/net')/self.name/'ifindex').read_text())==self.index
                and Path('/proc/self/ns/net').stat().st_ino==self.namespace,'identity-unknown')

    def call(self,args):
        self.guard()
        try:
            result=subprocess.run([str(self.IP),*args],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,timeout=3,check=False,env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'},close_fds=True)
        except subprocess.TimeoutExpired:require(False,'control-unreachable')
        require(result.returncode==0 and len(result.stdout)<=65536 and len(result.stderr)<=65536,'backend-failed')
        return result.stdout

    def preflight_addresses(self):
        import json
        targets=[ipaddress.IPv4Address(self.specification[k]) for k in ('local','peer')]
        addresses=json.loads(self.call(['-4','-j','address','show']))
        routes=json.loads(self.call(['-4','-j','route','show','table','all']))
        require(type(addresses) is list and len(addresses)<=256 and type(routes) is list and len(routes)<=2048,'route-conflict')
        for row in addresses:
            require(type(row) is dict and type(row.get('addr_info',[])) is list,'route-conflict')
            for info in row.get('addr_info',[]):
                if info.get('family')!='inet':continue
                subnet=ipaddress.IPv4Network(f"{info['local']}/{info['prefixlen']}",strict=False)
                require(not any(address in subnet for address in targets),'route-conflict')
        for row in routes:
            destination=row.get('dst')
            if destination in (None,'default'):continue
            subnet=ipaddress.IPv4Network(destination,strict=False)
            require(not any(address in subnet for address in targets),'route-conflict')

    def receive(self):
        self.guard();require(not self.closed,'control-unreachable')
        try:return os.read(self.fd,self.specification['mtu']+1)
        except BlockingIOError:return None

    def send(self,data):
        self.guard();require(not self.closed,'control-unreachable')
        require(os.write(self.fd,data)==len(data),'control-unreachable')

    def close(self):
        if self.fd is not None:
            os.close(self.fd);self.fd=None
        self.closed=True


class Circuit:
    """两个固定SSH端点间的显式有界转送；不打开宿主TUN或重试不确定发送。"""
    def __init__(self,left,left_name,right,right_name,*,cancel_requested=lambda:False):
        self.sessions=(left,right);self.channels=[];self.closed=False
        try:
            a=left.report['ip_tunnels'][left_name];b=right.report['ip_tunnels'][right_name]
            policy(a);policy(b)
            require(a['local']==b['peer'] and a['peer']==b['local'] and a['mtu']==b['mtu']
                and a.get('icmp_errors',False)==b.get('icmp_errors',False),'identity-unknown')
            inverted=[dict(flow,initiator='peer' if flow['initiator']=='local' else 'local') for flow in a['flows']]
            require(sorted(map(canonical,inverted))==sorted(map(canonical,b['flows'])),'permission-denied')
            require(left.expected['cohort_uuid']==right.expected['cohort_uuid']
                and left.expected['generation']==right.expected['generation']
                and left.expected['machine_uuid']!=right.expected['machine_uuid'],'identity-unknown')
            require(not cancel_requested(),'operation-finished')
            self.channels.append(left.open_ip(left_name))
            require(not cancel_requested(),'operation-finished')
            self.channels.append(right.open_ip(right_name))
            require(not cancel_requested(),'operation-finished')
        except BaseException:self.close();raise

    def step(self):
        require(not self.closed,'control-unreachable');counts=[]
        try:
            for source,destination in ((0,1),(1,0)):
                data=self.sessions[source].receive_ip(self.channels[source])
                if data is not None:self.sessions[destination].send_ip(self.channels[destination],data)
                counts.append(len(data) if data is not None else 0)
            return {'forwarded_bytes':counts,'application_result_verified':False,'automatic_replay':False}
        except BaseException:self.close();raise

    def close(self):
        failed=False
        for session in self.sessions:
            try:session.close()
            except Exception:failed=True
        self.closed=True
        require(not failed,'control-unreachable')


def relay(left_config,left_expected,left_name,right_config,right_expected,right_name,*,duration=60,interval_ms=50,stop=None):
    """显式调用后才打开端点；有界轮询，不安装后台服务，不自动重连。"""
    from contextlib import ExitStack
    import threading
    from ctflab_external import ExternalSession
    require(type(duration) is int and 1<=duration<=3600 and type(interval_ms) is int and 10<=interval_ms<=1000)
    require(left_config['server_uuid']!=right_config['server_uuid'],'identity-unknown')
    stop=stop or threading.Event();counts=[0,0];steps=0
    with ExitStack() as stack:
        require(not stop.is_set(),'operation-finished')
        left=stack.enter_context(ExternalSession(left_config,left_expected))
        require(not stop.is_set(),'operation-finished')
        right=stack.enter_context(ExternalSession(right_config,right_expected))
        require(not stop.is_set(),'operation-finished')
        circuit=Circuit(left,left_name,right,right_name,cancel_requested=stop.is_set);stack.callback(circuit.close)
        deadline=time.monotonic()+duration
        while not stop.is_set() and time.monotonic()<deadline:
            result=circuit.step();steps+=1
            counts=[a+b for a,b in zip(counts,result['forwarded_bytes'])]
            if stop.wait(interval_ms/1000):break
    return {'state':'ip-relay-closed','steps':steps,'forwarded_bytes':counts,'host_network_modified':False,
        'application_result_verified':False,'automatic_replay':False,'automatic_reconnect':False}


def materials(source,destination,configuration,ip_sha256):
    """仅写全新材料目录；不安装标记、密钥、服务或网络，不替代目标来宾预检。"""
    from ctflab_external import settings
    from ctflab_desktop_package import TOOLS
    from ctflab_generation_store import private_directory
    settings(configuration)
    require(bool(configuration.get('ip_tunnels')),'capability-unverified')
    require(type(ip_sha256) is str and len(ip_sha256)==64 and all(c in '0123456789abcdef' for c in ip_sha256))
    source=Path(source);destination=Path(destination).absolute()
    def source_file(name):
        path=source/name
        return path if path.is_file() else source/'runtime'/Path(name).name
    payload={'runtime/'+Path(name).name:source_file(name).read_bytes() for name in TOOLS}
    require(len(payload)==len(TOOLS),'identity-unknown')
    runtime={Path(name).name:hashlib.sha256(data).hexdigest() for name,data in payload.items()}
    marker={k:configuration[k] for k in ('machine_uuid','node_uuid','cohort_uuid','checkpoint_uuid','generation')}
    marker.update(schema=1,role='external-ip-endpoint',policies=sorted({policy_sha(v) for v in configuration['ip_tunnels'].values()}),
        runtime_sha256=runtime,ip_sha256=ip_sha256)
    payload['ctflab-external-ip.json']=canonical(marker).encode()
    payload['external-config.json']=canonical(configuration).encode()
    payload['README.txt']=('仅供管理员核对后的新专用Linux虚拟来宾；不在宿主执行。\n'
        'runtime目录内源码和所有父目录须为root所有且组/其他不可写，目录内不得额外加入Python模块。\n'
        '把本标记显式部署为/etc/ctflab-external-ip.json，配置放在root私有目录；不要覆盖已有部署。\n'
        '配置固定SSH强制命令ctflab-external-v1，禁止任意shell、端口转发与代理转发；按当前principal调用serve。\n'
        '需要Python与cryptography、固定/usr/sbin/ip、内核TUN；本目录不提供这些原生依赖或SSH密钥。\n'
        'ip_sha256来自目标来宾工具的独立核验，材料生成不验证该工具已存在或部署正确。\n'
        '转送方显式运行ctflab_external.py relay-ip，断线不自动重连；关闭FD由内核回收临时接口。\n'
        '只支持策略内点对点IPv4/TCP/UDP/ICMP echo；icmp_errors须双端显式开启，仅回送已见TCP/UDP差错。\n'
        '不支持中间路由器/子网/分片；PMTU仅转送，不在宿主或代理更改MTU，不承诺完整域课程可用。\n').encode()
    manifest={'schema':1,'kind':'external-ip-materials','files':{name:hashlib.sha256(data).hexdigest() for name,data in payload.items()},
        'installed':False,'native_dependencies_included':False,'network_modified':False}
    payload['MANIFEST.json']=canonical(manifest).encode()
    private_directory(destination);private_directory(destination/'runtime')
    for name,data in payload.items():
        fd=os.open(destination/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    return {'state':'external-ip-materials-written','files':len(payload),'installed':False,
        'host_network_modified':False,'native_dependencies_included':False,'automatic_cleanup':False}
