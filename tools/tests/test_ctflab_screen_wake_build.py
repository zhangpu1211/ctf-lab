"""屏保候选的离线准备、完整性门禁与只读系统构建边界。"""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "guest_fixes/kali-arm64"
spec = importlib.util.spec_from_file_location("screen_wake_build", SCRIPTS / "screen_wake_build.py")
builder = importlib.util.module_from_spec(spec)
with mock.patch.object(sys, "path", [str(SCRIPTS)] + sys.path):
    spec.loader.exec_module(builder)
wake = builder.wake
SOURCE = (wake.OLD_RATIO + "\n" + wake.OLD_DISTANCE + "\n").encode()


def archive(extra=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:xz") as handle:
        for name, data in [(builder.TOP + "/src/gs-window.c", SOURCE),
                           (builder.TOP + "/meson.build", b"trusted fixture")]:
            member = tarfile.TarInfo(name)
            member.size = len(data)
            handle.addfile(member, io.BytesIO(data))
        if extra:
            member = tarfile.TarInfo(extra[0])
            member.type = extra[1]
            member.linkname = "/etc/passwd"
            handle.addfile(member)
    return output.getvalue()


class WakeBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.out = self.root / "bundle"
        self.data = archive()
        self.pins = mock.patch.multiple(builder, ARCHIVE_SHA256=hashlib.sha256(self.data).hexdigest())
        self.pins.start()
        self.addCleanup(self.pins.stop)
        self.source_pin = mock.patch.object(wake, "SOURCE_SHA256", hashlib.sha256(SOURCE).hexdigest())
        self.source_pin.start()
        self.addCleanup(self.source_pin.stop)

    def test_prepare_and_verify_preserve_authentication_and_original(self):
        result = builder.prepare(self.data, self.out)
        self.assertEqual(builder.verify_bundle(self.out), result)
        self.assertFalse(result["runtime_verified"])
        self.assertEqual(result["authentication"], "pam")
        self.assertEqual((self.out / "official-source.tar.xz").read_bytes(), self.data)
        self.assertIn(wake.NEW_DISTANCE, (self.out / builder.TOP / "src/gs-window.c").read_text())

    def test_unknown_archive_does_not_create_output(self):
        with self.assertRaises(ValueError):
            builder.prepare(b"unknown", self.out)
        self.assertFalse(self.out.exists())

    def test_existing_output_is_not_touched(self):
        self.out.mkdir()
        (self.out / "user").write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            builder.prepare(self.data, self.out)
        self.assertEqual((self.out / "user").read_bytes(), b"keep")

    def test_archive_links_devices_and_traversal_are_refused(self):
        for name, kind in [(builder.TOP + "/alias", tarfile.SYMTYPE),
                           (builder.TOP + "/hard", tarfile.LNKTYPE),
                           (builder.TOP + "/fifo", tarfile.FIFOTYPE),
                           (builder.TOP + "/../escape", tarfile.REGTYPE)]:
            data = archive((name, kind))
            with mock.patch.object(builder, "ARCHIVE_SHA256", hashlib.sha256(data).hexdigest()):
                with self.assertRaises(ValueError):
                    builder.prepare(data, self.out)
            self.assertFalse(self.out.exists())

    def test_tampering_source_and_manifest_cannot_reauthorize_source(self):
        builder.prepare(self.data, self.out)
        target = self.out / builder.TOP / "meson.build"
        target.write_bytes(b"untrusted")
        manifest = json.loads((self.out / "MANIFEST.json").read_text())
        manifest["files"][builder.TOP + "/meson.build"] = hashlib.sha256(b"untrusted").hexdigest()
        (self.out / "MANIFEST.json").write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            builder.verify_bundle(self.out)

    def test_extra_source_or_symlink_refused(self):
        builder.prepare(self.data, self.out)
        extra = self.out / builder.TOP / "untracked"
        extra.write_bytes(b"extra")
        with self.assertRaises(ValueError):
            builder.verify_bundle(self.out)
        extra.unlink()
        extra.symlink_to(self.root)
        with self.assertRaises(ValueError):
            builder.verify_bundle(self.out)

    def test_partial_prepare_failure_cleans_only_owned_directory(self):
        existing = self.root / "user"
        existing.write_bytes(b"keep")
        with mock.patch.object(Path, "write_bytes", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                builder.prepare(self.data, self.out)
        self.assertFalse(self.out.exists())
        self.assertEqual(existing.read_bytes(), b"keep")

    def test_host_and_root_build_are_refused_without_processes(self):
        for system, machine, uid in [("darwin", "arm64", 501), ("linux", "aarch64", 0)]:
            with mock.patch.object(builder.sys, "platform", system), \
                    mock.patch.object(builder.platform, "machine", return_value=machine), \
                    mock.patch.object(builder.os, "geteuid", return_value=uid), \
                    mock.patch.object(builder.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    builder.build(self.out)
                run.assert_not_called()

    def test_build_is_staged_pam_no_download_no_sudo(self):
        builder.prepare(self.data, self.out)
        with mock.patch.object(builder.sys, "platform", "linux"), \
                mock.patch.object(builder.platform, "machine", return_value="aarch64"), \
                mock.patch.object(builder.os, "geteuid", return_value=1000), \
                mock.patch.object(builder.shutil, "which", return_value="tool"), \
                mock.patch.object(builder.subprocess, "run") as run:
            result = builder.build(self.out)
        self.assertFalse(result["runtime_verified"])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn("-Dauthentication-scheme=pam", commands[0])
        self.assertIn("--wrap-mode=nodownload", commands[0])
        self.assertEqual(commands[-1][-2:], ["--destdir", str(self.out / "stage")])
        self.assertFalse(any("sudo" in command for command in commands))

    def test_build_failure_never_records_success(self):
        builder.prepare(self.data, self.out)
        with mock.patch.object(builder.sys, "platform", "linux"), \
                mock.patch.object(builder.platform, "machine", return_value="aarch64"), \
                mock.patch.object(builder.os, "geteuid", return_value=1000), \
                mock.patch.object(builder.shutil, "which", return_value="tool"), \
                mock.patch.object(builder.subprocess, "run", side_effect=OSError("missing dependency")):
            with self.assertRaises(OSError):
                builder.build(self.out)
        self.assertFalse((self.out / "BUILD.json").exists())
