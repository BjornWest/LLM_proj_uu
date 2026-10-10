// Authoring metadata. The reviewer displays it; shopper renderers use unit IDs only.
import {variationSettings} from './variations.js';
export const typicalUnits = {
  home: [
    ['departments', 'Department directory', 'Department tiles and nested routes → collection teasers → sampled products → brands → advice → shops', 'Hughes / Lakeland'],
    ['editorial', 'Editorial collections', 'Collection banner → two featured products → collection banners → two featured products → compact help links', 'TOAST / Alpkit'],
    ['noticeboard', 'Shop noticeboard', 'Shop records and service notices → four sampled product list entries → handbook → shop introduction', 'Daunt Books'],
  ],
  results: [
    ['faceted', 'Faceted product grid', 'Query and count → adjacent filters → cards → numbered pages', 'Elgiganten / Lakeland'],
    ['ledger', 'Catalog ledger', 'Query → expandable filter form → comparison table → numbered pages', 'D&M Tools technical catalog (adapted)'],
    ['grouped', 'Category lists', 'Query → category links → filter toolbar → grouped product lists → Load more', 'Daunt Books / TOAST'],
  ],
  product: [
    ['story', 'Story and disclosures', 'Identity → buying controls → highlights and authored sections → grouped related cards → detail disclosures → advice and catalog context', 'TOAST / Pushchair Expert'],
    ['tabs', 'Buying panel and tabs', 'Identity → buying panel → tabbed information → highlights and catalog context → grouped related cards → advice', 'StarmoreBoss / Lakeland'],
    ['technical', 'Specification first', 'Identity → scoped facts tables → buying form → description and services → advice → related product lists → catalog context', 'Elgiganten / IKEA'],
  ],
  cart: [
    ['table', 'Editable basket table', 'Lines with quantities and destinations → coupon → current quote → checkout', 'New authoring draft; checkout capture pending'],
    ['cards', 'Line cards and summary', 'Per-line configuration cards → quote → coupon → checkout', 'New authoring draft; checkout capture pending'],
    ['groups', 'Shipment review', 'Derived shipment sections with editable lines → coupon disclosure → shipment review → checkout', 'New authoring draft; checkout capture pending'],
  ],
  checkout: [
    ['steps', 'Three-step checkout', 'Address → delivery and coupon → complete review, with explicit back links', 'Older project wizard; real checkout capture pending'],
    ['single', 'Single-page checkout', 'Address form → delivery controls → coupon → complete review', 'Older project express; real checkout capture pending'],
    ['sections', 'Expandable checkout', 'Address / delivery / coupon disclosures → persistent complete review', 'Older project accordion; real checkout capture pending'],
  ],
  info: [
    ['directory', 'Help directory', 'Topic index → selected article → related topics', 'Lakeland / Daunt Books'],
    ['questions', 'Questions and answers', 'Topic links → question disclosures → contact route', 'Retail delivery help references; authored questions'],
    ['handbook', 'Customer handbook', 'Contents links → consecutive policy sections → contact details', 'IKEA / Robinson’s Shoes'],
  ],
  navbar: [
    ['departments', 'Department navigation', 'Identity and utilities → category links → search', 'Elgiganten / D&M Tools'],
    ['menu', 'Menu disclosure', 'Identity → nested department menu → search → utilities', 'Alpkit native disclosures'],
    ['compact', 'Compact navigation', 'Identity → catalog and help links → cart → search disclosure', 'Daunt Books / TOAST'],
  ],
  sidebar: [
    ['directory', 'Department directory', 'Persistent category navigation and help routes', 'D&M Tools / department stores'],
    ['drawer', 'Browse disclosure', 'Expandable category routes and catalog entry', 'Alpkit navigation; separate authoring unit'],
    ['services', 'Services and shortcuts', 'Branch information → shopping links → expandable customer support', 'IKEA / Lakeland service regions'],
  ],
  footer: [
    ['columns', 'Service columns', 'Customer services → store information → legal links', 'Lakeland / Robinson’s Shoes'],
    ['disclosures', 'Service disclosures', 'Expandable support, company and legal groups', 'zooplus native footer disclosures'],
    ['directory', 'Compact directory', 'Single categorized link list → retailer identity and contact', 'Daunt Books / StarmoreBoss'],
  ],
};

