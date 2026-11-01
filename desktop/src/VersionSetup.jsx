import React,{useState,useRef} from 'react';
import {invoke} from '@tauri-apps/api/core';
import {bootstrapCreatePayload,bootstrapResumePayload} from './version-model.mjs';

export default function VersionSetup({onConfig}){
 const [view,setView]=useState(null),[keys,setKeys]=useState(''),[plan,setPlan]=useState(null),[busy,setBusy]=useState(false),[message,setMessage]=useState('首次使用可先检查设置。已有版本库不会覆盖或移动。');
 const flight=useRef(false),epoch=useRef(0);
 async function send(payload){
  if(flight.current)return;flight.current=true;setBusy(true);const ticket=epoch.current;
  try{
   const reply=await invoke('version_setup',{payload});if(ticket!==epoch.current)return;
   if(reply.error||reply.state==='refused-or-unknown')throw Error(reply.error?.message||'设置结果未能确认，请读取原记录。');
   if(payload.action==='bootstrap-preview'){setPlan(reply);setMessage('请核对公钥指纹和新目录。指纹相同不代表发布者已由软件验证。');}
   else{setView(reply);setPlan(null);setMessage(reply.ready?'版本库已准备，尚未安装、切换或启动任何版本。':reply.state==='unrecognized-preserved'?'已有目录无法识别，原文件保留；请先人工核对，不会重建。':reply.read_only?'当前入口只读；请从安装目录的独立入口管理。':'原记录已读取。未知步骤不会重新执行。');}
  }catch(e){setPlan(null);setMessage(String(e.message||e)+'；可检查原设置记录，失败现场保留。');}
  finally{flight.current=false;setBusy(false);}
 }
 async function choose(){
  if(busy)return;
  try{const path=await invoke('choose_remote_file',{kind:'release_keys'});if(path){epoch.current++;setKeys(path);setPlan(null);}}
  catch(e){setMessage(String(e.message||e));}
 }
 const writable=view?.available===true&&view.read_only===false&&!view.ready;
 return <details><summary>首次准备版本库</summary>
  <p>在独立的数据目录建立新版本库与配置，不移动已有实验，不下载或启动软件。发布公钥必须来自你核对的发布者。</p>
  <button disabled={busy} onClick={()=>send({action:'bootstrap-status'})}>检查设置 / 读取原记录</button>
  {view?.available===false&&<p>本机继续使用原Mac更新方式，不创建此版本库。</p>}
  {writable&&view.state==='not-configured'&&<>
   <label>发布公钥文件（本机JSON）<input value={keys} disabled={busy} onChange={e=>{epoch.current++;setKeys(e.target.value);setPlan(null);}}/></label>
   <button disabled={busy} onClick={choose}>选择发布公钥</button><span>{keys?'已选择本机公钥文件':'尚未选择公钥'}</span>
   <button disabled={busy||!keys} onClick={()=>send({action:'bootstrap-preview',public_keys:keys})}>预览新设置</button>
  </>}
  {plan&&<div><p>新数据目录：<code>{plan.root}</code></p><p>公钥 {plan.keys_count} 个 · 文件指纹：<code>{plan.source_sha256}</code></p>
   <p>请通过发布者独立提供的信息核对以上指纹。此步骤不会认证发布者身份。</p>
   <button disabled={busy} onClick={()=>{if(!window.confirm('确认公钥来源和指纹，并创建此新版本库？已有目录不会覆盖，不会安装、切换或启动软件。'))return;try{send(bootstrapCreatePayload(plan,keys,crypto.randomUUID()));}catch(e){setMessage(e.message);}}}>确认创建新设置</button>
  </div>}
  {view?.operation_id&&!view.ready&&!view.read_only&&<button disabled={busy} onClick={()=>{if(!window.confirm('明确继续原设置？已完成步骤只核对，结果未知的副作用不会重做。'))return;try{send(bootstrapResumePayload(view));}catch(e){setMessage(e.message);}}}>继续原设置</button>}
  {view?.ready&&<button disabled={busy} onClick={()=>onConfig(view.config)}>使用此版本库配置</button>}
  <p role="status">{message}</p>
 </details>;
}
