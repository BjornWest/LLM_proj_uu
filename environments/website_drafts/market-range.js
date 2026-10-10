// Consumer of declared producer facts. Sampling/applicability belong to Product.
export const marketRangeField = 'product.facts.market_range';
export const rangeLabels = {women:"Women's",men:"Men's",unisex:'Unisex'};
export const rangeSelections = [
  {id:'women',label:"Women's",values:['women']},
  {id:'men',label:"Men's",values:['men']},
  {id:'unisex',label:'Unisex',values:['unisex']},
  {id:'women+unisex',label:"Women's + unisex",values:['women','unisex']},
  {id:'men+unisex',label:"Men's + unisex",values:['men','unisex']},
];

export function readMarketRange(record = {}, expectedId) {
  const publicRecord = record.public || record;
  const subject = record.product_id || publicRecord.product_id || expectedId;
  if(expectedId && subject !== expectedId) throw new Error('Market-range product identity mismatch');
  const declaration = record.fields?.[marketRangeField] || {
    status:publicRecord.fact_status?.market_range || 'unknown',
    ...(Object.hasOwn(publicRecord.facts || {},'market_range') ? {value:publicRecord.facts.market_range} : {}),
  };
  const {status,value} = declaration;
  if(!['known','unknown','not_applicable'].includes(status)) throw new Error('Invalid market-range status');
  if(status==='known' && (!subject || !Object.hasOwn(rangeLabels,value))) throw new Error('Invalid declared market range');
  if(status!=='known' && Object.hasOwn(declaration,'value')) throw new Error('Non-known range cannot carry a value');
  return {status,...(status==='known'?{value}:{}),subject};
}

export function matchesRange(declaration, selection) {
  if(!selection) return true; // Unfiltered browsing retains unrelated/unknown gear.
  const predicate = rangeSelections.find(choice=>choice.id===selection);
  return Boolean(predicate && declaration.status==='known' && predicate.values.includes(declaration.value));
}

export function availableRanges(assortment) {
  return Object.keys(rangeLabels).filter(value=>assortment.some(p=>p.marketRange?.status==='known' && p.marketRange.value===value));
}

// For the private realization ledger/fact-span adapter, never DOM attributes.
export function marketRangeAssertion(declaration) {
  return {id:'catalog.market_range',kind:'field_value',field:marketRangeField,
    subject:{kind:'product',id:declaration.subject},authority:'catalog_fact',
    status:declaration.status,...(declaration.status==='known'?{value:declaration.value}:{})};
}
