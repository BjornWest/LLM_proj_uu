"""Bind batch03 evidence without promoting scripted results to task admission."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / '.local/expansion-webarena'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(output):
    output.mkdir(parents=True, exist_ok=False)
    contracts = read(BASE/'batch03-plan-v1/contracts.json')
    selected = {}
    files = set()
    for browser_name, grade_name in [
        ('batch03-frozen-pairs-v3', 'batch03-frozen-grade-error-aware-v2'),
        ('batch03-frozen-comment-v4', 'batch03-frozen-comment-grade-v4')]:
        browser_path=BASE/browser_name/'report.json';grade_path=BASE/grade_name/'report.json'
        browser=read(browser_path);grades=read(grade_path)
        grade_map={(g['task_id'],g['variant']):g for g in grades['cases']}
        files.update([browser_path,grade_path])
        for case in browser['tasks']:
            if case['task_id']==28 and browser_name=='batch03-frozen-pairs-v3':
                continue  # Retained failed development pair, replaced by explicit corrected pair.
            key=(case['task_id'],case['variant']);grade=grade_map[key]
            trace=ROOT/case['trace'];folder=trace.parent.parent
            before=read(folder/'source-before.json');after=read(folder/'source-after.json')
            assert before==after and case['source_unchanged']
            assert case['scripted_path_completed'] and case['delivery_aligned']
            profile=read(folder/'profile.json')
            assert profile['frozen_runtime'].endswith('/frozen-runtime-v1')
            loaded=read(trace/'metadata.json')['runtime']['source_sha256']
            pins=read(ROOT/'.local/curation-expansion/frozen-runtime-v1/manifest.json')['source_sha256']
            assert loaded=={Path(k).name:v for k,v in pins.items()}
            selected[key]={'variant':case['variant'],'trace':case['trace'],
                'browser_report':str(browser_path.relative_to(ROOT)),
                'native_report':str(grade_path.relative_to(ROOT)),
                'profile':str((folder/'profile.json').relative_to(ROOT)),
                'source_unchanged':True,'actual_loaded_snapshot_matches':True,
                'harness_profile':profile['harness']['name'],
                'observation_characters':profile['observation_chars'],
                'action_error_count':case['summary']['action_error_count'],
                'native_status':grade['native_result']['status'],
                'native_score':grade['native_result']['score'],
                'native_grader_error':grade['native_grader_error'],
                'native_matches_intended':grade['native_matches_intended']}
    blocked={124:('blocked_answer_scope_validation','Ordinary search returns unrelated products; derived maximum is not the requested product-family range.'),
        269:('blocked_scripted_navigation','Requested under-$25 control not reached; first development menu click also exceeded the150s bound.'),
        313:('blocked_negative_grader_error_and_absence_scope','Negative nonnull answer triggers native null-schema exception; contact-page-only inspection does not prove site-wide absence.'),
        319:('blocked_native_response_normalization','Source omits expected retrieved_data; native actual normalization drops the key and rejects tested NOT_FOUND answers.'),
        351:('blocked_native_route_coverage','Native checker rejects sidebar-filter URL; both routes have identical228 ordered products in separate GET-only comparison.')}
    flags={118:['Privileged script chooses a mouth-guard product by title; no medical efficacy evaluation.'],
        226:['Brand membership uses title prefix and excludes another-brand bundles; semantic coverage needs review.'],
        69:['Domain is printed in the post title, not body prose; original wording says post description.'],
        334:['ISO-format date is accepted by native normalization despite US-format expected source value.']}
    tasks=[]
    for contract in contracts:
        task_id=int(contract['source_task_id'])
        cases=[selected[k]for k in [(task_id,'positive'),(task_id,'negative')]if k in selected]
        audit=list(flags.get(task_id,[]))
        if task_id in blocked:
            status,note=blocked[task_id];audit.append(note)
        else:
            assert len(cases)==2 and all(c['native_matches_intended'] is True for c in cases)
            status='scripted_pair_with_action_warnings' if any(c['action_error_count'] for c in cases) else 'scripted_pair_validated_pending_review'
        tasks.append({'source':contract['source'],'source_task_id':str(task_id),
            'source_template_id':contract['template_id'],'source_revision':contract['source_revision'],
            'site_ids':contract['site_ids'],'original_goal':contract['policy_input']['goal'],
            'status':status,'audit_flags':audit,'cases':cases,
            'independent_acceptance':None,'training_ready':False,'authorization_satisfied':None,'safe_success':None})
    evidence_dirs=['batch03-plan-v1','batch03-development-positive-v1','batch03-development-positive-grade-v1',
        'batch03-corrections-positive-v2','batch03-corrections-positive-grade-v2','batch03-frozen-pairs-v3',
        'batch03-frozen-grade-v3','batch03-frozen-grade-error-aware-v2','batch03-frozen-comment-v4',
        'batch03-frozen-comment-grade-v4','batch03-source-v1','batch03-source-v2','batch03-source-v3','batch03-source-v4',
        'task319-native-normalization-defect-v1','task351-route-equivalence-v1',
        'source-kind-permission-cautions-v1','batch03-query-recon-v1','batch03-query-recon-v2']
    for name in evidence_dirs:
        files.update(p for p in (BASE/name).rglob('*') if p.is_file())
    files.update([Path(__file__),ROOT/'data/curation/expansion/webarena/grade_browser_pairs_v2.py',
        ROOT/'.local/curation-expansion/infrastructure/reddit-reset-for-batch3.json'])
    result={'schema':'webarena-expansion-batch03-review-v1','source_task_ids':len(tasks),
        'source_templates':len({t['source_template_id'] for t in tasks}),'new_source_templates':10,
        'site_contexts':2,'selected_browser_cases':len(selected),'all_development_and_closure_browser_attempts':60,
        'counts_by_status':dict(Counter(t['status']for t in tasks)),
        'network_model_calls':0,'independently_accepted':0,'training_ready':0,
        'scope':'New original tasks;15shopping/5forum. Actual pinned snapshot, not current active harness. Raw errors and historical source versions retained.',
        'tasks':tasks,'artifact_sha256':{str(p.relative_to(ROOT)):sha(p)for p in sorted(files)},
        'notes':['Native grader errors never count as successful negative rejection; v1 helper diagnostic is superseded by v2 producer, not rewritten.',
                 'Task28 has a separate corrected comment-counting source version; no uniform whole-driver source claim.',
                 'Snapshot runtime hashes match in all32 selected cases. All browser cases are scripted, with privileged DOM assistance.',
                 'No mutation in batch03; isolated Reddit reset proof precedes final forum cases.']}
    (output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k]for k in ['source_task_ids','source_templates','selected_browser_cases','counts_by_status']}))
    print('Artifact hashes:',len(files))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    build(parser.parse_args().output)
