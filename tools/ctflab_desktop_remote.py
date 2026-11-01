"""桌面远程目标的固定SSH桥接；显式连接，不开放显示、导入或任意命令。"""
import argparse
import hashlib
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent))
from ctflab_contract import canonical,require,uuid_text,validate_request,MAX_MESSAGE_BYTES,ContractError,STATES,identifier,integer
from ctflab_local_adapter import failure
from ctflab_generation_store import digest
from ctflab_remote import private_json,ssh_arguments,SSHSession,decode,RESPONSE_LIMIT
from ctflab_tls_endpoint import guard


def target(config_path):
    path=guard(Path(config_path).absolute());before=digest(path)
    config=private_json(path);ssh_arguments(config)
    identity=guard(Path(config['identity']));require(identity.stat().st_size<=1024**2)
    value=hashlib.sha256(canonical({'config':config,'identity_sha256':digest(identity)}).encode()).hexdigest()
    require(before==digest(guard(path)),'identity-unknown')
    return config,value


def request_parameters(value):
    require(type(value) is dict and type(value.get('action')) is str)
    action=value['action'];require(action in ('connect','overview','events','submit','lease-status','lease-acquire','lease-renew','lease-release',
        'course-list','course-preview','course-provision','audit-review','audit-settlement-preview','audit-settle'))
    if action.startswith(('course-','audit-')):
        fields={'course-list':set(),'course-preview':{'offer_id','instance_uuid'},'course-provision':{'offer_id','instance_uuid','mapping_sha256'},
            'audit-review':{'after','limit','checkpoint'},'audit-settlement-preview':{'attempt_id'},'audit-settle':{'attempt_id','review_sha256'}}[action]
        require(set(value)=={'action','target'}|fields)
        require(type(value['target']) is str and re.fullmatch('[0-9a-f]{64}',value['target']),'identity-unknown')
        params={k:value[k] for k in fields}
        if 'offer_id' in params:identifier(params['offer_id'])
        if 'instance_uuid' in params:uuid_text(params['instance_uuid'])
        if 'attempt_id' in params:uuid_text(params['attempt_id'])
        for key in ('mapping_sha256','review_sha256'):
            if key in params:require(type(params[key]) is str and re.fullmatch('[0-9a-f]{64}',params[key]) is not None)
        if action=='audit-review':
            integer(params['after']);integer(params['limit'],1);require(params['limit']<=100)
            if params['checkpoint'] is not None:
                checkpoint=params['checkpoint'];require(type(checkpoint) is dict and set(checkpoint)=={'seq','sha256'})
                integer(checkpoint['seq']);require(type(checkpoint['sha256']) is str and re.fullmatch('[0-9a-f]{64}',checkpoint['sha256']) is not None)
        return action,params,{}
    fields={'action'} if action=='connect' else {'action','target','instance_uuid'}
    if action=='events':fields.add('after')
    if action=='submit':fields.add('request')
    lease_fields={'lease-acquire':{'lease_id','ttl_seconds','expiry_action'},
                  'lease-renew':{'lease_id','renewal_id','ttl_seconds'},'lease-release':{'lease_id'}}
    fields.update(lease_fields.get(action,set()))
    require(set(value)==fields or action=='submit' and set(value)==fields|{'lease_id'})
    if action!='connect':
        require(type(value['target']) is str and re.fullmatch('[0-9a-f]{64}',value['target']),'identity-unknown')
        uuid_text(value['instance_uuid'])
    params={}
    if action in lease_fields:
        params={key:value[key] for key in lease_fields[action]}
        uuid_text(params['lease_id'])
        if action=='lease-renew':uuid_text(params['renewal_id'])
        if action!='lease-release':require(type(params['ttl_seconds']) is int and 10<=params['ttl_seconds']<=86400)
        if action=='lease-acquire':require(params['expiry_action'] in ('notify','request-stop'))
    if action=='events':
        require(type(value['after']) is int and 0<=value['after']<=2**53-1);params['after']=value['after']
    if action=='submit':
        request=validate_request(value['request'])
        require(request['instance_uuid']==value['instance_uuid'],'permission-denied')
        require(request['operation'] in ('status','prepare','start','stop','reset','recover','cancel'),'permission-denied')
        params['request']=request
        if 'lease_id' in value:params['lease_id']=uuid_text(value['lease_id'])
    return action,params,lease_fields


