// 图形编辑只改变草稿；完整执行校验仍由本地后端完成。
const clone=value=>structuredClone(value);
function check(value,message='草稿结构无效'){if(!value)throw Error(message);}
function id(value){check(typeof value==='string'&&/^[a-z][a-z0-9-]{0,47}$/.test(value),'标识仅支持小写字母、数字与连字符');}
export function subnet(cidr){
 check(typeof cidr==='string');const parts=cidr.split('/');check(parts.length===2&&/^\d+$/.test(parts[1]));
 const bytes=parts[0].split('.');check(bytes.length===4&&bytes.every(b=>/^(0|[1-9]\d{0,2})$/.test(b)&&Number(b)<=255));
 const prefix=Number(parts[1]);check(String(prefix)===parts[1]&&prefix>=16&&prefix<=30,'网段长度须为 /16 至 /30');
 const address=bytes.reduce((n,b)=>n*256+Number(b),0);const size=2**(32-prefix);check(address%size===0,'请输入网段地址');
 const privateAddress=Number(bytes[0])===10||Number(bytes[0])===172&&Number(bytes[1])>=16&&Number(bytes[1])<=31||Number(bytes[0])===192&&Number(bytes[1])===168;
 check(privateAddress,'只支持私有实验网段');return{address,size,first:address+1,last:address+size-2};
}
const ip=n=>[24,16,8,0].map(shift=>Math.floor(n/2**shift)%256).join('.');
export function fromManifest(manifest){
 check(manifest&&manifest.schema===2&&manifest.nodes&&manifest.networks);
 check(Object.keys(manifest.nodes).length<=32&&Object.keys(manifest.networks).length<=16);
 Object.keys(manifest.nodes).forEach(id);Object.keys(manifest.networks).forEach(id);
 const base=clone(manifest),connections=[];
 for(const [node,spec]of Object.entries(base.nodes)){
  check(Array.isArray(spec.interfaces)&&spec.interfaces.length<=8);
  spec.interfaces.forEach((nic,order)=>{check(nic&&Object.keys(nic).sort().join(',')==='address,id,mac,model,network','网卡含未知字段');id(nic.id);connections.push({...clone(nic),node,order});});delete spec.interfaces;
 }
 return{kind:'ctflab-graph-draft-v1',base,connections};
}
export function toManifest(graph){
 check(graph?.kind==='ctflab-graph-draft-v1'&&Array.isArray(graph.connections));
 const value=clone(graph.base);
 for(const node of Object.keys(value.nodes)){
  const edges=graph.connections.filter(e=>e.node===node).sort((a,b)=>a.order-b.order);
  check(edges.every((e,index)=>e.order===index),'网卡顺序无效');
  value.nodes[node].interfaces=edges.map(({node,order,...nic})=>clone(nic));
 }
 check(graph.connections.every(e=>Object.hasOwn(value.nodes,e.node)),'连接引用了不存在的节点');
 return value;
}
export function connect(manifest,node,nic,network){
 const value=clone(manifest);check(Object.hasOwn(value.nodes,node)&&Object.hasOwn(value.networks,network));
 const spec=value.nodes[node];check(Array.isArray(spec.interfaces));
 check(!spec.interfaces.some(i=>i.network===network&&i.id!==nic),'该节点已连接此网段');
 const old=spec.interfaces.find(i=>i.id===nic);if(old?.network===network)return value;
 if(nic===null){let n=0;while(spec.interfaces.some(i=>i.id==='eth'+n))n++;nic='eth'+n;check(spec.interfaces.length<8,'最多8张网卡');}
 else check(Boolean(old),'网卡不存在');
 const block=subnet(value.networks[network].cidr),used=new Set(Object.values(value.nodes).flatMap(n=>n.interfaces.map(i=>i.address)));
 let address=block.first;while(address<=block.last&&used.has(ip(address)))address++;
 check(address<=block.last,'该网段没有空闲设计地址');
 const arch=value.assets[spec.asset]?.architecture;
 const entry={...(old||{id:nic,mac:'derived',model:arch==='aarch64'?'virtio-net-pci':'e1000'}),network,address:ip(address)};
 if(old)spec.interfaces=spec.interfaces.map(i=>i.id===nic?entry:i);else spec.interfaces.push(entry);
 return value;
}
export function disconnect(manifest,node,nic){
 const value=clone(manifest);check(Object.hasOwn(value.nodes,node));
 check(value.nodes[node].interfaces.some(i=>i.id===nic));
 value.nodes[node].interfaces=value.nodes[node].interfaces.filter(i=>i.id!==nic);
 return value;
}
export function addNode(manifest,name,asset){
 id(name);check(!Object.hasOwn(manifest.nodes,name)&&Object.hasOwn(manifest.assets,asset)&&Object.keys(manifest.nodes).length<32);
 const value=clone(manifest),arm=value.assets[asset].architecture==='aarch64';
 Object.defineProperty(value.nodes,name,{value:{asset,cpus:1,memory_mb:512,firmware:arm?'uefi':'bios',disk_bus:arm?'virtio':'ide',interfaces:[],depends_on:[]},enumerable:true,writable:true,configurable:true});
 return value;
}
export function removeNode(manifest,name){
 const value=clone(manifest);check(Object.hasOwn(value.nodes,name));delete value.nodes[name];
 for(const node of Object.values(value.nodes))node.depends_on=node.depends_on.filter(n=>n!==name);
 return value;
}
export function addNetwork(manifest,name,cidr){
 id(name);check(!Object.hasOwn(manifest.networks,name)&&Object.keys(manifest.networks).length<16);
 const candidate=subnet(cidr);for(const n of Object.values(manifest.networks)){const old=subnet(n.cidr);check(candidate.last<old.address||old.last<candidate.address,'实验网段不能重叠');}
 const value=clone(manifest);Object.defineProperty(value.networks,name,{value:{cidr,uplink:'none'},enumerable:true,writable:true,configurable:true});return value;
}

