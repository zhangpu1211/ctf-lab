"""远程封存证据窄通道与本机暂停续传；真实临时文件/账本，SSH及VM均替身。"""
import base64
from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
from ctflab_remote_evidence import publish,RemoteEvidence,CHUNK
from ctflab_client_evidence import ClientEvidence
from ctflab_client_store import ClientStore
from ctflab_remote import Runner,PROTOCOL
import test_ctflab_generation_store as fixtures


class EvidenceTests(unittest.TestCase):
    setUp=fixtures.GenerationTests.setUp
    def configured(self):
        self.data=b'opaque-pcap-fixture'*7000;self.sha=hashlib.sha256(self.data).hexdigest();self.export_id=str(uuid.uuid4());self.server=str(uuid.uuid4())
        self.source=self.root/'export-source';self.source.mkdir(mode=0o700)
        capture=self.source/'capture-001.pcap';capture.write_bytes(self.data);capture.chmod(0o600)
        manifest={'schema':1,'kind':'local-evidence-export','binding':{'instance_uuid':self.instance,'generation':1,'network_id':'outer'},
            'files':{'capture-001.pcap':self.sha}}
        path=self.source/'MANIFEST.json';path.write_text(canonical(manifest));path.chmod(0o600)
        self.manifest_sha=hashlib.sha256(path.read_bytes()).hexdigest()
        self.policy={'schema':1,'server_uuid':self.server,'evidence':{'max_exports':128,'max_bytes':1024**3},
            'principals':{name:{'role':role,'instances':[self.instance],'expires':'2099-01-01T00:00:00Z'} for name,role in [('alice','student'),('bob','student'),('teacher','teacher')]},
            'instances':{self.instance:{'root':str(self.store.root),'owner':'alice'}}}
        publish(self.store.root,self.source,self.export_id,self.manifest_sha)
        self.remote=RemoteEvidence(self.policy,'alice');self.target_id=str(uuid.uuid4());self.download_id=str(uuid.uuid4())
        self.client=ClientStore(self.root/'client');self.client.initialize();config=self.root/'client-config.json'
        config.write_text(canonical({'server_uuid':self.server}));config.chmod(0o600)
        self.client.entry=lambda identity:(str(config),'a'*64)
        self.calls=[];self.on_chunk=None;outer=self
        class Session:
            def __init__(inner,config,**kw):inner.cancel_requested=kw.get('cancel_requested')
            def request(inner,action,params):
                outer.calls.append(action)
                result=Runner(outer.policy,'alice').exchange({'protocol':PROTOCOL,'version':1,'server_uuid':outer.server,
                    'request_id':str(uuid.uuid4()),'action':action,'parameters':params})['result']
                if action=='evidence-read' and outer.on_chunk:outer.on_chunk(result)
                return result
            def __enter__(inner):return inner
            def __exit__(inner,*a):pass
        self.downloader=ClientEvidence(self.client,session_factory=Session)
        self.payload={'instance_uuid':self.instance,'export_id':self.export_id,'file':'capture-001.pcap','sha256':self.sha,'size':len(self.data)}
    def params(self,**change):
        return dict(instance_uuid=self.instance,export_id=self.export_id,file='capture-001.pcap',sha256=self.sha,offset=0,**change)
    def test_publish_copies_and_freezes_evidence_without_modifying_originals_or_opening_network(self):
        self.configured();listing=self.remote.handle('evidence-list',{'instance_uuid':self.instance})
        self.assertEqual(len(listing['exports']),1);self.assertFalse(listing['automatic_transfer'])
        self.assertEqual((self.source/'capture-001.pcap').read_bytes(),self.data)
        target=self.store.root/'evidence-published'/self.export_id/'capture-001.pcap'
        self.assertEqual(target.stat().st_mode&0o777,0o400)
        with self.assertRaises(FileExistsError):publish(self.store.root,self.source,self.export_id,self.manifest_sha)
    def test_chunks_exact_offset_hash_eof_and_no_remote_path(self):
        self.configured();params=self.params();result=self.remote.handle('evidence-read',params)
        self.assertEqual(base64.b64decode(result['data']),self.data[:CHUNK]);self.assertFalse(result['eof'])
        params['offset']=len(self.data);self.assertTrue(self.remote.handle('evidence-read',params)['eof'])
        for change in ({'offset':True},{'offset':-1},{'offset':len(self.data)+1},{'file':'../ca-key.pem'},{'path':'/etc/passwd'},{'sha256':'0'*64}):
            changed=self.params();changed.update(change)
            with self.assertRaises(ContractError):self.remote.handle('evidence-read',changed)
    def test_cross_owner_expired_subject_and_wrong_instance_refuse_before_transfer(self):
        self.configured()
        with self.assertRaises(ContractError):RemoteEvidence(self.policy,'bob').handle('evidence-read',self.params())
        self.policy['principals']['alice']['expires']='2000-01-01T00:00:00Z'
        with self.assertRaises(ContractError):self.remote.handle('evidence-read',self.params())
        changed=self.params();changed['instance_uuid']=str(uuid.uuid4())
        with self.assertRaises(ContractError):self.remote.handle('evidence-read',changed)
    def test_snapshot_mutation_refuses_instead_of_reading_changed_original_or_credentials(self):
        self.configured();snapshot=self.store.root/'evidence-published'/self.export_id/'capture-001.pcap'
        snapshot.chmod(0o600);snapshot.write_bytes(b'tampered')
        with self.assertRaises(ContractError):self.remote.handle('evidence-read',self.params())
        self.assertEqual((self.source/'capture-001.pcap').read_bytes(),self.data)
    def test_client_complete_download_preserves_server_and_never_extracts_or_executes(self):
        self.configured();listing=self.downloader.listing(self.target_id,self.instance);self.assertEqual(len(listing['exports']),1)
        result=self.downloader.run(self.target_id,self.download_id,self.payload)
        self.assertEqual(result['phase'],'verified');self.assertFalse(result['content_executed'])
        self.assertEqual(Path(result['local_path']).read_bytes(),self.data)
        before=len(self.calls);again=self.downloader.run(self.target_id,self.download_id,self.payload)
        self.assertEqual(again['phase'],'verified');self.assertEqual(len(self.calls),before)
        self.assertFalse(any(action in ('submit','lease-release','lease-acquire') for action in self.calls))
    def test_client_pause_and_explicit_resume_validate_even_uncommitted_tail_without_truncating(self):
        self.configured();result=self.downloader.run(self.target_id,self.download_id,self.payload,max_chunks=1)
        self.assertEqual(result['phase'],'paused');partial=self.client.root/'evidence-downloads'/self.download_id/'capture-001.pcap.partial'
        with partial.open('ab') as stream:stream.write(self.data[CHUNK:CHUNK+13])
        result=self.downloader.resume(self.download_id)
        self.assertEqual(result['phase'],'verified');self.assertEqual(partial.read_bytes(),self.data)
    def test_cancel_from_another_client_is_reachable_without_holding_instance_operation_gate(self):
        self.configured()
        def cancel(value):
            if value['offset']==0:self.downloader.cancel(self.download_id)
        self.on_chunk=cancel;result=self.downloader.run(self.target_id,self.download_id,self.payload)
        self.assertEqual(result['phase'],'paused');self.assertEqual(result['received'],CHUNK)
        # 下载门独立，实例请求的本机协调门仍然可获取。
        with self.client.db(gate=True):pass
        self.assertFalse(any(action=='submit' for action in self.calls))
    def test_lost_read_reply_keeps_unknown_and_rebinding_or_bad_local_prefix_cannot_overwrite(self):
        self.configured()
        def lost(value):raise OSError('fixture lost reply')
        self.on_chunk=lost;result=self.downloader.run(self.target_id,self.download_id,self.payload)
        self.assertEqual(result['phase'],'unknown');self.on_chunk=None
        self.client.entry=lambda identity:(str(self.root/'client-config.json'),'b'*64)
        with self.assertRaises(ContractError):self.downloader.resume(self.download_id)
        self.client.entry=lambda identity:(str(self.root/'client-config.json'),'a'*64)
        partial=self.client.root/'evidence-downloads'/self.download_id/'capture-001.pcap.partial';partial.write_bytes(b'bad prefix')
        result=self.downloader.resume(self.download_id);self.assertEqual(result['phase'],'unknown')
        self.assertEqual(partial.read_bytes(),b'bad prefix')


if __name__=='__main__':unittest.main()
