"""外部Kali专用助手材料生成：TAP/命名空间助手、安装说明与摘要清单。

只生成新材料目录，不安装、不改网络、不要求root。助手为来宾内单文件Python3：
root守护进程持有窄权限网络操作与TAP生命周期（租约到期自动回收），SSH专用账户
client经私有Unix socket对端凭据校验调用；帧数据经固定SSH入口双向传输。会话选择
通过数据面HELLO握手完成（ForceCommand不含会话参数）；实际来宾身份（助手摘要/
机器UUID）在握手中上报并严格核验。真实内核行为属实机验收。
"""
import hashlib
import json
import os
import re
import shlex
from pathlib import Path

if __package__ in (None, ''):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctflab_contract import canonical, require

ASSISTANT_NAME = 'ctflab-kali-attach'
DAEMON_NAME = 'ctflab-kali-attachd'
CONTROL_SOCKET = '/run/ctflab-attach/control.sock'
STATE_ROOT = '/var/lib/ctflab-attach/sessions'
DEFAULT_USER = 'ctflab-attach'
MAX_FRAME = 1514
SESSION_HOURS = 2
SESSION_QUOTA_BYTES = 2**30
SESSION_PATTERN = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
MAC_PATTERN = r'02(?::[0-9a-f]{2}){5}'
# 受控raw工具白名单名与参数上限（宿主侧展示用）；脚本内RAW_TOOLS为权威定义，
# 测试核验两处一致，改动白名单必须同时更新这里。
RAW_TOOL_NAMES = frozenset(('ping',))
RAW_TOOL_ARGUMENT_LIMIT = 16

