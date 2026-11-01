"""Windows Job结构/限制与绑定替身；不在Mac创建Job，不操作真实VM。"""
from contextlib import contextmanager
import copy
import ctypes
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ctflab_windows_limits as module
from ctflab_contract import ContractError
from ctflab_windows_native import ProcessIdentity,BOOL
from test_ctflab_scenario_v2 import sample
from ctflab_scenario_v2 import instance_plan
import test_ctflab_qemu_driver as fixtures
import ctflab_qemu_driver as driver


def profile(plan):
    return {'windows_limits':{'schema':1,'nodes':{n:{'memory_max_mb':1024,'cpu_rate':2000,'processes_max':16}
        for n in plan['manifest']['nodes']}}}


class Kernel:
    def __init__(self):self.values={};self.closed=[];self.assigned=[];self.member=True;self.bad_flags=False
    def CreateJobObjectW(self,*args):return 11
    def OpenJobObjectW(self,access,inherit,name):assert access==4 and not inherit;return 11
    def CloseHandle(self,handle):self.closed.append(handle);return 1
    def SetInformationJobObject(self,handle,kind,pointer,size):self.values[kind]=ctypes.string_at(pointer,size);return 1
    def QueryInformationJobObject(self,handle,kind,pointer,size,unused):
        data=self.values[kind]
        if self.bad_flags and kind==15:data=bytes(module.CPU(1,2000))
        ctypes.memmove(pointer,data,size);return 1
    def GetCurrentProcess(self):return 99
    def AssignProcessToJobObject(self,handle,process):self.assigned.append((handle,process));return 1
    def IsProcessInJob(self,process,handle,result):ctypes.cast(result,ctypes.POINTER(BOOL))[0]=int(self.member);return 1


class LimitTests(unittest.TestCase):
    def setUp(self):
        self.plan=instance_plan(sample(),str(uuid.uuid4()));self.profile=profile(self.plan)
        self.value=module.declaration(self.profile,self.plan,'server','00000001')
        self.native=module.Native.__new__(module.Native);self.native.kernel=Kernel()
    def enter(self):
        with patch.object(ctypes,'set_last_error',create=True),patch.object(ctypes,'get_last_error',return_value=0,create=True):
            return module.enter(self.value,native=self.native)
    def test_abi_and_exact_limits_include_no_kill_or_breakaway(self):
        self.assertEqual((ctypes.sizeof(module.Basic),ctypes.sizeof(module.Extended),ctypes.sizeof(module.CPU)),(64,144,8))
        proof=self.enter();observed=self.native.query(11)
        self.assertEqual(observed,dict(self.value['limits'],memory_max_bytes=1024**3))
        self.assertEqual(self.native.kernel.assigned,[(11,99)]);self.assertFalse(proof['kill_on_close'])
        flags=module.Extended.from_buffer_copy(self.native.kernel.values[9]).BasicLimitInformation.LimitFlags
        self.assertEqual(flags,0x208);self.assertFalse(flags&(0x2000|0x800|0x1000))
        self.assertEqual(self.native.kernel.closed,[11]);self.assertFalse(proof['disk_quota_hard_enforced'])
    def test_existing_job_is_never_reconfigured_or_assigned(self):
        with patch.object(ctypes,'set_last_error',create=True),patch.object(ctypes,'get_last_error',return_value=183,create=True):
            with self.assertRaises(ContractError):self.native.enter(self.value)
        self.assertEqual(self.native.kernel.values,{});self.assertEqual(self.native.kernel.assigned,[])
        self.assertEqual(self.native.kernel.closed,[11])
    def test_wrong_types_memory_overhead_node_set_and_cpu_rate_refused(self):
        for changes in ({'cpu_rate':0},{'cpu_rate':10001},{'cpu_rate':True},{'memory_max_mb':512},{'processes_max':1}):
            configuration=copy.deepcopy(self.profile['windows_limits']);configuration['nodes']['server'].update(changes)
            with self.subTest(changes=changes),self.assertRaises(ContractError):module.settings(configuration,self.plan)
        configuration=copy.deepcopy(self.profile['windows_limits']);configuration['nodes'].pop('client')
        with self.assertRaises(ContractError):module.settings(configuration,self.plan)
    def test_declaration_rejects_changed_digest_or_name(self):
        for changes in ({'name':'Local\\Other'},{'generation':2},{'node':'middle'},{'attempt':'00000002'}):
            with self.assertRaises(ContractError):module.validate(dict(self.value,**changes))
    def test_native_unsupported_host_is_rejected_before_win32_calls(self):
        with patch.object(module.os,'name','posix'):
            with self.assertRaises(ContractError):module.Native()
    def test_observation_rechecks_exact_kernel_limits_and_retained_process_membership(self):
        proof=self.enter();expected=ProcessIdentity(123,456,'qemu.exe','running')
        @contextmanager
        def retained(value):
            self.assertEqual(value,expected);yield 55
        observer=type('Observer',(),{'retained':staticmethod(retained)})()
        with patch.object(module,'Win32',return_value=observer):
            self.assertTrue(module.verify(self.value,proof,expected,native=self.native)['cpu_commit_memory_process_limits_observed'])
            self.native.kernel.member=False
            with self.assertRaises(ContractError):module.verify(self.value,proof,expected,native=self.native)
            self.native.kernel.member=True;self.native.kernel.bad_flags=True
            with self.assertRaises(ContractError):module.verify(self.value,proof,expected,native=self.native)
        self.assertEqual(self.native.kernel.closed,[11,11,11,11])
    def test_bad_proof_never_observes_pid_or_opens_job(self):
        proof=self.enter();proof['declaration_sha256']='0'*64
        with patch.object(self.native,'verify',side_effect=AssertionError('不得观察')):
            with self.assertRaises(ContractError):module.verify(self.value,proof,ProcessIdentity(123,456,'x','running'),native=self.native)


