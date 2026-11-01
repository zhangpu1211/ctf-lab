"""内容缓存显式回收账本：逐对象写尝试，未知不重试；仅未尝试对象可继续。"""
import hashlib
import os
from pathlib import Path
import stat

from ctflab_contract import canonical,require,uuid_text
from ctflab_generation_store import digest
from ctflab_runtime_inventory import signature
from ctflab_tls_endpoint import guard

MAX_OBJECTS=20000
MAX_JOBS=256


def sha(value):
    from ctflab_content_cache import checksum
    return checksum(value)


def fingerprint(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def exists(path):
    try:info=path.lstat()
    except FileNotFoundError:return False
    require(stat.S_ISREG(info.st_mode) and info.st_nlink==1,'identity-unknown')
    guard(path);return True


def snapshot(path):
    sha(path.name);info=guard(path).stat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink==1,'identity-unknown')
    value={'sha256':path.name,'size':info.st_size,'identity':[info.st_dev,info.st_ino],
           'stamp':list(signature(info)),'digest':digest(path)}
    require(list(signature(guard(path).stat()))==value['stamp'],'identity-unknown')
    return value


def candidates(cache,db):
    refs=db.execute('SELECT owner,sha FROM refs LIMIT 20001').fetchall()
    require(len(refs)<=MAX_OBJECTS,'storage-insufficient')
    from ctflab_contract import identifier
    for owner,value in refs:identifier(owner);sha(value)
    referenced={row[1] for row in refs};result=[];paths=[]
    for path in guard(cache.root/'objects').iterdir():
        require(len(paths)<MAX_OBJECTS,'storage-insufficient');paths.append(path)
    for path in sorted(paths):
        # 即使有引用，也验证文件类型；未知对象不能被当作可安全回收的目录。
        require(exists(path),'identity-unknown');sha(path.name)
        if path.name not in referenced:result.append(snapshot(path))
    return result


def identity(cache):
    result=[]
    for index,path in enumerate((cache.root,cache.root/'cache.sqlite3',cache.root/'objects')):
        info=guard(path).stat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 if index==1 else stat.S_ISDIR(info.st_mode),'identity-unknown')
        result.append([info.st_dev,info.st_ino])
    return result


def read(path,maximum=8*1024**2):
    require(exists(path),'identity-unknown');info=path.stat()
    require(info.st_size<=maximum,'storage-insufficient')
    from ctflab_remote import decode
    value=decode(path.read_bytes(),maximum)
    require(signature(path.stat())==signature(info),'identity-unknown')
    return value


def sync_directory(path):
    if os.name!='nt':
        fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)


def record(path,value):
    from ctflab_windows_recovery import record as write
    write(path,value)
    # POSIX落盘父目录项；Windows只使用文件fsync，不声称断电后目录项持久性已验。
    sync_directory(path.parent)


