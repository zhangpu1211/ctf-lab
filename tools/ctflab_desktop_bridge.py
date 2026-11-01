"""桌面薄壳的本地白名单桥接；契约后台进程与显示窗口独立于管理窗口。"""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import platform
import socket
import sqlite3
import subprocess
import sys
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from ctflab_contract import MAX_MESSAGE_BYTES, ContractError, canonical, require, uuid_text, integer
from ctflab_local_adapter import process_actor, failure
from ctflab_local_service import LocalService
from ctflab_generation_store import GenerationStore, private_directory
from ctflab_tls_endpoint import guard
from ctflab_scenario_coordinator import ScenarioCoordinator
from ctflab_qemu_driver import QemuDriver, read, record, validate_profile, runtime_dependencies
from ctflab_topology import projection


def sampled_observations(raw, instance, generation, nodes, started, finished):
    """逐节点核对原始绑定，不把外部观测重新盖成本次实例/代次。"""
    result = {}
    for node in nodes:
        item = raw.get(node) if type(raw) is dict else None
        unknown = {'instance_uuid': instance, 'generation': generation, 'node': node,
                   'identity': 'unknown', 'state': 'unknown'}
        result[node] = unknown
        if type(item) is not dict:
            continue
        try:
            require(item.get('instance_uuid') == instance and type(item.get('generation')) is int
                    and item['generation'] == generation and item.get('node') == node
                    and item.get('identity') == 'verified' and item.get('state') in ('stopped', 'process-running'),
                    'identity-unknown')
            stamp = datetime.fromisoformat(item['observed_at'].replace('Z', '+00:00'))
            require(stamp.tzinfo is not None and started <= stamp <= finished, 'identity-unknown')
        except (ValueError, RuntimeError, KeyError, TypeError, AttributeError):
            continue
        result[node] = dict(unknown, identity='verified', state=item['state'], observed_at=item['observed_at'])
    return result


def backend(root):
    from ctflab_server_storage import check_instance
    check_instance(root)
    store = GenerationStore(root)
    return ScenarioCoordinator(store, course_id='host', baseline_id='host',
                               driver=QemuDriver(store, read(root/'runtime-profile.json')))


def launch(root, action, *, operation=None, node=None, session=None):
    from ctflab_server_storage import check_instance
    check_instance(root)
    require(action in ('execute', 'display-worker', 'external-relay'))
    args = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), action, '--run', str(root)]
    if operation is not None:
        uuid_text(operation); args += ['--operation', operation]
    if node is not None:
        from ctflab_scenario_v2 import identifier
        identifier(node); args += ['--node', node]
    if session is not None:
        uuid_text(session); args += ['--session', session]
    flags = {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    # 每次创建独立日志；不向UI返回宿主路径或原始堆栈。
    from ctflab_bounded_log import spawn
    logs = root/('desktop-'+str(uuid.uuid4()))
    private_directory(logs)
    receiver = spawn(logs, 'desktop-'+action)
    try:
        return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=receiver.stdin, stderr=receiver.stdin, close_fds=True, **flags)
    finally: receiver.stdin.close()


def configure(root, value):
    """仅导入用户选择的宿主配置；不执行课程脚本，也不启动节点。"""
    from ctflab_scenario_v2 import parse_manifest, instance_plan, MAX_BYTES as MANIFEST_MAX_BYTES
    required = {'action', 'manifest', 'assets', 'profile'}
    require(required <= set(value) <= required | {'nvram','instance_uuid'})
    path = Path(value['manifest']); require(path.is_absolute())
    with path.open('rb') as stream: raw = stream.read(MANIFEST_MAX_BYTES+1)
    require(len(raw)<=MANIFEST_MAX_BYTES)
    manifest = parse_manifest(raw.decode('utf-8'))
    instance = value['instance_uuid'] if 'instance_uuid' in value else str(uuid.uuid4()); uuid_text(instance)
    def mapping(v):
        if type(v) is dict:return v
        require(type(v) is str and Path(v).is_absolute())
        return read(Path(v))
    profile = validate_profile(instance_plan(manifest, instance), mapping(value['profile']))
    nvram = None
    if 'nvram' in value:
        nvram = mapping(value['nvram'])
    require(not profile.get('firmware') or nvram is not None, 'capability-unverified')
    assets = mapping(value['assets'])
    if root.exists():
        # 显式固定UUID的配置重试可补齐缺失登记；不覆盖半写文件、改配置或选择代次。
        require('instance_uuid' in value, 'state-conflict')
        store = GenerationStore(root)
        with store.locked():
            snapshot = store.snapshot()
            require(snapshot['active_generation']==0 and not snapshot['generations'] and not snapshot['unresolved'], 'state-conflict')
            require(store.config['instance_uuid']==instance and store.config['manifest']==manifest, 'idempotency-conflict')
            require(type(assets) is dict and all(type(v) is str and Path(v).is_absolute() for v in assets.values()))
            require({k:str(Path(v)) for k,v in assets.items()}=={k:v['path'] for k,v in store.config['assets'].items()},'idempotency-conflict')
            require(type(nvram or {}) is dict and all(type(v) is str and Path(v).is_absolute() for v in (nvram or {}).values()))
            require({k:str(Path(v)) for k,v in (nvram or {}).items()}=={k:v['path'] for k,v in store.config['nvram'].items()},'idempotency-conflict')
            if (root/'runtime-profile.json').exists():require(read(root/'runtime-profile.json')==profile,'idempotency-conflict')
            else:record(root/'runtime-profile.json',profile)
            if (root/'desktop-contract').exists():LocalService(root/'desktop-contract')
            else:LocalService.create(root/'desktop-contract')
    else:
        store = GenerationStore.create(root, manifest, instance, assets, nvram)
        record(root/'runtime-profile.json', profile)
        LocalService.create(root/'desktop-contract')
    return {'state': 'configured', 'instance_uuid': store.config['instance_uuid'], 'runtime_verified': False}


