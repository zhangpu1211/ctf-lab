"""只复核A01源级快照及符号/调用位置；不导入被查模块、不探测或执行宿主操作。"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import sys

SNAPSHOT = 'docs/ctflab-platform-ownership-2026-10-30-r2.json'
SNAPSHOT_SHA256 = 'd5c1d2d1ec233664fe82d5347b041bd010f415fc3e02f34f9195844384d18b34'


def unique(pairs):
    value = {}
    for name, item in pairs:
        if name in value:raise ValueError('快照字段重复')
        value[name] = item
    return value


def check(root):
    root = Path(root).absolute(); path = root/SNAPSHOT
    if path.is_symlink() or path.stat().st_size > 4*1024*1024:raise ValueError('快照路径或长度不符')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SNAPSHOT_SHA256:raise ValueError('快照摘要变化，须重新审查')
    value = json.loads(raw, object_pairs_hook=unique)
    if (value['schema'] != 1 or value['source_only'] is not True or value['runtime_dispatch_verified'] is not False
            or value['logical_interfaces_are_not_runtime_base_classes'] is not True):
        raise ValueError('不能将源级责任快照提升为原生兼容证明')
    if list(sys.version_info[:2]) != value['python_ast_version']:
        raise ValueError('本快照的AST规范化需Python3.10；不要把解释器差异当源码回归')
    expected_shells = {'desktop/src-tauri/src/main.rs', 'desktop/src-tauri/src/transport.rs',
                       'gui/GuiCore.swift', 'gui/GuiApp.swift'}
    if set(value['non_python_boundary_sources']) != expected_shells:raise ValueError('薄壳来源范围不符')
    for name, expected in value['non_python_boundary_sources'].items():
        source = root/name
        if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError('薄壳源码变化，边界需复核：'+name)
    modules = value['modules']
    if not 1 <= len(modules) <= 256:raise ValueError('来源范围无效')
    trees = {}; definitions = {}; calls = {}
    for name, entry in modules.items():
        if not re.fullmatch(r'ctflab(?:_[a-z0-9_]+)?', name) or entry['path'] != 'tools/'+name+'.py':
            raise ValueError('只读取登记的项目源码')
        source = root/entry['path']
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 8*1024*1024:
            raise ValueError('来源类型或长度不符')
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:raise ValueError('源码变化，盘点需更新：'+name)
        tree = ast.parse(data, filename=entry['path']); trees[name] = tree
        qualified = {}
        class Definitions(ast.NodeVisitor):
            def __init__(self):self.parts = []
            def record(self, node):
                self.parts.append(node.name); qualified['.'.join(self.parts)] = node
                self.generic_visit(node); self.parts.pop()
            visit_ClassDef = record
            visit_FunctionDef = record
        Definitions().visit(tree); definitions[name] = qualified
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                expression = ast.unparse(node.func); digest = hashlib.sha256(expression.encode()).hexdigest()
                identifier = f'{name}:{node.lineno}:{node.col_offset}:{node.end_lineno}:{node.end_col_offset}:{digest[:12]}'
                if identifier in calls:raise ValueError('重复调用位置')
                calls[identifier] = (expression, digest)
    count = 0
    for entry in value['candidate_calls']:
        if entry['owner_interface'] not in value['interfaces']:raise ValueError('责任接口未登记')
        expression, digest = calls[entry['id']]
        if entry['call_sha256'] != digest or entry['call'] != expression[:240]:raise ValueError('调用位置不符')
        if entry['call_truncated'] != (len(expression) > 240):raise ValueError('截断标记不符')
        count += 1
    if count != value['candidate_call_count']:raise ValueError('候选调用数量不符')
    for entry in value['current_binding_symbols']:
        module, qualified = entry['symbol'].split('.', 1); node = definitions[module][qualified]
        if node.lineno != entry['line']:raise ValueError('接口符号位置变化')
        if isinstance(node, ast.FunctionDef) and ast.unparse(node.args) != entry['source_arguments']:
            raise ValueError('接口参数变化')
    return {'source_snapshot_verified': True, 'modules': len(trees), 'candidate_calls': count,
            'binding_symbols': len(value['current_binding_symbols']), 'interfaces': len(value['interfaces']),
            'thin_shell_source_hashes_checked': len(expected_shells),
            'runtime_dispatch_verified': False, 'native_compatibility_verified': False,
            'note': '仅核对已审源级快照；不证明筛选器穷尽所有动态行为，不运行盘点中的调用'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    try:
        print(json.dumps(check(args.root), ensure_ascii=False)); return 0
    except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as error:
        print('源级快照未能复核：'+str(error)); return 2


if __name__ == '__main__':raise SystemExit(main())
