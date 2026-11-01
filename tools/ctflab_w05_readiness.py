#!/usr/bin/env python3
"""W05离线可核对项：安装配置、PE签名缺失、随包载荷与卸载保留证据。

只做本机可重复的静态核对，不制作安装包、不签名、不连接实机。
WebView2供应、干净机安装/卸载、升级迁移回退与Authenticode等仍属最终包/实机门槛，
报告按项如实标注 verified / missing-evidence / open，不把本地核对冒充平台验收。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctflab_contract import require

MAX_JSON_BYTES = 8 * 1024 * 1024


def read_json(path, limit=MAX_JSON_BYTES):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'JSON超出大小限制')
    return json.loads(raw.decode('utf-8'))


def digest(path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while True:
            chunk = stream.read(1 << 20)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def check_bundle_config(tauri_conf: dict, overlay_conf: dict | None = None) -> dict:
    """安装布局配置门：NSIS/currentUser/WebView2离线供应/CSP按当前源配置核对。"""
    require(type(tauri_conf) is dict, 'Tauri配置必须是JSON对象')
    bundle = dict(tauri_conf.get('bundle') or {})
    if type(overlay_conf) is dict:
        bundle.update(overlay_conf.get('bundle') or {})
    windows = bundle.get('windows') or {}
    nsis = windows.get('nsis') or {}
    webview = windows.get('webviewInstallMode') or {}
    app = tauri_conf.get('app') or {}
    checks = {
        'bundle_active_for_installer': bundle.get('active') is True,
        'nsis_target_declared': 'nsis' in (bundle.get('targets') or []),
        'nsis_current_user_scope': nsis.get('installMode') == 'currentUser',
        'webview2_offline_installer_mode': webview.get('type') == 'offlineInstaller' and webview.get('silent') is True,
        'main_window_single_and_titled': [w.get('label') for w in (app.get('windows') or [])] == ['main'],
        'csp_locks_down_content': "default-src 'self'" in str((app.get('security') or {}).get('csp') or ''),
        'identifier_fixed': tauri_conf.get('identifier') == 'org.ctflab.desktop',
    }
    return {'schema': 1, 'kind': 'w05-bundle-config-checks', 'checks': checks,
            'ok': all(checks.values()),
            'note': '配置核对只证明声明；实际安装布局须在最终包/干净机复验。'}


def pe_certificate_directory(data: bytes) -> tuple[int, int]:
    """读取PE可选头数据目录第4项（证书表）；返回(偏移,大小)。"""
    require(data[:2] == b'MZ', '非PE文件')
    e_lfanew = int.from_bytes(data[0x3C:0x40], 'little')
    require(data[e_lfanew:e_lfanew + 4] == b'PE\0\0', 'PE签名缺失')
    optional = e_lfanew + 24
    magic = int.from_bytes(data[optional:optional + 2], 'little')
    require(magic in (0x10B, 0x20B), '未知PE可选头')
    directory = optional + (96 if magic == 0x10B else 112)
    entry = directory + 4 * 8  # 第4项（每项8字节）：证书表
    require(len(data) >= entry + 8, 'PE数据目录被截断')
    return int.from_bytes(data[entry:entry + 4], 'little'), int.from_bytes(data[entry + 4:entry + 8], 'little')


def signature_status(installer: Path) -> dict:
    """Authenticode签名状态：证书表为空即未签名（未签名只限封闭试点）。"""
    with Path(installer).open('rb') as stream:
        head = stream.read(4 * 1024 * 1024)
    offset, size = pe_certificate_directory(head)
    return {'schema': 1, 'kind': 'w05-signature-status', 'installer': Path(installer).name,
            'sha256': digest(installer), 'signed': size > 0,
            'release_signing_required_for_public_g1': size == 0,
            'note': '未签名候选仅限封闭试点；公开发布前须完成Authenticode签名与信任链核对（需用户授权与证书）。'}


def payload_report(payload_dir: Path) -> dict:
    """随包运行时载荷：清单与实际文件逐项摘要一致；静态导入报告在位。"""
    import ctflab_desktop_package as package
    root = Path(payload_dir).resolve()
    manifest = read_json(root / 'bundle-manifest.json')
    require(manifest.get('kind') == 'windows-desktop-staging', '载荷清单类型不符')
    runtime = root / 'runtime'
    current = {item['name']: item['sha256'] for item in package.component(runtime)['files']}
    checks = {'payload_files_match_manifest': current == manifest['files'],
              'python_runtime_present': 'python/python.exe' in current,
              'qemu_runtime_present': 'qemu/qemu-system-x86_64.exe' in current,
              'static_imports_report_present': 'static-imports.json' in current,
              'dependency_closure_declared': manifest.get('dependency_closure_verified') is True,
              'signature_verified_declared': manifest.get('signature_verified') is True}
    return {'schema': 1, 'kind': 'w05-payload-checks', 'files': len(current), 'checks': checks,
            'ok': checks['payload_files_match_manifest'] and checks['python_runtime_present']
                  and checks['qemu_runtime_present'] and checks['static_imports_report_present'],
            'note': '清单只绑定随包载荷；PE导入核验以static-imports.json与CI记录为准。'}


def uninstall_evidence(results: dict) -> dict:
    """卸载保留证据：程序移除且应用数据哨兵保留（Server2025自动检查记录）。"""
    require(type(results) is dict and results.get('os'), '安装结果记录无效')
    checks = {'uninstall_program_removed': results.get('uninstall_program_removed') is True,
              'application_data_preserved': results.get('application_data_sentinels_preserved') is True,
              'visible_native_window_observed': results.get('visible_native_window_observed') is True,
              'manual_ui_verified': results.get('manual_ui_verified') is True,
              'windows_11_verified': results.get('windows_11_verified') is True,
              'upgrade_migration_verified': False,
              'authenticode_signed': results.get('authenticode_release_signed') is True}
    return {'schema': 1, 'kind': 'w05-platform-evidence-checks', 'os': results['os'], 'checks': checks,
            'ok': checks['uninstall_program_removed'] and checks['application_data_preserved'],
            'note': '自动检查不替代干净Windows11人工验收、升级迁移回退与签名发布。'}


def readiness_report(*, config, signature=None, payload=None, platform=None) -> dict:
    items = []
    config_ok = bool(config['ok'])
    items.append({'item': '安装布局配置（NSIS/currentUser/CSP）', 'status': 'verified' if config_ok else 'missing-evidence',
                  'evidence': 'desktop/src-tauri/tauri.conf.json + 本项checks'})
    items.append({'item': 'WebView2离线供应', 'status': 'missing-evidence',
                  'evidence': '配置声明offlineInstaller；静态解包未列出WebView2安装器，须在无WebView2干净机安装验证'})
    items.append({'item': 'Authenticode签名信任', 'status': ('verified-unsigned-candidate-only' if signature and not signature['signed'] else 'missing-evidence'),
                  'evidence': f"证书表为空={signature['signed'] is False}" if signature else '未提供安装器',
                  'open': '公开发布前须签名；属用户授权与证书决策'})
    items.append({'item': '随包运行时依赖', 'status': 'verified' if payload and payload['ok'] else 'missing-evidence',
                  'evidence': 'bundle-manifest.json逐文件摘要 + static-imports.json'})
    items.append({'item': '卸载保留配置', 'status': 'verified' if platform and platform['ok'] else 'missing-evidence',
                  'evidence': 'Server2025自动安装/卸载记录（历史结果，不替代本轮干净机复验）'})
    for name, status in (('干净Windows11人工/桌面验收', platform and platform['checks']['windows_11_verified']),
                         ('升级/迁移失败回退', False),
                         ('最终包复验', None)):
        items.append({'item': name, 'status': 'verified' if status is True else 'open',
                      'evidence': '需授权实机环境' if status is not True else ''})
    return {'schema': 1, 'kind': 'w05-offline-readiness', 'items': items,
            'offline_all_verified': all(i['status'] == 'verified' for i in items),
            'note': 'missing-evidence/open项在最终包与干净机验收前不关闭，不把本报告当作W05完成。'}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tauri-config', type=Path, default=Path('desktop/src-tauri/tauri.conf.json'))
    parser.add_argument('--bundle-overlay', type=Path, default=None, help='CI用tauri.bundle.json覆盖配置')
    parser.add_argument('--installer', type=Path, default=None, help='候选安装器EXE（核对签名与摘要）')
    parser.add_argument('--payload', type=Path, default=None, help='静态解包的载荷目录（含bundle-manifest.json）')
    parser.add_argument('--platform-results', type=Path, default=None, help='实机安装/卸载结果JSON')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        config = check_bundle_config(read_json(args.tauri_config),
                                     read_json(args.bundle_overlay) if args.bundle_overlay else None)
        signature = signature_status(args.installer) if args.installer else None
        payload = payload_report(args.payload) if args.payload else None
        platform = uninstall_evidence(read_json(args.platform_results)) if args.platform_results else None
        report = readiness_report(config=config, signature=signature, payload=payload, platform=platform)
        if signature is not None:
            report['installer_sha256'] = signature['sha256']
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'ok': True, 'output': str(args.output)}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f'核对未完成：{error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
