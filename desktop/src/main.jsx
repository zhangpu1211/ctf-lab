import React, {useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {invoke} from '@tauri-apps/api/core';
import {labels,request,allowed,refreshEvents,canResumeDispatch,canRestartPreparation,canRearmObserver,canRearmLog,configurationReady,overviewFresh,boundedCall,createRefreshScope} from './model.mjs';
import './style.css';
import GraphEditor from './GraphEditor.jsx';
import{createGraphHistory,editGraphHistory,undoGraphHistory,redoGraphHistory}from'./graph-model.mjs';
import RemoteWorkspace from './RemoteWorkspace.jsx';
import Versions from './Versions.jsx';
import GuestRecovery from './GuestRecovery.jsx';
import OperationHistory from './OperationHistory.jsx';
import PreparationProgress from './PreparationProgress.jsx';
import ExternalAttach from './ExternalAttach.jsx';

function NavIcon({name}){
 const paths={实验:'M4 4h16v12H4z M8 20h8 M12 16v4',拓扑:'M9 3h6v6H9z M2 15h6v6H2z M16 15h6v6h-6z M12 9v3 M5 15v-3h14v3',模板:'M6 3h9l4 4v14H6z M14 3v5h5 M9 12h7 M9 16h7',远程:'M3 4h18v12H3z M8 20h8 M12 16v4 M8 10h8 M13 7l3 3-3 3',版本:'M12 3l9 5-9 5-9-5z M3 12l9 5 9-5 M3 16l9 5 9-5',诊断:'M9 3h6l1 3h4v15H4V6h4z M8 12h8 M8 16h5'};
 return <span className="nav-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d={paths[name]||paths.实验}/></svg></span>;
}
function App(){
 const [appearance,setAppearance]=useState(()=>{try{const v=localStorage.getItem('ctflab.appearance');return ['system','light','dark'].includes(v)?v:'system';}catch{return 'system';}});
 useEffect(()=>{document.documentElement.dataset.appearance=appearance;try{localStorage.setItem('ctflab.appearance',appearance);}catch{}},[appearance]);
 const [run,setRun]=useState(''),[opened,setOpened]=useState(''),[view,setView]=useState(null),[tab,setTab]=useState('实验'),[busy,setBusy]=useState(false),[message,setMessage]=useState('选择新的实验目录并导入配置，或打开已配置的通用实例。'),[events,setEvents]=useState([]),[diag,setDiag]=useState(null),[history,setHistory]=useState(()=>createGraphHistory('')),[diff,setDiff]=useState(null);
 const draft=history.present;
 const [files,setFiles]=useState({manifest:'',assets:'',profile:'',nvram:''});
 const [emulationConsent,setEmulationConsent]=useState(false);
 const [course,setCourse]=useState({catalog:'',course_id:'',variant_id:'',asset_root:''});
 const openedRef=useRef('');
 const scope=useRef(createRefreshScope()),[,setClock]=useState(0), cursor=useRef(0), actionGuard=useRef(false), lastRequest=useRef(null), draftVersion=useRef(0);
 async function call(payload,root=opened){return boundedCall(()=>invoke('bridge',{run:root,payload}));}
 function invalidate(){setView(old=>old?{...old,freshness:{...old.freshness,complete:false}}:null);}
 useEffect(()=>{const timer=setInterval(()=>setClock(n=>(n+1)%60),1000);return()=>clearInterval(timer);},[]);
 async function refresh(root=opened){
  const ticket=scope.current.begin(root);if(!ticket)return;
  try{const v=await call({action:'overview'},root);if(v.error)throw Error(v.error.message);if(!scope.current.current(ticket))return;setView(v);
   const result=refreshEvents(cursor.current,await call({action:'events',after:cursor.current},root),v);
   if(!scope.current.current(ticket))return;cursor.current=result.cursor;if(result.reload){setEvents([]);setMessage('事件序列已变化，历史列表已清空；按可核验的状态继续读取，不会重发操作。');}else setEvents(old=>[...old,...result.events].slice(-80));
  }catch(e){if(scope.current.current(ticket)){invalidate();setMessage(String(e.message||e));}}finally{scope.current.finish(ticket);}
 }

 useEffect(()=>{setEmulationConsent(false);draftVersion.current++;setDiff(null);if(!opened)return;refresh();const timer=setInterval(()=>refresh(),4000);return()=>clearInterval(timer);},[opened]);
 async function open(){draftVersion.current++;setDiff(null);cursor.current=0;setEvents([]);lastRequest.current=null;setEmulationConsent(false);openedRef.current=run;scope.current.attach(run);setView(null);setOpened(run);await refresh(run);}
 async function configure(){if(actionGuard.current)return;actionGuard.current=true;setBusy(true);try{const v=await call({action:'configure',...Object.fromEntries(Object.entries(files).filter(([key,value])=>key!=='nvram'||value))},run);if(v.error)throw Error(v.error.message);openedRef.current=run;scope.current.attach(run);setView(null);setOpened(run);await refresh(run);setMessage('配置已导入。点击准备实验创建独立运行副本。');}catch(e){setMessage(String(e.message||e));}finally{actionGuard.current=false;setBusy(false);}}
 async function importCourse(){if(actionGuard.current)return;actionGuard.current=true;setBusy(true);try{const v=await call({action:'import-course',...course},run);if(v.error)throw Error(v.error.message);openedRef.current=run;scope.current.attach(run);setView(null);setOpened(run);await refresh(run);setMessage('课程资产已校验并导入，使用随包运行时。点击准备实验创建运行副本。');}catch(e){setMessage(String(e.message||e));}finally{actionGuard.current=false;setBusy(false);}}
 async function operate(op,extra=null){
  if(!view||!allowed(op,view,busy,emulationConsent)||actionGuard.current)return;
  if(op==='reset'&&!window.confirm('重置将创建新代次，保留旧进度和原盘。确认创建？'))return;
  actionGuard.current=true;setBusy(true);
  const parameters=extra||{prepare:{course_id:'host',baseline_id:'host'},start:{display:'headless',allow_emulation:view.runtime?.emulation_required===true&&emulationConsent},stop:{},reset:{baseline_id:'host'},recover:{},cancel:{operation_id:view.status.operation_id}}[op];
  const req=request(op,view,parameters,crypto.randomUUID(),crypto.randomUUID());lastRequest.current=req;
  try{const result=await call({action:'submit',request:req});setMessage(result.error?.message||'操作已记录。后台执行期间可关闭管理窗口。');await refresh();}
  catch(e){invalidate();setMessage('响应未取得。先读取状态或查询原请求，不会自动重发操作。');}
  finally{actionGuard.current=false;setBusy(false);}
 }
 async function retry(){if(!lastRequest.current||actionGuard.current)return;actionGuard.current=true;try{const v=await call({action:'query-request',request:lastRequest.current});setMessage(v.error?.message||(v.recorded?'原请求：'+(labels[v.response?.state]||v.response?.state||'结果待核对'):'暂未找到原请求；标识保留，不会自动重发。'));await refresh();}catch(e){setMessage(String(e.message||e));}finally{actionGuard.current=false;}}

 async function resumeDispatch(){
  if(!canResumeDispatch(view,busy)||actionGuard.current)return;
  if(!window.confirm('继续派发尚未开始执行的原请求？沿用原操作标识及取消标记；已开始执行的请求不会重放。'))return;
  const root=opened, original=view;
  actionGuard.current=true;setBusy(true);
  try{const result=await call({action:'resume-dispatch',instance_uuid:original.instance_uuid,operation_id:original.status.operation_id,state_revision:original.status.state_revision,attempt_id:crypto.randomUUID()},root);
   setMessage(result.error?.message||({ 'dispatch-requested':'已请求继续派发原操作，请读取当前状态。','dispatch-already-requested':'本次派发已登记，请先核对状态。','dispatch-unknown':'派发结果未知，原请求与现场已保留，请先读取状态。' }[result.state]||'请核对原请求当前状态。'));await refresh(root);
  }catch(e){setMessage('未取得派发结果。原请求仍保留，请读取当前状态后再决定。');}
  finally{actionGuard.current=false;setBusy(false);}
 }
 async function restartPreparation(){
  if(!canRestartPreparation(view,busy)||actionGuard.current)return;
  if(!window.confirm('保留首次准备的全部旧副本与记录，以新操作重新准备？只在尚无已选择运行代次且旧执行器已释放工作锁时允许；不会继续原未知操作。'))return;
  const root=opened, original=view.preparation;
  actionGuard.current=true;setBusy(true);
  try{const result=await call({action:'restart-preparation',instance_uuid:original.instance_uuid,operation_id:original.operation_id,state_revision:original.state_revision,attempt_id:crypto.randomUUID()},root);
   setMessage(result.error?.message||(result.result==='accepted'?'旧现场已保留，新准备请求已登记。请核对状态。':'结果待核对，旧现场保持保留；请先刷新状态。'));await refresh(root);
  }catch(e){setMessage('未取得重新准备结果，旧现场保留。请先刷新状态，不能把原未知操作当作未执行。');}
  finally{actionGuard.current=false;setBusy(false);}
 }
 async function rearmObserver(node){
  if(!canRearmObserver(view,node,busy)||actionGuard.current)return;
  if(!window.confirm('明确补建此节点的退出观测器？先核对当前进程与认证通道，只观察退出，不发送启动或关机命令。'))return;
  const root=opened, original=view;actionGuard.current=true;setBusy(true);
  try{const reply=await call({action:'rearm-observer',instance_uuid:original.instance_uuid,generation:original.generation,state_revision:original.status.state_revision,node,attempt_id:crypto.randomUUID()},root);
   setMessage(reply.error?.message||({'observer-ready':'退出观测器已绑定当前进程。','observer-exited':'取得已绑定进程的退出证据，请刷新状态。','unknown':'观测器结果未知，原现场保留；不会自动重试。'}[reply.state]||'请核对当前观测状态。'));await refresh(root);
  }catch(e){setMessage('观测器结果未取得，原现场保留，请先刷新状态。');}
  finally{actionGuard.current=false;setBusy(false);}
 }
 async function rearmLog(node){
  if(!canRearmLog(view,node,busy)||actionGuard.current)return;
  if(!window.confirm('明确重接此节点已登记的日志通道？仅启动日志接收器；旧片段保留，不重启或停止实验。接收器中断期间生产者可能因背压等待。'))return;
  const root=opened,original=view;actionGuard.current=true;setBusy(true);
  try{const reply=await call({action:'rearm-log',instance_uuid:original.instance_uuid,generation:original.generation,state_revision:original.status.state_revision,node,attempt_id:crypto.randomUUID()},root);
   setMessage(reply.error?.message||(reply.state==='log-receiver-requested'?'日志接收器已请求，历史缺口不会补写；请重新读取状态。':'结果待核对，原日志保留，不会自动重试。'));await refresh(root);
  }catch(e){setMessage('日志重接结果未取得，现场已保留；请重新读取状态，不会自动重发。');}
  finally{actionGuard.current=false;setBusy(false);}
 }
 async function display(node){try{const v=await call({action:'display',node});setMessage(v.error?.message||'显示连接已请求；关闭显示窗口后可再次打开。');}catch(e){setMessage(String(e));}}
 async function diagnostics(){try{setDiag(await call({action:'diagnostics'}));}catch(e){setMessage(String(e));}}
 function save(name,value){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();URL.revokeObjectURL(url);}
 function updateDraft(value){try{const checked=createGraphHistory(value).present;draftVersion.current++;setHistory(old=>editGraphHistory(old,checked));setDiff(null);}catch(e){setMessage(e.message);}}
 function moveDraft(redo){draftVersion.current++;setHistory(old=>(redo?redoGraphHistory:undoGraphHistory)(old));setDiff(null);}
 async function validateDraft(){const version=draftVersion.current;setDiff(null);try{const result=await call({action:"draft",manifest:JSON.parse(draft)});if(draftVersion.current===version)setDiff(result);}catch(e){setMessage(String(e.message||e));}}
 const nodes=view?.topology.nodes||[];
 const shownState=node=>overviewFresh(view)&&view.observations?.[node]?.identity==='verified'?view.observations[node].state:'unknown';
 return <div className="app"><aside><div className="brand"><span className="brand-mark" aria-hidden="true">C</span><b>CTFLab</b></div><p className="edition">本地实验工作台 <span>0.1.4 预览</span></p><nav aria-label="工作台导航">{['实验','拓扑','模板','远程','版本','诊断'].map(t=><button key={t} className={tab===t?'selected':''} onClick={()=>setTab(t)} aria-current={tab===t?'page':undefined}><NavIcon name={t}/>{t}</button>)}</nav><div className="appearance" role="group" aria-label="外观">{[['system','自动'],['light','浅色'],['dark','深色']].map(([value,label])=><button key={value} aria-pressed={appearance===value} onClick={()=>setAppearance(value)}>{label}</button>)}</div><div className="rail-note"><span className="dot"/> 本地运行<br/>关闭管理窗口后实验继续。<br/>原始镜像保持不变。</div></aside>
 <main><header><div><p className="eyebrow">CTFLab · 本地实验环境</p><h1>{tab==='实验'?'实验工作台':tab==='拓扑'?'网络拓扑':tab==='模板'?'场景模板':tab==='远程'?'远程实验':tab==='版本'?'版本管理':'诊断与支持'}</h1></div><div className="status-pill">{tab==='远程'?'远程管理':view?(view.execution?.identity==='running'?'正在后台执行':labels[view.status.state]||view.status.state):'未连接'}</div></header>
 {!['远程','版本'].includes(tab)&&<><section className="connect"><label htmlFor="run">实验目录</label><div className="inline"><input id="run" placeholder="填写一个新的绝对路径，或已有通用实例目录" value={run} onChange={e=>setRun(e.target.value)}/><button onClick={open} disabled={!run||busy}>打开 / 刷新</button></div><details><summary>导入离线课程（使用随包运行时）</summary><p>填写课程目录、课程标识及资产文件夹；多个变体时指定变体标识。仅在完整Windows安装资产中可用。</p>{Object.keys(course).map(k=><label key={k}>{({catalog:"课程目录 JSON",course_id:"课程标识",variant_id:"变体标识（单变体可留空）",asset_root:"资产文件夹"})[k]}<input value={course[k]} onChange={e=>setCourse({...course,[k]:e.target.value})}/></label>)}<button disabled={!run||!course.catalog||!course.course_id||!course.asset_root||busy} onClick={importCourse}>校验并导入课程</button></details><details><summary>高级：导入场景与宿主配置</summary><p>选择场景、资产与运行配置；UEFI场景还需NVRAM模板映射。此操作只建立新实例，不启动节点；已有目录不会覆盖。</p>{Object.keys(files).map(k=><label key={k}>{({manifest:'场景 JSON',assets:'资产映射 JSON',profile:'宿主运行配置 JSON',nvram:'NVRAM模板映射 JSON（UEFI场景需要）'})[k]}<input value={files[k]} onChange={e=>setFiles({...files,[k]:e.target.value})} placeholder="绝对路径"/></label>)}<button disabled={!run||!configurationReady(files,busy)||busy} onClick={configure}>导入新实验</button></details></section>
 <div className="notice" role="status">{message}{lastRequest.current&&<button className="link" onClick={retry}>查询原请求</button>}</div></>}
 {view&&!overviewFresh(view)&&<p className="notice" role="status">{view.freshness?.reason==='changed-during-sampling'?'采样期间实验已变化，请重新读取。':'状态已过期或采样不完整，请重新读取。'}图中保留设计信息，运行状态待核验。</p>}
 {tab==='实验'&&<><section className="toolbar"><div><span className="eyebrow">INSTANCE</span><h2>{view?(view.course?.title||view.instance_uuid.slice(0,8)):'等待打开实验'} <small>{view?`代次 ${view.generation}`:''}</small></h2></div><div className="actions">{[['prepare','准备实验'],['start','启动'],['stop','保存并停止'],['reset','整课重置'],['recover','恢复核验'],['cancel','取消']].map(([op,text])=><button key={op} disabled={!allowed(op,view,busy,emulationConsent)} className={op==='start'?'primary':''} onClick={()=>operate(op)}>{text}</button>)}</div></section>{canResumeDispatch(view,busy)&&<section className="notice"><p>原请求尚未被执行器领取。可明确继续派发，沿用原操作标识；刷新状态不会自动派发。</p><button disabled={busy} onClick={resumeDispatch}>继续派发原请求</button></section>}{canRestartPreparation(view,busy)&&<section className="notice"><p>首次准备未形成运行代次。可保留全部旧现场，以新操作重新准备；已有代次或启动记录时会拒绝。</p><button disabled={busy} onClick={restartPreparation}>保留现场，重新准备</button></section>}{view?.runtime?.emulation_required&&<label><input type="checkbox" checked={emulationConsent} onChange={e=>setEmulationConsent(e.target.checked)}/> 明确允许本课x86软件仿真（速度可能较慢）</label>}{!view&&<section className="empty-state"><NavIcon name="实验"/><h2>从一个实验开始</h2><p>打开已有实验目录，或导入离线课程。校验完成后，再准备独立运行副本。</p></section>}<div className="nodes">{nodes.map((n,i)=><article key={n.id}><div className="node-top"><span className="number">{String(i+1).padStart(2,'0')}</span><span className="node-state">{labels[shownState(n.id)]||'未观测'}</span></div><h3>{n.id}</h3>{["renewal-due","invalid","unknown"].includes(view.certificates?.[n.id]?.state)&&<p className="certificate-warning">{view.certificates[n.id].state==="renewal-due"?"连接证书即将到期，请在到期前保存并停止实验，再启动以更新证书。":view.certificates[n.id].state==="invalid"?"连接证书已失效，请保留现场并检查时间及证书记录。":"连接证书状态待核验。"}</p>}<p>{n.cpus} vCPU <span> / </span>{n.memory_mb} MiB</p><dl>{n.interfaces.map(nic=><React.Fragment key={nic.id}><dt>{nic.network}</dt><dd>{nic.planned_address} <em>设计地址</em></dd></React.Fragment>)}</dl>{(view.course?.entries||[]).filter(e=>e.node===n.id&&e.protocol!=="console").map(e=><p className="service-entry" key={e.protocol+e.port}>在实验节点内访问：<br/><code>{e.protocol}://{n.interfaces[0]?.planned_address}:{e.port}</code></p>)}{view.guest_agents?.[n.id]&&<details className="guest-controls"><summary>实验网络与容器</summary>{view.guest_agents[n.id].last_result&&<p>最近结果：{({"network-configured":"网络配置已写入，等待实测","services-running":"基础服务进程运行中","services-stopped":"基础服务已停止","containers-prepared":"容器已准备","containers-running":"容器进程运行中","containers-stopped":"容器已停止","analysis-completed":"分析过程已封存，结论待核验","analysis-failed":"分析未成功，输出已保留","observed":"已读取状态","failed":"操作失败，现场已保留","unknown":"结果待核对"})[view.guest_agents[n.id].last_result.state]||"请核对本轮记录"}</p>}<p>先配置网络并启动基础服务；容器使用本代次独立数据卷。操作结果不代表网络或课程已验收。</p><div className="actions">{[...(view.guest_agents[n.id].analysis?[["analysis-run","离线分析并封存"]]:[]),["network-apply","配置实验网络"],["services-start","启动DNS与时间"],["services-stop","停止基础服务"],["status","读取来宾状态"],...(view.guest_agents[n.id].containers?[["containers-prepare","准备容器"],["containers-start","启动容器"],["containers-stop","保存并停止容器"]]:[])].map(([action,label])=><button key={action} disabled={!allowed("guest",view,busy)} onClick={()=>operate("guest",{node:n.id,action})}>{label}</button>)}</div>{view.guest_agents[n.id].containers&&<GuestRecovery key={view.instance_uuid+':'+view.generation+':'+n.id} view={view} node={n.id} busy={busy} onOperate={operate} onError={setMessage}/>}</details>}<p>退出观测：{view.supervision?.[n.id]?.observer==='running'?'观测器进程已核验':'尚未确认'}</p><button disabled={!canRearmObserver(view,n.id,busy)} onClick={()=>rearmObserver(n.id)}>恢复退出观测</button>{view.supervision?.[n.id]?.logs?.kind==='posix-fifo-v1'&&<><p>日志接收：{view.supervision[n.id].logs.receiver==='lock-held'?'接收锁已占用':'尚未确认接收'} · 历史可能有缺口</p><button disabled={!canRearmLog(view,n.id,busy)} onClick={()=>rearmLog(n.id)}>重接日志接收器</button></>}<button onClick={()=>display(n.id)} disabled={shownState(n.id)!=='process-running'||view.runtime?.dependencies?.display===false}>打开 / 重连显示 <span>↗</span></button></article>)}</div><section className="timeline"><h2>持续监督历史</h2><p>以下为已保存的采样记录，不能证明现在仍在运行；读取不会启动监督或重放操作。</p>{view?.supervision_history?.unavailable?<p>历史记录暂不可核验，现场已保留。</p>:(view?.supervision_history?.watches||[]).slice(-16).reverse().map(w=><div className="event" key={w.operation_id}><code>{w.operation_id.slice(0,8)}</code><time>{w.sampled_at||'尚无采样'}</time><b>代次 {w.generation} · {w.ticks??0} 次</b><span>{w.coherent&&w.complete?'末次采样完整一致（历史）':'末次采样待核验（历史）'}</span></div>)}</section>{view&&<PreparationProgress view={view}/> }{opened&&view?.instance_uuid&&<OperationHistory key={opened+'|'+view.instance_uuid} root={opened} instance={view.instance_uuid}/>}<section className="timeline"><h2>操作时间线</h2>{events.length===0?<p>暂无本轮事件。状态刷新只读，不会重放操作。</p>:events.slice().reverse().map(e=><div className="event" key={e.event_id}><code>#{e.sequence}</code><time>{e.timestamp}</time><b>{labels[e.state]||e.state}</b><span>{e.stage}</span></div>)}</section></>}
 {tab==='拓扑'&&<section className="topology"><p>连线与地址来自当前计划。运行状态由现场查询取得；网络隔离和课程服务需单独验收。</p><div className="network-grid">{Object.entries(view?.topology.networks||{}).map(([name,n])=><div key={name} className="segment"><div className="segment-title">{name}<small>{n.cidr} · 无默认出口（设计）</small></div>{nodes.filter(node=>node.interfaces.some(i=>i.network===name)).map(node=><div className="segment-node" key={node.id}><b>{node.id}</b><span>{node.interfaces.find(i=>i.network===name).planned_address}</span><em>{labels[shownState(node.id)]||'未观测'}</em></div>)}</div>)}</div><p className="verification">网络隔离：待实测 · 课程完成：待验收</p></section>}
 {tab==='拓扑'&&opened&&<ExternalAttach root={opened} call={call} busy={busy} onMessage={setMessage}/>}
 {tab==='模板'&&<section><div className="actions"><button disabled={!history.past.length} onClick={()=>moveDraft(false)}>撤销配置</button><button disabled={!history.future.length} onClick={()=>moveDraft(true)}>重做配置</button><small>保留最近20步配置编辑；布局单独导出</small></div><GraphEditor source={draft} onChange={updateDraft} onError={setMessage}/><p>编辑完整场景清单，检查连接、地址、依赖和变更差异。导出草稿后用新实例导入，运行中的实验不会修改。导出草稿不是可执行模板；发布可执行模板须通过具体场景验收并绑定草稿摘要。清单有效也不代表当前后端支持全部组合。</p><textarea aria-label="场景草稿 JSON" rows="16" value={draft} onChange={e=>updateDraft(e.target.value)}/><div className="actions"><button disabled={!view} onClick={()=>updateDraft(JSON.stringify(view.manifest,null,2))}>载入当前清单</button><button disabled={!view||!draft} onClick={validateDraft}>校验差异</button><button disabled={!diff||diff.error} onClick={()=>save('ctflab-scenario-draft.json',diff.manifest)}>导出已校验草稿</button></div>{diff&&<pre>{JSON.stringify(diff,null,2)}</pre>}</section>}
 {tab==='远程'&&<RemoteWorkspace/>}
 {tab==='版本'&&<Versions/>}
 {tab==='诊断'&&<section><p>只生成节点数量、宿主类型和运行阶段等白名单摘要。先预览，再保存；不会自动上传。</p><button disabled={!view} onClick={diagnostics}>生成诊断预览</button>{diag&&<><pre>{JSON.stringify(diag,null,2)}</pre><button disabled={!diag.preview} onClick={()=>save('ctflab-diagnostics.json',diag.preview)}>保存此预览</button></>}</section>}
 <footer><span>CTFLab / {view?.runtime?.host==='darwin-arm64'?'Mac ARM / x86仿真':'Windows / Linux 通用运行器'}</span><span>真实来宾、干净机与课程验收独立记录</span></footer></main></div>;
}
createRoot(document.getElementById('root')).render(<App/>);
