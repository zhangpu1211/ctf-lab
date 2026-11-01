"""来宾安装材料的完整性与非Linux拒绝；不安装到本机。"""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_guest_kit import build,MODULES


class GuestKitTests(unittest.TestCase):
    def test_copied_analysis_metadata_reader_and_compare_have_complete_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()/'kit';build(Path(__file__).resolve().parents[2],root)
            script='''import sys,json,uuid,hashlib
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from ctflab_guest_analysis import pinned_result,compare_results,WRAPPER_SHA256
value={'state':'analysis-completed','returncode':0,'instance_uuid':str(uuid.uuid4()),'generation':1,
 'policy_sha256':'1'*64,'input_sha256':'2'*64,'config_sha256':None,'tool':'zeek','tool_version':'1.2.3',
 'image':'example/analyzer@sha256:'+'3'*64,'wrapper_sha256':WRAPPER_SHA256,'operation_id':str(uuid.uuid4()),
 'tool_version_observed':'1.2.3','version_report_sha256':'4'*64,'output_content':{'sha256':'5'*64,'files':2,'bytes':10}}
path=Path('result.json');path.write_text(json.dumps(value));sha=hashlib.sha256(path.read_bytes()).hexdigest()
left=pinned_result(path,sha);right=dict(left,operation_id=str(uuid.uuid4()))
assert compare_results(left,right)['same_output_content'] is True
'''
            result=subprocess.run([sys.executable,'-I','-B','-c',script,str(root/'usr/local/lib/ctflab')],
                                  cwd=tmp,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_source_bundle_hashes_and_fixed_systemd_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()/'kit'
            result=build(Path(__file__).resolve().parents[2],root)
            self.assertFalse(result['guest_validated'])
            for name,sha in result['files'].items():
                self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),sha)
                if name.endswith('.py'):ast.parse((root/name).read_bytes())
            check=subprocess.run([sys.executable,'-I','-B','-c',
                'import sys;sys.path.insert(0,sys.argv[1]);import ctflab_guest_agent,ctflab_guest_routed,ctflab_guest_routes,ctflab_linux_native,ctflab_guest_analysis',
                str(root/'usr/local/lib/ctflab')],cwd=tmp,capture_output=True,text=True,timeout=5)
            self.assertEqual(check.returncode,0,check.stderr)
            # 实际执行延迟导入的副本准备；仅import无法发现来宾材料缺运行时依赖。
            script='''import sys,hashlib,uuid
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
from ctflab_guest_analysis import OfflineAnalysis
root=Path(sys.argv[2]);root.mkdir(mode=0o700)
source=root/'original';source.write_bytes(b'opaque-input');source.chmod(0o600)
sha=hashlib.sha256(source.read_bytes()).hexdigest()
obj=OfflineAnalysis.__new__(OfflineAnalysis)
obj.agent=SimpleNamespace(root=root,effect=lambda operation,step,fn:fn())
obj.spec={'input_sha256':sha,'config_sha256':None};obj.evidence=lambda value:source
operation=str(uuid.uuid4());obj.prepare_inputs(operation)
assert obj.input_copy(sha,operation).read_bytes()==source.read_bytes()
assert source.stat().st_mode&0o777==0o600
'''
            copied=subprocess.run([sys.executable,'-I','-B','-c',script,str(root/'usr/local/lib/ctflab'),str(Path(tmp).resolve()/'job')],
                cwd=tmp,capture_output=True,text=True,timeout=5)
            self.assertEqual(copied.returncode,0,copied.stderr)
            self.assertIn('org.ctflab.agent.0',(root/'etc/systemd/system/ctflab-agent.service').read_text())
            self.assertFalse(list(root.rglob('*.qcow2')));self.assertFalse(list(root.rglob('*.pem')))
            with self.assertRaises(FileExistsError):build(Path(__file__).resolve().parents[2],root)
    def test_installer_refuses_test_host_without_touching_system(self):
        if sys.platform=='linux' and os.geteuid()==0:self.skipTest('不在root Linux测试宿主执行初始化器')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()/'kit';build(Path(__file__).resolve().parents[2],root)
            result=subprocess.run([sys.executable,'-I','-B',str(root/'install.py'),'--expected-vm','00000000-0000-4000-8000-000000000001'],
                                  capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,2);self.assertEqual(json.loads(result.stdout)['state'],'refused-or-partial')


if __name__=='__main__':unittest.main()
