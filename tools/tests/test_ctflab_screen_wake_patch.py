"""锁屏唤醒源码补丁的门禁与排他输出；不编译或替换屏保程序。"""
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "guest_fixes/kali-arm64/screen_wake_patch.py"
spec = importlib.util.spec_from_file_location("screen_wake_patch", SCRIPT)
wake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wake)
FIXTURE = ("/* isolated test source */\n" + wake.OLD_RATIO + "\n" + wake.OLD_DISTANCE +
           "\n    maybe_handle_activity (window);\n").encode()


class WakePatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / "wake.patch"

    def trusted(self):
        return mock.patch.object(wake, "SOURCE_SHA256", hashlib.sha256(FIXTURE).hexdigest())

    def test_real_source_pin_is_fixed(self):
        self.assertEqual(wake.SOURCE_SHA256, "5fec2129f0217c7ff6e1d9d16a5d3c4878649a7aa6ba2121d41872a114e89c7f")
        self.assertIn("xfce4-screensaver-4.20.2", wake.SOURCE_URL)

    def test_only_two_motion_lines_change(self):
        with self.trusted():
            updated = wake.patched_source(FIXTURE)
            self.assertEqual(updated.replace(wake.NEW_RATIO, wake.OLD_RATIO)
                             .replace(wake.NEW_DISTANCE, wake.OLD_DISTANCE), FIXTURE.decode())
            self.assertIn("maybe_handle_activity (window);", updated)
            self.assertIn("8.0, 24.0", updated)

    def test_unknown_changed_and_already_patched_sources_refused(self):
        for source in (b"unknown", FIXTURE, FIXTURE + b"x", b"x" * (wake.MAX_SOURCE_BYTES + 1)):
            with self.assertRaises(ValueError):
                wake.make_patch(source)
        with self.trusted():
            already = wake.patched_source(FIXTURE).encode()
            with self.assertRaises(ValueError):
                wake.make_patch(already)

    def test_duplicate_or_missing_anchor_refused_even_with_matching_hash(self):
        for source in (FIXTURE + wake.OLD_RATIO.encode(), FIXTURE.replace(wake.OLD_DISTANCE.encode(), b"")):
            with mock.patch.object(wake, "SOURCE_SHA256", hashlib.sha256(source).hexdigest()):
                with self.assertRaises(ValueError):
                    wake.make_patch(source)

    def test_patch_has_honest_status_and_standard_paths(self):
        with self.trusted():
            patch = wake.make_patch(FIXTURE).decode()
        self.assertIn("Runtime acceptance: NOT VERIFIED", patch)
        self.assertIn("--- a/src/gs-window.c", patch)
        self.assertIn("+++ b/src/gs-window.c", patch)
        self.assertNotIn("sudo", patch)

    def test_exclusive_publish_permissions_hash_and_cleanup(self):
        with self.trusted():
            digest = wake.publish_patch(FIXTURE, self.output)
        self.assertEqual(digest, hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o644)
        self.assertFalse(list(self.root.glob(".ctflab-wake-*")))

    def test_existing_output_unchanged(self):
        self.output.write_bytes(b"user")
        with self.trusted(), self.assertRaises(ValueError):
            wake.publish_patch(FIXTURE, self.output)
        self.assertEqual(self.output.read_bytes(), b"user")

    def test_publish_failure_and_concurrent_file_are_preserved(self):
        def race(*args, **kwargs):
            self.output.write_bytes(b"concurrent")
            raise FileExistsError("race")
        with self.trusted(), mock.patch.object(wake.os, "link", side_effect=race):
            with self.assertRaises(OSError):
                wake.publish_patch(FIXTURE, self.output)
        self.assertEqual(self.output.read_bytes(), b"concurrent")
        self.assertFalse(list(self.root.glob(".ctflab-wake-*")))

    def test_source_symlink_and_fifo_rejected(self):
        source = self.root / "source"
        source.symlink_to(self.output)
        with self.assertRaises(OSError):
            wake.read_source(source)
        source.unlink()
        os.mkfifo(source)
        with self.assertRaises(ValueError):
            wake.read_source(source)

    def test_output_parent_link_rejected(self):
        link = self.root / "alias"
        link.symlink_to(self.root, target_is_directory=True)
        with self.trusted(), self.assertRaises(ValueError):
            wake.publish_patch(FIXTURE, link / "wake.patch")
        self.assertFalse(self.output.exists())

    def test_invalid_source_never_creates_output(self):
        with self.assertRaises(ValueError):
            wake.publish_patch(b"invalid", self.output)
        self.assertEqual(list(self.root.iterdir()), [])
