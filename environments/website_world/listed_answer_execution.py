"""Fresh execution recipes: policy session, close, then one answer extraction.

No backend is opened during preparation. The caller supplies an authorized policy
session whose exit closes every policy bridge/backend and releases its lease.
"""
from copy import deepcopy
from pathlib import Path
import json

from .generation import GeneratedEpisode, load, save
from .generation_configs import provenance, grading_options
from experiments.answer_grading.listed_offer import grade_saved_once, SubscriptionExtractor
from intent_browser.connected_world_task import checked_files, TERMINAL_INSTRUCTION
from intent_browser.runner import run_episode
from .generation_configs import observation_runner_options

VERSION = 'website-listed-answer-execution-v1'


def runtime_options(value=None):
    """Private execution choices; absent settings retain historical startup."""
    if value is None:
        return {'lazy_publication': False}
    if type(value) is not dict or set(value) - {'lazy_publication'}:
        raise ValueError('Unknown runtime execution option')
    lazy = value.get('lazy_publication', False)
    if type(lazy) is not bool:
        raise ValueError('lazy_publication must be a bool')
    return {'lazy_publication': lazy}


def options(value=None):
    return grading_options(value)


def run(output, run_directory, *, policy_session, metadata, runner_options,
        extraction_backend_factory=None, runner=run_episode):
    """Run an authorized bounded episode, then grade only after session exit.

    The extraction backend factory is a testing/dedicated-transport override.
    Policy summary/evaluation stay unchanged; derived grade lives in a sidecar.
    Reusing a run directory is rejected before either backend can be opened.
    """
    runner_options = observation_runner_options(runner_options)
    output, destination = Path(output).resolve(), Path(run_directory).resolve()
    manifest = load(output)
    record = json.loads((output/'execution.private.json').read_text())
    grading = options(record.get('answer_grading'))
    runtime = runtime_options(record.get('runtime_options'))
    if type(runner_options) is not dict:
        raise ValueError('Supply bounded runner options')
    for key in ('max_steps', 'max_input_tokens'):
        if type(runner_options.get(key)) is not int or runner_options[key] <= 0:
            raise ValueError('Execution requires explicit positive ' + key)
    if set(runner_options) & {'env_factory', 'backend', 'metadata', 'output', 'episode_task', 'harness_profile', 'site_discovery'}:
        raise ValueError('Runner options cannot override episode bindings')
    if grading['mode'] == 'off' and extraction_backend_factory is not None:
        raise ValueError('Extraction backend configured with grading disabled')
    destination.mkdir(parents=True, exist_ok=False)
    save(destination/'execution-plan.private.json', {'schema': VERSION, 'answer_grading': grading,
        'generation': provenance(output),
        'runtime_options': runtime,
        'runner_options': runner_options, 'source_sha256': manifest['source_sha256'],
        'requests_max': 1 if grading['mode'] != 'off' else 0, 'automatic_grading_retries': 0})
    with GeneratedEpisode(output, **runtime) as episode:
        if grading['mode'] != 'off' and episode.answer_grader is None:
            raise ValueError('Post-run grading requires a supported native listed-offer task')
        episode.export_private_runtime(destination/'runtime-binding')
        # An unsupported task is rejected before opening the policy session.
        with policy_session() as backend:
            invocation = {'terminal_response_instruction': TERMINAL_INSTRUCTION, **runner_options}
            trace, summary = runner(episode.task.make_env, backend, metadata,
                output=destination/'runs', episode_task=episode.task, harness_profile=episode.profile,
                site_discovery=episode.site_discovery, **invocation)
        # Exiting the caller-owned session must close the HTTP facade/server and
        # subscription backend. Only now may a grading backend acquire that lease.
        save(destination/'policy-result.json', {'trace': str(trace), 'summary': summary})
        checked_files(episode.task.files)
        stage = {'mode': grading['mode'], 'status': 'disabled', 'task_completed': None}
        if grading['mode'] != 'off':
            factory = extraction_backend_factory
            if factory is None:
                factory = SubscriptionExtractor(model=grading['model'],
                         reasoning_effort=grading['reasoning_effort']).backend
            try:
                if summary.get('error') or summary.get('cleanup_errors'):
                    stage.update(status='skipped', reason='Policy execution or cleanup failed')
                else:
                    grade = grade_saved_once(trace=trace, world=output/'pin/world.private.json',
                        task=output/'basic-offer-task.private.json',
                        reference=output/'basic-offer-reference.private.json',
                        bindings=destination/'runtime-binding/bindings.private.json',
                        output=destination/'answer-grading', backend_factory=factory,
                        surrounding=output/'surrounding.private.json'
                        if (output/'surrounding.private.json').exists() else None)
                    stage.update(status='graded' if grade is not None else 'skipped',
                                 task_completed=grade['structured_claims_correct'] if grade is not None else None)
            except Exception as error:
                stage.update(status='failed', error_type=type(error).__name__, reason=str(error), automatic_retries=0)
        result = {'schema': VERSION, 'trace': str(trace), 'policy_summary': summary, 'answer_grading': stage}
        save(destination/'execution-result.json', result)
        return result
