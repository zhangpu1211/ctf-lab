"""仅新专用Windows来宾接口的固定防火墙规则；不关闭防火墙或改既有规则。"""
from contextlib import contextmanager
import ctypes as C
import hashlib
import ipaddress

from ctflab_contract import canonical, require, uuid_text

PTR=C.c_void_p
I32=C.c_int32
U32=C.c_uint32
I16=C.c_int16


class Variant(C.Structure):
    _fields_=[('kind',C.c_uint16),('reserved',C.c_uint16*3),('value',C.c_uint64),('extra',C.c_uint64)]


# SDK的IUnknown/IDispatch之后的固定INetFwRule属性槽；不接收RPC方法名。
FIELDS={
    'Name':(7,'text'),'Description':(9,'text'),'ApplicationName':(11,'text'),'ServiceName':(13,'text'),
    'Protocol':(15,'integer'),'LocalPorts':(17,'text'),'RemotePorts':(19,'text'),
    'LocalAddresses':(21,'text'),'RemoteAddresses':(23,'text'),'IcmpTypesAndCodes':(25,'text'),
    'Direction':(27,'integer'),'Interfaces':(29,'interfaces'),'InterfaceTypes':(31,'text'),
    'Enabled':(33,'bool'),'Grouping':(35,'text'),'Profiles':(37,'integer'),'EdgeTraversal':(39,'bool'),'Action':(41,'integer')}


def recipes(specification,alias,channel):
    from ctflab_external_ip import policy,policy_sha
    policy(specification);uuid_text(channel);require(alias=='CTFLab-'+channel)
    values=[]
    for flow in specification['flows']:
        entry={'Protocol':{'tcp':6,'udp':17,'icmp':1}[flow['protocol']],
            'Direction':2 if flow['initiator']=='local' else 1}
        if flow['protocol']=='icmp':entry['IcmpTypesAndCodes']='8:0'
        else:
            entry['LocalPorts']='*' if flow['initiator']=='local' else ','.join(map(str,sorted(flow['ports'])))
            entry['RemotePorts']=','.join(map(str,sorted(flow['ports']))) if flow['initiator']=='local' else '*'
        values.append(entry)
    if specification.get('icmp_errors'):
        for direction in (1,2):values.append({'Protocol':1,'Direction':direction,
            'IcmpTypesAndCodes':'3:0,3:1,3:2,3:3,3:4,3:9,3:10,3:13,11:0,11:1'})
    result=[]
    for index,entry in enumerate(values):
        value={'Name':alias+'-'+str(index),'Description':'policy:'+policy_sha(specification)+';channel:'+channel,
            **entry,'LocalAddresses':specification['local'],'RemoteAddresses':specification['peer'],
            'Interfaces':[alias],'InterfaceTypes':'All','Grouping':'CTFLabExternalIP','Profiles':0x7fffffff,
            'EdgeTraversal':False,'Action':1,'Enabled':True,'ApplicationName':'','ServiceName':''}
        result.append(value)
    return result


def matches(expected,observed):
    if type(observed) is not dict or set(expected)!=set(observed):return False
    for name,value in expected.items():
        other=observed[name]
        if name in ('LocalAddresses','RemoteAddresses'):
            try:
                if str(ipaddress.ip_network(other,strict=False))!=str(ipaddress.ip_network(value,strict=False)):return False
            except (ValueError,TypeError):return False
        elif name=='InterfaceTypes':
            if type(other) is not str or other.casefold()!=value.casefold():return False
        elif type(value) is bool:
            if type(other) is not bool or other!=value:return False
        elif other!=value:return False
    return True


