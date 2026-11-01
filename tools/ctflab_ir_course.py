"""C06 Windows自建应用应急课程：明确触发、自有事件、保全、派生处置；不操作VM生命周期。"""
import argparse
from datetime import datetime,timezone
import hashlib
from http.server import BaseHTTPRequestHandler,HTTPServer
import html
import os
from pathlib import Path
import re
import secrets
import sys
import time
import uuid

sys.dont_write_bytecode=True
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text,ContractError
from ctflab_generation_store import private_directory,digest
from ctflab_tls_endpoint import guard
from ctflab_windows_recovery import record,command_lock
from ctflab_waf_course import read,fingerprint,HeaderBudget
from ctflab_windows_course_events import WindowsEvents

MAX_CHANGES=32
HEALTHY={'schema':1,'maintenance':False,'support_contact':'help@ctflab.invalid'}
INCIDENT={'schema':1,'maintenance':True,'support_contact':'unverified-help@ctflab.invalid'}


def timestamp():return datetime.now(timezone.utc).isoformat()


def checked_time(value):
    require(type(value) is str and len(value)<=40,'identity-unknown')
    parsed=datetime.fromisoformat(value);require(parsed.tzinfo is not None and parsed.utcoffset()==timezone.utc.utcoffset(None),'identity-unknown')
    return value


def app_settings(value):
    require(type(value) is dict and set(value)==set(HEALTHY) and type(value['schema']) is int and value['schema']==1
        and type(value['maintenance']) is bool and value['support_contact'] in (HEALTHY['support_contact'],INCIDENT['support_contact']))
    return value


def settings(value):
    fields={'schema','lab_uuid','machine_uuid','generation','port','allow_eventlog','origin'}
    require(type(value) is dict and set(value)==fields and type(value['schema']) is int and value['schema']==1)
    uuid_text(value['lab_uuid']);uuid_text(value['machine_uuid'])
    require(type(value['generation']) is int and 1<=value['generation']<=2**31-1 and type(value['allow_eventlog']) is bool)
    require(type(value['port']) is int and 1024<=value['port']<=65535 and value['port'] not in (2375,2376)
        and not 5900<=value['port']<=5999,'permission-denied')
    origin=value['origin']
    if origin is not None:
        require(type(origin) is dict and set(origin)=={'capture_sha256','lab_uuid','native_windows_api_executed'}
            and type(origin['capture_sha256']) is str and re.fullmatch('[0-9a-f]{64}',origin['capture_sha256'])
            and type(origin['native_windows_api_executed']) is bool);uuid_text(origin['lab_uuid'])
    return value


def sealed(path,value):
    guard(path.parent);raw=canonical(value).encode()
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    if os.name!='nt':path.chmod(0o400)