def import_course(root,value):
    from ctflab_catalog import parse_catalog,select_variant,inspect_assets,MAX_BYTES
    from ctflab_scenario_v2 import instance_plan
    from ctflab_runtime_inventory import inventory,compare
    require(set(value)=={'action','catalog','course_id','variant_id','asset_root'})
    path=Path(value['catalog']);asset_root=Path(value['asset_root'])
    require(path.is_absolute() and asset_root.is_absolute())
    with path.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
    require(len(raw)<=MAX_BYTES)
    selection=select_variant(parse_catalog(raw.decode('utf-8')),value['course_id'],'x86_64',variant_id=value['variant_id'] or None)
    require(inspect_assets(selection,asset_root)['all_present_and_verified'],'state-conflict')
    runtime=Path(__file__).resolve().parent.parent
    binary=runtime/'qemu'/'qemu-system-x86_64.exe';reference=runtime/'qemu-inventory.json'
    from ctflab_windows_control import read_json
    require(compare(read_json(reference,lambda _:None,8*1024**2),inventory(binary.parent))['matches'],'state-conflict')
    manifest=selection['variant']['scenario'];instance=str(uuid.uuid4());plan=instance_plan(manifest,instance)
    # 空闲端口探测只是候选分配；真正启动仍须通过实例身份和TLS握手，绝不称为预留。
    reservations=[]
    try:
        from ctflab_qemu_driver import network_members
        members = {name: network_members(plan, name) for name in sorted(manifest['networks'])}
        # external槽位同批分配：声明了槽位的网段必须得到预留口，不能静默丢弃。
        external_networks = {name for name in members if isinstance(manifest['networks'][name].get('external'), dict)}
        for _ in range(2*len(manifest['nodes'])+sum(max(0,len(v)-1) for v in members.values())+len(external_networks)):
            probe=socket.socket();probe.bind(('127.0.0.1',0));reservations.append(probe)
        ports=[s.getsockname()[1] for s in reservations]
        profile={'binary':str(binary),'inventory':str(reference),
                 'nodes':{n:{'qmp':ports[2*i],'vnc':ports[2*i+1]} for i,n in enumerate(plan['start_order'])},
                 'networks':{}}
        remaining = iter(ports[2*len(manifest['nodes']):])
        for name, nodes in members.items():
            if name not in external_networks:
                profile['networks'][name] = (next(remaining) if len(nodes)==2 else
                                            {node:next(remaining) for node in nodes[1:]})
            elif len(nodes)==2:
                # 带槽位的二成员改走hub规划：直连格式无法携带external预留口。
                profile['networks'][name] = {nodes[1]:next(remaining),'external':next(remaining)}
            else:
                planned = {node:next(remaining) for node in nodes[1:]}
                planned['external']=next(remaining)
                profile['networks'][name] = planned
        validate_profile(plan,profile)
        assets={key:str(asset_root/relative) for key,relative in selection['variant']['assets'].items()}
        store=GenerationStore.create(root,manifest,instance,assets)
        record(root/'runtime-profile.json',profile)
        record(root/'course-selection.json',{'course_id':selection['course_id'],'variant_id':selection['variant_id'],
                'title':selection['title'],'entries':selection['entries'],'runtime_verified':False})
        LocalService.create(root/'desktop-contract')
    finally:
        for probe in reservations:probe.close()
    return {'state':'configured','instance_uuid':store.config['instance_uuid'],'runtime_verified':False}


def dispatch_pending(root, response, spawn):
    if response['result'] == 'accepted':
        try:
            record(root/('desktop-dispatch-'+response['operation_id']+'.json'), {'operation_id': response['operation_id']})
        except FileExistsError:
            return response
        try:
            spawn(root, 'execute', operation=response['operation_id'])
        except OSError:
            response = dict(response, result='unknown', state='recovery-required')
    return response


def guest_history(attempt,plan_sha256):
    """只读取当前启动的有界宿主记录；原unknown不代表来宾此刻仍未完成。"""
    from itertools import islice
    attempt=guard(Path(attempt));intents=list(islice(attempt.glob('guest-*.intent.json'),4097))
    require(len(intents)<=4096,'storage-insufficient');records=[];replies=[]
    for path in intents:
        item=read(path);uuid_text(item['operation_id'])
        require(path.name=='guest-'+item['operation_id']+'.intent.json' and item['plan_sha256']==plan_sha256,'identity-unknown')
        reply=path.with_name(path.name.replace('.intent.','.result.'))
        result=read(reply) if reply.exists() else None
        if result is not None:
            require(type(result) is dict and type(result.get('state')) is str,'identity-unknown')
            replies.append((reply.stat().st_mtime_ns,item['operation_id'],item,result))
        if item.get('action')=='containers-prepare' and (result is None or result['state']!='containers-prepared'):
            records.append((path.stat().st_mtime_ns,item['operation_id']))
    info={'preparation_records':[{'operation_id':op,'state':'original-result-unconfirmed','guest_rechecked':False}
          for _,op in sorted(records,reverse=True)[:16]]}
    if replies:
        _,_,intent,result=max(replies,key=lambda row:(row[0],row[1]))
        info.update(last_result=result,last_action=intent['action'],last_operation_id=intent['operation_id'])
    return info


def preparation_progress(store,service,actor):
    """读取历史检查点并核对当前请求引用；不检查或控制工作器进程。"""
    instance=store.config['instance_uuid']
    status_request={'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),
                    'operation':'status','instance_uuid':instance}
    try:
        before=store.snapshot();status=service.status(status_request,actor)
        value=store.preparation_progress()
        if value is None:return None
        coherent=before==store.snapshot() and status==service.status(status_request,actor)
        return dict(value,request_matches=bool(coherent and status['operation_id']==value['operation_id']
            and before['active_generation']==value['source_generation']))
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,sqlite3.Error):
        return {'stage':'unknown','historical':True,'current_runtime_verified':False,
                'automatic_replay':False,'unavailable':True,'request_matches':False}


def _valid_disconnect_request(session):
    try:
        uuid_text(session.get('disconnect_request_id'))
        return True
    except ValueError:
        return False


