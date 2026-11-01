"""独立管理CLI绑定已读版本库目标，拒绝旧目标和版本树内调用。"""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ctflab_manage as manager


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.bridge=Mock();self.bridge.target='a'*64;self.bridge.store.root=Path('/private/ctflab-library')
        self.bridge.handle.return_value={'state':'fixture-only','automatic_stop':False}
    def run_command(self,*args):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):
            code=manager.main(['--config','/private/config',*args],factory=lambda _:self.bridge)
        return code,json.loads(stream.getvalue())
    def test_status_is_readonly_and_does_not_require_an_old_target(self):
        code,_=self.run_command('status');self.assertEqual(code,0)
        self.bridge.handle.assert_called_once_with({'action':'status'})
    def test_mutation_requires_exact_target_and_fixed_payload(self):
        code,_=self.run_command('--expected-target','b'*64,'initialize');self.assertEqual(code,2)
        self.bridge.handle.assert_not_called()
        code,_=self.run_command('--expected-target','a'*64,'online-download','--source','https://example.invalid/',
            '--maximum','1048576','--operation-id','original','--plan-sha256','c'*64)
        self.assertEqual(code,0);self.assertEqual(self.bridge.handle.call_args.args[0],{
            'action':'online-download','target':'a'*64,'source':'https://example.invalid/','maximum':1048576,
            'operation_id':'original','plan_sha256':'c'*64})
    def test_manager_inside_version_tree_cannot_mutate(self):
        with patch.object(manager,'__file__',str(self.bridge.store.root/'versions/0.1.0/tools/ctflab_manage.py')):
            code,_=self.run_command('--expected-target','a'*64,'initialize')
        self.assertEqual(code,2);self.bridge.handle.assert_not_called()


if __name__=='__main__':unittest.main()
