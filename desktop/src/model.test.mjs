import test from 'node:test';
import assert from 'node:assert/strict';
import {request,allowed,consumeEvents,canResumeDispatch,canRestartPreparation,canRearmObserver,configurationReady} from './model.mjs';
const freshAt=Date.now();const freshness={schema:1,complete:true,sampled_at:new Date(freshAt-1000).toISOString(),valid_until:new Date(freshAt+59000).toISOString()};
const view={freshness,instance_uuid:'i',generation:1,status:{generation:1,state_revision:3,state:'stopped',result:'completed'}};
test('重试保持幂等键与原前置条件',()=>{const a=request('start',view,{display:'headless',allow_emulation:false},'retry-key','r1');const b=request('start',view,a.parameters,'retry-key','r2');assert.deepEqual({...a,request_id:'r2'},b);assert.equal(a.expected_state_revision,3);});
test('未知和正在操作时禁止启动和重置',()=>{assert.equal(allowed('start',{...view,status:{...view.status,state:'unknown'}},false),false);assert.equal(allowed('reset',view,true),false);assert.equal(allowed('start',view,false),true);});
const eventInstance='12345678-1234-1234-1234-123456789abc';
const makeEvent=(sequence,extra={})=>({protocol:'ctflab-local',version:1,event_id:`00000000-0000-0000-0000-${String(sequence).padStart(12,'0')}`,sequence,timestamp:'2026-10-30T00:00:00+00:00',instance_uuid:eventInstance,generation:1,operation_id:'22345678-1234-1234-1234-123456789abc',state_revision:1,stage:'intent',state:'preparing',...extra});
test('事件缺口要求重读快照，不重放操作',()=>{assert.deepEqual(consumeEvents(3,[makeEvent(5)],eventInstance),{cursor:0,events:[],reload:true});});
test('事件去重和跨实例拒绝',()=>{assert.equal(consumeEvents(3,[makeEvent(3),makeEvent(4),makeEvent(4)],eventInstance).cursor,4);assert.equal(consumeEvents(3,[makeEvent(4,{instance_uuid:'other'})],eventInstance).reload,true);});
test('后台执行身份已确认时保留取消入口并禁止其他副作用',()=>{const v={...view,execution:{identity:'running'},status:{...view.status,operation_id:'active',result:'unknown',state:'recovery-required'}};assert.equal(allowed('cancel',v,false),true);assert.equal(allowed('stop',v,false),false);assert.equal(allowed('recover',v,false),false);});
test('来宾操作只在确认整课进程运行且无并发操作时开放',()=>{assert.equal(allowed('guest',view,false),false);const running={...view,status:{...view.status,state:'process-running'}};assert.equal(allowed('guest',running,false),true);assert.equal(allowed('guest',{...running,execution:{identity:'running'}},false),false);const r=request('guest',running,{node:'middle',action:'network-apply'},'idem','request');assert.deepEqual(r.parameters,{node:'middle',action:'network-apply'});});

const pending={freshness,instance_uuid:'i',generation:0,status:{operation_id:'op',result:'accepted',generation:1,state_revision:2},execution:{identity:'unknown'},dispatch:{instance_uuid:'i',operation_id:'op',generation:1,state_revision:2,status:'pending',active:true,resume_allowed:true,automatic_replay:false}};
test('新窗口可继续尚未领取的原派发，不依赖内存中的请求',()=>{assert.equal(canResumeDispatch(pending,false),true);assert.equal(canResumeDispatch(pending,true),false);assert.equal(canResumeDispatch({...pending,execution:{identity:'running'}},false),false);});
test('执行中、未知、旧实例或旧版本不显示继续派发',()=>{for(const d of [{status:'executing'},{status:'unknown'},{active:false},{resume_allowed:false},{operation_id:'other'},{instance_uuid:'other'},{state_revision:1},{state_revision:true},{generation:2},{automatic_replay:true}])assert.equal(canResumeDispatch({...pending,dispatch:{...pending.dispatch,...d}},false),false);assert.equal(canResumeDispatch(null,false),false);assert.equal(canResumeDispatch({...pending,status:{...pending.status,result:'unknown'}},false),false);});

