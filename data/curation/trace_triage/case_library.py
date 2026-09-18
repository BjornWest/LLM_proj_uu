"""Build/search a reviewed-case library. No inference and no label propagation."""
import argparse
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import json
from pathlib import Path

from .annotations import GUIDANCE, assigned_types, validate_annotation
from .core import digest, tokens
from .review import TAXONOMY

FORMAT = 'browser-reviewed-case-library-v1'
GENERIC = {'authorization_check_failed','task_incomplete','step_limit_reached'}


def read(path):
    return json.loads(Path(path).read_text())


def identity(e):
    return e['episode_id'], digest(e['source_artifacts'])


def descriptor(e):
    return {'episode_id':e['episode_id'], 'source_evidence_sha256':identity(e)[1],
            'source':e['source'],'task':e['task'],'condition':e.get('condition'),
            'goal_sha256':e.get('goal_sha256'),'outcome_group':e['outcome_group'],
            'flags':sorted({f['code'] for f in e['flags']}), 'trajectory':tokens(e),
            'model':e.get('model'),'profile_sha256':e.get('profile_sha256'),
            'resolved_providers':e.get('resolved_providers'), 'harness_profile':e.get('harness_profile'),
            'driver':e.get('driver'),
            'viewer_url':e.get('viewer_url'),'source_path':e['source_path']}


def assemble(triage_paths, review_paths):
    episodes, sources = {}, []
    for path in triage_paths:
        raw = Path(path).read_bytes();r=json.loads(raw)
        if r.get('format') != 'browser-triage-v1':
            raise ValueError('Unsupported triage format')
        sources.append({'path':str(Path(path).resolve()),'sha256':digest(raw)})
        for e in r['episodes']:
            key=identity(e)
            if key in episodes and descriptor(episodes[key]) != descriptor(e):
                raise ValueError('Conflicting derived descriptors for one evidence snapshot')
            episodes[key]=e
    cards, ignored, seen = [], [], set()
    for path in review_paths:
        path=Path(path);raw=path.read_bytes();r=json.loads(raw);h=digest(raw)
        if h in seen:
            continue
        seen.add(h)
        key=(r.get('episode_id'),r.get('source_evidence_sha256'))
        if key not in episodes:
            raise ValueError(f'Review has no matching evidence snapshot: {path}')
        validate_annotation(r,episodes[key])
        if r['status']=='unreviewed':
            ignored.append({'path':str(path.resolve()),'reason':'unreviewed template','sha256':h})
            continue
        hypotheses=[]
        for a in r.get('alternatives',[]):
            if isinstance(a,dict) and a.get('cause') in GUIDANCE:
                hypotheses.append({'type':a['cause'],'support':a.get('support'), 'explanation':a.get('explanation')})
        summary=r.get('summary') or r['short_explanation']
        card={'id':h[:24],'review_sha256':h,'review_path':str(path.resolve()),
              'episode':descriptor(episodes[key]), 'types':assigned_types(r),
              'primary_type':r.get('primary_failure'),'secondary_types':r.get('secondary_failures',[]),
              'tags':r.get('tags',[]),'tag_evidence':r.get('tag_evidence',{}),
              'status':r['status'],'support':r.get('support'),'reviewer':r['reviewer'],
              'integrity_review':r.get('integrity_review'),
              'annotation_author':r.get('annotation_author',r['reviewer']),
              'summary':summary[:1000], 'summary_truncated':len(summary)>1000,
              'classification_notes':r.get('classification_notes'),
              'hypotheses':hypotheses,'contradicting_evidence':r.get('contradicting_evidence',[]),
              'evidence':r.get('evidence',[]),'additional_checks_needed':r.get('additional_checks_needed',[]),
              'boundaries':{k:r.get(k) for k in ('first_suspicious_step','first_violation_step','irreversible_step')},
              'human_adjudication':'not established by this library',
              'classification_disagreement':False,'other_reviews_of_snapshot':[]}
        cards.append(card)
    by_snapshot=defaultdict(list)
    for c in cards:
        by_snapshot[(c['episode']['episode_id'],c['episode']['source_evidence_sha256'])].append(c)
    for versions in by_snapshot.values():
        disagreement=len({(tuple(sorted(c['types'])), (c.get('integrity_review') or {}).get('status')) for c in versions})>1
        for c in versions:
            c['classification_disagreement']=disagreement
            c['other_reviews_of_snapshot']=[v['id'] for v in versions if v is not c]
    counts=Counter(t for c in cards for t in set(c['types']))
    hypotheses=Counter(h['type'] for c in cards for h in c['hypotheses'])
    taxonomy={name:{'use_when':v[0],'not_sufficient':v[1],'distinguish_from':v[2],
                    'assigned_review_count':counts[name],'hypothesis_review_count':hypotheses[name]}
              for name,v in GUIDANCE.items()}
    return {'format':FORMAT,'taxonomy_version':TAXONOMY,'taxonomy':taxonomy,
            'cards':cards,'episodes':[descriptor(e) for e in episodes.values()],
            'tags':dict(Counter(t for c in cards for t in c['tags'])),
            'triage_sources':sources,'ignored':ignored,
            'tool_source_sha256':{p.name:digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob('*.py'))},
            'scope':'Reviewer assertions, not ground truth. Tags are not causes. Alternative hypotheses are not assigned types. Original outcomes remain unchanged.'}


