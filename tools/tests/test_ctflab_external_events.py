"""外部事件XML采集/固定SSH分块/私有保存；仅ctypes替身和临时文件，不读取宿主事件。"""
import base64
import copy
import ctypes as C
from html import escape
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ctflab_external_events as events
from ctflab_external import ExternalAgent, ExternalSession, save_events, settings
from ctflab_contract import ContractError, canonical
from ctflab_generation_store import digest


def policy():
    return {'channel': 'System', 'provider': 'Service Control Manager', 'event_ids': [7036],
            'after': '2026-10-29T00:00:00Z', 'before': '2026-10-29T01:00:00Z', 'max_records': 32}


def xml(record=1, *, at='2026-10-29T00:30:00.0000001Z', provider='Service Control Manager', channel='System', event=7036, data='测试事件'):
    return ('<Event xmlns="' + events.NS['e'] + '"><System><Provider Name="' + escape(provider, quote=True)
            + '"/><EventID>' + str(event) + '</EventID><TimeCreated SystemTime="' + at
            + '"/><EventRecordID>' + str(record) + '</EventRecordID><Channel>' + escape(channel)
            + '</Channel></System><EventData><Data>' + escape(data) + '</Data></EventData></Event>')


class FakeAPI:
    def __init__(self, rows=None):
        self.rows=[xml()] if rows is None else rows
        self.position=0;self.closed=[];self.last=0;self.calls=[];self.close_ok=True;self.next_error=None
    def error(self):return self.last
    def EvtQuery(self, session, channel, query, flags):
        self.calls.append((session,channel,query,flags));self.position=0;return 9000
    def EvtNext(self, query, size, handles, timeout, flags, count):
        if self.next_error is not None:self.last=self.next_error;return 0
        if self.position==len(self.rows):self.last=259;return 0
        handles[0]=100+self.position;self.position+=1
        C.cast(count,C.POINTER(events.U32))[0]=1;return 1
    def EvtRender(self, context, handle, flags, size, buffer, used, properties):
        data=(self.rows[handle-100]+'\0').encode('utf-16-le')
        C.cast(used,C.POINTER(events.U32))[0]=len(data)
        if not size:self.last=122;return 0
        C.memmove(buffer,data,len(data));return 1
    def EvtClose(self, handle):self.closed.append(handle);return self.close_ok


