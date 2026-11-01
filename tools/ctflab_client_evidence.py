"""明确下载已封存实例证据；私有本机分块/暂停/续传，不自动打开、解包或执行。"""
import base64
from contextlib import contextmanager
import sqlite3
import hashlib
import json
import os
from pathlib import Path
import shutil
from ctflab_contract import canonical,require,uuid_text
from ctflab_generation_store import private_directory,digest
from ctflab_runtime_inventory import check_path
from ctflab_remote import SSHSession,private_json
from ctflab_remote_evidence import filename,CHUNK


class ClientEvidence:
    def __init__(self,store,*,session_factory=SSHSession):self.store=store;self.session_factory=session_factory
    @contextmanager
    def locked(self,identity):
        # 单下载独占门；不占实例变更/租约门，取消也能独立到达。
        path=self.store.root/('evidence-'+uuid_text(identity)+'.lock')
        if not path.exists():
            require(len(list(self.store.root.glob('evidence-*.lock')))<4096,'storage-insufficient')
            try:
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
            except FileExistsError:pass
        from ctflab_tls_endpoint import guard
        guard(path);require(path.stat().st_nlink==1,'identity-unknown')
        if os.name=='nt':
            from ctflab_windows_native import state_lock
            with state_lock(path):yield
        else:
            import fcntl
            with path.open('rb') as stream:
                fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB);yield

    def table(self,db):
        db.execute('CREATE TABLE IF NOT EXISTS evidence_downloads(id TEXT PRIMARY KEY,target TEXT,payload TEXT,sha TEXT,received INTEGER,phase TEXT,cancel INTEGER)')
        require([r[1] for r in db.execute('PRAGMA table_info(evidence_downloads)')]==['id','target','payload','sha','received','phase','cancel'],'version-mismatch')
    def record(self,identity):
        uuid_text(identity)
        with self.store.db() as db:row=db.execute('SELECT id,target,payload,sha,received,phase,cancel FROM evidence_downloads WHERE id=?',(identity,)).fetchone()
        require(row is not None,'state-conflict');payload=json.loads(row[2])
        require(hashlib.sha256(canonical(payload).encode()).hexdigest()==row[3],'identity-unknown')
        return row,payload
    def summary(self,row):
        uuid_text(row[0]);uuid_text(row[1]);payload=json.loads(row[2]);filename(payload['file'])
        value={'download_id':row[0],'target_id':row[1],'instance_uuid':payload['instance_uuid'],'file':payload['file'],
            'sha256':payload['sha256'],'size':payload['size'],'received':row[4],'phase':row[5],
            'automatic_replay':False,'content_executed':False,'local_integrity_current_verified':False}
        if row[5]=='verified':value['local_path']=str(self.store.root/'evidence-downloads'/row[0]/(payload['file']+'.partial'))
        return value
    def history(self,target):
        self.store.entry(target)
        with self.store.db() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='evidence_downloads'").fetchone():return {'downloads':[]}
            rows=db.execute('SELECT id,target,payload,sha,received,phase,cancel FROM evidence_downloads WHERE target=? ORDER BY rowid DESC LIMIT 101',(target,)).fetchall()
        return {'downloads':[self.summary(row) for row in rows[:100]],'truncated':len(rows)>100,'automatic_transfer':False}
    def listing(self,target,instance):
        entry=self.store.entry(target);uuid_text(instance)
        with self.session_factory(private_json(entry[0])) as session:
            require(session.request('handshake',{}).get('evidence_download') is True,'capability-unverified')
            result=session.request('evidence-list',{'instance_uuid':instance})
        require(type(result) is dict and result.get('instance_uuid')==instance and type(result.get('exports')) is list
            and len(result['exports'])<=128 and self.store.entry(target)[1]==entry[1],'identity-unknown')
        for row in result['exports']:
            uuid_text(row['export_id']);require(type(row['generation']) is int and row['generation']>0 and type(row['files']) is list and len(row['files'])<=34)
            for item in row['files']:
                filename(item['name']);require(type(item['size']) is int and 0<=item['size']<=1024**3
                    and type(item['sha256']) is str and len(item['sha256'])==64 and all(c in '0123456789abcdef' for c in item['sha256']))
        return result
    def cancel(self,identity):
        self.record(identity)
        with self.store.db(write=True) as db:db.execute("UPDATE evidence_downloads SET cancel=1 WHERE id=? AND phase!='verified'",(identity,))
        return self.summary(self.record(identity)[0])
    def run(self,target,identity,payload,*,resume=False,max_chunks=8192):
        uuid_text(identity);uuid_text(target);require(type(payload) is dict and set(payload)=={'instance_uuid','export_id','file','sha256','size'})
        uuid_text(payload['instance_uuid']);uuid_text(payload['export_id']);filename(payload['file'])
        require(type(payload['size']) is int and 0<=payload['size']<=1024**3 and type(payload['sha256']) is str
                and len(payload['sha256'])==64 and all(c in '0123456789abcdef' for c in payload['sha256']))
        require(type(max_chunks) is int and 1<=max_chunks<=8192)
        entry=self.store.entry(target);bound=dict(payload,target_sha256=entry[1]);encoded=canonical(bound);sha=hashlib.sha256(encoded.encode()).hexdigest()
        with self.locked(identity):
            with self.store.db(write=True) as db:
                self.table(db);row=db.execute('SELECT target,sha,phase FROM evidence_downloads WHERE id=?',(identity,)).fetchone()
                if row:
                    require(row[:2]==(target,sha),'idempotency-conflict')
                    if row[2]=='verified':return self.summary(self.record(identity)[0])
                    require(resume,'state-conflict');db.execute("UPDATE evidence_downloads SET cancel=0,phase='receiving' WHERE id=?",(identity,))
                else:
                    require(not resume and db.execute('SELECT COUNT(*) FROM evidence_downloads').fetchone()[0]<4096,'storage-insufficient')
                    db.execute('INSERT INTO evidence_downloads VALUES(?,?,?,?,0,?,0)',(identity,target,encoded,sha,'receiving'))
            parent=self.store.root/'evidence-downloads'
            if not parent.exists():private_directory(parent)
            folder=parent/identity
            if not folder.exists():private_directory(folder)
            path=folder/(payload['file']+'.partial')
            if not path.exists():
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
            info=check_path(path);require(path.is_file() and info.st_nlink==1 and info.st_size<=payload['size'],'identity-unknown')
            require(shutil.disk_usage(folder).free>=max(0,payload['size']-info.st_size)+32*1024**2,'storage-insufficient')
            phase='unknown';current=0
            def cancelled():return self.record(identity)[0][6]==1
            try:
                with self.session_factory(private_json(entry[0]),cancel_requested=cancelled) as session,path.open('r+b') as output:
                    require(session.request('handshake',{}).get('evidence_download') is True,'capability-unverified')
                    original=os.fstat(output.fileno())
                    require((original.st_dev,original.st_ino)==(info.st_dev,info.st_ino),'identity-unknown')
                    for _ in range(max_chunks):
                        require(not cancelled(),'operation-finished')
                        value=session.request('evidence-read',{'instance_uuid':payload['instance_uuid'],'export_id':payload['export_id'],
                            'file':payload['file'],'sha256':payload['sha256'],'offset':current})
                        require(type(value) is dict and all(value.get(k)==payload[k] for k in ('instance_uuid','export_id','file','sha256','size'))
                            and type(value.get('offset')) is int and value['offset']==current and type(value.get('data')) is str
                            and len(value['data'])<=4*((CHUNK+2)//3) and type(value.get('eof')) is bool,'identity-unknown')
                        block=base64.b64decode(value['data'],validate=True)
                        require(len(block)<=CHUNK and current+len(block)<=payload['size'] and (bool(block) or value['eof'])
                            and value['eof']==(current+len(block)==payload['size']),'identity-unknown')
                        # 中断写入尚未记入DB的尾部也保留；从原件重新逐块比对后才追加，不截断。
                        output.seek(current);existing=output.read(len(block));require(block.startswith(existing),'identity-unknown')
                        if len(existing)<len(block):output.write(block[len(existing):])
                        output.flush();os.fsync(output.fileno());current+=len(block)
                        final=os.fstat(output.fileno());live=check_path(path)
                        require(final.st_nlink==1 and (final.st_dev,final.st_ino)==(info.st_dev,info.st_ino)==(live.st_dev,live.st_ino),'identity-unknown')
                        with self.store.db(write=True) as db:db.execute('UPDATE evidence_downloads SET received=? WHERE id=?',(current,identity))
                        if value['eof']:
                            require(final.st_size==payload['size'] and digest(path)==payload['sha256'],'identity-unknown');phase='verified';break
                    else:phase='paused'
                require(self.store.entry(target)[1]==entry[1],'identity-unknown')
            except (OSError,ValueError,RuntimeError,TypeError,KeyError,sqlite3.Error):phase='paused' if cancelled() else 'unknown'
            with self.store.db(write=True) as db:db.execute('UPDATE evidence_downloads SET phase=? WHERE id=?',(phase,identity))
        return self.summary(self.record(identity)[0])
    def resume(self,identity):
        row,payload=self.record(identity);payload.pop('target_sha256');return self.run(row[1],identity,payload,resume=True)
    def handle(self,value):
        action=value['action']
        if action=='evidence-list':
            require(set(value)=={'action','id','instance_uuid'});return self.listing(value['id'],value['instance_uuid'])
        if action=='evidence-history':require(set(value)=={'action','id'});return self.history(value['id'])
        if action in ('evidence-resume','evidence-cancel'):
            require(set(value)=={'action','download_id'});return self.resume(value['download_id']) if action=='evidence-resume' else self.cancel(value['download_id'])
        require(action=='evidence-download' and set(value)=={'action','id','download_id','payload'})
        return self.run(value['id'],value['download_id'],value['payload'])