class Lab:
    def __init__(self,root,*,machine=None,event_factory=None):
        self.root=guard(Path(root).absolute());self.config=settings(read(self.root/'lab.json'))
        self.runtime=read(self.root/'runtime-manifest.json');self.key=read(self.root/'key.json')
        require(set(self.key)=={'key'} and type(self.key['key']) is str and re.fullmatch('[0-9a-f]{64}',self.key['key']))
        self.machine=machine;self.event_factory=event_factory;self.guard_base()
    def guard_base(self):
        require(settings(read(self.root/'lab.json'))==self.config and read(self.root/'key.json')==self.key
            and read(self.root/'runtime-manifest.json')==self.runtime,'identity-unknown')
        require(set(self.runtime)=={'schema','files'} and type(self.runtime['schema']) is int and self.runtime['schema']==1
            and type(self.runtime['files']) is dict and 1<=len(self.runtime['files'])<=256,'identity-unknown')
        required={'ctflab_ir_course.py','ctflab_windows_course_events.py','ctflab_waf_course.py','ctflab_external.py'}
        require(required<=set(self.runtime['files']),'identity-unknown');runtime=guard(self.root/'runtime');total=0
        require({p.name for p in runtime.iterdir()}==set(self.runtime['files']),'identity-unknown')
        for name,sha in self.runtime['files'].items():
            require(type(name) is str and re.fullmatch('ctflab_[a-z0-9_]+\\.py',name)
                and type(sha) is str and re.fullmatch('[0-9a-f]{64}',sha),'identity-unknown')
            path=guard(runtime/name);total+=path.stat().st_size
            require(total<=32*1024**2 and path.is_file() and path.stat().st_nlink==1 and digest(path)==sha,'identity-unknown')
        if self.config['origin'] is not None:
            origin=self.config['origin'];completed=read(self.root/'derivation.complete.json')
            require(canonical(completed)==canonical({'schema':1,'capture_sha256':origin['capture_sha256'],
                'config_sha256':fingerprint(self.config)}),'identity-unknown')
            manifest,_,_=evidence(self.root/'evidence-original',origin['capture_sha256'])
            require(manifest['lab_uuid']==origin['lab_uuid']
                and manifest['native_windows_api_executed'] is origin['native_windows_api_executed'],'identity-unknown')
        if self.machine is None:
            require(os.name=='nt' and Path(__file__).resolve().parent==runtime,'unsupported-platform')
            from ctflab_external import native_machine
            value=native_machine()
        else:value=self.machine()
        require(type(value) is dict and value.get('machine_uuid')==self.config['machine_uuid'],'identity-unknown')
    def owner(self):
        info=self.root.stat()
        return {'schema':1,'root_identity':[info.st_dev,info.st_ino],'config_sha256':fingerprint(self.config),
            'runtime_sha256':fingerprint(self.runtime),'key_sha256':fingerprint(self.key),'native_guest_verified':self.machine is None}
    def guard(self):
        self.guard_base();require(canonical(read(self.root/'owner.json'))==canonical(self.owner()),'identity-unknown')
    def activate(self):
        self.guard_base()
        with command_lock(self.root):
            path=self.root/'owner.json';value=self.owner()
            if path.exists() or path.is_symlink():require(canonical(read(path))==canonical(value),'identity-unknown')
            else:record(path,value)
        return {'state':'c06-lab-activated','native_guest_verified':self.machine is None,'eventlog_written':False,'vm_lifecycle_changed':False}
    def scope(self):return {key:self.config[key] for key in ('lab_uuid','machine_uuid','generation')}
    def events(self):
        self.guard();require(self.config['allow_eventlog'],'permission-denied')
        if self.event_factory:return self.event_factory(self.scope(),self.key['key'])
        return WindowsEvents(self.scope(),self.key['key'])
    def head(self):
        value=read(self.root/'HEAD.json')
        require(set(value)=={'schema','lab_uuid','generation','revision','version','settings_sha256'}
            and type(value['schema']) is int and value['schema']==1 and value['lab_uuid']==self.config['lab_uuid']
            and type(value['generation']) is int and value['generation']==self.config['generation']
            and type(value['revision']) is int and 0<=value['revision']<=MAX_CHANGES,'identity-unknown')
        if value['version'] in ('baseline','seed'):path=self.root/(value['version']+'-settings.json')
        else:path=self.root/'operations'/uuid_text(value['version'])/'settings.json'
        data=app_settings(read(path));require(digest(path)==value['settings_sha256'],'identity-unknown')
        return value,data
    def intent(self,directory):
        value=read(directory/'intent.json')
        fields={'schema','lab_uuid','generation','action','before','after','after_sha256','owner_sha256','origin','before_head_sha256',
            'plan_sha256','automatic_replay','operation_id','intent_at'}
        require(set(value)==fields and type(value['schema']) is int and value['schema']==1
            and value['lab_uuid']==self.config['lab_uuid'] and type(value['generation']) is int
            and value['generation']==self.config['generation'] and value['operation_id']==directory.name
            and value['action'] in ('incident','repair','reset') and value['automatic_replay'] is False
            and value['owner_sha256']==fingerprint(self.owner()) and canonical(value['origin'])==canonical(self.config['origin']),'identity-unknown')
        checked_time(value['intent_at'])
        after=app_settings(value['after']);require(after==(INCIDENT if value['action']=='incident' else HEALTHY)
            and value['after_sha256']==hashlib.sha256(canonical(after).encode()).hexdigest(),'identity-unknown')
        plan={key:item for key,item in value.items() if key not in ('plan_sha256','automatic_replay','operation_id','intent_at')}
        require(fingerprint(plan)==value['plan_sha256'],'identity-unknown')
        return value
    def journal(self):
        paths=[]
        for path in guard(self.root/'operations').iterdir():
            require(len(paths)<MAX_CHANGES,'storage-insufficient');uuid_text(path.name);guard(path)
            require(path.is_dir(),'identity-unknown');paths.append(path)
        rows=[]
        for path in sorted(paths):
            intent=self.intent(path) if (path/'intent.json').exists() else None
            receipt=read(path/'receipt.json') if (path/'receipt.json').exists() else None
            rows.append({'operation_id':path.name,'intent':intent,'receipt':receipt,
                'native_attempted':(path/'native-attempt.json').exists()})
        return rows
    def status(self):
        self.guard();head,data=self.head();journal=self.journal()
        return {'state':'maintenance' if data['maintenance'] else 'serving','head':head,'settings':data,
            'pending':[row['operation_id'] for row in journal if row['receipt'] is None],
            'native_guest_verified':self.machine is None,'system_health_verified':False,'vm_lifecycle_changed':False}
    def _plan(self,action):
        require(action in ('incident','repair','reset'));head,current=self.head();journal=self.journal()
        require(not any(row['receipt'] is None for row in journal),'resource-busy')
        require(len(journal)<MAX_CHANGES and head['revision']<MAX_CHANGES,'storage-insufficient')
        if action=='incident':require(not current['maintenance'],'state-conflict');after=dict(INCIDENT)
        else:after=app_settings(read(self.root/'baseline-settings.json'));require(after==HEALTHY,'identity-unknown')
        if action=='repair':require(current['maintenance'] and self.config['origin'] is not None,'permission-denied')
        value={'schema':1,'lab_uuid':self.config['lab_uuid'],'generation':self.config['generation'],'action':action,
            'before':head,'before_head_sha256':digest(self.root/'HEAD.json'),'after':after,'after_sha256':hashlib.sha256(canonical(after).encode()).hexdigest(),
            'owner_sha256':fingerprint(self.owner()),'origin':self.config['origin']}
        return dict(value,plan_sha256=fingerprint(value),automatic_replay=False)
    def preview(self,action):
        self.guard()
        with command_lock(self.root):return self._plan(action)
    def commit(self,directory,intent):
        before,current=self.head();after=intent['after'];operation=intent['operation_id']
        require(digest(directory/'settings.json')==intent['after_sha256'],'identity-unknown')
        expected={'schema':1,'lab_uuid':self.config['lab_uuid'],'generation':self.config['generation'],
            'revision':intent['before']['revision']+1,'version':operation,'settings_sha256':intent['after_sha256']}
        require(before in (intent['before'],expected),'identity-unknown')
        if before!=expected:
            require(digest(self.root/'HEAD.json')==intent['before_head_sha256'],'identity-unknown')
            pending=directory/'head.commit.json';record(pending,expected);os.replace(pending,self.root/'HEAD.json')
        result={'state':'course-change-applied','operation_id':operation,'action':intent['action'],
            'plan_sha256':intent['plan_sha256'],'after':expected,'native_event_submitted':True,
            'native_windows_api_executed':self.machine is None and self.event_factory is None and self.events().is_native,'current_system_health_verified':False,
            'vm_lifecycle_changed':False,'automatic_replay':False,'receipt_observed_at':timestamp()}
        receipt=directory/'receipt.json'
        if receipt.exists():
            original=read(receipt);checked_time(original['receipt_observed_at'])
            require({k:v for k,v in original.items() if k!='receipt_observed_at'}=={k:v for k,v in result.items() if k!='receipt_observed_at'},'identity-unknown')
            result=original
        else:record(receipt,result)
        return result
    def apply(self,action,operation,expected):
        self.guard();uuid_text(operation)
        with command_lock(self.root):
            directory=self.root/'operations'/operation
            if directory.exists():
                intent=self.intent(directory);require(intent['action']==action and intent['plan_sha256']==expected,'idempotency-conflict')
                require((directory/'receipt.json').exists(),'state-conflict')
                result=read(directory/'receipt.json');require(result['operation_id']==operation
                    and result['action']==action and result['plan_sha256']==expected and result['after']['lab_uuid']==self.config['lab_uuid'],'identity-unknown')
                return dict(result,original_result=True,current_state_verified=False)
            plan=self._plan(action);require(plan['plan_sha256']==expected,'state-conflict');events=self.events()
            private_directory(directory);intent=dict(plan,operation_id=operation,intent_at=timestamp())
            record(directory/'intent.json',intent)
            before_bytes=(self.root/'HEAD.json').read_bytes()
            fd=os.open(directory/'before-head.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(before_bytes);stream.flush();os.fsync(stream.fileno())
            require(digest(directory/'before-head.json')==plan['before_head_sha256'],'identity-unknown')
            sealed(directory/'settings.json',plan['after'])
            record(directory/'native-attempt.json',{'operation_id':operation,'plan_sha256':expected,'automatic_replay':False,'attempt_at':timestamp()})
            events.report(action,operation,plan['after_sha256'])
            return self.commit(directory,intent)
    def _observation(self,operation):
        uuid_text(operation);directory=guard(self.root/'operations'/operation);intent=self.intent(directory)
        require(intent['operation_id']==operation and intent['lab_uuid']==self.config['lab_uuid']
            and intent['generation']==self.config['generation'] and (directory/'native-attempt.json').exists(),'identity-unknown')
        attempt=read(directory/'native-attempt.json')
        require(set(attempt)=={'operation_id','plan_sha256','automatic_replay','attempt_at'}
            and attempt['operation_id']==operation and attempt['plan_sha256']==intent['plan_sha256']
            and attempt['automatic_replay'] is False,'identity-unknown');checked_time(attempt['attempt_at'])
        head,current=self.head();events=self.events().records()
        matching=[row for row in events if row['operation_id']==operation and row['action']==intent['action']
            and row['state_sha256']==intent['after_sha256']]
        value={'operation_id':operation,'intent_sha256':fingerprint(intent),'head':head,'head_sha256':digest(self.root/'HEAD.json'),'matching_events':matching,
            'settings_sha256':digest(directory/'settings.json'),'receipt_present':(directory/'receipt.json').exists(),
            'automatic_event_replay':False}
        return dict(value,observation_sha256=fingerprint(value))
    def resume_preview(self,operation):
        self.guard()
        with command_lock(self.root):return self._observation(operation)
    def resume(self,operation,expected):
        self.guard()
        with command_lock(self.root):
            value=self._observation(operation);require(value['observation_sha256']==expected
                and len(value['matching_events'])==1 and not value['receipt_present'],'state-conflict')
            directory=self.root/'operations'/operation;return self.commit(directory,self.intent(directory))
    def capture(self,destination):
        self.guard();destination=Path(destination).absolute()
        require(destination!=self.root and self.root not in destination.parents and destination not in self.root.parents,'permission-denied')
        with command_lock(self.root):
            self.guard();head,current=self.head();journal=self.journal();events=self.events()
            token=fingerprint({'head':head,'journal':journal});private_directory(destination)
            current_path=self.root/(head['version']+'-settings.json') if head['version'] in ('baseline','seed') else self.root/'operations'/head['version']/'settings.json'
            sources={'lab.json':self.root/'lab.json','HEAD.json':self.root/'HEAD.json',
                'current-settings.json':current_path,'baseline-settings.json':self.root/'baseline-settings.json'}
            allowed={'intent.json','before-head.json','settings.json','native-attempt.json','head.commit.json','receipt.json'}
            for row in journal:
                for path in (self.root/'operations'/row['operation_id']).iterdir():
                    require(path.name in allowed,'identity-unknown');sources['operations/'+row['operation_id']+'/'+path.name]=path
            original_hashes={name:digest(guard(path)) for name,path in sources.items()}
            try:
                for name,path in sources.items():
                    require(path.is_file() and path.stat().st_nlink==1 and path.stat().st_size<=65536,'identity-unknown')
                    target=destination/name
                    if name.startswith('operations/'):
                        if not (destination/'operations').exists():private_directory(destination/'operations')
                        if not target.parent.exists():private_directory(target.parent)
                    data=path.read_bytes();fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
                    require(digest(target)==original_hashes[name],'identity-unknown')
                sealed(destination/'journal.json',{'operations':journal})
                native=events.collect(destination)
                require(type(native) is dict,'identity-unknown')
                require(native.get('selection_complete') is True and native.get('channel')=='Application'
                    and native.get('source')=='CTFLabC06' and type(native.get('native_windows_api_executed')) is bool,'identity-unknown')
                actual_native=self.machine is None and self.event_factory is None and native['native_windows_api_executed']
                record(destination/'native-events.json',native)
                require(token==fingerprint({'head':self.head()[0],'journal':self.journal()}),'identity-unknown')
                require(all(digest(path)==original_hashes[name] for name,path in sources.items()),'identity-unknown')
                names=list(sources)+['journal.json','native-events.json']+(['application.evtx'] if native['evtx'] is not None else [])
                manifest={'schema':1,'kind':'c06-course-capture','lab_uuid':self.config['lab_uuid'],
                    'generation':self.config['generation'],'head_revision':head['revision'],
                    'files':{name:{'sha256':digest(destination/name),'bytes':(destination/name).stat().st_size} for name in names},
                    'complete':True,'native_windows_api_executed':actual_native,
                    'native_guest_verified':self.machine is None,'source_unchanged':True,'key_or_teacher_included':False,
                    'external_clock_verified':False,'externally_anchored':False,'whole_system_capture':False}
                record(destination/'MANIFEST.json',manifest)
                return {'state':'course-evidence-captured','manifest_sha256':digest(destination/'MANIFEST.json'),
                    'complete':True,'native_windows_api_executed':actual_native,'original_modified':False}
            except (OSError,ValueError,RuntimeError):
                record(destination/'INCOMPLETE.json',{'state':'preserved-incomplete','automatic_retry':False,'original_modified':False});raise


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    def setup(self):super().setup();self.connection.settimeout(2);self.rfile=HeaderBudget(self.rfile)
    def log_message(self,*args):pass
    def do_GET(self):
        try:
            require(len(self.headers)<=32 and self.headers.get('Transfer-Encoding') is None
                and self.headers.get('Content-Length','0')=='0')
            status=self.server.lab.status()
            if self.path=='/health':code=200;value={'state':'process-listening','business_verified':False}
            elif self.path=='/':
                code=503 if status['settings']['maintenance'] else 200
                value={'state':status['state'],'message':'课程服务暂不可用' if code==503 else '课程服务正常',
                    'support_contact':status['settings']['support_contact']}
            else:code=404;value={'state':'unknown-route'}
        except (OSError,ValueError,RuntimeError,TypeError):code=503;value={'state':'refused-or-unknown'}
        raw=canonical(value).encode();self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(raw)
    def do_POST(self):self.send_error(405)


STUDENT='''# C06：Windows应用故障调查与派生副本处置

这是教师明确触发的自建应用配置事件，不是未知恶意软件或真实账户被窃。仅在教师给定的专用Windows来宾内进行。不要对宿主、其他来宾、账户或系统日志执行动作。

1. 分别访问课程服务和/health，解释业务503与进程健康200为何可同时发生。
2. 教师使用capture封存原现场；先核对清单及另存的摘要，再调查只读副本。对照HEAD、当前/基线配置、journal与Application EVTX中本课范围事件。
3. 按操作标识关联配置摘要、事件时间及本地提交；事件名表示变更准备，不单独证明配置已经提交。缺失事件、消息描述不可显示、时间偏移和回执未知分别如何处理？
4. 使用derive建立新lab_uuid的派生副本，明确指定目标来宾UUID/代次/新端口；只在派生副本预览并明确执行repair，再验证业务恢复200。原现场仍应为503，原封存摘要不变。
5. 使用reset恢复本课自己的配置基线，并复验。它不清Windows日志、不停止进程、不重置VM；整课VM重置仍由已有代次流程及教师权限决定。
6. 提交证据引用、时间线、事实与推断、派生处置及复验记录、遗漏范围。不得将本课Application自有事件说成全系统/安全日志调查或真实入侵证明。
'''
TEACHER='''# C06部署与独立真值

材料只有源码/模板，不含Windows镜像/Python/凭据。必须部署在绑定原生SMBIOS UUID的新专用Windows来宾，文件/ACL仅当前用户与SYSTEM。先用activate --execute建立当前根身份。只有材料时显式allow-eventlog，才允许本课向未注册的CTFLabC06源写Application；不创建/修改注册表项，发现任意已有同名注册源即拒绝。Windows可能不能显示消息描述，应按原始字段查看，不把描述错误当作记录不存在。不会写Security/System日志或清理任何日志。

incident只改变本课私有配置为maintenance=true并改为无效教学联系地址；服务/返回503而/health仍200。每次操作先保留intent/旧HEAD/新配置和Native尝试再报告事件，未知不重放。丢回执时以resume-preview重新观察精确事件/配置/原HEAD，接受当前摘要才可只补本地提交，不再ReportEvent。没有记录/多条匹配/状态变化均拒绝。事件HMAC绑定范围、操作与配置，不是防同用户恶意代码或整个系统攻陷的保证。

capture只选择本课Provider+lab_uuid+代次及有界RecordID范围，不收全安全日志；EVTX原件保留，HMAC密钥不导出。摘要另存，确认来源后才derive；派生使用当前可信源码/新UUID/新密钥，不执行捕获内文件或解析EVTX。repair只允许派生副本，原lab配置不改；reset只恢复本课基线并保留旧变更/Windows事件。不能替代真实Windows磁盘克隆、系统持久化排查、课程VM一致重置或干净机验收。
'''


def materials(source,destination,machine,generation,port,allow_eventlog,*,origin=None,initial=None,baseline=None):
    from ctflab_desktop_package import TOOLS
    config={'schema':1,'lab_uuid':str(uuid.uuid4()),'machine_uuid':machine,'generation':generation,'port':port,
        'allow_eventlog':allow_eventlog,'origin':origin};settings(config)
    initial=HEALTHY if initial is None else app_settings(initial);baseline=HEALTHY if baseline is None else app_settings(baseline)
    require(baseline==HEALTHY,'identity-unknown');source=Path(source);destination=Path(destination).absolute();payload={}
    for name in TOOLS:
        path=source/name
        if not path.is_file():path=source/'runtime'/Path(name).name
        payload['runtime/'+Path(name).name]=path.read_bytes()
    require(len(payload)==len(TOOLS) and sum(map(len,payload.values()))<=32*1024**2,'identity-unknown')
    runtime={'schema':1,'files':{Path(name).name:hashlib.sha256(raw).hexdigest() for name,raw in payload.items()}}
    head={'schema':1,'lab_uuid':config['lab_uuid'],'generation':generation,'revision':0,
        'version':'seed' if initial!=baseline else 'baseline','settings_sha256':hashlib.sha256(canonical(initial).encode()).hexdigest()}
    values={'lab.json':config,'runtime-manifest.json':runtime,'key.json':{'key':secrets.token_hex(32)},
        'baseline-settings.json':baseline,'seed-settings.json':initial,'HEAD.json':head,'control.lock':{}}
    private_directory(destination)
    for parent in ('runtime','operations','student','teacher'):private_directory(destination/parent)
    for name,raw in payload.items():
        fd=os.open(destination/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    for name,value in values.items():
        if name in ('baseline-settings.json','seed-settings.json'):sealed(destination/name,value)
        else:record(destination/name,value)
    for name,value in (('student/学生任务.md',STUDENT),('teacher/部署与真值.md',TEACHER)):
        with (destination/name).open('x',encoding='utf-8') as stream:stream.write(value)
        (destination/name).chmod(0o600)
    return {'state':'c06-source-materials-created','lab_uuid':config['lab_uuid'],'native_windows_verified':False,
        'eventlog_written':False,'service_started':False,'vm_lifecycle_changed':False}


def evidence(directory,expected):
    directory=guard(Path(directory).absolute());marker=guard(directory/'MANIFEST.json')
    require(marker.is_file() and marker.stat().st_nlink==1 and marker.stat().st_size<=65536,'identity-unknown')
    require(digest(marker)==expected,'identity-unknown')
    manifest=read(directory/'MANIFEST.json');require(manifest.get('kind')=='c06-course-capture' and manifest.get('complete') is True,'state-conflict')
    required={'lab.json','HEAD.json','current-settings.json','baseline-settings.json','journal.json','native-events.json'}
    require(type(manifest.get('files')) is dict and required<=set(manifest['files']) and len(manifest['files'])<=200,'identity-unknown')
    total=0
    for name,entry in manifest['files'].items():
        require(name in required|{'application.evtx'} or type(name) is str and re.fullmatch(r'operations/[0-9a-f-]{36}/(?:intent|before-head|settings|native-attempt|head\.commit|receipt)\.json',name),'permission-denied')
        if name.startswith('operations/'):uuid_text(name.split('/')[1])
        require(type(entry) is dict and set(entry)=={'sha256','bytes'} and type(entry['bytes']) is int
            and 0<=entry['bytes']<=16*1024**2,'identity-unknown')
        path=guard(directory/name);info=path.stat();total+=info.st_size
        require(path.is_file() and info.st_nlink==1 and info.st_size==entry['bytes'] and total<=32*1024**2
            and digest(path)==entry['sha256'],'identity-unknown')
    config=settings(read(directory/'lab.json'));head=read(directory/'HEAD.json');current=app_settings(read(directory/'current-settings.json'))
    baseline=app_settings(read(directory/'baseline-settings.json'))
    require(manifest['lab_uuid']==config['lab_uuid'] and manifest['generation']==config['generation']
        and head['lab_uuid']==config['lab_uuid'] and head['generation']==config['generation']
        and head['settings_sha256']==digest(directory/'current-settings.json') and baseline==HEALTHY,'identity-unknown')
    return manifest,current,baseline


def derive(source,capture,destination,expected,machine,generation,port,allow_eventlog):
    capture=guard(Path(capture).absolute());manifest,current,baseline=evidence(capture,expected)
    original_config=settings(read(capture/'lab.json'))
    require(uuid_text(machine)!=original_config['machine_uuid'],'permission-denied')
    destination=Path(destination).absolute()
    require(destination!=capture and capture not in destination.parents and destination not in capture.parents,'permission-denied')
    result=materials(source,destination,machine,generation,port,allow_eventlog,origin={'capture_sha256':expected,
        'lab_uuid':manifest['lab_uuid'],'native_windows_api_executed':manifest['native_windows_api_executed']},initial=current,baseline=baseline)
    original=destination/'evidence-original';private_directory(original)
    for name in (*manifest['files'],'MANIFEST.json'):
        target=original/name
        if name.startswith('operations/'):
            if not (original/'operations').exists():private_directory(original/'operations')
            if not target.parent.exists():private_directory(target.parent)
        data=(capture/name).read_bytes();fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        expected_file=expected if name=='MANIFEST.json' else manifest['files'][name]['sha256']
        require(digest(original/name)==expected_file and digest(guard(capture/name))==expected_file,'identity-unknown')
    require(digest(guard(capture/'MANIFEST.json'))==expected,'identity-unknown')
    evidence(original,expected)
    record(destination/'derivation.complete.json',{'schema':1,'capture_sha256':expected,
        'config_sha256':fingerprint(read(destination/'lab.json'))})
    return dict(result,state='c06-derived-materials-created',original_capture_modified=False,
        original_lab_uuid=manifest['lab_uuid'],new_guest_registration_required=True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    for name in ('materials','derive'):
        item=sub.add_parser(name);item.add_argument('--destination',type=Path,required=True)
        item.add_argument('--machine-uuid',required=True);item.add_argument('--generation',type=int,required=True)
        item.add_argument('--port',type=int,required=True);item.add_argument('--allow-eventlog',action='store_true')
        if name=='derive':item.add_argument('--capture',type=Path,required=True);item.add_argument('--manifest-sha256',required=True)
    for name in ('activate','status','preview','apply','resume-preview','resume','capture','serve'):
        item=sub.add_parser(name);item.add_argument('--run',type=Path,required=True)
        if name in ('activate','apply','resume'):item.add_argument('--execute',action='store_true')
        if name in ('preview','apply'):item.add_argument('--change',choices=('incident','repair','reset'),required=True)
        if name in ('apply','resume-preview','resume'):item.add_argument('--operation-id',required=True)
        if name=='apply':item.add_argument('--plan-sha256',required=True)
        if name=='resume':item.add_argument('--observation-sha256',required=True)
        if name=='capture':item.add_argument('--destination',type=Path,required=True)
        if name=='serve':item.add_argument('--duration',type=int,required=True)
    args=parser.parse_args(argv)
    try:
        source=Path(__file__).resolve().parent.parent
        if args.action=='materials':result=materials(source,args.destination,args.machine_uuid,args.generation,args.port,args.allow_eventlog)
        elif args.action=='derive':result=derive(source,args.capture,args.destination,args.manifest_sha256,args.machine_uuid,args.generation,args.port,args.allow_eventlog)
        else:
            lab=Lab(args.run)
            if args.action=='activate':require(args.execute);result=lab.activate()
            elif args.action=='status':result=lab.status()
            elif args.action=='preview':result=lab.preview(args.change)
            elif args.action=='apply':require(args.execute);result=lab.apply(args.change,args.operation_id,args.plan_sha256)
            elif args.action=='resume-preview':result=lab.resume_preview(args.operation_id)
            elif args.action=='resume':require(args.execute);result=lab.resume(args.operation_id,args.observation_sha256)
            elif args.action=='capture':result=lab.capture(args.destination)
            else:
                require(1<=args.duration<=3600);lab.guard();server=HTTPServer(('127.0.0.1',lab.config['port']),Handler)
                server.lab=lab;server.timeout=.25;deadline=time.monotonic()+args.duration
                try:
                    while time.monotonic()<deadline:server.handle_request()
                finally:server.server_close()
                result={'state':'course-service-ended','vm_stopped':False,'events_preserved':True}
        print(canonical(result));return 0
    except (OSError,ValueError,RuntimeError,TypeError,KeyError):
        print(canonical({'state':'refused-or-unknown','automatic_replay':False,'vm_stopped':False,'originals_preserved':True}));return 2


if __name__=='__main__':raise SystemExit(main())
