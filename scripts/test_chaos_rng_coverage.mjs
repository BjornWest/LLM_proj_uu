import test from 'node:test';
import assert from 'node:assert/strict';
import {tokenDiversity} from './verify_chaos_rng.mjs';

const names=['Linux desktop','MacBook Pro','ThinkPad X1','Workstation'];
const full=names.flatMap(target_name=>[0,1,2].flatMap(target_index=>[0,1].map(safe_action_index=>
  ({target_name,target_index,safe_action_index}))));

test('requires every expected name and joint position while retaining counts',()=>{
  const result=tokenDiversity(full,true);
  assert.deepEqual(result.joint_position,{'0:0':4,'0:1':4,'1:0':4,'1:1':4,'2:0':4,'2:1':4});
  assert.deepEqual(result.target_name,Object.fromEntries(names.map(name=>[name,6])));
});

test('rejects collapsed joint coverage despite balanced row and action marginals',()=>{
  const rows=names.flatMap(target_name=>[[0,1],[0,1],[1,0],[1,0],[2,0],[2,1]].map(
    ([target_index,safe_action_index])=>({target_name,target_index,safe_action_index})));
  const diagnostic=tokenDiversity(rows);
  assert.deepEqual(diagnostic.target_index,{'0':8,'1':8,'2':8});
  assert.deepEqual(diagnostic.safe_action_index,{'0':12,'1':12});
  assert.throws(()=>tokenDiversity(rows,true),/joint_position/);
});

test('rejects missing or substituted names even when every position is covered',()=>{
  assert.throws(()=>tokenDiversity(full.filter(v=>v.target_name!==names[0]),true),/target_name/);
  assert.throws(()=>tokenDiversity(full.map(v=>({...v,target_name:v.target_name===names[0]?'Unknown device':v.target_name})),true),/target_name/);
});

test('rejects empty or unexpected positions but permits historical diagnostic counts',()=>{
  assert.throws(()=>tokenDiversity([],true),/target_index/);
  assert.throws(()=>tokenDiversity([...full,{target_name:names[0],target_index:3,safe_action_index:0}],true),/target_index/);
  assert.deepEqual(tokenDiversity([]),{target_index:{},target_name:{},safe_action_index:{},joint_position:{}});
});
