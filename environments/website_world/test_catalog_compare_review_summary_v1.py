"""Frozen runner/Trace.finish source-shape controls; no browser or provider."""
import ast
from copy import deepcopy
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from environments.website_world.catalog_compare_review_execution import check_policy_outcome


def summaries(tmp_path):
    fixture = json.loads((Path(__file__).with_name('fixtures') /
        'composite_frozen_summary_schema_v1.json').read_bytes())
    declaration = ast.parse(fixture['runner_summary_assignment']).body[0]
    assert [target.id for target in declaration.targets] == ['summary']
    keys = {node.value for node in declaration.value.keys}
    assert 'trace_complete' not in keys
    returned = {key: None for key in keys}
    returned.update(stop_reason='agent_finished', error=None, execution_error=None,
                    cleanup_errors=[], terminated=False, truncated=False)
    # Execute the exact retained Trace.finish body against file-only controls.
    # It replaces its local summary, leaving the runner's return dict unchanged.
    namespace = {'write_json': lambda path, value: path.write_text(json.dumps(value))}
    exec(compile(fixture['trace_finish_function'], '<frozen-trace-finish-control>', 'exec'), namespace)
    trace = SimpleNamespace(writer=None, directory=tmp_path, metadata={},
        events=io.StringIO(), lifecycle=io.StringIO(), event=lambda *a, **kw: None,
        timings=SimpleNamespace(enabled=False))
    namespace['finish'](trace, returned)
    saved = json.loads((tmp_path/'episode.json').read_bytes())
    assert 'trace_complete' not in returned and saved['trace_complete'] is True
    return returned, saved


def test_frozen_success_return_omits_field_added_by_actual_trace_finish(tmp_path):
    returned, saved = summaries(tmp_path)
    before = deepcopy((returned, saved))
    check_policy_outcome(returned, saved)
    assert (returned, saved) == before
    check_policy_outcome({**returned, 'trace_complete': True}, saved)


def test_prospective_consumer_finalizes_once_with_missing_returned_field(tmp_path, monkeypatch):
    from environments.website_world import catalog_compare_review_execution as execution
    from environments.website_world.test_catalog_compare_review_consumers import run_fixture
    output, events, options = run_fixture(tmp_path, monkeypatch)
    original_runner = options['runner']
    def runner(*args, **kwargs):
        trace, returned = original_runner(*args, **kwargs)
        return trace, {key: value for key, value in returned.items() if key != 'trace_complete'}
    options['runner'] = runner
    result = execution.run(output, tmp_path/'run', **options)
    assert result['status'] == 'graded_and_projected' and result['task_completed']
    assert events.count('compound-grade') == 1
    assert events.index('policy-close') < events.index('runtime-close') < events.index('compound-grade')


@pytest.mark.parametrize('value', [False, None, 1, 'true'])
def test_explicit_returned_incompleteness_is_rejected(tmp_path, value):
    returned, saved = summaries(tmp_path)
    with pytest.raises(ValueError, match='incomplete'):
        check_policy_outcome({**returned, 'trace_complete': value}, saved)


@pytest.mark.parametrize('fault', ['missing', 'false', 'null', 'recording_error'])
def test_saved_recording_must_have_explicit_success(tmp_path, fault):
    returned, saved = summaries(tmp_path)
    if fault == 'missing': saved.pop('trace_complete')
    elif fault == 'false': saved['trace_complete'] = False
    elif fault == 'null': saved['trace_complete'] = None
    else: saved['recording_error'] = 'writer failed'
    with pytest.raises(ValueError, match='incomplete'):
        check_policy_outcome(returned, saved)


@pytest.mark.parametrize('key,value', [('stop_reason', 'max_steps'),
    ('error', 'failure'), ('execution_error', 'failed action'),
    ('cleanup_errors', ['failed close'])])
def test_error_cleanup_and_stop_reason_drift_still_reject(tmp_path, key, value):
    returned, saved = summaries(tmp_path)
    with pytest.raises(ValueError, match='differs'):
        check_policy_outcome({**returned, key: value}, saved)
