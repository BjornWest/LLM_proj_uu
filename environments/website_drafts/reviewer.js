import {variationControls,variationSettings} from './variations.js';
import {units,hugeUnits,boutiqueUnits,globals,configuration,validateConfiguration} from './manifest.js';
import {resolveProduct} from './catalog.js';
import {initialAddress} from './quote.js';
const form=document.querySelector('#compose'),frame=document.querySelector('#preview');
const copyButton=document.querySelector('#copy-config'),copyStatus=document.querySelector('#copy-status');
const assetRevision=new URL(import.meta.url).pathname.match(/\/assets\/([^/]+)\//)?.[1];
function previewUrl(page){return `shop.html?site=${site}${assetRevision?`&v=${assetRevision}`:''}#/${page}`;}
let conf=configuration(41),site='';
for(const [id,g] of Object.entries(globals)){const option=new Option(g.name,id);form.elements.global.add(option);}
for(const [role,choices] of Object.entries(units)){
  const label=document.createElement('label');label.className='unit-select';label.append(role.charAt(0).toUpperCase()+role.slice(1));
  const select=document.createElement('select');select.name=`module-${role}`;
  for(const [id,title] of choices)select.add(new Option(title,id));
  label.append(select);document.querySelector('#modules').append(label);
}
for(const [role,fields] of Object.entries(variationControls)){
  const group=document.createElement('fieldset'),legend=document.createElement('legend');legend.textContent=role;group.append(legend);
  for(const [key,choices] of Object.entries(fields)){const label=document.createElement('label'),select=document.createElement('select');label.append(key.replace(/([A-Z])/g,' $1').toLowerCase());select.name=`variation-${role}-${key}`;for(const choice of choices)select.add(new Option(choice,choice));label.append(select);group.append(label);}document.querySelector('#variation-controls').append(group);
}
function fill(value){conf=value;const settings=variationSettings(value.variations);for(const [role,fields] of Object.entries(settings))for(const [key,item] of Object.entries(fields))form.elements[`variation-${role}-${key}`].value=item;for(const [key,item] of Object.entries(value)){if(key==='modules'){for(const [role,id] of Object.entries(item))form.elements[`module-${role}`].value=id;}else if(form.elements[key]){if(typeof item==='boolean')form.elements[key].checked=item;else form.elements[key].value=item;}}}
function read(){const value={...conf,seed:Number(form.elements.seed.value),modules:{}};for(const role of Object.keys(units))value.modules[role]=form.elements[`module-${role}`].value;for(const key of ['search','iconCart','split','reset','opaque'])value[key]=form.elements[key].checked;for(const key of ['scale','global','url','policy','qualification','collectionPayment'])value[key]=form.elements[key].value;value.variations=Object.fromEntries(Object.entries(variationControls).map(([role,fields])=>[role,Object.fromEntries(Object.keys(fields).map(key=>[key,form.elements[`variation-${role}-${key}`].value]))]));return validateConfiguration(value);}
function hash(text){let h=2166136261;for(const c of text)h=Math.imul(h^c.charCodeAt(0),16777619);return(h>>>0).toString(16);}
function open(page='home'){
  copyButton.disabled=true;copyStatus.textContent='';
  conf=read();site=hash(JSON.stringify(conf));localStorage.setItem(`website-drafts.config.${site}`,JSON.stringify(conf));
  const loaded=frame.contentWindow.websiteDraftReview?.snapshot();
  const sameComposition=loaded?.site===site&&JSON.stringify(loaded.configuration)===JSON.stringify(conf);
  const url=previewUrl(page);frame.src=url;
  // Moving within an already open composition can be a hash-only navigation,
  // which does not emit the iframe's load event. Its snapshot remains usable.
  copyButton.disabled=!sameComposition;
  const anchor=document.createElement('a');anchor.href=url;anchor.target='_blank';anchor.rel='noopener';anchor.textContent='Open the composed shop in its own tab';document.querySelector('#shop-link').replaceChildren(anchor);
  document.querySelector('#status').textContent=`${globals[conf.global].name} · ${Object.values(conf.modules).join(' / ')}. Stable composition ${site}; its basket is remembered separately.`;
  localStorage.setItem('website-drafts.last-composition',JSON.stringify(conf));
}
frame.addEventListener('load',()=>{copyButton.disabled=!frame.contentWindow.websiteDraftReview;});
copyButton.addEventListener('click',async()=>{
  try{
    const loaded=frame.contentWindow.websiteDraftReview?.snapshot();
    if(!loaded)throw Error('The preview is still loading. Try again once it opens.');
    const controls=read(),unapplied=JSON.stringify(controls)!==JSON.stringify(loaded.configuration);
    const report={schema:'website-draft-review-v1',configuration:loaded.configuration,previewUrl:loaded.url,site:loaded.site,
      ...(unapplied?{unappliedControls:controls}:{})};
    const text=JSON.stringify(report,null,2),manual=document.querySelector('#manual-copy'),textarea=document.querySelector('#copy-config-text');
    textarea.value=text;manual.hidden=true;
    try{await navigator.clipboard.writeText(text);}
    catch{
      // Older/permission-limited browsers can still copy from the user click.
      manual.hidden=false;manual.open=true;textarea.focus();textarea.select();
      if(!document.execCommand('copy')){copyStatus.textContent='Automatic copying is unavailable. The open composition is selected below; press Ctrl+C.';return;}
      manual.hidden=true;copyButton.focus();
    }
    copyStatus.textContent=unapplied?'Copied the open composition and current page. Unapplied dropdown changes are included separately.':'Copied the open composition and current page.';
  }catch(error){copyStatus.textContent=error.message;}
});
form.addEventListener('submit',event=>{event.preventDefault();open();});
document.querySelector('#sample').addEventListener('click',()=>{const variations=read().variations;fill({...configuration(Number(form.elements.seed.value),form.elements.scale.value),variations});open();});
document.querySelectorAll('[data-huge]').forEach(button=>button.addEventListener('click',()=>{
  const value=read();value.scale='huge';
  for(const role of Object.keys(hugeUnits))value.modules[role]=button.dataset.huge;
  fill(value);open();
}));
document.querySelectorAll('[data-boutique]').forEach(button=>button.addEventListener('click',()=>{
  const value=read();value.scale='boutique';
  for(const role of Object.keys(boutiqueUnits))value.modules[role]=button.dataset.boutique;
  fill(value);open();
}));
document.querySelector('#empty').addEventListener('click',()=>{copyButton.disabled=true;localStorage.removeItem(`website-drafts.state.${site}`);frame.contentWindow.location.reload();document.querySelector('#status').textContent='This composition’s basket and remembered state were cleared.';});
document.querySelector('#load-example').addEventListener('click',()=>{
  open('cart');
  const ids=document.querySelector('#example').value==='arrival'?['cup','lamp']:['desk','ridge','trail'];
  const existing=JSON.parse(localStorage.getItem(`website-drafts.state.${site}`)||'null');
  const basket={version:2,cart:ids.map((id,i)=>({id:String(i+1),key:resolveProduct(id).variant.key,quantity:1})),selection:{},disclosures:{},address:{...initialAddress},remembered:{...initialAddress},coupon:'',split:false,deliveryChoices:{},orders:existing?.orders||[],revision:1,serial:ids.length,tab:'description',editing:null};
  localStorage.setItem(`website-drafts.state.${site}`,JSON.stringify(basket));
  frame.src=previewUrl('cart');
  document.querySelector('#status').textContent='Example basket loaded for this composition. Browse Cart or Checkout to inspect it.';
});
document.querySelectorAll('[data-page]').forEach(button=>button.addEventListener('click',()=>open(button.dataset.page)));
try{const previous=JSON.parse(localStorage.getItem('website-drafts.last-composition'));fill(previous?validateConfiguration(previous):conf);}catch{fill(configuration(41));}
const requested=new URLSearchParams(location.search),preset=requested.get('huge')||requested.get('boutique');
const presetPool=requested.has('huge')?hugeUnits:boutiqueUnits;
if(presetPool.home.some(([id])=>id===preset)) {
  const value=configuration(Number(requested.get('seed')||41),requested.has('huge')?'huge':'boutique');
  for(const role of Object.keys(presetPool))value.modules[role]=preset;
  value.global='concise';value.modules.cart='table';value.modules.checkout='steps';value.modules.info='directory';value.policy='footer';
  fill(value);
}else if(['typical','huge','boutique'].includes(requested.get('scale'))) {
  fill(configuration(Number(requested.get('seed')||41),requested.get('scale')));
}
open();
