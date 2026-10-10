// Central illustrative evaluator; production Product/world oracle adoption is pending.
import {byVariant} from './catalog.js';
export const worldBinding = null;
export const policy = {freeMinimum:1000, standard:49, bulky:249, transfer:19, bulkyTransfer:49, coupon:'WELCOME10', couponMinimum:500, couponPercent:10};
export const shopContact = {email:'support@northline.example',phone:'018-555 010',hours:'Monday to Friday, 09:00–17:00'};
export const branches = {uppsala:{name:'Uppsala shop',address:'Storgatan 8, Uppsala',hours:'Monday–Friday 10:00–18:00; Saturday 10:00–16:00; Sunday closed'},stockholm:{name:'Stockholm shop',address:'Torggatan 12, Stockholm',hours:'Monday–Friday 10:00–18:00; Saturday 10:00–16:00; Sunday closed'}};
export const initialAddress = {name:'Alex Lind',street:'Parkgatan 4',postcode:'75310',city:'Uppsala'};
export const serviceTypes = {home:'Home delivery',locker:'Pickup box',counter:'Staffed pickup point',retailer_branch:'Store collection'};
// Mock contracts and points, not these companies' real rates or geographic coverage.
export const services = [
  {id:'postnord-home',company:'PostNord',name:'Home delivery',type:'home',regular:49,bulky:249,extraDays:0},
  {id:'dhl-home',company:'DHL',name:'Home delivery',type:'home',regular:59,bulky:279,extraDays:1},
  {id:'instabox-locker',company:'Instabox',name:'Parcel locker',type:'locker',regular:39,extraDays:0},
  {id:'dhl-counter',company:'DHL',name:'ServicePoint',type:'counter',regular:49,extraDays:1},
];
const pickupPoints = {
  uppsala:[
    {id:'uppsala-station',type:'locker',name:'Central station lockers',address:'Stationsgatan 2, Uppsala'},
    {id:'uppsala-market',type:'locker',name:'Market Hall lockers',address:'Marknadsgatan 6, Uppsala'},
    {id:'uppsala-grocery',type:'counter',name:'Kvarnbutiken ServicePoint',address:'Kvarngatan 5, Uppsala'},
    {id:'uppsala-news',type:'counter',name:'Torget ServicePoint',address:'Torggatan 3, Uppsala'},
  ],
  stockholm:[
    {id:'stockholm-station',type:'locker',name:'Central station lockers',address:'Stationsgatan 2, Stockholm'},
    {id:'stockholm-market',type:'locker',name:'Market Hall lockers',address:'Marknadsgatan 6, Stockholm'},
    {id:'stockholm-grocery',type:'counter',name:'Kvarnbutiken ServicePoint',address:'Kvarngatan 5, Stockholm'},
    {id:'stockholm-news',type:'counter',name:'Torget ServicePoint',address:'Torggatan 3, Stockholm'},
  ],
};
export function validateAddress(address) {
  const errors=[];
  for (const key of ['name','street','city']) if (!address?.[key]?.trim()) errors.push(`${key} is required`);
  if (!/^\d{5}$/.test((address?.postcode || '').replace(/\s/g,''))) errors.push('Enter a five-digit Swedish postcode');
  return errors;
}
function date(days) {const d=new Date('2026-10-01T12:00:00Z');d.setUTCDate(d.getUTCDate()+days);return d.toLocaleDateString('en-GB',{day:'numeric',month:'long',year:'numeric',timeZone:'UTC'});}
function areaFor(address) {return address.postcode.replace(/\s/g,'').startsWith('75')?'uppsala':'stockholm';}
export function itemEstimate(variant,address) {
  if (variant.state!=='in_stock'||validateAddress(address).length) return null;
  return date(variant.days+(areaFor(address)==='uppsala'?0:2));
}

