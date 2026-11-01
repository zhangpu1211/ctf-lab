"""本机私有远程目标和请求账本；先持久意图、显式重试，不自动恢复发送。"""
import argparse
from contextlib import contextmanager,closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text,ContractError,public_error,MAX_MESSAGE_BYTES,STATES,identifier
from ctflab_generation_store import private_directory,digest
from ctflab_tls_endpoint import guard
from ctflab_local_service import _guard_path
from ctflab_remote import decode,SSHSession
from ctflab_desktop_remote import target,dispatch as remote,request_parameters


def mutation(payload):
    action,_,_=request_parameters(payload)
    return action in ('lease-acquire','lease-renew','lease-release','course-provision','audit-settle') or action=='submit' and payload['request']['operation']!='status'


def public_response(value):
    require(type(value) is dict)
    result=value.get('result');out={}
    if 'target' in value:out['target']=value['target']
    if type(result) is dict:
        allowed={'protocol','version','request_id','instance_uuid','operation_id','generation','state_revision','state','cursor',
            'result','cancelled','lease_id','principal','time_state','expires_at','resources','expiry_action',
            'stop_operation_id','disk_reservation_hard_enforced','storage_reference_retained','graceful_stop_verified',
            'automatic_replay','renewal_id','already_recorded'}
        allowed|={'mapping_sha256','instance_created','already_configured','automatic_start','runtime_verified','original_assets_modified',
                  'attempt_id','already_settled','original_worker_result','contract_observed','vm_observed','guest_effect_verified'}
        clean={key:v for key,v in result.items() if key in allowed}
        uuids={'request_id','instance_uuid','operation_id','lease_id','stop_operation_id','renewal_id','attempt_id'}
        numbers={'version','generation','state_revision','cursor'}
        flags={'cancelled','disk_reservation_hard_enforced','storage_reference_retained','graceful_stop_verified','automatic_replay','already_recorded'}
        flags|={'instance_created','already_configured','automatic_start','runtime_verified','original_assets_modified','already_settled','contract_observed','vm_observed','guest_effect_verified'}
        states=set(STATES)|{'active','expired','clock-uncertain','released','reserved','attention','stop-intent','stop-submitted','course-instance-configured','audit-pending-resolved-by-observation'}
        for key,item in clean.items():
            if key=='mapping_sha256':require(type(item) is str and len(item)==64 and all(c in '0123456789abcdef' for c in item))
            if key=='original_worker_result':require(item=='unknown')
            if key in uuids:
                if item is not None:uuid_text(item)
            elif key in numbers:require(item is None or type(item) is int and 0<=item<=2**53-1)
            elif key in flags:require(type(item) is bool)
            elif key=='state':require(type(item) is str and item in states)
            elif key=='result':require(item in ('accepted','completed','failed','unknown'))
            elif key=='time_state':require(item in ('active','expired','clock-uncertain'))
            elif key=='expiry_action':require(item in ('notify','request-stop'))
            elif key=='protocol':require(item=='ctflab-local')
            elif key=='principal':identifier(item)
            elif key=='expires_at':
                from datetime import datetime
                require(type(item) is str and len(item)<=40 and datetime.fromisoformat(item.replace('Z','+00:00')).tzinfo is not None)
            elif key=='resources':
                require(type(item) is dict and set(item)=={'cpus','memory_mb','disk_reservation_bytes'} and all(type(v) is int and 0<=v<=2**63-1 for v in item.values()))
        out['result']=clean
        error=result.get('error')
        if type(error) is dict:out['result']['error']=public_error(error.get('code'))
    if type(value.get('error')) is dict:out['error']=public_error(value['error'].get('code'))
    return out


