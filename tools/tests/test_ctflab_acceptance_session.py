"""集中验收拒绝跨实例、缺失故障证明和重复启动；不连接实际实例。"""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ctflab_acceptance_session import compare
from ctflab_contract import ContractError


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.qemu={'pid':1,'creation_ticks':10,'image_path':'qemu','state':'running'}
        self.worker={'pid':2,'creation_ticks':20,'image_path':'python','state':'running'}
        self.before={'schema':1,'kind':'scenario','instance_uuid':'fixture','generation':1,'plan_sha256':'plan',
                     'sources':{'base':{'expected':'sha','actual':'sha'}},'nodes':{'server':{
                     'status':{'identity':'verified','state':'process-running'},'disk_path':'gen1/disk','disk_identity':[1,2],
                     'runtime':{'attempt':'00000001','launch_sha256':'launch','start_intents':['start.intent.json'],
                     'binding.json':{'identity':self.qemu},'worker.json':self.worker}}}}
        self.after=copy.deepcopy(self.before)
        self.after['nodes']['server']['runtime'].update({
            'supervisor-fault.applied.json':{'worker':self.worker,'qemu':self.qemu},
            'supervisor-fault.exit.json':{'identity':self.worker,'state':'exited','returncode':73,'source':'retained-native-handle'}})

    def test_matching_recovery_passes_only_control_checks(self):
        result=compare(self.before,self.after,'recovery')
        self.assertEqual(result['result'],'passed')
        self.assertFalse(result['guest_verified']);self.assertFalse(result['course_verified'])

    def test_without_fault_proof_not_marked_recovered(self):
        self.assertEqual(compare(self.before,self.before,'recovery')['result'],'failed')

    def test_pid_replacement_or_new_start_fails(self):
        self.after['nodes']['server']['runtime']['binding.json']['identity']['creation_ticks']=99
        self.assertEqual(compare(self.before,self.after,'recovery')['result'],'failed')

    def test_unknown_or_no_qmp_not_counted_running(self):
        self.after['nodes']['server']['status']={'identity':'running','control_reconnected':False}
        self.assertEqual(compare(self.before,self.after,'recovery')['result'],'failed')

    def test_cross_instance_refused(self):
        self.after['instance_uuid']='other'
        with self.assertRaises(ContractError):compare(self.before,self.after,'recovery')

    def test_unchanged_base_must_be_measured(self):
        self.after['sources']={}
        self.assertEqual(compare(self.before,self.after,'recovery')['result'],'failed')

    def test_restart_requires_new_process_same_disk(self):
        self.after['nodes']['server']['runtime']['binding.json']['identity']['creation_ticks']=99
        self.after['nodes']['server']['runtime']['attempt']='00000002'
        self.assertEqual(compare(self.before,self.after,'restart')['result'],'passed')
        self.after['nodes']['server']['disk_identity']=[1,9]
        self.assertEqual(compare(self.before,self.after,'restart')['result'],'failed')

    def test_reset_requires_new_baseline_and_old_progress_still_present(self):
        left=self.before['nodes']['server'];right=self.after['nodes']['server']
        left['status']['state']=right['status']['state']='stopped'
        left['disk_sha256']='progress';self.after['generation']=2
        right.update(disk_path='gen2/disk',disk_identity=[1,3],disk_sha256='base',baseline_sha256='base')
        self.after['retained_generations']={'1':{'server':{k:left[k] for k in ('disk_path','disk_identity','disk_sha256')}}}
        self.assertEqual(compare(self.before,self.after,'reset')['result'],'passed')
        self.after['retained_generations']['1']['server']['disk_sha256']='changed'
        self.assertEqual(compare(self.before,self.after,'reset')['result'],'failed')


if __name__=='__main__':unittest.main()