export function resources(manifest,node,cpus,memory){
 check(Object.hasOwn(manifest.nodes,node),'节点不存在');
 check(Number.isInteger(cpus)&&cpus>=1&&cpus<=64&&Number.isInteger(memory)&&memory>=256&&memory<=262144,'CPU须为1至64，内存须为256至262144 MiB的整数');
 const value=clone(manifest);value.nodes[node].cpus=cpus;value.nodes[node].memory_mb=memory;return value;
}
export function dependencies(manifest,node,selected){
 check(Object.hasOwn(manifest.nodes,node)&&Array.isArray(selected),'依赖结构无效');
 check(new Set(selected).size===selected.length&&selected.every(n=>n!==node&&Object.hasOwn(manifest.nodes,n)),'依赖不能重复、引用自身或缺失节点');
 const value=clone(manifest);value.nodes[node].depends_on=[...selected].sort();
 const remaining=new Set(Object.keys(value.nodes)),done=new Set();
 while(remaining.size){const ready=[...remaining].filter(n=>Array.isArray(value.nodes[n].depends_on)&&value.nodes[n].depends_on.every(d=>done.has(d)));check(ready.length,'启动依赖形成循环或引用无效');for(const n of ready){remaining.delete(n);done.add(n);}}
 return value;
}
export function removeNetwork(manifest,name){
 check(Object.hasOwn(manifest.networks,name),'网段不存在');
 check(!Object.values(manifest.nodes).some(n=>n.interfaces.some(i=>i.network===name)),'先断开该网段的全部草稿连接');
 const value=clone(manifest);delete value.networks[name];return value;
}

// 布局旁车不进入执行清单；只接受当前草稿中的已知元素和有界整数坐标。
export function layoutScope(manifest){
 fromManifest(manifest);check(typeof manifest.scenario_id==='string','草稿标识缺失');
 return {scenario_id:manifest.scenario_id,nodes:Object.keys(manifest.nodes).sort(),networks:Object.keys(manifest.networks).sort()};
}
export function layoutKeys(manifest){return [...Object.keys(manifest.nodes).map(id=>'node:'+id),...Object.keys(manifest.networks).map(id=>'network:'+id)];}
export function layoutPoint(x,y){
 check(Number.isFinite(x)&&Number.isFinite(y),'布局坐标无效');
 return {x:Math.max(0,Math.min(4000,Math.round(x))),y:Math.max(0,Math.min(32000,Math.round(y)))};
}
export function layoutPositions(manifest,saved={},heights={}){
 const result={};
 for(const [kind,names,x]of [['node',Object.keys(manifest.nodes),24],['network',Object.keys(manifest.networks),430]]){
  let y=24;
  for(const name of names){const key=kind+':'+name;result[key]=Object.hasOwn(saved,key)?layoutPoint(saved[key].x,saved[key].y):{x,y};
   const height=heights[key];y+=Number.isFinite(height)&&height>0&&height<=4096?Math.ceil(height)+24:424;}
 }
 return result;
}
export function exportLayout(manifest,positions){
 const keys=layoutKeys(manifest);check(Object.keys(positions).length===keys.length&&keys.every(k=>Object.hasOwn(positions,k)),'布局元素不匹配');
 const result={schema:1,kind:'ctflab-graph-layout',scope:layoutScope(manifest),positions:{}};
 for(const key of keys){const point=positions[key];check(point&&Object.keys(point).sort().join(',')==='x,y');
  check(Number.isInteger(point.x)&&point.x>=0&&point.x<=4000&&Number.isInteger(point.y)&&point.y>=0&&point.y<=32000,'布局坐标超出范围');result.positions[key]={...point};}
 return result;
}
export function importLayout(manifest,text){
 check(typeof text==='string'&&new TextEncoder().encode(text).length<=65536,'布局文件过大');
 const value=JSON.parse(text);check(value&&Object.keys(value).sort().join(',')==='kind,positions,schema,scope'&&value.schema===1&&value.kind==='ctflab-graph-layout','布局文件格式无效');
 const expected=layoutScope(manifest);check(value.scope&&Object.keys(value.scope).sort().join(',')==='networks,nodes,scenario_id'&&value.scope.scenario_id===expected.scenario_id&&JSON.stringify(value.scope.nodes)===JSON.stringify(expected.nodes)&&JSON.stringify(value.scope.networks)===JSON.stringify(expected.networks),'布局不属于当前草稿');
 check(value.positions&&typeof value.positions==='object'&&!Array.isArray(value.positions),'布局坐标无效');
 return exportLayout(manifest,value.positions).positions;
}

// 最近20步配置编辑历史；布局旁车独立，不写入运行实例。
export function createGraphHistory(source){check(typeof source==='string'&&new TextEncoder().encode(source).length<=65536,'配置草稿超过64KiB，原草稿已保留');return {past:[],present:source,future:[]};}
export function editGraphHistory(history,next){createGraphHistory(next);if(history.present===next)return history;return {past:[...history.past,history.present].slice(-20),present:next,future:[]};}
export function undoGraphHistory(history){if(!history.past.length)return history;return {past:history.past.slice(0,-1),present:history.past.at(-1),future:[history.present,...history.future].slice(0,20)};}
export function redoGraphHistory(history){if(!history.future.length)return history;return {past:[...history.past,history.present].slice(-20),present:history.future[0],future:history.future.slice(1)};}
