import test from'node:test';import assert from'node:assert/strict';
import{fromManifest,toManifest,connect,disconnect,addNode,removeNode,addNetwork}from'./graph-model.mjs';
const fixture=()=>({schema:2,scenario_id:'draft',assets:{linux:{architecture:'x86_64',sha256:'a'.repeat(64),source:'fixture',license:'synthetic',verification:'unverified'}},policy:{internet:false,host_forwards:[],failure:'preserve'},networks:{outer:{cidr:'10.80.0.0/24',uplink:'none'},inner:{cidr:'10.81.0.0/24',uplink:'none'}},nodes:{client:{asset:'linux',cpus:1,memory_mb:512,firmware:'bios',disk_bus:'ide',depends_on:[],interfaces:[{id:'eth0',network:'outer',address:'10.80.0.10',mac:'derived',model:'e1000'}]}}});
test('图与清单往返保留硬件、许可、依赖、地址和网卡顺序',()=>{const value=fixture();assert.deepEqual(toManifest(fromManifest(value)),value);});
test('重新连接只修改草稿并分配未占用的设计地址',()=>{const old=fixture();const changed=connect(old,'client','eth0','inner');assert.equal(old.nodes.client.interfaces[0].network,'outer');assert.equal(changed.nodes.client.interfaces[0].network,'inner');assert.equal(changed.nodes.client.interfaces[0].address,'10.81.0.1');});
test('新增网卡拒绝重复网段，断开允许形成待补全草稿',()=>{let value=connect(fixture(),'client',null,'inner');assert.equal(value.nodes.client.interfaces.length,2);assert.throws(()=>connect(value,'client',null,'inner'));value=disconnect(value,'client','eth1');value=disconnect(value,'client','eth0');assert.deepEqual(value.nodes.client.interfaces,[]);});
test('新增节点保留原件并按资产架构选择声明，移除清理草稿依赖',()=>{const base=fixture();let value=addNode(base,'analysis','linux');assert.equal(value.nodes.analysis.firmware,'bios');assert.deepEqual(value.nodes.analysis.interfaces,[]);value.nodes.client.depends_on=['analysis'];value=removeNode(value,'analysis');assert.deepEqual(value.nodes.client.depends_on,[]);assert.equal(Object.keys(base.nodes).length,1);});
test('网段重叠、公共地址、原型键和未知引用拒绝',()=>{const value=fixture();assert.throws(()=>addNetwork(value,'new','10.80.0.0/25'));assert.throws(()=>addNetwork(value,'new','8.8.8.0/24'));assert.throws(()=>addNode(value,'__proto__','linux'));assert.throws(()=>connect(value,'missing',null,'outer'));assert.equal(addNetwork(value,'new','10.90.0.0/24').networks.new.uplink,'none');});
test('图连接不能引用已删除节点',()=>{const graph=fromManifest(fixture());delete graph.base.nodes.client;assert.throws(()=>toManifest(graph));});

test('资源编辑只改变草稿，遵守生产CPU和内存边界',async()=>{
 const {resources}=await import('./graph-model.mjs');const base=fixture(),value=resources(base,'client',64,262144);
 assert.equal(value.nodes.client.cpus,64);assert.equal(base.nodes.client.cpus,1);assert.deepEqual(value.assets,base.assets);
 for(const [cpu,mem]of [[0,512],[65,512],[1.1,512],[1,255],[1,262145],[true,512]])assert.throws(()=>resources(base,'client',cpu,mem));
});
test('启动依赖拒绝自引、重复、缺失和间接循环，失败保留原草稿',async()=>{
 const {dependencies}=await import('./graph-model.mjs');let base=addNode(addNode(fixture(),'middle','linux'),'server','linux');
 base=dependencies(base,'client',['middle']);base=dependencies(base,'middle',['server']);
 assert.throws(()=>dependencies(base,'server',['client']));assert.deepEqual(base.nodes.server.depends_on,[]);
 for(const selected of [['client'],['missing'],['middle','middle']])assert.throws(()=>dependencies(base,'client',selected));
 assert.deepEqual(dependencies(base,'client',[]).nodes.client.depends_on,[]);
});
test('移除空闲网段不删除或隐式断开任何连接',async()=>{
 const {removeNetwork}=await import('./graph-model.mjs');const base=fixture();assert.throws(()=>removeNetwork(base,'outer'));
 const value=removeNetwork(base,'inner');assert.equal(value.networks.inner,undefined);assert.ok(base.networks.inner);assert.deepEqual(value.nodes,base.nodes);
});

test('布局旁车可往返，不修改执行清单、网卡或许可',async()=>{
 const {layoutPositions,exportLayout,importLayout}=await import('./graph-model.mjs');const base=fixture(),before=structuredClone(base);
 const positions=layoutPositions(base,{'node:client':{x:788,y:900}}),sidecar=exportLayout(base,positions);
 assert.deepEqual(importLayout(base,JSON.stringify(sidecar)),positions);assert.deepEqual(base,before);
 assert.equal(positions['network:outer'].x,430);assert.equal(sidecar.assets,undefined);
});
test('布局拒绝其他草稿、缺失/外来元素、越界/非整数和未知字段',async()=>{
 const {layoutPositions,exportLayout,importLayout}=await import('./graph-model.mjs');const base=fixture(),value=exportLayout(base,layoutPositions(base));
 for(const change of [v=>v.scope.scenario_id='foreign',v=>delete v.positions['node:client'],v=>v.positions['node:foreign']={x:0,y:0},v=>v.positions['node:client'].x=-1,v=>v.positions['node:client'].y=32001,v=>v.positions['node:client'].x=.1,v=>v.positions['node:client'].extra=true,v=>v.extra=true]){
  const bad=structuredClone(value);change(bad);assert.throws(()=>importLayout(base,JSON.stringify(bad)));}
 assert.throws(()=>importLayout(base,' '.repeat(65537)));
});
test('布局移动夹紧边界，按实际卡片高度自动排列',async()=>{
 const {layoutPoint,layoutPositions}=await import('./graph-model.mjs');assert.deepEqual(layoutPoint(-10,1e6),{x:0,y:32000});assert.throws(()=>layoutPoint(NaN,1));
 const points=layoutPositions(fixture(),{}, {'network:outer':180});assert.equal(points['network:inner'].y,228);
});

test('配置撤销重做保留精确原文，新编辑清空重做且历史最多20步',async()=>{
 const {createGraphHistory,editGraphHistory,undoGraphHistory,redoGraphHistory}=await import('./graph-model.mjs');
 let history=createGraphHistory('原始文本');history=editGraphHistory(history,'下一步');const old=history;history=undoGraphHistory(history);
 assert.equal(history.present,'原始文本');assert.equal(old.present,'下一步');assert.equal(redoGraphHistory(history).present,'下一步');
 history=editGraphHistory(history,'新分支');assert.equal(history.future.length,0);
 for(let i=0;i<40;i++)history=editGraphHistory(history,'第'+i+'步');assert.equal(history.past.length,20);
 for(let i=0;i<40;i++)history=undoGraphHistory(history);assert.equal(history.future.length,20);
 assert.throws(()=>editGraphHistory(history,'字'.repeat(22000)));assert.equal(history.future.length,20);
});
