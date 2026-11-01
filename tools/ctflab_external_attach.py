"""外部攻击机二层接入契约：登记/绑定/静态预约/槽位规划与会话凭据；不创建端点或操作VM。

本模块只做计划层校验与凭据派生。外部Kali不进入镜像导入、启动顺序、整课重置或删除；
未预留external槽位的运行中实验不热改。既有无external字段的计划保持原语义。
"""
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import time
from pathlib import Path

if __package__ in (None, ''):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctflab_contract import canonical, require, uuid_text, identifier, ContractError

COMMAND = 'ctflab-external-l2-v1'
GUEST_COMMAND = 'ctflab-kali-attach-v1'
KIND = 'kali-l2-v1'
ETHER_TYPES = ('0x0800', '0x0806')  # 首版只放行IPv4与ARP；VLAN/IPv6等显式拒绝。
MAX_FRAME = 1514
DEFAULT_MTU = 1400
LIMIT_DEFAULTS = {'max_frames_per_second': 1000, 'burst_frames': 250,
                  'max_bytes': 2**30, 'max_seconds': 7200, 'queue_frames': 256}
LIMIT_BOUNDS = {'max_frames_per_second': (1, 100000), 'burst_frames': (1, 100000),
                'max_bytes': (2**20, 8 * 2**30), 'max_seconds': (60, 86400),
                'queue_frames': (16, 4096)}
MAC_PATTERN = r'02(?::[0-9a-f]{2}){5}'

# 来宾身份策略：按虚拟化家族登记可识别的DMI厂商/产品组合。
# 身份未识别一律拒绝，不放宽为仅凭IP或客户端自报授权；Fusion/ARM等平台的
# DMI可读性属实机核验，材料与本策略不据此声明支持。
GUEST_IDENTITY_FAMILIES = {
    'vmware': (('VMware, Inc.', 'VMware Virtual Platform'),
               ('VMware, Inc.', 'VMware7,1'),
               ('VMware, Inc.', 'VMware20,1')),
    'parallels': (('Parallels International GmbH.', 'Parallels ARM Virtual Machine'),
                  ('Parallels International GmbH', 'Parallels Virtual Platform'),
                  ('Parallels Software International Inc.', 'Parallels Virtual Platform')),
    'utm-qemu': (('QEMU', 'Standard PC (Q35 + ICH9, 2009)'),
                 ('QEMU', 'QEMU Virtual Machine'),
                 ('UTM', 'QEMU Virtual Machine')),
    'virtualbox': (('innotek GmbH', 'VirtualBox'),
                   ('Oracle Corporation', 'VirtualBox')),
    'hyperv': (('Microsoft Corporation', 'Virtual Machine'),),
}


def classify_guest_identity(vendor, product):
    """返回虚拟化家族；未识别组合拒绝，不提供跳过身份检查的旁路。"""
    require(type(vendor) is str and type(product) is str, 'invalid-request')
    for family, combinations in GUEST_IDENTITY_FAMILIES.items():
        for known_vendor, known_product in combinations:
            if vendor.strip() == known_vendor and product.strip() == known_product:
                return family
    raise ContractError('identity-unknown')


def mac_bytes(text):
    parts = str(text).lower().split(':')
    require(len(parts) == 6 and re.fullmatch(MAC_PATTERN, str(text).lower()) is not None,
            'invalid-request')
    return bytes(int(part, 16) for part in parts)


def mac_text(raw):
    return ':'.join(f'{value:02x}' for value in raw[:6])


def validate_limits(value):
    merged = dict(LIMIT_DEFAULTS)
    require(type(value) is dict and set(value) <= set(LIMIT_DEFAULTS), 'invalid-request')
    for key, (low, high) in LIMIT_BOUNDS.items():
        if key in value:
            require(type(value[key]) is int and low <= value[key] <= high, 'invalid-request')
            merged[key] = value[key]
    require(merged['burst_frames'] <= merged['queue_frames'], 'invalid-request')
    return merged


def _parse_expiry(text):
    from datetime import datetime
    require(type(text) is str and text.endswith('Z'), 'invalid-request')
    moment = datetime.fromisoformat(text.replace('Z', '+00:00'))
    require(moment.tzinfo is not None, 'invalid-request')
    return moment


