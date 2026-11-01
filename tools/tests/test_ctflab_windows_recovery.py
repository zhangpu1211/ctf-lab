"""恢复候选的故障测试；可选QEMU仅machine none，不启动来宾或挂载资产。"""
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
from dataclasses import asdict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ctflab_windows_recovery as runtime
from ctflab_windows_native import ProcessIdentity
from ctflab_tls_endpoint import provision, server_arguments, client_context, CERT_FILES
from ctflab_qmp_tls import QMPClient
from ctflab_rfb_tls import RFBClient, DisplayError

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.ident=str(uuid.uuid4())
        self.config={'schema':1,'instance_uuid':self.ident,'generation':1,
            'name':'ctflab-'+self.ident+'-g1-smoke','qmp_port':18001,'vnc_port':18002,
            'certificates':{n:'0'*64 for n in CERT_FILES}}
        runtime.record(self.root/'endpoint.json',self.config)
        runtime.record(self.root/'config.json',{'schema':1,'instance_uuid':self.ident,'generation':1,'inventory_sha256':'0'*64})
        self.identity=ProcessIdentity(123,456,'synthetic-qemu','running')
        runtime.record(self.root/'binding.json',{'instance_uuid':self.ident,'generation':1,'identity':asdict(self.identity)})
        runtime.record(self.root/'control.lock',{})
        self.calls=[]
        owner=self
        class Connection:
            def __init__(self,*args):owner.calls.append('connect')
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
            def close(self):pass
            def command(self,action):
                owner.calls.append(action)
                if owner.fail:raise ConnectionError('synthetic lost response')
                return {'return':{'status':'running'}}
        self.fail=False
        self.client=runtime.RuntimeClient(self.root,observe=lambda pid:self.identity,connector=Connection)
    def test_retained_native_exit_is_bound_and_does_not_reopen_pid(self):
        runtime.record(self.root/'observer-exit.json', {'state':'exited','identity':asdict(self.identity),'returncode':7})
        self.client.observe=lambda pid: self.fail('不应重开已退出 PID')
        self.assertEqual(self.client.status()['identity'],'exited')
        self.assertEqual(self.calls,[])

    def test_retained_exit_wrong_binding_rejected(self):
        runtime.record(self.root/'observer-exit.json', {'state':'exited','identity':{},'returncode':0})
        with self.assertRaises(ValueError):self.client.status()

    def test_status_reconnect(self):
        self.assertTrue(self.client.status()['control_reconnected'])
        self.assertEqual(self.calls,['connect','query-status'])
    def test_unknown_identity_never_connects(self):
        self.client.observe=lambda pid:ProcessIdentity(pid,None,None,'unknown')
        with self.assertRaises(ValueError):self.client.connect()
        self.assertEqual(self.calls,[])
    def test_lost_reply_never_replayed(self):
        self.fail=True;op=str(uuid.uuid4())
        self.assertEqual(self.client.powerdown(op)['state'],'unknown')
        self.assertEqual(self.client.powerdown(op)['state'],'unknown')
        self.assertEqual(self.calls.count('system_powerdown'),1)
        with self.assertRaises(ValueError):self.client.powerdown(str(uuid.uuid4()))
    def test_persisted_intent_never_replayed(self):
        op=str(uuid.uuid4());runtime.record(self.root/f'powerdown-{op}.intent.json',{})
        self.assertEqual(self.client.powerdown(op)['state'],'unknown');self.assertEqual(self.calls,[])
    def test_acknowledged_is_not_shutdown(self):
        result=self.client.powerdown(str(uuid.uuid4()))
        self.assertEqual(result['state'],'acknowledged');self.assertFalse(result['graceful_stop_verified'])
    def test_wrong_instance_rejected(self):
        self.client.config=dict(self.config,instance_uuid=str(uuid.uuid4()))
        with self.assertRaises(ValueError):self.client.connect()
        self.assertEqual(self.calls,[])
    def test_launch_loopback_and_no_network(self):
        args=runtime.launch_arguments(Path('qemu'),Path('disk'),self.root,self.config)
        self.assertIn('none',args);self.assertIn('127.0.0.1:12102,tls-creds=ctflab-tls,tls-authz=ctflab-client',args)
        self.assertIn('none',args[args.index('-nic')+1:]);self.assertNotIn('stdio',args)
    def test_config_rejects_boolean_port(self):
        with self.assertRaises(ValueError):runtime.validate_config(dict(self.config,qmp_port=True))
    def test_dimension_limit(self):
        client=object.__new__(RFBClient)
        with self.assertRaises(DisplayError):client.resize(65535,65535)
    def test_certificate_tamper(self):
        try:import cryptography
        except ImportError:self.skipTest('证书生成依赖未安装')
        hashes=provision(self.root/'tls',self.ident)
        (self.root/'tls'/'client-cert.pem').write_bytes(b'changed')
        with self.assertRaises(ValueError):client_context(self.root/'tls',hashes)

@unittest.skipUnless(os.environ.get('CTFLAB_RECOVERY_QEMU'),'显式设置本地无来宾QEMU测试路径后运行')
class QemuReconnectTests(unittest.TestCase):
    def test_control_display_reconnect_and_reject_unauthenticated(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();ident=str(uuid.uuid4());name='ctflab-'+ident
            hashes=provision(root/'tls',ident)
            sockets=[]
            for _ in range(2):
                sock=socket.socket();sock.bind(('127.0.0.1',0));sockets.append(sock)
            qmp,vnc=[s.getsockname()[1] for s in sockets]
            for sock in sockets:sock.close()
            args=[os.environ['CTFLAB_RECOVERY_QEMU'],'-machine','none','-accel','tcg','-S','-nodefaults','-display','none','-name',name]
            args+=server_arguments(root/'tls',ident)
            args+=['-chardev',f'socket,id=control,host=127.0.0.1,port={qmp},server=on,wait=off,tls-creds=ctflab-tls,tls-authz=ctflab-client','-mon','chardev=control,mode=control','-vnc',f'127.0.0.1:{vnc-5900},tls-creds=ctflab-tls,tls-authz=ctflab-client']
            with tempfile.TemporaryFile() as log:
                process=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=log)
                try:
                    deadline=time.monotonic()+5
                    while True:
                        try:
                            c=QMPClient(qmp,root/'tls',hashes,name);c.close();break
                        except ConnectionRefusedError:
                            if time.monotonic()>deadline:raise
                            time.sleep(.05)
                    context=ssl.create_default_context(cafile=str(root/'tls'/'ca-cert.pem'))
                    with self.assertRaises((OSError,ssl.SSLError)):
                        with socket.create_connection(('127.0.0.1',qmp),timeout=2) as raw:
                            with context.wrap_socket(raw,server_hostname='localhost') as bad:
                                if not bad.recv(1):raise ConnectionError('无证书被关闭')
                    with self.assertRaises(ValueError):QMPClient(qmp,root/'tls',hashes,'wrong-name')
                    for _ in range(2):
                        with QMPClient(qmp,root/'tls',hashes,name) as control:
                            self.assertIn('return',control.command('query-status'))
                        display=RFBClient(vnc,root/'tls',hashes)
                        try:self.assertTrue(display.frame().startswith(b'P6\n640 480\n'))
                        finally:display.close()
                        self.assertIsNone(process.poll())
                finally:
                    # 仅回收本测试创建且无来宾/磁盘的fixture；从不按外部PID操作。
                    process.terminate();process.wait(timeout=5)
                    log.seek(0);print(log.read().decode(errors='replace'))

if __name__=='__main__':unittest.main()
