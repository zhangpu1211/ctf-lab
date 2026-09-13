#!/usr/bin/env python3
"""CTFLab ARM64 Kali 安装链路的回归测试。"""

from __future__ import annotations

from pathlib import Path
import gzip
import shutil
import sys
import tempfile
import unittest
from unittest import mock


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from ctflab import (  # noqa: E402
    CTFLabError,
    LabManager,
    build_unattended_preseed,
    prepare_unattended_installer_assets,
    validate_arm64_installer_iso,
    write_json,
)


@mock.patch.dict("os.environ", {"CTFLAB_INSTALL_PASSWORD": "test-only-not-a-secret"})
class PreseedTests(unittest.TestCase):
    def test_preseed_installs_desktop_and_remote_access(self) -> None:
        preseed = build_unattended_preseed()
        self.assertIn("passwd/username string kali", preseed)
        self.assertIn("kali-desktop-xfce", preseed)
        self.assertIn("kali-linux-default", preseed)
        self.assertIn("openssh-server", preseed)
        self.assertIn("partman-auto/disk string /dev/vda", preseed)

    def test_password_is_required_and_cannot_inject_preseed(self) -> None:
        for value in ("", "bad\nd-i injected", "bad\x00value"):
            with self.assertRaises(CTFLabError):
                build_unattended_preseed(password=value)

    def test_preseed_rejects_unsafe_identity_values(self) -> None:
        with self.assertRaises(CTFLabError):
            build_unattended_preseed(username="Kali User")
        with self.assertRaises(CTFLabError):
            build_unattended_preseed(hostname="bad.host")

    @unittest.skipUnless(shutil.which("cpio"), "需要系统 cpio")
    def test_preseed_is_appended_with_macos_compatible_cpio(self) -> None:
        def fake_extract(_iso: Path, member: str, destination: Path) -> None:
            if member.endswith("vmlinuz"):
                destination.write_bytes(b"kernel")
            else:
                with gzip.open(destination, "wb") as handle:
                    handle.write(b"base-initramfs\0\0\0")

        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "ctflab.extract_iso_member", side_effect=fake_extract
        ):
            root = Path(directory)
            kernel, initrd = prepare_unattended_installer_assets(root / "kali.iso", "b" * 64, root / "assets")
            kernel_data = kernel.read_bytes()
            self.assertEqual(initrd.stat().st_mode & 0o777, 0o600)
            self.assertEqual(initrd.parent.stat().st_mode & 0o777, 0o700)
            with gzip.open(initrd, "rb") as handle:
                unpacked = handle.read()

        self.assertEqual(kernel_data, b"kernel")
        self.assertIn(b"preseed.cfg", unpacked)
        self.assertIn(b"kismet-capture-common/install-setuid", unpacked)
        self.assertIn(b"ctflab-guest-setup.sh", unpacked)
        self.assertIn(b"systemctl enable ssh", unpacked)