# 来宾端助手：client(专用SSH账户,非root) + daemon(root)。
# - 帧记录格式与宿主一致：type(1) seq(4) len(2) payload；双向序号各自单调，
#   重复/回退序号即断开，不重放。
# - 会话选择：SSH ForceCommand固定为 attach（无参数）；宿主首条CONTROL记录携带
#   会话UUID与一次性挑战，client向daemon核验存在性与到期后应答身份（助手摘要/
#   机器UUID，DMI不可读时上报null，宿主拒绝自动退化身份）。
# - shell：daemon按连接fork降权shell（不阻塞控制循环），client双向转发stdio。
# - TAP生命周期：daemon持有生命周期FD并按租约回收；client副本随进程退出关闭。
ASSISTANT_SCRIPT = r'''#!/usr/bin/python3 -I
"""CTFLab 外部攻击机专用助手（来宾端，单文件两模式）。

daemon(root)：ctflab-kali-attachd —— 唯一持有网络权限与TAP生命周期FD的进程。
client(专用SSH账户)：ctflab-kali-attach attach|shell —— attach为SSH固定入口。
setup/teardown/status 由管理员以 root 运行。实验资源位于会话独占network
namespace；不改原管理网卡/默认路由/DNS。
"""
import argparse, fcntl, hashlib, json, os, re, select, shlex, signal, socket, struct, subprocess, sys, threading, time

CONTROL = @CONTROL@
STATE_ROOT = @STATE@
ATTACH_USER = @USER@
MAX_FRAME = @MAX_FRAME@
SESSION_HOURS = @HOURS@
SESSION_QUOTA_BYTES = @QUOTA@
RECORD_HEADER = 7
PAYLOAD_LIMITS = {0x01: MAX_FRAME, 0x02: 4096, 0x03: 0, 0x04: 256}
RECORD_FRAME, RECORD_CONTROL, RECORD_HEARTBEAT, RECORD_CLOSE = 0x01, 0x02, 0x03, 0x04
HANDSHAKE_HOST = 'ctflab-external-l2/1'
HANDSHAKE_GUEST = 'ctflab-kali-attach/1'
SWEEP_SECONDS = 30


def fail(message):
    print(message, file=sys.stderr); raise SystemExit(2)


def valid_session(text):
    return type(text) is str and re.fullmatch(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', text) is not None


def valid_mac(text):
    return type(text) is str and re.fullmatch(r'02(?::[0-9a-f]{2}){5}', text.lower()) is not None


def netns_name(session):
    return 'ctflab-' + session.replace('-', '')[:12]


def tap_name(session):
    return 'ctf' + session.replace('-', '')[:11]


# 固定系统候选，不从PATH、请求或来宾环境选择root执行入口。
SYSTEM_ENV = {'PATH': '/usr/sbin:/usr/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
TOOL_CANDIDATES = {'ip': ('/usr/sbin/ip', '/usr/bin/ip'),
                   'setpriv': ('/usr/bin/setpriv',), 'shell': ('/bin/sh', '/usr/bin/sh')}
TOOLS = {}

# 受控raw工具（设计§4.2）：原始套接字能力(net_raw)只授予固定白名单内的二进制，
# 运行在会话命名空间内并降权到专用账户；不交付任意sudo、可写脚本或
# CAP_SYS_ADMIN shell。首版只登记ICMP探测与SYN/UDP扫描两类已声明工具；
# 真实Kali上的工具行为与能力生效属实机验收，不在本地合成中冒称通过。
RAW_TOOL_MAX_SECONDS = 1800
RAW_TOOL_ARGUMENT_LIMIT = 16
RAW_TOOLS = {
    'ping': {'candidates': ('/usr/bin/ping', '/bin/ping'),
             'value_flags': {'-c': (1, 100), '-w': (1, 300), '-W': (1, 10)},
             'boolean_flags': ('-n',)},
    # nmap不在首版白名单：Kali Rolling 2026-08的/usr/bin/nmap是shell包装脚本，
    # 其/usr/lib/nmap/nmap带cap_net_admin,cap_net_raw=eip文件能力；内核对
    # no_new_privs进程exec带filecap二进制一律EPERM（2026-11-01真实内核验收
    # 发现）。ambient授予的net_raw只对无filecap二进制有效；SYN/UDP扫描需
    # 另行提供无filecap的专用工具后重新单列测试，不得以放宽NNP绕过。
}
RAW_TOOLS_RESOLVED = {}
VERIFIED_SOURCE = None


def trusted_path(path, *, directory=False, private=False, owner_uid=0):
    """逐组件检查，包括root管理的usr-merge链接；不能先resolve后漏查原路径。

    owner_uid仅供函数级测试；所有实际入口固定使用root(0)。不允许来自RPC的覆盖。
    """
    import stat
    if type(path) is not str or not os.path.isabs(path) or '\x00' in path:
        raise OSError('untrusted-path')
    owners = {0, owner_uid}
    def walk(value, depth=0):
        if depth > 32:
            raise OSError('link-depth-exceeded')
        current = '/'
        info = os.lstat(current)
        if info.st_uid not in owners or info.st_mode & 0o022:
            raise OSError('untrusted-ancestor')
        for part in value.split('/'):
            if part in ('', '.'):
                continue
            if not stat.S_ISDIR(os.lstat(current).st_mode):
                raise OSError('untrusted-ancestor-type')
            if part == '..':
                current = os.path.dirname(current)
                continue  # 上一个组件已经核对，不能词法折叠而跳过不可信目录。
            candidate = os.path.join(current, part)
            info = os.lstat(candidate)
            if info.st_uid not in owners:
                raise OSError('untrusted-owner')
            if stat.S_ISLNK(info.st_mode):
                target = os.readlink(candidate)
                target = target if os.path.isabs(target) else os.path.join(current, target)
                current = walk(target, depth + 1)
                info = os.lstat(current)
            else:
                if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)) or info.st_mode & 0o022:
                    raise OSError('untrusted-permissions-or-type')
                current = candidate
        return current
    canonical = walk(path)
    info = os.lstat(canonical)
    if directory:
        if not stat.S_ISDIR(info.st_mode) or (private and info.st_mode & 0o077):
            raise OSError('untrusted-directory')
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise OSError('untrusted-file')
    return canonical


def file_digest(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def command_path(name):
    if name not in TOOL_CANDIDATES:
        raise OSError('command-not-approved')
    if name in TOOLS:
        saved = TOOLS[name]
        actual = trusted_path(saved['logical'])
        if actual != saved['path'] or file_digest(actual) != saved['sha256']:
            raise OSError('installed-tool-changed')
        return actual
    for candidate in TOOL_CANDIDATES[name]:
        if os.path.lexists(candidate):
            actual = trusted_path(candidate)
            if not os.stat(actual).st_mode & 0o111:
                raise OSError('tool-not-executable')
            TOOLS[name] = {'logical': candidate, 'path': actual, 'sha256': file_digest(actual)}
            return actual
    raise OSError('required-tool-missing')


def verify_installation():
    global VERIFIED_SOURCE
    if sys.platform != 'linux':
        raise OSError('linux-required')
    source = trusted_path(os.path.abspath(__file__))
    interpreter = trusted_path(sys.executable)
    VERIFIED_SOURCE = {'path': source, 'sha256': file_digest(source)}
    for name in TOOL_CANDIDATES:
        command_path(name)
    result = subprocess.run([command_path('setpriv'), '--help'], env=SYSTEM_ENV,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5)
    required = (b'--no-new-privs', b'--bounding-set', b'--inh-caps', b'--ambient-caps', b'--clear-groups')
    if result.returncode or any(flag not in result.stdout for flag in required):
        raise OSError('setpriv-capabilities-unavailable')
    return {'state': 'installation-verified', 'assistant': VERIFIED_SOURCE,
            'interpreter': {'path': interpreter, 'sha256': file_digest(interpreter)},
            'tools': TOOLS, 'note': 'root路径与本进程启动摘要核对；不代表TAP或SSH实机验收。'}


def trusted_directory(path, mode):
    """只创建缺失的固定目录；既存不安全目录拒绝，不自动修权限或覆盖。"""
    if os.path.exists(path):
        return trusted_path(path, directory=True, private=mode == 0o700)
    parent = os.path.dirname(path)
    trusted_directory(parent, 0o755)
    os.mkdir(path, mode)
    return trusted_path(path, directory=True, private=mode == 0o700)


def socket_identity(path):
    info = os.lstat(path)
    return info.st_dev, info.st_ino


def unlink_owned_socket(path, identity):
    import stat
    try:
        info = os.lstat(path)
        if stat.S_ISSOCK(info.st_mode) and info.st_uid == 0 and (info.st_dev, info.st_ino) == identity:
            os.unlink(path)
    except FileNotFoundError:
        pass


def prepare_control_socket():
    """只移除已确认无监听者、且inode未变的自有旧socket；其他资产拒绝覆盖。"""
    import errno, stat
    if not os.path.lexists(CONTROL):
        return
    info = os.lstat(CONTROL)
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != 0:
        raise OSError('control-path-conflict')
    identity = socket_identity(CONTROL)
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(0.5)
    try:
        probe.connect(CONTROL)
    except OSError as error:
        if error.errno not in (errno.ECONNREFUSED, errno.ENOENT):
            raise OSError('control-liveness-unknown') from error
    else:
        raise OSError('control-already-running')
    finally:
        probe.close()
    if os.path.lexists(CONTROL):
        if socket_identity(CONTROL) != identity:
            raise OSError('control-path-changed')
        unlink_owned_socket(CONTROL, identity)


def shell_launch(grant, account):
    if (type(account.pw_uid) is not int or account.pw_uid <= 0
            or type(account.pw_gid) is not int or account.pw_gid <= 0
            or not valid_session(grant.get('session'))
            or grant.get('netns') != netns_name(grant['session'])):
        raise OSError('untrusted-shell-account-or-session')
    ip, privilege, shell = (command_path(name) for name in ('ip', 'setpriv', 'shell'))
    arguments = [ip, 'netns', 'exec', grant['netns'], privilege,
                 '--reuid=%d' % account.pw_uid, '--regid=%d' % account.pw_gid,
                 '--clear-groups', '--inh-caps=-all', '--ambient-caps=-all',
                 '--bounding-set=-all', '--no-new-privs', shell, '-i']
    environment = dict(SYSTEM_ENV, HOME=account.pw_dir, USER=account.pw_name,
                       LOGNAME=account.pw_name, SHELL=shell, TERM='xterm-256color')
    return ip, arguments, environment


def raw_tool_path(tool):
    """受控工具固定路径解析：白名单候选逐一通过可信路径检查并固定摘要。

    首次成功解析后缓存路径与摘要；后续调用复核摘要，文件被替换即拒绝执行，
    与TOOL_CANDIDATES的过程内摘要复核一致。
    """
    if tool not in RAW_TOOLS:
        raise OSError('raw-tool-not-approved')
    if tool in RAW_TOOLS_RESOLVED:
        saved = RAW_TOOLS_RESOLVED[tool]
        actual = trusted_path(saved['logical'])
        if actual != saved['path'] or file_digest(actual) != saved['sha256']:
            raise OSError('installed-raw-tool-changed')
        return actual
    failure = None
    for candidate in RAW_TOOLS[tool]['candidates']:
        try:
            actual = trusted_path(candidate)
        except OSError as error:
            failure = error
            continue
        RAW_TOOLS_RESOLVED[tool] = {'logical': candidate, 'path': actual,
                                    'sha256': file_digest(actual)}
        return actual
    raise OSError('raw-tool-unavailable: ' + str(failure))


def raw_tool_arguments(grant, tool, arguments):
    """严格校验受控工具参数；目标必须是会话网段内的点分IPv4地址。

    旗标与取值逐一匹配白名单；位置参数只接受网段内IPv4，不接受主机名、
    选项样式的目标或网段外地址。任何不匹配整体拒绝，不做部分执行。
    """
    spec = RAW_TOOLS.get(tool)
    if spec is None or type(arguments) is not list:
        raise ValueError('raw-tool-request')
    if len(arguments) > RAW_TOOL_ARGUMENT_LIMIT or any(
            type(item) is not str or not item or '\x00' in item or len(item) > 256
            for item in arguments):
        raise ValueError('raw-tool-arguments')
    validated, targets = [], []
    index = 0
    while index < len(arguments):
        item = arguments[index]
        if item.startswith('-'):
            if item in spec['boolean_flags']:
                validated.append(item)
                index += 1
                continue
            if item not in spec['value_flags'] or index + 1 >= len(arguments):
                raise ValueError('raw-tool-flag')
            bounds = spec['value_flags'][item]
            value = arguments[index + 1]
            if bounds is None:
                # 仅nmap -p端口表：数字、逗号与范围分隔符，长度有界。
                if type(value) is not str or not re.fullmatch(r'[0-9]{1,5}([,-][0-9]{1,5})*', value):
                    raise ValueError('raw-tool-ports')
            else:
                try:
                    numeric = int(value)
                except ValueError:
                    raise ValueError('raw-tool-value')
                if not bounds[0] <= numeric <= bounds[1]:
                    raise ValueError('raw-tool-value')
            validated.extend((item, value))
            index += 2
            continue
        if item.startswith('/') or '=' in item:
            raise ValueError('raw-tool-target')
        targets.append(item)
        index += 1
    if not targets:
        raise ValueError('raw-tool-target-missing')
    import ipaddress
    network = ipaddress.ip_network('%s/%d' % (grant['address'], grant['prefix']), strict=False)
    for target in targets:
        try:
            address = ipaddress.IPv4Address(target)
        except ValueError:
            raise ValueError('raw-tool-target')
        if address not in network:
            raise ValueError('raw-tool-target-outside')
    validated.extend(targets)
    return validated


def raw_tool_launch(grant, account, tool, arguments):
    """构造受控raw工具的固定argv：会话命名空间内、仅net_raw能力、降权+NNP。

    能力边界只含CAP_NET_RAW：bounding/inherited/ambient均显式限定，
    不得通过sudo、shell或可继承能力扩大；无新特权防止setuid/filecap提权。
    """
    if (type(account.pw_uid) is not int or account.pw_uid <= 0
            or type(account.pw_gid) is not int or account.pw_gid <= 0
            or not valid_session(grant.get('session'))
            or grant.get('netns') != netns_name(grant['session'])):
        raise OSError('untrusted-raw-account-or-session')
    validated = raw_tool_arguments(grant, tool, arguments)
    ip, privilege, executable = command_path('ip'), command_path('setpriv'), raw_tool_path(tool)
    arguments = [ip, 'netns', 'exec', grant['netns'], privilege,
                 '--reuid=%d' % account.pw_uid, '--regid=%d' % account.pw_gid,
                 '--clear-groups', '--bounding-set=-all,+net_raw',
                 '--inh-caps=+net_raw', '--ambient-caps=+net_raw', '--no-new-privs',
                 executable, *validated]
    return ip, arguments, dict(SYSTEM_ENV)


# ---------- 帧记录编解码（双向序号各自单调） ----------

def send_record(sink, kind, sequence, payload=b''):
    raw = struct.pack('!BIH', kind, sequence, len(payload)) + payload
    view = memoryview(raw)
    while view:
        written = sink.write(view)
        written = len(raw) if written is None else written
        view = view[written:]


def read_record(source):
    header = b''
    while len(header) < RECORD_HEADER:
        chunk = source.read(RECORD_HEADER - len(header))
        if not chunk:
            return None
        header += chunk
    kind, sequence, length = struct.unpack('!BIH', header)
    if kind not in PAYLOAD_LIMITS or length > PAYLOAD_LIMITS[kind]:
        return None
    payload = b''
    while len(payload) < length:
        chunk = source.read(length - len(payload))
        if not chunk:
            return None
        payload += chunk
    return kind, sequence, payload


def read_record_checked(source, expected_sequence):
    """接收宿主记录：序号必须严格等于期望值，重复/回退/跳号一律拒绝。"""
    record = read_record(source)
    if record is None:
        return None
    kind, sequence, payload = record
    if sequence != expected_sequence:
        return None
    return kind, sequence, payload


# ---------- SCM_RIGHTS 描述符收发（recvmsg第二参数为整数缓冲区大小） ----------

def send_descriptor(sock, fd):
    sock.sendmsg([b'fd'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, struct.pack('i', fd))])


def receive_descriptor(sock):
    size = struct.calcsize('i')
    data, auxiliary, flags, _ = sock.recvmsg(16, socket.CMSG_SPACE(size * 16))
    descriptors = []
    for level, kind, payload in auxiliary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
            descriptors.extend(struct.unpack('%di' % (len(payload) // size),
                                             payload[:len(payload) // size * size]))
    if data != b'fd' or flags & socket.MSG_CTRUNC or len(descriptors) != 1:
        for fd in descriptors:
            os.close(fd)
        raise OSError('missing-descriptor')
    os.set_inheritable(descriptors[0], False)
    return descriptors[0]  # SCM_RIGHTS已分配新FD，所有权直接交给调用方。


def create_tap_in_ns(ns, tap):
    """子进程setns进入新命名空间创建独占TAP，经SCM_RIGHTS把FD交还daemon。

    子进程失败时向parent发送空报文并由waitpid状态判定；parent只认一个描述符。
    """
    parent, child_end = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    pid = os.fork()
    if pid == 0:
        code = 0
        try:
            parent.close()
            netns = os.open('/run/netns/' + ns, os.O_RDONLY)
            import ctypes
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.setns(netns, 0) != 0:
                raise OSError(ctypes.get_errno(), 'setns失败')
            fd = os.open('/dev/net/tun', os.O_RDWR)
            TUNSETIFF, IFF_TAP, IFF_NO_PI = 0x400454CA, 0x0002, 0x1000
            fcntl.ioctl(fd, TUNSETIFF, struct.pack('16sH', tap.encode(), IFF_TAP | IFF_NO_PI))
            send_descriptor(child_end, fd)
            os.close(fd)
        except BaseException:
            code = 1
        finally:
            try:
                child_end.close()
            except OSError:
                pass
            os._exit(code)
    child_end.close()
    try:
        descriptor = receive_descriptor(parent)
        _, status = os.waitpid(pid, 0)
        if status != 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
            return None
        return descriptor
    except OSError:
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        return None
    finally:
        try:
            parent.close()
        except OSError:
            pass


def read_machine_uuid():
    """读取DMI机器UUID；不可读时返回None，宿主拒绝未登记的替代身份。"""
    try:
        with open('/sys/class/dmi/id/product_uuid', 'r', encoding='ascii') as stream:
            value = stream.read().strip().lower()
        return value or None
    except OSError:
        return None


def self_digest():
    try:
        if VERIFIED_SOURCE is not None:
            actual = trusted_path(os.path.abspath(__file__))
            digest = file_digest(actual)
            return digest if actual == VERIFIED_SOURCE['path'] and digest == VERIFIED_SOURCE['sha256'] else None
        with open(os.path.realpath(__file__), 'rb') as stream:
            return hashlib.sha256(stream.read()).hexdigest()
    except OSError:
        return None


def peer_uid(connection):
    return struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, 17, 12))[1]  # Linux SO_PEERCRED: pid, uid, gid


def load_grant(session):
    path = os.path.join(STATE_ROOT, session + '.json')
    try:
        with open(path, 'r', encoding='utf-8') as stream:
            grant = json.load(stream)
    except (OSError, ValueError):
        return None
    return grant if type(grant) is dict and grant.get('session') == session else None


def grant_expired(grant):
    try:
        expires = time.mktime(time.strptime(grant['expires'], '%Y-%m-%dT%H:%M:%SZ')) - time.timezone
    except (KeyError, ValueError):
        return True
    return time.time() > expires


def run(argv):
    """来宾网络命令封装；命令缺失（非Linux/最小环境）按失败处理而非崩溃。"""
    try:
        if not argv or argv[0] != 'ip':
            return 1
        return subprocess.run([command_path('ip'), *argv[1:]], env=SYSTEM_ENV,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 1


# ---------- daemon ----------

def save_cleanup_grant(grant):
    """先持久标记撤网中断；重启后只能继续清理，不能重新接入。"""
    path = os.path.join(STATE_ROOT, grant['session'] + '.json')
    temporary = path + '.cleanup'
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(grant, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(STATE_ROOT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def namespace_present(ns):
    try:
        os.stat('/run/netns/' + ns)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return None


def namespace_resources(ns):
    """只接受成功查询；查不到命令/无权限不解释为资源不存在。"""
    try:
        links = subprocess.run([command_path('ip'), '-j', '-n', ns, 'link', 'show'],
                               env=SYSTEM_ENV, timeout=5,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, check=True)
        names = json.loads(links.stdout)
        if type(names) is not list or any(type(item) is not dict or
                type(item.get('ifname')) is not str for item in names):
            return None
        pids = subprocess.run([command_path('ip'), 'netns', 'pids', ns], env=SYSTEM_ENV, timeout=5, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, text=True, check=True)
        processes = pids.stdout.split()
        if any(not value.isdecimal() for value in processes):
            return None
        return {item['ifname'] for item in names}, processes
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def restore_cleanup_sessions():
    """daemon重启不能恢复TAP FD；磁盘上的授权只用于管理员撤网。"""
    sessions = {}
    for filename in os.listdir(STATE_ROOT):
        session = filename[:-5] if filename.endswith('.json') else ''
        if not valid_session(session):
            continue
        grant = load_grant(session)
        if grant and grant.get('netns') == netns_name(session) and grant.get('tap') == tap_name(session):
            grant['cleanup_pending'] = True
            sessions[session] = {'grant': grant, 'tap_fd': None}
    return sessions


def teardown_session(session, sessions):
    entry = sessions.get(session)
    grant = entry['grant'] if entry else load_grant(session)
    ns, tap = netns_name(session), tap_name(session)
    if grant is None or grant.get('netns') != ns or grant.get('tap') != tap:
        return {'error': 'session-unknown', 'session': session}
    if entry is None:
        entry = sessions[session] = {'grant': grant, 'tap_fd': None}
    grant['cleanup_pending'] = True
    terminated = terminate_raw_children(session)
    leftover = []
    try:
        save_cleanup_grant(grant)
    except OSError:
        leftover.append('cleanup-record')
    if entry.get('tap_fd') is not None:
        try:
            os.close(entry['tap_fd'])
            entry['tap_fd'] = None
        except OSError:
            leftover.append('tap-fd')
    present = namespace_present(ns)
    if present is True:
        # 关闭生命周期FD不等于client副本关闭；显式删除TAP并验证。
        run(['ip', '-n', ns, 'link', 'del', tap])
        resources = namespace_resources(ns)
        if resources is None:
            leftover.append('namespace-inspection')
        else:
            names, pids = resources
            if tap in names:
                leftover.append('tap')
            if pids:
                leftover.append('namespace-processes')
            if names - {'lo', tap}:
                leftover.append('unexpected-links')
            if not leftover:
                run(['ip', 'netns', 'del', ns])
    removed = namespace_present(ns) is False
    if not removed:
        leftover.append('netns')
    if not leftover:
        try:
            os.unlink(os.path.join(STATE_ROOT, session + '.json'))
        except FileNotFoundError:
            pass
        except OSError:
            leftover.append('grant')
    if not leftover:
        sessions.pop(session, None)
    return {'state': 'cleanup-incomplete' if leftover else 'session-closed',
            'session': session, 'tap_fd_closed': entry.get('tap_fd') is None,
            'netns_removed': removed, 'raw_tools_terminated': terminated,
            'leftover': leftover}


def sweep_expired(sessions):
    for session in [key for key, entry in sessions.items()
                    if entry['grant'].get('cleanup_pending') or grant_expired(entry['grant'])]:
        teardown_session(session, sessions)


def daemon():
    import grp, pwd
    if os.geteuid() != 0:
        fail('daemon必须root运行')
    account = pwd.getpwnam(ATTACH_USER)
    attach_uid = account.pw_uid
    if attach_uid <= 0 or account.pw_gid <= 0 or grp.getgrnam(ATTACH_USER).gr_gid != account.pw_gid:
        fail('必须配置独立的非root账户与同名主组')
    directory = os.path.dirname(CONTROL)
    trusted_directory(directory, 0o755)
    trusted_directory(STATE_ROOT, 0o700)
    prepare_control_socket()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(CONTROL)
    owned_socket = socket_identity(CONTROL)
    try:
        os.chmod(CONTROL, 0o660)
        os.chown(CONTROL, 0, account.pw_gid)
    except OSError:
        server.close()
        unlink_owned_socket(CONTROL, owned_socket)
        raise
    server.listen(4)
    stopping = threading.Event()
    sessions = restore_cleanup_sessions()

    def stop_handler(_signum, _frame):
        stopping.set()
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    # 只回收shell子进程；TAP创建子进程由create_tap_in_ns同步持有与回收。
    server.settimeout(0.5)

    next_sweep = time.monotonic() + SWEEP_SECONDS

    while not stopping.is_set():
        try:
            reap_shell_children()
            reap_raw_children()
            if time.monotonic() >= next_sweep:
                sweep_expired(sessions)
                next_sweep = time.monotonic() + SWEEP_SECONDS
            connection, _ = server.accept()
            connection.settimeout(5.0)
        except OSError:
            continue
        try:
            identity = peer_uid(connection)
            request = json.loads(connection.recv(65536).decode())
            reply = handle_daemon(request, identity, attach_uid, sessions, connection)
            if reply is not None:
                connection.sendall((json.dumps(reply) + '\n').encode())
        except (ValueError, OSError):
            pass
        finally:
            connection.close()
    server.close()
    for session in sorted(sessions):
        teardown_session(session, sessions)
    unlink_owned_socket(CONTROL, owned_socket)


SHELL_CHILDREN = set()
# 受控raw工具子进程归属：{pid: {'session': …, 'deadline': monotonic}}。
# 只跟踪daemon自己fork的孩子；回收与超时终止都在daemon内完成，不触及其他PID。
RAW_CHILDREN = {}


def reap_raw_children():
    """回收raw工具子进程；超过时限先SIGTERM再回收，归属记录随回收删除。"""
    for pid in list(RAW_CHILDREN):
        try:
            reaped, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            reaped = pid
        if reaped:
            del RAW_CHILDREN[pid]
            continue
        if time.monotonic() >= RAW_CHILDREN[pid]['deadline']:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass


def terminate_raw_children(session):
    """撤网前终止该会话名下仍受跟踪的raw工具子进程；回执如实报告残留。"""
    terminated = 0
    for pid, record in list(RAW_CHILDREN.items()):
        if record.get('session') == session:
            try:
                os.kill(pid, signal.SIGTERM)
                terminated += 1
            except OSError:
                pass
    return terminated


def reap_shell_children():
    for pid in list(SHELL_CHILDREN):
        try:
            reaped, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            reaped = pid
        if reaped:
            SHELL_CHILDREN.discard(pid)


def grant_matches(grant, hello):
    fields = ('instance_uuid', 'generation', 'network_id', 'policy_sha256',
              'mac', 'address', 'mtu')
    return (type(hello) is dict and type(hello.get('generation')) is int
            and type(hello.get('mtu')) is int
            and all(key in grant and grant[key] == hello.get(key) for key in fields))


def handle_daemon(request, identity, attach_uid, sessions, connection):
    if type(request) is not dict:
        return {'error': 'invalid-request'}
    action, session = request.get('action'), request.get('session')
    if action != 'status' and not valid_session(session):
        return {'error': 'invalid-session'}
    privileged = identity == 0
    delegated = identity == attach_uid
    if action == 'setup':
        if not privileged:
            return {'error': 'permission-denied'}
        return setup_session(session, request, sessions)
    if action == 'verify':
        if not delegated:
            return {'error': 'permission-denied'}
        entry = sessions.get(session)
        grant = entry['grant'] if entry else load_grant(session)
        if grant is None:
            return {'error': 'session-unknown'}
        if grant.get('cleanup_pending'):
            return {'error': 'cleanup-pending'}
        if grant_expired(grant):
            return {'error': 'session-expired'}
        return {'ok': True, 'grant': grant, 'assistant_sha256': self_digest(),
                'machine_uuid': read_machine_uuid()}
    if action == 'attach':
        if not delegated:
            return {'error': 'permission-denied'}
        entry = sessions.get(session)
        if entry is None:
            return {'error': 'session-unknown'}
        if entry['grant'].get('cleanup_pending'):
            return {'error': 'cleanup-pending'}
        if grant_expired(entry['grant']):
            return {'error': 'session-expired'}
        if not grant_matches(entry['grant'], request.get('hello')):
            return {'error': 'grant-mismatch'}
        connection.sendall((json.dumps({'state': 'attached', 'grant': entry['grant'],
                                        'assistant_sha256': self_digest(),
                                        'machine_uuid': read_machine_uuid()}) + '\n').encode())
        send_descriptor(connection, entry['tap_fd'])
        return None  # FD已移交；连接由client继续用作帧泵（daemon另持生命周期FD）。
    if action == 'shell':
        if not delegated:
            return {'error': 'permission-denied'}
        entry = sessions.get(session)
        if entry is None:
            return {'error': 'session-unknown'}
        if entry['grant'].get('cleanup_pending'):
            return {'error': 'cleanup-pending'}
        if grant_expired(entry['grant']):
            return {'error': 'session-expired'}
        import pwd
        account = pwd.getpwnam(ATTACH_USER)
        try:
            executable, arguments, environment = shell_launch(entry['grant'], account)
        except OSError:
            return {'error': 'shell-identity-unverified'}
        connection.sendall(json.dumps({'state': 'shell-started'}).encode())
        child = os.fork()
        if child == 0:
            try:
                os.dup2(connection.fileno(), 0)
                os.dup2(connection.fileno(), 1)
                os.dup2(connection.fileno(), 2)
                os.execve(executable, arguments, environment)
            except BaseException:
                os._exit(1)
        SHELL_CHILDREN.add(child)
        return None  # 子进程持有连接；daemon父进程继续控制循环。
    if action == 'teardown':
        if not privileged:
            return {'error': 'permission-denied'}
        return teardown_session(session, sessions)
    if action == 'raw':
        # 受控raw工具（设计§4.2）：与shell同级的会话门禁；工具与参数经白名单
        # 严格校验后在会话命名空间内仅以net_raw能力降权执行，无shell介入。
        if not delegated:
            return {'error': 'permission-denied'}
        entry = sessions.get(session)
        if entry is None:
            return {'error': 'session-unknown'}
        if entry['grant'].get('cleanup_pending'):
            return {'error': 'cleanup-pending'}
        if grant_expired(entry['grant']):
            return {'error': 'session-expired'}
        import pwd
        account = pwd.getpwnam(ATTACH_USER)
        try:
            executable, arguments, environment = raw_tool_launch(
                entry['grant'], account, request.get('tool'), request.get('arguments'))
        except (OSError, ValueError):
            return {'error': 'raw-tool-rejected'}
        connection.sendall(json.dumps({'state': 'raw-started'}).encode())
        child = os.fork()
        if child == 0:
            try:
                os.dup2(connection.fileno(), 0)
                os.dup2(connection.fileno(), 1)
                os.dup2(connection.fileno(), 2)
                os.execve(executable, arguments, environment)
            except BaseException:
                os._exit(1)
        RAW_CHILDREN[child] = {'session': session,
                               'deadline': time.monotonic() + RAW_TOOL_MAX_SECONDS}
        return None  # 子进程持有连接；daemon父进程继续控制循环并跟踪归属。
    if action == 'status':
        if not (privileged or delegated):
            return {'error': 'permission-denied'}
        report = []
        for name, entry in sorted(sessions.items()):
            report.append({'session': name, 'expires': entry['grant']['expires'],
                           'tap_fd_alive': entry.get('tap_fd') is not None,
                           'netns': entry['grant']['netns'],
                           'raw_tools': sum(1 for record in RAW_CHILDREN.values()
                                            if record.get('session') == name),
                           'cleanup_pending': bool(entry['grant'].get('cleanup_pending'))})
        return {'state': 'status', 'sessions': report,
                'note': 'TAP生命周期FD由daemon持有；client副本随进程退出关闭，不等于已撤网。'
                        '受控raw工具子进程由daemon跟踪归属并在撤网时终止。'}
    return {'error': 'unknown-action'}


def setup_session(session, request, sessions):
    mac = str(request.get('mac', '')).lower()
    address, prefix, mtu = request.get('address'), request.get('prefix'), request.get('mtu')
    if not valid_mac(mac) or type(prefix) is not int or not 16 <= prefix <= 30 or mtu != 1400:
        return {'error': 'invalid-parameters'}
    if session in sessions or os.path.lexists(os.path.join(STATE_ROOT, session + '.json')):
        return {'error': 'session-exists'}
    try:
        chosen = ipaddress_check(address)
    except ValueError:
        return {'error': 'invalid-address'}
    mask = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF
    if int(chosen) & mask == 0 or int(chosen) & ~mask & 0xFFFFFFFF == ~mask & 0xFFFFFFFF:
        return {'error': 'invalid-address'}
    approved = request.get('binding')
    if (type(approved) is not dict or set(approved) !=
            {'instance_uuid', 'generation', 'network_id', 'policy_sha256'}
            or not valid_session(approved.get('instance_uuid'))
            or type(approved.get('generation')) is not int or approved['generation'] < 1
            or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}', str(approved.get('network_id', '')))
            or not re.fullmatch(r'[0-9a-f]{64}', str(approved.get('policy_sha256', '')))):
        return {'error': 'invalid-binding'}
    ns, tap = netns_name(session), tap_name(session)
    if os.path.exists('/run/netns/' + ns):
        return {'error': 'namespace-exists'}
    grant = {'session': session, 'netns': ns, 'tap': tap, 'mac': mac,
             'address': str(chosen), 'prefix': prefix, 'mtu': mtu,
             'expires': time.strftime('%Y-%m-%dT%H:%M:%SZ',
                                      time.gmtime(time.time() + SESSION_HOURS * 3600)),
             'cleanup_pending': True}
    grant.update(approved)
    sessions[session] = {'grant': grant, 'tap_fd': None}
    try:
        save_cleanup_grant(grant)
    except OSError:
        sessions.pop(session, None)
        return {'error': 'grant-write-failed'}
    if run(['ip', 'netns', 'add', ns]) != 0:
        return {'error': 'netns-failed', 'cleanup': teardown_session(session, sessions)}
    descriptor = create_tap_in_ns(ns, tap)
    if descriptor is None:
        return {'error': 'tap-failed', 'cleanup': teardown_session(session, sessions)}
    sessions[session]['tap_fd'] = descriptor
    steps = ([['ip', '-n', ns, 'link', 'set', 'lo', 'up'],
              ['ip', '-n', ns, 'link', 'set', tap, 'address', mac],
              ['ip', '-n', ns, 'link', 'set', tap, 'mtu', str(mtu)],
              ['ip', '-n', ns, 'addr', 'add', '%s/%d' % (chosen, prefix), 'dev', tap],
              ['ip', '-n', ns, 'link', 'set', tap, 'up']])
    if any(run(step) != 0 for step in steps):
        return {'error': 'configure-failed', 'cleanup': teardown_session(session, sessions)}
    grant.pop('cleanup_pending', None)
    try:
        save_cleanup_grant(grant)
    except OSError:
        return {'error': 'grant-write-failed', 'cleanup': teardown_session(session, sessions)}
    return {'state': 'session-created', 'grant': grant}


def ipaddress_check(address):
    import ipaddress
    return ipaddress.IPv4Address(address)


# ---------- client ----------

def pump_frames(grant, tap_fd, stdin):
    """帧泵：宿主记录流 <-> TAP。双向序号各自单调；心跳忽略；超额/过期即退出。"""
    sequence_out = 1  # 身份应答已消费序号0
    expected_in = 1  # 握手HELLO已消费序号0
    expires = time.mktime(time.strptime(grant['expires'], '%Y-%m-%dT%H:%M:%SZ')) - time.timezone
    transferred = 0
    try:
        while True:
            readable, _, _ = select.select([tap_fd, stdin], [], [], 5.0)
            if time.time() > expires or transferred > SESSION_QUOTA_BYTES:
                send_record(sys.stdout.buffer, RECORD_CLOSE, sequence_out, b'expired')
                sequence_out += 1
                break
            if tap_fd in readable:
                frame = os.read(tap_fd, MAX_FRAME)
                if not frame:
                    break
                send_record(sys.stdout.buffer, RECORD_FRAME, sequence_out, frame)
                sequence_out += 1
                transferred += len(frame)
                sys.stdout.buffer.flush()
            if stdin in readable:
                record = read_record_checked(stdin, expected_in)
                if record is None:
                    break  # 序号异常/流结束：断开，不重放
                expected_in += 1
                kind, _sequence, payload = record
                if kind == RECORD_FRAME:
                    if len(payload) >= 14:
                        os.write(tap_fd, payload)
                        transferred += len(payload)
                elif kind == RECORD_CLOSE:
                    break
                elif kind == RECORD_HEARTBEAT:
                    send_record(sys.stdout.buffer, RECORD_HEARTBEAT, sequence_out)
                    sequence_out += 1
                    sys.stdout.buffer.flush()
    finally:
        try:
            os.close(tap_fd)
        except OSError:
            pass


def attach_client():
    """SSH固定入口：HELLO握手→daemon核验→应答身份→移交TAP FD→帧泵。"""
    # select观察底层FD：禁止BufferedReader预读并隐藏后续完整记录。
    stdin = getattr(sys.stdin.buffer, 'raw', sys.stdin.buffer)
    hello = read_record_checked(stdin, 0)
    if hello is None or hello[0] != RECORD_CONTROL:
        fail('缺少握手记录')
    try:
        request = json.loads(hello[2].decode())
    except ValueError:
        fail('握手记录无效')
    if request.get('handshake') != HANDSHAKE_HOST or not valid_session(request.get('session_uuid')):
        fail('握手目标无效')
    session, challenge = request['session_uuid'], request.get('challenge', '')
    if not re.fullmatch(r'[0-9a-f]{32}', challenge):
        fail('挑战无效')
    connection = control_connection()
    try:
        connection.sendall(json.dumps({'action': 'attach', 'session': session,
                                       'hello': request}).encode())
        attach_reply = bytearray()
        while len(attach_reply) <= 65536:
            chunk = connection.recv(1)  # 不越过JSON边界消费SCM_RIGHTS携带字节。
            if not chunk:
                fail('助手响应中断')
            if chunk == b'\n':
                break
            attach_reply.extend(chunk)
        else:
            fail('助手响应过长')
        verdict = json.loads(attach_reply.decode())
        if verdict.get('state') != 'attached':
            fail(verdict.get('error', 'attach失败'))
        descriptor = receive_descriptor(connection)
        grant = verdict
        reply = {'handshake': HANDSHAKE_GUEST, 'session_uuid': session,
                 'challenge_echo': challenge,
                 'assistant_sha256': verdict.get('assistant_sha256'),
                 'machine_uuid': verdict.get('machine_uuid')}
        try:
            send_record(sys.stdout.buffer, RECORD_CONTROL, 0, json.dumps(reply).encode())
            sys.stdout.buffer.flush()
        except BaseException:
            os.close(descriptor)
            raise

    finally:
        connection.close()
    pump_frames(grant['grant'], descriptor, stdin)


def control_connection():
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        trusted_path(os.path.dirname(CONTROL), directory=True)
        connection.settimeout(5)
        connection.connect(CONTROL)
        if peer_uid(connection) != 0:
            raise OSError('control-peer-not-root')
    except OSError:
        connection.close()
        fail('助手控制通道不可达或对端身份未核验')
    return connection


def shell_client(session):
    connection = control_connection()
    try:
        connection.sendall(json.dumps({'action': 'shell', 'session': session}).encode())
        reply = connection.recv(65536).decode()
        if '"shell-started"' not in reply:
            fail(reply.strip() or 'shell启动失败')
        # 双向代理：用户stdin <-> daemon侧降权shell
        while True:
            readable, _, _ = select.select([sys.stdin.buffer, connection], [], [])
            if sys.stdin.buffer in readable:
                data = sys.stdin.buffer.read1(65536) if hasattr(sys.stdin.buffer, 'read1') \
                    else sys.stdin.buffer.read(1)
                if not data:
                    break
                connection.sendall(data)
            if connection in readable:
                data = connection.recv(65536)
                if not data:
                    break
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
    finally:
        connection.close()


def raw_client(session, tool, arguments):
    """受控raw工具入口：请求经daemon白名单校验后单向代理工具输出。

    与shell相同的选择语义（会话在请求中）；工具失败与拒绝都以错误回复返回，
    不进入代理循环。输入输出直连工具进程，无shell解释层。
    """
    connection = control_connection()
    try:
        request = {'action': 'raw', 'session': session, 'tool': tool,
                   'arguments': list(arguments)}
        connection.sendall(json.dumps(request).encode())
        reply = connection.recv(65536).decode()
        if '"raw-started"' not in reply:
            fail(reply.strip() or 'raw工具启动失败')
        while True:
            readable, _, _ = select.select([sys.stdin.buffer, connection], [], [])
            if sys.stdin.buffer in readable:
                data = sys.stdin.buffer.read1(65536) if hasattr(sys.stdin.buffer, 'read1') \
                    else sys.stdin.buffer.read(1)
                if not data:
                    break
                connection.sendall(data)
            if connection in readable:
                data = connection.recv(65536)
                if not data:
                    break
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
    finally:
        connection.close()


def client():
    if os.geteuid() == 0:
        fail('client不得以root运行')
    # 不能用REMAINDER位置参数：它会贪婪吞掉后续--session/--tool；
    # parse_known_args让未知token（工具旗标/目标）落入extra。
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('action', choices=('attach', 'shell', 'raw'))
    parser.add_argument('--session', default='')
    parser.add_argument('--tool', default='')
    arguments, extra = parser.parse_known_args()
    if arguments.action == 'attach':
        if arguments.session:
            fail('会话由宿主握手选择；attach不接受会话参数')
        attach_client()
        return
    if not valid_session(arguments.session):
        fail('会话标识无效')
    if arguments.action == 'raw':
        tool_arguments = [item for item in extra if item != '--']
        raw_client(arguments.session, arguments.tool, tool_arguments)
        return
    shell_client(arguments.session)


def privileged_client():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('action', choices=('setup', 'teardown', 'status'))
    parser.add_argument('--session', default='')
    parser.add_argument('--mac', default='')
    parser.add_argument('--address', default='')
    parser.add_argument('--prefix', type=int, default=0)
    parser.add_argument('--mtu', type=int, default=0)
    parser.add_argument('--instance-uuid')
    parser.add_argument('--generation', type=int)
    parser.add_argument('--network-id')
    parser.add_argument('--policy-sha256')
    arguments = parser.parse_args()
    request = {'action': arguments.action, 'session': arguments.session}
    if arguments.action == 'setup':
        request.update(mac=arguments.mac, address=arguments.address,
                       prefix=arguments.prefix, mtu=arguments.mtu,
                       binding={'instance_uuid': arguments.instance_uuid,
                                'generation': arguments.generation, 'network_id': arguments.network_id,
                                'policy_sha256': arguments.policy_sha256})
    connection = control_connection()
    try:
        connection.sendall(json.dumps(request).encode())
        reply = connection.recv(65536)
    except OSError:
        fail('助手控制通道不可达')
    finally:
        connection.close()
    print(reply.decode())
    result = json.loads(reply)
    if result.get('error') or result.get('state') == 'cleanup-incomplete':
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        report = verify_installation()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        fail('助手安装核验失败：' + str(error))
    if sys.argv[1:] == ['verify-install']:
        print(json.dumps(report))
        raise SystemExit(0)
    if os.path.basename(sys.argv[0]) == @DAEMON_NAME@ or '--daemon' in sys.argv:
        daemon()
    elif os.geteuid() == 0:
        privileged_client()
    else:
        client()
'''


