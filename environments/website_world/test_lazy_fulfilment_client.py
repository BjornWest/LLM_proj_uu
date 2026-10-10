"""Address refresh must not erase loaded lazy item delivery routes."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import pytest

JS=r'''
import assert from 'node:assert/strict';
import {mkdtempSync,writeFileSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const scenario=process.argv[1],src=process.argv[2],tmp=mkdtempSync(join(tmpdir(),'lazy-client-'));
const a={name:'Alex',street:'Road1',unit:'',postcode:'75310',city:'Uppsala'},b={...a,postcode:'11122',city:'Stockholm'};
const route=(address,sku)=>[{id:sku+'-home',type:'home',supply:'on_hand',readyDays:2,arrival:address.postcode==='75310'?'2026-10-02':'2026-10-04'}, {id:sku+'-branch',type:'retailer_branch',location:{name:'Local shop'},requiresTransfer:false,readyDays:0}];
const item=sku=>({skuId:sku,state:'in_stock',stock:1,sourceStock:[],pickup:[]});
const data={initialAddress:a,rememberedAddress:a,branches:{},policy:{freeThresholdMinor:null},lazyFulfilment:true,fulfilment:{address:a,optionsBySku:{},pending:true}};
writeFileSync(join(tmp,'world-data.js'),'export const data='+JSON.stringify(data));
writeFileSync(join(tmp,'catalog.js'),'export function byVariant(){return null;}');
writeFileSync(join(tmp,'quote.mjs'),readFileSync(src));
let calls=0,pendingRefresh;
globalThis.fetch=async(url)=>{
 calls++;const q=new URL(url,'https://shop.test').searchParams,sku=q.get('sku_id'),address=q.get('postcode')==='75310'?a:b;
 if(!sku&&scenario==='inflight'){await new Promise(resolve=>pendingRefresh=resolve);}
 const value=sku?{address,optionsBySku:{[sku]:route(address,sku)}}:{address,optionsBySku:{},pending:true};
 return {ok:true,json:async()=>scenario==='complete'&&!sku?{address,optionsBySku:{one:[]}}:value};
};
try {
 const {worldBinding:w,itemEstimate}=await import(pathToFileURL(join(tmp,'quote.mjs')));
 const v=item('one');
 assert.equal(await w.ensureProduct({},v,a),true);
 assert.equal(itemEstimate(v,a),'2026-10-02');
 if(scenario==='inflight'){
  const saving=w.refresh(a);
  await w.ensureProduct({},item('two'),a);
  pendingRefresh();await saving;
  assert.equal(itemEstimate(item('two'),a),'2026-10-02');
 }else if(scenario==='isolated'){
  await w.refresh(b);assert.equal(itemEstimate(v,b),null);assert.equal(itemEstimate(v,a),'2026-10-02');
  await w.ensureProduct({},v,b);assert.equal(itemEstimate(v,b),'2026-10-04');
  await w.refresh(a);assert.equal(itemEstimate(v,b),'2026-10-04');
 }else await w.refresh(a);
 if(scenario==='complete')assert.equal(itemEstimate(v,a),null);
 else {
  assert.equal(itemEstimate(v,a),'2026-10-02');
  const html=w.productServices({p:{},v,e:String,link:()=>'',state:{remembered:a},conf:{policy:'footer'},g:{}});
  assert(html.includes('2026-10-02'));assert(html.includes('Local shop: In stock locally'));assert(!html.includes('Calculating delivery details'));
  const before=calls;assert.equal(await w.ensureProduct({},v,a),false);assert.equal(calls,before);
 }
 console.log(JSON.stringify({scenario,status:'pass'}));
}finally{rmSync(tmp,{recursive:true,force:true});}
'''


def test_lazy_address_refresh_preserves_only_the_same_destination():
    # Independent processes isolate JS globals/module caches and fetch callbacks.
    source=Path(__file__).with_name('world_quote.js')
    def run(case):
        result=subprocess.run(['node','--input-type=module','-e',JS,case,str(source)],capture_output=True,text=True,timeout=15)
        assert result.returncode==0,result.stderr
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run,['pending','isolated','inflight','complete']))
