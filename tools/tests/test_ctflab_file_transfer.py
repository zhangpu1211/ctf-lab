"""文本共享与文件写入的独立授权：不操作真实剪贴板或来宾。"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab


class FileTransferTests(unittest.TestCase):
    def test_flags_are_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ctflab.LabManager(Path(directory))
            for clipboard in (False, True):
                for files in (False, True):
                    with self.subTest(clipboard=clipboard, files=files), \
                         mock.patch.object(ctflab, "which_any", return_value="/qemu"), \
                         mock.patch.object(manager, "probe_spice", return_value={"supported": True}), \
                         mock.patch.object(manager, "ensure_uefi_vars", return_value=(Path("/code.fd"), Path("/vars.fd"))):
                        command, _ = manager.qemu_command(
                            "kali-arm64", ctflab.load_profile("kali-arm64"), Path("/overlay"),
                            12345, False, clipboard=clipboard, display="spice", file_transfer=files)
                    flags = command[command.index("-spice") + 1]
                    self.assertIn("disable-copy-paste=" + ("off" if clipboard else "on"), flags)
                    self.assertIn("disable-agent-file-xfer=" + ("off" if files else "on"), flags)
                    client = ctflab.spice_client_command("/bin/spicy", Path("/socket"),
                                                       clipboard=clipboard, file_transfer=files)
                    self.assertEqual("--clipboard" in client, clipboard)
                    self.assertEqual("--file-transfer" in client, files)

    def test_unknown_client_cannot_receive_file_permission(self):
        with self.assertRaises(ctflab.CTFLabError):
            ctflab.spice_client_command("/bin/remote-viewer", Path("/sock"), file_transfer=True)

    def test_parser_does_not_couple_permissions(self):
        parser = ctflab.build_parser()
        text = parser.parse_args(["run", "kali-arm64", "--clipboard"])
        self.assertFalse(text.file_transfer)
        files = parser.parse_args(["run", "kali-arm64", "--file-transfer"])
        self.assertFalse(files.clipboard)

    def test_cocoa_file_transfer_rejected_before_start(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ctflab.LabManager(Path(directory))
            with mock.patch.object(ctflab, "check_host_resources", return_value=[]), \
                 mock.patch.object(manager, "ensure_network") as network:
                with self.assertRaises(ctflab.CTFLabError):
                    manager.run(["kali-arm64"], display="cocoa", file_transfer=True)
                network.assert_not_called()
