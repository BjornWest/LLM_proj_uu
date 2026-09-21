// Operator-only, offline evidence reconciliation. No inference and no network calls.
// Usage: node scripts/reconcile_demo_budget.mjs EVIDENCE_JSON [--apply SQLITE_PATH]
import fs from 'node:fs';
import {createHash,randomUUID} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {upgradeBudget,budgetTotals} from '../deploy/daylight/lib/budget.mjs';
const sha=s=>createHash('sha256').update(s).digest('hex');
const require=(b,m)=>{if(!b)throw Error(m);};
export function reconcile(prior,evidence){
 require(prior.schema_version!==2,'Budget already reconciled/upgraded; do not rewrite');
 require(evidence.date===prior.date&&Array.isArray(evidence.attempts),'Wrong evidence date');
 require(evidence.attempts.length===prior.calls,'Incomplete reservation coverage');
 const row=upgradeBudget(prior,prior.date),seen=new Set();let cumulative=0;
 for(const item of [...evidence.attempts].sort((a,b)=>a.receipt.daily_reserved_usd-b.receipt.daily_reserved_usd)){
  const {receipt,response_text,source}=item;const raw=JSON.parse(response_text),cost=raw?.usage?.cost;
  require(receipt.date===prior.date&&typeof receipt.amount_usd==='number'&&receipt.amount_usd>0,'Invalid receipt');
  require(typeof raw.id==='string'&&!seen.has(raw.id),'Duplicate/missing response ID');seen.add(raw.id);
  require(typeof cost==='number'&&Number.isFinite(cost)&&cost>=0&&cost<=receipt.amount_usd,'Missing or anomalous charge; retain old liability');
  cumulative+=receipt.amount_usd;
  require(Math.abs(cumulative-receipt.daily_reserved_usd)<1e-10,'Reservation sequence has a gap');
  require(typeof source?.sha256==='string'&&/^[0-9a-f]{64}$/.test(source.sha256),'Missing source hash');
  row.attempts['legacy-'+sha(raw.id)]={amount_usd:receipt.amount_usd,status:'settled',cost_usd:cost,
    response_id:raw.id,response_sha256:sha(response_text),not_sent:false,source};
 }
 require(Math.abs(cumulative-prior.reserved_usd)<1e-10,'Total reservation mismatch');
 row.legacy_unresolved_usd=0;row.reconciliation={evidence_sha256:sha(JSON.stringify(evidence)),at:new Date().toISOString(),scope:'Every legacy reservation matched a saved provider response'};
 Object.assign(row,budgetTotals(row));return row;
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
 const evidence=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
 if(process.argv[3]!=='--apply'){
  const row=reconcile(evidence.original,evidence);console.log(JSON.stringify({date:row.date,calls:row.calls,...budgetTotals(row)},null,2));
 }else{
  const {DatabaseSync}=await import('node:sqlite');const db=new DatabaseSync(process.argv[4]);
  db.exec('PRAGMA busy_timeout=5000; BEGIN IMMEDIATE');
  try{
   const key=`daylight/budgets/${evidence.date}.json`,saved=db.prepare('select raw,etag from objects where key=?').get(key);
   require(saved&&sha(saved.raw)===evidence.original_sha256,'Live ledger changed; recollect evidence');
   const state=db.prepare('select raw from objects where key=?').get('daylight/harness/control-v1.json');
   require(!state||!JSON.parse(state.raw).active,'Worker job active');
   for(const {raw} of db.prepare("select raw from objects where key like 'daylight/manual/%'").all()){
    const m=JSON.parse(raw);require(!(m.asks||[]).some(a=>a.status==='running'),'Manual inference active');
   }
   const result=reconcile(JSON.parse(saved.raw),evidence);
   db.prepare('update objects set raw=?,etag=? where key=?').run(JSON.stringify(result),randomUUID(),key);
   db.exec('COMMIT');console.log(JSON.stringify({date:result.date,calls:result.calls,...budgetTotals(result)},null,2));
  }catch(e){db.exec('ROLLBACK');throw e;}finally{db.close();}
 }
}