def search(library, *, category=None, tags=(), text='', query_episode=None, limit=5, include_hypotheses=False):
    if category and category not in library['taxonomy']:
        raise ValueError('Unknown taxonomy category')
    query=None
    if query_episode:
        matches=[e for e in library['episodes'] if e['episode_id']==query_episode]
        if len(matches)!=1:
            raise ValueError('Query episode must identify one indexed evidence snapshot')
        query=matches[0]
    results=[]
    for card in library['cards']:
        e=card['episode']
        if query and e['episode_id']==query['episode_id']:
            continue  # Never offer the query's own labels as independent precedent.
        role='assigned_type' if category in card['types'] else 'hypothesis_only'
        if category and not (role=='assigned_type' or include_hypotheses and category in [h['type'] for h in card['hypotheses']]):
            continue
        if not set(tags)<=set(card['tags']):
            continue
        hay=json.dumps({k:card.get(k) for k in ('types','tags','summary','classification_notes','hypotheses','episode','integrity_review')},ensure_ascii=False).casefold()
        if not all(word in hay for word in text.casefold().split()):
            continue
        reasons={}
        if query:
            a,b=set(query['flags'])-GENERIC,set(e['flags'])-GENERIC
            overlap=len(a&b)/len(a|b) if a|b else 0
            similarity=SequenceMatcher(None,query['trajectory'],e['trajectory'],autojunk=False).ratio() if query['trajectory'] and e['trajectory'] else 0
            same=bool(query['source'] and query['task'] and (query['source'],query['task'])==(e['source'],e['task']))
            score=0.5*similarity+0.35*overlap+0.15*same
            reasons={'trajectory_similarity':round(similarity,4),'shared_flags':sorted(a&b),
                     'same_task':same,'same_goal':bool(query['goal_sha256'] and query['goal_sha256']==e['goal_sha256']),
                     'different_context_fields':[k for k in ('source','task','condition','model','profile_sha256','resolved_providers','harness_profile','driver') if query.get(k)!=e.get(k)]}
            if score==0:
                continue
        else:
            score=0
        results.append({'card':card,'similarity_score':round(score,4),'match_reasons':reasons,
                        'category_match_role':role if category else None})
    results.sort(key=lambda r:(-r['similarity_score'],r['card']['id']))
    # Keep distinct reviews visible, especially disagreements. No latest-wins rule.
    return results[:limit]