class Com:
    """显式类型的COM调用；只访问已固定的Firewall接口，不执行脚本或任意命令。"""
    def __init__(self):
        from ctflab_windows_ip import native_platform,Guid
        native_platform();require(C.sizeof(Variant)==24,'unsupported-platform')
        self.Guid=Guid;self.policy=None;self.rules=None;self.initialized=False
        self.ole=C.WinDLL('ole32.dll',winmode=0x800);self.auto=C.WinDLL('oleaut32.dll',winmode=0x800)
        definitions={
            'CoInitializeEx':([PTR,U32],I32),'CoUninitialize':([],None),
            'CoCreateInstance':([C.POINTER(Guid),PTR,U32,C.POINTER(Guid),C.POINTER(PTR)],I32)}
        for name,(args,result) in definitions.items():
            fn=getattr(self.ole,name);fn.argtypes=args;fn.restype=result
        definitions={'SysAllocString':([C.c_wchar_p],PTR),'SysFreeString':([PTR],None),'SysStringLen':([PTR],U32),
            'VariantClear':([C.POINTER(Variant)],I32),'SafeArrayCreateVector':([C.c_uint16,I32,U32],PTR),
            'SafeArrayPutElement':([PTR,C.POINTER(I32),PTR],I32),'SafeArrayGetElement':([PTR,C.POINTER(I32),PTR],I32),
            'SafeArrayGetDim':([PTR],U32),'SafeArrayGetLBound':([PTR,U32,C.POINTER(I32)],I32),
            'SafeArrayGetUBound':([PTR,U32,C.POINTER(I32)],I32)}
        for name,(args,result) in definitions.items():
            fn=getattr(self.auto,name);fn.argtypes=args;fn.restype=result
        require(self.ole.CoInitializeEx(None,2) in (0,1),'capability-unverified');self.initialized=True
        try:
            self.policy=self.create('e2b3c97f-6ae1-41ac-817a-f6f92166d7dd','98325047-c671-4174-8d81-defcd3f03186')
            value=PTR();self.check(self.call(self.policy,18,I32,[C.POINTER(PTR)],C.byref(value)));require(value.value,'identity-unknown')
            self.rules=value
        except BaseException:self.close();raise
    def call(self,obj,index,result,args,*values):
        require(obj is not None and bool(obj),'identity-unknown')
        table=C.cast(obj,C.POINTER(C.POINTER(PTR))).contents
        function=C.WINFUNCTYPE(result,PTR,*args)(table[index])
        return function(obj,*values)
    def check(self,result):require(result==0,'permission-denied')
    def create(self,clsid,iid):
        clsid=self.Guid.of(clsid);iid=self.Guid.of(iid);value=PTR()
        self.check(self.ole.CoCreateInstance(C.byref(clsid),None,1,C.byref(iid),C.byref(value)))
        require(value.value,'identity-unknown');return value
    def release(self,obj):
        if obj is not None and obj:self.call(obj,2,U32,[])
    @contextmanager
    def text(self,value):
        require(type(value) is str and len(value)<=4096)
        pointer=self.auto.SysAllocString(value);require(pointer is not None,'storage-insufficient')
        try:yield pointer
        finally:self.auto.SysFreeString(pointer)
    def decoded(self,pointer):
        if not pointer:return ''
        require(self.auto.SysStringLen(pointer)<=4096,'storage-insufficient');return C.wstring_at(pointer)
    @contextmanager
    def array(self,values):
        require(type(values) is list and len(values)==1 and type(values[0]) is str and len(values[0])<=257)
        variant=Variant();variant.kind=0x200c;variant.value=self.auto.SafeArrayCreateVector(12,0,1)
        require(variant.value,'storage-insufficient')
        try:
            child=Variant();child.kind=8;child.value=self.auto.SysAllocString(values[0]);require(child.value,'storage-insufficient')
            try:self.check(self.auto.SafeArrayPutElement(PTR(variant.value),C.byref(I32(0)),C.byref(child)))
            finally:self.auto.VariantClear(C.byref(child))
            yield variant
        finally:self.auto.VariantClear(C.byref(variant))
    def array_values(self,value):
        if value.kind in (0,1):return []
        require(value.kind in (0x2008,0x200c) and value.value and self.auto.SafeArrayGetDim(PTR(value.value))==1,'identity-unknown')
        low=I32();high=I32();self.check(self.auto.SafeArrayGetLBound(PTR(value.value),1,C.byref(low)))
        self.check(self.auto.SafeArrayGetUBound(PTR(value.value),1,C.byref(high)))
        require(0<=high.value-low.value+1<=16,'identity-unknown');result=[]
        for number in range(low.value,high.value+1):
            if value.kind==0x2008:
                child=PTR();self.check(self.auto.SafeArrayGetElement(PTR(value.value),C.byref(I32(number)),C.byref(child)))
                try:result.append(self.decoded(child))
                finally:self.auto.SysFreeString(child)
            else:
                child=Variant();self.check(self.auto.SafeArrayGetElement(PTR(value.value),C.byref(I32(number)),C.byref(child)))
                try:require(child.kind==8,'identity-unknown');result.append(self.decoded(PTR(child.value)))
                finally:self.auto.VariantClear(C.byref(child))
        return result
    def get(self,obj,name):
        index,kind=FIELDS[name]
        if kind=='text':
            value=PTR();self.check(self.call(obj,index,I32,[C.POINTER(PTR)],C.byref(value)))
            try:return self.decoded(value)
            finally:self.auto.SysFreeString(value)
        if kind=='interfaces':
            value=Variant();self.check(self.call(obj,index,I32,[C.POINTER(Variant)],C.byref(value)))
            try:return self.array_values(value)
            finally:self.auto.VariantClear(C.byref(value))
        value=I16() if kind=='bool' else I32();self.check(self.call(obj,index,I32,[C.POINTER(type(value))],C.byref(value)))
        return bool(value.value) if kind=='bool' else value.value
    def put(self,obj,name,value):
        index,kind=FIELDS[name]
        if kind=='text':
            with self.text(value) as text:self.check(self.call(obj,index+1,I32,[PTR],text))
        elif kind=='interfaces':
            with self.array(value) as variant:self.check(self.call(obj,index+1,I32,[Variant],variant))
        else:self.check(self.call(obj,index+1,I32,[I16 if kind=='bool' else I32],-1 if kind=='bool' and value else int(value)))
    def find(self,name,fields):
        value=PTR()
        with self.text(name) as text:code=self.call(self.rules,10,I32,[PTR,C.POINTER(PTR)],text,C.byref(value))
        if code&0xffffffff==0x80070002:return None
        self.check(code);require(value.value,'identity-unknown')
        try:return {name:self.get(value,name) for name in fields}
        finally:self.release(value)
    def add(self,specification):
        value=self.create('2c5bc43e-3369-4c33-ab0c-be9469677af4','af230d27-baba-4e42-aced-f524f22cfce2')
        try:
            # 在发布到规则集合前完成全部属性；Enabled最后写入。
            for name,item in specification.items():
                if name!='Enabled' and not (name in ('ApplicationName','ServiceName') and item==''):self.put(value,name,item)
            self.put(value,'Enabled',specification['Enabled']);self.check(self.call(self.rules,8,I32,[PTR],value))
        finally:self.release(value)
    def set_enabled(self,expected,enabled):
        value=PTR()
        with self.text(expected['Name']) as text:self.check(self.call(self.rules,10,I32,[PTR,C.POINTER(PTR)],text,C.byref(value)))
        require(value.value,'identity-unknown')
        try:
            observed={name:self.get(value,name) for name in expected}
            require(type(observed['Enabled']) is bool and matches(dict(expected,Enabled=observed['Enabled']),observed),'identity-unknown')
            self.put(value,'Enabled',enabled)
        finally:self.release(value)
    def remove(self,name):
        with self.text(name) as text:self.check(self.call(self.rules,9,I32,[PTR],text))
    def guard(self,alias):
        value=I32();self.check(self.call(self.policy,28,I32,[C.POINTER(I32)],C.byref(value)))
        require(value.value==0,'permission-denied')
        for profile in (1,2,4):
            enabled=I16();blocked=I16()
            self.check(self.call(self.policy,8,I32,[I32,C.POINTER(I16)],profile,C.byref(enabled)))
            self.check(self.call(self.policy,12,I32,[I32,C.POINTER(I16)],profile,C.byref(blocked)))
            require(bool(enabled.value) and not blocked.value,'permission-denied')
            excluded=Variant();self.check(self.call(self.policy,10,I32,[I32,C.POINTER(Variant)],profile,C.byref(excluded)))
            try:require(alias not in self.array_values(excluded) and '*' not in self.array_values(excluded),'permission-denied')
            finally:self.auto.VariantClear(C.byref(excluded))
    def close(self):
        for key in ('rules','policy'):
            value=getattr(self,key,None);setattr(self,key,None)
            if value is not None:self.release(value)
        if self.initialized:self.initialized=False;self.ole.CoUninitialize()


