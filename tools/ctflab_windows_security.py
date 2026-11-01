"""Windows 私有状态根：当前普通进程 SID、创建时保护 DACL、每次读写前核验。

不修改已有目录的 ACL，不提供提权或权限修复入口；不防御同用户恶意代码。
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path, PureWindowsPath
import re
import stat

from ctflab_windows_native import NativeError, DWORD, BOOL, HANDLE

POINTER = ctypes.c_void_p


class SecurityAttributes(ctypes.Structure):
    _fields_ = [('length', DWORD), ('descriptor', POINTER), ('inherit', BOOL)]


class AclSize(ctypes.Structure):
    _fields_ = [('count', DWORD), ('used', DWORD), ('free', DWORD)]


class AceHeader(ctypes.Structure):
    _fields_ = [('kind', ctypes.c_ubyte), ('flags', ctypes.c_ubyte), ('size', ctypes.c_uint16)]


def validate_acl(owner, protected, aces, user, *, root):
    """只接受当前用户与 SYSTEM 的简单允许 ACE；其他类型保守拒绝。"""
    if owner != user or root and not protected or not isinstance(aces, list) or not 1 <= len(aces) <= 64:
        raise NativeError('permission-denied')
    granted = 0
    for ace in aces:
        if (ace['kind'] != 0 or ace['sid'] not in (user, 'S-1-5-18')
                or ace['flags'] & ~0x1f):
            raise NativeError('permission-denied')
        if ace['sid'] == user and not ace['flags'] & 0x08:
            granted |= ace['mask']
    if granted & 0x1f01ff != 0x1f01ff and not granted & 0x10000000:
        raise NativeError('permission-denied')


def validate_local_path(value):
    """活动状态仅接受本地盘符路径；拒绝共享、设备命名空间与 ADS。"""
    path = PureWindowsPath(value)
    if (not path.is_absolute() or re.fullmatch(r'[A-Za-z]:', path.drive) is None
            or any(part == '..' or ':' in part or part.endswith((' ', '.'))
                   or PureWindowsPath(part).is_reserved() for part in path.parts[1:])):
        raise NativeError('permission-denied')


def guard_path(path):
    validate_local_path(str(path))
    path = Path(path).absolute()
    for component in (path, *path.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            if component == path:
                continue
            raise NativeError('permission-denied') from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise NativeError('permission-denied')
    return path


class WindowsSecurity:
    def __init__(self):
        if os.name != 'nt':
            raise NativeError('unsupported-platform')
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True, winmode=0x800)
        self.security = ctypes.WinDLL('advapi32', use_last_error=True, winmode=0x800)
        pointer_out = ctypes.POINTER(POINTER)
        definitions = [
            (self.kernel, 'GetCurrentProcess', [], HANDLE),
            (self.kernel, 'GetCurrentThread', [], HANDLE),
            (self.kernel, 'CloseHandle', [HANDLE], BOOL),
            (self.kernel, 'LocalFree', [POINTER], POINTER),
            (self.kernel, 'CreateDirectoryW', [ctypes.c_wchar_p, ctypes.POINTER(SecurityAttributes)], BOOL),
            (self.security, 'OpenProcessToken', [HANDLE, DWORD, ctypes.POINTER(HANDLE)], BOOL),
            (self.security, 'OpenThreadToken', [HANDLE, DWORD, BOOL, ctypes.POINTER(HANDLE)], BOOL),
            (self.security, 'GetTokenInformation', [HANDLE, DWORD, POINTER, DWORD, ctypes.POINTER(DWORD)], BOOL),
            (self.security, 'ConvertSidToStringSidW', [POINTER, pointer_out], BOOL),
            (self.security, 'ConvertStringSecurityDescriptorToSecurityDescriptorW',
             [ctypes.c_wchar_p, DWORD, pointer_out, ctypes.POINTER(DWORD)], BOOL),
            (self.security, 'GetNamedSecurityInfoW',
             [ctypes.c_wchar_p, DWORD, DWORD]+[pointer_out]*5, DWORD),
            (self.security, 'GetSecurityDescriptorControl', [POINTER, ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(DWORD)], BOOL),
            (self.security, 'GetAclInformation', [POINTER, POINTER, DWORD, DWORD], BOOL),
            (self.security, 'GetAce', [POINTER, DWORD, pointer_out], BOOL),
        ]
        for library, name, arguments, result in definitions:
            function = getattr(library, name)
            function.argtypes = arguments; function.restype = result

    def _sid(self, pointer):
        output = POINTER()
        if not pointer or not self.security.ConvertSidToStringSidW(pointer, ctypes.byref(output)):
            raise NativeError('permission-denied')
        try:
            value = ctypes.wstring_at(output)
            if not re.fullmatch(r'S-1-(?:\d+-)+\d+', value):
                raise NativeError('permission-denied')
            return value
        finally:
            self.kernel.LocalFree(output)

    def current_user(self):
        # 不接受线程模拟身份，以免读取主进程身份后在另一主体下访问文件。
        thread_token = HANDLE()
        if self.security.OpenThreadToken(self.kernel.GetCurrentThread(), 8, True, ctypes.byref(thread_token)):
            self.kernel.CloseHandle(thread_token)
            raise NativeError('permission-denied')
        if ctypes.get_last_error() != 1008:  # ERROR_NO_TOKEN
            raise NativeError('permission-denied')
        token = HANDLE()
        if not self.security.OpenProcessToken(self.kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise NativeError('permission-denied')
        try:
            elevation, written = DWORD(), DWORD()
            if (not self.security.GetTokenInformation(token, 20, ctypes.byref(elevation), 4, ctypes.byref(written))
                    or written.value != 4 or elevation.value):
                raise NativeError('permission-denied')
            needed = DWORD()
            self.security.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
            if not ctypes.sizeof(POINTER) <= needed.value <= 4096:
                raise NativeError('permission-denied')
            buffer = ctypes.create_string_buffer(needed.value)
            if not self.security.GetTokenInformation(token, 1, buffer, needed.value, ctypes.byref(needed)):
                raise NativeError('permission-denied')
            # TOKEN_USER 首字段为 SID_AND_ATTRIBUTES，SID 指针位于偏移0。
            return self._sid(ctypes.cast(buffer, ctypes.POINTER(POINTER)).contents)
        finally:
            self.kernel.CloseHandle(token)

    def verify(self, path, *, root=False):
        path = guard_path(path)
        info = path.stat()
        if root:
            if not stat.S_ISDIR(info.st_mode): raise NativeError('permission-denied')
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise NativeError('permission-denied')
        user = self.current_user()
        owner, dacl, descriptor = POINTER(), POINTER(), POINTER()
        result = self.security.GetNamedSecurityInfoW(str(path), 1, 5, ctypes.byref(owner), None,
                                                     ctypes.byref(dacl), None, ctypes.byref(descriptor))
        if result or not descriptor:
            raise NativeError('permission-denied')
        try:
            if not dacl: raise NativeError('permission-denied')
            control, revision = ctypes.c_uint16(), DWORD()
            if not self.security.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)):
                raise NativeError('permission-denied')
            size = AclSize()
            if not self.security.GetAclInformation(dacl, ctypes.byref(size), ctypes.sizeof(size), 2) or size.count > 64:
                raise NativeError('permission-denied')
            aces = []
            for index in range(size.count):
                pointer = POINTER()
                if not self.security.GetAce(dacl, index, ctypes.byref(pointer)) or not pointer:
                    raise NativeError('permission-denied')
                header = ctypes.cast(pointer, ctypes.POINTER(AceHeader)).contents
                if header.kind != 0 or header.size < 16:
                    raise NativeError('permission-denied')
                mask = ctypes.cast(pointer.value+4, ctypes.POINTER(DWORD)).contents.value
                aces.append({'kind':header.kind,'flags':header.flags,'mask':mask,
                             'sid':self._sid(POINTER(pointer.value+8))})
            validate_acl(self._sid(owner), bool(control.value & 0x1000), aces, user, root=root)
            return user
        finally:
            self.kernel.LocalFree(descriptor)

    def create_directory(self, path):
        path = guard_path(path)
        user = self.current_user()
        descriptor = POINTER()
        # 仅在创建新根时设置 ACL；不先建宽权限目录再收紧。
        sddl = f'O:{user}D:P(A;OICI;FA;;;{user})(A;OICI;FA;;;SY)'
        if not self.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise NativeError('permission-denied')
        try:
            attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
            if not self.kernel.CreateDirectoryW(str(path), ctypes.byref(attributes)):
                if ctypes.get_last_error() == 183: raise FileExistsError('私有根已存在')
                raise NativeError('permission-denied')
        finally:
            self.kernel.LocalFree(descriptor)
        self.verify(path, root=True)
