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
RUST_RELEASE_SHA256 = '54b950ba2acc4b7b894a295c7cc36efb4836dc30c6d2df33905d644261558e3c'
INVENTORY_RELEASE_SHA256 = '308273cb16d7d9e373ad40593a02ed236d386aea135ab63a6c78dd265798ab4e'


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



def apply_native_overlay(source, results):
    # Windows首轮已复现cp1252无法输出中文；只对已发布的精确Rust源施加这一处候选补丁。
    path = source/'desktop/src-tauri/src/main.rs'
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RUST_RELEASE_SHA256:
        raise ValueError('候选补丁前置源码不符，保留原文件')
    before = b'cmd.args(["-I", "-B"]).arg(script);'
    after = b'cmd.args(["-X", "utf8", "-I", "-B"]).arg(script);'
    if raw.count(before) != 1: raise ValueError('候选UTF8入口匹配不唯一')
    updated = raw.replace(before, after, 1)
    record(results/'candidate-source-overlay.json', {
        'path': 'desktop/src-tauri/src/main.rs', 'release_sha256': RUST_RELEASE_SHA256,
        'candidate_sha256': hashlib.sha256(updated).hexdigest(), 'reason': 'Windows英文区域下固定UTF8桥接',
        'source_archive_unchanged': True, 'already_public_release': False})
    with (results/'candidate-main.rs').open('xb') as stream: stream.write(updated)
    path.write_bytes(updated)



def apply_inventory_overlay(source, results):
    path = source/'tools/ctflab_runtime_inventory.py'
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != INVENTORY_RELEASE_SHA256:
        raise ValueError('运行时清单补丁前置源码不符，保留原文件')
    before = b'return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)'
    after = (b"timestamp = getattr(info, 'st_birthtime_ns', info.st_ctime_ns) if os.name == 'nt' else info.st_ctime_ns\n"
             b'    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, timestamp)')
    if raw.count(before) != 1: raise ValueError('清单补丁入口不唯一')
    updated = raw.replace(before, after, 1)
    record(results/'candidate-inventory-overlay.json', {
        'path': 'tools/ctflab_runtime_inventory.py', 'release_sha256': INVENTORY_RELEASE_SHA256,
        'candidate_sha256': hashlib.sha256(updated).hexdigest(), 'reason': 'Windows路径与文件句柄创建时间统一',
        'inode_size_mtime_and_hash_checks_preserved': True, 'already_public_release': False})
    with (results/'candidate-runtime_inventory.py').open('xb') as stream: stream.write(updated)
    path.write_bytes(updated)


def apply_pe_overlay(source, results):
    path = source/'tools/ctflab_pe_dependencies.py'
    raw = path.read_bytes()
    expected = 'd15270f6634b26c97e3b4e7af33d192c44ea4807bdebbd574800fe8731f810b8'
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('PE系统声明补丁前置源码不符')
    updated = raw.replace(b'mpr msvcrt ', b'mpr msi msvcrt ').replace(b'profapi psapi', b'profapi propsys psapi')
    if updated == raw: raise ValueError('PE系统声明未匹配')
    record(results/'candidate-pe-overlay.json', {'path': 'tools/ctflab_pe_dependencies.py',
        'release_sha256': expected, 'candidate_sha256': hashlib.sha256(updated).hexdigest(),
        'reason': 'Microsoft声明的Windows Installer与Property System系统DLL',
        'os_contracts_verified': False, 'already_public_release': False})
    with (results/'candidate-pe_dependencies.py').open('xb') as stream: stream.write(updated)
    path.write_bytes(updated)


