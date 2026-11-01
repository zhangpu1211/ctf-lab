"""受管远程资源租约账本：准入预留、单调时限、保留现场；不执行VM操作。"""
from contextlib import contextmanager,closing
from datetime import datetime,timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time

from ctflab_contract import canonical,require,identifier,uuid_text,ContractError
from ctflab_generation_store import private_directory
from ctflab_tls_endpoint import guard

RESOURCES=('cpus','memory_mb','disk_reservation_bytes')


def resource_limits(value):
    require(type(value) is dict and set(value)==set(RESOURCES))
    for key,maximum in zip(RESOURCES,(4096,16*1024**2,1024**5)):
        require(type(value[key]) is int and 1<=value[key]<=maximum)
    return value


def validate_settings(value):
    require(type(value) is dict and set(value)=={'root','capacity','limits','instances','max_ttl_seconds'})
    require(isinstance(value['root'],str) and Path(value['root']).is_absolute())
    resource_limits(value['capacity'])
    require(type(value['limits']) is dict and 1<=len(value['limits'])<=256)
    for principal,limits in value['limits'].items():identifier(principal);resource_limits(limits)
    require(type(value['instances']) is dict and 1<=len(value['instances'])<=1024)
    for instance,entry in value['instances'].items():
        uuid_text(instance)
        require(type(entry) is dict and set(entry)=={'disk_reservation_bytes','expiry_action'})
        require(type(entry['disk_reservation_bytes']) is int and 1<=entry['disk_reservation_bytes']<=1024**5)
        require(entry['expiry_action'] in ('notify','request-stop'))
    require(type(value['max_ttl_seconds']) is int and 10<=value['max_ttl_seconds']<=86400)
    return value


class HostClock:
    def sample(self):
        require(sys.platform=='linux','unsupported-platform')
        boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();uuid_text(boot)
        return {'boot_id':boot,'mono':time.monotonic(),'utc':time.time()}


