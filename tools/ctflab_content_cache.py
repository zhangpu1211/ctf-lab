"""单 HTTPS 源的签名索引、内容寻址续传缓存与带引用核对的显式回收。"""
import argparse
import base64
from contextlib import contextmanager,closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import sys
import uuid
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from ctflab_contract import canonical, require
from ctflab_generation_store import private_directory, digest
from ctflab_tls_endpoint import guard


def checksum(value):
    require(isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value))
    return value


def source_url(value):
    require(isinstance(value,str) and len(value)<=2048)
    parsed=urlsplit(value)
    require(parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment and parsed.path.endswith('/'))
    return value


def verify_index(envelope, keys, source, *, now=None):
    """信任根由宿主提供，索引内的密钥声明不会自行进入信任集。"""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    require(type(envelope) is dict and set(envelope)=={'key_id','signature','payload'})
    require(type(keys) is dict and isinstance(envelope['key_id'],str)
            and isinstance(envelope['signature'],str) and len(envelope['signature'])<=128)
    require(envelope['key_id'] in keys, 'permission-denied')
    payload=envelope['payload']
    require(type(payload) is dict and set(payload)=={'schema','sequence','expires','source','assets'})
    raw=canonical(payload).encode()
    require(len(raw)<=1024*1024)
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(keys[envelope['key_id']])).verify(
            base64.b64decode(envelope['signature'],validate=True),raw)
    except (InvalidSignature,ValueError,TypeError):
        require(False,'permission-denied')
    require(type(payload['schema']) is int and payload['schema']==1)
    require(type(payload['sequence']) is int and 0<payload['sequence']<2**53)
    require(isinstance(payload['expires'],str) and len(payload['expires'])<=64)
    expires=datetime.fromisoformat(payload['expires'].replace('Z','+00:00'))
    require(expires.tzinfo is not None and expires>(now or datetime.now(timezone.utc)), 'state-conflict')
    require(source_url(payload['source'])==source_url(source), 'state-conflict')
    assets=payload['assets'];require(type(assets) is dict and len(assets)<=4096)
    for sha, asset in assets.items():
        checksum(sha)
        require(type(asset) is dict and set(asset)=={'path','size','redistribution','audience'})
        path=asset['path']
        require(isinstance(path,str) and re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)*',path)
                and all(p not in ('.','..') for p in path.split('/')))
        require(type(asset['size']) is int and 0<asset['size']<=1024**4)
        require(asset['redistribution'] in ('allowed','recipe-only') and asset['audience'] in ('student','teacher'))
    return payload,hashlib.sha256(raw).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('内容源重定向被拒绝；请由宿主重新核验来源')


