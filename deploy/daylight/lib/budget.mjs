// Actual provider charges plus outstanding liabilities; never reset a daily ledger.
import {randomUUID} from 'node:crypto';
const insist=(ok,message,status=400)=>{if(!ok)throw Object.assign(Error(message),{status});};
const money=n=>typeof n==='number'&&Number.isFinite(n)&&n>=0;
const conflict=e=>e.code==='BLOB_WRITE_CONFLICT'||e.message==='Storage conflict';
const key=date=>{insist(/^\d{4}-\d{2}-\d{2}$/.test(date),'Invalid budget date');return `daylight/budgets/${date}.json`;};
export function upgradeBudget(prior,date){
  if(prior?.schema_version===2)return structuredClone(prior);
  // Old aggregate reservations are unresolved until reconciled from saved responses.
  return {schema_version:2,date,calls:prior?.calls||0,legacy_unresolved_usd:prior?.reserved_usd||0,
    legacy:prior?structuredClone(prior):null,attempts:{}};
}
export function budgetTotals(row){
  const values=Object.values(row.attempts);
  const spent=values.filter(x=>x.status==='settled').reduce((s,x)=>s+x.cost_usd,0);
  const pending=values.filter(x=>x.status!=='settled').reduce((s,x)=>s+x.amount_usd,0)+(row.legacy_unresolved_usd||0);
  return {actual_spent_usd:spent,outstanding_usd:pending,reserved_usd:spent+pending,
    unknown_attempts:values.filter(x=>x.status==='unknown').length};
}
export class Budget {
  constructor(store,{env=process.env}={}){this.store=store;this.env=env;}
  async mutate(date,fn){
    for(let i=0;i<20;i++){
      const prior=await this.store.read(key(date));const row=upgradeBudget(prior?.value,date);
      const result=fn(row);Object.assign(row,budgetTotals(row));
      try{await this.store.write(key(date),row,prior?.etag??null);return result;}
      catch(e){if(!conflict(e)||i===19)throw e;}
    }
  }
  async reserve(amount){
    insist(money(amount)&&amount>0,'Invalid inference allowance');
    const date=new Date().toISOString().slice(0,10),id=randomUUID();
    const cap=Number(this.env.DEMO_DAILY_BUDGET_USD||1),calls=Number(this.env.DEMO_DAILY_CALL_LIMIT||100);
    insist(Number.isFinite(cap)&&cap>0&&cap<=100&&Number.isSafeInteger(calls)&&calls>0,'Invalid daily budget',503);
    return this.mutate(date,row=>{
      const totals=budgetTotals(row);
      insist(totals.reserved_usd+amount<=cap+1e-12,`Demo daily allowance reached: $${totals.actual_spent_usd.toFixed(4)} spent, $${totals.outstanding_usd.toFixed(4)} pending or unknown, $${cap.toFixed(2)} limit.`,429);
      insist(row.calls<calls,'Demo daily request limit reached',429);
      row.attempts[id]={amount_usd:amount,status:'pending',created_at:new Date().toISOString()};row.calls++;
      return {id,date,amount_usd:amount,daily_reserved_usd:budgetTotals(row).reserved_usd,daily_limit_usd:cap,accounting:'actual-cost-v2'};
    });
  }
  async settle(receipt,{cost=null,response_id=null,response_sha256=null,not_sent=false}={}){
    insist(receipt?.id&&typeof receipt.id==='string','Missing budget receipt');
    insist(cost===null||money(cost),'Invalid reported cost');
    insist(typeof not_sent==='boolean'&&(!not_sent||cost===0),'Invalid unsent settlement');
    const result={status:cost===null?'unknown':'settled',cost_usd:cost,response_id,response_sha256,not_sent};
    return this.mutate(receipt.date,row=>{
      const attempt=row.attempts[receipt.id];insist(attempt&&attempt.amount_usd===receipt.amount_usd,'Budget receipt mismatch',409);
      if(attempt.status==='settled'){
        insist(['status','cost_usd','response_id','response_sha256','not_sent'].every(k=>attempt[k]===result[k]),'Conflicting cost settlement',409);
        return {...result,...budgetTotals(row)};
      }
      if(response_id)insist(!Object.entries(row.attempts).some(([id,x])=>id!==receipt.id&&x.response_id===response_id),'Duplicate billed response',409);
      Object.assign(attempt,result,{settled_at:new Date().toISOString()});
      return {...result,...budgetTotals(row)};
    });
  }
}
