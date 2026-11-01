"""审计未决项的只读关联核验与显式观察结清；不重派、不观察或操作VM。"""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text,validate_request,fingerprint,ContractError,STATES,MESSAGES
from ctflab_generation_store import digest
from ctflab_tls_endpoint import guard
from ctflab_remote import private_json,validate_policy
from ctflab_remote_audit import AuditStore
from ctflab_local_service import LocalService
from ctflab_local_adapter import process_actor

PERMIT_FIELDS={'schema','server_uuid','principal','instance_uuid','operation_id','request_sha256',
    'policy_path','policy_sha256','lease_id','binding','purpose'}


@contextmanager
def readonly(path):
    path=guard(Path(path).absolute());require(path.is_file(),'identity-unknown')
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0,isolation_level=None)
    try:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN');yield db
    finally:db.close()


@contextmanager
def bound_instance(root,instance,binding):
    def check():
        guard(root);ledger=guard(root/'ledger.sqlite3')
        require(binding['root']==str(root) and binding['instance_uuid']==instance,'identity-unknown')
        require(binding['root_identity']==[root.stat().st_dev,root.stat().st_ino]
                and binding['ledger_identity']==[ledger.stat().st_dev,ledger.stat().st_ino],'identity-unknown')
        with readonly(ledger) as db:
            row=db.execute("SELECT value FROM metadata WHERE key='config'").fetchone()
            require(row is not None,'identity-unknown');config=json.loads(row[0])
            require(config['instance_uuid']==instance and hashlib.sha256(canonical(config).encode()).hexdigest()==binding['config_sha256'],'identity-unknown')
        profile=guard(root/'runtime-profile.json');require(profile.stat().st_size<=1024**2,'identity-unknown')
        require(digest(profile)==binding['profile_sha256'],'identity-unknown')
    check()
    try:yield
    finally:check()


