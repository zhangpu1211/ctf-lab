"""安装更新协调：登记既有实例、锁内停机核验、元数据备份与原子版本切换。

只支持现有数据schema=1；不搬移磁盘、不执行迁移脚本、不自动停止实例。
"""
from contextlib import ExitStack, closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from ctflab_contract import canonical, require, uuid_text
from ctflab_generation_store import GenerationStore, private_directory, digest
from ctflab_local_service import LocalService
from ctflab_tls_endpoint import guard

SCHEMA = '''
CREATE TABLE workspaces(id TEXT PRIMARY KEY,path TEXT UNIQUE NOT NULL);
CREATE TABLE updates(id TEXT PRIMARY KEY,target TEXT NOT NULL,previous TEXT,
 plan_sha256 TEXT NOT NULL,state TEXT NOT NULL,backup TEXT NOT NULL);
'''


def check_journal(releases, db):
    root = guard(releases.root/'update-backups')
    for path in root.iterdir():
        guard(path); uuid_text(path.name)
        row = db.execute('SELECT state FROM updates WHERE id=?', (path.name,)).fetchone()
        require(row is not None and row[0] in ('committed', 'abandoned'), 'identity-unknown')


class UpdateCoordinator:
    def __init__(self, releases, *, make_driver=None):
        self.releases = releases
        self.make_driver = make_driver or self.driver

    @staticmethod
    def driver(store):
        from ctflab_qemu_driver import QemuDriver, read
        return QemuDriver(store, read(store.root/'runtime-profile.json'))

    def register(self, root):
        path = Path(root)
        require(path.is_absolute())
        path = guard(path)
        install = self.releases.root
        require(path != install and path not in install.parents and install not in path.parents)
        store = GenerationStore(path)
        identity = store.config['instance_uuid']
        with self.releases.locked() as db:
            old = db.execute('SELECT path FROM workspaces WHERE id=?', (identity,)).fetchone()
            require(old is None or old[0] == str(path), 'state-conflict')
            db.execute('INSERT OR IGNORE INTO workspaces VALUES(?,?)', (identity, str(path)))
        return {'state': 'registered', 'instance_uuid': identity, 'data_moved': False}

    def initialize(self):
        """显式升级旧安装版本库；先备份SQLite，实验库与磁盘均不迁移。"""
        with self.releases.locked() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            require({'versions', 'pointers', 'refs'} <= tables, 'version-mismatch')
            # 明确初始化时才补新启动器状态；普通读取/启动不自动迁移旧安装根。
            launch_root=self.releases.root/'launches';launch_gate=self.releases.root/'application.lock'
            if not launch_root.exists():private_directory(launch_root)
            guard(launch_root)
            if not launch_gate.exists():
                fd=os.open(launch_gate,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
            guard(launch_gate)
            if {'workspaces', 'updates'} <= tables:
                return {'state': 'already-initialized', 'data_migrated': False}
            require(not {'workspaces', 'updates'} & tables, 'version-mismatch')
            root = self.releases.root
            target = root/('install-schema-backup-'+str(uuid.uuid4())+'.sqlite3')
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.close(fd)
            with closing(sqlite3.connect((root/'releases.sqlite3').as_uri()+'?mode=ro', uri=True)) as source:
                with closing(sqlite3.connect(target)) as output:
                    source.backup(output)
                    require(output.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'persistence-failed')
            with target.open('rb') as stream: os.fsync(stream.fileno())
            if not (root/'update-backups').exists(): private_directory(root/'update-backups')
            guard(root/'update-backups')
            require(not list((root/'update-backups').iterdir()), 'identity-unknown')
            for statement in SCHEMA.split(';'):
                if statement.strip(): db.execute(statement)
            return {'state': 'initialized', 'backup': str(target), 'backup_sha256': digest(target),
                    'data_migrated': False}

    def inspect(self, db, stack):
        """持有工作门与代次门直到备份/切换提交；不根据历史PID判断停机。"""
        self.releases.check_launches()
        require(not db.execute("SELECT 1 FROM updates WHERE state='intent'").fetchone(), 'identity-unknown')
        check_journal(self.releases, db)
        workspaces = []
        for identity, path in db.execute('SELECT id,path FROM workspaces ORDER BY id'):
            store = GenerationStore(path)
            require(store.config['instance_uuid'] == identity, 'identity-unknown')
            service = None
            if (store.root/'desktop-contract').exists():
                service = LocalService(store.root/'desktop-contract')
                stack.enter_context(service._transaction(worker=True))
                contract = stack.enter_context(service._transaction())
                require(not contract.execute('SELECT 1 FROM instances WHERE active IS NOT NULL').fetchone(), 'resource-busy')
            stack.enter_context(store.locked())
            snapshot = store.snapshot()
            require(not snapshot['unresolved'], 'identity-unknown')
            generations = snapshot['generations']
            driver = self.make_driver(store) if generations else None
            for generation in generations:
                require(generation['state'] == 'prepared', 'identity-unknown')
                plan = store.plan(generation['number'])
                for node in plan['start_order']:
                    seen = driver.observe(plan, node, store.node_paths(generation['number'], node))
                    require(seen.identity == 'verified' and seen.state == 'stopped'
                            and seen.instance_uuid == identity and seen.generation == generation['number']
                            and seen.node == node, 'resource-busy')
            workspaces.append((store, service, snapshot))
        return workspaces

    def plan(self, db, version, workspaces):
        row = db.execute('SELECT digest,path,payload FROM versions WHERE id=?', (version,)).fetchone()
        require(row is not None, 'state-conflict')
        payload = json.loads(row[2]); self.releases.check(Path(row[1]), payload)
        require(payload['data_schema'] == 1, 'version-mismatch')
        active = db.execute('SELECT active FROM pointers WHERE id=1').fetchone()[0]
        value = {'schema': 1, 'target': version, 'target_sha256': row[0], 'previous': active,
                 'workspaces': [dict(snapshot, config_sha256=hashlib.sha256(canonical(store.config).encode()).hexdigest(),
                                    profile_sha256=digest(guard(store.root/'runtime-profile.json'))
                                    if (store.root/'runtime-profile.json').exists() else None)
                                for store, _, snapshot in workspaces], 'data_schema': 1,
                 'migration': 'metadata-backup-in-place-no-schema-change',
                 'unregistered_workspaces_checked': False, 'automatic_stop': False}
        value['plan_sha256'] = hashlib.sha256(canonical(value).encode()).hexdigest()
        return value

    def preview(self, version):
        with self.releases.application_gate(),ExitStack() as stack, self.releases.locked() as db:
            return self.plan(db, version, self.inspect(db, stack))

    def apply(self, version, operation, expected):
        uuid_text(operation)
        # 先退出版本事务，再释放工作门，避免切换提交前出现新启动窗口。
        with self.releases.application_gate(),ExitStack() as stack, self.releases.locked() as db:
            old = db.execute('SELECT target,plan_sha256,state,backup FROM updates WHERE id=?', (operation,)).fetchone()
            if old:
                require(old[0] == version and old[1] == expected, 'idempotency-conflict')
                return {'state': old[2], 'backup': old[3], 'automatic_replay': False}
            workspaces = self.inspect(db, stack)
            plan = self.plan(db, version, workspaces)
            require(plan['plan_sha256'] == expected, 'state-conflict')
            backup = self.releases.root/'update-backups'/operation
            private_directory(backup)
            # 意图先单独落盘。SQLite切换失败或进程中断仍保留，不重放文件副作用。
            self.save(backup/'intent.json', plan)
            db.execute('INSERT INTO updates VALUES(?,?,?,?,?,?)',
                       (operation, version, plan['previous'], expected, 'intent', str(backup)))
            # releases事务直到结束保持锁；目录意图也参与后续inspect/switch_guard门禁。
            files = {}
            for store, service, snapshot in workspaces:
                target = backup/store.config['instance_uuid']; private_directory(target)
                inputs = [(store.root/'ledger.sqlite3', target/'ledger.sqlite3')]
                if service: inputs.append((service.database, target/'contract.sqlite3'))
                for origin, destination in inputs:
                    guard(origin)
                    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.close(fd)
                    with closing(sqlite3.connect(origin.as_uri()+'?mode=ro', uri=True)) as source:
                        with closing(sqlite3.connect(destination)) as output:
                            source.backup(output)
                            require(output.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'persistence-failed')
                    with destination.open('rb') as stream: os.fsync(stream.fileno())
                    files[str(destination.relative_to(backup))] = digest(destination)
                profile = store.root/'runtime-profile.json'
                if profile.exists():
                    guard(profile)
                    require(profile.stat().st_size <= 1024**2)
                    self.save(target/'runtime-profile.json', json.loads(profile.read_text()))
                    files[str((target/'runtime-profile.json').relative_to(backup))] = digest(target/'runtime-profile.json')
            self.save(backup/'backup.json', {'schema': 1, 'files': files, 'disks_included': False,
                                          'restore_automatically': False})
            # 再验载荷，备份失败不会触及版本指针。
            row = db.execute('SELECT path,payload FROM versions WHERE id=?', (version,)).fetchone()
            self.releases.check(Path(row[0]), json.loads(row[1]))
            if plan['previous'] != version:
                db.execute('UPDATE pointers SET active=?,previous=? WHERE id=1', (version, plan['previous']))
            db.execute("UPDATE updates SET state='committed' WHERE id=?", (operation,))
            return {'state': 'committed', 'version': version, 'backup': str(backup),
                    'automatic_replay': False, 'data_migrated': False}

    @staticmethod
    def save(path, value):
        from ctflab_windows_recovery import record
        record(path, value)

    def recovery(self):
        """只读区分已提交与目录意图；失败现场不自动清理或恢复旧数据。"""
        with self.releases.locked() as db:
            rows = {r[0]: {'state': r[1], 'target': r[2]} for r in db.execute('SELECT id,state,target FROM updates')}
            result = []
            for path in sorted((self.releases.root/'update-backups').iterdir()):
                guard(path); uuid_text(path.name)
                value = rows.get(path.name, {'state': 'interrupted-before-commit', 'target': None})
                result.append(dict(value, operation_id=path.name, backup_complete=(path/'backup.json').exists()))
            return {'updates': result, 'automatic_replay': False, 'automatic_cleanup': False}

    def abandon(self, operation):
        """显式保留旧版本并结清中断尝试；保留全部备份，不重放或删除文件。"""
        uuid_text(operation)
        with self.releases.locked() as db:
            root = guard(self.releases.root/'update-backups'/operation)
            intent = guard(root/'intent.json'); require(intent.stat().st_size <= 4*1024**2)
            plan = json.loads(intent.read_text())
            checksum = plan.pop('plan_sha256')
            require(hashlib.sha256(canonical(plan).encode()).hexdigest() == checksum, 'state-conflict')
            active = db.execute('SELECT active FROM pointers WHERE id=1').fetchone()[0]
            require(active == plan['previous'] and active != plan['target'], 'state-conflict')
            row = db.execute('SELECT state FROM updates WHERE id=?', (operation,)).fetchone()
            require(row is None or row[0] in ('intent', 'abandoned'), 'state-conflict')
            resolution = {'operation_id': operation, 'decision': 'keep-active', 'active': active,
                          'plan_sha256': checksum, 'replay_allowed': False, 'backup_preserved': True}
            if (root/'resolution.json').exists():
                require(json.loads(guard(root/'resolution.json').read_text()) == resolution, 'state-conflict')
            else: self.save(root/'resolution.json', resolution)
            db.execute('INSERT OR REPLACE INTO updates VALUES(?,?,?,?,?,?)',
                       (operation, plan['target'], active, checksum, 'abandoned', str(root)))
            return dict(resolution, state='abandoned')
