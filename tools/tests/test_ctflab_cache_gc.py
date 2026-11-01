"""回收中断与未知回执：仅本测试新建的临时字节，不访问真实镜像或缓存。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
from ctflab_content_cache import ContentCache
import ctflab_cache_gc as gc


class Interrupted(BaseException):pass


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.cache=ContentCache.create(self.root/'cache')
        self.operation=str(uuid.uuid4());self.collector=gc.Collector(self.cache)
    def object(self,data):
        name=hashlib.sha256(data).hexdigest();path=self.cache.root/'objects'/name
        path.write_bytes(data);path.chmod(0o600);return path
    def interrupted(self,suffix,*,after=False):
        original=gc.record
        def record(path,value):
            if path.name.endswith(suffix):
                if after:original(path,value)
                raise Interrupted()
            return original(path,value)
        return patch.object(gc,'record',side_effect=record)
    def begin_interrupted(self,suffix,*,after=False):
        plan=self.cache.gc_preview()
        with self.interrupted(suffix,after=after),self.assertRaises(Interrupted):
            self.cache.gc_start(self.operation,plan['plan_sha256'])
        return plan
    def test_preview_binds_root_database_objects_identity_and_file_changes(self):
        path=self.object(b'a');value=self.cache.gc_preview()
        self.assertEqual(value['objects'][0],gc.snapshot(path));self.assertFalse(value['automatic_cleanup'])
        self.assertEqual(len(value['cache_identity']),3)
        stamp=path.stat();path.write_bytes(b'b');os.utime(path,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        with self.assertRaises(ContractError):self.cache.gc_start(self.operation,value['plan_sha256'])
        self.assertEqual(path.read_bytes(),b'b');self.assertFalse(self.collector.path(self.operation,'.intent.json').exists())
    def test_start_records_attempt_and_result_for_each_object_and_never_replays(self):
        paths=[self.object(b'a'),self.object(b'b')];plan=self.cache.gc_preview()
        outcomes=self.cache.gc_start(self.operation,plan['plan_sha256'])
        self.assertEqual([row['state'] for row in outcomes],['removed','removed'])
        for path in paths:
            self.assertFalse(path.exists())
            self.assertTrue(self.collector.path(self.operation,'-'+path.name+'.attempt.json').is_file())
        status=self.cache.gc_status(self.operation);self.assertEqual(status['state'],'gc-finished')
        self.assertFalse(status['resumable']);self.assertFalse(status['cleanup_verified'])
        with self.assertRaises(ContractError):self.cache.gc_resume(self.operation,status['observation_sha256'])
    def test_intent_only_interruption_can_continue_after_fresh_explicit_observation(self):
        path=self.object(b'a');self.begin_interrupted('.intent.json',after=True)
        status=self.cache.gc_status(self.operation);self.assertTrue(status['resumable']);self.assertTrue(path.exists())
        result=self.cache.gc_resume(self.operation,status['observation_sha256'])
        self.assertEqual(result['state'],'gc-finished');self.assertFalse(path.exists())
        with self.assertRaises(ContractError):self.cache.gc_resume(self.operation,status['observation_sha256'])
    def test_unknown_attempt_with_existing_object_is_not_retried_but_untouched_can_continue(self):
        paths=[self.object(b'a'),self.object(b'b')];self.begin_interrupted('.attempt.json',after=True)
        status=self.cache.gc_status(self.operation)
        self.assertEqual([row['phase'] for row in status['objects']],['unknown','unattempted'])
        unknown=self.cache.root/'objects'/status['objects'][0]['sha256']
        self.assertTrue(status['resumable']);result=self.cache.gc_resume(self.operation,status['observation_sha256'])
        self.assertTrue(unknown.exists());self.assertEqual([r['phase'] for r in result['objects']],['unknown','removed'])
        self.assertFalse(result['resumable']);self.assertEqual(result['state'],'gc-observed')
    def test_lost_result_after_unlink_does_not_delete_recreated_same_sha(self):
        paths=[self.object(b'a'),self.object(b'b')];data={p.name:p.read_bytes() for p in paths}
        self.begin_interrupted('.result.json')
        status=self.cache.gc_status(self.operation);missing=status['objects'][0]
        self.assertEqual(missing['phase'],'unknown');self.assertIsNone(missing['current'])
        recreated=self.object(data[missing['sha256']]);fresh=self.cache.gc_status(self.operation)
        with self.assertRaises(ContractError):self.cache.gc_resume(self.operation,status['observation_sha256'])
        self.cache.gc_resume(self.operation,fresh['observation_sha256']);self.assertTrue(recreated.exists())
    def test_failed_unlink_receipt_is_preserved_without_retry(self):
        paths=[self.object(b'a'),self.object(b'b')];plan=self.cache.gc_preview();second=plan['objects'][1]['sha256']
        with patch.object(Path,'unlink',side_effect=PermissionError('夹具拒绝')),self.interrupted('-'+second+'.attempt.json'),self.assertRaises(Interrupted):
            self.cache.gc_start(self.operation,plan['plan_sha256'])
        status=self.cache.gc_status(self.operation);first=self.cache.root/'objects'/status['objects'][0]['sha256']
        self.assertEqual(status['objects'][0]['phase'],'preserved')
        self.cache.gc_resume(self.operation,status['observation_sha256']);self.assertTrue(first.exists())
    def test_added_reference_invalidates_start_and_continuation(self):
        path=self.object(b'a');plan=self.cache.gc_preview();self.cache.pin('new-course',path.name)
        with self.assertRaises(ContractError):self.cache.gc_start(self.operation,plan['plan_sha256'])
        self.cache.unpin('new-course',path.name);self.begin_interrupted('.intent.json',after=True)
        before=self.cache.gc_status(self.operation);self.cache.pin('new-course',path.name)
        with self.assertRaises(ContractError):self.cache.gc_resume(self.operation,before['observation_sha256'])
        after=self.cache.gc_status(self.operation);self.assertFalse(after['resumable'])
        with self.assertRaises(ContractError):self.cache.gc_resume(self.operation,after['observation_sha256'])
        self.assertTrue(path.exists())
    def test_changed_unattempted_object_rejects_whole_resume_before_deleting_any(self):
        paths=[self.object(b'a'),self.object(b'b')];self.begin_interrupted('.intent.json',after=True)
        status=self.cache.gc_status(self.operation);paths[1].write_bytes(b'changed')
        fresh=self.cache.gc_status(self.operation);self.assertFalse(fresh['resumable'])
        with self.assertRaises(ContractError):self.cache.gc_resume(self.operation,fresh['observation_sha256'])
        self.assertTrue(all(p.exists() for p in paths))
    def test_copied_job_cannot_be_rebound_to_another_cache(self):
        self.object(b'a');self.begin_interrupted('.intent.json',after=True)
        shutil.copytree(self.cache.root,self.root/'other');other=ContentCache(self.root/'other')
        with self.assertRaises(ContractError):other.gc_status(self.operation)
    def test_legacy_records_remain_read_only_without_guessing_attempt_boundary(self):
        path=self.object(b'a');gc.record(self.collector.path(self.operation,'.intent.json'),
            {'objects':self.cache.preview_gc(),'automatic_replay':False})
        status=self.cache.gc_status(self.operation);self.assertEqual(status['state'],'legacy-unresolved')
        with self.assertRaises(ContractError):self.cache.gc_resume(self.operation,status['observation_sha256'])
        self.assertTrue(path.exists())
    def test_database_exclusive_lock_blocks_new_reference_during_unlink(self):
        path=self.object(b'a');original=Path.unlink;calls=[]
        def unlink(value,*args,**kwargs):
            if value==path:
                with self.assertRaises(sqlite3.OperationalError):self.cache.pin('racing-owner',path.name)
                calls.append(value)
            return original(value,*args,**kwargs)
        with patch.object(Path,'unlink',unlink):self.cache.gc_start(self.operation,self.cache.gc_preview()['plan_sha256'])
        self.assertEqual(calls,[path])
    def test_malformed_attempt_receipt_refuses_observation_and_preserves_objects(self):
        path=self.object(b'a');self.begin_interrupted('.attempt.json',after=True)
        receipt=self.collector.path(self.operation,'-'+path.name+'.attempt.json')
        receipt.write_text('{"schema":2,"schema":2}')
        with self.assertRaises(ContractError):self.cache.gc_status(self.operation)
        self.assertTrue(path.exists())
    def test_wrong_receipt_scope_or_orphan_result_never_authorizes_deletion(self):
        path=self.object(b'a');plan=self.cache.gc_preview();item=plan['objects'][0]
        binding={'schema':2,'operation_id':self.operation,'plan_sha256':plan['plan_sha256'],
            'sha256':path.name,'object_sha256':gc.fingerprint(item),'state':'removed'}
        gc.record(self.collector.path(self.operation,'-'+path.name+'.result.json'),binding)
        with self.assertRaises(ContractError):self.cache.gc_start(self.operation,plan['plan_sha256'])
        self.assertTrue(path.exists())
    def test_unrelated_orphan_receipt_refuses_entire_new_job_before_any_delete(self):
        path=self.object(b'a');receipt=self.collector.path(self.operation,'-'+'f'*64+'.attempt.json')
        receipt.write_text('partial');receipt.chmod(0o600)
        with self.assertRaises(ContractError):self.cache.gc_start(self.operation,self.cache.gc_preview()['plan_sha256'])
        self.assertTrue(path.exists());self.assertEqual(receipt.read_text(),'partial')
        self.assertFalse(self.collector.path(self.operation,'.intent.json').exists())
    def test_symlink_hardlink_nonregular_and_object_limit_refused(self):
        path=self.object(b'a');other=self.cache.root/'objects'/('b'*64);os.link(path,other)
        with self.assertRaises(ContractError):self.cache.gc_preview()
        other.unlink();path.unlink();other.symlink_to(self.root/'outside')
        with self.assertRaises(ContractError):self.cache.gc_preview()
        other.unlink();path=self.object(b'a')
        with patch.object(gc,'MAX_OBJECTS',0),self.assertRaises(ContractError):self.cache.gc_preview()
        self.assertTrue(path.exists())
    def test_receipt_write_or_directory_sync_failure_preserves_unknown_without_replay(self):
        path=self.object(b'a');original=gc.sync_directory;calls=[]
        def sync(value):
            calls.append(value)
            if value.name=='objects':raise OSError('夹具目录落盘失败')
            return original(value)
        with patch.object(gc,'sync_directory',side_effect=sync),self.assertRaises(OSError):
            self.cache.gc_start(self.operation,self.cache.gc_preview()['plan_sha256'])
        status=self.cache.gc_status(self.operation);self.assertEqual(status['objects'][0]['phase'],'unknown')
        self.assertFalse(status['resumable']);self.assertIsNone(status['objects'][0]['current'])
    def test_operation_collision_and_job_bound_do_not_change_objects(self):
        path=self.object(b'a');self.begin_interrupted('.intent.json',after=True)
        before=self.collector.path(self.operation,'.intent.json').read_bytes()
        with self.assertRaises(FileExistsError):self.cache.gc_start(self.operation,self.cache.gc_preview()['plan_sha256'])
        self.assertEqual(self.collector.path(self.operation,'.intent.json').read_bytes(),before)
        with patch.object(gc,'MAX_JOBS',1),self.assertRaises(ContractError):
            self.cache.gc_start(str(uuid.uuid4()),self.cache.gc_preview()['plan_sha256'])
        self.assertTrue(path.exists())
    def test_isolated_cli_defaults_to_read_only_and_requires_both_explicit_approvals(self):
        path=self.object(b'a');script=Path(__file__).resolve().parents[1]/'ctflab_content_cache.py'
        def run(*args):return subprocess.run([sys.executable,'-I','-B',str(script),*args,'--root',str(self.cache.root)],capture_output=True,timeout=15)
        result=run('gc-preview');self.assertEqual(result.returncode,0,result.stderr)
        preview=json.loads(result.stdout)
        result=run('gc-start','--operation-id',self.operation,'--plan-sha256',preview['plan_sha256'])
        self.assertEqual(result.returncode,2);self.assertTrue(path.exists())
        result=run('gc-start','--operation-id',self.operation,'--execute','--plan-sha256','0'*64)
        self.assertEqual(result.returncode,2);self.assertTrue(path.exists())
        result=run('gc-start','--operation-id',self.operation,'--execute','--plan-sha256',preview['plan_sha256'])
        self.assertEqual(result.returncode,0,result.stderr);self.assertFalse(path.exists())
        status=run('gc-status','--operation-id',self.operation)
        self.assertEqual(status.returncode,0,status.stderr);self.assertEqual(json.loads(status.stdout)['state'],'gc-finished')
        self.assertEqual(run('storage','--execute').returncode,2)


if __name__=='__main__':unittest.main()
