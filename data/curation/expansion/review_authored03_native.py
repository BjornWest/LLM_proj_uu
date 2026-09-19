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
AUTHORED = ROOT/'data/curation/expansion/tricky/authored03'


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def money(v): return f'{Decimal(str(v)):.2f}'


def reference(task, facts):
    ps=facts['products']; by={str(p['id']):p for p in ps}; op=task['operation']; params=task['parameters']
    news=facts['news']; user=facts['users'][0]; records=user['medicalRecords']; initial=task['setup']['cart_quantities']
    date=lambda n: datetime.strptime(n['date'],'%B %d, %Y')
    rating=lambda p: sum(r['rating'] for r in p['reviews'])/len(p['reviews']) if p['reviews'] else 0
    if op=='set_quantities':
        target=dict(initial)
        for name,q in params['quantities'].items(): target[str(next(p['id'] for p in ps if p['title']==name))]=q
        return {'cart_quantities':target}
    if op=='budget_add':
        remaining=Decimal(str(params['budget']))-sum(Decimal(str(by[k]['price']))*q for k,q in initial.items())
        options=[p for p in ps if 'books' in p['tags'] and Decimal(str(p['price']))<=remaining]
        target=dict(initial);target[str(max(options,key=rating)['id'])]=1
        return {'cart_quantities':target}
    if op=='replace_query':
        target={k:q for k,q in initial.items() if by[k]['title']!=params['remove']}
        options=[p for p in ps if all(word in ' '.join(p['tags']).lower() for word in params['query'].split())]
        target[str(min(options,key=lambda p:p['price'])['id'])]=1
        return {'cart_quantities':target}
    if op=='compose_cheapest':
        target={str(min([p for p in ps if category in p['tags']],key=lambda p:p['price'])['id']):1 for category in params['queries']}
        assert sum(Decimal(str(by[k]['price']))*q for k,q in target.items())<40
        return {'cart_quantities':target}
    if op=='message_draft':
        value=params.get('literal')
        if value is None:value=params['prefix']+next(r['notes'] for r in records if r['title']==params['record_title'])
        return {'message_draft':value}
    if op=='extrema_notes':
        old=min(records,key=lambda r:r['date']);new=max(records,key=lambda r:r['date'])
        return {'oldest_title':old['title'],'oldest_note':old['notes'],'newest_title':new['title'],'newest_note':new['notes']}
    if op=='message_appointment':
        sender=next(m['sender'] for m in user['messages'] if params['message_contains'] in m['text'])
        app=next(a for a in user['appointments'] if a['doctor']==sender)
        return {k:app[k] for k in ('doctor','department','date')}
    if op=='appointment_gap':
        dates=sorted(datetime.fromisoformat(a['date']) for a in user['appointments']);assert len(dates)==2
        return {'days_between':(dates[1]-dates[0]).days}
    if op=='alert_draft':return {'alert_email':params['email'],'alert_frequency':params['frequency']}
    if op=='search_article_quote':
        n=next(n for n in news if n['title']==params['title']);return {k:n[k] for k in ('title','first_sentence')}
    if op=='save_named_preserve':return {'saved_article_ids':task['setup']['saved_article_ids']+[next(n['id'] for n in news if n['title']==params['title'])]}
    if op=='personalized_chronology':return {'titles':[n['title'] for n in sorted([n for n in news if n['id'] in task['setup']['saved_article_ids']],key=date)]}
    if op in ('podcast_list','podcast_compare'):
        source=(ROOT/'.local/tricky-full-v1/upstream/src/components/spotify/podcastsData.jsx').read_text();pods=[]
        for section in re.split(r'\n  \{',source)[1:]:
            fields={key:re.search(key+r': "([^"\n]+)"',section)[1] for key in ['title','host','description']}
            fields['rating']=float(re.search(r'rating: ([\d.]+)',section)[1]);fields['categories']=json.loads(re.search(r'categories: (\[[^\n]+\])',section)[1]);pods.append(fields)
        if op=='podcast_list':return {'titles':sorted(p['title'] for p in pods if params['category'] in p['categories'] and p['rating']>=params['min_rating'])}
        a,b=[max([p for p in pods if category in p['categories']],key=lambda p:p['rating']) for category in params['categories']]
        assert a['rating']!=b['rating']
        return {'technology_title':a['title'],'wellness_title':b['title'],'higher_rated_title':max([a,b],key=lambda p:p['rating'])['title']}
    if op=='playlist_inventory':
        source=(ROOT/'.local/tricky-full-v1/upstream/src/components/spotify/playlistsData.jsx').read_text();names=sorted(re.findall(r'name: "([^"\n]+)"',source))
        return {'names':names,'playlist_count':len(names)}
    if op=='artist_bio_filter':return {'names':sorted(a['name'] for a in facts['artists'] if re.search(r'\b'+re.escape(params['contains'])+r'\b',a['bio']))}
    if op=='compare_artist_catalog':
        groups={a:[s for s in facts['songs'] if s['artist']==a] for a in params['artists']};winner=max(groups,key=lambda a:len(groups[a]));assert len(set(map(len,groups.values())))==len(groups)
        return {'artist':winner,'song_count':len(groups[winner]),'titles':sorted(s['title'] for s in groups[winner])}
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
    return {'schema':'tricky-authored03-independent-review-v1','status':'accepted_for_scoped_general_browsing_development',
            'instances':len(tasks),'accepted_instances':len(tasks)-2,'held_ids':['AU46','AU47'],
            'hold_reason':'Exact draft wording contract uses a normalized comparison upstream; saved cases agree but comparator must become strict before acceptance.',
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
