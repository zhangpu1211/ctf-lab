"""离线拓扑、有限模板差异和网络验收计划；不设置路由、不探测任何地址。"""
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re

from ctflab_scenario_v2 import instance_plan, parse_manifest, require, validate_manifest, MAX_BYTES


def timestamp(value):
    require(isinstance(value, str), '时间必须带时区')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(result.tzinfo is not None, '时间缺少时区')
    return result


def projection(manifest, instance_uuid, *, generation=1, observations=None, now=None, max_age=60):
    plan = instance_plan(manifest, instance_uuid, generation=generation)
    now = now or datetime.now(timezone.utc)
    require(now.tzinfo is not None and type(max_age) is int and 1 <= max_age <= 3600, '观测时效无效')
    observations = [] if observations is None else observations
    require(type(observations) is list and len(observations) <= 32, '观测数量无效')
    indexed = {}
    for observation in observations:
        require(type(observation) is dict and set(observation) == {
            'instance_uuid', 'generation', 'plan_sha256', 'node', 'timestamp', 'state', 'addresses', 'evidence_ref'}, '观测字段无效')
        node = observation['node']
        require(isinstance(node, str) and node in plan['manifest']['nodes'] and node not in indexed, '观测节点无效或重复')
        require(observation['instance_uuid'] == instance_uuid and type(observation['generation']) is int
                and observation['generation'] == generation and observation['plan_sha256'] == plan['plan_sha256'], '观测不属于当前计划')
        require(observation['state'] in ('unknown', 'stopped', 'process-running', 'guest-ready', 'service-ready'), '观测状态无效')
        from ctflab_scenario_v2 import identifier
        identifier(observation['evidence_ref'])
        addresses = observation['addresses']
        require(type(addresses) is dict and set(addresses) <= {i['id'] for i in plan['manifest']['nodes'][node]['interfaces']}, '观测网卡无效')
        import ipaddress
        for value in addresses.values():
            require(isinstance(value, str), '观测地址类型无效')
            ipaddress.ip_address(value)
        age = (now - timestamp(observation['timestamp'])).total_seconds()
        require(age >= 0, '观测来自未来')
        indexed[node] = dict(observation, stale=age > max_age)
    nodes = []
    for node in plan['start_order']:
        definition = plan['manifest']['nodes'][node]
        observation = indexed.get(node)
        nodes.append({'id': node, 'depends_on': definition['depends_on'],
                      'cpus': definition['cpus'], 'memory_mb': definition['memory_mb'],
                      'interfaces': [{'id': i['id'], 'network': i['network'], 'planned_address': i['address'],
                                      'observed_address': observation['addresses'].get(i['id']) if observation and not observation['stale'] else None}
                                     for i in definition['interfaces']],
                      'state': observation['state'] if observation and not observation['stale'] else 'unknown',
                      'observation': observation})
    return {'schema': 1, 'instance_uuid': instance_uuid, 'generation': generation,
            'plan_sha256': plan['plan_sha256'], 'networks': plan['manifest']['networks'], 'nodes': nodes,
            'isolation_verified': False, 'runtime_verified': False,
            'scope': 'design-with-optional-evidence-overlay'}


def network_checks(manifest, instance_uuid, generation=1):
    plan = instance_plan(manifest, instance_uuid, generation=generation)
    nodes = plan['manifest']['nodes']
    checks = []
    for source in sorted(nodes):
        source_networks = {i['network'] for i in nodes[source]['interfaces']}
        for destination in sorted(nodes):
            if source == destination:
                continue
            common = source_networks & {i['network'] for i in nodes[destination]['interfaces']}
            checks.append({'source': source, 'destination': destination, 'family': 'ipv4',
                           'expected': 'allow' if common else 'deny', 'networks': sorted(common),
                           'scope': 'node-connectivity-not-service-readiness', 'result': 'not-run'})
        for boundary in ('host', 'control-plane', 'physical-lan', 'internet'):
            for family in ('ipv4', 'ipv6'):
                checks.append({'source': source, 'destination': boundary, 'family': family,
                               'expected': 'deny', 'result': 'not-run', 'target': 'requires-explicit-test-target'})
    return {'instance_uuid': instance_uuid, 'generation': generation, 'plan_sha256': plan['plan_sha256'],
            'checks': checks, 'isolation_verified': False, 'executed': False,
            'note': '双网卡不代表转发；服务协议和受控测试目标须另行指定。'}


