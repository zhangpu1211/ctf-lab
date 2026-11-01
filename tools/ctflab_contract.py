"""ctflab-local v1：严格消息契约与公开错误，不依赖平台运行器。"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid

PROTOCOL = 'ctflab-local'
VERSION = 1
MAX_MESSAGE_BYTES = 64 * 1024
STATES = frozenset({'preparing', 'prepared', 'starting', 'process-running', 'guest-ready',
                    'service-ready', 'course-verified', 'stopping', 'stopped', 'resetting',
                    'recovering', 'failed', 'unknown', 'recovery-required'})
MESSAGES = {
    'invalid-request': '请求结构或参数不符合契约。',
    'version-mismatch': '协议版本不兼容。',
    'permission-denied': '当前调用主体无权访问该实例。',
    'state-conflict': '实例、代次或状态版本已变化，请重新读取状态。',
    'idempotency-conflict': '同一幂等键不能用于不同请求。',
    'resource-busy': '操作仍在执行，请读取状态后重试。',
    'identity-unknown': '资源身份无法核验，已保留现场。',
    'capability-unverified': '所需能力尚未验证。',
    'unsupported-platform': '当前平台不支持此操作。',
    'storage-insufficient': '存储空间不足，已保留已有状态。',
    'persistence-failed': '操作记录未能可靠提交，需要恢复核验。',
    'control-unreachable': '控制通道不可达，需要恢复核验。',
    'stop-timeout': '正常停止超时，尚未释放资源。',
    'reset-commit-failed': '重置提交失败，需要恢复核验。',
    'route-conflict': '实验网络与现有路由冲突。',
    'cursor-expired': '事件游标已失效，请重新读取状态。',
    'event-gap': '事件序号不连续，请重新读取状态。',
    'operation-finished': '目标操作已结束，取消请求未执行。',
    'backend-failed': '后端操作失败，需要恢复核验。',
}


class ContractError(ValueError):
    def __init__(self, code='invalid-request'):
        self.code = code if code in MESSAGES else 'invalid-request'
        super().__init__(MESSAGES[self.code])


def require(condition, code='invalid-request'):
    if not condition:
        raise ContractError(code)


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}', value) is not None)
    return value


def uuid_text(value):
    require(isinstance(value, str))
    try:
        require(str(uuid.UUID(value)) == value)
    except (ValueError, AttributeError):
        raise ContractError() from None
    return value


def integer(value, minimum=0):
    require(type(value) is int and minimum <= value <= 2**53 - 1)
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False)


def parse_request(text):
    require(isinstance(text, str))
    try:
        require(len(text.encode('utf-8')) <= MAX_MESSAGE_BYTES)
    except UnicodeError:
        raise ContractError() from None
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        return result
    try:
        data = json.loads(text, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ContractError()))
    except (ValueError, RecursionError):
        raise ContractError() from None
    return validate_request(data)


def validate_request(data):
    require(type(data) is dict)
    require(data.get('protocol') == PROTOCOL and type(data.get('version')) is int
            and data['version'] == VERSION, 'version-mismatch')
    common = {'protocol', 'version', 'request_id', 'operation', 'instance_uuid'}
    op = data.get('operation')
    require(isinstance(op, str) and op in {'status', 'prepare', 'start', 'stop', 'reset', 'recover', 'cancel','guest'})
    fields = common if op == 'status' else common | {
        'expected_generation', 'expected_state_revision', 'idempotency_key', 'parameters'}
    require(set(data) == fields)
    uuid_text(data['request_id']); uuid_text(data['instance_uuid'])
    if op == 'status':
        return copy.deepcopy(data)
    identifier(data['idempotency_key'])
    if op == 'prepare':
        require(data['expected_generation'] is None and data['expected_state_revision'] is None)
    else:
        integer(data['expected_generation'], 1); integer(data['expected_state_revision'])
    params = data['parameters']
    require(type(params) is dict)
    expected = {'prepare': {'course_id', 'baseline_id'}, 'start': {'display', 'allow_emulation'},
                'stop': set(), 'reset': {'baseline_id'}, 'recover': set(),
                'cancel': {'operation_id'},'guest':{'node','action'}}[op]
    if op=='guest' and params.get('action') in ('preparation-inspect','preparation-resume'):
        expected=expected|{'target_operation_id'}
        if params['action']=='preparation-resume':expected=expected|{'expected_sha256'}
    require(set(params) == expected)
    if op in {'prepare', 'reset'}:
        identifier(params['baseline_id'])
    if op == 'prepare':
        identifier(params['course_id'])
    if op == 'start':
        require(params['display'] in ('headless', 'console') and type(params['allow_emulation']) is bool)
    if op == 'cancel':
        uuid_text(params['operation_id'])
    if op=='guest':
        identifier(params['node'])
        if params['action'] in ('preparation-inspect','preparation-resume'):
            uuid_text(params['target_operation_id'])
            if params['action']=='preparation-resume':
                require(type(params['expected_sha256']) is str and re.fullmatch('[0-9a-f]{64}',params['expected_sha256']))
        require(params['action'] in ('preparation-inspect','preparation-resume','status','recover','network-apply','services-start','services-stop',
                                     'containers-prepare','containers-start','containers-stop','analysis-run'))
    return copy.deepcopy(data)


def fingerprint(request):
    # request_id 只关联当前传输；重试必须保留其余请求内容，包括初始前置条件。
    return hashlib.sha256(canonical({k: v for k, v in request.items() if k != 'request_id'}).encode()).hexdigest()


def public_error(code, *, stage='dispatch', evidence_refs=()):
    require(code in MESSAGES)
    require(stage in {'dispatch', 'observe', 'execute', 'commit', 'events'})
    refs = [identifier(item) for item in evidence_refs]
    require(len(refs) <= 32)
    return {'code': code, 'stage': stage, 'message': MESSAGES[code],
            'retryable': code == 'resource-busy', 'preserved': True,
            'recovery_actions': ['status'] if code != 'cursor-expired' else ['status', 'events'],
            'evidence_refs': refs}


def capabilities():
    return {'protocol': PROTOCOL, 'version': VERSION, 'kind': 'contract-capabilities',
            'operations': ['status', 'prepare', 'start', 'stop', 'reset', 'recover', 'cancel','guest'],
            'runtime_verified': False, 'transport_authenticated': False}


def merge_events(cursor, events, *, instance_uuid=None):
    """客户端去重/缺口校验；游标按实例，不能混用实例或代次的流。"""
    integer(cursor)
    require(isinstance(events, list) and len(events) <= 1000)
    fresh = []; seen = {}; event_ids = {}
    for event in events:
        require(type(event) is dict and set(event) == {'protocol', 'version', 'event_id', 'sequence',
                'timestamp', 'instance_uuid', 'generation', 'operation_id', 'state_revision', 'stage', 'state'}, 'event-gap')
        require(event['protocol'] == PROTOCOL and type(event['version']) is int and event['version'] == VERSION, 'event-gap')
        seq = integer(event['sequence'], 1); uuid_text(event['event_id']); uuid_text(event['operation_id'])
        uuid_text(event['instance_uuid']); integer(event['generation'], 1); integer(event['state_revision'])
        if instance_uuid is None: instance_uuid = event['instance_uuid']
        require(event['instance_uuid'] == instance_uuid, 'event-gap')
        require(isinstance(event['state'], str) and event['state'] in STATES, 'event-gap')
        require(event['stage'] in ('intent', 'executing', 'cancel-requested', 'failed', 'cancelled', 'completed'), 'event-gap')
        require(isinstance(event['timestamp'], str) and len(event['timestamp']) <= 64, 'event-gap')
        require(event['event_id'] not in event_ids or event_ids[event['event_id']] == seq, 'event-gap')
        event_ids[event['event_id']] = seq
        if seq <= cursor:
            continue
        if seq in seen:
            require(seen[seq] == event, 'event-gap')
            continue
        require(seq == cursor + len(fresh) + 1, 'event-gap')
        seen[seq] = event; fresh.append(copy.deepcopy(event))
    return cursor + len(fresh), fresh
