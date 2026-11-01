"""显式VMGenID绑定实例/节点/代次；不操作来宾、热改设备或接管外部VM。"""
import hashlib
import hmac
import os
from pathlib import Path
import secrets
import uuid
from ctflab_contract import canonical, require, uuid_text

MODE = 'managed-generation-v1'
KEY_FILE = 'vmgenid.key'


def enabled(plan, node):
    spec = plan['manifest']['nodes'][node]
    mode = spec.get('vmgenid')
    require(mode is None or mode == MODE)
    if mode is not None:
        require(plan['manifest']['assets'][spec['asset']]['architecture'] == 'x86_64'
                and spec['firmware'] == 'bios', 'capability-unverified')
    return mode is not None


def initialize(root):
    """仅新实例根创建一次随机材料，失败保留现场，不覆盖。"""
    from ctflab_tls_endpoint import guard
    root = guard(Path(root).absolute()); key = secrets.token_bytes(32)
    fd = os.open(root/KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(key); stream.flush(); os.fsync(stream.fileno())
    guard(root/KEY_FILE)
    return {'schema': 1, 'mode': MODE, 'key_sha256': hashlib.sha256(key).hexdigest()}


def declaration(store, plan, node):
    if not enabled(plan, node):return None
    from ctflab_generation_store import regular
    from ctflab_tls_endpoint import guard
    require(plan == store.plan(plan['generation']), 'identity-unknown')
    config = store.config.get('vmgenid')
    require(type(config) is dict and set(config) == {'schema', 'mode', 'key_sha256'}
            and type(config['schema']) is int and config['schema'] == 1 and config['mode'] == MODE,
            'identity-unknown')
    path = guard(regular(store.root/KEY_FILE))
    with path.open('rb') as stream:key = stream.read(33)
    require(len(key) == 32 and type(config['key_sha256']) is str
            and hmac.compare_digest(hashlib.sha256(key).hexdigest(), config['key_sha256']), 'identity-unknown')
    scope = {'schema': 1, 'mode': MODE, 'instance_uuid': uuid_text(plan['instance_uuid']),
             'generation': plan['generation'], 'node': node}
    # 私有256位随机材料上的PRF；不用公开UUID5或每次启动都变化的guid=auto。
    raw = hmac.new(key, b'ctflab-vmgenid-v1\0' + canonical(scope).encode(), hashlib.sha256).digest()[:16]
    scope['guid'] = str(uuid.UUID(bytes=raw, version=4))
    return scope


def checked(value, plan, node):
    if not enabled(plan, node):
        require(value is None, 'identity-unknown'); return None
    fields = {'schema', 'mode', 'instance_uuid', 'generation', 'node', 'guid'}
    require(type(value) is dict and set(value) == fields and type(value['schema']) is int and value['schema'] == 1
            and value['mode'] == MODE and value['instance_uuid'] == plan['instance_uuid']
            and type(value['generation']) is int and value['generation'] == plan['generation']
            and value['node'] == node, 'identity-unknown')
    guid = uuid_text(value['guid'])
    require(uuid.UUID(guid).version == 4 and uuid.UUID(guid).variant == uuid.RFC_4122, 'identity-unknown')
    return value


def verify_qmp(client, value):
    reply = client.command('query-vm-generation-id')
    require(type(reply) is dict and type(reply.get('return')) is dict
            and set(reply['return']) == {'guid'} and reply['return']['guid'] == value['guid'], 'identity-unknown')
    return {'expected_guid': value['guid'], 'qmp_guid_verified': True, 'guest_guid_verified': False,
            'domain_health_verified': False, 'automatic_replay': False}


def verify_launch(spec, attempt):
    """工作器从实际代次目录重建绑定，不能只相信launch中的GUID或调用者给出的状态根。"""
    attempt = Path(attempt).absolute()
    layout = len(attempt.parents) >= 5 and attempt.parents[3].name == 'generations'
    if not layout:
        require('vmgenid' not in spec and not any(type(v) is str and (v == 'vmgenid' or v.startswith('vmgenid,'))
                for v in spec.get('argv',[])), 'identity-unknown'); return
    from ctflab_generation_store import GenerationStore
    store = GenerationStore(attempt.parents[4])
    generation = attempt.parents[2].name.split('-', 1)[0]
    require(generation.isascii() and generation.isdigit(), 'identity-unknown')
    plan = store.plan(int(generation)); node = attempt.parents[1].name
    require(node == spec['node'] and spec['plan_sha256'] == plan['plan_sha256'], 'identity-unknown')
    paths = store.node_paths(plan['generation'], node)
    require(str(paths['disk']) == spec['disk'] and attempt.parent == paths['disk'].parent/'runtime'
            and len(attempt.name) == 8 and attempt.name.isascii() and attempt.name.isdigit(), 'identity-unknown')
    expected = declaration(store, plan, node)
    if expected is not None:
        require(store.snapshot()['active_generation'] == plan['generation'], 'state-conflict')
    require(spec.get('vmgenid') == expected, 'identity-unknown')
    expected_args = [] if expected is None else ['vmgenid,guid='+expected['guid']]
    actual = [v for v in spec['argv'] if type(v) is str and (v == 'vmgenid' or v.startswith('vmgenid,'))]
    require(actual == expected_args and (expected is None or any(
        spec['argv'][i] == '-device' and spec['argv'][i+1] == expected_args[0]
        for i in range(len(spec['argv'])-1))), 'identity-unknown')
