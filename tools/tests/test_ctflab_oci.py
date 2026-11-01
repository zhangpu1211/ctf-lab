"""OCI字节/摘要/平台与受管代理装载，Docker全部为替身，镜像不执行。"""
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tarfile
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import canonical,ContractError
from ctflab_generation_store import digest,private_directory
from ctflab_oci import inspect_archive,convert,MANIFEST,CONFIG,LAYERS
import ctflab_oci as oci
from ctflab_guest_policy import compile_policy,verify_policy
from ctflab_guest_agent import GuestAgent,NativeBackend,serve
import test_ctflab_guest_agent as agent_tests
import test_ctflab_guest_policy as policy_tests


def packed(items,*,extra=None):
    target=io.BytesIO()
    with tarfile.open(fileobj=target,mode='w',format=tarfile.USTAR_FORMAT) as archive:
        for name,raw in items.items():
            info=tarfile.TarInfo(name);info.size=len(raw);archive.addfile(info,io.BytesIO(raw))
        if extra:
            info=tarfile.TarInfo(extra);info.type=tarfile.SYMTYPE;info.linkname='/outside';archive.addfile(info)
    return target.getvalue()


def fixture(path,*,compressed=True,architecture='amd64',wrong_diff=False,layer=None):
    layer=packed({'lesson.txt':b'synthetic fixture, never executed'}) if layer is None else layer
    diff=hashlib.sha256(layer).hexdigest()
    config=canonical({'architecture':architecture,'os':'linux','rootfs':{'type':'layers',
                    'diff_ids':['sha256:'+('0'*64 if wrong_diff else diff)]},
                    'config':{'User':'1000:1000','Cmd':['fixture-not-executed']}}).encode()
    blobs={}
    def desc(raw,media):
        sha=hashlib.sha256(raw).hexdigest();blobs['blobs/sha256/'+sha]=raw
        return {'mediaType':media,'digest':'sha256:'+sha,'size':len(raw)}
    config_desc=desc(config,CONFIG)
    layer_desc=desc(gzip.compress(layer,mtime=0) if compressed else layer,LAYERS[1] if compressed else LAYERS[0])
    manifest=canonical({'schemaVersion':2,'mediaType':MANIFEST,'config':config_desc,'layers':[layer_desc]}).encode()
    top=desc(manifest,MANIFEST);top['platform']={'architecture':architecture,'os':'linux'}
    items={'oci-layout':canonical({'imageLayoutVersion':'1.0.0'}).encode(),
           'index.json':canonical({'schemaVersion':2,'manifests':[top]}).encode(),**blobs}
    path.write_bytes(packed(items));path.chmod(0o600)
    return {'archive_sha256':digest(path),'manifest_sha256':top['digest'][7:],
            'config_sha256':config_desc['digest'][7:],'diff_id':'sha256:'+diff,
            'reference':'fixture/web@'+top['digest'],'items':items,'layer':layer}


class OCITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.path=self.root/'source.tar'

    def inspect(self,value):return inspect_archive(self.path,value['archive_sha256'],value['manifest_sha256'],'amd64')

    def test_gzip_and_raw_layers_convert_without_tags_or_source_mutation(self):
        for compressed in (True,False):
            value=fixture(self.path,compressed=compressed);before=digest(self.path)
            report=self.inspect(value);self.assertEqual(report['diff_ids'],[value['diff_id']])
            destination=self.root/str(compressed)
            result=convert(self.path,destination,before,value['manifest_sha256'],'amd64')
            self.assertFalse(result['runtime_verified']);self.assertEqual(digest(self.path),before)
            with tarfile.open(destination/'docker.tar') as archive:
                manifest=json.loads(archive.extractfile('manifest.json').read())
                self.assertEqual(manifest[0]['RepoTags'],[])
                self.assertEqual(archive.extractfile(manifest[0]['Layers'][0]).read(),value['layer'])
                config=archive.extractfile(manifest[0]['Config']).read()
                self.assertEqual(hashlib.sha256(config).hexdigest(),value['config_sha256'])
            with self.assertRaises(FileExistsError):convert(self.path,destination,before,value['manifest_sha256'],'amd64')

    def test_archive_manifest_and_uncompressed_diff_digests_are_independent(self):
        value=fixture(self.path)
        with self.assertRaises(ContractError):inspect_archive(self.path,'0'*64,value['manifest_sha256'],'amd64')
        with self.assertRaises(ContractError):inspect_archive(self.path,value['archive_sha256'],'0'*64,'amd64')
        value=fixture(self.path,wrong_diff=True)
        with self.assertRaises(ContractError):self.inspect(value)

    def test_wrong_architecture_and_multi_manifest_refused(self):
        value=fixture(self.path,architecture='arm64')
        with self.assertRaises(ContractError):self.inspect(value)
        value=fixture(self.path);index=json.loads(value['items']['index.json'])
        index['manifests']*=2;value['items']['index.json']=canonical(index).encode()
        self.path.write_bytes(packed(value['items']));value['archive_sha256']=digest(self.path)
        with self.assertRaises(ContractError):self.inspect(value)

    def test_missing_blob_corruption_and_foreign_urls_are_refused(self):
        value=fixture(self.path);blob=next(k for k in value['items'] if k.startswith('blobs/'))
        value['items'][blob]+=b'changed';self.path.write_bytes(packed(value['items']));value['archive_sha256']=digest(self.path)
        with self.assertRaises(ContractError):self.inspect(value)
        value=fixture(self.path);index=json.loads(value['items']['index.json'])
        index['manifests'][0]['urls']=['https://example.invalid/unapproved'];value['items']['index.json']=canonical(index).encode()
        self.path.write_bytes(packed(value['items']));value['archive_sha256']=digest(self.path)
        with self.assertRaises(ContractError):self.inspect(value)

    def test_outer_path_traversal_symlink_and_unreferenced_blobs_refused(self):
        for extra in ('../outside','blobs/sha256/'+'f'*64):
            value=fixture(self.path);self.path.write_bytes(packed(value['items'],extra=extra));value['archive_sha256']=digest(self.path)
            with self.assertRaises(ContractError):self.inspect(value)
        value=fixture(self.path);value['items']['blobs/sha256/'+'f'*64]=b'extra'
        self.path.write_bytes(packed(value['items']));value['archive_sha256']=digest(self.path)
        with self.assertRaises(ContractError):self.inspect(value)
        self.assertFalse((self.root/'outside').exists())

    def test_expansion_limit_and_non_ustar_metadata_refused(self):
        value=fixture(self.path)
        with patch.object(oci,'MAX_EXPANDED',1024):
            with self.assertRaises(ContractError):self.inspect(value)
        out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w',format=tarfile.PAX_FORMAT) as archive:
            item=tarfile.TarInfo('a'*130);archive.addfile(item)
        self.path.write_bytes(out.getvalue());value['archive_sha256']=digest(self.path)
        with self.assertRaises(ContractError):self.inspect(value)

    def test_digest_correct_but_invalid_layer_tar_or_traversal_is_refused(self):
        for layer in (b'not a tar',packed({'../outside':b'never extract'})):
            value=fixture(self.path,layer=layer)
            with self.assertRaises(ContractError):self.inspect(value)
        self.assertFalse((self.root/'outside').exists())

    def test_new_image_policy_is_opt_in_bound_and_rejects_unused_archives(self):
        value=fixture(self.path);definition=policy_tests.envelope(containers=True)
        old=copy.deepcopy(definition)
        self.assertNotIn('images',verify_policy(old))
        definition['containers']['web']['image']=value['reference'];definition['images']={value['reference']:value['archive_sha256']}
        definition['compiled']=compile_policy(definition['plan'],definition['node'],definition['devices'],definition['flows'],
            containers=definition['containers'],container_cidr=definition['container_cidr'],images=definition['images'])
        self.assertEqual(verify_policy(definition)['image_architecture'],'amd64')
        definition['images']['unused/web@sha256:'+'b'*64]='a'*64
        with self.assertRaises(ContractError):verify_policy(definition)


