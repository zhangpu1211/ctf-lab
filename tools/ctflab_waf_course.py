"""C07独立教学应用与简单WAF对照；生产入口限已声明专用来宾与回环，不是生产WAF。"""
import argparse
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler,HTTPServer
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import socket
from socketserver import ThreadingMixIn
import sqlite3
import sys
import threading
import time
import unicodedata
from urllib.parse import parse_qs,urlsplit,urlencode
import uuid

sys.dont_write_bytecode=True
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text,ContractError
from ctflab_generation_store import private_directory,digest
from ctflab_tls_endpoint import guard

MAX_REQUESTS=1000
MAX_HEADER_BYTES=16384
RULES=(('SQL-001',5,re.compile(r'\bselect\b.{0,80}\bfrom\b|\bor\s+1\s*=\s*1\b',re.I)),
       ('HTML-001',5,re.compile(r'<\s*script\b',re.I)),
       ('PATH-001',5,re.compile(r'(?:^|/)\.\.(?:/|$)')))
CATALOG=({'title':'网络隔离入门','category':'network'},
         {'title':'Select examples from SQL books','category':'database'},
         {'title':'Web事件调查','category':'response'})
PAGE='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>C07 WAF对照</title>
<style>body{font:16px system-ui;max-width:1120px;margin:32px auto;padding:16px;color:#172333;background:#f6f8fb}header,section{background:white;border:1px solid #dce2eb;border-radius:12px;padding:24px;margin-bottom:18px}h1{margin-top:0}p{line-height:1.7}button{font:inherit;padding:9px 18px;background:#254f93;color:white;border:0;border-radius:6px;cursor:pointer}button:disabled{opacity:.5}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:12px 8px;border-bottom:1px solid #e4e8ef;vertical-align:top}td.id{font-family:monospace;overflow-wrap:anywhere;max-width:220px}tr.blocked td{background:#fff1ed}tr.observed td{background:#fff9e9}.scroll{overflow-x:auto}.muted{color:#59677a}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f4f6;padding:18px}#error{color:#a02c21}</style>
<header><p class="muted">C07 · 独立选修实验</p><h1>观察、阻断与误报</h1><p>先按学生任务执行查询，再用请求标识对照代理与应用记录。教学匹配规则不等于生产WAF，告警也不证明攻击或漏洞。</p><p id="scope">正在读取当前记录…</p><button id="refresh">刷新记录</button><p id="error" role="status"></p></header>
<section><h2>处理记录</h2><p class="muted">这里只记录已接纳的搜索，不保存查询原文。记录不证明学生浏览器实际收到了响应。</p><div class="scroll"><table><thead><tr><th>时间（UTC）</th><th>请求标识</th><th>处理情况</th><th>匹配规则</th><th>应用返回</th></tr></thead><tbody id="rows"></tbody></table></div><p id="empty" class="muted">暂无记录，请先按学生任务执行查询。</p><details><summary>查看原始结构化记录</summary><pre id="raw"></pre></details></section>
<script>
const button=document.getElementById('refresh');
function cell(row,value,cls){const item=document.createElement('td');item.textContent=value;if(cls)item.className=cls;row.appendChild(item)}
async function show(){button.disabled=true;try{const response=await fetch('/events',{cache:'no-store'});if(!response.ok)throw new Error('unavailable');const data=await response.json();if(!Array.isArray(data.events))throw new Error('invalid');const roles={app:'应用端',observe:'观察端',block:'阻断端'};document.getElementById('scope').textContent=(roles[data.role]||'实验端')+' · 代次 '+data.generation+' · 共 '+data.events_total+' 条记录'+(data.events_truncated?'，仅显示最近100条':'')+' · 待核对请求 '+data.pending_count+' 个';const rows=document.createDocumentFragment();for(const event of data.events.slice(-100)){const row=document.createElement('tr');row.className=event.decision||'';let state=event.phase==='intent'?'开始处理，等待结果':({blocked:'已阻断，未转送',observed:'规则已匹配，仍转送',passed:'未匹配，已转送'}[event.decision]||'应用搜索完成');cell(row,String(event.at||'').replace('T',' ').replace('+00:00',''));cell(row,event.request_id||'未知','id');cell(row,state);cell(row,(event.rules||[]).map(rule=>rule.rule_id).join('、')||'—');cell(row,event.phase==='intent'?'等待结果':event.forward_attempted===false?'未转送':event.upstream_status||event.status||'待核对');rows.appendChild(row)}document.getElementById('rows').replaceChildren(rows);document.getElementById('empty').hidden=data.events.length>0;document.getElementById('raw').textContent=JSON.stringify(data,null,2);document.getElementById('error').textContent=''}catch(error){document.getElementById('error').textContent='记录暂不可读，已显示的旧记录保留。请核对服务状态，不要重复发送未知请求。'}finally{button.disabled=false}}
button.addEventListener('click',show);show();
</script></html>'''


def fingerprint(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def read(path,maximum=65536):
    from ctflab_remote import decode
    path=guard(path);before=path.stat();require(path.is_file() and before.st_nlink==1,'identity-unknown')
    require(before.st_size<=maximum,'storage-insufficient')
    value=decode(path.read_bytes(),maximum);after=path.stat()
    require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
        (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'identity-unknown')
    return value


def settings(value):
    fields={'schema','lab_uuid','machine_uuid','generation','role','ports','threshold'}
    require(type(value) is dict and set(value)==fields and type(value['schema']) is int and value['schema']==1)
    uuid_text(value['lab_uuid']);uuid_text(value['machine_uuid'])
    require(type(value['generation']) is int and 1<=value['generation']<=2**31-1 and value['role'] in ('app','observe','block'))
    ports=value['ports'];require(type(ports) is dict and set(ports)=={'app','observe','block'} and len(set(ports.values()))==3)
    require(all(type(port) is int and 1024<=port<=65535 and port not in (2375,2376)
        and not 5900<=port<=5999 for port in ports.values()),'permission-denied')
    require(type(value['threshold']) is int and 1<=value['threshold']<=10)
    return value


def query(target):
    require(type(target) is str and len(target.encode())<=2048 and all(32<=ord(c)<127 for c in target),'invalid-request')
    parsed=urlsplit(target);require(not parsed.scheme and not parsed.netloc and not parsed.fragment and parsed.path=='/search')
    require(not re.search(r'%(?![0-9a-fA-F]{2})',parsed.query),'invalid-request')
    params=parse_qs(parsed.query,keep_blank_values=True,strict_parsing=True,encoding='utf-8',errors='strict',max_num_fields=1)
    require(set(params)=={'q'} and len(params['q'])==1)
    value=unicodedata.normalize('NFKC',params['q'][0])
    require(len(value.encode())<=256 and all(ord(c)>=32 and ord(c)!=127 for c in value))
    return value,'/search?'+urlencode({'q':value})


def inspect_query(value):
    matched=[{'rule_id':name,'weight':weight} for name,weight,pattern in RULES if pattern.search(value)]
    return matched,sum(row['weight'] for row in matched)


def signature(key,config,identity,target):
    payload={'kind':'request','lab_uuid':config['lab_uuid'],'generation':config['generation'],'request_id':identity,'target':target}
    return hmac.new(key,canonical(payload).encode(),hashlib.sha256).hexdigest()


def response_signature(key,config,identity,status,raw):
    payload={'kind':'response','lab_uuid':config['lab_uuid'],'generation':config['generation'],
        'request_id':identity,'status':status,'body_sha256':hashlib.sha256(raw).hexdigest()}
    return hmac.new(key,canonical(payload).encode(),hashlib.sha256).hexdigest()


class Course:
    def __init__(self,root,*,native=None,create=True):
        self.root=guard(Path(root).absolute());self.config=settings(read(self.root/'config.json'))
        self.config_sha=fingerprint(self.config);self.native=native;self.key=read(self.root/'key.json')
        require(set(self.key)=={'key'} and type(self.key['key']) is str and re.fullmatch('[0-9a-f]{64}',self.key['key']))
        self.secret=bytes.fromhex(self.key['key']);self.runtime=read(self.root.parent/'runtime-manifest.json')
        self.authorize();path=self.root/'events.sqlite3'
        if not path.exists():
            require(create,'state-conflict')
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
            with closing(sqlite3.connect(path)) as db:
                db.execute('PRAGMA synchronous=FULL');db.executescript('CREATE TABLE metadata(value TEXT);'
                    'CREATE TABLE requests(id TEXT PRIMARY KEY,state TEXT);'
                    'CREATE TABLE events(seq INTEGER PRIMARY KEY,id TEXT,phase TEXT,payload TEXT);')
                info=self.root.stat();db.execute('INSERT INTO metadata VALUES(?)',(canonical({'config_sha256':self.config_sha,'runtime_sha256':fingerprint(self.runtime),'key_sha256':fingerprint(self.key),
                    'root_identity':[info.st_dev,info.st_ino]}),));db.commit()
        info=guard(path).stat();require(path.is_file() and info.st_nlink==1,'identity-unknown')
        self.database_identity=[info.st_dev,info.st_ino]
        with self.db(write=False) as db:self.check_db(db)
    def authorize(self):
        guard(self.root);require(settings(read(self.root/'config.json'))==self.config and read(self.root/'key.json')==self.key,'identity-unknown')
        require(read(self.root.parent/'runtime-manifest.json')==self.runtime,'identity-unknown')
        require(type(self.runtime) is dict and set(self.runtime)=={'schema','files'} and type(self.runtime['schema']) is int
            and self.runtime['schema']==1 and type(self.runtime['files']) is dict and 1<=len(self.runtime['files'])<=256,'identity-unknown')
        require({'ctflab_waf_course.py','ctflab_external.py','ctflab_contract.py','ctflab_generation_store.py'}<=set(self.runtime['files']),'identity-unknown')
        runtime=guard(self.root.parent/'runtime');total=0
        require({path.name for path in runtime.iterdir()}==set(self.runtime['files']),'identity-unknown')
        for name,sha in self.runtime['files'].items():
            require(type(name) is str and re.fullmatch('ctflab_[a-z0-9_]+\\.py',name)
                and type(sha) is str and re.fullmatch('[0-9a-f]{64}',sha),'identity-unknown')
            path=guard(runtime/name);total+=path.stat().st_size
            require(total<=32*1024**2 and path.is_file() and path.stat().st_nlink==1 and digest(path)==sha,'identity-unknown')
        if self.native is None:
            require(sys.platform=='linux' or os.name=='nt','unsupported-platform')
            require(Path(__file__).resolve().parent==runtime,'permission-denied')
            from ctflab_external import native_machine
            identity=native_machine()
        else:identity=self.native()
        require(type(identity) is dict and identity.get('machine_uuid')==self.config['machine_uuid'],'identity-unknown')
    def db(self,*,write=True):
        from contextlib import contextmanager
        @contextmanager
        def opened():
            path=guard(self.root/'events.sqlite3');info=path.stat()
            require(path.is_file() and info.st_nlink==1 and [info.st_dev,info.st_ino]==self.database_identity,'identity-unknown')
            require(info.st_size<=8*1024**2,'storage-insufficient')
            with closing(sqlite3.connect(path.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=0,isolation_level=None)) as db:
                require(db.execute('PRAGMA page_size').fetchone()[0]==4096
                    and db.execute('PRAGMA journal_mode').fetchone()[0]=='delete','identity-unknown')
                if write:
                    db.execute('PRAGMA synchronous=FULL')
                    require(db.execute('PRAGMA max_page_count=2048').fetchone()[0]<=2048,'storage-insufficient')
                else:db.execute('PRAGMA query_only=ON')
                db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                try:yield db;db.commit()
                except BaseException:db.rollback();raise
        return opened()
    def check_db(self,db):
        rows=db.execute('SELECT value FROM metadata LIMIT 2').fetchall();info=self.root.stat()
        require(len(rows)==1 and rows[0][0]==canonical({'config_sha256':self.config_sha,'runtime_sha256':fingerprint(self.runtime),'key_sha256':fingerprint(self.key),
            'root_identity':[info.st_dev,info.st_ino]}),'identity-unknown')
    def append(self,db,identity,phase,payload):
        value={'at':datetime.now(timezone.utc).isoformat(),**payload}
        require(len(canonical(value).encode())<=2048,'storage-insufficient')
        db.execute('INSERT INTO events(id,phase,payload) VALUES(?,?,?)',(identity,phase,canonical(value)))
    def begin(self,identity):
        uuid_text(identity)
        with self.db() as db:
            self.check_db(db);require(db.execute('SELECT COUNT(*) FROM requests').fetchone()[0]<MAX_REQUESTS,'storage-insufficient')
            require(db.execute('SELECT 1 FROM requests WHERE id=?',(identity,)).fetchone() is None,'state-conflict')
            db.execute("INSERT INTO requests VALUES(?,'pending')",(identity,));self.append(db,identity,'intent',{'action':'search'})
    def finish(self,identity,payload):
        with self.db() as db:
            self.check_db(db);require(db.execute('SELECT state FROM requests WHERE id=?',(identity,)).fetchone()==('pending',),'state-conflict')
            self.append(db,identity,'result',payload);db.execute("UPDATE requests SET state='finished' WHERE id=?",(identity,))
    def events(self):
        self.authorize()
        with self.db(write=False) as db:
            self.check_db(db);rows=db.execute('SELECT seq,id,phase,payload FROM events ORDER BY seq DESC LIMIT 100').fetchall()
            total=db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            pending=db.execute("SELECT COUNT(*) FROM requests WHERE state='pending'").fetchone()[0]
        return {'role':self.config['role'],'generation':self.config['generation'],'lab_uuid':self.config['lab_uuid'],
            'events_total':total,'events_truncated':total>100,
            'events':[{'seq':seq,'request_id':identity,'phase':phase,**json.loads(payload)} for seq,identity,phase,payload in reversed(rows)],
            'pending_count':pending,'window_limit':100,'raw_query_recorded':False,'client_delivery_verified':False,'automatic_replay':False}
    def export(self,destination):
        self.authorize();destination=Path(destination).absolute()
        require(destination!=self.root.parent and self.root.parent not in destination.parents
            and destination not in self.root.parents,'permission-denied')
        with self.db(write=False) as db:
            self.check_db(db);rows=db.execute('SELECT seq,id,phase,payload FROM events ORDER BY seq LIMIT 2001').fetchall()
            require(len(rows)<=2*MAX_REQUESTS,'storage-insufficient')
            pending=db.execute("SELECT COUNT(*) FROM requests WHERE state='pending'").fetchone()[0]
            raw=b''.join((canonical({'seq':seq,'request_id':identity,'phase':phase,**json.loads(payload)})+'\n').encode()
                for seq,identity,phase,payload in rows)
        require(len(raw)<=8*1024**2,'storage-insufficient');private_directory(destination)
        fd=os.open(destination/'events.jsonl',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        from ctflab_windows_recovery import record
        record(destination/'MANIFEST.json',{'schema':1,'lab_uuid':self.config['lab_uuid'],
            'generation':self.config['generation'],'role':self.config['role'],'event_count':len(rows),
            'head_sequence':rows[-1][0] if rows else 0,'pending_count':pending,
            'files':{'events.jsonl':hashlib.sha256(raw).hexdigest()},'raw_query_recorded':False,
            'key_or_teacher_materials_included':False,'source':'service-owned-events-not-PCAP-or-Windows-eventlog',
            'externally_anchored':False,'client_delivery_verified':False,'automatic_replay':False})
        return {'state':'c07-events-exported','event_count':len(rows),'pending_count':pending,
            'original_modified':False,'key_or_teacher_materials_included':False,'externally_anchored':False}
    def search(self,target,headers):
        self.authorize();value,target=query(target);role=self.config['role']
        if role=='app':
            require(all(len(headers.get_all(name,[]))==1 for name in ('X-CTFLab-Request','X-CTFLab-Signature')),'permission-denied')
            identity=uuid_text(headers.get('X-CTFLab-Request'))
            expected=signature(self.secret,self.config,identity,target)
            require(hmac.compare_digest(headers.get('X-CTFLab-Signature',''),expected),'permission-denied')
            self.begin(identity);items=[item for item in CATALOG if value.casefold() in item['title'].casefold()]
            self.finish(identity,{'status':200,'result_count':len(items),'action':'catalog-search'})
            return 200,{'items':items},identity
        identity=str(uuid.uuid4());rules,score=inspect_query(value);blocked=role=='block' and score>=self.config['threshold']
        self.begin(identity)
        result={'decision':'blocked' if blocked else 'observed' if rules else 'passed','rules':rules,'score':score,
            'forward_attempted':not blocked,'upstream_status':None,'client_delivery_verified':False}
        if blocked:
            self.finish(identity,dict(result,status=403));return 403,{'state':'blocked','request_id':identity,'rules':rules},identity
        connection=http.client.HTTPConnection('127.0.0.1',self.config['ports']['app'],timeout=2)
        try:
            connection.request('GET',target,headers={'X-CTFLab-Request':identity,
                'X-CTFLab-Signature':signature(self.secret,self.config,identity,target)})
            response=connection.getresponse();raw=response.read(65537)
            require(len(raw)<=65536 and response.status==200 and response.getheader('X-CTFLab-Request')==identity,'control-unreachable')
            require(hmac.compare_digest(response.getheader('X-CTFLab-Response',''),
                response_signature(self.secret,self.config,identity,response.status,raw)),'identity-unknown')
            body=json.loads(raw);require(type(body) is dict and set(body)=={'items'} and type(body['items']) is list,'control-unreachable')
            result['upstream_status']=200;self.finish(identity,dict(result,status=200))
            return 200,body,identity
        except (OSError,ValueError,RuntimeError,http.client.HTTPException):
            # 上游是否执行/响应是否真实未知；本意图保持pending，不重试、补发或伪造失败终态。
            return 502,{'state':'upstream-unknown','request_id':identity,'automatic_replay':False},identity
        finally:connection.close()


class HeaderBudget:
    def __init__(self,stream):self.stream=stream;self.remaining=MAX_HEADER_BYTES
    def readline(self,size=-1):
        limit=min(4097,self.remaining+1,size if size>=0 else self.remaining+1)
        if limit<=0:raise http.client.LineTooLong('header budget')
        value=self.stream.readline(limit);self.remaining-=len(value)
        if self.remaining<0 or len(value)>4096:raise http.client.LineTooLong('header budget')
        return value
    def __getattr__(self,name):return getattr(self.stream,name)


class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    def setup(self):super().setup();self.connection.settimeout(2);self.rfile=HeaderBudget(self.rfile)
    def log_message(self,*args):pass
    def respond(self,status,value,identity=None,html=False):
        raw=value.encode() if html else canonical(value).encode();self.send_response(status)
        self.send_header('Content-Type','text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Connection','close')
        if identity:
            self.send_header('X-CTFLab-Request',identity)
            if self.server.course.config['role']=='app' and status==200:
                self.send_header('X-CTFLab-Response',response_signature(self.server.course.secret,
                    self.server.course.config,identity,status,raw))
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(raw)
    def do_GET(self):
        try:
            require(len(self.headers)<=32 and self.headers.get('Transfer-Encoding') is None
                and self.headers.get('Content-Length','0')=='0','invalid-request')
            self.server.course.authorize()
            if self.path=='/':self.respond(200,PAGE,html=True)
            elif self.path=='/health':self.respond(200,{'state':'listening','role':self.server.course.config['role'],
                'course_acceptance_verified':False})
            elif self.path=='/events':self.respond(200,self.server.course.events())
            elif self.path.startswith('/search?'):
                status,value,identity=self.server.course.search(self.path,self.headers);self.respond(status,value,identity)
            else:self.respond(404,{'state':'unknown-route'})
        except ContractError as error:
            self.respond({'permission-denied':403,'state-conflict':409,'invalid-request':400}.get(error.code,503),
                {'state':'refused-or-unknown','automatic_replay':False})
        except (OSError,ValueError,RuntimeError,TypeError,sqlite3.Error):
            self.respond(503,{'state':'refused-or-unknown','automatic_replay':False})
    def do_POST(self):self.respond(405,{'state':'method-refused'})
    def do_CONNECT(self):self.respond(405,{'state':'method-refused'})
    def do_HEAD(self):self.respond(405,{'state':'method-refused'})


class Server(ThreadingMixIn,HTTPServer):
    daemon_threads=False
    block_on_close=True
    request_queue_size=8
    allow_reuse_address=False
    def __init__(self,course):
        self.course=course;self.slots=threading.BoundedSemaphore(8)
        super().__init__(('127.0.0.1',course.config['ports'][course.config['role']]),Handler)
    def process_request(self,request,address):
        if not self.slots.acquire(False):self.shutdown_request(request);return
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()
    def handle_error(self,*args):pass


STUDENT='''# C07：WAF观察、阻断与误报

这是独立选修内容，不改变普通渗透课。应用只做固定目录搜索，输入不进入SQL或HTML执行；WAF是教学用简单匹配器，不是生产产品或真实漏洞证明。服务只监听已声明专用来宾的127.0.0.1，宿主不配置网络。由教师按部署说明启动，学生通过已有获准会话访问指定端口。

1. 在观察和阻断端分别查询“网络”并记录结果与请求标识。
2. 分别查询“or 1=1”“<script>demo”和“../demo”。对照代理与应用/events中的同一request_id；阻断是否等于应用执行过？
3. 搜索合法书名“Select examples from SQL books”。应用中确有该目录项，为什么阻断模式会影响正常业务？这是误报还是已确认入侵？
4. 对照rules、score、forward_attempted与upstream_status，区分匹配、转送、应用结果和客户端是否实际收到。pending没有终态时保留未知，不补发。
5. 提出可验证的误报调整方案；本课不热改运行规则。需要改变阈值/模式时由教师建立新目录/代次后再对照，保留旧事件。
6. 教师可用export将服务事件封存到全新目录，学生保存导出及自己的请求/结果记录，说明时间、范围和遗漏。记录只有最近100个事件且不含查询原文；不能拿它证明全部历史或查询内容。

页面仅显示只读事件，无规则修改、文件浏览或教师答案入口。没有真实Docker/跨网/Windows课堂验收时，不勾选整课通过。
'''
TEACHER='''# C07部署与答案边界

材料不含Python、来宾镜像或容器运行时，不自动安装、启动或修改网络。仅部署到绑定machine_uuid的新专用Linux/Windows虚拟来宾，根/runtime/各角色目录使用当前用户私有权限/ACL。key.json只供服务读取，不发给学生、不记入日志；runtime-manifest必须与整套源码一致。Mac宿主serve拒绝。分别使用python -I -B runtime/ctflab_waf_course.py serve --run角色目录 --duration明确时长启动app、observe、block；关闭本次服务不停止VM，也不删除旧日志/数据。CLI不接管已占端口或其他进程。

合法词请求两端200。SQL/HTML/路径匹配在observe中转送、block达到阈值时403；应用的结果始终是安全目录搜索。SQL-001会误报合法书名，观察端可返回目录项而阻断端不转送；不能将匹配等同真实攻击。教师应另行记录实际输入，服务刻意不保存原查询、认证头、cookie或密钥。DB固定1000请求预算，只记录已接纳的搜索；健康/事件读取、格式或鉴权拒绝、连接限额拒绝不进入该事件账本。此账本不是全量访问日志或不可篡改审计链。intent先于上游，失败pending不重试；真实故障可导致已执行却无结果，不能猜测失败或重放。

external-service-candidates.json只给出既有外部代理可用的回环TCP候选，仍须教师按实际machine/cohort/代次/账户配置原认证代理，不自动登记或部署SSH。应用端口仅健康/事件可匿名读取，搜索必须代理HMAC认证；可只给学生observe/block端口，由教师另导出app事件。

仅有loopback业务测试不证明容器隔离、跨节点网络、真实分析镜像、Windows事件采集、课堂或发布验收。C06不因本课存在而完成。D02/OCI真实部署、原生CPU/存储限制与课堂真值仍须独立验收。本匹配器不可作为生产防护。
'''


def materials(source,destination,machine,generation,*,ports=None):
    from ctflab_desktop_package import TOOLS
    uuid_text(machine);ports={'app':18080,'observe':18081,'block':18082} if ports is None else ports
    lab=str(uuid.uuid4());base={'schema':1,'lab_uuid':lab,'machine_uuid':machine,'generation':generation,
        'role':'app','ports':ports,'threshold':5};settings(base)
    source=Path(source);destination=Path(destination).absolute()
    payload={}
    for name in TOOLS:
        path=source/name
        if not path.is_file():path=source/'runtime'/Path(name).name
        payload['runtime/'+Path(name).name]=path.read_bytes()
    require(len(payload)==len(TOOLS) and sum(len(raw) for raw in payload.values())<=32*1024**2,'identity-unknown')
    manifest={'schema':1,'files':{Path(name).name:hashlib.sha256(raw).hexdigest() for name,raw in payload.items()}}
    payload['runtime-manifest.json']=canonical(manifest).encode();key=canonical({'key':secrets.token_hex(32)}).encode()
    for role in ('app','observe','block'):
        payload[role+'/config.json']=canonical(dict(base,role=role)).encode();payload[role+'/key.json']=key
    payload['student/学生任务.md']=STUDENT.encode();payload['teacher/部署与说明.md']=TEACHER.encode()
    payload['teacher/external-service-candidates.json']=canonical({'schema':1,'kind':'external-loopback-tcp-candidates',
        'services':{'c07-'+role:{'port':port,'protocol':'tcp'} for role,port in ports.items()},
        'automatic_registration':False,'runtime_verified':False}).encode()
    private_directory(destination)
    for parent in ('runtime','app','observe','block','student','teacher'):private_directory(destination/parent)
    from ctflab_windows_recovery import record
    for name,raw in payload.items():
        fd=os.open(destination/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    record(destination/'MANIFEST.json',{'schema':1,'kind':'c07-source-materials','lab_uuid':lab,
        'files':{name:hashlib.sha256(raw).hexdigest() for name,raw in payload.items()},
        'services_started':False,'guest_or_container_verified':False,'network_modified':False})
    return {'state':'c07-source-materials-created','files':len(payload),'lab_uuid':lab,'services_started':False,
        'teacher_materials_separate':True,'guest_or_container_verified':False,'network_modified':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    build=sub.add_parser('materials');build.add_argument('--destination',required=True,type=Path)
    build.add_argument('--machine-uuid',required=True);build.add_argument('--generation',type=int,required=True)
    serve=sub.add_parser('serve');serve.add_argument('--run',required=True,type=Path);serve.add_argument('--duration',type=int,required=True)
    export=sub.add_parser('export');export.add_argument('--run',required=True,type=Path);export.add_argument('--destination',required=True,type=Path)
    args=parser.parse_args(argv)
    try:
        if args.action=='materials':result=materials(Path(__file__).resolve().parent.parent,args.destination,args.machine_uuid,args.generation)
        elif args.action=='export':result=Course(args.run,create=False).export(args.destination)
        else:
            require(type(args.duration) is int and 1<=args.duration<=3600)
            course=Course(args.run);server=Server(course);server.timeout=.25;deadline=time.monotonic()+args.duration
            try:
                while time.monotonic()<deadline:server.handle_request()
            finally:server.server_close()
            result={'state':'c07-service-ended','vm_stopped':False,'events_preserved':True,'course_acceptance_verified':False}
        print(canonical(result));return 0
    except (OSError,ValueError,RuntimeError,sqlite3.Error,TypeError,KeyError):
        print(canonical({'state':'refused-or-unknown','automatic_replay':False,'vm_stopped':False,'events_preserved':True}));return 2


if __name__=='__main__':raise SystemExit(main())
