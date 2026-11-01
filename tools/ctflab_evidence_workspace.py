"""C05学生独立调查工作区：新建只读快照与可写副本，不改原解压目录。"""
import argparse
import inspect
import json
import os
from pathlib import Path, PurePosixPath
import stat

from ctflab_evidence_course import MAX_FILE, MAX_TOTAL, sha, verify


def checked_path(value):
    path = Path(value).absolute()
    if '..' in path.parts:raise ValueError('路径不能含上级跳转')
    for item in (path, *path.parents):
        try:info = item.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('拒绝链接或重解析路径')
    return path


def read_stable(path):
    path = checked_path(path); before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 <= before.st_size <= MAX_FILE:
        raise ValueError('文件类型、链接或长度不符')
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno()); raw = stream.read(MAX_FILE+1)
        after = os.fstat(stream.fileno())
    current = path.lstat()
    keys = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if len(raw) != before.st_size or any(getattr(info, key) != getattr(before, key)
                                        for info in (opened, after, current) for key in keys):
        raise ValueError('读取期间原件变化')
    return raw


def new_file(path, raw):
    checked_path(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def readonly_kind():
    return 'windows-file-readonly-attribute' if os.name == 'nt' else 'posix-no-write-mode'


def check_readonly(root):
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in names:
            path = checked_path(Path(directory)/name)
            if path.stat().st_mode & stat.S_IWRITE:raise ValueError('原件仍可写')
            if os.name != 'nt' and path.stat().st_mode & 0o222:raise ValueError('原件权限仍允许写入')
        if os.name != 'nt':
            for path in (Path(directory), *(Path(directory)/name for name in dirs)):
                if checked_path(path).stat().st_mode & 0o222:raise ValueError('原件目录仍可写')


def inspect_workspace(root, manifest_sha256):
    root = checked_path(root)
    if (type(manifest_sha256) is not str or len(manifest_sha256) != 64
            or any(c not in '0123456789abcdef' for c in manifest_sha256)):
        raise ValueError('须提供独立核对的清单SHA256')
    descriptor = json.loads(read_stable(root/'WORKSPACE.json'))
    if descriptor != {'schema': 1, 'course': 'c05-synthetic-web-01', 'manifest_sha256': manifest_sha256,
                      'state': 'evidence-workspace-prepared', 'readonly_kind': readonly_kind()}:
        raise ValueError('工作区完成记录不符')
    original = root/'original'
    if sha(read_stable(original/'MANIFEST.json')) != manifest_sha256:raise ValueError('原件清单指纹不符')
    result = verify(original)
    check_readonly(original)
    return dict(result, state='evidence-workspace-verified', manifest_sha256=manifest_sha256,
                original_readonly_verified=True, readonly_kind=readonly_kind(),
                tamperproof=False, publisher_identity_verified=False, working_copy_checked=False,
                reports_checked=False, source_rechecked=False)


def prepare(source, destination, manifest_sha256):
    """只向新目录写入；部分结果保留，不覆盖、不自动继续或清理。"""
    source = checked_path(source); destination = checked_path(destination)
    if destination == source or source in destination.parents or destination.exists():
        raise ValueError('须使用原件目录外不存在的新工作区')
    verify(source)
    raw_manifest = read_stable(source/'MANIFEST.json')
    if sha(raw_manifest) != manifest_sha256:raise ValueError('清单指纹与已核对值不符')
    manifest = json.loads(raw_manifest)
    if manifest.get('course') != 'c05-synthetic-web-01':raise ValueError('非本课程')
    source_id = (source.stat().st_dev, source.stat().st_ino)
    files = {'MANIFEST.json': raw_manifest}
    for name, expected in manifest['files'].items():
        raw = read_stable(source/name)
        if sha(raw) != expected['sha256'] or len(raw) != expected['bytes']:raise ValueError('原件读取不符')
        files[name] = raw
    destination.mkdir(mode=0o700)
    for name in ('original', 'work', 'reports'):(destination/name).mkdir(mode=0o700)
    for tree in ('original', 'work'):
        for name, raw in files.items():
            path = destination/tree/name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            new_file(path, raw)
    # 源目录只读取；只对本次新快照撤销写权限，不把文件权限当不可篡改封存。
    original = destination/'original'
    for directory, dirs, names in os.walk(original, topdown=False):
        for name in names:os.chmod(Path(directory)/name, stat.S_IREAD if os.name == 'nt' else 0o400)
        if os.name != 'nt':os.chmod(directory, 0o500)
    verify(source)
    if source_id != (source.stat().st_dev, source.stat().st_ino):raise ValueError('原件目录身份变化')
    for name, raw in files.items():
        if read_stable(source/name) != raw:raise ValueError('准备期间原件变化')
    descriptor = {'schema': 1, 'course': manifest['course'], 'manifest_sha256': manifest_sha256,
                  'state': 'evidence-workspace-prepared', 'readonly_kind': readonly_kind()}
    new_file(destination/'WORKSPACE.json', json.dumps(descriptor, ensure_ascii=False, sort_keys=True).encode())
    return dict(inspect_workspace(destination, manifest_sha256), source_rechecked=True, source_modified=False)


def standalone_main(argv=None):
    parser = argparse.ArgumentParser(description='只读原件与独立调查副本；不运行样本、不联网')
    parser.add_argument('action', choices=('prepare', 'inspect'))
    parser.add_argument('directory', type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        result = (prepare(Path(__file__).absolute().parent, args.directory, args.manifest_sha256)
                  if args.action == 'prepare' else inspect_workspace(args.directory, args.manifest_sha256))
        print(json.dumps(result, ensure_ascii=False)); return 0
    except (OSError, ValueError, TypeError, KeyError):
        print('工作区未能确认；保留原件与本次目录，不覆盖或自动重做。'); return 2


def standalone_source():
    # 仅提取无答案的校验/副本准备函数，学生不依赖完整项目或教师模块。
    imports = 'import argparse,hashlib,json,os,stat\nfrom pathlib import Path,PurePosixPath\n'
    functions = (sha, verify, checked_path, read_stable, new_file, readonly_kind, check_readonly,
                 inspect_workspace, prepare, standalone_main)
    return (imports + f'MAX_FILE={MAX_FILE}\nMAX_TOTAL={MAX_TOTAL}\n'
            + '\n\n'.join(inspect.getsource(function) for function in functions)
            + "\nif __name__ == '__main__':raise SystemExit(standalone_main())\n")
