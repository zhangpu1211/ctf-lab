"""签名版本的固定入口启动器；不切换版本、不停止实验、不替换原Mac更新器。"""
import argparse
from dataclasses import asdict
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import subprocess
import sys
import uuid

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,ContractError,public_error
from ctflab_generation_store import private_directory,digest
from ctflab_release_store import ReleaseStore,release_manifest,SIGNED_MANIFEST
from ctflab_release_update import check_journal
from ctflab_tls_endpoint import guard
from ctflab_windows_native import ProcessIdentity, NativeError
from ctflab_windows_recovery import record


class GUID(ctypes.Structure):
    _fields_=[('Data1',ctypes.c_uint32),('Data2',ctypes.c_uint16),('Data3',ctypes.c_uint16),('Data4',ctypes.c_ubyte*8)]


class WINTRUST_FILE_INFO(ctypes.Structure):
    _fields_=[('cbStruct',ctypes.c_uint32),('pcwszFilePath',ctypes.c_wchar_p),('hFile',ctypes.c_void_p),('pgKnownSubject',ctypes.c_void_p)]


class WINTRUST_DATA(ctypes.Structure):
    _fields_=[('cbStruct',ctypes.c_uint32),('pPolicyCallbackData',ctypes.c_void_p),('pSIPClientData',ctypes.c_void_p),
        ('dwUIChoice',ctypes.c_uint32),('fdwRevocationChecks',ctypes.c_uint32),('dwUnionChoice',ctypes.c_uint32),
        ('pFile',ctypes.POINTER(WINTRUST_FILE_INFO)),('dwStateAction',ctypes.c_uint32),('hWVTStateData',ctypes.c_void_p),
        ('pwszURLReference',ctypes.c_wchar_p),('dwProvFlags',ctypes.c_uint32),('dwUIContext',ctypes.c_uint32),('pSignatureSettings',ctypes.c_void_p)]


def verify_embedded_signature(path,*,verify=None):
    """Windows Authenticode：无UI、仅缓存链/撤销检查，只有返回0才成功；始终关闭provider状态。"""
    if verify is None:
        require(os.name=='nt','unsupported-platform')
        native=ctypes.WinDLL('wintrust.dll',winmode=0x800)
        verify=native.WinVerifyTrust;verify.argtypes=[ctypes.c_void_p,ctypes.POINTER(GUID),ctypes.c_void_p];verify.restype=ctypes.c_int32
    action=GUID.from_buffer_copy(uuid.UUID('00aac56b-cd44-11d0-8cc2-00c04fc295ee').bytes_le)
    info=WINTRUST_FILE_INFO();info.cbStruct=ctypes.sizeof(info);info.pcwszFilePath=str(path)
    data=WINTRUST_DATA();data.cbStruct=ctypes.sizeof(data);data.dwUIChoice=2;data.dwUnionChoice=1
    data.pFile=ctypes.pointer(info);data.dwStateAction=1
    data.dwProvFlags=0x80|0x1000|0x2000
    try:require(verify(ctypes.c_void_p(-1),ctypes.byref(action),ctypes.byref(data))==0,'permission-denied')
    finally:
        data.dwStateAction=2;verify(ctypes.c_void_p(-1),ctypes.byref(action),ctypes.byref(data))
    return True


def host_platform():
    system=platform.system();machine=platform.machine().lower()
    require(system in ('Windows','Linux') and machine in ('amd64','x86_64') and ctypes.sizeof(ctypes.c_void_p)==8,'unsupported-platform')
    return 'windows-x64' if system=='Windows' else 'linux-x64'


def native_observer():
    if platform.system()=='Windows':
        from ctflab_windows_native import Win32
        return Win32()
    if platform.system()=='Linux':
        from ctflab_linux_native import LinuxObserver
        return LinuxObserver()
    raise NativeError('unsupported-platform')


def checked_identity(value,pid,entry,platform_name):
    require(type(value) is ProcessIdentity and type(value.pid) is int and value.pid==pid
            and type(value.creation_ticks) is int and value.creation_ticks>0
            and type(value.image_path) is str and value.state in ('running','exited'),'identity-unknown')
    actual=value.image_path;expected=str(entry)
    if platform_name=='windows-x64':actual=actual.casefold();expected=expected.casefold()
    require(actual==expected,'identity-unknown')
    return value


