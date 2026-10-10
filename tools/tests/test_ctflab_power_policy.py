"""睡眠避险配置的原子写入、撤销和证据门禁；不写宿主 /etc、不启动来宾。"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "guest_fixes/kali-arm64/power_policy.py"
spec = importlib.util.spec_from_file_location("power_policy", SCRIPT)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class PowerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / policy.RELATIVE_PATH

    def test_atomic_apply_permissions_and_idempotency(self):
        self.assertEqual(policy.installed_state(self.root), "not-installed")
        self.assertTrue(policy.apply_policy(self.root)["changed"])
        self.assertEqual(self.target.read_bytes(), policy.POLICY)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o644)
        before = self.target.stat().st_mtime_ns
        self.assertFalse(policy.apply_policy(self.root)["changed"])
        self.assertEqual(before, self.target.stat().st_mtime_ns)
        self.assertFalse(list(self.target.parent.glob(".ctflab-sleep-*")))

    def test_restore_only_removes_owned_file(self):
        policy.apply_policy(self.root)
        other = self.target.parent / "50-user.conf"
        other.write_text("[Sleep]\nAllowSuspend=yes\n")
        self.assertTrue(policy.restore_policy(self.root)["changed"])
        self.assertEqual(other.read_text(), "[Sleep]\nAllowSuspend=yes\n")
        self.assertFalse(policy.restore_policy(self.root)["changed"])

    def test_unowned_or_modified_file_is_never_overwritten_or_removed(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"user-data")
        for action in (policy.apply_policy, policy.restore_policy):
            with self.assertRaises(ValueError):
                action(self.root)
            self.assertEqual(self.target.read_bytes(), b"user-data")

    def test_target_and_parent_symlinks_are_rejected(self):
        other = self.root / "other"
        other.mkdir()
        self.target.parent.mkdir(parents=True)
        self.target.symlink_to(other / "untouched")
        with self.assertRaises(ValueError):
            policy.apply_policy(self.root)
        self.target.unlink()
        self.target.parent.rmdir()
        self.target.parent.symlink_to(other, target_is_directory=True)
        with self.assertRaises(ValueError):
            policy.apply_policy(self.root)
        self.assertEqual(list(other.iterdir()), [])

    def test_fifo_is_rejected_without_blocking(self):
        self.target.parent.mkdir(parents=True)
        os.mkfifo(self.target)
        with self.assertRaises(ValueError):
            policy.installed_state(self.root)

    def test_failed_publish_leaves_no_target_or_temporary(self):
        with mock.patch.object(policy.os, "link", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                policy.apply_policy(self.root)
        self.assertFalse(self.target.exists())
        self.assertFalse(list(self.target.parent.glob(".ctflab-sleep-*")))

    def test_concurrent_target_is_preserved(self):
        def concurrent(*args, **kwargs):
            self.target.write_bytes(b"concurrent-user")
            raise FileExistsError("exists")
        with mock.patch.object(policy.os, "link", side_effect=concurrent):
            with self.assertRaises(FileExistsError):
                policy.apply_policy(self.root)
        self.assertEqual(self.target.read_bytes(), b"concurrent-user")
        self.assertFalse(list(self.target.parent.glob(".ctflab-sleep-*")))

    def test_scope_excludes_screen_lock_authentication_and_network(self):
        config = policy.POLICY.decode()
        for setting in ("AllowSuspend", "AllowHibernation", "AllowHybridSleep", "AllowSuspendThenHibernate"):
            self.assertIn(setting + "=no", config)
        for setting in ("IdleAction", "HandlePowerKey", "lock-enabled", "autologin", "NetworkManager"):
            self.assertNotIn(setting, config)

    def test_capability_results_do_not_turn_errors_into_no(self):
        responses = [mock.Mock(returncode=0, stdout='s "no"\n'),
                     mock.Mock(returncode=0, stdout='s "na"\n'),
                     mock.Mock(returncode=0, stdout='s "challenge"\n'),
                     mock.Mock(returncode=1, stdout='s "no"\n')]
        with mock.patch.object(policy.subprocess, "run", side_effect=responses):
            self.assertEqual(list(policy.sleep_capabilities().values()), ["no", "na", "challenge", "unknown"])

    def test_capability_timeout_is_unknown(self):
        with mock.patch.object(policy.subprocess, "run", side_effect=subprocess.TimeoutExpired("busctl", 5)):
            self.assertEqual(set(policy.sleep_capabilities().values()), {"unknown"})

    def test_host_platform_is_refused(self):
        with mock.patch.object(policy.sys, "platform", "darwin"):
            with self.assertRaises(ValueError):
                policy.require_guest()
        with mock.patch.object(policy.sys, "platform", "linux"), \
                mock.patch.object(policy.platform, "machine", return_value="x86_64"):
            with self.assertRaises(ValueError):
                policy.require_guest()

    def test_version_gate(self):
        for version, accepted in ((239, False), (240, True), (257, True)):
            with mock.patch.object(policy.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=f"systemd {version}\n")):
                if accepted:
                    policy.require_systemd()
                else:
                    with self.assertRaises(ValueError):
                        policy.require_systemd()

    def test_apply_requires_confirmation_before_write(self):
        with mock.patch.object(policy, "require_guest"), \
                mock.patch.object(policy, "apply_policy") as apply, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                policy.main(["apply"])
            apply.assert_not_called()

    def test_apply_unproven_effect_returns_nonzero(self):
        with mock.patch.object(policy, "require_guest"), \
                mock.patch.object(policy.os, "geteuid", return_value=0), \
                mock.patch.object(policy, "require_systemd"), \
                mock.patch.object(policy, "apply_policy", return_value={"policy": "installed", "changed": True}), \
                mock.patch.object(policy, "sleep_capabilities", return_value={method: "unknown" for method in policy.SLEEP_METHODS}), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(policy.main(["apply", "--confirm"]), 2)
            self.assertFalse(json.loads(output.getvalue())["sleep_block_verified"])

    def test_apply_verified_is_separate_from_file_presence(self):
        with mock.patch.object(policy, "require_guest"), \
                mock.patch.object(policy.os, "geteuid", return_value=0), \
                mock.patch.object(policy, "require_systemd"), \
                mock.patch.object(policy, "apply_policy", return_value={"policy": "installed", "changed": False}), \
                mock.patch.object(policy, "sleep_capabilities", return_value={method: "no" for method in policy.SLEEP_METHODS}), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(policy.main(["apply", "--confirm"]), 0)
            self.assertTrue(json.loads(output.getvalue())["sleep_block_verified"])
