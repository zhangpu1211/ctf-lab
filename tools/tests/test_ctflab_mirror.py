"""镜像材料与显式HTTPS镜像位置；无真实服务器或网络下载。"""
from pathlib import Path
import json
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError
from ctflab_mirror import build
from ctflab_generation_store import digest
import test_ctflab_content_cache as cache_tests


class MirrorTests(unittest.TestCase):
    setUp=cache_tests.CacheTests.setUp
    envelope=cache_tests.CacheTests.envelope
    accept=cache_tests.CacheTests.accept
    opener=cache_tests.CacheTests.opener
    download=cache_tests.CacheTests.download
    def prepare(self):self.accept();self.download();self.destination=self.root/'student-mirror'
    def build(self):return build(self.cache,self.envelope(),self.keys,self.source,self.destination,now=self.now)
    def test_signed_student_export_keeps_exact_content_and_signature(self):
        self.prepare();receipt=self.build()
        self.assertEqual(digest(self.destination/'assets/linux.qcow2'),self.sha)
        self.assertEqual(json.loads((self.destination/'INDEX.json').read_text()),self.envelope())
        self.assertFalse(receipt['teacher_materials_included']);self.assertFalse(receipt['service_started'])
        self.assertEqual(self.cache.preview_gc(),[])
        with self.assertRaises(ContractError):self.build()
    def test_teacher_or_recipe_entry_refused_before_creating_anything(self):
        self.prepare()
        for key,value in (('audience','teacher'),('redistribution','recipe-only')):
            original=self.payload['assets'][self.sha][key];self.payload['assets'][self.sha][key]=value
            with self.assertRaises(ContractError):self.build()
            self.assertFalse(self.destination.exists());self.payload['assets'][self.sha][key]=original
    def test_windows_alias_path_rejected(self):
        self.prepare()
        for path in ('assets/CON.txt','assets/name.','assets/LPT1'):
            self.payload['assets'][self.sha]['path']=path
            with self.assertRaises(ContractError):self.build()
            self.assertFalse(self.destination.exists())
    def test_missing_or_changed_cache_not_exported(self):
        self.prepare();(self.cache.root/'objects'/self.sha).write_bytes(b'changed')
        with self.assertRaises(ContractError):self.build()
        self.assertFalse(self.destination.exists())
    def test_explicit_mirror_changes_transport_url_only(self):
        self.accept();urls=[]
        def opener(request,timeout):urls.append(request.full_url);return self.opener(request,timeout)
        path=self.cache.download(self.source,self.sha,mirror='https://school.invalid/mirror/',opener=opener,now=self.now)
        self.assertEqual(urls,['https://school.invalid/mirror/assets/linux.qcow2'])
        self.assertEqual(digest(path),self.sha)
        with self.cache.locked() as db:
            self.assertEqual(db.execute('SELECT source FROM indexes').fetchone()[0],self.source)
    def test_non_https_mirror_rejected_before_network_call(self):
        self.accept()
        with self.assertRaises(ContractError):self.cache.download(self.source,self.sha,mirror='http://school.invalid/',
                                                                opener=lambda *a,**k:self.fail('不得访问'),now=self.now)


if __name__=='__main__':unittest.main()
