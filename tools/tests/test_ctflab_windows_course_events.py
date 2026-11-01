"""Windows事件API真实ctypes指针替身：不加载DLL、写注册表或系统事件。"""
import copy
import ctypes as C
from html import escape
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
import ctflab_windows_course_events as events


def context():return {'lab_uuid':str(uuid.uuid4()),'machine_uuid':str(uuid.uuid4()),'generation':1}


def xml(row):
    return '<Event xmlns="'+events.NS['e']+'"><System><Provider Name="'+events.SOURCE+'"/><EventID>'+str(row['event_id'])+'</EventID><TimeCreated SystemTime="'+row.get('at','2026-10-29T00:00:00.0000000Z')+'"/><EventRecordID>'+str(row['id'])+'</EventRecordID></System><EventData>'+''.join('<Data>'+escape(item)+'</Data>' for item in row['strings'])+'</EventData></Event>'


class FakeAPI:
    def __init__(self):
        self.rows=[];self.queries={};self.counter=5000;self.closed=[];self.last=0;self.calls=[]
        self.fail_after_report=False;self.export_hook=None;self.close_ok=True;self.report_ok=True
    def error(self):return self.last
    def absent_source(self):self.calls.append(('registry-read-only',))
    def RegisterEventSourceW(self,server,source):self.calls.append(('register-handle',server,source));return 9000
    def ReportEventW(self,handle,kind,category,event,sid,count,size,strings,data):
        self.calls.append(('report',int(event),int(count)))
        if not self.report_ok:return 0
        self.rows.append({'id':len(self.rows)+1,'event_id':int(event),'strings':[strings[i] for i in range(count)]})
        if self.fail_after_report:raise OSError('替身已接收，回执未知')
        return 1
    def DeregisterEventSource(self,handle):self.calls.append(('deregister-handle',handle));return 1
    def EvtQuery(self,session,channel,query,flags):
        import re
        self.calls.append(('query',session,channel,query,flags));selected=list(self.rows)
        scope=re.search(r"Data='ctflab:c06:([0-9a-f-]+)'",query);generation=re.search(r"Data='generation:(\d+)'",query)
        if scope:selected=[row for row in selected if row['strings'][0]=='ctflab:c06:'+scope[1]]
        if generation:selected=[row for row in selected if row['strings'][1]=='generation:'+generation[1]]
        lower=re.search(r'EventRecordID>=(\d+)',query);upper=re.search(r'EventRecordID<=(\d+)',query)
        if lower:selected=[row for row in selected if int(lower[1])<=row['id']<=int(upper[1])]
        self.counter+=1;self.queries[self.counter]=selected;return self.counter
    def EvtNext(self,query,size,handles,timeout,flags,count):
        rows=self.queries[query];batch=rows[:size];del rows[:size]
        C.cast(count,C.POINTER(events.U32))[0]=len(batch)
        for index,row in enumerate(batch):handles[index]=1000+row['id']
        if not batch:self.last=259;return 0
        return 1
    def EvtRender(self,context,handle,flags,size,buffer,used,properties):
        row=next(row for row in self.rows if row['id']==handle-1000);raw=(xml(row)+'\0').encode('utf-16-le')
        C.cast(used,C.POINTER(events.U32))[0]=len(raw);C.cast(properties,C.POINTER(events.U32))[0]=0
        if not size:self.last=122;return 0
        if size<len(raw):self.last=122;return 0
        C.memmove(buffer,raw,len(raw));return 1
    def EvtClose(self,handle):self.closed.append(handle);return self.close_ok
    def EvtExportLog(self,session,channel,query,path,flags):
        self.calls.append(('export',session,channel,query,path,flags));target=Path(path)
        if target.exists():return 0
        target.write_bytes(b'ElfFile\0FAKE-EVTX-NOT-A-NATIVE-FILE')
        if self.export_hook:self.export_hook()
        return 1


