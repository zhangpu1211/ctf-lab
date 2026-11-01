"""离线版本暂存、签名和回退；不创建真实Windows安装包。"""
import base64
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import canonical,ContractError
from ctflab_generation_store import digest
from ctflab_release_store import ReleaseStore,release_manifest


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        try:from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError:self.skipTest('签名依赖缺失')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.source=self.root/'source';self.source.mkdir()
        (self.source/'LICENSE').write_text('fixture license')
        (self.source/'app.exe').write_bytes(b'fixture executable')
        self.payload={'schema':1,'version':'0.1.0','data_schema':1,'files':{n:digest(self.source/n) for n in ('LICENSE','app.exe')},'licenses':['LICENSE']}
        self.key=Ed25519PrivateKey.generate();self.keys={'main':self.key.public_key().public_bytes_raw().hex()}
        self.store=ReleaseStore.create(self.root/'install')

    def envelope(self):return {'key_id':'main','payload':self.payload,'signature':base64.b64encode(self.key.sign(canonical(self.payload).encode())).decode()}
    def stage(self):return self.store.stage(self.source,self.envelope(),self.keys)

    def test_stage_activate_update_rollback_keeps_both_versions_and_refs(self):
        self.stage();self.store.activate('0.1.0');self.store.pin('active-lab','0.1.0')
        self.payload['version']='0.2.0';self.stage();self.store.activate('0.2.0')
        self.assertEqual(self.store.rollback()['version'],'0.1.0')
        status=self.store.status();self.assertEqual(len(status['versions']),2)
        self.assertEqual(status['references'],[{'owner':'active-lab','version':'0.1.0'}])

    def test_bad_signature_never_stages_or_changes_active(self):
        value=self.envelope();value['payload']['version']='0.2.0'
        with self.assertRaises(ContractError):self.store.stage(self.source,value,self.keys)
        self.assertEqual(self.store.status()['versions'],[])

    def test_changed_staged_binary_refuses_activation_and_preserves_old(self):
        self.stage();self.store.activate('0.1.0');self.payload['version']='0.2.0';self.stage()
        (self.store.root/'versions'/'0.2.0'/'app.exe').write_bytes(b'changed')
        with self.assertRaises(ContractError):self.store.activate('0.2.0')
        self.assertEqual(self.store.status()['active'],'0.1.0')

    def test_unsupported_migration_refused_without_data_access(self):
        self.payload['data_schema']=2
        with self.assertRaises(ContractError):self.stage()
        self.assertEqual(self.store.status()['versions'],[])

    def test_windows_path_aliases_and_traversal_refused(self):
        for name in ('../outside','C:/outside','CON.txt','dir/NUL.exe','app.exe/../LICENSE'):
            self.payload['files'][name]='0'*64
            with self.assertRaises(ContractError):release_manifest(self.envelope(),self.keys)
            del self.payload['files'][name]
        self.payload['files']['APP.exe']='0'*64
        with self.assertRaises(ContractError):release_manifest(self.envelope(),self.keys)

    def test_failure_midcopy_preserves_previous_and_staging(self):
        self.stage();self.store.activate('0.1.0');self.payload['version']='0.2.0'
        with patch('ctflab_release_store.shutil.copyfileobj',side_effect=OSError('synthetic storage failure')):
            with self.assertRaises(OSError):self.stage()
        self.assertEqual(self.store.status()['active'],'0.1.0')
        self.assertEqual(len(list((self.store.root/'staging').iterdir())),1)


if __name__=='__main__':unittest.main()
