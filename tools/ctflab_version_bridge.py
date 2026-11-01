"""桌面版本管理固定桥接：签名暂存、停机门预览/切换、显式回退与启动；不替换Mac更新器。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import uuid
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text,MAX_MESSAGE_BYTES,ContractError,public_error
from ctflab_generation_store import digest,private_directory
from ctflab_tls_endpoint import guard
from ctflab_release_launcher import read_json,ReleaseLauncher
from ctflab_release_store import ReleaseStore
from ctflab_release_update import UpdateCoordinator


def stable_caller(root):
    """管理入口必须独立于当前版本树；未知父进程身份不开放版本变更。"""
    from ctflab_qemu_driver import native_observe
    require(root/'versions' not in Path(__file__).resolve().parents
            and root/'versions' not in Path(sys.executable).resolve().parents,'permission-denied')
    observed=native_observe(os.getppid());path=Path(observed.image_path)
    return observed.state=='running' and root/'versions' not in path.parents


class VersionBridge:
    def __init__(self,config_path,*,system=platform.system,coordinator=UpdateCoordinator,launcher=ReleaseLauncher,spawn=None,caller=stable_caller):
        self.path=guard(Path(config_path).absolute());before=digest(self.path);config=read_json(self.path,16384)
        require(type(config) is dict and set(config)=={'schema','release_root','trusted_keys'}
            and type(config['schema']) is int and config['schema']==1)
        require(all(type(config[k]) is str and Path(config[k]).is_absolute() for k in ('release_root','trusted_keys')))
        root=guard(Path(config['release_root']));key_path=guard(Path(config['trusted_keys']))
        require(root!=key_path and root not in key_path.parents,'permission-denied')
        key_before=digest(key_path);self.keys=read_json(key_path,65536);require(key_before==digest(key_path),'identity-unknown');self.store=ReleaseStore(root);self.updates=coordinator(self.store)
        self.launcher=launcher(self.store,self.keys);self.system=system;self.spawn=spawn;self.caller=caller
        self.key_path=key_path;self.config_sha=before;self.key_sha=key_before;self.root_identity=[root.stat().st_dev,root.stat().st_ino]
        descriptor={'config_sha256':before,'keys_sha256':key_before,'root_identity':[root.stat().st_dev,root.stat().st_ino],
            'release_root':str(root),'trusted_keys':str(key_path)}
        require(before==digest(guard(self.path)),'identity-unknown')
        self.target=hashlib.sha256(canonical(descriptor).encode()).hexdigest()
    def writable(self):
        if self.system() not in ('Windows','Linux'):return False
        try:return self.caller(self.store.root) is True
        except (OSError,ValueError,RuntimeError):return False
    def check(self):
        require(digest(guard(self.path))==self.config_sha and digest(guard(self.key_path))==self.key_sha
            and [self.store.root.stat().st_dev,self.store.root.stat().st_ino]==self.root_identity,'identity-unknown')
    def status(self):
        self.check()
        value=self.store.status()
        with self.store.locked() as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            initialized={'workspaces','updates'}<=tables and (self.store.root/'launches').is_dir() and (self.store.root/'application.lock').is_file()
            workspaces=[{'instance_uuid':r[0],'path':r[1]} for r in db.execute('SELECT id,path FROM workspaces')] if 'workspaces' in tables else []
        writable=self.writable()
        self.check()
        return dict(value,target=self.target,read_only=not writable,requires_stable_manager=self.system() in ('Windows','Linux') and not writable,requires_initialize=not initialized,
            online_downloads=self.online().history(),
            workspaces=workspaces,updates=self.updates.recovery()['updates'] if initialized else [],
            launches=self.launcher.history()['launches'] if initialized else [],unregistered_workspaces_checked=False,
            original_mac_updater_preserved=True,automatic_stop=False)
    def online(self):
        from ctflab_release_online import OnlineRelease
        return OnlineRelease(self.store.root,self.keys,self.target,check=self.check)
    def launch(self,plan):
        args=[sys.executable,'-I','-B',str(Path(__file__).resolve()),'launch-worker','--config',str(self.path),
            '--target',self.target,'--plan-sha256',plan]
        if self.spawn is not None:self.spawn(args)
        else:
            from ctflab_bounded_log import spawn
            logs=self.store.root/('launcher-log-'+str(uuid.uuid4()));private_directory(logs);receiver=spawn(logs,'version-launch')
            flags={'creationflags':subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}
            try:subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=receiver.stdin,stderr=receiver.stdin,close_fds=True,**flags)
            finally:receiver.stdin.close()
        return {'state':'application-launch-requested','application_running_verified':False,'automatic_replay':False,'vm_stopped':False}
    def handle(self,value):
        self.check()
        require(type(value) is dict and type(value.get('action')) is str)
        action=value['action'];fields={'status':set(),'initialize':set(),'register':{'workspace'},
            'stage':{'source','manifest'},'update-preview':{'version'},'update-apply':{'version','operation_id','plan_sha256'},
            'launch-preview':set(),'launch':{'plan_sha256'},'abandon':{'operation_id'},
            'online-preview':{'source','maximum'},'online-download':{'source','maximum','plan_sha256','operation_id'},
            'online-restore':{'operation_id'},'online-cancel':{'operation_id','cancel_id'}}
        require(action in fields)
        required={'action'}|fields[action]|(set() if action=='status' else {'target'})
        require(required<=set(value)<=required|({'resume_sha256'} if action=='online-download' else set()))
        if action=='status':return self.status()
        require(value['target']==self.target,'identity-unknown')
        require(self.writable(),'unsupported-platform')
        if action=='initialize':result=self.updates.initialize()
        elif action=='register':
            require(type(value['workspace']) is str and Path(value['workspace']).is_absolute());result=self.updates.register(Path(value['workspace']))
        elif action=='stage':
            require(type(value['source']) is str and Path(value['source']).is_absolute()
                    and type(value['manifest']) is str and Path(value['manifest']).is_absolute())
            result=self.store.stage(Path(value['source']),read_json(Path(value['manifest'])),self.keys)
        elif action=='online-preview':result=self.online().preview(value['source'],value['maximum'])
        elif action=='online-download':
            result=self.online().prepare(value['source'],value['maximum'],value['plan_sha256'],value['operation_id'],resume_sha256=value.get('resume_sha256'))
        elif action=='online-restore':result=self.online().restore(value['operation_id'])
        elif action=='online-cancel':result=self.online().cancel(value['operation_id'],value['cancel_id'])
        elif action=='update-preview':result=self.updates.preview(value['version'])
        elif action=='update-apply':
            uuid_text(value['operation_id']);result=self.updates.apply(value['version'],value['operation_id'],value['plan_sha256'])
        elif action=='launch-preview':result=self.launcher.preview()
        elif action=='launch':
            plan=self.launcher.preview();require(plan['plan_sha256']==value['plan_sha256'],'state-conflict');result=self.launch(plan['plan_sha256'])
        else:uuid_text(value['operation_id']);result=self.updates.abandon(value['operation_id'])
        return dict(result,library_target=self.target,original_mac_updater_preserved=True,automatic_stop=False)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('bridge','launch-worker'))
    parser.add_argument('--config',type=Path,required=True);parser.add_argument('--target');parser.add_argument('--plan-sha256');args=parser.parse_args(argv)
    try:
        if args.action=='launch-worker':
            bridge=VersionBridge(args.config)
            require(bridge.target==args.target and bridge.system() in ('Windows','Linux'),'permission-denied')
            result=bridge.launcher.run(args.plan_sha256)
        else:
            require(args.target is None and args.plan_sha256 is None)
            raw=sys.stdin.buffer.read(MAX_MESSAGE_BYTES+1);require(len(raw)<=MAX_MESSAGE_BYTES)
            from ctflab_remote import decode
            payload=decode(raw)
            from ctflab_version_setup import VersionSetup,ACTIONS
            if payload.get('action') in ACTIONS:result=VersionSetup(args.config).handle(payload)
            else:result=VersionBridge(args.config).handle(payload)
        print(canonical(result));return 0
    except ContractError as error:
        print(canonical({'error':public_error(error.code),'state':'refused-or-unknown','preserved':True,'automatic_stop':False}));return 2
    except (OSError,ValueError,RuntimeError,TypeError,KeyError,sqlite3.Error):
        print(canonical({'state':'refused-or-unknown','preserved':True,'automatic_stop':False,'automatic_replay':False}));return 2


if __name__=='__main__':raise SystemExit(main())