class Collector:
    def __init__(self,cache):self.cache=cache
    def path(self,operation,suffix):return self.cache.root/('gc-'+uuid_text(operation)+suffix)
    def plan(self,db):
        value={'schema':2,'cache_identity':identity(self.cache),'objects':candidates(self.cache,db)}
        return dict(value,plan_sha256=fingerprint(value),automatic_cleanup=False)
    def preview(self):
        with self.cache.locked() as db:return self.plan(db)
    def intent(self,operation):
        value=read(self.path(operation,'.intent.json'))
        # 旧账本没有逐对象尝试边界，只能只读交接，不能推断仍可安全继续。
        if set(value)=={'objects','automatic_replay'}:
            require(value['automatic_replay'] is False,'identity-unknown');return None
        require(set(value)=={'schema','cache_identity','objects','operation_id','plan_sha256','automatic_replay'}
            and type(value['schema']) is int and value['schema']==2 and value['automatic_replay'] is False
            and value['operation_id']==operation and value['cache_identity']==identity(self.cache),'identity-unknown')
        require(type(value['cache_identity']) is list and len(value['cache_identity'])==3
            and all(type(pair) is list and len(pair)==2 and all(type(n) is int for n in pair)
                for pair in value['cache_identity']),'identity-unknown')
        objects=value['objects'];require(type(objects) is list and len(objects)<=MAX_OBJECTS,'identity-unknown')
        names=[]
        for item in objects:
            require(type(item) is dict and set(item)=={'sha256','size','identity','stamp','digest'},'identity-unknown')
            sha(item['sha256']);sha(item['digest']);names.append(item['sha256'])
            require(type(item['size']) is int and item['size']>=0 and type(item['identity']) is list
                and len(item['identity'])==2 and type(item['stamp']) is list and len(item['stamp'])==5
                and all(type(n) is int for n in item['identity']+item['stamp'])
                and item['stamp'][:2]==item['identity'] and item['stamp'][2]==item['size'],'identity-unknown')
        require(names==sorted(set(names)) and value['plan_sha256']==fingerprint({key:value[key]
            for key in ('schema','cache_identity','objects')}),'identity-unknown')
        return value
    def receipt(self,operation,item,phase,plan):
        path=self.path(operation,'-'+item['sha256']+'.'+phase+'.json')
        if not exists(path):return None
        value=read(path,65536)
        fields={'schema','operation_id','plan_sha256','sha256','object_sha256'}
        if phase=='result':fields.add('state')
        require(set(value)==fields and type(value['schema']) is int and value['schema']==2
            and value['operation_id']==operation and value['plan_sha256']==plan
            and value['sha256']==item['sha256'] and value['object_sha256']==fingerprint(item),'identity-unknown')
        if phase=='result':require(value['state'] in ('removed','preserved'),'identity-unknown')
        return value
    def view(self,db,operation):
        intent=self.intent(operation)
        if intent is None:
            value={'schema':2,'operation_id':operation,'state':'legacy-unresolved','objects':[],
                'automatic_replay':False,'resumable':False,'cleanup_verified':False}
            return dict(value,observation_sha256=fingerprint(value))
        rows=[]
        for item in intent['objects']:
            name=item['sha256'];attempt=self.receipt(operation,item,'attempt',intent['plan_sha256'])
            result=self.receipt(operation,item,'result',intent['plan_sha256'])
            require(result is None or attempt is not None,'identity-unknown')
            path=self.cache.root/'objects'/name
            current=snapshot(path) if exists(path) else None
            refs=[row[0] for row in db.execute('SELECT owner FROM refs WHERE sha=? ORDER BY owner LIMIT 20001',(name,))]
            require(len(refs)<=MAX_OBJECTS,'storage-insufficient')
            from ctflab_contract import identifier
            for owner in refs:identifier(owner)
            phase=result['state'] if result else 'unknown' if attempt else 'unattempted'
            rows.append({'sha256':name,'phase':phase,'current':current,'references':refs,
                'eligible':phase=='unattempted' and current==item and not refs})
        pending=[row for row in rows if row['phase']=='unattempted']
        unknown=any(row['phase']=='unknown' for row in rows)
        value={'schema':2,'operation_id':operation,'plan_sha256':intent['plan_sha256'],'objects':rows,
            'state':'gc-observed' if pending or unknown else 'gc-finished',
            'automatic_replay':False,'resumable':bool(pending) and all(row['eligible'] for row in pending),
            'cleanup_verified':False}
        # 即使读到原removed回执，重现的同名对象和未知外部写入也不推断已清理。
        return dict(value,observation_sha256=fingerprint(value))
    def status(self,operation):
        uuid_text(operation)
        with self.cache.locked() as db:return self.view(db,operation)
    def apply(self,db,operation,intent):
        outcomes=[]
        for item in intent['objects']:
            if self.receipt(operation,item,'attempt',intent['plan_sha256']) is not None:continue
            require(self.receipt(operation,item,'result',intent['plan_sha256']) is None,'identity-unknown')
            path=self.cache.root/'objects'/item['sha256']
            require(snapshot(path)==item and not db.execute('SELECT 1 FROM refs WHERE sha=? LIMIT 1',
                (item['sha256'],)).fetchone(),'state-conflict')
            binding={'schema':2,'operation_id':operation,'plan_sha256':intent['plan_sha256'],
                     'sha256':item['sha256'],'object_sha256':fingerprint(item)}
            record(self.path(operation,'-'+item['sha256']+'.attempt.json'),binding)
            # 尝试记录持久后再做一次身份核对；失败留下unknown，不能猜测可重放。
            require(snapshot(path)==item,'identity-unknown')
            try:path.unlink();outcome='removed'
            except OSError:outcome='preserved'
            if outcome=='removed':sync_directory(path.parent)
            record(self.path(operation,'-'+item['sha256']+'.result.json'),dict(binding,state=outcome))
            outcomes.append({'sha256':item['sha256'],'state':outcome})
        return outcomes
    def ensure_new(self,operation):
        path=self.path(operation,'.intent.json')
        if exists(path):raise FileExistsError(str(path))
        # 不能把旧孤立回执纳入新操作，即使它对应当前计划外的对象。
        for receipt in self.cache.root.glob('gc-'+operation+'-*.json'):
            require(not exists(receipt),'identity-unknown')
    def start(self,operation,approved):
        uuid_text(operation);sha(approved)
        with self.cache.locked() as db:
            current=self.plan(db);require(current['plan_sha256']==approved,'state-conflict')
            self.ensure_new(operation)
            count=0
            for _ in self.cache.root.glob('gc-*.intent.json'):
                count+=1;require(count<MAX_JOBS,'storage-insufficient')
            intent={key:current[key] for key in ('schema','cache_identity','objects','plan_sha256')}
            intent.update(operation_id=operation,automatic_replay=False)
            record(self.path(operation,'.intent.json'),intent)
            return self.apply(db,operation,intent)
    def resume(self,operation,observed):
        uuid_text(operation);sha(observed)
        with self.cache.locked() as db:
            current=self.view(db,operation)
            require(current['observation_sha256']==observed and current['resumable'],'state-conflict')
            self.apply(db,operation,self.intent(operation))
            return self.view(db,operation)
