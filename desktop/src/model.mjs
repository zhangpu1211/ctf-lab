export const labels = {unknown:'尚未取得状态', prepared:'已准备', stopped:'已停止', 'process-running':'进程运行中', 'guest-ready':'来宾已就绪', 'service-ready':'服务已就绪', 'course-verified':'课程已验收', 'recovery-required':'需要恢复核验', preparing:'正在准备', starting:'正在启动', stopping:'正在停止', resetting:'正在重置', recovering:'正在核验', failed:'未完成'};
export function request(operation, overview, parameters, key, requestId) {
  const value = {protocol:'ctflab-local', version:1, request_id:requestId, operation, instance_uuid:overview.instance_uuid};
  if(operation !== 'status') Object.assign(value, {expected_generation:operation==='prepare'?null:overview.status.generation, expected_state_revision:operation==='prepare'?null:overview.status.state_revision, idempotency_key:key, parameters});
  return value;
}
export function allowed(operation, view, busy, emulationConsent=false,checkFreshness=true) {
  if(!view || busy) return false;
  if(operation==='start' && (view.runtime?.dependencies?.tls_control===false || view.runtime?.emulation_required===true && !emulationConsent))return false;
  const state=view.status.state;
  if(operation==='cancel') return Boolean(view.status.operation_id && ['accepted','unknown'].includes(view.status.result));
  if(view.status.result==='accepted'||view.execution?.identity==='running') return false;
  if(checkFreshness&&operation!=='recover'&&!overviewFresh(view))return false;
  return {prepare:view.generation===0 && state==='unknown',start:['prepared','stopped'].includes(state),stop:['process-running','guest-ready','service-ready','recovery-required'].includes(state),reset:['prepared','stopped'].includes(state),recover:view.generation>0,guest:state==='process-running'}[operation]===true;
}
const eventFields=['protocol','version','event_id','sequence','timestamp','instance_uuid','generation','operation_id','state_revision','stage','state'];
const eventStages=new Set(['intent','executing','cancel-requested','failed','cancelled','completed']);
const safeInteger=(value,minimum=0)=>Number.isSafeInteger(value)&&value>=minimum;
export function consumeEvents(cursor, response, instance) {
  // 桥接原样返回事件数组；拒绝未知形状，不能把未识别的回复默认为空列表。
  const refused=()=>({cursor:0,events:[],reload:true});
  if(!safeInteger(cursor)||!Array.isArray(response)||response.length>1000)return refused();
  const events=[],seen=new Map(),identities=new Map();let expectedInstance=instance;
  for(const event of response){
    if(!event||typeof event!=='object'||Array.isArray(event)||Object.keys(event).length!==eventFields.length||!eventFields.every(key=>Object.hasOwn(event,key)))return refused();
    if(event.protocol!=='ctflab-local'||event.version!==1||!safeInteger(event.sequence,1)||!guestUuid(event.event_id)||!guestUuid(event.operation_id)||!guestUuid(event.instance_uuid)||!safeInteger(event.generation,1)||!safeInteger(event.state_revision)||(typeof event.state!=='string'||!Object.hasOwn(labels,event.state))||!eventStages.has(event.stage)||typeof event.timestamp!=='string'||[...event.timestamp].length>64)return refused();
    if(expectedInstance==null)expectedInstance=event.instance_uuid;
    if(event.instance_uuid!==expectedInstance||identities.has(event.event_id)&&identities.get(event.event_id)!==event.sequence)return refused();
    identities.set(event.event_id,event.sequence);
    if(event.sequence<=cursor)continue;
    if(seen.has(event.sequence)){
      if(!eventFields.every(key=>seen.get(event.sequence)[key]===event[key]))return refused();
      continue;
    }
    if(event.sequence!==cursor+events.length+1)return refused();
    seen.set(event.sequence,event);events.push({...event});
  }
  return {cursor:cursor+events.length,events,reload:false};
}

export function refreshEvents(cursor,response,view){
 const result=consumeEvents(cursor,response,view?.instance_uuid);
 if(!result.reload)return result;
 const status=view?.status;
 // 只用本次状态快照重定位；未绑定的回复不能决定下一页游标。
 const bound=status?.protocol==='ctflab-local'&&status.version===1&&guestUuid(view?.instance_uuid)&&status.instance_uuid===view.instance_uuid&&safeInteger(status.cursor);
 return {...result,cursor:bound?status.cursor:0};
}

