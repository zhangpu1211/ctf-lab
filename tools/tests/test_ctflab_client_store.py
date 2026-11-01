"""客户端目标/请求持久化；真实远程租约账本、假SSH，不运行真实VM。"""
from contextlib import contextmanager
import copy
import json
import os
import subprocess
import threading
import time
from pathlib import Path
import sqlite3
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_ctflab_desktop_leases as desktop
from ctflab_client_store import ClientStore
from ctflab_contract import ContractError,canonical
from ctflab_desktop_remote import dispatch


class ClientTests(unittest.TestCase):
    setUp=desktop.DesktopLeaseTests.setUp
    configured_lease=desktop.DesktopLeaseTests.configured_lease
    make_manager=desktop.DesktopLeaseTests.make_manager
    write_policy=desktop.DesktopLeaseTests.write_policy
    request=desktop.DesktopLeaseTests.request
    operate=desktop.DesktopLeaseTests.operate
    configured_remote=desktop.DesktopLeaseTests.configured

    def configured(self):
        self.configured_remote();self.target_id=str(uuid.uuid4());self.attempt=str(uuid.uuid4())
        self.store=ClientStore(self.root/'client-state',send=lambda config,payload:dispatch(config,payload,session=self.session))
        self.store.save(self.target_id,'课堂服务器',str(self.path))
        self.payload={'action':'lease-acquire','target':self.fingerprint,'instance_uuid':self.instance,
            'lease_id':self.lease,'ttl_seconds':60,'expiry_action':'notify'}
    def test_admin_mutation_lost_reply_reopens_with_original_identity_and_sanitized_receipt(self):
        self.configured();calls=[]
        payload={'action':'course-provision','target':self.fingerprint,'offer_id':'web','instance_uuid':self.instance,'mapping_sha256':'a'*64}
        def send(config,value):
            calls.append(copy.deepcopy(value))
            if len(calls)==1:raise OSError('lost fixture reply')
            return {'target':self.fingerprint,'result':{'state':'course-instance-configured','instance_uuid':self.instance,
                'mapping_sha256':'a'*64,'automatic_start':False,'runtime_verified':False,'private_path':'/never-export'}}
        self.store.send=send
        self.assertEqual(self.store.request(self.target_id,payload,self.attempt)['client_phase'],'unknown')
        reopened=ClientStore(self.root/'client-state',send=send)
        self.assertEqual(len(calls),1)
        value=reopened.retry(self.attempt);self.assertEqual(value['client_phase'],'returned')
        self.assertEqual(calls,[payload,payload]);self.assertNotIn('private_path',value['result'])
        reopened.retry(self.attempt);self.assertEqual(len(calls),2)

    def send(self):return self.store.request(self.target_id,self.payload,self.attempt)

    def test_list_missing_store_never_creates_or_connects(self):
        root=self.root/'absent';self.assertEqual(ClientStore(root).targets()['targets'],[]);self.assertFalse(root.exists())

    def test_target_save_and_reopen_do_not_connect_or_expose_configuration_path(self):
        self.configured();reopened=ClientStore(self.store.root)
        listing=reopened.targets();self.assertEqual(listing['targets'][0]['id'],self.target_id)
        self.assertNotIn(str(self.path),canonical(listing));self.assertEqual(self.sessions,0)
        self.assertEqual(reopened.pending(self.target_id)['attempts'],[])
        with self.store.db() as db:
            with self.assertRaises(sqlite3.OperationalError):db.execute('DELETE FROM targets')

    def test_configuration_wizard_writes_private_reference_only_and_is_idempotent(self):
        self.configured();identity=str(uuid.uuid4());config={k:v for k,v in self.config.items() if k not in ('schema','known_hosts_sha256')}
        self.store.create(identity,'配置向导',config);self.store.create(identity,'配置向导',config)
        raw=(self.store.root/'configs'/(identity+'.json')).read_text()
        self.assertIn(self.config['identity'],raw);self.assertNotIn('fixture response',raw)
        self.assertEqual(len(self.store.targets()['targets']),2);self.assertEqual(self.sessions,0)
        with self.assertRaises(ContractError):self.store.create(identity,'配置向导',dict(config,user='other'))

    def test_intent_committed_before_send_and_completed_request_not_sent_twice(self):
        self.configured();original=self.store.send
        def observed(config,payload):
            pending=self.store.pending(self.target_id)['attempts'];self.assertEqual(pending[0]['phase'],'attempting')
            return original(config,payload)
        self.store.send=observed
        self.assertEqual(self.send()['client_phase'],'returned');count=self.sessions
        self.assertEqual(self.send()['client_phase'],'returned');self.assertEqual(self.sessions,count)
        self.assertEqual(self.store.pending(self.target_id)['attempts'],[]);self.assertEqual(self.driver.calls,[])

    def test_lost_reply_survives_restart_without_automatic_replay(self):
        self.configured();self.drop='lease-acquire';result=self.send();self.assertEqual(result['client_phase'],'unknown')
        expiry=self.manager.pool.get(self.lease)['expires_utc'];count=self.sessions
        reopened=ClientStore(self.store.root,send=self.store.send);reopened.targets()
        self.assertEqual(reopened.pending(self.target_id)['attempts'][0]['id'],self.attempt);self.assertEqual(self.sessions,count)
        with self.assertRaises(ContractError):reopened.request(self.target_id,self.payload,self.attempt)
        self.clock.advance(5);self.assertEqual(reopened.retry(self.attempt)['client_phase'],'returned')
        self.assertEqual(self.manager.pool.get(self.lease)['expires_utc'],expiry)

    def test_process_interruption_preserves_attempting_and_manual_retry_same_identifiers(self):
        self.configured();original=self.store.send
        def interrupted(config,payload):original(config,payload);raise KeyboardInterrupt()
        self.store.send=interrupted
        with self.assertRaises(KeyboardInterrupt):self.send()
        self.assertEqual(self.store.pending(self.target_id)['attempts'][0]['phase'],'attempting')
        expiry=self.manager.pool.get(self.lease)['expires_utc'];self.store.send=original
        self.clock.advance(5);self.store.retry(self.attempt)
        self.assertEqual(self.manager.pool.get(self.lease)['expires_utc'],expiry);self.assertEqual(self.driver.calls,[])

    def test_response_commit_failure_leaves_recoverable_original_attempt(self):
        self.configured();original=self.store.db
        class Proxy:
            def __init__(self,db):self.db=db
            def execute(self,sql,*params):
                if sql.startswith('UPDATE attempts SET phase='):raise sqlite3.OperationalError('fixture persistence failure')
                return self.db.execute(sql,*params)
        @contextmanager
        def failed(**kwargs):
            with original(**kwargs) as db:yield Proxy(db) if kwargs.get('write') else db
        with patch.object(self.store,'db',failed):
            with self.assertRaises(sqlite3.OperationalError):self.send()
        self.assertEqual(self.store.pending(self.target_id)['attempts'][0]['phase'],'attempting')
        self.store.retry(self.attempt);self.assertEqual(self.store.pending(self.target_id)['attempts'],[])

    def test_changed_payload_or_target_cannot_reuse_attempt_or_target_identifier(self):
        self.configured();self.send();changed=dict(self.payload,ttl_seconds=120)
        with self.assertRaises(ContractError):self.store.request(self.target_id,changed,self.attempt)
        with self.assertRaises(ContractError):self.store.save(self.target_id,'changed label',str(self.path))
        self.assertEqual(len([a for a,_ in self.messages if a=='lease-acquire']),1)

    def test_invalid_command_fields_are_rejected_before_persistence_or_send(self):
        self.configured();before=len(self.messages)
        for payload in (dict(self.payload,root='/secret'),dict(self.payload,ttl_seconds=True),dict(self.payload,action='shell')):
            with self.assertRaises(ContractError):self.store.request(self.target_id,payload,str(uuid.uuid4()))
        self.assertEqual(len(self.messages),before)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],0)

    def test_configuration_identity_drift_does_not_rebind_saved_target(self):
        self.configured();Path(self.config['identity']).write_text('changed')
        with self.assertRaises(ContractError):self.send()
        self.assertEqual(self.sessions,0)

    def test_global_gate_blocks_duplicate_sender_but_pending_query_stays_readonly(self):
        self.configured()
        with self.store.db(gate=True):
            with self.assertRaises(sqlite3.OperationalError):self.send()
            self.assertEqual(self.store.pending(self.target_id)['attempts'],[])
        self.assertEqual(self.sessions,0)

    def test_response_redacts_unknown_fields_and_nested_resources(self):
        self.configured();original=self.store.send
        def extra(config,payload):
            result=original(config,payload);result['result']['secret_path']='/secret';return result
        self.store.send=extra;self.send()
        with self.store.db() as db:raw=db.execute('SELECT response FROM attempts').fetchone()[0]
        self.assertNotIn('secret',raw)

    def test_corrupt_pending_payload_is_not_returned_as_recovery_data(self):
        self.configured();self.drop='lease-acquire';self.send()
        with self.store.db(write=True) as db:db.execute('UPDATE attempts SET payload=?',(canonical(dict(self.payload,path='/secret')),))
        with self.assertRaises(ContractError):self.store.pending(self.target_id)
        with self.assertRaises(ContractError):self.store.retry(self.attempt)

    def test_wizard_copies_public_known_hosts_without_changing_source_permissions(self):
        self.configured();source=Path(self.config['known_hosts']);source.chmod(0o644)
        identity=str(uuid.uuid4());config={k:v for k,v in self.config.items() if k not in ('schema','known_hosts_sha256')}
        before=source.read_bytes();self.store.create(identity,'公用主机密钥',config)
        private=self.store.root/'configs'/(identity+'.known_hosts')
        self.assertEqual(private.read_bytes(),before);self.assertEqual(source.read_bytes(),before)
        self.assertEqual(source.stat().st_mode&0o777,0o644);self.assertEqual(private.stat().st_mode&0o777,0o600)

    def test_nested_response_secret_is_not_persisted_as_resource_metadata(self):
        self.configured();original=self.store.send
        def bad(config,payload):
            value=original(config,payload);value['result']['resources']['credential']='secret';return value
        self.store.send=bad;result=self.send();self.assertEqual(result['client_phase'],'unknown')
        with self.store.db() as db:raw=db.execute('SELECT response FROM attempts').fetchone()[0]
        self.assertNotIn('secret',raw)


    def test_cancel_before_connection_start_is_a_tombstone_without_network(self):
        self.configured();identity=str(uuid.uuid4());calls=[]
        self.store.connect_send=lambda *a,**k:calls.append(a)
        value=self.store.handle({'action':'cancel-connect','id':self.target_id,'connection_id':identity})
        self.assertEqual(value['connection_phase'],'cancelled')
        result=self.store.handle({'action':'connect','id':self.target_id,'connection_id':identity})
        self.assertTrue(result['connection_cancelled']);self.assertEqual(calls,[])

    def test_connection_cancel_from_other_client_is_visible_and_late_reply_discarded(self):
        self.configured();identity=str(uuid.uuid4());events=[]
        def send(config,payload,*,cancel_requested):
            self.assertFalse(cancel_requested());events.append(payload['action'])
            other=ClientStore(self.store.root)
            other.handle({'action':'cancel-connect','id':self.target_id,'connection_id':identity})
            self.assertTrue(cancel_requested())
            return {'target':self.fingerprint,'result':{'secret':'late reply not returned or persisted'}}
        self.store.connect_send=send
        result=self.store.connect(self.target_id,identity)
        self.assertTrue(result['connection_cancelled']);self.assertNotIn('result',result)
        self.assertEqual(events,['connect'])
        with self.store.db() as db:
            self.assertNotIn('secret',canonical(db.execute('SELECT * FROM connections').fetchall()))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],0)

    def test_completed_connection_is_not_replayed_and_late_cancel_is_readonly(self):
        self.configured();identity=str(uuid.uuid4());calls=[]
        def send(*a,**k):calls.append(True);return {'target':self.fingerprint,'result':{'instances':[]}}
        self.store.connect_send=send
        self.assertEqual(self.store.connect(self.target_id,identity)['connection_phase'],'returned')
        late=self.store.handle({'action':'cancel-connect','id':self.target_id,'connection_id':identity})
        self.assertEqual(late['connection_phase'],'returned')
        with self.assertRaises(ContractError):self.store.connect(self.target_id,identity)
        self.assertEqual(len(calls),1)

    def test_crashed_connection_is_not_automatically_resent_after_reopen(self):
        self.configured();identity=str(uuid.uuid4())
        def crashed(*a,**k):raise KeyboardInterrupt()
        self.store.connect_send=crashed
        with self.assertRaises(KeyboardInterrupt):self.store.connect(self.target_id,identity)
        reopened=ClientStore(self.store.root);reopened.targets()
        with self.assertRaises(ContractError):reopened.connect(self.target_id,identity)
        value=reopened.handle({'action':'cancel-connect','id':self.target_id,'connection_id':identity})
        self.assertEqual(value['connection_phase'],'cancelled')

    def test_connection_id_rebind_and_extra_cancel_fields_are_rejected(self):
        self.configured();identity=str(uuid.uuid4())
        self.store.connection_record(self.target_id,identity,cancel=True)
        other=str(uuid.uuid4());self.store.save(other,'另一个目标',str(self.path))
        with self.assertRaises(ContractError):self.store.connection_record(other,identity,cancel=True)
        with self.assertRaises(ContractError):self.store.handle({'action':'cancel-connect','id':self.target_id,'connection_id':identity,'operation':'stop'})

    def exercise_pipe_cancel(self,preview=False):
        self.configured();identity=str(uuid.uuid4());trace=self.root/'connect-actions.txt';ready=self.root/'connect-waiting'
        binary=Path(self.config['ssh'])
        binary.write_text('#!'+sys.executable+'\n'+
            'import json,sys,time\nfrom pathlib import Path\n'+
            'for line in sys.stdin:\n v=json.loads(line); action=v.pop("action");v.pop("parameters")\n'+
            ' with open('+repr(str(trace))+',"a") as stream:stream.write(action+"\\n")\n'+
            ' if action=="list":\n  Path('+repr(str(ready))+').write_text("waiting");time.sleep(10)\n'+
            ' v["result"]={"state":"compatible","contract_version":1,"role":"student"}\n print(json.dumps(v),flush=True)\n')
        binary.chmod(0o700);children=[];results=[];failures=[];original=subprocess.Popen
        def spawn(*args,**kwargs):
            process=original(*args,**kwargs);children.append(process);return process
        def connect():
            try:results.append(ClientStore(self.store.root).preview_connect(str(self.path),identity) if preview else ClientStore(self.store.root).connect(self.target_id,identity))
            except BaseException as error:failures.append(error)
        with patch('ctflab_remote.subprocess.Popen',side_effect=spawn):
            worker=threading.Thread(target=connect);worker.start()
            try:
                deadline=time.monotonic()+3
                while not ready.exists() and worker.is_alive() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(ready.exists(),failures)
                client=ClientStore(self.store.root)
                if preview:client.handle({'action':'cancel-preview-connect','config':str(self.path),'connection_id':identity})
                else:client.connection_record(self.target_id,identity,cancel=True)
                worker.join(timeout=3);self.assertFalse(worker.is_alive())
                self.assertEqual(failures,[]);self.assertTrue(results[0]['connection_cancelled'])
                self.assertEqual(trace.read_text().splitlines(),['handshake','list'])
                self.assertEqual(len(children),1);self.assertIsNotNone(children[0].poll())
            finally:
                for process in children:
                    if process.poll() is None:process.kill();process.wait(timeout=3)
                worker.join(timeout=3)

    @unittest.skipIf(os.name=='nt','POSIX固定管道替身，不代替真实SSH/Windows实测')
    def test_real_session_cancel_from_independent_registry_closes_only_owned_pipe(self):
        self.exercise_pipe_cancel()

    @unittest.skipIf(os.name=='nt','POSIX固定管道替身，不代替真实SSH/Windows实测')
    def test_manual_preview_real_session_cancel_closes_only_owned_pipe(self):
        self.exercise_pipe_cancel(preview=True)

    def test_manual_preview_cancel_before_start_does_not_send_or_save_target(self):
        self.configured();identity=str(uuid.uuid4());calls=[]
        self.store.connect_send=lambda *a,**k:calls.append(a)
        payload={'config':str(self.path),'connection_id':identity}
        self.store.handle(dict(payload,action='cancel-preview-connect'))
        self.assertTrue(self.store.handle(dict(payload,action='preview-connect'))['connection_cancelled'])
        self.assertEqual(calls,[])
        with self.store.db() as db:
            rows=db.execute('SELECT target FROM connections').fetchall()
            self.assertEqual(rows,[(self.store.preview_key(str(self.path)),)])
            self.assertNotIn(str(self.path),canonical(rows))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM targets').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0],0)

    def test_manual_preview_cancel_late_reply_discard_and_no_resource_mutation(self):
        self.configured();identity=str(uuid.uuid4());calls=[]
        def send(config,payload,*,cancel_requested):
            calls.append(payload);self.assertFalse(cancel_requested())
            ClientStore(self.store.root).handle({'action':'cancel-preview-connect','config':str(self.path),'connection_id':identity})
            self.assertTrue(cancel_requested());return {'result':{'secret':'late'}}
        self.store.connect_send=send
        response=self.store.preview_connect(str(self.path),identity)
        self.assertTrue(response['connection_cancelled']);self.assertNotIn('result',response)
        self.assertEqual(calls,[{'action':'connect'}])

    def test_manual_preview_rebinding_and_extra_fields_refuse(self):
        self.configured();identity=str(uuid.uuid4())
        payload={'action':'cancel-preview-connect','config':str(self.path),'connection_id':identity}
        self.store.handle(payload)
        for bad in (dict(payload,config=str(self.path)+'-other'),dict(payload,operation='stop'),dict(payload,config='relative.json')):
            with self.assertRaises(ContractError):self.store.handle(bad)
        with self.assertRaises(ContractError):self.store.connection_record(self.target_id,identity,cancel=True)

    def test_manual_preview_can_cancel_after_config_disappears_and_cannot_replay_returned(self):
        self.configured();identity=str(uuid.uuid4());calls=[]
        self.store.connect_send=lambda *a,**k:(calls.append(a) or {'target':self.fingerprint,'result':{'instances':[]}})
        self.assertEqual(self.store.preview_connect(str(self.path),identity)['connection_phase'],'returned')
        with self.assertRaises(ContractError):self.store.preview_connect(str(self.path),identity)
        self.path.unlink()
        result=self.store.handle({'action':'cancel-preview-connect','config':str(self.path),'connection_id':identity})
        self.assertEqual(result['connection_phase'],'returned');self.assertEqual(len(calls),1)

    def test_remote_display_request_uses_saved_target_and_fixed_fields_without_vm_mutation(self):
        self.configured();calls=[];self.store.display_spawn=lambda *a:calls.append(a)
        value={'action':'display','id':self.target_id,'instance_uuid':self.instance,'node':'client','lease_id':self.lease}
        response=self.store.handle(value)
        self.assertEqual(response['state'],'display-window-requested');self.assertFalse(response['remote_connection_verified'])
        self.assertFalse(response['vm_stopped']);self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1:],(self.instance,'client',self.lease))
        for bad in (dict(value,node='../other'),dict(value,command='shell'),dict(value,lease_id='invalid')):
            with self.assertRaises(ContractError):self.store.handle(bad)
        self.assertEqual(len(calls),1)

    def test_remote_display_refuses_saved_target_identity_drift_before_spawning(self):
        self.configured();calls=[];self.store.display_spawn=lambda *a:calls.append(a)
        self.path.write_text(self.path.read_text()+' ')
        # 空白不改变配置语义；身份文件实际漂移必须拒绝。
        Path(self.config['identity']).write_text('changed identity')
        with self.assertRaises(ContractError):self.store.handle({'action':'display','id':self.target_id,
            'instance_uuid':self.instance,'node':'client','lease_id':self.lease})
        self.assertEqual(calls,[])

    def test_cancel_callback_cannot_be_attached_to_resource_mutation(self):
        self.configured();before=self.sessions
        with self.assertRaises(ContractError):dispatch(self.path,self.payload,session=self.session,cancel_requested=lambda:True)
        self.assertEqual(self.sessions,before)


if __name__=='__main__':unittest.main()
