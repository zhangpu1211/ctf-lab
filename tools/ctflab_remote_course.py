"""管理员将当前许可缓存映射到预分配的新课程实例；不从学生RPC接受路径或运行命令。"""
import argparse
from datetime import datetime,timezone
import hashlib
import sqlite3
from pathlib import Path
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text,identifier
from ctflab_generation_store import GenerationStore,digest
from ctflab_local_service import LocalService
from ctflab_remote import private_json,validate_policy
from ctflab_remote_assets import RemoteUploads
from ctflab_catalog import parse_catalog,select_variant,MAX_BYTES
from ctflab_scenario_v2 import instance_plan
from ctflab_qemu_driver import validate_profile
from ctflab_windows_recovery import record
from ctflab_tls_endpoint import guard


class RemoteCourse:
    def __init__(self,policy_path,principal,*,now=None):
        self.path=guard(Path(policy_path).absolute());self.sha=digest(self.path)
        self.policy=validate_policy(private_json(self.path));self.principal=principal;self.now=now or (lambda:datetime.now(timezone.utc))
        require(self.sha==digest(guard(self.path)) and principal in self.policy['principals'],'permission-denied')
        actor=self.policy['principals'][principal]
        require(actor['role'] in ('administrator','teacher') and self.now()<datetime.fromisoformat(actor['expires'].replace('Z','+00:00')),'permission-denied')
        require('uploads' in self.policy,'capability-unverified')

    def plan(self,instance,catalog_path,course,variant,profile_path,source,*,_existing=False):
        from ctflab_server_storage import verify as verify_storage
        verify_storage(self.policy,allow_unbound=instance)
        uuid_text(instance);actor=self.policy['principals'][self.principal]
        require(instance in actor['instances'] and instance in self.policy['instances'],'permission-denied')
        entry=self.policy['instances'][instance];owner=self.policy['principals'][entry['owner']]
        require(instance in owner['instances'],'permission-denied')
        root=Path(entry['root']);require(_existing or not root.exists() and not root.is_symlink(),'state-conflict')
        path=guard(Path(catalog_path).absolute());before=digest(path)
        with path.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
        require(len(raw)<=MAX_BYTES,'invalid-request')
        selection=select_variant(parse_catalog(raw.decode('utf-8')),course,'x86_64',variant_id=variant)
        require(selection['redistribution'] in ('allowed','recipe-only'),'permission-denied')
        manifest=selection['variant']['scenario'];plan=instance_plan(manifest,instance)
        profile_path=guard(Path(profile_path).absolute());profile_sha=digest(profile_path)
        profile=private_json(profile_path);validate_profile(plan,profile)
        uploads=RemoteUploads(self.policy['uploads'],entry['owner'],owner['role'],now=self.now);assets={};hashes={}
        with uploads.cache.locked() as db:
            for name,definition in manifest['assets'].items():
                sha=definition['sha256'];asset=uploads.asset(db,source,sha,'student');candidate=uploads.cache.object(sha)
                require(candidate.stat().st_size==asset['size'],'identity-unknown')
                assets[name]=str(candidate);hashes[name]=sha
            row=db.execute('SELECT payload FROM indexes WHERE source=?',(source,)).fetchone()
            index_sha=hashlib.sha256(row[0].encode()).hexdigest()
        require(before==digest(guard(path)) and profile_sha==digest(guard(profile_path))
                and self.sha==digest(guard(self.path)),'identity-unknown')
        result={'schema':1,'instance_uuid':instance,'owner':entry['owner'],'course_id':selection['course_id'],
            'variant_id':selection['variant_id'],'title':selection['title'],'entries':selection['entries'],
            'assets':hashes,'catalog_sha256':before,'index_sha256':index_sha,'profile_sha256':profile_sha,
            'policy_sha256':self.sha,'plan_sha256':plan['plan_sha256'],'verification_scope':'catalog-declaration-not-runtime-proof',
            'runtime_verified':False,'instance_created':False,'automatic_start':False}
        result['mapping_sha256']=hashlib.sha256(canonical(result).encode()).hexdigest()
        return result,(root,manifest,assets,profile)

    def provision(self,instance,catalog,course,variant,profile,source,expected,*,_declarations=None):
        uuid_text(instance);require(instance in self.policy['instances'],'permission-denied')
        root=Path(self.policy['instances'][instance]['root'])
        existing=root.exists() or root.is_symlink()
        result,(root,manifest,assets,runtime)=self.plan(instance,catalog,course,variant,profile,source,_existing=existing)
        require(type(expected) is str and expected==result['mapping_sha256'],'state-conflict')
        if _declarations is not None:require(all(result.get(k)==v for k,v in _declarations.items()),'identity-unknown')
        # GenerationStore先pin内容，再排他创建root；失败保留引用和部分现场，不覆盖/清理。
        if not existing:GenerationStore.create(root,manifest,instance,assets)
        store=GenerationStore(root)
        with store.locked():
            require(store.config['instance_uuid']==instance and store.config['manifest']==manifest,'identity-unknown')
            require({k:v['path'] for k,v in store.config['assets'].items()}==assets
                    and {k:v['sha256'] for k,v in store.config['assets'].items()}==result['assets'],'identity-unknown')
            files={'runtime-profile.json':runtime,'course-selection.json':{k:result[k] for k in
                ('course_id','variant_id','title','entries','verification_scope','runtime_verified')},'course-mapping.json':result}
            receipt=root/'course-provision-complete.json'
            if receipt.exists():
                proof=private_json(receipt)
                require(proof==self.completion(root,store,result),'identity-unknown')
            for name,value in files.items():
                path=root/name
                if path.exists() or path.is_symlink():require(private_json(path)==value,'identity-unknown')
                else:
                    snapshot=store.snapshot()
                    require(not snapshot['active_generation'] and not snapshot['generations'] and not snapshot['unresolved'],'state-conflict')
                    record(path,value)
            if (root/'desktop-contract').exists():LocalService(root/'desktop-contract')
            else:
                snapshot=store.snapshot();require(not snapshot['active_generation'] and not snapshot['generations'] and not snapshot['unresolved'],'state-conflict')
                LocalService.create(root/'desktop-contract')
            if 'storage_pool' in self.policy:
                from ctflab_server_storage import _register_context
                _register_context(self.policy,instance)
            if not receipt.exists():
                snapshot=store.snapshot();require(not snapshot['active_generation'] and not snapshot['generations'] and not snapshot['unresolved'],'state-conflict')
                record(receipt,self.completion(root,store,result))
        require(digest(guard(self.path))==self.sha,'permission-denied')
        return {'state':'course-instance-configured','instance_uuid':instance,'mapping_sha256':expected,'already_configured':existing,
            'instance_created':True,'runtime_verified':False,'automatic_start':False,'original_assets_modified':False}

    @staticmethod
    def completion(root,store,result):
        ledger=root/'ledger.sqlite3'
        return {'schema':1,'instance_uuid':store.config['instance_uuid'],'mapping_sha256':result['mapping_sha256'],
                'root_identity':[root.stat().st_dev,root.stat().st_ino],
                'ledger_identity':[ledger.stat().st_dev,ledger.stat().st_ino],
                'config_sha256':hashlib.sha256(canonical(store.config).encode()).hexdigest(),
                'runtime_profile_sha256':digest(root/'runtime-profile.json')}


