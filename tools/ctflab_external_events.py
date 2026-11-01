"""外部Windows来宾的显式白名单事件XML快照；只读，不注册源、清日志或启动程序。"""
import ctypes as C
from datetime import datetime, timezone
import hashlib
import os
import re
import xml.etree.ElementTree as ET

from ctflab_contract import canonical, require, uuid_text

MAX_XML = 64 * 1024
MAX_SNAPSHOT = 256 * 1024
NS = {'e': 'http://schemas.microsoft.com/win/2004/08/events/event'}
PTR = C.c_void_p
U32 = C.c_uint32


def instant(value):
    """按100ns整数比较，保留Windows第七位小数，避免边界截断。"""
    require(type(value) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,7})?Z', value))
    main, _, fraction = value[:-1].partition('.')
    stamp = datetime.strptime(main, '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
    return (stamp.toordinal() * 86400 + stamp.hour * 3600 + stamp.minute * 60 + stamp.second) * 10**7 + int(fraction.ljust(7, '0'))


def policy(value):
    require(type(value) is dict and set(value) == {'channel', 'provider', 'event_ids', 'after', 'before', 'max_records'})
    # 单个来源、至多四个事件ID，固定小于20个XPath表达式；不接受文件路径或调用者XPath。
    require(type(value['channel']) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _./-]{0,127}', value['channel'])
            and '..' not in value['channel'] and not value['channel'].endswith('/'), 'permission-denied')
    name = value['provider']
    require(type(name) is str and 1 <= len(name) <= 128 and name.strip() == name
            and all(ch.isalnum() or ch in ' ._-{}' for ch in name), 'permission-denied')
    ids = value['event_ids']
    require(type(ids) is list and 1 <= len(ids) <= 4 and all(type(n) is int and 0 <= n <= 65535 for n in ids)
            and ids == sorted(set(ids)))
    require(0 < instant(value['before']) - instant(value['after']) <= 86400 * 10**7)
    require(type(value['max_records']) is int and 1 <= value['max_records'] <= 32)
    return value


def selection(value):
    value = policy(value)
    ids = ' or '.join('EventID=' + str(n) for n in value['event_ids'])
    return ("*[System[Provider[@Name='" + value['provider'] + "'] and (" + ids + ") and TimeCreated[@SystemTime>='"
            + value['after'] + "' and @SystemTime<'" + value['before'] + "']]]")


def parsed(raw, value):
    policy(value)
    require(type(raw) is str and 0 < len(raw.encode('utf-8')) <= MAX_XML and '<!' not in raw and '\0' not in raw,
            'identity-unknown')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        require(False, 'identity-unknown')
    require(root.tag == '{' + NS['e'] + '}Event', 'identity-unknown')
    systems = root.findall('e:System', NS)
    require(len(systems) == 1, 'identity-unknown')
    system = systems[0]
    def one(name):
        found = system.findall('e:' + name, NS)
        require(len(found) == 1, 'identity-unknown')
        return found[0]
    channel = one('Channel').text
    provider = one('Provider').get('Name')
    event = one('EventID').text
    record = one('EventRecordID').text
    at = one('TimeCreated').get('SystemTime')
    require(channel == value['channel'] and provider == value['provider']
            and type(event) is str and re.fullmatch(r'\d{1,5}', event) and int(event) in value['event_ids']
            and type(record) is str and re.fullmatch(r'[1-9]\d{0,19}', record) and int(record) <= 2**64 - 1,
            'identity-unknown')
    require(instant(value['after']) <= instant(at) < instant(value['before']), 'identity-unknown')
    return {'record_id': int(record), 'event_id': int(event), 'at': at,
            'xml_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(), 'xml': raw}


class API:
    """只加载系统目录的wevtapi读函数；普通账户权限不足即失败。"""
    def __init__(self, machine):
        require(os.name == 'nt' and C.sizeof(PTR) == 8, 'unsupported-platform')
        from ctflab_external import native_machine
        require(native_machine()['machine_uuid'] == uuid_text(machine), 'identity-unknown')
        self.library = C.WinDLL('wevtapi.dll', winmode=0x800, use_last_error=True)
        definitions = {'EvtQuery': ([PTR, C.c_wchar_p, C.c_wchar_p, U32], PTR),
                       'EvtNext': ([PTR, U32, C.POINTER(PTR), U32, U32, C.POINTER(U32)], C.c_int),
                       'EvtRender': ([PTR, PTR, U32, U32, PTR, C.POINTER(U32), C.POINTER(U32)], C.c_int),
                       'EvtClose': ([PTR], C.c_int)}
        for name, (args, result) in definitions.items():
            fn = getattr(self.library, name)
            fn.argtypes = args
            fn.restype = result
            setattr(self, name, fn)
        self.error = C.get_last_error


class Collector:
    def __init__(self, machine, *, api=None):
        self.is_native = api is None
        self.api = API(machine) if api is None else api

    def render(self, event):
        used, properties = U32(), U32()
        require(not self.api.EvtRender(None, event, 1, 0, None, C.byref(used), C.byref(properties))
                and self.api.error() == 122 and 2 <= used.value <= MAX_XML and used.value % 2 == 0,
                'identity-unknown')
        buffer = C.create_string_buffer(used.value)
        size = used.value
        require(self.api.EvtRender(None, event, 1, size, buffer, C.byref(used), C.byref(properties))
                and 2 <= used.value <= size and used.value % 2 == 0 and buffer.raw[used.value-2:used.value] == b'\0\0',
                'identity-unknown')
        return buffer.raw[:used.value-2].decode('utf-16-le')

    def collect(self, value):
        value = policy(value)
        query = self.api.EvtQuery(None, value['channel'], selection(value), 0x101)
        require(bool(query), 'permission-denied')
        rows, total, close_failed = [], 0, False
        try:
            while True:
                # 一个句柄一批，最多多读一条用于拒绝截断结果，所有句柄均在原调用线程关闭。
                handles, count = (PTR * 1)(), U32()
                try:
                    ok = self.api.EvtNext(query, 1, handles, 1000, 0, C.byref(count))
                    if not ok:
                        require(self.api.error() == 259 and count.value == 0, 'control-unreachable')
                        break
                    require(count.value == 1 and bool(handles[0]), 'identity-unknown')
                    require(len(rows) < value['max_records'], 'storage-insufficient')
                    row = parsed(self.render(handles[0]), value)
                    total += len(canonical(row).encode('utf-8'))
                    require(total <= MAX_SNAPSHOT, 'storage-insufficient')
                    require(not rows or row['record_id'] > rows[-1]['record_id'], 'identity-unknown')
                    rows.append(row)
                finally:
                    if handles[0] and not self.api.EvtClose(handles[0]):
                        close_failed = True
        finally:
            if not self.api.EvtClose(query):
                close_failed = True
        require(not close_failed, 'control-unreachable')
        data = canonical({'schema': 1, 'policy': value, 'records': rows}).encode('utf-8')
        require(len(data) <= MAX_SNAPSHOT, 'storage-insufficient')
        return data, len(rows)
