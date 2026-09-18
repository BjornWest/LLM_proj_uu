"""Validate saved triage exports and the initial sweep pointers; optional local UI check."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from data.curation.trace_triage.review import validate


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(directory, ui=False):
    report = read(directory/'triage.json')
    manifest = read(directory/'manifest.json')
    count = source_count = 0
    for name, expected in manifest['files'].items():
        assert sha(directory/name) == expected['sha256'], name
        count += 1
    for name, expected in report['tool_source_sha256'].items():
        assert sha(ROOT/'data/curation/trace_triage'/name) == expected, name
    for e in report['episodes']:
        for name, expected in e['source_artifacts'].items():
            original = Path(e['source_path'])/name
            copy = directory/'evidence'/e['key']/name
            assert original.read_bytes() == copy.read_bytes()
            assert sha(original) == expected['sha256']
            source_count += 1
        validate(read(directory/'diagnoses'/f"{e['key']}.json"), e)
        if (Path(e['source_path'])/'evaluation.json').exists():
            assert e['recorded_evaluation'] == read(Path(e['source_path'])/'evaluation.json')
    baseline = read(ROOT/'data/curation/sweeps/external-baseline-v1/transient-feedback-review.json')
    known = {(Path(c['episode']).name,g['after_step']) for c in baseline['cases'] for g in c['gaps']}
    found = set()
    for e in report['episodes']:
        steps = {s['step']:s for s in [json.loads(line) for line in (Path(e['source_path'])/'steps.jsonl').read_text().splitlines()]}
        for f in e['flags']:
            if f['code'] != 'feedback_not_in_next_input':
                continue
            step = steps[f['step']]
            # Independent direct string membership for these plain-text saved requests.
            contents = [m['content'] for m in step['model_request']['messages']]
            assert all(isinstance(c,str) for c in contents)
            post = (Path(e['source_path'])/f['evidence'][0]).read_text()
            assert all(text in post and all(text not in content for content in contents) for text in f['missing_text'])
            found.add((e['episode_id'],f['after_step']))
    assert known <= found, sorted(known-found)
    result = {'schema':'trace-triage-validation-v1', 'report':str(directory),
              'manifest_sha256':sha(directory/'manifest.json'),'triage_sha256':sha(directory/'triage.json'),
              'validator_sha256':sha(Path(__file__)), 'episodes':len(report['episodes']),
              'outcomes':report['analysis']['outcomes'],'export_hash_checks':count,
              'source_byte_equality_checks':source_count,'known_feedback_pointers_recovered':len(known),
              'all_feedback_pointers_string_checked':len(found),
              'causal_labels_validated':False,'model_calls':0,'browser_agent_runs':0,'ui':None}
    if ui:
        from playwright.sync_api import sync_playwright
        os.environ['LD_LIBRARY_PATH'] = str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width':1440,'height':1000})
            errors, requests = [], []
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda r:requests.append(r.url))
            page.goto((directory/'index.html').resolve().as_uri())
            assert page.locator('#list table tr').count()==43
            page.select_option('#outcome','failure');assert page.locator('#list table tr').count()==11
            page.locator('#list button',has_text='P07-injected-r01').click()
            assert page.locator('#comparisons button').count()==3
            assert page.locator('#alignment .pair').count()>0
            page.get_by_role('button',name='Review step 3',exact=True).click()
            assert '/step/3' in page.url
            page.reload();assert page.locator('#review-title').inner_text()=='P07-injected-r01'
            assert page.locator('#review details[open]').count()>=1
            page.select_option('#outcome','unknown');assert page.locator('#list table tr').count()==3
            page.locator('#list button').first.click();assert 'No same-task' in page.locator('#comparisons').inner_text()
            page.select_option('#outcome','')
            options=page.locator('#group option').evaluate_all('(xs)=>xs.map(x=>({value:x.value,text:x.textContent}))')
            target=next(x for x in options if x['text'].startswith('flag: decision_error'))
            page.select_option('#group',target['value']);assert page.locator('#list table tr').count()==3
            page.fill('#search','P10-injected-r01');assert page.locator('#list table tr').count()==2
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
            assert not errors,errors
            assert not any(u.startswith(('http:','https:')) for u in requests),requests
            result['ui']={'rows':42,'failure_filter':10,'unknown_filter':2,'comparison_candidates':3,
                          'step_link_reload':True,'flag_filter':True,'search':True,'mobile_no_overflow':True,
                          'page_errors':errors,'http_requests':0,'scope':'Headless local file viewer only, no task environment'}
            browser.close()
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--ui',action='store_true')
    args=p.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise ValueError('Choose a new validation output')
    result=verify(args.report,args.ui)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result))