def validate_offers(offers,policy):
    require(type(offers) is dict and len(offers)<=64)
    for name,item in offers.items():
        identifier(name)
        require(type(item) is dict and set(item)=={'catalog','catalog_sha256','course_id','variant_id','profile','profile_sha256','source','instances'})
        for key in ('course_id','variant_id'):identifier(item[key])
        from ctflab_content_cache import source_url
        source_url(item['source']);require(item['source'] in policy.get('uploads',{}).get('sources',[]),'permission-denied')
        for key in ('catalog','profile'):
            require(type(item[key]) is str and Path(item[key]).is_absolute() and '..' not in Path(item[key]).parts)
        for key in ('catalog_sha256','profile_sha256'):
            require(type(item[key]) is str and len(item[key])==64 and all(c in '0123456789abcdef' for c in item[key]))
        require(type(item['instances']) is list and len(item['instances'])<=1024 and len(set(item['instances']))==len(item['instances'])
                and set(item['instances'])<=set(policy['instances']))
    require(not offers or 'uploads' in policy,'capability-unverified')
    return offers


class CourseOffers:
    """远程只选择服务器预登记offer/实例；不接收路径、脚本或宿主参数。"""
    def __init__(self,path,principal,*,now=None,expected_policy=None):
        self.mapper=RemoteCourse(path,principal,now=now);self.policy=self.mapper.policy
        require(expected_policy is None or self.policy==expected_policy,'permission-denied')
        require('courses' in self.policy,'capability-unverified')
        self.offers=validate_offers(self.policy['courses'],self.policy)
        self.account=self.policy['principals'][principal]

    def selected(self,name):
        identifier(name);require(name in self.offers,'permission-denied');item=self.offers[name]
        require(digest(guard(Path(item['catalog'])))==item['catalog_sha256']
                and digest(guard(Path(item['profile'])))==item['profile_sha256'],'identity-unknown')
        require(digest(guard(self.mapper.path))==self.mapper.sha,'permission-denied')
        return item

    def handle(self,action,parameters):
        require(type(parameters) is dict)
        if action=='course-list':
            require(not parameters);rows=[]
            for name in sorted(self.offers):
                item=self.selected(name);scope=sorted(set(item['instances'])&set(self.account['instances']))
                if not scope:continue
                with Path(item['catalog']).open('rb') as stream:raw=stream.read(MAX_BYTES+1)
                require(len(raw)<=MAX_BYTES)
                choice=select_variant(parse_catalog(raw.decode('utf-8')),item['course_id'],'x86_64',variant_id=item['variant_id'])
                self.selected(name)
                rows.append({'offer_id':name,'course_id':item['course_id'],'variant_id':item['variant_id'],'title':choice['title'],
                    'instances':scope,'runtime_verified':False})
            require(digest(guard(self.mapper.path))==self.mapper.sha,'permission-denied')
            return {'offers':rows,'automatic_start':False,'runtime_verified':False}
        fields={'offer_id','instance_uuid'}|({'mapping_sha256'} if action=='course-provision' else set())
        require(action in ('course-preview','course-provision') and set(parameters)==fields)
        item=self.selected(parameters['offer_id']);instance=uuid_text(parameters['instance_uuid'])
        require(instance in item['instances'] and instance in self.account['instances'],'permission-denied')
        args=(instance,item['catalog'],item['course_id'],item['variant_id'],item['profile'],item['source'])
        declared={'catalog_sha256':item['catalog_sha256'],'profile_sha256':item['profile_sha256']}
        if action=='course-provision':return self.mapper.provision(*args,parameters['mapping_sha256'],_declarations=declared)
        value=self.mapper.plan(*args,_existing=Path(self.policy['instances'][instance]['root']).exists())[0]
        require(all(value[k]==v for k,v in declared.items()),'identity-unknown');self.selected(parameters['offer_id'])
        return value


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('preview','provision'))
    for name in ('policy','catalog','profile'):parser.add_argument('--'+name,required=True,type=Path)
    for name in ('principal','instance','course','variant','source'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--mapping-sha256');args=parser.parse_args(argv)
    try:
        require(bool(args.mapping_sha256)==(args.action=='provision'))
        mapper=RemoteCourse(args.policy,args.principal)
        params=(args.instance,args.catalog,args.course,args.variant,args.profile,args.source)
        result=mapper.provision(*params,args.mapping_sha256) if args.action=='provision' else mapper.plan(*params)[0]
        print(canonical(result));return 0
    except (OSError,ValueError,RuntimeError,TypeError,KeyError,sqlite3.Error):
        print(canonical({'state':'refused-or-partial','preserved':True,'automatic_start':False}));return 2


if __name__=='__main__':raise SystemExit(main())