def external_relay_worker(root, session_uuid):
    """外部接入中转工作进程：读私有会话记录，运行帧泵并落状态。

    授权节点集合从当前实例计划派生（非空名单），与帧门禁贯通。
    'connected'只在SSH+端点认证+会话握手全部完成后落；断开/超额/SSH中断/代次
    变化都写明原因退出；不重启、不重连、不重放旧帧。
    """
    import hashlib
    import signal as _signal
    import threading as _threading
    from ctflab_external_attach import (AttachStore, run_relay, validate_attachment,
                                        validate_registration, policy_summary, now_iso,
                                        derive_allowed_macs)
    from ctflab_scenario_v2 import instance_plan
    uuid_text(session_uuid)
    store = GenerationStore(root)
    instance = store.config['instance_uuid']
    generation = max(1, store.snapshot()['active_generation'])
    networks = {name: net['external'] for name, net in store.config['manifest'].get('networks', {}).items()
                if isinstance(net, dict) and isinstance(net.get('external'), dict)}
    attach = AttachStore(root, instance, generation=generation,
                         network_id=next(iter(networks), 'lab'))
    binding = attach.load()
    require(type(binding) is dict and binding.get('schema') == 1, 'identity-unknown')
    session = binding.get('session')
    require(type(session) is dict and session.get('session_uuid') == session_uuid
            and session.get('state') == 'connecting', 'state-conflict')
    stopped = _threading.Event()
    for name in ('SIGINT', 'SIGTERM'):
        _signal.signal(getattr(_signal, name), lambda *_: stopped.set())
    registration = validate_registration(binding['registration'])
    attachment = validate_attachment(binding['attachment'])
    # 生产装配：授权节点集合来自当前计划的实际派生MAC，不允许空名单。
    plan = instance_plan(store.config['manifest'], instance)
    allowed_macs = derive_allowed_macs(plan, binding['network_id'])
    require(allowed_macs, 'invalid-request')
    policy = policy_summary(attachment, allowed_macs)
    profile = read(root/'runtime-profile.json')
    port = (profile.get('networks', {}).get(binding['network_id']) or {}).get('external')
    require(type(port) is int, 'state-conflict')

    def update(state, **extra):
        import time as _time
        deadline = _time.monotonic() + 2.0
        while True:
            try:
                with store.locked():
                    fresh = attach.load() or {}
                    base = fresh.get('session', {})
                    if base.get('session_uuid') != session_uuid:
                        return
                    fresh['session'] = dict(base, state=state, updated_at=now_iso(), **extra)
                    attach.save(fresh)
                return
            except ContractError as error:
                if error.code != 'resource-busy' or _time.monotonic() >= deadline:
                    raise
                _time.sleep(0.05)  # 只重试状态持久化，不重连/重放网络操作。

    from ctflab_contract import canonical
    manifest_digest = hashlib.sha256(canonical(store.config['manifest']).encode()).hexdigest()
    require(binding['policy_sha256'] == policy['policy_sha256'], 'state-conflict')

    def generation_changed():
        try:
            latest = attach.load() or {}
            return (max(1, store.snapshot()['active_generation']) != generation
                    or hashlib.sha256(canonical(GenerationStore(root).config['manifest']).encode()).hexdigest()
                    != manifest_digest
                    or latest.get('session', {}).get('session_uuid') != session_uuid
                    or (latest.get('session', {}).get('disconnect_requested') is True
                        and _valid_disconnect_request(latest.get('session', {}))))
        except (OSError, ValueError, KeyError):
            return True

    def mark_ready(identity):
        update('connected', identity_state=identity.get('identity_state'),
               identity_binding=identity.get('identity_binding'))
    transport_started = False
    try:
        if platform.system() == 'Windows':
            _wait_windows_relay_identity(attach, session_uuid)
            if generation_changed():
                update('disconnected', report={'reason':'completed','transport_closed':True,'not_started':True})
                return
        transport_started = True
        report = run_relay(_load_json_public(session['ssh_config']), attachment, policy,
                           session.get('secret') or '0' * 64, session_uuid,
                           ('127.0.0.1', port), backend=session.get('backend', 'hub'),
                           stop=lambda: stopped.is_set() or generation_changed(),
                           registration=registration, on_ready=mark_ready)
        report['transport_closed'] = True  # run_relay的finally已确认自有通道收口。
        state = 'disconnected' if report.get('reason') in ('completed', 'guest-close') \
            else 'unknown'
        update(state, report=report)
    except BaseException as error:
        extra = {} if transport_started else {'report':{'reason':'not-started','transport_closed':True}}
        update('unknown', reason=str(error)[:160], **extra)
        raise


def _load_json_public(path):
    return read(Path(path))


def _external_session_view(root, attach, binding, *, observe_process=None):
    """会话状态视图：进程消失而状态未收口即显示unknown，不自动重启或重连。"""
    session = binding.get('session') if isinstance(binding, dict) else None
    if not isinstance(session, dict) or session.get('state') in (None, 'idle'):
        return {'state': 'idle'}
    if session['state'] in ('connecting', 'connected'):
        alive = True
        if observe_process is not None:
            alive = observe_process(session)
        if not alive:
            return {'state': 'unknown', 'session_uuid': session.get('session_uuid'),
                    'note': '中转进程已退出且未写明原因；请核对现场后显式清除或重连。'}
    return {key: session.get(key) for key in ('state', 'session_uuid', 'backend', 'started_at',
                                              'disconnect_failure', 'identity_state',
                                              'identity_binding')
            if key in session}


def _wait_windows_relay_identity(attach, session_uuid, timeout=2.0):
    """先绑定启动方记录与本进程原生身份，再允许打开网络。"""
    import time as _time
    from ctflab_windows_native import Win32, compare_identity
    deadline = _time.monotonic() + timeout
    while True:
        latest = (attach.load() or {}).get('session', {})
        require(latest.get('session_uuid') == session_uuid, 'state-conflict')
        if latest.get('process_identity') is not None:
            expected = _windows_relay_identity(latest)
            require(expected.pid == os.getpid() and compare_identity(
                expected, Win32().observe(os.getpid())) == 'running', 'identity-unknown')
            return
        require(_time.monotonic() < deadline, 'identity-unknown')
        _time.sleep(0.01)


def _windows_relay_identity(session):
    """只接受启动方从自己持有的子进程句柄记录的完整身份。"""
    from ctflab_windows_native import ProcessIdentity, NativeError
    import ntpath
    raw = session.get('process_identity')
    if (type(raw) is not dict or set(raw) != {'pid', 'creation_ticks', 'image_path', 'state'}
            or type(raw.get('pid')) is not int or raw['pid'] != session.get('pid')
            or type(raw.get('creation_ticks')) is not int or not 0 < raw['creation_ticks'] < 2**64
            or type(raw.get('image_path')) is not str or not ntpath.isabs(raw['image_path'])
            or '\x00' in raw['image_path']
            or raw.get('state') != 'running'):
        raise NativeError('identity-unknown')
    return ProcessIdentity(**raw)


def _capture_windows_relay(process):
    """Popen持有的原始Windows句柄，不以PID重开替代启动证明。"""
    from ctflab_windows_native import Win32, NativeError
    handle = getattr(process, '_handle', None)
    if handle is None or type(process.pid) is not int or not 1 < process.pid <= 0xffffffff:
        raise NativeError('identity-unknown')
    observed = Win32().observe_handle(int(handle), process.pid)
    if observed.pid != process.pid or observed.state != 'running':
        raise NativeError('identity-unknown')
    raw = asdict(observed)
    _windows_relay_identity({'pid':process.pid,'process_identity':raw})
    return raw


def _observe_windows_relay(session, native=None):
    from ctflab_windows_native import Win32, NativeError, compare_identity
    pid = session.get('pid')
    if type(pid) is not int or not 1 < pid <= 0xffffffff:
        return None
    launch_exit = session.get('launch_exit')
    if (type(launch_exit) is dict and set(launch_exit) == {'session_uuid', 'pid', 'exit_code', 'before_transport'}
            and launch_exit.get('session_uuid') == session.get('session_uuid')
            and launch_exit.get('pid') == pid and type(launch_exit.get('exit_code')) is int
            and launch_exit.get('before_transport') is True):
        return False  # 启动方已等待原Popen对象退出，且身份闸门前未打开通道。
    native = native or Win32()
    try:
        expected = _windows_relay_identity(session)
    except NativeError:
        # 旧记录缺创建时间：仅快照确认PID已不存在时可恢复；不对现存PID猜身份。
        try:
            return None if native.pid_exists(pid) else False
        except (NativeError, OSError):
            return None
    try:
        state = compare_identity(expected, native.observe(pid))
        if state in ('exited', 'mismatch'):
            return False
        return True if state == 'running' else None
    except (NativeError, OSError):
        try:
            return None if native.pid_exists(pid) else False
        except (NativeError, OSError):
            return None


