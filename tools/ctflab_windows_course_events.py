"""C06自有Windows Application事件：固定源/范围/原生EVTX，只读注册表，不清日志。"""
from datetime import datetime,timezone
import ctypes as C
import hashlib
import hmac
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from ctflab_contract import require,uuid_text,canonical
from ctflab_generation_store import digest
from ctflab_tls_endpoint import guard

SOURCE='CTFLabC06'
CHANNEL='Application'
EVENTS={'incident':1001,'repair':1002,'reset':1003}
MAX_EVENTS=128
MAX_XML=65536
MAX_EVTX=16*1024**2
U32=C.c_uint32
U16=C.c_uint16
PTR=C.c_void_p
BOOL=C.c_int32
NS={'e':'http://schemas.microsoft.com/win/2004/08/events/event'}


def scope(value):
    require(type(value) is dict and set(value)=={'lab_uuid','machine_uuid','generation'},'identity-unknown')
    uuid_text(value['lab_uuid']);uuid_text(value['machine_uuid'])
    require(type(value['generation']) is int and 1<=value['generation']<=2**31-1)
    return value


def terms(value,action,operation,sha):
    scope(value);require(action in EVENTS);uuid_text(operation)
    require(type(sha) is str and re.fullmatch('[0-9a-f]{64}',sha))
    return ['ctflab:c06:'+value['lab_uuid'],'generation:'+str(value['generation']),
        'operation:'+operation,'action:'+action,'state-sha256:'+sha]


def event_signature(value,action,operation,sha,key):
    require(type(key) is str and re.fullmatch('[0-9a-f]{64}',key),'permission-denied')
    payload={'kind':'c06-course-event-v1','scope':value,'action':action,'operation_id':operation,'state_sha256':sha}
    return hmac.new(bytes.fromhex(key),canonical(payload).encode(),hashlib.sha256).hexdigest()


def selection(value,lower=None,upper=None):
    scope(value)
    bound=''
    if lower is not None:
        require(type(lower) is int and type(upper) is int and 0<lower<=upper<2**64)
        bound=f' and EventRecordID>={lower} and EventRecordID<={upper}'
    else:require(upper is None)
    return "*[System[Provider[@Name='"+SOURCE+"'] and (EventID=1001 or EventID=1002 or EventID=1003)"+bound+"] and EventData[Data='ctflab:c06:"+value['lab_uuid']+"' and Data='generation:"+str(value['generation'])+"']]"


def parsed(raw,value,key):
    scope(value);require(type(raw) is str and len(raw.encode('utf-8'))<=MAX_XML
        and '<!DOCTYPE' not in raw.upper() and '<!ENTITY' not in raw.upper(),'identity-unknown')
    try:root=ET.fromstring(raw)
    except ET.ParseError:require(False,'identity-unknown')
    require(root.tag=='{'+NS['e']+'}Event','identity-unknown')
    provider=root.find('./e:System/e:Provider',NS);record=root.findtext('./e:System/e:EventRecordID',namespaces=NS)
    event=root.findtext('./e:System/e:EventID',namespaces=NS);at=root.find('./e:System/e:TimeCreated',NS)
    require(provider is not None and provider.get('Name')==SOURCE and record is not None and record.isdecimal()
        and 0<int(record)<2**64 and event is not None and event.isdecimal() and int(event) in EVENTS.values(),'identity-unknown')
    require(at is not None and type(at.get('SystemTime')) is str,'identity-unknown');timestamp=at.get('SystemTime')
    require(timestamp.endswith('Z') and len(timestamp)<=40,'identity-unknown')
    normalized=re.sub(r'(\.\d{6})\d+(?=Z$)',r'\1',timestamp).replace('Z','+00:00')
    require(datetime.fromisoformat(normalized).utcoffset()==timezone.utc.utcoffset(None),'identity-unknown')
    data=[item.text for item in root.findall('./e:EventData/e:Data',NS)]
    require(len(data)==6 and all(type(item) is str and len(item)<=256 for item in data),'identity-unknown')
    require(data[0]=='ctflab:c06:'+value['lab_uuid'] and data[1]=='generation:'+str(value['generation'])
        and data[2].startswith('operation:') and data[3].startswith('action:') and data[4].startswith('state-sha256:'),'identity-unknown')
    operation=data[2][10:];action=data[3][7:];sha=data[4][13:]
    require(data[:5]==terms(value,action,operation,sha) and EVENTS[action]==int(event)
        and hmac.compare_digest(data[5],'signature:'+event_signature(value,action,operation,sha,key)),'identity-unknown')
    return {'record_id':int(record),'event_id':int(event),'at':timestamp,'operation_id':operation,
        'action':action,'state_sha256':sha,'xml_sha256':hashlib.sha256(raw.encode('utf-8')).hexdigest()}


def absent_source():
    """未注册源按Windows文档写Application；拒绝任何现存同名源，不新建注册表键。"""
    import winreg
    base=r'SYSTEM\CurrentControlSet\Services\EventLog'
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,base,0,winreg.KEY_READ) as parent:
        for index in range(129):
            try:name=winreg.EnumKey(parent,index)
            except OSError as error:
                require(getattr(error,'winerror',None)==259,'permission-denied');return
            require(index<128,'storage-insufficient')
            try:
                with winreg.OpenKey(parent,name+'\\'+SOURCE,0,winreg.KEY_READ):require(False,'permission-denied')
            except FileNotFoundError:pass
    require(False,'identity-unknown')


