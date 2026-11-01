"""跨阶段集成源码交付；显式白名单，排除运行时、镜像、密钥和运行现场。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_windows_recovery_kit import FILES as RECOVERY_FILES
from ctflab_offline_kit import FILES as OFFLINE_FILES
from ctflab_package import RELEASE_TOOL_FILES as MAC_TOOL_FILES

FILES=tuple(sorted(set(RECOVERY_FILES)|set(OFFLINE_FILES)|set(MAC_TOOL_FILES)|{
    'docs/ctflab-platform-ownership-2026-10-30-r2.json',
    'tools/tests/test_ctflab_contract_parity.py','docs/ctflab-contract-parity-2026-10-30.md',
    'desktop/src/PreparationProgress.jsx','tools/tests/test_ctflab_preparation_progress.py','docs/ctflab-preparation-progress-2026-10-30.md',
    'desktop/src/OperationHistory.jsx','tools/tests/test_ctflab_operation_history.py',
    'docs/ctflab-contract-reopen-2026-10-30.md',
    'docs/ctflab-platform-ownership-2026-10-30.md','docs/ctflab-platform-ownership-2026-10-30.json',
    'tools/tests/check_ctflab_platform_ownership.py',
    'tools/tests/test_ctflab_mac_argv_equivalence.py','tools/tests/test_ctflab_platform.py',
    'tools/tests/fixtures/mac-argv-0994f62.json','docs/ctflab-mac-argv-equivalence-2026-10-30.md',
    'docs/ctflab-mac-transport-2026-10-29.md',
    'docs/ctflab-desktop-transport-2026-10-29.md',
    'docs/ctflab-analysis-reproducibility-2026-10-29.md',
    'tools/ctflab_ir_course.py','tools/ctflab_windows_course_events.py','tools/tests/test_ctflab_ir_course.py','tools/tests/test_ctflab_windows_course_events.py','docs/ctflab-ir-course-2026-10-29.md',
    'tools/ctflab_waf_course.py','tools/tests/test_ctflab_waf_course.py','docs/ctflab-waf-course-2026-10-29.md',
    'tools/ctflab_server_storage.py','tools/tests/test_ctflab_server_storage.py','docs/ctflab-server-storage-2026-10-29.md',
    'tools/ctflab_cache_gc.py','tools/tests/test_ctflab_cache_gc.py','docs/ctflab-cache-gc-2026-10-29.md',
    'tools/ctflab_windows_ip.py','tools/ctflab_windows_firewall.py','tools/tests/test_ctflab_windows_ip.py','docs/ctflab-windows-ip-2026-10-29.md',
    'tools/ctflab_recoverable_log.py','tools/tests/test_ctflab_recoverable_log.py','docs/ctflab-recoverable-log-2026-10-29.md',
    'docs/ctflab-cache-watch-ip-2026-10-29.md','docs/ctflab-coherent-observation-2026-10-29.md','tools/tests/test_ctflab_local_contract.py','tools/tests/test_ctflab_stability_topology.py','docs/ctflab-stability-topology-2026-10-28.md',
    'docs/ctflab-continuation-2026-10-28.md','docs/ctflab-recovery-dependencies-2026-10-28.md',
    'tools/ctflab_windows_storage.py','tools/tests/test_ctflab_windows_storage.py',
    'tools/ctflab_pe_dependencies.py','tools/tests/test_ctflab_pe_dependencies.py',
    'tools/ctflab_storage_bind.py','tools/tests/test_ctflab_storage_bind.py','docs/ctflab-windows-volume-2026-10-27.md',
    'tools/ctflab_release_online.py','tools/tests/test_ctflab_release_online.py',
    'tools/ctflab_windows_limits.py','tools/tests/test_ctflab_windows_limits.py',
    'tools/ctflab_watch.py','tools/tests/test_ctflab_watch.py','tools/ctflab_manage.py','tools/tests/test_ctflab_manage.py',
    'docs/ctflab-consolidated-2026-10-27.md',
    'tools/ctflab_external_ip.py','tools/tests/test_ctflab_external_ip.py','docs/ctflab-external-ip-2026-10-27.md',
    'tools/ctflab_profiles/basic-pentesting-2.yaml','tools/ctflab_profiles/smoke.yaml',
    'tools/ctflab_profiles/kali-arm64.yaml','tools/ctflab_profiles/acfun.yaml','tools/ctflab_profiles/webserver.yaml',
    'tools/ctflab_bounded_log.py','tools/ctflab_release_update.py','tools/ctflab_remote.py','tools/ctflab_evidence_export.py',
    'tools/ctflab_remote_assets.py','tools/ctflab_remote_course.py','tools/ctflab_remote_display.py','tools/ctflab_external.py','tools/ctflab_external_events.py','tools/ctflab_remote_evidence.py','tools/ctflab_client_evidence.py','tools/tests/test_ctflab_remote_assets.py','tools/tests/test_ctflab_remote_course.py','tools/tests/test_ctflab_remote_display.py','tools/tests/test_ctflab_external.py','tools/tests/test_ctflab_external_events.py','docs/ctflab-external-events-2026-10-29.md','tools/tests/test_ctflab_remote_evidence.py',
    'tools/ctflab_lease_store.py','tools/ctflab_remote_leases.py','tools/ctflab_lease_scheduler.py','tools/tests/test_ctflab_remote_leases.py','tools/tests/test_ctflab_lease_scheduler.py',
    'tools/ctflab_remote_audit.py','tools/tests/test_ctflab_remote_audit.py',
    'tools/tests/test_ctflab_worker_audit.py',
    'tools/ctflab_audit_review.py','tools/ctflab_audit_archive.py','tools/ctflab_audit_rotation.py','tools/tests/test_ctflab_audit_archive.py','tools/tests/test_ctflab_audit_rotation.py','tools/tests/test_ctflab_audit_review.py',
    'tools/ctflab_desktop_remote.py','tools/tests/test_ctflab_desktop_remote.py',
    'tools/tests/test_ctflab_desktop_leases.py',
    'tools/ctflab_client_store.py','tools/ctflab_client_assets.py',
    'tools/tests/test_ctflab_client_store.py','tools/tests/test_ctflab_client_assets.py',
    'tools/ctflab_oci.py','tools/tests/test_ctflab_oci.py',
    'tools/ctflab_guest_routes.py','tools/ctflab_guest_routed.py','tools/ctflab_guest_analysis.py','tools/tests/test_ctflab_guest_routes.py','tools/tests/test_ctflab_guest_routed.py','tools/tests/test_ctflab_guest_analysis.py',
    'tools/ctflab_policy_review.py','tools/tests/test_ctflab_policy_review.py',
    'tools/tests/test_ctflab_bounded_log.py','tools/tests/test_ctflab_release_update.py',
    'tools/ctflab_release_launcher.py','tools/ctflab_version_bridge.py','tools/ctflab_version_setup.py','tools/ctflab_cgroup.py','tools/ctflab_macos_storage.py','tools/ctflab.py','tools/ctflab_inspect.py','tools/ctflab_utm.py','tools/tests/test_ctflab_macos_storage.py','tools/tests/test_ctflab_mac_remote.py','docs/ctflab-mac-diagnostics-2026-10-29.md','docs/ctflab-vmgenid-2026-10-29.md','docs/ctflab-completion-audit-2026-10-29.md','gui/GuiCore.swift','gui/GuiApp.swift','gui/GuiCoreTests.swift','tools/tests/test_ctflab_storage_boundary.py','tools/tests/test_ctflab_release_launcher.py','tools/tests/test_ctflab_version_bridge.py','tools/tests/test_ctflab_version_setup.py','desktop/src/VersionSetup.jsx','docs/ctflab-version-setup-2026-10-30.md','tools/tests/test_ctflab_cgroup.py',
    'tools/tests/test_ctflab_remote.py','tools/tests/test_ctflab_evidence_export.py',
    'tools/tests/test_ctflab_scenario.py','docs/ctflab-wintermute-scenario-design.md',
    'tools/tests/test_ctflab_darwin_native.py','tools/tests/test_ctflab_darwin_driver.py',
    'tools/ctflab_integrated_kit.py','tools/ctflab_offline_kit.py','tools/ctflab_runtime_inventory.py',
    'tools/ctflab_network.py','tools/ctflab_local_adapter.py','tools/ctflab_desktop_bridge.py',
    'tools/ctflab_external_attach.py','tools/ctflab_external_l2.py','tools/ctflab_kali_attach.py',
    'tools/tests/test_ctflab_external_attach.py','tools/tests/test_ctflab_external_l2.py','tools/tests/test_ctflab_kali_attach.py','tools/tests/test_ctflab_kali_attach_functions.py',
    'tools/tests/test_ctflab_desktop_external_attach.py','tools/tests/test_ctflab_external_attach_acceptance.py',
    'desktop/src/external-attach-model.mjs','desktop/src/ExternalAttach.jsx',
    'desktop/src/external-attach-model.test.mjs','docs/ctflab-external-kali-l2-design-2026-10-30.md','docs/ctflab-remaining-work-matrix-2026-10-30.md',
    'tools/ctflab_desktop_package.py','tools/ctflab_content_cache.py','tools/ctflab_release_store.py',
    'tools/ctflab_delivery.py','tools/ctflab_acceptance_session.py','tools/ctflab_linux_native.py',
    'tools/ctflab_diagnostics_public.py','tools/tests/test_ctflab_desktop_bridge.py',
    'tools/ctflab_guest_policy.py','tools/ctflab_guest_agent.py','tools/ctflab_guest_channel.py','tools/ctflab_guest_kit.py',
    'tools/ctflab_mirror.py','tools/ctflab_mirror_service.py','tools/tests/test_ctflab_guest_policy.py','tools/tests/test_ctflab_guest_agent.py',
    'tools/tests/test_ctflab_guest_channel.py','tools/tests/test_ctflab_guest_contract.py',
    'tools/tests/test_ctflab_guest_kit.py','tools/tests/test_ctflab_mirror.py','tools/tests/test_ctflab_mirror_service.py','docs/ctflab-mirror-service-2026-10-29.md',
    'tools/tests/test_ctflab_desktop_package.py','tools/tests/test_ctflab_content_cache.py',
    'tools/tests/test_ctflab_release_store.py','tools/tests/test_ctflab_acceptance_session.py',
    'tools/tests/test_ctflab_runtime_inventory.py','tools/tests/test_ctflab_linux_native.py',
    'tools/tests/test_ctflab_network.py','tools/tests/test_ctflab_catalog.py',
    'docs/ctflab-integrated-candidate-2026-10-25.md',
    'docs/ctflab-managed-guest-2026-10-25.md',
    'docs/ctflab-mac-generic-2026-10-27.md',
    'docs/ctflab-maintenance-remote-evidence-2026-10-25.md',
    'docs/ctflab-remote-assets-2026-10-25.md',
    'docs/ctflab-oci-routing-2026-10-25.md',
    'docs/ctflab-remote-leases-2026-10-25.md',
    'docs/ctflab-remote-audit-2026-10-25.md',
    'docs/ctflab-worker-audit-2026-10-25.md',
    'docs/ctflab-audit-review-2026-10-25.md',
    'docs/ctflab-desktop-remote-2026-10-25.md',
    'docs/ctflab-desktop-leases-2026-10-25.md',
    'docs/ctflab-continuous-development-2026-10-26.md',
    'docs/ctflab-version-launcher-2026-10-26.md','docs/ctflab-remaining-development-2026-10-26.md','docs/ctflab-storage-boundary-2026-10-26.md','docs/ctflab-mac-parity-2026-10-26.md','docs/ctflab-mac-remote-2026-10-26.md',
    'desktop/package.json','desktop/package-lock.json','desktop/index.html',
    'desktop/THIRD_PARTY_NOTICES.md',
    'desktop/Build-Windows.ps1','desktop/Test-Integration.ps1','desktop/src/main.jsx',
    'desktop/src/style.css','desktop/src/model.mjs','desktop/src/model.test.mjs',
    'desktop/src/RemoteWorkspace.jsx','desktop/src/remote-model.mjs','desktop/src/remote-model.test.mjs',
    'docs/ctflab-mac-topology-2026-10-27.md','docs/ctflab-course-administration-2026-10-27.md','desktop/src/RemoteAdministration.jsx','desktop/src/admin-model.mjs','desktop/src/admin-model.test.mjs',
    'desktop/src/RemoteTargets.jsx','desktop/src/RemoteAssets.jsx','desktop/src/RemoteEvidence.jsx','desktop/src/Versions.jsx','desktop/src/version-model.mjs','desktop/src/version-model.test.mjs',
    'desktop/src/GraphEditor.jsx','desktop/src/graph-model.mjs','desktop/src/graph-model.test.mjs',
    'desktop/src/GuestRecovery.jsx','tools/tests/test_ctflab_guest_recovery_integration.py',
    'desktop/src-tauri/Cargo.toml','desktop/src-tauri/Cargo.lock','desktop/src-tauri/build.rs',
    'desktop/src-tauri/rust-toolchain.toml','desktop/src-tauri/tauri.conf.json',
    'desktop/src-tauri/src/main.rs','desktop/src-tauri/src/transport.rs','desktop/src-tauri/capabilities/default.json',
    'desktop/src-tauri/icons/icon.png','desktop/src-tauri/icons/icon.ico',
}))


def build(source,destination,*,guide='docs/ctflab-integrated-candidate-2026-10-25.md'):
    if guide not in ('docs/ctflab-integrated-candidate-2026-10-25.md','docs/ctflab-managed-guest-2026-10-25.md',
                     'docs/ctflab-maintenance-remote-evidence-2026-10-25.md','docs/ctflab-remote-assets-2026-10-25.md',
                     'docs/ctflab-oci-routing-2026-10-25.md','docs/ctflab-remote-leases-2026-10-25.md',
                     'docs/ctflab-remote-audit-2026-10-25.md','docs/ctflab-worker-audit-2026-10-25.md',
                     'docs/ctflab-audit-review-2026-10-25.md','docs/ctflab-desktop-remote-2026-10-25.md',
                     'docs/ctflab-desktop-leases-2026-10-25.md','docs/ctflab-version-launcher-2026-10-26.md','docs/ctflab-remaining-development-2026-10-26.md','docs/ctflab-storage-boundary-2026-10-26.md','docs/ctflab-mac-parity-2026-10-26.md','docs/ctflab-mac-remote-2026-10-26.md'):
        raise ValueError('交付说明不在白名单')
    data={n:(Path(source)/n).read_bytes() for n in FILES}
    data['README.md']=data[guide]
    data['MANIFEST.json']=json.dumps({'schema':1,'kind':'integrated-source-candidate',
        'g0_passed':False,'g1_passed':False,'installer_included':False,'readme_source':guide,
        'files':{n:hashlib.sha256(v).hexdigest() for n,v in sorted(data.items())}},sort_keys=True,indent=2).encode()
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,raw in sorted(data.items()):
            info=zipfile.ZipInfo(name,(2026,10,25,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644<<16;archive.writestr(info,raw)
    return hashlib.sha256(Path(destination).read_bytes()).hexdigest()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('destination',type=Path)
    parser.add_argument('--guide',choices=('docs/ctflab-integrated-candidate-2026-10-25.md','docs/ctflab-managed-guest-2026-10-25.md',
                                        'docs/ctflab-maintenance-remote-evidence-2026-10-25.md','docs/ctflab-remote-assets-2026-10-25.md',
                                        'docs/ctflab-oci-routing-2026-10-25.md','docs/ctflab-remote-leases-2026-10-25.md',
                     'docs/ctflab-remote-audit-2026-10-25.md','docs/ctflab-worker-audit-2026-10-25.md',
                     'docs/ctflab-audit-review-2026-10-25.md','docs/ctflab-desktop-remote-2026-10-25.md',
                     'docs/ctflab-desktop-leases-2026-10-25.md','docs/ctflab-version-launcher-2026-10-26.md','docs/ctflab-remaining-development-2026-10-26.md','docs/ctflab-storage-boundary-2026-10-26.md','docs/ctflab-mac-parity-2026-10-26.md','docs/ctflab-mac-remote-2026-10-26.md'),default='docs/ctflab-integrated-candidate-2026-10-25.md')
    args=parser.parse_args();print(build(Path(__file__).resolve().parents[1],args.destination,guide=args.guide))
