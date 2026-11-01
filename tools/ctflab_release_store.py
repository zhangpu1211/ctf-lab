"""离线安装版本存储：签名白名单文件、完整暂存、原子激活和手动回退。

应用版本与实验数据分离；不迁移、不删除实验、旧版本或失败暂存目录。
"""
import base64
from contextlib import contextmanager,closing
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import shutil
import sqlite3
import uuid

from ctflab_contract import canonical,require
from ctflab_generation_store import private_directory,digest
from ctflab_tls_endpoint import guard

SIGNED_MANIFEST='RELEASE-MANIFEST.json'
LAUNCH_ENTRIES={'windows-x64':'ctflab-desktop.exe','linux-x64':'ctflab-desktop'}

def release_manifest(envelope,keys):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    require(type(envelope) is dict and set(envelope)=={'key_id','signature','payload'})
    require(type(keys) is dict and isinstance(envelope['key_id'],str)
            and isinstance(envelope['signature'],str) and len(envelope['signature'])<=128)
    require(envelope['key_id'] in keys,'permission-denied')
    payload=envelope['payload'];raw=canonical(payload).encode();require(len(raw)<=4*1024**2)
    try:Ed25519PublicKey.from_public_bytes(bytes.fromhex(keys[envelope['key_id']])).verify(base64.b64decode(envelope['signature'],validate=True),raw)
    except (InvalidSignature,ValueError,TypeError):require(False,'permission-denied')
    payload=json.loads(raw)
    require(type(payload) is dict and type(payload.get('schema')) is int and payload['schema'] in (1,2))
    require(set(payload)=={'schema','version','data_schema','files','licenses'}|({'launch'} if payload['schema']==2 else set()))
    require(isinstance(payload['version'],str) and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?',payload['version']))
    require(type(payload['data_schema']) is int and payload['data_schema']==1,'version-mismatch')
    require(type(payload['files']) is dict and 1<=len(payload['files'])<=20000)
    folded=set();prefixes={}
    for name,sha in payload['files'].items():
        require(isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9_-]+(?:[A-Za-z0-9_./-]*[A-Za-z0-9_-])?',name))
        parts=PurePosixPath(name).parts
        if payload['schema']==2:
            require(parts[0].casefold()!=SIGNED_MANIFEST.casefold() and all(not part.endswith('.') for part in parts))
            for index in range(1,len(parts)+1):
                prefix='/'.join(parts[:index]);folded_prefix=prefix.casefold()
                require(prefixes.get(folded_prefix,prefix)==prefix);prefixes[folded_prefix]=prefix
        require(not name.startswith('/') and str(PurePosixPath(name))==name and '..' not in parts
                and all(p.split('.')[0].upper() not in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]} for p in parts))
        require(name.casefold() not in folded);folded.add(name.casefold())
        require(isinstance(sha,str) and re.fullmatch('[0-9a-f]{64}',sha))
    require(type(payload['licenses']) is list and payload['licenses'] and all(n in payload['files'] for n in payload['licenses']))
    if payload['schema']==2:
        launch=payload['launch'];require(type(launch) is dict and set(launch)=={'platform','entry','executables'})
        require(type(launch['platform']) is str and launch['platform'] in LAUNCH_ENTRIES
                and launch['entry']==LAUNCH_ENTRIES[launch['platform']] and launch['entry'] in payload['files'],'capability-unverified')
        require(type(launch['executables']) is list and 1<=len(launch['executables'])<=256
                and all(type(n) is str and n in payload['files'] for n in launch['executables'])
                and len(set(launch['executables']))==len(launch['executables'])
                and launch['entry'] in launch['executables'])
    return payload,hashlib.sha256(raw).hexdigest()


