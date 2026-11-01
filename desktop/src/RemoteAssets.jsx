import React,{useEffect,useRef,useState} from 'react';
import {invoke} from '@tauri-apps/api/core';
export default function RemoteAssets({connection,onMessage}){
 const [file,setFile]=useState(''),[source,setSource]=useState(''),[audience,setAudience]=useState('student'),[items,setItems]=useState([]),[working,setWorking]=useState(false);
 const alive=useRef(true),gate=useRef(false);
 const id=connection.config?.savedId;
 const call=payload=>invoke('client_bridge',{payload});
 async function refresh(){if(!id)return;try{const result=await call({action:'asset-history',id});if(alive.current&&!result.error)setItems(result.uploads);}catch(e){if(alive.current)onMessage('传输记录暂时无法读取；不会自动续传。');}}
 useEffect(()=>{alive.current=true;refresh();const timer=setInterval(refresh,2000);return()=>{alive.current=false;clearInterval(timer);};},[id]);
 async function upload(item=null){if(!id||gate.current)return;const uploadId=item?.upload_id||crypto.randomUUID();if(!window.confirm(item?'使用原upload_id和原文件继续传输？不创建或启动实例。':'上传选定文件到服务器许可缓存？不会导入或启动实例。'))return;gate.current=true;setWorking(true);try{
  const payload=item?{action:'asset-resume',upload_id:uploadId}:{action:'asset-upload',id,upload_id:uploadId,file,source,audience};
  const result=await call(payload);if(alive.current)onMessage(result.error?.message||`传输${uploadId}：${result.phase}。这不代表镜像或课程运行通过。`);
 }catch(e){if(alive.current)onMessage('传输结果未确认；记录保留，先查进度后明确续传。');}finally{gate.current=false;if(alive.current){setWorking(false);refresh();}}}
 async function pause(item){try{const result=await call({action:'asset-cancel',upload_id:item.upload_id});if(alive.current)onMessage(result.error?.message||'已请求暂停；在校验/分块边界停止自有传输，服务器部分数据保留。');await refresh();}catch(e){if(alive.current)onMessage('暂停尚未确认，请继续查看传输记录。');}}
 async function probe(item){try{const result=await call({action:'asset-probe',upload_id:item.upload_id});if(alive.current)onMessage(result.error?.message||(result.server_current_verified?'本次远端缓存核对通过；不代表运行效果。':'本次远端状态尚未验证。'));}catch(e){if(alive.current)onMessage('远端状态未取得，不重发上传。');}}
 async function choose(){try{const path=await invoke('choose_remote_file',{kind:'asset'});if(path&&alive.current)setFile(path);}catch(e){if(alive.current)onMessage(String(e.message||e));}}
 if(!id)return <p>资产传输需先保存目标并明确连接，才能持久保留原upload_id和续传记录。</p>;
 if(connection.asset_upload!==true)return <p>此目标未声明资产上传能力；不会自动初始化服务器缓存或开启上传。</p>;
 return <div className="remote-assets"><h3>远程资产缓存</h3><p>服务器必须预先登记可信签名索引与许可；此入口不提供任意下载、不创建实例或改变网络。</p>
 <label>已许可资产文件<input aria-label="上传资产文件" value={file} disabled={working} onChange={e=>setFile(e.target.value)} placeholder="本机绝对路径"/></label>
 <button disabled={working} onClick={choose}>选择资产文件</button>
 <label>签名索引源<input aria-label="资产索引源" value={source} disabled={working} onChange={e=>setSource(e.target.value)} placeholder="https://校内源地址/"/></label>
 <label>材料范围<select aria-label="资产材料范围" disabled={working} value={audience} onChange={e=>setAudience(e.target.value)}><option value="student">学生材料</option><option value="teacher">教师材料（服务器核验权限）</option></select></label>
 <button disabled={working||!file||!source} onClick={()=>upload()}>明确上传资产</button><button onClick={refresh}>刷新传输记录</button>
 {items.map(item=><div key={item.upload_id}><p>{item.upload_id} · {item.phase} · {item.received}/{item.size} 字节 · 第{item.tries}次明确尝试</p><p>“verified”是上次客户端结果，当前远端需明确核对。</p><div className="actions"><button disabled={item.phase==='verified'} onClick={()=>pause(item)}>暂停传输</button><button disabled={working||item.phase==='verified'} onClick={()=>upload(item)}>使用原标识续传</button><button disabled={!item.sha256} onClick={()=>probe(item)}>核对远端缓存</button></div></div>)}
 <p>关闭页面不会删除部分数据或自动续传；传输进程可能继续，暂停请明确点击。资源操作与上传共用本机发送门，长传输期间可读取状态和请求暂停。</p></div>;
}
