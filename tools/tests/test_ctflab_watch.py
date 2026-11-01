"""只读监督范围、故障记录与日志边界；临时实例、假时钟/VM，不启动真实后台任务。"""
import json
from pathlib import Path
import sys
import threading
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_ctflab_generation_store as fixtures
from ctflab_contract import ContractError
from ctflab_generation_store import digest
from ctflab_windows_recovery import record
import ctflab_watch as module


class WatchTests(unittest.TestCase):
    setUp=fixtures.GenerationTests.setUp
    run_action=fixtures.GenerationTests.run_action
    context=fixtures.GenerationTests.context
    def setup_watch(self):
        self.run_action('prepare');record(self.store.root/'runtime-profile.json',{})
        self.now=0;self.operation=str(uuid.uuid4())
    def wait(self,seconds):self.now+=seconds;return False
    def watch(self,**kw):
        return module.run(self.store.root,self.operation,duration=10,interval=5,
            make_driver=lambda _:self.driver,clock=lambda:self.now,wait=kw.pop('wait',self.wait),**kw)
    def test_two_samples_do_not_start_stop_reset_or_modify_original(self):
        self.setup_watch();before=digest(self.base);result=self.watch()
        self.assertEqual(result['ticks'],2);self.assertEqual(self.driver.calls,[])
        self.assertEqual(digest(self.base),before);self.assertFalse(result['vm_control_sent'])
        current=json.loads((self.store.root/'watches'/self.operation/'current.json').read_text())
        self.assertEqual(current['scope_kind'],'process-samples-not-guest-or-course-health')
        self.assertEqual(len(current['nodes']),3)
    def test_unknown_or_wrong_protocol_is_not_reported_running(self):
        self.setup_watch()
        with patch.object(self.driver,'observe',return_value={'state':'running'}):self.watch()
        current=json.loads((self.store.root/'watches'/self.operation/'current.json').read_text())
        self.assertEqual({v['state'] for v in current['nodes']},{'unknown'})
        self.assertEqual(self.driver.calls,[])
    def test_scope_change_ends_watch_without_following_new_configuration(self):
        self.setup_watch()
        def changed(seconds):
            self.now+=seconds;(self.store.root/'runtime-profile.json').write_text('{"changed":true}');return False
        result=self.watch(wait=changed)
        self.assertEqual(result['state'],'watch-scope-changed');self.assertEqual(result['ticks'],1)
        self.assertEqual(self.driver.calls,[])
    def test_cancel_before_start_and_repeat_id_do_not_create_second_watch(self):
        self.setup_watch();stop=threading.Event();stop.set()
        with self.assertRaises(ContractError):self.watch(stop=stop)
        self.assertFalse((self.store.root/'watches').exists())
        self.watch()
        with self.assertRaises(FileExistsError):self.watch()
        self.assertEqual(len(list((self.store.root/'watches').iterdir())),1)
    def test_history_does_not_query_vm_or_create_missing_directory(self):
        self.setup_watch();self.assertEqual(module.history(self.store.root)['watches'],[])
        self.assertFalse((self.store.root/'watches').exists());self.watch()
        value=module.history(self.store.root);self.assertFalse(value['network_sent'])
        self.assertFalse(value['watches'][0]['live_process_rechecked'])
    def test_full_event_log_keeps_polling_with_bounded_output(self):
        self.setup_watch()
        def changed(seconds):
            self.now+=seconds;self.driver.states={(self.instance,1,n):'process-running' for n in self.manifest['nodes']};return False
        with patch.object(module,'EVENT_LIMIT',1024):result=self.watch(wait=changed)
        path=self.store.root/'watches'/self.operation/'events.jsonl'
        self.assertLessEqual(path.stat().st_size,1024);self.assertGreaterEqual(result['discarded_changes'],1)
        self.assertEqual(result['ticks'],2)

    def test_cancel_during_first_query_does_not_query_remaining_nodes(self):
        self.setup_watch();stop=threading.Event();original=self.driver.observe;calls=[]
        def observed(*args):
            calls.append(args[1]);value=original(*args);stop.set();return value
        with patch.object(self.driver,'observe',side_effect=observed):result=self.watch(stop=stop)
        self.assertEqual(len(calls),1);self.assertEqual(result['ticks'],0)
        self.assertTrue(result['cancel_requested']);self.assertEqual(self.driver.calls,[])

    def test_ledger_aba_commit_invalidates_one_sample_and_does_not_retry(self):
        self.setup_watch();original=self.driver.observe;called=[]
        def observed(*args):
            called.append(args[1]);value=original(*args)
            if len(called)==1:
                operation=str(uuid.uuid4());self.store.begin(operation,'start',1)
                self.store.finish(operation,{'state':'stopped'})
            return value
        with patch.object(self.driver,'observe',side_effect=observed):result=self.watch()
        events=[json.loads(row) for row in (self.store.root/'watches'/self.operation/'events.jsonl').read_text().splitlines()]
        self.assertFalse(events[0]['coherent']);self.assertEqual({v['state'] for v in events[0]['nodes']},{'unknown'})
        self.assertTrue(events[1]['coherent']);self.assertEqual(result['ticks'],2)
        self.assertEqual(len(called),6);self.assertEqual(self.driver.calls,[])

    def test_contract_aba_and_active_operation_are_unknown(self):
        import sqlite3
        from ctflab_generation_store import private_directory
        self.setup_watch();parent=self.store.root/'desktop-contract';private_directory(parent)
        path=parent/'contract.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE instances(active TEXT,revision INTEGER)');db.execute('INSERT INTO instances VALUES(NULL,0)')
        path.chmod(0o600);original=self.driver.observe;changed=[False]
        def observed(*args):
            value=original(*args)
            if not changed[0]:
                with sqlite3.connect(path) as db:db.execute('UPDATE instances SET revision=revision+1')
                changed[0]=True
            return value
        with patch.object(self.driver,'observe',side_effect=observed):self.watch()
        events=[json.loads(row) for row in (self.store.root/'watches'/self.operation/'events.jsonl').read_text().splitlines()]
        self.assertFalse(events[0]['coherent']);self.assertTrue(events[1]['coherent'])
        self.operation=str(uuid.uuid4())
        with sqlite3.connect(path) as db:db.execute("UPDATE instances SET active='pending'")
        self.watch();current=json.loads((self.store.root/'watches'/self.operation/'current.json').read_text())
        self.assertFalse(current['coherent']);self.assertEqual(current['reason'],'operation-in-progress')

    def test_completion_marks_samples_historical_and_scope_change_revokes_old_sample(self):
        self.setup_watch()
        def changed(seconds):
            self.now+=seconds;(self.store.root/'runtime-profile.json').write_text('{"change":1}');return False
        self.watch(wait=changed)
        current=json.loads((self.store.root/'watches'/self.operation/'current.json').read_text())
        self.assertTrue(current['historical']);self.assertFalse(current['watch_active'])
        self.assertFalse(current['complete']);self.assertFalse(current['coherent'])
        self.assertEqual({v['state'] for v in current['nodes']},{'unknown'})

    def test_contract_replacement_or_creation_does_not_follow_unbound_connection(self):
        import sqlite3
        from ctflab_generation_store import private_directory
        self.setup_watch();original=self.driver.observe;changed=[False]
        def observed(*args):
            value=original(*args)
            if not changed[0]:
                parent=self.store.root/'desktop-contract';private_directory(parent)
                path=parent/'contract.sqlite3'
                with sqlite3.connect(path) as db:
                    db.execute('CREATE TABLE instances(active TEXT)');db.execute('INSERT INTO instances VALUES(NULL)')
                path.chmod(0o600);changed[0]=True
            return value
        with patch.object(self.driver,'observe',side_effect=observed):result=self.watch()
        self.assertEqual(result['state'],'watch-observation-failed');self.assertEqual(result['ticks'],0)
        self.assertEqual(self.driver.calls,[])

    def test_scope_failure_revokes_previous_current_and_history_is_historical(self):
        self.setup_watch()
        def changed(seconds):
            self.now+=seconds;(self.store.root/'runtime-profile.json').write_bytes(b'not-json');return False
        # scope只绑定摘要；下一轮发现不同配置时撤回当前状态。
        self.watch(wait=changed)
        value=module.history(self.store.root)
        self.assertTrue(value['historical']);self.assertTrue(value['watches'][0]['historical'])
        self.assertFalse(value['watches'][0]['live_process_rechecked']);self.assertFalse(value['watches'][0]['coherent'])
        current=json.loads((self.store.root/'watches'/self.operation/'current.json').read_text())
        current['operation_id']=str(uuid.uuid4())
        (self.store.root/'watches'/self.operation/'current.json').write_text(json.dumps(current))
        with self.assertRaises(ContractError):module.history(self.store.root)

    def test_replaced_contract_file_ends_watch_instead_of_reading_old_database(self):
        import sqlite3
        from ctflab_generation_store import private_directory
        self.setup_watch();parent=self.store.root/'desktop-contract';private_directory(parent)
        path=parent/'contract.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE instances(active TEXT)');db.execute('INSERT INTO instances VALUES(NULL)')
        path.chmod(0o600);original=self.driver.observe;changed=[False]
        def observed(*args):
            value=original(*args)
            if not changed[0]:
                old=parent/'retained-contract.sqlite3';path.rename(old)
                with sqlite3.connect(path) as db:
                    db.execute('CREATE TABLE instances(active TEXT)');db.execute("INSERT INTO instances VALUES('operation')")
                path.chmod(0o600);changed[0]=True
            return value
        with patch.object(self.driver,'observe',side_effect=observed):result=self.watch()
        self.assertEqual(result['state'],'watch-observation-failed');self.assertEqual(result['ticks'],0)
        self.assertTrue((parent/'retained-contract.sqlite3').exists())


if __name__=='__main__':unittest.main()
