"""指定运行时目录的只读内容清单；不执行文件、不扫描个人目录、不认定依赖闭包。"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import sys

MAX_FILES = 20000
MAX_BYTES = 8 * 1024**3


class InventoryError(ValueError):
    pass


def check_path(path):
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise InventoryError('链接或重解析点不允许')
    return path.lstat()


def signature(info):
    timestamp = getattr(info, 'st_birthtime_ns', info.st_ctime_ns) if os.name == 'nt' else info.st_ctime_ns
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, timestamp)


def hash_file(path, expected):
    check_path(path)
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or signature(opened) != signature(expected):
            raise InventoryError('文件身份变化或文件不是独立普通文件')
        value = hashlib.sha256()
        count = 0
        while block := stream.read(1024 * 1024):
            count += len(block)
            if count > expected.st_size:
                raise InventoryError('采集期间文件增长')
            value.update(block)
        if signature(os.fstat(stream.fileno())) != signature(opened):
            raise InventoryError('采集期间文件变化')
    if signature(check_path(path)) != signature(expected):
        raise InventoryError('采集期间文件被替换')
    return value.hexdigest()


def listing(root):
    if not stat.S_ISDIR(check_path(root).st_mode):
        raise InventoryError('运行时根不是目录')
    records = {}
    directories = [root]
    total = 0
    visited = 0
    while directories:
        directory = directories.pop()
        check_path(directory)
        for path in sorted(directory.iterdir()):
            info = check_path(path)
            visited += 1
            if visited > MAX_FILES:
                raise InventoryError('采集范围超限')
            if stat.S_ISDIR(info.st_mode):
                directories.append(path)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                name = path.relative_to(root).as_posix()
                records[name] = info
                total += info.st_size
            else:
                raise InventoryError('非普通文件或硬链接不允许')
            if len(records) + len(directories) > MAX_FILES or total > MAX_BYTES:
                raise InventoryError('采集范围超限')
    return records


def inventory(root, *, executable='qemu-system-x86_64.exe'):
    root = Path(os.path.abspath(root))
    before = listing(root)
    if executable not in ('qemu-system-x86_64.exe','qemu-system-x86_64','qemu-system-aarch64','bin/qemu-system-aarch64') or executable not in before:
        raise InventoryError('请指定含所选 QEMU 可执行文件的安装目录')
    entries = [{'name': name, 'size': info.st_size, 'sha256': hash_file(root/name, info)}
               for name, info in sorted(before.items())]
    after = listing(root)
    if set(before) != set(after) or any(signature(info) != signature(after[name]) for name, info in before.items()):
        raise InventoryError('采集期间目录或文件变化，请保留现场并重试')
    encoded = json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()
    return {'schema': 1, 'scope': 'runtime-directory-inventory-only',
            'files': entries, 'inventory_sha256': hashlib.sha256(encoded).hexdigest(),
            'host': {'system': platform.system(), 'release': platform.release(),
                     'machine': platform.machine(), 'python_version': platform.python_version()},
            'components_complete': False, 'dependency_closure_verified': False,
            'source_verified': False, 'g0_passed': False}


def validate_reference(value):
    if type(value) is not dict or value.get('schema') != 1 or value.get('scope') != 'runtime-directory-inventory-only':
        raise InventoryError('参考清单类型不正确')
    entries = value.get('files')
    if type(entries) is not list or not 1 <= len(entries) <= MAX_FILES:
        raise InventoryError('参考清单文件数量无效')
    names = []
    for item in entries:
        if type(item) is not dict or set(item) != {'name', 'size', 'sha256'}:
            raise InventoryError('参考清单字段无效')
        name = item['name']
        if not isinstance(name, str) or not name or any(x in name for x in ('\\', ':', '\x00')) or any(x in ('', '.', '..') for x in name.split('/')):
            raise InventoryError('参考清单路径无效')
        if type(item['size']) is not int or not 0 <= item['size'] <= MAX_BYTES:
            raise InventoryError('参考清单大小无效')
        digest = item['sha256']
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise InventoryError('参考清单哈希无效')
        names.append(name)
    if names != sorted(set(names)):
        raise InventoryError('参考清单顺序或重复项无效')
    encoded = json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()
    if hashlib.sha256(encoded).hexdigest() != value.get('inventory_sha256'):
        raise InventoryError('参考清单摘要不符')
    return entries


def compare(reference, current):
    old = {x['name']: x for x in validate_reference(reference)}
    new = {x['name']: x for x in validate_reference(current)}
    result = {'added': sorted(new.keys()-old.keys()), 'removed': sorted(old.keys()-new.keys()),
              'changed': sorted(k for k in old.keys() & new.keys() if old[k] != new[k])}
    result['matches'] = not any(result.values())
    result['g0_passed'] = False
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compare', type=Path)
    parser.add_argument('--executable',choices=('qemu-system-x86_64.exe','qemu-system-x86_64','qemu-system-aarch64','bin/qemu-system-aarch64'),default='qemu-system-x86_64.exe')
    args = parser.parse_args(argv)
    try:
        root = Path(os.path.abspath(args.root))
        output = Path(os.path.abspath(args.output))
        check_path(output.parent)
        if output == root or root in output.parents:
            raise InventoryError('输出必须位于被采集目录外')
        if output.exists() or output.is_symlink():
            raise InventoryError('输出已存在，不覆盖')
        reference = None
        if args.compare:
            if args.compare.stat().st_size > 8 * 1024**2:
                raise InventoryError('参考清单过大')
            reference = json.loads(args.compare.read_text(encoding='utf-8'))
            validate_reference(reference)
        result = inventory(root,executable=args.executable)
        if reference is not None:
            result['comparison'] = compare(reference, result)
        with output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print(json.dumps({'files': len(result['files']), 'inventory_sha256': result['inventory_sha256'],
                          'matches': result.get('comparison', {}).get('matches'), 'g0_passed': False}))
        return 0 if result.get('comparison', {}).get('matches', True) else 2
    except (OSError, ValueError) as exc:
        # 不回显系统异常内可能含有的私人绝对路径。
        print(str(exc) if isinstance(exc, InventoryError) else '读取或写入失败；检查本地权限与JSON格式', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