def safe_environment():
    names=('HOME','USERPROFILE','APPDATA','LOCALAPPDATA','TEMP','TMP','LANG','LC_ALL','DISPLAY',
           'WAYLAND_DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS','XDG_CONFIG_HOME','XDG_DATA_HOME')
    result={name:os.environ[name] for name in names if name in os.environ}
    if os.name=='nt':
        native=ctypes.WinDLL('kernel32.dll',winmode=0x800)
        for key,function in (('SystemRoot','GetWindowsDirectoryW'),('PATH','GetSystemDirectoryW')):
            call=getattr(native,function);call.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32];call.restype=ctypes.c_uint32
            buffer=ctypes.create_unicode_buffer(32768);length=call(buffer,len(buffer))
            require(0<length<len(buffer),'capability-unverified');result[key]=buffer.value
        result['WINDIR']=result['SystemRoot']
    else:result['PATH']='/usr/bin:/bin'
    return result


def read_json(path,limit=4*1024**2):
    path=guard(Path(path).absolute());info=path.stat();require(path.is_file() and info.st_nlink==1 and info.st_size<=limit)
    def unique(pairs):
        result={}
        for key,value in pairs:require(key not in result);result[key]=value
        return result
    with path.open('rb') as stream:raw=stream.read(limit+1)
    require(len(raw)<=limit)
    result=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:require(False))
    require(digest(path)==hashlib.sha256(raw).hexdigest(),'state-conflict')
    return result


