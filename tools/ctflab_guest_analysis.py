"""专用来宾内离线分析：固定Zeek/Suricata入口，宿主主进程不解析PCAP或输出归档。"""
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import stat
import subprocess
import sys
import time
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))

from ctflab_contract import canonical,require,uuid_text
from ctflab_generation_store import digest,private_directory
from ctflab_tls_endpoint import guard


ANALYZER_WRAPPER = r'''#!/usr/bin/python3
import hashlib,json,os,re,signal,stat,subprocess,sys,time
from pathlib import Path
def verify_archive(expected):
    # 只在独立受限容器调用；不解包、不执行归档成员，宿主不导入tar解析器。
    import tarfile
    source=Path('/input/output.tar');info=source.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or not 1024<=info.st_size<=4*1024**2:raise ValueError('archive-size-or-type')
    def identity(value):return (value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
    def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('duplicate-json')
            value[key]=item
        return value
    def invalid(_):raise ValueError('invalid-json')
    def parse(raw):return json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)
    class BoundedInfo(tarfile.TarInfo):
        @classmethod
        def frombuf(cls,buf,encoding,errors):
            member=super().frombuf(buf,encoding,errors)
            if member.type not in (tarfile.REGTYPE,tarfile.AREGTYPE,tarfile.DIRTYPE,tarfile.XHDTYPE):raise ValueError('member-type')
            if not 0<=member.size<=3*1024**2 or member.type==tarfile.XHDTYPE and member.size>65536:raise ValueError('header-size')
            return member
    seen=set();entries=[];controls={};total=0;end=0
    fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
    with os.fdopen(fd,'rb') as stream:
        if identity(os.fstat(stream.fileno()))!=identity(info):raise ValueError('archive-changed')
        def digest_archive():
            stream.seek(0);sha=hashlib.sha256();count=0
            while block:=stream.read(65536):
                count+=len(block)
                if count>info.st_size:raise ValueError('archive-growth')
                sha.update(block)
            if count!=info.st_size:raise ValueError('archive-truncated')
            stream.seek(0);return sha.hexdigest()
        archive_sha=digest_archive()
        with tarfile.open(fileobj=stream,mode='r:',tarinfo=BoundedInfo) as archive:
            for member in archive:
                name=member.name.rstrip('/') if member.isdir() else member.name
                if (name in seen or len(seen)>=515 or name.startswith('/') or len(name)>1200
                    or any(not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',part) or part in ('.','..') for part in name.split('/'))
                    or name.split('/')[0]!='output' or len(name.split('/'))>10
                    or member.linkname or member.sparse is not None
                    or set(member.pax_headers)-{'path','mtime','atime','ctime','size','uid','gid','uname','gname'}):raise ValueError('member-path-or-identity')
                seen.add(name)
                if not 0<=member.size<=3*1024**2:raise ValueError('member-size')
                end=max(end,member.offset_data+((member.size+511)//512)*512)
                if member.isdir():
                    if member.size!=0:raise ValueError('directory-size')
                    continue
                if member.type not in (tarfile.REGTYPE,tarfile.AREGTYPE) or name=='output':raise ValueError('member-type')
                relative=name[len('output/'):];control=relative in ('status.json','output-manifest.json')
                limit=(16384 if relative=='status.json' else 1024**2) if control else 2*1024**2
                if member.size>limit:raise ValueError('member-size')
                sha=hashlib.sha256();count=0;raw=[]
                with archive.extractfile(member) as incoming:
                    while block:=incoming.read(65536):
                        count+=len(block)
                        if count>member.size:raise ValueError('member-growth')
                        sha.update(block)
                        if control:raw.append(block)
                if count!=member.size:raise ValueError('member-truncated')
                if control:controls[relative]=parse(b''.join(raw))
                else:
                    total+=count
                    if total>2*1024**2:raise ValueError('output-size')
                    entries.append({'name':relative,'bytes':count,'sha256':sha.hexdigest()})
        stream.seek(end);tail=stream.read(4*1024**2+1)
        if len(tail)<1024 or any(tail):raise ValueError('archive-trailer')
        if digest_archive()!=archive_sha or identity(os.fstat(stream.fileno()))!=identity(info):raise ValueError('archive-changed')
    if identity(source.lstat())!=identity(info):raise ValueError('archive-replaced')
    if set(controls)!={'status.json','output-manifest.json'}:raise ValueError('missing-control')
    status_value=controls['status.json'];manifest=controls['output-manifest.json'];entries.sort(key=lambda item:item['name'])
    content={'sha256':hashlib.sha256(encoded(entries)).hexdigest(),'files':len(entries),'bytes':total}
    if (not isinstance(status_value,dict) or hashlib.sha256(encoded(status_value)).hexdigest()!=expected
        or status_value.get('output_content')!=content or not isinstance(manifest,dict)
        or set(manifest)!={'schema','scope','files','bytes','content_sha256'} or type(manifest['schema']) is not int or manifest['schema']!=1
        or manifest['scope']!='all-output-file-names-and-bytes-excluding-wrapper-status-and-manifest'
        or manifest['files']!=entries or type(manifest['bytes']) is not int or manifest['bytes']!=total
        or manifest['content_sha256']!=content['sha256']):raise ValueError('content-mismatch')
    versions=[item for item in entries if item['name']=='version.report']
    if status_value.get('version_report_sha256') is not None and (len(versions)!=1 or versions[0]['sha256']!=status_value['version_report_sha256']):raise ValueError('version-report')
    return {'state':'archive-content-matches','status_sha256':expected,'archive_sha256':archive_sha,
            'archive_bytes':info.st_size,'output_content':content,'members':len(seen),'extracted':False}
if sys.argv[1:]==['archive']:
    import tarfile
    with tarfile.open(fileobj=sys.stdout.buffer,mode='w|',format=tarfile.PAX_FORMAT,dereference=False) as archive:
        archive.add('/output',arcname='output')
    raise SystemExit(0)
if len(sys.argv)==3 and sys.argv[1]=='verify-archive':
    import tarfile
    try:
        if not re.fullmatch(r'[0-9a-f]{64}',sys.argv[2]):raise ValueError('expected-status')
        print(json.dumps(verify_archive(sys.argv[2]),sort_keys=True,separators=(',',':')))
    except (OSError,ValueError,KeyError,TypeError,RuntimeError,tarfile.TarError):
        print('{"state":"archive-refused","extracted":false}');raise SystemExit(2)
    raise SystemExit(0)
status=Path('/output/status.json')
if sys.argv[1:]==['status']:
    print(status.read_text() if status.exists() else '{"state":"running"}');raise SystemExit(0)
# namespace的PID 1不会按普通进程语义采用默认SIGTERM；显式处理正常退出。
signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))
tool=sys.argv[1];timeout=int(sys.argv[2]);expected=sys.argv[3]
if tool not in ('zeek','suricata') or not 1<=timeout<=300 or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-.a-z0-9]+)?',expected):raise SystemExit(2)
args=(['/usr/local/zeek/bin/zeek','-C','-r','/input/capture.pcap'] if tool=='zeek' else
      ['/usr/bin/suricata','-r','/input/capture.pcap','-c','/config/suricata.yaml','-l','/output','--runmode','single'])
observed=None;version_sha=None;content=None
def stable(info):return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
def output_manifest():
    # 不解析日志内容；每个正常输出文件的名称与原字节都参与对照，保留时间戳差异。
    root=Path('/output');entries=[];total=0;visited=0;observed={}
    for directory,dirs,files in os.walk(root,followlinks=False):
        if len(Path(directory).relative_to(root).parts)>8:raise ValueError('depth')
        for name in dirs+files:
            visited+=1
            if visited>512 or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',name):raise ValueError('name-or-count')
            path=Path(directory)/name;info=path.lstat()
            observed[path.relative_to(root).as_posix()]=stable(info)
            if stat.S_ISDIR(info.st_mode):continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('file-type')
            # 这两个文件由wrapper在指纹生成后新建，不允许分析器预先伪造。
            relative=path.relative_to(root).as_posix()
            if relative in ('status.json','output-manifest.json'):raise ValueError('reserved')
            total+=info.st_size
            if total>2*1024**2:raise ValueError('size')
            sha=hashlib.sha256();fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
            with os.fdopen(fd,'rb') as stream:
                if stable(os.fstat(stream.fileno()))!=stable(info):raise ValueError('changed')
                count=0
                while block:=stream.read(65536):
                    count+=len(block)
                    if count>info.st_size:raise ValueError('growth')
                    sha.update(block)
                if count!=info.st_size or stable(os.fstat(stream.fileno()))!=stable(info):raise ValueError('changed')
            if stable(path.lstat())!=stable(info):raise ValueError('replaced')
            entries.append({'name':relative,'bytes':info.st_size,'sha256':sha.hexdigest()})
    after={}
    for directory,dirs,files in os.walk(root,followlinks=False):
        if len(Path(directory).relative_to(root).parts)>8:raise ValueError('depth')
        for name in dirs+files:
            if len(after)>=512:raise ValueError('count')
            path=Path(directory)/name;after[path.relative_to(root).as_posix()]=stable(path.lstat())
    if observed!=after:raise ValueError('tree-changed')
    entries.sort(key=lambda item:item['name'])
    encoded=json.dumps(entries,sort_keys=True,separators=(',',':')).encode()
    value={'schema':1,'scope':'all-output-file-names-and-bytes-excluding-wrapper-status-and-manifest',
           'files':entries,'bytes':total,'content_sha256':hashlib.sha256(encoded).hexdigest()}
    with (root/'output-manifest.json').open('x') as stream:
        json.dump(value,stream,sort_keys=True,separators=(',',':'));stream.flush();os.fsync(stream.fileno())
    return {'sha256':value['content_sha256'],'files':len(entries),'bytes':total}
try:
    # 版本核对与分析共同使用原预算；版本输出写入有界tmpfs，不无限capture_output。
    deadline=time.monotonic()+timeout
    report=Path('/output/version.report')
    with report.open('xb') as stream:
        result=subprocess.run([args[0],'--version' if tool=='zeek' else '-V'],cwd='/output',
            stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,timeout=min(5,timeout))
    if result.returncode!=0 or report.stat().st_size>4096:raise ValueError('version-output')
    raw=report.read_bytes();version_sha=hashlib.sha256(raw).hexdigest()
    text=raw.decode('ascii').strip()
    pattern=(r'zeek version ([0-9]+\.[0-9]+\.[0-9]+(?:[-.a-z0-9]+)?)' if tool=='zeek' else
             r'This is Suricata version ([0-9]+\.[0-9]+\.[0-9]+(?:[-.a-z0-9]+)?)(?: RELEASE)?')
    match=re.fullmatch(pattern,text)
    if not match or match[1]!=expected:raise ValueError('version-mismatch')
    observed=match[1];remaining=deadline-time.monotonic()
    if remaining<=0:raise subprocess.TimeoutExpired(args,timeout)
    with open('/output/tool.stderr','xb') as error:
        code=subprocess.run(args,cwd='/output',stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=error,timeout=remaining).returncode
except subprocess.TimeoutExpired:code=124
except OSError:code=125
except (ValueError,UnicodeError):code=126
try:content=output_manifest()
except (OSError,ValueError):code=127
with status.open('x') as out:
    json.dump({'state':'completed','returncode':code,'tool_version_observed':observed,
               'version_report_sha256':version_sha,'output_content':content},out);out.flush();os.fsync(out.fileno())
# 保留tmpfs供控制端封存；只在封存后由本次专用容器收到正常SIGTERM。
while True:time.sleep(60)
'''
WRAPPER_SHA256=hashlib.sha256(ANALYZER_WRAPPER.encode()).hexdigest()


