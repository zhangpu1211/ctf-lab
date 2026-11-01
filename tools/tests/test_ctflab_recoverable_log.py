"""自有Python生产者与真实FIFO/接收器；不启动QEMU或操作用户实例。"""
from dataclasses import asdict
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ctflab_recoverable_log as module
from ctflab_bounded_log import collect,LIMIT
from ctflab_contract import ContractError
from ctflab_generation_store import private_directory,digest
from ctflab_qemu_driver import native_observe
from ctflab_windows_recovery import record


@unittest.skipUnless(sys.platform in ('linux','darwin'),'需POSIX FIFO；Windows保留旧日志链')
class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.parent=Path(self.temp.name).resolve();self.root=self.parent/'00000001';private_directory(self.root)
        self.scope={'instance_uuid':str(uuid.uuid4()),'generation':1,'node':'server','attempt':'00000001'}
        record(self.root/'launch.json',{'recoverable_logs':True,'log_scope':self.scope})
        self.fd=None;self.children=[]
        self.addCleanup(self.finish)

    def finish(self):
        if self.fd is not None:os.close(self.fd);self.fd=None
        # 仅收回本测试亲自创建的Popen句柄，不使用磁盘记录中的PID。
        for process in self.children:
            if process.poll() is None:process.terminate()
            process.wait(timeout=10)
            for stream in (process.stdin,process.stdout,process.stderr):
                if stream is not None and not stream.closed:stream.close()

    def initialize(self):self.fd=module.initialize(self.root)
    def receiver(self,operation=None):
        value=module.spawn(self.root,operation or str(uuid.uuid4()))
        if value.get('process') is not None:self.children.append(value['process'])
        self.assertEqual(value['state'],'log-receiver-requested')
        return value['process']
    def bind(self,pid):
        record(self.root/'binding.json',{'identity':asdict(native_observe(pid)),
            'launch_sha256':digest(self.root/'launch.json')})
    def wait_for(self,condition,seconds=10):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if condition():return
            time.sleep(.02)
        self.fail('自有通道未在期限内满足条件')
    def logs(self):return sorted((self.root/'log-channel'/'sessions').glob('*/qemu-stderr.log'))

    def test_initialize_binds_inode_and_refuses_overwrite_or_unsupported_platform(self):
        self.initialize();self.assertEqual(module.channel(self.root)[1]['scope'],self.scope)
        with self.assertRaises(FileExistsError):module.initialize(self.root)
        with patch.object(module.sys,'platform','win32'):
            with self.assertRaises(ContractError):module.channel(self.root)
        self.assertEqual(os.fstat(self.fd).st_ino,(self.root/'log-channel'/'stderr.fifo').stat().st_ino)

    def test_receiver_crash_reconnects_bounded_queue_without_replaying_producer(self):
        self.initialize();first=self.receiver('00000000-0000-0000-0000-000000000001')
        script='import sys;sys.stderr.buffer.write(b"first");sys.stderr.buffer.flush();sys.stdin.buffer.read(1);sys.stderr.buffer.write(b"x"*(9*1024**2));sys.stderr.buffer.flush()'
        producer=subprocess.Popen([sys.executable,'-I','-B','-c',script],stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,stderr=self.fd,close_fds=True)
        self.children.append(producer);self.bind(producer.pid);os.close(self.fd);self.fd=None
        self.wait_for(lambda:sum(p.stat().st_size for p in self.logs())==5)
        first.terminate();first.wait(timeout=10)
        producer.stdin.write(b'x');producer.stdin.flush();time.sleep(.1)
        self.assertIsNone(producer.poll(),'背压应保留生产者，不能因接收器退出收到SIGPIPE')
        state=module.status(self.root);self.assertTrue(state['rearm_allowed']);self.assertEqual(state['source_identity'],'running')
        second=self.receiver('00000000-0000-0000-0000-000000000002')
        self.assertEqual(producer.wait(timeout=20),0);producer.stdin.close()
        self.assertEqual(second.wait(timeout=20),0)
        logs=self.logs();self.assertEqual(sum(p.stat().st_size for p in logs),LIMIT)
        self.assertEqual(logs[0].read_bytes()+logs[1].read_bytes(),b'first'+b'x'*(LIMIT-5))
        self.assertTrue(all(p.exists() for p in logs));self.assertFalse(module.status(self.root)['capture_complete'])

    def test_same_operation_is_not_replayed_and_live_receiver_excludes_second_reader(self):
        self.initialize();self.bind(os.getpid());operation=str(uuid.uuid4());receiver=self.receiver(operation)
        again=module.spawn(self.root,operation);self.assertEqual(again['state'],'log-receiver-already-requested')
        with self.assertRaises(ContractError):module.spawn(self.root,str(uuid.uuid4()))
        self.assertFalse(module.status(self.root)['rearm_allowed'])
        os.close(self.fd);self.fd=None;self.assertEqual(receiver.wait(timeout=10),0)
        self.assertEqual(len(module.sessions(self.root)),1)

    def test_replaced_fifo_symlink_and_changed_launch_are_refused(self):
        self.initialize();directory=self.root/'log-channel';fifo=directory/'stderr.fifo'
        fifo.rename(directory/'preserved.fifo');os.mkfifo(fifo,0o600)
        with self.assertRaises(ContractError):module.channel(self.root)
        fifo.unlink();fifo.symlink_to(directory/'preserved.fifo')
        with self.assertRaises(ContractError):module.channel(self.root)
        self.assertTrue((directory/'preserved.fifo').exists())

    def test_cross_scope_or_intent_binding_refused_without_new_session(self):
        self.initialize();record(self.root/'binding.json',{'launch_sha256':'0'*64,'identity':{}})
        with self.assertRaises(ContractError):module.status(self.root)
        directory,value=module.channel(self.root);target=directory/'sessions'/str(uuid.uuid4());private_directory(target)
        record(target/'intent.json',{'operation_id':target.name,'channel_sha256':'0'*64,'automatic_replay':False})
        with self.assertRaises(ContractError):module.spawn(self.root,str(uuid.uuid4()))
        self.assertEqual(len(list((directory/'sessions').iterdir())),1)

    def test_zero_shared_budget_still_drains_without_changing_legacy_zero_rejection(self):
        target=self.parent/'zero';private_directory(target)
        value=collect(target,'qemu-stderr',io.BytesIO(b'x'*10000),limit=0,remaining_budget=True)
        self.assertEqual(value['stored_bytes'],0);self.assertEqual(value['discarded_bytes'],10000)
        self.assertEqual((target/'qemu-stderr.log').read_bytes(),b'')
        with self.assertRaises(ContractError):collect(self.parent,'worker-console',io.BytesIO(b''),limit=0)

    def worker_spec(self):
        binary=self.parent/'fake-qemu';binary.write_bytes(b'non-executable-fixture');binary.chmod(0o600)
        disk=self.parent/'derived';disk.write_bytes(b'derived-only');disk.chmod(0o600)
        spec=module.read(self.root/'launch.json');spec.update(binary=str(binary),binary_sha256=digest(binary),
            disk=str(disk),disk_identity=[disk.stat().st_dev,disk.stat().st_ino],argv=[str(binary)],certificates={})
        (self.root/'launch.json').write_text(__import__('json').dumps(spec));record(self.root/'control.lock',{})
        return binary

    def test_production_worker_passes_owned_fifo_and_preserves_start_intent_on_unknown(self):
        import ctflab_qemu_driver as driver
        from types import SimpleNamespace
        from ctflab_windows_native import ProcessIdentity
        binary=self.worker_spec();trace=[]
        def popen(*args,**kwargs):
            descriptor=kwargs['stderr'];self.assertIs(type(descriptor),int)
            self.assertTrue(__import__('stat').S_ISFIFO(os.fstat(descriptor).st_mode));trace.append(descriptor)
            return SimpleNamespace(pid=123)
        with patch.object(module,'spawn',return_value={'state':'log-receiver-requested','process':object()}),\
             patch.object(driver.subprocess,'Popen',side_effect=popen),patch.object(driver,'fingerprints',return_value={}),\
             patch.object(driver,'native_observe',side_effect=lambda pid:ProcessIdentity(pid,456,str(binary),'running')),\
             patch.object(driver,'spawn_worker'),patch('ctflab_supervisor_fault.wait',return_value=0):
            driver.worker(self.root)
        self.assertEqual(len(trace),1)
        with self.assertRaises(OSError):os.fstat(trace[0])
        self.assertTrue((self.root/'binding.json').exists());self.assertTrue((self.root/'exit.json').exists())

    def test_production_worker_never_starts_producer_after_missing_receiver_receipt(self):
        import ctflab_qemu_driver as driver
        from ctflab_windows_native import ProcessIdentity
        binary=self.worker_spec();descriptors=[];original=module.initialize
        def initialized(root):
            fd=original(root);descriptors.append(fd);return fd
        with patch.object(module,'initialize',side_effect=initialized),patch.object(module,'spawn',return_value={'state':'unknown'}),\
             patch.object(driver,'fingerprints',return_value={}),\
             patch.object(driver,'native_observe',side_effect=lambda pid:ProcessIdentity(pid,456,str(binary),'running')),\
             patch.object(driver.subprocess,'Popen',side_effect=AssertionError('接收器未确认不能启动生产者')):
            with self.assertRaises(ContractError):driver.worker(self.root)
        self.assertTrue((self.root/'start.intent.json').exists());self.assertFalse((self.root/'binding.json').exists())
        with self.assertRaises(OSError):os.fstat(descriptors[0])

    def test_session_cap_preserves_previous_intents(self):
        self.initialize();directory,value=module.channel(self.root)
        for number in range(module.MAX_SESSIONS):
            identity=str(uuid.UUID(int=number+1));target=directory/'sessions'/identity;private_directory(target)
            record(target/'intent.json',{'operation_id':identity,'channel_sha256':digest(directory/'channel.json'),'automatic_replay':False})
        with self.assertRaises(ContractError):module.spawn(self.root,str(uuid.uuid4()))
        self.assertEqual(len(module.sessions(self.root)),module.MAX_SESSIONS)


    def test_receiver_and_producer_finish_after_launching_parent_voluntary_exit(self):
        code="""import os,subprocess,sys
from pathlib import Path
from dataclasses import asdict
sys.path.insert(0,sys.argv[1])
import ctflab_recoverable_log as module
from ctflab_qemu_driver import native_observe
from ctflab_windows_recovery import record
from ctflab_generation_store import digest
root=Path(sys.argv[2]);fd=module.initialize(root)
reply=module.spawn(root,'00000000-0000-0000-0000-000000000003')
if reply['state']!='log-receiver-requested':raise SystemExit(2)
producer=subprocess.Popen([sys.executable,'-I','-B','-c','import sys,time;time.sleep(.3);sys.stderr.buffer.write(b"p"*(1024**2));sys.stderr.buffer.flush()'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=fd,close_fds=True,start_new_session=True)
record(root/'binding.json',{'identity':asdict(native_observe(producer.pid)),'launch_sha256':digest(root/'launch.json')})
os.close(fd);os._exit(73)
"""
        parent=subprocess.run([sys.executable,'-I','-B','-c',code,str(Path(__file__).resolve().parents[1]),str(self.root)],
            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=15)
        self.assertEqual(parent.returncode,73,parent.stderr.decode())
        target=self.root/'log-channel'/'sessions'/'00000000-0000-0000-0000-000000000003'
        self.wait_for(lambda:(target/'complete.json').exists(),seconds=15)
        self.assertEqual((target/'qemu-stderr.log').read_bytes(),b'p'*(1024**2))
        self.assertFalse(module.read(target/'complete.json')['process_exit_verified'])

    def test_full_old_segment_leaves_zero_budget_and_new_receiver_only_drains(self):
        self.initialize();self.bind(os.getpid());directory,value=module.channel(self.root)
        def intent(identity):
            target=directory/'sessions'/identity;private_directory(target)
            record(target/'intent.json',{'operation_id':identity,'channel_sha256':digest(directory/'channel.json'),'automatic_replay':False})
            return target
        old=intent('00000000-0000-0000-0000-000000000001');log=old/'qemu-stderr.log'
        log.write_bytes(b'z'*LIMIT);log.chmod(0o600)
        new=intent('00000000-0000-0000-0000-000000000002')
        with patch.object(module,'collect',return_value={'stored_bytes':0,'received_bytes':0,'discarded_bytes':0}) as collect:
            module.run(self.root,new.name)
        self.assertEqual(collect.call_args.kwargs['limit'],0);self.assertTrue(collect.call_args.kwargs['remaining_budget'])
        self.assertEqual(log.stat().st_size,LIMIT);self.assertEqual(module.stored(self.root),LIMIT)

    def test_partial_ready_file_waits_for_same_child_without_spawning_again(self):
        from types import SimpleNamespace
        from ctflab_windows_native import ProcessIdentity
        import ctflab_qemu_driver as driver
        self.initialize();operation=str(uuid.uuid4());calls=[];original=module.read
        identity=ProcessIdentity(123,456,'synthetic-owned-child','running')
        def spawned(*args,**kwargs):
            target=self.root/'log-channel'/'sessions'/operation
            (target/'ready.json').write_text('{');(target/'ready.json').chmod(0o600)
            return SimpleNamespace(pid=123,poll=lambda:None)
        def reading(path):
            if Path(path).name!='ready.json':return original(path)
            calls.append(str(path))
            if len(calls)==1:raise ValueError('接收器尚未写完就绪记录')
            return {'operation_id':operation,'channel_sha256':digest(self.root/'log-channel'/'channel.json'),
                'receiver_identity':asdict(identity)}
        with patch.object(module.subprocess,'Popen',side_effect=spawned) as spawn,patch.object(module,'read',side_effect=reading),\
             patch.object(driver,'native_observe',return_value=identity):
            result=module.spawn(self.root,operation)
        self.assertEqual(result['state'],'log-receiver-requested');self.assertEqual(spawn.call_count,1)
        self.assertGreaterEqual(len(calls),2)


if __name__=='__main__':unittest.main()
