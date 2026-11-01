"""SSH会话内认证显示；固定RFB/TLS后端、范围/租约逐请求核验，无端口转发或剪贴板。"""
import argparse
import base64
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import math
from pathlib import Path
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text,identifier
from ctflab_generation_store import GenerationStore,digest
from ctflab_tls_endpoint import guard

ACTIONS=('display-open','display-frame','display-key','display-pointer','display-close')


def settings(value):
    require(type(value) is dict and set(value)=={'max_sessions','max_pixels','lease_required'})
    require(type(value['max_sessions']) is int and 1<=value['max_sessions']<=4
            and type(value['max_pixels']) is int and 65536<=value['max_pixels']<=786432
            and value['lease_required'] is True)
    return value


def endpoint(policy,instance,node,*,connect=False):
    from ctflab_qemu_driver import QemuDriver,read
    root=guard(Path(policy['instances'][instance]['root']));store=GenerationStore(root)
    require(store.config['instance_uuid']==instance,'identity-unknown');snapshot=store.snapshot();generation=snapshot['active_generation']
    require(type(generation) is int and generation>0,'identity-unknown');plan=store.plan(generation)
    require(node in plan['manifest']['nodes'],'permission-denied')
    profile=guard(root/'runtime-profile.json');driver=QemuDriver(store,read(profile));paths=store.node_paths(generation,node)
    attempt=driver.latest(driver.location(plan,node,paths));require(attempt is not None,'identity-unknown')
    spec,binding,expected=driver.binding(plan,node,paths,attempt)
    observed=driver.observe(plan,node,paths);require(observed.identity=='verified' and observed.state=='process-running','identity-unknown')
    value={'root_identity':[root.stat().st_dev,root.stat().st_ino],
        'ledger_identity':[(root/'ledger.sqlite3').stat().st_dev,(root/'ledger.sqlite3').stat().st_ino],
        'config_sha256':hashlib.sha256(canonical(store.config).encode()).hexdigest(),'profile_sha256':digest(profile),
        'generation':generation,'plan_sha256':plan['plan_sha256'],'attempt':str(attempt.relative_to(root)),
        'process':asdict(expected)}
    sha=hashlib.sha256(canonical(value).encode()).hexdigest()
    return sha,driver.display(plan,node,paths) if connect else None


def lease_valid(policy,instance,lease):
    from ctflab_remote_leases import RemoteLeases
    owner=policy['instances'][instance]['owner'];manager=RemoteLeases(policy,owner)
    row=manager.pool.get(uuid_text(lease))
    require(row['instance_uuid']==instance and row['principal']==owner and row['state']!='released'
            and manager.pool.time_state(row)=='active' and row['binding']==manager.binding(instance),'permission-denied')


