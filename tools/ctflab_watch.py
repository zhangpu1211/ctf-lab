"""显式启动的有界只读场景监督：固定实例代次，不重放或自动控制VM。"""
import argparse
from datetime import datetime,timezone,timedelta
import hashlib
import os
from pathlib import Path
import signal
import sqlite3
from contextlib import ExitStack,closing
import sys
import threading
import time
import uuid
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text,ContractError
from ctflab_generation_store import GenerationStore,private_directory,digest
from ctflab_tls_endpoint import guard
from ctflab_windows_recovery import record,command_lock
from ctflab_qemu_driver import QemuDriver,read
from ctflab_scenario_coordinator import NodeObservation

EVENT_LIMIT=2*1024**2


def scope(root):
    root=guard(Path(root).absolute());store=GenerationStore(root);snapshot=store.snapshot()
    require(snapshot['active_generation']>0,'state-conflict')
    profile=guard(root/'runtime-profile.json');require(profile.stat().st_size<=8*1024**2,'storage-insufficient')
    ledger=guard(root/'ledger.sqlite3').stat();info=root.stat()
    return {'instance_uuid':store.config['instance_uuid'],'generation':snapshot['active_generation'],
        'root_identity':[info.st_dev,info.st_ino],'ledger_identity':[ledger.st_dev,ledger.st_ino],
        'profile_sha256':digest(profile),'config_sha256':hashlib.sha256(canonical(store.config).encode()).hexdigest()}


def publish(directory,name,value):
    require(name in ('current','complete'))
    path=directory/(name+'.json');pending=directory/(name+'.pending')
    if path.exists():guard(path)
    record(pending,value);os.replace(pending,path)


def epochs(root, stack):
    """持连接读取data_version，无跨I/O读写事务；同状态ABA提交也使窗口失效。"""
    paths=[root/'ledger.sqlite3']
    contract=root/'desktop-contract'/'contract.sqlite3'
    if contract.exists():paths.append(contract)
    connections=[]
    for path in paths:
        guard(path)
        db=stack.enter_context(closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0,isolation_level=None)))
        info=path.stat();connections.append((path,db,[info.st_dev,info.st_ino]))
    def token():
        result=[]
        for path,db,expected in connections:
            info=guard(path).stat()
            require([info.st_dev,info.st_ino]==expected,'identity-unknown')
            result.append((expected,db.execute('PRAGMA data_version').fetchone()[0]))
        # 启动采样后才创建契约也属于变化，不能静默忽略。
        require(contract.exists()==(len(connections)>1),'identity-unknown')
        result.append(contract.exists())
        return result
    def busy():
        with GenerationStore(root).db() as db:
            if db.execute("SELECT 1 FROM operations WHERE state='intent' LIMIT 1").fetchone():return True
        if len(connections)>1:
            rows=connections[1][1].execute('SELECT active FROM instances LIMIT 2').fetchall()
            require(len(rows)==1, 'identity-unknown')
            return rows[0][0] is not None
        return False
    return token,busy


