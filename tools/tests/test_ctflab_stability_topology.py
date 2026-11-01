"""只读查询和逐节点观测边界；真实临时账本/合成磁盘，不启动VM。"""
from datetime import datetime,timezone
from pathlib import Path
import sys
import unittest
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError
from ctflab_local_service import LocalService
from ctflab_local_adapter import process_actor
import ctflab_desktop_bridge as bridge
import test_ctflab_generation_store as generations
import test_ctflab_desktop_bridge as bridges
import test_ctflab_local_contract as contracts


class SamplingTests(unittest.TestCase):
    setUp=generations.GenerationTests.setUp
    context=generations.GenerationTests.context
    run_action=generations.GenerationTests.run_action
    def test_sampling_records_times_and_budget_exhaustion_does_not_invent_running(self):
        self.run_action('prepare',0)
        values=iter([0,0,20,20]);clock=lambda:next(values)
        result=self.backend.observation_snapshot(1,budget=1,monotonic=clock,utcnow=lambda:datetime(2026,10,28,tzinfo=timezone.utc))
        nodes=self.store.plan(1)['start_order'];self.assertEqual(result[nodes[0]]['identity'],'verified')
        self.assertEqual([result[n]['state'] for n in nodes[1:]],['unknown']*(len(nodes)-1))
        self.assertTrue(all(v['observed_at'].endswith('+00:00') for v in result.values()))
    def test_unverified_driver_response_stays_unknown_and_lifecycle_remains_strict(self):
        self.run_action('prepare',0);self.driver.identity='unknown'
        self.assertEqual({v['identity'] for v in self.backend.observation_snapshot(1).values()},{'unknown'})
        with self.assertRaises(ContractError):self.backend.observations(1)


class QueryTests(unittest.TestCase):
    setUp=contracts.ServiceTests.setUp
    tearDown=contracts.ServiceTests.tearDown
    def counts(self):
        with self.service._read() as db:return tuple(db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('operations','events','instances'))
    def test_absent_query_does_not_create_instance_or_intent(self):
        before=self.counts();result=self.service.query_request(self.prep,contracts.ACTOR)
        self.assertFalse(result['recorded']);self.assertEqual(self.counts(),before)
    def test_pending_and_completed_queries_do_not_dispatch_or_mutate_events(self):
        accepted=self.service.submit(self.prep,contracts.ACTOR);before=self.counts()
        value=self.service.query_request(self.prep,contracts.ACTOR);self.assertTrue(value['recorded'])
        self.assertEqual(value['response']['result'],'accepted');self.assertEqual(self.counts(),before)
        self.assertEqual(value['response']['operation_id'],accepted['operation_id'])
        self.service.execute(accepted['operation_id'],contracts.ACTOR,self.backend);before=self.counts()
        self.assertEqual(self.service.query_request(self.prep,contracts.ACTOR)['response']['state'],'prepared')
        self.assertEqual(self.counts(),before)
    def test_other_actor_and_same_key_changed_request_are_rejected(self):
        self.service.submit(self.prep,contracts.ACTOR)
        with self.assertRaises(ContractError):self.service.query_request(self.prep,'other-user')
        changed=dict(self.prep,parameters={'course_id':'other','baseline_id':'base'})
        with self.assertRaises(ContractError):self.service.query_request(changed,contracts.ACTOR)


class OverviewTests(unittest.TestCase):
    setUp=bridges.BridgeTests.setUp
    connect=bridges.BridgeTests.connect
    dispatch=bridges.BridgeTests.dispatch
    prepare=bridges.BridgeTests.prepare
    def test_overview_projects_verified_process_states_without_claiming_guest_addresses(self):
        self.connect();req,response=self.prepare()
        LocalService(self.root/'desktop-contract').execute(response['operation_id'],process_actor(),self.backend)
        view=self.dispatch({'action':'overview'})
        self.assertTrue(view['freshness']['complete']);self.assertFalse(view['freshness']['simultaneous'])
        self.assertEqual({v['state'] for v in view['topology']['nodes']},{'stopped'})
        self.assertTrue(all(nic['observed_address'] is None for n in view['topology']['nodes'] for nic in n['interfaces']))
        self.assertFalse(view['topology']['runtime_verified']);self.assertFalse(view['topology']['isolation_verified'])
    def test_querying_original_pending_before_dispatch_cannot_spawn_executor(self):
        self.connect();req,_=self.prepare();self.calls.clear()
        # 删除派发标记仅发生在自有临时夹具，模拟首次记录后尚未派发。
        for path in self.root.glob('desktop-dispatch-*.json'):path.unlink()
        value=self.dispatch({'action':'query-request','request':req})
        self.assertTrue(value['recorded']);self.assertEqual(self.calls,[])
        self.assertEqual(list(self.root.glob('desktop-dispatch-*.json')),[])


