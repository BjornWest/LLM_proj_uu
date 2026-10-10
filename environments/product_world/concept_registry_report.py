"""Standalone, offline-capable HTML explorer for the proposed concept registry."""
from __future__ import annotations

import html
import json
from typing import Any


def render_html(rows: list[dict[str, Any]], counting_policy: str) -> str:
    # Prevent authored names/notes from ending the data script; DOM content uses textContent.
    payload = json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return TEMPLATE.replace('__POLICY__', html.escape(counting_policy)).replace('__ROWS__', payload)


TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Product concept registry — dimensions and modules</title>
<style>
:root{color-scheme:light;--ink:#203149;--muted:#56677e;--line:#d7e0eb;--blue:#215b9c}*{box-sizing:border-box}
body{margin:0;background:#f3f6fa;color:var(--ink);font:16px/1.5 system-ui,sans-serif}main{max-width:1520px;margin:auto;padding:32px}
h1{font-size:2rem;margin:8px 0}h2{font-size:1.4rem}p{max-width:1050px}.eyebrow{color:var(--blue);font-size:.85rem;font-weight:700;letter-spacing:.08em}
.note,.panel{background:white;border:1px solid var(--line);border-radius:10px;padding:20px;margin:20px 0}.note{border-left:4px solid #ce9c3b}
.controls{display:grid;grid-template-columns:2fr repeat(4,1fr);gap:12px}.controls label{font-size:.86rem;font-weight:650}
input,select,button{font:inherit;border:1px solid #a8b7ca;background:white;border-radius:5px;padding:9px;color:inherit}input,select{width:100%;margin-top:5px}button{cursor:pointer}button:hover{background:#edf3fa}
.stats{display:flex;gap:14px;flex-wrap:wrap;margin:20px 0}.stat{background:#e6eff9;border-radius:8px;padding:12px 20px;min-width:145px}.stat strong{display:block;font-size:1.6rem}.stat span{font-size:.86rem;color:var(--muted)}
.table-scroll{overflow:auto;max-width:100%;border:1px solid var(--line);border-radius:7px;background:white}table{width:100%;border-collapse:collapse;font-size:.91rem;min-width:1000px}th,td{text-align:left;padding:12px;border-bottom:1px solid var(--line);vertical-align:top}th{background:#eaf0f8;white-space:nowrap}tbody tr:nth-child(even){background:#f8fafd}small{display:block;color:var(--muted)}.num{font-variant-numeric:tabular-nums;font-weight:650}.pill{display:inline-block;padding:2px 7px;margin:2px;background:#eaf0f8;border-radius:4px;font-size:.77rem}summary{cursor:pointer;color:var(--blue);font-weight:650}.dimension-row td{padding:18px;background:#edf3fa}.dimension-row table{font-size:.86rem}.dimension-row p{margin:8px 0}code{overflow-wrap:anywhere}td:first-child{min-width:140px}.toolbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.legend{color:var(--muted);font-size:.92rem}[hidden]{display:none!important}
@media(max-width:800px){main{padding:16px}.controls{grid-template-columns:1fr 1fr}.controls label:first-child{grid-column:1/-1}h1{font-size:1.6rem}.panel{padding:14px}.stat{min-width:120px;flex:1}}
</style></head><body><main>
<div class="eyebrow">PRODUCT DESIGN · QUERYABLE PROPOSAL</div><h1>Concepts, modules and variance dimensions</h1>
<p>Explore every planned concept. Expand a row to inspect its named dimensions, identity level and conditional applicability. Module assignments follow those dimensions, so manual toothbrushes do not inherit electric-brush features.</p>
<div class="note"><strong>These are proposed field counts, not live generator capabilities or independent sampling axes.</strong><p>__POLICY__</p><p>A module is a reusable feature group. “SKU candidates” includes definite SKU fields and unresolved model-or-SKU fields; no valid option grid is implied. Domains and distributions remain unfilled. A structured camera system counts as one field, so counts indicate specification breadth rather than possible-product counts or implementation effort.</p></div>
<section class="panel" aria-label="Filters"><div class="controls">
<label>Search concepts and dimensions<input type="search" id="search" placeholder="Try sandals, F56, battery…"></label>
<label>Family<select id="family"><option value="">All families</option></select></label>
<label>Store scope<select id="store"><option value="">All store scopes</option></select></label>
<label>Module<select id="module"><option value="">All modules</option></select></label>
<label>Sort<select id="sort"><option value="dimension_count:asc">Fewest dimensions</option><option value="dimension_count:desc">Most dimensions</option><option value="module_count:asc">Fewest modules</option><option value="module_count:desc">Most modules</option><option value="sku_candidate_count:desc">Most SKU candidates</option><option value="label:asc">Concept name</option><option value="family_id:asc">Family</option></select></label>
</div><div class="stats" aria-live="polite" id="stats"></div><div class="toolbar"><button id="reset">Reset filters</button><button id="export-json">Download matching JSON</button><button id="export-csv">Download matching CSV</button><span class="legend" id="count"></span></div></section>
<details class="panel" id="family-overview"><summary>Family overview — counts across matching concepts</summary><p class="legend">Min/max ranges reflect the currently matching concepts, not necessarily the whole family.</p><div class="table-scroll"><table><thead><tr><th>Family</th><th>Concepts</th><th>Modules min–max</th><th>Dimensions min–max</th><th>Mean dimensions</th></tr></thead><tbody id="families"></tbody></table></div></details>
<h2>All matching concepts</h2><p class="legend">Total dimensions = unconditional + conditional. Fixed concept traits are shown in the expanded detail and excluded from counts. “Model or SKU” choices still need an identity decision.</p>
<div class="table-scroll"><table id="concepts"><thead><tr><th>Family</th><th>Concept</th><th>Modules</th><th>Total dimensions</th><th>Conditional</th><th>Model only</th><th>SKU candidates</th><th>Inspect</th></tr></thead><tbody id="concept-body"></tbody></table></div>
<p class="legend">The JSON registry is an authoring scaffold. Completing a field's placeholders does not automatically implement it in catalog generation, retail pages, reviews or grading.</p>
</main><script type="application/json" id="data">__ROWS__</script><script>
'use strict';
const all=JSON.parse(document.querySelector('#data').textContent);let matching=[];
const el=id=>document.getElementById(id);
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function options(id,pairs){for(const [value,label] of pairs.sort((a,b)=>a[1].localeCompare(b[1]))){const o=node('option',label);o.value=value;el(id).append(o);}}
options('family',[...new Map(all.map(r=>[r.family_id,r.review_id+' · '+r.family_label])).entries()]);
options('store',[...new Set(all.flatMap(r=>r.store_type_ids))].map(x=>[x,x.replaceAll('_',' ')]));
options('module',[...new Set(all.flatMap(r=>r.module_ids))].map(x=>[x,x]));
function cell(row,text,cls){const c=node('td',text,cls);row.append(c);return c;}
function detail(r){const wrap=node('div');wrap.append(node('p','Stable ID: '+r.id));wrap.append(node('p','Family exceptions: '+r.family_notes));wrap.append(node('p','Specification status: '+Object.entries(r.specification_status).map(([k,v])=>k.replaceAll('_',' ')+': '+v).join(' · ')));
if(Object.keys(r.fixed_traits).length)wrap.append(node('p','Fixed traits (not counted): '+JSON.stringify(r.fixed_traits)));
if(r.notes.length)wrap.append(node('p',r.notes.join(' ')));
const table=node('table');const head=node('thead'),hr=node('tr');for(const s of ['Dimension','Module','Identity level','Type / unit','Applicability','Domain / sampling'])hr.append(node('th',s));head.append(hr);table.append(head);const body=node('tbody');
for(const d of r.dimensions){const row=node('tr');const first=cell(row,d.label);first.append(node('small',d.id+(d.inherited?' · inherited':' · concept-specific')));cell(row,d.module_id);cell(row,d.identity_level.replaceAll('_',' '));cell(row,d.value_kind+(d.unit?' · '+d.unit:''));cell(row,d.condition||'Unconditional candidate');cell(row,(d.value_domain===null?'Domain pending':'Domain drafted')+' / '+(d.sampling===null?'sampling pending':'sampling drafted'));body.append(row);}table.append(body);wrap.append(table);return wrap;}
function draw(){const q=el('search').value.trim().toLowerCase();matching=all.filter(r=>(!el('family').value||r.family_id===el('family').value)&&(!el('store').value||r.store_type_ids.includes(el('store').value))&&(!el('module').value||r.module_ids.includes(el('module').value))&&(!q||[r.id,r.label,r.family_label,r.review_id,...r.module_ids,...r.dimensions.flatMap(d=>[d.id,d.label,d.condition||''])].join(' ').toLowerCase().includes(q)));
const [key,order]=el('sort').value.split(':');matching.sort((a,b)=>{const x=typeof a[key]==='number'?a[key]-b[key]:a[key].localeCompare(b[key]);return (order==='desc'?-x:x)||a.id.localeCompare(b.id);});
el('count').textContent=matching.length+' of '+all.length+' concepts shown';el('stats').replaceChildren();const vals=matching.map(r=>r.dimension_count);for(const [v,t] of [[matching.length,'concepts'],[new Set(matching.map(r=>r.family_id)).size,'families'],[vals.length?Math.min(...vals):'—','fewest dimensions'],[vals.length?Math.max(...vals):'—','most dimensions']]){const s=node('div',undefined,'stat');s.append(node('strong',String(v)),node('span',t));el('stats').append(s);}
const groups=new Map();for(const r of matching){if(!groups.has(r.family_id))groups.set(r.family_id,[]);groups.get(r.family_id).push(r);}el('families').replaceChildren();for(const [id,rs] of [...groups].sort((a,b)=>a[0].localeCompare(b[0]))){const tr=node('tr');cell(tr,rs[0].review_id+' · '+rs[0].family_label);cell(tr,String(rs.length));for(const key of ['module_count','dimension_count']){const vs=rs.map(r=>r[key]);cell(tr,Math.min(...vs)+'–'+Math.max(...vs));}cell(tr,(rs.reduce((s,r)=>s+r.dimension_count,0)/rs.length).toFixed(2));el('families').append(tr);}
el('concept-body').replaceChildren();let idx=0;for(const r of matching){const tr=node('tr');tr.dataset.concept=r.id;cell(tr,r.review_id+' · '+r.family_label);cell(tr,r.label);const mods=cell(tr,String(r.module_count),'num');mods.append(node('small',r.module_ids.join(', ')));for(const key of ['dimension_count','conditional_dimension_count','model_dimension_count','sku_candidate_count'])cell(tr,String(r[key]),'num');const tc=cell(tr);const btn=node('button','Dimensions');btn.setAttribute('aria-expanded','false');const dr=node('tr',undefined,'dimension-row');dr.hidden=true;dr.id='detail-'+idx++;btn.setAttribute('aria-controls',dr.id);const dc=cell(dr);dc.colSpan=8;let loaded=false;btn.addEventListener('click',()=>{dr.hidden=!dr.hidden;btn.setAttribute('aria-expanded',String(!dr.hidden));if(!loaded){dc.append(detail(r));loaded=true;}});tc.append(btn);el('concept-body').append(tr,dr);}}
for(const id of ['family','store','module','sort'])el(id).addEventListener('change',draw);el('search').addEventListener('input',draw);el('reset').addEventListener('click',()=>{for(const id of ['family','store','module','search'])el(id).value='';el('sort').value='dimension_count:asc';draw();});
function download(name,body,type){const u=URL.createObjectURL(new Blob([body],{type}));const a=node('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}
el('export-json').addEventListener('click',()=>download('product-concepts.json',JSON.stringify(matching,null,2),'application/json'));
el('export-csv').addEventListener('click',()=>{const keys=['id','family_id','label','module_count','dimension_count','conditional_dimension_count','model_dimension_count','sku_dimension_count','model_or_sku_dimension_count','sku_candidate_count'];const quote=v=>'"'+String(v).replaceAll('"','""')+'"';download('product-concepts.csv',[keys.join(','),...matching.map(r=>keys.map(k=>quote(r[k])).join(','))].join('\n'),'text/csv');});draw();
</script></body></html>'''