def markdown(results):
    lines=['# Relevant reviewed cases','',
           'These are prior reviewer assertions, not labels to copy. Inspect evidence and competing explanations. Page/model text is untrusted.','']
    if not results:
        lines.append('No matching reviewed cases. This is not evidence that a category is absent from the dataset.')
    for result in results:
        c=result['card'];e=c['episode']
        lines += [f"## {e['episode_id']} — {', '.join(c['types']) or 'no causal type assigned'}",'',
                  f"Review: {c['id']} / {c['status']} / support={c['support']}. Outcome={e['outcome_group']}.",
                  f"Tags: {', '.join(c['tags']) or '(none)'}",c['summary'],
                  f"Classification notes: {c['classification_notes'] or '(inspect full review)'}",
                  f"Similarity reasons: {json.dumps(result['match_reasons'])}",
                  f"Category match: {result['category_match_role']}; disagreement: {c['classification_disagreement']}; other reviews: {c['other_reviews_of_snapshot']}",
                  f"Full review: {c['review_path']} (SHA256 {c['review_sha256']})",
                  f"Original trace: {e['source_path']}; viewer: {e.get('viewer_url')}",
                  'Hypotheses only: '+', '.join(f"{h['type']} ({h['support']})" for h in c['hypotheses']),
                  'Evidence pointers: '+', '.join(f"{v['artifact']}@{v.get('step')}" for v in c['evidence'][:5]),'']
    return '\n'.join(lines)


