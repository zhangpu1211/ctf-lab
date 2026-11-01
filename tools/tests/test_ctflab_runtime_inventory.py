"""运行时清单的合成边界验证，不运行QEMU。"""
import copy
from contextlib import redirect_stdout, redirect_stderr
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab_runtime_inventory as inv


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()/'runtime'
        self.root.mkdir()
        (self.root/'qemu-system-x86_64.exe').write_bytes(b'fixture-not-executable')
        (self.root/'share').mkdir()
        (self.root/'share'/'bios.bin').write_bytes(b'firmware')

    def test_windows_path_and_handle_timestamp_semantics_match(self):
        from types import SimpleNamespace
        path = SimpleNamespace(st_dev=7, st_ino=91, st_size=10, st_mtime_ns=100,
                               st_ctime_ns=20, st_birthtime_ns=20)
        handle = SimpleNamespace(**{**vars(path), 'st_ctime_ns': 200})
        with mock.patch.object(inv.os, 'name', 'nt'):
            self.assertEqual(inv.signature(path), inv.signature(handle))
            for field in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_birthtime_ns'):
                changed = SimpleNamespace(**{**vars(handle), field: getattr(handle, field)+1})
                self.assertNotEqual(inv.signature(path), inv.signature(changed), field)

    def test_posix_still_checks_metadata_change_time(self):
        from types import SimpleNamespace
        path = SimpleNamespace(st_dev=7, st_ino=91, st_size=10, st_mtime_ns=100,
                               st_ctime_ns=20, st_birthtime_ns=20)
        changed = SimpleNamespace(**{**vars(path), 'st_ctime_ns': 200})
        with mock.patch.object(inv.os, 'name', 'posix'):
            self.assertNotEqual(inv.signature(path), inv.signature(changed))

    def test_stable_complete_directory_but_not_verified_runtime(self):
        first = inv.inventory(self.root)
        self.assertEqual(first, inv.inventory(self.root))
        self.assertEqual(len(first['files']), 2)
        self.assertNotIn(str(self.root), str(first))
        for key in ('components_complete', 'dependency_closure_verified', 'source_verified', 'g0_passed'):
            self.assertFalse(first[key])

    def test_added_removed_changed(self):
        first = inv.inventory(self.root)
        (self.root/'share'/'bios.bin').unlink()
        (self.root/'qemu-system-x86_64.exe').write_bytes(b'changed')
        (self.root/'new.dll').write_bytes(b'new')
        diff = inv.compare(first, inv.inventory(self.root))
        self.assertEqual(diff['removed'], ['share/bios.bin'])
        self.assertEqual(diff['added'], ['new.dll'])
        self.assertEqual(diff['changed'], ['qemu-system-x86_64.exe'])
        self.assertFalse(diff['matches'])

    def test_hardlink_rejected(self):
        os.link(self.root/'qemu-system-x86_64.exe', self.root/'alias')
        with self.assertRaises(inv.InventoryError): inv.inventory(self.root)

    def test_symlink_rejected(self):
        try: (self.root/'alias').symlink_to(self.root/'share', target_is_directory=True)
        except OSError as exc: self.skipTest('宿主不允许创建符号链接: '+str(exc.errno))
        with self.assertRaises(inv.InventoryError): inv.inventory(self.root)

    def test_changed_during_scan_rejected(self):
        original = inv.hash_file
        def change(path, expected):
            value = original(path, expected)
            if path.name.endswith('.exe'): path.write_bytes(b'changed')
            return value
        with mock.patch.object(inv, 'hash_file', side_effect=change):
            with self.assertRaises(inv.InventoryError): inv.inventory(self.root)

    def test_limits(self):
        with mock.patch.object(inv, 'MAX_BYTES', 1):
            with self.assertRaises(inv.InventoryError): inv.inventory(self.root)

    def test_reference_tampering_and_traversal(self):
        original = inv.inventory(self.root)
        for mutation in ('digest', 'path', 'duplicate'):
            value = copy.deepcopy(original)
            if mutation == 'digest': value['files'][0]['sha256'] = '0'*64
            elif mutation == 'path': value['files'][0]['name'] = '../escape'
            else: value['files'].append(value['files'][0])
            with self.assertRaises(inv.InventoryError): inv.validate_reference(value)

    def test_cli_never_overwrites_or_writes_inside_runtime(self):
        output = self.root.parent/'report.json'
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(inv.main(['--root', str(self.root), '--output', str(output)]), 0)
            saved = output.read_bytes()
            self.assertEqual(inv.main(['--root', str(self.root), '--output', str(output)]), 1)
            self.assertEqual(output.read_bytes(), saved)
            self.assertEqual(inv.main(['--root', str(self.root), '--output', str(self.root/'report.json')]), 1)
            (self.root/'added.dll').write_bytes(b'x')
            self.assertEqual(inv.main(['--root', str(self.root), '--output', str(output.with_name('second.json')), '--compare', str(output)]), 2)
