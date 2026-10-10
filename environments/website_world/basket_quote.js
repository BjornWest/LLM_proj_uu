// Public projection only. All prices, groups and dates are computed by the oracle.
import {data} from './world-data.js';
import {byVariant} from './catalog.js';
import {worldBinding as itemBinding,validateAddress} from './item_quote.js';
export {initialAddress,branches,shopContact,services,serviceTypes,policy,itemEstimate,validateAddress} from './item_quote.js';
const requests=new Map();
const arrival=a=>a?.status!=='estimated'?null:a.earliest_date===a.latest_date?a.latest_date:`${a.earliest_date} to ${a.latest_date}`;
const monetaryId=l=>data.basket.domain?byVariant(l.key).variant.offerId:l.id;
function payload(draft){
  const lines=new Map();
  for(const l of draft.cart){const id=monetaryId(l),old=lines.get(id);lines.set(id,{line_id:id,offer_id:byVariant(l.key)?.variant.offerId,quantity:l.quantity+(old?.quantity||0)});}
  return {revision:draft.revision,world_id:data.basket.worldId,plan_id:data.basket.planId,
    ...(data.basket.domain?{domain_id:data.basket.domain.id}:{}),
    lines:data.basket.domain?[...lines.values()].sort((a,b)=>a.line_id.localeCompare(b.line_id)):draft.cart.map(l=>({line_id:l.id,offer_id:byVariant(l.key)?.variant.offerId,quantity:l.quantity})),
    address:{...draft.address},selections:draft.basketSelection||null,split:!!draft.split,coupon_code:draft.coupon||null};
}
const inquiryKey=draft=>JSON.stringify(payload(draft));
function available(draft){return draft.cart.length&&!validateAddress(draft.address).length&&!['unvalidated','pending','invalid'].includes(draft.addressStatus);}
export function quote(cart,draft,conf,revision){
  const base={revision,errors:[],shipments:[],coupon:{status:'none'},total:null,canSplit:false,selectionChanges:[]};
  if(!cart.length)return {...base,errors:['Your basket is empty']};
  if(!available(draft))return {...base,errors:['Save the current address to refresh delivery']};
  const cached=requests.get(inquiryKey(draft));
  if(!cached?.value)return {...base,errors:[cached?.error||'Delivery calculation is pending']};
  const value=cached.value,selected=value.selected;
  if(!selected)return {...base,errors:value.reasons.map(r=>r.reason.replaceAll('_',' ')).concat(value.reasons.length?[]:['No complete basket delivery is available'])};
  const lines=new Map(cart.map((l,index)=>[monetaryId(l),{...l,...byVariant(l.key),index}]));
  const shipments=selected.shipments.map(s=>({...s,lines:s.lineIds.map(id=>lines.get(id)),
    selected:{...s.delivery,arrival:arrival(s.arrival),fee:s.shippingMinor/100},
    arrival:arrival(s.arrival),fee:s.shippingMinor/100,qualified:s.qualification.threshold_met,
    brand:lines.get(s.lineIds[0])?.product.brand}));
  return {...base,shipments,subtotal:selected.subtotalMinor/100,discount:selected.discountMinor/100,
    shipping:selected.shippingMinor/100,total:selected.totalMinor/100,quoteId:value.quoteId,
    coupon:{...selected.coupon,status:selected.coupon.status==='not_requested'?'none':selected.coupon.status},
    canSplit:value.canSplit,selectionChanges:value.selectionReset?['invalidated']:[]};
}
export const worldBinding={...itemBinding,basket:true,inquiryKey,
  quantityLimit(v){return data.basket.domain?.quantityLimits[v.offerId]??20;},
  maxLinesPerOrder(){return data.basket.domain?.maxLinesPerOrder??64;},
  async ensureQuote(draft){
    if(!available(draft))return false;
    const key=inquiryKey(draft);
    if(requests.has(key))return false;
    requests.set(key,{pending:true});
    try{
      const response=await fetch('/api/basket-quote',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload(draft))});
      const value=await response.json();if(!response.ok)throw Error(value.error||'Basket quote unavailable');
      if(value.revision!==draft.revision||key!==inquiryKey(draft))return false;
      requests.set(key,{value});
    }catch(error){requests.set(key,{error:error.message});}
    return key===inquiryKey(draft);
  },
  selectDelivery(draft,id){
    const value=requests.get(inquiryKey(draft))?.value;
    const option=value?.options.find(o=>o.id===id);
    if(!option)return false;
    draft.basketSelection={...option.selection};return true;
  },
  deliveryForm({state,e,money,serviceTypes}){
    const value=requests.get(inquiryKey(state))?.value;
    if(!value?.selected)return '<section aria-label="Delivery choices"><h2>Delivery choices</h2><p>Save a valid address to see current basket services and prices.</p></section>';
    const groups=Map.groupBy?Map.groupBy(value.groupOffers,o=>o.selection_group_id):value.groupOffers.reduce((m,o)=>m.set(o.selection_group_id,[...(m.get(o.selection_group_id)||[]),o]),new Map());
    const split=value.canSplit?`<fieldset><legend>Dispatch preference</legend><label><input type="radio" name="split" data-split="false" ${!state.split?'checked':''}> Deliver together within required shipment groups</label><label><input type="radio" name="split" data-split="true" ${state.split?'checked':''}> Send items as they become ready</label><p>Each separate shipment has its own delivery charge.</p></fieldset>`:'';
    return `<section aria-label="Delivery choices"><h2>Delivery choices</h2>${data.quoteAsOf?`<p>Delivery estimates calculated as of ${e(data.quoteAsOf)}.</p>`:''}${split}${[...groups].map(([key,offers])=>{
      const lines=offers[0].line_ids.map(id=>state.cart.find(l=>monetaryId(l)===id));
      return `<fieldset class="delivery-options"><legend>Delivery for ${lines.map(l=>e(byVariant(l.key).product.name)).join(', ')}</legend>${offers.map(o=>{
        const option=value.options.find(v=>v.id===o.option_id);
        const shipment=option.shipments.find(s=>s.lineIds.some(id=>o.line_ids.includes(id)));
        const d=shipment.delivery;
        return `<label class="delivery-row"><input type="radio" name="${e(key)}" data-service-group="${e(key)}" value="${e(option.id)}" ${option.id===value.selected.id?'checked':''}><span><strong>${e(d.company)} — ${e(d.name)}</strong><br>${e(serviceTypes[d.type])} · ${e(d.location.name)}<br>${e(d.location.address)}<br>${arrival(o.arrival)?`Estimated: ${e(arrival(o.arrival))}`:'Arrival date not yet confirmed'}<br>Delivery for these items: ${money(o.shipping_minor/100)}<br>Basket total with this choice: ${money(o.complete_basket_total_minor/100)}</span></label>`;
      }).join('')}</fieldset>`;
    }).join('')}</section>`;
  },
  policyContent({e,money}){
    const p=data.basket.policy,threshold=data.policy.freeThresholdMinor;
    return `<h3>Delivery charges and services</h3><p>Compatible items travel together; each shipment is charged its highest applicable item tariff. Separate shipment charges are added.</p><p>Supplier orders travel separately from stocked goods, grouped by brand where compatible.</p>${threshold===null?'<p>No free-delivery threshold is offered.</p>':`<p>Domestic standard delivery qualifies from ${money(threshold/100)} in eligible products after discounts, assessed ${p.qualification_scope==='shipment'?'for each shipment':'across the checkout'}. Express upgrades retain their additional charge; foreign shipments do not qualify automatically.</p>`}${p.membership_active?'<p>Your active membership provides the applicable domestic standard-delivery benefit.</p>':''}<p>Local shop collection and supported warehouse-to-shop transfers are free.</p><p>${p.optional_split?'Optional arrival groups can ship separately when their estimates differ.':'Compatible shipments are delivered together.'}</p>`;
  },
  decorate(root){itemBinding.decorate(root);},
};
