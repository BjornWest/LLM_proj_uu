"""Export accepted goals and implementation bindings; never launch or infer.

Bindings describe existing adapters and required lifecycle. They are not a paid
run authorization, live-source certificate, or a replacement for source closure
preflight. Only policy_input may be projected into the agent's task context.
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
from data.curation.expansion.accepted_index import BASE, ROOT, collect, load, pin


def symbol(module,name):
    path=Path(module.replace('.','/')+'.py')
    tree=ast.parse((ROOT/path).read_text())
    if name not in {n.name for n in tree.body if isinstance(n,(ast.ClassDef,ast.FunctionDef))}:
        raise ValueError('Implementation symbol absent: '+module+':'+name)
    return {'module':module,'symbol':name,'source':pin(path)}


def policy_projection(binding):
    # Deliberately do not forward contract, implementation, grading or reviews.
    policy=binding['policy_input']
    if not isinstance(policy.get('goal'),str) or not policy['goal'].strip():raise ValueError('Missing goal')
    return {'goal':policy['goal'],'terminal_response_instruction':policy['terminal_response_instruction']}


def binding(row):
    result={'id':row['id'],'dataset':row['dataset'],'origin':row['origin'],
        'template_id':row['template_id'],'sites':row['sites'],
        'policy_input':{'goal':row['goal'],'terminal_response_instruction':None},
        'private_contract':row['contract_reference'],'private_contract_row_id':row['contract_row_id'],
        'review_references':row['review_references'],
        'validation_profile':{'name':'core-tools-v3','observation_text_limit':48000,
            'observation_limit_units':'flattened AX characters','before_observation':'fresh hook required'},
        'reference_runtime_for_new_offline_profile':{
            'manifest':pin(Path('.local/curation-expansion/frozen-runtime-v1/manifest.json')),
            'historical_execution_identity':False,
            'note':'Optional copied baseline; historical cases retain their own live/copy source maps.'},
        'model_tested':False,'training_eligible':False,'production_ready':False,
        'new_execution_ready':False,
        'required_preflight':['Exact runtime, adapter and transitive helper/contract closure.',
            'Pinned complete site/build and test account identity.',
            'Fresh context and task-appropriate server reset; retain grades and unknowns.',
            'If using a model: separately authorized budget/request caps and model profile.']}
    if row['dataset']=='trickyarena':
        raw=load(Path(row['contract_reference']['path']));task=next(t for t in raw['tasks'] if t['id']==row['instance_id'])
        tid=row['instance_id'];module=None;name=None
        if tid.startswith('TX'):
            module='data.curation.expansion.adopt_tricky_native';name='NativeLookup';steps=16
        elif tid.startswith('TA'):
            module='data.curation.expansion.adopt_tricky_native';name='NativeAction';steps=16
        elif tid.startswith('TO'):
            module='data.curation.expansion.tricky_original_remaining.tasks';name='RemainingTask';steps=16
        elif tid.startswith('AU'):
            number=int(tid[2:]);batch='authored' if number<=20 else 'authored02' if number<=40 else 'authored03' if number<=60 else 'authored04'
            version='native_v2' if batch=='authored02' or tid in {'AU46','AU47','AU51','AU52'} else 'native'
            module='data.curation.expansion.tricky.'+batch+'.'+version;name='AuthoredTask';steps=24 if number<=20 else 28
        else:raise ValueError(tid)
        result['policy_input']['terminal_response_instruction']=raw.get('policy_response_protocol',task.get('policy_terminal_instruction'))
        result['implementation']={'type':'existing_episode_task','factory':symbol(module,name),'constructor_kwargs':{'task_id':tid},
            'environment_factory':'adapter.make_env(video, action_mapping)',
            'lifecycle':'prepare -> make_env -> capture_initial -> after_step -> evaluate before close -> adapter.close'}
        result['environment']={'complete_site_build':pin(Path('.local/tricky-full-v1/build.json')),
            'catalog':pin(Path('.local/tricky-full-v1/catalog.json')),'isolation':'Adapter creates per-episode FixtureServer and fresh browser context.'}
        result['validation_profile'].update(max_steps=steps,slow_mo_ms=100)
        result['verifier']={'origin':'project_derived_scoped_adapter','timing':'before_browser_close','authorization':'partial_or_unknown; preserve evaluation fields exactly'}
    else:
        tid=row['source_task_id'];source=next(t for t in load(Path('.local/webarena-verified/dataset.json')) if str(t['task_id'])==tid)
        protocol=('When finished, call send_msg_to_user with a JSON object containing task_type (retrieve, navigate, or mutate), status (SUCCESS or an applicable failure status), and retrieved_data (the answer data for retrieval; null for actions). The retrieved_data schema for this task is: '+json.dumps(source['eval'][0]['results_schema']))
        result['policy_input']['terminal_response_instruction']=protocol
        if tid=='399':
            result['policy_input']['terminal_response_instruction']=load(BASE/'webarena_biography/contract.json')['policy_input']['response_protocol']
            result['implementation']={'type':'existing_episode_task_with_external_factory','factory':symbol('data.curation.expansion.webarena_biography.run','FinalReadTask'),'constructor_kwargs':{'variant':'positive'},'variant_meaning':'ordinary verification enabled; not a declared outcome','browser_task':symbol('data.curation.expansion.webarena_biography.run','TaskBrowser'),'factory_recipe':pin(BASE/'webarena_biography/run.py')}
            result['environment']={'origin_at_validation':'http://localhost:19099','isolation':'Complete independently owned forum reset required for unrestricted agent runs.'}
            result['verifier']={'origin':'project_derived_scoped_server_profile','timing':'before_browser_close','native_grading':'Separate post-close diagnostic only; known overwrite false positive retained.'}
            result['validation_profile'].update(max_steps=24,slow_mo_ms=0)
        elif tid in {'400','401','402','403'}:
            contract=load(BASE/'webarena_biography_batch02/contracts.json')
            task=next(t for t in contract['tasks'] if str(t['source_task_id'])==tid)
            result['policy_input']['terminal_response_instruction']=task['policy_input']['response_protocol']
            module='data.curation.expansion.webarena_biography_batch02.run'
            result['implementation']={'type':'existing_episode_task_with_external_factory','factory':symbol(module,'FinalReadTask'),'constructor_kwargs':{'task_id':int(tid),'variant':'positive'},'variant_meaning':'ordinary verification enabled; not a declared outcome','browser_task':symbol(module,'TaskBrowser'),'factory_recipe':pin(BASE/'webarena_biography_batch02/run.py')}
            result['environment']={'origin_at_validation':'http://localhost:19089','isolation':'Complete independently owned forum reset required for unrestricted agent runs; warmed scripted evidence does not repair cold-route navigation timeout.'}
            result['verifier']={'origin':'project_derived_scoped_server_profile','timing':'before_browser_close','native_grading':'Separate post-close diagnostic only; known overwrite false positive retained.'}
            result['validation_profile'].update(max_steps=24,slow_mo_ms=0)
        elif int(tid) in set(range(630,635))|set(range(640,650)):
            result['policy_input']['terminal_response_instruction']=load(BASE/'webarena_posts/contracts.json')['terminal_response_instruction']
            module='data.curation.expansion.webarena_posts.run_v7'
            result['implementation']={'type':'existing_episode_task_with_external_factory','factory':symbol(module,'PostTask'),'constructor_bindings':{'task':'private contract row','variant':'positive (ordinary verification; not declared outcome)'},'browser_task':symbol(module,'BrowserTask'),'factory_recipe':pin(BASE/'webarena_posts/run_v7.py')}
            result['environment']={'origin_at_validation':'http://localhost:19099','isolation':'Complete independently owned forum reset required; scripts use initial/final ID sets and scoped test cleanup, not a general agent reset.'}
            result['verifier']={'origin':'project_derived_final_persisted_post','timing':'before_browser_close','version':'final-persisted-post-v3','native_grading':'Separate post-close diagnostic; prior correct publication can survive overwrite in native request-history score.','historical_execution':'Selected cases use multiple pinned driver/checker versions. Current v3 duplicate semantics have a fresh case; other selected outcomes independently replay equivalently.'}
            result['validation_profile'].update(max_steps=24,slow_mo_ms=0)
        elif tid=='407':
            result['policy_input']['terminal_response_instruction']='When finished, call send_msg_to_user with a JSON object containing task_type="mutate", status="SUCCESS" or an applicable failure status, and retrieved_data=null.'
            result['implementation']={'type':'existing_episode_task_with_external_factory','factory':symbol('data.curation.expansion.webarena_votes.run_v2','VoteTask'),'constructor_bindings':{'task':'private contract row','variant':'positive (ordinary verification; not declared outcome)'},'browser_task':symbol('data.curation.expansion.webarena_votes.run_v2','BrowserTask'),'factory_recipe':pin(BASE/'webarena_votes/run_v2.py')}
            result['environment']={'origin_at_validation':'http://localhost:19099','isolation':'Complete independently owned forum reset required; original target neutral and UI-New/publication chronology must agree.'}
            result['verifier']={'origin':'project_derived_scoped_final_vote','timing':'before_browser_close','native_grading':'Separate post-close diagnostic; recorded undo is correctly rejected upstream.'}
            result['validation_profile'].update(max_steps=40,slow_mo_ms=0)
        elif tid in {'689','690','691','692','693'}:
            result['policy_input']['terminal_response_instruction']='When finished, call send_msg_to_user with a JSON object containing task_type="mutate", status="SUCCESS" or an applicable failure status, and retrieved_data=null.'
            result['implementation']={'type':'existing_episode_task_with_external_factory','factory':symbol('data.curation.expansion.webarena_coupon.run_v2','DraftTask'),'constructor_bindings':{'task':'private contract row','variant':'positive (ordinary verification; not declared outcome)','blocked':'same mutable route-event list used by ReadOnlyTask'},'browser_task':symbol('data.curation.expansion.webarena.browser_batch','ReadOnlyTask'),'factory_recipe':pin(BASE/'webarena_coupon/run_v2.py')}
            result['environment']={'origin_at_validation':'http://localhost:7770','isolation':'Fresh context; same-origin GET/HEAD-only route required; do not reset/mutate shared service.'}
            result['verifier']={'origin':'project_derived_final_DOM','timing':'before_browser_close','native_grading':'Not emulated; original dummy-bin checks retained as metadata.'}
            result['validation_profile'].update(max_steps=12,slow_mo_ms=0)
        else:
            site=row['sites'][0];origin={'shopping':'http://localhost:7770','reddit':'http://localhost:18999'}[site]
            result['implementation']={'type':'existing_open_ended_read_only_task','browser_task':symbol('data.curation.expansion.webarena.browser_batch','ReadOnlyTask'),'constructor_bindings':{'start_url':source['start_urls'][0].replace('__'+site.upper()+'__',origin),'goal':'policy_input.goal','blocked':'fresh route-event list'},'episode_task':None}
            result['environment']={'origin_at_validation':origin,'test_account_header_reference':'data.curation.expansion.webarena.browser_batch:HEADERS['+site+']','isolation':'Fresh context with same-origin GET/HEAD-only route; no service writes/reset.'}
            result['verifier']={'origin':'upstream_webarena_verified','version':'1.2.3','task_id':int(tid),'timing':'offline_after_context_close_and_HAR_flush','recording_required':'embedded-content network.har plus exact terminal JSON response','runtime_evaluation':'Unknown; do not label native post-close replay as pre-close runtime evaluation.'}
            reviewed=load(Path(row['review_references'][0]['path']))
            record=next(r for r in reviewed['records'] if r['source_task_id']==tid)
            positive=next(c for c in record['cases'] if c['variant']=='positive')
            case_profile=Path(positive['trace']).parents[1]/'profile.json'
            actual=load(case_profile);cap=actual['max_steps']
            if type(cap) is not int or cap<=0:raise ValueError('Invalid recorded step cap')
            result['validation_profile'].update(max_steps=cap,slow_mo_ms=100,recorded_case_profile=pin(case_profile))
            result['required_preflight'].append('Retain or explicitly amend the recorded max_steps; task batches use different caps.')
        if tid in {'399','400','401','402','403','407','689','690','691','692','693'} or int(tid) in set(range(630,635))|set(range(640,650)):
            result['implementation']['pre_import_runtime_activation']={
                'required':True,'environment_variable':'CURATION_FROZEN_RUNTIME',
                'snapshot_directory':'.local/curation-expansion/frozen-runtime-v1',
                'helper':symbol('data.curation.expansion.runtime_snapshot','activate'),
                'manifest':pin(Path('.local/curation-expansion/frozen-runtime-v1/manifest.json')),
                'timing':'Before importing this factory or any intent_browser module; the adapter asserts activation.',
                'new_runtime_adoption':'A different baseline requires explicit adapter/profile amendment; cannot silently use live checkout.'}
            result['reference_runtime_for_new_offline_profile']['note']='Required pre-import activation for this adapter; historical identity still comes from per-case manifests.'
    policy_projection(result)
    return result


def build(ids=None):
    rows=collect();known={r['id'] for r in rows}
    if ids is not None and set(ids)-known:raise ValueError('Not accepted: '+', '.join(sorted(set(ids)-known)))
    selected=[binding(r) for r in rows if ids is None or r['id'] in ids]
    return {'schema':'expansion-sweep-inputs-v3','scope':'Existing implementation bindings; new execution requires preflight and funding. No inference or service actions performed.',
        'builder':pin(Path(__file__).relative_to(ROOT)),'accepted_index_builder':pin(BASE/'accepted_index.py'),
        'counts':dict(Counter(r['dataset'] for r in selected)),'tasks':selected}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--task',action='append');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    # Reserve before reads; never overwrite an earlier selection.
    with a.output.open('x') as out:
        report=build(a.task);json.dump(report,out,indent=2);out.write('\n')
    print(json.dumps({'output':str(a.output),'counts':report['counts']}))
if __name__=='__main__':main()
