"""安装后显式准备新私有版本库；预览绑定公钥/位置，未知步骤只观察不重做。"""
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3

from ctflab_contract import canonical, require, uuid_text, identifier
from ctflab_generation_store import private_directory, digest
from ctflab_local_service import _guard_path
from ctflab_remote import decode, private_json
from ctflab_runtime_inventory import check_path
from ctflab_tls_endpoint import guard
from ctflab_windows_recovery import command_lock

ACTIONS = frozenset(('bootstrap-status', 'bootstrap-preview', 'bootstrap-create', 'bootstrap-resume'))
STEPS = ('store', 'keys', 'config')


def sha(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def new_json(path, value):
    guard(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write((canonical(value)+'\n').encode()); stream.flush(); os.fsync(stream.fileno())
    guard(path)


def identity(path):
    _guard_path(path); info = path.stat()
    return [info.st_dev, info.st_ino]


def public_keys(value):
    require(type(value) is dict and 1 <= len(value) <= 16)
    for name, key in value.items():
        identifier(name)
        require(type(key) is str and len(key) == 64 and all(c in '0123456789abcdef' for c in key))
    return value


def stable_location(root):
    """新的管理数据必须在当前安装入口/运行时/版本树之外，身份未知不创建。"""
    from ctflab_qemu_driver import native_observe
    from ctflab_version_bridge import stable_caller
    import sys
    require(stable_caller(root/'releases'), 'permission-denied')
    observed = native_observe(os.getppid())
    require(observed.state == 'running' and Path(observed.image_path).is_absolute(), 'identity-unknown')
    for parent in (Path(observed.image_path).parent, Path(sys.executable).resolve().parent, Path(__file__).resolve().parent):
        require(root != parent and parent not in root.parents, 'permission-denied')
    return True


class VersionSetup:
    def __init__(self, config, *, system=platform.system, caller=stable_location, checkpoint=lambda _: None):
        self.config = Path(config).absolute(); self.root = self.config.parent
        require(Path(config).is_absolute() and '..' not in self.config.parts and self.config.name == 'manager.json')
        _guard_path(self.config)
        self.system, self.caller, self.checkpoint = system, caller, checkpoint

    def available(self):return self.system() in ('Windows', 'Linux')

    def writable(self):
        if not self.available():return False
        try:return self.caller(self.root) is True
        except (OSError, ValueError, RuntimeError):return False

    def preview(self, source):
        require(self.available() and self.writable(), 'permission-denied')
        require(not self.root.exists() and not self.root.is_symlink(), 'state-conflict')
        path = Path(source); require(path.is_absolute() and '..' not in path.parts)
        info = check_path(path)
        require(path.is_file() and info.st_nlink == 1 and 0 < info.st_size <= 65536, 'permission-denied')
        with path.open('rb') as stream:raw = stream.read(65537)
        after = check_path(path)
        require(len(raw) == info.st_size and all(getattr(after, key) == getattr(info, key)
                for key in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')), 'identity-unknown')
        keys = public_keys(decode(raw)); parent = self.root.parent; missing = [self.root]
        while not parent.exists():
            require(len(missing) < 8, 'permission-denied'); missing.append(parent); parent = parent.parent
        _guard_path(parent); require(parent.is_dir(), 'permission-denied')
        if os.name != 'nt':require(not parent.stat().st_mode & 0o022, 'permission-denied')
        plan = {'schema': 1, 'config': str(self.config), 'root': str(self.root), 'platform': self.system(),
                'source': str(path), 'source_sha256': hashlib.sha256(raw).hexdigest(), 'keys_sha256': sha(keys),
                'keys_count': len(keys), 'ancestor': str(parent), 'ancestor_identity': identity(parent),
                'create_directories': [str(p) for p in reversed(missing)]}
        return plan, keys

    def read_intent(self):
        guard(self.root); value = private_json(self.root/'bootstrap.json')
        require(type(value) is dict and set(value) == {'schema', 'operation_id', 'plan', 'plan_sha256', 'keys', 'root_identity'}
                and type(value['schema']) is int and value['schema'] == 1, 'identity-unknown')
        uuid_text(value['operation_id']); plan = value['plan']
        require(type(plan) is dict and sha(plan) == value['plan_sha256'] and plan['root'] == str(self.root)
                and plan['config'] == str(self.config) and plan['platform'] == self.system()
                and identity(self.root) == value['root_identity']
                and sha(public_keys(value['keys'])) == plan['keys_sha256'], 'identity-unknown')
        return value

    def config_value(self):
        return {'schema': 1, 'release_root': str(self.root/'releases'), 'trusted_keys': str(self.root/'trusted-keys.json')}

    def binding(self, step, intent, *, fresh=False):
        """只读核对副作用；不能证明完整结果就保留unknown，不修复或重做。"""
        try:
            if step == 'store':
                from ctflab_release_store import ReleaseStore
                store = ReleaseStore(self.root/'releases')
                paths = [store.root/n for n in ('versions', 'staging', 'update-backups', 'launches', 'application.lock', 'releases.sqlite3')]
                for path in paths:guard(path)
                require(all(p.is_dir() for p in paths[:4]) and all(p.is_file() and p.stat().st_nlink == 1 for p in paths[4:]), 'identity-unknown')
                with store.locked() as db:
                    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    require({'versions', 'pointers', 'refs', 'workspaces', 'updates'} <= tables, 'identity-unknown')
                    require(db.execute('SELECT COUNT(*) FROM pointers').fetchone()[0] == 1, 'identity-unknown')
                    if fresh:
                        require(all(db.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] == 0
                                    for name in ('versions', 'refs', 'workspaces', 'updates'))
                                and db.execute('SELECT active,previous FROM pointers').fetchone() == (None, None)
                                and all(not any((store.root/n).iterdir()) for n in ('versions', 'staging', 'update-backups', 'launches')),
                                'identity-unknown')
                return {'root': identity(store.root), 'entries': {p.name: identity(p) for p in paths}}
            path = self.root/('trusted-keys.json' if step == 'keys' else 'manager.json')
            expected = intent['keys'] if step == 'keys' else self.config_value()
            guard(path)
            require(private_json(path) == expected and path.stat().st_nlink == 1, 'identity-unknown')
            require(digest(path) == hashlib.sha256((canonical(expected)+'\n').encode()).hexdigest(), 'identity-unknown')
            return {'identity': identity(path), 'sha256': digest(path)}
        except (OSError, ValueError, RuntimeError, TypeError, KeyError, sqlite3.Error):return None

    def marker(self, intent, step):
        return {'operation_id': intent['operation_id'], 'plan_sha256': intent['plan_sha256'], 'step': step}

    def summary(self, intent):
        phases = {}; all_done = True
        for step in STEPS:
            started = self.root/(step+'.intent.json'); complete = self.root/(step+'.complete.json')
            if complete.exists():
                require(private_json(started) == self.marker(intent, step), 'identity-unknown')
                value = private_json(complete); expected = dict(self.marker(intent, step), binding=self.binding(step, intent))
                require(value == expected and expected['binding'] is not None, 'identity-unknown'); phases[step] = 'completed'
            elif started.exists():
                require(private_json(started) == self.marker(intent, step), 'identity-unknown')
                phases[step] = 'outcome-unknown'; all_done = False
            else:phases[step] = 'pending'; all_done = False
        done = self.root/'bootstrap-complete.json'
        if done.exists():
            require(all_done and private_json(done) == self.marker(intent, 'all'), 'identity-unknown')
        ready = all_done and done.exists()
        return {'state': 'version-manager-prepared' if ready else 'setup-preserved', 'available': True,
                'read_only': not self.writable(), 'config': str(self.config), 'operation_id': intent['operation_id'],
                'plan_sha256': intent['plan_sha256'], 'steps': phases, 'ready': ready,
                'source_sha256': intent['plan']['source_sha256'], 'keys_sha256': intent['plan']['keys_sha256'],
                'keys_count': intent['plan']['keys_count'], 'automatic_replay': False, 'automatic_stop': False,
                'packages_installed': False, 'publisher_identity_verified': False}

    def advance(self, intent):
        from ctflab_release_store import ReleaseStore
        for step in STEPS:
            marker = self.marker(intent, step); started = self.root/(step+'.intent.json'); complete = self.root/(step+'.complete.json')
            if complete.exists():
                require(private_json(started) == marker, 'identity-unknown')
                require(private_json(complete) == dict(marker, binding=self.binding(step, intent))
                        and self.binding(step, intent) is not None, 'identity-unknown'); continue
            if started.exists():
                require(private_json(started) == marker, 'identity-unknown')
                observed = self.binding(step, intent, fresh=True)
                if observed is None:return self.summary(intent)
            else:
                new_json(started, marker); self.checkpoint('intent-'+step)
                if step == 'store':ReleaseStore.create(self.root/'releases')
                elif step == 'keys':new_json(self.root/'trusted-keys.json', intent['keys'])
                else:new_json(self.config, self.config_value())
                self.checkpoint('effect-'+step); observed = self.binding(step, intent, fresh=True)
                require(observed is not None, 'persistence-failed')
            new_json(complete, dict(marker, binding=observed)); self.checkpoint('complete-'+step)
        done = self.root/'bootstrap-complete.json'
        if not done.exists():new_json(done, self.marker(intent, 'all'))
        return self.summary(intent)

    def handle(self, payload):
        require(type(payload) is dict and payload.get('action') in ACTIONS)
        action = payload['action']
        if action == 'bootstrap-status':
            require(set(payload) == {'action'})
            if not self.available():return {'state': 'platform-read-only', 'available': False, 'read_only': True, 'original_mac_updater_preserved': True}
            if not self.root.exists():return {'state': 'not-configured', 'available': True, 'read_only': not self.writable(), 'ready': False}
            _guard_path(self.root)
            if not (self.root/'bootstrap.json').exists():return {'state': 'unrecognized-preserved', 'available': True, 'read_only': True, 'ready': False}
            with command_lock(self.root):return self.summary(self.read_intent())
        require(self.available() and self.writable(), 'permission-denied')
        if action in ('bootstrap-preview', 'bootstrap-create'):
            fields = {'action', 'public_keys'} | ({'operation_id', 'plan_sha256'} if action == 'bootstrap-create' else set())
            require(set(payload) == fields)
            plan, keys = self.preview(payload['public_keys']); checksum = sha(plan)
            if action == 'bootstrap-preview':return dict(plan, plan_sha256=checksum, publisher_identity_verified=False, created=False)
            operation = uuid_text(payload['operation_id']); require(payload['plan_sha256'] == checksum, 'state-conflict')
            require(identity(Path(plan['ancestor'])) == plan['ancestor_identity'], 'identity-unknown')
            for name in plan['create_directories']:private_directory(Path(name))
            new_json(self.root/'control.lock', {})
            with command_lock(self.root):
                intent = {'schema': 1, 'operation_id': operation, 'plan': plan, 'plan_sha256': checksum,
                          'keys': keys, 'root_identity': identity(self.root)}
                new_json(self.root/'bootstrap.json', intent); self.checkpoint('bootstrap-intent')
                return self.advance(intent)
        require(action == 'bootstrap-resume' and set(payload) == {'action', 'operation_id', 'plan_sha256'})
        with command_lock(self.root):
            intent = self.read_intent()
            require(uuid_text(payload['operation_id']) == intent['operation_id'] and payload['plan_sha256'] == intent['plan_sha256'], 'state-conflict')
            return self.advance(intent)
