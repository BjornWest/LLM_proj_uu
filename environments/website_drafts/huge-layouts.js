// Additive huge-retailer page units. Peripheral articles are deliberately fixed
// across seeds; assortment discovery/recommendations use only public records.
import {products,categories,brands,typesFor} from './catalog.js';
import {homeContent} from './home-content.js';
import {optionalParagraph} from './product-content.js';
import {shuffled,moduleSeed} from './manifest.js';
import {variedCard,variationSettings} from './variations.js';

const corporateGroups = [
  ['Our company',['Company history','Leadership principles','Working together','Careers journal','Press room','Brand resources','Company milestones','Office life']],
  ['Places and spaces',['Architecture archive','Workplace design','Town histories','City walks','Public spaces','Landscape notes','Local landmarks','Building stories']],
  ['Culture and collections',['Museum notebook','Design collections','Craft traditions','Photography archive','Music notebook','Literature journal','Exhibition notes','Objects and stories']],
  ['Learning and ideas',['Learning library','Research notebook','Creative practice','Writing workshop','Design vocabulary','Reading lists','Ideas exchange','Learning together']],
  ['Business connections',['Supplier stories','Partner directory','Industry perspectives','Small business journal','Trade exhibitions','Business library','Independent makers','Enterprise notebook']],
  ['Materials and making',['Material library','Manufacturing stories','Craft notebook','Colour archive','Textile histories','Woodland journal','Ceramics archive','Metalwork notebook']],
  ['The editorial desk',['Weekend reading','Long-form essays','Conversation archive','Editors notebook','Seasonal journal','Illustration archive','Behind the stories','Contributors directory']],
  ['Media and publishing',['Publishing library','Audio notebook','Film archive','Digital editions','Magazine index','Studio journal','Media resources','Broadcast archive']],
  ['Community stories',['Neighbourhood notebook','Community gardens','Volunteer journal','Local partnerships','Shared spaces','People and places','Community interviews','Gathering stories']],
  ['From the archives',['Timeline collection','Historic catalogues','Early advertising','Packaging archive','Correspondence collection','Archive highlights','Document library','Preserving stories']],
  ['Northline network',['Northline Studio','Northline Editions','Northline Audio','Northline Journal','Northline Archives','Northline Design Library','Northline Conversations','Northline Collections']],
];
export const peripheralPages = corporateGroups.flatMap(([group,titles],g)=>titles.map((title,i)=>({
  id:`company-${g}-${i}`,title,group,
  summary:`Notes, essays and background reading from our ${title.toLowerCase()}.`,
  text:`The ${title.toLowerCase()} brings together short essays, reading lists and observations from the wider world of ${group.toLowerCase()}. Familiar places and everyday objects offer starting points for exploring how ideas develop over time.`,
  continuation:'Collections grow through conversations, notebooks and the careful preservation of older material. Some entries focus on a single object or place; others follow a theme across several years. Browse at your own pace and return to the shop whenever you wish.',
})));
export function peripheralArticle(id,{e,link}) {
  const page=peripheralPages.find(p=>p.id===id);
  return page?`<h1>${e(page.title)}</h1><p>${e(page.group)}</p><article><h2>From the notebook</h2><p>${e(page.text)}</p><p>${e(page.continuation)}</p></article><p>${link('home','Return to Northline')} · ${link('results','Browse products')}</p>`:null;
}
export function hugeFooter(kind,{e,link}) {
  if(kind==='marketplace')return `<section aria-label="Explore Northline"><h2>Explore Northline</h2><div class="columns">${corporateGroups.map(([group],g)=>`<nav aria-label="${e(group)}"><h3>${e(group)}</h3><ul>${peripheralPages.filter(p=>p.id.startsWith(`company-${g}-`)).map(p=>`<li>${link(`info/${p.id}`,e(p.title))}<p>${e(p.summary)}</p></li>`).join('')}</ul></nav>`).join('')}</div></section>`;
  return `<section aria-label="Northline corporate directory"><h2>More from Northline</h2><ul>${corporateGroups.map(([group],g)=>`<li><section><h3>${e(group)}</h3><dl>${peripheralPages.filter(p=>p.id.startsWith(`company-${g}-`)).map(p=>`<dt>${link(`info/${p.id}`,e(p.title))}</dt><dd><p>${e(p.summary)}</p></dd>`).join('')}</dl></section></li>`).join('')}</ul><nav aria-label="Brand index"><h3>Brands in our catalog</h3><ul>${brands.map(brand=>`<li>${link(`results?${new URLSearchParams({brand})}`,e(brand))}</li>`).join('')}</ul></nav></section>`;
}

