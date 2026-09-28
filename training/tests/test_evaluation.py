from copy import deepcopy
import json
from pathlib import Path
import sys
import time

import pytest

from browser_training.evaluation import (EvaluationSchedule, case_event, compare, evaluation_event,
                                         request, summarize_evaluations, validate_suite)
from browser_training.evaluation_runner import run
from browser_training.monitoring_io import scalar_metrics
from browser_training.runtime_metrics import RuntimeMetrics
from test_runtime_metrics import TASK, GOOD, begin


def suite(ids=('good','failure'), split='model_dev'):
    return dict(name='fixed-browser', split=split, cases=[dict(case_id=name, task_id='mock',
        task_family='checkout',task_template='no-extras',task_instance=f'fixed-{name}',seed=i,
        harness_revision='h1',verifier_revision='v1',environment_revision='e1',tokenizer_revision='fixture')
        for i,name in enumerate(ids)])


def job(s=None, version=1):
    return request(s or suite(),checkpoint_id=f'checkpoint-{version}',policy_version=version,
                   publication_run_id='test',completed_training_episodes=1000,trigger_count=1000)


def episodes(j, outcomes=None):
    return [case_event(j,case,(outcomes or [GOOD]*len(j['suite']['cases']))[i],occurred_at=100+i)
            for i,case in enumerate(j['suite']['cases'])]


def test_fixed_suite_excludes_final_and_duplicate_instances():
    with pytest.raises(ValueError,match='sealed'):
        validate_suite(suite(split='final_test'))
    s=suite();s['cases'][1]['task_instance']=s['cases'][0]['task_instance'];s['cases'][1]['seed']=0
    with pytest.raises(ValueError,match='Duplicate evaluation instance'):
        validate_suite(s)


def test_reports_are_checkpoint_specific_and_invalid_runs_cannot_rank(tmp_path):
    monitor=RuntimeMetrics(tmp_path/'metrics',run_id='test',synthetic=True,expected_producers=['evaluator'])
    j=job();es=episodes(j)
    delivery=dict(episodes=es,report=evaluation_event(j,es,occurred_at=103))
    monitor.import_evaluation(delivery);monitor.import_evaluation(delivery)
    value=monitor.emit_snapshot()
    assert value['watermark']==3
    first=value['evaluations'][0]
    assert first['metrics']['safe_completion']['value']==1
    j2=job(version=2)
    bad={**GOOD,'goal_completed':False,'reward':0}
    es=episodes(j2,[GOOD,bad]);monitor.import_evaluation(dict(episodes=es,report=evaluation_event(j2,es,occurred_at=104)))
    value=monitor.emit_snapshot();second=value['evaluations'][1]
    assert compare(first,second)['paired_safe_completion_delta']==-0.5
    assert scalar_metrics(value)['evaluation/fixed-browser/safe_completion/value']==0.5
    j3=job(version=3);unknown={**GOOD,'goal_completed':None,'reward':None}
    es=episodes(j3,[GOOD,unknown]);report=evaluation_event(j3,es,occurred_at=105)
    third=summarize_evaluations([*es,report])[0]
    with pytest.raises(ValueError,match='verification'):
        compare(first,third)
    changed=deepcopy(second);changed['suite_revision']='different'
    with pytest.raises(ValueError,match='identical'):
        compare(first,changed)


def test_wrong_policy_missing_cases_and_old_execution_rejected(tmp_path):
    j=job();es=episodes(j)
    with pytest.raises(ValueError,match='Incomplete'):
        evaluation_event(j,es[:1],occurred_at=104)
    es[0]['payload']['policy_version']=9
    with pytest.raises(ValueError,match='policy mismatch'):
        evaluation_event(j,es,occurred_at=104)
    monitor=RuntimeMetrics(tmp_path,run_id='other',synthetic=True)
    es=episodes(j)
    with pytest.raises(ValueError,match='another execution'):
        monitor.import_evaluation(dict(episodes=es,report=evaluation_event(j,es,occurred_at=104)))
    assert monitor.ledger.watermark()==0


def test_schedule_at_checkpoint_persists_and_does_not_duplicate_on_restore(tmp_path):
    monitor=RuntimeMetrics(tmp_path/'m',run_id='test',synthetic=True,tasks=[TASK],
                           evaluation_suites=[suite()],evaluation_interval_episodes=2)
    for name in ('a','b'):
        begin(monitor,name);monitor.finish(name,GOOD)
    cp=tmp_path/'checkpoint-1';cp.mkdir();(cp/'rollout_state.json').write_text(json.dumps(dict(model_version=3,prompt_index=1)))
    state=monitor.checkpoint(cp)
    jobs=list((cp/'monitoring/evaluation-requests').glob('*.json'))
    assert len(jobs)==1 and state['evaluation_schedule']['last_boundary']==2
    resumed=RuntimeMetrics(tmp_path/'resumed',run_id='test',synthetic=True,tasks=[TASK],resume=cp,
                           evaluation_suites=[suite()],evaluation_interval_episodes=2)
    cp2=tmp_path/'checkpoint-2';cp2.mkdir();(cp2/'rollout_state.json').write_text(json.dumps(dict(model_version=3,prompt_index=1)))
    resumed.checkpoint(cp2)
    assert not list((cp2/'monitoring/evaluation-requests').glob('*.json'))
    with pytest.raises(ValueError,match='schedule changed'):
        RuntimeMetrics(tmp_path/'wrong',run_id='test',synthetic=True,tasks=[TASK],resume=cp,
                       evaluation_suites=[suite()],evaluation_interval_episodes=4)


def test_parallel_worker_errors_and_restart_preserve_results(tmp_path):
    j=job(suite(('good','failure','unknown','error')))
    command=[sys.executable,str(Path(__file__).resolve().parents[1]/'scripts/mock_evaluation_worker.py')]
    first=run(j,tmp_path/'eval',command,concurrency=2,timeout_s=5)
    assert [e['payload']['status'] for e in first['episodes']]==['completed']*3+['infra_error']
    assert not summarize_evaluations([*first['episodes'],first['report']])[0]['valid_for_comparison']
    assert run(j,tmp_path/'eval',command,concurrency=2,timeout_s=5)==first
    with pytest.raises(ValueError,match='contract changed'):
        run(j,tmp_path/'eval',command,concurrency=1,timeout_s=5)


def test_worker_timeout_is_infrastructure_error_and_does_not_retry(tmp_path):
    command=[sys.executable,'-c','import time; time.sleep(10)']
    value=run(job(suite(('timeout',))),tmp_path/'timeout',command,timeout_s=0.05)
    assert value['episodes'][0]['payload']['status']=='infra_error'
    assert value['episodes'][0]['payload']['reward'] is None
    assert run(job(suite(('timeout',))),tmp_path/'timeout',command,timeout_s=0.05)==value


def test_explicit_repetition_keeps_suite_comparable_without_overwriting_attempts():
    first=job()
    second=request(first['suite'],checkpoint_id=first['checkpoint_id'],policy_version=first['policy_version'],
                   publication_run_id='test',completed_training_episodes=1000,trigger_count=1000,repetition=1)
    assert first['suite_revision']==second['suite_revision']
    assert first['evaluation_id']!=second['evaluation_id']


def test_scheduled_checkpoints_cannot_be_pruned_before_evaluation():
    from browser_training.evaluation import validate_checkpoint_retention
    validate_checkpoint_retention(False, 3)
    validate_checkpoint_retention(True, None)
    with pytest.raises(ValueError,match='pruning'):
        validate_checkpoint_retention(True, 3)
