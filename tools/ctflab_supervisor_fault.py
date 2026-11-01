"""专用验收实例的监督器故障注入：监督器自行退出，不按 PID 终止进程。"""
from dataclasses import asdict
import os
from pathlib import Path
import time

from ctflab_windows_native import ProcessIdentity, compare_identity


def identities(root, read, observe):
    binding = read(root/'binding.json')
    worker = read(root/'worker.json')
    ready = read(root/'observer-ready.json')
    if ready.get('identity') != binding.get('identity'):
        raise ValueError('独立观测器尚未绑定来宾进程')
    expected = {'qemu': binding['identity'], 'worker': worker, 'observer': ready['observer']}
    if len({v['pid'] for v in expected.values()}) != 3:
        raise ValueError('监督器、QEMU与观测器必须是不同进程')
    for value in expected.values():
        identity = ProcessIdentity(**value)
        if compare_identity(identity, observe(identity.pid)) != 'running':
            raise ValueError('故障注入前身份未确认')
    return expected


def request(root, *, read, record, observe):
    """调用方必须先通过实例锁和认证 QMP 查询；只创建一次绑定请求。"""
    root = Path(root)
    target = root/'supervisor-fault.intent.json'
    if target.exists():
        raise ValueError('已有监督器故障请求，保留现场，不重复注入')
    expected = identities(root, read, observe)
    record(target, {'schema': 1, 'action': 'supervisor-self-exit', **expected})
    return {'state': 'fault-requested', 'automatic_replay': False,
            'qemu_terminated': False, 'observer_terminated': False}


def request_and_wait(root, *, read, record, observe, native):
    """请求前保留监督器句柄，确认同一内核对象退出，不把查询失败当作已死。"""
    expected=identities(root,read,observe)['worker']
    with native.retained(ProcessIdentity(**expected)) as handle:
        result=request(root,read=read,record=record,observe=observe)
        code=native.wait_exit(handle,10000)
        if code is None:
            return dict(result,state='unknown',reason='supervisor-exit-timeout')
        record(root/'supervisor-fault.exit.json',{'identity':expected,'state':'exited',
               'returncode':code,'source':'retained-native-handle'})
        return dict(result,state='supervisor-exited',returncode=code)


def wait(process, root, *, read, record, observe, exit_now=os._exit):
    """保留自有 Popen 等待语义；只有精确绑定且观测器仍在才退出监督器。"""
    path = root/'supervisor-fault.intent.json'
    rejected = False
    while process.poll() is None:
        if not rejected and path.exists():
            try:
                value = read(path)
                expected = identities(root, read, observe)
                if (set(value) != {'schema', 'action', 'qemu', 'worker', 'observer'}
                        or type(value['schema']) is not int or value['schema'] != 1
                        or value['action'] != 'supervisor-self-exit'
                        or any(value[k] != v for k, v in expected.items())
                        or value['worker'] != asdict(observe(os.getpid()))
                        or value['qemu']['pid'] != process.pid):
                    raise ValueError('故障请求与当前监督器不符')
                record(root/'supervisor-fault.applied.json', value)
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                # 不重试畸形或不匹配的请求；不改变 QEMU/观测器生命周期。
                record(root/'supervisor-fault.rejected.json', {'state': 'rejected'})
                rejected = True
            else:
                exit_now(73)
                raise RuntimeError('监督器退出函数意外返回')
        time.sleep(.1)
    return process.wait()