INSTALL_GUIDE = '''# 外部Kali助手安装说明（独立部署动作，不属于"连接"按钮）

本目录材料只生成，不安装。安装需要在目标 Kali 内由管理员执行并自行复核；
CTFLab 不修改现有 Kali 的网络、账户或权限。

1. 核对助手摘要：`sha256sum ctflab-kali-attach` 应与 manifest.json 一致。
2. 在宿主登记持久批准：`ctflab external-attach approve --registration <登记JSON>
   --materials-manifest <材料目录>/manifest.json` 把登记的助手摘要与本机材料
   清单绑定写入用户私有批准账本。同节点连接前宿主按账本核验摘要；清单变化
   或更换机器须重新批准。
3. 创建专用账户——**必须使用可用登录 shell**（sshd 的 ForceCommand 经该
   shell 以 `-c` 执行，`/usr/sbin/nologin` 会导致固定入口无法运行）：
   `useradd --system --shell /bin/sh ctflab-attach`。
4. 安装：`install -o root -g root -m 0755 ctflab-kali-attach /usr/local/bin/`，
   并使 `/usr/local/bin/ctflab-kali-attachd` 指向同一文件。
5. 以 root 启动守护进程（材料含 systemd 示例单元）；确认
   `/run/ctflab-attach/control.sock` 属主 `root:ctflab-attach`、模式 0660。
6. SSH 受限入口：安装 sshd 片段材料（固定 ForceCommand、显式禁止端口转发/
   代理/X11/隧道）。会话不由命令行参数选择：宿主经数据面 HELLO 握手传递会话
   UUID 与一次性挑战，助手向守护进程核验后应答身份（助手摘要、机器UUID；
   DMI 不可读时上报 null，宿主拒绝未批准的替代身份，不自动降级）。
7. 会话创建（root）：连接前在 Kali 执行 CTFLab 界面显示的固定 setup 命令；
   实验终端入口为 `ctflab-kali-attach shell --session <会话标识>`（双向输入输出，
   在专用命名空间内降权运行）。普通桌面程序不进入实验网络。
8. 受控raw工具（需要原始套接字的探测）：普通shell没有原始套接字能力；
   需要时用 `ctflab-kali-attach raw --session <会话标识> --tool <工具> -- <参数>`
   （如 `--tool ping -- -c 4 10.80.0.10`）。工具白名单与参数边界在助手内固定，
   仅授予 CAP_NET_RAW，在会话命名空间内以专用账户运行；白名单外工具、网段外
   目标或未知旗标一律拒绝，不提供任意 sudo 或 shell 包装。首版白名单只含
   ping（已真实内核验收）；Kali 的 nmap 因自带文件能力在 no_new_privs 下被
   内核拒绝执行（EPERM），SYN/UDP 扫描须待专用无 filecap 工具另行测试后
   再声明。
9. 撤网命令须核对JSON回执及退出码：只有 `session-closed` 且 `leftover=[]`
7. 撤网命令须核对JSON回执及退出码：只有 `session-closed` 且 `leftover=[]`
   表示本次清理完成。`cleanup-incomplete` 以非零退出，保留恢复记录；先退出
   会话内工具，再重复同一 teardown 命令。命名空间查询失败、TAP残留、额外网卡
   或工具进程残留均不会被解释成已撤网，也不自动杀进程。
   助手重启后的已有授权只用于撤网；不会重建TAP或恢复帧连接，须清理后重新批准。

安全边界：daemon 只提供登记会话的建立/核验/移交/降权shell/关闭与租约回收，
不提供任意命令、任意 setns 或任意宿主 PID 参数；TAP 生命周期 FD 由 daemon
持有并按租约（默认2小时）自动回收，客户端副本随进程退出关闭——客户端断开
不等于已撤网，残留以 `status` 为准。真实内核行为（TAP 创建、命名空间隔离、
异常清理、原管理网保全）以实机验收为准。
'''


