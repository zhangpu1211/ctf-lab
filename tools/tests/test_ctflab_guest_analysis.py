"""隔离分析生产命令/状态/限额/证据绑定与失败保全；不执行分析器或解析PCAP。"""
import ast
import copy
import hashlib
import io
import json
import os
import signal
import subprocess
import tarfile
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
from ctflab_guest_policy import compile_policy,verify_policy
from ctflab_guest_agent import GuestAgent
from ctflab_guest_analysis import OfflineAnalysis,settings,image_materials,ANALYZER_WRAPPER,WRAPPER_SHA256,analysis_status,compare_results
import test_ctflab_guest_policy as policy_tests
import test_ctflab_guest_agent as agent_tests


def envelope(tool='zeek'):
    value=policy_tests.envelope(containers=True)
    value['analysis']={'tool':tool,'tool_version':'1.2.3','image':value['containers']['web']['image'],
        'input_sha256':hashlib.sha256(b'malformed-not-parsed-on-host').hexdigest(),
        'config_sha256':hashlib.sha256(b'locked-config').hexdigest() if tool=='suricata' else None,
        'timeout_seconds':1,'output_limit_mb':1}
    recompile(value);return value


def recompile(value):
    value['compiled']=compile_policy(value['plan'],value['node'],value['devices'],value['flows'],
        containers=value['containers'],container_cidr=value['container_cidr'],analysis=value['analysis'])


