"""Windows固定Smoke的可重连运行入口：本机双向TLS控制/显示，不接管旧control-r1。"""
import argparse
from contextlib import contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

if __package__ in (None, ''):
    sys.path.insert(0,str(Path(__file__).resolve().parent))

from ctflab_tls_endpoint import guard, provision, fingerprints, server_arguments
from ctflab_windows_control import read_json, prepare, settings, native_observe
from ctflab_windows_smoke import QEMU, BASE, QEMU_SHA, BASE_SHA, digest, verified, command as smoke_command
from ctflab_windows_native import ProcessIdentity, compare_identity
from ctflab_qmp_tls import QMPClient


def record(path, value):
    guard(path.parent)
    fd = os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,sort_keys=True)
        stream.flush();os.fsync(stream.fileno())
    guard(path)


@contextmanager
def command_lock(root):
    path = root/'control.lock'
    guard(root);guard(path)
    if os.name == 'nt':
        from ctflab_windows_native import state_lock
        with state_lock(path): yield
    else:
        import fcntl
        with path.open('rb') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            yield


def validate_config(value):
    if type(value) is not dict or set(value) != {'schema','instance_uuid','generation','name','qmp_port','vnc_port','certificates'}:
        raise ValueError('端点配置字段无效')
    if type(value['schema']) is not int or value['schema'] != 1 or type(value['generation']) is not int or value['generation'] != 1:
        raise ValueError('端点版本或代次无效')
    identity = value['instance_uuid']
    if str(uuid.UUID(identity)) != identity or value['name'] != 'ctflab-'+identity+'-g1-smoke':
        raise ValueError('实例名称不符')
    if (type(value['qmp_port']) is not int or not 1024 <= value['qmp_port'] <= 65535
            or type(value['vnc_port']) is not int or not 5900 <= value['vnc_port'] <= 65535
            or value['qmp_port'] == value['vnc_port']):
        raise ValueError('固定本机端口无效')
    from ctflab_tls_endpoint import CERT_FILES
    certs = value['certificates']
    if type(certs) is not dict or set(certs) != set(CERT_FILES):
        raise ValueError('证书清单缺失')
    for checksum in certs.values():
        if not isinstance(checksum,str) or len(checksum) != 64 or any(c not in '0123456789abcdef' for c in checksum):
            raise ValueError('证书摘要无效')
    return value


def launch_arguments(binary,disk,root,config):
    config = validate_config(config)
    result = smoke_command(binary,disk)
    result[result.index('-name')+1] = config['name']
    result[result.index('-display')+1] = 'none'
    result[result.index('-monitor')+1] = 'none'
    result += server_arguments(root/'tls',config['instance_uuid'])
    result += ['-chardev',f'socket,id=control,host=127.0.0.1,port={config["qmp_port"]},server=on,wait=off,ipv4=on,tls-creds=ctflab-tls,tls-authz=ctflab-client',
               '-mon','chardev=control,mode=control',
               '-vnc',f'127.0.0.1:{config["vnc_port"]-5900},tls-creds=ctflab-tls,tls-authz=ctflab-client']
    return result


