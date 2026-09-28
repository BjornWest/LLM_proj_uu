"""Run ten finite, explicitly authored answer mutations, with bounded concurrency."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from threading import Event

from .extraction import MODEL, VERSION, messages, schema_for, response_format, strict_loads, validate_claims
from .grading import grade_claims, research_effects
from .robustness import cases, compare
from .run import write
from .saved import load_saved, sha


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cohort',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--live',action='store_true');args=p.parse_args()
    if args.output.exists() or args.output.is_symlink():p.error('Output must be new')
    sys.path.insert(0,str(args.cohort.resolve()/'source'))
    saved=load_saved(args.cohort);schema=schema_for(saved.episode)
    fixtures=cases(saved.public,saved.answer);assert len(fixtures)==10
    effects=research_effects(saved.initial,saved.final)
    out=args.output;out.mkdir(parents=True)
    hashes={str(f.resolve()):sha(f) for f in Path(__file__).parent.glob('*.py')}
    write(out/'cases.private.json',fixtures);write(out/'source-hashes.json',saved.hashes)
    (out/'source').mkdir()
    for name,h in hashes.items():
        data=Path(name).read_bytes();assert hashlib.sha256(data).hexdigest()==h
        with (out/'source'/Path(name).name).open('xb') as f:f.write(data)
    from intent_browser.openrouter import provider_options,DEFAULT_PROVIDERS
    options=provider_options(DEFAULT_PROVIDERS);options['response_format']=response_format(schema)
    write(out/'plan.json',{'version':VERSION,'kind':'extractor-mutation-suite-v1','model':MODEL,
        'cases':[{'id':c['id'],'name':c['name']} for c in fixtures],'max_requests':10,'concurrency':2,
        'max_tokens':16384,'client_retries':0,'browser_runs':0,'reasoning_enabled':True,
        'code_sha256':hashes,'cohort':str(args.cohort.resolve()),'request_options':options,
        'scope':'Authored answer mutations, not new policy trajectories or task-performance measurements.'})
    if not args.live:
        print(json.dumps({'status':'prepared','cases':10,'model_calls':0}));return
    from dotenv import dotenv_values
    from intent_browser.backend import ChatCompletionsBackend
    key=os.environ.get('OPENROUTER_API_KEY') or dotenv_values(Path.cwd()/'.env').get('OPENROUTER_API_KEY')
    if not key:raise ValueError('Missing OpenRouter credential')
    stop=Event()
    def run(case):
        directory=out/case['id'];directory.mkdir()
        result={'id':case['id'],'name':case['name'],'extraction_valid':False,'test_passed':False,'reported_cost_usd':None}
        if stop.is_set():
            result['error']='Not dispatched: previous transport failure';write(directory/'result.json',result);return result
        prompt=messages(case['public_task'],case['answer'],schema=schema)
        write(directory/'messages.json',prompt)
        backend=ChatCompletionsBackend('https://openrouter.ai/api/v1',MODEL,key,timeout=240,
            max_tokens=16384,request_options=options,session_routing=True)
        backend.begin_episode(out.name+'-'+case['id'])
        def dispatch(request):
            if stop.is_set():raise ValueError('Suite transport stop before dispatch')
            for name,h in {**saved.hashes,**hashes}.items():
                if sha(name)!=h:raise ValueError('Pinned source changed')
            write(directory/'request.json',json.loads(request.content))
            write(directory/'dispatch.json',{'at':datetime.now(timezone.utc).isoformat(),'attempt':1})
        def receive(response):
            response.read()
            with (directory/'response.body').open('xb') as f:f.write(response.content)
            write(directory/'http.json',{'status':response.status_code,'at':datetime.now(timezone.utc).isoformat()})
        backend.client.event_hooks={'request':[dispatch],'response':[receive]}
        stage='transport'
        try:
            completion=backend.complete(prompt);write(directory/'response.json',completion.raw)
            usage=completion.raw.get('usage') or {};result['reported_cost_usd']=usage.get('cost')
            result['usage']=usage;result['provider']=completion.raw.get('provider');stage='validation'
            choice=completion.raw['choices'][0];result['finish_reason']=choice.get('finish_reason')
            if choice.get('finish_reason')!='stop' or choice['message'].get('refusal') or choice['message'].get('tool_calls'):
                raise ValueError('Incomplete/refused/nontext response')
            claims=strict_loads(completion.text);write(directory/'claims.json',claims)
            validate_claims(claims,case['answer'],schema=schema);result['extraction_valid']=True
            result['checks']=compare(claims,case['expected'])
            if claims['interpretation']=='ambiguous':result['grading']='review_required'
            else:
                grade=grade_claims(saved.episode,claims,case['answer'],effects=effects,schema=schema)
                write(directory/'grade.json',grade);result['grading']='graded'
                result['oracle_checks']=compare(grade['oracle_grade']['requirements'],case['oracle_checks'])
            result['test_passed']=all(x['passed'] for x in result['checks'].values()) and all(x['passed'] for x in result.get('oracle_checks',{}).values())
        except Exception as exc:
            result['error']={'stage':stage,'type':type(exc).__name__,'message':str(exc)}
            if stage=='transport':stop.set()
        finally:backend.close()
        write(directory/'result.json',result)
        print(json.dumps({k:result.get(k) for k in ['id','test_passed','extraction_valid','reported_cost_usd','error']}),flush=True)
        return result
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,fixtures))
    unchanged=all(sha(name)==h for name,h in {**saved.hashes,**hashes}.items())
    report={'schema':'extractor-mutation-results-v1','cases':results,'passed':sum(r['test_passed'] for r in results),
            'total':len(results),'valid_extractions':sum(r['extraction_valid'] for r in results),
            'reported_cost_usd':sum(r['reported_cost_usd'] or 0 for r in results),
            'unknown_cost_attempts':sum((out/r['id']/'dispatch.json').exists() and r['reported_cost_usd'] is None for r in results),
            'source_hashes_unchanged':unchanged,'browser_runs':0,
            'limitations':['One sample per authored perturbation; not an extraction accuracy estimate.',
                           'Original task wording ambiguity irrelevant to field extraction, not reclassified as policy failure.']}
    write(out/'report.json',report);print(json.dumps({k:v for k,v in report.items() if k!='cases'}),flush=True)


if __name__=='__main__':main()
