"""真实自有Python子进程的管道集成测试，不启动虚拟机。"""
from pathlib import Path
import subprocess
import sys
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_qmp_transport import OwnedPipe, TransportError

CHILD = '''
import json,sys,time
mode=sys.argv[1]
print(json.dumps({'QMP':{'version':{},'capabilities':[]}}),flush=True)
for line in sys.stdin:
 r=json.loads(line)
 if r['execute']=='query-status' and mode=='timeout': time.sleep(1);break
 if r['execute']=='query-status' and mode=='disconnect':break
 if r['execute']=='system_powerdown':
  print(json.dumps({'event':'SHUTDOWN'}),flush=True)
 print(json.dumps({'return':{},'id':r['id']}),flush=True)
 if r['execute']=='system_powerdown':break
'''

class PipeTests(unittest.TestCase):
    def start(self,mode='normal',timeout=1):
        p=subprocess.Popen([sys.executable,'-u','-c',CHILD,mode],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        def cleanup():
            if p.poll() is None:p.terminate()
            p.wait(timeout=5)
            for stream in (p.stdin,p.stdout):
                if not stream.closed:stream.close()
        self.addCleanup(cleanup)
        t=OwnedPipe(p,timeout);t.connect();return p,t
    def test_handshake_query_powerdown_exit(self):
        p,t=self.start()
        self.assertEqual(t.command('query-status')['kind'],'response')
        t.command('system_powerdown');p.wait(timeout=3)
        self.assertEqual(t.observe()['state'],'exited')
        self.assertFalse(t.observe()['graceful_stop_verified'])
        self.assertEqual(t.events[0]['event'],'SHUTDOWN');t.reap()
    def test_timeout_does_not_kill_or_replay(self):
        p,t=self.start('timeout',.2);start=time.monotonic()
        with self.assertRaises(TransportError):t.command('query-status')
        self.assertLess(time.monotonic()-start,1)
        self.assertIsNone(p.poll())
        self.assertFalse(t.observe()['control_available'])
        p.wait(timeout=3);t.reap()
    def test_disconnect_unknown(self):
        p,t=self.start('disconnect')
        with self.assertRaises(TransportError):t.command('query-status')
        p.wait(timeout=3);t.reap()
    def test_reap_refuses_live_process(self):
        p,t=self.start()
        with self.assertRaises(TransportError):t.reap()
        self.assertIsNone(p.poll())
        t.command('system_powerdown');p.wait(timeout=3);t.reap()