class RuntimeClient:
    def __init__(self,root,*,observe=native_observe,connector=QMPClient):
        self.root = Path(root).absolute()
        guard(self.root)
        self.config = validate_config(read_json(self.root/'endpoint.json',guard))
        config = settings(self.root,guard)
        if any(config[k] != self.config[k] for k in ('instance_uuid','generation')):
            raise ValueError('实例配置绑定不符')
        self.observe = observe
        self.connector = connector

    def identity(self):
        binding = read_json(self.root/'binding.json',guard)
        if any(binding.get(k) != self.config[k] for k in ('instance_uuid','generation')):
            raise ValueError('进程绑定不属于该实例')
        expected = ProcessIdentity(**binding['identity'])
        try: return compare_identity(expected,self.observe(expected.pid))
        except Exception: return 'unknown'

    def connect(self):
        if self.identity() != 'running':
            raise ValueError('进程身份未确认，拒绝连接或控制')
        c = self.config
        connection = self.connector(c['qmp_port'],self.root/'tls',c['certificates'],c['name'])
        if self.identity() != 'running':
            connection.close()
            raise ValueError('连接期间进程身份发生变化')
        return connection

    def status(self):
        report = {'scope':'authenticated-reconnect','g0_passed':False,'control_reconnected':False,
                  'automatic_replay':False,'identity':'unknown'}
        if (self.root/'observer-exit.json').exists():
            exit_record = read_json(self.root/'observer-exit.json', guard)
            binding = read_json(self.root/'binding.json', guard)
            if (any(binding.get(k) != self.config[k] for k in ('instance_uuid', 'generation'))
                    or exit_record.get('identity') != binding.get('identity')
                    or exit_record.get('state') != 'exited'
                    or type(exit_record.get('returncode')) is not int):
                raise ValueError('退出观测绑定不符')
            report.update(identity='exited', result=exit_record)
            return report
        if (self.root/'result.json').exists():
            report['result'] = read_json(self.root/'result.json',guard)
            return report
        if not (self.root/'binding.json').exists():
            report.update(state='preparing', stage='binding-pending')
            report['start_intent_exists'] = (self.root/'start.intent.json').exists()
            return report
        report['identity'] = self.identity()
        if report['identity'] == 'running':
            with self.connect() as connection:
                response = connection.command('query-status')
            if 'error' in response or type(response.get('return')) is not dict:
                raise ValueError('QMP查询未成功')
            report.update(control_reconnected=True,qemu_status=response['return'].get('status','unknown'))
        report['unfinished_operations'] = [p.stem for p in self.root.glob('powerdown-*.intent.json')
                                          if not p.with_name(p.name.replace('.intent.','.result.')).exists()]
        return report

    def powerdown(self,operation):
        if str(uuid.UUID(operation)) != operation:
            raise ValueError('操作ID无效')
        with command_lock(self.root):
            intent = self.root/('powerdown-'+operation+'.intent.json')
            result = self.root/('powerdown-'+operation+'.result.json')
            if intent.exists():
                return read_json(result,guard) if result.exists() else {'state':'unknown','automatic_replay':False}
            if list(self.root.glob('powerdown-*.intent.json')):
                raise ValueError('已存在关机意图；用原操作ID读取，不换ID重复关机')
            with self.connect() as connection:
                record(intent,{'operation_id':operation,'instance_uuid':self.config['instance_uuid'],
                               'generation':1,'action':'system_powerdown'})
                try:
                    reply = connection.command('system_powerdown')
                    outcome = {'state':'rejected' if 'error' in reply else 'acknowledged',
                               'automatic_replay':False,'graceful_stop_verified':False}
                except Exception:
                    outcome = {'state':'unknown','automatic_replay':False,'graceful_stop_verified':False}
                record(result,outcome)
                return outcome

    def display(self):
        from ctflab_rfb_tls import RFBClient
        # 建立显示前先经过QMP名称和内核身份的双重核验。
        with self.connect(): pass
        c = self.config
        display = RFBClient(c['vnc_port'],self.root/'tls',c['certificates'])
        if self.identity() != 'running':
            display.close()
            raise ValueError('显示连接期间进程身份发生变化')
        return display

    def supervisor_fault(self):
        from ctflab_supervisor_fault import request_and_wait
        from ctflab_windows_native import Win32
        with command_lock(self.root):
            if list(self.root.glob('powerdown-*.intent.json')):
                raise ValueError('已存在关机意图，拒绝故障注入')
            with self.connect() as connection:
                if 'return' not in connection.command('query-status'):
                    raise ValueError('QMP未确认，拒绝故障注入')
            return request_and_wait(self.root, read=lambda p: read_json(p, guard), record=record,
                                    observe=self.observe, native=Win32())


def prepare_runtime(root,reference,qmp_port,vnc_port):
    # 依赖检查必须在复制镜像前完成；不自动安装第三方包。
    import cryptography
    if cryptography.__version__ != '46.0.5':
        raise ValueError('此开发包证书生成器仅核验cryptography==46.0.5；未启动')
    identity = str(uuid.uuid4())
    placeholder = {name:'0'*64 for name in __import__('ctflab_tls_endpoint').CERT_FILES}
    validate_config({'schema':1,'instance_uuid':identity,'generation':1,'name':'ctflab-'+identity+'-g1-smoke',
                     'qmp_port':qmp_port,'vnc_port':vnc_port,'certificates':placeholder})
    prepare(root,reference)
    base_config = settings(root,guard)
    identity = base_config['instance_uuid']
    certificates = provision(root/'tls',identity)
    config = {'schema':1,'instance_uuid':identity,'generation':1,'name':'ctflab-'+identity+'-g1-smoke',
              'qmp_port':qmp_port,'vnc_port':vnc_port,'certificates':certificates}
    record(root/'endpoint.json',config)
    record(root/'control.lock',{})
    return config