class CoherentOverviewTests(unittest.TestCase):
    setUp = bridges.BridgeTests.setUp
    connect = bridges.BridgeTests.connect
    dispatch = bridges.BridgeTests.dispatch
    prepare = bridges.BridgeTests.prepare

    def prepared(self):
        self.connect(); _, reply = self.prepare()
        service = LocalService(self.root/'desktop-contract')
        service.execute(reply['operation_id'], process_actor(), self.backend)
        return service

    def test_new_operation_during_sampling_invalidates_whole_view_without_replay(self):
        service = self.prepared(); original = self.backend.observation_snapshot
        status = service.status({'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),
            'operation':'status','instance_uuid':self.instance}, process_actor())
        def sample(generation):
            result = original(generation)
            req = {'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),
                'operation':'start','instance_uuid':self.instance,'expected_generation':1,
                'expected_state_revision':status['state_revision'],'idempotency_key':str(uuid.uuid4()),
                'parameters':{'display':'headless','allow_emulation':False}}
            service.submit(req, process_actor())
            return result
        self.backend.observation_snapshot = sample
        self.calls.clear(); view = self.dispatch({'action':'overview'})
        self.assertFalse(view['freshness']['complete']); self.assertFalse(view['freshness']['coherent'])
        self.assertEqual(view['freshness']['reason'],'changed-during-sampling')
        self.assertEqual({n['state'] for n in view['topology']['nodes']},{'unknown'})
        self.assertEqual({v['identity'] for v in view['observations'].values()},{'unknown'})
        self.assertIsNone(view['dispatch']); self.assertEqual(self.calls,[])

    def test_generation_pointer_change_during_sampling_clears_verified_nodes(self):
        self.prepared(); original = self.backend.observation_snapshot
        def sample(generation):
            result = original(generation)
            with self.store.db() as db:
                db.execute("UPDATE metadata SET value='2' WHERE key='active'")
            return result
        self.backend.observation_snapshot = sample
        view = self.dispatch({'action':'overview'})
        self.assertFalse(view['freshness']['coherent'])
        self.assertEqual({v['state'] for v in view['observations'].values()},{'unknown'})
        self.assertTrue(all(v['observer']=='unknown' for v in view['supervision'].values()))

    def test_malformed_cross_generation_cross_node_and_future_observations_stay_unknown(self):
        self.prepared(); original = self.backend.observation_snapshot
        for change in ({'generation':2},{'generation':True},{'node':'other'},
                       {'instance_uuid':str(uuid.uuid4())},{'observed_at':'2099-01-01T00:00:00+00:00'},
                       {'state':'service-ready'}, {'observed_at':None}):
            def sample(generation, change=change):
                result = original(generation)
                node = next(iter(result)); result[node] = dict(result[node], **change)
                return result
            self.backend.observation_snapshot = sample
            view = self.dispatch({'action':'overview'})
            self.assertFalse(view['freshness']['complete'],change)
            self.assertEqual(sum(v['identity']=='unknown' for v in view['observations'].values()),1,change)
            self.assertFalse(view['isolation_verified'])
        self.backend.observation_snapshot = lambda _: ['invalid']
        view = self.dispatch({'action':'overview'})
        self.assertFalse(view['freshness']['complete'])
        self.assertEqual({v['state'] for v in view['observations'].values()},{'unknown'})

    def test_late_metadata_change_also_invalidates_view(self):
        self.prepared()
        def changed(*args):
            with self.store.db() as db:
                db.execute("UPDATE metadata SET value='2' WHERE key='active'")
            return {'state':'verified'}
        self.driver.certificates = changed
        view = self.dispatch({'action':'overview'})
        self.assertFalse(view['freshness']['coherent'])
        self.assertTrue(all(item['state']=='unknown' for item in view['certificates'].values()))

    def test_diagnostics_does_not_share_mixed_generation_states(self):
        self.prepared(); original = self.backend.observation_snapshot
        def sample(generation):
            result = original(generation)
            with self.store.db() as db:
                db.execute("UPDATE metadata SET value='2' WHERE key='active'")
            return result
        self.backend.observation_snapshot = sample
        view = self.dispatch({'action':'diagnostics'})
        self.assertEqual({n['state'] for n in view['preview']['profiles']},{'unknown'})
        self.assertFalse(view['uploaded'])


class WatchHistoryBridgeTests(unittest.TestCase):
    setUp=bridges.BridgeTests.setUp
    connect=bridges.BridgeTests.connect
    dispatch=bridges.BridgeTests.dispatch
    def test_history_failure_does_not_discard_current_process_samples_or_dispatch(self):
        from unittest.mock import patch
        # 纯配置实例也能读历史；损坏历史只降低该历史区，不变成可恢复操作。
        self.connect()
        with patch('ctflab_watch.history',side_effect=ValueError('malformed record')):
            value=self.dispatch({'action':'overview'})
        self.assertEqual(self.calls,[])
        self.assertTrue(value['supervision_history']['unavailable'])
        self.assertTrue(value['supervision_history']['historical'])
        self.assertFalse(value['supervision_history']['automatic_replay'])
