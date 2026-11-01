"""服务端私有远程审计：先记录尝试、再追加结果；不重放、不记录载荷或凭据。"""
import argparse
from contextlib import contextmanager,closing
from datetime import datetime,timezone
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import sys
import uuid

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,identifier,uuid_text,ContractError,MESSAGES,STATES
from ctflab_generation_store import private_directory
from ctflab_tls_endpoint import guard

ACTIONS=frozenset(('evidence-list','evidence-read','display-open','display-frame','display-key','display-pointer','display-close','lease-expiry','handshake','list','overview','diagnostics','submit','events',
    'course-list','course-preview','course-provision','audit-review','audit-settlement-preview','audit-settle',
    'asset-begin','asset-status','asset-chunk','asset-finish','lease-acquire','lease-renew','lease-release','lease-status'))
OPERATIONS=frozenset(('prepare','start','stop','reset','recover','guest','status','cancel'))
ZERO='0'*64


def settings(value):
    require(type(value) is dict and set(value)=={'root','max_attempts'})
    require(isinstance(value['root'],str) and Path(value['root']).is_absolute())
    require(type(value['max_attempts']) is int and 1<=value['max_attempts']<=10000)
    return value


def optional_uuid(value):
    try:return uuid_text(value)
    except (ValueError,TypeError,AttributeError):return None


def summary(value,principal):
    identifier(principal)
    value=value if type(value) is dict else {}
    params=value.get('parameters');params=params if type(params) is dict else {}
    request=params.get('request');request=request if type(request) is dict else {}
    # 不保存原请求/响应摘要，避免低熵凭据或课程答案通过摘要被枚举。
    action=value.get('action');operation=request.get('operation')
    return {'principal':principal,'request_id':optional_uuid(value.get('request_id')),
            'action':action if type(action) is str and action in ACTIONS else 'invalid',
            'instance_uuid':optional_uuid(params.get('instance_uuid')),
            'operation':operation if type(operation) is str and operation in OPERATIONS else None}