class AuditReview:
    def __init__(self,policy_path):
        self.path=guard(Path(policy_path).absolute());before=digest(self.path)
        self.policy=validate_policy(private_json(self.path));self.policy_sha=digest(guard(self.path))
        require(before==self.policy_sha,'permission-denied')
        require('audit' in self.policy,'capability-unverified')
        from ctflab_server_storage import verify as verify_storage
        verify_storage(self.policy)
        self.audit=AuditStore(self.policy['audit'],self.policy['server_uuid'])

    def observation(self,intent):
        summary=intent['summary'];principal=summary['principal'];instance=summary['instance_uuid']
        account=self.policy['principals'].get(principal);entry=self.policy['instances'].get(instance)
        if (not account or not entry or instance not in account['instances']
                or account['role']=='student' and entry['owner']!=principal):return {'observation':'scope-unavailable'}
        if 'execution' not in intent:return {'observation':'not-linked'}
        operation=uuid_text(intent['execution']['operation_id'])
        if 'leases' not in self.policy or instance not in self.policy['leases']['instances']:
            return {'observation':'binding-unavailable'}
        permit=private_json(Path(self.policy['leases']['root'])/'jobs'/(operation+'.json'))
        require(set(permit)==PERMIT_FIELDS and type(permit['schema']) is int and permit['schema']==1,'identity-unknown')
        require(permit['server_uuid']==self.policy['server_uuid'] and permit['principal']==principal
                and permit['instance_uuid']==instance and permit['operation_id']==operation
                and permit['purpose'] in ('remote','expiry'),'identity-unknown')
        if permit['policy_path']!=str(self.path) or permit['policy_sha256']!=self.policy_sha:
            return {'observation':'policy-changed'}
        binding=permit['binding'];root=guard(Path(entry['root']))
        with bound_instance(root,instance,binding):
            actor=process_actor();service=LocalService(root/'desktop-contract')
            with service._read() as db:
                owned=db.execute('SELECT owner,active FROM instances WHERE id=?',(instance,)).fetchone()
                require(owned is not None and owned['owner']==actor,'identity-unknown')
                row=db.execute('SELECT actor,digest,request,status,response FROM operations WHERE id=?',(operation,)).fetchone()
                if row is None:return {'observation':'contract-missing'}
                require(row['actor']==actor and len(row['request'].encode())<=65536,'identity-unknown')
                request=validate_request(json.loads(row['request']))
                require(fingerprint(request)==row['digest']==permit['request_sha256']
                        and request['request_id']==summary['request_id'] and request['instance_uuid']==instance
                        and request['operation']==summary['operation'],'identity-unknown')
                if row['response'] is None:
                    require(row['status'] in ('pending','executing') and owned['active']==operation,'identity-unknown')
                    return {'observation':'contract-'+row['status']}
                require(row['status'] in ('completed','failed') and len(row['response'].encode())<=65536,'identity-unknown')
                response=json.loads(row['response'])
                require(response['protocol']=='ctflab-local' and type(response['version']) is int and response['version']==1
                        and response['instance_uuid']==instance and response['operation_id']==operation
                        and response['request_id']==request['request_id'] and response['result']==row['status'],'identity-unknown')
                require(type(response['state']) is str and response['state'] in STATES
                        and type(response['cancelled']) is bool,'identity-unknown')
                for field in ('generation','state_revision'):
                    require(type(response[field]) is int and 0<=response[field]<=2**53-1,'identity-unknown')
                error=response.get('error');code=error.get('code') if type(error) is dict else None
                require(code is None or type(code) is str and code in MESSAGES,'identity-unknown')
                require((row['status']=='failed')==(code is not None),'identity-unknown')
                return {'observation':'contract-recorded','contract':{'state':response['state'],'result':response['result'],
                    'cancelled':response['cancelled'],'error_code':code,'generation':response['generation'],
                    'state_revision':response['state_revision']}}

    def settlement_plan(self,db,attempt):
        from ctflab_server_storage import verify as verify_storage
        verify_storage(self.policy)
        uuid_text(attempt);events=self.audit.verify(db)
        row=db.execute('SELECT intent,completed FROM attempts WHERE id=?',(attempt,)).fetchone()
        require(row is not None and row[1]==0,'state-conflict')
        intent=events[row[0]-1]['payload'];observation=self.observation(intent)
        require(observation.get('observation')=='contract-recorded','identity-unknown')
        require(digest(guard(self.path))==self.policy_sha,'permission-denied')
        value={'schema':1,'attempt_id':attempt,'server_uuid':self.policy['server_uuid'],
            'policy_sha256':self.policy_sha,'head_seq':len(events),'head_sha256':events[-1]['sha256'],
            'operation_id':intent['execution']['operation_id'],'observation':observation,
            'original_worker_result':'unknown','vm_observed':False,'automatic_replay':False}
        value['review_sha256']=hashlib.sha256(canonical(value).encode()).hexdigest()
        return value

    def preview_settlement(self,attempt):
        with self.audit.transaction() as db:return self.settlement_plan(db,attempt)

    def settle(self,attempt,expected,*,principal=None):
        require(type(expected) is str and len(expected)==64,'state-conflict')
        with self.audit.transaction(write=True) as db:
            self.audit.require_writable(db)
            plan=self.settlement_plan(db,attempt);require(plan['review_sha256']==expected,'state-conflict')
            # 外部终态只作追加的观察来源，不伪造缺失的worker返回或重派来宾动作。
            again=self.settlement_plan(db,attempt);require(again==plan,'state-conflict')
            if principal is not None:
                from ctflab_contract import identifier
                identifier(principal);require(self.policy['principals'].get(principal,{}).get('role')=='administrator','permission-denied')
            resolution={'source':'explicit-contract-observation','review_sha256':expected,'policy_sha256':self.policy_sha}
            if principal is not None:resolution['principal']=principal
            observed=plan['observation']['contract']
            contract={k:observed[k] for k in ('state','result','cancelled','error_code')}
            self.audit.append(db,attempt,'result',{'at':self.audit.timestamp(None),'outcome':'unknown','code':None,
                'operation_id':plan['operation_id'],'contract':contract,'resolution':resolution})
            require(db.execute('UPDATE attempts SET completed=1 WHERE id=? AND completed=0',(attempt,)).rowcount==1,'state-conflict')
            self.audit.verify(db)
            return {'state':'audit-pending-resolved-by-observation','attempt_id':attempt,
                'original_worker_result':'unknown','contract_observed':True,'vm_observed':False,
                'guest_effect_verified':False,'graceful_stop_verified':False,'automatic_replay':False}

    def settle_idempotent(self,attempt,expected,*,principal=None):
        from ctflab_server_storage import verify as verify_storage
        verify_storage(self.policy)
        """RPC同一明确结清可取回原收据；原CLI的严格一次性settle保持。"""
        uuid_text(attempt)
        require(type(expected) is str and len(expected)==64 and all(c in '0123456789abcdef' for c in expected),'state-conflict')
        with self.audit.transaction() as db:
            events=self.audit.verify(db)
            row=db.execute('SELECT completed FROM attempts WHERE id=?',(attempt,)).fetchone()
            require(row is not None,'state-conflict')
            if row[0]:
                results=[e['payload'] for e in events if e['attempt_id']==attempt and e['phase']=='result']
                require(len(results)==1,'identity-unknown');resolution=results[0].get('resolution',{})
                wanted={'source':'explicit-contract-observation','review_sha256':expected,'policy_sha256':self.policy_sha}
                if principal is not None:wanted['principal']=principal
                require(resolution==wanted,'state-conflict')
                require(digest(guard(self.path))==self.policy_sha,'permission-denied')
                return {'state':'audit-pending-resolved-by-observation','attempt_id':attempt,'already_settled':True,
                    'original_worker_result':'unknown','contract_observed':True,'vm_observed':False,
                    'guest_effect_verified':False,'graceful_stop_verified':False,'automatic_replay':False}
        return self.settle(attempt,expected,principal=principal)

    def read(self,*,after=0,limit=100,checkpoint=None):
        from ctflab_server_storage import verify as verify_storage
        verify_storage(self.policy)
        require(type(after) is int and after>=0 and type(limit) is int and 1<=limit<=100)
        # 审计与各契约是独立只读快照，不能把它们冒称一个原子现场或VM观测。
        with self.audit.transaction() as db:
            events=self.audit.verify(db)
            if checkpoint is not None:
                require(type(checkpoint) is dict and set(checkpoint)=={'seq','sha256'})
                seq=checkpoint['seq'];require(type(seq) is int and 0<=seq<=len(events),'identity-unknown')
                require(checkpoint['sha256']==(events[seq-1]['sha256'] if seq else '0'*64),'identity-unknown')
            pending=db.execute('SELECT id,intent FROM attempts WHERE completed=0 AND intent>? ORDER BY intent LIMIT ?',
                               (after,limit+1)).fetchall()
            count=db.execute('SELECT COUNT(*) FROM attempts WHERE completed=0').fetchone()[0]
        rows=[]
        for attempt,seq in pending[:limit]:
            intent=events[seq-1]['payload'];summary=intent['summary']
            record={'attempt_id':attempt,'intent_seq':seq,'principal':summary['principal'],
                'request_id':summary['request_id'],'instance_uuid':summary['instance_uuid'],
                'operation_id':intent.get('execution',{}).get('operation_id'),
                'origin':'worker' if 'execution' in intent else 'request'}
            try:record.update(self.observation(intent))
            except ContractError:record['observation']='identity-conflict'
            except (OSError,ValueError,TypeError,KeyError,RuntimeError,sqlite3.Error):record['observation']='unavailable'
            rows.append(record)
        # 策略文件若在查询中发生变化，拒绝返回沿用旧scope的关联结果。
        require(digest(guard(self.path))==self.policy_sha,'permission-denied')
        return {'server_uuid':self.policy['server_uuid'],'pending':rows,'pending_count':count,
                'next_intent':rows[-1]['intent_seq'] if rows else after,'more':len(pending)>limit,
                'audit_head_seq':len(events),'audit_head_sha256':events[-1]['sha256'] if events else '0'*64,
                'checkpoint_verified':checkpoint is not None,'snapshots_atomic':False,
                'audit_modified':False,'contract_modified':False,'vm_observed':False,'automatic_replay':False,
                'guest_effect_verified':False,'graceful_stop_verified':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--policy',required=True,type=Path)
    parser.add_argument('--after-intent',type=int,default=0);parser.add_argument('--limit',type=int,default=100)
    parser.add_argument('--action',choices=('read','preview-settlement','settle'),default='read')
    parser.add_argument('--attempt-id');parser.add_argument('--review-sha256')
    parser.add_argument('--checkpoint-seq',type=int);parser.add_argument('--checkpoint-sha256');args=parser.parse_args(argv)
    try:
        require((args.checkpoint_seq is None)==(args.checkpoint_sha256 is None))
        checkpoint=None if args.checkpoint_seq is None else {'seq':args.checkpoint_seq,'sha256':args.checkpoint_sha256}
        require(bool(args.attempt_id)==(args.action!='read') and bool(args.review_sha256)==(args.action=='settle'))
        require(args.action=='read' or args.after_intent==0 and args.limit==100 and checkpoint is None)
        review=AuditReview(args.policy)
        value=review.preview_settlement(args.attempt_id) if args.action=='preview-settlement' else review.settle(args.attempt_id,args.review_sha256) if args.action=='settle' else review.read(after=args.after_intent,limit=args.limit,checkpoint=checkpoint)
        print(canonical(value));return 0
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,sqlite3.Error):
        print(canonical({'state':'unknown','automatic_replay':False,'preserved':True}));return 2


if __name__=='__main__':raise SystemExit(main())
