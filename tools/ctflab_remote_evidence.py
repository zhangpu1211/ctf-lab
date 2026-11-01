"""实例归属的封存证据窄通道；只读有界分块，不接受远程路径、不解包或执行内容。"""
import argparse
import base64
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text
from ctflab_generation_store import private_directory,digest,GenerationStore
from ctflab_runtime_inventory import check_path,hash_file,signature
from ctflab_tls_endpoint import guard
from ctflab_windows_recovery import record

CHUNK=32768


def filename(value):
    require(type(value) is str and (value in ('MANIFEST.json','timeline.json') or re.fullmatch(r'capture-[0-9]{3}\.pcap',value)))
    return value


def settings(value):
    require(type(value) is dict and set(value)=={'max_exports','max_bytes'}
            and type(value['max_exports']) is int and 1<=value['max_exports']<=128
            and type(value['max_bytes']) is int and 1<=value['max_bytes']<=1024**3)
    return value


def publish(root,source,identity,expected):
    root=guard(Path(root).absolute());instance=GenerationStore(root).config['instance_uuid'];uuid_text(identity)
    source=guard(Path(source).absolute());manifest=guard(source/'MANIFEST.json')
    require(manifest.stat().st_size<=1024**2 and digest(manifest)==expected,'identity-unknown')
    value=json.loads(manifest.read_text());require(type(value) is dict and value.get('kind')=='local-evidence-export'
        and type(value.get('schema')) is int and value['schema']==1 and type(value.get('binding')) is dict and value['binding'].get('instance_uuid')==instance
        and type(value['binding'].get('generation')) is int and value['binding']['generation']>0,'identity-unknown')
    files=value.get('files');require(type(files) is dict and 1<=len(files)<=33 and 'MANIFEST.json' not in files)
    hashes=dict(files,**{'MANIFEST.json':expected});sources={};total=0
    for name,sha in hashes.items():
        filename(name);require(type(sha) is str and re.fullmatch('[0-9a-f]{64}',sha))
        path=guard(source/name);info=check_path(path)
        require(path.is_file() and info.st_nlink==1 and 0<=info.st_size<=1024**3 and hash_file(path,info)==sha,'identity-unknown')
        total+=info.st_size;sources[name]=(path,info,sha)
    require(total<=1024**3,'storage-insufficient')
    parent=root/'evidence-published'
    if not parent.exists():private_directory(parent)
    guard(parent);require(len(list(parent.iterdir()))<128,'storage-insufficient')
    target=parent/identity;require(shutil.disk_usage(root).free>=total+32*1024**2,'storage-insufficient');private_directory(target)
    publication={'schema':1,'instance_uuid':instance,'export_id':identity,'generation':value['binding']['generation'],'files':{}}
    for name,(path,info,sha) in sources.items():
        copied=target/name;fd=os.open(copied,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with path.open('rb') as incoming,os.fdopen(fd,'wb') as outgoing:
            require(signature(os.fstat(incoming.fileno()))==signature(info),'identity-unknown')
            remaining=info.st_size
            while remaining:
                block=incoming.read(min(1024**2,remaining));require(bool(block),'state-conflict');outgoing.write(block);remaining-=len(block)
            require(incoming.read(1)==b'' and signature(os.fstat(incoming.fileno()))==signature(info),'state-conflict')
            outgoing.flush();os.fsync(outgoing.fileno())
        require(digest(copied)==sha and signature(check_path(path))==signature(info),'identity-unknown');copied.chmod(0o400)
        publication['files'][name]={'sha256':sha,'size':info.st_size,'signature':list(signature(copied.stat()))}
    record(target/'PUBLICATION.json',publication)
    return {'state':'evidence-published','export_id':identity,'instance_uuid':instance,'files':len(hashes),
        'original_files_modified':False,'network_listener_created':False,'uploaded':False,'findings_verified':False}


class RemoteEvidence:
    def __init__(self,policy,principal,*,now=None):
        self.policy=policy;self.principal=principal;self.now=now or (lambda:datetime.now(timezone.utc));self.config=settings(policy['evidence'])
    def instance(self,instance):
        uuid_text(instance);account=self.policy['principals'].get(self.principal)
        require(account is not None and instance in account['instances'] and instance in self.policy['instances'],'permission-denied')
        require(account['role']!='student' or self.policy['instances'][instance]['owner']==self.principal,'permission-denied')
        require(self.now()<datetime.fromisoformat(account['expires'].replace('Z','+00:00')),'permission-denied')
        root=guard(Path(self.policy['instances'][instance]['root']))
        require(GenerationStore(root).config['instance_uuid']==instance,'identity-unknown');return root
    def publication(self,root,instance,identity):
        uuid_text(identity);directory=guard(root/'evidence-published'/identity);file=guard(directory/'PUBLICATION.json')
        require(file.stat().st_size<=1024**2,'storage-insufficient');value=json.loads(file.read_text())
        require(type(value) is dict and set(value)=={'schema','instance_uuid','export_id','generation','files'}
                and type(value['schema']) is int and value['schema']==1 and value['instance_uuid']==instance and value['export_id']==identity
                and type(value['generation']) is int and value['generation']>0 and type(value['files']) is dict
                and 1<=len(value['files'])<=34,'identity-unknown')
        total=0
        for name,item in value['files'].items():
            filename(name)
            require(type(item) is dict and set(item)=={'sha256','size','signature'} and type(item['size']) is int
                and 0<=item['size']<=self.config['max_bytes'] and type(item['sha256']) is str
                and re.fullmatch('[0-9a-f]{64}',item['sha256']) and type(item['signature']) is list and len(item['signature'])==5,'identity-unknown')
            path=guard(directory/name);info=check_path(path)
            require(info.st_nlink==1 and item['size']==info.st_size and list(signature(info))==item['signature'],'identity-unknown');total+=item['size']
        require(total<=self.config['max_bytes'],'storage-insufficient')
        return directory,value
    def handle(self,action,params):
        require(action in ('evidence-list','evidence-read') and type(params) is dict)
        fields={'instance_uuid'}|({'export_id','file','sha256','offset'} if action=='evidence-read' else set())
        require(set(params)==fields);instance=params['instance_uuid'];root=self.instance(instance)
        if action=='evidence-list':
            parent=root/'evidence-published'
            if not parent.exists():return {'instance_uuid':instance,'exports':[],'automatic_transfer':False}
            guard(parent);paths=sorted(parent.iterdir());require(len(paths)<=self.config['max_exports'],'storage-insufficient');rows=[]
            for path in paths:
                directory,value=self.publication(root,instance,path.name)
                rows.append({'export_id':path.name,'generation':value['generation'],'files':[
                    {'name':name,'sha256':item['sha256'],'size':item['size']} for name,item in sorted(value['files'].items())]})
            result={'instance_uuid':instance,'exports':rows,'automatic_transfer':False,'content_executed':False}
        else:
            directory,value=self.publication(root,instance,params['export_id']);name=filename(params['file'])
            require(name in value['files'],'permission-denied');item=value['files'][name]
            require(params['sha256']==item['sha256'] and type(params['offset']) is int and 0<=params['offset']<=item['size'],'state-conflict')
            path=directory/name
            with path.open('rb') as stream:
                require(list(signature(os.fstat(stream.fileno())))==item['signature'],'identity-unknown')
                stream.seek(params['offset']);block=stream.read(min(CHUNK,item['size']-params['offset']))
                require(list(signature(os.fstat(stream.fileno())))==item['signature'],'identity-unknown')
            require(list(signature(check_path(path)))==item['signature'],'identity-unknown')
            result={'instance_uuid':instance,'export_id':value['export_id'],'file':name,'sha256':item['sha256'],
                'size':item['size'],'offset':params['offset'],'data':base64.b64encode(block).decode(),'eof':params['offset']+len(block)==item['size']}
        self.instance(instance) # 传输期间到期不返回内容。
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('publish',))
    parser.add_argument('--run',required=True,type=Path);parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--export-id',required=True);parser.add_argument('--manifest-sha256',required=True);args=parser.parse_args()
    try:print(canonical(publish(args.run,args.source,args.export_id,args.manifest_sha256)))
    except (OSError,ValueError,RuntimeError,TypeError,KeyError):
        print(canonical({'state':'refused-or-partial','preserved':True,'uploaded':False}));raise SystemExit(2)
