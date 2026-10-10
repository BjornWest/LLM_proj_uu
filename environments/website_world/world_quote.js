// All dates and charges originate from the server-side Product quote helper.
import {data} from './world-data.js';
import {byVariant} from './catalog.js';
export const initialAddress=data.initialAddress,branches=data.branches;
export const shopContact={email:'Not published',phone:'Not published',hours:'Not published'};
export const policy={freeMinimum:data.policy.freeThresholdMinor===null?null:data.policy.freeThresholdMinor/100};
export const services=[];
export const serviceTypes={home:'Home delivery',parcel_locker:'Pickup box',staffed_counter:'Staffed pickup point',retailer_branch:'Store collection'};
let fulfilment=data.fulfilment;
const addressKey=a=>JSON.stringify(['name','street','unit','postcode','city'].map(k=>String(a?.[k]||'').replace(/\s/g,'').toLowerCase()));
const byAddress=new Map([[addressKey(fulfilment.address),fulfilment]]);
if(data.initialFulfilment)byAddress.set(addressKey(data.initialFulfilment.address),data.initialFulfilment);
export function validateAddress(address){return byAddress.has(addressKey(address))?[]:['Save a supported delivery address to obtain a quote'];}
export function itemEstimate(variant,address){
  if(variant.state!=='in_stock'||validateAddress(address).length)return null;
  const available=(byAddress.get(addressKey(address)).optionsBySku[variant.skuId]||[]).filter(o=>o.type==='home'&&o.supply==='on_hand');
  return available.length?available.reduce((a,b)=>a.readyDays<=b.readyDays?a:b).arrival:null;
}

const couponQuotes=new Map();
const productRequests=new Map();
const productKey=(v,a)=>JSON.stringify([v.skuId,addressKey(a)]);
const inquiryKey=draft=>JSON.stringify([draft.revision,draft.cart,addressKey(draft.address),draft.coupon||'',data.account]);
function nativeQuery(draft){
  if(!data.couponProgramme||draft.cart.length!==1||draft.cart[0].quantity!==1||validateAddress(draft.address).length||['unvalidated','pending','invalid'].includes(draft.addressStatus))return null;
  const found=byVariant(draft.cart[0].key);
  return found&&found.variant.state!=='unavailable'?new URLSearchParams({...draft.address,offer_id:found.variant.offerId,quantity:'1',coupon_code:draft.coupon||''}):null;
}
const couponReasons={coupon_sign_in_required:'Sign in is required for this code.',coupon_not_found:'This code is not recognised.',coupon_already_redeemed:'This code has already been used.',coupon_not_active:'This code is outside its validity dates.',coupon_wrong_concept:'This code does not cover this product type.',coupon_minimum_not_met:'The product subtotal is below the code’s minimum.',coupon_requires_purchasable_quote:'This code requires an available delivery quote.'};
function couponTerms({e,money}){
  const account=data.account;
  if(!account)return '<p>No coupon programme is published by this retailer.</p>';
  const terms=account.coupons.map(c=>`<li><strong>${e(c.code)}</strong>: ${c.kind==='percent'?`${c.value}% off products`:`${money(c.value/100)} off products`}; minimum product subtotal ${money(c.minimum_subtotal_minor/100)} before discount. ${c.concept_ids.length?`Applies to ${c.concept_ids.map(id=>e(data.couponScopes[id]||id)).join(', ')}.`:'Applies to all listed product types.'} Valid ${e(c.valid_from)} through ${e(c.valid_until)}. ${c.redeemed?'Already used.':'Not yet used.'}</li>`).join('');
  return `<p>${account.signed_in?'You are signed in.':'You are signed out.'}</p>${terms?`<ul>${terms}</ul>`:'<p>No codes are available in this account.</p>'}<p>One code per checkout. Codes are case-sensitive. Free delivery is assessed after discounts; applying a code can increase a delivery charge. All charges can be inspected before payment.</p>`;
}