const interrupted={...pending,status:{...pending.status,result:'unknown',state:'recovery-required'},preparation:{instance_uuid:'i',operation_id:'old',generation:1,state_revision:2,status:'executing',restart_allowed:true,automatic_replay:false}};
test('首次准备已领取但没有运行代次时允许显式重新准备',()=>{assert.equal(canRestartPreparation(interrupted,false),true);assert.equal(canRestartPreparation({...interrupted,preparation:{...interrupted.preparation,status:'failed'}},false),true);assert.equal(canRestartPreparation({...interrupted,generation:1},false),false);assert.equal(canRestartPreparation(interrupted,true),false);});
test('重新准备拒绝旧版本、跨实例、待领取和仍运行执行器',()=>{for(const changed of [{state_revision:1},{state_revision:true},{instance_uuid:'other'},{generation:0},{restart_allowed:false},{automatic_replay:true},{status:'pending'},{operation_id:''}])assert.equal(canRestartPreparation({...interrupted,preparation:{...interrupted.preparation,...changed}},false),false);assert.equal(canRestartPreparation({...interrupted,execution:{identity:'running'}},false),false);assert.equal(canRestartPreparation({...interrupted,status:{...interrupted.status,result:'accepted'}},false),false);assert.equal(canRestartPreparation(null,false),false);});

test('退出观测恢复仅在当前运行节点且没有业务操作时开放',()=>{const v={freshness,instance_uuid:'i',generation:1,status:{generation:1,result:'completed',operation_id:null},observations:{n:{state:'process-running'}},supervision:{n:{observer:'unknown'}}};assert.equal(canRearmObserver(v,'n',false),true);assert.equal(canRearmObserver(v,'n',true),false);assert.equal(canRearmObserver({...v,status:{...v.status,operation_id:'busy'}},'n',false),false);assert.equal(canRearmObserver({...v,supervision:{n:{observer:'running'}}},'n',false),false);assert.equal(canRearmObserver({...v,generation:2},'n',false),false);});

test('Mac混合架构课要求本次明确仿真确认，原生课不借用确认',()=>{const mixed={...view,runtime:{host:'darwin-arm64',emulation_required:true}};assert.equal(allowed('start',mixed,false),false);assert.equal(allowed('start',mixed,false,true),true);assert.equal(allowed('start',view,false),true);});

test('BIOS配置不被可选NVRAM字段阻断，三个核心文件仍必须提供',()=>{const files={manifest:'/m',assets:'/a',profile:'/p',nvram:''};assert.equal(configurationReady(files,false),true);assert.equal(configurationReady({...files,nvram:'/n'},false),true);assert.equal(configurationReady(files,true),false);assert.equal(configurationReady({...files,profile:''},false),false);assert.equal(configurationReady({},false),false);});

test('来宾续建绑定当前节点、原操作和核对摘要，不借用其他记录',async()=>{
 const {canInspectGuestPreparation,canResumeGuestPreparation,guestPreparationParameters}=await import('./model.mjs');const target='11111111-1111-4111-8111-111111111111';
 const snapshot={state:'preparation-observed',operation_id:target,can_resume:true,automatic_replay:false,resume_sha256:'a'.repeat(64)};
 const v={...view,status:{...view.status,state:'process-running'},observations:{middle:{state:'process-running'}},guest_agents:{middle:{containers:true,last_action:'preparation-inspect',last_result:snapshot}}};
 assert.equal(canInspectGuestPreparation(v,'middle',target,false),true);assert.equal(canResumeGuestPreparation(v,'middle',target,false),true);
 assert.deepEqual(guestPreparationParameters(v,'middle',target,true),{node:'middle',action:'preparation-resume',target_operation_id:target,expected_sha256:'a'.repeat(64)});
 for(const change of [{operation_id:'22222222-2222-4222-8222-222222222222'},{state:'unknown'},{can_resume:false},{automatic_replay:true},{resume_sha256:'bad'}])assert.equal(canResumeGuestPreparation({...v,guest_agents:{middle:{...v.guest_agents.middle,last_result:{...snapshot,...change}}}},'middle',target,false),false);
 assert.equal(canResumeGuestPreparation(v,'middle',target,true),false);assert.equal(canResumeGuestPreparation(v,'missing',target,false),false);
 assert.equal(canResumeGuestPreparation({...v,status:{...v.status,state:'recovery-required'}},'middle',target,false),false);
 assert.throws(()=>guestPreparationParameters(v,'middle','bad',true));
});

