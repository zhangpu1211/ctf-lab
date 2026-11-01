"""验证包闭包与可复现性；隔离解压后仅运行所附基础测试。"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ctflab_windows_kit as kit


class KitTests(unittest.TestCase):
    def test_reproducible_and_isolated_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=Path(kit.__file__).resolve().parents[1]
            a=root/'a.zip';b=root/'b.zip'
            self.assertEqual(kit.build(source,a),kit.build(source,b))
            with self.assertRaises(FileExistsError):kit.build(source,a)
            with zipfile.ZipFile(a) as archive:
                manifest=json.loads(archive.read('MANIFEST.json'))
                self.assertFalse(manifest['g0_passed'])
                for name,digest in manifest['files'].items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(),digest)
                extracted=root/'isolated';archive.extractall(extracted)
            result=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tools/tests'],
                                  cwd=extracted,capture_output=True,text=True,timeout=45)
            self.assertEqual(result.returncode,0,result.stderr)
            probe=subprocess.run([sys.executable,'-I','tools/ctflab_windows_probe.py','--self-test'],
                                 cwd=extracted,capture_output=True,text=True,timeout=15)
            self.assertEqual(probe.returncode,0,probe.stderr)
            self.assertFalse(json.loads(probe.stdout)['g0_passed'])