class API:
    def __init__(self,machine):
        require(os.name=='nt' and C.sizeof(PTR)==8,'unsupported-platform')
        from ctflab_external import native_machine
        require(native_machine()['machine_uuid']==uuid_text(machine),'identity-unknown')
        self.event=C.WinDLL('wevtapi.dll',winmode=0x800,use_last_error=True)
        self.log=C.WinDLL('advapi32.dll',winmode=0x800,use_last_error=True)
        definitions={'EvtQuery':([PTR,C.c_wchar_p,C.c_wchar_p,U32],PTR),
            'EvtNext':([PTR,U32,C.POINTER(PTR),U32,U32,C.POINTER(U32)],BOOL),
            'EvtRender':([PTR,PTR,U32,U32,PTR,C.POINTER(U32),C.POINTER(U32)],BOOL),
            'EvtExportLog':([PTR,C.c_wchar_p,C.c_wchar_p,C.c_wchar_p,U32],BOOL),'EvtClose':([PTR],BOOL)}
        for name,(args,result) in definitions.items():
            fn=getattr(self.event,name);fn.argtypes=args;fn.restype=result;setattr(self,name,fn)
        definitions={'RegisterEventSourceW':([C.c_wchar_p,C.c_wchar_p],PTR),
            'ReportEventW':([PTR,U16,U16,U32,PTR,U16,U32,C.POINTER(C.c_wchar_p),PTR],BOOL),
            'DeregisterEventSource':([PTR],BOOL)}
        for name,(args,result) in definitions.items():
            fn=getattr(self.log,name);fn.argtypes=args;fn.restype=result;setattr(self,name,fn)
        self.error=C.get_last_error;self.absent_source=absent_source


class WindowsEvents:
    def __init__(self,value,key,*,api=None):
        self.scope=scope(value);event_signature(value,'incident','00000000-0000-4000-8000-000000000001','0'*64,key)
        self.key=key;self.is_native=api is None;self.api=api or API(value['machine_uuid'])
    def report(self,action,operation,sha):
        values=terms(self.scope,action,operation,sha)+['signature:'+event_signature(self.scope,action,operation,sha,self.key)];self.api.absent_source()
        source=self.api.RegisterEventSourceW(None,SOURCE);require(bool(source),'permission-denied')
        try:
            strings=(C.c_wchar_p*len(values))(*values)
            require(self.api.ReportEventW(source,4,0,EVENTS[action],None,len(values),0,strings,None),'control-unreachable')
        finally:require(self.api.DeregisterEventSource(source),'control-unreachable')
    def render(self,event):
        used=U32();properties=U32()
        require(not self.api.EvtRender(None,event,1,0,None,C.byref(used),C.byref(properties))
            and self.api.error()==122 and 2<=used.value<=MAX_XML and used.value%2==0,'identity-unknown')
        buffer=C.create_string_buffer(used.value);size=used.value
        require(self.api.EvtRender(None,event,1,size,buffer,C.byref(used),C.byref(properties))
            and 2<=used.value<=size and used.value%2==0 and buffer.raw[used.value-2:used.value]==b'\0\0','identity-unknown')
        raw=buffer.raw[:used.value-2].decode('utf-16-le');require('\0' not in raw,'identity-unknown')
        return parsed(raw,self.scope,self.key)
    def records(self,lower=None,upper=None):
        query=self.api.EvtQuery(None,CHANNEL,selection(self.scope,lower,upper),0x101);require(bool(query),'permission-denied')
        result=[];close_failed=False
        try:
            while True:
                handles=(PTR*16)();count=U32()
                try:
                    ok=self.api.EvtNext(query,16,handles,0,0,C.byref(count))
                    if not ok:require(self.api.error()==259 and count.value==0,'control-unreachable');break
                    require(0<count.value<=16 and len({handles[i] for i in range(count.value)})==count.value
                        and all(handles[i] for i in range(count.value)),'identity-unknown')
                    for index in range(count.value):
                        require(len(result)<MAX_EVENTS,'storage-insufficient');row=self.render(handles[index])
                        require(lower is None or lower<=row['record_id']<=upper,'identity-unknown');result.append(row)
                finally:
                    for handle in set(handles):
                        if handle and not self.api.EvtClose(handle):close_failed=True
        finally:
            if not self.api.EvtClose(query):close_failed=True
        require(not close_failed,'control-unreachable')
        ids=[row['record_id'] for row in result];require(ids==sorted(set(ids)),'identity-unknown')
        return result
    def collect(self,destination):
        destination=guard(Path(destination).absolute());path=destination/'application.evtx'
        require(not path.exists() and not path.is_symlink(),'state-conflict')
        before=self.records()
        if before:
            lower,upper=before[0]['record_id'],before[-1]['record_id']
            require(self.api.EvtExportLog(None,CHANNEL,selection(self.scope,lower,upper),str(path),1),'control-unreachable')
            require(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=MAX_EVTX,'storage-insufficient')
            if os.name!='nt':path.chmod(0o600)
            guard(path);require(path.stat().st_nlink==1,'identity-unknown')
            after=self.records(lower,upper);require(before==after,'identity-unknown')
            file={'sha256':digest(path),'bytes':path.stat().st_size}
        else:file=None
        return {'records':before,'channel':CHANNEL,'source':SOURCE,'evtx':file,
            'native_windows_api_executed':self.is_native,'selection_complete':True,'system_log_cleared':False,
            'scope':'own-course-provider-lab-generation-bounded-record-range','external_clock_verified':False}
