"""离线课程目录与精确变体解析；不下载资产、不修改内容包或运行盘。"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from ctflab_scenario_v2 import (ScenarioError, fields, identifier, integer, require,
                               text, validate_manifest)

MAX_BYTES = 1024 * 1024


def validate_catalog(value):
    try:
        fields(value, 'catalog_schema courses')
        require(type(value['catalog_schema']) is int and value['catalog_schema'] == 1, '目录版本不支持')
        courses = value['courses']
        require(type(courses) is dict and 1 <= len(courses) <= 256, '课程数量错误')
        for course_id, course in courses.items():
            identifier(course_id)
            fields(course, 'title description source license redistribution entries variants')
            for key in ('title','description','source','license'):text(course[key])
            require(course['redistribution'] in ('allowed','recipe-only','unknown'), '分发声明无效')
            variants = course['variants']
            require(type(variants) is dict and 1 <= len(variants) <= 16, '变体数量无效')
            for variant_id, variant in variants.items():
                identifier(variant_id)
                fields(variant, 'host_architecture scenario assets verification evidence_refs')
                require(variant['host_architecture'] in ('x86_64','aarch64'), '宿主架构不支持')
                scenario = validate_manifest(variant['scenario'])
                require(type(variant['assets']) is dict and set(variant['assets']) == set(scenario['assets']), '资产绑定必须精确覆盖场景')
                for filename in variant['assets'].values():
                    require(isinstance(filename,str) and '\\' not in filename and ':' not in filename and '\x00' not in filename, '资产路径无效')
                    path=PurePosixPath(filename)
                    require(not path.is_absolute() and len(path.parts)>0 and '..' not in path.parts
                            and str(path)==filename, '资产必须为规范相对路径')
                require(variant['verification'] in ('unverified','boot','service','course'), '验证等级无效')
                refs=variant['evidence_refs']
                require(type(refs) is list and len(refs)<=32, '证据引用无效')
                for ref in refs:identifier(ref)
                require(len(refs)==len(set(refs)), '证据引用重复')
                require(variant['verification']=='unverified' or len(refs)>0, '验证声明必须有证据引用')
            entries=course['entries']
            require(type(entries) is list and len(entries)<=32, '入口数量无效')
            for entry in entries:
                fields(entry,'node protocol port')
                identifier(entry['node'])
                require(entry['protocol'] in ('http','https','ssh','console'), '入口协议不支持')
                if entry['protocol']=='console':require(entry['port'] is None, '控制台不使用端口')
                else:integer(entry['port'],1,65535)
                require(all(entry['node'] in v['scenario']['nodes'] for v in variants.values()), '入口节点不在全部变体中')
        return copy.deepcopy(value)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        if isinstance(exc,ScenarioError):raise
        raise ScenarioError('目录字段类型或值无效') from None


def parse_catalog(raw):
    try:
        require(isinstance(raw,str) and len(raw.encode('utf-8'))<=MAX_BYTES, '目录大小错误')
        def unique(pairs):
            result={}
            for key,value in pairs:
                require(key not in result,'重复 JSON 字段');result[key]=value
            return result
        def invalid(_):raise ScenarioError('非 JSON 常量')
        return validate_catalog(json.loads(raw,object_pairs_hook=unique,parse_constant=invalid))
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc,ScenarioError):raise
        raise ScenarioError('目录 JSON 无效') from None


def select_variant(catalog, course_id, host_architecture, *, variant_id=None):
    catalog=validate_catalog(catalog)
    require(isinstance(course_id,str) and course_id in catalog['courses'],'未知课程')
    require(host_architecture in ('x86_64','aarch64'),'宿主架构不支持')
    course=catalog['courses'][course_id]
    candidates={key:value for key,value in course['variants'].items() if value['host_architecture']==host_architecture}
    if variant_id is None:
        require(len(candidates)==1,'变体缺失或存在歧义，请显式选择')
        variant_id=next(iter(candidates))
    require(isinstance(variant_id,str) and variant_id in candidates,'变体与宿主不匹配')
    variant=candidates[variant_id]
    return {'course_id':course_id,'variant_id':variant_id,'title':course['title'],
            'source':course['source'],'license':course['license'],'redistribution':course['redistribution'],
            'entries':course['entries'],'variant':variant,
            'verification_scope':'catalog-declaration-not-current-runtime-proof',
            'runtime_verified':False}


def inspect_assets(selection, root):
    """受信调用方选择库根；只读取普通文件，禁止链接/重解析点与越界。"""
    root=Path(root).absolute()
    for component in (root,*root.parents):
        info=component.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400,'镜像库路径含链接')
    require(root.is_dir(),'镜像库不是目录')
    # 重新校验选择中的场景，不依赖 UI 自报的哈希或文件名。
    variant=selection['variant']
    scenario=validate_manifest(variant['scenario'])
    require(type(variant['assets']) is dict and set(variant['assets'])==set(scenario['assets']),'资产绑定无效')
    results=[]
    for asset_id,relative in sorted(variant['assets'].items()):
        require(isinstance(relative,str) and '\\' not in relative and ':' not in relative,'资产路径无效')
        rel=PurePosixPath(relative)
        require(not rel.is_absolute() and len(rel.parts)>0 and '..' not in rel.parts and str(rel)==relative,'资产路径越界')
        target=root.joinpath(*rel.parts)
        try:
            for component in (target,*target.parents):
                if component==root:break
                info=component.lstat()
                require(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400,'资产路径含链接')
            info=target.stat()
            require(stat.S_ISREG(info.st_mode) and info.st_nlink==1,'资产必须为独立普通文件')
            digest=hashlib.sha256()
            with target.open('rb') as stream:
                opened=os.fstat(stream.fileno())
                require((opened.st_dev,opened.st_ino)==(info.st_dev,info.st_ino),'资产读取前发生替换')
                for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
                after=os.fstat(stream.fileno())
                require((opened.st_size,opened.st_mtime_ns,opened.st_ctime_ns)==(after.st_size,after.st_mtime_ns,after.st_ctime_ns),'资产读取中变化')
            matches=digest.hexdigest()==scenario['assets'][asset_id]['sha256']
            results.append({'asset_id':asset_id,'status':'verified' if matches else 'hash-mismatch','bytes':info.st_size})
        except FileNotFoundError:
            results.append({'asset_id':asset_id,'status':'missing','bytes':None})
    return {'assets':results,'all_present_and_verified':all(r['status']=='verified' for r in results),
            'runtime_verified':False,'course_verified':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description='离线课程目录和精确资产校验，不启动 VM')
    parser.add_argument('catalog',type=Path)
    parser.add_argument('--course',required=True)
    parser.add_argument('--host-architecture',required=True,choices=('x86_64','aarch64'))
    parser.add_argument('--variant')
    parser.add_argument('--asset-root',type=Path)
    args=parser.parse_args(argv)
    try:
        with args.catalog.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
        require(len(raw)<=MAX_BYTES,'目录过大')
        selection=select_variant(parse_catalog(raw.decode('utf-8')),args.course,args.host_architecture,variant_id=args.variant)
        if args.asset_root is not None:selection['inspection']=inspect_assets(selection,args.asset_root)
        print(json.dumps(selection,ensure_ascii=False,sort_keys=True))
        return 0 if args.asset_root is None or selection['inspection']['all_present_and_verified'] else 1
    except (OSError,UnicodeError,ScenarioError):
        print(json.dumps({'result':'failed','error':'课程目录或资产校验失败'},ensure_ascii=False))
        return 2


if __name__=='__main__':raise SystemExit(main())
