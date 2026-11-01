"""SSH固定命令Runner与角色范围门；不安装SSH、不接受远程shell或宿主路径。

部署方在authorized_keys中固定principal/策略文件；请求不能声明自己的身份。
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import queue
import subprocess
import sqlite3
import sys
import threading
import time
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from ctflab_contract import canonical, require, identifier, uuid_text, MAX_MESSAGE_BYTES, ContractError
from ctflab_generation_store import digest
from ctflab_tls_endpoint import guard

PROTOCOL = 'ctflab-runner'
COMMAND = 'ctflab-runner-v1'
RESPONSE_LIMIT = 4*1024**2


def decode(raw, limit=MAX_MESSAGE_BYTES):
    require(type(raw) is bytes and len(raw) <= limit)
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value); value[key] = item
        return value
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                       parse_constant=lambda _: require(False))
    require(type(value) is dict)
    return value


def private_json(path):
    path = guard(Path(path).absolute()); require(path.is_file() and path.stat().st_size <= 1024**2)
    return decode(path.read_bytes(), 1024**2)


def validate_policy(policy):
    required={'schema','server_uuid','principals','instances'}
    require(type(policy) is dict and required<=set(policy)<=required|{'uploads','leases','audit','display','evidence','courses','audit_management','storage_pool'})
    require(type(policy['schema']) is int and policy['schema'] == 1)
    uuid_text(policy['server_uuid'])
    require(type(policy['principals']) is dict and type(policy['instances']) is dict)
    require(len(policy['principals']) <= 256 and len(policy['instances']) <= 1024)
    for name, account in policy['principals'].items():
        identifier(name)
        require(type(account) is dict and set(account) == {'role', 'instances', 'expires'})
        require(account['role'] in ('student', 'teacher', 'administrator'))
        require(type(account['instances']) is list and len(set(account['instances'])) == len(account['instances']))
        require(set(account['instances']) <= set(policy['instances']))
        expiry = datetime.fromisoformat(account['expires'].replace('Z', '+00:00'))
        require(expiry.tzinfo is not None)
    roots = set()
    for instance, entry in policy['instances'].items():
        uuid_text(instance)
        require(type(entry) is dict and set(entry) == {'root', 'owner'})
        require(entry['owner'] in policy['principals'])
        root = Path(entry['root']); require(root.is_absolute() and str(root) not in roots)
        require(not any(root in Path(p).parents or Path(p) in root.parents for p in roots))
        roots.add(str(root))
    if 'uploads' in policy:
        from ctflab_remote_assets import validate_settings
        validate_settings(policy['uploads'])
    if 'courses' in policy:
        from ctflab_remote_course import validate_offers
        validate_offers(policy['courses'],policy)
    if 'audit_management' in policy:
        require(type(policy['audit_management']) is bool and (not policy['audit_management'] or 'audit' in policy))
    if 'leases' in policy:
        from ctflab_lease_store import validate_settings
        settings=validate_settings(policy['leases'])
        require(set(settings['limits'])<=set(policy['principals']))
        require(set(settings['instances'])<=set(policy['instances']))
        require(all(policy['instances'][i]['owner'] in settings['limits'] for i in settings['instances']))
        # 配置来自管理员，但目录隔离仍须按内核解释后的词法路径比较。
        root=Path(os.path.abspath(settings['root']))
        others=[Path(os.path.abspath(entry['root'])) for entry in policy['instances'].values()]
        if 'uploads' in policy:others.append(Path(os.path.abspath(policy['uploads']['cache_root'])))
        require(all(root!=p and root not in p.parents and p not in root.parents for p in others))
    if 'evidence' in policy:
        from ctflab_remote_evidence import settings as evidence_settings
        evidence_settings(policy['evidence'])
    if 'display' in policy:
        from ctflab_remote_display import settings as display_settings
        display_settings(policy['display']);require('leases' in policy,'capability-unverified')
    if 'audit' in policy:
        from ctflab_remote_audit import settings
        config=settings(policy['audit']);root=Path(os.path.abspath(config['root']))
        others=[Path(os.path.abspath(entry['root'])) for entry in policy['instances'].values()]
        if 'uploads' in policy:others.append(Path(os.path.abspath(policy['uploads']['cache_root'])))
        if 'leases' in policy:others.append(Path(os.path.abspath(policy['leases']['root'])))
        require(all(root!=p and root not in p.parents and p not in root.parents for p in others))
    from ctflab_server_storage import settings as storage_settings
    storage_settings(policy)
    return policy


class Runner:
    def __init__(self, policy, principal, *, dispatch=None, now=None,lease_manager=None,policy_path=None,display_pool=None):
        self.policy = validate_policy(policy); identifier(principal)
        require(principal in policy['principals'], 'permission-denied')
        self.display_pool=display_pool
        self.principal = principal
        self.now = now or (lambda: datetime.now(timezone.utc))
        if dispatch is None:
            from ctflab_desktop_bridge import dispatch
        self.dispatch = dispatch
        self.lease_manager=lease_manager
        self.policy_path=Path(policy_path).absolute() if policy_path is not None else None

    def leases(self):
        require('leases' in self.policy,'capability-unverified')
        if self.lease_manager is None:
            from ctflab_remote_leases import RemoteLeases
            self.lease_manager=RemoteLeases(self.policy,self.principal,policy_path=self.policy_path)
        return self.lease_manager

    def exchange(self, value):
        from ctflab_server_storage import verify as verify_storage
        verify_storage(self.policy)
        # 审计查看/结清不能先追加自身意图，否则每次请求都会使预览head失效。
        # 只有完整认证、明确启用且当前权限未变的管理员走此独立路径；未获授权的管理请求仍入常规审计。
        if self.audit_management_request(value):return self._exchange(value)
        if 'audit' not in self.policy:return self._exchange(value)
        from ctflab_remote_audit import AuditStore
        audit=AuditStore(self.policy['audit'],self.policy['server_uuid'])
        try:attempt=audit.begin(value,self.principal,now=self.now)
        except ContractError:raise
        except (OSError,ValueError,RuntimeError,sqlite3.Error):raise ContractError('persistence-failed') from None
        try:response=self._exchange(value)
        except Exception as error:
            try:audit.finish(attempt,error=error,now=self.now)
            except (OSError,ValueError,RuntimeError,sqlite3.Error):raise ContractError('persistence-failed') from None
            raise
        try:audit.finish(attempt,response=response,now=self.now)
        except (OSError,ValueError,RuntimeError,sqlite3.Error):raise ContractError('persistence-failed') from None
        return response

    def audit_management_request(self,value):
        try:
            require(type(value) is dict and set(value)=={'protocol','version','request_id','server_uuid','action','parameters'})
            require(value['protocol']==PROTOCOL and type(value['version']) is int and value['version']==1
                    and value['server_uuid']==self.policy['server_uuid']);uuid_text(value['request_id'])
            require(value['action'] in ('audit-review','audit-settlement-preview','audit-settle') and type(value['parameters']) is dict)
            params=value['parameters'];action=value['action']
            fields={'audit-review':{'after','limit','checkpoint'},'audit-settlement-preview':{'attempt_id'},'audit-settle':{'attempt_id','review_sha256'}}
            require(set(params)==fields[action])
            if action=='audit-review':
                require(type(params['after']) is int and 0<=params['after']<=2**53-1
                        and type(params['limit']) is int and 1<=params['limit']<=100)
                checkpoint=params['checkpoint']
                if checkpoint is not None:
                    require(type(checkpoint) is dict and set(checkpoint)=={'seq','sha256'} and type(checkpoint['seq']) is int and checkpoint['seq']>=0)
                    require(type(checkpoint['sha256']) is str and len(checkpoint['sha256'])==64 and all(c in '0123456789abcdef' for c in checkpoint['sha256']))
            else:
                uuid_text(params['attempt_id'])
                if action=='audit-settle':require(type(params['review_sha256']) is str and len(params['review_sha256'])==64
                    and all(c in '0123456789abcdef' for c in params['review_sha256']))
            account=self.policy['principals'][self.principal]
            require(self.policy.get('audit_management') is True and account['role']=='administrator' and self.policy_path is not None)
            require(self.now()<datetime.fromisoformat(account['expires'].replace('Z','+00:00')),'permission-denied')
            require(private_json(self.policy_path)==self.policy,'permission-denied')
            return True
        except (OSError,ValueError,RuntimeError,TypeError,KeyError):return False

    def _exchange(self, value):
        require(type(value) is dict and set(value) == {'protocol', 'version', 'request_id', 'server_uuid', 'action', 'parameters'})
        require(value['protocol'] == PROTOCOL and type(value['version']) is int and value['version'] == 1, 'version-mismatch')
        uuid_text(value['request_id'])
        require(value['server_uuid'] == self.policy['server_uuid'], 'identity-unknown')
        require(type(value['parameters']) is dict)
        account = self.policy['principals'][self.principal]
        action = value['action']; parameters = value['parameters']
        require(action in ('handshake', 'list', 'overview', 'diagnostics', 'submit', 'events',
                          'asset-begin', 'asset-status', 'asset-chunk', 'asset-finish',
                          'lease-acquire','lease-renew','lease-release','lease-status',
                          'display-open','display-frame','display-key','display-pointer','display-close','evidence-list','evidence-read',
                          'course-list','course-preview','course-provision','audit-review','audit-settlement-preview','audit-settle'))
        if action == 'handshake':
            require(parameters == {})
            result = {'state': 'compatible', 'role': account['role'], 'contract_version': 1,
                      'capabilities': ['assigned-instance-contract', 'events', 'public-diagnostics'],
                      'display_tunnel': 'display' in self.policy and self.display_pool is not None, 'asset_upload': 'uploads' in self.policy,
                      'resource_leases':'leases' in self.policy,
                      'request_audit':'audit' in self.policy,'evidence_download':'evidence' in self.policy,
                      'course_management':'courses' in self.policy and self.policy_path is not None and account['role'] in ('teacher','administrator')
                        and self.now()<datetime.fromisoformat(account['expires'].replace('Z','+00:00')),
                      'audit_management':self.policy.get('audit_management') is True and self.policy_path is not None and account['role']=='administrator'
                        and self.now()<datetime.fromisoformat(account['expires'].replace('Z','+00:00')),
                      'persistent_requests': True, 'max_session_requests': 1000000, 'native_verified': False,
                      'arbitrary_commands': False, 'automatic_replay': False}
        elif action.startswith('course-'):
            require(self.policy_path is not None,'capability-unverified')
            from ctflab_remote_course import CourseOffers
            result=CourseOffers(self.policy_path,self.principal,now=self.now,expected_policy=self.policy).handle(action,parameters)
        elif action.startswith('audit-'):
            require(self.audit_management_request(value),'permission-denied')
            from ctflab_audit_review import AuditReview
            review=AuditReview(self.policy_path)
            require(review.policy==self.policy,'permission-denied')
            if action=='audit-review':
                require(set(parameters)=={'after','limit','checkpoint'})
                result=review.read(after=parameters['after'],limit=parameters['limit'],checkpoint=parameters['checkpoint'])
            elif action=='audit-settlement-preview':
                require(set(parameters)=={'attempt_id'});result=review.preview_settlement(parameters['attempt_id'])
            else:
                require(set(parameters)=={'attempt_id','review_sha256'})
                result=review.settle_idempotent(parameters['attempt_id'],parameters['review_sha256'],principal=self.principal)
        elif action.startswith('evidence-'):
            require('evidence' in self.policy,'capability-unverified')
            from ctflab_remote_evidence import RemoteEvidence
            result=RemoteEvidence(self.policy,self.principal,now=self.now).handle(action,parameters)
        elif action.startswith('display-'):
            require('display' in self.policy and self.display_pool is not None,'capability-unverified')
            result=self.display_pool.handle(self.policy,self.principal,action,parameters)
        elif action.startswith('asset-'):
            require('uploads' in self.policy, 'capability-unverified')
            expiry = datetime.fromisoformat(account['expires'].replace('Z', '+00:00'))
            require(action == 'asset-status' or self.now() < expiry, 'permission-denied')
            from ctflab_remote_assets import RemoteUploads
            result = RemoteUploads(self.policy['uploads'], self.principal, account['role'], now=self.now).handle(action, parameters)
        elif action == 'list':
            require(parameters == {})
            result = {'instances': sorted(i for i in account['instances'] if
                      account['role'] != 'student' or self.policy['instances'][i]['owner'] == self.principal)}
        elif action.startswith('lease-'):
            require('instance_uuid' in parameters)
            identity=uuid_text(parameters['instance_uuid'])
            fields={'lease-acquire':{'instance_uuid','lease_id','ttl_seconds','expiry_action'},
                    'lease-renew':{'instance_uuid','lease_id','renewal_id','ttl_seconds'},
                    'lease-release':{'instance_uuid','lease_id'},'lease-status':{'instance_uuid'}}
            require(set(parameters)==fields[action])
            manager=self.leases()
            if action=='lease-acquire':result=manager.acquire(identity,parameters['lease_id'],parameters['ttl_seconds'],parameters['expiry_action'])
            elif action=='lease-renew':result=manager.renew(identity,parameters['lease_id'],parameters['renewal_id'],parameters['ttl_seconds'])
            elif action=='lease-release':result=manager.release(identity,parameters['lease_id'])
            else:result=manager.status(identity)
        else:
            require('instance_uuid' in parameters)
            identity = uuid_text(parameters['instance_uuid'])
            require(identity in account['instances'], 'permission-denied')
            entry = self.policy['instances'][identity]
            require(account['role'] != 'student' or entry['owner'] == self.principal, 'permission-denied')
            require(set(parameters) in (({'instance_uuid','request'}, {'instance_uuid','request','lease_id'}) if action=='submit' and 'leases' in self.policy else
                                      ({'instance_uuid', 'request'},) if action == 'submit' else
                                      ({'instance_uuid', 'after'},) if action == 'events' else ({'instance_uuid'},)))
            if action == 'submit':
                from ctflab_contract import validate_request
                request = validate_request(parameters['request'])
                require(request['instance_uuid'] == identity, 'permission-denied')
                # 已到期主体仍可查询、取消或正常停止，不能启动/重置/改配置。
                expiry = datetime.fromisoformat(account['expires'].replace('Z', '+00:00'))
                require(self.now() < expiry or request['operation'] in ('status', 'cancel', 'stop'), 'permission-denied')
                require(request['operation'] != 'guest' or account['role'] != 'student', 'permission-denied')
            from ctflab_generation_store import GenerationStore
            root = guard(Path(entry['root']))
            store = GenerationStore(root)
            require(store.config['instance_uuid'] == identity, 'identity-unknown')
            payload = {'action': action}
            if action == 'submit': payload['request'] = parameters['request']
            if action == 'events': payload['after'] = parameters['after']
            if action=='submit' and 'leases' in self.policy:
                result=self.leases().submit(identity,parameters['request'],parameters.get('lease_id'))
            else:result = self.dispatch(root, payload)
        return {'protocol': PROTOCOL, 'version': 1, 'request_id': value['request_id'],
                'server_uuid': self.policy['server_uuid'], 'result': result}


def ssh_arguments(config,*,purpose='runner'):
    require(purpose in ('runner','external','external-l2'))
    require(type(config) is dict and set(config) == {'schema', 'host', 'port', 'user', 'ssh', 'identity',
             'known_hosts', 'known_hosts_sha256', 'server_uuid'})
    require(type(config['schema']) is int and config['schema'] == 1)
    uuid_text(config['server_uuid'])
    require(isinstance(config['host'], str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', config['host']))
    require(isinstance(config['user'], str) and re.fullmatch(r'[a-z_][a-z0-9_-]{0,63}', config['user']))
    require(type(config['port']) is int and 1 <= config['port'] <= 65535)
    for key in ('ssh', 'identity', 'known_hosts'):
        require(isinstance(config[key], str) and Path(config[key]).is_absolute())
    # OpenSSH对带空白路径的配置值再解析；拒绝有歧义的参数值。
    require(not any(c.isspace() or c in '%"\'\\#\r\n' for c in config['known_hosts']))
    known = guard(Path(config['known_hosts'])); guard(Path(config['identity']))
    require(known.is_file() and digest(known) == config['known_hosts_sha256'], 'identity-unknown')
    binary = Path(config['ssh'])
    require(binary.name in ('ssh', 'ssh.exe') and binary.is_file(), 'capability-unverified')
    return [str(binary), '-F', 'none', '-T', '-a', '-x', '-e', 'none',
            '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'UserKnownHostsFile='+str(known), '-o', 'GlobalKnownHostsFile=none',
            '-o', 'UpdateHostKeys=no', '-o', 'VerifyHostKeyDNS=no',
            '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none',
            '-o', 'ClearAllForwardings=yes', '-o', 'PermitLocalCommand=no',
            '-o', 'ProxyCommand=none', '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
            '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
            '-i', config['identity'], '-p', str(config['port']), '-l', config['user'], config['host'],
            {'runner':COMMAND,'external':'ctflab-external-v1','external-l2':'ctflab-external-l2-v1'}[purpose]]


def exchange(config, request, *, timeout=30):
    """只运行固定SSH客户端；超时仅结束自有传输进程，不重放远程请求。"""
    require(type(timeout) in (int, float) and 0 < timeout <= 120)
    require(request.get('server_uuid') == config['server_uuid'], 'identity-unknown')
    raw = canonical(request).encode(); require(len(raw) <= MAX_MESSAGE_BYTES)
    command = ssh_arguments(config)
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               close_fds=True, env={**os.environ, 'SSH_ASKPASS_REQUIRE': 'never'})
    collected = bytearray(); failure = []
    def read():
        try:
            while True:
                block = process.stdout.read1(65536)
                if not block: break
                if len(collected)+len(block) > RESPONSE_LIMIT:
                    failure.append('response-limit'); process.terminate(); break
                collected.extend(block)
        except OSError: failure.append('transport-failed')
        finally: process.stdout.close()
    def write():
        try: process.stdin.write(raw); process.stdin.close()
        except OSError: failure.append('input-failed')
        finally:
            if not process.stdin.closed: process.stdin.close()
    reader = threading.Thread(target=read, daemon=True); writer = threading.Thread(target=write, daemon=True)
    reader.start(); writer.start()
    try:
        code = process.wait(timeout=timeout)
        reader.join(timeout=2); writer.join(timeout=2)
        require(not reader.is_alive() and not writer.is_alive() and not failure and code == 0, 'control-unreachable')
    except BaseException:
        if process.poll() is None: process.kill(); process.wait(timeout=5)
        reader.join(timeout=2); writer.join(timeout=2)
        raise
    result = decode(bytes(collected), RESPONSE_LIMIT)
    require(set(result) == {'protocol', 'version', 'request_id', 'server_uuid', 'result'}
            and result['protocol'] == PROTOCOL and type(result['version']) is int and result['version'] == 1
            and result['request_id'] == request['request_id'] and result['server_uuid'] == config['server_uuid'], 'identity-unknown')
    return result


class SSHSession:
    """单个固定SSH命令上的有界JSONL通道；按请求关联，不自动重发。"""
    def __init__(self, config, *, timeout=30,cancel_requested=None,purpose='runner'):
        require(type(timeout) in (int, float) and 0 < timeout <= 120)
        self.config, self.timeout = config, timeout
        self.messages = queue.Queue(maxsize=2); self.lock = threading.Lock(); self.closed = False
        self.cancel_requested=cancel_requested
        self.check_cancel()
        require(purpose in ('runner','external','external-l2'))
        arguments=ssh_arguments(config) if purpose=='runner' else ssh_arguments(config,purpose=purpose)
        self.process = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, close_fds=True,
                                        env={**os.environ, 'SSH_ASKPASS_REQUIRE': 'never'})
        self.reader = threading.Thread(target=self.read, daemon=True); self.reader.start()

    def check_cancel(self):
        require(not (self.cancel_requested and self.cancel_requested()),'operation-finished')

    def read(self):
        try:
            while True:
                raw = self.process.stdout.readline(RESPONSE_LIMIT+2)
                if not raw: self.messages.put_nowait(None); break
                if len(raw) > RESPONSE_LIMIT+1 or not raw.endswith(b'\n'):
                    self.process.terminate(); self.messages.put_nowait(None); break
                self.messages.put_nowait(raw[:-1])
        except (OSError, queue.Full):
            if self.process.poll() is None: self.process.terminate()
        finally: self.process.stdout.close()

    def request(self, action, parameters):
        with self.lock:
            require(not self.closed, 'control-unreachable')
            request = {'protocol': PROTOCOL, 'version': 1, 'request_id': str(uuid.uuid4()),
                       'server_uuid': self.config['server_uuid'], 'action': action, 'parameters': parameters}
            raw = (canonical(request)+'\n').encode(); require(len(raw) <= MAX_MESSAGE_BYTES+1)
            failure = []
            def send():
                try: self.process.stdin.write(raw); self.process.stdin.flush()
                except OSError: failure.append(True)
            writer = threading.Thread(target=send, daemon=True)
            try:
                self.check_cancel();writer.start()
                if self.cancel_requested is None:writer.join(timeout=self.timeout)
                else:
                    deadline=time.monotonic()+self.timeout
                    while writer.is_alive() and time.monotonic()<deadline:
                        self.check_cancel();writer.join(timeout=min(.1,max(0,deadline-time.monotonic())))
                require(not writer.is_alive() and not failure, 'control-unreachable')
                if self.cancel_requested is None:reply=self.messages.get(timeout=self.timeout)
                else:
                    deadline=time.monotonic()+self.timeout
                    while True:
                        self.check_cancel();remaining=deadline-time.monotonic()
                        if remaining<=0:raise queue.Empty()
                        try:reply=self.messages.get(timeout=min(.1,remaining));break
                        except queue.Empty:continue
                    self.check_cancel()
                require(reply is not None, 'control-unreachable')
                result = decode(reply, RESPONSE_LIMIT)
                require(set(result) == {'protocol', 'version', 'request_id', 'server_uuid', 'result'}
                        and result['protocol'] == PROTOCOL and type(result['version']) is int and result['version'] == 1
                        and result['request_id'] == request['request_id'] and result['server_uuid'] == request['server_uuid'], 'identity-unknown')
                return result['result']
            except BaseException as exc:
                self.close(failed=True)
                if writer.ident is not None:writer.join(timeout=2)
                if isinstance(exc, queue.Empty): require(False, 'control-unreachable')
                raise

    def close(self, *, failed=False):
        if self.closed: return
        self.closed = True
        if failed and self.process.poll() is None: self.process.kill()
        try: self.process.stdin.close()
        except OSError: pass
        try: self.process.wait(timeout=5)
        except subprocess.TimeoutExpired: self.process.kill(); self.process.wait(timeout=5)
        self.reader.join(timeout=2)

    def __enter__(self): return self
    def __exit__(self, *args): self.close(failed=args[0] is not None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    serve = sub.add_parser('serve'); serve.add_argument('--policy', type=Path, required=True)
    serve.add_argument('--principal', required=True)
    client = sub.add_parser('request'); client.add_argument('--config', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'serve':
            require(sys.platform == 'linux' and os.geteuid() != 0, 'unsupported-platform')
            require(os.environ.get('SSH_ORIGINAL_COMMAND') == COMMAND, 'permission-denied')
            from ctflab_remote_display import DisplayPool
            with DisplayPool() as displays:
                for _ in range(1000000):
                    raw = sys.stdin.buffer.readline(MAX_MESSAGE_BYTES+2)
                    if not raw:return 0
                    require(len(raw.rstrip(b'\n'))<=MAX_MESSAGE_BYTES)
                    # 每条消息重读权限，显示会话同样不能沿用撤销scope或旧期限。
                    result=Runner(private_json(args.policy),args.principal,policy_path=args.policy,display_pool=displays).exchange(decode(raw.rstrip(b'\n')))
                    output=canonical(result);require(len(output.encode())<=RESPONSE_LIMIT)
                    print(output,flush=True)
                return 0
        raw = sys.stdin.buffer.read(MAX_MESSAGE_BYTES+1); value = decode(raw)
        result = exchange(private_json(args.config), value)
        output = canonical(result); require(len(output.encode()) <= RESPONSE_LIMIT)
        print(output); return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError, sqlite3.Error):
        print(canonical({'state': 'unknown', 'automatic_replay': False, 'preserved': True})); return 2


if __name__ == '__main__': raise SystemExit(main())
