"""VMGenID声明/私有材料/代次/工作器/QMP绑定；只用临时文件和替身，不启动QEMU。"""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError,canonical
from ctflab_generation_store import GenerationStore,private_directory,digest
from ctflab_scenario_coordinator import ScenarioCoordinator
from ctflab_windows_recovery import record
from ctflab_windows_native import ProcessIdentity
import ctflab_scenario_v2 as scenario
import ctflab_qemu_driver as driver
import ctflab_vmgenid as ids
import test_ctflab_generation_store as fixture


class GenerationIDTests(unittest.TestCase):
    def setUp(self):
        fixture.GenerationTests.setUp(self)
        self.manifest['nodes']['server']['vmgenid']=ids.MODE
        self.manifest['nodes']['client']['vmgenid']=ids.MODE
        self.store=GenerationStore.create(self.root/'managed',self.manifest,self.instance,{'linux':self.base})
        self.backend=ScenarioCoordinator(self.store,course_id='c01',baseline_id='base',driver=self.driver)
    context=fixture.GenerationTests.context
    run_action=fixture.GenerationTests.run_action
    def value(self,generation=1,node='server'):
        return ids.declaration(self.store,self.store.plan(generation),node)
    def prepared(self):
        self.assertEqual(self.run_action('prepare').state,'prepared')
        self.plan=self.store.plan(1);self.paths=self.store.node_paths(1,'server')
        self.profile={'binary':str(self.root/'qemu.exe'),'inventory':str(self.root/'inventory.json'),
            'networks':{'outer':18001,'inner':18002},'nodes':{n:{'qmp':19000+2*i,'vnc':19001+2*i} for i,n in enumerate(self.manifest['nodes'])}}
        self.real=driver.QemuDriver(self.store,self.profile)
        root=self.real.location(self.plan,'server',self.paths);private_directory(root)
        self.attempt=root/'00000001';private_directory(self.attempt)
        self.guid=self.value()
        args,name=driver.arguments(self.plan,'server',self.paths,self.profile,self.attempt,{},generation_id=self.guid)
        self.spec={'schema':1,'plan_sha256':self.plan['plan_sha256'],'node':'server','disk':str(self.paths['disk']),
            'argv':args,'name':name,'vmgenid':self.guid,'binary':self.profile['binary'],'qmp':19004,'certificates':{}}
    def test_manifest_explicit_opt_in_preserves_old_plan_and_no_implicit_key(self):
        old=copy.deepcopy(self.manifest)
        for node in old['nodes'].values():node.pop('vmgenid',None)
        plain=GenerationStore.create(self.root/'plain',old,str(uuid.uuid4()),{'linux':self.base})
        self.assertFalse((plain.root/ids.KEY_FILE).exists());self.assertNotIn('vmgenid',plain.config)
        self.assertIsNone(ids.declaration(plain,plain.plan(1),'server'))
        self.assertNotIn('vmgenid',plain.plan(1)['manifest']['nodes']['server'])
    def test_bad_modes_arbitrary_guid_or_arm_guest_rejected(self):
        for value in (False,True,{},'auto',str(uuid.uuid4()),ids.MODE+',guid=bad'):
            bad=copy.deepcopy(self.manifest);bad['nodes']['server']['vmgenid']=value
            with self.assertRaises(scenario.ScenarioError):scenario.validate_manifest(bad)
        bad=copy.deepcopy(self.manifest);bad['assets']['linux']['architecture']='aarch64'
        with self.assertRaises(scenario.ScenarioError):scenario.validate_manifest(bad)
    def test_key_private_random_not_exposed_in_config_plan_or_snapshot(self):
        key=(self.store.root/ids.KEY_FILE).read_bytes();self.assertEqual(len(key),32)
        if os.name!='nt':self.assertEqual((self.store.root/ids.KEY_FILE).stat().st_mode&0o777,0o600)
        public=canonical([self.store.config,self.store.plan(1),self.store.snapshot()])
        self.assertNotIn(key.hex(),public);self.assertNotIn(key.decode('latin1'),public)
        self.assertEqual(self.store.config['vmgenid']['key_sha256'],digest(self.store.root/ids.KEY_FILE))
    def test_same_generation_reopen_and_different_node_generation_instance(self):
        first=self.value();self.assertEqual(self.value(),first)
        reopened=GenerationStore(self.store.root);self.assertEqual(ids.declaration(reopened,reopened.plan(1),'server'),first)
        self.assertNotEqual(self.value(node='client')['guid'],first['guid'])
        self.assertNotEqual(self.value(2)['guid'],first['guid'])
        other=GenerationStore.create(self.root/'other',self.manifest,self.instance,{'linux':self.base})
        self.assertNotEqual(ids.declaration(other,other.plan(1),'server')['guid'],first['guid'])
        self.assertEqual(uuid.UUID(first['guid']).version,4)
    def test_reset_changes_guid_and_preserves_old_progress_and_key(self):
        self.run_action('prepare');old=self.value();key=(self.store.root/ids.KEY_FILE).read_bytes()
        disk=self.store.node_paths(1,'server')['disk'];disk.write_bytes(b'prior-progress')
        self.assertEqual(self.run_action('reset').state,'prepared')
        self.assertNotEqual(self.value(2)['guid'],old['guid']);self.assertEqual(self.value(),old)
        self.assertEqual(disk.read_bytes(),b'prior-progress');self.assertEqual((self.store.root/ids.KEY_FILE).read_bytes(),key)
    def test_missing_changed_linked_or_nonprivate_key_never_regenerates(self):
        path=self.store.root/ids.KEY_FILE;original=path.read_bytes();path.write_bytes(b'x'*32)
        with self.assertRaises(ContractError):self.value()
        self.assertEqual(path.read_bytes(),b'x'*32)
        path.write_bytes(original)
        if os.name!='nt':
            path.chmod(0o644)
            with self.assertRaises(ValueError):self.value()
            path.chmod(0o600)
        path.unlink()
        with self.assertRaises(OSError):self.value()
        self.assertFalse(path.exists());other=self.root/'other-key';other.write_bytes(original);other.chmod(0o600);path.symlink_to(other)
        with self.assertRaises((ContractError,ValueError)):self.value()
        path.unlink();os.link(other,path)
        with self.assertRaises((ContractError,ValueError)):self.value()
    def test_initialize_never_replaces_existing_random_material(self):
        original=(self.store.root/ids.KEY_FILE).read_bytes()
        with self.assertRaises(FileExistsError):ids.initialize(self.store.root)
        self.assertEqual((self.store.root/ids.KEY_FILE).read_bytes(),original)
    def test_declaration_rejects_forged_plan_and_wrong_scope(self):
        plan=self.store.plan(1);plan['instance_uuid']=str(uuid.uuid4())
        with self.assertRaises(ContractError):ids.declaration(self.store,plan,'server')
        for field,value in (('generation',True),('generation',2),('node','client'),('instance_uuid',str(uuid.uuid4())),('guid','auto')):
            wrong=dict(self.value(),**{field:value})
            with self.assertRaises(ContractError):ids.checked(wrong,self.store.plan(1),'server')
    def test_exact_device_arg_required_and_unopted_node_cannot_inject(self):
        self.prepared();args=self.spec['argv']
        self.assertEqual(args.count('vmgenid,guid='+self.guid['guid']),1);self.assertNotIn('vmgenid,guid=auto',args)
        with self.assertRaises(ContractError):driver.arguments(self.plan,'server',self.paths,self.profile,self.attempt,{})
        with self.assertRaises(ContractError):driver.arguments(self.plan,'middle',self.paths,self.profile,self.attempt,{},generation_id=self.guid)
    def test_worker_checks_store_generation_and_device_before_any_spawn(self):
        self.prepared();ids.verify_launch(self.spec,self.attempt)
        for change in ('guid','omit','device','duplicate','plan'):
            bad=copy.deepcopy(self.spec)
            if change=='guid':bad['vmgenid']['guid']=str(uuid.uuid4())
            if change=='omit':bad.pop('vmgenid')
            if change=='device':bad['argv']=[v for v in bad['argv'] if not v.startswith('vmgenid,')]
            if change=='duplicate':bad['argv']+=['-device','vmgenid,guid='+self.guid['guid']]
            if change=='plan':bad['plan_sha256']='0'*64
            with patch('subprocess.Popen',side_effect=AssertionError('不允许启动')):
                with self.assertRaises(ContractError):ids.verify_launch(bad,self.attempt)
    def test_launch_binding_refuses_removed_or_forged_generation_id(self):
        self.prepared();info=self.paths['disk'].stat();self.spec.update(disk_identity=[info.st_dev,info.st_ino])
        record(self.attempt/'launch.json',self.spec)
        identity=ProcessIdentity(123,4,str(self.root/'qemu.exe'),'running')
        record(self.attempt/'binding.json',{'identity':identity.__dict__,'launch_sha256':digest(self.attempt/'launch.json')})
        self.real.binding(self.plan,'server',self.paths,self.attempt)
        self.spec.pop('vmgenid');(self.attempt/'launch.json').write_text(canonical(self.spec))
        (self.attempt/'binding.json').write_text(canonical({'identity':identity.__dict__,'launch_sha256':digest(self.attempt/'launch.json')}))
        with self.assertRaises(ContractError):self.real.binding(self.plan,'server',self.paths,self.attempt)
    def test_qmp_guid_exact_match_is_only_hypervisor_evidence(self):
        value=self.value();client=Mock();client.command.return_value={'return':{'guid':value['guid']}}
        report=ids.verify_qmp(client,value);client.command.assert_called_once_with('query-vm-generation-id')
        self.assertTrue(report['qmp_guid_verified']);self.assertFalse(report['guest_guid_verified']);self.assertFalse(report['domain_health_verified'])
        for reply in ({'return':{}},{'error':{}},{'return':{'guid':str(uuid.uuid4())}}):
            client.command.return_value=reply
            with self.assertRaises(ContractError):ids.verify_qmp(client,value)
    def test_live_connection_mismatch_closes_before_control_or_display(self):
        self.prepared();expected=ProcessIdentity(123,4,self.profile['binary'],'running')
        client=Mock();client.command.return_value={'return':{'guid':str(uuid.uuid4())}}
        with patch.object(driver,'native_observe',return_value=expected),patch.object(driver,'QMPClient',return_value=client):
            with self.assertRaises(ContractError):self.real.connection(self.spec,expected,self.attempt)
        client.close.assert_called_once();client.command.assert_called_once_with('query-vm-generation-id')
    def test_worker_entry_refuses_modified_guid_before_start_intent_or_spawn(self):
        self.prepared();self.spec['vmgenid']['guid']=str(uuid.uuid4())
        record(self.attempt/'launch.json',self.spec);record(self.attempt/'control.lock',{})
        with patch('subprocess.Popen',side_effect=AssertionError('不可创建QEMU')):
            with self.assertRaises(ContractError):driver.worker(self.attempt)
        self.assertFalse((self.attempt/'start.intent.json').exists())
    def test_late_worker_for_old_prepared_generation_cannot_start_after_reset(self):
        self.prepared();old=self.value();self.assertEqual(self.run_action('reset').state,'prepared')
        self.assertEqual(self.value(),old)
        with self.assertRaises(ContractError):ids.verify_launch(self.spec,self.attempt)
    def test_copied_attempt_outside_registered_generation_location_refused(self):
        self.prepared()
        other=self.store.root/'generations'/'1-unregistered'/'server'/'runtime'/'00000001'
        for path in (other,self.attempt.with_name('unregistered')):
            with self.assertRaises(ContractError):ids.verify_launch(self.spec,path)
        ids.verify_launch(self.spec,self.attempt)


if __name__=='__main__':unittest.main()
