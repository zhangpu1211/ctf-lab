"""按许可生成学生只读镜像材料；保持签名与内容身份，不启动网络服务。"""
import argparse
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import shutil
import sys
import uuid

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))

from ctflab_contract import canonical,require
from ctflab_content_cache import ContentCache,verify_index
from ctflab_generation_store import private_directory,digest
from ctflab_windows_control import read_json
from ctflab_windows_recovery import record


def build(cache,envelope,keys,source,destination,*,now=None):
    payload,index_sha=verify_index(envelope,keys,source,now=now)
    # 不擅自删掉教师条目后沿用旧签名；需要发布者签名的纯学生索引。
    require(bool(payload['assets']) and all(a['audience']=='student' and a['redistribution']=='allowed' for a in payload['assets'].values()),'permission-denied')
    destination=Path(destination).absolute()
    require(not destination.exists() and destination!=cache.root
            and cache.root not in destination.parents and destination not in cache.root.parents,'permission-denied')
    names=set();planned={}
    reserved={'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}
    for sha,asset in payload['assets'].items():
        name=asset['path'];parts=PurePosixPath(name).parts;folded=name.casefold()
        require(not any(p.split('.')[0].upper() in reserved or p!=p.rstrip(' .') for p in parts)
                and parts[0].casefold() not in ('index.json','mirror.json','sha256sums')
                and folded not in names and not any(folded.startswith(n+'/') or n.startswith(folded+'/') for n in names))
        names.add(folded);planned[sha]=name
        cache.object(sha)
    owner='mirror-'+str(uuid.uuid4())
    for sha in planned:cache.pin(owner,sha)
    required=sum(a['size'] for a in payload['assets'].values())
    require(shutil.disk_usage(destination.parent).free>required+16*1024**2,'storage-insufficient')
    private_directory(destination)
    with cache.locked():
        for sha,name in planned.items():
            original=cache.object(sha);target=destination/name
            for parent in reversed(target.parents):
                if parent!=destination and destination in parent.parents and not parent.exists():private_directory(parent)
            fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with original.open('rb') as input,os.fdopen(fd,'wb') as output:
                shutil.copyfileobj(input,output);output.flush();os.fsync(output.fileno())
            require(digest(target)==sha and target.stat().st_size==payload['assets'][sha]['size'],'state-conflict')
    record(destination/'INDEX.json',envelope)
    receipt={'schema':1,'kind':'student-mirror-materials','origin':source,'signed_index_sha256':index_sha,
             'cache_reference':owner,'files':{name:sha for sha,name in planned.items()},
             'teacher_materials_included':False,'service_started':False,'runtime_verified':False}
    record(destination/'MIRROR.json',receipt)
    return receipt


def main(argv=None):
    values=list(sys.argv[1:] if argv is None else argv)
    if values and values[0]=='serve':return serve_main(values[1:])
    parser=argparse.ArgumentParser(description=__doc__,epilog='回环HTTPS只读服务：ctflab_mirror.py serve --help；不改变系统信任或对外监听。')
    for name in ('cache','index','keys','destination'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--source',required=True)
    args=parser.parse_args(argv)
    try:
        read=lambda p:read_json(p,lambda _:None,4*1024**2)
        value=build(ContentCache(args.cache),read(args.index),read(args.keys),args.source,args.destination)
        print(canonical({'state':'created','assets':len(value['files']),'service_started':False}));return 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError):
        print(canonical({'state':'failed','preserved':True,'service_started':False}));return 2


def serve_main(argv=None):
    parser=argparse.ArgumentParser(description='只在127.0.0.1提供现有学生镜像的HTTPS只读服务；不改系统信任')
    for name in ('root','keys','certificate','key'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--origin',required=True);parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args(argv)
    try:
        from ctflab_mirror_service import MirrorView,MirrorServer
        from ctflab_tls_endpoint import guard
        keys=read_json(args.keys,guard,1024**2)
        view=MirrorView(args.root,keys,args.origin)
        with MirrorServer(view,args.certificate,args.key,port=args.port) as server:
            print(canonical({'state':'loopback-mirror-listening','host':'127.0.0.1','port':server.server_port,
                'read_only':True,'system_trust_modified':False,'lan_listener':False}),flush=True)
            try:server.serve_forever()
            except KeyboardInterrupt:pass
        return 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError):
        print(canonical({'state':'refused-or-failed','preserved':True,'lan_listener':False}));return 2


if __name__=='__main__':raise SystemExit(main())