SSHD_SNIPPET = '''# /etc/ssh/sshd_config.d/ctflab-attach.conf（管理员手动安装）
# 固定入口只承载帧传输与降权shell；会话经数据面握手选择，命令行不带会话参数。
Match User {user}
    ForceCommand /usr/local/bin/ctflab-kali-attach attach
    PermitTTY no
    X11Forwarding no
    AllowTcpForwarding no
    AllowAgentForwarding no
    PermitTunnel no
    GatewayPorts no
'''


SYSTEMD_UNIT = '''[Unit]
Description=CTFLab external attach assistant daemon
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -I /usr/local/bin/ctflab-kali-attachd
Restart=on-failure
User=root
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
'''


def render_assistant(*, user=DEFAULT_USER, control=CONTROL_SOCKET, state=STATE_ROOT):
    replacements = {'@CONTROL@': repr(control), '@STATE@': repr(state), '@USER@': repr(user),
                    '@MAX_FRAME@': str(MAX_FRAME), '@HOURS@': str(SESSION_HOURS),
                    '@QUOTA@': str(SESSION_QUOTA_BYTES), '@DAEMON_NAME@': repr(DAEMON_NAME)}
    result = ASSISTANT_SCRIPT
    for marker, value in replacements.items():
        result = result.replace(marker, value)
    require(all(marker not in result for marker in replacements), 'render-error')
    return result