export function canResumeDispatch(view, busy) {
  const d=view?.dispatch, s=view?.status;
  return !busy && overviewFresh(view) && Boolean(d && s && d.resume_allowed===true && d.active===true &&
    d.status==='pending' && d.automatic_replay===false && s.result==='accepted' &&
    d.instance_uuid===view.instance_uuid && d.operation_id===s.operation_id &&
    Number.isSafeInteger(d.state_revision) && d.state_revision>=0 && d.state_revision===s.state_revision &&
    Number.isSafeInteger(d.generation) && d.generation>=1 && d.generation===s.generation && view.execution?.identity!=='running');
}

export function canRestartPreparation(view, busy) {
  const p=view?.preparation, s=view?.status;
  return !busy && overviewFresh(view) && Boolean(p && s && view.generation===0 && p.restart_allowed===true &&
    p.instance_uuid===view.instance_uuid && p.automatic_replay===false &&
    typeof p.operation_id==='string' && p.operation_id.length>0 &&
    ['executing','unknown','failed','completed'].includes(p.status) && s.result!=='accepted' &&
    p.generation===1 && s.generation===1 &&
    Number.isSafeInteger(p.state_revision) && p.state_revision>=0 && p.state_revision===s.state_revision &&
    view.execution?.identity!=='running');
}

export function canRearmObserver(view, node, busy) {
 return Boolean(view && !busy && overviewFresh(view) && view.generation>0 && view.status.generation===view.generation &&
  !view.status.operation_id && view.status.result==='completed' && view.execution?.identity!=='running' &&
  view.observations?.[node]?.state==='process-running' && view.supervision?.[node]?.observer==='unknown');
}

export function configurationReady(files,busy){
 return !busy&&['manifest','assets','profile'].every(key=>typeof files?.[key]==='string'&&files[key].trim().length>0);
}

const guestUuid=value=>typeof value==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
export function canInspectGuestPreparation(view,node,target,busy){
 return allowed('guest',view,busy)&&view.observations?.[node]?.state==='process-running'&&view.guest_agents?.[node]?.containers===true&&guestUuid(target);
}
export function canResumeGuestPreparation(view,node,target,busy){
 if(!canInspectGuestPreparation(view,node,target,busy))return false;
 const info=view.guest_agents[node],snapshot=info.last_result;
 return info.last_action==='preparation-inspect'&&snapshot?.state==='preparation-observed'&&snapshot.operation_id===target&&snapshot.can_resume===true&&snapshot.automatic_replay===false&&typeof snapshot.resume_sha256==='string'&&/^[0-9a-f]{64}$/.test(snapshot.resume_sha256);
}
export function guestPreparationParameters(view,node,target,resume=false){
 if(!(resume?canResumeGuestPreparation(view,node,target,false):canInspectGuestPreparation(view,node,target,false)))throw Error('请先恢复核验实验进程，再核对原准备记录；现场变化后须重新核对。');
 const value={node,action:resume?'preparation-resume':'preparation-inspect',target_operation_id:target};
 if(resume)value.expected_sha256=view.guest_agents[node].last_result.resume_sha256;
 return value;
}

// 缺失、未来、过期或不完整的采样不能继续作为当前运行事实。
export function overviewFresh(view,now=Date.now(),requireComplete=true){
 const f=view?.freshness;if(!f||f.schema!==1||(requireComplete&&f.complete!==true)||f.coherent===false||!Number.isFinite(now))return false;
 if(![f.sampled_at,f.valid_until].every(v=>typeof v==='string'&&/(?:Z|[+-]\d{2}:\d{2})$/.test(v)))return false;
 const sampled=Date.parse(f.sampled_at),until=Date.parse(f.valid_until);
 return Number.isFinite(sampled)&&Number.isFinite(until)&&sampled<=now&&now<=until&&until>sampled&&until-sampled<=60000;
}
export async function boundedCall(call,{timeoutMs=30000,setTimer=setTimeout,clearTimer=clearTimeout}={}){
 if(typeof call!=='function'||!Number.isInteger(timeoutMs)||timeoutMs<1||timeoutMs>120000)throw Error('请求期限无效');
 let timer;try{return await Promise.race([Promise.resolve().then(call),new Promise((_,reject)=>{
  timer=setTimer(()=>{const e=Error('请求暂未返回，结果可能已记录；请读取状态或查询原请求，不会自动重发。');e.code='reply-timeout';reject(e);},timeoutMs);
 })]);}finally{clearTimer(timer);}
}
export function createRefreshScope(){
 let root='',epoch=0,active=null;
 return {attach(value){root=value;epoch++;active=null;},begin(value){if(!value||value!==root||active)return null;active={root,epoch};return active;},
  current(ticket){return ticket!==null&&active===ticket&&ticket.root===root&&ticket.epoch===epoch;},finish(ticket){if(active===ticket)active=null;}};
}

