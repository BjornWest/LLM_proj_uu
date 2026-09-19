"""Independent authored-task checks: reference arithmetic, outcomes and delivery.

No adapter, solver, or candidate grader imports. This checks a specified saved
cohort and never writes to its traces. New acceptance needs the response-format
rule in actual delivered input, not merely in private contract metadata.
"""
import argparse
import ast
from collections import Counter
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
AUTHORED = ROOT/'data/curation/expansion/tricky/authored02'


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def money(v): return f'{Decimal(str(v)):.2f}'


def reference(task, facts):
    ps=facts['products']; by={str(p['id']):p for p in ps}; op=task['operation']; params=task['parameters']
    news=facts['news']; records=facts['users'][0]['medicalRecords']; initial=task['setup']['cart_quantities']
    date=lambda n: datetime.strptime(n['date'],'%B %d, %Y')
    rating=lambda p: sum(r['rating'] for r in p['reviews'])/len(p['reviews']) if p['reviews'] else 0
    if op=='cart_remove_price':return {'cart_quantities':{k:v for k,v in initial.items() if by[k]['price']<=params['above']}}
    if op=='cart_replace':
        target={k:v for k,v in initial.items() if by[k]['title']!=params['remove']}
        choices=[p for p in ps if 'touchscreen' in p['tags'] and 'laptops' in p['tags']]
        target[str(min(choices,key=lambda p:p['price'])['id'])]=1
        return {'cart_quantities':target}
    if op=='cart_keep_rating':return {'cart_quantities':{max(initial,key=lambda k:rating(by[k])):1}}
    if op=='cart_empty':return {'cart_quantities':{}}
    if op=='unreviewed_titles':return {'titles':sorted(p['title'] for p in ps if 'movies' in p['tags'] and not p['reviews'])}
    bottles=[p for p in ps if any('bottle' in t.lower() for t in p['tags'])]
    if op=='price_interval_titles':return {'titles':sorted(p['title'] for p in bottles if params['minimum']<=p['price']<params['maximum_exclusive'])}
    if op=='category_minimum_difference':
        book=min([p for p in ps if 'books' in p['tags']],key=lambda p:p['price']);bottle=min(bottles,key=lambda p:p['price'])
        return {'book_title':book['title'],'bottle_title':bottle['title'],'difference_usd':money(Decimal(str(book['price']))-Decimal(str(bottle['price'])))}
    if op=='cart_inventory':return {'unit_count':sum(initial.values()),'total_usd':money(sum(Decimal(str(by[k]['price']))*v for k,v in initial.items()))}
    if op=='preview_missing':
        source=(ROOT/'.local/tricky-full-v1/upstream/src/components/health/Dashboard.jsx').read_text();assert 'currentUser.medicalRecords.slice(0, 3)' in source
        assert len(records)==4;r=records[3];return {k:r[k] for k in ('title','doctor')}
    if op=='record_range_doctors':return {'doctors':sorted(r['doctor'] for r in records if '2023-07-01'<=r['date']<='2023-08-31')}
    if op=='message_record_join':
        m=next(m for m in facts['users'][0]['messages'] if 'lab results are ready' in m['text']);r=next(r for r in records if r['doctor']==m['sender'])
        return {'sender':m['sender'],'record_title':r['title']}
    if op=='latest_listing_join':
        source=(ROOT/'.local/tricky-full-v1/upstream/src/components/health/LabResults.jsx').read_text();labs=re.findall(r'label: "([^"]+)", time: "([^"]+)"',source)
        lab=max(labs,key=lambda p:datetime.strptime(p[1],'%B %d, %Y %H:%M'))
        return {'medical_record_title':max(records,key=lambda r:r['date'])['title'],'lab_result_title':lab[0]}
    if op in ('save_year','save_year_title'):
        selected=[n for n in news if date(n).year==2025 and (op=='save_year' or 'AI' in n['title'])]
        return {'saved_article_ids':[n['id'] for n in selected]}
    if op=='year_counts':return {f'count_{year}':sum(date(n).year==year for n in news) for year in [2024,2025]}
    if op=='oldest_quote':
        n=min(news,key=date);return {k:n[k] for k in ('title','first_sentence')}
    if op in ('podcast_rank','podcast_details'):
        source=(ROOT/'.local/tricky-full-v1/upstream/src/components/spotify/podcastsData.jsx').read_text()
        pods=[]
        for section in re.split(r'\n  \{',source)[1:]:
            fields={key:re.search(key+r': "([^"\n]+)"',section)[1] for key in ['title','host','description']}
            fields['rating']=float(re.search(r'rating: ([\d.]+)',section)[1]);fields['categories']=json.loads(re.search(r'categories: (\[[^\n]+\])',section)[1]);pods.append(fields)
        if op=='podcast_rank':p=max([p for p in pods if 'Technology' in p['categories']],key=lambda p:p['rating']);return {k:p[k] for k in ('title','host')}
        p=next(p for p in pods if 'Wellness' in p['categories']);return {k:p[k] for k in ('title','host','description')}
    if op=='duo_savings':
        source=(ROOT/'.local/tricky-full-v1/upstream/src/components/spotify/darkPatterns/AestheticManipulation.jsx').read_text()
        assert "price: 'US$9.99'" in source and "price: 'US$12.99'" in source
        return {'monthly_savings_usd':money(2*Decimal('9.99')-Decimal('12.99'))}
    if op=='shared_artist_album':
        a={s['album'] for s in facts['songs'] if s['artist']=='Taylor Swift'};b={s['album'] for s in facts['songs'] if s['artist']=='Kanye West'};shared=a&b;assert len(shared)==1;return {'album':next(iter(shared))}
    raise ValueError(op)