def worker(root):
    from ctflab_windows_native import state_lock, hypervisor_capability
    from ctflab_runtime_inventory import inventory, compare
    with state_lock(root/'worker.lock'):
        config = validate_config(read_json(root/'endpoint.json',guard))
        base_config = settings(root,guard)
        if (base_config['instance_uuid'] != config['instance_uuid']
                or fingerprints(root/'tls') != config['certificates']):
            raise ValueError('配置/证书绑定不符')
        if (root/'start.intent.json').exists():
            raise ValueError('已有启动意图；不重启旧实例')
        reference = read_json(root/'inventory.json',guard,8*1024**2)
        if reference['inventory_sha256'] != base_config['inventory_sha256'] or not compare(reference,inventory(QEMU.parent))['matches']:
            raise ValueError('运行时目录已变化')
        verified(QEMU,QEMU_SHA);verified(BASE,BASE_SHA);verified(root/'test-disk.qcow2',BASE_SHA)
        if hypervisor_capability().get('hypervisor_present') is not True:
            raise ValueError('WHP不可用；不回退TCG')
        record(root/'worker.json',asdict(native_observe(os.getpid())))
        record(root/'start.intent.json',{'instance_uuid':config['instance_uuid'],'generation':1})
        # QEMU直接持有日志文件与TLS监听，不依赖worker的匿名管道或控制连接。
        with (root/'qemu-stderr.log').open('xb') as log:
            process = subprocess.Popen(launch_arguments(QEMU,root/'test-disk.qcow2',root,config),
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=log,cwd=str(QEMU.parent),
                close_fds=True,creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
            record(root/'process-created.json',{'pid':process.pid})
            try:
                identity = native_observe(process.pid)
                record(root/'binding.json',{'schema':1,'instance_uuid':config['instance_uuid'],'generation':1,'identity':asdict(identity)})
                from ctflab_qemu_driver import spawn_worker
                try:
                    spawn_worker('observe-exit', root)
                except OSError:
                    record(root/'observer-failure.json', {'reason':'observer-spawn-failed','process_may_be_running':True})
            except Exception:
                record(root/'failure.json',{'reason':'binding-unknown','process_may_be_running':True})
            from ctflab_supervisor_fault import wait
            code = wait(process, root, read=lambda p: read_json(p, guard), record=record, observe=native_observe)
        try: unchanged = digest(BASE) == BASE_SHA
        except OSError: unchanged = None
        record(root/'result.json',{'state':'exited','returncode':code,'source_unchanged':unchanged,
                                  'graceful_stop_verified':False,'g0_passed':False})
        return 0 if code == 0 else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action',required=True)
    for name in ('start','worker','status','recover','powerdown','display','supervisor-fault'):
        p = sub.add_parser(name);p.add_argument('--run',required=True,type=Path)
        if name == 'start':
            p.add_argument('--inventory',required=True,type=Path)
            p.add_argument('--qmp-port',required=True,type=int)
            p.add_argument('--vnc-port',required=True,type=int)
        if name == 'powerdown':p.add_argument('--operation-id')
    args = parser.parse_args(argv)
    if os.name != 'nt':
        print('此运行入口仅支持Windows；未启动任何进程。');return 2
    root = args.run.absolute()
    try:
        if args.action == 'start':
            prepare_runtime(root,args.inventory,args.qmp_port,args.vnc_port)
            with (root/'worker-console.log').open('xb') as log:
                process = subprocess.Popen([sys.executable,'-I','-B',str(Path(__file__).resolve()),'worker','--run',str(root)],
                    stdin=subprocess.DEVNULL,stdout=log,stderr=log,close_fds=True,
                    creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
            print(json.dumps({'state':'worker-created','pid':process.pid,'g0_passed':False}))
            return 0
        if args.action == 'worker':return worker(root)
        client = RuntimeClient(root)
        if args.action == 'display':
            from ctflab_rfb_tls import show
            show(client.display);return 0
        if args.action == 'supervisor-fault':
            print(json.dumps(client.supervisor_fault()));return 0
        if args.action == 'powerdown':
            operation = args.operation_id or str(uuid.uuid4())
            result = client.powerdown(operation)
            print(json.dumps({'operation_id':operation,'result':result}))
            return 0 if result.get('state') == 'acknowledged' else 2
        print(json.dumps(client.status(),ensure_ascii=False));return 0
    except (OSError,ValueError,RuntimeError,ImportError,KeyError,TypeError) as exc:
        print('操作未完成，现场保留：'+type(exc).__name__+'。请核对依赖、实例记录与本轮日志。',file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