test('本地状态缺失/过期/未来/不完整时禁止新副作用，保留恢复与取消',async()=>{
 const {overviewFresh}=await import('./model.mjs');const now=Date.now();
 assert.equal(overviewFresh(view,now),true);
 for(const value of [undefined,{...freshness,coherent:false},{...freshness,complete:false},{...freshness,sampled_at:new Date(now+1000).toISOString()},
  {...freshness,valid_until:new Date(now-1).toISOString()},{...freshness,valid_until:new Date(now+120000).toISOString()},
  {...freshness,sampled_at:'2026-10-28T12:00:00'}]){
  const stale={...view,freshness:value};assert.equal(overviewFresh(stale,now),false);assert.equal(allowed('start',stale,false),false);
  assert.equal(allowed('recover',stale,false),true);
 }
 const stale={...view,freshness:undefined,status:{...view.status,result:'unknown',operation_id:'original'}};
 assert.equal(allowed('cancel',stale,false),true);
});
test('只读刷新即使同一路径重开也拒绝旧回复，旧finally不能释放新门',async()=>{
 const {createRefreshScope}=await import('./model.mjs');const scope=createRefreshScope();scope.attach('/one');
 const a=scope.begin('/one');assert.ok(a);assert.equal(scope.begin('/one'),null);
 scope.attach('/one');const b=scope.begin('/one');assert.equal(scope.current(a),false);assert.equal(scope.current(b),true);
 scope.finish(a);assert.equal(scope.begin('/one'),null);scope.finish(b);assert.ok(scope.begin('/one'));
 scope.attach('/two');assert.equal(scope.begin('/one'),null);
});
test('请求超时只拒绝当前等待，不重发，迟到回复不改变已结束结果',async()=>{
 const {boundedCall}=await import('./model.mjs');let fire,resolve,calls=0,cleared=0;
 const task=boundedCall(()=>{calls++;return new Promise(done=>resolve=done);},{timeoutMs:1,setTimer:f=>{fire=f;return 9;},clearTimer:id=>{assert.equal(id,9);cleared++;}});
 await Promise.resolve();fire();await assert.rejects(task,e=>e.code==='reply-timeout');resolve('late');await Promise.resolve();
 assert.equal(calls,1);assert.equal(cleared,1);
});
test('及时回复清理等待定时器，异常不自动重试',async()=>{
 const {boundedCall}=await import('./model.mjs');let clears=0,calls=0;
 assert.equal(await boundedCall(()=>{calls++;return 42;},{setTimer:()=>1,clearTimer:()=>clears++}),42);
 await assert.rejects(boundedCall(()=>{calls++;throw Error('once');},{setTimer:()=>1,clearTimer:()=>clears++}),/once/);
 assert.equal(calls,2);assert.equal(clears,2);
});

test('日志背压可在QMP采样不完整时恢复，但不开放生命周期或来宾动作',async()=>{
 const {canRearmLog}=await import('./model.mjs');
 const v={...view,freshness:{...freshness,coherent:true,complete:false},manifest:{nodes:{server:{}}},
  observations:{server:{state:'unknown',identity:'unknown'}},supervision:{server:{logs:{kind:'posix-fifo-v1',
  rearm_allowed:true,source_identity:'running',receiver:'not-receiving'}}}};
 assert.equal(canRearmLog(v,'server',false),true);assert.equal(allowed('start',v,false),false);assert.equal(allowed('guest',v,false),false);
 for(const changed of [{freshness:{...v.freshness,coherent:false}},{freshness:{...v.freshness,valid_until:new Date(Date.now()-1).toISOString()}},
  {status:{...v.status,operation_id:'active'}},{generation:2},{execution:{identity:'running'}}])assert.equal(canRearmLog({...v,...changed},'server',false),false);
 assert.equal(canRearmLog(v,'outside',false),false);assert.equal(canRearmLog(v,'server',true),false);
 for(const changed of [{kind:'legacy-anonymous'},{rearm_allowed:false},{source_identity:'unknown'},{receiver:'lock-held'}])
  assert.equal(canRearmLog({...v,supervision:{server:{logs:{...v.supervision.server.logs,...changed}}}},'server',false),false);
});