class EventTests(unittest.TestCase):
    def setUp(self):self.scope=context();self.key='a'*64;self.api=FakeAPI();self.native=events.WindowsEvents(self.scope,self.key,api=self.api)
    def emit(self,action='incident'):operation=str(uuid.uuid4());self.native.report(action,operation,'b'*64);return operation
    def test_typed_report_uses_only_local_fixed_source_six_bounded_strings_and_always_releases(self):
        operation=self.emit();self.assertEqual(self.api.calls[0],('registry-read-only',))
        self.assertIn(('register-handle',None,events.SOURCE),self.api.calls);self.assertIn(('report',1001,6),self.api.calls)
        self.assertEqual(self.api.calls[-1],('deregister-handle',9000));self.assertEqual(self.native.records()[0]['operation_id'],operation)
        self.api.fail_after_report=True
        with self.assertRaises(OSError):self.emit('repair')
        self.assertEqual(self.api.calls[-1],('deregister-handle',9000));self.assertEqual(len(self.api.rows),2)
    def test_actual_utf16_buffers_and_handles_are_read_and_released_once(self):
        self.emit();self.emit('repair');rows=self.native.records();self.assertEqual([row['record_id'] for row in rows],[1,2])
        self.assertEqual(self.api.closed.count(1001),1);self.assertEqual(self.api.closed.count(1002),1)
        self.assertEqual(self.api.closed.count(5001),1);self.assertFalse(self.native.is_native)
    def test_wrong_scope_hmac_action_id_or_xml_entities_fail_closed(self):
        self.emit();raw=xml(self.api.rows[0]);self.assertEqual(events.parsed(raw,self.scope,self.key)['event_id'],1001)
        for value in (raw.replace('signature:','signature:0'),raw.replace('<EventID>1001','<EventID>1002'),
                      '<!DOCTYPE x [<!ENTITY t "test">]>'+raw,raw.replace('generation:1','generation:2')):
            with self.subTest(value=value[:60]),self.assertRaises((ValueError,RuntimeError)):events.parsed(value,self.scope,self.key)
        with self.assertRaises(ContractError):events.parsed(raw,dict(self.scope,lab_uuid=str(uuid.uuid4())),self.key)
    def test_export_is_no_overwrite_scoped_by_observed_record_range_and_future_records_excluded(self):
        self.emit();self.emit('repair')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();self.api.export_hook=lambda:self.emit('reset')
            result=self.native.collect(root);self.assertEqual(len(result['records']),2)
            self.assertEqual(len(self.api.rows),3);self.assertFalse(result['native_windows_api_executed'])
            query=next(call[3] for call in self.api.calls if call[0]=='export')
            self.assertIn('EventRecordID>=1',query);self.assertIn('EventRecordID<=2',query)
            with self.assertRaises(ContractError):self.native.collect(root)
            self.assertTrue((root/'application.evtx').exists())
    def test_export_detects_existing_record_drift_and_preserves_partial_file(self):
        self.emit()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();self.api.export_hook=lambda:self.api.rows[0].update(at='2026-10-29T00:00:01.0000000Z')
            with self.assertRaises(ContractError):self.native.collect(root)
            self.assertTrue((root/'application.evtx').exists())
    def test_empty_scope_does_not_export_or_claim_all_system_absence(self):
        with tempfile.TemporaryDirectory() as temp:result=self.native.collect(Path(temp).resolve())
        self.assertEqual(result['records'],[]);self.assertIsNone(result['evtx'])
        self.assertFalse(any(call[0]=='export' for call in self.api.calls));self.assertFalse(result['external_clock_verified'])
    def test_record_and_render_limits_release_owned_handles_without_retries(self):
        self.emit();self.emit('repair')
        with patch.object(events,'MAX_EVENTS',1),self.assertRaises(ContractError):self.native.records()
        self.assertEqual(self.api.closed.count(1001),1);self.assertEqual(self.api.closed.count(1002),1)
        self.api.closed.clear()
        with patch.object(events,'MAX_XML',16),self.assertRaises(ContractError):self.native.records()
        self.assertEqual(set(self.api.closed),{1001,1002,5002})
    def test_handle_close_failure_or_unknown_next_error_cannot_be_reported_complete(self):
        self.emit();self.api.close_ok=False
        with self.assertRaises(ContractError):self.native.records()
        self.api.close_ok=True
        original=self.api.EvtNext
        def failure(*args):self.api.last=5;return 0
        with patch.object(self.api,'EvtNext',side_effect=failure),self.assertRaises(ContractError):self.native.records()
    def test_native_host_rejected_before_loading_dll(self):
        with patch.object(events,'os',SimpleNamespace(name='posix')),patch.object(events.C,'WinDLL',create=True) as loader,self.assertRaises(ContractError):events.WindowsEvents(self.scope,self.key)
        loader.assert_not_called()
    def test_registered_source_is_never_adopted_and_registry_api_only_reads(self):
        import types
        calls=[]
        class Key:
            def __init__(self,name):self.name=name
            def __enter__(self):return self
            def __exit__(self,*args):pass
        module=types.SimpleNamespace(HKEY_LOCAL_MACHINE=1,KEY_READ=0x20019)
        def open_key(parent,name,reserved,mode):
            calls.append((name,mode))
            if name.endswith('\\'+events.SOURCE):raise FileNotFoundError()
            return Key(name)
        def enum(parent,index):
            if index==0:return 'Application'
            error=OSError();error.winerror=259;raise error
        module.OpenKey=open_key;module.EnumKey=enum
        with patch.dict(sys.modules,{'winreg':module}):events.absent_source()
        self.assertTrue(all(mode==module.KEY_READ for _,mode in calls))
        module.OpenKey=lambda parent,name,reserved,mode:Key(name)
        with patch.dict(sys.modules,{'winreg':module}),self.assertRaises(ContractError):events.absent_source()
    def test_fixed_system32_dll_bridge_has_correct_widths_and_checks_machine_before_loading(self):
        functions={}
        class Function:
            def __call__(self,*args):return 0
        class Library:
            def __getattr__(self,name):return functions.setdefault(name,Function())
        loader=Mock(side_effect=[Library(),Library()])
        with patch.object(events,'os',SimpleNamespace(name='nt')),patch('ctflab_external.native_machine',return_value={'machine_uuid':self.scope['machine_uuid']}),\
             patch.object(events.C,'WinDLL',create=True,side_effect=loader),patch.object(events.C,'get_last_error',create=True,return_value=0):
            bridge=events.API(self.scope['machine_uuid'])
        self.assertEqual([call.args[0] for call in loader.call_args_list],['wevtapi.dll','advapi32.dll'])
        self.assertTrue(all(call.kwargs['winmode']==0x800 and call.kwargs['use_last_error'] for call in loader.call_args_list))
        self.assertEqual(functions['ReportEventW'].argtypes,[events.PTR,events.U16,events.U16,events.U32,events.PTR,events.U16,events.U32,C.POINTER(C.c_wchar_p),events.PTR])
        self.assertEqual(functions['EvtRender'].restype,events.BOOL);self.assertEqual(C.sizeof(events.U32),4)
        with patch.object(events,'os',SimpleNamespace(name='nt')),patch('ctflab_external.native_machine',return_value={'machine_uuid':str(uuid.uuid4())}),\
             patch.object(events.C,'WinDLL',create=True) as rejected,self.assertRaises(ContractError):events.API(self.scope['machine_uuid'])
        rejected.assert_not_called()
    def test_invalid_xml_closes_all_owned_events_and_no_export_is_attempted(self):
        self.emit();self.emit('repair')
        with patch(__name__+'.xml',return_value='<bad'),self.assertRaises(ContractError):self.native.records()
        self.assertEqual(set(self.api.closed),{1001,1002,5001});self.assertFalse(any(call[0]=='export' for call in self.api.calls))
    def test_fixed_scope_and_selection_reject_injection_bool_generation_and_record_bounds(self):
        for value in (dict(self.scope,generation=True),dict(self.scope,lab_uuid="x' or true()")):
            with self.assertRaises(ContractError):events.selection(value)
        for lower,upper in ((0,1),(1,True),(2,1)):
            with self.assertRaises(ContractError):events.selection(self.scope,lower,upper)


if __name__=='__main__':unittest.main()