class ContentCache:
    def __init__(self,root):
        self.root=Path(root).absolute();guard(self.root)
        guard(self.root/'cache.sqlite3')

    @classmethod
    def create(cls,root):
        root=Path(root).absolute();private_directory(root)
        for name in ('objects','partial','quarantine'):private_directory(root/name)
        path=root/'cache.sqlite3'
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        with closing(sqlite3.connect(path)) as db:
            db.executescript('CREATE TABLE indexes(source TEXT PRIMARY KEY,sequence INTEGER,digest TEXT,payload TEXT);'
                             'CREATE TABLE refs(owner TEXT,sha TEXT,PRIMARY KEY(owner,sha));')
            db.commit()
        return cls(root)

    @contextmanager
    def locked(self):
        guard(self.root);guard(self.root/'cache.sqlite3')
        db=sqlite3.connect((self.root/'cache.sqlite3').as_uri()+'?mode=rw',uri=True,timeout=0)
        try:
            db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
            yield db;db.commit()
        except BaseException:
            db.rollback();raise
        finally:db.close()

    def _usage(self, db):
        """仅统计四个受管载荷目录；数据库/日志等元数据不冒充硬配额。"""
        from ctflab_runtime_inventory import signature
        records = {}
        total = 0
        for name in ('objects', 'partial', 'quarantine', 'uploads'):
            directory = self.root/name
            require(not directory.is_symlink(), 'permission-denied')
            if not directory.exists():
                require(name == 'uploads', 'state-conflict')
                continue
            guard(directory)
            require(directory.is_dir(), 'identity-unknown')
            for path in directory.iterdir():
                require(len(records) < 20000, 'storage-insufficient')
                info = guard(path).stat()
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'identity-unknown')
                records[path.relative_to(self.root).as_posix()] = list(signature(info))
                total += info.st_size
        reservations = 0
        reservation_rows = []
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='remote_uploads'").fetchone():
            rows = db.execute("SELECT id,size,received FROM remote_uploads WHERE state='uploading' LIMIT 20001").fetchall()
            require(len(rows) <= 20000, 'storage-insufficient')
            from ctflab_contract import uuid_text
            for identity, size, received in rows:
                uuid_text(identity)
                require(type(size) is int and type(received) is int and 0 <= received <= size <= 1024**4, 'identity-unknown')
                info = records.get('uploads/'+identity)
                if info is None:
                    # 提升后但数据库未提交：原预约仍保守保留，不能猜测可释放。
                    reservations += size
                else:
                    require(received <= info[2] <= size, 'identity-unknown')
                    reservations += size-info[2]
                reservation_rows.append({'upload_id': identity, 'size': size, 'received': received})
        configured = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cache_budget'").fetchone()
        maximum = None
        if configured:
            rows = db.execute('SELECT maximum FROM cache_budget').fetchall()
            require(len(rows) == 1 and type(rows[0][0]) is int and 1 <= rows[0][0] <= 1024**4, 'identity-unknown')
            maximum = rows[0][0]
        return {'payload_bytes': total, 'reserved_bytes': reservations,
                'committed_bytes': total+reservations, 'maximum_bytes': maximum,
                'files': records, 'upload_reservations': sorted(reservation_rows,key=lambda row:row['upload_id'])}

    def _storage(self, db):
        before = self._usage(db)
        require(before == self._usage(db), 'state-conflict')
        rows = db.execute('SELECT owner,sha FROM refs ORDER BY owner,sha LIMIT 20001').fetchall()
        require(len(rows) <= 20000, 'storage-insufficient')
        from ctflab_contract import identifier
        for owner, sha in rows:
            identifier(owner); checksum(sha)
        value = dict(before, references=[{'owner': owner, 'sha256': sha,
            'object_present': 'objects/'+sha in before['files']} for owner, sha in rows],
            scope='managed-cache-payload-and-upload-reservations', hard_quota_verified=False,
            metadata_included=False, external_writers_blocked=False, automatic_cleanup=False)
        value['snapshot_sha256'] = hashlib.sha256(canonical(value).encode()).hexdigest()
        return value

    def storage(self):
        with self.locked() as db:
            return self._storage(db)

    def budget_preview(self, maximum):
        require(type(maximum) is int and 1 <= maximum <= 1024**4)
        with self.locked() as db:
            current = self._storage(db)
            value = {'schema': 1, 'root': str(self.root),
                'root_identity': [self.root.stat().st_dev, self.root.stat().st_ino],
                'maximum_bytes': maximum, 'snapshot_sha256': current['snapshot_sha256'],
                'admissible': current['committed_bytes'] <= maximum}
            value['plan_sha256'] = hashlib.sha256(canonical(value).encode()).hexdigest()
            return value

    def budget_apply(self, maximum, expected):
        """显式接受当前载荷/引用/预约快照后登记；不配置文件系统或删除数据。"""
        require(type(maximum) is int and 1 <= maximum <= 1024**4)
        checksum(expected)
        with self.locked() as db:
            current = self._storage(db)
            info = self.root.stat()
            plan = {'schema': 1, 'root': str(self.root), 'root_identity': [info.st_dev, info.st_ino],
                'maximum_bytes': maximum, 'snapshot_sha256': current['snapshot_sha256'],
                'admissible': current['committed_bytes'] <= maximum}
            require(hashlib.sha256(canonical(plan).encode()).hexdigest() == expected, 'state-conflict')
            require(plan['admissible'], 'storage-insufficient')
            db.execute('CREATE TABLE IF NOT EXISTS cache_budget(maximum INTEGER NOT NULL)')
            db.execute('DELETE FROM cache_budget')
            db.execute('INSERT INTO cache_budget VALUES(?)', (maximum,))
            return {'state': 'cache-budget-registered', 'maximum_bytes': maximum,
                'hard_quota_verified': False, 'automatic_cleanup': False}

    def admit(self, db, additional=0):
        require(type(additional) is int and additional >= 0)
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cache_budget'").fetchone():
            pending = 0
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='remote_uploads'").fetchone():
                pending = db.execute("SELECT COALESCE(SUM(size-received),0) FROM remote_uploads WHERE state='uploading'").fetchone()[0]
            return {'maximum_bytes': None, 'reserved_bytes': pending}
        usage = self._usage(db)
        require(usage['committed_bytes']+additional <= usage['maximum_bytes'], 'storage-insufficient')
        return usage

    def accept(self,envelope,keys,source,*,now=None):
        payload,sha=verify_index(envelope,keys,source,now=now)
        with self.locked() as db:
            old=db.execute('SELECT sequence,digest FROM indexes WHERE source=?',(source,)).fetchone()
            require(old is None or payload['sequence']>old[0] or
                    payload['sequence']==old[0] and sha==old[1], 'state-conflict')
            db.execute('INSERT OR REPLACE INTO indexes VALUES(?,?,?,?)',
                       (source,payload['sequence'],sha,canonical(payload)))
        return {'state':'index-verified','sequence':payload['sequence'],'sha256':sha}

    def object(self,sha):
        path=self.root/'objects'/checksum(sha);guard(path)
        require(path.is_file() and digest(path)==sha,'state-conflict')
        return path

    def pin(self,owner,sha):
        from ctflab_contract import identifier
        identifier(owner)
        with self.locked() as db:
            self.object(sha)
            db.execute('INSERT OR IGNORE INTO refs VALUES(?,?)',(owner,sha))

    def unpin(self,owner,sha):
        from ctflab_contract import identifier
        identifier(owner);checksum(sha)
        # 实例引用覆盖运行、旧代次和失败现场；没有受管实例删除协议时保持保护。
        require(not owner.startswith('instance-'),'permission-denied')
        with self.locked() as db:db.execute('DELETE FROM refs WHERE owner=? AND sha=?',(owner,sha))

    def download(self,source,sha,*,audience='student',opener=None,now=None,mirror=None,cancel_requested=None):
        """网络和磁盘写入共用排他锁，索引校验与引用变动不能竞态替换。"""
        checksum(sha);source_url(source)
        location=source_url(mirror) if mirror is not None else source
        opener=opener or build_opener(NoRedirect()).open
        def permit():require(not (cancel_requested and cancel_requested()),'operation-finished')
        permit()
        with self.locked() as db:
            row=db.execute('SELECT payload FROM indexes WHERE source=?',(source,)).fetchone()
            require(row is not None,'state-conflict')
            payload=json.loads(row[0]);asset=payload['assets'].get(sha)
            require(asset is not None and asset['redistribution']=='allowed','permission-denied')
            require(audience in ('student','teacher') and asset['audience']==audience,'permission-denied')
            final=self.root/'objects'/sha
            if final.exists():return self.object(sha)
            expiry=datetime.fromisoformat(payload['expires'].replace('Z','+00:00'))
            require(expiry>(now or datetime.now(timezone.utc)),'state-conflict')
            part=self.root/'partial'/sha
            guard(part.parent)
            offset=guard(part).stat().st_size if part.exists() else 0
            require(offset<=asset['size'],'state-conflict')
            usage=self.admit(db, asset['size']-offset)
            require(shutil.disk_usage(self.root).free>=asset['size']-offset+usage['reserved_bytes']+16*1024**2,'storage-insufficient')
            if offset<asset['size']:
                headers={'Accept-Encoding':'identity'}
                if offset:headers['Range']=f'bytes={offset}-'
                url=location+asset['path']
                permit()
                with opener(Request(url,headers=headers),timeout=30) as response:
                    require(response.geturl()==url,'permission-denied')
                    require(response.headers.get('Content-Encoding','identity')=='identity')
                    if offset:
                        require(response.status==206 and response.headers.get('Content-Range')==
                                f'bytes {offset}-{asset["size"]-1}/{asset["size"]}', 'state-conflict')
                    else:require(response.status==200,'state-conflict')
                    length=response.headers.get('Content-Length')
                    require(length is not None and length.isdigit() and int(length)==asset['size']-offset,'state-conflict')
                    fd=os.open(part,os.O_WRONLY|os.O_APPEND if offset else os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    with os.fdopen(fd,'ab') as stream:
                        total=offset
                        while True:
                            permit()
                            reader=response.read1 if cancel_requested is not None and hasattr(response,'read1') else response.read
                            chunk=reader(min(1024*1024,asset['size']-total+1))
                            permit()
                            if not chunk:break
                            total+=len(chunk);require(total<=asset['size'],'state-conflict')
                            stream.write(chunk)
                        stream.flush();os.fsync(stream.fileno())
                    require(total==asset['size'],'state-conflict')
            actual=digest(part)
            permit()
            if actual!=sha:
                destination=self.root/'quarantine'/(sha+'-'+actual)
                require(not destination.exists(),'state-conflict')
                part.rename(destination)
                require(False,'state-conflict')
            part.rename(final)
            return self.object(sha)

    def preview_gc(self):
        with self.locked() as db:
            return self._preview(db)

    def _preview(self,db):
        from ctflab_cache_gc import candidates
        return candidates(self,db)

    def gc_preview(self):
        from ctflab_cache_gc import Collector
        return Collector(self).preview()

    def gc_status(self,operation):
        from ctflab_cache_gc import Collector
        return Collector(self).status(operation)

    def gc_start(self,operation,approved):
        from ctflab_cache_gc import Collector
        return Collector(self).start(operation,approved)

    def gc_resume(self,operation,observed):
        from ctflab_cache_gc import Collector
        return Collector(self).resume(operation,observed)

    def collect(self,approved):
        """兼容原显式完整预览API；新增逐对象尝试边界，旧未知不重放。"""
        from ctflab_cache_gc import Collector,record
        collector=Collector(self)
        with self.locked() as db:
            current=collector.plan(db)
            require(approved==current['objects'],'state-conflict')
            operation=str(uuid.uuid4());collector.ensure_new(operation)
            require(sum(1 for _ in self.root.glob('gc-*.intent.json'))<256,'storage-insufficient')
            intent={key:current[key] for key in ('schema','cache_identity','objects','plan_sha256')}
            intent.update(operation_id=operation,automatic_replay=False)
            record(collector.path(operation,'.intent.json'),intent)
            return collector.apply(db,operation,intent)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('storage', 'budget-preview', 'budget-apply', 'gc-preview', 'gc-status', 'gc-start', 'gc-resume'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--maximum-bytes', type=int)
    parser.add_argument('--plan-sha256')
    parser.add_argument('--operation-id')
    parser.add_argument('--observation-sha256')
    parser.add_argument('--execute',action='store_true')
    args = parser.parse_args(argv)
    try:
        cache = ContentCache(args.root)
        if not args.action.startswith('gc-'):
            require(args.operation_id is None and args.observation_sha256 is None and not args.execute)
        if args.action.startswith('gc-'):
            require(args.maximum_bytes is None)
            if args.action=='gc-preview':
                require(args.operation_id is None and args.plan_sha256 is None and args.observation_sha256 is None and not args.execute)
                result=cache.gc_preview()
            elif args.action=='gc-status':
                require(args.plan_sha256 is None and args.observation_sha256 is None and not args.execute)
                result=cache.gc_status(args.operation_id)
            elif args.action=='gc-start':
                require(args.execute and args.observation_sha256 is None)
                result={'state':'gc-request-finished','operation_id':args.operation_id,
                    'outcomes':cache.gc_start(args.operation_id,args.plan_sha256),'automatic_replay':False,'cleanup_verified':False}
            else:
                require(args.execute and args.plan_sha256 is None)
                result=cache.gc_resume(args.operation_id,args.observation_sha256)
        elif args.action == 'storage':
            require(args.maximum_bytes is None and args.plan_sha256 is None)
            result = cache.storage()
        elif args.action == 'budget-preview':
            require(args.plan_sha256 is None)
            result = cache.budget_preview(args.maximum_bytes)
        else:
            result = cache.budget_apply(args.maximum_bytes, args.plan_sha256)
        print(canonical(result)); return 0
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, sqlite3.Error):
        print(canonical({'state': 'refused-or-unknown', 'preserved': True, 'automatic_cleanup': False})); return 2


if __name__ == '__main__': raise SystemExit(main())
