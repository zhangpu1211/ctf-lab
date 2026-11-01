"""W01 驱动负测：使用锁定的合成文件与替身，不执行真实 QEMU。"""
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ctflab_windows_probe as probe
from ctflab_contract import ContractError


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        binary=self.root/'qemu-system-x86_64.exe';binary.write_bytes(b'fixture-not-executable')
        self.manifest={'schema':1,'build_id':'fixture-build','target':'windows-x86_64','components':{
            'qemu':{'path':str(binary),'sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
                    'version':'1.2.3','source_id':'test-fixture'}}}

    def tearDown(self):self.temp.cleanup()

    def inspect(self,manifest=None,run=None):
        return probe.inspect_runtime(manifest or self.manifest,host_system='Windows',host_machine='AMD64',run=run or self.fake)

    def fake(self,args,**kwargs):
        self.assertFalse(kwargs['shell']);self.assertEqual(kwargs['timeout'],10)
        self.assertEqual(kwargs['stdin'],subprocess.DEVNULL)
        output=b'QEMU emulator version 1.2.3\n' if args[-1]=='--version' else b'whpx tcg sdl virtio-gpu-pci'
        return subprocess.CompletedProcess(args,0,stdout=output,stderr=b'/Users/private token=secret')

    def test_default_plan_never_executes_or_claims_windows_support(self):
        with mock.patch('subprocess.run',side_effect=AssertionError('执行进程')),redirect_stdout(io.StringIO()) as out:
            self.assertEqual(probe.main([]),0)
        report=json.loads(out.getvalue());self.assertFalse(report['g0_passed']);self.assertFalse(report['vm_started'])
        self.assertTrue(all(item['status']=='not-tested' for item in report['probes']))

    def test_fixed_queries_and_no_raw_output_or_paths(self):
        calls=[]
        def run(args,**kwargs):calls.append(args);return self.fake(args,**kwargs)
        report=self.inspect(run=run)
        self.assertEqual([args[1:] for args in calls],[list(args) for args in probe.QUERY_ARGS.values()])
        self.assertTrue(report['build_inspection_passed']);self.assertFalse(report['components_complete'])
        self.assertFalse(report['native_windows_verified']);self.assertFalse(report['g0_passed'])
        text=json.dumps(report);self.assertNotIn(str(self.root),text);self.assertNotIn('secret',text)
        self.assertIn('whpx',text);self.assertTrue(all(p['status']=='not-tested' for p in report['probes']))

    def test_manifest_cannot_add_arguments_or_change_target(self):
        mutations=[lambda d:d.update(arguments=['-drive','file=user.qcow2']),
                   lambda d:d.update(target='macos-arm64'),lambda d:d.update(schema=True),
                   lambda d:d['components']['qemu'].update(arguments=['-qmp','tcp:0.0.0.0:1']),
                   lambda d:d['components']['qemu'].update(path='/bin/sh'),
                   lambda d:d['components']['qemu'].update(source_id='../secret'),
                   lambda d:d['components']['qemu'].update(sha256='0'*63)]
        for mutate in mutations:
            value=copy.deepcopy(self.manifest);mutate(value)
            with self.assertRaises(ContractError),mock.patch('subprocess.run',side_effect=AssertionError('执行')):
                probe.validate_manifest(value)

    def test_wrong_platform_refuses_before_probe(self):
        run=mock.Mock(side_effect=AssertionError('执行'))
        with self.assertRaises(ContractError):probe.inspect_runtime(self.manifest,host_system='Darwin',host_machine='arm64',run=run)
        run.assert_not_called()

    def test_all_component_hashes_checked_before_any_query(self):
        extra=self.root/'firmware.fd';extra.write_bytes(b'changed')
        self.manifest['components']['firmware']={'path':str(extra),'sha256':'0'*64,'version':'v1','source_id':'fixture'}
        run=mock.Mock(side_effect=AssertionError('执行'))
        with self.assertRaises(ContractError):self.inspect(run=run)
        run.assert_not_called()

    def test_symlink_component_is_rejected(self):
        other=self.root/'actual';other.write_bytes(b'fixture-not-executable')
        binary=Path(self.manifest['components']['qemu']['path']);binary.unlink()
        try:
            binary.symlink_to(other)
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 1314:
                self.skipTest('Windows 当前用户无创建符号链接权限；该负测未验证')
            raise
        with self.assertRaises(ContractError):self.inspect()

    def test_replaced_binary_between_queries_is_rejected(self):
        calls=[]
        def run(args,**kwargs):
            calls.append(args);result=self.fake(args,**kwargs)
            Path(args[0]).write_bytes(b'replaced');return result
        with self.assertRaises(ContractError):self.inspect(run=run)
        self.assertEqual(len(calls),1)

    def test_timeout_and_failure_preserve_not_tested_native_status(self):
        run=mock.Mock(side_effect=subprocess.TimeoutExpired('fixture',10))
        report=self.inspect(run=run)
        self.assertFalse(report['build_inspection_passed']);self.assertEqual(len(report['queries']),4)
        self.assertTrue(all(item['status']=='failed' for item in report['queries']))
        self.assertFalse(report['g0_passed'])

    def test_mismatched_version_is_not_inspected_successfully(self):
        def run(args,**kwargs):return subprocess.CompletedProcess(args,0,stdout=b'QEMU emulator version 9.9.9',stderr=b'')
        report=self.inspect(run=run)
        self.assertFalse(report['build_inspection_passed']);self.assertEqual(report['queries'][0]['status'],'failed')

    def test_selftest_uses_only_python_child_and_temporary_store(self):
        real=probe.subprocess.run;calls=[]
        def run(args,**kwargs):
            self.assertEqual(args[0],sys.executable);self.assertIn('--fixture-child',args)
            calls.append(args);return real(args,**kwargs)
        with mock.patch.object(probe.subprocess,'run',side_effect=run),mock.patch('socket.socket',side_effect=AssertionError('网络')):
            report=probe.self_test()
        self.assertEqual(len(calls),1);self.assertEqual(report['scope'],'synthetic-only')
        self.assertEqual(len(report['checks']),5);self.assertFalse(report['vm_started'])
        self.assertFalse(report['g0_passed'])

    def test_independent_driver_imports_without_posix_runner(self):
        code="import sys;sys.path.insert(0,sys.argv[1]);sys.modules['fcntl']=None;import ctflab_windows_probe as p;assert 'ctflab' not in sys.modules;assert not p.new_report()['g0_passed']"
        result=subprocess.run([sys.executable,'-I','-c',code,str(Path(probe.__file__).parent)],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_cli_rejects_duplicate_manifest_fields(self):
        path=self.root/'manifest.json';path.write_text('{"schema":1,"schema":1}')
        with redirect_stdout(io.StringIO()) as out:self.assertEqual(probe.main(['--inspect-runtime',str(path)]),1)
        self.assertEqual(json.loads(out.getvalue())['scope'],'driver-error')


class NativePreflightTests(unittest.TestCase):
    def test_native_success_never_promotes_g0(self):
        with mock.patch.object(probe.platform,'system',return_value='Windows'), \
             mock.patch.object(probe.platform,'machine',return_value='AMD64'), \
             mock.patch('ctflab_windows_native.hypervisor_capability',return_value={'status':'available','hypervisor_present':True}):
            result=probe.native_preflight()
        self.assertTrue(result['host_preflight_passed'])
        self.assertFalse(result['g0_passed'])
        self.assertFalse(result['qemu_execution_verified'])
        self.assertTrue(all(p['status']=='not-tested' for p in result['probes']))

    def test_wrong_host_never_loads_native_api(self):
        with mock.patch.object(probe.platform,'system',return_value='Darwin'), \
             mock.patch('ctflab_windows_native.hypervisor_capability',side_effect=AssertionError('不能调用')):
            result=probe.native_preflight()
        self.assertFalse(result['host_preflight_passed'])
        self.assertIsNone(result['hypervisor']['hypervisor_present'])

    def test_absent_capability_is_failed_cli_preflight(self):
        with mock.patch.object(probe.platform,'system',return_value='Windows'), \
             mock.patch.object(probe.platform,'machine',return_value='AMD64'), \
             mock.patch('ctflab_windows_native.hypervisor_capability',return_value={'status':'not-present','hypervisor_present':False}), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(probe.main(['--native-preflight']),1)
        self.assertFalse(json.loads(output.getvalue())['g0_passed'])


if __name__=='__main__':unittest.main()
