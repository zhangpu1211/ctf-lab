"""仅回环双向TLS端点；每实例独立CA，私钥只写私有状态根，不安装系统信任。"""
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import socket
import ssl
import stat
import uuid

from ctflab_generation_store import private_directory
from ctflab_local_service import _guard_path, _windows_storage

CERT_FILES = ('ca-cert.pem', 'server-cert.pem', 'server-key.pem', 'client-cert.pem', 'client-key.pem')


def guard(path):
    path = Path(path).absolute()
    _guard_path(path)
    info = path.stat()
    if os.name == 'nt':
        _windows_storage(path, root=path.is_dir())
    elif info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('私有文件权限不符')
    return path


def provision(path, instance_uuid):
    """仅证书生成依赖cryptography；运行连接使用Python ssl。CA私钥不落盘。"""
    if str(uuid.UUID(instance_uuid)) != instance_uuid:
        raise ValueError('实例ID无效')
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    path = Path(path).absolute()
    guard(path.parent)
    private_directory(path)
    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'ctflab-ca-' + instance_uuid)])
    def base(subject, key):
        return (x509.CertificateBuilder().subject_name(subject).issuer_name(ca_name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
                .not_valid_after(now+timedelta(days=30)))
    ca = (base(ca_name, ca_key).add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, None, None), critical=True)
          .sign(ca_key, hashes.SHA256()))
    payloads = {'ca-cert.pem': ca.public_bytes(serialization.Encoding.PEM)}
    for role, purpose in [('server', ExtendedKeyUsageOID.SERVER_AUTH), ('client', ExtendedKeyUsageOID.CLIENT_AUTH)]:
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'ctflab-' + role + '-' + instance_uuid)])
        cert = (base(name, key).add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, None, None), critical=True)
                .add_extension(x509.ExtendedKeyUsage([purpose]), critical=False))
        if role == 'server':
            import ipaddress
            cert = cert.add_extension(x509.SubjectAlternativeName([
                x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
        cert = cert.sign(ca_key, hashes.SHA256())
        payloads[role+'-cert.pem'] = cert.public_bytes(serialization.Encoding.PEM)
        payloads[role+'-key.pem'] = key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    for name, raw in payloads.items():
        fd = os.open(path/name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        guard(path/name)
    return fingerprints(path)


def fingerprints(path):
    guard(path)
    return {name: hashlib.sha256(guard(Path(path)/name).read_bytes()).hexdigest() for name in CERT_FILES}


def certificate_status(path, expected, *, now=None):
    """只读到期检查；续期通过确认停机后的新启动材料完成，禁止在线替换密钥。"""
    from cryptography import x509
    if fingerprints(path) != expected:
        raise ValueError('证书材料与实例绑定不符')
    now = datetime.now(timezone.utc) if now is None else now
    if now.tzinfo is None: raise ValueError('检查时间必须带时区')
    entries = {}
    for name in ('ca-cert.pem', 'server-cert.pem', 'client-cert.pem'):
        cert = x509.load_pem_x509_certificate(guard(Path(path)/name).read_bytes())
        begin, end = cert.not_valid_before_utc, cert.not_valid_after_utc
        entries[name] = {'not_before': begin.isoformat(), 'not_after': end.isoformat(),
                         'remaining_seconds': int((end-now).total_seconds()), 'valid': begin <= now < end}
    if fingerprints(path) != expected:
        raise ValueError('检查期间证书材料发生变化')
    remaining = min(v['remaining_seconds'] for v in entries.values())
    valid = all(v['valid'] for v in entries.values())
    return {'state': ('valid' if remaining > 7*86400 else 'renewal-due') if valid else 'invalid',
            'valid': valid, 'certificates': entries,
            'renewal': 'confirmed-stop-then-start-new-attempt', 'online_replacement': False,
            'automatic_stop': False}


def client_context(path, expected):
    if fingerprints(path) != expected:
        raise ValueError('证书材料与实例绑定不符')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cafile=str(Path(path)/'ca-cert.pem'))
    context.load_cert_chain(str(Path(path)/'client-cert.pem'), str(Path(path)/'client-key.pem'))
    return context


def wrap_client(raw, path, expected):
    try:
        secure = client_context(path, expected).wrap_socket(raw, server_hostname='localhost')
        pem = (Path(path)/'server-cert.pem').read_text(encoding='ascii')
        expected_der = ssl.PEM_cert_to_DER_cert(pem)
        if hashlib.sha256(secure.getpeercert(binary_form=True)).digest() != hashlib.sha256(expected_der).digest():
            secure.close()
            raise ValueError('服务端证书不属于该实例')
        return secure
    except BaseException:
        raw.close()
        raise


def tcp(port, timeout=5):
    if type(port) is not int or not 1024 <= port <= 65535 or not 0 < timeout <= 60:
        raise ValueError('端口或超时无效')
    # 地址固定；任何配置都不能改成LAN或默认全接口监听。
    return socket.create_connection(('127.0.0.1', port), timeout=timeout)


def server_arguments(path, instance_uuid):
    path = str(Path(path).absolute()).replace(',', ',,')
    if str(uuid.UUID(instance_uuid)) != instance_uuid:
        raise ValueError('实例ID无效')
    return ['-object', f'tls-creds-x509,id=ctflab-tls,endpoint=server,dir={path},verify-peer=yes',
            '-object', f'authz-simple,id=ctflab-client,identity=CN=ctflab-client-{instance_uuid}']
