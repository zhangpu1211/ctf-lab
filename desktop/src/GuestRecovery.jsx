import React,{useState}from'react';
import{canInspectGuestPreparation,canResumeGuestPreparation,guestPreparationParameters}from'./model.mjs';
export default function GuestRecovery({view,node,busy,onOperate,onError}){
 const [selected,setSelected]=useState(''),info=view.guest_agents[node],records=info.preparation_records||[],target=selected||records[0]?.operation_id||'';
 const snapshot=info.last_action==='preparation-inspect'?info.last_result:null,matching=snapshot?.operation_id===target;
 function act(resume){try{if(resume&&!window.confirm('保留旧文件和数据，只续建核对后尚未完成的准备步骤？可能创建缺少的容器，但保持停止；结果未知的装载或创建不会重发。'))return;onOperate('guest',guestPreparationParameters(view,node,target,resume));}catch(e){onError(e.message);}}
 return<section className="guest-recovery"><p>准备中断后，先使用实验的“恢复核验”，再核对原准备记录。旧记录不代表来宾当前状态。</p>
 {records.length>0&&<label>已有待核对记录<select aria-label={node+'原准备记录'} value={target} onChange={e=>setSelected(e.target.value)}>{!records.some(r=>r.operation_id===target)&&<option value={target}>手动选择的记录</option>}{records.map((r,i)=><option key={r.operation_id} value={r.operation_id}>记录 {i+1} · {r.operation_id.slice(0,8)}</option>)}</select></label>}
 <label>准备记录标识<input aria-label={node+'准备记录标识'} value={target} maxLength={36} onChange={e=>setSelected(e.target.value.trim())}/></label>
 <div className="actions"><button disabled={!canInspectGuestPreparation(view,node,target,busy)} onClick={()=>act(false)}>核对容器准备现场</button><button disabled={!canResumeGuestPreparation(view,node,target,busy)} onClick={()=>act(true)}>保留现场，继续准备</button></div>
 {matching&&<><p>{snapshot.can_resume?'可以继续未完成的准备；不会启动容器。':'当前现场不允许续建，请保留记录。'}</p><ul>{(snapshot.steps||[]).map(s=><li key={s.step}>{s.step} · {({'recorded':'身份与记录一致','observed-unrecorded':'资源存在，记录未闭合','not-started':'尚未开始','unknown-absent':'结果未知且未找到资源','recorded-missing':'已有记录但资源缺失'})[s.state]||'待核对'}</li>)}</ul></>}
 {snapshot?.state==='completed'&&snapshot.operation_id===target&&<p>该准备操作已有完成记录；本次核对未重放操作，真实服务仍需另行验收。</p>}</section>;
}
