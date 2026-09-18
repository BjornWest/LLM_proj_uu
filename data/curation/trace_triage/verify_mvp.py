"""Verify a saved MVP export against originals; optional local browser UI check."""
import argparse
import hashlib
import json
import os
from pathlib import Path


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text())


def verify(directory, ui=False):
    report=read(directory/'triage.json');manifest=read(directory/'manifest.json')
    for name,info in manifest['files'].items():
        assert sha(directory/name)==info['sha256'],name
    for name,value in report['tool_source_sha256'].items():
        assert sha(Path(__file__).parent/name)==value,name
    sources=rows=0
    for episode in report['episodes']:
        root=Path(episode['source_path']);key=episode['key']
        for name,info in episode['source_artifacts'].items():
            assert sha(root/name)==info['sha256'] and (root/name).read_bytes()==(directory/'evidence'/key/name).read_bytes(),name
            sources+=1
        if (root/'evaluation.json').exists():
            assert episode['recorded_evaluation']==read(root/'evaluation.json')
        meta=read(root/'episode.json') if (root/'episode.json').exists() else read(root/'metadata.json')
        original=[json.loads(s) for s in (root/meta.get('steps_file','steps.jsonl')).read_text().splitlines() if s.strip()]
        for row in original:
            projection=read(directory/'step-records'/key/f"{row['step']}.json")
            assert projection['row']==row
            assert projection['source_sha256']==sha(root/projection['source_artifact'])
            rows+=1
        for field in ('prompt_tokens','completion_tokens','cached_tokens','reasoning_tokens'):
            values=[];attempts=0
            for row in original:
                request=row.get('model_request');response=row.get('model_response')
                if not (isinstance(request,dict) and request or isinstance(response,dict) and response):continue
                attempts+=1
                usage=(response or {}).get('usage') or {}
                if field=='cached_tokens': data=usage.get('prompt_tokens_details') or {}
                elif field=='reasoning_tokens': data=usage.get('completion_tokens_details') or {}
                else: data=usage
                value=data.get(field)
                if type(value) is int and value>=0:values.append(value)
            actual=episode['operational_metrics']['totals'][field]
            assert actual['known_sum']==(sum(values) if values else None)
            assert actual['reported_requests']==len(values)
            assert actual['missing_requests']==attempts-len(values)
    result={'schema':'trace-triage-mvp-validation-v1','report':str(directory),
            'report_sha256':sha(directory/'triage.json'),'manifest_sha256':sha(directory/'manifest.json'),
            'episodes':len(report['episodes']),'outcomes':report['analysis']['outcomes'],
            'source_files_checked':sources,'step_projections_checked':rows,
            'export_hashes_checked':len(manifest['files']),'raw_usage_totals_independently_checked':True,
            'model_calls':0,'task_browser_runs':0,'ui':None}
    if ui:
        from playwright.sync_api import sync_playwright
        root=Path(__file__).resolve().parents[3]
        os.environ['LD_LIBRARY_PATH']=str(root/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];requests=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda r:requests.append(r.url))
            page.goto((directory/'index.html').resolve().as_uri())
            assert page.locator('#list button').count()==len(report['episodes'])
            page.select_option('#sort','tokens')
            top=max(report['episodes'],key=lambda e:e['operational_metrics']['totals']['total_tokens']['known_sum'] or -1)
            page.locator('#list button').first.click()
            assert page.locator('#review-title').inner_text()==(top['case_id'] or top['episode_id'])
            assert page.get_by_text('Tokens, cache, reasoning, provider and reporting coverage',exact=True).count()==1
            page.select_option('#queue','sampled')
            assert page.locator('#list button').count()==report['analysis']['review_queue']['sampled_success_count']
            page.select_option('#queue','');page.select_option('#outcome','success')
            assert page.locator('#list button').count()==report['analysis']['outcomes'].get('success',0)
            successes=[e for e in report['episodes'] if e['outcome_group']=='success' and any(c['left']==e['episode_id'] for c in report['analysis']['comparisons'])]
            if successes:
                e=successes[0];page.locator('#list button',has_text=e['case_id'] or e['episode_id']).click()
                assert page.locator('#comparisons button').count()>0
                assert page.locator('#alignment .pair').count()>0
                assert page.get_by_text('Saved request/response for this step',exact=True).count()>0
            page.select_option('#outcome','');page.fill('#search','20260916T222837Z')
            assert page.locator('#list button').count()==sum('20260916T222837Z' in e['episode_id'] for e in report['episodes'])
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
            assert not errors,errors
            assert not any(u.startswith(('http:','https:')) for u in requests)
            result['ui']={'filters':True,'token_sort':True,'control_sample':True,'success_comparisons':bool(successes),
                          'step_links':True,'mobile_no_overflow':True,'javascript_errors':errors,'http_requests':0}
            browser.close()
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--ui',action='store_true');args=parser.parse_args()
    if args.output.exists() or args.output.is_symlink():raise ValueError('Choose a new validation path')
    result=verify(args.report,args.ui)
    with args.output.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps(result))
