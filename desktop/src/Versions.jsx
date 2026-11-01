import React,{useRef,useState} from 'react';
import VersionSetup from './VersionSetup.jsx';
import {invoke} from '@tauri-apps/api/core';
import {canManageVersions,sameVersionTarget,versionChangePayload,onlineDownloadPayload} from './version-model.mjs';
export default function Versions(){
 const [config,setConfig]=useState(''),[status,setStatus]=useState(null),[busy,setBusy]=useState(false),[message,setMessage]=useState('选择安装程序或管理员准备的版本库配置，再读取当前版本。');
 const [source,setSource]=useState(''),[manifest,setManifest]=useState(''),[workspace,setWorkspace]=useState(''),[version,setVersion]=useState(''),[preview,setPreview]=useState(null),[launchPlan,setLaunchPlan]=useState(null),[attempt,setAttempt]=useState(null);
 const epoch=useRef(0),flight=useRef(false);
 const [onlineSource,setOnlineSource]=useState(''),[onlineMaximum,setOnlineMaximum]=useState('4096'),[onlinePlan,setOnlinePlan]=useState(null),[onlineAttempt,setOnlineAttempt]=useState(null);
 const [onlineDownloading,setOnlineDownloading]=useState(false);const cancelFlight=useRef(false);
 function change(value){epoch.current++;setConfig(value);setStatus(null);setPreview(null);setLaunchPlan(null);setAttempt(null);setVersion('');setOnlinePlan(null);setOnlineAttempt(null);}
 async function choose(kind,setter){try{const path=await invoke('choose_remote_file',{kind});if(path)setter(path);}catch(e){setMessage(String(e.message||e));}}
 const call=(payload)=>invoke('version_bridge',{config,payload});
 async function load(){if(flight.current||!config)return;flight.current=true;setBusy(true);const ticket=epoch.current;
  try{const reply=await call({action:'status'});if(ticket!==epoch.current)return;if(reply.error)throw Error(reply.error.message);if(!reply.target)throw Error('版本库状态未确认。');if(status?.target&&status.target!==reply.target){setAttempt(null);setOnlineAttempt(null);}setStatus(reply);setPreview(null);setLaunchPlan(null);setOnlinePlan(null);setMessage('已读取版本库。应用和已登记实验必须通过各自门禁，系统不会自动停止实验。');}
  catch(e){if(ticket===epoch.current){setStatus(null);setMessage(String(e.message||e));}}finally{flight.current=false;if(ticket===epoch.current)setBusy(false);}}
 async function act(payload,label){if(flight.current||!canManageVersions(status))return;if(payload.target&&payload.target!==status.target){setMessage('原请求属于其他版本库，已拒绝发送。');return;}flight.current=true;setBusy(true);setOnlineDownloading(payload.action==='online-download');const ticket=epoch.current,context=status;
  try{const reply=await call({...payload,target:context.target});if(ticket!==epoch.current)return;if(reply.error)throw Error(reply.error.message);if(!sameVersionTarget(context,reply))throw Error('版本库或信任配置已变化，请重新读取。');
   if(payload.action==='update-preview')setPreview(reply);else if(payload.action==='launch-preview')setLaunchPlan(reply);else if(payload.action==='online-preview')setOnlinePlan(reply);else if(payload.action==='online-restore'){setOnlineAttempt({...reply.request,target:context.target});setOnlineSource(reply.request.source);setOnlineMaximum(String(reply.request.maximum/1024**2));setOnlinePlan(null);}else{if(payload.action==='online-download'){setSource(reply.source);setManifest(reply.manifest);setOnlinePlan(null);}if(payload.action==='online-cancel')setOnlineAttempt(null);setPreview(null);setLaunchPlan(null);const current=await call({action:'status'});if(ticket===epoch.current&&sameVersionTarget(context,current))setStatus(current);}
   setMessage(payload.action==='online-cancel'&&reply.pause_recorded!==true?'此暂停标识已处理，未重新暂停；请读取当前记录。':label+(reply.state==='intent'?'：操作未收口，请读取记录核对，不能当成已更新。':'。'));
  }catch(e){if(ticket===epoch.current)setMessage(String(e.message||e)+'；已有记录和资产保留，请先读取状态。');}
  finally{flight.current=false;if(ticket===epoch.current){setBusy(false);setOnlineDownloading(false);}}}
 async function pauseOnline(){if(cancelFlight.current||!onlineDownloading||!onlineAttempt||!status)return;cancelFlight.current=true;const ticket=epoch.current,context=status,operation=onlineAttempt.operation_id;
  try{const reply=await call({action:'online-cancel',target:context.target,operation_id:operation,cancel_id:crypto.randomUUID()});if(ticket!==epoch.current)return;if(reply.error)throw Error(reply.error.message);if(!sameVersionTarget(context,reply)||reply.operation_id!==operation||!/^[0-9a-f]{64}$/.test(reply.cancel_sha256||''))throw Error('暂停记录未确认，请读取状态。');if(reply.pause_recorded!==true){setMessage('此暂停标识已处理，未重新暂停；请读取当前记录。');return;}setOnlineAttempt(prior=>prior?.operation_id===operation?{...prior,resume_sha256:reply.cancel_sha256}:prior);setMessage('已记录暂停请求；当前在途操作仍可能完成，部分文件会保留。');}
  catch(e){if(ticket===epoch.current)setMessage(String(e.message||e));}finally{cancelFlight.current=false;}}
 async function apply(){if(!preview||!window.confirm(`确认切换到 ${version}？只检查已登记实验；不会自动停止任何实验，旧版本和备份会保留。`))return;
  try{const operation=crypto.randomUUID();const payload=versionChangePayload(status,preview,version,operation);setAttempt(payload);await act(payload,'已收到版本切换结果');}catch(e){setMessage(String(e.message||e));}}
 const editable=canManageVersions(status,busy);
 return <section><h2>版本与恢复</h2><p>此入口管理独立的Windows/Linux版本库。Mac继续使用原更新方式；版本库中的旧版本、实验数据和失败记录会保留。</p>
  <VersionSetup onConfig={value=>{if(!flight.current)change(value);}}/>
  <label>版本库配置<input aria-label="版本库配置" disabled={busy} value={config} onChange={e=>change(e.target.value)} placeholder="首次设置或管理员准备的 JSON 配置绝对路径"/></label><button disabled={busy} onClick={()=>choose('version_config',change)}>选择版本库配置</button><button disabled={busy||!config} onClick={load}>读取版本状态</button>
  <div role="status" className="notice">{message}</div>
  {status&&<><p>当前版本：{status.active||'未选择'} · 上一版本：{status.previous||'无'}</p>
   {status.read_only&&<p>{status.requires_stable_manager?'请关闭当前版本的应用，并从安装目录的独立管理入口进行版本变更。':'本机仅开放版本库读取，原Mac更新器保持不变。'}</p>}
   {status.requires_initialize&&<button disabled={!editable} onClick={()=>{if(window.confirm('明确准备此版本库的更新记录？不会移动实验数据。'))act({action:'initialize'},'版本库记录已准备');}}>准备更新记录</button>}
   <h3>登记实验范围</h3><p>切换前只检查已登记的实验目录；未登记目录不会被自动停止或推断为已停机。</p>
   {status.workspaces?.map(item=><p key={item.instance_uuid}><code>{item.path}</code></p>)}
   <label>已有实验目录<input aria-label="登记实验目录" disabled={!editable} value={workspace} onChange={e=>setWorkspace(e.target.value)}/></label><button disabled={!editable||!workspace||status.requires_initialize} onClick={()=>act({action:'register',workspace},'实验目录已登记')}>登记此目录</button>
   <h3>暂存签名版本</h3><label>已展开的版本文件夹<input aria-label="版本文件夹" disabled={!editable} value={source} onChange={e=>setSource(e.target.value)}/></label>
   <label>签名版本清单<input aria-label="签名版本清单" disabled={!editable} value={manifest} onChange={e=>setManifest(e.target.value)}/></label><button disabled={!editable} onClick={()=>choose('release_manifest',setManifest)}>选择签名清单</button>
   <button disabled={!editable||!source||!manifest} onClick={()=>act({action:'stage',source,manifest},'版本已完成暂存请求')}>校验并暂存</button>
   <h3>准备在线版本</h3><p>只访问填写的HTTPS来源，核验签名索引与版本清单后下载。完成后仍须单独暂存和切换；不会自动启动或停止应用。</p>
   <label>版本来源<input aria-label="在线版本来源" disabled={!editable} value={onlineSource} onChange={e=>{setOnlineSource(e.target.value);setOnlinePlan(null);setOnlineAttempt(null);}} placeholder="https://版本来源/目录/"/></label>
   <label>版本文件上限（MiB）<input aria-label="在线版本下载上限" disabled={!editable} type="number" min="1" max="16384" value={onlineMaximum} onChange={e=>{setOnlineMaximum(e.target.value);setOnlinePlan(null);setOnlineAttempt(null);}}/></label>
   <button disabled={!editable||!onlineSource} onClick={()=>act({action:'online-preview',source:onlineSource,maximum:Number(onlineMaximum)*1024**2},'已核对在线版本签名与大小')}>核对在线版本</button>
   {onlinePlan&&<p>版本 {onlinePlan.version} · {onlinePlan.platform} · {onlinePlan.files} 个文件 · {onlinePlan.bytes} 字节</p>}
   <button disabled={!editable||!onlinePlan} onClick={()=>{if(!window.confirm('下载已核对的签名版本？失败材料和旧版本会保留，不会自动切换。'))return;try{const payload=onlineDownloadPayload(status,onlinePlan,onlineSource,Number(onlineMaximum)*1024**2,crypto.randomUUID());setOnlineAttempt(payload);act(payload,'在线文件已核验，已填入暂存路径');}catch(e){setMessage(String(e.message||e));}}}>下载已核对版本</button>
   <button disabled={!onlineDownloading||!onlineAttempt} onClick={pauseOnline}>暂停本次下载</button>
   {onlineAttempt&&<button disabled={!editable} onClick={()=>{if(window.confirm('明确使用原标识核对或续传下载？不会自动暂存、切换或启动。'))act(onlineAttempt,'原下载已核对，已填入暂存路径');}}>核对或续传原下载</button>}
   {status.online_downloads?.map(item=><p key={item.operation_id}>下载 {item.version||'待核对'} · {item.pause_recorded?'已记录暂停':item.state==='download-recorded'?'已留完成记录，尚未重新核验文件':'部分材料保留'} <button disabled={!editable} onClick={()=>act({action:'online-restore',operation_id:item.operation_id},'已恢复原请求记录，尚未连接来源；请明确核对或续传')}>恢复此下载记录</button><button disabled={!editable||item.pause_recorded} onClick={()=>act({action:'online-cancel',operation_id:item.operation_id,cancel_id:crypto.randomUUID()},'已记录暂停请求，当前在途操作仍可能完成；恢复原记录后才能明确续传')}>请求暂停此下载</button></p>)}
   <h3>切换或回退</h3><label>目标版本<select aria-label="目标版本" disabled={!editable} value={version} onChange={e=>{setVersion(e.target.value);setPreview(null);setAttempt(null);}}><option value="">选择已暂存版本</option>{status.versions?.map(item=><option key={item}>{item}</option>)}</select></label>
   <button disabled={!editable||!version||status.requires_initialize} onClick={()=>act({action:'update-preview',version},'已核对切换预览')}>核对切换预览</button>
   {preview&&<p>目标 {preview.target} · 已登记实验 {preview.workspaces?.length||0} 个 · 元数据备份后切换，实验磁盘不回退。</p>}
   <button disabled={!editable||!preview||preview.target!==version} onClick={apply}>确认切换到此版本</button>
   {attempt&&<button disabled={!editable} onClick={()=>{if(window.confirm('使用原操作标识读取或重试？不会创建新标识或自动重放中断步骤。'))act(attempt,'已读取原操作结果');}}>核对原切换请求</button>}
   <h3>启动当前版本</h3><button disabled={!editable||!status.active||status.requires_initialize} onClick={()=>act({action:'launch-preview'},'已核对启动签名与入口')}>核对启动条件</button>
   <button disabled={!editable||!launchPlan} onClick={()=>act({action:'launch',plan_sha256:launchPlan.plan_sha256},'已请求独立应用启动，运行结果请再读取记录核对')}>启动已核对版本</button>
   <h3>保留的恢复记录</h3>{status.updates?.map(item=><p key={item.operation_id}>{item.target||'未提交'} · {item.state} · {item.operation_id.slice(0,8)} {['intent','interrupted-before-commit'].includes(item.state)&&<button disabled={!editable} onClick={()=>{if(window.confirm('保留当前版本和全部备份，明确结清此中断尝试？不会重放文件步骤。'))act({action:'abandon',operation_id:item.operation_id},'已请求保留当前版本并结清尝试');}}>保留当前版本并结清</button>}</p>)}
   {status.launches?.map(item=><p key={item.launch_id}>启动 {item.launch_id.slice(0,8)} · {item.state==='exit-recorded'?'已记录应用退出':'退出仍待独立核验，不能直接清理或切换版本'}</p>)}
  </>}
 </section>;
}