def _retain_windows_relay(session, stack):
    """在发停止意图之前保留匹配对象；失败不降级为不带身份的控制。"""
    from ctflab_windows_native import Win32, NativeError
    native = Win32()
    try:
        expected = _windows_relay_identity(session)
        handle = stack.enter_context(native.retained(expected))
        code = native.wait_exit(handle, 0)
        return native, handle, code is None, code
    except (NativeError, OSError):
        observation = _observe_windows_relay(session, native)
        return native, None, False if observation is False else None, None


def scan_relay_pid(session_uuid):
    """无PID旧记录的命令行身份扫描（Darwin/Linux）：一次性列出进程表精确匹配。

    证明语义：命令行同时包含桥接程序名、external-relay与完整会话UUID的进程
    存在→返回其PID；确认不存在→False；扫描不可用（非POSIX平台、ps失败、
    会话标识无效）→None，绝不当作已退出。多个匹配说明现场异常，拒绝恢复。
    Windows命令行枚举不读取完整argv，不在本入口冒充。
    """
    if platform.system() not in ('Darwin', 'Linux'):
        return None
    try:
        uuid_text(session_uuid)
    except ValueError:
        return None
    import subprocess
    from ctflab_scenario_runtime import PS_BINARY, _ps_environment
    try:
        result = subprocess.run([PS_BINARY, '-ww', '-axo', 'pid=,command='],
                                capture_output=True, text=True, check=True,
                                timeout=15, env=_ps_environment())
    except (OSError, subprocess.SubprocessError, ImportError, AttributeError):
        return None
    matches = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, command = stripped.partition(' ')
        if not pid_text.isdigit():
            continue
        if 'ctflab_desktop_bridge' in command and 'external-relay' in command \
                and session_uuid in command:
            matches.append(int(pid_text))
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise RuntimeError('relay-scan-ambiguous')
    return False


def observe_relay_process(session):
    """三态进程观测：True匹配、False确认原身份不在、None不可判定。

    缺PID或PID不可用的旧unknown记录回退到命令行扫描；扫描不可用时保持
    None，不得当作已退出，也不清账。
    """
    from ctflab_scenario_runtime import process_command
    if platform.system() == 'Windows':
        try:
            uuid_text(session.get('session_uuid'))
            return _observe_windows_relay(session)
        except (OSError, ValueError, RuntimeError):
            return None
    if platform.system() not in ('Darwin', 'Linux'):
        return None
    pid = session.get('pid')
    if type(pid) is not int or pid <= 1:
        found = scan_relay_pid(session.get('session_uuid'))
        return True if type(found) is int else found
    try:
        uuid_text(session.get('session_uuid'))
    except ValueError:
        return None
    try:
        command = process_command(pid)
    except (OSError, ValueError, RuntimeError):
        return None
    if not command:
        try:
            os.kill(pid, 0)  # 只读存在性探测，不发送信号。
        except ProcessLookupError:
            return False
        except OSError:
            return None
        return None  # PID仍在但身份不可读，不能当已退出。
    return bool(command) and 'ctflab_desktop_bridge' in command and 'external-relay' in command \
        and str(session.get('session_uuid')) in command


def disconnect_external_relay(root, store, instance, value):
    """两阶段断开：锁内登记意图，锁外等进程，锁内按原会话合并回执。"""
    import signal as _signal
    import time as _time
    from ctflab_external_attach import AttachStore, now_iso
    from contextlib import ExitStack
    require(set(value) == {'action'}, 'invalid-request')
    with ExitStack() as handles:
        with store.locked():
            generation = max(1, store.snapshot()['active_generation'])
            attach = AttachStore(root, instance, generation=generation, network_id='lab')
            binding = attach.load()
            session = (binding or {}).get('session')
            require(isinstance(session, dict) and session.get('state') in
                    ('connecting', 'connected', 'unknown'), 'state-conflict')
            uuid_text(session.get('session_uuid'))
            identity = canonical({key: item for key, item in binding.items() if key != 'session'})
            windows = platform.system() == 'Windows'
            windows_control = _retain_windows_relay(session, handles) if windows else None
            request_id = str(uuid.uuid4())
            session = dict(session, disconnect_request_id=request_id, disconnect_requested=True)
            attach.save(dict(binding, session=session))
        # 此处不能持代次锁：worker要先落最终回执，再退出。
        terminated = False
        already_exited = False
        failure = None
        if type(session.get('pid')) is not int or session['pid'] <= 1:
            if windows:
                # Windows无完整argv进程枚举，不以工具快照冒充扫描证明。
                failure = 'pid-unknown'
            else:
                # 无PID旧unknown的受验证恢复：命令行身份扫描给出在场/不在场
                # 证明。扫描不可用保持pid-unknown；多个匹配视为现场异常拒绝。
                found = None
                try:
                    found = scan_relay_pid(session.get('session_uuid'))
                except RuntimeError:
                    failure = 'relay-scan-ambiguous'
                if failure is None:
                    if found is False:
                        already_exited = True
                        session = dict(session, pid_source='command-scan-absent')
                    elif type(found) is int and found > 1:
                        # 采信扫描PID前会再经observe按命令行核验，不以裸PID强杀。
                        session = dict(session, pid=found, pid_source='command-scan')
                    else:
                        failure = 'pid-unknown'
        if failure is None and not already_exited:
            if windows:
                native, handle, alive, exit_code = windows_control
                if alive is None:
                    failure = 'process-observation-unknown'
                elif alive is False:
                    already_exited = True
                    if exit_code not in (None, 0):
                        failure = 'relay-exit-error'
                else:
                    try:
                        exit_code = native.wait_exit(handle, 2000)
                        if exit_code is None:
                            failure = 'termination-unconfirmed'
                        elif exit_code != 0:
                            failure = 'relay-exit-error'
                        else:
                            terminated = True
                    except (OSError, RuntimeError):
                        failure = 'process-observation-unknown'
            else:
                try:
                    alive = observe_relay_process(session)
                    if alive is None:
                        failure = 'process-observation-unknown'
                    elif alive is False:
                        already_exited = True
                    else:
                        # 协作退出窗口：disconnect_requested已落库，worker通常在
                        # 数十毫秒内自行收口并落回执；先等窗口，仍存活才SIGTERM，
                        # 避免信号命中正在退出/刚退出的进程（-15而非协作回执）。
                        for _ in range(10):
                            alive = observe_relay_process(session)
                            if alive is not True:
                                break
                            _time.sleep(0.1)
                    if alive is None:
                        failure = 'process-observation-unknown'
                    elif alive is False:
                        already_exited = True
                    elif failure is None:
                        os.kill(session['pid'], _signal.SIGTERM)
                        for _ in range(20):
                            alive = observe_relay_process(session)
                            if alive is not True:
                                break
                            _time.sleep(0.1)
                        if alive is None:
                            failure = 'process-observation-unknown'
                        elif alive:
                            failure = 'termination-unconfirmed'
                        else:
                            terminated = True
                except (OSError, ValueError) as error:
                    failure = f'terminate-failed: {str(error)[:80]}'
        with store.locked():
            fresh = attach.load()
            current = (fresh or {}).get('session')
            # 命令行扫描采信的PID尚未落库：只接受current没有别的有效PID，
            # 不允许覆盖其他并发方写入的在场身份。
            adopted = session.get('pid_source') == 'command-scan'
            require(isinstance(current, dict) and current.get('session_uuid') == session['session_uuid']
                    and (current.get('pid') == session.get('pid')
                         or (adopted and not (type(current.get('pid')) is int
                                              and current['pid'] > 1
                                              and current['pid'] != session.get('pid'))))
                    and current.get('process_identity') == session.get('process_identity')
                    and current.get('disconnect_request_id') == request_id
                    and canonical({key: item for key, item in fresh.items() if key != 'session'}) == identity
                    and max(1, store.snapshot()['active_generation']) == generation, 'state-conflict')
            if failure is None and (not isinstance(current.get('report'), dict)
                                    or current['report'].get('transport_closed') is not True):
                failure = 'final-receipt-missing'
            # worker可能刚写入report/身份；必须合并最新session，不能用等待前副本覆盖。
            evidence = {'pid': session.get('pid'), 'pid_source': session.get('pid_source')} \
                if session.get('pid_source') else {}
            if failure is None:
                fresh['session'] = dict(current, state='disconnected',
                                        terminated_by_user=terminated, already_exited=already_exited,
                                        disconnect_requested=False, updated_at=now_iso(), **evidence)
                fresh['session'].pop('disconnect_failure', None)
                state_name = 'relay-detached'
                note = '仅断开中转通道；Kali内残留进程与命名空间以助手status为准，不会自动清理。'
            else:
                fresh['session'] = dict(current, state='unknown', disconnect_failure=failure,
                                        disconnect_requested=True, updated_at=now_iso(), **evidence)
                state_name = 'relay-unknown'
                note = '终止未证实；保留unknown与恢复入口，请核对进程后重试或显式清除。'
            attach.save(fresh)
        return {'state': state_name, 'session_uuid': session['session_uuid'],
                'terminated_by_user': terminated, 'automatic_replay': False, 'note': note}


