"""Darwin只读进程身份及kqueue退出观测；不申请终止或调试权限。"""
from contextlib import contextmanager
import ctypes
from functools import lru_cache
import hashlib
import os
import platform
import select
import subprocess
import sys
import uuid
from ctflab_windows_native import NativeError, ProcessIdentity, compare_identity


class BSDInfo(ctypes.Structure):
    # 当前SDK sys/proc_info.h的proc_bsdinfo；固定宽度而非宿主long。
    _fields_ = [(name, ctypes.c_uint32) for name in
                ('flags','status','xstatus','pid','ppid','uid','gid','ruid','rgid','svuid','svgid','rfu')]+[
        ('comm',ctypes.c_char*16),('name',ctypes.c_char*32),('nfiles',ctypes.c_uint32),
        ('pgid',ctypes.c_uint32),('pjobc',ctypes.c_uint32),('tdev',ctypes.c_uint32),
        ('tpgid',ctypes.c_uint32),('nice',ctypes.c_int32),('start_sec',ctypes.c_uint64),('start_usec',ctypes.c_uint64)]


def permission():
    if sys.platform!='darwin' or os.geteuid()==0 or os.getuid()!=os.geteuid():
        raise NativeError('unsupported-platform-or-permission')


@lru_cache(maxsize=1)
def boot_identity():
    permission()
    try:
        value=subprocess.run(['/usr/sbin/sysctl','-n','kern.bootsessionuuid'],stdin=subprocess.DEVNULL,
            capture_output=True,timeout=5,check=True).stdout.decode().strip().lower()
    except (OSError,subprocess.SubprocessError):raise NativeError('identity-unknown') from None
    return uuid.UUID(value).bytes


def observe(pid):
    permission()
    if type(pid) is not int or not 0<pid<2**31:raise NativeError('invalid-pid')
    lib=ctypes.CDLL('/usr/lib/libproc.dylib',use_errno=True)
    info=lib.proc_pidinfo;info.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_uint64,ctypes.c_void_p,ctypes.c_int];info.restype=ctypes.c_int
    path=lib.proc_pidpath;path.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32];path.restype=ctypes.c_int
    def sample():
        value=BSDInfo()
        if ctypes.sizeof(value)!=136 or info(pid,3,0,ctypes.byref(value),ctypes.sizeof(value))!=ctypes.sizeof(value):
            raise NativeError('identity-unknown')
        if value.pid!=pid or value.uid!=os.geteuid() or value.ruid!=os.getuid() or value.start_usec>=1000000:
            raise NativeError('identity-unknown')
        return value
    first=sample();buffer=ctypes.create_string_buffer(4096)
    if not 0<path(pid,buffer,len(buffer))<len(buffer):raise NativeError('identity-unknown')
    image=buffer.value.decode('utf-8');second=sample()
    if (first.start_sec,first.start_usec)!=(second.start_sec,second.start_usec) or not image.startswith('/'):
        raise NativeError('identity-unknown')
    start=second.start_sec*1000000+second.start_usec
    ticks=(int.from_bytes(hashlib.sha256(boot_identity()).digest()[:16],'big')<<64)|start
    return ProcessIdentity(pid,ticks,image,'exited' if second.status==5 else 'running')


def capability():
    if sys.platform!='darwin' or platform.machine().lower() not in ('arm64','aarch64'):
        return {'hypervisor_present':False,'status':'unsupported-platform'}
    try:
        permission()
        reply=subprocess.run(['/usr/sbin/sysctl','-n','kern.hv_support'],stdin=subprocess.DEVNULL,capture_output=True,timeout=5,check=True)
        present=reply.stdout.strip()==b'1' and hasattr(select,'kqueue')
        return {'hypervisor_present':present,'status':'available' if present else 'unavailable',
                'runtime_verified':False}
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError):
        return {'hypervisor_present':False,'status':'unavailable'}


class DarwinObserver:
    observe=staticmethod(observe)

    @contextmanager
    def retained(self,expected):
        permission()
        if not hasattr(select,'kqueue'):raise NativeError('kqueue-unavailable')
        def matches():
            current=observe(expected.pid)
            return expected.image_path==current.image_path and compare_identity(expected,current)=='running'
        if not matches():raise NativeError('identity-mismatch')
        queue=select.kqueue()
        try:
            event=select.kevent(expected.pid,filter=select.KQ_FILTER_PROC,
                flags=select.KQ_EV_ADD|select.KQ_EV_ENABLE|select.KQ_EV_ONESHOT,fflags=select.KQ_NOTE_EXIT)
            queue.control([event],0,0)
            if not matches():raise NativeError('identity-mismatch')
            yield (queue,expected.pid)
        finally:queue.close()

    def wait_exit(self,handle,timeout_ms=1000):
        if type(timeout_ms) is not int or not 0<=timeout_ms<=60000:raise NativeError('invalid-timeout')
        queue,pid=handle;events=queue.control(None,1,timeout_ms/1000)
        if not events:return None
        event=events[0]
        if event.ident!=pid or event.filter!=select.KQ_FILTER_PROC or event.flags&select.KQ_EV_ERROR or not event.fflags&select.KQ_NOTE_EXIT:
            raise NativeError('identity-unknown')
        return {'state':'exited','returncode':None,'source':'retained-darwin-kqueue','exit_code_known':False}