def draft_diff(original, proposed, instance_uuid, generation=1):
    original = validate_manifest(original)
    proposed = validate_manifest(proposed)
    require(original['scenario_id'] == proposed['scenario_id'], '草稿必须属于同一场景')
    before = instance_plan(original, instance_uuid, generation=generation)
    after = instance_plan(proposed, instance_uuid, generation=generation+1)
    changes = []
    def compare(left, right, path):
        if left == right:
            return
        if type(left) is dict and type(right) is dict:
            for key in sorted(set(left) | set(right)):
                compare(left.get(key), right.get(key), path + '/' + key)
        else:
            changes.append({'path': path, 'before': left, 'after': right})
    compare(original, proposed, '')
    return {'base_plan_sha256': before['plan_sha256'], 'next_plan_sha256': after['plan_sha256'],
            'next_generation': generation+1, 'changes': changes, 'manifest': proposed,
            'applied': False, 'requires_new_generation': True}


def canonical_digest(value):
    """语义摘要：对规范化JSON计算；排版差异不影响绑定，任何内容变化即失效。"""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


ACCEPTANCE_FIELDS = {'schema', 'kind', 'scenario_id', 'manifest_sha256', 'next_plan_sha256',
                     'next_generation', 'result', 'evidence_ref', 'recorded_at'}
QUALIFICATION_FIELDS = {'schema', 'kind', 'instance_uuid', 'base_generation', 'next_generation',
                        'base_plan_sha256', 'next_plan_sha256', 'manifest_sha256', 'acceptance',
                        'applied', 'requires_new_generation', 'runtime_verified', 'isolation_verified',
                        'automatic_replay'}


def check_acceptance(acceptance, *, scenario_id, manifest_sha256, next_plan_sha256, next_generation):
    """具体场景验收门：记录必须精确绑定本草稿摘要/计划摘要/代次，未通过即拒绝。"""
    require(type(acceptance) is dict and set(acceptance) == ACCEPTANCE_FIELDS, '验收记录字段无效')
    require(acceptance['schema'] == 1 and acceptance['kind'] == 'scenario-acceptance', '验收记录类型无效')
    require(acceptance['scenario_id'] == scenario_id, '验收记录属于其他场景')
    require(acceptance['manifest_sha256'] == manifest_sha256, '验收记录摘要与本草稿不符；草稿变化后须重新验收')
    require(acceptance['next_plan_sha256'] == next_plan_sha256, '验收记录计划摘要与本草稿不符')
    require(type(acceptance['next_generation']) is int and acceptance['next_generation'] == next_generation,
            '验收记录代次与本草稿不符')
    require(acceptance['result'] == 'passed', '具体场景验收未通过；草稿不能发布为可执行模板')
    require(isinstance(acceptance['evidence_ref'], str)
            and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}', acceptance['evidence_ref']) is not None,
            '验收证据标识无效')
    timestamp(acceptance['recorded_at'])
    return True


