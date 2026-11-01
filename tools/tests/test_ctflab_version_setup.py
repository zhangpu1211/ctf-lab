"""首轮版本设置的真实临时SQLite/私有文件/中断恢复；不安装、迁移或启动软件。"""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
from ctflab_release_store import ReleaseStore
from ctflab_version_bridge import VersionBridge
from ctflab_version_setup import VersionSetup,sha,STEPS,stable_location


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.keys=self.root/'publisher-keys.json'
        self.keys.write_text(canonical({'publisher':'a'*64}));self.config=self.root/'data'/'version-manager'/'manager.json'
        self.setup=VersionSetup(self.config,system=lambda:'Windows',caller=lambda _:True)
        self.operation=str(uuid.uuid4())
    def preview(self):return self.setup.handle({'action':'bootstrap-preview','public_keys':str(self.keys)})
    def payload(self):
        plan=self.preview()
        return {'action':'bootstrap-create','public_keys':str(self.keys),'operation_id':self.operation,'plan_sha256':plan['plan_sha256']}
    def create(self):return self.setup.handle(self.payload())
    def resume(self,view=None):
        view=view or self.setup.handle({'action':'bootstrap-status'})
        return self.setup.handle({'action':'bootstrap-resume','operation_id':view['operation_id'],'plan_sha256':view['plan_sha256']})
    def fail(self,point):
        request=self.payload()
        self.setup.checkpoint=lambda step:(_ for _ in ()).throw(OSError('本轮受控中断')) if step==point else None
        with self.assertRaises(OSError):self.setup.handle(request)
        self.setup=VersionSetup(self.config,system=lambda:'Windows',caller=lambda _:True)
        return self.setup.handle({'action':'bootstrap-status'})
    def test_preview_is_readonly_and_exact_fingerprint_not_publisher_verification(self):
        plan=self.preview();self.assertFalse(self.config.parent.exists());self.assertFalse(plan['created'])
        self.assertEqual(plan['keys_sha256'],sha({'publisher':'a'*64}));self.assertFalse(plan['publisher_identity_verified'])
        self.assertEqual(self.preview(),plan)
    def test_preview_ancestor_replacement_refuses_before_creation(self):
        ancestor=self.root/'data';ancestor.mkdir(mode=0o700)
        request=self.payload();ancestor.rename(self.root/'original-data');ancestor.mkdir(mode=0o700)
        with self.assertRaises(ContractError):self.setup.handle(request)
        self.assertFalse(self.config.parent.exists());self.assertTrue((self.root/'original-data').is_dir())
    def test_stable_location_refuses_install_tree_and_unknown_parent(self):
        image=self.root/'installed'/'ctflab-desktop.exe'
        with patch('ctflab_qemu_driver.native_observe',return_value=SimpleNamespace(state='running',image_path=str(image))),patch('ctflab_version_bridge.stable_caller',return_value=True):
            with self.assertRaises(ContractError):stable_location(image.parent/'data')
            self.assertTrue(stable_location(self.root/'separate-data'))
        with patch('ctflab_qemu_driver.native_observe',return_value=SimpleNamespace(state='unknown',image_path='')),patch('ctflab_version_bridge.stable_caller',return_value=True):
            with self.assertRaises(ContractError):stable_location(self.root/'separate-data')
    @unittest.skipUnless(sys.platform=='darwin','此项只验证原Mac入口保持只读')
    def test_actual_isolated_bridge_dispatches_bootstrap_without_existing_config(self):
        script=Path(__file__).resolve().parents[1]/'ctflab_version_bridge.py'
        result=subprocess.run([sys.executable,'-I','-B',str(script),'bridge','--config',str(self.config)],
                              input=b'{"action":"bootstrap-status"}',capture_output=True,cwd=self.root,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        value=json.loads(result.stdout);self.assertEqual(value['state'],'platform-read-only')
        self.assertTrue(value['original_mac_updater_preserved']);self.assertFalse(self.config.parent.exists())
    def test_complete_setup_opens_real_version_bridge_without_development_preparation(self):
        view=self.create();self.assertTrue(view['ready']);self.assertFalse(view['packages_installed'])
        bridge=VersionBridge(self.config,system=lambda:'Windows',caller=lambda _:True)
        status=bridge.status();self.assertFalse(status['requires_initialize']);self.assertFalse(status['read_only'])
        self.assertIsNone(status['active']);self.assertEqual(status['versions'],[])
        self.assertEqual(json.loads((self.config.parent/'trusted-keys.json').read_text()),{'publisher':'a'*64})
        self.assertNotIn('a'*64,canonical(view))
    def test_existing_target_unknown_directory_and_file_preserved(self):
        self.config.parent.mkdir(parents=True);marker=self.config.parent/'user-file';marker.write_text('keep')
        self.assertEqual(self.setup.handle({'action':'bootstrap-status'})['state'],'unrecognized-preserved')
        with self.assertRaises(ContractError):self.preview()
        self.assertEqual(marker.read_text(),'keep')
    def test_changed_keys_or_stale_approved_preview_never_creates(self):
        request=self.payload();self.keys.write_text(canonical({'different':'b'*64}))
        with self.assertRaises(ContractError):self.setup.handle(request)
        self.assertFalse(self.config.parent.exists())
    def test_bad_keys_and_unknown_payload_fields_refused(self):
        for keys in ({}, {'name':'nothex'},{'name':'a'*63},{'name':True},['a'*64]):
            self.keys.write_text(json.dumps(keys))
            with self.assertRaises((ContractError,ValueError)):self.preview()
        for payload in ({'action':'bootstrap-status','command':'sh'},{'action':'bootstrap-preview','public_keys':str(self.keys),'system':'Windows'}):
            with self.assertRaises(ContractError):self.setup.handle(payload)
        self.assertFalse(self.config.parent.exists())
    def test_mac_and_unstable_caller_do_not_create_or_change_original_updater(self):
        mac=VersionSetup(self.config,system=lambda:'Darwin',caller=lambda _:True)
        self.assertFalse(mac.handle({'action':'bootstrap-status'})['available'])
        with self.assertRaises(ContractError):mac.handle({'action':'bootstrap-preview','public_keys':str(self.keys)})
        locked=VersionSetup(self.config,system=lambda:'Windows',caller=lambda _:False)
        self.assertTrue(locked.handle({'action':'bootstrap-status'})['read_only'])
        with self.assertRaises(ContractError):locked.handle({'action':'bootstrap-preview','public_keys':str(self.keys)})
        self.assertFalse(self.config.parent.exists())
    def test_known_pending_steps_resume_after_original_manager_exit(self):
        view=self.fail('bootstrap-intent');self.assertEqual(set(view['steps'].values()),{'pending'})
        self.assertTrue(self.resume(view)['ready'])
        with patch.object(ReleaseStore,'create',side_effect=AssertionError('不能重建')):self.assertTrue(self.resume()['ready'])
    def test_completed_store_without_receipt_is_only_observed_not_recreated(self):
        view=self.fail('effect-store');self.assertEqual(view['steps']['store'],'outcome-unknown')
        with patch.object(ReleaseStore,'create',side_effect=AssertionError('不得重放副作用')):
            self.assertTrue(self.resume(view)['ready'])
    def test_key_write_without_receipt_can_be_observed_after_source_disappears(self):
        view=self.fail('effect-keys');self.keys.unlink()
        self.assertTrue(self.resume(view)['ready'])
    def test_unknown_step_without_provable_output_is_never_replayed(self):
        view=self.fail('intent-store');self.assertEqual(view['steps']['store'],'outcome-unknown')
        with patch.object(ReleaseStore,'create',side_effect=AssertionError('不得重做未知步骤')):
            returned=self.resume(view);self.assertFalse(returned['ready'])
        self.assertFalse((self.config.parent/'releases').exists())
    def test_partial_or_changed_config_is_preserved_and_not_overwritten(self):
        view=self.fail('intent-config');self.config.write_text('partial');original=self.config.read_bytes()
        returned=self.resume(view);self.assertFalse(returned['ready']);self.assertEqual(self.config.read_bytes(),original)
    def test_resume_requires_original_operation_and_plan(self):
        view=self.fail('bootstrap-intent')
        for operation,plan in ((str(uuid.uuid4()),view['plan_sha256']),(self.operation,'0'*64)):
            with self.assertRaises(ContractError):self.setup.handle({'action':'bootstrap-resume','operation_id':operation,'plan_sha256':plan})
        self.assertFalse((self.config.parent/'releases').exists())
    def test_duplicate_create_never_adopts_existing_job(self):
        request=self.payload();view=self.setup.handle(request)
        with self.assertRaises(ContractError):self.setup.handle(request)
        self.assertEqual(self.setup.handle({'action':'bootstrap-status'})['operation_id'],view['operation_id'])
    def test_private_files_and_missing_step_intent_refuse(self):
        self.create()
        for name in ('manager.json','trusted-keys.json','bootstrap.json','control.lock'):
            if os.name!='nt':self.assertEqual((self.config.parent/name).stat().st_mode&0o777,0o600)
        (self.config.parent/'keys.intent.json').unlink()
        with self.assertRaises((ContractError,OSError)):self.setup.handle({'action':'bootstrap-status'})
    def test_plan_cannot_target_symlink_or_arbitrary_config_name(self):
        with self.assertRaises(ContractError):VersionSetup(self.config.with_name('other.json'))
        target=self.root/'existing';target.mkdir();link=self.root/'link';link.symlink_to(target,target_is_directory=True)
        with self.assertRaises(ContractError):VersionSetup(link/'manager.json')
    def test_normal_store_use_does_not_make_completed_setup_unknown(self):
        self.create();store=ReleaseStore(self.config.parent/'releases')
        with store.locked() as db:db.execute('INSERT INTO refs VALUES(?,?)',('fixture','1.0.0'))
        self.assertTrue(self.setup.handle({'action':'bootstrap-status'})['ready'])


if __name__=='__main__':unittest.main()
