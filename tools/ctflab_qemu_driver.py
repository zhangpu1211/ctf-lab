"""场景协调器的跨平台 QEMU 后端：回环链路、独立代次。

宿主显式提供固定运行时清单和端口；不接受课程中的命令或路径。
不强杀、不回滚已启动节点，未确认退出时拒绝重启与重置。
"""
import argparse
import hashlib
from dataclasses import asdict
import json
import os
import platform
import re
from pathlib import Path
import subprocess
import sys
import time
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from ctflab_contract import require,canonical
from ctflab_generation_store import GenerationStore, private_directory, digest
from ctflab_scenario_coordinator import NodeObservation, ScenarioCoordinator
from ctflab_tls_endpoint import guard, provision, server_arguments, fingerprints, certificate_status
from ctflab_windows_control import read_json, native_observe as windows_observe
from ctflab_windows_recovery import record, command_lock
from ctflab_windows_native import ProcessIdentity, compare_identity as windows_compare_identity, hypervisor_capability as windows_capability, Win32, NativeError
from ctflab_qmp_tls import QMPClient
from ctflab_runtime_inventory import inventory, compare


def read(path):
    return read_json(path, guard, 8*1024**2)


def profile_sha(profile):return hashlib.sha256(canonical(profile).encode()).hexdigest()


def runtime_dependencies():
    from importlib.util import find_spec
    def available(name):
        try:return find_spec(name) is not None
        except (ImportError,ValueError,AttributeError):return False
    # 这里只定位安装内容，不把模块存在当成原生显示或来宾验收。
    return {'tls_control':available('cryptography'),
            'display':available('tkinter') and available('_tkinter'),
            'native_verified':False}


def compare_identity(expected, observed):
    if sys.platform=='darwin' and isinstance(expected,ProcessIdentity) and isinstance(observed,ProcessIdentity) and expected.image_path!=observed.image_path:
        return 'mismatch'
    return windows_compare_identity(expected, observed)


def native_observe(pid):
    if sys.platform=='darwin':
        from ctflab_darwin_native import observe
        return observe(pid)
    if sys.platform=='linux':
        from ctflab_linux_native import observe
        return observe(pid)
    return windows_observe(pid)


def hypervisor_capability():
    if sys.platform=='darwin':
        from ctflab_darwin_native import capability
        return capability()
    if sys.platform=='linux':
        from ctflab_linux_native import capability
        return capability()
    return windows_capability()


