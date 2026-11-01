"""Mac通用后端合成整课：真实代次/文件/证书，QEMU与QMP注入，不启动VM。"""
import copy
from dataclasses import asdict
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1])]
import test_ctflab_generation_store as fixtures
from ctflab_generation_store import GenerationStore,digest,private_directory
from ctflab_local_service import OperationContext
from ctflab_scenario_coordinator import ScenarioCoordinator
from ctflab_contract import ContractError
from ctflab_windows_native import ProcessIdentity
import ctflab_qemu_driver as driver
from ctflab_runtime_inventory import inventory


class DarwinDriverTests(unittest.TestCase):
    setUp=fixtures.GenerationTests.setUp

    def build(self,mixed=False):
        manifest=copy.deepcopy(self.manifest)
        manifest['assets']['linux']['architecture']='aarch64'
        for node in manifest['nodes'].values():
            node.update(firmware='uefi',disk_bus='virtio')
            for nic in node['interfaces']:nic['model']='virtio-net-pci'
        assets={'linux':self.base}
        if mixed:
            manifest['assets']['x64']=dict(manifest['assets']['linux'],architecture='x86_64')
            manifest['nodes']['client'].update(asset='x64',firmware='bios',disk_bus='ide')
            for nic in manifest['nodes']['client']['interfaces']:nic['model']='e1000'
            assets['x64']=self.base
        runtime_root=self.root/'runtime';private_directory(runtime_root)
        code=runtime_root/'code.fd';code.write_bytes(b'fixture-code');code.chmod(0o444)
        self.template=self.root/'vars.fd';self.template.write_bytes(b'fixture-vars');self.template.chmod(0o444)
        arm={n for n,s in manifest['nodes'].items() if s['firmware']=='uefi'}
        self.store=GenerationStore.create(self.root/'mac',manifest,self.instance,assets,{n:self.template for n in arm})
        runtime=runtime_root/'bin';private_directory(runtime)
        for name in ('qemu-system-aarch64','qemu-system-x86_64'):
            path=runtime/name;path.write_bytes(b'synthetic-not-executable');path.chmod(0o600)
        reference=self.root/'inventory.json';driver.record(reference,inventory(runtime_root,executable='bin/qemu-system-aarch64'))
        self.profile={'host':'darwin-arm64','runtime_root':str(runtime_root),'binary':str(runtime/'qemu-system-aarch64'),'inventory':str(reference),
            'firmware':{n:{'code':str(code),'sha256':digest(code)} for n in arm},
            'networks':{'outer':18001,'inner':18002},
            'nodes':{n:{'qmp':19000+2*i,'vnc':19001+2*i} for i,n in enumerate(manifest['nodes'])}}
        if mixed:self.profile['emulator']=str(runtime/'qemu-system-x86_64')
        self.real=driver.QemuDriver(self.store,self.profile)
        self.coordinator=ScenarioCoordinator(self.store,course_id='c01',baseline_id='base',driver=self.real)
        self.action('prepare')
        self.plan=self.store.plan(1);self.paths=self.store.node_paths(1,'server')

    def action(self,operation,generation=1,mixed=False):
        params={'prepare':{'course_id':'c01','baseline_id':'base'},'start':{'display':'headless','allow_emulation':mixed},
                'stop':{},'reset':{'baseline_id':'base'},'recover':{}}[operation]
        return self.coordinator.execute({'operation':operation,'parameters':params},OperationContext(self.instance,str(uuid.uuid4()),generation,lambda:False))

    def test_native_arguments_use_hvf_private_nvram_and_loopback_tls(self):
        self.build();args,_=driver.arguments(self.plan,'server',self.paths,self.profile,self.root,{})
        self.assertEqual(args[args.index('-accel')+1],'hvf');self.assertEqual(args[args.index('-machine')+1],'virt')
        self.assertIn('readonly=on',' '.join(args));self.assertIn(str(self.paths['nvram']),' '.join(args))
        self.assertNotIn('0.0.0.0',' '.join(args));self.assertNotIn('netdev=user',' '.join(args));self.assertIn('tls-creds=ctflab-tls',' '.join(args))

    def test_mixed_x86_arguments_use_fixed_tcg_binary(self):
        self.build(mixed=True);paths=self.store.node_paths(1,'client')
        args,_=driver.arguments(self.plan,'client',paths,self.profile,self.root,{})
        self.assertEqual(Path(args[0]).name,'qemu-system-x86_64');self.assertEqual(args[args.index('-accel')+1],'tcg')
        self.assertNotIn('pflash',' '.join(args));self.assertNotIn('hvf',args)

    def test_emulation_requires_consent_before_any_spawn(self):
        self.build(mixed=True)
        with patch.object(driver.sys,'platform','darwin'),patch.object(driver.platform,'machine',return_value='arm64'),patch.object(driver,'spawn_worker',side_effect=AssertionError('不得启动')):
            with self.assertRaises(ContractError):self.real.start(self.plan,'server',self.paths,{'display':'headless','allow_emulation':False})

    def test_profile_refuses_firmware_drift_unsafe_host_and_cross_runtime_emulator(self):
        self.build(mixed=True)
        with self.assertRaises(ContractError):driver.validate_profile(self.plan,dict(self.profile,host='other'))
        with self.assertRaises(ContractError):driver.validate_profile(self.plan,dict(self.profile,emulator='/other/qemu-system-x86_64'))
        code=Path(self.profile['firmware']['server']['code']);code.chmod(0o600);code.write_bytes(b'changed')
        with self.assertRaises(ContractError):driver.arguments(self.plan,'server',self.paths,self.profile,self.root,{})

    def test_nvram_inode_replacement_and_launch_firmware_binding_refuse(self):
        self.build();location=self.real.location(self.plan,'server',self.paths);private_directory(location)
        attempt=location/'00000001';private_directory(attempt)
        args,name=driver.arguments(self.plan,'server',self.paths,self.profile,attempt,{})
        disk=self.paths['disk'].stat();nvram=self.paths['nvram'].stat()
        launch={'runtime_profile_sha256':driver.profile_sha(self.profile),'plan_sha256':self.plan['plan_sha256'],'node':'server',
            'disk':str(self.paths['disk']),'disk_identity':[disk.st_dev,disk.st_ino],'binary':self.profile['binary'],
            'qmp':self.profile['nodes']['server']['qmp'],'argv':args,'name':name,'certificates':{},
            'nvram':str(self.paths['nvram']),'nvram_identity':[nvram.st_dev,nvram.st_ino],'firmware':self.profile['firmware']['server']}
        driver.record(attempt/'launch.json',launch)
        driver.record(attempt/'binding.json',{'identity':asdict(ProcessIdentity(123,456,self.profile['binary'],'running')),'launch_sha256':digest(attempt/'launch.json')})
        self.real.binding(self.plan,'server',self.paths,attempt)
        self.paths['nvram'].rename(self.paths['nvram'].with_suffix('.retained'))
        self.paths['nvram'].write_bytes(b'new-inode');self.paths['nvram'].chmod(0o600)
        with self.assertRaises(ContractError):self.real.binding(self.plan,'server',self.paths,attempt)

    def test_complete_mixed_lifecycle_preserves_bases_and_old_generation(self):
        self.build(mixed=True);base=self.base.read_bytes();vars_original=self.template.read_bytes();identities={};commands=[]
        test=self
        class Client:
            def __init__(self,spec,expected,attempt):self.expected=expected;self.attempt=attempt
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def command(self,command):
                commands.append(command)
                if command=='system_powerdown':driver.record(self.attempt/'observer-exit.json',{'state':'exited','identity':asdict(self.expected),
                    'returncode':None,'source':'retained-darwin-kqueue','exit_code_known':False})
                return {'return':{'status':'running'}}
        def spawn(action,attempt):
            self.assertEqual(action,'worker');launch=driver.read(attempt/'launch.json')
            identity=ProcessIdentity(5000+len(identities),900+len(identities),launch['binary'],'running');identities[identity.pid]=identity
            driver.record(attempt/'binding.json',{'identity':asdict(identity),'launch_sha256':digest(attempt/'launch.json')})
            driver.record(attempt/'observer-ready.json',{'identity':asdict(identity),'observer':asdict(ProcessIdentity(9000+identity.pid,42,'synthetic-observer','running'))})
        with patch.object(driver.sys,'platform','darwin'),patch.object(driver.platform,'machine',return_value='arm64'),\
             patch.object(driver,'hypervisor_capability',return_value={'hypervisor_present':True}),patch.object(driver,'verify_disk'),\
             patch.object(driver,'spawn_worker',side_effect=spawn),patch.object(driver,'native_observe',side_effect=lambda pid:identities[pid]),\
             patch.object(self.real,'connection',side_effect=lambda *args:Client(*args)):
            self.assertEqual(self.action('start',mixed=True).state,'process-running')
            self.paths['nvram'].write_bytes(b'guest-progress')
            code=Path(self.profile['firmware']['server']['code']);code.chmod(0o600);code.write_bytes(b'changed-after-launch')
            self.assertEqual(self.action('stop').state,'stopped')
            self.assertEqual(self.action('recover').state,'stopped')
            self.assertEqual(self.action('reset').state,'prepared')
        with self.assertRaises(ContractError):driver.arguments(self.store.plan(2),'server',self.store.node_paths(2,'server'),self.profile,self.root,{})
        self.assertEqual(commands.count('system_powerdown'),3)
        self.assertEqual(self.store.snapshot()['active_generation'],2)
        self.assertEqual(self.paths['nvram'].read_bytes(),b'guest-progress')
        self.assertEqual(self.base.read_bytes(),base);self.assertEqual(self.template.read_bytes(),vars_original)
        self.assertEqual(self.store.node_paths(2,'server')['nvram'].read_bytes(),vars_original)
