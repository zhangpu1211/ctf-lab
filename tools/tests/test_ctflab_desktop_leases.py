"""桌面租约变更经假SSH进入真实Runner/租约账本；不执行真实VM或到期调度。"""
import copy
from pathlib import Path
import sys
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_ctflab_remote_leases as lease_tests
from ctflab_contract import canonical,ContractError
from ctflab_desktop_remote import dispatch,target
from ctflab_generation_store import digest
from ctflab_remote import Runner,PROTOCOL


class DesktopLeaseTests(unittest.TestCase):
    setUp=lease_tests.LeaseTests.setUp
    configured_lease=lease_tests.LeaseTests.configured
    make_manager=lease_tests.LeaseTests.make_manager
    write_policy=lease_tests.LeaseTests.write_policy
    request=lease_tests.LeaseTests.request
    operate=lease_tests.LeaseTests.operate

    def configured(self,expiry='notify',principal='alice'):
        self.configured_lease(expiry);self.messages=[];self.sessions=0;self.closed=0;self.drop=None
        self.transform=lambda action,response:response
        self.runner=Runner(self.policy,principal,lease_manager=self.make_manager(principal),policy_path=self.policy_path)
        ssh=self.root/'ssh';ssh.write_bytes(b'not executed')
        key=self.root/'identity';key.write_text('fixture');key.chmod(0o600)
        known=self.root/'known';known.write_text('fixture');known.chmod(0o600)
        self.config={'schema':1,'host':'fixture.test','port':22,'user':'student','ssh':str(ssh),
            'identity':str(key),'known_hosts':str(known),'known_hosts_sha256':digest(known),'server_uuid':self.server}
        self.path=self.root/'client.json';self.path.write_text(canonical(self.config));self.path.chmod(0o600)
        self.fingerprint=target(self.path)[1];owner=self
        class Session:
            def __init__(self,config,timeout):owner.sessions+=1
            def __enter__(self):return self
            def __exit__(self,*args):owner.closed+=1
            def request(self,action,parameters):
                owner.messages.append((action,copy.deepcopy(parameters)))
                result=owner.runner.exchange({'protocol':PROTOCOL,'version':1,'server_uuid':owner.server,
                    'request_id':str(uuid.uuid4()),'action':action,'parameters':parameters})
                if owner.drop==action:owner.drop=None;raise OSError('fixture response lost after commit')
                return owner.transform(action,result)['result']
        self.session=Session
    def call(self,action,**params):
        return dispatch(self.path,{'action':action,'target':self.fingerprint,'instance_uuid':self.instance,**params},session=self.session)['result']
    def acquire(self,ttl=60,expiry='notify'):
        return self.call('lease-acquire',lease_id=self.lease,ttl_seconds=ttl,expiry_action=expiry)

    def test_status_supplies_owner_limits_and_fixed_expiry_without_mutation(self):
        self.configured();result=self.call('lease-status')
        self.assertEqual(result['max_ttl_seconds'],3600);self.assertTrue(result['owner_actions'])
        self.assertEqual(result['expiry_action'],'notify');self.assertEqual(result['leases'],[])
        self.assertEqual(self.driver.calls,[]);self.assertEqual(self.jobs,[])

    def test_acquire_renew_replay_and_release_keep_source_and_disk_reference(self):
        self.configured();before=digest(self.base);first=self.acquire();self.assertEqual(first['state'],'active')
        self.clock.advance(5);renewal=str(uuid.uuid4())
        result=self.call('lease-renew',lease_id=self.lease,renewal_id=renewal,ttl_seconds=120)
        expiry=result['expires_at'];self.clock.advance(10)
        replay=self.call('lease-renew',lease_id=self.lease,renewal_id=renewal,ttl_seconds=120)
        self.assertTrue(replay['already_recorded']);self.assertEqual(replay['expires_at'],expiry)
        retained=self.manager.pool.usage('alice')['principal']['disk_reservation_bytes']
        self.assertEqual(self.call('lease-release',lease_id=self.lease)['state'],'released')
        self.assertEqual(self.call('lease-release',lease_id=self.lease)['state'],'released')
        self.assertEqual(self.manager.pool.usage('alice')['principal']['disk_reservation_bytes'],retained)
        self.assertEqual(self.manager.pool.usage('alice')['principal']['cpus'],0)
        self.assertEqual(digest(self.base),before);self.assertEqual(self.driver.calls,[])

    def test_lost_acquire_reply_never_replays_until_explicit_same_identifier(self):
        self.configured();self.drop='lease-acquire'
        with self.assertRaises(OSError):self.acquire()
        expires=self.manager.pool.get(self.lease)['expires_utc'];self.clock.advance(5)
        self.assertEqual(len([a for a,_ in self.messages if a=='lease-acquire']),1)
        self.acquire();self.assertEqual(self.manager.pool.get(self.lease)['expires_utc'],expires)
        with self.manager.pool.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM leases').fetchone()[0],1)
        self.assertEqual(self.driver.calls,[]);self.assertEqual(self.sessions,self.closed)

    def test_teacher_scope_cannot_acquire_renew_or_release_owner_lease(self):
        self.configured(principal='teacher');self.assertFalse(self.call('lease-status')['owner_actions'])
        with self.assertRaises(ContractError):self.acquire()
        self.assertEqual(self.driver.calls,[]);self.assertEqual(self.jobs,[])

    def test_explicit_stop_policy_acknowledgement_never_installs_or_runs_scheduler(self):
        self.configured('request-stop')
        with self.assertRaises(ContractError):self.acquire(expiry='notify')
        result=self.acquire(expiry='request-stop');self.assertEqual(result['expiry_action'],'request-stop')
        self.clock.advance(61);status=self.call('lease-status');self.assertFalse(status['scheduler_installed'])
        self.assertEqual(self.jobs,[]);self.assertEqual(self.driver.calls,[])
        self.assertGreater(status['usage']['principal']['cpus'],0)

    def test_invalid_ttl_identifier_and_extra_host_fields_never_open_transport(self):
        self.configured()
        for ttl in (True,0,86401,'60'):
            with self.assertRaises(ContractError):self.acquire(ttl=ttl)
        with self.assertRaises(ContractError):self.call('lease-release',lease_id='../secret')
        with self.assertRaises(ContractError):self.call('lease-acquire',lease_id=self.lease,ttl_seconds=60,expiry_action='notify',root='/secret')
        self.assertEqual(self.sessions,0)

    def test_release_running_instance_never_stops_it_or_frees_quota(self):
        self.configured();self.acquire();self.operate('prepare');self.operate('start');before=list(self.driver.calls)
        with self.assertRaises(ContractError):self.call('lease-release',lease_id=self.lease)
        self.assertEqual(self.driver.calls,before);self.assertGreater(self.manager.pool.usage('alice')['principal']['cpus'],0)

    def test_mismatched_renewal_reply_is_unknown_and_explicit_retry_does_not_extend_twice(self):
        self.configured();self.acquire();renewal=str(uuid.uuid4())
        def wrong(action,response):
            if action=='lease-renew':response['result']['renewal_id']=str(uuid.uuid4())
            return response
        self.transform=wrong
        with self.assertRaises(ContractError):self.call('lease-renew',lease_id=self.lease,renewal_id=renewal,ttl_seconds=120)
        expires=self.manager.pool.get(self.lease)['expires_utc'];self.clock.advance(5)
        self.transform=lambda action,response:response
        result=self.call('lease-renew',lease_id=self.lease,renewal_id=renewal,ttl_seconds=120)
        self.assertTrue(result['already_recorded']);self.assertEqual(self.manager.pool.get(self.lease)['expires_utc'],expires)

    def test_policy_changed_to_stop_cannot_use_old_notify_acknowledgement(self):
        self.configured();self.policy['leases']['instances'][self.instance]['expiry_action']='request-stop';self.write_policy()
        with self.assertRaises(ContractError):self.acquire(expiry='notify')
        with self.manager.pool.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM leases').fetchone()[0],0)
        self.assertEqual(self.driver.calls,[])


if __name__=='__main__':unittest.main()