def spawn_options():
    return ({'creationflags':subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name=='nt' else {'start_new_session':True})


def network_members(plan, network):
    """按既有启动顺序选中心；不额外修改生命周期依赖。"""
    return [n for n in plan['start_order'] if any(i['network'] == network
            for i in plan['manifest']['nodes'][n]['interfaces'])]


def network_ports(plan, ports):
    """双成员保留整数；其他网段显式为每个非中心成员声明端口。

    计划声明external槽位时，端口规划必须含'external'接入口（dict形式）；
    未声明external的旧计划保持整数/dict原语义，二成员直连不得携带external。
    """
    from ctflab_external_attach import validate_hub_networks
    flattened, external = validate_hub_networks(plan, ports)
    return flattened


def external_port(plan, ports, network):
    """返回网段的external接入口端口；未声明槽位返回None。"""
    from ctflab_external_attach import validate_hub_networks
    _flattened, external = validate_hub_networks(plan, ports)
    return external.get(network)


def network_arguments(plan, node, ports):
    """首成员内的独立hub连接回环TCP星形链路，不创建宿主网卡或出口。

    带external槽位的网段由中心成员额外预留一个listen口，唯一客户端是
    认证过的接入中转；不把普通数据口当认证接口。
    """
    network_ports(plan, ports)
    args = []
    for nic in plan['manifest']['nodes'][node]['interfaces']:
        network = nic['network']
        members = network_members(plan, network)
        value = ports[network]
        if len(members) == 2 and type(value) is int:
            role = 'listen' if members[0] == node else 'connect'
            args += ['-netdev', f'socket,id={nic["id"]},{role}=127.0.0.1:{value}']
        elif members[0] != node:
            args += ['-netdev', f'socket,id={nic["id"]},connect=127.0.0.1:{value[node]}']
        else:
            hub = sorted(plan['manifest']['networks']).index(network)
            # 内部ID独立于用户网卡ID，避免用户声明与辅助netdev重名。
            used = {i['id'] for i in plan['manifest']['nodes'][node]['interfaces']}
            prefix = 'ctflab'
            while any(name.startswith(prefix) for name in used):
                prefix += 'x'
            for index, peer in enumerate(members[1:]):
                link = f'{prefix}{hub}s{index}'
                args += ['-netdev', f'socket,id={link},listen=127.0.0.1:{value[peer]}',
                         '-netdev', f'hubport,id={prefix}{hub}p{index},hubid={hub},netdev={link}']
            args += ['-netdev', f'hubport,id={nic["id"]},hubid={hub}']
            reserved = external_port(plan, ports, network)
            if reserved is not None:
                link = f'{prefix}{hub}x'
                args += ['-netdev', f'socket,id={link},listen=127.0.0.1:{reserved}',
                         '-netdev', f'hubport,id={prefix}{hub}e,hubid={hub},netdev={link}']
        args += ['-device', f'{nic["model"]},netdev={nic["id"]},mac={nic["mac"]}']
    return args


def node_binary(plan, node, profile):
    if profile.get('host') == 'darwin-arm64' and plan['manifest']['assets'][plan['manifest']['nodes'][node]['asset']]['architecture']=='x86_64':
        return profile['emulator']
    return profile['binary']


def validate_profile(plan, profile):
    required_profile={'binary','inventory','nodes','networks'}
    require(type(profile) is dict and required_profile<=set(profile)<=required_profile|{'agents','resource_limits','windows_limits','storage_boundary','windows_storage','host','firmware','emulator','macos_storage','runtime_root','recoverable_logs'})
    require('recoverable_logs' not in profile or type(profile['recoverable_logs']) is bool)
    if profile.get('recoverable_logs'):
        from ctflab_recoverable_log import supported
        supported()
    mac = profile.get('host') == 'darwin-arm64'
    require(len({'storage_boundary','macos_storage','windows_storage'}&set(profile))<=1,'capability-unverified')
    if 'windows_storage' in profile:
        require(not mac,'capability-unverified')
        from ctflab_windows_storage import settings as windows_storage_settings
        windows_storage_settings(profile['windows_storage'],instance=plan['instance_uuid'])
    if 'windows_limits' in profile:
        require(not mac and 'resource_limits' not in profile,'capability-unverified')
        from ctflab_windows_limits import settings as windows_limit_settings
        windows_limit_settings(profile['windows_limits'],plan)
    require('host' not in profile or mac, 'capability-unverified')
    require(mac or not {'firmware','emulator','runtime_root'} & set(profile), 'capability-unverified')
    if 'macos_storage' in profile:
        require(mac,'capability-unverified')
        from ctflab_macos_storage import settings as mac_settings
        mac_settings(profile['macos_storage'])
    if mac:
        require(not {'resource_limits','storage_boundary'} & set(profile), 'capability-unverified')
        arm = {n for n,s in plan['manifest']['nodes'].items() if plan['manifest']['assets'][s['asset']]['architecture']=='aarch64'}
        require(type(profile.get('firmware')) is dict and set(profile['firmware']) == arm)
        require(Path(profile['binary']).name == 'qemu-system-aarch64', 'capability-unverified')
        require(type(profile.get('runtime_root')) is str and Path(profile['runtime_root']).is_absolute()
                and '..' not in Path(profile['runtime_root']).parts and str(Path(profile['runtime_root']))==profile['runtime_root']
                and Path(profile['binary'])==Path(profile['runtime_root'])/'bin/qemu-system-aarch64', 'capability-unverified')
        if len(arm) != len(plan['manifest']['nodes']):
            require(type(profile.get('emulator')) is str and Path(profile['emulator']).is_absolute()
                    and Path(profile['emulator']).name=='qemu-system-x86_64'
                    and Path(profile['emulator']).parent==Path(profile['binary']).parent, 'capability-unverified')
        for entry in profile['firmware'].values():
            require(type(entry) is dict and set(entry)=={'code','sha256'} and type(entry['code']) is str and Path(entry['code']).is_absolute()
                    and type(entry['sha256']) is str and len(entry['sha256'])==64 and all(c in '0123456789abcdef' for c in entry['sha256']))
            require(Path(profile['runtime_root']) in Path(entry['code']).parents, 'capability-unverified')
            require('..' not in Path(entry['code']).parts and str(Path(entry['code']))==entry['code'], 'capability-unverified')
    if 'storage_boundary' in profile:
        from ctflab_storage_boundary import settings as storage_settings
        storage_settings(profile['storage_boundary'],instance=plan['instance_uuid'])
    if 'resource_limits' in profile:
        from ctflab_cgroup import settings as limit_settings
        limit_settings(profile['resource_limits'],plan)
    require(set(profile['nodes']) == set(plan['manifest']['nodes']))
    ports = network_ports(plan, profile['networks'])
    agents=profile.get('agents',{})
    require(type(agents) is dict and set(agents)<=set(plan['manifest']['nodes']))
    for node,agent in agents.items():
        required={'port','devices','flows','containers','container_cidr'}
        require(type(agent) is dict and required<=set(agent)<=required|{'images','endpoint','routed','analysis'})
        for optional in ('images','endpoint'):
            if optional in agent:require(type(agent[optional]) is dict)
        from ctflab_guest_policy import compile_policy
        compile_policy(plan,node,agent['devices'],agent['flows'],containers=agent['containers'],container_cidr=agent['container_cidr'],images=agent.get('images'),endpoint=agent.get('endpoint'),routed=agent.get('routed',False),analysis=agent.get('analysis'))
        ports.append(agent['port'])
    for node, spec in plan['manifest']['nodes'].items():
        architecture = plan['manifest']['assets'][spec['asset']]['architecture']
        require((mac and spec['firmware']=='uefi' and spec['disk_bus']=='virtio' and architecture=='aarch64') or
                (mac and spec['firmware']=='bios' and spec['disk_bus'] in ('ide','virtio') and architecture=='x86_64') or
                (not mac and spec['firmware']=='bios' and spec['disk_bus'] in ('ide','virtio') and architecture=='x86_64'), 'capability-unverified')
        entry = profile['nodes'][node]
        require(type(entry) is dict and set(entry) == {'qmp', 'vnc'})
        require(type(entry['vnc']) is int and entry['vnc'] >= 5900)
        ports.extend(entry.values())
        network_arguments(plan, node, profile['networks'])
    require(all(type(p) is int and 1024 <= p <= 65535 for p in ports))
    require(len(ports) == len(set(ports)), 'resource-busy')
    require(Path(profile['binary']).is_absolute() and Path(profile['inventory']).is_absolute())
    return profile


def arguments(plan, node, paths, profile, attempt, certificates, *, verify_firmware=True, generation_id=None):
    validate_profile(plan, profile)
    spec = plan['manifest']['nodes'][node]
    # QEMU keyval 以双逗号转义路径；课程不能提供运行参数。
    disk = str(paths['disk']).replace(',', ',,')
    name = f'ctflab-{plan["instance_uuid"]}-g{plan["generation"]}-{node}'
    ports = profile['nodes'][node]
    args = [profile['binary'], '-no-user-config', '-serial', 'none', '-parallel', 'none', '-name', name, '-machine', 'pc', '-accel', 'kvm' if sys.platform=='linux' else 'whpx',
            '-smp', str(spec['cpus']), '-m', str(spec['memory_mb']), '-nodefaults',
            '-display', 'none', '-monitor', 'none', '-vga', 'std',
            '-drive', f'file={disk},format=qcow2,if={spec["disk_bus"]}', '-boot', 'c']
    if sys.platform=='linux':args+=['-cpu','host']
    if profile.get('host') == 'darwin-arm64' and plan['manifest']['assets'][spec['asset']]['architecture']=='aarch64':
        from ctflab_generation_store import regular
        firmware = profile['firmware'][node]
        code = regular(firmware['code']) if verify_firmware else Path(firmware['code'])
        require('nvram' in paths and (not verify_firmware or digest(code)==firmware['sha256']), 'identity-unknown')
        args = [profile['binary'],'-no-user-config','-serial','none','-parallel','none','-name',name,
            '-machine','virt','-accel','hvf','-cpu','host','-smp',str(spec['cpus']),'-m',str(spec['memory_mb']),
            '-nodefaults','-display','none','-monitor','none',
            '-drive',f'if=pflash,format=raw,unit=0,file={str(code).replace(chr(44),chr(44)*2)},readonly=on',
            '-drive',f'if=pflash,format=raw,unit=1,file={str(paths["nvram"]).replace(chr(44),chr(44)*2)}',
            '-drive',f'file={disk},format=qcow2,if=virtio','-boot','c',
            '-device','virtio-gpu-pci','-device','ramfb','-device','qemu-xhci','-device','usb-kbd','-device','usb-tablet']
    elif profile.get('host') == 'darwin-arm64':
        args[0] = node_binary(plan,node,profile)
        args[args.index('-accel')+1] = 'tcg'
        args += ['-cpu','max']
    from ctflab_vmgenid import checked
    generation_id = checked(generation_id,plan,node)
    if generation_id is not None:args += ['-device','vmgenid,guid='+generation_id['guid']]
    args += network_arguments(plan, node, profile['networks'])
    args += server_arguments(attempt/'tls', plan['instance_uuid'])
    args += ['-chardev', f'socket,id=control,host=127.0.0.1,port={ports["qmp"]},server=on,wait=off,ipv4=on,tls-creds=ctflab-tls,tls-authz=ctflab-client',
             '-mon', 'chardev=control,mode=control',
             '-vnc', f'127.0.0.1:{ports["vnc"]-5900},tls-creds=ctflab-tls,tls-authz=ctflab-client']
    if node in profile.get('agents',{}):
        from ctflab_guest_policy import vm_uuid
        port=profile['agents'][node]['port']
        args+=['-uuid',vm_uuid(plan,node),'-device','virtio-serial-pci,id=ctflab-agent-bus',
               '-chardev',f'socket,id=guestagent,host=127.0.0.1,port={port},server=on,wait=off,ipv4=on,tls-creds=ctflab-tls,tls-authz=ctflab-client',
               '-device','virtserialport,bus=ctflab-agent-bus.0,chardev=guestagent,name=org.ctflab.agent.0']
    return args, name


def verify_disk(binary, disk):
    """使用同一固定运行时的 qemu-img 只读核验，不接受外部 backing/data 文件。"""
    image_tool = Path(binary).with_name('qemu-img' if sys.platform in ('linux','darwin') else 'qemu-img.exe')
    reply = subprocess.run([str(image_tool), 'info', '--output=json', '--backing-chain', str(disk)],
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=True)
    require(len(reply.stdout) <= 1024*1024, 'state-conflict')
    value = json.loads(reply.stdout)
    require(type(value) is list and len(value) == 1 and value[0].get('format') == 'qcow2', 'capability-unverified')
    def external(item):
        if isinstance(item, dict):
            return any(k in ('backing-filename', 'full-backing-filename', 'data-file') or external(v)
                       for k, v in item.items())
        return isinstance(item, list) and any(external(v) for v in item)
    require(not external(value), 'capability-unverified')


class QemuDriver:
    def __init__(self, store, profile, *, timeout=30):
        require(type(timeout) in (int, float) and 0 < timeout <= 120)
        self.store, self.profile, self.timeout = store, profile, timeout
        from ctflab_server_storage import check_instance
        check_instance(store.root)
        validate_profile(store.plan(1), profile)

    def location(self, plan, node, paths):
        from ctflab_server_storage import check_instance
        check_instance(self.store.root)
        require(plan == self.store.plan(plan['generation']), 'identity-unknown')
        require(paths == self.store.node_paths(plan['generation'], node), 'identity-unknown')
        return paths['disk'].parent/'runtime'

    def latest(self, root):
        if not root.exists():
            return None
        guard(root)
        entries = sorted(root.iterdir())
        require(all(p.is_dir() and len(p.name) == 8 and p.name.isdigit() for p in entries), 'identity-unknown')
        require([p.name for p in entries] == [f'{i:08d}' for i in range(1, len(entries)+1)], 'identity-unknown')
        return entries[-1] if entries else None

    def binding(self, plan, node, paths, attempt):
        spec = read(attempt/'launch.json')
        if self.profile.get('agents') or 'runtime_profile_sha256' in spec:
            require(spec.get('runtime_profile_sha256')==profile_sha(self.profile),'identity-unknown')
        require(spec['plan_sha256'] == plan['plan_sha256'] and spec['node'] == node
                and spec['disk'] == str(paths['disk']), 'identity-unknown')
        info = paths['disk'].stat()
        require(spec['disk_identity'] == [info.st_dev, info.st_ino], 'identity-unknown')
        binding = read(attempt/'binding.json')
        require(binding['launch_sha256'] == digest(attempt/'launch.json'), 'identity-unknown')
        identity = ProcessIdentity(**binding['identity'])
        require(Path(identity.image_path) == Path(spec['binary']), 'identity-unknown')
        from ctflab_vmgenid import declaration
        generation_id=declaration(self.store,plan,node)
        require(spec.get('vmgenid')==generation_id,'identity-unknown')
        args, name = arguments(plan, node, paths, self.profile, attempt, spec.get('certificates'), verify_firmware=False,generation_id=generation_id)
        require(spec.get('argv') == args and spec.get('name') == name
                and spec['binary'] == node_binary(plan,node,self.profile)
                and spec['qmp'] == self.profile['nodes'][node]['qmp'], 'identity-unknown')
        if 'resource_limits' in self.profile:
            from ctflab_cgroup import validate_declaration
            group=validate_declaration(spec.get('cgroup'));limits=self.profile['resource_limits']
            require(group['root']==limits['cgroup_root'] and group['limits']==limits['nodes'][node]
                    and group['instance_uuid']==plan['instance_uuid'] and group['generation']==plan['generation'] and group['node']==node
                    and group['group']=='ctflab-'+plan['instance_uuid']+'-g'+str(plan['generation'])+'-'+node+'-a'+attempt.name,'identity-unknown')
        else:require('cgroup' not in spec,'identity-unknown')
        if 'windows_limits' in self.profile:
            from ctflab_windows_limits import declaration as windows_declaration
            require(spec.get('windows_job')==windows_declaration(self.profile,plan,node,attempt.name),'identity-unknown')
        else:require('windows_job' not in spec,'identity-unknown')
        require(spec.get('recoverable_logs',False)==self.profile.get('recoverable_logs',False),'identity-unknown')
        if spec.get('recoverable_logs'):
            require(spec.get('log_scope')=={'instance_uuid':plan['instance_uuid'],'generation':plan['generation'],
                'node':node,'attempt':attempt.name},'identity-unknown')
        require(spec.get('storage_boundary')==self.profile.get('storage_boundary'),'identity-unknown')
        require(spec.get('macos_storage')==self.profile.get('macos_storage'),'identity-unknown')
        require(spec.get('windows_storage')==self.profile.get('windows_storage'),'identity-unknown')
        if self.profile.get('host') == 'darwin-arm64' and 'nvram' in paths:
            nvram = guard(paths['nvram']).stat(); firmware = self.profile['firmware'][node]
            require(spec.get('nvram') == str(paths['nvram']) and spec.get('nvram_identity') == [nvram.st_dev,nvram.st_ino]
                    and spec.get('firmware')==firmware, 'identity-unknown')
        return spec, binding, identity

    def observe(self, plan, node, paths):
        attempt = self.latest(self.location(plan, node, paths))
        state = 'stopped'
        if attempt is not None:
            spec, binding, expected = self.binding(plan, node, paths, attempt)
            exits = [attempt/n for n in ('exit.json', 'observer-exit.json') if (attempt/n).exists()]
            for session in observer_sessions(attempt):
                if (session/'exit.json').exists():
                    observer_binding(attempt, session)
                    value = read(session/'exit.json')
                    require(value.get('binding_sha256') == digest(attempt/'binding.json'), 'identity-unknown')
                    exits.append(session/'exit.json')
            if exits:
                for path in exits:
                    value = read(path)
                    known_exit=(type(value.get('returncode')) is int or sys.platform in ('linux','darwin')
                                and value.get('returncode') is None and value.get('source')==('retained-darwin-kqueue' if sys.platform=='darwin' else 'retained-linux-pidfd')
                                and value.get('exit_code_known') is False)
                    require(value['identity'] == binding['identity'] and value['state'] == 'exited'
                            and known_exit, 'identity-unknown')
            else:
                require(compare_identity(expected, native_observe(expected.pid)) == 'running', 'identity-unknown')
                if 'storage_boundary' in spec:
                    from ctflab_storage_boundary import verify as verify_storage
                    verify_storage(spec['storage_boundary'],root=self.store.root,instance=plan['instance_uuid'],pid=expected.pid)
                if 'macos_storage' in spec:
                    from ctflab_storage_boundary import check_mac_profile
                    check_mac_profile(spec,self.store.root)
                if 'windows_storage' in spec:
                    from ctflab_storage_boundary import check_windows_profile
                    check_windows_profile(spec,self.store.root,instance=plan['instance_uuid'])
                if 'cgroup' in spec:
                    from ctflab_cgroup import verify as verify_limits
                    verify_limits(spec['cgroup'],read(attempt/'cgroup.json'),expected.pid)
                if 'windows_job' in spec:
                    from ctflab_windows_limits import verify as verify_windows_limits
                    verify_windows_limits(spec['windows_job'],read(attempt/'windows-job.json'),expected)
                with self.connection(spec, expected, attempt) as client:
                    reply = client.command('query-status')
                    require(type(reply.get('return')) is dict, 'identity-unknown')
                state = 'process-running'
        return NodeObservation(plan['instance_uuid'], plan['generation'], node, 'verified', state)

    def supervision(self, plan, node, paths):
        attempt = self.latest(self.location(plan, node, paths))
        if attempt is None: return {'state': 'not-started', 'observer': 'unknown', 'automatic_replay': False}
        self.binding(plan, node, paths, attempt)
        states = []
        if (attempt/'observer-ready.json').exists():
            try:
                ready = read(attempt/'observer-ready.json')
                require(ready['identity'] == read(attempt/'binding.json')['identity'], 'identity-unknown')
                require(ready['observer']['pid'] != ready['identity']['pid'], 'identity-unknown')
                states.append(identity_status(ready['observer']))
            except (OSError, ValueError, RuntimeError, KeyError, TypeError): states.append('unknown')
        for session in observer_sessions(attempt):
            try:
                observer_binding(attempt, session)
                states.append(identity_status(read(session/'ready.json')['observer']))
            except (OSError, ValueError, RuntimeError, KeyError, TypeError): states.append('unknown')
        logs={'kind':'legacy-anonymous','rearm_allowed':False,'receiver':'unknown'}
        if self.profile.get('recoverable_logs'):
            from ctflab_recoverable_log import status as log_status
            try:logs=log_status(attempt)
            except (OSError,ValueError,RuntimeError,KeyError,TypeError):
                logs={'kind':'posix-fifo-v1','rearm_allowed':False,'receiver':'unknown'}
        return {'state': 'observed', 'observer': 'running' if 'running' in states else 'unknown',
                'sessions': len(states), 'logs':logs,'automatic_replay': False, 'pipe_takeover': False}

    def rearm_observer(self, plan, node, paths, operation):
        """只显式补建持有内核对象的退出观测器；不重放控制命令。"""
        from ctflab_contract import uuid_text
        uuid_text(operation)
        attempt = self.latest(self.location(plan, node, paths))
        require(attempt is not None, 'identity-unknown')
        with command_lock(attempt):
            self.binding(plan, node, paths, attempt)
            sessions = attempt/'observers'
            target = sessions/operation
            if target.exists():
                observer_binding(attempt, target)
                return observer_result(attempt, target)
            require(self.observe(plan, node, paths).state == 'process-running', 'state-conflict')
            require(self.supervision(plan, node, paths)['observer'] != 'running', 'resource-busy')
            require(len(observer_sessions(attempt)) < 16, 'resource-busy')
            if not sessions.exists(): private_directory(sessions)
            else: guard(sessions)
            private_directory(target)
            record(target/'intent.json', {'operation_id': operation,
                   'binding_sha256': digest(attempt/'binding.json'), 'automatic_replay': False})
            try: spawn_worker('observe-exit', attempt, session=operation)
            except OSError: return {'state': 'unknown', 'automatic_replay': False, 'qemu_changed': False}
        deadline = time.monotonic()+self.timeout
        while time.monotonic() < deadline:
            if (target/'ready.json').exists():
                observer_binding(attempt, target)
                return observer_result(attempt, target)
            time.sleep(.1)
        return {'state': 'unknown', 'automatic_replay': False, 'qemu_changed': False}

    def rearm_log(self, plan, node, paths, operation):
        """核验原生身份后只重接已登记FIFO；不依赖可能被日志背压阻塞的QMP。"""
        from ctflab_contract import uuid_text
        from ctflab_recoverable_log import spawn as spawn_log, channel
        uuid_text(operation)
        attempt=self.latest(self.location(plan,node,paths))
        require(attempt is not None and self.profile.get('recoverable_logs') is True,'capability-unverified')
        with command_lock(attempt):
            spec,bound,expected=self.binding(plan,node,paths,attempt)
            require(compare_identity(expected,native_observe(expected.pid))=='running','identity-unknown')
            channel(attempt)
            result=spawn_log(attempt,operation)
            result.pop('process',None)
            return dict(result,qemu_changed=False,capture_complete=False)

    def connection(self, spec, expected, attempt):
        require(compare_identity(expected, native_observe(expected.pid)) == 'running', 'identity-unknown')
        client = QMPClient(spec['qmp'], attempt/'tls', spec['certificates'], spec['name'])
        try:
            require(compare_identity(expected, native_observe(expected.pid)) == 'running', 'identity-unknown')
            if spec.get('vmgenid') is not None:
                from ctflab_vmgenid import verify_qmp
                verify_qmp(client,spec['vmgenid'])
            return client
        except BaseException:
            client.close()
            raise

    def certificates(self, plan, node, paths):
        attempt = self.latest(self.location(plan, node, paths))
        if attempt is None: return {'state': 'not-provisioned'}
        spec, _, _ = self.binding(plan, node, paths, attempt)
        result = certificate_status(attempt/'tls', spec['certificates'])
        return {'state': result['state'], 'valid': result['valid'],
                'remaining_seconds': min(v['remaining_seconds'] for v in result['certificates'].values()),
                'renewal': result['renewal'], 'automatic_stop': False}

    def display(self, plan, node, paths):
        from ctflab_rfb_tls import RFBClient
        attempt = self.latest(self.location(plan, node, paths))
        require(attempt is not None, 'identity-unknown')
        spec, binding, expected = self.binding(plan, node, paths, attempt)
        with self.connection(spec, expected, attempt):
            pass
        display = RFBClient(self.profile['nodes'][node]['vnc'], attempt/'tls', spec['certificates'])
        try:
            require(compare_identity(expected, native_observe(expected.pid)) == 'running', 'identity-unknown')
            return display
        except BaseException:
            display.close()
            raise

    def guest_agent(self,plan,node,paths):
        from ctflab_guest_channel import GuestClient
        require(node in self.profile.get('agents',{}),'capability-unverified')
        attempt=self.latest(self.location(plan,node,paths));require(attempt is not None,'identity-unknown')
        spec,binding,expected=self.binding(plan,node,paths,attempt)
        with self.connection(spec,expected,attempt):pass
        entry=self.profile['agents'][node]
        client=GuestClient(entry['port'],attempt/'tls',spec['certificates'],plan,node,entry)
        try:
            require(compare_identity(expected,native_observe(expected.pid))=='running','identity-unknown')
            return client
        except BaseException:client.close();raise

    def guest_command(self,plan,node,paths,action,operation,*,target_operation_id=None,expected_sha256=None):
        require(str(uuid.UUID(operation))==operation)
        require(action in ('preparation-inspect','preparation-resume','status','recover','operation-status','network-apply','services-start','services-stop',
                          'containers-prepare','containers-start','containers-stop','analysis-run'))
        extra={}
        if action in ('preparation-inspect','preparation-resume'):
            require(str(uuid.UUID(target_operation_id))==target_operation_id);extra['target_operation_id']=target_operation_id
            if action=='preparation-resume':
                require(type(expected_sha256) is str and re.fullmatch('[0-9a-f]{64}',expected_sha256));extra['expected_sha256']=expected_sha256
            else:require(expected_sha256 is None)
        else:require(target_operation_id is None and expected_sha256 is None)
        attempt=self.latest(self.location(plan,node,paths));require(attempt is not None,'identity-unknown')
        with command_lock(attempt):
            read_only=action in ('status','recover','operation-status')
            intent=attempt/('guest-'+operation+'.intent.json');result=attempt/('guest-'+operation+'.result.json')
            if not read_only and intent.exists():
                prior=read(intent);require(prior['action']==action and {k:prior.get(k) for k in ('target_operation_id','expected_sha256') if k in prior}==extra,'idempotency-conflict')
                return read(result) if result.exists() else {'state':'unknown','automatic_replay':False}
            with self.guest_agent(plan,node,paths) as client:
                if action in ('preparation-inspect','preparation-resume'):require(action in client.capabilities,'capability-unverified')
                if read_only:return client.command(action,operation)
                record(intent,dict(extra,**{'action':action,'operation_id':operation,'plan_sha256':plan['plan_sha256'],
                               'policy_sha256':client.policy['policy_sha256'],'automatic_replay':False}))
                try:value=client.command(action,operation,**extra)
                except (OSError,ValueError,RuntimeError):value={'state':'unknown','automatic_replay':False}
                record(result,value)
                return value

    def start(self, plan, node, paths, parameters):
        mac = self.profile.get('host') == 'darwin-arm64'
        if 'windows_storage' in self.profile:require(os.name=='nt','unsupported-platform')
        if 'windows_limits' in self.profile:require(os.name=='nt','unsupported-platform')
        require((mac and sys.platform=='darwin' and platform.machine().lower() in ('arm64','aarch64')) or
                (not mac and (os.name=='nt' or sys.platform=='linux')), 'capability-unverified')
        require(type(parameters) is dict and set(parameters)=={'display','allow_emulation'} and parameters['display']=='headless'
                and type(parameters['allow_emulation']) is bool, 'capability-unverified')
        needs_emulation = mac and any(a['architecture']=='x86_64' for a in plan['manifest']['assets'].values())
        require(parameters['allow_emulation'] is needs_emulation, 'capability-unverified')
        if 'storage_boundary' in self.profile:
            from ctflab_storage_boundary import verify as verify_storage
            verify_storage(self.profile['storage_boundary'],root=self.store.root,instance=plan['instance_uuid'])
        if 'macos_storage' in self.profile:
            from ctflab_storage_boundary import check_mac_profile
            require(check_mac_profile(self.profile,self.store.root)['available_bytes']>0,'storage-insufficient')
        if 'windows_storage' in self.profile:
            from ctflab_storage_boundary import check_windows_profile
            require(check_windows_profile(self.profile,self.store.root,instance=plan['instance_uuid'])['available_bytes']>0,'storage-insufficient')
        if 'resource_limits' in self.profile:
            from ctflab_cgroup import preflight as limit_preflight
            limit_preflight(self.profile['resource_limits']['cgroup_root'])
            cap=self.profile['resource_limits']['nodes'][node].get('disk_max_bytes')
            if cap is not None:require(paths['disk'].stat().st_size<=cap,'storage-insufficient')
        require(self.observe(plan, node, paths).state == 'stopped', 'state-conflict')
        require(hypervisor_capability().get('hypervisor_present') is True, 'capability-unverified')
        reference = read_json(Path(self.profile['inventory']), lambda p: None, 8*1024**2)
        executable='qemu-system-aarch64' if mac else 'qemu-system-x86_64' if sys.platform=='linux' else 'qemu-system-x86_64.exe'
        require(Path(self.profile['binary']).name==executable,'capability-unverified')
        runtime_root=Path(self.profile['runtime_root']) if mac else Path(self.profile['binary']).parent
        inventory_executable='bin/qemu-system-aarch64' if mac else executable
        require(compare(reference, inventory(runtime_root,executable=inventory_executable))['matches'], 'state-conflict')
        binary = node_binary(plan,node,self.profile)
        verify_disk(binary, paths['disk'])
        source = self.store.config['assets'][plan['manifest']['nodes'][node]['asset']]
        require(digest(source['path']) == source['sha256'], 'state-conflict')
        root = self.location(plan, node, paths)
        if not root.exists():
            private_directory(root)
        prior = self.latest(root)
        attempt = root/f'{int(prior.name)+1 if prior else 1:08d}'
        private_directory(attempt)
        certificates = provision(attempt/'tls', plan['instance_uuid'])
        require(certificate_status(attempt/'tls', certificates)['valid'], 'state-conflict')
        from ctflab_vmgenid import declaration
        generation_id=declaration(self.store,plan,node)
        args, name = arguments(plan, node, paths, self.profile, attempt, certificates,generation_id=generation_id)
        info = paths['disk'].stat()
        resource={}
        if generation_id is not None:resource['vmgenid']=generation_id
        if self.profile.get('recoverable_logs'):
            resource.update(recoverable_logs=True,log_scope={'instance_uuid':plan['instance_uuid'],
                'generation':plan['generation'],'node':node,'attempt':attempt.name})
        if 'macos_storage' in self.profile:resource['macos_storage']=self.profile['macos_storage']
        if mac and 'nvram' in paths:
            nvram=guard(paths['nvram']).stat()
            resource.update(nvram=str(paths['nvram']),nvram_identity=[nvram.st_dev,nvram.st_ino],
                            firmware=self.profile['firmware'][node])
        if 'storage_boundary' in self.profile:resource['storage_boundary']=self.profile['storage_boundary']
        if 'windows_storage' in self.profile:resource['windows_storage']=self.profile['windows_storage']
        if 'resource_limits' in self.profile:
            from ctflab_cgroup import declaration
            resource['cgroup']=declaration(self.profile,plan,node,attempt.name)
        if 'windows_limits' in self.profile:
            from ctflab_windows_limits import declaration as windows_declaration
            resource['windows_job']=windows_declaration(self.profile,plan,node,attempt.name)
        from ctflab_server_storage import launch_binding
        pool_binding=launch_binding(self.store.root)
        if pool_binding is not None:resource['server_storage']=pool_binding
        record(attempt/'launch.json', dict(resource,**{'schema': 1, 'plan_sha256': plan['plan_sha256'], 'node': node,
               'runtime_profile_sha256':profile_sha(self.profile),
               'disk': str(paths['disk']), 'disk_identity': [info.st_dev, info.st_ino],
               'binary': binary, 'binary_sha256': digest(binary),
               'argv': args, 'name': name, 'qmp': self.profile['nodes'][node]['qmp'],
               'certificates': certificates}))
        record(attempt/'control.lock', {})
        spawn_worker('worker', attempt)
        deadline = time.monotonic()+self.timeout
        while time.monotonic() < deadline:
            if (attempt/'binding.json').exists() and (attempt/'observer-ready.json').exists():
                try:
                    require(read(attempt/'observer-ready.json')['identity'] == read(attempt/'binding.json')['identity'], 'identity-unknown')
                    require(self.observe(plan, node, paths).state == 'process-running', 'identity-unknown')
                    return
                except (OSError, ValueError, NativeError):
                    pass
            time.sleep(.1)
        require(False, 'identity-unknown')

    def stop(self, plan, node, paths):
        attempt = self.latest(self.location(plan, node, paths))
        require(attempt is not None, 'identity-unknown')
        spec, binding, expected = self.binding(plan, node, paths, attempt)
        with command_lock(attempt):
            require(not (attempt/'stop.intent.json').exists(), 'identity-unknown')
            with self.connection(spec, expected, attempt) as client:
                record(attempt/'stop.intent.json', {'action': 'system_powerdown', 'automatic_replay': False})
                reply = client.command('system_powerdown')
                record(attempt/'stop.result.json', {'acknowledged': 'return' in reply, 'automatic_replay': False})
                require('return' in reply, 'identity-unknown')
        deadline = time.monotonic()+self.timeout
        while time.monotonic() < deadline:
            try:
                if self.observe(plan, node, paths).state == 'stopped':
                    return
            except (OSError, ValueError, NativeError):
                # 等待已发送命令的退出证据；未知期间不再发命令。
                pass
            time.sleep(.1)
        require(False, 'stop-timeout')

    def supervisor_fault(self, plan, node, paths):
        from ctflab_supervisor_fault import request_and_wait
        require(os.name=='nt','capability-unverified')
        attempt = self.latest(self.location(plan, node, paths))
        require(attempt is not None, 'identity-unknown')
        with command_lock(attempt):
            require(not (attempt/'stop.intent.json').exists(), 'state-conflict')
            spec, binding, expected = self.binding(plan, node, paths, attempt)
            with self.connection(spec, expected, attempt) as client:
                require('return' in client.command('query-status'), 'identity-unknown')
            return request_and_wait(attempt, read=read, record=record, observe=native_observe, native=Win32())


def identity_status(value):
    try:
        expected = ProcessIdentity(**value)
        require(type(expected.pid) is int and expected.pid > 0 and type(expected.creation_ticks) is int
                and expected.creation_ticks >= 0 and type(expected.image_path) is str
                and bool(expected.image_path) and expected.state in ('running', 'exited'), 'identity-unknown')
        return compare_identity(expected, native_observe(expected.pid))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError): return 'unknown'


