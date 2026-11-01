"""为 Windows NSIS 构建准备独立运行时；显式来源清单，不下载镜像或安装依赖。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))

from ctflab_contract import require,canonical
from ctflab_generation_store import private_directory,digest
from ctflab_runtime_inventory import inventory,compare,validate_reference,listing,hash_file,check_path
from ctflab_windows_recovery_kit import FILES as RECOVERY_FILES
from ctflab_windows_control import read_json
from ctflab_windows_smoke import QEMU_SHA
from ctflab_windows_recovery import record

TOOLS=tuple(sorted({n for n in RECOVERY_FILES if n.startswith('tools/') and '/tests/' not in n} | {
    'tools/ctflab_windows_storage.py','tools/ctflab_storage_bind.py','tools/ctflab_pe_dependencies.py',
    'tools/ctflab_external_attach.py','tools/ctflab_external_l2.py','tools/ctflab_kali_attach.py',
    'tools/ctflab_scenario_runtime.py','tools/ctflab_scenario.py','tools/ctflab_scenario_registry.py',
    'tools/ctflab_scenario_resources.py','tools/ctflab_scenario_services.py','tools/ctflab_network.py',
    'tools/ctflab_platform.py','tools/ctflab_darwin_native.py','tools/ctflab_macos_storage.py',
    'tools/ctflab_ir_course.py','tools/ctflab_windows_course_events.py',
    'tools/ctflab_waf_course.py',
    'tools/ctflab_server_storage.py',
    'tools/ctflab_cache_gc.py',
    'tools/ctflab_external_ip.py','tools/ctflab_windows_ip.py','tools/ctflab_windows_firewall.py','tools/ctflab_desktop_package.py','tools/ctflab_release_online.py','tools/ctflab_windows_limits.py','tools/ctflab_watch.py','tools/ctflab_manage.py',
    'tools/ctflab_desktop_bridge.py','tools/ctflab_local_adapter.py','tools/ctflab_topology.py','tools/ctflab_policy_review.py',
    'tools/ctflab_catalog.py','tools/ctflab_diagnostics_public.py','tools/ctflab_content_cache.py',
    'tools/ctflab_release_store.py','tools/ctflab_acceptance_session.py','tools/ctflab_delivery.py',
    'tools/ctflab_linux_native.py','tools/ctflab_guest_policy.py','tools/ctflab_guest_channel.py',
    'tools/ctflab_guest_agent.py','tools/ctflab_guest_kit.py','tools/ctflab_mirror.py','tools/ctflab_mirror_service.py',
    'tools/ctflab_bounded_log.py','tools/ctflab_recoverable_log.py','tools/ctflab_release_update.py','tools/ctflab_remote.py',
    'tools/ctflab_evidence_export.py','tools/ctflab_remote_assets.py','tools/ctflab_remote_course.py','tools/ctflab_remote_display.py','tools/ctflab_external.py','tools/ctflab_external_events.py','tools/ctflab_remote_evidence.py','tools/ctflab_client_evidence.py','tools/ctflab_oci.py','tools/ctflab_guest_routes.py','tools/ctflab_guest_routed.py','tools/ctflab_guest_analysis.py',
    'tools/ctflab_release_launcher.py','tools/ctflab_version_bridge.py','tools/ctflab_version_setup.py','tools/ctflab_cgroup.py','tools/ctflab_audit_archive.py','tools/ctflab_audit_rotation.py',
    'tools/ctflab_lease_store.py','tools/ctflab_remote_leases.py','tools/ctflab_lease_scheduler.py','tools/ctflab_remote_audit.py','tools/ctflab_audit_review.py',
    'tools/ctflab_desktop_remote.py','tools/ctflab_client_store.py','tools/ctflab_client_assets.py'}))


def component(root):
    root=Path(root).absolute();files=listing(root)
    entries=[{'name':name,'size':info.st_size,'sha256':hash_file(root/name,info)} for name,info in sorted(files.items())]
    current=listing(root)
    require(set(files)==set(current) and all(hash_file(root/name,info)==item['sha256'] for item,(name,info) in zip(entries,sorted(current.items()))),'state-conflict')
    return {'files':entries,'inventory_sha256':hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'schema':1,'scope':'runtime-directory-inventory-only','source_verified':False}


def copy_component(source,target,reference):
    private_directory(target)
    for item in validate_reference(reference):
        original=source/item['name'];check_path(original)
        require(digest(original)==item['sha256'],'state-conflict')
        destination=target/item['name']
        for parent in reversed(destination.parents):
            if parent!=target and target in parent.parents and not parent.exists():private_directory(parent)
        fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with original.open('rb') as input,os.fdopen(fd,'wb') as output:
            shutil.copyfileobj(input,output);output.flush();os.fsync(output.fileno())
        require(digest(destination)==item['sha256'],'state-conflict')


def static_imports(root,required):
    from ctflab_pe_dependencies import analyze
    files=listing(root);entries=sorted(name for name in files if Path(name).suffix.lower() in ('.exe','.dll','.pyd','.drv'))
    require(required in entries,'capability-unverified')
    directories=['.']+(['DLLs'] if (root/'DLLs').is_dir() else [])
    return analyze(root,entries,directories)


def stage(source,destination,python_root,python_inventory,qemu_root,qemu_inventory,*,inspect_imports=False):
    require(type(inspect_imports) is bool)
    source=Path(source).absolute();destination=Path(destination).absolute()
    python_root=Path(python_root).absolute();qemu_root=Path(qemu_root).absolute()
    # 防止将输出放入输入中，或把用户数据目录当作安装载荷。
    require(all(destination!=p and destination not in p.parents and p not in destination.parents
                for p in (source,python_root,qemu_root)))
    require(not destination.exists(),'state-conflict')
    python_reference=read_json(Path(python_inventory),lambda _:None,8*1024**2)
    qemu_reference=read_json(Path(qemu_inventory),lambda _:None,8*1024**2)
    require(compare(python_reference,component(python_root))['matches'],'state-conflict')
    require(compare(qemu_reference,inventory(qemu_root))['matches'],'state-conflict')
    require(digest(qemu_root/'qemu-system-x86_64.exe')==QEMU_SHA,'state-conflict')
    names={n['name'] for n in validate_reference(python_reference)}
    require('python.exe' in names and any('cryptography' in n for n in names),'capability-unverified')
    for reference in (python_reference,qemu_reference):
        require(any(Path(n['name']).name.lower() in ('license','license.txt','license.rst','copying','copying.txt')
                    for n in validate_reference(reference)),'permission-denied')
    reports=None
    if inspect_imports:
        reports={'schema':1,'python':static_imports(python_root,'python.exe'),
                 'qemu':static_imports(qemu_root,'qemu-system-x86_64.exe')}
        require(all(reports[k]['bundled_static_dependencies_present'] for k in ('python','qemu')),'capability-unverified')
    required=sum(n['size'] for ref in (python_reference,qemu_reference) for n in validate_reference(ref))
    require(shutil.disk_usage(destination.parent).free>required+64*1024**2,'storage-insufficient')
    private_directory(destination);runtime=destination/'runtime';private_directory(runtime)
    copy_component(python_root,runtime/'python',python_reference)
    copy_component(qemu_root,runtime/'qemu',qemu_reference)
    private_directory(runtime/'tools')
    for name in TOOLS:
        target=runtime/'tools'/Path(name).name
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as output:output.write((source/name).read_bytes())
    fd=os.open(runtime/'THIRD_PARTY_NOTICES.md',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as output:output.write((source/'desktop/THIRD_PARTY_NOTICES.md').read_bytes())
    if reports is not None:record(runtime/'static-imports.json',reports)
    record(runtime/'qemu-inventory.json',qemu_reference)
    record(runtime/'python-inventory.json',python_reference)
    manifest={str(p.relative_to(runtime)).replace(os.sep,'/'):digest(p) for p in runtime.rglob('*') if p.is_file()}
    record(destination/'bundle-manifest.json',{'schema':1,'kind':'windows-desktop-staging','files':manifest,
           'static_imports_checked':reports is not None,'static_import_report_sha256':digest(runtime/'static-imports.json') if reports else None,
           'dependency_closure_verified':False,'source_verified':False,'signature_verified':False,'g0_passed':False,'g1_passed':False})
    record(destination/'tauri.bundle.json',{'bundle':{'active':True,'resources':{str(runtime):'runtime/'}}})
    return {'state':'staged','files':len(manifest),'signature_verified':False,'installer_built':False,'static_imports_checked':reports is not None,
            'manifest_sha256':digest(destination/'bundle-manifest.json')}


def verify_staging(destination,expected_manifest_sha256):
    # 摘要须由调用方独立保留；同目录内可修改的清单本身不是信任根。
    require(isinstance(expected_manifest_sha256,str) and len(expected_manifest_sha256)==64
            and all(c in '0123456789abcdef' for c in expected_manifest_sha256))
    root=Path(destination).absolute();manifest=root/'bundle-manifest.json'
    info=check_path(manifest)
    require(hash_file(manifest,info)==expected_manifest_sha256,'state-conflict')
    value=read_json(manifest,check_path,8*1024**2)
    require(type(value) is dict and type(value.get('schema')) is int and value['schema']==1
            and value.get('kind')=='windows-desktop-staging')
    files=value.get('files');require(type(files) is dict and files)
    # 复用路径/摘要/数量校验，避免清单路径穿越、Windows别名或空集合。
    entries=[{'name':name,'size':0,'sha256':sha} for name,sha in sorted(files.items())]
    validate_reference({'schema':1,'scope':'runtime-directory-inventory-only','files':entries,
        'inventory_sha256':hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(',',':')).encode()).hexdigest()})
    current=component(root/'runtime')
    require({item['name']:item['sha256'] for item in current['files']}==files,'state-conflict')
    require({'python/python.exe','python-inventory.json','qemu-inventory.json'}<=set(files))
    require(hash_file(manifest,info)==expected_manifest_sha256,'state-conflict')
    return value


def probe(destination,expected_manifest_sha256=None):
    require(os.name=='nt','unsupported-platform')
    root=Path(destination).absolute();runtime=root/'runtime'
    verify_staging(root,expected_manifest_sha256)
    require(not (root/'python-probe.json').exists(),'state-conflict')
    # 仅执行显式准备的固定Python；探测其依赖是否从随包目录加载。
    script=('import sys,ssl,tkinter,json,cryptography,cryptography.hazmat.bindings._rust; '
            'from pathlib import Path; '
            'root=Path(sys.executable).resolve().parent; '
            'mods=[ssl,tkinter,cryptography,cryptography.hazmat.bindings._rust]; '
            'assert cryptography.__version__=="46.0.5"; '
            'assert all(root in Path(m.__file__).resolve().parents for m in mods); '
            'print(json.dumps({"imports_from_bundle":True,"python":sys.version.split()[0],"cryptography":cryptography.__version__}))')
    result=subprocess.run([str(runtime/'python'/'python.exe'),'-I','-B','-c',script],
                          capture_output=True,timeout=30,check=True,stdin=subprocess.DEVNULL,cwd=runtime/'python')
    verify_staging(root,expected_manifest_sha256)
    value=json.loads(result.stdout)
    require(type(value) is dict and set(value)=={'imports_from_bundle','python','cryptography'}
            and value['imports_from_bundle'] is True and value['cryptography']=='46.0.5'
            and isinstance(value['python'],str) and len(value['python'])<=64,'capability-unverified')
    value.update({'manifest_sha256':expected_manifest_sha256,'signature_verified':False,'dependency_closure_verified':False})
    record(root/'python-probe.json',value)
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('python-inventory');p.add_argument('--root',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p=sub.add_parser('stage')
    for key in ('destination','python-root','python-inventory','qemu-root','qemu-inventory'):p.add_argument('--'+key,required=True,type=Path)
    p.add_argument('--inspect-imports',action='store_true',help='复制前静态核对所有exe/dll/pyd，失败时不创建输出目录')
    p=sub.add_parser('inspect-imports');p.add_argument('--root',required=True,type=Path);p.add_argument('--entry',required=True,action='append');p.add_argument('--search-dir',action='append',default=[])
    p=sub.add_parser('probe');p.add_argument('--destination',required=True,type=Path)
    p.add_argument('--manifest-sha256',required=True,help='暂存时独立保存的清单摘要；探测前后核对全部载荷')
    p=sub.add_parser('verify');p.add_argument('--destination',required=True,type=Path)
    p.add_argument('--manifest-sha256',required=True,help='只读核对调用方独立保存的清单摘要及完整载荷')
    p=sub.add_parser('workspace');p.add_argument('--destination',required=True,type=Path)
    args=parser.parse_args(argv)
    try:
        if args.action=='workspace':
            private_directory(args.destination.absolute());value={'state':'private-workspace-created'}
        elif args.action=='python-inventory':
            value=component(args.root);record(args.output.absolute(),value)
        elif args.action=='inspect-imports':
            from ctflab_pe_dependencies import analyze
            value=analyze(args.root,args.entry,args.search_dir)
            print(canonical(value));return 0 if value['bundled_static_dependencies_present'] else 2
        elif args.action=='stage':value=stage(Path(__file__).resolve().parents[1],args.destination,args.python_root,args.python_inventory,args.qemu_root,args.qemu_inventory,inspect_imports=args.inspect_imports)
        elif args.action=='verify':
            manifest=verify_staging(args.destination,args.manifest_sha256)
            value={'state':'payload-matches','files':len(manifest['files']),
                   'manifest_sha256':args.manifest_sha256,'signature_verified':False,'dependency_closure_verified':False}
        else:value=probe(args.destination,args.manifest_sha256)
        print(canonical(value if args.action!='python-inventory' else {'state':'inventory-created','files':len(value['files'])}));return 0
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError):
        print(canonical({'state':'failed','preserved':True,'installer_built':False}));return 2


if __name__=='__main__':raise SystemExit(main())
