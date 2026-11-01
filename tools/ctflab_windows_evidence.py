"""只读汇总已有Windows控制验收材料；不操作进程、不复制磁盘、不上传。"""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import uuid

MAX_BYTES = 4 * 1024 * 1024
FILES = ('config.json', 'host.json', 'result.json', 'exit.json', 'failure.json',
         'qemu-stderr.log', 'worker-console.log')
REQUIRED = {'config.json', 'host.json', 'result.json', 'qemu-stderr.log'}
CONTROL_R1_SHA = 'bd001ff0cc7c18a63370bfbdd64c499be26118c76bd3042f3d6f7bf23ae85242'


def read(path):
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('拒绝链接或重解析路径')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
        raise ValueError('不是限额内的普通文件')
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES+1)
    if len(raw) > MAX_BYTES or len(raw) != info.st_size:
        raise ValueError('文件读取期间变化或超限')
    return raw


def object_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('重复JSON字段')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('非法常量')))
    if type(value) is not dict:
        raise ValueError('JSON必须为对象')
    return value


def summary(root, kit=None, terminal_reopened=None):
    root = Path(root).absolute()
    records, missing, invalid, selected = {}, [], [], {}
    for name in FILES:
        try:
            raw = read(root / name)
            records[name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
            if name.endswith('.json'):
                selected[name] = object_json(raw)
        except FileNotFoundError:
            missing.append(name)
        except (OSError, ValueError, UnicodeError, RecursionError):
            invalid.append(name)
    config = selected.get('config.json', {})
    binding = None
    try:
        identity = config['instance_uuid']
        if str(uuid.UUID(identity)) != identity or type(config['generation']) is not int or config['generation'] < 1:
            raise ValueError()
        binding = {'instance_uuid': identity, 'generation': config['generation']}
    except (KeyError, ValueError, TypeError, AttributeError):
        if 'config.json' not in missing and 'config.json' not in invalid:
            invalid.append('config.json')
    raw_result = selected.get('result.json', {})
    result = {}
    bool_fields = ('source_unchanged', 'shutdown_guest_event', 'stderr_complete', 'g0_passed', 'graceful_stop_verified')
    for key in bool_fields:
        if type(raw_result.get(key)) is bool or key in raw_result and raw_result[key] is None:
            result[key] = raw_result[key]
    if raw_result.get('state') in ('exited', 'unknown', 'failed'):
        result['state'] = raw_result['state']
    for key in ('returncode', 'events_dropped'):
        if type(raw_result.get(key)) is int:
            result[key] = raw_result[key]
    # 私人路径、自由文本错误和日志内容均不进入分享报告。
    result['control_failure_present'] = raw_result.get('control_failure') is not None
    if 'result.json' in selected and not (raw_result.get('state') == 'exited'
            and type(raw_result.get('returncode')) is int and all(k in result for k in bool_fields)):
        invalid.append('result.json')
    host = selected.get('host.json', {})
    import re
    host_summary = {}
    patterns = {'system': r'Windows', 'machine': r'(?:AMD64|x86_64|ARM64|arm64)',
                'version': r'[0-9.]{1,40}', 'python': r'[0-9.]{1,20}'}
    for key, pattern in patterns.items():
        if isinstance(host.get(key), str) and re.fullmatch(pattern, host[key]):
            host_summary[key] = host[key]
    if 'host.json' in selected and set(host_summary) != set(patterns):
        invalid.append('host.json')
    package = {'provided': kit is not None, 'matches_control_r1': False}
    if kit is not None:
        raw = read(Path(kit).absolute())
        package.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        package['matches_control_r1'] = package['sha256'] == CONTROL_R1_SHA
    if terminal_reopened not in (None, True, False):
        raise ValueError('人工确认无效')
    return {'schema': 1, 'scope': 'local-artifact-summary-not-independent-host-attestation',
            'files': records, 'missing': missing, 'invalid': sorted(set(invalid)),
            'required_artifacts_complete': not (REQUIRED & set(missing)) and not invalid,
            'instance': binding, 'host': host_summary, 'reported_result': result,
            'kit': package, 'terminal_reopened_user_statement': terminal_reopened,
            'g0_passed': False, 'g1_passed': False,
            'logs_included': False, 'uploaded': False,
            'note': '日志仅摘要，不证明无警告；同目录材料不能独立证明设备真实性。'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--kit', type=Path)
    parser.add_argument('--terminal-reopened', choices=('yes', 'no'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        statement = None if args.terminal_reopened is None else args.terminal_reopened == 'yes'
        result = summary(args.run, args.kit, statement)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            # 不允许输出到原验收根，避免把汇总误当原始证据。
            root = args.run.resolve()
            output = args.output.absolute()
            if output.resolve() == root or root in output.resolve().parents:
                raise ValueError('输出需位于原验收目录之外')
            with output.open('x', encoding='utf-8') as stream:
                stream.write(text + '\n')
        else:
            print(text)
        return 0 if result['required_artifacts_complete'] else 2
    except (OSError, ValueError, TypeError):
        print('汇总失败，原材料未修改；请核对路径和文件大小。')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