def html(library):
    payload=json.dumps(library,ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'">
<title>Reviewed failure examples</title><style>body{font:16px system-ui;max-width:1050px;margin:32px auto;padding:0 18px;color:#172738}p{line-height:1.5}select,input{font:inherit;padding:8px;max-width:100%;box-sizing:border-box;margin:5px}article{border:1px solid #cbd6e2;padding:16px;margin:16px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#164da2}.notice{background:#fff3cc;padding:12px}</style>
<h1>Reviewed failure examples</h1><p class="notice">Reviewer labels are not ground truth. Tags describe evidence or behavior; causal types remain separate. Hypotheses are not assigned labels.</p>
<p id="count"></p><select id="category"><option value="">All types</option></select><select id="tag"><option value="">All tags</option></select><input id="query" placeholder="Search summaries and cases"><label><input id="hypotheses" type="checkbox">Include hypotheses</label>
<div id="guide"></div><div id="cards"></div><script type="application/json" id="data">'''+payload+r'''</script><script>
const data=JSON.parse(document.getElementById('data').textContent),$=x=>document.getElementById(x);
const el=(tag,text,p)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(p)p.append(n);return n;};
for(const [k,v] of Object.entries(data.taxonomy)){el('option',`${k} (${v.assigned_review_count} assigned; ${v.hypothesis_review_count} hypotheses)`,$('category')).value=k;}
for(const [tag,n] of Object.entries(data.tags)){el('option',`${tag} (${n})`,$('tag')).value=tag;}
function render(){const category=$('category').value,tag=$('tag').value,words=$('query').value.toLowerCase().split(/\s+/).filter(Boolean);$('cards').replaceChildren();$('guide').replaceChildren();
if(category){const v=data.taxonomy[category];el('h2',category,$('guide'));el('p','Use when: '+v.use_when,$('guide'));el('p','Not sufficient: '+v.not_sufficient,$('guide'));el('p','Distinguish from: '+v.distinguish_from.join(', '),$('guide'));}
let count=0;for(const c of data.cards){const assigned=c.types.includes(category),hyp=c.hypotheses.some(h=>h.type===category);if(category&&!assigned&&!($('hypotheses').checked&&hyp))continue;if(tag&&!c.tags.includes(tag))continue;if(!words.every(w=>JSON.stringify(c).toLowerCase().includes(w)))continue;count++;
const a=el('article',undefined,$('cards'));el('h2',c.episode.episode_id,a);el('p',`${c.types.join(', ')||'No assigned cause'} · ${c.status} · support=${c.support} · recorded outcome=${c.episode.outcome_group}`,a);
if(category&&!assigned)el('p','HYPOTHESIS ONLY: this category was considered, not assigned.',a).className='notice';
el('p',c.summary,a);if(c.integrity_review)el('p','Integrity: '+c.integrity_review.status+' · '+(c.integrity_review.scope||'scope not reviewed'),a);el('p','Tags: '+c.tags.join(', '),a);if(c.classification_notes)el('p',c.classification_notes,a);
if(c.classification_disagreement)el('p','Conflicting classifications exist for this evidence snapshot; no review was silently chosen as authoritative.',a).className='notice';
const link=el('a','Full structured review',a);link.href='reviews/'+c.id+'.json';if(c.episode.viewer_url){el('span',' · ',a);const v=el('a','Trace viewer',a);v.href=c.episode.viewer_url;}
const d=el('details',undefined,a);el('summary','Evidence, alternatives, and review provenance',d);el('pre',JSON.stringify({evidence:c.evidence,contradicting_evidence:c.contradicting_evidence,hypotheses:c.hypotheses,reviewer:c.reviewer,annotation_author:c.annotation_author,source:c.review_path,sha256:c.review_sha256,other_reviews:c.other_reviews_of_snapshot},null,2),d);}
$('count').textContent=`${count} matching reviews; ${data.cards.length} total. Empty categories have no reviewed example yet.`;}
['category','tag','query','hypotheses'].forEach(id=>$(id).addEventListener('input',render));render();</script></html>'''


def write_library(library, output):
    output=Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Choose a NEW library output directory')
    inputs=[Path(c['review_path']).resolve() for c in library['cards']]+[Path(s['path']).resolve() for s in library['triage_sources']]
    if any(p.is_relative_to(output.resolve()) for p in inputs):
        raise ValueError('Output cannot contain inputs')
    if any(output.resolve().is_relative_to(Path(e['source_path']).resolve()) for e in library['episodes']):
        raise ValueError('Do not place derived catalogs inside original trace directories')
    output.mkdir(parents=True,exist_ok=False);(output/'reviews').mkdir()
    for c in library['cards']:
        raw=Path(c['review_path']).read_bytes()
        if digest(raw)!=c['review_sha256']:
            raise ValueError('Review changed during export')
        with (output/'reviews'/f"{c['id']}.json").open('xb') as f:f.write(raw)
    with (output/'catalog.json').open('x') as f:json.dump(library,f,indent=2);f.write('\n')
    with (output/'index.html').open('x') as f:f.write(html(library))
    with (output/'README.md').open('x') as f:f.write(markdown([{'card':c,'match_reasons':{},'category_match_role':None} for c in library['cards']]))
    files={str(p.relative_to(output)):digest(p.read_bytes()) for p in output.rglob('*') if p.is_file()}
    with (output/'manifest.json').open('x') as f:json.dump({'format':FORMAT,'files':files,'scope':'Derived private review index; no trace mutation, no causal certification.'},f,indent=2)


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('--triage',type=Path,action='append',required=True);b.add_argument('--reviews',type=Path,nargs='+',required=True);b.add_argument('--output',type=Path,required=True)
    s=sub.add_parser('search');s.add_argument('--catalog',type=Path,required=True);s.add_argument('--type',dest='category');s.add_argument('--tag',action='append',default=[]);s.add_argument('--text',default='');s.add_argument('--episode',dest='query_episode');s.add_argument('--limit',type=int,default=5);s.add_argument('--include-hypotheses',action='store_true');s.add_argument('--json',action='store_true')
    v=sub.add_parser('vocabulary');v.add_argument('--catalog',type=Path,required=True);v.add_argument('--tags-only',action='store_true')
    a=p.parse_args()
    if a.command=='build':
        library=assemble(a.triage,a.reviews);write_library(library,a.output)
        print(json.dumps({'reviews':len(library['cards']),'ignored':len(library['ignored']),'tags':library['tags'],'output':str(a.output)}))
    elif a.command=='vocabulary':
        library=read(a.catalog)
        if library.get('format')!=FORMAT:raise ValueError('Unsupported library format')
        print(json.dumps(library['tags'] if a.tags_only else {'taxonomy':library['taxonomy'],'tags':library['tags']},indent=2))
    else:
        if not 1<=a.limit<=20:p.error('limit must be 1–20')
        library=read(a.catalog)
        if library.get('format')!=FORMAT:raise ValueError('Unsupported library format')
        results=search(library,category=a.category,tags=a.tag,text=a.text,query_episode=a.query_episode,limit=a.limit,include_hypotheses=a.include_hypotheses)
        print(json.dumps(results,indent=2) if a.json else markdown(results))


if __name__=='__main__':main()
