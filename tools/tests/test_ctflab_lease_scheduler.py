"""调度循环与只读默认值，真实临时账本+假时钟/到期处理；不运行实际到期调度。"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import canonical,ContractError
from ctflab_lease_store import LeaseStore
from ctflab_lease_scheduler import LeaseScheduler,main
from test_ctflab_remote_leases import Clock


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        self.instance=str(uuid.uuid4());self.server=str(uuid.uuid4());self.clock=Clock();self.calls=[]
        resources={'cpus':1,'memory_mb':128,'disk_reservation_bytes':1024}
        self.policy={'schema':1,'server_uuid':self.server,
            'principals':{'alice':{'role':'student','instances':[self.instance],'expires':'2099-01-01T00:00:00Z'}},
            'instances':{self.instance:{'root':str(self.root/'instance'),'owner':'alice'}},
            'leases':{'root':str(self.root/'leases'),'capacity':resources,'limits':{'alice':resources},
                'instances':{self.instance:{'disk_reservation_bytes':1024,'expiry_action':'notify'}},'max_ttl_seconds':100}}
        self.path=self.root/'policy.json';self.path.write_text(canonical(self.policy));self.path.chmod(0o600)
        self.pool=LeaseStore.create(self.root/'leases',self.server,clock=self.clock)
        self.lease=str(uuid.uuid4());self.add(self.lease,1000)
        outer=self
        class Manager:
            def __init__(inner,*a,**kw):pass
            def require_policy(inner,expected):
                if hashlib.sha256(outer.path.read_bytes()).hexdigest()!=expected:raise ContractError('permission-denied')
            def expiry(inner,identity):outer.calls.append(identity);return {'state':'attention'}
        self.scheduler=LeaseScheduler(self.path,pool_factory=lambda root,server:LeaseStore(root,server,clock=self.clock),manager_factory=Manager)
    def add(self,identity,deadline):
        # 各行使用不同实例避免held_instance唯一约束，测试只覆盖调度选择，不派发资源动作。
        instance=self.instance if identity==self.lease else str(uuid.uuid4())
        payload={'lease_id':identity,'instance_uuid':instance,'principal':'alice','state':'held',
            'issued':self.clock.sample(),'deadline_mono':deadline,'binding':{'expiry_action':'notify','instance_uuid':instance}}
        with self.pool.db(write=True) as db:db.execute('INSERT INTO leases VALUES(?,?,?,?,?)',(identity,instance,'alice','held',canonical(payload)))
    def test_default_preview_is_readonly_and_never_calls_expiry_or_creates_gate(self):
        before=(self.pool.root/'leases.sqlite3').read_bytes();self.clock.advance(1001)
        result=self.scheduler.tick()
        self.assertEqual(result['state'],'scheduler-preview');self.assertFalse(result['expiry_executed'])
        self.assertEqual(self.calls,[]);self.assertEqual((self.pool.root/'leases.sqlite3').read_bytes(),before)
        self.assertFalse((self.pool.root/'scheduler.lock').exists())
    def test_explicit_initialization_only_creates_gate_and_duplicate_refuses(self):
        result=self.scheduler.initialize();self.assertFalse(result['expiry_executed']);self.assertEqual(self.calls,[])
        with self.assertRaises(FileExistsError):self.scheduler.initialize()
    def test_active_skipped_expired_fake_handler_runs_under_single_gate(self):
        self.scheduler.initialize()
        with patch('ctflab_lease_scheduler.sys.platform','linux'):
            self.scheduler.tick(execute=True);self.assertEqual(self.calls,[])
            self.clock.advance(1001);result=self.scheduler.tick(execute=True)
            self.assertEqual(self.calls,[self.lease]);self.assertTrue(result['expiry_executed'])
            with self.scheduler.gate(self.policy):
                with self.assertRaises((BlockingIOError,ContractError)):self.scheduler.tick(execute=True)
    def test_round_robin_bounds_work_and_does_not_starve_later_records(self):
        identities=[self.lease]+[str(uuid.uuid4()) for _ in range(4)]
        for identity in identities[1:]:self.add(identity,0)
        observed=[]
        for _ in range(5):observed.append(self.scheduler.tick(limit=1)['leases'][0]['lease_id'])
        self.assertEqual(set(observed),set(identities));self.assertEqual(len(observed),5)
    def test_clock_uncertainty_is_reported_and_only_fake_manager_invoked(self):
        self.clock.boot=str(uuid.uuid4());self.assertEqual(self.scheduler.tick()['leases'][0]['time_state'],'clock-uncertain')
        self.assertEqual(self.calls,[])
    def test_loop_wait_uses_requested_interval_and_reloads_policy(self):
        self.scheduler.initialize();self.clock.advance(1001);waits=[]
        class Stop:
            def is_set(inner):return False
            def wait(inner,interval):waits.append(interval);return True
        with patch('ctflab_lease_scheduler.sys.platform','linux'):
            results=list(self.scheduler.loop(Stop(),interval=10,limit=1))
        self.assertEqual(waits,[10]);self.assertEqual(len(results),1);self.assertEqual(self.calls,[self.lease])
    def test_no_execute_cli_cannot_start_once_and_invalid_bounds_refuse(self):
        self.assertEqual(main(['once','--policy',str(self.path)]),2)
        for limit in (0,101,True):
            with self.assertRaises(ContractError):self.scheduler.tick(limit=limit)
        self.assertEqual(self.calls,[])


if __name__=='__main__':unittest.main()