// 保存记录只作为历史证据；不会变成当前运行状态或新请求。
import {operationHistory,operationResult} from './model.mjs';
const historyInstance='12345678-1234-1234-1234-123456789abc';
const historyOperation='22345678-1234-1234-1234-123456789abc';
const historyRequest='32345678-1234-1234-1234-123456789abc';
const savedRecord={operation_id:historyOperation,request_id:historyRequest,operation:'prepare',expected_generation:null,status:'pending',response_recorded:false,cancel_requested:false};
const savedEnvelope={instance_uuid:historyInstance,historical:true,current_runtime_verified:false,automatic_replay:false};
const savedList={...savedEnvelope,state:'operation-history',operations:[savedRecord],truncated:false,next_before:null};
const savedResult={...savedEnvelope,state:'operation-recorded',record:savedRecord,response:null};
test('重开账本的未领取操作保持无结果且不生成请求',()=>{
 assert.deepEqual(operationHistory(savedList,historyInstance),[savedRecord]);
 assert.equal(operationResult(savedResult,historyInstance,historyOperation).response,null);
 assert.equal(Object.hasOwn(savedRecord,'parameters'),false);
});
test('历史查询拒绝跨实例、当前状态冒充与自动重发标志',()=>{
 for(const change of [{instance_uuid:'other'},{historical:false},{current_runtime_verified:true},{automatic_replay:true}]){
  assert.throws(()=>operationHistory({...savedList,...change},historyInstance));
  assert.throws(()=>operationResult({...savedResult,...change},historyInstance,historyOperation));
 }
});
test('原操作描述拒绝坏代次、未知动作、缺结果和重复记录',()=>{
 for(const change of [{expected_generation:1},{operation:'shell'},{status:'completed'},{operation_id:'other'},{cancel_requested:1},{operation:'start',expected_generation:true}])assert.throws(()=>operationHistory({...savedList,operations:[{...savedRecord,...change}]},historyInstance));
 assert.throws(()=>operationHistory({...savedList,operations:[savedRecord,savedRecord]},historyInstance));
 assert.throws(()=>operationHistory({...savedList,operations:Array(51).fill(savedRecord)},historyInstance));
});
test('历史分页只接受本页末尾原操作标识',()=>{
 assert.equal(operationHistory({...savedList,truncated:true,next_before:historyOperation},historyInstance).length,1);
 for(const change of [{truncated:true,next_before:historyRequest},{truncated:false,next_before:historyOperation},{truncated:true,operations:[],next_before:historyOperation}])assert.throws(()=>operationHistory({...savedList,...change},historyInstance));
});
test('原响应绑定请求、实例与操作且不接受缺失响应',()=>{
 const response={instance_uuid:historyInstance,operation_id:historyOperation,request_id:historyRequest,state:'prepared'};
 const value={...savedResult,record:{...savedRecord,status:'completed',response_recorded:true},response};
 assert.equal(operationResult(value,historyInstance,historyOperation).response.state,'prepared');
 for(const change of [{instance_uuid:'other'},{operation_id:historyRequest},{request_id:historyOperation},{state:'fake-current'}])assert.throws(()=>operationResult({...value,response:{...response,...change}},historyInstance,historyOperation));
 assert.throws(()=>operationResult({...value,response:null},historyInstance,historyOperation));
 assert.throws(()=>operationResult({...savedResult,response},historyInstance,historyOperation));
 assert.throws(()=>operationResult(value,historyInstance,historyRequest));
});

test('桥接真实数组消费全部事件而不把未知包装默认为空',()=>{
 const events=[makeEvent(1),makeEvent(2),makeEvent(3)];const value=consumeEvents(0,events,eventInstance);
 assert.equal(value.cursor,3);assert.deepEqual(value.events,events);assert.equal(value.reload,false);
 for(const wire of [null,{}, {events}, {error:{code:'cursor-expired'}}, 'not-an-array'])assert.equal(consumeEvents(0,wire,eventInstance).reload,true);
});
test('事件严格校验协议、字段、标识、代次、状态与时间',()=>{
 const changes=[{version:2},{version:true},{protocol:'other'},{event_id:'bad'},{operation_id:'bad'},{generation:0},{generation:true},{state_revision:-1},{state_revision:true},{sequence:0},{sequence:1.5},{state:'ready'},{stage:'fake'},{timestamp:null},{timestamp:'x'.repeat(65)},{extra:'private'}];
 for(const change of changes)assert.equal(consumeEvents(0,[makeEvent(1,change)],eventInstance).reload,true,JSON.stringify(change));
 const missing=makeEvent(1);delete missing.protocol;assert.equal(consumeEvents(0,[missing],eventInstance).reload,true);
});
test('同序号内容冲突与跨序号复用事件UUID触发重读',()=>{
 assert.equal(consumeEvents(0,[makeEvent(1),makeEvent(1,{state:'failed'})],eventInstance).reload,true);
 assert.equal(consumeEvents(0,[makeEvent(1),makeEvent(2,{event_id:makeEvent(1).event_id})],eventInstance).reload,true);
 const reordered=Object.fromEntries(Object.entries(makeEvent(1)).reverse());assert.equal(consumeEvents(0,[makeEvent(1),reordered],eventInstance).cursor,1);
});
test('旧事件也核验结构并且不改变输入、无效游标和超量拒绝',()=>{
 const first=makeEvent(1),events=[first,makeEvent(2)];const before=JSON.stringify(events);const result=consumeEvents(1,events,eventInstance);
 assert.equal(result.cursor,2);result.events[0].state='failed';assert.equal(JSON.stringify(events),before);
 assert.equal(consumeEvents(1,[makeEvent(1,{version:2})],eventInstance).reload,true);
 for(const cursor of [-1,true,1.5,Number.MAX_SAFE_INTEGER+1])assert.equal(consumeEvents(cursor,[],eventInstance).reload,true);
 assert.equal(consumeEvents(0,Array(1001).fill(first),eventInstance).reload,true);
 assert.equal(consumeEvents(0,[],eventInstance).reload,false);
});