def validate_attachment(value):
    """external槽位规范：绑定实例/代次/网段与静态地址；由调用方核对与节点地址/DHCP池不冲突。"""
    fields = {'schema', 'kind', 'instance_uuid', 'generation', 'network_id', 'cidr',
              'address', 'mac', 'mtu', 'limits', 'expires'}
    require(type(value) is dict and set(value) == fields, 'invalid-request')
    require(type(value['schema']) is int and value['schema'] == 1
            and value['kind'] == KIND, 'invalid-request')
    uuid_text(value['instance_uuid'])
    require(type(value['generation']) is int and 1 <= value['generation'] <= 2**31 - 1,
            'invalid-request')
    identifier(value['network_id'])
    require(type(value['cidr']) is str, 'invalid-request')
    subnet = ipaddress.IPv4Network(value['cidr'], strict=True)
    require(16 <= subnet.prefixlen <= 30
            and any(subnet.subnet_of(ipaddress.IPv4Network(block))
                    for block in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')),
            'invalid-request')
    address = ipaddress.IPv4Address(value['address'])
    require(type(value['address']) is str and address in subnet
            and address not in (subnet.network_address, subnet.broadcast_address),
            'invalid-request')
    mac_bytes(value['mac'])
    require(value['mtu'] == DEFAULT_MTU, 'invalid-request')
    validate_limits(value['limits'])
    _parse_expiry(value['expires'])
    return value


def validate_ssh_reference(value):
    """接入SSH引用只做契约层校验；文件存在性与固定入口在连接时按 ctflab_remote 复核。"""
    fields = {'host', 'port', 'user', 'identity'}
    require(type(value) is dict and set(value) == fields, 'invalid-request')
    require(type(value['host']) is str
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', value['host']) is not None,
            'invalid-request')
    require(type(value['port']) is int and 1 <= value['port'] <= 65535, 'invalid-request')
    require(type(value['user']) is str
            and re.fullmatch(r'[a-z_][a-z0-9_-]{0,63}', value['user']) is not None,
            'invalid-request')
    require(is_absolute_host_path(value['identity']), 'invalid-request')
    return value


def validate_registration(value):
    """登记一条外部攻击机；身份未知不得放宽为仅凭IP授权。"""
    fields = {'schema', 'kind', 'name', 'node_uuid', 'machine_uuid', 'vendor', 'product',
              'ssh', 'assistant_sha256'}
    require(type(value) is dict and set(value) in (fields, fields | {'identity_family'}),
            'invalid-request')
    require(type(value['schema']) is int and value['schema'] == 1
            and value['kind'] == KIND, 'invalid-request')
    require(type(value['name']) is str and 0 < len(value['name']) <= 64
            and not any(c in value['name'] for c in '\x00\r\n'), 'invalid-request')
    uuid_text(value['node_uuid'])
    uuid_text(value['machine_uuid'])
    require(type(value['vendor']) is str and 0 < len(value['vendor']) <= 128
            and type(value['product']) is str and 0 < len(value['product']) <= 128,
            'invalid-request')
    # 厂商/产品必须命中来宾身份策略；DMI不可读时仍以machine_uuid+助手摘要+主机密钥
    # 组合绑定，不关闭身份检查。策略外组合按identity-unknown拒绝。
    value['identity_family'] = classify_guest_identity(value['vendor'], value['product'])
    validate_ssh_reference(value['ssh'])
    require(type(value['assistant_sha256']) is str
            and re.fullmatch(r'[0-9a-f]{64}', value['assistant_sha256']) is not None,
            'invalid-request')
    return value


def validate_network_external(network):
    """场景v2网段可选external槽位：{'address','mac'}；与节点地址/MAC全局查重由场景校验完成。"""
    require(type(network) is dict and 'cidr' in network, 'invalid-request')
    if 'external' not in network:
        return None
    fields = {'schema', 'address', 'mac'}
    slot = network['external']
    require(type(slot) is dict and set(slot) == fields and slot['schema'] == 1,
            'invalid-request')
    subnet = ipaddress.IPv4Network(network['cidr'], strict=True)
    address = ipaddress.IPv4Address(slot['address'])
    require(type(slot['address']) is str and address in subnet
            and address not in (subnet.network_address, subnet.broadcast_address),
            'invalid-request')
    mac_bytes(slot['mac'])
    return {'address': slot['address'], 'mac': slot['mac'].lower()}


def validate_hub_networks(plan, ports):
    """通用hub规划的端口槽位校验：external只接受dict形式，二成员整数直连不得携带external。

    未声明external时保持旧契约：dict键必须恰为非中心成员；声明external时额外
    要求含'external'接入口端口。
    """
    from ctflab_qemu_driver import network_members
    require(type(ports) is dict and set(ports) == set(plan['manifest']['networks']))
    flattened = []
    external = {}
    for network, value in ports.items():
        slot = plan['manifest']['networks'][network].get('external') if type(
            plan['manifest']['networks'][network]) is dict else None
        members = network_members(plan, network)
        if type(value) is int:
            # 旧契约：仅二成员直连接受整数端口，且不得携带external槽位。
            require(len(members) == 2 and slot is None, 'invalid-request')
            flattened.append(value)
            continue
        require(type(value) is dict, 'invalid-request')
        require(set(value) - {'external'} == set(members[1:]), 'invalid-request')
        if slot is not None:
            # 计划声明槽位则端口规划必须携带预留口；否则槽位会被静默丢弃。
            require('external' in value, 'invalid-request')
        if 'external' in value:
            require(slot is not None and type(value['external']) is int
                    and 1024 <= value['external'] <= 65535, 'invalid-request')
            external[network] = value['external']
            flattened.append(value['external'])
        for key, port in value.items():
            if key == 'external':
                continue
            require(type(port) is int and 1024 <= port <= 65535, 'invalid-request')
            flattened.append(port)
    require(all(type(p) is int and 1024 <= p <= 65535 for p in flattened))
    return flattened, external


def derive_allowed_macs(plan, network_id, *, server_mac=None):
    """从实例计划派生网段授权节点MAC集合；生产装配与测试共用同一来源。

    计划MAC必须已派生（instance_plan之后）；交换机后端额外并入DHCP服务器MAC。
    """
    require(type(plan) is dict and type(plan.get('manifest')) is dict, 'invalid-request')
    require(network_id in plan['manifest']['networks'], 'invalid-request')
    macs = set()
    for node in plan['manifest']['nodes'].values():
        for nic in node.get('interfaces', []):
            if nic['network'] != network_id:
                continue
            mac = str(nic['mac']).lower()
            require(mac != 'derived', 'invalid-request')
            mac_bytes(mac)
            macs.add(mac)
    if server_mac:
        macs.add(str(server_mac).lower())
    return sorted(macs)


ABSOLUTE_HOST_PATH = re.compile(r'^(?:/|\\\\|\\|[A-Za-z]:[\\/])')


def is_absolute_host_path(text):
    """跨平台绝对路径判定：POSIX /、Windows 盘符与UNC均为绝对。"""
    return type(text) is str and 0 < len(text) <= 4096 \
        and ABSOLUTE_HOST_PATH.match(text) is not None


HANDSHAKE_HOST = 'ctflab-external-l2/1'
HANDSHAKE_GUEST = 'ctflab-kali-attach/1'


def handshake_record(session_uuid, attachment, policy, *, challenge=None):
    """宿主→来宾握手记录：绑定会话/实例/代次/网段/策略摘要与一次性挑战。"""
    validate_attachment(attachment)
    challenge = challenge or secrets.token_hex(16)
    require(type(challenge) is str and re.fullmatch(r'[0-9a-f]{32}', challenge) is not None,
            'invalid-request')
    record = {'handshake': HANDSHAKE_HOST, 'session_uuid': session_uuid,
              'instance_uuid': attachment['instance_uuid'],
              'generation': attachment['generation'],
              'network_id': attachment['network_id'],
              'mac': attachment['mac'].lower(), 'address': attachment['address'],
              'mtu': attachment['mtu'],
              'policy_sha256': policy['policy_sha256'], 'challenge': challenge}
    return record, challenge


def verify_guest_handshake(reply, *, registration, session_uuid, challenge):
    """核验来宾握手：会话/挑战回显、助手摘要必须匹配；机器UUID不匹配即拒绝，
    未登记替代身份策略时，来宾机器UUID不可读也拒绝。"""
    require(type(reply) is dict
            and reply.get('handshake') == HANDSHAKE_GUEST
            and reply.get('session_uuid') == session_uuid
            and reply.get('challenge_echo') == challenge, 'identity-unknown')
    require(reply.get('assistant_sha256') == registration['assistant_sha256'],
            'identity-unknown')
    machine = reply.get('machine_uuid')
    require(machine == registration['machine_uuid'], 'identity-unknown')
    return {'identity_state': 'verified', 'identity_binding': 'dmi-machine-uuid',
            'machine_uuid': machine}


def policy_summary(attachment, allowed_macs):
    """帧门禁策略摘要；进入会话绑定与UI预览，策略变化即旧会话失效。"""
    validate_attachment(attachment)
    require(type(allowed_macs) is list and len(allowed_macs) <= 64
            and all(type(item) is str for item in allowed_macs), 'invalid-request')
    payload = {'schema': 1, 'kind': KIND,
               'instance_uuid': attachment['instance_uuid'],
               'generation': attachment['generation'],
               'network_id': attachment['network_id'],
               'cidr': str(ipaddress.IPv4Network(attachment['cidr'])),
               'address': attachment['address'], 'mac': attachment['mac'].lower(),
               'mtu': attachment['mtu'], 'ether_types': list(ETHER_TYPES),
               'allowed_macs': sorted(mac.lower() for mac in allowed_macs),
               'limits': validate_limits(attachment['limits'])}
    return {'policy_sha256': hashlib.sha256(canonical(payload).encode()).hexdigest(),
            'policy': payload}


def prepare_session(attachment, policy, *, session_uuid=None):
    """生成可由管理员批准的固定会话命令；桌面和CLI共用，不部署来宾。"""
    from ctflab_kali_attach import setup_command, shell_command, teardown_command
    validate_attachment(attachment)
    require(policy['policy']['allowed_macs'], 'invalid-request')
    require(policy_summary(attachment, policy['policy']['allowed_macs']) == policy, 'state-conflict')
    session_uuid = session_uuid or str(__import__('uuid').uuid4())
    uuid_text(session_uuid)
    prefix = ipaddress.IPv4Network(attachment['cidr']).prefixlen
    setup = setup_command(session_uuid, attachment['mac'], attachment['address'], prefix)
    setup += (f" --instance-uuid {attachment['instance_uuid']} --generation {attachment['generation']}"
              f" --network-id {attachment['network_id']} --policy-sha256 {policy['policy_sha256']}")
    return {'session_uuid': session_uuid, 'policy_sha256': policy['policy_sha256'],
            'setup_command': setup, 'shell_command': shell_command(session_uuid),
            'teardown_command': teardown_command(session_uuid)}


def attachment_digest(value):
    return hashlib.sha256(canonical(validate_attachment(value)).encode()).hexdigest()


# ---------- 助手安装批准账本（设计§4.3持久批准/固定安装摘要） ----------

APPROVAL_KIND = 'ctflab-external-attach-approval'
APPROVAL_FILE = 'assistant-approvals.jsonl'
MATERIALS_KIND = 'ctflab-kali-attach-materials'


def materials_assistant_digest(manifest):
    """从本机生成的材料清单提取固定安装摘要；清单形态不符即拒绝。"""
    require(type(manifest) is dict and manifest.get('schema') == 1
            and manifest.get('kind') == MATERIALS_KIND
            and isinstance(manifest.get('files'), dict), 'invalid-request')
    assistant_digest = manifest['files'].get('ctflab-kali-attach')
    require(type(assistant_digest) is str
            and re.fullmatch(r'[0-9a-f]{64}', assistant_digest) is not None,
            'invalid-request')
    return hashlib.sha256(canonical(manifest).encode()).hexdigest(), assistant_digest


def _approval_entry(value):
    require(type(value) is dict and value.get('schema') == 1
            and value.get('kind') == APPROVAL_KIND
            and set(value) == {'schema', 'kind', 'node_uuid', 'machine_uuid',
                               'assistant_sha256', 'manifest_sha256', 'approved_at'},
            'invalid-request')
    uuid_text(value['node_uuid'])
    uuid_text(value['machine_uuid'])
    for field in ('assistant_sha256', 'manifest_sha256'):
        require(type(value[field]) is str
                and re.fullmatch(r'[0-9a-f]{64}', value[field]) is not None,
                'invalid-request')
    require(type(value['approved_at']) is str and value['approved_at'], 'invalid-request')
    return value


def load_assistant_approvals(ledger_dir):
    """读取批准账本；损坏行整体拒绝，不静默跳过，不猜测原意。"""
    path = Path(ledger_dir) / APPROVAL_FILE
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return []
    entries = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            entries.append(_approval_entry(json.loads(line)))
        except (ValueError, ContractError):
            raise ContractError('approval-ledger-corrupt')
    return entries


def approve_assistant(registration, manifest, ledger_dir, *, approved_at=None):
    """持久批准：登记的助手摘要必须与本机材料清单一致，绑定写入私有账本。

    同节点+机器+摘要的批准幂等，不重复追加；清单摘要变化或换机器须重新
    批准。账本目录与文件保持私有（0700/0600），追加后fsync。
    """
    registration = validate_registration(registration)
    manifest_sha256, assistant_digest = materials_assistant_digest(manifest)
    require(registration['assistant_sha256'] == assistant_digest,
            'assistant-digest-mismatch')
    record = _approval_entry({'schema': 1, 'kind': APPROVAL_KIND,
                              'node_uuid': registration['node_uuid'],
                              'machine_uuid': registration['machine_uuid'],
                              'assistant_sha256': registration['assistant_sha256'],
                              'manifest_sha256': manifest_sha256,
                              'approved_at': approved_at or now_iso()})
    for entry in load_assistant_approvals(ledger_dir):
        if (entry['node_uuid'] == record['node_uuid']
                and entry['machine_uuid'] == record['machine_uuid']
                and entry['assistant_sha256'] == record['assistant_sha256']):
            return dict(entry, duplicate=True)
    directory = Path(ledger_dir)
    if directory.exists() and (not directory.is_dir() or directory.is_symlink()):
        raise ContractError('invalid-request')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    descriptor = os.open(directory / APPROVAL_FILE,
                         os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, (canonical(record) + '\n').encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return record


def require_approved_assistant(registration, ledger_dir):
    """连接前核验：节点+机器+摘要组合已有持久批准；未批准按identity-unknown拒绝。"""
    registration = validate_registration(registration)
    match = [entry for entry in load_assistant_approvals(ledger_dir)
             if entry['node_uuid'] == registration['node_uuid']
             and entry['machine_uuid'] == registration['machine_uuid']]
    require(match, 'identity-unknown')
    require(any(entry['assistant_sha256'] == registration['assistant_sha256']
                for entry in match), 'identity-unknown')
    return match[-1]


def approval_ledger_dir():
    """批准账本目录的统一解析：显式环境变量优先，其次隔离profile根，否则默认。

    CTFLAB_PROFILE_DIR 仅供隔离验收或GUI的临时目录覆盖（与ctflab.py
    user_profile_dir语义一致）；桌面桥接连接路径也用本函数，保证CLI批准与
    桌面强制核验读写同一账本。
    """
    override = os.environ.get('CTFLAB_EXTERNAL_ATTACH_APPROVALS')
    if override:
        return Path(override)
    profile_root = os.environ.get('CTFLAB_PROFILE_DIR')
    if profile_root:
        return Path(profile_root) / 'external-attach'
    return (Path.home() / 'Library' / 'Application Support' / 'CTFLab'
            / 'profiles' / 'external-attach')


def session_secret():
    return secrets.token_hex(32)


def challenge_token(secret, session_uuid, nonce_switch, nonce_relay):
    """交换机接入口的一次性认证令牌；双方同持per-generation秘密。"""
    require(type(secret) is str and re.fullmatch(r'[0-9a-f]{64}', secret) is not None,
            'invalid-request')
    for nonce in (nonce_switch, nonce_relay):
        require(type(nonce) is str and re.fullmatch(r'[0-9a-f]{32}', nonce) is not None,
                'invalid-request')
    uuid_text(session_uuid)
    material = f'ctflab-external-l2/1\n{session_uuid}\n{nonce_switch}\n{nonce_relay}'.encode()
    return hmac.new(bytes.fromhex(secret), material, hashlib.sha256).hexdigest()


class AttachStore:
    """接入意图/会话状态的私有持久化；代次或计划摘要变化即拒绝旧会话。"""

    def __init__(self, root, instance_uuid, *, generation, network_id):
        uuid_text(instance_uuid)
        identifier(network_id)
        self.root = Path(root).absolute()
        require(not self.root.is_symlink(), 'state-conflict')
        self.path = self.root / 'external-attach' / f'{instance_uuid}.json'
        self.instance_uuid = instance_uuid
        self.generation = generation
        self.network_id = network_id

    def _prepare(self):
        directory = self.path.parent
        if os.name == 'nt':
            from ctflab_local_service import _guard_path, _windows_storage
            _guard_path(directory)
            if directory.exists():
                require(directory.is_dir(), 'state-conflict')
                _windows_storage(directory, root=True)
            else:
                _windows_storage(directory, create=True)
            return
        if directory.exists():
            require(directory.is_dir() and not directory.is_symlink(), 'state-conflict')
        else:
            directory.mkdir(mode=0o700, parents=True)
        # macOS /var、/tmp等系统别名先解析，再逐级核对真实组件非链接。
        resolved = Path(directory.resolve())
        for component in [*reversed(resolved.parents), resolved]:
            require(not component.is_symlink(), 'state-conflict')
        info = directory.stat()
        require(info.st_uid == os.getuid(), 'state-conflict')

    def load(self):
        if not self.path.exists():
            return None
        require(self.path.is_file() and not self.path.is_symlink(), 'state-conflict')
        if os.name == 'nt':
            from ctflab_local_service import _guard_path, _windows_storage
            _guard_path(self.path)
            _windows_storage(self.path.parent, root=True)
            _windows_storage(self.path)
        raw = self.path.read_bytes()
        require(len(raw) <= 1024 * 1024, 'state-conflict')
        def unique(pairs):
            value = {}
            for key, item in pairs:
                require(key not in value)
                value[key] = item
            return value
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
        require(type(value) is dict and value.get('schema') == 1
                and value.get('instance_uuid') == self.instance_uuid, 'identity-unknown')
        return value

    def save(self, value):
        require(type(value) is dict and value.get('schema') == 1
                and value.get('instance_uuid') == self.instance_uuid, 'invalid-request')
        self._prepare()
        temporary = self.path.with_suffix('.tmp')
        require(not temporary.is_symlink() and
                (not temporary.exists() or (temporary.is_file() and temporary.stat().st_nlink == 1)),
                'state-conflict')
        if os.name == 'nt':
            from ctflab_local_service import _guard_path, _windows_storage
            _guard_path(temporary)
            if temporary.exists():
                _windows_storage(temporary)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(canonical(value) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == 'nt':
            _windows_storage(temporary)
        temporary.replace(self.path)

    def clear(self):
        self._prepare()
        if self.path.exists():
            if os.name == 'nt':
                from ctflab_local_service import _guard_path, _windows_storage
                _guard_path(self.path)
                _windows_storage(self.path)
            self.path.unlink()


def check_generation(binding, *, instance_uuid, generation, plan_sha256):
    """代次/计划摘要一致才允许复用接入意图；恢复快照或新计划使旧意图失效。"""
    require(type(binding) is dict and binding.get('schema') == 1, 'identity-unknown')
    require(binding.get('instance_uuid') == instance_uuid
            and binding.get('generation') == generation
            and binding.get('plan_sha256') == plan_sha256, 'identity-unknown')


def now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def monotonic():
    return time.monotonic()


# ---------- 宿主中转：固定SSH入口 <-> 认证外部端口 ----------

class FrameChannel:
    """固定SSH入口；管道由两个搬运线程持有，主循环只等待跨平台socket。

    socket缓冲有界，没有无限队列；阻塞的管道写只发生在专用线程内。
    关闭先终止本通道持有的SSH子进程，确保管道读写可收口，再关闭文件对象。
    """

    def __init__(self, ssh_config, *, purpose='external-l2', spawn=None):
        from ctflab_remote import ssh_arguments
        require(purpose == 'external-l2', 'invalid-request')
        self.arguments = ssh_arguments(ssh_config, purpose=purpose)
        self.process = (spawn or self._spawn)(self.arguments)
        require(hasattr(self.process, 'stdin') and hasattr(self.process, 'stdout'),
                'control-unreachable')
        try:
            self._start_transport()
        except BaseException:
            self.close()
            raise

    def _spawn(self, arguments):
        import subprocess
        return subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, close_fds=True, bufsize=0)

    def _start_transport(self):
        import socket, threading
        self.readable, self._pipe_socket = socket.socketpair()
        for peer in (self.readable, self._pipe_socket):
            peer.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
            peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        self.readable.setblocking(False)
        self._pipe_socket.settimeout(0.1)
        self._closing = threading.Event()
        self._stop = None
        self._expired = None
        self.io_timeout = 5.0
        self._failure = None
        self._threads = [threading.Thread(target=self._from_pipe, daemon=True,
                                           name='ctflab-ssh-output'),
                         threading.Thread(target=self._to_pipe, daemon=True,
                                           name='ctflab-ssh-input')]
        for worker in self._threads:
            worker.start()

    def configure_io(self, *, stop=None, expired=None, timeout=5.0):
        require(type(timeout) in (int, float) and 0 < timeout <= 30, 'invalid-request')
        self._stop, self._expired, self.io_timeout = stop, expired, timeout

    def _from_pipe(self):
        import socket
        source = getattr(self.process.stdout, 'raw', self.process.stdout)
        try:
            while not self._closing.is_set():
                chunk = source.read(65536)
                if not chunk:
                    break
                view = memoryview(chunk)
                while view and not self._closing.is_set():
                    try:
                        count = self._pipe_socket.send(view)
                        if count == 0:
                            raise OSError('ssh-output-closed')
                        view = view[count:]
                    except socket.timeout:
                        continue
        except (OSError, ValueError) as error:
            if not self._closing.is_set():
                self._failure = error
        finally:
            try:
                self._pipe_socket.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    def _to_pipe(self):
        import socket
        sink = getattr(self.process.stdin, 'raw', self.process.stdin)
        try:
            while not self._closing.is_set():
                try:
                    chunk = self._pipe_socket.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                view = memoryview(chunk)
                while view and not self._closing.is_set():
                    count = sink.write(view)
                    if count is None or count <= 0:
                        raise OSError('ssh-input-closed')
                    view = view[count:]
                sink.flush()
        except (OSError, ValueError) as error:
            if not self._closing.is_set():
                self._failure = error
        finally:
            try:
                self._pipe_socket.shutdown(socket.SHUT_RD)
            except OSError:
                pass

    def _check_io(self, deadline):
        if self._closing.is_set() or (self._stop is not None and self._stop()):
            raise InterruptedError('ssh-channel-stopped')
        if self._expired is not None and self._expired():
            raise TimeoutError('ssh-session-expired')
        if self._failure is not None:
            raise OSError('ssh-pipe-failed') from self._failure
        if time.monotonic() >= deadline:
            raise TimeoutError('ssh-io-timeout')

    def read(self, size):
        import select
        deadline = getattr(self, '_record_deadline', None) or time.monotonic() + self.io_timeout
        buffer = bytearray()
        while len(buffer) < size:
            self._check_io(deadline)
            active = select.select([self.readable], [], [], min(0.05, max(0, deadline-time.monotonic())))[0]
            if not active:
                continue
            try:
                chunk = self.readable.recv(size-len(buffer))
            except BlockingIOError:
                continue
            if not chunk:
                raise EOFError('ssh-frame-channel-closed')
            buffer.extend(chunk)
        return bytes(buffer)

    def receive_record(self, stream):
        # 头和payload共享截止时间，防止分段慢传不断延长记录寿命。
        self._record_deadline = time.monotonic() + self.io_timeout
        try:
            return stream.receive(read_source=self.read)
        finally:
            self._record_deadline = None

    def write(self, raw):
        import select
        deadline = time.monotonic() + self.io_timeout
        view = memoryview(raw)
        while view:
            self._check_io(deadline)
            if not select.select([], [self.readable], [], min(0.05, max(0, deadline-time.monotonic())))[1]:
                continue
            try:
                count = self.readable.send(view)
            except BlockingIOError:
                continue
            if count <= 0:
                raise OSError('ssh-frame-channel-closed')
            view = view[count:]
        return len(raw)

    def close(self):
        import socket
        if not hasattr(self, '_closing'):
            # 初始化尚未完成也要回收自己创建的SSH子进程。
            workers = []
        else:
            self._closing.set()
            workers = self._threads
            for peer in (self.readable, self._pipe_socket):
                try:
                    peer.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except TimeoutError:
                self.process.kill()
                self.process.wait(timeout=1)
            except __import__('subprocess').TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        for worker in workers:
            if worker.ident is not None:
                worker.join(timeout=1)
        if any(worker.is_alive() for worker in workers):
            raise OSError('ssh-pipe-cleanup-incomplete')
        for stream in (self.process.stdin, self.process.stdout):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        for name in ('readable', '_pipe_socket'):
            peer = getattr(self, name, None)
            if peer is not None:
                peer.close()


def authenticate_switch(attach_socket, session_uuid, secret, *, nonce_relay=None, recv=None,
                        stop=None, expired=None, timeout=5.0):
    """完成交换机一次性挑战认证；返回套接字。失败即关闭，不重试旧令牌。"""
    import os as _os
    nonce_relay = nonce_relay or _os.urandom(16).hex()
    try:
        attach_socket.settimeout(min(0.1, timeout))
    except OSError:
        pass
    attach_socket.sendall(f'AUTH {session_uuid} {nonce_relay}\n'.encode())
    line = b''
    deadline = time.monotonic() + timeout
    def read_auth(size):
        import socket
        while True:
            if stop is not None and stop():
                raise InterruptedError('auth-stopped')
            if (expired is not None and expired()) or time.monotonic() >= deadline:
                raise TimeoutError('auth-timeout')
            try:
                return attach_socket.recv(size)
            except socket.timeout:
                continue
    reader = recv or read_auth
    while not line.endswith(b'\n'):
        chunk = reader(256)
        if not chunk:
            attach_socket.close()
            raise RuntimeError('auth-closed')
        line += chunk
        if len(line) > AUTH_LIMIT:
            attach_socket.close()
            raise RuntimeError('auth-oversize')
    text = line.decode('ascii', 'replace').strip()
    require(text.startswith('CHALLENGE '), 'permission-denied')
    nonce_switch = text[10:].strip()
    require(len(nonce_switch) == 32 and all(c in '0123456789abcdef' for c in nonce_switch),
            'permission-denied')
    token = challenge_token(secret, session_uuid, nonce_switch, nonce_relay)
    attach_socket.sendall(f'TOKEN {token}\n'.encode())
    verdict = b''
    while not verdict.endswith(b'\n'):
        chunk = reader(256)
        if not chunk:
            attach_socket.close()
            raise RuntimeError('auth-rejected')
        verdict += chunk
        if len(verdict) > AUTH_LIMIT:
            attach_socket.close()
            raise RuntimeError('auth-oversize')
    text = verdict.decode('ascii', 'replace').strip()
    require(text == f'READY {session_uuid}', 'permission-denied')
    return attach_socket


AUTH_LIMIT = 512


def connect_switch(endpoint, *, timeout=5.0):
    import socket
    host, port = endpoint
    require(host in ('127.0.0.1', '::1'), 'permission-denied')
    peer = socket.create_connection((host, port), timeout=timeout)
    peer.settimeout(timeout)
    return peer


def run_relay(ssh_config, attachment, policy, secret, session_uuid, endpoint, *,
              quota=None, clock=monotonic, stop=None, spawn=None, max_idle=15.0,
              on_state=None, channel=None, wait=None, backend='switch',
              registration=None, on_ready=None, heartbeat_seconds=10.0):
    """双向帧泵：SSH记录流 <-> 外部接入口。

    backend='switch'：先完成一次性挑战认证（ctflab_network接入口）。
    backend='hub'：QEMU预留hubport无认证层，中转是唯一客户端，门禁只在中转；
    该端口只绑定127.0.0.1且不在计划外开放。
    握手：发HELLO控制记录并核验来宾回显（会话/挑战/助手摘要/机器身份）；
    on_ready仅在握手通过后调用——SSH、认证、数据端点与来宾就绪前不得报已连接。
    空闲期发送心跳；任一方向结束/超额/过期即撤除本端，不重放旧帧。
    """
    require(backend in ('switch', 'hub'), 'invalid-request')
    import math
    require(all(type(value) in (int, float) and math.isfinite(value) and value > 0
                for value in (max_idle, heartbeat_seconds)), 'invalid-request')
    import select as _select
    from ctflab_external_l2 import (FrameGate, RecordStream, RECORD_FRAME, RECORD_CLOSE,
                                    RECORD_CONTROL, RECORD_HEARTBEAT, control_payload)
    from ctflab_external_l2 import SessionQuota
    validate_attachment(attachment)
    gate = FrameGate(policy['policy'])
    session = quota or SessionQuota(attachment['limits'], clock=clock)
    channel = channel or FrameChannel(ssh_config, spawn=spawn)
    peer = None
    report = None
    try:
        if hasattr(channel, 'configure_io'):
            channel.configure_io(stop=stop, expired=session.expired, timeout=min(5.0, max_idle))
        incoming = getattr(channel, 'readable', channel.process.stdout)
        # 先建立SSH帧通道，再接入外部端口；两步独立报错，状态可区分。
        stream = RecordStream(channel, channel)
        peer = connect_switch(endpoint)
        if backend == 'switch':
            peer.setblocking(True)
            authenticate_switch(peer, session_uuid, secret, stop=stop, expired=session.expired,
                                timeout=min(5.0, max_idle))
        peer.setblocking(False)
        # 会话握手：SSH+认证+端点就绪之后、任何帧转发之前完成。
        hello, challenge = handshake_record(session_uuid, attachment, policy)
        stream.send(RECORD_CONTROL, control_payload(hello))
        reply_record = None
        for _attempt in range(4):
            record = (channel.receive_record(stream) if hasattr(channel, 'receive_record')
                      else stream.receive(read_source=channel.read))
            require(record is not None, 'handshake-closed')
            kind, _sequence, payload = record
            if kind == RECORD_CONTROL:
                reply_record = json.loads(payload.decode())
                break
        identity = verify_guest_handshake(reply_record, registration=registration,
                                          session_uuid=session_uuid, challenge=challenge)
        if on_ready is not None:
            on_ready(identity)
        report = {'frames_to_lab': 0, 'frames_to_kali': 0, 'dropped': 0,
                  'identity_state': identity['identity_state'], 'reason': 'completed'}
        last_traffic = clock()
        last_heartbeat = clock()
        buffer = b''
        partial_since = None
        wait_readable = wait or (lambda readables, timeout: _select.select(
            readables, [], [], timeout)[0])
        while stop is None or not stop():
            if session.expired():
                report['reason'] = 'quota-expired'
                break
            if partial_since is not None and time.monotonic() - partial_since >= min(5.0, max_idle):
                report['reason'] = 'partial-frame-timeout'
                break
            readable = [incoming, peer]
            timeout = max(0.2, min(0.5, max_idle - (clock() - last_traffic),
                                   heartbeat_seconds - (clock() - last_heartbeat)))
            active = wait_readable(readable, max(0.05, timeout))
            if not active:
                if clock() - last_traffic > max_idle:
                    report['reason'] = 'partial-frame-timeout' if buffer else 'idle-timeout'
                    break
                if clock() - last_heartbeat >= heartbeat_seconds:
                    stream.send(RECORD_HEARTBEAT)
                    last_heartbeat = clock()
                continue
            if peer in active:
                try:
                    chunk = peer.recv(65536)
                except BlockingIOError:
                    continue
                except OSError:
                    chunk = b''
                if not chunk:
                    report['reason'] = 'switch-closed'
                    break
                if not buffer:
                    partial_since = time.monotonic()
                buffer += chunk
                while len(buffer) >= 4:
                    length = int.from_bytes(buffer[:4], 'big')
                    if length < 14 or length > 1514:
                        report['reason'] = 'bad-frame-length'
                        break
                    if len(buffer) < 4 + length:
                        break
                    frame = buffer[4:4 + length]
                    buffer = buffer[4 + length:]
                    last_traffic = clock()
                    partial_since = time.monotonic() if buffer else None
                    if gate.egress(frame) and session.consume(len(frame),
                                                               broadcast=frame[:6] == b'\xff' * 6):
                        stream.send(RECORD_FRAME, frame)
                        report['frames_to_kali'] += 1
                    else:
                        report['dropped'] += 1
            if report['reason'] == 'bad-frame-length':
                break
            if incoming in active:
                try:
                    record = (channel.receive_record(stream) if hasattr(channel, 'receive_record')
                              else stream.receive(read_source=channel.read))
                except (InterruptedError, TimeoutError):
                    raise
                except Exception:
                    record = None
                if record is None:
                    report['reason'] = 'ssh-closed'
                    break
                last_traffic = clock()
                kind, _sequence, payload = record
                if kind == RECORD_FRAME:
                    if gate.ingress(payload) and session.consume(len(payload),
                                                                 broadcast=payload[:6] == b'\xff' * 6):
                        _send_frame(peer, payload, stop=stop, expired=session.expired,
                                    timeout=min(5.0, max_idle))
                        report['frames_to_lab'] += 1
                    else:
                        report['dropped'] += 1
                elif kind == RECORD_CLOSE:
                    report['reason'] = 'guest-close'
                    break
                elif kind in (RECORD_CONTROL, RECORD_HEARTBEAT):
                    last_heartbeat = clock()
            if session.expired():
                report['reason'] = 'quota-expired'
                break
        try:
            stream.send(RECORD_CLOSE, b'bye')
        except Exception:
            pass
        return report
    except InterruptedError:
        if report is None or stop is None or not stop():
            raise
        report['reason'] = 'completed'
        return report
    except TimeoutError:
        if report is None:
            raise
        report['reason'] = 'io-timeout'
        return report
    finally:
        if peer is not None:
            try:
                peer.close()
            except OSError:
                pass
        channel.close()


def _send_frame(peer, frame, *, stop=None, expired=None, timeout=5.0):
    from ctflab_network import pad_ethernet_frame
    import struct
    raw = pad_ethernet_frame(frame)
    import select
    packet = memoryview(struct.pack('!I', len(raw)) + raw)
    deadline = time.monotonic() + timeout
    while packet:
        if stop is not None and stop():
            raise InterruptedError('relay-stopped')
        if (expired is not None and expired()) or time.monotonic() >= deadline:
            raise TimeoutError('switch-write-timeout')
        if not select.select([], [peer], [], min(0.05, max(0, deadline-time.monotonic())))[1]:
            continue
        try:
            count = peer.send(packet)
        except BlockingIOError:
            continue
        if count <= 0:
            raise OSError('switch-closed')
        packet = packet[count:]


def bind_ssh_config(ssh_config, registration):
    """连接前绑定完整SSH配置：server_uuid须等于登记node_uuid，并按固定入口预检。"""
    from ctflab_remote import ssh_arguments
    require(type(ssh_config) is dict and type(registration) is dict, 'invalid-request')
    require(ssh_config.get('server_uuid') == registration.get('node_uuid'), 'identity-unknown')
    return ssh_arguments(ssh_config, purpose='external-l2')


# ---------- 命令行入口 ----------

def _load_json(path):
    from ctflab_remote import private_json
    return private_json(path)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    materials_parser = sub.add_parser('materials', help='只生成Kali助手材料目录')
    materials_parser.add_argument('--destination', required=True)
    materials_parser.add_argument('--attachment')
    materials_parser.add_argument('--policy')
    materials_parser.add_argument('--session')
    approve_parser = sub.add_parser('approve',
                                    help='持久批准：绑定登记助手摘要与本机材料清单（私有账本）')
    approve_parser.add_argument('--registration', type=str, required=True)
    approve_parser.add_argument('--materials-manifest', type=str, required=True)
    approve_parser.add_argument('--ledger-dir', type=str, required=True)
    attach_parser = sub.add_parser('connect', help='建立外部攻击机接入会话')
    attach_parser.add_argument('--registration', type=str, required=True)
    attach_parser.add_argument('--attachment', type=str, required=True)
    attach_parser.add_argument('--policy', type=str, required=True)
    attach_parser.add_argument('--ssh-config', type=str, required=True,
                               help='完整SSH配置（ctflab_remote schema，server_uuid须等于登记node_uuid）')
    attach_parser.add_argument('--secret', type=str, required=True)
    attach_parser.add_argument('--endpoint', type=str, required=True,
                               help='交换机接入口 127.0.0.1:端口')
    attach_parser.add_argument('--session', required=True, help='管理员setup已批准的会话UUID（来自准备材料）')
    attach_parser.add_argument('--duration', type=int, help='仅缩短本次会话时限，不扩大批准策略')
    attach_parser.add_argument('--approvals-dir', type=str,
                               help='提供时强制核验助手持久批准；未批准按identity-unknown拒绝')
    attach_parser.add_argument('--mode', choices=('switch', 'hub'), default='switch',
                               help='switch=ctflab_network认证口；hub=QEMU预留口裸连')
    check_parser = sub.add_parser('check', help='校验登记/槽位/策略文件并输出摘要（只读）')
    check_parser.add_argument('--registration', type=str, required=True)
    check_parser.add_argument('--attachment', type=str, required=True)
    check_parser.add_argument('--policy', type=str, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'materials':
            from ctflab_kali_attach import materials
            prepared = None
            if args.attachment or args.policy or args.session:
                require(args.attachment and args.policy, 'invalid-request')
                attachment = validate_attachment(_load_json(args.attachment))
                policy = policy_summary(attachment, _load_json(args.policy)['allowed_macs'])
                prepared = prepare_session(attachment, policy, session_uuid=args.session)
            print(canonical(materials(args.destination, prepared=prepared)))
            return 0
        if args.action == 'approve':
            registration = validate_registration(_load_json(args.registration))
            manifest = _load_json(args.materials_manifest)
            record = approve_assistant(registration, manifest, args.ledger_dir)
            print(canonical({'state': 'assistant-approved', 'approval': record}))
            return 0
        if args.action == 'check':
            registration = validate_registration(_load_json(args.registration))
            attachment = validate_attachment(_load_json(args.attachment))
            policy = policy_summary(attachment, _load_json(args.policy)['allowed_macs'])
            print(canonical({'registration_node': registration['node_uuid'],
                             'attachment_sha256': attachment_digest(attachment),
                             'policy_sha256': policy['policy_sha256']}))
            return 0
        if args.action == 'connect':
            registration = validate_registration(_load_json(args.registration))
            attachment = validate_attachment(_load_json(args.attachment))
            policy = policy_summary(attachment, _load_json(args.policy)['allowed_macs'])
            if args.approvals_dir:
                # 显式提供批准账本时强制核验；未批准的助手摘要不允许建立会话。
                approval = require_approved_assistant(registration, args.approvals_dir)
                require(approval['assistant_sha256'] == registration['assistant_sha256'],
                        'identity-unknown')
            # 连接需要完整SSH配置（固定入口/known_hosts/身份文件）；登记里的ssh只是契约引用。
            ssh_config = _load_json(args.ssh_config)
            bind_ssh_config(ssh_config, registration)
            host, _, port = args.endpoint.rpartition(':')
            require(host == '127.0.0.1', 'permission-denied')
            limits = validate_limits(attachment['limits'])
            if args.duration is not None:
                require(60 <= args.duration <= limits['max_seconds'], 'invalid-request')
                limits['max_seconds'] = args.duration
            session_uuid = uuid_text(args.session)
            require(policy['policy']['allowed_macs'], 'invalid-request')
            from ctflab_external_l2 import SessionQuota
            import signal as _signal
            import threading as _threading
            stopped = _threading.Event()
            for name in ('SIGINT', 'SIGTERM'):
                _signal.signal(getattr(_signal, name), lambda *_: stopped.set())
            report = run_relay(ssh_config, attachment, policy, args.secret,
                               session_uuid, (host, int(port)), stop=stopped.is_set,
                               backend=args.mode, registration=registration,
                               quota=SessionQuota(limits))
            print(canonical({'state': 'detached', 'session_uuid': session_uuid,
                             'report': report, 'automatic_replay': False}))
            return 0
        require(False, 'invalid-request')
    except Exception as error:
        print(canonical({'state': 'failed', 'reason': str(error)[:160],
                         'automatic_replay': False}), flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