class CollectorTests(unittest.TestCase):
    def collect(self, rows=None, spec=None):
        api=FakeAPI(rows);collector=events.Collector(str(uuid.uuid4()),api=api)
        return collector.collect(spec or policy()),api
    def test_native_adapter_refuses_mac_and_injected_is_not_native(self):
        with patch.object(events.os,'name','posix'):
            with self.assertRaises(ContractError):events.API(str(uuid.uuid4()))
        self.assertFalse(events.Collector(str(uuid.uuid4()),api=FakeAPI()).is_native)
    def test_fixed_query_uses_channel_path_and_preserves_xml_with_no_writes(self):
        (data,count),api=self.collect();value=json.loads(data)
        self.assertEqual(count,1);self.assertEqual(value['records'][0]['xml'],xml())
        self.assertEqual(api.calls,[(None,'System',events.selection(policy()),0x101)])
        self.assertEqual(api.closed,[100,9000])
    def test_empty_result_is_complete_not_failed_query(self):
        (data,count),api=self.collect([]);self.assertEqual(count,0)
        self.assertEqual(json.loads(data)['records'],[]);self.assertEqual(api.closed,[9000])
    def test_time_comparison_keeps_seventh_fractional_digit(self):
        p=policy();p.update(after='2026-10-29T00:30:00.0000001Z',before='2026-10-29T00:30:00.0000002Z')
        events.parsed(xml(),p)
        for at in ('2026-10-29T00:30:00.0000000Z','2026-10-29T00:30:00.0000002Z'):
            with self.assertRaises(ContractError):events.parsed(xml(at=at),p)
    def test_policy_refuses_paths_xpath_overscopes_and_boolean_numbers(self):
        for key,bad in [('channel','C:\\logs\\a.evtx'),('channel','../System'),('provider',"x' or 1=1"),
                        ('event_ids',[True]),('event_ids',[1,2,3,4,5]),('max_records',33),
                        ('before','2026-10-31T00:00:00Z'),('after','2026-10-29T00:00:00+00:00')]:
            with self.subTest(key=key,bad=bad):
                p=policy();p[key]=bad
                with self.assertRaises((ContractError,ValueError)):events.policy(p)
    def test_xml_scope_mismatch_or_ambiguous_metadata_refuses(self):
        for raw in (xml(provider='other'),xml(channel='Application'),xml(event=1),xml(record=0),
                    xml().replace('</System>','<Channel>System</Channel></System>'),
                    '<!DOCTYPE Event [<!ENTITY secret "bad">]>'+xml(),xml().replace('测试事件','\0'),'<Event>'):
            with self.subTest(raw=raw[:80]):
                with self.assertRaises((ContractError,ValueError)):self.collect([raw])
    def test_over_limit_and_duplicate_records_close_all_handles_without_partial_result(self):
        for rows in ([xml(1),xml(2)],[xml(1),xml(1)]):
            api=FakeAPI(rows);p=policy();p['max_records']=1 if rows[1]==xml(2) else 32
            with self.assertRaises(ContractError):events.Collector(str(uuid.uuid4()),api=api).collect(p)
            self.assertEqual(api.closed,[100,101,9000])
    def test_size_limit_closes_without_truncated_xml(self):
        api=FakeAPI([xml(data='x'*events.MAX_XML)])
        with self.assertRaises(ContractError):events.Collector(str(uuid.uuid4()),api=api).collect(policy())
        self.assertEqual(api.closed,[100,9000])
    def test_timeout_access_denied_or_close_failure_is_not_empty_success(self):
        for error in (1460,5):
            api=FakeAPI();api.next_error=error
            with self.assertRaises(ContractError):events.Collector(str(uuid.uuid4()),api=api).collect(policy())
            self.assertEqual(api.closed,[9000])
        api=FakeAPI();api.close_ok=False
        with self.assertRaises(ContractError):events.Collector(str(uuid.uuid4()),api=api).collect(policy())
        self.assertEqual(api.closed,[100,9000])
    def test_total_snapshot_limit_and_unicode_provider(self):
        with self.assertRaises(ContractError):self.collect([xml(i,data='x'*20000) for i in range(1,17)])
        p=policy();p['provider']='课程 服务';self.collect([xml(provider=p['provider'])],p)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.config={'schema':1,'node_uuid':str(uuid.uuid4()),'machine_uuid':str(uuid.uuid4()),
            'cohort_uuid':str(uuid.uuid4()),'checkpoint_uuid':str(uuid.uuid4()),'generation':1,'kind':'windows',
            'principals':{'runner':['web','system-events'],'other':['web']},'services':{'web':{'port':80,'protocol':'tcp'}},
            'event_sources':{'system-events':policy()},'max_channels':2,'max_bytes':1024*1024,'expires':'2099-01-01T00:00:00Z'}
        self.api=FakeAPI([xml(1,data='x'*20000),xml(2)])
        self.machine={'machine_uuid':self.config['machine_uuid'],'system':'Windows','native_verified':True}
        self.collects=0
        def collector(machine):
            self.collects+=1;return events.Collector(machine,api=self.api)
        self.agent=ExternalAgent(self.config,'runner',observe=lambda:self.machine,events_factory=collector)
        self.addCleanup(self.agent.close)
        self.challenge=str(uuid.uuid4());self.agent.handle('ext-handshake',{'challenge':self.challenge})
        self.snapshot=str(uuid.uuid4())
    def params(self,**extra):
        return {k:self.config[k] for k in ('node_uuid','cohort_uuid','checkpoint_uuid','generation')}|dict(challenge=self.challenge,snapshot_id=self.snapshot,**extra)
    def capture(self):return self.agent.handle('ext-events-capture',self.params(source='system-events'))
    def session(self,mutate=None):
        outer=self
        class Transport:
            def __init__(self,config,**kw):self.failed=False
            def request(self,action,params):
                if action=='ext-handshake':outer.agent.challenge=None
                reply=outer.agent.handle(action,params)
                return mutate(action,reply) if mutate else reply
            def close(self,**kw):self.failed=kw.get('failed',False)
        expected={k:self.config[k] for k in ('node_uuid','machine_uuid','cohort_uuid','checkpoint_uuid','generation','kind')}
        expected['agent_sha256']=digest(Path(__file__).resolve().parents[1]/'ctflab_external.py')
        return ExternalSession({'server_uuid':self.config['node_uuid']},expected,factory=Transport)
    def test_capture_idempotency_returns_identical_immutable_bytes(self):
        first=self.capture();self.api.rows=[xml(9)]
        self.assertEqual(self.capture(),first);self.assertEqual(self.collects,1)
        reply=self.agent.handle('ext-events-read',self.params(offset=0,sha256=first['sha256']))
        self.assertFalse(reply['eof']);self.assertEqual(len(base64.b64decode(reply['data'])),16384)
        self.assertFalse(first['native_collection']);self.assertFalse(first['health_verified'])
    def test_wrong_source_no_permission_no_handshake_or_stale_scope_never_queries(self):
        self.agent.challenge=None
        with self.assertRaises(ContractError):self.capture()
        self.agent.challenge=self.challenge
        for extra in ({'source':'web'},{'source':'unknown'}):
            with self.assertRaises(ContractError):self.agent.handle('ext-events-capture',self.params(**extra))
        params=self.params(source='system-events');params['generation']=2
        with self.assertRaises(ContractError):self.agent.handle('ext-events-capture',params)
        self.assertEqual(self.collects,0)
    def test_other_principal_not_advertised_and_linux_config_refuses(self):
        a=ExternalAgent(self.config,'other',observe=lambda:self.machine)
        self.addCleanup(a.close)
        report=a.handle('ext-handshake',{'challenge':self.challenge})
        self.assertEqual(report['event_sources'],{});self.assertEqual(report['services'],['web'])
        with self.assertRaises(ContractError):a.handle('ext-events-capture',self.params(source='system-events'))
        c=copy.deepcopy(self.config);c['kind']='kali'
        with self.assertRaises(ContractError):settings(c)
    def test_capture_failure_reserved_id_survives_close_without_recollection(self):
        self.api.next_error=1460
        with self.assertRaises(ContractError):self.capture()
        self.api.next_error=None
        with self.assertRaises(ContractError):self.capture()
        self.assertEqual(self.collects,1)
    def test_only_four_attempts_and_aggregate_byte_budget(self):
        for _ in range(4):self.snapshot=str(uuid.uuid4());self.capture()
        self.snapshot=str(uuid.uuid4())
        with self.assertRaises(ContractError):self.capture()
        self.assertEqual(self.collects,4)
    def test_read_hash_offsets_generation_and_byte_budget_fail_closed(self):
        for extra in ({'sha256':'0'*64,'offset':0},{'sha256':None,'offset':1}):
            first=self.capture();extra['sha256']=extra['sha256'] or first['sha256']
            with self.assertRaises(ContractError):self.agent.handle('ext-events-read',self.params(**extra))
            self.snapshot=str(uuid.uuid4())
        first=self.capture();self.agent.event_bytes=self.config['max_bytes']
        with self.assertRaises(ContractError):self.agent.handle('ext-events-read',self.params(offset=0,sha256=first['sha256']))
    def test_roundtrip_validates_multichunk_xml_metadata_and_digest(self):
        with self.session() as session:report,data=session.collect_events('system-events')
        self.assertEqual(report['records'],2);self.assertEqual(json.loads(data)['records'][0]['xml'],xml(1,data='x'*20000))
        self.assertEqual(self.collects,1)
    def test_tampered_chunks_receipt_or_xml_close_client_without_retry(self):
        for field,bad in (('offset',True),('eof',True),('sha256','0'*64),('data',base64.b64encode(b'bad').decode())):
            self.agent.event_attempts.clear()
            def mutate(action,reply):
                if action=='ext-events-read':reply[field]=bad
                return reply
            session=self.session(mutate)
            with self.assertRaises((ContractError,ValueError)):session.collect_events('system-events')
            self.assertTrue(session.closed);self.assertTrue(session.session.failed)
    def test_old_peer_capability_refused_without_collection(self):
        def mutate(action,reply):
            if action=='ext-handshake':reply.pop('event_protocol')
            return reply
        with self.session(mutate) as session:
            with self.assertRaises(ContractError):session.collect_events('system-events')
        self.assertEqual(self.collects,0)
    def test_save_new_private_file_only_after_complete_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp).resolve()/'events.json'
            report=save_events({}, {}, 'system-events',target,factory=lambda *_:self.session())
            self.assertEqual(json.loads(target.read_bytes())['receipt'],report)
            if os.name!='nt':self.assertEqual(target.stat().st_mode&0o777,0o600)
            original=target.read_bytes()
            with self.assertRaises(ContractError):save_events({}, {}, 'system-events',target,factory=lambda *_:self.session())
            self.assertEqual(target.read_bytes(),original);self.assertEqual(self.collects,1)
    def test_failed_download_never_creates_file_and_public_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();target=root/'events.json'
            def mutate(action,reply):
                if action=='ext-events-read':reply['sha256']='0'*64
                return reply
            with self.assertRaises(ContractError):save_events({}, {}, 'system-events',target,factory=lambda *_:self.session(mutate))
            self.assertFalse(target.exists())
            if os.name!='nt':
                root.chmod(0o755)
                with self.assertRaises(ValueError):save_events({}, {}, 'system-events',target,factory=lambda *_:self.session())
                self.assertEqual(self.collects,1)
    def test_hardware_configuration_drift_and_source_name_collision_refuse(self):
        self.machine['machine_uuid']=str(uuid.uuid4())
        with self.assertRaises(ContractError):self.capture()
        self.assertEqual(self.collects,0)
        c=copy.deepcopy(self.config);c['event_sources']['web']=policy()
        with self.assertRaises(ContractError):settings(c)
    def test_cache_never_crosses_sessions_or_returns_after_close(self):
        report=self.capture();self.agent.close()
        with self.assertRaises(ContractError):self.agent.handle('ext-events-read',self.params(offset=0,sha256=report['sha256']))
        with self.assertRaises(ContractError):self.capture()
        self.assertEqual(self.collects,1)
    def test_client_rejects_receipt_extra_fields_before_reading_data(self):
        def mutate(action,reply):
            if action=='ext-events-capture':reply['unexpected']='不得输出额外正文'
            return reply
        session=self.session(mutate)
        with self.assertRaises(ContractError):session.collect_events('system-events')
        self.assertTrue(session.closed);self.assertEqual(self.agent.event_bytes,0)
    def test_identity_changes_during_collection_never_publishes_snapshot(self):
        original=self.agent.events_factory
        def factory(machine):
            collector=original(machine);collect=collector.collect
            def changed(spec):
                data=collect(spec);self.machine['machine_uuid']=str(uuid.uuid4());return data
            collector.collect=changed;return collector
        self.agent.events_factory=factory
        with self.assertRaises(ContractError):self.capture()
        self.assertEqual(self.agent.event_snapshots,{})
        self.assertIn(self.snapshot,self.agent.event_attempts)


if __name__=='__main__':unittest.main()