import {refreshEvents} from './model.mjs';
test('事件裁剪后按本次绑定快照重新定位并能读取后续事件',()=>{
 const snapshot={instance_uuid:eventInstance,status:{protocol:'ctflab-local',version:1,instance_uuid:eventInstance,cursor:3}};
 const expired=refreshEvents(0,{error:{code:'cursor-expired'}},snapshot);
 assert.deepEqual(expired,{cursor:3,events:[],reload:true});
 const next=refreshEvents(expired.cursor,[makeEvent(4)],snapshot);assert.equal(next.cursor,4);assert.equal(next.events.length,1);assert.equal(next.reload,false);
});
test('未绑定、坏版本或非法快照游标不能重定位事件流',()=>{
 const status={protocol:'ctflab-local',version:1,instance_uuid:eventInstance,cursor:3};
 for(const change of [{instance_uuid:historyOperation},{version:2},{cursor:true},{cursor:-1},{cursor:Number.MAX_SAFE_INTEGER+1},{protocol:'other'}])assert.equal(refreshEvents(0,{}, {instance_uuid:eventInstance,status:{...status,...change}}).cursor,0);
 assert.equal(refreshEvents(0,{},null).cursor,0);
});

import {preparationProgress} from './model.mjs';
const prepPoint={schema:1,instance_uuid:historyInstance,operation_id:historyOperation,source_generation:0,target_generation:1,
 node:'server',material:'disk',stage:'source-check',bytes_processed:1048576,total_bytes:8388608,files_completed:0,total_files:3,
 updated_at:'2026-10-30T00:00:00+00:00',historical:true,current_runtime_verified:false,automatic_replay:false,request_matches:true};
const prepView={instance_uuid:historyInstance,generation:0,status:{operation_id:historyOperation},manifest:{nodes:{server:{}}},preparation_progress:prepPoint};
test('准备进度明确为历史检查点且绑定当前请求，不生成控制操作',()=>{
 assert.equal(preparationProgress(prepView),prepPoint);assert.equal(preparationProgress({...prepView,preparation_progress:null}),null);
 const old={...prepPoint,request_matches:false};assert.equal(preparationProgress({...prepView,generation:1,status:{operation_id:null},preparation_progress:old}),old);
});
test('准备进度拒绝跨实例、坏计数、非白名单阶段与假活性',()=>{
 for(const change of [{instance_uuid:historyRequest},{operation_id:'bad'},{target_generation:2},{source_generation:true},{bytes_processed:9000000},{total_bytes:true},{files_completed:4},{stage:'running'},{node:'/private'},{material:'path'},{historical:false},{current_runtime_verified:true},{automatic_replay:true},{updated_at:'bad'}])assert.equal(preparationProgress({...prepView,preparation_progress:{...prepPoint,...change}}).unavailable,true,JSON.stringify(change));
 assert.equal(preparationProgress({...prepView,generation:1}).unavailable,true);assert.equal(preparationProgress({...prepView,status:{operation_id:historyRequest}}).unavailable,true);
 assert.equal(preparationProgress({...prepView,preparation_progress:{unavailable:true}}).unavailable,true);
});
test('准备已提交进度必须有完整材料计数，取消不能冒充提交',()=>{
 const complete={...prepPoint,stage:'completed',files_completed:3,node:null,material:null,total_bytes:0,bytes_processed:0,request_matches:false};
 assert.equal(preparationProgress({...prepView,preparation_progress:complete}),complete);
 assert.equal(preparationProgress({...prepView,preparation_progress:{...complete,files_completed:2}}).unavailable,true);
 const cancelled={...prepPoint,stage:'cancelled'};assert.equal(preparationProgress({...prepView,preparation_progress:cancelled}),cancelled);
});