def observer_sessions(root):
    from itertools import islice
    from ctflab_contract import uuid_text
    parent = root/'observers'
    if not parent.exists(): return []
    guard(parent)
    entries = list(islice(parent.iterdir(), 17))
    require(len(entries) <= 16, 'resource-busy')
    for path in entries:
        uuid_text(path.name); guard(path); require(path.is_dir(), 'identity-unknown')
    return entries


def observer_binding(root, session):
    from ctflab_contract import uuid_text
    uuid_text(session.name); guard(session)
    require(session.parent == root/'observers', 'identity-unknown')
    intent = read(session/'intent.json')
    require(intent == {'operation_id': session.name, 'binding_sha256': digest(root/'binding.json'),
                       'automatic_replay': False}, 'identity-unknown')
    if (session/'ready.json').exists():
        ready = read(session/'ready.json')
        require(ready['binding_sha256'] == intent['binding_sha256'] and
                ready['identity'] == read(root/'binding.json')['identity'] and
                ready['observer']['pid'] != ready['identity']['pid'], 'identity-unknown')
    if (session/'exit.json').exists(): require((session/'ready.json').exists(), 'identity-unknown')
    return intent


def observer_result(root, session):
    observer_binding(root, session)
    state = 'unknown'
    if (session/'exit.json').exists():
        value = read(session/'exit.json')
        known = type(value.get('returncode')) is int or (sys.platform in ('linux','darwin') and
            value.get('returncode') is None and value.get('source') == ('retained-darwin-kqueue' if sys.platform=='darwin' else 'retained-linux-pidfd') and
            value.get('exit_code_known') is False)
        require(value['state'] == 'exited' and known and
                value['identity'] == read(root/'binding.json')['identity'] and
                value['binding_sha256'] == digest(root/'binding.json'), 'identity-unknown')
        return {'state': 'observer-exited', 'automatic_replay': False, 'qemu_changed': False,
                'graceful_stop_verified': False}
    if (session/'ready.json').exists():
        ready = read(session/'ready.json')
        if identity_status(ready['observer']) == 'running': state = 'observer-ready'
    return {'state': state, 'automatic_replay': False, 'qemu_changed': False,
            'graceful_stop_verified': False}