const operationNames=new Set(['prepare','start','stop','reset','recover','cancel','guest']);
const operationStatuses=new Set(['pending','executing','unknown','failed','completed']);
function historicalEnvelope(reply,instance){
 if(!reply||reply.instance_uuid!==instance||reply.historical!==true||reply.current_runtime_verified!==false||reply.automatic_replay!==false)throw Error('保存记录的实例或证据范围不符，请重新读取。');
}
function savedOperation(record){
 if(!record||!guestUuid(record.operation_id)||!guestUuid(record.request_id)||!operationNames.has(record.operation)||!operationStatuses.has(record.status)||typeof record.response_recorded!=='boolean'||typeof record.cancel_requested!=='boolean')throw Error('保存的操作记录未能核验。');
 if(record.operation==='prepare'?record.expected_generation!==null:!Number.isSafeInteger(record.expected_generation)||record.expected_generation<1)throw Error('保存记录的代次无效。');
 if(['completed','failed'].includes(record.status)&&!record.response_recorded)throw Error('保存记录缺少原响应。');
 return record;
}
export function operationHistory(reply,instance){
 historicalEnvelope(reply,instance);
 if(reply.state!=='operation-history'||!Array.isArray(reply.operations)||reply.operations.length>50||typeof reply.truncated!=='boolean')throw Error('保存记录列表无效。');
 const rows=reply.operations.map(savedOperation);if(new Set(rows.map(row=>row.operation_id)).size!==rows.length)throw Error('保存记录重复，请核对原账本。');
 if(reply.truncated?(!guestUuid(reply.next_before)||reply.next_before!==rows.at(-1)?.operation_id):reply.next_before!==null)throw Error('保存记录分页标识不符。');
 return rows;
}
export function operationResult(reply,instance,operation){
 historicalEnvelope(reply,instance);const record=savedOperation(reply.record);
 if(reply.state!=='operation-recorded'||record.operation_id!==operation||(reply.response!==null&&(!reply.response||reply.response.instance_uuid!==instance||reply.response.operation_id!==operation||reply.response.request_id!==record.request_id||!Object.hasOwn(labels,reply.response.state))))throw Error('原操作响应的绑定不符。');
 if(record.response_recorded!==(reply.response!==null))throw Error('原操作响应仍待核对。');
 return reply;
}

// 日志背压时QMP可能不可达；仅此恢复可使用一致但逐节点不完整的窗口。
export function canRearmLog(view,node,busy){
 const log=view?.supervision?.[node]?.logs;
 return Boolean(view&&!busy&&view.freshness?.coherent===true&&overviewFresh(view,Date.now(),false)&&
  Number.isSafeInteger(view.generation)&&view.generation>0&&view.status?.generation===view.generation&&
  !view.status.operation_id&&view.status.result==='completed'&&view.execution?.identity!=='running'&&
  view.manifest?.nodes?.[node]&&log?.kind==='posix-fifo-v1'&&log.rearm_allowed===true&&
  log.source_identity==='running'&&log.receiver==='not-receiving');
}

export function preparationProgress(view){
 const p=view?.preparation_progress;if(p==null)return null;
 const unavailable={unavailable:true};
 if(p.unavailable||p.historical!==true||p.current_runtime_verified!==false||p.automatic_replay!==false||typeof p.request_matches!=='boolean')return unavailable;
 const stages=['source-check','copy','copy-check','source-recheck','before-commit','completed','cancelled'];
 if(p.schema!==1||!guestUuid(p.instance_uuid)||p.instance_uuid!==view.instance_uuid||!guestUuid(p.operation_id)||!stages.includes(p.stage)||!safeInteger(p.source_generation)||!safeInteger(p.target_generation,1)||p.target_generation!==p.source_generation+1||!safeInteger(p.bytes_processed)||!safeInteger(p.total_bytes)||p.bytes_processed>p.total_bytes||!safeInteger(p.files_completed)||!safeInteger(p.total_files,1)||p.files_completed>p.total_files)return unavailable;
 if(p.stage==='completed'&&p.files_completed!==p.total_files)return unavailable;
 if(p.node==null?(p.material!==null||p.total_bytes!==0||!['before-commit','completed','cancelled'].includes(p.stage)):(!Object.hasOwn(view.manifest?.nodes||{},p.node)||!['disk','nvram'].includes(p.material)))return unavailable;
 if(typeof p.updated_at!=='string'||!/(?:Z|[+-]\d{2}:\d{2})$/.test(p.updated_at)||!Number.isFinite(Date.parse(p.updated_at)))return unavailable;
 if(p.request_matches&&(view.status?.operation_id!==p.operation_id||view.generation!==p.source_generation))return unavailable;
 return p;
}
