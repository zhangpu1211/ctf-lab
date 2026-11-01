"""离线内容/安装版本的明确入口；网络下载和回收都必须显式选择。"""
import argparse
import json
import sqlite3
from pathlib import Path
import sys

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))

from ctflab_contract import canonical,require
from ctflab_content_cache import ContentCache
from ctflab_release_store import ReleaseStore
from ctflab_windows_control import read_json
from ctflab_windows_recovery import record


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('cache-create','index-accept','fetch','pin','unpin','preview-gc','collect',
                                       'release-create','release-stage','activate','rollback','release-status',
                                       'update-initialize','update-register','update-preview','update-apply',
                                       'update-recovery','update-abandon'))
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--input',type=Path);parser.add_argument('--keys',type=Path)
    parser.add_argument('--source');parser.add_argument('--sha256');parser.add_argument('--owner')
    parser.add_argument('--mirror',help='宿主明确选择的HTTPS镜像根；不改变索引签名及原始来源身份')
    parser.add_argument('--audience',choices=('student','teacher'),default='student')
    parser.add_argument('--payload-directory',type=Path);parser.add_argument('--version');parser.add_argument('--output',type=Path)
    parser.add_argument('--workspace',type=Path);parser.add_argument('--operation-id');parser.add_argument('--plan-sha256')
    args=parser.parse_args(argv)
    def read(path):
        require(path is not None)
        return read_json(path,lambda _:None,4*1024**2)
    try:
        action=args.action
        if action=='cache-create':ContentCache.create(args.root);result={'state':'created'}
        elif action=='release-create':ReleaseStore.create(args.root);result={'state':'created'}
        elif action.startswith('update-'):
            from ctflab_release_update import UpdateCoordinator
            updates=UpdateCoordinator(ReleaseStore(args.root))
            if action=='update-initialize':result=updates.initialize()
            elif action=='update-abandon':result=updates.abandon(args.operation_id)
            elif action=='update-register':
                require(args.workspace is not None);result=updates.register(args.workspace)
            elif action=='update-preview':result=updates.preview(args.version)
            elif action=='update-apply':result=updates.apply(args.version,args.operation_id,args.plan_sha256)
            else:result=updates.recovery()
        elif action in ('release-stage','activate','rollback','release-status'):
            store=ReleaseStore(args.root)
            if action=='release-stage':
                require(args.payload_directory is not None)
                result=store.stage(args.payload_directory,read(args.input),read(args.keys))
            elif action=='activate':result=store.activate(args.version)
            elif action=='rollback':result=store.rollback()
            else:result=store.status()
        else:
            cache=ContentCache(args.root)
            if action=='index-accept':result=cache.accept(read(args.input),read(args.keys),args.source)
            elif action=='fetch':
                path=cache.download(args.source,args.sha256,audience=args.audience,mirror=args.mirror)
                result={'state':'verified','sha256':path.name,'downloaded_or_cached':True}
            elif action in ('pin','unpin'):
                getattr(cache,action)(args.owner,args.sha256);result={'state':'reference-updated'}
            elif action=='preview-gc':result={'objects':cache.preview_gc(),'deleted':False}
            else:result={'results':cache.collect(read(args.input)['objects'])}
        if args.output:record(args.output.absolute(),result)
        print(canonical(result));return 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,sqlite3.Error):
        print(canonical({'state':'failed','preserved':True,'reason':'delivery-validation-failed'}));return 2


if __name__=='__main__':raise SystemExit(main())
