"""原A02的28组完整Mac参数回归；预期来自固定Git旧实现，绝不启动VM。"""
import contextlib
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab
import ctflab_scenario as scenario

REFERENCE = Path(__file__).parent/'fixtures/mac-argv-0994f62.json'


def build(case, reference):
    """外部运行时/固件/端点为固定绑定；不调用有副作用的资源准备入口。"""
    manager = object.__new__(ctflab.LabManager)
    with contextlib.ExitStack() as stack:
        for name, result in (
            ('ensure_uefi_vars', (Path('/fixture/code.fd'), Path('/fixture/vars.fd'))),
            ('_qmp_socket', Path('/fixture/qmp.sock')), ('_spice_socket', Path('/fixture/spice.sock')),
            ('_spice_ticket', Path('/fixture/ticket')), ('probe_spice', {'supported': True}),
        ):stack.enter_context(patch.object(manager, name, return_value=result))
        stack.enter_context(patch.object(ctflab, 'which_any', return_value='/fixture/qemu'))
        stack.enter_context(patch.object(ctflab, 'find_firmware', return_value=Path('/fixture/code.fd')))
        stack.enter_context(patch.object(Path, 'exists', return_value=False))
        for name in ('mkdir', 'unlink', 'write_text', 'write_bytes'):
            stack.enter_context(patch.object(Path, name, side_effect=AssertionError('参数核验不得写入')))
        stack.enter_context(patch('builtins.open', side_effect=AssertionError('参数核验不得读写文件')))
        stack.enter_context(patch.object(Path, 'open', side_effect=AssertionError('参数核验不得读写文件')))
        stack.enter_context(patch('subprocess.Popen', side_effect=AssertionError('参数核验不得启动进程')))
        stack.enter_context(patch('socket.socket', side_effect=AssertionError('参数核验不得建立网络')))
        if case['builder'] == 'single':
            return manager.qemu_command(case['profile'], reference['profiles'][case['profile']],
                                        Path('/fixture/overlay.qcow2'), 23400, **case['options'])
        if case['builder'] == 'installer':
            return manager.installer_command(case['profile'], reference['profiles'][case['profile']],
                                             Path('/fixture/install.iso'), Path('/fixture/target.qcow2'),
                                             Path('/fixture/vars.fd'), Path('/fixture/qmp.sock'),
                                             kernel_path=Path('/fixture/kernel'), initrd_path=Path('/fixture/initrd'),
                                             **case['options'])
        if case['builder'] != 'scenario':raise AssertionError('未知对照类别')
        return scenario.qemu_command(reference['scenario_manifest'], reference['instance_uuid'], case['node'],
                                     generation=1, state_root='/state', socket_root='/s',
                                     network_ports={'outer': 12001, 'inner': 12002}, qemu_binary='/fixture/qemu',
                                     firmware_code='/fixture/code.fd' if case['node'] == 'kali' else None,
                                     available_capabilities=scenario.REQUIRED_CAPABILITIES,
                                     include_spice=case['include_spice'])


class MacArgvEquivalenceTests(unittest.TestCase):
    def test_reference_is_fixed_and_current_builtin_profiles_match_approved_sources(self):
        self.assertEqual(hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),
                         '3ee65591a407486ec418783900601283b7c2d90c9e8522fee03b250c2ac3cd0e')
        reference = json.loads(REFERENCE.read_text())
        self.assertEqual(reference['reference_commit'], '0994f620516c49d84badc3a606c1cd5ae4b483d0')
        self.assertFalse(reference['vm_started'])
        root = Path(__file__).resolve().parents[2]
        for name, expected in reference['reference_sha256'].items():
            if name.endswith('.yaml'):
                with self.subTest(profile=name):
                    self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(), expected)
        cases = reference['cases']
        self.assertEqual(len(cases), 28); self.assertEqual(len({c['id'] for c in cases}), 28)
        self.assertEqual([sum(c['builder'] == name for c in cases) for name in ('single', 'installer', 'scenario')], [18, 4, 6])

    def test_all_28_complete_argv_and_port_maps_match_pre_policy_implementation(self):
        reference = json.loads(REFERENCE.read_text())
        for case in reference['cases']:
            with self.subTest(case=case['id']):
                actual = build(case, reference)
                expected = (case['argv'], case['ports']) if case['builder'] == 'single' else case['argv']
                self.assertEqual(actual, expected)


if __name__ == '__main__':unittest.main()