def timestamp_probe(path, results):
    fields = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_birthtime_ns')
    before = path.stat()
    with path.open('rb') as stream: opened = os.fstat(stream.fileno())
    after = path.stat()
    record(results/'windows-file-stat.json', {
        'path': path.name, 'python': sys.version.split()[0],
        'before': {n: getattr(before,n,None) for n in fields},
        'opened': {n: getattr(opened,n,None) for n in fields},
        'after': {n: getattr(after,n,None) for n in fields}})


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
    apply_native_overlay(source, results)
    apply_inventory_overlay(source, results)
    apply_pe_overlay(source, results)
    pyroot=root/'python';prepare_python(Path(sys.executable).parent, pyroot)
    requirements=Path(__file__).with_name('requirements-windows-native-ci.txt')
    command([sys.executable,'-I','-m','pip','install','--only-binary=:all:','--require-hashes','--no-deps',
             '--no-compile','--target',pyroot/'Lib/site-packages','-r',requirements],results/'python-dependencies.log')
    for suite in ('test_ctflab_windows_native.py', 'test_ctflab_windows_control.py'):
        command([pyroot/'python.exe', '-X', 'utf8', '-B', '-m', 'unittest', 'discover', '-s', 'tools/tests', '-p', suite, '-v'],
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
    timestamp_probe(qroot/'qemu-system-x86_64.exe', results)
    tool=source/'tools/ctflab_runtime_inventory.py';inventory=root/'qemu-inventory.json'
    command([pyroot/'python.exe','-I','-B',tool,'--root',qroot,'--output',inventory],results/'qemu-inventory.log')
    launch_standard(root, results)


def launch_standard(root, results):
    # 云端runner默认管理员；仅在本轮新根授予一次性标准用户访问，不绕过应用普通用户门。
    launcher = shutil.which('rustup')
    if not launcher: raise ValueError('缺少runner已安装的rustup入口')
    shutil.copy2(launcher, root/'rustup.exe')
    shutil.copy2(Path(__file__).resolve(), root/'standard-ci.py')
    record(root/'standard-context.json', {
        'python': sys.executable, 'script': str(root/'standard-ci.py'), 'path': os.environ['PATH'],
        'github_run_id': os.environ['GITHUB_RUN_ID'], 'github_run_attempt': os.environ['GITHUB_RUN_ATTEMPT']})
    bootstrap = root/'standard-bootstrap.ps1'
    bootstrap.write_text(r'''param([string]$RunRoot)
$ErrorActionPreference = 'Stop'
$ctx = Get-Content -LiteralPath (Join-Path $RunRoot 'standard-context.json') -Raw | ConvertFrom-Json
$env:PATH = $ctx.path
$env:GITHUB_ACTIONS = 'true'
$env:RUNNER_OS = 'Windows'
$env:RUNNER_TEMP = Split-Path -Parent $RunRoot
$env:GITHUB_RUN_ID = $ctx.github_run_id
$env:GITHUB_RUN_ATTEMPT = $ctx.github_run_attempt
$env:USERPROFILE = [Environment]::GetFolderPath('UserProfile')
$env:APPDATA = [Environment]::GetFolderPath('ApplicationData')
$env:LOCALAPPDATA = [Environment]::GetFolderPath('LocalApplicationData')
& $ctx.python -X utf8 -I -B $ctx.script build-standard --root $RunRoot
exit $LASTEXITCODE
''', encoding='utf-8')
    launch = root/'launch-standard.ps1'
    launch.write_text(r'''param([string]$RunRoot)
$ErrorActionPreference = 'Stop'
$ctx = Get-Content -LiteralPath (Join-Path $RunRoot 'standard-context.json') -Raw | ConvertFrom-Json
$name = 'ctflab' + $ctx.github_run_id.Substring([Math]::Max(0,$ctx.github_run_id.Length-8))
if (Get-LocalUser -Name $name -ErrorAction SilentlyContinue) { throw '测试账户已存在；拒绝接管。' }
$random = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$password = ConvertTo-SecureString ('Aa1!' + $random) -AsPlainText -Force
New-LocalUser -Name $name -Password $password -AccountNeverExpires -UserMayNotChangePassword | Out-Null
Add-LocalGroupMember -SID 'S-1-5-32-545' -Member $name
$account = "$env:COMPUTERNAME\$name"
# RunRoot由本轮排他创建；不修改仓库、系统目录或任何原有用户根ACL。
$acl = Get-Acl -LiteralPath $RunRoot
$rule = [Security.AccessControl.FileSystemAccessRule]::new($account,'Modify','ContainerInherit,ObjectInherit','None','Allow')
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $RunRoot -AclObject $acl
$credential = [Management.Automation.PSCredential]::new($account,$password)
$workerArguments = @('-NoProfile','-NonInteractive','-File',(Join-Path $RunRoot 'standard-bootstrap.ps1'),'-RunRoot',$RunRoot)
$p = Start-Process -FilePath (Get-Command pwsh.exe).Source -ArgumentList $workerArguments -WorkingDirectory $RunRoot -Credential $credential -LoadUserProfile -UseNewEnvironment -Wait -PassThru -RedirectStandardOutput (Join-Path $RunRoot 'results/standard.stdout.log') -RedirectStandardError (Join-Path $RunRoot 'results/standard.stderr.log')
exit $p.ExitCode
''', encoding='utf-8')
    command(['pwsh','-NoProfile','-NonInteractive','-File',launch,'-RunRoot',root],
            results/'standard-launch.log', timeout=3000)


def build_standard(root):
    if os.name != 'nt' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise ValueError('只允许本轮云端Windows普通用户入口')
    run_id, attempt = os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT']
    expected = Path(os.environ['RUNNER_TEMP'])/f'ctflab-native-{run_id}-{attempt}'
    if root != expected or root.is_symlink(): raise ValueError('普通用户运行根不符')
    results = root/'results'; source = root/'source'; pyroot = root/'python'; qroot = root/'qemu'
    sys.path.insert(0, str(source/'tools'))
    from ctflab_windows_security import WindowsSecurity
    # 明确验证非提权令牌；管理员环境仍拒绝，不能记为普通用户测试。
    WindowsSecurity().current_user()
    if not all(os.environ.get(n) and Path(os.environ[n]).is_absolute() for n in ('USERPROFILE','APPDATA','LOCALAPPDATA')):
        raise ValueError('普通用户配置目录未加载，拒绝安装')
    record(results/'standard-user.json', {'non_elevated_user_verified': True,
           'profile_paths_present': all(os.environ.get(n) for n in ('USERPROFILE','APPDATA','LOCALAPPDATA')),
           'host': platform.platform(), 'temporary_ci_account_only': True})
    os.environ['CARGO_HOME'] = str(root/'cargo-home')
    os.environ['RUSTUP_HOME'] = str(root/'rustup-home')
    from ctflab_desktop_package import static_imports
    incomplete = []
    for name, directory, entry in [('python', pyroot, 'python.exe'), ('qemu', qroot, 'qemu-system-x86_64.exe')]:
        from ctflab_pe_dependencies import PE
        diagnostics = []
        for binary in sorted(directory.rglob('*')):
            if binary.suffix.lower() not in ('.exe','.dll','.pyd','.drv'): continue
            image = PE(binary.read_bytes())
            try: image.dependencies()
            except Exception as error:
                diagnostics.append({'name':binary.relative_to(directory).as_posix(),
                    'sha256':digest(binary),'directories':image.directories,
                    'error':type(error).__name__+': '+str(error)})
        record(results/(name+'-pe-diagnostics.json'), diagnostics)
        report = static_imports(directory, entry)
        record(results/(name+'-static-imports.json'), report)
        if not report['bundled_static_dependencies_present']:
            incomplete.append(name)
    if incomplete: raise ValueError(','.join(incomplete)+'静态依赖尚未闭合，报告保留，不跳过检查')
    rustup_bin = root/'cargo-home/bin';rustup_bin.mkdir(parents=True)
    shutil.copy2(root/'rustup.exe', rustup_bin/'rustup.exe')
    command([rustup_bin/'rustup.exe','toolchain','install','1.90.0','--profile','minimal'],results/'standard-rust-toolchain.log')
    toolchain = root/'rustup-home/toolchains/1.90.0-x86_64-pc-windows-msvc/bin'
    os.environ['PATH'] = str(toolchain)+os.pathsep+str(rustup_bin)+os.pathsep+os.environ['PATH']
    build=root/'build';inventory=root/'qemu-inventory.json'
    command(['pwsh','-NoProfile','-NonInteractive','-File',source/'desktop/Build-Windows.ps1',
             '-PythonRoot',pyroot,'-QemuRoot',qroot,'-QemuInventory',inventory,'-BuildRoot',build],results/'build-standard.log',timeout=2700)
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
    parser.add_argument('action',choices=['run','verify-snapshot','build-standard']);parser.add_argument('--archive',type=Path);parser.add_argument('--root',type=Path)
    args=parser.parse_args()
    if args.action=='verify-snapshot':
        if args.archive is None:parser.error('需要--archive')
        if digest(args.archive)!=SOURCE_SHA256:raise ValueError('固定源码ZIP摘要不符')
        files=snapshot_files(args.archive);print(json.dumps({'files':len(files),'source_sha256':SOURCE_SHA256}));return
    if args.action=='build-standard':
        if args.root is None:parser.error('需要--root')
        build_standard(args.root);return
    run()


if __name__=='__main__':main()
