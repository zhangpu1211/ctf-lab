"""分享摘要不复制原始私密字段；预览与导出精确一致。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ctflab_diagnostics_public as diagnostics


class PublicDiagnosticsTests(unittest.TestCase):
    def report(self):
        return {'schema':1,'ctflab_version':'0.1.2-preview.20261015',
                'host':{'system':'Darwin 25.0 private-user','machine':'arm64','python':'private'},
                'profiles':[{'id':'private-user','state':'running','boot':{'phase':'network','detail':'secret'},
                             'log_tail':['password=secret','C:\\Users\\private-user','10.1.1.1'],
                             'pid':12345,'path':'/Users/private-user'}]}

    def test_sensitive_fields_omitted(self):
        data,digest=diagnostics.encoded_preview(self.report())
        for value in (b'private-user',b'secret',b'12345',b'10.1.1.1',b'C:\\'):
            self.assertNotIn(value,data)
        result=json.loads(data)
        self.assertEqual(result['profiles'][0]['boot_phase'],'network')
        self.assertEqual(len(digest),64)

    def test_untrusted_free_text_not_echoed(self):
        report=self.report();report['ctflab_version']='password=hello';report['profiles'][0]['state']='private-state'
        text=diagnostics.encoded_preview(report)[0]
        self.assertNotIn(b'password',text);self.assertNotIn(b'private-state',text)

    def test_export_matches_preview_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'public.json';data,digest=diagnostics.encoded_preview(self.report())
            diagnostics.export(self.report(),path,digest);self.assertEqual(path.read_bytes(),data)
            with self.assertRaises(FileExistsError):diagnostics.export(self.report(),path,digest)

    def test_changed_preview_and_unapproved_export_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'public.json'
            for digest in (None,'bad'):
                with self.assertRaises(diagnostics.DiagnosticsError):diagnostics.export(self.report(),path,digest)
            self.assertFalse(path.exists())

    def test_malformed_report_rejected(self):
        for report in ({'schema':True},{'schema':1,'profiles':'secret'},{'schema':1,'host':[]}):
            with self.assertRaises(diagnostics.DiagnosticsError):diagnostics.preview(report)
