"""换库的真实SQLite/CAS/中断恢复，全部自有临时材料；不观察或操作VM。"""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from ctflab_contract import ContractError,canonical
from ctflab_generation_store import digest
from ctflab_remote import private_json
from ctflab_remote_audit import AuditStore
from ctflab_audit_rotation import preview,rotate,resume
import test_ctflab_worker_audit as worker


class RotationTests(unittest.TestCase):
    setUp=worker.WorkerAuditTests.setUp
    configured_lease=worker.WorkerAuditTests.configured_lease
    make_manager=worker.WorkerAuditTests.make_manager
    write_policy=worker.WorkerAuditTests.write_policy
    acquire=worker.WorkerAuditTests.acquire
    request=worker.WorkerAuditTests.request
    configured_worker=worker.WorkerAuditTests.configured
    def configured(self):
        self.configured_worker();self.new=self.root/'new-audit';self.archive=self.root/'signed-archive'
        key=Ed25519PrivateKey.generate();self.public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw).hex()
        self.signing={'key_id':'fixture','private_key_hex':key.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()).hex()}
    def plan(self):return preview(self.policy_path,self.new,self.archive,self.signing)
    def rotate(self,plan):return rotate(self.policy_path,self.new,self.archive,self.signing,plan['rotation_sha256'])
    def test_preview_no_mutation_then_switch_keeps_original_bytes_freezes_old_and_new_is_writable(self):
        self.configured();attempt=self.audit.begin({'action':'list'},'alice');self.audit.finish(attempt)
        before=self.policy_path.read_bytes();old_events=self.audit.read()['events'];plan=self.plan()
        self.assertFalse(self.new.exists());self.assertFalse(self.archive.exists())
        result=self.rotate(plan);self.assertFalse(result['vm_stopped']);self.assertTrue(result['old_audit_preserved'])
        self.assertEqual((self.new/'policy.before.json').read_bytes(),before);self.assertEqual(self.audit.read()['events'],old_events)
        with self.assertRaises(ContractError):self.audit.begin({'action':'list'},'alice')
        policy=private_json(self.policy_path);self.assertEqual(policy['audit']['root'],str(self.new))
        fresh=AuditStore(policy['audit'],self.server);self.assertEqual(fresh.read()['events'],[])
        fresh.begin({'action':'list'},'alice');self.assertEqual(len(fresh.read()['pending']),1)
        self.assertEqual(self.driver.calls,[])
    def test_pending_audit_or_active_contract_refuses_without_freezing_or_changing_policy(self):
        self.configured();attempt=self.audit.begin({'action':'list'},'alice');before=self.policy_path.read_bytes()
        with self.assertRaises(ContractError):self.plan()
        self.audit.finish(attempt);plan=self.plan();accepted=self.manager.submit(self.instance,self.request('prepare'),self.lease)
        self.assertEqual(accepted['result'],'accepted')
        with self.assertRaises(ContractError):self.rotate(plan)
        self.assertEqual(self.policy_path.read_bytes(),before);self.assertFalse(self.new.exists())
        self.audit.begin({'action':'list'},'alice')
    def test_stale_policy_or_head_refuses_before_any_new_root(self):
        self.configured();plan=self.plan();self.audit.begin({'action':'list'},'alice')
        with self.assertRaises(ContractError):self.rotate(plan)
        self.assertFalse(self.new.exists())
    def test_failure_after_old_freeze_is_preserved_and_explicit_resume_switches_with_trusted_key(self):
        self.configured();before=self.policy_path.read_bytes();plan=self.plan()
        with patch('ctflab_audit_rotation.replace_policy',side_effect=OSError('fixture interrupted before rename')):
            with self.assertRaises(OSError):self.rotate(plan)
        self.assertEqual(self.policy_path.read_bytes(),before);self.assertTrue(self.archive.exists())
        with self.assertRaises(ContractError):self.audit.begin({'action':'list'},'alice')
        expected=digest(self.new/'rotation.intent.json')
        result=resume(self.new,{'fixture':self.public},expected)
        self.assertEqual(result['state'],'audit-rotation-resumed');self.assertFalse(result['vm_stopped'])
        self.assertEqual(private_json(self.policy_path)['audit']['root'],str(self.new));self.assertEqual(self.driver.calls,[])
    def test_failure_before_freeze_keeps_old_writable_and_preserves_new_partial_files(self):
        self.configured();plan=self.plan();before=self.policy_path.read_bytes()
        with patch('ctflab_audit_rotation.seal',side_effect=OSError('fixture archive disk full')):
            with self.assertRaises(OSError):self.rotate(plan)
        self.assertEqual(self.policy_path.read_bytes(),before);self.assertTrue((self.new/'rotation.intent.json').exists())
        self.audit.begin({'action':'list'},'alice')
    def test_resume_refuses_wrong_key_changed_policy_and_nonempty_new_database(self):
        self.configured();plan=self.plan()
        with patch('ctflab_audit_rotation.replace_policy',side_effect=OSError('fixture interrupted')):
            with self.assertRaises(OSError):self.rotate(plan)
        expected=digest(self.new/'rotation.intent.json')
        with self.assertRaises(ContractError):resume(self.new,{},expected)
        self.policy_path.write_text(self.policy_path.read_text()+' ')
        with self.assertRaises(ContractError):resume(self.new,{'fixture':self.public},expected)
        self.assertEqual(self.driver.calls,[])


if __name__=='__main__':unittest.main()