export const hugeUnits = {
  home: [
    ['marketplace','Huge: Marketplace mosaic','Collection mosaic → compact recommendation shelves → themed discovery → advice tiles','Amazon / zooplus'],
    ['superstore','Huge: Department superstore','Campaign introduction → long product rails → collection features → brands and advice','Elgiganten / IKEA'],
  ],
  results: [
    ['marketplace','Huge: Marketplace results','Query → department refinement → filters beside twelve compact cards → pages','Amazon / zooplus'],
    ['superstore','Huge: Superstore results','Query and filter toolbar → twelve detailed catalog entries → pages','Elgiganten / IKEA'],
  ],
  product: [
    ['marketplace','Huge: Marketplace buying panel','Highlights beside buying/availability → full facts → multiple recommendation shelves → description and context','Amazon / zooplus'],
    ['superstore','Huge: Superstore product sections','Buying and availability → information tabs → model comparison → long recommendation rails → advice','Elgiganten / IKEA'],
  ],
  navbar: [
    ['marketplace','Huge: Marketplace masthead','Identity/utilities → search → department ribbon and all-departments disclosure','Amazon / zooplus'],
    ['superstore','Huge: Superstore masthead','Identity/search/utilities → department navigation → selected brand shortcuts','Elgiganten / IKEA'],
  ],
  sidebar: [
    ['marketplace','Huge: Shopping shortcuts','Department shortcuts → featured brands → customer information','Amazon / zooplus'],
    ['superstore','Huge: Catalog hierarchy','Department/type/range tree → advice and store routes','Elgiganten / IKEA'],
  ],
  footer: [
    ['marketplace','Huge: Corporate columns','Shopping help and branches → broad corporate link columns → network directory','Amazon / zooplus'],
    ['superstore','Huge: Corporate directory','Customer information → nested corporate handbook → brand index','IKEA / Elgiganten'],
  ],
};
export const boutiqueUnits = {
  home: [
    ['atelier','Boutique: Collection journal','Collection stories → four sampled pieces → choosing advice','TOAST / StarmoreBoss'],
    ['counter','Boutique: Independent shop','Shop introduction → four compact shelf entries → branch information','Daunt Books / StarmoreBoss'],
  ],
  results: [
    ['atelier','Boutique: Collection cards','Collapsed refinements → six compact product cards → numbered pages','TOAST / StarmoreBoss'],
    ['counter','Boutique: Shop ledger','Filter toolbar → twelve product/price/orderability rows → numbered pages','Daunt Books (authored table adaptation)'],
  ],
  product: [
    ['atelier','Boutique: Product story','Description → buying → full detail and delivery disclosures → three related pieces','TOAST / Alpkit'],
    ['counter','Boutique: Product handbook','Buying and availability → highlights → individual fact-group disclosures → description → two related entries','Daunt Books / StarmoreBoss'],
  ],
  navbar: [
    ['atelier','Boutique: Shop masthead','Identity, catalog, about, help and basket → exposed search','TOAST / Daunt Books'],
    ['counter','Boutique: Counter navigation','Identity, basket and orders → collections disclosure → exposed search','StarmoreBoss / Alpkit'],
  ],
  sidebar: [
    ['atelier','Boutique: Collections drawer','Full department/type/range hierarchy behind one disclosure → catalog entry','Alpkit / TOAST'],
    ['counter','Boutique: Collection refinements','Category links with individual type/range disclosures → catalog and shop routes','Daunt Books / StarmoreBoss'],
  ],
  footer: [
    ['atelier','Boutique: Information links','Two short information link groups','TOAST / StarmoreBoss'],
    ['counter','Boutique: Shop contact and terms','Contact definitions and shop links → policy disclosure','Daunt Books / StarmoreBoss'],
  ],
};
export const units = Object.fromEntries(Object.entries(typicalUnits).map(([role,choices])=>[role,[...choices,...(hugeUnits[role]||[]),...(boutiqueUnits[role]||[])]]));

