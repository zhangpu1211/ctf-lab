import React,{useEffect,useRef,useState} from 'react';
import {invoke} from '@tauri-apps/api/core';
import {boundedCall,labels,operationHistory,operationResult} from './model.mjs';

const names={prepare:'准备',start:'启动',stop:'保存并停止',reset:'重置',recover:'恢复核验',cancel:'请求取消',guest:'来宾操作'};
const statuses={pending:'已登记，尚未领取',executing:'曾被领取，结果待核对',unknown:'结果未知',failed:'已保存未完成响应',completed:'已保存响应'};

export default function OperationHistory({root,instance}){
 const [rows,setRows]=useState(null),[next,setNext]=useState(null),[selected,setSelected]=useState(null),[busy,setBusy]=useState(false),[message,setMessage]=useState('重新打开管理窗口后，可从原账本读取已保存操作。');
 const epoch=useRef(0),flight=useRef(false);
 useEffect(()=>()=>{epoch.current++;},[root,instance]);
 async function read(operation=null,before=null){
  if(flight.current||!root||!instance)return;flight.current=true;setBusy(true);const ticket=epoch.current;
  try{
   const payload=operation?{action:'operation-result',operation_id:operation}:{action:'operation-history',limit:20,...(before?{before}:{})};
   const reply=await boundedCall(()=>invoke('bridge',{run:root,payload}));if(ticket!==epoch.current)return;
   if(reply.error)throw Error(reply.error.message||'保存记录暂不可读，现场保留。');
   if(operation){setSelected(operationResult(reply,instance,operation));setMessage('以下只显示原账本响应，不证明现在仍处于同一状态。');}
   else{setRows(operationHistory(reply,instance));setNext(reply.next_before);setSelected(null);setMessage(reply.truncated?'每页最多20项，可继续读取更早记录；原记录未删除。':'已读取原账本；缺少记录不能证明操作从未执行。');}
  }catch(error){if(ticket===epoch.current){setSelected(null);setMessage(String(error.message||error));}}
  finally{flight.current=false;if(ticket===epoch.current)setBusy(false);}
 }
 return <section className="timeline"><h2>已保存操作（历史）</h2>
  <p>只读，不提交或重发操作；当前运行状态请看上方概览。</p>
  <button disabled={busy||!instance} onClick={()=>read()}>读取原账本</button>
  {next&&<button disabled={busy} onClick={()=>read(null,next)}>更早一页</button>}
  <p role="status">{message}</p>
  {rows?.length===0&&<p>没有查到已保存操作，请结合当前状态和日志核对。</p>}
  {rows?.map(record=><div className="event" key={record.operation_id}><code>{record.operation_id.slice(0,8)}</code><b>{names[record.operation]}</b><span>{statuses[record.status]}</span><button disabled={busy} onClick={()=>read(record.operation_id)}>查看原响应</button></div>)}
  {selected&&<div><p>原响应：{selected.response?(labels[selected.response.state]||selected.response.state)+'（历史）':'尚无已保存响应，结果仍需核对。'}</p>
   {selected.response?.error&&<p>{selected.response.error.message}</p>}
   <p>此处不会据历史记录恢复、停止、重置或再派发。</p></div>}
 </section>;
}