def spawn_worker(action, root, *, session=None):
    from ctflab_bounded_log import spawn
    log_root = root
    if session is not None:
        from ctflab_contract import uuid_text
        uuid_text(session); require(action == 'observe-exit')
        log_root = root/'observers'/session
        observer_binding(root, log_root)
    receiver = spawn(log_root, action+'-console')
    try:
        args = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), action, '--run', str(root)]
        if session is not None:
            from ctflab_contract import uuid_text
            uuid_text(session); require(action == 'observe-exit')
            args += ['--observer-session', session]
        return subprocess.Popen(args,
            stdin=subprocess.DEVNULL, stdout=receiver.stdin, stderr=receiver.stdin, close_fds=True,
            **spawn_options())
    finally: receiver.stdin.close()


def observe_exit(root, session=None, *, native=None):
    """独立进程保留经核验的 Windows 句柄；不发送任何 VM 命令。"""
    binding = read(root/'binding.json')
    expected = ProcessIdentity(**binding['identity'])
    destination = root if session is None else root/'observers'/session
    if session is not None: observer_binding(root, destination)
    if native is not None: pass
    elif sys.platform=='darwin':
        from ctflab_darwin_native import DarwinObserver
        native=DarwinObserver()
    elif sys.platform=='linux':
        from ctflab_linux_native import LinuxObserver
        native=LinuxObserver()
    else:native=Win32()
    with native.retained(expected) as handle:
        extra = {} if session is None else {'binding_sha256': digest(root/'binding.json')}
        if session is not None: observer_binding(root, destination)
        record(destination/('observer-ready.json' if session is None else 'ready.json'),
               dict(extra, identity=asdict(expected), observer=asdict(native.observe(os.getpid()))))
        while True:
            code = native.wait_exit(handle)
            if code is not None:
                evidence=code if type(code) is dict else {'state':'exited','returncode':code,'source':'retained-native-handle'}
                record(destination/('observer-exit.json' if session is None else 'exit.json'),
                       dict(evidence,**extra,identity=asdict(expected),graceful_stop_verified=False))
                return