def publish_qualification(original, proposed, instance_uuid, *, generation=1, acceptance=None):
    """可执行模板资格门（只读计算）：S03解析/计划必须通过，且具体场景验收精确绑定本草稿。

    草稿导出与执行资格分离：本函数不写文件、不建代次、不热改运行场景；
    错误图（S03校验失败）无论验收记录如何都直接拒绝。
    """
    result = draft_diff(original, proposed, instance_uuid, generation=generation)
    manifest_sha256 = canonical_digest(proposed)
    check_acceptance(acceptance, scenario_id=proposed['scenario_id'], manifest_sha256=manifest_sha256,
                     next_plan_sha256=result['next_plan_sha256'], next_generation=result['next_generation'])
    return {'schema': 1, 'kind': 'executable-template-qualification', 'instance_uuid': instance_uuid,
            'base_generation': generation, 'next_generation': result['next_generation'],
            'base_plan_sha256': result['base_plan_sha256'], 'next_plan_sha256': result['next_plan_sha256'],
            'manifest_sha256': manifest_sha256, 'acceptance': dict(acceptance),
            'applied': False, 'requires_new_generation': True, 'runtime_verified': False,
            'isolation_verified': False, 'automatic_replay': False}


def verify_qualification(record, original, proposed, instance_uuid, *, generation=1):
    """按当前输入重算全部绑定；清单/计划/代次任一变化或记录被改即失效。"""
    require(type(record) is dict and set(record) == QUALIFICATION_FIELDS, '资格记录字段无效')
    require(record['schema'] == 1 and record['kind'] == 'executable-template-qualification'
            and record['applied'] is False and record['requires_new_generation'] is True
            and record['runtime_verified'] is False and record['isolation_verified'] is False
            and record['automatic_replay'] is False, '资格记录状态无效')
    require(record['instance_uuid'] == instance_uuid, '资格记录属于其他实例')
    result = draft_diff(original, proposed, instance_uuid, generation=generation)
    require(type(record['base_generation']) is int and record['base_generation'] == generation
            and record['next_generation'] == result['next_generation'], '资格记录代次不符')
    require(record['base_plan_sha256'] == result['base_plan_sha256']
            and record['next_plan_sha256'] == result['next_plan_sha256'], '资格记录计划摘要不符')
    require(record['manifest_sha256'] == canonical_digest(proposed), '草稿摘要变化；原资格已失效，须重新验收')
    check_acceptance(record['acceptance'], scenario_id=proposed['scenario_id'],
                     manifest_sha256=record['manifest_sha256'],
                     next_plan_sha256=record['next_plan_sha256'], next_generation=record['next_generation'])
    return True


