"""cgroup限额声明、生产控制顺序、漂移拒绝及租约预算；仅内存树，不写宿主cgroup。"""
import copy
import os
import io
import json
import tempfile
from unittest.mock import patch
from pathlib import Path
import sys
import unittest
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_contract import ContractError
from ctflab_cgroup import settings,preflight,declaration,enter,verify,controls,KernelTree
from ctflab_scenario_v2 import instance_plan
from test_ctflab_scenario_v2 import sample


class Tree:
    def __init__(self):
        self.data={'cgroup.controllers':'cpu memory pids','cgroup.subtree_control':'cpu memory pids','cgroup.procs':''}
        self.identities={'':[1,2]};self.members={};self.trace=[];self.file_limit=None
    def read(self,key):return self.data[key]
    def write(self,key,value):self.trace.append(('write',key,value));self.data[key]=value
    def mkdir(self,name):
        if name in self.identities:raise FileExistsError(name)
        self.trace.append(('mkdir',name));self.identities[name]=[1,len(self.identities)+100];self.data[name+'/cgroup.procs']=''
        return self.identities[name]
    def stamp(self,name):return self.identities[name]
    def join_self(self,name):self.trace.append(('join',name));self.members[os.getpid()]=name
    def limit_files(self,maximum):self.trace.append(('file-limit',maximum));self.file_limit=(maximum,maximum)
    def file_limits(self,pid):return self.file_limit
    def contains(self,name,pid):return self.members.get(pid)==name


