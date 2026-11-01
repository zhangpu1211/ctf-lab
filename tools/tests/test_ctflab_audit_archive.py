"""审计一致快照/外部公钥验证/篡改拒绝；临时SQLite与密钥，不上传或切换策略。"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from ctflab_contract import ContractError
from ctflab_audit_archive import seal,verify
from ctflab_remote_audit import AuditStore


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        self.store=AuditStore.create({'root':str(self.root/'audit'),'max_attempts':10},str(uuid.uuid4()))
        self.key=Ed25519PrivateKey.generate();self.public=self.key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
        self.signing={'key_id':'fixture','private_key_hex':self.key.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()).hex()}
        self.destination=self.root/'sealed'
    def test_snapshot_preserves_pending_and_source_database_and_verifies_with_external_key(self):
        pending=self.store.begin({'action':'list'},'alice');before=(self.store.root/'audit.sqlite3').read_bytes()
        result=seal(self.store,self.destination,self.signing);checked=verify(self.destination,{'fixture':self.public})
        self.assertEqual(result['pending_count'],1);self.assertEqual(checked['pending_count'],1)
        self.assertFalse(checked['externally_anchored']);self.assertFalse(result['original_audit_modified'])
        self.assertEqual((self.store.root/'audit.sqlite3').read_bytes(),before)
        self.assertEqual(self.store.read()['pending'],[pending]);self.assertNotIn(self.signing['private_key_hex'],(self.destination/'CHECKPOINT.json').read_text())
    def test_unknown_key_signature_database_and_checkpoint_drift_refuse(self):
        seal(self.store,self.destination,self.signing)
        with self.assertRaises(ContractError):verify(self.destination,{})
        envelope=json.loads((self.destination/'CHECKPOINT.json').read_text());envelope['payload']['pending_count']=1
        (self.destination/'CHECKPOINT.json').write_text(json.dumps(envelope))
        with self.assertRaises(Exception):verify(self.destination,{'fixture':self.public})
    def test_completed_snapshot_remains_valid_when_live_database_advances(self):
        seal(self.store,self.destination,self.signing);self.store.begin({'action':'list'},'alice')
        self.assertEqual(verify(self.destination,{'fixture':self.public})['head_seq'],0)
        self.assertEqual(self.store.read()['head_seq'],1)
        with (self.destination/'audit.sqlite3').open('ab') as stream:stream.write(b'tamper')
        with self.assertRaises(ContractError):verify(self.destination,{'fixture':self.public})
    def test_existing_or_nested_destination_and_extra_unsigned_file_are_rejected(self):
        seal(self.store,self.destination,self.signing)
        with self.assertRaises(FileExistsError):seal(self.store,self.destination,self.signing)
        with self.assertRaises(ContractError):seal(self.store,self.store.root/'nested',self.signing)
        (self.destination/'extra').write_text('unsigned')
        with self.assertRaises(ContractError):verify(self.destination,{'fixture':self.public})
    @unittest.skipIf(os.name=='nt','POSIX链接负向，Windows重解析点由路径边界处理')
    def test_symlink_archive_is_refused(self):
        seal(self.store,self.destination,self.signing);link=self.root/'link';link.symlink_to(self.destination,target_is_directory=True)
        with self.assertRaises((ContractError,OSError)):verify(link,{'fixture':self.public})


if __name__=='__main__':unittest.main()
