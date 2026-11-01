"""远程分块上传进入既有签名内容缓存；未完成内容不进入objects或实例。

缓存索引/信任根由服务器操作者预先管理，不从上传请求接受密钥、许可或路径。
"""
import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from ctflab_contract import require, identifier, uuid_text, integer, canonical
from ctflab_content_cache import ContentCache, checksum, source_url
from ctflab_generation_store import private_directory
from ctflab_runtime_inventory import check_path, hash_file
from ctflab_tls_endpoint import guard
from ctflab_local_service import _guard_path

CHUNK = 32768
SCHEMA = '''CREATE TABLE remote_uploads(
 id TEXT PRIMARY KEY,principal TEXT NOT NULL,sha TEXT NOT NULL,size INTEGER NOT NULL,
 source TEXT NOT NULL,audience TEXT NOT NULL,state TEXT NOT NULL,received INTEGER NOT NULL);
'''


def validate_settings(value):
    require(type(value) is dict and set(value) == {'cache_root', 'sources', 'quota_bytes', 'max_uploads'})
    require(isinstance(value['cache_root'], str) and Path(value['cache_root']).is_absolute())
    require(type(value['sources']) is list and 1 <= len(value['sources']) <= 8)
    require(len(set(value['sources'])) == len(value['sources']))
    for source in value['sources']: source_url(source)
    require(type(value['quota_bytes']) is int and 1 <= value['quota_bytes'] <= 1024**4)
    require(type(value['max_uploads']) is int and 1 <= value['max_uploads'] <= 4096)
    return value


def initialize(root):
    cache = ContentCache(root)
    with cache.locked() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='remote_uploads'").fetchone()
        directory = cache.root/'uploads'
        if exists:
            guard(directory)
            return {'state': 'already-initialized', 'automatic_cleanup': False}
        if directory.exists():
            guard(directory); require(not list(directory.iterdir()), 'identity-unknown')
        else: private_directory(directory)
        db.execute(SCHEMA)
    return {'state': 'initialized', 'automatic_cleanup': False}


