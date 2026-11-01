"""W05离线就绪核对：安装配置门、PE证书表、载荷清单与卸载保留证据。

只用本地静态材料与合成PE；不制作安装包、不签名、不连接实机。
真实候选/实机记录在位时一并核对；不在位时明确跳过，不把跳过当通过。
"""
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab_w05_readiness as readiness

REPO = Path(__file__).resolve().parents[2]
RUN10 = REPO / 'output/windows-native-20261030'
CANDIDATE = Path('/Users/pufei/Downloads/CTFLab-Library/03-软件/'
                 'CTFLab-0.1.4-Windows-native-candidate-20261030/CTFLab_0.1.4_x64-setup.exe')


def pe_bytes(cert_rva=0, cert_size=0):
    dos = b'MZ' + b'\0' * 0x3A + (0x40).to_bytes(4, 'little')
    pe = b'PE\0\0' + b'\0' * 20                       # COFF头占位
    optional = struct.pack('<H', 0x20B) + b'\0' * 110  # PE32+，数据目录前占位
    directories = [b'\0' * 8] * 16
    directories[4] = cert_rva.to_bytes(4, 'little') + cert_size.to_bytes(4, 'little')
    return dos + pe + optional + b''.join(directories)


class W05ReadinessTests(unittest.TestCase):
    def test_bundle_config_gate_requires_overlay_and_declares_offline_webview(self):
        conf = readiness.read_json(REPO / 'desktop/src-tauri/tauri.conf.json')
        base = readiness.check_bundle_config(conf)
        self.assertFalse(base['ok'])
        self.assertFalse(base['checks']['bundle_active_for_installer'])
        self.assertTrue(base['checks']['nsis_current_user_scope'])
        self.assertTrue(base['checks']['webview2_offline_installer_mode'])
        overlay = readiness.check_bundle_config(conf, {'bundle': {'active': True}})
        self.assertTrue(overlay['ok'])

    def test_pe_certificate_directory_and_signature_status(self):
        self.assertEqual(readiness.pe_certificate_directory(pe_bytes()), (0, 0))
        self.assertEqual(readiness.pe_certificate_directory(pe_bytes(0x2A000, 0x1234)), (0x2A000, 0x1234))
        for bad in (b'MZ\0\0', pe_bytes()[:100], pe_bytes()[:0x40 + 4] + b'NOPE'):
            with self.assertRaises(ValueError):
                readiness.pe_certificate_directory(bad)
        with tempfile.TemporaryDirectory() as temp:
            unsigned = Path(temp) / 'setup.exe'; unsigned.write_bytes(pe_bytes())
            status = readiness.signature_status(unsigned)
            self.assertFalse(status['signed'])
            self.assertTrue(status['release_signing_required_for_public_g1'])

    def test_payload_report_matches_manifest_and_detects_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'staging'; runtime = root / 'runtime'
            (runtime / 'python').mkdir(parents=True); (runtime / 'qemu').mkdir()
            files = {'python/python.exe': b'py-fixture', 'qemu/qemu-system-x86_64.exe': b'qemu-fixture',
                     'static-imports.json': b'{"schema":1}'}
            for name, blob in files.items():
                (runtime / name).write_bytes(blob)
            manifest = {'schema': 1, 'kind': 'windows-desktop-staging',
                        'files': {name: __import__('hashlib').sha256(blob).hexdigest() for name, blob in files.items()},
                        'static_imports_checked': True, 'dependency_closure_verified': False,
                        'signature_verified': False, 'g0_passed': False, 'g1_passed': False}
            (root / 'bundle-manifest.json').write_text(json.dumps(manifest))
            report = readiness.payload_report(root)
            self.assertTrue(report['ok'])
            self.assertEqual(report['files'], 3)
            (runtime / 'python/python.exe').write_bytes(b'tampered')
            drifted = readiness.payload_report(root)
            self.assertFalse(drifted['checks']['payload_files_match_manifest'])
            self.assertFalse(drifted['ok'])

    @unittest.skipUnless(RUN10.joinpath('run-10-artifacts.zip').exists(), '缺少run-10实机记录')
    def test_platform_evidence_from_run10_and_readiness_report_statuses(self):
        with zipfile.ZipFile(RUN10 / 'run-10-artifacts.zip') as archive:
            results = json.loads(archive.read('installation-results.json'))
        evidence = readiness.uninstall_evidence(results)
        self.assertTrue(evidence['ok'])
        self.assertTrue(evidence['checks']['uninstall_program_removed'])
        self.assertTrue(evidence['checks']['application_data_preserved'])
        self.assertFalse(evidence['checks']['windows_11_verified'])
        self.assertFalse(evidence['checks']['authenticode_signed'])
        report = readiness.readiness_report(
            config=readiness.check_bundle_config(readiness.read_json(REPO / 'desktop/src-tauri/tauri.conf.json'),
                                                 {'bundle': {'active': True}}),
            signature={'signed': False, 'sha256': '0' * 64},
            payload={'ok': True}, platform=evidence)
        statuses = {item['item']: item['status'] for item in report['items']}
        self.assertEqual(statuses['安装布局配置（NSIS/currentUser/CSP）'], 'verified')
        self.assertEqual(statuses['WebView2离线供应'], 'missing-evidence')
        self.assertEqual(statuses['干净Windows11人工/桌面验收'], 'open')
        self.assertEqual(statuses['升级/迁移失败回退'], 'open')
        self.assertFalse(report['offline_all_verified'])

    @unittest.skipUnless(CANDIDATE.exists(), '缺少Windows候选安装器')
    def test_real_candidate_is_unsigned_nsis_and_matches_recorded_digest(self):
        status = readiness.signature_status(CANDIDATE)
        self.assertFalse(status['signed'])
        self.assertEqual(status['sha256'],
                         '8583d7796dcd231aeec9ca334f18978547af92d810a062f80e4f93ece46b13a2')
        with CANDIDATE.open('rb') as stream:
            head = stream.read(1 << 20)
        self.assertIn(b'Nullsoft', head)

    def test_cli_end_to_end_writes_report_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'staging'; runtime = root / 'runtime'
            (runtime / 'python').mkdir(parents=True)
            files = {'python/python.exe': b'py-fixture', 'static-imports.json': b'{}'}
            for name, blob in files.items():
                (runtime / name).write_bytes(blob)
            manifest = {'schema': 1, 'kind': 'windows-desktop-staging',
                        'files': {name: __import__('hashlib').sha256(blob).hexdigest() for name, blob in files.items()},
                        'static_imports_checked': True, 'dependency_closure_verified': False,
                        'signature_verified': False, 'g0_passed': False, 'g1_passed': False}
            (root / 'bundle-manifest.json').write_text(json.dumps(manifest))
            installer = Path(temp) / 'setup.exe'; installer.write_bytes(pe_bytes())
            platform_results = Path(temp) / 'results.json'
            platform_results.write_text(json.dumps({'os': 'Windows-2025Server', 'uninstall_program_removed': True,
                'application_data_sentinels_preserved': True, 'visible_native_window_observed': True,
                'manual_ui_verified': False, 'windows_11_verified': False, 'authenticode_release_signed': False}))
            output = Path(temp) / 'w05.json'
            command = [sys.executable, '-I', '-B', str(Path(readiness.__file__)),
                       '--tauri-config', str(REPO / 'desktop/src-tauri/tauri.conf.json'),
                       '--installer', str(installer), '--payload', str(root),
                       '--platform-results', str(platform_results), '--output', str(output)]
            result = subprocess.run(command, capture_output=True, text=True, cwd=temp, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(output.read_text())
            self.assertEqual({i['status'] for i in report['items']} >= {'verified'}, True)
            self.assertEqual(len(report['items']), 8)
            self.assertEqual(result.returncode, 0)
            # 已有报告不覆盖。
            self.assertEqual(subprocess.run(command, capture_output=True, text=True, cwd=temp).returncode, 2)
            self.assertEqual(output.read_text(), report and output.read_text())


if __name__ == '__main__':
    unittest.main()
