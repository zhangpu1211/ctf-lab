"""本地更新不覆盖旧 App；失败、篡改、未授权候选不能改变更新指针。"""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab_update as update


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve()
        self.root = self.directory / "updates"
        self.source = self.directory / "source" / "CTFLab.app"
        self.source.mkdir(parents=True)
        (self.source / "data").write_text("候选一")
        self.source.with_suffix(".app.sha256").write_text("旁车由 verify_app 验证")
        self.report = {"version": "0.1.0", "signature": {"level": "ad-hoc", "verify_returncode": 0, "notarized": False}}
        self.patcher = mock.patch.object(update, "verify_app", return_value=self.report)
        self.patcher.start(); self.addCleanup(self.patcher.stop)

    def stage(self):
        return update.stage(self.root, self.source, update.app_tree_hash(self.source), True)

    def test_stage_does_not_select_or_touch_source(self):
        before = update.app_tree_hash(self.source)
        item = self.stage()
        self.assertFalse(item["activated"])
        self.assertIsNone(update.status(self.root)["active"])
        self.assertEqual(update.app_tree_hash(self.source), before)

    def test_two_slots_select_then_rollback_preserves_both(self):
        first = self.stage()
        update.select(self.root, first["slot"])
        (self.source / "data").write_text("候选二")
        second = self.stage()
        update.select(self.root, second["slot"])
        result = update.select(self.root, rollback=True)
        self.assertEqual(result["active"], first["slot"])
        self.assertEqual(result["previous"], second["slot"])
        self.assertTrue(Path(second["app"]).exists())

    def test_default_rejects_adhoc(self):
        with self.assertRaisesRegex(update.UpdateError, "Developer ID"):
            update.stage(self.root, self.source, update.app_tree_hash(self.source))
        self.assertFalse((self.root / "selection.json").exists())

    def test_hash_mismatch_does_not_publish(self):
        with self.assertRaisesRegex(update.UpdateError, "不匹配"):
            update.stage(self.root, self.source, "0" * 64, True)
        self.assertEqual(list(self.root.glob("*/CTFLab.app")), [])

    def test_tampered_slot_cannot_change_pointer(self):
        first = self.stage(); update.select(self.root, first["slot"])
        second = self.stage()
        (Path(second["app"]) / "data").write_text("篡改")
        before = (self.root / "selection.json").read_bytes()
        with self.assertRaises(update.UpdateError): update.select(self.root, second["slot"])
        self.assertEqual((self.root / "selection.json").read_bytes(), before)

    def test_copy_failure_removes_only_new_slot(self):
        first = self.stage()
        with mock.patch.object(update.shutil, "copy2", side_effect=OSError("复制失败")):
            with self.assertRaises(OSError): self.stage()
        self.assertEqual(len(list(self.root.glob("*/CTFLab.app"))), 1)
        self.assertTrue(Path(first["app"]).is_dir())

    def test_missing_previous_and_traversal_rejected(self):
        with self.assertRaises(update.UpdateError): update.select(self.root, rollback=True)
        with self.assertRaises(update.UpdateError): update.select(self.root, "../source")

    def test_symlink_root_rejected(self):
        self.root.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaises(update.UpdateError): self.stage()

    def test_signature_failure_rejected_even_with_opt_in(self):
        self.report["signature"]["verify_returncode"] = 1
        with self.assertRaisesRegex(update.UpdateError, "签名"):
            self.stage()

    def test_launch_revalidates_and_preserves_state_scope(self):
        item = self.stage(); update.select(self.root, item["slot"])
        with mock.patch.object(update.subprocess, "run") as launch:
            result = update.launch(self.root, self.directory / "test-state")
        self.assertTrue(result["launch_requested"])
        self.assertFalse(result["gui_ready_verified"])
        self.assertIn("CTFLAB_GUI_STATE_DIR=" + str(self.directory / "test-state"), launch.call_args.args[0])
        (Path(item["app"]) / "data").write_text("篡改")
        with mock.patch.object(update.subprocess, "run") as launch:
            with self.assertRaises(update.UpdateError): update.launch(self.root, self.directory)
            launch.assert_not_called()


if __name__ == "__main__": unittest.main()
