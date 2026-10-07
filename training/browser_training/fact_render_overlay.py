"""Opt-in copied-renderer overlay; never mutate source or shared Website assets.

Each seam must match exactly once. Source drift is an explicit error, not a
silent partial installation. Native field/slot identities are qualification
metadata, not a fabricated public assertion registry.
"""
from hashlib import sha256
from pathlib import Path

ASSET = Path(__file__).parent / 'assets' / 'fact_render_recorder.js'


def _once(source, before, after):
    count = source.count(before)
    if count != 1:
        raise ValueError(f'Renderer seam changed: expected once, found {count}: {before[:90]}')
    return source.replace(before, after)


HELPERS = r'''
const factRecorder=createFactRecorder({enabled:true,sink:records=>{
  if(!globalThis.__recordFactCommit)throw new Error('Private recording collector is missing');
  records.meta.html=document.querySelector('#app').outerHTML;
  globalThis.__recordFactCommit(records);
}});
function factProductId(p){return p.canonicalProductId??p.id;}
function factState(p,v){return {site,product_id:factProductId(p),page_id:p.id,sku_id:v.skuId??null,offer_id:v.offerId??null,variant_key:v.key,selection:{...v.selection}};}
function fieldBinding(f,p,v){return {source_family:'retailer',site_id:site,authority:f.field?'native_public_field':f.slotId?'selected_slot':'unmapped',field:f.field??null,slot_id:f.slotId??null,assertions:f.assertions??[],subject_type:f.subjectType??null,subject_id:f.subjectId??null,displayed_value:f.value,unit:f.unit??null,qualifier:f.qualifier??null,product_id:factProductId(p),page_id:p.id,sku_id:v.skuId??null,status:f.status??null,granular_assertions: false};}
function recordedFactRow(f,p,v,mode){
  const occurrence=factRecorder.occurrence(fieldBinding(f,p,v),factState(p,v));
  const label=fragment([{text:f.label,part:'label'}]);
  let value;
  if(Array.isArray(f.value)) {
    const seg=[{html:'<ul>',text:''}];
    f.value.forEach((v,i)=>seg.push({html:'<li>',text:''},{text:v,part:`value-${i}`},{html:'</li>',text:''}));
    seg.push({html:'</ul>',text:''});value=fragment(seg);
  } else value=fragment([{text:f.value,part:'value'},...(f.unit?[{text:' '},{text:f.unit,part:'unit'}]:[])]);
  const qualifier=f.qualifier?fragment([{text:f.qualifier,part:'qualifier'}]):fragment([]);
  const suffix=f.qualifier?(['table','highlights'].includes(mode)?`<p>${qualifier.html}</p>`:`<br><small>${qualifier.html}</small>`):'';
  const body={html:value.html+suffix,text:value.text+qualifier.text,parts:[...value.parts,...qualifier.parts.map(part=>({...part,start:part.start+value.text.length,end:part.end+value.text.length}))]};
  if(mode==='table')return `<tr>${factRecorder.element(`<th scope="row">${label.html}</th>`,occurrence,label)}${factRecorder.element(`<td>${body.html}</td>`,occurrence,body)}</tr>`;
  return factRecorder.element(`<dt>${label.html}</dt>`,occurrence,label)+factRecorder.element(`<dd>${body.html}</dd>`,occurrence,body);
}
function recordedListingPrice(p,v){
  const content=fragment([{text:money(v.price),part:'amount_with_currency'}]);
  const occurrence=factRecorder.occurrence({authority:'renderer_native_scalar',field:'listing_price',product_id:factProductId(p),page_id:p.id,sku_id:v.skuId??null,offer_id:v.offerId??null,value:v.price,value_minor:v.priceMinor??null,currency:v.currency??'SEK'},factState(p,v));
  return factRecorder.element(`<p class="amount">${content.html}</p>`,occurrence,content);
}
function recordedSelection(p,v){
  const segments=[{text:'Selected: '}];
  Object.entries(v.selection).forEach(([k,value],i)=>{if(i)segments.push({text:' · '});segments.push({text:p.options.find(o=>o.key===k).label,part:`${k}.label`},{text:' '},{text:value,part:`${k}.value`});});
  const content=fragment(segments),occurrence=factRecorder.occurrence({authority:'renderer_native_selection',product_id:factProductId(p),page_id:p.id,sku_id:v.skuId??null,selection:{...v.selection}},factState(p,v));
  return factRecorder.element(`<p>${content.html}</p>`,occurrence,content);
}
function recordedQuoteAmount(result,field){
  const content=fragment([{text:money(result[field]),part:'amount_with_currency'}]);
  const occurrence=factRecorder.occurrence({authority:'renderer_native_quote_scalar',field,quote_id:result.quoteId??null,value:result[field],currency:'SEK'}, {site,quote_id:result.quoteId??null,quote_result:result,draft:state});
  return factRecorder.element(field==='total'?`<dd><strong>${content.html}</strong></dd>`:`<dd>${content.html}</dd>`,occurrence,content);
}
function recordedRecipient(result){
  const segments=[{text:'Recipient: '},{text:state.address.name,part:'name'},{text:', '},{text:state.address.street,part:'street'},...(state.address.unit?[{text:', Apartment '},{text:state.address.unit,part:'unit'}]:[]),{text:', '},{text:state.address.postcode,part:'postcode'},{text:' '},{text:state.address.city,part:'city'},{text:'.'}];
  const content=fragment(segments),occurrence=factRecorder.occurrence({authority:'renderer_native_recipient',quote_id:result.quoteId??null}, {site,quote_id:result.quoteId??null,quote_result:result,draft:state});
  return factRecorder.element(`<p>${content.html}</p>`,occurrence,content);
}
function recordedShipmentCharge(result,s){
  const content=fragment([{text:'Delivery charge: '},{text:money(s.fee),part:'amount_with_currency'},...(s.qualified?[{text:' · Free-delivery minimum reached',part:'qualification'}]:[])]);
  const occurrence=factRecorder.occurrence({authority:'renderer_native_shipment_scalar',field:'fee',quote_id:result.quoteId??null,shipment_key:s.key??null,shipment_index:result.shipments.indexOf(s),selected_service:s.selected,value:s.fee,currency:'SEK'}, {site,quote_id:result.quoteId??null,quote_result:result,shipment:s,draft:state});
  return factRecorder.element(`<p>${content.html}</p>`,occurrence,content);
}
function recordedShipmentIdentity(result,s){
  const service=fragment([{text:s.selected.company,part:'company'},{text:' — '},{text:serviceTypes[s.selected.type],part:'type'},{text:' — '},{text:s.selected.name,part:'name'}]);
  const location=fragment([{text:s.selected.location.name,part:'name'},{text:' · '},{text:s.selected.location.address,part:'address'}]);
  const effective={site,quote_id:result.quoteId??null,quote_result:result,shipment:s,draft:state};
  const binding={authority:'renderer_native_shipment_selection',quote_id:result.quoteId??null,shipment_index:result.shipments.indexOf(s),selected_service:s.selected};
  const serviceOccurrence=factRecorder.occurrence({...binding,field:'selected_service'},effective);
  const locationOccurrence=factRecorder.occurrence({...binding,field:'selected_location'},effective);
  return factRecorder.element(`<p>${service.html}</p>`,serviceOccurrence,service)+factRecorder.element(`<p>${location.html}</p>`,locationOccurrence,location);
}
function commitFacts(kind){const app=document.querySelector('#app');factRecorder.commit(app,{kind,url:location.href,state_key:stateKey,route:{role:route().role,id:route().id},draft:state,html:app.outerHTML});}
'''


