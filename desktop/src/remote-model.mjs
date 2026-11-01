import {allowed,request} from './model.mjs';
export const uuid=value=>typeof value==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
export const remoteOperations=['prepare','start','stop','reset','recover','cancel'];
export function remoteAllowed(operation,view,busy,connection,lease){
 if(!connection||connection.persisted===false||!remoteOperations.includes(operation)||!allowed(operation,view,busy,false,false))return false;
 return !connection.resource_leases||['stop','recover','cancel'].includes(operation)||uuid(lease);
}
export function currentReply(expectedEpoch,currentEpoch,target,reply){
 return expectedEpoch===currentEpoch&&reply?.target===target&&!reply.error;
}
export function acceptOverview(previous,next){
 const initial=next?.generation===0&&next?.status?.state==='unknown'&&next.status.generation===null&&next.status.state_revision===null;
 if(!next?.status||!initial&&!Number.isSafeInteger(next.status.state_revision))throw Error('远程状态版本无效，请重新读取。');
 if(initial&&previous?.instance_uuid===next.instance_uuid&&Number.isSafeInteger(previous.status?.state_revision))return previous;
 if(previous?.instance_uuid===next.instance_uuid&&Number.isSafeInteger(previous.status?.state_revision)&&previous.status.state_revision>next.status.state_revision)return previous;
 return next;
}
export function remotePayload(operation,view,instance,connection,lease,key,id){
 if(view?.instance_uuid!==instance||!uuid(instance)||!uuid(id)||!uuid(key)||!remoteAllowed(operation,view,false,connection,lease))throw Error('目标或实验状态已变化，请先刷新。');
 const parameters={prepare:{course_id:'host',baseline_id:'host'},start:{display:'headless',allow_emulation:false},stop:{},reset:{baseline_id:'host'},recover:{},cancel:{operation_id:view.status.operation_id}}[operation];
 const value={action:'submit',target:connection.target,instance_uuid:instance,request:request(operation,view,parameters,key,id)};
 if(uuid(lease))value.lease_id=lease;
 return value;
}
export function leaseAllowed(action,connection,status,selected,ttl,consent,busy=false){
 if(busy||connection?.persisted===false||!connection?.resource_leases||status?.owner_actions!==true||!Array.isArray(status.leases))return false;
 if(!Number.isSafeInteger(status.max_ttl_seconds)||status.max_ttl_seconds<10||status.max_ttl_seconds>86400)return false;
 const row=status.leases.find(item=>item.lease_id===selected);
 if(action==='lease-release')return uuid(selected)&&Boolean(row)&&row.state!=='released';
 if(!Number.isSafeInteger(ttl)||ttl<10||ttl>status.max_ttl_seconds)return false;
 if(action==='lease-renew')return uuid(selected)&&row?.state==='active'&&row.time_state==='active';
 if(action==='lease-acquire')return ['notify','request-stop'].includes(status.expiry_action)&&(!status.leases.some(item=>item.state!=='released'))&&(status.expiry_action!=='request-stop'||consent===true);
 return false;
}
export function leasePayload(action,connection,instance,status,selected,ttl,consent,id){
 if(!uuid(instance)||!uuid(id)||!leaseAllowed(action,connection,status,selected,ttl,consent))throw Error('租约状态或权限已变化，请先刷新。');
 const payload={action,target:connection.target,instance_uuid:instance,lease_id:action==='lease-acquire'?id:selected};
 if(action!=='lease-release')payload.ttl_seconds=ttl;
 if(action==='lease-acquire')payload.expiry_action=status.expiry_action;
 if(action==='lease-renew')payload.renewal_id=id;
 return payload;
}
export function leaseRetry(payload,connection,instance){
 if(!payload||payload.target!==connection?.target||payload.instance_uuid!==instance||!['lease-acquire','lease-renew','lease-release'].includes(payload.action))throw Error('原请求属于其他目标或实例，不能重试。');
 return structuredClone(payload);
}

export function displayAllowed(connection,view,node,lease,status,busy=false){
 const selected=status?.leases?.find(item=>item.lease_id===lease);
 return !busy&&connection?.persisted===true&&connection?.display_available===true&&connection?.resource_leases===true
  &&uuid(lease)&&selected?.state==='active'&&selected?.time_state==='active'
  &&view?.status?.state==='process-running'&&view?.observations?.[node]?.state==='process-running';
}
