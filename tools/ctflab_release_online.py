"""签名索引与版本清单双重核验的在线准备；不激活、启动、停止或安装应用。"""
import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import ssl
import uuid
from urllib.request import Request,build_opener,ProxyHandler,HTTPSHandler

from ctflab_contract import canonical,require,uuid_text
from ctflab_content_cache import ContentCache,NoRedirect,source_url,verify_index
from ctflab_generation_store import private_directory,digest
from ctflab_release_store import release_manifest
from ctflab_release_launcher import read_json
from ctflab_tls_endpoint import guard
from ctflab_windows_recovery import record,command_lock

EMPTY=hashlib.sha256(b'').hexdigest()


def metadata(url,opener,limit,permit=lambda:None):
    permit()
    with opener(Request(url,headers={'Accept-Encoding':'identity'}),timeout=30) as response:
        require(response.geturl()==url and response.status==200
            and response.headers.get('Content-Encoding','identity')=='identity','permission-denied')
        length=response.headers.get('Content-Length')
        require(type(length) is str and length.isdigit() and 0<int(length)<=limit,'storage-insufficient')
        buffer=bytearray();received=0
        while True:
            permit();reader=response.read1 if hasattr(response,'read1') else response.read
            piece=reader(min(65536,int(length)-received+1));permit()
            if not piece:break
            received+=len(piece);require(received<=int(length),'state-conflict');buffer.extend(piece)
        raw=bytes(buffer)
        require(len(raw)==int(length),'state-conflict')
    def unique(pairs):
        value={}
        for key,item in pairs:require(key not in value);value[key]=item
        return value
    return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:require(False))


