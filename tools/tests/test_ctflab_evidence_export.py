"""封口PCAP、绑定、畸形记录与生命周期字段白名单。"""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError
from ctflab_evidence_export import read_capture, export, lifecycle
from ctflab_generation_store import digest, private_directory
from ctflab_network import PcapWriter
from ctflab_windows_recovery import record


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.identity = str(uuid.uuid4())
        self.binding = {'instance_uuid':self.identity,'generation':1,'network_id':'outer'}
        self.path = self.root/'capture.pcap'

    def capture(self, *, close=True):
        writer = PcapWriter(self.path, max_bytes=80, **self.binding)
        writer.write(b'a'*20, timestamp=100.25); writer.write(b'b'*20, timestamp=101.5)
        if close: writer.close()
        else: self.addCleanup(writer.close)
        return writer

    def test_export_keeps_original_digest_quota_loss_and_explicit_limits(self):
        self.capture(); before = digest(self.path)
        result = export(self.root/'export', instance_uuid=self.identity, generation=1, network_id='outer', captures=[self.path])
        self.assertEqual(digest(self.path), before)
        self.assertEqual(digest(self.root/'export'/'capture-001.pcap'), before)
        manifest = json.loads((self.root/'export'/'MANIFEST.json').read_text())
        self.assertEqual(manifest['captures'][0]['capture']['frames_dropped_quota'], 1)
        self.assertEqual(manifest['captures'][0]['packet_time_range_us'], [100250000,100250000])
        self.assertFalse(result['complete_capture_verified']); self.assertFalse(result['uploaded'])
        with self.assertRaises(FileExistsError):
            export(self.root/'export', instance_uuid=self.identity, generation=1, network_id='outer', captures=[self.path])

    def test_live_capture_without_final_metadata_is_refused(self):
        self.capture(close=False)
        with self.assertRaises(OSError): read_capture(self.path, self.binding)

    def test_wrong_instance_and_truncated_pcap_are_refused(self):
        self.capture()
        with self.assertRaises(ContractError): read_capture(self.path, dict(self.binding,generation=2))
        raw = self.path.read_bytes(); self.path.write_bytes(raw[:-1])
        with self.assertRaises(ContractError): read_capture(self.path, self.binding)

    def test_malformed_record_length_is_not_allocated_or_exported(self):
        self.capture()
        raw = bytearray(self.path.read_bytes()); raw[32:36] = struct.pack('<I',0xffffffff)
        self.path.write_bytes(raw)
        with self.assertRaises(ContractError): read_capture(self.path, self.binding)

    def test_event_export_filters_paths_keys_and_reports_mtime_basis(self):
        attempt = self.root/'attempt'; private_directory(attempt)
        plan_sha = 'a'*64
        record(attempt/'launch.json',{'name':f'ctflab-{self.identity}-g1-server','plan_sha256':plan_sha,'node':'server',
                                     'argv':['secret-path'], 'disk':'private-disk-path'})
        identity = {'pid':123,'created':1}
        record(attempt/'binding.json',{'launch_sha256':digest(attempt/'launch.json'),'identity':identity})
        record(attempt/'exit.json',{'identity':identity,'state':'exited','returncode':0,
                                   'secret':'credential-not-exported','graceful_stop_verified':False})
        events = lifecycle(attempt,{'node':'server','plan_sha256':plan_sha})
        text = json.dumps(events)
        self.assertNotIn('secret',text); self.assertNotIn('private-disk-path',text); self.assertNotIn('pid',text)
        self.assertEqual(events[0]['time_basis'],'filesystem-mtime-not-verified-event-time')
        self.capture()
        export(self.root/'events', instance_uuid=self.identity, generation=1, network_id='outer', captures=[self.path],
               attempts=[(attempt,'server',plan_sha)])
        self.assertFalse((self.root/'events'/'launch.json').exists())


if __name__ == '__main__': unittest.main()
