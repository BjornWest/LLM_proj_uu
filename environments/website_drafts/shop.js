import {configuration, validateConfiguration, globals, shuffled, moduleSeed} from './manifest.js';
import {products, categories, brands, typesFor, resolveProduct, byVariant} from './catalog.js';
import {availableRanges,rangeLabels,rangeSelections,matchesRange} from './market-range.js';
import {quote, itemEstimate, branches, shopContact, services, serviceTypes, policy, initialAddress, validateAddress, worldBinding} from './quote.js';
import {applyReset,resetPolicy,shouldReset} from './checkout_policy.js';
import {homeContent} from './home-content.js';
import {hugeHome,hugeRecommendations,hugeComparison,hugeFooter,hugeNavigation,hugeSidebar,denseCard,peripheralArticle,peripheralPages} from './huge-layouts.js';
import {boutiqueHome,boutiqueNavigation,boutiqueSidebar,boutiqueFooter,boutiqueProduct,boutiqueResults,boutiqueRecommendations} from './boutique-layouts.js';
import {highlightFacts,informationTabs,optionalParagraph} from './product-content.js';
import {variationSettings,filterOrder,productSectionOrder,skipLinks,applyNavigationVariation,applyHomeOrder,variedCard,renderGallery,moveRecommendations} from './variations.js';

