"""签名缓存上传、权限、配额、重放和文件/数据库中断一致性。"""
import base64
from datetime import timedelta
import json
import hashlib
import os
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_ctflab_content_cache as cache_tests
from ctflab_contract import ContractError
from ctflab_remote_assets import RemoteUploads, initialize, upload_file


class UploadTests(unittest.TestCase):
    setUp = cache_tests.CacheTests.setUp
    envelope = cache_tests.CacheTests.envelope
    accept = cache_tests.CacheTests.accept

    def configured(self, *, role='student', principal='alice', quota=100000):
        self.accept(); initialize(self.cache.root)
        self.settings = {'cache_root':str(self.cache.root),'sources':[self.source],
                         'quota_bytes':quota,'max_uploads':16}
        self.uploads = RemoteUploads(self.settings,principal,role,now=lambda:self.now)
        self.upload = str(uuid.uuid4())
        return self.uploads

    def begin(self): return self.uploads.begin(self.upload,self.source,self.sha,'student')
    def chunk(self, offset, block): return self.uploads.chunk(self.upload,offset,base64.b64encode(block).decode())

    def test_complete_upload_is_verified_pinned_and_original_index_unchanged(self):
        self.configured(); self.begin(); self.chunk(0,self.data)
        value = self.uploads.finish(self.upload)
        self.assertEqual(value['state'],'verified'); self.assertFalse(value['executable'])
        self.assertEqual(self.cache.object(self.sha).read_bytes(),self.data)
        self.assertEqual(self.cache.preview_gc(),[])
        self.assertEqual(self.uploads.finish(self.upload)['state'],'verified')
        self.assertEqual(self.uploads.begin(self.upload,self.source,self.sha,'student')['state'],'verified')

    def test_incomplete_upload_cannot_be_used_or_finished(self):
        self.configured();self.begin();self.chunk(0,self.data[:100])
        with self.assertRaises(OSError): self.cache.object(self.sha)
        with self.assertRaises(ContractError): self.uploads.finish(self.upload)
        self.assertEqual(self.uploads.status(self.upload)['received'],100)

    def test_duplicate_chunk_is_idempotent_but_changed_content_or_gap_refused(self):
        self.configured();self.begin();self.chunk(0,self.data[:100])
        self.assertEqual(self.chunk(0,self.data[:100])['received'],100)
        with self.assertRaises(ContractError):self.chunk(0,b'x'*100)
        with self.assertRaises(ContractError):self.chunk(101,b'x')
        self.assertEqual(self.uploads.status(self.upload)['received'],100)

    def test_uncommitted_matching_prefix_can_be_completed_without_replaying_other_bytes(self):
        self.configured();self.begin()
        path=self.uploads.path(self.upload);path.write_bytes(self.data[:31])
        self.assertEqual(self.chunk(0,self.data[:100])['received'],100)
        self.assertEqual(path.read_bytes(),self.data[:100])
        path.write_bytes(self.data[:100]+b'wrong')
        with self.assertRaises(ContractError):self.chunk(100,self.data[100:200])
        self.assertEqual(self.uploads.status(self.upload)['received'],100)

    def test_cross_principal_and_teacher_material_are_refused(self):
        self.configured();self.begin()
        other=RemoteUploads(self.settings,'bob','student',now=lambda:self.now)
        for action in (lambda:other.status(self.upload),lambda:other.finish(self.upload),
                       lambda:other.chunk(self.upload,0,base64.b64encode(self.data).decode())):
            with self.assertRaises(ContractError):action()
        self.payload['sequence']=2;self.payload['assets'][self.sha]['audience']='teacher';self.accept()
        with self.assertRaises(ContractError):self.uploads.begin(str(uuid.uuid4()),self.source,self.sha,'teacher')
        teacher=RemoteUploads(self.settings,'teacher','teacher',now=lambda:self.now)
        self.assertEqual(teacher.begin(str(uuid.uuid4()),self.source,self.sha,'teacher')['state'],'uploading')

    def test_recipe_only_unknown_source_and_expired_index_refused(self):
        self.configured()
        with self.assertRaises(ContractError):self.uploads.begin(self.upload,'https://other.invalid/',self.sha,'student')
        self.payload['sequence']=2;self.payload['assets'][self.sha]['redistribution']='recipe-only';self.accept()
        with self.assertRaises(ContractError):self.begin()
        self.payload['sequence']=3;self.payload['assets'][self.sha]['redistribution']='allowed';self.accept()
        self.uploads.now=lambda:self.now+timedelta(days=2)
        with self.assertRaises(ContractError):self.begin()
        self.assertEqual(list((self.cache.root/'uploads').iterdir()),[])

    def test_reservation_quota_counts_incomplete_and_completed_uploads(self):
        self.configured(quota=len(self.data));self.begin()
        with self.assertRaises(ContractError):self.uploads.begin(str(uuid.uuid4()),self.source,self.sha,'student')
        self.chunk(0,self.data);self.uploads.finish(self.upload)
        with self.assertRaises(ContractError):self.uploads.begin(str(uuid.uuid4()),self.source,self.sha,'student')
        self.assertEqual(self.cache.object(self.sha).read_bytes(),self.data)

    def test_hash_failure_is_persisted_and_never_promoted(self):
        self.configured();self.begin();self.chunk(0,b'x'*len(self.data))
        self.assertEqual(self.uploads.finish(self.upload)['state'],'corrupt')
        self.assertEqual(self.uploads.status(self.upload)['state'],'corrupt')
        self.assertTrue(self.uploads.path(self.upload).exists())
        with self.assertRaises(OSError):self.cache.object(self.sha)

    def test_interruption_after_rename_keeps_reference_and_recovers_without_copying(self):
        self.configured();self.begin();self.chunk(0,self.data)
        rename=Path.rename
        def interrupted(path,target):
            result=rename(path,target)
            if path==self.uploads.path(self.upload):raise OSError('synthetic interruption after rename')
            return result
        with patch.object(Path,'rename',interrupted):
            with self.assertRaises(OSError):self.uploads.finish(self.upload)
        self.assertEqual(self.cache.preview_gc(),[])
        self.assertTrue(self.uploads.status(self.upload)['promotion_pending'])
        self.assertEqual(self.uploads.finish(self.upload)['state'],'verified')
        self.assertEqual(self.cache.object(self.sha).read_bytes(),self.data)

    def test_dangling_object_symlink_and_invalid_chunk_inputs_refused(self):
        self.configured()
        (self.cache.root/'objects'/self.sha).symlink_to(self.root/'missing')
        with self.assertRaises(ContractError):self.begin()
        (self.cache.root/'objects'/self.sha).unlink()  # 仅本测试自有链接
        self.begin()
        for offset,data in ((True,'YQ=='),(0,'%%%'),(0,base64.b64encode(b'x'*32769).decode())):
            with self.assertRaises(ContractError):self.uploads.chunk(self.upload,offset,data)

    def test_local_client_streams_and_explicit_same_id_resume(self):
        self.configured();self.begin();self.chunk(0,self.data[:100])
        source=self.root/'selected-source';source.write_bytes(self.data)
        owner=self
        class Session:
            def __init__(self,config):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def request(self,action,parameters):
                if action=='handshake':return {'asset_upload':True,'persistent_requests':True}
                return owner.uploads.handle(action,parameters)
        value=upload_file({},source,self.source,'student',self.upload,session_factory=Session)
        self.assertEqual(value['state'],'verified');self.assertFalse(value['instance_created'])
        self.assertEqual(source.read_bytes(),self.data)

    def test_runner_binds_upload_principal_and_denies_expired_new_chunks(self):
        self.configured()
        from ctflab_remote import Runner,PROTOCOL
        server=str(uuid.uuid4())
        policy={'schema':1,'server_uuid':server,'instances':{},'uploads':self.settings,
                'principals':{'alice':{'role':'student','instances':[],'expires':'2099-01-01T00:00:00Z'},
                              'bob':{'role':'student','instances':[],'expires':'2099-01-01T00:00:00Z'}}}
        def request(action,parameters):return {'protocol':PROTOCOL,'version':1,'request_id':str(uuid.uuid4()),
                    'server_uuid':server,'action':action,'parameters':parameters}
        runner=Runner(policy,'alice',now=lambda:self.now)
        capabilities=runner.exchange(request('handshake',{}))['result']
        self.assertTrue(capabilities['asset_upload'])
        runner.exchange(request('asset-begin',{'upload_id':self.upload,'source':self.source,'sha256':self.sha,'audience':'student'}))
        with self.assertRaises(ContractError):Runner(policy,'bob',now=lambda:self.now).exchange(request('asset-status',{'upload_id':self.upload}))
        policy['principals']['alice']['expires']='2000-01-01T00:00:00Z'
        self.assertEqual(runner.exchange(request('asset-status',{'upload_id':self.upload}))['result']['received'],0)
        with self.assertRaises(ContractError):runner.exchange(request('asset-chunk',{'upload_id':self.upload,'offset':0,'data':base64.b64encode(self.data).decode()}))

    def test_cached_result_is_not_reported_verified_after_object_disappears(self):
        self.configured();self.begin();self.chunk(0,self.data);self.uploads.finish(self.upload)
        (self.cache.root/'objects'/self.sha).unlink()  # 只移除测试自有对象，模拟外部损坏
        with self.assertRaises(OSError):self.begin()
        with self.assertRaises(OSError):self.uploads.status(self.upload)

    @unittest.skipIf(os.name=='nt','POSIX SSH脚本替身；不代替真实SSH部署')
    def test_client_and_runner_use_one_real_pipe_session_for_multiple_chunks(self):
        old=self.payload['assets'].pop(self.sha)
        self.data=b'fixture-large-upload'*5000;self.sha=hashlib.sha256(self.data).hexdigest()
        old['size']=len(self.data);self.payload['assets'][self.sha]=old
        self.configured(quota=len(self.data)*2)
        server=str(uuid.uuid4());policy={'schema':1,'server_uuid':server,'instances':{},'uploads':self.settings,
                'principals':{'alice':{'role':'student','instances':[],'expires':'2099-01-01T00:00:00Z'}}}
        settings=self.root/'server-policy.json';settings.write_text(json.dumps(policy));settings.chmod(0o600)
        script='''import json,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,TOOLS)
from ctflab_remote import Runner,decode
from ctflab_contract import canonical
runner=Runner(json.loads(Path(POLICY).read_text()),'alice',now=lambda:datetime.fromisoformat(NOW))
for raw in sys.stdin.buffer:
 print(canonical(runner.exchange(decode(raw.rstrip(b'\\n')))),flush=True)
'''.replace('TOOLS',repr(str(Path(__file__).resolve().parents[1]))).replace('POLICY',repr(str(settings))).replace('NOW',repr(self.now.isoformat()))
        executable=self.root/'ssh';executable.write_text('#!'+sys.executable+'\n'+script);executable.chmod(0o700)
        known=self.root/'known_hosts';known.write_text('fixture-host');known.chmod(0o600)
        key=self.root/'identity';key.write_text('fixture-key');key.chmod(0o600)
        config={'schema':1,'host':'runner.invalid','port':22,'user':'student','ssh':str(executable),
                'identity':str(key),'known_hosts':str(known),'known_hosts_sha256':hashlib.sha256(known.read_bytes()).hexdigest(),
                'server_uuid':server}
        source=self.root/'selected-data';source.write_bytes(self.data)
        result=upload_file(config,source,self.source,'student',self.upload)
        self.assertEqual(result['state'],'verified');self.assertEqual(result['received'],len(self.data))
        self.assertEqual(self.cache.object(self.sha).read_bytes(),self.data)


