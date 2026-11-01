"""可复现的离线工具源码包；只收录固定白名单，不扫描工作区或用户材料。"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

FILES = (
    'tools/ctflab_offline.py', 'tools/ctflab_topology.py', 'tools/ctflab_evidence_course.py', 'tools/ctflab_evidence_workspace.py','tools/ctflab_evidence_samples.py',
    'tools/tests/test_ctflab_evidence_workspace.py','docs/ctflab-evidence-workflow-2026-10-30.md',
    'tools/tests/test_ctflab_evidence_samples.py',
    'tools/ctflab_windows_evidence.py', 'tools/ctflab_scenario_v2.py', 'tools/ctflab_catalog.py',
    'tools/ctflab_generation_store.py','tools/ctflab_vmgenid.py', 'tools/ctflab_scenario_coordinator.py',
    'tools/ctflab_contract.py', 'tools/ctflab_local_service.py', 'tools/ctflab_storage_boundary.py', 'tools/ctflab_tls_endpoint.py',
    'tools/ctflab_windows_native.py', 'tools/ctflab_windows_security.py',
    'tools/tests/test_ctflab_generation_store.py', 'tools/tests/test_ctflab_roadmap_offline.py',
    'tools/tests/test_ctflab_scenario_v2.py',
    'docs/ctflab-offline-delivery-2026-10-23.md', 'docs/ctflab-community-workflow-2026-10-23.md',
    'docs/verification-offline-foundation-2026-10-23.md',
)


def build(source, destination):
    data = {name: (Path(source) / name).read_bytes() for name in FILES}
    data['README.md'] = (data['docs/ctflab-offline-delivery-2026-10-23.md']
                         .replace(b'](ctflab-', b'](docs/ctflab-')
                         .replace(b'](verification-', b'](docs/verification-'))
    manifest = {'schema': 1, 'kind': 'offline-foundation-source-only', 'g0_passed': False, 'g1_passed': False,
                'files': {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(data.items())}}
    data['MANIFEST.json'] = json.dumps(manifest, sort_keys=True, indent=2).encode()
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in sorted(data.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 23, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)
    return hashlib.sha256(Path(destination).read_bytes()).hexdigest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(build(Path(__file__).resolve().parents[1], args.destination))