class AnalysisBackend(agent_tests.FakeBackend):
    def __init__(self):
        super().__init__();self.code=0;self.ready=True;self.bad_image=False;self.bad_status=False
        self.verify_failure=False;self.verify_wrong_hash=False;self.verify_bad_mount=False
        self.verify_duplicate=False;self.verify_exit=0;self.verify_corrupt_original=False;self.raw_export_path=None
        self.image_volumes=False
        self.content_missing=False
    def check_tool(self,tool):pass
    def json(self,tool,args):
        if args[:2]==['image','inspect']:
            return [{'RepoDigests':[args[2]],'Config':{'Volumes':{'/unexpected':{}} if self.image_volumes else None,'Labels':{'org.ctflab.analyzer.tool':'zeek',
                'org.ctflab.analyzer.version':'1.2.3','org.ctflab.analyzer.wrapper-sha256':'0'*64 if self.bad_image else WRAPPER_SHA256}}}]
        if args[:2]==['container','inspect']:return [copy.deepcopy(self.objects['container',args[2]])]
        return super().json(tool,args)
    def call(self,tool,args,**kw):
        self.calls.append((tool,*args))
        if args[:2]==['container','create']:
            get=lambda key:args[args.index(key)+1]
            labels=dict(args[i+1].split('=',1) for i,a in enumerate(args[:-1]) if a=='--label')
            mounts=[];tmpfs={}
            for i,a in enumerate(args[:-1]):
                if a=='--mount':
                    parts=args[i+1].split(',');m=dict(x.split('=',1) for x in parts if '=' in x)
                    mounts.append({'Type':m['type'],'Source':m['source'],'Destination':m['target'],'RW':'readonly' not in parts})
                if a=='--tmpfs':
                    key,text=args[i+1].split(':',1);tmpfs[key]=text
            verifier=labels.get('org.ctflab.role')=='archive-verifier';identity=('b' if verifier else 'a')*64
            if verifier and self.verify_bad_mount:mounts[0]['RW']=True
            image_at=args.index('--entrypoint')+2
            self.objects['container',identity]={'Id':identity,'Config':{'Labels':labels,'Image':args[image_at],'User':'1000:1000',
                'Entrypoint':['/usr/bin/python3'],'Cmd':args[image_at+1:],'Healthcheck':{'Test':['NONE']}},
                'HostConfig':{'NetworkMode':'none','ReadonlyRootfs':True,'Privileged':False,'CapDrop':['ALL'],
                    'SecurityOpt':['no-new-privileges'],'Memory':(128 if verifier else 512)*1024**2,'MemorySwap':(128 if verifier else 512)*1024**2,'NanoCpus':10**9,
                    'PidsLimit':16 if verifier else 64,'RestartPolicy':{'Name':'no'},'Tmpfs':tmpfs,
                    'LogConfig':{'Type':'local','Config':{'max-size':'1m','max-file':'1'}}},'Mounts':mounts,'State':{'Running':False,'ExitCode':0}}
            return identity+'\n'
        if args[:2]==['container','start']:
            obj=self.objects['container',args[-1]]
            if '--attach' in args:
                if self.verify_failure:raise OSError('fixture lost verifier acknowledgement')
                path=Path(obj['Mounts'][0]['Source']);raw=path.read_bytes()
                obj['State']['ExitCode']=self.verify_exit
                if self.verify_corrupt_original:self.raw_export_path.write_bytes(b'changed-original-fixture')
                value=canonical({'state':'archive-content-matches','status_sha256':obj['Config']['Cmd'][-1],
                    'archive_sha256':'0'*64 if self.verify_wrong_hash else hashlib.sha256(raw).hexdigest(),
                    'archive_bytes':len(raw),'output_content':{'sha256':'d'*64,'files':2,'bytes':20},'members':5,'extracted':False})
                return value[:-1]+',"extracted":false}' if self.verify_duplicate else value
            obj['State']['Running']=True;return ''
        if args[:2]==['container','exec']:
            if self.bad_status:return canonical({'state':'completed','returncode':0,'credential':'refuse'})
            return canonical({'state':'completed','returncode':self.code,'tool_version_observed':'1.2.3',
                'version_report_sha256':'b'*64,'output_content':None if self.content_missing else {'sha256':'d'*64,'files':2,'bytes':20}} if self.ready else {'state':'running'})
        if args[:2]==['container','kill']:self.objects['container',args[-1]]['State']['Running']=False;return ''
        raise AssertionError(args)


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        self.definition=envelope();self.backend=AnalysisBackend();self.agent=GuestAgent(self.root/'guest',self.definition,self.backend)
        directory=self.agent.root/'evidence';directory.mkdir()
        (directory/self.definition['analysis']['input_sha256']).write_bytes(b'malformed-not-parsed-on-host')
        self.outputs=[]
        def evidence(analyzer,sha):
            path=analyzer.agent.root/'evidence'/sha
            if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ContractError('identity-unknown')
            return path
        def export(backend,identity,path,limit):
            path.write_bytes(b'opaque-output-not-extracted'.ljust(10240,b'\0'));path.chmod(0o600);self.outputs.append(path)
            backend.raw_export_path=path
            return {'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
        self.evidence_patch=patch.object(OfflineAnalysis,'evidence',evidence);self.evidence_patch.start();self.addCleanup(self.evidence_patch.stop)
        self.export_patch=patch('ctflab_guest_analysis.export_archive',export)
        # 默认参数已在定义时绑定，显式替换构造器注入导出器与假时钟。
        self.ticks=0
        def clock():self.ticks+=1;return self.ticks
        original=OfflineAnalysis.__init__
        self.init_patch=patch.object(OfflineAnalysis,'__init__',lambda obj,agent:original(obj,agent,clock=clock,sleep=lambda _:None,export=export))
        self.init_patch.start();self.addCleanup(self.init_patch.stop)
    def action(self,operation=None):
        p=self.agent.policy
        return self.agent.dispatch({'schema':1,'instance_uuid':p['instance_uuid'],'generation':p['generation'],
            'policy_sha256':p['policy_sha256'],'operation_id':operation or str(uuid.uuid4()),'action':'analysis-run'})
    def test_malformed_input_only_goes_to_network_none_sandbox_and_archive_stays_opaque(self):
        result=self.action();self.assertEqual(result['state'],'analysis-completed');self.assertFalse(result['output_extracted'])
        self.assertFalse(result['byte_reproducibility_verified']);self.assertFalse(result['analysis_findings_verified'])
        commands=canonical(self.backend.calls)
        self.assertIn('--network=none',commands);self.assertIn('--cap-drop=ALL',commands);self.assertIn('--read-only',commands)
        self.assertIn('readonly',commands);self.assertIn('noexec,nosuid,nodev,size=1m',commands)
        self.assertNotIn('SIGKILL',commands);self.assertNotIn('pull',commands.replace('--pull=never',''))
        self.assertFalse(any('extract' in str(c) for c in self.backend.calls))
        self.assertEqual(self.outputs[0].read_bytes(),b'opaque-output-not-extracted'.ljust(10240,b'\0'))
        self.assertTrue(result['archive_content_consistent']);self.assertEqual(result['verifier_container_id'],'b'*64)
    def test_completed_same_operation_never_replays(self):
        operation=str(uuid.uuid4());one=self.action(operation);count=len(self.backend.calls)
        self.assertEqual(self.action(operation),one);self.assertEqual(len(self.backend.calls),count)
    def test_image_wrapper_mismatch_is_rejected_before_any_create(self):
        self.backend.bad_image=True;result=self.action();self.assertEqual(result['state'],'failed')
        self.assertFalse(any(c[:3]==('docker','container','create') for c in self.backend.calls))
    def test_tool_failure_is_recorded_with_opaque_evidence_not_business_success(self):
        self.backend.code=42;result=self.action();self.assertEqual(result['state'],'analysis-failed')
        self.assertEqual(result['returncode'],42);self.assertEqual(len(self.outputs),1)
    def test_timeout_keeps_unknown_no_stop_or_replay(self):
        self.backend.ready=False;operation=str(uuid.uuid4())
        with self.assertRaises(ContractError):self.action(operation)
        count=len(self.backend.calls);self.assertEqual(self.action(operation)['state'],'unknown')
        self.assertEqual(len(self.backend.calls),count)
        self.assertFalse(any(c[:3]==('docker','container','kill') for c in self.backend.calls))
    def test_status_extra_fields_do_not_become_success_and_input_drift_refuses(self):
        self.backend.bad_status=True
        with self.assertRaises(ContractError):self.action()
        self.assertEqual(self.outputs,[])
        fresh=GuestAgent(self.root/'fresh',self.definition,AnalysisBackend());job=OfflineAnalysis(fresh)
        with self.assertRaises(OSError):job.command(str(uuid.uuid4()))
    def test_settings_reject_arbitrary_command_image_root_mount_and_unbounded_budget(self):
        for change in ({'command':['sh']},{'image':'arbitrary:latest'},{'timeout_seconds':301},{'output_limit_mb':3},
                       {'tool':'shell'},{'tool_version':'latest'},{'config_sha256':'a'*64},{'timeout_seconds':True}):
            value=copy.deepcopy(self.definition);value['analysis'].update(change)
            with self.assertRaises(ContractError):recompile(value)
    def test_suricata_requires_locked_config_and_uses_fixed_paths(self):
        value=envelope('suricata');value['analysis']['config_sha256']=None
        with self.assertRaises(ContractError):recompile(value)
        value=envelope('suricata');self.agent.policy=value['compiled']
        (self.agent.root/'evidence'/value['analysis']['config_sha256']).write_bytes(b'locked-config')
        job=OfflineAnalysis(self.agent);operation=str(uuid.uuid4());job.prepare_inputs(operation);args=job.command(operation)
        self.assertEqual(args[-3:],['suricata','1','1.2.3']);self.assertIn('target=/config/suricata.yaml,readonly',canonical(args))
    def test_container_readable_copy_keeps_private_original_and_rejects_drift(self):
        original=self.agent.root/'evidence'/self.definition['analysis']['input_sha256'];original.chmod(0o600)
        before=original.stat();job=OfflineAnalysis(self.agent);operation=str(uuid.uuid4());job.prepare_inputs(operation)
        copied=job.input_copy(self.definition['analysis']['input_sha256'],operation)
        self.assertEqual(copied.stat().st_mode&0o777,0o444);self.assertEqual(copied.parent.stat().st_mode&0o777,0o700)
        self.assertNotEqual(copied.stat().st_ino,before.st_ino);self.assertEqual(copied.read_bytes(),original.read_bytes())
        self.assertEqual(original.stat().st_mode&0o777,0o600);self.assertEqual(original.stat().st_mtime_ns,before.st_mtime_ns)
        copied.chmod(0o600)
        with self.assertRaises(ContractError):job.command(operation)
        copied.chmod(0o444)
    def test_actual_wrapper_handles_sigterm_after_status_without_waiting_for_timeout(self):
        if os.name=='nt':self.skipTest('本机POSIX信号测试，Windows由原生验收覆盖')
        path=self.root/'status.json';wrapper=self.root/'wrapper.py'
        analyzer=self.root/'fake-analyzer';analyzer.write_text('#!'+sys.executable+'\nimport sys\nif sys.argv[1:]==["--version"]:print("zeek version 1.2.3")\n');analyzer.chmod(0o700)
        wrapper.write_text(ANALYZER_WRAPPER.replace('/output',str(self.root)).replace("'/usr/local/zeek/bin/zeek'",repr(str(analyzer))))
        process=subprocess.Popen([sys.executable,'-I','-B',str(wrapper),'zeek','10','1.2.3'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            import time
            deadline=time.monotonic()+3
            while not path.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(path.exists());self.assertIsNone(process.poll());process.send_signal(signal.SIGTERM)
            self.assertEqual(process.wait(timeout=2),0)
            self.assertEqual(json.loads(path.read_text())['returncode'],0)
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=2)
    def test_recipe_pins_base_wrapper_version_and_never_builds_or_overwrites(self):
        dest=self.root/'recipe';report=image_materials(dest,'example/base@sha256:'+'c'*64,'zeek','1.2.3')
        self.assertFalse(report['image_built']);ast.parse(ANALYZER_WRAPPER)
        self.assertIn(WRAPPER_SHA256,(dest/'Dockerfile').read_text())
        self.assertIn('FROM example/base@sha256:',(dest/'Dockerfile').read_text())
        with self.assertRaises(FileExistsError):image_materials(dest,'example/base@sha256:'+'c'*64,'zeek','1.2.3')
        with self.assertRaises(ContractError):image_materials(self.root/'bad','example/base:latest','zeek','1.2.3')
    def test_fixed_cli_help_imports_without_working_directory_or_pythonpath(self):
        result=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve().parents[1]/'ctflab_guest_analysis.py'),'--help'],
            cwd=self.root,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('image-materials',result.stdout)

    def test_completed_report_binds_scope_version_wrapper_and_observed_content(self):
        result=self.action()
        self.assertEqual(result['tool_version_observed'],'1.2.3');self.assertEqual(result['wrapper_sha256'],WRAPPER_SHA256)
        self.assertEqual(result['instance_uuid'],self.agent.policy['instance_uuid'])
        self.assertEqual(result['policy_sha256'],self.agent.policy['policy_sha256'])
        self.assertEqual(result['output_content'],{'sha256':'d'*64,'files':2,'bytes':20})

    def test_old_or_unverified_success_status_cannot_export_or_stop(self):
        for change in ({'tool_version_observed':None},{'version_report_sha256':None},{'output_content':None},
                       {'output_content':{'sha256':'d'*64,'files':True,'bytes':20}}, {'returncode':True}):
            status={'state':'completed','returncode':0,'tool_version_observed':'1.2.3',
                    'version_report_sha256':'b'*64,'output_content':{'sha256':'d'*64,'files':2,'bytes':20}}
            status.update(change)
            with self.assertRaises(ContractError):analysis_status(status,'1.2.3')
        with self.assertRaises(ContractError):analysis_status({'state':'completed','returncode':0},'1.2.3')

    def test_two_distinct_same_context_results_compare_without_parsing_archive(self):
        first=self.action();second=copy.deepcopy(first);second['operation_id']=str(uuid.uuid4())
        result=compare_results(first,second)
        self.assertTrue(result['same_output_content']);self.assertFalse(result['reports_authenticated'])
        self.assertFalse(result['byte_reproducibility_verified']);self.assertFalse(result['archives_extracted'])
        second['output_content']['sha256']='e'*64
        self.assertFalse(compare_results(first,second)['same_output_content'])

    def test_compare_refuses_same_operation_context_drift_and_unverified_version(self):
        first=self.action()
        with self.assertRaises(ContractError):compare_results(first,first)
        for changes in ({'input_sha256':'e'*64},{'image':'example/other@sha256:'+'a'*64},
                        {'instance_uuid':str(uuid.uuid4())},{'tool_version_observed':None},
                        {'state':'analysis-failed'},{'wrapper_sha256':'0'*64}):
            second=copy.deepcopy(first);second['operation_id']=str(uuid.uuid4());second.update(changes)
            with self.assertRaises(ContractError):compare_results(first,second)

    def test_isolated_compare_cli_checks_pinned_raw_reports_and_writes_nothing(self):
        first=self.action();second=copy.deepcopy(first);second['operation_id']=str(uuid.uuid4())
        paths=[self.root/'left.json',self.root/'right.json']
        for path,value in zip(paths,(first,second)):path.write_text(canonical(value))
        before={p:p.read_bytes() for p in paths}
        command=[sys.executable,'-I','-B',str(Path(__file__).resolve().parents[1]/'ctflab_guest_analysis.py'),'compare-results']
        for side,path in zip(('left','right'),paths):
            command+=['--'+side,str(path),'--'+side+'-sha256',hashlib.sha256(path.read_bytes()).hexdigest()]
        result=subprocess.run(command,capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(json.loads(result.stdout)['same_output_content'])
        paths[1].write_text(canonical(first))
        bad=subprocess.run(command,capture_output=True,timeout=15);self.assertEqual(bad.returncode,2)
        self.assertEqual(paths[0].read_bytes(),before[paths[0]])

    def test_pinned_metadata_rejects_duplicate_fields_and_non_json_constants(self):
        from ctflab_guest_analysis import pinned_result
        for raw in (b'{"state":1,"state":2}',b'{"state":NaN}'):
            path=self.root/'bad-result.json';path.write_bytes(raw)
            with self.assertRaises(ContractError):pinned_result(path,hashlib.sha256(raw).hexdigest())

    def test_verifier_is_separate_network_none_readonly_and_original_archive_keeps_private_mode(self):
        result=self.action();commands=[c for c in self.backend.calls if c[:3]==('docker','container','create')]
        self.assertEqual(len(commands),2)
        verification=self.backend.objects['container','b'*64]
        self.assertEqual(verification['HostConfig']['Memory'],128*1024**2)
        source=Path(verification['Mounts'][0]['Source'])
        self.assertEqual(source.stat().st_mode&0o777,0o444)
        self.assertEqual(self.outputs[0].stat().st_mode&0o777,0o600)
        self.assertEqual(source.read_bytes(),self.outputs[0].read_bytes())
        self.assertEqual(result['archive_verification']['archive_sha256'],result['archive_sha256'])

    def test_lost_verifier_reply_stays_unknown_does_not_stop_or_replay(self):
        self.backend.verify_failure=True;operation=str(uuid.uuid4())
        with self.assertRaises(OSError):self.action(operation)
        count=len(self.backend.calls);self.assertEqual(self.action(operation)['state'],'unknown')
        self.assertEqual(len(self.backend.calls),count);self.assertTrue(self.outputs[0].exists())
        self.assertFalse(any(c[:3]==('docker','container','kill') for c in self.backend.calls))

    def test_wrong_verifier_archive_hash_refuses_success_and_preserves_original(self):
        self.backend.verify_wrong_hash=True
        with self.assertRaises(ContractError):self.action()
        self.assertTrue(self.outputs[0].exists())
        self.assertFalse(any(c[:3]==('docker','container','kill') for c in self.backend.calls))

    def test_verifier_mount_drift_refuses_before_start(self):
        self.backend.verify_bad_mount=True
        with self.assertRaises(ContractError):self.action()
        self.assertFalse(any(c[:4]==('docker','container','start','--attach') for c in self.backend.calls))

    def test_duplicate_verifier_ack_and_nonzero_exit_cannot_commit_success(self):
        self.backend.verify_duplicate=True
        with self.assertRaises(ContractError):self.action()
        self.assertFalse(any(c[:3]==('docker','container','kill') for c in self.backend.calls))
        from ctflab_guest_analysis import decode_metadata
        with self.assertRaises(ContractError):decode_metadata(b'{}'+b' '*4095,4096)
        with self.assertRaises(ContractError):decode_metadata(b'{"value":NaN}',4096)

    def test_nonzero_verifier_exit_refuses_even_if_report_matches(self):
        self.backend.verify_exit=2
        with self.assertRaises(ContractError):self.action()
        self.assertFalse(any(c[:3]==('docker','container','kill') for c in self.backend.calls))

    def test_original_archive_drift_after_helper_is_preserved_and_refused(self):
        self.backend.verify_corrupt_original=True
        with self.assertRaises(ValueError):self.action()
        self.assertEqual(self.outputs[0].read_bytes(),b'changed-original-fixture')
        self.assertFalse(any(c[:3]==('docker','container','kill') for c in self.backend.calls))

    def test_implicit_image_volumes_refuse_before_create_and_healthchecks_are_disabled(self):
        self.backend.image_volumes=True;result=self.action();self.assertEqual(result['state'],'failed')
        self.assertFalse(any(c[:3]==('docker','container','create') for c in self.backend.calls))
        self.backend.image_volumes=False;self.action()
        for command in self.backend.calls:
            if command[:3]==('docker','container','create'):
                self.assertIn('--no-healthcheck',command)
                self.assertEqual(command[command.index('--entrypoint')+1],'/usr/bin/python3')

    def test_known_failed_output_without_manifest_keeps_opaque_archive_unverified(self):
        self.backend.code=127;self.backend.content_missing=True
        result=self.action();self.assertEqual(result['state'],'analysis-failed')
        self.assertFalse(result['archive_content_consistent']);self.assertIsNone(result['verifier_container_id'])
        self.assertIsNone(result['archive_verification']);self.assertTrue(self.outputs[0].is_file())
        self.assertEqual(len([c for c in self.backend.calls if c[:3]==('docker','container','create')]),1)


@unittest.skipIf(os.name=='nt','POSIX自有替身程序，不是原生Windows/Linux容器验收')
class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.counter=0

    def run_wrapper(self,*,tool='zeek',version=None,program="Path('conn.log').write_bytes(b'same-original-bytes')",timeout=10):
        self.counter+=1;work=self.root/str(self.counter);work.mkdir();output=work/'output';output.mkdir()
        analyzer=work/'analyzer';wrapper=work/'wrapper.py'
        if version is None:version='zeek version 1.2.3' if tool=='zeek' else 'This is Suricata version 1.2.3 RELEASE'
        analyzer.write_text('#!'+sys.executable+'\nimport sys,time\nfrom pathlib import Path\n'
            'if sys.argv[1:] in (["--version"],["-V"]):\n print('+repr(version)+')\n raise SystemExit(0)\n'
            +"Path('../analysis-started').write_text('yes')\n"+program+'\n')
        analyzer.chmod(0o700)
        wrapper.write_text(ANALYZER_WRAPPER.replace('/output',str(output))
            .replace('/usr/local/zeek/bin/zeek',str(analyzer)).replace('/usr/bin/suricata',str(analyzer)))
        process=subprocess.Popen([sys.executable,'-I','-B',str(wrapper),tool,str(timeout),'1.2.3'],
            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            import time
            deadline=time.monotonic()+timeout+5;status=output/'status.json';value=None
            while time.monotonic()<deadline and process.poll() is None:
                if status.exists():
                    try:value=json.loads(status.read_text());break
                    except json.JSONDecodeError:pass
                time.sleep(.01)
            self.assertIsNotNone(value,'自有wrapper未生成完整状态')
            process.send_signal(signal.SIGTERM);self.assertEqual(process.wait(timeout=3),0)
            analysis_status(value,'1.2.3')
            return value,output,work
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=3)
            process.stderr.close()

    def test_actual_fixed_version_probe_precedes_input_analysis_and_manifest_covers_all_bytes(self):
        status,out,work=self.run_wrapper()
        self.assertEqual(status['returncode'],0);self.assertEqual(status['tool_version_observed'],'1.2.3')
        self.assertTrue((work/'analysis-started').exists())
        manifest=json.loads((out/'output-manifest.json').read_text())
        self.assertEqual({x['name'] for x in manifest['files']},{'conn.log','tool.stderr','version.report'})
        for entry in manifest['files']:
            self.assertEqual(hashlib.sha256((out/entry['name']).read_bytes()).hexdigest(),entry['sha256'])
        self.assertEqual(status['output_content']['sha256'],hashlib.sha256(json.dumps(manifest['files'],sort_keys=True,separators=(',',':')).encode()).hexdigest())

    def test_actual_suricata_version_shape_and_fixed_V_flag(self):
        status,_,_=self.run_wrapper(tool='suricata');self.assertEqual(status['returncode'],0)

    def test_actual_wrong_version_never_runs_analysis(self):
        status,_,work=self.run_wrapper(version='zeek version 1.2.30')
        self.assertEqual(status['returncode'],126);self.assertIsNone(status['tool_version_observed'])
        self.assertFalse((work/'analysis-started').exists())

    def test_actual_version_output_over_limit_is_not_loaded_as_unbounded_text(self):
        status,_,work=self.run_wrapper(version='v'*4097)
        self.assertEqual(status['returncode'],126);self.assertFalse((work/'analysis-started').exists())

    def test_actual_malformed_multiline_version_cannot_hide_approved_prefix(self):
        status,_,work=self.run_wrapper(version='zeek version 1.2.3\nzeek version 9.9.9')
        self.assertEqual(status['returncode'],126);self.assertFalse((work/'analysis-started').exists())

    def test_actual_two_runs_ignore_filesystem_times_but_keep_log_content_differences(self):
        first,_,_=self.run_wrapper();same,_,_=self.run_wrapper()
        different,_,_=self.run_wrapper(program="Path('conn.log').write_bytes(b'log-timestamp-changed')")
        self.assertEqual(first['output_content'],same['output_content'])
        self.assertNotEqual(first['output_content']['sha256'],different['output_content']['sha256'])

    def test_actual_bad_output_symlink_cannot_read_outside_output(self):
        status,_,_=self.run_wrapper(program="Path('link.log').symlink_to('../analyzer')")
        self.assertEqual(status['returncode'],127);self.assertIsNone(status['output_content'])

    def test_actual_reserved_control_output_does_not_become_success(self):
        status,_,_=self.run_wrapper(program="Path('output-manifest.json').write_text('{}')")
        self.assertEqual(status['returncode'],127);self.assertIsNone(status['output_content'])

    def test_actual_output_file_count_is_bounded(self):
        status,_,_=self.run_wrapper(program="for i in range(513):Path(str(i)+'.log').touch()")
        self.assertEqual(status['returncode'],127);self.assertIsNone(status['output_content'])

    def test_actual_output_depth_is_bounded(self):
        status,_,_=self.run_wrapper(program="Path('/'.join(['deep']*10)).mkdir(parents=True)")
        self.assertEqual(status['returncode'],127);self.assertIsNone(status['output_content'])

    def test_actual_hard_linked_output_is_refused(self):
        status,_,_=self.run_wrapper(program="import os\nPath('one.log').write_bytes(b'data')\nos.link('one.log','two.log')")
        self.assertEqual(status['returncode'],127);self.assertIsNone(status['output_content'])

    def test_actual_oversized_output_is_not_reported_as_success(self):
        status,_,_=self.run_wrapper(program="Path('big.log').write_bytes(b'x'*(2*1024**2+1))")
        self.assertEqual(status['returncode'],127);self.assertIsNone(status['output_content'])

    def test_actual_timeout_does_not_expand_original_analysis_budget(self):
        status,_,_=self.run_wrapper(timeout=1,program='time.sleep(20)')
        self.assertEqual(status['returncode'],124)


@unittest.skipIf(os.name=='nt','自有POSIX替身与归档校验子进程，不是Docker/来宾验收')
class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        runner=WrapperTests();runner.root=self.root;runner.counter=0
        self.status,self.output,self.work=runner.run_wrapper()
        self.expected=hashlib.sha256(canonical(self.status).encode()).hexdigest()
        self.archive=self.root/'raw.tar';self.verifier=self.root/'verify.py'
        self.verifier.write_text(ANALYZER_WRAPPER.replace('/input/output.tar',str(self.archive)))

    def entries(self):return [(p.name,p.read_bytes()) for p in sorted(self.output.iterdir()) if p.is_file()]

    def make(self,entries=None,specials=()):
        # 只创建自有合成成员；宿主测试进程不读取或解包待校验tar。
        with tarfile.open(self.archive,'w',format=tarfile.PAX_FORMAT) as archive:
            root=tarfile.TarInfo('output');root.type=tarfile.DIRTYPE;archive.addfile(root)
            for name,data in self.entries() if entries is None else entries:
                member=tarfile.TarInfo('output/'+name);member.size=len(data);archive.addfile(member,io.BytesIO(data))
            for member,data in specials:archive.addfile(member,io.BytesIO(data))

    def verify(self,success):
        before=hashlib.sha256(self.archive.read_bytes()).hexdigest()
        result=subprocess.run([sys.executable,'-I','-B',str(self.verifier),'verify-archive',self.expected],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0 if success else 2,result.stderr)
        value=json.loads(result.stdout);self.assertFalse(value['extracted'])
        self.assertEqual(hashlib.sha256(self.archive.read_bytes()).hexdigest(),before)
        return value

    def test_fixed_archive_entrypoint_streams_tmpfs_style_directory_without_docker_cp(self):
        with self.archive.open('xb') as target:
            result=subprocess.run([sys.executable,'-I','-B',str(self.work/'wrapper.py'),'archive'],stdout=target,stderr=subprocess.PIPE,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        value=self.verify(True);self.assertEqual(value['output_content'],self.status['output_content'])
        self.assertEqual(value['archive_sha256'],hashlib.sha256(self.archive.read_bytes()).hexdigest())

    def test_valid_content_status_and_manifest_are_bound_without_extracting_files(self):
        self.make();before={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        value=self.verify(True);self.assertEqual(value['status_sha256'],self.expected)
        self.assertEqual(value['output_content'],self.status['output_content'])
        self.assertEqual(before,{str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_changed_log_bytes_are_refused(self):
        entries=dict(self.entries());entries['conn.log']=b'changed';self.make(list(entries.items()));self.verify(False)

    def test_changed_status_is_refused_even_with_self_consistent_manifest(self):
        entries=dict(self.entries());value=json.loads(entries['status.json']);value['returncode']=42
        entries['status.json']=canonical(value).encode();self.make(list(entries.items()));self.verify(False)

    def test_missing_or_extra_files_do_not_match_full_manifest(self):
        for remove in ('status.json','output-manifest.json','conn.log'):
            with self.subTest(remove=remove):self.make([(n,d) for n,d in self.entries() if n!=remove]);self.verify(False)
        self.make(self.entries()+[('extra.log',b'extra')]);self.verify(False)

    def test_forged_manifest_is_refused(self):
        entries=dict(self.entries());value=json.loads(entries['output-manifest.json']);value['files']=[]
        entries['output-manifest.json']=canonical(value).encode();self.make(list(entries.items()));self.verify(False)

    def test_duplicate_members_are_refused(self):
        self.make(self.entries()+[('conn.log',b'duplicate')]);self.verify(False)

    def test_symlink_hardlink_fifo_and_sparse_members_are_refused(self):
        for kind in (tarfile.SYMTYPE,tarfile.LNKTYPE,tarfile.FIFOTYPE,tarfile.GNUTYPE_SPARSE):
            with self.subTest(kind=kind):
                member=tarfile.TarInfo('output/unsafe');member.type=kind
                if kind in (tarfile.SYMTYPE,tarfile.LNKTYPE):member.linkname='../../outside'
                self.make(specials=[(member,b'')]);self.verify(False)
        self.assertFalse((self.root/'outside').exists())

    def test_absolute_traversal_and_ambiguous_path_members_are_refused(self):
        for name in ('/output/absolute','output/../outside','output//empty','output/./dot','other/file'):
            with self.subTest(name=name):
                member=tarfile.TarInfo(name);member.size=1;self.make(specials=[(member,b'x')]);self.verify(False)
        self.assertFalse((self.root/'outside').exists())

    def test_nonzero_trailer_or_concatenated_archive_is_refused(self):
        self.make();valid=self.archive.read_bytes()
        self.archive.write_bytes(valid+b'nonzero-tail');self.verify(False)
        self.archive.write_bytes(valid+valid);self.verify(False)

    def test_declared_giant_size_and_large_pax_are_refused_before_content_allocation(self):
        for kind,size in ((tarfile.REGTYPE,2**40),(tarfile.XHDTYPE,65537)):
            member=tarfile.TarInfo('output/oversize');member.type=kind;member.size=size
            self.archive.write_bytes(member.tobuf(format=tarfile.GNU_FORMAT)+b'\0'*1024);self.verify(False)

    def test_total_archive_size_is_bounded(self):
        self.archive.write_bytes(b'\0'*(4*1024**2+1));self.verify(False)

    def test_member_count_is_bounded(self):
        self.make([(str(i)+'.log',b'') for i in range(516)]);self.verify(False)

    def test_duplicate_json_control_fields_are_refused(self):
        entries=dict(self.entries());entries['status.json']=b'{"state":"completed","state":"running"}'
        self.make(list(entries.items()));self.verify(False)

    def test_export_client_uses_fixed_wrapper_archive_and_retains_over_limit_partial(self):
        from types import SimpleNamespace
        from ctflab_guest_analysis import export_archive
        original=subprocess.Popen;children=[];commands=[]
        def spawn(argv,**kw):
            commands.append(argv)
            child=original([sys.executable,'-I','-B','-c',"import sys;sys.stdout.buffer.write(b'owned-stream')"],**kw)
            children.append(child);return child
        backend=SimpleNamespace(guard=lambda:None,check_tool=lambda _:None,state=self.root)
        target=self.root/'stream.partial'
        with patch('ctflab_guest_analysis.subprocess.Popen',spawn):
            with self.assertRaises(ContractError):export_archive(backend,'a'*64,target,4)
            report=export_archive(backend,'a'*64,self.root/'success.partial',64)
        self.assertEqual(report['bytes'],len(b'owned-stream'));self.assertEqual(report['sha256'],hashlib.sha256(b'owned-stream').hexdigest())
        self.assertTrue(target.exists());self.assertTrue(all(p.poll() is not None for p in children))
        self.assertIn('exec',commands[0]);self.assertEqual(commands[0][-2:],['/usr/local/bin/ctflab-analyzer','archive'])
        self.assertIn('-I',commands[0]);self.assertIn('-B',commands[0])
        self.assertNotIn('cp',commands[0])


if __name__=='__main__':unittest.main()
