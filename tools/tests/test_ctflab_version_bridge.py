"""固定版本桥接与Mac只读/独立管理入口/摘要绑定；临时版本库，不启动真实应用或VM。"""
import json
from pathlib import Path
import sys
import unittest
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
from ctflab_generation_store import digest
from ctflab_version_bridge import VersionBridge
import test_ctflab_release_store as fixtures


class VersionTests(unittest.TestCase):
    setUp=fixtures.ReleaseTests.setUp
    envelope=fixtures.ReleaseTests.envelope
    stage=fixtures.ReleaseTests.stage
    def configure(self,system='Linux',caller=True):
        self.keys_path=self.root/'trusted-keys.json';self.keys_path.write_text(canonical(self.keys));self.keys_path.chmod(0o600)
        self.config=self.root/'version-config.json';self.config.write_text(canonical({'schema':1,'release_root':str(self.store.root),'trusted_keys':str(self.keys_path)}));self.config.chmod(0o600)
        self.spawned=[]
        self.bridge=VersionBridge(self.config,system=lambda:system,caller=lambda _:caller,spawn=lambda args:self.spawned.append(args))
    def request(self,action,**fields):return self.bridge.handle(dict(action=action,target=self.bridge.target,**fields))
    def test_mac_reads_existing_library_but_refuses_all_new_mutation_paths(self):
        self.configure('Darwin');status=self.bridge.handle({'action':'status'})
        self.assertTrue(status['read_only']);self.assertTrue(status['original_mac_updater_preserved'])
        with self.assertRaises(ContractError):self.request('initialize')
        self.assertEqual(self.store.status()['versions'],[]);self.assertEqual(self.spawned,[])
    def test_versioned_caller_cannot_switch_itself_and_unknown_identity_is_readonly(self):
        self.configure(caller=False);status=self.bridge.handle({'action':'status'})
        self.assertTrue(status['read_only']);self.assertTrue(status['requires_stable_manager'])
        with self.assertRaises(ContractError):self.request('initialize')
    def test_stage_preview_and_same_operation_switch_use_library_and_version_targets_separately(self):
        self.configure();manifest=self.root/'signed.json';manifest.write_text(canonical(self.envelope()));manifest.chmod(0o600)
        result=self.request('stage',source=str(self.source),manifest=str(manifest))
        self.assertEqual(result['version'],'0.1.0');self.assertEqual(result['library_target'],self.bridge.target)
        preview=self.request('update-preview',version='0.1.0')
        self.assertEqual(preview['target'],'0.1.0');self.assertEqual(preview['library_target'],self.bridge.target)
        operation=str(uuid.uuid4());first=self.request('update-apply',version='0.1.0',operation_id=operation,plan_sha256=preview['plan_sha256'])
        again=self.request('update-apply',version='0.1.0',operation_id=operation,plan_sha256=preview['plan_sha256'])
        self.assertEqual(first['state'],'committed');self.assertEqual(again['state'],'committed')
        self.assertEqual(self.store.status()['active'],'0.1.0');self.assertEqual(self.spawned,[])
    def test_config_trust_or_explicit_target_drift_refuses_without_staging(self):
        self.configure()
        with self.assertRaises(ContractError):self.bridge.handle({'action':'initialize','target':'0'*64})
        self.keys_path.write_text(self.keys_path.read_text()+' ')
        with self.assertRaises(ContractError):self.request('initialize')
        self.assertEqual(self.store.status()['versions'],[])
    def test_unknown_fields_arbitrary_command_and_untrusted_key_inside_library_are_rejected(self):
        self.configure()
        for value in ({'action':'shell','target':self.bridge.target,'command':'anything'},
            {'action':'status','root':'/other'},{'action':'initialize','target':self.bridge.target,'command':'anything'}):
            with self.assertRaises(ContractError):self.bridge.handle(value)
        keys=self.store.root/'keys.json';keys.write_text(canonical(self.keys));keys.chmod(0o600)
        self.config.write_text(canonical({'schema':1,'release_root':str(self.store.root),'trusted_keys':str(keys)}))
        with self.assertRaises(ContractError):VersionBridge(self.config)
    def test_launch_requires_rechecked_plan_and_only_requests_fixed_worker(self):
        self.configure();self.stage();self.store.activate('0.1.0')
        class Launcher:
            def preview(inner):return {'plan_sha256':'a'*64}
            def history(inner):return {'launches':[]}
        self.bridge.launcher=Launcher()
        with self.assertRaises(ContractError):self.request('launch',plan_sha256='b'*64)
        result=self.request('launch',plan_sha256='a'*64)
        self.assertFalse(result['application_running_verified']);self.assertFalse(result['vm_stopped'])
        self.assertEqual(len(self.spawned),1);args=self.spawned[0]
        self.assertEqual(Path(args[3]).name,'ctflab_version_bridge.py');self.assertIn('launch-worker',args)
        self.assertEqual(args[args.index('--target')+1],self.bridge.target)

    def test_default_launch_path_uses_real_bounded_receiver(self):
        import subprocess,time
        from unittest.mock import patch
        self.configure();self.bridge.spawn=None;processes=[];original=subprocess.Popen
        def popen(args,**kwargs):
            if any(str(arg).endswith('ctflab_version_bridge.py') for arg in args):
                args=[sys.executable,'-I','-B','-c','print("owned-version-launch-fixture")']
            child=original(args,**kwargs);processes.append(child);return child
        try:
            with patch('ctflab_version_bridge.subprocess.Popen',side_effect=popen):
                value=self.bridge.launch('a'*64)
            self.assertFalse(value['application_running_verified'])
            for child in reversed(processes):self.assertEqual(child.wait(timeout=15),0)
            logs=list(self.store.root.glob('launcher-log-*'));self.assertEqual(len(logs),1)
            status=json.loads((logs[0]/'version-launch.log-status.json').read_text())
            self.assertTrue(status['complete']);self.assertIn('owned-version-launch-fixture',(logs[0]/'version-launch.log').read_text())
        finally:
            for child in processes:
                if child.stdin is not None and not child.stdin.closed:child.stdin.close()
                if child.poll() is None:child.wait(timeout=15)

    def test_online_bridge_requires_target_and_only_fills_explicit_stage_materials(self):
        import hashlib
        from ctflab_release_online import OnlineRelease
        from test_ctflab_release_online import Response
        self.configure('Windows');location='https://updates.example.invalid/stable/';calls=[]
        data={'ctflab-desktop.exe':b'synthetic-not-executable','LICENSE':b'fixture license'}
        payload={'schema':2,'version':'0.2.0','data_schema':1,'files':{n:hashlib.sha256(v).hexdigest() for n,v in data.items()},
            'licenses':['LICENSE'],'launch':{'platform':'windows-x64','entry':'ctflab-desktop.exe','executables':['ctflab-desktop.exe']}}
        index={'schema':1,'sequence':1,'expires':'2099-01-01T00:00:00Z','source':location,
            'assets':{hashlib.sha256(v).hexdigest():{'path':'objects/'+hashlib.sha256(v).hexdigest(),'size':len(v),
                'redistribution':'allowed','audience':'student'} for v in data.values()}}
        import base64
        def signed(value):return {'key_id':'main','payload':value,'signature':base64.b64encode(self.key.sign(canonical(value).encode())).decode()}
        def opened(request,timeout):
            calls.append(request.full_url)
            if request.full_url.endswith('INDEX.json'):raw=canonical(signed(index)).encode()
            elif request.full_url.endswith('RELEASE.json'):raw=canonical(signed(payload)).encode()
            else:raw=next(v for v in data.values() if request.full_url.endswith(hashlib.sha256(v).hexdigest()))
            return Response(raw,request.full_url)
        online=OnlineRelease(self.store.root,self.keys,self.bridge.target,opener=opened,check=self.bridge.check)
        self.bridge.online=lambda:online
        preview=self.request('online-preview',source=location,maximum=1024**2)
        self.assertEqual(preview['library_target'],self.bridge.target);operation=str(uuid.uuid4())
        downloaded=self.request('online-download',source=location,maximum=1024**2,plan_sha256=preview['plan_sha256'],operation_id=operation)
        before=len(calls);restored=self.request('online-restore',operation_id=operation)
        self.assertFalse(restored['network_sent']);self.assertEqual(len(calls),before)
        self.assertEqual(self.store.status()['versions'],[])
        self.request('stage',source=downloaded['source'],manifest=downloaded['manifest'])
        self.assertIsNone(self.store.status()['active']);self.assertEqual(self.store.status()['versions'],['0.2.0'])


if __name__=='__main__':unittest.main()
