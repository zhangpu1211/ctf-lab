"""后台控制完整合成流程：真实Python子进程、文件请求、协议和监督共同运行。

fixture观察器不代表Windows内核身份，真实原生验证仍需Windows。
"""
from dataclasses import asdict
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ctflab_windows_control as control
from ctflab_windows_native import ProcessIdentity


class TestFiles:
    def __init__(self,root):self.root=root
    def guard(self,path):
        if path!=self.root and self.root not in path.parents:raise ValueError('outside')
        for part in (path,*path.parents):
            if part.is_symlink():raise ValueError('link')
        if not path.exists():raise ValueError('missing')
        if path.is_file() and path.stat().st_nlink!=1:raise ValueError('hardlink')
    def create(self,path):self.guard(path.parent);path.mkdir(mode=0o700)


CHILD = r'''
import json,sys,time
mode=sys.argv[1]
print(json.dumps({'QMP':{'version':{},'capabilities':[]}}),flush=True)
for line in sys.stdin:
 r=json.loads(line)
 if r['execute']=='query-status' and mode=='disconnect':break
 if r['execute']=='query-status' and mode=='timeout':time.sleep(.8);break
 if r['execute']=='query-status' and mode=='bad':print('not-json',flush=True);break
 if r['execute']=='system_powerdown':
  print(json.dumps({'event':'SHUTDOWN','data':{'guest':True}}),flush=True)
 value={'status':'running'} if r['execute']=='query-status' else {}
 print(json.dumps({'return':value,'id':r['id']}),flush=True)
 if r['execute']=='system_powerdown':break
'''


