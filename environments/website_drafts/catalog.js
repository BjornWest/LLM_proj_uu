// A bounded public authoring fixture, NOT a product-world exporter or assertion registry.
import {marketRangeFixture} from './market-range-fixture.js';
import {readMarketRange} from './market-range.js';
import {generatedProducts} from './generated-catalog.js';
import {normalizeProductContent} from './product-content.js';
const fact = (label, value, extra = {}) => ({label, value, ...extra});
const group = (heading, facts) => ({heading, facts});
const rows = [
  ['mela','Granvik Mela','Footwear','Granvik',849,'Everyday walking shoe with an enclosed construction and a closed heel.','shoe'],
  ['ridge','Granvik Ridge','Footwear','Granvik',1099,'Walking shoe with a deep-tread rubber outsole.','shoe'],
  ['stride','Liden Stride','Footwear','Liden',699,'A flexible lace-up shoe for everyday walking.','shoe'],
  ['trail','Liden Trail','Footwear','Liden',949,'A walking shoe with a reinforced toe and a textile lining.','shoe'],
  ['city','Klint City','Footwear','Klint',799,'An enclosed walking shoe with a removable footbed.','shoe'],
  ['haven','Klint Haven','Footwear','Klint',1199,'A leather walking shoe with a closed heel.','shoe'],
  ['desk','Liden Work Desk','Home','Liden',1499,'A compact desk with a drawer and cable opening.','desk'],
  ['lamp','Granvik Task Lamp','Home','Granvik',399,'A plug-in desk lamp with an adjustable shade.','lamp'],
  ['kettle','Klint Kettle','Home','Klint',599,'An electric kettle with automatic shutoff.','kettle'],
  ['shelf','Liden Shelf','Home','Liden',1299,'A freestanding shelf with three adjustable shelves.','shelf'],
  ['cup','Klint Stoneware Cup','Home','Klint',129,'A glazed stoneware cup with a handle.','cup'],
  ['throw','Granvik Woven Throw','Home','Granvik',449,'A woven cotton throw with fringed edges.','throw'],
  ['tent','Granvik Two-person Tent','Outdoors','Granvik',1899,'A two-person tent with a separate outer flysheet.','tent'],
  ['bottle','Liden Trail Bottle','Outdoors','Liden',249,'A stainless-steel drinking bottle with a screw cap.','bottle'],
  ['pack','Klint Day Pack','Outdoors','Klint',649,'A day pack with an internal zipped pocket.','pack'],
  ['mat','Granvik Camping Mat','Outdoors','Granvik',499,'A foam camping mat that folds for storage.','mat'],
  ['torch','Liden Trail Torch','Outdoors','Liden',299,'A hand torch supplied with a wrist strap.','torch'],
  ['stove','Klint Camp Stove','Outdoors','Klint',899,'A gas camping stove; fuel is sold separately.','stove'],
  ['headphones','Granvik Headphones','Electronics','Granvik',999,'Wireless over-ear headphones with a USB charging cable.','headphones'],
  ['speaker','Liden Speaker','Electronics','Liden',699,'A portable wireless speaker with a carry strap.','speaker'],
  ['keyboard','Klint Keyboard','Electronics','Klint',499,'A wired keyboard with a Nordic key layout.','keyboard'],
  ['mouse','Granvik Mouse','Electronics','Granvik',299,'A wired optical mouse with three buttons.','mouse'],
  ['hub','Liden USB Hub','Electronics','Liden',449,'A four-port USB hub with a fixed USB-C lead.','hub'],
  ['charger','Klint USB Charger','Electronics','Klint',349,'A USB-C mains charger; device cable is sold separately.','charger'],
];

