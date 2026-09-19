import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from intent_browser.evaluation import Evaluation
from intent_browser.task_finalization import finalize_task_run

def fixture(tmp_path, closed=True):
    runtime=Evaluation('runtime','1',limitations=['Waiting for HAR flush']).to_dict()
    (tmp_path/'evaluation.json').write_text(json.dumps(runtime))
    (tmp_path/'episode.json').write_text(json.dumps({'evaluation':runtime}))
    (tmp_path/'events.jsonl').write_text(json.dumps({'event':'environment_close_completed' if closed else 'evaluation_completed'})+'\n')
    return {p.name:p.read_bytes() for p in tmp_path.iterdir()}

def test_post_close_is_distinct_and_does_not_rewrite_runtime(tmp_path):
    old=fixture(tmp_path)
    def grade(directory,summary):
        assert directory==tmp_path
        assert 'environment_close_completed' in (directory/'events.jsonl').read_text()
        summary['evaluation']='must not alter caller'
        return Evaluation('native-HAR','1',task_completed=True,authorization_satisfied=None,evidence=['page.har'])
    summary={'error':None,'evaluation':'unknown'}
    r=finalize_task_run(SimpleNamespace(grading_phase='after_browser_close',finalize_after_close=grade),tmp_path,summary)
    assert r['evaluation']['task_completed'] is True and r['evaluation']['safe_success'] is None
    assert summary['evaluation']=='unknown'
    assert all((tmp_path/name).read_bytes()==raw for name,raw in old.items())
    with pytest.raises(FileExistsError):finalize_task_run(SimpleNamespace(),tmp_path,summary)

@pytest.mark.parametrize('failure',['missing_close','missing_har','invalid_result'])
def test_post_close_failure_never_promotes_runtime(tmp_path,failure):
    fixture(tmp_path,closed=failure!='missing_close');calls=[]
    def grade(*args):
        calls.append(1)
        if failure=='missing_har':raise FileNotFoundError('HAR missing')
        return {'task_completed':True}
    r=finalize_task_run(SimpleNamespace(grading_phase='after_browser_close',finalize_after_close=grade),tmp_path,{'error':None})
    assert r['evaluation']['safe_success'] is None and r['evaluation']['task_completed'] is None and r['evaluation']['technical_error']
    assert bool(calls)==(failure!='missing_close')

def test_technical_error_preserves_independent_result_but_not_safe_success(tmp_path):
    fixture(tmp_path)
    r=finalize_task_run(SimpleNamespace(grading_phase='after_browser_close',finalize_after_close=lambda *args:Evaluation('native','1',task_completed=True,authorization_satisfied=True)),tmp_path,{'error':'Model timeout'})
    assert r['evaluation']['task_completed'] is True and r['evaluation']['authorization_satisfied'] is True
    assert r['evaluation']['safe_success'] is None and r['evaluation']['technical_error']=='Model timeout'

def test_before_close_uses_existing_evaluation_without_invoking_late_hook(tmp_path):
    fixture(tmp_path)
    r=finalize_task_run(SimpleNamespace(finalize_after_close=lambda *a:pytest.fail('Unexpected late grader')),tmp_path,{'error':None})
    assert r['grading_phase']=='before_browser_close'
    assert r['evaluation']==json.loads((tmp_path/'evaluation.json').read_text())
