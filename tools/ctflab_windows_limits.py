"""自有Windows worker树的Job CPU/提交内存/进程数限制；无强杀或磁盘配额声明。"""
import ctypes
from dataclasses import asdict
import hashlib
import os
import re

from ctflab_contract import require,canonical,uuid_text,identifier
from ctflab_windows_native import Win32,ProcessIdentity,DWORD,BOOL,HANDLE


class Basic(ctypes.Structure):
    _fields_=[('ProcessTime',ctypes.c_int64),('JobTime',ctypes.c_int64),('LimitFlags',DWORD),
        ('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),
        ('ActiveProcessLimit',DWORD),('Affinity',ctypes.c_size_t),('PriorityClass',DWORD),('SchedulingClass',DWORD)]


class IO(ctypes.Structure):
    _fields_=[(name,ctypes.c_uint64) for name in ('ReadOperations','WriteOperations','OtherOperations','ReadBytes','WriteBytes','OtherBytes')]


class Extended(ctypes.Structure):
    _fields_=[('BasicLimitInformation',Basic),('IoInfo',IO),('ProcessMemoryLimit',ctypes.c_size_t),
        ('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]


class CPU(ctypes.Structure):
    _fields_=[('ControlFlags',DWORD),('CpuRate',DWORD)]


def limits(value):
    require(type(value) is dict and set(value)=={'memory_max_mb','cpu_rate','processes_max'})
    require(type(value['memory_max_mb']) is int and 512<=value['memory_max_mb']<=1024**2
        and type(value['cpu_rate']) is int and 1<=value['cpu_rate']<=10000
        and type(value['processes_max']) is int and 8<=value['processes_max']<=256)
    return value


def settings(value,plan):
    require(type(value) is dict and set(value)=={'schema','nodes'} and type(value['schema']) is int and value['schema']==1)
    require(type(value['nodes']) is dict and set(value['nodes'])==set(plan['manifest']['nodes']))
    for name,spec in value['nodes'].items():
        limits(spec);require(spec['memory_max_mb']>=plan['manifest']['nodes'][name]['memory_mb']+256)
    return value


def declaration(profile,plan,node,attempt):
    configuration=settings(profile['windows_limits'],plan);identifier(node)
    require(type(attempt) is str and re.fullmatch('[0-9]{8}',attempt))
    value={'schema':1,'instance_uuid':plan['instance_uuid'],'generation':plan['generation'],'node':node,
        'attempt':attempt,'name':f'Local\\CTFLab-{plan["instance_uuid"]}-g{plan["generation"]}-{node}-a{attempt}',
        'limits':configuration['nodes'][node]}
    value['sha256']=hashlib.sha256(canonical(value).encode()).hexdigest();return validate(value)


def validate(value):
    require(type(value) is dict and set(value)=={'schema','instance_uuid','generation','node','attempt','name','limits','sha256'}
        and type(value['schema']) is int and value['schema']==1)
    uuid_text(value['instance_uuid']);identifier(value['node']);limits(value['limits'])
    require(type(value['generation']) is int and 1<=value['generation']<=2**31-1
        and type(value['attempt']) is str and re.fullmatch('[0-9]{8}',value['attempt']))
    require(value['name']==f'Local\\CTFLab-{value["instance_uuid"]}-g{value["generation"]}-{value["node"]}-a{value["attempt"]}','identity-unknown')
    require(hashlib.sha256(canonical({k:v for k,v in value.items() if k!='sha256'}).encode()).hexdigest()==value['sha256'],'identity-unknown')
    return value


class Native:
    def __init__(self):
        require(os.name=='nt' and ctypes.sizeof(ctypes.c_void_p)==8,'unsupported-platform')
        require(ctypes.sizeof(Basic)==64 and ctypes.sizeof(Extended)==144 and ctypes.sizeof(CPU)==8,'unsupported-platform')
        self.kernel=ctypes.WinDLL('kernel32.dll',winmode=0x800,use_last_error=True)
        definitions={'CreateJobObjectW':([ctypes.c_void_p,ctypes.c_wchar_p],HANDLE),
            'OpenJobObjectW':([DWORD,BOOL,ctypes.c_wchar_p],HANDLE),'CloseHandle':([HANDLE],BOOL),
            'SetInformationJobObject':([HANDLE,ctypes.c_int32,ctypes.c_void_p,DWORD],BOOL),
            'QueryInformationJobObject':([HANDLE,ctypes.c_int32,ctypes.c_void_p,DWORD,ctypes.POINTER(DWORD)],BOOL),
            'AssignProcessToJobObject':([HANDLE,HANDLE],BOOL),'GetCurrentProcess':([],HANDLE),
            'IsProcessInJob':([HANDLE,HANDLE,ctypes.POINTER(BOOL)],BOOL)}
        for name,(args,result) in definitions.items():
            method=getattr(self.kernel,name);method.argtypes=args;method.restype=result

    def query(self,handle):
        extended=Extended();cpu=CPU()
        for kind,value in ((9,extended),(15,cpu)):
            require(self.kernel.QueryInformationJobObject(handle,kind,ctypes.byref(value),ctypes.sizeof(value),None),'identity-unknown')
        require(extended.BasicLimitInformation.LimitFlags==0x208 and cpu.ControlFlags==5,'state-conflict')
        return {'memory_max_mb':extended.JobMemoryLimit//1024**2,'cpu_rate':cpu.CpuRate,
            'processes_max':extended.BasicLimitInformation.ActiveProcessLimit,
            'memory_max_bytes':extended.JobMemoryLimit}

    def check(self,handle,value,process):
        observed=self.query(handle);expected=value['limits']
        require(all(observed[k]==v for k,v in expected.items())
            and observed['memory_max_bytes']==expected['memory_max_mb']*1024**2,'state-conflict')
        member=BOOL();require(self.kernel.IsProcessInJob(process,handle,ctypes.byref(member)) and member.value==1,'identity-unknown')

    def enter(self,value):
        validate(value);ctypes.set_last_error(0);handle=self.kernel.CreateJobObjectW(None,value['name'])
        require(bool(handle),'permission-denied')
        try:
            # 命名对象存在时只关闭本次句柄；绝不修改已有Job或收编外部进程。
            require(ctypes.get_last_error()!=183,'resource-busy')
            extended=Extended();extended.BasicLimitInformation.LimitFlags=0x208
            extended.BasicLimitInformation.ActiveProcessLimit=value['limits']['processes_max']
            extended.JobMemoryLimit=value['limits']['memory_max_mb']*1024**2
            cpu=CPU(5,value['limits']['cpu_rate'])
            for kind,item in ((9,extended),(15,cpu)):
                require(self.kernel.SetInformationJobObject(handle,kind,ctypes.byref(item),ctypes.sizeof(item)),'capability-unverified')
            process=self.kernel.GetCurrentProcess()
            require(self.kernel.AssignProcessToJobObject(handle,process),'capability-unverified')
            self.check(handle,value,process)
            return handle
        except BaseException:self.kernel.CloseHandle(handle);raise

    def verify(self,value,expected):
        validate(value);require(type(expected) is ProcessIdentity,'identity-unknown')
        handle=self.kernel.OpenJobObjectW(4,False,value['name'])
        require(bool(handle),'identity-unknown')
        try:
            with Win32().retained(expected) as process:self.check(handle,value,process)
        finally:self.kernel.CloseHandle(handle)

    def close(self,handle):
        require(bool(self.kernel.CloseHandle(handle)),'control-unreachable')


def enter(value,*,native=None):
    validate(value);native=native or Native();handle=native.enter(value)
    # 当前worker和子进程持有Job归属；关闭控制句柄不终止成员。
    # 不设置KILL_ON_JOB_CLOSE/BREAKAWAY，不创建可继承Job句柄。
    try:
        return {'schema':1,'declaration_sha256':value['sha256'],'worker_pid':os.getpid(),
            'limits_applied_before_qemu':True,'kill_on_close':False,'disk_quota_hard_enforced':False}
    finally:native.close(handle)


def verify(value,proof,expected,*,native=None):
    validate(value)
    require(type(proof) is dict and set(proof)=={'schema','declaration_sha256','worker_pid','limits_applied_before_qemu','kill_on_close','disk_quota_hard_enforced'}
        and type(proof['schema']) is int and proof['schema']==1 and proof['declaration_sha256']==value['sha256']
        and type(proof['worker_pid']) is int and proof['worker_pid']>0 and proof['limits_applied_before_qemu'] is True
        and proof['kill_on_close'] is False and proof['disk_quota_hard_enforced'] is False,'identity-unknown')
    (native or Native()).verify(value,expected)
    return {'cpu_commit_memory_process_limits_observed':True,'disk_quota_hard_enforced':False,'graceful_stop_verified':False}