def sha256_text(value):
    return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None


def decode_metadata(raw,limit):
    require(type(raw) in (str,bytes) and len(raw.encode() if isinstance(raw,str) else raw)<=limit,'identity-unknown')
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,'identity-unknown');result[key]=value
        return result
    def invalid(_):require(False,'identity-unknown')
    return json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)


def analysis_status(value,expected_version):
    require(type(value) is dict,'identity-unknown')
    if value=={'state':'running'}:return value
    require(set(value)=={'state','returncode','tool_version_observed','version_report_sha256','output_content'}
            and value['state']=='completed' and type(value['returncode']) is int,'identity-unknown')
    require(value['tool_version_observed'] in (None,expected_version)
            and (value['version_report_sha256'] is None or sha256_text(value['version_report_sha256'])),'identity-unknown')
    content=value['output_content']
    require(content is None or type(content) is dict and set(content)=={'sha256','files','bytes'}
            and sha256_text(content['sha256']) and type(content['files']) is int and 1<=content['files']<=512
            and type(content['bytes']) is int and 0<=content['bytes']<=2*1024**2,'identity-unknown')
    if value['returncode']==0:
        require(value['tool_version_observed']==expected_version and sha256_text(value['version_report_sha256'])
                and content is not None,'version-mismatch')
    return value