class OnlineRelease:
    def __init__(self,root,keys,target,*,opener=None,now=None,check=lambda:None):
        self.root=guard(Path(root).absolute());self.keys=json.loads(canonical(keys));self.target=target
        self.opener=opener
        self.now=now;self.check=check

    def plan(self,source,maximum,permit=lambda:None):
        self.check();source_url(source)
        require(type(maximum) is int and 1024**2<=maximum<=16*1024**3)
        if self.opener is None:
            self.opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context())).open
        index=metadata(source+'INDEX.json',self.opener,1024**2+4096,permit)
        signed=metadata(source+'RELEASE.json',self.opener,4*1024**2+4096,permit)
        content,index_sha=verify_index(index,self.keys,source,now=self.now)
        payload,release_sha=release_manifest(signed,self.keys)
        require(payload['schema']==2,'version-mismatch')
        sizes={}
        for name,sha in payload['files'].items():
            if sha==EMPTY:sizes[name]=0;continue
            asset=content['assets'].get(sha)
            require(asset is not None and asset['redistribution']=='allowed' and asset['audience']=='student','permission-denied')
            sizes[name]=asset['size']
        total=sum(sizes.values());require(total<=maximum,'storage-insufficient')
        descriptor={'source':source,'maximum':maximum,'target':self.target,'index_sha256':index_sha,
            'release_sha256':release_sha,'version':payload['version'],'platform':payload['launch']['platform'],
            'files':len(sizes),'bytes':total}
        descriptor['plan_sha256']=hashlib.sha256(canonical(descriptor).encode()).hexdigest()
        self.check()
        return descriptor,index,signed,payload

    def preview(self,source,maximum):
        result,*_=self.plan(source,maximum)
        return dict(result,state='online-release-reviewed',downloaded=False,activated=False)

    def prepare(self,source,maximum,expected,operation,*,resume_sha256=None):
        uuid_text(operation)
        def permit():self.check();require(not self.cancelled(operation),'operation-finished')
        plan_permit=(lambda:self._resume_allowed(operation,resume_sha256)) if resume_sha256 is not None else permit
        plan_permit();plan,index,signed,payload=self.plan(source,maximum,plan_permit)
        require(plan['plan_sha256']==expected,'state-conflict')
        if resume_sha256 is not None:self._resume(operation,resume_sha256)
        permit()
        self.check()
        # 拷贝缓存、下载材料与后续暂存各留一份空间；这不是硬配额或物理容量预留。
        require(shutil.disk_usage(self.root).free>=3*plan['bytes']+64*1024**2,'storage-insufficient')
        with self._library_gate():
            cache_path=self.root/'online-cache'
            cache=ContentCache(cache_path) if cache_path.exists() else ContentCache.create(cache_path)
            directory=self.root/'online-downloads'
            if not directory.exists():private_directory(directory)
            attempt=directory/operation
            guard(directory);require(sum(1 for _ in directory.iterdir())<(257 if attempt.exists() else 256),'storage-insufficient')
            if not attempt.exists():
                private_directory(attempt);record(attempt/'control.lock',{})
            guard(attempt)
        with command_lock(attempt):
            intent={'schema':1,'operation_id':operation,'plan':plan}
            if (attempt/'intent.json').exists():require(read_json(attempt/'intent.json')==intent,'idempotency-conflict')
            else:
                require(set(p.name for p in attempt.iterdir())=={'control.lock'},'identity-unknown')
                record(attempt/'intent.json',intent)
            manifest=attempt/'signed-release.json'
            if manifest.exists():require(read_json(manifest)==signed,'identity-unknown')
            else:record(manifest,signed)
            sources=attempt/'files'
            if not sources.exists():private_directory(sources)
            guard(sources);cache.accept(index,self.keys,source,now=self.now)
            for name,sha in payload['files'].items():
                permit();target=sources/name
                if target.exists():
                    guard(target);require(target.is_file() and target.stat().st_nlink==1 and digest(target)==sha,'identity-unknown')
                    continue
                for parent in reversed(target.parents):
                    if sources==parent or sources in parent.parents:
                        if not parent.exists():private_directory(parent)
                        guard(parent)
                if sha==EMPTY:data=None
                else:
                    data=cache.download(source,sha,opener=self.opener,now=self.now,cancel_requested=lambda:self.cancelled(operation))
                    # 有引用的缓存对象不进入显式回收候选；本轮不执行回收。
                    cache.pin('release-'+plan['release_sha256'],sha)
                fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as output:
                    if data is not None:
                        with data.open('rb') as stream:shutil.copyfileobj(stream,output,1024**2)
                    output.flush();os.fsync(output.fileno())
                require(digest(target)==sha,'identity-unknown')
            # 发布材料前复核完整文件集合，不让保留现场中的额外文件混入后续版本。
            actual=set()
            for current,dirs,files in os.walk(sources,followlinks=False):
                guard(Path(current))
                for name in dirs:guard(Path(current)/name)
                for name in files:
                    path=guard(Path(current)/name);actual.add(path.relative_to(sources).as_posix())
                    require(path.stat().st_nlink==1,'identity-unknown')
            require(actual==set(payload['files']),'identity-unknown')
            for name,sha in payload['files'].items():require(digest(sources/name)==sha,'identity-unknown')
            permit()
            result={'state':'online-files-verified','operation_id':operation,'version':payload['version'],
                'plan_sha256':expected,'source':str(sources),'manifest':str(manifest),'activated':False,'application_started':False}
            receipt=attempt/'complete.json'
            if receipt.exists():require(read_json(receipt)==result,'identity-unknown')
            else:record(receipt,result)
            return result

    def _library_gate(self):
        # 只序列化本版本库的目录建立；长网络传输使用各自操作门与缓存门。
        from ctflab_release_store import ReleaseStore
        return ReleaseStore(self.root).locked()

    def history(self):
        self.check();directory=self.root/'online-downloads'
        if not directory.exists():return []
        guard(directory);result=[]
        for number,path in enumerate(sorted(directory.iterdir()),1):
            require(number<=256,'storage-insufficient');guard(path);uuid_text(path.name)
            intent=read_json(path/'intent.json') if (path/'intent.json').exists() else None
            require(intent is None or intent.get('operation_id')==path.name,'identity-unknown')
            result.append({'operation_id':path.name,'version':intent['plan']['version'] if intent else None,
                'state':'download-recorded' if (path/'complete.json').exists() else 'partial-preserved',
                'pause_recorded':self.cancelled(path.name),
                'files_currently_reverified':False,'automatic_replay':False})
        return result

    def restore(self,operation):
        uuid_text(operation);self.check()
        path=guard(self.root/'online-downloads'/operation/'intent.json')
        intent=read_json(path);plan=intent['plan']
        require(intent.get('operation_id')==operation and plan.get('target')==self.target,'identity-unknown')
        request={
            'action':'online-download','source':plan['source'],'maximum':plan['maximum'],
            'plan_sha256':plan['plan_sha256'],'operation_id':operation}
        if self.cancelled(operation):request['resume_sha256']=digest(self._cancel_path(operation))
        return {'state':'online-request-restored','network_sent':False,'request':request}

    def _cancel_path(self,operation):
        uuid_text(operation);return self.root/'online-cancellations'/(operation+'.json')

    def cancelled(self,operation):
        self.check();path=self._cancel_path(operation)
        require(not path.with_suffix('.pending').exists(),'identity-unknown')
        if not path.exists():return False
        value=read_json(path,4096)
        require(type(value) is dict and set(value)=={'schema','operation_id','cancel_id','target'}
            and type(value['schema']) is int and value['schema']==1 and value['operation_id']==operation and value['target']==self.target,'identity-unknown')
        uuid_text(value['cancel_id']);return True

    def cancel(self,operation,cancel_id):
        uuid_text(operation);uuid_text(cancel_id);self.check();path=self._cancel_path(operation)
        with self._cancel_gate(operation):
            receipt=path.parent/(operation+'-cancel-'+cancel_id+'.json')
            active=self.cancelled(operation)
            if receipt.exists():
                value=read_json(receipt,4096)
                require(value=={'schema':1,'operation_id':operation,'cancel_id':cancel_id,'target':self.target},'identity-unknown')
                sha=digest(path if active else receipt)
            else:
                require(sum(1 for _ in path.parent.iterdir())<4096,'storage-insufficient')
                value={'schema':1,'operation_id':operation,'cancel_id':cancel_id,'target':self.target}
                record(receipt,value);pending=path.with_suffix('.pending');record(pending,value)
                os.replace(pending,path);active=True;sha=digest(path)
        return {'state':'online-cancel-recorded' if active else 'online-cancel-already-resumed','operation_id':operation,
            'cancel_sha256':sha,'pause_recorded':active,'network_sent':False,'existing_files_preserved':True,
            'inflight_request_may_complete':True}

    @contextmanager
    def _cancel_gate(self,operation):
        path=self._cancel_path(operation)
        if not path.parent.exists():
            try:private_directory(path.parent)
            except FileExistsError:guard(path.parent)
        guard(path.parent)
        lock=path.with_suffix('.lock')
        if not lock.exists():
            require(sum(1 for _ in path.parent.iterdir())<4096,'storage-insufficient')
            try:record(lock,{})
            except FileExistsError:pass
        guard(lock)
        if os.name=='nt':
            from ctflab_windows_native import state_lock
            with state_lock(lock):yield
        else:
            import fcntl
            before=lock.stat()
            with lock.open('rb') as stream:
                opened=os.fstat(stream.fileno());require((before.st_dev,before.st_ino)==(opened.st_dev,opened.st_ino),'identity-unknown')
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB);yield

    def _resume_allowed(self,operation,expected):
        require(type(expected) is str and len(expected)==64 and all(c in '0123456789abcdef' for c in expected))
        self.check();path=self._cancel_path(operation)
        require(not path.with_suffix('.pending').exists(),'identity-unknown')
        saved=path.parent/(operation+'-'+expected+'.resumed.json')
        if not path.exists():
            value=read_json(saved,4096)
            require(digest(saved)==expected and value['operation_id']==operation and value['target']==self.target,'identity-unknown')
            return
        require(self.cancelled(operation) and digest(path)==expected,'state-conflict')

    def _resume(self,operation,expected):
        with self._cancel_gate(operation):
            self._resume_allowed(operation,expected);path=self._cancel_path(operation)
            if not path.exists():return
            saved=path.parent/(operation+'-'+expected+'.resumed.json')
            require(not saved.exists(),'state-conflict')
            path.rename(saved)