def materials(destination, *, user=DEFAULT_USER, control=CONTROL_SOCKET, state=STATE_ROOT, prepared=None):
    """只写指定新目录内的材料文件；目录已存在即失败，不覆盖任何文件。"""
    target = Path(destination).absolute()
    require(not target.exists() and not target.is_symlink(), 'state-conflict')
    target.mkdir(parents=True, mode=0o700)
    files = {}
    assistant = render_assistant(user=user, control=control, state=state)
    (target / ASSISTANT_NAME).write_text(assistant, encoding='utf-8')
    os.chmod(target / ASSISTANT_NAME, 0o755)
    files[ASSISTANT_NAME] = hashlib.sha256(assistant.encode()).hexdigest()
    written = {'sshd-ctflab-attach.conf': SSHD_SNIPPET.format(user=user),
               'ctflab-attachd.service': SYSTEMD_UNIT, 'INSTALL.md': INSTALL_GUIDE}
    for name, content in written.items():
        (target / name).write_text(content, encoding='utf-8')
        files[name] = hashlib.sha256(content.encode()).hexdigest()
    manifest = {'schema': 1, 'kind': 'ctflab-kali-attach-materials',
                'guest_protocol': 'ctflab-external-l2-v1', 'files': files,
                'generated_for_user': user,
                'note': 'materials-only；真实内核与平台行为需实机验收'}
    if prepared is not None:
        manifest['prepared'] = prepared
    (target / 'manifest.json').write_text(canonical(manifest) + '\n', encoding='utf-8')
    return manifest