class DriverTests(unittest.TestCase):
    setUp=fixtures.DriverTests.setUp
    setup_driver=fixtures.DriverTests.setup_driver
    run_action=fixtures.DriverTests.run_action
    context=fixtures.DriverTests.context
    attempt=fixtures.DriverTests.attempt
    def test_profile_validates_opt_in_and_launch_binding_change_is_refused(self):
        self.setup_driver();self.profile.update(profile(self.plan));driver.validate_profile(self.plan,self.profile)
        attempt=self.attempt()
        # 旧启动没有Job声明，不能通过追加profile把它说成已受限制。
        with self.assertRaises(ContractError):self.real.binding(self.plan,'server',self.paths,attempt)
    def test_linux_start_rejects_windows_job_before_identity_or_spawn(self):
        self.setup_driver();self.profile.update(profile(self.plan))
        with patch.object(driver.os,'name','posix'),patch.object(self.real,'observe',side_effect=AssertionError('不能观察或派生')):
            with self.assertRaises(ContractError):self.real.start(self.plan,'server',self.paths,{'display':'headless','allow_emulation':False})
    def test_cgroup_and_job_cannot_be_combined(self):
        self.setup_driver();self.profile.update(profile(self.plan));self.profile['resource_limits']={}
        with self.assertRaises(ContractError):driver.validate_profile(self.plan,self.profile)

    def test_worker_refuses_failed_job_before_logger_or_qemu(self):
        from ctflab_generation_store import digest,private_directory
        from ctflab_windows_recovery import record
        self.setup_driver();root=self.root/'worker';private_directory(root)
        binary=self.root/'not-executable-qemu';binary.write_bytes(b'fixture');binary.chmod(0o600)
        disk=self.paths['disk'];configuration=profile(self.plan)
        value=module.declaration(configuration,self.plan,'server','00000001')
        record(root/'control.lock',{});record(root/'launch.json',{'binary':str(binary),
            'binary_sha256':digest(binary),'argv':[str(binary)],'disk':str(disk),
            'disk_identity':[disk.stat().st_dev,disk.stat().st_ino],'certificates':{},'windows_job':value})
        with patch.object(driver,'fingerprints',return_value={}),\
             patch.object(driver,'native_observe',return_value=ProcessIdentity(123,456,str(binary),'running')),\
             patch.object(module,'enter',side_effect=ContractError('capability-unverified')),\
             patch('ctflab_bounded_log.spawn',side_effect=AssertionError('不能启动日志子进程')),\
             patch.object(driver.subprocess,'Popen',side_effect=AssertionError('不能启动QEMU')):
            with self.assertRaises(ContractError):driver.worker(root)
        self.assertTrue((root/'start.intent.json').is_file());self.assertFalse((root/'binding.json').exists())


if __name__=='__main__':unittest.main()