def external_attach_dispatch(root, store, instance, action, value):
    """外部攻击机接入：登记/预览/连接/断开/材料。

    连接只在本代次计划与profile都有预留口且登记有效时开放（设计§9）；
    断开只撤中转通道，不停止VM、不杀用户工具；未预留的运行中实验不热改。
    """
    if action == 'external-attach-disconnect':
        return disconnect_external_relay(root, store, instance, value)
    import hashlib
    from ctflab_contract import canonical
    from ctflab_external_attach import (AttachStore, validate_attachment, validate_registration,
                                        policy_summary, attachment_digest, now_iso,
                                        bind_ssh_config, approval_ledger_dir,
                                        require_approved_assistant)
    plan_sha = hashlib.sha256(canonical(store.config['manifest']).encode()).hexdigest()
    generation = max(1, store.snapshot()['active_generation'])
    networks = {name: net['external'] for name, net in store.config['manifest'].get('networks', {}).items()
                if isinstance(net, dict) and isinstance(net.get('external'), dict)}
    attach = AttachStore(root, instance, generation=generation,
                         network_id=next(iter(networks), 'lab'))
    binding = attach.load()
    binding_valid = bool(binding) and binding.get('plan_sha256') == plan_sha \
        and binding.get('generation') == generation
    profile = read(root/'runtime-profile.json') if (root/'runtime-profile.json').exists() else {}
    reserved_ports = {name: (profile.get('networks', {}).get(name) or {}).get('external')
                      for name in networks}
    if action == 'external-attach-status':
        slots = []
        for name, slot in sorted(networks.items()):
            subnet = store.config['manifest']['networks'][name].get('cidr')
            slots.append({'network': name, 'address': slot.get('address'), 'mac': slot.get('mac'),
                          'cidr': subnet, 'reserved_port': reserved_ports.get(name),
                          'note': '静态预约；未预留槽位的运行中实验不热改'})
        session = _external_session_view(root, attach, binding if binding_valid else None,
                                         observe_process=observe_relay_process)
        if session.get('state') == 'unknown' and isinstance(binding, dict) \
                and isinstance(binding.get('session'), dict) \
                and binding['session'].get('state') != 'unknown':
            # 进程已消失而状态未收口：惰性落unknown，之后允许显式清除或重连。
            fresh = dict(binding)
            fresh['session'] = dict(binding['session'], state='unknown', updated_at=now_iso())
            attach.save(fresh)
            binding = fresh
        return {'state': 'external-attach-status', 'instance_uuid': instance,
                'generation': generation, 'plan_sha256': plan_sha,
                'binding_valid': binding_valid, 'binding': binding, 'slots': slots,
                'session': session,
                'connect_supported': bool(binding_valid) and any(
                    type(port) is int for port in reserved_ports.values()),
                'note': '连接须同时满足：登记有效、本代次profile已预留接入口、无并发业务操作。'}
    if action == 'external-attach-save':
        require(set(value) == {'action', 'registration', 'network'}, 'invalid-request')
        require((binding or {}).get('session', {}).get('state') not in
                ('connecting', 'connected', 'unknown'), 'resource-busy')
        registration = validate_registration(value['registration'])
        require(value['network'] in networks, 'permission-denied')
        slot = networks[value['network']]
        attachment_value = validate_attachment({
            'schema': 1, 'kind': 'kali-l2-v1', 'instance_uuid': instance,
            'generation': generation, 'network_id': value['network'],
            'cidr': store.config['manifest']['networks'][value['network']]['cidr'],
            'address': slot['address'], 'mac': slot['mac'], 'mtu': 1400, 'limits': {},
            'expires': '2099-01-01T00:00:00Z'})
        from ctflab_scenario_v2 import instance_plan
        from ctflab_external_attach import derive_allowed_macs
        policy = policy_summary(attachment_value, derive_allowed_macs(
            instance_plan(store.config['manifest'], instance), value['network']))
        binding = {'schema': 1, 'instance_uuid': instance, 'generation': generation,
                   'network_id': value['network'], 'plan_sha256': plan_sha,
                   'registration': registration, 'attachment': attachment_value,
                   'policy_sha256': policy['policy_sha256'], 'saved_at': now_iso()}
        attach.save(binding)
        return {'state': 'external-attach-saved', 'attachment_sha256': attachment_digest(attachment_value),
                'binding': binding}
    if action == 'external-attach-connect':
        require(set(value) == {'action', 'ssh_config'}, 'invalid-request')
        require(binding_valid, 'state-conflict')
        network = binding['network_id']
        port = reserved_ports.get(network)
        require(type(port) is int, 'state-conflict')
        previous = _external_session_view(root, attach, binding)
        require(previous['state'] in ('idle', 'disconnected', 'unknown'), 'resource-busy')
        if previous['state'] == 'unknown':
            require(observe_relay_process(binding.get('session', {})) is False, 'resource-busy')
        ssh_config = _load_json_public(value['ssh_config'])
        registration = validate_registration(binding['registration'])
        bind_ssh_config(ssh_config, registration)
        # 设计§4.3持久批准：登记的助手摘要必须在用户账本中有对本机材料清单的
        # 批准；未批准（含从未批准过）一律拒绝建立会话，不在桌面路径绕过。
        require_approved_assistant(registration, approval_ledger_dir())
        prepared = binding.get('prepared')
        require(isinstance(prepared, dict) and prepared.get('policy_sha256') == binding['policy_sha256']
                and not prepared.get('used'),
                'state-conflict')
        session_uuid = prepared['session_uuid']
        session_path = root/'external-attach'/f'{session_uuid}.ssh.json'
        session_path.parent.mkdir(mode=0o700, exist_ok=True)
        record(session_path, ssh_config)
        fresh = dict(binding)
        fresh['prepared'] = dict(prepared, used=True)
        fresh['session'] = {'schema': 1, 'session_uuid': session_uuid, 'backend': 'hub',
                            'endpoint': f'127.0.0.1:{port}', 'ssh_config': str(session_path),
                            'state': 'connecting', 'started_at': now_iso()}
        attach.save(fresh)
        try:
            process = launch(root, 'external-relay', session=session_uuid)
        except OSError:
            return {'state': 'relay-unknown', 'session_uuid': session_uuid,
                    'automatic_replay': False,
                    'note': '派发结果未知；原会话记录保留，请先读取状态再决定。'}
        current = attach.load() or {}
        current['session'] = dict(current.get('session', {}), pid=process.pid)
        if platform.system() == 'Windows':
            try:
                current['session']['process_identity'] = _capture_windows_relay(process)
            except (OSError, ValueError, RuntimeError):
                current['session'].update(state='unknown', reason='process-identity-unverified')
                # 仅回收本次Popen原始句柄；worker身份闸门前尚未打开数据通道。
                try:
                    process.terminate()
                    process.wait(timeout=2)
                    current['session']['launch_exit'] = {'session_uuid':session_uuid, 'pid':process.pid,
                                                         'exit_code':process.returncode, 'before_transport':True}
                    current['session']['report'] = {'reason':'launch-not-started','transport_closed':True}
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                    pass
                attach.save(current)
                return {'state':'relay-unknown','session_uuid':session_uuid,'automatic_replay':False,
                        'note':'原生进程身份未能核验；未进入网络连接，保留现场与启动回执。'}
        attach.save(current)
        return {'state': 'relay-requested', 'session_uuid': session_uuid,
                'automatic_replay': False}
    if action == 'external-attach-clear':
        require(set(value) == {'action'}, 'invalid-request')
        session = (binding or {}).get('session')
        require(not isinstance(session, dict) or session.get('state') in
                (None, 'idle', 'disconnected', 'unknown'), 'resource-busy')
        if isinstance(session, dict) and session.get('state') in ('disconnected', 'unknown'):
            require(observe_relay_process(session) is False, 'resource-busy')
        attach.clear()
        return {'state': 'external-attach-cleared'}
    if action == 'external-attach-materials':
        require(set(value) == {'action', 'destination'}, 'invalid-request')
        from ctflab_kali_attach import materials
        prepared = None
        if binding_valid:
            from ctflab_external_attach import prepare_session
            from ctflab_scenario_v2 import instance_plan
            from ctflab_external_attach import derive_allowed_macs
            session = binding.get('session', {})
            require(session.get('state') not in ('connecting', 'connected', 'unknown'), 'resource-busy')
            previous_prepared = binding.get('prepared') or {}
            policy = policy_summary(binding['attachment'], derive_allowed_macs(
                instance_plan(store.config['manifest'], instance), binding['network_id']))
            require(binding['policy_sha256'] == policy['policy_sha256'], 'state-conflict')
            prepared = prepare_session(binding['attachment'], policy,
                session_uuid=None if previous_prepared.get('used') else previous_prepared.get('session_uuid'))
        manifest = materials(value['destination'], prepared=prepared)
        if prepared is not None:
            binding['prepared'] = prepared
            attach.save(binding)
        return {'state': 'external-attach-materials', 'manifest': manifest}

    raise ContractError('invalid-request')


