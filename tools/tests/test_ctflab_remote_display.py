"""SSH会话内显示认证/逐次撤销/绑定/未知不重放；全用假RFB/假SSH，不启动VM或桌面。"""
from datetime import datetime,timezone
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError
from ctflab_remote import Runner,PROTOCOL
from ctflab_remote_display import DisplayPool,RemoteRFB,scaled_frame,settings


class Client:
    def __init__(self):self.width=1200;self.height=900;self.pixels=bytearray(b'\x11\x22\x33'*self.width*self.height);self.calls=[];self.closed=False
    def frame(self):self.calls.append(('frame',));return b'not-forwarded-original-frame'
    def key(self,*args):self.calls.append(('key',*args))
    def pointer(self,*args):self.calls.append(('pointer',*args))
    def close(self):self.closed=True


class DisplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        self.server=str(uuid.uuid4());self.instance=str(uuid.uuid4());self.lease=str(uuid.uuid4());self.identity=str(uuid.uuid4())
        resource={'cpus':1,'memory_mb':128,'disk_reservation_bytes':1024}
        self.policy={'schema':1,'server_uuid':self.server,'display':{'max_sessions':2,'max_pixels':65536,'lease_required':True},
            'principals':{name:{'role':role,'instances':[self.instance],'expires':'2099-01-01T00:00:00Z'} for name,role in [('alice','student'),('bob','student'),('teacher','teacher')]},
            'instances':{self.instance:{'root':str(self.root/'instance'),'owner':'alice'}},
            'leases':{'root':str(self.root/'pool'),'capacity':resource,'limits':{'alice':resource},
                'instances':{self.instance:{'disk_reservation_bytes':1024,'expiry_action':'notify'}},'max_ttl_seconds':100}}
        self.binding='a'*64;self.allowed=True;self.clients=[];self.endpoint_calls=[]
        def endpoint(policy,instance,node,*,connect=False):
            self.endpoint_calls.append((instance,node,connect))
            if node!='client':raise ContractError('permission-denied')
            client=None
            if connect:client=Client();self.clients.append(client)
            return self.binding,client
        def lease_check(policy,instance,lease):
            if not self.allowed or lease!=self.lease:raise ContractError('permission-denied')
        self.pool=DisplayPool(endpoint_factory=endpoint,lease_check=lease_check,now=lambda:datetime(2026,10,26,tzinfo=timezone.utc))
        self.addCleanup(self.pool.close)
    def runner(self,principal='alice'):return Runner(self.policy,principal,display_pool=self.pool)
    def request(self,action,parameters,principal='alice'):
        return self.runner(principal).exchange({'protocol':PROTOCOL,'version':1,'server_uuid':self.server,'request_id':str(uuid.uuid4()),
            'action':action,'parameters':parameters})['result']
    def opened(self):
        return self.request('display-open',{'instance_uuid':self.instance,'session_id':self.identity,'node':'client','lease_id':self.lease})
    def params(self,sequence=1,**extra):return dict(extra,instance_uuid=self.instance,session_id=self.identity,sequence=sequence)
    def test_explicit_capability_ssh_pool_and_active_lease_are_required(self):
        self.assertTrue(self.request('handshake',{})['display_tunnel'])
        no_pool=Runner(self.policy,'alice').exchange({'protocol':PROTOCOL,'version':1,'server_uuid':self.server,'request_id':str(uuid.uuid4()),'action':'handshake','parameters':{}})['result']
        self.assertFalse(no_pool['display_tunnel']);self.allowed=False
        with self.assertRaises(ContractError):self.opened()
        self.assertEqual(self.clients,[])
    def test_scaled_rgb_frame_and_pointer_mapping_keep_bound_dimensions(self):
        result=self.opened();self.assertFalse(result['clipboard']);self.assertFalse(result['file_transfer'])
        result=self.request('display-frame',self.params());self.assertEqual((result['width'],result['height']),(240,180))
        self.request('display-pointer',self.params(2,x=2,y=3,mask=1))
        self.assertEqual(self.clients[0].calls[-1],('pointer',10,15,1))
        self.request('display-key',self.params(3,keysym=65,down=True));self.assertEqual(self.clients[0].calls[-1],('key',65,True))
        self.assertFalse(self.request('display-close',self.params(4))['vm_stopped']);self.assertTrue(self.clients[0].closed)
    def test_cross_owner_expired_account_and_bad_lease_never_open_socket(self):
        params={'instance_uuid':self.instance,'session_id':self.identity,'node':'client','lease_id':self.lease}
        with self.assertRaises(ContractError):self.request('display-open',params,'bob')
        self.policy['principals']['alice']['expires']='2000-01-01T00:00:00Z'
        with self.assertRaises(ContractError):self.opened()
        self.assertEqual(self.clients,[])
    def test_policy_revocation_or_current_lease_expiry_closes_without_forwarding_input(self):
        self.opened();self.allowed=False
        with self.assertRaises(ContractError):self.request('display-key',self.params(keysym=65,down=True))
        self.assertEqual(self.clients[0].calls,[]);self.assertTrue(self.clients[0].closed)
        self.allowed=True;self.identity=str(uuid.uuid4());self.opened();self.policy['principals']['alice']['instances']=[]
        with self.assertRaises(ContractError):self.request('display-frame',self.params())
        self.assertTrue(self.clients[-1].closed)
    def test_process_generation_or_profile_binding_change_refuses_before_frame(self):
        self.opened();self.binding='b'*64
        with self.assertRaises(ContractError):self.request('display-frame',self.params())
        self.assertTrue(self.clients[0].closed);self.assertEqual(self.clients[0].calls,[])
    def test_duplicate_sequence_and_extra_command_fields_do_not_replay_keys(self):
        self.opened();self.request('display-key',self.params(keysym=65,down=True))
        with self.assertRaises(ContractError):self.request('display-key',self.params(keysym=65,down=True))
        self.assertEqual(self.clients[0].calls,[('key',65,True)])
        with self.assertRaises(ContractError):self.request('display-open',{'instance_uuid':self.instance,'session_id':str(uuid.uuid4()),'node':'client','lease_id':self.lease,'host':'8.8.8.8'})
    def test_close_after_expiry_only_closes_owned_display_and_does_not_stop_vm(self):
        self.opened();self.allowed=False
        result=self.request('display-close',self.params());self.assertEqual(result['state'],'display-closed')
        self.assertFalse(result['vm_stopped']);self.assertEqual(self.clients[0].calls,[])
    def test_capacity_bounds_and_open_tombstone_prevent_replaying_same_session(self):
        self.opened();self.request('display-close',self.params())
        with self.assertRaises(ContractError):self.opened()
        self.assertEqual(len(self.clients),1)
        for change in ({'max_sessions':5},{'max_pixels':786433},{'lease_required':False},{'max_sessions':True}):
            value=dict(self.policy['display'],**change)
            with self.assertRaises(ContractError):settings(value)
    def test_full_remote_client_uses_same_ssh_session_revalidates_target_and_never_retries_unknown_input(self):
        outer=self;calls=[]
        class Session:
            def __init__(inner,config):inner.closed=False
            def request(inner,action,parameters):
                calls.append(action);reply=outer.request(action,parameters)
                if action=='display-key':raise OSError('fixture reply lost after one key')
                return reply
            def close(inner,**kw):inner.closed=True;outer.pool.close()
        with patch('ctflab_desktop_remote.target',return_value=({'server_uuid':self.server},'a'*64)):
            remote=RemoteRFB(self.root/'config','a'*64,self.instance,'client',self.lease,session_factory=Session)
            image=remote.frame();self.assertTrue(image.startswith(b'P6\n240 180\n255\n'))
            with self.assertRaises(OSError):remote.key(65,True)
            self.assertTrue(remote.closed);self.assertEqual(calls.count('display-key'),1)
            self.assertEqual(self.clients[0].calls[-1],('key',65,True));remote.close()
    def test_rgb_memory_and_dimensions_mismatch_refuse(self):
        client=Client();client.pixels=bytearray(b'x')
        with self.assertRaises(ContractError):scaled_frame(client,65536)
        client.width=True
        with self.assertRaises(ContractError):scaled_frame(client,65536)


if __name__=='__main__':unittest.main()
