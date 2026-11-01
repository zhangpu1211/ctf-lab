"""C05自制PCAP/FAT12的有界只读解析及实际标准库学生入口。"""
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab_evidence_course as course
import ctflab_evidence_samples as samples


class EvidenceSampleTests(unittest.TestCase):
    def test_pcap_six_records_cross_reference_requests_and_http_business_results(self):
        records = samples.read_pcap(samples.pcap_sample())
        self.assertEqual([r['request'] for r in records], ['r05','r05','r06','r06','r07','r07'])
        self.assertEqual(records[0]['body'], 'maintenance=true')
        self.assertEqual([r['http'] for r in records[1::2]],
                         ['HTTP/1.1 200 OK','HTTP/1.1 503 Service Unavailable','HTTP/1.1 200 OK'])
        self.assertEqual(records[0]['source'], '198.51.100.24')
        self.assertEqual(records[2]['timestamp_utc'], '2026-10-20T09:02:00+00:00')

    def test_fat12_actual_data_volume_contains_config_and_exact_log_copy(self):
        log = course.student_files()['evidence/web-access.log'].encode()
        raw = samples.fat_sample(log); volume = samples.read_fat(raw)
        self.assertEqual(len(raw), 368640)
        self.assertEqual(volume['CONFIG.TXT']['text'], 'maintenance=true\ncache_ttl=120\n')
        self.assertEqual(volume['ACCESS.LOG']['text'].encode(), log)
        self.assertEqual(volume['ACCESS.LOG']['sha256'], course.sha(log))
        self.assertEqual(volume['CONFIG.TXT']['timestamp_timezone'], 'unspecified-local')
        self.assertIn('09:04:00Z', volume['COLLECT.TXT']['text'])

    def test_deterministic_self_authored_bytes_no_runtime_dependencies(self):
        self.assertEqual(samples.pcap_sample(), samples.pcap_sample())
        self.assertEqual(samples.fat_sample(b'text'), samples.fat_sample(b'text'))

    def test_pcap_header_truncation_length_and_record_limit_refused(self):
        raw = samples.pcap_sample()
        malformed = [raw[:10], raw[:-1], b'x'+raw[1:], raw+b'x']
        broken = bytearray(raw); struct.pack_into('<I', broken, 24+8, 0xffffffff); malformed.append(bytes(broken))
        record = raw[24:24+16+struct.unpack_from('<I', raw, 32)[0]]
        malformed.append(raw[:24]+record*33)
        for item in malformed:
            with self.subTest(size=len(item)), self.assertRaises(ValueError):samples.read_pcap(item)

    def test_pcap_ip_and_tcp_checksums_or_microseconds_refused(self):
        raw = samples.pcap_sample()
        for index in (24+16+14+8, 24+16+14+20+16):
            broken = bytearray(raw); broken[index] ^= 1
            with self.assertRaises(ValueError):samples.read_pcap(bytes(broken))
        broken = bytearray(raw); struct.pack_into('<I', broken, 28, 1000000)
        with self.assertRaises(ValueError):samples.read_pcap(bytes(broken))

    def test_fat_geometry_length_or_second_table_change_refused(self):
        raw = samples.fat_sample(b'hello')
        for item in (raw[:-1], raw+b'x', raw[:11]+b'\0\0'+raw[13:]):
            with self.assertRaises(ValueError):samples.read_fat(item)
        broken = bytearray(raw); broken[4*512+3] ^= 1
        with self.assertRaises(ValueError):samples.read_fat(bytes(broken))

    def test_fat_cycle_and_cross_link_or_unfinished_chain_refused(self):
        raw = samples.fat_sample(b'A'*2048)
        for cluster, value in ((3,3), (3,0xfff), (2,4)):
            broken = bytearray(raw); table = bytearray(raw[512:4*512]); samples.fat_entry(table, cluster, value)
            broken[512:4*512] = table; broken[4*512:7*512] = table
            with self.subTest(value=value), self.assertRaises(ValueError):samples.read_fat(bytes(broken))
        broken = bytearray(raw); struct.pack_into('<H', broken, 7*512+32+26, 2)
        with self.assertRaises(ValueError):samples.read_fat(bytes(broken))

    def test_fat_directories_and_unbounded_file_sizes_refused(self):
        raw = samples.fat_sample(b'hello')
        broken = bytearray(raw); broken[7*512+11] = 0x10
        with self.assertRaises(ValueError):samples.read_fat(bytes(broken))
        broken = bytearray(raw); struct.pack_into('<I', broken, 7*512+28, 65537)
        with self.assertRaises(ValueError):samples.read_fat(bytes(broken))

    def test_actual_student_inspector_isolated_has_no_teacher_or_project_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); course.build(root/'pack'); student = root/'student'
            with zipfile.ZipFile(root/'pack/C05-student.zip') as archive:archive.extractall(student)
            pin = course.sha((student/'MANIFEST.json').read_bytes()); script = student/'inspect_samples.py'
            self.assertNotIn('import ctflab', script.read_text()); self.assertNotIn('C05逐条证据复盘示例', script.read_text())
            result = subprocess.run([sys.executable,'-I','-B',str(script),'--manifest-sha256',pin],
                                    cwd=root,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            view = json.loads(result.stdout); self.assertEqual(len(view['pcap']),6); self.assertEqual(len(view['fat12_files']),3)
            self.assertFalse(view['capture_executed']); self.assertFalse(view['volume_mounted']); self.assertFalse(view['sample_executed'])
            self.assertFalse(view['classroom_verified'])
            result = subprocess.run([sys.executable,'-I','-B',str(script),'--manifest-sha256','0'*64],
                                    cwd=root,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,2)

    def test_legacy_text_manifest_still_verifies_without_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); raw = b'legacy text only'
            (root/'log.txt').write_bytes(raw)
            manifest = {'schema':1,'course':'c05-synthetic-web-01','kind':'synthetic-text-only','classroom_verified':False,
                        'files':{'log.txt':{'sha256':course.sha(raw),'bytes':len(raw)}}}
            (root/'MANIFEST.json').write_text(json.dumps(manifest))
            self.assertTrue(course.verify(root)['integrity_verified'])


if __name__ == '__main__':unittest.main()
