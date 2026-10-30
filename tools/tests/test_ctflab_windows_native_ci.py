"""云端原生检查准备器的安全输入测试；不把本机测试当成Windows验收。"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

path = Path(__file__).resolve().parents[2]/'desktop/windows_native_ci.py'
spec = importlib.util.spec_from_file_location('windows_native_ci', path)
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class NativePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def archive(self, files=None, extra=None, manifest_update=None):
        files = files or {'desktop/Build-Windows.ps1': b'# fixture'}
        manifest = {'schema': 1, 'version': '0.1.4', 'kind': 'source-snapshot',
                    'files': {n: hashlib.sha256(raw).hexdigest() for n,raw in files.items()}}
        if manifest_update: manifest_update(manifest)
        path = self.root/'source.zip'
        with zipfile.ZipFile(path, 'x') as archive:
            archive.writestr('SOURCE-MANIFEST.json', json.dumps(manifest))
            for name, raw in files.items(): archive.writestr(name, raw)
            if extra: extra(archive)
        return path

    def test_valid_archive_has_exact_verified_payload(self):
        path = self.archive()
        self.assertEqual(ci.snapshot_files(path), {'desktop/Build-Windows.ps1': b'# fixture'})
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_rejects_traversal_before_extraction(self):
        path = self.archive(files={'../outside.py': b'payload'})
        with self.assertRaises(ValueError): ci.snapshot_files(path)
        self.assertFalse((self.root.parent/'outside.py').exists())

    def test_rejects_windows_alias_even_if_manifest_matches(self):
        path = self.archive(files={'tools/run.py': b'a', 'TOOLS/RUN.py': b'b'})
        with self.assertRaises(ValueError): ci.snapshot_files(path)

    def test_rejects_symlink_before_extraction(self):
        def add(archive):
            info = zipfile.ZipInfo('link.py'); info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, '../outside')
        path = self.archive(extra=add)
        with self.assertRaises(ValueError): ci.snapshot_files(path)

    def test_rejects_unlisted_file(self):
        path = self.archive(extra=lambda a: a.writestr('extra.exe', b'unlisted'))
        with self.assertRaises(ValueError): ci.snapshot_files(path)

    def test_rejects_changed_payload(self):
        path = self.archive(manifest_update=lambda m: m['files'].update({'desktop/Build-Windows.ps1': '0'*64}))
        with self.assertRaises(ValueError): ci.snapshot_files(path)

    def test_rejects_missing_manifest_payload(self):
        path = self.archive(manifest_update=lambda m: m['files'].update({'missing.py': '0'*64}))
        with self.assertRaises(ValueError): ci.snapshot_files(path)

    def test_rejects_wrong_snapshot_kind(self):
        path = self.archive(manifest_update=lambda m: m.update(kind='source-test-fixture'))
        with self.assertRaises(ValueError): ci.snapshot_files(path)

    def test_copy_refuses_existing_destination(self):
        src = self.root/'original'; src.write_bytes(b'new')
        dst = self.root/'destination'; dst.write_bytes(b'preserved')
        with self.assertRaises(FileExistsError): ci.copy_plain(src, dst)
        self.assertEqual(dst.read_bytes(), b'preserved')

    def test_copy_refuses_source_symlink(self):
        src = self.root/'original'; src.write_bytes(b'original')
        link = self.root/'link'; link.symlink_to(src)
        with self.assertRaises(ValueError): ci.copy_plain(link, self.root/'copy')
        self.assertFalse((self.root/'copy').exists())

    def test_mismatched_download_is_preserved_without_execution(self):
        response = io.BytesIO(b'changed'); response.url = 'https://example.invalid/fixed'
        target = self.root/'download.exe'
        with patch.object(ci.urllib.request, 'urlopen', return_value=response):
            with self.assertRaises(ValueError): ci.download(response.url, target, '0'*64)
        self.assertEqual(target.read_bytes(), b'changed')

    def test_overlay_rejects_source_drift_without_writing(self):
        source = self.root/'source'; path = source/'desktop/src-tauri/src/main.rs'
        path.parent.mkdir(parents=True); path.write_bytes(b'changed-source')
        results = self.root/'results'; results.mkdir()
        with self.assertRaises(ValueError): ci.apply_native_overlay(source, results)
        self.assertEqual(path.read_bytes(), b'changed-source')
        self.assertEqual(list(results.iterdir()), [])

    def test_overlay_binds_candidate_and_keeps_release_archive_separate(self):
        source = self.root/'source'; path = source/'desktop/src-tauri/src/main.rs'
        path.parent.mkdir(parents=True)
        raw = b'cmd.args(["-I", "-B"]).arg(script);'; path.write_bytes(raw)
        results = self.root/'results'; results.mkdir()
        with patch.object(ci, 'RUST_RELEASE_SHA256', hashlib.sha256(raw).hexdigest()):
            ci.apply_native_overlay(source, results)
        self.assertIn(b'"-X", "utf8"', path.read_bytes())
        value = json.loads((results/'candidate-source-overlay.json').read_text())
        self.assertEqual(value['candidate_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertFalse(value['already_public_release'])

    def test_pe_overlay_refuses_drift_without_mutation(self):
        source=self.root/'source';results=self.root/'results'
        (source/'tools').mkdir(parents=True);results.mkdir()
        target=source/'tools/ctflab_pe_dependencies.py';target.write_bytes(b'changed')
        with self.assertRaises(ValueError): ci.apply_pe_overlay(source,results)
        self.assertEqual(target.read_bytes(),b'changed')
        self.assertEqual(list(results.iterdir()),[])

    def test_inventory_overlay_refuses_drift(self):
        source = self.root/'source'; path = source/'tools/ctflab_runtime_inventory.py'
        path.parent.mkdir(parents=True); path.write_bytes(b'changed-source')
        results = self.root/'results'; results.mkdir()
        with self.assertRaises(ValueError): ci.apply_inventory_overlay(source, results)
        self.assertEqual(path.read_bytes(), b'changed-source')
        self.assertEqual(list(results.iterdir()), [])

    def test_non_windows_cannot_create_run_directory(self):
        if os.name == 'nt': self.skipTest('本用例验证非Windows拒绝边界')
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'Windows', 'RUNNER_TEMP': str(self.root)}):
            with self.assertRaises(ValueError): ci.run()
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__': unittest.main()
