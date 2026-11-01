import React,{useEffect,useRef,useState} from 'react';
import {invoke} from '@tauri-apps/api/core';
export default function RemoteEvidence({connection,instance,onMessage}){
 const [exports,setExports]=useState([]),[history,setHistory]=useState([]),[busy,setBusy]=useState(false),[active,setActive]=useState(null),[consent,setConsent]=useState(false);
 const epoch=useRef(0),flight=useRef(false);
 useEffect(()=>()=>{epoch.current++;},[]);
 if(!connection?.persisted||!connection?.evidence_available)return null;
 const id=connection.config.savedId;
 async function records(){const reply=await invoke('client_bridge',{payload:{action:'evidence-history',id}});if(reply.error)throw Error(reply.error.message);return reply.downloads||[];}
 async function list(){if(flight.current)return;flight.current=true;setBusy(true);const ticket=epoch.current;
  try{const reply=await invoke('client_bridge',{payload:{action:'evidence-list',id,instance_uuid:instance}});if(ticket!==epoch.current)return;
   if(reply.error)throw Error(reply.error.message);setExports(reply.exports||[]);setHistory(await records());
  }catch(e){if(ticket===epoch.current)onMessage(String(e.message||e));}finally{if(ticket===epoch.current)setBusy(false);flight.current=false;}}
 async function download(entry,file,previous=null){if(flight.current||!consent)return;flight.current=true;setBusy(true);const ticket=epoch.current,downloadId=previous||crypto.randomUUID();setActive(downloadId);
  const payload=previous?{action:'evidence-resume',download_id:downloadId}:{action:'evidence-download',id,download_id:downloadId,
   payload:{instance_uuid:instance,export_id:entry.export_id,file:file.name,sha256:file.sha256,size:file.size}};
  try{const reply=await invoke('client_bridge',{payload});if(ticket!==epoch.current)return;if(reply.error)throw Error(reply.error.message);
   setHistory(await records());onMessage(reply.phase==='verified'?'本次证据副本已校验并保存在本机；文件未自动打开或解包。':'下载未完成，已保留现有字节；可明确续传。');
  }catch(e){if(ticket===epoch.current){onMessage(String(e.message||e));try{setHistory(await records());}catch{}}}
  finally{if(ticket===epoch.current){setBusy(false);setActive(null);}flight.current=false;}}
 async function cancel(){if(!active)return;try{const reply=await invoke('client_bridge',{payload:{action:'evidence-cancel',download_id:active}});if(reply.error)throw Error(reply.error.message);onMessage('已请求暂停证据下载；不发送实验停止请求。');}catch(e){onMessage(String(e.message||e));}}
 return <section className="remote-evidence"><h3>封存证据取回</h3><p>仅列出管理员明确发布到此实例的证据；不读取任意路径。下载内容可能包含实验流量和时间线。</p>
  <button disabled={busy} onClick={list}>读取封存证据列表</button>
  <label><input type="checkbox" checked={consent} disabled={busy} onChange={e=>setConsent(e.target.checked)}/>我确认将所选原始证据保存到本机，文件不会自动打开或解包。</label>
  {active&&<button onClick={cancel}>暂停本次下载</button>}
  {exports.map(entry=><div key={entry.export_id}><p>代次 {entry.generation} · {entry.export_id.slice(0,8)}</p>{entry.files.map(file=><p key={file.name}>{file.name} · {file.size} 字节 <button disabled={busy||!consent} onClick={()=>download(entry,file)}>下载此文件</button></p>)}</div>)}
  {history.filter(item=>item.instance_uuid===instance).map(item=><div key={item.download_id}><p>{item.file} · {item.received}/{item.size} · {item.phase==='verified'?'完成校验（历史记录）':'未完成'} {item.phase!=='verified'&&<button disabled={busy||!consent} onClick={()=>download(null,null,item.download_id)}>明确续传</button>}</p>{item.local_path&&<p>本机位置：<code>{item.local_path}</code></p>}</div>)}
 </section>;
}
