"""逐块准备取消与历史进度；只用自有普通文件/临时数据库，不运行来宾。"""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
import uuid
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ctflab_generation_store as storage
import ctflab_desktop_bridge as bridge
from ctflab_contract import ContractError,canonical
from ctflab_local_adapter import process_actor
from ctflab_local_service import LocalService
from ctflab_windows_probe import request


class ProgressTests(unittest.TestCase):
    def setUp(self):
        from test_ctflab_generation_store import GenerationTests
        GenerationTests.setUp(self)
        self.op=str(uuid.uuid4())

    def begin(self):
        self.store.begin(self.op,'prepare',0)

    def prepare(self,**kwargs):
        with self.store.locked():
            self.begin();return self.store.prepare_generation(self.op,0,**kwargs)

    def test_complete_progress_bound_and_readonly_after_reopen(self):
        result=self.prepare();self.assertEqual(result['generation'],1)
        before=(self.store.root/'ledger.sqlite3').read_bytes()
        p=storage.GenerationStore(self.store.root).preparation_progress()
        self.assertEqual(p['stage'],'completed');self.assertEqual(p['target_generation'],1)
        self.assertEqual(p['files_completed'],3);self.assertEqual(p['total_files'],3)
        self.assertTrue(p['historical']);self.assertFalse(p['current_runtime_verified']);self.assertFalse(p['automatic_replay'])
        self.assertNotIn(str(self.base),canonical(p));self.assertEqual(before,(self.store.root/'ledger.sqlite3').read_bytes())

    def test_cancel_each_digest_before_consuming_second_chunk(self):
        real=storage._preparation_digest
        for stage in ('source-check','copy-check','source-recheck'):
            with self.subTest(stage=stage):
                # 每个子例使用不同根，失败目录均由测试私有临时目录管理。
                temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
                origin=Path(temp.name).resolve()/'source';origin.write_bytes(b'x'*(8*1024**2))
                manifest=copy.deepcopy(self.manifest);manifest['assets']['linux']['sha256']=storage.digest(origin)
                store=storage.GenerationStore.create(Path(temp.name).resolve()/'state',manifest,str(uuid.uuid4()),{'linux':origin})
                op=str(uuid.uuid4());cancel=[False];current=[None];counts=[];writer=store._write_preparation_progress
                def report(value,**kwargs):current[0]=value['stage'];return writer(value,**kwargs)
                def digest(path,check,progress):
                    selected=current[0]==stage
                    def counted(count):
                        progress(count)
                        if selected:counts.append(count);cancel[0]=True
                    return real(path,check,counted)
                with store.locked(),mock.patch.object(store,'_write_preparation_progress',side_effect=report),mock.patch.object(storage,'_preparation_digest',side_effect=digest):
                    store.begin(op,'prepare',0);value=store.prepare_generation(op,0,cancelled=lambda:cancel[0])
                self.assertEqual(value['state'],'cancelled');self.assertEqual(counts,[1024**2])
                self.assertEqual(store.snapshot()['active_generation'],0);self.assertEqual(store.preparation_progress()['stage'],'cancelled')
                self.assertEqual(storage.digest(origin),manifest['assets']['linux']['sha256'])
                self.assertTrue(list((store.root/'generations').iterdir()))

    def test_cancel_copy_preserves_partial_and_original(self):
        cancel=[False];original_open=Path.open;current=[None];report=self.store._write_preparation_progress
        def recorded(value,**kwargs):current[0]=value['stage'];return report(value,**kwargs)
        class Reader:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):self.stream.close()
            def read(self,*args):
                block=self.stream.read(*args)
                if block:cancel[0]=True
                return block
        def opened(path,*args,**kwargs):
            stream=original_open(path,*args,**kwargs)
            return Reader(stream) if path==self.base and current[0]=='copy' else stream
        before=storage.digest(self.base)
        with mock.patch.object(self.store,'_write_preparation_progress',side_effect=recorded),mock.patch.object(Path,'open',opened):
            value=self.prepare(cancelled=lambda:cancel[0])
        self.assertEqual(value['state'],'cancelled');self.assertEqual(storage.digest(self.base),before)
        partial=list((self.store.root/'generations').glob('*/*/disk.qcow2'));self.assertEqual(len(partial),1)
        self.assertGreater(partial[0].stat().st_size,0);self.assertEqual(self.store.snapshot()['active_generation'],0)
        self.assertEqual(self.store.preparation_progress()['stage'],'cancelled')

    def test_completion_progress_is_atomic_with_generation_selection(self):
        writer=self.store._write_preparation_progress
        def failed(value,**kwargs):
            if value['stage']=='completed':raise OSError('controlled commit failure')
            return writer(value,**kwargs)
        with mock.patch.object(self.store,'_write_preparation_progress',side_effect=failed),self.assertRaises(OSError):self.prepare()
        self.assertEqual(self.store.snapshot()['active_generation'],0)
        self.assertEqual(self.store.preparation_progress()['stage'],'before-commit')
        self.assertEqual(self.store.snapshot()['unresolved'][0]['id'],self.op)
        self.assertEqual(len(list((self.store.root/'generations').glob('*/*/disk.qcow2'))),3)

    def test_late_cancel_after_commit_keeps_completed_progress(self):
        flag=[False]
        value=self.prepare(cancelled=lambda:flag[0],checkpoint=lambda stage:flag.__setitem__(0,True) if stage=='after-commit' else None)
        self.assertEqual(value['state'],'prepared');self.assertEqual(self.store.preparation_progress()['stage'],'completed')
        self.assertEqual(self.store.snapshot()['active_generation'],1)

    def test_bad_record_is_refused_without_repair_or_path_leak(self):
        self.prepare();good=self.store.preparation_progress();private={k:v for k,v in good.items() if k not in ('historical','current_runtime_verified','automatic_replay')}
        for mutation in ({'operation_id':str(uuid.uuid4())},{'instance_uuid':str(uuid.uuid4())},{'bytes_processed':-1},{'total_files':400},
                {'node':'/private','material':'disk'},{'stage':'running'},{'total_bytes':True},{'updated_at':'bad'},{'extra':'private'}):
            changed=dict(private,**mutation)
            with self.store.db(write=True) as db:db.execute('UPDATE metadata SET value=? WHERE key=?',(canonical(changed),'preparation-progress-'+self.op))
            before=(self.store.root/'ledger.sqlite3').read_bytes()
            with self.subTest(mutation=mutation),self.assertRaises(ContractError):self.store.preparation_progress()
            self.assertEqual(before,(self.store.root/'ledger.sqlite3').read_bytes())

    def test_progress_read_does_not_spawn_backend_and_rejects_caller_fields(self):
        self.prepare();LocalService.create(self.store.root/'desktop-contract')
        spawn=mock.Mock();backend=mock.Mock();before=(self.store.root/'ledger.sqlite3').read_bytes()
        value=bridge.dispatch(self.store.root,{'action':'preparation-progress'},spawn=spawn,make_backend=backend)
        self.assertFalse(value['progress']['request_matches']);self.assertEqual(value['progress']['stage'],'completed')
        spawn.assert_not_called();backend.assert_not_called();self.assertEqual(before,(self.store.root/'ledger.sqlite3').read_bytes())
        with self.assertRaises(ContractError):bridge.dispatch(self.store.root,{'action':'preparation-progress','actor':'other'})

    def test_real_cancellation_request_during_hash_does_not_select_generation(self):
        from ctflab_scenario_coordinator import ScenarioCoordinator
        service=LocalService.create(self.store.root/'desktop-contract');actor=process_actor()
        prep=request(self.instance,'prepare',parameters={'course_id':'c01','baseline_id':'base'})
        accepted=service.submit(prep,actor);entered=threading.Event();resume=threading.Event();real=storage._preparation_digest;results=[]
        def paused(path,cancelled,progress):
            entered.set();self.assertTrue(resume.wait(5));return real(path,cancelled,progress)
        worker=threading.Thread(target=lambda:results.append(service.execute(accepted['operation_id'],actor,self.backend)))
        with mock.patch.object(storage,'_preparation_digest',side_effect=paused):
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                snapshot=service.status(request(self.instance,'status'),actor)
                p=bridge.dispatch(self.store.root,{'action':'preparation-progress'})['progress'];self.assertTrue(p['request_matches'])
                cancel=request(self.instance,'cancel',generation=snapshot['generation'],revision=snapshot['state_revision'],parameters={'operation_id':accepted['operation_id']})
                service.submit(cancel,actor)
            finally:resume.set();worker.join(5)
        self.assertFalse(worker.is_alive());self.assertEqual(len(results),1);self.assertTrue(results[0]['cancelled'])
        self.assertEqual(self.store.snapshot()['active_generation'],0);self.assertEqual(self.store.preparation_progress()['stage'],'cancelled')

    def test_busy_optional_checkpoint_preserves_previous_record_without_failing_work(self):
        self.prepare();p=self.store.preparation_progress();value={k:v for k,v in p.items() if k not in ('historical','current_runtime_verified','automatic_replay')}
        before=(self.store.root/'ledger.sqlite3').read_bytes()
        connection=sqlite3.connect(self.store.root/'ledger.sqlite3',isolation_level=None,timeout=0)
        try:
            connection.execute('BEGIN');connection.execute('SELECT * FROM metadata').fetchall()
            self.assertIs(self.store._write_preparation_progress(value),False)
        finally:connection.close()
        self.assertEqual(before,(self.store.root/'ledger.sqlite3').read_bytes())
        self.assertEqual(self.store.preparation_progress(),p)
        with mock.patch.object(self.store,'db',side_effect=sqlite3.OperationalError('disk I/O error')):
            with self.assertRaises(sqlite3.OperationalError):self.store._write_preparation_progress(value)

    def test_old_store_has_no_fabricated_progress(self):
        before=(self.store.root/'ledger.sqlite3').read_bytes()
        self.assertIsNone(storage.GenerationStore(self.store.root).preparation_progress())
        self.assertEqual(before,(self.store.root/'ledger.sqlite3').read_bytes())
