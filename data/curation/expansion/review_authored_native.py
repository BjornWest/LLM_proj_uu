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
AUTHORED = ROOT/'data/curation/expansion/tricky/authored'


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def money(v): return f'{Decimal(str(v)):.2f}'


def reference(task, facts):
    params, op = task['parameters'], task['operation']
    products = facts['products']
    def select(spec):
        query = spec.get('query', '').lower()
        rows = [p for p in products if query in p['title'].lower()
                or all(any(w in tag.lower() for tag in p['tags']) for w in query.split())
                or all(w in p['title'].lower() for w in query.split())]
        if 'named' in spec: rows = [p for p in products if p['title'] == spec['named']]
        rating = lambda p: sum(Decimal(r['rating']) for r in p['reviews']) / len(p['reviews']) if p['reviews'] else Decimal(0)
        if 'min_rating' in spec: rows = [p for p in rows if rating(p) >= spec['min_rating']]
        if 'max_price_exclusive' in spec: rows = [p for p in rows if p['price'] < spec['max_price_exclusive']]
        if spec.get('rank') == 'rating_max': return max(rows, key=rating)
        if spec.get('rank') == 'price_min': return min(rows, key=lambda p: p['price'])
        assert len(rows) == 1
        return rows[0]
    records = facts['users'][0]['medicalRecords']
    news = facts['news']
    date = lambda n: datetime.strptime(n['date'], '%B %d, %Y')
    if op == 'price_difference':
        prices = [Decimal(str(select({'named': title})['price'])) for title in params['titles']]
        return {'difference_usd': money(prices[1]-prices[0])}
    if op == 'compose_cart':
        counts = Counter(str(select(s)['id']) for s in params['selections'])
        return {'cart_quantities': dict(counts)}
    if op == 'compare_reviews':
        p = max([select({'named': t}) for t in params['titles']], key=lambda p: len(p['reviews']))
        return {'title': p['title'], 'review_count': len(p['reviews'])}
    if op == 'filter_lookup':
        p = select(params)
        return {'title': p['title'], 'price_usd': money(p['price'])}
    if op == 'sum_ranked':
        return {'total_usd': money(sum(Decimal(str(select(s)['price'])) for s in params['selections']))}
    if op == 'record_fields':
        r = next(r for r in records if r['title'] == params['title'])
        return {k: r[k] for k in ('doctor', 'date')}
    if op == 'latest_record':
        r = max(records, key=lambda r: r['date'])
        return {k: r[k] for k in ('title', 'date')}
    if op == 'count_records': return {'record_count': sum(r['date'] < params['before'] for r in records)}
    if op == 'cross_page_dates':
        source = (ROOT/'.local/tricky-full-v1/upstream/src/components/health/LabResults.jsx').read_text()
        timestamp = re.search(r'label: "Blood Test", time: "([^"]+)"', source)[1]
        return {'medical_record_date': next(r['date'] for r in records if r['title'] == params['title']),
                'lab_result_timestamp': timestamp}
    if op == 'save_articles':
        selected = [min(news, key=date), max(news, key=date)] if 'rank_dates' in params else [next(n for n in news if n['title']==t) for t in params['titles']]
        return {'saved_article_ids': [n['id'] for n in selected]}
    if op == 'two_article_quotes':
        return {k: next(n['first_sentence'] for n in news if n['title']==t)
                for k,t in zip(('music_article','creative_article'),params['titles'])}
    if op == 'year_titles': return {'titles': [n['title'] for n in sorted(news,key=date) if date(n).year==params['year']]}
    if op == 'artist_catalog': return {'titles': sorted(s['title'] for s in facts['songs'] if s['artist']==params['artist'])}
    if op == 'plan_difference':
        # Explicit manually inspected original plan price source; not a task answer import.
        source = (ROOT/'.local/tricky-full-v1/upstream/src/components/spotify/darkPatterns/AestheticManipulation.jsx').read_text()
        prices = re.findall(r"price:\s*'US\$(\d+\.\d+)'", source)
        assert '9.99' in prices and '14.99' in prices
        return {'difference_usd': money(Decimal('14.99')-Decimal('9.99'))}
    if op == 'track_album':
        s = next(s for s in facts['songs'] if s['title']==params['title'])
        return {k:s[k] for k in ('artist','album')}
    if op == 'biography_catalog':
        artists = [a for a in facts['artists'] if params['biography_contains'] in a['bio']]
        assert len(artists)==1
        a=artists[0]
        return {'artist':a['name'],'titles':sorted(s['title'] for s in facts['songs'] if s['artistId']==a['id'])}
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
    facts=json.loads((AUTHORED/'source-facts.json').read_text())
    assert facts['products']==json.loads((ROOT/'.local/tricky-full-v1/catalog.json').read_text())
    for f,pin in contract['source_sha256'].items(): assert sha(ROOT/'.local/tricky-full-v1/upstream'/f)==pin
    tasks={t['id']:t for t in contract['tasks']}
    for t in tasks.values(): assert reference(t,facts)==t['grader_input']['expected'],t['id']
    counts=Counter(); records=[]
    for row in suite['rows']:
        assert row['source_unchanged'] and row['source_sha256']==suite['source_sha256']
        trace=ROOT/row['trace'];task=tasks[row['task_id']]
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
    return {'schema':'tricky-authored-independent-review-v1','status':'accepted_for_scoped_general_browsing_development',
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
