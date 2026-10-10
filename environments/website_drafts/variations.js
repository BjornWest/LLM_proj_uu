import {rangeLabels} from './market-range.js';
// Explicit authoring options only. Distribution/conditioning adoption is separate.
export const variationControls = {
  site:{skipLinks:['main','none','regions'],navigation:['base','flat','grouped'],navigationGrouping:['departments','shopping-services'],selectors:['inherit','select','radio','buttons']},
  home:{sectionOrder:['base','showcase-first','services-first']},
  results:{presentation:['base','cards','list','table'],filterOrder:['seeded','catalog-first','price-first'],sortPlacement:['filters','toolbar'],filterApply:['submit','immediate']},
  product:{sectionOrder:['base','buying-first','details-first'],facts:['base','definitions','table'],detailsPresentation:['base','inline','disclosure','tabs'],purchaseRegion:['base','section','complementary','fieldset'],gallery:['stacked','list','featured'],highlightCount:['base','1','2','3','4']},
  cards:{detail:['base','compact','full'],grouping:['base','paragraphs','definitions']},
  recommendations:{presentation:['base','cards','list'],placement:['base','after-buying','after-information']},
};
export function variationSettings(value={}) {
  if(!value || typeof value!=='object' || Array.isArray(value))throw Error('Variations must be an object');
  if(Object.keys(value).some(role=>!Object.hasOwn(variationControls,role)))throw Error('Unknown variation role');
  return Object.fromEntries(Object.entries(variationControls).map(([role,fields])=>{
    const supplied=Object.hasOwn(value,role)?value[role]:{};
    if(!supplied || typeof supplied!=='object' || Array.isArray(supplied)||Object.keys(supplied).some(key=>!Object.hasOwn(fields,key)))throw Error(`Invalid ${role} variations`);
    return [role,Object.fromEntries(Object.entries(fields).map(([key,choices])=>{
      const selected=Object.hasOwn(supplied,key)?supplied[key]:choices[0];
      if(!choices.includes(selected))throw Error(`Invalid ${role}.${key} variation`);
      return [key,selected];
    }))];
  }));
}
export function filterOrder(keys,mode,seeded) {
  if(mode==='seeded')return seeded(keys);
  const priority=mode==='price-first'?['price','sort','category','market_range','type','brand']:['category','market_range','type','brand','price','sort'];
  return [...keys].sort((a,b)=>priority.indexOf(a)-priority.indexOf(b));
}
export function productSectionOrder(unit,mode,presentation='inline') {
  const order=mode==='buying-first'?['buying','overview','details','description','delivery']:
    mode==='details-first'?['details','description','overview','buying','delivery']:
    [...({story:['buying','overview','description','details','delivery'],tabs:['buying','description','details','delivery','overview'],technical:['details','buying','description','delivery','overview'],atelier:['description','buying','details','delivery','overview'],counter:['buying','delivery','overview','details','description'],marketplace:['overview','buying','details','description','delivery'],superstore:['overview','buying','description','details','delivery']})[unit]];
  // Information order varies; expanded catalogs/prose must not bury purchasing.
  // Only closed disclosures can precede the buying region. Tabs have an expanded
  // default panel, so they follow the same rule as inline information.
  if(presentation!=='disclosure') {
    const buying=order.indexOf('buying'),information=order.findIndex(k=>['details','description'].includes(k));
    if(information>=0&&information<buying){order.splice(buying,1);order.splice(information,0,'buying');}
  }
  return order;
}
export function skipLinks(mode) {
  if(mode==='none')return '';
  const links=mode==='regions'?[['main','Skip to content'],['site-navigation','Skip to navigation'],['site-footer','Skip to customer information']]:[['main','Skip to content']];
  return links.map(([id,label])=>`<a href="#${id}" data-skip="${id}">${label}</a>`).join('');
}
// Restructure existing, working destinations. No new catalog facts or routes.
export function applyNavigationVariation(root,settings) {
  if(settings.navigation==='base')return;
  for(const nav of root.querySelectorAll('header nav, aside nav')) {
    if(!nav.querySelector('a[href^="#/results"]')||nav.querySelector('form'))continue;
    const anchors=[...nav.querySelectorAll('a')];if(!anchors.length)continue;
    const heading=nav.querySelector(':scope > h2');const list=document.createElement('ul');
    const groups=new Map();
    for(const anchor of anchors) {
      const path=anchor.getAttribute('href');let key='Other shopping links';
      if(settings.navigationGrouping==='shopping-services')key=path.startsWith('#/info/')?'Help and services':'Shopping';
      else if(path.startsWith('#/results'))key=new URLSearchParams(path.split('?')[1]||'').get('category')||'All products';
      const item=document.createElement('li');item.append(anchor);
      if(settings.navigation==='flat')list.append(item);
      else {if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item);}
    }
    if(settings.navigation==='grouped')for(const [label,items] of groups) {
      const item=document.createElement('li'),details=document.createElement('details'),summary=document.createElement('summary'),children=document.createElement('ul');
      summary.textContent=label;details.dataset.disclosureId=`navigation:${nav.getAttribute('aria-label')}:${label}`;children.append(...items);details.append(summary,children);item.append(details);list.append(item);
    }
    nav.replaceChildren(...(heading?[heading]:[]),list);
  }
}
export function applyHomeOrder(main,mode) {
  if(mode==='base')return;
  const sections=[...main.children].filter(n=>n.matches('section,nav,div'));
  const priority=node=>mode==='showcase-first'?(node.querySelector('[data-product-card]')?0:1):(/shop|visit|service|help|contact/i.test(node.getAttribute('aria-label')||node.querySelector('h2')?.textContent||'')?0:1);
  const anchor=sections[0];if(!anchor)return;
  const marker=document.createComment('home sections');anchor.before(marker);
  for(const node of [...sections].sort((a,b)=>priority(a)-priority(b)))marker.before(node);
  marker.remove();
}
export function variedCard(p,h) {
  const settings=h.variations||variationSettings(h.conf?.variations),options=settings.cards;
  if(options.detail==='base'&&options.grouping==='base')return null;
  const {e,link,money}=h,v=p.variants.reduce((a,b)=>a.price<=b.price?a:b),orderable=p.variants.filter(v=>v.state!=='unavailable');
  const status=orderable.some(v=>v.state==='in_stock')?'In-stock options':orderable.length?'Supplier backorder':'Currently unavailable';
  const pairs=[['Brand',e(p.brand)],['Product type',e(p.type)],['Price from',money(v.price)],['Ordering',e(status)]];
  if(options.detail==='full') {
    if(p.marketRange?.status==='known')pairs.push(['Market range',e(rangeLabels[p.marketRange.value])]);
    if(p.options.length)pairs.push(['Available options',p.options.map(o=>`${e(o.label)}: ${o.values.map(e).join(', ')}`).join(' · ')]);
  }
  const details=options.grouping==='paragraphs'?pairs.map(([label,value])=>`<p><strong>${label}:</strong> ${value}</p>`).join(''):`<dl>${pairs.map(([label,value])=>`<dt>${label}</dt><dd>${value}</dd>`).join('')}</dl>`;
  const intro=options.detail==='compact'||!p.introduction?.trim()?'':`<p>${e(p.introduction)}</p>`;
  return `<article data-product-card="${e(p.id)}"><h3>${link(`product/${p.id}`,e(p.name))}</h3>${intro}${details}<p>${link(`product/${p.id}`,p.options.length?'View options':'View product')}</p></article>`;
}
export function renderGallery(images,mode,e) {
  if(!images?.length)return '';
  const image=item=>`<figure><img src="${e(item.src)}" alt="${e(item.alt)}">${item.caption?`<figcaption>${e(item.caption)}</figcaption>`:''}</figure>`;
  if(mode==='list')return `<section aria-label="Product images"><h2>Product images</h2><ul>${images.map(i=>`<li>${image(i)}</li>`).join('')}</ul></section>`;
  if(mode==='featured')return `<section aria-label="Product images"><h2>Product images</h2><section aria-label="Main product image">${image(images[0])}</section>${images.length>1?`<section aria-label="Other product views"><h3>Other views</h3>${images.slice(1).map(image).join('')}</section>`:''}</section>`;
  return `<section aria-label="Product images"><h2>Product images</h2>${images.map(image).join('')}</section>`;
}
export function moveRecommendations(main,mode) {
  if(mode==='base')return;
  const rows=[...main.querySelectorAll('[data-recommendations]')];if(!rows.length)return;
  let anchor;
  if(mode==='after-buying')anchor=main.querySelector('[data-product-part="buying"]');
  else {
    anchor=main.querySelector('[data-product-core]');
    if(!anchor){
      const panels=[...main.querySelectorAll('[role="tabpanel"], [data-product-part="details"], [data-product-part="description"]')];anchor=panels.at(-1);
      // Keep the completed information wrapper together, including disclosures.
      while(anchor?.parentElement&&anchor.parentElement!==main)anchor=anchor.parentElement;
    }
  }
  if(!anchor)return;
  let last=anchor;for(const row of rows){last.after(row);last=row;}
}
