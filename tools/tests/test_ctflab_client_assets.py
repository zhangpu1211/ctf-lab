"""客户端传输持久化/暂停/续传，真实签名缓存与假SSH，无VM操作。"""
import hashlib
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_ctflab_remote_assets as asset_tests
from ctflab_client_store import ClientStore
from ctflab_client_assets import ClientAssets
from ctflab_contract import canonical,ContractError
from ctflab_generation_store import digest


class ClientAssetTests(unittest.TestCase):
    setUp=asset_tests.UploadTests.setUp
    envelope=asset_tests.UploadTests.envelope
    accept=asset_tests.UploadTests.accept
    configured_uploads=asset_tests.UploadTests.configured

    def configured(self):
        self.configured_uploads();self.calls=[];self.cut=None;self.pause=False
        self.path=self.root/'chosen.bin';self.path.write_bytes(self.data)
        ssh=self.root/'ssh';ssh.write_bytes(b'not executed')
        key=self.root/'identity';key.write_text('fixture');key.chmod(0o600)
        known=self.root/'known';known.write_text('fixture');known.chmod(0o600)
        config={'schema':1,'host':'fixture.test','port':22,'user':'alice','server_uuid':str(uuid.uuid4()),
                'ssh':str(ssh),'identity':str(key),'known_hosts':str(known),'known_hosts_sha256':digest(known)}
        connection=self.root/'connection.json';connection.write_text(canonical(config));connection.chmod(0o600)
        self.store=ClientStore(self.root/'client');self.target_id=str(uuid.uuid4());self.store.save(self.target_id,'资产节点',str(connection))
        self.transfer=str(uuid.uuid4());owner=self
        class Session:
            def __init__(self,config):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def request(self,action,params):
                owner.calls.append(action)
                if action=='handshake':return {'asset_upload':True,'persistent_requests':True}
                result=owner.uploads.handle(action,params)
                if owner.pause and action=='asset-begin':owner.assets.cancel(owner.transfer)
                if owner.cut==action:owner.cut=None;raise OSError('fixture lost response')
                return result
        self.assets=ClientAssets(self.store,session_factory=Session)
    def run_upload(self):return self.assets.run(self.target_id,self.transfer,self.path,self.source,'student')

    def test_upload_verified_history_read_does_not_resend_or_claim_current_server(self):
        self.configured();result=self.run_upload();self.assertEqual(result['phase'],'verified')
        self.assertEqual(self.cache.object(self.sha).read_bytes(),self.data);count=len(self.calls)
        result=self.assets.history(self.target_id);self.assertEqual(len(self.calls),count)
        self.assertFalse(result['uploads'][0]['server_current_verified']);self.assertNotIn(str(self.path),canonical(result))
        self.assertTrue(self.assets.probe(self.transfer)['server_current_verified'])

    def test_reply_lost_after_chunk_is_unknown_until_explicit_resume(self):
        self.configured();self.cut='asset-chunk';self.assertEqual(self.run_upload()['phase'],'unknown')
        count=len(self.calls);self.assets.history(self.target_id);self.assertEqual(len(self.calls),count)
        with self.assertRaises(ContractError):self.run_upload()
        result=self.assets.resume(self.transfer);self.assertEqual(result['phase'],'verified')
        self.assertEqual(self.cache.object(self.sha).read_bytes(),self.data)

    def test_pause_never_deletes_partial_object_and_resume_reuses_upload_id(self):
        self.configured();self.pause=True;result=self.run_upload();self.assertEqual(result['phase'],'paused')
        self.assertTrue(self.uploads.path(self.transfer).exists());self.assertNotIn('asset-chunk',self.calls)
        self.pause=False;self.assertEqual(self.assets.resume(self.transfer)['phase'],'verified')
        self.assertEqual(self.assets.record(self.transfer)[0][9],2)

    def test_same_identifier_cannot_be_rebound_to_changed_source_file(self):
        self.configured();self.cut='asset-begin';self.run_upload();self.path.write_bytes(b'changed')
        with self.assertRaises(ContractError):self.assets.resume(self.transfer)
        self.assertEqual(self.assets.record(self.transfer)[0][7],'unknown')

    def test_history_on_new_registry_is_readonly_without_creating_transfer_schema(self):
        self.configured();self.assertEqual(self.assets.history(self.target_id)['uploads'],[])
        with self.store.db() as db:self.assertFalse(self.assets.exists(db))

    def test_teacher_audience_rejection_keeps_source_and_never_publishes_cache(self):
        self.configured();original=self.path.read_bytes()
        result=self.assets.run(self.target_id,self.transfer,self.path,self.source,'teacher')
        self.assertEqual(result['phase'],'unknown');self.assertEqual(self.path.read_bytes(),original)
        self.assertNotIn('asset-chunk',self.calls)

    def test_verified_result_reuse_is_local_history_and_explicit_probe_checks_remote(self):
        self.configured();self.run_upload();count=len(self.calls)
        result=self.run_upload();self.assertEqual(len(self.calls),count);self.assertFalse(result['server_current_verified'])
        self.assertTrue(self.assets.probe(self.transfer)['server_current_verified'])

    def test_extra_fields_and_credential_urls_are_rejected(self):
        self.configured()
        with self.assertRaises(ContractError):self.assets.handle({'action':'asset-resume','upload_id':self.transfer,'command':'stop'})
        with self.assertRaises(ContractError):self.assets.run(self.target_id,self.transfer,self.path,'https://user:secret@example.test/','student')
        self.assertEqual(self.calls,[])

    def test_verified_with_short_byte_count_is_not_accepted_as_current_server_evidence(self):
        self.configured();self.run_upload();original=self.uploads.handle
        def handle(action,params):
            value=original(action,params)
            if action=='asset-status':value=dict(value,received=value['size']-1)
            return value
        with patch.object(self.uploads,'handle',side_effect=handle):
            with self.assertRaises(ContractError):self.assets.probe(self.transfer)
        self.assertFalse(self.assets.history(self.target_id)['uploads'][0]['server_current_verified'])

    def test_short_verified_begin_is_unknown_and_does_not_mark_transfer_complete(self):
        self.configured();original=self.uploads.handle
        def handle(action,params):
            value=original(action,params)
            if action=='asset-begin':value=dict(value,state='verified',received=0)
            return value
        with patch.object(self.uploads,'handle',side_effect=handle):
            self.assertEqual(self.run_upload()['phase'],'unknown')
        self.assertNotIn('asset-chunk',self.calls)


if __name__=='__main__':unittest.main()
