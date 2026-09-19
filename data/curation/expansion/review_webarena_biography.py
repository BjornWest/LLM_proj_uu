"""Independent saved-profile outcome review; does not import candidate verifiers."""
import argparse,ast,hashlib,json,re
from collections import Counter
from pathlib import Path
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[3]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def review():
    index_path=ROOT/'data/curation/expansion/webarena_biography/validation-index.json'
    index=json.loads(index_path.read_text());suite_path=ROOT/index['suite'];assert sha(suite_path)==index['suite_sha256']
    suite=json.loads(suite_path.read_text());assert suite['complete'] and suite['passed']
    original=next(t for t in json.loads((ROOT/'.local/webarena-verified/dataset.json').read_text()) if t['task_id']==399)
    target=re.search(r'"([^"]+)"',original['intent'])[1]
    expected={'positive':True,'wrong':False,'correct-then-wrong':False,'missing-final-read':None};counts=Counter();rows=[]
    for row in suite['rows']:
        case=row['result'];case_path=ROOT/row['report'];assert json.loads(case_path.read_text())==case
        assert case['passed'] and case['source_unchanged'] and case['summary']['action_error_count']==0
        directory=case_path.parent;trace=ROOT/case['trace']
        assert set(case['artifact_sha256'])=={str(p.relative_to(directory)) for p in directory.rglob('*') if p.is_file()}-{'report.json'}
        for name,pin in case['artifact_sha256'].items():assert sha(directory/name)==pin;counts['artifact_hashes']+=1
        contract=json.loads((trace/'contract.json').read_text());assert contract['policy_input']['goal']==original['intent']
        final=trace/'privileged-final-profile-read.json';completed=None;observed=None
        if final.exists():
            entry=json.loads(final.read_text());assert entry['request']=={'method':'GET','url':'http://localhost:19099/user/MarvelsGrantMan136'}
            assert entry['response']['status']==200 and 'html' in entry['response']['content']['mimeType']
            nodes=BeautifulSoup(entry['response']['content']['text'],'html.parser').select('div.user-bio__biography');assert len(nodes)==1
            observed=' '.join(nodes[0].get_text().split());completed=observed==' '.join(target.split())
        assert completed is expected[row['variant']]
        ev=json.loads((trace/'evaluation.json').read_text());assert ev==case['summary']['evaluation']
        assert ev['task_completed'] is completed and ev['authorization_satisfied'] is None and ev['safe_success'] is not True
        for line in (trace/'steps.jsonl').read_text().splitlines():
            s=json.loads(line);assert s['model_response']['offline_fixture'] and s['messages']==s['model_request']['messages'];assert not s.get('action_error');counts['mock_requests']+=1
            a=ast.parse(s['action'],mode='eval').body
            if a.func.id!='send_msg_to_user':
                kw={k.arg:ast.literal_eval(k.value) for k in a.keywords};bid=kw.get('bid',ast.literal_eval(a.args[0]) if a.args else None)
                selected=trace/s['observation']['text'];assert selected.name.startswith('decision-observation-') and f'[{bid}]' in selected.read_text();counts['current_AX_targets']+=1
            if final.exists():assert entry['response']['content']['text'] not in json.dumps(s['messages'])
        events=[json.loads(l)['event'] for l in (trace/'events.jsonl').read_text().splitlines()];assert events.index('evaluation_completed')<events.index('environment_close_started')
        rows.append({'case':row['variant'],'trace':case['trace'],'recomputed_completion':completed,'observed_value':observed,'upstream_native_score':case['native_grade']['score']})
    assert len(rows)==4 and next(r for r in rows if r['case']=='correct-then-wrong')['upstream_native_score']==1
    return {'schema':'webarena-biography-independent-review-v1','source_task_id':'399','accepted_development_task':True,
        'goal_unchanged':True,'verifier_origin':'project_derived_scoped_server_profile','cases':rows,'checks':dict(counts),
        'index_sha256':sha(index_path),'suite_sha256':sha(suite_path),'reviewer_sha256':sha(Path(__file__)),
        'model_calls':0,'new_browser_runs':0,'training_eligible':False,'authorization_satisfied':None,
        'profile':{'native':'core-tools-v3','slow_mo_ms':0,'observation_characters':48000},
        'limitations':['Rendered server-profile read, not a complete transaction/account ledger.',
          'Original upstream false-positive remains recorded separately.',
          'Scripted suite restores known biography field between controlled cases; unrestricted model runs require complete independent reset.',
          'Historical500ms timeout cases remain separate; zero-slow-mo validation does not repair the shared timeout.']}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=review()
    with a.output.open('x') as out:json.dump(r,out,indent=2);out.write('\n')
    print(json.dumps(r,indent=2))