def run(root,operation,*,duration=3600,interval=30,stop=None,make_driver=None,clock=time.monotonic,wait=None):
    uuid_text(operation)
    require(type(duration) is int and 1<=duration<=604800 and type(interval) is int and 5<=interval<=300)
    stop=stop or threading.Event();wait=wait or stop.wait
    require(not stop.is_set(),'operation-finished')
    root=guard(Path(root).absolute());binding=scope(root);store=GenerationStore(root)
    plan=store.plan(binding['generation']);driver=make_driver(store) if make_driver else QemuDriver(store,read(root/'runtime-profile.json'))
    parent=root/'watches'
    if not parent.exists():
        try:private_directory(parent)
        except FileExistsError:guard(parent)
    guard(parent);require(sum(1 for _ in parent.iterdir())<256,'storage-insufficient')
    directory=parent/operation;private_directory(directory)
    record(directory/'control.lock',{})
    record(directory/'intent.json',{'schema':1,'operation_id':operation,'scope':binding,
        'duration_seconds':duration,'interval_seconds':interval,'automatic_replay':False})
    ticks=0;events=0;discarded=0;last=None;state='watch-complete';deadline=clock()+duration
    fd=os.open(directory/'events.jsonl',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    latest=None
    with os.fdopen(fd,'wb') as log,command_lock(directory),ExitStack() as stack:
        epoch,busy=epochs(root,stack)
        try:
            while not stop.is_set() and clock()<deadline:
                if scope(root)!=binding:state='watch-scope-changed';break
                before=epoch();in_progress=busy();samples=[]
                started=datetime.now(timezone.utc)
                for node in plan['start_order']:
                    if stop.is_set():break
                    try:
                        value=driver.observe(plan,node,store.node_paths(binding['generation'],node))
                        require(isinstance(value,NodeObservation) and value.instance_uuid==binding['instance_uuid']
                            and type(value.generation) is int and value.generation==binding['generation']
                            and value.node==node and value.identity=='verified' and value.state in ('stopped','process-running'),'identity-unknown')
                        samples.append({'node':node,'state':value.state,'identity':'verified'})
                    except (OSError,ValueError,RuntimeError,KeyError,TypeError):
                        samples.append({'node':node,'state':'unknown','identity':'unknown'})
                if stop.is_set():break
                after_scope=scope(root)
                coherent=before==epoch() and after_scope==binding and not in_progress and not busy()
                if not coherent:
                    samples=[dict(value,state='unknown',identity='unknown') for value in samples]
                reason='sampled' if coherent else ('operation-in-progress' if in_progress else 'changed-during-sampling')
                ticks+=1;signature=canonical({'nodes':samples,'coherent':coherent,'reason':reason})
                snapshot={'schema':1,'operation_id':operation,'scope':binding,'ticks':ticks,'nodes':samples,
                    'sampled_at':started.isoformat(),'valid_until':(started+timedelta(seconds=interval+30)).isoformat(),
                    'coherent':coherent,'complete':coherent and all(v['identity']=='verified' for v in samples),
                    'reason':reason,'watch_active':True,'historical':False,'scope_kind':'process-samples-not-guest-or-course-health',
                    'vm_control_sent':False,'automatic_replay':False,'pipe_takeover':False}
                if signature!=last:
                    raw=(canonical(snapshot)+'\n').encode()
                    if events+len(raw)<=EVENT_LIMIT:log.write(raw);log.flush();os.fsync(log.fileno());events+=len(raw)
                    else:discarded+=1
                    last=signature
                latest=dict(snapshot,event_bytes=events,discarded_changes=discarded)
                publish(directory,'current',latest)
                if after_scope!=binding:state='watch-scope-changed';break
                if wait(min(interval,max(0,deadline-clock()))):break
        except (OSError,ValueError,RuntimeError,KeyError,TypeError,sqlite3.Error):
            state='watch-observation-failed'
        if latest is not None:
            if state in ('watch-scope-changed','watch-observation-failed'):
                latest.update(coherent=False,complete=False,reason=state,
                    nodes=[dict(v,state='unknown',identity='unknown') for v in latest['nodes']])
            publish(directory,'current',dict(latest,watch_active=False,historical=True,
                valid_until=datetime.now(timezone.utc).isoformat()))
        result={'state':state,'operation_id':operation,'ticks':ticks,'event_bytes':events,
            'discarded_changes':discarded,'cancel_requested':stop.is_set(),'vm_control_sent':False,
            'automatic_replay':False,'pipe_takeover':False,'graceful_stop_verified':False}
        publish(directory,'complete',result)
    return result


def history(root):
    root=guard(Path(root).absolute());parent=root/'watches';store=GenerationStore(root)
    if not parent.exists():return {'watches':[],'network_sent':False,'automatic_replay':False,'historical':True}
    guard(parent);values=[]
    for number,directory in enumerate(sorted(parent.iterdir()),1):
        require(number<=256,'storage-insufficient');guard(directory);uuid_text(directory.name)
        from ctflab_windows_recovery import read_json
        def metadata(name):return read_json(directory/name,guard,65536)
        intent=metadata('intent.json');binding=intent['scope']
        require(intent.get('operation_id')==directory.name and binding.get('instance_uuid')==store.config['instance_uuid']
            and type(binding.get('generation')) is int and binding['generation']>0,'identity-unknown')
        value=metadata('complete.json') if (directory/'complete.json').exists() else {'state':'interrupted-or-running'}
        require(value.get('state') in ('watch-complete','watch-scope-changed','watch-observation-failed','interrupted-or-running'),'identity-unknown')
        item={'operation_id':directory.name,'state':value['state'],'generation':binding['generation'],
            'historical':True,'live_process_rechecked':False,'ticks':None,'sampled_at':None,'coherent':False,'complete':False}
        if (directory/'current.json').exists():
            current=metadata('current.json')
            require(current.get('operation_id')==directory.name and current.get('scope')==binding
                and type(current.get('ticks')) is int and current['ticks']>0,'identity-unknown')
            stamp=datetime.fromisoformat(current['sampled_at'].replace('Z','+00:00'))
            require(stamp.tzinfo is not None and stamp<=datetime.now(timezone.utc),'identity-unknown')
            item.update(ticks=current['ticks'],sampled_at=current['sampled_at'],coherent=current.get('coherent') is True,
                complete=current.get('complete') is True and current.get('coherent') is True)
        values.append(item)
    values.sort(key=lambda item: datetime.fromisoformat(item['sampled_at'].replace('Z','+00:00')).timestamp() if item['sampled_at'] else 0)
    return {'watches':values,'network_sent':False,'automatic_replay':False,'historical':True}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('history','run'))
    parser.add_argument('--run',required=True,type=Path);parser.add_argument('--operation-id')
    parser.add_argument('--duration',default=3600,type=int);parser.add_argument('--interval',default=30,type=int)
    args=parser.parse_args(argv)
    try:
        if args.action=='history':require(args.operation_id is None);result=history(args.run)
        else:
            require(args.operation_id is not None);stop=threading.Event()
            for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
            result=run(args.run,args.operation_id,duration=args.duration,interval=args.interval,stop=stop)
        print(canonical(result));return 2 if result.get('state')=='watch-observation-failed' else 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,sqlite3.Error):
        print(canonical({'state':'watch-refused-or-interrupted','preserved':True,'vm_control_sent':False,'automatic_replay':False}));return 2


if __name__=='__main__':raise SystemExit(main())
