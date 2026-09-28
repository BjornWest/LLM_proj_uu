#!/usr/bin/env python3
"""CPU fixed-suite scheduler/runner/checkpoint/import test; optional W&B readback.

Scripted mock workers, no model/browser inference, no final-test tasks.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from browser_training.evaluation import compare, request
from browser_training.evaluation_runner import run
from browser_training.monitoring_files import atomic_json,exclusive_writer
from browser_training.monitoring_io import credentials_from_project_env,load_wandb_snapshot,scalar_metrics
from browser_training.runtime_metrics import RuntimeMetrics
from browser_training.snapshot_uploader import SnapshotUploader,subprocess_transport


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=ROOT/'outputs/fixed-evaluation')
    p.add_argument('--online',action='store_true')
    a=p.parse_args()
    run_id='fixed-eval-'+uuid.uuid4().hex[:12]
    directory=a.output.resolve()/run_id
    task=dict(task_id='mock',task_family='checkout',task_template='fixture',harness_revision='fixture-h1',
              verifier_revision='fixture-v1',environment_revision='fixture-e1',tokenizer_revision='no-tokenizer',split='rl_train')
    suites=[dict(name=name,split=split,cases=[dict(case_id=case,task_id='mock',task_family='checkout',
        task_template='fixture',task_instance=f'{name}-{case}',seed=i,
        **{k:task[k] for k in ('harness_revision','verifier_revision','environment_revision','tokenizer_revision')})
        for i,case in enumerate(('good','failure'))]) for name,split in [('browser-dev','model_dev'),('generic-dev','generic_eval')]]
    monitor=RuntimeMetrics(directory/'monitor',run_id=run_id,synthetic=True,tasks=[task],
                           expected_producers=['browser','trainer','evaluator'],evaluation_suites=suites,evaluation_interval_episodes=2)
    for name in ('train-a','train-b'):
        monitor.begin(native_group_id=0,episode_id=name,policy_version=3,group_size=2)
        monitor.finish(name,dict(status='completed',goal_completed=True,constraints_satisfied=True,unauthorized_effect=False,reward=1))
    checkpoint=directory/'checkpoint-2';checkpoint.mkdir()
    atomic_json(checkpoint/'rollout_state.json',dict(model_version=3,prompt_index=1))
    monitor.checkpoint(checkpoint)
    jobs=sorted((checkpoint/'monitoring/evaluation-requests').glob('*.json'))
    assert len(jobs)==2
    command=[sys.executable,str(ROOT/'scripts/mock_evaluation_worker.py')]
    # Suites are independent; run both with a shared, small total concurrency of two.
    from concurrent.futures import ThreadPoolExecutor
    def execute(path):
        job=json.loads(path.read_text())
        output=directory/job['suite']['name']
        delivery=run(job,output,command,concurrency=1,timeout_s=10)
        assert run(job,output,command,concurrency=1,timeout_s=10)==delivery
        return job,delivery
    with ThreadPoolExecutor(max_workers=2) as executor:
        completed=list(executor.map(execute,jobs))
    for job,delivery in completed:
        atomic_json(monitor.directory/'evaluation-inbox'/f"{job['evaluation_id']}.json",delivery)
    value=monitor.emit_snapshot()
    assert len(value['evaluations'])==2
    assert all(r['valid_for_comparison'] and r['metrics']['safe_completion']['value']==0.5 for r in value['evaluations'])
    report=dict(status='LOCAL_PASS',run_id=run_id,synthetic=True,model_calls=0,gpu_used=False,
                scheduled_suites=len(jobs),worker_episodes=4,resume_reused_results=True,
                monitoring_import_verified=True,scalar_keys=len(scalar_metrics(value)),
                comparisons_use_exact_suite=True,remote_readback_verified=False)
    if a.online:
        credentials_from_project_env(ROOT.parent)
        destination=f"{os.environ['WANDB_ENTITY']}/{os.environ.get('WANDB_PROJECT','browser-training')}/{run_id}"
        state=directory/'uploader'
        with exclusive_writer(state/'uploader.lock'):
            uploader=SnapshotUploader(state,run_path=destination)
            assert uploader.tick(monitor.directory/'snapshot.json',subprocess_transport)=='confirmed'
        remote,run_remote=load_wandb_snapshot(destination)
        assert remote==value
        for key,expected in scalar_metrics(value).items():
            assert abs(run_remote.summary[key]-expected)<=1e-9*max(1,abs(expected)),key
        report.update(status='PASS',remote_readback_verified=True,url=run_remote.url)
    atomic_json(directory/'report.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
