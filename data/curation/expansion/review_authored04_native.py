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
AUTHORED = ROOT/'data/curation/expansion/tricky/authored04'


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def money(v): return f'{Decimal(str(v)):.2f}'


def reference(task,facts):
    ps=facts['products'];by={str(p['id']):p for p in ps};op=task['operation'];params=task['parameters']
    user=facts['users'][0];records=user['medicalRecords'];news=facts['news'];initial=task['setup']['cart_quantities']
    date=lambda n:datetime.strptime(n['date'],'%B %d, %Y')
    rating=lambda p:sum(r['rating'] for r in p['reviews'])/len(p['reviews']) if p['reviews'] else 0
    if op=='description_match':
        matches=[p for p in ps if p['title'] in params['titles'] and params['contains'] in p['description']];assert len(matches)==1
        return {k:matches[0][k] for k in ('title','description')}
    if op=='review_star_counts':return {key:sum(r['rating']==params['rating'] for r in next(p for p in ps if p['title']==title)['reviews']) for key,title in zip(params['keys'],params['titles'])}
    if op=='compose_ranked':
        target={}
        for spec in params['selections']:
            candidates=[p for p in ps if all(w in ' '.join(p['tags']).lower() for w in spec['query'].split())]
            best=min(candidates,key=lambda p:p['price']) if spec['rank']=='price_min' else max(candidates,key=rating)
            target[str(best['id'])]=1
        assert sum(Decimal(str(by[k]['price']))*q for k,q in target.items())<40
        return {'cart_quantities':target}
    if op=='budget_quantity':
        key=next(k for k in initial if by[k]['title']==params['title']);others=sum(Decimal(str(by[k]['price']))*q for k,q in initial.items() if k!=key)
        quantity=int((Decimal(str(params['budget']))-others)//Decimal(str(by[key]['price'])))
        assert 0<quantity<=initial[key]
        return {'cart_quantities':{**initial,key:quantity}}
    if op=='remove_largest_subtotal':
        values={k:Decimal(str(by[k]['price']))*q for k,q in initial.items()};largest=max(values,key=values.get)
        assert sum(v==values[largest] for v in values.values())==1
        return {'cart_quantities':{k:q for k,q in initial.items() if k!=largest}}
    if op=='record_lab_gap':
        source=(ROOT/'.local/tricky-full-v1/upstream/src/components/health/LabResults.jsx').read_text();labs=re.findall(r'label: "([^"]+)", time: "([^"]+)"',source)
        lab=next(v for title,v in labs if title==params['title']);record=next(r for r in records if r['title']==params['title'])
        return {'days_later':(datetime.strptime(lab,'%B %d, %Y %H:%M').date()-datetime.fromisoformat(record['date']).date()).days}
    if op=='message_quote':
        m=next(m for m in user['messages'] if params['contains'] in m['text']);return {'sender':m['sender'],'message':m['text']}
    if op=='latest_record_draft':
        r=max(records,key=lambda r:r['date']);return {'message_draft':'Question about '+r['title']+': '+r['notes']}
    if op=='appointment_record_join':return {'appointment_doctor':min(user['appointments'],key=lambda a:a['date'])['doctor'],'record_doctor':max(records,key=lambda r:r['date'])['doctor']}
    if op=='record_note_filter':return {'titles':[r['title'] for r in sorted(records,key=lambda r:r['date']) if re.search(r'\b'+re.escape(params['word'])+r'\b',r['notes'],re.I)]}
    if op=='date_range_titles':return {'titles':[n['title'] for n in sorted(news,key=date) if params['start']<=date(n).date().isoformat()<=params['end']]}
    if op=='article_date_gap':
        dates=[date(next(n for n in news if n['title']==t)) for t in params['titles']];return {'days_between':abs((dates[0]-dates[1]).days)}
    if op=='article_numeric_facts':
        text=next(n['first_sentence'] for n in news if n['title']==params['title']);assert 'over the next decade' in text
        return {'reduction_percent':int(re.search(r'(\d+)%',text)[1]),'horizon_years':10}
    if op=='save_article_titles':return {'saved_article_ids':task['setup']['saved_article_ids']+[next(n['id'] for n in news if n['title']==title) for title in params['titles']]}
    if op=='article_content_match':
        matches=[n for n in news if n['title'] in params['titles'] and params['contains'] in n['first_sentence']];assert len(matches)==1
        return {k:matches[0][k] for k in ('title','first_sentence')}
    if op=='shared_artist_album':
        artist_ids={a['name']:a['id'] for a in facts['artists']}
        common=set.intersection(*[{s['album'] for s in facts['songs'] if s['artistId']==artist_ids[artist]} for artist in params['artists']]);assert len(common)==1;return {'album':next(iter(common))}
    if op in ('plan_capacity','family_savings'):
        source=(ROOT/'.local/tricky-full-v1/upstream/src/components/spotify/darkPatterns/AestheticManipulation.jsx').read_text()
        prices=dict(re.findall(r"title: '([^']+)',\s+price: 'US\$([\d.]+)'",source))
        assert 'one account' in source and 'two people' in source and 'Up to 6 premium accounts' in source
        if op=='plan_capacity':assert params['minimum_accounts']==3;return {'plan':'Spotify Premium Family','monthly_usd':prices['Spotify Premium Family'],'account_limit':6}
        return {'monthly_savings_usd':money(2*Decimal(prices['Spotify Premium Duo'])-Decimal(prices['Spotify Premium Family']))}
    if op=='podcast_category_intersection':
        source=(ROOT/'.local/tricky-full-v1/upstream/src/components/spotify/podcastsData.jsx').read_text();hosts=[]
        for section in re.split(r'\n  \{',source)[1:]:
            categories=json.loads(re.search(r'categories: (\[[^\n]+\])',section)[1])
            if set(params['categories'])<=set(categories):hosts.append(re.search(r'host: "([^"]+)"',section)[1])
        return {'hosts':sorted(hosts),'podcast_count':len(hosts)}
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
        elif task['kind']=='draft':
            complete=all(detail['state']['form_fields'].get(k)==v for k,v in expected.items()) and detail['state']['path']==task['grader_input']['required_final_path']
        elif task['kind']=='cart':
            cart=Counter()
            for item in detail['state']['cart']:
                assert type(item['quantity']) is int and item['quantity']>0
                cart[str(item['id'])]+=item['quantity']
            complete=dict(cart)==expected['cart_quantities']
        else:
            complete=Counter(detail['state']['personalizedArticles'])==Counter(expected['saved_article_ids']) and detail['state']['path']==task['grader_input']['required_final_path']
        if task['grader_input']['required_final_path']: complete=complete and detail['state']['path']==task['grader_input']['required_final_path']
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
    return {'schema':'tricky-authored04-independent-review-v1','status':'accepted_for_scoped_general_browsing_development',
            'instances':len(tasks),'accepted_instances':len(tasks),'held_ids':[],
            'templates':len({t['template_id'] for t in tasks.values()}),
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