class ClientStore:
    def __init__(self,root,*,send=remote,connect_send=remote,display_spawn=None):
        self.root=Path(root).absolute();self.send=send;self.connect_send=connect_send;self.display_spawn=display_spawn

    def initialize(self):
        if self.root.exists():
            with self.db() as db:require(db.execute('SELECT schema FROM metadata').fetchall()==[(1,)],'version-mismatch')
            return
        _guard_path(self.root)
        missing=[];parent=self.root.parent
        while not parent.exists():missing.append(parent);parent=parent.parent
        for path in reversed(missing):private_directory(path)
        private_directory(self.root);private_directory(self.root/'configs')
        for name,sql in (('client.sqlite3','CREATE TABLE metadata(schema INTEGER);INSERT INTO metadata VALUES(1);'
            'CREATE TABLE targets(id TEXT PRIMARY KEY,label TEXT,config TEXT,fingerprint TEXT,server TEXT);'
            'CREATE TABLE attempts(id TEXT PRIMARY KEY,target TEXT,payload TEXT,digest TEXT,phase TEXT,tries INTEGER,response TEXT);'),
            ('gate.sqlite3','CREATE TABLE gate(id INTEGER);')):
            fd=os.open(self.root/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
            with closing(sqlite3.connect(self.root/name)) as db:db.executescript(sql);db.commit()

    @contextmanager
    def db(self,*,write=False,gate=False):
        guard(self.root);path=guard(self.root/('gate.sqlite3' if gate else 'client.sqlite3'))
        db=sqlite3.connect(path.as_uri()+('?mode=rw' if write or gate else '?mode=ro'),uri=True,timeout=0,isolation_level=None)
        try:
            if write or gate:db.execute('PRAGMA synchronous=FULL')
            else:db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN IMMEDIATE' if write or gate else 'BEGIN');yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    def targets(self):
        if not self.root.exists():return {'targets':[],'automatic_connect':False}
        with self.db() as db:
            require(db.execute('SELECT schema FROM metadata').fetchall()==[(1,)],'version-mismatch')
            rows=db.execute('SELECT id,label,fingerprint,server FROM targets ORDER BY rowid DESC LIMIT 201').fetchall()
        require(len(rows)<=200,'identity-unknown')
        return {'targets':[{'id':r[0],'label':r[1],'target':r[2],'server_uuid':r[3]} for r in rows],'automatic_connect':False}

    def save(self,identity,label,config):
        uuid_text(identity);require(type(label) is str and 1<=len(label)<=96 and all(ord(c)>=32 for c in label))
        path=Path(config);require(path.is_absolute());definition,fingerprint=target(path)
        self.initialize()
        row=(identity,label,str(path),fingerprint,definition['server_uuid'])
        with self.db(write=True) as db:
            old=db.execute('SELECT id,label,config,fingerprint,server FROM targets WHERE id=?',(identity,)).fetchone()
            if old:require(old==row,'idempotency-conflict')
            else:
                require(db.execute('SELECT COUNT(*) FROM targets').fetchone()[0]<200,'storage-insufficient')
                db.execute('INSERT INTO targets VALUES(?,?,?,?,?)',row)
        return {'state':'saved','id':identity,'target':fingerprint,'server_uuid':definition['server_uuid'],'connected':False}

    def create(self,identity,label,definition):
        uuid_text(identity)
        require(type(definition) is dict and set(definition)=={'host','port','user','ssh','identity','known_hosts','server_uuid'})
        from ctflab_runtime_inventory import check_path,hash_file
        known=Path(definition['known_hosts']).absolute();info=check_path(known)
        require(known.is_file() and info.st_nlink==1 and info.st_size<=16*1024**2)
        expected=hash_file(known,info);raw=known.read_bytes()
        require(hashlib.sha256(raw).hexdigest()==expected and hash_file(known,info)==expected,'identity-unknown')
        self.initialize();private_known=self.root/'configs'/(identity+'.known_hosts')
        if private_known.exists():require(digest(guard(private_known))==expected,'idempotency-conflict')
        else:
            fd=os.open(private_known,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as output:output.write(raw);output.flush();os.fsync(output.fileno())
        config=dict(definition,schema=1,known_hosts=str(private_known),known_hosts_sha256=expected)
        from ctflab_remote import ssh_arguments
        ssh_arguments(config);self.initialize()
        path=self.root/'configs'/(identity+'.json')
        if path.exists():
            from ctflab_remote import private_json
            require(private_json(path)==config,'idempotency-conflict')
        else:
            from ctflab_windows_recovery import record
            record(path,config)
        return self.save(identity,label,str(path))

    def entry(self,identity):
        uuid_text(identity)
        with self.db() as db:row=db.execute('SELECT config,fingerprint FROM targets WHERE id=?',(identity,)).fetchone()
        require(row is not None,'permission-denied')
        require(target(row[0])[1]==row[1],'identity-unknown');return row

    def pending(self,identity):
        uuid_text(identity)
        with self.db() as db:
            require(db.execute('SELECT 1 FROM targets WHERE id=?',(identity,)).fetchone(),'permission-denied')
            fingerprint=db.execute('SELECT fingerprint FROM targets WHERE id=?',(identity,)).fetchone()[0]
            rows=db.execute("SELECT id,payload,phase,tries,digest FROM attempts WHERE target=? AND phase!='returned' ORDER BY rowid DESC LIMIT 101",(identity,)).fetchall()
        result=[]
        for row in rows[:100]:
            uuid_text(row[0]);payload=json.loads(row[1]);require(mutation(payload) and payload['target']==fingerprint,'identity-unknown')
            require(hashlib.sha256(canonical(payload).encode()).hexdigest()==row[4] and row[2] in ('unknown','attempting') and type(row[3]) is int and row[3]>=1,'identity-unknown')
            result.append({'id':row[0],'payload':payload,'phase':row[2],'tries':row[3]})
        return {'attempts':result,'truncated':len(rows)>100,'automatic_replay':False}

    def request(self,identity,payload,attempt=None,*,retry=False):
        require(len(canonical(payload).encode())<=MAX_MESSAGE_BYTES)
        mutating=mutation(payload);entry=self.entry(identity)
        if payload['action']!='connect':require(payload['target']==entry[1],'identity-unknown')
        if not mutating:
            require(attempt is None and not retry)
            return self.send(entry[0],payload)
        uuid_text(attempt)
        encoded=canonical(payload);sha=hashlib.sha256(encoded.encode()).hexdigest()
        # 独立门跨越传输，进程退出释放；不会因重开页面自动发送attempting记录。
        with self.db(gate=True):
            with self.db(write=True) as db:
                old=db.execute('SELECT target,digest,phase,response FROM attempts WHERE id=?',(attempt,)).fetchone()
                if old:
                    require(old[:2]==(identity,sha),'idempotency-conflict')
                    if old[2]=='returned':return dict(json.loads(old[3]),client_attempt_id=attempt,client_phase='returned')
                    require(retry,'state-conflict')
                    db.execute("UPDATE attempts SET phase='attempting',tries=tries+1 WHERE id=?",(attempt,))
                else:
                    require(not retry,'state-conflict')
                    require(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]<10000,'storage-insufficient')
                    db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,1,NULL)',(attempt,identity,encoded,sha,'attempting'))
            try:
                response=public_response(self.send(entry[0],payload))
                require(target(entry[0])[1]==entry[1],'identity-unknown')
                phase='unknown' if 'error' in response else 'returned'
            except (OSError,ValueError,RuntimeError,TypeError,KeyError,sqlite3.Error):
                response={'target':entry[1],'error':public_error('control-unreachable'),'automatic_replay':False};phase='unknown'
            with self.db(write=True) as db:
                db.execute('UPDATE attempts SET phase=?,response=? WHERE id=?',(phase,canonical(response),attempt))
            return dict(response,client_attempt_id=attempt,client_phase=phase)

    def retry(self,attempt):
        uuid_text(attempt)
        with self.db() as db:row=db.execute('SELECT target,payload,digest FROM attempts WHERE id=?',(attempt,)).fetchone()
        require(row is not None,'state-conflict');payload=json.loads(row[1])
        require(hashlib.sha256(canonical(payload).encode()).hexdigest()==row[2],'identity-unknown')
        return self.request(row[0],payload,attempt,retry=True)

    def connection_table(self,db):
        db.execute('CREATE TABLE IF NOT EXISTS connections(id TEXT PRIMARY KEY,target TEXT,phase TEXT,cancel INTEGER)')
        require([r[1] for r in db.execute('PRAGMA table_info(connections)')]==['id','target','phase','cancel'],'version-mismatch')

    def preview_key(self,config):
        require(type(config) is str and len(config)<=4096 and Path(config).is_absolute() and '\x00' not in config)
        # 仅绑定规范化路径摘要；取消不读取已变更/移走的配置或保存凭据位置。
        return 'preview:'+hashlib.sha256(os.path.normcase(os.path.abspath(config)).encode()).hexdigest()

    def connection_record(self,target_id,identity,*,cancel=False,preview=False):
        uuid_text(identity)
        if preview:require(type(target_id) is str and target_id.startswith('preview:') and len(target_id)==72)
        else:uuid_text(target_id)
        with self.db(write=True) as db:
            if not preview:require(db.execute('SELECT 1 FROM targets WHERE id=?',(target_id,)).fetchone(),'permission-denied')
            self.connection_table(db)
            row=db.execute('SELECT target,phase,cancel FROM connections WHERE id=?',(identity,)).fetchone()
            if row is None:
                require(db.execute('SELECT COUNT(*) FROM connections').fetchone()[0]<4096,'storage-insufficient')
                phase='cancelled' if cancel else 'connecting'
                db.execute('INSERT INTO connections VALUES(?,?,?,?)',(identity,target_id,phase,int(cancel)))
            else:
                require(row[0]==target_id,'idempotency-conflict')
                require(row[1] in ('connecting','cancelled','returned','unknown') and row[2] in (0,1),'identity-unknown')
                require(cancel or row[1]=='cancelled','state-conflict')
                phase=row[1]
                if cancel and phase in ('connecting','unknown'):
                    phase='cancelled';db.execute("UPDATE connections SET phase='cancelled',cancel=1 WHERE id=?",(identity,))
        return {'client_connection_id':identity,'connection_phase':phase,'automatic_replay':False}

    def connect(self,target_id,identity):
        entry=self.entry(target_id)
        return self.connect_entry(target_id,identity,entry,lambda:self.entry(target_id)[1])

    def preview_connect(self,config,identity):
        key=self.preview_key(config);self.initialize()
        fingerprint=target(config)[1]
        return self.connect_entry(key,identity,(config,fingerprint),lambda:target(config)[1],preview=True)

    def connect_entry(self,target_id,identity,entry,current_target,*,preview=False):
        initial=self.connection_record(target_id,identity,preview=preview)
        if initial['connection_phase']=='cancelled':return dict(initial,connection_cancelled=True)
        def cancelled():
            with self.db() as db:row=db.execute('SELECT target,cancel FROM connections WHERE id=?',(identity,)).fetchone()
            require(row is not None and row[0]==target_id,'identity-unknown')
            return row[1]==1
        try:
            response=self.connect_send(entry[0],{'action':'connect'},cancel_requested=cancelled)
            require(current_target()==entry[1],'identity-unknown')
            require(type(response) is dict)
            phase='unknown' if response.get('error') else 'returned'
        except (OSError,ValueError,RuntimeError,TypeError,KeyError,sqlite3.Error):
            response={'error':public_error('control-unreachable'),'automatic_replay':False};phase='unknown'
        with self.db(write=True) as db:
            row=db.execute('SELECT cancel FROM connections WHERE id=?',(identity,)).fetchone()
            require(row is not None,'identity-unknown')
            if row[0]:phase='cancelled';response={'connection_cancelled':True,'automatic_replay':False}
            db.execute('UPDATE connections SET phase=? WHERE id=?',(phase,identity))
        return dict(response,client_connection_id=identity,connection_phase=phase)

    def display(self,identity,instance,node,lease):
        uuid_text(instance);identifier(node);uuid_text(lease);entry=self.entry(identity)
        if self.display_spawn is None:
            import subprocess
            from ctflab_bounded_log import spawn
            logs=self.root/('display-'+str(uuid.uuid4()));private_directory(logs);receiver=spawn(logs,'remote-display')
            args=[sys.executable,'-I','-B',str(Path(__file__).resolve().with_name('ctflab_remote_display.py')),
                  '--config',entry[0],'--target',entry[1],'--instance',instance,'--node',node,'--lease',lease]
            flags={'creationflags':subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}
            try:subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=receiver.stdin,stderr=receiver.stdin,close_fds=True,**flags)
            finally:receiver.stdin.close()
        else:self.display_spawn(entry,instance,node,lease)
        return {'state':'display-window-requested','instance_uuid':instance,'node':node,
                'remote_connection_verified':False,'vm_stopped':False,'automatic_replay':False}

    def handle(self,value):
        require(type(value) is dict and type(value.get('action')) is str)
        action=value['action']
        if action=='display':
            require(set(value)=={'action','id','instance_uuid','node','lease_id'})
            return self.display(value['id'],value['instance_uuid'],value['node'],value['lease_id'])
        if action.startswith('evidence-'):
            from ctflab_client_evidence import ClientEvidence
            return ClientEvidence(self).handle(value)
        if action.startswith('asset-'):
            from ctflab_client_assets import ClientAssets
            return ClientAssets(self).handle(value)
        if action=='targets':require(set(value)=={'action'});return self.targets()
        if action in ('save-target','create-target'):
            require(set(value)=={'action','id','label','config'})
            return (self.save if action=='save-target' else self.create)(value['id'],value['label'],value['config'])
        if action=='pending':require(set(value)=={'action','id'});return self.pending(value['id'])
        if action in ('preview-connect','cancel-preview-connect'):
            require(set(value)=={'action','config','connection_id'})
            key=self.preview_key(value['config']);uuid_text(value['connection_id'])
            if action=='preview-connect':return self.preview_connect(value['config'],value['connection_id'])
            self.initialize()
            return self.connection_record(key,value['connection_id'],cancel=True,preview=True)
        if action in ('connect','cancel-connect'):

            require(set(value)=={'action','id','connection_id'})
            return self.connect(value['id'],value['connection_id']) if action=='connect' else self.connection_record(value['id'],value['connection_id'],cancel=True)
        if action=='retry':require(set(value)=={'action','attempt_id'});return self.retry(value['attempt_id'])
        require(action=='request' and set(value) in ({'action','id','payload'},{'action','id','payload','attempt_id'}))
        return self.request(value['id'],value['payload'],value.get('attempt_id'))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',required=True,type=Path);args=parser.parse_args(argv)
    try:
        result=ClientStore(args.root).handle(decode(sys.stdin.buffer.read(MAX_MESSAGE_BYTES+1)))
        print(canonical(result));return 0
    except ContractError as error:code=error.code
    except (OSError,ValueError,RuntimeError,TypeError,KeyError,sqlite3.Error):code='persistence-failed'
    print(canonical({'error':public_error(code),'automatic_replay':False}));return 2


if __name__=='__main__':raise SystemExit(main())
