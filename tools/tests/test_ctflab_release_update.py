"""更新锁、停机门、备份与崩溃现场；不启动用户实例。"""
import json
from pathlib import Path
import sqlite3
import sys
import uuid
from unittest.mock import patch
import unittest
from contextlib import closing, contextmanager

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_ctflab_release_store as release_tests
import test_ctflab_generation_store as generation_tests
from ctflab_contract import ContractError
from ctflab_generation_store import digest
from ctflab_release_update import UpdateCoordinator


class UpdateTests(unittest.TestCase):
    setUp = release_tests.ReleaseTests.setUp
    envelope = release_tests.ReleaseTests.envelope
    stage = release_tests.ReleaseTests.stage

    def configure(self):
        self.stage(); self.store.activate('0.1.0')
        self.payload['version'] = '0.2.0'; self.stage()
        self.lab = generation_tests.GenerationTests()
        self.lab.setUp(); self.addCleanup(self.lab.doCleanups)
        self.updates = UpdateCoordinator(self.store, make_driver=lambda _: self.lab.driver)
        self.updates.register(self.lab.store.root)
        self.lab.run_action('prepare')

    def test_registered_workspace_requires_preview_backup_and_atomic_switch(self):
        self.configure()
        with self.assertRaises(ContractError): self.store.activate('0.2.0')
        preview = self.updates.preview('0.2.0'); op = str(uuid.uuid4())
        original = digest(self.lab.base)
        result = self.updates.apply('0.2.0', op, preview['plan_sha256'])
        self.assertEqual(self.store.status()['active'], '0.2.0')
        self.assertEqual(digest(self.lab.base), original)
        backup = Path(result['backup']); self.assertTrue((backup/'backup.json').exists())
        manifest = json.loads((backup/'backup.json').read_text())
        self.assertFalse(manifest['disks_included'])
        self.assertTrue(manifest['files'])
        for name, sha in manifest['files'].items(): self.assertEqual(digest(backup/name), sha)
        self.assertEqual(self.updates.apply('0.2.0', op, preview['plan_sha256'])['state'], 'committed')
        self.assertEqual(self.updates.recovery()['updates'][0]['state'], 'committed')
        # 回退走相同预览和停机门；不恢复旧账本覆盖新进度。
        back = self.updates.preview('0.1.0')
        self.updates.apply('0.1.0', str(uuid.uuid4()), back['plan_sha256'])
        self.assertEqual(self.store.status()['active'], '0.1.0')

    def test_running_or_unknown_node_refuses_update(self):
        self.configure(); self.lab.run_action('start')
        with self.assertRaises(ContractError): self.updates.preview('0.2.0')
        self.assertEqual(self.store.status()['active'], '0.1.0')
        self.lab.run_action('stop'); self.lab.driver.identity = 'unknown'
        with self.assertRaises(ContractError): self.updates.preview('0.2.0')

    def test_generation_gate_prevents_concurrent_update(self):
        self.configure()
        with self.lab.store.locked():
            with self.assertRaises(ContractError): self.updates.preview('0.2.0')
        self.assertEqual(self.store.status()['active'], '0.1.0')

    def test_stale_preview_cannot_activate_after_generation_changes(self):
        self.configure(); preview = self.updates.preview('0.2.0')
        self.lab.run_action('reset')
        with self.assertRaises(ContractError): self.updates.apply('0.2.0', str(uuid.uuid4()), preview['plan_sha256'])
        self.assertEqual(self.store.status()['active'], '0.1.0')

    def test_backup_failure_preserves_active_and_blocks_replay(self):
        self.configure(); preview = self.updates.preview('0.2.0'); op = str(uuid.uuid4())
        with patch.object(self.updates, 'save', side_effect=[None, OSError('synthetic disk full')]):
            with self.assertRaises(OSError): self.updates.apply('0.2.0', op, preview['plan_sha256'])
        self.assertEqual(self.store.status()['active'], '0.1.0')
        self.assertEqual(self.updates.recovery()['updates'][0]['state'], 'interrupted-before-commit')
        with self.assertRaises(ContractError): self.updates.apply('0.2.0', op, preview['plan_sha256'])
        with self.assertRaises(ContractError): self.updates.preview('0.2.0')

    def test_tampered_payload_between_preview_and_apply_is_rejected(self):
        self.configure(); preview = self.updates.preview('0.2.0')
        (self.store.root/'versions'/'0.2.0'/'app.exe').write_bytes(b'changed')
        with self.assertRaises(ContractError): self.updates.apply('0.2.0', str(uuid.uuid4()), preview['plan_sha256'])
        self.assertEqual(self.store.status()['active'], '0.1.0')

    def test_contract_gate_and_contract_backup_are_real_sqlite(self):
        self.configure()
        from ctflab_local_service import LocalService
        service = LocalService.create(self.lab.store.root/'desktop-contract')
        with service._transaction(worker=True):
            with self.assertRaises(sqlite3.OperationalError): self.updates.preview('0.2.0')
        preview = self.updates.preview('0.2.0')
        result = self.updates.apply('0.2.0', str(uuid.uuid4()), preview['plan_sha256'])
        database = Path(result['backup'])/self.lab.instance/'contract.sqlite3'
        with closing(sqlite3.connect(database)) as db:
            self.assertEqual(db.execute('SELECT version FROM metadata').fetchone()[0], 1)

    def test_explicit_abandon_keeps_old_version_and_failed_backup_then_allows_new_attempt(self):
        self.configure(); preview = self.updates.preview('0.2.0'); operation = str(uuid.uuid4())
        real = self.updates.save
        def fail_manifest(path, value):
            if path.name == 'backup.json': raise OSError('synthetic interruption')
            return real(path, value)
        with patch.object(self.updates, 'save', side_effect=fail_manifest):
            with self.assertRaises(OSError): self.updates.apply('0.2.0', operation, preview['plan_sha256'])
        self.assertEqual(self.updates.abandon(operation)['state'], 'abandoned')
        self.assertTrue((self.store.root/'update-backups'/operation/'intent.json').exists())
        self.assertEqual(self.store.status()['active'], '0.1.0')
        next_plan = self.updates.preview('0.2.0')
        self.updates.apply('0.2.0', str(uuid.uuid4()), next_plan['plan_sha256'])
        self.assertEqual(self.store.status()['active'], '0.2.0')

    def test_legacy_install_store_migration_backs_up_before_adding_tables(self):
        self.stage(); self.store.activate('0.1.0')
        with self.store.locked() as db:
            db.execute('DROP TABLE workspaces'); db.execute('DROP TABLE updates')
        updates = UpdateCoordinator(self.store)
        with self.assertRaises(ContractError): self.store.activate('0.1.0')
        result = updates.initialize(); self.assertEqual(result['state'], 'initialized')
        self.assertEqual(digest(Path(result['backup'])), result['backup_sha256'])
        with closing(sqlite3.connect(result['backup'])) as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='updates'").fetchone())
            self.assertEqual(db.execute('SELECT active FROM pointers').fetchone()[0], '0.1.0')
        self.assertEqual(updates.initialize()['state'], 'already-initialized')

    def test_workspace_gate_is_held_until_release_transaction_finishes(self):
        self.configure(); preview = self.updates.preview('0.2.0')
        original = self.store.locked; checked = []
        @contextmanager
        def transaction():
            with original() as db:
                yield db
                with self.assertRaises(ContractError):
                    with self.lab.store.locked(): pass
                checked.append(True)
        with patch.object(self.store, 'locked', transaction):
            self.updates.apply('0.2.0', str(uuid.uuid4()), preview['plan_sha256'])
        self.assertEqual(checked, [True])
        with self.lab.store.locked(): pass


if __name__ == '__main__': unittest.main()