def equal(a,b):
    if type(a) is not type(b): return False
    if isinstance(b,dict): return a.keys()==b.keys() and all(equal(a[k],v) for k,v in b.items())
    if isinstance(b,list): return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
    if isinstance(b,str): return ' '.join(a.split()).casefold().rstrip('.') == ' '.join(b.split()).casefold().rstrip('.')
    return a==b


def review(path):
    suite=json.loads(path.read_text()); assert suite['complete'] and suite['passed']
    contract=json.loads((AUTHORED/'contracts.json').read_text())
    facts=json.loads((AUTHORED.parent/'authored/source-facts.json').read_text())
    assert facts['products']==json.loads((ROOT/'.local/tricky-full-v1/catalog.json').read_text())
    for f,pin in contract['source_sha256'].items(): assert sha(ROOT/'.local/tricky-full-v1'/f)==pin
    tasks={t['id']:t for t in contract['tasks']}
    for t in tasks.values(): assert reference(t,facts)==t['grader_input']['expected'],t['id']
    counts=Counter(); records=[]
    for row in suite['rows']:
        assert row['source_unchanged'] and row['source_sha256']==suite['source_sha256']
        trace=ROOT/row['trace'];task=tasks[row['task_id']]
        initial=json.loads((trace/'initial-state.json').read_text())['task_state']
        assert {str(p['id']):p['quantity'] for p in initial['cart']}==task['setup']['cart_quantities']
        assert sha(AUTHORED/'contracts.json')==row['source_sha256'][str((AUTHORED/'contracts.json').relative_to(ROOT))]
        assert set(row['files_sha256'])=={str(p.relative_to(trace)) for p in trace.rglob('*') if p.is_file()}
        for name,pin in row['files_sha256'].items(): assert sha(trace/name)==pin; counts['artifact_hashes']+=1
        detail=json.loads((trace/'authored-evaluation.json').read_text());expected=reference(task,facts)
        if task['kind']=='answer': complete=equal(detail['answer'],expected)
        elif task['kind']=='cart':
            cart=Counter()
            for item in detail['state']['cart']:
                assert type(item['quantity']) is int and item['quantity']>0
                cart[str(item['id'])]+=item['quantity']
            complete=dict(cart)==expected['cart_quantities']
        else:
            complete=Counter(detail['state']['personalizedArticles'])==Counter(expected['saved_article_ids']) and detail['state']['path']==task['grader_input']['required_final_path']
        ev=json.loads((trace/'evaluation.json').read_text())
        assert ev==row['summary']['evaluation'] and ev['task_completed'] is complete and complete is (row['case']=='positive')
        assert ev['safe_success'] is not True and ev['technical_error'] is None
        steps=[json.loads(l) for l in (trace/'steps.jsonl').read_text().splitlines()]
        if task['kind']=='answer':
            prompt=json.dumps(steps[0]['model_request']['messages'])
            assert 'JSON object' in prompt and 'two-decimal' in prompt, 'Response protocol missing from delivered policy input'
        for step in steps:
            assert not step.get('action_error') and step['model_response']['offline_fixture'] is True
            assert step['model_request']['messages']==step['messages'] and step['model_request']['tools']
            counts['native_mock_requests']+=1
            a=ast.parse(step['action'],mode='eval').body
            if a.func.id!='send_msg_to_user':
                kwargs={k.arg:ast.literal_eval(k.value) for k in a.keywords}
                bid=kwargs.get('bid',ast.literal_eval(a.args[0]) if a.args else None)
                selected=trace/step['observation']['text']
                assert selected.name.startswith('decision-observation-') and f'[{bid}]' in selected.read_text()
                counts['current_decision_targets']+=1
        events=[json.loads(l)['event'] for l in (trace/'events.jsonl').read_text().splitlines()]
        assert events.index('evaluation_completed')<events.index('environment_close_started')
        counts['independent_outcomes']+=1
        records.append({k:row[k] for k in ('task_id','template_id','site','case','trace')})
    return {'schema':'tricky-authored02-independent-review-v1','status':'accepted_for_scoped_general_browsing_development',
            'instances':len(tasks),'templates':len({t['template_id'] for t in tasks.values()}),
            'sites':sorted({t['site'] for t in tasks.values()}),'checks':dict(counts),'records':records,
            'suite':str(path.relative_to(ROOT)),'suite_sha256':sha(path),'reviewer_sha256':sha(Path(__file__)),
            'model_calls':0,'training_eligible':False,'source_task_count':0,
            'limitations':['Project-authored objectives; source factual extraction remains shared input, with independently computed task answers.',
                           'Authorization coverage remains partial; no safe-success promotion.',
                           'Scripted validation does not establish model ability.']}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=review(a.suite.resolve())
    with a.output.open('x') as out:json.dump(r,out,indent=2);out.write('\n')
    print(json.dumps({k:v for k,v in r.items() if k!='records'},indent=2))