const site = worldBinding?.siteId || new URLSearchParams(location.search).get('site') || 'default';
const configKey = `website-drafts.config.${site}`, stateKey = `website-drafts.state.${site}`;
const conf = validateConfiguration(worldBinding?.configuration || JSON.parse(localStorage.getItem(configKey) || 'null') || configuration(41));
const variations=variationSettings(conf.variations);
const g = {...globals[conf.global],...(variations.site.selectors==='inherit'?{}:{controls:variations.site.selectors})};
const cartNoun = g.cart.replace(/^Your /,'').toLowerCase();
const fresh = () => ({version:2,cart:[],selection:{},disclosures:{},address:{...initialAddress},remembered:{...(worldBinding?.rememberedAddress||initialAddress)},instructions:worldBinding?.initialInstructions||'',coupon:'',split:false,deliveryChoices:{},orders:[],revision:0,serial:0,tab:'description',editing:null});
let state = JSON.parse(localStorage.getItem(stateKey) || 'null') || fresh();
state.disclosures ||= {};
state.orders ||= [];
// Upgrade this isolated preview's old per-line destination model. Old split and
// destination preferences must not silently keep separating the revised basket.
if(state.version!==2){
  state.cart=state.cart.map(line=>{const resolved=byVariant(line.key)||resolveProduct(line.key.replace(/-\d+$/,''));return resolved?{id:line.id,key:resolved.variant.key,quantity:line.quantity}:null;}).filter(Boolean);
  state.version=2;state.split=false;state.deliveryChoices={};
}
state.deliveryChoices ||= {};
let feedback = '', previousRoute = '', lastCheckoutStep = null;
let applyingStoredState = false;
let explicitBack=false, historyBack=false;
const historyKey=`website-drafts.navigation.${site}`;
let historyPosition=history.state?.[historyKey]?.position??0;
function trackNavigation() {
  const marker=history.state?.[historyKey];
  historyBack=!!marker&&marker.position<historyPosition;
  if(!marker||marker.position===historyPosition)historyPosition++;
  else historyPosition=marker.position;
  history.replaceState({...history.state,[historyKey]:{position:historyPosition}},'');
}
history.replaceState({...history.state,[historyKey]:{position:historyPosition}},'');
const disclosureOpen = new WeakMap();
// Reviewer-only access to the configuration actually loaded in this window.
window.websiteDraftReview = Object.freeze({snapshot:()=>({configuration:structuredClone(conf),site,url:location.href})});
const e = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = value => g.money === 'prefix' ? `SEK ${value.toLocaleString('en-GB')}` : g.money === 'code' ? `${value.toLocaleString('en-GB')} SEK` : `${value.toLocaleString('en-GB')} kr`;
const link = (path,label,extra='') => `<a href="#/${e(path)}" ${extra}>${label}</a>`;
const cartLink = () => link('cart',conf.iconCart ? `<span aria-hidden="true">🛒</span> <span aria-hidden="true">${state.cart.reduce((s,l)=>s+l.quantity,0)}</span>` : `${e(g.cart)} (${state.cart.reduce((s,l)=>s+l.quantity,0)})`,conf.iconCart ? `aria-label="${e(g.cart)}, ${state.cart.reduce((s,l)=>s+l.quantity,0)} items"` : '');
function save() {if(!applyingStoredState)localStorage.setItem(stateKey,JSON.stringify(state));}
let addressRequest=0;
function revise(message='') {state.revision++; save(); feedback=message; render();}
function route() {
  const [path,query=''] = location.hash.replace(/^#\/?/,'').split('?');
  const [role='home',id=''] = (path || 'home').split('/');
  return {role,id,params:new URLSearchParams(query)};
}
function goto(path) {const target=`#/${path}`; if(location.hash === target) render(); else location.hash=target;}
function rangeLinks(category) {
  return availableRanges(products.filter(p=>p.category===category)).map(value=>link(`results?category=${encodeURIComponent(category)}&market_range=${value}`,e(`${rangeLabels[value]} ${category.toLowerCase()}`))).join(' · ');
}
function catalogPath(values={}) {return `results?${new URLSearchParams(values)}`;}
function categoryList() {return categories.map(c=>`<li>${link(catalogPath({category:c}),e(c))}<ul>${availableRanges(products.filter(p=>p.category===c)).map(value=>`<li>${link(catalogPath({category:c,market_range:value}),e(`${rangeLabels[value]} ${c.toLowerCase()}`))}</li>`).join('')}${typesFor(c).map(type=>`<li>${link(catalogPath({category:c,type}),e(type))}</li>`).join('')}</ul></li>`).join('');}
function categoryLinks() {return categories.map(c=>`${link(`results?category=${encodeURIComponent(c)}`,e(c))}${rangeLinks(c)?` (${rangeLinks(c)})`:''}`).join(' · ');}
function rangeText(p) {return p.marketRange.status==='known'?`${rangeLabels[p.marketRange.value]} range`:'';}
function searchForm() {return conf.search ? `<form data-form="search" role="search"><label>Search ${e(g.catalog.toLowerCase())}<input type="search" name="q" value="${e(route().params.get('q') || '')}"></label><button>Search</button></form>` : '';}
function navbar() {
  if(['atelier','counter'].includes(conf.modules.navbar))return boutiqueNavigation(conf.modules.navbar,{e,link,cartLink,searchForm,categoryList,g});
  if(['marketplace','superstore'].includes(conf.modules.navbar))return hugeNavigation(conf.modules.navbar,{e,link,cartLink,searchForm,categoryLinks,categoryList,g});
  const identity=link('home','<strong>Northline</strong>'), utilities=`${cartLink()} · ${link('info/contact',e(g.help))} · ${link('info/orders','My orders')}`;
  switch(conf.modules.navbar) {
    case 'departments': return `<header><div class="row">${identity}<nav aria-label="Shopping utilities">${utilities}</nav></div><nav aria-label="Departments">${link('results',e(g.catalog))} · ${categoryLinks()}</nav>${searchForm()}</header>`;
    case 'menu': return `<header>${identity}<nav aria-label="Main navigation"><details><summary>Menu</summary><ul><li>${link('results',e(g.catalog))}<ul>${categoryList()}</ul></li><li>${link('info/about','About Northline')}</li></ul></details>${utilities}</nav>${searchForm()}</header>`;
    case 'compact': return `<header><nav aria-label="Main navigation">${identity} · ${link('results',e(g.catalog))} · ${link('info/about','Our shop')} · ${utilities}</nav><nav aria-label="Departments"><details><summary>Departments</summary><ul>${categoryList()}</ul></details></nav>${conf.search?`<details><summary>Search</summary>${searchForm()}</details>`:''}</header>`;
  }
}
function sidebar() {
  if(['atelier','counter'].includes(conf.modules.sidebar))return boutiqueSidebar(conf.modules.sidebar,{e,link,categoryList,g});
  if(['marketplace','superstore'].includes(conf.modules.sidebar))return hugeSidebar(conf.modules.sidebar,{e,link,categoryList,g,conf});
  switch(conf.modules.sidebar) {
    case 'directory': return `<aside><nav aria-label="Browse departments"><h2>Departments</h2><ul>${categoryList()}</ul>${link('results','View all products')}</nav><nav aria-label="Shopping help"><h2>${e(g.help)}</h2>${link('info/sizing','Choosing a size')}<br>${link('info/stores','Our shops')}</nav></aside>`;
    case 'drawer': return `<aside><nav aria-label="Browse"><details><summary>Browse ${e(g.catalog.toLowerCase())}</summary><ul>${categoryList()}</ul>${link('results','Complete catalog')}</details></nav></aside>`;
    case 'services': return `<aside><section aria-label="Shop services"><h2>Visit a shop</h2><ul>${Object.values(branches).map(b=>`<li><strong>${e(b.name)}</strong><p>${e(b.address)}</p></li>`).join('')}</ul>${link('info/stores','Addresses and opening hours')}<nav aria-label="Shopping shortcuts"><h2>Shopping</h2><ul><li>${link('results',e(g.catalog))}</li>${categories.map(c=>`<li>${link(catalogPath({category:c}),e(c))}</li>`).join('')}</ul></nav><details><summary>${e(g.help)}</summary>${link('info/contact','Contact us')}<br>${link('info/care','Product care')}<br>${link('info/returns','Returns')}</details></section></aside>`;
  }
}
function footer() {
  if(['atelier','counter'].includes(conf.modules.footer))return boutiqueFooter(conf.modules.footer,{e,link,conf,shopContact,g});
  const base=standardFooter();
  return ['marketplace','superstore'].includes(conf.modules.footer)?base.replace('</footer>',hugeFooter(conf.modules.footer,{e,link})+'</footer>'):base;
}
function standardFooter() {
  const groups=[['Customer service',[['contact','Contact us','Opening hours and customer-service details'],['returns','Returns','How to return an item'],['stores','Our shops','Addresses, opening hours and local collection'],...(conf.policy==='footer'?[['shipping','Delivery policy','Charges, free-delivery terms and dispatch groups']]:[])]],['Shopping advice',[['care','Product care','Care information for the products you choose'],['sizing','Size guide','EU sizing and measurement information'],['orders','My orders','Retrieve an existing order']]],['About Northline',[['about','About us','The shop and its range'],['privacy','Privacy','Remembered options, basket and delivery address'],['terms','Terms','Prices and shopping terms']]]];
  const entries=links=>`<ul>${links.map(([id,label,note])=>`<li>${link(`info/${id}`,e(label))}<p>${e(note)}</p></li>`).join('')}</ul>`;
  const catalog=`<nav aria-label="Footer shopping directory"><h2>Browse the range</h2><ul>${categories.map(c=>`<li>${link(catalogPath({category:c}),e(c))}</li>`).join('')}</ul>${link('results','All products')}</nav>`;
  const shops=`<section aria-label="Northline shops"><h2>Our shops</h2>${Object.values(branches).map(b=>`<section><h3>${e(b.name)}</h3><address>${e(b.address)}</address><p>${e(b.hours)}</p></section>`).join('')}${link('info/stores','Collection and shop information')}</section>`;
  const contact=`<section><h2>Get in touch</h2><dl><dt>Customer service</dt><dd>${e(shopContact.email)}</dd><dt>Telephone</dt><dd>${e(shopContact.phone)}</dd><dt>Opening hours</dt><dd>${e(shopContact.hours)}</dd></dl>${link('info/contact','Contact details')}</section>`;
  if(conf.modules.footer==='columns') return `<footer><nav aria-label="Footer" class="columns">${groups.map(([title,links])=>`<section><h2>${e(title)}</h2>${entries(links)}</section>`).join('')}</nav><div class="columns">${catalog}${shops}${contact}</div></footer>`;
  if(conf.modules.footer==='disclosures') return `<footer><div class="columns">${shops}${contact}</div><nav aria-label="Footer">${groups.map(([title,links])=>`<details><summary>${e(title)}</summary>${entries(links)}</details>`).join('')}</nav>${catalog}<p>Northline · Everyday goods from our two shops</p></footer>`;
  return `<footer><nav aria-label="Footer directory"><ul>${groups.map(([title,links])=>`<li><strong>${e(title)}</strong>${entries(links)}</li>`).join('')}</ul></nav><div class="columns">${catalog}${contact}${shops}</div></footer>`;
}
function cardFacts(p,v) {
  return highlightFacts(v,variations.product.highlightCount==='base'?2:Number(variations.product.highlightCount));
}
function productCard(p) {
  const custom=variedCard(p,{e,link,money,conf,variations});if(custom!==null)return custom;
  const v=p.variants.reduce((a,b)=>a.price<=b.price?a:b),orderable=p.variants.filter(v=>v.state!=='unavailable');
  const status=orderable.some(v=>v.state==='in_stock')?'In-stock options available':orderable.length?'Supplier backorder options':'Currently unavailable';
  return `<article data-product-card="${e(p.id)}"><h3>${link(`product/${p.id}`,e(p.name))}</h3><p>${link(catalogPath({brand:p.brand}),e(p.brand))} · ${link(catalogPath({category:p.category,type:p.type}),e(p.type))}${rangeText(p)?` · ${e(rangeText(p))}`:''}</p>${optionalParagraph(p.introduction,e)}<dl><dt>${p.variants.length>1?'Price from':'Price'}</dt><dd class="amount">${money(v.price)}</dd><dt>Ordering</dt><dd>${e(status)}</dd>${cardFacts(p,v).map(f=>`<dt>${e(f.label)}</dt><dd>${factValue(f)}${f.qualifier?`<p>${e(f.qualifier)}</p>`:''}</dd>`).join('')}</dl>${p.options.length?`<section aria-label="Options for ${e(p.name)}"><h4>Product options</h4><ul>${p.options.map(o=>`<li>${e(o.label)}: ${o.values.map(e).join(', ')}</li>`).join('')}</ul><p>Details shown for ${Object.entries(v.selection).map(([key,value])=>`${e(p.options.find(o=>o.key===key).label)} ${e(value)}`).join(' · ')}.</p></section>`:''}<p>${link(`product/${p.id}`,p.options.length?'View options':'View product')} · ${link(`info/${p.guide==='Sizing'?'sizing':'care'}`,p.guide==='Sizing'?'Size guide':'Product care')}</p></article>`;
}
const homeGuides = [
  {id:'sizing',title:'Choosing a size',text:'Read the measurement guide, then check the available sizes and size-specific details on the product page.'},
  {id:'care',title:'Caring for your things',text:'Find the product-care handbook and check the material information for the item you choose.'},
  {id:'stores',title:'Collection from a shop',text:'Find our addresses and opening hours. Local availability and warehouse transfers are shown with the selected item.'},
  {id:'returns',title:'Before you return an item',text:'Read the return terms and contact customer service with questions about your purchase.'},
  {id:'orders',title:'An order you already placed',text:'Look up an existing order to inspect its items, delivery information and current status.'},
  {id:'contact',title:'Talk to our team',text:'Find the telephone number, email address and customer-service opening hours.'},
];
function homeDepartmentRoutes(department,limit=Infinity) {
  const {category,types,ranges}=department;
  return `<ul>${ranges.map(value=>`<li>${link(catalogPath({category,market_range:value}),e(`${rangeLabels[value]} ${category.toLowerCase()}`))}</li>`).join('')}${types.slice(0,limit).map(type=>`<li>${link(catalogPath({category,type}),e(type))}</li>`).join('')}</ul>`;
}
function homeDepartments(plan,mode) {
  const intro='<h2>Shop by department</h2>';
  const all=link('results','Browse the complete range');
  if(mode==='tiles') return `<nav aria-label="Shop by department">${intro}<div class="grid">${plan.departments.map(d=>`<section><h3>${link(catalogPath({category:d.category}),e(d.category))}</h3><p>${e(d.intro)}</p>${homeDepartmentRoutes(d)}</section>`).join('')}</div>${all}</nav>`;
  if(mode==='directory') return `<nav aria-label="Shop by department">${intro}<ul>${plan.departments.map(d=>`<li><h3>${link(catalogPath({category:d.category}),e(d.category))}</h3>${homeDepartmentRoutes(d)}</li>`).join('')}</ul>${all}</nav>`;
  return `<nav aria-label="Shop by department">${intro}<ul>${plan.departments.map(d=>`<li>${link(catalogPath({category:d.category}),e(d.category))}${d.ranges.length?`<ul>${d.ranges.map(value=>`<li>${link(catalogPath({category:d.category,market_range:value}),e(`${rangeLabels[value]} ${d.category.toLowerCase()}`))}</li>`).join('')}</ul>`:''}</li>`).join('')}</ul>${all}</nav>`;
}
function homeCollections(plan,mode) {
  if(!plan.collections.length)return '';
  const stories=plan.collections.map(d=>mode==='stories'
    ? `<section aria-label="${e(d.title)}"><h2>${e(d.title)}</h2><p>${e(d.intro)}</p><p>${e(d.note)}</p>${link(catalogPath({category:d.category}),`Explore ${e(d.category.toLowerCase())}`)}<nav aria-label="Explore ${e(d.title.toLowerCase())}"><h3>Explore the collection</h3>${homeDepartmentRoutes(d,2)}</nav></section>`
    : `<article><h3>${link(catalogPath({category:d.category}),e(d.title))}</h3><p>${e(d.intro)}</p>${homeDepartmentRoutes(d,2)}</article>`).join('');
  return mode==='stories'?stories:`<section aria-label="Collection highlights"><h2>Explore the collections</h2><div class="grid">${stories}</div></section>`;
}
function homeBrands(plan,mode) {
  if(!plan.brands.length)return '';
  const rows=plan.brands.map(b=>`<li><h3>${link(catalogPath({brand:b.name}),e(b.name))}</h3><ul>${b.categories.map(category=>`<li>${link(catalogPath({brand:b.name,category}),e(category))}</li>`).join('')}</ul></li>`).join('');
  const body=`<nav aria-label="Featured brands"><ul>${rows}</ul></nav>`;
  return mode==='disclosure'?`<section><h2>Brands in the shop</h2><details><summary>Explore featured brands</summary>${body}</details></section>`:`<section><h2>Brands in the shop</h2>${body}</section>`;
}
function homeAdvice(mode) {
  if(mode==='handbook') return `<section aria-label="Shopping handbook"><h2>Shopping handbook</h2><dl>${homeGuides.map(a=>`<dt>${link(`info/${a.id}`,e(a.title))}</dt><dd>${e(a.text)}</dd>`).join('')}</dl></section>`;
  return `<section aria-label="Shopping advice"><h2>${e(g.help)}</h2>${mode==='articles'?`<div class="grid">${homeGuides.map(a=>`<article><h3>${link(`info/${a.id}`,e(a.title))}</h3><p>${e(a.text)}</p></article>`).join('')}</div>`:`<ul>${homeGuides.map(a=>`<li><h3>${link(`info/${a.id}`,e(a.title))}</h3><p>${e(a.text)}</p></li>`).join('')}</ul>`}</section>`;
}
function homeShops(mode) {
  const records=Object.values(branches).map(b=>`<section><h3>${e(b.name)}</h3><address>${e(b.address)}</address><p>${e(b.hours)}</p></section>`).join('');
  const visit=`${link('info/stores','Addresses, opening hours and collection')} · ${link('info/contact',e(g.help))}`;
  if(mode==='noticeboard') return `<section aria-label="Visit Northline"><h2>Visit our shops</h2>${records}<p>${visit}</p></section><section aria-label="Shop notices"><h2>Shop notices</h2><article><h3>Collect or arrange a transfer</h3><p>Selected items have local shop stock. Warehouse-to-shop transfer options can be inspected at checkout.</p>${link('info/stores','How shop collection works')}</article><article><h3>Help with a purchase</h3><p>Our customer-service team can answer questions during its opening hours.</p><dl><dt>Telephone</dt><dd>${e(shopContact.phone)}</dd><dt>Email</dt><dd>${e(shopContact.email)}</dd><dt>Opening hours</dt><dd>${e(shopContact.hours)}</dd></dl>${link('info/contact','Customer-service details')}</article><article><h3>Already ordered?</h3><p>Inspect an existing order or read the return terms before contacting the shop.</p>${link('info/orders','Find an existing order')} · ${link('info/returns','Return information')}</article></section>`;
  return `<section aria-label="From our shops"><h2>From our shops</h2><p>Browse online or visit our Uppsala and Stockholm shops.</p><div class="columns">${records}</div><p>${visit}</p>${link('info/about','About Northline')}</section>`;
}
function homeBanner(collection) {
  return `<section aria-label="${e(collection.title)}"><h2>${e(collection.title)}</h2><p>${e(collection.intro)}</p>${link(catalogPath({category:collection.category}),`Explore ${e(collection.category.toLowerCase())}`)}</section>`;
}
function home() {
  if(['atelier','counter'].includes(conf.modules.home))return boutiqueHome(conf.modules.home,{e,link,money,conf,branches});
  if(['marketplace','superstore'].includes(conf.modules.home))return hugeHome(conf.modules.home,{e,link,money,conf});
  const plan=homeContent(products,moduleSeed(conf,'home'));
  const cards=plan.showcase.map(productCard);
  const showcase=cards.length?`<section aria-label="A selection from the shop"><h2>A selection from the shop</h2>${conf.modules.home==='noticeboard'?`<ul>${cards.map(card=>`<li>${card}</li>`).join('')}</ul>`:`<div class="grid">${cards.join('')}</div>`}</section>`:'';
  if(conf.modules.home==='departments') return `<h1>Northline</h1><p>Explore the departments, collections and brands in our shop.</p>${homeDepartments(plan,'tiles')}${homeCollections(plan,'teasers')}${showcase}${homeBrands(plan,'directory')}${homeAdvice('articles')}${homeShops('directory')}`;
  if(conf.modules.home==='editorial') return `<h1>For everyday journeys</h1><p>Northline brings together goods for home, work and time outdoors.</p>${plan.collections.slice(0,1).map(homeBanner).join('')}${cards.length?`<section aria-label="A selection from the shop"><h2>A selection from the shop</h2><div class="grid">${cards.slice(0,2).join('')}</div></section>`:''}${plan.collections.slice(1).map(homeBanner).join('')}${cards.length>2?`<section aria-label="More from our shop"><h2>More from our shop</h2><div class="grid">${cards.slice(2).join('')}</div></section>`:''}<section><h2>${e(g.help)}</h2><p>${link('info/sizing','Choosing a size')} · ${link('info/care','Product care')} · ${link('info/stores','Visit our shops')} · ${link('info/contact','Contact our team')}</p></section>`;
  return `<h1>Welcome to Northline</h1><p>Visit our shops or browse the range online.</p>${homeShops('noticeboard')}${showcase}${homeAdvice('handbook')}<section><h2>About the shop</h2><p>Find out about Northline and its range of everyday goods.</p>${link('info/about','Our shop and its range')}</section>`;
}
function filterControls(params) {
  const controls={category:`<label>Department<select name="category"><option value="">All departments</option>${categories.map(c=>`<option ${params.get('category')===c?'selected':''}>${e(c)}</option>`).join('')}</select></label>`, brand:`<label>Brand<select name="brand"><option value="">All brands</option>${brands.map(b=>`<option ${params.get('brand')===b?'selected':''}>${e(b)}</option>`).join('')}</select></label>`, type:`<label>Product type<select name="type"><option value="">All product types</option>${typesFor(params.get('category')).map(t=>`<option ${params.get('type')===t?'selected':''}>${e(t)}</option>`).join('')}</select></label>`,price:`<label>Maximum price (SEK)<input name="max" type="number" min="0" value="${e(params.get('max') || '')}"></label>`,sort:`<label>Sort by<select name="sort">${[['name','Name'],['price','Price: low to high'],['brand','Brand']].map(([id,label])=>`<option value="${id}" ${params.get('sort')===id?'selected':''}>${label}</option>`).join('')}</select></label>`};
  const local=products.filter(p=>!params.get('category')||p.category===params.get('category'));
  const ranges=availableRanges(local);
  if(ranges.length || params.get('market_range')) controls.market_range=`<label>Market range<select name="market_range"><option value="">All ranges</option>${rangeSelections.filter(choice=>choice.values.some(value=>ranges.includes(value)) || choice.id===params.get('market_range')).map(choice=>`<option value="${choice.id}" ${params.get('market_range')===choice.id?'selected':''}>${e(choice.label)}</option>`).join('')}</select></label>`;
  if(variations.results.sortPlacement==='toolbar')delete controls.sort;
  return filterOrder(Object.keys(controls),variations.results.filterOrder,keys=>shuffled(keys,moduleSeed(conf,'results'),`results:${conf.modules.results}:filter-order`)).map(k=>controls[k]).join('');
}
function results(params) {
  const query=(params.get('q') || '').trim(),category=params.get('category') || '',brand=params.get('brand') || '',max=params.get('max');
  const type=params.get('type')||'';
  const matched=products.filter(p=>matchesRange(p.marketRange,params.get('market_range'))&&(!category||p.category===category)&&(!type||p.type===type)&&(!brand||p.brand===brand)&&(!query||`${p.name} ${p.brand} ${p.introduction} ${p.category} ${p.type}`.toLowerCase().includes(query.toLowerCase()))&&(!max||Math.min(...p.variants.map(v=>v.price))<=Number(max)));
  const sort=params.get('sort') || 'name'; matched.sort((a,b)=>sort==='price'?Math.min(...a.variants.map(v=>v.price))-Math.min(...b.variants.map(v=>v.price)):sort==='brand'?a.brand.localeCompare(b.brand)||a.name.localeCompare(b.name):a.name.localeCompare(b.name));
  const huge=['marketplace','superstore'].includes(conf.modules.results),pageSize=huge||conf.modules.results==='counter'?12:6;
  const pageCount=Math.max(1,Math.ceil(matched.length/pageSize)),page=Math.min(pageCount,Math.max(1,Number(params.get('page'))||1));
  const batch=conf.modules.results==='grouped'?matched.slice(0,page*pageSize):matched.slice((page-1)*pageSize,page*pageSize);
  const title=query?`Search: ${query}`:category||g.catalog;
  const toolbar=variations.results.sortPlacement==='toolbar'?`<form data-form="filters" data-sort-toolbar><label>Sort by<select name="sort">${[['name','Name'],['price','Price: low to high'],['brand','Brand']].map(([id,label])=>`<option value="${id}" ${sort===id?'selected':''}>${label}</option>`).join('')}</select></label>${variations.results.filterApply==='submit'?'<button>Apply sorting</button>':''}</form>`:'';
  const heading=`<h1>${e(title)}</h1><p role="status">${matched.length} products${type?` · Product type: ${e(type)}`:''}${params.get('market_range')?` · Market range: ${e(rangeSelections.find(choice=>choice.id===params.get('market_range'))?.label || 'Unknown selection')}`:''}${brand?` · Brand: ${e(brand)}`:''}${max?` · Up to ${e(max)} SEK`:''}</p>${toolbar}`;
  const filterForm=`<form data-form="filters">${query?`<input type="hidden" name="q" value="${e(query)}">`:''}<fieldset><legend>Refine the catalog</legend>${filterControls(params)}${variations.results.filterApply==='submit'?'<button>Apply filters</button>':'<p>Results update when you change a filter.</p>'} ${link('results','Clear filters')}</fieldset></form>`;
  const pageLink=n=>{const q=new URLSearchParams(params);q.set('page',n);return `results?${q}`;};
  const paging=`<nav aria-label="Results pages">${Array.from({length:pageCount},(_,i)=>link(pageLink(i+1),String(i+1),i+1===page?'aria-current="page"':'')).join(' · ')}</nav>`;
  const empty='<p>No products match these filters. Change the filters or browse all products.</p>';
  if(variations.results.presentation!=='base') {
    const cards=batch.map(productCard);
    const body=!batch.length?empty:variations.results.presentation==='table'?`<table><caption>Matching products and their lowest listed prices</caption><thead><tr><th>Product</th><th>Price from</th><th>Available options</th></tr></thead><tbody>${batch.map((p,i)=>`<tr><td>${cards[i]}</td><td>${money(Math.min(...p.variants.map(v=>v.price)))}</td><td>${p.options.length?p.options.map(o=>e(o.label)).join(', '):'One configuration'}</td></tr>`).join('')}</tbody></table>`:variations.results.presentation==='list'?`<ul>${cards.map(c=>`<li>${c}</li>`).join('')}</ul>`:`<div class="grid">${cards.join('')}</div>`;
    return `${heading}${conf.modules.results==='atelier'||conf.modules.results==='ledger'?`<details><summary>Refine the catalog</summary>${filterForm}</details>`:filterForm}<section aria-label="Product results">${body}${paging}</section>`;
  }
  if(['atelier','counter'].includes(conf.modules.results))return boutiqueResults(conf.modules.results,{e,link,money,conf,heading,filterForm,batch,paging,empty});
  if(conf.modules.results==='marketplace')return `${heading}<div class="columns"><section aria-label="Refine your search"><nav aria-label="Results departments"><h2>Departments</h2><ul>${categoryList()}</ul></nav>${filterForm}</section><section aria-label="Product results"><div class="grid">${batch.map(p=>denseCard(p,{e,link,money,conf})).join('')}</div>${batch.length?'':empty}${paging}</section></div>`;
  if(conf.modules.results==='superstore')return `${heading}<section aria-label="Catalog toolbar">${filterForm}</section><section aria-label="Product results"><ul>${batch.map(p=>`<li>${productCard(p)}</li>`).join('')}</ul>${batch.length?'':empty}${paging}</section>`;
  if(conf.modules.results==='faceted') return `${heading}<div class="columns"><section aria-label="Catalog filters">${filterForm}</section><section aria-label="Product results"><div class="grid">${batch.map(productCard).join('')}</div>${batch.length?'':empty}${paging}</section></div>`;
  if(conf.modules.results==='ledger') return `${heading}<details><summary>Filter and sort</summary>${filterForm}</details>${batch.length?`<div class="scroll"><table><caption>Catalog entries — prices start at the lowest listed configuration</caption><thead><tr><th>Product</th><th>Department</th><th>Brand</th><th>From price</th><th>Options</th></tr></thead><tbody>${batch.map(p=>`<tr><th scope="row">${link(`product/${p.id}`,e(p.name))}</th><td>${e(p.category)}${rangeText(p)?` · ${e(rangeText(p))}`:''}</td><td>${p.brand}</td><td>${money(Math.min(...p.variants.map(v=>v.price)))}</td><td>${p.options.map(o=>e(o.label)).join(', ')}</td></tr>`).join('')}</tbody></table></div>`:empty}${paging}`;
  return `${heading}<nav aria-label="Departments">${categoryLinks()}</nav>${filterForm}${categories.filter(c=>batch.some(p=>p.category===c)).map(c=>`<section><h2>${e(c)}</h2><ul>${batch.filter(p=>p.category===c).map(p=>`<li>${link(`product/${p.id}`,e(p.name))} · ${money(Math.min(...p.variants.map(v=>v.price)))} and up${optionalParagraph([p.introduction,rangeText(p)].filter(text=>typeof text==='string'&&text.trim()).join(' · '),e)}</li>`).join('')}</ul></section>`).join('')}${batch.length?'':empty}${page<pageCount?link(pageLink(page+1),'Load more products'):matched.length?'<p>All matching products are shown.</p>':''}`;
}
function factValue(f) {return Array.isArray(f.value)?`<ul>${f.value.map(v=>`<li>${e(v)}</li>`).join('')}</ul>`:`${e(f.value)}${f.unit?` ${e(f.unit)}`:''}`;}
function factGroups(product,variant,mode='definitions') {
  const disclosures=mode==='disclosures';
  if(variations.product.facts!=='base')mode=variations.product.facts;
  const details=[...(product.marketRange.status==='known'?[{heading:'Product range',facts:[{label:'Market range',value:rangeLabels[product.marketRange.value]}]}]:[]),...variant.details];
  const groups=shuffled(details,moduleSeed(conf,'product'),`product:${conf.modules.product}:detail-order`).map(group=>({...group,facts:group.facts.filter(f=>f.status!=='not_applicable')})).filter(group=>group.facts.length);
  return groups.map(group=>{
    const body=mode==='table'?`<div class="scroll"><table><tbody>${group.facts.map(f=>`<tr><th scope="row">${e(f.label)}</th><td>${factValue(f)}${f.qualifier?`<p>${e(f.qualifier)}</p>`:''}</td></tr>`).join('')}</tbody></table></div>`:`<dl>${group.facts.map(f=>`<dt>${e(f.label)}</dt><dd>${factValue(f)}${f.qualifier?`<br><small>${e(f.qualifier)}</small>`:''}</dd>`).join('')}</dl>`;
    return disclosures?`<details data-product-part="details"><summary>${e(group.heading)}</summary>${body}</details>`:`<section data-product-part="details"><h3>${e(group.heading)}</h3>${body}</section>`;
  }).join('');
}
function selectors(p,v) {
  return p.options.map((o,index)=>{
    const values=o.values.filter(value=>p.variants.some(candidate=>candidate.selection[o.key]===value&&p.options.slice(0,index).every(previous=>candidate.selection[previous.key]===v.selection[previous.key])));
    return g.controls==='select'?`<label>${e(o.label)}<select data-selection="${e(o.key)}">${values.map(value=>`<option ${v.selection[o.key]===value?'selected':''}>${e(value)}</option>`).join('')}</select></label>`:g.controls==='buttons'?`<div role="group" aria-label="${e(o.label)}">${values.map(value=>`<button type="button" data-selection-button="${e(o.key)}" data-value="${e(value)}" aria-pressed="${v.selection[o.key]===value}">${e(value)}</button>`).join('')}</div>`:`<fieldset><legend>${e(o.label)}</legend>${values.map(value=>`<label><input type="radio" name="${e(o.key)}" value="${e(value)}" data-selection="${e(o.key)}" ${v.selection[o.key]===value?'checked':''}> ${e(value)}</label>`).join('')}</fieldset>`;
  }).join('');
}
function stockText(v) {if(worldBinding)return worldBinding.stockText(v);return v.state==='unavailable'?'Unavailable — cannot be ordered':v.state==='backorder'?g.backorder:g.status;}
function buying(p,v) {
  const editing=state.editing&&state.cart.find(l=>l.id===state.editing&&byVariant(l.key).product.id===p.id);
  return `<section data-product-part="buying" aria-label="Choose and order"><h2>${p.options.length?'Choose your options':'Order this item'}</h2>${selectors(p,v)}${p.options.length?`<p>Selected: ${Object.entries(v.selection).map(([k,value])=>`${e(p.options.find(o=>o.key===k).label)} ${e(value)}`).join(' · ')}</p>`:''}<p class="amount">${money(v.price)}</p><p>${e(stockText(v))}</p><form data-form="add" data-key="${e(v.key)}"><label>Quantity<input name="quantity" type="number" min="1" max="${worldBinding?1:20}" value="${editing?editing.quantity:1}"></label><button ${v.state==='unavailable'?'disabled':''}>${editing?'Update item':e(g.add)}</button></form>${worldBinding?`<p>${e(worldBinding.supplierNotice(v))}</p>`:v.state==='backorder'?'<p>This item is ordered from the supplier. It ships separately from warehouse stock; backorders from the same brand can travel together. An arrival date is not yet confirmed.</p>':''}${link(`info/${p.guide==='Sizing'?'sizing':'care'}`,e(p.guide==='Sizing'?'Size guide':'Product care'))}${conf.global==='guided'?'<p>Your items will be listed in your bag. You can inspect delivery and totals before paying.</p>':''}</section>`;
}
function productServices(p,v) {
  if(worldBinding)return worldBinding.productServices({p,v,e,link,state,conf,g});
  const estimate=itemEstimate(v,state.remembered);
  return `<section aria-label="Availability and delivery"><h2>Availability and delivery</h2>${estimate?`<p>Estimated home delivery to ${e(state.remembered.postcode)}: <strong>${e(estimate)}</strong></p><p>Estimate for this selected item only.</p>`:''}${v.state==='unavailable'?'<p>This configuration is unavailable in our ordering network.</p>':`<p>${v.state==='backorder'?'Supplier order — no warehouse stock':`Dispatch stock: ${v.stock} at ${e(v.source)}`}</p><p>Uppsala shop: ${v.branchStock?v.branchStock+' available for collection':'No local stock'} · Stockholm shop: no local stock</p>${v.state==='in_stock'?'<p>Warehouse-to-shop transfer is available at checkout when local stock cannot cover the quantity.</p>':''}`} ${link('info/stores','Shop details')}${conf.policy==='footer'?'':conf.policy==='checkout'?`<p>Delivery charges and the full delivery policy are shown in ${link('checkout',e(g.checkout.toLowerCase()))}.</p>`:`<p>${link('info/contact',e(g.help))} can help with delivery questions.</p>`}</section>`;
}
function descriptionBlocks(p,v) {return p.descriptions.filter(d=>(!d.skuId||d.skuId===v.skuId)&&typeof d.text==='string'&&d.text.trim()).map(d=>`<section data-product-part="description">${d.heading?`<h3>${e(d.heading)}</h3>`:''}<p>${e(d.text)}</p></section>`).join('');}
function productInformation(description,details,delivery) {
  const {labels,active}=informationTabs(description,details,state.tab);
  state.tab=active;
  return `<section><div role="tablist" aria-label="Product information" class="tab-buttons">${Object.entries(labels).map(([id,label])=>`<button role="tab" id="tab-${id}" aria-controls="panel-${id}" aria-selected="${id===active}" tabindex="${id===active?0:-1}" data-tab="${id}">${e(label)}</button>`).join('')}</div><section role="tabpanel" id="panel-${active}" aria-labelledby="tab-${active}" tabindex="0">${active==='description'?description:active==='details'?details:delivery}</section></section>`;
}
function productOverview(p,v) {
  const facts=cardFacts(p,v);
  return `<section aria-label="Product highlights"><h2>At a glance</h2><dl><dt>Brand</dt><dd>${link(catalogPath({brand:p.brand}),e(p.brand))}</dd><dt>Product type</dt><dd>${link(catalogPath({category:p.category,type:p.type}),e(p.type))}</dd>${facts.map(f=>`<dt>${e(f.label)}</dt><dd>${factValue(f)}${f.qualifier?`<p>${e(f.qualifier)}</p>`:''}</dd>`).join('')}</dl></section>`;
}
function relatedProducts(p) {
  const used=new Set([p.id]),groups=[];
  function add(title,pool,limit){const chosen=shuffled(pool.filter(q=>!used.has(q.id)),moduleSeed(conf,'product'),`related:${p.id}:${title}`).slice(0,limit);if(!chosen.length)return;for(const q of chosen)used.add(q.id);groups.push({title,chosen});}
  add(`More from ${p.category.toLowerCase()}`,products.filter(q=>q.category===p.category),6);
  add(`More from ${p.brand}`,products.filter(q=>q.brand===p.brand),Math.min(4,12-(used.size-1)));
  add('Explore other departments',products.filter(q=>q.category!==p.category),12-(used.size-1));
  // A specialist assortment may have no other departments; remaining genuinely
  // carried models can still fill the local rail. Never clone or invent records.
  if(used.size<13)add('Explore the rest of the range',products,12-(used.size-1));
  return groups.map(({title,chosen})=>`<section data-recommendations aria-label="${e(title)}"><h2>${e(title)}</h2>${variations.recommendations.presentation==='list'||variations.recommendations.presentation==='base'&&conf.modules.product==='technical'?`<ul class="product-list">${chosen.map(q=>`<li>${productCard(q)}</li>`).join('')}</ul>`:`<div class="grid">${chosen.map(productCard).join('')}</div>`}</section>`).join('');
}
function productContext(p) {
  const localTypes=typesFor(p.category),localBrands=[...new Set(products.filter(q=>q.category===p.category).map(q=>q.brand))];
  return `<section aria-label="Explore ${e(p.category.toLowerCase())}"><h2>Explore ${e(p.category.toLowerCase())}</h2><nav aria-label="Related product types"><h3>Shop by product type</h3><ul>${localTypes.map(type=>`<li>${link(catalogPath({category:p.category,type}),e(type))}</li>`).join('')}</ul></nav>${localBrands.length>1?`<nav aria-label="Brands in ${e(p.category)}"><h3>Brands in this department</h3><ul>${localBrands.map(brand=>`<li>${link(catalogPath({category:p.category,brand}),e(brand))}</li>`).join('')}</ul></nav>`:''}${rangeLinks(p.category)?`<nav aria-label="Product ranges"><h3>Shop by range</h3><p>${rangeLinks(p.category)}</p></nav>`:''}</section>`;
}
function choosingHelp(p) {
  return `<section aria-label="Shopping advice"><h2>Help with your choice</h2><ul><li>${link(`info/${p.guide==='Sizing'?'sizing':'care'}`,p.guide==='Sizing'?'Sizing and measurements':'Care information')}<p>${p.guide==='Sizing'?'Check the size labels and measurement basis for the product you choose.':'Check the applicable care information for this product.'}</p></li><li>${link('info/stores','Visit a Northline shop')}<p>Find addresses and opening hours for Uppsala and Stockholm.</p></li><li>${link('info/returns','Returns information')}<p>Read the terms for returning an item.</p></li><li>${link('info/contact','Ask customer service')}<p>Contact details and customer-service hours.</p></li></ul></section>`;
}
function variedProduct(p,v,heading) {
  const settings=variations.product,unit=conf.modules.product;
  const tag=settings.purchaseRegion==='complementary'?'aside':settings.purchaseRegion==='fieldset'?'fieldset':'section';
  const buy=buying(p,v).replace('<section data-product-part="buying" aria-label="Choose and order">',`<${tag} data-product-part="buying" aria-label="Choose and order">${tag==='fieldset'?'<legend>Choose and order</legend>':''}`).replace(/<\/section>$/,`</${tag}>`);
  const description=descriptionBlocks(p,v),details=factGroups(p,v,unit==='technical'||unit==='superstore'?'table':'definitions'),delivery=productServices(p,v);
  const blocks={buying:buy,overview:productOverview(p,v),description,details,delivery};
  const presentation=settings.detailsPresentation==='base'?(['tabs','superstore'].includes(unit)?'tabs':['atelier','counter'].includes(unit)?'disclosure':'inline'):settings.detailsPresentation;
  let order=productSectionOrder(unit,settings.sectionOrder,presentation);
  const content=(key,body)=>body?`<section data-product-part="${key}" aria-label="${{description:'Product description',details:'Product specifications',delivery:'Availability and delivery'}[key]||key}">${body}</section>`:'';
  if(presentation==='tabs') {
    blocks.information=productInformation(description,details,delivery);
    const first=order.findIndex(k=>['description','details','delivery'].includes(k));order=order.filter(k=>!['description','details','delivery'].includes(k));order.splice(first,0,'information');
  } else for(const key of ['description','details','delivery']) {
    const body=blocks[key];blocks[key]=!body?'':presentation==='disclosure'?`<details data-product-part="${key}" data-disclosure-id="product:${p.id}:${key}"><summary>${{description:'Product description',details:'Product details',delivery:'Availability and delivery'}[key]}</summary>${body}</details>`:content(key,body);
  }
  const h={e,link,money,conf},related=['atelier','counter'].includes(unit)?boutiqueRecommendations(p,unit,h):['marketplace','superstore'].includes(unit)?hugeRecommendations(p,unit,h):relatedProducts(p);
  return `${heading}${renderGallery(p.images,settings.gallery,e)}<div data-product-core aria-label="${unit==='atelier'?'Product story':unit==='counter'?'Product handbook':unit==='technical'?'Technical product information':unit==='marketplace'?'Product and buying panel':unit==='superstore'?'Product sections':'Product information'}">${order.map(key=>blocks[key]).join('')}</div>${unit==='superstore'?hugeComparison(p,h):''}${related}${productContext(p)}${choosingHelp(p)}`;
}
function productPage(id,params) {
  const p=products.find(p=>p.id===id); if(!p) return '<h1>Product not found</h1>'+link('results','Browse products');
  const selection={...state.selection[id]};
  for (const o of p.options) if((conf.url==='all'||conf.url==='colour'&&o.key==='colour')&&params.has(o.key)&&o.values.includes(params.get(o.key))) selection[o.key]=params.get(o.key);
  const {variant:v}=resolveProduct(id,selection); state.selection[id]={...v.selection}; save();
  const heading=`<nav aria-label="Breadcrumb">${link('home','Home')} / ${link(catalogPath({category:p.category}),e(p.category))} / ${link(catalogPath({category:p.category,type:p.type}),e(p.type))}</nav><h1>${e(p.name)}</h1><p>${link(catalogPath({brand:p.brand}),e(p.brand))}${rangeText(p)?` · ${e(rangeText(p))}`:''}</p>`;
  if(Object.entries(variations.product).some(([key,value])=>!['facts','gallery','highlightCount'].includes(key)&&value!=='base')||p.images?.length)return variedProduct(p,v,heading);
  const description=descriptionBlocks(p,v),details=factGroups(p,v);
  if(['atelier','counter'].includes(conf.modules.product))return boutiqueProduct(conf.modules.product,p,{e,link,money,conf,heading,description,buying:buying(p,v),services:productServices(p,v),facts:mode=>factGroups(p,v,mode),overview:productOverview(p,v)});
  const related=relatedProducts(p),context=productContext(p),help=choosingHelp(p);
  if(conf.modules.product==='marketplace')return `${heading}<div class="columns"><section aria-label="Product overview">${optionalParagraph(p.introduction,e)}${productOverview(p,v)}</section><section aria-label="Buying and delivery">${buying(p,v)}${productServices(p,v)}</section></div>${details?`<section aria-label="Product details"><h2>Product details</h2>${details}</section>`:''}${hugeRecommendations(p,'marketplace',{e,link,money,conf})}${description?`<section><h2>From the product description</h2>${description}</section>`:''}${context}${help}`;
  if(conf.modules.product==='superstore') {
    return `${heading}<div class="columns"><section aria-label="Product highlights">${optionalParagraph(p.introduction,e)}${productOverview(p,v)}</section><section aria-label="Buying and delivery">${buying(p,v)}${productServices(p,v)}</section></div>${productInformation(description,factGroups(p,v,'table'),productServices(p,v))}${hugeComparison(p,{e,link,money,conf})}${hugeRecommendations(p,'superstore',{e,link,money,conf})}${help}${context}`;
  }
  if(conf.modules.product==='story') return `${heading}${optionalParagraph(p.introduction,e)}${buying(p,v)}${productOverview(p,v)}${description?`<section><h2>The product in detail</h2>${description}</section>`:''}${related}<section><h2>More about this product</h2>${details?`<details><summary>Product details</summary>${details}</details>`:''}<details><summary>Availability and delivery</summary>${productServices(p,v)}</details></section>${help}${context}`;
  if(conf.modules.product==='tabs') {
    return `${heading}${buying(p,v)}${productInformation(description,details,productServices(p,v))}${productOverview(p,v)}${context}${related}${help}`;
  }
  const tableDetails=factGroups(p,v,'table');
  return `${heading}${buying(p,v)}${tableDetails?`<section aria-label="Product specification"><h2>Specification of the selected configuration</h2>${tableDetails}</section>`:''}${description?`<section><h2>Description</h2>${description}</section>`:''}${productServices(p,v)}${help}${related}${context}`;
}
function variantPath(product,variant) {
  const params=new URLSearchParams();
  for(const [key,value] of Object.entries(variant.selection)) if(conf.url==='all'||conf.url==='colour'&&key==='colour') params.set(key,value);
  return `product/${product.id}${params.size?'?'+params:''}`;
}
function lineContent(line) {
  const {product:p,variant:v}=byVariant(line.key);
  return `<h3>${link(variantPath(p,v),e(p.name),`data-edit="${line.id}"`)}</h3>${p.options.length?`<p>${Object.entries(v.selection).map(([k,value])=>`${e(p.options.find(o=>o.key===k).label)}: ${e(value)}`).join(' · ')}</p>`:''}<p>${e(stockText(v))} · ${money(v.price)} each</p><form data-form="quantity" data-line="${line.id}"><label>Quantity for ${e(p.name)}<input name="quantity" type="number" min="1" max="${worldBinding?1:20}" value="${line.quantity}"></label><button>Update quantity</button></form><p>Line subtotal: ${money(v.price*line.quantity)}</p><button data-remove="${line.id}">Remove ${e(p.name)}</button>`;
}
function currentQuote() {
  const result=quote(state.cart,state,conf,state.revision);
  for(const shipment of result.shipments)state.deliveryChoices[shipment.key]=shipment.selected.id;
  if(!result.canSplit)state.split=false;
  if(result.selectionChanges.length)feedback=worldBinding?[feedback,'The previous delivery choice is no longer available. Please review the current service and totals.'].filter(Boolean).join(' '):'The previous delivery choice is no longer available. Home delivery is selected; please review the service choices.';
  return result;
}
function couponForm() {if(worldBinding)return worldBinding.couponForm({state,conf,e,money,link});return `<form data-form="coupon"><label>Discount code<input name="coupon" value="${e(state.coupon)}" autocomplete="off"></label><button>Apply code</button></form>${conf.opaque?'':`<p>WELCOME10 gives 10% off products when the basket subtotal is at least ${money(policy.couponMinimum)}. One code per checkout.</p>`}`;}
function splitControls(result) {return result.canSplit?`<fieldset><legend>Dispatch preference</legend><label><input type="radio" name="split" data-split="false" ${!state.split?'checked':''}> Deliver together — one warehouse shipment</label><label><input type="radio" name="split" data-split="true" ${state.split?'checked':''}> Send items as they become ready</label><p>Different source arrival groups can travel separately. Each shipment has its own delivery charge. Items from the same stock source stay together.</p></fieldset>`:'';}
function policyContent() {if(worldBinding)return worldBinding.policyContent({e,money,link});return `<h3>Delivery charges</h3><ul>${services.map(s=>`<li>${e(s.company)} ${e(s.name)}: ${money(s.regular)}${s.bulky?`; bulky ${money(s.bulky)}`:'; regular parcels only'}.</li>`).join('')}</ul><p>For compatible items traveling together, the highest applicable line tariff is charged once for the selected service.</p><p>Warehouse-to-shop transfer costs ${money(policy.transfer)}, or ${money(policy.bulkyTransfer)} for a bulky item; locally stocked collection is free. Bulky products support home delivery and retailer-shop collection, but not carrier pickup boxes or staffed parcel points.</p><p>Delivery is free when the ${conf.qualification==='basket'?'checkout':'shipment'} product subtotal after coupon discounts reaches ${money(policy.freeMinimum)}. Qualifying free delivery also waives all shop-transfer charges, including bulky transfers.</p><p>Warehouse items default to one combined shipment, arriving at the latest item’s estimated date. Optional earlier arrival groups are offered only when they differ. Supplier backorders travel separately, grouped by brand.</p><p>Shop orders are ${conf.collectionPayment==='collection'?'paid at collection':'paid online when ordering'}. All charges can be inspected before entering payment details.</p>`;}
function shipmentName(s) {return s.backorder?`${s.brand} supplier order`:worldBinding?'Selected item':s.key==='stock'?'All warehouse items':'Warehouse arrival group';}
function shipmentList(s) {return `<ul>${s.lines.map(l=>`<li>${e(l.product.name)}${Object.values(l.variant.selection).length?' · '+Object.values(l.variant.selection).map(e).join(' / '):''} · Quantity ${l.quantity}</li>`).join('')}</ul>`;}
function quoteView(result=currentQuote()) {
  if(result.errors.length)return `<section aria-label="Current quote"><h2>Delivery and total</h2><p role="alert">A complete quote is not available: ${result.errors.map(e).join('; ')}.</p></section>`;
  if(!state.cart.length)return `<p>Your ${e(cartNoun)} is empty.</p>`;
  return `<section aria-label="Current quote"><h2>Delivery and total</h2><p>Recipient: ${e(state.address.name)}, ${e(state.address.street)}${state.address.unit?`, Apartment ${e(state.address.unit)}`:''}, ${e(state.address.postcode)} ${e(state.address.city)}.</p>${state.instructions?`<p>Delivery instructions: ${e(state.instructions)}</p>`:''}<ol>${result.shipments.map(s=>`<li><section><h3>${e(shipmentName(s))}</h3>${shipmentList(s)}<p>${e(s.selected.company)} — ${e(serviceTypes[s.selected.type])} — ${e(s.selected.name)}</p><p>${e(s.selected.location.name)} · ${e(s.selected.location.address)}</p><p>${s.arrival===null?'Arrival date not yet confirmed':s.local?'Ready today — local shop stock':`Estimated ${s.selected.type==='home'?'delivery':'ready for collection'}: ${e(s.arrival)}`}</p><p>Delivery charge: ${money(s.fee)}${s.qualified?' · Free-delivery minimum reached':''}</p>${s.selected.type==='retailer_branch'?`<p>${s.selected.payment==='collection'?'Pay at collection':'Pay online when ordering'}</p>`:''}</section></li>`).join('')}</ol><dl><dt>Products</dt><dd>${money(result.subtotal)}</dd><dt>Coupon discount</dt><dd>${money(result.discount)}</dd><dt>Delivery charges</dt><dd>${money(result.shipping)}</dd><dt>${worldBinding?'Total':'Total including VAT'}</dt><dd><strong>${money(result.total)}</strong></dd></dl>${result.coupon.status==='none'?'':result.coupon.status==='applied'?`<p>${conf.opaque?'Discount code processed.':`Code ${e(result.coupon.code)} applied.`}</p>`:`<p>${conf.opaque?'Discount code processed.':`Code ${e(result.coupon.code)} not applied. ${e(result.coupon.reason)}`}</p>`}${conf.opaque?`<details><summary>Discount-code terms</summary>${worldBinding?worldBinding.couponDetails({e,money}):`<p>${e(policy.coupon)}: ${policy.couponPercent}% off products, minimum ${money(policy.couponMinimum)} before discount. Other codes are not accepted.</p><p>Delivery qualification uses the subtotal after the discount.</p>`}</details>`:''}<details><summary>How delivery is calculated</summary>${policyContent()}</details></section>`;
}
function cart() {
  if(!state.cart.length)return `<h1>${e(g.cart)}</h1><p>Your ${e(cartNoun)} is empty.</p>${link('results','Browse products')}`;
  const exit=`<p>${link('checkout',e(g.checkout))} · ${link('results','Continue shopping')}</p>`;
  if(conf.modules.cart==='table')return `<h1>${e(g.cart)}</h1><div class="scroll"><table><caption>Your selected items</caption><thead><tr><th>Item and controls</th><th>Line total</th></tr></thead><tbody>${state.cart.map(l=>`<tr><td>${lineContent(l)}</td><td>${money(byVariant(l.key).variant.price*l.quantity)}</td></tr>`).join('')}</tbody></table></div>${couponForm()}${quoteView()}${exit}`;
  if(conf.modules.cart==='cards')return `<h1>${e(g.cart)}</h1><div class="grid">${state.cart.map(l=>`<article>${lineContent(l)}</article>`).join('')}</div>${quoteView()}<section><h2>Discounts</h2>${couponForm()}</section>${exit}`;
  const result=currentQuote();
  return `<h1>Review your ${e(cartNoun)}</h1>${result.shipments.length?result.shipments.map(s=>`<section><h2>${e(shipmentName(s))}</h2><ul>${s.lines.map(l=>`<li>${lineContent(l)}</li>`).join('')}</ul></section>`).join(''):`<ul>${state.cart.map(l=>`<li>${lineContent(l)}</li>`).join('')}</ul>`}<details><summary>Add a discount code</summary>${couponForm()}</details>${quoteView(result)}${exit}`;
}
function scheduleNativeQuote() {
  const current=route();
  if(current.role==='product'&&worldBinding?.ensureProduct){
    const selected=resolveProduct(current.id,state.selection[current.id]||Object.fromEntries(current.params)),
      address={...state.remembered};
    if(selected){
      const key=JSON.stringify([current.id,selected.variant.key,address]);
      worldBinding.ensureProduct(selected.product,selected.variant,address).then(changed=>{
        const next=route(),resolved=next.role==='product'&&resolveProduct(next.id,state.selection[next.id]||Object.fromEntries(next.params));
        if(changed&&resolved&&key===JSON.stringify([next.id,resolved.variant.key,state.remembered]))render();
      });
    }
  }
  if(!worldBinding?.ensureQuote)return;
  const key=worldBinding.inquiryKey(state);
  worldBinding.ensureQuote(state).then(changed=>{
    if(!changed||key!==worldBinding.inquiryKey(state))return;
    if(document.activeElement?.closest('[data-form="address"]'))invalidateAddressViews();
    else render();
  });
}
function invalidateAddressViews() {
  for(const node of document.querySelectorAll('[aria-label="Checkout review"]'))node.outerHTML=review();
  for(const node of document.querySelectorAll('[aria-label="Current quote"]'))node.outerHTML=quoteView();
  for(const node of document.querySelectorAll('[aria-label="Delivery choices"]'))node.outerHTML=deliveryForm();
  const app=document.querySelector('#app');
  if(worldBinding)worldBinding.decorate(app);
  scheduleNativeQuote();
}
function addressForm() {return `<form data-form="address"><fieldset><legend>Recipient and delivery address</legend>${[['name','Full name','name'],['street','Street address','street-address'],['postcode','Postcode','postal-code'],['city','City','address-level2']].map(([key,label,autocomplete])=>`<label>${label}<input name="${key}" value="${e(state.address[key])}" autocomplete="${autocomplete}" required ${key==='postcode'?'inputmode="numeric" pattern="[0-9 ]{5,6}"':''}></label>`).join('')}${worldBinding?.checkoutCapabilities?.unitField?`<label>Apartment / unit (optional)<input name="unit" value="${e(state.address.unit)}" autocomplete="address-line2"></label>`:''}${worldBinding?.checkoutCapabilities?.instructions?`<label>Delivery instructions (optional)<textarea name="instructions">${e(state.instructions)}</textarea></label>`:''}<button>Save address</button><p>Country: Sweden. Shop collection uses the selected shop address.</p></fieldset></form>`;}
function deliveryForm() {
  const result=currentQuote();
  if(result.errors.length)return `<section aria-label="Delivery choices"><h2>Delivery choices</h2><p>Save a valid address to see available services, arrival estimates and costs.</p></section>`;
  return `<section aria-label="Delivery choices"><h2>Delivery choices</h2>${splitControls(result)}${result.shipments.map((shipment,index)=>`<fieldset class="delivery-options"><legend>${e(shipmentName(shipment))}</legend>${shipmentList(shipment)}${shipment.options.map(option=>`<label class="delivery-row" data-service-row><input type="radio" name="delivery-${index}" data-service-group="${e(shipment.key)}" value="${e(option.id)}" ${shipment.selected.id===option.id?'checked':''}><span><strong>${e(option.company)} — ${e(option.name)}</strong><br>${e(serviceTypes[option.type])} · ${e(option.location.name)}<br>${e(option.location.address)}<br>${option.arrival===null?'Arrival date not yet confirmed':option.local?'Ready today':`Estimated ${option.type==='home'?'delivery':'collection'}: ${e(option.arrival)}`}<br><strong>${money(option.fee)}</strong>${option.qualified?' · Free-delivery minimum reached':''}${option.type==='retailer_branch'?`<br>${option.payment==='collection'?'Pay at collection':'Pay online'}`:''}</span></label>`).join('')}</fieldset>`).join('')}${conf.policy==='checkout'?`<details><summary>Delivery policy</summary>${policyContent()}</details>`:''}</section>`;
}
function purchaseForm(result) {
  const paidAtCollection=result.shipments.length&&result.shipments.every(s=>s.selected.type==='retailer_branch'&&s.selected.payment==='collection');
  return `<form data-form="purchase"><h3>Payment</h3>${paidAtCollection?'<p>Pay at collection. No card details are needed.</p>':`<details><summary>Pay by card</summary><fieldset><legend>Card details</legend><label>Name on card<input name="cardName" autocomplete="cc-name" required></label><label>Card number<input name="cardNumber" autocomplete="cc-number" inputmode="numeric" pattern="[0-9 ]{13,23}" required></label><label>Expiry (MM/YY)<input name="expiry" autocomplete="cc-exp" placeholder="MM/YY" pattern="(0[1-9]|1[0-2])/[0-9]{2}" required></label><label>Security code<input name="securityCode" type="password" autocomplete="cc-csc" inputmode="numeric" pattern="[0-9]{3,4}" required></label></fieldset></details>`}<label><input name="terms" type="checkbox" required> I accept the ${link('info/terms','shopping terms')}.</label><p><button ${result.errors.length||!state.cart.length?'disabled':''}>Complete purchase</button></p></form>`;
}
function review() {const result=currentQuote();return `<section aria-label="Checkout review"><h2>Review before payment</h2>${quoteView(result)}${result.errors.length?'':purchaseForm(result)}</section>`;}
function checkout(params) {
  if(!state.cart.length) return `<h1>${e(g.checkout)}</h1><p>Add items to your ${e(cartNoun)} before arranging delivery.</p>${link('results','Browse products')}`;
  const heading=`<h1>${e(g.checkout)}</h1><p>${link('cart',`Return to ${e(g.cart.toLowerCase())}`,'data-checkout-back')}</p>`;
  if(conf.modules.checkout==='single') return `${heading}${addressForm()}${deliveryForm()}<section><h2>Discount code</h2>${couponForm()}</section>${review()}`;
  if(conf.modules.checkout==='sections') return `${heading}<details open><summary>1. Recipient and address</summary>${addressForm()}</details><details><summary>2. Delivery choices</summary>${deliveryForm()}</details><details><summary>3. Discount code</summary>${couponForm()}</details>${review()}`;
  const step=Math.max(1,Math.min(3,Number(params.get('step'))||1));
  return `${heading}<nav aria-label="Checkout steps"><ol>${['Address','Delivery','Review'].map((label,i)=>`<li>${link(`checkout?step=${i+1}`,e(label),step===i+1?'aria-current="step"':'')}</li>`).join('')}</ol></nav>${step===1?`${addressForm()}<p>${link('checkout?step=2','Continue to delivery')}</p>`:step===2?`${deliveryForm()}<section><h2>Discount code</h2>${couponForm()}</section>${quoteView()}<p>${link('checkout?step=1','Back to address')} · ${link('checkout?step=3','Continue to review')}</p>`:`${review()}<p>${link('checkout?step=2','Back to delivery')}</p>`}`;
}
const topics={...(worldBinding?{coupons:'Account and discount codes'}:{}),contact:'Contact and help',shipping:'Delivery policy',returns:'Returns',stores:'Our shops',sizing:'Size guide',care:'Product care',about:'About Northline',privacy:'Privacy',terms:'Shopping terms',orders:'Existing orders'};
function orderArticle(order) {
  return `<h3>Order ${e(order.id)}</h3><p>${e(order.date)} · ${e(order.status)}</p><ul>${order.items.map(item=>`<li>${e(item.name)}${item.options?' · '+e(item.options):''} · Quantity ${item.quantity} · ${money(item.subtotal)}</li>`).join('')}</ul><p>Products ${money(order.subtotal)}; discount ${money(order.discount)}; delivery ${money(order.shipping)}; total ${money(order.total)}.</p>${order.shipments.map(s=>`<p>${e(s.company)} · ${e(serviceTypes[s.type])} · ${e(s.location.name)}, ${e(s.location.address)} · ${s.arrival?e(s.arrival):'Arrival not yet confirmed'} · ${money(s.fee)}</p>`).join('')}<p>Payment: ${e(order.payment)}.</p>`;
}
function article(id) {
  if(worldBinding){const publicArticle=worldBinding.article(id,{e,link,money});if(publicArticle!==null)return publicArticle;}
  const placed=state.orders.find(order=>id===`order-${order.id}`);
  if(placed)return orderArticle(placed);
  switch(id) {
    case 'shipping':return policyContent();
    case 'contact':return `<dl><dt>Customer service</dt><dd>${e(shopContact.email)}</dd><dt>Telephone</dt><dd>${e(shopContact.phone)}</dd><dt>Opening hours</dt><dd>${e(shopContact.hours)}</dd></dl><p>For delivery charges, collection and supplier orders, see ${link('info/shipping','our delivery policy')}.</p>`;
    case 'stores':return `<div class="columns">${Object.values(branches).map(b=>`<section><h3>${e(b.name)}</h3><p>${e(b.address)}</p><p>${e(b.hours)}</p></section>`).join('')}</div><p>Stock is shown for the selected product configuration. Local collection and warehouse transfers are different services.</p>`;
    case 'returns':return '<p>Return unused products within 30 days with proof of purchase. Contact customer service for a bulky-item return. Return delivery is paid by the customer unless the product is faulty.</p>';
    case 'sizing':return '<p>Footwear with EU size labels uses the EU system. Check the options on the particular product: available sizes and width labels differ between models. A missing width measurement is not a claim of narrow or wide fit.</p><p>Apparel may use nominal alpha size labels. Those labels are not a body-measurement chart or a conversion to footwear sizes.</p><p>Read the basis alongside a mass or other measurement. A reference size is not necessarily the currently selected size.</p>';
    case 'care':return '<p>Use the material and care details on the selected product page. Let damp footwear dry at room temperature. Unplug electrical products before cleaning. Follow the instructions supplied with each product.</p>';
    case 'about':return `<p>Northline sells ${categories.map(c=>e(c.toLowerCase())).join(', ')} online and through our Uppsala and Stockholm shops.</p><nav aria-label="Our departments"><ul>${categoryList()}</ul></nav>`;
    case 'privacy':return '<p>This shop remembers your selected options and basket in this browser. A delivery address explicitly saved in checkout is used for later product-page delivery estimates at Northline.</p>';
    case 'terms':return `<p>Prices include VAT and are shown in Swedish kronor. You can inspect a full quote before providing payment details. ${link('info/shipping','Read delivery and collection terms')}.</p>`;
    case 'orders':return `<p>Orders previously placed with Northline:</p><ul>${state.orders.map(order=>`<li>${link(`info/order-${order.id}`,`Order ${e(order.id)} · ${e(order.date)} · ${e(order.status)}`)}</li>`).join('')}<li>${link('info/order-NL1048','Order NL1048 · 14 September 2026 · Delivered')}</li><li>${link('info/order-NL1062','Order NL1062 · 23 September 2026 · Ready for collection')}</li></ul>`;
    case 'order-NL1048':return '<h3>Order NL1048</h3><p>14 September 2026 · Delivered 18 September 2026.</p><p>Granvik Task Lamp, White, quantity 1. Products 399 SEK; home delivery 49 SEK; total 448 SEK.</p><p>Delivery address: Alex Lind, Parkgatan 4, 75310 Uppsala.</p>';
    case 'order-NL1062':return '<h3>Order NL1062</h3><p>23 September 2026 · Ready for collection at Uppsala shop.</p><p>Klint Stoneware Cup, quantity 2. Products 258 SEK; local collection 0 SEK; total 258 SEK. Pay at collection.</p><p>Collection address: Storgatan 8, Uppsala.</p>';
    default:return '<p>This information page does not exist.</p>';
  }
}
function info(id) {
  id=id||'contact';
  const peripheral=peripheralArticle(id,{e,link});
  if(peripheral)return peripheral;
  const title=topics[id] || (id.startsWith('order-')?'Order details':'Page not found');
  const topicLinks=Object.entries(topics).map(([key,label])=>link(`info/${key}`,e(label),key===id?'aria-current="page"':'')).join(' · ');
  if(conf.modules.info==='directory') return `<h1>${e(g.help)}</h1><nav aria-label="Help topics"><ul>${Object.entries(topics).map(([key,label])=>`<li>${link(`info/${key}`,e(label),key===id?'aria-current="page"':'')}</li>`).join('')}</ul></nav><article><h2>${e(title)}</h2>${article(id)}</article>`;
  if(conf.modules.info==='questions') return `<h1>${e(title)}</h1><nav aria-label="Help topics">${topicLinks}</nav>${id==='shipping'?`<details open><summary>What does delivery cost?</summary>${policyContent()}</details><details><summary>When will my items arrive?</summary><p>Check the full quote at checkout. Separate groups have their own arrival dates; a supplier backorder may have no confirmed date.</p></details>`:`<details open><summary>${id==='sizing'?'How do I choose a size?':id==='orders'?'Where are my previous orders?':e(title)}</summary>${article(id)}</details>`}<p>${link('info/contact','Contact customer service')}</p>`;
  if(id.startsWith('order-'))return `<h1>Order details</h1>${article(id)}${link('info/orders','All existing orders')}`;
  return `<h1>Customer handbook</h1><nav aria-label="Handbook contents">${Object.entries(topics).map(([key,label])=>link(`info/${key}`,e(label))).join(' · ')}</nav>${[id,...Object.keys(topics).filter(key=>key!==id)].map(key=>`<section id="article-${key}"><h2>${e(topics[key])}</h2>${article(key)}</section>`).join('')}`;
}
function resetDraft() {
  const policy=resetPolicy(conf);
  applyReset(state,initialAddress,policy);
  if(!worldBinding)delete state.addressStatus;
  save();feedback='Delivery details were reset. Check your address and delivery choices again.';
}
function render({captureDisclosures=true}={}) {
  if(captureDisclosures)for(const node of document.querySelectorAll('details[data-disclosure]'))state.disclosures[node.dataset.disclosure]=node.open;
  const r=route(),current=location.hash || '#/home';
  const step=r.role==='checkout'?(conf.modules.checkout==='steps'?Math.max(1,Math.min(3,Math.floor(Number(r.params.get('step')))||1)):1):null;
  if(previousRoute&&previousRoute!==current&&shouldReset({policy:resetPolicy(conf),
    from:{role:previousRoute.startsWith('#/checkout')?'checkout':'other',step:lastCheckoutStep},
    to:{role:r.role,step},historyBack,explicitBack}))resetDraft();
  historyBack=false;explicitBack=false;
  previousRoute=current;lastCheckoutStep=step;
  const content=r.role==='home'?home():r.role==='results'?results(r.params):r.role==='product'?productPage(r.id,r.params):r.role==='cart'?cart():r.role==='checkout'?checkout(r.params):r.role==='info'?info(r.id):'<h1>Page not found</h1>'+link('home','Home');
  document.title=`Northline | ${r.role==='product'?products.find(p=>p.id===r.id)?.name||'Product':r.role==='cart'?g.cart:r.role==='checkout'?g.checkout:r.role==='info'?topics[r.id]||peripheralPages.find(p=>p.id===r.id)?.title||g.help:r.role==='results'?g.catalog:'Home'}`;
  const focus=document.activeElement,focusId=focus?.dataset?.tab;
  document.querySelector('#app').innerHTML=`${skipLinks(variations.site.skipLinks)}${navbar()}<div class="shell">${sidebar()}<main id="main" tabindex="-1"><p id="feedback" role="status" aria-live="polite">${e(feedback)}</p>${content}</main></div>${footer()}`;
  const app=document.querySelector('#app');app.querySelector('header').id='site-navigation';app.querySelector('header').tabIndex=-1;app.querySelector('footer').id='site-footer';app.querySelector('footer').tabIndex=-1;
  applyNavigationVariation(app,variations.site);
  if(r.role==='home')applyHomeOrder(app.querySelector('main'),variations.home.sectionOrder);
  if(r.role==='product')moveRecommendations(app.querySelector('main'),variations.recommendations.placement);
  if(worldBinding)worldBinding.decorate(app);
  for(const node of document.querySelectorAll('details')){
    const shell=node.closest('header,footer,aside'),key=node.dataset.disclosureId||`${shell?shell.tagName:r.role+':'+r.id}:${node.querySelector(':scope > summary').textContent}`;
    node.dataset.disclosure=key;
    if(key in state.disclosures)node.open=state.disclosures[key];
    disclosureOpen.set(node,node.open);
  }
  save();
  if(focusId)document.querySelector(`[data-tab="${focusId}"]`)?.focus();
  scheduleNativeQuote();
}
document.addEventListener('click',event=>{
  const target=event.target.closest('button,a');if(!target)return;
  if(target.hasAttribute('data-checkout-back')&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&event.button===0)explicitBack=true;
  if(target.hasAttribute('data-skip')){event.preventDefault();const destination=document.getElementById(target.dataset.skip||'main');destination.focus();destination.scrollIntoView();return;}
  if(target.dataset.selectionButton){changeSelection(target.dataset.selectionButton,target.dataset.value);return;}
  if(target.dataset.edit){const l=state.cart.find(l=>l.id===target.dataset.edit);if(l){const {product,variant}=byVariant(l.key);state.editing=l.id;state.selection[product.id]={...variant.selection};save();}}
  if(target.dataset.remove){state.cart=state.cart.filter(l=>l.id!==target.dataset.remove);state.editing=null;revise('Item removed. Delivery and totals recalculated.');}
  if(target.dataset.tab){state.tab=target.dataset.tab;save();render();document.querySelector(`[data-tab="${state.tab}"]`)?.focus();}
});
document.addEventListener('keydown',event=>{
  if(event.target.getAttribute('role')!=='tab'||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  event.preventDefault();const names=Array.from(document.querySelectorAll('[role="tab"][data-tab]'),node=>node.dataset.tab),i=names.indexOf(event.target.dataset.tab);state.tab=event.key==='Home'?names[0]:event.key==='End'?names.at(-1):names[(i+(event.key==='ArrowRight'?1:names.length-1))%names.length];save();render();document.querySelector(`[data-tab="${state.tab}"]`)?.focus();
});
function changeSelection(key,value) {
  const r=route(),p=products.find(p=>p.id===r.id);state.selection[p.id]={...state.selection[p.id],[key]:value};
  const {variant}=resolveProduct(p.id,state.selection[p.id]);state.selection[p.id]={...variant.selection};save();feedback='';
  if(conf.url==='all'||conf.url==='colour'&&key==='colour')goto(variantPath(p,variant));else render();
}
document.addEventListener('change',event=>{
  const input=event.target;
  if(input.dataset.selection)changeSelection(input.dataset.selection,input.value);
  if(input.closest('[data-form="filters"]')&&variations.results.filterApply==='immediate')input.closest('form').requestSubmit();
  if(input.dataset.serviceGroup){const result=currentQuote(),group=result.shipments.find(s=>s.key===input.dataset.serviceGroup);if(group?.options.some(o=>o.id===input.value)){state.deliveryChoices[group.key]=input.value;revise('Delivery service selected. Totals recalculated.');}}
  if(input.dataset.split){state.split=input.dataset.split==='true';revise('Dispatch preference updated. Delivery and totals recalculated.');}
});
document.addEventListener('input',event=>{
  const form=event.target.closest('[data-form="address"]');
  if(!form||!worldBinding)return;
  if(event.target.name==='instructions'){state.instructions=event.target.value;state.revision++;save();invalidateAddressViews();return;}
  const values=Object.fromEntries(new FormData(form));delete values.instructions;
  addressRequest++;state.address=values;state.addressStatus='unvalidated';state.deliveryChoices={};state.revision++;save();
  invalidateAddressViews();
});
document.addEventListener('submit',async event=>{
  const form=event.target;if(!form.dataset.form)return;event.preventDefault();const data=new FormData(form),values=Object.fromEntries(data);
  if(form.dataset.form==='search'){goto(`results?q=${encodeURIComponent(values.q.trim())}`);}
  if(form.dataset.form==='filters'){const params=new URLSearchParams();for(const part of document.querySelectorAll('main [data-form="filters"]'))for(const [key,value] of new FormData(part))if(String(value).trim())params.set(key,value);if(params.get('category')!==route().params.get('category')&&params.get('category')){if(!availableRanges(products.filter(p=>p.category===params.get('category'))).length)params.delete('market_range');if(params.get('type')&&!typesFor(params.get('category')).includes(params.get('type')))params.delete('type');}goto(`results?${params}`);}
  if(form.dataset.form==='add'){
    if(worldBinding&&(Number(values.quantity)!==1||state.cart.length&&!state.editing)){feedback='Remove the current item before starting another one-item delivery inquiry.';render();return;}
    const {product,variant}=byVariant(form.dataset.key),quantity=Number(values.quantity);if(variant.state==='unavailable'||!Number.isInteger(quantity)||quantity<1||quantity>20){feedback='This item or quantity cannot be ordered.';render();return;}
    const editing=state.cart.find(l=>l.id===state.editing&&byVariant(l.key).product.id===product.id);
    if(editing){editing.key=variant.key;editing.quantity=quantity;state.editing=null;}
    else {const existing=state.cart.find(l=>l.key===variant.key);if(existing){if(existing.quantity+quantity>20){feedback='The maximum quantity is 20.';render();return;}existing.quantity+=quantity;}else state.cart.push({id:String(++state.serial),key:variant.key,quantity});}
    revise(editing?'Item updated. Delivery and totals recalculated.':`Added ${product.name} to ${g.cart.toLowerCase()}.`);
  }
  if(form.dataset.form==='quantity'){const l=state.cart.find(l=>l.id===form.dataset.line),quantity=Number(values.quantity);if(!Number.isInteger(quantity)||quantity<1||quantity>(worldBinding?1:20)){feedback=worldBinding?'This delivery inquiry supports a quantity of one.':'Quantity must be between 1 and 20.';render();return;}l.quantity=quantity;revise('Quantity updated. Delivery and totals recalculated.');}
  if(form.dataset.form==='coupon'){state.coupon=values.coupon;revise(conf.opaque?'Discount code processed.':'Discount code checked. Delivery and totals recalculated.');}
  if(form.dataset.form==='address'){
    const instructions=values.instructions;delete values.instructions;
    if(worldBinding){
      state.address={...values};state.addressStatus='pending';state.deliveryChoices={};
      if(instructions!==undefined)state.instructions=instructions;
      const request=++addressRequest;++state.revision;save();invalidateAddressViews();
      try{await worldBinding.refresh(values);}catch(error){
        if(addressRequest!==request||state.addressStatus!=='pending')return;
        state.addressStatus='invalid';feedback=error.message;save();render();return;
      }
      if(addressRequest!==request||state.addressStatus!=='pending')return;
    }
    const errors=validateAddress(values);if(errors.length){feedback=errors.join('; ');render();return;}
    state.address=Object.fromEntries(Object.entries(values).map(([key,value])=>[key,String(value).trim()]));
    state.address.postcode=state.address.postcode.replace(/\s/g,'');state.addressStatus='valid';
    state.remembered={...state.address};revise('Address saved. Delivery estimates and totals recalculated.');
  }
  if(form.dataset.form==='purchase'){
    if(worldBinding){feedback='Purchase submission is unavailable.';render();return;}
    const result=currentQuote();
    if(result.errors.length||!state.cart.length){feedback='Review your basket and delivery details before placing the order.';render();return;}
    const collection=result.shipments.every(s=>s.selected.type==='retailer_branch'&&s.selected.payment==='collection');
    if(!values.terms||(!collection&&(!values.cardName?.trim()||!/^\d{13,19}$/.test((values.cardNumber||'').replace(/\s/g,''))||! /^(0[1-9]|1[0-2])\/\d{2}$/.test(values.expiry||'')||!/^\d{3,4}$/.test(values.securityCode||'')))){feedback='Complete the payment details and accept the shopping terms.';render();return;}
    // This original local shop has no payment-provider/network call. Store the
    // resolved order snapshot, never card numbers, expiry or security codes.
    const order={id:`NL${2001+state.orders.length}`,date:'1 October 2026',status:'Order received',payment:collection?'Pay at collection':'Card',items:state.cart.map(line=>{const {product,variant}=byVariant(line.key);return {name:product.name,key:variant.key,options:Object.values(variant.selection).join(' / '),quantity:line.quantity,subtotal:variant.price*line.quantity};}),subtotal:result.subtotal,discount:result.discount,shipping:result.shipping,total:result.total,shipments:result.shipments.map(s=>({company:s.selected.company,type:s.selected.type,location:s.selected.location,arrival:s.arrival,fee:s.fee}))};
    state.orders.push(order);state.cart=[];state.coupon='';state.split=false;state.deliveryChoices={};state.editing=null;state.revision++;save();goto(`info/order-${order.id}`);
  }
});
window.addEventListener('hashchange',()=>{trackNavigation();feedback='';render();});
document.addEventListener('toggle',event=>{const node=event.target;if(node.tagName==='DETAILS'&&node.dataset.disclosure&&document.contains(node)&&disclosureOpen.get(node)!==node.open){disclosureOpen.set(node,node.open);state.disclosures[node.dataset.disclosure]=node.open;save();}},true);
window.addEventListener('storage',event=>{if(event.key===stateKey){state=JSON.parse(event.newValue)||fresh();applyingStoredState=true;try{render({captureDisclosures:false});}finally{applyingStoredState=false;}}});
if(worldBinding&&validateAddress(state.address).length)try{await worldBinding.refresh(state.address);}catch(error){feedback=error.message;}
if(worldBinding&&validateAddress(state.remembered).length)try{await worldBinding.refresh(state.remembered);}catch(error){feedback=error.message;}
render();
