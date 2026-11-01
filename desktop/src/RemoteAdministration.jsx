import React,{useRef,useState,useEffect} from 'react';
import {invoke} from '@tauri-apps/api/core';
import {adminAllowed,adminPayload,adminResult,adminMutations} from './admin-model.mjs';
export default function RemoteAdministration({connection:c,call,onMessage,pending=[]}){
 const [offers,setOffers]=useState([]),[offer,setOffer]=useState(''),[instance,setInstance]=useState('');
 const [course,setCourse]=useState(null),[audit,setAudit]=useState(null),[plan,setPlan]=useState(null),[busy,setBusy]=useState(false),[unknown,setUnknown]=useState(null);
 const alive=useRef(true),guard=useRef(false);useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
 async function send(action,values={},retry=null){
  if(guard.current)return;let payload;try{payload=retry?.payload||adminPayload(c,action,values);}catch(e){onMessage(e.message);return;}
  if(adminMutations.includes(action)&&!window.confirm(action==='course-provision'?'确认配置此课程？不准备磁盘或启动实例。':'确认追加契约终态观察？原执行结果仍为未知，不重放任何操作。'))return;
  guard.current=true;setBusy(true);const attempt=retry||{payload,id:crypto.randomUUID()};
  try{
   const reply=retry?await invoke('client_bridge',{payload:{action:'retry',attempt_id:retry.id}}):await call(c.config,payload,attempt.id);
   if(!alive.current)return;const result=adminResult(c,payload,reply);
   if(action==='course-list'){setOffers(result.offers||[]);setCourse(null);}
   if(action==='course-preview')setCourse({payload,result});
   if(action==='audit-review'){setAudit(result);setPlan(null);}
   if(action==='audit-settlement-preview')setPlan({payload,result});
   if(adminMutations.includes(action)){setUnknown(null);setCourse(null);setPlan(null);setAudit(null);onMessage('管理请求已返回。课程需另行准备和验收；审计原执行结果仍可能未知。');}
  }catch(e){if(alive.current){setCourse(null);setPlan(null);if(adminMutations.includes(action))setUnknown(attempt);onMessage(String(e.message||e));}}
  finally{guard.current=false;if(alive.current)setBusy(false);}
 }
 const selected=offers.find(x=>x.offer_id===offer);
 return <div className="remote-admin"><p>进入管理时暂停实例自动刷新。所有变更均先预览、明确确认；配置不代表课程实机可用。</p>
 {adminAllowed(c,'course-list')&&<fieldset disabled={busy||Boolean(unknown)}><legend>登记课程</legend><button onClick={()=>send('course-list')}>读取登记课程</button>
 <select aria-label="登记课程" value={offer} onChange={e=>{setOffer(e.target.value);setInstance('');setCourse(null);}}><option value="">选择课程</option>{offers.map(x=><option key={x.offer_id} value={x.offer_id}>{x.title} · {x.variant_id}</option>)}</select>
 <select aria-label="课程分配实例" value={instance} onChange={e=>{setInstance(e.target.value);setCourse(null);}}><option value="">选择实例</option>{selected?.instances?.map(x=><option key={x} value={x}>{x}</option>)}</select>
 <button disabled={!instance} onClick={()=>send('course-preview',{offer_id:offer,instance_uuid:instance})}>预览配置</button>
 {course&&<p>映射摘要：{course.result.mapping_sha256} <button onClick={()=>send('course-provision',{offer_id:course.payload.offer_id,instance_uuid:course.payload.instance_uuid,mapping_sha256:course.result.mapping_sha256})}>配置</button></p>}
 </fieldset>}
 {adminAllowed(c,'audit-review')&&<fieldset disabled={busy||Boolean(unknown)}><legend>未决审计</legend>
 <button onClick={()=>send('audit-review',{after:0,limit:50,checkpoint:audit?{seq:audit.audit_head_seq,sha256:audit.audit_head_sha256}:null})}>读取 / 刷新未决记录</button>
 {audit&&<p>未决 {audit.pending_count} 项 · 检查点 {audit.audit_head_seq} · 独立快照，不代表虚拟机当前状态。</p>}
 {audit?.pending?.map(x=><p key={x.attempt_id}>{x.attempt_id} · {x.origin} · {x.observation} <button onClick={()=>send('audit-settlement-preview',{attempt_id:x.attempt_id})}>预览终态观察</button></p>)}
 {audit?.more&&<button onClick={()=>send('audit-review',{after:audit.next_intent,limit:50,checkpoint:{seq:audit.audit_head_seq,sha256:audit.audit_head_sha256}})}>下一页</button>}
 {plan&&<p>观察摘要 {plan.result.review_sha256} · 原执行结果：未知 <button onClick={()=>send('audit-settle',{attempt_id:plan.payload.attempt_id,review_sha256:plan.result.review_sha256})}>追加此观察记录</button></p>}
 </fieldset>}
 {unknown&&<p>管理请求响应未确认。<button disabled={busy} onClick={()=>send(unknown.payload.action,{},unknown)}>使用原请求重试</button></p>}
 {pending.filter(x=>adminMutations.includes(x.payload.action)&&x.payload.target===c.target).map(x=><p key={x.id}>{x.payload.action} · {x.phase} <button disabled={busy} onClick={()=>{setUnknown({id:x.id,payload:x.payload});onMessage('已恢复原管理请求，尚未发送。');}}>恢复原管理请求</button></p>)}
 </div>;
}
