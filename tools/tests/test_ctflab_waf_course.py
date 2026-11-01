"""C07真实自有回环HTTP对照；合成目录、临时SQLite、来宾身份替身，不连接真实VM。"""
from contextlib import ExitStack
import copy
import http.client
from http.client import HTTPMessage
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import Mock,patch
from urllib.parse import urlencode,quote

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
from ctflab_generation_store import digest
import ctflab_waf_course as waf


class CourseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve()
        self.machine=str(uuid.uuid4());sockets=[];self.ports={}
        try:
            for role in ('app','observe','block'):
                item=socket.socket();item.bind(('127.0.0.1',0));sockets.append(item);self.ports[role]=item.getsockname()[1]
        finally:
            for item in sockets:item.close()
        self.lab=self.root/'lab';waf.materials(Path(__file__).resolve().parents[2],self.lab,self.machine,1,ports=self.ports)
        self.courses={};self.servers={}
    def course(self,role):
        if role not in self.courses:self.courses[role]=waf.Course(self.lab/role,native=lambda:{'machine_uuid':self.machine})
        return self.courses[role]
    def start(self,role):
        server=waf.Server(self.course(role));thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01})
        thread.start();self.servers[role]=server
        def cleanup():server.shutdown();server.server_close();thread.join(3);self.assertFalse(thread.is_alive())
        self.addCleanup(cleanup);return server
    def request(self,role,target='/health',*,method='GET',headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.ports[role],timeout=3)
        try:
            connection.request(method,target,headers=headers or {});response=connection.getresponse();raw=response.read()
            return response.status,dict(response.getheaders()),json.loads(raw) if response.getheader('Content-Type','').startswith('application/json') else raw.decode()
        finally:connection.close()
    def search(self,role,value):return self.request(role,'/search?'+urlencode({'q':value}))
    def results(self,role):return [row for row in self.course(role).events()['events'] if row['phase']=='result']
    def test_real_http_observe_forwards_and_block_does_not_reach_application(self):
        for role in ('app','observe','block'):self.start(role)
        observed=self.search('observe','or 1=1');blocked=self.search('block','or 1=1')
        self.assertEqual(observed[0],200);self.assertEqual(blocked[0],403)
        app_ids={row['request_id'] for row in self.results('app')}
        self.assertIn(observed[1]['X-CTFLab-Request'],app_ids);self.assertNotIn(blocked[1]['X-CTFLab-Request'],app_ids)
        self.assertEqual(self.results('observe')[0]['decision'],'observed');self.assertFalse(self.results('block')[0]['forward_attempted'])
    def test_legitimate_catalog_search_passes_and_actual_false_positive_is_explainable(self):
        for role in ('app','observe','block'):self.start(role)
        self.assertEqual(self.search('observe','网络')[2]['items'][0]['category'],'network')
        self.assertEqual(self.search('block','网络')[0],200)
        legitimate='Select examples from SQL books'
        self.assertEqual(self.search('observe',legitimate)[2]['items'][0]['title'],legitimate)
        blocked=self.search('block',legitimate);self.assertEqual(blocked[0],403)
        self.assertEqual(blocked[2]['rules'][0]['rule_id'],'SQL-001')
    def test_html_and_path_signatures_are_matched_without_executing_input(self):
        for role in ('app','observe','block'):self.start(role)
        for value,rule in (('<script>demo','HTML-001'),('../demo','PATH-001')):
            observed=self.search('observe',value);blocked=self.search('block',value)
            self.assertEqual(observed[0],200);self.assertEqual(observed[2],{'items':[]});self.assertEqual(blocked[0],403)
            self.assertEqual(blocked[2]['rules'][0]['rule_id'],rule)
    def test_events_and_readonly_view_never_include_queries_headers_keys_or_teacher_answers(self):
        for role in ('app','observe'):self.start(role)
        self.search('observe','private-sentinel-query')
        self.request('observe','/search?q=x',headers={'Authorization':'Bearer private-auth','Cookie':'private-cookie'})
        status,headers,body=self.request('observe','/events');text=canonical(body)
        for secret in ('private-sentinel-query','private-auth','private-cookie',self.course('observe').key['key']):self.assertNotIn(secret,text)
        self.assertEqual(status,200);self.assertFalse(body['raw_query_recorded']);self.assertFalse(body['client_delivery_verified'])
        self.assertEqual(self.request('observe','/teacher/'+quote('部署与说明.md'))[0],404)
        page=self.request('observe','/')[2];self.assertIn('textContent',page);self.assertIn('处理情况',page)
        self.assertIn('查看原始结构化记录',page);self.assertNotIn('innerHTML',page);self.assertEqual(headers['Cache-Control'],'no-store')
    def test_upstream_timeout_preserves_pending_intent_without_retry(self):
        proxy=self.course('observe');connection=Mock();connection.getresponse.side_effect=TimeoutError('private-host-path')
        with patch.object(waf.http.client,'HTTPConnection',return_value=connection):
            result=proxy.search('/search?q=private-query',HTTPMessage())
        self.assertEqual(result[0],502);self.assertFalse(result[1]['automatic_replay']);self.assertEqual(connection.request.call_count,1)
        events=proxy.events();self.assertEqual(events['pending_count'],1);self.assertEqual(len(events['events']),1)
        self.assertNotIn('private-query',canonical(events));self.assertNotIn('private-host-path',canonical(events))
    def test_untrusted_app_response_is_not_accepted_or_replayed(self):
        proxy=self.course('observe');connection=Mock();response=connection.getresponse.return_value
        response.status=200;response.read.return_value=b'{"items":[]}';response.getheader.return_value=str(uuid.uuid4())
        with patch.object(waf.http.client,'HTTPConnection',return_value=connection):result=proxy.search('/search?q=x',HTTPMessage())
        self.assertEqual(result[0],502);self.assertEqual(connection.request.call_count,1);self.assertEqual(proxy.events()['pending_count'],1)
    def test_echoed_request_id_without_authenticated_response_cannot_forge_application_result(self):
        proxy=self.course('observe');connection=Mock();captured={}
        def request(method,target,headers):captured.update(headers)
        connection.request.side_effect=request;response=connection.getresponse.return_value
        response.status=200;response.read.return_value=b'{"items":[]}'
        response.getheader.side_effect=lambda name,default=None:captured['X-CTFLab-Request'] if name=='X-CTFLab-Request' else '0'*64
        with patch.object(waf.http.client,'HTTPConnection',return_value=connection):result=proxy.search('/search?q=x',HTTPMessage())
        self.assertEqual(result[0],502);self.assertEqual(proxy.events()['pending_count'],1)
        self.assertEqual(connection.request.call_count,1);self.assertEqual(self.results('observe'),[])
    def test_direct_application_access_and_replay_are_denied_without_reexecuting(self):
        self.start('app');status,_,_=self.search('app','网络');self.assertIn(status,(400,403,503))
        self.assertEqual(self.results('app'),[])
        course=self.course('app');identity=str(uuid.uuid4());target='/search?q=x'
        headers={'X-CTFLab-Request':identity,'X-CTFLab-Signature':waf.signature(course.secret,course.config,identity,target)}
        self.assertEqual(self.request('app',target,headers=headers)[0],200)
        self.assertEqual(self.request('app',target,headers=headers)[0],409);self.assertEqual(len(self.results('app')),1)
    def test_request_uuid_signature_is_bound_to_lab_generation_and_target(self):
        self.start('app');course=self.course('app');identity=str(uuid.uuid4())
        headers={'X-CTFLab-Request':identity,'X-CTFLab-Signature':waf.signature(course.secret,dict(course.config,generation=2),identity,'/search?q=x')}
        self.assertEqual(self.request('app','/search?q=x',headers=headers)[0],403)
        headers['X-CTFLab-Signature']=waf.signature(course.secret,course.config,identity,'/search?q=y')
        self.assertEqual(self.request('app','/search?q=x',headers=headers)[0],403);self.assertEqual(self.results('app'),[])
    def test_no_arbitrary_proxy_target_redirect_body_or_file_path(self):
        for role in ('app','observe'):self.start(role)
        self.assertEqual(self.request('observe','http://example.invalid/search?q=x')[0],404)
        self.assertEqual(self.request('observe','/search?q=x',method='POST')[0],405)
        self.assertEqual(self.request('observe','/search?q=x',method='CONNECT')[0],405)
        self.assertEqual(self.request('observe','/search?q=x',headers={'Transfer-Encoding':'chunked'})[0],400)
        self.assertEqual(self.results('app'),[])
        for target in ('/search?q=%ff','/search?q=%ZZ','/search?q=x&q=y','/search?q=%00','/search?q='+('x'*300)):
            with self.subTest(target=target),self.assertRaises((ValueError,RuntimeError,UnicodeError)):waf.query(target)
    def test_large_headers_fail_closed_and_threads_are_bounded(self):
        server=self.start('observe');connections=[]
        try:
            for _ in range(8):
                connection=socket.create_connection(('127.0.0.1',self.ports['observe']),timeout=2)
                connection.sendall(b'GET /health HTTP/1.0\r\nX-Wait: ');connections.append(connection)
            deadline=time.monotonic()+1
            while server.slots._value and time.monotonic()<deadline:time.sleep(.01)
            extra=socket.create_connection(('127.0.0.1',self.ports['observe']),timeout=1);extra.settimeout(1)
            try:
                extra.sendall(b'GET /health HTTP/1.0\r\n\r\n')
                try:self.assertEqual(extra.recv(1),b'')
                except ConnectionResetError:pass
            finally:extra.close()
        finally:
            for connection in connections:connection.close()
        deadline=time.monotonic()+1
        while server.slots._value!=8 and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(server.slots._value,8)
        with socket.create_connection(('127.0.0.1',self.ports['observe']),timeout=2) as connection:
            connection.sendall(b'GET /health HTTP/1.0\r\nX-Large: '+b'x'*17000+b'\r\n\r\n');connection.settimeout(2)
            try:
                data=connection.recv(4096);self.assertTrue(not data or b'431' in data)
            except ConnectionResetError:pass
        self.assertEqual(self.course('observe').events()['events_total'],0)
    def test_config_or_runtime_drift_refuses_before_new_business_effect(self):
        self.start('app');self.start('observe');self.search('observe','网络');before=len(self.results('app'))
        source=self.lab/'runtime'/'ctflab_waf_course.py';source.write_bytes(source.read_bytes()+b'\n# drift\n')
        self.assertEqual(self.search('observe','网络')[0],503)
        with self.assertRaises(ContractError):self.course('app').authorize()
        with sqlite3.connect(self.lab/'app'/'events.sqlite3') as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE phase='result'").fetchone()[0],before)
    def test_wrong_machine_source_host_or_config_generation_never_starts_server(self):
        with self.assertRaises(ContractError):waf.Course(self.lab/'app',native=lambda:{'machine_uuid':str(uuid.uuid4())})
        self.assertFalse((self.lab/'app'/'events.sqlite3').exists())
        with patch.object(waf,'Server') as server:self.assertEqual(waf.main(['serve','--run',str(self.lab/'app'),'--duration','1']),2)
        server.assert_not_called();self.assertFalse((self.lab/'app'/'events.sqlite3').exists())
        for change in ({'generation':True},{'ports':dict(self.ports,observe=self.ports['app'])},{'threshold':0}):
            config=copy.deepcopy(json.loads((self.lab/'app'/'config.json').read_text()));config.update(change)
            with self.assertRaises(ContractError):waf.settings(config)
    def test_existing_port_is_not_adopted_or_stopped(self):
        self.start('app')
        with self.assertRaises(OSError):waf.Server(self.course('app'))
        self.assertEqual(self.request('app')[0],200)
    def test_request_budget_reserves_result_and_denies_before_upstream(self):
        proxy=self.course('block')
        with patch.object(waf,'MAX_REQUESTS',1):
            self.assertEqual(proxy.search('/search?q=or+1%3D1',HTTPMessage())[0],403)
            with patch.object(waf.http.client,'HTTPConnection') as upstream,self.assertRaises(ContractError):proxy.search('/search?q=x',HTTPMessage())
            upstream.assert_not_called()
        self.assertEqual(len(proxy.events()['events']),2)
    def test_readonly_event_export_preserves_original_and_never_exports_keys_or_teacher(self):
        course=self.course('block');course.search('/search?q=or+1%3D1',HTTPMessage())
        before=digest(course.root/'events.sqlite3');destination=self.root/'export'
        result=course.export(destination);self.assertFalse(result['original_modified']);self.assertEqual(before,digest(course.root/'events.sqlite3'))
        manifest=json.loads((destination/'MANIFEST.json').read_text());self.assertEqual(manifest['files']['events.jsonl'],digest(destination/'events.jsonl'))
        self.assertEqual(set(p.name for p in destination.iterdir()),{'events.jsonl','MANIFEST.json'})
        self.assertNotIn(course.key['key'],(destination/'events.jsonl').read_text());self.assertFalse(manifest['externally_anchored'])
        with self.assertRaises(FileExistsError):course.export(destination)
        with self.assertRaises(ContractError):course.export(self.lab/'new-export')
    def test_pending_export_and_copied_database_identity_remain_explicit(self):
        course=self.course('observe');identity=str(uuid.uuid4());course.begin(identity)
        course.export(self.root/'pending-export');manifest=json.loads((self.root/'pending-export'/'MANIFEST.json').read_text())
        self.assertEqual(manifest['pending_count'],1);self.assertFalse(manifest['automatic_replay'])
        path=course.root/'events.sqlite3';raw=path.read_bytes();path.rename(course.root/'preserved.sqlite3');path.write_bytes(raw);path.chmod(0o600)
        with self.assertRaises(ContractError):course.events()
    def test_display_window_has_explicit_truncation_and_export_keeps_all_events(self):
        course=self.course('block')
        for _ in range(51):course.search('/search?q=or+1%3D1',HTTPMessage())
        events=course.events();self.assertEqual(len(events['events']),100);self.assertEqual(events['events_total'],102)
        self.assertTrue(events['events_truncated']);course.export(self.root/'all-export')
        self.assertEqual(len((self.root/'all-export'/'events.jsonl').read_text().splitlines()),102)
    def test_restart_cannot_mix_changed_runtime_or_generation_into_old_events(self):
        course=self.course('block');course.search('/search?q=or+1%3D1',HTTPMessage())
        path=self.lab/'runtime'/'ctflab_waf_course.py';path.write_bytes(path.read_bytes()+b'\n# changed runtime\n')
        manifest=self.lab/'runtime-manifest.json';value=json.loads(manifest.read_text())
        value['files'][path.name]=digest(path);manifest.write_text(canonical(value))
        with self.assertRaises(ContractError):waf.Course(self.lab/'block',native=lambda:{'machine_uuid':self.machine})
        with sqlite3.connect(course.root/'events.sqlite3') as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],2)
    def test_restarting_with_changed_private_key_or_generation_preserves_original_history(self):
        course=self.course('block');course.search('/search?q=or+1%3D1',HTTPMessage());before=digest(course.root/'events.sqlite3')
        path=course.root/'key.json';original=path.read_bytes();path.write_text(canonical({'key':'f'*64}))
        with self.assertRaises(ContractError):waf.Course(course.root,native=lambda:{'machine_uuid':self.machine})
        path.write_bytes(original);config=course.root/'config.json';value=json.loads(config.read_text());value['generation']=2
        config.write_text(canonical(value))
        with self.assertRaises(ContractError):waf.Course(course.root,native=lambda:{'machine_uuid':self.machine})
        self.assertEqual(before,digest(course.root/'events.sqlite3'))
    def test_readonly_display_preserves_database_bytes_and_invalid_materials_leave_no_output(self):
        course=self.course('block');course.search('/search?q=or+1%3D1',HTTPMessage());before=digest(course.root/'events.sqlite3')
        course.events();self.assertEqual(before,digest(course.root/'events.sqlite3'))
        with self.assertRaises(ContractError):waf.materials(Path(__file__).resolve().parents[2],self.root/'invalid',self.machine,1,ports={})
        self.assertFalse((self.root/'invalid').exists())
    def test_materials_are_explicit_new_source_only_and_student_teacher_are_separate(self):
        before=(self.lab/'MANIFEST.json').read_bytes()
        with self.assertRaises(FileExistsError):waf.materials(Path(__file__).resolve().parents[2],self.lab,self.machine,1)
        self.assertEqual(before,(self.lab/'MANIFEST.json').read_bytes())
        self.assertEqual([p.name for p in (self.lab/'student').iterdir()],['学生任务.md'])
        self.assertFalse(any(path.suffix in ('.exe','.dll','.qcow2','.zip') for path in self.lab.rglob('*')))
        self.assertNotIn('key.json',(self.lab/'student'/'学生任务.md').read_text())
    def test_actual_isolated_materials_cli_and_native_host_rejection(self):
        script=Path(__file__).resolve().parents[1]/'ctflab_waf_course.py';destination=self.root/'cli'
        result=subprocess.run([sys.executable,'-I','-B',str(script),'materials','--destination',str(destination),
            '--machine-uuid',self.machine,'--generation','1'],capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertFalse(json.loads(result.stdout)['services_started'])
        result=subprocess.run([sys.executable,'-I','-B',str(script),'serve','--run',str(destination/'app'),'--duration','1'],
            capture_output=True,timeout=15)
        self.assertEqual(result.returncode,2);self.assertFalse((destination/'app'/'events.sqlite3').exists())
        with self.assertRaises(ContractError):waf.Course(destination/'app',native=lambda:{'machine_uuid':self.machine},create=False)


if __name__=='__main__':unittest.main()
