import React,{useEffect,useRef,useState} from 'react';
import {invoke} from '@tauri-apps/api/core';
import {labels,consumeEvents} from './model.mjs';
import {uuid,remoteOperations,remoteAllowed,remotePayload,currentReply,acceptOverview,leaseAllowed,leasePayload,leaseRetry,displayAllowed} from './remote-model.mjs';
import RemoteTargets from './RemoteTargets.jsx';
import RemoteAssets from './RemoteAssets.jsx';
import RemoteEvidence from './RemoteEvidence.jsx';
import RemoteAdministration from './RemoteAdministration.jsx';
const names={prepare:'准备实验',start:'启动',stop:'正常停止',reset:'整课重置',recover:'恢复核验',cancel:'取消后续操作'};
export default function RemoteWorkspace(){
 const [config,setConfig]=useState(''),[connection,setConnection]=useState(null),[selected,setSelected]=useState(''),[opened,setOpened]=useState('');
 const [view,setView]=useState(null),[events,setEvents]=useState([]),[lease,setLease]=useState(''),[leases,setLeases]=useState(null);
 const [busy,setBusy]=useState(false),[message,setMessage]=useState('选择已准备的远程连接配置，明确连接后读取分配给你的实例。');
 const [ttl,setTtl]=useState('600'),[stopConsent,setStopConsent]=useState(false),[leaseAttempt,setLeaseAttempt]=useState(null);
 const [pending,setPending]=useState([]),[operationAttempt,setOperationAttempt]=useState(null);
 const [adminOpen,setAdminOpen]=useState(false);
 const [connecting,setConnecting]=useState(null);const connectionFlight=useRef(null);
 const epoch=useRef(0),cursor=useRef(0),flight=useRef(null),actionGuard=useRef(false);
 useEffect(()=>()=>{epoch.current++;flight.current=null;connectionFlight.current=null;},[]);
 const call=(path,payload,attemptId=null)=>{
  if(path?.savedId){const value={action:'request',id:path.savedId,payload};if(payload.action==='submit'&&payload.request.operation!=='status'||['lease-acquire','lease-renew','lease-release','course-provision','audit-settle'].includes(payload.action))value.attempt_id=attemptId||crypto.randomUUID();return invoke('client_bridge',{payload:value});}
  return invoke('remote_bridge',{config:path,payload});
 };
 async function chooseConfig(){try{const selected=await invoke('choose_remote_file',{kind:'config'});if(selected)changeConfig(selected);}catch(e){setMessage(String(e.message||e));}}
 function clear(){setAdminOpen(false);epoch.current++;cursor.current=0;flight.current=null;connectionFlight.current=null;setConnecting(null);setConnection(null);setSelected('');setOpened('');setView(null);setEvents([]);setLease('');setLeases(null);setStopConsent(false);setLeaseAttempt(null);setPending([]);setOperationAttempt(null);}
 function changeConfig(value){clear();setConfig(value);}
 async function connect(reference=config){
  if(actionGuard.current||!reference)return;actionGuard.current=true;clear();const ticket=epoch.current;setBusy(true);
  const attempt={id:crypto.randomUUID(),target:reference?.savedId,config:typeof reference==='string'?reference:null};connectionFlight.current=attempt;setConnecting(attempt);
  try{const reply=attempt.target?await invoke('client_bridge',{payload:{action:'connect',id:attempt.target,connection_id:attempt.id}}):await invoke('client_bridge',{payload:{action:'preview-connect',config:attempt.config,connection_id:attempt.id}});if(ticket!==epoch.current)return;
   if(reply.connection_cancelled){setMessage('本次连接已取消；没有发送远程实验停止请求。');return;}
   if(reply.error)throw Error(reply.error.message);setConnection({...reply.result,target:reply.target,config:reference,persisted:Boolean(reference?.savedId)});setMessage('已读取分配实例。选择后打开，只自动刷新状态和事件。');
   if(reference?.savedId){const records=await invoke('client_bridge',{payload:{action:'pending',id:reference.savedId}});if(ticket===epoch.current&&!records.error)setPending(records.attempts);}
  }catch(e){if(ticket===epoch.current)setMessage(String(e.message||e));}finally{if(connectionFlight.current===attempt){connectionFlight.current=null;setConnecting(null);actionGuard.current=false;if(ticket===epoch.current)setBusy(false);}}
 }
 async function cancelConnection(){const attempt=connectionFlight.current;if(!attempt)return;try{
  const reply=await invoke('client_bridge',{payload:attempt.target?{action:'cancel-connect',id:attempt.target,connection_id:attempt.id}:{action:'cancel-preview-connect',config:attempt.config,connection_id:attempt.id}});
  if(connectionFlight.current!==attempt)return;
  if(reply.error)throw Error(reply.error.message);
  if(reply.connection_phase!=='cancelled'){setMessage('连接已返回；取消未关闭当前已建立的管理页面。');return;}
  clear();actionGuard.current=false;setBusy(false);setMessage('已取消本次连接并丢弃迟到回复；只结束自有SSH传输，远程实验继续运行。');
 }catch(e){if(connectionFlight.current===attempt)setMessage('取消尚未确认；连接仍在等待，可再次请求取消。');}}
 async function openDisplay(node){
  if(actionGuard.current||!displayAllowed(connection,view,node,lease,leases,busy))return;
  const ticket=epoch.current;actionGuard.current=true;setBusy(true);
  try{const reply=await invoke('client_bridge',{payload:{action:'display',id:connection.config.savedId,instance_uuid:opened,node,lease_id:lease}});
   if(ticket!==epoch.current)return;if(reply.error)throw Error(reply.error.message);
   setMessage('已请求独立显示窗口；窗口内会重新核对权限、租约与节点身份。关闭显示不停止实验。');
  }catch(e){if(ticket===epoch.current)setMessage(String(e.message||e));}
  finally{actionGuard.current=false;if(ticket===epoch.current)setBusy(false);}
 }
 async function refresh(context,instance,ticket){
  if(!context||!instance||ticket!==epoch.current||flight.current?.ticket===ticket)return;
  const token={ticket};flight.current=token;
  const parameters={target:context.target,instance_uuid:instance};
  try{const reply=await call(context.config,{action:'overview',...parameters});
   if(!currentReply(ticket,epoch.current,context.target,reply)){if(ticket===epoch.current)throw Error(reply.error?.message||'连接目标已变化，请重新连接。');return;}
   if(reply.result.instance_uuid!==instance)throw Error('实例响应不匹配，请重新连接。');const incoming=acceptOverview(null,reply.result);setView(previous=>acceptOverview(previous,incoming));
   const eventReply=await call(context.config,{action:'events',after:cursor.current,...parameters});
   if(!currentReply(ticket,epoch.current,context.target,eventReply)){if(ticket===epoch.current)throw Error(eventReply.error?.message||'事件读取未完成。');return;}
   const page=consumeEvents(cursor.current,eventReply.result,instance);cursor.current=page.cursor;
   if(page.reload)setEvents([]);else setEvents(old=>[...old,...page.events].slice(-80));
   if(context.resource_leases){const result=await call(context.config,{action:'lease-status',...parameters});
    if(currentReply(ticket,epoch.current,context.target,result))setLeases(result.result);
    else if(ticket===epoch.current)setLeases(null);
   }
   if(context.config?.savedId){const records=await invoke('client_bridge',{payload:{action:'pending',id:context.config.savedId}});if(ticket===epoch.current&&!records.error)setPending(records.attempts);}
  }catch(e){if(ticket===epoch.current){setView(null);setLeases(null);setMessage(String(e.message||e));}}
  finally{if(flight.current===token)flight.current=null;}
 }
 function open(){if(!connection||!uuid(selected)||busy)return;epoch.current++;cursor.current=0;flight.current=null;setView(null);setEvents([]);setLease('');setLeases(null);setLeaseAttempt(null);setOperationAttempt(null);setStopConsent(false);setOpened(selected);}
 useEffect(()=>{if(!connection||!opened||adminOpen)return;const ticket=epoch.current;refresh(connection,opened,ticket);const timer=setInterval(()=>refresh(connection,opened,ticket),4000);return()=>clearInterval(timer);},[connection,opened,adminOpen]);
 // 同一实例再次打开时，直接刷新；切换实例则使旧响应全部失效。
 function openSelected(){if(opened===selected&&opened){refresh(connection,opened,epoch.current);return;}open();}
 async function operate(operation){
  if(actionGuard.current||operationAttempt?.phase==='unknown'&&operation!=='cancel'||!remoteAllowed(operation,view,busy,connection,lease))return;
  if(['stop','reset'].includes(operation)&&!window.confirm(operation==='stop'?'确认向当前远程实验请求正常停止？':'确认创建新代次？原始镜像和旧进度会保留。'))return;
  const ticket=epoch.current,context=connection,instance=opened;
  actionGuard.current=true;setBusy(true);
  let attempt;
  try{const payload=remotePayload(operation,view,instance,context,lease,crypto.randomUUID(),crypto.randomUUID());attempt={payload,clientAttemptId:crypto.randomUUID(),phase:'sending'};setOperationAttempt(attempt);
   const reply=await call(context.config,payload,attempt.clientAttemptId);if(ticket!==epoch.current)return;
   if(!currentReply(ticket,epoch.current,context.target,reply))throw Error(reply.error?.message||'响应未知');
   setOperationAttempt({...attempt,phase:'returned'});
   setView(previous=>previous?acceptOverview(previous,{...previous,status:reply.result}):previous);
   setMessage(reply.result.error?.message||'操作已记录；接收不代表执行完成。');await refresh(context,instance,ticket);
  }catch(e){if(ticket===epoch.current){if(attempt)setOperationAttempt({...attempt,phase:'unknown'});setMessage('响应未取得或操作未完成。先刷新状态；不会自动重发操作。');}}
  finally{actionGuard.current=false;if(ticket===epoch.current)setBusy(false);}
 }
 async function changeLease(action,retry=false){
  if(actionGuard.current||!connection||!opened)return;
  let payload;
  try{payload=retry?leaseRetry(leaseAttempt?.payload,connection,opened):leasePayload(action,connection,opened,leases,lease,Number(ttl),stopConsent,crypto.randomUUID());}
  catch(e){setMessage(e.message);return;}
  const confirmation=retry?'使用原租约与续期标识再次请求？不会生成第二个标识；服务器仍会重新检查权限与当前绑定。':action==='lease-release'?'确认申请释放CPU和内存预留？服务器只在证实全部停止后释放，磁盘引用继续保留。':payload.expiry_action==='request-stop'?'确认申请此停止策略租约？显式到期处理时可请求正常停止，本页不会安装或运行调度。':'确认按当前期限预留或续期资源？不会启动节点。';
  if(!window.confirm(confirmation))return;
  const ticket=epoch.current,context=connection,instance=opened;
  const clientAttemptId=retry?leaseAttempt.clientAttemptId:crypto.randomUUID();
  actionGuard.current=true;setBusy(true);setLeaseAttempt({payload,phase:'sending',clientAttemptId});
  try{const reply=retry&&context.config?.savedId?await invoke('client_bridge',{payload:{action:'retry',attempt_id:clientAttemptId}}):await call(context.config,payload,clientAttemptId);if(ticket!==epoch.current)return;
   if(!currentReply(ticket,epoch.current,context.target,reply))throw Error(reply.error?.message||'响应未知');
   setLeaseAttempt({payload,phase:'returned',clientAttemptId});
   if(payload.action==='lease-acquire'&&reply.result.state==='active'&&reply.result.time_state==='active')setLease(reply.result.lease_id);
   if(payload.action==='lease-release')setLease('');
   setMessage('租约请求已返回；以服务器当前状态为准，磁盘引用不会删除。');
   await refresh(context,instance,ticket);
  }catch(e){if(ticket===epoch.current){setLeaseAttempt({payload,phase:'unknown',clientAttemptId});setMessage('租约响应未确认。先刷新状态；可保存本次请求，或明确点击使用原标识重试，不会自动重发。');}}
  finally{actionGuard.current=false;if(ticket===epoch.current)setBusy(false);}
 }
 function saveLeaseAttempt(){if(!leaseAttempt)return;const url=URL.createObjectURL(new Blob([JSON.stringify(leaseAttempt.payload,null,2)],{type:'application/json'}));const anchor=document.createElement('a');anchor.href=url;anchor.download='ctflab-lease-request.json';anchor.click();URL.revokeObjectURL(url);}
 function restoreAttempt(item){if(!connection||item.payload.target!==connection.target||item.payload.instance_uuid!==opened){setMessage('请先打开该原请求对应的实例；不会自动连接或发送。');return;}const restored={payload:item.payload,clientAttemptId:item.id,phase:'unknown'};if(item.payload.action.startsWith('lease-'))setLeaseAttempt(restored);else setOperationAttempt(restored);setMessage('已恢复本地跟踪；尚未发送原请求。');}
 async function retryOperation(){if(!operationAttempt||actionGuard.current||!connection)return;const item=operationAttempt;if(item.payload.target!==connection.target||item.payload.instance_uuid!==opened)return;if(!window.confirm('使用原请求标识重试？不会生成新幂等键，服务器仍检查权限。'))return;const ticket=epoch.current,context=connection,instance=opened;actionGuard.current=true;setBusy(true);try{const reply=context.config?.savedId?await invoke('client_bridge',{payload:{action:'retry',attempt_id:item.clientAttemptId}}):await call(context.config,item.payload);if(!currentReply(ticket,epoch.current,context.target,reply))throw Error();setOperationAttempt({...item,phase:'returned'});await refresh(context,instance,ticket);}catch(e){if(ticket===epoch.current)setMessage('原请求结果仍未确认；没有自动生成新操作。');}finally{actionGuard.current=false;if(ticket===epoch.current)setBusy(false);}}
 const nodes=view?.topology?.nodes||[];
 async function toggleAdmin(){if(busy)return;epoch.current++;flight.current=null;setAdminOpen(!adminOpen);const ticket=epoch.current;if(!adminOpen&&connection?.config?.savedId){try{const records=await invoke('client_bridge',{payload:{action:'pending',id:connection.config.savedId}});if(ticket===epoch.current&&!records.error)setPending(records.attempts);}catch(e){if(ticket===epoch.current)setMessage('本机管理请求记录暂未读到，可重新打开管理页读取。');}}}
 return <section className="remote-workspace"><h2>远程实验</h2><p>连接Linux受管运行器。连接配置包含固定服务器标识、主机密钥与本机身份文件位置；请使用管理员提供的配置。</p>
 <label>连接配置文件<input aria-label="远程连接配置" value={config} disabled={busy} onChange={e=>changeConfig(e.target.value)} placeholder="本机配置 JSON 的绝对路径"/></label>
 <button disabled={busy} onClick={chooseConfig}>选择连接配置文件</button>
 <div className="actions"><button disabled={busy||!config} onClick={()=>connect()}>连接并读取分配实例</button><button disabled={busy||!connection} onClick={()=>{clear();setMessage('已停止本地刷新；远程实验继续运行。');}}>断开管理</button></div>
 {connecting&&<button onClick={cancelConnection}>取消本次连接</button>}
 <RemoteTargets configPath={config} busy={busy} onConnect={item=>connect({savedId:item.id})} onMessage={setMessage}/>
 {connection&&!adminOpen&&<><p>服务器 {connection.server_uuid} · {({student:'学生',teacher:'教师',administrator:'管理员'})[connection.role]}</p><label>分配实例<select aria-label="远程实例" value={selected} disabled={busy} onChange={e=>{epoch.current++;setOpened('');setView(null);setEvents([]);setLease('');setLeases(null);setSelected(e.target.value);}}><option value="">选择实例</option>{connection.instances.map(id=><option key={id} value={id}>{id}</option>)}</select></label><button disabled={busy||!uuid(selected)} onClick={openSelected}>打开 / 刷新实例</button></>}
 {connection?.persisted&&(connection.course_management||connection.audit_management)&&<><button disabled={busy} onClick={toggleAdmin}>{adminOpen?'返回实例管理':'课程与审计管理'}</button>{adminOpen&&<RemoteAdministration key={connection.target} connection={connection} call={call} onMessage={setMessage} pending={pending}/>}</>}
 <div className="notice" role="status">{message}</div>
 {connection&&!connection.persisted&&<p>此连接仅作只读预览。请先保存目标，再从保存列表明确连接，以持久记录变更请求。</p>}
 {!adminOpen&&connection?.config?.savedId&&<div className="remote-recovery"><h3>本机未确认请求</h3><p>保存目标的变更请求在传输前落盘。重开只显示记录，恢复跟踪和重试均需明确点击。</p>{pending.map(item=><p key={item.id}>{item.payload.instance_uuid} · {item.payload.action} · {item.phase} <button disabled={busy} onClick={()=>restoreAttempt(item)}>恢复原请求跟踪</button></p>)}</div>}
 {operationAttempt?.phase==='unknown'&&<p>原操作结果未确认。<button disabled={busy} onClick={retryOperation}>使用原标识重试操作</button></p>}
 {!adminOpen&&opened&&connection?.resource_leases&&<div className="remote-lease"><h3>资源租约</h3><label>使用的租约<input aria-label="资源租约 UUID" disabled={busy} value={lease} onChange={e=>setLease(e.target.value.trim())} placeholder="申请后使用，或填写已有租约 UUID"/></label>
 <label>申请或续期秒数（最多 {leases?.max_ttl_seconds??'以服务器为准'} 秒）<input aria-label="租约期限秒数" type="number" min="10" max={leases?.max_ttl_seconds??86400} disabled={busy} value={ttl} onChange={e=>setTtl(e.target.value)}/></label>
 <p>到期策略：{leases?.expiry_action==='notify'?'仅通知':leases?.expiry_action==='request-stop'?'显式到期处理可请求正常停止':'尚未读取'}。本页不更改策略、不安装或运行到期调度。</p>
 {leases?.expiry_action==='request-stop'&&<label><input aria-label="确认停止策略" type="checkbox" disabled={busy} checked={stopConsent} onChange={e=>setStopConsent(e.target.checked)}/> 我同意此租约在显式到期处理时请求正常停止。</label>}
 <div className="actions">{[['lease-acquire','申请租约'],['lease-renew','续期所选租约'],['lease-release','释放所选预留']].map(([action,label])=><button key={action} disabled={leaseAttempt?.phase==='unknown'||!leaseAllowed(action,connection,leases,lease,Number(ttl),stopConsent,busy)} onClick={()=>changeLease(action)}>{label}</button>)}</div>
 {leases?.owner_actions===false&&<p>当前主体可按已有权限查看；只有此实例所有者能管理租约。</p>}
 {leases?.leases?.slice(0,100).map(item=><p key={item.lease_id}><button disabled={busy} onClick={()=>setLease(item.lease_id)}>选择</button> {item.lease_id} · {item.state} · 截止 {item.expires_at}</p>)}
 {leaseAttempt&&<div><p>本次标识：{leaseAttempt.payload.renewal_id||leaseAttempt.payload.lease_id} · {leaseAttempt.phase==='unknown'?'结果未确认':leaseAttempt.phase==='sending'?'等待响应':'已返回'}</p><button onClick={saveLeaseAttempt}>保存本次租约请求</button>{leaseAttempt.phase==='unknown'&&<button disabled={busy} onClick={()=>changeLease(leaseAttempt.payload.action,true)}>使用原标识重试</button>}<p>切换目标或关闭窗口不会自动重发；需要保留未知请求时，请先保存。保存内容不含连接配置或凭据。</p></div>}
 </div>}
 {!adminOpen&&view&&<><h3>{opened.slice(0,8)} · {labels[view.status.state]||'尚未取得状态'}</h3><div className="actions">{remoteOperations.map(op=><button key={op} disabled={operationAttempt?.phase==='unknown'&&op!=='cancel'||!remoteAllowed(op,view,busy,connection,lease)} onClick={()=>operate(op)}>{names[op]}</button>)}</div><div className="nodes">{nodes.map(node=><article key={node.id}><h3>{node.id}</h3><p>{labels[view.observations?.[node.id]?.state]||'未观测'}</p><button disabled={!displayAllowed(connection,view,node.id,lease,leases,busy)} onClick={()=>openDisplay(node.id)}>打开认证显示</button></article>)}</div><h3>最近事件</h3>{events.map(event=><p key={event.event_id}>{event.sequence} · {labels[event.state]||event.state}</p>)}</>}
 {!adminOpen&&connection&&opened&&<RemoteEvidence key={connection.target+'/'+opened} connection={connection} instance={opened} onMessage={setMessage}/>}
 {!adminOpen&&connection&&<RemoteAssets key={connection.target+'/'+(connection.config?.savedId||'legacy')} connection={connection} onMessage={setMessage}/>}
 <p>认证显示需服务器明确启用和有效租约，无剪贴板或文件传输。资产上传仅进入许可缓存；课程映射由管理员执行，断开管理不停止实验。</p></section>;
}