export const globals = {
  standard: {name: 'Conventional retail', catalog: 'Products', cart: 'Cart', checkout: 'Checkout', help: 'Customer service', add: 'Add to cart', collect: 'Store collection', money: 'suffix', controls: 'select', status: 'In stock', backorder: 'Available to backorder'},
  guided: {name: 'Guided shop', catalog: 'Explore the range', cart: 'Your bag', checkout: 'Arrange delivery', help: 'Help & advice', add: 'Add to bag', collect: 'Collect from our shop', money: 'code', controls: 'radio', status: 'Ready to order', backorder: 'Order from the supplier'},
  concise: {name: 'Compact catalog', catalog: 'Shop', cart: 'Basket', checkout: 'Delivery & totals', help: 'Help', add: 'Add to basket', collect: 'Pickup', money: 'prefix', controls: 'select', status: 'Available', backorder: 'Backorder'},
};

export function rng(seed, scope) {
  let h = 2166136261;
  for (const c of `${seed}:${scope}`) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  return () => {h += 0x6D2B79F5; let t = Math.imul(h ^ h >>> 15, 1 | h); t ^= t + Math.imul(t ^ t >>> 7, 61 | t); return ((t ^ t >>> 14) >>> 0) / 4294967296;};
}
export function shuffled(items, seed, scope) {
  const copy = [...items], random = rng(seed, scope);
  for (let i = copy.length - 1; i > 0; i--) {const j = Math.floor(random() * (i + 1)); [copy[i], copy[j]] = [copy[j], copy[i]];}
  return copy;
}
export function moduleSeed(conf, role) {
  const binding=conf.unitPermutations?.[role];
  return binding?.unit===conf.modules[role] ? binding.seed : conf.seed;
}
export function configuration(seed = 41, scale = 'typical') {
  const conf = {schema: 'website-draft-v1', seed, scale, modules: {}};
  for (const [role, original] of Object.entries(typicalUnits)) {
    const choices = scale==='huge' ? hugeUnits[role]||original : scale==='boutique' ? boutiqueUnits[role]||original : original;
    conf.modules[role] = choices[Math.floor(rng(seed, `module:${role}`)() * choices.length)][0];
  }
  conf.global = Object.keys(globals)[Math.floor(rng(seed, 'global')() * 3)];
  conf.search = true;
  conf.iconCart = rng(seed, 'cart-label')() < .5;
  conf.split = true;
  conf.url = ['all', 'colour', 'none'][Math.floor(rng(seed, 'variant-url')() * 3)];
  conf.reset = false;
  conf.opaque = false;
  conf.policy = ['footer', 'checkout', 'help'][Math.floor(rng(seed, 'policy-entry')() * 3)];
  conf.qualification = 'basket';
  conf.collectionPayment = rng(seed, 'collection-payment')() < .5 ? 'online' : 'collection';
  return conf;
}

export function validateConfiguration(conf) {
  if (conf?.schema !== 'website-draft-v1' || !Number.isSafeInteger(conf.seed)) throw Error('Unsupported authoring configuration');
  for (const [role, choices] of Object.entries(units)) if (!choices.some(c => c[0] === conf.modules?.[role])) throw Error(`Invalid ${role} module`);
  if (!['typical','huge','boutique'].includes(conf.scale||'typical')) throw Error('Invalid authoring scale');
  if (!globals[conf.global] || !['all','colour','none'].includes(conf.url) || !['footer','checkout','help'].includes(conf.policy) || !['basket','shipment'].includes(conf.qualification) || !['online','collection'].includes(conf.collectionPayment)) throw Error('Invalid site conventions');
  for (const key of ['search','iconCart','split','reset','opaque']) if (typeof conf[key] !== 'boolean') throw Error(`Invalid ${key} capability`);
  if(conf.resetPolicy!==undefined&&(!['preserve','services','delivery','checkout'].includes(conf.resetPolicy)||conf.reset!==(conf.resetPolicy!=='preserve')))throw Error('Invalid reset policy binding');
  if(conf.unitPermutations)for(const [role,binding] of Object.entries(conf.unitPermutations))if(!units[role]||binding.unit!==conf.modules[role]||!Number.isSafeInteger(binding.seed))throw Error(`Invalid ${role} permutation binding`);
  if(conf.deliveryOrder!==undefined&&!['arrival','cost'].includes(conf.deliveryOrder))throw Error('Invalid delivery ordering');
  if(conf.deliveryCount!==undefined&&(!Number.isSafeInteger(conf.deliveryCount)||conf.deliveryCount<0))throw Error('Invalid delivery menu count');
  variationSettings(conf.variations);
  return conf;
}
