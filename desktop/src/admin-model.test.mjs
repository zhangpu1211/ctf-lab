import test from 'node:test';import assert from 'node:assert/strict';
import {adminAllowed,adminPayload,adminResult} from './admin-model.mjs';
const instance='11111111-1111-4111-8111-111111111111',attempt='22222222-2222-4222-8222-222222222222';
const c={target:'a'.repeat(64),config:{savedId:'saved'},role:'administrator',course_management:true,audit_management:true,instances:[instance]};
test('管理入口要求保存目标、角色和服务器能力；旧握手默认隐藏',()=>{
 for(const x of [{...c,config:{}},{...c,role:'student'},{...c,course_management:false},{}])assert.equal(adminAllowed(x,'course-list'),false);
 assert.equal(adminAllowed({...c,role:'teacher'},'audit-review'),false);assert.equal(adminAllowed(c,'course-list'),true);
});
test('课程只接受登记标识和已分配实例，变更绑定预览摘要',()=>{
 const v={offer_id:'web',instance_uuid:instance,mapping_sha256:'b'.repeat(64)};
 const p=adminPayload(c,'course-provision',v);assert.deepEqual(p,{action:'course-provision',target:c.target,...v});
 for(const values of [{...v,path:'/outside'},{...v,instance_uuid:attempt},{...v,mapping_sha256:''}])assert.throws(()=>adminPayload(c,'course-provision',values));
 assert.throws(()=>adminResult(c,p,{target:c.target,result:{instance_uuid:instance,mapping_sha256:'c'.repeat(64)}}));
});
test('审计使用检查点、原attempt和预览摘要，不能冒称VM已验证',()=>{
 assert.throws(()=>adminPayload(c,'audit-review',{after:-1,limit:50,checkpoint:null}));
 assert.throws(()=>adminPayload(c,'audit-review',{after:0,limit:50,checkpoint:{seq:0,sha256:'bad'}}));
 const p=adminPayload(c,'audit-settle',{attempt_id:attempt,review_sha256:'b'.repeat(64)});
 const result={attempt_id:attempt,original_worker_result:'unknown',vm_observed:false,automatic_replay:false};
 assert.deepEqual(adminResult(c,p,{target:c.target,result}),result);
 assert.throws(()=>adminResult(c,p,{target:c.target,result:{...result,vm_observed:true}}));
 assert.throws(()=>adminResult(c,p,{target:'changed',result}));
});