class IsoValidationTests(unittest.TestCase):
    def test_iso_requires_arm64_installer_members(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            iso = Path(directory) / "kali.iso"
            data = bytearray(0x9000)
            data[0x8001:0x8006] = b"CD001"
            iso.write_bytes(data)
            completed = mock.Mock(returncode=0, stdout="install.a64/vmlinuz\ninstall.a64/gtk/initrd.gz\n", stderr="")
            with mock.patch("ctflab.shutil.which", return_value="/usr/bin/bsdtar"), mock.patch(
                "ctflab.subprocess.run", return_value=completed
            ), mock.patch("ctflab.sha256_file", return_value="a" * 64):
                result = validate_arm64_installer_iso(iso)
        self.assertEqual(result["sha256"], "a" * 64)
        self.assertEqual(result["kernel_member"], "install.a64/vmlinuz")

    def test_non_iso_is_rejected_before_archive_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-an.iso"
            path.write_bytes(b"not an iso")
            with self.assertRaises(CTFLabError):
                validate_arm64_installer_iso(path)


class InstallerCommandTests(unittest.TestCase):
    def test_clipboard_is_scoped_to_graphical_kali(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = LabManager(root)
            for profile, headless in (("smoke", False), ("kali-arm64", True)):
                with self.assertRaises(CTFLabError):
                    manager.qemu_command(profile, {}, root / "disk", 23400, headless, clipboard=True)
            with mock.patch.object(manager, "ensure_uefi_vars", return_value=(root / "code", root / "vars")), mock.patch("ctflab.which_any", return_value="qemu"):
                profile = {"guest": {"architecture": "aarch64"}, "network": {}}
                default, _ = manager.qemu_command("kali-arm64", profile, root / "disk", 23400, False)
                shared, _ = manager.qemu_command("kali-arm64", profile, root / "disk", 23400, False, clipboard=True)
            self.assertNotIn("qemu-vdagent", " ".join(default))
            self.assertIn("clipboard=on,mouse=off", " ".join(shared))
            self.assertIn("cocoa,zoom-to-fit=on", shared)

    def test_arm64_command_uses_hvf_pflash_and_input_devices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = LabManager(root)
            profile = {
                "guest": {"architecture": "aarch64", "machine": "virt", "memory_mb": 5120, "cpus": 4}
            }
            paths = [root / name for name in ("kali.iso", "target.qcow2", "vars.fd", "qmp.sock", "vmlinuz", "initrd.gz")]
            with mock.patch("ctflab.which_any", return_value="/opt/homebrew/bin/qemu-system-aarch64"), mock.patch(
                "ctflab.find_firmware", return_value=Path("/opt/homebrew/share/qemu/edk2-aarch64-code.fd")
            ):
                command = manager.installer_command(
                    "kali-arm64",
                    profile,
                    paths[0],
                    paths[1],
                    paths[2],
                    paths[3],
                    unattended=True,
                    headless=True,
                    kernel_path=paths[4],
                    initrd_path=paths[5],
                )
        joined = " ".join(map(str, command))
        self.assertIn("-accel hvf", joined)
        self.assertIn("if=pflash,format=raw,unit=1", joined)
        self.assertIn("qemu-xhci", command)
        self.assertIn("usb-kbd", command)
        self.assertIn("usb-tablet", command)
        self.assertIn("-display none", joined)
        self.assertIn("preseed/file=/preseed.cfg", joined)
        self.assertIn("-serial stdio", joined)

    def test_preparing_state_without_log_is_reportable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = LabManager(Path(directory))
            write_json(
                manager.installer_state_path("kali-arm64"),
                {"profile_id": "kali-arm64", "pid": 0, "status": "preparing"},
            )
            status = manager.install_status("kali-arm64")
        self.assertFalse(status["running"])
        self.assertEqual(status["log_tail"], "")

    def test_reinstall_requires_explicit_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = LabManager(Path(directory))
            write_json(manager.installer_state_path("kali-arm64"), {"pid": 0})
            with self.assertRaisesRegex(CTFLabError, "confirm-reinstall"):
                manager.start_install("kali-arm64", "unused.iso", unattended=True, resume=True)

    def test_online_maintenance_rejects_targets_and_mode_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = LabManager(Path(directory))
            with self.assertRaisesRegex(CTFLabError, "只能单独"):
                manager.run(["smoke"], allow_internet=True)
            with mock.patch.object(manager, "running_states", return_value=[{"profile_id": "smoke"}]), self.assertRaisesRegex(CTFLabError, "停止其他靶机"):
                manager.run(["kali-arm64"], allow_internet=True)
            online = [{"profile_id": "kali-arm64", "internet_enabled": True}]
            with mock.patch.object(manager, "running_states", return_value=online):
                with self.assertRaisesRegex(CTFLabError, "联网维护"):
                    manager.run(["smoke"])
                with self.assertRaisesRegex(CTFLabError, "切换联网模式"):
                    manager.run(["kali-arm64"])

    def test_running_or_incomplete_install_cannot_be_finalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = LabManager(Path(directory))
            with mock.patch.object(manager, "install_status", return_value={"running": True}):
                with self.assertRaisesRegex(CTFLabError, "仍在运行"):
                    manager.finalize_install("kali-arm64", confirmed=True)
            incomplete = {"running": False, "unattended": True, "completion_hint": False, "target_path": "missing", "uefi_vars_path": "missing"}
            with mock.patch.object(manager, "install_status", return_value=incomplete):
                with self.assertRaisesRegex(CTFLabError, "半成品"):
                    manager.finalize_install("kali-arm64", confirmed=True)


if __name__ == "__main__":
    unittest.main()