export function quote(cart,draft,conf,revision){
  const errors=validateAddress(draft.address);
  if(['unvalidated','pending','invalid'].includes(draft.addressStatus))errors.push(draft.addressStatus==='pending'?'Delivery calculation is pending':'Save the current address to refresh delivery');
  if(cart.length!==1||cart[0]?.quantity!==1)errors.push('A delivery inquiry can contain one item at a time');
  const found=cart[0]&&byVariant(cart[0].key);
  if(!found||found.variant.state==='unavailable')errors.push('This item cannot be ordered');
  const bound=byAddress.get(addressKey(draft.address));
  const cached=data.couponProgramme?couponQuotes.get(inquiryKey(draft)):null;
  const authoritative=cached?.value;
  if(data.couponProgramme&&!authoritative)errors.push(cached?.error||'Delivery and discount calculation is pending');
  const options=authoritative?authoritative.options:data.couponProgramme?[]:found?(bound?.optionsBySku[found.variant.skuId]||[]):[];
  if(!options.length)errors.push('No delivery service is available for this item and address');
  const base={revision,errors,shipments:[],coupon:{status:'none'},total:null,canSplit:false,selectionChanges:[]};
  if(errors.length)return base;
  const subtotal=authoritative?authoritative.subtotal_minor/100:found.variant.price;
  const discount=authoritative?authoritative.discount_minor/100:0;
  const coupon=authoritative?{...authoritative.coupon,status:authoritative.coupon.status==='not_requested'?'none':authoritative.coupon.status,reason:couponReasons[authoritative.coupon.reason]||authoritative.coupon.reason}:{status:'none'};
  const requested=draft.deliveryChoices.stock;
  const selected=options.find(o=>o.id===requested)||options.find(o=>o.type==='home')||options[0];
  const line={...cart[0],...found,index:0};
  const shipment={key:'stock',lines:[line],sources:[selected.sourceId],backorder:found.variant.state==='backorder',
    brand:found.product.brand,base:subtotal,discount,options,selected,
    arrival:selected.arrival,fee:selected.fee,tariff:selected.fee,qualified:false,local:false,destination:selected.location.id};
  return {...base,subtotal,discount,coupon,quoteId:authoritative?.quote_id,shipping:selected.shippingMinor/100,total:selected.totalMinor/100,
    shipments:[shipment],selectionChanges:requested&&requested!==selected.id?[{group:'stock',previous:requested,selected:selected.id}]:[]};
}
export const worldBinding={
  configuration:data.configuration,siteId:data.siteId,siteName:data.siteName,
  rememberedAddress:data.rememberedAddress,initialInstructions:data.initialInstructions,checkoutCapabilities:data.checkoutCapabilities,
  inquiryKey,
  async ensureProduct(p,v,address){
    if(!data.lazyFulfilment||v.state==='unavailable')return false;
    const key=productKey(v,address);
    if(productRequests.has(key))return false;
    const query=new URLSearchParams({...address,sku_id:v.skuId});
    productRequests.set(key,{pending:true});
    try{
      const response=await fetch('/api/fulfilment?'+query),value=await response.json();
      if(!response.ok)throw Error(value.error||'Delivery details could not be loaded');
      const bound=byAddress.get(addressKey(address))||{address:{...address},optionsBySku:{}};
      bound.optionsBySku={...bound.optionsBySku,...value.optionsBySku};
      byAddress.set(addressKey(address),bound);
      productRequests.set(key,{value});
    }catch(error){productRequests.set(key,{error:error.message});}
    return true;
  },
  async ensureQuote(draft){
    const query=nativeQuery(draft),key=inquiryKey(draft);
    if(!query||couponQuotes.has(key))return false;
    couponQuotes.set(key,{pending:true});
    try{
      const response=await fetch('/api/quote?'+query),value=await response.json();
      if(!response.ok)throw Error(value.error||'Delivery quote is unavailable');
      couponQuotes.set(key,{value});
    }catch(error){couponQuotes.set(key,{error:error.message});}
    // Results are bound to their exact input, never to whichever draft is now open.
    return key===inquiryKey(draft);
  },
  async refresh(address){const result=await fetch('/api/fulfilment?'+new URLSearchParams(address));const next=await result.json();if(!result.ok)throw Error(next.error||'Delivery is unavailable for this address');fulfilment=next;byAddress.set(addressKey(address),next);},
  stockText(v){return v.state==='unavailable'?'Unavailable':v.state==='backorder'?'Available to order from the supplier':v.stock?'Stock available for dispatch':'Available in shops; delivery availability depends on your address';},
  supplierNotice(v){if(v.state!=='backorder')return '';return v.supplierOrder.disclosure==='product_page'?`Supplier order; allow approximately ${v.supplierOrder.wait_days} additional days before dispatch.`:'This item can be ordered from the supplier. See the delivery policy for lead-time information.';},
  decorate(root){
    const cities=[...new Set(Object.values(branches).map(b=>b.address.split(',')[0]))].join(', ');
    const change=text=>text.replaceAll('Northline',data.siteName).replaceAll('Uppsala and Stockholm',cities).replaceAll('home, work and time outdoors','walking and everyday journeys');
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
    while(walker.nextNode())walker.currentNode.textContent=change(walker.currentNode.textContent);
    for(const node of root.querySelectorAll('[aria-label]'))node.setAttribute('aria-label',change(node.getAttribute('aria-label')));
    const rows=root.querySelectorAll('[data-service-row]');
    const optionById=rows.length?new Map([...byAddress.values()].flatMap(b=>Object.values(b.optionsBySku).flat()).map(o=>[o.id,o])):new Map();
    for(const row of rows){
      const option=optionById.get(row.querySelector('input').value);
      if(!option||row.dataset.nativeDecorated)continue;
      row.dataset.nativeDecorated='true';
      const arrangements={carrier_assigned:'Delivery day assigned by the carrier',choose_day:'Delivery day can be chosen',choose_day_and_slot:'Delivery day and time slot can be chosen',collection_after_ready:'Collect after the parcel is ready'};
      const note=document.createElement('p');note.textContent=arrangements[option.scheduling]||option.scheduling.replaceAll('_',' ');row.append(note);
      if(option.collectionHours){const hours=document.createElement('p');hours.textContent='Collection hours: '+Object.entries(option.collectionHours).map(([day,slots])=>day+': '+(slots.length?slots.map(slot=>slot.join('–')).join(', '):'closed')).join('; ');row.append(hours);}
    }
    document.title=change(document.title);
  },
  productServices({p,v,e,link,state,conf,g}){
    const estimate=itemEstimate(v,state.remembered);
    const request=data.lazyFulfilment&&v.state!=='unavailable'?productRequests.get(productKey(v,state.remembered)):null;
    const waiting=data.lazyFulfilment&&v.state!=='unavailable'&&!request?.value&&!request?.error;
    const sources=v.sourceStock.map(s=>`<li>${e(s.name)} · ${e(s.kind)} · ${s.quantity} in stock${s.shippingEnabled?' · Dispatch available':' · No dispatch from this location'}</li>`).join('');
    const pickupRows=data.lazyFulfilment?(byAddress.get(addressKey(state.remembered))?.optionsBySku[v.skuId]||[]).filter(q=>q.type==='retailer_branch').map(q=>({branch_name:q.location.name,requires_transfer:q.requiresTransfer,ready_days:q.readyDays})):v.pickup;
    const pickup=pickupRows.map(q=>`<li>${e(q.branch_name)}: ${q.requires_transfer?`Warehouse transfer; estimated ${q.ready_days} days`:'In stock locally'}</li>`).join('');
    return `<section aria-label="Availability and delivery"><h2>Availability and delivery</h2>${waiting?'<p role="status">Calculating delivery details…</p>':request?.error?`<p role="status">${e(request.error)}</p>`:''}${estimate?`<p>Estimated home delivery to ${e(state.remembered.postcode)}: <strong>${e(estimate)}</strong></p><p>Estimate for this selected item only.${data.quoteAsOf?` Calculated as of ${e(data.quoteAsOf)}.`:''}</p>`:''}<p>${e(this.stockText(v))}</p><ul>${sources}</ul>${pickup?`<h3>Shop availability</h3><ul>${pickup}</ul>`:''}<p>${link('info/stores','Shop details')}${conf.policy==='footer'?'':conf.policy==='checkout'?` · Delivery charges and policy are shown in ${link('checkout',e(g.checkout))}`:` · ${link('info/contact',e(g.help))} can help with delivery questions`}</p></section>`;
  },
  couponForm({state,conf,e,money,link}){
    if(!data.couponProgramme)return '<p>No coupon programme is published by this retailer.</p>';
    return `<form data-form="coupon"><label>Discount code<input name="coupon" value="${e(state.coupon)}" autocomplete="off"></label><button>Apply code</button></form><p>${link('info/coupons','Account and discount-code terms')}</p>${conf.opaque?'':couponTerms({e,money})}`;
  },
  couponDetails:couponTerms,
  policyContent({e,money}){
    const threshold=data.policy.freeThresholdMinor;
    return `<h3>Delivery charges and services</h3><p>Charges depend on the carrier, service tier, dispatch location and delivery destination. All available services, estimated dates and full charges are displayed after the address is saved.</p><p>Delivery countries: ${data.policy.deliveryCountries.map(e).join(', ')}.</p>${threshold===null?'<p>No free-delivery threshold is offered.</p>':`<p>Domestic standard delivery is free from ${money(threshold/100)}${data.couponProgramme?' in product value after discounts':''}. Express upgrades retain their extra charge. International shipments do not qualify for the domestic waiver.</p>`}<p>Local shop stock is separate from warehouse stock. ${data.policy.transferEnabled?'Warehouse-to-shop transfers are supported where stock and routes permit.':'Warehouse-to-shop transfers are not supported.'}</p><p>Supplier orders may require an additional wait before dispatch. A current delivery inquiry shows its complete estimated date.</p>`;
  },
  article(id,{e,link,money}){
    if(id==='coupons')return couponTerms({e,money});
    if(id==='sizing')return '<p>Check the EU size, width and fit guidance on the selected product page. Regular-width task requests correspond to the standard width label. Reference mass describes the specified reference configuration.</p>';
    if(id==='care')return '<p>Follow the care instructions supplied with your footwear. Material and construction details are listed on each product page.</p>';
    if(id==='about')return `<p>${e(data.siteName)} offers the products listed in this catalog.</p>`;
    if(id==='stores'&&!Object.keys(branches).length)return '<p>No physical shops are listed for this retailer.</p>';
    if(id==='stores')return Object.values(branches).map(b=>`<section><h3>${e(b.name)}</h3><address>${e(b.address)}</address><p>${e(b.hours)}</p></section>`).join('');
    if(id==='contact')return `<p>Contact details are not published in this catalog.</p>${link('info/stores','Our shops')}`;
    if(id==='returns'){
      const terms=data.policy.returnTerms;
      return terms?`<h3>Returns for online purchases</h3><p>Return within ${e(terms.window_days)} days of receiving your order.</p><p>${e(terms.conditions)}</p><p>Return delivery: ${e(terms.return_delivery)}</p><p>${e(terms.shop_returns)}</p>`:'<p>Return terms are not published in this catalog.</p>';
    }
    if(id==='orders'||id.startsWith('order-'))return '<p>No existing order information is available.</p>';
    if(id==='terms')return '<p>Prices and delivery charges are shown in Swedish kronor. Inspect the full delivery inquiry before payment.</p>';
    if(id==='privacy')return '<p>This shop remembers your selected options, delivery address and inquiry in this browser.</p>';
    return null;
  },
};