def compare_results(left,right):
    """只比较明确选定结果的元数据，不读取PCAP/tar或把报告匹配当原生验收。"""
    context=('instance_uuid','generation','policy_sha256','input_sha256','config_sha256','tool','tool_version','image','wrapper_sha256')
    for value in (left,right):
        require(type(value) is dict and value.get('state')=='analysis-completed' and type(value.get('returncode')) is int
                and value['returncode']==0,'capability-unverified')
        for name in ('operation_id','instance_uuid'):uuid_text(value.get(name))
        require(type(value.get('generation')) is int and value['generation']>=1 and value.get('tool') in ('zeek','suricata'))
        for name in ('policy_sha256','input_sha256','wrapper_sha256','version_report_sha256'):require(sha256_text(value.get(name)))
        require(value.get('wrapper_sha256')==WRAPPER_SHA256,'version-mismatch')
        require(isinstance(value.get('tool_version'),str) and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-.a-z0-9]+)?',value['tool_version']))
        require(isinstance(value.get('image'),str) and re.fullmatch(r'[a-z0-9][a-z0-9./:_-]{0,180}@sha256:[0-9a-f]{64}',value['image']))
        require(value.get('config_sha256') is None if value['tool']=='zeek' else sha256_text(value.get('config_sha256')))
        analysis_status({'state':'completed','returncode':0,'tool_version_observed':value.get('tool_version_observed'),
                         'version_report_sha256':value.get('version_report_sha256'),'output_content':value.get('output_content')},value['tool_version'])
    require(left['operation_id']!=right['operation_id'],'idempotency-conflict')
    require(all(left[name]==right[name] for name in context),'state-conflict')
    return {'state':'compared','scope':'reported-output-file-names-and-content-only','same_context':True,
            'same_output_content':left['output_content']==right['output_content'],
            'same_version_report':left['version_report_sha256']==right['version_report_sha256'],
            'left_operation_id':left['operation_id'],'right_operation_id':right['operation_id'],
            'reports_authenticated':False,'archives_extracted':False,'byte_reproducibility_verified':False,
            'analysis_findings_verified':False}


