"""Fixed held-out suite accounting and checkpoint-triggered requests, CPU only.

This does not generate model responses, allocate hardware, or implement RL.
Environment/model runners supply outcome events against the immutable request.
"""
import hashlib
import json
from pathlib import Path
import re

from .outcomes import canonical, fields, number, require, safe, reduce_cohort

PROVENANCE = ('harness_revision', 'verifier_revision', 'environment_revision', 'tokenizer_revision')


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def validate_suite(suite):
    fields(suite, {'name', 'split', 'cases'})
    require(isinstance(suite['name'], str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', suite['name']), 'Invalid suite name')
    require(suite['split'] in {'model_dev', 'generic_eval'}, 'Scheduled evaluation must exclude train and sealed final test')
    require(isinstance(suite['cases'], list) and 0 < len(suite['cases']) <= 1000, 'Suite needs 1..1000 cases')
    identities = set()
    instances = set()
    for case in suite['cases']:
        fields(case, {'case_id', 'task_id', 'task_family', 'task_template', 'task_instance', 'seed', *PROVENANCE})
        for key in case.keys() - {'seed'}:
            require(isinstance(case[key], str) and case[key], f'Case {key} required')
        number(case['seed'], 'seed', integer=True)
        require(case['case_id'] not in identities, 'Duplicate evaluation case')
        identity = case['environment_revision'], case['task_instance'], case['seed']
        require(identity not in instances, 'Duplicate evaluation instance')
        identities.add(case['case_id'])
        instances.add(identity)
    require(len({case['tokenizer_revision'] for case in suite['cases']}) == 1, 'One tokenizer per suite')
    return suite


def request(suite, *, checkpoint_id, policy_version, publication_run_id, completed_training_episodes, trigger_count, repetition=0):
    validate_suite(suite)
    for key, value in (('checkpoint_id', checkpoint_id), ('publication_run_id', publication_run_id)):
        require(isinstance(value, str) and value, f'{key} required')
    number(policy_version, 'policy_version', integer=True)
    number(completed_training_episodes, 'completed_training_episodes', integer=True)
    number(trigger_count, 'trigger_count', integer=True)
    number(repetition, 'repetition', integer=True)
    value = dict(schema_version=1, suite=suite, suite_revision=digest(suite), checkpoint_id=checkpoint_id,
                 policy_version=policy_version, publication_run_id=publication_run_id,
                 completed_training_episodes=completed_training_episodes, trigger_count=trigger_count, repetition=repetition)
    return {**value, 'evaluation_id': digest(value)}


def validate_request(value):
    fields(value, {'schema_version', 'suite', 'suite_revision', 'checkpoint_id', 'policy_version',
                   'publication_run_id', 'completed_training_episodes', 'trigger_count', 'repetition', 'evaluation_id'})
    require(value['schema_version'] == 1, 'Unknown evaluation request schema')
    expected = request(value['suite'], **{k: value[k] for k in ('checkpoint_id', 'policy_version',
        'publication_run_id', 'completed_training_episodes', 'trigger_count', 'repetition')})
    require(value == expected, 'Evaluation request checksum mismatch')
    return value


def evaluation_event(job, episodes, *, occurred_at):
    validate_request(job)
    require(len(episodes) == len(job['suite']['cases']), 'Incomplete evaluation: retain partial results, do not publish a pass rate')
    ids = [e['id'] for e in episodes]
    require(len(set(ids)) == len(ids), 'Duplicate evaluation event')
    value = dict(id='evaluation-' + job['evaluation_id'], kind='evaluation', producer='evaluator',
                 occurred_at=occurred_at, payload=dict(request=job, episode_ids=ids))
    validate_report(value['payload'], episodes)
    return value


def validate_report(payload, episodes=None):
    fields(payload, {'request', 'episode_ids'})
    job = validate_request(payload['request'])
    ids = payload['episode_ids']
    require(isinstance(ids, list) and len(ids) == len(job['suite']['cases']) and
            all(isinstance(i, str) and i for i in ids) and len(set(ids)) == len(ids), 'Invalid evaluation episode list')
    if episodes is None:
        return
    by_id = {e['id']: e for e in episodes if e['kind'] == 'episode'}
    require(set(ids) <= by_id.keys(), 'Evaluation references missing episode events')
    for case, identity in zip(job['suite']['cases'], ids):
        event = by_id[identity]
        p = event['payload']
        require(all(p[k] == case[k] for k in ('task_family', 'task_template', 'task_instance', 'seed', *PROVENANCE)),
                'Evaluation case/provenance mismatch')
        require(p['group_id'] == f"eval:{job['evaluation_id']}:{case['case_id']}" and p['group_size'] == 1
                and p['member'] == 0 and p['attempt'] == 0, 'Evaluation must use one prespecified attempt per case')
        require(p['policy_version'] == job['policy_version'] and p['split'] == job['suite']['split'],
                'Evaluation split or checkpoint policy mismatch')
        require(event['producer'] == 'evaluator', 'Evaluation outcomes must name the evaluator producer')


def case_event(job, case, outcome, *, occurred_at, trace_ref=None, generated_tokens=None, duration_s=None, steps=None):
    from .outcomes import validate
    fields(outcome, {'status', 'goal_completed', 'constraints_satisfied', 'unauthorized_effect', 'reward'})
    validate_request(job)
    require(case in job['suite']['cases'], 'Case not in fixed suite')
    identity = f"eval:{job['evaluation_id']}:{case['case_id']}"
    p = {k: case[k] for k in ('task_family', 'task_template', 'task_instance', 'seed', *PROVENANCE)}
    p.update(episode_id=identity, group_id=identity, group_size=1, member=0, attempt=0,
             split=job['suite']['split'], policy_version=job['policy_version'], **outcome,
             trace_ref=trace_ref, generated_tokens=generated_tokens, duration_s=duration_s, steps=steps)
    event = dict(id='finish-' + identity, kind='episode', producer='evaluator', occurred_at=occurred_at, payload=p)
    validate(event)
    return event


def summarize_evaluations(events):
    reports = []
    for event in events:
        if event['kind'] != 'evaluation':
            continue
        p = event['payload']
        validate_report(p, events)
        job = p['request']
        by_id = {e['id']: e['payload'] for e in events if e['kind'] == 'episode'}
        cases = [by_id[identity] for identity in p['episode_ids']]
        cohort = reduce_cohort(cases, cases, {})
        valid = all(case['status'] == 'completed' and safe(case) is not None for case in cases)
        reports.append(dict(evaluation_id=job['evaluation_id'], suite_name=job['suite']['name'],
                            suite_revision=job['suite_revision'], split=job['suite']['split'],
                            checkpoint_id=job['checkpoint_id'], policy_version=job['policy_version'],
                            publication_run_id=job['publication_run_id'], occurred_at=event['occurred_at'],
                            expected_cases=len(cases), valid_for_comparison=valid,
                            metrics=cohort['metrics'], cases={case['case_id']: row for case, row in zip(job['suite']['cases'], cases)}))
    return sorted(reports, key=lambda r: (r['occurred_at'], r['evaluation_id']))


def compare(left, right):
    require(left['suite_revision'] == right['suite_revision'] and left['split'] == right['split'],
            'Compare the identical fixed suite and split')
    require(left['valid_for_comparison'] and right['valid_for_comparison'],
            'Incomplete verification or infrastructure errors: no checkpoint ranking')
    pairs = [(safe(left['cases'][key]), safe(right['cases'][key])) for key in left['cases']]
    wins = sum(not a and b for a, b in pairs)
    losses = sum(a and not b for a, b in pairs)
    return dict(left_checkpoint=left['checkpoint_id'], right_checkpoint=right['checkpoint_id'],
                cases=len(pairs), improved= wins, regressed=losses, unchanged=len(pairs)-wins-losses,
                paired_safe_completion_delta=(wins-losses)/len(pairs),
                note='Descriptive paired difference; no significance or automatic best-checkpoint claim.')


class EvaluationSchedule:
    def __init__(self, suites, interval_episodes=1000):
        number(interval_episodes, 'interval_episodes', integer=True)
        require(interval_episodes > 0, 'Positive evaluation interval required')
        self.suites = json.loads(canonical([validate_suite(s) for s in suites]))
        require(len({s['name'] for s in suites}) == len(suites), 'Unique suite names required')
        self.interval = interval_episodes
        self.last_boundary = 0

    def state_dict(self):
        return dict(suites=self.suites, interval_episodes=self.interval, last_boundary=self.last_boundary)

    def restore(self, state):
        require(state['suites'] == self.suites and state['interval_episodes'] == self.interval,
                'Evaluation suite/schedule changed across resume')
        number(state['last_boundary'], 'last_boundary', integer=True)
        self.last_boundary = state['last_boundary']

    def at_checkpoint(self, events, *, checkpoint_id, policy_version, publication_run_id):
        latest = {}
        for event in events:
            if event['kind'] == 'episode' and event['payload']['split'] == 'rl_train':
                p = event['payload']
                key = p['group_id'], p['member']
                if key not in latest or p['attempt'] > latest[key]['attempt']:
                    latest[key] = p
        count = sum(p['status'] == 'completed' for p in latest.values())
        boundary = count // self.interval * self.interval
        if boundary <= self.last_boundary:
            return []
        # If several boundaries elapsed before a saved checkpoint, evaluate it once.
        jobs = [request(suite, checkpoint_id=checkpoint_id, policy_version=policy_version,
                        publication_run_id=publication_run_id, completed_training_episodes=count,
                        trigger_count=boundary) for suite in self.suites]
        self.last_boundary = boundary
        return jobs


def validate_checkpoint_retention(evaluation_enabled, save_total_limit):
    require(not evaluation_enabled or save_total_limit in (None, 0),
            'Fixed evaluation requests live beside checkpoints: disable automatic checkpoint pruning until an explicit retention policy is qualified')
