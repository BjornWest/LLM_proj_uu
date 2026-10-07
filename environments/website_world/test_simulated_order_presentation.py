"""Copied generated renderer controls; source tests are not native acceptance."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import subprocess
from tempfile import TemporaryDirectory
import unittest

from . import simulated_order_presentation as orders
from .basket import basket_shop_source


class SimulatedOrderPresentationControls(unittest.TestCase):
    def test_composed_scheduler_and_orders_route(self):
        """Run the actual projected caller and binding, with offline native replies."""
        raw=Path(__file__).parents[1].joinpath('website_drafts/shop.js').read_bytes()
        assets,_=orders.project_assets({'shop.js':raw,'quote.js':Path(__file__).with_name('basket_quote.js').read_bytes()},expected_source_sha256=sha256(raw).hexdigest())
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name,source in assets.items():(root/name).write_bytes(source)
            (root/'package.json').write_text(json.dumps({'type':'module'}))
            (root/'world-data.js').write_text('export const data={simulatedOrders:true,basket:{worldId:"world",planId:"plan"}};')
            (root/'catalog.js').write_text('export const byVariant=key=>({variant:{offerId:"offer",key},product:{name:"Shoe"}});')
            (root/'item_quote.js').write_text('export const worldBinding={};export const validateAddress=()=>[];export const initialAddress={},branches=[],shopContact={},services=[],serviceTypes={},policy={},itemEstimate=()=>null;')
            script=r'''
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
const root=process.argv[2],shop=readFileSync(root+'/shop.js','utf8');
const {worldBinding}=await import(pathToFileURL(root+'/quote.js'));
const scheduler=shop.slice(shop.indexOf('function scheduleNativeQuote() {'),shop.indexOf('function invalidateAddressViews() {'));
const make=revision=>({revision,cart:[{id:'line',key:'sku',quantity:1}],address:{name:'Person',street:'Street',postcode:'12345',city:'City'},addressStatus:'valid',basketSelection:null,split:false,coupon:''});
const response=body=>({revision:body.revision,quoteId:'quote',requestId:body.selections?.line==='choice'?'explicit':'initial',status:'quoted',selectionReset:body.selections?.line==='stale',selected:{id:'option',selection:{line:'choice'},totalMinor:100}});
let rendered=0;
const schedule=(state,binding=worldBinding)=>new Function('worldBinding','state','route','render','document','invalidateAddressViews',scheduler+';return scheduleNativeQuote;')(binding,state,()=>({role:'checkout'}),()=>rendered++,{activeElement:null},()=>{throw Error('Unexpected address branch')})();
const settled=()=>new Promise(resolve=>setImmediate(resolve));
// First/default and reset requests must render their explicit native result.
for(const [revision,selection] of [[1,null],[2,{line:'stale'}]]){
 const state=make(revision);state.basketSelection=selection;let calls=0;
 globalThis.fetch=async(path,options)=>{calls++;return {ok:true,json:async()=>response(JSON.parse(options.body))}};
 const before=rendered;schedule(state);await settled();
 assert.equal(calls,2);assert.equal(rendered,before+1);assert.deepEqual(state.basketSelection,{line:'choice'});
 assert(worldBinding.orderIdentity(state,{errors:[],quoteId:'quote',total:1}).includes('explicit'));
 schedule(state);await settled();assert.equal(rendered,before+1); // settled cache causes no render loop
}
// Changes during either fetch must not install a stale selection or redraw.
for(const [revision,mutateAt] of [[3,1],[4,2]]){
 const state=make(revision);let calls=0;const before=rendered;
 globalThis.fetch=async(path,options)=>{const body=JSON.parse(options.body);if(++calls===mutateAt)state.address.city='Changed';return {ok:true,json:async()=>response(body)}};
 schedule(state);await settled();assert.equal(rendered,before);assert.equal(state.basketSelection,null);
}
// A change after ensureQuote settles but before its caller runs is stale too.
const state=make(5),before=rendered;
globalThis.fetch=async(path,options)=>({ok:true,json:async()=>response(JSON.parse(options.body))});
schedule(state,{...worldBinding,ensureQuote:draft=>worldBinding.ensureQuote(draft).then(result=>{draft.revision++;return result})});
await settled();assert.equal(rendered,before);
// The same projected caller retains the ordinary non-ordering boolean guard.
for(const changed of [false,true]){
 const draft=make(6),count=rendered;
 schedule(draft,{simulatedOrders:false,inquiryKey:s=>String(s.revision),ensureQuote:async()=>changed});
 await settled();assert.equal(rendered,count+(changed?1:0));
}
// Exercise the actual article function before its native "no orders" fallback.
const article=shop.slice(shop.indexOf('function article(id) {'),shop.indexOf('function info('));
assert(article.includes('function article(id)'));
let fallbackCalls=0;
const e=s=>String(s).replaceAll('<','&lt;'),link=(url,label)=>`<a href="${url}">${label}</a>`;
const shopper={orders:[{simulated:true,id:'SIM1',date:'2026-10-08'},{id:'legacy',date:'old'}]};
const view=new Function('state','worldBinding','e','link','orderArticle',article+';return article;')(shopper,{simulatedOrders:true,article:()=>{fallbackCalls++;return '<p>No existing order information is available.</p>'}},e,link,order=>`Confirmed ${order.id}`);
assert(view('orders').includes('info/order-SIM1'));assert(!view('orders').includes('legacy'));assert.equal(fallbackCalls,0);
assert.equal(view('order-SIM1'),'Confirmed SIM1');assert.equal(fallbackCalls,0);
shopper.orders=[];assert(view('orders').includes('No orders have been placed'));assert.equal(fallbackCalls,0);
console.log(JSON.stringify({composed_scheduler_and_orders:'pass',network_requests:0}));
'''
            result=subprocess.run(['node','--input-type=module','-',str(root)],input=script,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_all_composed_sources_keep_exact_inverse_and_other_assets(self):
        raw=Path(__file__).parents[1].joinpath('website_drafts/shop.js').read_text()
        for basket in (False,True):
            for reviews in (False,True):
                source=basket_shop_source(raw,canonical_domain=True) if basket else raw
                if reviews:
                    source=source.replace('function productPage(id,params) {','function originalProductPage(id,params) {')
                    source+='\nimport {customerReviews} from "./retailer_reviews.js";\nfunction productPage(id,params){return originalProductPage(id,params);}\n'
                assets={'shop.js':source.encode(),'quote.js':Path(__file__).with_name('basket_quote.js').read_bytes(),'retailer_reviews.js':b'attributed corpus'}
                before=deepcopy(assets)
                result,evidence=orders.project_assets(assets,expected_source_sha256=sha256(assets['shop.js']).hexdigest())
                self.assertEqual(orders.restore_source(result['shop.js'],evidence),assets['shop.js'])
                self.assertEqual(assets,before)
                self.assertEqual(orders.restore_quote(result['quote.js'],evidence),assets['quote.js'])
                for name in assets.keys()-{'shop.js','quote.js'}:self.assertEqual(result[name],assets[name])
                self.assertIn('const __simulatedOrder=',result['shop.js'].decode())
                self.assertNotIn('simulatedPurchaseForm',source)

    def test_changed_or_ambiguous_projection_rejects(self):
        raw=Path(__file__).parents[1].joinpath('website_drafts/shop.js').read_bytes()
        for source in (b'',raw+next(iter(orders.HOOKS)).encode()):
            with self.assertRaises(ValueError):orders.project_assets({'shop.js':source},expected_source_sha256=sha256(source).hexdigest())
        with self.assertRaises(ValueError):orders.project_assets({'shop.js':raw},expected_source_sha256='0'*64)
        projected,evidence=orders.project_assets({'shop.js':raw,'quote.js':Path(__file__).with_name('basket_quote.js').read_bytes()},expected_source_sha256=sha256(raw).hexdigest())
        with self.assertRaises(ValueError):orders.project_assets(projected,expected_source_sha256=sha256(projected['shop.js']).hexdigest())
        with self.assertRaises(ValueError):orders.restore_source(projected['shop.js']+b'changed',evidence)


if __name__=='__main__':unittest.main()