def dispatch(root, value, *, spawn=launch, make_backend=backend):
    require(type(value) is dict and isinstance(value.get('action'), str))
    action = value['action']
    if action == 'configure':
        return configure(root, value)
    if action == 'import-course':
        return import_course(root,value)
    store = GenerationStore(root)
    instance = store.config['instance_uuid']
    if action == 'attach':
        require(set(value) == {'action'})
        # 接入既有通用实例；不接管旧固定Smoke目录，不启动或改变代次。
        require(store.snapshot()['active_generation'] == 0, 'state-conflict')
        LocalService.create(root/'desktop-contract')
        return {'state': 'configured', 'instance_uuid': instance}
    service = LocalService(root/'desktop-contract')
    actor = process_actor()
    if action == 'preparation-progress':
        require(set(value)=={'action'})
        return {'state':'preparation-progress','instance_uuid':instance,'progress':preparation_progress(store,service,actor)}
    if action == 'operation-history':
        require({'action', 'limit'} <= set(value) <= {'action', 'limit', 'before'})
        return service.operation_history(instance, actor, limit=value['limit'], before=value.get('before'))
    if action == 'operation-result':
        require(set(value) == {'action', 'operation_id'})
        return service.operation_result(instance, value['operation_id'], actor)
    if action in ('rearm-observer','rearm-log'):
        require(set(value) == {'action', 'instance_uuid', 'generation', 'state_revision', 'node', 'attempt_id'})
        require(value['instance_uuid'] == instance, 'permission-denied')
        uuid_text(value['attempt_id']); integer(value['generation'], 1); integer(value['state_revision'])
        with store.locked():
            status = service.status({'protocol':'ctflab-local','version':1,'request_id':str(uuid.uuid4()),
                                     'operation':'status','instance_uuid':instance}, actor)
            require(status['generation'] == value['generation'] and status['state_revision'] == value['state_revision']
                    and not status['operation_id'] and store.snapshot()['active_generation'] == value['generation'], 'state-conflict')
            worker = make_backend(root);plan = store.plan(value['generation'])
            require(value['node'] in plan['manifest']['nodes'])
            handler=worker.driver.rearm_log if action=='rearm-log' else worker.driver.rearm_observer
            return handler(plan,value['node'],store.node_paths(value['generation'],value['node']),value['attempt_id'])
    if action == 'restart-preparation':
        require(set(value) == {'action', 'instance_uuid', 'operation_id', 'state_revision', 'attempt_id'})
        require(value['instance_uuid'] == instance, 'permission-denied')
        try:
            response = service.restart_preparation(instance, value['operation_id'], value['state_revision'],
                        value['attempt_id'], actor, make_backend(root))
        except sqlite3.Error as exc:
            busy = getattr(exc, 'sqlite_errorcode', None) in (5, 6) or 'locked' in str(exc)
            raise ContractError('resource-busy' if busy else 'persistence-failed') from None
        return dispatch_pending(root, response, spawn)
    if action == 'resume-dispatch':
        require(set(value) == {'action', 'instance_uuid', 'operation_id', 'state_revision', 'attempt_id'})
        require(value['instance_uuid'] == instance, 'permission-denied')
        uuid_text(value['attempt_id']); integer(value['state_revision'])
        original = service.dispatch_status(instance, value['operation_id'], actor)
        require(original['resume_allowed'], 'state-conflict')
        require(original['state_revision'] == value['state_revision'], 'state-conflict')
        # 新派发尝试仅引用原操作，不改请求/版本/取消标记。即使旧worker迟到，
        # LocalService工作门锁和pending→executing事务也只允许后端领取一次。
        intent = {k: value[k] for k in ('instance_uuid', 'operation_id', 'state_revision', 'attempt_id')}
        marker = root/('desktop-redelivery-'+value['attempt_id']+'.json')
        try:
            record(marker, intent)
        except FileExistsError:
            require(read(marker) == intent, 'idempotency-conflict')
            return dict(original, state='dispatch-already-requested')
        try:
            spawn(root, 'execute', operation=value['operation_id'])
        except OSError:
            return dict(original, state='dispatch-unknown')
        return dict(original, state='dispatch-requested')
    if action == 'query-request':
        require(set(value)=={'action','request'} and type(value['request']) is dict
            and value['request'].get('instance_uuid')==instance,'permission-denied')
        return service.query_request(value['request'],actor)
    if action == 'submit':
        require(set(value) == {'action', 'request'})
        req = value['request']
        require(type(req) is dict and req.get('instance_uuid') == instance, 'permission-denied')
        response = service.submit(req, actor)
        if req['operation'] not in ('status', 'cancel'):
            return dispatch_pending(root, response, spawn)
        return response
    if action == 'events':
        require(set(value) == {'action', 'after'})
        return service.events(instance, actor, after=value['after'], limit=100)
    if action == 'display':
        require(set(value) == {'action', 'node'})
        require(value['node'] in store.config['manifest']['nodes'])
        spawn(root, 'display-worker', node=value['node'])
        return {'state': 'display-requested', 'node': value['node']}
    if action == 'draft':
        require(set(value) == {'action', 'manifest'})
        from ctflab_topology import draft_diff
        # 只返回校验后的草稿差异，不修改活动清单或运行代次。
        return draft_diff(store.config['manifest'], value['manifest'], instance,
                          max(1, store.snapshot()['active_generation']))
    if action == 'template-qualify':
        require(set(value) == {'action', 'manifest', 'acceptance'})
        from ctflab_topology import publish_qualification
        # 可执行模板资格门：只读计算；S03失败或验收未绑定精确摘要即拒绝，不改运行场景。
        return publish_qualification(store.config['manifest'], value['manifest'], instance,
                                     generation=max(1, store.snapshot()['active_generation']),
                                     acceptance=value['acceptance'])
    if action == 'external-attach-disconnect':
        return external_attach_dispatch(root, store, instance, action, value)
    if action.startswith('external-attach-'):
        with store.locked():
            return external_attach_dispatch(root, store, instance, action, value)
    require(action in ('overview', 'diagnostics') and set(value) == {'action'})
    sample_started=datetime.now(timezone.utc)
    before = store.snapshot()
    status_request = {'protocol': 'ctflab-local', 'version': 1, 'request_id': str(uuid.uuid4()),
                      'operation': 'status', 'instance_uuid': instance}
    status = service.status(status_request, actor)
    generation = before['active_generation']
    def unchanged():
        # 不跨驱动I/O持数据库锁；乐观核对失败时只降级，不重采样或重放。
        return before == store.snapshot() and status == service.status(status_request, actor)

    preparation = service.preparation_status(instance, actor) if generation == 0 else None
    observed = {}
    if generation:
        try:
            worker=make_backend(root)
            observed=(worker.observation_snapshot(generation) if hasattr(worker,'observation_snapshot') else
                {k:dict(asdict(v),observed_at=sample_started.isoformat()) for k,v in worker.observations(generation).items()})
        except (OSError, ValueError, RuntimeError, KeyError):
            observed = {k: {'identity': 'unknown', 'state': 'unknown'} for k in store.config['manifest']['nodes']}
    observed = sampled_observations(observed, instance, generation, store.config['manifest']['nodes'],
                                    sample_started, datetime.now(timezone.utc))
    if action == 'diagnostics':
        if not unchanged():
            observed = {n: dict(v, identity='unknown', state='unknown') for n, v in observed.items()}
        from ctflab_diagnostics_public import encoded_preview
        report = {'schema': 1, 'host': {'system': platform.system(), 'machine': platform.machine()},
                  'profiles': [{'state': 'running' if v['state'] == 'process-running' else v['state']}
                               for v in observed.values()]}
        raw, checksum = encoded_preview(report)
        return {'preview': json.loads(raw), 'preview_sha256': checksum, 'uploaded': False}
    execution={'identity':'unknown'}
    dispatch_info = None
    if status.get('operation_id') and status.get('result') in ('accepted','unknown'):
        operation = status['operation_id']
        dispatch_info = service.dispatch_status(instance, operation, actor)
        execution = execution_status(root, operation)
    guest_agents={node:{'containers':bool(spec['containers']),'analysis':'analysis' in spec,'routed':spec.get('routed',False),'services':['dns','local-time'],'verified':False}
                  for node,spec in read(root/'runtime-profile.json').get('agents',{}).items()}
    for node,info in guest_agents.items():
        if observed.get(node,{}).get('state')!='process-running':continue
        try:
            worker=make_backend(root);plan=store.plan(generation)
            attempt=worker.driver.latest(worker.driver.location(plan,node,store.node_paths(generation,node)))
            if attempt:info.update(guest_history(attempt,plan['plan_sha256']))
        except (OSError,ValueError,RuntimeError,KeyError,TypeError):info['last_result']={'state':'unknown'}
    certificates = {}
    supervision = {}
    if generation:
        worker = make_backend(root)
        for node in store.config['manifest']['nodes']:
            try: supervision[node] = worker.driver.supervision(store.plan(generation), node, store.node_paths(generation, node))
            except (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError):
                supervision[node] = {'state': 'unknown', 'observer': 'unknown', 'automatic_replay': False}
            try: certificates[node] = worker.driver.certificates(store.plan(generation), node, store.node_paths(generation, node))
            except (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError):
                certificates[node] = {'state': 'unknown'}
    from ctflab_watch import history as watch_history
    try: supervision_history = watch_history(root)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError):
        supervision_history = {'watches': [], 'historical': True, 'unavailable': True, 'automatic_replay': False}
    profile = read(root/'runtime-profile.json')
    coherent = unchanged()
    if not coherent:
        observed = {n: dict(v, identity='unknown', state='unknown') for n, v in observed.items()}
        execution = {'identity': 'unknown'}; dispatch_info = None; preparation = None
        certificates = {n: {'state': 'unknown'} for n in certificates}
        supervision = {n: {'state': 'unknown', 'observer': 'unknown', 'automatic_replay': False} for n in supervision}
        guest_agents = {n: {k: v for k, v in info.items() if k in ('containers','analysis','routed','services','verified')}
                        for n, info in guest_agents.items()}
    now=datetime.now(timezone.utc);records=[];plan=store.plan(generation) if generation else None
    for node,item in observed.items():
        if item.get('identity')!='verified':continue
        try:
            stamp=datetime.fromisoformat(item['observed_at'].replace('Z','+00:00'))
            require(stamp.tzinfo is not None and stamp<=now,'identity-unknown')
            records.append({'instance_uuid':instance,'generation':generation,'plan_sha256':plan['plan_sha256'],
                'node':node,'timestamp':item['observed_at'],'state':item['state'],'addresses':{},'evidence_ref':'query-'+node})
        except (OSError,ValueError,RuntimeError,KeyError,TypeError):pass
    complete=coherent and (not generation or len(records)==len(store.config['manifest']['nodes']))
    freshness={'schema':1,'sampled_at':sample_started.isoformat(),'valid_until':(sample_started+timedelta(seconds=60)).isoformat(),
        'complete':complete,'simultaneous':False,'coherent':coherent,
        'reason':'changed-during-sampling' if not coherent else ('sample-incomplete' if not complete else 'sampled')}
    topology=projection(store.config['manifest'],instance,generation=max(1,generation),observations=records,now=now)
    return {'freshness':freshness,'instance_uuid': instance, 'status': status, 'observations': observed,
            'runtime': {'host': profile.get('host', platform.system().lower()),
                'dependencies': runtime_dependencies(),
                'emulation_required': profile.get('host')=='darwin-arm64' and any(a['architecture']=='x86_64' for a in store.config['manifest']['assets'].values())},
            'execution':execution,
            'dispatch':dispatch_info,
            'preparation':preparation,
            'preparation_progress':preparation_progress(store,service,actor),
            'certificates':certificates,
            'supervision':supervision,
            'supervision_history':supervision_history,
            'guest_agents':guest_agents,
            'manifest': store.config['manifest'],
            'course': read(root/'course-selection.json') if (root/'course-selection.json').exists() else None,
            'topology':topology,
            'generation': generation, 'runtime_verified': False, 'isolation_verified': False}