def instrument_shop(source, *, enabled=False):
    """Return new source and receipt; disabled returns byte-identical input."""
    if not isinstance(source, str) or type(enabled) is not bool:
        raise TypeError('Source text and explicit boolean required')
    original = sha256(source.encode()).hexdigest()
    if not enabled:
        return source, {'enabled': False, 'source_sha256': original, 'output_sha256': original, 'seams': 0}
    source = "import {createFactRecorder,fragment} from './fact-recorder.js';\n" + source
    source = _once(source, "function render({captureDisclosures=true}={}) {", HELPERS + "\nfunction render({captureDisclosures=true}={}) {\n  factRecorder.begin();")
    source = _once(source, '${group.facts.map(f=>`<tr><th scope="row">${e(f.label)}</th><td>${factValue(f)}${f.qualifier?`<p>${e(f.qualifier)}</p>`:\'\'}</td></tr>`).join(\'\')}', "${group.facts.map(f=>recordedFactRow(f,product,variant,'table')).join('')}")
    source = _once(source, '${group.facts.map(f=>`<dt>${e(f.label)}</dt><dd>${factValue(f)}${f.qualifier?`<br><small>${e(f.qualifier)}</small>`:\'\'}</dd>`).join(\'\')}', "${group.facts.map(f=>recordedFactRow(f,product,variant,'definitions')).join('')}")
    source = _once(source, '${facts.map(f=>`<dt>${e(f.label)}</dt><dd>${factValue(f)}${f.qualifier?`<p>${e(f.qualifier)}</p>`:\'\'}</dd>`).join(\'\')}', "${facts.map(f=>recordedFactRow(f,p,v,'highlights')).join('')}")
    source = _once(source, '<p class="amount">${money(v.price)}</p>', '${recordedListingPrice(p,v)}')
    source = _once(source, '${p.options.length?`<p>Selected: ${Object.entries(v.selection).map(([k,value])=>`${e(p.options.find(o=>o.key===k).label)} ${e(value)}`).join(\' · \')}</p>`:\'\'}', "${p.options.length?recordedSelection(p,v):''}")
    source = _once(source, "  scheduleNativeQuote();\n}\ndocument.addEventListener('click'", "  scheduleNativeQuote();\n  commitFacts('full');\n}\ndocument.addEventListener('click'")
    source = _once(source, '  scheduleNativeQuote();\n}\nfunction addressForm()', "  scheduleNativeQuote();\n  commitFacts('partial');\n}\nfunction addressForm()")
    source = _once(source, "state.disclosures[node.dataset.disclosure]=node.open;save();}},true);", "state.disclosures[node.dataset.disclosure]=node.open;save();commitFacts('disclosure');}},true);")
    for field in ('subtotal','discount','shipping'):
        source = _once(source, '<dd>${money(result.'+field+')}</dd>', '${recordedQuoteAmount(result,"'+field+'")}')
    source = _once(source, '<dd><strong>${money(result.total)}</strong></dd>', '${recordedQuoteAmount(result,"total")}')
    source = _once(source, '<p>Recipient: ${e(state.address.name)}, ${e(state.address.street)}${state.address.unit?`, Apartment ${e(state.address.unit)}`:\'\'}, ${e(state.address.postcode)} ${e(state.address.city)}.</p>', '${recordedRecipient(result)}')
    source = _once(source, '<p>Delivery charge: ${money(s.fee)}${s.qualified?\' · Free-delivery minimum reached\':\'\'}</p>', '${recordedShipmentCharge(result,s)}')
    source = _once(source, '<p>${e(s.selected.company)} — ${e(serviceTypes[s.selected.type])} — ${e(s.selected.name)}</p><p>${e(s.selected.location.name)} · ${e(s.selected.location.address)}</p>', '${recordedShipmentIdentity(result,s)}')
    return source, {'enabled': True, 'recorder_sha256':sha256(ASSET.read_bytes()).hexdigest(), 'source_sha256': original, 'output_sha256': sha256(source.encode()).hexdigest(), 'seams': 16, 'schema':'fact-render-dom-v1'}


def overlay_assets(assets, *, enabled=False):
    """Copy asset mapping; leave its bytes and caller's files untouched."""
    if type(enabled) is not bool:
        raise TypeError('Explicit boolean required')
    result = dict(assets)
    if not enabled:
        return result, {'enabled':False,'asset_bytes_identical':True}
    text, receipt = instrument_shop(assets['shop.js'].decode('utf-8'), enabled=True)
    result['shop.js'] = text.encode()
    result['fact-recorder.js'] = ASSET.read_bytes()
    return result, receipt
