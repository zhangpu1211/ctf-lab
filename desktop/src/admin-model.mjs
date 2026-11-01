import {uuid} from './remote-model.mjs';
export const adminMutations=['course-provision','audit-settle'];
const hash=x=>typeof x==='string'&&/^[0-9a-f]{64}$/.test(x);
export function adminAllowed(c,action){return Boolean(c?.config?.savedId&&(action.startsWith('course-')?c.course_management&&['teacher','administrator'].includes(c.role):c.audit_management&&c.role==='administrator'));}
export function adminPayload(c,action,values={}){
 if(!adminAllowed(c,action))throw Error('当前目标未授权此管理入口。');
 let fields;
 if(action==='course-list')fields=[];
 else if(action==='course-preview'||action==='course-provision'){
  fields=['offer_id','instance_uuid'];if(action==='course-provision')fields.push('mapping_sha256');
  if(!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$/.test(values.offer_id)||!uuid(values.instance_uuid)||!c.instances.includes(values.instance_uuid))throw Error('请选择登记课程和分配实例。');
  if(action==='course-provision'&&!hash(values.mapping_sha256))throw Error('请先重新预览课程配置。');
 }else if(action==='audit-review'){
  fields=['after','limit','checkpoint'];if(!Number.isSafeInteger(values.after)||values.after<0||!Number.isInteger(values.limit)||values.limit<1||values.limit>100)throw Error('审计分页无效。');
  if(values.checkpoint!==null&&(!Number.isSafeInteger(values.checkpoint?.seq)||values.checkpoint.seq<0||!hash(values.checkpoint.sha256)))throw Error('审计检查点无效。');
 }else if(action==='audit-settlement-preview'||action==='audit-settle'){
  fields=['attempt_id'];if(!uuid(values.attempt_id))throw Error('请选择未决审计记录。');
  if(action==='audit-settle'){fields.push('review_sha256');if(!hash(values.review_sha256))throw Error('请重新预览观察记录。');}
 }else throw Error('管理动作不受支持。');
 if(Object.keys(values).sort().join()!==fields.sort().join())throw Error('管理参数不匹配。');
 return {action,target:c.target,...values};
}
export function adminResult(c,payload,reply){
 if(reply?.target!==c.target||reply.error||!reply.result)throw Error(reply?.error?.message||'管理响应无法核验。');
 const r=reply.result;
 if(payload.action==='course-preview'||payload.action==='course-provision'){
  if(r.instance_uuid!==payload.instance_uuid||!hash(r.mapping_sha256)||payload.action==='course-provision'&&r.mapping_sha256!==payload.mapping_sha256)throw Error('课程绑定不匹配。');
 }
 if(payload.action==='audit-settlement-preview'||payload.action==='audit-settle'){
  if(r.attempt_id!==payload.attempt_id||r.original_worker_result!=='unknown'||r.vm_observed!==false||r.automatic_replay!==false)throw Error('审计观察绑定不匹配。');
 }
 return r;
}