// Source partitions are derived centrally. A source's in-stock lines always stay
// together; optional splits combine whole sources sharing the same readiness date.
function planGroups(lines,split) {
  const sourceMap=new Map(),brandMap=new Map();
  for (const line of lines) {
    const supplier=line.variant.state==='backorder',map=supplier?brandMap:sourceMap;
    const key=supplier?line.product.brand:line.variant.source;
    if (!map.has(key)) map.set(key,[]);
    map.get(key).push(line);
  }
  const sourceGroups=[...sourceMap.entries()].map(([source,items])=>({source,lines:items,days:Math.max(...items.map(l=>l.variant.days))}));
  const canSplit=new Set(sourceGroups.map(s=>s.days)).size>1;
  const stockGroups=new Map();
  for (const source of sourceGroups) {
    const key=split&&canSplit?`stock:ready-${source.days}`:'stock';
    if (!stockGroups.has(key))stockGroups.set(key,{key,lines:[],sources:[],days:0,backorder:false,brand:null});
    const group=stockGroups.get(key);group.lines.push(...source.lines);group.sources.push(source.source);group.days=Math.max(group.days,source.days);
  }
  const supplierGroups=[...brandMap.entries()].map(([brand,items])=>({key:`supplier:${brand}`,lines:items,sources:[],days:null,backorder:true,brand}));
  return {groups:[...stockGroups.values(),...supplierGroups],canSplit};
}
function deliveryOptions(group,address,qualified,conf) {
  const bulky=group.lines.some(l=>l.variant.bulky),area=areaFor(address),remote=area==='uppsala'?0:2;
  const locationHome={id:'home',name:'Your address',address:`${address.street}, ${address.postcode} ${address.city}`};
  const options=[];
  for (const service of services) {
    if ((bulky||group.backorder)&&service.type!=='home')continue;
    const locations=service.type==='home'?[locationHome]:pickupPoints[area].filter(p=>p.type===service.type);
    for (const location of locations) {
      const tariff=bulky?service.bulky:service.regular;
      options.push({id:service.id+(service.type==='home'?'':':'+location.id),serviceId:service.id,company:service.company,name:service.name,type:service.type,location,
        arrival:group.backorder?null:date(group.days+remote+service.extraDays),local:false,tariff,fee:qualified?0:tariff,qualified,payment:'online'});
    }
  }
  if (!group.backorder)for (const [id,branch] of Object.entries(branches)) {
    const local=id==='uppsala'&&group.lines.every(l=>l.quantity<=l.variant.branchStock);
    const transferring=group.lines.filter(l=>id!=='uppsala'||l.quantity>l.variant.branchStock);
    const tariff=local?0:Math.max(...transferring.map(l=>l.variant.bulky?policy.bulkyTransfer:policy.transfer));
    // Locally ready items may wait for the remaining items to transfer to this shop.
    const days=local?0:Math.max(...transferring.map(l=>l.variant.days))+2;
    options.push({id:`northline-collection:${id}`,serviceId:'northline-collection',company:'Northline',name:local?'Collect shop stock':'Order to shop',type:'retailer_branch',location:{id,name:branch.name,address:branch.address},arrival:local?'Ready today':date(days),local,tariff,fee:qualified?0:tariff,qualified,payment:conf.collectionPayment});
  }
  return options;
}
export function quote(cart,draft,conf,revision) {
  const errors=validateAddress(draft.address);
  const lines=cart.map((line,i)=>({...line,...byVariant(line.key),index:i}));
  for (const line of lines) {
    if (!line.variant||line.variant.state==='unavailable')errors.push('An item can no longer be ordered');
    if (!Number.isInteger(line.quantity)||line.quantity<1||line.quantity>20)errors.push('Quantity must be between 1 and 20');
  }
  if (errors.length)return {revision,errors,shipments:[],coupon:{status:'pending'},total:null,canSplit:false,selectionChanges:[]};
  const subtotal=lines.reduce((s,l)=>s+l.variant.price*l.quantity,0),code=(draft.coupon||'').trim().toUpperCase();
  const accepted=code===policy.coupon&&subtotal>=policy.couponMinimum;
  const coupon={code,status:!code?'none':accepted?'applied':'rejected',reason:code!==policy.coupon?'This code is not recognised.':`Spend at least ${policy.couponMinimum} SEK before this discount can apply.`};
  const discount=accepted?Math.floor(subtotal*policy.couponPercent/100):0;
  const allocations=lines.map(l=>({index:l.index,base:l.variant.price*l.quantity,discount:subtotal?Math.floor(discount*l.variant.price*l.quantity/subtotal):0,remainder:subtotal?discount*l.variant.price*l.quantity%subtotal:0}));
  let residual=discount-allocations.reduce((s,a)=>s+a.discount,0);
  for (const a of [...allocations].sort((a,b)=>b.remainder-a.remainder||a.index-b.index))if(residual-->0)a.discount++;
  let {groups,canSplit}=planGroups(lines,conf.split&&draft.split);
  const selectionChanges=[],choices={...(draft.deliveryChoices||{})};
  const stockGroups=groups.filter(g=>!g.backorder),stockLines=lines.filter(l=>l.variant.state==='in_stock');
  const requests=stockGroups.map(g=>choices[g.key]||(g.key.startsWith('stock:')?choices.stock:null));
  // A selected shop's local stock is one source, regardless of which warehouses
  // would otherwise fulfill home delivery. Do not split two ready-today pickups.
  if(stockLines.length&&requests.length&&requests.every(id=>id==='northline-collection:uppsala')&&stockLines.every(l=>l.quantity<=l.variant.branchStock)){
    groups=planGroups(lines,false).groups;canSplit=false;choices.stock='northline-collection:uppsala';
  }
  const shipments=groups.map(group=>{
    const base=group.lines.reduce((s,l)=>s+allocations[l.index].base,0),allocatedDiscount=group.lines.reduce((s,l)=>s+allocations[l.index].discount,0);
    const qualified=(conf.qualification==='basket'?subtotal-discount:base-allocatedDiscount)>=policy.freeMinimum;
    const options=deliveryOptions(group,draft.address,qualified,conf);
    const requested=choices[group.key]||(group.key.startsWith('stock:')?choices.stock:null);
    const selected=options.find(o=>o.id===requested)||options.find(o=>o.id==='postnord-home');
    if (requested&&selected.id!==requested)selectionChanges.push({group:group.key,previous:requested,selected:selected.id,reason:'The previous service or pickup point is no longer available for this shipment.'});
    return {...group,base,discount:allocatedDiscount,options,selected,arrival:selected.arrival,fee:selected.fee,tariff:selected.tariff,qualified,local:selected.local,
      destination:selected.type==='home'?'home':selected.location.id};
  });
  const shipping=shipments.reduce((s,g)=>s+g.fee,0);
  return {revision,errors:[],subtotal,discount,shipping,total:subtotal-discount+shipping,coupon,shipments,canSplit:conf.split&&canSplit,selectionChanges};
}