class ImageBackend(agent_tests.FakeBackend):
    def __init__(self,value):super().__init__();self.fixture=value;self.loaded=False
    def call(self,tool,args,**kwargs):
        if tool=='docker' and args[:2]==['image','load']:
            self.calls.append((tool,*args))
            if self.fail=='load':raise OSError('合成装载中断')
            if self.fail=='timeout':raise ContractError('control-unreachable')
            with tarfile.open(args[-1]) as archive:
                manifest=json.loads(archive.extractfile('manifest.json').read())
                raw=archive.extractfile(manifest[0]['Config']).read()
                assert hashlib.sha256(raw).hexdigest()==self.fixture['config_sha256']
            self.loaded=True;return 'Loaded image ID: sha256:'+self.fixture['config_sha256']
        return super().call(tool,args,**kwargs)
    def json(self,tool,args):
        if tool=='docker' and args[:2]==['image','inspect'] and args[2].startswith('sha256:'):
            self.calls.append((tool,*args))
            if not self.loaded:raise ContractError('identity-unknown')
            return [{'Id':'sha256:'+self.fixture['config_sha256'],'Os':'linux','Architecture':'amd64',
                     'RootFS':{'Type':'layers','Layers':[self.fixture['diff_id']]}}]
        return super().json(tool,args)


