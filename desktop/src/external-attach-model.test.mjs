import test from 'node:test';
import assert from 'node:assert/strict';
import {defaultRegistrationForm,registrationFromForm,validateRegistration,validateForm,
        slotSummary,statusView,cliConnectHint,sessionView,diagnosticsView,isAbsoluteHostPath} from './external-attach-model.mjs';

const goodForm=()=>({...defaultRegistrationForm(),name:'教室Kali',
  machine_uuid:'0d1f7e57-7b1e-4c8e-9c8d-2f1a3b4c5d60',identity:'/Users/s/.ssh/kali',
  assistant_sha256:'a'.repeat(64)});

test('完整登记表单通过并生成契约形状的登记',()=>{
  const form=goodForm();
  assert.equal(validateForm(form),null);
  const registration=registrationFromForm(form);
  assert.equal(registration.schema,1);
  assert.equal(registration.kind,'kali-l2-v1');
  assert.equal(registration.ssh.port,22);
  assert.equal(registration.assistant_sha256,'a'.repeat(64));
});

test('缺失私钥/坏UUID/坏摘要/坏SSH字段被拒绝',()=>{
  assert.match(validateForm({...goodForm(),name:''}),/名称/);
  assert.match(validateForm({...goodForm(),machine_uuid:'nope'}),/UUID/);
  assert.match(validateForm({...goodForm(),assistant_sha256:'xyz'}),/64位/);
  assert.match(validateForm({...goodForm(),identity:'relative/path'}),/绝对路径/);
  assert.match(validateForm({...goodForm(),host:'a b'}),/SSH地址/);
  assert.match(validateForm({...goodForm(),port:'0'}),/端口/);
  assert.match(validateRegistration(null),/不完整/);
});

test('无预留槽位时如实说明且不虚构可用性',()=>{
  const summary=slotSummary([]);
  assert.equal(summary.available,false);
  assert.match(summary.note,/不热改/);
});

test('槽位预览展示静态地址与MAC',()=>{
  const summary=slotSummary([{network:'lab0',address:'192.168.50.9',mac:'02:aa:bb:cc:dd:ee'}]);
  assert.equal(summary.available,true);
  assert.ok(summary.items[0].label.includes('192.168.50.9'));
});

test('计划或代次变化时登记标记过期',()=>{
  const view=statusView({state:'external-attach-status',binding:{plan_sha256:'x'},binding_valid:false,
    slots:[],connect_supported:false,note:''});
  assert.equal(view.binding.stale,true);
});

test('无预留口或未登记时连接不可用',()=>{
  const view=statusView({state:'external-attach-status',binding_valid:true,binding:{},
    slots:[{network:'lab0',address:'192.168.50.9',mac:'02:aa:bb:cc:dd:ee'}],
    connect_supported:false,session:{state:'idle'},note:''});
  assert.equal(view.ready,true);
  assert.equal(view.connect,false);
  assert.equal(view.canConnect,false);
});

test('状态未取得时不可用',()=>{
  assert.equal(statusView(null).ready,false);
});

test('会话门控：仅idle/disconnected/unknown可连接，connecting/connected可断开',()=>{
  assert.equal(sessionView({state:'idle'}).canConnect,true);
  assert.equal(sessionView({state:'disconnected'}).canConnect,true);
  assert.equal(sessionView({state:'unknown'}).canConnect,true);
  assert.equal(sessionView({state:'connecting'}).canConnect,false);
  assert.equal(sessionView({state:'connected'}).canDisconnect,true);
  assert.equal(sessionView({state:'connecting'}).canDisconnect,true);
  assert.equal(sessionView(null).state,'idle');
});

test('状态视图按前置条件给出连接/断开可用性',()=>{
  const base={state:'external-attach-status',binding_valid:true,binding:{registration:{identity_family:'vmware'},attachment:{limits:{max_frames_per_second:500,max_seconds:3600}},policy_sha256:'a'.repeat(64)},
    slots:[{network:'lab0',address:'192.168.50.9',mac:'02:aa:bb:cc:dd:ee',reserved_port:40011}],
    connect_supported:true,session:{state:'idle'},note:''};
  const ready=statusView(base);
  assert.equal(ready.canConnect,true);
  assert.equal(ready.canDisconnect,false);
  assert.equal(statusView({...base,connect_supported:false}).canConnect,false);
  assert.equal(statusView({...base,session:{state:'connected'}}).canDisconnect,true);
});

test('诊断展开区只输出白名单字段',()=>{
  const report={state:'external-attach-status',
    binding:{registration:{identity_family:'vmware'},attachment:{limits:{max_frames_per_second:500,max_seconds:3600}},policy_sha256:'a'.repeat(64)},
    slots:[{network:'lab0',address:'192.168.50.9',mac:'02:aa:bb:cc:dd:ee',reserved_port:40011},
           {network:'plain',address:'10.81.0.9',mac:'02:aa:bb:cc:dd:0f'}]};
  const lines=diagnosticsView(report);
  assert.ok(lines.some(l=>l.includes('vmware')));
  assert.ok(lines.some(l=>l.includes('127.0.0.1:40011')));
  assert.ok(lines.some(l=>l.includes('本代次未预留接入口')));
  assert.ok(lines.some(l=>l.includes('500 帧/秒')));
  assert.ok(lines.every(l=>!/\/Users\/|password|secret/i.test(l)),'不输出宿主路径或凭据');
  assert.deepEqual(diagnosticsView(null),[]);
});

test('Windows盘符与UNC为绝对路径；歧义相对路径拒绝',()=>{
  assert.equal(isAbsoluteHostPath('/Users/s/.ssh/kali'),true);
  assert.equal(isAbsoluteHostPath('C:\\Users\\student\\.ssh\\kali'),true);
  assert.equal(isAbsoluteHostPath('c:/kali/key'),true);
  assert.equal(isAbsoluteHostPath('\\\\server\\share\\kali'),true);
  assert.equal(isAbsoluteHostPath('relative/key'),false);
  assert.equal(isAbsoluteHostPath('C:relative'),false);
  assert.equal(isAbsoluteHostPath(''),false);
  const win=goodForm(); win.identity='C:\\Users\\student\\.ssh\\kali';
  assert.equal(validateForm(win),null);
});

test('无有效登记时不给CLI提示；有效时给固定入口',()=>{
  assert.equal(cliConnectHint(null),null);
  assert.equal(cliConnectHint({}),null);
  assert.match(cliConnectHint({plan_sha256:'x'}),/ctflab_external_attach\.py connect/);
});
