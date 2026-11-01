"""仅供用户运行的固定 Smoke 冷启动实验；没有通用运行器或自动验收声明。"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

QEMU = Path(r'C:\Program Files\qemu\qemu-system-x86_64.exe')
BASE = Path(r'C:\CTFLab-Test\Smoke-OVA\smoke-ova-base.qcow2')
QEMU_SHA = '47d57a6072e0bb3bd98f87926eb129eb1736dfe818c67b3b81ef7ce4edd0b3cd'
BASE_SHA = 'f9c2edc334c9e2839c1d605d6d870e8f68ad1242f892fe3f96ed75bfaf554052'


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def verified(path, expected):
    from ctflab_windows_security import guard_path, validate_local_path
    validate_local_path(str(path))
    guard_path(path)
    if not path.is_file() or path.stat().st_nlink != 1 or digest(path) != expected:
        raise ValueError('文件缺失、存在链接或哈希不符；未启动')


def copy_disk(source, target):
    # 独占创建；即使复制中断也保留部分副本，不覆盖用户文件。
    with source.open('rb') as src, target.open('xb') as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)
        dst.flush()
        os.fsync(dst.fileno())
    if digest(target) != BASE_SHA:
        raise ValueError('独立磁盘复制校验失败；未启动，现场保留')


def command(binary, disk):
    return [str(binary), '-no-user-config', '-nodefaults', '-name', 'CTFLab-Smoke-WHPX-test',
            '-machine', 'pc', '-accel', 'whpx', '-m', '1024', '-smp', '1',
            '-drive', 'file=' + str(disk).replace(',', ',,') + ',format=qcow2,if=ide',
            '-nic', 'none', '-display', 'sdl', '-vga', 'std',
            '-monitor', 'stdio', '-serial', 'none', '-parallel', 'none']


def main(argv=None):
    parser = argparse.ArgumentParser(description='固定 Smoke WHPX/SDL 无网络独立磁盘测试')
    parser.add_argument('--start', action='store_true', help='显式启动本轮测试；默认仅说明')
    args = parser.parse_args(argv)
    if not args.start:
        print('使用 --start 启动固定 Smoke 测试；独立副本、无网络、保留日志，不自动判定通过。')
        return 0
    if os.name != 'nt':
        print('此入口仅供 Windows 实机使用。')
        return 1
    from ctflab_windows_security import WindowsSecurity
    from ctflab_windows_native import NativeError, Win32, hypervisor_capability
    run = None
    proc = None
    try:
        security = WindowsSecurity()
        security.current_user()  # 普通用户；拒绝提权和线程模拟。
        verified(QEMU, QEMU_SHA)
        verified(BASE, BASE_SHA)
        if hypervisor_capability().get('hypervisor_present') is not True:
            raise ValueError('虚拟化平台未报告可用；未启动，不回退 TCG')
        run = BASE.parent / ('w01-run-' + uuid.uuid4().hex)
        security.create_directory(run)
        disk = run / 'test-disk.qcow2'
        copy_disk(BASE, disk)
        security.verify(disk)
        verified(QEMU, QEMU_SHA)
        verified(BASE, BASE_SHA)
        report = {'scope': 'manual-whpx-sdl-offline-smoke', 'g0_passed': False,
                  'guest_verified': False, 'graceful_stop_verified': False,
                  'qemu_sha256': QEMU_SHA, 'source_sha256': BASE_SHA, 'network': 'none',
                  'state': 'prepared', 'pid': None}
        report_path = run / 'result.json'
        def save():
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        save()
        print('测试目录：', run, flush=True)
        print('请记录 SDL 中的登录画面。结束时回到本终端，在 (qemu) 后输入 system_powerdown。', flush=True)
        print('若等待60秒仍未退出，先记录画面；只有确定要强制结束本次副本时输入 quit。', flush=True)
        print('退出码0不证明正常关机；不要输入 commit。不要关闭此终端。', flush=True)
        with (run / 'qemu-stderr.log').open('xb') as log:
            # 固定二进制/参数；控制台直连本次子进程，无TCP控制或显示监听。
            proc = subprocess.Popen(command(QEMU, disk), stdin=None, stdout=None, stderr=log,
                                    cwd=str(QEMU.parent), shell=False,
                                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            report.update(state='process-created', pid=proc.pid)
            print('本轮子进程 PID：', proc.pid, flush=True)
            try:
                report['process_identity'] = asdict(Win32().observe(proc.pid))
            except NativeError:
                report['process_identity'] = 'unknown'
            save()
            while True:
                try:
                    code = proc.wait()
                    break
                except KeyboardInterrupt:
                    print('测试仍由本终端管理；请使用 system_powerdown，必要时明确输入 quit。', flush=True)
        report.update(state='exited', returncode=code, source_unchanged=digest(BASE) == BASE_SHA)
        save()
        print('进程已退出，结果与日志保留在：', run)
        print('原始基盘未改变：', report['source_unchanged'])
        return 0 if code == 0 and report['source_unchanged'] else 1
    except (OSError, ValueError, NativeError) as exc:
        print('测试失败，保留现场：', run or '尚未建立测试目录')
        print(type(exc).__name__, str(exc))
        if proc is not None and proc.poll() is None:
            print('本次子进程仍在运行，PID：', proc.pid, '；不要重复启动，先保留现场。')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
