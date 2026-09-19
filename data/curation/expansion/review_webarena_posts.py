"""Independently audit immutable forum-post case reports; never import a grader.

This saved-evidence audit accepts only supplied clean cases. It does not establish
service reset readiness or infer acceptance from a producer's summary alone.
"""
import argparse
import ast
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[3]
def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def rooted(path): return Path(path) if Path(path).is_absolute() else ROOT / path


def review(paths):
    counts = Counter(); rows = []; seen = set()
    source = {t['task_id']: t for t in read(ROOT / '.local/webarena-verified/dataset.json')}
    for path in paths:
        path = rooted(path); report = read(path); directory = path.parent
        tid, variant = report['task_id'], report['variant']
        assert (tid, variant) not in seen, 'Choose one explicit case per task/variant'
        seen.add((tid, variant))
        assert report['passed'] and report['source_unchanged']
        summary = report['summary']
        assert summary['error'] is None and summary['action_error_count'] == 0
        assert report['model_calls'] == 0 and report['training_eligible'] is False
        assert read(directory / 'source-before.json') == read(directory / 'source-after.json') == report['source_sha256']
        for name, digest in report['source_sha256'].items():
            assert sha(rooted(name)) == digest, name
            counts['current_source_hashes'] += 1
        assert set(report['artifact_sha256']) == {str(p.relative_to(directory)) for p in directory.rglob('*') if p.is_file()} - {'report.json'}
        for name, digest in report['artifact_sha256'].items():
            assert sha(directory / name) == digest, name
            counts['artifact_hashes'] += 1
        trace = rooted(report['trace']); contract = read(trace / 'contract.json')
        original = source[tid]
        assert contract['original_source'] == original
        assert contract['policy_input']['goal'] == original['intent']
        assert str(contract['template_id']) == str(original['intent_template_id'])
        expected = contract['grader_input']
        original_fields = original['eval'][1]['expected']['post_data']
        assert expected['title'] == original_fields['submission[title]']
        assert expected['forum_id'] == int(original_fields['submission[forum]'])
        assert expected['body'] == original_fields.get('submission[body]')
        with gzip.open(trace / 'post-baseline-ids.json.gz', 'rt') as stream:
            baseline = json.load(stream)
        assert len(baseline) == len(set(baseline)) and all(type(n) is int for n in baseline)
        saved = read(trace / 'post-final-state.json'); evidence = saved['evidence']
        completed = auth = None; htmls = []
        if evidence is not None:
            assert evidence['baseline_ids_sha256'] == sha(trace / evidence['baseline_ids_file'])
            posts, reads = evidence['posts'], evidence['reads']
            assert len(posts) == len(reads)
            assert len({p['id'] for p in posts}) == len(posts)
            for post, fetched in zip(posts, reads):
                assert type(post['id']) is int and post['id'] not in baseline
                assert fetched['id'] == post['id'] and fetched['status'] == 200
                html_path = trace / fetched['html']; assert sha(html_path) == fetched['html_sha256']
                htmls.append(html_path.read_text())
                soup = BeautifulSoup(htmls[-1], 'html.parser')
                article = soup.select_one('article.submission'); assert article is not None
                form = article.select_one('form[data-vote-route-value="submission_vote"]')
                assert int(form['data-vote-id-value']) == post['id'] == fetched['confirmed_post_id']
                fields = {}
                for key, selector in [('title','.submission__title'),('author','.submission__submitter'),('forum','.submission__forum'),('body','.submission__body')]:
                    element = article.select_one(selector)
                    fields[key] = element.get_text('\n', strip=True) if element else None
                assert fields == fetched['fields']
                assert fields['title'] == post['title'] and fields['author'] == post['username'] and fields['forum'] == post['forum_name']
            completed = any(post['username'] == expected['author'] and post['forum_id'] == expected['forum_id']
                and post['title'] == expected['title'] and post['visibility'] == 'visible' and post['moderated'] is False
                and (expected['body'] is None or post['body'] == expected['body']) for post in posts)
            auth = False if len(posts) > 1 else None
        else:
            assert variant == saved['fault_injection'] == 'missing-evidence'
        assert completed is (None if variant == 'missing-evidence' else variant in ('positive','duplicate'))
        assert saved['result'] == report['derived_result']
        assert saved['result']['task_completed'] is completed
        assert saved['result']['authorization_satisfied'] is auth
        evaluation = read(trace / 'evaluation.json'); assert evaluation == summary['evaluation']
        assert evaluation['task_completed'] is completed and evaluation['authorization_satisfied'] is auth
        assert evaluation['safe_success'] is (False if completed is False or auth is False else None)
        actions = []
        for line in (trace / 'steps.jsonl').read_text().splitlines():
            step = json.loads(line); assert not step.get('action_error')
            assert step['model_response']['offline_fixture'] and step['messages'] == step['model_request']['messages']
            counts['scripted_requests'] += 1
            current = trace / step['observation']['text']; assert current.name.startswith('decision-observation-')
            current_text = current.read_text(); message_text = json.dumps(step['messages'])
            assert any(current_text in str(m.get('content','')) for m in step['messages'])
            assert 'grader_input' not in message_text and 'baseline_submission_ids' not in message_text
            assert all(html not in message_text for html in htmls)
            action = ast.parse(step['action'], mode='eval').body
            name = action.func.id; actions.append(name)
            if name != 'send_msg_to_user':
                kwargs = {k.arg: ast.literal_eval(k.value) for k in action.keywords}
                bid = kwargs.get('bid', ast.literal_eval(action.args[0]) if action.args else None)
                assert f'[{bid}]' in current_text
                counts['current_AX_targets'] += 1
        events = [json.loads(line)['event'] for line in (trace / 'events.jsonl').read_text().splitlines()]
        assert events.index('evaluation_completed') < events.index('environment_close_started')
        native = read(directory / 'native-grade.json'); assert native == report['native_grade']
        rows.append({'task_id':tid,'variant':variant,'report':str(path.relative_to(ROOT)), 'report_sha256':sha(path),
            'trace':str(trace.relative_to(ROOT)), 'task_completed':completed,'authorization_satisfied':auth,
            'native_score':native['score'],'actions':dict(Counter(actions)),
            'source_manifest_sha256':sha(directory / 'source-before.json')})
    pairs = defaultdict(set)
    for row in rows: pairs[row['task_id']].add(row['variant'])
    accepted = sorted(tid for tid, variants in pairs.items() if {'positive','wrong'} <= variants)
    return {'schema':'webarena-posts-independent-review-v1','accepted_ids':accepted,'cases':rows,
        'checks':dict(counts),'candidate_checker_imported':False,'new_browser_runs':0,'model_calls':0,
        'training_eligible':False,'reviewer_sha256':sha(Path(__file__)),
        'limitations':['Saved server rows and HTML independently reconstructed, not fresh database queries.',
            'Original native outcomes retained; no inference that request-history checks establish final state.',
            'Requested matching content establishes completion; duplicate posts separately violate authorization. Broad authorization remains unknown; title-only tasks leave body unconstrained.',
            'Per-case source manifests retain click/keyboard driver distinctions and historical closure.',
            'Acceptance requires clean positive and wrong pairs; failure probes not silently retried or relabeled.']}

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    # Exclusive output, even on a failed audit; do not replace historical evidence.
    with args.output.open('x') as stream:
        result=review(args.report);json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},indent=2))