class LeaseStore:
    def __init__(self,root,server_uuid,*,clock=None):
        self.root=guard(Path(root).absolute());uuid_text(server_uuid);self.server_uuid=server_uuid
        self.clock=clock or HostClock();self._owner=None
        with self.db() as db:
            require(db.execute('SELECT schema,server FROM metadata').fetchone()==(1,server_uuid),'identity-unknown')

    @classmethod
    def create(cls,root,server_uuid,*,clock=None):
        uuid_text(server_uuid);root=Path(root).absolute();private_directory(root)
        private_directory(root/'jobs')
        private_directory(root/'job-logs')
        schema='''CREATE TABLE metadata(schema INTEGER,server TEXT);
CREATE TABLE leases(id TEXT PRIMARY KEY,instance TEXT,principal TEXT,state TEXT,payload TEXT);
CREATE UNIQUE INDEX held_instance ON leases(instance) WHERE state!='released';
CREATE TABLE storage(instance TEXT PRIMARY KEY,principal TEXT,bytes INTEGER,binding TEXT);
CREATE TABLE renewals(id TEXT PRIMARY KEY,digest TEXT,payload TEXT);
'''
        for name,sql in (('leases.sqlite3',schema),('gate.sqlite3','CREATE TABLE gate(id INTEGER);')):
            fd=os.open(root/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
            with closing(sqlite3.connect(root/name)) as db:
                db.executescript(sql)
                if name=='leases.sqlite3':db.execute('INSERT INTO metadata VALUES(1,?)',(server_uuid,))
                db.commit()
        return cls(root,server_uuid,clock=clock)

    @contextmanager
    def db(self,*,write=False,gate=False):
        guard(self.root);path=guard(self.root/('gate.sqlite3' if gate else 'leases.sqlite3'))
        db=sqlite3.connect(path.as_uri()+'?mode=rw',uri=True,timeout=0,isolation_level=None)
        try:
            db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE' if write or gate else 'BEGIN')
            yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    @contextmanager
    def locked(self):
        require(self._owner!=threading.get_ident(),'resource-busy')
        try:
            with self.db(gate=True):
                self._owner=threading.get_ident()
                try:yield
                finally:self._owner=None
        except sqlite3.OperationalError as error:
            raise ContractError('resource-busy' if 'locked' in str(error) else 'persistence-failed') from None

    def held(self):require(self._owner==threading.get_ident(),'permission-denied')

    def sample(self):
        value=self.clock.sample()
        require(type(value) is dict and set(value)=={'boot_id','mono','utc'})
        uuid_text(value['boot_id'])
        require(all(type(value[k]) in (int,float) and math.isfinite(value[k]) and value[k]>=0 for k in ('mono','utc')))
        require(value['utc']<=253402214400,'capability-unverified')
        return value

    def time_state(self,row):
        now=self.sample();old=row['issued']
        if (now['boot_id']!=old['boot_id'] or now['mono']<old['mono']
                or abs((now['utc']-old['utc'])-(now['mono']-old['mono']))>300):return 'clock-uncertain'
        return 'expired' if now['mono']>=row['deadline_mono'] else 'active'

    def get(self,lease):
        uuid_text(lease)
        with self.db() as db:row=db.execute('SELECT instance,principal,state,payload FROM leases WHERE id=?',(lease,)).fetchone()
        require(row is not None,'state-conflict');value=json.loads(row[3])
        require(value['lease_id']==lease and (value['instance_uuid'],value['principal'],value['state'])==row[:3]
                and value['binding']['instance_uuid']==row[0],'identity-unknown');return value

    def save(self,row):
        self.held()
        with self.db(write=True) as db:
            require(db.execute('UPDATE leases SET state=?,payload=? WHERE id=?',
                               (row['state'],canonical(row),row['lease_id'])).rowcount==1,'state-conflict')

    def view(self,row):
        timing=self.time_state(row)
        return {'lease_id':row['lease_id'],'instance_uuid':row['instance_uuid'],'principal':row['principal'],
                'state':timing if row['state']=='reserved' else row['state'],'time_state':timing,
                'expires_at':datetime.fromtimestamp(row['expires_utc'],timezone.utc).isoformat(),
                'resources':{key:row['binding'][key] for key in RESOURCES},
                'expiry_action':row['binding']['expiry_action'],'stop_operation_id':row['stop_operation_id'],
                'disk_reservation_hard_enforced':False,'storage_reference_retained':True,
                'graceful_stop_verified':False,'automatic_replay':False}

    def usage(self,principal):
        identifier(principal)
        total={key:0 for key in RESOURCES};own=dict(total)
        with self.db() as db:
            for encoded,owner in db.execute("SELECT payload,principal FROM leases WHERE state!='released'"):
                binding=json.loads(encoded)['binding']
                for key in ('cpus','memory_mb'):
                    total[key]+=binding[key]
                    if owner==principal:own[key]+=binding[key]
            total['disk_reservation_bytes']=db.execute('SELECT COALESCE(SUM(bytes),0) FROM storage').fetchone()[0]
            own['disk_reservation_bytes']=db.execute('SELECT COALESCE(SUM(bytes),0) FROM storage WHERE principal=?',(principal,)).fetchone()[0]
        return {'pool':total,'principal':own,'disk_is_retained_reservation':True}

    def fits(self,principal,settings,additional=None):
        require(principal in settings['limits'],'permission-denied')
        usage=self.usage(principal);additional=additional or {key:0 for key in RESOURCES}
        require(all(usage['pool'][k]+additional[k]<=settings['capacity'][k]
                    and usage['principal'][k]+additional[k]<=settings['limits'][principal][k] for k in RESOURCES),'resource-busy')

    def acquire_locked(self,principal,lease,ttl,binding,settings,until):
        self.held();identifier(principal);uuid_text(lease)
        require(type(ttl) is int and 10<=ttl<=settings['max_ttl_seconds'])
        request={'principal':principal,'ttl':ttl,'binding':binding,'server_uuid':self.server_uuid}
        request_sha=hashlib.sha256(canonical(request).encode()).hexdigest()
        with self.db() as db:
            prior=db.execute('SELECT payload FROM leases WHERE id=?',(lease,)).fetchone()
        if prior:
            row=json.loads(prior[0]);require(row['request_sha256']==request_sha,'idempotency-conflict');return self.view(row)
        now=self.sample();require(now['utc']+ttl<=until,'permission-denied')
        with self.db() as db:
            require(not db.execute("SELECT 1 FROM leases WHERE instance=? AND state!='released'",(binding['instance_uuid'],)).fetchone(),'resource-busy')
            storage=db.execute('SELECT principal,bytes,binding FROM storage WHERE instance=?',(binding['instance_uuid'],)).fetchone()
            require(db.execute('SELECT COUNT(*) FROM leases').fetchone()[0]<65536,'storage-insufficient')
        if storage:require(storage==(principal,binding['disk_reservation_bytes'],canonical(binding)),'identity-unknown')
        additional={key:binding[key] for key in RESOURCES}
        if storage:additional['disk_reservation_bytes']=0
        self.fits(principal,settings,additional)
        row={'lease_id':lease,'instance_uuid':binding['instance_uuid'],'principal':principal,'state':'reserved',
             'binding':binding,'request_sha256':request_sha,'issued':now,'deadline_mono':now['mono']+ttl,
             'expires_utc':now['utc']+ttl,'stop_request':None,'stop_operation_id':None,'stop_response':None}
        with self.db(write=True) as db:
            if not storage:db.execute('INSERT INTO storage VALUES(?,?,?,?)',(binding['instance_uuid'],principal,binding['disk_reservation_bytes'],canonical(binding)))
            db.execute('INSERT INTO leases VALUES(?,?,?,?,?)',(lease,binding['instance_uuid'],principal,'reserved',canonical(row)))
        return self.view(row)

    def admit_locked(self,principal,lease,binding,settings):
        self.held();row=self.get(lease)
        require(row['principal']==principal and row['instance_uuid']==binding['instance_uuid'],'permission-denied')
        require(row['binding']==binding,'identity-unknown')
        require(row['state']=='reserved' and self.time_state(row)=='active','state-conflict')
        self.fits(principal,settings);return row

    def renew_locked(self,principal,lease,renewal,ttl,binding,settings,until):
        self.held();uuid_text(renewal)
        require(type(ttl) is int and 10<=ttl<=settings['max_ttl_seconds'])
        request_sha=hashlib.sha256(canonical({'lease':lease,'principal':principal,'ttl':ttl,'binding':binding}).encode()).hexdigest()
        with self.db() as db:prior=db.execute('SELECT digest,payload FROM renewals WHERE id=?',(renewal,)).fetchone()
        if prior:
            require(prior[0]==request_sha,'idempotency-conflict')
            row=self.get(lease);return dict(self.view(row),renewal_id=renewal,already_recorded=True)
        row=self.admit_locked(principal,lease,binding,settings);now=self.sample()
        require(now['utc']+ttl<=until,'permission-denied')
        # 续租只能延长，不能意外缩短正在运行实验的时限。
        row['deadline_mono']=max(row['deadline_mono'],now['mono']+ttl)
        row['expires_utc']=max(row['expires_utc'],now['utc']+ttl)
        result=dict(self.view(row),renewal_id=renewal,already_recorded=False)
        with self.db(write=True) as db:
            db.execute('UPDATE leases SET payload=? WHERE id=?',(canonical(row),lease))
            db.execute('INSERT INTO renewals VALUES(?,?,?)',(renewal,request_sha,canonical(result)))
        return result
