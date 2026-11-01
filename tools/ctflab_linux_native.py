"""Linux x64 普通用户进程身份、KVM只读能力门禁和独立 pidfd 退出观测。"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import platform
import select
import stat

from ctflab_windows_native import ProcessIdentity,compare_identity,NativeError


def parse_stat(raw):
    # comm 可包含空格及右括号；最后一个右括号之后才是固定字段。
    head,separator,tail=raw.rpartition(')')
    if not separator or '(' not in head:raise NativeError('identity-unknown')
    fields=tail.split()
    if len(fields)<20 or fields[0] not in ('R','S','D','Z','T','t','X','I','W','P'):raise NativeError('identity-unknown')
    ticks=int(fields[19])
    if ticks<0:raise NativeError('identity-unknown')
    return fields[0],ticks


def observe(pid):
    if platform.system()!='Linux' or type(pid) is not int or pid<=0:raise NativeError('unsupported-platform')
    if os.geteuid()==0 or os.geteuid()!=os.getuid():raise NativeError('permission-denied')
    root=Path('/proc')/str(pid)
    try:
        if root.stat().st_uid!=os.geteuid():raise NativeError('permission-denied')
        first=parse_stat((root/'stat').read_text())
        image=os.readlink(root/'exe')
        second=parse_stat((root/'stat').read_text())
        if first[1]!=second[1] or not image.startswith('/') or image.endswith(' (deleted)'):
            raise NativeError('identity-unknown')
        boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        creation=(int.from_bytes(hashlib.sha256(boot.encode()).digest()[:16],'big')<<64)|second[1]
        return ProcessIdentity(pid,creation,image,'exited' if second[0] in ('Z','X') else 'running')
    except (OSError,ValueError,IndexError):raise NativeError('identity-unknown') from None


def capability():
    if platform.system()!='Linux' or platform.machine().lower() not in ('x86_64','amd64'):
        return {'status':'unsupported-platform','hypervisor_present':False}
    if os.geteuid()==0 or os.geteuid()!=os.getuid() or not hasattr(os,'pidfd_open'):
        return {'status':'permission-or-pidfd-unavailable','hypervisor_present':False}
    try:
        import fcntl
        info=Path('/dev/kvm').stat()
        if not stat.S_ISCHR(info.st_mode):raise OSError('not kvm device')
        fd=os.open('/dev/kvm',os.O_RDWR|os.O_CLOEXEC)
        try:available=fcntl.ioctl(fd,0xAE00,0)==12 # KVM_GET_API_VERSION，不创建VM。
        finally:os.close(fd)
        return {'status':'available' if available else 'api-mismatch','hypervisor_present':available}
    except OSError:return {'status':'kvm-unavailable','hypervisor_present':False}


class LinuxObserver:
    observe=staticmethod(observe)

    @contextmanager
    def retained(self,expected):
        if not hasattr(os,'pidfd_open'):raise NativeError('pidfd-unavailable')
        fd=os.pidfd_open(expected.pid,0)
        try:
            if compare_identity(expected,observe(expected.pid))!='running':raise NativeError('identity-mismatch')
            yield fd
        finally:os.close(fd)

    def wait_exit(self,fd,timeout_ms=1000):
        if type(timeout_ms) is not int or not 0<=timeout_ms<=60000:raise NativeError('invalid-timeout')
        poll=select.poll();poll.register(fd,select.POLLIN)
        events=poll.poll(timeout_ms)
        if not events:return None
        if any(flags & select.POLLNVAL for _,flags in events):raise NativeError('identity-unknown')
        if not any(flags & select.POLLIN for _,flags in events):raise NativeError('wait-failed')
        # 独立观察者不是父进程，pidfd只证明退出，不伪造不可取得的退出码。
        return {'state':'exited','returncode':None,'source':'retained-linux-pidfd','exit_code_known':False}