def execution_status(root, operation):
    """兼容旧身份文件，保留各次执行器现场；不使用文件中的PID控制进程。"""
    uuid_text(operation)
    from itertools import islice
    from ctflab_qemu_driver import native_observe
    from ctflab_windows_native import ProcessIdentity, compare_identity
    markers = list(islice(root.glob('desktop-execution-'+operation+'-*.json'), 65))
    old = root/('desktop-execution-'+operation+'.json')
    if old.exists(): markers.append(old)
    if not markers or len(markers) > 64: return {'identity': 'unknown'}
    states = []
    for marker in markers:
        try:
            expected = ProcessIdentity(**read(marker))
            states.append(compare_identity(expected, native_observe(expected.pid)))
        except (OSError, ValueError, RuntimeError, KeyError, TypeError): states.append('unknown')
    # 任何已确认仍在运行的执行器都阻止新的实验变更；损坏记录不伪装退出。
    return {'identity': 'running' if 'running' in states else
            'exited' if all(s == 'exited' for s in states) else 'unknown'}


def execute_operation(root, operation, *, make_backend=backend, observe=None):
    """每个worker留独立身份文件；原意图的领取权由契约事务决定。"""
    uuid_text(operation)
    if observe is None:
        from ctflab_qemu_driver import native_observe
        observe = native_observe
    record(root/('desktop-execution-'+operation+'-'+str(uuid.uuid4())+'.json'),
           asdict(observe(os.getpid())))
    return LocalService(root/'desktop-contract').execute(operation, process_actor(), make_backend(root))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('bridge', 'execute', 'display-worker', 'external-relay'))
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--operation')
    parser.add_argument('--node')
    parser.add_argument('--session')
    args = parser.parse_args(argv)
    root = args.run.absolute()
    try:
        if args.action == 'execute':
            execute_operation(root, args.operation)
        elif args.action == 'external-relay':
            external_relay_worker(root, args.session)
        elif args.action == 'display-worker':
            worker = backend(root)
            generation = worker.store.snapshot()['active_generation']
            require(args.node in worker.store.config['manifest']['nodes'])
            from ctflab_rfb_tls import show
            show(lambda: worker.driver.display(worker.store.plan(generation), args.node, worker.store.node_paths(generation, args.node)))
        else:
            raw = sys.stdin.buffer.read(MAX_MESSAGE_BYTES+1)
            require(len(raw) <= MAX_MESSAGE_BYTES)
            def unique(pairs):
                result = {}
                for key, item in pairs:
                    require(key not in result); result[key] = item
                return result
            try:
                value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                                   parse_constant=lambda _: require(False))
            except (ValueError, UnicodeError, RecursionError):
                raise ContractError('invalid-request') from None
            print(canonical(dispatch(root, value)))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, sqlite3.Error) as exc:
        print(canonical(failure(exc.code if isinstance(exc, ContractError) else 'backend-failed',
                                result='failed' if isinstance(exc, ContractError) else 'unknown')))
        return 2


if __name__ == '__main__': raise SystemExit(main())
