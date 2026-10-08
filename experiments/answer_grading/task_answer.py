"""Task-specific formatting over shared once-only extraction/publication machinery.

Grader semantics stay native and private. Task-specific instructions describe
field interpretation, never expected values. Old listed-offer prompts are unchanged.
"""
from copy import deepcopy
import json
from pathlib import Path

from . import listed_offer

VERSION = 'website-task-answer-execution-v1'


def messages(public, answer, schema, *, instructions):
    if type(answer) is not str or not answer.strip():
        raise ValueError('A natural final answer is required')
    if type(instructions) is not str or not instructions.strip():
        raise ValueError('Missing task-specific extraction instructions')
    task = {k: deepcopy(public[k]) for k in ('user_message', 'memories', 'environment_context') if k in public}
    return [{'role': 'system', 'content': instructions + '\n\nOUTPUT JSON SCHEMA:\n' +
             json.dumps(schema, ensure_ascii=False, sort_keys=True)},
            {'role': 'user', 'content': json.dumps({'public_task': task, 'final_answer': answer}, ensure_ascii=False)}]


def extract_and_grade(grader, public, answer, output, backend, *, before_dispatch=lambda: None):
    instructions = grader.extraction_instructions
    return listed_offer.extract_and_grade(grader, public, answer, output, backend,
        before_dispatch=before_dispatch,
        message_builder=lambda public, answer, schema: messages(public, answer, schema, instructions=instructions))


def grade_saved_once(*, trace, inputs, output, grader_factory, backend_factory,
                     source_paths, before_model_dispatch=lambda: None):
    """One complete saved episode; caller selects its registered native grader.

    inputs is name->JSON path; all source_paths and inputs are pinned before the
    grader/backend are constructed. Caller owns the source closure and factory.
    Only public task/final answer/schema/instructions reach the formatter. Output
    is an exclusive claim, including failures: there is no implicit replay/retry.
    """
    from scripts.trace_grades import BOUND_FILES
    from . import extraction
    trace, output = Path(trace).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    paths = [trace/name for name in BOUND_FILES]
    paths += [Path(p).resolve() for p in inputs.values()]
    paths += [Path(p).resolve() for p in source_paths]
    paths += [Path(module.__file__).resolve() for module in (listed_offer, extraction)]
    paths.append(Path(__file__).resolve())
    hashes = {str(p): listed_offer.sha(p) for p in paths}

    def checked():
        for name, expected in hashes.items():
            if listed_offer.sha(name) != expected:
                raise ValueError('Task grading input/source changed: '+name)

    read = lambda p: json.loads(Path(p).read_text())
    natural = read(trace/'natural-answer.json')
    if natural.get('stop_reason') != 'agent_finished' or natural.get('technical_error') or not natural.get('text'):
        listed_offer.write(output/'skipped.json', {'reason': 'No complete uninterrupted final answer', 'requests': 0})
        return None
    listed_offer.write(output/'source-hashes.json', hashes)
    grader = grader_factory(**{name: read(p) for name, p in inputs.items()})
    public = read(trace/'policy-task.json')
    # Grade the pinned structured task; edited public phrasing is not a new
    # task. The formatter still receives the actual observed request below.
    # Older ID-less captures keep their original binding rule. Fresh episode
    # projections always include task_id and need no generated-prose match.
    identity_matches = (public['task_id'] == grader.task['task_id'] if 'task_id' in public
                        else public.get('user_message') == grader.task['user_message'])
    if (not identity_matches
            or public.get('memories') != grader.task['memories']
            or type(public.get('user_message')) is not str
            or not public['user_message'].strip()):
        raise ValueError('Observed public task differs from the native graded task')
    checked()
    before_model_dispatch()
    backend = backend_factory(output/'transport')
    try:
        dispatched = False
        def before():
            nonlocal dispatched
            checked()
            if not dispatched:
                before_model_dispatch()
                dispatched = True
        grade = extract_and_grade(grader, public, natural['text'], output/'extraction', backend,
                                  before_dispatch=before)
        checked()
        listed_offer.publish(trace, output/'extraction', grade, mode='live', source_hashes=hashes)
        listed_offer.write(output/'completed.json', {'status': 'graded_and_published', 'requests': 1,
            'source_hashes_unchanged': True, 'grading_version': grade['grading_version'],
            'structured_claims_correct': grade['structured_claims_correct']})
        return grade
    finally:
        backend.close()


class SubscriptionTaskExtractor:
    """One tool-free subscription completion, with required quota guard."""
    def __init__(self, *, quota_guard, model='gpt-6.1-sol', reasoning_effort='low', lock_path=None):
        self.quota_guard = quota_guard
        self.transport = listed_offer.SubscriptionExtractor(model=model,
            reasoning_effort=reasoning_effort, lock_path=lock_path)

    def backend(self, path):
        self.quota_guard()
        backend = self.transport.backend(path)
        backend.before_dispatch = self.quota_guard
        return backend

    def __call__(self, grader, public, answer, output):
        backend = self.backend(Path(output).with_name('extractor-transport'))
        try:
            # The backend checks quota immediately before its transport dispatch.
            # Post-response source checks must not discard a completed grade merely
            # because the request itself reached the reserve floor.
            return extract_and_grade(grader, public, answer, output, backend)
        finally:
            backend.close()