class RemoteUploads:
    def __init__(self, settings, principal, role, *, now=None):
        self.settings = validate_settings(settings)
        identifier(principal); require(role in ('student', 'teacher', 'administrator'))
        self.principal, self.role = principal, role
        self.cache = ContentCache(settings['cache_root'])
        guard(self.cache.root/'uploads')
        self.now = now or (lambda: datetime.now(timezone.utc))

    def asset(self, db, source, sha, audience):
        checksum(sha); require(source in self.settings['sources'], 'permission-denied')
        require(audience in ('student', 'teacher') and (audience == 'student' or self.role != 'student'), 'permission-denied')
        row = db.execute('SELECT payload FROM indexes WHERE source=?', (source,)).fetchone()
        require(row is not None, 'permission-denied')
        index = json.loads(row[0]); asset = index['assets'].get(sha)
        require(asset is not None and asset['redistribution'] == 'allowed' and asset['audience'] == audience, 'permission-denied')
        expiry = datetime.fromisoformat(index['expires'].replace('Z', '+00:00'))
        require(expiry > self.now(), 'state-conflict')
        return asset

    def row(self, db, upload):
        uuid_text(upload)
        row = db.execute('SELECT id,principal,sha,size,source,audience,state,received FROM remote_uploads WHERE id=?', (upload,)).fetchone()
        require(row is not None and row[1] == self.principal, 'permission-denied')
        value = dict(zip(('id','principal','sha','size','source','audience','state','received'), row))
        asset = self.asset(db, value['source'], value['sha'], value['audience'])
        require(asset['size'] == value['size'], 'state-conflict')
        return value

    def path(self, upload):
        uuid_text(upload)
        guard(self.cache.root/'uploads')
        path = self.cache.root/'uploads'/upload
        _guard_path(path)
        return path

    def verified_object(self, sha, size):
        path = self.cache.root/'objects'/checksum(sha); guard(path)
        info = check_path(path)
        require(path.is_file() and info.st_nlink == 1 and info.st_size == size and hash_file(path, info) == sha, 'state-conflict')
        return path

    def begin(self, upload, source, sha, audience):
        uuid_text(upload)
        with self.cache.locked() as db:
            asset = self.asset(db, source, sha, audience)
            old = db.execute('SELECT 1 FROM remote_uploads WHERE id=?', (upload,)).fetchone()
            if old:
                row = self.row(db, upload)
                require((row['source'], row['sha'], row['audience']) == (source, sha, audience), 'idempotency-conflict')
                if row['state'] == 'verified': self.verified_object(row['sha'], row['size'])
                return self.summary(row)
            reserved, count = db.execute('SELECT COALESCE(SUM(size),0),COUNT(*) FROM remote_uploads WHERE principal=?',
                                         (self.principal,)).fetchone()
            require(reserved+asset['size'] <= self.settings['quota_bytes'] and count < self.settings['max_uploads'], 'storage-insufficient')
            pending = db.execute("SELECT COALESCE(SUM(size-received),0) FROM remote_uploads WHERE state='uploading'").fetchone()[0]
            require(shutil.disk_usage(self.cache.root).free >= asset['size']+pending+16*1024**2, 'storage-insufficient')
            final = self.cache.root/'objects'/sha
            _guard_path(final)
            cached = final.exists()
            if cached:
                self.verified_object(sha, asset['size'])
                db.execute('INSERT OR IGNORE INTO refs VALUES(?,?)', ('remote-upload-'+upload, sha))
            else:
                self.cache.admit(db, asset['size'])
                # 事务失败仍保留孤立文件；同ID绝不覆盖。操作者可只读调查，不自动清除。
                fd = os.open(self.path(upload), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.close(fd)
            db.execute('INSERT INTO remote_uploads VALUES(?,?,?,?,?,?,?,?)',
                       (upload, self.principal, sha, asset['size'], source, audience,
                        'verified' if cached else 'uploading', asset['size'] if cached else 0))
            return self.summary(self.row(db, upload))

    @staticmethod
    def summary(row):
        return {'upload_id': row['id'], 'sha256': row['sha'], 'size': row['size'],
                'received': row['received'], 'state': row['state'], 'chunk_bytes': CHUNK,
                'executable': False, 'automatic_cleanup': False}

    def status(self, upload):
        with self.cache.locked() as db:
            row = self.row(db, upload)
            if row['state'] == 'verified': self.verified_object(row['sha'], row['size'])
            else:
                path = self.path(upload)
                if not path.exists():
                    require(row['received'] == row['size'] and db.execute('SELECT 1 FROM refs WHERE owner=? AND sha=?',
                            ('remote-upload-'+upload,row['sha'])).fetchone(), 'identity-unknown')
                    self.verified_object(row['sha'], row['size'])
                    return dict(self.summary(row), promotion_pending=True)
                guard(path); info = check_path(path)
                require(path.is_file() and info.st_nlink == 1 and row['received'] <= info.st_size <= row['size'], 'state-conflict')
            return self.summary(row)

    def chunk(self, upload, offset, encoded):
        integer(offset)
        require(isinstance(encoded, str) and 0 < len(encoded) <= 4*((CHUNK+2)//3))
        try: block = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError): require(False)
        require(0 < len(block) <= CHUNK)
        with self.cache.locked() as db:
            row = self.row(db, upload)
            require(row['state'] == 'uploading' and offset <= row['received'] and offset+len(block) <= row['size'], 'state-conflict')
            path = guard(self.path(upload)); info = check_path(path)
            require(path.is_file() and info.st_nlink == 1 and row['received'] <= info.st_size <= row['size'], 'state-conflict')
            # begin已预约整份文件；分块写入只把预约变成载荷，不增加承诺总量。
            # 不逐32KiB重复扫描整个公共缓存；外部写入不受本准入预算控制。
            end = offset+len(block)
            if offset < row['received']:
                require(end <= row['received'], 'state-conflict')
                with path.open('rb') as stream:
                    stream.seek(offset); require(stream.read(len(block)) == block, 'idempotency-conflict')
                return self.summary(row)
            # 文件先于SQLite提交的中断：仅核对并补完同offset/同内容前缀，不猜测新字节。
            require(info.st_size <= end, 'state-conflict')
            require(shutil.disk_usage(self.cache.root).free >= end-info.st_size+16*1024**2, 'storage-insufficient')
            with path.open('r+b', buffering=0) as stream:
                opened = os.fstat(stream.fileno())
                require((opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino) and opened.st_nlink == 1, 'identity-unknown')
                stream.seek(offset); existing = stream.read(info.st_size-offset)
                require(existing == block[:len(existing)], 'idempotency-conflict')
                stream.seek(info.st_size); remaining = memoryview(block)[len(existing):]
                while remaining:
                    written = stream.write(remaining); require(bool(written), 'persistence-failed'); remaining = remaining[written:]
                os.fsync(stream.fileno())
            db.execute('UPDATE remote_uploads SET received=? WHERE id=?', (end, upload))
            row['received'] = end
            return self.summary(row)

    def finish(self, upload):
        # 先持久引用，再公布对象；重命名和SQLite之间中断也不会被GC当作无主对象删除。
        with self.cache.locked() as db:
            row = self.row(db, upload)
            if row['state'] == 'verified':
                self.verified_object(row['sha'], row['size']); return self.summary(row)
            require(row['state'] == 'uploading' and row['received'] == row['size'], 'state-conflict')
            path = self.path(upload); final = self.cache.root/'objects'/row['sha']
            _guard_path(final)
            if path.exists():
                guard(path); info = check_path(path)
                require(path.is_file() and info.st_nlink == 1 and info.st_size == row['size'], 'state-conflict')
                if hash_file(path, info) != row['sha']:
                    db.execute("UPDATE remote_uploads SET state='corrupt' WHERE id=?", (upload,))
                    return dict(self.summary(row), state='corrupt')
            else: self.verified_object(row['sha'], row['size'])
            db.execute('INSERT OR IGNORE INTO refs VALUES(?,?)', ('remote-upload-'+upload, row['sha']))
        with self.cache.locked() as db:
            row = self.row(db, upload)
            require(row['state'] == 'uploading', 'state-conflict')
            path = self.path(upload); final = self.cache.root/'objects'/row['sha']
            _guard_path(final)
            if final.exists(): self.verified_object(row['sha'], row['size'])
            else:
                guard(path); info = check_path(path)
                require(info.st_nlink == 1 and info.st_size == row['size'] and hash_file(path, info) == row['sha'], 'state-conflict')
                path.rename(final)
            self.verified_object(row['sha'], row['size'])
            db.execute("UPDATE remote_uploads SET state='verified' WHERE id=?", (upload,))
            row['state'] = 'verified'
            return self.summary(row)

    def handle(self, action, parameters):
        fields = {'asset-begin': {'upload_id','source','sha256','audience'},
                  'asset-status': {'upload_id'}, 'asset-chunk': {'upload_id','offset','data'},
                  'asset-finish': {'upload_id'}}
        require(action in fields and type(parameters) is dict and set(parameters) == fields[action])
        if action == 'asset-begin': return self.begin(parameters['upload_id'], parameters['source'], parameters['sha256'], parameters['audience'])
        if action == 'asset-chunk': return self.chunk(parameters['upload_id'], parameters['offset'], parameters['data'])
        return getattr(self, 'status' if action == 'asset-status' else 'finish')(parameters['upload_id'])


def upload_file(config, path, source, audience, upload, *, session_factory=None,hash_file_func=None,cancel_requested=None,on_progress=None):
    """明确选择文件后上传；ID必须由操作者保留，断线后显式用相同ID继续。"""
    from ctflab_remote import SSHSession
    session_factory = session_factory or SSHSession
    uuid_text(upload); source_url(source)
    require(audience in ('student', 'teacher'))
    path = Path(path).absolute(); info = check_path(path)
    require(path.is_file() and info.st_nlink == 1 and 0 < info.st_size <= 1024**4)
    hasher=hash_file_func or hash_file
    def cancelled():require(not (cancel_requested and cancel_requested()),'operation-finished')
    cancelled();sha = hasher(path, info)
    def validate(result):
        require(type(result) is dict and result.get('upload_id') == upload and result.get('sha256') == sha
                and result.get('size') == info.st_size, 'identity-unknown')
        require(type(result.get('received')) is int and 0 <= result['received'] <= info.st_size)
        require(type(result.get('size')) is int and result.get('state') in ('uploading','verified')
                and (result['state']!='verified' or result['received']==info.st_size),'state-conflict')
        if on_progress:on_progress(dict(result))
        return result
    cancelled()
    with session_factory(config) as session:
        capabilities = session.request('handshake', {})
        require(capabilities.get('asset_upload') is True and capabilities.get('persistent_requests') is True, 'capability-unverified')
        cancelled();value = validate(session.request('asset-begin', {'upload_id':upload,'source':source,'sha256':sha,'audience':audience}))
        require(value['state'] in ('uploading', 'verified'), 'state-conflict')
        if value['state'] == 'uploading':
            with path.open('rb') as stream:
                opened = os.fstat(stream.fileno())
                require((opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns) ==
                        (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns), 'identity-unknown')
                offset = value['received']; stream.seek(offset)
                while offset < info.st_size:
                    cancelled()
                    block = stream.read(min(CHUNK, info.st_size-offset)); require(bool(block), 'state-conflict')
                    value = validate(session.request('asset-chunk', {'upload_id':upload,'offset':offset,
                                                       'data':base64.b64encode(block).decode('ascii')}))
                    require(value['received'] == offset+len(block) and value['state'] == 'uploading', 'state-conflict')
                    offset = value['received']
            require(hasher(path, info) == sha, 'state-conflict');cancelled()
            value = validate(session.request('asset-finish', {'upload_id':upload}))
        require(value['state'] == 'verified', 'state-conflict')
        return dict(value, uploaded_or_cached=True, instance_created=False, runtime_verified=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    init = sub.add_parser('initialize'); init.add_argument('--cache-root', required=True, type=Path)
    upload = sub.add_parser('upload')
    upload.add_argument('--config', required=True, type=Path); upload.add_argument('--file', required=True, type=Path)
    upload.add_argument('--source', required=True); upload.add_argument('--audience', choices=('student','teacher'), required=True)
    upload.add_argument('--upload-id', required=True)
    args = parser.parse_args()
    try:
        if args.action == 'initialize': result = initialize(args.cache_root)
        else:
            from ctflab_remote import private_json
            result = upload_file(private_json(args.config), args.file, args.source, args.audience, args.upload_id)
        print(canonical(result))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, sqlite3.Error):
        print(canonical({'state':'unknown','automatic_replay':False,'preserved':True})); raise SystemExit(2)