def render(view):
    esc = lambda v: html.escape(str(v), quote=True)
    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">',
             '<title>CTFLab 场景拓扑</title><style>body{font:16px system-ui;max-width:1000px;margin:36px auto;padding:0 20px;background:#f4f6f8;color:#182b3b}details{background:white;padding:18px;margin:12px 0;border-radius:10px}summary{cursor:pointer;font-weight:650}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:10px;border-bottom:1px solid #ddd}.note{color:#5b6270}</style>',
             '<h1>场景拓扑</h1><p class="note">这是离线设计视图。展开节点查看网卡；设计地址不代表已获得地址，连线不代表已验证可达。</p>',
             f'<p>实例 {esc(view["instance_uuid"])} · 代次 {view["generation"]}</p><h2>实验网络</h2>']
    for name, network in view['networks'].items():
        parts.append(f'<p>{esc(name)} · {esc(network["cidr"])} · 无默认出口（设计）</p>')
    height = max(len(view['nodes']), len(view['networks'])) * 90 + 40
    positions = {name: 55 + index * 90 for index, name in enumerate(view['networks'])}
    parts.append(f'<svg role="img" aria-label="节点与实验网段的设计连接，不代表实测可达" viewBox="0 0 920 {height}" style="width:100%;background:white;border-radius:10px"><title>节点与实验网段的设计连接</title>')
    for index, node in enumerate(view['nodes']):
        y = 55 + index * 90
        for nic in node['interfaces']:
            parts.append(f'<path d="M 260 {y} L 640 {positions[nic["network"]]}" fill="none" stroke="#849bab" stroke-width="2"/>')
    for index, node in enumerate(view['nodes']):
        y = 55 + index * 90
        parts.append(f'<rect x="20" y="{y-24}" width="240" height="48" rx="8" fill="#e5eef5"/><text x="140" y="{y+6}" text-anchor="middle" fill="#182b3b">{esc(node["id"])}</text>')
    for name, y in positions.items():
        parts.append(f'<rect x="640" y="{y-24}" width="260" height="48" rx="8" fill="#e8f2ed"/><text x="770" y="{y+6}" text-anchor="middle" fill="#182b3b">{esc(name)} · {esc(view["networks"][name]["cidr"])}</text>')
    parts.append('</svg>')
    parts.append('<h2>节点与连接</h2>')
    for node in view['nodes']:
        obs = node['observation']
        labels = {'unknown': '未取得当前状态', 'stopped': '已停止', 'process-running': '进程运行中',
                  'guest-ready': '来宾已就绪', 'service-ready': '服务已就绪'}
        status = '观测过期' if obs and obs['stale'] else labels.get(node['state'], node['state'])
        parts.append(f'<details open><summary>{esc(node["id"])} · {esc(status)}</summary><p>{node["cpus"]} vCPU / {node["memory_mb"]} MiB · 启动依赖：{esc(", ".join(node["depends_on"]) or "无")}</p>')
        parts.append('<table><tr><th>网卡</th><th>连接网段</th><th>设计地址</th><th>最近观测地址</th></tr>')
        for nic in node['interfaces']:
            parts.append('<tr>' + ''.join(f'<td>{esc(v)}</td>' for v in (nic['id'], nic['network'], nic['planned_address'], nic['observed_address'] or '未取得')) + '</tr>')
        parts.append('</table></details>')
    parts.append('<p class="note">未执行网络探测或修改任何运行实例。</p></html>')
    return '\n'.join(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--instance', required=True)
    parser.add_argument('--generation', type=int, default=1)
    parser.add_argument('--format', choices=('json', 'html', 'network-checks', 'diff',
                                             'publish-qualification', 'verify-qualification'), default='json')
    parser.add_argument('--proposed', type=Path)
    parser.add_argument('--acceptance', type=Path)
    parser.add_argument('--qualification', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    def load(path):
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES+1)
        return parse_manifest(raw.decode('utf-8'))
    def load_json(path, what):
        require(path is not None, f'需要{what}')
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES+1)
        require(len(raw) <= MAX_BYTES, f'{what}超出大小限制')
        value = json.loads(raw.decode('utf-8'))
        require(type(value) is dict, f'{what}必须是JSON对象')
        return value
    try:
        manifest = load(args.manifest)
        if args.format == 'diff':
            require(args.proposed is not None, '需要新草稿')
            result = draft_diff(manifest, load(args.proposed), args.instance, args.generation)
        elif args.format == 'publish-qualification':
            require(args.proposed is not None, '需要新草稿')
            result = publish_qualification(manifest, load(args.proposed), args.instance, generation=args.generation,
                                           acceptance=load_json(args.acceptance, '具体场景验收记录'))
        elif args.format == 'verify-qualification':
            record = load_json(args.qualification, '资格记录')
            require(args.proposed is not None, '需要草稿')
            verify_qualification(record, manifest, load(args.proposed), args.instance, generation=args.generation)
            result = {'schema': 1, 'kind': 'qualification-verified', 'instance_uuid': args.instance,
                      'manifest_sha256': record['manifest_sha256'], 'next_generation': record['next_generation'],
                      'applied': False, 'runtime_verified': False, 'automatic_replay': False}
        elif args.format == 'network-checks':
            result = network_checks(manifest, args.instance, args.generation)
        else:
            result = projection(manifest, args.instance, generation=args.generation)
        output = render(result) if args.format == 'html' else json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            with args.output.open('x', encoding='utf-8') as stream:
                stream.write(output + '\n')
        else:
            print(output)
        return 0
    except (OSError, ValueError, TypeError):
        print('读取、校验或输出失败；已有文件未覆盖。')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