class ReleaseLauncher:
    def __init__(self,releases,keys,*,host=host_platform,signature=verify_embedded_signature,spawn=subprocess.Popen,observer=native_observer):
        self.releases=releases;self.keys=json.loads(canonical(keys));self.host=host;self.signature=signature;self.spawn=spawn;self.observer=observer

    def selected(self,db):
        self.releases.check_launches();check_journal(self.releases,db)
        require(not db.execute("SELECT 1 FROM updates WHERE state='intent'").fetchone(),'identity-unknown')
        active=db.execute('SELECT active FROM pointers WHERE id=1').fetchone()[0]
        require(type(active) is str and len(active)<=128 and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?',active),'state-conflict')
        row=db.execute('SELECT digest,path,payload FROM versions WHERE id=?',(active,)).fetchone()
        require(row is not None,'state-conflict')
        stored=json.loads(row[2]);require(type(stored) is dict and type(stored.get('schema')) is int and stored['schema']==2,'version-mismatch')
        path=self.releases.root/'versions'/active
        require(Path(row[1])==path,'identity-unknown');guard(path)
        envelope=read_json(path/SIGNED_MANIFEST,4*1024**2+4096);payload,sha=release_manifest(envelope,self.keys)
        require(payload['schema']==2 and payload['version']==active and payload==stored and sha==row[0],'identity-unknown')
        require(payload['launch']['platform']==self.host(),'unsupported-platform')
        self.releases.check(path,payload)
        entry=guard(path/payload['launch']['entry'])
        os_verified=False
        if payload['launch']['platform']=='windows-x64':
            require(self.signature(entry) is True,'permission-denied');os_verified=True
        else:require(os.access(entry,os.X_OK),'permission-denied')
        self.releases.check(path,payload)
        result={'schema':1,'version':active,'platform':payload['launch']['platform'],'entry':payload['launch']['entry'],
            'payload_sha256':sha,'entry_sha256':payload['files'][payload['launch']['entry']],
            'files':len(payload['files']),'release_signature_verified':True,'authenticode_verified':os_verified,
            'network_retrieval':False,'data_schema':payload['data_schema'],'runtime_verified':False,'automatic_stop':False,
            'application_gate_scope':'launches-through-this-store-only'}
        result['plan_sha256']=hashlib.sha256(canonical(result).encode()).hexdigest()
        return result,path

    def preview(self):
        with self.releases.application_gate(),self.releases.locked() as db:return self.selected(db)[0]

    def run(self,expected):
        require(type(expected) is str and len(expected)==64 and all(c in '0123456789abcdef' for c in expected))
        with self.releases.application_gate():
            with self.releases.locked() as db:
                plan,path=self.selected(db);require(plan['plan_sha256']==expected,'state-conflict')
                require(len(list((self.releases.root/'launches').iterdir()))<4096,'storage-insufficient')
                identity=str(uuid.uuid4());attempt=self.releases.root/'launches'/identity;private_directory(attempt)
                intent={'schema':1,'launch_id':identity,'version':plan['version'],'platform':plan['platform'],
                    'entry':plan['entry'],'entry_sha256':plan['entry_sha256'],'payload_sha256':plan['payload_sha256'],
                    'plan_sha256':expected}
                record(attempt/'intent.json',intent)
                options={'cwd':str(path),'stdin':subprocess.DEVNULL,'stdout':subprocess.DEVNULL,
                         'stderr':subprocess.DEVNULL,'env':safe_environment(),'close_fds':True}
                if os.name=='nt':options['creationflags']=subprocess.CREATE_NEW_PROCESS_GROUP
                else:options['start_new_session']=True
                process=self.spawn([str(path/plan['entry'])],**options)
                record(attempt/'spawned.json',{'launch_id':identity,'pid':process.pid,'intent_sha256':digest(attempt/'intent.json')})
                # 快速退出/不可观察不猜身份；父进程仍可正常等待，独立恢复则保守拒绝。
                try:
                    require(process.poll() is None,'identity-unknown')
                    observed=checked_identity(self.observer().observe(process.pid),process.pid,path/plan['entry'],plan['platform'])
                    require(process.poll() is None,'identity-unknown')
                except (NativeError,OSError,ContractError):observed=None
                if observed is not None:
                    record(attempt/'identity.json',{'schema':1,'launch_id':identity,
                        'spawn_sha256':digest(attempt/'spawned.json'),'process':asdict(observed)})
            # 仅持有应用门，不占用版本数据库；中断不杀子进程，也不伪造退出证明。
            code=process.wait();require(type(code) is int,'identity-unknown')
            record(attempt/'exit.json',{'schema':1,'launch_id':identity,'intent_sha256':digest(attempt/'intent.json'),
                'spawn_sha256':digest(attempt/'spawned.json'),'source':'retained-child-process','returncode':code})
            return {'state':'application-exited','version':plan['version'],'launch_id':identity,'returncode':code,
                    'runtime_verified':False,'vm_stopped':False,'automatic_replay':False}

    def review_locked(self,identity):
        from ctflab_contract import uuid_text
        uuid_text(identity)
        attempt=guard(self.releases.root/'launches'/identity)
        require(not (attempt/'exit.json').exists() and not (attempt/'settled.json').exists(),'state-conflict')
        intent=read_json(attempt/'intent.json',16384);binding=read_json(attempt/'spawned.json',16384)
        saved=read_json(attempt/'identity.json',16384)
        require(type(intent) is dict and type(intent.get('schema')) is int and intent['schema']==1 and intent.get('launch_id')==identity
                and intent.get('platform')==self.host(),'identity-unknown')
        require(type(intent.get('version')) is str and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?',intent['version'])
                and intent.get('entry')=={'windows-x64':'ctflab-desktop.exe','linux-x64':'ctflab-desktop'}.get(intent['platform']),'identity-unknown')
        require(type(binding) is dict and set(binding)=={'launch_id','pid','intent_sha256'}
                and binding['launch_id']==identity and type(binding['pid']) is int and binding['pid']>0
                and binding['intent_sha256']==digest(attempt/'intent.json'),'identity-unknown')
        require(type(saved) is dict and set(saved)=={'schema','launch_id','spawn_sha256','process'}
                and type(saved['schema']) is int and saved['schema']==1 and saved['launch_id']==identity
                and saved['spawn_sha256']==digest(attempt/'spawned.json')
                and type(saved['process']) is dict and set(saved['process'])=={'pid','creation_ticks','image_path','state'},'identity-unknown')
        expected=checked_identity(ProcessIdentity(**saved['process']),binding['pid'],
            self.releases.root/'versions'/intent['version']/intent['entry'],intent['platform'])
        observer=self.observer();current=observer.observe(expected.pid)
        checked_identity(current,expected.pid,Path(expected.image_path),intent['platform'])
        require(current.creation_ticks==expected.creation_ticks,'identity-unknown')
        result={'schema':1,'launch_id':identity,'version':intent['version'],
            'intent_sha256':digest(attempt/'intent.json'),'spawn_sha256':digest(attempt/'spawned.json'),
            'identity_sha256':digest(attempt/'identity.json'),'process_state':current.state,
            'scope':'bound-application-process-only','vm_stopped':False,'automatic_replay':False}
        result['review_sha256']=hashlib.sha256(canonical(result).encode()).hexdigest()
        return result,attempt,expected,observer

    def review(self,identity):
        # 不取写数据库门，也不创建/迁移记录；应用门被占用时直接拒绝。
        with self.releases.application_gate():return self.review_locked(identity)[0]

    def settle(self,identity,expected_sha,wait_ms=0):
        require(type(expected_sha) is str and re.fullmatch('[0-9a-f]{64}',expected_sha) is not None)
        require(type(wait_ms) is int and 0<=wait_ms<=1000)
        with self.releases.application_gate(),self.releases.locked():
            review,attempt,expected,observer=self.review_locked(identity)
            require(review['review_sha256']==expected_sha,'state-conflict')
            # 只等待经创建时间与映像重新核验的同一内核对象；缺PID永远不是退出证据。
            with observer.retained(expected) as handle:outcome=observer.wait_exit(handle,wait_ms)
            require(outcome is not None,'resource-busy')
            if type(outcome) is dict:
                require(outcome=={'state':'exited','returncode':None,'source':'retained-linux-pidfd','exit_code_known':False}
                        and self.host()=='linux-x64','identity-unknown')
                source='retained-linux-pidfd';code=None
            else:
                require(type(outcome) is int and self.host()=='windows-x64','identity-unknown')
                source='retained-win32-handle';code=outcome
            # 观察期间原始记录漂移时不写结清；历史原文件始终保留。
            for name,key in (('intent.json','intent_sha256'),('spawned.json','spawn_sha256'),('identity.json','identity_sha256')):
                require(digest(guard(attempt/name))==review[key],'state-conflict')
            record(attempt/'settled.json',{'schema':1,'launch_id':identity,
                'intent_sha256':review['intent_sha256'],'spawn_sha256':review['spawn_sha256'],
                'identity_sha256':review['identity_sha256'],'review_sha256':expected_sha,
                'source':source,'returncode':code,'exit_code_known':code is not None})
            self.releases.launch_exit(attempt)
            return {'state':'application-exit-settled','launch_id':identity,'returncode':code,
                'exit_code_known':code is not None,'scope':'bound-application-process-only',
                'vm_stopped':False,'automatic_replay':False,'runtime_verified':False}

    def history(self):
        directory=guard(self.releases.root/'launches');rows=[]
        for path in sorted(directory.iterdir()):
            guard(path);require(len(rows)<4096,'storage-insufficient')
            from ctflab_contract import uuid_text
            uuid_text(path.name)
            try:self.releases.launch_exit(path);state='exit-recorded'
            except (OSError,ValueError,RuntimeError,TypeError,KeyError):state='unknown'
            rows.append({'launch_id':path.name,'state':state,
                         'automatic_replay':False,'automatic_cleanup':False})
        return {'launches':rows,'scope':'historical-files-not-live-process-observation','vm_stopped':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('preview','run','history','review','settle'))
    parser.add_argument('--root',required=True,type=Path);parser.add_argument('--keys',type=Path);parser.add_argument('--plan-sha256')
    parser.add_argument('--launch-id');parser.add_argument('--review-sha256');parser.add_argument('--wait-ms',type=int,default=0)
    args=parser.parse_args(argv)
    try:
        require(bool(args.plan_sha256)==(args.action=='run'))
        require(bool(args.launch_id)==(args.action in ('review','settle')))
        require(bool(args.review_sha256)==(args.action=='settle'))
        require(args.action=='settle' or args.wait_ms==0)
        launcher=ReleaseLauncher(ReleaseStore(args.root),read_json(args.keys) if args.keys else {})
        if args.action in ('preview','run'):require(args.keys is not None)
        result=launcher.review(args.launch_id) if args.action=='review' else launcher.settle(args.launch_id,args.review_sha256,args.wait_ms) if args.action=='settle' else launcher.preview() if args.action=='preview' else launcher.run(args.plan_sha256) if args.action=='run' else launcher.history()
        print(canonical(result));return 0
    except ContractError as error:
        print(canonical({'state':'refused-or-unknown','error':public_error(error.code),'preserved':True,'automatic_replay':False,'vm_stopped':False}));return 2
    except (OSError,ValueError,RuntimeError,TypeError,KeyError,sqlite3.Error,NativeError,KeyboardInterrupt):
        print(canonical({'state':'refused-or-unknown','preserved':True,'automatic_replay':False,'vm_stopped':False}));return 2


if __name__=='__main__':raise SystemExit(main())