def dispatch(config_path,value,*,session=SSHSession,cancel_requested=None):
    action,params,lease_fields=request_parameters(value)
    require(cancel_requested is None or action=='connect')
    config,identity=target(config_path)
    if action!='connect':require(value['target']==identity,'identity-unknown')
    options={'timeout':30}
    if cancel_requested is not None:options['cancel_requested']=cancel_requested
    with session(config,**options) as channel:
        handshake=channel.request('handshake',{})
        require(type(handshake) is dict and handshake.get('state')=='compatible'
                and type(handshake.get('contract_version')) is int and handshake['contract_version']==1
                and handshake.get('role') in ('student','teacher','administrator'),'version-mismatch')
        require(type(handshake.get('resource_leases',False)) is bool,'version-mismatch')
        for capability in ('course_management','audit_management'):
            require(type(handshake.get(capability,False)) is bool,'version-mismatch')
        require(type(handshake.get('asset_upload',False)) is bool,'version-mismatch')
        require(type(handshake.get('display_tunnel',False)) is bool,'version-mismatch')
        require(type(handshake.get('evidence_download',False)) is bool,'version-mismatch')
        if action=='connect':
            listing=channel.request('list',{});require(type(listing) is dict and set(listing)=={'instances'})
            instances=listing['instances'];require(type(instances) is list and len(instances)<=1024)
            for instance in instances:uuid_text(instance)
            require(len(set(instances))==len(instances))
            result={'server_uuid':config['server_uuid'],'role':handshake['role'],'instances':instances,
                    'resource_leases':handshake.get('resource_leases',False),
                    'course_management':handshake.get('course_management',False),'audit_management':handshake.get('audit_management',False),
                    'asset_upload':handshake.get('asset_upload',False),'display_available':handshake.get('display_tunnel',False),'evidence_available':handshake.get('evidence_download',False)}
        else:
            if action.startswith('course-'):
                require(handshake.get('course_management',False) and handshake['role'] in ('teacher','administrator'),'permission-denied')
            elif action.startswith('audit-'):
                require(handshake.get('audit_management',False) and handshake['role']=='administrator','permission-denied')
            else:params['instance_uuid']=value['instance_uuid']
            if action.startswith('lease-'):require(handshake.get('resource_leases',False),'capability-unverified')
            if action=='submit' and handshake.get('resource_leases',False) and params['request']['operation'] not in ('status','cancel','stop','recover'):
                require('lease_id' in params,'permission-denied')
            result=channel.request(action,params)
            require(type(result) is dict,'invalid-request')
            if action in ('course-preview','course-provision'):
                require(result.get('instance_uuid')==params['instance_uuid'],'identity-unknown')
                require(type(result.get('mapping_sha256')) is str and re.fullmatch('[0-9a-f]{64}',result['mapping_sha256']) is not None,'identity-unknown')
                if action=='course-provision':require(result['mapping_sha256']==params['mapping_sha256'],'identity-unknown')
            if action in ('audit-settlement-preview','audit-settle'):
                require(result.get('attempt_id')==params['attempt_id'] and result.get('original_worker_result')=='unknown'
                        and result.get('vm_observed') is False and result.get('automatic_replay') is False,'identity-unknown')
            if action=='course-provision':
                require(result.get('automatic_start') is False and result.get('runtime_verified') is False,'identity-unknown')
            if action in lease_fields:
                require(result.get('instance_uuid')==value['instance_uuid'] and result.get('lease_id')==params['lease_id'],'identity-unknown')
                if action=='lease-renew':require(result.get('renewal_id')==params['renewal_id'],'identity-unknown')
            if action in ('overview','submit'):
                require(result.get('instance_uuid')==value['instance_uuid'],'identity-unknown')
            if action=='overview':
                require(type(result.get('status')) is dict and result['status'].get('instance_uuid')==value['instance_uuid'],'identity-unknown')
            if action=='submit':require(result.get('request_id')==params['request']['request_id'],'identity-unknown')
            if action in ('overview','submit'):
                status=result['status'] if action=='overview' else result
                initial=action=='overview' and result.get('generation')==0 and type(result.get('generation')) is int and status.get('generation') is None and status.get('state')=='unknown' and status.get('state_revision') is None
                require(type(status.get('state')) is str and status['state'] in STATES
                        and (initial or type(status.get('state_revision')) is int and 0<=status['state_revision']<=2**53-1),'invalid-request')
    # 配置/身份文件在传输期间变化时，返回未知而非沿用上一次目标；不重发。
    require(target(config_path)[1]==identity,'identity-unknown')
    response={'target':identity,'result':result};require(len(canonical(response).encode())<=RESPONSE_LIMIT)
    return response


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True,type=Path)
    args=parser.parse_args(argv)
    try:
        value=decode(sys.stdin.buffer.read(MAX_MESSAGE_BYTES+1));result=dispatch(args.config,value)
        print(canonical(result));return 0
    except ContractError as error:result=failure(error.code)
    except (OSError,ValueError,RuntimeError,TypeError,KeyError,sqlite3.Error,subprocess.SubprocessError):result=failure('control-unreachable',result='unknown')
    print(canonical({'error':result['error'],'state':result['state'],'result':result['result'],'automatic_replay':False}));return 2


if __name__=='__main__':raise SystemExit(main())
