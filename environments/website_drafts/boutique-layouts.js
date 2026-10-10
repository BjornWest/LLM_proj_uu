// Small-store architecture over the same public authoring assortment. Content
// stays independent of tasks and layouts; all detail/control bindings are shared.
import {products,categories,typesFor} from './catalog.js';
import {homeContent} from './home-content.js';
import {optionalParagraph} from './product-content.js';
import {shuffled,moduleSeed} from './manifest.js';
import {availableRanges,rangeLabels} from './market-range.js';
import {variedCard,variationSettings} from './variations.js';

export function boutiqueCard(p,h) {
  const custom=variedCard(p,h);if(custom!==null)return custom;
  const {e,link,money}=h;
  const orderable=p.variants.filter(v=>v.state!=='unavailable');
  const status=orderable.some(v=>v.state==='in_stock')?'In-stock options':orderable.length?'Supplier order':'Currently unavailable';
  return `<article data-product-card="${e(p.id)}"><h3>${link(`product/${p.id}`,e(p.name))}</h3>${optionalParagraph(p.introduction,e)}<p>${p.variants.length>1?'From ':''}${money(Math.min(...p.variants.map(v=>v.price)))} · ${e(status)}</p><p>${link(`results?${new URLSearchParams({brand:p.brand})}`,e(p.brand))} · ${e(p.type)}${p.marketRange.status==='known'?` · ${e(rangeLabels[p.marketRange.value])}`:''}</p></article>`;
}
export function boutiqueHome(kind,h) {
  const {e,link,branches}=h,plan=homeContent(products,moduleSeed(h.conf,'home'));
  const cards=plan.showcase.map(p=>boutiqueCard(p,h)),shopBranches=Object.values(branches);
  if(kind==='atelier')return `<h1>A journal of everyday things</h1><p>Explore pieces for home, work and time outside.</p>${plan.collections.map((d,i)=>`<section aria-label="${e(d.title)}"><h2>${e(d.title)}</h2><p>${e(d.intro)}</p>${link(`results?${new URLSearchParams({category:d.category})}`,`Browse ${e(d.category.toLowerCase())}`)}${i<2&&cards.slice(i*2,i*2+2).length?`<div class="grid">${cards.slice(i*2,i*2+2).join('')}</div>`:''}</section>`).join('')}<section><h2>Choosing and caring</h2><p>${link('info/sizing','Size guidance')} · ${link('info/care','Product care')} · ${link('info/about','About our shop')}</p></section>`;
  return `<h1>Welcome to our shop</h1><section><h2>Northline</h2><p>Browse the range online${shopBranches.length?' or visit a shop to see the listed goods':''}.</p>${link('results','Browse the shop')}</section>${cards.length?`<section aria-label="On the shelves"><h2>On the shelves</h2><ul>${cards.map(c=>`<li>${c}</li>`).join('')}</ul></section>`:''}${shopBranches.length?`<section><h2>Visit Northline</h2><dl>${Object.values(branches).map(b=>`<dt>${e(b.name)}</dt><dd><address>${e(b.address)}</address><p>${e(b.hours)}</p></dd>`).join('')}</dl>${link('info/stores','Shop information and collection')} · ${link('info/contact','Contact the shop')}</section>`:`<p>${link('info/contact','Contact the shop')}</p>`}`;
}
export function boutiqueNavigation(kind,{e,link,cartLink,searchForm,categoryList,g}) {
  if(kind==='atelier')return `<header><nav aria-label="Shop navigation">${link('home','<strong>Northline</strong>')} · ${link('results',e(g.catalog))} · ${link('info/about','About the shop')} · ${link('info/contact',e(g.help))} · ${cartLink()}</nav>${searchForm()}</header>`;
  return `<header><nav aria-label="Shop utilities">${link('home','<strong>Northline</strong>')} · ${cartLink()} · ${link('info/orders','My orders')} · ${link('info/contact',e(g.help))}</nav><nav aria-label="Shop collections"><details><summary>Shop collections</summary><ul>${categoryList()}</ul>${link('results',e(g.catalog))}</details></nav>${searchForm()}</header>`;
}
export function boutiqueSidebar(kind,{e,link,categoryList,g}) {
  if(kind==='atelier')return `<aside><nav aria-label="Collections"><details><summary>Explore the collections</summary><ul>${categoryList()}</ul></details><p>${link('results',e(g.catalog))}</p></nav></aside>`;
  return `<aside><nav aria-label="Shop shelves"><h2>Browse the shop</h2><ul>${categories.map(category=>{
    const ranges=availableRanges(products.filter(p=>p.category===category));
    const rows=[...ranges.map(value=>link(`results?${new URLSearchParams({category,market_range:value})}`,e(`${rangeLabels[value]} ${category.toLowerCase()}`))),...typesFor(category).map(type=>link(`results?${new URLSearchParams({category,type})}`,e(type)))];
    return `<li>${link(`results?${new URLSearchParams({category})}`,e(category))}<details><summary>Refine ${e(category.toLowerCase())}</summary><ul>${rows.map(row=>`<li>${row}</li>`).join('')}</ul></details></li>`;
  }).join('')}</ul>${link('results',e(g.catalog))}</nav><p>${link('info/stores','Visit a shop')}</p></aside>`;
}
export function boutiqueFooter(kind,{e,link,conf,shopContact,g}) {
  const policy=conf.policy==='footer'?[['shipping','Delivery policy']]:[];
  if(kind==='atelier')return `<footer><nav aria-label="Shopping information"><h2>${e(g.help)}</h2><ul>${[['contact','Contact'],['stores','Our shops'],['sizing','Size guide'],['care','Product care'],...policy].map(([id,title])=>`<li>${link(`info/${id}`,e(title))}</li>`).join('')}</ul></nav><nav aria-label="About the shop"><h2>About Northline</h2><ul>${[['about','Our shop'],['orders','Existing orders'],['returns','Returns'],['privacy','Privacy'],['terms','Terms']].map(([id,title])=>`<li>${link(`info/${id}`,e(title))}</li>`).join('')}</ul></nav></footer>`;
  return `<footer><section><h2>Contact Northline</h2><dl><dt>Telephone</dt><dd>${e(shopContact.phone)}</dd><dt>Email</dt><dd>${e(shopContact.email)}</dd><dt>Customer-service hours</dt><dd>${e(shopContact.hours)}</dd></dl><p>${link('info/contact',e(g.help))} · ${link('info/stores','Our shops')} · ${link('info/about','About Northline')}</p></section><nav aria-label="Shop policies"><details><summary>Shop policies and information</summary><ul>${[['returns','Returns'],['privacy','Privacy'],['terms','Terms'],['care','Product care'],['sizing','Size guide'],['orders','Existing orders'],...policy].map(([id,title])=>`<li>${link(`info/${id}`,e(title))}</li>`).join('')}</ul></details></nav></footer>`;
}
export function boutiqueRecommendations(p,kind,h) {
  const local=products.filter(q=>q.id!==p.id&&q.category===p.category);
  const chosen=shuffled(local,moduleSeed(h.conf,'product'),`boutique:related:${p.id}`).slice(0,kind==='atelier'?3:2);
  if(!chosen.length)return '';
  const presentation=variationSettings(h.conf?.variations).recommendations.presentation;
  return `<section data-recommendations aria-label="Other pieces in this collection"><h2>Other pieces in this collection</h2>${presentation==='cards'||presentation==='base'&&kind==='atelier'?`<div class="grid">${chosen.map(q=>boutiqueCard(q,h)).join('')}</div>`:`<ul>${chosen.map(q=>`<li>${boutiqueCard(q,h)}</li>`).join('')}</ul>`}</section>`;
}
export function boutiqueProduct(kind,p,h) {
  const {e,link,heading,description,buying,services,facts,overview}=h;
  const help=`<p>${link('info/returns','Returns information')} · ${link('info/contact','Ask the shop')}</p>`;
  const details=facts(kind==='atelier'?'definitions':'disclosures');
  if(kind==='atelier')return `${heading}${buying}${description?`<article aria-label="The product story"><h2>About this piece</h2>${description}</article>`:''}<section aria-label="More about this piece"><h2>More about this piece</h2>${details?`<details><summary>Details of the selected option</summary>${details}</details>`:''}<details><summary>Availability and delivery</summary>${services}</details></section>${boutiqueRecommendations(p,kind,h)}${help}`;
  return `${heading}${optionalParagraph(p.introduction,e)}${buying}${services}${overview}${details?`<section aria-label="Product handbook"><h2>Details of your selection</h2>${details}</section>`:''}${description?`<article aria-label="Product description"><h2>Product description</h2>${description}</article>`:''}${help}${boutiqueRecommendations(p,kind,h)}`;
}
export function boutiqueResults(kind,h) {
  const {e,link,money,heading,filterForm,batch,paging,empty}=h;
  if(kind==='atelier')return `${heading}<details><summary>Refine this collection</summary>${filterForm}</details><section aria-label="Product results"><div class="grid">${batch.map(p=>boutiqueCard(p,h)).join('')}</div>${batch.length?'':empty}${paging}</section>`;
  return `${heading}${filterForm}<section aria-label="Product results">${batch.length?`<div class="scroll"><table><caption>Shop listings — lowest listed option prices</caption><thead><tr><th>Product</th><th>From price</th><th>Options</th><th>Ordering</th></tr></thead><tbody>${batch.map(p=>`<tr data-product-card="${e(p.id)}"><th scope="row">${link(`product/${p.id}`,e(p.name))}<p>${e(p.type)}${p.marketRange.status==='known'?` · ${e(rangeLabels[p.marketRange.value])}`:''}</p></th><td>${money(Math.min(...p.variants.map(v=>v.price)))}</td><td>${p.options.length?e(p.options.map(o=>o.label).join(', ')):'One configuration'}</td><td>${p.variants.some(v=>v.state==='in_stock')?'In-stock options':p.variants.some(v=>v.state==='backorder')?'Supplier order':'Currently unavailable'}</td></tr>`).join('')}</tbody></table></div>`:empty}${paging}</section>`;
}
