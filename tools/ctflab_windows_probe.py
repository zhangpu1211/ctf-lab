"""W01 独立驱动：默认计划、显式只读构建探针、无 VM 合成自检。

无 VM 启动/停止入口，也不修改 Windows 功能、网络或现有实例。
原型实机生命周期由后续受保护适配器接入，不能用本报告宣称 G0 通过。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import uuid

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from ctflab_contract import (ContractError, PROTOCOL, VERSION, canonical, identifier,
                             merge_events, require)
from ctflab_local_service import LocalService, Observation, Outcome
from ctflab_platform import HostPlatform, plan_execution

PROBES = ('runtime-whpx', 'lock-storage', 'protected-control', 'display', 'socket-handoff',
          'supervision-recovery', 'graceful-stop', 'storage-commit', 'coexistence')
QUERY_ARGS = {'version': ('--version',), 'accelerators': ('-accel', 'help'),
              'displays': ('-display', 'help'), 'devices': ('-device', 'help')}


def new_report():
    return {'schema': 1, 'scope': 'w01-driver-only', 'g0_passed': False,
            'vm_started': False, 'native_windows_verified': False,
            'candidate': plan_execution(HostPlatform('Windows', 'AMD64'), 'x86_64').report(),
            'probes': [{'id': name, 'status': 'not-tested'} for name in PROBES]}


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate_manifest(data):
    require(type(data) is dict and set(data) == {'schema', 'build_id', 'target', 'components'})
    require(type(data['schema']) is int and data['schema'] == 1)
    identifier(data['build_id']); require(data['target'] == 'windows-x86_64')
    components = data['components']
    require(type(components) is dict and 'qemu' in components
            and set(components) <= {'qemu', 'python', 'firmware', 'display-client'})
    paths = set()
    for role, item in components.items():
        require(type(item) is dict and set(item) == {'path', 'sha256', 'version', 'source_id'})
        require(isinstance(item['path'], str) and '\x00' not in item['path'])
        path = Path(item['path']); require(path.is_absolute() and '..' not in path.parts)
        if role == 'qemu':
            require(path.name.lower() == 'qemu-system-x86_64.exe')
        require(str(path) not in paths); paths.add(str(path))
        require(isinstance(item['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', item['sha256']) is not None)
        identifier(item['version']); identifier(item['source_id'])
    return json.loads(canonical(data))


def inspect_runtime(manifest, *, run=subprocess.run, host_system=None, host_machine=None):
    """显式执行可信锁定构建的四个帮助查询，参数不能由清单改写。

    run 为独立测试注入点。现场仍需用户授权该设备与构建，不执行下载内容。
    """
    data = validate_manifest(manifest)
    host = HostPlatform(host_system or platform.system(), host_machine or platform.machine())
    require(host == HostPlatform('Windows', 'AMD64'), 'unsupported-platform')
    # 先校验所有组件再执行，任何链接/哈希不符都拒绝。
    for component in data['components'].values():
        path = Path(component['path'])
        for part in (path, *path.parents):
            require(not part.is_symlink() and not getattr(part.lstat(), 'st_file_attributes', 0) & 0x400,
                    'permission-denied')
        require(path.is_file() and path.stat().st_nlink == 1 and _file_hash(path) == component['sha256'],
                'capability-unverified')
    report = new_report(); report['scope'] = 'runtime-build-inspection'
    report['build_id'] = data['build_id']
    # 不输出本机私有路径、原始 stderr/stdout 或环境变量。
    report['components'] = {role: {key: value for key, value in item.items() if key != 'path'}
                            for role, item in data['components'].items()}
    results = []
    binary = Path(data['components']['qemu']['path'])
    for name, arguments in QUERY_ARGS.items():
        if _file_hash(binary) != data['components']['qemu']['sha256']:
            raise ContractError('capability-unverified')
        try:
            completed = run([str(binary), *arguments], capture_output=True, timeout=10,
                            stdin=subprocess.DEVNULL, cwd=str(binary.parent), shell=False)
            output = completed.stdout if isinstance(completed.stdout, bytes) else str(completed.stdout).encode()
            # 仅提取固定能力标签；help 中出现 whpx 不标为硬件可用。
            tokens = sorted(set(re.findall(rb'\b(?:whpx|tcg|spice|vnc|sdl|virtio-gpu-pci|qemu-xhci)\b', output)))
            version_match = (name != 'version' or re.search(
                rb'QEMU emulator version ' + re.escape(data['components']['qemu']['version'].encode())
                + rb'(?:\s|\(|$)', output) is not None)
            results.append({'query': name, 'status': 'inspected' if completed.returncode == 0 and version_match else 'failed',
                            'returncode': completed.returncode, 'output_sha256': hashlib.sha256(output).hexdigest(),
                            'reported_features': [token.decode() for token in tokens]})
        except (OSError, subprocess.TimeoutExpired):
            results.append({'query': name, 'status': 'failed', 'reason': 'query-unavailable-or-timeout'})
    report['queries'] = results
    report['components_complete'] = set(data['components']) == {'qemu', 'python', 'firmware', 'display-client'}
    report['build_inspection_passed'] = all(item['status'] == 'inspected' for item in results)
    return report


def request(instance, operation, *, generation=1, revision=0, key=None, parameters=None):
    result = {'protocol': PROTOCOL, 'version': VERSION, 'request_id': str(uuid.uuid4()),
              'instance_uuid': instance, 'operation': operation}
    if operation != 'status':
        result.update(expected_generation=None if operation == 'prepare' else generation,
                      expected_state_revision=None if operation == 'prepare' else revision,
                      idempotency_key=key or str(uuid.uuid4()), parameters=parameters or {})
    return result


class FixtureBackend:
    """纯内存合成后端，不代表 WHPX/QMP/显示或 VM 进程。"""
    def __init__(self):
        self.generation = 1; self.state = 'prepared'; self.calls = []

    def observe(self, context):
        return Observation('verified', self.generation, self.state)

    def execute(self, req, context):
        op = req['operation']; self.calls.append(op)
        self.state = {'prepare': 'prepared', 'start': 'process-running', 'stop': 'stopped',
                      'reset': 'prepared', 'recover': self.state}[op]
        if op == 'reset': self.generation += 1
        return Outcome(self.state)


def self_test():
    """独立临时状态 + 固定 Python 替身子进程；无网络、QEMU 或用户状态。"""
    checks = []
    with tempfile.TemporaryDirectory(prefix='ctflab-w01-fixture-') as directory:
        service = LocalService.create(Path(directory).resolve() / 'contract')
        backend = FixtureBackend(); instance = str(uuid.uuid4()); actor = 'fixture-user'
        prep = request(instance, 'prepare', key='prepare-once',
                       parameters={'course_id': 'fixture-course', 'baseline_id': 'fixture-baseline'})
        accepted = service.submit(prep, actor)
        assert accepted['result'] == 'accepted'
        done = service.execute(accepted['operation_id'], actor, backend)
        assert done['state'] == 'prepared'
        retry = dict(prep, request_id=str(uuid.uuid4()))
        assert service.handle_json(canonical(retry), actor)['operation_id'] == done['operation_id']
        assert backend.calls == ['prepare']
        checks.append('durable-idempotency')
        service = LocalService(service.root)
        assert service.submit(retry, actor)['result'] == 'completed'
        checks.append('store-reopen')
        for op, params in [('start', {'display': 'headless', 'allow_emulation': False}),
                           ('stop', {}), ('reset', {'baseline_id': 'fixture-baseline'})]:
            accepted = service.submit(request(instance, op, generation=done['generation'],
                                             revision=done['state_revision'], parameters=params), actor)
            assert accepted['result'] == 'accepted'
            done = service.execute(accepted['operation_id'], actor, backend)
            assert done['result'] == 'completed'
        assert done['generation'] == 2
        events = service.events(instance, actor)
        cursor, fresh = merge_events(0, events)
        assert len(fresh) == cursor and merge_events(cursor, events) == (cursor, [])
        checks.extend(['synthetic-lifecycle', 'event-replay'])
        # 固定自有子程序验证 stdio 消息/身份关联；不是持久 QMP 控制通道。
        nonce = str(uuid.uuid4())
        child = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve()), '--fixture-child'],
                               input=canonical({'nonce': nonce, 'action': 'ping'}) + '\n',
                               capture_output=True, text=True, timeout=10, cwd=directory)
        assert child.returncode == 0
        assert json.loads(child.stdout) == {'nonce': nonce, 'reply': 'fixture-pong'}
        checks.append('owned-stdio-fixture')
    report = new_report(); report['scope'] = 'synthetic-only'
    report['checks'] = [{'id': name, 'status': 'passed'} for name in checks]
    return report


def native_preflight():
    """无需 QEMU 的宿主只读检查；不等价于 WHPX 实际运行成功。"""
    from ctflab_windows_native import hypervisor_capability
    report = new_report()
    report['scope'] = 'native-host-preflight-only'
    supported = (platform.system() == 'Windows' and platform.machine().lower() in {'amd64', 'x86_64'}
                 and sys.maxsize > 2**32)
    report['host_supported'] = supported
    report['hypervisor'] = (hypervisor_capability() if supported else
                            {'status': 'unsupported-platform', 'hypervisor_present': None})
    report['host_preflight_passed'] = supported and report['hypervisor']['hypervisor_present'] is True
    report['qemu_execution_verified'] = False
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='W01 独立驱动；不包含 VM 操作')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--self-test', action='store_true')
    mode.add_argument('--native-preflight', action='store_true', help='只读查询 Windows x64 的 WHP 能力，不启动 VM')
    mode.add_argument('--inspect-runtime', type=Path, metavar='LOCKED_MANIFEST')
    mode.add_argument('--fixture-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.fixture_child:
        message = json.loads(sys.stdin.readline(4096))
        require(set(message) == {'nonce', 'action'} and message['action'] == 'ping')
        require(str(uuid.UUID(message['nonce'])) == message['nonce'])
        print(canonical({'nonce': message['nonce'], 'reply': 'fixture-pong'})); return 0
    try:
        if args.self_test: report = self_test()
        elif args.native_preflight: report = native_preflight()
        elif args.inspect_runtime:
            # 清单也必须拒绝重复字段，不让工具参数隐藏在 JSON 中。
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    require(key not in result); result[key] = value
                return result
            require(args.inspect_runtime.stat().st_size <= 64 * 1024)
            data = json.loads(args.inspect_runtime.read_text(encoding='utf-8'), object_pairs_hook=unique)
            report = inspect_runtime(data)
        else: report = new_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1 if (report.get('build_inspection_passed') is False
                     or report.get('host_preflight_passed') is False) else 0
    except (ContractError, OSError, ValueError, AssertionError):
        print(json.dumps({'scope': 'driver-error', 'g0_passed': False,
                          'error': '驱动检查失败；请在本地核对输入、组件与测试记录。'}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    # -I 替身进程也只能加载同目录模块，避免工作目录/PYTHONPATH 污染。
    raise SystemExit(main())
