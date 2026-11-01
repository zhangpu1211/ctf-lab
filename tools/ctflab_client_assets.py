"""已保存目标的资产传输账本：明确上传/续传/暂停，不导入或启动实例。"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from ctflab_contract import canonical,require,uuid_text,ContractError
from ctflab_content_cache import source_url,checksum
from ctflab_runtime_inventory import check_path,signature
from ctflab_remote_assets import upload_file
from ctflab_remote import private_json

SCHEMA='CREATE TABLE transfers(id TEXT PRIMARY KEY,target TEXT,payload TEXT,digest TEXT,sha TEXT,size INTEGER,received INTEGER,phase TEXT,cancel INTEGER,tries INTEGER)'


class ClientAssets:
    def __init__(self,store,*,session_factory=None):self.store=store;self.session_factory=session_factory
    def exists(self,db):return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='transfers'").fetchone() is not None
    def record(self,identity):
        with self.store.db() as db:
            row=db.execute('SELECT id,target,payload,digest,sha,size,received,phase,cancel,tries FROM transfers WHERE id=?',(uuid_text(identity),)).fetchone()
        require(row is not None,'state-conflict')
        payload=json.loads(row[2]);require(hashlib.sha256(canonical(payload).encode()).hexdigest()==row[3],'identity-unknown')
        return row,payload
    @staticmethod
    def summary(row):
        uuid_text(row[0]);uuid_text(row[1])
        if row[4] is not None:checksum(row[4])
        require(type(row[5]) is int and 0<row[5]<=1024**4 and type(row[6]) is int and 0<=row[6]<=row[5]
                and row[7] in ('hashing','uploading','verified','paused','unknown') and row[8] in (0,1)
                and type(row[9]) is int and row[9]>=1,'identity-unknown')
        return {'upload_id':row[0],'target_id':row[1],'sha256':row[4],'size':row[5],'received':row[6],
            'phase':row[7],'cancel_requested':bool(row[8]),'tries':row[9],
            'automatic_replay':False,'instance_created':False,'runtime_verified':False,'server_current_verified':False}
    def history(self,identity):
        uuid_text(identity)
        if not self.store.root.exists():return {'uploads':[],'automatic_replay':False}
        with self.store.db() as db:
            require(db.execute('SELECT 1 FROM targets WHERE id=?',(identity,)).fetchone(),'permission-denied')
            if not self.exists(db):return {'uploads':[],'automatic_replay':False}
            rows=db.execute('SELECT id,target,payload,digest,sha,size,received,phase,cancel,tries FROM transfers WHERE target=? ORDER BY rowid DESC LIMIT 101',(identity,)).fetchall()
        return {'uploads':[self.summary(row) for row in rows[:100]],'truncated':len(rows)>100,'automatic_replay':False}
    def cancel(self,identity):
        row,_=self.record(identity)
        with self.store.db(write=True) as db:
            if row[7]!='verified':db.execute('UPDATE transfers SET cancel=1 WHERE id=?',(identity,))
        current,_=self.record(identity);return self.summary(current)
    def run(self,target_id,identity,path,source,audience,*,resume=False):
        uuid_text(identity);uuid_text(target_id);source_url(source);require(audience in ('student','teacher'))
        entry=self.store.entry(target_id);path=Path(path).absolute();info=check_path(path)
        require(path.is_file() and info.st_nlink==1 and 0<info.st_size<=1024**4)
        payload={'target':entry[1],'file':str(path),'source':source,'audience':audience,
                 'file_signature':list(signature(info))}
        encoded=canonical(payload);sha=hashlib.sha256(encoded.encode()).hexdigest()
        with self.store.db(gate=True):
            with self.store.db(write=True) as db:
                if not self.exists(db):db.execute(SCHEMA)
                columns=[r[1] for r in db.execute('PRAGMA table_info(transfers)')]
                require(columns==['id','target','payload','digest','sha','size','received','phase','cancel','tries'],'version-mismatch')
                old=db.execute('SELECT target,digest,phase FROM transfers WHERE id=?',(identity,)).fetchone()
                if old:
                    require(old[:2]==(target_id,sha),'idempotency-conflict')
                    if old[2]=='verified':return self.summary(self.record(identity)[0])
                    require(resume,'state-conflict')
                    db.execute("UPDATE transfers SET phase='hashing',cancel=0,tries=tries+1 WHERE id=?",(identity,))
                else:
                    require(not resume,'state-conflict');require(db.execute('SELECT COUNT(*) FROM transfers').fetchone()[0]<4096,'storage-insufficient')
                    db.execute('INSERT INTO transfers VALUES(?,?,?,?,NULL,?,0,?,0,1)',(identity,target_id,encoded,sha,info.st_size,'hashing'))
            def cancelled():return self.record(identity)[0][8]==1
            def hashed(file,expected):
                value=hashlib.sha256();count=0
                with file.open('rb') as stream:
                    require(signature(os.fstat(stream.fileno()))==signature(expected),'identity-unknown')
                    while block:=stream.read(1024**2):
                        require(not cancelled(),'operation-finished');count+=len(block);require(count<=expected.st_size,'state-conflict');value.update(block)
                    require(count==expected.st_size and signature(os.fstat(stream.fileno()))==signature(expected),'state-conflict')
                require(signature(check_path(file))==signature(expected),'identity-unknown')
                result=value.hexdigest();old_sha=self.record(identity)[0][4]
                require(old_sha is None or old_sha==result,'identity-unknown')
                with self.store.db(write=True) as db:db.execute("UPDATE transfers SET sha=?,phase='uploading' WHERE id=?",(result,identity))
                return result
            def progress(value):
                require(value['upload_id']==identity and type(value['received']) is int and 0<=value['received']<=info.st_size,'identity-unknown')
                with self.store.db(write=True) as db:db.execute('UPDATE transfers SET received=? WHERE id=?',(value['received'],identity))
            try:
                upload_file(private_json(entry[0]),path,source,audience,identity,session_factory=self.session_factory,
                    hash_file_func=hashed,cancel_requested=cancelled,on_progress=progress)
                require(self.store.entry(target_id)[1]==entry[1],'identity-unknown');phase='verified'
            except (OSError,ValueError,RuntimeError,TypeError,KeyError,sqlite3.Error):phase='paused' if cancelled() else 'unknown'
            with self.store.db(write=True) as db:db.execute('UPDATE transfers SET phase=? WHERE id=?',(phase,identity))
        return self.summary(self.record(identity)[0])
    def resume(self,identity):
        row,payload=self.record(identity)
        return self.run(row[1],identity,payload['file'],payload['source'],payload['audience'],resume=True)
    def probe(self,identity):
        from ctflab_remote import SSHSession
        row,payload=self.record(identity);require(row[4] is not None,'state-conflict');entry=self.store.entry(row[1])
        require(entry[1]==payload['target'],'identity-unknown')
        factory=self.session_factory or SSHSession
        with factory(private_json(entry[0])) as session:
            result=session.request('asset-status',{'upload_id':identity})
        require(type(result) is dict and result['upload_id']==identity and result['sha256']==row[4]
                and type(result['size']) is int and result['size']==row[5]
                and type(result['received']) is int and 0<=result['received']<=row[5]
                and result['state'] in ('uploading','verified','corrupt')
                and (result['state']!='verified' or result['received']==row[5]),'identity-unknown')
        require(self.store.entry(row[1])[1]==entry[1],'identity-unknown')
        return dict(self.summary(row),server_state=result['state'] if result['state'] in ('uploading','verified','corrupt') else 'unknown',
                    server_current_verified=result['state']=='verified')
    def handle(self,value):
        action=value.get('action')
        if action=='asset-history':require(set(value)=={'action','id'});return self.history(value['id'])
        if action=='asset-cancel':require(set(value)=={'action','upload_id'});return self.cancel(value['upload_id'])
        if action=='asset-resume':require(set(value)=={'action','upload_id'});return self.resume(value['upload_id'])
        if action=='asset-probe':require(set(value)=={'action','upload_id'});return self.probe(value['upload_id'])
        require(action=='asset-upload' and set(value)=={'action','id','upload_id','file','source','audience'})
        return self.run(value['id'],value['upload_id'],value['file'],value['source'],value['audience'])
