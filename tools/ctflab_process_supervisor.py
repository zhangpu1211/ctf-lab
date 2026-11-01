"""单次自有进程监督与持久意图；不支持重启后重新接管匿名管道。

调用方必须提供已验证ACL/权限的私有根、真实内核身份观察器与自有传输。
磁盘中的身份仅供核验，绝不用于自动重开或终止PID。
"""
from contextlib import contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import uuid
from ctflab_windows_native import ProcessIdentity, compare_identity


class SupervisorError(RuntimeError):
    pass


class Supervisor:
    def __init__(self, root, transport, identity, observe, guard):
        if not isinstance(identity, ProcessIdentity) or transport.process.pid != identity.pid:
            raise SupervisorError('传输与自有进程绑定不匹配')
        self.root=Path(root)
        self.transport=transport
        self.identity=identity
        self.observe_identity=observe
        self.guard=guard

    @contextmanager
    def locked(self):
        self.guard(self.root)
        lock=self.root/'operation.lock'
        try: fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError: raise SupervisorError('监督操作忙或中断现场待核验') from None
        try:
            os.close(fd)
            yield
        finally:
            lock.unlink()

    def save(self, name, value):
        self.guard(self.root)
        path=self.root/name
        # 独占不可变记录：绝不覆盖旧证据。写入失败保留部分文件并阻止重放。
        with path.open('x',encoding='utf-8') as stream:
            json.dump(value,stream,ensure_ascii=False,sort_keys=True)
            stream.flush();os.fsync(stream.fileno())

    def verify(self):
        try: observed=self.observe_identity(self.identity.pid)
        except Exception: return 'unknown'
        return compare_identity(self.identity,observed)

    def bind(self, instance_uuid, generation):
        if str(uuid.UUID(instance_uuid)) != instance_uuid or type(generation) is not int or generation < 1:
            raise SupervisorError('实例或代次无效')
        if not isinstance(self.identity,ProcessIdentity):raise SupervisorError('缺少进程身份')
        with self.locked():
            if self.verify() != 'running':raise SupervisorError('进程身份未确认')
            self.save('binding.json',{'schema':1,'instance_uuid':instance_uuid,'generation':generation,
                                     'identity':asdict(self.identity)})

    def command(self, operation_id, command):
        if str(uuid.UUID(operation_id)) != operation_id:raise SupervisorError('操作ID无效')
        if command not in ('query-status','system_powerdown'):raise SupervisorError('命令不允许')
        with self.locked():
            self.guard(self.root/'binding.json')
            binding=json.loads((self.root/'binding.json').read_text(encoding='utf-8'))
            if binding['identity'] != asdict(self.identity):raise SupervisorError('绑定不匹配')
            intent=self.root/(operation_id+'.intent.json')
            if intent.exists():raise SupervisorError('操作已登记；先核验结果，禁止重放')
            if self.verify() != 'running':raise SupervisorError('进程身份未确认，拒绝控制')
            self.save(intent.name,{'operation_id':operation_id,'command':command,
                                  'instance_uuid':binding['instance_uuid'],'generation':binding['generation']})
            try:
                reply=self.transport.command(command)
            except Exception:
                self.save(operation_id+'.result.json',{'state':'unknown','reason':'control-failed','replay_allowed':False})
                raise SupervisorError('控制结果未知，保留现场，不重放') from None
            result={'state':'rejected' if 'error' in reply['message'] else 'acknowledged',
                    'graceful_stop_verified':False,'replay_allowed':False}
            if command == 'query-status' and isinstance(reply['message'].get('return'), dict):
                status = reply['message']['return'].get('status')
                if status in ('running','paused','shutdown','prelaunch','internal-error','guest-panicked'):
                    result['qemu_status'] = status
            self.save(operation_id+'.result.json',result)
            return result

    def record_exit(self):
        with self.locked():
            state=self.transport.observe()
            if state['state'] != 'exited':raise SupervisorError('自有进程尚未退出')
            self.save('exit.json',{'state':'exited','returncode':state['returncode'],
                                   'graceful_stop_verified':False})
            return state

    def recovery_status(self):
        # 仅报告；即使身份匹配也不能据此恢复已失去的匿名管道。
        self.guard(self.root)
        return {'identity':self.verify(),'control_reconnected':False,
                'interrupted_lock':(self.root/'operation.lock').exists(),
                'unresolved_operations':sorted(p.name for p in self.root.glob('*.intent.json')
                    if not p.with_name(p.name.replace('.intent.json','.result.json')).exists()),
                'automatic_replay':False}
