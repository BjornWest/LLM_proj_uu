import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {Budget,budgetTotals} from '../lib/budget.mjs';
import {FileStore} from '../lib/store.mjs';
async function setup(t,env={}){const dir=await mkdtemp(path.join(os.tmpdir(),'actual-budget-'));t.after(()=>rm(dir,{recursive:true,force:true}));const store=new FileStore(dir);return {store,budget:new Budget(store,{env:{DEMO_DAILY_BUDGET_USD:'1',...env}})};}
test('settlement counts actual charges, frees unused bound, and duplicate response cannot double settle',async t=>{
 const {budget,store}=await setup(t);const a=await budget.reserve(.8);
 await assert.rejects(budget.reserve(.3),/pending or unknown/);
 const evidence={cost:.002,response_id:'response-1',response_sha256:'abc'};
 const first=await budget.settle(a,evidence);assert.equal(first.actual_spent_usd,.002);assert.equal(first.outstanding_usd,0);
 assert.deepEqual(await budget.settle(a,evidence),first);
 await assert.rejects(budget.settle(a,{...evidence,cost:.001}),/Conflicting/);
 const b=await budget.reserve(.8);await assert.rejects(budget.settle(b,evidence),/Duplicate/);
 const row=(await store.read(`daylight/budgets/${a.date}.json`)).value;
 assert.equal(row.calls,2);assert.equal(row.actual_spent_usd,.002);assert.equal(row.outstanding_usd,.8);
});
test('unknown charges retain liability; over-bound actual cost recorded and stops further requests',async t=>{
 const {budget}=await setup(t);const a=await budget.reserve(.8);
 assert.equal((await budget.settle(a)).unknown_attempts,1);await assert.rejects(budget.reserve(.3),/daily allowance/);
 const s=await budget.settle(a,{cost:1.2,response_id:'late'});assert.equal(s.actual_spent_usd,1.2);assert.equal(s.outstanding_usd,0);
 await assert.rejects(budget.reserve(.01),/daily allowance/);
});
test('concurrent reservations cannot overspend and concurrent settlements preserve both charges',async t=>{
 const {budget,store}=await setup(t);
 const results=await Promise.allSettled(Array.from({length:10},()=>budget.reserve(.3)));
 const receipts=results.filter(x=>x.status==='fulfilled').map(x=>x.value);assert.equal(receipts.length,3);
 await Promise.all(receipts.map((r,i)=>budget.settle(r,{cost:.001*(i+1),response_id:'id'+i})));
 const row=(await store.read(`daylight/budgets/${receipts[0].date}.json`)).value;
 assert.equal(row.calls,3);assert.ok(Math.abs(row.actual_spent_usd-.006)<1e-12);assert.equal(row.outstanding_usd,0);
});
test('legacy totals preserved as unresolved and known-unsent attempts release their allowance',async t=>{
 const {budget,store}=await setup(t);const date=new Date().toISOString().slice(0,10);
 await store.write(`daylight/budgets/${date}.json`,{date,reserved_usd:.7,calls:5});
 const receipt=await budget.reserve(.2);const result=await budget.settle(receipt,{cost:0,not_sent:true});assert.equal(result.outstanding_usd,.7);
 const row=(await store.read(`daylight/budgets/${date}.json`)).value;assert.equal(row.legacy.reserved_usd,.7);assert.equal(row.calls,6);
 await assert.rejects(budget.reserve(.4),/daily allowance/);
});
test('late settlement uses reservation date, not current day; call limit still enforced',async t=>{
 const {budget,store}=await setup(t,{DEMO_DAILY_CALL_LIMIT:'1'});const a=await budget.reserve(.1);
 await budget.settle(a,{cost:0,not_sent:true});await assert.rejects(budget.reserve(.1),/request limit/);
 const old={schema_version:2,date:'2020-01-01',calls:1,attempts:{old:{amount_usd:.1,status:'pending'}}};
 await store.write('daylight/budgets/2020-01-01.json',old);
 await budget.settle({id:'old',date:old.date,amount_usd:.1},{cost:.002});
 assert.equal(budgetTotals((await store.read('daylight/budgets/2020-01-01.json')).value).actual_spent_usd,.002);
});

test('legacy reconciliation requires complete unique response coverage and preserves original totals',async()=>{
 const {reconcile}=await import('../../../scripts/reconcile_demo_budget.mjs');
 const date='2026-09-21',prior={date,calls:2,reserved_usd:.7};
 const item=(id,bound,cumulative,cost)=>({receipt:{date,amount_usd:bound,daily_reserved_usd:cumulative},response_text:JSON.stringify({id,usage:{cost}}),source:{sha256:'a'.repeat(64)}});
 const evidence={date,attempts:[item('a',.4,.4,.001),item('b',.3,.7,.002)]};
 const row=reconcile(prior,evidence);assert.equal(row.actual_spent_usd,.003);assert.equal(row.outstanding_usd,0);assert.deepEqual(row.legacy,prior);assert.equal(row.calls,2);
 assert.throws(()=>reconcile(prior,{...evidence,attempts:evidence.attempts.slice(1)}),/Incomplete/);
 const duplicate=structuredClone(evidence);duplicate.attempts[1].response_text=duplicate.attempts[0].response_text;assert.throws(()=>reconcile(prior,duplicate),/Duplicate/);
 const gap=structuredClone(evidence);gap.attempts[1].receipt.daily_reserved_usd=.8;assert.throws(()=>reconcile(prior,gap),/gap/);
 const unknown=structuredClone(evidence);unknown.attempts[1].response_text='{"id":"b"}';assert.throws(()=>reconcile(prior,unknown),/Missing/);
});