class AuditStore:
    def __init__(self,config,server):
        self.config=settings(config);self.root=Path(config['root']).absolute();uuid_text(server);self.server=server

    @classmethod
    def create(cls,config,server):
        store=cls(config,server);private_directory(store.root)
        fd=os.open(store.root/'audit.sqlite3',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        with closing(sqlite3.connect(store.root/'audit.sqlite3')) as db:
            db.executescript('CREATE TABLE metadata(schema INTEGER,server TEXT,capacity INTEGER,seq INTEGER,sha TEXT);'
                'CREATE TABLE attempts(id TEXT PRIMARY KEY,intent INTEGER UNIQUE,completed INTEGER,summary TEXT);'
                'CREATE TABLE events(seq INTEGER PRIMARY KEY,attempt TEXT,phase TEXT,payload TEXT,previous TEXT,sha TEXT);')
            db.execute('INSERT INTO metadata VALUES(1,?,?,0,?)',(server,config['max_attempts'],ZERO));db.commit()
        return store

    @contextmanager
    def transaction(self,*,write=False):
        guard(self.root);path=guard(self.root/'audit.sqlite3')
        db=sqlite3.connect(path.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=0,isolation_level=None)
        try:
            if write:db.execute('PRAGMA synchronous=FULL')
            else:db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    def verify(self,db):
        meta=db.execute('SELECT schema,server,capacity,seq,sha FROM metadata').fetchall()
        require(len(meta)==1 and meta[0][:3]==(1,self.server,self.config['max_attempts']),'identity-unknown')
        rows=db.execute('SELECT seq,attempt,phase,payload,previous,sha FROM events ORDER BY seq LIMIT 20001').fetchall()
        require(len(rows)<=2*self.config['max_attempts'],'identity-unknown')
        previous=ZERO;attempts={};result=[]
        for expected,(seq,attempt,phase,encoded,parent,sha) in enumerate(rows,1):
            uuid_text(attempt);payload=json.loads(encoded)
            require(type(payload) is dict and seq==expected and parent==previous,'identity-unknown')
            record={'seq':seq,'attempt_id':attempt,'phase':phase,'payload':payload,'previous':parent}
            require(hashlib.sha256(canonical(record).encode()).hexdigest()==sha,'identity-unknown')
            require(type(payload.get('at')) is str and len(payload['at'])<=40,'identity-unknown')
            if phase=='intent':
                require(set(payload) in ({'at','summary'},{'at','summary','execution'}) and attempt not in attempts,'identity-unknown')
                if 'execution' in payload:
                    execution=payload['execution']
                    require(type(execution) is dict and set(execution)=={'origin','operation_id'}
                            and execution['origin']=='worker','identity-unknown')
                    uuid_text(execution['operation_id'])
                require(summary({'request_id':payload['summary']['request_id'],'action':payload['summary']['action'],
                    'parameters':{'instance_uuid':payload['summary']['instance_uuid'],'request':{'operation':payload['summary']['operation']}}},
                    payload['summary']['principal'])==payload['summary'],'identity-unknown')
                attempts[attempt]=[seq,0,canonical(payload['summary'])]
            else:
                require(phase=='result' and set(payload) in ({'at','outcome','code','operation_id'},
                        {'at','outcome','code','operation_id','contract'},
                        {'at','outcome','code','operation_id','contract','resolution'})
                        and attempt in attempts and attempts[attempt][1]==0,'identity-unknown')
                require(payload['outcome'] in ('returned','rejected','unknown') and payload['code'] in (None,*MESSAGES)
                        and (payload['operation_id'] is None or optional_uuid(payload['operation_id'])==payload['operation_id']),'identity-unknown')
                intent=result[attempts[attempt][0]-1]['payload']
                if 'execution' in intent:
                    require(payload['operation_id']==intent['execution']['operation_id'],'identity-unknown')
                if 'contract' in payload:
                    require('execution' in intent,'identity-unknown');contract=payload['contract']
                    require(type(contract) is dict and set(contract)=={'state','result','cancelled','error_code'},'identity-unknown')
                    require(contract['state'] is None or type(contract['state']) is str and contract['state'] in STATES,'identity-unknown')
                    require(contract['result'] in (None,'completed','failed','accepted','unknown')
                            and type(contract['cancelled']) in (bool,type(None)) and contract['error_code'] in (None,*MESSAGES),'identity-unknown')
                if 'resolution' in payload:
                    resolution=payload['resolution']
                    require('execution' in intent and 'contract' in payload and payload['outcome']=='unknown'
                            and type(resolution) is dict and set(resolution) in ({'source','review_sha256','policy_sha256'},{'source','review_sha256','policy_sha256','principal'})
                            and resolution['source']=='explicit-contract-observation'
                            and all(type(resolution[k]) is str and re.fullmatch('[0-9a-f]{64}',resolution[k])
                                    for k in ('review_sha256','policy_sha256')),'identity-unknown')
                    if 'principal' in resolution:identifier(resolution['principal'])
                attempts[attempt][1]=1
            result.append(dict(record,sha256=sha));previous=sha
        require(meta[0][3:]==(len(rows),previous),'identity-unknown')
        indexed=db.execute('SELECT id,intent,completed,summary FROM attempts LIMIT 10001').fetchall()
        require(len(indexed)==len(attempts)<=self.config['max_attempts'],'identity-unknown')
        require(all(attempt in attempts and list(row)==attempts[attempt] for attempt,*row in indexed),'identity-unknown')
        return result

    @staticmethod
    def timestamp(now):
        value=now() if now else datetime.now(timezone.utc)
        require(isinstance(value,datetime) and value.tzinfo is not None)
        return value.astimezone(timezone.utc).isoformat()

    def append(self,db,attempt,phase,payload):
        seq,previous=db.execute('SELECT seq,sha FROM metadata').fetchone();seq+=1
        record={'seq':seq,'attempt_id':attempt,'phase':phase,'payload':payload,'previous':previous}
        sha=hashlib.sha256(canonical(record).encode()).hexdigest()
        db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',(seq,attempt,phase,canonical(payload),previous,sha))
        db.execute('UPDATE metadata SET seq=?,sha=?',(seq,sha));return seq

    def require_writable(self,db):
        present=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit_seal'").fetchone()
        require(present is None,'state-conflict')

    def begin(self,value,principal,*,now=None,execution=None):
        record=summary(value,principal);attempt=str(uuid.uuid4())
        payload={'at':self.timestamp(now),'summary':record}
        if execution is not None:
            require(type(execution) is dict and set(execution)=={'origin','operation_id'} and execution['origin']=='worker')
            uuid_text(execution['operation_id']);payload['execution']=dict(execution)
        with self.transaction(write=True) as db:
            self.verify(db);self.require_writable(db)
            require(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]<self.config['max_attempts'],'storage-insufficient')
            seq=self.append(db,attempt,'intent',payload)
            db.execute('INSERT INTO attempts VALUES(?,?,0,?)',(attempt,seq,canonical(record)))
        return attempt

    def finish(self,attempt,*,error=None,response=None,now=None):
        uuid_text(attempt)
        outcome='returned' if error is None else 'rejected' if isinstance(error,ContractError) else 'unknown'
        code=error.code if isinstance(error,ContractError) else None
        result=response.get('result') if type(response) is dict else None
        operation=optional_uuid(result.get('operation_id')) if type(result) is dict else None
        with self.transaction(write=True) as db:
            self.verify(db);self.require_writable(db)
            row=db.execute('SELECT completed,intent FROM attempts WHERE id=?',(attempt,)).fetchone()
            require(row is not None and row[0]==0,'state-conflict')
            intent=json.loads(db.execute('SELECT payload FROM events WHERE seq=?',(row[1],)).fetchone()[0])
            payload={'at':self.timestamp(now),'outcome':outcome,'code':code,'operation_id':operation}
            if 'execution' in intent:
                operation=intent['execution']['operation_id'];payload['operation_id']=operation
                if error is None:
                    require(type(response) is dict and response.get('operation_id')==operation
                            and response.get('instance_uuid')==intent['summary']['instance_uuid'],'identity-unknown')
                    state=response.get('state');result=response.get('result');cancelled=response.get('cancelled')
                    failure=response.get('error');failure=failure.get('code') if type(failure) is dict else None
                    payload['contract']={'state':state if type(state) is str and state in STATES else None,
                        'result':result if type(result) is str and result in ('completed','failed','accepted','unknown') else None,
                        'cancelled':cancelled if type(cancelled) is bool else None,
                        'error_code':failure if type(failure) is str and failure in MESSAGES else None}
            self.append(db,attempt,'result',payload)
            db.execute('UPDATE attempts SET completed=1 WHERE id=?',(attempt,))

    def read(self,*,after=0,limit=100,checkpoint=None):
        require(type(after) is int and after>=0 and type(limit) is int and 1<=limit<=100)
        with self.transaction() as db:
            events=self.verify(db);page=[r for r in events if r['seq']>after][:limit]
            if checkpoint is not None:
                require(type(checkpoint) is dict and set(checkpoint)=={'seq','sha256'})
                seq=checkpoint['seq'];sha=checkpoint['sha256']
                require(type(seq) is int and 0<=seq<=len(events) and isinstance(sha,str)
                        and re.fullmatch('[0-9a-f]{64}',sha),'identity-unknown')
                require(sha==(events[seq-1]['sha256'] if seq else ZERO),'identity-unknown')
            pending=[r[0] for r in db.execute('SELECT id FROM attempts WHERE completed=0 ORDER BY intent LIMIT 101')]
        return {'server_uuid':self.server,'events':page,'next':page[-1]['seq'] if page else after,
                'head_seq':len(events),'head_sha256':events[-1]['sha256'] if events else ZERO,
                'pending':pending[:100],'pending_truncated':len(pending)>100,'automatic_replay':False,
                'chain_consistent':True,'checkpoint_verified':checkpoint is not None,
                'externally_anchored':False,'guest_effect_verified':False}