def scaled_frame(client,maximum):
    client.frame();width,height=client.width,client.height
    require(type(width) is int and type(height) is int and 0<width<=4096 and 0<height<=2160
            and type(client.pixels) in (bytes,bytearray) and len(client.pixels)==width*height*3,'identity-unknown')
    scale=max(1,math.ceil(math.sqrt(width*height/maximum)))
    w=max(1,width//scale);h=max(1,height//scale);require(w*h<=maximum,'storage-insufficient')
    rgb=bytearray(w*h*3)
    for y in range(h):
        source=client.pixels[(y*scale)*width*3:((y*scale)*width+w*scale)*3]
        for channel in range(3):rgb[y*w*3+channel:(y+1)*w*3:3]=source[channel:w*scale*3:scale*3]
    ppm=f'P6\n{w} {h}\n255\n'.encode()+rgb
    return {'width':w,'height':h,'scale':scale,'ppm_base64':base64.b64encode(ppm).decode()}


class DisplayPool:
    def __init__(self,*,endpoint_factory=endpoint,lease_check=lease_valid,now=None):
        self.endpoint=endpoint_factory;self.lease_check=lease_check;self.now=now or (lambda:datetime.now(timezone.utc))
        self.sessions={};self.used=set();self.principal=None
    def __enter__(self):return self
    def __exit__(self,*a):self.close()
    def close(self):
        for identity in list(self.sessions):self.drop(identity)
    def drop(self,identity):
        entry=self.sessions.pop(identity,None)
        if entry:
            try:entry['client'].close()
            except (OSError,ValueError,RuntimeError):pass
    def authorize(self,policy,principal,instance,lease):
        require('display' in policy and 'leases' in policy,'capability-unverified');settings(policy['display'])
        account=policy['principals'].get(principal)
        require(account is not None and instance in account['instances'] and instance in policy['instances'],'permission-denied')
        require(account['role']!='student' or policy['instances'][instance]['owner']==principal,'permission-denied')
        require(self.now()<datetime.fromisoformat(account['expires'].replace('Z','+00:00')),'permission-denied')
        self.lease_check(policy,instance,lease)
    def handle(self,policy,principal,action,params):
        require(action in ACTIONS and type(params) is dict)
        identifier(principal)
        if self.principal is None:self.principal=principal
        require(self.principal==principal,'permission-denied')
        required={'instance_uuid','session_id'}
        extras={'display-open':{'node','lease_id'},'display-frame':{'sequence'},'display-key':{'sequence','keysym','down'},
            'display-pointer':{'sequence','x','y','mask'},'display-close':{'sequence'}}[action]
        require(set(params)==required|extras);instance=uuid_text(params['instance_uuid']);identity=uuid_text(params['session_id'])
        fingerprint=hashlib.sha256(canonical(policy).encode()).hexdigest()
        try:
            if action=='display-open':
                identifier(params['node']);uuid_text(params['lease_id']);self.authorize(policy,principal,instance,params['lease_id'])
                require(identity not in self.used and len(self.used)<4096 and len(self.sessions)<policy['display']['max_sessions'],'resource-busy')
                self.used.add(identity);binding,client=self.endpoint(policy,instance,params['node'],connect=True)
                self.sessions[identity]={'client':client,'binding':binding,'principal':principal,'instance':instance,'node':params['node'],
                    'lease':params['lease_id'],'policy_sha256':fingerprint,'sequence':0,'scale':1,'width':client.width,'height':client.height}
                self.authorize(policy,principal,instance,params['lease_id'])
                require(self.endpoint(policy,instance,params['node'])[0]==binding,'identity-unknown')
                return {'session_id':identity,'instance_uuid':instance,'sequence':0,'state':'display-connected','clipboard':False,'file_transfer':False}
            require(identity in self.sessions,'identity-unknown');entry=self.sessions[identity]
            require(entry['principal']==principal and entry['instance']==instance,'permission-denied')
            require(type(params['sequence']) is int and params['sequence']==entry['sequence']+1,'state-conflict')
            entry['sequence']=params['sequence']
            if action=='display-close':
                self.drop(identity);return {'session_id':identity,'instance_uuid':instance,'sequence':params['sequence'],'state':'display-closed','vm_stopped':False}
            require(entry['policy_sha256']==fingerprint,'permission-denied');self.authorize(policy,principal,instance,entry['lease'])
            require(self.endpoint(policy,instance,entry['node'])[0]==entry['binding'],'identity-unknown')
            client=entry['client'];result={}
            if action=='display-frame':
                result=scaled_frame(client,policy['display']['max_pixels'])
                for key in ('scale','width','height'):entry[key]=result[key]
                result.pop('scale')
            elif action=='display-key':
                require(type(params['keysym']) is int and 0<=params['keysym']<=0x1fffffff and type(params['down']) is bool)
                client.key(params['keysym'],params['down'])
            else:
                require(all(type(params[k]) is int for k in ('x','y','mask')) and 0<=params['x']<entry['width']
                        and 0<=params['y']<entry['height'] and 0<=params['mask']<=7)
                client.pointer(min(client.width-1,params['x']*entry['scale']),min(client.height-1,params['y']*entry['scale']),params['mask'])
            self.authorize(policy,principal,instance,entry['lease'])
            require(self.endpoint(policy,instance,entry['node'])[0]==entry['binding'],'identity-unknown')
            return dict(result,session_id=identity,instance_uuid=instance,sequence=entry['sequence'],state='display-response',
                        clipboard=False,file_transfer=False,vm_stopped=False)
        except Exception:
            # 拒绝/未知即断开本会话显示；不向VM发送停止、重置或自动重连。
            self.drop(identity);raise


class RemoteRFB:
    def __init__(self,config_path,target_sha,instance,node,lease,*,session_factory=None):
        import uuid
        from ctflab_desktop_remote import target
        from ctflab_remote import SSHSession
        self.config_path=Path(config_path);self.target_sha=target_sha;self.instance=uuid_text(instance)
        self.identity=str(uuid.uuid4());self.sequence=0;self.keys=set();self.width=self.height=1;self.closed=False
        config,sha=target(config_path);require(sha==target_sha,'identity-unknown')
        self.session=(session_factory or SSHSession)(config)
        try:
            handshake=self.session.request('handshake',{});require(handshake.get('display_tunnel') is True,'capability-unverified')
            reply=self.session.request('display-open',{'instance_uuid':instance,'session_id':self.identity,'node':node,'lease_id':lease})
            self.validate(reply,0);require(reply.get('state')=='display-connected','identity-unknown')
        except BaseException:self.session.close(failed=True);self.closed=True;raise
    def validate(self,reply,sequence):
        from ctflab_desktop_remote import target
        require(type(reply) is dict and reply.get('session_id')==self.identity and reply.get('instance_uuid')==self.instance
                and type(reply.get('sequence')) is int and reply['sequence']==sequence
                and target(self.config_path)[1]==self.target_sha,'identity-unknown')
    def request(self,action,**params):
        require(not self.closed,'control-unreachable');self.sequence+=1
        try:
            reply=self.session.request(action,dict(params,instance_uuid=self.instance,session_id=self.identity,sequence=self.sequence))
            self.validate(reply,self.sequence);return reply
        except BaseException:self.session.close(failed=True);self.closed=True;raise
    def frame(self):
        reply=self.request('display-frame');width,height=reply.get('width'),reply.get('height');raw=reply.get('ppm_base64')
        require(type(width) is int and type(height) is int and width>0 and height>0 and width*height<=786432 and width<=4096 and height<=2160
                and type(raw) is str and len(raw)<=4*1024**2,'identity-unknown')
        image=base64.b64decode(raw,validate=True);header=f'P6\n{width} {height}\n255\n'.encode()
        require(image.startswith(header) and len(image)==len(header)+width*height*3,'identity-unknown')
        self.width,self.height=width,height;return image
    def key(self,keysym,down):
        self.request('display-key',keysym=keysym,down=down)
        if down:self.keys.add(keysym)
        else:self.keys.discard(keysym)
    def pointer(self,x,y,mask):self.request('display-pointer',x=x,y=y,mask=mask)
    def close(self):
        if self.closed:return
        try:self.request('display-close')
        finally:self.session.close();self.closed=True


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True,type=Path)
    for key in ('target','instance','node','lease'):parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    try:
        from ctflab_rfb_tls import show
        show(lambda:RemoteRFB(args.config,args.target,args.instance,args.node,args.lease))
    except (OSError,ValueError,RuntimeError,TypeError,KeyError):raise SystemExit(2)
