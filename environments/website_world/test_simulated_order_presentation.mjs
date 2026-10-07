// Authored offline confirmation controls; no browser, provider or world draw.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {webcrypto} from 'node:crypto';
globalThis.crypto ||= webcrypto;
const source=readFileSync(new URL('./simulated_order_presentation.js',import.meta.url),'utf8');
const m=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const escape=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const quote={errors:[],quoteId:'native-quote',total:1};
const base=()=>({orders:[],cart:[{id:'1',key:'sku',quantity:2}],address:{name:'Person',street:'Street',unit:'4',postcode:'12345',city:'City'},instructions:'Note',revision:3,coupon:'CODE',split:true,editing:'1',basketSelection:{line:'choice'},deliveryChoices:{stock:'choice'}});
const receipt={simulated:true,id:'SIM1',date:'2026-10-08',items:[{name:'<Shoe>',options:'42',quantity:2,subtotalMinor:100}],address:{name:'Person',street:'Street',unit:'4',postcode:'12345',city:'City'},instructions:'<Note>',shipments:[{company:'Carrier',type:'home',name:'Standard',location:{name:'Your address',address:'Street'},arrival:null,shippingMinor:10}],subtotalMinor:100,discountMinor:0,shippingMinor:10,totalMinor:110};
let saved=0,target=null,notices=[];
const complete=args=>m.complete({...args,binding:{orderIdentity:(draft,result)=>JSON.stringify([draft.cart,draft.address,draft.instructions,result.quoteId]),...args.binding}});
const context=state=>({state,values:{terms:'on',cardNumber:'SHOULD NOT PASS'},result:quote,save:()=>saved++,goto:p=>{target=p},notify:x=>notices.push(x)});
const state=base();
await complete({...context(state),binding:{placeOrder:async(draft,result)=>{assert.equal(result,quote);assert.equal(draft.cardNumber,undefined);assert.deepEqual(draft.cart,state.cart);return structuredClone(receipt)}}});
assert.equal(state.cart.length,0);assert.equal(state.orders.length,1);assert.equal(state.coupon,'');assert.equal(saved,2);assert.equal(target,'info/order-SIM1');
const form=m.purchaseForm(quote,{state:base(),e:escape,link:()=>'<a>Terms</a>'});
assert(form.includes('Complete purchase'));assert(!form.includes('cardNumber'));assert(!form.includes('securityCode'));
const html=m.confirmation(receipt,{e:escape,money:n=>`${n} SEK`,serviceTypes:{home:'Home delivery'}});
assert(html.includes('Order confirmed'));assert(html.includes('Apartment 4'));assert(html.includes('1.1 SEK'));assert(html.includes('&lt;Shoe>'));assert(!html.includes('<Note>'));assert(html.includes('Home delivery'));
// A changed live basket must retain later items and additional quantity.
const changed=base();
await complete({...context(changed),binding:{placeOrder:async()=>{changed.cart[0].quantity=3;changed.cart.push({id:'2',key:'other',quantity:1});changed.revision++;return structuredClone(receipt)}}});
assert.deepEqual(changed.cart,[{id:'1',key:'sku',quantity:1},{id:'2',key:'other',quantity:1}]);assert.equal(changed.coupon,'CODE');
// Failed or invalid submissions preserve the cart and do not create a receipt.
for(const binding of [{placeOrder:async()=>{throw Error('Stale quote')}},{placeOrder:async()=>null}]){
 const failed=base();await complete({...context(failed),binding});assert.equal(failed.orders.length,0);assert.equal(failed.cart.length,1);
}
let dispatches=0;const rejected=base();
await complete({...context(rejected),values:{},binding:{placeOrder:async()=>{dispatches++;return receipt}}});assert.equal(dispatches,0);
// Double-clicks while an identical completion is pending cause one dispatch.
const concurrent=base();let release;const wait=new Promise(resolve=>{release=resolve});
const args={...context(concurrent),binding:{placeOrder:async()=>{dispatches++;await wait;return structuredClone(receipt)}}};
const first=complete(args);await complete(args);release();await first;assert.equal(dispatches,1);assert.equal(concurrent.orders.length,1);
console.log(JSON.stringify({checks:'pass',kind:'authored offline presentation and asynchronous state controls',browser_requests:0,provider_requests:0,world_draws:0}));
