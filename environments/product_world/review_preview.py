"""Write a human authoring preview of an existing frozen review corpus; no resampling."""
from html import escape
import json
from pathlib import Path

from environments.product_review_sites.evidence import validate_evidence,ASPECTS,PRIMARY
from environments.shopping_intent.review_evidence import summarize
from .product_review_tasks import sample_count_task
from .scenario import sample_task


def write_preview(world,export,directory):
    validate_evidence(world,export)
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    public=export['public'];products={p['product_id']:p for p in world['public']['products']}
    by_sku={}
    for r in public['reviews']:by_sku.setdefault(r['subject']['id'],[]).append(r)
    groups=[]
    for sku,reports in by_sku.items():
        p=products[sku];family=p['category']
        task=sample_task(seed=0,family=family,requirements=1,hidden='none',memory='episodic',world_preferences='none',cookie_preferences='none',product_review_preferences='majority')
        preference=' '.join(m['text'] for m in task['public']['memories']['episodes'])
        count_task=sample_count_task(world,sku_id=sku,aspect_id=PRIMARY[family])
        rows=[]
        for aspect,spec in ASPECTS.items():
            if family not in spec['families']:continue
            complete=any(c=={'sku_id':sku,'aspect_id':aspect,'context_id':spec['context'],'status':'complete'} for c in public['coverage'])
            summary=summarize(reports,sku_id=sku,aspect_id=aspect,context_id=spec['context'],complete=complete)
            counts=summary['review_counts']
            majority='Unknown' if summary['majority_positive'] is None else 'Yes' if summary['majority_positive'] else 'No'
            rows.append('<tr><th>'+escape(spec['label'])+'</th>'+''.join('<td>'+str(counts[s])+'</td>' for s in ('positive','negative','mixed','neutral','not_assessed'))+'<td>'+str(summary['positive_reviewer_count'])+'/'+str(summary['contextual_reviewer_count'])+' · '+majority+'</td></tr>')
        cards=[]
        for r in reports:
            usage=r['usage_reports'][0]['experience_kind'].replace('_',' ')
            stars='Not rated' if r['stars'] is None else str(r['stars'])+'/5'
            metadata=r['handle']+' · '+r['published_date']+' · '+stars
            if r.get('template_version',1)<3:metadata+=' · '+usage
            claims={k:r[k] for k in ('review_id','reviewer_id','subject','usage_reports','assessments','mentioned_attributes','template_choices')}
            if 'sensory_observations' in r:claims['sensory_observations']=r['sensory_observations']
            cards.append('<article class="review"><div class="meta">'+escape(metadata)+'</div><p>'+escape(r['body'])+'</p><details><summary>Structured source and template choices</summary><pre>'+escape(json.dumps(claims,indent=2,ensure_ascii=False))+'</pre></details></article>')
        groups.append('<section class="product" data-family="'+escape(family)+'" id="'+escape(sku)+'"><h2>'+escape(p['name'])+'</h2><div class="meta">'+escape(sku)+'</div><div class="tasks"><div><h3>Shopping request + saved memory</h3><p>'+escape(task['public']['user_message'])+'</p><p class="memory">'+escape(preference)+'</p></div><div><h3>Count-task variation</h3><p>'+escape(count_task['public']['user_message'])+'</p></div></div><details><summary>Authoring reference: published first-hand reports</summary><div class="scroll"><table><thead><tr><th>Claim</th><th>Positive</th><th>Negative</th><th>Mixed</th><th>Neutral</th><th>Unassessed</th><th>Majority of users</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div><p>Positive supports the named claim, including complaints. Intention and hearsay are excluded. Absence is not a negative claim.</p></details><div class="reviews">'+''.join(cards)+'</div></section>')
    families=sorted({products[sku]['category'] for sku in by_sku})
    options=''.join('<option value="'+f+'">'+escape(f.replace('_',' ').title())+'</option>' for f in families)
    html='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Product review workshop</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f3f2ed;color:#203530;font:16px/1.6 system-ui}header{padding:36px max(24px,5vw);background:#173e35;color:white}header p{max-width:900px}main{max-width:1350px;margin:auto;padding:24px}h1,h2{line-height:1.25}h1{font-size:36px;margin:0}h2{font-size:25px}h3{font-size:17px}.toolbar{position:sticky;top:0;background:#f3f2ed;padding:14px 0;z-index:1;display:flex;gap:24px;flex-wrap:wrap}.toolbar label{min-width:0;max-width:100%;display:grid}select{min-width:0;padding:10px;font:inherit;max-width:100%}.product{background:white;padding:24px;border:1px solid #d7ded8;border-radius:12px;margin:24px 0}.meta{color:#526960;font-size:13px;overflow-wrap:anywhere}.tasks{display:grid;grid-template-columns:1fr 1fr;gap:24px;border-block:1px solid #e2e6df;margin:20px 0;padding:16px 0}.memory{border-left:4px solid #bd8641;padding-left:14px}.reviews{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:16px;margin-top:24px}.review{padding:18px;background:#f7f8f4;border:1px solid #dfe4db;border-radius:8px}.review p{font-size:15px}details{margin-top:12px}summary{cursor:pointer;color:#316353}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:8px;border-bottom:1px solid #d8dfd6}.scroll{overflow:auto}[hidden]{display:none!important}@media(max-width:700px){.tasks{grid-template-columns:1fr}main{padding:12px}.product{padding:16px}}</style>
<header><h1>Product review workshop</h1><p>Authoring preview · reusable templates with catalog facts, personal experiences and structured claims. Each record concerns one exact product option. These are newly generated opinions, separate from the existing review-site snapshots.</p></header><main><div class="toolbar"><label>Family <select id="family">'''+options+'''</select></label><label>Product <select id="product"></select></label></div>'''+''.join(groups)+'''<footer><p>Reference counts are for author inspection. They are not added to shopping prompts. One frozen corpus; no task-conditioned opinions or resampling.</p></footer></main>
<script>const family=document.querySelector('#family'),product=document.querySelector('#product'),sections=[...document.querySelectorAll('.product')];function show(){sections.forEach(s=>s.hidden=s.id!==product.value)}function populate(){product.replaceChildren();sections.filter(s=>s.dataset.family===family.value).forEach(s=>{const o=document.createElement('option');o.value=s.id;o.textContent=s.querySelector('h2').textContent;product.append(o)});show()}family.addEventListener('change',populate);product.addEventListener('change',show);populate();</script></html>'''
    (root/'index.html').write_text(html)
    return root/'index.html'
