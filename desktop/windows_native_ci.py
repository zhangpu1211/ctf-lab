"""只在GitHub临时Windows主机进行固定候选构建/安装检查；不运行VM、不公开发布。"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile

SOURCE_URL = 'https://github.com/zhangpu1211/ctf-lab/releases/download/v0.1.4-preview.20261030/CTFLab-0.1.4-preview.20261030-source-snapshot.zip'
SOURCE_SHA256 = '62e870b6700a83031a3c9f1e4cfbded3207be7d9a839e2ef6d72c200608093fd'
QEMU_URL = 'https://qemu.weilnetz.de/w64/2026/qemu-w64-setup-20260811.exe'
QEMU_SHA512 = '5bcf9eed634e8575a37b74f445af41a2fe4106da512d0c30c368301d4c105037fdfab40a5287367a28a957624cddebbc8c07e16c88ab6634f554cdf3d16bf543'
QEMU_BINARY_SHA256 = '47d57a6072e0bb3bd98f87926eb129eb1736dfe818c67b3b81ef7ce4edd0b3cd'


def digest(path, algorithm='sha256'):
    value = hashlib.new(algorithm)
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): value.update(block)
    return value.hexdigest()


def record(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def download(url, path, expected, algorithm='sha256', limit=256 * 1024**2):
    with urllib.request.urlopen(url, timeout=120) as response, path.open('xb') as target:
        if not response.url.startswith('https://'): raise ValueError('拒绝非HTTPS重定向')
        count = 0
        for data in iter(lambda: response.read(1024 * 1024), b''):
            count += len(data)
            if count > limit: raise ValueError('下载超过固定容量边界')
            target.write(data)
    if digest(path, algorithm) != expected: raise ValueError('输入摘要不符，文件保留，不执行')


def snapshot_files(archive):
    """先完整验证再写任何源码；拒绝大小写别名、链接、额外文件和摘要漂移。"""
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if not 1 <= len(entries) <= 1024 or sum(v.file_size for v in entries) > 64*1024**2:
            raise ValueError('源码归档范围不符')
        names = set()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (path.is_absolute() or not path.parts or '..' in path.parts or '\\' in entry.filename
                    or ':' in entry.filename or entry.is_dir() or str(path) != entry.filename
                    or any(p.endswith((' ', '.')) for p in path.parts)
                    or stat.S_ISLNK(entry.external_attr >> 16) or entry.filename.casefold() in names):
                raise ValueError('源码归档路径/类型不符')
            names.add(entry.filename.casefold())
        manifest = json.loads(source.read('SOURCE-MANIFEST.json'))
        if (manifest.get('schema') != 1 or manifest.get('version') != '0.1.4'
                or manifest.get('kind') != 'source-snapshot' or type(manifest.get('files')) is not dict):
            raise ValueError('源码清单类型不符')
        files = manifest['files']
        if set(files) | {'SOURCE-MANIFEST.json'} != {v.filename for v in entries}:
            raise ValueError('源码清单与完整文件集合不符')
        payload = {name: source.read(name) for name in files}
        if any(hashlib.sha256(raw).hexdigest() != files[name] for name, raw in payload.items()):
            raise ValueError('源码摘要不符')
        return payload


def command(args, log, **options):
    # 日志仅收本轮构建/检查输出，不记录环境变量、访问令牌或用户目录。
    with log.open('x', encoding='utf-8') as stream:
        subprocess.run(args if isinstance(args, str) else [str(a) for a in args], stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=options.pop('timeout', 1800), **options)


def copy_plain(source, destination):
    info = source.lstat()
    if source.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('复制来源不能是链接或重解析点')
    if source.is_dir():
        destination.mkdir()
        for item in source.iterdir(): copy_plain(item, destination / item.name)
    elif source.is_file() and info.st_nlink == 1:
        with source.open('rb') as src, destination.open('xb') as dst: shutil.copyfileobj(src, dst)
    else: raise ValueError('复制来源必须是独立普通文件')


def prepare_python(original, target):
    # 保留Tcl/Tk和标准库；不把pip内的32位启动器/构建工具带入x64运行时。
    target.mkdir()
    for item in original.iterdir():
        if item.is_file() and (item.name in ('python.exe', 'pythonw.exe')
                              or item.suffix.lower() == '.dll' or item.name.lower().startswith('license')):
            copy_plain(item, target/item.name)
    for name in ('DLLs', 'tcl'):
        copy_plain(original/name, target/name)
    (target/'Lib').mkdir()
    for item in (original/'Lib').iterdir():
        if item.name not in ('site-packages', 'ensurepip', 'idlelib', 'test', 'turtledemo', 'venv', '__pycache__'):
            copy_plain(item, target/'Lib'/item.name)
    (target/'Lib/site-packages').mkdir()


def window_for_process(pid):
    """只观察本次Popen的可见顶层窗口；不按名称操控其他进程。"""
    user = ctypes.WinDLL('user32', use_last_error=True)
    from ctypes import wintypes
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
    found = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, unused):
        value = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(value))
        if value.value == pid and user.IsWindowVisible(hwnd): found.append(hwnd)
        return True
    user.EnumWindows(visit, 0)
    return found[0] if found else None


def inspect_install(installer, build, root, results):
    payload = json.loads((build/'stage-result.json').read_text(encoding='utf-8-sig'))
    manifest_sha = payload['manifest_sha256']
    # 只有临时GitHub主机且两类应用数据根均不存在时才准备本轮保留标记。
    data_roots = [Path(os.environ['LOCALAPPDATA'])/'CTFLabData',
                  Path(os.environ['APPDATA'])/'org.ctflab.desktop']
    if any(path.exists() for path in data_roots): raise ValueError('发现已有应用数据；不安装或卸载')
    tools = root/'source/tools';sys.path.insert(0, str(tools))
    from ctflab_windows_security import WindowsSecurity
    from ctflab_desktop_package import verify_staging
    security = WindowsSecurity()
    sentinels = {}
    for path in data_roots:
        security.create_directory(path)
        marker = path/'native-acceptance-sentinel.json'
        record(marker, {'scope': '本轮自动安装数据保留检查', 'run_id': os.environ['GITHUB_RUN_ID']})
        sentinels[str(marker)] = digest(marker)
    record(results/'sentinels-before.json', sentinels)
    install = root/'installed-app'
    # NSIS要求/D路径处于末尾且不加引号；字符串直接交CreateProcess，不经过shell。
    command(subprocess.list2cmdline([str(installer)])+' /S /D='+str(install), results/'install.log', timeout=600)
    binaries = list(install.glob('*.exe'))
    app = next((p for p in binaries if p.name.casefold() == 'ctflab-desktop.exe'), None)
    if app is None: raise ValueError('未找到实际安装的固定桌面入口，保留现场')
    # 校验实际安装载荷，不把暂存目录的成功等同于安装后的成功。
    installed_manifest = json.loads((build/'payload/bundle-manifest.json').read_text())
    actual = {p.relative_to(install/'runtime').as_posix(): digest(p)
              for p in (install/'runtime').rglob('*') if p.is_file()}
    if actual != installed_manifest['files']: raise ValueError('实际安装的运行时文件集合/摘要不符')
    script = ('import sys,json,ssl,tkinter,yaml,cryptography;'
              'from pathlib import Path;root=Path(sys.executable).resolve().parent;'
              'assert all(root in Path(m.__file__).resolve().parents for m in (ssl,tkinter,yaml,cryptography));'
              'assert yaml.__version__=="6.0.3" and cryptography.__version__=="46.0.5";'
              'print(json.dumps({"bundle_imports":True,"python":sys.version.split()[0]}))')
    command([install/'runtime/python/python.exe', '-I', '-B', '-c', script], results/'installed-runtime.log', timeout=60)
    child = subprocess.Popen([str(app)], cwd=install, stdin=subprocess.DEVNULL)
    record(results/'own-gui-process.json', {'pid': child.pid, 'executable': str(app), 'no_vm_action': True})
    deadline = time.monotonic()+60; hwnd = None
    while child.poll() is None and time.monotonic() < deadline:
        hwnd = window_for_process(child.pid)
        if hwnd: break
        time.sleep(.5)
    if not hwnd: raise ValueError('未观察到本次GUI可见窗口；不强杀或继续卸载')
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE，仅向自有GUI请求正常关闭。
    child.wait(timeout=30)
    if child.returncode != 0: raise ValueError('GUI正常退出返回非零，保留现场')
    uninstaller = install/'uninstall.exe'
    if not uninstaller.is_file(): raise ValueError('缺少实际卸载器')
    command(subprocess.list2cmdline([str(uninstaller)])+' /S _?='+str(install), results/'uninstall.log', timeout=180)
    deadline = time.monotonic()+30
    while app.exists() and time.monotonic() < deadline: time.sleep(.5)
    if app.exists() or any(not Path(p).is_file() or digest(p) != sha for p,sha in sentinels.items()):
        raise ValueError('卸载未移除程序或改变本轮应用数据标记；保留现场')
    verify_staging(build/'payload', manifest_sha)
    record(results/'installation-results.json', {'os': platform.platform(), 'installed_payload_matches': True,
           'visible_native_window_observed': True, 'gui_normal_exit': True, 'uninstall_program_removed': True,
           'application_data_sentinels_preserved': True, 'manual_ui_verified': False, 'windows_11_verified': False,
           'whpx_or_vm_or_course_verified': False, 'authenticode_release_signed': False, 'g0_passed': False, 'g1_passed': False})


def run():
    if (os.name != 'nt' or os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_OS') != 'Windows'):
        raise ValueError('只允许GitHub临时Windows主机，不操作现有个人电脑')
    run_id, attempt = os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT']
    if not run_id.isdecimal() or not attempt.isdecimal(): raise ValueError('运行标识无效')
    root = Path(os.environ['RUNNER_TEMP'])/f'ctflab-native-{run_id}-{attempt}'
    root.mkdir();results=root/'results';results.mkdir()
    record(results/'scope.json', {'os':platform.platform(),'root':str(root),'vm_operations':False,'public_release':False})
    source_zip=root/'source.zip';download(SOURCE_URL, source_zip, SOURCE_SHA256, limit=8*1024**2)
    files=snapshot_files(source_zip);source=root/'source';source.mkdir()
    for name,raw in files.items():
        target=source/name;target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream:stream.write(raw)
    pyroot=root/'python';prepare_python(Path(sys.executable).parent, pyroot)
    requirements=Path(__file__).with_name('requirements-windows-native-ci.txt')
    command([sys.executable,'-I','-m','pip','install','--only-binary=:all:','--require-hashes','--no-deps',
             '--no-compile','--target',pyroot/'Lib/site-packages','-r',requirements],results/'python-dependencies.log')
    for suite in ('test_ctflab_windows_native.py', 'test_ctflab_windows_control.py'):
        command([pyroot/'python.exe', '-B', '-m', 'unittest', 'discover', '-s', 'tools/tests', '-p', suite, '-v'],
                results/(suite+'.log'), cwd=source, timeout=180)
    archive=root/'qemu-installer.exe';download(QEMU_URL, archive, QEMU_SHA512, 'sha512')
    extracted=root/'qemu-extracted'
    command(['7z','x',archive,'-o'+str(extracted)],results/'qemu-extract.log')
    candidates=list(extracted.rglob('qemu-system-x86_64.exe'))
    if len(candidates)!=1 or digest(candidates[0])!=QEMU_BINARY_SHA256:raise ValueError('固定QEMU二进制不符')
    qroot=root/'qemu';qroot.mkdir()
    for item in candidates[0].parent.iterdir():
        if ((item.is_file() and (item.suffix.lower()=='.dll' or item.name in ('qemu-system-x86_64.exe','qemu-img.exe')
                                or item.name.lower().startswith(('copying','license','readme'))))
                or item.is_dir() and item.name in ('share','etc','lib','licenses')):
            copy_plain(item,qroot/item.name)
    record(results/'input-provenance.json', {'source_sha256':digest(source_zip),'qemu_installer_sha512':digest(archive,'sha512'),
          'qemu_binary_sha256':digest(qroot/'qemu-system-x86_64.exe'),'python':sys.version.split()[0],
          'python_setup_action_pinned':True,'source_signature_verified':False})
    tool=source/'tools/ctflab_runtime_inventory.py';inventory=root/'qemu-inventory.json'
    command([pyroot/'python.exe','-I','-B',tool,'--root',qroot,'--output',inventory],results/'qemu-inventory.log')
    command(['rustup','toolchain','install','1.90.0','--profile','minimal'],results/'rust-toolchain.log')
    build=root/'build'
    command(['pwsh','-NoProfile','-NonInteractive','-File',source/'desktop/Build-Windows.ps1',
             '-PythonRoot',pyroot,'-QemuRoot',qroot,'-QemuInventory',inventory,'-BuildRoot',build],results/'build.log',timeout=2700)
    for name in ('stage-result.json','installer-results.json'):
        shutil.copy2(build/name,results/name)
    installers=list((build/'installers').glob('*.exe'))
    if len(installers)!=1:raise ValueError('本轮安装器数量不符')
    shutil.copy2(installers[0],results/installers[0].name)
    inspect_install(installers[0],build,root,results)
    record(results/'completion.json', {'native_build':True,'automated_install_check':True,'signed_public_release':False,
           'windows_11_or_real_guest_verified':False,'existing_user_vm_or_assets_operated':False})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['run','verify-snapshot']);parser.add_argument('--archive',type=Path)
    args=parser.parse_args()
    if args.action=='verify-snapshot':
        if args.archive is None:parser.error('需要--archive')
        if digest(args.archive)!=SOURCE_SHA256:raise ValueError('固定源码ZIP摘要不符')
        files=snapshot_files(args.archive);print(json.dumps({'files':len(files),'source_sha256':SOURCE_SHA256}));return
    run()


if __name__=='__main__':main()
