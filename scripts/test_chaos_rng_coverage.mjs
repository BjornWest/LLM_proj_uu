import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {tokenDiversity,requireNewOutput,writeNewReport} from './verify_chaos_rng.mjs';

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

function scratch(t) {
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'chaos-rng-output-'));
  t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  return dir;
}

test('CLI rejects existing outputs before reading bundles or computing RNG',t=>{
  const dir=scratch(t),output=path.join(dir,'historical.json');
  fs.writeFileSync(output,'historical bytes\n');
  const result=spawnSync(process.execPath,[path.join(import.meta.dirname,'verify_chaos_rng.mjs'),
    'missing-original','missing-derived',output],{cwd:dir,encoding:'utf8'});
  assert.notEqual(result.status,0);
  assert.match(result.stderr,/Refusing to overwrite existing report path/);
  assert.doesNotMatch(result.stderr,/ENOENT/);
  assert.equal(fs.readFileSync(output,'utf8'),'historical bytes\n');
});

test('default path is separate from historical report and also guarded',t=>{
  const dir=scratch(t),folder=path.join(dir,'.local/preflight');
  fs.mkdirSync(folder,{recursive:true});
  const legacy=path.join(folder,'chaos-rng-v2.json');
  const current=path.join(folder,'chaos-rng-joint-coverage-v2.json');
  fs.writeFileSync(legacy,'legacy');fs.writeFileSync(current,'current');
  const result=spawnSync(process.execPath,[path.join(import.meta.dirname,'verify_chaos_rng.mjs'),
    'missing-original','missing-derived'],{cwd:dir,encoding:'utf8'});
  assert.notEqual(result.status,0);
  assert.match(result.stderr,/Refusing to overwrite existing report path: .local\/preflight\/chaos-rng-joint-coverage-v2.json/);
  assert.equal(fs.readFileSync(legacy,'utf8'),'legacy');
  assert.equal(fs.readFileSync(current,'utf8'),'current');
});

test('existing paths include directories and dangling symlinks',t=>{
  const dir=scratch(t),link=path.join(dir,'dangling.json');
  fs.symlinkSync(path.join(dir,'missing-target'),link);
  for(const output of [dir,link])assert.throws(()=>requireNewOutput(output),/Refusing to overwrite/);
  assert.equal(fs.lstatSync(link).isSymbolicLink(),true);
});

test('exclusive final creation protects a competing file after early check',t=>{
  const dir=scratch(t),output=path.join(dir,'report.json');
  requireNewOutput(output);
  fs.writeFileSync(output,'competing writer');
  assert.throws(()=>writeNewReport(output,{passed:true}),{code:'EEXIST'});
  assert.equal(fs.readFileSync(output,'utf8'),'competing writer');
});

test('fresh report creates parent directories and preserves exact JSON',t=>{
  const dir=scratch(t),output=path.join(dir,'nested/report.json'),report={passed:true,counts:[17,22,19,23,26,21]};
  requireNewOutput(output);writeNewReport(output,report);
  assert.deepEqual(JSON.parse(fs.readFileSync(output,'utf8')),report);
  assert.throws(()=>writeNewReport(output,{passed:false}),{code:'EEXIST'});
  assert.deepEqual(JSON.parse(fs.readFileSync(output,'utf8')),report);
});