class SharedBudgetTests(unittest.TestCase):
    setUp = UploadTests.setUp
    envelope = UploadTests.envelope
    accept = UploadTests.accept
    configured = UploadTests.configured
    begin = UploadTests.begin
    chunk = UploadTests.chunk

    def budget(self, maximum):
        value=self.cache.budget_preview(maximum)
        self.cache.budget_apply(maximum,value['plan_sha256'])

    def test_two_principals_share_reservations_with_local_downloads(self):
        from ctflab_content_cache import ContentCache
        self.configured();self.budget(len(self.data));self.begin()
        other=RemoteUploads(self.settings,'bob','student',now=lambda:self.now)
        with self.assertRaises(ContractError):other.begin(str(uuid.uuid4()),self.source,self.sha,'student')
        value=self.cache.storage();self.assertEqual(value['reserved_bytes'],len(self.data))
        def forbidden(*args,**kwargs):self.fail('共享预约占满时不下载')
        with self.assertRaises(ContractError):ContentCache(self.cache.root).download(self.source,self.sha,opener=forbidden,now=self.now)
        self.assertEqual(len(list((self.cache.root/'uploads').iterdir())),1)
        self.chunk(0,self.data[:100]);value=self.cache.storage()
        self.assertEqual(value['payload_bytes'],100);self.assertEqual(value['committed_bytes'],len(self.data))
        self.chunk(100,self.data[100:]);self.uploads.finish(self.upload)
        value=self.cache.storage();self.assertEqual(value['reserved_bytes'],0)
        self.assertEqual(value['payload_bytes'],len(self.data))
        # 复用已核验对象不再重复占载荷，但原引用保护继续保留。
        self.assertEqual(other.begin(str(uuid.uuid4()),self.source,self.sha,'student')['state'],'verified')

    def test_uncommitted_tail_or_orphan_is_not_double_counted_or_erased(self):
        self.configured();self.budget(len(self.data));self.begin()
        path=self.uploads.path(self.upload);path.write_bytes(self.data[:90])
        self.assertEqual(self.cache.storage()['committed_bytes'],len(self.data))
        self.chunk(0,self.data[:100]);self.assertEqual(self.cache.storage()['committed_bytes'],len(self.data))
        orphan=self.cache.root/'quarantine'/'orphan';orphan.write_bytes(b'x');orphan.chmod(0o600)
        with self.assertRaises(ContractError):self.uploads.begin(str(uuid.uuid4()),self.source,self.sha,'student')
        # 外部写入会使报告超预算，但既有预约内写入不再次扫描/申请容量。
        self.chunk(100,self.data[100:])
        self.assertEqual(path.read_bytes(),self.data);self.assertEqual(orphan.read_bytes(),b'x')
        self.assertEqual(self.cache.storage()['committed_bytes'],len(self.data)+1)

    def test_budget_cannot_shrink_below_outstanding_upload(self):
        self.configured();self.begin()
        with self.assertRaises(ContractError):self.budget(len(self.data)-1)
        self.assertIsNone(self.cache.storage()['maximum_bytes'])

    def test_reserved_chunks_do_not_rescan_cache_for_each_block(self):
        self.configured();self.budget(len(self.data));self.begin()
        with patch.object(self.cache.__class__,'_usage',side_effect=AssertionError('不能逐块扫描公共缓存')):
            self.chunk(0,self.data[:100]);self.chunk(100,self.data[100:])
        self.assertEqual(self.cache.storage()['payload_bytes'],len(self.data))


if __name__=='__main__':unittest.main()
