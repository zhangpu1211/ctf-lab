import React,{useEffect,useState} from 'react';
import {defaultRegistrationForm,registrationFromForm,validateForm,statusView,slotSummary,cliConnectHint,isAbsoluteHostPath} from './external-attach-model.mjs';

// 外部攻击机卡片：登记、槽位预览与助手材料；连接按钮待实机验收组合通过后启用。
export default function ExternalAttach({root,call,busy,onMessage}){
 const [report,setReport]=useState(null);
 const [form,setForm]=useState(defaultRegistrationForm());
 const [network,setNetwork]=useState('');
 const [destination,setDestination]=useState('');
 const [sshConfig,setSshConfig]=useState('');
 useEffect(()=>{let alive=true;
  if(!root){setReport(null);return;}
  (async()=>{try{const v=await call({action:'external-attach-status'},root);if(alive)setReport(v);}catch(e){if(alive)onMessage(String(e.message||e));}})();
  return()=>{alive=false;};
 },[root,call,onMessage]);
 const view=statusView(report);
 const field=(key,label)=>(<label key={key}>{label}<input value={form[key]} onChange={e=>setForm({...form,[key]:e.target.value})}/></label>);
 async function save(){
  const error=validateForm(form);
  if(error){onMessage(error);return;}
  try{const v=await call({action:'external-attach-save',registration:registrationFromForm(form),network},root);
   if(v.error)throw Error(v.error.message);
   onMessage('登记已保存。请生成会话材料，在专用Kali内完成setup后连接。');
   const status=await call({action:'external-attach-status'},root);setReport(status);
  }catch(e){onMessage(String(e.message||e));}
 }
 async function clear(){
  if(!window.confirm('清除外部攻击机登记？只删除本机登记意图，不停止任何虚拟机。'))return;
  try{const v=await call({action:'external-attach-clear'},root);if(v.error)throw Error(v.error.message);
   setReport(await call({action:'external-attach-status'},root));onMessage('登记已清除。');
  }catch(e){onMessage(String(e.message||e));}
 }
 async function connect(){
  if(!isAbsoluteHostPath(sshConfig)){onMessage('请填写完整SSH配置JSON的绝对路径（含known_hosts与身份文件）。');return;}
  if(!window.confirm('连接外部攻击机？将启动受控中转；失败时显示具体阶段，不会重放旧帧。'))return;
  try{const v=await call({action:'external-attach-connect',ssh_config:sshConfig},root);
   if(v.error)throw Error(v.error.message);
   onMessage(v.error?.message||({ 'relay-requested':'连接已请求；状态以刷新结果为准。','relay-unknown':'派发结果未知，原会话记录保留，请先读取状态。' }[v.state]||'请核对当前状态。'));
   setReport(await call({action:'external-attach-status'},root));
  }catch(e){onMessage(String(e.message||e));setReport(await call({action:'external-attach-status'},root).catch(()=>null));}
 }
 async function disconnect(){
  if(!window.confirm('断开外部攻击机通道？仅撤除中转；Kali内的工具进程不会被停止，残留以助手status为准。'))return;
  try{const v=await call({action:'external-attach-disconnect'},root);
   if(v.error)throw Error(v.error.message);
   onMessage(v.note||'请读取状态核对断开结果。');
   setReport(await call({action:'external-attach-status'},root));
  }catch(e){onMessage(String(e.message||e));}
 }
 async function makeMaterials(){
  if(!isAbsoluteHostPath(destination)){onMessage('请填写材料输出目录的绝对路径。');return;}
  try{const v=await call({action:'external-attach-materials',destination},root);
   if(v.error)throw Error(v.error.message);
   onMessage('Kali助手材料已生成；请按准备命令在授权Kali内创建会话后连接。');
   setReport(await call({action:'external-attach-status'},root));
  }catch(e){onMessage(String(e.message||e));}
 }
 const hint=cliConnectHint(report?.binding_valid?report.binding:null);
 return (<section className="external-attach" aria-label="外部攻击机">
  <h2>外部攻击机</h2>
  <p className="muted">{view.note||'在同一台电脑上把已有的Kali接入指定实验网段；Kali的启动、暂停、关机、快照和磁盘仍由原虚拟机软件管理。'}</p>
  {view.ready&&<><p className={'binding '+(view.binding.stale?'stale':'')}>{view.binding.text}</p>
   {view.slots.available?<div className="slot-list">{view.slots.items.map(item=>(<label key={item.network} className="slot"><input type="radio" name="external-network" checked={network===item.network} onChange={()=>setNetwork(item.network)}/> {item.label}</label>))}</div>
    :<p className="muted">{view.slots.note}</p>}
   <details><summary>登记 Kali</summary>
    <div className="form-grid">
     {field('name','显示名称')}{field('host','SSH地址')}{field('port','SSH端口')}
     {field('user','SSH用户')}{field('identity','本地私钥路径')}{field('machine_uuid','机器UUID（Kali内读取）')}
     {field('vendor','厂商')}{field('product','产品')}{field('assistant_sha256','助手SHA-256')}
    </div>
    <p className="muted">主机密钥采用严格校验；身份未知不会放宽为仅凭IP授权。安装助手是独立操作，不混在连接测试里。</p>
    <div className="actions"><button disabled={busy||!network||!view.slots.available} onClick={save}>保存登记</button>
     <button disabled={busy} onClick={clear}>清除登记</button></div>
   </details>
   <details><summary>Kali 助手材料</summary>
    <label>材料输出目录<input value={destination} onChange={e=>setDestination(e.target.value)} placeholder="/绝对路径/ctflab-kali-materials 或 C:\\ctflab\\kali-materials"/></label>
    <div className="actions"><button disabled={busy} onClick={makeMaterials}>生成材料</button></div>
    <p className="muted">材料只生成不安装；真实TAP/命名空间行为与原管理网保全以实机验收为准。</p>
   </details>
   {report.binding?.prepared&&<div className="prepared-session"><p>在授权的 Kali 内以管理员运行：</p>
    <pre>{report.binding.prepared.setup_command}</pre>
    <p>实验终端：</p><code>{report.binding.prepared.shell_command}</code>
    <p>撤网命令：</p><code>{report.binding.prepared.teardown_command}</code>
    <p className="muted">连接前须完成助手安装批准（未批准会按身份未核验拒绝）：在宿主终端运行 <code>ctflab external-attach approve --registration &lt;登记JSON&gt; --materials-manifest &lt;材料目录&gt;/manifest.json</code>。</p></div>}
   <details><summary>诊断与协议</summary>
    <ul className="diag">{view.diagnostics.map((line,i)=><li key={i}>{line}</li>)}</ul>
   </details>
   <div className="actions attach-session">
    <label className="ssh-config">SSH配置JSON路径<input value={sshConfig} onChange={e=>setSshConfig(e.target.value)} placeholder="/绝对路径/ctflab-kali.ssh.json 或 C:\\Users\\me\\ctflab-kali.ssh.json"/></label>
    <button disabled={busy||!view.canConnect||!report?.binding?.prepared||report.binding.prepared.used||!isAbsoluteHostPath(sshConfig)} onClick={connect}>连接</button>
    <button disabled={busy||!view.canDisconnect} onClick={disconnect}>断开</button>
   </div>
   <p className="muted">会话状态：{view.session.text}。普通桌面程序不进入实验网络；断开只撤中转，不停VM、不杀工具。{!view.connect&&' 本代次未预留接入口或未登记时连接不可用。'}{hint&&<><br/><code>{hint}</code></>}</p>
  </>}
 </section>);
}
