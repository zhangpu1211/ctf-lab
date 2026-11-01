export function canManageVersions(status,busy=false){return Boolean(status&&/^[0-9a-f]{64}$/.test(status.target||'')&&status.read_only===false&&!busy);}
export function sameVersionTarget(status,reply){return Boolean(status?.target&&(reply?.library_target||reply?.target)===status.target);}
export function versionChangePayload(status,preview,version,operation){
 if(!canManageVersions(status)||!preview||preview.target!==version||typeof preview.plan_sha256!=='string')throw Error('请重新核对版本预览。');
 return {action:'update-apply',target:status.target,version,operation_id:operation,plan_sha256:preview.plan_sha256};
}
export function onlineDownloadPayload(status,preview,source,maximum,operation){
 if(!canManageVersions(status)||!sameVersionTarget(status,preview)||preview.source!==source||preview.maximum!==maximum||!/^[0-9a-f]{64}$/.test(preview.plan_sha256||''))throw Error('来源或版本预览已变化，请重新核对。');
 return {action:'online-download',target:status.target,source,maximum,operation_id:operation,plan_sha256:preview.plan_sha256};
}
const setupHash=x=>typeof x==='string'&&/^[0-9a-f]{64}$/.test(x);
const setupUUID=x=>typeof x==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(x);
export function bootstrapCreatePayload(plan,source,operation){
 if(!plan||plan.source!==source||plan.created!==false||plan.publisher_identity_verified!==false||!setupHash(plan.plan_sha256)||!setupHash(plan.source_sha256)||!setupHash(plan.keys_sha256)||!setupUUID(operation))throw Error('设置预览或公钥已变化，请重新核对。');
 return {action:'bootstrap-create',public_keys:source,operation_id:operation,plan_sha256:plan.plan_sha256};
}
export function bootstrapResumePayload(view){
 if(!view||view.read_only!==false||view.ready!==false||!setupUUID(view.operation_id)||!setupHash(view.plan_sha256))throw Error('原设置记录尚未核验。');
 return {action:'bootstrap-resume',operation_id:view.operation_id,plan_sha256:view.plan_sha256};
}