class OCIIntegrationTests(unittest.TestCase):
    setUp=OCITests.setUp
    def configured(self):
        self.value=fixture(self.path);self.definition=policy_tests.envelope(containers=True)
        self.definition['containers']['web']['image']=self.value['reference']
        self.definition['images']={self.value['reference']:self.value['archive_sha256']}
        e=self.definition;e['compiled']=compile_policy(e['plan'],e['node'],e['devices'],e['flows'],
                    containers=e['containers'],container_cidr=e['container_cidr'],images=e['images'])
        self.backend=ImageBackend(self.value);self.agent=GuestAgent(self.root/'guest',e,self.backend)
        private_directory(self.agent.root/'oci');self.staged=self.agent.root/'oci'/self.value['archive_sha256']
        self.staged.write_bytes(self.path.read_bytes());self.staged.chmod(0o600)
        self.run_action('network-apply')
    def request(self,action,operation=None):
        policy=self.agent.policy
        return {'schema':1,'instance_uuid':policy['instance_uuid'],'generation':policy['generation'],
                'policy_sha256':policy['policy_sha256'],'operation_id':operation or str(uuid.uuid4()),'action':action}
    def run_action(self,action):return self.agent.dispatch(self.request(action))

    def test_prepare_imports_locally_and_pins_config_id_without_pull_or_start(self):
        self.configured();before=digest(self.staged)
        self.assertEqual(self.run_action('containers-prepare')['state'],'containers-prepared')
        create=next(c for c in self.backend.calls if c[:3]==('docker','container','create'))
        self.assertEqual(create[-1],'sha256:'+self.value['config_sha256']);self.assertIn('--pull=never',create)
        self.assertFalse(any(c[:3]==('docker','container','start') for c in self.backend.calls))
        self.assertEqual(digest(self.staged),before)
        self.assertEqual(self.run_action('containers-start')['state'],'containers-running')
        self.assertEqual(self.run_action('containers-stop')['state'],'containers-stopped')

    def test_tampered_archive_fails_before_any_docker_load_or_resource_creation(self):
        self.configured();self.staged.write_bytes(b'bad OCI');self.backend.calls.clear()
        value=self.run_action('containers-prepare');self.assertEqual(value['state'],'failed');self.assertFalse(value['effects_started'])
        self.assertFalse(any(c[:3] in (('docker','image','load'),('docker','network','create')) for c in self.backend.calls))

    def test_interrupted_load_has_durable_intent_and_is_never_replayed(self):
        self.configured();self.backend.fail='load';request=self.request('containers-prepare')
        with self.assertRaises(OSError):self.agent.dispatch(request)
        count=len([c for c in self.backend.calls if c[:3]==('docker','image','load')])
        self.assertEqual(self.agent.dispatch(request)['state'],'unknown')
        self.assertEqual(len([c for c in self.backend.calls if c[:3]==('docker','image','load')]),count)
        with self.assertRaises(ContractError):self.run_action('containers-prepare')

    def test_changed_loaded_image_identity_prevents_container_start(self):
        self.configured();self.run_action('containers-prepare');self.backend.fixture=dict(self.value,config_sha256='b'*64)
        before=len(self.backend.calls);value=self.run_action('containers-start')
        self.assertEqual(value['state'],'failed')
        self.assertFalse(any(c[:3]==('docker','container','start') for c in self.backend.calls[before:]))

    def test_preparation_repair_does_not_replay_unknown_oci_load(self):
        self.configured();self.backend.fail='load';request=self.request('containers-prepare')
        with self.assertRaises(OSError):self.agent.dispatch(request)
        before=sum(c[:3]==('docker','image','load') for c in self.backend.calls)
        with self.assertRaises(ContractError):self.agent.inspect_preparation(request['operation_id'])
        self.assertEqual(sum(c[:3]==('docker','image','load') for c in self.backend.calls),before)
        self.assertFalse(self.agent.image_record(self.value['reference']).exists())

    def lost_load_reply(self):
        original=self.backend.call;request=self.request('containers-prepare')
        def failed(tool,args,**kwargs):
            result=original(tool,args,**kwargs)
            if tool=='docker' and args[:2]==['image','load']:raise OSError('合成已载入后丢回复')
            return result
        with patch.object(self.backend,'call',side_effect=failed):
            with self.assertRaises(OSError):self.agent.dispatch(request)
        return request['operation_id']

    def test_observed_loaded_image_can_finish_resources_without_replaying_load(self):
        self.configured();operation=self.lost_load_reply();before=digest(self.staged)
        count=sum(c[:3]==('docker','image','load') for c in self.backend.calls)
        snapshot=self.agent.inspect_preparation(operation)
        self.assertTrue(snapshot['can_resume']);self.assertEqual(snapshot['oci_effects']['oci-load-0'],'unknown')
        self.assertFalse(snapshot['images'][self.value['reference']]['present'])
        self.assertFalse(self.agent.image_record(self.value['reference']).exists())
        result=self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        self.assertTrue(result['oci_unknown_effects_preserved']);self.assertFalse(result['oci_load_replayed'])
        self.assertFalse(result['service_verified']);self.assertEqual(digest(self.staged),before)
        self.assertEqual(sum(c[:3]==('docker','image','load') for c in self.backend.calls),count)
        with self.agent.db() as db:
            self.assertIsNone(db.execute('SELECT result FROM effects WHERE operation=? AND step=?',(operation,'oci-load-0')).fetchone()[0])
        self.assertEqual(self.run_action('containers-start')['state'],'containers-running')

    def test_changed_loaded_layer_is_not_adopted_or_reloaded(self):
        self.configured();operation=self.lost_load_reply();self.backend.fixture=dict(self.value,diff_id='sha256:'+'c'*64)
        count=sum(c[:3]==('docker','image','load') for c in self.backend.calls)
        with self.assertRaises(ContractError):self.agent.inspect_preparation(operation)
        self.assertEqual(sum(c[:3]==('docker','image','load') for c in self.backend.calls),count)
        self.assertFalse(self.backend.objects)

    def test_record_write_interruption_requires_new_snapshot_and_never_loads_again(self):
        self.configured();operation=self.lost_load_reply();snapshot=self.agent.inspect_preparation(operation)
        original=self.agent.write_config
        def failed(name,text):original(name,text);raise OSError('合成写记录后中断')
        with patch.object(self.agent,'write_config',side_effect=failed):
            with self.assertRaises(OSError):self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        fresh=self.agent.inspect_preparation(operation)
        self.assertTrue(fresh['images'][self.value['reference']]['present'])
        with self.assertRaises(ContractError):self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        self.agent.resume_preparation(operation,fresh['resume_sha256'])
        self.assertEqual(sum(c[:3]==('docker','image','load') for c in self.backend.calls),1)

    def test_load_timeout_keeps_agent_readable_and_never_replays_daemon_mutation(self):
        native=NativeBackend.__new__(NativeBackend);native.state=self.root
        native.guard=lambda:None;native.check_tool=lambda _:None
        with patch('ctflab_guest_agent.subprocess.run',side_effect=subprocess.TimeoutExpired(['fixture-docker'],.1)):
            with self.assertRaises(ContractError) as error:native.call('docker',['image','load','--input','fixture'],timeout=.1)
        self.assertEqual(error.exception.code,'control-unreachable')
        self.configured();self.backend.fail='timeout';request=self.request('containers-prepare')
        source=io.BytesIO((canonical(request)+'\n'+canonical(dict(request,action='operation-status'))+'\n').encode())
        destination=io.BytesIO();self.assertEqual(serve(self.agent,source,destination),0)
        replies=[json.loads(line)['result'] for line in destination.getvalue().splitlines()]
        self.assertEqual([r['state'] for r in replies],['unknown','unknown'])
        self.assertIn({'step':'oci-load-0','state':'unknown'},replies[1]['effects'])
        self.assertEqual(len([c for c in self.backend.calls if c[:3]==('docker','image','load')]),1)


    def conversion_interrupted(self):
        import ctflab_oci
        original=ctflab_oci.convert;request=self.request('containers-prepare')
        def interrupted(*args):
            original(*args);raise OSError('合成转换完整写入后丢失记录')
        with patch('ctflab_oci.convert',side_effect=interrupted):
            with self.assertRaises(OSError):self.agent.dispatch(request)
        return request['operation_id']

    def test_never_started_load_can_resume_in_fresh_directory_preserving_unknown_conversion(self):
        self.configured();operation=self.conversion_interrupted()
        old=self.agent.root/'oci-work'/operation/'0'/'docker.tar';before=digest(old)
        snapshot=self.agent.inspect_preparation(operation)
        self.assertTrue(snapshot['can_resume'])
        self.assertEqual(snapshot['images'][self.value['reference']]['load_state'],'not-started')
        self.assertFalse(self.backend.loaded)
        result=self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        self.assertEqual(result['oci_loads_first_started'],1);self.assertFalse(result['oci_load_replayed'])
        self.assertEqual(digest(old),before);self.assertEqual(digest(self.staged),self.value['archive_sha256'])
        self.assertEqual(sum(c[:3]==('docker','image','load') for c in self.backend.calls),1)
        self.assertFalse(any(c[:3]==('docker','container','start') for c in self.backend.calls))
        with self.agent.db() as db:
            self.assertIsNone(db.execute('SELECT result FROM effects WHERE operation=? AND step=?',
                (operation,'oci-convert-0')).fetchone()[0])
        self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        self.assertEqual(sum(c[:3]==('docker','image','load') for c in self.backend.calls),1)

    def test_resume_conversion_failure_preserves_directory_and_requires_fresh_snapshot(self):
        self.configured();operation=self.conversion_interrupted();snapshot=self.agent.inspect_preparation(operation)
        with patch('ctflab_oci.convert',side_effect=OSError('合成本地转换失败')):
            with self.assertRaises(OSError):self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        old=self.agent.root/('oci-resume-'+operation+'-'+snapshot['resume_sha256']);self.assertTrue(old.is_dir())
        fresh=self.agent.inspect_preparation(operation)
        self.assertNotEqual(fresh['resume_sha256'],snapshot['resume_sha256'])
        with self.assertRaises(ContractError):self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        self.agent.resume_preparation(operation,fresh['resume_sha256']);self.assertTrue(old.is_dir())
        self.assertEqual(sum(c[:3]==('docker','image','load') for c in self.backend.calls),1)

    def test_first_load_failure_in_resume_stays_unknown_and_cannot_be_replayed(self):
        self.configured();operation=self.conversion_interrupted();snapshot=self.agent.inspect_preparation(operation)
        self.backend.fail='load'
        with self.assertRaises(OSError):self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        with self.assertRaises(ContractError):self.agent.inspect_preparation(operation)
        self.assertEqual(sum(c[:3]==('docker','image','load') for c in self.backend.calls),1)
        self.assertFalse(self.backend.objects)

    def test_changed_staged_archive_blocks_pending_import_without_daemon_mutation(self):
        self.configured();operation=self.conversion_interrupted();snapshot=self.agent.inspect_preparation(operation)
        self.staged.write_bytes(b'changed')
        with self.assertRaises(ContractError):self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        self.assertEqual(sum(c[:3]==('docker','image','load') for c in self.backend.calls),0)

    def test_recovery_directory_limit_preserves_all_old_attempts_and_refuses_load(self):
        self.configured();operation=self.conversion_interrupted();snapshot=self.agent.inspect_preparation(operation)
        for index in range(16):private_directory(self.agent.root/('oci-resume-'+operation+'-'+str(index)))
        with self.assertRaises(ContractError):self.agent.resume_preparation(operation,snapshot['resume_sha256'])
        self.assertEqual(len(list(self.agent.root.glob('oci-resume-'+operation+'-*'))),16)
        self.assertEqual(sum(c[:3]==('docker','image','load') for c in self.backend.calls),0)


if __name__=='__main__':unittest.main()
