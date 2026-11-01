import test from 'node:test';
import assert from 'node:assert/strict';
import {canManageVersions,sameVersionTarget,versionChangePayload,onlineDownloadPayload,bootstrapCreatePayload,bootstrapResumePayload} from './version-model.mjs';
const status={target:'a'.repeat(64),read_only:false};
test('版本变更需服务器明确可写，读取失败/只读/忙碌时拒绝',()=>{assert.equal(canManageVersions(status),true);for(const value of [null,{...status,read_only:true},{target:status.target}])assert.equal(canManageVersions(value),false);assert.equal(canManageVersions(status,true),false);});
test('目标配置变化或旧预览不能切换版本',()=>{assert.equal(sameVersionTarget(status,{target:status.target}),true);assert.equal(sameVersionTarget(status,{target:'b'.repeat(64)}),false);const preview={target:'0.2.0',plan_sha256:'c'.repeat(64)};assert.throws(()=>versionChangePayload(status,preview,'0.3.0','id'));const payload=versionChangePayload(status,preview,'0.2.0','id');assert.equal(payload.target,status.target);assert.equal(payload.operation_id,'id');assert.equal(payload.plan_sha256,preview.plan_sha256);});
test('在线下载绑定版本库、来源、上限与原计划',()=>{const preview={library_target:status.target,source:'https://example.invalid/',maximum:1048576,plan_sha256:'d'.repeat(64)};const payload=onlineDownloadPayload(status,preview,preview.source,preview.maximum,'original');assert.equal(payload.operation_id,'original');for(const change of [{library_target:'b'.repeat(64)},{source:'https://other.invalid/'},{maximum:2}])assert.throws(()=>onlineDownloadPayload(status,{...preview,...change},preview.source,preview.maximum,'original'));});
test('首轮设置只发送原预览的公钥来源和摘要，继续沿用原标识',()=>{
 const source='/public/keys.json',operation='22222222-2222-4222-8222-222222222222';
 const plan={source,created:false,publisher_identity_verified:false,plan_sha256:'a'.repeat(64),source_sha256:'b'.repeat(64),keys_sha256:'c'.repeat(64)};
 assert.deepEqual(bootstrapCreatePayload(plan,source,operation),{action:'bootstrap-create',public_keys:source,operation_id:operation,plan_sha256:plan.plan_sha256});
 for(const bad of [{...plan,created:true},{...plan,publisher_identity_verified:true},{...plan,plan_sha256:'bad'}])assert.throws(()=>bootstrapCreatePayload(bad,source,operation));
 assert.throws(()=>bootstrapCreatePayload(plan,'/changed',operation));assert.throws(()=>bootstrapCreatePayload(plan,source,'new'));
 const view={read_only:false,ready:false,operation_id:operation,plan_sha256:plan.plan_sha256};
 assert.deepEqual(bootstrapResumePayload(view),{action:'bootstrap-resume',operation_id:operation,plan_sha256:plan.plan_sha256});
 for(const bad of [{...view,read_only:true},{...view,ready:true},{...view,operation_id:'bad'}])assert.throws(()=>bootstrapResumePayload(bad));
});
