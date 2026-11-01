"""安装运行时复制核对；合成文件不是Windows运行时或最终安装资产。"""
from pathlib import Path
import json
import subprocess
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError
from ctflab_generation_store import digest
from ctflab_windows_recovery import record
from ctflab_runtime_inventory import inventory
import ctflab_desktop_package as package


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.source=Path(__file__).resolve().parents[2]
        self.python=self.root/'python';self.qemu=self.root/'qemu';self.python.mkdir();self.qemu.mkdir()
        (self.python/'python.exe').write_bytes(b'python-fixture')
        (self.python/'cryptography').mkdir();(self.python/'cryptography'/'fixture.py').write_text('# fixture')
        (self.python/'LICENSE.txt').write_text('fixture license')
        (self.qemu/'qemu-system-x86_64.exe').write_bytes(b'qemu-fixture')
        (self.qemu/'COPYING').write_text('fixture license')
        self.pyref=self.root/'python.json';self.qref=self.root/'qemu.json'
        record(self.pyref,package.component(self.python));record(self.qref,inventory(self.qemu))
        self.destination=self.root/'staged'

    def stage(self):
        with patch.object(package,'QEMU_SHA',digest(self.qemu/'qemu-system-x86_64.exe')):
            return package.stage(self.source,self.destination,self.python,self.pyref,self.qemu,self.qref)

    def test_whitelist_copy_and_manifest_no_vm_or_private_state(self):
        result=self.stage();self.assertFalse(result['installer_built'])
        self.assertFalse(result['signature_verified'])
        self.assertEqual((self.destination/'runtime/python/python.exe').read_bytes(),b'python-fixture')
        self.assertTrue((self.destination/'runtime/tools/ctflab_desktop_bridge.py').exists())
        self.assertFalse(list(self.destination.rglob('*.qcow2')))
        self.assertFalse(list(self.destination.rglob('*key.pem')))
        with self.assertRaises(ContractError):self.stage()

    def test_runtime_change_refused_before_creating_output(self):
        (self.qemu/'qemu-system-x86_64.exe').write_bytes(b'changed')
        with self.assertRaises(ContractError):self.stage()
        self.assertFalse(self.destination.exists())

    def test_missing_license_refuses_distribution_staging(self):
        (self.python/'LICENSE.txt').unlink();self.pyref.unlink();record(self.pyref,package.component(self.python))
        with self.assertRaises(ContractError):self.stage()
        self.assertFalse(self.destination.exists())

    def test_destination_within_input_refused(self):
        self.destination=self.python/'stage'
        with self.assertRaises(ContractError):self.stage()
        self.assertFalse(self.destination.exists())

    def test_non_windows_probe_refuses_execution(self):
        if sys.platform=='win32':self.skipTest('此边界只在非Windows执行')
        with self.assertRaises(ContractError):package.probe(self.destination)

    def test_explicit_static_check_refuses_invalid_native_files_before_output_creation(self):
        with patch.object(package,'QEMU_SHA',digest(self.qemu/'qemu-system-x86_64.exe')):
            with self.assertRaises(ContractError):package.stage(self.source,self.destination,self.python,self.pyref,self.qemu,self.qref,inspect_imports=True)
        self.assertFalse(self.destination.exists())

    def native_fixtures(self,missing=False):
        import test_ctflab_pe_dependencies as fixtures
        (self.python/'python.exe').write_bytes(fixtures.fixture(['kernel32.dll']))
        (self.qemu/'qemu-system-x86_64.exe').write_bytes(fixtures.fixture(delay=['missing.dll']) if missing else fixtures.fixture(['kernel32.dll']))
        self.pyref.unlink();self.qref.unlink();record(self.pyref,package.component(self.python));record(self.qref,inventory(self.qemu))

    def test_static_reports_bound_to_payload_but_not_native_loader_or_signature_proof(self):
        self.native_fixtures()
        with patch.object(package,'QEMU_SHA',digest(self.qemu/'qemu-system-x86_64.exe')),patch('subprocess.run',side_effect=AssertionError('不能执行PE')):
            result=package.stage(self.source,self.destination,self.python,self.pyref,self.qemu,self.qref,inspect_imports=True)
        self.assertTrue(result['static_imports_checked']);self.assertFalse(result['installer_built'])
        manifest=package.read_json(self.destination/'bundle-manifest.json',lambda _:None)
        self.assertEqual(manifest['static_import_report_sha256'],digest(self.destination/'runtime/static-imports.json'))
        self.assertFalse(manifest['dependency_closure_verified']);self.assertFalse(manifest['signature_verified'])

    def test_missing_delay_import_refuses_copy_without_creating_staging_directory(self):
        self.native_fixtures(missing=True)
        with patch.object(package,'QEMU_SHA',digest(self.qemu/'qemu-system-x86_64.exe')):
            with self.assertRaises(ContractError):package.stage(self.source,self.destination,self.python,self.pyref,self.qemu,self.qref,inspect_imports=True)
        self.assertFalse(self.destination.exists())

    def probe(self,manifest_sha256,runner):
        # 不更改全局os.name，避免把Mac上的Path意外变为WindowsPath。
        with patch.object(package,'os',SimpleNamespace(name='nt')),patch.object(package.subprocess,'run',runner):
            return package.probe(self.destination,manifest_sha256)

    def good_result(self):
        return SimpleNamespace(stdout=json.dumps({'imports_from_bundle':True,'python':'3.13.0','cryptography':'46.0.5'}).encode())

    def test_probe_checks_pinned_payload_before_and_after_without_claiming_signature(self):
        staged=self.stage();calls=[]
        def runner(argv,**kwargs):
            calls.append(argv);self.assertEqual(kwargs['stdin'],package.subprocess.DEVNULL)
            self.assertEqual(kwargs['cwd'],self.destination/'runtime/python')
            self.assertIn('-I',argv);return self.good_result()
        result=self.probe(staged['manifest_sha256'],runner)
        self.assertEqual(len(calls),1);self.assertFalse(result['signature_verified'])
        self.assertFalse(result['dependency_closure_verified'])
        self.assertEqual(result['manifest_sha256'],staged['manifest_sha256'])
        with self.assertRaises(ContractError):self.probe(staged['manifest_sha256'],lambda *a,**k:self.fail('不重复探测'))

    def test_probe_refuses_changed_python_before_execution(self):
        staged=self.stage();(self.destination/'runtime/python/python.exe').write_bytes(b'replaced')
        with self.assertRaises(ContractError):self.probe(staged['manifest_sha256'],lambda *a,**k:self.fail('不执行漂移文件'))

    def test_probe_refuses_extra_dll_before_execution(self):
        staged=self.stage();(self.destination/'runtime/python/extra.dll').write_bytes(b'extra')
        with self.assertRaises(ContractError):self.probe(staged['manifest_sha256'],lambda *a,**k:self.fail('不执行额外DLL'))

    def test_probe_refuses_missing_runtime_file(self):
        staged=self.stage();(self.destination/'runtime/python/LICENSE.txt').unlink()
        with self.assertRaises(ContractError):self.probe(staged['manifest_sha256'],lambda *a,**k:self.fail('不执行残缺载荷'))

    def test_probe_refuses_rewritten_manifest_even_if_payload_matches_it(self):
        staged=self.stage();manifest=self.destination/'bundle-manifest.json'
        value=json.loads(manifest.read_text());target=self.destination/'runtime/python/python.exe'
        target.write_bytes(b'replaced');value['files']['python/python.exe']=digest(target)
        manifest.write_text(json.dumps(value))
        with self.assertRaises(ContractError):self.probe(staged['manifest_sha256'],lambda *a,**k:self.fail('不能自行替换信任摘要'))

    def test_probe_refuses_missing_pin(self):
        self.stage()
        with self.assertRaises(ContractError):self.probe(None,lambda *a,**k:self.fail('必须有独立摘要'))

    def test_probe_preserves_drift_after_child_and_does_not_write_success_receipt(self):
        staged=self.stage();target=self.destination/'runtime/python/python.exe'
        def runner(*args,**kwargs):target.write_bytes(b'changed-by-fixture');return self.good_result()
        with self.assertRaises(ContractError):self.probe(staged['manifest_sha256'],runner)
        self.assertEqual(target.read_bytes(),b'changed-by-fixture')
        self.assertFalse((self.destination/'python-probe.json').exists())

    def test_probe_rejects_invalid_success_response(self):
        staged=self.stage()
        with self.assertRaises(ContractError):self.probe(staged['manifest_sha256'],lambda *a,**k:SimpleNamespace(stdout=b'{"imports_from_bundle":true}'))
        self.assertFalse((self.destination/'python-probe.json').exists())

    def test_probe_rejects_manifest_path_escape(self):
        self.stage();manifest=self.destination/'bundle-manifest.json';value=json.loads(manifest.read_text())
        value['files']['../outside.exe']='0'*64;manifest.write_text(json.dumps(value))
        with self.assertRaises(ValueError):self.probe(digest(manifest),lambda *a,**k:self.fail('路径越界不得执行'))

    def test_isolated_verify_cli_is_read_only_and_refuses_wrong_pin(self):
        staged=self.stage();before={str(p.relative_to(self.destination)):digest(p) for p in self.destination.rglob('*') if p.is_file()}
        command=[sys.executable,'-I','-B',str(self.source/'tools/ctflab_desktop_package.py'),
                 'verify','--destination',str(self.destination),'--manifest-sha256',staged['manifest_sha256']]
        result=subprocess.run(command,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr);value=json.loads(result.stdout)
        self.assertEqual(value['state'],'payload-matches');self.assertFalse(value['signature_verified'])
        bad=subprocess.run(command[:-1]+['0'*64],capture_output=True,timeout=30)
        self.assertEqual(bad.returncode,2);self.assertTrue(json.loads(bad.stdout)['preserved'])
        self.assertEqual(before,{str(p.relative_to(self.destination)):digest(p) for p in self.destination.rglob('*') if p.is_file()})

    @unittest.skipIf(sys.platform=='win32','Windows链接权限不在本机夹具范围')
    def test_probe_refuses_linked_payload_without_execution(self):
        staged=self.stage();target=self.destination/'runtime/python/python.exe';target.unlink()
        target.symlink_to(self.python/'python.exe')
        with self.assertRaises(ValueError):self.probe(staged['manifest_sha256'],lambda *a,**k:self.fail('不执行链接'))


if __name__=='__main__':unittest.main()
