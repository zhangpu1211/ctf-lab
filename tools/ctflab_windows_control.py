"""固定Smoke的Windows后台控制验收入口；普通用户私有文件通道，无网络监听。"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctflab_windows_smoke import QEMU, BASE, QEMU_SHA, BASE_SHA, digest, verified, copy_disk, command as smoke_command
from ctflab_runtime_inventory import inventory, compare, validate_reference
from ctflab_windows_native import ProcessIdentity, compare_identity, NativeError
from ctflab_process_supervisor import Supervisor, SupervisorError
from ctflab_qmp_transport import OwnedPipe, TransportError

SCHEMA = 1
MAX_REQUESTS = 256


class ControlError(ValueError):
    pass


def identifier(value):
    if not isinstance(value,str) or str(uuid.UUID(value)) != value:
        raise ControlError('ID必须是规范UUID')
    return value


def read_json(path, guard, limit=65536):
    guard(path)
    if not path.is_file():raise ControlError('JSON必须是普通文件')
    with path.open('rb') as stream:
        raw=stream.read(limit+1)
    if len(raw)>limit: raise ControlError('JSON超过限额')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ControlError('重复字段')
            result[key]=value
        return result
    def invalid(value):raise ControlError('非法JSON常量')
    return json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)


def write_new(path, value, guard):
    guard(path.parent)
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,sort_keys=True)
        stream.flush();os.fsync(stream.fileno())
    guard(path)


def settings(root, guard):
    value=read_json(root/'config.json',guard)
    if (type(value) is not dict or set(value)!={'schema','instance_uuid','generation','inventory_sha256'}
            or type(value['schema']) is not int or value['schema']!=SCHEMA or type(value['generation']) is not int or value['generation']!=1):
        raise ControlError('实例配置无效')
    identifier(value['instance_uuid'])
    if not isinstance(value['inventory_sha256'],str) or len(value['inventory_sha256'])!=64 or any(c not in '0123456789abcdef' for c in value['inventory_sha256']):
        raise ControlError('清单摘要无效')
    return value


def qmp_command(binary, disk):
    result=smoke_command(binary,disk)
    index=result.index('-monitor')
    result[index+1]='none'
    result.extend(['-qmp','stdio'])
    return result


class PrivateFiles:
    def __init__(self, root):
        from ctflab_windows_security import WindowsSecurity
        self.root=Path(root)
        self.security=WindowsSecurity()
    def guard(self,path):
        path=Path(path)
        if path!=self.root and self.root not in path.parents:raise ControlError('状态路径越界')
        self.security.verify(self.root,root=True)
        self.security.verify(path,root=path.is_dir())
    def create(self,path):
        self.guard(Path(path).parent)
        self.security.create_directory(path)


class BoundedLog:
    def __init__(self, stream, path, limit=1024*1024):
        self.stream=stream;self.path=path;self.limit=limit
        self.truncated=False;self.failed=False
        self.thread=threading.Thread(target=self.run,daemon=True)
        self.thread.start()
    def run(self):
        target=None
        try:
            try:target=self.path.open('xb')
            except OSError:self.failed=True
            remaining=self.limit
            while block:=self.stream.read1(4096):
                if len(block)>remaining:self.truncated=True
                if target is not None:
                    try:
                        target.write(block[:remaining]);target.flush()
                    except OSError:
                        self.failed=True
                        try:target.close()
                        except OSError:pass
                        target=None
                remaining=max(0,remaining-len(block))
            if target is not None:
                try:target.flush();os.fsync(target.fileno())
                except OSError:self.failed=True
        except OSError:self.failed=True
        finally:
            if target is not None:
                try:target.close()
                except OSError:self.failed=True
    def finish(self):
        self.thread.join(timeout=5)
        if self.thread.is_alive():return False
        self.stream.close()
        return not self.failed


def request_value(config, operation_id, action):
    identifier(operation_id)
    if action not in ('query-status','system_powerdown'):raise ControlError('不允许的控制命令')
    return {'schema':SCHEMA,'operation_id':operation_id,'instance_uuid':config['instance_uuid'],
            'generation':config['generation'],'action':action}


def validate_request(value,config,operation_id):
    if (type(value) is not dict or type(value.get('schema')) is not int or type(value.get('generation')) is not int
            or value != request_value(config,operation_id,value.get('action'))):
        raise ControlError('请求字段、实例或代次不匹配')
    return value


def submit(root, files, action, operation_id):
    config=settings(root,files.guard)
    request=request_value(config,operation_id,action)
    directory=root/('request-'+operation_id)
    if directory.exists():
        if read_json(directory/'request.json',files.guard)!=request:
            raise ControlError('同一操作ID的内容不同或提交中断')
        return directory
    if len(list(root.glob('request-*')))>=MAX_REQUESTS:raise ControlError('本实验请求达到限额')
    files.create(directory)
    # ready是最后的提交标记；部分写入不被后台执行。
    write_new(directory/'request.json',request,files.guard)
    write_new(directory/'ready.json',{'ready':True},files.guard)
    return directory


def process_requests(root, files, supervisor, config):
    directories=sorted(root.glob('request-*'))
    if len(directories)>MAX_REQUESTS:raise ControlError('请求超限，保留现场')
    control_failed=False
    for directory in directories:
        files.guard(directory)
        if not (directory/'ready.json').exists() or (directory/'response.json').exists():continue
        op=identifier(directory.name[len('request-'):])
        try:
            if read_json(directory/'ready.json',files.guard)!={'ready':True}:raise ControlError('提交标记无效')
            value=validate_request(read_json(directory/'request.json',files.guard),config,op)
            result=supervisor.command(op,value['action'])
        except (OSError,ValueError,SupervisorError,NativeError):
            result={'state':'unknown-or-rejected','automatic_replay':False}
            control_failed = control_failed or supervisor.transport.closed.is_set()
        write_new(directory/'response.json',result,files.guard)
    return not control_failed


def run_owned(root, files, config, spawn, observe, source_unchanged, timeout=5):
    """受信注入点仅供测试；生产CLI不允许指定程序/参数/观察器。"""
    write_new(root/'start.intent.json',{'instance_uuid':config['instance_uuid'],'generation':1},files.guard)
    process=None;transport=None;logger=None;supervisor=None
    failure=None
    try:
        process=spawn()
        write_new(root/'process-created.json',{'pid':process.pid},files.guard)
        logger=BoundedLog(process.stderr,root/'qemu-stderr.log')
        transport=OwnedPipe(process,timeout)
        identity=observe(process.pid)
        supervisor=Supervisor(root,transport,identity,observe,files.guard)
        supervisor.bind(config['instance_uuid'],1)
        transport.connect()
        write_new(root/'control-ready.json',{'ready':True},files.guard)
        while process.poll() is None:
            if not process_requests(root,files,supervisor,config):
                raise TransportError('控制命令结果未知')
            transport.pump()
            if not transport.observe()['control_available']:
                try:process.wait(timeout=.5)
                except subprocess.TimeoutExpired:raise TransportError('控制通道失效')
            time.sleep(.05)
    except (OSError,ValueError,RuntimeError) as exc:
        failure=type(exc).__name__
        write_new(root/'failure.json',{'reason':failure,'process_may_be_running':process is not None and process.poll() is None,
                                     'automatic_replay':False},files.guard)
    finally:
        # 控制错误后不杀VM，也不重建会话；后台继续持有句柄等待实际退出。
        if process is not None:
            while process.poll() is None:time.sleep(.1)
            if transport:
                try:transport.pump()
                except (ValueError,RuntimeError):pass
            if supervisor:
                try:supervisor.record_exit()
                except (OSError,ValueError,RuntimeError):failure=failure or 'exit-record-failed'
            log_ok=logger.finish() if logger else False
            events=list(transport.events) if transport else []
            shutdown_guest=any(e.get('event')=='SHUTDOWN' and isinstance(e.get('data'),dict)
                               and e['data'].get('guest') is True for e in events)
            try:source_intact=source_unchanged()
            except OSError:source_intact=None
            result={'state':'exited','returncode':process.returncode,'source_unchanged':source_intact,
                    'control_failure':failure,'shutdown_guest_event':shutdown_guest,
                    'graceful_stop_verified':False,'g0_passed':False,
                    'stderr_complete':log_ok and not logger.truncated if logger else False,
                    'events_dropped':transport.events_dropped if transport else 0}
            write_new(root/'result.json',result,files.guard)
            if transport:
                try:transport.reap()
                except TransportError:pass
    return 0 if failure is None and process is not None and process.returncode==0 else 1


def native_observe(pid):
    from ctflab_windows_native import Win32
    return Win32().observe(pid)


def prepare(root, reference_path):
    from ctflab_windows_security import WindowsSecurity
    from ctflab_windows_native import hypervisor_capability
    security=WindowsSecurity();security.current_user()
    verified(QEMU,QEMU_SHA);verified(BASE,BASE_SHA)
    if hypervisor_capability().get('hypervisor_present') is not True:raise ControlError('WHP不可用')
    reference=read_json(reference_path,lambda path:None,8*1024**2)
    validate_reference(reference)
    current=inventory(QEMU.parent)
    if not compare(reference,current)['matches']:raise ControlError('安装目录已变化；未启动，请先核验差异')
    if shutil.disk_usage(root.parent).free < BASE.stat().st_size+512*1024**2:
        raise ControlError('独立副本与余量所需空间不足')
    security.create_directory(root)
    files=PrivateFiles(root)
    copy_disk(BASE,root/'test-disk.qcow2');files.guard(root/'test-disk.qcow2')
    write_new(root/'inventory.json',reference,files.guard)
    config={'schema':1,'instance_uuid':str(uuid.uuid4()),'generation':1,'inventory_sha256':reference['inventory_sha256']}
    write_new(root/'config.json',config,files.guard)
    write_new(root/'worker.lock',{},files.guard)
    return files


def worker(root):
    from ctflab_windows_native import state_lock,hypervisor_capability
    files=PrivateFiles(root);files.guard(root)
    with state_lock(root/'worker.lock'):
        config=settings(root,files.guard)
        if (root/'start.intent.json').exists():raise ControlError('存在启动意图，不重启旧实例')
        reference=read_json(root/'inventory.json',files.guard,8*1024**2)
        if reference['inventory_sha256']!=config['inventory_sha256']:raise ControlError('清单绑定不符')
        if not compare(reference,inventory(QEMU.parent))['matches']:raise ControlError('运行时变化')
        verified(QEMU,QEMU_SHA);verified(BASE,BASE_SHA);verified(root/'test-disk.qcow2',BASE_SHA)
        files.guard(root/'test-disk.qcow2')
        if hypervisor_capability().get('hypervisor_present') is not True:raise ControlError('WHP不可用')
        write_new(root/'worker.json',asdict(native_observe(os.getpid())),files.guard)
        write_new(root/'host.json',{'system':platform.system(),'version':platform.version(),
                                  'machine':platform.machine(),'python':platform.python_version()},files.guard)
        def spawn():
            return subprocess.Popen(qmp_command(QEMU,root/'test-disk.qcow2'),stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=str(QEMU.parent),shell=False,close_fds=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        return run_owned(root,files,config,spawn,native_observe,lambda:digest(BASE)==BASE_SHA)


def recovery(root,files,observe=native_observe):
    settings(root,files.guard)
    report={'scope':'read-only-recovery','g0_passed':False,'automatic_replay':False,
            'worker_identity':'unknown','qemu_identity':'unknown','control_reconnected':False}
    for filename,key,field in [('worker.json','worker_identity',None),('binding.json','qemu_identity','identity')]:
        if not (root/filename).exists():continue
        try:
            value=read_json(root/filename,files.guard)
            expected=ProcessIdentity(**(value[field] if field else value))
            report[key]=compare_identity(expected,observe(expected.pid))
        except (OSError,ValueError,TypeError,NativeError):pass
    for filename,key in [('result.json','result'),('failure.json','failure')]:
        if (root/filename).exists():report[key]=read_json(root/filename,files.guard)
    report['control_ready_recorded']=(root/'control-ready.json').exists()
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    start=sub.add_parser('start');start.add_argument('--run',required=True);start.add_argument('--inventory',required=True)
    for name in ('worker','status','powerdown','recover'):
        p=sub.add_parser(name);p.add_argument('--run',required=True)
        if name in ('status','powerdown'):p.add_argument('--operation-id')
    args=parser.parse_args(argv)
    if os.name!='nt':
        print('仅Windows原生入口；没有启动任何进程。');return 1
    root=Path(os.path.abspath(args.run))
    try:
        if args.action=='start':
            files=prepare(root,Path(args.inventory))
            with (root/'worker-console.log').open('xb') as log:
                proc=subprocess.Popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),'worker','--run',str(root)],
                    stdin=subprocess.DEVNULL,stdout=log,stderr=log,close_fds=True,
                    creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
            print(json.dumps({'state':'worker-created','pid':proc.pid,'run':str(root),'g0_passed':False},ensure_ascii=False))
            print('后台准备控制通道；本命令退出不代表VM已启动，使用status核验。')
            return 0
        if args.action=='worker':return worker(root)
        files=PrivateFiles(root);files.guard(root)
        report=recovery(root,files)
        if args.action=='recover':print(json.dumps(report,ensure_ascii=False));return 0
        if report['worker_identity']!='running' or 'failure' in report or 'result' in report:
            print(json.dumps(report,ensure_ascii=False));return 2
        if not report['control_ready_recorded']:
            print('后台尚未就绪；稍后查询，不重复start。');return 2
        op=args.operation_id or str(uuid.uuid4())
        directory=submit(root,files,'query-status' if args.action=='status' else 'system_powerdown',op)
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if (directory/'response.json').exists():
                try:result=read_json(directory/'response.json',files.guard)
                except (json.JSONDecodeError,UnicodeError):time.sleep(.05);continue
                print(json.dumps({'operation_id':op,'result':result},ensure_ascii=False))
                return 0 if result.get('state')=='acknowledged' else 2
            time.sleep(.1)
        print(json.dumps({'operation_id':op,'state':'unknown','automatic_replay':False}))
        print('请求已保留；使用相同operation-id查询，不换新ID重复关机。')
        return 2
    except (OSError,ValueError,RuntimeError) as exc:
        reason=str(exc) if isinstance(exc,(ControlError,NativeError)) else type(exc).__name__
        print('操作未完成，现场保留：'+reason+'；请查看本轮日志。',file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