def setup_command(session_uuid, mac, address, prefix, *, user=DEFAULT_USER):
    """UI展示的固定 setup 命令；参数全部来自已校验的接入计划。"""
    require(type(session_uuid) is str and re.fullmatch(SESSION_PATTERN, session_uuid) is not None,
            'invalid-request')
    require(re.fullmatch(MAC_PATTERN, mac.lower()) is not None, 'invalid-request')
    require(type(address) is str and type(prefix) is int and 16 <= prefix <= 30,
            'invalid-request')
    return (f'sudo {ASSISTANT_NAME} setup --session {session_uuid} '
            f'--mac {mac.lower()} --address {address} --prefix {prefix} --mtu 1400')


def shell_command(session_uuid, *, user=DEFAULT_USER):
    require(type(session_uuid) is str and re.fullmatch(SESSION_PATTERN, session_uuid) is not None,
            'invalid-request')
    return f'{ASSISTANT_NAME} shell --session {session_uuid}'


def raw_command(session_uuid, tool, arguments=(), *, user=DEFAULT_USER):
    """UI展示的受控raw工具固定命令；工具须在白名单内，参数逐个shell转义。"""
    require(type(session_uuid) is str and re.fullmatch(SESSION_PATTERN, session_uuid) is not None,
            'invalid-request')
    require(type(tool) is str and tool in RAW_TOOL_NAMES, 'invalid-request')
    require(type(arguments) in (list, tuple)
            and all(type(item) is str and item for item in arguments)
            and len(arguments) <= RAW_TOOL_ARGUMENT_LIMIT, 'invalid-request')
    quoted = ' '.join(shlex.quote(item) for item in arguments)
    command = f'{ASSISTANT_NAME} raw --session {session_uuid} --tool {tool}'
    return command + (' -- ' + quoted if quoted else '')


def teardown_command(session_uuid):
    require(type(session_uuid) is str and re.fullmatch(SESSION_PATTERN, session_uuid) is not None,
            'invalid-request')
    return f'sudo {ASSISTANT_NAME} teardown --session {session_uuid}'
