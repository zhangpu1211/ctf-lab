"""诊断分享预览：重新构建白名单摘要，绝不复制原始日志/路径/标识。"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

MAX_BYTES = 2 * 1024 * 1024


class DiagnosticsError(ValueError):
    pass


def preview(report):
    if type(report) is not dict or type(report.get('schema')) is not int or report['schema'] != 1:
        raise DiagnosticsError('仅接受诊断 schema 1')
    profiles = report.get('profiles', [])
    if type(profiles) is not list or len(profiles) > 256:
        raise DiagnosticsError('节点列表无效')
    host = report.get('host', {})
    if type(host) is not dict:
        raise DiagnosticsError('宿主摘要无效')
    system = host.get('system', '')
    system = next((name for name in ('Darwin','Windows','Linux')
                   if isinstance(system,str) and (system==name or system.startswith(name+' '))), 'unknown')
    machine = host.get('machine')
    machine = machine if isinstance(machine,str) and machine in ('arm64','aarch64','x86_64','AMD64') else 'unknown'
    version = report.get('ctflab_version')
    version = version if isinstance(version,str) and re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}(?:-preview\.\d{8})?',version) else 'unknown'
    result = {'schema':1,'kind':'share-preview','scope':'sanitized-summary-only',
              'ctflab_version':version,'host':{'system':system,'machine':machine},'profiles':[],
              'omitted':['raw-logs','private-paths','identifiers','addresses','process-ids','environment','free-text'],
              'uploaded':False}
    for index,node in enumerate(profiles):
        if type(node) is not dict:
            raise DiagnosticsError('节点摘要无效')
        boot = node.get('boot')
        phase = boot.get('phase') if type(boot) is dict else None
        phase = phase if phase in ('process','guest-boot','display','network') else 'unknown'
        state = node.get('state')
        state = state if isinstance(state,str) and state in ('stopped','running','unknown','failed','recovery-required') else 'unknown'
        result['profiles'].append({'node':'node-'+str(index+1),'state':state,'boot_phase':phase})
    return result


def encoded_preview(report):
    data=(json.dumps(preview(report),sort_keys=True,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    return data,hashlib.sha256(data).hexdigest()


def export(report, destination, approved_digest):
    data,digest=encoded_preview(report)
    if approved_digest!=digest:
        raise DiagnosticsError('预览已变化或尚未确认，请重新预览')
    # 不覆盖已有文件、不创建目录；只写已经预览的精确字节。
    fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    return digest


def main(argv=None):
    parser=argparse.ArgumentParser(description='从本地诊断生成可分享摘要，默认仅预览，不上传')
    parser.add_argument('source',type=Path)
    parser.add_argument('--export',type=Path)
    parser.add_argument('--preview-sha256')
    args=parser.parse_args(argv)
    try:
        with args.source.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:raise DiagnosticsError('诊断超过大小限制')
        def unique(pairs):
            value={}
            for key,item in pairs:
                if key in value:raise DiagnosticsError('重复 JSON 字段')
                value[key]=item
            return value
        def invalid(_):raise DiagnosticsError('非 JSON 常量')
        report=json.loads(raw.decode('utf-8'),object_pairs_hook=unique,parse_constant=invalid)
        data,digest=encoded_preview(report)
        if args.export is not None:
            export(report,args.export,args.preview_sha256)
            print(json.dumps({'exported':True,'sha256':digest,'uploaded':False}))
        else:
            print(json.dumps({'preview':json.loads(data),'preview_sha256':digest},ensure_ascii=False,indent=2))
        return 0
    except (OSError,ValueError,TypeError,UnicodeError,RecursionError):
        print(json.dumps({'result':'failed','error':'诊断预览或导出失败；原文件保留'},ensure_ascii=False))
        return 2


if __name__=='__main__':raise SystemExit(main())
