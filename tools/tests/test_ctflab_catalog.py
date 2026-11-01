"""离线目录/精确资产测试；不下载镜像、不写原始资产。"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ctflab_catalog as catalog
from ctflab_scenario_v2 import ScenarioError
from test_ctflab_scenario_v2 import sample


def fixture():
    return {'catalog_schema':1,'courses':{'course':{
        'title':'合成课程','description':'目录测试夹具','source':'local-fixture',
        'license':'synthetic-only','redistribution':'unknown',
        'entries':[{'node':'client','protocol':'console','port':None}],
        'variants':{'x64':{'host_architecture':'x86_64','scenario':sample(),
                           'assets':{'linux':'镜像/linux.qcow2'},'verification':'unverified','evidence_refs':[]}}}}}


class CatalogTests(unittest.TestCase):
    def setUp(self):self.value=fixture()

    def test_exact_variant_and_no_claim_promotion(self):
        selected=catalog.select_variant(self.value,'course','x86_64')
        self.assertEqual(selected['variant_id'],'x64')
        self.assertFalse(selected['runtime_verified'])
        selected['variant']['assets']['linux']='changed'
        self.assertEqual(self.value,fixture())

    def test_ambiguous_variant_requires_explicit_choice(self):
        variants=self.value['courses']['course']['variants'];variants['other']=copy.deepcopy(variants['x64'])
        with self.assertRaises(ScenarioError):catalog.select_variant(self.value,'course','x86_64')
        self.assertEqual(catalog.select_variant(self.value,'course','x86_64',variant_id='other')['variant_id'],'other')

    def test_wrong_host_or_unknown_course(self):
        for name,host in [('missing','x86_64'),('course','aarch64')]:
            with self.assertRaises(ScenarioError):catalog.select_variant(self.value,name,host)

    def test_no_paths_escape_or_commands(self):
        for path in ('../disk','/disk','C:\\disk','folder//disk','./disk','disk\x00'):
            data=fixture();data['courses']['course']['variants']['x64']['assets']['linux']=path
            with self.assertRaises(ScenarioError):catalog.validate_catalog(data)
        self.value['courses']['course']['command']='shell'
        with self.assertRaises(ScenarioError):catalog.validate_catalog(self.value)

    def test_verification_requires_evidence_and_valid_entry(self):
        variant=self.value['courses']['course']['variants']['x64'];variant['verification']='course'
        with self.assertRaises(ScenarioError):catalog.validate_catalog(self.value)
        variant['evidence_refs']=['report-one'];catalog.validate_catalog(self.value)
        self.value['courses']['course']['entries'][0]['node']='missing'
        with self.assertRaises(ScenarioError):catalog.validate_catalog(self.value)

    def test_hash_checks_readonly_missing_mismatch_and_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();selected=catalog.select_variant(self.value,'course','x86_64')
            self.assertEqual(catalog.inspect_assets(selected,root)['assets'][0]['status'],'missing')
            file=root/'镜像/linux.qcow2';file.parent.mkdir();file.write_bytes(b'synthetic')
            before=file.stat().st_mtime_ns
            self.assertEqual(catalog.inspect_assets(selected,root)['assets'][0]['status'],'hash-mismatch')
            selected['variant']['scenario']['assets']['linux']['sha256']=hashlib.sha256(b'synthetic').hexdigest()
            result=catalog.inspect_assets(selected,root)
            self.assertTrue(result['all_present_and_verified']);self.assertFalse(result['course_verified'])
            self.assertEqual(file.stat().st_mtime_ns,before)

    def test_symlink_is_not_asset(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();file=root/'source';file.write_bytes(b'x');(root/'镜像').mkdir()
            try:(root/'镜像/linux.qcow2').symlink_to(file)
            except OSError as exc:
                if getattr(exc, 'winerror', None) == 1314:
                    self.skipTest('Windows 当前用户无创建符号链接权限；该负测未验证')
                raise
            with self.assertRaises(ScenarioError):catalog.inspect_assets(catalog.select_variant(self.value,'course','x86_64'),root)

    def test_json_duplicates_nan_size(self):
        for raw in ('{"catalog_schema":1,"catalog_schema":1}','{"x":NaN}','x'*(catalog.MAX_BYTES+1)):
            with self.assertRaises(ScenarioError):catalog.parse_catalog(raw)
        self.assertEqual(catalog.parse_catalog(json.dumps(self.value)),self.value)