const choice = (key,label,values) => [{key,label,values}];
function optionsFor(kind) {
  switch (kind) {
    case 'shoe': return [{key:'size',label:'Size (EU)',values:['40','42','44']},{key:'colour',label:'Colour',values:['Black','Oat']}];
    case 'desk': case 'shelf': return choice('finish','Finish',['White','Dark gray']);
    case 'lamp': return choice('colour','Colour',['White','Black']);
    case 'kettle': return choice('capacity','Capacity',['1.7 L','1.0 L']);
    case 'throw': return choice('colour','Colour',['Sand','Blue']);
    case 'tent': return choice('package','Package',['Tent only','Tent and footprint']);
    case 'bottle': return choice('capacity','Capacity',['750 mL','1 L']);
    case 'pack': return choice('capacity','Capacity',['22 L','28 L']);
    case 'mat': return choice('length','Length',['185 cm','200 cm']);
    case 'torch': return choice('output','Light output',['240 lm','400 lm']);
    case 'headphones': return choice('colour','Colour',['Black','Stone']);
    case 'speaker': return choice('colour','Colour',['Black','Blue']);
    case 'keyboard': return choice('layout','Key layout',['Nordic','UK']);
    case 'mouse': return choice('colour','Colour',['Black','White']);
    case 'charger': return choice('power','Power output',['30 W','45 W']);
    default: return []; // Cup, stove and hub have one actual configuration.
  }
}
function specifications(kind, selection) {
  const size=selection.size, colour=selection.colour || selection.finish || (kind==='cup'?'White':'Natural');
  const material = {shoe:'Leather and textile', desk:'Painted fibreboard', shelf:'Painted fibreboard', lamp:'Steel', kettle:'Stainless steel', cup:'Stoneware', throw:'Cotton', tent:'Polyester flysheet', bottle:'Stainless steel', pack:'Polyester', mat:'Closed-cell foam', torch:'Aluminium', stove:'Stainless steel'}[kind] || 'Polymer housing';
  const construction = group('Materials and care', [fact('Main material', material), fact('Colour', colour), fact('Care', kind === 'shoe' ? 'Wipe clean; allow to dry at room temperature.' : 'Follow the supplied care instructions.')]);
  if (kind === 'shoe') return [group('Fit and construction', [fact('Size', size, {unit:'EU'}), fact('Heel', 'Closed'), fact('Fastening','Laces'), fact('Mass', 260 + (Number(size) - 40) * 10, {unit:'g', qualifier:`One shoe, selected EU size ${size}`}), fact('Footbed', 'Removable')]), construction, group('Measurements', [fact('Internal width', null, {status:'unknown', qualifier:'Not published by the supplier'})])];
  const dimensions = {desk:['Width',100,'cm'], shelf:['Height',180,'cm'], lamp:['Height',42,'cm'], kettle:['Capacity',parseFloat(selection.capacity),'L'], cup:['Capacity',300,'mL'], throw:['Length',180,'cm'], tent:['Occupancy',2,'people'], bottle:['Capacity',selection.capacity==='1 L'?1000:750,'mL'], pack:['Capacity',parseFloat(selection.capacity),'L'], mat:['Length',parseFloat(selection.length),'cm'], torch:['Light output',parseFloat(selection.output),'lm'], stove:['Mass',320,'g'], headphones:['Battery runtime',30,'h'], speaker:['Battery runtime',12,'h'], keyboard:['Key layout',selection.layout,''], mouse:['Connection','USB-A',''], hub:['Ports',4,''], charger:['Power output',parseFloat(selection.power),'W']}[kind];
  const components = kind === 'headphones' ? ['Headphones','USB charging cable'] : kind === 'tent' ? ['Inner tent','Flysheet','Pegs','Storage bag',...(selection.package==='Tent and footprint'?['Footprint']:[])] : [kind === 'stove' ? 'Stove (fuel not included)' : 'Product', 'Care instructions'];
  return [group('Specification', [fact(...dimensions.slice(0,2), {unit:dimensions[2]}),...(selection.package?[fact('Package',selection.package)]:[])]), construction,group('Included in the box', [fact('Components',components)])];
}

export const authoringProducts = rows.map(([id,name,category,brand,price,introduction,kind], index) => {
  const options = optionsFor(kind);
  const tuples = options.reduce((tuples,option)=>tuples.flatMap(tuple=>option.values.map(value=>({...tuple,[option.key]:value}))),[{}]);
  const variants = tuples.map((selection,v) => {
    const state = id === 'mela' && selection.size === '44' ? 'unavailable' : ['ridge','trail','headphones'].includes(id) ? 'backorder' : 'in_stock';
    const central = index % 3 === 0 || id === 'cup';
    return {key:`${id}-${v}`,selection,price:price + (v % 2) * 50,state,stock:state === 'in_stock' ? 20 : 0,bulky:['desk','shelf'].includes(kind),source:central ? 'Central warehouse' : 'Regional warehouse',days:central ? 4 : 7,
      branchStock:state === 'in_stock' && !['desk','shelf'].includes(kind) && v === 0 ? 3 : 0,
      details:specifications(kind,selection)};
  });
  const type={shoe:'Walking shoes',desk:'Desks',lamp:'Lighting',kettle:'Kettles',shelf:'Shelving',cup:'Cups',throw:'Throws',tent:'Tents',bottle:'Drinking bottles',pack:'Day packs',mat:'Camping mats',torch:'Torches',stove:'Camping stoves',headphones:'Headphones',speaker:'Speakers',keyboard:'Keyboards',mouse:'Mice',hub:'USB hubs',charger:'USB chargers'}[kind];
  return {id,name,category,brand,type,marketRange:readMarketRange(marketRangeFixture[id],id),introduction:kind==='keyboard'?'A wired keyboard with a selectable key layout.':introduction,options,variants,descriptions:[{heading:'About this product',text:kind==='keyboard'?'A wired keyboard with a selectable key layout.':introduction},{heading:'Before you choose',text:kind === 'shoe' ? 'Choose your usual EU size. The listed mass describes one shoe in the selected size.' : options.length?`Check the ${options[0].label.toLowerCase()} selection and the included components before ordering.`:'Check the dimensions, materials and included components before ordering.'}], guide:kind === 'shoe' ? 'Sizing' : 'Product care'};
});
export const products = [...authoringProducts, ...generatedProducts].map(normalizeProductContent);
export const categories = [...new Set(products.map(p=>p.category))];
export const brands = [...new Set(products.map(p=>p.brand))].sort((a,b)=>a.localeCompare(b));
export const typesFor = category => [...new Set(products.filter(p=>!category||p.category===category).map(p=>p.type))].sort((a,b)=>a.localeCompare(b));

// Resolve only actual producer tuples. A change to an earlier axis can invalidate
// a later one; choose the first compatible tuple rather than synthesize a SKU.
export function resolveProduct(id, selection = {}) {
  const product = products.find(p => p.id === id);
  if (!product) return null;
  let candidates=product.variants;
  for(const option of product.options){const value=selection[option.key];const compatible=candidates.filter(v=>v.selection[option.key]===(value||candidates[0].selection[option.key]));if(compatible.length)candidates=compatible;}
  const variant = candidates[0];
  return {product,variant};
}
export function byVariant(key) {
  for (const product of products) {const variant = product.variants.find(v => v.key === key); if (variant) return {product,variant};}
  return null;
}
