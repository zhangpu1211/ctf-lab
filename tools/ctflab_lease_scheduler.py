"""租约周期调度入口：默认只读预览；执行/初始化均须显式选择，不安装服务。"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import threading
import uuid
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,ContractError
from ctflab_generation_store import digest
from ctflab_tls_endpoint import guard
from ctflab_remote import private_json,validate_policy
from ctflab_lease_store import LeaseStore
from ctflab_remote_leases import RemoteLeases


class LeaseScheduler:
    def __init__(self,policy_path,*,pool_factory=LeaseStore,manager_factory=RemoteLeases):
        self.path=Path(policy_path).absolute();self.pool_factory=pool_factory;self.manager_factory=manager_factory;self.cursor=''

    def config(self):
        before=digest(guard(self.path));policy=validate_policy(private_json(self.path))
        require('leases' in policy and before==digest(guard(self.path)),'identity-unknown')
        from ctflab_server_storage import verify as verify_storage
        verify_storage(policy)
        return policy,before

    def initialize(self):
        policy,sha=self.config();root=guard(Path(policy['leases']['root']));self.pool_factory(root,policy['server_uuid'])
        path=root/'scheduler.lock'
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
        return {'state':'scheduler-gate-initialized','scheduler_installed':False,'expiry_executed':False}

    @contextmanager
    def gate(self,policy):
        require(sys.platform=='linux' and os.geteuid()!=0,'unsupported-platform')
        import fcntl
        path=guard(Path(policy['leases']['root'])/'scheduler.lock');info=path.stat()
        require(path.is_file() and info.st_nlink==1,'identity-unknown')
        with path.open('rb') as stream:
            opened=os.fstat(stream.fileno());require((opened.st_dev,opened.st_ino)==(info.st_dev,info.st_ino),'identity-unknown')
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            yield

    def candidates(self,policy,limit):
        pool=self.pool_factory(policy['leases']['root'],policy['server_uuid'])
        with pool.db() as db:ids=[row[0] for row in db.execute("SELECT id FROM leases WHERE state!='released' ORDER BY id LIMIT 10001")]
        require(len(ids)<=10000,'storage-insufficient')
        # 有界轮转，避免第一批长期attention租约饿死后续租约；进程重启从头只读核验。
        ordered=[value for value in ids if value>self.cursor]+[value for value in ids if value<=self.cursor]
        result=[]
        for identity in ordered[:limit]:
            row=pool.get(identity);timing=pool.time_state(row)
            result.append({'lease_id':identity,'principal':row['principal'],'time_state':timing,
                'state':row['state'],'instance_uuid':row['instance_uuid'],'expiry_action':row['binding']['expiry_action']})
        if result:self.cursor=result[-1]['lease_id']
        return result,len(ids)

    def tick_locked(self,policy,sha,limit,execute):
        rows,total=self.candidates(policy,limit);results=[]
        for row in rows:
            require(digest(guard(self.path))==sha,'permission-denied')
            if not execute or row['time_state']=='active':
                results.append({'lease_id':row['lease_id'],'time_state':row['time_state'],'processed':False});continue
            attempt=None;audit=None
            try:
                if 'audit' in policy:
                    from ctflab_remote_audit import AuditStore
                    audit=AuditStore(policy['audit'],policy['server_uuid'])
                    attempt=audit.begin({'action':'lease-expiry','request_id':str(uuid.uuid4()),
                        'parameters':{'instance_uuid':row['instance_uuid']}},row['principal'])
                manager=self.manager_factory(policy,row['principal'],policy_path=self.path)
                manager.require_policy(sha)
                outcome=manager.expiry(row['lease_id'])
                if audit:audit.finish(attempt,response={'result':outcome})
                results.append({'lease_id':row['lease_id'],'state':outcome.get('state','unknown'),
                    'processed':True,'automatic_replay':False})
            except (OSError,ValueError,RuntimeError,KeyError,TypeError,sqlite3.Error) as error:
                if audit and attempt:
                    try:audit.finish(attempt,error=error)
                    except (OSError,ValueError,RuntimeError,KeyError,TypeError,sqlite3.Error):pass
                results.append({'lease_id':row['lease_id'],'state':'attention','processed':False,'automatic_replay':False})
        return {'state':'scheduler-tick' if execute else 'scheduler-preview','total_held':total,'checked':len(rows),
            'leases':results,'expiry_executed':execute,'scheduler_installed':False,'automatic_cleanup':False,
            'disk_reservation_hard_enforced':False,'graceful_stop_verified':False}

    def tick(self,*,execute=False,limit=16):
        require(type(execute) is bool and type(limit) is int and 1<=limit<=100)
        policy,sha=self.config()
        if not execute:return self.tick_locked(policy,sha,limit,False)
        with self.gate(policy):return self.tick_locked(policy,sha,limit,True)

    def loop(self,stop,*,interval=30,limit=16):
        require(type(interval) is int and 10<=interval<=3600)
        # 单个调度器全周期持同一root门；策略换租约根后要求重启，不产生第二调度身份。
        policy,sha=self.config()
        with self.gate(policy):
            while not stop.is_set():
                current,current_sha=self.config()
                require(current['server_uuid']==policy['server_uuid'] and current['leases']['root']==policy['leases']['root'],'identity-unknown')
                yield self.tick_locked(current,current_sha,limit,True)
                if stop.wait(interval):break


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('preview','initialize','once','loop'))
    parser.add_argument('--policy',type=Path,required=True);parser.add_argument('--execute',action='store_true')
    parser.add_argument('--limit',type=int,default=16);parser.add_argument('--interval',type=int,default=30);args=parser.parse_args(argv)
    try:
        require(args.execute==(args.action in ('once','loop')))
        scheduler=LeaseScheduler(args.policy)
        if args.action=='loop':
            stopped=threading.Event()
            for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stopped.set())
            for value in scheduler.loop(stopped,interval=args.interval,limit=args.limit):print(canonical(value),flush=True)
        else:
            value=scheduler.initialize() if args.action=='initialize' else scheduler.tick(execute=args.execute,limit=args.limit)
            print(canonical(value))
        return 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,sqlite3.Error):
        print(canonical({'state':'refused-or-unknown','preserved':True,'automatic_replay':False,'scheduler_installed':False}));return 2


if __name__=='__main__':raise SystemExit(main())