def fixture_worker(root,mode):
    files=TestFiles(root);config=control.settings(root,files.guard)
    child=[]
    def spawn():
        p=subprocess.Popen([sys.executable,'-u','-c',CHILD,mode],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        child.append(p);return p
    def observe(pid):return ProcessIdentity(pid,1,'synthetic-python','running')
    def source_check():
        if mode=='source-error':raise FileNotFoundError('fixture source missing')
        return True
    try:return control.run_owned(root,files,config,spawn,observe,source_check,timeout=.3)
    finally:
        for p in child:
            if p.poll() is None:p.terminate()
            p.wait(timeout=3)


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()/'run';self.root.mkdir()
        self.files=TestFiles(self.root)
        self.config={'schema':1,'instance_uuid':str(uuid.uuid4()),'generation':1,'inventory_sha256':'0'*64}
        control.write_new(self.root/'config.json',self.config,self.files.guard)

    def wait_file(self,path,timeout=5):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if path.exists():
                try:return json.loads(path.read_text())
                except json.JSONDecodeError:pass
            time.sleep(.02)
        self.fail('未取得预期结果: '+path.name)

    def worker(self,mode='normal'):
        p=subprocess.Popen([sys.executable,'-B',__file__,'fixture-worker',str(self.root),mode],
                           stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        def cleanup():
            # fixture始终在约定命令后退出；异常时只清理本测试自有子进程。
            if p.poll() is None:
                try:control.submit(self.root,self.files,'system_powerdown',str(uuid.uuid4()));p.wait(timeout=3)
                except Exception:p.terminate();p.wait(timeout=3)
            p.stderr.close()
        self.addCleanup(cleanup)
        self.wait_file(self.root/'control-ready.json')
        return p

    def send(self,action,op=None):
        directory=control.submit(self.root,self.files,action,op or str(uuid.uuid4()))
        return self.wait_file(directory/'response.json')

    def test_complete_background_control_reconnect_exit(self):
        p=self.worker()
        self.assertEqual(self.send('query-status')['qemu_status'],'running')
        # 另一个短命客户端进程退出，后台仍持续运行。
        code="import sys;sys.path.insert(0,sys.argv[1]);import ctflab_windows_control;print('client-exit')"
        client=subprocess.run([sys.executable,'-B','-c',code,str(Path(control.__file__).parent)],capture_output=True)
        self.assertEqual(client.returncode,0);self.assertIsNone(p.poll())
        self.assertEqual(self.send('query-status')['state'],'acknowledged')
        self.assertEqual(self.send('system_powerdown')['state'],'acknowledged')
        p.wait(timeout=5)
        result=self.wait_file(self.root/'result.json')
        self.assertEqual(result['returncode'],0)
        self.assertTrue(result['source_unchanged'])
        self.assertTrue(result['shutdown_guest_event'])
        self.assertFalse(result['graceful_stop_verified'])
        self.assertFalse(result['g0_passed'])
        self.assertIsNone(result['control_failure'])

    def test_missing_source_after_exit_keeps_result_unknown(self):
        p=self.worker('source-error');self.send('system_powerdown');p.wait(timeout=5)
        result=self.wait_file(self.root/'result.json')
        self.assertEqual(result['state'],'exited');self.assertIsNone(result['source_unchanged'])

    def test_duplicate_id_uses_original_response(self):
        p=self.worker();op=str(uuid.uuid4())
        first=self.send('query-status',op);second=self.send('query-status',op)
        self.assertEqual(first,second)
        with self.assertRaises(control.ControlError):control.submit(self.root,self.files,'system_powerdown',op)
        self.send('system_powerdown');p.wait(timeout=5)

    def test_partial_submission_not_executed(self):
        p=self.worker();op=str(uuid.uuid4());directory=self.root/('request-'+op);directory.mkdir()
        (directory/'request.json').write_text('{')
        self.assertEqual(self.send('query-status')['state'],'acknowledged')
        self.assertFalse((directory/'response.json').exists())
        self.send('system_powerdown');p.wait(timeout=5)

    def test_wrong_instance_refused_without_control(self):
        p=self.worker();op=str(uuid.uuid4());directory=self.root/('request-'+op);directory.mkdir()
        value=control.request_value(self.config,op,'system_powerdown');value['instance_uuid']=str(uuid.uuid4())
        control.write_new(directory/'request.json',value,self.files.guard)
        control.write_new(directory/'ready.json',{'ready':True},self.files.guard)
        self.assertEqual(self.wait_file(directory/'response.json')['state'],'unknown-or-rejected')
        self.assertIsNone(p.poll());self.assertFalse((self.root/(op+'.intent.json')).exists())
        self.send('system_powerdown');p.wait(timeout=5)

    def test_timeout_retains_evidence_no_replay(self):
        p=self.worker('timeout');op=str(uuid.uuid4())
        self.assertEqual(self.send('query-status',op)['state'],'unknown-or-rejected')
        p.wait(timeout=5)
        self.assertEqual(json.loads((self.root/(op+'.result.json')).read_text())['state'],'unknown')
        self.assertTrue((self.root/'failure.json').exists())
        self.assertEqual(len(list(self.root.glob('*.intent.json'))),2)  # start + one command

    def test_disconnect_retains_failure(self):
        p=self.worker('disconnect');self.send('query-status');p.wait(timeout=5)
        self.assertTrue((self.root/'failure.json').exists())
        self.assertEqual(self.wait_file(self.root/'result.json')['state'],'exited')

    def test_malformed_protocol_retains_failure(self):
        p=self.worker('bad');self.send('query-status');p.wait(timeout=5)
        self.assertTrue((self.root/'failure.json').exists())

    def test_fixed_qmp_command_no_tcp_or_hmp(self):
        cmd=control.qmp_command(Path('qemu.exe'),Path('test,disk.qcow2'))
        self.assertEqual(cmd[cmd.index('-qmp')+1],'stdio')
        self.assertEqual(cmd[cmd.index('-monitor')+1],'none')
        self.assertEqual(cmd[cmd.index('-nic')+1],'none')
        self.assertEqual(cmd[cmd.index('-accel')+1],'whpx')
        self.assertNotIn('tcp:',str(cmd));self.assertNotIn('tcg',cmd)

    def test_recovery_identity_mismatch_no_reconnect(self):
        expected=ProcessIdentity(101,102,'fixture','running')
        control.write_new(self.root/'worker.json',asdict(expected),self.files.guard)
        value=control.recovery(self.root,self.files,lambda pid:ProcessIdentity(pid,999,'fixture','running'))
        self.assertEqual(value['worker_identity'],'mismatch')
        self.assertFalse(value['control_reconnected']);self.assertFalse(value['automatic_replay'])

    def test_unsafe_request_and_unknown_fields_rejected(self):
        for value in ('../escape','a',str(uuid.uuid4()).upper()):
            with self.assertRaises(ValueError):control.request_value(self.config,value,'query-status')
        op=str(uuid.uuid4());value=control.request_value(self.config,op,'query-status');value['extra']=1
        with self.assertRaises(ValueError):control.validate_request(value,self.config,op)
        for command in ('quit','human-monitor-command','block-commit'):
            with self.assertRaises(ValueError):control.request_value(self.config,op,command)

    def test_guard_denial_prevents_request_creation(self):
        class Denied(TestFiles):
            def guard(self,path):raise PermissionError('denied')
        before=set(self.root.iterdir())
        with self.assertRaises(PermissionError):
            control.submit(self.root,Denied(self.root),'query-status',str(uuid.uuid4()))
        self.assertEqual(set(self.root.iterdir()),before)

    def test_output_no_overwrite_and_read_limit(self):
        with self.assertRaises(FileExistsError):control.write_new(self.root/'config.json',{},self.files.guard)
        with self.assertRaises(ValueError):control.read_json(self.root/'config.json',self.files.guard,3)

    def test_wrong_platform_has_no_side_effects(self):
        with mock.patch.object(control.os,'name','posix'),mock.patch.object(control,'prepare',side_effect=AssertionError):
            self.assertEqual(control.main(['start','--run','unused','--inventory','unused']),1)

    def test_two_instances_are_independent(self):
        first=self.root;files1=self.files
        p1=self.worker()
        self.root=first.parent/'run2';self.root.mkdir();self.files=TestFiles(self.root)
        config2=dict(self.config,instance_uuid=str(uuid.uuid4()))
        control.write_new(self.root/'config.json',config2,self.files.guard)
        p2=self.worker()
        self.send('system_powerdown');p2.wait(timeout=5)
        self.assertIsNone(p1.poll())
        self.root=first;self.files=files1
        self.assertEqual(self.send('query-status')['state'],'acknowledged')
        self.send('system_powerdown');p1.wait(timeout=5)

    def test_restart_with_intent_never_spawns_again(self):
        control.write_new(self.root/'start.intent.json',{},self.files.guard)
        spawn=mock.Mock(side_effect=AssertionError)
        with self.assertRaises(FileExistsError):
            control.run_owned(self.root,self.files,self.config,spawn,lambda pid:None,lambda:True)
        spawn.assert_not_called()

    def test_booleans_not_accepted_as_schema_or_generation(self):
        op=str(uuid.uuid4())
        for key in ('schema','generation'):
            value=control.request_value(self.config,op,'query-status');value[key]=True
            with self.assertRaises(ValueError):control.validate_request(value,self.config,op)

    def test_log_failure_still_drains_child(self):
        path=self.root/'existing.log';path.write_bytes(b'preserve')
        p=subprocess.Popen([sys.executable,'-c',"import sys;sys.stderr.buffer.write(b'x'*200000)"],stderr=subprocess.PIPE)
        log=control.BoundedLog(p.stderr,path,100)
        p.wait(timeout=5)
        self.assertFalse(log.finish());self.assertEqual(path.read_bytes(),b'preserve')

    def test_stderr_capture_is_bounded(self):
        p=subprocess.Popen([sys.executable,'-c',"import sys;sys.stderr.buffer.write(b'x'*50000)"],stderr=subprocess.PIPE)
        log=control.BoundedLog(p.stderr,self.root/'bounded.log',100)
        p.wait(timeout=5);self.assertTrue(log.finish())
        self.assertEqual((self.root/'bounded.log').stat().st_size,100);self.assertTrue(log.truncated)


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='fixture-worker':raise SystemExit(fixture_worker(Path(sys.argv[2]),sys.argv[3]))
    unittest.main()