class Firewall:
    def __init__(self,api=None):self.api=api or Com();self.owned=[];self.closed=False;self.alias=None
    def install(self,specification,alias,channel):
        require(not self.closed and not self.owned,'state-conflict');self.api.guard(alias)
        values=recipes(specification,alias,channel)
        for value in values:require(self.api.find(value['Name'],value) is None,'resource-busy')
        self.alias=alias
        for value in values:
            disabled=dict(value,Enabled=False)
            self.api.add(disabled);self.owned.append(value)
            require(matches(disabled,self.api.find(value['Name'],value)),'identity-unknown')
            self.api.set_enabled(value,True)
            require(matches(value,self.api.find(value['Name'],value)),'identity-unknown')
    def verify(self):
        require(not self.closed and self.alias is not None,'identity-unknown');self.api.guard(self.alias)
        for value in self.owned:require(matches(value,self.api.find(value['Name'],value)),'identity-unknown')
    def close(self):
        if self.closed:return
        failed=False
        try:
            for value in reversed(self.owned):
                try:
                    observed=self.api.find(value['Name'],value)
                    require(type(observed) is dict and type(observed.get('Enabled')) is bool
                        and matches(dict(value,Enabled=observed['Enabled']),observed),'identity-unknown')
                    self.api.set_enabled(value,False)
                    self.api.remove(value['Name'])
                except (OSError,ValueError,RuntimeError):failed=True
        finally:self.closed=True;self.api.close()
        require(not failed,'identity-unknown')
