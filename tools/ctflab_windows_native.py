"""Windows 原生文件锁和只读进程身份；不包含 VM 启停或强制终止。"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import os
from pathlib import Path
import stat


class NativeError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


# 显式固定 Win32 宽度，避免非 Windows 测试宿主的 c_ulong 宽度差异。
DWORD = ctypes.c_uint32
BOOL = ctypes.c_int32
HANDLE = ctypes.c_void_p


class FileTime(ctypes.Structure):
    _fields_ = [('low', DWORD), ('high', DWORD)]


class Overlapped(ctypes.Structure):
    _fields_ = [('internal', ctypes.c_size_t), ('internal_high', ctypes.c_size_t),
                ('offset', DWORD), ('offset_high', DWORD), ('event', HANDLE)]


class ProcessEntry32(ctypes.Structure):
    # WCHAR固定16位，非Windows ABI桩也不能沿用宿主c_wchar的宽度。
    _fields_ = [('size', DWORD), ('usage', DWORD), ('pid', DWORD),
                ('heap', ctypes.c_size_t), ('module', DWORD), ('threads', DWORD),
                ('parent_pid', DWORD), ('priority', ctypes.c_int32), ('flags', DWORD),
                ('exe', ctypes.c_uint16 * 260)]


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    creation_ticks: int
    image_path: str
    state: str


class Win32:
    def __init__(self):
        if os.name != 'nt':
            raise NativeError('unsupported-platform')
        self.dll = ctypes.WinDLL('kernel32', use_last_error=True)
        definitions = {
            'CreateToolhelp32Snapshot': ([DWORD, DWORD], HANDLE),
            'Process32FirstW': ([HANDLE, ctypes.POINTER(ProcessEntry32)], BOOL),
            'Process32NextW': ([HANDLE, ctypes.POINTER(ProcessEntry32)], BOOL),
            'GetLastError': ([], DWORD),
            'OpenProcess': ([DWORD, BOOL, DWORD], HANDLE),
            'CloseHandle': ([HANDLE], BOOL),
            'GetExitCodeProcess': ([HANDLE, ctypes.POINTER(DWORD)], BOOL),
            'GetProcessTimes': ([HANDLE]+[ctypes.POINTER(FileTime)]*4, BOOL),
            'QueryFullProcessImageNameW': ([HANDLE, DWORD, ctypes.c_wchar_p, ctypes.POINTER(DWORD)], BOOL),
            'WaitForSingleObject': ([HANDLE, DWORD], DWORD),
            'LockFileEx': ([HANDLE, DWORD, DWORD, DWORD, DWORD, ctypes.POINTER(Overlapped)], BOOL),
            'UnlockFileEx': ([HANDLE, DWORD, DWORD, DWORD, ctypes.POINTER(Overlapped)], BOOL),
        }
        for name, (args, result) in definitions.items():
            function = getattr(self.dll, name); function.argtypes = args; function.restype = result

    def pid_exists(self, pid):
        """只读快照仅比较PID；枚举失败不能解释为不存在，不输出其他进程资料。"""
        if type(pid) is not int or not 1 < pid <= 0xffffffff:
            raise NativeError('invalid-pid')
        handle = self.dll.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
        if handle in (None, 0, HANDLE(-1).value):
            raise NativeError('process-list-unknown')
        try:
            entry = ProcessEntry32()
            entry.size = ctypes.sizeof(entry)
            found = self.dll.Process32FirstW(handle, ctypes.byref(entry))
            while found:
                if entry.pid == pid:
                    return True
                found = self.dll.Process32NextW(handle, ctypes.byref(entry))
            if self.dll.GetLastError() != 18:  # ERROR_NO_MORE_FILES才是完整枚举结束。
                raise NativeError('process-list-unknown')
            return False
        finally:
            self.dll.CloseHandle(handle)

    def observe(self, pid):
        if type(pid) is not int or not 0 < pid <= 0xffffffff:
            raise NativeError('invalid-pid')
        # 只申请查询与等待权；不申请 PROCESS_TERMINATE。
        handle = self.dll.OpenProcess(0x1000 | 0x100000, False, pid)
        if not handle:
            # 权限失败/退出竞争均为未知，不能据此清理其他资源。
            raise NativeError('identity-unknown')
        try:
            return self.observe_handle(handle, pid)
        finally:
            self.dll.CloseHandle(handle)

    def observe_handle(self, handle, pid):
        times = [FileTime() for _ in range(4)]
        if not self.dll.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            raise NativeError('identity-unknown')
        buffer = ctypes.create_unicode_buffer(32768); length = DWORD(len(buffer))
        if not self.dll.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
            raise NativeError('identity-unknown')
        wait = self.dll.WaitForSingleObject(handle, 0)
        if wait not in (0, 258):
            raise NativeError('identity-unknown')
        return ProcessIdentity(pid, (times[0].high << 32) | times[0].low,
                               buffer.value, 'running' if wait == 258 else 'exited')

    @contextmanager
    def retained(self, expected):
        """核验后保留同一内核对象，只申请查询/等待权，避免 PID 重用。"""
        handle = self.dll.OpenProcess(0x1000 | 0x100000, False, expected.pid)
        if not handle:
            raise NativeError('identity-unknown')
        try:
            if compare_identity(expected, self.observe_handle(handle, expected.pid)) not in ('running', 'exited'):
                raise NativeError('identity-mismatch')
            yield handle
        finally:
            self.dll.CloseHandle(handle)

    def wait_exit(self, handle, timeout_ms=1000):
        if type(timeout_ms) is not int or not 0 <= timeout_ms <= 60000:
            raise NativeError('invalid-timeout')
        state = self.dll.WaitForSingleObject(handle, timeout_ms)
        if state == 258:
            return None
        if state != 0:
            raise NativeError('wait-failed')
        code = DWORD()
        if not self.dll.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise NativeError('exit-code-unknown')
        # 只有对象已 signaled 才读取；退出码 259 也可以是合法退出码。
        return code.value

    def lock(self, handle, overlapped):
        if not self.dll.LockFileEx(handle, 3, 0, 1, 0, ctypes.byref(overlapped)):
            raise NativeError('resource-busy' if ctypes.get_last_error() == 33 else 'lock-failed')

    def unlock(self, handle, overlapped):
        if not self.dll.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped)):
            raise NativeError('unlock-failed')


def compare_identity(expected, observed):
    """只证明内核身份字段一致；端点/磁盘/实例归属仍须监督层另行核验。"""
    if not isinstance(expected, ProcessIdentity) or not isinstance(observed, ProcessIdentity):
        return 'unknown'
    if (expected.pid != observed.pid or expected.creation_ticks != observed.creation_ticks
            or expected.image_path.casefold() != observed.image_path.casefold()):
        return 'mismatch'
    return observed.state if observed.state in ('running', 'exited') else 'unknown'


@contextmanager
def state_lock(path):
    """只锁既有普通文件；调用方先提供经过 ACL 验证的私有根。"""
    native = Win32()
    import msvcrt
    path = Path(path)
    for component in (path, *path.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise NativeError('unsafe-path')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise NativeError('unsafe-path')
    # Python 打开的描述符默认不可继承；再显式核验，退出始终关闭句柄。
    with path.open('r+b', buffering=0) as stream:
        if os.get_inheritable(stream.fileno()):
            raise NativeError('inheritable-handle')
        opened = os.fstat(stream.fileno())
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise NativeError('unsafe-path')
        handle = msvcrt.get_osfhandle(stream.fileno())
        overlapped = Overlapped()
        native.lock(handle, overlapped)
        try:
            yield
        finally:
            native.unlock(handle, overlapped)


def _query_hypervisor(query):
    """只查询 HypervisorPresent；不创建 partition 或改变宿主功能。"""
    query.argtypes = [DWORD, ctypes.c_void_p, DWORD, ctypes.POINTER(DWORD)]
    query.restype = ctypes.c_int32
    # 文档要求容量足以容纳64位值；本 capability 的结果类型为 BOOL。
    buffer = ctypes.c_uint64(0)
    written = DWORD(0)
    result = query(0, ctypes.byref(buffer), ctypes.sizeof(buffer), ctypes.byref(written))
    if result != 0 or written.value not in (ctypes.sizeof(BOOL), ctypes.sizeof(buffer)):
        return {'status': 'query-failed', 'hypervisor_present': None}
    present = ctypes.cast(ctypes.byref(buffer), ctypes.POINTER(BOOL)).contents.value
    return {'status': 'available' if present else 'not-present',
            'hypervisor_present': bool(present)}


def hypervisor_capability():
    """从系统目录加载 WHP API；缺失和读取失败不冒充硬件关闭。"""
    if os.name != 'nt':
        return {'status': 'unsupported-platform', 'hypervisor_present': None}
    try:
        library = ctypes.WinDLL('WinHvPlatform.dll', winmode=0x800)
        query = library.WHvGetCapability
    except (OSError, AttributeError):
        return {'status': 'api-unavailable', 'hypervisor_present': None}
    try:
        return _query_hypervisor(query)
    except OSError:
        return {'status': 'query-failed', 'hypervisor_present': None}