def pinned_result(path,expected_sha256):
    from ctflab_runtime_inventory import check_path,hash_file
    require(sha256_text(expected_sha256))
    path=Path(path).absolute();info=check_path(path)
    require(info.st_size<=65536 and hash_file(path,info)==expected_sha256,'state-conflict')
    with path.open('rb') as stream:raw=stream.read(65537)
    require(len(raw)<=65536)
    result=decode_metadata(raw,65536)
    require(hash_file(path,info)==expected_sha256,'state-conflict')
    return result


def image_materials(destination,base_image,tool,version):
    """仅生成不可覆盖的派生镜像配方，不下载/构建/运行镜像。"""
    require(type(base_image) is str and re.fullmatch(r'[a-z0-9][a-z0-9./:_-]{0,180}@sha256:[0-9a-f]{64}',base_image))
    require(tool in ('zeek','suricata') and type(version) is str and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-.a-z0-9]+)?',version))
    destination=Path(destination);destination.mkdir(mode=0o700)
    dockerfile=(f'FROM {base_image}\nUSER 0\nCOPY --chmod=0555 ctflab-analyzer /usr/local/bin/ctflab-analyzer\n'
        f'LABEL org.ctflab.analyzer.tool="{tool}" org.ctflab.analyzer.version="{version}" '
        f'org.ctflab.analyzer.wrapper-sha256="{WRAPPER_SHA256}"\nUSER 1000:1000\n')
    for name,data in (('ctflab-analyzer',ANALYZER_WRAPPER),('Dockerfile',dockerfile)):
        with (destination/name).open('x') as stream:stream.write(data)
    return {'state':'recipe-created','base_image':base_image,'wrapper_sha256':WRAPPER_SHA256,'image_built':False}


def settings(value,containers):
    require(type(value) is dict and set(value)=={'tool','tool_version','image','input_sha256','config_sha256','timeout_seconds','output_limit_mb'})
    require(value['tool'] in ('zeek','suricata') and type(value['tool_version']) is str
            and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-.a-z0-9]+)?',value['tool_version']))
    require(value['image'] in {spec['image'] for spec in containers.values()},'permission-denied')
    require(type(value['input_sha256']) is str and re.fullmatch('[0-9a-f]{64}',value['input_sha256']))
    if value['tool']=='zeek':require(value['config_sha256'] is None)
    else:require(type(value['config_sha256']) is str and re.fullmatch('[0-9a-f]{64}',value['config_sha256']))
    require(type(value['timeout_seconds']) is int and 1<=value['timeout_seconds']<=300
            and type(value['output_limit_mb']) is int and 1<=value['output_limit_mb']<=2)
    return json.loads(canonical(value))


