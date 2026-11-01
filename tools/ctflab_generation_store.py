"""私有实例的代次存储：完整复制、原子选择、引用保留；不启动或删除任何VM。"""
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import time
from datetime import datetime,timezone

from ctflab_contract import ContractError, canonical, require, uuid_text, integer
from ctflab_local_service import _guard_path, _windows_storage
from ctflab_scenario_v2 import instance_plan


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def _preparation_digest(path, cancelled, progress):
    """准备材料专用的逐块校验；返回None只表示请求取消，不记成摘要成功。"""
    result=hashlib.sha256();processed=0
    with Path(path).open('rb') as stream:
        while True:
            if cancelled():return None
            block=stream.read(1024*1024)
            if not block:break
            result.update(block);processed+=len(block);progress(processed)
    return None if cancelled() else result.hexdigest()


def private_directory(path):
    _guard_path(path)
    if os.name == 'nt':
        _windows_storage(path, create=True)
    else:
        path.mkdir(mode=0o700)


def regular(path):
    path = Path(path).absolute()
    _guard_path(path)
    require(stat.S_ISREG(path.stat().st_mode), 'permission-denied')
    return path


class GenerationStore:
    """基盘映射来自可信宿主，不从课程内容接受路径或命令。

    gate事务跨越磁盘副作用；ledger独立提交意图。崩溃释放gate锁但不重放意图。
    运行盘允许修改，恢复不以初始摘要冒充当前运行盘健康检查。
    """
    def __init__(self, root):
        self.root = Path(root).absolute()
        self.guard(self.root)
        with self.db() as db:
            row = db.execute('SELECT value FROM metadata WHERE key=?', ('config',)).fetchone()
            require(row is not None, 'persistence-failed')
            self.config = json.loads(row[0])

    @classmethod
    def create(cls, root, manifest, instance_uuid, assets, nvram=None):
        plan = instance_plan(manifest, instance_uuid)
        require(set(assets) == set(manifest['assets']))
        sources = {}
        for key, value in assets.items():
            path = regular(value)
            expected = manifest['assets'][key]['sha256']
            require(digest(path) == expected, 'state-conflict')
            sources[key] = {'path': str(path), 'sha256': expected, 'size': path.stat().st_size}
        nvram = nvram or {}
        expected_nodes = {k for k, v in manifest['nodes'].items() if v['firmware'] == 'uefi'}
        require(set(nvram) == expected_nodes, 'capability-unverified')
        firmware = {}
        for key, value in nvram.items():
            path = regular(value)
            firmware[key] = {'path': str(path), 'sha256': digest(path), 'size': path.stat().st_size}
        root = Path(root).absolute()
        # 禁止来源位于即将管理的新状态根中。
        require(all(root != Path(v['path']) and root not in Path(v['path']).parents
                    for v in [*sources.values(), *firmware.values()]), 'permission-denied')
        # 缓存资产在创建实例之前持久登记引用，避免GC预览与实例准备之间出现窗口。
        # 创建失败也保留引用，不能因异常自动回收仍作为失败现场来源的资产。
        cache_references=[]
        for value in [*sources.values(),*firmware.values()]:
            path=Path(value['path'])
            cache_root=path.parent.parent
            if path.parent.name=='objects' and path.name==value['sha256'] and (cache_root/'cache.sqlite3').exists():
                from ctflab_content_cache import ContentCache
                owner='instance-'+plan['instance_uuid']
                ContentCache(cache_root).pin(owner,value['sha256'])
                cache_references.append({'root':str(cache_root),'owner':owner,'sha256':value['sha256']})
        private_directory(root)
        private_directory(root / 'generations')
        config = {'manifest': manifest, 'instance_uuid': plan['instance_uuid'],
                  'assets': sources, 'nvram': firmware}
        if any('vmgenid' in node for node in plan['manifest']['nodes'].values()):
            from ctflab_vmgenid import initialize
            config['vmgenid'] = initialize(root)
        if cache_references:config['cache_references']=cache_references
        for name, schema in [('ledger.sqlite3', '''
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE generations(number INTEGER NOT NULL,operation TEXT PRIMARY KEY,state TEXT NOT NULL,
              plan TEXT NOT NULL,files TEXT);
            CREATE TABLE operations(id TEXT PRIMARY KEY,action TEXT NOT NULL,generation INTEGER NOT NULL,
              state TEXT NOT NULL,result TEXT);
            CREATE TABLE effects(operation TEXT,node TEXT,action TEXT,state TEXT,result TEXT,
              PRIMARY KEY(operation,node,action));
            '''), ('gate.sqlite3', 'CREATE TABLE gate(id INTEGER)')]:
            path = root / name
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            with closing(sqlite3.connect(path)) as db:
                db.executescript(schema)
                if name == 'ledger.sqlite3':
                    db.executemany('INSERT INTO metadata VALUES(?,?)',
                                   [('config', canonical(config)), ('active', '0')])
                db.commit()
        return cls(root)

    def guard(self, path):
        path = Path(path)
        require(path == self.root or self.root in path.parents, 'permission-denied')
        _guard_path(path)
        info = path.stat()
        if os.name == 'nt':
            _windows_storage(path, root=path.is_dir())
        else:
            require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0,
                    'permission-denied')

    @contextmanager
    def db(self, gate=False, write=False):
        path = self.root / ('gate.sqlite3' if gate else 'ledger.sqlite3')
        self.guard(self.root)
        self.guard(path)
        db = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=0, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE' if gate or write else 'BEGIN')
            yield db
            db.commit()
        finally:
            db.close()

    @contextmanager
    def locked(self):
        try:
            with self.db(gate=True):
                yield
        except sqlite3.OperationalError as exc:
            raise ContractError('resource-busy' if 'locked' in str(exc) else 'persistence-failed') from None

    def snapshot(self):
        with self.db() as db:
            active = int(db.execute("SELECT value FROM metadata WHERE key='active'").fetchone()[0])
            generations = [dict(r) for r in db.execute('SELECT number,operation,state FROM generations ORDER BY number')]
            unresolved = [dict(r) for r in db.execute("SELECT id,action,generation FROM operations WHERE state='intent'")]
        return {'instance_uuid': self.config['instance_uuid'], 'active_generation': active,
                'generations': generations, 'unresolved': unresolved, 'automatic_replay': False,
                'deletion_available': False}

    def plan(self, generation):
        return instance_plan(self.config['manifest'], self.config['instance_uuid'], generation=generation)

    def node_paths(self, generation, node):
        plan = self.plan(generation)
        require(node in plan['resources'])
        with self.db() as db:
            rows = db.execute("SELECT operation FROM generations WHERE number=? AND state='prepared'", (generation,)).fetchall()
        require(len(rows) == 1, 'identity-unknown')
        directory = self.root / 'generations' / (str(generation) + '-' + rows[0][0]) / node
        result = {'disk': directory / 'disk.qcow2'}
        if plan['resources'][node]['nvram']:
            result['nvram'] = directory / 'nvram.fd'
        for path in result.values():
            self.guard(path)
        return result

    def begin(self, operation, action, generation):
        uuid_text(operation)
        require(action in ('prepare', 'reset', 'start', 'stop'))
        with self.db(write=True) as db:
            old = db.execute('SELECT * FROM operations WHERE id=?', (operation,)).fetchone()
            if old:
                require(old['action'] == action and old['generation'] == generation, 'idempotency-conflict')
                require(old['result'] is not None, 'identity-unknown')
                return json.loads(old['result'])
            if action in ('prepare','reset') and (self.root/'storage-bind.intent.json').exists():
                from ctflab_storage_bind import assert_closed,read_json
                assert_closed(self.root,read_json(self.root/'runtime-profile.json'),instance=self.config['instance_uuid'])
            require(not db.execute("SELECT 1 FROM operations WHERE state='intent'").fetchone(), 'identity-unknown')
            db.execute('INSERT INTO operations VALUES(?,?,?,?,NULL)', (operation, action, generation, 'intent'))
        return None

    def finish(self, operation, result):
        with self.db(write=True) as db:
            count = db.execute("UPDATE operations SET state='completed',result=? WHERE id=? AND state='intent'",
                               (canonical(result), operation)).rowcount
            require(count == 1, 'state-conflict')
        return result

    def effect(self, operation, node, action, result=None):
        with self.db(write=True) as db:
            if result is None:
                db.execute('INSERT INTO effects VALUES(?,?,?,?,NULL)', (operation, node, action, 'intent'))
            else:
                require(db.execute("UPDATE effects SET state='recorded',result=? WHERE operation=? AND node=? AND action=? AND state='intent'",
                                   (canonical(result), operation, node, action)).rowcount == 1, 'state-conflict')

    def preserve_initial_preparation(self, original, replacement):
        """调用方持locked；仅封存未选择的首次准备，不复制/覆盖/删除任何磁盘。"""
        uuid_text(original); uuid_text(replacement)
        require(original != replacement, 'idempotency-conflict')
        with self.db(write=True) as db:
            require(int(db.execute("SELECT value FROM metadata WHERE key='active'").fetchone()[0]) == 0,
                    'state-conflict')
            require(not db.execute('SELECT 1 FROM effects').fetchone(), 'identity-unknown')
            generations = db.execute('SELECT * FROM generations').fetchall()
            for candidate in generations:
                require(candidate['number'] == 1 and candidate['state'] in ('preparing', 'preserved'), 'identity-unknown')
                require(json.loads(candidate['plan']) == self.plan(1), 'identity-unknown')
                require(candidate['state'] == 'preserved' or candidate['operation'] == original, 'identity-unknown')
                owner = db.execute('SELECT * FROM operations WHERE id=?', (candidate['operation'],)).fetchone()
                require(owner is not None and owner['action'] == 'prepare' and owner['generation'] == 0, 'identity-unknown')
                if candidate['state'] == 'preserved': require(owner['state'] == 'completed', 'identity-unknown')
            pending = db.execute("SELECT * FROM operations WHERE state='intent'").fetchall()
            require(all(p['id'] == original and p['action'] == 'prepare' and p['generation'] == 0 for p in pending),
                    'identity-unknown')
            old = db.execute('SELECT * FROM operations WHERE id=?', (original,)).fetchone()
            require(old is None or old['action'] == 'prepare' and old['generation'] == 0, 'identity-unknown')
            # 独立收据保留既有result（包括取消），不把封存记成原准备成功。
            db.execute('CREATE TABLE IF NOT EXISTS preparation_restarts(original TEXT NOT NULL, replacement TEXT PRIMARY KEY, receipt TEXT NOT NULL)')
            receipt = {'original_operation': original, 'replacement_operation': replacement,
                       'active_generation': 0, 'preserved': True, 'automatic_replay': False}
            db.execute('INSERT INTO preparation_restarts VALUES(?,?,?)', (original, replacement, canonical(receipt)))
            if pending:
                db.execute("UPDATE operations SET state='completed',result=? WHERE id=? AND state='intent'",
                           (canonical(dict(receipt, state='preserved', generation=0)), original))
            db.execute("UPDATE generations SET state='preserved' WHERE operation=? AND state='preparing'", (original,))
        return receipt

    def prepare_generation(self, operation, expected, *, cancelled=lambda: False, checkpoint=lambda stage: None):
        """调用者必须持locked；校验/复制可取消，提交后不能假称取消。"""
        from ctflab_storage_boundary import check_profile
        storage=check_profile(self.root,self.config['instance_uuid'])
        def confirm_storage():
            current=check_profile(self.root,self.config['instance_uuid'])
            require((current or {}).get('binding_sha256')==(storage or {}).get('binding_sha256'),'identity-unknown')
        current = self.snapshot()['active_generation']
        require(current == expected, 'state-conflict')
        target = expected + 1
        plan = self.plan(target)
        required_bytes = sum(self.config['assets'][n['asset']]['size'] for n in plan['manifest']['nodes'].values())
        required_bytes += sum(v['size'] for v in self.config['nvram'].values())
        if storage is not None:require(storage['available_bytes']>=required_bytes+512*1024**2,'storage-insufficient')
        require(shutil.disk_usage(self.root).free >= required_bytes + 512 * 1024**2, 'storage-insufficient')
        with self.db(write=True) as db:
            db.execute('INSERT INTO generations VALUES(?,?,?,?,NULL)',
                       (target, operation, 'preparing', canonical(plan)))
        directory = self.root / 'generations' / (str(target) + '-' + operation)
        private_directory(directory)
        total_files=sum(1+(node in self.config['nvram']) for node in plan['start_order'])
        progress={'schema':1,'instance_uuid':self.config['instance_uuid'],'operation_id':operation,
                  'source_generation':expected,'target_generation':target,'node':None,'material':None,
                  'stage':'before-commit','bytes_processed':0,'total_bytes':0,
                  'files_completed':0,'total_files':total_files}
        last_report=[None,0,0.0]
        def report(stage, *, node=None, material=None, processed=0, total=0, force=True, db=None):
            progress.update(stage=stage,node=node,material=material,bytes_processed=processed,total_bytes=total)
            now=time.monotonic();identity=(stage,node,material)
            if not force and identity==last_report[0] and processed-last_report[1]<16*1024**2 and now-last_report[2]<1:
                return
            progress['updated_at']=datetime.now(timezone.utc).isoformat()
            if self._write_preparation_progress(progress,db=db) is False:return
            last_report[:]=[identity,processed,now]
        def cancel_result():
            report('cancelled',node=progress['node'],material=progress['material'],
                   processed=progress['bytes_processed'],total=progress['total_bytes'])
            return {'state':'cancelled','generation':expected,'preserved':True}
        files = {}
        for node in plan['start_order']:
            private_directory(directory / node)
            source_list = [('disk.qcow2','disk',self.config['assets'][plan['manifest']['nodes'][node]['asset']])]
            if node in self.config['nvram']:
                source_list.append(('nvram.fd','nvram',self.config['nvram'][node]))
            for name,material,source in source_list:
                confirm_storage()
                if cancelled():return cancel_result()
                origin=regular(source['path']);size=source['size']
                report('source-check',node=node,material=material,total=size)
                checksum=_preparation_digest(origin,cancelled,
                    lambda count:report('source-check',node=node,material=material,processed=count,total=size,force=False))
                if checksum is None:return cancel_result()
                require(checksum==source['sha256'],'state-conflict')
                destination=directory/node/name
                report('copy',node=node,material=material,total=size)
                fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                with os.fdopen(fd,'wb') as output,origin.open('rb') as stream:
                    processed=0
                    while True:
                        if cancelled():return cancel_result()
                        block=stream.read(1024*1024)
                        if not block:break
                        output.write(block);processed+=len(block)
                        report('copy',node=node,material=material,processed=processed,total=size,force=False)
                    output.flush();os.fsync(output.fileno())
                for stage,path in (('copy-check',destination),('source-recheck',origin)):
                    report(stage,node=node,material=material,total=size)
                    checksum=_preparation_digest(path,cancelled,
                        lambda count:report(stage,node=node,material=material,processed=count,total=size,force=False))
                    if checksum is None:return cancel_result()
                    require(checksum==source['sha256'],'state-conflict')
                files[f'{node}/{name}']=source['sha256'];progress['files_completed']+=1
                checkpoint('copied-'+node+'-'+name)
        report('before-commit')
        checkpoint('before-commit');confirm_storage()
        if cancelled():return cancel_result()
        result={'state':'prepared','generation':target,'preserved':True}
        with self.db(write=True) as db:
            require(int(db.execute("SELECT value FROM metadata WHERE key='active'").fetchone()[0])==expected,'state-conflict')
            db.execute("UPDATE generations SET state='prepared',files=? WHERE operation=?",(canonical(files),operation))
            db.execute("UPDATE metadata SET value=? WHERE key='active'",(str(target),))
            require(db.execute("UPDATE operations SET state='completed',result=? WHERE id=? AND state='intent'",
                               (canonical(result),operation)).rowcount==1,'state-conflict')
            # 完成进度与选择新代次同事务；提交后迟到取消不篡改已完成结果。
            report('completed',db=db)
        checkpoint('after-commit')
        return result

    def _write_preparation_progress(self, value, *, db=None):
        integer(value['bytes_processed']);integer(value['total_bytes'])
        require(value['bytes_processed']<=value['total_bytes'],'state-conflict')
        key='preparation-progress-'+uuid_text(value['operation_id'])
        if db is None:
            try:
                with self.db(write=True) as connection:
                    self._write_preparation_progress(value,db=connection)
            except sqlite3.OperationalError as exc:
                if 'locked' in str(exc):return False
                raise
            return True
        db.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)',(key,canonical(value)))
        return True

    def preparation_progress(self):
        """只读最近一次已保存进度；不证明工作器现在存活，不自动恢复。"""
        with self.db() as db:
            row=db.execute("SELECT key,value FROM metadata WHERE key LIKE 'preparation-progress-%' ORDER BY rowid DESC LIMIT 1").fetchone()
            if row is None:return None
            try:
                require(len(row['value'])<=4096,'identity-unknown');value=json.loads(row['value'])
                require(type(value) is dict and set(value)=={'schema','instance_uuid','operation_id','source_generation',
                    'target_generation','node','material','stage','bytes_processed','total_bytes','files_completed','total_files','updated_at'},'identity-unknown')
                uuid_text(value['operation_id']);require(row['key']=='preparation-progress-'+value['operation_id'],'identity-unknown')
                require(type(value['schema']) is int and value['schema']==1 and value['instance_uuid']==self.config['instance_uuid'],'identity-unknown')
                for field in ('source_generation','bytes_processed','total_bytes','files_completed'):integer(value[field])
                integer(value['target_generation'],1);integer(value['total_files'],1)
                require(value['target_generation']==value['source_generation']+1 and value['bytes_processed']<=value['total_bytes']
                    and value['files_completed']<=value['total_files'],'identity-unknown')
                require(value['stage'] in ('source-check','copy','copy-check','source-recheck','before-commit','completed','cancelled'),'identity-unknown')
                require((value['node'] is None and value['material'] is None) or
                    (value['node'] in self.config['manifest']['nodes'] and value['material'] in ('disk','nvram')),'identity-unknown')
                stamp=datetime.fromisoformat(value['updated_at']);require(stamp.tzinfo is not None,'identity-unknown')
                operation=db.execute('SELECT * FROM operations WHERE id=?',(value['operation_id'],)).fetchone()
                generation=db.execute('SELECT * FROM generations WHERE operation=?',(value['operation_id'],)).fetchone()
                require(operation is not None and operation['action'] in ('prepare','reset') and operation['generation']==value['source_generation']
                    and generation is not None and generation['number']==value['target_generation'],'identity-unknown')
                require(value['total_files']==sum(1+(node in self.config['nvram']) for node in self.config['manifest']['nodes']),'identity-unknown')
                if value['node'] is not None:
                    source=(self.config['assets'][self.config['manifest']['nodes'][value['node']]['asset']] if value['material']=='disk' else self.config['nvram'].get(value['node']))
                    require(source is not None and value['total_bytes']==source['size'],'identity-unknown')
                else:require(value['total_bytes']==0 and value['bytes_processed']==0 and value['stage'] in ('before-commit','completed','cancelled'),'identity-unknown')
                if value['stage']=='before-commit':require(value['files_completed']==value['total_files'],'identity-unknown')
                if value['stage']=='completed':
                    require(operation['state']=='completed' and generation['state']=='prepared' and value['files_completed']==value['total_files'],'identity-unknown')
            except (ValueError,TypeError,KeyError,AttributeError):
                raise ContractError('identity-unknown') from None
        return dict(value,historical=True,current_runtime_verified=False,automatic_replay=False)
