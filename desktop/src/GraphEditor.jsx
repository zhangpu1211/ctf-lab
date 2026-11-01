import React,{useRef,useState,useLayoutEffect}from'react';
import{fromManifest,toManifest,connect,disconnect,addNode,removeNode,addNetwork,resources,dependencies,removeNetwork,layoutKeys,layoutPoint,layoutPositions,importLayout,exportLayout}from'./graph-model.mjs';

export default function GraphEditor({source,onChange,onError}){
 const drag=useRef(null),[name,setName]=useState(''),[asset,setAsset]=useState(''),[network,setNetwork]=useState(''),[cidr,setCidr]=useState('');
 const moving=useRef(null),scenario=useRef(null),latestSource=useRef(source),[layout,setLayout]=useState({}),[heights,setHeights]=useState({}),[layoutNotice,setLayoutNotice]=useState('');latestSource.current=source;
 const board=useRef(null),[geometry,setGeometry]=useState({paths:[],box:'0 0 1 1'});
 useLayoutEffect(()=>{
  try{const m=toManifest(fromManifest(JSON.parse(source))),keys=new Set(layoutKeys(m));
   moving.current=null;
   const sameScenario=scenario.current===m.scenario_id;scenario.current=m.scenario_id;
   setLayout(old=>{const next=sameScenario?Object.fromEntries(Object.entries(old).filter(([k])=>keys.has(k))):{};return JSON.stringify(old)===JSON.stringify(next)?old:next;});
  }catch{moving.current=null;}
 },[source]);
 useLayoutEffect(()=>{
  const element=board.current;if(!element)return;
  function measure(){
   const measured=Object.fromEntries([...element.querySelectorAll('[data-layout-key]')].map(e=>[e.dataset.layoutKey,e.getBoundingClientRect().height]));
   setHeights(old=>JSON.stringify(old)===JSON.stringify(measured)?old:measured);
   const bounds=element.getBoundingClientRect();let edges=[];try{edges=fromManifest(JSON.parse(source)).connections;}catch{return;}
   const anchors=new Map([...element.querySelectorAll('[data-anchor]')].map(e=>[e.dataset.anchor,e]));
   const targets=new Map([...element.querySelectorAll('[data-network]')].map(e=>[e.dataset.network,e]));
   const paths=edges.flatMap(e=>{const a=anchors.get(e.node+'/'+e.id)?.getBoundingClientRect(),b=targets.get(e.network)?.getBoundingClientRect();if(!a||!b)return[];const x=a.right-bounds.left,y=a.top+a.height/2-bounds.top,tx=b.left-bounds.left,ty=b.top+25-bounds.top;return[`M ${x} ${y} C ${x+35} ${y}, ${tx-35} ${ty}, ${tx} ${ty}`];});
   const next={paths,box:`0 0 ${Math.max(1,bounds.width)} ${Math.max(1,bounds.height)}`};
   setGeometry(old=>JSON.stringify(old)===JSON.stringify(next)?old:next);
  }
  measure();const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(measure);observer?.observe(element);element.querySelectorAll('[data-layout-key]').forEach(e=>observer?.observe(e));window.addEventListener('resize',measure);
  return()=>{observer?.disconnect();window.removeEventListener('resize',measure);};
 },[source,layout,heights]);
 let graph,manifest;
 try{if(new TextEncoder().encode(source).length>65536)throw Error('草稿超过界面编辑容量');graph=fromManifest(JSON.parse(source));manifest=toManifest(graph);}catch(e){return<p className="draft-hint">载入完整场景清单后可编辑连接。{source?' 当前文本尚不能显示为图。':''}</p>;}
 const nodes=Object.entries(manifest.nodes),segments=Object.entries(manifest.networks),positions=layoutPositions(manifest,layout,heights);
 const extent={width:Math.max(800,...Object.values(positions).map(p=>p.x+340)),height:Math.max(380,...Object.entries(positions).map(([k,p])=>p.y+(heights[k]||400)+24))};
 const placement=key=>({left:positions[key].x,top:positions[key].y});
 function setPoint(key,point){setLayout(old=>({...old,[key]:point}));}
 function grip(key,label){return <button className="layout-grip" aria-label={'移动'+label} title="拖动移动；方向键移动10，Shift加速" onPointerDown={e=>{
  if(e.button!==0||!e.isPrimary||moving.current)return;e.preventDefault();const scroll=board.current.parentElement;
  moving.current={key,id:e.pointerId,x:e.clientX,y:e.clientY,start:positions[key],scrollX:scroll.scrollLeft,scrollY:scroll.scrollTop};e.currentTarget.setPointerCapture(e.pointerId);
 }} onPointerMove={e=>{const move=moving.current;if(!move||move.id!==e.pointerId)return;const scroll=board.current.parentElement;
  setPoint(key,layoutPoint(move.start.x+e.clientX-move.x+scroll.scrollLeft-move.scrollX,move.start.y+e.clientY-move.y+scroll.scrollTop-move.scrollY));
 }} onPointerUp={e=>{if(moving.current?.id===e.pointerId){moving.current=null;setLayoutNotice('布局已调整，仅影响草稿显示。');}}}
 onPointerCancel={e=>{if(moving.current?.id===e.pointerId){setPoint(key,moving.current.start);moving.current=null;}}}
 onLostPointerCapture={e=>{if(moving.current?.id===e.pointerId){setPoint(key,moving.current.start);moving.current=null;}}}
 onKeyDown={e=>{const delta={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[e.key];if(!delta)return;e.preventDefault();const step=e.shiftKey?50:10;
  setPoint(key,layoutPoint(positions[key].x+delta[0]*step,positions[key].y+delta[1]*step));setLayoutNotice('布局已调整，仅影响草稿显示。');}}>⠿ {label}</button>;}
 function saveLayout(){try{const content=JSON.stringify(exportLayout(manifest,positions),null,2),url=URL.createObjectURL(new Blob([content],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='ctflab-graph-layout.json';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);setLayoutNotice('已导出布局文件，实验配置保持原样。');
 }catch(e){onError(e.message);}}
 async function loadLayout(event){const file=event.target.files?.[0];event.target.value='';if(!file)return;const original=source;
  try{if(file.size>65536)throw Error('布局文件过大');const text=await file.text();if(latestSource.current!==original)throw Error('草稿已改变，请重新选择布局文件');setLayout(importLayout(manifest,text));setLayoutNotice('已载入布局，实验配置保持原样。');}catch(e){onError(e.message);}}

 function apply(fn){try{onChange(JSON.stringify(fn(manifest),null,2));}catch(e){onError(e.message);}}
 function start(event,node,nic){drag.current={node,nic};event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain','CTFLab草稿连接');}
 function drop(event,target){event.preventDefault();const value=drag.current;drag.current=null;if(value)apply(m=>connect(m,value.node,value.nic,target));}
 return<section className="graph-editor"><h2>图形草稿 <small>拖动标题调整布局；拖动网卡到网段，或使用下拉框连接</small></h2><div className="actions"><button onClick={()=>{moving.current=null;setLayout({});setLayoutNotice("已恢复自动布局。");}}>自动排列</button><button onClick={saveLayout}>导出布局</button><label className="layout-import">载入布局<input type="file" accept="application/json,.json" onChange={loadLayout}/></label></div><p className="sr-only" aria-live="polite">{layoutNotice}</p><p>图中的连接只属于草稿。断开最后一张网卡会使草稿待补全，完整校验通过后才能导出。</p>
 <div className="graph-scroll"><div className="graph-board graph-canvas" ref={board} style={extent}><svg className="graph-edges" viewBox={geometry.box} role="img" aria-label="草稿中的节点网卡与网段连接"><title>设计连接，不代表实测可达</title>{geometry.paths.map((d,i)=><path key={i} d={d}/>)}</svg><div className="graph-nodes">{nodes.map(([node,spec])=><article key={node} className="graph-node" data-layout-key={"node:"+node} style={placement("node:"+node)}><header>{grip("node:"+node,node)}<button onClick={()=>apply(m=>removeNode(m,node))} aria-label={'移除草稿节点'+node}>移除</button></header><div className="graph-resources"><label>{node} CPU<select value={spec.cpus} onChange={e=>apply(m=>resources(m,node,Number(e.target.value),spec.memory_mb))}>{Array.from({length:64},(_,i)=><option key={i+1} value={i+1}>{i+1}</option>)}</select></label><label>{node} 内存 MiB<select value={spec.memory_mb} onChange={e=>apply(m=>resources(m,node,spec.cpus,Number(e.target.value)))}>{[...new Set([256,512,1024,2048,4096,8192,16384,32768,65536,131072,262144,spec.memory_mb])].sort((a,b)=>a-b).map(n=><option key={n} value={n}>{n}</option>)}</select></label></div><details><summary>启动依赖（{spec.depends_on.length}）</summary>{nodes.filter(([id])=>id!==node).map(([id])=><label key={id}><input type="checkbox" checked={spec.depends_on.includes(id)} onChange={e=>apply(m=>dependencies(m,node,e.target.checked?[...spec.depends_on,id]:spec.depends_on.filter(n=>n!==id)))}/>{id}</label>)}</details>{spec.interfaces.map(nic=><div className="graph-nic" key={nic.id}><button data-anchor={node+'/'+nic.id} draggable onDragStart={e=>start(e,node,nic.id)} onDragEnd={()=>drag.current=null}>{nic.id} ↗</button><label><span className="sr-only">{node+'/'+nic.id+'连接网段'}</span><select value={nic.network} onChange={e=>apply(m=>connect(m,node,nic.id,e.target.value))}>{segments.map(([id])=><option key={id}>{id}</option>)}</select></label><button aria-label={'断开'+node+'/'+nic.id} onClick={()=>apply(m=>disconnect(m,node,nic.id))}>断开</button><small>{nic.address} · 设计地址</small></div>)}<button draggable onDragStart={e=>start(e,node,null)} onDragEnd={()=>drag.current=null}>拖动新增网卡 ↗</button><label className="add-nic"><span>或选择网段新增网卡</span><select value="" onChange={e=>{if(e.target.value)apply(m=>connect(m,node,null,e.target.value));}}><option value="">选择网段</option>{segments.map(([id])=><option key={id}>{id}</option>)}</select></label></article>)}</div>
 <div className="graph-segments">{segments.map(([id,spec])=><div className="graph-segment" data-network={id} data-layout-key={"network:"+id} style={placement("network:"+id)} key={id} onDragOver={e=>{if(drag.current)e.preventDefault();}} onDrop={e=>drop(e,id)}>{grip("network:"+id,id)}<button disabled={graph.connections.some(e=>e.network===id)} onClick={()=>apply(m=>removeNetwork(m,id))}>移除空闲草稿网段</button><p>{spec.cidr}</p><small>拖放目标 · 无默认出口（设计）</small><ul>{graph.connections.filter(e=>e.network===id).map(e=><li key={e.node+'/'+e.id}>{e.node} / {e.id}</li>)}</ul></div>)}</div></div></div>
 <div className="graph-add"><label>新节点标识<input value={name} onChange={e=>setName(e.target.value)} placeholder="如 analysis"/></label><label>已有资产<select value={asset} onChange={e=>setAsset(e.target.value)}><option value="">选择资产</option>{Object.keys(manifest.assets||{}).map(id=><option key={id}>{id}</option>)}</select></label><button disabled={!name||!asset} onClick={()=>apply(m=>addNode(m,name,asset))}>添加草稿节点</button></div>
 <div className="graph-add"><label>新网段标识<input value={network} onChange={e=>setNetwork(e.target.value)} placeholder="如 analysis-net"/></label><label>设计网段<input value={cidr} onChange={e=>setCidr(e.target.value)} placeholder="10.90.0.0/24"/></label><button disabled={!network||!cidr} onClick={()=>apply(m=>addNetwork(m,network,cidr))}>添加草稿网段</button></div></section>;
}
