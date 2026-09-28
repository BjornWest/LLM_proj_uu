"""Prepare answer-free manual evaluation packages; never dispatch inference.

Usage: python -m scripts.prepare_connected_qwen --binding ... --output NEW_DIRECTORY
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from intent_browser.connected_world_task import public_projection, sha, checked_files
from intent_browser.input_budget import DEFAULT_MAX_STEPS, DEFAULT_MAX_INPUT_TOKENS
from intent_browser.openrouter import DEFAULT_PROVIDERS, DEFAULT_MAX_TOKENS, provider_options


def read(path): return json.loads(Path(path).read_text())

def write(path, data):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def prepare_six(binding, output):
    binding=Path(binding).resolve(); output=Path(output)
    pins=read(binding/'pins.json')
    # Historical source versions are recorded, not silently relabelled current.
    inputs={str(Path(k).resolve()):v for section in ('input_sha256','private_artifact_sha256','policy_artifact_sha256')
            for k,v in pins[section].items()}
    inputs[str(binding/'pins.json')]=sha(binding/'pins.json')
    checked_files(inputs)
    runtime=Path(pins['runtime']).resolve()
    manifest=read(runtime/'manifest.json')
    origins=[manifest['index_url']]+[s['origin'] for s in manifest['sites']]
    policies=[(Path(p),read(p)) for p in pins['policy_artifact_sha256'] if p.endswith('/task.json')]
    output.mkdir(parents=True, exist_ok=False)
    cases=[]
    for case in pins['case_order']:
        task=read(binding/f'{case}.task.private.json')
        selected=[(p,v) for p,v in policies if all(v[k]==task['public'][k] for k in ('user_message','memories'))]
        if len(selected)!=1:raise ValueError('Ambiguous public projection for '+case)
        policy_path,original=selected[0]
        public=public_projection({**original,'task_id':original['episode_id']})
        directory=output/case;directory.mkdir();(directory/'public').mkdir();(directory/'private').mkdir()
        write(directory/'public/task.json',public)
        attachments={'original-policy.json':str(policy_path.resolve()),
                     'task.private.json':str(binding/f'{case}.task.private.json'),
                     'scenario.private.json':str(binding/f'{case}.scenario.private.json'),
                     'reference.private.json':str(binding/f'{case}.acceptance.private.json')}
        write(directory/'private/binding.json',{'schema_version':'connected-world-manual-binding-v1',
            'case_id':case,'public_sha256':sha(directory/'public/task.json'),
            'origins':origins,'source_sha256':inputs,'attachments':attachments,
            'runtime':str(runtime),'reference_scope':'Frozen deterministic reference; manual prose review, no grading call',
            'clarification':None})
        cases.append(case)
    profile=proposed_profile(cases)
    profile['historical_binding_source_sha256']=pins['source_sha256']
    profile['source_changes_since_binding']=[p for p,h in pins['source_sha256'].items() if not Path(p).is_file() or sha(p)!=h]
    write(output/'profile.proposed.json',profile)
    return profile


def prepare_bank(bank, output):
    bank=Path(bank).resolve();output=Path(output)
    pins=read(bank/'pins.json');manifest_path=bank/'manifest.private.json'
    files={str(Path(k).resolve()):v for section in ('inputs','files','code') for k,v in pins[section].items()}
    files[str(bank/'pins.json')]=sha(bank/'pins.json')
    files[str(manifest_path)]=sha(manifest_path)
    checked_files(files)
    manifest=read(manifest_path)
    output.mkdir(parents=True,exist_ok=False)
    cases=[]
    for row in manifest['cases']:
        case=row['case_id'];public_path=Path(row['public_path']).resolve();private_path=Path(row['private_path']).resolve()
        packet=read(private_path);public=public_projection(read(public_path))
        from environments.product_world.generator import digest
        if digest(read(public_path))!=packet['public_sha256'] or packet['task_id']!=public['task_id']:
            raise ValueError('Manual packet identity mismatch')
        sources={str(Path(k).resolve()):h for k,h in packet['source_bindings'].items()}
        checked_files(sources)
        runtime_paths=[Path(k) for k in sources if k.endswith('/manifest.json')]
        if len(runtime_paths)!=1:raise ValueError('Ambiguous runtime manifest')
        runtime=read(runtime_paths[0])
        directory=output/case;directory.mkdir();(directory/'public').mkdir();(directory/'private').mkdir()
        write(directory/'public/task.json',public)
        write(directory/'private/binding.json',{'schema_version':'connected-world-manual-binding-v1',
            'case_id':case,'public_sha256':sha(directory/'public/task.json'),
            'origins':[runtime['index_url']]+[v['origin'] for v in runtime['sites']],
            'source_sha256':{**files,**sources},
            'attachments':{'reference.private.json':str(private_path),'original-policy.json':str(public_path)},
            'runtime':str(runtime_paths[0].parent),'clarification':packet.get('clarification'),
            'reference_scope':'Product frozen manual fact packet; not an automatic grader'})
        cases.append(case)
    profile=proposed_profile(cases)
    profile['clarification']='Same opt-in ask_user tool in all 14 cases; private responder supplies only known facts or unavailable reply'
    profile['bank_manifest_sha256']=sha(manifest_path)
    write(output/'profile.proposed.json',profile)
    return profile


def proposed_profile(cases):
    # Read only selected nonsecret settings. Do not serialize .env or credentials.
    from dotenv import dotenv_values
    import os
    values=dotenv_values('.env')
    model=os.environ.get('MODEL_NAME') or values.get('MODEL_NAME') or 'qwen/qwen3.8-27b'
    providers=os.environ.get('OPENROUTER_PROVIDERS') or values.get('OPENROUTER_PROVIDERS') or ','.join(DEFAULT_PROVIDERS)
    return {'schema_version':'connected-qwen-manual-profile-v1','status':'proposed_not_executed',
        'cases':list(cases),'model':model,
        'base_url':os.environ.get('MODEL_BASE_URL') or values.get('MODEL_BASE_URL') or 'https://openrouter.ai/api/v1',
        'request_options':provider_options(providers),
        'session_routing':True,'temperature':0,'max_tokens':DEFAULT_MAX_TOKENS,
        'max_steps':DEFAULT_MAX_STEPS,'max_input_tokens':DEFAULT_MAX_INPUT_TOKENS,
        'harness_profile':'current standard + opt-in clarification when applicable',
        'helpers':False,'data_tools':True,'parallel_search':False,'record_video':True,
        'headless':True,'concurrency':2,'client_retries':False,'decision_retries':False,
        'grading':'manual natural-answer/world-fact review; outcome labels unknown',
        'costs':'Report actual provider usage/cost and unknown costs; no new inference in preparation',
        'readiness':'Requires stable current runtime source freeze and scripted host acceptance before model dispatch',
        'scope':'First cohort has no helper agents; exact schema/settings saved by normal runner'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--binding',type=Path)
    source.add_argument('--bank',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=prepare_bank(args.bank,args.output) if args.bank else prepare_six(args.binding,args.output)
    print(json.dumps({'output':str(args.output),'cases':report['cases'],'model_calls':0}))

if __name__=='__main__':main()