export function denseCard(p,h) {
  const custom=variedCard(p,h);if(custom!==null)return custom;
  const {e,link,money}=h;
  const orderable=p.variants.filter(v=>v.state!=='unavailable'),price=Math.min(...p.variants.map(v=>v.price));
  const status=orderable.some(v=>v.state==='in_stock')?'In-stock options':orderable.length?'Supplier order':'Currently unavailable';
  return `<article data-product-card="${e(p.id)}"><h3>${link(`product/${p.id}`,e(p.name))}</h3><p>${link(`results?${new URLSearchParams({brand:p.brand})}`,e(p.brand))} · ${e(p.type)}</p>${optionalParagraph(p.introduction,e)}<dl><dt>${p.variants.length>1?'From price':'Price'}</dt><dd>${money(price)}</dd><dt>Ordering</dt><dd>${e(status)}</dd></dl>${p.options.length?`<p>${e(p.options.map(o=>`${o.label}: ${o.values.join(', ')}`).join(' · '))}</p>`:''}<p>${link(`product/${p.id}`,'View product')}</p></article>`;
}
function rail(title,items,h,mode='cards',path='results') {
  const {e,link}=h;
  if(!items.length)return '';
  return `<section ${h.recommendation?'data-recommendations':''} aria-label="${e(title)}"><h2>${e(title)}</h2>${mode==='list'?`<ul>${items.map(p=>`<li>${denseCard(p,h)}</li>`).join('')}</ul>`:`<div class="grid">${items.map(p=>denseCard(p,h)).join('')}</div>`}<p>${link(path,'Explore more')}</p></section>`;
}
function editorialTiles(plan,{e,link},kind) {
  if(!plan.collections.length)return '';
  return `<section aria-label="Collection features"><h2>${kind==='marketplace'?'Discover something different':'Ideas for everyday life'}</h2><div class="grid">${plan.collections.map(d=>`<article><h3>${e(d.title)}</h3><p>${e(d.intro)}</p>${link(`results?${new URLSearchParams({category:d.category})}`,`Explore ${e(d.category.toLowerCase())}`)}<ul>${d.types.slice(0,3).map(type=>`<li>${link(`results?${new URLSearchParams({category:d.category,type})}`,e(type))}</li>`).join('')}</ul></article>`).join('')}</div></section>`;
}
function readingTiles({e,link},kind) {
  const pool=kind==='marketplace'?peripheralPages.slice(48,56):peripheralPages.slice(8,16);
  return `<section aria-label="More to read"><h2>More to read</h2><div class="grid">${pool.map(p=>`<article><h3>${link(`info/${p.id}`,e(p.title))}</h3><p>${e(p.summary)}</p></article>`).join('')}</div></section>`;
}
function brandProfiles(h,kind) {
  const {e,link,conf}=h;
  const selected=shuffled(brands,moduleSeed(conf,'home'),'huge:home:brand-profiles').slice(0,12);
  if(!selected.length)return '';
  const entries=selected.map(brand=>{
    const carried=products.filter(p=>p.brand===brand),departments=[...new Set(carried.map(p=>p.category))];
    return `<article><h3>${link(`results?${new URLSearchParams({brand})}`,e(brand))}</h3><dl><dt>Listed models</dt><dd>${carried.length}</dd><dt>Departments</dt><dd>${e(departments.join(' · '))}</dd></dl><p>${link(`results?${new URLSearchParams({brand})}`,'Explore the brand')}</p></article>`;
  });
  return `<section aria-label="Brand collections"><h2>Brands and collections</h2>${kind==='marketplace'?`<div class="grid">${entries.join('')}</div>`:`<ul>${entries.map(entry=>`<li>${entry}</li>`).join('')}</ul>`}</section>`;
}
function discoveryMosaic(h) {
  const {e,link}=h;
  return `<section aria-label="Discover the departments"><h2>Find your next interest</h2><div class="grid">${homeContent(products,moduleSeed(h.conf,'home')).departments.map(d=>`<article><h3>${e(d.title)}</h3><p>${e(d.intro)}</p><ul>${d.types.slice(0,4).map(type=>`<li>${link(`results?${new URLSearchParams({category:d.category,type})}`,e(type))}</li>`).join('')}</ul><p>${link(`results?${new URLSearchParams({category:d.category})}`,'See the collection')}</p></article>`).join('')}</div></section>`;
}
function customerAdvice({e,link}) {
  const items=[['stores','Visit our shops','Addresses, opening hours and collection information.'],['sizing','Choosing a size','Measurement guidance for the product you select.'],['care','Product care','Care information for everyday goods.'],['returns','Returns information','Read the return terms before contacting the shop.'],['orders','An existing order','Look up items and delivery details from an existing order.'],['contact','Customer service','Telephone, email and opening hours.'],['about','About Northline','Background on our shop and its range.'],['privacy','Privacy information','Information about remembered shopping preferences.'],['terms','Shopping terms','Read our prices and shopping terms.']];
  const groups=[['Products and shops','Guidance for choosing and looking after a product.',items.slice(0,3)],['Help with shopping','Support before and after an order.',items.slice(3,6)],['About the shop','Company information and shopping terms.',items.slice(6)]];
  return `<section aria-label="Shopping with Northline"><h2>Shopping with Northline</h2>${groups.map(([title,intro,entries])=>`<section><h3>${e(title)}</h3><p>${e(intro)}</p><ul>${entries.map(([id,label,note])=>`<li><article><h4>${link(`info/${id}`,e(label))}</h4><p>${e(note)}</p></article></li>`).join('')}</ul></section>`).join('')}</section>`;
}
export function hugeHome(kind,h) {
  const {e,link,conf}=h,plan=homeContent(products,moduleSeed(conf,'home'));
  // Fixed bounded sample: never a whole assortment, availability preference or
  // task answer. In production this belongs to the central content export.
  const picks=shuffled(products,moduleSeed(conf,'home'),'huge:home:featured').slice(0,16);
  if(kind==='marketplace')return `<h1>Discover Northline</h1><p>Find everyday goods, explore our collections and take another look at the range.</p>${editorialTiles(plan,h,kind)}${rail('A selection for your day',picks.slice(0,4),h)}${discoveryMosaic(h)}${rail('You might also like',picks.slice(4,8),h)}${brandProfiles(h,kind)}${rail('More to explore',picks.slice(8,12),h)}${readingTiles(h,kind)}${rail('Another look at the shop',picks.slice(12),h)}${customerAdvice(h)}`;
  return `<h1>Everyday ideas, a wider choice</h1><section><h2>Make room for the everyday</h2><p>Explore goods for home, work and time outside.</p>${link('results','Explore the range')}</section>${rail('Featured from our catalog',picks.slice(0,8),h)}${editorialTiles(plan,h,kind)}${rail('Take another look',picks.slice(8),h)}${brandProfiles(h,kind)}${readingTiles(h,kind)}<section><h2>Services and support</h2><ul>${[['stores','Shop addresses and collection'],['sizing','Sizing and measurements'],['care','Product-care handbook'],['returns','Returns information'],['orders','Existing orders'],['contact','Customer service']].map(([id,title])=>`<li>${link(`info/${id}`,e(title))}</li>`).join('')}</ul></section>`;
}
export function hugeRecommendations(p,kind,h) {
  const used=new Set([p.id]),groups=[];
  function add(title,pool,count,path='results') {
    const picked=shuffled(pool.filter(q=>!used.has(q.id)),moduleSeed(h.conf,'product'),`huge:recommendations:${p.id}:${title}`).slice(0,count);
    for(const q of picked)used.add(q.id);
    if(picked.length)groups.push({title,picked,path});
  }
  add('Similar models to explore',products.filter(q=>q.category===p.category),8,`results?${new URLSearchParams({category:p.category})}`);
  add(`More from ${p.brand}`,products.filter(q=>q.brand===p.brand),8,`results?${new URLSearchParams({brand:p.brand})}`);
  add('You might also like',products,8);
  add('Discover other parts of the range',products,(kind==='marketplace'?32:28)-(used.size-1));
  const setting=variationSettings(h.conf?.variations).recommendations.presentation;
  return groups.map(g=>rail(g.title,g.picked,{...h,recommendation:true},setting==='base'?(kind==='marketplace'?'cards':'list'):setting,g.path)).join('');
}
export function hugeComparison(p,h) {
  const {e,link,money}=h;
  const peers=shuffled(products.filter(q=>q.id!==p.id&&q.category===p.category),moduleSeed(h.conf,'product'),`huge:compare:${p.id}`).slice(0,4);
  return `<section aria-label="Explore other models"><h2>Explore other models</h2><div class="scroll"><table><caption>Other models in this department — lowest listed configuration prices</caption><thead><tr><th>Model</th><th>Brand</th><th>Product type</th><th>From price</th><th>Options</th></tr></thead><tbody>${peers.map(q=>`<tr><th scope="row">${link(`product/${q.id}`,e(q.name))}</th><td>${e(q.brand)}</td><td>${e(q.type)}</td><td>${money(Math.min(...q.variants.map(v=>v.price)))}</td><td>${q.options.length?e(q.options.map(o=>o.label).join(', ')):'One configuration'}</td></tr>`).join('')}</tbody></table></div></section>`;
}
export function hugeNavigation(kind,h) {
  const {e,link,cartLink,searchForm,categoryLinks,categoryList,g}=h;
  const utilities=`${cartLink()} · ${link('info/orders','My orders')} · ${link('info/contact',e(g.help))} · ${link('info/stores','Our shops')}`;
  if(kind==='marketplace')return `<header><div class="row">${link('home','<strong>Northline</strong>')}<nav aria-label="Shopping utilities">${utilities}</nav></div>${searchForm()}<nav aria-label="Department ribbon">${link('results',e(g.catalog))} · ${categoryLinks()}</nav><nav aria-label="All departments"><details><summary>All departments</summary><ul>${categoryList()}</ul></details>${link('info/about','About Northline')} · ${link('info/care','Product care')} · ${link('info/sizing','Size guide')}</nav></header>`;
  return `<header><div class="columns">${link('home','<strong>Northline</strong>')}${searchForm()}<nav aria-label="Shopping utilities">${utilities}</nav></div><nav aria-label="Departments">${link('results',e(g.catalog))} · ${categoryLinks()}</nav><nav aria-label="Selected brands">${brands.slice(0,8).map(brand=>link(`results?${new URLSearchParams({brand})}`,e(brand))).join(' · ')}</nav></header>`;
}
export function hugeSidebar(kind,h) {
  const {e,link,categoryList,g,conf}=h;
  if(kind==='superstore')return `<aside><nav aria-label="Catalog hierarchy"><h2>Explore the departments</h2><ul>${categoryList()}</ul>${link('results',e(g.catalog))}</nav><section><h2>Plan your visit</h2><p>${link('info/stores','Our shops and collection')}</p>${link('info/contact',e(g.help))}</section></aside>`;
  return `<aside><nav aria-label="Shopping shortcuts"><h2>Shopping shortcuts</h2><ul>${categories.map(c=>`<li>${link(`results?${new URLSearchParams({category:c})}`,e(c))}</li>`).join('')}</ul>${link('results',e(g.catalog))}</nav><nav aria-label="Featured brands"><h2>Brands to explore</h2><ul>${homeContent(products,moduleSeed(conf,'sidebar')).brands.map(b=>`<li>${link(`results?${new URLSearchParams({brand:b.name})}`,e(b.name))}</li>`).join('')}</ul></nav><section><h2>Customer information</h2><ul>${[['stores','Shop collection'],['care','Product care'],['sizing','Size guide'],['returns','Returns'],['contact',g.help]].map(([id,title])=>`<li>${link(`info/${id}`,e(title))}</li>`).join('')}</ul></section></aside>`;
}
