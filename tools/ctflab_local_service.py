"""本地契约服务：持久意图、幂等与事件；通过注入后端执行，不连接现有 VM。

调用者须提供经过传输认证的 actor 与受保护本地状态根。本模块不实现 IPC
鉴权；Windows 存储使用原生 ACL 核验，不能作为不可信网络服务直接开放。
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import uuid

from ctflab_contract import (ContractError, MAX_MESSAGE_BYTES, PROTOCOL, VERSION, STATES, canonical, fingerprint,
                             identifier, integer, parse_request, public_error, require,
                             uuid_text, validate_request)


@dataclass(frozen=True)
class Observation:
    identity: str  # verified / unknown / mismatch；由受信后端现场核验
    generation: int
    state: str


@dataclass(frozen=True)
class Outcome:
    state: str
    error_code: str | None = None
    evidence_refs: tuple[str, ...] = ()
    cancelled: bool = False


@dataclass(frozen=True)
class OperationContext:
    instance_uuid: str
    operation_id: str
    generation: int
    cancel_requested: object  # 无参数只读回调；后端在可取消点查询


SCHEMA = '''
CREATE TABLE metadata(version INTEGER NOT NULL);
INSERT INTO metadata VALUES(1);
CREATE TABLE instances(id TEXT PRIMARY KEY, owner TEXT NOT NULL, generation INTEGER NOT NULL,
 revision INTEGER NOT NULL, state TEXT NOT NULL, active TEXT, previous_state TEXT,
 event_seq INTEGER NOT NULL DEFAULT 0, event_floor INTEGER NOT NULL DEFAULT 0);
CREATE TABLE operations(id TEXT PRIMARY KEY, actor TEXT NOT NULL, idem TEXT NOT NULL,
 digest TEXT NOT NULL, request TEXT NOT NULL, status TEXT NOT NULL, response TEXT,
 cancel INTEGER NOT NULL DEFAULT 0, UNIQUE(actor,idem));
CREATE TABLE events(instance TEXT NOT NULL, sequence INTEGER NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(instance,sequence));
'''
TRANSIENT = {'prepare': 'preparing', 'start': 'starting', 'stop': 'stopping',
             'reset': 'resetting', 'recover': 'recovering','guest':'recovering'}
ALLOWED = {'start': {'prepared', 'stopped'}, 'stop': {'prepared', 'stopped', 'process-running',
           'guest-ready', 'service-ready', 'course-verified', 'recovery-required'}, 'reset': {'prepared', 'stopped'},
           'recover': STATES,'guest':{'process-running'}}
# 部分启动失败后允许请求正常停止；execute仍要求后端现场证明identity=verified。
# 未知进程身份不会因状态被列入允许集合而绕过核验，更不授权强杀或删除。
SUCCESS = {'prepare': {'prepared'}, 'start': {'process-running', 'guest-ready', 'service-ready',
           'course-verified'}, 'stop': {'stopped'}, 'reset': {'prepared'},
           'recover': {'prepared', 'stopped', 'process-running', 'guest-ready', 'service-ready',
                       'course-verified'},'guest':{'process-running'}}


def _guard_path(path):
    if os.name == 'nt':
        from ctflab_windows_security import validate_local_path
        from ctflab_windows_native import NativeError
        try:
            validate_local_path(str(path))
        except NativeError:
            raise ContractError('permission-denied') from None
    # reparse point 也不能被当成普通目录；ACL 的现场验证归 PrivateStorage。
    for component in (path, *path.parents):
        if component.exists() or component.is_symlink():
            info = component.lstat()
            require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                    'permission-denied')
    if path.exists() and path.is_file():
        require(path.stat().st_nlink == 1, 'permission-denied')


def _windows_storage(path, *, root=False, create=False):
    from ctflab_windows_security import WindowsSecurity
    from ctflab_windows_native import NativeError
    try:
        security = WindowsSecurity()
        if create:
            security.create_directory(path)
        else:
            security.verify(path, root=root)
    except NativeError:
        raise ContractError('permission-denied') from None


class LocalService:
    def __init__(self, root):
        self.root = Path(root).absolute()
        _guard_path(self.root)
        if os.name == 'posix':
            info = self.root.stat()
            require(info.st_uid == os.getuid() and stat.S_ISDIR(info.st_mode)
                    and stat.S_IMODE(info.st_mode) & 0o077 == 0, 'permission-denied')
        if os.name == 'nt':
            _windows_storage(self.root, root=True)
        self.database = self.root / 'contract.sqlite3'
        self.worker = self.root / 'worker.sqlite3'
        with self._read() as db:
            require(db.execute('SELECT version FROM metadata').fetchone()[0] == VERSION, 'version-mismatch')

    @classmethod
    def create(cls, root):
        """显式初始化新目录；拒绝覆盖任何已有目录，不迁移用户状态。"""
        root = Path(root).absolute(); _guard_path(root)
        if os.name == 'nt':
            _windows_storage(root, create=True)
        else:
            root.mkdir(mode=0o700, parents=False, exist_ok=False)
        for name, schema in [('contract.sqlite3', SCHEMA), ('worker.sqlite3', 'CREATE TABLE gate(id INTEGER);')]:
            path = root / name
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
            # Connection 上下文只处理事务，不释放句柄；Windows 删除文件前必须关闭。
            with closing(sqlite3.connect(path)) as db:
                with db:
                    db.executescript(schema)
        return cls(root)

    def _connect(self, path, readonly=False):
        _guard_path(path)
        info = path.stat()
        require(stat.S_ISREG(info.st_mode), 'permission-denied')
        if os.name == 'posix':
            require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0,
                    'permission-denied')
        if os.name == 'nt':
            _windows_storage(self.root, root=True)
            _windows_storage(path)
        mode = 'ro' if readonly else 'rw'
        db = sqlite3.connect(path.as_uri() + '?mode=' + mode, uri=True, timeout=0, isolation_level=None)
        db.row_factory = sqlite3.Row
        if readonly:
            db.execute('PRAGMA query_only=ON')
        else:
            db.execute('PRAGMA synchronous=FULL')
        return db

    @contextmanager
    def _read(self):
        db = self._connect(self.database, True)
        try:
            db.execute('BEGIN'); yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self, worker=False):
        db = self._connect(self.worker if worker else self.database)
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback(); raise
        finally:
            db.close()

    def _instance(self, db, instance_id, actor):
        row = db.execute('SELECT * FROM instances WHERE id=?', (instance_id,)).fetchone()
        if row is not None:
            require(row['owner'] == actor, 'permission-denied')
        return row

    def _response(self, req, row=None, *, operation_id=None, result='completed', error=None, cancelled=False):
        return {'protocol': PROTOCOL, 'version': VERSION, 'request_id': req['request_id'],
                'instance_uuid': req['instance_uuid'], 'operation_id': operation_id,
                'generation': row['generation'] if row else None,
                'state_revision': row['revision'] if row else None,
                'state': row['state'] if row else 'unknown',
                'cursor': row['event_seq'] if row else 0,
                'result': result, 'cancelled': cancelled, 'error': error, 'evidence_refs': []}

    def _event(self, db, instance_id, operation_id, stage):
        row = db.execute('SELECT * FROM instances WHERE id=?', (instance_id,)).fetchone()
        sequence = row['event_seq'] + 1
        event = {'protocol': PROTOCOL, 'version': VERSION, 'event_id': str(uuid.uuid4()),
                 'sequence': sequence, 'timestamp': datetime.now(timezone.utc).isoformat(),
                 'instance_uuid': instance_id, 'generation': row['generation'],
                 'operation_id': operation_id, 'state_revision': row['revision'],
                 'stage': stage, 'state': row['state']}
        db.execute('INSERT INTO events VALUES(?,?,?)', (instance_id, sequence, canonical(event)))
        db.execute('UPDATE instances SET event_seq=? WHERE id=?', (sequence, instance_id))
        return db.execute('SELECT * FROM instances WHERE id=?', (instance_id,)).fetchone()

    def handle_json(self, text, actor):
        """CLI 与 GUI 适配器可共用；不从请求体接受主体身份。"""
        try:
            return self.submit(parse_request(text), actor)
        except ContractError as exc:
            return {'protocol': PROTOCOL, 'version': VERSION, 'request_id': None,
                    'instance_uuid': None, 'operation_id': None, 'generation': None,
                    'state_revision': None, 'state': 'unknown', 'cursor': 0,
                    'result': 'failed', 'cancelled': False, 'error': public_error(exc.code), 'evidence_refs': []}
        except (sqlite3.Error, OSError):
            return {'protocol': PROTOCOL, 'version': VERSION, 'request_id': None,
                    'instance_uuid': None, 'operation_id': None, 'generation': None,
                    'state_revision': None, 'state': 'unknown', 'cursor': 0,
                    'result': 'unknown', 'cancelled': False, 'error': public_error('persistence-failed'), 'evidence_refs': []}

    def status(self, request, actor):
        req = validate_request(request); identifier(actor)
        require(req['operation'] == 'status')
        with self._read() as db:
            row = self._instance(db, req['instance_uuid'], actor)
            response = self._response(req, row)
            if row and row['active']:
                op = db.execute('SELECT status FROM operations WHERE id=?', (row['active'],)).fetchone()
                response['operation_id'] = row['active']
                response['result'] = 'accepted' if op['status'] == 'pending' else 'unknown'
                if op['status'] == 'executing':
                    response['state'] = 'recovery-required'
            return response

    def query_request(self,request,actor):
        """只读查询原幂等请求，绝不创建请求、派发或改变事件/修订。"""
        req=validate_request(request);identifier(actor);require(req['operation'] != 'status')
        with self._read() as db:
            row=self._instance(db,req['instance_uuid'],actor)
            prior=db.execute('SELECT * FROM operations WHERE actor=? AND idem=?',(actor,req['idempotency_key'])).fetchone()
            if prior is None:
                return {'state':'request-not-recorded','recorded':False,'response':None,'automatic_replay':False}
            require(prior['digest']==fingerprint(req),'idempotency-conflict')
            value=json.loads(prior['response']) if prior['response'] else self._response(req,row,operation_id=prior['id'],
                result='accepted' if prior['status']=='pending' else 'unknown')
            value['request_id']=req['request_id']
            return {'state':'request-recorded','recorded':True,'response':value,'automatic_replay':False}

    def dispatch_status(self, instance_uuid, operation_id, actor):
        """只读核对原操作领取状态；不重新提交、不改变版本或取消标记。"""
        uuid_text(instance_uuid); uuid_text(operation_id); identifier(actor)
        with self._read() as db:
            row = self._instance(db, instance_uuid, actor)
            require(row is not None, 'permission-denied')
            op = db.execute('SELECT * FROM operations WHERE id=?', (operation_id,)).fetchone()
            require(op is not None and op['actor'] == actor, 'permission-denied')
            req = json.loads(op['request'])
            require(req['instance_uuid'] == instance_uuid, 'permission-denied')
            return {'instance_uuid': instance_uuid, 'operation_id': operation_id,
                    'state_revision': row['revision'], 'generation': row['generation'],
                    'status': op['status'], 'active': row['active'] == operation_id,
                    'resume_allowed': row['active'] == operation_id and op['status'] == 'pending'
                                      and op['response'] is None,
                    'cancel_requested': bool(op['cancel']), 'automatic_replay': False}

    def _preparation(self, db, row, actor):
        if row is None: return None
        operation = row['active']
        if operation is None:
            # 请求按canonical固定保存；从持久业务账本定位，不依赖可裁剪事件。
            # 使用标准SQLite字符串匹配，避免给旧安装新增JSON扩展依赖。
            prior = db.execute('SELECT id FROM operations WHERE actor=? AND instr(request,?)>0 AND instr(request,?)>0 ORDER BY rowid DESC LIMIT 1',
                (actor, '"instance_uuid":'+canonical(row['id']), '"operation":"prepare"')).fetchone()
            if prior is None: return None
            operation = prior['id']
        old = db.execute('SELECT * FROM operations WHERE id=? AND actor=?', (operation, actor)).fetchone()
        if old is None: return None
        request = json.loads(old['request'])
        if request['instance_uuid'] != row['id'] or request['operation'] != 'prepare': return None
        response = json.loads(old['response']) if old['response'] else None
        eligible = (old['status'] in ('executing', 'unknown', 'failed') or
                    old['status'] == 'completed' and response and response['cancelled'])
        return {'instance_uuid': row['id'], 'operation_id': operation, 'generation': row['generation'],
                'state_revision': row['revision'], 'status': old['status'],
                'restart_allowed': bool(row['generation'] == 1 and eligible and
                                        row['state'] in ('preparing', 'failed', 'recovery-required')),
                'preserved': True, 'automatic_replay': False}

    def preparation_status(self, instance_uuid, actor):
        """契约侧候选状态；状态根无已选择代次的证明仍由后端现场提供。"""
        uuid_text(instance_uuid); identifier(actor)
        with self._read() as db:
            return self._preparation(db, self._instance(db, instance_uuid, actor), actor)

    def restart_preparation(self, instance_uuid, original, revision, attempt, actor, backend):
        """显式封存首次准备并登记全新准备；不重新执行原未知操作。"""
        uuid_text(instance_uuid); uuid_text(original); uuid_text(attempt); integer(revision); identifier(actor)
        # 与execute/recover使用同一工作门锁，原执行器未退出领取区间时不能封存。
        with self._transaction(worker=True):
            with self._transaction() as db:
                row = self._instance(db, instance_uuid, actor)
                old = db.execute('SELECT * FROM operations WHERE id=? AND actor=?', (original, actor)).fetchone()
                require(row is not None and old is not None, 'permission-denied')
                prior_request = json.loads(old['request'])
                require(prior_request['instance_uuid'] == instance_uuid and prior_request['operation'] == 'prepare', 'permission-denied')
                key = hashlib.sha256(canonical({'instance': instance_uuid, 'original': original,
                    'revision': revision, 'attempt': attempt}).encode()).hexdigest()
                req = dict(prior_request, request_id=str(uuid.uuid4()), idempotency_key=key)
                validate_request(req)
                prior = db.execute('SELECT * FROM operations WHERE actor=? AND idem=?', (actor, key)).fetchone()
                if prior:
                    require(prior['digest'] == fingerprint(req), 'idempotency-conflict')
                    if prior['response']: return json.loads(prior['response'])
                    return self._response(req, row, operation_id=prior['id'],
                                          result='accepted' if prior['status'] == 'pending' else 'unknown')
                metadata = self._preparation(db, row, actor)
                require(metadata is not None and metadata['operation_id'] == original and metadata['restart_allowed'], 'state-conflict')
                require(row['revision'] == revision, 'state-conflict')
                replacement = str(uuid.uuid4())
                proof = backend.preserve_initial_preparation(original, replacement)
                require(proof == {'original_operation': original, 'replacement_operation': replacement,
                    'active_generation': 0, 'preserved': True, 'automatic_replay': False}, 'identity-unknown')
                if not old['response']:
                    stale = self._response(prior_request, row, operation_id=original, result='unknown',
                                           error=public_error('identity-unknown'))
                    stale['state'] = 'recovery-required'
                    db.execute('UPDATE operations SET status=?,response=? WHERE id=?', ('unknown', canonical(stale), original))
                db.execute('INSERT INTO operations(id,actor,idem,digest,request,status) VALUES(?,?,?,?,?,?)',
                           (replacement, actor, key, fingerprint(req), canonical(req), 'pending'))
                db.execute("UPDATE instances SET previous_state='failed',state='preparing',active=?,revision=revision+1 WHERE id=?",
                           (replacement, instance_uuid))
                row = self._event(db, instance_uuid, replacement, 'intent')
                return self._response(req, row, operation_id=replacement, result='accepted')

    def submit(self, request, actor):
        req = validate_request(request); identifier(actor)
        if req['operation'] == 'status':
            return self.status(req, actor)
        try:
            # 恢复需要证明旧执行器不再持工作门锁；取消仍可写独立的契约库。
            if req['operation'] == 'recover':
                with self._transaction(worker=True):
                    return self._submit(req, actor)
            return self._submit(req, actor)
        except ContractError as exc:
            return self._response(req, result='conflict' if exc.code in {
                'state-conflict', 'idempotency-conflict', 'resource-busy', 'operation-finished'} else 'failed',
                error=public_error(exc.code))
        except sqlite3.Error as exc:
            busy = (getattr(exc, 'sqlite_errorcode', None) in (5, 6)
                    or str(exc) in {'database is locked', 'database table is locked'})
            code = 'resource-busy' if busy else 'persistence-failed'
            return self._response(req, result='failed', error=public_error(code))

    def _submit(self, req, actor):
        with self._transaction() as db:
            row = self._instance(db, req['instance_uuid'], actor)
            prior = db.execute('SELECT * FROM operations WHERE actor=? AND idem=?',
                               (actor, req['idempotency_key'])).fetchone()
            if prior:
                require(prior['digest'] == fingerprint(req), 'idempotency-conflict')
                if prior['response']:
                    response = json.loads(prior['response']); response['request_id'] = req['request_id']; return response
                response = self._response(req, row, operation_id=prior['id'],
                                          result='accepted' if prior['status'] == 'pending' else 'unknown')
                if prior['status'] == 'executing': response['state'] = 'recovery-required'
                return response
            op = req['operation']; operation_id = str(uuid.uuid4())
            if op == 'prepare':
                require(row is None, 'state-conflict')
                db.execute('INSERT INTO instances(id,owner,generation,revision,state) VALUES(?,?,1,0,?)',
                           (req['instance_uuid'], actor, 'failed'))
                row = self._instance(db, req['instance_uuid'], actor)
            else:
                require(row is not None and row['generation'] == req['expected_generation']
                        and row['revision'] == req['expected_state_revision'], 'state-conflict')
            if op == 'cancel':
                target = req['parameters']['operation_id']
                require(row['active'] == target, 'operation-finished')
                db.execute('UPDATE operations SET cancel=1 WHERE id=?', (target,))
                db.execute('UPDATE instances SET revision=revision+1 WHERE id=?', (row['id'],))
                row = self._event(db, row['id'], operation_id, 'cancel-requested')
                response = self._response(req, row, operation_id=operation_id)
                db.execute('INSERT INTO operations(id,actor,idem,digest,request,status,response) VALUES(?,?,?,?,?,?,?)',
                           (operation_id, actor, req['idempotency_key'], fingerprint(req), canonical(req),
                            'completed', canonical(response)))
                return response
            if row['active']:
                require(op == 'recover', 'resource-busy')
                old = db.execute('SELECT * FROM operations WHERE id=?', (row['active'],)).fetchone()
                stale = self._response(json.loads(old['request']), row, operation_id=old['id'],
                                       result='unknown', error=public_error('identity-unknown'))
                stale['state'] = 'recovery-required'
                db.execute('UPDATE operations SET status=?,response=? WHERE id=?',
                           ('unknown', canonical(stale), old['id']))
            if op != 'prepare':
                require(row['state'] in ALLOWED[op], 'state-conflict')
            db.execute('INSERT INTO operations(id,actor,idem,digest,request,status) VALUES(?,?,?,?,?,?)',
                       (operation_id, actor, req['idempotency_key'], fingerprint(req), canonical(req), 'pending'))
            db.execute('UPDATE instances SET previous_state=state,state=?,active=?,revision=revision+1 WHERE id=?',
                       (TRANSIENT[op], operation_id, row['id']))
            row = self._event(db, row['id'], operation_id, 'intent')
            return self._response(req, row, operation_id=operation_id, result='accepted')

    def _cancelled(self, operation_id):
        with self._read() as db:
            return bool(db.execute('SELECT cancel FROM operations WHERE id=?', (operation_id,)).fetchone()[0])

    def execute(self, operation_id, actor, backend):
        """显式领取一次已落盘操作。后台崩溃后同一意图不自动重执行。

        工作库的写锁跨越后端执行；所有实例当前串行执行，提交/状态/取消独立。
        SQLite 锁释放不等于 VM 停止，recover 仍要求后端现场身份与状态证明。
        """
        uuid_text(operation_id); identifier(actor)
        req = None
        try:
            with self._transaction(worker=True):
                with self._transaction() as db:
                    op = db.execute('SELECT * FROM operations WHERE id=?', (operation_id,)).fetchone()
                    require(op is not None and op['actor'] == actor, 'permission-denied')
                    req = json.loads(op['request']); row = self._instance(db, req['instance_uuid'], actor)
                    if op['response']: return json.loads(op['response'])
                    require(row['active'] == operation_id and op['status'] == 'pending', 'identity-unknown')
                    before = dict(row)
                    db.execute('UPDATE operations SET status=? WHERE id=?', ('executing', operation_id))
                    self._event(db, row['id'], operation_id, 'executing')
                context = OperationContext(req['instance_uuid'], operation_id, before['generation'],
                                           lambda: self._cancelled(operation_id))
                observed_generation = before['generation']
                try:
                    if context.cancel_requested():
                        outcome = Outcome(before['previous_state'], cancelled=True)
                    else:
                        if req['operation'] != 'prepare':
                            observed = backend.observe(context)
                            require(isinstance(observed, Observation) and observed.identity == 'verified', 'identity-unknown')
                            allowed_generations = {context.generation, context.generation + 1} if req['operation'] == 'recover' else {context.generation}
                            require(type(observed.generation) is int and observed.generation in allowed_generations, 'identity-unknown')
                            require(observed.state in ALLOWED[req['operation']], 'state-conflict')
                            observed_generation = observed.generation
                        outcome = backend.execute(req, context)
                    require(isinstance(outcome, Outcome) and type(outcome.cancelled) is bool, 'backend-failed')
                    require(outcome.state in STATES, 'backend-failed')
                    if outcome.error_code:
                        public_error(outcome.error_code, evidence_refs=outcome.evidence_refs)
                        require(outcome.state in {'failed', 'unknown', 'recovery-required'}, 'backend-failed')
                    elif outcome.cancelled:
                        require(context.cancel_requested() and outcome.state in {'prepared','stopped','failed','process-running',
                                'guest-ready','service-ready','course-verified','recovery-required'}, 'backend-failed')
                    else:
                        require(outcome.state in SUCCESS[req['operation']], 'backend-failed')
                    for ref in outcome.evidence_refs: identifier(ref)
                    require(len(outcome.evidence_refs) <= 32, 'backend-failed')
                except Exception as exc:
                    outcome = Outcome('recovery-required', exc.code if isinstance(exc, ContractError) else 'backend-failed')
                return self._finish(req, actor, operation_id, outcome, observed_generation)
        except (sqlite3.Error, OSError):
            if req is None: raise ContractError('resource-busy') from None
            return self._response(req, operation_id=operation_id, result='unknown',
                                  error=public_error('persistence-failed', stage='commit'))

    def _finish(self, req, actor, operation_id, outcome, observed_generation):
        with self._transaction() as db:
            row = self._instance(db, req['instance_uuid'], actor)
            require(row['active'] == operation_id, 'identity-unknown')
            generation = row['generation']
            if not outcome.error_code and not outcome.cancelled:
                if req['operation'] == 'reset': generation += 1
                elif req['operation'] == 'recover': generation = observed_generation
            db.execute('UPDATE instances SET state=?,generation=?,revision=revision+1,active=NULL WHERE id=?',
                       (outcome.state, generation, row['id']))
            row = self._event(db, row['id'], operation_id,
                              'failed' if outcome.error_code else 'cancelled' if outcome.cancelled else 'completed')
            error = public_error(outcome.error_code, stage='execute', evidence_refs=outcome.evidence_refs) if outcome.error_code else None
            response = self._response(req, row, operation_id=operation_id,
                                      result='failed' if error else 'completed', error=error, cancelled=outcome.cancelled)
            response['evidence_refs'] = list(outcome.evidence_refs)
            db.execute('UPDATE operations SET status=?,response=? WHERE id=?',
                       (response['result'], canonical(response), operation_id))
            return response

    def events(self, instance_uuid, actor, *, after=0, limit=100):
        uuid_text(instance_uuid); identifier(actor); integer(after); integer(limit, 1); require(limit <= 1000)
        with self._read() as db:
            row = self._instance(db, instance_uuid, actor); require(row is not None, 'state-conflict')
            require(row['event_floor'] <= after <= row['event_seq'], 'cursor-expired')
            rows = db.execute('SELECT payload FROM events WHERE instance=? AND sequence>? ORDER BY sequence LIMIT ?',
                              (instance_uuid, after, limit)).fetchall()
            return [json.loads(item[0]) for item in rows]

    def prune_events(self, instance_uuid, actor, *, through):
        """受信维护入口，仅修剪事件；幂等记录不删除，过期游标明确拒绝。"""
        uuid_text(instance_uuid); identifier(actor); integer(through)
        with self._transaction() as db:
            row = self._instance(db, instance_uuid, actor); require(row is not None, 'state-conflict')
            require(row['event_floor'] <= through <= row['event_seq'], 'cursor-expired')
            db.execute('DELETE FROM events WHERE instance=? AND sequence<=?', (instance_uuid, through))
            db.execute('UPDATE instances SET event_floor=? WHERE id=?', (through, instance_uuid))

    def _saved_operation(self, op, instance_uuid):
        """校验账本引用与公开响应；不把历史状态当当前运行事实。"""
        try:
            require(len(op['request'].encode()) <= 4*MAX_MESSAGE_BYTES, 'identity-unknown')
            req = validate_request(json.loads(op['request']))
            require(req['instance_uuid'] == instance_uuid and fingerprint(req) == op['digest'] and op['idem'] == req['idempotency_key']
                    and req['operation'] != 'status' and op['status'] in ('pending','executing','unknown','failed','completed')
                    and op['cancel'] in (0, 1), 'identity-unknown')
            uuid_text(op['id'])
            response = None
            require(op['response'] is not None or op['status'] not in ('completed', 'failed'), 'identity-unknown')
            require(op['response'] is None or op['status'] not in ('pending', 'executing'), 'identity-unknown')
            if op['response'] is not None:
                require(len(op['response'].encode()) <= MAX_MESSAGE_BYTES, 'identity-unknown')
                response = json.loads(op['response'])
                require(type(response) is dict and set(response) == {'protocol','version','request_id','instance_uuid',
                        'operation_id','generation','state_revision','state','cursor','result','cancelled','error','evidence_refs'}, 'identity-unknown')
                require(response['protocol'] == PROTOCOL and type(response['version']) is int and response['version'] == VERSION
                        and response['request_id'] == req['request_id'] and response['instance_uuid'] == instance_uuid
                        and response['operation_id'] == op['id'] and response['state'] in STATES
                        and response['result'] in ('accepted','completed','conflict','failed','unknown')
                        and type(response['cancelled']) is bool, 'identity-unknown')
                require(response['result'] == op['status'], 'identity-unknown')
                integer(response['generation'], 1); integer(response['state_revision']); integer(response['cursor'])
                require(type(response['evidence_refs']) is list and len(response['evidence_refs']) <= 32, 'identity-unknown')
                for ref in response['evidence_refs']:identifier(ref)
                if response['error'] is not None:
                    error = response['error']; require(type(error) is dict, 'identity-unknown')
                    require(error == public_error(error['code'], stage=error['stage'], evidence_refs=error['evidence_refs']), 'identity-unknown')
            summary = {'operation_id': op['id'], 'request_id': req['request_id'], 'operation': req['operation'],
                       'expected_generation': req['expected_generation'], 'status': op['status'],
                       'response_recorded': response is not None, 'cancel_requested': bool(op['cancel'])}
            return summary, response
        except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
            raise ContractError('identity-unknown') from None

    def operation_history(self, instance_uuid, actor, *, limit=20, before=None):
        """从原幂等账本读取有界历史；不依赖事件保留，不暴露请求参数/幂等键。"""
        uuid_text(instance_uuid); identifier(actor); integer(limit, 1); require(limit <= 50)
        if before is not None:uuid_text(before)
        with self._read() as db:
            row = self._instance(db, instance_uuid, actor)
            records = []
            if row is None:require(before is None, 'permission-denied')
            if row is not None:
                cutoff = None
                if before is not None:
                    cursor = db.execute('SELECT rowid AS sequence,* FROM operations WHERE id=? AND actor=?',(before,actor)).fetchone()
                    require(cursor is not None,'permission-denied');self._saved_operation(cursor,instance_uuid)
                    cutoff = cursor['sequence']
                rows = db.execute('SELECT * FROM operations WHERE actor=? AND instr(request,?)>0 AND (? IS NULL OR rowid<?) ORDER BY rowid DESC LIMIT ?',
                                  (actor, '"instance_uuid":'+canonical(instance_uuid), cutoff, cutoff, limit+1)).fetchall()
                for op in rows[:limit]:records.append(self._saved_operation(op, instance_uuid)[0])
            truncated = bool(row is not None and len(rows)>limit)
            return {'state':'operation-history','instance_uuid':instance_uuid,'operations':records,
                    'truncated':truncated,'next_before':records[-1]['operation_id'] if truncated else None,'historical':True,
                    'current_runtime_verified':False,'automatic_replay':False}

    def operation_result(self, instance_uuid, operation_id, actor):
        """按原UUID只读取回已保存响应；未落结果仍未知，不合成当前状态。"""
        uuid_text(instance_uuid); uuid_text(operation_id); identifier(actor)
        with self._read() as db:
            row = self._instance(db, instance_uuid, actor); require(row is not None, 'permission-denied')
            op = db.execute('SELECT * FROM operations WHERE id=? AND actor=?', (operation_id, actor)).fetchone()
            require(op is not None, 'permission-denied')
            summary, response = self._saved_operation(op, instance_uuid)
            return {'state':'operation-recorded','instance_uuid':instance_uuid,'record':summary,'response':response,
                    'historical':True,'current_runtime_verified':False,'automatic_replay':False}