class ReleaseStore:
    def __init__(self,root):
        self.root=Path(root).absolute();guard(self.root);guard(self.root/'releases.sqlite3')

    @classmethod
    def create(cls,root):
        root=Path(root).absolute();private_directory(root)
        private_directory(root/'versions');private_directory(root/'staging')
        private_directory(root/'update-backups')
        private_directory(root/'launches')
        fd=os.open(root/'application.lock',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
        fd=os.open(root/'releases.sqlite3',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
        from ctflab_release_update import SCHEMA
        with closing(sqlite3.connect(root/'releases.sqlite3')) as db:
            db.executescript('CREATE TABLE versions(id TEXT PRIMARY KEY,digest TEXT,path TEXT,payload TEXT);'
                             'CREATE TABLE pointers(id INTEGER PRIMARY KEY,active TEXT,previous TEXT);'
                             'INSERT INTO pointers VALUES(1,NULL,NULL);'
                             'CREATE TABLE refs(owner TEXT,version TEXT,PRIMARY KEY(owner,version));'+SCHEMA)
            db.commit()
        return cls(root)

    @contextmanager
    def locked(self):
        guard(self.root);guard(self.root/'releases.sqlite3')
        db=sqlite3.connect((self.root/'releases.sqlite3').as_uri()+'?mode=rw',uri=True,timeout=0)
        try:
            db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE');yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    def check(self,path,payload):
        from ctflab_runtime_inventory import check_path,hash_file
        for name,sha in payload['files'].items():
            file=path/name
            info=check_path(file)
            require(file.is_file() and info.st_nlink==1 and hash_file(file,info)==sha,'state-conflict')
        if payload['schema']==2:
            if payload['launch']['platform']=='linux-x64' and os.name!='nt':
                require(all(os.access(path/name,os.X_OK) for name in payload['launch']['executables']),'permission-denied')
            metadata=path/SIGNED_MANIFEST;info=check_path(metadata)
            require(metadata.is_file() and info.st_nlink==1 and info.st_size<=4*1024**2+4096,'state-conflict')
            expected=set(payload['files'])|{SIGNED_MANIFEST};seen=set();directories={'.'}
            for name in expected:
                directories.update(str(p) for p in PurePosixPath(name).parents)
            for current,dirs,files in os.walk(path,followlinks=False):
                require(str(Path(current).relative_to(path)).replace(os.sep,'/') in directories,'state-conflict')
                for name in dirs:
                    child=Path(current)/name
                    require(str(child.relative_to(path)).replace(os.sep,'/') in directories and child.is_dir() and not child.is_symlink(),'state-conflict')
                    check_path(child)
                for name in files:seen.add(str((Path(current)/name).relative_to(path)).replace(os.sep,'/'));check_path(Path(current)/name)
            require(seen==expected,'state-conflict')

    @contextmanager
    def application_gate(self):
        path=guard(self.root/'application.lock')
        info=path.stat();require(path.is_file() and info.st_nlink==1,'permission-denied')
        if os.name=='nt':
            from ctflab_windows_native import state_lock
            with state_lock(path):yield
        else:
            import fcntl
            with path.open('rb') as stream:
                opened=os.fstat(stream.fileno());require((opened.st_dev,opened.st_ino)==(info.st_dev,info.st_ino),'identity-unknown')
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
                yield

    def check_launches(self):
        directory=guard(self.root/'launches')
        from ctflab_contract import uuid_text
        for number,path in enumerate(directory.iterdir(),1):
            require(number<=4096,'storage-insufficient');guard(path);uuid_text(path.name)
            self.launch_exit(path)

    def launch_exit(self,path):
        from ctflab_contract import uuid_text
        guard(path);uuid_text(path.name)
        require(all((path/name).is_file() for name in ('intent.json','spawned.json'))
                and ((path/'exit.json').is_file() or ((path/'identity.json').is_file() and (path/'settled.json').is_file())),'identity-unknown')
        from ctflab_release_launcher import read_json,checked_identity
        from ctflab_windows_native import ProcessIdentity
        intent=guard(path/'intent.json');spawned=guard(path/'spawned.json')
        original=read_json(intent,16384);binding=read_json(spawned,16384)
        require(type(original) is dict and original.get('launch_id')==path.name
                and type(original.get('schema')) is int and original['schema']==1,'identity-unknown')
        require(type(binding) is dict and set(binding)=={'launch_id','pid','intent_sha256'}
                and binding['launch_id']==path.name and type(binding['pid']) is int and binding['pid']>0
                and binding['intent_sha256']==digest(intent),'identity-unknown')
        # 原父进程退出证明优先；损坏的旧证明不能由另一记录掩盖。
        if (path/'exit.json').exists():
            result=read_json(path/'exit.json',16384)
            require(type(result) is dict and set(result)=={'schema','launch_id','intent_sha256','spawn_sha256','source','returncode'}
                    and type(result['schema']) is int and result['schema']==1 and result['launch_id']==path.name
                    and result['intent_sha256']==digest(intent) and result['spawn_sha256']==digest(spawned) and type(result['returncode']) is int
                    and result['source']=='retained-child-process','identity-unknown')
            return result
        saved=read_json(path/'identity.json',16384);result=read_json(path/'settled.json',16384)
        require(type(saved) is dict and set(saved)=={'schema','launch_id','spawn_sha256','process'}
                and type(saved['schema']) is int and saved['schema']==1 and saved['launch_id']==path.name
                and saved['spawn_sha256']==digest(spawned) and type(saved['process']) is dict
                and set(saved['process'])=={'pid','creation_ticks','image_path','state'},'identity-unknown')
        require(type(original.get('version')) is str and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.]+)?',original['version'])
                and original.get('entry')==LAUNCH_ENTRIES.get(original.get('platform')),'identity-unknown')
        checked_identity(ProcessIdentity(**saved['process']),binding['pid'],
            self.root/'versions'/original['version']/original['entry'],original['platform'])
        require(type(result) is dict and set(result)=={'schema','launch_id','intent_sha256','spawn_sha256','identity_sha256',
                'review_sha256','source','returncode','exit_code_known'} and type(result['schema']) is int and result['schema']==1
                and result['launch_id']==path.name and result['intent_sha256']==digest(intent)
                and result['spawn_sha256']==digest(spawned) and result['identity_sha256']==digest(path/'identity.json')
                and type(result['review_sha256']) is str and re.fullmatch('[0-9a-f]{64}',result['review_sha256']) is not None,'identity-unknown')
        require((original['platform']=='linux-x64' and result['source']=='retained-linux-pidfd'
                 and result['returncode'] is None and result['exit_code_known'] is False)
                or (original['platform']=='windows-x64' and result['source']=='retained-win32-handle'
                    and type(result['returncode']) is int and result['exit_code_known'] is True),'identity-unknown')
        return result

    def stage(self,source,envelope,keys):
        from ctflab_runtime_inventory import check_path
        payload,sha=release_manifest(envelope,keys)
        source=Path(source).absolute()
        with self.locked() as db:
            require(db.execute('SELECT 1 FROM versions WHERE id=?',(payload['version'],)).fetchone() is None,'state-conflict')
            # 输入目录可以有未选择的材料；严格闭包仅适用于新暂存/版本目录。
            initial=dict(payload,schema=1);self.check(source,initial)
            required=sum(check_path(source/name).st_size for name in payload['files'])
            require(shutil.disk_usage(self.root).free>=required+32*1024**2,'storage-insufficient')
            attempt=self.root/'staging'/str(uuid.uuid4());private_directory(attempt)
            for name in payload['files']:
                target=attempt/name
                for parent in reversed(target.parents):
                    if parent!=attempt and attempt in parent.parents and not parent.exists():private_directory(parent)
                fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as output,(source/name).open('rb') as original:
                    shutil.copyfileobj(original,output);output.flush();os.fsync(output.fileno())
            if payload['schema']==2:
                fd=os.open(attempt/SIGNED_MANIFEST,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'w') as stream:
                    stream.write(canonical(dict(envelope,payload=payload)));stream.flush();os.fsync(stream.fileno())
                if payload['launch']['platform']=='linux-x64':
                    for name in payload['launch']['executables']:os.chmod(attempt/name,0o700)
            self.check(attempt,payload)
            destination=self.root/'versions'/payload['version']
            require(not destination.exists(),'state-conflict');attempt.rename(destination)
            db.execute('INSERT INTO versions VALUES(?,?,?,?)',(payload['version'],sha,str(destination),canonical(payload)))
        return {'state':'staged','version':payload['version'],'signature_verified':True,'activated':False}

    def activate(self,version):
        with self.application_gate(),self.locked() as db:
            self.switch_guard(db)
            row=db.execute('SELECT path,payload FROM versions WHERE id=?',(version,)).fetchone()
            require(row is not None,'state-conflict');self.check(Path(row[0]),json.loads(row[1]))
            old=db.execute('SELECT active FROM pointers WHERE id=1').fetchone()[0]
            if old!=version:db.execute('UPDATE pointers SET active=?,previous=? WHERE id=1',(version,old))
        return {'state':'active','version':version,'previous':old,'data_migrated':False}

    def rollback(self):
        with self.application_gate(),self.locked() as db:
            self.switch_guard(db)
            active,previous=db.execute('SELECT active,previous FROM pointers WHERE id=1').fetchone()
            require(previous is not None,'state-conflict')
            row=db.execute('SELECT path,payload FROM versions WHERE id=?',(previous,)).fetchone()
            require(row is not None,'state-conflict');self.check(Path(row[0]),json.loads(row[1]))
            db.execute('UPDATE pointers SET active=?,previous=? WHERE id=1',(previous,active))
        return {'state':'active','version':previous,'data_migrated':False}

    def switch_guard(self,db):
        self.check_launches()
        # 旧版本库未初始化协调表时不假装已核验；不自动迁移旧SQLite。
        require(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspaces'").fetchone()
                is not None,'version-mismatch')
        require(not db.execute('SELECT 1 FROM workspaces').fetchone(),'resource-busy')
        from ctflab_release_update import check_journal
        check_journal(self,db)

    def pin(self,owner,version):
        from ctflab_contract import identifier
        identifier(owner)
        with self.locked() as db:
            require(db.execute('SELECT 1 FROM versions WHERE id=?',(version,)).fetchone() is not None,'state-conflict')
            db.execute('INSERT OR IGNORE INTO refs VALUES(?,?)',(owner,version))

    def status(self):
        with self.locked() as db:
            active,previous=db.execute('SELECT active,previous FROM pointers WHERE id=1').fetchone()
            return {'active':active,'previous':previous,'versions':[r[0] for r in db.execute('SELECT id FROM versions ORDER BY id')],
                    'references':[{'owner':r[0],'version':r[1]} for r in db.execute('SELECT owner,version FROM refs')],
                    'automatic_cleanup':False,'data_migrated':False}