def export_archive(backend,container_id,destination,limit):
    """仅流式保存不解包；越限/断线保留partial，只结束自有Docker客户端。"""
    from ctflab_guest_agent import TOOLS
    backend.guard();backend.check_tool('docker');guard(destination.parent)
    fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    process=None;count=0
    try:
        with os.fdopen(fd,'wb') as target:
            process=subprocess.Popen([TOOLS['docker'],'--host=unix:///var/run/docker.sock','--config',str(backend.state/'docker-config'),
                'container','exec','--user','1000:1000',container_id,'/usr/bin/python3','-I','-B','/usr/local/bin/ctflab-analyzer','archive'],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'},close_fds=True)
            with selectors.DefaultSelector() as poll:
                poll.register(process.stdout,selectors.EVENT_READ);deadline=time.monotonic()+20
                while True:
                    require(time.monotonic()<deadline,'control-unreachable')
                    if not poll.select(min(.2,max(0,deadline-time.monotonic()))):continue
                    block=os.read(process.stdout.fileno(),65536)
                    if not block:break
                    count+=len(block);require(count<=limit,'storage-insufficient');target.write(block)
            require(process.wait(timeout=2)==0,'backend-failed');target.flush();os.fsync(target.fileno())
        backend.guard()
        return {'bytes':count,'sha256':digest(destination),'format':'opaque-docker-tar','extracted':False}
    finally:
        if process is not None:
            if process.poll() is None:process.kill()
            process.wait(timeout=3)
            process.stdout.close()


class OfflineAnalysis:
    def __init__(self,agent,*,clock=time.monotonic,sleep=time.sleep,export=export_archive):
        self.agent=agent;self.backend=agent.backend;self.policy=agent.policy;self.clock=clock;self.sleep=sleep;self.export=export
        self.spec=settings(self.policy['analysis'],self.policy['containers'])

    def evidence(self,sha):
        path=guard(self.agent.root/'evidence'/sha)
        # 输入按原始字节校验，不尝试识别/解析PCAP或配置语法。
        info=path.stat();require(path.is_file() and info.st_nlink==1 and info.st_size<=256*1024**2
                and info.st_uid==0 and not info.st_mode&0o077 and digest(path)==sha,'identity-unknown')
        return path

    def prepare_inputs(self,operation):
        """原件保持私有/只读；专用0700父目录内建立容器UID可读的独立副本。"""
        from ctflab_runtime_inventory import signature,check_path
        uuid_text(operation)
        sources={sha:self.evidence(sha) for sha in (self.spec['input_sha256'],self.spec['config_sha256']) if sha}
        require(shutil.disk_usage(self.agent.root).free>=sum(p.stat().st_size for p in sources.values())+32*1024**2,'storage-insufficient')
        parent=self.agent.root/'analysis-input'
        if not parent.exists():self.agent.effect(operation,'analysis-input-parent',lambda:private_directory(parent))
        guard(parent);require(len(list(parent.iterdir()))<128,'storage-insufficient');directory=parent/operation
        self.agent.effect(operation,'analysis-input-directory',lambda:private_directory(directory))
        for sha,source in sources.items():
            def copy_input(source=source,sha=sha):
                info=check_path(source);target=directory/sha
                fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with source.open('rb') as incoming,os.fdopen(fd,'wb') as output:
                    require(signature(os.fstat(incoming.fileno()))==signature(info),'identity-unknown')
                    left=info.st_size
                    while left:
                        data=incoming.read(min(left,1024**2));require(bool(data),'identity-unknown');output.write(data);left-=len(data)
                    require(incoming.read(1)==b'' and signature(os.fstat(incoming.fileno()))==signature(info),'identity-unknown')
                    output.flush();os.fchmod(output.fileno(),0o444);os.fsync(output.fileno())
                require(signature(check_path(source))==signature(info) and digest(target)==sha,'identity-unknown')
                self.evidence(sha)
                return {'sha256':sha,'bytes':info.st_size,'original_modified':False}
            self.agent.effect(operation,'analysis-input-'+sha,copy_input)

    def input_copy(self,sha,operation):
        from ctflab_runtime_inventory import check_path,hash_file
        uuid_text(operation);self.evidence(sha)
        directory=guard(self.agent.root/'analysis-input'/operation);path=directory/sha;info=check_path(path)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.getuid()
            and stat.S_IMODE(info.st_mode)==0o444 and info.st_size<=256*1024**2 and hash_file(path,info)==sha,'identity-unknown')
        return path

    def inspect(self,identity,operation):
        rows=self.backend.json('docker',['container','inspect',identity])
        require(type(rows) is list and len(rows)==1 and rows[0].get('Id')==identity,'identity-unknown')
        value=rows[0];config=value.get('Config',{});host=value.get('HostConfig',{})
        labels=config.get('Labels',{})
        require(all(labels.get(k)==v for k,v in self.agent.labels.items())
                and labels.get('org.ctflab.analysis')==operation and config.get('Image')==self.spec['image']
                and config.get('User')=='1000:1000' and host.get('NetworkMode')=='none'
                and config.get('Entrypoint')==['/usr/bin/python3']
                and config.get('Cmd')==['-I','-B','/usr/local/bin/ctflab-analyzer',self.spec['tool'],str(self.spec['timeout_seconds']),self.spec['tool_version']]
                and config.get('Healthcheck',{}).get('Test')==['NONE']
                and host.get('ReadonlyRootfs') is True and host.get('Privileged') is False
                and host.get('CapAdd') in (None,[]) and host.get('CapDrop')==['ALL']
                and not host.get('Devices') and not host.get('PortBindings') and not host.get('Binds')
                and host.get('PidMode','')=='' and host.get('IpcMode','private') in ('','private')
                and host.get('Memory')==512*1024**2 and host.get('MemorySwap')==512*1024**2
                and host.get('NanoCpus')==10**9 and host.get('PidsLimit')==64
                and host.get('RestartPolicy',{}).get('Name')=='no'
                and any(v in ('no-new-privileges','no-new-privileges:true') for v in host.get('SecurityOpt',[])),'identity-unknown')
        expected={str(self.input_copy(self.spec['input_sha256'],operation)):'/input/capture.pcap'}
        if self.spec['config_sha256']:expected[str(self.input_copy(self.spec['config_sha256'],operation))]='/config/suricata.yaml'
        mounts=value.get('Mounts',[]);mounts=[m for m in mounts if m.get('Type')!='tmpfs']
        require(len(mounts)==len(expected) and all(m.get('Type')=='bind' and m.get('RW') is False
                and expected.get(m.get('Source'))==m.get('Destination') for m in mounts),'identity-unknown')
        require(host.get('Tmpfs')==self.tmpfs(),'identity-unknown')
        require(type(value.get('State',{}).get('Running')) is bool,'identity-unknown')
        return value

    def tmpfs(self):
        return {'/tmp':'rw,noexec,nosuid,nodev,size=16m,nr_inodes=1024,uid=1000,gid=1000',
                '/output':f'rw,noexec,nosuid,nodev,size={self.spec["output_limit_mb"]}m,nr_inodes=1024,uid=1000,gid=1000'}

    def command(self,operation):
        args=['container','create','--name',self.agent.prefix+'-analysis-'+operation,'--pull=never','--network=none','--no-healthcheck',
              '--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--pids-limit=64','--memory=512m',
              '--memory-swap=512m','--cpus=1','--user=1000:1000','--restart=no','--log-driver=local',
              '--log-opt','max-size=1m','--log-opt','max-file=1','--env','TZ=UTC','--env','LC_ALL=C',
              '--env','SOURCE_DATE_EPOCH=0',*self.agent.label_args(),'--label','org.ctflab.analysis='+operation]
        for name,value in self.tmpfs().items():args+=['--tmpfs',name+':'+value]
        args+=['--mount',f'type=bind,source={self.input_copy(self.spec["input_sha256"],operation)},target=/input/capture.pcap,readonly']
        if self.spec['config_sha256']:
            args+=['--mount',f'type=bind,source={self.input_copy(self.spec["config_sha256"],operation)},target=/config/suricata.yaml,readonly']
        return args+['--workdir','/output','--entrypoint','/usr/bin/python3',self.spec['image'],
                     '-I','-B','/usr/local/bin/ctflab-analyzer',self.spec['tool'],str(self.spec['timeout_seconds']),self.spec['tool_version']]

    def verify_export(self,operation,partial,report,status):
        from ctflab_runtime_inventory import check_path,hash_file,signature
        original=check_path(guard(partial))
        require(type(report) is dict and type(report.get('bytes')) is int and 1024<=report['bytes']<=4*1024**2
                and original.st_size==report['bytes'] and hash_file(partial,original)==report['sha256'],'identity-unknown')
        directory=guard(self.agent.root/'analysis-input'/operation);copied=directory/'verification.tar'
        require(shutil.disk_usage(directory).free>=report['bytes']+32*1024**2,'storage-insufficient')
        def copy_archive():
            fd=os.open(copied,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with partial.open('rb') as incoming,os.fdopen(fd,'wb') as target:
                require(signature(os.fstat(incoming.fileno()))==signature(original),'identity-unknown');count=0
                while block:=incoming.read(65536):
                    count+=len(block);require(count<=report['bytes'],'identity-unknown');target.write(block)
                require(count==report['bytes'] and signature(os.fstat(incoming.fileno()))==signature(original),'identity-unknown')
                target.flush();os.fchmod(target.fileno(),0o444);os.fsync(target.fileno())
            require(hash_file(partial,original)==report['sha256'],'identity-unknown')
            return {'sha256':report['sha256'],'bytes':count}
        self.agent.effect(operation,'analysis-verifier-input',copy_archive)
        copy_info=check_path(copied)
        require(copy_info.st_uid==os.getuid() and stat.S_IMODE(copy_info.st_mode)==0o444
                and hash_file(copied,copy_info)==report['sha256'],'identity-unknown')
        status_sha=hashlib.sha256(canonical(status).encode()).hexdigest();name=self.agent.prefix+'-verify-'+operation
        require(self.backend.docker_find('container',name) is None,'state-conflict')
        args=['container','create','--name',name,'--pull=never','--network=none','--no-healthcheck','--read-only','--cap-drop=ALL',
            '--security-opt=no-new-privileges','--pids-limit=16','--memory=128m','--memory-swap=128m','--cpus=1',
            '--user=1000:1000','--restart=no','--log-driver=local','--log-opt','max-size=1m','--log-opt','max-file=1',
            *self.agent.label_args(),'--label','org.ctflab.analysis='+operation,'--label','org.ctflab.role=archive-verifier',
            '--mount',f'type=bind,source={copied},target=/input/output.tar,readonly',
            '--entrypoint','/usr/bin/python3',self.spec['image'],'-I','-B','/usr/local/bin/ctflab-analyzer','verify-archive',status_sha]
        identity=self.agent.effect(operation,'analysis-verifier-create',lambda:self.backend.call('docker',args).strip())
        require(isinstance(identity,str) and re.fullmatch('[0-9a-f]{64}',identity),'identity-unknown')
        def inspect():
            rows=self.backend.json('docker',['container','inspect',identity]);require(type(rows) is list and len(rows)==1,'identity-unknown')
            value=rows[0];config=value.get('Config',{});host=value.get('HostConfig',{});labels=config.get('Labels',{});mounts=value.get('Mounts')
            require(type(mounts) is list and len(mounts)==1 and isinstance(mounts[0],dict)
                and mounts[0].get('Type')=='bind' and mounts[0].get('Source')==str(copied)
                and mounts[0].get('Destination')=='/input/output.tar' and mounts[0].get('RW') is False,'identity-unknown')
            require(value.get('Id')==identity and config.get('Image')==self.spec['image'] and config.get('User')=='1000:1000'
                and config.get('Entrypoint')==['/usr/bin/python3'] and config.get('Cmd')==['-I','-B','/usr/local/bin/ctflab-analyzer','verify-archive',status_sha]
                and config.get('Healthcheck',{}).get('Test')==['NONE']
                and all(labels.get(k)==v for k,v in self.agent.labels.items()) and labels.get('org.ctflab.analysis')==operation
                and labels.get('org.ctflab.role')=='archive-verifier' and host.get('NetworkMode')=='none'
                and host.get('ReadonlyRootfs') is True and host.get('Privileged') is False
                and host.get('CapAdd') in (None,[]) and host.get('CapDrop')==['ALL']
                and any(v in ('no-new-privileges','no-new-privileges:true') for v in host.get('SecurityOpt',[]))
                and host.get('Memory')==128*1024**2 and host.get('MemorySwap')==128*1024**2 and host.get('NanoCpus')==10**9
                and host.get('PidsLimit')==16 and host.get('RestartPolicy',{}).get('Name')=='no'
                and not host.get('Devices') and not host.get('PortBindings') and not host.get('Binds') and not host.get('Tmpfs')
                and host.get('PidMode','')=='' and host.get('IpcMode','private') in ('','private')
                and host.get('LogConfig')=={'Type':'local','Config':{'max-size':'1m','max-file':'1'}}
                and type(value.get('State',{}).get('Running')) is bool,'identity-unknown')
            return value['State']
        require(inspect()['Running'] is False,'resource-busy')
        def verify():
            raw=self.backend.call('docker',['container','start','--attach',identity],timeout=20)
            value=decode_metadata(raw,4096)
            require(type(value) is dict and set(value)=={'state','status_sha256','archive_sha256','archive_bytes','output_content','members','extracted'}
                and value['state']=='archive-content-matches' and value['status_sha256']==status_sha
                and value['archive_sha256']==report['sha256'] and type(value['archive_bytes']) is int and value['archive_bytes']==report['bytes']
                and value['output_content']==status['output_content'] and type(value['members']) is int and 1<=value['members']<=515
                and value['extracted'] is False,'identity-unknown')
            final=inspect();require(final['Running'] is False and type(final.get('ExitCode')) is int and final['ExitCode']==0,'identity-unknown')
            require(hash_file(copied,copy_info)==report['sha256'] and hash_file(partial,original)==report['sha256'],'identity-unknown')
            return value
        return identity,self.agent.effect(operation,'analysis-verifier-run',verify)

    def run(self,operation):
        uuid_text(operation)
        image=self.backend.json('docker',['image','inspect',self.spec['image']])
        require(type(image) is list and len(image)==1 and self.spec['image'] in (image[0].get('RepoDigests') or []),'identity-unknown')
        require(image[0].get('Config',{}).get('Volumes') in (None,{}),'permission-denied')
        labels=image[0].get('Config',{}).get('Labels',{})
        require(labels.get('org.ctflab.analyzer.tool')==self.spec['tool']
                and labels.get('org.ctflab.analyzer.version')==self.spec['tool_version']
                and labels.get('org.ctflab.analyzer.wrapper-sha256')==WRAPPER_SHA256,'version-mismatch')
        self.prepare_inputs(operation)
        args=self.command(operation) # 全部输入与副本预检先于容器创建意图。
        self.backend.check_tool('docker');name=self.agent.prefix+'-analysis-'+operation
        require(self.backend.docker_find('container',name) is None,'state-conflict')
        identity=self.agent.effect(operation,'analysis-create',lambda:self.backend.call('docker',args).strip())
        require(type(identity) is str and re.fullmatch('[0-9a-f]{64}',identity),'identity-unknown')
        before=self.inspect(identity,operation);require(before['State']['Running'] is False,'resource-busy')
        self.agent.effect(operation,'analysis-start',lambda:self.backend.call('docker',['container','start',identity]))
        deadline=self.clock()+self.spec['timeout_seconds']+5
        while True:
            observed=self.inspect(identity,operation)
            require(observed['State']['Running'] is True,'identity-unknown')
            status=analysis_status(decode_metadata(self.backend.call('docker',['container','exec','--user','1000:1000',identity,
                '/usr/bin/python3','-I','-B','/usr/local/bin/ctflab-analyzer','status']),16384),self.spec['tool_version'])
            if status['state']=='completed':break
            require(self.clock()<deadline,'stop-timeout');self.sleep(.1)
        code=status['returncode']
        output=self.agent.root/'analysis-output'
        if not output.exists():self.agent.effect(operation,'analysis-output-directory',lambda:private_directory(output))
        guard(output);partial=output/(operation+'.tar.partial')
        report=self.agent.effect(operation,'analysis-export',lambda:self.export(self.backend,identity,partial,4*1024**2))
        verifier,verification=self.verify_export(operation,partial,report,status) if status['output_content'] is not None else (None,None)
        # 原件在创建、运行、导出后都必须仍匹配，未知结果不强行标成分析成功。
        self.evidence(self.spec['input_sha256'])
        if self.spec['config_sha256']:self.evidence(self.spec['config_sha256'])
        self.agent.effect(operation,'analysis-stop',lambda:self.backend.call('docker',['container','kill','--signal=SIGTERM',identity]))
        deadline=self.clock()+5
        while self.inspect(identity,operation)['State']['Running']:
            require(self.clock()<deadline,'stop-timeout');self.sleep(.1)
        return {'state':'analysis-completed' if code==0 else 'analysis-failed','returncode':code,'container_id':identity,
                'archive':partial.name,'archive_sha256':report['sha256'],'archive_bytes':report['bytes'],
                'input_sha256':self.spec['input_sha256'],'config_sha256':self.spec['config_sha256'],
                'tool':self.spec['tool'],'tool_version':self.spec['tool_version'],'image':self.spec['image'],
                'operation_id':operation,'instance_uuid':self.policy['instance_uuid'],'generation':self.policy['generation'],
                'policy_sha256':self.policy['policy_sha256'],'wrapper_sha256':WRAPPER_SHA256,
                'tool_version_observed':status['tool_version_observed'],'version_report_sha256':status['version_report_sha256'],
                'output_content':status['output_content'],
                'verifier_container_id':verifier,'archive_content_consistent':verification is not None,'archive_verification':verification,
                'output_extracted':False,'network':'none','byte_reproducibility_verified':False,
                'analysis_findings_verified':False,'automatic_cleanup':False,'service_verified':False}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('image-materials');p.add_argument('--destination',required=True,type=Path)
    p.add_argument('--base-image',required=True);p.add_argument('--tool',required=True,choices=('zeek','suricata'))
    p.add_argument('--tool-version',required=True)
    p=sub.add_parser('compare-results')
    for side in ('left','right'):
        p.add_argument('--'+side,required=True,type=Path);p.add_argument('--'+side+'-sha256',required=True)
    args=parser.parse_args()
    try:
        if args.action=='image-materials':value=image_materials(args.destination,args.base_image,args.tool,args.tool_version)
        else:value=compare_results(pinned_result(args.left,args.left_sha256),pinned_result(args.right,args.right_sha256))
        print(canonical(value))
    except (OSError,ValueError,RuntimeError,TypeError,KeyError):
        print(canonical({'state':'refused-or-partial','preserved':True,'image_built':False}));raise SystemExit(2)
