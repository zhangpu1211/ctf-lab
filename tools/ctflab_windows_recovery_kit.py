"""可恢复运行候选源码包；显式依赖白名单，不含镜像、证书或运行记录。"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from ctflab_windows_control_kit import FILES as CONTROL_FILES

FILES = tuple(n for n in CONTROL_FILES if not n.startswith('docs/')) + (
    'tools/ctflab_tls_endpoint.py','tools/ctflab_qmp_tls.py','tools/ctflab_rfb_tls.py',
    'tools/ctflab_qemu_driver.py','tools/ctflab_scenario_coordinator.py',
    'tools/ctflab_bounded_log.py',
    'tools/ctflab_supervisor_fault.py','tools/tests/test_ctflab_supervisor_fault.py',
    'tools/ctflab_linux_native.py','tools/ctflab_storage_boundary.py',
    'tools/ctflab_guest_policy.py','tools/ctflab_guest_channel.py',
    'tools/ctflab_oci.py','tools/ctflab_guest_routes.py',
    'tools/tests/test_ctflab_windows_exit_observer.py',
    'tools/tests/test_ctflab_windows_native.py','tools/tests/test_ctflab_qemu_driver.py','tools/tests/test_ctflab_vmgenid.py',
    'tools/tests/test_ctflab_generation_store.py','tools/tests/test_ctflab_scenario_v2.py',
    'tools/ctflab_windows_recovery.py','tools/ctflab_windows_recovery_kit.py',
    'tools/ctflab_windows_control_kit.py','tools/ctflab_generation_store.py','tools/ctflab_vmgenid.py',
    'tools/ctflab_local_service.py','tools/ctflab_contract.py','tools/ctflab_scenario_v2.py',
    'tools/tests/test_ctflab_windows_recovery.py',
    'docs/ctflab-windows-test-steps-2026-10-24.md',
    'docs/ctflab-windows-recovery-2026-10-23.md',
    'docs/ctflab-production-driver-2026-10-24.md',
    'docs/verification-production-driver-2026-10-24.md',
)

def build(source,destination):
    source=Path(source);destination=Path(destination)
    data={n:(source/n).read_bytes() for n in FILES}
    data['README.md']=data['docs/ctflab-windows-test-steps-2026-10-24.md']
    data['MANIFEST.json']=json.dumps({'schema':1,'kind':'windows-recovery-candidate',
        'g0_passed':False,'files':{n:hashlib.sha256(v).hexdigest() for n,v in sorted(data.items())}},sort_keys=True,indent=2).encode()
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,raw in sorted(data.items()):
            info=zipfile.ZipInfo(name,(2026,10,23,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644<<16;archive.writestr(info,raw)
    return hashlib.sha256(destination.read_bytes()).hexdigest()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('destination',type=Path)
    args=parser.parse_args();print(build(Path(__file__).resolve().parents[1],args.destination))