class CgroupTests(unittest.TestCase):
    def setUp(self):
        self.plan=instance_plan(sample(),str(uuid.uuid4()))
        self.profile={'resource_limits':{'cgroup_root':'/sys/fs/cgroup/user.slice/ctflab-delegated',
            'nodes':{n:{'memory_max_mb':768,'cpu_quota_us':100000,'pids_max':64} for n in self.plan['manifest']['nodes']}}}
        self.tree=Tree();self.spec=declaration(self.profile,self.plan,'client','00000001',tree=self.tree)
    def test_controls_all_apply_before_migrating_only_supervisor_and_future_children_inherit(self):
        proof=enter(self.spec,tree=self.tree)
        self.assertEqual(self.tree.trace[-1],('join',self.spec['group']))
        self.assertEqual(len([x for x in self.tree.trace if x[0]=='write']),5)
        self.assertTrue(proof['cpu_memory_pids_enforced_before_qemu']);self.assertFalse(proof['disk_quota_hard_enforced'])
        self.tree.members[321]=self.spec['group'];result=verify(self.spec,proof,321,tree=self.tree)
        self.assertTrue(result['cpu_memory_pids_limits_observed']);self.assertFalse(result['disk_quota_hard_enforced'])
        self.assertEqual(controls(self.spec['limits'])['memory.swap.max'],'0')
    def test_reuse_or_existing_group_never_rewrites_limits_or_moves_again(self):
        enter(self.spec,tree=self.tree);before=list(self.tree.trace)
        with self.assertRaises(FileExistsError):enter(self.spec,tree=self.tree)
        self.assertEqual(self.tree.trace,before)
    def test_missing_controller_root_process_or_root_identity_change_refuses_before_mkdir(self):
        for field,value in (('cgroup.controllers','cpu pids'),('cgroup.subtree_control','cpu pids'),('cgroup.procs','999')):
            tree=Tree();tree.data[field]=value
            with self.assertRaises(ContractError):enter(self.spec,tree=tree)
            self.assertEqual(tree.trace,[])
        self.tree.identities['']=[1,999]
        with self.assertRaises(ContractError):enter(self.spec,tree=self.tree)
        self.assertEqual(self.tree.trace,[])
    def test_kernel_limit_drift_or_pid_moved_is_unknown_not_reapplied(self):
        proof=enter(self.spec,tree=self.tree);before=list(self.tree.trace)
        for name in controls(self.spec['limits']):
            key=self.spec['group']+'/'+name;old=self.tree.data[key];self.tree.data[key]='max'
            with self.assertRaises(ContractError):verify(self.spec,proof,os.getpid(),tree=self.tree)
            self.tree.data[key]=old
        self.tree.members[os.getpid()]='other-instance'
        with self.assertRaises(ContractError):verify(self.spec,proof,os.getpid(),tree=self.tree)
        self.assertEqual(self.tree.trace,before)
    def test_declaration_tamper_and_unsafe_roots_or_unbounded_fields_refused(self):
        bad=copy.deepcopy(self.spec);bad['limits']['pids_max']=999
        with self.assertRaises(ContractError):enter(bad,tree=self.tree)
        for root in ('/tmp/cgroup','/sys/fs/cgroup/../other','/sys/fs/cgroup','relative','/sys/fs/cgroup/a;bad'):
            value=copy.deepcopy(self.profile['resource_limits']);value['cgroup_root']=root
            with self.assertRaises(ContractError):settings(value,self.plan)
        for change in ({'pids_max':31},{'memory_max_mb':512},{'cpu_quota_us':100001},{'pids_max':True},{'command':['sh']}):
            value=copy.deepcopy(self.profile['resource_limits']);value['nodes']['client'].update(change)
            with self.assertRaises(ContractError):settings(value,self.plan)
    def test_group_names_separate_instance_generation_node_and_attempt(self):
        one=self.spec['group']
        self.assertNotEqual(one,declaration(self.profile,self.plan,'client','00000002',tree=self.tree)['group'])
        self.assertNotEqual(one,declaration(self.profile,self.plan,'server','00000001',tree=self.tree)['group'])
        plan=instance_plan(sample(),self.plan['instance_uuid'],generation=2)
        self.assertNotEqual(one,declaration(self.profile,plan,'client','00000001',tree=self.tree)['group'])
    def test_production_worker_enters_limits_before_logger_or_qemu_spawn(self):
        from ctflab_qemu_driver import worker
        from ctflab_windows_recovery import record
        from ctflab_generation_store import digest
        from ctflab_windows_native import ProcessIdentity
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();binary=root/'qemu';binary.write_bytes(b'fixture executable');binary.chmod(0o600)
            disk=root/'overlay.qcow2';disk.write_bytes(b'fixture derived disk');disk.chmod(0o600)
            record(root/'control.lock',{})
            record(root/'launch.json',{'binary':str(binary),'binary_sha256':digest(binary),'argv':[str(binary)],
                'disk':str(disk),'disk_identity':[disk.stat().st_dev,disk.stat().st_ino],'certificates':{},'cgroup':self.spec})
            trace=[]
            class Receiver:
                stdin=io.BytesIO()
            class Process:
                pid=123
            def enter_limits(value):trace.append('limits');return {'fixture':True}
            def logger(*a):trace.append('logger');return Receiver()
            def spawn(*a,**kw):
                self.assertTrue((root/'cgroup.json').is_file());trace.append('qemu');return Process()
            with patch('ctflab_cgroup.enter',side_effect=enter_limits),patch('ctflab_bounded_log.spawn',side_effect=logger),\
                 patch('ctflab_qemu_driver.subprocess.Popen',side_effect=spawn),patch('ctflab_qemu_driver.fingerprints',return_value={}),\
                 patch('ctflab_qemu_driver.native_observe',side_effect=lambda pid:ProcessIdentity(pid,456,str(binary),'running')),\
                 patch('ctflab_qemu_driver.spawn_worker',return_value=None),patch('ctflab_supervisor_fault.wait',return_value=0):
                worker(root)
            self.assertEqual(trace,['limits','logger','qemu']);self.assertEqual(json.loads((root/'exit.json').read_text())['returncode'],0)

    def test_optional_overlay_file_cap_is_not_reported_as_aggregate_filesystem_quota(self):
        for limits in self.profile['resource_limits']['nodes'].values():limits['disk_max_bytes']=64*1024**2
        spec=declaration(self.profile,self.plan,'client','00000001',tree=self.tree);proof=enter(spec,tree=self.tree)
        self.assertEqual(proof['overlay_file_limit_bytes'],64*1024**2)
        result=verify(spec,proof,os.getpid(),tree=self.tree)
        self.assertTrue(result['overlay_file_limit_observed']);self.assertFalse(result['disk_quota_hard_enforced'])
        self.tree.file_limit=(128*1024**2,128*1024**2)
        with self.assertRaises(ContractError):verify(spec,proof,os.getpid(),tree=self.tree)
    def test_mixed_or_invalid_disk_caps_cannot_claim_full_instance_coverage(self):
        value=copy.deepcopy(self.profile['resource_limits']);value['nodes']['client']['disk_max_bytes']=64*1024**2
        with self.assertRaises(ContractError):settings(value,self.plan)
        for limits in value['nodes'].values():limits['disk_max_bytes']=True
        with self.assertRaises(ContractError):settings(value,self.plan)

    def test_native_adapter_is_not_enabled_on_mac_or_windows_test_host(self):
        if sys.platform!='linux':
            with self.assertRaises(ContractError):KernelTree(self.profile['resource_limits']['cgroup_root'])


if __name__=='__main__':unittest.main()
