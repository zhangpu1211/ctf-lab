#!/usr/bin/env python3
"""快照、重置前备份与存储清单的回归测试（qemu-img 小型夹具，无虚拟机）。"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import ctflab  # noqa: E402
from ctflab import CTFLabError, LabManager, qemu_img_path, write_json  # noqa: E402

PROFILE = "smoke"


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.manager = LabManager(Path(self._tmp.name))
        # 4M 基础镜像 + 登记，保证 overlay 可创建且 backing chain 可校验。
        self.base = Path(self._tmp.name) / "base.qcow2"
        subprocess.run([qemu_img_path(), "create", "-f", "qcow2",
                        str(self.base), "4M"], check=True, capture_output=True)
        destination = self.manager.image_state_path(PROFILE)
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_json(destination, {"schema": 1, "profile_id": PROFILE,
                                 "base_path": str(self.base)})
        self.overlay = self.manager.ensure_overlay(PROFILE)
        self.instance_dir = self.manager.runtime_dir / PROFILE

    def nvram_path(self) -> Path:
        return self.instance_dir / "uefi-vars.fd"

    def test_create_list_revert_delete_roundtrip(self):
        self.manager.snapshot_create(PROFILE, "baseline")
        self.manager.snapshot_create(PROFILE, "after-lab")
        tags = [item["tag"] for item in self.manager.snapshot_list(PROFILE)]
        self.assertEqual(tags, ["baseline", "after-lab"])
        result = self.manager.snapshot_revert(PROFILE, "baseline")
        self.assertEqual(result["reverted"], "baseline")
        self.manager.snapshot_delete(PROFILE, "after-lab")
        tags = [item["tag"] for item in self.manager.snapshot_list(PROFILE)]
        self.assertEqual(tags, ["baseline"])
        with self.assertRaisesRegex(CTFLabError, "已存在"):
            self.manager.snapshot_create(PROFILE, "baseline")
        with self.assertRaisesRegex(CTFLabError, "不存在"):
            self.manager.snapshot_revert(PROFILE, "after-lab")
        with self.assertRaisesRegex(CTFLabError, "不存在"):
            self.manager.snapshot_delete(PROFILE, "missing")

    def test_snapshot_names_are_validated(self):
        for bad in ("has space", "中文快照", "-leading", "UPPER", "a" * 33, ""):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(CTFLabError, "不合法"):
                    self.manager.snapshot_create(PROFILE, bad)

    def test_revert_restores_paired_nvram(self):
        nvram = self.nvram_path()
        nvram.write_bytes(b"VARS-1")
        self.manager.snapshot_create(PROFILE, "with-nvram")
        nvram.write_bytes(b"VARS-2")
        result = self.manager.snapshot_revert(PROFILE, "with-nvram")
        self.assertTrue(result["nvram_restored"])
        self.assertEqual(nvram.read_bytes(), b"VARS-1")
        self.manager.snapshot_delete(PROFILE, "with-nvram")
        self.assertFalse((self.instance_dir / "uefi-vars.fd.snapshot-with-nvram").exists())

    def test_operations_refuse_running_node(self):
        write_json(self.manager.runtime_state_path(PROFILE), {
            "schema": 1, "profile_id": PROFILE, "pid": 4242,
            "qmp_path": str(self.instance_dir / "qmp.sock"),
            "log_path": str(self.manager.logs_dir / f"{PROFILE}.log"),
            "started_at": ctflab.now_iso(),
        })
        with mock.patch.object(ctflab, "bool_pid_alive", return_value=True):
            for action in (lambda: self.manager.snapshot_create(PROFILE, "x"),
                           lambda: self.manager.snapshot_revert(PROFILE, "x"),
                           lambda: self.manager.snapshot_delete(PROFILE, "x"),
                           lambda: self.manager.backup_restore(PROFILE, "x")):
                with self.subTest(action=action):
                    with self.assertRaisesRegex(CTFLabError, "正在运行"):
                        action()

    def test_reset_backup_preserves_and_restores_instance(self):
        nvram = self.nvram_path()
        nvram.write_bytes(b"KEEP-ME")
        self.manager.snapshot_create(PROFILE, "inside")
        self.manager.reset(PROFILE, backup_name="pre-reset")
        # runtime 目录被清空，但备份区保留 overlay+NVRAM；内部快照随 overlay 走。
        self.assertFalse(self.overlay.exists())
        backups = self.manager.backups_list(PROFILE)
        self.assertEqual([b["name"] for b in backups], ["pre-reset"])
        self.assertTrue(backups[0]["complete"])
        with self.assertRaisesRegex(CTFLabError, "已存在"):
            self.manager.reset(PROFILE, backup_name="pre-reset")
        result = self.manager.backup_restore(PROFILE, "pre-reset")
        self.assertEqual(result["restored_backup"], "pre-reset")
        self.assertTrue(self.overlay.exists())
        self.assertEqual(nvram.read_bytes(), b"KEEP-ME")
        self.assertIn("inside",
                      [item["tag"] for item in self.manager.snapshot_list(PROFILE)])
        self.assertTrue(self.manager.snapshot_revert(PROFILE, "inside")["nvram_restored"])
        self.assertEqual(self.manager.backups_list(PROFILE), [])

    def test_backup_preserves_snapshot_nvram_history(self):
        nvram = self.nvram_path()
        nvram.write_bytes(b"BEFORE")
        self.manager.snapshot_create(PROFILE, "s")
        nvram.write_bytes(b"AFTER")
        self.manager.reset(PROFILE, backup_name="saved")
        self.manager.backup_restore(PROFILE, "saved")
        self.manager.snapshot_revert(PROFILE, "s")
        self.assertEqual(nvram.read_bytes(), b"BEFORE")

    def test_missing_nvram_pair_rejected_before_disk_revert(self):
        self.nvram_path().write_bytes(b"BEFORE")
        self.manager.snapshot_create(PROFILE, "s")
        (self.instance_dir / "uefi-vars.fd.snapshot-s").unlink()
        with mock.patch.object(ctflab, "run_command", wraps=ctflab.run_command) as run:
            with self.assertRaisesRegex(CTFLabError, "缺少配对"):
                self.manager.snapshot_revert(PROFILE, "s")
        self.assertFalse(any("-a" in call.args[0] for call in run.call_args_list))

    def test_remove_refuses_base_with_backup_references(self):
        self.manager.reset(PROFILE, backup_name="saved")
        with self.assertRaisesRegex(CTFLabError, "整盘备份依赖"):
            self.manager.remove_image(PROFILE)
        self.assertTrue(self.manager.image_state_path(PROFILE).exists())
        self.assertTrue((self.manager._backup_root(PROFILE) / "saved/overlay.qcow2").exists())

    def test_backup_move_failure_preserves_instance(self):
        self.nvram_path().write_bytes(b"SAFE")
        self.manager.snapshot_create(PROFILE, "s")
        with mock.patch.object(ctflab.os, "rename", side_effect=OSError("injected")):
            with self.assertRaises(OSError):
                self.manager.reset(PROFILE, backup_name="saved")
        self.assertTrue(self.overlay.exists())
        self.assertTrue((self.instance_dir / "uefi-vars.fd.snapshot-s").exists())
        self.assertFalse((self.manager._backup_root(PROFILE) / "saved").exists())

    def test_restore_failure_rolls_back_current_instance(self):
        self.manager.reset(PROFILE, backup_name="saved")
        self.manager.ensure_overlay(PROFILE)
        marker = self.instance_dir / "current-marker"
        marker.write_bytes(b"CURRENT")
        rename = ctflab.os.rename
        def fail_source(source, dest):
            if Path(source).name == "saved":
                raise OSError("injected restore failure")
            return rename(source, dest)
        with mock.patch.object(ctflab.os, "rename", side_effect=fail_source):
            with self.assertRaises(OSError):
                self.manager.backup_restore(PROFILE, "saved")
        self.assertEqual(marker.read_bytes(), b"CURRENT")
        self.assertTrue((self.manager._backup_root(PROFILE) / "saved/overlay.qcow2").exists())

    def test_restore_retains_previous_instance_as_backup(self):
        self.manager.reset(PROFILE, backup_name="saved")
        self.manager.ensure_overlay(PROFILE)
        (self.instance_dir / "marker").write_text("keep")
        result = self.manager.backup_restore(PROFILE, "saved")
        previous = self.manager._backup_root(PROFILE) / result["previous_backup"]
        self.assertEqual((previous / "marker").read_text(), "keep")

    def test_restore_rejects_missing_backing_without_changes(self):
        self.manager.reset(PROFILE, backup_name="saved")
        self.base.rename(self.base.with_suffix(".moved"))
        with self.assertRaisesRegex(CTFLabError, "基础盘不存在"):
            self.manager.backup_restore(PROFILE, "saved")
        self.assertTrue((self.manager._backup_root(PROFILE) / "saved/overlay.qcow2").exists())

    def test_explicit_delete_backup_allows_image_removal(self):
        self.manager.reset(PROFILE, backup_name="saved")
        self.manager.backup_delete(PROFILE, "saved")
        self.assertTrue(self.manager.image_state_path(PROFILE).exists())
        self.manager.remove_image(PROFILE)
        self.assertFalse(self.manager.image_state_path(PROFILE).exists())
        with self.assertRaises(CTFLabError):
            self.manager.backup_delete(PROFILE, "saved")

    def test_backup_delete_rejects_traversal_and_symlinks(self):
        self.manager.reset(PROFILE, backup_name="saved")
        with self.assertRaises(CTFLabError):
            self.manager.backup_delete(PROFILE, "../saved")
        link = self.manager._backup_root(PROFILE) / "link"
        link.symlink_to(link.parent / "saved", target_is_directory=True)
        with self.assertRaises(CTFLabError):
            self.manager.backup_delete(PROFILE, "link")
        self.assertTrue((link.parent / "saved/overlay.qcow2").exists())

    def test_plain_reset_discards_snapshots(self):
        self.manager.snapshot_create(PROFILE, "gone")
        self.manager.reset(PROFILE)
        self.assertFalse(self.overlay.exists())
        with self.assertRaisesRegex(CTFLabError, "没有可操作的 overlay"):
            self.manager.snapshot_list(PROFILE)

    def test_storage_report_covers_chain_snapshots_and_backups(self):
        self.manager.snapshot_create(PROFILE, "listed")
        write_json(self.manager.runtime_state_path(PROFILE), {
            "schema": 1, "profile_id": PROFILE, "pid": 4242,
            "qmp_path": str(self.instance_dir / "qmp.sock"),
            "log_path": str(self.manager.logs_dir / f"{PROFILE}.log"),
            "started_at": ctflab.now_iso(),
        })
        with mock.patch.object(ctflab, "bool_pid_alive", return_value=True):
            report = self.manager.storage_report()
        entry = next(item for item in report["profiles"] if item["id"] == PROFILE)
        self.assertTrue(entry["imported"] and entry["running"])
        self.assertTrue(entry["base_referenced"])
        self.assertGreater(entry["base"]["actual_bytes"], 0)
        self.assertTrue(entry["overlay"]["backing_ok"])
        self.assertEqual(entry["overlay"]["backing_path"], str(self.base))
        self.assertIn("listed", [s["tag"] for s in entry["snapshots"]])
        self.assertEqual(entry["backups"], [])

    def test_cli_wires_snapshot_storage_and_reset_backup(self):
        parser = ctflab.build_parser()
        parsed = parser.parse_args(["snapshot", "create", PROFILE, "lab-1"])
        self.assertEqual(parsed.snapshot_command, "create")
        self.assertEqual(parsed.name, "lab-1")
        parsed = parser.parse_args(["snapshot", "restore-backup", PROFILE, "pre-reset"])
        self.assertEqual(parsed.snapshot_command, "restore-backup")
        parsed = parser.parse_args(["storage", "--json"])
        self.assertTrue(parsed.json)
        parsed = parser.parse_args(["reset", PROFILE, "--backup", "before-class"])
        self.assertEqual(parsed.backup, "before-class")


if __name__ == "__main__":
    unittest.main()
