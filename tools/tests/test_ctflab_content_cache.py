"""签名、断点、许可和回收竞态；HTTPS使用内存响应，不访问真实内容源。"""
import base64
from datetime import datetime,timezone,timedelta
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
from ctflab_content_cache import ContentCache,verify_index


class CacheTests(unittest.TestCase):
    def setUp(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError:self.skipTest('签名依赖缺失')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.cache=ContentCache.create(self.root/'cache')
        self.key=Ed25519PrivateKey.generate()
        self.keys={'main':self.key.public_key().public_bytes_raw().hex()}
        self.data=b'course-fixture'*100
        self.sha=hashlib.sha256(self.data).hexdigest()
        self.source='https://example.invalid/courses/'
        self.now=datetime(2026,10,24,tzinfo=timezone.utc)
        self.payload={'schema':1,'sequence':1,'expires':(self.now+timedelta(days=1)).isoformat(),
                      'source':self.source,'assets':{self.sha:{'path':'assets/linux.qcow2','size':len(self.data),
                      'redistribution':'allowed','audience':'student'}}}

    def envelope(self):
        return {'key_id':'main','payload':self.payload,
                'signature':base64.b64encode(self.key.sign(canonical(self.payload).encode())).decode()}

    def accept(self):return self.cache.accept(self.envelope(),self.keys,self.source,now=self.now)

    def opener(self,request,timeout):
        offset=int(request.get_header('Range','bytes=0-').split('=')[1].split('-')[0])
        raw=self.data[offset:]
        class Response(io.BytesIO):
            status=206 if offset else 200
            headers={'Content-Length':str(len(raw))}
            if offset:headers['Content-Range']=f'bytes {offset}-{len(self.data)-1}/{len(self.data)}'
            def geturl(inner):return request.full_url
        return Response(raw)

    def download(self,**kwargs):return self.cache.download(self.source,self.sha,opener=kwargs.get('opener',self.opener),now=self.now)

    def test_signed_download_and_offline_object(self):
        self.accept();path=self.download()
        self.assertEqual(path.read_bytes(),self.data)
        self.assertEqual(self.cache.object(self.sha),path)

    def test_signature_tamper_unknown_key_and_source_change(self):
        value=self.envelope();value['payload']['sequence']=2
        with self.assertRaises(ContractError):verify_index(value,self.keys,self.source,now=self.now)
        value=self.envelope();value['key_id']='unknown'
        with self.assertRaises(ContractError):verify_index(value,self.keys,self.source,now=self.now)
        with self.assertRaises(ContractError):verify_index(self.envelope(),self.keys,'https://other.invalid/',now=self.now)

    def test_expiry_rollback_and_same_sequence_changed_body(self):
        self.accept();self.payload['sequence']=2;self.accept()
        self.payload['sequence']=1
        with self.assertRaises(ContractError):self.accept()
        self.payload['sequence']=2;self.payload['expires']=(self.now+timedelta(days=2)).isoformat()
        with self.assertRaises(ContractError):self.accept()
        self.payload['expires']=self.now.isoformat()
        with self.assertRaises(ContractError):self.accept()

    def test_partial_resume_validated_and_promoted(self):
        self.accept();part=self.cache.root/'partial'/self.sha
        part.write_bytes(self.data[:101]);part.chmod(0o600)
        self.assertEqual(self.download().read_bytes(),self.data)
        self.assertFalse(part.exists())

    def test_server_ignores_range_preserves_partial(self):
        self.accept();part=self.cache.root/'partial'/self.sha
        part.write_bytes(self.data[:101]);part.chmod(0o600)
        def opener(req,timeout):
            response=self.opener(req,timeout);response.status=200;return response
        with self.assertRaises(ContractError):self.download(opener=opener)
        self.assertEqual(part.read_bytes(),self.data[:101])

    def test_hash_mismatch_quarantined_not_installed(self):
        self.accept();self.data=b'x'*len(self.data)
        with self.assertRaises(ContractError):self.download()
        self.assertFalse((self.cache.root/'objects'/self.sha).exists())
        self.assertEqual(len(list((self.cache.root/'quarantine').iterdir())),1)

    def test_teacher_and_recipe_not_student_downloads(self):
        self.payload['assets'][self.sha]['audience']='teacher';self.accept()
        with self.assertRaises(ContractError):self.download()
        self.payload['sequence']=2;self.payload['assets'][self.sha].update(audience='student',redistribution='recipe-only');self.accept()
        with self.assertRaises(ContractError):self.download()

    def test_expired_index_does_not_remove_installed_object(self):
        self.accept();path=self.download()
        self.assertEqual(self.cache.download(self.source,self.sha,now=self.now+timedelta(days=9)),path)

    def test_new_reference_invalidates_gc_preview(self):
        self.accept();self.download();preview=self.cache.preview_gc()
        self.cache.pin('active-instance',self.sha)
        with self.assertRaises(ContractError):self.cache.collect(preview)
        self.assertTrue(self.cache.object(self.sha).exists())
        self.assertEqual(self.cache.preview_gc(),[])

    def test_gc_object_change_refused_then_explicit_unpin_and_collect(self):
        self.accept();path=self.download();self.cache.pin('evidence',self.sha)
        self.assertEqual(self.cache.preview_gc(),[])
        self.cache.unpin('evidence',self.sha);preview=self.cache.preview_gc()
        path.write_bytes(b'changed')
        with self.assertRaises(ContractError):self.cache.collect(preview)
        path.write_bytes(self.data);preview=self.cache.preview_gc()
        self.assertEqual(self.cache.collect(preview)[0]['state'],'removed')
        self.assertFalse(path.exists())
        self.assertEqual(len(list(self.cache.root.glob('gc-*.result.json'))),1)

    def test_redirect_and_encoded_response_refused_before_writing(self):
        self.accept()
        def opener(req,timeout):
            response=self.opener(req,timeout);response.geturl=lambda:'https://other.invalid/data';return response
        with self.assertRaises(ContractError):self.download(opener=opener)
        self.assertFalse((self.cache.root/'partial'/self.sha).exists())

    def test_generation_store_registers_protected_reference_before_gc(self):
        from ctflab_generation_store import GenerationStore
        from test_ctflab_scenario_v2 import sample
        import uuid
        self.accept();path=self.download();preview=self.cache.preview_gc()
        manifest=sample();manifest['assets']['linux']['sha256']=self.sha
        instance=str(uuid.uuid4())
        store=GenerationStore.create(self.root/'instance',manifest,instance,{'linux':path})
        self.assertEqual(store.config['cache_references'][0]['sha256'],self.sha)
        with self.assertRaises(ContractError):self.cache.collect(preview)
        with self.assertRaises(ContractError):self.cache.unpin('instance-'+instance,self.sha)
        self.assertTrue(path.exists())


class CacheBudgetTests(unittest.TestCase):
    setUp = CacheTests.setUp
    envelope = CacheTests.envelope
    accept = CacheTests.accept
    opener = CacheTests.opener
    download = CacheTests.download
    # 复用签名夹具，不重复收集旧类的测试。
    def configure_budget(self, maximum):
        preview = self.cache.budget_preview(maximum)
        return self.cache.budget_apply(maximum, preview['plan_sha256'])

    def test_budget_refuses_download_before_network_and_preserves_partial(self):
        self.accept()
        part=self.cache.root/'partial'/self.sha;part.write_bytes(self.data[:100]);part.chmod(0o600)
        self.configure_budget(len(self.data)-1)
        def forbidden(*args, **kwargs): self.fail('容量不足不能请求网络')
        with self.assertRaises(ContractError): self.download(opener=forbidden)
        self.assertEqual(part.read_bytes(), self.data[:100])

    def test_exact_limit_resume_and_shared_categories(self):
        self.accept();self.configure_budget(len(self.data))
        self.download()
        value=self.cache.storage()
        self.assertEqual(value['payload_bytes'],len(self.data))
        self.assertEqual(value['reserved_bytes'],0)
        self.assertFalse(value['hard_quota_verified']);self.assertFalse(value['metadata_included'])
        self.cache.pin('retained-course',self.sha)
        value=self.cache.storage();self.assertTrue(value['references'][0]['object_present'])
        self.assertEqual(self.cache.preview_gc(),[])

    def test_quarantine_or_orphan_counts_and_stale_preview_refused(self):
        preview=self.cache.budget_preview(1000)
        path=self.cache.root/'quarantine'/'failed';path.write_bytes(b'x'*101);path.chmod(0o600)
        with self.assertRaises(ContractError): self.cache.budget_apply(1000,preview['plan_sha256'])
        self.assertEqual(self.cache.storage()['payload_bytes'],101)
        with self.assertRaises(ContractError): self.configure_budget(100)
        self.assertTrue(path.exists())

    def test_reference_change_invalidates_preview_without_deleting(self):
        self.accept();path=self.download();preview=self.cache.budget_preview(2000)
        self.cache.pin('new-owner',self.sha)
        with self.assertRaises(ContractError): self.cache.budget_apply(2000,preview['plan_sha256'])
        self.assertTrue(path.exists());self.assertIsNone(self.cache.storage()['maximum_bytes'])

    def test_links_nonregular_and_scope_bounds_refused(self):
        import os
        path=self.cache.root/'partial'/'bad';target=self.root/'protected';target.write_bytes(b'safe')
        target.chmod(0o600);path.symlink_to(target)
        with self.assertRaises((ValueError,ContractError)):self.cache.storage()
        path.unlink();os.link(target,path)
        with self.assertRaises(ContractError):self.cache.storage()
        self.assertEqual(target.read_bytes(),b'safe')

    def test_invalid_budget_and_readonly_cli(self):
        import subprocess,json
        for value in (True,0,-1,1024**4+1,None):
            with self.assertRaises(ContractError):self.cache.budget_preview(value)
        script=Path(__file__).resolve().parents[1]/'ctflab_content_cache.py'
        value=subprocess.run([sys.executable,'-I','-B',str(script),'storage','--root',str(self.cache.root)],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(value.returncode,0,value.stderr)
        self.assertFalse(json.loads(value.stdout)['automatic_cleanup'])
        self.assertIsNone(self.cache.storage()['maximum_bytes'])


if __name__=='__main__':unittest.main()