def worker(root):
    with command_lock(root):
        require(not (root/'start.intent.json').exists(), 'identity-unknown')
        spec = read(root/'launch.json')
        from ctflab_server_storage import verify_launch
        verify_launch(spec,root)
        from ctflab_vmgenid import verify_launch as verify_vmgenid_launch
        verify_vmgenid_launch(spec,root)
        require(digest(spec['binary']) == spec['binary_sha256'] and fingerprints(root/'tls') == spec['certificates'], 'state-conflict')
        if 'nvram' in spec:
            nvram=guard(Path(spec['nvram'])).stat();firmware=spec['firmware']
            require([nvram.st_dev,nvram.st_ino]==spec['nvram_identity'] and digest(firmware['code'])==firmware['sha256'], 'identity-unknown')
        if 'macos_storage' in spec:
            from ctflab_storage_boundary import check_mac_profile
            check_mac_profile(spec,root)
            require(Path(spec['macos_storage']['root']) in Path(spec['disk']).parents,'identity-unknown')
        if 'windows_storage' in spec:
            from ctflab_storage_boundary import check_windows_profile
            proof=check_windows_profile(spec,root)
            require(Path(spec['windows_storage']['root']) in Path(spec['disk']).parents,'identity-unknown')
            record(root/'storage.json',proof)
        info = guard(Path(spec['disk'])).stat()
        require([info.st_dev, info.st_ino] == spec['disk_identity'], 'identity-unknown')
        if 'storage_boundary' in spec:
            from ctflab_storage_boundary import verify as verify_storage
            proof=verify_storage(spec['storage_boundary'])
            require(Path(spec['storage_boundary']['root']) in root.parents
                and Path(spec['storage_boundary']['root']) in Path(spec['disk']).parents,'identity-unknown')
            record(root/'storage.json',proof)
        record(root/'worker.json', asdict(native_observe(os.getpid())))
        record(root/'start.intent.json', {'automatic_replay': False})
        if 'cgroup' in spec:
            from ctflab_cgroup import enter as enter_limits
            record(root/'cgroup.json',enter_limits(spec['cgroup']))
        if 'windows_job' in spec:
            from ctflab_windows_limits import enter as enter_windows_limits
            record(root/'windows-job.json',enter_windows_limits(spec['windows_job']))
        from ctflab_bounded_log import spawn
        output_fd=None;receiver=None
        if spec.get('recoverable_logs'):
            from ctflab_recoverable_log import initialize as initialize_log, spawn as spawn_log
            output_fd=initialize_log(root)
            try:
                result=spawn_log(root,str(uuid.uuid4()))
                receiver=result.get('process')
                require(result['state']=='log-receiver-requested','identity-unknown')
            except BaseException:
                os.close(output_fd);raise
        else:receiver=spawn(root,'qemu-stderr')
        try:
            options=spawn_options()
            if 'storage_boundary' in spec:verify_storage(spec['storage_boundary'])
            if 'macos_storage' in spec:check_mac_profile(spec,root)
            if 'windows_storage' in spec:check_windows_profile(spec,root)
            if 'disk_max_bytes' in spec.get('cgroup',{}).get('limits',{}):options['restore_signals']=False
            process = subprocess.Popen(spec['argv'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=output_fd if output_fd is not None else receiver.stdin, cwd=str(Path(spec['binary']).parent), close_fds=True,
                **options)
        finally:
            if output_fd is not None:os.close(output_fd)
            else:receiver.stdin.close()
        identity = native_observe(process.pid)
        record(root/'binding.json', {'identity': asdict(identity), 'launch_sha256': digest(root/'launch.json')})
        if 'windows_job' in spec:
            from ctflab_windows_limits import verify as verify_windows_limits
            verify_windows_limits(spec['windows_job'],read(root/'windows-job.json'),identity)
        try:
            spawn_worker('observe-exit', root)
        except OSError:
            record(root/'observer-failure.json', {'reason': 'observer-spawn-failed', 'process_may_be_running': True})
    from ctflab_supervisor_fault import wait
    code = wait(process, root, read=read, record=record, observe=native_observe)
    record(root/'exit.json', {'state': 'exited', 'identity': asdict(identity), 'returncode': code,
           'source': 'owned-process-wait', 'graceful_stop_verified': False})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    guest_actions=tuple('guest-'+a for a in ('preparation-inspect','preparation-resume','status','recover','operation-status','network-apply','services-start','services-stop',
                                           'containers-prepare','containers-start','containers-stop','analysis-run'))
    parser.add_argument('action', choices=('init', 'worker', 'observe-exit', 'status', 'certificate-status', 'supervision', 'rearm-observer', 'rearm-log', 'display', 'start', 'stop', 'recover', 'reset', 'prepare', 'supervisor-fault')+guest_actions)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--course-id', default='host')
    parser.add_argument('--baseline-id', default='host')
    parser.add_argument('--operation-id')
    parser.add_argument('--target-operation-id')
    parser.add_argument('--expected-sha256')
    parser.add_argument('--node')
    parser.add_argument('--observer-session')
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--assets', type=Path)
    parser.add_argument('--nvram', type=Path)
    args = parser.parse_args(argv)
    if args.action not in ('guest-preparation-inspect','guest-preparation-resume'):
        require(args.target_operation_id is None and args.expected_sha256 is None)
    if os.name != 'nt' and sys.platform not in ('linux','darwin'):
        print('当前平台不支持通用运行器；未启动进程。'); return 2
    root = args.run.absolute()
    if args.action == 'init':
        from ctflab_scenario_v2 import parse_manifest, instance_plan
        require(args.manifest is not None and args.assets is not None and args.profile is not None)
        manifest = parse_manifest(args.manifest.read_text(encoding='utf-8'))
        identity = str(uuid.uuid4())
        profile = validate_profile(instance_plan(manifest, identity), read(args.profile))
        require(not profile.get('firmware') or args.nvram is not None, 'capability-unverified')
        store = GenerationStore.create(root, manifest, identity, read(args.assets), read(args.nvram) if args.nvram else None)
        record(root/'runtime-profile.json', profile)
        print(json.dumps({'instance_uuid': identity, 'state': 'configured', 'runtime_verified': False}))
    elif args.action == 'worker':
        worker(root)
    elif args.action == 'observe-exit':
        observe_exit(root, args.observer_session)
    else:
        store = GenerationStore(root)
        profile = read(root/'runtime-profile.json')
        if args.profile is not None:
            require(read(args.profile) == profile, 'state-conflict')
        driver = QemuDriver(store, profile)
        coordinator = ScenarioCoordinator(store, course_id=args.course_id, baseline_id=args.baseline_id, driver=driver)
        generation = store.snapshot()['active_generation']
        if args.action in guest_actions:
            with store.locked():
                require(args.node in store.plan(generation)['manifest']['nodes'])
                require(args.action!='guest-operation-status' or args.operation_id is not None)
                result=driver.guest_command(store.plan(generation),args.node,store.node_paths(generation,args.node),
                                            args.action[6:],args.operation_id or str(uuid.uuid4()),
                                            **({'target_operation_id':args.target_operation_id,'expected_sha256':args.expected_sha256}
                                               if args.action in ('guest-preparation-inspect','guest-preparation-resume') else {}))
                print(json.dumps(result,ensure_ascii=False))
                if result.get('state')=='unknown':return 2
        elif args.action == 'supervisor-fault':
            with store.locked():
                require(args.node in store.plan(generation)['manifest']['nodes'])
                print(json.dumps(driver.supervisor_fault(store.plan(generation), args.node, store.node_paths(generation, args.node))))
        elif args.action == 'display':
            from ctflab_rfb_tls import show
            require(args.node in store.plan(generation)['manifest']['nodes'])
            show(lambda: driver.display(store.plan(generation), args.node, store.node_paths(generation, args.node)))
        elif args.action in ('supervision', 'rearm-observer','rearm-log'):
            with store.locked():
                plan = store.plan(generation)
                require(args.node in plan['manifest']['nodes'])
                if args.action=='rearm-log':require(args.operation_id is not None)
                rearm=driver.rearm_log if args.action=='rearm-log' else driver.rearm_observer
                print(json.dumps(driver.supervision(plan, args.node, store.node_paths(generation, args.node))
                    if args.action == 'supervision' else rearm(plan, args.node,
                        store.node_paths(generation, args.node), args.operation_id or str(uuid.uuid4()))))
        elif args.action == 'certificate-status':
            with store.locked():
                plan = store.plan(generation)
                require(args.node in plan['manifest']['nodes'])
                attempt = driver.latest(driver.location(plan, args.node, store.node_paths(generation, args.node)))
                require(attempt is not None, 'state-conflict')
                spec, _, _ = driver.binding(plan, args.node, store.node_paths(generation, args.node), attempt)
                print(canonical(certificate_status(attempt/'tls', spec['certificates'])))
        elif args.action == 'status':
            values = coordinator.observations(generation)
            print(json.dumps({k: asdict(v) for k, v in values.items()}, ensure_ascii=False))
        else:
            from ctflab_local_service import OperationContext
            parameters = {'prepare': {'course_id': args.course_id, 'baseline_id': args.baseline_id},
                          'reset': {'baseline_id': args.baseline_id},
                          'start': {'display': 'headless', 'allow_emulation': False}, 'stop': {}, 'recover': {}}
            context = OperationContext(store.config['instance_uuid'], args.operation_id or str(uuid.uuid4()),
                                       generation, lambda: False)
            outcome = coordinator.execute({'operation': args.action, 'parameters': parameters[args.action]}, context)
            print(json.dumps(asdict(outcome), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
