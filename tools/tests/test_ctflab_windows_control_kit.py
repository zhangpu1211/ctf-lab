import hashlib,json
from pathlib import Path
import subprocess,sys,tempfile,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ctflab_windows_control_kit as kit

class ControlKitTests(unittest.TestCase):
    def test_reproducible_closed_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=Path(kit.__file__).resolve().parents[1]
            a=root/'a.zip';b=root/'b.zip'
            self.assertEqual(kit.build(source,a),kit.build(source,b))
            with self.assertRaises(FileExistsError):kit.build(source,a)
            with zipfile.ZipFile(a) as archive:
                manifest=json.loads(archive.read('MANIFEST.json'))
                for name,digest in manifest['files'].items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(),digest)
                archive.extractall(root/'isolated')
            result=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tools/tests','-v'],
                                  cwd=root/'isolated',capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stderr)