def execute_audited(policy,principal,request,operation_id,call):
    """仅经已验证许可进入的worker调用；不接受请求自报执行来源或回放标记。"""
    from ctflab_server_storage import verify as verify_storage
    verify_storage(policy)
    if 'audit' not in policy:return call()
    uuid_text(operation_id)
    audit=AuditStore(policy['audit'],policy['server_uuid'])
    value={'action':'submit','request_id':request['request_id'],
           'parameters':{'instance_uuid':request['instance_uuid'],'request':request}}
    try:
        attempt=audit.begin(value,principal,execution={'origin':'worker','operation_id':operation_id})
    except ContractError:raise
    except (OSError,ValueError,RuntimeError,sqlite3.Error):raise ContractError('persistence-failed') from None
    try:response=call()
    except Exception as error:
        try:audit.finish(attempt,error=error)
        except (OSError,ValueError,RuntimeError,sqlite3.Error):raise ContractError('persistence-failed') from None
        raise
    try:audit.finish(attempt,response=response)
    except (OSError,ValueError,RuntimeError,sqlite3.Error):raise ContractError('persistence-failed') from None
    return response


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('initialize','read'))
    parser.add_argument('--policy',required=True,type=Path);parser.add_argument('--after',type=int,default=0)
    parser.add_argument('--limit',type=int,default=100)
    parser.add_argument('--checkpoint-seq',type=int);parser.add_argument('--checkpoint-sha256');args=parser.parse_args(argv)
    try:
        from ctflab_remote import private_json,validate_policy
        policy=validate_policy(private_json(args.policy));config=policy['audit']
        from ctflab_server_storage import verify as verify_storage
        verify_storage(policy)
        if args.action=='initialize':
            AuditStore.create(config,policy['server_uuid']);value={'state':'initialized','automatic_cleanup':False}
        else:
            require((args.checkpoint_seq is None)==(args.checkpoint_sha256 is None))
            checkpoint=None if args.checkpoint_seq is None else {'seq':args.checkpoint_seq,'sha256':args.checkpoint_sha256}
            value=AuditStore(config,policy['server_uuid']).read(after=args.after,limit=args.limit,checkpoint=checkpoint)
        print(canonical(value));return 0
    except (OSError,ValueError,RuntimeError,TypeError,KeyError,sqlite3.Error):
        print(canonical({'state':'unknown','automatic_replay':False,'preserved':True}));return 2


if __name__=='__main__':raise SystemExit(main())
