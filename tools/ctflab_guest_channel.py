"""受保护virtio串口的宿主客户端；消息只能选择预定义来宾操作。"""
import json
import uuid
import time
from ctflab_contract import canonical,require,uuid_text,MAX_MESSAGE_BYTES
from ctflab_guest_policy import compile_policy
from ctflab_tls_endpoint import tcp,wrap_client


class GuestClient:
    def __init__(self,port,tls,certificates,plan,node,definition):
        self.policy=compile_policy(plan,node,definition['devices'],definition['flows'],
                                   containers=definition['containers'],container_cidr=definition['container_cidr'],images=definition.get('images'),endpoint=definition.get('endpoint'),routed=definition.get('routed',False),analysis=definition.get('analysis'))
        self.envelope={'plan':plan,'node':node,'devices':definition['devices'],'flows':definition['flows'],
                       'containers':definition['containers'],'container_cidr':definition['container_cidr'],'compiled':self.policy}
        for optional in ('images','endpoint','routed','analysis'):
            if optional in definition:self.envelope[optional]=definition[optional]
        self.socket=wrap_client(tcp(port,15),tls,certificates)
        self.stream=self.socket.makefile('rwb',buffering=0)
        try:
            result=self.exchange({'schema':1,'action':'configure','operation_id':str(uuid.uuid4()),'envelope':self.envelope})
            require(result.get('state')=='configured','state-conflict')
            capabilities=result.get('capabilities',[])
            require(type(capabilities) is list and len(capabilities)<=16 and all(type(v) is str for v in capabilities),'identity-unknown')
            self.capabilities=frozenset(capabilities)
        except BaseException:self.close();raise

    def exchange(self,request):
        raw=(canonical(request)+'\n').encode();require(len(raw)<=MAX_MESSAGE_BYTES+1)
        self.socket.sendall(raw)
        # readline有明确上限；丢失回应不自动重发，原operation_id用于只读查询。
        def unique(pairs):
            value={}
            for k,v in pairs:require(k not in value);value[k]=v
            return value
        # 长操作超时后旧回复可能迟到。仅不触发网络/容器动作的configure握手可排空8条同绑定旧回复。
        handshake=request['action']=='configure'
        timeout=self.socket.gettimeout() if hasattr(self.socket,'gettimeout') else 15
        deadline=time.monotonic()+(timeout or 15)
        try:
            for stale in range(9 if handshake else 1):
                remaining=deadline-time.monotonic();require(remaining>0,'control-unreachable')
                if handshake and hasattr(self.socket,'settimeout'):self.socket.settimeout(remaining)
                reply=self.stream.readline(MAX_MESSAGE_BYTES+2)
                require(reply.endswith(b'\n') and len(reply)<=MAX_MESSAGE_BYTES+1,'control-unreachable')
                value=json.loads(reply.decode('utf-8'),object_pairs_hook=unique,parse_constant=lambda _:require(False))
                require(type(value) is dict and set(value)=={'schema','instance_uuid','generation','policy_sha256','operation_id','result'})
                require(type(value['schema']) is int and value['schema']==1 and value['instance_uuid']==self.policy['instance_uuid']
                        and type(value['generation']) is int and value['generation']==self.policy['generation']
                        and value['policy_sha256']==self.policy['policy_sha256'],'identity-unknown')
                uuid_text(value['operation_id']);require(type(value['result']) is dict)
                if value['operation_id']==request['operation_id']:return value['result']
                require(handshake and stale<8,'identity-unknown')
            require(False,'control-unreachable')
        finally:
            if handshake and hasattr(self.socket,'settimeout'):self.socket.settimeout(timeout)

    def command(self,action,operation_id,*,target_operation_id=None,expected_sha256=None):
        if action in ('preparation-inspect','preparation-resume'):
            require(action in self.capabilities,'capability-unverified');uuid_text(operation_id);uuid_text(target_operation_id)
            request={'schema':1,'instance_uuid':self.policy['instance_uuid'],'generation':self.policy['generation'],
                'policy_sha256':self.policy['policy_sha256'],'action':action,'operation_id':operation_id,'target_operation_id':target_operation_id}
            if action=='preparation-resume':
                import re
                require(type(expected_sha256) is str and re.fullmatch('[0-9a-f]{64}',expected_sha256));request['expected_sha256']=expected_sha256
            else:require(expected_sha256 is None)
            return self.exchange(request)
        require(target_operation_id is None and expected_sha256 is None)
        require(action in ('status','recover','operation-status','network-apply','services-start','services-stop',
                          'containers-prepare','containers-start','containers-stop','analysis-run'))
        uuid_text(operation_id)
        return self.exchange({'schema':1,'instance_uuid':self.policy['instance_uuid'],'generation':self.policy['generation'],
                              'policy_sha256':self.policy['policy_sha256'],'action':action,'operation_id':operation_id})

    def close(self):
        self.stream.close();self.socket.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
