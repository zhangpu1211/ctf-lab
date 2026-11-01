import React,{useEffect,useState} from 'react';
import {invoke} from '@tauri-apps/api/core';
export default function RemoteTargets({configPath,busy,onConnect,onMessage}){
 const [targets,setTargets]=useState([]),[label,setLabel]=useState(''),[working,setWorking]=useState(false);
 const [wizard,setWizard]=useState({host:'',port:'22',user:'',server_uuid:'',ssh:'',identity:'',known_hosts:''});
 const call=payload=>invoke('client_bridge',{payload});
 async function reload(){try{const result=await call({action:'targets'});if(result.error)throw Error(result.error.message);setTargets(result.targets);}catch(e){onMessage(String(e.message||e));}}
 useEffect(()=>{reload();},[]);
 async function save(create=false){if(busy||working)return;setWorking(true);try{
  const config=create?{...wizard,port:Number(wizard.port)}:configPath;
  const result=await call({action:create?'create-target':'save-target',id:crypto.randomUUID(),label,config});
  if(result.error)throw Error(result.error.message);await reload();onMessage('目标已保存在本机私有目录；尚未连接。请明确选择连接。');
 }catch(e){onMessage(String(e.message||e));}finally{setWorking(false);}}
 async function choose(key){try{const path=await invoke('choose_remote_file',{kind:key});if(path)setWizard(value=>({...value,[key]:path}));}catch(e){onMessage(String(e.message||e));}}
 return <div className="remote-targets"><h3>本机保存的目标</h3><p>读取列表不会连接服务器；保存内容只引用配置和身份文件，不复制私钥。</p>
 <div className="actions">{targets.map(item=><button key={item.id} disabled={busy||working} onClick={()=>onConnect(item)}>{item.label} · {item.server_uuid.slice(0,8)} · 连接</button>)}<button disabled={busy||working} onClick={reload}>刷新目标列表</button></div>
 <label>目标名称<input aria-label="目标名称" value={label} disabled={busy||working} maxLength="96" onChange={e=>setLabel(e.target.value)}/></label><button disabled={busy||working||!label||!configPath} onClick={()=>save(false)}>保存上方连接配置</button>
 <details><summary>创建新的连接配置</summary><p>填写服务器标识、固定主机密钥文件与本机程序/身份路径。只生成私有配置，不连接或安装SSH；公用主机密钥文件会复制到私有配置目录，原文件不变，私钥不复制。</p>{Object.keys(wizard).map(key=><label key={key}>{({host:'服务器地址',port:'SSH端口',user:'SSH用户',server_uuid:'服务器UUID',ssh:'ssh/ssh.exe绝对路径',identity:'身份文件绝对路径',known_hosts:'固定主机密钥文件绝对路径'})[key]}<input aria-label={'连接配置-'+key} value={wizard[key]} disabled={busy||working} onChange={e=>setWizard({...wizard,[key]:e.target.value})}/>{['ssh','identity','known_hosts'].includes(key)&&<button disabled={busy||working} onClick={()=>choose(key)}>选择文件</button>}</label>)}<button disabled={busy||working||!label||Object.values(wizard).some(value=>!value)} onClick={()=>save(true)}>生成并保存配置</button></details></div>;
}
